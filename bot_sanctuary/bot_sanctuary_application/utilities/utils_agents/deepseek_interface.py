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
#   - Unlike claude_interface.py/codex_interface.py, DeepSeek is API-key-only - the official DeepSeek API
#     has never offered an OAuth flow, and there is no official DeepSeek CLI to log in with at all (see
#     bot_sanctuary/CODE_TODO.md §1/§2). query_via_oauth() exists purely so this module still matches the
#     two-endpoint shape agent_interface.py::query_llm() dispatches against, uniformly, without a
#     per-provider capability check - it is never expected to be reached in a correctly-configured
#     deployment (config.py's LLM_DEEPSEEK_ACCESS_TYPE should be "API" - the default already).
#   - No DeepSeek Python SDK dependency is installed - the DeepSeek API is OpenAI-compatible, so this
#     calls its REST endpoint directly via the stdlib (urllib.request, wrapped in asyncio.to_thread() so
#     the blocking call doesn't stall the event loop), rather than adding a new pip dependency for one
#     HTTP call shape.
#   - The credential is passed in by the caller (token, below) rather than read from settings directly -
#     agent_interface.py resolves it from config.py's LLM_DEEPSEEK_TOKEN before calling either endpoint,
#     so this module has no dependency on global config state and stays a pure function of its arguments.
#     Bridged into the standard "Authorization: Bearer <token>" header - never logged.
#   - Endpoint/model (_API_URL/_MODEL below) confirmed against DeepSeek's own API docs at the time this
#     was written - see bot_sanctuary/CODE_TODO.md §2 if either ever needs revisiting.
#   - persona (below) is delivered as its own {"role": "system", ...} message ahead of the user message -
#     the standard OpenAI-compatible convention this API already supports - rather than being concatenated
#     into prompt as plain text.
#   - See agent_interface.py for the provider-agnostic dispatch that selects between this module and any
#     other provider's own interface file, and bot_sanctuary/CODE_TODO.md for the wider multi-provider
#     design context.
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
            The DeepSeek API key (config.py's LLM_DEEPSEEK_TOKEN).

        persona (str | None):
            Optional persona/system prompt for this call, sent as its own leading "system" role message.

    Returns:
        str | None:
            The assistant's reply text, or None if the request failed or returned no content.

    Notes:
        - Synchronous/blocking (stdlib urllib) - only ever called via asyncio.to_thread(), never directly
          from an async context, so it never stalls the event loop.
        - Any failure (HTTP error, network error, unexpected response shape) is caught and logged rather
          than raised, matching claude_interface.py's/codex_interface.py's own "never crash the caller"
          convention.
    """
    messages = []
    if persona:
        messages.append({"role": "system", "content": persona})
    else:
        pass  # No persona for this call - a plain single-turn user message, same as this function's original behaviour.
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
            The DeepSeek API key (config.py's LLM_DEEPSEEK_TOKEN).

        persona (str | None):
            Optional persona/system prompt for this call - see _post_chat_completion()'s own Notes.

    Returns:
        str | None:
            The assistant's text reply, or None on failure.

    Notes:
        - Runs the blocking HTTP call in a worker thread (asyncio.to_thread()) so it doesn't stall the
          event loop other async work (e.g. claude_interface.py's own SDK call) may be running on.
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

    Notes:
        - Reaching this at all means LLM_DEEPSEEK_ACCESS_TYPE is configured as "OAUTH", which is a
          configuration mistake - "API" is the only access type DeepSeek actually supports.
    """
    logger.warning("LLM_DEEPSEEK_ACCESS_TYPE=\"OAUTH\" is not supported - DeepSeek is API-key-only. Set LLM_DEEPSEEK_ACCESS_TYPE=\"API\" instead.")
    return None

# =============================================================================
