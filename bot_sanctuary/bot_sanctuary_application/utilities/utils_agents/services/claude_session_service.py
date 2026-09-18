# =============================================================================
# File        : claude_session_service.py
# Description : Always-on platform maintaining one persistent Claude Agent SDK connection per generation directory, so a conversation can genuinely continue turn-to-turn.
# Author      : SorinoSSK
# Created On  : 2026-09-13
#
# Features    :
#   - start_claude_session_service()/stop_claude_session_service() - lifecycle for this platform's own thread and event loop.
#   - query_via_service() - runs one turn against a session_dir's persistent client, synchronously from any caller's own thread.
#   - destroy_session()/destroy_sessions_under() - disconnects and discards one or more clients by registry key.
#
# Notes       :
#   - One ClaudeSDKClient per generation directory, never pooled or shared across two different session_dir keys.
#   - A changed library file mid-generation triggers a reconnect with the new agent definition.
#   - A broken/crashed client is dropped from the registry and rebuilt fresh on its next use.
#   - A caller timeout evicts the corresponding registry entry, so the next call always builds a fresh client.
#   - Registry entries are bounded by session reset, not by an idle timeout.
#   - Library-file loading/parsing (parse_agent()) lives in agent_persona.py, not this module - moved out
#     2026-09-18 and generalised (llm_type/call_name are now parameters) so every provider's own interface
#     module can share it. This module still only ever calls it with settings.LLM_TYPE_CLAUDE + "chat" -
#     not yet generalised to any other Call, same limitation as before the move.
#   - See agent_interface.py for the provider-agnostic dispatch that would eventually route into this module.
#   - See README.md for the full concurrency, caching, and failure-handling design rationale.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging
import asyncio
import threading
import concurrent.futures

from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, TextBlock, ToolResultBlock, ToolUseBlock

from ....config import AgentPersona, settings
from ..agent_persona import parse_agent

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

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
    """

    def __init__(self, client: ClaudeSDKClient, agent: AgentPersona):
        self.client = client
        self.agent = agent
        self.lock = asyncio.Lock()

_clients: dict[str, _ClientEntry] = {}

# =============================================================================

def _get_registry_lock() -> asyncio.Lock:
    """
    Returns this platform's own registry lock, creating it on first use.

    Args:
        None

    Returns:
        asyncio.Lock:
            The lock guarding _clients dict mutation.
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
        - Never raises - a failed disconnect is logged but does not block whatever cleanup is happening around it.
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

async def _drop_entries_under(root: Path) -> None:
    """
    Removes and disconnects every client entry whose key is equal to, or nested under, root.

    Args:
        root (Path):
            The path every matching entry's own key must equal or fall under.

    Returns:
        None
    """
    root_str = str(root)
    prefix = root_str + "/"
    registry_lock = _get_registry_lock()
    async with registry_lock:
        matching_keys = [key for key in _clients if key == root_str or key.startswith(prefix)]
        entries = [_clients.pop(key) for key in matching_keys]

    for entry in entries:
        await _disconnect_entry(entry)

async def _get_or_create_entry(session_dir: Path) -> _ClientEntry:
    """
    Returns session_dir's own persistent Claude client entry, creating or recreating it if needed.

    Args:
        session_dir (Path):
            The generation directory this client is anchored to, and this registry's own lookup key.

    Returns:
        _ClientEntry:
            The (possibly newly-created) entry for session_dir.

    Notes:
        - A library file change since the entry was created triggers a disconnect-and-recreate.
        - Registry lookup/creation is serialised, so two concurrent first-use requests cannot both create a client.
    """
    key = str(session_dir)
    registry_lock = _get_registry_lock()
    async with registry_lock:
        # settings.CALL_NAME_CHAT hardcoded here, matching this module's own pre-existing fixed "chat.json"
        # lookup - not a new limitation introduced by the agent_persona.py move, see this module's own header
        # Notes. Was a bare "chat" string literal before settings.CALL_NAME_CHAT existed - same fixed value,
        # now sourced from one shared constant instead of its own separately-typed copy.
        agent = parse_agent(settings.LLM_TYPE_CLAUDE, settings.CALL_NAME_CHAT)
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
        - Serialised per-client for the whole query/response cycle, so two turns never overlap on one client.
        - Any failure drops this session_dir's entry entirely, so the next call starts completely fresh.
        - Token usage and ToolUseBlock/ToolResultBlock content are logged for diagnostic purposes only.
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
            Maximum seconds to wait for a reply before abandoning this call.

    Returns:
        str | None:
            The assistant's text reply, or None if the service isn't running, the call timed out, or it failed.

    Notes:
        - This platform's one public, caller-facing entry point - synchronous from the calling thread's own point of view.
        - Takes no persona - the client's own system prompt/tools/model come entirely from the library file.
        - A timeout evicts session_dir's entry from the registry, so the next call always builds a fresh client.
        - Never raises - every failure path is logged and returns None instead.
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
            # The abandoned _run_turn() coroutine may still be running on the service's own loop, still holding
            # session_dir's own entry.lock (see this function's own Notes above) - left alone, the *next* call
            # for this same session_dir would block waiting on that same lock, and could time out identically.
            # Evicting the entry here (fire-and-forget - not awaited, since this function has already exceeded
            # its own timeout budget) guarantees the next call always builds a fresh client/lock instead of
            # potentially queuing behind one that may never release. Mirrors _run_turn()'s own except-branch
            # cleanup (_drop_entry()) for every other failure mode - this was the one path missing it.
            asyncio.run_coroutine_threadsafe(_drop_entry(session_dir), _loop)
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
        - Exact-key match only - destroy_sessions_under() is the root-scoped equivalent used elsewhere.
        - A no-op if the service isn't running, or session_dir has no client to begin with.
    """
    if _loop is None:
        logger.debug(f"Claude session service is not running - nothing to destroy for session_dir={session_dir}.")
    else:
        future = asyncio.run_coroutine_threadsafe(_drop_entry(session_dir), _loop)
        try:
            future.result(timeout=settings.AGENT_SHUTDOWN_TIMEOUT_SECONDS)
        except Exception:
            logger.exception(f"Failed to cleanly destroy the persistent Claude client for session_dir={session_dir}.")

def destroy_sessions_under(root: Path) -> None:
    """
    Disconnects and discards every live Claude client whose key falls under root, if any exist.

    Args:
        root (Path):
            The session root, or a specific Call/LLM leaf beneath it, whose live client(s) should be destroyed.

    Returns:
        None

    Notes:
        - Root-scoped rather than a single exact-key match, since one session root can own several live clients.
        - A no-op if the service isn't running, or nothing under root has a live client.
    """
    if _loop is None:
        logger.debug(f"Claude session service is not running - nothing to destroy under root={root}.")
    else:
        future = asyncio.run_coroutine_threadsafe(_drop_entries_under(root), _loop)
        try:
            future.result(timeout=settings.AGENT_SHUTDOWN_TIMEOUT_SECONDS)
        except Exception:
            logger.exception(f"Failed to cleanly destroy persistent Claude client(s) under root={root}.")

def start_claude_session_service() -> None:
    """
    Starts this platform's own dedicated thread and persistent event loop, if not already running.

    Args:
        None

    Returns:
        None

    Notes:
        - No-op if already running.
        - The thread runs _loop.run_forever() and nothing else - all actual work is scheduled onto it separately.
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

    Returns:
        None

    Notes:
        - No-op if the service was never started/already stopped.
        - A client that fails to disconnect cleanly within timeout is logged and abandoned.
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
