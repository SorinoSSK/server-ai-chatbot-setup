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

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# =============================================================================

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
            - bool:
                True if shutdown has been signalled (i.e. set() has been called); otherwise False.
        """
        return self.is_set()

    def handle_signal(self, signum, frame) -> None:
        """
        Signal handler compatible with signal.signal() - signals shutdown when invoked.

        Args:
            - signum (int):
                Signal number received (e.g. signal.SIGINT, signal.SIGTERM).

            - frame (types.FrameType | None):
                Current stack frame, as passed by the signal module. Unused.

        Returns:
            None
        """
        logger.info(f"Shutdown signal received (signum={signum}).")
        self.set()

# =============================================================================
