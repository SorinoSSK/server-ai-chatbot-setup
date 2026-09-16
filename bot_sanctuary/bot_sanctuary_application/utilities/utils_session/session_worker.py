# =============================================================================
# File        : session_worker.py
# Description : Owns per-session task routing, coalescing, and lifecycle for the Bot Sanctuary application.
# Author      : SorinoSSK
# Created On  : 2026-09-09
#
# Features    :
#   - SessionWorker - one long-lived worker per session_id, coalescing queued messages into combined turns.
#   - Session registry management, including per-session on-disk directory lifecycle.
#   - Startup crash-recovery sweep requesting a session reset for sessions left dangling by a prior run.
#   - Admin-triggered and optional scheduled global session resets, decided by whether a reset sweep is already in progress.
#   - Graceful per-session and application-wide shutdown that drains and finishes outstanding work before exiting.
#   - Hands each coalesced batch's combined turn off to utils_calls/call_dispatch_handler.py::execute_dispatch_call(),
#     on this worker's own thread/publisher - the Call pipeline's own run-and-publish mechanics live there, not here.
#
# Notes       :
#   - stop() abandons whatever remains queued; shutdown()/retire() both drain it fully before exiting.
#   - Each SessionWorker's session_dir is a stable root (SESSION_DIR/<session_id>), not a randomly-named
#     per-generation directory - a session's own directory tree is only ever removed by clear_session_directory(),
#     called on the startup sweep (clear_all_session_directories()) and on an actual session reset (retire()'s own
#     exit path, or directly when no worker is active) - never merely because a new SessionWorker was constructed.
#     See CODE_TODO.md's "per-session on-disk directory" entry for the full history of this decision.
#   - retire()'s own exit-path cleanup (clear_session_directory()) is shared by two distinct callers: a global
#     session reset sweep (session_clear_request/SESSION_RESET_TIME), and a per-chat session_cleared confirmation
#     (utils_queue/message_handler.py::_handle_session_cleared()) - both need the same guarantee (drain whatever's
#     already in flight, only clean up once that's genuinely finished), so both reuse this one exit path rather
#     than each inventing their own.
#   - A global session reset may only ever be triggered by a whitelisted admin command or this application's own optional daily schedule - telegram_gateway has no authority to trigger one itself.
#   - The Call pipeline handed off to is deliberately minimal (Chat only, no handoff) - see CODE_TODO.md §5 Phase 3/4.
#   - See README.md for the full coalescing, crash-recovery, and session reset design.
#
# =============================================================================
# I M P O R T   H E A D E R

import shutil
import logging
import queue
import threading

from datetime import timedelta

from ...config import settings
from ..utilities import application_time
from ..utils_agents.agent_interface import terminate_session
from ..utils_calls import call_dispatch_handler
from ..utils_redis.database import mark_task_active, mark_task_complete, sweep_orphaned_sessions

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_sessions: dict[str, "SessionWorker"] = {}
_sessions_lock = threading.Lock()

# Tracks a currently in-progress global session reset sweep - the set of session_ids signalled to retire that haven't yet reported back in.
# Non-empty means a sweep is in progress; a further reset request arriving while non-empty is rejected rather than accepted.
_pending_retirements: set[str] = set()
_sweep_lock = threading.Lock()

# Signals the background loop started by start_session_reset_schedule() to stop.
_session_reset_schedule_stop_event = threading.Event()
_session_reset_schedule_thread: threading.Thread | None = None

# =============================================================================

def get_or_create_session_worker(session_id: str) -> "SessionWorker":
    """
    Retrieves the SessionWorker owning session_id, creating and starting one if this is a new session.

    Args:
        session_id (str):
            Session identifier to look up or create a worker for.

    Returns:
        SessionWorker:
            The existing or newly created worker for this session.
    """
    with _sessions_lock:
        worker = _sessions.get(session_id)
        if worker is None:
            worker = SessionWorker(session_id)
            _sessions[session_id] = worker
            worker.start()
            logger.info(f"Created SessionWorker for session_id={session_id}.")
        else:
            logger.debug(f"Reusing existing SessionWorker for session_id={session_id}.")

        return worker

