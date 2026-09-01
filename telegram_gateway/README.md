# Telegram Gateway

The Telegram Gateway is the sole interface between the Telegram Bot API and
the rest of the AI agent system. It translates Telegram messages and inline
keyboard button interactions into internal queue messages (and vice versa),
so no other container talks to Telegram directly. It is also responsible for
rendering inline keyboard buttons (Accept / Reject / Request Revision, mode
selection) and for triggering the user's global session reset.

All application code runs inside a Docker container - there is no
standalone (non-Docker) execution path.

## Infrastructure
Python application root is located at
```
telegram_gateway/telegram_gateway_application
```
- Python 3.12 (`python:3.12.4-slim` base image)
- Runs as a Docker container on the project's isolated bridge network (`chatbot-app-network`)
- Depends on RabbitMQ for internal messaging (not yet implemented)
- Depends on the Telegram Bot API via a bot token (not yet implemented)

Under development.

## Getting Started (Development)
The Telegram Gateway container is intended to be managed by the project's
root `./setup.sh` script (run from the `server-ai-chatbot-setup` root
directory) and is not typically invoked directly. You may use the helper
script, `setup.sh`, for standalone `telegram_gateway` development.

### Project Helper Script
Run `setup.sh` from the root directory of the `telegram_gateway` project.
```bash
./setup.sh
```

### Device First-Time Setup
**Step 1:** Run helper script
```bash
./setup.sh
```
**Step 2:** Select option 1 to build and run the project
```
1
```

### Useful Docker Commands
```bash
docker ps
docker images
docker rmi <docker-image-name>
docker start <docker-container-name>
docker stop <docker-container-name>
docker restart <docker-container-name>
```

## Documentation
Under development.

### Task Queue Payload (gateway -> backend)

Every task the gateway pushes to RabbitMQ (`Q_CHANNEL_OUT`) shares one shape,
regardless of whether it originated from plain text or from a finalised draft:

```json
{"task_id": "...", "text": "...", "image_url": "...", "video_url": "...", "file_url": "..."}
```

- `text`: always present, `""` if the update carried no text.
- `image_url` / `video_url` / `file_url`: at most one is ever non-empty - the
  other two are always `""`. Resolved from Telegram's `getFile` endpoint, so
  the URL embeds the bot token and is only guaranteed valid by Telegram for
  at least 1 hour - the backend should download promptly rather than persist the URL.

#### Pending drafts (media without an instruction yet)

A photo/video/document arriving **without** a caption, or with one but no
further text, is not immediately turned into a task - it is staged as a
Redis-backed draft (one per `chat_id` at a time) until a text update finalises it:

- Media with a caption: the caption is stored as the draft's initial text.
  The next text update is appended onto it (`caption + " " + text`) and the
  task is pushed immediately.
- Media with no caption: the next text update becomes the task's `text`
  outright, and the task is pushed immediately.
- Further media (single item or album) arriving while a draft is already
  pending is **not** stored - the user is reminded about the existing draft instead.
- Album items (Telegram sets `media_group_id` on each item, delivered as
  separate updates) are never staged as a draft - the user is asked to resend
  them one at a time with individual instructions. The reply is sent once per
  album, not once per item.
- Whether the finalising text still applies to the pending media (e.g. the
  user changed their mind) is not decided by the gateway - it always attaches
  the draft's media to whatever text finalises it; that judgement call is left to the backend.

**Timeout**, per draft, is a repeating keep-alive cycle rather than a single
countdown (see `utils_telegram/utilities/image_draft_handler.py`). Each cycle
is `DRAFT_CYCLE_SECONDS` long (5 min by default) and has two "typing..."
windows, one immediately before each of the two messages a cycle can send:
- `DRAFT_CYCLE_SECONDS - DRAFT_CYCLE_NOTICE_LEAD_SECONDS - DRAFT_TYPING_LEAD_SECONDS`
  into the cycle (1 min by default): a "typing..." indicator starts.
- `DRAFT_CYCLE_SECONDS - DRAFT_CYCLE_NOTICE_LEAD_SECONDS` into the cycle
  (2 min by default): typing stops, a notice is sent asking if the user
  needs more time, with a "Give me a little while more" button attached.
- `DRAFT_CYCLE_SECONDS - DRAFT_TYPING_LEAD_SECONDS` into the cycle (4 min by
  default): if the button still hasn't been pressed, "typing..." starts again.
- `DRAFT_CYCLE_SECONDS` into the cycle (5 min by default): typing stops. If
  the button wasn't pressed by now (and the draft wasn't finalised), the
  cycle simply ends and the **next** scheduled cycle begins - sending its own
  notice at its own 2 min mark, and so on - **unless** this was the final
  cycle, in which case the draft is cleared and the user is told the bot
  will get to it later.

