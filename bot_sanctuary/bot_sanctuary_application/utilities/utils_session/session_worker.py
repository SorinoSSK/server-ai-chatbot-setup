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
#
# Notes       :
#   - stop() abandons whatever remains queued; shutdown()/retire() both drain it fully before exiting.
#   - Each SessionWorker gets a fresh, randomly-named session directory, so a future session-resume feature never reuses a stale working directory.
#   - A global session reset may only ever be triggered by a whitelisted admin command or this application's own optional daily schedule - telegram_gateway has no authority to trigger one itself.
#   - See README.md for the full coalescing, crash-recovery, and session reset design.
#
# =============================================================================
# I M P O R T   H E A D E R

import uuid
import shutil
import logging
import queue
import threading

from datetime import timedelta

from ...config import settings
from ..utilities import application_time
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
    Removes session_id's entire on-disk session directory (every generation), if one exists.

    Args:
        session_id (str):
            Session identifier whose on-disk directory (settings.SESSION_DIR/<session_id>) should be removed.

    Returns:
        None

    Notes:
        - Best-effort - a failure is logged but non-fatal.
    """
    session_root = settings.SESSION_DIR / session_id
    try:
        shutil.rmtree(session_root)
    except FileNotFoundError:
        logger.debug(f"No on-disk session directory existed for session_id={session_id} - nothing to remove.")
    except Exception:
        logger.exception(f"Failed to remove on-disk session directory for session_id={session_id}.")
    else:
        logger.info(f"Removed on-disk session directory for session_id={session_id}.")

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
        self.session_dir = settings.SESSION_DIR / session_id / uuid.uuid4().hex
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.inbox: queue.Queue = queue.Queue(maxsize=settings.SESSION_INBOX_MAX_SIZE)
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
        Signals this worker to finish processing whatever is currently queued, then permanently retire - removing itself from the session registry and clearing its on-disk session directory.

        A third terminal path alongside stop()/shutdown() - the per-session exit action a global session_clear_request sweep signals every session with.

        Args:
            None

        Returns:
            None

        Notes:
            - Same draining behaviour as shutdown() - finishes whatever is already queued rather than abandoning it. Differs only in its exit action: shutdown() simply stops, retire() also removes this session from the registry and clears its on-disk directory.
            - Does not publish session_reset itself - that publish already happened once, at accept-time, for the whole sweep this retirement is part of.
            - Does not block - the caller is not expected to join this worker's thread; a retiring session simply removes itself from the registry once it finishes.
            - Reports its own retirement once finished, which is what allows a future global session reset to be accepted again once every currently-pending session has done the same.
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
            logger.info(f"SessionWorker for session_id={self.session_id} finished its last queued task and retired (session_clear_request sweep).")
        else:
            logger.info(f"SessionWorker for session_id={self.session_id} stopped.")

    def _process_batch(self, batch: list[dict]) -> None:
        """
        Coalesces a batch of queued messages into a single turn.

        Args:
            batch (list[dict]):
                One or more task payloads belonging to this session, oldest first.

        Returns:
            None

        Notes:
            - Every task_id in the batch except the last is closed out immediately, so it does not stay open on telegram_gateway's side for the turn's whole duration.
            - The batch's text fields are combined into one input, on the assumption that consecutive messages arriving before a turn starts represent one continued thought.
            - The agent Call pipeline itself is not yet implemented - this currently only logs what would happen. See CODE_TODO.md §5.
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
            combined_text = "\n".join(text for text in ((item.get("text") or "") for item in batch) if text.strip())

            logger.info(
                f"session_id={self.session_id}: coalesced {len(batch)} message(s) (task_ids={task_ids}) into one "
                f"turn - agent Call pipeline not yet implemented. combined_text={combined_text!r}. "
                f"The eventual reply must be published against task_id={final_task_id}."
            )
            # TODO: invoke the agent Call pipeline, publish the reply, then mark_task_complete(final_task_id).

# =============================================================================
