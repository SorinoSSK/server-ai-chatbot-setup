# TODO Record for Telegram Gateway

Tracks the design goals of `telegram_gateway`, the Telegram-facing service that translates between Telegram and the RabbitMQ queues shared with `bot_sanctuary`, and where each one stands. Section numbers are referenced from `bot_sanctuary/CODE_TODO.md`, so they are kept stable. Findings labelled CCR-nnn come from `CODE_NON_COMPLIANCE.md`, a protected record that is never edited here, so whether each finding should be marked resolved is for that file's owner. This record was regrouped from an earlier chronological version into the status-table layout used by the `V-Project-Multimedia-Application` TODO files. Decisions, rejected alternatives and history are kept inside each section, and the earlier version remains in git history.

**Status key:** 🟢 Closed = finished. ⚪ Superseded = replaced by a later design, kept for history. 🟡 Ongoing = partly done, work remains. 🔴 Open = not started or undecided.

**Priority key (my proposal, change freely):** **P1** = do next: a live bug, a feature that does not work, or something other work waits on. **P2** = should be done soon: a known gap with limited impact or a workaround. **P3** = optional, or whenever convenient.

**Action key:** **DECIDE** = needs your decision. **BUILD** = implementation work. **TEST** = verify, change nothing unless it fails. **CHECK** = confirm a fact. **DOC** = documentation only. Every unresolved bullet in a section starts with 🔴, then its priority and action, for example `🔴 **P2 · DECIDE** [TG-07]`. P1 and P2 items also carry an ID that matches the action list below. Resolved questions are struck through or moved to Closed and Decided.

| # | Topic | Status | Top open priority | Next step |
|---|-------|--------|-------------------|-----------|
| 1 | Admin-triggered global session reset | 🟡 Ongoing | P3 | Retire the `session_cleared` event on both sides |
| 2 | Graceful `session_reset` (deferred reset, crash-resilient ack) | 🟡 Ongoing | P3 | Decide the "unsignalled reset after a lull" behaviour |
| 3 | Agent-call access tier (`coding_allowed`) | 🟡 Ongoing | P2 | Give it its own whitelist variable (TG-09) |
| 4 | Draft keep-alive button does not extend the timer | 🔴 Open | P1 | Rework `_draft_loop()` to the confirmed +5 minute mechanic (TG-02) |
| 5 | Startup connection retry (RabbitMQ and Redis) | 🟢 Closed | P3 | Revisit the `REDIS_FORCE_INFINITE_RETRY` default |
| 6 | `gateway_recover` (Tier 2) and alert persistence | 🟡 Ongoing | P2 | Exercise an alert-to-recovery cycle end to end (TG-05, TG-06) |
| 7 | Concurrency fixes for Tier 2 publish and the publish channel | 🟢 Closed | P3 | Optional load test (not load-tested) |
| 8 | Redis retry on every primitive | 🟢 Closed | none | None |
| 9 | Timezone awareness and central time retrieval | 🟢 Closed | none | None |
| 10 | Markdown to Telegram HTML conversion | 🟡 Ongoing | P2 | Test against a live send (TG-04) |
| 11 | Button press with an unwired `purpose` | 🟢 Closed | P3 | None |
| 12 | `delivery_failed` retry versus `completed`, and message length | 🟡 Ongoing | P2 | Length guard on the caption overflow message (TG-03) |
| 13 | `billing_exhausted` message and button | 🔴 Open | P2 | Decide what the button click should do (TG-07) |
| 14 | Captioned media accepted as input, not a draft | 🟡 Ongoing | P1 | Test against a live bot (TG-01) |

**Action list: everything still to resolve, highest priority first.** The ID on each row is repeated on the matching bullet in its section.

| ID | Pri | Action | What | § |
|----|-----|--------|------|---|
| TG-01 | P1 | TEST | Send a captioned image, video and file (expect one task each), a captionless one (expect a draft), a whitespace-only caption, an edited caption, and a captioned item while a draft is pending | 14 |
| TG-02 | P1 | BUILD | Rework the draft keep-alive so each button press adds 5 minutes to the wait, up to the 55 minute cap | 4 |
| TG-03 | P2 | BUILD | Add a length guard and a Tier 1 report to the caption overflow message | 12 |
| TG-04 | P2 | TEST | Check Markdown to HTML conversion on a live send (`**bold**`, `*bold*`, literal `<` and `&`) | 10 |
| TG-05 | P2 | TEST | Force an alert, let a send succeed, confirm one `gateway_recover`; repeat across a restart | 6 |
| TG-06 | P2 | CHECK | Confirm `type: "gateway_recover"` is what the backend consumer expects | 6 |
| TG-07 | P2 | DECIDE | What the `billing_exhausted` button click does after starting typing (blocks TG-10) | 13 |
| TG-08 | P2 | CHECK | Section 4's root-cause text says the loop advances whether or not the button is pressed, but `_draft_loop()` now closes an unanswered cycle. Confirm current behaviour and correct section 4 before TG-02 | 4 |
| TG-09 | P2 | BUILD | Give `coding_allowed` its own whitelist variable (needs the name, a P3 question) | 3 |
| TG-10 | P2 | BUILD | Implement the `billing_exhausted` branch and button (after TG-07) | 13 |

**P3, optional or whenever convenient:** §1 retire `session_cleared`, roll back the `_push_task()` mapping on failure; §2 the unsignalled-reset behaviour; §3 name of the new whitelist variable, `coding_allowed` on other payload types; §5 Redis retry default; §7 concurrency load test; §11 other button purposes; §13 button label, wording, TTL, second press, `answerCallbackQuery`, a live look at the generic display; §14 captioned albums, edited media without a caption, removing the old caption code from the draft path.

