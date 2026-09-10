# =============================================================================
# File        : agent_interface.py
# Description : Provider-agnostic entry point for sending a prompt to an explicitly-named LLM provider, plus the startup LLM credential smoke test.
# Author      : SorinoSSK
# Created On  : 2026-09-10
#
# Features    :
#   - query_llm() - sends a prompt to an explicitly-named provider, via that provider's configured access method/credential.
#   - load_persona() - loads a provider/Call-specific persona file, if one has been written.
#   - test_llm_tokens() - one-off startup smoke test, run once per provider with a configured credential.
#
# Notes       :
#   - More than one provider can be configured and used at once - callers pass llm_type explicitly rather than reading a single global setting.
#   - Add a matching <provider>_interface.py and a branch in _resolve_provider() to support a further provider.
#   - persona is passed through to the resolved provider's own native mechanism, never concatenated into prompt.
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
            The raw content of libraries/<llm_type>/<call_name>.md, or None if that file doesn't exist or is empty.
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
            Which provider to use - "claude", "codex", "deepseek", or "qwen".

        prompt (str):
            The prompt to send.

        persona (str | None):
            Optional persona/agent-context content for this call, typically the result of a prior load_persona() call.

    Returns:
        str | None:
            The assistant's text reply, or None if llm_type/its access type is invalid, or the call failed.
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
    """
    reply = await query_llm(llm_type, f"Hello - this is a startup connectivity test for {llm_type}. Reply with a short acknowledgement.")
    if reply is not None:
        logger.info(f"{llm_type} credential test response: {reply}")

def test_llm_tokens() -> None:
    """
    Runs a one-off startup smoke test for every LLM provider that has a credential configured.

    Args:
        None

    Returns:
        None

    Notes:
        - A provider with no credential configured is skipped, not treated as a misconfiguration.
    """
    for llm_type in _KNOWN_LLM_TYPES:
        _, _, token = _resolve_provider(llm_type)
        if not token:
            logger.info(f"No credential configured for llm_type={llm_type!r} - skipping its startup LLM credential test.")
            continue
        else:
            asyncio.run(_send_llm_test_prompt(llm_type))

# =============================================================================
