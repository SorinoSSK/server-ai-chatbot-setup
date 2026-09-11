# =============================================================================
# File        : session_reset_handler.py
# Description : Manages the graceful session_reset workflow across every chat the gateway currently holds a session for.
# Author      : SorinoSSK
# Created On  : 2026-09-05
#
# Features    :
#   - Deferred session reset application, waiting for a chat's in-flight task(s) to complete naturally before clearing its state.
#   - Crash-resilient tracking of a reset that is still owed, surviving a gateway restart.
#   - A bounded wait ceiling that force-applies a reset if its task never completes on its own.
#   - Orchestrator acknowledgement and chat-facing notification once a reset actually takes effect.
#   - Outbound request for an admin-triggered global session reset, and reconciliation once the orchestrator confirms it has restarted.
#
# Notes       :
#   - Execution authority for triggering a reset belongs to the orchestrator, not this gateway - this module only carries out a reset instruction already decided upstream.
#   - Whitelist enforcement for who may trigger a global reset happens upstream, at command detection - see utils_telegram/gateway_inbound.py.
#   - See README.md's "session_reset"/"session_clear_request"/"bot_started" sections for the full request/response design this module implements.
#
# =============================================================================
# I M P O R T   H E A D E R

import time
import logging
import threading

from ...config import settings
from ..utils_redis.database import (
    has_open_tasks,
    set_pending_reset,
    get_pending_reset,
    clear_pending_reset,
    get_all_pending_resets,
    get_all_session_chat_ids,
    get_session_poll_ids,
    reset_session,
    get_task_mapping,
    delete_task_mapping
)
from ..utils_telegram.gateway_outbound import send_message
from ..utils_telegram.utilities.image_draft_handler import stop_draft_timer
from ..utils_telegram.utilities.poll_response_handler import stop_poll_for_reset

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# Sent to a chat once its session has actually been reset - see _send_reset_notice().
# A single fixed value, set directly here rather than chosen/generated per-send.
RESET_NOTICE_MESSAGE: str = f"Looks like {settings.TELEGRAM_BOT_NAME} got a little refresh... let's start fresh."

# Stored as a pending reset's task_id for every chat swept into a broad session_reset that isn't
# the one (if any) that actually triggered it - see handle_session_reset_request(). A fixed,
# non-empty sentinel rather than a bare None, so a stored pending reset's task_id is never itself
# None - only ever absent entirely - keeping get_pending_reset()'s None return unambiguous. Never
# collides with a real task_id, since those are always uuid4 hex values.
SYSTEM_TRIGGERED_TASK_ID: str = "system_triggered"

# Signals the background loop started by start_pending_reset_ceiling_sweep() to stop.
_ceiling_sweep_stop_event = threading.Event()
_ceiling_sweep_thread: threading.Thread | None = None

# =============================================================================

def _push_session_cleared(chat_id: int, session_id: str) -> bool:
    """
    Pushes a session_cleared event - the orchestrator's confirmation that a specific session_id is gone on the gateway side.

    Args:
        chat_id (int):
            Used only to identify the chat in this function's own log lines - not part of the outbound payload.

        session_id (str):
            The session_id that was just cleared.

    Returns:
        bool:
            True if pushed successfully; otherwise False.

    Notes:
        - chat_id is intentionally excluded from the payload, keeping the orchestrator identity-blind - see README.md's Design Decisions and "session_cleared" documentation.
        - Deferred import of queue_push_task to avoid a circular import, same pattern used elsewhere in the codebase for this reason.
    """
    from ..utils_queue.queue import queue_push_task

    payload = {
        "task_id": None,
        "session_id": session_id,
        "type": "session_cleared"
    }

    if not queue_push_task(payload):
        logger.error(f"Failed to push session_cleared event for chat_id={chat_id} (session_id={session_id}) to RabbitMQ. Event dropped.")
        return False
    else:
        logger.info(f"Pushed session_cleared event for chat_id={chat_id} (session_id={session_id}).")
        return True

def push_session_clear_request(task_id: str, chat_id: int) -> bool:
    """
    Pushes a session_clear_request event - the admin-triggered request for the orchestrator to begin a global session reset.

    Args:
        task_id (str):
            The task_id minted for the triggering admin command - see utils_telegram/gateway_inbound.py. Echoed back on the orchestrator's own session_reset once accepted.

        chat_id (int):
            The requesting admin's chat_id - used only in this function's own log lines, not part of the outbound payload.

    Returns:
        bool:
            True if pushed successfully; otherwise False.

    Notes:
        - chat_id is intentionally excluded from the payload, keeping the orchestrator identity-blind - see README.md's Design Decisions.
        - Public, unlike _push_session_cleared() above - called from utils_telegram/gateway_inbound.py once the admin command is detected.
    """
    from ..utils_queue.queue import queue_push_task

    payload = {
        "task_id": task_id,
        "type": "session_clear_request"
    }

    if not queue_push_task(payload):
        logger.error(f"Failed to push session_clear_request for chat_id={chat_id} (task_id={task_id}) to RabbitMQ. Request dropped.")
        return False
    else:
        logger.info(f"Pushed session_clear_request for chat_id={chat_id} (task_id={task_id}).")
        return True

