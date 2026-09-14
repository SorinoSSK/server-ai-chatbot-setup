# =============================================================================
# File        : claude_session_service.py
# Description : Always-on platform maintaining one persistent Claude Agent SDK connection (ClaudeSDKClient) per
#               generation directory, so a conversation can genuinely continue turn-to-turn - and become
#               eligible for Claude's own prompt-cache pricing - without any per-session thread ever holding
#               persistent async state itself.
# Author      : SorinoSSK
# Created On  : 2026-09-13
#
# Features    :
#   - start_claude_session_service()/stop_claude_session_service() - lifecycle for this platform's own
#     dedicated thread and persistent event loop.
#   - query_via_service() - the platform's public entry point. Synchronous from any caller's own thread - hands
#     a turn off to this service's persistent loop and blocks for the reply, the same shape as any other
#     blocking provider call (a subprocess run, an HTTP request) elsewhere in utils_agents/.
#   - destroy_session() - disconnects and discards a generation's client. Exists for a future session_reset
#     hook to call, so an external client's own memory of a cleared conversation is destroyed alongside the
#     on-disk state, not left to leak until process exit.
#
# Notes       :
#   - Built and hardened in isolation initially, per explicit instruction - see the module's own Created On
#     date. Since wired in for real: claude_interface.py::query_via_oauth() routes here whenever session_dir
#     is given, initialise_claude()/terminate_claude() call start_claude_session_service()/
#     stop_claude_session_service() (gated on OAuth), and those two are in turn wired into
#     utilities/initialise.py's own initialise_application()/terminate_application(). destroy_session() alone
#     remains uncalled from anywhere - see its own docstring.
#   - ToolUseBlock/ToolResultBlock content is now logged (name/input, and tool_use_id/is_error/content
#     respectively) inside _run_turn() - added specifically to get direct, per-turn evidence of whether a tool
#     (e.g. WebSearch) was actually invoked and what it returned, rather than relying on the model's own
#     self-report of what it does/doesn't have access to. Diagnostic only - neither block type is fed into the
#     returned reply string, which stays text-only.
#   - One ClaudeSDKClient per generation directory (keyed by str(session_dir)), never pooled or shared across
#     two different session_dir keys - see _get_or_create_entry()'s own Notes. This is what actually guarantees
#     cache isolation between different sessions/users: Claude's own prompt cache is an exact-content-prefix match,
#     and since every generation's client sends only that one conversation's own accumulating turns, there is
#     no code path where one session's private content could ever be served back against another session's
#     request. This is a structural guarantee (one client object, one generation, never crossed), not a
#     runtime check layered on top of a shared connection.
#   - The static persona/system-prompt block is identical across every session using the same Call, and may
#     legitimately be cached and reused across different sessions by Claude's own automatic caching - that's
#     safe (no private content) and is Claude's own behaviour, not anything built here. Flagged as an assumption
#     consistent with Claude Code's documented caching behaviour, not independently verified by this module.
#   - Continuity comes from holding one connection open across turns - unlike the one-shot query() function's
#     continue_conversation/resume options (both empirically proven not to work for this application - see
#     claude_interface.py's own history), a ClaudeSDKClient's persistent connection continues its own session
#     automatically on every further .query() call, with no resume flag needed at all.
#   - Deliberately-considered limitations, each addressed or explicitly accepted below rather than overlooked:
#       - Two concurrent turns for the same session_dir (shouldn't happen given SessionWorker's own
#         one-batch-at-a-time guarantee, but this platform doesn't assume a caller's internal discipline) -
#         serialised per-client via _ClientEntry.lock, held for a whole query()/receive_response() cycle.
#       - Two concurrent first-use requests for the same session_dir racing to create a client - serialised via
#         the registry's own asyncio.Lock, held only for the short create-or-fetch step, never across a query.
#       - A persona change mid-generation (e.g. an admin edits a library file while a session is still active) -
#         detected by comparing the AgentPersona an existing client was built with against a fresh one parsed
#         straight off disk on every turn (_parse_agent() takes no input and always re-reads the file); a
#         mismatch reconnects with a fresh client rather than silently continuing on stale configuration.
#       - A broken/crashed client (subprocess died, pipe closed) - dropped from the registry on its next failed
#         use rather than retried in place; the following call creates a fresh connection instead of wedging
#         permanently. That session loses Claude-side continuity for one turn but recovers.
#       - A caller that times out waiting for a reply - query_via_service() cancels its own future, but this is
#         best-effort only: cancelling a Future returned by run_coroutine_threadsafe() does not guarantee the
#         in-flight coroutine on the service's own loop actually stops - it may keep running to completion in
#         the background, updating/holding its client's state, with nothing left to receive the eventual result.
#       - Unbounded growth of the registry (many generations, none ever destroyed) - expected and accepted for
#         now, since destroy_session() has no caller yet in this isolated build; not a defect of this module.
#       - Credential setup (CLAUDE_CODE_OAUTH_TOKEN/ANTHROPIC_API_KEY) still mutates process-wide os.environ,
#         same constraint already documented against claude_interface.py/agent_interface.py - inherited, not
#         newly introduced here, and unchanged by this module's own single-Claude-credential-configured-at-once
#         reality today.
#   - Expected library file format - libraries/claude/chat.json, read directly by _parse_agent() (which takes no
#     input at all - it owns its own file path via the module-level _LIBRARIES_ROOT/_LLM_TYPE constants):
#       {
#           "tools": ["WebSearch"],
#           "model": "sonnet",
#           "persona": ["You are {{BOT_NAME}}, ...", "..."]
#       }
#     "persona" may be an array of lines (joined with "\n") or a bare string - either is accepted. "name"/
#     "description" keys, if present, are still not read into body/tools/model at all - a persona's identity
#     comes from {{BOT_NAME}} in the body, substituted for settings.TELEGRAM_BOT_NAME at load time, never a fixed
#     name written into the file itself.
#   - _parse_agent() returns an AgentPersona (body/tools/model/persona) rather than a bare tuple. AgentPersona
#     itself is defined in config.py, not here, since the same shape is meant to be valid and reusable across
#     every LLM provider's own eventual equivalent of this function - not something specific to Claude.
#   - _DEFAULT_QUERY_TIMEOUT_SECONDS/_DEFAULT_SHUTDOWN_TIMEOUT_SECONDS, previously local module constants, are
#     now settings.AGENT_QUERY_TIMEOUT_SECONDS/settings.AGENT_SHUTDOWN_TIMEOUT_SECONDS in config.py - global,
#     provider-agnostic defaults for any always-on, persistent-connection agent session platform, not specific
#     to Claude even though it's the only provider with one implemented today.
#   - See agent_interface.py for the provider-agnostic dispatch that would eventually route into this module.
#
# =============================================================================
# I M P O R T   H E A D E R

