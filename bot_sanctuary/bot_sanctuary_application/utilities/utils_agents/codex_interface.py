# =============================================================================
# File        : codex_interface.py
# Description : Interfaces with Codex (OpenAI) via the codex CLI, supporting both OAuth and API key credentials.
# Author      : SorinoSSK
# Created On  : 2026-09-10
#
# Features    :
#   - query_via_oauth() - sends a prompt to Codex, authenticated via the CLI's existing ChatGPT/OAuth login session.
#   - query_via_api()   - sends a prompt to Codex, authenticated via an OpenAI API key.
#
# Notes       :
#   - Mirrors claude_interface.py's two-endpoint shape, but there is no OpenAI/Codex Python SDK dependency
#     installed (see bot_sanctuary/CODE_TODO.md §1) - both endpoints instead shell out to the `codex` CLI
#     already installed in the image (see Dockerfile), via `codex exec <prompt>` (codex's own documented
#     non-interactive scripting mode - streams progress to stderr, prints only the final agent message to
#     stdout, so stdout alone is the reply).
#   - The credential is passed in by the caller (token, below) rather than read from settings directly -
#     agent_interface.py resolves it from config.py's LLM_CODEX_TOKEN before calling either endpoint, so
#     this module has no dependency on global config state and stays a pure function of its arguments.
#     query_via_oauth() deliberately never touches token at all, relying entirely on whatever session
#     `codex login` already persisted to the bind-mounted `bot_directory/codex` (~/.codex/auth.json) -
#     same credential the OAuth login flow documented in bot_sanctuary/CODE_TODO.md §1/§2 already sets up,
#     just now actually invoked by the application.
#   - persona (below) is delivered via an AGENTS.md file - codex's own, pre-existing convention for
#     persistent instructions, read automatically at session start rather than needing to be typed into
#     every prompt (see https://developers.openai.com/codex/cli/reference /
#     https://learn.chatgpt.com/docs/agent-configuration/agents-md). Rather than writing to a single shared
#     path (e.g. ~/.codex/AGENTS.md, which would race if two concurrent calls used different personas),
#     each call that has a persona gets its own throwaway working directory containing just that call's
#     AGENTS.md, and `codex exec` is run with cwd set to it - scoping the persona to that one call only,
#     with no shared mutable state between calls. The directory is removed again once the call finishes.
#   - See agent_interface.py for the provider-agnostic dispatch that selects between this module and any
#     other provider's own interface file, and bot_sanctuary/CODE_TODO.md for the wider multi-provider
#     design context.
#
# =============================================================================
# I M P O R T   H E A D E R

import os
import shutil
import asyncio
import logging
import tempfile
from pathlib import Path

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_CODEX_BINARY = "codex"
_AGENTS_FILE_NAME = "AGENTS.md"

# =============================================================================

async def _run_query(prompt: str, env: dict[str, str], persona: str | None = None) -> str | None:
    """
    Runs a single prompt through `codex exec` and returns its final agent message.

    Args:
        prompt (str):
            The prompt to send.

        env (dict[str, str]):
            Environment the subprocess is run with - controls which credential (if any) codex picks up.

        persona (str | None):
            Optional persona/system prompt for this call. Written to a per-call AGENTS.md in a throwaway
            working directory - see module Notes above for why.

    Returns:
        str | None:
            The assistant's text reply (codex exec's final stdout message), or None if the call failed or
            produced no output.

    Notes:
        - Any failure (non-zero exit code, missing binary, etc.) is caught and logged rather than raised,
          matching claude_interface.py's own "never crash the caller" convention.
    """
    call_directory = None
    if persona:
        call_directory = tempfile.mkdtemp(prefix="codex_call_")
        (Path(call_directory) / _AGENTS_FILE_NAME).write_text(persona, encoding="utf-8")
    else:
        pass  # No persona for this call - codex exec runs with no cwd override, picking up whatever AGENTS.md (if any) already applies at its default working directory.

    try:
        process = await asyncio.create_subprocess_exec(
            _CODEX_BINARY, "exec", prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=call_directory
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.error(f"codex exec exited with code {process.returncode}: {stderr.decode(errors='replace').strip()}")
            return None
        else:
            reply = stdout.decode(errors="replace").strip()
            return reply or None
    except Exception:
        logger.exception("Codex query failed - credential may be invalid/expired, the codex CLI may be missing, or the endpoint is unreachable.")
        return None
    finally:
        if call_directory is not None:
            shutil.rmtree(call_directory, ignore_errors=True)
        else:
            pass  # No per-call directory was created - nothing to clean up.

async def query_via_oauth(prompt: str, token: str, persona: str | None = None) -> str | None:
    """
    Sends a prompt to Codex, authenticated via the CLI's existing ChatGPT/OAuth login session.

    Args:
        prompt (str):
            The prompt to send.

        token (str):
            Unused - accepted only for a uniform call signature across every provider's query_via_oauth().
            Codex's OAuth path relies entirely on the CLI's own persisted login session, not a token value.

        persona (str | None):
            Optional persona/system prompt for this call - see _run_query()'s own Notes.

    Returns:
        str | None:
            The assistant's text reply, or None on failure.

    Notes:
        - Runs with OPENAI_API_KEY deliberately absent from the subprocess environment - codex CLI falls
          back to whatever session `codex login` already persisted (~/.codex/auth.json) whenever no API
          key is present.
    """
    env = {key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"}
    return await _run_query(prompt, env, persona)

async def query_via_api(prompt: str, token: str, persona: str | None = None) -> str | None:
    """
    Sends a prompt to Codex, authenticated via an OpenAI API key.

    Args:
        prompt (str):
            The prompt to send.

        token (str):
            The OpenAI API key (config.py's LLM_CODEX_TOKEN).

        persona (str | None):
            Optional persona/system prompt for this call - see _run_query()'s own Notes.

    Returns:
        str | None:
            The assistant's text reply, or None on failure.

    Notes:
        - Bridges token into OPENAI_API_KEY for this subprocess only - codex CLI uses an API key over any
          existing logged-in session whenever OPENAI_API_KEY is present.
    """
    env = {**os.environ, "OPENAI_API_KEY": token}
    return await _run_query(prompt, env, persona)

# =============================================================================
