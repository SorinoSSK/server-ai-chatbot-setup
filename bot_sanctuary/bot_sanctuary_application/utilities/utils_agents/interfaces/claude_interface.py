# =============================================================================
# File        : claude_interface.py
# Description : Interfaces with Claude via the Claude Agent SDK, supporting both OAuth and API key credentials.
# Author      : SorinoSSK
# Created On  : 2026-09-10
#
# Features    :
#   - query_via_oauth() - sends a prompt to Claude via an OAuth token, routing through the persistent session platform whenever a session_dir is given.
#   - query_via_api() - sends a prompt to Claude via an Anthropic API key, always one-shot.
#   - initialise_claude()/terminate_claude() - starts/stops claude_session_service.py's persistent Claude session platform.
#   - terminate_session(session_dir) - tears down every live, in-memory Claude client anchored anywhere under session_dir.
#
# Notes       :
#   - Claude's credential is resolved once at startup by initialise_claude(), not per call.
#   - query_via_oauth()/query_via_api() take no token argument, unlike every other provider's own equivalent.
#   - persona/tools/model are resolved internally by _run_query() itself, via agent_persona.parse_agent(),
#     derived from session_dir - not passed in from any caller. See _run_query()'s own Notes.
#   - Session continuity uses an explicit resume=<session_id> marker file, since continue_conversation was found empirically unreliable across separate calls.
#   - _run_query() is bounded by settings.AGENT_QUERY_TIMEOUT_SECONDS, deliberately mirroring
#     claude_session_service.py::query_via_service()'s own timeout handling exactly (same constant, same
#     discard-on-timeout, same bare None return) - added 2026-09-19, per explicit instruction that the API
#     path should behave the same as the OAuth path, not differently from it.
#   - See agent_interface.py for the provider-agnostic dispatch that selects this module.
#   - See README.md for the full credential-resolution and session-continuity design rationale.
#
# =============================================================================
# I M P O R T   H E A D E R

import os
import asyncio
import logging

from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, ToolResultBlock, ToolUseBlock, query as claude_query

from ....config import settings
from ..agent_persona import call_name_from_session_dir, parse_agent
from ..services.claude_session_service import destroy_sessions_under, query_via_service, start_claude_session_service, stop_claude_session_service

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# Marker file this module reads/writes inside a given session_dir to remember Claude's own session_id across
# separate _run_query() calls - see _read_resume_id()/_write_resume_id(). Colocated with session_dir
# deliberately, not tracked anywhere else, so clear_session_directory()'s existing whole-tree removal
# (utils_session/session_worker.py) already clears it for free on a session_cleared/global reset - no extra
# clearing logic needed for this file.
_SESSION_ID_MARKER_FILENAME = ".claude_session_id"

# =============================================================================

def _read_resume_id(session_dir: Path | None) -> str | None:
    """
    Reads session_dir's own remembered Claude session_id, if a prior successful call in this generation left one.

    Args:
        session_dir (Path | None):
            The working-directory anchor to check. None if this call has no session_dir at all.

    Returns:
        str | None:
            The remembered session_id, or None if unavailable.

    Notes:
        - Never raises - a missing/unreadable marker file is treated as nothing to resume from.
    """
    if session_dir is None:
        return None
    else:
        marker = session_dir / _SESSION_ID_MARKER_FILENAME
        try:
            return marker.read_text(encoding="utf-8").strip() or None
        except FileNotFoundError:
            return None
        except OSError:
            logger.exception(f"Failed to read Claude session_id marker at session_dir={session_dir} - starting a fresh session instead of resuming.")
            return None

def _write_resume_id(session_dir: Path | None, session_id: str | None) -> None:
    """
    Remembers session_id as session_dir's own latest Claude session, for a future call to resume from.

    Args:
        session_dir (Path | None):
            The working-directory anchor to write into. A no-op if None.

        session_id (str | None):
            The session_id captured from this call's own ResultMessage. A no-op if None/empty.

    Returns:
        None

    Notes:
        - Only called after a confirmed-successful call, so a failed call leaves the prior session_id in place.
        - Best-effort - a write failure is logged but non-fatal.
    """
    if session_dir is None or not session_id:
        return
    else:
        try:
            (session_dir / _SESSION_ID_MARKER_FILENAME).write_text(session_id, encoding="utf-8")
        except OSError:
            logger.exception(f"Failed to persist Claude session_id for session_dir={session_dir} - the next call in this generation will start a fresh session instead of resuming.")

def _find_transcript(session_id: str) -> Path | None:
    """
    Searches ~/.claude/projects/ for session_id's own transcript file.

    Diagnostic only - used to confirm whether a resumed session_id genuinely exists on disk.

    Args:
        session_id (str):
            The Claude session_id to look for.

    Returns:
        Path | None:
            The matching <session_id>.jsonl file, if found; otherwise None.

    Notes:
        - Never raises - a missing/inaccessible directory is treated the same as "not found".
    """
    projects_root = Path("~/.claude/projects").expanduser()
    if not projects_root.is_dir():
        return None
    else:
        try:
            return next(projects_root.rglob(f"{session_id}.jsonl"), None)
        except OSError:
            logger.exception(f"Failed to search ~/.claude/projects/ for session_id={session_id}'s transcript - diagnostic lookup only, not fatal.")
            return None

