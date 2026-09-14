# =============================================================================
# File        : claude_interface.py
# Description : Interfaces with Claude via the Claude Agent SDK, supporting both OAuth and API key credentials.
# Author      : SorinoSSK
# Created On  : 2026-09-10
#
# Features    :
#   - query_via_oauth() - sends a prompt to Claude, authenticated via a Claude Code OAuth token. Routed through claude_session_service.py's persistent per-generation platform whenever a session_dir is given; falls back to this module's own one-shot _run_query() otherwise.
#   - query_via_api()   - sends a prompt to Claude, authenticated via an Anthropic API key. Always one-shot (_run_query()) - claude_session_service.py has no API-key equivalent.
#   - initialise_claude()/terminate_claude() - starts/stops claude_session_service.py's persistent Claude session platform, called from agent_interface.py's own initialise_llm_services()/terminate_llm_services().
#
# Notes       :
#   - query_via_api() always uses this module's own one-shot claude_agent_sdk.query() call
#     (_run_query()) - query_via_oauth() uses it only when called with no session_dir (e.g. the startup
#     credential smoke test); otherwise it delegates to claude_session_service.py::query_via_service() instead.
#     See query_via_oauth()'s own Notes for the behavioural differences this split creates (persona handling,
#     the service's own startup dependency).
#   - persona is parsed for an optional YAML frontmatter block (tools/model) plus a system prompt body, wired into ClaudeAgentOptions.
#   - session_dir, if given, anchors Claude's own session continuity: this module remembers the SDK's own
#     session_id in a small marker file inside session_dir (_read_resume_id()/_write_resume_id()) and passes it
#     back as ClaudeAgentOptions' resume= on the next call - continue_conversation=True was tried first and
#     confirmed, empirically, not to reliably resume a session across separate query() calls (matches known
#     upstream reports - see github.com/anthropics/claude-agent-sdk-python issues #10/#555/#848). See
#     _run_query()'s own Notes for detail.
#   - See agent_interface.py for the provider-agnostic dispatch that selects this module.
#   - initialise_claude()/terminate_claude() read settings.LLM_CLAUDE_ACCESS_TYPE/settings.LLM_CLAUDE_TOKEN
#     directly rather than taking either as a parameter, per explicit instruction - it is this module, not
#     agent_interface.py, that decides how Claude is configured. This is why this module imports settings
#     directly - query_via_oauth()/query_via_api() no longer need any credential argument at all (see below),
#     so settings is read only by these two functions.
#   - Credential bridging (CLAUDE_CODE_OAUTH_TOKEN/ANTHROPIC_API_KEY) now happens exactly once, inside
#     initialise_claude(), at startup - per explicit instruction ("run once on startup... and never be called
#     again"). query_via_oauth()/query_via_api() no longer bridge their own credential into os.environ on every
#     call - see their own Notes for the accepted consequence this creates (a call-time dependency on
#     initialise_claude() having already run).
#   - query_via_oauth()/query_via_api() no longer take a token parameter at all, per explicit instruction
#     ("clean up unused token parameter") - since neither function's own body ever read it once the bridging
#     above moved out to initialise_claude(), it was dead, not merely unused-for-parity. This makes this
#     module's own two functions the one deviation from the otherwise-uniform four-provider
#     query_via_oauth(prompt, token, persona, session_dir)/query_via_api(...) signature every other
#     <provider>_interface.py still uses - agent_interface.py::query_llm() calls this module specifically
#     without a token argument as a result. See that module's own Notes for how it accommodates this.
#   - ToolUseBlock/ToolResultBlock content is now logged (name/input, and tool_use_id/is_error/content
#     respectively) wherever an AssistantMessage's blocks are inspected - added specifically to get direct,
#     per-turn evidence of whether a tool (e.g. WebSearch) was actually invoked and what it returned, rather
#     than relying on the model's own self-report of what it does/doesn't have access to. Diagnostic only -
#     neither block type is fed into the returned reply string, which stays text-only.
#
# =============================================================================
# I M P O R T   H E A D E R

import os
import re
import logging

from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, ToolResultBlock, ToolUseBlock, query as claude_query

from ....config import settings
from ..services.claude_session_service import query_via_service, start_claude_session_service, stop_claude_session_service

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_FRONTMATTER_DELIMITER = "---"
_FRONTMATTER_LINE_PATTERN = re.compile(r"^(name|description|tools|model):\s*(.*)$")

