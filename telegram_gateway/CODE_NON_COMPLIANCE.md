# Non-Compliance Report — Telegram Gateway Application

**Status legend:** 🟢 Fixed (resolved) · 🟠 Open — Deferred (valid, postponed by decision) · 🔴 Open (needs action) · 🟡 In Progress (partly fixed) · ⚪ Rejected (closed by user decision)

**At a glance:** 🟢 21 Fixed · 🟡 1 In Progress · 🟠 2 Open — Deferred · ⚪ 1 Rejected · 🔴 0 Open

## Review Metadata

| Field | Value |
|---------|---------|
| Scope | `telegram_gateway/telegram_gateway_application/`: all Python source files, plus `README.md`, `CODE_TODO.md`, `config_sample.ini` and `compose.dev.yml` as context |
| Review Type | Static compliance review, followed by an instructed remediation pass (2026-09-03) and repeated follow-up reviews and validations |
| Reviewer | Claude Code (Code Compliance Reviewer) |
| Review Date | 2026-09-03 |
| Follow-up and Validation Dates | 2026-09-03 to 2026-09-12: eight follow-up reviews and five validation-only passes (see Change Log). 2026-10-06: CCR-005, CCR-011 and the CCR-009 clean-up re-checked against source. 2026-10-06: restructured into point form using the `docker_*` reports in `V-Project-Multimedia-Application` as the template |
| Review Depth | Three iterations per review (read, cross-file and concurrency analysis, evidence validation). Each follow-up traced the changed files against `README.md` and `CODE_TODO.md`, and did not rely on "Implemented" markers alone |

---

## Review Summary

### Files Reviewed

- Entry and config: `main.py`, `config.py`
- Utilities: `utilities/utilities.py`, `utilities/logging_setup.py`, `utilities/initialise.py`
- Access control: `utilities/utils_gatekeeper/gatekeeper.py`
- Redis state: `utilities/utils_redis/database.py`
- Queue: `utilities/utils_queue/queue.py`, `error_handling.py`, `message_handler.py`
- Session reset: `utilities/utils_session/session_reset_handler.py`
- Telegram: `utilities/utils_telegram/gateway_inbound.py`, `gateway_outbound.py`
- Telegram helpers: `typing_indicator.py`, `poll_response_handler.py`, `button_prompt_handler.py`, `image_draft_handler.py`
- Context: `README.md`, `CODE_TODO.md`, `CODE_SEQUENCE_DIAGRAM.md`, `config_sample.ini`, `compose.dev.yml`

### Standards Evaluated

PEP 8, PEP 257, OWASP Top 10, CWE mappings, Bandit-style secure coding guidance, and general secure-scripting and reliability best practice.

### Overall Assessment

- **Strengths**
  - Consistent timeout, retry and backoff handling.
  - Tiered failure reporting and orphan-recovery sweeps.
  - No injection, authentication-bypass or memory-safety defects found.
  - `parse_mode="HTML"` risk is mitigated at both call sites.
- **Main risks found (all now closed)**
  - Credential exposure through exception logging (CCR-001).
  - Raw user data in logs (CCR-002).
  - Concurrency gaps in session reset and the RabbitMQ publish path (CCR-013, CCR-020, CCR-021).
- **Open items** are two Low-severity network and memory hardening points (CCR-005, CCR-011) and the TLS half of CCR-004.

### Total Findings

- **25 numbered findings:** 2 High (CCR-001, CCR-021), 11 Medium (CCR-002, CCR-003, CCR-004, CCR-006, CCR-012, CCR-013, CCR-019, CCR-020, CCR-022, CCR-023, CCR-025), 9 Low (CCR-005, CCR-007, CCR-008, CCR-009, CCR-011, CCR-014, CCR-015, CCR-016, CCR-024), 3 Informational (CCR-010, CCR-017, CCR-018).
- **2 unnumbered Informational notes:** blank `RESET_NOTICE_MESSAGE`, and permanent `session:<chat_id>` retention. Both are disclosed design choices.
- Severities are as first raised. CCR-003 and CCR-004 were later reassessed, see their entries.
- **21 Fixed:** CCR-001, 002, 003, 007, 008, 009, 010, and CCR-012 to CCR-025.
- **1 In Progress:** CCR-004 (authentication fixed, TLS open).
- **2 Open — Deferred:** CCR-005, CCR-011.
- **1 Rejected:** CCR-006 (residual risk accepted).

