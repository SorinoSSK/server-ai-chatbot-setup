# =============================================================================
# File        : poll_response_handler.py
# Description : File responsible for timing out, debouncing, and closing an open poll.
# Author      : SorinoSSK
# Created On  : 2026-09-02
#
# Features    :
#   - Runs a per-poll_id background loop through two phases:
#       - AWAITING FIRST ANSWER (POLL_TIMEOUT_SECONDS): closes with a chat message if nobody answers in time,
#         and pushes a poll_timed_out event (see _push_poll_timed_out()) so the backend isn't left with no signal at all.
#       - DEBOUNCING (POLL_DEBOUNCE_INITIAL_SECONDS, shortened to POLL_DEBOUNCE_SUBSEQUENT_SECONDS on every further answer): once answered, waits for things to go quiet before compiling and pushing the latest answer - capped overall by POLL_GLOBAL_CAP_SECONDS from poll creation, regardless of how many times debouncing resets.
#   - Unrelated chat messages do not interact with an open poll at all - the bot is expected to answer them independently while the poll keeps running.
#   - close_orphaned_polls() sweeps Redis on startup for polls left behind by a timer that did not survive the previous run (e.g. an app restart), closing each one out immediately - pushing whatever answer (or poll_timed_out) it already has, same as any other closure path.
#
# Notes       :
#   - In-memory only - not persisted.
#     Redis-side poll mapping has its own TTL as backstop, refreshed on every answer (see utils_redis/database.py::update_poll_answer()).
#   - Whether a closure pushes a poll_answer or a poll_timed_out event depends solely on whether the poll was ever answered, not on why it's closing - the same _finalise_poll() path handles a natural debounce expiry, the global cap being reached, and an orphan-sweep closure identically.
#   - poll_timed_out (§8, TODO.md) closes the gap where an unanswered poll left the backend with nothing to act on - the task_id could stay open in session_tasks:<chat_id> indefinitely, which in turn could leave a deferred session_reset (see utils_session/session_reset_handler.py) waiting forever. Routed to whichever agent currently owns task_id, the same way a real poll_answer already is - no new logic is asked of the orchestrator itself.
#
# =============================================================================
# I M P O R T   H E A D E R

import time
import logging
import threading

from ....config import settings
from ..gateway_outbound import send_message, stop_poll
from ...utils_redis.database import (
    get_poll_mapping,
    update_poll_answer,
    delete_poll_mapping,
    get_all_poll_ids,
    generate_session
)

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_lock = threading.RLock()

# poll_id -> {"event": threading.Event}
_active_polls: dict[str, dict] = {}

# =============================================================================

def _push_poll_answer(task_id: str, option_ids: list) -> None:
    """
    Pushes a compiled poll answer to the outbound queue, on the existing task payload shape.

    Args:
        task_id (str)

        option_ids (list)

    Returns:
        None

    Notes:
        - user_id is not part of this payload - a poll only ever has one possible responder (the chat's own user, per this gateway's 1 user : 1 chat model), so task_id already resolves the poll back to its chat unambiguously; see database.py::generate_session() for how session_id is resolved from task_id when no chat_id is directly available at this call site.
        - session_id is resolved via generate_session() and is mandatory on every outbound payload - see utils_redis/database.py.
        - Deferred import of queue_push_task to avoid a circular import (queue.py -> message_handler.py -> this module -> queue.py).
    """
    from ...utils_queue.queue import queue_push_task

    session_id = generate_session(task_id=task_id)
    if not session_id:
        logger.error(f"Failed to resolve session_id for task_id={task_id}. Poll answer dropped.")
        return
    elif not queue_push_task({
        "task_id": task_id,
        "session_id": session_id,
        "text": "",
        "image_url": "",
        "video_url": "",
        "file_url": "",
        "poll_answer": option_ids
    }):
        logger.error(f"Failed to push poll answer for task_id={task_id} to RabbitMQ. Message dropped.")
    else:
        logger.info(f"Pushed poll answer for task_id={task_id} to RabbitMQ.")