# Marker file this module reads/writes inside a given session_dir to remember Claude's own session_id across
# separate _run_query() calls - see _read_resume_id()/_write_resume_id(). Colocated with session_dir
# deliberately, not tracked anywhere else, so clear_session_directory()'s existing whole-tree removal
# (utils_session/session_worker.py) already clears it for free on a session_cleared/global reset - no extra
# clearing logic needed for this file.
_SESSION_ID_MARKER_FILENAME = ".claude_session_id"

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

def _read_resume_id(session_dir: Path | None) -> str | None:
    """
    Reads session_dir's own remembered Claude session_id, if a prior successful call in this generation left one.

    Args:
        session_dir (Path | None):
            The working-directory anchor to check - typically a SessionWorker's own session_dir. None if this
            call has no session_dir at all (e.g. the startup credential smoke test).

    Returns:
        str | None:
            The remembered session_id, or None if session_dir is None, no marker file exists yet (this
            generation's very first call), or the file is empty.

    Notes:
        - Never raises - a missing/unreadable marker file is treated the same as "nothing to resume from" (this
          generation's first call), not an error.
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
    Remembers session_id as session_dir's own latest Claude session, for a future call in this generation to
    resume from.

    Args:
        session_dir (Path | None):
            The working-directory anchor to write into. A no-op if None (nothing to anchor the marker to).

        session_id (str | None):
            The session_id captured from this call's own ResultMessage. A no-op if None/empty - leaves whatever
            was previously remembered untouched, rather than overwriting it with nothing.

    Returns:
        None

    Notes:
        - Only ever called after a confirmed-successful call (see _run_query()) - a failed call leaves the
          previously-remembered session_id in place, so the next call still has something valid to resume from.
        - Best-effort - a write failure is logged but non-fatal, matching this codebase's own on-disk cleanup
          convention (e.g. utils_session/session_worker.py::clear_session_directory()).
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
    Searches ~/.claude/projects/ for session_id's own transcript file - diagnostic only, decides nothing.

    Args:
        session_id (str):
            The Claude session_id to look for.

    Returns:
        Path | None:
            The matching <session_id>.jsonl file, if found anywhere under ~/.claude/projects/; otherwise None.

    Notes:
        - Added purely to get direct evidence on a resume=<session_id> failure ("No conversation found") -
          whether the transcript genuinely isn't on disk yet (a timing race), or is present somewhere Claude
          itself isn't finding it (a session_dir/lookup mismatch) - rather than guessing from third-party bug
          reports.
        - A plain recursive filename search, not dependent on Claude's own undocumented project-directory
          encoding scheme - only the leaf filename (<session_id>.jsonl) is assumed stable.
        - Never raises - a missing/inaccessible ~/.claude/projects/ is treated the same as "not found".
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

async def _run_query(prompt: str, persona: str | None = None, session_dir: Path | None = None) -> str | None:
    """
    Runs a single prompt through the Claude Agent SDK and collects the assistant's text reply.

    Args:
        prompt (str):
            The prompt to send.

        persona (str | None):
            Optional persona/system prompt for this call, parsed via _parse_persona().

        session_dir (Path | None):
            Optional working-directory anchor for this call, typically a SessionWorker's own session_dir. When
            given, also drives Claude's own session continuity - see Notes below.

    Returns:
        str | None:
            The assistant's concatenated text reply, or None if no text block was returned or the call failed.

    Notes:
        - Credential resolution is env-var driven - callers set the relevant env var before calling this.
        - Session continuity is resume-based, not continue_conversation-based. continue_conversation=True was
          tried first (on the assumption that a stable session_dir alone would let the SDK find and resume its
          most recent session there) and confirmed, empirically, not to work - diagnostic logging showed a
          brand-new session_id and num_turns=1 on every single call despite an identical session_dir across all
          of them, matching known upstream reports (github.com/anthropics/claude-agent-sdk-python issues
          #10/#555/#848). The documented, working mechanism instead is: capture session_id from a call's own
          ResultMessage, then pass it back explicitly as resume= on the next call - which is what this function
          now does via _read_resume_id()/_write_resume_id(), using a small marker file colocated with
          session_dir.
        - Only ever reads/writes that marker file when session_dir is given - a call with no session_dir (e.g.
          the startup credential smoke test) behaves exactly as before, no resume attempted, no marker file
          involved.
        - Each SessionWorker generation gets its own never-before-used session_dir (see session_worker.py's own
          Notes on why), so this marker file is likewise generation-scoped - a session_cleared/global reset
          wipes it along with the rest of that generation's directory (see clear_session_directory()), and the
          next generation starts with no marker file, correctly starting Claude fresh rather than resuming a
          conversation that was supposed to be cleared.
        - ToolUseBlock/ToolResultBlock are logged too, not just collected/discarded like every other
          non-TextBlock content - same diagnostic addition as claude_session_service.py::_run_turn(), for
          parity between this one-shot path and that persistent one. Purely diagnostic - neither is fed into
          the returned reply string, which remains text-only, unchanged.
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

    options = None
    if persona or session_dir:
        body, tools, model = _parse_persona(persona) if persona else (None, None, None)
        options = ClaudeAgentOptions(
            system_prompt=body,
            tools=tools,
            allowed_tools=tools,
            model=model,
            cwd=str(session_dir) if session_dir else None,
            resume=resume_id,
        )

    reply_parts = []
    captured_session_id = None
    try:
        async for message in claude_query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        reply_parts.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        logger.info(f"Claude tool_use: name={block.name!r} input={block.input} session_dir={session_dir}")
                    elif isinstance(block, ToolResultBlock):
                        logger.info(f"Claude tool_result: tool_use_id={block.tool_use_id} is_error={block.is_error} content={block.content} session_dir={session_dir}")
            elif isinstance(message, ResultMessage):
                captured_session_id = message.session_id
                # Diagnostic logging, kept from the continue_conversation investigation - still useful to
                # directly verify resume= is now actually working (session_id staying stable, num_turns
                # climbing across successive calls at the same session_dir) rather than trusting it silently.
                logger.info(f"Claude ResultMessage: session_id={message.session_id} num_turns={message.num_turns} is_error={message.is_error} session_dir={session_dir}")
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
            Optional working-directory anchor for this call - see _run_query()'s own Notes for what it does.
            Also decides which of the two underlying paths this call actually takes - see Notes below.

    Returns:
        str | None:
            The assistant's text reply, or None on failure.

    Notes:
        - Takes no token argument - unlike codex_interface.py/deepseek_interface.py/qwen_interface.py's own
          query_via_oauth(), which still bridge their own credential per call. Claude's credential is resolved
          exactly once, at startup, inside initialise_claude() - CLAUDE_CODE_OAUTH_TOKEN is already set (or not)
          in os.environ by the time this function ever runs, and this function has no per-call use for it
          anyway (see the next Note). A direct consequence: this function depends on initialise_claude() having
          already run and having actually selected OAuth - calling it beforehand, or with Claude configured for
          a different access type, sends an unauthenticated request rather than one authenticated per call.
          agent_interface.py::query_llm() calls this function's own signature specifically (no token argument),
          not the uniform four-provider call it uses for codex/deepseek/qwen - see its own Notes.
        - Routes through claude_session_service.py's persistent per-generation platform (query_via_service())
          whenever session_dir is given, rather than this module's own one-shot _run_query() - a genuinely
          continued conversation on one long-lived ClaudeSDKClient per session_dir, reused turn to turn, rather
          than a fresh connection and a resume=<session_id> marker file on every call. Falls back to
          _run_query() only when session_dir is None (today, only agent_interface.py's own startup credential
          smoke test calls this with no session_dir at all).
        - persona is silently unused on the query_via_service() path - that platform loads its own
          persona/tools/model itself, from libraries/claude/chat.json via its own _parse_agent(), never from
          whatever this function was called with. This is a real behavioural divergence from the _run_query()
          fallback path (which does honour persona, parsed via _parse_persona() from libraries/claude/chat.md) -
          flagged explicitly rather than silently absorbed: a caller passing a persona now only sees it take
          effect when session_dir is None.
        - claude_session_service.py's own persona file is hardcoded to the Chat Call specifically
          (_LLM_TYPE="claude", filename "chat.json") - not a problem in practice today since Chat is the only
          Call actually reachable (see call_dispatch_handler.py's own Phase 3/4 history in CODE_TODO.md), but a
          real, pre-existing constraint this routing now makes load-bearing rather than latent, should
          Architect/Coder/Review/Documentation ever also resolve to llm_type="claude"+access_type="OAUTH" with
          a session_dir of their own.
        - query_via_service() is itself a blocking, synchronous call (it blocks its own calling thread for a
          reply, up to settings.AGENT_QUERY_TIMEOUT_SECONDS) - called directly here, not awaited, since it is
          not itself a coroutine. Consistent with this codebase's existing blocking-call convention elsewhere
          (this function's own caller already runs one turn at a time on one SessionWorker's dedicated thread -
          see session_worker.py), not a new concurrency risk introduced by this change.
        - Requires claude_session_service.py's own background thread/loop to already be running
          (start_claude_session_service(), called from initialise_claude() when OAuth is selected) - if that
          service was never started (e.g. initialise_llm_services() not yet wired into initialise.py - see
          CODE_TODO.md), every call on this path returns None immediately (logged as an error by
          query_via_service() itself) rather than silently falling back to _run_query().
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
        - Takes no token argument - unlike codex_interface.py/deepseek_interface.py/qwen_interface.py's own
          query_via_api(), which still bridge their own credential per call. Claude's credential is resolved
          exactly once, at startup, inside initialise_claude() - ANTHROPIC_API_KEY is already set (or not) in
          os.environ by the time this function ever runs. A direct consequence: this function depends on
          initialise_claude() having already run and having actually selected API - calling it beforehand, or
          with Claude configured for a different access type, sends an unauthenticated request rather than one
          authenticated per call. agent_interface.py::query_llm() calls this function's own signature
          specifically (no token argument), not the uniform four-provider call it uses for codex/deepseek/qwen
          - see its own Notes.
    """
    return await _run_query(prompt, persona, session_dir)

def initialise_claude() -> None:
    """
    Resolves Claude's configured access type exactly once, at startup, bridges its credential into whichever
    environment variable claude_agent_sdk actually reads, and starts claude_session_service.py's persistent
    Claude session platform if - and only if - that resolved access type is OAuth.

    Args:
        None

    Returns:
        None

    Notes:
        - Reads settings.LLM_CLAUDE_ACCESS_TYPE/settings.LLM_CLAUDE_TOKEN directly rather than taking either as
          a parameter, per explicit instruction - this module is the one that decides how Claude is configured,
          rather than a caller (agent_interface.py) resolving that decision and handing this function the
          result. See this module's own header Notes for why this deliberately departs from
          query_via_oauth()/query_via_api()'s explicit-argument convention.
        - Runs once, at startup, per explicit instruction ("begin the implementation to run once on startup") -
          this is now the *only* place either CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY is ever set for
          Claude; query_via_oauth()/query_via_api() no longer bridge anything themselves (see their own Notes).
          A direct, accepted consequence: both of those now depend on this function having already run with
          the same access type still in effect - not yet addressed here, since wiring this into initialise.py's
          own startup ordering (ahead of test_llm_tokens()'s smoke test, specifically) is deferred until
          initialise_llm_services() itself is actually wired in.
        - Logs the resolved access type either way, per explicit instruction ("log selection choice") - an
          operator can tell from the logs alone which of the three outcomes below this startup run resolved
          to, rather than only seeing evidence of the two "something happened" branches.
        - Three outcomes, one branch each:
            - LLM_CLAUDE_ACCESS_TYPE == "OAUTH" and LLM_CLAUDE_TOKEN configured - bridges
              CLAUDE_CODE_OAUTH_TOKEN, then starts claude_session_service.py's persistent platform (unchanged
              from the existing OAuth-only gate on that platform).
            - LLM_CLAUDE_ACCESS_TYPE == "API" and LLM_CLAUDE_TOKEN configured - bridges ANTHROPIC_API_KEY only;
              there is no persistent platform for this access type, so this bridge exists purely for
              query_via_api()'s own one-shot claude_agent_sdk.query() calls.
            - Anything else (access type unset/unrecognised, or its own token missing) - per explicit
              instruction ("if none, assume unknown decision, log it and do nothing") - logged as an
              unresolved/unknown configuration decision; no environment mutation, no service start.
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
        - Safe to call unconditionally, even if initialise_claude() never started the service (Claude
          configured for API access instead of OAuth, or not configured at all) -
          stop_claude_session_service() is already its own no-op in that case.
        - Called from agent_interface.py::terminate_llm_services() - not intended to be called directly by
          any other caller, though nothing in this function's own signature prevents it.
    """
    stop_claude_session_service()

# =============================================================================
