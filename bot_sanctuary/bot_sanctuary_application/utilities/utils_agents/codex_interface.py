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
#   - No Codex Python SDK exists, so both endpoints shell out to the installed `codex` CLI via `codex exec`.
#   - persona is delivered via a per-call, throwaway AGENTS.md working directory, removed once the call finishes.
#   - See agent_interface.py for the provider-agnostic dispatch that selects this module.
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
            Optional persona/system prompt for this call, written to a per-call AGENTS.md.

    Returns:
        str | None:
            The assistant's text reply, or None if the call failed or produced no output.
    """
    call_directory = None
    if persona:
        call_directory = tempfile.mkdtemp(prefix="codex_call_")
        (Path(call_directory) / _AGENTS_FILE_NAME).write_text(persona, encoding="utf-8")

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

async def query_via_oauth(prompt: str, token: str, persona: str | None = None) -> str | None:
    """
    Sends a prompt to Codex, authenticated via the CLI's existing ChatGPT/OAuth login session.

    Args:
        prompt (str):
            The prompt to send.

        token (str):
            Unused - Codex's OAuth path relies entirely on the CLI's own persisted login session.

        persona (str | None):
            Optional persona/system prompt for this call.

    Returns:
        str | None:
            The assistant's text reply, or None on failure.

    Notes:
        - Runs with OPENAI_API_KEY absent from the subprocess environment, so codex CLI falls back to its persisted login session.
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
            The OpenAI API key.

        persona (str | None):
            Optional persona/system prompt for this call.

    Returns:
        str | None:
            The assistant's text reply, or None on failure.

    Notes:
        - Bridges token into OPENAI_API_KEY for this subprocess only.
    """
    env = {**os.environ, "OPENAI_API_KEY": token}
    return await _run_query(prompt, env, persona)

# =============================================================================
