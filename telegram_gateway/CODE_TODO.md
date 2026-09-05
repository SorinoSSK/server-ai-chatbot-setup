# TODO — Graceful `session_reset` (deferred reset + crash-resilient ack)

Status: **§0-§8 implemented (§8: direction C - A + B).** The remaining open question (§8's UX
consequence - an unsignalled reset landing immediately behind a single reply after a lull) is a
conscious, separate, not-yet-decided call - see the "Open questions" section at the bottom.

## Goal

Defer a `session_reset` until any in-flight task for that chat naturally completes (rather than
forcibly interrupting an open poll/draft), survive a gateway crash without silently losing track
of a reset that's still owed, and keep the orchestrator positively informed when a reset actually
happens.

---

## 0. Module layout — new `utils_session/` folder

All session-reset business logic (state transitions, whitelist enforcement, orchestrator ack,
crash-recovery resync, chat notice) is consolidated into a new module, a peer of `utils_redis/`,
`utils_telegram/`, and `utils_queue/`:

```
telegram_gateway_application/utilities/utils_session/
    session_reset_handler.py
```

- [x] `session_reset_handler.py` owns:
  - `_is_reset_allowed(chat_id)` — whitelist check (§7)
  - `handle_session_reset_request(task_id, chat_id)` — replaces the current
    `_handle_session_reset()` body: whitelist check, then defer-or-immediate (§1)
  - `resolve_pending_reset_if_ready(chat_id)` — called from `_handle_completed`/`_handle_error`
    after task mapping deletion (§3)
  - `_apply_session_reset(chat_id)` — the single place a reset actually takes effect (§4)
  - `push_session_cleared(chat_id, session_id)` — orchestrator-facing ack (§4)
  - `RESET_NOTICE_MESSAGE` (global variable) + `send_reset_notice(chat_id)` — chat-facing notice
    (§6)
  - `resync_pending_resets()` — startup crash-recovery sweep (§5)
