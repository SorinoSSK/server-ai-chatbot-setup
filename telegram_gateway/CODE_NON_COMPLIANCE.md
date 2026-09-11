# Non-Compliance Report — Telegram Gateway Application

| | |
|---|---|
| **Scope** | `telegram_gateway/telegram_gateway_application/` (all Python source files) |
| **Review Type** | Static compliance review, followed by an instructed remediation pass |
| **Reviewer** | Claude Code (Code Compliance Reviewer) |
| **Review Date** | 2026-09-03 |
| **Remediation Date** | 2026-09-03 |
| **Follow-up Review Date** | 2026-09-04 — scoped to the `user_id`-removal / permanent `session_id` change (CCR-012–CCR-014) |
| **Second Follow-up Review Date** | 2026-09-05 — scoped to `TODO.md`'s graceful `session_reset` implementation (CCR-012/CCR-013 remediation verification; CCR-015 new) |
| **Revalidation Date** | 2026-09-05 — "revalidate all open CCR" (CCR-005, CCR-011, CCR-014, CCR-015 re-checked against current disk state) |
| **Third Follow-up Review Date** | 2026-09-05 — scoped to a behaviour change in `utils_telegram/utilities/image_draft_handler.py`'s draft keep-alive cycle (continue-button wait-preservation logic); CCR-016–CCR-018 new |
| **Validation Date** | 2026-09-05 — "validate CCR 16, 17, and 18" (all three re-checked directly against current source) |
| **Second Validation Date** | 2026-09-05 — "validate CCR 16, 17, and 18" repeated (all three found RESOLVED, not authored this session) |
| **Fourth Follow-up Review Date** | 2026-09-08 — scoped to `error_handling.py`'s new `record_send_success()`/`_push_tier2_gateway_recover()` addition (the `gateway_recover` Tier 2 feature); CCR-019–CCR-021 new |
| **Fifth Follow-up Review Date** | 2026-09-08 — scoped to major changes in `utils_redis/database.py` and validation of CCR-019; CCR-019 confirmed RESOLVED, CCR-022 new |
| **Sixth Validation Date** | 2026-09-09 — "validate CR-022 fix" — CCR-022 re-checked directly against current source; confirmed RESOLVED |
| **Seventh Validation Date** | 2026-09-09 — "validate CR-020 fix" — CCR-020 re-checked directly against current source; confirmed PARTIALLY RESOLVED (Medium → Low), residual race identified and disclosed |
| **Eighth Validation Date** | 2026-09-09, same day — "validate CR-020 fix" repeated — implementation changed (`_publish_lock` replaced with widened `_lock` scope); CCR-020 re-checked and confirmed fully RESOLVED, superseding the seventh pass's interim rating |
| **Ninth Validation Date** | 2026-09-09, same day — "validate ccr-021" — CCR-021 re-checked directly against current source; confirmed RESOLVED (`_lock_publish` widened to cover the entire publish critical section); no Medium-or-above findings remain open |
| **Tenth Follow-up Review Date** | 2026-09-12 — "reverify telegram_gateway for non-compliance and weakness" following the new `session_reset` broad-sweep/admin-command redesign (`CODE_TODO.md`'s "BUG — `SESSION_RESET_ALLOWED_CHAT_IDS` implements self-service per-chat reset, not admin-triggered global reset" entry, Parts 0–5, implemented 2026-09-12); CCR-023–CCR-024 new |
| **Eleventh Validation Date** | 2026-09-12, same day — "verify changes on CCR-023 and CCR-024 and update non-compliance audit" — both re-checked directly against current source; both confirmed RESOLVED |
| **Review Depth** | 3 iterations (initial read, cross-file/context analysis, evidence validation); follow-up pass likewise 3 iterations (structural/data-flow read, cross-file/concurrency analysis, evidence re-validation); second follow-up pass likewise 3 iterations (checklist-vs-code trace, concurrency/lock-symmetry analysis, evidence re-validation); revalidation pass - direct source re-read of every open finding, no assumptions carried over from prior report text; third follow-up pass - full control-flow and cross-thread interleaving trace of the changed file against `README.md`'s documented spec and the structurally analogous `poll_response_handler.py`; fourth follow-up pass - traced the new call path (`record_send_success()` → `_push_tier2_gateway_recover()` → `queue_push_task()`) against `TODO.md`'s own stated design/decisions, `config.py`'s token-loading behaviour, and `queue.py`'s publish-connection threading model; fifth follow-up pass - full re-read of `database.py` against its prior state, cross-referenced against `CODE_TODO.md`'s newly-added fix entries, `initialise.py`'s call ordering, and every caller of every changed/added function for signature/behavioural regressions; sixth pass (validation only) - direct re-read of `database.py::initialise_redis_connection()`'s docstring, `config.py`'s `REDIS_FORCE_INFINITE_RETRY` default, and `CODE_TODO.md`'s decision log against the finding's own Recommended Remediation; seventh pass (validation only) - direct re-read of `error_handling.py`'s new `_publish_lock`, a lock-ordering/deadlock trace, and a first-principles concurrency analysis of the gap between `_lock` release and `_publish_lock` acquisition against the finding's own Recommended Remediation; eighth pass (validation only, same day) - full re-read of `error_handling.py` against its state at the seventh pass, confirming `_publish_lock`'s removal and `_lock`'s widened scope, a repeated lock-ordering/deadlock trace across `database.py` and `queue.py`, and an assessment of the newly-accepted full-publish-duration blocking trade-off; ninth pass (validation only, same day) - full re-read of `queue.py` against its prior state, a codebase-wide search confirming no unguarded access path to the shared publish channel remains, a full three-module lock-graph deadlock trace (`error_handling.py`/`database.py`/`queue.py`), and a quantified worst-case-latency analysis of this fix's compounding interaction with the CCR-020 fix; tenth follow-up pass - full re-read of `utils_session/session_reset_handler.py`, `utils_telegram/gateway_inbound.py`, `utils_queue/message_handler.py`, `utils_redis/database.py` (the new `get_all_session_chat_ids()`/`pending_reset:<chat_id>` primitives), `utilities/initialise.py`, and `config.py`, cross-referenced end-to-end against `CODE_TODO.md`'s own multi-part design record for the broad-sweep/admin-command redesign and against `README.md`'s own documented `session_reset`/`pending_reset` contract - not assumed correct from the checklist's "Implemented" status markers alone |

---

## Review Summary

**Files Reviewed (16):**
- `main.py`, `config.py`
- `utilities/utilities.py`, `utilities/logging.py` (superseded — see CCR-009), `utilities/logging_setup.py` (added by remediation), `utilities/initialise.py`
- `utilities/utils_gatekeeper/gatekeeper.py`
- `utilities/utils_redis/database.py`
- `utilities/utils_queue/queue.py`, `utilities/utils_queue/error_handling.py`, `utilities/utils_queue/message_handler.py`
- `utilities/utils_telegram/gateway_inbound.py`, `utilities/utils_telegram/gateway_outbound.py`
- `utilities/utils_telegram/utilities/typing_indicator.py`, `poll_response_handler.py`, `button_prompt_handler.py`, `image_draft_handler.py`

**Additional files re-reviewed in the 2026-09-04 follow-up pass (`user_id`-removal / `session_id` change):** `utils_queue/message_handler.py`, `utils_queue/error_handling.py`, `utils_redis/database.py`, `utils_telegram/gateway_inbound.py`, `utils_telegram/utilities/poll_response_handler.py`, `utils_telegram/utilities/image_draft_handler.py`, `README.md` (payload contract) — see CCR-012–CCR-014 and the accompanying informational note.

**Additional files re-reviewed in the 2026-09-05 second follow-up pass (`TODO.md` `session_reset` implementation):** `utils_session/session_reset_handler.py` (new), `utils_redis/database.py`, `utils_queue/message_handler.py`, `utils_queue/error_handling.py`, `utilities/initialise.py`, `config.py`, `utils_telegram/utilities/poll_response_handler.py`, `utils_telegram/utilities/image_draft_handler.py`, `utils_telegram/gateway_inbound.py`, `utils_queue/queue.py`, `README.md`, `config_sample.ini`, `compose.dev.yml` — see CCR-012/CCR-013 (resolved), CCR-014 (re-confirmed open), CCR-015 (new), and the accompanying informational note.

**Additional files re-reviewed in the 2026-09-05 third follow-up pass (`image_draft_handler.py` behaviour change):** `utils_telegram/utilities/image_draft_handler.py` (changed file), cross-referenced against `README.md` §"Pending drafts", `config.py` (`DRAFT_*` settings, `get_env_int()`), `utils_telegram/utilities/poll_response_handler.py` (structurally analogous control-dict/background-loop pattern), `utils_telegram/utilities/button_prompt_handler.py`, `utils_telegram/gateway_inbound.py`, `utils_redis/database.py::reset_session()`/`delete_chat_draft()` — see CCR-016–CCR-018 (new).

**Additional files re-reviewed in the 2026-09-08 fourth follow-up pass (`error_handling.py`'s new `gateway_recover` Tier 2 feature):** `utils_queue/error_handling.py` (changed file — `record_send_success()`, `_push_tier2_gateway_recover()`, and their interaction with the pre-existing `record_send_failure()`/`_push_tier2_gateway_alert()`), `utils_telegram/gateway_outbound.py` (all 8 updated `record_send_success()` call sites), `utils_queue/queue.py` (`queue_push_task()`, `_get_rabbitmq_publish_channel()`, `_lock_publish`), `config.py` (`TELEGRAM_BOT_TOKEN` loading, `Q_PUSH_MAX_ATTEMPTS`/`Q_PUSH_RETRY_DELAY`), `utils_queue/message_handler.py`, `CODE_TODO.md` ("NEW — `gateway_recover`" section, the feature's own stated design decisions and open questions), `CODE_SEQUENCE_DIAGRAM.md` §10.1–10.4 — see CCR-019–CCR-021 (new).

**Additional files re-reviewed in the 2026-09-08 fifth follow-up pass (major `database.py` changes; CCR-019 validation):** `utils_redis/database.py` (changed file, read in full — `_get_chat_lock()`, `_redis_write()`/`_redis_read()`/`_redis_delete()`/`_redis_sadd()`/`_redis_srem()`/`_redis_smembers()`/`_redis_ping()`, `create_task_mapping()`, `create_poll_mapping()`, `reset_session()`, `get_tier2_alert_armed()`/`set_tier2_alert_armed()` (new), `initialise_redis_connection()`/`_should_redis_retry_infinite()` (new)), `utils_queue/error_handling.py` (`load_tier2_alert_state()`, updated `record_send_success()`/`record_send_failure()`), `utilities/initialise.py` (call ordering), `config.py` (new `REDIS_FORCE_INFINITE_RETRY` setting), `utils_queue/queue.py` (comparison against `initialise_rabbitmq_connection()`), `utils_session/session_reset_handler.py` (`get_all_pending_resets()` 3-tuple unpacking, unchanged), `README.md` (Redis env var table), `CODE_TODO.md` ("FIX — CCR-019", "FIX — `_redis_write()`/`_redis_read()` had no retry", "FIX — remaining raw `sadd`/`srem`/`scard`/`smembers`/`scan_iter` calls" entries) — see CCR-019 (validated RESOLVED), CCR-020 (extended), CCR-022 (new).

**Standards Evaluated:** PEP 8, PEP 257, OWASP Top 10, CWE mappings, Bandit-style secure coding guidance, general secure-scripting/reliability best practice.

**Overall Assessment:** The codebase is well-documented, consistently structured, and demonstrates mature error-handling patterns (tiered failure reporting, retry/backoff, orphan-recovery sweeps). No injection, authentication-bypass, or memory-safety defects were found. The most significant issues concerned **credential exposure through exception logging** and **verbose logging of raw user data**, plus several lower-severity configuration/reliability gaps — the majority of which have now been remediated (see Remediation Summary below).

**Total Findings:** 11 (1 High, 4 Medium, 5 Low, 1 Informational)

**Remediation Summary (this pass):** 6 of 11 findings actioned at the user's instruction — CCR-001, CCR-002, CCR-007, CCR-009, CCR-010 **RESOLVED**; CCR-006 **MITIGATED** (residual architectural risk explicitly accepted — see its entry for detail). CCR-003, CCR-004, CCR-005, CCR-008, CCR-011 were explicitly excluded from this pass at the user's request.

**Re-verification (2026-09-03, on request, "reverify CCR 3,4,5,8"):** CCR-003, CCR-004, CCR-005, CCR-008 were re-checked directly against current source (not cached report text) at the user's request. Current code differs from what the original findings describe, for reasons outside this session's Fix Mode edits — **not authored by this session**, validated as found on disk:
- **CCR-003: RESOLVED** — `DEFAULT_Q_USER`/`DEFAULT_Q_PASSWORD` are now `""` (was `"chatbotAdmin"`/`"chatbotAdmin"`); no functional default credential remains.
- **CCR-004: PARTIALLY RESOLVED, severity Medium → Low** — `REDIS_USERNAME`/`REDIS_PASSWORD` now exist and are wired into the Redis client (CWE-306 component closed); TLS is still absent (CWE-319 component remains open, tracked under CCR-005).
- **CCR-005: unchanged, still OPEN** — no TLS added to either the RabbitMQ or Redis connection.
- **CCR-008: RESOLVED** — `REDIS_SOCKET_CONNECT_TIMEOUT`/`REDIS_SOCKET_TIMEOUT` now exist and are wired into the Redis client.

CCR-011 was not part of the reverification request and remains **OPEN**, unexamined this pass.

**Follow-up Review (2026-09-04, on request, "review telegram_gateway_application 3 times and look for new weaknesses" — scoped to a subsequent change removing `user_id` from outbound RabbitMQ payloads and introducing a permanent, per-`chat_id` `session_id` reset via a `session_reset` queue message):** Re-read `utils_queue/message_handler.py`, `utils_queue/error_handling.py`, `utils_redis/database.py`, `utils_telegram/gateway_inbound.py`, `utils_telegram/utilities/poll_response_handler.py`, and `utils_telegram/utilities/image_draft_handler.py` directly against current source, plus `README.md`'s payload contract, across 3 passes. Confirmed the `user_id`-removal itself is implemented correctly and consistently (no outbound payload leaks `user_id`; verified via full-codebase `grep`). Three new findings and one informational governance note were identified in the new `session_id`/`session_reset` logic and are recorded below as **CCR-012, CCR-013, CCR-014**. No fixes were applied this pass (review-only; not instructed to enter Fix Mode).

**Second Follow-up Review (2026-09-05, on request, "review TODO.md and verify all changes made for non-compliance" — scoped to `TODO.md`'s graceful, crash-resilient `session_reset` implementation, built specifically to close CCR-012/CCR-013):** Re-read `utils_session/session_reset_handler.py` (new), `utils_redis/database.py`, `utils_queue/message_handler.py`, `utils_queue/error_handling.py`, `utilities/initialise.py`, `config.py`, `utils_telegram/utilities/poll_response_handler.py`, `utils_telegram/utilities/image_draft_handler.py`, `utils_telegram/gateway_inbound.py`, `utils_queue/queue.py`, `README.md`, `config_sample.ini`, and `compose.dev.yml` directly against current source, across 3 passes. Every checkbox in `TODO.md` §0–§8 (including the "Also to fold back in" items) was traced to real, correctly-wired code rather than assumed from the checklist alone - including confirming no circular import was introduced (`queue.py` → `message_handler.py` → `utils_session/session_reset_handler.py` → `gateway_outbound.py`/`image_draft_handler.py`/`poll_response_handler.py`, none of which import `queue.py` at module level).

**CCR-012 and CCR-013 are both confirmed RESOLVED** by this work - see their entries below for validation detail. This remediation was **not authored in this session**; it is validated against current disk state only, same provenance caveat as CCR-003/CCR-004/CCR-008 above. One new Low-severity finding, **CCR-015**, was identified: `create_poll_mapping()`'s `session_polls:<chat_id>` indexing is not serialised against `reset_session()` via the same per-`chat_id` lock (`_get_chat_lock()`) that now protects `create_task_mapping()`, reintroducing CCR-013's structural pattern in a narrower, not-conclusively-reachable form. **CCR-014 was re-checked and remains open** - unaddressed, out of scope for this work. One further informational note (`RESET_NOTICE_MESSAGE` shipping blank) is recorded for operational-readiness traceability. No fixes were applied this pass (review-only; not instructed to enter Fix Mode).

**Revalidation (2026-09-05, on request, "revalidate all open CCR"):** Every finding still marked Open at that point - **CCR-005, CCR-011, CCR-014, CCR-015** - was re-read directly against current source (not cached report text). Two have since been fixed, **outside this session's own edits**, between the second follow-up review above and this revalidation request:
- **CCR-014: now RESOLVED** - the unused `user_id = mapping.get("user_id")` assignment in `message_handler.py::process_message()` has been removed; confirmed via `grep` that `user_id` no longer appears anywhere in the file body (only a stale reference in the module's own header comment - see the finding's entry below).
- **CCR-015: now RESOLVED** - `create_poll_mapping()` (`utils_redis/database.py`) now wraps its write+index step in `with _get_chat_lock(chat_id):`, the same lock `reset_session()`/`create_task_mapping()` already use, closing the asymmetry this finding identified.
- **CCR-005: unchanged, still OPEN** - re-confirmed via `grep` that no `ssl`/`TLS` configuration exists in `utils_queue/queue.py` or `utils_redis/database.py`; `compose.dev.yml`'s RabbitMQ/Redis `ports:` mappings remain commented out (unchanged network isolation).
- **CCR-011: unchanged, still OPEN** - re-confirmed `button_prompt_handler.py::_registered_callbacks` is still pruned only by age (`_prune_expired_callbacks()`), with no size-based cap.

As of this revalidation, only **CCR-005** (Low, accepted risk) and **CCR-011** (Low, skipped/unaddressed) remain open in this report.

**Third Follow-up Review (2026-09-05, on request, "changes have been made to image_draft_handler.py including behaviour change, validate non-compliance" — scoped to a behaviour change in the draft keep-alive cycle's continue-button handling):** Re-read `utils_telegram/utilities/image_draft_handler.py` directly against current source, exhaustively tracing every control-flow path — including cross-thread interleaving between the per-chat background loop and the RabbitMQ/Telegram-polling thread invoking `continue_draft_timer()`/`stop_draft_timer()` — against `README.md`'s independently-maintained spec for this exact feature (§"Pending drafts") and `config.py`'s actual default values. The changed behaviour itself (a continue-button press now preserves the current cycle's remaining wait rather than cutting it short) was confirmed correctly and consistently implemented, matching `README.md` exactly at current defaults, with no reachable data-corruption, crash, or resource-leak path identified across every interleaving traced. At the user's explicit instruction, three findings arising from this review — one previously assessed as not independently reachable/no-action-required — are recorded below as open non-compliance findings: **CCR-016, CCR-017, CCR-018**.

**Total Findings (cumulative):** 24 (2 High, 9 Medium, 8 Low, 5 Informational) - 22 numbered findings (CCR-001–CCR-022) plus 2 unnumbered informational notes (session-identifier retention, 2026-09-04; `RESET_NOTICE_MESSAGE` shipping blank, 2026-09-05). As of the 2026-09-09 sixth validation pass, CCR-022 is confirmed RESOLVED. The same-day seventh validation pass initially confirmed CCR-020 only PARTIALLY RESOLVED (downgraded Medium → Low); the eighth validation pass, later the same day, confirmed a subsequent code change fully closes it, superseding that interim rating. The same-day ninth validation pass confirmed CCR-021 (High) is also now RESOLVED. No High- or Medium-severity findings remain open as of this pass — only two unchanged Low-severity items remain (CCR-005 accepted risk, CCR-011 skipped), neither treated as a hard blocker.

**Validation (2026-09-05, same day, on request "validate CCR 16, 17, and 18"):** All three findings were re-read directly against current source (not cached report text) rather than assumed still accurate from the prior pass. All three are **re-confirmed Open, substance unchanged**. One incidental, non-substantive change was found in the file in the interim: `_stop()` was renamed to `_stop_draft_loop()` (identical body/behaviour) — CCR-018's Location/Evidence has been corrected to reflect this; it does not affect CCR-016 or CCR-017. CCR-018's cross-file comparison against `poll_response_handler.py` was also independently re-checked and remains accurate (that file is unchanged).

**Second Validation (2026-09-05, same day, on request "validate CCR 16, 17, and 18" repeated):** All three findings were re-read directly against current source. This time, **all three are confirmed RESOLVED** — each finding's own recommended remediation has been applied, near-verbatim, since the previous validation moments earlier:
- **CCR-016: RESOLVED** — `_wait_full_duration()` now explicitly branches on `control["action"] == "continue"` then `control["action"] == "stop"`, with a final `else` that logs a warning and defensively treats any unrecognised state as stop, replacing the prior implicit by-elimination inference.
- **CCR-017: RESOLVED** — the `# Wait 1 min`/`# Start typing and Wait 1 min` comments have been replaced with settings-derived phrasing (`# Silent wait before this cycle's typing indicator starts`; `# Start typing and hold it for DRAFT_TYPING_LEAD_SECONDS, immediately before the notice`) that no longer hardcodes a default duration.
- **CCR-018: RESOLVED** — `_stop_draft_loop()`, `continue_draft_timer()`, and `_consume_continue()` now all mutate `control["action"]`/`control["event"]` inside `with _lock:`, and the module's own header Notes explicitly document this convention by name, referencing all three functions.

**Provenance:** none of these three fixes were made by me / not part of any edit in this session — validating current disk state only, consistent with the provenance caveat already applied to CCR-003/004/008/012–015 above.

**Tenth Follow-up Review (2026-09-12, on request, "reverify telegram_gateway for non-compliance and weakness. I have added change to new session_reset behaviour"):** Scoped to a substantial redesign of the `session_reset` feature recorded in `CODE_TODO.md`'s "BUG — `SESSION_RESET_ALLOWED_CHAT_IDS` implements self-service per-chat reset, not admin-triggered global reset" entry — a whitelisted in-chat admin command ("`${BOT_NAME} refresh yourself`") now mints a real `task_id`, pushes a new `session_clear_request` event, and an inbound `session_reset` (now carrying only an optional `task_id`, no `session_id`) triggers a broad, per-chat sweep (`get_all_session_chat_ids()`) that independently defers-or-applies a reset for every chat the gateway currently holds a session for, plus a new `bot_started` orchestrator-restart reconciliation path. `utils_session/session_reset_handler.py`, `utils_telegram/gateway_inbound.py` (`_is_reset_command()`/`_handle_reset_command()`), `utils_queue/message_handler.py` (`_handle_session_reset()`/`_handle_bot_started()`), `utils_redis/database.py` (`get_all_session_chat_ids()`, `set_pending_reset()`/`get_pending_reset()`/`clear_pending_reset()`/`get_all_pending_resets()`, `reset_session()`), `utilities/initialise.py`, and `config.py` were all re-read directly against current source, cross-referenced end-to-end against `CODE_TODO.md`'s own multi-part design record and against `README.md`'s own documented `session_reset`/`pending_reset` contract (§"`session_reset`", the `pending_reset:<chat_id>` key table) — not assumed correct from the checklist's own "Implemented"/"[x]" status markers. The broad-sweep mechanism itself, the admin-command detection/whitelist gate, the `session_clear_request`/`session_reset`/`bot_started` payload shapes, and the two post-implementation hardening fixes already recorded in `CODE_TODO.md` were all confirmed correctly and consistently implemented against that design record. One genuine, previously-unflagged functional regression was identified, directly contradicting `README.md`'s own documented contract for this exact feature ("applied automatically the moment that chat's last open task naturally completes") — recorded below as **CCR-023** (Medium). One narrower, configuration-dependent robustness gap in the new admin-command matching was also identified — recorded as **CCR-024** (Low). No fixes were applied this pass (review-only; not instructed to enter Fix Mode).

**Total Findings (cumulative, revised):** 26 (2 High, 10 Medium, 9 Low, 5 Informational) — 24 numbered findings (CCR-001–CCR-024) plus 2 unnumbered informational notes. Of these, CCR-023 and CCR-024 were newly identified and Open as of this pass; both are confirmed RESOLVED as of the eleventh (validation-only) pass immediately below.

**Eleventh Pass — Validation Only (2026-09-12, same day, on request, "verify changes on CCR-023 and CCR-024 and update non-compliance audit"):** Both findings were re-checked directly against current source, not accepted on the strength of a prior claim of closure.
- **CCR-024: confirmed RESOLVED.** `gateway_inbound.py::_is_reset_command()`'s `normalised_command` now goes through the identical `" ".join(...split()).lower()` normalisation as `normalised_text`.
- **CCR-023: confirmed RESOLVED**, via a fixed sentinel rather than either option this finding's own Recommended Remediation suggested. `session_reset_handler.py` now defines `SYSTEM_TRIGGERED_TASK_ID = "system_triggered"`, passed by `handle_session_reset_request()`'s broad-sweep loop for every chat that isn't the one that actually triggered the reset — in place of the bare `None` this finding identified as the root cause. A stored `pending_reset:<chat_id>` record's `task_id` field is therefore never actually `None` in practice, restoring `get_pending_reset()`'s `None` return to an unambiguous meaning, with no change to `database.py`'s storage format or exposed signatures.
- **One follow-on documentation gap found and corrected in this session** (at the user's explicit "clean up documentation" instruction in the prior turn): `database.py::get_all_pending_resets()`'s own docstring still claimed `task_id` "is `None`" for a non-triggering chat, contradicting `set_pending_reset()`'s already-updated docstring describing the same stored value. Corrected to reference the `SYSTEM_TRIGGERED_TASK_ID` sentinel instead, closing the last inconsistency between the two docstrings. `get_pending_reset()`'s own docstring additionally now discloses, candidly, that its implementation still cannot distinguish "absent" from "present with a literal `None`" if some future caller ever stored one — a residual, disclosed scope note rather than a live defect, since no current caller does.
- No fixes were applied to production logic by this review itself — the core CCR-023/CCR-024 fixes were authored outside this session; only the one documentation correction above was made in this session, per the user's own instruction to do so (see Fix Mode Traceability below).

**Compliance Verdict: Mostly Compliant** (restored — both new findings from the tenth follow-up pass, CCR-023 and CCR-024, are confirmed RESOLVED by this eleventh pass; see updated rationale at the end of this document)

---

## Findings

### ~~CCR-001~~ — RESOLVED

**Severity:** High

**Location:**
- `utilities/utils_telegram/gateway_outbound.py` — every `send_*`/`stop_poll` function's `except requests.exceptions.RequestException` and connection-exhaustion branches (e.g. lines 128–140, 173–182, 242–254, 299–308, 356–368, 413–425, 470–482, 525–537)
- `utilities/utils_telegram/gateway_inbound.py::_resolve_file_url` (lines 168–177) and `poll_updates()` (lines 488–493)

**Violated Standard:**
- CWE-532: Insertion of Sensitive Information into Log File
- CWE-522: Insufficiently Protected Credentials
- OWASP A09:2021 — Security Logging and Monitoring Failures / A02:2021 — Cryptographic Failures (secrets handling)

**Description:**
Every Telegram Bot API call embeds `settings.TELEGRAM_BOT_TOKEN` directly in the request URL (`f".../bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"`), which is required by the Telegram Bot API design. However, on failure these functions call `logger.exception(...)`, which logs the full exception, including its `str()` representation. `requests`/`urllib3` exceptions (`ConnectionError`, `Timeout`, `HTTPError`, `MaxRetryError`) routinely embed the full request URL — including the bot token — in their message text (e.g. `HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries exceeded with url: /bot<TOKEN>/sendMessage ...`). This means the bot token can be written verbatim into the application's rotating log files (retained up to `LOG_RETENTION_DAYS`, default 30 days) any time a send fails or is rejected.

**Evidence:**
```python
except requests.exceptions.RequestException as exc:
    ...
    logger.exception("Failed to send message to Telegram. Not retrying.")
```
`logger.exception()` implicitly sets `exc_info=True`, so the traceback (including the token-bearing URL embedded in the underlying exception message) is written to disk.

**Impact:**
A leaked bot token grants an attacker full control of the Telegram bot (send/receive messages, read chat history via `getUpdates`, impersonate the bot to all authorised users). Log files are frequently subject to broader read access, shipped to log aggregation/monitoring platforms, or retained beyond the lifetime of the credential itself — significantly widening the exposure surface beyond the original `.env`/secret store.

**Recommended Remediation:**
Avoid passing raw exception objects containing the token-bearing URL to the logger. Options include: constructing a token-redacted URL for logging purposes; catching and re-raising exceptions with a sanitised message; or wrapping `requests` calls so the URL is never rendered with the real token in any log sink. Apply consistently across `gateway_outbound.py` and `gateway_inbound.py`.

**Confidence:** High

**Resolution Status:** RESOLVED (2026-09-03)

**Validation Result:**
- Added `log_sanitised_exception()` to `utilities/utils_telegram/gateway_outbound.py` — captures `traceback.format_exc()`, redacts every occurrence of `settings.TELEGRAM_BOT_TOKEN` with `***REDACTED***`, and logs at `ERROR` level in place of `logger.exception()`.
- Replaced all 20 `logger.exception(...)` call sites in `gateway_outbound.py` (across `send_message`, `send_typing_action`, `send_poll`, `stop_poll`, `send_document`, `send_photo`, `send_video`, `send_media_group`) with `log_sanitised_exception(...)`.
- Imported and applied the same helper in `utilities/utils_telegram/gateway_inbound.py` for `_resolve_file_url()` (2 sites) and `poll_updates()` (4 sites, including the "giving up"/"unexpected error" branches and the long-polling request-failure branches) — every location that could raise a `requests`/`urllib3` exception against a token-bearing Telegram API URL.
- Verified via `grep` that no `logger.exception(...)` calls referencing a Telegram API request remain in either file (only the helper's own docstring text matches the search pattern).
- Confidence in fix completeness: High — confirmed via direct source re-inspection, not just pattern matching.

---

### ~~CCR-002~~ — RESOLVED

**Severity:** Medium

**Location:** `utilities/utils_telegram/gateway_inbound.py::poll_updates` (lines 455, 458, 467, 469, 481, 485)

**Violated Standard:**
- CWE-532: Insertion of Sensitive Information into Log File
- Governance: Data minimisation / auditability (general secure-logging best practice — no single named rule for this aspect)

**Description:**
The raw Telegram `update` object is logged in full at INFO/WARNING/DEBUG level in multiple places, e.g. `logger.info(f"Received Telegram update: {update}")`. A Telegram `Update` can contain personal data: sender first/last name, username, free-text message content, and (for `contact` messages) phone numbers. This is written unredacted to disk logs retained for up to 30 days by default.

**Evidence:**
```python
logger.info(f"Received Telegram update: {update}")
...
logger.warning(f"First unauthorised access from chat_id={chat_id}: {update}")
```

**Impact:**
Sensitive/personal user data persisted in plaintext logs increases the blast radius of any log exposure (e.g. misconfigured log shipping, broad file permissions) and may create regulatory data-handling exposure depending on jurisdiction/data classification.

**Recommended Remediation:**
Log only the fields needed for troubleshooting (e.g. `update_id`, `chat_id`, event type) rather than the entire update payload. If full-payload logging is needed for debugging, gate it behind a dedicated debug flag with tighter retention/permissions.

**Confidence:** High

**Resolution Status:** RESOLVED (2026-09-03)

**Validation Result:**
- Added `_summarise_update(update: dict) -> dict` to `gateway_inbound.py`, returning only `{"update_id", "event_type"}` — no message text, sender name/username, or contact details.
- Replaced the raw `{update}` interpolation with `{_summarise_update(update)}` at all 5 log sites: the missing-chat_id/user_id warning, the first-unauthorised-access warning, the ignored-unauthorised-chat debug log, the "Received Telegram update" info log, and the "giving up on update_id" exception log (the last of which was also folded into the CCR-001 fix).
- Verified via `grep` that no log statement in `gateway_inbound.py` interpolates the raw `update` dict any longer.
- `chat_id`/`update_id` (bare integers, not personal data) are still logged where useful for troubleshooting/correlation.

---

### ~~CCR-003~~ — RESOLVED (validated, not authored this session)

**Severity:** Medium

**Location:** `config.py`, lines 146–147 (`DEFAULT_Q_USER`, `DEFAULT_Q_PASSWORD`)

**Violated Standard:**
- CWE-798: Use of Hard-coded Credentials
- OWASP A07:2021 — Identification and Authentication Failures

**Description:**
```python
DEFAULT_Q_USER     = "chatbotAdmin"
DEFAULT_Q_PASSWORD = "chatbotAdmin"
```
These are used as the fallback RabbitMQ credentials whenever `Q_USER`/`Q_PASSWORD` environment variables are unset. Unlike `TELEGRAM_BOT_TOKEN` (whose placeholder `"REPLACE_WITH_BOT_TOKEN"` is deliberately non-functional and commented as such), the RabbitMQ default is a **working, weak, identical username/password pair** that will silently authenticate if the operator forgets to override it in a given environment.

**Impact:**
If deployed without setting `Q_USER`/`Q_PASSWORD`, the message broker is protected only by a well-known, guessable default credential — a common root cause of lateral-movement compromise in containerised deployments.

**Recommended Remediation:**
Either remove the functional default (fail fast / raise at startup if unset in a non-development environment) or clearly flag it as a development-only placeholder the way `TELEGRAM_BOT_TOKEN` is, and document that it must be overridden before production use.

**Confidence:** High

**Severity Reassessment (Deployment Context Accepted, 2026-09-03):**
The user has stated the intended deployment context: RabbitMQ is never exposed outside the host and this component runs in a closed, automated environment. This claim was validated against repository evidence rather than accepted at face value:

- **Confirmed:** `compose.dev.yml` defines the `rabbitmq` service with its `ports:` mapping (`40000:5672`, `40002:15672`) commented out, and it is reachable only via the internal `chatbot-app-network` Docker bridge network — no host/external binding exists in the checked-in compose definition. This is consistent with the stated intent for the dev environment.
- **Not verifiable from the repository:** no `compose.prod.yml` (or equivalent) exists in this codebase to confirm the same isolation holds for production; the actual `.env` file is not checked in, so I cannot confirm what `CHATBOT_RABBITMQ_USERNAME`/`CHATBOT_RABBITMQ_PASSWORD` are set to at runtime. This remains a stated assumption, not an independently confirmed fact for all environments.
- **Related observation (informational, not a new CCR):** `compose.dev.yml` does not pass `Q_USER`/`Q_PASSWORD` as environment variables to the `telegram-gateway` service at all (only `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_CHAT_IDS` are wired in). As shipped, the gateway will therefore always fall back to the hard-coded `"chatbotAdmin"/"chatbotAdmin"` default at runtime unless `Q_USER`/`Q_PASSWORD` are supplied through some other mechanism outside this repo. Worth confirming operationally — if `CHATBOT_RABBITMQ_USERNAME`/`PASSWORD` (which are forced non-functional placeholders in `config_sample.ini`) are ever set to anything other than `"chatbotAdmin"/"chatbotAdmin"`, the gateway will fail to authenticate to the broker.

**Effect on classification:**
- The underlying **rule violation is unchanged** — CWE-798 concerns the presence of a hard-coded, working credential in source, which is a static-code fact independent of network topology. This finding remains valid and is **not withdrawn**.
- The **severity is revised from Medium to Low**, given that the primary threat vector this rating was driven by (an external/remote attacker reaching an exposed broker and authenticating with a guessable default — OWASP A07) is not realistic under the confirmed network configuration.
- **Residual risk retained even in a closed environment**, and why this is not reduced to zero/informational:
  1. **Defence-in-depth**: the control preventing exploitation (network isolation) is enforced entirely outside this codebase, in the compose/deployment layer. A future, purely operational change (e.g. temporarily uncommenting the RabbitMQ ports for debugging, adding a reverse proxy, or joining the network to a shared segment) would silently reactivate the risk with no code change and no warning from the application itself.
  2. **Lateral movement**: within `chatbot-app-network`, any other container or process reachable on that network (including a hypothetically compromised sibling service) inherits full broker access via a well-known, guessable, identical username/password — this is a different threat actor to the "external attacker" the Medium rating was originally scoped against, and closed-host intent does not mitigate it.
  3. **Inconsistent with the project's own established pattern**: the broker's actual credentials (`CHATBOT_RABBITMQ_USERNAME`/`PASSWORD`) are deliberately shipped as non-functional `"REPLACE_WITH_..."` placeholders elsewhere in this repo (`config_sample.ini`) specifically to force an operator override — `DEFAULT_Q_USER`/`DEFAULT_Q_PASSWORD` breaks that same pattern by being silently functional.

**Revised Status:** ~~Open — Accepted Risk (Low)~~ **RESOLVED (validated 2026-09-03)** — superseded by a further re-verification the same day; see below.

**Re-verification (2026-09-03, on request):** Re-read `config.py` directly (not from cached report text) to confirm current source state. `DEFAULT_Q_USER`/`DEFAULT_Q_PASSWORD` are **no longer** `"chatbotAdmin"`/`"chatbotAdmin"` — they are now `""` (empty string) at lines 146–147. `self.Q_USER`/`self.Q_PASSWORD` resolve to `os.getenv(...) or ""`, so if unset, `pika.PlainCredentials("", "")` is passed, which RabbitMQ will reject (no default vhost/user matches blank credentials), causing the connection to fail closed rather than silently authenticating with a guessable working credential — this is precisely the fail-fast behaviour originally recommended.

**Important provenance note:** This change was **not** made by me and was **not** part of this session's Fix Mode pass (CCR-003 was explicitly excluded from that pass at your instruction, and no edit to these lines was made under this session). The current source already differs from what was read/quoted at the time the original finding and the prior severity-reassessment note were written — the fix appears to have been applied directly/externally between messages. I am validating what is on disk now, not claiming credit for authorship.

**Classification:** The underlying CWE-798 concern (a functional, guessable, working default credential embedded in source) is **no longer present** in the current code — an empty-string default is a fail-closed, non-functional placeholder, not a hard-coded credential. Finding is validated as resolved.

**Confidence:** High — verified directly against the current file contents, not inferred.

---

### CCR-004

**Severity:** ~~Medium~~ **Downgraded — see re-verification**

**Location:** `utilities/utils_redis/database.py::initialise_redis_connection` (originally lines 54–59; now lines 54–65); `config.py` (Redis Connection section, originally lines 172–184; now lines 172–196)

**Violated Standard:**
- ~~CWE-306: Missing Authentication for Critical Function~~ — **closed, see below**
- CWE-319: Cleartext Transmission of Sensitive Information — **remains open**

**Description (as originally written — see re-verification note for current accuracy):**
The Redis client is constructed with only `host`, `port`, and `db` — there is no `password`/`username` parameter, and no corresponding `REDIS_PASSWORD` setting exists in `config.py` at all (unlike the RabbitMQ connection, which does support credentials). TLS (`ssl=True`) is likewise not configurable. Redis stores chat_id/user_id task mappings, pending drafts (including bot-token-bearing file URLs), and poll state — all of which are unauthenticated-and-unencrypted-in-transit by design of this code, regardless of how the underlying Redis server is configured.

**Impact:**
Even if the Redis instance itself supports `requirepass`/TLS, this application cannot use it. If Redis is reachable from a broader network segment than intended, task/session state (including bot-token-bearing draft media URLs — see CCR-006) is exposed with no authentication and no encryption.

**Recommended Remediation:**
Add `REDIS_PASSWORD` (and optionally `REDIS_USERNAME`, `REDIS_SSL`) settings, threading them through to `redis.Redis(...)`, for parity with the RabbitMQ connection's credential support.

**Confidence:** High (code-level gap is unambiguous); actual exploitability depends on network topology, which is outside this review's visibility (assumption stated).

**Re-verification (2026-09-03, on request):** Re-read `config.py` and `database.py` directly against current source (not cached report text). Current state differs materially from the description above:
- `config.py` now defines `REDIS_USERNAME`/`REDIS_PASSWORD` settings (lines 175–176, 187–188), defaulting to `""` if unset.
- `database.py::initialise_redis_connection` now passes `username=settings.REDIS_USERNAME, password=settings.REDIS_PASSWORD` into `redis.Redis(...)` (lines 58–59).
- **This closes the CWE-306 ("missing authentication capability") component** — the application can now authenticate to Redis if `REDIS_USERNAME`/`REDIS_PASSWORD` are set, achieving parity with the RabbitMQ connection as originally recommended.
- **This does not close the CWE-319 (cleartext transmission) component** — no `ssl=`/TLS parameter has been added to the `redis.Redis(...)` call. This half of the finding remains fully open and is functionally identical to CCR-005 (which already tracks the same gap for both Redis and RabbitMQ) — retained here for traceability but not duplicated as a separate blocker.
- **Provenance:** not made by me / not part of this session's Fix Mode pass (CCR-004 was explicitly excluded at your instruction). Validating current disk state only.
- **Operational note:** even with the code capability now present, `compose.dev.yml`'s `redis` service does not configure `requirepass`, and no `REDIS_USERNAME`/`REDIS_PASSWORD` env vars are wired into the `telegram-gateway` service — so in the current dev deployment, authentication remains unset/unused in practice (both sides default to no-auth, which is at least *consistent*, unlike the earlier Q_USER/Q_PASSWORD wiring gap noted under CCR-003). This is a deployment-configuration decision, not a code defect, and is consistent with the same closed-host network intent already validated for CCR-003/CCR-005.

**Revised Severity:** Medium → **Low** (authentication capability gap closed; only the TLS/cleartext-transmission component remains, which is already tracked at Low severity under CCR-005 for the same underlying reason — network trust boundary dependent).

**Revised Status:** **PARTIALLY RESOLVED** (CWE-306 closed; CWE-319 component merged into / tracked under CCR-005).

---

### CCR-005

**Severity:** Low

**Location:** `utilities/utils_queue/queue.py::_build_rabbitmq_parameters` (lines 60–68); `utilities/utils_redis/database.py::initialise_redis_connection`

**Violated Standard:**
- CWE-319: Cleartext Transmission of Sensitive Information

**Description:**
Neither the RabbitMQ (`pika.ConnectionParameters`) nor Redis connection configures TLS. `Q_PASSWORD` and all task/session payloads (including bot-token-bearing URLs, per CCR-006) traverse the network in cleartext.

**Impact:**
On a Docker bridge/overlay network isolated from untrusted hosts, this is commonly an accepted risk. If the network boundary is broader than a single trusted host/VPC, credentials and message payloads are sniffable.

**Recommended Remediation:**
Where the deployment network is not fully trusted, add TLS support (`ssl_options` for pika, `ssl=True` for redis-py) as a configurable option.

**Confidence:** Medium — severity is genuinely deployment-context-dependent; flagged as a recommendation rather than a confirmed violation, since the trust boundary of the Docker network is not visible from source alone (assumption stated).

**Re-verification (2026-09-03, on request):** Re-read `queue.py::_build_rabbitmq_parameters` and `database.py::initialise_redis_connection` directly against current source. **Unchanged and still fully open** — neither `pika.ConnectionParameters(...)` nor `redis.Redis(...)` configures any TLS/`ssl_options`/`ssl=` parameter, despite the Redis call otherwise being materially hardened since the original review (see CCR-004, CCR-008). Combined with the deployment-context evidence already validated under CCR-003 (RabbitMQ/Redis have no host-exposed ports in `compose.dev.yml`, reachable only via the internal `chatbot-app-network`), the same mitigating reasoning applies here: an external/host-network attacker cannot intercept this traffic under the current compose definition, which supports treating this as a **Low severity, accepted risk within a closed-network deployment** rather than a blocker — consistent with the "commonly an accepted risk" language already in this finding's Impact statement above. This finding's rating and status are **unchanged** (Low, open) — no code change was made or requested.

**Status:** Open (skipped, unchanged) — severity rating already reflected the network-trust caveat prior to this re-verification; re-verification confirms no regression and no fix applied.

---

### ~~CCR-006~~ — MITIGATED (RESIDUAL RISK ACCEPTED)

**Severity:** Medium

**Location:** `utilities/utils_telegram/gateway_inbound.py::_resolve_file_url` (lines 139–177) and `_push_task`/`_handle_update` (media draft finalisation, lines 234–284, 400–401)

**Violated Standard:**
- CWE-522: Insufficiently Protected Credentials (closest applicable mapping — no single CWE rule cleanly covers "capability URL propagated beyond originating trust boundary", so this is the nearest fit)

**Description:**
`_resolve_file_url()` resolves a Telegram `file_id` to a URL of the form `https://api.telegram.org/file/bot<TOKEN>/<path>`. This URL — which embeds the live bot token and is valid for roughly an hour — is then stored in Redis (`create_chat_draft`) and ultimately placed into the RabbitMQ task payload (`image_url`/`video_url`/`file_url`) consumed by the downstream backend/orchestrator (per `_push_task`). The module's own docstring correctly warns "do not log it," but the design still forwards the token-bearing URL to two additional systems (Redis, RabbitMQ, and transitively the backend) outside the gateway's own trust boundary.

**Impact:**
Any system or log sink downstream of the gateway (backend orchestrator, RabbitMQ message inspection tooling, Redis) that has visibility of this URL effectively gains a working Telegram bot token for up to an hour, not just read access to that one file — because Telegram bot-token URLs are not scoped to a single resource.

**Recommended Remediation:**
This is largely inherent to the Telegram Bot API (no scoped, token-less file URL exists). Where feasible, consider having the gateway fetch/proxy the media itself and hand the backend a gateway-issued, scoped URL instead of Telegram's raw token-bearing one — eliminating token propagation beyond this service. If proxying is not feasible, this should be a documented, accepted architectural risk.

**Confidence:** Medium — this is an architectural/design observation rather than a coding defect; flagged for governance awareness rather than as a definite mandatory-fix bug.

**Resolution Status:** MITIGATED — residual risk accepted (2026-09-03)

**Validation Result:**
- Confirmed via `grep` across the full application source that `media_url`/`image_url`/`video_url`/`file_url` values are **never** passed to a logging call anywhere in the codebase — the docstring instruction "do not log it" is honoured in practice, not just in comment form. This closes the log-leakage angle of this finding, and is additionally reinforced by the CCR-001/CCR-002 logging hardening above.
- **Not fully resolved at the code level**: the token-bearing URL is still, by design, written to Redis (`create_chat_draft`) and forwarded to the backend via the RabbitMQ task payload (`_push_task`). Eliminating this would require the gateway to download and re-host media itself (a new proxy/storage feature — new infrastructure, a public-facing endpoint, and a cleanup lifecycle), which is a substantial architectural change beyond the scope of a targeted compliance fix and was not undertaken without explicit instruction to build it.
- **Recorded as an accepted residual risk**: the token-bearing URL's ~1 hour validity window and its confinement to the already-authenticated RabbitMQ/Redis/backend chain (see CCR-004/CCR-005, deliberately left unaddressed per user instruction) bound the exposure. Should the trust boundary of those systems change, this finding should be re-opened.

---

### ~~CCR-007~~ — RESOLVED

**Severity:** Low

**Location:** `main.py`, lines 25–30 (module level, outside `main()`)

**Violated Standard:**
- General secure-scripting/maintainability best practice: avoid side effects on import (closest formal reference: PEP 8 guidance on module organisation; no specific CWE applies)

**Description:**
`settings.DATA_DIR.mkdir(...)` and `setup_logging()` execute at module import time, not inside `main()` or a guarded entry point. Any code that imports `telegram_gateway_application.main` (e.g. for testing, tooling, or reuse) will create directories and reconfigure the root logger as an import side effect.

**Evidence:**
```python
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
setup_logging()
logger = logging.getLogger(__name__)
_shutdown_event = ShutdownSignal()
```

**Impact:**
Reduces testability and predictability; importing the module for any reason (e.g. unit tests importing a sibling symbol) mutates filesystem state and global logging configuration.

**Recommended Remediation:**
Move directory creation and `setup_logging()` calls inside `main()` (or an explicit `bootstrap()` function called only from the `if __name__ == "__main__":` guard).

**Confidence:** Medium

**Resolution Status:** RESOLVED (2026-09-03)

**Validation Result:**
- `main.py` restructured: `settings.DATA_DIR.mkdir(...)`, `setup_logging()`, `logger` creation, and `ShutdownSignal()` instantiation all moved inside `main()`, removing every module-level side effect. Only function/class definitions and the `if __name__ == "__main__": main()` guard now execute on import.
- Behaviour when run as the application entry point (`python -m telegram_gateway_application.main` / the existing Docker entry point) is unchanged — `main()` performs setup, signal registration, initialisation, blocking wait, then termination in the same order as before.
- Confirmed no other module imports symbols (e.g. a shared `logger`) that depended on `main.py`'s former module-level setup.

---

### ~~CCR-008~~ — RESOLVED (validated, not authored this session)

**Severity:** Low

**Location:** `utilities/utils_redis/database.py::initialise_redis_connection` (originally lines 54–59; now lines 54–65)

**Violated Standard:**
- CWE-400: Uncontrolled Resource Consumption (closest applicable mapping)

**Description (as originally written — see re-verification note for current accuracy):**
`redis.Redis(...)` is constructed without `socket_connect_timeout` or `socket_timeout`. redis-py's defaults leave these as `None` (no timeout), so a network-level stall (not a clean connection refusal) could cause Redis operations to block indefinitely rather than failing fast into the existing retry logic.

**Impact:**
A silent network hang on Redis could stall the RabbitMQ consumer thread or the Telegram polling thread indefinitely (since several call paths, e.g. `create_task_mapping`, are on the hot path), rather than surfacing as a bounded, retried failure the way Telegram API calls are handled (which do set `timeout=`).

**Recommended Remediation:**
Set explicit `socket_connect_timeout`/`socket_timeout` values on the Redis client, consistent with the timeout discipline already applied to `requests` calls elsewhere in the codebase.

**Confidence:** Medium

**Re-verification (2026-09-03, on request):** Re-read `config.py` and `database.py` directly against current source. `config.py` now defines `REDIS_SOCKET_CONNECT_TIMEOUT` (default 5s) and `REDIS_SOCKET_TIMEOUT` (default 5s) (lines 178–179, 190–191), and `database.py::initialise_redis_connection` now passes `socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT, socket_timeout=settings.REDIS_SOCKET_TIMEOUT` into `redis.Redis(...)` (lines 60–61) — exactly the remediation originally recommended. As a bonus, `socket_keepalive` and `health_check_interval` were also added, which is beyond what this finding asked for but is good additional hardening in the same spirit.

**Provenance:** not made by me / not part of this session's Fix Mode pass (CCR-008 was explicitly excluded at your instruction). Validating current disk state only.

**Confidence (re-verification):** High — verified directly against current file contents.

---

### ~~CCR-009~~ — RESOLVED

**Severity:** Low

**Location:** `utilities/logging.py` (whole file, filename itself)

**Violated Standard:**
- PEP 8 — Naming Conventions (module naming; general guidance against shadowing standard-library module names)

**Description:**
The module is named `logging.py` and imports the standard library `logging` module (`import logging`) from within itself. Python 3's absolute-import default means this resolves correctly at runtime, but the naming choice is a readability/maintainability hazard (easy to misread `import logging` as a self-import, and any accidental relative-import tooling/config could break it).

**Impact:**
No functional defect under current Python 3 absolute-import semantics; purely a maintainability/clarity concern.

**Recommended Remediation:**
Consider renaming to `logging_setup.py` or `log_config.py` to avoid shadowing the standard library name.

**Confidence:** High (naming fact); Low functional risk.

**Resolution Status:** RESOLVED (2026-09-03)

**Validation Result:**
- Created `utilities/logging_setup.py` containing the full original implementation of `setup_logging()`, no longer shadowing the standard library's `logging` module.
- Updated `main.py`'s import from `from .utilities.logging import setup_logging` to `from .utilities.logging_setup import setup_logging`.
- Updated `telegram_gateway/README.md`'s project-structure listing from `utilities/logging.py` to `utilities/logging_setup.py`.
- Confirmed via `grep` that `main.py` was the only importer of the old module path in the repository.
- **Tooling limitation noted:** this environment has no file-deletion capability. `utilities/logging.py` could not be removed outright; it has instead been replaced with a thin backward-compatible re-export (`from .logging_setup import setup_logging`) and a docstring flagging it as superseded, so no functional breakage occurs even if something else still references the old path. **A maintainer should delete `utilities/logging.py` manually** once confirmed unused, to fully close out the original shadowing concern.

---

### ~~CCR-010~~ — RESOLVED

**Severity:** Informational

**Location:** `config.py::get_env_int` (lines 186–208)

**Violated Standard:** None formally violated — internal consistency observation.

**Description:**
On the success path, `get_env_int` clamps the parsed value to `minimum`. On the `except ValueError` path (invalid, non-numeric env var), it returns `default` unclamped. Since all current call sites pass sane, already-valid defaults, this has no observable effect today, but it is an inconsistency that could produce a sub-minimum value if a future default were ever set below the intended floor.

**Recommended Remediation:** Apply `max(minimum, default)` in the exception path too, for consistency.

**Confidence:** High

**Resolution Status:** RESOLVED (2026-09-03)

**Validation Result:**
- `config.py::get_env_int` exception path changed from `return default` to `return max(minimum, default)`, matching the clamping behaviour of the success path.
- No caller-observable behavioural change under current settings, since every existing default already satisfies its own minimum — confirmed by re-inspection of all `get_env_int(...)` call sites in `config.py`.

---

### CCR-011

**Severity:** Low

**Location:** `utilities/utils_telegram/utilities/button_prompt_handler.py::_registered_callbacks` (line 39); pruning only via `_prune_expired_callbacks()` triggered opportunistically from `register_bot_button`/`validate_bot_callback`.

**Violated Standard:**
- CWE-400: Uncontrolled Resource Consumption

**Description:**
`_registered_callbacks` is an unbounded in-memory dict, pruned only lazily (by age, on the next register/validate call) rather than capped by size. Under sustained high message volume with a long `TELEGRAM_CALLBACK_TTL_SECONDS` (default 3600s), memory usage scales with button-issue rate over that window with no hard ceiling, unlike `gatekeeper.py`'s `_access_counts`, which is explicitly size-capped (`TELEGRAM_UNAUTHORISED_CACHE_SIZE`).

**Impact:**
Low under expected/typical bot traffic volumes; a theoretical DoS/memory-growth vector under abnormally high sustained button-issuing load.

**Recommended Remediation:**
Consider an optional maximum-size bound (mirroring the pattern already used in `gatekeeper.py`) as defence-in-depth.

**Confidence:** Medium

---

### ~~CCR-012~~ — RESOLVED

**Severity:** Medium

**Review Date:** 2026-09-04 (follow-up pass — `user_id`-removal / `session_id` change)

**Location:**
- `utilities/utils_redis/database.py::reset_session()` (lines 627–658)
- Cross-referenced against `utilities/utils_telegram/utilities/image_draft_handler.py` (no import/interaction with `reset_session`) and `utilities/utils_telegram/utilities/poll_response_handler.py::_finalise_poll()`/`_push_poll_answer()`

**Violated Standard:**
- CWE-459: Incomplete Cleanup
- Closest secondary mapping: CWE-664 (Improper Control of a Resource Through its Lifetime)

**Description:**
`reset_session(chat_id)` is documented (both in its own docstring and in `README.md`'s Design Decisions/`session_reset` sections) as the mechanism that "wipes a chat's permanent `session_id` and every `task_id` still open under it," on the stated rationale that "the backend has already unwound whatever state it held for it." In practice it only deletes three key families: `task:<task_id>` (via the `session_tasks:<chat_id>` index), `session_tasks:<chat_id>`, and `session:<chat_id>`. It does **not** touch `draft:<chat_id>` or any `poll:<poll_id>` belonging to that chat, and it has no visibility of (or interaction with) the in-memory draft keep-alive loop (`image_draft_handler.py::_active_drafts`) or the in-memory poll debounce loop (`poll_response_handler.py::_active_polls`) — both of which key off `chat_id`/`poll_id`, not `task_id`, so they fall entirely outside what `reset_session()` enumerates.

Consequences, both confirmed by direct code trace:
1. **Stale draft survives a reset.** If a photo/video/document draft is pending when `session_reset` fires, `draft:<chat_id>` and its in-memory keep-alive thread are untouched. The very next text message the user sends is still finalised against that pre-reset draft (`gateway_inbound.py::_handle_update()`, lines 428–440), attaching pre-reset media (including a Telegram-token-bearing URL, per the already-accepted CCR-006 risk) to a task pushed under a **freshly created, post-reset** `session_id` — silently carrying forward exactly the state the reset was meant to discard.
2. **Open poll silently loses its answer.** A poll still awaiting/debouncing an answer at reset time keeps running to completion, but when it closes, `_finalise_poll()` calls `_push_poll_answer(task_id, option_ids)`, which resolves `session_id` via `generate_session(task_id=task_id)`. Since the poll's original `task:<task_id>` mapping was deleted by the reset, `get_task_mapping()` returns `None`, `generate_session()` logs `"Failed to resolve session_id for task_id=... - no task mapping found"`, and the answer is dropped (`poll_response_handler.py::_push_poll_answer`, lines 66–69) with no user-facing notice that this happened.

**Evidence:**
```python
# database.py::reset_session — only these three key families are touched
for task_id in task_ids:
    redis_delete(f"task:{task_id}")
redis_delete(f"session_tasks:{chat_id}")
redis_delete(f"session:{chat_id}")
# no delete_chat_draft(chat_id), no poll cleanup, no stop_draft_timer()/poll-loop signal
```

**Impact:**
Undermines the stated security/privacy invariant that a `session_reset` yields a clean slate — pre-reset conversational content (potentially including a still-valid, token-bearing media URL) can be attached to a task carrying a brand-new `session_id`, defeating the consumer's ability to rely on `session_id` boundaries to categorise session chat as intended by this change. Separately, a poll answer can be silently and permanently lost with no operator-visible signal beyond a single log line.

**Recommended Remediation:**
Extend `reset_session()` (or have `_handle_session_reset()` orchestrate it) to also: delete `draft:<chat_id>` and signal `image_draft_handler.py::stop_draft_timer(chat_id)`; and enumerate/close any `poll:<poll_id>` mapped to `chat_id` (would require either indexing polls by `chat_id`, similar to `session_tasks:<chat_id>`, or accepting the current design and documenting the gap explicitly as an accepted limitation).

**Confidence:** High — verified directly by tracing every code path that reads/writes `draft:<chat_id>` and `poll:<poll_id>`, and confirming none is referenced by `reset_session()`.

**Resolution Status:** RESOLVED (validated 2026-09-05, not authored this session)

**Validation Result:**
- `utils_redis/database.py::reset_session()` now additionally calls `delete_chat_draft(chat_id)` and `redis_delete(f"session_polls:{chat_id}")` as part of the same reset — the two gaps this finding described (stale draft, silently-lost poll answer) are both closed at the Redis-state level.
- A new `utils_session/session_reset_handler.py` module (built specifically against `TODO.md`, "Also to fold back in regardless of direction chosen") restores the in-memory side this finding also flagged as out of `reset_session()`'s visibility: `_apply_session_reset()` calls `stop_draft_timer(chat_id)` before `reset_session()`, and `_force_apply_session_reset()` (the §8 force-through backstop) calls `poll_response_handler.py::stop_poll_for_reset()` for every poll still indexed under `session_polls:<chat_id>` before applying.
- Confirmed the poll-answer-loss scenario this finding traced (`_push_poll_answer()` failing to resolve `session_id` because `task:<task_id>` was already deleted by a reset) can no longer arise under the new design: an open poll always has an open `task_id` (unchanged invariant), and a `session_reset` for a chat with any open `task_id` is now **deferred** (`handle_session_reset_request()`) rather than applied immediately — a poll is either genuinely still open (task open, reset still deferred, poll finalises and pushes its answer/`poll_timed_out` normally) or already closed out defensively by `stop_poll_for_reset()` on the one path (§8 force-through) where a reset could otherwise outlive it.
- New indexes (`session_polls:<chat_id>`, mirroring the existing `session_tasks:<chat_id>` pattern) were added to `create_poll_mapping()`/`delete_poll_mapping()`/`get_session_poll_ids()` specifically to give `reset_session()`/`_force_apply_session_reset()` visibility into open polls without a keyspace `SCAN` — see also **CCR-015** below, a narrower synchronisation gap introduced by this same new indexing.
- **Provenance:** this remediation was **not** made by me / not part of this session's own edits — validating current disk state only, per `TODO.md`.

**Classification:** The underlying CWE-459/CWE-664 concern (a `session_reset` not reliably yielding a clean slate for drafts/polls) is resolved for both code paths this finding identified. Finding is validated as resolved.

**Confidence:** High — verified directly against current file contents and cross-referenced against `TODO.md`'s own stated design, not inferred from the checklist alone.

---

### ~~CCR-013~~ — RESOLVED

**Severity:** Medium

**Review Date:** 2026-09-04 (follow-up pass — `user_id`-removal / `session_id` change)

**Location:**
- `utilities/utils_redis/database.py::reset_session()` (lines 627–658) vs. `create_task_mapping()` (lines 259–302) and `_get_or_create_session()`/`generate_session()` (lines 544–625)
- Triggered concurrently from two independent threads: the RabbitMQ consumer thread (`utils_queue/queue.py::queue_consume_task()` → `message_handler.py::_handle_session_reset()`) and the Telegram long-polling thread (`utils_telegram/gateway_inbound.py::poll_updates()` → `_push_task()`)

**Violated Standard:**
- CWE-362: Concurrent Execution using Shared Resource with Improper Synchronization ('Race Condition')

**Description:**
`reset_session()` performs a read-then-delete sequence (`SMEMBERS session_tasks:<chat_id>` → delete each `task:<task_id>` → delete `session_tasks:<chat_id>` → delete `session:<chat_id>`) with **no locking, Redis transaction (`MULTI`/`WATCH`), or other synchronisation** against a concurrent `create_task_mapping()` for the same `chat_id`. The two operations run on genuinely independent threads (RabbitMQ consumer vs. Telegram poller), each with unsynchronised access to the same Redis key set for a given `chat_id` — unlike `utils_queue/queue.py`, which explicitly separates its publish/consume connections with dedicated `RLock`s for exactly this class of concern.

Traced interleaving: if `create_task_mapping()`'s `redis_write(f"task:{task_id}", ..., nx=True)` (its first step) completes *before* `reset_session()`'s `SMEMBERS` read, but its second step, `sadd(f"session_tasks:{chat_id}", task_id)`, has not yet executed by the time `reset_session()` reads and then deletes `session_tasks:<chat_id>` — the new `task_id` is never enumerated by the reset's loop, so its own `task:<task_id>` key is **never deleted**, while its index entry is destroyed regardless (the whole `session_tasks:<chat_id>` key is deleted outright). The task mapping survives the reset as a live, unindexed orphan for up to `REDIS_TASK_MAPPING_TTL_SECONDS` (24h by default). When a response for that task later arrives, `generate_session(task_id=task_id)` finds no `session:<chat_id>` (deleted by the reset), logs a `CRITICAL` "should never happen" self-heal, and **silently creates a brand-new session** — delivering content the backend had already unwound its state for, under a session identifier that gives the consumer no signal this task predates the reset.

**Evidence:**
```python
# reset_session() — no lock, two independent network round-trips, no transaction
task_ids = client.smembers(f"session_tasks:{chat_id}")   # read
...
redis_delete(f"session_tasks:{chat_id}")                 # unconditional delete of the whole set

# create_task_mapping() — two separate, non-atomic Redis calls
redis_write(f"task:{task_id}", value, ttl_seconds, nx=True)   # step 1
get_redis_client().sadd(f"session_tasks:{chat_id}", task_id)  # step 2 (best-effort)
```

**Impact:**
A task created in the narrow window around a `session_reset` can escape deletion entirely, and its eventual response is delivered to the user under a newly self-healed `session_id` with no error surfaced beyond a log line — directly undermining the reliability of `session_id` as a categorisation boundary, which is the specific purpose this change assigns to it. Likelihood is timing-dependent (a genuine but narrow race window, not deterministic), which is reflected in the confidence rating below rather than the severity.

**Recommended Remediation:**
Serialise `reset_session()` against `create_task_mapping()`/`_get_or_create_session()` for the same `chat_id` — e.g. a per-`chat_id` lock, or move the index-read-and-delete into a Redis `MULTI`/`WATCH` transaction (or a Lua script) so the enumerate-and-delete is atomic with respect to concurrent `sadd`s.

**Confidence:** Medium — the absence of synchronisation and the resulting orphan/self-heal path are confirmed facts in the code; actual occurrence depends on precise thread-timing overlap between the RabbitMQ consumer and Telegram-polling threads for the same `chat_id`, which cannot be proven from static analysis alone.

**Resolution Status:** RESOLVED (validated 2026-09-05, not authored this session)

**Validation Result:**
- `utils_redis/database.py` now has a `_chat_locks_guard`/`_chat_locks: dict[int, threading.Lock]` registry and a `_get_chat_lock(chat_id)` helper, explicitly documented as existing "to serialise `create_task_mapping()` against `reset_session()` for the same `chat_id`" and citing this finding by ID in its own docstring.
- `create_task_mapping()`'s entire write-then-index sequence (`redis_write(f"task:{task_id}", ..., nx=True)` followed by `sadd(f"session_tasks:{chat_id}", task_id)`) is now wrapped in `with _get_chat_lock(chat_id):` - the exact two-step sequence this finding traced as racing against a concurrent reset.
- `reset_session()`'s entire read-then-delete sequence (`smembers(f"session_tasks:{chat_id}")` through the final `session:<chat_id>` delete) is now wrapped in the same `with _get_chat_lock(chat_id):` block, using the same lock instance per `chat_id` (via `_get_chat_lock()`), so the two functions can no longer interleave for the same `chat_id` - directly closing the traced interleaving (a `task_id` written+`sadd`'d after `reset_session()`'s `SMEMBERS` read but before its `session_tasks:<chat_id>` delete, escaping deletion while losing its index entry).
- Confirmed this is a single-process, single-Python-interpreter mitigation (an in-memory `threading.Lock` per `chat_id`, not a Redis-side transaction/Lua script) - the code's own docstring discloses this limitation explicitly ("Only sufficient because this application runs as a single process... a horizontally-scaled deployment would need a Redis-side transaction/Lua script instead"), consistent with `compose.dev.yml` running a single `telegram-gateway` container. This is an accurate, disclosed scope boundary rather than an overstated fix.
- **Residual, narrower gap identified as a result of this same change:** the new `session_polls:<chat_id>` indexing (`create_poll_mapping()`), added to support the CCR-012 fix, does **not** use `_get_chat_lock()` - see **CCR-015** below.
- **Provenance:** this remediation was **not** made by me / not part of this session's own edits - validating current disk state only, per `TODO.md`.

**Classification:** The underlying CWE-362 concern (an unsynchronised race between task creation and a session reset for the same `chat_id`) is resolved for the specific `task:<task_id>`/`session_tasks:<chat_id>` pair this finding described. Finding is validated as resolved.

**Confidence:** High — verified directly against current file contents; the lock's scope and its single-process caveat are both explicitly disclosed in the code's own docstrings, not inferred.

---

### CCR-014

**Severity:** Low

**Review Date:** 2026-09-04 (follow-up pass — `user_id`-removal / `session_id` change)

**Location:** `utilities/utils_queue/message_handler.py::process_message()`, line 475

**Violated Standard:**
- CWE-563: Assignment to Variable without Use ('Unused Variable')
- PEP 8 — general code-cleanliness guidance (no specific numbered rule)

**Description:**
```python
chat_id = mapping.get("chat_id")
user_id = mapping.get("user_id")
```
`user_id` is read from the Redis task mapping but never referenced anywhere else in the function or file — confirmed via full-file `grep`, it is the only occurrence of `user_id` in `message_handler.py`. This is dead code left over from the `user_id`-removal refactor; none of the `_handle_*` dispatch functions accept or use it.

**Impact:**
No functional or security effect (the value is never forwarded anywhere), but it is a maintainability/clarity defect and a minor incomplete-refactor signal — a reviewer could reasonably (and incorrectly) infer from its presence that `user_id` is still used somewhere in this dispatch path.

**Recommended Remediation:** Remove the unused assignment.

**Confidence:** High.

**Re-confirmation (2026-09-05, on request, scoped to the `TODO.md` `session_reset` follow-up):** Re-read `message_handler.py::process_message()` directly against current source. `user_id = mapping.get("user_id")` (line 483) is still present and still unused - unaffected by the `session_reset` work in `TODO.md`, which was out of scope for this line. **Status unchanged: Open.**

**Resolution Status:** RESOLVED (validated 2026-09-05, "revalidate all open CCR", not authored this session)

**Validation Result:**
- `message_handler.py::process_message()` no longer assigns `user_id` at all - re-read directly, and confirmed via `grep` across the whole file that `user_id` no longer appears anywhere in the file body.
- **Residual, cosmetic-only note:** the module's own header comment (`# Notes: ... Resolves chat_id/user_id from Redis via task_id.`) still mentions `user_id`, which is now slightly stale documentation given the function body no longer resolves it. This is a trivial doc-comment lag, not a re-opening of the original CWE-563 concern (the unused variable itself is gone) - not worth a separate finding, noted here for completeness only.
- **Provenance:** this fix was **not** made by me / not part of any edit in this session - validating current disk state only. It was not present at the time of the 2026-09-05 second follow-up review earlier the same day; it appears to have been applied externally between that review and this revalidation request.

**Classification:** The underlying CWE-563 concern (an assigned-but-unused variable) is no longer present in the current code. Finding is validated as resolved.

**Confidence:** High — verified directly via `grep` against current file contents, not inferred.

---

### ~~CCR-015~~ — RESOLVED

**Severity:** Low

**Review Date:** 2026-09-05 (second follow-up pass — `TODO.md` `session_reset` implementation verification)

**Location:**
- `utilities/utils_redis/database.py::create_poll_mapping()` (the `sadd(f"session_polls:{chat_id}", poll_id)` step) vs. `reset_session()`'s `redis_delete(f"session_polls:{chat_id}")` (both within the scope of the CCR-012/CCR-013 remediation)

**Violated Standard:**
- CWE-362: Concurrent Execution using Shared Resource with Improper Synchronization ('Race Condition') — the same class of defect CCR-013 closed for `session_tasks:<chat_id>`, applied incompletely to the newly-added `session_polls:<chat_id>` index.

**Description:**
The CCR-013 fix serialises `create_task_mapping()` against `reset_session()` for the same `chat_id` via the new `_get_chat_lock()`. `create_poll_mapping()` — added as part of this same `session_reset` feature specifically to support the CCR-012 fix (indexing open polls under `session_polls:<chat_id>` so `reset_session()`/`_force_apply_session_reset()` can find them without a keyspace `SCAN`) — indexes `poll_id` under `session_polls:<chat_id>` with an unprotected `sadd`; it does **not** take `_get_chat_lock(chat_id)`, even though `reset_session()` now deletes that same key from inside the lock. This reintroduces the identical structural gap CCR-013 closed, just for `session_polls:<chat_id>` instead of `session_tasks:<chat_id>`.

**Evidence:**
```python
# create_poll_mapping() — no lock held
created = redis_write(f"poll:{poll_id}", value, ttl_seconds=..., nx=True)
if created:
    get_redis_client().sadd(f"session_polls:{chat_id}", poll_id)   # unprotected

# reset_session() — under _get_chat_lock(chat_id)
redis_delete(f"session_polls:{chat_id}")
```

**Impact:**
In principle, a `poll_id` `sadd`'d into `session_polls:<chat_id>` concurrently with a reset's delete of that same key could leave a poll's index entry lost (never enumerated by a future force-through sweep) or, less likely, surviving stale. In practice, exploitability is narrow: a poll can only be created for a `task_id` that already exists and is indexed under `session_tasks:<chat_id>` (`message_handler.py::_handle_poll()` requires a resolved `task_id` mapping first), and by this codebase's own documented invariant ("an open poll always has an open task_id" — `utils_session/session_reset_handler.py` module Notes), `has_open_tasks()` would already be `True` for that chat at the moment a poll is created, meaning a reset can only be *deferred* (not applied immediately) for as long as that task remains open. The window this finding depends on — a task's `session_tasks` entry being removed at the exact moment its own poll is still being indexed — would itself require an anomalous backend/orchestrator sequencing (a `completed`/`error` sent for a task before/while its poll payload is still being processed), outside this gateway's own control. No independently-reachable trigger from this gateway's own code alone was identified, unlike CCR-013's originally-confirmed reachable window.

**Recommended Remediation:**
For consistency and defence-in-depth (not because a concrete exploit path was proven), wrap `create_poll_mapping()`'s write+index step in `with _get_chat_lock(chat_id):`, mirroring `create_task_mapping()`.

**Confidence:** Low-Medium — the structural asymmetry is a confirmed fact in the code; whether it is independently reachable (versus only under an already-anomalous backend sequencing) could not be proven from static analysis alone.

**Resolution Status:** RESOLVED (validated 2026-09-05, "revalidate all open CCR", not authored this session)

**Validation Result:**
- `create_poll_mapping()` (`utils_redis/database.py`) now wraps its entire write-then-index sequence (`redis_write(f"poll:{poll_id}", ..., nx=True)` followed by `sadd(f"session_polls:{chat_id}", poll_id)`) in `with _get_chat_lock(chat_id):` - the same lock instance `create_task_mapping()` and `reset_session()` already share for the same `chat_id`.
- The function's own docstring now explicitly states this: "Holds chat_id's lock (see `_get_chat_lock()`) across the write+index step, serialised against a concurrent `reset_session()` for the same chat_id - mirrors `create_task_mapping()`'s own use of the same lock, closing the same class of race for `session_polls:<chat_id>` as well." `_get_chat_lock()`'s own docstring was also updated to reference both callers.
- This closes the exact structural asymmetry this finding identified - `session_polls:<chat_id>` is now protected the same way `session_tasks:<chat_id>` is.
- **Provenance:** this fix was **not** made by me / not part of any edit in this session - validating current disk state only. It was not present at the time of the 2026-09-05 second follow-up review earlier the same day; it appears to have been applied externally between that review and this revalidation request.

**Classification:** The underlying CWE-362 concern (unsynchronised `session_polls:<chat_id>` indexing vs. `reset_session()`) is resolved. Finding is validated as resolved.

**Confidence:** High — verified directly against current file contents, including the code's own updated docstrings, not inferred.

---

### Informational — `RESET_NOTICE_MESSAGE` Ships Blank

**Review Date:** 2026-09-05 (second follow-up pass — `TODO.md` `session_reset` implementation verification)

**Location:** `utilities/utils_session/session_reset_handler.py`, line 64 — `RESET_NOTICE_MESSAGE: str = ""`.

**Violated Standard:** None formally violated — a deliberate, disclosed design choice (`TODO.md` §6: "the value itself will be filled in separately, directly in the file"); recorded for operational-readiness traceability, not as a rule breach.

**Description:** As shipped, the chat-facing reset notice is blank. `send_reset_notice()` correctly no-ops (with a warning log) rather than sending an empty Telegram message, so this is not a functional defect. However, until an operator fills in this string, a user whose session is reset receives **no** chat-facing notice at all — only the orchestrator-facing `session_cleared` event fires.

**Recommended Remediation:** None required from a compliance standpoint. Track as a pre-deployment checklist item.

**Confidence:** High (fact); Informational only — a disclosed design choice, not an oversight.

---

### Informational — Governance / Data Retention (session identifier lifetime)

**Review Date:** 2026-09-04 (follow-up pass — `user_id`-removal / `session_id` change)

**Location:** `utilities/utils_redis/database.py::_get_or_create_session()` (line 566) — `redis_write(f"session:{chat_id}", session_id, nx=True)` with no `ttl_seconds` argument.

**Violated Standard:** None formally violated — disclosed, deliberate design choice (documented in `README.md`'s Design Decisions); recorded here for governance/data-retention traceability, not as a rule breach.

**Description:** `session:<chat_id>` is stored permanently by design. Its only purge path is the `session_reset` message (see CCR-012/CCR-013 above), itself entirely dependent on the orchestrator/backend choosing to send it. There is no automatic expiry or independent gateway-side retention ceiling. This is a reasonable tradeoff given the stated requirements, but is worth recording: the gateway provides no backstop if the "global trigger" is never fired (e.g. an orchestrator-side bug, or a user who never invokes a reset), so `session_id`/`chat_id` linkage persists in Redis indefinitely.

**Recommended Remediation:** None required unless organisational data-retention policy mandates an upper bound; if so, consider an optional `SESSION_MAPPING_TTL_SECONDS` backstop analogous to the TTLs already used for tasks/drafts/polls.

**Confidence:** High (fact); Informational only — a disclosed design choice, not an oversight.

---

### ~~CCR-016~~ — RESOLVED

**Severity:** Low

**Review Date:** 2026-09-05 (third follow-up pass — `image_draft_handler.py` behaviour change)

**Location:** `utilities/utils_telegram/utilities/image_draft_handler.py::_wait_full_duration()` (lines 254–265), in conjunction with `_consume_continue()` (lines 218–223)

**Violated Standard:**
- CWE-670: Always-Incorrect Control Flow Implementation (closest applicable mapping — implicit-by-elimination branching rather than an explicit state check)

**Description:**
When `event.wait(remaining)` returns `True` (the shared `control["event"]` was signalled) and `_consume_continue(control, is_final_cycle)` returns `False`, the code unconditionally infers `"stop"` (`else: return "stop"`) rather than explicitly checking `control["action"] == "stop"`. This is currently safe only because the only two producers of `event.set()` in this file are `_stop()` (which always pairs it with `control["action"] = "stop"`) and `continue_draft_timer()` (which always pairs it with `control["action"] = "continue"`) — the inference that "not a valid continue" therefore means "stop" is implicit, not enforced by an explicit check against the actual state value.

**Evidence:**
```python
# _consume_continue() only special-cases "continue"
if control["action"] == "continue" and not is_final_cycle:
    control["event"].clear()
    control["action"] = None
    return True
else:
    return False

# _wait_full_duration() treats every other outcome identically as "stop"
elif _consume_continue(control, is_final_cycle):
    ...
    was_extended = True
else:
    return "stop"
```

**Impact:**
No currently-reachable defect — verified by tracing every writer of `control["action"]`/`control["event"]` in this file and its two external callers (`continue_draft_timer()`, `stop_draft_timer()`/`_stop()`); both writers are consistent with the implicit assumption. The risk is a future-maintenance fragility: if a third `action` value is ever introduced, or a signal is ever set without an accompanying `action` update, it would be silently misclassified as a stop with no error surfaced.

**Recommended Remediation:** Make the check explicit — e.g. `elif control["action"] == "stop": return "stop"` — with a distinct, logged outcome for any unrecognised `action` value, for self-documenting robustness against future extension.

**Confidence:** High (verified by tracing every writer of the shared control-dict fields across the file and its callers).

**Validation (2026-09-05, on request, "validate CCR 16, 17, and 18"):** Re-read `image_draft_handler.py` directly against current source. `_wait_full_duration()` (lines 254–265) and `_consume_continue()` (lines 218–223) are unchanged in substance — the `else: return "stop"` branch still infers a stop outcome by elimination rather than an explicit `control["action"] == "stop"` check. One incidental, non-substantive change was found elsewhere in the file since the original finding was recorded: `_stop()` has been renamed to `_stop_draft_loop()` (same body, same two-line mutation at what are now lines 147–148) — this does not affect this finding's substance, since `_wait_full_duration()`/`_consume_continue()` never reference that function by name. No fix applied to this finding's own logic.

**Resolution Status:** RESOLVED (validated 2026-09-05, second validation pass, not authored this session)

**Second Validation Result:** `_wait_full_duration()` (now lines 267–286) no longer infers "stop" by elimination. It now explicitly checks `elif control["action"] == "continue" and not is_final_cycle:` (consuming via `_consume_continue()`), then `elif control["action"] == "stop": return "stop"`, and finally a genuinely new `else` branch — `logger.warning(f"...unrecognised control state (action={control['action']!r}...)"); return "stop"` — that logs and defensively defaults to stop only for a truly unrecognised value, rather than silently assuming every non-continue signal must be a stop. This closes the exact fragility this finding described.

**Classification:** The underlying CWE-670 concern (implicit-by-elimination control-flow inference) is resolved. Finding is validated as resolved.

**Confidence (re-verification):** High — verified directly against current file contents.

**Status:** RESOLVED (re-confirmed 2026-09-05)

---

### ~~CCR-017~~ — RESOLVED

**Severity:** Informational

**Review Date:** 2026-09-05 (third follow-up pass — `image_draft_handler.py` behaviour change)

**Location:** `utilities/utils_telegram/utilities/image_draft_handler.py::_draft_loop()`, lines 295 and 300 (comments `# Wait 1 min`, `# Start typing and Wait 1 min`)

**Violated Standard:** None formally violated — general code-comment accuracy / self-documenting-code best practice (no specific numbered rule).

**Description:**
These comments hardcode the *default* config-derived durations (1 minute) rather than describing the underlying computation generically. They are currently accurate against `DEFAULT_DRAFT_CYCLE_SECONDS`/`DEFAULT_DRAFT_CYCLE_NOTICE_LEAD_SECONDS`/`DEFAULT_DRAFT_TYPING_LEAD_SECONDS` (verified directly against `config.py`), but will silently go stale/misleading if `DRAFT_CYCLE_SECONDS`, `DRAFT_CYCLE_NOTICE_LEAD_SECONDS`, or `DRAFT_TYPING_LEAD_SECONDS` is ever reconfigured via environment variable in a deployment, since the comment text does not derive from or reference the settings it describes.

**Evidence:**
```python
# Wait 1 min
wait_before_notice_typing = max(0, settings.DRAFT_CYCLE_SECONDS - settings.DRAFT_CYCLE_NOTICE_LEAD_SECONDS - settings.DRAFT_TYPING_LEAD_SECONDS)
...
# Start typing and Wait 1 min
start_typing(_typing_key(chat_id), chat_id)
```

**Impact:** No functional effect — cosmetic/documentation accuracy only. A future operator who reconfigures these settings without also updating the comment would find the comment misleading relative to actual runtime behaviour.

**Recommended Remediation:** Rephrase generically, e.g. `# Silent wait before this cycle's typing indicator starts`, rather than embedding the current default's literal duration.

**Confidence:** High.

**Validation (2026-09-05, on request, "validate CCR 16, 17, and 18"):** Re-read `image_draft_handler.py::_draft_loop()` directly against current source. The comments `# Wait 1 min` (line 295) and `# Start typing and Wait 1 min` (line 300) are unchanged, word-for-word, and still accurate only against the current `DEFAULT_DRAFT_*` values in `config.py` (re-confirmed unchanged). No fix applied.

**Resolution Status:** RESOLVED (validated 2026-09-05, second validation pass, not authored this session)

**Second Validation Result:** Both comments have been replaced with settings-derived phrasing that no longer hardcodes a default duration: `# Wait 1 min` (line 295) is now `# Silent wait before this cycle's typing indicator starts` (line 316); `# Start typing and Wait 1 min` (line 300) is now `# Start typing and hold it for DRAFT_TYPING_LEAD_SECONDS, immediately before the notice` (line 321) — the latter explicitly names the setting it depends on rather than embedding its current default value. This closes the staleness risk this finding described.

**Classification:** The underlying comment-accuracy concern is resolved. Finding is validated as resolved.

**Confidence (re-verification):** High — verified directly against current file contents.

**Status:** RESOLVED (re-confirmed 2026-09-05)

---

### ~~CCR-018~~ — RESOLVED

**Severity:** Informational

**Review Date:** 2026-09-05 (third follow-up pass — `image_draft_handler.py` behaviour change)

**Location:** `utilities/utils_telegram/utilities/image_draft_handler.py` — `continue_draft_timer()` (lines 175–176), `_stop_draft_loop()` (lines 147–148, renamed from `_stop()` — see Validation note below), `_consume_continue()` (lines 219–220) — all mutate `control["action"]`/`control["event"]` outside `_lock`.

**Violated Standard:**
- CWE-362: Concurrent Execution using Shared Resource with Improper Synchronization ('Race Condition') — nearest mapping, cited for traceability.

**Description:**
`_lock` in this file only guards mutations of the `_active_drafts` dict itself (adding/removing a `chat_id` entry); the individual fields *within* a given `control` object are read/written from different threads — the per-chat background loop (`_draft_loop()`/`_consume_continue()`) versus the RabbitMQ/Telegram-polling thread invoking `continue_draft_timer()`/`stop_draft_timer()` — with no lock around those specific field accesses.

**Evidence:**
```python
# continue_draft_timer() — mutates control fields outside _lock
with _lock:
    control = _active_drafts.get(chat_id)
...
control["action"] = "continue"     # outside the lock
control["event"].set()             # outside the lock
```

**Impact:**
Every reachable interleaving was traced by hand (a button press racing a cycle's own timeout, a stale/leftover signal surviving into a subsequent cycle, an "invalid continue" landing on the final cycle) and none produced data corruption, a crash, or a resource leak — each producer of `event.set()` pairs it with a single, CPython-GIL-atomic write to `action`, and `_consume_continue()`'s `.clear()` on any recognised press guarantees no stale "set" state survives into a later cycle's wait. This is the same unsynchronized-field pattern already present in `poll_response_handler.py` (`control.get("stop")`, `control["event"].set()` also mutated outside `_lock`), so it is an established, apparently deliberate house pattern for these lightweight control dicts rather than a defect unique to this file. Recorded here as an open item at the user's instruction rather than closed as "no action required," since the underlying unsynchronized-access pattern is a genuine, present fact in the code regardless of whether an exploitable interleaving was found.

**Recommended Remediation:** If revisited, consider documenting this narrow-lock-scope convention explicitly in both files' module Notes for future maintainers, and/or widening `_lock`'s scope to cover the individual `control` field mutations for defence-in-depth, consistent with how `_active_drafts` membership itself is already protected.

**Confidence:** Medium — no exploitable path was found in every interleaving traced, but cross-thread races are inherently harder to prove exhaustively than sequential logic; the underlying lock-scope fact itself is High confidence.

**Validation (2026-09-05, on request, "validate CCR 16, 17, and 18"):** Re-read `image_draft_handler.py` directly against current source. The unsynchronized pattern is unchanged in substance: `continue_draft_timer()` (lines 175–176) still mutates `control["action"]`/`control["event"]` after its `with _lock:` block has already exited; `_consume_continue()` (lines 219–220) still holds no lock at all. One naming-only change was found: `_stop()` has been renamed to `_stop_draft_loop()`, with the identical two-line mutation (`control["action"] = "stop"`; `control["event"].set()`) still occurring after its own `with _lock:` block exits (now lines 143–148) — the rename does not alter this finding's substance, and the Location above has been corrected to reflect it. Re-confirmed against `poll_response_handler.py` (unchanged, re-read directly): `handle_poll_answer()`'s `control["event"].set()` (line 172) and `stop_poll_for_reset()`'s `control["stop"] = True` / `control["event"].set()` (lines 280–281) both still mutate outside their respective `with _lock:` blocks — the cross-file pattern comparison this finding relies on remains accurate. No fix applied.

**Resolution Status:** RESOLVED (validated 2026-09-05, second validation pass, not authored this session)

**Second Validation Result:** All three functions now mutate the shared `control` fields from inside `with _lock:`, not after it exits:
- `_stop_draft_loop()` (lines 149–156): the `control["action"] = "stop"` / `control["event"].set()` mutation moved inside the same `with _lock:` block that pops `chat_id` from `_active_drafts`.
- `continue_draft_timer()` (lines 179–189): the `control["action"] = "continue"` / `control["event"].set()` mutation likewise moved inside its `with _lock:` block.
- `_consume_continue()` (lines 233–239): now itself opens `with _lock:` around its full check-clear-reset sequence, where previously it held no lock at all.

The module's own header Notes (line 15) now explicitly documents this: "`_lock` guards both `_active_drafts` membership and each control dict's own 'action'/'event' field mutations - `_stop_draft_loop()`/`continue_draft_timer()`... and `_consume_continue()`... all mutate the same shared control fields, so all three hold `_lock` across those mutations." This closes the unsynchronized-access gap this finding described; the pattern comparison against `poll_response_handler.py` (still using the narrower lock-scope convention) is no longer applicable to this file, since `image_draft_handler.py` has since diverged to a stricter convention.

**Classification:** The underlying CWE-362 concern (unsynchronized cross-thread mutation of the shared `control` dict) is resolved. Finding is validated as resolved.

**Confidence (re-verification):** High — verified directly against current file contents, including the code's own updated module Notes.

**Status:** RESOLVED (re-confirmed 2026-09-05)

---

### ~~CCR-019~~ — RESOLVED (validated 2026-09-08)

**Severity:** Medium

**Review Date:** 2026-09-08 (fourth follow-up pass — `error_handling.py`'s new `record_send_success()`/`_push_tier2_gateway_recover()` addition)

**Location:**
- `utilities/utils_queue/error_handling.py` — module-level globals `_alert_armed`/`_consecutive_failures` (lines 33–34), read/written by `record_send_success()` (lines 86–111) and `record_send_failure()` (lines 113–146)
- `utilities/utils_telegram/gateway_outbound.py::_config_failure_reason()` (lines 75–95) — classifies a 401 as `"unauthorized"`, a 404 as `"not_found"`
- `config.py`, line 66 — `self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or DEFAULT_TELEGRAM_BOT_TOKEN`, read exactly once at process start

**Violated Standard:**
- No single CWE cleanly captures "a paired monitoring signal whose own documented remediation path silently defeats the closing half of the pair" — the closest applicable references are OWASP A09:2021 (Security Logging and Monitoring Failures) and general observability/alerting best practice (an alert must reliably resolve, or the signal becomes untrustworthy). Stated as the closest applicable classification per this review's rule-attribution requirements, not as an invented CWE identifier.

**Description:**
`_alert_armed`/`_consecutive_failures` are plain in-memory globals, explicitly documented (this file's own module Notes, line 16) as resetting on every process restart — a design choice already accepted for the alert side ("acceptable, since a restart is itself a fresh start at reassessing whether Telegram is reachable"). The new `gateway_recover` feature (`record_send_success()`/`_push_tier2_gateway_recover()`) inherits this same reset behaviour, but its consequence is materially different for `record_send_failure()`'s two config-failure reasons: a 401 (`"unauthorized"`) or 404 (`"not_found"`) fires a `gateway_alert` immediately (bypassing the consecutive-failure threshold entirely), specifically because — per this file's own docstring and `TODO.md`'s design notes — these are "permanent, config-level failures... no number of retries fixes it," i.e. an invalid/revoked bot token. `TELEGRAM_BOT_TOKEN` is read exactly once, from the environment, in `config.py::Settings.__init__()`, with no runtime reload path anywhere in the codebase (confirmed via `grep` — `gateway_outbound.py`/`gateway_inbound.py` only ever read the already-resolved `settings.TELEGRAM_BOT_TOKEN`). Consequently, the realistic, and in practice near-universal, fix for a 401/404 alert is: update the `TELEGRAM_BOT_TOKEN` environment variable, then restart the container/process. That restart re-initialises `_alert_armed` back to `True` and `_consecutive_failures` back to `0` from a clean slate — so the very first successful send after the fix sees `was_alerted = not _alert_armed = False` and never calls `_push_tier2_gateway_recover()`. The orchestrator that received the original `gateway_alert` therefore never receives its closing `gateway_recover` for this specific, and most deterministic, class of Tier 2 incident — the one this feature's own worked example (a 401/404 config fix) is arguably the most likely trigger for in practice.

**Evidence:**
```python
# error_handling.py module Notes
# - Tier 2's counter/armed-state is in-memory only and resets on restart - acceptable, since a
#   restart is itself a fresh start at reassessing whether Telegram is reachable.

# record_send_failure() - 401/404 fires immediately, bypassing the threshold
if reason in ("unauthorized", "not_found"):
    with _lock:
        should_fire = _alert_armed
        _alert_armed = False
```
```python
# config.py - TELEGRAM_BOT_TOKEN read exactly once, no reload path exists anywhere in the codebase
self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or DEFAULT_TELEGRAM_BOT_TOKEN
```
A restart between the `gateway_alert` and the next successful send resets `_alert_armed` to `True` before that send ever runs, so `record_send_success()`'s `was_alerted` check can never observe the prior alert.

**Impact:**
An orchestrator/on-call process consuming `Q_CHANNEL_OUT` and treating `gateway_alert`/`gateway_recover` as a matched open/close pair (the design this feature exists to support — see `TODO.md`'s own stated goal, "push a `gateway_recover` event the first time a send succeeds again after a `gateway_alert` was fired") will be left with a permanently "open" incident for every 401/404 alert fixed via the normal restart path, even though the gateway itself is healthy again. This degrades trust in the signal over time — an operator who learns that `gateway_recover` "sometimes doesn't come" for the most common fix path may start ignoring or manually clearing alerts, undermining the monitoring feature's purpose. This is a reliability/observability gap, not a security vulnerability, and does not affect message delivery itself.

**Recommended Remediation:**
Persist `_alert_armed`/`_consecutive_failures` (or at minimum, "an alert is currently outstanding") somewhere that survives a restart — e.g. a Redis key, mirroring how session/task/draft/poll state already survives restarts in this codebase — and have startup initialisation check it, firing a `gateway_recover` on the first successful send after a restart if an alert was left outstanding beforehand. Alternatively, if in-memory-only is retained by deliberate choice (consistent with the existing accepted rationale for the alert side), explicitly document this specific consequence (401/404 fixed via restart will not receive a paired recover) as a disclosed limitation, so the orchestrator's consumer logic can be built to expect it (e.g. treat a fresh `gateway_alert` after a gap, with no intervening `gateway_recover`, as itself implying a resolved-and-reoccurred cycle, or as the gateway process having restarted).

**Confidence:** Medium-High — the code path and its consequence are unambiguous facts, derived directly from the module's own documented restart-reset behaviour and the codebase's own confirmed absence of a token-reload path; the only source of uncertainty is that this has not been exercised end-to-end in live testing (the module's own docstring already discloses the whole feature is "not yet exercised in testing" — see `TODO.md`'s Open Questions).

**Resolution Status:** RESOLVED (validated 2026-09-08, per `CODE_TODO.md`'s "FIX — CCR-019" entry; provenance not established as this session's own edit — validating current disk state against the finding's own described scenario)

**Validation Result:**
- `utils_redis/database.py` now has `get_tier2_alert_armed()`/`set_tier2_alert_armed(armed)` — a new Redis key `tier2_alert_armed` (`"1"`/`"0"`, no TTL, matching the module's own `pending_reset:<chat_id>` convention of "must outlive an unbounded outage, resolved only by an explicit write").
- `utils_queue/error_handling.py` now has `load_tier2_alert_state()`, called once from `initialise.py::initialise_application()` immediately after `initialise_redis_connection()` (confirmed by direct read of both files) — loads `_alert_armed` from Redis at startup instead of unconditionally defaulting to `True`.
- `record_send_success()`/`record_send_failure()` now each call `set_tier2_alert_armed()` on their respective transition (armed→disarmed or disarmed→armed), confirmed directly in the current source (lines 136 and 174 respectively) — matching the "written only on the actual transition" design intent.
- **Confirmed this closes the specific scenario the finding described**: a 401/404 `gateway_alert` fixed by updating `TELEGRAM_BOT_TOKEN` and restarting the container will now have `_alert_armed` loaded back as `False` (disarmed) from Redis at the new process's startup, so the first successful send after the fix correctly observes `was_alerted = True` and fires the paired `gateway_recover` — the exact gap this finding identified no longer exists for this scenario.
- **Scope explicitly not widened to CCR-020/CCR-021** — `CODE_TODO.md`'s own decision log states this directly: "Does not address CCR-020 or CCR-021. The persist call (`set_tier2_alert_armed()`) is itself added outside `_lock` alongside the existing `_push_tier2_gateway_*()` calls, same ordering shape CCR-020 already flags — this fix does not widen or narrow that gap, it was explicitly scoped to CCR-019 only." This review concurs: the new `set_tier2_alert_armed()` call sites are additional instances of CCR-020's already-tracked, still-open pattern, not a new/separate defect — CCR-020's own Location/Evidence has been extended below to reference them, rather than raising a duplicate finding.
- **Residual caveat, not a flaw in this fix's own logic**: if Redis itself is unreachable at the exact moment `load_tier2_alert_state()` runs during startup, `get_tier2_alert_armed()` falls back to `True` (armed) per its own documented default — meaning a genuinely still-outstanding disarmed state persisted before the restart would be silently missed on that specific startup. This was always a theoretical possibility, but is now materially more reachable given the new default Redis startup behaviour introduced alongside this same batch of changes — see **CCR-022** below.

**Classification:** The underlying gap (a restart via the realistic 401/404 fix path silently orphaning the paired `gateway_recover`) is resolved for the scenario this finding described. The already-known, separately-tracked ordering race (CCR-020) is correctly left open rather than being incorrectly claimed as fixed.

**Confidence:** High — verified directly against current source (`database.py`, `error_handling.py`, `initialise.py`) and cross-referenced against `CODE_TODO.md`'s own contemporaneous decision record for this exact fix.

---

### CCR-020 — Unsynchronised state-transition-to-publish window can reorder `gateway_alert`/`gateway_recover` relative to each other

**Severity:** Medium (at identification, 2026-09-08) — **RESOLVED**, second validation 2026-09-09 (structural fix confirmed; supersedes the same-day first validation's "Partially Resolved, Low" interim rating — see Second Validation Result below)

**Review Date:** 2026-09-08 (fourth follow-up pass — `error_handling.py`'s new `record_send_success()`/`_push_tier2_gateway_recover()` addition)

**Location:**
- `utilities/utils_queue/error_handling.py::record_send_success()` (lines 128–138) and `record_send_failure()` (lines 160–175) — both release `_lock` before calling their respective `_push_tier2_gateway_*()` function
- **Update, 2026-09-08:** the same two functions also now call `set_tier2_alert_armed()` (`utils_redis/database.py`) immediately after releasing `_lock`, added by the CCR-019 fix — an additional instance of this exact same unsynchronised-window pattern, explicitly acknowledged as such in `CODE_TODO.md`'s own decision log for that fix ("Does not address CCR-020 or CCR-021... same ordering shape CCR-020 already flags"). Not a new/separate defect — recorded here rather than as a duplicate finding.
- Called concurrently from many independent threads via `utilities/utils_telegram/gateway_outbound.py`'s `send_*`/`stop_poll` functions: the Telegram long-polling thread (`gateway_inbound.py::poll_updates()`), the RabbitMQ consumer thread (`message_handler.py`, via `queue_consume_task()`), and every per-chat/per-poll background thread (`typing_indicator.py::_typing_loop()`, `image_draft_handler.py::_draft_loop()`, `poll_response_handler.py::_poll_loop()`, `session_reset_handler.py::send_reset_notice()`)

**Violated Standard:**
- CWE-362: Concurrent Execution using Shared Resource with Improper Synchronization ('Race Condition') — the same class of defect already identified and resolved elsewhere in this codebase for Redis state (CCR-013/CCR-015), applied here to the newly-added Tier 2 alert/recover signalling pair.

**Description:**
Both `record_send_success()` and `record_send_failure()` follow the same pattern: mutate the shared `_alert_armed`/`_consecutive_failures` state atomically under `_lock`, decide `should_fire`/`was_alerted` from that atomic snapshot, then release `_lock` and only afterwards call `_push_tier2_gateway_alert()`/`_push_tier2_gateway_recover()` — each of which performs its own, independent, potentially slow (`Q_PUSH_MAX_ATTEMPTS` retries, up to ~30s by default) call into `queue_push_task()`. Because the lock is released before the corresponding queue push begins, two calls on two different threads that both decide `should_fire`/`was_alerted = True` at nearly the same moment (fully possible in this application, since `send_*`/`stop_poll` are invoked concurrently from at least five independent thread classes, all sharing this same global Tier 2 state) are not serialised relative to each other beyond that shared state mutation — the actual publish to `Q_CHANNEL_OUT` can happen in either order, independent of which state transition logically happened first. Neither the `gateway_alert` nor `gateway_recover` payload carries a timestamp, sequence number, or any other ordering/correlation field (both are `{task_id: null, session_id: null, tier: 2, ...}`), so a consumer has no way to detect or correct for a reordering even if it does occur.

**Evidence:**
```python
# record_send_success() - lock released, THEN the (slow, retried) push happens
with _lock:
    was_alerted = not _alert_armed
    _consecutive_failures = 0
    _alert_armed = True
if was_alerted:
    logger.info(...)
    _push_tier2_gateway_recover(status_code)   # queue_push_task() - up to ~30s of retries

# record_send_failure() - same pattern, same gap
with _lock:
    ...
    if should_fire:
        _alert_armed = False
if should_fire:
    _push_tier2_gateway_alert(reason, status_code)   # queue_push_task() - up to ~30s of retries
```
Neither payload (`_push_tier2_gateway_alert`/`_push_tier2_gateway_recover`) carries a timestamp or sequence field to allow a consumer to reconstruct true ordering after the fact.

**Impact:**
An orchestrator relying on strict `gateway_alert` → `gateway_recover` ordering to drive an on-call paging/auto-resolve workflow could, in a narrow but genuinely reachable timing window, observe a `gateway_recover` arrive before (or without an immediately preceding) its `gateway_alert` — e.g. if the alert-firing thread's `queue_push_task()` call is delayed by a concurrent RabbitMQ retry while a different thread's near-simultaneous recovery publish succeeds first. This could cause a monitoring system to either miss the alert entirely (treating the lone `gateway_recover` as noise) or, worse, receive the alert afterwards and treat an already-resolved incident as newly opened. **Update, 2026-09-08:** the same unsynchronised window now also applies to `set_tier2_alert_armed()`'s Redis write (added by the CCR-019 fix), so the same race could, in principle, leave the *persisted* `tier2_alert_armed` value itself out of sync with the true final in-memory state — a stale value that would then be read back as ground truth by `load_tier2_alert_state()` on a subsequent restart. This is a plausible extension of this finding's existing impact, not independently verified via testing.

**Recommended Remediation:**
Either serialise the state-transition-and-publish sequence as a single critical section (e.g. widen `_lock`'s scope to cover the `queue_push_task()` call itself, accepting that this blocks other callers of `record_send_success()`/`record_send_failure()` for the duration of the publish), or add a monotonic sequence number/timestamp to both `gateway_alert` and `gateway_recover` payloads so a consumer can independently detect and correct for out-of-order delivery.

**Confidence:** Medium — the absence of synchronisation between the state mutation and the publish call, and the absence of any ordering field in the payload, are both confirmed facts in the code; actual occurrence depends on precise multi-threaded timing overlap that cannot be proven exhaustively from static analysis alone (same epistemic caveat already applied to CCR-013).

**Status / Decision:** PARTIALLY RESOLVED (validated 2026-09-09, on request "validate CR-020 fix"; downgraded Medium → Low, not fully closed)

**Validation Result (2026-09-09):**

`utils_queue/error_handling.py` was re-read directly against current source. A new module-level `_publish_lock = threading.Lock()` has been added, and both `record_send_success()`'s `if was_alerted:` branch and `record_send_failure()`'s `if should_fire:` branch now wrap their `set_tier2_alert_armed(...)` + `_push_tier2_gateway_recover()`/`_push_tier2_gateway_alert()` calls in `with _publish_lock:`. This is a genuine, correctly-targeted improvement, confirmed by direct code inspection:

- The persist-and-publish step of an armed↔disarmed transition is now mutually exclusive between the two functions — two transitions can no longer have their `set_tier2_alert_armed()`/`queue_push_task()` calls actively interleaved with each other, which was possible before this fix (the entire ~`Q_PUSH_MAX_ATTEMPTS (30) × Q_PUSH_RETRY_DELAY (1s)` ≈ 30-second worst-case publish-retry window was previously fully unsynchronised between the two functions).
- No deadlock risk: `_lock` is fully released (`with _lock:` block exits) before `_publish_lock` is ever acquired — confirmed by direct inspection, the two are never nested — and nothing reachable inside `_publish_lock`'s critical section (`set_tier2_alert_armed()` → `database.py`'s own, distinct `_lock`; `_push_tier2_gateway_*()` → `queue.py`'s own, distinct `_lock_publish`) re-enters `error_handling.py`'s `_lock` or `_publish_lock`.
- `_lock`'s scope was deliberately **not** widened to cover the publish, avoiding blocking the ~30s worst case onto every ordinary send's `record_send_success()`/`record_send_failure()` call — this was the user's stated concern and it is correctly addressed; ordinary (non-transition) sends only ever touch the cheap `_lock` critical section, never `_publish_lock`.

**However, the reordering race this finding describes is narrowed, not structurally closed**, and `CODE_TODO.md`'s own claim that locking "closes the race entirely within this codebase" is not fully supported by the code as implemented — see the "Downside of Current Implementation" analysis below for the mechanism. Because `_lock` is released before `_publish_lock` is acquired (rather than the two being coupled/handed-over), the true chronological order in which the two functions' `_lock`-protected transitions completed is not guaranteed to be preserved through to which of them acquires `_publish_lock` first — a thread can be pre-empted by the OS scheduler in the gap between releasing `_lock` and acquiring `_publish_lock`, which is a real (if now extremely narrow — microseconds rather than up to ~30 seconds) window in which the second-decided transition's publish could still win the race for `_publish_lock` and be published first. This reduces the practical likelihood of the finding's described impact by several orders of magnitude (from a multi-second window down to a single lock hand-off gap) but does not eliminate it by construction the way the Recommended Remediation's first option ("serialise the state-transition-and-publish sequence as a single critical section") would have. Accordingly, this finding is recorded as **Partially Resolved, severity downgraded from Medium to Low** to reflect the substantially reduced but still non-zero residual risk, rather than closed as fully Resolved.

**Confidence (validation):** High on what was implemented (directly observed in code); Medium on the residual-race analysis itself — the reasoning is a sound, standard concurrency argument (lock release/re-acquire is not atomic with the critical section that follows it) but its real-world likelihood of manifesting has not been verified via a live concurrency test, consistent with this feature's testing status elsewhere in `CODE_TODO.md`.

**Second Validation Result (2026-09-09, same day, on request "validate CR-020 fix" repeated) — RESOLVED, residual gap closed:**

The implementation changed again since the first validation above. `_publish_lock` has been **removed entirely**. `utils_queue/error_handling.py` was re-read in full against current source:

- `record_send_success()`'s `if was_alerted:` branch and `record_send_failure()`'s `if should_fire:` branch are now nested **inside** their respective `with _lock:` blocks — the state-mutation decision, `set_tier2_alert_armed(...)`, and `_push_tier2_gateway_recover()`/`_push_tier2_gateway_alert()` all execute as one uninterrupted critical section under the single `_lock`, with `_lock` never released between the decision and the publish. Confirmed directly in both function bodies — no intermediate `with _publish_lock:` remains anywhere in the file.
- This closes exactly the gap identified in the first validation above: because a transitioning thread now holds `_lock` for its entire decision-to-publish sequence, a second thread cannot even begin reading `_alert_armed` (which also requires `_lock`) until the first thread's publish has fully completed and `_lock` is released. This structurally guarantees the publish order matches the true order in which the two functions' transitions occurred — there is no longer a lock-release/lock-reacquire gap in which OS thread scheduling could invert the order, unlike the `_publish_lock` design validated in the first pass.
- **Accepted trade-off, explicitly recorded by the maintainer in `CODE_TODO.md`:** a transitioning call now holds `_lock` for up to the full ~30s worst-case publish-retry duration, during which *every* other thread's `record_send_success()`/`record_send_failure()` call (i.e. every `send_*()` in `gateway_outbound.py`, across every concurrent thread) blocks too — not just the two threads actually racing. `CODE_TODO.md`'s own decision log states this was traded off deliberately, on the basis that this worst case only arises when RabbitMQ is unreachable at the same time Telegram delivery is failing/recovering, a scenario in which the system is already broadly degraded. This is a legitimate, disclosed engineering trade-off rather than an oversight — see the "Downside of current implementation" note below for this review's own assessment of that trade-off's operational consequence.
- **No deadlock risk, re-confirmed:** `set_tier2_alert_armed()` → `database.py`'s own, distinct `_lock`/`_get_redis_client()`'s locking; `_push_tier2_gateway_*()` → `queue.py`'s own, distinct `_lock_publish`. Neither of those two lock objects, nor anything reachable from within their critical sections, ever attempts to acquire `error_handling.py`'s `_lock` — confirmed by tracing `set_tier2_alert_armed()` (`database.py`, via `_redis_write()`/`_get_redis_client()`) and `queue_push_task()` (`queue.py`, via `_get_rabbitmq_publish_channel()`/`_lock_publish`) directly. No cycle exists, so nesting the publish inside `_lock` does not introduce a new deadlock path.
- `CODE_TODO.md`'s decision log candidly documents the rejected intermediate `_publish_lock` design and the reasoning for abandoning it — the same "publish-order not guaranteed by a second, independently-acquired lock" mechanism this review's own first validation pass identified independently. The two analyses converge, which increases confidence in both.

**Status upgraded to RESOLVED, severity restored to Medium→n/a (closed) rather than left at the interim Low/Partially-Resolved rating** — the race this finding described is now structurally eliminated for the two functions covered, not merely narrowed.

**Downside of the current implementation (requested, not itself a compliance defect):** the accepted trade-off is a genuine operational consideration worth flagging even though it doesn't change the compliance verdict. Holding `_lock` for the full publish-retry duration means that during a RabbitMQ outage coinciding with a Tier 2 transition, **every** `send_*()`/`stop_poll()` call across the entire application — not just the two racing threads — is serialised behind that one transitioning call for up to ~30 seconds, because `record_send_success()`/`record_send_failure()` run after every send and all contend for the same single `_lock`. Concretely: the Telegram long-poll thread, the RabbitMQ consumer thread, and every per-chat draft/poll background thread would all block on their own `record_send_success()`/`record_send_failure()` call (not on the Telegram send itself, which happens before the lock is taken) until the transitioning call's publish attempt resolves. `CODE_TODO.md`'s own rationale — "the system is already broadly degraded in that scenario" — is reasonable but rests on an assumption (RabbitMQ down implies broad degradation is already tolerable) that isn't independently verified against this codebase's actual failure-mode behaviour elsewhere (e.g. `queue_push_task()`'s own bounded-retry-then-`False`-return contract, used elsewhere specifically to avoid this exact kind of pile-up). It is a reasonable, disclosed, low-likelihood-scenario trade-off, not a hidden defect — recorded here as an accepted-risk observation rather than a new finding, since it was made as an explicit, informed choice with the alternative (a sequence-number payload field, avoiding any added locking cost) considered and consciously not pursued.

---

### CCR-021 — Shared RabbitMQ publish connection/channel is used concurrently across threads without synchronisation around the actual publish call

**Severity:** High (at identification, 2026-09-08) — **RESOLVED**, validated 2026-09-09 (structural fix confirmed — see Validation Result below)

**Review Date:** 2026-09-08 (fourth follow-up pass — surfaced while tracing `record_send_success()`'s new call path into `queue_push_task()`; root cause predates this specific change and is not itself part of the reviewed diff)

**Location:**
- `utilities/utils_queue/queue.py::_get_rabbitmq_publish_channel()` (lines 182–202) and `queue_push_task()` (lines 226–268) — the shared module-level `_connection_publish`/`_channel_publish` pika `BlockingConnection`/`BlockingChannel`
- Exercised concurrently by every caller of `queue_push_task()`, including the newly-added `error_handling.py::_push_tier2_gateway_recover()` (called from `record_send_success()`, itself called from every `send_*`/`stop_poll` function in `gateway_outbound.py` across at least five independent thread classes — see CCR-020's Location list)

**Violated Standard:**
- CWE-362: Concurrent Execution using Shared Resource with Improper Synchronization ('Race Condition')
- CWE-667: Improper Locking (closest secondary mapping — the lock that exists protects only channel *acquisition*, not channel *use*)

**Description:**
`queue.py`'s own module header states, as a documented invariant: "Publish and consume each use their own dedicated connection, confined to their own thread (publish: caller's thread, consume: `_consumer_thread`), since a pika `BlockingConnection` must not be shared or used concurrently across threads." In practice, however, the *publish* connection is not confined to a single thread at all — `_get_rabbitmq_publish_channel()` acquires `_lock_publish` only long enough to lazily (re)initialise `_channel_publish` if needed, then returns the shared channel object and releases the lock. `queue_push_task()` then calls `channel.queue_declare(...)` and `channel.basic_publish(...)` directly on that shared object with **no lock held at all** during those calls. Since `queue_push_task()` is invoked from many independently-running threads in this application (the Telegram long-polling thread, the RabbitMQ consumer thread, and every per-chat/per-poll/per-task background thread — see CCR-020's Location list, all of which now reach it via `record_send_success()`/`record_send_failure()`, `push_tier1_delivery_failed()`, `push_session_cleared()`, and the poll/session-reset modules' own direct calls), two of those threads can genuinely call `channel.basic_publish()`/`channel.queue_declare()` on the same pika `BlockingChannel` at the same time — precisely the scenario the module's own header comment says must not happen.

**Evidence:**
```python
# queue.py module header (self-documented invariant)
# - Always use the helper functions in this file to enqueue and dequeue tasks.
# Publish and consume each use their own dedicated connection, confined to their own thread
# (publish: caller's thread, consume: _consumer_thread), since a pika BlockingConnection must
# not be shared or used concurrently across threads.

def _get_rabbitmq_publish_channel():
    with _lock_publish:
        if _connection_publish is None or _connection_publish.is_closed:
            _initialise_rabbitmq_publish_connection()
        return _channel_publish   # lock released here - channel handed out unprotected

def queue_push_task(payload):
    for attempt in range(1, settings.Q_PUSH_MAX_ATTEMPTS + 1):
        channel = _get_rabbitmq_publish_channel()
        channel.queue_declare(queue=settings.Q_CHANNEL_OUT, durable=True)   # no lock held
        channel.basic_publish(...)                                          # no lock held
```
`_lock_publish` is an `RLock` guarding only the `if _connection_publish is None or ...: _initialise_rabbitmq_publish_connection()` branch — it does not extend over `queue_declare()`/`basic_publish()`, which is where the actual, non-thread-safe pika I/O happens.

**Impact:**
This is a pre-existing structural gap in `queue.py`, not something introduced by the `error_handling.py` change reviewed here — but this review's own scope (tracing `record_send_success()`'s new call into `_push_tier2_gateway_recover()` → `queue_push_task()`) is what surfaced it, and this specific change measurably widens its exposure: previously, a publish from the Tier 2 path only occurred on a failure/alert transition (relatively rare); now, `record_send_success()` can also trigger a publish on the far more frequent *success* path (any send that happens to close out a prior incident), increasing the odds of two publish-triggering call sites overlapping in time across the application's several concurrent threads. Per pika's own documented threading contract (echoed by this codebase's own module comment), concurrent use of a single `BlockingConnection`/`BlockingChannel` from multiple threads is unsupported and can produce corrupted AMQP frames, unexpected/misleading exceptions, or an unexpectedly closed connection — potentially affecting **every** outbound message on `Q_CHANNEL_OUT` (Tier 1 `delivery_failed`, Tier 2 `gateway_alert`/`gateway_recover`, `session_cleared`, `poll_answer`/`poll_timed_out`), not just the newly-added recovery event.

**Recommended Remediation:**
Widen `_lock_publish`'s scope in `queue_push_task()` to cover the entire `queue_declare()`/`basic_publish()` sequence (and the retry loop around it), so only one thread at a time ever touches `_channel_publish`/`_connection_publish` — consistent with the module's own stated design intent, just not currently enforced by the code. Alternatively, give each calling thread its own dedicated publish connection (more consistent with pika's per-thread ownership model, at the cost of more open connections to RabbitMQ).

**Confidence:** Medium — the absence of any lock around the actual `basic_publish()`/`queue_declare()` calls is an unambiguous, directly-observed fact in the code, confirmed against the module's own documented invariant; whether this has already manifested as a real production defect (a corrupted frame, a dropped connection) cannot be confirmed from static analysis alone, and no test evidence either way was available for this review.

**Status / Decision:** RESOLVED (validated 2026-09-09, on request "validate ccr-021")

**Validation Result (2026-09-09):**

`utils_queue/queue.py` was re-read in full against current source, directly against this finding's own Recommended Remediation and evidence. The fix implements the remediation's first (preferred) option exactly:

- `queue_push_task()`'s entire retry loop — including `_get_rabbitmq_publish_channel()`, `channel.queue_declare()`, `channel.basic_publish()`, and the inter-attempt `time.sleep()` — is now wrapped in `with _lock_publish:`, confirmed directly in the function body (previously the lock was only held inside `_get_rabbitmq_publish_channel()` itself, released before `queue_declare()`/`basic_publish()` ever ran).
- `_lock_publish` remains an `RLock`, so `_get_rabbitmq_publish_channel()`'s own internal `with _lock_publish:` (retained for its lazy-reconnect branch) safely re-enters on the same thread — confirmed no double-lock deadlock on a single thread.
- **Every** access point to the shared `_connection_publish`/`_channel_publish` globals in the file is confirmed to go through `_lock_publish`: `_initialise_rabbitmq_publish_connection()`, `close_rabbitmq_connection()`, `_get_rabbitmq_publish_channel()`, and now the whole of `queue_push_task()`. A codebase-wide search confirms `_get_rabbitmq_publish_channel()` is called from nowhere else in the repository, so there is no remaining unguarded access path to the shared channel object anywhere in the application.
- The module header comment is confirmed corrected — it no longer claims publish is "confined to caller's thread" (previously inaccurate); it now documents `_lock_publish`'s actual dual role (connection lifecycle *and* channel use) and explicitly cross-references this finding.
- **No deadlock risk introduced, traced across the full lock graph now in play** (`error_handling.py::_lock`, `database.py::_lock`, `queue.py::_lock_publish`/`_lock_consume`): the only edges are `error_handling._lock → database._lock` (via `set_tier2_alert_armed()`) and `error_handling._lock → queue._lock_publish` (via `_push_tier2_gateway_*()` → `queue_push_task()`, following the CCR-020 fix). Neither `database._lock` nor `queue._lock_publish` ever calls back into `error_handling.py` or into each other while held — the dependency graph is a simple one-directional DAG with no cycle, so no deadlock is possible from this change or its interaction with the CCR-020 fix.
- `_lock_consume` was correctly left untouched — `queue_consume_task()`'s actual pika calls are confined to the single `_consumer_thread` by construction, and the one cross-thread interaction (`stop_queue_consumer()`) already uses pika's own `add_callback_threadsafe()` rather than calling a channel method directly from another thread, so consume was never exposed to the same hazard.

This closes the race entirely and correctly — unlike CCR-020's first (rejected) attempt, this is not a second, independently-acquired lock but the *same* lock widened to cover the entire critical section, which structurally guarantees mutual exclusion for every touch of the shared channel object, not merely a probabilistic narrowing.

**Downside of the current implementation (requested, not itself a compliance defect — and compounds directly with CCR-020's own accepted trade-off):** concurrent `queue_push_task()` callers now fully serialise, including through each other's retry-sleeps. Under a sustained RabbitMQ outage, a caller can wait up to another in-flight call's full `Q_PUSH_MAX_ATTEMPTS (30) × Q_PUSH_RETRY_DELAY (1s)` ≈ 30-second budget before its own first attempt even starts — `CODE_TODO.md`'s own decision log discloses this as an accepted, redistributed (not new) cost. More significant, and only partially disclosed in `CODE_TODO.md`'s Decisions (flagged there as "a compounding, still bounded, worst-case latency" without quantifying it): this now **compounds directly with CCR-020's own fix**. A Tier 2 transition (`record_send_success()`/`record_send_failure()`) holds `error_handling.py`'s `_lock` for its entire decision-to-publish sequence (per the CCR-020 fix), and that sequence's publish step now itself may have to wait on `queue.py`'s `_lock_publish` if another thread is already mid-retry there. In the theoretical worst case — one thread already exhausting its full ~30s `queue_push_task()` budget while holding `_lock_publish`, followed immediately by a Tier 2 transition thread that must first wait out that ~30s before starting its *own* up-to-~30s retry budget — `error_handling.py`'s `_lock` could be held for up to **~60 seconds**, during which literally every other thread's `record_send_success()`/`record_send_failure()` call across the entire application (i.e. the post-processing step of every single Telegram send) blocks. This scenario requires simultaneous RabbitMQ unavailability and thread contention on the publish path, which is a narrow, low-likelihood-but-not-implausible combination during a real outage (multiple per-chat draft/poll threads can plausibly all attempt a push around the same time). Recorded as an accepted-risk observation, consistent with the maintainer's own explicit reasoning ("the system is already broadly degraded in that scenario"), not as a new open finding — but the ~60s compounded figure itself had not been explicitly quantified in `CODE_TODO.md` prior to this validation and is worth the maintainer being aware of concretely, rather than only in the abstract "compounding" terms recorded there.

---

### CCR-022 — Redis startup connection silently reverts to "give up after one attempt" by default, undocumented in the project's own decision log and inconsistent with RabbitMQ's startup behaviour

**Severity:** Medium (at identification, 2026-09-08) — RESOLVED, validated 2026-09-09

**Review Date:** 2026-09-08 (fifth follow-up pass — surfaced while reviewing the "major changes" to `database.py` and validating CCR-019)

**Location:**
- `utilities/utils_redis/database.py::initialise_redis_connection()` (lines 39–86) and the new `_should_redis_retry_infinite()` helper (lines 127–139)
- `config.py`, lines 205/219 — new `DEFAULT_REDIS_FORCE_INFINITE_RETRY = False` / `self.REDIS_FORCE_INFINITE_RETRY`
- Compare against `utilities/utils_queue/queue.py::initialise_rabbitmq_connection()` (lines 126–150), which has no equivalent flag and always retries indefinitely, unconditionally

**Violated Standard:**
- PEP 257 / general docstring-accuracy best practice — `initialise_redis_connection()`'s own docstring is materially inconsistent with its current default behaviour.
- No CWE cleanly captures "a previously-implemented and recorded reliability fix silently reversed by a new default, undocumented in the project's own change log" — recorded as a reliability/documentation-governance concern rather than an invented CWE identifier.

**Description:**
`initialise_redis_connection()`'s docstring states, unconditionally: "Retries indefinitely, with a fixed delay between attempts, whenever Redis is not yet reachable - blocks the caller until a connection succeeds rather than giving up after a bounded number of attempts." This is no longer accurate for the function's actual default behaviour. The function now checks a new `_should_redis_retry_infinite()` helper (`settings.REDIS_FORCE_INFINITE_RETRY`, defaulting to `False`) inside its retry loop; when `False` (the default, confirmed in both `config.py` and `README.md`'s own variable table — "gives up after one attempt \[...\] (`false`, default)"), a single failed connection attempt at startup causes the function to log a warning and `break` out of the loop, returning normally with `_client` left as `None`, rather than continuing to retry. This directly reverses the previously-implemented and explicitly recorded fix in `CODE_TODO.md`'s "FIX — No retry on RabbitMQ/Redis startup connections, crashing the application" entry (Status: Implemented), whose entire stated purpose was that "a transient 'dependency not up yet' race... crashed the whole application on launch" and needed unconditional indefinite retry to avoid it. `CODE_TODO.md`'s own decision log — which meticulously records every other design choice in this same batch of changes, including explicitly scoping the CCR-019 fix away from CCR-020/CCR-021 — contains no entry at all discussing this new setting, its default, or its interaction with the earlier fix it partially reverses. RabbitMQ's structurally equivalent `initialise_rabbitmq_connection()` was left untouched and still retries indefinitely, unconditionally, with no equivalent opt-out — creating an inconsistency between the two dependencies' startup resilience behaviour for no stated reason.

**Evidence:**
```python
# database.py::initialise_redis_connection() docstring (unconditional claim, now inaccurate by default)
"""
Retries indefinitely, with a fixed delay between attempts, whenever Redis is not yet reachable -
blocks the caller until a connection succeeds rather than giving up after a bounded number of attempts.
"""
...
except redis.exceptions.RedisError as e:
    _client = None
    if not _should_redis_retry_infinite():
        logger.warning(f"Redis not reachable at startup: {e}. REDIS_FORCE_INFINITE_RETRY is disabled - giving up.")
        break                      # <-- returns without connecting and without raising, by default
    else:
        logger.warning(...)
        time.sleep(...)
```
```python
# config.py
DEFAULT_REDIS_FORCE_INFINITE_RETRY = False   # default reverses the previously-implemented fix
```
```python
# queue.py::initialise_rabbitmq_connection() - unchanged, always retries indefinitely, no equivalent flag
while True:
    try:
        ...
    except pika.exceptions.AMQPConnectionError as e:
        logger.warning(...)
        time.sleep(settings.Q_CONNECT_RETRY_DELAY_SECONDS)
```

**Impact:**
Under the default configuration, a transient "Redis not up yet" race at container start — the exact scenario the earlier fix was built to survive — now causes `initialise_redis_connection()` to give up after one attempt rather than blocking. `main()` does not crash (the function returns normally rather than raising), but `initialise_application()` proceeds to run `load_tier2_alert_state()`, `close_orphaned_drafts()`, `close_orphaned_polls()`, and `resync_pending_resets()` against a Redis client that is still `None`/disconnected on that first pass — each of these falls back to its own pre-existing "ping failed" default (an empty sweep, or `_alert_armed` defaulting to armed) rather than performing the startup recovery/resync work it exists to do, per this review's earlier analysis of `get_tier2_alert_armed()`'s failure-mode default (see CCR-019's Validation Result above). The application does self-heal on the very next Redis-dependent operation (each of `_redis_write()`/`_redis_read()`/etc. calls `_get_redis_client()` fresh, which will attempt to reconnect again), so this is a narrow startup-window degradation rather than a permanent outage — but it is a genuine, silent reduction in startup robustness compared to the previously-implemented and recorded fix, and the stale docstring means a future maintainer reading `initialise_redis_connection()` in isolation would not realise this is the current default behaviour at all.

**Recommended Remediation:**
Update `initialise_redis_connection()`'s docstring to accurately describe the conditional behaviour (retries indefinitely only if `REDIS_FORCE_INFINITE_RETRY` is set). Separately, confirm with the maintainer whether reverting the default startup-resilience behaviour for Redis (while leaving RabbitMQ's equivalent path unconditionally infinite) is an intentional, permanent decision or an oversight — if intentional, record the rationale in `CODE_TODO.md` alongside the other decisions in this same batch of changes, consistent with the project's own established documentation discipline; if not, consider defaulting `REDIS_FORCE_INFINITE_RETRY` to `True` to restore parity with RabbitMQ's startup behaviour and the originally-recorded fix.

**Confidence:** High — the docstring/behaviour mismatch, the new default, and the inconsistency with RabbitMQ's unconditional retry are all directly observed, unambiguous facts in the current source and `README.md`; the operational-impact assessment (self-healing on the next Redis operation) is a reasoned deduction from the code's own structure, not independently verified via live testing.

**Status / Decision:** RESOLVED (validated 2026-09-09, on request "validate CR-022 fix")

**Validation Result (2026-09-09):**

Both elements of this finding's Recommended Remediation have been directly confirmed against current disk state, not assumed from `CODE_TODO.md`'s own claim of closure:

- **Docstring corrected.** `initialise_redis_connection()`'s docstring (`utils_redis/database.py`, lines 39–56) no longer makes the prior unconditional "retries indefinitely" claim. It now reads: "Retries indefinitely, with a fixed delay between attempts, whenever Redis is not yet reachable, if `REDIS_FORCE_INFINITE_RETRY` is enabled - blocks the caller until a connection succeeds rather than giving up after a bounded number of attempts. Otherwise (the default), gives up after a single failed attempt, logging a warning and returning with the connection left unset." A new Notes bullet cross-references `_should_redis_retry_infinite()` and this same `CODE_TODO.md` entry, and explicitly flags the resulting asymmetry with `initialise_rabbitmq_connection()`'s still-unconditional retry — the docstring now accurately matches the implementation's actual `break`-on-single-failure behaviour observed in the code body (lines 78–85), which is unchanged from the original finding.
- **Decision recorded in `CODE_TODO.md`.** The "FIX — No retry on RabbitMQ/Redis startup connections" entry's Decisions section now contains a dedicated bullet documenting `REDIS_FORCE_INFINITE_RETRY`, explicitly cross-referencing this finding by ID (`"flagged as CCR-022 (CODE_NON_COMPLIANCE.md)"`), and recording a dated, explicit maintainer decision: **"User's explicit call (2026-09-09): keep the default `False` for now"** — with the stated rationale that Redis is deliberately being treated more conservatively than RabbitMQ's still-unconditional retry, and that the flag exists precisely so a deployment can opt back into parity via `REDIS_FORCE_INFINITE_RETRY=true` without a code change. Open Question 3 in that same entry additionally records that "for now" is not treated as a permanent decision and states the concrete condition under which it should be revisited (observed startup-window degradation matching this finding's own Impact analysis).

`config.py`'s `DEFAULT_REDIS_FORCE_INFINITE_RETRY = False` (line 205) and `README.md`'s variable table entry are both unchanged and remain consistent with the corrected docstring and the recorded decision — no drift between the three was found. The underlying behavioural inconsistency with RabbitMQ's unconditional retry still exists in the running code (this was always one of two remediation options offered — "confirm... if intentional, record the rationale... if not, consider defaulting to `True`" — and the intentional-with-recorded-rationale option was the one taken), but that is no longer an undocumented, unreconciled gap: it is now a disclosed, dated, attributable engineering decision with an explicit revisit trigger, which is what this finding's remediation asked for. Accordingly, this finding is closed as RESOLVED rather than carried forward as Accepted Risk — the compliance gap was the silent, undocumented reversal itself, not the underlying default value, and that gap is now closed.

**Confidence (validation):** High — every claim above (docstring text, `CODE_TODO.md` decision-log bullet, `config.py` default, `README.md` entry) was read directly from current source in this session, not inferred or taken on trust from `CODE_TODO.md`'s own narrative.

---

### ~~CCR-023~~ — RESOLVED — A broad-sweep deferred `session_reset` with no `task_id` of its own can never resolve via its documented natural-completion path, only via the up-to-1-hour force-through ceiling

**Severity:** Medium

**Review Date:** 2026-09-12 (tenth follow-up pass — `session_reset` broad-sweep/admin-command redesign)

**Location:**
- `utilities/utils_session/session_reset_handler.py::resolve_pending_reset_if_ready()` (the function called from `message_handler.py::_handle_completed()`/`_handle_error()` immediately after a task's Redis mapping is deleted)
- `utilities/utils_redis/database.py::get_pending_reset()` and its private helper `_get_pending_reset_info()`
- `utilities/utils_session/session_reset_handler.py::handle_session_reset_request()`/`_defer_or_apply_reset()` — the Part 4 broad-sweep call site that first creates a legitimate, task_id-less `pending_reset:<chat_id>` entry for every chat other than the one (if any) that triggered the reset

**Violated Standard:**
- No single CWE cleanly captures "an ambiguous sentinel value silently conflates two logically distinct states" — the closest applicable references are CWE-697 (Incorrect Comparison) and CWE-393 (Return of Wrong Status Code), stated as the nearest fit per this review's rule-attribution requirements, not as an invented CWE identifier. More concretely, this is a direct violation of `README.md`'s own documented contract for this feature (§"`session_reset`": "applied automatically the moment that chat's last open task naturally completes") — a project-authoritative specification, not a CWE.

**Description:**
`handle_session_reset_request()`'s new Part 4 broad sweep (`CODE_TODO.md`, implemented 2026-09-12) calls `_defer_or_apply_reset(chat_id, task_id if chat_id == triggering_chat_id else None)` for every `chat_id` returned by `get_all_session_chat_ids()`. For every chat other than the one that actually sent the admin "refresh yourself" command (i.e. the overwhelming majority of chats swept by any global reset touching more than one active conversation), `task_id` is passed as `None`. If that chat still has an open task, `_defer_or_apply_reset()` calls `set_pending_reset(chat_id, None)`, which legitimately and deliberately stores `pending_reset:<chat_id> → {"task_id": null, "created_at": ...}` — `CODE_TODO.md`'s own Part 0 explicitly documents this widening of `task_id` to `str | None` as required precisely for this case.

However, `get_pending_reset(chat_id)` — the only function `resolve_pending_reset_if_ready()` uses to decide whether a reset is currently pending for a chat — is defined as `info.get("task_id") if info else None`. This collapses two logically distinct states into the identical return value, `None`: (a) no `pending_reset:<chat_id>` key exists at all, and (b) a `pending_reset:<chat_id>` key exists, but its stored `task_id` field is legitimately `null`. `resolve_pending_reset_if_ready()`'s very first line, `if get_pending_reset(chat_id) is None: return`, cannot distinguish these two cases — it silently treats a genuinely pending, task_id-less reset exactly as if no reset were pending at all, and returns immediately without ever calling `has_open_tasks()`, `clear_pending_reset()`, or `_apply_session_reset()` — even when this function is being called at the exact moment that chat's last open task has just been closed out by its caller (`_handle_completed()`/`_handle_error()`), which is precisely the moment the reset should resolve.

This directly contradicts `README.md`'s own documented contract for this exact feature (§"`session_reset`"): "a chat with any open `task_id`... is stored durably in Redis... and applied automatically the moment that chat's last open task naturally completes (`completed`/`error`)." For every swept chat with no `task_id` of its own tied to the triggering reset, this promised behaviour does not occur.

**Evidence:**
```python
# session_reset_handler.py::handle_session_reset_request() — Part 4 broad sweep
for chat_id in get_all_session_chat_ids():
    _defer_or_apply_reset(chat_id, task_id if chat_id == triggering_chat_id else None)

# _defer_or_apply_reset() — legitimately stores a null task_id for every other chat
if has_open_tasks(chat_id):
    set_pending_reset(chat_id, task_id)   # task_id is None here for every non-triggering chat

# database.py::get_pending_reset() — collapses "absent" and "present but null" into the same value
def get_pending_reset(chat_id: int) -> str | None:
    info = _get_pending_reset_info(chat_id)
    return info.get("task_id") if info else None

# session_reset_handler.py::resolve_pending_reset_if_ready() — cannot tell the two cases apart
if get_pending_reset(chat_id) is None:
    return   # <-- also true for a genuinely-pending, task_id-less entry
```

**Impact:**
For every chat swept by a global admin "refresh yourself" reset (i.e. every chat other than the one that literally typed the command) that still has an open task at the moment the sweep runs, the reset's documented "resolve the instant the last open task completes" behaviour never fires. The reset instead only ever gets force-applied by `_enforce_pending_reset_ceiling()`'s periodic backstop, once `PENDING_RESET_MAX_WAIT_SECONDS` (3600 seconds / 1 hour by default) has elapsed since it was first deferred — even though the corresponding chat's task genuinely completed, and `_handle_completed()`/`_handle_error()` genuinely attempted to resolve it, potentially only seconds later. This defeats the stated purpose of the "graceful `session_reset`" feature (`CODE_TODO.md` §0's own Goal: "Defer a `session_reset` until any in-flight task for that chat naturally completes... keep the orchestrator positively informed when a reset actually happens") for precisely the majority-case scenario the new Part 4 broad sweep exists to serve. The eventual force-through also logs a materially misleading warning — `"Force-applied session_reset for chat_id=...  pending longer than PENDING_RESET_MAX_WAIT_SECONDS...with no completed/error ever arriving for its open task(s)"` — for a task whose `completed`/`error` message did, in fact, arrive and was processed correctly; only the reset-resolution step silently no-opped. This is a functional/reliability defect, not a security vulnerability: no data is lost or corrupted, and the reset is still guaranteed to eventually apply via the ceiling backstop, but the user-facing/orchestrator-facing delay (up to an hour, by default, instead of near-immediate) is a direct, deterministic consequence of the code as written, not a rare timing-dependent race.

**Recommended Remediation:**
Distinguish "no `pending_reset` entry exists" from "a `pending_reset` entry exists with a null `task_id`" via an explicit presence check, rather than reusing the `task_id` field's own optionality as the sentinel for both. For example, have `resolve_pending_reset_if_ready()` call the existing private `_get_pending_reset_info(chat_id)` directly and check `if info is None: return` instead of routing through `get_pending_reset(chat_id)`; alternatively, change `get_pending_reset()`'s own contract to return a distinguishable tri-state (e.g. a dedicated sentinel object, or a `(found: bool, task_id: str | None)` tuple) so every current and future caller can tell "absent" apart from "present but null".

**Confidence:** High — this is a deterministic logic defect traced directly from the code and from `README.md`'s own documented contract for the feature, not a timing-dependent race whose likelihood is hard to assess. Reachability requires only that the broad sweep defers a chat's reset while that chat has an open task at the moment of the sweep — an expected, ordinary occurrence for any deployment with more than a trivial number of concurrently-active chats at the moment an admin triggers a global refresh.

**Status / Decision:** RESOLVED (validated 2026-09-12, not authored this session)

**Validation Result:**
- `utils_session/session_reset_handler.py` now defines a module-level sentinel, `SYSTEM_TRIGGERED_TASK_ID = "system_triggered"` (a fixed, non-empty string that can never collide with a real `task_id`, since those are always `uuid.uuid4().hex` values per `create_task_mapping()`).
- `handle_session_reset_request()`'s broad-sweep loop — `for chat_id in get_all_session_chat_ids(): _defer_or_apply_reset(chat_id, task_id if chat_id == triggering_chat_id else SYSTEM_TRIGGERED_TASK_ID)` — now passes this sentinel, never a bare `None`, for every chat that isn't the one that actually triggered the reset. Confirmed this covers both scenarios this finding traced: the majority of chats under a user-triggered reset, and *every* chat under an orchestrator-triggered reset with no `task_id` at all (`triggering_chat_id` stays `None`, which never equals a real `chat_id`).
- A stored `pending_reset:<chat_id>` record's `task_id` field is therefore never actually `None` in practice — only ever a real `task_id` or the fixed sentinel. `database.py::get_pending_reset()` (unchanged, byte-for-byte, from this finding's original evidence — no `database.py` change was needed) now returns `None` only when no `pending_reset:<chat_id>` entry exists at all, restoring `resolve_pending_reset_if_ready()`'s `if get_pending_reset(chat_id) is None: return` check to correctness for every reachable case. `get_pending_reset()`'s own docstring now states this explicitly, and candidly discloses the residual scope limit: its implementation still could not distinguish "absent" from "present with a literal `None`" if some future caller ever stored one — directing such a caller to the private `_get_pending_reset_info()` instead, which is an honest, disclosed boundary rather than a live defect, since no current caller stores a bare `None`.
- Re-traced this finding's own worked example against the fixed code: a broad sweep now stores `pending_reset:200 → {"task_id": "system_triggered", "created_at": ...}` for a non-triggering chat with an open task; when that task later completes, `resolve_pending_reset_if_ready(200)` now correctly observes `get_pending_reset(200) == "system_triggered"` (not `None`), proceeds to check `has_open_tasks(200)` (now `False`), and correctly clears and applies the reset immediately — the exact behaviour `README.md`'s documented contract promises.
- **One follow-on documentation gap was found and corrected in this session**, at the user's explicit instruction to "clean up documentation": `database.py::get_all_pending_resets()`'s own docstring still claimed `task_id` "is `None`" for a non-triggering chat, contradicting `set_pending_reset()`'s already-updated docstring for the same stored value — corrected to reference `SYSTEM_TRIGGERED_TASK_ID` instead. This is a documentation-only correction, not a behavioural change; see Fix Mode Traceability below.
- No regression identified in `resync_pending_resets()`, `_enforce_pending_reset_ceiling()`, or `resolve_pending_resets_on_bot_started()` — all three already read the full `(chat_id, task_id, created_at)` tuple via `get_all_pending_resets()` rather than the lossy `get_pending_reset()` wrapper, so they were never affected by the original gap.
- **Provenance:** the core fix (the sentinel and its one call site) was **not** made by me / not part of any edit in this session — validating current disk state only. The one documentation correction noted above **was** made in this session, at the user's explicit instruction.

**Classification:** The underlying ambiguous-sentinel concern (this finding's own closest-applicable CWE-697/CWE-393 mapping) is resolved, and the direct contradiction of `README.md`'s documented "applied automatically the moment that chat's last open task naturally completes" contract no longer exists for any reachable case. Finding is validated as resolved.

**Confidence (validation):** High — verified directly against current source (`session_reset_handler.py`'s sentinel and its one call site, `database.py`'s three mutually-consistent docstrings) and independently re-traced through the finding's own worked example.

---

### ~~CCR-024~~ — RESOLVED — Admin reset-command matching normalises only the incoming message text, not the configured command phrase itself

**Severity:** Low

**Review Date:** 2026-09-12 (tenth follow-up pass — `session_reset` broad-sweep/admin-command redesign)

**Location:** `utilities/utils_telegram/gateway_inbound.py::_is_reset_command()` (lines 276–293)

**Violated Standard:**
- No CWE formally applies; recorded as a code-consistency / defensive-coding observation against the function's own documented normalisation contract (its docstring's stated whitespace-handling guarantee is not, in fact, applied symmetrically to both sides of the comparison it performs).

**Description:**
`_is_reset_command()`'s own docstring states the match is "case-insensitive, with leading/trailing whitespace stripped and internal runs of whitespace collapsed." This normalisation — `" ".join(text.split()).lower()` — is applied only to the incoming Telegram message text (`normalised_text`). The command phrase built from configuration, `normalised_command = f"{settings.TELEGRAM_BOT_NAME} refresh yourself".lower()`, is only lower-cased; it is never passed through the same `split()`/`" ".join()` collapsing. If `TELEGRAM_BOT_NAME` is ever configured with a leading, trailing, or doubled internal whitespace character (e.g. a trailing space accidentally left in a `.env`/`config.ini` value), `normalised_command` retains that irregularity, while `normalised_text` — by construction of `" ".join(text.split())` — never can. The two strings would then be permanently unequal for every possible user input.

**Evidence:**
```python
normalised_text = " ".join(text.split()).lower()
normalised_command = f"{settings.TELEGRAM_BOT_NAME} refresh yourself".lower()
return normalised_text == normalised_command
```

**Impact:**
A whitespace slip in `TELEGRAM_BOT_NAME`'s configured value would make `_is_reset_command()` return `False` unconditionally, silently and permanently disabling the only mechanism this codebase provides for triggering a global session reset (per `CODE_TODO.md`'s own "Confirmed requirement" — one of only two legitimate paths by which a session may ever be cleared). No error, warning, or log line anywhere would indicate why the admin command stopped working. Under a normally-configured `TELEGRAM_BOT_NAME` (a clean name/word with no incidental whitespace), this has no observable effect today — it is a latent robustness gap rather than a currently-manifesting defect.

**Recommended Remediation:** Build `normalised_command` through the identical `" ".join(...split()).lower()` normalisation already applied to `normalised_text`, so both sides of the comparison are held to the same whitespace contract the function's own docstring already claims to provide.

**Confidence:** Medium — the code asymmetry itself is a directly-observed fact; whether it manifests in a given deployment depends entirely on how `TELEGRAM_BOT_NAME` happens to be configured, which is outside this review's visibility (assumption stated).

**Status / Decision:** RESOLVED (validated 2026-09-12, not authored this session)

**Validation Result:**
- `utils_telegram/gateway_inbound.py::_is_reset_command()` now builds `normalised_command` as `" ".join(f"{settings.TELEGRAM_BOT_NAME} refresh yourself".split()).lower()` — the identical `split()`/`" ".join()`/`.lower()` normalisation already applied to `normalised_text`, confirmed directly in the current function body.
- Re-traced this finding's own Impact scenario: a `TELEGRAM_BOT_NAME` value with a stray leading/trailing/doubled-internal whitespace character now normalises identically on both sides of the comparison, closing the "permanently un-collapsed command phrase" failure mode this finding identified. No behavioural change under a normally-configured (whitespace-clean) `TELEGRAM_BOT_NAME`.
- **Provenance:** this fix was **not** made by me / not part of any edit in this session — validating current disk state only.

**Classification:** The underlying normalisation-asymmetry concern is resolved — both sides of `_is_reset_command()`'s comparison are now held to the identical whitespace contract. Finding is validated as resolved.

**Confidence (validation):** High — verified directly against current source, a one-line, unambiguous change.

---

## Compliance Verdict

**Verdict: Mostly Compliant** (the fourth follow-up review, 2026-09-08, identified one new High-severity and two new Medium-severity findings, temporarily revising the verdict down to "Partially Compliant"; the fifth follow-up review, same day, confirmed one of those Medium findings (CCR-019) RESOLVED but identified one further new Medium-severity finding (CCR-022); a sixth validation pass, 2026-09-09, confirmed CCR-022 RESOLVED; a seventh validation pass, same day, initially confirmed CCR-020 only PARTIALLY RESOLVED; an eighth validation pass, same day, confirmed a subsequent structural fix now fully RESOLVES CCR-020; a ninth validation pass, same day, confirmed the sole remaining Medium-or-above finding, CCR-021 (High), is also now RESOLVED — no Critical/High/Medium-severity findings remained open at that point, restoring the verdict to "Mostly Compliant"; a **tenth follow-up review, 2026-09-12**, scoped to the new `session_reset` broad-sweep/admin-command redesign, identified one new Medium-severity finding (**CCR-023** — a broad-sweep-deferred reset with no `task_id` of its own cannot resolve via its own documented natural-completion path) and one new Low-severity finding (**CCR-024**), **revising the verdict back down to "Partially Compliant"** pending CCR-023's resolution; an **eleventh pass, same day (validation only)**, confirmed both **CCR-023 and CCR-024 are now RESOLVED**, directly against current source — no Critical/High/Medium-severity findings remain open, **restoring the verdict to "Mostly Compliant"**)

**Rationale:**
The codebase reflects a disciplined, well-documented engineering standard — consistent timeout/retry handling, tiered failure reporting, thread-safety comments backed by correct locking, and thoughtful edge-case handling (album dedupe, orphan sweeps, debounced poll closing). No injection, broken-access-control, or memory-safety issues were identified, and existing HTML-injection risk (`parse_mode="HTML"`) is correctly mitigated at both call sites that use it.

Following this remediation pass, the highest-severity finding (CCR-001, High) and the other logging-hygiene finding (CCR-002) are both resolved and validated, and the token-propagation architectural concern (CCR-006) has been reduced to an explicitly accepted residual risk with its log-leakage angle closed off. A subsequent re-verification (on request) additionally confirmed that CCR-003 and CCR-008 are now resolved and CCR-004 is partially resolved in the current source — changes made outside this session's Fix Mode edits, validated directly against disk rather than assumed. Only CCR-005 and CCR-011 remain outstanding from that pass.

A follow-up review (2026-09-04), scoped to the subsequent `user_id`-removal / permanent `session_id` change, found the removal itself correctly and consistently implemented, but identified two new Medium-severity gaps in the new `session_reset` logic — incomplete cleanup of drafts/polls (CCR-012) and an unsynchronised race between reset and concurrent task creation (CCR-013) — plus one Low code-cleanliness item (CCR-014) and one Informational governance note on session retention. Neither new Medium finding was an injection/access-control-class defect, but both meant a `session_reset` did not yet reliably guarantee the clean-slate boundary the rest of the system's trust model assumes of it.

A second follow-up review (2026-09-05), scoped to `TODO.md`'s subsequent graceful, crash-resilient `session_reset` implementation (built specifically to close CCR-012/CCR-013), confirmed **both Medium-severity findings are now resolved** — verified line-by-line against the new `utils_session/session_reset_handler.py` module and the corresponding `utils_redis/database.py` changes (per-`chat_id` locking, draft/poll-index cleanup, deferral logic), not merely assumed from `TODO.md`'s own checklist. This closes the last Medium-severity findings outstanding in this report. One new Low-severity finding (CCR-015) was identified as a narrower, structurally-similar gap introduced by the same remediation, and CCR-014 remained open at that point, unaddressed (out of scope for that work).

A subsequent revalidation (2026-09-05, same day, on request "revalidate all open CCR") re-checked every finding still marked Open - CCR-005, CCR-011, CCR-014, CCR-015 - directly against current source. **CCR-014 and CCR-015 were both found to have been fixed in the interim**, outside this session's own edits (the unused `user_id` variable removed; `create_poll_mapping()` now holds `_get_chat_lock()` the same way `create_task_mapping()` does). Only **CCR-005** and **CCR-011** remain open as of this revalidation.

A third follow-up review (2026-09-05, same day, on request "changes have been made to image_draft_handler.py including behaviour change, validate non-compliance") examined a subsequent behaviour change to the draft keep-alive cycle's continue-button handling in `image_draft_handler.py`. The changed behaviour itself was confirmed correctly and consistently implemented against `README.md`'s spec, with no exploitable defect identified across an exhaustive cross-thread interleaving trace. At the user's explicit instruction, three findings from this review are recorded as open non-compliance items — **CCR-016** (Low, an implicit rather than explicit state check with a future-maintenance fragility risk), **CCR-017** (Informational, default-value-hardcoded comments that could go stale under reconfiguration), and **CCR-018** (Informational, unsynchronized in-memory control-dict field mutation across threads — a pattern already present elsewhere in the codebase, not unique to this change, but logged as open rather than closed per instruction).

A fourth follow-up review (2026-09-08, on request, "review the modification to error_handling.py — mainly the addition of `_push_tier2_gateway_recover()` and `record_send_success()` — for weaknesses") examined the new `gateway_recover` (Tier 2) counterpart-confirmation feature documented in `TODO.md`'s "NEW — `gateway_recover`" section. `utilities/utils_queue/error_handling.py` (the changed file), `utilities/utils_telegram/gateway_outbound.py` (all 8 updated `record_send_success()` call sites), `utilities/utils_queue/queue.py`, `config.py`, `utilities/utils_queue/message_handler.py`, `CODE_TODO.md`, and `CODE_SEQUENCE_DIAGRAM.md` §10.1–10.4 were read directly against current source, cross-referencing the feature's own stated design intent and open questions. The feature is implemented consistently with its own documented design (once-per-incident firing, correct payload shape, correct `_alert_armed` re-arming) — no defect was found in the core once-per-incident logic itself. Three new findings were identified and are recorded as Open: **CCR-019** (Medium — a process restart, the realistic fix path for the 401/404 alerts this feature is most deterministically triggered by, silently resets the in-memory Tier 2 state and orphans the corresponding `gateway_recover`), **CCR-020** (Medium — the state-transition-to-publish window is unsynchronised across the many independent threads that call into `gateway_outbound.py`'s send functions, allowing `gateway_alert`/`gateway_recover` to be published out of order relative to each other, with no ordering field in either payload to detect this), and **CCR-021** (High — surfaced while tracing this same call path: `queue.py`'s shared RabbitMQ publish `BlockingConnection`/`BlockingChannel` is used concurrently across threads with no lock held around the actual `basic_publish()`/`queue_declare()` calls, directly contradicting the module's own documented single-thread-per-connection invariant; a pre-existing gap in `queue.py`, not introduced by this diff, but materially more exposed now that a success — not just a failure — can trigger a publish). No fixes were applied this pass (review-only; not instructed to enter Fix Mode).

A fifth follow-up review (2026-09-08, same day, on request, "major changes have been made to database.py and also validate ccr-019 — verify for regression") re-read `utilities/utils_redis/database.py` in full against its previous state, cross-referenced against `utilities/utils_queue/error_handling.py`, `utilities/initialise.py`, `config.py`, `README.md`, and `CODE_TODO.md`'s newly-added "FIX — CCR-019", "FIX — `_redis_write()`/`_redis_read()` had no retry", and "FIX — remaining raw `sadd`/`srem`/`scard`/`smembers`/`scan_iter` calls" entries. **CCR-019 is confirmed RESOLVED** for the exact scenario it described — `get_tier2_alert_armed()`/`set_tier2_alert_armed()` (new, `database.py`) and `load_tier2_alert_state()` (new, `error_handling.py`, called from `initialise_application()`) correctly persist and restore the armed/disarmed flag across a restart, closing the gap where a 401/404 alert fixed via restart never received its paired `gateway_recover`. `CODE_TODO.md`'s own decision log explicitly and correctly scopes this fix away from CCR-020/CCR-021 (disclosing, not hiding, that the new `set_tier2_alert_armed()` call shares CCR-020's existing unsynchronised-window pattern) — this review concurs and has extended CCR-020's own Location/Evidence to reference the new call site rather than raising a duplicate finding. The broader retry-hardening changes in `database.py` (`_redis_write()`/`_redis_read()` gaining retry, `_redis_sadd()`/`_redis_srem()`/`_redis_smembers()`/`_redis_ping()` added, `create_task_mapping()`'s retry loop corrected) were traced against every caller and found to be safe, backward-compatible refactors with no signature changes and no regression in the CCR-012/013/015 per-`chat_id` locking they sit alongside. One new Medium-severity finding was identified and is recorded as Open: **CCR-022** — a new `REDIS_FORCE_INFINITE_RETRY` setting (default `False`, disclosed in `README.md` but absent from `CODE_TODO.md`'s otherwise-thorough decision log) silently reverses the previously-implemented and recorded "retry indefinitely at startup" fix for Redis specifically, leaves `initialise_redis_connection()`'s own docstring materially inaccurate for the new default, and creates an unexplained inconsistency with RabbitMQ's structurally equivalent startup path (still unconditionally infinite). No fixes were applied this pass (review-only; not instructed to enter Fix Mode).

**Sixth pass — validation only (2026-09-09, on request, "validate CR-022 fix"):** `utils_redis/database.py::initialise_redis_connection()`'s docstring and `CODE_TODO.md`'s decision log were re-read directly against current source, specifically against this finding's own two-part Recommended Remediation. **CCR-022 is confirmed RESOLVED** — the docstring no longer makes an unconditional "retries indefinitely" claim, now accurately describing the `REDIS_FORCE_INFINITE_RETRY`-gated behaviour and explicitly cross-referencing both `_should_redis_retry_infinite()` and this finding's own governing `CODE_TODO.md` entry; and that same `CODE_TODO.md` entry now records a dated, explicit maintainer decision ("keep the default `False` for now") with a stated rationale and revisit condition, closing the previously-undocumented gap. The underlying inconsistency with RabbitMQ's unconditional retry behaviour still exists by design — this was always the disclosed, intentional-and-documented option offered in the original remediation, not an oversight — so it is not carried forward as a separate open item. No code was modified in this validation pass; the fix being validated was authored outside this session (`CODE_TODO.md`'s own dated attribution places the decision on 2026-09-09).

**Seventh pass — validation only (2026-09-09, same day, on request, "validate CR-020 fix"):** `utils_queue/error_handling.py` was re-read directly against current source, specifically against this finding's own Recommended Remediation and a first-principles lock-ordering/deadlock trace. A new `_publish_lock` now serialises `record_send_success()`/`record_send_failure()`'s persist-and-publish step of an armed↔disarmed transition against each other, confirmed never nested with `_lock` (no deadlock path identified) and confirmed not widening `_lock`'s own per-send blocking cost, matching the user's stated design concern. **CCR-020 is confirmed PARTIALLY RESOLVED, severity downgraded Medium → Low** rather than fully closed: because `_lock` is released before `_publish_lock` is acquired (the two are not coupled/handed-over), the true order in which the two functions' state transitions completed is not structurally guaranteed to carry through to which of them publishes first — a genuine, if now much narrower (a single lock hand-off gap rather than up to ~30 seconds), residual race remains. This gap, its mechanism, and a recommended structural remediation (lock coupling, or the originally-suggested ordering/sequence payload field) were given to the user directly as the requested "downside of current implementation" analysis, rather than silently accepted from `CODE_TODO.md`'s own "closes the race entirely" characterisation. No code was modified in this validation pass; the fix being validated was authored outside this session.

**Eighth pass — validation only (2026-09-09, same day, on request "validate CR-020 fix" repeated):** `utils_queue/error_handling.py` was re-read directly against current source, which had changed again since the seventh pass. The interim `_publish_lock` design has been removed and replaced with the exact structural remediation this review's seventh-pass "downside" analysis recommended: `_lock`'s own scope was widened to cover the transition branches' entire decision-to-publish sequence as one uninterrupted critical section, rather than two separately-acquired locks. This was re-traced for deadlock risk against `database.py`'s and `queue.py`'s own distinct locks (no cycle found) and confirmed to structurally guarantee publish order now matches transition order, since a second thread cannot begin its own transition decision until the first thread's entire decision-and-publish sequence has completed and released `_lock`. **CCR-020 is confirmed RESOLVED**, superseding the seventh pass's interim "Partially Resolved, Low" rating. `CODE_TODO.md`'s own decision log independently documents the same reasoning for rejecting the `_publish_lock` design that this review's seventh pass identified — the two analyses converge. An accepted trade-off (a transitioning call can now hold `_lock` for the full ~30s publish-retry duration, blocking every other thread's `record_send_success()`/`record_send_failure()` call during a simultaneous RabbitMQ outage) is disclosed as an operational downside worth being aware of, not a compliance defect in its own right — recorded in the finding's own Second Validation Result rather than as a new open item. No code was modified in this validation pass; the fix being validated was authored outside this session.

**Ninth pass — validation only (2026-09-09, same day, on request "validate ccr-021"):** `utils_queue/queue.py` was re-read in full directly against current source, against this finding's own Recommended Remediation. `_lock_publish` now covers `queue_push_task()`'s entire retry loop — `_get_rabbitmq_publish_channel()`, `channel.queue_declare()`, `channel.basic_publish()`, and the inter-attempt sleep — rather than only the channel-acquisition branch as before. A codebase-wide search confirmed `_get_rabbitmq_publish_channel()` has no other caller, so every remaining access point to the shared `_connection_publish`/`_channel_publish` globals is now confirmed to be lock-guarded, with no unprotected path left anywhere in the application. **CCR-021 is confirmed RESOLVED.** A full three-module lock-graph trace (`error_handling.py`, `database.py`, `queue.py`) found no deadlock risk — the dependency graph is a simple one-directional DAG. This fix's interaction with the CCR-020 fix was quantified rather than left at `CODE_TODO.md`'s own abstract "compounding, still bounded" description: in the theoretical worst case, `error_handling.py`'s `_lock` can now be held for up to ~60 seconds (two stacked ~30s publish-retry budgets), during which every other thread's Tier 2 post-send bookkeeping blocks. This is recorded as a disclosed, accepted-risk operational downside — consistent with the maintainer's own stated reasoning — not as a new open finding. With CCR-021 now resolved, no Critical/High/Medium-severity findings remained open in this report at that point; the overall verdict was restored to "Mostly Compliant." No code was modified in this validation pass; the fix being validated was authored outside this session.

**Tenth follow-up review (2026-09-12, on request, "reverify telegram_gateway for non-compliance and weakness. I have added change to new session_reset behaviour"):** `utils_session/session_reset_handler.py`, `utils_telegram/gateway_inbound.py`, `utils_queue/message_handler.py`, `utils_redis/database.py`, `utilities/initialise.py`, and `config.py` were read directly against current source, cross-referenced end-to-end against `CODE_TODO.md`'s own multi-part design record for the `session_reset` broad-sweep/admin-command redesign (Parts 0–5) and against `README.md`'s own documented `session_reset`/`pending_reset` contract. The redesign's core mechanics — admin-command detection and whitelist gating, `session_clear_request`/`session_reset`/`bot_started` payload shapes, the broad per-chat sweep itself, and the two post-implementation hardening fixes `CODE_TODO.md` already records — were all confirmed correctly and consistently implemented. One new, previously-unflagged Medium-severity finding was identified: **CCR-023** — `get_pending_reset()`'s `None` return value ambiguously represents both "no pending reset exists" and "a pending reset exists with a legitimately null `task_id`" (the latter a direct, intended consequence of the new broad sweep passing `task_id=None` for every non-triggering chat), causing `resolve_pending_reset_if_ready()` to silently fail to resolve a deferred reset the instant its chat's last open task completes — directly contradicting `README.md`'s own documented contract for this exact behaviour, and leaving the reset to fall back to the up-to-one-hour `PENDING_RESET_MAX_WAIT_SECONDS` force-through ceiling instead. One further Low-severity finding, **CCR-024** (an asymmetric whitespace-normalisation gap in the new admin-command matching), was also identified. No fixes were applied this pass (review-only; not instructed to enter Fix Mode).

**Eleventh pass — validation only (2026-09-12, same day, on request, "verify changes on CCR-023 and CCR-024 and update non-compliance audit"):** `session_reset_handler.py` and `gateway_inbound.py` were re-read directly against current source. **CCR-024 is confirmed RESOLVED** — `_is_reset_command()`'s `normalised_command` now shares the identical whitespace-collapsing normalisation as `normalised_text`. **CCR-023 is confirmed RESOLVED** — a new fixed sentinel, `SYSTEM_TRIGGERED_TASK_ID = "system_triggered"`, is now stored in place of a bare `None` for every chat swept into a broad reset that isn't the one that triggered it, restoring `get_pending_reset()`'s `None` return to its originally-intended unambiguous meaning with no change to `database.py`'s storage format. Both findings' own worked examples were independently re-traced against the fixed code, not merely checked for the presence of a code change. One follow-on documentation gap (a stale docstring on `get_all_pending_resets()`, contradicting `set_pending_reset()`'s already-updated docstring for the same value) was found and corrected in this session, at the user's own explicit instruction to clean up documentation — see Fix Mode Traceability below. No other code was modified in this validation pass; the core CCR-023/CCR-024 fixes were authored outside this session.

**Remaining Blockers to a "Compliant" Verdict:**
1. CCR-005 (Low) — RabbitMQ/Redis connections lack TLS in transit; unchanged, re-confirmed still open on revalidation (2026-09-05). Treated as a low-severity, network-topology-dependent accepted risk under the same closed-host deployment context validated for CCR-003, rather than a hard blocker.
2. CCR-011 (Low) — `_registered_callbacks` has no hard size cap; re-confirmed still open on revalidation (2026-09-05). **[Skipped at the user's request during the 2026-09-03 remediation pass; not examined again since]**

No Critical, High, or Medium-severity findings remain open as of the 2026-09-12 eleventh validation pass — the only two open items are both Low-severity and neither is treated as a hard blocker (see above).

**Resolved / no longer blocking (2026-09-12 eleventh validation pass, same day):**
- ~~CCR-023~~ (Medium → n/a) — **RESOLVED** (validated 2026-09-12, on request "verify changes on CCR-023 and CCR-024 and update non-compliance audit"). `session_reset_handler.py` now stores a fixed sentinel (`SYSTEM_TRIGGERED_TASK_ID`) instead of a bare `None` for every broad-sweep-deferred chat that isn't the reset's own trigger, restoring `get_pending_reset()`'s `None` return to an unambiguous "no entry exists" meaning — no change needed to `database.py`'s storage format. See the finding's own Validation Result for the re-traced worked example.
- ~~CCR-024~~ (Low → n/a) — **RESOLVED** (validated 2026-09-12, same request). `gateway_inbound.py::_is_reset_command()`'s `normalised_command` now shares the identical whitespace-collapsing normalisation already applied to `normalised_text`.

**Resolved / no longer blocking (2026-09-09 ninth validation pass, same day):**
- ~~CCR-021~~ (High → n/a) — **RESOLVED** (validated 2026-09-09, on request "validate ccr-021"). `_lock_publish` (`utils_queue/queue.py`) widened to cover `queue_push_task()`'s entire retry loop, not just channel acquisition — every access point to the shared publish channel/connection is now confirmed to go through this lock, with no remaining unguarded path anywhere in the codebase. No deadlock risk found across the full three-module lock graph. A compounding worst-case latency interaction with the CCR-020 fix (`error_handling.py::_lock` held for up to ~60s in the theoretical worst case) is disclosed as an accepted-risk operational downside, not a defect — see the finding's own Validation Result.

**Resolved / no longer blocking (2026-09-09 eighth validation pass, same day, supersedes the seventh pass below):**
- ~~CCR-020~~ (Medium → n/a) — **RESOLVED** (second validation, 2026-09-09, on request "validate CR-020 fix" repeated). The interim `_publish_lock` design was replaced with `_lock`'s own scope being widened to cover the entire decision-to-publish sequence for the rare armed↔disarmed transition branches — the state read, `set_tier2_alert_armed()`, and the `_push_tier2_gateway_*()` publish now execute as one uninterrupted critical section, structurally guaranteeing publish order matches transition order. No deadlock risk found (re-traced against `database.py`/`queue.py`'s distinct locks). An accepted trade-off (a transitioning call can now block every other thread's `record_send_success()`/`record_send_failure()` call for up to ~30s under a simultaneous RabbitMQ outage) is disclosed as an operational downside worth being aware of, not a compliance defect — see the finding's own Second Validation Result.

**Superseded interim rating (2026-09-09 seventh validation pass, same day, no longer current):**
- ~~CCR-020~~ (Medium → **Low**, interim) — PARTIALLY RESOLVED (first validation, 2026-09-09). A `_publish_lock` (since removed and replaced, see above) narrowed but did not structurally close the reordering window. Retained here only for audit-trail continuity; the eighth-pass validation above is the current status.

**Resolved / no longer blocking (2026-09-09 sixth validation pass):**
- ~~CCR-022~~ (Medium → n/a) — RESOLVED (validated 2026-09-09, on request "validate CR-022 fix"). `initialise_redis_connection()`'s docstring now accurately describes the conditional (`REDIS_FORCE_INFINITE_RETRY`-gated) retry behaviour, and `CODE_TODO.md`'s decision log now records the dated, explicit maintainer decision to keep the `False` default for now, with a stated revisit condition — closing the "silent, undocumented reversal" gap this finding identified.

**Resolved / no longer blocking (2026-09-08 fifth follow-up pass):**
- ~~CCR-019~~ (Medium → n/a) — RESOLVED (validated 2026-09-08). `get_tier2_alert_armed()`/`set_tier2_alert_armed()`/`load_tier2_alert_state()` now persist and restore Tier 2's armed/disarmed flag across a restart, closing the 401/404-via-restart gap this finding described.

**Resolved / no longer blocking (this pass):**
- ~~CCR-016~~ (Low → n/a) — RESOLVED (validated 2026-09-05, second validation pass, not authored this session). `_wait_full_duration()` now explicitly checks `control["action"]` for both `"continue"` and `"stop"`, with a logged, defensive fallback for any unrecognised value.
- ~~CCR-017~~ (Informational → n/a) — RESOLVED (validated 2026-09-05, second validation pass, not authored this session). Hardcoded-duration comments in `_draft_loop()` replaced with settings-derived phrasing.
- ~~CCR-018~~ (Informational → n/a) — RESOLVED (validated 2026-09-05, second validation pass, not authored this session). `_lock`'s scope widened to cover all `control` dict field mutations across `_stop_draft_loop()`/`continue_draft_timer()`/`_consume_continue()`, documented explicitly in the module's own header Notes.

**Resolved / no longer blocking:**
- ~~CCR-003~~ (Medium → n/a) — RESOLVED (validated 2026-09-03). Hard-coded functional default credential removed from source.
- ~~CCR-004~~ (Medium → Low) — PARTIALLY RESOLVED (validated 2026-09-03). Authentication capability (CWE-306) added; TLS (CWE-319) still tracked under CCR-005.
- ~~CCR-008~~ (Low → n/a) — RESOLVED (validated 2026-09-03). Socket/connect timeouts added.
- ~~CCR-012~~ (Medium → n/a) — RESOLVED (validated 2026-09-05). `reset_session()` now clears the chat's draft and poll indexing; the new `utils_session` module stops the draft timer and closes any still-open poll before a reset applies.
- ~~CCR-013~~ (Medium → n/a) — RESOLVED (validated 2026-09-05). `create_task_mapping()` and `reset_session()` are now serialised per `chat_id` via `_get_chat_lock()`.
- ~~CCR-014~~ (Low → n/a) — RESOLVED (validated 2026-09-05, revalidation pass). Unused `user_id` assignment removed from `message_handler.py::process_message()`.
- ~~CCR-015~~ (Low → n/a) — RESOLVED (validated 2026-09-05, revalidation pass). `create_poll_mapping()` now holds `_get_chat_lock(chat_id)` across its write+index step, mirroring `create_task_mapping()`.

As of the 2026-09-05 revalidation, no Critical/High/Medium-severity findings remained open, with only two Low-severity items outstanding (CCR-005, an accepted risk; CCR-011, unaddressed/skipped). CCR-016, CCR-017, and CCR-018 (identified and validated as still-open earlier the same day) were re-validated once more on request and found to have all been resolved in the interim, outside this session's own edits.

**This position changed with the fourth follow-up review (2026-09-08):** one High-severity finding (CCR-021) and two Medium-severity findings (CCR-019, CCR-020) were newly identified in the `gateway_recover` (Tier 2) feature and its underlying RabbitMQ publish path — all three were subsequently confirmed RESOLVED across the sixth-through-ninth validation passes (2026-09-09), restoring "Mostly Compliant" at that point.

**This position changed again with the tenth follow-up review (2026-09-12):** one new Medium-severity finding (CCR-023) was identified in the newly-implemented `session_reset` broad-sweep redesign. This temporarily revised the overall verdict from "Mostly Compliant" back down to "Partially Compliant."

**This position was restored by the eleventh pass, later the same day (2026-09-12):** both CCR-023 and CCR-024 were confirmed RESOLVED, validated directly against current source. No Critical/High/Medium-severity findings remain open as of this report, restoring the verdict to "Mostly Compliant."

---

## Findings Summary Table

| ID | Severity | Category | Location | Standard | Status |
|----|----------|----------|----------|----------|--------|
| ~~CCR-001~~ | High | Security | gateway_outbound.py, gateway_inbound.py | CWE-532, CWE-522 | **RESOLVED** |
| ~~CCR-002~~ | Medium | Security / Governance | gateway_inbound.py::poll_updates | CWE-532 | **RESOLVED** |
| ~~CCR-003~~ | ~~Medium~~ n/a | Security | config.py | CWE-798 | **RESOLVED** (validated 2026-09-03, not authored this session) |
| ~~CCR-004~~ | ~~Medium~~ **Low** | Security | utils_redis/database.py, config.py | CWE-306 (closed), CWE-319 (open, see CCR-005) | **PARTIALLY RESOLVED** (validated 2026-09-03, not authored this session) |
| CCR-005 | Low | Security | utils_queue/queue.py, utils_redis/database.py | CWE-319 | Open — Accepted Risk (re-verified 2026-09-03, unchanged) |
| ~~CCR-006~~ | Medium | Security / Governance | gateway_inbound.py | CWE-522 (closest) | **MITIGATED** (residual risk accepted) |
| ~~CCR-007~~ | Low | Maintainability | main.py | Best practice | **RESOLVED** |
| ~~CCR-008~~ | ~~Low~~ n/a | Reliability | utils_redis/database.py | CWE-400 (closest) | **RESOLVED** (validated 2026-09-03, not authored this session) |
| ~~CCR-009~~ | Low | Maintainability | utilities/logging.py → logging_setup.py | PEP 8 | **RESOLVED*** (old file could not be deleted — see notes) |
| ~~CCR-010~~ | Informational | Maintainability | config.py::get_env_int | None (consistency) | **RESOLVED** |
| CCR-011 | Low | Reliability | button_prompt_handler.py | CWE-400 | Open (skipped) |
| ~~CCR-012~~ | Medium | Reliability / Governance | utils_redis/database.py::reset_session | CWE-459 (CWE-664) | **RESOLVED** (validated 2026-09-05, not authored this session) |
| ~~CCR-013~~ | Medium | Reliability / Security | utils_redis/database.py::reset_session vs. create_task_mapping | CWE-362 | **RESOLVED** (validated 2026-09-05, not authored this session) |
| ~~CCR-014~~ | Low | Maintainability | utils_queue/message_handler.py::process_message | CWE-563 | **RESOLVED** (validated 2026-09-05 revalidation, not authored this session) |
| ~~CCR-015~~ | Low | Reliability / Security | utils_redis/database.py::create_poll_mapping vs. reset_session | CWE-362 | **RESOLVED** (validated 2026-09-05 revalidation, not authored this session) |
| Informational | Informational | Governance | utils_redis/database.py::_get_or_create_session | None (design disclosure) | Accepted design choice (2026-09-04) |
| Informational | Informational | Governance | utils_session/session_reset_handler.py::RESET_NOTICE_MESSAGE | None (design disclosure) | Accepted design choice, pre-deployment item (new, 2026-09-05) |
| ~~CCR-016~~ | Low | Reliability / Maintainability | utils_telegram/utilities/image_draft_handler.py::_wait_full_duration | CWE-670 (closest) | **RESOLVED** (validated 2026-09-05, second validation pass, not authored this session) |
| ~~CCR-017~~ | Informational | Maintainability | utils_telegram/utilities/image_draft_handler.py::_draft_loop | None (comment accuracy) | **RESOLVED** (validated 2026-09-05, second validation pass, not authored this session) |
| ~~CCR-018~~ | Informational | Reliability | utils_telegram/utilities/image_draft_handler.py (control dict mutation) | CWE-362 (closest) | **RESOLVED** (validated 2026-09-05, second validation pass, not authored this session) |
| ~~CCR-019~~ | Medium | Reliability / Governance | utils_queue/error_handling.py, utils_redis/database.py, initialise.py | OWASP A09:2021 (closest) | **RESOLVED** (validated 2026-09-08, not authored this session) |
| ~~CCR-020~~ | Medium | Reliability | utils_queue/error_handling.py (record_send_success/record_send_failure) vs. gateway_outbound.py's concurrent callers | CWE-362 | **RESOLVED** (second validation 2026-09-09, not authored this session; interim "Low, Partially Resolved" first-pass rating superseded) |
| ~~CCR-021~~ | High | Reliability | utils_queue/queue.py (_get_rabbitmq_publish_channel, queue_push_task) | CWE-362, CWE-667 | **RESOLVED** (validated 2026-09-09, not authored this session) |
| ~~CCR-022~~ | Medium | Reliability / Maintainability | utils_redis/database.py::initialise_redis_connection, config.py, queue.py (comparison) | None formally (docstring accuracy / reliability regression) | **RESOLVED** (validated 2026-09-09, not authored this session) |
| ~~CCR-023~~ | Medium | Reliability | utils_session/session_reset_handler.py::resolve_pending_reset_if_ready, utils_redis/database.py::get_pending_reset | CWE-697, CWE-393 (closest); violates README.md's own documented contract | **RESOLVED** (validated 2026-09-12, not authored this session) |
| ~~CCR-024~~ | Low | Reliability / Maintainability | utils_telegram/gateway_inbound.py::_is_reset_command | None formally (normalisation-symmetry consistency) | **RESOLVED** (validated 2026-09-12, not authored this session) |

---

## Fix Mode Traceability

| Finding ID | Violated Rule | Fix Applied |
|------------|----------------|-------------|
| CCR-001 | CWE-532 / CWE-522 | Added `log_sanitised_exception()` (redacts `TELEGRAM_BOT_TOKEN` from the formatted traceback) in `gateway_outbound.py`; replaced all 20 `logger.exception()` calls there and 6 in `gateway_inbound.py` with it. |
| CCR-002 | CWE-532 | Added `_summarise_update()` in `gateway_inbound.py` (returns only `update_id`/`event_type`); replaced 5 raw `{update}` log interpolations with it. |
| CCR-006 | CWE-522 (closest) | Validated (via full-codebase `grep`) that no log statement anywhere emits `media_url`/`image_url`/`video_url`/`file_url`. No code change made to the Redis/RabbitMQ propagation itself — accepted as residual architectural risk, since eliminating it would require building a new media-proxy feature. |
| CCR-007 | Best practice (avoid import-time side effects) | Moved `settings.DATA_DIR.mkdir(...)`, `setup_logging()`, `logger`, and `ShutdownSignal()` construction from module level into `main()` in `main.py`. |
| CCR-009 | PEP 8 (module naming) | Created `utilities/logging_setup.py` with the original implementation; updated `main.py` and `README.md` to reference it. `utilities/logging.py` reduced to a backward-compatible re-export stub (could not be deleted — no file-deletion tool available in this environment; flagged for manual removal). |
| CCR-010 | Consistency (no formal rule) | `config.py::get_env_int` exception path changed from `return default` to `return max(minimum, default)`. |

**Re-verified, not authored this session (validated 2026-09-03 against current disk state on request — "reverify CCR 3,4,5,8"):**

| Finding ID | Violated Rule | Validation Result |
|------------|----------------|--------------------|
| CCR-003 | CWE-798 | `DEFAULT_Q_USER`/`DEFAULT_Q_PASSWORD` confirmed changed to `""` in current `config.py` (was `"chatbotAdmin"`). Fail-closed by design. RESOLVED. |
| CCR-004 | CWE-306 / CWE-319 | `REDIS_USERNAME`/`REDIS_PASSWORD` confirmed present in `config.py` and wired into `database.py`'s `redis.Redis(...)` call. CWE-306 RESOLVED; CWE-319 (TLS) still absent — remains open, tracked under CCR-005. |
| CCR-005 | CWE-319 | Confirmed unchanged — no TLS/`ssl_options`/`ssl=` on either RabbitMQ or Redis connections. Still OPEN. |
| CCR-008 | CWE-400 (closest) | `REDIS_SOCKET_CONNECT_TIMEOUT`/`REDIS_SOCKET_TIMEOUT` confirmed present in `config.py` and wired into `database.py`'s `redis.Redis(...)` call. RESOLVED. |

**Re-verified, not authored this session (validated 2026-09-05 against current disk state on request — "review TODO.md and verify all changes made for non-compliance"):**

| Finding ID | Violated Rule | Validation Result |
|------------|----------------|--------------------|
| CCR-012 | CWE-459 / CWE-664 | `reset_session()` (`utils_redis/database.py`) confirmed now calling `delete_chat_draft(chat_id)` and `redis_delete(f"session_polls:{chat_id}")`; new `utils_session/session_reset_handler.py::_apply_session_reset()` confirmed calling `stop_draft_timer(chat_id)`, and `_force_apply_session_reset()` confirmed calling `poll_response_handler.py::stop_poll_for_reset()` for every still-open poll before a force-through reset. RESOLVED. |
| CCR-013 | CWE-362 | `_get_chat_lock()`/`_chat_locks` (`utils_redis/database.py`) confirmed present; `create_task_mapping()`'s write+`sadd` and `reset_session()`'s read-then-delete confirmed both wrapped in `with _get_chat_lock(chat_id):`, serialising the two functions for the same `chat_id`. RESOLVED (single-process scope, explicitly disclosed in the code's own docstring). |

**Re-verified, not authored this session (validated 2026-09-05 against current disk state on request — "revalidate all open CCR"):**

| Finding ID | Violated Rule | Validation Result |
|------------|----------------|--------------------|
| CCR-005 | CWE-319 | Confirmed unchanged — `grep` for `ssl`/`TLS`/`tls` across `utils_queue/queue.py` and `utils_redis/database.py` returns no matches; `compose.dev.yml`'s RabbitMQ/Redis `ports:` mappings remain commented out. Still OPEN — accepted risk, unchanged. |
| CCR-011 | CWE-400 (closest) | Confirmed unchanged — `button_prompt_handler.py::_registered_callbacks` is still pruned only by `_prune_expired_callbacks()` (age-based, `TELEGRAM_CALLBACK_TTL_SECONDS`); no size-based cap exists. Still OPEN — skipped, unchanged. |
| CCR-014 | CWE-563 | The unused `user_id = mapping.get("user_id")` assignment in `message_handler.py::process_message()` is confirmed removed; `grep` for `user_id` across the file returns only a stale mention in the module's own header comment. RESOLVED. |
| CCR-015 | CWE-362 | `create_poll_mapping()` (`utils_redis/database.py`) confirmed now wrapping its write+`sadd` step in `with _get_chat_lock(chat_id):`, mirroring `create_task_mapping()`; the function's own docstring was also updated to state this explicitly. RESOLVED. |

**Re-verified, not authored this session (validated 2026-09-05 against current disk state on request — "validate CCR 16, 17, and 18," second pass):**

| Finding ID | Violated Rule | Validation Result |
|------------|----------------|--------------------|
| CCR-016 | CWE-670 (closest) | `image_draft_handler.py::_wait_full_duration()` confirmed now explicitly branching on `control["action"] == "continue"` then `control["action"] == "stop"`, with a logged `else` fallback for any unrecognised value, replacing the prior implicit by-elimination inference. RESOLVED. |
| CCR-017 | None (comment accuracy) | `image_draft_handler.py::_draft_loop()`'s two hardcoded-duration comments confirmed replaced with settings-derived phrasing that no longer embeds a literal default value. RESOLVED. |
| CCR-018 | CWE-362 (closest) | `image_draft_handler.py`'s `_stop_draft_loop()`/`continue_draft_timer()`/`_consume_continue()` confirmed now all mutating the shared `control` dict fields from inside `with _lock:`; the module's own header Notes updated to document this explicitly. RESOLVED. |

**Re-verified, not authored this session (validated 2026-09-09 against current disk state on request — "validate CR-022 fix"):**

| Finding ID | Violated Rule | Validation Result |
|------------|----------------|--------------------|
| CCR-022 | None formally (docstring accuracy / reliability regression) | `initialise_redis_connection()`'s docstring (`utils_redis/database.py`) confirmed corrected to describe the `REDIS_FORCE_INFINITE_RETRY`-conditional behaviour, no longer claiming unconditional indefinite retry; `CODE_TODO.md`'s "FIX — No retry on RabbitMQ/Redis startup connections" entry confirmed now containing a dedicated, dated bullet recording the maintainer's explicit decision to keep the `False` default, with rationale and a stated revisit condition. `config.py`'s `DEFAULT_REDIS_FORCE_INFINITE_RETRY = False` and `README.md`'s variable-table entry confirmed unchanged and consistent with both. RESOLVED. |

**Re-verified, not authored this session (validated 2026-09-09 against current disk state on request — "validate CR-020 fix"):**

| Finding ID | Violated Rule | Validation Result |
|------------|----------------|--------------------|
| CCR-020 | CWE-362 | First validation (2026-09-09): a `_publish_lock` (`utils_queue/error_handling.py`) confirmed serialising the two transition branches against each other, but confirmed not to structurally guarantee publish order — recorded PARTIALLY RESOLVED, Medium → Low. |

**Re-verified, not authored this session (validated 2026-09-09 against current disk state on request — "validate CR-020 fix," repeated same day):**

| Finding ID | Violated Rule | Validation Result |
|------------|----------------|--------------------|
| CCR-020 | CWE-362 | Second validation: `_publish_lock` confirmed removed; `record_send_success()`'s `if was_alerted:` and `record_send_failure()`'s `if should_fire:` branches confirmed now nested entirely inside their `with _lock:` blocks, making the decision-to-publish sequence one uninterrupted critical section. Re-traced for deadlock against `database.py`'s `_lock`/`_get_redis_client()` and `queue.py`'s `_lock_publish` — no cycle found. RESOLVED, superseding the first validation's interim Low/Partially-Resolved rating. An accepted full-publish-duration blocking trade-off is disclosed as an operational downside, not a compliance defect. |

**Re-verified, not authored this session (validated 2026-09-09 against current disk state on request — "validate ccr-021"):**

| Finding ID | Violated Rule | Validation Result |
|------------|----------------|--------------------|
| CCR-021 | CWE-362, CWE-667 | `_lock_publish` (`utils_queue/queue.py`) confirmed widened to cover `queue_push_task()`'s entire retry loop (channel acquisition, `queue_declare()`, `basic_publish()`, and the inter-attempt sleep), not just channel acquisition as before; confirmed `_get_rabbitmq_publish_channel()` has no other caller in the codebase, so no unguarded access path to the shared channel remains anywhere. Full three-module lock-graph trace (`error_handling.py`/`database.py`/`queue.py`) found no deadlock risk. RESOLVED. A quantified (~60s worst-case) compounding interaction with the CCR-020 fix is disclosed as an accepted-risk operational downside, not a defect. |

**Re-verified, not authored this session (validated 2026-09-12 against current disk state on request — "verify changes on CCR-023 and CCR-024 and update non-compliance audit"):**

| Finding ID | Violated Rule | Validation Result |
|------------|----------------|--------------------|
| CCR-023 | CWE-697, CWE-393 (closest) | `session_reset_handler.py::SYSTEM_TRIGGERED_TASK_ID` confirmed defined and passed by `handle_session_reset_request()`'s broad-sweep loop in place of a bare `None` for every non-triggering chat; `database.py::get_pending_reset()` confirmed unchanged, its `None` return now unambiguous. RESOLVED. |
| CCR-024 | None formally (normalisation-symmetry consistency) | `gateway_inbound.py::_is_reset_command()`'s `normalised_command` confirmed now built via the identical `" ".join(...split()).lower()` normalisation as `normalised_text`. RESOLVED. |

**Authored in this session (2026-09-12, at the user's explicit instruction to "clean up documentation" — a documentation-only correction, not a behavioural fix, and not itself a numbered finding):**

| Finding ID | Violated Rule | Fix Applied |
|------------|----------------|-------------|
| (follow-on to CCR-023) | Documentation accuracy (docstring-vs-docstring inconsistency; no CWE) | `database.py::get_all_pending_resets()`'s docstring corrected — no longer claims `task_id` "is `None`" for a non-triggering chat (which contradicted `set_pending_reset()`'s already-updated docstring for the same value); now references the `SYSTEM_TRIGGERED_TASK_ID` sentinel instead. |

---

*This report was originally a static, evidence-backed review; a subsequent revision additionally recorded an instructed remediation pass. All code changes were scoped to the minimum necessary to resolve each targeted finding, preserving existing behaviour. Where confidence is Medium (deployment-context-dependent findings), assumptions are stated explicitly within the relevant finding. A further follow-up review (2026-09-04) is appended above (CCR-012–CCR-014 and one informational note), scoped to the `user_id`-removal / permanent `session_id` change — review-only, no code modified, no Fix Mode entered. A second follow-up review (2026-09-05) is appended above (CCR-012/CCR-013 confirmed resolved, CCR-014 re-confirmed open, CCR-015 and one further informational note added), scoped to `TODO.md`'s graceful `session_reset` implementation — review-only, no code modified, no Fix Mode entered; the CCR-012/CCR-013 remediation itself was not authored in this session. A subsequent revalidation pass (2026-09-05, same day) re-checked every then-open finding (CCR-005, CCR-011, CCR-014, CCR-015) directly against current source; CCR-014 and CCR-015 are now confirmed resolved (also not authored in this session), leaving only CCR-005 and CCR-011 open. A third follow-up review (2026-09-05, same day) is appended above (CCR-016–CCR-018 added), scoped to a behaviour change in `image_draft_handler.py`'s draft keep-alive cycle — review-only, no code modified, no Fix Mode entered; all three findings were initially recorded as Open at the user's explicit instruction, including one (CCR-018) whose underlying pattern was independently confirmed to be already present elsewhere in the codebase (`poll_response_handler.py`) rather than unique to the reviewed change. A first validation pass (2026-09-05, same day) re-confirmed all three still open, correcting one incidental function rename (`_stop()` → `_stop_draft_loop()`) discovered along the way. A second validation pass (2026-09-05, same day, on request) found all three had since been resolved, outside this session's own edits, each remediated near-verbatim to this report's own recommended fix — review-only, no code modified by this session, no Fix Mode entered. A fifth follow-up review (2026-09-08, same day) is appended above (CCR-019 confirmed resolved, CCR-020 extended, CCR-022 added), scoped to major changes in `utils_redis/database.py` — review-only, no code modified, no Fix Mode entered. A sixth pass (2026-09-09, on request "validate CR-022 fix") re-checked CCR-022 directly against current source; both elements of its Recommended Remediation — the docstring correction and the recorded `CODE_TODO.md` decision — were confirmed present and accurate, and the finding is now closed as RESOLVED. This remediation was not authored in this session; it is validated against current disk state only, same provenance caveat as the other not-authored-this-session resolutions above. A seventh pass (2026-09-09, same day, on request "validate CR-020 fix") re-checked CCR-020 directly against current source; the new `_publish_lock` was confirmed correctly implemented with no deadlock risk, but a residual reordering race — narrower than before, not structurally eliminated — was identified and disclosed rather than accepting `CODE_TODO.md`'s own "closes the race entirely" claim at face value; the finding was recorded as PARTIALLY RESOLVED, severity downgraded Medium → Low. An eighth pass, later the same day, on the same request repeated, found the code had changed again: `_publish_lock` was removed and `_lock`'s own scope widened to cover the full decision-to-publish sequence, structurally closing the residual gap the seventh pass identified; CCR-020 was re-confirmed RESOLVED, superseding the seventh pass's interim rating, with an accepted full-publish-duration blocking trade-off disclosed as an operational downside rather than a new open finding. A ninth pass (2026-09-09, same day, on request "validate ccr-021") re-checked CCR-021 directly against current source; `_lock_publish` was confirmed widened to cover `queue_push_task()`'s entire retry loop, with no unguarded access path to the shared publish channel remaining anywhere in the codebase and no deadlock risk found across the full three-module lock graph — CCR-021 is confirmed RESOLVED, the last Medium-or-above finding open at that point, restoring the overall verdict to "Mostly Compliant." A quantified ~60-second worst-case compounding interaction with the CCR-020 fix is disclosed as an accepted-risk operational downside, not a defect. A tenth follow-up review (2026-09-12, on request, "reverify telegram_gateway for non-compliance and weakness. I have added change to new session_reset behaviour") examined the subsequent `session_reset` broad-sweep/admin-command redesign recorded in `CODE_TODO.md`; the redesign's core mechanics were confirmed correctly implemented against that design record and against `README.md`'s own documented contract, but one new Medium-severity finding (CCR-023 — a broad-sweep-deferred reset with a legitimately null `task_id` cannot resolve via its own documented natural-completion path, contradicting `README.md`'s stated behaviour) and one new Low-severity finding (CCR-024 — an asymmetric whitespace-normalisation gap in the new admin-command matching) were identified and recorded as Open, revising the overall verdict back down to "Partially Compliant." Review-only, no code modified in the sixth, seventh, eighth, ninth, or tenth pass, no Fix Mode entered. An eleventh pass (2026-09-12, same day, on request "verify changes on CCR-023 and CCR-024 and update non-compliance audit") re-checked both directly against current source; both are confirmed RESOLVED — `session_reset_handler.py`'s new `SYSTEM_TRIGGERED_TASK_ID` sentinel closes CCR-023, and `gateway_inbound.py::_is_reset_command()`'s symmetric normalisation closes CCR-024 — restoring the overall verdict to "Mostly Compliant." Neither core fix was authored in this session; one small follow-on documentation correction (`database.py::get_all_pending_resets()`'s stale docstring) was made in this session, at the user's own explicit instruction to clean up documentation, and is recorded separately in the Fix Mode Traceability table above rather than folded into either finding's own provenance note.*
