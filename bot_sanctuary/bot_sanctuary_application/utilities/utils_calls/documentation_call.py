# =============================================================================
# File        : documentation_call.py
# Description : Documentation Call - the documentation-writing role in the multi-agent "Call" model.
# Author      : SorinoSSK
# Created On  : 2026-09-10
#
# Features    :
#   - handle() - sends a prompt to this Call's configured LLM, together with its persona content.
#
# Notes       :
#   - Intended to get filesystem/tool access, unlike Chat - not yet wired, see CODE_TODO.md.
#   - Persona content is loaded per provider from libraries/<llm_type>/documentation.md, currently empty for every provider.
#   - No handoff decision logic or bounded turn loop yet.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging

from ...config import settings
from ..utils_agents.agent_interface import load_persona, query_llm

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

CALL_NAME = "documentation"

# =============================================================================

async def handle(prompt: str) -> str | None:
    """
    Handles a single turn for the Documentation Call.

    Args:
        prompt (str):
            The prompt/context for this turn.

    Returns:
        str | None:
            The assistant's reply, or None if LLM_DOCUMENTATION_TYPE (falls back to LLM_CHAT_TYPE) is unset, or the underlying call failed.
    """
    if not settings.LLM_DOCUMENTATION_TYPE:
        logger.warning(f"{CALL_NAME} Call has no LLM_DOCUMENTATION_TYPE (or fallback LLM_CHAT_TYPE) configured - skipping.")
        return None
    else:
        persona = load_persona(settings.LLM_DOCUMENTATION_TYPE, CALL_NAME)
        return await query_llm(settings.LLM_DOCUMENTATION_TYPE, prompt, persona=persona)

# =============================================================================
