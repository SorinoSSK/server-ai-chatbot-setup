# =============================================================================
# File        : coder_call.py
# Description : Coder Call - the implementation/code-writing role in the multi-agent "Call" model.
# Author      : SorinoSSK
# Created On  : 2026-09-10
#
# Features    :
#   - handle() - sends a prompt to this Call's configured LLM (settings.LLM_CODER_TYPE), together with the
#     persona/agent-context content loaded for whichever provider that resolves to (currently empty for
#     every provider - not yet written).
#
# Notes       :
#   - Per bot_sanctuary/CODE_TODO.md §6, this Call (unlike Chat) is intended to get filesystem/tool access
#     - not yet wired here, since no tool-calling mechanism has been decided yet.
#   - Persona content lives at bot_sanctuary_application/libraries/<llm_type>/coder.md, one file per
#     provider (see chat_call.py's own Notes for the full design) - loaded via
#     utils_agents/agent_interface.py::load_persona(). Every provider's copy is deliberately empty for now,
#     per explicit instruction ("leave coder, reviewer, and documentation's persona empty for now") - LLM
#     wiring/handoff plumbing is in place, but this Call has no persona/agent-context yet. See chat_call.py
#     for the shape a persona takes once written.
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

CALL_NAME = "coder"

# =============================================================================

async def handle(prompt: str) -> str | None:
    """
    Handles a single turn for the Coder Call.

    Args:
        prompt (str):
            The prompt/context for this turn.

    Returns:
        str | None:
            The assistant's reply, or None if LLM_CODER_TYPE (which falls back to LLM_CHAT_TYPE if unset)
            is unset, or the underlying call failed.

    Notes:
        - Persona content is loaded fresh from libraries/<llm_type>/coder.md on every call (currently empty
          for every provider) and passed as query_llm()'s persona argument - see chat_call.py's own Notes
          for how each provider delivers a non-empty one natively.
    """
    if not settings.LLM_CODER_TYPE:
        logger.warning(f"{CALL_NAME} Call has no LLM_CODER_TYPE (or fallback LLM_CHAT_TYPE) configured - skipping.")
        return None
    else:
        persona = load_persona(settings.LLM_CODER_TYPE, CALL_NAME)
        return await query_llm(settings.LLM_CODER_TYPE, prompt, persona=persona)

# =============================================================================
