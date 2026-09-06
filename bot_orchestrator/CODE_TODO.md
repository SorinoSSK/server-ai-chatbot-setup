# TODO Record for Bot Orchestrator

## Duplicate RabbitMQ + logging infrastructure from Telegram Gateway

Status: **Done.** Private-function naming parity applied; verified against every Telegram Gateway CCR finding in scope for this infrastructure (`CODE_NON_COMPLIANCE.md`) — all already satisfied.

### Goal

Bring up `bot_orchestrator`'s RabbitMQ (queue) and logging foundation by duplicating the equivalent, already-hardened infrastructure from `telegram_gateway`, so both applications share the same connection-handling, retry, and logging conventions.

### What was duplicated

- [x] `config.py` — Queue Connection block (`Q_HOST`/`Q_USER`/`Q_PASSWORD`/`Q_PORT`/`Q_VHOST`/`Q_CHANNEL_IN`/`Q_CHANNEL_OUT`/`Q_PUSH_*`/`Q_CONSUME_*`), `get_env_int()`, Application Loggings block (`LOG_DIR`/`LOG_FILE`/`LOG_LEVEL`/`LOG_MAX_SIZE_MB`/`LOG_RETENTION_DAYS`) — carried over already reflecting `telegram_gateway`'s remediated state (empty-string `DEFAULT_Q_USER`/`DEFAULT_Q_PASSWORD` per CCR-003, `get_env_int()`'s exception-path clamping per CCR-010).
- [x] `utilities/logging_setup.py` — console + daily/size-based rotating file handler, identical to `telegram_gateway`'s post-CCR-009 version (never shadowed `logging.py` here, so no rename history applies).
- [x] `utilities/utils_queue/queue.py` — dual publish/consume connections, per-connection locks, retrying `queue_push_task()`, reconnecting `queue_consume_task()` consumer loop with per-message attempt tracking, `start_queue_consumer()`/`stop_queue_consumer()`.
- [x] `utilities/utils_queue/message_handler.py` — `process_message()` stub (JSON parse/validate, log-only). Deliberately minimal — orchestration/dispatch-by-`type` logic hasn't been defined yet for this application, per the file's own header Notes. Not a duplication gap.
- [x] `utilities/utilities.py` — `ShutdownSignal` (`threading.Event` wrapper), identical to `telegram_gateway`.
- [x] `utilities/initialise.py`, `main.py` — startup/shutdown wiring (`initialise_rabbitmq_connection()`, `start_queue_consumer()` / `stop_queue_consumer()`, `close_rabbitmq_connection()`), signal handling, same structure as `telegram_gateway`.

### Private-function naming parity — done

`telegram_gateway/utilities/utils_queue/queue.py`'s internal-only connection helpers were converted to a leading-underscore (private) naming convention in a later pass (same wave as the `utils_redis` conversion — see git history). `bot_orchestrator`'s copy predated that pass; now matched:

- [x] `initialise_rabbitmq_publish_connection()` → `_initialise_rabbitmq_publish_connection()`
- [x] `initialise_rabbitmq_consume_connection()` → `_initialise_rabbitmq_consume_connection()`
- [x] `get_rabbitmq_publish_channel()` → `_get_rabbitmq_publish_channel()`
- [x] `get_rabbitmq_consume_channel()` → `_get_rabbitmq_consume_channel()`

Confirmed via `grep`, both before and after the rename, that none of these four are imported/used outside `queue.py` itself — only `initialise_rabbitmq_connection()`, `close_rabbitmq_connection()`, `start_queue_consumer()`, `stop_queue_consumer()` are imported elsewhere (`utilities/initialise.py`), so all four internal call sites within `queue.py` were updated with no other file affected.

### Verified against every applicable Telegram Gateway CCR finding

Cross-checked `bot_orchestrator`'s duplicated `config.py`/`main.py`/`logging_setup.py`/`utils_queue/*` against every finding in `telegram_gateway/CODE_NON_COMPLIANCE.md` whose location falls within this same RabbitMQ/logging scope. Findings outside this scope (Telegram-specific: CCR-001, CCR-002, CCR-006, CCR-011; Redis-specific: CCR-004, CCR-008, CCR-012, CCR-013, CCR-015; draft-timer-specific: CCR-016–CCR-018) don't apply — `bot_orchestrator` has no Telegram or Redis integration yet.