def _push_poll_timed_out(task_id: str) -> None:
    """
    Pushes a poll_timed_out event to the outbound queue - the positive signal a poll ended with no answer ever recorded, since no other payload is pushed on this path.

    Args:
        task_id (str)

    Returns:
        None

    Notes:
        - See TODO.md §8 - closes the gap where an unanswered poll previously left the backend with nothing to act on, which could leave the task_id open in session_tasks:<chat_id> indefinitely (and by extension, a deferred session_reset waiting on it forever - see utils_session/session_reset_handler.py).
        - Routed by task_id the same way a real poll_answer already is - the deciding logic belongs to whichever agent currently owns task_id (re-ask, treat as declined, escalate, or simply send back completed/error), not to the orchestrator or this gateway.
        - session_id is resolved via generate_session() and is mandatory on every outbound payload - see utils_redis/database.py.
        - Deferred import of queue_push_task to avoid a circular import (queue.py -> message_handler.py -> this module -> queue.py).
    """
    from ...utils_queue.queue import queue_push_task

    session_id = generate_session(task_id=task_id)
    if not session_id:
        logger.error(f"Failed to resolve session_id for task_id={task_id}. poll_timed_out event dropped.")
        return
    elif not queue_push_task({
        "task_id": task_id,
        "session_id": session_id,
        "type": "poll_timed_out"
    }):
        logger.error(f"Failed to push poll_timed_out event for task_id={task_id} to RabbitMQ. Event dropped.")
    else:
        logger.info(f"Pushed poll_timed_out event for task_id={task_id} to RabbitMQ.")

def _finalise_poll(poll_id: str, mapping: dict) -> None:
    """
    Closes a poll on Telegram, clears its Redis mapping, and either pushes its answer or a poll_timed_out event (plus a chat notice), based on whether it was ever answered.

    Args:
        poll_id (str)

        mapping (dict):
            {"chat_id", "task_id", "message_id", "user_id", "option_ids"} - see get_poll_mapping().

    Returns:
        None

    Notes:
        - stop_poll() is best-effort - a poll already closed (e.g. a previous run's orphan sweep raced with this one) is not treated as a hard failure.
        - Shared by the normal in-memory closure path and close_orphaned_polls(), so both close a poll out identically.
    """
    chat_id = mapping.get("chat_id")
    task_id = mapping.get("task_id")
    message_id = mapping.get("message_id")
    option_ids = mapping.get("option_ids") or []

    stop_poll(chat_id, message_id)
    delete_poll_mapping(poll_id, chat_id)

    if option_ids:
        _push_poll_answer(task_id, option_ids)
    else:
        send_message(
            chat_id,
            f"{settings.TELEGRAM_BOT_NAME} didn't hear back in time, so the poll's been closed for now."
        )
        _push_poll_timed_out(task_id)

    logger.info(f"Closed poll_id={poll_id} for chat_id={chat_id} (answered={bool(option_ids)}).")

def handle_poll_answer(poll_id: str, user_id: int, option_ids: list) -> bool:
    """
    Records a poll_answer update against its open poll, waking its debounce loop.

    Args:
        poll_id (str)

        user_id (int):
            The responder's id, per Telegram's poll_answer update.

        option_ids (list):
            The responder's currently selected option indices, per Telegram's poll_answer update.

    Returns:
        bool:
            True if poll_id was an active, tracked poll and the answer was recorded; otherwise False (unknown/already-closed poll_id, or a Redis write failure).
    """
    with _lock:
        control = _active_polls.get(poll_id)

        if control is None:
            return False
        elif not update_poll_answer(poll_id, user_id, option_ids):
            logger.error(f"Failed to persist poll answer for poll_id={poll_id}. Answer not recorded.")
            return False
        else:
            control["event"].set()
            logger.info(f"Recorded poll answer for poll_id={poll_id} (user_id={user_id}).")
            return True

