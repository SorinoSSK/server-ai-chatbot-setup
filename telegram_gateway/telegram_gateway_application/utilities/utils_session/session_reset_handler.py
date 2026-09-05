# =============================================================================
# File        : session_reset_handler.py
# Description : File responsible for the graceful session_reset flow - deferring a reset until any in-flight task for a chat naturally completes, surviving a gateway crash without losing track of a reset that's still owed, and keeping the orchestrator/chat positively informed once a reset actually happens.
# Author      : SorinoSSK
# Created On  : 2026-09-05
#
# Features    :
#   - handle_session_reset_request() - whitelist check, then defers a reset while the chat has an open task_id, or applies it immediately if not.
#   - resolve_pending_reset_if_ready() - called after a task's completed/error mapping is deleted, to apply a deferred reset the moment its last open task_id clears.
#   - resync_pending_resets() - startup sweep resolving any deferred reset that became resolvable while the gateway was down, force-applying any that's already exceeded PENDING_RESET_MAX_WAIT_SECONDS.
#   - start_pending_reset_ceiling_sweep() - periodic background backstop (§8, TODO.md): force-applies any deferred reset that's been waiting longer than PENDING_RESET_MAX_WAIT_SECONDS, regardless of whether its task_id(s) ever send a completed/error - covers a poll that timed out with nothing pushed, an orphaned/expired task mapping, or any other task that's simply never going to finish.
#   - _apply_session_reset() - the single place a reset actually takes effect: wipes Redis session state, stops the chat's draft keep-alive timer, pushes a session_cleared ack, and sends the chat notice.
#
# Notes       :
#   - Execution authority for triggering a reset belongs to the orchestrator, not this gateway - this module only carries out a reset instruction already decided upstream.
#   - An open poll always has an open task_id (see utils_redis/database.py::has_open_tasks()), so it can only ever be encountered on the deferred path here, which waits rather than force-closing it - except defensively in the force-through path (see _force_apply_session_reset()), in case PENDING_RESET_MAX_WAIT_SECONDS is ever configured shorter than a poll's own maximum lifetime.
#   - Deferred import of queue_push_task in _push_session_cleared() to avoid a circular import (queue.py -> message_handler.py -> ... -> queue.py), same pattern as utils_queue/error_handling.py::push_tier1_delivery_failed() and utils_telegram/utilities/poll_response_handler.py::_push_poll_answer().
#
# =============================================================================
# I M P O R T   H E A D E R

import time
import logging
import threading

from ...config import settings
from ..utils_redis.database import has_open_tasks, set_pending_reset, get_pending_reset, clear_pending_reset, get_all_pending_resets, get_session_poll_ids, reset_session
from ..utils_telegram.gateway_outbound import send_message
from ..utils_telegram.utilities.image_draft_handler import stop_draft_timer
from ..utils_telegram.utilities.poll_response_handler import stop_poll_for_reset

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# Sent to a chat once its session has actually been reset - see _send_reset_notice().
# Set directly here - not chosen/generated at send-time.
RESET_NOTICE_MESSAGE: str = "Looks like Rukia got a little refresh... let's start fresh."

# Signals the background loop started by start_pending_reset_ceiling_sweep() to stop.
_ceiling_sweep_stop_event = threading.Event()
_ceiling_sweep_thread: threading.Thread | None = None

# =============================================================================

def _is_reset_allowed(chat_id: int) -> bool:
    """
    Checks whether chat_id is whitelisted to trigger a session reset.

    Args:
        chat_id (int)

    Returns:
        bool:
            True if chat_id is in settings.SESSION_RESET_ALLOWED_CHAT_IDS; otherwise False.
    """
    return chat_id in settings.SESSION_RESET_ALLOWED_CHAT_IDS

