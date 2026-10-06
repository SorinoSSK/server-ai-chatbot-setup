# TODO Record for Bot Sanctuary

Tracks the design goals of `bot_sanctuary`, and where each one stands. It is the successor to `bot_orchestrator`'s routing role, merged with the AI agent pipeline into one Python application: RabbitMQ consumption from `telegram_gateway`, per-session threading, the multi-agent "Call" pipeline, the LLM provider interfaces, tool access, and error and alert routing. `bot_orchestrator` is retired and removed, and its planned responsibilities (SMTP alerting, session-reset broadcast, task routing, outbound payload validation) are absorbed here. Section numbers 1 to 6 are referenced from `telegram_gateway/CODE_TODO.md` and elsewhere, so they are kept stable. This record was regrouped from an earlier chronological version into the status-table layout used by the `V-Project-Multimedia-Application` TODO files. Decisions, rejected alternatives and history are kept inside each section, and the earlier version remains in git history.

**Status key:** 🟢 Closed = finished. ⚪ Superseded = replaced by a later design, kept for history. 🟡 Ongoing = partly done, work remains. 🔴 Open = not started or undecided.

**Priority key (my proposal, change freely):** **P1** = do next: a live bug, a feature that does not work, or something other work waits on. **P2** = should be done soon: a known gap with limited impact or a workaround. **P3** = optional, or whenever convenient.

**Action key:** **DECIDE** = needs your decision. **BUILD** = implementation work. **TEST** = verify, change nothing unless it fails. **CHECK** = confirm a fact. **DOC** = documentation only. Every unresolved bullet in a section starts with 🔴, then its priority and action, for example `🔴 **P2 · DECIDE** [BS-07]`. P1 and P2 items also carry an ID that matches the action list below. Resolved questions are struck through or moved to Closed and Decided.

| # | Topic | Status | Top open priority | Next step |
|---|-------|--------|-------------------|-----------|
| 1 | Container and runtime | 🟡 Ongoing | P2 | Verify the multi-arch build on both targets (BS-19) |
| 2 | Authentication and provider credentials | 🟡 Ongoing | P3 | Decide the pending-authentication behaviour |
| 3 | RabbitMQ and threading model | 🟡 Ongoing | P3 | Decide the stray-message-after-clear risk |
| 4 | Error handling and alerting (SMTP) | 🟡 Ongoing | P3 | Make SMTP and Redis calls non-blocking |
| 5 | Agent "Call" model | 🟡 Ongoing | P1 | Apply the `allowed_tools` fix (BS-01), then the Calls contract (BS-04) |
| 6 | Workspace and repository access | 🟡 Ongoing | P2 | Phase 3, read-only code tools for the agents (BS-06) |
| 7 | Standing open items | 🔴 Open | P2 | Decide each item, starting with BS-18 |
| 8 | Global session clear and `bot_started` | 🟡 Ongoing | P2 | Close the three recorded gaps, publish backstop first (BS-09) |
| 9 | Timed reset, timezone and central time | 🟢 Closed | none | None |
| 10 | Persistent Claude client left uncleaned after a timeout | 🟢 Closed | P2 | Decide whether to raise the timeout (BS-10) |
| 11 | Token-usage cost review | 🟡 Ongoing | P1 | Decide whether to set `SESSION_RESET_TIME` (BS-02) |
| 12 | Non-text payload fields in `_process_batch()` | 🟢 Closed | P2 | Read the image, video and file URLs (BS-03) |
| 13 | Persona and library-file loading | 🟡 Ongoing | P2 | Verify the Claude API path (BS-12), then tidy the helper style |
| 14 | Claude API-path timeout | 🟢 Closed | P2 | Confirm the installed SDK version (BS-13) |
| 15 | Qwen interface | 🟡 Ongoing | P3 | Confirm fixed versus sliding TTL |
| 16 | DeepSeek interface | 🟡 Ongoing | P2 | Decide the timeout for the high-effort model (BS-14), then a real call (BS-15) |
| 17 | API retry and billing errors | 🟡 Ongoing | P2 | Claude billing (BS-16), and test retry and billing (BS-17) |
| 18 | Codex chat file and OAuth | 🔴 Open | P2 | Restrict the subprocess environment (BS-20) before enabling Codex |

**Action list: everything still to resolve, highest priority first.** The ID on each row is repeated on the matching bullet in its section. Items marked "blocked by" cannot start until the earlier one is done.

| ID | Pri | Action | What | § |
|----|-----|--------|------|---|
| BS-01 | P1 | CHECK, then BUILD | Confirm whether `allowed_tools` was applied. If not, apply it in `claude_session_service.py` and `claude_interface.py`. `WebSearch` is otherwise denied locally | 5 |
| BS-02 | P1 | DECIDE | Set `SESSION_RESET_TIME` (a `config.ini` value, no code). Sessions otherwise grow all day and every reply re-reads the whole history | 11 |
| BS-03 | P2 | BUILD | Read `image_url`, `video_url` and `file_url` in `_extract_item_text()`. Needed for the media `telegram_gateway` now sends with a caption to be of any use | 12 |
| BS-04 | P2 | BUILD | Bring `architect`, `coder`, `review` and `documentation` Calls to `handle(prompt, session_dir)` and the dispatcher's contract | 5 |
| BS-05 | P2 | BUILD | Phase 6: read the `coding_allowed` tag and keep a non-whitelisted task on Chat | 5 |
| BS-06 | P2 | BUILD | Let the agents read a pulled repository with generic read-only tools (blocked by BS-04) | 6 |
| BS-07 | P2 | DECIDE | What to do when a pulled repository was force-pushed (`git pull --ff-only` fails) | 6 |
| BS-08 | P2 | DOC | Document `GIT_HOSTS`, `data/git_ssh/` and the deploy-key step in `README.md`; add tests for the classifier, `sync_git_hosts()` and the pull path | 6 |
| BS-09 | P2 | BUILD | Add a backstop for a failed accept or reject publish of a session clear request | 8 |
| BS-10 | P2 | DECIDE | Raise `AGENT_QUERY_TIMEOUT_SECONDS`? Long tool chains already hit 120 seconds | 10 |
| BS-11 | P2 | TEST | Measure token usage after the recent fixes to confirm the expected drop | 11 |
| BS-12 | P2 | TEST | Confirm `system_prompt`, `tools` and `model` reach the Claude API path and `WebSearch` is permitted (blocked by BS-01) | 13 |
| BS-13 | P2 | CHECK | Run `pip show claude-agent-sdk` in the container and confirm 0.2.152 | 14 |
| BS-14 | P2 | DECIDE | Timeout for `deepseek-v4-pro` at high effort. The shared setting also moves Claude's | 16 |
| BS-15 | P2 | TEST | One real chat call through DeepSeek: is `reasoning_effort` honoured, and what is the latency | 16 |
| BS-16 | P2 | BUILD | Cover Claude's `billing_error` (`AssistantMessage.error`) as `billing_exhausted` | 17 |
| BS-17 | P2 | TEST | Stub 503, 503, 200, a permanent 401 and a socket timeout; confirm the 402 and 429 billing signals on a real account | 17 |
| BS-18 | P2 | DECIDE | Distinguish "provider unavailable" from quota for Claude and Codex failures (today all become `call_pipeline_unavailable`) | 7 |
| BS-19 | P2 | TEST | Build the multi-arch image and confirm real wheels and binaries on both targets | 1 |
| BS-20 | P2 | BUILD | Pass Codex a minimal subprocess environment, before Codex is ever enabled | 18 |

**P3, optional or whenever convenient:** §2 pending-authentication behaviour; §3 stray message after a clear; §4 non-blocking SMTP and Redis, calendar-day cooldown, fail-open; §5 Phase 5 native tool-calling, Phase 7 observability, Rukia tone, `claude_session_service.py` documentation; §6 HTTPS for private repositories, push, `ssh-keygen` check, review-server stub; §7 session registry, task classification, access-tier field, auth retry interval; §8 busy-session retirement, stray-message risk, graceful-versus-immediate check; §10 repeat-timeout test; §11 idle-based reset; §12 `poll_timed_out` prompt; §13 helper style, dead `load_persona` call, `coder` filename, Chat-hardcoded persona; §14 effective-budget asymmetry; §15 Qwen TTL, error shape, tools, marker robustness; §16 keep-alive, `finish_reason`, usage logging, tool boilerplate, tools, `IncompleteRead`; §17 billing phases 3 and 4, Arrearage, error as assistant text, README error types; §18 Codex field wiring, `--skip-git-repo-check`, `--ephemeral`, read isolation, OAuth hardening and its questions.

---

## 1. Container and runtime

**Status:** 🟡 Ongoing

**In short:** One `python:3.12.4-slim` image runs the app. The `claude` and `codex` CLIs are installed for administrator login, and `claude-agent-sdk` is used programmatically. Each provider has its own config folder under `bot_directory`.

**Closed**
- 🟢 Base image `python:3.12.4-slim` (`Dockerfile.dev` and `Dockerfile.prod`), not a generic Linux and Node image.
- 🟢 `claude` CLI via the native installer (Node-free, architecture-detecting), installed into `bot_sanctuary_usr`'s home after the `USER` switch so the app and an administrator's `docker exec` share one installation. It is for manual and admin use only (`claude setup-token`, `claude doctor`).
- 🟢 `codex` CLI via its native installer, same shape. It started as login plumbing only and is now also invoked programmatically through `codex exec`. No OpenAI Python SDK was added.
- 🟢 `claude-agent-sdk==0.2.152` via pip. Wheels exist for `manylinux_2_17_aarch64` (Raspberry Pi) and x86_64.
- 🟢 `bot_directory` is one subfolder per provider, each mounted to that provider's config directory: `claude` to `~/.claude`, `codex` to `~/.codex`, `qwen` to `~/.qwen`, `deepseek` to `~/.deepseek`. This is in `compose.dev.yml` and the exposed branch of `bs_dev_run_docker()`. The old standalone `codex_directory` is retired, with no automated migration.
- 🟢 `qwen` and `deepseek` have no CLI and none is planned. DeepSeek has no OAuth and no official CLI, and `qwen-code`'s free OAuth tier was discontinued on 2026-04-15. Both are called by REST. Their folders are kept exposed by explicit instruction as inert placeholders keeping one folder per provider.

