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
#   - Persona/model/reasoning_effort are resolved internally by query_via_api(), via agent_persona.parse_agent(),
#     derived from session_dir, whenever session_dir is given - not passed in from any caller. See
#     _resolve_agent()'s own Notes.
#   - _DEFAULT_MODEL is only ever used as a fallback for a Call whose own libraries/deepseek/<call_name>.json
#     is empty/missing (today: architect/coder/review/documentation) - chat.json already overrides this
#     explicitly to "deepseek-v4-pro". Updated 2026-09-19 away from the legacy "deepseek-chat" name, which
#     was discontinued 2026-07-24 (a hard cutover, no fallback) - research-confirmed, not inferred.
#   - reasoning_effort is a DeepSeek-specific field with no dedicated AgentPersona attribute - read off
#     AgentPersona.persona (the raw parsed JSON parse_agent() already returns in full) instead, per-Call,
#     and passed straight through to the request body untouched (no validation against DeepSeek's own known
#     values low/medium/high/max/xhigh) - trusting the library file's content, same as model/tools elsewhere.
#     Omitted entirely from the request body when unset, so a Call with no reasoning_effort configured behaves
#     exactly as before this field existed (DeepSeek's own model-level default thinking effort applies).
#   - Session continuity is a local transcript file, since DeepSeek's /chat/completions is genuinely stateless -
#     no server-side conversation handle exists to key a marker off, unlike Claude's resume id/Qwen's
#     previous_response_id. Added 2026-09-19: session_dir's own .deepseek_transcript.json is read before every
#     call (persona + prior turns + this turn's own prompt are all sent together, since DeepSeek never
#     remembers anything itself) and appended to - the user's own turn, then the assistant's reply - only
#     after a confirmed successful call. A failed call leaves the persisted transcript untouched, same
#     convention Claude's/Qwen's own marker files already follow.
#   - Every stored/sent human turn uses role="user" and every reply uses role="assistant" - DeepSeek's
#     OpenAI-compatible /chat/completions endpoint only accepts "system"/"user"/"assistant"/"tool" as a message
#     role, so the persisted transcript uses that same vocabulary directly - no local-only role label, no
#     translation step needed between what's stored and what's sent. (An earlier revision stored the human
#     turn as role="session" instead, translated to "user" only when sent - removed same day, since it added
#     an indirection with no benefit; DeepSeek's own conversation model is inherently system+user/assistant,
#     not something this module can redefine.)
#   - The transcript is removed by four separate mechanisms, only the first two of which live in this module:
#     1. Size - DEEPSEEK_TRANSCRIPT_MAX_BYTES (config.py) bounds the persisted turns' own serialized size,
#        dropping the oldest complete turns first (the file itself is kept) - see _trim_transcript()'s own Notes.
#     2. Age - DEEPSEEK_SESSION_TTL_DAYS (config.py, default 2) discards the whole transcript once it is that old,
#        measured from its own original creation (absolute, not reset by activity), optionally rolled forward to
#        the next occurrence of the shared settings.SESSION_RESET_TIME when that is set - same design as
#        qwen_interface.py's own TTL, see _session_expiry_cutoff(). Added 2026-09-20.
#     3. Session reset - a telegram_gateway "refresh yourself" request, and the timed global reset when
#        SESSION_RESET_TIME is set.
#     4. Application startup.
#     3 and 4 are utils_session/session_worker.py's existing whole-directory wipe (shutil.rmtree()), which
#     removes this file for free along with everything else under session_dir - no clearing code lives here.
#   - The persisted file is a JSON object {"created_at": <ISO 8601>, "turns": [...]}, not a bare list, so the
#     original creation time survives across turns for the age check above. A bare-list file (the format used
#     for a few hours on 2026-09-19, before the age check existed) is treated as no history and replaced.
#   - query_via_api() is bounded by an outer asyncio.wait_for(_OUTER_TIMEOUT_SECONDS), mirroring the pattern
#     already implemented for Claude/Qwen. Both this and the inner urllib socket timeout are driven by the
#     shared settings.AGENT_QUERY_TIMEOUT_SECONDS Claude's own timeout also uses (outer = that value + 10s, so
#     the inner one fires first) - changed 2026-09-19 from a hardcoded, DeepSeek-scoped 60s/70s pair.
#   - See agent_interface.py for the provider-agnostic dispatch that selects this module.
#
# =============================================================================
# I M P O R T   H E A D E R