def clear_session_directory(session_id: str) -> None:
    """
    Removes session_id's entire on-disk session directory (every Call/LLM leaf beneath it), and terminates any
    live LLM session(s) anchored to it, if either exists.

    Args:
        session_id (str):
            Session identifier whose on-disk directory (settings.SESSION_DIR/<session_id>) should be removed.

    Returns:
        None

    Notes:
        - terminate_session() runs first, deliberately - it tears down a live, in-memory LLM connection (today,
          only Claude's persistent per-generation client - see claude_session_service.py) still anchored to
          session_root or one of its <call_type>/<llm_type> leaves, so nothing is left holding a reference to a
          cwd that's about to be deleted out from under it. Best-effort itself, same convention as the rmtree
          below - a provider-side failure is logged internally by terminate_session()'s own call chain, not
          raised here.
        - Best-effort - a failure to remove the directory itself is logged but non-fatal.
        - The only two callers of this function are clear_all_session_directories() (the startup sweep) and
          whichever path decided this session_id's turn(s) have already finished - never while a turn could
          still be in flight. See this module's own header Notes and utils_queue/message_handler.py's
          _handle_session_cleared() for how that guarantee is maintained.
    """
    session_root = settings.SESSION_DIR / session_id
    terminate_session(session_root)

    try:
        shutil.rmtree(session_root)
    except FileNotFoundError:
        logger.debug(f"No on-disk session directory existed for session_id={session_id} - nothing to remove.")
    except Exception:
        logger.exception(f"Failed to remove on-disk session directory for session_id={session_id}.")
    else:
        logger.info(f"Removed on-disk session directory for session_id={session_id}.")

def clear_all_session_directories() -> None:
    """
    Removes every on-disk session directory under SESSION_DIR, unconditionally - the startup sweep that
    guarantees a session is reset on every bot_sanctuary startup, not only on an explicit session reset.

    Args:
        None

    Returns:
        None

    Notes:
        - Intended to run once, as the very first step of initialise_application() - before RabbitMQ connects,
          before the message consumer starts, and before any SessionWorker can possibly exist. Every directory
          found at that point is therefore guaranteed to be left over from a prior process lifetime - nothing in
          this process could be using any of them yet, so this is safe regardless of whether a prior turn
          finished cleanly or not (see this module's own header Notes).
        - Delegates per-session_id removal to the existing clear_session_directory() - same best-effort
          behaviour, same terminate_session() + rmtree pairing, just swept across every session_id found rather
          than one at a time.
        - A no-op (logged) if SESSION_DIR doesn't exist yet - main.py already creates it before
          initialise_application() ever runs, but this guards against being called in a context where that
          ordering doesn't hold.
    """
    if not settings.SESSION_DIR.is_dir():
        logger.info("SESSION_DIR does not exist yet - nothing to clear at startup.")
    else:
        cleared = 0
        for session_root in settings.SESSION_DIR.iterdir():
            if session_root.is_dir():
                clear_session_directory(session_root.name)
                cleared += 1

        logger.info(f"Startup sweep cleared {cleared} leftover session director{'y' if cleared == 1 else 'ies'} under SESSION_DIR.")

def remove_session_worker(session_id: str) -> "SessionWorker | None":
    """
    Removes and returns the SessionWorker owning session_id, if one exists.

    Args:
        session_id (str):
            Session identifier to remove.

    Returns:
        SessionWorker | None:
            The removed worker, if one existed; otherwise None.

    Notes:
        - Removal from the registry does not stop the worker's thread - the caller is responsible for calling stop() on it.
    """
    with _sessions_lock:
        return _sessions.pop(session_id, None)

