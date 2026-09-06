# Telegram Gateway

The Telegram Gateway is the sole interface between the Telegram Bot API and the rest of the AI agent system.
It translates Telegram messages and inline keyboard button interactions into internal queue messages (and vice versa), so no other container talks to Telegram directly.
It is also responsible for rendering inline keyboard buttons (Accept / Reject / Request Revision, mode selection) and for triggering the user's global session reset.

All application code runs inside a Docker container - there is no standalone (non-Docker) execution path.

## Infrastructure
Python application root is located at
```
telegram_gateway/telegram_gateway_application
```
- Python 3.12 (`python:3.12.4-slim` base image)
- Runs as a Docker container on the project's isolated bridge network (`chatbot-app-network`)
- Depends on RabbitMQ for internal messaging (see `utils_queue/queue.py`)
- Depends on Redis for task/draft/poll state (see `utils_redis/database.py`)
- Depends on the Telegram Bot API via a bot token (see `utils_telegram/`)

### Project Structure
- `main.py` - application entry point; configures logging, registers shutdown signal handlers, and drives startup/shutdown.
- `config.py` - centralised, environment-driven application configuration (see Environment Variables below).
- `utilities/initialise.py` - startup/shutdown orchestration (`initialise_application()` / `terminate_application()`).
- `utilities/logging_setup.py` - console and rotating file logging configuration.
- `utilities/utilities.py` - shared, dependency-free helpers (e.g. `ShutdownSignal`).
- `utilities/utils_gatekeeper/` - tracks repeated access attempts from unauthorised chats.
- `utilities/utils_queue/` - RabbitMQ connection lifecycle, inbound message dispatch, and delivery-failure reporting.
- `utilities/utils_redis/` - Redis connection lifecycle and task/draft/poll/pending-reset state storage.
- `utilities/utils_session/` - graceful `session_reset` handling: whitelist enforcement, defer-until-idle, crash-recovery resync, orchestrator ack, and the chat-facing reset notice.
- `utilities/utils_telegram/` - Telegram Bot API integration: inbound long-polling (`gateway_inbound.py`) and outbound sends (`gateway_outbound.py`), with supporting behaviours (typing indicator, draft keep-alive, poll debounce, inline keyboard buttons) under `utils_telegram/utilities/`.
- `data/logs/` - runtime log output (rotating daily, see Logging below).

### Application Lifecycle

#### Startup
`main.py` is the entry point:
1. Ensures `DATA_DIR` exists and configures logging (`setup_logging()`).
2. Registers `SIGINT`/`SIGTERM` handlers against a shared `ShutdownSignal`.
3. Calls `initialise_application()` (`utilities/initialise.py`), which:
   - Opens the RabbitMQ publish and consume connections, then starts the RabbitMQ consumer on its own background thread.
   - Opens the Redis connection.
   - Sweeps Redis for any draft (`close_orphaned_drafts()`) or poll (`close_orphaned_polls()`) left behind by a previous run - each is closed out immediately, since their in-memory timers don't survive a restart.
   - Resyncs any deferred `session_reset` that became resolvable while the gateway was down (`resync_pending_resets()`, `utils_session/session_reset_handler.py`) - run only after the two sweeps above have both completed.
   - Starts the periodic `PENDING_RESET_MAX_WAIT_SECONDS` backstop sweep (`start_pending_reset_ceiling_sweep()`) - see "`session_reset`" under Response Queue Message Payloads below.
   - Starts the Telegram long-polling loop (`poll_updates()`) on its own background thread.
4. The main thread then blocks on `_shutdown_event.wait()` - from this point on, the application runs entirely on background threads.

#### Runtime - two long-running loops

**RabbitMQ consumer loop** (`utils_queue/queue.py::queue_consume_task()`) - one iteration per message:
- Consumes from `Q_CHANNEL_IN` via `basic_consume`.
- Decodes the message body and passes it to `process_message()` (`utils_queue/message_handler.py`), which dispatches by `type` (poll/image/video/album/file/text/completed/error/session_reset) to the matching Telegram send call.
- Acks on success.
  On failure, nacks with requeue up to `Q_CONSUME_MAX_ATTEMPTS`, then drops.
  Reconnects automatically on a connection-level failure.

**Telegram long-polling loop** (`utils_telegram/gateway_inbound.py::poll_updates()`) - one iteration per `getUpdates` call:
- Calls `getUpdates` with the current `offset` and `TELEGRAM_ALLOWED_UPDATES`, holding the connection open for up to `TELEGRAM_POLL_TIMEOUT` seconds.
- For each update returned:
  - A `poll_answer` update is routed straight to `handle_poll_answer()` - it carries no `chat_id`, so it's resolved via its own `poll:<poll_id>` Redis mapping instead of the usual authorisation check.
  - Any other update has its `chat_id`/`user_id` extracted; a `chat_id` outside `TELEGRAM_ALLOWED_CHAT_IDS` gets tracked and, on first offence, one warning reply.
  - An authorised update is routed to `_handle_update()` - callback_query validation, media/draft staging, or a finalised task pushed to `Q_CHANNEL_OUT`.
- `offset` only advances once an update is fully handled - a failing update is retried up to `TELEGRAM_UPDATE_MAX_ATTEMPTS` times, blocking the rest of that batch meanwhile.

Beyond these two loops, several short-lived per-task/per-chat background threads are spawned dynamically as needed (not part of startup) - the typing indicator (`typing_indicator.py`), the draft keep-alive cycle (`image_draft_handler.py`), and the poll answer-collection timer (`poll_response_handler.py`) - each exits on its own once its job is done.

