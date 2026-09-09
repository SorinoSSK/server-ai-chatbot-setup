# =============================================================================
# File        : agent_interface.py
# Description : Provider-agnostic entry point for sending a prompt to an explicitly-named LLM provider, plus the startup LLM credential smoke test.
# Author      : SorinoSSK
# Created On  : 2026-09-10
#
# Features    :
#   - query_llm() - sends a prompt to an explicitly-named provider (llm_type), via that provider's own
#     configured access method/credential (config.py's per-provider LLM_<PROVIDER>_ACCESS_TYPE/TOKEN).
#   - test_llm_tokens() - one-off startup smoke test, invoked from utilities/initialise.py, run once per
#     provider that actually has a credential configured.
#
# Notes       :
#   - More than one provider's credentials can be configured/tested at once - there is no longer a single
#     "current" global provider. query_llm() takes llm_type as an explicit argument (a plain string -
#     "claude"/"codex"/"deepseek"/"qwen") rather than reading a single settings.LLM_TYPE, precisely so more
#     than one caller can each ask for a different provider. All four are wired today via their own
#     <provider>_interface.py; only claude/codex actually support both access types - deepseek/qwen are
#     API-key-only, and their own query_via_oauth() is a stub that logs and returns None rather than being
#     a real implementation (see each module's own Notes for why).
#   - **Per-Call provider routing is now real** - each named Call (Chat/Architect/Coder/Review/
#     Documentation, see utils_calls/) resolves its own config.py LLM_<CALL>_TYPE and calls query_llm()
#     with it directly. This module still only provides the building block (an explicit-llm_type
#     query_llm()) - it has no opinion on which Call is calling it or why, that routing logic lives in
#     utils_calls/ (see bot_sanctuary/CODE_TODO.md §5).
#   - Add a <provider>_interface.py alongside this file (same two-endpoint shape as the four existing
#     ones - a query_via_oauth(prompt, token, persona=None) and a query_via_api(prompt, token, persona=None),
#     even if one is only ever a "not supported" stub) and a matching branch in _resolve_provider() below,
#     for any further future provider - see bot_sanctuary/CODE_TODO.md §1/§2.
#   - test_llm_tokens() calls query_llm() itself for each configured provider - it is not a special-cased
#     path outside the normal dispatch, unlike the single-provider smoke test this replaced.
#   - query_llm()'s optional persona argument is passed straight through to whichever provider module is
#     resolved, which is each provider's own native mechanism for it - never string-concatenated into
#     prompt here or by any Call. See each <provider>_interface.py's own Notes for what "native" means for
#     that provider (Claude Agent SDK's system_prompt/tools/model options; a per-call AGENTS.md for Codex;
#     an OpenAI-style "system" role message for DeepSeek/Qwen).
#   - load_persona() reads that persona content from bot_sanctuary_application/libraries/<llm_type>/
#     <call_name>.md - one file per provider per Call, so the same Call can have a differently-optimised
#     persona depending on which provider it's actually configured to use (e.g. Claude's copy is written
#     with its own name:/description:/tools:/model: frontmatter, meaningful to claude_interface.py; an
#     OpenAI-compatible provider's copy is just plain persona text). Callers (each <name>_call.py) resolve
#     their own llm_type first and pass it here - this module has no opinion on which provider a Call uses,
#     same as query_llm() itself. See bot_sanctuary/CODE_TODO.md §5 for the wider design.
#
# =============================================================================
# I M P O R T   H E A D E R

import asyncio
import logging
from pathlib import Path

from ...config import settings
from . import claude_interface
from . import codex_interface
from . import deepseek_interface
from . import qwen_interface

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_KNOWN_LLM_TYPES = ("claude", "codex", "deepseek", "qwen")

# bot_sanctuary_application/libraries/ - this file lives at
# bot_sanctuary_application/utilities/utils_agents/agent_interface.py, three levels below it.
_LIBRARIES_ROOT = Path(__file__).resolve().parent.parent.parent / "libraries"

# =============================================================================

def _resolve_provider(llm_type: str) -> tuple[object, str, str] | None:
    """
    Resolves an llm_type string to its interface module and configured credential.

    Args:
        llm_type (str):
            Which provider to resolve - "claude", "codex", "deepseek", or "qwen".

    Returns:
        tuple[object, str, str] | None:
            (provider module, access_type, token) for a recognised llm_type; otherwise None.
    """
    if llm_type == "claude":
        return claude_interface, settings.LLM_CLAUDE_ACCESS_TYPE, settings.LLM_CLAUDE_TOKEN
    elif llm_type == "codex":
        return codex_interface, settings.LLM_CODEX_ACCESS_TYPE, settings.LLM_CODEX_TOKEN
    elif llm_type == "deepseek":
        return deepseek_interface, settings.LLM_DEEPSEEK_ACCESS_TYPE, settings.LLM_DEEPSEEK_TOKEN
    elif llm_type == "qwen":
        return qwen_interface, settings.LLM_QWEN_ACCESS_TYPE, settings.LLM_QWEN_TOKEN
    else:
        return None

