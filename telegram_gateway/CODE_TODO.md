# TODO Record for Telegram Gateway

## BUG — `SESSION_RESET_ALLOWED_CHAT_IDS` implements self-service per-chat reset, not admin-triggered global reset

Status: **Design finalised (2026-09-11) - admin command ("Rukia refresh yourself") + `session_clear_request`/`session_reset` round-trip with `bot_sanctuary`. Corrected 2026-09-12 - the 2026-09-11 design wrongly modelled `bot_sanctuary` publishing one `session_reset` per session, after finishing; see "Confirmed design correction" below. Parts 0, 1, 2, 4, and 5's `telegram_gateway` side all implemented 2026-09-12 (`_is_reset_allowed()` removal included - pulled forward ahead of Part 4; two defensive hardening fixes also added post-implementation, see Part 4's "Post-implementation hardening"). `telegram_gateway`'s entire side of this feature is now implemented, plus one `telegram_gateway`-side-only correction to `session_cleared` (`chat_id` dropped from its payload - see Part 3's own subsection below; full retirement of that event now unblocked but still not done, see that subsection). Both Part 3 and Part 5 are now implemented on both sides (2026-09-12) - `bot_sanctuary`'s `session_clear_request` accept/reject/`retire()` handling and its `bot_started` broadcast are both done, in `bot_sanctuary`'s own codebase, tracked in full in `bot_sanctuary/CODE_TODO.md`. This entry's entire designed behaviour is now implemented across both codebases. A handful of small, non-blocking follow-ups remain open on `bot_sanctuary`'s side (documentation, two narrow unbackstopped-failure gaps, one bounded edge case) - see that file's own "Part 3 — post-implementation review" subsection, not duplicated here.** Supersedes the "Must fix" list this entry originally carried (2026-09-10) - kept below, marked superseded, for history.

### Confirmed requirement (authoritative - given directly by user, must not change)

- `SESSION_RESET_ALLOWED_CHAT_IDS` identifies the bot admin(s) - the group of individuals permitted to trigger a **global** reset of every session the bot is currently holding, not a self-service reset of their own chat. The env var's name is confirmed correct as-is - only its enforcement scope/target was wrong.
- No `chat_id` may reset its own session on request, with exactly two legitimate paths to a session ever being cleared:
  1. The admin/owner (a `chat_id` in `SESSION_RESET_ALLOWED_CHAT_IDS`) triggers the global reset - their own session is cleared as part of that same action too, incidentally, since "every session" includes their own, not because self-service reset exists as its own separate path.
  2. ~~A future fixed/scheduled reset time configured in `bot_sanctuary` - an automatic, time-based reset, not user-triggered at all, not yet designed on either side (see Open Questions below, and the corresponding new entry in `bot_sanctuary/CODE_TODO.md`).~~ **Implemented 2026-09-12, entirely on `bot_sanctuary`'s side (`SESSION_RESET_TIME`) - see that file's own "NEW — `session_clear_request` handling" entry, "Timed session reset" subsection, and Open Question 4 below.** `telegram_gateway` has no involvement in triggering it at all, by design - it only ever reacts to whichever `session_reset` scenario produced it, exactly like any other. A first attempt wrongly built this on `telegram_gateway`'s side instead (routed via `session_clear_request`, as if an external admin had triggered it); caught and fully reverted once re-reading this very entry surfaced the conflict - see `bot_sanctuary/CODE_TODO.md`'s own subsection for that history.
