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
| **Review Depth** | 3 iterations (initial read, cross-file/context analysis, evidence validation); follow-up pass likewise 3 iterations (structural/data-flow read, cross-file/concurrency analysis, evidence re-validation); second follow-up pass likewise 3 iterations (checklist-vs-code trace, concurrency/lock-symmetry analysis, evidence re-validation); revalidation pass - direct source re-read of every open finding, no assumptions carried over from prior report text |

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

**Total Findings (cumulative):** 17 (1 High, 6 Medium, 7 Low, 3 Informational) - 15 numbered findings (CCR-001–CCR-015) plus 2 unnumbered informational notes (session-identifier retention, 2026-09-04; `RESET_NOTICE_MESSAGE` shipping blank, 2026-09-05).

**Compliance Verdict: Mostly Compliant** (see updated rationale at the end of this document)

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

## Compliance Verdict

**Verdict: Mostly Compliant** (improved from the pre-remediation baseline of the same rating — as of the 2026-09-05 revalidation, no Critical/High/Medium-severity findings remain open; exactly one Low-severity item is genuinely outstanding, alongside one Low-severity accepted risk)

**Rationale:**
The codebase reflects a disciplined, well-documented engineering standard — consistent timeout/retry handling, tiered failure reporting, thread-safety comments backed by correct locking, and thoughtful edge-case handling (album dedupe, orphan sweeps, debounced poll closing). No injection, broken-access-control, or memory-safety issues were identified, and existing HTML-injection risk (`parse_mode="HTML"`) is correctly mitigated at both call sites that use it.

Following this remediation pass, the highest-severity finding (CCR-001, High) and the other logging-hygiene finding (CCR-002) are both resolved and validated, and the token-propagation architectural concern (CCR-006) has been reduced to an explicitly accepted residual risk with its log-leakage angle closed off. A subsequent re-verification (on request) additionally confirmed that CCR-003 and CCR-008 are now resolved and CCR-004 is partially resolved in the current source — changes made outside this session's Fix Mode edits, validated directly against disk rather than assumed. Only CCR-005 and CCR-011 remain outstanding from that pass.

A follow-up review (2026-09-04), scoped to the subsequent `user_id`-removal / permanent `session_id` change, found the removal itself correctly and consistently implemented, but identified two new Medium-severity gaps in the new `session_reset` logic — incomplete cleanup of drafts/polls (CCR-012) and an unsynchronised race between reset and concurrent task creation (CCR-013) — plus one Low code-cleanliness item (CCR-014) and one Informational governance note on session retention. Neither new Medium finding was an injection/access-control-class defect, but both meant a `session_reset` did not yet reliably guarantee the clean-slate boundary the rest of the system's trust model assumes of it.

A second follow-up review (2026-09-05), scoped to `TODO.md`'s subsequent graceful, crash-resilient `session_reset` implementation (built specifically to close CCR-012/CCR-013), confirmed **both Medium-severity findings are now resolved** — verified line-by-line against the new `utils_session/session_reset_handler.py` module and the corresponding `utils_redis/database.py` changes (per-`chat_id` locking, draft/poll-index cleanup, deferral logic), not merely assumed from `TODO.md`'s own checklist. This closes the last Medium-severity findings outstanding in this report. One new Low-severity finding (CCR-015) was identified as a narrower, structurally-similar gap introduced by the same remediation, and CCR-014 remained open at that point, unaddressed (out of scope for that work).

A subsequent revalidation (2026-09-05, same day, on request "revalidate all open CCR") re-checked every finding still marked Open - CCR-005, CCR-011, CCR-014, CCR-015 - directly against current source. **CCR-014 and CCR-015 were both found to have been fixed in the interim**, outside this session's own edits (the unused `user_id` variable removed; `create_poll_mapping()` now holds `_get_chat_lock()` the same way `create_task_mapping()` does). Only **CCR-005** and **CCR-011** remain open as of this revalidation.

**Remaining Blockers to a "Compliant" Verdict:**
1. CCR-005 (Low) — RabbitMQ/Redis connections lack TLS in transit; unchanged, re-confirmed still open on revalidation (2026-09-05). Treated as a low-severity, network-topology-dependent accepted risk under the same closed-host deployment context validated for CCR-003, rather than a hard blocker.
2. CCR-011 (Low) — `_registered_callbacks` has no hard size cap; re-confirmed still open on revalidation (2026-09-05). **[Skipped at the user's request during the 2026-09-03 remediation pass; not examined again since]**

**Resolved / no longer blocking:**
- ~~CCR-003~~ (Medium → n/a) — RESOLVED (validated 2026-09-03). Hard-coded functional default credential removed from source.
- ~~CCR-004~~ (Medium → Low) — PARTIALLY RESOLVED (validated 2026-09-03). Authentication capability (CWE-306) added; TLS (CWE-319) still tracked under CCR-005.
- ~~CCR-008~~ (Low → n/a) — RESOLVED (validated 2026-09-03). Socket/connect timeouts added.
- ~~CCR-012~~ (Medium → n/a) — RESOLVED (validated 2026-09-05). `reset_session()` now clears the chat's draft and poll indexing; the new `utils_session` module stops the draft timer and closes any still-open poll before a reset applies.
- ~~CCR-013~~ (Medium → n/a) — RESOLVED (validated 2026-09-05). `create_task_mapping()` and `reset_session()` are now serialised per `chat_id` via `_get_chat_lock()`.
- ~~CCR-014~~ (Low → n/a) — RESOLVED (validated 2026-09-05, revalidation pass). Unused `user_id` assignment removed from `message_handler.py::process_message()`.
- ~~CCR-015~~ (Low → n/a) — RESOLVED (validated 2026-09-05, revalidation pass). `create_poll_mapping()` now holds `_get_chat_lock(chat_id)` across its write+index step, mirroring `create_task_mapping()`.

No Critical/High/Medium-severity findings remain open in this report as of 2026-09-05. Exactly two Low-severity items remain (CCR-005, an accepted risk; CCR-011, unaddressed/skipped) - neither requires a behavioural/architectural rewrite, and both remain addressable as scoped, targeted fixes whenever the user chooses to action them.

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

---

*This report was originally a static, evidence-backed review; a subsequent revision additionally recorded an instructed remediation pass. All code changes were scoped to the minimum necessary to resolve each targeted finding, preserving existing behaviour. Where confidence is Medium (deployment-context-dependent findings), assumptions are stated explicitly within the relevant finding. A further follow-up review (2026-09-04) is appended above (CCR-012–CCR-014 and one informational note), scoped to the `user_id`-removal / permanent `session_id` change — review-only, no code modified, no Fix Mode entered. A second follow-up review (2026-09-05) is appended above (CCR-012/CCR-013 confirmed resolved, CCR-014 re-confirmed open, CCR-015 and one further informational note added), scoped to `TODO.md`'s graceful `session_reset` implementation — review-only, no code modified, no Fix Mode entered; the CCR-012/CCR-013 remediation itself was not authored in this session. A subsequent revalidation pass (2026-09-05, same day) re-checked every then-open finding (CCR-005, CCR-011, CCR-014, CCR-015) directly against current source; CCR-014 and CCR-015 are now confirmed resolved (also not authored in this session), leaving only CCR-005 and CCR-011 open — review-only, no code modified, no Fix Mode entered.*