- [x] `utils_redis/database.py` keeps owning the raw Redis primitives for the pending-reset store
  (`set_pending_reset`, `get_pending_reset`, `clear_pending_reset`, `get_all_pending_resets`,
  `reset_session`'s return-value change) — consistent with database.py already being the sole
  owner of every other Redis key type (task/poll/draft/session). `utils_session` calls into these,
  it doesn't reimplement Redis access itself.
- [x] `utils_queue/message_handler.py` changes to a thin delegate:
  - `_handle_session_reset(task_id, chat_id)` → calls `handle_session_reset_request(...)`
  - `_handle_completed`/`_handle_error` → call `resolve_pending_reset_if_ready(chat_id)` after
    `delete_task_mapping(...)`
- [x] `utilities/initialise.py` imports `resync_pending_resets` from the new module and calls it
  during startup (§5).
- [x] `gateway_outbound.py` is untouched by this feature beyond providing the existing
  `send_message()` that `send_reset_notice()` calls into — no session-specific state lives there.

---

## 1. Detection & deferral

`handle_session_reset_request(task_id, chat_id)` (`utils_session/session_reset_handler.py`):

- [x] Whitelist check first (§7) — reject/log and stop if `chat_id` isn't allowed to trigger a
      reset.
- [x] Check `session_tasks:<chat_id>` (existing SET, see `create_task_mapping()`/CCR-013).
  - Non-empty → **defer** (§2). No user-facing message at this point (§6 confirms no ack is sent
    while deferred).
  - Empty → apply the reset immediately (§4).

---

## 2. Durable pending-reset store — Redis, **no TTL**

- [x] New key: `pending_reset:<chat_id> → task_id` (plain string, `nx=False` so a repeat trigger
      just overwrites the existing entry).
- [x] **No TTL.** This store must outlive whatever task/session it's tracking — a task can
      legitimately stay open for an unknown/unbounded duration, so any expiry risks silently
      dropping a genuinely pending reset before it's resolved, which would defeat the entire
      point of moving this to Redis instead of an in-memory variable. `redis_write(...,
      ttl_seconds=None)` (the existing default) covers this — just don't pass a TTL.
- [x] Resolved only by an explicit `clear_pending_reset()` call — either on natural completion
      (§3) or during crash-recovery resync (§5). Never by expiry.
- [x] New `database.py` functions, mirroring existing style (`get_all_poll_ids()`,
      `get_all_chat_draft_ids()`):
  - `set_pending_reset(chat_id: int, task_id: str) -> bool`
  - `get_pending_reset(chat_id: int) -> str | None`
  - `clear_pending_reset(chat_id: int) -> bool`
  - `get_all_pending_resets() -> list[tuple[int, str]]` (SCAN `pending_reset:*`)

---

## 3. Resolution on natural completion

`_handle_completed` / `_handle_error` (`utils_queue/message_handler.py`), after
`delete_task_mapping(...)`:

- [x] Call `resolve_pending_reset_if_ready(chat_id)` (`utils_session/session_reset_handler.py`):
  - If `get_pending_reset(chat_id)` is set **and** `session_tasks:<chat_id>` is now empty:
    - `clear_pending_reset(chat_id)`
    - Apply the reset (§4)

---

## 4. Centralised reset application + orchestrator ack

- [x] `reset_session(chat_id)` (`utils_redis/database.py`) changes to **return** the `session_id`
      it wiped (`str | None`), captured via a read before deletion — instead of `None`.
- [x] New `_apply_session_reset(chat_id)` helper (`utils_session/session_reset_handler.py`):
  ```python
  def _apply_session_reset(chat_id: int) -> None:
      cleared_session_id = reset_session(chat_id)
      if cleared_session_id:
          push_session_cleared(chat_id, cleared_session_id)
          send_reset_notice(chat_id)
  ```
- [x] New `push_session_cleared(chat_id, session_id)` (`utils_session/session_reset_handler.py`)
      — publishes onto `Q_CHANNEL_OUT`:
  ```json
  {"task_id": null, "session_id": "<cleared>", "chat_id": <chat_id>, "type": "session_cleared"}
  ```
  The orchestrator's positive confirmation that this specific `session_id` is gone on the
  gateway side. Deferred import of `queue_push_task`, same pattern as
  `error_handling.py::push_tier1_delivery_failed()` and
  `poll_response_handler.py::_push_poll_answer()` (avoids the `queue.py` →
  `message_handler.py` → ... → `queue.py` circular import).
- [x] Used by both the immediate path (§1) and the deferred/resolved path (§3) — one function,
      called from the one place a reset actually applies, regardless of which path got there.

---

## 5. Crash recovery

On startup (`initialise_application()`, `utilities/initialise.py`), **confirmed to run after**
the existing `close_orphaned_drafts()` / `close_orphaned_polls()` sweeps have both completed:

- [x] New `resync_pending_resets()` (`utils_session/session_reset_handler.py`):
  ```python
  for chat_id, task_id in get_all_pending_resets():
      if <session_tasks:{chat_id} is now empty>:
          # task actually finished while the gateway was down (its completed/error event
          # was already redelivered and processed, or otherwise resolved)
          clear_pending_reset(chat_id)
          _apply_session_reset(chat_id)          # normal session_cleared ack (§4)
      # else: still genuinely in flight - leave it. No separate signal is sent (no
      # "reset_pending" event - see below). resolve_pending_reset_if_ready() (§3) will pick
      # it up naturally once the real completed/error event for that task_id arrives.
  ```
- [x] **No `reset_pending` event.** Only entries that are *already resolvable* at startup are
      acted on; anything still genuinely in flight is left untouched in Redis (no TTL, per §2)
      and is picked up later by the normal completion hook (§3) — no separate recovery-time
      notification type exists.

---

## 6. User-facing notification (Telegram side) — no ack, no copied text

No pending/done ack pair, no message during the defer/wait window, and no message text written
into this plan or hardcoded into the function. A single global variable holds whatever text is
currently set — `send_reset_notice()` always sends exactly what's in it, nothing computed,
nothing chosen at random, nothing embedded in the function body. The value itself will be filled
in separately, directly in the file.

Fires once, after a reset actually takes effect, for **every** `chat_id` whose session gets
cleared — not just the `chat_id` that triggered it. This closes the gap in the old behaviour
where only the chat that triggered the `session_reset` would ever hear about it — a broader
reset touching multiple chats (one `session_reset` message per affected `chat_id`) left every
other affected chat with no notice at all. Calling this from the one centralised place a reset
actually applies (`_apply_session_reset(chat_id)`, §4) fixes that uniformly.

- [x] `utils_session/session_reset_handler.py`:
  ```python
  RESET_NOTICE_MESSAGE: str = ""   # set directly here - not chosen/generated at send-time

  def send_reset_notice(chat_id: int) -> None:
      """
      Informs a chat that its session has just been reset.

      Args:
          chat_id (int)

      Returns:
          None

      Notes:
          - Always sends exactly what's currently set in RESET_NOTICE_MESSAGE - no copy is
            chosen/generated here; the value is maintained directly in this file.
          - No-op (logged) while RESET_NOTICE_MESSAGE is unset, rather than sending an empty
            message.
          - Called for every chat_id whose session is actually cleared - not only the chat_id
            that triggered the reset - so a broader reset touching multiple chats notifies each
            one individually, not just the initiator. See _apply_session_reset() (§4).
          - Fires once, after the reset has already taken effect - no separate notice while a
            deferred reset is still waiting on an in-flight task.
      """
      if not RESET_NOTICE_MESSAGE:
          logger.warning(f"RESET_NOTICE_MESSAGE is unset - no reset notice sent for chat_id={chat_id}.")
          return
      send_message(chat_id, RESET_NOTICE_MESSAGE)
  ```
- [x] `send_message` is imported from `gateway_outbound.py` — the actual Telegram call still
      lives there; only the message content and the decision to send live in `utils_session`.

---

## 7. Whitelist — who can trigger a session reset

New `config.py` setting, following the exact existing pattern used for
`TELEGRAM_ALLOWED_CHAT_IDS` (comma-separated env var → a `set[int]`, empty default):

- [x] `config.py`:
  ```python
  # Session Reset (see utils_session/session_reset_handler.py)
  DEFAULT_SESSION_RESET_ALLOWED_CHAT_IDS = ""
  self.SESSION_RESET_ALLOWED_CHAT_IDS = {
      int(chat_id.strip())
      for chat_id in (os.getenv("SESSION_RESET_ALLOWED_CHAT_IDS") or DEFAULT_SESSION_RESET_ALLOWED_CHAT_IDS).split(",")
      if chat_id.strip().lstrip("-").isdigit()
  }
  ```
- [x] `config_sample.ini` gets the matching new key, same as `TELEGRAM_ALLOWED_CHAT_IDS` today.
- [x] Enforced in `handle_session_reset_request(task_id, chat_id)` (§1), first thing, before any
      deferral/immediate-reset decision:
  ```python
  def _is_reset_allowed(chat_id: int) -> bool:
      return chat_id in settings.SESSION_RESET_ALLOWED_CHAT_IDS
  ```
  A `chat_id` not in the whitelist is logged and dropped — no defer, no reset, no notice, no
  orchestrator ack. **Decided: silent (log only), no response of any kind.**

---

## 8. Gap: a task's `completed`/`error` may never arrive, leaving a deferred reset stuck forever

Confirmed by re-checking each mechanism directly. Two independent causes, both landing on the same
symptom - `session_tasks:<chat_id>` never truly empties, so `has_open_tasks()` returns `True`
forever for that chat, and any `pending_reset:<chat_id>` behind it can never resolve via
`resolve_pending_reset_if_ready()` (§3) or `resync_pending_resets()` (§5) - stuck, with nothing in
the current design able to clear it:

- **Draft/image timeout — not an issue.** A draft never has a `task_id` at all. Per
  `gateway_inbound.py`, `create_task_mapping()` (i.e. `task_id` creation) only happens inside
  `_push_task()`, which only runs once a draft is **finalised** by an incoming instruction/caption
  (the `existing_draft` → `_push_task(...)` block). A draft that instead hits its
  `DRAFT_CLOSE_SECONDS` hard cap and expires unfinalised never reaches that line — no `task_id` is
  ever created for it, so it has no bearing on `session_tasks:<chat_id>` or a pending reset.
  Nothing to handle here.
- **Poll timeout — real gap.** A poll *is* tied to an existing `task_id` (created before the poll
  was ever sent, via `_handle_poll()` → `create_task_mapping()`). When a poll's
  `POLL_TIMEOUT_SECONDS` elapses unanswered, `_finalise_poll()` sends a Telegram "didn't hear back"
  message but — per its own existing design/comment — pushes **nothing** onto the outbound
  RabbitMQ queue. Nobody downstream is ever told the poll ended. The orchestrator itself is a
  pass-through/router - it forwards a response to whichever agent currently owns `task_id`, it
  doesn't hold business logic about polls or timeouts - so it's specifically **that agent** that's
  left with nothing to act on. If it was waiting on the poll's answer before sending
  `completed`/`error` for the task, the task_id can stay open in `session_tasks:<chat_id>`
  indefinitely, and by extension a deferred `pending_reset` for that chat_id would never resolve.
- **Orphaned/expired task mapping — real gap, independent of polls.** `session_tasks:<chat_id>`
  membership is removed *only* by `delete_task_mapping()`, called *only* from
  `_handle_completed`/`_handle_error` when a terminal event actually arrives and is processed.
  `task:<task_id>` itself, separately, carries its own TTL (`REDIS_TASK_MAPPING_TTL_SECONDS`, 24h
  default) that has no relationship to that SET membership at all. So if a `completed`/`error` for
  some `task_id` is ever lost - dropped after `Q_CONSUME_MAX_ATTEMPTS` retries, or simply arriving
  after `task:<task_id>` has already TTL-expired (in which case `process_message()` drops it at the
  `get_task_mapping()` check, *before* `_handle_completed`/`_handle_error` ever runs, so
  `delete_task_mapping()` never gets called for it either) - that `task_id` is left indexed under
  `session_tasks:<chat_id>` permanently. Unlike the poll case, this doesn't depend on how the poll
  contract behaves, and it doesn't self-heal with more chat activity - a stale entry is never
  cleaned up just because the user keeps messaging; new messages only add further (legitimately
  open) task_ids alongside it.

Both causes undermine §1/§3's core assumption — that every open `task_id` will eventually receive a
`completed`/`error` event. Neither is guaranteed today.

**Related, but not itself a bug - a UX consequence worth being aware of.** Per §6, nothing is sent
to the chat while a reset is only deferred/waiting - so the moment `session_tasks:<chat_id>`
*legitimately* empties (no orphaning, no bug), the reset applies immediately and silently, with no
forewarning. In a continuous back-to-back conversation, a new task is typically already open before
the previous one clears, so the empty-queue moment - and the reset - keeps getting pushed out
naturally. But if the user sends a single message after a lull and that happens to be the task
that finally empties the queue, the reset (and its notice, §6) lands immediately behind that one
reply, with no warning it was ever pending - which can read as abrupt. This is the deferred design
behaving exactly as specified (§1/§6), not a defect, but worth a conscious decision on whether it's
acceptable as-is.

### Candidate directions - **Decided and implemented: C (A + B).**

- [x] **A — close the information gap at the source.** Have `_finalise_poll()` push *something* to
  the outbound queue on an unanswered timeout too (not just when answered) — e.g. a
  `poll_answer: null`/empty signal, or a dedicated `poll_timed_out` event, carrying `task_id` like
  every other response payload. The orchestrator needs no new logic of its own here - it just
  routes this event to whichever agent currently owns `task_id`, exactly the same task_id-keyed
  forwarding it already does for a real poll answer, a text reply, etc. **The decision belongs to
  that agent** (re-ask, treat as declined, escalate, or simply send back `completed`/`error`,
  which is what actually clears `session_tasks:<chat_id>` and lets §3 resolve a deferred reset) -
  not to the orchestrator, and not to the gateway. This is the root-cause fix, but it's a
  behaviour change to the poll contract beyond just session-reset (today's design deliberately
  pushes nothing on an unanswered timeout), so it needs sign-off independent of this feature, and
  its resolution depends on every agent implementation actually handling the new signal.
  Implemented as a dedicated `poll_timed_out` event - see
  `poll_response_handler.py::_push_poll_timed_out()`, README.md.
- [x] **B — bounded grace period on the gateway side.** Give a pending reset a ceiling independent of
  ever hearing a `completed`/`error` back for that task_id: if it's been pending longer than some
  `PENDING_RESET_MAX_WAIT_SECONDS`, force the reset through anyway (treat every task_id still
  indexed under that chat as abandoned for reset purposes only — `task:<task_id>`/
  `session_tasks:<chat_id>` need clearing too, since otherwise they'd sit there stale forever even
  after being force-reset). Needs a timestamp alongside the existing `pending_reset:<chat_id> →
  task_id` entry, and *some* periodic mechanism to check the ceiling (there's currently nothing
  that revisits a pending reset other than `_handle_completed`/`_handle_error`/startup resync) —
  worth noting this reintroduces the kind of "watchdog" idea dropped earlier, but now for a
  concretely identified reason rather than a speculative one. **Cause-agnostic by construction** -
  it doesn't check *why* `session_tasks:<chat_id>` never emptied, only *how long* it's been
  pending, so it equally backstops the poll-timeout cause above *and* the orphaned/expired-mapping
  cause above, without needing to detect either one specifically.
  Implemented as `PENDING_RESET_MAX_WAIT_SECONDS` (config.py) + a `created_at` timestamp on
  `pending_reset:<chat_id>` (`set_pending_reset()`/`get_all_pending_resets()`, `utils_redis/database.py`)
  + a periodic sweep thread (`enforce_pending_reset_ceiling()`,
  `start_pending_reset_ceiling_sweep()`/`stop_pending_reset_ceiling_sweep()`, run from
  `utilities/initialise.py`, interval `PENDING_RESET_SWEEP_INTERVAL_SECONDS`) + the same check folded
  into `resync_pending_resets()` (§5) so a startup resync doesn't have to wait for the next sweep tick
  if an entry is already expired.
- [x] **C — both (recommended).** A is still the right root-cause fix for the poll-specific case -
  cheap for the orchestrator (one more type to pass through, no embedded poll/timeout logic) and
  puts the decision where the context already lives, with whichever agent is currently in charge.
  But A only ever addresses the poll cause, and even there its resolution is entirely in that
  agent's hands - a bug, a crash, a dropped message, or an agent that's no longer around for that
  task_id all leave the gap exactly as open as before. B is a gateway-side backstop that catches
  both causes at once, independent of anything downstream ever behaving correctly - useful as
  permanent defence-in-depth, not just as a stand-in for while A hasn't shipped yet. Given the
  orphaned/expired-mapping cause has no direction-A equivalent (there is no "orchestrator behaviour
  change" that fixes a message RabbitMQ already dropped), **B is not optional under C - it's the
  only fix for that cause**.

Note: the UX consequence noted above (an immediate, unsignalled reset landing right behind a single
reply after a lull) is **not** addressed by either A or B - both are about making sure a reset
*eventually* applies; neither changes the "no warning beforehand" behaviour from §6. Left as a
conscious, separate decision - see open questions below.

### Also to fold back in regardless of direction chosen

- [x] `_apply_session_reset(chat_id)` (§4) must still call `stop_draft_timer(chat_id)` before/
      alongside `reset_session()` — a draft can be actively accumulating independently of whether
      `session_tasks:<chat_id>` is empty (drafts have no `task_id`), so the immediate-reset path
      still needs to stop that in-memory timer itself, same as the current CCR-012 fix in
      `message_handler.py` does today. This was missing from §0–§7 above and needs restoring so
      the orphan-draft-timer fix (CCR-012) isn't regressed by this refactor.
- [x] `stop_poll_for_reset()` (the forced, silent poll-interrupt added for CCR-012) - **decided:
      repurposed, not removed.** Still unreachable on the normal deferred-wait path (an open poll
      always has an open `task_id`, so it's never force-closed while genuinely waiting), but now
      called defensively by `_force_apply_session_reset()` (direction B's force-through step) in
      case `PENDING_RESET_MAX_WAIT_SECONDS` is ever misconfigured shorter than a poll's own maximum
      lifetime (`POLL_GLOBAL_CAP_SECONDS`) - in practice a no-op given a sane default, but cheap
      defence-in-depth against that misconfiguration rather than dead code to delete.

---

## Open questions

1. ~~Which of A/B/C (§8) to adopt.~~ **Decided and implemented: C.**
2. ~~Whether to remove `stop_poll_for_reset()` or repurpose it.~~ **Decided and implemented:
   repurposed** for direction B's force-through step.
3. Whether the §8 UX consequence (an unsignalled reset landing immediately behind a single reply
   after a lull) needs its own mitigation (e.g. a short additional grace delay before applying even
   on the natural-empty path, not just B's force-through ceiling), or is accepted as-is per §6's
   existing "no warning during the wait" decision. **Still open** - not addressed by A or B, a
   separate call.