| CCR | Finding | Status in `bot_orchestrator` |
|---|---|---|
| CCR-003 | Hard-coded functional `Q_USER`/`Q_PASSWORD` default | Already matches resolved state — `DEFAULT_Q_USER`/`DEFAULT_Q_PASSWORD` are `""` (fail-closed), not a working credential. |
| CCR-005 | No TLS on the RabbitMQ connection | Same open, accepted-risk status as `telegram_gateway` (Low, network-topology-dependent) — no TLS here either, consistent, not a regression. |
| CCR-007 | Import-time side effects (`mkdir`/`setup_logging()` at module level) | Already matches resolved state — `main.py`'s `main()` performs all setup; nothing runs on import. |
| CCR-009 | Logging module named `logging.py`, shadowing the stdlib | Not applicable — this app's logging module was created directly as `logging_setup.py`, never had the shadowing name. |
| CCR-010 | `get_env_int()`'s exception path not clamped to `minimum` | Already matches resolved state — `except ValueError: return max(minimum, default)`. |
| CCR-014 | Unused `user_id` variable in `message_handler.py::process_message()` | Not applicable — `process_message()` here is a minimal stub with no `user_id` reference at all. |

No new findings identified in this scope. `bot_orchestrator`'s RabbitMQ/logging foundation is at full parity with `telegram_gateway`'s current (post-remediation) state.

---

## Orchestration features — SMTP alerting, session reset, task routing, upward validation

Status: **Planned, not yet implemented.** Design refined and confirmed against user answers below; item 2 and item 4's classification mechanism are deliberately parked (see their own sections). Everything else here is ready to build.

### Prerequisite — state store (in-memory, no Redis)

