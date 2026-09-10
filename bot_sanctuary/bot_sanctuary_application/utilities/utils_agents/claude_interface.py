# =============================================================================
# File        : claude_interface.py
# Description : Interfaces with Claude via the Claude Agent SDK, supporting both OAuth and API key credentials.
# Author      : SorinoSSK
# Created On  : 2026-09-10
#
# Features    :
#   - query_via_oauth() - sends a prompt to Claude, authenticated via a Claude Code OAuth token.
#   - query_via_api()   - sends a prompt to Claude, authenticated via an Anthropic API key.
#
# Notes       :
#   - Both endpoints share the same claude_agent_sdk.query() call - only the bridged credential env var differs.
#   - persona is parsed for an optional YAML frontmatter block (tools/model) plus a system prompt body, wired into ClaudeAgentOptions.
#   - See agent_interface.py for the provider-agnostic dispatch that selects this module.
#
# =============================================================================
# I M P O R T   H E A D E R

import os
import re
import logging

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query as claude_query

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_FRONTMATTER_DELIMITER = "---"
_FRONTMATTER_LINE_PATTERN = re.compile(r"^(name|description|tools|model):\s*(.*)$")

# =============================================================================

def _parse_persona(persona: str) -> tuple[str, list[str] | None, str | None]:
    """
    Splits persona content into its Claude-specific frontmatter (tools/model) and body system prompt.

    Args:
        persona (str):
            Raw persona content - an optional leading "---" frontmatter block followed by the system prompt body.

    Returns:
        tuple[str, list[str] | None, str | None]:
            (body, tools, model) - frontmatter stripped from body; tools/model are None if absent.
    """
    lines = persona.splitlines()
    tools = None
    model = None
    body_lines = lines

    has_frontmatter = bool(lines) and lines[0].strip() == _FRONTMATTER_DELIMITER
    if has_frontmatter:
        closing_index = None
        for index in range(1, len(lines)):
            if lines[index].strip() == _FRONTMATTER_DELIMITER:
                closing_index = index
                break

        if closing_index is not None:
            for line in lines[1:closing_index]:
                match = _FRONTMATTER_LINE_PATTERN.match(line.strip())
                if match is not None:
                    key, value = match.group(1), match.group(2).strip()
                    if key == "tools":
                        tools = [tool.strip() for tool in value.split(",") if tool.strip()]
                    elif key == "model":
                        model = value or None
            body_lines = lines[closing_index + 1:]

    body = "\n".join(body_lines).strip()
    return body, tools, model

async def _run_query(prompt: str, persona: str | None = None) -> str | None:
    """
    Runs a single prompt through the Claude Agent SDK and collects the assistant's text reply.

    Args:
        prompt (str):
            The prompt to send.

        persona (str | None):
            Optional persona/system prompt for this call, parsed via _parse_persona().

    Returns:
        str | None:
            The assistant's concatenated text reply, or None if no text block was returned or the call failed.

    Notes:
        - Credential resolution is env-var driven - callers set the relevant env var before calling this.
    """
    options = None
    if persona:
        body, tools, model = _parse_persona(persona)
        options = ClaudeAgentOptions(system_prompt=body, tools=tools, model=model)

    reply_parts = []
    try:
        async for message in claude_query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        reply_parts.append(block.text)
    except Exception:
        logger.exception("Claude query failed - credential may be invalid/expired, or the endpoint is unreachable.")
        return None

    return "".join(reply_parts) or None

async def query_via_oauth(prompt: str, token: str, persona: str | None = None) -> str | None:
    """
    Sends a prompt to Claude, authenticated via a Claude Code OAuth token.

    Args:
        prompt (str):
            The prompt to send.

        token (str):
            The Claude Code OAuth token.

        persona (str | None):
            Optional persona/system prompt for this call.

    Returns:
        str | None:
            The assistant's text reply, or None on failure.

    Notes:
        - Bridges token into CLAUDE_CODE_OAUTH_TOKEN.
    """
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return await _run_query(prompt, persona)

async def query_via_api(prompt: str, token: str, persona: str | None = None) -> str | None:
    """
    Sends a prompt to Claude, authenticated via an Anthropic API key.

    Args:
        prompt (str):
            The prompt to send.

        token (str):
            The Anthropic API key.

        persona (str | None):
            Optional persona/system prompt for this call.

    Returns:
        str | None:
            The assistant's text reply, or None on failure.

    Notes:
        - Bridges token into ANTHROPIC_API_KEY.
    """
    os.environ["ANTHROPIC_API_KEY"] = token
    return await _run_query(prompt, persona)

# =============================================================================
