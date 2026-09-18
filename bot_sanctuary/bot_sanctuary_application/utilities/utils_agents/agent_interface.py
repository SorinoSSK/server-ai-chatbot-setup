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
#   - initialise_llm_services()/terminate_llm_services() - provider-agnostic lifecycle for whichever LLM providers have their own always-on service to start/stop (today, only Claude's claude_session_service.py, via claude_interface.py's own initialise_claude()/terminate_claude()).
#   - terminate_session(session_dir) - provider-agnostic teardown of a live, in-memory LLM session anchored to a specific session_dir, for whichever providers have such a concept (today, only Claude, via claude_interface.py's own terminate_session()).
#
# Notes       :
#   - More than one provider can be configured and used at once - callers pass llm_type explicitly.
#   - Add a matching <provider>_interface.py and a branch in _resolve_provider() to support a further provider.
#   - Provider identifiers (settings.LLM_TYPE_CLAUDE/CODEX/DEEPSEEK/QWEN, settings.KNOWN_LLM_TYPES) and the
#     shared libraries/ filesystem root (settings.LIBRARIES_DIR) live in config.py, not as module constants
#     here - every interface module references the same instances rather than each typing its own copy.
#   - persona is passed through to the resolved provider's own native mechanism, never concatenated into prompt.
#   - Claude is called with no token argument, since its credential is resolved once at startup rather than per call - see claude_interface.py.
#   - initialise_llm_services()/terminate_llm_services() are provider-agnostic - each delegates to whichever provider module exposes its own initialise_<provider>()/terminate_<provider>() pair.
#   - See README.md for the full provider dispatch and credential-handling design rationale.
#
# =============================================================================
# I M P O R T   H E A D E R

import asyncio
import logging
from pathlib import Path

from ...config import settings
from .interfaces import claude_interface
from .interfaces import codex_interface
from .interfaces import deepseek_interface
from .interfaces import qwen_interface

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# =============================================================================

def _resolve_provider(llm_type: str) -> tuple[object, str, str] | None:
    """
    Resolves an llm_type string to its interface module and configured credential.

    Args:
        llm_type (str):
            Which provider to resolve - one of settings.KNOWN_LLM_TYPES.

    Returns:
        tuple[object, str, str] | None:
            (provider module, access_type, token) for a recognised llm_type; otherwise None.
    """
    if llm_type == settings.LLM_TYPE_CLAUDE:
        return claude_interface, settings.LLM_CLAUDE_ACCESS_TYPE, settings.LLM_CLAUDE_TOKEN
    elif llm_type == settings.LLM_TYPE_CODEX:
        return codex_interface, settings.LLM_CODEX_ACCESS_TYPE, settings.LLM_CODEX_TOKEN
    elif llm_type == settings.LLM_TYPE_DEEPSEEK:
        return deepseek_interface, settings.LLM_DEEPSEEK_ACCESS_TYPE, settings.LLM_DEEPSEEK_TOKEN
    elif llm_type == settings.LLM_TYPE_QWEN:
        return qwen_interface, settings.LLM_QWEN_ACCESS_TYPE, settings.LLM_QWEN_TOKEN
    else:
        return None

def load_persona(llm_type: str, call_name: str) -> str | None:
    """
    Loads the persona/agent-context content optimised for the given provider and Call, if one has been written.

    Args:
        llm_type (str):
            Which provider's variant to load - one of settings.KNOWN_LLM_TYPES.

        call_name (str):
            Which Call's persona to load - matches that Call's own CALL_NAME (e.g. "chat").

    Returns:
        str | None:
            The raw content of libraries/<llm_type>/<call_name>.md, or None if that file doesn't exist or is empty.
    """
    library_file = settings.LIBRARIES_DIR / llm_type / f"{call_name}.md"
    if not library_file.is_file():
        return None
    else:
        content = library_file.read_text(encoding="utf-8").strip()
        return content or None

async def query_llm(llm_type: str, prompt: str, persona: str | None = None, session_dir: Path | None = None) -> str | None:
    """
    Sends a prompt to the given LLM provider, via that provider's own configured access method/credential.

    Args:
        llm_type (str):
            Which provider to use - one of settings.KNOWN_LLM_TYPES.

        prompt (str):
            The prompt to send.

        persona (str | None):
            Optional persona/agent-context content for this call, typically the result of a prior load_persona() call.

        session_dir (Path | None):
            Optional working-directory anchor for this call. claude_interface.py/codex_interface.py/
            qwen_interface.py each use it for their own session-continuity mechanism; deepseek_interface.py uses
            it to key its own local transcript file.

    Returns:
        str | None:
            The assistant's text reply, or None if llm_type/its access type is invalid, or the call failed.

    Notes:
        - Claude is called with no token argument, since its credential is resolved once at startup rather than per call - see claude_interface.py.
    """
    resolved = _resolve_provider(llm_type)
    if resolved is None:
        logger.warning(f"llm_type={llm_type!r} is not a supported provider - skipping query.")
        return None
    else:
        provider, access_type, token = resolved
        access_type = access_type.upper()
        if access_type == "OAUTH":
            if llm_type == settings.LLM_TYPE_CLAUDE:
                return await provider.query_via_oauth(prompt, persona, session_dir)
            else:
                return await provider.query_via_oauth(prompt, token, persona, session_dir)
        elif access_type == "API":
            if llm_type == settings.LLM_TYPE_CLAUDE:
                return await provider.query_via_api(prompt, persona, session_dir)
            else:
                return await provider.query_via_api(prompt, token, persona, session_dir)
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
    for llm_type in settings.KNOWN_LLM_TYPES:
        _, _, token = _resolve_provider(llm_type)
        if not token:
            logger.info(f"No credential configured for llm_type={llm_type!r} - skipping its startup LLM credential test.")
            continue
        else:
            asyncio.run(_send_llm_test_prompt(llm_type))

def initialise_llm_services() -> None:
    """
    Starts every LLM provider's own always-on service, for whichever providers have one.

    Args:
        None

    Returns:
        None

    Notes:
        - Provider-agnostic - delegates to whichever provider module exposes its own initialise_<provider>().
        - Today, only Claude has an always-on service (claude_session_service.py), gated on OAuth access.
        - Safe to call unconditionally at startup, regardless of which providers are actually configured.
    """
    claude_interface.initialise_claude()

def terminate_llm_services() -> None:
    """
    Stops every LLM provider's own always-on service that was started.

    Args:
        None

    Returns:
        None

    Notes:
        - Provider-agnostic - delegates to whichever provider module exposes its own terminate_<provider>().
        - Safe to call unconditionally, even if no provider's service was ever started.
    """
    claude_interface.terminate_claude()

def terminate_session(session_dir: Path) -> None:
    """
    Terminates any live, in-memory LLM session anchored to session_dir, for providers that have one.

    Args:
        session_dir (Path):
            The Call/LLM-scoped leaf directory, or a session root covering several such leaves, whose live session(s), if any, should be torn down.

    Returns:
        None

    Notes:
        - Provider-agnostic - delegates to whichever provider module exposes its own terminate_session().
        - Today, only Claude has a persistent-session concept to terminate.
    """
    claude_interface.terminate_session(session_dir)

# =============================================================================