---

## 1. Admin-triggered global session reset

**Status:** 🟡 Ongoing

**In short:** `SESSION_RESET_ALLOWED_CHAT_IDS` names the bot admins who may clear every session. It was first built as a self-service per-chat reset, which was wrong. An admin now sends `"${TELEGRAM_BOT_NAME} refresh yourself"`, the gateway asks `bot_sanctuary` with `session_clear_request`, `bot_sanctuary` answers with one `session_reset`, and the gateway then sweeps every chat. Both sides are implemented. Only the retirement of the `session_cleared` event remains.

**Requirement (given directly by the user, authoritative)**
- Only two paths may ever clear a session. The first is the admin command, which clears every session including the admin's own. The second is a scheduled reset owned by `bot_sanctuary`. The gateway has no authority to start one on a schedule. A first attempt placed it here and was fully reverted.
- No chat can reset its own session on request.
- `coding_allowed` is a separate privilege from reset admin. The same people hold both today, but the two lists are not structurally tied (section 3).

**Root cause of the original bug**
- `_is_reset_allowed()` checked the requesting chat's own ID and `reset_session(chat_id)` only ever cleared that same chat. The whitelist pattern was copied from `TELEGRAM_ALLOWED_CHAT_IDS`, which answers "may this chat do X to itself", not "may this requester trigger a global action".
- No function enumerated sessions at all. `database.py` had no `session:*` sweep.

**Closed**
- 🟢 Part 0, enumeration: `get_all_session_chat_ids()` (`utils_redis/database.py`) scans every `session:<chat_id>` key. A reverse lookup `get_chat_id_for_session()` was added and then reverted, because no path needs `session_id` to `chat_id` resolution.
- 🟢 Part 1, command detection (`gateway_inbound.py`, `_is_reset_command()` and `_handle_reset_command()`):
  - Match is case-insensitive with whitespace normalised, and must equal the whole message.
  - A whitelisted requester gets a real `task_id` minted (as for any message) and a `session_clear_request` pushed. A non-whitelisted or non-matching message falls through to `_push_task()` as ordinary text.
  - Detection only runs on plain text with no draft pending. A draft's finalising text is never read as the command. This was an implementation assumption and was not reconfirmed.
  - CCR-024 fixed: the configured phrase is normalised the same way as the incoming text, so stray whitespace in `TELEGRAM_BOT_NAME` can no longer disable the command silently.
- 🟢 Part 2, outbound request: `{"task_id": <minted>, "type": "session_clear_request"}`. No `chat_id`, so `bot_sanctuary` stays chat-agnostic. `push_session_clear_request()` keeps `chat_id` only for its log lines.
- 🟢 Part 3, `bot_sanctuary` side: accept publishes one `session_reset` carrying the same `task_id` immediately, and reject sends an `error`. Tracked in `bot_sanctuary/CODE_TODO.md` section 8.
- 🟢 Part 4, sweep on receipt: `handle_session_reset_request(task_id)` first closes the triggering `task_id` through `get_task_mapping()` and `delete_task_mapping()` (the `session_reset` doubles as its `completed`). It then loops over every chat from `get_all_session_chat_ids()` and applies the existing `has_open_tasks()` decision per chat via `_defer_or_apply_reset()`.
  - The sweep is idempotent, runs as a plain sequential loop (the chat count is small and bounded), and does not special-case the admin's own chat.
  - Section 2's machinery needed no internal changes.
- 🟢 `_is_reset_allowed()` removed outright. A `session_reset` always comes from `bot_sanctuary`, so there was nothing to re-verify, and the check was silently dropping crash-recovery resets for every non-admin chat.
- 🟢 Part 5, `bot_started`: `resolve_pending_resets_on_bot_started()` resolves every pending entry directly through `_apply_session_reset()`, and also closes any lingering open poll first. There is no expiry check, because the restart is a fact, not a guess. It is dispatched from `process_message()` through `_handle_bot_started()`, ahead of the `task_id` gate. `_force_apply_session_reset()` and the ceiling sweep stay as defence in depth.
- 🟢 Hardening (defensive, not a proven gap):
  - `_defer_or_apply_reset()` clears a stale `pending_reset` before an immediate apply.
  - `_handle_reset_command()` rolls back the minted task mapping when the push fails, so a dead `session_tasks` entry cannot defer later resets.
- 🟢 CCR-023 fixed: `get_pending_reset()` returned `None` both for "no entry" and for an entry whose `task_id` was legitimately `None`, so natural completion silently fell back to the one-hour ceiling sweep. The sweep now stores a sentinel `SYSTEM_TRIGGERED_TASK_ID = "system_triggered"` for every non-triggering chat, so `None` always means "no entry". `database.py` needed no change.
- 🟢 `README.md` and `CODE_SEQUENCE_DIAGRAM.md` (sections 8.0 and 8.8) updated.
- 🟢 `session_cleared` payload no longer carries `chat_id` (`{"task_id": null, "session_id": ..., "type": "session_cleared"}`), restoring the identity-blind rule. `chat_id` is still a parameter for logging only.

**Open**
- 🔴 **P3 · BUILD** Retire `session_cleared` completely (the push here and `_handle_session_cleared()` on the other side). It is unblocked, because `SessionWorker.retire()` now tears down state proactively, but it has not been done.