import json
import logging
import asyncio
import threading
import concurrent.futures

from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, TextBlock, ToolResultBlock, ToolUseBlock

from ....config import AgentPersona, settings

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# Placeholder a persona body may use to refer to the bot's own configured name - substituted for
# settings.TELEGRAM_BOT_NAME by _parse_agent(), never hardcoded into a library file itself. See this module's
# own Notes for the expected chat.json shape this is meant to be authored against.
_BOT_NAME_PLACEHOLDER = "{{BOT_NAME}}"

# This service's own library file location - libraries/<llm_type>/chat.json, resolved relative to this file's
# own location so it doesn't depend on the process's current working directory. Fixed to "claude"/"chat.json"
# since this module is Claude-specific - a future Codex/Qwen/DeepSeek equivalent would define its own constants
# pointing at its own library file, rather than sharing these.
_LLM_TYPE = "claude"
_LIBRARIES_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "libraries"

# This platform's own dedicated thread and event loop - created by start_claude_session_service(), torn down by
# stop_claude_session_service(). Never shared with, or touched by, any SessionWorker's own thread.
_loop: "asyncio.AbstractEventLoop | None" = None
_thread: "threading.Thread | None" = None

# Guards _clients dict mutation only (insert/remove) - created lazily, the first time it's needed, always from
# within a coroutine already running on _loop (see _get_registry_lock()). Never held across an await beyond the
# short create-or-fetch step itself.
_registry_lock: "asyncio.Lock | None" = None