def _push_session_cleared(chat_id: int, session_id: str) -> bool:
    """
    Pushes a session_cleared event onto Q_CHANNEL_OUT - the orchestrator's positive confirmation that a specific session_id is gone on the gateway side.

    Args:
        chat_id (int)

        session_id (str):
            The session_id that was just cleared - see utils_redis/database.py::reset_session().

    Returns:
        bool:
            True if pushed successfully; otherwise False.

    Notes:
        - task_id is deliberately None - this isn't about any single task, it's a session-level ack.
    """
    from ..utils_queue.queue import queue_push_task

    payload = {
        "task_id": None,
        "session_id": session_id,
        "chat_id": chat_id,
        "type": "session_cleared"
    }

    if not queue_push_task(payload):
        logger.error(f"Failed to push session_cleared event for chat_id={chat_id} (session_id={session_id}) to RabbitMQ. Event dropped.")
        return False
    else:
        logger.info(f"Pushed session_cleared event for chat_id={chat_id} (session_id={session_id}).")
        return True

def _send_reset_notice(chat_id: int) -> None:
    """
    Informs a chat that its session has just been reset.

    Args:
        chat_id (int)

    Returns:
        None

    Notes:
        - Always sends exactly what's currently set in RESET_NOTICE_MESSAGE - no copy is chosen/generated here; the value is maintained directly in this file.
        - No-op (logged) while RESET_NOTICE_MESSAGE is unset, rather than sending an empty message.
        - Called for every chat_id whose session is actually cleared - not only the chat_id that triggered the reset - so a broader reset touching multiple chats notifies each one individually, not just the initiator.
          See _apply_session_reset().
        - Fires once, after the reset has already taken effect - no separate notice while a deferred reset is still waiting on an in-flight task.
    """
    if not RESET_NOTICE_MESSAGE:
        logger.warning(f"RESET_NOTICE_MESSAGE is unset - no reset notice sent for chat_id={chat_id}.")
        return
    else:
        send_message(chat_id, RESET_NOTICE_MESSAGE)

def _apply_session_reset(chat_id: int) -> None:
    """
    Applies a session reset for chat_id - the single place a reset actually takes effect.

    Args:
        chat_id (int)

    Returns:
        None

    Notes:
        - Stops the chat's draft keep-alive timer first - Redis state alone can't stop an in-memory timer (see utils_telegram/utilities/image_draft_handler.py::stop_draft_timer()); reset_session() only clears the Redis-side draft record itself.
        - No poll-specific handling here - an open poll always has an open task_id, so this point is only ever reached once none remain (see module Notes above).
        - _push_session_cleared()/_send_reset_notice() only fire if reset_session() actually had something to clear (a non-None session_id) - a chat with no session to begin with has nothing to ack or notify about.
        - Used by every path that ultimately applies a reset: the immediate path (handle_session_reset_request()), the deferred/resolved path (resolve_pending_reset_if_ready()), and startup crash-recovery (resync_pending_resets()).
    """
    stop_draft_timer(chat_id)

    cleared_session_id = reset_session(chat_id)
    if cleared_session_id:
        _push_session_cleared(chat_id, cleared_session_id)
        _send_reset_notice(chat_id)

def _force_apply_session_reset(chat_id: int, task_id: str) -> None:
    """
    Force-applies a session reset for chat_id whose deferred reset has exceeded PENDING_RESET_MAX_WAIT_SECONDS - the §8 (TODO.md) backstop, used when the natural completion path (resolve_pending_reset_if_ready()) never fires.

    Args:
        chat_id (int)

        task_id (str):
            The task_id originally stored against the pending reset - logged for traceability only.

    Returns:
        None

    Notes:
        - Closes out any poll still open for chat_id first (see poll_response_handler.py::stop_poll_for_reset()) - defensive only.
          In practice a poll's own maximum lifetime (POLL_GLOBAL_CAP_SECONDS) is expected to be far shorter than PENDING_RESET_MAX_WAIT_SECONDS, so any poll should already be long closed (and its task_id's completed/error already sent) by the time this fires.
          Only matters at all if PENDING_RESET_MAX_WAIT_SECONDS is ever misconfigured below a poll's own lifetime.
        - reset_session() (via _apply_session_reset()) unconditionally deletes every task_id still indexed under session_tasks:<chat_id>, regardless of whether it "actually" finished - no separate abandonment/cleanup step is needed beyond that.
    """
    for poll_id in get_session_poll_ids(chat_id):
        stop_poll_for_reset(poll_id)

    _apply_session_reset(chat_id)
    logger.warning(
        f"Force-applied session_reset for chat_id={chat_id} (task_id={task_id}) - pending longer than "
        f"PENDING_RESET_MAX_WAIT_SECONDS={settings.PENDING_RESET_MAX_WAIT_SECONDS}s with no "
        f"completed/error ever arriving for its open task(s)."
    )

