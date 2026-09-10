# =============================================================================
# File        : deepseek_interface.py
# Description : Interfaces with DeepSeek via its OpenAI-compatible chat completions API.
# Author      : SorinoSSK
# Created On  : 2026-09-10
#
# Features    :
#   - query_via_api()   - sends a prompt to DeepSeek, authenticated via a DeepSeek API key.
#   - query_via_oauth() - not supported; always logs and returns None (see Notes).
#
# Notes       :
#   - DeepSeek is API-key-only - it has no OAuth flow and no official CLI.
#   - No DeepSeek Python SDK exists, so this calls its OpenAI-compatible REST endpoint directly via stdlib urllib, wrapped in asyncio.to_thread().
#   - persona is delivered as its own leading "system" role message, not concatenated into prompt.
#   - See agent_interface.py for the provider-agnostic dispatch that selects this module.
#
# =============================================================================
# I M P O R T   H E A D E R

import json
import asyncio
import logging
import urllib.error
import urllib.request

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_API_URL = "https://api.deepseek.com/chat/completions"
_MODEL = "deepseek-chat"
_REQUEST_TIMEOUT_SECONDS = 60

# =============================================================================

def _post_chat_completion(prompt: str, token: str, persona: str | None = None) -> str | None:
    """
    Posts a single chat completion request to the DeepSeek API and returns the reply text.

    Args:
        prompt (str):
            The prompt to send.

        token (str):
            The DeepSeek API key.

        persona (str | None):
            Optional persona/system prompt for this call.

    Returns:
        str | None:
            The assistant's reply text, or None if the request failed or returned no content.

    Notes:
        - Synchronous/blocking - only ever called via asyncio.to_thread().
    """
    messages = []
    if persona:
        messages.append({"role": "system", "content": persona})
    messages.append({"role": "user", "content": prompt})

    body = json.dumps({
        "model": _MODEL,
        "messages": messages,
        "stream": False
    }).encode("utf-8")

    request = urllib.request.Request(
        _API_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
    )

    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"] or None
    except urllib.error.HTTPError as error:
        logger.error(f"DeepSeek API returned HTTP {error.code}: {error.read().decode(errors='replace').strip()}")
        return None
    except Exception:
        logger.exception("DeepSeek query failed - credential may be invalid/expired, the response was malformed, or the endpoint is unreachable.")
        return None

async def query_via_api(prompt: str, token: str, persona: str | None = None) -> str | None:
    """
    Sends a prompt to DeepSeek, authenticated via a DeepSeek API key.

    Args:
        prompt (str):
            The prompt to send.

        token (str):
            The DeepSeek API key.

        persona (str | None):
            Optional persona/system prompt for this call.

    Returns:
        str | None:
            The assistant's text reply, or None on failure.

    Notes:
        - Runs the blocking HTTP call in a worker thread so it doesn't stall the event loop.
    """
    return await asyncio.to_thread(_post_chat_completion, prompt, token, persona)

async def query_via_oauth(prompt: str, token: str, persona: str | None = None) -> str | None:
    """
    Not supported - DeepSeek has no OAuth/CLI login mechanism.

    Args:
        prompt (str):
            Unused - accepted only to match this module's expected two-endpoint shape.

        token (str):
            Unused, same reason.

        persona (str | None):
            Unused, same reason.

    Returns:
        str | None:
            Always None.
    """
    logger.warning("LLM_DEEPSEEK_ACCESS_TYPE=\"OAUTH\" is not supported - DeepSeek is API-key-only. Set LLM_DEEPSEEK_ACCESS_TYPE=\"API\" instead.")
    return None

# =============================================================================