# =============================================================================

class _ClientEntry:
    """
    One generation's own persistent Claude connection, plus what's needed to serialise and validate reuse of it.

    Notes:
        - Stores the AgentPersona the client was actually built with (not a raw string) so a later call can
          detect a changed library file with a plain dataclass equality check (entry.agent != freshly-parsed
          agent) - see _get_or_create_entry()'s own Notes.
    """

    def __init__(self, client: ClaudeSDKClient, agent: AgentPersona):
        self.client = client
        self.agent = agent
        self.lock = asyncio.Lock()

_clients: dict[str, _ClientEntry] = {}

# =============================================================================

def _parse_agent() -> AgentPersona:
    """
    Loads and parses this service's own Claude library file (libraries/claude/chat.json) into an AgentPersona,
    defensively - a missing, unreadable, or malformed file falls back to an empty-but-valid AgentPersona rather
    than raising, so a broken library file degrades a session's persona rather than blocking it outright.

    Args:
        None

    Returns:
        AgentPersona:
            The parsed agent definition, with _BOT_NAME_PLACEHOLDER in its body already substituted for
            settings.TELEGRAM_BOT_NAME. Falls back to AgentPersona(body="", tools=None, model=None, persona={})
            if the file is missing, unreadable, or not valid JSON.

    Notes:
        - Takes no arguments and owns its own file path entirely - _LIBRARIES_ROOT / _LLM_TYPE / "chat.json" -
          rather than being handed pre-loaded content by a caller, per explicit instruction. A side effect of
          this is that it re-reads the file fresh on every call, which is exactly what lets
          _get_or_create_entry() detect a library file changing mid-generation by comparing two AgentPersona
          values for equality, rather than needing a separate file-watching mechanism.
        - Every failure mode is caught and logged rather than raised, and all three fall back to the same empty
          AgentPersona rather than three different error shapes a caller would need to handle separately:
          a missing file (FileNotFoundError), a file that exists but can't be read (OSError), and a file that
          exists but isn't valid JSON (json.JSONDecodeError).
        - AgentPersona itself lives in config.py, not here - it's meant to be one shared, provider-agnostic
          return shape reusable by a future Codex/Qwen/DeepSeek equivalent of this function, not something
          specific to Claude.
        - "name"/"description" keys, if present in the JSON, are not read into body/tools/model at all - a
          persona's identity comes from _BOT_NAME_PLACEHOLDER in its body, substituted for
          settings.TELEGRAM_BOT_NAME, never from a name written into the file itself. Both are still available
          on the returned value's own .persona field, for any future need.
    """
    path = _LIBRARIES_ROOT / _LLM_TYPE / "chat.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.exception(f"Claude library file not found at {path} - using an empty AgentPersona instead.")
        return AgentPersona(body="", tools=None, model=None, persona={})
    except OSError:
        logger.exception(f"Claude library file at {path} could not be read - using an empty AgentPersona instead.")
        return AgentPersona(body="", tools=None, model=None, persona={})
    except json.JSONDecodeError:
        logger.exception(f"Claude library file at {path} is not valid JSON - using an empty AgentPersona instead.")
        return AgentPersona(body="", tools=None, model=None, persona={})
    else:
        raw_body = data.get("persona", "")
        body = "\n".join(raw_body) if isinstance(raw_body, list) else str(raw_body)
        body = body.strip().replace(_BOT_NAME_PLACEHOLDER, settings.TELEGRAM_BOT_NAME)

        tools = data.get("tools") or None
        model = data.get("model") or None
        return AgentPersona(body=body, tools=tools, model=model, persona=data)

def _get_registry_lock() -> asyncio.Lock:
    """
    Returns this platform's own registry lock, creating it on first use.

    Args:
        None

    Returns:
        asyncio.Lock:
            The lock guarding _clients dict mutation.

    Notes:
        - Only ever called from within a coroutine already running on _loop, so the check-then-create below has
          no await between the check and the assignment - safe under asyncio's own cooperative scheduling with
          no separate guard needed for the lock's own creation.
    """
    global _registry_lock
    if _registry_lock is None:
        _registry_lock = asyncio.Lock()
    return _registry_lock