#### Shutdown
On `SIGINT`/`SIGTERM`, the signal handler sets the shared `ShutdownSignal`, waking the blocked main thread, which calls `terminate_application()`:
1. `stop_polling()` - signals the Telegram long-polling loop to exit (may take up to `TELEGRAM_POLL_TIMEOUT + TELEGRAM_CLIENT_TIMEOUT` if a request is already in flight).
2. `stop_pending_reset_ceiling_sweep()` - signals the `PENDING_RESET_MAX_WAIT_SECONDS` backstop sweep to stop (may take up to `PENDING_RESET_SWEEP_INTERVAL_SECONDS`).
3. `stop_queue_consumer()` - signals the RabbitMQ consumer to stop.
4. `close_rabbitmq_connection()` - closes both RabbitMQ channels/connections.
5. `close_redis_connection()` - closes the Redis client.

Dynamically spawned per-task threads are daemon threads and are not explicitly joined - they die with the process rather than being waited on.

## Getting Started
The Telegram Gateway container is intended to be managed by the project's root `./setup.sh` script (run from the `server-ai-chatbot-setup` root directory) and is not typically invoked directly.
You may use the helper script, `setup.sh`, for standalone `telegram_gateway` development.

### First-Time Setup
**Step 1:** Run helper script
```bash
./setup.sh
```
**Step 2:** Select option 1 to build and run the project
```
1
```

### Running the Project
Once built, use the same helper script, run from the root directory of the `telegram_gateway` project, for day-to-day container management.
```bash
./setup.sh
```

#### Useful Docker Commands
```bash
docker ps
docker images
docker rmi <docker-image-name>
docker start <docker-container-name>
docker stop <docker-container-name>
docker restart <docker-container-name>
```

## Documentation

### Logging
- Logged to both the console (stdout) and a rotating file at `telegram_gateway_application/data/logs/telegram_gateway.log`, rotated daily at midnight (or on reaching `LOG_MAX_SIZE_MB`), retained for `LOG_RETENTION_DAYS` days.
- Format: `%(asctime)s | %(levelname)s | %(name)s | %(message)s`.
- Verbosity is controlled by `LOG_LEVEL`.

| Level | Purpose |
|---------|---------|
| DEBUG | Detailed diagnostic information, e.g. an update ignored from an already-tracked unauthorised chat. |
| INFO | Normal application events, e.g. a message sent, a task pushed, a timer started or stopped. |
| WARNING | A recoverable issue, e.g. a retried send, a first unauthorised access attempt. |
| ERROR | A single operation failed and was dropped, e.g. a malformed payload. |
| CRITICAL | A systemic failure requiring attention, e.g. a `gateway_alert`, or a failed RabbitMQ/Redis connection. |

### Design Decisions
- **Long-polling, not webhooks** - `getUpdates` is used instead of a webhook, avoiding the need for a publicly reachable inbound endpoint.
- **Identity-blind agents** - `chat_id`/`user_id` are never forwarded to downstream agents directly; a `task_id` correlates back to identity via Redis, keeping the gateway the sole holder of chat identity.
- **`task_id` vs `session_id`** - `task_id` is the primary identifier: scoped to one request/response exchange, and deleted once that exchange's `completed`/`error` response is delivered. `session_id` is a separate, permanent identifier derived from `chat_id` (see `utils_redis/database.py::generate_session()`), mandatory on every message published to RabbitMQ in both directions, purely for segregation - deciding which chat a message belongs to - not for per-exchange correlation. It does not expire or rotate on its own; it is only cleared by an explicit, orchestrator-executed global session reset (`session_reset`, user-triggered via Telegram, see below), which also destroys every `task_id` still open under that chat, since the backend has already unwound whatever state it held for them.
- **Deferred, crash-resilient `session_reset`** - a `session_reset` never forcibly interrupts an open poll/draft-bearing task; it waits for every currently open `task_id` for that chat to naturally complete (`completed`/`error`) before applying, tracked durably in Redis (no TTL) so a gateway restart doesn't lose track of a reset still owed - see `utils_session/session_reset_handler.py` and "`session_reset`"/"`session_cleared`" below.
- **Media staged as a draft, not sent as a task immediately** - a photo/video/document arriving without a finalising instruction is held server-side as a draft, rather than forcing every upload to carry its instruction as a caption.
- **Two-tier delivery-failure reporting** - a rejected send is reported per-task (Tier 1, actionable by retrying differently) separately from a systemic outage (Tier 2, human intervention), so a consumer of `Q_CHANNEL_OUT` can distinguish "retry this differently" from "something is broken".
- **In-memory timers with a Redis backstop** - draft/poll keep-alive timers are deliberately in-memory rather than persisted/distributed, with Redis TTLs and startup sweeps (`close_orphaned_drafts()`/`close_orphaned_polls()`) as a safety net against a restart leaving state silently stuck.

### Limitations
- Only one pending draft is held per `chat_id` at a time - further media is rejected with a reminder rather than queued.
- `sendDocument` by URL only supports `.pdf`/`.zip` files (a Telegram Bot API constraint) - other file types are rejected, and multipart upload is not implemented.
- Draft/poll keep-alive progress is in-memory only - an application restart closes any in-flight draft/poll immediately rather than resuming it part-way through.
- Requires RabbitMQ and Redis to be reachable at startup; Redis, in particular, is required before Telegram polling begins.
- A deferred `session_reset` applies the instant its chat's open task(s) naturally clear, with no forewarning sent beforehand ("nothing is sent to the chat while a reset is only deferred/waiting" - see `session_reset` below) - in a conversation with a single message after a lull, the reset (and its notice) can land immediately behind that one reply. This is the deferred design behaving as specified, not a defect, but is worth being aware of - see `TODO.md` §8's open question on whether it needs its own mitigation.

### Redis Key Hierarchy

Every key `utils_redis/database.py` generates is namespaced by `chat_id` - Redis itself has no native parent/child key relationship (keys are flat strings, there is no cascading delete), so the grouping below is a conceptual model enforced entirely by application logic, chiefly `reset_session()`.

