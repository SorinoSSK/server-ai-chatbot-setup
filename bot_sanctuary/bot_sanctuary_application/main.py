# =============================================================================
# File        : main.py
# Description : Primary entry point used to start and run Bot Sanctuary.
# Author      : SorinoSSK
# Created On  : 2026-09-06
#
# Features    :
#   - Performs application startup/shutdown wiring (data directory, logging, signal handling).
#
# Notes       :
#   - initialise_application() (see utilities/initialise.py) runs a one-off startup smoke test for every configured LLM provider credential, opens the RabbitMQ consume connection, and starts the background consumer thread.
#   - The session-routing/agent-call pipeline is still a placeholder at the message-handling layer (see utilities/utils_queue/message_handler.py) - see bot_sanctuary/CODE_TODO.md §3.
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

    Performs application setup (data directory, logging), registers shutdown signal handlers, initialises the application, then blocks the main thread until a shutdown signal is received before terminating.

    Args:
        None

    Returns:
        None

    Notes:
        - Setup is performed here (rather than at module import time) so importing this module has no filesystem/logging side effects - only running it as the application entry point does.
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
