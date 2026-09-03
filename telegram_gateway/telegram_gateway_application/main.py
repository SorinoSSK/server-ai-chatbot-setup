# =============================================================================
# File        : main.py
# Description : Primary entry point used to start and run the Telegram Gateway.
# Author      : SorinoSSK
# Created On  : 2026-08-29
#
# Features    :
#   - Initialises RabbitMQ and starts the RabbitMQ consumer and Telegram long polling loop, each on its own thread.
#   - Performs a graceful shutdown of both threads on SIGINT/SIGTERM.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging
import signal

from .config import settings
from .utilities.logging import setup_logging
from .utilities.utilities import ShutdownSignal
from .utilities.initialise import initialise_application, terminate_application

# =============================================================================
# A P P L I C A T I O N   S E T U P

settings.DATA_DIR.mkdir(parents=True, exist_ok=True)

setup_logging()
logger = logging.getLogger(__name__)

_shutdown_event = ShutdownSignal()

# =============================================================================
# M A I N

def main():
    """
    Runs the Telegram Gateway application for its entire process lifetime.

    Registers shutdown signal handlers, initialises the application, then blocks the main thread until a shutdown signal is received before terminating.

    Args:
        None

    Returns:
        None
    """
    logger.info("Starting Telegram Gateway...")

    signal.signal(signal.SIGINT, _shutdown_event.handle_signal)
    signal.signal(signal.SIGTERM, _shutdown_event.handle_signal)

    logger.info("Telegram Gateway Initialising...")
    initialise_application()

    # Block the main thread until a shutdown signal is received.
    _shutdown_event.wait()

    logger.info("Telegram Gateway Terminating...")
    terminate_application()

if __name__ == "__main__":
    main()

# =============================================================================