```text
chat_id
 │
 ├── session:<chat_id>                         -> session_id (str)
 │     Permanent (no TTL) - created once by _get_or_create_session(),
 │     cleared only by reset_session().
 │
 ├── session_tasks:<chat_id>                   -> SET of task_id
 │     Index only - created via create_task_mapping()'s sadd().
 │     │
 │     └── task:<task_id>                      -> {"chat_id", "user_id"} (json)
 │           TTL = REDIS_TASK_MAPPING_TTL_SECONDS.
 │           One key per open task; indexed above so reset_session()
 │           can find every task_id under this chat without a SCAN.
 │
 ├── session_polls:<chat_id>                   -> SET of poll_id
 │     Index only - created via create_poll_mapping()'s sadd().
 │     │
 │     └── poll:<poll_id>                      -> {"chat_id", "task_id",
 │                                                  "message_id", "user_id",
 │                                                  "option_ids"} (json)
 │           TTL = POLL_MAPPING_TTL_SECONDS.
 │           One key per open poll. Carries task_id back to the task
 │           that spawned it (a poll always has a parent task).
 │
 ├── draft:<chat_id>                           -> {"media_type", "media_url",
 │                                                  "text", "has_caption"} (json)
 │     TTL = DRAFT_MAPPING_TTL_SECONDS.
 │     At most one pending draft per chat_id (nx=True on write).
 │
 └── pending_reset:<chat_id>                   -> {"task_id", "created_at"} (json)
       No TTL. Only exists while a session_reset is deferred, waiting
       for has_open_tasks(chat_id) to go false.
```

| Key pattern | Value | TTL | Created by | Cardinality per chat |
|---|---|---|---|---|
| `session:<chat_id>` | session_id | None | `_get_or_create_session()` | 1 |
| `session_tasks:<chat_id>` | SET of task_id | None | `create_task_mapping()` | 1 (grows/shrinks) |
| `task:<task_id>` | `{chat_id, user_id}` | `REDIS_TASK_MAPPING_TTL_SECONDS` | `create_task_mapping()` | 0..N |
| `session_polls:<chat_id>` | SET of poll_id | None | `create_poll_mapping()` | 1 (grows/shrinks) |
| `poll:<poll_id>` | `{chat_id, task_id, message_id, user_id, option_ids}` | `POLL_MAPPING_TTL_SECONDS` | `create_poll_mapping()` | 0..N |
| `draft:<chat_id>` | `{media_type, media_url, text, has_caption}` | `DRAFT_MAPPING_TTL_SECONDS` | `create_chat_draft()` | 0..1 |
| `pending_reset:<chat_id>` | `{task_id, created_at}` | None | `set_pending_reset()` | 0..1 |

`session:<chat_id>` is the only permanent anchor - everything else is transient, either TTL-bound or deleted once resolved/completed. `session_tasks:<chat_id>`/`session_polls:<chat_id>` are pure indexes (pointers only, no state of their own), letting `reset_session()`/`has_open_tasks()` answer "what's open for this chat?" without a full keyspace `SCAN`. `task_id` bridges two branches: it's a member of `session_tasks:<chat_id>`, the id half of `task:<task_id>`, and also embedded inside `poll:<poll_id>` - so a poll always traces back to the task that created it.

#### `reset_session(chat_id)` cascade

`reset_session()` does not rely on any Redis-native cascading delete - it explicitly knows and deletes each key pattern above, by hand, all scoped to the same `chat_id`, under one `_get_chat_lock(chat_id)`:

```text
reset_session(chat_id)                         <- everything below keyed by the SAME chat_id
 │
 ├── read   session:<chat_id>                  -> captured as cleared_session_id (for the return value)
 ├── read   session_tasks:<chat_id>            -> SMEMBERS gives the set of task_ids
 │     └── for each task_id found:
 │           delete  task:<task_id>            <- individually, one DEL per member
 ├── delete session_tasks:<chat_id>            <- the index itself
 ├── delete session:<chat_id>                  <- the session_id value is gone now
 ├── delete draft:<chat_id>                    <- via delete_chat_draft()
 └── delete session_polls:<chat_id>            <- the index itself only (see note below)
```

- **`poll:<poll_id>` is not deleted here.** Unlike `task:<task_id>`, `reset_session()` only clears the `session_polls:<chat_id>` index itself - it does not read that set's members and delete each `poll:<poll_id>` individually. Any open poll is expected to already be closed out (mapping and index entry both removed) by the caller before this runs - see `utils_queue/message_handler.py::_handle_session_reset()`. This is a defensive final sweep of the index in case one was missed, not the primary close-out path; a leftover `poll:<poll_id>` would otherwise just expire via `POLL_MAPPING_TTL_SECONDS`.
- **`pending_reset:<chat_id>` is untouched by `reset_session()` entirely.** It's cleared independently by `clear_pending_reset()` in `utils_session/session_reset_handler.py`, on its own lifecycle - it records the reset request itself, so it can't be part of what the request it represents wipes.

### Environment Variables

#### Logging
| Variable | Purpose |
|-----------|---------|
| LOG_LEVEL | Root logger verbosity. |
| LOG_MAX_SIZE_MB | File size that triggers a log rotation, alongside the daily rotation. |
| LOG_RETENTION_DAYS | Number of rotated log files kept before deletion. |

#### Telegram Connectivity
| Variable | Purpose |
|-----------|---------|
| TELEGRAM_BOT_TOKEN | The bot's API token - must be set before running. |
| TELEGRAM_BOT_NAME | Persona name used in user-facing reply text. |
| TELEGRAM_API_BASE_URL | Base URL for the Telegram Bot API. |
| TELEGRAM_POLL_TIMEOUT | How long a `getUpdates` call holds the connection open awaiting new updates. |
| TELEGRAM_CLIENT_TIMEOUT | Request timeout applied on top of `TELEGRAM_POLL_TIMEOUT`/other API calls. |
| TELEGRAM_ALLOWED_CHAT_IDS | Whitelist of chat IDs permitted to interact with the bot. |
| TELEGRAM_ALLOWED_UPDATES | Update types requested from `getUpdates`. |
| TELEGRAM_UNAUTHORISED_CACHE_SIZE | Maximum number of unauthorised `chat_id`s tracked at once. |
| TELEGRAM_UNAUTHORISED_EVICTION_WINDOW_PERCENT | Portion of the tracked cache considered for eviction once full. |
| TELEGRAM_UNAUTHORISED_ACCESS_COUNT_CAP | Ceiling on the per-`chat_id` unauthorised access counter. |
| TELEGRAM_UPDATE_MAX_ATTEMPTS | Retry attempts for an update that fails to process before it is given up on. |

