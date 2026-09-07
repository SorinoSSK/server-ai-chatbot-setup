# =============================================================================
# File        : initialise.py
# Description : Provides centralised application initialisation for the Bot Sanctuary application.
# Author      : SorinoSSK
# Created On  : 2026-09-06
#
# Features    :
#   - test_llm_oauth_token() - one-off startup smoke test that sends a minimal prompt through claude_agent_sdk using LLM_OAUTH_TOKEN, logging whatever comes back (or why it failed).
#   - RabbitMQ consume connection initialisation and the background consumer thread (see utils_queue/queue.py) - the session-routing/agent-call pipeline is added here as its owning modules are built (see bot_sanctuary/CODE_TODO.md).
#
# Notes       :
#   - Intended to be executed once during application startup.
#   - Initialisation order should follow application dependency requirements.
#   - test_llm_oauth_token() is a standalone smoke test, not part of the RabbitMQ pipeline - it exists purely to confirm LLM_OAUTH_TOKEN is valid/reachable at startup, nothing more.
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

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# =============================================================================

async def _send_llm_test_prompt() -> None:
    """
    Sends a single minimal prompt through claude_agent_sdk, logging the assistant's reply.

    Args:
        None

    Returns:
        None

    Notes:
        - claude_agent_sdk resolves credentials via its own CLAUDE_CODE_OAUTH_TOKEN environment variable (per bot_sanctuary/CODE_TODO.md's credential resolution order) - not LLM_OAUTH_TOKEN directly, so it's bridged across here, at the one call site that actually needs it, keeping config.py's own LLM_TYPE/LLM_OAUTH_TOKEN provider-agnostic.
        - Deferred import of claude_agent_sdk - this is the only place in the module that needs it.
        - Any failure (bad/expired token, network issue, SDK error) is caught and logged, not raised - a failed smoke test must not crash application startup.
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
    Runs a one-off startup smoke test of LLM_OAUTH_TOKEN, logging the response (or failure).

    Args:
        None

    Returns:
        None

    Notes:
        - No-op (logged) if LLM_OAUTH_TOKEN is unset, or LLM_TYPE isn't "claude" - only the claude_agent_sdk path is implemented so far (see bot_sanctuary/CODE_TODO.md).
        - Synchronous wrapper around _send_llm_test_prompt() - the rest of the application has no other async code yet, so the event loop is spun up and torn down just for this call.
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

    Args:
        None

    Returns:
        None

    Notes:
        - Opens the RabbitMQ consume connection (retrying indefinitely if not yet reachable - see utils_queue/queue.py::initialise_rabbitmq_connection()) and starts the background consumer thread.
        - The session-routing/agent-call pipeline is still a placeholder at the message-handling layer (see utils_queue/message_handler.py) - see bot_sanctuary/CODE_TODO.md §3.
    """
    test_llm_oauth_token()

    initialise_rabbitmq_connection()
    start_queue_consumer()

    logger.info("Bot Sanctuary application initialised.")

def terminate_application() -> None:
    """
    Runs application shutdown steps.

    Args:
        None

    Returns:
        None

    Notes:
        - close_redis_connection() is a safe no-op if the gateway_alert throttle's lazy Redis connection (see utils_redis/database.py) was never actually opened.
    """
    stop_queue_consumer()
    close_rabbitmq_connection()
    close_redis_connection()
    logger.info("Bot Sanctuary application terminated.")

# =============================================================================
