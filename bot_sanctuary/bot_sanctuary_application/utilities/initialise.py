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
#   - Initialisation order follows each dependency's own startup requirements.
#   - The LLM credential smoke test itself (test_llm_tokens()) lives in utils_agents/agent_interface.py,
#     not here - this module only invokes it, keeping every LLM-facing call in one place. It now tests
#     every configured LLM provider in turn, not just one - see agent_interface.py's own Notes.
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
        - The crash-recovery sweep runs before the consumer thread starts, so no new task can be accepted while it is in progress.
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
        - Steps run in dependency order, so a worker finishing its last batch still has a live connection available to it.
        - See README.md for the full shutdown sequence and its design rationale.
    """
    stop_queue_consumer()
    shutdown_all_session_workers()
    close_rabbitmq_connection()
    close_redis_connection()
    logger.info("Bot Sanctuary application terminated.")

# =============================================================================