def handle_session_reset_request(task_id: str, chat_id: int) -> None:
    """
    Handles a session_reset instruction - whitelist check, then defers the reset while chat_id has an open task_id, or applies it immediately if not.

    Args:
        task_id (str):
            The task_id the session_reset instruction arrived on - logged for traceability, and stored against a deferred reset (see utils_redis/database.py::set_pending_reset()), but not itself part of what gets reset.

        chat_id (int)

    Returns:
        None

    Notes:
        - A chat_id not in settings.SESSION_RESET_ALLOWED_CHAT_IDS is logged and dropped - no defer, no reset, no notice, no orchestrator ack.
          Decided: silent (log only), no response of any kind.
        - No user-facing message is sent while a reset is deferred (see _send_reset_notice()) - the chat only ever hears about a reset once it has actually taken effect.
    """
    if not _is_reset_allowed(chat_id):
        logger.warning(f"Rejected session_reset request for chat_id={chat_id} (task_id={task_id}) - chat_id is not whitelisted.")
        return
    else:
        if has_open_tasks(chat_id):
            set_pending_reset(chat_id, task_id)
            logger.info(f"Deferred session_reset for chat_id={chat_id} (task_id={task_id}) - an in-flight task is still open.")
        else:
            _apply_session_reset(chat_id)
            logger.info(f"Applied session_reset immediately for chat_id={chat_id} (task_id={task_id}) - no in-flight task was open.")

def resolve_pending_reset_if_ready(chat_id: int) -> None:
    """
    Applies a deferred session reset for chat_id the moment its last open task_id has cleared.

    Args:
        chat_id (int)

    Returns:
        None

    Notes:
        - Intended to be called from utils_queue/message_handler.py::_handle_completed()/_handle_error(), after delete_task_mapping() has already removed the just-finished task_id from session_tasks:<chat_id> - so has_open_tasks() reflects the state after that removal.
        - No-op if no reset is currently pending for chat_id, or if session_tasks:<chat_id> is still non-empty (another task is still open).
    """
    if get_pending_reset(chat_id) is None:
        return
    elif has_open_tasks(chat_id):
        return
    else:
        clear_pending_reset(chat_id)
        _apply_session_reset(chat_id)
        logger.info(f"Resolved deferred session_reset for chat_id={chat_id} - its last open task has completed.")

def _is_pending_reset_expired(created_at: float) -> bool:
    """
    Checks whether a pending reset's age has exceeded PENDING_RESET_MAX_WAIT_SECONDS.

    Args:
        created_at (float):
            The pending reset's creation time (time.time(), as stored by set_pending_reset()).

    Returns:
        bool:
            True if it's been pending at least PENDING_RESET_MAX_WAIT_SECONDS; otherwise False.
    """
    return (time.time() - created_at) >= settings.PENDING_RESET_MAX_WAIT_SECONDS