import json
import asyncio
import logging
import urllib.error
import urllib.request

from datetime import datetime, timedelta
from pathlib import Path

from ....config import settings
from ...utilities import application_time
from ..agent_persona import call_name_from_session_dir, parse_agent

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_API_URL = "https://api.deepseek.com/chat/completions"
_DEFAULT_MODEL = "deepseek-v4-flash"

# The outer asyncio-level ceiling wrapping the blocking HTTP call. Deliberately a little larger than
# settings.AGENT_QUERY_TIMEOUT_SECONDS (the inner urllib socket timeout, see _post_chat_completion()), not equal
# to it, so the inner timeout fires first and returns cleanly. Both are driven by the same shared setting
# Claude's own timeout uses, changed from a hardcoded 60s 2026-09-19.
_OUTER_TIMEOUT_SECONDS = settings.AGENT_QUERY_TIMEOUT_SECONDS + 10

# Marker file this module reads/writes inside a given session_dir to remember DeepSeek's own conversation
# history across separate query_via_api() calls - see _read_transcript()/_write_transcript(). Colocated with
# session_dir deliberately, not tracked anywhere else, so clear_session_directory()'s existing whole-tree
# removal (utils_session/session_worker.py) already clears it for free on a session_cleared/global reset - no
# extra clearing logic needed for this file, same conclusion already reached for Claude's/Qwen's own marker
# files.
_TRANSCRIPT_FILENAME = ".deepseek_transcript.json"

# =============================================================================

def _session_expiry_cutoff(created_at: datetime) -> datetime:
    """
    Computes the moment a transcript created at created_at should be treated as expired.

    Args:
        created_at (datetime):
            The transcript's own originally-recorded creation time (timezone-aware, settings.TZ).

    Returns:
        datetime:
            created_at plus settings.DEEPSEEK_SESSION_TTL_DAYS, optionally rolled forward to the next occurrence
            of settings.SESSION_RESET_TIME if one is configured.

    Notes:
        - settings.SESSION_RESET_TIME is unset (None) by default - the raw day-count cutoff is used as-is until
          a specific wall-clock time is configured. It is the same shared setting the global timed session reset
          and qwen_interface.py's own TTL use, not a DeepSeek-specific one.
        - When a specific time is configured, the cutoff is rolled forward (never backward) to the next
          occurrence on/after the raw day-count cutoff - same rule as qwen_interface.py::_session_expiry_cutoff().
          That function is duplicated here rather than shared, since it reads its own provider's TTL setting and
          extracting a shared helper would have meant changing qwen_interface.py - see CODE_TODO.md.
    """
    cutoff = created_at + timedelta(days=settings.DEEPSEEK_SESSION_TTL_DAYS)
    if settings.SESSION_RESET_TIME is not None:
        aligned = cutoff.replace(hour=settings.SESSION_RESET_TIME.hour, minute=settings.SESSION_RESET_TIME.minute, second=0, microsecond=0)
        if aligned < cutoff:
            aligned += timedelta(days=1)
        cutoff = aligned
    return cutoff