**Decided**
- Rejected: `bot_sanctuary` enumerating every session and handing the gateway a target list. The gateway owns the chat and session mapping.
- Rejected: one `session_reset` per session, and sending it after clearing finishes. There is exactly one per trigger, sent when the request is accepted. This decouples the two sides so they clear in parallel. `session_id` was dropped from the payload because it serves no purpose here.
- Rejected: any `session_id` to `chat_id` resolution. The action is never scoped to one chat.
- No cross-process recovery of a half-finished sweep. A crash loses `bot_sanctuary`'s in-memory state, and `bot_started` is the whole reconciliation.
- Rejected for CCR-023: importing a private helper into `session_reset_handler.py`. A failed Redis read is treated as "not pending", which is fail-safe and backstopped by the ceiling sweep. This matches how every other Redis getter behaves.

**Known limitations**
- 🔴 **P3 · BUILD** `_push_task()` has the same unrolled-back mapping shape on its two failure branches. This is a separate, older risk and was not addressed.

**Open Questions**
- 🔴 **P3 · DECIDE** The name of the dedicated `coding_allowed` whitelist variable. Explicitly not to be addressed yet (section 3, where it blocks TG-09).

**Technical notes:** the code is in `utils_session/session_reset_handler.py`, `utils_redis/database.py`, `utils_queue/message_handler.py` and `utils_telegram/gateway_inbound.py`.

---

## 2. Graceful `session_reset` (deferred reset, crash-resilient ack)

**Status:** 🟡 Ongoing

**In short:** A reset waits until the chat's in-flight tasks finish instead of interrupting a poll or draft. The pending state is durable, survives a gateway crash, and is backstopped by a ceiling so it can never stick forever. Sections 0 to 8 are implemented. One UX question remains.

