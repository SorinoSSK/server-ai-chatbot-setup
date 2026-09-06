# TODO Record for Bot Sanctuary

## Purpose

`bot_sanctuary` is the successor to `bot_orchestrator`'s routing role, merged with the AI agent pipeline itself — one consolidated Python application rather than a separate orchestrator container plus per-agent containers. It owns: RabbitMQ consumption from `telegram_gateway`, per-session threading, the multi-agent "Call" pipeline (via the Claude Agent SDK), tool access, and error/alert routing.

**Confirmed:** `bot_orchestrator_application` is being retired in favour of this single application. `bot_orchestrator`'s already-planned responsibilities (SMTP alerting, session-reset broadcast, task routing, outbound payload validation — see its own `CODE_TODO.md`) are absorbed here, refined per the sections below.

Status: **Planned, not yet implemented.** Design being drafted across architecture discussion; several items below are proposed and awaiting confirmation, marked accordingly.

---

## 1. Container & runtime

- [ ] Base image: `python:3.x-slim` (not a generic Linux+Node image — see rationale below).
- [ ] `claude` CLI installed via the native installer (`curl -fsSL https://claude.ai/install.sh | bash`) — Node-free, auto-detects host architecture. Used for manual/admin actions only (`claude setup-token`, `claude doctor`), not by the app itself.
- [ ] `claude-agent-sdk` installed via `pip` — used programmatically by the app for the actual session pipeline. Bundles its own native binary per-platform; confirmed wheels exist for `manylinux_2_17_aarch64` (covers Raspberry Pi) and the equivalent x86_64 wheel for the eventual AMD deployment target.
- [ ] **Confirmed:** build as a multi-arch image (Docker Buildx, `--platform linux/amd64,linux/arm64`) — must run on both the AMD64 production host and the Raspberry Pi. Verify post-build on both targets that the SDK resolved a proper wheel (not a source-dist fallback with no bundled binary).
- [ ] `CLAUDE_CONFIG_DIR` set to a path on the secondary disk — used for both relocated logs and the manually-placed OAuth credential (below).

## 2. Authentication — manual, dual-method, no automated injection by default

- [ ] **Confirmed: no automated credential injection as the primary path.** The administrator authenticates personally, either:
  - **Method A — in-container login:** `docker exec` into the container, run `claude setup-token` (loopback port published, or SSH `-L` tunnel if the host is remote), complete the browser step, then manually write the printed token into `${CLAUDE_CONFIG_DIR}/oauth_token`.
  - **Method B — generate elsewhere, place later:** run `claude setup-token` on any other browser-capable device (no container network exposure needed at all), store the token, then `docker exec` in later and write it into the same `${CLAUDE_CONFIG_DIR}/oauth_token` file.
  - **Confirmed: both methods are supported**, resolved by the same credential loader (below) — not an either/or choice baked into the code.