def resync_pending_resets() -> None:
    """
    Sweeps every deferred session_reset left in Redis on startup, applying any that became resolvable while the gateway was down, and force-applying any that's already exceeded PENDING_RESET_MAX_WAIT_SECONDS regardless.

    Args:
        None

    Returns:
        None

    Notes:
        - Intended to be called once on startup, after close_orphaned_drafts()/close_orphaned_polls() have both completed (see utilities/initialise.py) - so a chat's session_tasks:<chat_id> reflects those sweeps' outcome before this one runs.
        - An entry that's already resolvable (session_tasks:<chat_id> now empty) resolves the same way resolve_pending_reset_if_ready() would (§3).
          One that's still genuinely in flight but hasn't yet exceeded the ceiling is left untouched in Redis (no TTL - see utils_redis/database.py::set_pending_reset()) and is picked up later by resolve_pending_reset_if_ready() (§3) or the periodic ceiling sweep (see start_pending_reset_ceiling_sweep()) - whichever comes first.
        - No separate "reset_pending" event exists for the still-in-flight, not-yet-expired case - see TODO.md §5.
    """
    for chat_id, task_id, created_at in get_all_pending_resets():
        if has_open_tasks(chat_id):
            if _is_pending_reset_expired(created_at):
                clear_pending_reset(chat_id)
                _force_apply_session_reset(chat_id, task_id)
        else:
            clear_pending_reset(chat_id)
            _apply_session_reset(chat_id)
            logger.info(f"Resynced deferred session_reset for chat_id={chat_id} (task_id={task_id}) on startup - its task had already completed.")

def _enforce_pending_reset_ceiling() -> None:
    """
    Force-applies every deferred session_reset that's exceeded PENDING_RESET_MAX_WAIT_SECONDS - the §8 (TODO.md) backstop against a task_id that's never going to send a completed/error (a poll that timed out with nothing pushed, an orphaned/expired task mapping, or any other stuck task).

    Args:
        None

    Returns:
        None

    Notes:
        - Runs regardless of has_open_tasks() - a pending reset past the ceiling is force-applied whether or not its task_id(s) are still technically open; see _force_apply_session_reset().
        - Intended to be called periodically - see start_pending_reset_ceiling_sweep().
    """
    for chat_id, task_id, created_at in get_all_pending_resets():
        if not _is_pending_reset_expired(created_at):
            continue
        else:
            clear_pending_reset(chat_id)
            _force_apply_session_reset(chat_id, task_id)

def _pending_reset_ceiling_loop() -> None:
    """
    Background loop calling _enforce_pending_reset_ceiling() every PENDING_RESET_SWEEP_INTERVAL_SECONDS, until stop_pending_reset_ceiling_sweep() is called.

    Args:
        None

    Returns:
        None
    """
    while not _ceiling_sweep_stop_event.wait(settings.PENDING_RESET_SWEEP_INTERVAL_SECONDS):
        _enforce_pending_reset_ceiling()

def start_pending_reset_ceiling_sweep() -> None:
    """
    Starts the background loop enforcing PENDING_RESET_MAX_WAIT_SECONDS on every deferred session_reset, if one is not already running.

    Args:
        None

    Returns:
        None

    Notes:
        - No-op if already running (defensive guard, not the primary check) - mirrors poll_response_handler.py::start_poll_timer()'s style.
        - Runs until stop_pending_reset_ceiling_sweep() is called.
    """
    global _ceiling_sweep_thread

    if _ceiling_sweep_thread is not None and _ceiling_sweep_thread.is_alive():
        return
    else:
        _ceiling_sweep_stop_event.clear()
        _ceiling_sweep_thread = threading.Thread(target=_pending_reset_ceiling_loop, daemon=True)
        _ceiling_sweep_thread.start()
        logger.info(
            f"Started pending-reset ceiling sweep (every {settings.PENDING_RESET_SWEEP_INTERVAL_SECONDS}s, "
            f"ceiling {settings.PENDING_RESET_MAX_WAIT_SECONDS}s)."
        )

def stop_pending_reset_ceiling_sweep() -> None:
    """
    Stops the background pending-reset ceiling sweep loop.

    Args:
        None

    Returns:
        None

    Notes:
        - Does not wait for the loop to actually terminate - it will exit on its next wait() wake-up, at most PENDING_RESET_SWEEP_INTERVAL_SECONDS later.
    """
    _ceiling_sweep_stop_event.set()

# =============================================================================
