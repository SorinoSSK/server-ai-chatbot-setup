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
#   - Which reply tool to use (text/poll/image/...), or whether to hand off via target_call, is decided entirely
#     by the LLM itself - agent_tools.build_tool_prompt() appends the available formats to prompt. This file
#     never parses/inspects/validates/retries the LLM's raw reply itself - utils_calls/call_dispatch_handler.py's
#     own message_dissect() owns all of that now (including correcting an invalid reply via a retry, queued
#     back to this same Call) - same shape every other <name>_call.py already uses.
#   - Persona content is loaded per provider from libraries/<llm_type>/chat.md - for Claude specifically, this
#     is only actually used on agent_interface.py's one-shot fallback path (session_dir is None); every real
#     turn (session_dir given) routes through claude_session_service.py's persistent platform instead, which
#     loads its own persona from libraries/claude/chat.json, ignoring whatever this function passes as persona
#     entirely. See claude_interface.py::query_via_oauth()'s own Notes for the full detail.
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

CALL_NAME = "chat"

# =============================================================================

async def handle(prompt: str, session_dir: Path) -> str | None:
    """
    Handles a single turn for the Chat Call.

    Args:
        prompt (str):
            The prompt/context for this turn.

        session_dir (Path):
            This session's own on-disk directory (SessionWorker.session_dir), passed straight through to
            query_llm() as session_dir - see its own Notes for what a given provider actually does with it
            (today, only Claude's session continuity consumes it at all).

    Returns:
        str | None:
            The LLM's raw reply, unparsed - expected to be one of agent_tools.py's TOOLS formats, or a
            {"target_call": ..., "message": ...} call pass (see agent_tools.build_tool_prompt()), interpreted
            entirely by utils_calls/call_dispatch_handler.py::message_dissect(), not by this function.
            None if LLM_CHAT_TYPE is unset or the underlying call failed.

    Notes:
        - The LLM decides the tool (or handoff), not this function - agent_tools.build_tool_prompt() appends
          the available tools/formats to prompt. Whatever the LLM sends back is returned as-is, unexamined.
        - Persona content is loaded fresh on every call, so an LLM_CHAT_TYPE change takes effect immediately.
        - session_dir is forwarded regardless of which provider LLM_CHAT_TYPE names - only claude_interface.py
          currently does anything with it (routes to claude_session_service.py's persistent, per-session_dir
          ClaudeSDKClient platform for OAuth access, or its own resume=<session_id> marker-file mechanism for
          API access). codex/deepseek/qwen accept and ignore it today.
    """
    if not settings.LLM_CHAT_TYPE:
        logger.warning(f"{CALL_NAME} Call has no LLM_CHAT_TYPE configured - skipping.")
        return None
    else:
        persona = load_persona(settings.LLM_CHAT_TYPE, CALL_NAME)
        return await query_llm(settings.LLM_CHAT_TYPE, agent_tools.build_tool_prompt(prompt), persona=persona, session_dir=session_dir)

# =============================================================================
