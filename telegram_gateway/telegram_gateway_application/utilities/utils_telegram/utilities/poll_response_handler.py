# =============================================================================
# File        : poll_response_handler.py
# Description : File responsible for timing out, debouncing, and closing an open poll.
# Author      : SorinoSSK
# Created On  : 2026-09-02
#
# Features    :
#   - Runs a per-poll_id background loop through two phases:
#       - AWAITING FIRST ANSWER (POLL_TIMEOUT_SECONDS): closes with a chat message if nobody answers in time.
#         Nothing is pushed to the queue.
#       - DEBOUNCING (POLL_DEBOUNCE_INITIAL_SECONDS, shortened to POLL_DEBOUNCE_SUBSEQUENT_SECONDS on every further answer): once answered, waits for things to go quiet before compiling and pushing the latest answer - capped overall by POLL_GLOBAL_CAP_SECONDS from poll creation, regardless of how many times debouncing resets.
#   - Unrelated chat messages do not interact with an open poll at all - the bot is expected to answer them independently while the poll keeps running.
#   - close_orphaned_polls() sweeps Redis on startup for polls left behind by a timer that did not survive the previous run (e.g. an app restart), closing each one out immediately - pushing whatever answer it already has, same as any other closure path.
#
# Notes       :
#   - In-memory only - not persisted.
#     Redis-side poll mapping has its own TTL as backstop, refreshed on every answer (see utils_redis/database.py::update_poll_answer()).
#   - Whether a closure pushes an answer to the queue depends solely on whether the poll was ever answered, not on why it's closing - the same _finalise_poll() path handles a natural debounce expiry, the global cap being reached, and an orphan-sweep closure identically.
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
    get_all_poll_ids
)

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_lock = threading.RLock()

# poll_id -> {"event": threading.Event}
_active_polls: dict[str, dict] = {}

# =============================================================================

def _push_poll_answer(task_id: str, user_id: int | None, option_ids: list) -> None:
    """
    Pushes a compiled poll answer to the outbound queue, on the existing task payload shape.

    Args:
        task_id (str)

        user_id (int | None):
            The responder's id - for the Debate Orchestrator's use only (see AI_AGENT_ARCHITECTURE.md); never forwarded on to the LLM agents.

        option_ids (list)

    Returns:
        None

    Notes:
        - Deferred import of queue_push_task to avoid a circular import (queue.py -> message_handler.py -> this module -> queue.py).
    """
    from ...utils_queue.queue import queue_push_task

    if not queue_push_task({
        "task_id": task_id,
        "text": "",
        "image_url": "",
        "video_url": "",
        "file_url": "",
        "user_id": user_id,
        "poll_answer": option_ids
    }):
        logger.error(f"Failed to push poll answer for task_id={task_id} to RabbitMQ. Message dropped.")

def _finalise_poll(poll_id: str, mapping: dict) -> None:
    """
    Closes a poll on Telegram, clears its Redis mapping, and either pushes its answer or notifies the user, based on whether it was ever answered.

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
    user_id = mapping.get("user_id")
    option_ids = mapping.get("option_ids") or []

    stop_poll(chat_id, message_id)
    delete_poll_mapping(poll_id)

    if option_ids:
        _push_poll_answer(task_id, user_id, option_ids)
    else:
        send_message(
            chat_id,
            f"{settings.TELEGRAM_BOT_NAME} didn't hear back in time, so the poll's been closed for now."
        )

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

    if not update_poll_answer(poll_id, user_id, option_ids):
        logger.error(f"Failed to persist poll answer for poll_id={poll_id}. Answer not recorded.")
        return False

    control["event"].set()
    logger.info(f"Recorded poll answer for poll_id={poll_id} (user_id={user_id}).")
    return True

def _poll_loop(poll_id: str, event: threading.Event) -> None:
    """
    Background loop taking a poll through AWAITING FIRST ANSWER, then DEBOUNCING, until closed.

    Args:
        poll_id (str)

        event (threading.Event):
            Shared with handle_poll_answer(), set each time an answer is recorded.

    Returns:
        None

    Notes:
        - Every debounce deadline is clamped to started_at + POLL_GLOBAL_CAP_SECONDS, so the global cap is enforced simply by whichever deadline is soonest - no separate cap-check is needed.
    """
    started_at = time.monotonic()

    answered = event.wait(settings.POLL_TIMEOUT_SECONDS)
    if not answered:
        with _lock:
            _active_polls.pop(poll_id, None)
        mapping = get_poll_mapping(poll_id)
        if mapping is not None:
            _finalise_poll(poll_id, mapping)
        return
    event.clear()

    deadline = min(time.monotonic() + settings.POLL_DEBOUNCE_INITIAL_SECONDS, started_at + settings.POLL_GLOBAL_CAP_SECONDS)
    while True:
        wait_seconds = max(0, deadline - time.monotonic())
        answered_again = event.wait(wait_seconds)
        if not answered_again:
            break
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

        control = {"event": threading.Event()}
        _active_polls[poll_id] = control

    threading.Thread(
        target=_poll_loop,
        args=(poll_id, control["event"]),
        daemon=True
    ).start()
    logger.info(f"Started poll timer for poll_id={poll_id} (chat_id={chat_id}).")

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

    for poll_id in poll_ids:
        mapping = get_poll_mapping(poll_id)
        if mapping is None:
            continue

        _finalise_poll(poll_id, mapping)
        logger.info(f"Closed orphaned poll_id={poll_id} left behind by a previous run.")

# =============================================================================
