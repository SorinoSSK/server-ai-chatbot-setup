# TODO Record for Telegram Gateway

## Agent-call access tier — whitelist for `bot_sanctuary`

Status: **Implemented, reusing `SESSION_RESET_ALLOWED_CHAT_IDS` rather than a new whitelist.** Cross-service follow-up flagged from `bot_sanctuary/CODE_TODO.md` — `bot_sanctuary`'s multi-agent "Call" model (Chat [persona: Rukia] + Architect/Coder/Review/Documentation) needs to know, per task, whether the requesting `chat_id` is allowed to reach any Call beyond Chat. `telegram_gateway` is the right owner since it's the only component that knows chat_id identity — `bot_sanctuary` should not need its own whitelist lookup.

### Goal

Same precedent as `SESSION_RESET_ALLOWED_CHAT_IDS` (§7 above) — comma-separated env var → `set[int]` — but used to **tag**, not **gate**: a non-whitelisted `chat_id`'s task still proceeds normally, just scoped to the Chat Call only by `bot_sanctuary`. This is deliberately different from `SESSION_RESET_ALLOWED_CHAT_IDS`'s silent-drop behaviour — nothing here is rejected or logged-only; every chat_id gets a working conversation, just with a different agent-access tier.

- [x] No new `config.py` setting added — **decided: reuse the existing `SESSION_RESET_ALLOWED_CHAT_IDS` whitelist** (§7 above) instead of introducing a separate `AGENT_CALL_ALLOWED_CHAT_IDS`. A `chat_id` permitted to trigger a `session_reset` is treated as the same tier permitted full agent-call access — one whitelist, two consumers, rather than two whitelists that would need to be kept in sync by hand. `config_sample.ini` needed no new key as a result.
- [x] Stamped in `gateway_inbound.py::_push_task()` — the outbound task payload always carries:
  ```python
  "coding_allowed": chat_id in settings.SESSION_RESET_ALLOWED_CHAT_IDS
  ```
  Field name finalised as `coding_allowed` (not `full_access`, the placeholder above). Always present on every task payload — `True` if `chat_id` is whitelisted, `False` by default otherwise. See README.md's Task Queue Payload section.
- [x] Scoped to the payload built in `_push_task()` only (plain text/finalised-draft tasks) — the poll-answer/poll-timed-out pushes (`poll_response_handler.py`) and the delivery-failure/gateway-alert events (`error_handling.py`) do not currently carry `coding_allowed`, since those call sites resolve only `task_id`→`session_id` and don't have `chat_id` on hand. Extending it there, if `bot_sanctuary` needs it on every payload type rather than just the initial task, is open follow-up work.
- [x] No enforcement on this side beyond the tag itself — `bot_sanctuary` is the one that actually restricts which Calls a tagged-Chat-only task can reach; `telegram_gateway`'s job here is purely to know and stamp identity, consistent with its existing "translate only, no downstream business logic" role.

---

## Graceful `session_reset` (deferred reset + crash-resilient ack)