- [ ] Credential resolution order, checked at each `start_new_session()` call:
  1. `CLAUDE_CODE_OAUTH_TOKEN` environment variable, if present (covers a future/optional injection path — not used by default, but the resolver doesn't hard-block it).
  2. Else, read `${CLAUDE_CONFIG_DIR}/oauth_token` from disk.
  3. Else — **container does not crash or exit.** The main process (queue consumer, exec-accessible shell) stays alive; only that specific session request goes into a pending/"waiting for authentication" state until a credential becomes available. Open sub-decision: auto-retry on an interval vs. only re-check on next explicit trigger — not yet decided.
- [ ] **Note (not a container-security boundary):** the OAuth token is a portable bearer credential, not device/container-bound — anyone holding the string can use it from anywhere until expiry/revocation. File permissions on `oauth_token` should be restrictive (`0600`); the secondary disk holding `CLAUDE_CONFIG_DIR` is a meaningful thing to protect/exclude from loosely-handled backups.
- [ ] `setup-token` chosen deliberately over `/login` — avoids the documented `--print` mode OAuth refresh bug (access token expiry ~8h, refresh not persisted correctly in headless/print automation). `setup-token`'s long-lived (1-year) static token sidesteps this.

## 3. RabbitMQ + threading model

- [ ] Main consumer loop reads inbound tasks from RabbitMQ and hands each off to a dedicated thread, which owns that session end-to-end.
- [ ] **Confirmed, corrected from initial assumption:** each thread owns its **own** RabbitMQ connection for publishing its result back to `telegram_gateway` — **not** a single shared connection guarded by a lock.
  - **Why:** verified against Pika's own thread-safety guidance — Pika connections/channels are not thread-safe, and a simple lock around a shared connection's `basic_publish` is explicitly called out as *insufficient* (the connection's I/O loop is tied to the thread that owns it; a lock doesn't fix the cross-thread I/O side effects). The two valid patterns are (a) one connection per thread, created in that thread, or (b) a single loop-owning thread with `add_callback_threadsafe()` dispatch from worker threads. **Per-thread connections (option a) is the adopted approach**, matching the original assumption.
- [ ] **For now:** each thread hosts exactly one agent and fully owns consuming/processing its task. Flagged as a current-phase simplification — expected to evolve as the multi-agent Call model (section 5) matures.

## 4. Error handling — two distinct alert paths

- [ ] Errors **originating from `telegram_gateway`** (Telegram itself unreachable) → routed to **SMTP** (Telegram can't be used to notify the user if Telegram is what's down).
- [ ] Errors **from Claude/the agent backend** (API down) → sent **to `telegram_gateway`** → surfaced to the user via Telegram directly (Telegram itself is presumably fine in this case).
- [ ] Reuses the SMTP alerting groundwork already specified in `bot_orchestrator/CODE_TODO.md` item 1 (`utils_email/email_handler.py`, throttling, non-blocking dispatch) — carried over, not redesigned.

## 5. Agent "Call" model

- [ ] Named roles: **Rukia Call** (entry/default, conversation & routing only), **Architect Call**, **Coder Call**, **Review Call**, **Documentation Call**.
- [ ] Any Call may respond directly or hand off to another Call.
- [ ] Per-thread main loop: if the active Call doesn't resolve the task, hand off to the next Call; that Call can hand back — a bounded back-and-forth ("agent call"), not a strict one-way pipeline.
- [ ] **Corrected — whitelist enforcement moved to `telegram_gateway`, not owned here.** `telegram_gateway` is the only component that actually knows chat_id identity, and it already has the exact precedent pattern (`SESSION_RESET_ALLOWED_CHAT_IDS`, same comma-separated-env-var → `set[int]` style). `bot_sanctuary` does **not** read an env var or perform its own lookup — it trusts an access-tier field stamped onto the inbound task payload by `telegram_gateway` (see follow-up item added to `telegram_gateway/CODE_TODO.md`).
  - A non-whitelisted user's task arrives tagged Rukia-only — no handoff, no access to Architect/Coder/Review/Documentation, effectively a single-agent conversational experience with no repository access (see section 6).
  - A whitelisted user's task arrives tagged for the full Call-handoff graph.
  - **Note the behavioural difference from `SESSION_RESET_ALLOWED_CHAT_IDS`'s pattern:** that whitelist silently drops a disallowed request entirely (log only, no action). This one does not reject anything — the task still proceeds normally, just scoped to Rukia only. It's a tagging/tiering mechanism, not a gate.
- [ ] Each agent gets a defined tool set with explicit specs, so the model can call them directly with no extra glue per tool.

## 6. Workspace / repository access

- [ ] No `session_id`-based folder structure — session IDs are ephemeral and unsuitable as a persistent directory key.
- [ ] **Confirmed — single-user assumption:** the repository directory is wide open to the container; no per-session or per-user filesystem isolation is required.
- [ ] **Confirmed: Rukia has no access to the repository/container filesystem or code tools at all.** It is a conversation/routing-only role. Only the specialised Calls (Architect/Coder/Review/Documentation) get filesystem/tool access. This is also what makes a non-whitelisted user's Rukia-only restriction meaningful as an access boundary, not just a routing default.

---

## Open items, not yet decided

- [ ] Auto-retry interval (or lack thereof) for sessions pending authentication.
- [ ] Exact field name/shape for the access-tier tag on the inbound task payload — depends on `telegram_gateway`'s own whitelist item (see its `CODE_TODO.md`) landing first.
- [ ] Whether the Session Registry (`session_id → role, cwd, permission_scope, status`) persists anywhere or is in-memory-only (same accepted-trade-off `bot_orchestrator` made for its own routing state — not yet confirmed this should carry over identically here, given it affects conversation continuity rather than just message routing).
- [ ] Task classification mechanism (rule-based vs. model-based), carried over unresolved from `bot_orchestrator/CODE_TODO.md` item 4 — still parked.
