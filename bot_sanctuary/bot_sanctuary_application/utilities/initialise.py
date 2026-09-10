# =============================================================================
# File        : initialise.py
# Description : Provides centralised application initialisation for the Bot Sanctuary application.
# Author      : SorinoSSK
# Created On  : 2026-09-06
#
# Features    :
#   - One-off LLM credential smoke test performed during startup.
#   - RabbitMQ consume connection and background consumer lifecycle management.
#   - Crash-recovery sweep for sessions left dangling by a prior run.
#   - Graceful shutdown of active session workers ahead of connection teardown.
#
# Notes       :
#   - Intended to be invoked once during application startup and once during shutdown.
#   - See README.md for the full startup/shutdown sequence and design rationale.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging

from .utils_agents.agent_interface import test_llm_tokens
from .utils_queue.queue import (
    initialise_rabbitmq_connection,
    start_queue_consumer,
    stop_queue_consumer,
    close_rabbitmq_connection
)
from .utils_redis.database import close_redis_connection
from .utils_session.session_worker import resync_orphaned_sessions, shutdown_all_session_workers

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# =============================================================================

def initialise_application() -> None:
    """
    Runs application startup steps.

    Performs the LLM credential smoke test, establishes the RabbitMQ consume connection, recovers any sessions left dangling by a prior run, and starts the background message consumer.

    Args:
        None

    Returns:
        None

    Notes:
        - See README.md for the full startup sequence and its design rationale.
    """
    test_llm_tokens()

    initialise_rabbitmq_connection()
    resync_orphaned_sessions()
    start_queue_consumer()

    logger.info("Bot Sanctuary application initialised.")

def terminate_application() -> None:
    """
    Runs application shutdown steps.

    Stops accepting new messages, allows active session workers to finish their current work, then closes the RabbitMQ and Redis connections.

    Args:
        None

    Returns:
        None

    Notes:
        - See README.md for the full shutdown sequence and its design rationale.
    """
    stop_queue_consumer()
    shutdown_all_session_workers()
    close_rabbitmq_connection()
    close_redis_connection()
    logger.info("Bot Sanctuary application terminated.")

# =============================================================================
