# =============================================================================
# File        : initialise.py
# Description : Provides centralised application initialisation for the Bot Sanctuary application.
# Author      : SorinoSSK
# Created On  : 2026-09-06
#
# Features    :
#   - Startup sweep clearing every leftover on-disk session directory, ahead of everything else.
#   - Starts/stops every LLM provider's own always-on service, ahead of the LLM credential smoke test.
#   - One-off LLM credential smoke test performed during startup.
#   - RabbitMQ consume connection and background consumer lifecycle management.
#   - Unconditional bot_started broadcast on every startup, ahead of crash recovery.
#   - Crash-recovery sweep for sessions left dangling by a prior run.
#   - Starts the optional daily timed global session reset, if configured.
#   - Graceful shutdown of active session workers ahead of connection teardown, then the LLM services above.
#
# Notes       :
#   - Intended to be invoked once during application startup and once during shutdown.
#   - LLM services are started before the credential smoke test, since a provider's credential may need resolving first.
#   - LLM services are stopped after every session worker has finished, since a worker's last turn may still be mid-call against one.
#   - See README.md for the full startup/shutdown sequence and design rationale.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging

from .utils_agents.agent_interface import initialise_llm_services, terminate_llm_services, test_llm_tokens
from .utils_queue.queue import (
    initialise_rabbitmq_connection,
    start_queue_consumer,
    stop_queue_consumer,
    close_rabbitmq_connection,
    RabbitMQPublisher
)
from .utils_redis.database import close_redis_connection
from .utils_session.session_worker import (
    clear_all_session_directories,
    resync_orphaned_sessions,
    shutdown_all_session_workers,
    start_session_reset_schedule,
    stop_session_reset_schedule
)

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# =============================================================================

def _push_bot_started() -> None:
    """
    Publishes an unconditional bot_started event to telegram_gateway on every application startup.

    Fired regardless of cause - a genuine crash-recovery restart or a routine redeploy alike - since either way this application has no memory of what it was doing before.

    Args:
        None

    Returns:
        None

    Notes:
        - Fired once RabbitMQ connectivity is already confirmed, ahead of the crash-recovery sweep.
        - Best-effort and non-fatal - a failed publish is logged and startup proceeds regardless.
    """
    publisher = RabbitMQPublisher()
    try:
        if publisher.publish({"type": "bot_started"}):
            logger.info("Published bot_started - this application has just started (crash-recovery restart or a routine redeploy).")
        else:
            logger.error("Failed to publish bot_started - telegram_gateway's own PENDING_RESET_MAX_WAIT_SECONDS ceiling sweep remains the fallback for whatever this was meant to reconcile.")
    finally:
        publisher.close()

def initialise_application() -> None:
    """
    Runs application startup steps.

    Starts every LLM provider's own always-on service, performs the LLM credential smoke test, establishes the RabbitMQ consume connection, broadcasts bot_started, recovers any sessions left dangling by a prior run, starts the optional timed session reset schedule, and starts the background message consumer.

    Args:
        None

    Returns:
        None

    Notes:
        - See README.md for the full startup sequence and its design rationale.
    """
    clear_all_session_directories()

    initialise_llm_services()
    test_llm_tokens()

    initialise_rabbitmq_connection()
    _push_bot_started()
    resync_orphaned_sessions()
    start_session_reset_schedule()
    start_queue_consumer()

    logger.info("Bot Sanctuary application initialised.")

def terminate_application() -> None:
    """
    Runs application shutdown steps.

    Stops the timed session reset schedule and accepting new messages, allows active session workers to finish their current work, stops every LLM provider's own always-on service, then closes the RabbitMQ and Redis connections.

    Args:
        None

    Returns:
        None

    Notes:
        - See README.md for the full shutdown sequence and its design rationale.
    """
    stop_session_reset_schedule()
    stop_queue_consumer()
    shutdown_all_session_workers()
    terminate_llm_services()
    close_rabbitmq_connection()
    close_redis_connection()
    logger.info("Bot Sanctuary application terminated.")

# =============================================================================
