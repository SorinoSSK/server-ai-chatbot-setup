# =============================================================================
# File        : typing_indicator.py
# Description : File responsible for sustaining Telegram's "typing..." indicator while a task is in progress.
# Author      : SorinoSSK
# Created On  : 2026-08-30
#
# Features    :
#   - Runs a per-task_id background loop calling send_typing_action() at a jittered interval.
#   - Self-terminates on a randomised ping cap, in addition to an explicit stop.
#
# Notes       :
#   - In-memory only - not persisted, resets on application restart.
#
# =============================================================================
# I M P O R T   H E A D E R

import random
import logging
import threading

from ....config import settings
from ..gateway_outbound import send_typing_action

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_active_typing: dict[str, threading.Event] = {}

# =============================================================================

def _stop(task_id: str) -> None:
    """
    Removes task_id from the active registry and signals its loop to stop, if present.

    Args:
        task_id (str)

    Returns:
        None
    """
    with _lock:
        stop_event = _active_typing.pop(task_id, None)

    if stop_event is not None:
        stop_event.set()
        logger.info(f"Stopped typing indicator for task_id={task_id}.")

def _typing_loop(task_id: str, chat_id: int, stop_event: threading.Event, on_giveup) -> None:
    """
    Background loop sustaining the typing indicator for a single task, until stopped or self-terminated.

    Args:
        task_id (str)

        chat_id (int)

        stop_event (threading.Event)

        on_giveup (Callable[[str, str], None] | None):
            Called with (task_id, reason) on self-termination.

    Returns:
        None

    Notes:
        - Interval is randomised each ping; ping count is capped (randomised once per session) as ghost-task protection in case nothing else stops the loop.
    """
    max_pings = random.randint(settings.TELEGRAM_TYPING_MAX_PINGS_MIN, settings.TELEGRAM_TYPING_MAX_PINGS_MAX)
    pings_sent = 0

    while not stop_event.is_set():
        send_typing_action(chat_id)

        pings_sent += 1
        if pings_sent >= max_pings:
            logger.info(f"Typing indicator for task_id={task_id} reached its ping cap ({max_pings}). Stopping.")
            _stop(task_id)
            if on_giveup is not None:
                on_giveup(task_id, "ping_cap_reached")
            return

        interval = random.uniform(settings.TELEGRAM_TYPING_INTERVAL_MIN, settings.TELEGRAM_TYPING_INTERVAL_MAX)
        stop_event.wait(interval)

def start_typing(task_id: str, chat_id: int, on_giveup=None) -> None:
    """
    Starts the typing indicator loop for a task, if one is not already running.

    Args:
        task_id (str)

        chat_id (int)

        on_giveup (Callable[[str, str], None] | None, optional):
            See _typing_loop(). Defaults to None.

    Returns:
        None
    """
    with _lock:
        if task_id in _active_typing:
            return

        stop_event = threading.Event()
        _active_typing[task_id] = stop_event

    threading.Thread(
        target=_typing_loop,
        args=(task_id, chat_id, stop_event, on_giveup),
        daemon=True
    ).start()
    logger.info(f"Started typing indicator for task_id={task_id} (chat_id={chat_id}).")

def stop_typing(task_id: str) -> None:
    """
    Stops the typing indicator loop for a task, if one is active.

    Args:
        task_id (str)

    Returns:
        None
    """
    _stop(task_id)

# =============================================================================