def resync_orphaned_sessions() -> None:
    """
    Requests a session reset from telegram_gateway for every session left dangling by a prior run.

    Args:
        None

    Returns:
        None

    Notes:
        - Intended to run once at startup, before the message consumer starts.
        - A failed request leaves that session's entries untouched, to be retried on the next startup.
        - See README.md for the crash-recovery design and its known interim limitations.
    """
    from ..utils_queue.queue import RabbitMQPublisher

    active = sweep_orphaned_sessions()
    if not active:
        logger.info("No orphaned sessions found at startup - nothing to resync.")
    else:
        by_session: dict[str, list[str]] = {}
        for task_id, session_id in active.items():
            by_session.setdefault(session_id, []).append(task_id)

        publisher = RabbitMQPublisher()
        try:
            for session_id, task_ids in by_session.items():
                if publisher.publish({"task_id": task_ids[0], "type": "session_reset"}):
                    for task_id in task_ids:
                        mark_task_complete(task_id)
                    logger.warning(
                        f"Requested session_reset for orphaned session_id={session_id} "
                        f"({len(task_ids)} task_id(s) left dangling by a prior run)."
                    )
                else:
                    logger.error(
                        f"Failed to request session_reset for orphaned session_id={session_id} - "
                        f"will retry on next application startup."
                    )
        finally:
            publisher.close()

def session_clear_response(task_id: str) -> None:
    """
    Responds to an accepted session_clear_request by immediately publishing the corresponding session_reset back to telegram_gateway.

    Published before any session is actually cleared, so telegram_gateway's own reset-application timing is never forced to wait on this application finishing its own clearing sweep.

    Args:
        task_id (str):
            The task_id the session_clear_request arrived on, already validated non-empty by the caller. Echoed back on session_reset so telegram_gateway can close it out.

    Returns:
        None

    Notes:
        - Called only from the accept path of handle_session_clear_request().
        - A failed publish is not retried or backstopped - see README.md's Limitations.
        - Uses its own disposable RabbitMQPublisher, not the long-lived one a SessionWorker owns for its own turn traffic.
    """
    from ..utils_queue.queue import RabbitMQPublisher

    publisher = RabbitMQPublisher()
    try:
        if publisher.publish({"task_id": task_id, "type": "session_reset"}):
            logger.info(f"Accepted session_clear_request (task_id={task_id}) - published session_reset.")
        else:
            logger.error(f"Failed to publish session_reset for accepted session_clear_request (task_id={task_id}) - telegram_gateway will not learn this request was accepted.")
    finally:
        publisher.close()

def _reject_session_clear_request(task_id: str) -> None:
    """
    Rejects an inbound session_clear_request because a sweep is already in progress.

    Closes out the rejected request's own task_id with a literal error reply, and does nothing else - the currently in-progress sweep is left untouched.

    Args:
        task_id (str):
            The task_id the rejected session_clear_request arrived on.

    Returns:
        None

    Notes:
        - Sent as an error, not a silent completion, so the requesting admin sees why nothing happened.
        - A failed publish is not retried or backstopped - see README.md's Limitations.
        - Uses its own disposable RabbitMQPublisher, same pattern as session_clear_response().
    """
    from ..utils_queue.queue import RabbitMQPublisher

    publisher = RabbitMQPublisher()
    try:
        payload = {
            "task_id": task_id,
            "type": "error",
            "error_type": "session_reset_in_progress",
            "message": "A global session reset is already in progress - please try again once it finishes."
        }
        if publisher.publish(payload):
            logger.info(f"Rejected session_clear_request (task_id={task_id}) - a session_clear_request sweep is already in progress.")
        else:
            logger.error(f"Failed to publish rejection for session_clear_request (task_id={task_id}) while a sweep was already in progress - its task_id may hang on telegram_gateway's side.")
    finally:
        publisher.close()