- `coding_allowed` (`bot_sanctuary`'s agent-call access tier - full Call-handoff graph vs. Chat-only, see `## Agent-call access tier` below) is a **separate** concern from admin/reset privilege, confirmed by the user. It gets its own dedicated whitelist env var, decoupled from `SESSION_RESET_ALLOWED_CHAT_IDS` entirely. **The same group of individuals is expected to hold both today** - that's a coincidence of who the user currently trusts with each privilege, not a structural requirement that the two lists must ever be kept in sync.

### Symptom / current (incorrect) behaviour

- `session_reset_handler.py::_is_reset_allowed(chat_id)` checks whether the **requesting chat's own** `chat_id` is in `SESSION_RESET_ALLOWED_CHAT_IDS`.
- `handle_session_reset_request(task_id, chat_id)` / `_apply_session_reset(chat_id)` then only ever clears **that same chat's own** session - `reset_session(chat_id)` is entirely single-`chat_id`-scoped, by construction.
- Net effect as built: a whitelisted chat can clear only its own session; a non-whitelisted chat can clear nothing. There is no "reset every session currently held" action anywhere in the codebase today - no function enumerates active sessions at all (`utils_redis/database.py` has no `session:*` equivalent of `get_all_chat_draft_ids()`/`get_all_poll_ids()`'s existing `SCAN`-based sweep).
- `## Agent-call access tier` (below) then inherited the same conflation by deliberately reusing this same whitelist for `coding_allowed`, reasoning "a chat_id permitted to trigger a session_reset is treated as the same tier permitted full agent-call access" - a reasonable-sounding shortcut once `SESSION_RESET_ALLOWED_CHAT_IDS` is (mis)understood as a self-service permission, but not what was actually meant to be tied together once its correct admin/global meaning is restored.

### Root cause

`_is_reset_allowed()`/its whitelist were modelled directly on `TELEGRAM_ALLOWED_CHAT_IDS`'s existing pattern - see the original §7 Goal note further below: *"Same precedent as TELEGRAM_ALLOWED_CHAT_IDS... comma-separated env var -> set[int]."* That pattern answers "does this `chat_id` get to do X to itself?", which is correct for `TELEGRAM_ALLOWED_CHAT_IDS` (may this chat talk to the bot at all) but was never actually correct for an admin-triggers-a-global-action whitelist - the check needs to gate on the *requester's* identity while the *effect* fans out to every chat, not just the requester's own. That distinction was never drawn during the original implementation; the existing single-chat-scoped pattern was reused wholesale instead of designed against the actual admin/global requirement.

### Must fix (2026-09-10 draft) - superseded by "Confirmed design" below, kept for history

The core diagnosis (Confirmed requirement/Symptom/Root cause above) is unchanged and still authoritative. This specific remediation list - built around `telegram_gateway` itself enumerating every `chat_id` and applying a reset to all of them directly - was superseded on 2026-09-11 once the actual trigger mechanism (an in-chat admin command) and the cross-service split with `bot_sanctuary` were worked out. See "Confirmed design" below for what's actually being built.

- [x] ~~Add a chat_id-enumeration primitive... needed since nothing today can answer "which chat_ids currently hold a session."~~ **Superseded** - `telegram_gateway` still gets an enumeration primitive (Part 0 below), but as a targeted `session_id -> chat_id` reverse lookup driven by `bot_sanctuary`'s own per-session `session_reset` publishes, not a bulk "list every chat_id" sweep applied all at once from this side.
- [x] ~~Rework `handle_session_reset_request()`'s whitelist check to gate on the requester's own chat_id, then apply to every chat_id from the enumeration primitive.~~ **Superseded** - `bot_sanctuary`, not `telegram_gateway`, now decides and iterates which sessions get cleared (see Part 3/"Confirmed design" below). `telegram_gateway` no longer needs to fan a single admin request out to every chat_id itself.
- [x] ~~Work through the deferred-vs-immediate logic per affected chat_id individually.~~ **No longer a distinct concern** - §0-§8's existing per-`chat_id` deferred logic is left completely untouched (see Part 4 below); it already handles one `chat_id` at a time correctly, and nothing in the new design asks it to do anything different.
- [x] ~~Confirm the resulting end state has no other self-service reset path.~~ **Still true, unchanged** - see "Confirmed design" below; the only trigger is the whitelisted admin command.
- [ ] `## Agent-call access tier` (below): still open, unchanged by this redesign - see its own entry.
- [ ] README.md's `session_reset` documentation - still needs the rewrite, now against the design below instead.

### Confirmed design (2026-09-11, superseding an earlier 2026-09-11 draft of this same section) — corrected 2026-09-12, see "Confirmed design correction" below

New user-facing trigger: a whitelisted chat sends the literal text **`"${BOT_NAME} refresh yourself"`** - `${BOT_NAME}` interpolated from `settings.TELEGRAM_BOT_NAME` (the same variable already used for `RESET_NOTICE_MESSAGE` and every other persona-name string in this codebase), not a literal, hardcoded name. "Rukia" in earlier drafts of this entry was this project's own example persona, not the literal string to match.

- `telegram_gateway` owns: detecting the command, gating it against `SESSION_RESET_ALLOWED_CHAT_IDS` on the **requesting** `chat_id`, ~~resolving `session_id -> chat_id` itself using its own existing Redis state~~ (**superseded 2026-09-12** - no `session_id` resolution exists anywhere in the corrected design; see below), and independently enumerating and attempting every chat_id it knows about on its own, rather than being told targets by `bot_sanctuary`.
- `bot_sanctuary` owns: deciding whether to accept or ignore the request, clearing its own session state, and ~~notifying `telegram_gateway` per session as each is actually cleared~~ (**superseded 2026-09-12** - notifies `telegram_gateway` **once**, at the moment it *begins* the reset, not per session and not after finishing; see below). `bot_sanctuary` stays chat-agnostic throughout. Full entry: `bot_sanctuary/CODE_TODO.md`.
- **Rejected intermediate design:** `bot_sanctuary` enumerating every active `session_id` and handing `telegram_gateway` an explicit target list. Rejected by the user - `telegram_gateway` already owns the `chat_id <-> session_id` mapping and should resolve/enumerate targets itself.
- **No cross-process recovery of a `bot_sanctuary`-side sweep, deliberately.** Once `bot_sanctuary` consumes/acks a RabbitMQ message, its content is gone if the process crashes before finishing - there is nothing to "resume." `bot_sanctuary`'s own in-progress-sweep tracking is therefore plain in-memory, lost on any restart, with no attempt to persist or recover it. Reconciling anything left waiting on `telegram_gateway`'s side after such a crash is entirely `telegram_gateway`'s job, driven by a new `bot_started` signal (Part 5) - not something `bot_sanctuary` tries to do itself.

Original flow diagram (2026-09-11) - **superseded by the corrected diagram below, kept for history**:

```text
Whitelisted chat: "${BOT_NAME} refresh yourself"
        |
telegram_gateway: detect command, check SESSION_RESET_ALLOWED_CHAT_IDS (requester),
mint a real task_id for it (same as any other message)
        | (whitelisted)                                  | (not whitelisted)
push "session_clear_request" (task_id, chat_id)      treat as normal text,
        |                                             _push_task() as usual
bot_sanctuary: sweep already in progress?
  yes -> IGNORE: send literal completed/error for the incoming task_id, stop.
  no  -> mark sweep in progress (snapshot every session_id in the registry),
         signal every one of them AT ONCE (concurrent, not sequential)
        |
  EACH session, independently, on its own thread:
    finish current turn naturally (no abandonment, dedicated new method -
    not shutdown()/stop()) -> clear own local state -> publish
    "session_reset" (session_id, task_id: <last task_id, if any>)
    -> log + report in; sweep-in-progress clears once every
    snapshotted session has reported in once
        |
telegram_gateway, on receiving ANY session_reset:
  resolve chat_id (task_id if present -> existing mapping; else session_id
  -> new lookup, Part 0). If task_id present, close it exactly like a
  completed/error would (this message doubles as that signal - no
  separate completed/error is sent for the accepted/normal path at all).
  THEN: independently enumerate every chat_id it knows about (its own
  Part 0 primitive) and attempt the existing, unchanged
  handle_session_reset_request()/has_open_tasks() logic for each one -
  concurrently, no chat blocks another, each one deferred/applied purely
  on its own open-task state. Idempotent - safe to re-run on every arrival.
        |
if bot_sanctuary restarts (crash or redeploy) before finishing:
  it fires "bot_started" unconditionally on every startup (Part 5) ->
  telegram_gateway force-resolves every still-pending chat directly via
  _apply_session_reset() (NOT _force_apply_session_reset() - see Part 5)
```

### Confirmed design correction (2026-09-12) - one `session_reset` per trigger, sent at accept-time, no `session_id` resolution

Corrects two mistakes in the 2026-09-11 diagram above, both caught by the user directly:

1. **`bot_sanctuary` never publishes `session_reset` per session.** There is exactly **one** `session_reset` per trigger - whichever of the two scenarios below caused it - never one per session in a sweep. The "EACH session, independently... publish session_reset" step above never existed as a real requirement; it was this entry's own misreading of the original instruction, which was explicit: "session_reset is isolated... there should not be an indication for bot_sanctuary to inform telegram_gateway one by one."
2. **`bot_sanctuary` sends that one `session_reset` when it *begins* handling the reset, not after it finishes clearing every session it holds.** Waiting until fully done before ever telling `telegram_gateway` would force the two sides to run sequentially (`bot_sanctuary` finishes its own graceful per-session termination first, only then `telegram_gateway` starts its own) instead of concurrently (each side runs its own graceful completion independently, in parallel) - "it will decouple session_reset sync," in the user's own words.

**The two scenarios that produce a `session_reset`, restated:**

1. **User-triggered** (the admin "refresh yourself" command, Part 1/2 below) - `telegram_gateway` mints a `task_id` for the triggering message, sends `session_clear_request`, `bot_sanctuary` accepts and immediately sends `session_reset` back **carrying that same `task_id`** (before it has finished clearing anything).
2. **`bot_sanctuary`-triggered** (the still-undesigned future fixed/scheduled reset - see "Confirmed requirement" #2 above) - not user-initiated at all, so there is no `task_id` to carry. `bot_sanctuary` sends `session_reset` with `task_id: null`.

**`telegram_gateway`'s handling of `session_reset` is identical in both scenarios except for one step:**
- If `task_id` is present (scenario 1 only): resolve `chat_id` via the **existing** `get_task_mapping(task_id)` - the same resolution every other message type already uses, nothing new - and close that `task_id` out exactly like a `completed`/`error` would.
- Regardless of scenario: independently enumerate every `chat_id` it knows about (`get_all_session_chat_ids()`) and attempt the existing, unchanged `handle_session_reset_request()`/`has_open_tasks()` logic for each one - concurrently, no chat blocks another, each deferred/applied purely on its own open-task state. Idempotent - safe to re-run on every arrival.

**No `session_id -> chat_id` resolution exists anywhere in the corrected design.** There is never a case where `telegram_gateway` needs to identify "the one chat this `session_reset` targets," because the action is never scoped to a single chat - it's always either "close this one `task_id`, then sweep everyone" or just "sweep everyone." `session_id` is dropped from the payload entirely - confirmed by the user as serving no purpose on `telegram_gateway`'s side.

Corrected flow diagram:

```text
Whitelisted chat: "${BOT_NAME} refresh yourself"          bot_sanctuary's own future
        |                                                  scheduled/automatic reset
telegram_gateway: detect command, check                   (not user-triggered, not yet
SESSION_RESET_ALLOWED_CHAT_IDS (requester),                designed - see "Confirmed
mint a real task_id for it (same as any                    requirement" #2 above)
other message)                                                     |
        | (whitelisted)          | (not whitelisted)                |
push "session_clear_request"   treat as normal text,                |
(task_id only - bot_sanctuary   _push_task() as usual                |
 stays chat-agnostic)                                                |
        |                                                            |
        v                                                            v
bot_sanctuary: sweep already in progress?
  yes -> IGNORE: send literal completed/error for the incoming task_id (scenario 1
         only - scenario 2 has none to close), stop.
  no  -> mark sweep in progress, publish "session_reset" IMMEDIATELY
         (task_id: <the triggering task_id> for scenario 1, null for scenario 2)
         -> THEN begin gracefully finishing/clearing every session it holds
        |
telegram_gateway, on receiving ANY session_reset:
  if task_id present -> resolve chat_id via existing get_task_mapping(), close
  it exactly like a completed/error would (this message doubles as that signal -
  no separate completed/error is sent for the accepted/normal path at all).
  THEN, regardless: independently enumerate every chat_id it knows about (Part 0's
  get_all_session_chat_ids()) and attempt the existing, unchanged
  handle_session_reset_request()/has_open_tasks() logic for each one -
  concurrently, no chat blocks another, each deferred/applied purely on its own
  open-task state. Idempotent - safe to re-run on every arrival.
        |
if bot_sanctuary restarts (crash or redeploy) before finishing:
  it fires "bot_started" unconditionally on every startup (Part 5) ->
  telegram_gateway force-resolves every still-pending chat directly via
  _apply_session_reset() (NOT _force_apply_session_reset() - see Part 5)
```

#### Part 0 — `chat_id` enumeration

Status: **Re-implemented 2026-09-12 against the "Confirmed design correction" above - see the reverted/kept breakdown below.**

- [x] New `utils_redis/database.py` primitive: `get_all_session_chat_ids() -> list[int]` - `SCAN`-based enumeration of every `chat_id` currently holding a `session:<chat_id>` entry, same shape/style as `get_all_chat_draft_ids()`/`get_all_poll_ids()`. Still needed and still correct as originally added (2026-09-11) - this is exactly what Part 4's broad sweep enumerates over in both scenarios. Not yet called from anywhere as of this entry - Part 4 itself is still not implemented.
- [x] ~~`get_chat_id_for_session(session_id) -> int | None` - `SCAN`-based reverse lookup over `session:*`, used for the `task_id`-absent case.~~ **Reverted (2026-09-12).** Built on the mistaken belief that an absent `task_id` meant "resolve which single chat this targets" - it doesn't; an absent `task_id` means "nothing to close, go straight to the broad sweep" (see "Confirmed design correction" above). No code path ever needs a `session_id -> chat_id` lookup. Removed from `database.py` entirely.
- [x] ~~`process_message()` reads `data.get("session_id")` and passes it through to `_handle_session_reset()`.~~ **Reverted (2026-09-12).** `session_id` is dropped from the payload design entirely - confirmed by the user as serving no purpose here. `process_message()`'s `session_reset` branch still dispatches ahead of the shared `task_id`/`get_task_mapping()` gate (that part was correct and is kept - `session_reset` is still the one type that may carry no `task_id`); it just no longer reads or forwards a `session_id`.
- [x] `_handle_session_reset()` / `handle_session_reset_request()` signatures - **corrected 2026-09-12: `task_id: str | None` only, no second `session_id` parameter.** `handle_session_reset_request()` resolves `chat_id` via the existing `get_task_mapping(task_id)` when `task_id` is present; when absent, it resolves nothing and simply skips the close-a-task step, falling straight through to whatever Part 4's broad sweep does (not yet implemented) - there is no fallback resolution step of any kind.
  - [x] `_is_reset_allowed()` - **removed outright, 2026-09-12 - pulled forward ahead of Part 4, see below.** Challenged directly by the user: "why is this still blocking?" - correctly so. It was never just a forward-looking cleanup item; it was actively wrong *today*, independent of anything else in this entry. An inbound `session_reset` always originates from `bot_sanctuary` itself (never directly from a chat), so there was nothing left to re-verify by the time it reached this function - and worse, `bot_sanctuary`'s already-shipped `resync_orphaned_sessions()` crash-recovery sweep sends a `session_reset` for **any** orphaned session regardless of chat, so this check was silently dropping crash-recovery resets for every non-whitelisted (i.e. non-admin) chat - a live instance of this entry's own "Symptom" section, not a hypothetical one. Removing it didn't need to wait for Part 4's broad sweep to exist first - the two were only bundled together in the original Part 4 draft because they were drafted at the same time, not because one depends on the other. `SESSION_RESET_ALLOWED_CHAT_IDS` itself is untouched and still has a job - gating Part 1's command-detection gate, not this function.
  - `set_pending_reset()`/`get_all_pending_resets()` (`database.py`) and `_force_apply_session_reset()` (`session_reset_handler.py`) keep their `task_id: str | None` widening from the 2026-09-11 pass - **still needed, for a different reason than originally stated**: once Part 4's broad sweep exists, every `chat_id` *other than* the one (if any) tied to the triggering `task_id` has no `task_id` of its own to store against its own deferred reset - not because of any `session_id`-only path, which no longer exists.

#### Part 1 — detect the command, mint a real task_id

Status: **Implemented (2026-09-12).**

- [x] `gateway_inbound.py`, at the point inbound text currently reaches `_push_task()` - new `_is_reset_command(text)`/`_handle_reset_command(chat_id, user_id)`, checked in `_handle_update()`'s plain-text branch only.
- [x] **Match rule, decided (2026-09-11): case-insensitive, with leading/trailing/extra internal whitespace normalised away before comparison** - implemented as `" ".join(text.split()).lower()` (handles strip + internal-run-collapse in one step) compared against `f"{settings.TELEGRAM_BOT_NAME} refresh yourself".lower()`. Not a substring match - the normalised text must equal the normalised phrase in full.
- [x] Whitelisted -> **mints a real `task_id`/task mapping** (same `create_task_mapping()` call `_push_task()` would have made), then pushes `session_clear_request` carrying it (Part 2) instead of a normal task payload. On a failed mint or push, mirrors `_push_task()`'s own apology-message shape rather than silently dropping.
  - **Revised from an earlier draft that used `task_id: null` here.** Needed so `bot_sanctuary` has something concrete to close via a literal `completed`/`error` in the ignored-duplicate case (see Part 3/`bot_sanctuary`'s own entry) - `task_id: null` gave it nothing to close.
  - **No special-casing for the requesting admin's own chat/session anywhere in this flow** - confirmed by the user. Its own eventual open task (this very command) is treated identically to any other chat's, folded into the same broad sweep and the same `session_reset`-closes-it-like-a-completed/error mechanism as everyone else - not a separate code path.
- [x] Not whitelisted -> unchanged, falls through to `_push_task()` as ordinary text. Whitelisted but text doesn't match the command -> also unchanged, falls through to `_push_task()` as ordinary text (being whitelisted for reset doesn't make every message from that chat special).
- **Scope decision made during implementation, not explicitly pinned down in the design above:** command detection only runs on a plain text message with **no draft pending** - never against a draft-finalising instruction. A pending draft's media always takes priority; the finalising text is only ever read as an instruction for that media, even in the narrow coincidental case where it happens to match the command phrase exactly. Flagged as an assumption, not re-confirmed with the user before implementing - open to revisiting if that's wrong.

#### Part 2 — new outbound `session_clear_request`

Status: **Implemented (2026-09-12).**

- [x] **Corrected during implementation (2026-09-12): `{"task_id": <minted>, "type": "session_clear_request"}` only - no `chat_id`.** The originally-drafted shape above (`chat_id` included) was caught by the user - `bot_sanctuary` stays entirely chat-agnostic (see "Confirmed design correction" above), the same "identity-blind agents" principle every other outbound task payload already follows (see README.md's Design Decisions) - it has no use for `chat_id`, only `task_id` (to echo back later on its own `session_reset`). `push_session_clear_request(task_id, chat_id)` still accepts `chat_id` as a parameter, purely so its own log lines can identify which chat triggered the request - it's just never written into the payload itself.
- [x] New helper alongside `_push_session_cleared()`'s existing pattern in `session_reset_handler.py` - public (not underscore-prefixed), since it's called from `gateway_inbound.py`, not just internally within this module. Same deferred-import-of-`queue_push_task` pattern to avoid the existing circular-import risk.

#### Part 3 — `bot_sanctuary` side

Status: **Implemented (2026-09-12), in `bot_sanctuary`'s own codebase, in three staged steps - owned and documented in full in `bot_sanctuary/CODE_TODO.md`'s own entry ("NEW — `session_clear_request` handling"), not duplicated here.**

Accepts or rejects (sweep already in progress -> literal `error` closes the incoming `task_id`, nothing else happens - implemented as `error` rather than `completed`, a decision made during implementation so the requesting admin actually learns why nothing happened), and on acceptance publishes **one** `session_reset` **immediately** (**corrected 2026-09-12** - not per session, not after finishing; see "Confirmed design correction" above), then signals every session it holds to gracefully finish/clear itself, concurrently, via a new dedicated `SessionWorker.retire()` method (not `shutdown()`/`stop()` - a third, purpose-built exit path).

**Cross-file consistency gap - resolved 2026-09-12.** `bot_sanctuary/CODE_TODO.md`'s own "`session_clear_request` handling" entry was, at the time this was originally flagged, still dated 2026-09-11 and described the disproven per-session-publish model. It has since been reconciled during implementation - the stale text is kept, marked superseded in place (struck through, not deleted, per that file's own history-preservation convention) rather than rewritten, with the corrected model implemented and documented alongside it.

**Still open on `bot_sanctuary`'s side (tracked there, not here):** `README.md` documentation for the whole feature; two small unbackstopped-publish-failure gaps (accept-path and reject-path); a bounded continuously-busy-session edge case; and the "stray message" accepted-risk note now also applying to `retire()`. See `bot_sanctuary/CODE_TODO.md`'s own "Part 3 — post-implementation review" subsection for full detail. None of these block Part 3's own functional completeness - the accept/reject/publish/retire round-trip this design specifies is fully implemented and traced.

##### `session_cleared` retirement - now unblocked, still not done

`bot_sanctuary`'s `SessionWorker.retire()` (the "new dedicated clearing method" the option below was waiting on) now exists and is implemented. Per the "Not done, deliberately deferred" bullet below, retiring `session_cleared` entirely (both `telegram_gateway`'s push and `bot_sanctuary`'s `_handle_session_cleared()`/its dispatch branch) is therefore no longer blocked on a missing prerequisite - but it also hasn't been acted on. Still open, tracked as a `bot_sanctuary/CODE_TODO.md` follow-up, as originally planned.

##### `session_cleared` - investigated and partially corrected (2026-09-12), `telegram_gateway` side only

Raised directly by the user: `_push_session_cleared()` was never removed, and still included `chat_id` in its payload - "I realised that `_push_session_cleared` is not removed which contradicts the requirement in addition to sending `chat_id` in... bot_sanctuary will not have an active session to ack this."

- **Confirmed correct, on investigation.** `bot_sanctuary/CODE_TODO.md`'s own "`session_clear_request` handling" entry (§Decisions) already states its forthcoming dedicated per-session clearing method tears down its own `SessionWorker`/session directory **proactively**, as part of publishing its own `session_reset` - not waiting on or needing `telegram_gateway`'s `session_cleared` ack for anything ("`_handle_session_cleared()` still exists and is still idempotent against an already-removed session, but this feature does not wait on or need it"). So by the time that ack arrives - especially for a chat gateway deferred behind an open poll/task - `bot_sanctuary`'s worker for that session will typically already be gone. `session_cleared`'s original premise (an ack `bot_sanctuary` depends on to know when to tear its own state down) doesn't hold under the corrected, decoupled design.
- **Three options presented (A: remove both sides now, B: remove `telegram_gateway`'s push side now and accept a temporary bot_sanctuary-side cleanup gap until Part 3 ships, C: fix the identity-blind violation now and defer full removal to Part 3-time).** Full removal (A/B) was set aside for now - `bot_sanctuary`'s Part 3 (the new dedicated clearing method) is not yet implemented, and today `_handle_session_cleared()` remains `bot_sanctuary`'s *only* mechanism for tearing down a stale `SessionWorker`/session directory after any reset. Removing `telegram_gateway`'s push side before that replacement exists would leave `bot_sanctuary` with no cleanup mechanism at all in the meantime.
- [x] **Option C implemented (2026-09-12), `telegram_gateway` side only:** `_push_session_cleared()`'s payload no longer includes `chat_id` - `{"task_id": null, "session_id": "<cleared>", "type": "session_cleared"}`. Restores the "identity-blind agents" principle this payload had been a standing exception to; `session_id` alone is already sufficient for `bot_sanctuary`'s existing `_handle_session_cleared()` (keyed purely by `session_id`). `chat_id` is still accepted as a parameter, purely for this function's own log lines - same pattern as `push_session_clear_request()`. No `bot_sanctuary` code touched by this change.
- **Not done, deliberately deferred to `bot_sanctuary`'s own Part 3 implementation:** retiring `session_cleared` entirely (both the push here and `_handle_session_cleared()`/its dispatch branch there), once `bot_sanctuary`'s new dedicated clearing method actually exists and proves out tearing down its own state without this event. Tracked as a `bot_sanctuary/CODE_TODO.md` follow-up at that point, not here.

#### Part 4 — add the broad sweep-on-receipt behaviour

Status: **Implemented (2026-09-12).**

`session_reset_handler.py::_is_reset_allowed()`'s removal - originally drafted as this Part's opening bullet - was pulled forward and **already implemented 2026-09-12**; see Part 0 above for the full reasoning.

- [x] `handle_session_reset_request(task_id)` now does two passes: **(1)** if `task_id` is present, resolve `chat_id` via the existing `get_task_mapping()` and close it out via `delete_task_mapping(task_id, chat_id)` - exactly like a `completed`/`error` would, per the "Confirmed design correction" above (this was the previously-flagged gap - without it, a deferred reset triggered by this very `task_id` could never resolve, since nothing else was ever going to close it). **(2)** Regardless of whether `task_id` was present, enumerate every `chat_id` it knows about (Part 0's `get_all_session_chat_ids()`) and attempt the existing, **completely unchanged** `has_open_tasks()`/`pending_reset` decision for each one, independently - no chat blocks on another; each is deferred or applied purely by its own open-task state, exactly as today. Idempotent by construction (a no-op for an already-clear chat or one already correctly sitting in `pending_reset`), so re-running this on every arrival is safe, if somewhat redundant at scale - a minor efficiency note, not a correctness concern given this project's size.
  - The chat_id tied to `task_id` (if any) is **not** special-cased out of the sweep - it's swept like any other, just carrying the real `task_id` (instead of `None`) in its own `pending_reset` entry for traceability.
  - **New private helper `_defer_or_apply_reset(chat_id, task_id)`** - the `has_open_tasks()` → `set_pending_reset()`/`_apply_session_reset()` decision, extracted out of what used to be `handle_session_reset_request()`'s own body, so it can run once per chat_id in a loop instead of once for a single already-resolved chat_id.
  - **Run as a plain sequential `for` loop, not across separate threads** - a deliberate implementation choice, not explicitly specified in the design above. This project's chat count is small and bounded (same assumption already relied on by `utils_redis/database.py::_get_chat_lock()`'s one-lock-per-chat_id, never-removed design), so sequential execution was judged sufficient; `bot_sanctuary`'s own "signal every session AT ONCE (concurrent, not sequential)" requirement (Part 3) is a separate, unrelated concern on that side, not something this loop needs to replicate.
- [x] **§0-§8 ("Graceful `session_reset`" feature, below this entry) needed no internal changes at all.** `_apply_session_reset()`, `resolve_pending_reset_if_ready()`, `resync_pending_resets()`, `_enforce_pending_reset_ceiling()` are all untouched - `_defer_or_apply_reset()` reuses exactly what `handle_session_reset_request()` used to do inline, just now callable per chat_id in a loop.
- [x] **No new per-chat tracking state needed on `telegram_gateway`'s side** (an earlier draft of this entry proposed a `pending_refresh:<chat_id>` key - superseded; the existing `pending_reset` store already does everything required once this broad, idempotent sweep exists).

#### Post-implementation hardening (2026-09-12 verification pass)

Two defensive fixes made during a dedicated integrity-verification pass over Parts 0/1/2/4, requested directly by the user rather than found during initial implementation. Both are cheap, harmless additions with no behavioural downside - implemented on that basis ("I see no risk in implementing the hardening, it's defensive coding"), independent of exactly how likely either gap is to ever actually fire.

**Issue 1 - `_defer_or_apply_reset()` could apply a reset without clearing a stale `pending_reset` entry first.**

- Initial claim (now corrected): first described as reachable via two overlapping admin triggers on the same chat. That specific construction turned out to be **wrong** - directly caught by the user - because `bot_sanctuary` rejects a second `session_clear_request` outright while its own sweep is still in progress (Part 3), and its sweep can only clear once every session it holds (including the one blocking `has_open_tasks()` on the gateway side) has already finished its current turn and reported in. That means whatever was keeping `has_open_tasks()` true would already have triggered `resolve_pending_reset_if_ready()` (which does clear first) before a second trigger could ever be accepted - closing the exact path first described.
- **Re-derived, narrower, still-real path:** only reachable as a compounding effect on top of the already-known, already-documented §8 gap (an orphaned/expired task mapping whose `completed`/`error` was lost/dropped, so `bot_sanctuary` considers it done while the gateway's own `session_tasks:<chat_id>` still lists it as open). In that specific combination, a later `session_reset`'s own task-closing step can be what empties `session_tasks:<chat_id>`, reaching the immediate-apply branch while an earlier, different `pending_reset` entry is still sitting there un-refreshed.
- **Not an independent gap** - contingent entirely on §8 already being present; already backstopped today by `PENDING_RESET_MAX_WAIT_SECONDS`'s periodic ceiling sweep even without this fix. Its only effect if left unfixed: one delayed force-apply plus a spurious "Force-applied session_reset" warning log, once, after the ceiling elapses - no duplicate resets, no user-facing symptom, no data corruption.
- [x] **Fixed anyway, as defensive coding, not because the gap was proven likely:** `_defer_or_apply_reset()`'s immediate-apply branch now calls `clear_pending_reset(chat_id)` before `_apply_session_reset(chat_id)` - a no-op when there was nothing pending, and removes the one delayed-warning-log outcome above when there was.

**Issue 2 - `_handle_reset_command()`'s mint-succeeds/push-fails path could leave an orphaned task mapping.** Not previously written down anywhere despite being raised in conversation - corrected here.

- If `create_task_mapping()` succeeds but `push_session_clear_request()` then fails (e.g. a RabbitMQ publish failure), the admin is still told via the existing apology message, but the just-created `task:<task_id>` mapping and its `session_tasks:<chat_id>` index entry were never cleaned up - `bot_sanctuary` never received the request, so nothing was ever going to close it.
- **Effect if left unfixed:** `has_open_tasks(chat_id)` returns `True` for that chat indefinitely - any *future* `session_reset` for the same chat, including a successful retry of the same command, gets deferred instead of applying immediately, purely because of this one dead entry. Same shape as the §8 gap, so bounded by the same `PENDING_RESET_MAX_WAIT_SECONDS` ceiling sweep rather than an indefinite hang - but a real, avoidable delay.
- [x] **Fixed:** the `push_session_clear_request()`-failed branch now calls `delete_task_mapping(task_id, chat_id)` before sending the apology message, rolling back the orphaned mapping immediately instead of waiting on the ceiling sweep.
- **Explicitly not addressed:** `_push_task()` has the identical unrolled-back-mapping shape on its own two failure branches (`generate_session()` failing, `queue_push_task()` failing) - a separate, pre-existing risk of the same kind, flagged but out of scope for this pass.

#### Part 5 — `bot_started`: the only mechanism for reconciling a `bot_sanctuary` crash/restart

Status: **Implemented on both sides (`telegram_gateway` 2026-09-12, `bot_sanctuary` 2026-09-12) - see `bot_sanctuary/CODE_TODO.md`'s own "`bot_started` — implemented" subsection for that side's detail.**

- [x] New event, `bot_sanctuary -> telegram_gateway`, `{"type": "bot_started"}` (no other fields - not chat/session-scoped), fired **unconditionally at every `bot_sanctuary` startup** (crash-recovery or a routine redeploy alike - either way, whatever `bot_sanctuary` was doing before is gone). **Implemented 2026-09-12** (`bot_sanctuary`'s `initialise.py::_push_bot_started()`) - fired after `initialise_rabbitmq_connection()` confirms RabbitMQ is reachable (rather than at the literal first line of startup, since `RabbitMQPublisher.publish()` only retries a bounded number of times, unlike that call's own indefinite retry), still ahead of `resync_orphaned_sessions()` as this design requires. Best-effort/non-fatal on a failed publish - this file's own ceiling-sweep backstop below is exactly the fallback for that case.
- [x] `telegram_gateway`: new `resolve_pending_resets_on_bot_started()` (`session_reset_handler.py`) - loops `get_all_pending_resets()` (already exists) and, for every entry, resolves it **directly via `_apply_session_reset(chat_id)`** - not `_force_apply_session_reset()`. Dispatched from `process_message()` via a new thin delegate, `_handle_bot_started()` (`message_handler.py`), routed the same way `session_reset` already is - ahead of the shared `task_id`-mandatory gate, since `bot_started` carries no `task_id` (or any other field) at all.
  - [x] **Why not `_force_apply_session_reset()` - explicit instruction, and it turns out to be the more honest fit once traced through:** that function differs from plain `_apply_session_reset()` by exactly two things - a defensive `stop_poll_for_reset()` sweep over any lingering polls, and a "forced after timeout" warning log. The warning-log framing ("forced after exceeding the wait ceiling") doesn't fit `bot_started` - this isn't a guess after waiting too long, it's a definite, known fact that `bot_sanctuary` restarted, so nothing is coming for whatever it was holding.
  - [x] **Decided (2026-09-11): still close any lingering open poll for each resolved chat, same as `_force_apply_session_reset()` does** - "expire that poll if a session reset is on-going." `resolve_pending_resets_on_bot_started()` calls the same `get_session_poll_ids(chat_id)` + `stop_poll_for_reset(poll_id)` step directly, then `_apply_session_reset(chat_id)` - structurally identical to `_force_apply_session_reset()`'s body, but as its own function with its own log framing ("resolved via bot_started" rather than "forced after timeout"), not a call into that function itself.
  - [x] **No `has_open_tasks()`/expiry check at all** - unlike `resync_pending_resets()`/`_enforce_pending_reset_ceiling()`, every entry in `get_all_pending_resets()` is resolved unconditionally and immediately. A `bot_started` event is a definite fact, not a guess after waiting - there is nothing left to wait for, for any of them.
  - **`bot_sanctuary` itself does nothing about this and doesn't need to** - confirmed: "I am expecting bot_sanctuary to reset and moved on." Closing a lingering Telegram poll is entirely `telegram_gateway`'s own concern (it owns the poll, `bot_sanctuary` never knew about it as anything other than an open task_id) - `bot_sanctuary`'s side of a restart is just the unconditional `bot_started` broadcast, nothing more.
  - [x] **`_force_apply_session_reset()`/`_enforce_pending_reset_ceiling()` remain completely untouched** - kept purely as the last-resort safety net for whatever `bot_started` itself doesn't cover (the `bot_started` message being lost, or some other scenario not yet identified). Explicit expectation, not just a side effect: now that `bot_started` is wired end-to-end on both sides (2026-09-12), this path **should rarely or never actually fire in practice** for this feature's cause of pending resets - it stays as defence-in-depth, not as the primary mechanism it was before `bot_sanctuary`'s side shipped.
- `bot_sanctuary`'s own existing crash recovery (`mark_task_active`/`mark_task_complete`/`sweep_orphaned_sessions`/`resync_orphaned_sessions()`) is **unrelated and untouched** - it keeps doing its own generic job for ordinary orphaned tasks, whether or not they happen to belong to an in-progress admin sweep. This feature does not rely on it, build on it, or change it.

#### Also needed

- [ ] `## Agent-call access tier` (below): still-open, separate follow-up - decoupled `coding_allowed` whitelist env var. Not part of this design, not blocking it.
- [x] `README.md` - new `session_clear_request`/`bot_started` sections added, `session_reset`/whitelist scope description corrected to match the design above (implemented 2026-09-12).
- [x] `CODE_SEQUENCE_DIAGRAM.md` - new §8.0 (admin command → `session_clear_request` round trip) and §8.8 (`bot_started` recovery) added, §8.1-8.3/§6.5-6.9 corrected to match the design above (implemented 2026-09-12).

#### Compliance review findings — CCR-023/CCR-024 (`CODE_NON_COMPLIANCE.md`'s tenth follow-up pass, 2026-09-12)

`CODE_NON_COMPLIANCE.md` (the project's own protected compliance record - reviewed, never edited directly here) identified two findings against this feature's own implementation above, on request ("reverify telegram_gateway for non-compliance and weakness"). Both were re-verified directly against current source before any fix was made, not assumed from the report's own text.

- **CCR-024 (Low) - Fixed 2026-09-12.** `gateway_inbound.py::_is_reset_command()`'s own docstring claimed a symmetric whitespace-normalisation contract ("leading/trailing whitespace stripped and internal runs collapsed") that the code didn't actually apply to both sides of its comparison - only the incoming Telegram text (`normalised_text`) was run through `" ".join(text.split())`; the configured command phrase (`normalised_command`, built from `settings.TELEGRAM_BOT_NAME`) was only `.lower()`'d. A stray whitespace character in a deployment's configured `TELEGRAM_BOT_NAME` would have made this function return `False` unconditionally, silently and permanently disabling the only mechanism this codebase provides for triggering a global session reset - with no error or log line anywhere to explain why. **Fix:** `normalised_command` now goes through the identical `" ".join(...split()).lower()` normalisation as `normalised_text` - one line, no behavioural change under a normally-configured (whitespace-clean) `TELEGRAM_BOT_NAME`, closes the gap for a misconfigured one.
- **CCR-023 (Medium) - Fixed 2026-09-12, after two rejected/corrected proposals - kept below for the full history, per this file's own record-keeping convention.** `database.py::get_pending_reset()`'s `None` return value ambiguously represented both "no `pending_reset:<chat_id>` entry exists" and "an entry exists with a legitimately-`None` `task_id`" (the latter a deliberate, expected outcome of Part 4's broad sweep passing `task_id=None` for every non-triggering chat_id - see `set_pending_reset()`'s own docstring). `resolve_pending_reset_if_ready()` - the natural-completion resolution path, called the instant a chat's last open task's `completed`/`error` is processed - couldn't tell the two cases apart and silently no-opped for the second one, falling back to the up-to-`PENDING_RESET_MAX_WAIT_SECONDS` (1h default) ceiling sweep instead of resolving immediately. Directly contradicted `README.md`'s own documented contract for this feature ("applied automatically the moment that chat's last open task naturally completes"). Confirmed reachable regardless of any other fix already landed - `get_all_pending_resets()` (used by `resync_pending_resets()`/`_enforce_pending_reset_ceiling()`/`resolve_pending_resets_on_bot_started()`) reads the full stored record directly and was never affected; only `get_pending_reset()`/`resolve_pending_reset_if_ready()` were.
  - **First proposal, rejected (user-caught): swap `resolve_pending_reset_if_ready()`'s check to `_get_pending_reset_info(chat_id) is None`.** Logically sound in isolation, but `_get_pending_reset_info()` is a private (`_`-prefixed) `database.py` helper never imported into `session_reset_handler.py` - as literally proposed this would not run at all, not silently fix nothing as first assumed. Correctly challenged: "Either fix nothing." True two-line cost was understated (an import, plus crossing this codebase's own private/public module-boundary convention, or a new public wrapper) - not the "no `database.py` change needed" originally claimed.
  - **Follow-up question, also correctly raised: what about a failed Redis read?** `_redis_read()` already collapses "key missing" and "read failed after exhausted retries" into the same `None` - a pre-existing, documented, codebase-wide convention shared by every other Redis-backed getter (`get_task_mapping()`, `get_chat_draft()`, etc.), not something either proposed fix introduced or needed to solve. Resolved by explicit design decision: a failed read is treated identically to "not pending" here - fail-safe (skips one resolution attempt, never falsely resolves/clears on bad information) and self-healing (the `PENDING_RESET_MAX_WAIT_SECONDS` ceiling sweep remains the backstop for exactly this kind of missed natural-completion attempt) - consistent with, not a deviation from, how the rest of this codebase already treats every other Redis read failure.
  - **Adopted fix, user-proposed: a fixed sentinel string instead of a bare `None`.** New `session_reset_handler.py` module constant `SYSTEM_TRIGGERED_TASK_ID = "system_triggered"`. `handle_session_reset_request()`'s broad-sweep loop now passes this sentinel (never a bare `None`) for every chat_id that isn't the one that actually triggered the reset - covering both scenarios: the majority of chats under a user-triggered (Scenario 1) reset, and *every* chat under an orchestrator-triggered (Scenario 2, no `task_id` at all) reset, since `triggering_chat_id` never matches any real `chat_id` in that case. A stored `pending_reset:<chat_id>` entry's `task_id` field is therefore never actually `None` in practice - only ever a real `task_id` or this sentinel - which makes `get_pending_reset()`'s existing `None` return unambiguous again ("no entry exists", full stop) with **zero changes needed to `database.py`'s implementation, signature, or storage format, and no new cross-module exposure** - a smaller, cleaner fix than either prior proposal. Never collides with a real `task_id` (always a `uuid.uuid4().hex` value from `create_task_mapping()`). `set_pending_reset()`'s own signature is deliberately left as `task_id: str | None` regardless - it's a generic storage primitive with no opinion on the sentinel's meaning; the invariant is enforced entirely at the one call site in `session_reset_handler.py` that owns this feature's semantics.

### Open Questions

All five resolved on 2026-09-11 except the last, which stays open by explicit instruction:

1. ~~Exact command-matching rule.~~ **Decided** - case-insensitive, whitespace-normalised, full-body match. See Part 1.
2. ~~Whether `_handle_bot_started()` should also defensively close any lingering open poll.~~ **Decided: yes.** See Part 5.
3. ~~Exact ordering of `bot_started` vs. `resync_orphaned_sessions()` at startup.~~ **Closed as a non-issue.** Both are independently idempotent - each resolves whatever it's responsible for and finds nothing to do if the other already handled it, regardless of which runs first. No explicit ordering requirement needed; this entry's Part 5 still fires `bot_started` first purely as the simpler-to-write-down default, not because order is load-bearing.
4. ~~Exact shape of `bot_sanctuary`'s future "fixed/scheduled reset time" mechanism.~~ **Closed as a non-issue for this design specifically.** However that future trigger ends up built, it should simply behave like any other `session_reset` arrival once triggered - this is scenario 2 in the "Confirmed design correction" above, and Part 0/Part 4's handling is already agnostic to *why* a `session_reset` was sent: a `task_id`-less trigger already has a defined, correct behaviour (nothing task-specific to close, go straight to the broad sweep - no `session_id` resolution of any kind). ~~The *scheduling* mechanism itself (when/how it decides to fire) remains a separate, still-undesigned question on `bot_sanctuary`'s side, unaffected by this closure.~~ **Now designed and implemented (2026-09-12) - `bot_sanctuary`'s `SESSION_RESET_TIME` setting, see that project's own `CODE_TODO.md` "Timed session reset" subsection.** Publishes `session_reset` with `task_id: null` exactly as this closure anticipated - no change needed on this side at all.
5. **Still open, explicit instruction not to address it now:** exact new env var name for the decoupled `coding_allowed` whitelist.

### Where

- `telegram_gateway_application/utilities/utils_session/session_reset_handler.py`: `_is_reset_allowed()` (removed), `handle_session_reset_request()` (Part 4 broad sweep, implemented 2026-09-12), `_defer_or_apply_reset()` (Part 4; `clear_pending_reset()` hardening added post-implementation), `_apply_session_reset()`, `resolve_pending_reset_if_ready()`, `resync_pending_resets()`, `_enforce_pending_reset_ceiling()`, new `resolve_pending_resets_on_bot_started()` (Part 5, `telegram_gateway` side implemented 2026-09-12).
- `telegram_gateway_application/utilities/utils_redis/database.py`: new `get_all_session_chat_ids()` (`get_chat_id_for_session()` was added, then reverted 2026-09-12 - see Part 0).
- `telegram_gateway_application/utilities/utils_queue/message_handler.py`: `process_message()`'s dispatch (`session_reset`'s `task_id`-optional gate, Part 0; new `bot_started` branch, Part 5, implemented 2026-09-12), `_handle_session_reset()`, new `_handle_bot_started()`.
- `telegram_gateway_application/utilities/utils_telegram/gateway_inbound.py`: command detection (`${BOT_NAME}` interpolation) - `_is_reset_command()`/`_handle_reset_command()`, implemented 2026-09-12 (Part 1; `delete_task_mapping()` rollback-on-push-failure hardening added post-implementation) - task_id minting, new `session_clear_request` push (`push_session_clear_request()`, `session_reset_handler.py`, Part 2).
- `README.md`: `session_reset` section, new `session_clear_request`/`bot_started` sections, Agent-call access tier env var table.
- `bot_sanctuary/CODE_TODO.md`: full counterpart entry.

---

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
- [ ] **Superseded by user clarification (2026-09-10) — see the `BUG` entry at the top of this file.** Reusing `SESSION_RESET_ALLOWED_CHAT_IDS` here was decided on the (incorrect) understanding that it meant "self-service reset permission," treated as the same tier as full agent-call access. Its actual meaning is "bot admin, may trigger a global reset of every session" — a different privilege entirely. `coding_allowed` needs its own dedicated whitelist env var, decoupled from `SESSION_RESET_ALLOWED_CHAT_IDS`, even though the same individuals are expected to hold both today. Not yet implemented — see the `BUG` entry's "Must fix" list.

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

**Superseded 2026-09-12 - see the `BUG` entry at the top of this file.** This section's original premise - that `handle_session_reset_request()` should itself gate a `session_reset` on `chat_id` being whitelisted - is exactly the "self-service" misunderstanding the `BUG` entry above corrects. `_is_reset_allowed()` (below) has been **removed outright**, not just moved: an inbound `session_reset` always originates from `bot_sanctuary` itself, never directly from a chat, so there was never anything here to legitimately re-verify - see the `BUG` entry's Part 0 for the full reasoning, including the live crash-recovery bug this was silently causing. `SESSION_RESET_ALLOWED_CHAT_IDS` itself (the `config.py` setting below) is untouched and still real - it's just enforced elsewhere now (the `BUG` entry's Part 1, gateway_inbound.py's command-detection gate), not here. Kept below for history, exactly as originally written:

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
- [x] ~~Enforced in `handle_session_reset_request(task_id, chat_id)` (§1), first thing, before any deferral/immediate-reset decision~~ **Removed 2026-09-12 - see superseding note above.**
  ```python
  def _is_reset_allowed(chat_id: int) -> bool:
      return chat_id in settings.SESSION_RESET_ALLOWED_CHAT_IDS
  ```
  ~~A `chat_id` not in the whitelist is logged and dropped — no defer, no reset, no notice, no orchestrator ack. **Decided: silent (log only), no response of any kind.**~~

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

---

## NEW — Timezone awareness (`TZ`) for logging and wall-clock timing

Status: **Implemented 2026-09-12, cross-service with `bot_sanctuary` — full shared history recorded in `bot_sanctuary/CODE_TODO.md`'s own "NEW — `session_clear_request` handling" entry, "Timezone awareness" subsection (not duplicated in full here, since this project has no wall-clock scheduling logic of its own to describe - only logging is affected on this side). Same day, immediate follow-up: `config.ini` (missed when `CHATBOT_TZ` was first added) has been caught up, and this project's own direct `time.time()` call sites now go through two new shared helpers, `application_time()`/`application_time_diff()` (`utilities/utilities.py`) - see this entry's own "Centralised time retrieval" subsection below and `bot_sanctuary/CODE_TODO.md`'s parallel entry for the full cross-project history.**

### Context

Direct instruction: "implement timing according to whichever timezone set to env. follow `${HOME}/repository/V-Project-Multimedia-Application/development/compose.standalone_dev.yml` to implement timezone for both telegram_gateway and bot_sanctuary. Logging such use timezone timing too." Immediate same-day follow-up to `bot_sanctuary`'s newly-added `SESSION_RESET_TIME` (which had explicitly deferred timezone handling - "ignore timezone for now" - per an earlier instruction the same day).

### Decisions

- **New `config.py` setting: `TZ`, plus a new `get_env_timezone()` helper** - same file, same silent-fallback-to-default convention as `get_env_int()`/`get_env_bool()`. Resolves the standard `TZ` environment variable (deliberately not a project-prefixed name, since that's also what the container's own OS layer expects) to a `zoneinfo.ZoneInfo`, falling back to `"UTC"` on unset or an unrecognised zone name.
- **`utilities/logging_setup.py`'s shared `Formatter` instance given an explicit `.converter`** - `lambda timestamp: datetime.fromtimestamp(timestamp, tz=settings.TZ).timetuple()`, replacing the default `time.localtime`-based conversion. Applies to both the console and rotating-file handlers, since both share the one `formatter` object. This is this project's only actual use of `settings.TZ` today - unlike `bot_sanctuary`, nothing here schedules against a wall-clock target time.
- **`tzdata` (PyPI) added to `requirements.txt`** - `python:3.12.4-slim` has no guaranteed system IANA timezone database; `zoneinfo.ZoneInfo()` automatically falls back to this package when the system one is missing (documented stdlib behaviour), removing the risk of a `ZoneInfoNotFoundError` regardless of the image's own OS-level timezone data.
- **Root `config_sample.ini` - new `CHATBOT_TZ="Asia/Singapore"` variable**, shared between this project and `bot_sanctuary` (both containers' `TZ` env var is set from the same value in `compose.dev.yml`) - added to the shared/common section at the top of the file, not scoped under either service's own section. Not added to `setup.sh`'s `get_masked_config_variables()` (that list is for values every install must supply its own real value for; `TZ` already has one reasonable universal default carried over unchanged from what `compose.dev.yml` previously hardcoded) or to either project's own `tg_dev_run_docker()`/`bs_dev_run_docker()` (both settings this project and `bot_sanctuary` gained today - `TZ` and `SESSION_RESET_TIME` - have safe in-`config.py` defaults, so a standalone dev run works without them).
- **Root `compose.dev.yml` - both services' hardcoded `TZ: "Asia/Singapore"` replaced with `TZ: "${CHATBOT_TZ}"`** - follows the referenced `compose.standalone_dev.yml`'s own plain-`TZ`-env-var pattern, but parameterised through this project's existing `CHATBOT_*`/`config.ini` convention rather than a second hardcoded literal, so this project and `bot_sanctuary` can never silently drift apart on which zone they're each using.
- **`README.md` - new "Timezone" settings-table section.**

### Where

- `telegram_gateway_application/config.py`: new `TZ` setting + `get_env_timezone()`.
- `telegram_gateway_application/utilities/logging_setup.py`: `Formatter.converter` override.
- `requirements.txt`: new `tzdata` dependency.
- `README.md`: new "Timezone" section under Environment Variables.
- Root `config_sample.ini`/`compose.dev.yml`: shared `CHATBOT_TZ`/`TZ` plumbing, covering both this project and `bot_sanctuary`.
- `bot_sanctuary/CODE_TODO.md`: the full counterpart entry, including the `bot_sanctuary`-side wall-clock scheduling change (`SESSION_RESET_TIME` made timezone-aware) that this project has no equivalent of.

### Centralised time retrieval — `application_time()`/`application_time_diff()` — implemented 2026-09-12

Direct same-day follow-up instruction: "update config.ini too. Additionally, create application_time() function in utilitise.py on both bot_sanctuary and telegram_gateway. all retrieval of time should be retrieved from application_time(), create another function to get time diff too if required." See `bot_sanctuary/CODE_TODO.md`'s parallel "Centralised time retrieval" subsection for the full shared rationale (single clock source of truth, why a separate diff helper, why `time.sleep()`/`logging_setup.py`'s `Formatter.converter` were deliberately left untouched) - not repeated here in full.

- [x] **`config.ini` updated** with the same `CHATBOT_TZ="Asia/Singapore"` block added to `config_sample.ini` in the "Timezone awareness" section above - this file was overlooked in that earlier pass.
- [x] **New `application_time() -> datetime` and `application_time_diff(reference: float) -> float` added to `utilities/utilities.py`** - `application_time()` returns `datetime.now(settings.TZ)`; `application_time_diff()` returns `application_time().timestamp() - reference`. Same implementation as `bot_sanctuary`'s copy - no shared package between the two projects, so each gets its own.
- [x] **This project's own direct time-retrieval call sites migrated:** `utils_redis/database.py::set_pending_reset()`'s `"created_at": time.time()` → `"created_at": application_time().timestamp()`; `utils_session/session_reset_handler.py::_is_pending_reset_expired()`'s `time.time() - created_at` → `application_time_diff(created_at)`. `import time` dropped from `session_reset_handler.py` entirely once its only use was replaced (still needed in `database.py`, for its `time.sleep()` retry-delay calls, which stay untouched).

### Where (this subsection only)

- `telegram_gateway_application/utilities/utilities.py`: new `application_time()`/`application_time_diff()`.
- `telegram_gateway_application/utilities/utils_redis/database.py`: `set_pending_reset()`.
- `telegram_gateway_application/utilities/utils_session/session_reset_handler.py`: `_is_pending_reset_expired()`, dropped `import time`.
- Root `config.ini`: new `CHATBOT_TZ`.
- `bot_sanctuary/CODE_TODO.md`: the full shared rationale and its own parallel call-site migration.

---

## FIX — CCR-025: `get_env_timezone()` only caught one of several exception types `zoneinfo.ZoneInfo()` can raise for a malformed `TZ` value

Status: **Implemented, cross-service with `bot_sanctuary` (identical fix, both `config.py` files) — by explicit instruction ("update fix for both telegram_gateway and bot_santuary") following on-request validation confirming the finding was still Open. Fixes the Medium-severity finding identified in the twelfth follow-up compliance review (2026-09-12) of the new timezone-awareness change — see `CODE_NON_COMPLIANCE.md`. Not modified there directly (treated as an immutable compliance record); this entry is the code-side record of the fix.**

### Context

`get_env_timezone()`'s own docstring promised "Falls back to default, silently, on an unrecognised zone name" — the same "disable/fall back rather than crash" convention every other `get_env_*()` helper in `config.py` follows. Its implementation only caught `zoneinfo.ZoneInfoNotFoundError`, but CPython's `zoneinfo.ZoneInfo()` also raises `ValueError` for a key that is an absolute path or contains an uplevel (`..`) component, and `IsADirectoryError` (an `OSError` subclass) for a key that resolves to a tzdata directory rather than a leaf zone file — the latter a plausible real operator typo (`TZ=America` instead of `TZ=America/New_York`), not a contrived attack string. Since `settings = Settings()` runs unconditionally at module-import time, before `setup_logging()` or any other guarded startup step, either uncaught exception type crashed the whole process with a raw traceback instead of the documented graceful fallback.

### Decisions

- **Broadened the `except` clause to `(ZoneInfoNotFoundError, ValueError, OSError)`** — exactly the Recommended Remediation from the original finding. `OSError` covers `IsADirectoryError` (and any other filesystem-adjacent exception `zoneinfo`'s path-validation logic might raise for a malformed key) without needing to enumerate every subclass individually.
- **No behavioural change for a valid `TZ` value** — the fix only widens what is caught on the failure path; a well-formed IANA zone name resolves exactly as before.
- **Docstring's Notes section updated** to name the three caught exception types and why each is caught, cross-referencing CCR-025 by number for anyone tracing the code back to the compliance record.
- **Applied identically to `bot_sanctuary/bot_sanctuary_application/config.py`'s own `get_env_timezone()`** — the two functions are byte-for-byte identical copies (no shared package between the two projects), so the same defect existed in both and is fixed in both, in the same commit-worthy change.

### Implementation Notes

- `telegram_gateway_application/config.py::get_env_timezone()`: `except ZoneInfoNotFoundError:` → `except (ZoneInfoNotFoundError, ValueError, OSError):`.
- `bot_sanctuary_application/config.py::get_env_timezone()`: identical change.

### Open Questions

1. Whether `CODE_NON_COMPLIANCE.md` should be updated to mark CCR-025 Resolved is a call for whoever owns that document next — it's treated as an immutable compliance record here and was not modified as part of this session.

### Where

- `telegram_gateway_application/config.py`: `get_env_timezone()`.
- `bot_sanctuary/bot_sanctuary_application/config.py`: `get_env_timezone()` (see `bot_sanctuary/CODE_TODO.md` for that project's own copy of this entry).

---

## NEW — server-side Markdown → Telegram HTML conversion for `_handle_text()`

Status: **Implemented 2026-09-15.** Item 2 of a three-part plan the user approved to fix `**bold**` rendering as literal asterisks in Telegram. Items 1 and 3 (rewording `bot_sanctuary`'s `chat.json` persona to hand-write Telegram-specific Markdown, and to write shorter/more scannable replies) were explicitly skipped by the user's own instruction — "proceed with option 2, however try to optimise it without affecting it's persona. I have yet to make use of coding rights of the user to perform call type" — `chat.json` is not touched by this entry at all.

### Context

An earlier, since-superseded fix wired `parse_mode="Markdown"` into `_handle_text()` and told the persona "Markdown formatting is fine" in `chat.json`'s `# JSON String Safety` section. The bug persisted — confirmed via WebSearch against Telegram's own Bot API docs, not assumed: both of Telegram's Markdown `parse_mode` dialects (`Markdown`, `MarkdownV2`) use a **single** asterisk for bold (`*bold*`), never `**bold**`. The persona (like essentially every LLM by default) naturally writes CommonMark/GitHub-style `**bold**`, which Telegram's Markdown parser doesn't recognise as anything special — it passes the literal asterisk characters straight through, or, depending on how the asterisks happen to pair up elsewhere in a given reply, could instead trigger an outright 400 "can't parse entities" rejection.

Rather than depend on the persona reliably hand-writing Telegram-specific syntax turn after turn (already shown unreliable — it ignored the earlier general "Markdown is fine" wording), this converts server-side, deterministically, in `telegram_gateway` — the persona's own wording is left completely untouched.

### Decisions

- **New module, `utils_telegram/utilities/markdown_converter.py`, one public function `to_telegram_html(text: str) -> str`.** Placed alongside `typing_indicator.py`/`button_prompt_handler.py` in the existing `utils_telegram/utilities/` convention.
- **No new pip dependency.** The construct set the persona actually produces is small and known (bold, italic, inline/fenced code, headers, bullet lists) — a fixed, ordered sequence of `re` substitutions covers it without pulling in a general-purpose Markdown parser.
- **`parse_mode` switched from `"Markdown"` to `"HTML"`** in `message_handler.py`'s `_TEXT_PARSE_MODE` — HTML only requires escaping `&`/`<`/`>` (per Telegram's own docs), far less fragile than MarkdownV2's dozen-plus reserved characters, and every substitution here only ever emits a matched, balanced tag pair, so a stray/unmatched delimiter degrades to a harmless literal character instead of Telegram rejecting the whole send.
- **Ordering is safety-critical, inside `to_telegram_html()`:** (1) the entire raw text is HTML-escaped exactly once, first, via `html.escape(text, quote=False)`, before any tag is ever inserted — a tag can only ever originate from this module's own substitutions afterwards; (2) fenced/inline code spans are then pulled out into opaque placeholders *before* header/bullet/bold/italic conversion runs, so a formatting character that happens to appear inside a code span (e.g. `**kwargs` in a Python snippet) is never itself reinterpreted, then restored verbatim at the end; (3) headers → a bold lead-in line (Telegram HTML has no header tag); (4) bullet markers (`-`/`*` at line start) → a plain `•` character, run before bold so a leading `*` list marker is never mistaken for an opening bold delimiter; (5) `**bold**` converted before single-asterisk `*bold*`, so a double-asterisk pair is never left with a leftover asterisk from a greedy single-asterisk match; (6) `_italic_` converted last, guarded with a "not flanked by a word character" pattern on both sides specifically so it does not mangle a snake_case identifier (e.g. `SESSION_ID_MARKER`) into italics — the persona is explicitly technology-focused (`chat.json`'s own "Technology Interests" section) and routinely discusses such identifiers.
- **Deliberately narrow scope** — only the constructs the persona actually produces are converted. Telegram HTML also supports `<u>`/`<s>`/`<tg-spoiler>`/`<blockquote>`, none of which are handled, since nothing in the persona's instructions asks for them.
- **Scoped to `_handle_text()` only** — poll/image/video/album/file each go through their own separate `send_*()` function in `gateway_outbound.py` and are untouched. A button's own `"text"` label (inline keyboard) is sent as-is, unconverted — Telegram button labels are plain UI text with no formatting support at all.
- **`gateway_outbound.py`/`button_prompt_handler.py` needed no changes** — both already accepted and forwarded an optional `parse_mode` kwarg (added for `_handle_error()`'s existing `parse_mode="HTML"` usage), so this only required switching the value passed in and converting the text ahead of the call.

### Implementation Notes

- `telegram_gateway_application/utilities/utils_telegram/utilities/markdown_converter.py` (new): `to_telegram_html()`, `_extract_code_spans()`/`_restore_code_spans()`, and the module-level compiled patterns (`_FENCED_CODE_PATTERN`, `_INLINE_CODE_PATTERN`, `_HEADER_PATTERN`, `_BULLET_PATTERN`, `_BOLD_DOUBLE_PATTERN`, `_BOLD_SINGLE_PATTERN`, `_ITALIC_PATTERN`).
- `telegram_gateway_application/utilities/utils_queue/message_handler.py`: `_TEXT_PARSE_MODE` changed `"Markdown"` → `"HTML"`; new import of `to_telegram_html`; `_handle_text()` now converts `message` via `to_telegram_html()` before either `send_message_with_buttons()`/`send_message()` call. Module-level comment and `_handle_text()`'s own docstring updated to match.
- Never raises — a construct this module doesn't recognise is simply left as literal (already HTML-escaped) text, always safe to send regardless.

### Open Questions

1. Not yet exercised against a live Telegram send in this session — the plan's own Verification steps (re-send a web-search synthesis reply; deliberately test `**bold**`/`*bold*`/literal `<`/`&`; confirm only `_handle_text()`'s call sites changed) are still to be run manually against a real bot.
2. Items 1 (`chat.json` Telegram-accurate syntax spec) and 3 (`chat.json` reply-length/source-list tightening) from the original plan remain deliberately unimplemented, per the user's explicit persona-preservation instruction — not tracked further here since they're out of scope for this entry; revisit only if this server-side conversion alone proves insufficient (e.g. a construct the persona produces that this module doesn't yet handle).

### Follow-up fix (2026-09-15) — tag-nesting risk when bold/italic delimiters interleave

Found while directly answering the user's own follow-up question, "is telegram_gateway ready to accept html?" — a full re-read of the send path against Telegram's documented HTML `parse_mode` rules turned up one real, previously-unflagged gap in the module above (everything else — `parse_mode` plumbing, `&`/`<`/`>` escaping, the tag set used, the buttons-path length check now measuring the actual post-conversion string — checked out as-is, no changes needed).

- **Gap:** `_BOLD_DOUBLE_PATTERN`/`_BOLD_SINGLE_PATTERN`/`_ITALIC_PATTERN` originally used an unrestricted `(.+?)` capture group, which could match straight across a `<`/`>` character an *earlier* step in the same conversion had already inserted (a header's own `<b>...</b>`, or an earlier bold pass ahead of the italic pass that runs last). Concretely: `"**bold and _italic** text_"` converted to `"<b>bold and <i>italic</b> text</i>"` — invalid, overlapping tags. Telegram's HTML parser rejects a message like that outright (400 "can't parse entities"), not the graceful degrade-to-literal-text this module's own header Notes otherwise correctly describe for a single stray/unmatched delimiter. Not a silent failure — already caught by the existing Tier 1 `delivery_failed` path — but a real, avoidable send failure for a plausible reply shape (interleaved emphasis is ordinary prose).
- **Fixed:** all three patterns' capture groups changed from `(.+?)` to `([^<\n]+?)` — excluding `<` stops a match the instant it would cross an already-inserted tag, leaving the outer delimiters as harmless literal text instead of an invalid overlapping tag; excluding `\n` as a side effect also stops emphasis from spanning multiple lines/paragraphs, shrinking the blast radius of any stray unmatched delimiter further.
- No other file needed touching — `gateway_outbound.py`/`button_prompt_handler.py`/`message_handler.py` were all re-confirmed ready as-is during this same investigation.

### Where

- `telegram_gateway_application/utilities/utils_telegram/utilities/markdown_converter.py` (new; nesting-guard follow-up fix, same file, 2026-09-15).
- `telegram_gateway_application/utilities/utils_queue/message_handler.py`: `_TEXT_PARSE_MODE`, `_handle_text()`.

---

## BUG — a validated button press produces no response when its `purpose` isn't `draft_continue` (e.g. `select_shoe`)

Status: **Scoped (2026-09-16) - not yet implemented.** Raised directly by the user testing the live bot ("bot did not provide any response when clicking on a button", ~07:13am) - traced against `telegram_gateway.log`/`bot_sanctuary.log` for that morning (both logs read in full, cross-referenced by timestamp/`task_id`) before any fix was scoped, per explicit follow-up instruction to scope all three issues found that morning and log them here.

### Context

`bot_sanctuary`'s persona is free to send a `text` reply with `buttons`, each carrying a caller-defined `purpose` string (see `chat.json`'s own `text` format: `{"type": "text", "text": "...", "buttons": [[{"text": "...", "purpose": "...", "payload": {...}}]]}`) - `purpose` is never validated or constrained to a fixed set anywhere in either codebase. `telegram_gateway`'s own `gateway_inbound.py::_handle_update()` docstring already states plainly: *"`draft_continue` ... is the only callback purpose currently wired up; any other purpose is logged and otherwise ignored."* This morning the persona sent a shoe-selection prompt with `purpose='select_shoe'` - a purpose that has never had a wired handler on this side, so the press was silently swallowed.

### Symptom / Evidence

`telegram_gateway.log`, 07:13:47-08:07:53 (chat_id=543086109):

- `07:13:47` - `bot_sanctuary` sends a text reply with 3 buttons, `purpose='select_shoe'`; `bot_sanctuary.log` confirms it left that task_id open ("leaving it open (poll, or a text reply carrying buttons)").
- `07:13:52` - user taps one. `button_prompt_handler.validate_bot_callback()` correctly validates it as genuine, single-use, not expired/forged - then `_handle_update()`'s own `else` branch logs *"Validated callback_query ... no handler wired up for this purpose yet"* and returns. Nothing is pushed onward; the open task_id from 07:13:47 never receives a `completed`/`error`, so nothing is ever sent back to Telegram.
- `07:14:11` onward, and again at `08:07:53` - further `callback_query` updates are correctly rejected as stale/already-consumed/expired (`validate_bot_callback()`'s own single-use/TTL behaviour, working as designed) - consistent with the user re-tapping a button that already silently failed once, or an older message's buttons.

### Root Cause

Confirmed in code, not just inferred from logs: `_handle_update()`'s callback branch (`gateway_inbound.py`) only has a real handler for `purpose == "draft_continue"`; every other purpose falls into the deliberate, logged no-op `else`. This is an incomplete integration, not a crash or race - the persona-side feature (buttons with an arbitrary `purpose`) was built assuming the gateway would route the press back into a task, but no generic mechanism for that exists; only the one purpose `telegram_gateway` itself needed (`draft_continue`, for its own media-draft-expiry feature) was ever wired.

### Decisions (scoped fix, elaborated 2026-09-16 against a direct precedent already in this codebase - not yet implemented)

- **Preferred direction, unchanged: a generic callback-to-task routing path, not a second hardcoded purpose.** Hardcoding `select_shoe` the same way `draft_continue` is wired today was considered and rejected - the persona can invent any `purpose` string at any time (nothing constrains it to a known set), so a second hardcoded branch would only fix today's specific case and leave the same silent-drop gap for the next new purpose the persona ever tries.
- **Open design question from the original scoping - now resolved by precedent: a button press resolves back onto the *same* `task_id` the buttoned message was published against, exactly like a poll answer already does.** `utils_telegram/utilities/poll_response_handler.py::_push_poll_answer(task_id, option_ids)` is the *identical* problem, already solved and already implemented for polls: it pushes `{"task_id": <the poll's own task_id>, "session_id": ..., "text": "", ..., "poll_answer": option_ids}` back onto the outbound queue against the task_id that was already open when the poll was sent - never a freshly-minted one. Buttons should follow the same shape, not the alternative (mint a new task_id via `create_task_mapping()`/`_push_task()`) - that alternative was never seriously in the running once this precedent was found; it would need a second, parallel task_id-minting path with no clear benefit over reusing the one `bot_sanctuary` is already holding open.
- **Concrete mechanism, modelled directly on `create_poll_mapping()`/`get_poll_mapping()`'s existing shape:**
  1. `register_bot_button()` (`button_prompt_handler.py`) gains a new required `task_id` parameter, stored in `_registered_callbacks[token]` alongside the existing `chat_id`/`purpose`/`payload`/`created_at` - mirrors `create_poll_mapping()` storing `task_id` keyed by `poll_id`, just in-memory rather than Redis (this registry already is - see the module's own header Notes, "in-memory only, resets on application restart").
  2. `_build_button_rows()` (`message_handler.py`) already has `task_id` in scope at its one call site (`_handle_text(task_id, chat_id, message, buttons)`) - just needs to thread it through into each `register_bot_button()` call it makes.
  3. `validate_bot_callback()` returns `task_id` alongside `purpose`/`payload` in its result dict, once popped from `_registered_callbacks`.
  4. `_handle_update()`'s callback branch, for any `result["purpose"]` other than `"draft_continue"`, pushes a new payload back onto the outbound queue via `queue_push_task()` - `{"task_id": result["task_id"], "session_id": generate_session(task_id=result["task_id"]), "text": "", "image_url": "", "video_url": "", "file_url": "", "button_press": {"purpose": result["purpose"], "payload": result["payload"]}}` - the same shape/call pattern as `_push_poll_answer()`, just with a `button_press` key instead of `poll_answer`. No `_handle_text()`-side change needed beyond passing `task_id` through, and no `create_task_mapping()` call at all for this path - the mapping already exists from when the buttoned message was first pushed.
- **The button's `payload` dict is carried through unchanged** by the mechanism above (item 4) - it is no longer silently discarded once `validate_bot_callback()` returns it, closing the gap flagged in the original scoping.
- **New finding, found while tracing this fix through to its actual consumer - changes this entry's scope materially: `bot_sanctuary`'s own turn-building step doesn't read anything but `text` from a task payload today.** `utils_session/session_worker.py::_process_batch()` builds its combined prompt with `combined_text = "\n".join(text for text in ((item.get("text") or "") for item in batch) if text.strip())` - `image_url`/`video_url`/`file_url`/`poll_answer` are *all* already just as inert as a hypothetical `button_press` field would be; none of them are read anywhere in `_process_batch()` or downstream in `call_dispatch_handler.py`. This means `telegram_gateway`'s side of the poll-answer round trip (`_push_poll_answer()`) has apparently never had a working consumer on `bot_sanctuary`'s side either - the same gap this entry originally found for buttons turns out to already exist for polls, undocumented until now. **This fix is therefore a two-repo change, not a `telegram_gateway`-only one**: `_process_batch()` (or wherever the final prompt is actually assembled before reaching Claude) needs a new branch that recognises a `button_press` (and, while there, arguably `poll_answer`) key on a batch item and folds it into the turn's prompt as something like "the user selected: <purpose>/<payload>" - otherwise the press would arrive, be correctly resolved back onto its `task_id`, and still produce no visible effect, for exactly the same reason poll answers already don't today.

### Open Questions

1. ~~Whether a button press resolves onto the same task_id or a new one.~~ **Resolved above - same task_id, mirroring `_push_poll_answer()`.**
2. ~~Exact task payload shape.~~ **Resolved above - `button_press: {"purpose", "payload"}` alongside the existing poll_answer-style envelope fields.**
3. Whether to fix `_process_batch()`'s "only reads `text`" gap generally (covering `poll_answer`/media too, since all are equally affected) as part of this same change, or narrowly (just enough to make `button_press` visible to the prompt) and leave `poll_answer`/media as a separately-tracked pre-existing gap - **see the new cross-referenced entry in `bot_sanctuary/CODE_TODO.md`**, not yet decided which repo's TODO should own that broader fix.
4. Whether any button `purpose` besides `select_shoe`/`draft_continue` is expected soon - affects only how the persona-facing wording of the folded-in prompt ("the user selected: ...") should be phrased generically enough to cover future purposes, not whether the mechanism itself is worth building.

### Follow-up Work

- Implement the four-step mechanism above (`register_bot_button()` → `_build_button_rows()` → `validate_bot_callback()` → `_handle_update()`'s callback branch), reusing `generate_session(task_id=...)`/`queue_push_task()` exactly as `_push_poll_answer()` already does.
- Coordinate with `bot_sanctuary/CODE_TODO.md`'s new cross-referenced entry on `_process_batch()` actually reading `button_press` (and deciding the `poll_answer`/media scope question above) - this fix does not work end-to-end without that half landing too.
- Retest the exact `select_shoe` flow end-to-end once both halves are implemented.

### Where

- `telegram_gateway_application/utilities/utils_telegram/utilities/button_prompt_handler.py`: `register_bot_button()` (new `task_id` param), `validate_bot_callback()` (return `task_id`).
- `telegram_gateway_application/utilities/utils_queue/message_handler.py`: `_build_button_rows()` (thread `task_id` through).
- `telegram_gateway_application/utilities/utils_telegram/gateway_inbound.py::_handle_update()` (callback branch - new `button_press` push, modelled on `poll_response_handler.py::_push_poll_answer()`).
- Cross-reference (required, not optional): `bot_sanctuary/CODE_TODO.md`'s new entry on `_process_batch()`'s "only reads `text`" gap - this fix is incomplete without that side landing too.
- Cross-reference: `bot_sanctuary/CODE_TODO.md` (no counterpart entry added there for this issue - the gap is entirely `telegram_gateway`-side; `bot_sanctuary` already assumes a button press round-trips somehow, it just doesn't yet).

---

## BUG — a Tier 1 `delivery_failed` retry can never resolve once the task's `completed` marker has already run; plain `send_message()` has no pre-send length guard unlike `send_message_with_buttons()`

Status: **Scoped (2026-09-16) - not yet implemented.** Raised directly by the user ("bot failed to respond to a message", ~09:17am) - traced against both logs for `task_id=9478f79c8fd74cdbb6dd71aa1f0ec650`, per the same instruction as the entry above.

### Context

`bot_sanctuary` publishes a `text` message and its terminal `completed` marker back-to-back, immediately after generating a reply - it does not wait to learn whether the send to Telegram actually succeeded before marking the task done (there is no contract anywhere that says it should - `completed` means "no further payloads are expected for this `task_id`," not "the last payload was confirmed delivered"). Separately, `send_message_with_buttons()` (`button_prompt_handler.py`) explicitly pre-checks `len(text) > TELEGRAM_MESSAGE_MAX_LENGTH` (4096, Telegram's own hard cap) before ever calling Telegram - but the plain `send_message()` path, which `_handle_text()` uses whenever a reply carries no buttons, has no equivalent check anywhere. These two facts combine into a real, reproduced failure mode.

### Symptom / Evidence

Both logs, 09:17:33-09:18:36, `task_id=9478f79c8fd74cdbb6dd71aa1f0ec650`:

1. `bot_sanctuary` runs 4 `WebSearch` calls, self-corrects a non-JSON first draft (per `chat.json`'s enforced JSON-only contract), then publishes `text` (a long, multi-paragraph reply with ~10 citation links) followed immediately by `completed` for the task.
2. `telegram_gateway` attempts the send via plain `send_message()` (no buttons on this reply) - Telegram rejects it with **400 Bad Request**, logged and *not retried* (`gateway_outbound.py`'s own documented Tier 1 behaviour for a non-connection rejection). A Tier 1 `delivery_failed` event is pushed for this `task_id`.
3. `telegram_gateway` then processes the already-queued `completed` marker from step 1 - `_handle_completed()` deletes the task's Redis mapping unconditionally (`"Task ... completed. Is mapping deleted successfully: True"`).
4. `bot_sanctuary` receives the `delivery_failed` event, runs a third Claude turn for the same `task_id`, and republishes `text` + `completed` for it - but the mapping is already gone (step 3). Both are dropped: *"No task mapping found in Redis for task_id=... Message dropped."* The user receives nothing for this exchange.

### Root Cause

Two independent, compounding gaps, confirmed against source:

1. **No pre-send length guard on the plain-text path.** `send_message()` (`gateway_outbound.py`) has no equivalent of `send_message_with_buttons()`'s own `len(text) > settings.TELEGRAM_MESSAGE_MAX_LENGTH` check - an overlong reply with no buttons attached is sent straight to Telegram and only ever caught by Telegram's own 400 rejection, after the fact, rather than being pre-empted or split the way an overlong media caption already is (`_send_media_with_caption()`'s existing caption-overflow-into-follow-up pattern).
2. **A `task_id`'s Redis mapping is deleted unconditionally on `completed`, with no awareness that a `delivery_failed` event for the same `task_id` might still be in flight and expecting an answer.** Once `_handle_completed()` runs, that `task_id` is permanently unusable for any further reply - including one the gateway's own Tier 1 mechanism explicitly asked `bot_sanctuary` to retry.

### Decisions (scoped fix, not yet implemented)

- **(a) - lower-risk, addresses the specific trigger seen today: give `_handle_text()`'s plain-send path the same length awareness `send_message_with_buttons()` already has**, most likely by extending `_send_media_with_caption()`'s existing "split the overflow into a follow-up message" pattern to plain text too, rather than only rejecting outright the way the buttoned path does today (a buttoned reply can't be split without detaching the buttons from the text; a plain reply has no such constraint). This alone would have prevented today's specific 400, without touching the `completed`/`delivery_failed` ordering at all.
- **(b) - deeper structural fix, covers *any* Tier 1 rejection reason, not just length: stop the `completed`/`delivery_failed` race from being able to happen at all.** Two candidate shapes, neither committed yet:
  - **(b1) - a `delivery_failed`-triggered corrective retry targets a *fresh* `task_id`**, rather than trying to republish against the original (already-closeable) one - mirrors how `bot_sanctuary`'s own coalescing mechanism already mints/reuses `task_id`s deliberately (see `bot_sanctuary/CODE_TODO.md`'s "message coalescing" entry) rather than assuming one is always safe to reuse. Needs no new state on `telegram_gateway`'s side.
  - **(b2) - `telegram_gateway` withholds deleting a `task_id`'s mapping on `completed` if a `delivery_failed` for that same `task_id` was just pushed and hasn't yet been superseded by a later reply.** Would need new tracking state (e.g. "this `task_id` has an outstanding Tier 1 retry expected") and a decision on how long to hold it open - more invasive than (b1), not preferred without a reason (b1) doesn't already cover.
  - **(b1) is the currently-preferred direction** - it requires a change only on `bot_sanctuary`'s side (which already owns `task_id` minting for a turn) rather than new gateway-side state, and doesn't need `telegram_gateway` to reason about "is a retry still pending for this closed task_id" at all.
- **(a) and (b) are independent and both worth doing** - (a) closes the length-specific trigger outright; (b) closes the general shape of the race for every other Tier 1 rejection reason (a bad `chat_id`, an unexpected Telegram-side validation failure, etc.), which (a) alone would not cover.

### Open Questions

1. Whether (b) is worth building immediately given (a) closes today's specific trigger, or whether it's acceptable to land (a) first and revisit (b) only if a non-length Tier 1 rejection is ever actually observed in practice.
2. If (b1) is adopted, the exact mechanism `bot_sanctuary`'s `delivery_failed` handling would use to obtain a fresh `task_id` for its corrective retry - this is a cross-service decision, not something this side can finalise alone.

### Follow-up Work

- Implement (a): length-aware overflow handling for `_handle_text()`'s plain-send path.
- Once (b1) vs (b2) is decided (jointly with whoever owns `bot_sanctuary`'s `call_dispatch_handler.py`/`session_worker.py`), implement whichever side of it belongs here.
- Add a matching entry to `bot_sanctuary/CODE_TODO.md` once (b1)'s exact shape is agreed, since it requires a change on that side too.

### Where

- `telegram_gateway_application/utilities/utils_telegram/gateway_outbound.py::send_message()`.
- `telegram_gateway_application/utilities/utils_telegram/utilities/button_prompt_handler.py::send_message_with_buttons()` (existing length-check pattern to extend/mirror).
- `telegram_gateway_application/utilities/utils_queue/message_handler.py::_handle_text()`, `_send_media_with_caption()` (existing overflow-split pattern to extend to plain text), `_handle_completed()`.
- Cross-reference: `bot_sanctuary/CODE_TODO.md` (a counterpart entry is still needed once (b1)'s shape is agreed - not added yet, since the exact mechanism isn't decided).