**Open**
- 🔴 **P2 · TEST** [BS-19] Build as a multi-arch image (Buildx, `linux/amd64,linux/arm64`). Verify on both targets that the SDK resolved a real wheel rather than a source-dist with no bundled binary, and that both native installers resolved a real binary.

**Decided**
- Relocating state with `CLAUDE_CONFIG_DIR` was superseded by the per-provider bind mounts.

**Known limitations**
- `~/.qwen` is confirmed as `qwen-code`'s directory. `~/.deepseek` is an unconfirmed placeholder chosen by convention and should be corrected if a DeepSeek CLI is ever adopted.

---

## 2. Authentication and provider credentials

**Status:** 🟡 Ongoing

**In short:** An administrator authenticates personally and the app does not resolve credentials from disk. Each provider has its own access type and token, and a dispatcher routes a call to the right provider and endpoint.

**Closed**
- 🟢 What is actually built is simpler than the first draft. The administrator generates a long-lived token once (`claude setup-token`) and puts it in `config.ini` as `CHATBOT_LLM_<PROVIDER>_TOKEN`, which reaches the container as an environment variable. `~/.claude` and `~/.codex` are persisted only so an administrator's CLI login survives a container recreation.
- 🟢 `codex login` inside the container writes `~/.codex/auth.json`, and the app consumes it when the Codex access type is `OAUTH`.
- 🟢 Configuration history: a single `LLM_TYPE`, `LLM_ACCESS_TYPE` and `LLM_TOKEN` (first named `LLM_OAUTH_TOKEN`) was retired. It is replaced by `LLM_CHAT_TYPE`, a `LLM_<CALL>_TYPE` per Call (Architect, Coder, Review and Documentation fall back to `LLM_CHAT_TYPE`), and a `LLM_<PROVIDER>_ACCESS_TYPE` and `LLM_<PROVIDER>_TOKEN` pair per provider. DeepSeek and Qwen default to `"API"`. The plumbing is in `compose.dev.yml`, `bs_dev_run_docker()` (both branches), the root `setup.sh` masked list and `config_sample.ini`.
- 🟢 `utilities/utils_agents/` holds one interface per provider (later moved under `interfaces/`, with persistent platforms under `services/`) and a provider-agnostic `agent_interface.py`. Each interface has `query_via_oauth()` and `query_via_api()`, both `async`, both uniform across providers so the dispatcher needs no capability check.
  - `claude_interface.py` uses the Agent SDK.
  - `codex_interface.py` shells out to `codex exec`. The OAuth path strips `OPENAI_API_KEY` from the subprocess environment, and the API path bridges the token into it.
  - `deepseek_interface.py` and `qwen_interface.py` post directly through `urllib` inside `asyncio.to_thread()`, so no dependency was added. The `openai` package was considered and rejected. Their `query_via_oauth()` is a logged "not supported" stub.
- 🟢 `query_llm(llm_type, prompt, ...)` takes the provider explicitly, resolved by `_resolve_provider()`. `test_llm_tokens()` runs at startup for every provider with a configured token and logs an info line for those without one.
- 🟢 `setup-token` was chosen over `/login` to avoid the documented headless OAuth refresh bug. It gives a long-lived static token (about one year).

**Open**
- 🔴 **P3 · DECIDE** The disk-based credential resolution (an `oauth_token` file, a pending "waiting for authentication" state, an auto-retry interval) was never built. Whether it is wanted is a standing item (section 7).

**Decided**
- Both ways of producing the token are supported: log in inside the container, or generate it on another browser-capable machine and place it later.
- The token is a portable bearer credential, not bound to a device or container. Any file holding it should be `0600`, and the disk holding it should be kept out of loosely handled backups.

**Known limitations**
- Claude authenticates by setting a process-wide environment variable. Two different credentials for the same provider cannot be active at once. This would matter if per-Call routing ever wants two Claude keys.
- Qwen's DashScope endpoint and model name were unverified when first written. They were replaced by the Responses API work in section 15.

---

## 3. RabbitMQ and threading model

**Status:** 🟡 Ongoing

**In short:** One consumer thread reads from `telegram_gateway`. Messages are routed by `session_id` to a long-lived `SessionWorker` thread per session, which coalesces queued messages into one turn, runs it, and publishes the reply.

**Closed**
- 🟢 One shared consume connection read by one thread (`queue_consume_task()`, started by `start_queue_consumer()`). `Q_CHANNEL_IN` defaults to `telegram_gateway_outbound_queue`. Startup retries without limit.
- 🟢 `process_message()` branches on type: `gateway_alert`, `gateway_recover`, `session_cleared`, `session_clear_request`, and otherwise `_dispatch_to_session()`, which calls `get_or_create_session_worker(session_id).submit(data)`. Alert and recover are checked before routing because they carry no `session_id`.
- 🟢 Each `SessionWorker` owns its own `RabbitMQPublisher` connection, confined to its thread. A shared connection with a lock was rejected, since pika's I/O loop is tied to its owning thread. Short-lived closer threads create and close their own.
- 🟢 The routing key is `session_id`. A worker loops `inbox.get()`, coalesce, dispatch, repeat, so a session's batches run strictly one at a time in arrival order. The registry (`dict[str, SessionWorker]`) is guarded by a `threading.Lock` only around get-or-create and remove.
- 🟢 Coalescing happens at dequeue time. The worker blocks for one message, then drains whatever is already queued into one batch. There is no added latency in the common single-message case.
  - Rejected: a debounce in `telegram_gateway`. It taxes every message with latency, reintroduces the "renewed timer never expires" bug already fixed twice elsewhere, needs persisted-timer infrastructure the gateway should not own, and hides a buffered message from `has_open_tasks()`.
  - Every `task_id` in a batch except the last is closed immediately with `completed` on a separate thread (`_close_intermediate_task_ids()`, own disposable publisher) and marked complete. Only the last stays open for the reply. No gateway change was needed.
- 🟢 Crash-recovery tracking: `mark_task_active()` runs in `submit()` in the same window as the ack. `mark_task_complete()` runs when a task is closed. `sweep_orphaned_sessions()` returns what is still active.
  - `resync_orphaned_sessions()` runs after RabbitMQ is up and before `start_queue_consumer()`. It sends one `session_reset` per distinct session (`{"task_id": <one of its tasks>, "type": "session_reset"}`), deduplicated because a second request for an already wiped chat could not resolve it. On a successful publish every task of that session is cleared, and on a failed one nothing is cleared so it retries at the next startup.
- 🟢 Per-session directory (`SESSION_DIR = DATA_DIR / "sessions"`, created in `main.py`). The layout evolved:
  - First a fresh random `uuid4` subfolder per worker, so a reset could never reuse a path Claude had cached.
  - Superseded on 2026-09-15 by a stable `SESSION_DIR/<session_id>/<call_type>/<llm_type>`, which isolates each Call and provider. Two triggers keep it fresh: an unconditional startup sweep `clear_all_session_directories()`, and `clear_session_directory(session_id)` on every reset.
  - `clear_session_directory()` first calls `terminate_session()` (down through `agent_interface` and `claude_interface` to `destroy_sessions_under(root)`, a prefix match, so every client under the session root is disconnected), then removes the tree with `shutil.rmtree`.