def _poll_loop(poll_id: str, control: dict) -> None:
    """
    Background loop taking a poll through AWAITING FIRST ANSWER, then DEBOUNCING, until closed.

    Args:
        poll_id (str)

        control (dict):
            {"event": threading.Event, "stop": bool} - shared with handle_poll_answer() (sets "event" on each recorded answer) and stop_poll_for_reset() (sets both "event" and "stop" to end this loop immediately without finalising).

    Returns:
        None

    Notes:
        - Every debounce deadline is clamped to started_at + POLL_GLOBAL_CAP_SECONDS, so the global cap is enforced simply by whichever deadline is soonest - no separate cap-check is needed.
        - Checked after every wait() for a stop signal (see stop_poll_for_reset()) - on a stop, this loop returns immediately without calling _finalise_poll(), since stop_poll_for_reset() has already closed the poll out itself - see CCR-012 (NON_COMPLIANCE_REPORT.md).
    """
    event = control["event"]
    started_at = time.monotonic()

    answered = event.wait(settings.POLL_TIMEOUT_SECONDS)
    if control.get("stop"):
        with _lock:
            _active_polls.pop(poll_id, None)
        logger.info(f"Poll timer for poll_id={poll_id} stopped by a session reset.")
        return
    elif not answered:
        with _lock:
            _active_polls.pop(poll_id, None)
        mapping = get_poll_mapping(poll_id)
        if mapping is not None:
            _finalise_poll(poll_id, mapping)
        return
    else:
        event.clear()

        deadline = min(time.monotonic() + settings.POLL_DEBOUNCE_INITIAL_SECONDS, started_at + settings.POLL_GLOBAL_CAP_SECONDS)
        while True:
            wait_seconds = max(0, deadline - time.monotonic())
            answered_again = event.wait(wait_seconds)
            if control.get("stop"):
                with _lock:
                    _active_polls.pop(poll_id, None)
                logger.info(f"Poll timer for poll_id={poll_id} stopped by a session reset.")
                return
            elif not answered_again:
                break
            else:
                event.clear()
                deadline = min(time.monotonic() + settings.POLL_DEBOUNCE_SUBSEQUENT_SECONDS, started_at + settings.POLL_GLOBAL_CAP_SECONDS)

        with _lock:
            _active_polls.pop(poll_id, None)
        mapping = get_poll_mapping(poll_id)
        if mapping is not None:
            _finalise_poll(poll_id, mapping)

def start_poll_timer(poll_id: str, chat_id: int) -> None:
    """
    Starts the AWAITING FIRST ANSWER / DEBOUNCING timer for a poll, if one is not already running.

    Args:
        poll_id (str)

        chat_id (int):
            Unused directly - kept for logging context only; all state is read from the poll's Redis mapping (see create_poll_mapping()).

    Returns:
        None

    Notes:
        - No-op if already active for this poll_id (defensive guard, not the primary check).
    """
    with _lock:
        if poll_id in _active_polls:
            return
        else:
            control = {"event": threading.Event(), "stop": False}
            _active_polls[poll_id] = control

    threading.Thread(
        target=_poll_loop,
        args=(poll_id, control),
        daemon=True
    ).start()
    logger.info(f"Started poll timer for poll_id={poll_id} (chat_id={chat_id}).")

def stop_poll_for_reset(poll_id: str) -> None:
    """
    Closes a single open poll out immediately for a session reset - no answer pushed, no closing chat message.

    Args:
        poll_id (str)

    Returns:
        None

    Notes:
        - Signals _poll_loop() (if its timer is still active) to return without finalising, then closes the poll out on Telegram and clears its Redis mapping itself - distinct from every other closure path (_finalise_poll()), which always pushes whatever answer was recorded, or sends a "didn't hear back" message.
          A reset is treated as a deliberate clean slate, so any partial answer is discarded silently instead - see CCR-012 (NON_COMPLIANCE_REPORT.md).
        - No-op if poll_id is already unknown (e.g. a race with a natural closure) - get_poll_mapping() returns None and this exits quietly.
    """
    with _lock:
        control = _active_polls.get(poll_id)
        if control is not None:
            control["stop"] = True
            control["event"].set()

    mapping = get_poll_mapping(poll_id)
    if mapping is None:
        return
    else:
        chat_id = mapping.get("chat_id")
        message_id = mapping.get("message_id")

        stop_poll(chat_id, message_id)
        delete_poll_mapping(poll_id, chat_id)
        logger.info(f"Closed poll_id={poll_id} for chat_id={chat_id} as part of a session reset (no answer pushed).")

def close_orphaned_polls() -> None:
    """
    Closes out any poll left in Redis with no matching in-memory timer.

    Args:
        None

    Returns:
        None

    Notes:
        - Intended to be called once on startup, before polling resumes.
          A poll's timer is in-memory only (see module Notes above), so it does not survive an application restart - without this sweep, such a poll would sit silently until its Redis TTL lapses, with no notice, no closure, and no answer ever pushed, even if one had already been recorded.
        - Since the timer's progress (which phase, how much time remains) isn't persisted, an orphaned poll is closed out immediately rather than resumed part-way through a phase.
    """
    poll_ids = get_all_poll_ids()
    if not poll_ids:
        return
    else:
        for poll_id in poll_ids:
            mapping = get_poll_mapping(poll_id)
            if mapping is None:
                continue
            else:
                _finalise_poll(poll_id, mapping)
                logger.info(f"Closed orphaned poll_id={poll_id} left behind by a previous run.")

# =============================================================================
