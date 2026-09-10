# =============================================================================
# File        : call_router.py
# Description : Registry and handoff dispatch for the multi-agent "Call" model - lets any Call hand off to any other Call.
# Author      : SorinoSSK
# Created On  : 2026-09-10
#
# Features    :
#   - handoff_call() - hands a prompt off from the current turn to a named target Call.
#   - get_call() - resolves a Call name to its module.
#
# Notes       :
#   - Mirrors agent_interface.py's dispatch-by-name shape, applied to Calls instead of LLM providers.
#   - Individual Call modules never import each other or this router, avoiding circular imports.
#   - No bounded handoff limit, whitelist check, or turn loop exists yet - this is routing plumbing only.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging

from . import architect_call
from . import chat_call
from . import coder_call
from . import documentation_call
from . import review_call

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_CALL_REGISTRY = {
    chat_call.CALL_NAME: chat_call,
    architect_call.CALL_NAME: architect_call,
    coder_call.CALL_NAME: coder_call,
    review_call.CALL_NAME: review_call,
    documentation_call.CALL_NAME: documentation_call,
}

# =============================================================================

def get_call(call_name: str):
    """
    Resolves a Call name to its module.

    Args:
        call_name (str):
            Which Call to resolve - "chat", "architect", "coder", "review", or "documentation".

    Returns:
        module | None:
            The matching Call module, or None if call_name isn't recognised.
    """
    return _CALL_REGISTRY.get(call_name)

async def handoff_call(target_call: str, prompt: str) -> str | None:
    """
    Hands a prompt off to the named target Call.

    Args:
        target_call (str):
            Which Call to hand off to - "chat", "architect", "coder", "review", or "documentation".

        prompt (str):
            The prompt/context being handed off.

    Returns:
        str | None:
            The target Call's reply, or None if target_call isn't recognised or the Call returned nothing.

    Notes:
        - Any Call can be handed off to from any other - there is no fixed pipeline order.
        - Does not bound how many handoffs a single turn can chain through.
    """
    call = get_call(target_call)
    if call is None:
        logger.warning(f"target_call={target_call!r} is not a recognised Call - skipping handoff.")
        return None
    else:
        return await call.handle(prompt)

# =============================================================================