async def _collect_claude_response(prompt: str, options: ClaudeAgentOptions | None, session_dir: Path | None) -> tuple[list[str], str | None]:
    """
    Consumes claude_query()'s own message stream to completion, collecting it into one final reply.

    Args:
        prompt (str):
            The prompt to send.

        options (ClaudeAgentOptions | None):
            The already-resolved options (persona/tools/model/session continuity) to query with.

        session_dir (Path | None):
            This call's own working-directory anchor - used only for log-message context here, not logic.

    Returns:
        tuple[list[str], str | None]:
            The assistant's own text fragments (one per TextBlock, in arrival order), and the session_id
            captured from this call's own ResultMessage (None if none arrived).

    Notes:
        - Module-level, not nested inside _run_query() - factored out solely so its own async for loop can be
          bounded by asyncio.wait_for() at that call site, which cannot wrap an async for statement directly.
        - Collects rather than streams: nothing here is yielded progressively to a caller - the full message
          stream is consumed internally and returned as one aggregate result once exhausted.
        - ToolUseBlock/ToolResultBlock content is logged for diagnostic purposes only.
    """
    parts: list[str] = []
    session_id: str | None = None
    async for message in claude_query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    parts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    logger.info(f"Claude tool_use: name={block.name!r} input={block.input} session_dir={session_dir}")
                elif isinstance(block, ToolResultBlock):
                    logger.info(f"Claude tool_result: tool_use_id={block.tool_use_id} is_error={block.is_error} content={block.content} session_dir={session_dir}")
        elif isinstance(message, ResultMessage):
            session_id = message.session_id
            # Diagnostic logging, kept from the continue_conversation investigation - still useful to
            # directly verify resume= is now actually working (session_id staying stable, num_turns
            # climbing across successive calls at the same session_dir) rather than trusting it silently.
            logger.info(f"Claude ResultMessage: session_id={message.session_id} num_turns={message.num_turns} is_error={message.is_error} session_dir={session_dir}")
    return parts, session_id