#### Session Reset
| Variable | Purpose |
|-----------|---------|
| SESSION_RESET_ALLOWED_CHAT_IDS | Whitelist of chat IDs permitted to trigger a `session_reset`. A `chat_id` outside this list is silently logged and dropped - no defer, no reset, no notice, no orchestrator ack. |
| PENDING_RESET_MAX_WAIT_SECONDS | Ceiling on how long a deferred `session_reset` may wait for its chat's open task_id(s) to naturally complete, before being force-applied regardless. |
| PENDING_RESET_SWEEP_INTERVAL_SECONDS | How often the ceiling above is checked by the background sweep. |

#### Telegram Delivery Behaviour
| Variable | Purpose |
|-----------|---------|
| TELEGRAM_TYPING_INTERVAL_MIN / TELEGRAM_TYPING_INTERVAL_MAX | Jittered interval range between "typing..." pings while a task is in progress. |
| TELEGRAM_TYPING_MAX_PINGS_MIN / TELEGRAM_TYPING_MAX_PINGS_MAX | Randomised cap range on typing pings per task, as ghost-task protection. |
| TELEGRAM_SEND_MAX_ATTEMPTS | Retry attempts for a send on connection failure/timeout. |
| TELEGRAM_SEND_RETRY_DELAY | Delay between send retry attempts. |
| TELEGRAM_CAPTION_MAX_LENGTH | Telegram's caption length cap, used to split an overlong caption into a follow-up message. |
| TELEGRAM_MESSAGE_MAX_LENGTH | Telegram's text message length cap. |
| TELEGRAM_CALLBACK_DATA_MAX_BYTES | Telegram's `callback_data` byte-length cap. |
| TELEGRAM_BUTTONS_MAX_PER_ROW | Telegram's inline keyboard row limit. |
| TELEGRAM_BUTTONS_MAX_TOTAL | Telegram's inline keyboard total button limit. |
| TELEGRAM_CALLBACK_TTL_SECONDS | How long a bot-issued button stays pressable before being treated as stale. |

#### Draft Handling
| Variable | Purpose |
|-----------|---------|
| DRAFT_CLOSE_SECONDS | Hard cap on a pending draft's total lifetime across all keep-alive cycles. |
| DRAFT_CYCLE_SECONDS | Length of one keep-alive cycle. |
| DRAFT_CYCLE_NOTICE_LEAD_SECONDS | How far before a cycle ends its keep-alive notice is sent. |
| DRAFT_TYPING_LEAD_SECONDS | How long the "typing..." indicator runs immediately before each cycle's notice/close. |
| DRAFT_MAPPING_TTL_SECONDS | Redis-side backstop TTL for a draft record, beyond the hard cap. |
| MEDIA_GROUP_DEDUPE_SECONDS | Window for deduping the "resend one at a time" reply across items of one album. |

#### Poll Handling
| Variable | Purpose |
|-----------|---------|
| TELEGRAM_POLL_ANONYMOUS | Whether polls are sent anonymously (not caller-configurable elsewhere - answers must be attributable). |
| POLL_TIMEOUT_SECONDS | How long a poll awaits its first answer before closing unanswered. |
| POLL_DEBOUNCE_INITIAL_SECONDS | Debounce window after a poll's first answer. |
| POLL_DEBOUNCE_SUBSEQUENT_SECONDS | Shortened debounce window after every further answer. |
| POLL_GLOBAL_CAP_SECONDS | Hard ceiling on a poll's total open time from creation, regardless of debounce resets. |
| POLL_MAPPING_TTL_SECONDS | Redis-side backstop TTL for a poll record, beyond the global cap. |

#### Error Handling
| Variable | Purpose |
|-----------|---------|
| GATEWAY_ALERT_FAILURE_THRESHOLD | Consecutive connection-level send failures required before a Tier 2 "unreachable" alert fires. |

#### RabbitMQ
| Variable | Purpose |
|-----------|---------|
| Q_HOST / Q_PORT / Q_VHOST | RabbitMQ connection target. |
| Q_USER / Q_PASSWORD | RabbitMQ credentials. |
| Q_CHANNEL_IN | Queue the gateway consumes inbound response tasks from. |
| Q_CHANNEL_OUT | Queue the gateway publishes tasks/events to. |
| Q_PUSH_MAX_ATTEMPTS / Q_PUSH_RETRY_DELAY | Retry behaviour when publishing a task. |
| Q_HEARTBEAT / Q_BLOCKED_CONNECTION_TIMEOUT | RabbitMQ connection health parameters. |
| Q_CONSUME_RETRY_DELAY | Delay before the consumer loop reconnects after a connection-level failure. |
| Q_CONSUME_MAX_ATTEMPTS | Retry attempts for a message that fails to process before it is dropped. |

#### Redis
| Variable | Purpose |
|-----------|---------|
| REDIS_HOST / REDIS_PORT / REDIS_DB | Redis connection target. |
| REDIS_USERNAME / REDIS_PASSWORD | Redis credentials, if the server requires authentication. Empty by default (no auth). |
| REDIS_SOCKET_CONNECT_TIMEOUT / REDIS_SOCKET_TIMEOUT | Bounds a Redis network-level stall so it fails fast into the existing retry logic instead of blocking indefinitely. |
| REDIS_SOCKET_KEEPALIVE | Whether the Redis client keeps its TCP connection alive between operations. |
| REDIS_HEALTH_CHECK_INTERVAL | How often the Redis client proactively pings the connection to detect a stale/dead socket. |
| REDIS_TASK_RETRY_DELAY / REDIS_TASK_MAX_ATTEMPTS | Retry behaviour for Redis reads/writes. |
| REDIS_TASK_MAPPING_TTL_SECONDS | Expiry for a `task_id` -> `chat_id`/`user_id` mapping. |