def _read_transcript(session_dir: Path | None) -> dict:
    """
    Reads session_dir's own persisted DeepSeek transcript, if one exists and is not locally expired.

    Args:
        session_dir (Path | None):
            The working-directory anchor to check. None if this call has no session_dir at all.

    Returns:
        dict:
            {"turns": list[dict], "created_at": datetime | None}. "turns" is the remembered history (a list of
            {"role", "content"} entries, role one of "user"/"assistant"), oldest first. "created_at" is when the
            transcript was first created. Both are empty/None together - never one without the other - if
            session_dir is None, no file exists, the file is unreadable/malformed/in the old bare-list format,
            or the transcript is expired (see _session_expiry_cutoff()).

    Notes:
        - Never raises - any read/parse problem is treated the same as "no history to resume from".
        - An expired transcript is logged at info and treated identically to no file at all. It is not deleted
          here - the next successful call overwrites it with a fresh transcript.
        - A fresh dict is built for every return, never a shared one - the caller appends to "turns".
    """
    if session_dir is None:
        return {"turns": [], "created_at": None}

    path = session_dir / _TRANSCRIPT_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"turns": [], "created_at": None}
    except (OSError, json.JSONDecodeError):
        logger.exception(f"Failed to read DeepSeek transcript at session_dir={session_dir} - starting with an empty transcript instead.")
        return {"turns": [], "created_at": None}

    turns = data.get("turns") if isinstance(data, dict) else None
    created_at_raw = data.get("created_at") if isinstance(data, dict) else None
    if not isinstance(turns, list) or not created_at_raw:
        logger.info(f"DeepSeek transcript at session_dir={session_dir} is not in the expected {{created_at, turns}} format (an older bare-list file, or malformed) - starting with an empty transcript instead.")
        return {"turns": [], "created_at": None}

    try:
        created_at = datetime.fromisoformat(created_at_raw)
    except ValueError:
        logger.warning(f"DeepSeek transcript at session_dir={session_dir} has an unparsable created_at={created_at_raw!r} - starting with an empty transcript instead.")
        return {"turns": [], "created_at": None}

    if application_time() >= _session_expiry_cutoff(created_at):
        logger.info(f"DeepSeek transcript at session_dir={session_dir} exceeded its local TTL (created_at={created_at.isoformat()}, DEEPSEEK_SESSION_TTL_DAYS={settings.DEEPSEEK_SESSION_TTL_DAYS}) - starting with an empty transcript instead.")
        return {"turns": [], "created_at": None}

    return {"turns": turns, "created_at": created_at}

def _transcript_size_bytes(turns: list[dict]) -> int:
    """
    Measures turns' own serialized size in bytes, as it would be persisted to disk.

    Args:
        turns (list[dict]):
            The transcript's turns to measure.

    Returns:
        int:
            The UTF-8 byte length of turns' own JSON serialisation.

    Notes:
        - A byte-size proxy, not a token-accurate measurement - no DeepSeek tokenizer is vendored here. Treated
          as a safety net against unbounded growth, not a precise cost/context budget.
        - Measures the turns list only, not the small {"created_at", "turns"} wrapper the file adds around it
          (a few dozen bytes) - negligible against a cap in the hundreds of kilobytes.
    """
    return len(json.dumps(turns).encode("utf-8"))

def _trim_transcript(turns: list[dict]) -> list[dict]:
    """
    Drops the oldest complete turns from turns until its own serialized size is at/under
    settings.DEEPSEEK_TRANSCRIPT_MAX_BYTES.

    Args:
        turns (list[dict]):
            The transcript's turns to trim, oldest first - each turn is always exactly two entries (one
            role="user" human turn, immediately followed by its paired role="assistant" reply), appended
            together by query_via_api() - see this module's own header Notes.

    Returns:
        list[dict]:
            turns, with zero or more of its oldest turns removed.

    Notes:
        - Trims in whole turns (two entries at a time), never a lone half-turn - keeps every remaining "user"
          entry paired with its own "assistant" reply, so a resent transcript never starts mid-turn.
        - Never trims below the single most-recently-appended turn, even if that turn alone exceeds the cap -
          this is a safety net against unbounded growth over time, not a guarantee every request stays under
          the cap regardless of how large one single turn is.
        - Removes entries from the list it is given, in place, as well as returning it.
    """
    while len(turns) > 2 and _transcript_size_bytes(turns) > settings.DEEPSEEK_TRANSCRIPT_MAX_BYTES:
        # Each interaction consist of user and response, so remove two entries at a time to keep the transcript consistent.
        del turns[0:2]
    return turns