Status: **§0-§8 implemented (§8: direction C - A + B).** The remaining open question (§8's UX consequence - an unsignalled reset landing immediately behind a single reply after a lull) is a conscious, separate, not-yet-decided call - see the "Open questions" section at the bottom.

### Goal

Defer a `session_reset` until any in-flight task for that chat naturally completes (rather than forcibly interrupting an open poll/draft), survive a gateway crash without silently losing track of a reset that's still owed, and keep the orchestrator positively informed when a reset actually happens.

---

### 0. Module layout — new `utils_session/` folder

All session-reset business logic (state transitions, whitelist enforcement, orchestrator ack, crash-recovery resync, chat notice) is consolidated into a new module, a peer of `utils_redis/`, `utils_telegram/`, and `utils_queue/`:

```
telegram_gateway_application/utilities/utils_session/
    session_reset_handler.py
```

- [x] `session_reset_handler.py` owns:
  - `_is_reset_allowed(chat_id)` — whitelist check (§7)
  - `handle_session_reset_request(task_id, chat_id)` — replaces the current `_handle_session_reset()` body: whitelist check, then defer-or-immediate (§1)
  - `resolve_pending_reset_if_ready(chat_id)` — called from `_handle_completed`/`_handle_error` after task mapping deletion (§3)
  - `_apply_session_reset(chat_id)` — the single place a reset actually takes effect (§4)
  - `push_session_cleared(chat_id, session_id)` — orchestrator-facing ack (§4)
  - `RESET_NOTICE_MESSAGE` (global variable) + `send_reset_notice(chat_id)` — chat-facing notice (§6)
  - `resync_pending_resets()` — startup crash-recovery sweep (§5)
- [x] `utils_redis/database.py` keeps owning the raw Redis primitives for the pending-reset store (`set_pending_reset`, `get_pending_reset`, `clear_pending_reset`, `get_all_pending_resets`, `reset_session`'s return-value change) — consistent with database.py already being the sole owner of every other Redis key type (task/poll/draft/session). `utils_session` calls into these, it doesn't reimplement Redis access itself.
- [x] `utils_queue/message_handler.py` changes to a thin delegate:
  - `_handle_session_reset(task_id, chat_id)` → calls `handle_session_reset_request(...)`
  - `_handle_completed`/`_handle_error` → call `resolve_pending_reset_if_ready(chat_id)` after `delete_task_mapping(...)`
- [x] `utilities/initialise.py` imports `resync_pending_resets` from the new module and calls it during startup (§5).
- [x] `gateway_outbound.py` is untouched by this feature beyond providing the existing `send_message()` that `send_reset_notice()` calls into — no session-specific state lives there.

---

### 1. Detection & deferral

`handle_session_reset_request(task_id, chat_id)` (`utils_session/session_reset_handler.py`):

- [x] Whitelist check first (§7) — reject/log and stop if `chat_id` isn't allowed to trigger a reset.
- [x] Check `session_tasks:<chat_id>` (existing SET, see `create_task_mapping()`/CCR-013).
  - Non-empty → **defer** (§2). No user-facing message at this point (§6 confirms no ack is sent while deferred).
  - Empty → apply the reset immediately (§4).

---

### 2. Durable pending-reset store — Redis, **no TTL**

- [x] New key: `pending_reset:<chat_id> → task_id` (plain string, `nx=False` so a repeat trigger just overwrites the existing entry).
- [x] **No TTL.** This store must outlive whatever task/session it's tracking — a task can legitimately stay open for an unknown/unbounded duration, so any expiry risks silently dropping a genuinely pending reset before it's resolved, which would defeat the entire point of moving this to Redis instead of an in-memory variable. `redis_write(..., ttl_seconds=None)` (the existing default) covers this — just don't pass a TTL.
- [x] Resolved only by an explicit `clear_pending_reset()` call — either on natural completion (§3) or during crash-recovery resync (§5). Never by expiry.
- [x] New `database.py` functions, mirroring existing style (`get_all_poll_ids()`, `get_all_chat_draft_ids()`):
  - `set_pending_reset(chat_id: int, task_id: str) -> bool`
  - `get_pending_reset(chat_id: int) -> str | None`
  - `clear_pending_reset(chat_id: int) -> bool`
  - `get_all_pending_resets() -> list[tuple[int, str]]` (SCAN `pending_reset:*`)

---

### 3. Resolution on natural completion

`_handle_completed` / `_handle_error` (`utils_queue/message_handler.py`), after `delete_task_mapping(...)`:

- [x] Call `resolve_pending_reset_if_ready(chat_id)` (`utils_session/session_reset_handler.py`):
  - If `get_pending_reset(chat_id)` is set **and** `session_tasks:<chat_id>` is now empty:
    - `clear_pending_reset(chat_id)`
    - Apply the reset (§4)

---

### 4. Centralised reset application + orchestrator ack

- [x] `reset_session(chat_id)` (`utils_redis/database.py`) changes to **return** the `session_id` it wiped (`str | None`), captured via a read before deletion — instead of `None`.
- [x] New `_apply_session_reset(chat_id)` helper (`utils_session/session_reset_handler.py`):
  ```python
  def _apply_session_reset(chat_id: int) -> None:
      cleared_session_id = reset_session(chat_id)
      if cleared_session_id:
          push_session_cleared(chat_id, cleared_session_id)
          send_reset_notice(chat_id)
  ```
- [x] New `push_session_cleared(chat_id, session_id)` (`utils_session/session_reset_handler.py`) — publishes onto `Q_CHANNEL_OUT`:
  ```json
  {"task_id": null, "session_id": "<cleared>", "chat_id": <chat_id>, "type": "session_cleared"}
  ```
  The orchestrator's positive confirmation that this specific `session_id` is gone on the gateway side. Deferred import of `queue_push_task`, same pattern as `error_handling.py::push_tier1_delivery_failed()` and `poll_response_handler.py::_push_poll_answer()` (avoids the `queue.py` → `message_handler.py` → ... → `queue.py` circular import).
- [x] Used by both the immediate path (§1) and the deferred/resolved path (§3) — one function, called from the one place a reset actually applies, regardless of which path got there.

---

### 5. Crash recovery

On startup (`initialise_application()`, `utilities/initialise.py`), **confirmed to run after** the existing `close_orphaned_drafts()` / `close_orphaned_polls()` sweeps have both completed:

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
- [x] **No `reset_pending` event.** Only entries that are *already resolvable* at startup are acted on; anything still genuinely in flight is left untouched in Redis (no TTL, per §2) and is picked up later by the normal completion hook (§3) — no separate recovery-time notification type exists.

---

### 6. User-facing notification (Telegram side) — no ack, no copied text

No pending/done ack pair, no message during the defer/wait window, and no message text written into this plan or hardcoded into the function. A single global variable holds whatever text is currently set — `send_reset_notice()` always sends exactly what's in it, nothing computed, nothing chosen at random, nothing embedded in the function body. The value itself will be filled in separately, directly in the file.

Fires once, after a reset actually takes effect, for **every** `chat_id` whose session gets cleared — not just the `chat_id` that triggered it. This closes the gap in the old behaviour where only the chat that triggered the `session_reset` would ever hear about it — a broader reset touching multiple chats (one `session_reset` message per affected `chat_id`) left every other affected chat with no notice at all. Calling this from the one centralised place a reset actually applies (`_apply_session_reset(chat_id)`, §4) fixes that uniformly.

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
- [x] `send_message` is imported from `gateway_outbound.py` — the actual Telegram call still lives there; only the message content and the decision to send live in `utils_session`.

---

### 7. Whitelist — who can trigger a session reset

New `config.py` setting, following the exact existing pattern used for `TELEGRAM_ALLOWED_CHAT_IDS` (comma-separated env var → a `set[int]`, empty default):

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
- [x] Enforced in `handle_session_reset_request(task_id, chat_id)` (§1), first thing, before any deferral/immediate-reset decision:
  ```python
  def _is_reset_allowed(chat_id: int) -> bool:
      return chat_id in settings.SESSION_RESET_ALLOWED_CHAT_IDS
  ```
  A `chat_id` not in the whitelist is logged and dropped — no defer, no reset, no notice, no orchestrator ack. **Decided: silent (log only), no response of any kind.**

---

### 8. Gap: a task's `completed`/`error` may never arrive, leaving a deferred reset stuck forever

Confirmed by re-checking each mechanism directly. Two independent causes, both landing on the same symptom - `session_tasks:<chat_id>` never truly empties, so `has_open_tasks()` returns `True` forever for that chat, and any `pending_reset:<chat_id>` behind it can never resolve via `resolve_pending_reset_if_ready()` (§3) or `resync_pending_resets()` (§5) - stuck, with nothing in the current design able to clear it:

- **Draft/image timeout — not an issue.** A draft never has a `task_id` at all. Per `gateway_inbound.py`, `create_task_mapping()` (i.e. `task_id` creation) only happens inside `_push_task()`, which only runs once a draft is **finalised** by an incoming instruction/caption (the `existing_draft` → `_push_task(...)` block). A draft that instead hits its `DRAFT_CLOSE_SECONDS` hard cap and expires unfinalised never reaches that line — no `task_id` is ever created for it, so it has no bearing on `session_tasks:<chat_id>` or a pending reset. Nothing to handle here.
- **Poll timeout — real gap.** A poll *is* tied to an existing `task_id` (created before the poll was ever sent, via `_handle_poll()` → `create_task_mapping()`). When a poll's `POLL_TIMEOUT_SECONDS` elapses unanswered, `_finalise_poll()` sends a Telegram "didn't hear back" message but — per its own existing design/comment — pushes **nothing** onto the outbound RabbitMQ queue. Nobody downstream is ever told the poll ended. The orchestrator itself is a pass-through/router - it forwards a response to whichever agent currently owns `task_id`, it doesn't hold business logic about polls or timeouts - so it's specifically **that agent** that's left with nothing to act on. If it was waiting on the poll's answer before sending `completed`/`error` for the task, the task_id can stay open in `session_tasks:<chat_id>` indefinitely, and by extension a deferred `pending_reset` for that chat_id would never resolve.
- **Orphaned/expired task mapping — real gap, independent of polls.** `session_tasks:<chat_id>` membership is removed *only* by `delete_task_mapping()`, called *only* from `_handle_completed`/`_handle_error` when a terminal event actually arrives and is processed. `task:<task_id>` itself, separately, carries its own TTL (`REDIS_TASK_MAPPING_TTL_SECONDS`, 24h default) that has no relationship to that SET membership at all. So if a `completed`/`error` for some `task_id` is ever lost - dropped after `Q_CONSUME_MAX_ATTEMPTS` retries, or simply arriving after `task:<task_id>` has already TTL-expired (in which case `process_message()` drops it at the `get_task_mapping()` check, *before* `_handle_completed`/`_handle_error` ever runs, so `delete_task_mapping()` never gets called for it either) - that `task_id` is left indexed under `session_tasks:<chat_id>` permanently. Unlike the poll case, this doesn't depend on how the poll contract behaves, and it doesn't self-heal with more chat activity - a stale entry is never cleaned up just because the user keeps messaging; new messages only add further (legitimately open) task_ids alongside it.

Both causes undermine §1/§3's core assumption — that every open `task_id` will eventually receive a `completed`/`error` event. Neither is guaranteed today.

**Related, but not itself a bug - a UX consequence worth being aware of.** Per §6, nothing is sent to the chat while a reset is only deferred/waiting - so the moment `session_tasks:<chat_id>` *legitimately* empties (no orphaning, no bug), the reset applies immediately and silently, with no forewarning. In a continuous back-to-back conversation, a new task is typically already open before the previous one clears, so the empty-queue moment - and the reset - keeps getting pushed out naturally. But if the user sends a single message after a lull and that happens to be the task that finally empties the queue, the reset (and its notice, §6) lands immediately behind that one reply, with no warning it was ever pending - which can read as abrupt. This is the deferred design behaving exactly as specified (§1/§6), not a defect, but worth a conscious decision on whether it's acceptable as-is.

#### Candidate directions - **Decided and implemented: C (A + B).**

- [x] **A — close the information gap at the source.** Have `_finalise_poll()` push *something* to the outbound queue on an unanswered timeout too (not just when answered) — e.g. a `poll_answer: null`/empty signal, or a dedicated `poll_timed_out` event, carrying `task_id` like every other response payload. The orchestrator needs no new logic of its own here - it just routes this event to whichever agent currently owns `task_id`, exactly the same task_id-keyed forwarding it already does for a real poll answer, a text reply, etc. **The decision belongs to that agent** (re-ask, treat as declined, escalate, or simply send back `completed`/`error`, which is what actually clears `session_tasks:<chat_id>` and lets §3 resolve a deferred reset) - not to the orchestrator, and not to the gateway. This is the root-cause fix, but it's a behaviour change to the poll contract beyond just session-reset (today's design deliberately pushes nothing on an unanswered timeout), so it needs sign-off independent of this feature, and its resolution depends on every agent implementation actually handling the new signal. Implemented as a dedicated `poll_timed_out` event - see `poll_response_handler.py::_push_poll_timed_out()`, README.md.
- [x] **B — bounded grace period on the gateway side.** Give a pending reset a ceiling independent of ever hearing a `completed`/`error` back for that task_id: if it's been pending longer than some `PENDING_RESET_MAX_WAIT_SECONDS`, force the reset through anyway (treat every task_id still indexed under that chat as abandoned for reset purposes only — `task:<task_id>`/`session_tasks:<chat_id>` need clearing too, since otherwise they'd sit there stale forever even after being force-reset). Needs a timestamp alongside the existing `pending_reset:<chat_id> → task_id` entry, and *some* periodic mechanism to check the ceiling (there's currently nothing that revisits a pending reset other than `_handle_completed`/`_handle_error`/startup resync) — worth noting this reintroduces the kind of "watchdog" idea dropped earlier, but now for a concretely identified reason rather than a speculative one. **Cause-agnostic by construction** - it doesn't check *why* `session_tasks:<chat_id>` never emptied, only *how long* it's been pending, so it equally backstops the poll-timeout cause above *and* the orphaned/expired-mapping cause above, without needing to detect either one specifically. Implemented as `PENDING_RESET_MAX_WAIT_SECONDS` (config.py) + a `created_at` timestamp on `pending_reset:<chat_id>` (`set_pending_reset()`/`get_all_pending_resets()`, `utils_redis/database.py`) + a periodic sweep thread (`enforce_pending_reset_ceiling()`, `start_pending_reset_ceiling_sweep()`/`stop_pending_reset_ceiling_sweep()`, run from `utilities/initialise.py`, interval `PENDING_RESET_SWEEP_INTERVAL_SECONDS`) + the same check folded into `resync_pending_resets()` (§5) so a startup resync doesn't have to wait for the next sweep tick if an entry is already expired.
- [x] **C — both (recommended).** A is still the right root-cause fix for the poll-specific case - cheap for the orchestrator (one more type to pass through, no embedded poll/timeout logic) and puts the decision where the context already lives, with whichever agent is currently in charge. But A only ever addresses the poll cause, and even there its resolution is entirely in that agent's hands - a bug, a crash, a dropped message, or an agent that's no longer around for that task_id all leave the gap exactly as open as before. B is a gateway-side backstop that catches both causes at once, independent of anything downstream ever behaving correctly - useful as permanent defence-in-depth, not just as a stand-in for while A hasn't shipped yet. Given the orphaned/expired-mapping cause has no direction-A equivalent (there is no "orchestrator behaviour change" that fixes a message RabbitMQ already dropped), **B is not optional under C - it's the only fix for that cause**.

Note: the UX consequence noted above (an immediate, unsignalled reset landing right behind a single reply after a lull) is **not** addressed by either A or B - both are about making sure a reset *eventually* applies; neither changes the "no warning beforehand" behaviour from §6. Left as a conscious, separate decision - see open questions below.

#### Also to fold back in regardless of direction chosen

- [x] `_apply_session_reset(chat_id)` (§4) must still call `stop_draft_timer(chat_id)` before/alongside `reset_session()` — a draft can be actively accumulating independently of whether `session_tasks:<chat_id>` is empty (drafts have no `task_id`), so the immediate-reset path still needs to stop that in-memory timer itself, same as the current CCR-012 fix in `message_handler.py` does today. This was missing from §0–§7 above and needs restoring so the orphan-draft-timer fix (CCR-012) isn't regressed by this refactor.
- [x] `stop_poll_for_reset()` (the forced, silent poll-interrupt added for CCR-012) - **decided: repurposed, not removed.** Still unreachable on the normal deferred-wait path (an open poll always has an open `task_id`, so it's never force-closed while genuinely waiting), but now called defensively by `_force_apply_session_reset()` (direction B's force-through step) in case `PENDING_RESET_MAX_WAIT_SECONDS` is ever misconfigured shorter than a poll's own maximum lifetime (`POLL_GLOBAL_CAP_SECONDS`) - in practice a no-op given a sane default, but cheap defence-in-depth against that misconfiguration rather than dead code to delete.

---

### Open questions

1. ~~Which of A/B/C (§8) to adopt.~~ **Decided and implemented: C.**
2. ~~Whether to remove `stop_poll_for_reset()` or repurpose it.~~ **Decided and implemented: repurposed** for direction B's force-through step.
3. Whether the §8 UX consequence (an unsignalled reset landing immediately behind a single reply after a lull) needs its own mitigation (e.g. a short additional grace delay before applying even on the natural-empty path, not just B's force-through ceiling), or is accepted as-is per §6's existing "no warning during the wait" decision. **Still open** - not addressed by A or B, a separate call.

---

## BUG — `continue_draft_timer()` does not actually extend a draft's keep-alive time

Status: **Requirement clarified by user - previous fix (below) implemented the wrong mechanic and needs rework.** Unrelated to the `session_reset` feature above; tracked here as the project's other outstanding must-fix item.

### Confirmed requirement (authoritative - given directly by user, must not change)

Per cycle (5 min, `DRAFT_CYCLE_SECONDS`):

- t = 0: cycle's 5-minute wait begins.
- t = 1 min: typing animation starts.
- t = 3 min: prompt (notice + continue button) sent.
- If the button is pressed: **extend by 5 minutes** - meaning +5 minutes added to the current required wait time, not a fresh/reset cycle. First press: required wait becomes 10 min. Second press: 15 min. And so on, in 5-minute increments.
- **Hard ceiling: 55 minutes (`DRAFT_CLOSE_SECONDS`) total - no further extension is granted once reached**, regardless of further presses.
- Once the (possibly extended) required wait time is reached with no further extension, the cycle completes and moves to the next 5-minute cycle, which repeats the same t=1min-typing / t=3min-prompt pattern from its own start.
- Final cycle only: same t=1min typing / t=3min prompt, but the prompt has no button ("prompt for closing"). At the cycle's end, the final message is sent and the draft is cleared.

This is the exact, literal spec - "+5 mins" means +5 minutes added to the current required wait time (a running total), not "abandon the current cycle and start a fresh one" (the original bug) and not "preserve remaining time, then still proceed to an unmodified next cycle" (the fix implemented further below, which turned out not to match this requirement either - see Root cause/Symptom below for the original diagnosis, still valid, and "Must fix" for the corrected plan).

### Symptom

The "Give me a little while more" button (`continue_draft_timer()`, `utils_telegram/utilities/image_draft_handler.py`) is documented, in its own docstring, to "grant one more keep-alive cycle" in response to a press. The actual mechanics do not add any time to the draft's schedule - they cut the current cycle short and jump to the next cycle already within the existing fixed budget. For every cycle the button is actually shown on, the eventual outcome is identical whether or not it's pressed; pressing it can only make things happen *sooner*, never later.

### Root cause

- `_draft_loop()` computes `total_cycles = DRAFT_CLOSE_SECONDS // DRAFT_CYCLE_SECONDS` once, outside the `for` loop, and never changes it - the schedule is a fixed number of pre-allocated cycles from the moment the draft is created.
- Pressing continue during a non-final cycle's second wait window (`event.wait(...)` calls guarded by `_consume_continue()`) sends an acknowledgement, then executes Python's `continue` statement - which jumps straight to the *next* iteration of that same fixed-range loop. Per the module's own notes, this is deliberate: "it does not carry over unused time" / "it does not add extra cycles beyond the fixed total."
- However, per `_draft_loop()`'s own docstring, "an unanswered non-final cycle does not close the draft - it simply moves on to the next scheduled cycle" regardless of whether the button was ever pressed. So for every cycle where the button exists (non-final only - `_build_continue_button()` is never called for the final cycle, and `_consume_continue()` explicitly refuses a `"continue"` action when `is_final_cycle` is `True`), the loop reaches cycle N+1 either way. The only thing a press changes is *when* - skipping the current cycle's remaining wait makes the transition happen earlier, not later.
- Net effect: pressing "Give me a little while more" as early as possible on every cycle can make the draft reach its hard close **sooner** than never pressing it at all - the opposite of the button's stated purpose. The one cycle where "more time" would actually matter (the final cycle, where non-response closes the draft) is exactly the one cycle with no button at all.

### Why this is a bug, not a design preference

- `continue_draft_timer()`'s own docstring ("grant one more keep-alive cycle") describes additive behaviour the implementation does not provide - the code and its own nearest docstring contradict each other.
- The user-facing button copy ("Give me a little while more") sets the same expectation as the docstring, which the mechanics don't meet.
- The module header comment, `_draft_loop()`'s docstring, and README.md all describe the *mechanics* accurately (cut short, fixed total, no carry-over) - but that description was mistakenly read as confirmation the feature satisfies its own requirement, rather than as evidence of the mismatch against `continue_draft_timer()`'s docstring and the button's own purpose. The documentation is internally inconsistent, not in agreement.

### Must fix

- [x] ~~Direction 1 as first implemented ("preserve remaining wait, then proceed to an unmodified next cycle").~~ **Superseded - did not match the confirmed requirement above.** That version made a press a functional no-op for every non-final cycle (the loop reaches cycle N+1 either way, pressed or not) - it fixed the "cut short" regression but not the deeper "button does nothing" gap. `_wait_full_duration()` (the helper it introduced) is being reworked, not discarded - see below.
- [ ] Rework to match the confirmed requirement: a press must genuinely add 5 minutes to the *current* cycle's required wait (5 → 10 → 15 → ... min), capped at `DRAFT_CLOSE_SECONDS` (55 min) with no further extension beyond it - all within the existing single `_draft_loop()` function plus (at most) the existing `_wait_full_duration()` helper, improved rather than joined by further new functions (explicit user instruction: no additional helper functions).
- [ ] `_wait_full_duration()` needs to distinguish, on return, between: (a) a stop signal (draft finalised - exits `_draft_loop()` immediately) vs (b) the wait's full duration having genuinely elapsed uninterrupted - and `_draft_loop()` itself needs to track the current cycle's required-wait total (starting at `DRAFT_CYCLE_SECONDS`, +`DRAFT_CYCLE_SECONDS` per valid press, capped at `DRAFT_CLOSE_SECONDS`) rather than relying on the fixed `total_cycles`/`for` loop increment to represent elapsed time the way it did before.
- [ ] Fix `continue_draft_timer()`'s docstring ("grant one more keep-alive cycle") to describe the corrected, confirmed behaviour (adds 5 min to the current cycle's required wait, capped at `DRAFT_CLOSE_SECONDS`).
- [ ] Update `_draft_loop()`'s docstring, the module header comment (`image_draft_handler.py`), and README.md's "Pending drafts" / draft timeout section to match once the corrected behaviour is implemented - including the fact that total draft lifetime can now genuinely reach up to `DRAFT_CLOSE_SECONDS` via presses (this was already the documented ceiling, but is now an actively reachable one via extension rather than a fixed schedule length regardless of presses).

### Where

- `telegram_gateway_application/utilities/utils_telegram/utilities/image_draft_handler.py`: `continue_draft_timer()`, `_draft_loop()`, `_consume_continue()`, module header comment.
- `README.md`: "Pending drafts (media without an instruction yet)" section, the "Timeout, per draft..." paragraph describing the keep-alive cycle schedule.

---

## FIX — No retry on RabbitMQ/Redis startup connections, crashing the application

Status: **Implemented.** `initialise_rabbitmq_publish_connection()`, `initialise_rabbitmq_consume_connection()`, and `initialise_redis_connection()` each made exactly one connection attempt at startup, raising immediately on failure with no retry loop; because `main.py::main()` calls `initialise_application()` with no `try`/`except` around it, a transient "dependency not up yet" race (a normal, expected condition in multi-container deployments without externally enforced startup ordering) crashed the whole application on launch.

### Context

`utils_queue/queue.py::_initialise_rabbitmq_publish_connection()`/`_initialise_rabbitmq_consume_connection()` and `utils_redis/database.py::initialise_redis_connection()` each opened their respective connection inside a `try`/`except` that logged `critical` and re-raised on the very first failure. `initialise_application()` calls these unguarded via `initialise_rabbitmq_connection()`/`initialise_redis_connection()`, and `main()` has no `try`/`except` around `initialise_application()` either — so RabbitMQ or Redis not yet being reachable at the exact moment the gateway container starts (a normal race, not a genuine fault) propagated straight out of `main()` and killed the process, rather than being retried.

### Decisions

- **Scoped the fix to the startup entry points only** (`initialise_rabbitmq_connection()`, `initialise_redis_connection()`), not the shared per-connection helpers (`_initialise_rabbitmq_publish_connection()`/`_initialise_rabbitmq_consume_connection()`) themselves — those two helpers are also reused at *runtime* to reacquire a dropped connection (`_get_rabbitmq_publish_channel()`/`_get_rabbitmq_consume_channel()`). `queue_push_task()` deliberately relies on a *bounded* retry (`Q_PUSH_MAX_ATTEMPTS`, since it runs on the request path and is expected to fail fast and return `False` rather than hang indefinitely), and `queue_consume_task()` already has its own infinite reconnect loop independent of this fix. Making the shared helpers themselves block forever would have silently turned `queue_push_task()`'s bounded-retry contract into an indefinite hang — not requested, and a behaviour change beyond what was asked. The infinite retry loop lives only in `initialise_rabbitmq_connection()`, wrapping calls to the (unchanged) single-attempt helpers.
- `initialise_redis_connection()` was modified in place (not wrapped) — `_client` is only `None` before the first successful connection (or after `close_redis_connection()` during shutdown), so it has no equivalent runtime-reacquisition reuse to protect; safe to make it block-and-retry directly.
- New settings `Q_CONNECT_RETRY_DELAY_SECONDS`/`REDIS_CONNECT_RETRY_DELAY_SECONDS` (both default 5s, env-overridable via `get_env_int()`).
- Docstrings updated — `initialise_rabbitmq_connection()`, `initialise_redis_connection()`, and `initialise_application()` no longer claim a `Raises` contract for the transient-unavailability case; they now describe the indefinite-retry/blocks-until-connected behaviour instead.
- **Accepted risk, decided by user:** the retry loops catch the whole `pika.exceptions.AMQPConnectionError` family (which includes `ProbableAuthenticationError`/`ProbableAccessDeniedError`) and, on the Redis side, the whole `redis.exceptions.RedisError` hierarchy, treating every instance as the transient "not up yet" case rather than distinguishing it from a permanent credential/vhost/db misconfiguration — so a bad credential would also retry forever at startup instead of failing fast. **User's explicit call: acceptable, in favour of stability over fail-fast diagnostics.** A failed authentication/connection attempt is still logged (warning, per attempt) on every retry cycle, so it remains straightforward to spot and resolve from the logs on startup — not silent. Not narrowed further; no bounded cap or exception-subtype distinction is planned.
- **`REDIS_FORCE_INFINITE_RETRY` added after this fix originally shipped, defaulting to `False`** (`config.py`; see `_should_redis_retry_infinite()`) — flagged as CCR-022 (`CODE_NON_COMPLIANCE.md`), since a `False` default reintroduces the single-attempt-then-give-up behaviour for Redis specifically that this fix's Redis half was originally built to remove, without this entry being updated to record it, and left `initialise_redis_connection()`'s docstring claiming the old unconditional-retry behaviour unconditionally. Both gaps are now closed: the docstring was corrected to describe the conditional behaviour, and this bullet records the decision. **User's explicit call (2026-09-09): keep the default `False` for now** — Redis is deliberately treated more conservatively than RabbitMQ's still-unconditional retry, not restored to parity; the flag exists so a deployment can opt back into indefinite retry (`REDIS_FORCE_INFINITE_RETRY=true`) without a code change if the single-attempt default proves too fragile in practice.

### Implementation Notes

- `utils_queue/queue.py::initialise_rabbitmq_connection()`: now a `while True` loop calling the two existing single-attempt helpers, catching `pika.exceptions.AMQPConnectionError`, logging a warning, and sleeping `settings.Q_CONNECT_RETRY_DELAY_SECONDS` before retrying. Any other exception type still propagates immediately (fail-fast preserved for genuinely unexpected errors).
- `utils_redis/database.py::initialise_redis_connection()`: the `try`/`except redis.exceptions.RedisError`/raise block became a `while True` loop with the same warning-log-and-sleep pattern, using `settings.REDIS_CONNECT_RETRY_DELAY_SECONDS`. `_client` is reset to `None` on a failed attempt before retrying, to keep "is `_client` actually connected" consistent for any other reader of that global.
- `config.py`: `Q_CONNECT_RETRY_DELAY_SECONDS`/`REDIS_CONNECT_RETRY_DELAY_SECONDS` added alongside their respective existing Queue/Redis Connection blocks.
- Runtime reconnection paths (`queue_push_task()`'s bounded retry, `queue_consume_task()`'s own infinite reconnect loop, and every Redis per-operation helper's `REDIS_TASK_MAX_ATTEMPTS`-bounded retry) were **not touched** — this fix is scoped to the startup race only, per the user's explicit ask.

### Open Questions

1. ~~Whether the retry loops should distinguish a transient "not up yet" failure from a permanent credential/config error (which would otherwise also retry forever).~~ **Decided: accepted risk, no change.** User prefers stability (never crash on startup) over fail-fast diagnostics here; a bad credential retrying indefinitely is acceptable given every attempt is still logged, making it straightforward to diagnose from the logs.
2. Whether `CODE_NON_COMPLIANCE.md` in this repository should be updated to record this finding/fix formally as its own numbered entry is a call for whoever owns that document next — it's treated as an immutable compliance record here and was not modified as part of this session.
3. Whether `REDIS_FORCE_INFINITE_RETRY` should eventually default to `True` (full parity with RabbitMQ's unconditional startup retry) is explicitly left open — "for now" (2026-09-09) is not a permanent decision; revisit if the single-attempt default is observed to cause the startup-window degradation CCR-022 describes (Tier 2 alert state / orphan sweeps / pending-reset resync silently no-op-ing on a slow Redis start) in practice.

---

## NEW — `gateway_recover` (Tier 2) — counterpart confirmation to `gateway_alert`

Status: **Implemented, not yet exercised in testing.** `gateway_alert` (Tier 2) had no counterpart signal for "the incident it warned about is now over" — the orchestrator/backend had no way to know from `Q_CHANNEL_OUT` alone whether Telegram had recovered, short of inferring it from the absence of further alerts.

### Goal

Push a `gateway_recover` event the first time a send succeeds again after a `gateway_alert` was fired — mirroring `_push_tier2_gateway_alert()`'s payload shape exactly, so consumers already parsing Tier 2 events don't need a second, differently-shaped message type to handle.

### Decisions

- `_push_tier2_gateway_recover(status_code)` (`utils_queue/error_handling.py`) builds a payload identical in shape to `_push_tier2_gateway_alert()`'s (`task_id`/`session_id` both `None`, `tier: 2`) — only `type` (`"gateway_recover"`) and `reason` (always `"recovered"`, fixed rather than derived from what previously failed) differ.
- **Fires once per incident, not on every successful send.** `record_send_success()` already tracks `_alert_armed` — before resetting it, the function now captures whether it was `False` (i.e. a `gateway_alert` had already fired and hadn't yet been closed out). Only that transition triggers `_push_tier2_gateway_recover()`; an ordinary success with no prior alert is a no-op, same restraint `record_send_failure()` already applies to `gateway_alert` itself.
- **`status_code` is passed through from the response, not fixed to `None`.** `record_send_success()` gained a `status_code: int | None = None` parameter, and all 8 call sites in `gateway_outbound.py` (`send_message`, `send_typing_action`, `send_poll`, `stop_poll`, `send_document`, `send_photo`, `send_video`, `send_media_group`) now pass `response.status_code` in. Since this feature hadn't been deployed/tested yet at the time of this change, every call site was updated directly rather than defaulting the parameter to preserve old call sites unchanged.
- **The recovery-transition log line lives in `record_send_success()`, not `_push_tier2_gateway_recover()`** — explicit user request, so the fact that a recovery is happening is always visible in the logs regardless of whether the subsequent queue push itself succeeds. `_push_tier2_gateway_recover()` still logs its own push outcome (success/failure), same convention as every other queue-push helper in this file (`push_tier1_delivery_failed()`, `_push_tier2_gateway_alert()`) — kept for consistency rather than requested outright; flagged here in case the user wants that trimmed further.
- `_push_tier2_gateway_recover()` returns `None` (not `bool`, unlike `_push_tier2_gateway_alert()`) — explicit user request; nothing currently needs to branch on whether the recovery push itself succeeded.

### Implementation Notes

- `utils_queue/error_handling.py`: `record_send_success(status_code)`, new `_push_tier2_gateway_recover(status_code)`, module header Notes updated.
- `utils_telegram/gateway_outbound.py`: all 8 `record_send_success()` call sites updated to `record_send_success(response.status_code)`; module header Notes updated.
- `README.md`: new `gateway_recover` subsection added under "Error/Alert Events", alongside the existing `delivery_failed`/`gateway_alert` documentation.
- `CODE_SEQUENCE_DIAGRAM.md` §10.1–10.4 updated to show the recovery branch.

### Open Questions

1. `type: "gateway_recover"` was chosen to parallel `gateway_alert` — not yet confirmed against whatever the backend/orchestrator consumer expects to see on `Q_CHANNEL_OUT`. Worth a quick check before/while wiring up the consumer side.
2. Not yet exercised against a real `gateway_alert` → recovery cycle in testing (per user, this is the reason the recovery-transition log line was placed where it is) — worth a manual pass (force a 401/unreachable state, then let a send succeed again) once RabbitMQ/consumer wiring is available to confirm the once-per-incident behaviour holds end-to-end.

---

## FIX — CCR-019: restart silently orphaned the `gateway_recover` counterpart for a 401/404 `gateway_alert`

Status: **Implemented.** Fixes the Medium-severity finding identified in the fourth follow-up compliance review (2026-09-08) of the `gateway_recover` feature above — see `CODE_NON_COMPLIANCE.md`.

### Context

`_alert_armed`/`_consecutive_failures` (`utils_queue/error_handling.py`) were plain in-memory globals, reset on every process restart. For the two Tier 2 reasons that fire immediately (`"unauthorized"`/`"not_found"`, i.e. a 401/404), the realistic and near-universal fix is updating `TELEGRAM_BOT_TOKEN` and restarting the container — `TELEGRAM_BOT_TOKEN` is read exactly once at `config.py::Settings.__init__()`, with no runtime reload path anywhere in the codebase. That restart reset `_alert_armed` back to `True` before the first post-fix send ever ran, so `record_send_success()`'s `was_alerted = not _alert_armed` check could never observe the prior alert — the orchestrator was left with a permanently "open" incident for the single most deterministic Tier 2 trigger, even though the gateway was healthy again.

### Decisions

- **Persisted only the armed/disarmed flag, not the consecutive-failure counter.** `_consecutive_failures` resetting to `0` on restart is separate, already-accepted behaviour (per the module's own pre-existing Notes: "a restart is itself a fresh start at reassessing whether Telegram is reachable") — CCR-019 was specifically about the armed flag orphaning `gateway_recover`, not about the counter. Widening the fix to persist the counter too was considered and rejected as scope creep beyond what the finding actually described.
- **New Redis key `tier2_alert_armed`** (`"1"`/`"0"`, no TTL) — same rationale as `pending_reset:<chat_id>`: must outlive an unbounded outage, resolved only by an explicit write, never by expiry.
- **Written only on the actual transition**, not on every send/failure — mirrors the existing once-per-incident restraint already governing `_push_tier2_gateway_alert()`/`_push_tier2_gateway_recover()`, and keeps the added Redis write volume proportional to genuine incidents rather than every message.
- **Loaded once at startup** via a new `load_tier2_alert_state()`, called from `initialise_application()` right after `initialise_redis_connection()` — chosen over relying on `_get_redis_client()`'s incidental lazy-init (which would technically also work, since `start_queue_consumer()` runs before Redis is explicitly initialised) for consistency with every other restart-relevant state sweep in this file (`close_orphaned_drafts()`, `close_orphaned_polls()`, `resync_pending_resets()`).
- **`get_tier2_alert_armed()` defaults to `True` (armed)** on a missing key or a Redis read failure — matches the module's own pre-existing in-memory default, so an unwritten/unreadable key behaves exactly as "no incident on record" rather than fabricating a false alert.
- **Does not address CCR-020 or CCR-021.** The persist call (`set_tier2_alert_armed()`) is itself added outside `_lock` alongside the existing `_push_tier2_gateway_*()` calls, same ordering shape CCR-020 already flags — this fix does not widen or narrow that gap, it was explicitly scoped to CCR-019 only.

### Implementation Notes

- `utils_redis/database.py`: new `get_tier2_alert_armed()` / `set_tier2_alert_armed(armed)`.
- `utils_queue/error_handling.py`: new `load_tier2_alert_state()`; `record_send_success()` and `record_send_failure()` each call `set_tier2_alert_armed()` on their respective transition; module header Notes updated.
- `utilities/initialise.py`: imports and calls `load_tier2_alert_state()` after `initialise_redis_connection()`; module header Notes updated.
- `README.md`: `gateway_alert` section notes the armed flag now survives a restart.
- `CODE_SEQUENCE_DIAGRAM.md`: §1.1-1.3 cold start updated with the new startup call; §10.1-10.4 updated with the persist calls; new §10.6 added for the startup restore path.

### Open Questions

1. Whether `CODE_NON_COMPLIANCE.md` should be updated to mark CCR-019 Resolved is a call for whoever owns that document next — it's treated as an immutable compliance record here and was not modified as part of this session.
2. Same caveat as the `gateway_recover` feature itself — not yet exercised end-to-end (kill the process mid-incident, restart, confirm the next successful send fires `gateway_recover`) since RabbitMQ/consumer wiring for manual testing wasn't available in this session.

---

## FIX — CCR-020: `gateway_alert`/`gateway_recover` publish (and Redis persist) not serialised relative to each other

Status: **Implemented.** Fixes the Medium-severity finding identified in the fourth follow-up compliance review (2026-09-08) — see `CODE_NON_COMPLIANCE.md`. Explicitly called out as *not* addressed by the CCR-019 fix above (see that entry's Decisions) — this is the follow-up that actually closes it.

### Context

`record_send_success()`/`record_send_failure()` each released `_lock` (after atomically updating `_alert_armed`/`_consecutive_failures`) before calling `set_tier2_alert_armed()` and `_push_tier2_gateway_recover()`/`_push_tier2_gateway_alert()`. Since `queue_push_task()` can take up to `Q_PUSH_MAX_ATTEMPTS (30) x Q_PUSH_RETRY_DELAY (1s)` ≈ 30s under a RabbitMQ outage, two threads independently deciding `was_alerted`/`should_fire = True` at nearly the same moment were not serialised beyond that initial state mutation — the actual publish to `Q_CHANNEL_OUT` (and the Redis persist added by the CCR-019 fix) could land in either order. Neither payload carries a timestamp/sequence field, so a consumer had no way to detect or correct a reordering.

### Decisions

- **Went through an incorrect intermediate version before landing here — a dedicated second lock (`_publish_lock`), scoped only to the publish/persist step, tried first and rejected on further scrutiny.** The concern driving that first attempt was real: `_lock` is acquired on every single send (`record_send_success()`/`record_send_failure()` run after every `send_*()`/`stop_poll()` call in `gateway_outbound.py`, across every concurrent thread — typing indicator, per-poll/per-draft loops, the RabbitMQ consumer thread, `gateway_inbound.py`'s long-poll thread, session-reset notices), so widening it to cover a ~30s publish looked like it would tax every other thread unnecessarily. A second lock, taken only on the rare armed<->disarmed transition branches, seemed to get the same serialisation for free. **On tracing the actual interleaving, this was found insufficient: a second, independently-acquired lock only prevents two publishes from overlapping — it does not guarantee which of the two starts first matches which transition happened first.** After `_lock` is released, the order in which two threads reach the second lock is scheduler-dependent, not tied to lock-acquisition order under `_lock` — so the exact reordering CCR-020 describes (`gateway_recover` published before a `gateway_alert` that logically preceded it) remained possible even with `_publish_lock` in place. Guaranteeing order requires the decision and the publish to be one uninterrupted critical section under the *same* lock, not two.
- **Corrected: `_lock`'s own scope widened to cover the persist-and-publish step**, for the transition branches only (`if was_alerted:` / `if should_fire:`) — non-transitioning calls still only hold `_lock` for the cheap variable read/write, unchanged. `_publish_lock` removed entirely.
- **Accepted cost, user's explicit call:** a transitioning call now holds `_lock` for the full publish duration in the worst case (~30s, if RabbitMQ is also unreachable), during which every other thread's `record_send_success()`/`record_send_failure()` call blocks too — not just the two threads actually racing. **Judged acceptable: this worst case only arises when RabbitMQ is unreachable at the same time Telegram delivery is failing/recovering, at which point the system is already broadly degraded — the added internal lock contention is not the dominant concern in that scenario**, so no further work (e.g. a sequence-number payload field to avoid locking around the publish entirely) was pursued.
- **Sequence-number/timestamp payload field (the finding's alternative remediation) was considered and not implemented.** Would have avoided any added locking cost, but only makes reordering *detectable* rather than preventing it, requiring the backend/orchestrator consumer (outside this repo) to also be updated to honour it. Locking closes the race entirely within this codebase instead.
- **Does not touch CCR-021** (the shared RabbitMQ publish-channel thread-safety gap inside `queue_push_task()` itself) — same call path, different root cause (unsynchronised shared pika channel, not ordering), left as a separate open finding.

### Implementation Notes

- `utils_queue/error_handling.py`: `record_send_success()`'s `if was_alerted:` branch and `record_send_failure()`'s `if should_fire:` branch are now nested *inside* their respective `with _lock:` blocks (previously sat after it, and briefly after a since-removed `with _publish_lock:`), so `set_tier2_alert_armed(...)` + `_push_tier2_gateway_*()` run without ever releasing `_lock` in between. Docstrings and module header Notes updated to describe the widened scope and the rejected intermediate design.

### Open Questions

1. Whether `CODE_NON_COMPLIANCE.md` should be updated to mark CCR-020 Resolved is a call for whoever owns that document next — it's treated as an immutable compliance record here and was not modified as part of this session.
2. Not yet exercised under real concurrent load (two threads genuinely racing an alert-firing and a recovery-firing send at the same moment) — the fix is verified by code inspection (lock placement, ordering/deadlock trace) rather than a live concurrency test, consistent with this feature's testing status elsewhere in this file.

---

## FIX — CCR-021: shared RabbitMQ publish channel used concurrently across threads without synchronisation around the actual publish call

Status: **Implemented.** Fixes the High-severity finding identified in the fourth follow-up compliance review (2026-09-08) — see `CODE_NON_COMPLIANCE.md`. Surfaced while tracing the CCR-020 fix's call path into `queue_push_task()`, but the root cause predates that change and is independent of it.

### Context

`queue.py`'s own module header documented an invariant: publish and consume each use their own dedicated connection, confined to their own thread, since a pika `BlockingConnection` must not be shared or used concurrently across threads. In practice, only the consume half was actually enforced. `_get_rabbitmq_publish_channel()` acquired `_lock_publish` only long enough to lazily (re)initialise `_connection_publish`/`_channel_publish`, then returned the shared channel object and released the lock — `queue_push_task()` then called `channel.queue_declare()`/`channel.basic_publish()` directly with no lock held at all. Since `queue_push_task()` is invoked from many independent threads (every `send_*()`/`stop_poll()` in `gateway_outbound.py`, across every concurrent thread class - typing indicator, per-poll/per-draft loops, the RabbitMQ consumer thread, `gateway_inbound.py`'s long-poll thread), two threads could genuinely call `basic_publish()`/`queue_declare()` on the same shared `BlockingChannel` at the same time - unsupported by pika, capable of corrupting AMQP frames or producing misleading exceptions/an unexpectedly closed connection, affecting every outbound message type on `Q_CHANNEL_OUT`.

### Decisions

- **`_lock_publish` widened to cover the entire retry loop in `queue_push_task()`, rather than introducing a separate lock for "actual publish use" alongside the existing lifecycle lock.** `_lock_publish` already guarded `_connection_publish`/`_channel_publish`'s lifecycle (open in `_initialise_rabbitmq_publish_connection()`, close in `close_rabbitmq_connection()`). Lifecycle and actual use both operate on the same shared mutable object, so they must exclude each other too, not just exclude within their own kind - a separate "usage" lock alongside the existing "lifecycle" lock would not have actually been safe, since a publish call under the new lock would have no protection against a concurrent reconnect/close proceeding under the old lock on the same channel. This is the same shape of mistake already caught and corrected for CCR-020's short-lived `_publish_lock` attempt, recognised here before implementing rather than after.
- **`_lock_consume` confirmed not to need equivalent treatment - reasoned through explicitly with the user before implementing.** `queue_consume_task()`'s actual pika calls (`basic_consume()`/`start_consuming()`) are confined to the single `_consumer_thread` by construction (`start_queue_consumer()` guards against a second invocation via `_consumer_running`) - no second thread ever calls them. The one legitimate cross-thread interaction, `stop_queue_consumer()`, already uses pika's own `add_callback_threadsafe()` to hand `stop_consuming` back to the connection's own thread, rather than invoking a channel method directly from outside it - so consume was never exposed to the hazard publish had, and `_lock_consume`'s existing (narrower) scope is sufficient. `_lock_consume`/`_lock_publish` guard entirely disjoint resources (separate connections) regardless, so neither change affects the other.
- **Accepted cost, consistent with the stance already taken for CCR-020:** concurrent `queue_push_task()` callers now fully serialise, including through each other's retry-sleeps - a caller can wait up to another in-flight call's full `Q_PUSH_MAX_ATTEMPTS x Q_PUSH_RETRY_DELAY` (~30s) budget before its own first attempt even starts, if RabbitMQ is unreachable. Judged a redistribution of an existing cost rather than a new one: any individual call already took up to that long in that scenario - the lock only decides whether concurrent callers wait for each other safely in turn (this fix), or overlap unsafely (the prior bug).
- **Per-thread dedicated publish connections (the finding's alternative remediation) was considered and not implemented.** More faithful to pika's per-thread ownership model and avoids blocking entirely, but this application spawns many short-lived threads (a typing-indicator/draft/poll thread per active task, created and torn down per interaction) - per-thread connections would mean frequent connection open/close churn against RabbitMQ and added lifecycle-management complexity, for scale this "1 user : 1 chat" application doesn't need.
- **Interaction with the CCR-020 fix acknowledged, not mitigated further:** `record_send_success()`/`record_send_failure()` now hold `error_handling._lock` while calling into `queue_push_task()` for a Tier 2 transition, and `queue_push_task()` can now itself wait on `_lock_publish`. This extends how long `error_handling._lock` can be held in the worst case, but does not introduce a new lock-ordering cycle - the dependency is one-directional (`error_handling._lock` → `_lock_publish`; nothing in `queue.py` ever calls back into `error_handling.py`), so no deadlock, just a compounding (still bounded) worst-case latency.
- **Module header comment corrected** - previously claimed publish was "confined to caller's thread" (never true in practice); now documents `_lock_publish`'s actual dual role (lifecycle + usage) and why consume didn't need the same treatment.

### Implementation Notes

- `utils_queue/queue.py`: `queue_push_task()`'s entire retry loop (previously unguarded) is now wrapped in `with _lock_publish:`. `_lock_publish` is an `RLock`, so `_get_rabbitmq_publish_channel()`'s own internal `with _lock_publish:` (for lazy reconnection) nests safely on the same thread. Docstring and module header Notes updated.

### Open Questions

1. Whether `CODE_NON_COMPLIANCE.md` should be updated to mark CCR-021 Resolved is a call for whoever owns that document next — it's treated as an immutable compliance record here and was not modified as part of this session.
2. Not yet exercised under real concurrent load (two threads genuinely racing a publish at the same moment against a real RabbitMQ instance) - the fix is verified by code inspection (lock placement, resource-disjointness and deadlock trace) rather than a live concurrency test.

---

## FIX — `_redis_write()`/`_redis_read()` had no retry, unlike their sibling `_redis_delete()`

Status: **Implemented.** Surfaced while adding `get_tier2_alert_armed()`/`set_tier2_alert_armed()` for the CCR-019 fix above — those two were pointed out as missing retry, which led to auditing every function in `utils_redis/database.py` for the same gap.

### Context

`_redis_delete()` has always retried a raised exception up to `REDIS_TASK_MAX_ATTEMPTS` times. `_redis_write()`/`_redis_read()` — the two most-reused primitives in the file — never did; a single attempt, any exception caught and swallowed into `False`/`None`. Every function built directly on top of them (rather than hand-rolling its own retry loop the way `get_task_mapping()`/`get_chat_draft()`/`get_poll_mapping()` did) silently inherited that gap. A full audit of every function in the file was given to the user directly (not reproduced here) before this fix; this entry only records the fix itself.

### Decisions

- **Retry ownership moved into `_redis_write()`/`_redis_read()` themselves**, mirroring `_redis_delete()`'s existing shape exactly (bounded loop, `REDIS_TASK_MAX_ATTEMPTS`/`REDIS_TASK_RETRY_DELAY`, warn-and-retry then exception-log-and-return on exhaustion) — rather than adding a retry loop to each individual caller, per explicit instruction.
- **`get_task_mapping()`, `get_chat_draft()`, `get_poll_mapping()` had their own duplicate hand-rolled retry loop removed**, now a single call to `_redis_read()` — retry ownership moved to the primitive, not left duplicated in both places (which would have meant a nested-retry budget for these three specifically, on top of being redundant code).
- **No change to functions that already call `_redis_write()`/`_redis_read()` directly with no loop of their own** (`create_chat_draft()`, `update_poll_answer()`, `_get_or_create_session()`, `generate_session()`'s session read, `set_pending_reset()`, `_get_pending_reset_info()`/`get_pending_reset()`, `reset_session()`'s initial read, `get_tier2_alert_armed()`/`set_tier2_alert_armed()`) — these all gain retry automatically now, with zero code changes needed, since they were already delegating to the primitives.
- **`create_task_mapping()` — its retry/regeneration loop was removed entirely (follow-up, same session, corrected after an intermediate fix left the underlying problem in place).** An first attempt at this only removed the loop's own `time.sleep(REDIS_TASK_RETRY_DELAY)`, but left the loop itself regenerating a new `task_id` and calling `_redis_write()` again on *any* `False` — which is still "retrying because `_redis_write()` failed," just without the sleep, since `_redis_write()`'s own internal retry and an `nx=True` collision are indistinguishable from its `bool` return alone. Corrected to a single attempt: one `uuid4().hex`, one `_redis_write()` call, `False` treated as final. `_redis_write()` already retries a connection-level failure internally before ever returning `False`, so there is nothing left for this function to usefully retry; a `uuid4()` collision is a ~1-in-2^122 event, not worth a dedicated retry path on its own. `_redis_write()` still can't distinguish a collision from an exhausted write failure — moot now, since neither case is retried here anymore.
- **`create_poll_mapping()`'s primary write** (previously a single, non-retried `_redis_write()` call — the inconsistency flagged against `create_task_mapping()` in the earlier audit) **now retries for free**, with no code change of its own needed, since it already called `_redis_write()` directly.
- **Raw `client.X()` calls that bypass `_redis_write()`/`_redis_read()`/`_redis_delete()` entirely were left untouched** — the `sadd`/`srem` index-maintenance calls (documented best-effort elsewhere in this file), `scard()`/`smembers()` reads (`has_open_tasks()`, `get_session_poll_ids()`, `reset_session()`'s task-id read), and the `scan_iter()`-based startup sweeps (`get_all_chat_draft_ids()`, `get_all_poll_ids()`, `get_all_pending_resets()`). Out of scope for this change, which was specifically about `_redis_write()`/`_redis_read()`.

### Implementation Notes

- `utils_redis/database.py`: `_redis_write()`, `_redis_read()` — added retry loop, docstrings updated. `get_task_mapping()`, `get_chat_draft()`, `get_poll_mapping()` — own retry loop removed, now delegate to `_redis_read()`, docstrings updated.
- **Minor logging precision trade-off, accepted, not fixed further**: `get_task_mapping()` logs `"No task mapping found ... (expired or unknown)"` whenever `_redis_read()` returns `None` — which is now also true after retries are exhausted on a genuine connection failure (previously that case returned early from within the loop, before this log line, with its own distinct exception log instead). A real outage now logs both an accurate `ERROR`-level `_redis_read()` exhaustion message and a slightly misleading `WARNING`-level "expired or unknown" line immediately after. Cosmetic, not a correctness issue (both cases still correctly return `None`) — flagged rather than silently left unmentioned.

### Open Questions

1. ~~Whether to also route the `sadd`/`srem`/`scard`/`smembers`/`scan_iter` raw calls through retrying helpers is a separate, broader change.~~ **Done — see the follow-up entry below.**

---

## FIX — remaining raw `sadd`/`srem`/`scard`/`smembers`/`scan_iter` calls given retry (High/Medium) or a ping-first, exception-surfacing guard (Low)

Status: **Implemented.** Closes the open question above. Follows directly from a per-call-site risk analysis given to the user first (not reproduced in full here — see chat history): each of the 10 remaining raw call sites was ranked High/Medium/Low by what actually breaks downstream if it silently fails, not just "is it retried today."

### Context

After `_redis_write()`/`_redis_read()`/`_redis_delete()` gained retry, 10 call sites across 8 functions still used the raw Redis client directly for operations those three primitives don't cover - SET membership (`sadd`/`srem`/`scard`/`smembers`) and keyspace sweeps (`scan_iter`). Each was single-attempt, catch-and-swallow.

### Decisions

- **High priority (real gap, undermines a documented safety guarantee) - given a proper retrying primitive:**
  - `create_task_mapping()`'s `sadd` (session_tasks index) - a failed index write here can make `has_open_tasks()` wrongly report a chat as fully idle while a task is still genuinely open, letting a `session_reset` apply immediately when it should defer - the exact scenario the deferred-reset feature exists to prevent.
  - `reset_session()`'s `smembers` (session_tasks read) - a failed read here means `reset_session()` still wipes `session_tasks:<chat_id>`/`session:<chat_id>` regardless, silently orphaning whatever task_ids it couldn't read, which undermines the function's own documented guarantee that a stale task_id is dropped after a reset.
- **Medium priority (real gap, but backstopped or narrower blast radius) - given the same retrying primitive treatment as High:**
  - `delete_task_mapping()`'s `srem` - a ghost `session_tasks` entry is already backstopped by `PENDING_RESET_MAX_WAIT_SECONDS` (TODO.md §8).
  - `create_poll_mapping()`'s `sadd` - a poll always has an open `task_id` tracked separately, so this only affects the defensive force-through poll-stop sweep, not deferred-reset correctness itself.
  - `get_session_poll_ids()`'s `smembers` - same narrower consequence as above (one poll possibly left open on Telegram's side after a forced reset), not a safety break.
  - New primitives added: `_redis_sadd()`, `_redis_srem()`, `_redis_smembers()` (`utils_redis/database.py`), mirroring `_redis_write()`/`_redis_read()`/`_redis_delete()`'s exact retry shape (`REDIS_TASK_MAX_ATTEMPTS`/`REDIS_TASK_RETRY_DELAY`). All 5 call sites above now go through one of these instead of a raw `_get_redis_client().sadd(...)`/`.srem(...)`/`.smembers(...)` call.
- **Low priority (already fine as-is, per the earlier analysis) - given a cheaper treatment instead, per explicit instruction: a `_redis_ping()` pre-check (same retry shape) before the raw command, with a failed ping treated exactly like any other failure that function already handles - same existing fallback value, no new return type:**
  - `delete_poll_mapping()`'s `srem` - a ghost entry here is already absorbed gracefully downstream by `stop_poll_for_reset()`'s existing no-op-on-unknown-poll_id handling.
  - `has_open_tasks()`'s `scard` - already had a deliberate fail-safe (`True`, "still open") that a retry would just delay reaching.
  - `get_all_chat_draft_ids()`/`get_all_poll_ids()`'s `scan_iter` - startup-only, run right after Redis is confirmed reachable, each record backstopped by its own TTL.
  - `get_all_pending_resets()`'s `scan_iter` + raw `client.get()` - also runs periodically (the ceiling sweep), so a single failed cycle self-heals on the next tick.
  - New `_redis_ping()` added (`utils_redis/database.py`), same retry shape as the other primitives, returning a plain `bool` (like every other primitive in the file) - logs the underlying exception itself before returning `False`, same as the rest.
  - **Went through two incorrect intermediate versions before landing here** - first `_redis_ping()` itself returned the caught exception (rejected: coupled every caller to `_redis_ping()`'s internal exception type); then each of the 5 callers built and returned a *new*, function-specific `Exception` instance on a failed ping (rejected: not what was asked - see below). **Corrected, final design**: `if not _redis_ping():` in each of the 5 functions logs an error and returns/falls through to that same function's own pre-existing failure fallback (`get_all_chat_draft_ids()`/`get_all_poll_ids()`/`get_all_pending_resets()` → `[]`; `has_open_tasks()` → `True`; `delete_poll_mapping()` → skips the `srem` attempt and falls through to its unrelated `deleted` return value, unchanged). **No return type of any of the 5 functions changed** - each keeps its original signature (`list[int]`, `list[str]`, `list[tuple[...]]`, `bool`, `bool`) exactly as it was before this whole `_redis_ping()` change, since a ping failure is no longer a distinguishable case at all from any other failure that function already tolerated.
- **No caller changes needed anywhere** - since none of the 5 functions' return contracts changed, `image_draft_handler.py::close_orphaned_drafts()`, `poll_response_handler.py::close_orphaned_polls()`, and `session_reset_handler.py::resync_pending_resets()`/`_enforce_pending_reset_ceiling()` are all back to their original, untouched form (an earlier intermediate version had added `isinstance(result, Exception)` guards to these; removed once the return-type change itself was reverted).

### Implementation Notes

- `utils_redis/database.py`: `_redis_sadd()`, `_redis_srem()`, `_redis_smembers()`, `_redis_ping()` added. `create_task_mapping()`, `delete_task_mapping()`, `create_poll_mapping()`, `get_session_poll_ids()`, `reset_session()` updated to use the new High/Medium primitives. `has_open_tasks()`, `get_all_chat_draft_ids()`, `get_all_poll_ids()`, `get_all_pending_resets()`, `delete_poll_mapping()` updated with the ping-first guard, each falling back to its own pre-existing failure value on a failed ping - no signature changes.

### Open Questions

1. `get_all_pending_resets()`'s raw `client.get(key)` inside its `scan_iter` loop still bypasses `_redis_read()` even after this change - covered by the same up-front `_redis_ping()` guard as the `scan_iter` call itself, but not given its own dedicated retry. Consistent with treating this function's Low-tier ranking as a whole, not fixed further.
2. Whether `CODE_NON_COMPLIANCE.md` should be revisited given this closes most of the retry gaps identified in the earlier audit is a call for whoever owns that document next - not modified as part of this session.