def _report_retirement(session_id: str) -> None:
    """
    Reports that session_id has finished retiring, clearing it from the currently in-progress sweep.

    Args:
        session_id (str):
            The session_id that just finished retiring.

    Returns:
        None

    Notes:
        - A no-op (logged) if session_id was not actually part of a pending sweep.
        - The sweep is considered complete once every signalled session has reported in this way.
    """
    with _sweep_lock:
        if session_id not in _pending_retirements:
            logger.debug(f"SessionWorker for session_id={session_id} retired, but is not part of any currently in-progress session_clear_request sweep - report ignored.")
            return
        else:
            _pending_retirements.discard(session_id)
            remaining = len(_pending_retirements)

    if remaining == 0:
        logger.info(f"session_id={session_id} was the last pending retirement - session_clear_request sweep complete.")
    else:
        logger.info(f"session_id={session_id} retired - sweep still waiting on {remaining} more session(s).")

def _begin_session_clear_sweep() -> "list[SessionWorker] | None":
    """
    Decides atomically whether a new global session reset sweep may begin, snapshotting every currently active SessionWorker if so.

    Shared by both an inbound session_clear_request and the optional timed schedule, so the accept/reject decision and the snapshot step are made in exactly one place regardless of which one is asking.

    Args:
        None

    Returns:
        list[SessionWorker] | None:
            The snapshot of every SessionWorker to retire, possibly empty, if accepted; None if a sweep is already in progress and this attempt must be rejected/skipped instead.
    """
    with _sweep_lock:
        if _pending_retirements:
            return None
        else:
            with _sessions_lock:
                snapshot = list(_sessions.values())
            _pending_retirements.update(worker.session_id for worker in snapshot)
            return snapshot

def _push_scheduled_session_reset() -> None:
    """
    Publishes the session_reset for a scheduled timed reset, immediately, before anything is actually cleared.

    Args:
        None

    Returns:
        None

    Notes:
        - Carries no task_id, since a timed reset has no requesting task to echo back.
        - A failed publish is not retried - the next scheduled occurrence (24h later) is the retry.
        - Uses its own disposable RabbitMQPublisher, same pattern as session_clear_response().
    """
    from ..utils_queue.queue import RabbitMQPublisher

    publisher = RabbitMQPublisher()
    try:
        if publisher.publish({"task_id": None, "type": "session_reset"}):
            logger.info("Published scheduled session_reset (SESSION_RESET_TIME).")
        else:
            logger.error("Failed to publish scheduled session_reset (SESSION_RESET_TIME) - telegram_gateway will not learn a reset just began.")
    finally:
        publisher.close()

def handle_session_clear_request(task_id: str) -> None:
    """
    Accepts or rejects an inbound session_clear_request, decided purely by whether a sweep is already in progress.

    On accept, publishes session_reset and signals every currently active session to retire, concurrently. On reject, the request's own task_id is closed with an error and the in-progress sweep is left untouched.

    Args:
        task_id (str):
            The task_id the session_clear_request arrived on, already validated non-empty by the caller.

    Returns:
        None

    Notes:
        - An empty snapshot (no active SessionWorkers at all) is accepted the same as any other - there is simply nothing to wait for, so the next request is immediately eligible too.
    """
    snapshot = _begin_session_clear_sweep()
    if snapshot is None:
        _reject_session_clear_request(task_id)
    else:
        session_clear_response(task_id)
        if not snapshot:
            logger.info("session_clear_request accepted - no active SessionWorkers to clear.")
        else:
            for worker in snapshot:
                worker.retire()
            logger.info(f"session_clear_request accepted - signalled {len(snapshot)} active SessionWorker(s) to retire.")

def trigger_timed_session_reset() -> None:
    """
    Fires the optional daily timed global session reset, sharing the same accept/reject sweep mechanism as an inbound session_clear_request.

    Args:
        None

    Returns:
        None

    Notes:
        - Publishes session_reset with no task_id, since there is no requesting task to echo back. telegram_gateway has no authority to initiate this itself - it only ever reacts to whichever trigger produced it.
        - If a sweep is already in progress, this occurrence is silently skipped rather than rejected - there is no requesting task_id to notify of anything. The next scheduled occurrence (24h later) is the retry.
        - Called only by the background loop started by start_session_reset_schedule().
    """
    snapshot = _begin_session_clear_sweep()
    if snapshot is None:
        logger.info("Skipped scheduled session reset (SESSION_RESET_TIME) - a session_clear_request sweep is already in progress.")
    else:
        _push_scheduled_session_reset()
        if not snapshot:
            logger.info("Scheduled session reset (SESSION_RESET_TIME) accepted - no active SessionWorkers to clear.")
        else:
            for worker in snapshot:
                worker.retire()
            logger.info(f"Scheduled session reset (SESSION_RESET_TIME) accepted - signalled {len(snapshot)} active SessionWorker(s) to retire.")