- 🟢 Claude session continuity: `continue_conversation=True` was found not to resume anything. A live test showed a new Claude `session_id` and `num_turns=1` on every call, which matches upstream reports (`claude-agent-sdk-python` issues #10, #555, #848). Plain `query()` always starts fresh, and `continue_conversation` alone is not the supported mechanism.
  - Replaced by `resume=`, driven by a marker file `.claude_session_id` inside the session directory, written after each successful call and read before the next. Clearing the directory clears it, so a reset starts fresh.
  - OAuth later moved to a persistent client (section 5). The API path still uses the marker.
- 🟢 Inbox overflow: a bounded `queue.Queue(maxsize=SESSION_INBOX_MAX_SIZE)`, default 100, drops the newest with a `critical` log. Blocking `put()` was rejected, because it would stall the single consumer thread for every session.
- 🟢 Ack timing: the ack follows successful registration into the session's mailbox. A failed registration raises, so the message is nacked and requeued up to `Q_CONSUME_MAX_ATTEMPTS`. A missing `session_id` is a plain logged drop. A deferred ack was rejected (cross-thread ack plumbing, a stale delivery tag after a reconnect).
- 🟢 Three stop paths:
  - `stop()` is immediate and abandons what is queued.
  - `shutdown()` drains the queue first. `shutdown_all_session_workers()` snapshots the registry and joins each thread, bounded by `SESSION_SHUTDOWN_TIMEOUT_SECONDS` (30, where 0 waits indefinitely). It runs after `stop_queue_consumer()` and before the connections close.
  - `retire()` is the clear-and-remove path (section 8).
- 🟢 A race between `session_cleared` cleanup and an in-flight turn was fixed. `_handle_session_cleared()` used to call `stop()` and then remove the directory from the consumer thread while a turn could still be using it. It now calls `retire()`, which finishes the turn first. With no active worker it clears the directory directly.

**Open**
- 🔴 **P3 · DECIDE** Stray message after a clear. `get_or_create_session_worker()` would resurrect a worker for a late message tagged with a cleared `session_id`. On hold by explicit instruction. The gateway never reuses a `session_id` after a reset, so this only bites on genuinely out-of-order delivery. It now also applies to `retire()`.

**Known limitations**
- Claude's own transcripts (`~/.claude/projects/<encoded-cwd>/`, inside the bind mount) are never cleaned. A retired session's transcript becomes unreachable disk usage. No sweep is planned.
- Crash recovery over-triggers. Until every exit path calls `mark_task_complete()`, a task accepted but not finished before a restart looks active, including after an ordinary redeploy. The Chat-only path now covers its final task, so this is narrowed, not closed.

---

## 4. Error handling and alerting (SMTP)

**Status:** 🟡 Ongoing

**In short:** A `gateway_alert` (Telegram unreachable) cannot be reported through Telegram, so it goes by email, throttled by a Redis-backed cooldown. Errors from the AI side go back through `telegram_gateway` to the user (section 5 and section 17).

**Closed**
- 🟢 SMTP in `utils_smtp/smtp_handler.py`: `send_mail()` and `test_smtp_configuration(to_address=None)`. The test is run by hand and not at startup: `docker exec <container> python -m bot_sanctuary_application.utilities.utils_smtp.smtp_handler [address]`.
  - Settings: `SMTP_ENABLE_MAILER` (default off), `SMTP_FORCE_SSL`, `SMTP_AUTH_TYPE` (only `NONE` is special), `SMTP_SKIP_TLS`, `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_FROM_EMAIL`, `SMTP_TO_EMAIL`, `SMTP_USERNAME`, `SMTP_PASSWORD`.
  - The From display name is the shared `TELEGRAM_BOT_NAME` (root `CHATBOT_NAME`). A separate `SMTP_FROM_NAME` was dropped.
  - Logs never reveal the from address, username or password, only `<set>` or `<unset>`. A partial reveal is open to revisiting.
  - `CHATBOT_SMTP_*` variables are wired through `setup.sh` and `compose.dev.yml`, and the four sensitive ones are in the masked list.
- 🟢 `gateway_alert` to SMTP (`_handle_gateway_alert()`): every occurrence is logged and counted. The email is gated by a rolling cooldown, `GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS` (86400). A suppressed one is logged at info. The cooldown is marked only after a successful send, so a failed send retries on the next occurrence. The recipient is `SMTP_TO_EMAIL` directly, guarded against an empty value. The text is the user's own wording, with the persona name substituted.
- 🟢 Redis (`utils_redis/database.py`): a separate ACL user restricted to `~bot_sanctuary:*` on the shared `chatbot-redis`, `REDIS_DB` 1, two keys (`...:gateway_alert:count` and `...:last_notified_at`). Connection is lazy with a single attempt, and Redis is not a startup dependency. It fails open, so an outage allows a notification. Over-notifying was judged less harmful than silencing every future alert.
- 🟢 Self-resetting window: a sliding TTL refreshed on each occurrence was rejected, because a renewed expiry can never lapse while occurrences keep coming. The final design is a one-time fixed TTL equal to the cooldown, applied only when the counter key has no expiry yet. The counter therefore means "occurrences in the current fixed window".
- 🟢 `gateway_recover` is consumed to reset the throttle early (`reset_gateway_alert_throttle()` deletes both keys). The 24-hour TTL stays as the ceiling for when the message is lost. No guard was added before the reset.
- 🟢 Per-call Redis retry for parity with the gateway: `REDIS_TASK_MAX_ATTEMPTS` (5) and `REDIS_TASK_RETRY_DELAY` (1). Fail-open behaviour is unchanged. `_get_redis_client()`'s lazy connect and `RabbitMQPublisher` were left alone (it is per-instance and never shared).

**Open**
- 🔴 **P3 · BUILD** Non-blocking dispatch. `send_mail()` and the Redis calls run synchronously on the consumer thread inside `_handle_gateway_alert()`, so a slow SMTP or Redis call can stall consumption. Alerts are rare, but the same thread now dispatches every session's work.

**Open Questions**
- 🔴 **P3 · DECIDE** Whether "once per day" means a calendar day. A rolling 24 hours was assumed.
- 🔴 **P3 · DECIDE** Whether failing open is the user's own risk tolerance.

---

## 5. Agent "Call" model

**Status:** 🟡 Ongoing

**In short:** A turn enters at the Chat Call (persona "Rukia") and can hand off to Architect, Coder, Review or Documentation, any to any, through a per-session dispatch queue. The reply tool (text, poll, image and so on) is chosen by the LLM through a JSON prompt. Only the Chat Call is wired end to end.

**Closed**
- 🟢 Structure: `utils_calls/` has one file per Call (`chat_call.py`, `architect_call.py`, `coder_call.py`, `review_call.py`, `documentation_call.py`), each with `CALL_NAME` and `handle()`. `call_router.py` is the only module that imports all five, so there is no import mesh. Rukia is the persona, and the Call id is `"chat"`.
  - Whether "call one another" meant a literal peer-to-peer shape was never confirmed. That is a strictly bigger and more coupled change.
- 🟢 Phase 1, scaffolding. Phase 2, LLM and persona for the Chat Call only. The persona is the user-authored Rukia text, stored verbatim. The other four personas are intentionally empty.
- 🟢 Persona delivery was changed from string concatenation to each provider's native channel, because concatenation re-sent the whole persona as ordinary tokens on every call and could not use prompt caching. Claude uses `system_prompt` (not the subagent mechanism, which is for delegated helpers). Codex uses a per-call temporary `AGENTS.md`. DeepSeek and Qwen use a system or instructions message. Content now lives in library files (section 13).
- 🟢 Phase 3, handoff. A first `call_request` signal was replaced on 2026-09-13 by a per-session `dispatch_queue`:
  - Every hop (entry, handoff or corrective retry) is a `{"target_call", "prompt"}` item. `dispatch_call()` only pops one, calls that Call's `handle()`, and passes the result to `message_dissect()`.
  - `message_dissect()` is the single place that decides what a result is: unparseable replies queue a corrective retry to the same Call, a `target_call` plus `message` queues a handoff, and anything else is validated through `agent_tools.validate_message()`, then either returned or retried with the specific error.
  - `CALL_MAX_HOPS` (in `config.py`, not plumbed through compose) bounds handoffs and retries together. `_drain()` empties the queue on the hop-limit path so a leftover hop does not leak into the next turn.
  - `dispatch_queue` is passed explicitly. A `threading.local()` version was rejected because it silently depended on one long-lived thread.
- 🟢 Phase 4, wiring. `SessionWorker._process_batch()` coalesces and then calls `call_dispatch_handler.execute_dispatch_call()`. The run-and-publish function was moved out of `SessionWorker` so the worker only manages the thread, inbox and lifecycle. A defensive `try/except` wraps the `asyncio.run()` call, because an uncaught error there would now kill the thread. `mark_task_complete()` runs on every path that closes a task, which closed the final-task gap in section 3 for the Chat path.
- 🟢 The LLM chooses the reply tool. Two earlier revisions only moved where `"text"` was hardcoded. `agent_tools.build_tool_prompt()` now appends a JSON-only instruction built from the `TOOLS` table, and `message_dissect()` parses the result. This works for every provider because it uses plain prompt instructions rather than a native tool API. The cost is that a misbehaving model can answer in prose, which is treated as invalid and corrected.
- 🟢 `utils_agents/agent_tools.py` mirrors `telegram_gateway`'s documented payloads: a flat `TOOLS` list of name, description and format (poll, image, video, album, file, text, completed, error).
  - `execute_tool()` validates, then adds `task_id` and `session_id` itself, so agents stay identity-blind.
  - `session_reset` and `bot_started` are deliberately not tools, so an LLM cannot trigger a global wipe.
  - Validation is stricter than the gateway for a few cases (poll needs an option, urls and text must be non-empty). Telegram's own length limits are deliberately not copied, because they are configurable on the gateway and a copy would drift. Button rows are not validated, since the gateway drops a bad button and still sends the text.
  - It was rewritten for simplicity after the first version had tuples, a lambda dispatch table and nine functions.
- 🟢 Every Call's `handle()` returns the raw LLM string. `chat_call.handle()` differs only in wrapping the prompt with `build_tool_prompt()`. Its own retry loop was removed so correction happens in exactly one place (`message_dissect()`), and `resolve_reply()` and `verify_target_call()` were deleted.
- 🟢 Completion timing: a `poll`, or a `text` with `buttons`, is published without a following `completed`, so the `task_id` stays open for the answer. Each task's completion is decided independently from its own reply. On a restart the task is lost or orphaned, which the user accepted. Press routing, expiry and Redis machinery for buttons were proposed and explicitly rejected ("it is similar to poll but it is not a poll").
- 🟢 `settings.CALL_NAME_CHAT = "chat"` replaces three independent literals (`chat_call.py`, `call_dispatch_handler.py`, `claude_session_service.py`). Only chat was consolidated, as instructed.
- 🟢 Claude session service lifecycle (2026-09-14):
  - `agent_interface.initialise_llm_services()` and `terminate_llm_services()` delegate to `claude_interface.initialise_claude()` and `terminate_claude()`. They were first named for Claude, then moved so `agent_interface.py` holds no provider logic.
  - `initialise_claude()` has three outcomes, each logged: OAuth with a token bridges `CLAUDE_CODE_OAUTH_TOKEN` and starts `claude_session_service.py`, API with a token bridges `ANTHROPIC_API_KEY` once, and anything else logs "unknown decision" and does nothing.
  - `query_via_oauth()` routes through `query_via_service()` (the persistent per-session client) when a `session_dir` exists, and falls back to the one-shot `_run_query()` otherwise (the startup smoke test). `query_via_api()` always uses `_run_query()`.
  - The `token` parameter was removed from the two Claude functions, because it was dead once bridging moved to startup. `query_llm()` therefore has a Claude branch, a deliberate and acknowledged exception to its provider-agnostic header.
  - Wired into `initialise_application()` as the first step (before `test_llm_tokens()`) and into `terminate_application()` after `shutdown_all_session_workers()`, since a worker may still be mid-call. This removed the smoke test ordering risk.
- 🟢 Fix, 2026-09-14: `chat_call.py` still passed the retired `cwd=` keyword to `query_llm()`, raising `TypeError` on every turn, caught by `dispatch_call()`, so every message got a generic `call_pipeline_failed`. It was one line (`session_dir=session_dir`). The rename had left the file outside both earlier turns' scope. The runtime prerequisites (`LLM_CHAT_TYPE` and the Claude OAuth values in the gitignored `config.ini`) were verified present.
- 🟢 Diagnostic logging: `claude_session_service._run_turn()` and `claude_interface._run_query()` now log `ToolUseBlock` and `ToolResultBlock` content, and neither is added to the reply.

**Open**
- 🔴 **P1 · BUILD** [BS-01] **First CHECK that the fix is not already applied.** `WebSearch` is denied locally. A live run of 8 turns showed no `tool_use` line at all and `usage.server_tool_use` at zero. `ClaudeAgentOptions.tools` only sets nominal availability. Invocation approval is a separate layer, and with no `allowed_tools` or `permission_mode` set in either construction site, headless mode denies it before it ever reaches Anthropic (upstream `claude-code` issue #46250). This also means the model's own report that it lacked permission was accurate, and an earlier framing of it as an excuse was retracted.
  - Proposed fix, not recorded as applied: add `allowed_tools=agent.tools` (and the persona's tools in `_run_query()`) beside `tools=`. `permission_mode="bypassPermissions"` was rejected, because it approves `Bash`, `Write` and `Edit`, contradicting the persona's "cannot access files or run code".
  - Sites: `claude_session_service.py::_get_or_create_entry()` and `claude_interface.py::_run_query()`.
- 🔴 **P2 · BUILD** [BS-04] `architect_call.py`, `coder_call.py`, `review_call.py` and `documentation_call.py` still use `handle(prompt) -> str | None` and take no `session_dir`, although `dispatch_call()` calls every Call as `handle(prompt, session_dir)`. A `target_call` naming one would raise `TypeError`. Not reachable yet, and it blocks section 6 Phase 3.
- 🔴 **P3 · BUILD** Phase 5: native per-provider tool-calling, replacing the JSON-prompt approach with a structured-output guarantee, plus filesystem and code tools for the four specialised Calls only. Chat stays tool-less on that front.
- 🔴 **P2 · BUILD** [BS-05] Phase 6: read the `coding_allowed` tag that `telegram_gateway` stamps (section 3 there) and restrict a non-whitelisted task to Chat with no handoff. The whitelist is deliberately not owned here. It is a tag, not a gate, so a non-whitelisted task still proceeds.
- 🔴 **P3 · BUILD** Phase 7: structured logging for a handoff chain and a manual test path (like the SMTP `python -m` pattern).
- 🔴 **P3 · CHECK** The Rukia persona reads "cold" rather than "quietly introverted". Not diagnosed. The persona was not rewritten, because it is an authored asset. Possible causes: the "avoid punctuation or enthusiasm" lines overpowering the "warm" ones, or a prompt-tuning pass.
- 🔴 **P3 · DOC** `claude_session_service.py`, and the `interfaces/` and `services/` restructuring, have no complete record in this file. Known documentation debt.

**Decided**
- Chat has no repository or filesystem access at all, only specialised Calls do. This is also what makes the non-whitelisted Chat-only tier a real access boundary.
- The multi-agent debate model of the earlier architecture documents is deliberately not rebuilt. This is a single sequential handoff pipeline.

**Known limitations**
- The persistent OAuth path uses a persona file that is hardcoded to Chat (section 13).
- The retry-to-LLM loop inside `message_dissect()` has no cost or count decision beyond `CALL_MAX_HOPS`.

---

## 6. Workspace and repository access

**Status:** 🟡 Ongoing

**In short:** The agents are meant to read, review and eventually change repositories. A user pastes a Gitea or GitHub URL into Telegram and the bot clones or pulls it into a persistent workspace. Pull works end to end. Nothing can read what was pulled, and there is no push.

**Context**
- `AI_AGENT_ARCHITECTURE.md` and `Architectural_ReferBack.txt` hold an earlier 11-container design (debating agents A and B, a Summariser, a Debate Orchestrator, a Repo/Git container, a Sandbox Orchestrator, a Review API and a public Netlify frontend). `bot_sanctuary` is a deliberate simplification. Some pieces are kept (a real review UI, a git-owning boundary, sandbox execution) and others are not (debate, Summariser, multi-agent per task).
- Coding is single-user (confirmed 2026-09-29), so the repository directory is open to the container and no per-session isolation is required.
- Claude's native tools are mechanically wired (`cwd` and `tools`) but pointed at the ephemeral session directory.

**Plan (2026-09-23) and status**
- 🟢 Phase 1, persistent per-repository workspace: `settings.WORKSPACE_DIR`, `data/repositories`, laid out as `<domain>/<repo name>`.
- 🟢 Phase 2, URL detection and a non-LLM pull pipeline. Implemented 2026-09-27 for remote Gitea and GitHub only. The local bare-repository half of the plan was not built.
- 🔴 **P2 · BUILD** [BS-06] Phase 3, generic read-only code tools (`list_directory`, `read_file`), executed in Python and wired into `dispatch_call()`'s hop loop as another hop on the same Call. Scoped to the four specialised Calls and blocked on their contract mismatch (section 5).
- 🔴 **P3 · DECIDE** Phase 4, review-server integration contract. Defined once the external review system exists.
- 🔴 **P3 · BUILD** Phase 5, write tools (`write_file`, `apply_patch`, git write-back) gated on a positive review decision. Push only for a repository that has a remote.
- 🔴 **P3 · BUILD** Phase 6, sandbox and test execution, sequenced after write access, feeding evidence into the review artefact.

**Decided (plan)**
- A real review UI with its own frontend, deployed as a separate system on its own server. `bot_sanctuary` only produces a diff artefact and calls across the boundary. Reusing `telegram_gateway`'s accept and reject buttons was considered and rejected.
- A repository is pulled when a user pastes a URL or path. Host-only repositories that are never pushed online must be supported.
- Git credentials are provisioned out of band, and the LLM-facing Call pipeline never sees them. This was revised on 2026-09-24: deploy keys are now generated automatically in-app by deterministic startup code (`git_hosts.py`), and the surviving constraint is that the Call pipeline never reaches that code.
- The code-tool mechanism must be generic across all four providers, extending `agent_tools.py`'s JSON-prompt pattern, not Claude's native tools. The trade-off is accepted: give up Claude's single-round-trip native execution and prompt-cache continuity for one consistent mechanism.
- Sandbox and test execution stays a requirement.

**Decided (implemented pull, 2026-09-24 to 2026-09-29)**
- The transport follows the URL exactly as `git clone <url>` would, and the port is never configured. `ssh://git@host[:port]/...` uses SSH on that port, `git@host:owner/repo` uses SSH on 22, and `https://host[:port]/...` uses HTTPS. The generated `ssh_config` has no `Port` line.
  - Rejected: `domain:port` entries in `GIT_HOSTS` (built 2026-09-28, removed 2026-09-29), querying the host's REST API for `ssh_url`, SRV records, and port probing.
- `GIT_HOSTS` (`CHATBOT_GIT_HOSTS`) is a comma-separated list of plain domains that is the allow-list. A stray `:port` is tolerated and warned about once at startup, because a full URL value was once configured and silently broke everything.
- One ed25519 deploy key per domain, shared by a `<uuid>-pull` and `<uuid>-push` alias pair. The uuid is opaque and persisted in `git_hosts_manifest.tsv` beside `ssh_config`. `sync_git_hosts()` rewrites the files only when a domain changed, and a removed domain's key files are left on disk. The administrator's only manual step is pasting the logged public key into the host's deploy-key settings (read and write). Rejected: key generation in `setup.sh` (built and reverted, it touched files outside the application), deploy tokens, and GitHub Apps.
- A deterministic, non-LLM classifier with two gates: a trigger word ("pull", "clone", "fetch") and a declared `GIT_HOSTS` domain. Matching URL shape alone was a real bug, because any two-segment `https://` link short-circuited the chat pipeline. It is also gated on `coding_allowed`.
- An already-cloned repository is left alone unless an update was asked for. "clone" alone replies "already available" with no network call. "pull" or "fetch" runs `git remote set-url origin <fresh URL>` and then `git pull --ff-only`. The `set-url` is needed because a re-added domain gets a new uuid, which broke every existing checkout's origin.
- The destination is `WORKSPACE_DIR/<domain>/<repo name>`, with a collision guard. A checkout whose `origin` points at a different `<owner>/<repo>` is refused with `repository_name_conflict`.
- Host keys are trust-on-first-use (`StrictHostKeyChecking=accept-new`), recorded by `ssh` into `GIT_SSH_DIR/known_hosts`. `GIT_SSH_COMMAND` pins `ssh -F <GIT_SSH_DIR>/ssh_config`, so the bot never falls back to a default `~/.ssh`.
- Plain `http://` is rejected with an explicit reply (`repository_insecure_scheme`) before the collision guard. It is still classified as a pull request so it does not fall through to chat. This does not add HTTPS credentials.

**Closed**
- 🟢 `sync_git_hosts()` empty-write gap, part (a): a summary warning naming the failed domains, and no write when nothing changed. It was triggered on 2026-09-28 when every key generation failed with `FileNotFoundError: 'ssh-keygen'` because the running image predated the change.
- 🟢 Implementation: new `utilities/utils_workspace/` package (no `__init__.py`): `git_hosts.py` (`sync_git_hosts()`, `resolve_git_hosts()`, `declared_domains()`) and `repository_pull.py` (`extract_repository_reference()`, `execute_repository_pull()`, called from `_process_batch()` ahead of the Call pipeline). `config.py` has `GIT_HOSTS` (new `get_env_list()`) and `GIT_SSH_DIR`. `.gitignore` covers `data/git_ssh/` and `data/repositories/`. The images install `openssh-client` and `git`, so a rebuild is required. `CHATBOT_GIT_HOSTS` is passed through compose, `bs_dev_run_docker()` and the root masked list.

**Open**
- 🔴 **P2 · DECIDE** [BS-07] A force-pushed remote makes `git pull --ff-only` fail (seen on `synciate-api` on 2026-09-29, and the checkout had no local commits). Proposed: after a failed fast-forward, `git reset --hard origin/<branch>` only when the working tree is clean and there are no local commits ahead, otherwise refuse clearly. Always resetting would discard local work once Phase 5 commits, and always refusing leaves the administrator fixing it by hand.
- 🔴 **P3 · DECIDE** HTTPS for private repositories. HTTPS sends no credentials, and deploy keys only work over SSH, so a private repository must be sent as an SSH URL. Adding a token means storing another secret, so it is not decided.
- 🔴 **P2 · BUILD** [BS-06] Let an LLM read a pulled repository (Phase 3). Claude's `cwd` is still the ephemeral session directory. Two decisions are needed: which repository a turn sees (the most recently pulled in that session, or everything), and which tools (read-only, and only when `coding_allowed`).
- 🔴 **P3 · BUILD** Push. `push_alias` is resolved and unused. Plan of record: push a dedicated `bot/<task_id>` branch so the external review UI fetches it from Gitea or GitHub directly, with no filesystem access into this container. Belongs with Phase 5.
- 🔴 **P3 · BUILD** `sync_git_hosts()` parts (b) and (c): check `shutil.which("ssh-keygen")` once and log one clear error naming the image-rebuild fix, and optionally self-heal a missing `ssh_config` when the manifest still has entries.
- 🔴 **P2 · DOC** [BS-08] Housekeeping: `README.md` does not document `GIT_HOSTS`, the `data/git_ssh/` layout or the deploy-key registration step. There are no automated tests. Known small limits: only the first URL in a message is used, trigger words are English only, the scp-like form needs the `git@` user.
- 🔴 **P3 · DECIDE** Open question: whether Phase 4 should get a stub integration point before the review server exists.

**Known limitations**
- Production is not wired. There is no `bs_prod_run_docker()` or `compose.prod.yml`, the same standing gap as `WORKSPACE_DIR`'s persistence.
- Nothing here has automated tests.

---

## 7. Standing open items

**Status:** 🔴 Open

**In short:** Decisions parked from the earlier record that are not yet owned by a section above.

**Open**
- 🔴 **P3 · DECIDE** The auto-retry interval, or the lack of one, for sessions pending authentication (section 2).
- 🔴 **P3 · DECIDE** The exact field shape of the access tier on the inbound payload. It is settled in practice as `coding_allowed`, with its own dedicated whitelist on the gateway side still to come.
- 🔴 **P3 · DECIDE** Whether the Session Registry (`session_id` to role, cwd, permission scope and status) is persisted or in-memory only. In-memory was accepted for routing in `bot_orchestrator`, but here it affects conversation continuity as well.
- 🔴 **P3 · DECIDE** Task classification mechanism (rule-based versus model-based), parked since `bot_orchestrator`.
- 🔴 **P2 · DECIDE** [BS-18] Telling "credit or quota exhausted" apart from "provider down" in the error outcome. Largely overtaken by section 17, which covers DeepSeek and Qwen billing as `billing_exhausted`. Still open: Claude and Codex failures, and a possible "provider unavailable" type.
  - Detection ideas, none confirmed: DeepSeek and Qwen already have the HTTP status and a possible `Retry-After`. Codex only has the exit code and stderr text, which is brittle. Claude's exception hierarchy for a rate limit versus an auth failure is not verified against `claude-agent-sdk==0.2.152`.
  - Open choices: retry once within a turn, back off a provider after quota exhaustion, and whether Codex distinction is worth building at all.

---

## 8. Global session clear and `bot_started`

**Status:** 🟡 Ongoing

**In short:** A whitelisted admin command clears every session. `telegram_gateway` detects it and sends `session_clear_request`. This side accepts or rejects it, publishes one `session_reset`, and retires every session gracefully. Restart is announced with `bot_started`. Fully implemented (2026-09-12) in staged parts. Three small gaps remain.

**Closed**
- 🟢 Part 3 step 1, trigger acceptance: `message_handler.py::_handle_session_clear_request()` validates a non-empty `task_id` (a missing one is malformed and dropped) and delegates. `session_worker.session_clear_response(task_id)` publishes `{"task_id": task_id, "type": "session_reset"}` immediately, through its own disposable publisher, before anything is cleared. Renamed from `accept_session_clear_request()`, because the old name implied it made the accept or ignore decision.
- 🟢 Part 3 step 2, `SessionWorker.retire()`: sets a third event, `_clear_event`, and nothing else. It drains like `shutdown()`. Its exit action removes the worker, clears the session directory and reports in. `retire()` never publishes `session_reset`, because that already went out once at accept time. The check applies once `retire()` has been called regardless of what broke the loop, so a later `stop()` does not cancel it.
- 🟢 Part 3 step 3, sweep tracking and rejection: `handle_session_clear_request(task_id)` takes `_sweep_lock`, rejects if a sweep is running, and otherwise snapshots every worker, adds all their IDs to `_pending_retirements` in the same critical section, then publishes and signals each `retire()` after releasing the lock.
  - Tracking uses a `set[str]`, not an integer counter, so its non-emptiness is the in-progress signal and no second flag can disagree with it. Each session reports in through `_report_retirement()`. An empty registry needs no special case.
  - The consumer thread is single, so two requests are never decided concurrently. The lock only serialises a decision against workers reporting in.
  - A reject publishes an `error` (`error_type="session_reset_in_progress"`), not `completed`, which sends nothing and would leave the admin unable to tell the command was ignored. The gateway's generic handler shows its `message` as-is, so no gateway change was needed.
  - Deadlock validated by listing every lock: the only nesting is `_sweep_lock` then `_sessions_lock` in one place, never reversed, with no blocking I/O under either.
- 🟢 `bot_started`: `_push_bot_started()` (`initialise.py`) publishes `{"type": "bot_started"}` unconditionally on every startup, best effort. It fires after `initialise_rabbitmq_connection()` rather than at the first line, because `RabbitMQPublisher.publish()` only retries a bounded number of times. It is still ahead of `resync_orphaned_sessions()`. The gateway resolves everything pending from it (`telegram_gateway/CODE_TODO.md` section 1).
- 🟢 `README.md` documents the whole feature: a new "Global Session Reset" subsection, the three stop paths, the sweep decisions, two new limitations and the architecture diagram.

**Open**
- 🔴 **P2 · BUILD** [BS-09] The reject-path publish can fail like the accept path can, and nothing else closes the incoming `task_id` then. Neither failure has a backstop, unlike this project's other recovery mechanisms. `_reject_session_clear_request()` has the identical shape and was not recorded before the review.
- 🔴 **P3 · BUILD** A continuously busy session can delay its own retirement indefinitely. `_run()` only checks `_clear_event` when `inbox.get(timeout=1)` times out. A gapless stream faster than that would stop the session from ever reporting in, and `_pending_retirements` would never empty, which rejects every later request. Bounded in practice, since it needs an unbroken stream.
- 🔴 **P3 · DOC** The accepted stray-message risk (section 3) now also applies to `retire()`. The "on hold" answer likely holds, but it should be stated.
- 🔴 **P3 · TEST** The graceful-versus-immediate distinction is unverifiable against real behaviour until more of the Call pipeline completes real turns. The scaffolding was built ahead of that dependency on purpose.

**Decided**
- A dedicated method rather than a flag on `shutdown()` or `stop()`, so there are three distinct exit paths. `shutdown_all_session_workers()` cannot be reused in any form, since it only calls `shutdown()` and joins, with no publish, no directory clear and no registry removal.
- Graceful, not immediate, and this was asked directly. The gateway's deferral only unblocks once a `completed` or `error` equivalent arrives, so abandoning an in-flight turn would leave the chat deferred until the gateway's own timeout force-applied it.
- No cross-process recovery of an interrupted sweep. `bot_started` is the whole extent of what this side does about a crash mid-sweep.
- The existing orphan tracking (`mark_task_active` and friends) is unrelated and untouched.
- The original design wrongly modelled one `session_reset` per session with a `session_id`. That text is kept struck through in the earlier record and was reconciled on implementation. `resync_orphaned_sessions()`'s own publish was already correct, so the proposal to add `session_id` to it was not done.

---

## 9. Timed reset, timezone and central time

**Status:** 🟢 Closed

**In short:** An optional daily timed global reset, plus timezone-aware timing and logging, plus one central place to read the clock. Done on 2026-09-12 together with `telegram_gateway` (its section 9).

**Closed**
- 🟢 `SESSION_RESET_TIME` (`config.py`, with a new `get_env_time()`): silent fallback to unset. It accepts "13:00" (24-hour) or "1:00pm" (12-hour). By explicit instruction an hour of 12 with either am or pm means noon, so midnight can only be written "00:00".
- 🟢 The trigger belongs on this side. A first attempt on `telegram_gateway` (pushing a `session_clear_request` with a sentinel) contradicted the agreed design, was flagged to the user and fully reverted ("telegram_gateway have no rights to trigger a session reset").
- 🟢 `_begin_session_clear_sweep()` was extracted from `handle_session_clear_request()` and shared. `trigger_timed_session_reset()` publishes `session_reset` directly with `task_id` null, then signals every `retire()`. If a sweep is already running it is skipped and logged, with no published error, since nobody asked. The next day's occurrence is the retry.
- 🟢 Scheduler: `start_session_reset_schedule()` and `stop_session_reset_schedule()`, an event-gated background thread that recomputes its wait each time, like the gateway's ceiling sweep. It is a no-op when `SESSION_RESET_TIME` is unset. Wired after `resync_orphaned_sessions()` and stopped first in `terminate_application()`.
- 🟢 `TZ` and `get_env_timezone()` in `config.py`. Both `logging_setup.py` files set `Formatter.converter` from `settings.TZ`. `tzdata` was added to both `requirements.txt` files. Root `config_sample.ini` and `config.ini` have `CHATBOT_TZ="Asia/Singapore"`, and `compose.dev.yml` sets each service's `TZ` from it. It is not in the masked list, because it has one reasonable default.
- 🟢 `application_time()` and `application_time_diff(reference)` (`utilities/utilities.py`, in both projects) are the single clock source. Migrated: `_seconds_until_next_session_reset_time()`, `should_notify_gateway_alert()` and `mark_gateway_alert_notified()`. `time.sleep()` and the logging converter were deliberately left.
- 🟢 CCR-025 (Medium): `get_env_timezone()` caught only `ZoneInfoNotFoundError`, so `ValueError` and `IsADirectoryError` would crash at import. It now catches `(ZoneInfoNotFoundError, ValueError, OSError)`, in both projects. `bot_sanctuary` has no `CODE_NON_COMPLIANCE.md`, so this record stands for it.
- 🟢 `README.md` has the `SESSION_RESET_TIME` and `TZ` entries.

**Known limitations**
- Daylight-saving edge cases in the next-occurrence arithmetic were not stress-tested. The deployment zone (`Asia/Singapore`) does not observe it.
- The three gaps in section 8 apply equally to this trigger, because it shares the same sweep machinery. None was fixed here.

---

## 10. Persistent Claude client left uncleaned after a timeout

**Status:** 🟢 Closed

**In short:** A 120-second timeout abandoned a turn but left the session's persistent client entry in the registry. The abandoned coroutine could still hold the entry's lock, so the next turn could block on it and time out the same way.

**Trigger:** on 2026-09-16 (23:18 to 23:20) the persona chained 12 sequential `WebSearch` calls in one shoe-comparison turn, reached `AGENT_QUERY_TIMEOUT_SECONDS` (120), and the user got "The chat agent is not currently available". This was the timeout working as designed, not a crash.

**Closed**
- 🟢 `query_via_service()`'s `TimeoutError` branch now also evicts the entry with a fire-and-forget `_drop_entry(session_dir)` on the service loop. The next turn builds a fresh entry and lock. It mirrors `_run_turn()`'s own exception path, which already evicted, and was the one failure path missing it.
- 🟢 Docstring and the module header's limitations bullet updated in place.

**Decided**
- The root trigger (unbounded tool chaining) is agent behaviour and was not changed. No `chat.json` change was proposed. Raising `AGENT_QUERY_TIMEOUT_SECONDS` is a separate operational choice.
- The abandoned coroutine may still run in the background. The fix only guarantees the next call is never queued behind it.

**Open Questions**
- 🔴 **P2 · DECIDE** [BS-10] Whether to raise `AGENT_QUERY_TIMEOUT_SECONDS`, a pure `config.ini` change.
- 🔴 **P3 · TEST** Not run against a live repeat-timeout scenario. Verify by lowering the timeout or reusing a long-chain prompt, then confirming the log shows the entry dropped and a fresh client on the next turn.

---

## 11. Token-usage cost review

**Status:** 🟡 Ongoing (on observation)

**In short:** About 13% of the plan was used between 06:59 and 09:30 on 2026-09-16, which was far above what about 8 messages should cost. Three drivers were traced from both logs. One was fixed as a by-product, one was declined, and one lever remains unpulled.

**Drivers**
- 🟢 Driver 3(b), one question costing 2 to 3 full turns: the 09:17 "AI slowdown" exchange cost three Claude calls (a research pass, a forced JSON self-correction, and a `delivery_failed` retry) and delivered nothing. `telegram_gateway` fixed the cause (`telegram_gateway/CODE_TODO.md` section 12). No `bot_sanctuary` change was needed for the mapping half. Its own half is section 12 here.
- ⚪ Driver 1, uncapped `WebSearch` chaining: a `max_turns` cap was discussed and rejected. A cap risks an incomplete answer for a genuinely multi-step question, and a capped call that still hits the timeout would repeat the abandon-and-redo waste anyway. No follow-up unless a materially different proposal (such as salvaging partial research on a timeout) is raised.
- 🔴 **P1 · DECIDE** [BS-02] Driver 2, an unbounded session: `SESSION_RESET_TIME` was unset, so every reply re-read the whole accumulated history (cached read tokens climbed from about 3.5K to about 56K across 2.5 hours). It is the lowest-effort lever. It is a `config.ini` value, no code, but it is still not applied.

**Decided**
- The Claude SDK's own automatic compaction is not available. The pinned `claude-agent-sdk==0.2.152` lacks the `compaction_control` parameter its docs describe (an open upstream issue).
- A custom idle-triggered "summarise then reseed" reset would be new infrastructure and is not designed. The user's own framing is that cost was dominated by a few expensive turns, so setting the existing `SESSION_RESET_TIME` may capture most of the benefit.

**Open Questions**
- 🔴 **P1 · DECIDE** [BS-02] Whether to set `SESSION_RESET_TIME`. Awaiting an operational decision.
- 🔴 **P3 · DECIDE** Whether an idle-based reset is worth designing at all.
- 🔴 **P2 · TEST** [BS-11] Whether to measure usage after the fixes to confirm the expectation. Not planned as a concrete step.

**Follow-up Work**
- 🔴 **P1 · DECIDE** [BS-02] Decide a `SESSION_RESET_TIME` value, then observe (BS-11) real usage before treating this as resolved.

---

## 12. Non-text payload fields in `_process_batch()`

**Status:** 🟢 Closed

**In short:** `SessionWorker._process_batch()` built each turn's prompt from the `text` field alone, so a button press, a poll answer or a failed-delivery notice produced a blank prompt. A new `_extract_item_text()` folds them in.

**Closed**
- 🟢 `_extract_item_text(item)`: `text` if non-empty, otherwise a button press (`"[The user pressed a button - purpose: ..., payload: ....]"`), a poll answer (`"[The user answered the poll by selecting option index/indices: ....]"`) or a delivery failure (`"[Your previous 'type' reply failed to send - status_code=..., reason: .... Please try again, correcting the issue if possible.]"`).
  - A poll answer carries Telegram's option indices, because the gateway has no lookup back to the question. It relies on the persona's own history.
  - A `delivery_failed` pass was a genuine separate gap: without it the corrective retry received an empty prompt and did not know why it was running.
- 🟢 Broad scope was chosen, covering all three signals in one function.
- 🟢 A claim in this entry's original text, that poll answers "never had a working consumer", was wrong. Three poll round-trips succeeded the same morning, and the one failing test was an unrelated restart. The claim was retracted, but the `text`-only gap was real.

**Open**
- 🔴 **P3 · DECIDE** `poll_timed_out` still resolves to an empty prompt and is out of scope.
- 🔴 **P2 · BUILD** [BS-03] `image_url`, `video_url` and `file_url` are still unread. `telegram_gateway` now sends captioned media straight through as a task, so this matters more than before. Real multimodal input is a larger piece of work and has no tracked entry.

---

## 13. Persona and library-file loading

**Status:** 🟡 Ongoing

**In short:** Persona text lives in shared library files, and each provider resolves its own persona and model locally at its own querying point. A dead-extension bug that left every one-shot persona empty is resolved by this work. A few tidy-ups and one verification remain.

**Closed**
- 🟢 The bug (scoped 2026-09-17): `agent_interface.load_persona()` read `libraries/<llm>/<call>.md`, but every library file had been migrated to `.json` with no record of the migration, so it returned `None` for every provider and Call. Claude's `_parse_persona()` also expected a frontmatter-over-text shape instead of `chat.json`'s structure, which would have dropped `tools` and `model` again. Both are superseded by `agent_persona.py`.
- 🟢 Shared persona files: `libraries/persona/<call>.md`, one per Call, outside any provider folder. Only `chat.md` has content (the former `persona` array, moved losslessly). The other four are empty placeholders. Each provider's library file sets `"persona": "{{PERSONA}}"`.
  - `{{PERSONA}}` is substituted first and `{{BOT_NAME}}` second, so one pass handles every occurrence. The placeholder was lower case at first and was capitalised to match `{{BOT_NAME}}`.
  - The file is named `coder.md`, not the requested `code.md`, to match the existing `CALL_NAME`. This was flagged and not confirmed.
- 🟢 Constants moved into `config.py`: `LLM_TYPE_CLAUDE`, `LLM_TYPE_CODEX`, `LLM_TYPE_DEEPSEEK`, `LLM_TYPE_QWEN`, `KNOWN_LLM_TYPES`, `LIBRARIES_DIR` (previously computed twice from different depths), `PERSONA_DIR`, `BOT_NAME_PLACEHOLDER` and `PERSONA_PLACEHOLDER`. `_CODEX_BINARY` was deliberately left, since it names an executable and not an `llm_type`.
- 🟢 `utils_agents/agent_persona.py`: `parse_agent(llm_type, call_name)`, `load_persona_text(call_name)` and `call_name_from_session_dir(session_dir)`. Resolution is local to each provider and `query_llm()` is untouched. A centralised version in `query_llm()` was rejected, because it moved resolution away from where each LLM actually queries.
  - Fallback rule, identical across providers: if a Call name can be derived from the directory, the internally resolved persona wins outright. Otherwise the `persona` argument is used.
  - Claude inlines it in `_run_query()`, and the old `_parse_persona()` and its frontmatter constants were deleted. Codex, DeepSeek and Qwen each have a small `_resolve_persona()` or `_resolve_agent()` helper, because their inner functions take no directory.
- 🟢 `parse_agent()` hardened: an empty or whitespace-only file is "not yet written" and logs at info, a partial file uses every field present, and only non-empty undecodable content logs an exception. Several library files are intentionally empty placeholders.

**Open**
- 🔴 **P3 · DECIDE** Style is not unified. Claude's resolution is inline while the other three have helpers. Functionally identical. The user wants one style, either inlined everywhere or a helper everywhere, and the choice is not made.
- 🔴 **P3 · DECIDE** `chat_call.py`'s own `load_persona(...)` call is provably dead, because its directory always resolves a Call name. It is not yet removed, pending a go-ahead. The other four Calls' equivalent calls still load.
- 🔴 **P3 · CHECK** Confirm the `coder` versus `code` filename.
- 🔴 **P2 · TEST** [BS-12] Verify the Claude API path end to end. Confirm via the existing tool-use logging that `system_prompt`, `tools` and `model` reach `ClaudeAgentOptions` and that `WebSearch` is permitted. This is blocked on the `allowed_tools` fix (section 5).
- 🔴 **P3 · BUILD** `claude_session_service.py` still calls `parse_agent(...)` hardcoded to `settings.CALL_NAME_CHAT`. If another Call resolved to Claude with OAuth it would receive the Chat persona. The four non-Chat Calls are also not yet directory-wired, which is the precondition for this whole mechanism to resolve anything beyond the fallback.

**Known limitations**
- On the OAuth persistent path the `persona` argument is ignored in favour of the library file. This split is now load-bearing.

---

## 14. Claude API-path timeout

**Status:** 🟢 Closed

**In short:** The one-shot path (`_run_query()`, used by `query_via_api()` and the OAuth fallback) had no timeout at all, so a hung CLI subprocess could block a worker thread forever. It now has the same discard-on-timeout behaviour as the OAuth platform.

**Closed**
- 🟢 The message loop was extracted into a module-level `_collect_claude_response(prompt, options, session_dir)` (not a nested closure, to match the file's convention). It returns `(reply_parts, captured_session_id)`. The name says "collecting": it consumes the stream and returns one aggregate.
- 🟢 `await asyncio.wait_for(..., timeout=settings.AGENT_QUERY_TIMEOUT_SECONDS)` reuses the OAuth path's constant. A new `except asyncio.TimeoutError` logs at `error` (no stack trace) and returns `None`, indistinguishable from other failures. A timeout skips `_write_resume_id()`.
- 🟢 Cancelling a hung subprocess was verified by documentation only, not a live test. The SDK's PR #1082 shields subprocess teardown from asyncio cancellation and shipped in 0.2.111 (2026-07-06), before the pinned 0.2.152. PR #916 adds an `atexit` backstop. Issue #378 (`Query.close()` hanging) affects the persistent `ClaudeSDKClient.disconnect()`, which is already bounded by `AGENT_SHUTDOWN_TIMEOUT_SECONDS`.

**Decided**
- Parity with the OAuth path, per the user ("I intend to make API the same as OAuth"). A distinguishable `error_type` for a timeout (`call_pipeline_timeout`) was proposed and rejected as out of scope. The OAuth path's own timeout is already indistinguishable from other failures: the cause exists only in one server-side log line and the user sees `call_pipeline_unavailable`.
- A partial-reply salvage option was dropped in favour of discard.

**Open Questions**
- 🔴 **P3 · DECIDE** The shared ceiling is not an equal effective budget. The API path spawns a new CLI subprocess on every call, so connection overhead is inside the 120 seconds every time, while OAuth pays it only when a client is created or reconnected. Options: accept as is, give the API path a small dedicated buffer, or document only. Not decided.
- 🔴 **P2 · CHECK** [BS-13] Confirm that the container really has `claude-agent-sdk==0.2.152` (`pip show`). No execution access was available.

---

## 15. Qwen interface

**Status:** 🟡 Ongoing

**In short:** Qwen now takes its model from the Call's library file and keeps conversation continuity through DashScope's Responses API `previous_response_id`, with a local expiry. It shares the common timeout, retry and billing handling (sections 14 and 17). Nothing here has run against a real account.

**Closed**
- 🟢 Research finding that shaped the scope: `tools` is structurally different from Claude's. Claude's `["WebSearch"]` names an SDK built-in that executes autonomously. DashScope's `tools` is raw function-calling with a JSON Schema per tool and a caller-side execute-and-respond loop. It was left out of `libraries/qwen/chat.json` on purpose. `name` and `description` are read by no provider.
- 🟢 `libraries/qwen/chat.json` was a 0-byte placeholder and is now `{"name", "model": "qwen3-plus", "description", "persona": "{{PERSONA}}"}`, which resolves to the same shared persona text as Claude.
- 🟢 Part 1, model wiring: `_MODEL` became `_DEFAULT_MODEL`, used only as a fallback. `_resolve_agent(persona, session_dir)` resolves persona and model from one `parse_agent()` call, falling back when `session_dir` is `None` or the Call's file has no `model` (the four non-chat files are still empty).
- 🟢 Part 2, continuity:
  - Full switch from `/chat/completions` to the OpenAI-compatible `/responses` endpoint (`_post_response()`), because `previous_response_id` only exists there.
  - Persona is sent as the Responses `instructions` field on every call, not folded into `input`. Instructions are not carried forward by `previous_response_id`, so a first-turn-only persona would silently stop applying. `input` carries only the new user message.
  - State is a marker file `.qwen_session.json` (`{"response_id", "created_at"}`) in the session directory, at `<SESSION_DIR>/<session_id>/chat/qwen/`. The existing whole-directory wipe already covers both of the user's two moments (startup, and "refresh yourself"), so no new clearing code was needed.
  - Local TTL `QWEN_SESSION_TTL_DAYS` (default 2), stricter than DashScope's 7-day server-side one. The user also wanted a specific wall-clock time, which was first built as `QWEN_SESSION_EXPIRY_TIME`, then replaced by the shared `SESSION_RESET_TIME`, then removed from this module entirely on 2026-09-20. Verified safe: the scheduled reset retires every worker and clears every session tree, so the alignment could never be what expired a session. The TTL remains as the only age limit when no reset is set and as a backstop when a reset is skipped.
  - A rejected `previous_response_id` is recognised by a narrow heuristic (`_is_expired_previous_response_error()`: 4xx and a body mentioning "response_id"), and the call is retried once as a fresh conversation. Status code alone was rejected as too broad, since a bad model string is also a 400.
  - Return shapes of `_post_response()`, `_resolve_agent()` and `_read_session_marker()` were converted from tuples to named dicts. `cwd` was renamed to `session_dir` throughout.
- 🟢 The request timeout now follows `settings.AGENT_QUERY_TIMEOUT_SECONDS`, and a Qwen-scoped constant was deleted. The outer bound is `AGENT_QUERY_TIMEOUT_SECONDS + 10`, so the inner socket timeout fires first (an assumption: equal values would race).
- 🟢 `IncompleteRead` on the success path is a retryable connection-level failure (section 17).
- 🟢 A Qwen `terminate_session()` was decided against, not deferred. Its only call site runs immediately before an unconditional `rmtree`, and Qwen has no live in-memory state to tear down. Claude's exists only because it disconnects a live client the filesystem cannot reach. Revisit only if a persistent connection is ever added.

**Open**
- 🔴 **P3 · DECIDE** Confirm the 2-day expiry is meant to be absolute from the marker's creation. It was implemented that way as the plan's recommendation, and the user did not answer the question. Switching to sliding means refreshing `created_at` on every write.
- 🔴 **P3 · TEST** The exact DashScope error shape for a rejected `previous_response_id` is unverified, and a rejection the heuristic misses never self-heals. The marker stays after a failed call, bounded by the reset or the TTL.
- 🔴 **P3 · DECIDE** `tools` is entirely unaddressed. No plan exists for a function-calling execute-and-respond loop.
- 🔴 **P3 · DECIDE** Review findings not acted on: `_read_session_marker()` can still raise on a corrupt or hand-edited marker (`UnicodeDecodeError`, non-object JSON, non-string or naive `created_at`), SSL failures arrive as `URLError` and are marked retryable (a preference), and any exception from `error.read()` in the `HTTPError` handler escapes `_post_response()` (judged unlikely, left unguarded on instruction).

---

## 16. DeepSeek interface

**Status:** 🟡 Ongoing

**In short:** DeepSeek takes its model and reasoning effort from the Call's library file and has local transcript-based continuity with size and age limits. The default model name was found to be dead and was corrected. It shares the common timeout, retry and billing handling. Nothing here has run against a real account.

**Closed**
- 🟢 A pre-existing correctness bug: `_MODEL = "deepseek-chat"` named a model discontinued on 2026-07-24 (a hard cutover, no grace period or fallback). It is now `_DEFAULT_MODEL = "deepseek-v4-flash"`, used only as a fallback. The choice of Flash over Pro as the generic default was an assumption the user accepted.
- 🟢 `libraries/deepseek/chat.json` is now `{"name", "model": "deepseek-v4-pro", "reasoning_effort": "high", "description", "persona": "{{PERSONA}}"}`. Model and effort were the user's own selection.
  - `reasoning_effort` is read off `AgentPersona.persona` (the raw parsed JSON) and sent as a top-level request field. It is omitted when unset, so other Calls behave as before. No dedicated dataclass attribute was added for a field no other provider uses.
  - It is a top-level field, not an `extra_body` or `thinking` wrapper. That wrapper is an OpenAI-SDK workaround, and this module posts directly to DeepSeek's REST endpoint.
- 🟢 `_resolve_agent()` returns a named dict `{"persona", "model", "reasoning_effort"}` from one `parse_agent()` call. `cwd` was renamed to `session_dir`.
- 🟢 DeepSeek's `/chat/completions` is fully stateless, with no server-side conversation concept. Continuity is a local transcript `.deepseek_transcript.json` in the session directory.
  - The full history is resent every call, with the persona as a leading system message and not stored in the file. DeepSeek's 1M-token window and automatic context caching made full replay viable.
  - It stores `role: "user"` and `role: "assistant"`. A local `"session"` role was tried at the user's instruction and then removed as confusing, since it had to be translated back before every call (`_to_api_messages()` was deleted).
  - A size cap, `DEEPSEEK_TRANSCRIPT_MAX_BYTES` (200000), drops the oldest complete turn (a pair) while the file exceeds it, on every write, never below the most recent turn. It is a byte proxy, not a token budget.
  - Age: `DEEPSEEK_SESSION_TTL_DAYS` (default 2), absolute from creation. The file is `{"created_at", "turns": [...]}`, because modification time cannot serve (every write updates it). An old bare-list file is treated as no history. An expired transcript is ignored and overwritten by the next success, not deleted at read time. The alignment to `SESSION_RESET_TIME` was added and then removed the same way as Qwen's. The question of one shared `_session_expiry_cutoff()` helper was closed as "no", an interpretation of "resolve".
  - The four removal mechanisms are size, age, a session reset, and application startup. Only a confirmed success appends and persists.
- 🟢 The timeout follows `settings.AGENT_QUERY_TIMEOUT_SECONDS`, the same unification as Qwen (outer bound plus 10).
- 🟢 The 60-second timeout had never been a deliberate decision. It was a shared default copied into both modules, and it was probably too short for `deepseek-v4-pro` at high effort. One third-party benchmark reported about 128 seconds to the first answer token. A single data point and not verified here.

**Open**
- 🔴 **P2 · DECIDE** [BS-14] The shared timeout is one knob across three providers. Raising it for DeepSeek's reasoning also raises Claude's. The 120 and 130 second pair may still be too short for `deepseek-v4-pro` at high effort.
- 🔴 **P2 · TEST** [BS-15] The startup smoke test calls `query_llm()` with no `session_dir`, so it uses the fallback model and no `reasoning_effort`, and never exercises the request shape `chat.json` produces. The `reasoning_effort` field itself is research-derived and unverified (some third-party gateways drop or rewrite it). The header does not carry the "unverified against a real account" caveat that Qwen's does. Run one real chat call to confirm effort is honoured and to observe latency.
- 🔴 **P3 · TEST** Whether DeepSeek's non-streaming keep-alive lines reset urllib's socket timeout is untested.
- 🔴 **P3 · BUILD** `finish_reason` is never inspected, so a reply truncated at the token limit is stored as complete. Claude's `is_error` is likewise only logged, so this is close to parity.
- 🔴 **P3 · BUILD** The response `usage` block, including prompt-cache hit and miss counts, is not logged. The byte cap is only a proxy for tokens, and this bears on section 11.
- 🔴 **P3 · DECIDE** Each stored user turn carries the roughly 1.3 KB tool-format instruction block from `build_tool_prompt()`, so the byte cap fills faster than the conversation does. Claude's history holds the same boilerplate.
- 🔴 **P3 · DECIDE** `tools` is unaddressed, the same mismatch as Qwen. The non-chat fallback tier choice, and whether 200000 bytes is the right cap, are unvalidated.
- 🔴 **P3 · CHECK** `IncompleteRead` handling on DeepSeek's error paths was not checked.

---

## 17. API retry and billing errors

**Status:** 🟡 Ongoing

**In short:** DeepSeek and Qwen now retry transient failures (rate limit, server error, dropped connection) with backoff, and report a depleted balance as a `billing_exhausted` error reply instead of retrying it. Claude and Codex are not covered. Nothing was run.

**Closed**
- 🟢 Retry (`utils_agents/api_retry.py`, shared): `run_with_retry(attempt_call, provider)` wraps the `asyncio.wait_for()` call in each interface.
  - Retryable: HTTP 429, 500, 502, 503, 504 (`RETRYABLE_STATUS_CODES`) and connection-level errors (`URLError` that is not an `HTTPError`, `ConnectionError`, unless the reason is a timeout). Every other 4xx is permanent.
  - A socket or outer timeout is not retried, because it would multiply an already long wait and the outcome is ambiguous.
  - Backoff is exponential with jitter, each delay capped at 30 seconds, and an integer `Retry-After` replaces the computed delay. It sleeps with `asyncio.sleep()`.
  - `API_RETRY_MAX_ATTEMPTS` (default 3, where 1 disables) and `API_RETRY_BASE_DELAY_SECONDS` (default 2), shared across providers.
  - The loop wraps `wait_for` in the async layer, which is why `_post_*` now returns a named dict with `retryable` and `retry_after`. A loop inside the sync function was reconsidered and not built. A retry state change cannot corrupt DeepSeek's transcript or Qwen's marker, since both are written only after a confirmed success.
  - Shared versus per-module helper was answered by assumption (shared), not by the user. Qwen's rejected-`previous_response_id` retry is separate and never retryable, since that is a 400 or 404.
- 🟢 `IncompleteRead` on Qwen's success path is retryable (it is an `http.client.HTTPException`, not an `OSError`). A retried request may have been processed already, so a retry after a truncated 200 can be billed twice, which was accepted. The matching guard around `error.read()` was first added and then removed after its likelihood was questioned.
- 🟢 Billing, phases 1 and 2, DeepSeek and Qwen only:
  - `is_billing_failure(status_code, body_text)`: HTTP 402, or 429 with `insufficient_quota` in the body. This also fixed Qwen's `insufficient_quota` 429 being retried for about 6 seconds a turn. A plain 429 stays an ordinary rate limit.
  - The result dicts gained `billing_failure`, forced non-retryable. `query_via_api()` returns `billing_exhausted_response()`, a fresh `{"type": "error", "error_type": "billing_exhausted", "message": "The chat agent's usage allowance has run out for now. Please try again later."}`. The provider's body is logged only. Nothing is persisted for that failure.
  - A first version raised an `LLMBillingError` exception, and was replaced the same day by returning the dict, which the existing `message_dissect()` and `execute_tool()` path already handles. `agent_errors.py` was repurposed to hold `billing_exhausted_response()` and can be merged or deleted later. `dispatch_call()` has no net change, because an `elif` added to `execute_dispatch_call()` was reverted at the user's instruction ("I do not want a new error handler").
  - `query_llm()` is typed `str | dict | None`. `_send_llm_test_prompt()` logs a dict reply as an error.
- 🟢 `billing_exhausted` is a new type and not `token_exhausted`, because that is the gateway's "taking a nap" message modelled on a known wait of about 5 hours. A depleted balance has no known end.

**Open**
- 🔴 **P2 · BUILD** [BS-16] Claude's `billing_error` is not covered. The SDK exposes `AssistantMessage.error` (documented values include `authentication_failed`, `billing_error`, `rate_limit`, `server_error`), which this codebase never reads. Unverified against `0.2.152`. Today Claude, like the others, collapses into `call_pipeline_unavailable`.
- 🔴 **P3 · DECIDE** Phase 3 (an operator email on a billing failure, throttled like `gateway_alert`) and phase 4 (a circuit breaker) were not requested and are not built.
- 🔴 **P3 · CHECK** DashScope's overdue-account response (Arrearage) is not detected. Its status and code were never confirmed.
- 🔴 **P2 · TEST** [BS-17] The 402 and 429 signals come from search results, not a real account.
- 🔴 **P3 · CHECK** Known consequence, accepted: the dict then also receives a `completed`, which the gateway is expected to drop with a logged "No task mapping found" after `_handle_error()` deletes the mapping. Not seen in any log.
- 🔴 **P3 · CHECK** Open: the exception route versus the response-dict route was a user challenge. The user observed that Claude seems to treat an error as a response. Checked: no code turns a Claude API failure into that shape. The only response-as-error route is the LLM's own `error` tool, which needs a model reply and so cannot cover a billing failure. Unverified: the SDK may return API errors as assistant text (`claude-agent-sdk-python` issue #472), which would loop through corrective retries up to `CALL_MAX_HOPS`.
- 🔴 **P3 · CHECK** Confirm whether `bot_sanctuary/README.md` lists the emitted error types. Not checked.
- 🔴 **P2 · TEST** [BS-17] Verification: stub 503, 503, 200, a permanent 401, and a socket timeout.

**Follow-up Work**
- 🔴 **P2 · BUILD** [TG-07, TG-10] The gateway's own message and button for `billing_exhausted` is `telegram_gateway/CODE_TODO.md` section 13 (decide first, then build). Tracked there, not here. Nothing was changed in gateway code.

---

## 18. Codex chat file and OAuth

**Status:** 🔴 Open

**In short:** `libraries/codex/chat.json` is written, but `codex_interface.py` reads only its `persona`, so `model`, `reasoning_effort` and `sandbox` are inert. A separate plan covers hardening the existing OAuth login path. Neither has been run.

**Closed**
- 🟢 `libraries/codex/chat.json` written: `name`, `description`, `persona: "{{PERSONA}}"`, `model: "gpt-5.6-terra"`, `reasoning_effort: "high"`, `sandbox: "read-only"`. Model, effort and sandbox are the user's choices. `sandbox` and `reasoning_effort` are this project's own field names, read off the raw persona JSON the way DeepSeek's are. `parse_agent()` tolerates extra fields. `tools` was left out, because Codex has no per-call tools array (the same mismatch as Qwen), and `web_search` was left out because it was not requested.
- 🟢 The OAuth path exists already: `query_via_oauth()` runs `codex exec` with `OPENAI_API_KEY` removed, `query_llm()` routes on `"OAUTH"`, the native CLI is installed, the `~/.codex` bind mount is in place, and the README documents `codex login`.

**Open**
- 🔴 **P3 · BUILD** Wire the fields into `codex_interface.py`: `-m`, `-c model_reasoning_effort=...` and `--sandbox`. It currently passes none, so the CLI's own defaults apply.
- 🔴 **P3 · TEST** `--skip-git-repo-check`. Codex requires a Git repository by default, and the persona's temporary directory is not one, so this path has never run for chat and may refuse to start. Verify before setting `LLM_CHAT_TYPE` to `codex`.
- 🔴 **P3 · BUILD** `--ephemeral`, otherwise Codex stores session files on disk with no continuity mechanism using them.
- 🔴 **P2 · BUILD** [BS-20] A minimal subprocess environment. `query_via_api()` passes `{**os.environ, "OPENAI_API_KEY": token}`, so every secret in the bot's environment (other LLM tokens, the Telegram token) is visible to a command the model runs, whatever the sandbox says. The OAuth path strips only `OPENAI_API_KEY`, and the login file under `~/.codex` is readable by the same OS user.
- 🔴 **P3 · DECIDE** Real read isolation. `read-only` stops writes but not reads, so it does not meet the user's stated requirement that the bot cannot read anything. Custom permission profiles exist, but upstream issues #22179 (deny-globs not blocking reads in 0.130.0) and #5237 (reading outside the working directory) were not tested. Options: a dedicated unprivileged user, or a container with nothing mounted.
- 🔴 **P3 · BUILD** `codex_interface.py` is behind the other interfaces: it still uses `cwd` rather than `session_dir`, has no timeout, retry or session continuity, and its `_resolve_persona()` has no fallback to the `persona` argument. `AGENTS.md` is read as project instructions, not a system prompt, so persona adherence may be weaker.
- 🔴 **P3 · DECIDE** OAuth hardening (planned 2026-09-21, not approved, revised after review):
  - Verify `codex login --device-auth` (OpenAI's documented headless flow) in the container and document it in the README. It requires device-code login enabled in the ChatGPT account's security settings. Copying `auth.json` from another machine is a documented fallback, deliberately not planned.
  - Add `initialise_codex()` mirroring `initialise_claude()`'s role: log the access type and, for OAuth, check `codex login status` and warn when there is no login. Call it from `initialise_llm_services()`. It does not start a service and never touches `auth.json`.
  - In `_run_query()`: a timeout using `AGENT_QUERY_TIMEOUT_SECONDS` like Claude's, and a distinct log for an authentication failure in stderr (`agent_errors.py` not reviewed for fit).

**Decided**
- Claude's `setup-token`, `LLM_CLAUDE_TOKEN` and environment-variable bridge are not replicated for Codex. Its login is an `auth.json` of access and refresh tokens that the CLI rewrites after each refresh, so a copy in `config.ini` would go stale and re-writing it at startup would overwrite a newer file.
- `test_llm_tokens()` is unchanged, since skipping a provider with an empty token is the intended convention. Removed on review: the `config_sample.ini` `API_KEY` wording, and wiring `chat.json` with `--skip-git-repo-check` as part of the OAuth work.

**Open Questions**
- 🔴 **P3 · DECIDE** Whether Codex should back chat at all, given the API providers have no filesystem access by design.
- 🔴 **P3 · DECIDE** Whether to add `"web_search"` for parity with Claude.
- 🔴 **P3 · TEST** Concurrent `codex exec` processes may race refreshing the same `auth.json`. Unverified, with a per-provider `asyncio.Lock` as the fallback at the cost of serialising Codex calls.
- 🔴 **P3 · CHECK** Whether `bot_directory/codex` is writable by `bot_sanctuary_usr` (uid 1000). If the host folder is missing, Docker creates it as root and login writes would break. The Claude mount is identical, so if Claude's login persists, Codex's will too. Verify on the host.
- 🔴 **P3 · CHECK** Whether a subscription-based ChatGPT login is permitted for always-on automated use under OpenAI's terms. Not checked.
- 🔴 **P3 · CHECK** Reasoning levels: whether `low`, `medium` and `minimal` exist for Codex, and which levels each model accepts, was not confirmed. Model names change, so confirm with `/model`.
