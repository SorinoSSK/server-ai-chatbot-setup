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

**Timeout**, per draft, measured from creation (see `utils_telegram/draft_timer.py`):
- `DRAFT_CLOSE_SECONDS - DRAFT_WARNING_LEAD_SECONDS - DRAFT_TYPING_LEAD_SECONDS`
  (52 min by default): a "typing..." indicator starts.
- `DRAFT_CLOSE_SECONDS - DRAFT_WARNING_LEAD_SECONDS` (53 min by default):
  typing stops, a warning is sent asking the user to resend when ready.
- `DRAFT_CLOSE_SECONDS` (55 min by default): the draft is silently cleared -
  no further message, the warning already covered it. Kept comfortably under
  Telegram's 1-hour file link guarantee.

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
{"task_id": "...", "type": "text", "text": "..."}
```

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