def _write_transcript(session_dir: Path | None, turns: list[dict], created_at: datetime | None) -> None:
    """
    Persists turns as session_dir's own latest DeepSeek conversation history, for a future call to resume from.

    Args:
        session_dir (Path | None):
            The working-directory anchor to write into. A no-op if None.

        turns (list[dict]):
            The full turn history to persist, oldest first - trimmed (see _trim_transcript()) before writing,
            so the file on disk never grows past settings.DEEPSEEK_TRANSCRIPT_MAX_BYTES going forward.

        created_at (datetime | None):
            The transcript's own original creation time to preserve, if this turn continued an existing,
            not-yet-expired transcript. None means this turn started a fresh transcript - application_time() is
            recorded as the new creation time.

    Returns:
        None

    Notes:
        - Only called after a confirmed-successful call, so a failed call leaves the prior transcript in place.
        - created_at is deliberately preserved rather than refreshed on every successful turn - the TTL is an
          absolute age from first creation, not a sliding one reset by activity, same as Qwen's.
        - Best-effort - a write failure is logged but non-fatal.
    """
    if session_dir is None:
        return
    else:
        payload = {"created_at": (created_at or application_time()).isoformat(), "turns": _trim_transcript(turns)}
        try:
            (session_dir / _TRANSCRIPT_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            logger.exception(f"Failed to persist DeepSeek transcript for session_dir={session_dir} - the next call in this generation will resume from the prior, un-appended transcript instead.")

def _post_chat_completion(messages: list[dict], token: str, model: str, reasoning_effort: str | None) -> str | None:
    """
    Posts a single chat completion request to the DeepSeek API and returns the reply text.

    Args:
        messages (list[dict]):
            The full message list to send - persona (if any) + prior turns (if any) + this turn's own prompt,
            already assembled by the caller. See query_via_api()'s own Notes.

        token (str):
            The DeepSeek API key.

        model (str):
            The DeepSeek model to query - resolved by the caller via _resolve_agent(), never hardcoded here.

        reasoning_effort (str | None):
            Optional DeepSeek-specific reasoning-effort level (e.g. "high") - omitted from the request body
            entirely when None, rather than sending an explicit default. See this module's own header Notes.

    Returns:
        str | None:
            The assistant's reply text, or None if the request failed or returned no content.

    Notes:
        - Synchronous/blocking - only ever called via asyncio.to_thread().
    """
    request_payload = {
        "model": model,
        "messages": messages,
        "stream": False
    }
    if reasoning_effort:
        request_payload["reasoning_effort"] = reasoning_effort

    body = json.dumps(request_payload).encode("utf-8")

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
        with urllib.request.urlopen(request, timeout=settings.AGENT_QUERY_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"] or None
    except urllib.error.HTTPError as error:
        logger.error(f"DeepSeek API returned HTTP {error.code}: {error.read().decode(errors='replace').strip()}")
        return None
    except Exception:
        logger.exception("DeepSeek query failed - credential may be invalid/expired, the response was malformed, or the endpoint is unreachable.")
        return None

def _resolve_agent(persona: str | None, session_dir: Path | None) -> dict:
    """
    Resolves this call's own persona/model/reasoning_effort, locally, right before querying.

    Args:
        persona (str | None):
            Fallback persona text, used only when session_dir is None.

        session_dir (Path | None):
            Working-directory anchor for this call - see call_name_from_session_dir()'s own Notes for the
            directory shape this is derived from.

    Returns:
        dict:
            {"persona": str | None, "model": str, "reasoning_effort": str | None}. session_dir's own resolved
            persona/model/reasoning_effort if session_dir is given and a call_name can be derived from it;
            otherwise {"persona": persona, "model": _DEFAULT_MODEL, "reasoning_effort": None} unchanged.

    Notes:
        - reasoning_effort has no dedicated AgentPersona attribute - read off AgentPersona.persona (the raw
          parsed JSON parse_agent() already returns in full) instead. See this module's own header Notes.
        - Renamed from _resolve_persona() 2026-09-19, once model/reasoning_effort also needed resolving here
          rather than being hardcoded - previously the first real use of session_dir (née cwd) in this module;
          still true. Changed from a positional tuple return to a named dict 2026-09-19, so each of the three
          resolved values is read by name at the call site rather than by unpacking position.
    """
    call_name = call_name_from_session_dir(session_dir)
    if call_name is None:
        return {"persona": persona, "model": _DEFAULT_MODEL, "reasoning_effort": None}
    else:
        agent = parse_agent(settings.LLM_TYPE_DEEPSEEK, call_name)
        return {
            "persona": agent.body or persona,
            "model": agent.model or _DEFAULT_MODEL,
            "reasoning_effort": agent.persona.get("reasoning_effort") or None
        }

async def query_via_api(prompt: str, token: str, persona: str | None = None, session_dir: Path | None = None) -> str | None:
    """
    Sends a prompt to DeepSeek, authenticated via a DeepSeek API key.

    Args:
        prompt (str):
            The prompt to send.

        token (str):
            The DeepSeek API key.

        persona (str | None):
            Fallback persona/system prompt, used only when session_dir is None - see _resolve_agent()'s own Notes.

        session_dir (Path | None):
            Working-directory anchor for this call - drives this call's own persona/model/reasoning_effort
            resolution (see _resolve_agent()) and its own transcript-based session continuity (see
            _read_transcript()/_write_transcript()).

    Returns:
        str | None:
            The assistant's text reply, or None on failure/timeout.

    Notes:
        - Runs the blocking HTTP call in a worker thread, bounded by an outer asyncio.wait_for(), so neither
          a stalled event loop nor an unbounded hang is possible - mirrors Claude's/Qwen's own equivalent
          timeout handling, driven by the same shared settings.AGENT_QUERY_TIMEOUT_SECONDS.
        - messages sent = persona (if any, as "system") + every prior turn in session_dir's own transcript (if
          any, as-is - already role="user"/"assistant") + this turn's own prompt (as "user") - DeepSeek never
          remembers anything itself, so the full history is resent on every call, same as any other stateless
          /chat/completions request. See this module's own header Notes for the transcript-file design.
        - The transcript is only appended to and persisted after a confirmed-successful reply - a failed call
          leaves session_dir's own persisted transcript untouched, so the next attempt resumes from the same
          point rather than from a broken/partial state.
    """
    agent = _resolve_agent(persona, session_dir)
    transcript = _read_transcript(session_dir)

    messages = []
    # Add persona if exists - DeepSeek expects it as a leading "system" role message, not concatenated into prompt.
    if agent["persona"]:
        messages.append({"role": "system", "content": agent["persona"]})
    # Add past conversation into messages to maintain context
    messages.extend(transcript["turns"])
    # Add new user prompt to messages
    messages.append({"role": "user", "content": prompt})

    try:
        reply = await asyncio.wait_for(asyncio.to_thread(_post_chat_completion, messages, token, agent["model"], agent["reasoning_effort"]), timeout=_OUTER_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.error(f"DeepSeek query for session_dir={session_dir} exceeded {_OUTER_TIMEOUT_SECONDS}s - abandoning it.")
        return None

    if reply is not None:
        transcript["turns"].append({"role": "user", "content": prompt})
        transcript["turns"].append({"role": "assistant", "content": reply})
        _write_transcript(session_dir, transcript["turns"], transcript["created_at"])

    return reply

async def query_via_oauth(prompt: str, token: str, persona: str | None = None, session_dir: Path | None = None) -> str | None:
    """
    Not supported - DeepSeek has no OAuth/CLI login mechanism.

    Args:
        prompt (str):
            Unused - accepted only to match this module's expected two-endpoint shape.

        token (str):
            Unused, same reason.

        persona (str | None):
            Unused, same reason.

        session_dir (Path | None):
            Unused, same reason.

    Returns:
        str | None:
            Always None.
    """
    logger.warning("LLM_DEEPSEEK_ACCESS_TYPE=\"OAUTH\" is not supported - DeepSeek is API-key-only. Set LLM_DEEPSEEK_ACCESS_TYPE=\"API\" instead.")
    return None

# =============================================================================
