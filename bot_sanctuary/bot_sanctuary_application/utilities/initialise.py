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
#   - See README.md for the full startup/shutdown sequence and design rationale.
#
# =============================================================================
# I M P O R T   H E A D E R

import os
import asyncio
import logging

from ..config import settings
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

async def _send_llm_test_prompt() -> None:
    """
    Sends a single test prompt through the Claude Agent SDK, logging the assistant's reply.

    Used to confirm that LLM_OAUTH_TOKEN is valid and the LLM endpoint is reachable during startup.

    Args:
        None

    Returns:
        None

    Notes:
        - Any failure is caught and logged rather than raised, so a failed test never crashes application startup.
    """
    from claude_agent_sdk import AssistantMessage, TextBlock, query

    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = settings.LLM_OAUTH_TOKEN

    try:
        async for message in query(prompt="Hello Claude - this is a startup connectivity test. Reply with a short acknowledgement."):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        logger.info(f"LLM_OAUTH_TOKEN test response: {block.text}")
    except Exception:
        logger.exception("LLM_OAUTH_TOKEN test failed - credential may be invalid/expired, or the LLM endpoint is unreachable.")

def test_llm_oauth_token() -> None:
    """
    Runs a one-off startup smoke test of LLM_OAUTH_TOKEN, logging the outcome.

    Args:
        None

    Returns:
        None

    Notes:
        - Skipped, with a warning logged, if no credential is configured or the configured provider is not yet supported.
    """
    if not settings.LLM_OAUTH_TOKEN:
        logger.warning("LLM_OAUTH_TOKEN is unset - skipping startup LLM credential test.")
        return
    elif settings.LLM_TYPE != "claude":
        logger.warning(f"LLM_TYPE={settings.LLM_TYPE!r} is not a supported provider for the startup LLM credential test yet - skipping.")
        return
    else:
        asyncio.run(_send_llm_test_prompt())

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
    test_llm_oauth_token()

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