async def _run_query(prompt: str, persona: str | None = None, session_dir: Path | None = None) -> str | None:
    """
    Runs a single prompt through the Claude Agent SDK and collects the assistant's text reply.

    Args:
        prompt (str):
            The prompt to send.

        persona (str | None):
            Fallback system prompt, used only when session_dir is None (e.g. the startup smoke test) - see
            this function's own Notes on why it's otherwise ignored.

        session_dir (Path | None):
            Optional working-directory anchor for this call. When given, also drives Claude's own session
            continuity via a resume marker file, and this call's own persona/tools/model resolution.

    Returns:
        str | None:
            The assistant's concatenated text reply, or None if no text block was returned or the call failed.

    Notes:
        - Credential resolution is env-var driven - callers set the relevant env var before calling this.
        - Session continuity is resume-based: this call's session_id is captured and reused on the next call for the same session_dir.
        - Persona/tools/model are resolved here, locally, right before querying - never passed down from
          agent_interface.py::query_llm() or any <name>_call.py. call_name_from_session_dir(session_dir) derives
          which Call this is from session_dir's own <root>/<call_name>/<llm_type> shape, then
          agent_persona.parse_agent(settings.LLM_TYPE_CLAUDE, call_name) loads that Call's own library file.
          The persona argument above is only ever consulted when session_dir is None, so a caller with no
          working-directory anchor (today, only the startup smoke test) still has some way to supply a system
          prompt directly.
        - ToolUseBlock/ToolResultBlock content is logged for diagnostic purposes only.
        - Bounded by settings.AGENT_QUERY_TIMEOUT_SECONDS, deliberately mirroring
          claude_session_service.py::query_via_service()'s own timeout handling exactly - same constant, same
          discard-everything-on-timeout behaviour, same logger.error() severity/no-stack-trace treatment, same
          bare None return with no distinguishable error signal. A timeout here is therefore indistinguishable
          from any other failure to every caller above this function, consistent with the OAuth path's own
          existing behaviour - not a gap, a deliberate parity choice.
    """
    resume_id = _read_resume_id(session_dir)
    if session_dir is not None:
        if resume_id:
            transcript = _find_transcript(resume_id)
            if transcript is not None:
                logger.info(f"Resuming Claude session_id={resume_id} at session_dir={session_dir} - transcript found on disk (path={transcript}, mtime={transcript.stat().st_mtime}).")
            else:
                logger.warning(f"Resuming Claude session_id={resume_id} at session_dir={session_dir} - diagnostic: no transcript file found anywhere under ~/.claude/projects/ for this session_id at the moment resume was attempted.")
        else:
            logger.info(f"No prior Claude session_id found at session_dir={session_dir} - starting a fresh session.")

    call_name = call_name_from_session_dir(session_dir)
    if call_name is not None:
        agent = parse_agent(settings.LLM_TYPE_CLAUDE, call_name)
        body, tools, model = agent.body, agent.tools, agent.model
    else:
        body, tools, model = persona, None, None

    options = None
    if body or session_dir:
        options = ClaudeAgentOptions(
            system_prompt=body,
            tools=tools,
            allowed_tools=tools,
            model=model,
            cwd=str(session_dir) if session_dir else None,
            resume=resume_id,
        )

    try:
        reply_parts, captured_session_id = await asyncio.wait_for(_collect_claude_response(prompt, options, session_dir), timeout=settings.AGENT_QUERY_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.error(f"Claude query for session_dir={session_dir} exceeded {settings.AGENT_QUERY_TIMEOUT_SECONDS}s - abandoning it.")
        return None
    except Exception:
        logger.exception("Claude query failed - credential may be invalid/expired, or the endpoint is unreachable.")
        return None
    else:
        _write_resume_id(session_dir, captured_session_id)

    return "".join(reply_parts) or None

async def query_via_oauth(prompt: str, persona: str | None = None, session_dir: Path | None = None) -> str | None:
    """
    Sends a prompt to Claude, authenticated via a Claude Code OAuth token.

    Args:
        prompt (str):
            The prompt to send.

        persona (str | None):
            Optional persona/system prompt for this call.

        session_dir (Path | None):
            Optional working-directory anchor for this call - also decides which of the two underlying paths this call takes.

    Returns:
        str | None:
            The assistant's text reply, or None on failure.

    Notes:
        - Takes no token argument - Claude's credential is resolved once at startup by initialise_claude().
        - Routes through claude_session_service.py's persistent platform whenever session_dir is given, falling back to this module's own one-shot _run_query() otherwise.
        - persona is ignored on the persistent-platform path, which loads its own persona from its own library file - see README.md.
    """
    if session_dir is not None:
        return query_via_service(session_dir, prompt)
    else:
        return await _run_query(prompt, persona, session_dir)

async def query_via_api(prompt: str, persona: str | None = None, session_dir: Path | None = None) -> str | None:
    """
    Sends a prompt to Claude, authenticated via an Anthropic API key.

    Args:
        prompt (str):
            The prompt to send.

        persona (str | None):
            Optional persona/system prompt for this call.

        session_dir (Path | None):
            Optional working-directory anchor for this call - see _run_query()'s own Notes for what it does.

    Returns:
        str | None:
            The assistant's text reply, or None on failure.

    Notes:
        - Takes no token argument - Claude's credential is resolved once at startup by initialise_claude().
    """
    return await _run_query(prompt, persona, session_dir)

def initialise_claude() -> None:
    """
    Resolves Claude's configured access type once at startup and bridges its credential accordingly.

    Starts claude_session_service.py's persistent Claude session platform if the resolved access type is OAuth.

    Args:
        None

    Returns:
        None

    Notes:
        - Reads settings.LLM_CLAUDE_ACCESS_TYPE/settings.LLM_CLAUDE_TOKEN directly, per this module's own convention.
        - Logs the resolved access type, or an unrecognised/unconfigured decision, either way.
    """
    access_type = settings.LLM_CLAUDE_ACCESS_TYPE.strip().upper()

    if access_type == "OAUTH" and settings.LLM_CLAUDE_TOKEN:
        logger.info("Claude access type selected: OAUTH - bridging CLAUDE_CODE_OAUTH_TOKEN and starting the Claude session service.")
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = settings.LLM_CLAUDE_TOKEN
        start_claude_session_service()
    elif access_type == "API" and settings.LLM_CLAUDE_TOKEN:
        logger.info("Claude access type selected: API - bridging ANTHROPIC_API_KEY.")
        os.environ["ANTHROPIC_API_KEY"] = settings.LLM_CLAUDE_TOKEN
    else:
        logger.info(
            f"Claude access type is unknown/unconfigured (LLM_CLAUDE_ACCESS_TYPE={settings.LLM_CLAUDE_ACCESS_TYPE!r}, "
            f"LLM_CLAUDE_TOKEN {'set' if settings.LLM_CLAUDE_TOKEN else 'unset'}) - treating this as no usable "
            f"decision and doing nothing."
        )

def terminate_claude() -> None:
    """
    Stops claude_session_service.py's persistent Claude session platform, if it was started.

    Args:
        None

    Returns:
        None

    Notes:
        - Safe to call unconditionally, even if the service was never started.
    """
    stop_claude_session_service()

def terminate_session(session_dir: Path) -> None:
    """
    Tears down every live, in-memory Claude client anchored anywhere under session_dir.

    Args:
        session_dir (Path):
            The Call/LLM-scoped leaf directory, or a session root covering several such leaves, whose live client(s) should be destroyed.

    Returns:
        None

    Notes:
        - Root-scoped - matches every registry entry equal to or nested under session_dir.
        - A no-op if the service isn't running, or nothing under session_dir has a live client.
    """
    destroy_sessions_under(session_dir)

# =============================================================================