def _seconds_until_next_session_reset_time() -> float:
    """
    Computes the number of seconds from now until the next occurrence of settings.SESSION_RESET_TIME.

    Args:
        None

    Returns:
        float:
            Seconds until the next occurrence - today's, if it hasn't passed yet; otherwise tomorrow's.

    Notes:
        - Only ever called from within a guard that has already confirmed settings.SESSION_RESET_TIME is set.
        - "now" comes from application_time(), timezone-aware and anchored to settings.TZ - SESSION_RESET_TIME itself is a plain hour/minute, interpreted as a wall-clock time in that same zone.
        - A target exactly equal to now (the boundary itself) is treated as already passed, rolling to tomorrow - avoids a zero-second wait firing the reset twice back to back.
    """
    now = application_time()
    target = now.replace(hour=settings.SESSION_RESET_TIME.hour, minute=settings.SESSION_RESET_TIME.minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)

    return (target - now).total_seconds()

def _session_reset_schedule_loop() -> None:
    """
    Background loop calling trigger_timed_session_reset() once every 24h at settings.SESSION_RESET_TIME, until stop_session_reset_schedule() is called.

    Args:
        None

    Returns:
        None

    Notes:
        - Recomputes the wait duration to the next occurrence on every iteration, rather than assuming a fixed 24h period - keeps this correct however far through the day it happened to start.
    """
    while not _session_reset_schedule_stop_event.wait(_seconds_until_next_session_reset_time()):
        trigger_timed_session_reset()

def start_session_reset_schedule() -> None:
    """
    Starts the background daily timed session reset loop, if SESSION_RESET_TIME is configured and one is not already running.

    Args:
        None

    Returns:
        None

    Notes:
        - No-op (logged at info) if SESSION_RESET_TIME is unset - the default, meaning no timed reset at all.
        - No-op if already running (defensive guard, not the primary check) - mirrors the style of other start_*() functions in this codebase (e.g. telegram_gateway's start_pending_reset_ceiling_sweep()).
        - Runs until stop_session_reset_schedule() is called.
    """
    global _session_reset_schedule_thread

    if settings.SESSION_RESET_TIME is None:
        logger.info("SESSION_RESET_TIME is unset - no timed session reset scheduled.")
    elif _session_reset_schedule_thread is not None and _session_reset_schedule_thread.is_alive():
        return
    else:
        _session_reset_schedule_stop_event.clear()
        _session_reset_schedule_thread = threading.Thread(target=_session_reset_schedule_loop, daemon=True)
        _session_reset_schedule_thread.start()
        logger.info(f"Started timed session reset schedule - next at {settings.SESSION_RESET_TIME.strftime('%H:%M')} {settings.TZ} (daily).")

def stop_session_reset_schedule() -> None:
    """
    Stops the background timed session reset loop, if running.

    Args:
        None

    Returns:
        None

    Notes:
        - Does not wait for the loop to actually terminate - it will exit on its next wait() wake-up, which may be up to just under 24h away depending on SESSION_RESET_TIME. Harmless to call unconditionally even if SESSION_RESET_TIME is unset/the loop was never started - setting an Event nothing is waiting on is a no-op.
    """
    _session_reset_schedule_stop_event.set()