async def _disconnect_entry(entry: _ClientEntry) -> None:
    """
    Disconnects one client entry's own connection, best-effort.

    Args:
        entry (_ClientEntry):
            The entry being discarded - already removed from _clients by the caller.

    Returns:
        None

    Notes:
        - Never raises - a failed disconnect is logged but does not block whatever cleanup/replacement is
          happening around it, since the entry is being discarded either way.
    """
    try:
        await entry.client.disconnect()
    except Exception:
        logger.exception("Failed to cleanly disconnect a persistent Claude client - continuing regardless, since it is being discarded either way.")

async def _drop_entry(session_dir: Path) -> None:
    """
    Removes and disconnects session_dir's own client entry, if one exists.

    Args:
        session_dir (Path):
            The generation directory whose entry should be removed.

    Returns:
        None
    """
    key = str(session_dir)
    registry_lock = _get_registry_lock()
    async with registry_lock:
        entry = _clients.pop(key, None)

    if entry is not None:
        await _disconnect_entry(entry)

async def _get_or_create_entry(session_dir: Path) -> _ClientEntry:
    """
    Returns session_dir's own persistent Claude client entry, creating - or recreating, if the library file has
    changed since it was created - it first.

    Args:
        session_dir (Path):
            The generation directory this client is anchored to. Doubles as ClaudeAgentOptions' own cwd, and as
            this registry's own lookup key (str(session_dir)).

    Returns:
        _ClientEntry:
            The (possibly newly-created) entry for session_dir - never shared with any other session_dir.

    Notes:
        - Calls _parse_agent() itself on every invocation, rather than being handed a persona by its own caller -
          this is what makes the library-file-changed check below possible with a plain equality comparison,
          since _parse_agent() always reflects the file's current on-disk contents.
        - An AgentPersona mismatch against an already-connected entry forces a disconnect-and-recreate, rather
          than silently continuing on the configuration the client was originally built with - a persistent
          connection would otherwise never notice a library file changing mid-generation, unlike the one-shot
          query() path (see chat_call.py's own "persona is loaded fresh on every call" behaviour).
        - Registry lookup/creation is serialised via _get_registry_lock() so two concurrent first-use requests
          for the same session_dir cannot both create a client - the second waiter finds the first's entry
          already present once it acquires the lock, rather than racing to create two.
        - Connection failure (client.connect() raising) is not caught here - it propagates to the caller
          (_run_turn()), which already has its own single, uniform failure-handling path for this whole
          operation. Nothing is added to _clients unless connect() actually succeeds.
    """
    key = str(session_dir)
    registry_lock = _get_registry_lock()
    async with registry_lock:
        agent = _parse_agent()
        entry = _clients.get(key)
        if entry is not None and entry.agent != agent:
            logger.info(f"Claude library file changed for session_dir={session_dir} since its client was created - reconnecting with the new agent definition instead of continuing on stale configuration.")
            _clients.pop(key, None)
            await _disconnect_entry(entry)
            entry = None

        if entry is None:
            options = ClaudeAgentOptions(system_prompt=agent.body, tools=agent.tools, allowed_tools=agent.tools, model=agent.model, cwd=str(session_dir))
            client = ClaudeSDKClient(options=options)
            await client.connect()
            entry = _ClientEntry(client, agent)
            _clients[key] = entry
            logger.info(f"Created new persistent Claude client for session_dir={session_dir}.")

        return entry