def load_persona(llm_type: str, call_name: str) -> str | None:
    """
    Loads the persona/agent-context content optimised for the given provider and Call, if one has been written.

    Args:
        llm_type (str):
            Which provider's variant to load - "claude", "codex", "deepseek", or "qwen".

        call_name (str):
            Which Call's persona to load - matches that Call's own CALL_NAME (e.g. "chat").

    Returns:
        str | None:
            The raw content of libraries/<llm_type>/<call_name>.md, or None if that file doesn't exist or
            is empty/whitespace-only (not yet written for that provider/Call combination).

    Notes:
        - Returns raw file content, unparsed - claude_interface.py parses its own frontmatter
          (name:/description:/tools:/model:) out of what this returns; other providers use it as-is.
    """
    library_file = _LIBRARIES_ROOT / llm_type / f"{call_name}.md"
    if not library_file.is_file():
        return None
    else:
        content = library_file.read_text(encoding="utf-8").strip()
        return content or None

async def query_llm(llm_type: str, prompt: str, persona: str | None = None) -> str | None:
    """
    Sends a prompt to the given LLM provider, via that provider's own configured access method/credential.

    Args:
        llm_type (str):
            Which provider to use - "claude", "codex", "deepseek", or "qwen". Passed explicitly by the
            caller rather than read from a single global setting, since more than one provider's
            credentials can be configured at once (see config.py's per-provider LLM_<PROVIDER>_* settings).

        prompt (str):
            The prompt to send.

        persona (str | None):
            Optional persona/agent-context content for this call, typically the result of a prior
            load_persona() call. Delivered via whichever mechanism is native to the resolved provider (see
            this module's own Notes above) - never concatenated into prompt here.

    Returns:
        str | None:
            The assistant's text reply, or None if llm_type is not recognised, its configured access type
            is invalid, or the underlying call failed.
    """
    resolved = _resolve_provider(llm_type)
    if resolved is None:
        logger.warning(f"llm_type={llm_type!r} is not a supported provider - skipping query.")
        return None
    else:
        provider, access_type, token = resolved
        access_type = access_type.upper()
        if access_type == "OAUTH":
            return await provider.query_via_oauth(prompt, token, persona)
        elif access_type == "API":
            return await provider.query_via_api(prompt, token, persona)
        else:
            logger.warning(f"llm_type={llm_type!r} has an invalid access type ({access_type!r} - expected 'API' or 'OAUTH') - skipping query.")
            return None

async def _send_llm_test_prompt(llm_type: str) -> None:
    """
    Sends a single startup test prompt to the given provider, logging the assistant's reply.

    Args:
        llm_type (str):
            Which provider to test.

    Returns:
        None

    Notes:
        - Delegates to query_llm() - any failure there is already caught and logged internally by the
          provider's own interface module, so a failed test never crashes application startup.
    """
    reply = await query_llm(llm_type, f"Hello - this is a startup connectivity test for {llm_type}. Reply with a short acknowledgement.")
    if reply is not None:
        logger.info(f"{llm_type} credential test response: {reply}")
    else:
        pass  # Failure is already logged inside query_llm()/the provider's own interface module - nothing further to do here.

def test_llm_tokens() -> None:
    """
    Runs a one-off startup smoke test for every LLM provider that has a credential configured.

    Args:
        None

    Returns:
        None

    Notes:
        - Independent of config.py's LLM_CHAT_TYPE - every provider with a non-empty token is tested, not
          just whichever one a future chat/Call pipeline might be configured to use.
        - A provider with no token configured is skipped with an info log, not a warning - having only
          some providers configured is the expected/normal case, not a misconfiguration.
        - Each provider is tested with its own currently-configured access type - this does not attempt
          both OAUTH and API per provider, only whichever one is actually set.
    """
    for llm_type in _KNOWN_LLM_TYPES:
        _, _, token = _resolve_provider(llm_type)
        if not token:
            logger.info(f"No credential configured for llm_type={llm_type!r} - skipping its startup LLM credential test.")
            continue
        else:
            asyncio.run(_send_llm_test_prompt(llm_type))

# =============================================================================