### Task Queue Payload (gateway -> backend)

Every task the gateway pushes to RabbitMQ (`Q_CHANNEL_OUT`) shares one shape, regardless of whether it originated from plain text, a finalised draft, or a poll answer:

```json
{
  "task_id": "...",
  "session_id": "...",
  "text": "...",
  "image_url": "...",
  "video_url": "...",
  "file_url": "...",
  "poll_answer": [0, 2]
}
```

- `task_id`: the primary identifier for this exchange - see "`task_id` vs `session_id`" in Design Decisions above.
- `session_id`: mandatory on every payload - resolved/lazily created via `generate_session()` (`utils_redis/database.py`) immediately before the message is built, from whichever of `chat_id`/`task_id` is available at the call site. Permanent per chat until an explicit `session_reset` - see "`task_id` vs `session_id`" in Design Decisions above.
- `text`: always present, `""` if the update carried no text.
- `image_url` / `video_url` / `file_url`: at most one is ever non-empty - the other two are always `""`.
  Resolved from Telegram's `getFile` endpoint, so the URL embeds the bot token and is only guaranteed valid by Telegram for at least 1 hour - the backend should download promptly rather than persist the URL.
- `poll_answer`: `null`/absent on a plain text/media task.
  Populated only on a poll answer push, with the responder's selected option indices (Telegram's `option_ids`, indices into the original poll's `options`).
  Carries no `user_id` - a poll only ever has one possible responder (this gateway's 1 user : 1 chat, private-chat-only model, where `chat_id` is itself the user's Telegram `user_id`), so `task_id` already resolves the poll back to its chat unambiguously.

#### Pending drafts (media without an instruction yet)

A photo/video/document arriving **without** a caption, or with one but no further text, is not immediately turned into a task - it is staged as a Redis-backed draft (one per `chat_id` at a time) until a text update finalises it:

- Media with a caption: the caption is stored as the draft's initial text.
  The next text update is appended onto it (`caption + " " + text`) and the task is pushed immediately.
- Media with no caption: the next text update becomes the task's `text` outright, and the task is pushed immediately.
- Further media (single item or album) arriving while a draft is already pending is **not** stored - the user is reminded about the existing draft instead.
- Album items (Telegram sets `media_group_id` on each item, delivered as separate updates) are never staged as a draft - the user is asked to resend them one at a time with individual instructions.
  The reply is sent once per album, not once per item.
- Whether the finalising text still applies to the pending media (e.g. the user changed their mind) is not decided by the gateway - it always attaches the draft's media to whatever text finalises it; that judgement call is left to the backend.

**Timeout**, per draft, is a repeating keep-alive cycle rather than a single countdown (see `utils_telegram/utilities/image_draft_handler.py`).
Each cycle is `DRAFT_CYCLE_SECONDS` long (5 min by default) and has exactly one "typing..." window, immediately before the one message a cycle sends:
- `DRAFT_CYCLE_SECONDS - DRAFT_CYCLE_NOTICE_LEAD_SECONDS - DRAFT_TYPING_LEAD_SECONDS` into the cycle (1 min by default): a "typing..." indicator starts.
- `DRAFT_CYCLE_SECONDS - DRAFT_CYCLE_NOTICE_LEAD_SECONDS` into the cycle (2 min by default): typing stops, a notice is sent asking if the user needs more time, with a "Give me a little while more" button attached.
- From there until `DRAFT_CYCLE_SECONDS` into the cycle (5 min by default): a further silent wait, with **no** typing indicator, watching for the button to be pressed.
  A press is acknowledged immediately but does **not** shorten this wait - it plays out in full regardless, same as if the button were never pressed.

**Whether the button was pressed at any point during that cycle is what decides what happens once the cycle's full 5 minutes has elapsed:**
- **Pressed at least once** → the draft proceeds to its next scheduled cycle, which repeats the same pattern from its own start (its own 1 min typing, 2 min notice, silent wait to its own close point).
- **Never pressed** → the draft closes at the end of this cycle, the same way an unanswered final cycle does - it does **not** silently continue to the next scheduled cycle.