### Remediation Summary

- **Applied by the reviewer (2026-09-03, at the user's instruction):** CCR-001, CCR-002, CCR-007, CCR-009, CCR-010, plus the CCR-006 log-leakage check.
- **Already in the repository when validated:** CCR-003, CCR-004 (partly), CCR-008, CCR-012 to CCR-025.
- **Documentation-only change by the reviewer (2026-09-12):** corrected the stale `get_all_pending_resets()` docstring that followed CCR-023.
- **No High or Medium finding is open.**

### Re-validation Note

- **2026-10-06:**
  - CCR-005: no TLS or `ssl_options` found in the queue, database or config code. Unchanged.
  - CCR-011: `_registered_callbacks` is still pruned by age only. Unchanged.
  - CCR-009: the `utilities/logging.py` stub is gone, so the manual clean-up it needed is done.
- **Every other finding** was last validated on the date shown in its entry and has not been re-read since.

### Compliance Verdict

**Mostly Compliant**: no Critical, High or Medium finding is open. Two Low items are deferred and one Medium item is partly fixed.

---

## Findings

### Open Findings

| ID | Severity | Title | Status |
|----|----------|-------|--------|
| CCR-004 | Medium → Low | Redis connection has no TLS (authentication added) | 🟡 In Progress |
| CCR-005 | Low | No TLS on RabbitMQ or Redis connections | 🟠 Open — Deferred |
| CCR-011 | Low | `_registered_callbacks` has no size cap | 🟠 Open — Deferred |

### Resolved Findings

| ID | Severity | Title | Status |
|----|----------|-------|--------|
| CCR-001 | High | Bot token written to logs through exception tracebacks | 🟢 Fixed |
| CCR-002 | Medium | Raw Telegram updates logged in full | 🟢 Fixed |
| CCR-003 | Medium → Low | Hard-coded default RabbitMQ credentials | 🟢 Fixed |
| CCR-006 | Medium | Token-bearing file URL forwarded to Redis and RabbitMQ | ⚪ Rejected |
| CCR-007 | Low | Import-time side effects in `main.py` | 🟢 Fixed |
| CCR-008 | Low | Redis client had no socket timeouts | 🟢 Fixed |
| CCR-009 | Low | `utilities/logging.py` shadowed the standard library | 🟢 Fixed |
| CCR-010 | Informational | `get_env_int` fallback not clamped to `minimum` | 🟢 Fixed |
| CCR-012 | Medium | `reset_session()` left drafts and polls behind | 🟢 Fixed |
| CCR-013 | Medium | Race between `reset_session()` and `create_task_mapping()` | 🟢 Fixed |
| CCR-014 | Low | Unused `user_id` assignment | 🟢 Fixed |
| CCR-015 | Low | `create_poll_mapping()` not serialised with reset | 🟢 Fixed |
| CCR-016 | Low | Implicit "stop" inference in `_wait_full_duration()` | 🟢 Fixed |
| CCR-017 | Informational | Comments hard-coded a default duration | 🟢 Fixed |
| CCR-018 | Informational | Draft control dict mutated outside `_lock` | 🟢 Fixed |
| CCR-019 | Medium | Tier 2 alert state lost on restart, orphaning `gateway_recover` | 🟢 Fixed |
| CCR-020 | Medium | Alert and recover could publish out of order | 🟢 Fixed |
| CCR-021 | High | Shared RabbitMQ publish channel used without a lock | 🟢 Fixed |
| CCR-022 | Medium | Redis startup retry reverted by default, undocumented | 🟢 Fixed |
| CCR-023 | Medium | Broad-sweep reset never resolved on natural completion | 🟢 Fixed |
| CCR-024 | Low | Admin command phrase not whitespace-normalised | 🟢 Fixed |
| CCR-025 | Medium | Malformed `TZ` crashed the process at import | 🟢 Fixed |

---

## Open Findings (Detail)

### CCR-004 — Redis Connection Has No TLS (Authentication Added)

**Severity:** Medium at identification. Reassessed to Low on 2026-09-03.

**Location:** `utilities/utils_redis/database.py::initialise_redis_connection`, `config.py` (Redis connection section)

**Violated Standard:**
- CWE-306: Missing Authentication for Critical Function (closed)
- CWE-319: Cleartext Transmission of Sensitive Information (open, tracked under CCR-005)

**Description:**
- The Redis client originally had no username, password or TLS option.
- `REDIS_USERNAME` and `REDIS_PASSWORD` now exist and are passed to `redis.Redis(...)`.
- No `ssl=` option has been added.

**Impact:**
- Task, draft and poll state travels unencrypted. This includes token-bearing draft media URLs (see CCR-006).
- In `compose.dev.yml`, Redis has no `requirepass` and no credentials are wired in, so authentication is unused in practice. This is a deployment choice, not a code defect.

**Recommended Remediation:**
- Add a configurable `REDIS_SSL` option. Track the work under CCR-005.

**Confidence:** High for the code gap. Exploitability depends on network topology, which is outside the repository.

**Status / Decision:** 🟡 In Progress (validated 2026-09-03). Authentication added outside the reviewer's edits. TLS merged into CCR-005.

---

### CCR-005 — No TLS on RabbitMQ or Redis Connections

**Severity:** Low

**Location:** `utilities/utils_queue/queue.py::_build_rabbitmq_parameters`, `utilities/utils_redis/database.py::initialise_redis_connection`

**Violated Standard:**
- CWE-319: Cleartext Transmission of Sensitive Information

**Description:**
- Neither `pika.ConnectionParameters` nor `redis.Redis` configures TLS.
- `Q_PASSWORD` and all task and session payloads cross the network in cleartext.

**Impact:**
- On an isolated Docker bridge network this is commonly accepted.
- Credentials and payloads can be sniffed if the network boundary is wider than one trusted host.
- `compose.dev.yml` keeps the RabbitMQ and Redis `ports:` mappings commented out. Both are reachable only through `chatbot-app-network`.
- No production compose file exists in the repository, so production isolation is a stated assumption.

**Recommended Remediation:**
- Add `ssl_options` for pika and `ssl=True` for redis-py as configurable options where the network is not fully trusted.

**Confidence:** Medium, because severity depends on the deployment network.

**Status / Decision:** 🟠 Open — Deferred. Accepted risk for a closed-network deployment. Re-checked 2026-10-06, unchanged.

---

### CCR-011 — `_registered_callbacks` Has No Size Cap

**Severity:** Low

**Location:** `utilities/utils_telegram/utilities/button_prompt_handler.py::_registered_callbacks`

**Violated Standard:**
- CWE-400: Uncontrolled Resource Consumption

**Description:**
- The dict is pruned by age only (`_prune_expired_callbacks()`), triggered during register and validate calls.
- With a long `TELEGRAM_CALLBACK_TTL_SECONDS` (default 3600), memory grows with the button-issue rate and has no ceiling.
- `gatekeeper.py::_access_counts` is already size-capped (`TELEGRAM_UNAUTHORISED_CACHE_SIZE`), so the pattern exists in the project.

**Impact:**
- Low at normal traffic. Theoretical memory growth under abnormally high sustained button load.

**Recommended Remediation:**
- Add an optional maximum size, mirroring `gatekeeper.py`.

**Confidence:** Medium

**Status / Decision:** 🟠 Open — Deferred. Skipped at the user's request on 2026-09-03. Re-checked 2026-10-06, unchanged.

---

## Informational Notes (Not Numbered)

### Blank `RESET_NOTICE_MESSAGE`

- **Location:** `utilities/utils_session/session_reset_handler.py`
- **Fact:** the chat-facing reset notice ships as an empty string. `send_reset_notice()` no-ops with a warning, so there is no functional defect.
- **Effect:** until an operator fills it in, users get no notice when a session resets. Only the orchestrator-facing `session_cleared` event fires.
- **Action:** none for compliance. Track as a pre-deployment checklist item.

### Permanent `session:<chat_id>` Retention

- **Location:** `utilities/utils_redis/database.py::_get_or_create_session()`
- **Fact:** the key is written with no TTL by design (see `README.md` Design Decisions).
- **Effect:** the only purge path is `session_reset`. If it is never triggered, the `session_id` to `chat_id` link persists indefinitely.
- **Action:** none unless a data-retention policy requires a bound. If so, add an optional `SESSION_MAPPING_TTL_SECONDS`.

---

## Resolved Findings (Fixed or Rejected)

Each entry below is condensed. Evidence, line numbers and full validation notes are in version control history.

### CCR-001 — Bot Token Written to Logs Through Exception Tracebacks

- **Severity / Standard:** High. CWE-532, CWE-522, OWASP A09:2021.
- **Problem:** Telegram API URLs embed the bot token. `logger.exception()` wrote `requests` errors, which include that URL, to rotating log files.
- **Resolution:** `log_sanitised_exception()` in `gateway_outbound.py` redacts the token from the traceback. It replaced all 20 `logger.exception()` calls there and 6 in `gateway_inbound.py`.
- **Status:** 🟢 Fixed (2026-09-03, applied by the reviewer).

### CCR-002 — Raw Telegram Updates Logged in Full

- **Severity / Standard:** Medium. CWE-532, data minimisation.
- **Problem:** full `update` objects (names, usernames, message text, phone numbers) were logged at five sites.
- **Resolution:** `_summarise_update()` returns only `update_id` and `event_type`. All five sites use it.
- **Status:** 🟢 Fixed (2026-09-03, applied by the reviewer).

### CCR-003 — Hard-Coded Default RabbitMQ Credentials

- **Severity / Standard:** Medium, reassessed to Low for the closed-host deployment. CWE-798, OWASP A07:2021.
- **Problem:** `DEFAULT_Q_USER` and `DEFAULT_Q_PASSWORD` were a working `chatbotAdmin` pair.
- **Resolution:** both defaults are now `""`, so an unset value fails closed.
- **Leftover:** `compose.dev.yml` did not pass `Q_USER` or `Q_PASSWORD` to the gateway when reviewed. Worth confirming operationally.
- **Status:** 🟢 Fixed (validated 2026-09-03, change not authored by the reviewer).

### CCR-006 — Token-Bearing File URL Forwarded to Redis and RabbitMQ

- **Severity / Standard:** Medium. CWE-522 (closest fit).
- **Problem:** `_resolve_file_url()` produces a URL containing the live bot token, valid for about an hour. It is stored in Redis and sent in the RabbitMQ task payload.
- **Resolution:**
  - Confirmed by search that no log statement emits `media_url`, `image_url`, `video_url` or `file_url`.
  - Propagation itself is unchanged. Removing it needs a new media-proxy feature.
- **Accepted risk:** exposure is bounded by the roughly one-hour validity and the authenticated Redis, RabbitMQ and backend chain. Re-open if that trust boundary changes.
- **Status:** ⚪ Rejected (residual risk accepted, 2026-09-03).

### CCR-007 — Import-Time Side Effects in `main.py`

- **Severity / Standard:** Low. Best practice.
- **Resolution:** directory creation, `setup_logging()`, `logger` and `ShutdownSignal()` moved inside `main()`.
- **Status:** 🟢 Fixed (2026-09-03, applied by the reviewer).

### CCR-008 — Redis Client Had No Socket Timeouts

- **Severity / Standard:** Low. CWE-400 (closest).
- **Resolution:** `REDIS_SOCKET_CONNECT_TIMEOUT` and `REDIS_SOCKET_TIMEOUT` (5s default) are wired into `redis.Redis(...)`. Keepalive and health-check were added as well.
- **Status:** 🟢 Fixed (validated 2026-09-03, change not authored by the reviewer).

### CCR-009 — `utilities/logging.py` Shadowed the Standard Library

- **Severity / Standard:** Low. PEP 8.
- **Resolution:** moved to `logging_setup.py` and updated `main.py` and `README.md`. The old file was first left as a re-export stub, and it has since been deleted (confirmed 2026-10-06).
- **Status:** 🟢 Fixed (2026-09-03, applied by the reviewer).

### CCR-010 — `get_env_int` Fallback Not Clamped

- **Severity / Standard:** Informational. Internal consistency.
- **Resolution:** the invalid-value path now returns `max(minimum, default)`.
- **Status:** 🟢 Fixed (2026-09-03, applied by the reviewer).

### CCR-012 — `reset_session()` Left Drafts and Polls Behind

- **Severity / Standard:** Medium. CWE-459, CWE-664.
- **Problem:** a reset removed task and session keys only. A pending draft could attach pre-reset media to a post-reset task, and an open poll lost its answer.
- **Resolution:**
  - `reset_session()` now also deletes the draft and `session_polls:<chat_id>`.
  - `utils_session/session_reset_handler.py` stops the draft timer and closes open polls before applying.
  - A reset for a chat with open tasks is now deferred.
- **Status:** 🟢 Fixed (validated 2026-09-05, change not authored by the reviewer).

### CCR-013 — Race Between `reset_session()` and `create_task_mapping()`

- **Severity / Standard:** Medium. CWE-362.
- **Problem:** an unsynchronised read-then-delete let a new task escape the reset as an unindexed orphan.
- **Resolution:** both functions now hold `_get_chat_lock(chat_id)`.
- **Limit:** an in-process lock, sufficient for the single-process deployment only. Horizontal scaling would need a Redis transaction or Lua script. This is disclosed in the code.
- **Status:** 🟢 Fixed (validated 2026-09-05, change not authored by the reviewer).

### CCR-014 — Unused `user_id` Assignment

- **Severity / Standard:** Low. CWE-563.
- **Resolution:** the assignment in `message_handler.py::process_message()` was removed.
- **Leftover:** the module header comment still mentions `user_id`. Cosmetic only.
- **Status:** 🟢 Fixed (validated 2026-09-05, change not authored by the reviewer).

### CCR-015 — `create_poll_mapping()` Not Serialised With Reset

- **Severity / Standard:** Low. CWE-362.
- **Resolution:** the write and index step now holds `_get_chat_lock(chat_id)`, like `create_task_mapping()`.
- **Status:** 🟢 Fixed (validated 2026-09-05, change not authored by the reviewer).

### CCR-016 — Implicit "Stop" Inference in `_wait_full_duration()`

- **Severity / Standard:** Low. CWE-670 (closest).
- **Resolution:** explicit checks for `continue` and `stop`, with a logged defensive fallback for any other value.
- **Status:** 🟢 Fixed (validated 2026-09-05, change not authored by the reviewer).

### CCR-017 — Comments Hard-Coded a Default Duration

- **Severity / Standard:** Informational. Comment accuracy.
- **Resolution:** the `Wait 1 min` comments in `_draft_loop()` now describe the setting-derived behaviour.
- **Status:** 🟢 Fixed (validated 2026-09-05, change not authored by the reviewer).

### CCR-018 — Draft Control Dict Mutated Outside `_lock`

- **Severity / Standard:** Informational. CWE-362 (closest).
- **Resolution:** `_stop_draft_loop()`, `continue_draft_timer()` and `_consume_continue()` now mutate `control` fields inside `_lock`. The module header documents the convention.
- **Note:** `poll_response_handler.py` still uses the narrower lock scope. No defect was found there.
- **Status:** 🟢 Fixed (validated 2026-09-05, change not authored by the reviewer).

### CCR-019 — Tier 2 Alert State Lost on Restart

- **Severity / Standard:** Medium. OWASP A09:2021 (closest).
- **Problem:** `_alert_armed` was in memory. The usual fix for a 401 or 404 (new token, restart) reset it, so the paired `gateway_recover` was never sent.
- **Resolution:** the flag is persisted in the Redis key `tier2_alert_armed` and loaded at startup by `load_tier2_alert_state()`.
- **Residual:** if Redis is unreachable at that moment, the flag defaults to armed and an outstanding alert is missed. See CCR-022.
- **Status:** 🟢 Fixed (validated 2026-09-08).

### CCR-020 — Alert and Recover Could Publish Out of Order

- **Severity / Standard:** Medium. CWE-362.
- **Problem:** the state change and the publish were separate steps, so two racing threads could publish in the wrong order. Neither payload carries an ordering field.
- **Resolution:** `_lock` now covers the decision, `set_tier2_alert_armed()` and the publish inside the transition branches.
- **History:** an interim second lock (`_publish_lock`) was rated Partially Resolved (Low) and then replaced, because lock order is scheduler-dependent.
- **Trade-off:** see Accepted Risks.
- **Status:** 🟢 Fixed (validated 2026-09-09).

### CCR-021 — Shared RabbitMQ Publish Channel Used Without a Lock

- **Severity / Standard:** High. CWE-362, CWE-667.
- **Problem:** `_lock_publish` guarded channel acquisition only. `queue_declare()` and `basic_publish()` ran unlocked from many threads, against the module's own stated invariant.
- **Resolution:** `_lock_publish` now wraps the whole retry loop in `queue_push_task()`. No other path to the shared channel exists. The lock graph is a one-way DAG with no deadlock.
- **Trade-off:** see Accepted Risks.
- **Status:** 🟢 Fixed (validated 2026-09-09).

### CCR-022 — Redis Startup Retry Reverted by Default, Undocumented

- **Severity / Standard:** Medium. Docstring accuracy and reliability governance.
- **Problem:** `REDIS_FORCE_INFINITE_RETRY` (default `False`) made Redis give up after one attempt. The docstring still claimed indefinite retry, and the decision log was silent.
- **Resolution:** docstring corrected. `CODE_TODO.md` records the maintainer's dated decision (2026-09-09) to keep `False` for now, with a revisit condition.
- **Open point:** RabbitMQ still retries unconditionally, so the two dependencies behave differently by design.
- **Status:** 🟢 Fixed (validated 2026-09-09).

### CCR-023 — Broad-Sweep Reset Never Resolved on Natural Completion

- **Severity / Standard:** Medium. CWE-697, CWE-393 (closest). Contradicted the documented `README.md` contract.
- **Problem:** `get_pending_reset()` returned `None` both for "no entry" and for an entry with a null `task_id`. Deferred resets for non-triggering chats fell back to the one-hour ceiling.
- **Resolution:** the sweep stores the sentinel `SYSTEM_TRIGGERED_TASK_ID = "system_triggered"`, so `None` always means "no entry". `database.py` needed no change.
- **Note:** `get_pending_reset()` still cannot tell "absent" from a stored literal `None`. No current caller stores one.
- **Status:** 🟢 Fixed (validated 2026-09-12, change not authored by the reviewer).

### CCR-024 — Admin Command Phrase Not Whitespace-Normalised

- **Severity / Standard:** Low. Code consistency.
- **Resolution:** `_is_reset_command()` now normalises the configured phrase the same way as the incoming text.
- **Status:** 🟢 Fixed (validated 2026-09-12, change not authored by the reviewer).

### CCR-025 — Malformed `TZ` Crashed the Process at Import

- **Severity / Standard:** Medium. CWE-248, CWE-755 (closest).
- **Problem:** `get_env_timezone()` caught only `ZoneInfoNotFoundError`. `ValueError` (absolute or `..` keys) and `IsADirectoryError` (for example `TZ=America`) crashed the process before logging started.
- **Resolution:** it now catches `(ZoneInfoNotFoundError, ValueError, OSError)` and falls back to `UTC`. The docstring cites this finding.
- **Status:** 🟢 Fixed (validated 2026-09-12, change not authored by the reviewer).

---

## Findings Summary Table

| ID | Severity | Category | Location | Standard | Status |
|----|----------|----------|----------|----------|--------|
| CCR-001 | High | Security / Logging | `gateway_outbound.py`, `gateway_inbound.py` | CWE-532, CWE-522 | 🟢 Fixed |
| CCR-002 | Medium | Security / Governance | `gateway_inbound.py::poll_updates` | CWE-532 | 🟢 Fixed |
| CCR-003 | Medium → Low | Security / Credentials | `config.py` | CWE-798 | 🟢 Fixed |
| CCR-004 | Medium → Low | Security / Transport | `database.py`, `config.py` | CWE-306 (closed), CWE-319 | 🟡 In Progress |
| CCR-005 | Low | Security / Transport | `queue.py`, `database.py` | CWE-319 | 🟠 Open — Deferred |
| CCR-006 | Medium | Security / Governance | `gateway_inbound.py` | CWE-522 (closest) | ⚪ Rejected |
| CCR-007 | Low | Maintainability | `main.py` | Best practice | 🟢 Fixed |
| CCR-008 | Low | Reliability | `database.py` | CWE-400 (closest) | 🟢 Fixed |
| CCR-009 | Low | Maintainability | `utilities/logging.py` | PEP 8 | 🟢 Fixed |
| CCR-010 | Informational | Maintainability | `config.py::get_env_int` | Consistency | 🟢 Fixed |
| CCR-011 | Low | Reliability | `button_prompt_handler.py` | CWE-400 | 🟠 Open — Deferred |
| CCR-012 | Medium | Reliability / Governance | `database.py::reset_session` | CWE-459, CWE-664 | 🟢 Fixed |
| CCR-013 | Medium | Concurrency | `database.py::reset_session`, `create_task_mapping` | CWE-362 | 🟢 Fixed |
| CCR-014 | Low | Maintainability | `message_handler.py::process_message` | CWE-563 | 🟢 Fixed |
| CCR-015 | Low | Concurrency | `database.py::create_poll_mapping` | CWE-362 | 🟢 Fixed |
| CCR-016 | Low | Maintainability | `image_draft_handler.py::_wait_full_duration` | CWE-670 (closest) | 🟢 Fixed |
| CCR-017 | Informational | Maintainability | `image_draft_handler.py::_draft_loop` | Comment accuracy | 🟢 Fixed |
| CCR-018 | Informational | Concurrency | `image_draft_handler.py` | CWE-362 (closest) | 🟢 Fixed |
| CCR-019 | Medium | Reliability / Monitoring | `error_handling.py`, `database.py`, `initialise.py` | OWASP A09:2021 (closest) | 🟢 Fixed |
| CCR-020 | Medium | Concurrency | `error_handling.py` | CWE-362 | 🟢 Fixed |
| CCR-021 | High | Concurrency | `queue.py::queue_push_task` | CWE-362, CWE-667 | 🟢 Fixed |
| CCR-022 | Medium | Reliability / Documentation | `database.py`, `config.py` | Docstring accuracy | 🟢 Fixed |
| CCR-023 | Medium | Reliability | `session_reset_handler.py`, `database.py::get_pending_reset` | CWE-697, CWE-393 (closest) | 🟢 Fixed |
| CCR-024 | Low | Maintainability | `gateway_inbound.py::_is_reset_command` | Consistency | 🟢 Fixed |
| CCR-025 | Medium | Reliability | `config.py::get_env_timezone` | CWE-248, CWE-755 (closest) | 🟢 Fixed |

---

## Compliance Verdict

### Verdict

**Mostly Compliant**

### Rationale

- No injection, access-control or memory-safety defect is known.
- Both High findings (CCR-001, CCR-021) and every Medium finding except CCR-004 are Fixed.
- CCR-004 is partly fixed. Its TLS half is the same gap as CCR-005.
- Two Low items (CCR-005, CCR-011) are deferred by decision.
- Most fixes were validated against disk and were not authored by the reviewer.

### Remaining Blockers to Compliance

- **CCR-005 and CCR-004 (TLS):** low risk under the closed-network deployment. Revisit if RabbitMQ or Redis is exposed beyond the host.
- **CCR-011:** optional hardening, not a blocker.

### Accepted Risks

- **CCR-005:** cleartext RabbitMQ and Redis traffic, accepted while both stay on the internal `chatbot-app-network`.
- **CCR-006:** the token-bearing media URL is still forwarded to Redis and RabbitMQ. Re-open if the trust boundary changes.
- **CCR-020 and CCR-021 (compounded):**
  - A Tier 2 transition holds `error_handling.py::_lock` through the publish, up to about 30 seconds.
  - If another thread is already mid-retry in `queue_push_task()`, this compounds to about 60 seconds.
  - Every other thread's post-send bookkeeping blocks for that time.
  - This needs RabbitMQ to be down while Telegram delivery is failing or recovering. The maintainer accepted it in `CODE_TODO.md`.
- **CCR-022:** Redis gives up after one startup attempt by default. Revisit if startup-window degradation is observed.
- **CCR-019:** an outstanding alert is missed if Redis is unreachable during startup.
- **CCR-013:** the per-chat lock covers a single process only.

**Classification**
- **Security concern:** CCR-004, CCR-005, CCR-006 (open or accepted). CCR-001, CCR-002, CCR-003 (Fixed).
- **Safety / reliability concern:** CCR-011 (open). CCR-008, CCR-012, CCR-013, CCR-015, CCR-019 to CCR-023, CCR-025 (Fixed).
- **Best-practice recommendation:** CCR-007, CCR-009, CCR-010, CCR-014, CCR-016 to CCR-018, CCR-024 (Fixed).

---

## Change Log

| Date | Change |
|------|--------|
| 2026-09-03 | Initial register created (CCR-001 to CCR-011). Remediation pass applied CCR-001, 002, 007, 009, 010 and mitigated CCR-006. CCR-003, 004, 005, 008, 011 were excluded at the user's request. |
| 2026-09-03 | CCR-003 and CCR-008 re-verified as Fixed. CCR-004 re-verified as partly fixed and downgraded to Low. CCR-005 unchanged. |
| 2026-09-04 | Follow-up review of the `user_id` removal and permanent `session_id` change. Added CCR-012, CCR-013, CCR-014 and the retention note. |
| 2026-09-05 | Follow-up review of the graceful `session_reset` work. CCR-012 and CCR-013 confirmed Fixed. Added CCR-015 and the blank-notice note. |
| 2026-09-05 | Revalidation of open findings. CCR-014 and CCR-015 found Fixed. CCR-005 and CCR-011 unchanged. |
| 2026-09-05 | Follow-up review of the `image_draft_handler.py` behaviour change. Added CCR-016, 017, 018. Two validation passes, the second confirming all three Fixed. |
| 2026-09-08 | Follow-up review of the `gateway_recover` feature. Added CCR-019, 020, 021. Verdict lowered to Partially Compliant. |
| 2026-09-08 | Review of the `database.py` changes. CCR-019 confirmed Fixed. Added CCR-022. |
| 2026-09-09 | Validation passes. CCR-022 Fixed. CCR-020 first rated Partially Resolved (Low), then Fixed after `_lock` was widened. CCR-021 Fixed. Verdict restored to Mostly Compliant. |
| 2026-09-12 | Review of the `session_reset` broad-sweep redesign. Added CCR-023 and CCR-024, then confirmed both Fixed the same day. The reviewer corrected the stale `get_all_pending_resets()` docstring at the user's instruction. |
| 2026-09-12 | Review of the timezone and centralised-time change. Added CCR-025, then confirmed it Fixed the same day. The migration itself was complete with no TZ-dependent scheduling regression. |
| 2026-10-06 | Restructured into point form using the `V-Project-Multimedia-Application` `docker_*` reports as the template. CCR-005, CCR-011 and the CCR-009 clean-up re-checked against source. All 25 findings, severities, standards and statuses kept. Per-pass narrative, evidence listings and the Fix Mode Traceability tables were condensed into the entries above. No code changed. |