def shutdown_all_session_workers() -> None:
    """
    Signals every active SessionWorker to finish its outstanding work, then waits for each to stop.

    Args:
        None

    Returns:
        None

    Notes:
        - Intended to run once during application shutdown, after the message consumer has already stopped.
        - Distinct from SessionWorker.stop(), which abandons queued work instead of draining it.
        - Bounded by SESSION_SHUTDOWN_TIMEOUT_SECONDS per worker.
    """
    with _sessions_lock:
        workers = list(_sessions.values())

    if not workers:
        logger.info("No active SessionWorkers at shutdown - nothing to drain.")
    else:
        logger.info(f"Signalling {len(workers)} active SessionWorker(s) to finish their last queued task before shutdown.")
        for worker in workers:
            worker.shutdown()

        timeout = settings.SESSION_SHUTDOWN_TIMEOUT_SECONDS or None
        for worker in workers:
            worker._thread.join(timeout=timeout)
            if worker._thread.is_alive():
                logger.error(
                    f"SessionWorker for session_id={worker.session_id} did not finish within "
                    f"SESSION_SHUTDOWN_TIMEOUT_SECONDS={settings.SESSION_SHUTDOWN_TIMEOUT_SECONDS}s - "
                    f"abandoning it (process is exiting regardless)."
                )
            else:
                logger.info(f"SessionWorker for session_id={worker.session_id} finished its last task and stopped cleanly.")

def _extract_item_text(item: dict) -> str:
    """
    Resolves the readable instruction text for a single coalesced batch item.

    Args:
        item (dict):
            One task payload from a coalesced batch.

    Returns:
        str:
            item["text"] if non-empty; otherwise a description built from item["button_press"] if
            present; otherwise a description built from item["poll_answer"] if present; otherwise "".

    Notes:
        - button_press/poll_answer are telegram_gateway's own gateway_inbound.py::_push_button_press()/
          poll_response_handler.py::_push_poll_answer() payloads - each always accompanied by text=""
          on that same payload (see their own Notes), so checking text first and falling back to
          whichever of the two is present is safe and requires no ordering assumption between them -
          a single payload never carries both at once.
        - button_press carries {"purpose", "payload"} exactly as the persona itself defined when it
          built the button (chat.json's button spec) - unlike poll_answer below, this can directly
          embed identifying content (e.g. {"shoe_name": "Cloud 5"}) rather than relying on the
          persona's own conversation history to make sense of a bare index.
        - poll_answer carries Telegram's own selected option *indices* (option_ids), not the option's
          own text - telegram_gateway has no lookup back to the original poll's question/options at
          this point, so this can only describe the answer by index. Relies on the persona's own
          conversation history (the poll it just sent, moments earlier in the same session) to make
          sense of which index means what.
        - poll_timed_out (a distinct payload - {"task_id", "type": "poll_timed_out"}, no "text"/
          "button_press"/"poll_answer" at all) still resolves to "" here - not handled by this
          function, out of scope of this change.
    """
    text = item.get("text") or ""
    if text:
        return text
    else:
        button_press = item.get("button_press")
        if button_press:
            purpose = button_press.get("purpose")
            payload = button_press.get("payload") or {}
            return f"[The user pressed a button - purpose: {purpose!r}, payload: {payload}.]"
        else:
            poll_answer = item.get("poll_answer")
            if poll_answer:
                indices = ", ".join(str(option_id) for option_id in poll_answer)
                return f"[The user answered the poll by selecting option index/indices: {indices}.]"
            else:
                return ""

def _close_intermediate_task_ids(task_ids: list[str]) -> None:
    """
    Publishes a silent completion marker for every task_id, on a dedicated, disposable publish connection.

    Args:
        task_ids (list[str]):
            Every task_id in a coalesced batch except the last one.

    Returns:
        None

    Notes:
        - Runs on its own short-lived thread, so it does not delay the owning session worker.
    """
    from ..utils_queue.queue import RabbitMQPublisher

    publisher = RabbitMQPublisher()
    try:
        for task_id in task_ids:
            if publisher.publish({"task_id": task_id, "type": "completed"}):
                mark_task_complete(task_id)
                logger.info(f"Closed intermediate coalesced task_id={task_id} (completed, no reply).")
            else:
                logger.error(f"Failed to close intermediate coalesced task_id={task_id} - it will remain open until a future session reset.")
    finally:
        publisher.close()