The final cycle's notice has no button at all, since there's no further cycle to reach - it always closes at its own end, regardless of response.
The number of cycles is capped by `DRAFT_CLOSE_SECONDS / DRAFT_CYCLE_SECONDS` (11 cycles at the defaults above, i.e. 55 min total - kept comfortably under Telegram's 1-hour file link guarantee), but that ceiling is only reached if the button is pressed on every single cycle along the way; a draft that's never answered at all closes after just its first cycle (5 min by default).

The keep-alive cycle above is **in-memory only** - it does not survive an application restart, though the Redis-backed draft record itself does (it has its own TTL, `DRAFT_MAPPING_TTL_SECONDS`, slightly beyond `DRAFT_CLOSE_SECONDS`, as a backstop).
Since the loop's progress isn't persisted, a restart would otherwise leave a draft silently pending with no further notices and no close message, for up to that TTL.
To avoid this, `close_orphaned_drafts()` sweeps Redis for any leftover drafts on startup, before polling resumes, and closes each one out immediately (draft deleted, close message sent) rather than attempting to resume it part-way through a cycle.

#### Poll answers

A poll (`type: "poll"`, see below) is always sent non-anonymous (`TELEGRAM_POLL_ANONYMOUS`, not caller-configurable) so an answer can be attributed to its responder.
See `utils_telegram/utilities/poll_response_handler.py`.

Unrelated chat messages **do not** interact with an open poll at all - the bot is expected to answer them independently while the poll keeps running in the background.
There is no "one poll per chat" restriction enforced by the gateway.

Each poll goes through two phases, governed by one timer:

- **Awaiting first answer** (`POLL_TIMEOUT_SECONDS`, 5 min by default): if nobody answers in time, the poll is closed with a chat message and a `poll_timed_out` event (see below) is pushed instead of an answer.
- **Debouncing**, once answered (`POLL_DEBOUNCE_INITIAL_SECONDS`, 2 min by default, shortened to `POLL_DEBOUNCE_SUBSEQUENT_SECONDS`, 1 min, on every further answer): waits for the responder to stop changing their answer before compiling and pushing the latest one - capped overall by `POLL_GLOBAL_CAP_SECONDS` (8 min by default, comfortably under Telegram's own 10 min native poll auto-close ceiling) from poll creation, regardless of how many times debouncing resets.
  No chat message is sent on this path - an answer was already collected, so there's nothing to apologise for.

Whether a closure pushes a `poll_answer` or a `poll_timed_out` event depends solely on whether the poll was ever answered, not on why it's closing - a natural debounce expiry, the global cap being reached mid-debounce, and a startup orphan-sweep closure (see below) all resolve identically.

#### `poll_timed_out` (gateway -> backend)

Pushed instead of an answer when a poll's "awaiting first answer" phase elapses with nobody having answered at all - closing the gap where the backend would otherwise be left with no signal that the poll ever ended.
```json
{"task_id": "...", "session_id": "...", "type": "poll_timed_out"}
```
- Routed by `task_id` exactly the same way a real `poll_answer` already is - to whichever agent currently owns that task. The orchestrator needs no poll-specific logic of its own for this; it's the same task_id-keyed forwarding it already does for every other response.
- The decision belongs to that agent (re-ask, treat as declined, escalate, or simply send back `completed`/`error`) - not to the orchestrator, and not to this gateway.
- If nothing ever acts on it (agent bug, crash, dropped message), a `session_reset` deferred behind that `task_id` doesn't wait forever either - see `PENDING_RESET_MAX_WAIT_SECONDS` under `session_reset` below.

The timer above is **in-memory only** - it does not survive an application restart, though the Redis-backed poll record does (its own TTL, `POLL_MAPPING_TTL_SECONDS`, slightly beyond `POLL_GLOBAL_CAP_SECONDS`, refreshed on every answer so it always reflects the latest one).
To avoid a poll sitting open indefinitely with an uncollected answer, `close_orphaned_polls()` sweeps Redis for any leftover poll on startup, before polling resumes, and closes each one out immediately - pushing whatever answer it already has, same as any other closure path.

### Delivery Failure Events (gateway -> backend)

When a Telegram send fails, the gateway does not simply stay silent about it - it pushes one of two event types onto `Q_CHANNEL_OUT`, depending on whether the failure is specific to one task or systemic (see `utils_queue/error_handling.py`).
Both share the type discriminator convention of the other gateway -> backend payloads above.

#### `delivery_failed` (Tier 1 - per-task, actionable)

A specific send was rejected by Telegram (e.g. an invalid `parse_mode`, a malformed poll), or failed local validation before ever reaching Telegram (e.g. an oversized message, an invalid inline keyboard).
Reported per `task_id`, since the backend/orchestrator can react by retrying that same task differently - a different content type, a shorter message, and so on.

```json
{
  "task_id": "...",
  "session_id": "...",
  "type": "delivery_failed",
  "tier": 1,
  "attempted_type": "image | video | album | file | text | poll",
  "status_code": 400,
  "reason": "..."
}
```
- `session_id`: mandatory, resolved via `generate_session()` the same as the Task Queue Payload above.
- `attempted_type`: which send was attempted - `image` / `video` / `album` / `file` / `text` / `poll`.
- `status_code`: Telegram's HTTP status code, if the request reached Telegram; `null` if caught by local validation before any request was sent.
- `reason`: Telegram's own error description, or the local validation failure message.
- Never raised for a connection-level failure (unreachable/timeout) or a 401 - those carry no "wrong tool" signal for this specific task and are reported as `gateway_alert` instead.

#### `gateway_alert` (Tier 2 - systemic, not tied to any task)

Telegram is unreachable altogether (connection/timeout exhausted after `TELEGRAM_SEND_MAX_ATTEMPTS` retries), or the bot token itself is invalid/revoked (`401`/`404`).
No per-task retry or different tool fixes either - human intervention is the only useful response.

```json
{
  "task_id": null,
  "session_id": null,
  "type": "gateway_alert",
  "tier": 2,
  "reason": "unreachable | unauthorized | not_found",
  "status_code": 401
}
```
- `task_id` / `session_id`: always `null` - this isn't about any single task or chat.
- `reason`: `unauthorized` (a 401 was returned), `not_found` (a 404 was returned - see below), or `unreachable` (connection failed/timed out across every retry).
- `status_code`: Telegram's HTTP status code if one was returned (`401`/`404`); `null` for `unreachable`.
- `unauthorized`/`not_found` fire immediately, bypassing the threshold below.
  Every endpoint the gateway calls is a fixed, hardcoded path, so a 404 here can't mean "wrong URL" - like a 401, it means the token doesn't resolve to a real bot (deleted/revoked/malformed).
  Both are permanent config issues, not blips, so retries won't fix either.
- `unreachable` only fires once `GATEWAY_ALERT_FAILURE_THRESHOLD` (5 by default) consecutive send failures have accumulated across *all* sends - a single blip is expected noise, not a systemic signal.
- Either way, fires **once per incident**: a successful send afterwards re-arms it, so an ongoing outage doesn't spam one alert per failed message.
- Always logged at `CRITICAL` first, regardless of whether the push to `Q_CHANNEL_OUT` itself succeeds - so the alert stays visible via infra/log-based monitoring even if RabbitMQ is part of what's broken.

**Out of scope:** disk/hardware-level failures (a true application-layer gap) are not detected or reported here - they rely on infrastructure-level restart policies/monitoring instead.

### Session Reset Events (gateway -> backend)

#### `session_cleared`

Pushed once a `session_reset` (see below) has actually taken effect for a chat - the orchestrator's positive confirmation that this specific `session_id` is gone on the gateway side. See `utils_session/session_reset_handler.py::_push_session_cleared()`.

```json
{"task_id": null, "session_id": "...", "chat_id": 123456789, "type": "session_cleared"}
```
- `task_id`: always `null` - this is a session-level ack, not tied to any one task.
- `session_id`: the `session_id` that was just cleared.
- `chat_id`: included directly (unlike every other payload above) - a `session_reset` triggered for one chat can end up clearing several, so each affected chat gets its own `session_cleared` event, and this is the only place identifying which one.
- Only pushed if the chat actually had a `session_id` to clear - a reset applying to a chat with no existing session has nothing to ack.
- Fires once, at the moment a reset actually applies - whether that's immediately or after being deferred (see `session_reset` below), the ack path is identical either way.

### Response Queue Message Payloads

Messages consumed by the gateway from the response queue (agent -> gateway) all share a common envelope:

```json
{"task_id": "...", "session_id": "...", "type": "<type>", ...}
```

`task_id` is required on every payload and correlates back to a `chat_id`/`user_id` stored in Redis - responses never carry chat/user identity directly, keeping agents identity-blind.
`session_id` is likewise mandatory on every payload (see "`task_id` vs `session_id`" in Design Decisions above) - the gateway itself resolves delivery via `task_id`/Redis regardless, so `session_id` here is primarily for the backend/orchestrator's own routing between multiple sessions/bots.
`type` selects which of the payload shapes below applies.
Consuming any payload, regardless of `type`, also stops that `task_id`'s outbound "typing..." indicator if one is active (see `utils_telegram/utilities/typing_indicator.py`) - this is not itself a distinct `type`.

#### `poll`
Maps to Telegram's `sendPoll`.
```json
{
  "task_id": "...",
  "type": "poll",
  "question": "...",
  "options": ["...", "..."],
  "allows_multiple_answers": false
}
```
- `question`: 1-300 characters.
  If missing, the whole poll is dropped and logged.
- `options`: 1-12 items, each 1-100 characters.
  Null/empty entries are filtered out; the poll is sent with whatever remains.
- `is_anonymous` is not accepted here - always `TELEGRAM_POLL_ANONYMOUS` (`false` by default), not caller-configurable.
  See "Poll answers" above for how an answer is collected and pushed back.

#### `image`
Maps to Telegram's `sendPhoto`.
```json
{"task_id": "...", "type": "image", "url": "...", "caption": "..."}
```
- `caption`: optional, see caption length note below.

#### `video`
Maps to Telegram's `sendVideo`.
```json
{"task_id": "...", "type": "video", "url": "...", "caption": "..."}
```
- `caption`: optional, see caption length note below.

#### `album`
Maps to Telegram's `sendMediaGroup`.
```json
{
  "task_id": "...",
  "type": "album",
  "items": [
    {"type": "photo", "url": "..."},
    {"type": "video", "url": "..."}
  ]
}
```
- `items`: any number of entries.
  Telegram's `sendMediaGroup` only accepts 2-10 per call, so the gateway handles the edge cases automatically:
  - 1 item: sent via `sendPhoto`/`sendVideo` instead of a media group.
  - More than 10: split into multiple `sendMediaGroup` calls of up to 10 each - if the final chunk has only 1 item, it falls back the same way.
- Each item's `type` must be `photo` or `video` - photos and videos can be mixed freely.
- Each item must have a non-empty `url` and a `type` of exactly `photo` or `video` - if any item fails this, the whole album is dropped and logged rather than sending a partial/broken result.
- No caption support - Telegram sets captions per item, not accepted here.
- No inline keyboard/buttons support on this type - Telegram's `sendMediaGroup` does not accept `reply_markup` at all.

#### `file`
Maps to Telegram's `sendDocument`.
```json
{"task_id": "...", "type": "file", "url": "...", "caption": "..."}
```
- `caption`: optional, see caption length note below.
- `url` is fetched by Telegram server-side, same as `image`/`video` - **but Telegram only supports sending a document by URL for `.pdf` and `.zip` files.**
  Any other file type sent this way is rejected; a direct multipart upload would be required instead, which is not implemented.

##### Caption length (`image`/`video`/`file`)
Telegram caps captions at 1024 characters and rejects the entire send if exceeded, rather than truncating it.
The gateway handles this automatically: the caption is cut to the limit for the media send, and anything beyond that is sent as a separate follow-up `sendMessage` instead of being lost or causing the send to fail.

#### `text`
Maps to Telegram's `sendMessage`.
```json
{
  "task_id": "...",
  "type": "text",
  "text": "...",
  "buttons": [
    [
      {"text": "Accept", "purpose": "task_review", "payload": {"decision": "accept"}},
      {"text": "Reject", "purpose": "task_review", "payload": {"decision": "reject"}}
    ]
  ]
}
```
- `buttons`: optional.
  Rows of inline keyboard buttons, each `{"text": "...", "purpose": "...", "payload": {...}}`.
  - `purpose`: caller-defined tag, read back when the press is validated so the gateway knows how to route it.
  - `payload`: optional caller-defined context retrieved alongside the press.
  - Each button is registered with a bot-issued `callback_data` token (see `utils_telegram/utilities/button_prompt_handler.py`) - the agent never supplies `callback_data` directly.
  - A button that fails to register, or a keyboard that fails Telegram's size limits, is dropped; the message still sends as plain text.

#### `completed`
Terminal marker - no further payloads are expected for this `task_id`.
```json
{"task_id": "...", "type": "completed"}
```
Triggers cleanup only: deletes the `task_id` mapping from Redis (the typing indicator is already stopped for every payload, per above).

#### `error`
Signals the task ended abnormally (e.g. an agent's token budget was exhausted).
```json
{"task_id": "...", "type": "error", "error_type": "token_exhausted", "message": "300"}
```
- `error_type`: short machine-readable code. Currently recognised:
  - `token_exhausted` - sends a fixed persona message.
    `message` is reused (not a separate field) to carry `nap_duration_left` - seconds **remaining**, a countdown, not a fixed total - included in the reply if present and numeric; omitted otherwise.
  - Any other value (including `unknown`) - `message` is treated as free text and sent back to the user, wrapped in a persona-styled HTML message (Telegram `parse_mode` `HTML`, `message` is HTML-escaped before being embedded).
- Same cleanup as `completed`, plus a user-facing notification.

#### `session_reset`
Requests a chat's permanent `session_id`, and every `task_id` still open under it, be wiped - the backend/agent-side counterpart of a user-triggered global session reset. See `utils_session/session_reset_handler.py`.
```json
{"task_id": "...", "type": "session_reset"}
```
- `task_id` here is only used to resolve `chat_id` (same as any other payload) and to track a deferred reset (see below) - it is not itself preserved.
- Execution authority belongs to the orchestrator, not this gateway - the gateway only carries out a reset already decided upstream, triggered by the user via Telegram.
- **Whitelist first**: a `chat_id` outside `SESSION_RESET_ALLOWED_CHAT_IDS` is silently logged and dropped - no defer, no reset, no notice, no ack of any kind.
- **Deferred, not forced**: if the chat currently has any open `task_id` (`session_tasks:<chat_id>`), the reset does not apply yet - it's stored durably in Redis (`pending_reset:<chat_id>`, no TTL) and applied automatically the moment that chat's last open task naturally completes (`completed`/`error`) - no poll/draft is ever forcibly interrupted. If the chat has no open task_id, it applies immediately.
- A gateway restart does not lose track of a reset that's still owed - `resync_pending_resets()` re-checks every deferred reset on startup and applies any that already became resolvable while the gateway was down (see Startup above).
- **Bounded wait, not indefinite**: a deferred reset isn't left waiting forever on a `task_id` that's never going to send `completed`/`error` (e.g. a bug, a crash, a dropped message, or - for a poll specifically - see `poll_timed_out` above). Once a pending reset has been waiting longer than `PENDING_RESET_MAX_WAIT_SECONDS` (1h by default), it's force-applied regardless of whether its task_id(s) are still technically open - checked every `PENDING_RESET_SWEEP_INTERVAL_SECONDS` by a background sweep (`enforce_pending_reset_ceiling()`), and also on startup as part of `resync_pending_resets()`. `reset_session()` deletes every `task_id` still indexed under the chat unconditionally either way, so nothing needs special "abandoned" handling beyond the normal reset.
- Once applied, see `utils_redis/database.py::reset_session()` for exactly what gets deleted (`session:<chat_id>`, `session_tasks:<chat_id>`, every `task:<task_id>` indexed under it, the chat's pending draft, and its poll indexing) - the chat's draft keep-alive timer (in-memory, not covered by the Redis deletion) is also stopped at this point, and (defensively, only relevant if `PENDING_RESET_MAX_WAIT_SECONDS` is misconfigured shorter than a poll's own maximum lifetime) any poll still open for the chat is closed out silently, the same way a reset always has.
- Applying a reset always does two more things, for **every** `chat_id` whose session actually gets cleared - not just the `chat_id` that triggered it, since one `session_reset` may end up affecting several chats: pushes a `session_cleared` event (see below) and sends a fixed, configurable chat notice (`RESET_NOTICE_MESSAGE` in `session_reset_handler.py`; no-op while unset). Nothing is sent to the chat while a reset is only deferred/waiting.

## Project Architecture

The diagram below traces the gateway's process lifecycle - startup, its two long-running loops, and shutdown - at a whiteboard level.

```mermaid
flowchart TD

    Start(["Process start (main.py)"]) --> Setup["Ensure DATA_DIR + setup_logging()"]
    Setup --> Signals["Register SIGINT/SIGTERM -> ShutdownSignal"]
    Signals --> Init["initialise_application()"]

    subgraph INIT["Startup (initialise.py)"]
        Init --> RMQ["initialise_rabbitmq_connection()"]
        RMQ --> Consumer["start_queue_consumer() - spawn thread"]
        Consumer --> RedisInit["initialise_redis_connection()"]
        RedisInit --> Drafts["close_orphaned_drafts()"]
        Drafts --> Polls["close_orphaned_polls()"]
        Polls --> Resync["resync_pending_resets()"]
        Resync --> Sweep["start_pending_reset_ceiling_sweep() - spawn thread"]
        Sweep --> LongPoll["spawn poll_updates() thread"]
    end

    LongPoll --> Block(["Main thread blocks on shutdown_event.wait()"])

    Consumer -.-> QLoop
    LongPoll -.-> TLoop

    subgraph QLoop["RabbitMQ consumer loop (per message)"]
        Q1["basic_consume Q_CHANNEL_IN"] --> Q2["process_message() dispatches by type"]
        Q2 --> Q3{"Handled OK?"}
        Q3 -- yes --> Q4["ack"]
        Q3 -- no --> Q5["nack + requeue, up to Q_CONSUME_MAX_ATTEMPTS"]
        Q4 --> Q1
        Q5 --> Q1
    end

    subgraph TLoop["Telegram long-poll loop (per getUpdates call)"]
        T1["getUpdates(offset, timeout=TELEGRAM_POLL_TIMEOUT)"] --> T2{"poll_answer update?"}
        T2 -- yes --> T3["resolve via poll:&lt;poll_id&gt; mapping"]
        T2 -- no --> T4{"chat_id authorised?"}
        T4 -- no --> T5["track/deny + one warning reply"]
        T4 -- yes --> T6["_handle_update(): text/media/draft/callback_query"]
        T3 --> T7["advance offset"]
        T5 --> T7
        T6 --> T7
        T7 --> T1
    end

    Block -- "SIGINT/SIGTERM" --> Term["terminate_application()"]
    Term --> S1["stop_polling()"]
    S1 --> S1b["stop_pending_reset_ceiling_sweep()"]
    S1b --> S2["stop_queue_consumer()"]
    S2 --> S3["close_rabbitmq_connection()"]
    S3 --> S4["close_redis_connection()"]
    S4 --> Exit(["Process exit"])
```
