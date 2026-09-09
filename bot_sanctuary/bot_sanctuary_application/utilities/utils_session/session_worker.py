# =============================================================================
# File        : session_worker.py
# Description : Owns per-session task routing, coalescing, and lifecycle for the Bot Sanctuary application.
# Author      : SorinoSSK
# Created On  : 2026-09-09
#
# Features    :
#   - SessionWorker - one long-lived worker per session_id, coalescing queued messages into combined turns.
#   - Session registry management via get_or_create_session_worker() / remove_session_worker().
#   - Startup crash-recovery sweep requesting a session reset for sessions left dangling by a prior run.
#   - Graceful, application-wide shutdown that drains and finishes each worker's outstanding work.
#
# Notes       :
#   - stop() abandons whatever remains queued; shutdown() drains it fully - see each method's own docstring.
#   - See README.md for the full coalescing, crash-recovery, and shutdown design rationale.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging
import queue
import threading

from ...config import settings
from ..utils_redis.database import mark_task_active, mark_task_complete, sweep_orphaned_sessions

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_sessions: dict[str, "SessionWorker"] = {}
_sessions_lock = threading.Lock()

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
        - Intended to run once at startup, before the message consumer starts, so no new task can mutate the active-task record while this sweep is in progress.
        - A failed request leaves that session's entries untouched, to be retried on the next application startup rather than lost.
        - See README.md and CODE_TODO.md §3 for the crash-recovery design and its known interim limitations.
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

def shutdown_all_session_workers() -> None:
    """
    Signals every active SessionWorker to finish its outstanding work, then waits for each to stop.

    Args:
        None

    Returns:
        None

    Notes:
        - Intended to run once during application shutdown, after the message consumer has already stopped.
        - Distinct from SessionWorker.stop() - this drains a worker's inbox as a final batch rather than abandoning it, since every queued item was already acknowledged off RabbitMQ.
        - Bounded by SESSION_SHUTDOWN_TIMEOUT_SECONDS per worker - a worker still alive once this elapses is logged and abandoned.
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
        - Runs on its own short-lived thread, so it does not delay whatever the owning session worker does next.
        - A failed publish is logged; the affected task_id remains open until a future session reset applies.
    """
    from ..utils_queue.queue import RabbitMQPublisher

    publisher = RabbitMQPublisher()
    try:
        for task_id in task_ids:
            if publisher.publish({"task_id": task_id, "type": "completed"}):
                mark_task_complete(task_id)
                logger.info(f"Closed intermediate coalesced task_id={task_id} (completed, no reply).")
            else:
                logger.error(
                    f"Failed to close intermediate coalesced task_id={task_id} - it will remain open on "
                    f"telegram_gateway until a future session_reset's PENDING_RESET_MAX_WAIT_SECONDS ceiling "
                    f"force-applies regardless."
                )
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
        self.inbox: queue.Queue = queue.Queue(maxsize=settings.SESSION_INBOX_MAX_SIZE)
        self._publisher = RabbitMQPublisher()
        self._stop_event = threading.Event()
        self._shutdown_event = threading.Event()
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
            - Immediate, not graceful - used when the session has already been cleared on telegram_gateway's side. Use shutdown() instead for a whole-application shutdown.
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

    def _run(self) -> None:
        """
        Main loop: waits for at least one queued item, drains whatever else is already ready alongside it, processes the combined batch, and repeats until stopped.

        Args:
            None

        Returns:
            None

        Notes:
            - stop() takes effect immediately, abandoning whatever remains queued.
            - shutdown() only takes effect once the inbox is genuinely empty, so a backlog queued as shutdown begins is still fully processed.
        """
        while not self._stop_event.is_set():
            try:
                first = self.inbox.get(timeout=1)
            except queue.Empty:
                if self._shutdown_event.is_set():
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
                f"turn - agent Call pipeline not yet implemented, see CODE_TODO.md §5. combined_text={combined_text!r}. "
                f"The eventual reply must be published against task_id={final_task_id} (this batch's last), "
                f"followed by mark_task_complete({final_task_id!r})."
            )
            # TODO (§5): invoke the agent Call pipeline with combined_text; on completion, publish the real
            # completed/error payload for final_task_id via self._publisher, then mark_task_complete(final_task_id).

# =============================================================================