**Closed**
- 🟢 All logic lives in `utils_session/session_reset_handler.py`. `database.py` keeps the raw Redis primitives (`set_pending_reset`, `get_pending_reset`, `clear_pending_reset`, `get_all_pending_resets`). `message_handler.py` is a thin delegate, and `initialise.py` calls `resync_pending_resets()` at startup.
- 🟢 Deferral: if `session_tasks:<chat_id>` is non-empty the reset is stored as `pending_reset:<chat_id>` with a `created_at` timestamp. It has no TTL, because it must outlive an unbounded task. Nothing is sent to the chat while it waits. A repeat trigger overwrites the entry.
- 🟢 Resolution: `resolve_pending_reset_if_ready(chat_id)` runs after `delete_task_mapping()` in `_handle_completed` and `_handle_error`.
- 🟢 One place applies a reset, `_apply_session_reset(chat_id)`: stop the draft timer (CCR-012, still required because drafts have no `task_id`), `reset_session()` (now returns the cleared `session_id`), push `session_cleared`, then `send_reset_notice()`. The notice is sent for every chat cleared, not only the initiator.
- 🟢 `RESET_NOTICE_MESSAGE` is a single module variable, filled in directly in the file. The function sends whatever it holds and does nothing, with a warning, while it is unset.
- 🟢 Crash recovery: `resync_pending_resets()` runs after `close_orphaned_drafts()` and `close_orphaned_polls()`. It resolves only entries that are already resolvable. No `reset_pending` event exists.
- 🟢 The section 8 gap (a task's `completed` or `error` never arriving) was closed by direction C, which combines two fixes:
  - A: a poll that times out unanswered now pushes a `poll_timed_out` event (`_push_poll_timed_out()`), so the owning agent can decide.
  - B: `PENDING_RESET_MAX_WAIT_SECONDS` plus `created_at` and a sweep thread (`PENDING_RESET_SWEEP_INTERVAL_SECONDS`, `start_pending_reset_ceiling_sweep()`), also folded into `resync_pending_resets()`. It is cause-agnostic, so it is the only fix for the orphaned or expired mapping cause.
- 🟢 `stop_poll_for_reset()` was repurposed, not removed. `_force_apply_session_reset()` calls it as a guard against a ceiling configured shorter than `POLL_GLOBAL_CAP_SECONDS`.

**Open**
- 🔴 **P3 · DECIDE** The "unsignalled reset" behaviour. After a lull, a single reply can empty the queue and the reset and its notice then land straight behind it with no warning. This is the design behaving as specified, not a defect. Decide whether to accept it or add a short grace delay on the natural-empty path.

**Decided**
- A draft timeout is not a gap, because a draft never has a `task_id` until it is finalised.
- Section 7 (the whitelist check inside `handle_session_reset_request()`) is superseded by section 1. `SESSION_RESET_ALLOWED_CHAT_IDS` is enforced at command detection, not here.
- A silent log-only drop was the original behaviour for a non-whitelisted chat. It no longer applies.

**Technical notes:** `config.py` defines `SESSION_RESET_ALLOWED_CHAT_IDS` as a comma-separated variable parsed into `set[int]`, with a matching `config_sample.ini` key.

---

## 3. Agent-call access tier (`coding_allowed`)

**Status:** 🟡 Ongoing

**In short:** Every task payload built in `_push_task()` carries `coding_allowed`, which is `True` when the chat is whitelisted. It tags, it does not gate, so a non-whitelisted chat still gets a working conversation scoped to Chat only by `bot_sanctuary`. It currently reuses the reset-admin whitelist, which is wrong in principle.

**Closed**
- 🟢 `coding_allowed: chat_id in settings.SESSION_RESET_ALLOWED_CHAT_IDS` is stamped on every payload from `_push_task()`. The field name replaced the placeholder `full_access`.
- 🟢 No enforcement on this side. `bot_sanctuary` restricts the Calls, and the gateway only knows and stamps identity.

**Open**
- 🔴 **P2 · BUILD** [TG-09] A dedicated whitelist variable, decoupled from `SESSION_RESET_ALLOWED_CHAT_IDS`. Reusing it assumed a reset permission meant agent access, and section 1 showed that is a different privilege. Not implemented.
- 🔴 **P3 · DECIDE** The field is only on `_push_task()` payloads. The poll-answer, poll-timed-out, `delivery_failed` and `gateway_alert` pushes do not carry it, because those call sites only resolve `task_id` to `session_id`. Extend it if `bot_sanctuary` needs it on every type.

**Open Questions**
- 🔴 **P3 · DECIDE** The new variable's name. Deferred by you ("not to be addressed now"), but TG-09 cannot start without it.

---

## 4. Draft keep-alive button does not extend the timer

**Status:** 🔴 Open

**In short:** The "Give me a little while more" button (`continue_draft_timer()`, `image_draft_handler.py`) is documented as granting more time but only cuts the current cycle short. Pressing it can make the draft close sooner, which is the opposite of its purpose. The first fix implemented the wrong mechanic.

**Requirement (given directly by the user, authoritative)**
- Each cycle is 5 minutes (`DRAFT_CYCLE_SECONDS`): typing starts at 1 minute and the prompt with the continue button is sent at 3 minutes.
- A press adds 5 minutes to the current required wait, as a running total: 5 becomes 10, then 15, and so on. It does not start a fresh cycle.
- Hard ceiling of 55 minutes (`DRAFT_CLOSE_SECONDS`). No extension is granted beyond it.
- When the extended wait elapses, the next 5-minute cycle begins and repeats the pattern. The final cycle has the same typing and prompt but no button. At its end the final message is sent and the draft is cleared.

**Root cause**
- `_draft_loop()` computes `total_cycles` once and never changes it. A press runs Python's `continue`, which jumps to the next iteration of the fixed loop. The loop reaches the next cycle whether or not the button was pressed, so a press only changes when.
- The one cycle where more time would matter, the final one, is exactly the one with no button.
- The module header, the docstring and `README.md` describe the mechanics accurately but were read as proof the feature worked. The documentation is internally inconsistent.

**Closed**
- ⚪ The first fix ("preserve the remaining wait, then proceed to an unmodified next cycle") is superseded. It made a press a no-op for non-final cycles. Its helper `_wait_full_duration()` is being reworked, not discarded.

**Open**
- 🔴 **P1 · BUILD** [TG-02] Rework to the confirmed mechanic inside the existing `_draft_loop()` and `_wait_full_duration()`. The user explicitly asked for no additional helper functions.
- 🔴 **P1 · BUILD** [TG-02] `_wait_full_duration()` must report whether a stop signal ended the wait or the full duration elapsed. `_draft_loop()` must track the current cycle's required total, starting at `DRAFT_CYCLE_SECONDS`, adding one cycle per valid press, and capped at `DRAFT_CLOSE_SECONDS`.
- 🔴 **P1 · DOC** [TG-02] Correct the `continue_draft_timer()` docstring, the `_draft_loop()` docstring, the module header and the `README.md` section on pending drafts, once the rework is done.
- 🔴 **P2 · CHECK** [TG-08] The root-cause text above (the loop reaches the next cycle whether or not the button is pressed) no longer matches the code. `_draft_loop()` now closes an unanswered cycle, and `README.md` already says so. Confirm what the code does today, then correct this section before starting TG-02.

**Technical notes:** `utils_telegram/utilities/image_draft_handler.py` (`continue_draft_timer()`, `_draft_loop()`, `_consume_continue()`) and `README.md`.

---

## 5. Startup connection retry (RabbitMQ and Redis)

**Status:** 🟢 Closed

**In short:** The gateway used to crash if RabbitMQ or Redis was not up when it started. Startup now retries without limit and logs each attempt.

**Closed**
- 🟢 `initialise_rabbitmq_connection()` is a `while True` loop around the two single-attempt helpers. It catches `pika.exceptions.AMQPConnectionError`, logs a warning and sleeps. Other exceptions still propagate.
- 🟢 `initialise_redis_connection()` was changed in place with the same warning-and-sleep pattern. `_client` is reset to `None` after a failed attempt.
- 🟢 New settings `Q_CONNECT_RETRY_DELAY_SECONDS` and `REDIS_CONNECT_RETRY_DELAY_SECONDS`, both 5 seconds by default.
- 🟢 Docstrings updated to describe the blocking behaviour instead of a `Raises` contract.

**Decided**
- The fix is scoped to the startup entry points only. The shared per-connection helpers are reused at runtime, where `queue_push_task()` deliberately relies on a bounded retry (`Q_PUSH_MAX_ATTEMPTS`) and `queue_consume_task()` has its own reconnect loop. Making the helpers block would have turned a bounded retry into a hang.
- Accepted risk, the user's explicit call: the loops catch the whole `AMQPConnectionError` family and the whole `RedisError` hierarchy. A bad credential therefore also retries forever. Stability was preferred over fail-fast diagnostics, and every attempt is still logged.
- CCR-022: `REDIS_FORCE_INFINITE_RETRY` was added later and defaults to `False`, which reintroduces single-attempt behaviour for Redis only. The docstring was corrected and the decision recorded. The user chose to keep `False` for now (2026-09-09). Redis is deliberately more conservative than RabbitMQ.

**Open Questions**
- 🔴 **P3 · DECIDE** Whether `REDIS_FORCE_INFINITE_RETRY` should default to `True`. Revisit if a slow Redis start is seen degrading the alert state, the orphan sweeps or the pending-reset resync.

---

## 6. `gateway_recover` (Tier 2) and alert persistence

**Status:** 🟡 Ongoing

**In short:** `gateway_alert` had no counterpart telling the backend the incident was over. The gateway now pushes `gateway_recover` once per incident, and the armed or disarmed state survives a restart. Neither has been exercised end to end.

**Closed**
- 🟢 `_push_tier2_gateway_recover(status_code)` (`utils_queue/error_handling.py`) mirrors the alert payload (`task_id` and `session_id` null, `tier: 2`). Only `type` (`"gateway_recover"`) and `reason` (always `"recovered"`) differ. It returns `None`.
- 🟢 It fires once per incident. `record_send_success()` captures whether `_alert_armed` was `False` before resetting it, and only that transition pushes the event.
- 🟢 `record_send_success()` now takes `status_code`, and all 8 call sites in `gateway_outbound.py` pass `response.status_code`.
- 🟢 The recovery log line sits in `record_send_success()`, so a recovery is always visible even if the push fails.
- 🟢 CCR-019 fixed: `_alert_armed` was in memory, so the usual fix for a 401 or 404 (new token, restart) reset it and orphaned the recovery. The armed flag is now persisted in a Redis key `tier2_alert_armed` with no TTL.
  - It is written only on an actual transition and loaded at startup by `load_tier2_alert_state()`, called after `initialise_redis_connection()`.
  - `get_tier2_alert_armed()` defaults to armed on a missing key or a read failure.
- 🟢 `README.md`, and `CODE_SEQUENCE_DIAGRAM.md` (sections 10.1 to 10.4 and the new 10.6), updated.

**Open**
- 🔴 **P2 · CHECK** [TG-06] Check `type: "gateway_recover"` against what the backend consumer expects on `Q_CHANNEL_OUT`.
- 🔴 **P2 · TEST** [TG-05] End-to-end test: force a 401 or an unreachable state, let a send succeed, and confirm one recovery fires. Repeat after killing the process mid-incident and restarting.

**Decided**
- Only the armed flag is persisted. `_consecutive_failures` resetting on restart is accepted ("a restart is a fresh start at reassessing Telegram"). Persisting the counter too was rejected as scope creep.
- `_push_tier2_gateway_recover()` logs its own push outcome, like every other push helper. This was not requested, so it can be trimmed.

---

## 7. Concurrency fixes for Tier 2 publish and the publish channel

**Status:** 🟢 Closed

**In short:** Two ordering and thread-safety gaps in the alert path were fixed by widening locks. Both were verified by code inspection and neither has been run under concurrent load.

**Closed**
- 🟢 CCR-020 (Medium): the alert or recovery publish, and its Redis persist, ran after `_lock` was released, so two racing threads could publish out of order. `_lock` now covers the persist and publish inside the transition branches only. Non-transitioning calls still hold it only for the cheap variable update.
- 🟢 CCR-021 (High): the shared pika publish channel was used by many threads with no lock around `queue_declare()` and `basic_publish()`. `_lock_publish` now wraps the whole retry loop in `queue_push_task()`. It is an `RLock`, so the lazy reconnect nests safely. The module header was corrected, because it had claimed publish was confined to the caller's thread.

**Decided**
- A second dedicated `_publish_lock` was tried first for CCR-020 and rejected. After `_lock` is released, the order in which threads reach a second lock is scheduler-dependent, so reordering stayed possible. The decision and the publish must be one critical section under the same lock.
- Accepted cost, the user's call: a transitioning call can hold `_lock` for the full publish (about 30 seconds if RabbitMQ is also down), blocking other threads' success and failure bookkeeping. This only happens when the system is already broadly degraded.
- Rejected: a sequence number or timestamp in the payload. It would only make reordering detectable and needs a consumer change outside this repository.
- Rejected: per-thread publish connections. The application spawns many short-lived threads, so this would cause connection churn.
- `_lock_consume` needs no equivalent. Consume calls are confined to one thread, and `stop_queue_consumer()` already uses `add_callback_threadsafe()`.
- Lock ordering is one-directional (`error_handling._lock` then `_lock_publish`), so there is no deadlock. The worst-case latency compounds but stays bounded.

**Known limitations**
- Concurrent `queue_push_task()` callers fully serialise, including through each other's retry sleeps, so a caller can wait up to about 30 seconds when RabbitMQ is unreachable.

---

## 8. Redis retry on every primitive

**Status:** 🟢 Closed

**In short:** `_redis_write()` and `_redis_read()` had no retry, unlike `_redis_delete()`, and ten raw calls bypassed all three. Every Redis path now retries or guards, with no signature changes.

**Closed**
- 🟢 `_redis_write()` and `_redis_read()` retry up to `REDIS_TASK_MAX_ATTEMPTS` with `REDIS_TASK_RETRY_DELAY`, mirroring `_redis_delete()`. Callers that already used them gained retry with no change.
- 🟢 `get_task_mapping()`, `get_chat_draft()` and `get_poll_mapping()` lost their own duplicate retry loops.
- 🟢 `create_task_mapping()` lost its retry-and-regenerate loop entirely and makes one attempt. A first fix only removed the sleep, which was still retrying on any `False`. A `uuid4` collision is about 1 in 2^122.
- 🟢 New retrying primitives `_redis_sadd()`, `_redis_srem()` and `_redis_smembers()` cover the High and Medium raw calls:
  - High: the `session_tasks` index write in `create_task_mapping()` (a failure could let a reset apply while a task is open) and the read in `reset_session()`.
  - Medium: `delete_task_mapping()`, `create_poll_mapping()` and `get_session_poll_ids()`.
- 🟢 Low-risk raw calls (`delete_poll_mapping()`, `has_open_tasks()`, the three `scan_iter` sweeps) got a `_redis_ping()` pre-check. A failed ping falls back to each function's existing failure value. No return type changed. Two earlier intermediate designs, `_redis_ping()` returning the exception and each caller building its own exception, were rejected.

**Known limitations**
- A genuine outage logs an accurate `ERROR` from `_redis_read()` and then a slightly misleading `WARNING` "expired or unknown" from `get_task_mapping()`. Cosmetic.
- `get_all_pending_resets()`'s raw `client.get()` inside its scan loop is covered by the up-front ping but has no retry of its own.

---

## 9. Timezone awareness and central time retrieval

**Status:** 🟢 Closed

**In short:** Logging and wall-clock timing follow the `TZ` environment variable, and every direct time retrieval goes through two shared helpers. This was done together with `bot_sanctuary` (its section 9).

**Closed**
- 🟢 `config.py`: `TZ` and `get_env_timezone()` (silent fallback to `"UTC"`). The plain `TZ` name was kept because the container's OS layer expects it.
- 🟢 `logging_setup.py`: the shared `Formatter.converter` uses `settings.TZ`, covering both the console and file handlers.
- 🟢 `tzdata` added to `requirements.txt`, because `python:3.12.4-slim` has no guaranteed system zone database.
- 🟢 Root `config_sample.ini` and `config.ini` gained `CHATBOT_TZ="Asia/Singapore"`, and `compose.dev.yml` sets both services' `TZ` from it. It is not in the masked variable list, because it has one reasonable universal default.
- 🟢 `utilities/utilities.py`: `application_time()` returns the current time in `settings.TZ`, and `application_time_diff(reference)` returns elapsed seconds against a stored epoch. `set_pending_reset()` and `_is_pending_reset_expired()` were migrated. `time.sleep()` calls and the logging converter were deliberately left alone.
- 🟢 CCR-025 (Medium) fixed: `get_env_timezone()` only caught `ZoneInfoNotFoundError`. `ValueError` (absolute or `..` keys) and `IsADirectoryError` (for example `TZ=America`) would have crashed the process at import. It now catches `(ZoneInfoNotFoundError, ValueError, OSError)`. The same fix was applied to `bot_sanctuary`.
- 🟢 `README.md` has a new "Timezone" section.

---

## 10. Markdown to Telegram HTML conversion

**Status:** 🟡 Ongoing

**In short:** The persona writes `**bold**`, which Telegram's Markdown modes show as literal asterisks. A server-side converter now turns the constructs the persona actually produces into Telegram HTML, leaving the persona text untouched. It has not been exercised live.

**Closed**
- 🟢 New `utils_telegram/utilities/markdown_converter.py` with one public function, `to_telegram_html(text)`. It uses a fixed, ordered set of `re` substitutions and adds no dependency.
- 🟢 `parse_mode` switched from `"Markdown"` to `"HTML"` (`_TEXT_PARSE_MODE`). HTML only needs `&`, `<` and `>` escaped, and every substitution emits a balanced pair.
- 🟢 Order matters and is safety-critical:
  - Escape the whole text once, first.
  - Pull code spans out into placeholders before any formatting runs, then restore them.
  - Convert headers to a bold line, then bullets to `•`, then `**bold**` before `*bold*`, then `_italic_`, guarded so snake_case identifiers are not mangled.
- 🟢 Nesting fix (2026-09-15): the capture groups changed from `(.+?)` to `([^<\n]+?)`. Interleaved emphasis such as `**bold and _italic** text_` produced overlapping tags that Telegram rejects with a 400. Matches now stop at an already inserted tag and at a line break.
- 🟢 Scope is `_handle_text()` only. Button labels are plain text and are not converted. `gateway_outbound.py` and `button_prompt_handler.py` needed no change.

**Open**
- 🔴 **P2 · TEST** [TG-04] Verification on a real bot: resend a web-search synthesis, test `**bold**`, `*bold*` and literal `<` and `&`, and confirm only `_handle_text()` call sites changed.

**Decided**
- Only the constructs the persona produces are handled. `<u>`, `<s>`, `<tg-spoiler>` and `<blockquote>` are not.
- Skipped on the user's instruction, to preserve the persona: rewording `chat.json` to hand-write Telegram syntax, and tightening reply length. Revisit only if server-side conversion alone proves insufficient.

---

## 11. Button press with an unwired `purpose`

**Status:** 🟢 Closed

**In short:** The persona can attach buttons with any `purpose`, but only `draft_continue` was wired, so a press such as `select_shoe` was validated and then silently dropped. A press now routes back onto the same `task_id` the buttoned message was sent against.

**Evidence:** the live log (2026-09-16, chat 543086109) showed a valid callback for `select_shoe` hitting the deliberate no-op branch with no response, while later taps were correctly rejected as consumed or expired.

**Closed**
- 🟢 `register_bot_button()` takes a `task_id` and stores it in `_registered_callbacks[token]`. `validate_bot_callback()` returns `{"purpose", "payload", "task_id"}`. `_build_button_rows()` threads the `task_id` through.
- 🟢 `_push_button_press()` (`gateway_inbound.py`) mirrors `_push_poll_answer()`. It pushes a payload carrying `button_press: {"purpose", "payload"}` against the original `task_id`, for any purpose other than `draft_continue`. No new task is minted.
- 🟢 The consumer side (`_extract_item_text()` in `bot_sanctuary`) landed the same day, so the press now reaches the persona (`bot_sanctuary/CODE_TODO.md` section 12).

**Decided**
- Rejected: hardcoding `select_shoe` as a second purpose, because the persona can invent any purpose at any time.
- Rejected: minting a new `task_id` for a press. The existing one is already held open by `bot_sanctuary`.
- Declined by the user: `answerCallbackQuery`, which dismisses the client-side spinner. It is purely cosmetic. Reopening needs a fresh request.

**Open Questions**
- 🔴 **P3 · DECIDE** Whether any purpose besides `select_shoe` and `draft_continue` is expected, which only affects how the folded-in prompt wording is phrased. Non-blocking.

---

## 12. `delivery_failed` retry versus `completed`, and message length

**Status:** 🟡 Ongoing

**In short:** A long reply with no buttons was rejected by Telegram with a 400, and the retry that `bot_sanctuary` was asked to make was then dropped because the `completed` marker had already deleted the task mapping. Both causes are fixed. One narrower length gap remains.

**Evidence:** both logs, 2026-09-16 09:17 to 09:18, `task_id=9478f79c8fd74cdbb6dd71aa1f0ec650`. The gateway sent a long plain reply, got a 400 and pushed `delivery_failed`. It then processed the queued `completed` and deleted the mapping. `bot_sanctuary` ran a third Claude turn and republished, and both messages were dropped with "No task mapping found". The user got nothing, and three Claude calls were spent (about 107,800 cached read tokens combined).

**Closed**
- 🟢 Fix (a), length: `_split_for_telegram()` and `_split_oversized_line()` (`message_handler.py`) split the raw text before conversion, then convert each chunk. Splitting before conversion keeps a delimiter cut in half as a literal character, never an unbalanced tag. Lines are packed as full as possible, and an over-long line is bisected recursively. `_handle_text()` sends every chunk in order and reports Tier 1 on the first rejected chunk.
- 🟢 Fix (b), the race: `push_tier1_delivery_failed()` sets a `pending_retry:<task_id>` marker (TTL `REDIS_TASK_MAPPING_TTL_SECONDS`) after a successful push. `_handle_completed()` calls `pop_pending_retry()` before `delete_task_mapping()`. If a retry is outstanding the mapping is kept alive, and the retry's own `completed` deletes it.
- 🟢 The retry's content depends on `bot_sanctuary` recognising a `delivery_failed` payload (`bot_sanctuary/CODE_TODO.md` section 12), which landed the same day.

**Open**
- 🔴 **P2 · BUILD** [TG-03] `_send_media_with_caption()`'s overflow `remainder` has no length check and its result is not reported as Tier 1. No media call ever sets `parse_mode`, so there is no tag to cut, and the risk is purely length. The scoping is complete and the guard is not written. It would likely reuse `_split_for_telegram()`.

**Decided**
- `_handle_error()` is deliberately not given the same treatment. An `error` means `bot_sanctuary` hit a blocking failure with no corrective retry coming.
- Rejected (b1): `bot_sanctuary` minting a fresh `task_id` for the retry. It never mints task IDs, because `create_task_mapping()` only runs in `gateway_inbound.py`. Rejected (b2) as first drafted: new tracking state on the gateway. The `pending_retry` marker is the simpler outcome.
- Dropped before implementation: a fallback `restore_task_mapping()`. The consumer runs on a single thread with no prefetch, so each message finishes before the next is dequeued and the race it guarded against cannot occur.
- Fix (a) alone would have prevented this incident. Fix (b) covers every other Tier 1 rejection reason.

---

## 13. `billing_exhausted` message and button

**Status:** 🔴 Open

**In short:** `bot_sanctuary` now reports a depleted provider balance or quota as `{"type": "error", "error_type": "billing_exhausted", "message": ...}`. The gateway has no special handling, so the user sees the generic "having difficulty managing a problem" wording with a fixed English message and no button. A bespoke message and a button whose click starts the typing indicator were requested. Nothing is implemented here.

**Context**
- `_handle_error()` special-cases only `token_exhausted`, the "taking a nap" message with a countdown, modelled on a known wait of about 5 hours. A depleted balance has no known end time, so reusing it would promise a recovery nobody can guarantee. That is why a separate type exists.
- The `bot_sanctuary` half is done (`bot_sanctuary/CODE_TODO.md` section 17).

**Decided**
- The error type is `billing_exhausted`. It is fixed, agreed and already emitted.
- Add a branch in `_handle_error()` with persona-style wording, sending through `send_message_with_buttons()` with one button registered through `register_bot_button()` under a new purpose.
- "Polling click" is read as the existing update polling receiving the button's `callback_query`, not a Telegram poll (`sendPoll`). The click starts the indicator through `typing_indicator.py::start_typing()`.

**Constraints found while planning**
- `_handle_error()` calls `delete_task_mapping()` right after sending. A press routed through `_push_button_press()` would therefore be pushed against a deleted mapping and dropped, the same failure section 11 fixed. The click must be handled locally like `draft_continue`, unless the handler mints a new task.
- `start_typing()` is keyed by `task_id` and stops on that task's `completed` or `error`, or on its randomised ping cap, so for a finished task only the cap stops it.

**Open Questions**
- 🔴 **P2 · DECIDE** [TG-07] What the click should actually do after starting typing. This is the main unresolved decision. Options: show typing and nothing else (looks like a hang), or re-submit the user's last message as a new task. The second needs the original text, which the gateway is not known to retain (not verified), plus a fresh `create_task_mapping()`.
- 🔴 **P2 · CHECK** [TG-07] Confirm that "polling click" means the existing update polling.
- 🔴 **P3 · DECIDE** Whether a second press, or a press while the balance is still empty, needs handling. The retry would just produce another `billing_exhausted`.
- 🔴 **P3 · DECIDE** The button label and the message wording, in the persona.
- 🔴 **P3 · DECIDE** Whether to call `answerCallbackQuery` for this button. It was declined elsewhere as cosmetic, but here the click has a visible effect.
- 🔴 **P3 · DECIDE** Whether the button's TTL should be longer, since a billing outage can last hours or days.

**Follow-up Work**
- 🔴 **P2 · DECIDE** [TG-07] Decide the click behaviour first, because the rest depends on it.
- 🔴 **P2 · BUILD** [TG-10] Implement the `_handle_error()` branch, the button and its local click handler, after TG-07.
- 🔴 **P2 · DOC** [TG-10] Document `billing_exhausted` in `README.md` beside `token_exhausted`.
- 🔴 **P3 · TEST** Not verified against a live bot: how the generic branch currently displays it.

**Technical notes:** `utils_queue/message_handler.py` (`_handle_error()`), `button_prompt_handler.py`, `gateway_inbound.py` (`_handle_update()`), `typing_indicator.py`.

---

## 14. Captioned media accepted as input, not a draft

**Status:** 🟡 Ongoing

**In short:** A captioned image, video or file used to be staged as a pending draft and only became a task when a follow-up text arrived (or was lost when the draft timed out). Media with a non-blank caption is now a complete input: it is pushed as a task immediately, with the caption as the text. Captionless media keeps the draft flow. Planned and implemented 2026-10-06, not yet run.

**Closed**
- 🟢 `gateway_inbound.py::_handle_update()`: a new branch ahead of the draft branch handles media whose caption is non-blank after `.strip()`. It resolves the URL and calls `_push_task()` with the stripped caption and the matching `<type>_url`. No draft or timer is created.
- 🟢 Pending draft plus captioned item: the new branch runs before `get_chat_draft()`, so the captioned item is its own task and the pending draft stays pending. The "still curious" reply is now only reachable for captionless media (the user's choice, recorded as keeping that path as unreachable-for-captions code).
- 🟢 Edited captions: an `edited_message` carrying a caption is ignored and logged.
- 🟢 Whitespace-only caption counts as no caption, in both the new branch and the draft branch (`caption` is stripped before `create_chat_draft()`).
- 🟢 Albums are unchanged (still the "resend one at a time" reply, checked first).
- 🟢 Draft finalisation keeps its caption-joining branch for drafts created before this change.
- 🟢 Updated: the `gateway_inbound.py` header notes, `README.md` (pending drafts section and design bullet) and `CODE_SEQUENCE_DIAGRAM.md` section 4.1 to 4.3.

**Context**
- The current behaviour is in `gateway_inbound.py::_handle_update()`: `create_chat_draft(..., caption, bool(caption))` and `start_draft_timer()`, then the follow-up text is joined as `"<caption> <follow-up>"` and pushed through `_push_task()`.
- The caption is already stored on the draft and already forms the start of the final text, so the data needed is all in hand at the point the media arrives.

**Decided (plan)**
- In the media branch, a non-empty caption (after `.strip()`) skips the draft entirely: resolve the file URL with `_resolve_file_url()`, then call `_push_task(chat_id, user_id, caption, **{_MEDIA_FIELD_NAMES[media_type]: url})`. No draft, no timer.
- The existing failure replies are reused unchanged: the "had trouble receiving that" reply when the URL cannot be resolved, and `_push_task()`'s own apology messages.
- A captionless item keeps the current draft flow, including the draft timer and the "still curious" reply.
- Draft finalisation keeps its caption-joining branch (`has_caption`). A draft created before deployment can still hold a caption, and Redis holds it until it expires, so removing the branch would change those in-flight drafts. New drafts will always have `has_caption=False`.
- No change to the outbound queue payload shape, `coding_allowed`, or typing (`_push_task()` starts it after a successful push).

**Open Questions**
- 🔴 **P3 · DECIDE** Albums (`media_group_id`): a caption on one album item is still unusable. Left unchanged by decision, and not requested.
- 🔴 **P3 · DECIDE** Edited media without a caption still creates a draft as before. Only edited captions are ignored.

**Dependencies and risks**
- `bot_sanctuary` does not read `image_url`, `video_url` or `file_url` yet (`bot_sanctuary/CODE_TODO.md` section 12, open). The caption text will reach the persona and the media will not, exactly as it does for a finalised draft today. This is not a regression, but the requirement's value depends on that follow-up.
- A caption can be up to 1024 characters (`TELEGRAM_CAPTION_MAX_LENGTH`), so a caption alone can already be a long instruction. No length handling is needed on the inbound side.
- Two quick captioned items in a row now produce two tasks instead of one draft plus a "still curious" reply. `bot_sanctuary` coalesces queued messages, but only `text` is merged, so one media URL could be unread (same root cause as above).
- The caption is not checked against the reset command. This matches the existing rule that the command is only read from plain text.

**Follow-up Work**
- ➜ Section 4's draft timer rework (TG-02) is unaffected and stays open.
- 🔴 **P1 · TEST** [TG-01] Test (not run): send a captioned image, video and file and confirm one task with the caption as `text` and the matching URL field. Then send a captionless one and confirm the draft flow is unchanged. Then cover the pending-draft, edited-caption and unresolvable-file cases.
- 🔴 **P3 · BUILD** Deferred, optional: drop the now-unused caption handling from the draft code once no old draft can exist.

**Technical notes:** `utils_telegram/gateway_inbound.py` (`_handle_update()`, `_extract_media()`), `utils_redis/database.py` (`create_chat_draft()`), `README.md`, `CODE_SEQUENCE_DIAGRAM.md`.
