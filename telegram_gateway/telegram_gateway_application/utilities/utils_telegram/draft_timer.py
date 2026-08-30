# =============================================================================
# File        : draft_timer.py
# Description : File responsible for warning about and closing a pending draft
#                (media received without an instruction yet).
# Author      : SorinoSSK
# Created On  : 2026-08-31
#
# Features    :
#   - Runs a per-chat_id background loop that shows "typing...", then warns the
#     user shortly before a pending draft is auto-closed, then closes it if the
#     wait continues past that.
#
# Notes       :
#   - In-memory only - not persisted, resets on application restart. The Redis-side
#     draft record has its own TTL as a backstop - see create_chat_draft().
#   - Timing, all measured from when the draft was created:
#       0                                            -> waiting
#       DRAFT_CLOSE - DRAFT_WARNING - DRAFT_TYPING    -> "typing..." starts
#       DRAFT_CLOSE - DRAFT_WARNING                   -> "typing..." stops, warning sent
#       DRAFT_CLOSE                                   -> hard close (draft deleted, no further message)
#   - Reuses typing_indicator.py's start_typing()/stop_typing(), keyed by "draft:<chat_id>"
#     rather than a task_id, so this never collides with a real task's typing loop.
#   - Finalising a draft early (see stop_draft_timer()) always stops both the timer
#     thread and its typing indicator, regardless of which phase it was in - the loop
#     itself does not need to handle that case, it simply returns as soon as its
#     current wait is interrupted.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging
import threading

from ...config import settings
from .gateway_outbound import send_message
from .typing_indicator import start_typing, stop_typing
from ..utils_redis.database import delete_chat_draft

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_active_drafts: dict[int, threading.Event] = {}

# =============================================================================

def _typing_key(chat_id: int) -> str:
    return f"draft:{chat_id}"

def _stop(chat_id: int) -> None:
    """
    Removes chat_id from the active registry and signals its loop to stop, if present.

    Args:
        - chat_id (int)

    Returns:
        None
    """
    with _lock:
        stop_event = _active_drafts.pop(chat_id, None)

    if stop_event is not None:
        stop_event.set()

def _draft_loop(chat_id: int, media_type: str, stop_event: threading.Event) -> None:
    """
    Background loop warning then closing a pending draft, until stopped or the wait elapses.

    Args:
        - chat_id (int)

        - media_type (str):
            "image" | "video" | "file" - used to word the warning message.

        - stop_event (threading.Event)

    Returns:
        None

    Notes:
        - Uses stop_event.wait() throughout so an early stop (see stop_draft_timer())
          cancels immediately, at any phase, rather than after the current wait finishes.
    """
    wait_before_typing = max(0, settings.DRAFT_CLOSE_SECONDS - settings.DRAFT_WARNING_LEAD_SECONDS - settings.DRAFT_TYPING_LEAD_SECONDS)
    if stop_event.wait(wait_before_typing):
        return

    start_typing(_typing_key(chat_id), chat_id)
    if stop_event.wait(settings.DRAFT_TYPING_LEAD_SECONDS):
        return

    stop_typing(_typing_key(chat_id))
    send_message(
        chat_id,
        f"{settings.TELEGRAM_BOT_NAME} will be doing other work for now - feel free to tell "
        f"{settings.TELEGRAM_BOT_NAME} what you'd like help with and resend the {media_type} "
        f"when you're ready."
    )

    if stop_event.wait(settings.DRAFT_WARNING_LEAD_SECONDS):
        return

    logger.info(f"Draft for chat_id={chat_id} reached its hard close. Clearing.")
    _stop(chat_id)
    delete_chat_draft(chat_id)

def start_draft_timer(chat_id: int, media_type: str) -> None:
    """
    Starts the draft warning/close timer for a chat, if one is not already running.

    Args:
        - chat_id (int)

        - media_type (str):
            "image" | "video" | "file" - used to word the warning message.

    Returns:
        None

    Notes:
        - No-op if a draft timer is already active for this chat_id. Callers are
          expected to have already checked get_chat_draft() before creating a new
          draft in the first place (only one pending draft is allowed per chat_id) -
          this is a defensive guard, not the primary check.
    """
    with _lock:
        if chat_id in _active_drafts:
            return

        stop_event = threading.Event()
        _active_drafts[chat_id] = stop_event

    threading.Thread(
        target=_draft_loop,
        args=(chat_id, media_type, stop_event),
        daemon=True
    ).start()

def stop_draft_timer(chat_id: int) -> None:
    """
    Stops the draft warning/close timer for a chat, if active - also stops its typing indicator.

    Args:
        - chat_id (int)

    Returns:
        None

    Notes:
        - stop_typing() is a safe no-op if no typing loop is active for this chat_id
          (e.g. the draft is still in its pre-typing wait, or already past the warning).
    """
    stop_typing(_typing_key(chat_id))
    _stop(chat_id)

# =============================================================================
