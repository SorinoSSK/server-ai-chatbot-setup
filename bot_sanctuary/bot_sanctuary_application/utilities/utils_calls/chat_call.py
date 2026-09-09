# =============================================================================
# File        : chat_call.py
# Description : Chat Call - the entry/default conversational Call in the multi-agent "Call" model (persona: Rukia). Renamed from rukia_call.py.
# Author      : SorinoSSK
# Created On  : 2026-09-10
#
# Features    :
#   - handle() - sends a prompt to this Call's configured LLM (settings.LLM_CHAT_TYPE), together with the
#     persona/agent-context content loaded for whichever provider that resolves to.
#
# Notes       :
#   - Per bot_sanctuary/CODE_TODO.md §5/§6: this Call is conversation/routing only - it has no access to
#     the repository/container filesystem or any code tool at all, unlike Architect/Coder/Review/
#     Documentation. A non-whitelisted user's task is tagged Chat-only by telegram_gateway (no handoff
#     permitted at all) - this Call's total lack of tool access is what makes that restriction a real
#     access boundary, not just a routing default.
#   - No handoff decision logic yet, and no bounded turn loop - see CODE_TODO.md §5's phased plan (Phase 3
#     onward) for what still wraps around this function.
#   - Persona content no longer lives in this file as a Python string constant - it's loaded at call time
#     from bot_sanctuary_application/libraries/<llm_type>/chat.md (via
#     utils_agents/agent_interface.py::load_persona()), one file per provider, so this Call can have a
#     genuinely different, provider-optimised persona depending on which LLM_CHAT_TYPE is actually
#     configured (e.g. libraries/claude/chat.md carries real Claude subagent-style frontmatter -
#     tools:/model: - that claude_interface.py wires into actual ClaudeAgentOptions fields; an
#     OpenAI-compatible provider's copy is just plain persona text - see each <provider>_interface.py's own
#     Notes). Today only libraries/claude/chat.md has been written (the user-authored "Rukia" persona,
#     verbatim); the other three providers' copies are still empty placeholders.
#   - persona is passed to query_llm() as its own argument, never concatenated into prompt - see
#     query_llm()'s own Notes for why.
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
        - Persona content is loaded fresh from libraries/<llm_type>/chat.md on every call (not cached at
          import time), so an LLM_CHAT_TYPE change takes effect on the next call with no restart needed.
          Passed as query_llm()'s persona argument, not prepended to prompt - see module Notes for how each
          provider delivers it natively.
    """
    if not settings.LLM_CHAT_TYPE:
        logger.warning(f"{CALL_NAME} Call has no LLM_CHAT_TYPE configured - skipping.")
        return None
    else:
        persona = load_persona(settings.LLM_CHAT_TYPE, CALL_NAME)
        return await query_llm(settings.LLM_CHAT_TYPE, prompt, persona=persona)

# =============================================================================
