# =============================================================================
# File        : architect_call.py
# Description : Architect Call - the software architecture/design role in the multi-agent "Call" model.
# Author      : SorinoSSK
# Created On  : 2026-09-10
#
# Features    :
#   - handle() - sends a prompt to this Call's configured LLM (settings.LLM_ARCHITECT_TYPE), together with
#     the persona/agent-context content loaded for whichever provider that resolves to (currently empty for
#     every provider - not yet written).
#
# Notes       :
#   - Per bot_sanctuary/CODE_TODO.md §6, this Call (unlike Chat) is intended to get filesystem/tool access
#     - not yet wired here, since no tool-calling mechanism has been decided yet.
#   - Persona content lives at bot_sanctuary_application/libraries/<llm_type>/architect.md, one file per
#     provider (see chat_call.py's own Notes for the full design) - loaded via
#     utils_agents/agent_interface.py::load_persona(). Every provider's copy is deliberately empty for now,
#     same treatment applied to coder_call.py/review_call.py/documentation_call.py per explicit instruction
#     - not explicitly named alongside those three, but kept consistent with them here rather than left on
#     the old unwired placeholder shape. Flag if Architect was actually meant to be excluded from this pass.
#   - No handoff decision logic yet, and no bounded turn loop - see CODE_TODO.md §5's phased plan (Phase 3
#     onward) for what still wraps around this function.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging

from ...config import settings
from ..utils_agents.agent_interface import load_persona, query_llm

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

CALL_NAME = "architect"

# =============================================================================

async def handle(prompt: str) -> str | None:
    """
    Handles a single turn for the Architect Call.

    Args:
        prompt (str):
            The prompt/context for this turn.

    Returns:
        str | None:
            The assistant's reply, or None if LLM_ARCHITECT_TYPE (which falls back to LLM_CHAT_TYPE if
            unset) is unset, or the underlying call failed.

    Notes:
        - Persona content is loaded fresh from libraries/<llm_type>/architect.md on every call (currently
          empty for every provider) and passed as query_llm()'s persona argument - see chat_call.py's own
          Notes for how each provider delivers a non-empty one natively.
    """
    if not settings.LLM_ARCHITECT_TYPE:
        logger.warning(f"{CALL_NAME} Call has no LLM_ARCHITECT_TYPE (or fallback LLM_CHAT_TYPE) configured - skipping.")
        return None
    else:
        persona = load_persona(settings.LLM_ARCHITECT_TYPE, CALL_NAME)
        return await query_llm(settings.LLM_ARCHITECT_TYPE, prompt, persona=persona)

# =============================================================================