async def _run_turn(session_dir: Path, prompt: str) -> str | None:
    """
    Runs one turn against session_dir's own persistent Claude client, creating it first if this is its first use.

    Args:
        session_dir (Path):
            The generation directory identifying which persistent client this turn belongs to.

        prompt (str):
            The prompt to send.

    Returns:
        str | None:
            The assistant's concatenated text reply, or None if no text block was returned or the call failed.

    Notes:
        - entry.lock is held for the entire query()/receive_response() cycle, not just around the send - this is
          what serialises two turns that somehow arrive concurrently for the same session_dir, so client.query()
          is never called a second time before the first turn has finished draining its own response.
        - Any failure (client-creation failure, a mid-query exception, a broken connection) drops and discards
          this session_dir's entry entirely before returning None - the next call starts completely fresh rather
          than reusing a connection that just proved itself broken.
        - ResultMessage's own usage (input_tokens/cache_creation_input_tokens/cache_read_input_tokens/
          output_tokens) is logged on every turn - direct, per-turn evidence of whether cache tokens are
          actually being used, not assumed from documentation.
        - ToolUseBlock/ToolResultBlock are logged too, not just collected/discarded like every other
          non-TextBlock content - added specifically to get direct, per-turn evidence of whether a tool
          (e.g. WebSearch) was actually invoked and what it returned, rather than relying on the model's own
          self-report of what it does/doesn't have access to. Purely diagnostic - neither is fed into the
          returned reply string, which remains text-only, unchanged.
    """
    try:
        entry = await _get_or_create_entry(session_dir)
        async with entry.lock:
            await entry.client.query(prompt)
            reply_parts = []
            async for message in entry.client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            reply_parts.append(block.text)
                        elif isinstance(block, ToolUseBlock):
                            logger.info(f"Claude tool_use: name={block.name!r} input={block.input} session_dir={session_dir}")
                        elif isinstance(block, ToolResultBlock):
                            logger.info(f"Claude tool_result: tool_use_id={block.tool_use_id} is_error={block.is_error} content={block.content} session_dir={session_dir}")
                elif isinstance(message, ResultMessage):
                    logger.info(
                        f"Claude session service ResultMessage: session_id={message.session_id} "
                        f"num_turns={message.num_turns} is_error={message.is_error} usage={message.usage} session_dir={session_dir}"
                    )

            return "".join(reply_parts) or None
    except Exception:
        logger.exception(f"Persistent Claude client for session_dir={session_dir} failed - dropping it so the next turn starts a fresh connection instead of reusing a possibly-broken one.")
        await _drop_entry(session_dir)
        return None

async def _disconnect_all() -> None:
    """
    Disconnects and discards every currently-registered client - used by stop_claude_session_service().

    Args:
        None

    Returns:
        None
    """
    registry_lock = _get_registry_lock()
    async with registry_lock:
        entries = list(_clients.values())
        _clients.clear()

    for entry in entries:
        await _disconnect_entry(entry)