class SessionWorker:
    """
    Owns one session_id's entire task inbox end-to-end, for the worker's whole lifetime.

    Example:
        worker = get_or_create_session_worker(session_id)
        worker.submit(task_payload)
        ...
        worker.stop()
    """

    def __init__(self, session_id: str):
        from ..utils_queue.queue import RabbitMQPublisher

        self.session_id = session_id
        self.session_dir = settings.SESSION_DIR / session_id
        self.inbox: queue.Queue = queue.Queue(maxsize=settings.SESSION_INBOX_MAX_SIZE)
        self.dispatch_queue: queue.Queue = queue.Queue()
        self._publisher = RabbitMQPublisher()
        self._stop_event = threading.Event()
        self._shutdown_event = threading.Event()
        self._clear_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"SessionWorker-{session_id}")

    def start(self) -> None:
        """
        Starts this worker's background thread.

        Args:
            None

        Returns:
            None
        """
        self._thread.start()

    def submit(self, data: dict) -> bool:
        """
        Queues a task payload for this session, marking its task_id durably active first.

        Args:
            data (dict):
                A decoded queue message - a task, poll_timed_out, or delivery_failed payload.

        Returns:
            bool:
                True if queued successfully; otherwise False if the inbox is full.

        Notes:
            - A full inbox drops the newest arrival and logs it critically, rather than blocking the shared message consumer.
        """
        task_id = data.get("task_id")
        try:
            self.inbox.put_nowait(data)
        except queue.Full:
            logger.critical(
                f"Session inbox full (session_id={self.session_id}, max={settings.SESSION_INBOX_MAX_SIZE}) - "
                f"dropping task_id={task_id}."
            )
            return False
        else:
            if task_id:
                mark_task_active(task_id, self.session_id)
            else:
                logger.error(
                    f"Queued session-routed message with missing task_id for session_id={self.session_id} - "
                    f"crash-recovery tracking skipped for it."
                )
            return True

    def stop(self) -> None:
        """
        Signals this worker to stop after its current batch, without draining whatever else is queued.

        Args:
            None

        Returns:
            None

        Notes:
            - Immediate, not graceful - used when the session has already been cleared on telegram_gateway's side.
        """
        self._stop_event.set()

    def shutdown(self) -> None:
        """
        Signals this worker to finish processing whatever is currently queued, then stop.

        Args:
            None

        Returns:
            None

        Notes:
            - Does not block - the caller is responsible for joining this worker's thread afterwards.
        """
        self._shutdown_event.set()

    def retire(self) -> None:
        """
        Signals this worker to finish processing whatever is currently queued - including a batch already in
        progress - then permanently retire: removing itself from the session registry and clearing its on-disk
        session directory (and terminating any live LLM session anchored to it - see clear_session_directory()).

        A third terminal path alongside stop()/shutdown(). Has two distinct callers today, both of which need the
        same guarantee (nothing torn down while a turn could still be in flight - see this module's own header
        Notes): the per-session exit action a global session_clear_request/SESSION_RESET_TIME sweep signals every
        session with, and the exit action utils_queue/message_handler.py::_handle_session_cleared() signals a
        single session with once telegram_gateway confirms that specific session_id has already been reset.

        Args:
            None

        Returns:
            None

        Notes:
            - Same draining behaviour as shutdown() - finishes whatever is already queued (including anything
              already in progress) rather than abandoning it. Differs only in its exit action: shutdown() simply
              stops, retire() also removes this session from the registry and clears its on-disk directory.
            - Does not publish anything itself - for a global sweep, session_reset already happened once, at
              accept-time, for the whole sweep this retirement is part of; for a per-chat session_cleared
              confirmation, telegram_gateway has already applied that reset on its own side by the time this is
              ever signalled, so there is nothing further to publish either way.
            - Does not block - the caller is not expected to join this worker's thread; a retiring session simply
              removes itself from the registry once it finishes.
            - Reports its own retirement once finished (_report_retirement()) - a no-op (logged at debug) unless
              this retirement is actually part of a currently in-progress global sweep, which is what allows a
              future global session reset to be accepted again once every currently-pending session in that
              sweep has done the same. A session_cleared-triggered retirement is never part of any sweep, so this
              is always a harmless no-op on that path.
        """
        self._clear_event.set()

    def _run(self) -> None:
        """
        Main loop - waits for a queued item, drains and coalesces whatever else is ready, processes the batch, and repeats until stopped.

        Args:
            None

        Returns:
            None

        Notes:
            - stop() takes effect immediately, abandoning whatever remains queued.
            - shutdown()/retire() only take effect once the inbox is genuinely empty, so a backlog queued as either begins is still fully processed.
            - retire()'s own exit action (registry removal + on-disk directory cleanup) runs here, once the loop actually exits - regardless of whether it exited by draining fully or by stop() abandoning what was left, since by that point retirement was already requested either way.
        """
        while not self._stop_event.is_set():
            try:
                first = self.inbox.get(timeout=1)
            except queue.Empty:
                if self._shutdown_event.is_set() or self._clear_event.is_set():
                    break
                else:
                    continue
            else:
                batch = [first]
                while True:
                    try:
                        batch.append(self.inbox.get_nowait())
                    except queue.Empty:
                        break

                self._process_batch(batch)

        self._publisher.close()

        if self._clear_event.is_set():
            remove_session_worker(self.session_id)
            clear_session_directory(self.session_id)
            _report_retirement(self.session_id)
            logger.info(f"SessionWorker for session_id={self.session_id} finished its last queued task and retired (session_cleared or a global session reset).")
        else:
            logger.info(f"SessionWorker for session_id={self.session_id} stopped.")

    def _process_batch(self, batch: list[dict]) -> None:
        """
        Coalesces a batch of queued messages into a single turn, then runs and publishes that turn.

        Args:
            batch (list[dict]):
                One or more task payloads belonging to this session, oldest first.

        Returns:
            None

        Notes:
            - Every task_id in the batch except the last is closed out immediately, so it does not stay open on telegram_gateway's side for the turn's whole duration.
            - The batch's text fields (falling back to a poll_answer description via _extract_item_text() when text is empty - see that function's own Notes) are combined into one input, on the assumption that consecutive messages arriving before a turn starts represent one continued thought.
            - The combined turn itself is delegated to utils_calls/call_dispatch_handler.py::execute_dispatch_call(), passed this worker's own self.dispatch_queue - see its own docstring for what runs the pipeline and publishes the outcome. Kept out of this class deliberately - a SessionWorker's own job is thread/inbox/lifecycle management, not the Call pipeline's run-and-publish mechanics.
            - self.session_dir is also passed through, purely so a Call/provider that wants continuity across turns (Claude's cwd-keyed session resume, today - see claude_interface.py) has a stable, per-generation directory to anchor it to. This SessionWorker never reads/writes anything in it itself.
        """
        task_ids = [item.get("task_id") for item in batch if item.get("task_id")]
        if not task_ids:
            logger.error(f"session_id={self.session_id}: coalesced batch contained no usable task_id - dropped: {batch}")
        else:
            if len(task_ids) > 1:
                threading.Thread(
                    target=_close_intermediate_task_ids,
                    args=(task_ids[:-1],),
                    daemon=True,
                    name=f"SessionWorker-{self.session_id}-closer"
                ).start()
            else:
                logger.debug(f"session_id={self.session_id}: single-message batch (task_id={task_ids[0]}) - no intermediate task_ids to close.")

            final_task_id = task_ids[-1]
            combined_text = "\n".join(text for text in (_extract_item_text(item) for item in batch) if text.strip())

            logger.info(
                f"session_id={self.session_id}: coalesced {len(batch)} message(s) (task_ids={task_ids}) into one "
                f"turn (final task_id={final_task_id})."
            )
            call_dispatch_handler.execute_dispatch_call(self._publisher, self.session_id, final_task_id, combined_text, self.dispatch_queue, self.session_dir)

# =============================================================================
