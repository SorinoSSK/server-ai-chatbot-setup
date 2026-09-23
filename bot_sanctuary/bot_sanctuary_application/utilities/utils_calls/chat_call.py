# =============================================================================
# File        : chat_call.py
# Description : Chat Call - the entry/default conversational Call in the multi-agent "Call" model (persona: Rukia).
# Author      : SorinoSSK
# Created On  : 2026-09-10
#
# Features    :
#   - handle() - sends a prompt to this Call's configured LLM, together with its persona content and the available tool formats.
#
# Notes       :
#   - Conversation/routing only - has no filesystem or code tool access, unlike Architect/Coder/Review/Documentation.
#   - Which reply tool to use, or whether to hand off via target_call, is decided entirely by the LLM itself -
#     handle()'s own coding_allowed just tells it upfront whether a handoff is worth attempting at all (see
#     agent_tools.build_tool_prompt()'s own Notes); the actual enforcement lives in
#     call_dispatch_handler.py::message_dissect(), not here.
#   - This file never parses/validates/retries the LLM's raw reply - call_dispatch_handler.py owns all of that.
#   - Persona content is loaded per provider from libraries/<llm_type>/chat.md.
#   - See README.md for how this interacts with Claude's own persistent-platform persona.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging

from pathlib import Path

from ...config import settings
from ..utils_agents import agent_tools
from ..utils_agents.agent_interface import load_persona, query_llm

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

CALL_NAME = settings.CALL_NAME_CHAT

# =============================================================================

async def handle(prompt: str, session_dir: Path, coding_allowed: bool) -> str | None:
    """
    Handles a single turn for the Chat Call.

    Args:
        prompt (str):
            The prompt/context for this turn.

        session_dir (Path):
            This session's own on-disk root directory - this function derives its own Call/LLM-scoped leaf directory before passing it on to query_llm().

        coding_allowed (bool):
            This turn's own resolved coding_allowed (see call_dispatch_handler.py::execute_dispatch_call()'s own
            Notes) - passed straight through to agent_tools.build_tool_prompt() so the LLM is told upfront
            whether a handoff is actually available. Advisory only - message_dissect() is what actually
            enforces it against whatever target_call the LLM's reply ends up requesting, regardless of what it
            was told here (§5 Phase 6 plan, CODE_TODO.md).

    Returns:
        str | None:
            The LLM's raw reply, unparsed, interpreted by call_dispatch_handler.py::message_dissect().
            None if LLM_CHAT_TYPE is unset or the underlying call failed.

    Notes:
        - The LLM decides the tool (or handoff), not this function.
        - Persona content is loaded fresh on every call, so a configuration change takes effect immediately.
        - See README.md for how the derived leaf directory anchors provider-side session continuity.
    """
    if not settings.LLM_CHAT_TYPE:
        logger.warning(f"{CALL_NAME} Call has no LLM_CHAT_TYPE configured - skipping.")
        return None
    else:
        persona = load_persona(settings.LLM_CHAT_TYPE, CALL_NAME)
        call_session_dir = session_dir / CALL_NAME / settings.LLM_CHAT_TYPE
        call_session_dir.mkdir(parents=True, exist_ok=True)
        return await query_llm(settings.LLM_CHAT_TYPE, agent_tools.build_tool_prompt(prompt, coding_allowed), persona=persona, session_dir=call_session_dir)

# =============================================================================
