# =============================================================================
# File        : utilities.py
# Description : Provides reusable utility functions/classes shared across the application.
#
# Author      : SorinoSSK
# Created On  : 2026-08-29
#
# Notes       :
#   - Contains common helper and utility functions.
#   - Intended for functions that are reused by multiple modules.
#   - Avoid placing application-specific business logic in this file.
#   - Avoid implementing functions that have dependencies on external files.
# =============================================================================
# I M P O R T   H E A D E R

import logging
import threading

from datetime import datetime

from ..config import settings

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# =============================================================================

def application_time() -> datetime:
    """
    Returns the application's current time, as a timezone-aware datetime anchored to settings.TZ.

    Args:
        None

    Returns:
        datetime:
            The current time in settings.TZ.

    Notes:
        - The single source of truth for "what time is it right now" throughout the application - every module needing the current time should call this rather than datetime.now()/time.time() directly, so every timing decision and every stored timestamp agrees on the same clock.
        - Anchored to settings.TZ, not the container's OS-level local time directly - same reasoning as logging_setup.py's log timestamps.
    """
    return datetime.now(settings.TZ)

def application_time_diff(reference: float) -> float:
    """
    Computes the number of seconds elapsed since a previously captured epoch timestamp, measured against application_time().

    Args:
        reference (float):
            An earlier point in time as a POSIX timestamp - normally application_time().timestamp(), as stored by whatever originally recorded it.

    Returns:
        float:
            Elapsed seconds since reference, measured against application_time().

    Notes:
        - Exists alongside application_time() for callers that persist a bare epoch float rather than a datetime, and only ever need the elapsed duration back, not the wall-clock time itself.
    """
    return application_time().timestamp() - reference

class ShutdownSignal(threading.Event):
    """
    Wraps threading.Event to add is_terminating() and a signal.signal()-compatible handle_signal().

    Example:
        shutdown_event = ShutdownSignal()
        signal.signal(signal.SIGINT, shutdown_event.handle_signal)
        signal.signal(signal.SIGTERM, shutdown_event.handle_signal)
        ...
        while not shutdown_event.is_terminating():
            ...
    """

    def is_terminating(self) -> bool:
        """
        Check whether shutdown has been signalled.

        Args:
            None

        Returns:
            bool:
                True if signalled; otherwise False.
        """
        return self.is_set()

    def handle_signal(self, signum, frame) -> None:
        """
        Signal handler compatible with signal.signal() - signals shutdown when invoked.

        Args:
            signum (int):
                Signal number received.

            frame:
                Unused, passed by the signal module.

        Returns:
            None
        """
        logger.info(f"Shutdown signal received (signum={signum}).")
        self.set()

# =============================================================================