def _send_reset_notice(chat_id: int) -> None:
    """
    Informs a chat that its session has just been reset.

    Args:
        chat_id (int)

    Returns:
        None

    Notes:
        - Always sends exactly what's currently set in RESET_NOTICE_MESSAGE.
        - No-op (logged) while RESET_NOTICE_MESSAGE is unset, rather than sending an empty message.
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
        - Stops the chat's draft keep-alive timer before clearing Redis state, since a Redis write alone cannot stop an in-memory timer.
        - The orchestrator ack and chat notice only fire if there was actually a session to clear.
        - The single function every reset path (immediate, deferred/resolved, crash recovery, force-applied) ultimately calls to take effect.
    """
    stop_draft_timer(chat_id)

    cleared_session_id = reset_session(chat_id)
    if cleared_session_id:
        _push_session_cleared(chat_id, cleared_session_id)
        _send_reset_notice(chat_id)

def _force_apply_session_reset(chat_id: int, task_id: str | None) -> None:
    """
    Force-applies a session reset for a chat whose deferred reset has exceeded PENDING_RESET_MAX_WAIT_SECONDS.

    Used as the backstop when the natural completion path (resolve_pending_reset_if_ready()) never fires for one of the chat's open task_id(s).

    Args:
        chat_id (int)

        task_id (str | None):
            The task_id originally stored against the pending reset, if any - logged for traceability only.

    Returns:
        None

    Notes:
        - Closes out any poll still open for the chat first, defensively, in case PENDING_RESET_MAX_WAIT_SECONDS is ever configured shorter than a poll's own maximum lifetime.
    """
    for poll_id in get_session_poll_ids(chat_id):
        stop_poll_for_reset(poll_id)

    _apply_session_reset(chat_id)
    logger.warning(
        f"Force-applied session_reset for chat_id={chat_id} (task_id={task_id}) - pending longer than "
        f"PENDING_RESET_MAX_WAIT_SECONDS={settings.PENDING_RESET_MAX_WAIT_SECONDS}s with no "
        f"completed/error ever arriving for its open task(s)."
    )

def _defer_or_apply_reset(chat_id: int, task_id: str | None) -> None:
    """
    Defers a session reset for a chat while it has an open task, or applies it immediately if not.

    The one per-chat decision every session_reset ultimately reduces to, shared by handle_session_reset_request()'s sweep across every chat it holds a session for.

    Args:
        chat_id (int)

        task_id (str | None):
            Stored against a deferred reset for traceability only - readiness is decided purely by whether the chat still has an open task.
            Passed as SYSTEM_TRIGGERED_TASK_ID, never a bare None, for every chat that isn't the one that actually triggered this reset - see handle_session_reset_request().

    Returns:
        None

    Notes:
        - Idempotent - safe to call repeatedly for the same chat across arrivals, whether the chat is already clear or already correctly deferred.
        - Clears any existing pending-reset entry before applying immediately, as a defensive guard against leaving a stale entry behind.
    """
    if has_open_tasks(chat_id):
        set_pending_reset(chat_id, task_id)
        logger.info(f"Deferred session_reset for chat_id={chat_id} (task_id={task_id}) - an in-flight task is still open.")
    else:
        clear_pending_reset(chat_id)
        _apply_session_reset(chat_id)
        logger.info(f"Applied session_reset immediately for chat_id={chat_id} (task_id={task_id}) - no in-flight task was open.")