def query_via_service(session_dir: Path, prompt: str, timeout: float = settings.AGENT_QUERY_TIMEOUT_SECONDS) -> str | None:
    """
    Runs one turn against session_dir's own persistent Claude session, from any calling thread.

    Args:
        session_dir (Path):
            The generation directory identifying which persistent client this turn belongs to.

        prompt (str):
            The prompt to send.

        timeout (float):
            Maximum seconds to wait for a reply before abandoning this call. Defaults to
            settings.AGENT_QUERY_TIMEOUT_SECONDS (see config.py - shared across every provider's own eventual
            session platform, not specific to Claude).

    Returns:
        str | None:
            The assistant's text reply, or None if the service isn't running, the call timed out, or it failed.

    Notes:
        - This is the platform's one public, caller-facing entry point - synchronous from the calling thread's
          own point of view, identical in shape to any other blocking provider call elsewhere in utils_agents/.
          All persistent/async state lives inside this service's own loop, never inside the caller's thread.
        - Takes no persona - the client's own system prompt/tools/model come entirely from _parse_agent()
          reading the library file directly, on this service's own loop, once per turn (via
          _get_or_create_entry()). A caller has no way to override it per-call.
        - A timeout cancels this call's own Future, but that is best-effort only - it stops this function from
          waiting any further, it does not guarantee the corresponding coroutine running on the service's own
          loop actually stops. It may continue running to completion in the background, still holding/updating
          its client's state, with no one left waiting on its result.
        - Never raises - every failure path (service not started, timeout, unexpected exception) is logged and
          returns None instead, matching this codebase's existing never-crash-on-a-failed-LLM-call convention.
    """
    if _loop is None:
        logger.error("Claude session service has not been started - call start_claude_session_service() first. Returning None rather than raising.")
        return None
    else:
        future = asyncio.run_coroutine_threadsafe(_run_turn(session_dir, prompt), _loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            logger.error(
                f"Claude session service call for session_dir={session_dir} exceeded {timeout}s - abandoning it. "
                f"The in-flight call on the service's own loop is not guaranteed to have actually stopped - see this function's own Notes."
            )
            return None
        except Exception:
            logger.exception(f"Claude session service call for session_dir={session_dir} raised unexpectedly.")
            return None

def destroy_session(session_dir: Path) -> None:
    """
    Disconnects and discards session_dir's own persistent Claude client, if one exists.

    Args:
        session_dir (Path):
            The generation directory whose client should be destroyed.

    Returns:
        None

    Notes:
        - Exists for a future session_reset/session_cleared hook to call, so this service's own memory of a
          cleared conversation is destroyed at the same moment as the on-disk generation directory, rather than
          left to leak until process exit. Not called from anywhere yet - this module is built in isolation.
        - A no-op (logged at debug) if the service isn't running at all, or if session_dir has no client to
          begin with.
        - Best-effort, same convention as this codebase's other on-disk/connection cleanup (e.g.
          utils_session/session_worker.py::clear_session_directory()) - a failure is logged, not raised.
    """
    if _loop is None:
        logger.debug(f"Claude session service is not running - nothing to destroy for session_dir={session_dir}.")
    else:
        future = asyncio.run_coroutine_threadsafe(_drop_entry(session_dir), _loop)
        try:
            future.result(timeout=settings.AGENT_SHUTDOWN_TIMEOUT_SECONDS)
        except Exception:
            logger.exception(f"Failed to cleanly destroy the persistent Claude client for session_dir={session_dir}.")

def start_claude_session_service() -> None:
    """
    Starts this platform's own dedicated thread and persistent event loop, if not already running.

    Args:
        None

    Returns:
        None

    Notes:
        - No-op (logged at debug) if already running - mirrors the defensive-guard style already used by this
          codebase's other start_*() functions (e.g. utils_session/session_worker.py's own
          start_session_reset_schedule()).
        - The thread runs _loop.run_forever() and nothing else - all actual work is scheduled onto it via
          asyncio.run_coroutine_threadsafe() from query_via_service()/destroy_session()/stop_claude_session_service().
    """
    global _loop, _thread
    if _thread is not None and _thread.is_alive():
        logger.debug("Claude session service already running - start_claude_session_service() is a no-op.")
    else:
        _loop = asyncio.new_event_loop()
        _thread = threading.Thread(target=_loop.run_forever, daemon=True, name="ClaudeSessionService")
        _thread.start()
        logger.info("Started Claude session service (persistent per-generation Claude client platform).")

def stop_claude_session_service(timeout: float = settings.AGENT_SHUTDOWN_TIMEOUT_SECONDS) -> None:
    """
    Disconnects every live client and stops this platform's own loop/thread.

    Args:
        timeout (float):
            Maximum seconds to wait for every client to disconnect, and for this service's own thread to stop.
            Defaults to settings.AGENT_SHUTDOWN_TIMEOUT_SECONDS (see config.py - shared across every provider's
            own eventual session platform, not specific to Claude).

    Returns:
        None

    Notes:
        - No-op (logged at debug) if the service was never started/already stopped - harmless to call
          unconditionally, same convention as utils_session/session_worker.py::stop_session_reset_schedule().
        - A client that fails to disconnect cleanly within timeout is logged and abandoned - the process is
          assumed to be exiting regardless, matching shutdown_all_session_workers()'s own bounded-wait-then-
          abandon precedent.
    """
    global _loop, _thread
    if _loop is None or _thread is None or not _thread.is_alive():
        logger.debug("Claude session service is not running - stop_claude_session_service() is a no-op.")
    else:
        future = asyncio.run_coroutine_threadsafe(_disconnect_all(), _loop)
        try:
            future.result(timeout=timeout)
        except Exception:
            logger.exception("Failed to cleanly disconnect every persistent Claude client during shutdown.")

        _loop.call_soon_threadsafe(_loop.stop)
        _thread.join(timeout=timeout)
        if _thread.is_alive():
            logger.error("Claude session service thread did not stop within timeout - abandoning it (process is exiting regardless).")

        _loop = None
        _thread = None

# =============================================================================
