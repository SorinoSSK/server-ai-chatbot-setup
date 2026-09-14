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
#
# Notes       :
#   - More than one provider can be configured and used at once - callers pass llm_type explicitly rather than reading a single global setting.
#   - Add a matching <provider>_interface.py and a branch in _resolve_provider() to support a further provider.
#   - persona is passed through to the resolved provider's own native mechanism, never concatenated into prompt.
#   - query_llm() special-cases llm_type == "claude" to omit the token argument (claude_interface.py's own
#     query_via_oauth()/query_via_api() no longer take one - see that module's own header Notes) - codex/
#     deepseek/qwen are still called with the original, uniform four-argument signature. This is the one
#     provider-specific branch in this otherwise provider-agnostic dispatch, added deliberately per explicit
#     instruction to remove that now-dead parameter from claude_interface.py itself.
#   - initialise_llm_services()/terminate_llm_services() are deliberately not Claude-specific, even though
#     Claude is the only provider with an always-on platform (claude_session_service.py) to start/stop today -
#     each simply delegates to whichever provider module(s) expose their own initialise_<provider>()/
#     terminate_<provider>() pair (today, only claude_interface.py does), rather than deciding any
#     provider-specific precondition/credential-bridging logic itself. A future provider's own equivalent
#     would add its own such pair to its own <provider>_interface.py and a further call here, rather than this
#     module growing new provider-specific branches of its own. Distinct from query_llm()'s own one-shot
#     <provider>_interface.py path, which needs no start/stop step at all for any provider.
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

async def query_llm(llm_type: str, prompt: str, persona: str | None = None, session_dir: Path | None = None) -> str | None:
    """
    Sends a prompt to the given LLM provider, via that provider's own configured access method/credential.

    Args:
        llm_type (str):
            Which provider to use - "claude", "codex", "deepseek", or "qwen".

        prompt (str):
            The prompt to send.

        persona (str | None):
            Optional persona/agent-context content for this call, typically the result of a prior load_persona() call.

        session_dir (Path | None):
            Optional working-directory anchor for this call, typically a SessionWorker's own session_dir. Passed
            through uniformly to every provider's query_via_oauth()/query_via_api(), same as persona - today only
            claude_interface.py actually uses it (session_dir + claude_session_service.py's own persistent
            platform, for Claude's own session_dir-keyed continuity); codex/deepseek/qwen accept and ignore it.

    Returns:
        str | None:
            The assistant's text reply, or None if llm_type/its access type is invalid, or the call failed.

    Notes:
        - claude_interface.py's own query_via_oauth()/query_via_api() take no token argument, unlike the other
          three providers - Claude's credential is resolved once at startup (claude_interface.py's own
          initialise_claude()), not per call, so there is nothing left for a per-call token to do (see that
          module's own header Notes). This function special-cases llm_type == "claude" below rather than
          calling all four providers with an identical signature, which is the one deliberate exception to
          this module's otherwise-uniform four-provider dispatch.
    """
    resolved = _resolve_provider(llm_type)
    if resolved is None:
        logger.warning(f"llm_type={llm_type!r} is not a supported provider - skipping query.")
        return None
    else:
        provider, access_type, token = resolved
        access_type = access_type.upper()
        if access_type == "OAUTH":
            if llm_type == "claude":
                return await provider.query_via_oauth(prompt, persona, session_dir)
            else:
                return await provider.query_via_oauth(prompt, token, persona, session_dir)
        elif access_type == "API":
            if llm_type == "claude":
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
    for llm_type in _KNOWN_LLM_TYPES:
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
        - Provider-agnostic entry point, per explicit instruction ("whatever agent_interface hold should be
          for all LLM") - this function itself decides nothing provider-specific; it only delegates to
          whichever provider module(s) expose their own initialise_<provider>() to call. A future provider's
          own always-on platform would add its own initialise_<provider>() to its own <provider>_interface.py
          and a further call here, rather than this module growing new provider-specific logic of its own.
        - Claude: delegates to claude_interface.initialise_claude(), which decides for itself whether Claude's
          own claude_session_service.py platform should actually start (gated on OAuth access - see that
          function's own docstring for the precondition/credential-bridging detail, both of which live in
          claude_interface.py, not here).
        - Codex/DeepSeek/Qwen have no equivalent always-on platform/initialise_<provider>() today - nothing
          further runs for them yet.
        - Safe to call unconditionally at startup regardless of LLM_CHAT_TYPE/LLM_ARCHITECT_TYPE/etc. - a
          provider mix that never actually names "claude" simply leaves Claude's own service
          started-but-unused (an idle background thread with an empty client registry), not a resource leak
          worth guarding against specially.
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
        - Provider-agnostic entry point, same rationale as initialise_llm_services() above - delegates to
          whichever provider module(s) expose their own terminate_<provider>(), rather than deciding anything
          provider-specific itself.
        - Claude: delegates to claude_interface.terminate_claude(). Safe to call unconditionally, even if
          initialise_llm_services() never actually started Claude's own service (configured for API access
          instead of OAuth, or not configured at all) - terminate_claude() is already its own no-op in that
          case.
        - Codex/DeepSeek/Qwen have no equivalent always-on platform/terminate_<provider>() today - nothing
          further runs for them yet.
    """
    claude_interface.terminate_claude()

# =============================================================================