The number of cycles is fixed by `DRAFT_CLOSE_SECONDS / DRAFT_CYCLE_SECONDS`
(11 cycles at the defaults above, i.e. 55 min total - kept comfortably under
Telegram's 1-hour file link guarantee) and runs its course regardless of
whether the button is ever pressed. Pressing the button at any point up to a
cycle's end (including during the second "typing..." window) sends a short
acknowledgement and **skips ahead** to the next scheduled cycle immediately,
instead of waiting out the rest of the current one - it does not add extra
cycles beyond the fixed total. The final cycle's notice has no button
instead, since there's no further cycle to skip ahead to - if it still
isn't finalised by the end of that cycle, the draft is cleared the same way.

The keep-alive cycle above is **in-memory only** - it does not survive an
application restart, though the Redis-backed draft record itself does (it has
its own TTL, `DRAFT_MAPPING_TTL_SECONDS`, slightly beyond `DRAFT_CLOSE_SECONDS`,
as a backstop). Since the loop's progress isn't persisted, a restart would
otherwise leave a draft silently pending with no further notices and no close
message, for up to that TTL. To avoid this, `close_orphaned_drafts()` sweeps
Redis for any leftover drafts on startup, before polling resumes, and closes
each one out immediately (draft deleted, close message sent) rather than
attempting to resume it part-way through a cycle.

### Response Queue Message Payloads

Messages consumed by the gateway from the response queue (agent -> gateway)
all share a common envelope:

```json
{"task_id": "...", "type": "<type>", ...}
```

`task_id` is required on every payload and correlates back to a
`chat_id`/`user_id` stored in Redis - responses never carry chat/user
identity directly, keeping agents identity-blind. `type` selects which of
the payload shapes below applies. A separate `typing` type also exists
(used to sustain the "typing..." indicator) and is not documented here.

#### `poll`
Maps to Telegram's `sendPoll`.
```json
{
  "task_id": "...",
  "type": "poll",
  "question": "...",
  "options": ["...", "..."],
  "is_anonymous": true,
  "allows_multiple_answers": false
}
```
- `question`: 1-300 characters. If missing, the whole poll is dropped and logged.
- `options`: 1-12 items, each 1-100 characters. Null/empty entries are
  filtered out; the poll is sent with whatever remains.

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
- `items`: any number of entries. Telegram's `sendMediaGroup` only accepts
  2-10 per call, so the gateway handles the edge cases automatically:
  - 1 item: sent via `sendPhoto`/`sendVideo` instead of a media group.
  - More than 10: split into multiple `sendMediaGroup` calls of up to 10
    each - if the final chunk has only 1 item, it falls back the same way.
- Each item's `type` must be `photo` or `video` - photos and videos can be
  mixed freely.
- Each item must have a non-empty `url` and a `type` of exactly `photo` or
  `video` - if any item fails this, the whole album is dropped and logged
  rather than sending a partial/broken result.
- No caption support - Telegram sets captions per item, not accepted here.
- No inline keyboard/buttons support on this type - Telegram's
  `sendMediaGroup` does not accept `reply_markup` at all.

#### `file`
Maps to Telegram's `sendDocument`.
```json
{"task_id": "...", "type": "file", "url": "...", "caption": "..."}
```
- `caption`: optional, see caption length note below.
- `url` is fetched by Telegram server-side, same as `image`/`video` - **but
  Telegram only supports sending a document by URL for `.pdf` and `.zip`
  files.** Any other file type sent this way is rejected; a direct
  multipart upload would be required instead, which is not implemented.

##### Caption length (`image`/`video`/`file`)
Telegram caps captions at 1024 characters and rejects the entire send if
exceeded, rather than truncating it. The gateway handles this automatically:
the caption is cut to the limit for the media send, and anything beyond
that is sent as a separate follow-up `sendMessage` instead of being lost
or causing the send to fail.

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
- `buttons`: optional. Rows of inline keyboard buttons, each
  `{"text": "...", "purpose": "...", "payload": {...}}`.
  - `purpose`: caller-defined tag, read back when the press is validated so
    the gateway knows how to route it.
  - `payload`: optional caller-defined context retrieved alongside the press.
  - Each button is registered with a bot-issued `callback_data` token (see
    `utils_telegram/utilities/button_prompt_handler.py`) - the agent never
    supplies `callback_data` directly.
  - A button that fails to register, or a keyboard that fails Telegram's
    size limits, is dropped; the message still sends as plain text.

#### `completed`
Terminal marker - no further payloads are expected for this `task_id`.
```json
{"task_id": "...", "type": "completed"}
```
Triggers cleanup only: stops the typing indicator if still active, and
deletes the `task_id` mapping from Redis.

#### `error`
Signals the task ended abnormally (e.g. an agent's token budget was
exhausted).
```json
{"task_id": "...", "type": "error", "error_type": "token_exhausted", "message": "300"}
```
- `error_type`: short machine-readable code. Currently recognised:
  - `token_exhausted` - sends a fixed persona message. `message` is reused
    (not a separate field) to carry `nap_duration_left` - seconds
    **remaining**, a countdown, not a fixed total - included in the reply
    if present and numeric; omitted otherwise.
  - Any other value (including `unknown`) - `message` is treated as
    free text and sent back to the user, wrapped in a persona-styled HTML
    message (Telegram `parse_mode` `HTML`, `message` is HTML-escaped
    before being embedded).
- Same cleanup as `completed`, plus a user-facing notification.

## TODO
- **Collect poll answers.** The gateway can currently only send polls
  (`send_poll()`/`type: "poll"`) - it has no wiring to receive results.
  To support this:
  - Add `poll_answer` (and/or `poll`) to `TELEGRAM_ALLOWED_UPDATES`.
  - Add a handler in `gateway_inbound.py` for the `poll_answer` update type.
  - Decide how a `poll_answer` correlates back to a `chat_id`/task, similar
    to how `utils_telegram/utilities/button_prompt_handler.py` correlates
    callback_query presses via a registered token.
  - Note: anonymous polls (`is_anonymous: true`, the current default in
    `send_poll()`) never expose the real voter's identity to the bot -
    `is_anonymous` must be `false` for a poll to support per-user answers.
