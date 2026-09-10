# =============================================================================
# File        : main.py
# Description : Primary entry point used to start and run Bot Sanctuary.
# Author      : SorinoSSK
# Created On  : 2026-09-06
#
# Features    :
#   - Application startup/shutdown wiring (data directory, logging, signal handling).
#
# Notes       :
#   - Delegates actual startup/shutdown work to utilities/initialise.py.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging
import signal

from .config import settings
from .utilities.logging_setup import setup_logging
from .utilities.utilities import ShutdownSignal
from .utilities.initialise import initialise_application, terminate_application

# =============================================================================
# M A I N

def main():
    """
    Runs the Bot Sanctuary application for its entire process lifetime.

    Performs application setup, registers shutdown signal handlers, initialises the application, then blocks until a shutdown signal is received before terminating.

    Args:
        None

    Returns:
        None
    """
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings.SESSION_DIR.mkdir(parents=True, exist_ok=True)

    setup_logging()
    logger = logging.getLogger(__name__)

    shutdown_event = ShutdownSignal()

    logger.info("Starting Bot Sanctuary...")

    signal.signal(signal.SIGINT, shutdown_event.handle_signal)
    signal.signal(signal.SIGTERM, shutdown_event.handle_signal)

    logger.info("Bot Sanctuary Initialising...")
    initialise_application()

    # Block the main thread until a shutdown signal is received.
    shutdown_event.wait()

    logger.info("Bot Sanctuary Terminating...")
    terminate_application()

if __name__ == "__main__":
    main()

# =============================================================================
