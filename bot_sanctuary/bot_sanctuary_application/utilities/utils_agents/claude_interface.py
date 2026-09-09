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
#   - Both endpoints share the same underlying claude_agent_sdk.query() call - the SDK/CLI itself resolves
#     credentials from whichever environment variable is set (CLAUDE_CODE_OAUTH_TOKEN vs ANTHROPIC_API_KEY),
#     so no separate client/transport is needed per access type - only the credential env var bridged
#     ahead of the call differs.
#   - The credential is passed in by the caller (token, below) rather than read from settings directly -
#     agent_interface.py resolves it from config.py's LLM_CLAUDE_TOKEN before calling either endpoint, so
#     this module has no dependency on global config state and stays a pure function of its arguments.
#   - persona (below) is loaded from bot_sanctuary_application/libraries/claude/<call_name>.md (via
#     agent_interface.py::load_persona()) and is expected to carry a Claude-specific leading YAML
#     frontmatter block - "---" / name:/description:/tools:/model: lines / "---" - the same shape Claude
#     Code's own subagent files use, followed by the actual system prompt body in Markdown. _parse_persona()
#     below splits that apart, and the pieces are wired into real ClaudeAgentOptions fields
#     (system_prompt/tools/model), rather than sent as one opaque block of text where "tools:"/"model:"
#     would just be inert prose the model reads but can't act on structurally.
#   - This is deliberately the plain system_prompt option (plus top-level tools/model), not the SDK's
#     separate agents={name: AgentDefinition(...)} subagent mechanism: subagents are for on-demand
#     specialised helpers a conversation can delegate to mid-turn, whereas a Call's persona is meant to be
#     in effect for the entire call - system_prompt is the direct match for that, and (along with the rest
#     of the call) is also what benefits from Anthropic's own prompt caching across repeated calls with the
#     same persona, unlike text baked into prompt.
#   - "name:"/"description:" are recognised and stripped out of the body during parsing, but neither maps
#     to a ClaudeAgentOptions field today - they exist in the source file purely as authoring metadata
#     (matching the subagent-file convention persona.md was originally written in).
#   - See agent_interface.py for the provider-agnostic dispatch that selects between this module and any
#     other provider's own interface file, and bot_sanctuary/CODE_TODO.md for the wider multi-provider
#     design context.
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
            Raw persona content as loaded from libraries/claude/<call_name>.md - an optional leading YAML
            frontmatter block ("---" / name:/description:/tools:/model: lines, any subset, in any order /
            "---") followed by the actual system prompt body.

    Returns:
        tuple[str, list[str] | None, str | None]:
            (body, tools, model) - body is the persona with any frontmatter block stripped; tools is a
            comma-separated "tools:" value split into a list, or None if absent/no frontmatter; model is
            the "model:" value, or None if absent/no frontmatter. "name:"/"description:" are recognised
            only so they're excluded from body - neither maps to a ClaudeAgentOptions field today.
        - A malformed frontmatter block (an opening "---" with no matching closing one) is treated as no
          frontmatter at all - the whole content becomes body - rather than guessing where it should end.
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
            else:
                pass  # Still inside the frontmatter block - keep scanning for the closing delimiter.

        if closing_index is None:
            pass  # Opening "---" with no matching closing one - malformed, leave body_lines as the whole content.
        else:
            for line in lines[1:closing_index]:
                match = _FRONTMATTER_LINE_PATTERN.match(line.strip())
                if match is None:
                    pass  # Blank line or unrecognised field inside the frontmatter block - skip it.
                else:
                    key, value = match.group(1), match.group(2).strip()
                    if key == "tools":
                        tools = [tool.strip() for tool in value.split(",") if tool.strip()]
                    elif key == "model":
                        model = value or None
                    else:
                        pass  # "name"/"description" - recognised frontmatter, but neither maps to a ClaudeAgentOptions field today.
            body_lines = lines[closing_index + 1:]
    else:
        pass  # No frontmatter block - the whole content is the body as-is.

    body = "\n".join(body_lines).strip()
    return body, tools, model

async def _run_query(prompt: str, persona: str | None = None) -> str | None:
    """
    Runs a single prompt through the Claude Agent SDK and collects the assistant's text reply.

    Args:
        prompt (str):
            The prompt to send.

        persona (str | None):
            Optional persona/agent-context content for this call, in libraries/claude/<call_name>.md's own
            frontmatter+body shape. Parsed by _parse_persona() and passed to the SDK as
            ClaudeAgentOptions(system_prompt=..., tools=..., model=...) rather than being folded into
            prompt.

    Returns:
        str | None:
            The assistant's concatenated text reply, or None if no text block was returned or the call failed.

    Notes:
        - Credential resolution (OAuth token vs API key) is entirely env-var driven - callers set the
          relevant env var before calling this, see query_via_oauth()/query_via_api() below.
        - Any failure is caught and logged rather than raised, matching this application's existing
          convention of never letting an LLM call crash its caller (see utilities/initialise.py).
    """
    options = None
    if persona:
        body, tools, model = _parse_persona(persona)
        options = ClaudeAgentOptions(system_prompt=body, tools=tools, model=model)
    else:
        pass  # No persona for this call - query with no options override, matching this function's original (pre-persona) behaviour.

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
            The Claude Code OAuth token (config.py's LLM_CLAUDE_TOKEN).

        persona (str | None):
            Optional persona/system prompt for this call - see _run_query()'s own Notes.

    Returns:
        str | None:
            The assistant's text reply, or None on failure.

    Notes:
        - Bridges token into CLAUDE_CODE_OAUTH_TOKEN, the environment variable the Claude Agent SDK/CLI
          itself reads for a subscription-based OAuth session.
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
            The Anthropic API key (config.py's LLM_CLAUDE_TOKEN).

        persona (str | None):
            Optional persona/system prompt for this call - see _run_query()'s own Notes.

    Returns:
        str | None:
            The assistant's text reply, or None on failure.

    Notes:
        - Bridges token into ANTHROPIC_API_KEY, the environment variable the Claude Agent SDK/CLI itself
          reads for direct, per-call API billing (bypassing an OAuth/subscription session).
    """
    os.environ["ANTHROPIC_API_KEY"] = token
    return await _run_query(prompt, persona)

# =============================================================================
