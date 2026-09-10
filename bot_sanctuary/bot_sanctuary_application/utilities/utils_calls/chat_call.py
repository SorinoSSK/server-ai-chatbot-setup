# =============================================================================
# File        : chat_call.py
# Description : Chat Call - the entry/default conversational Call in the multi-agent "Call" model (persona: Rukia).
# Author      : SorinoSSK
# Created On  : 2026-09-10
#
# Features    :
#   - handle() - sends a prompt to this Call's configured LLM, together with its persona content.
#
# Notes       :
#   - Conversation/routing only - has no filesystem or code tool access, unlike Architect/Coder/Review/Documentation.
#   - No handoff decision logic or bounded turn loop yet - see CODE_TODO.md.
#   - Persona content is loaded per provider from libraries/<llm_type>/chat.md.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging

from ...config import settings
from ..utils_agents.agent_interface import load_persona, query_llm

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

CALL_NAME = "chat"

# =============================================================================

async def handle(prompt: str) -> str | None:
    """
    Handles a single turn for the Chat Call.

    Args:
        prompt (str):
            The prompt/context for this turn.

    Returns:
        str | None:
            The assistant's reply, or None if LLM_CHAT_TYPE is unset or the underlying call failed.

    Notes:
        - Persona content is loaded fresh on every call, so an LLM_CHAT_TYPE change takes effect immediately.
    """
    if not settings.LLM_CHAT_TYPE:
        logger.warning(f"{CALL_NAME} Call has no LLM_CHAT_TYPE configured - skipping.")
        return None
    else:
        persona = load_persona(settings.LLM_CHAT_TYPE, CALL_NAME)
        return await query_llm(settings.LLM_CHAT_TYPE, prompt, persona=persona)

# =============================================================================