def handle_session_reset_request(task_id: str | None) -> None:
    """
    Handles an inbound session_reset instruction from the orchestrator.

    Closes the triggering task_id, if any, then independently defers or applies a reset for every chat the gateway currently holds a session for - see README.md's "session_reset" documentation for the full design.

    Args:
        task_id (str | None):
            The task_id the session_reset instruction arrived on, if any - resolved to a chat_id via its existing task mapping, and closed out exactly like a completed/error would.
            Absent when the orchestrator triggered the reset itself rather than a user.

    Returns:
        None

    Notes:
        - No whitelist check is performed here - an inbound session_reset always originates from the orchestrator itself, never directly from a chat; the whitelist governing who may trigger one is enforced upstream, at command detection.
        - Idempotent - safe to re-run on every arrival.
        - No user-facing message is sent while a reset is only deferred - a chat only hears about a reset once it has actually taken effect.
        - Every chat swept below that isn't the triggering one is deferred/applied with SYSTEM_TRIGGERED_TASK_ID rather than a bare None, keeping a stored pending reset's task_id unambiguous - see resolve_pending_reset_if_ready().
    """
    triggering_chat_id = None

    if not task_id:
        logger.info("Received a session_reset with no task_id - bot_sanctuary triggered this itself (not user-initiated), nothing to close. Proceeding straight to the broad sweep.")
    else:
        mapping = get_task_mapping(task_id)
        if mapping is None:
            logger.error(f"No task mapping found for task_id={task_id} while closing the triggering task for a session_reset - it may have already expired. Proceeding to the broad sweep regardless.")
        else:
            triggering_chat_id = mapping.get("chat_id")
            if not delete_task_mapping(task_id, triggering_chat_id):
                logger.error(f"Failed to delete task mapping for task_id={task_id} (chat_id={triggering_chat_id}) while closing a session_reset's triggering task.")
            else:
                logger.info(f"Closed triggering task_id={task_id} for chat_id={triggering_chat_id} - this session_reset doubles as its completion signal.")

    for chat_id in get_all_session_chat_ids():
        _defer_or_apply_reset(chat_id, task_id if chat_id == triggering_chat_id else SYSTEM_TRIGGERED_TASK_ID)

def resolve_pending_reset_if_ready(chat_id: int) -> None:
    """
    Applies a deferred session reset for chat_id the moment its last open task_id has cleared.

    Args:
        chat_id (int)

    Returns:
        None

    Notes:
        - Intended to be called after a task's completed/error mapping has already been deleted, so the chat's open-task state reflects that removal.
        - No-op if no reset is currently pending for the chat, or if another task is still open.
        - Relies on a stored pending reset never actually carrying a None task_id - handle_session_reset_request() always writes either a real task_id or SYSTEM_TRIGGERED_TASK_ID, so a None return here can only mean no reset is pending at all.
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
    Sweeps every deferred session_reset left in Redis on startup.

    Applies any that became resolvable while the gateway was down, and force-applies any that has already exceeded PENDING_RESET_MAX_WAIT_SECONDS regardless.

    Args:
        None

    Returns:
        None

    Notes:
        - Intended to be called once on startup, after the draft/poll orphan sweeps have both completed, so open-task state reflects their outcome.
        - An entry still genuinely in flight, but not yet expired, is left untouched in Redis and is picked up later by resolve_pending_reset_if_ready() or the periodic ceiling sweep, whichever comes first.
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
    Force-applies every deferred session_reset that has exceeded PENDING_RESET_MAX_WAIT_SECONDS.

    The backstop against a task that is never going to naturally complete, regardless of the cause.

    Args:
        None

    Returns:
        None

    Notes:
        - Runs regardless of whether the chat's task_id(s) are still technically open.
        - Intended to be called periodically - see start_pending_reset_ceiling_sweep().
    """
    for chat_id, task_id, created_at in get_all_pending_resets():
        if not _is_pending_reset_expired(created_at):
            continue
        else:
            clear_pending_reset(chat_id)
            _force_apply_session_reset(chat_id, task_id)

def resolve_pending_resets_on_bot_started() -> None:
    """
    Resolves every currently deferred session_reset in response to the orchestrator confirming it has just restarted.

    A restart means whatever the orchestrator was holding before is gone, so nothing further is ever coming for any pending reset, regardless of whether the gateway itself still considers any of that chat's tasks open.

    Args:
        None

    Returns:
        None

    Notes:
        - Unconditional and immediate for every currently pending reset - unlike resync_pending_resets()/_enforce_pending_reset_ceiling(), there is no open-task or expiry check here at all.
        - Also closes any lingering open poll for each resolved chat, since a restart is entirely the orchestrator's own concern - the gateway still owns closing out its own Telegram-side poll state.
        - resync_pending_resets()/_enforce_pending_reset_ceiling() remain the fallback for whatever a lost bot_started event doesn't cover.
    """
    for chat_id, task_id, _ in get_all_pending_resets():
        clear_pending_reset(chat_id)

        for poll_id in get_session_poll_ids(chat_id):
            stop_poll_for_reset(poll_id)

        _apply_session_reset(chat_id)
        logger.info(f"Resolved deferred session_reset for chat_id={chat_id} (task_id={task_id}) via bot_started - bot_sanctuary restarted, so nothing further was ever coming for it.")

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
