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
#   - Mirrors utils_agents/agent_interface.py's own dispatch-by-name shape (a registry lookup plus one
#     explicit-argument entry point), applied to Calls instead of LLM providers.
#   - Deliberately, individual Call modules (chat_call.py/architect_call.py/coder_call.py/review_call.py/
#     documentation_call.py) never import each other or this router - that would need five modules to all
#     know about each other (and about this router, which already knows about all five), a circular-import
#     shape with no real benefit. This router is instead the one place that knows about every Call and
#     mediates any handoff between them - "every Call type can call every other" is satisfied by this one,
#     central, any-to-any handoff function, not by direct module-to-module references. A Call module is
#     expected to stay self-contained (prompt in, reply out); deciding *whether* to hand off, and to whom,
#     is intended to live in the per-thread turn loop that calls handoff_call() (not yet built - see
#     CODE_TODO.md §5's phased plan), not inside a Call module itself.
#   - No bounded back-and-forth limit, no whitelist/access-tier check, and no turn loop exist yet - this is
#     routing/dispatch plumbing only. See bot_sanctuary/CODE_TODO.md §5 for the phased plan this belongs to.
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
            The target Call's reply, or None if target_call isn't recognised, or the Call itself returned
            nothing.

    Notes:
        - Any Call can be handed off to from any other - there is no fixed pipeline order enforced here
          (see bot_sanctuary/CODE_TODO.md §5 - "any Call may respond directly or hand off to another Call").
        - Does not bound how many handoffs a single turn can chain through - that belongs to the per-thread
          turn loop this router is meant to be called from, not yet built (see CODE_TODO.md §5).
    """
    call = get_call(target_call)
    if call is None:
        logger.warning(f"target_call={target_call!r} is not a recognised Call - skipping handoff.")
        return None
    else:
        return await call.handle(prompt)

# =============================================================================