- [ ] `bot_orchestrator` keeps its own routing/correlation state as an **in-memory dict guarded by a lock** (same pattern as `telegram_gateway`'s `_active_drafts`/`_registered_callbacks` — lightweight in-process state, not the durable Redis registry pattern used there for task/session mapping). **Confirmed: no Redis for `bot_orchestrator`.**
- [ ] **Accepted trade-off, documented on purpose:** a `bot_orchestrator` restart loses all in-flight `task_id → (chat_id, routing target)` correlation — any backend reply for a task dispatched before the restart can no longer be routed back. If this later proves unacceptable, the fix is "add Redis," not a redesign — not doing that now per explicit instruction.

### 1. SMTP email alert on error — scope: Tier 2 connectivity only

- [ ] New `utils_email/email_handler.py` + config block: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USE_TLS`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_ADDRESS`, `SMTP_TO_ADDRESSES` (comma-separated, same parsing pattern as `TELEGRAM_ALLOWED_CHAT_IDS`), `SMTP_MIN_INTERVAL_SECONDS` (throttle, so a retry storm sends one email, not one per attempt).
- [ ] **Confirmed trigger scope — exactly two conditions, nothing else:**
  - Connection to the **AI agent backend** is down (retries exhausted).
  - Connection to **`telegram_gateway`** is down (retries exhausted).
- [ ] **Confirmed non-triggers (log only, no email):** unknown/unauthorised access attempts (same pattern as `telegram_gateway/utils_gatekeeper/gatekeeper.py`'s logging), ordinary conversational (Tier 1) errors, outbound-payload validation failures (item 6).
- [ ] Mechanism: hook into `queue.py`'s existing retry-exhaustion points (`queue_push_task()` already returns `False` once `Q_PUSH_MAX_ATTEMPTS` is exhausted; the consume-side reconnect loop already logs each retry). Distinguishing "AI down" from "Telegram down" requires **separate outbound queues per direction** — this arrives naturally with item 4's routing (one queue/queue-set to `telegram_gateway`, one/more to the AI/agent side). Until the AI-side queue exists, only the Telegram-direction alert is wireable.
- [ ] Must not block the RabbitMQ consumer thread — wrap the SMTP call in its own timeout, catch-and-log, never re-raise into the consume loop.

### 2. Per-chat_id / per-session routing to a different bot — **parked**

- [ ] No design committed yet — more research needed (per explicit instruction). Placeholder only; revisit before building item 4's full routing table, since the two are likely related.

### 3. Push `session_reset` — two trigger paths, one shared broadcast function

- [ ] **User-defined path:** new inbound message type from `telegram_gateway` (proposed `type: "reset_request"`, carrying `chat_id`) — kept distinct from the existing `session_reset` type so `telegram_gateway`'s current consumer contract needs no change. `bot_orchestrator` receives it and initiates the broadcast below.
  - [ ] **Cross-service dependency, not `bot_orchestrator`'s to build alone:** `telegram_gateway` has no user-facing button/command yet to *send* `reset_request`. Flag as a follow-up item in `telegram_gateway/CODE_TODO.md` once this side is settled.
- [ ] **Time-defined path:** a background thread, started only if `SESSION_RESET_DAILY_ENABLED` (env var) is true, firing a daily broadcast at a configured `SESSION_RESET_DAILY_TIME`. **Open sub-question:** server-local time or a specific timezone setting (`SESSION_RESET_DAILY_TIMEZONE`)? Assuming UTC unless told otherwise.
- [ ] Both paths converge on one function, `broadcast_session_reset(chat_id: int | None)` — `None` for the daily global reset (every chat), a specific `chat_id` for the user-defined one — which fans the `session_reset` payload out to a **config-driven list of target queues** (`SESSION_RESET_BROADCAST_TARGETS`). Starts with just `telegram_gateway`'s inbound queue; extensible later once Agent/Debate-side containers exist and need the same signal (per `AI_AGENT_ARCHITECTURE.md`).

### 4. Task classification (code / normal response / websearch) — mechanism parked, routing contract scaffolded

- [ ] Per `AI_AGENT_ARCHITECTURE.md`, `bot_orchestrator` functionally fills the document's **Debate Orchestrator** role, generalised beyond just code: `"code"` routes into the Agent A/B debate pipeline described there; `"normal response"` and `"websearch"` are lighter paths that bypass debate entirely.
- [ ] **Classification mechanism deliberately not decided yet** (rule-based vs. model-based) — per explicit instruction. Scaffold around it with a stub classifier (e.g. always returns `"chat"`) so the routing/dispatch plumbing (item 5) isn't blocked; swap the stub for a real implementation later without touching the surrounding code.
- [ ] Proposed routing contract: three labels → three outbound targets (`Q_CHANNEL_OUT_CODE` / `Q_CHANNEL_OUT_CHAT` / `Q_CHANNEL_OUT_WEBSEARCH`, naming open to change).
- [ ] **Confirmed:** an unknown/unauthorised user/chat_id attempting access is logged only, never raised to SMTP (see item 1).

### 5. Full downward + upward passthrough to `telegram_gateway`

- [ ] **Downward:** inbound task → classify (4, stub for now) → record `task_id → (chat_id, target)` in the in-memory state store (prerequisite) → push to the resolved queue.
- [ ] **Upward:** inbound agent reply → look up `task_id` → validate (6) → push to `telegram_gateway`'s inbound queue in its documented per-`type` shape (`README.md`'s payload contract).

### 6. Outbound payload validation before pushing upward

- [ ] `validate_outbound_payload(payload: dict) -> bool` (or raise-based), checked immediately before every upward `queue_push_task()`, mirroring `telegram_gateway/README.md`'s contract per `type` (`poll` needs `question`/`options`; `image`/`video`/`file` need `url`; `album` needs a valid `items` list; `text` needs `message` and well-formed `buttons` rows if present; `error` needs `error_type`; `session_reset` needs `chat_id`).
- [ ] A payload that fails validation is logged and dropped, not sent — same "don't requeue a deterministically-bad message" philosophy already used elsewhere in this codebase.
- [ ] **Confirmed:** a validation failure here is log-only, not an SMTP trigger (see item 1's confirmed non-triggers).
