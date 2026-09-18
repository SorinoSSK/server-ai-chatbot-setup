# =============================================================================
# File        : qwen_interface.py
# Description : Interfaces with Qwen via DashScope's OpenAI-compatible Responses API, with previous_response_id-based session continuity.
# Author      : SorinoSSK
# Created On  : 2026-09-10
#
# Features    :
#   - query_via_api()   - sends a prompt to Qwen, authenticated via a DashScope (or compatible) API key.
#   - query_via_oauth() - not supported; always logs and returns None (see Notes).
#   - Session continuity via DashScope's own previous_response_id, remembered in a per-session_dir marker file and subject to this application's own, stricter local TTL (settings.QWEN_SESSION_TTL_DAYS).
#
# Notes       :
#   - Qwen is API-key-only today - its former free OAuth login tier was discontinued.
#   - No Qwen/DashScope Python SDK exists, so this calls its OpenAI-compatible REST endpoint directly via stdlib urllib, wrapped in asyncio.to_thread().
#   - _RESPONSES_API_URL defaults to DashScope's international endpoint. _DEFAULT_MODEL is the fallback model
#     string used whenever a Call has no "model" field of its own - both are unverified against a real
#     account, see CODE_TODO.md.
#   - persona is delivered as the Responses API's own "instructions" field, resent on every call (including
#     resumed ones) - deliberately not folded into "input", since previous_response_id only carries the raw
#     conversation forward, not any prior top-level instructions (confirmed via documentation research, not
#     empirically - see CODE_TODO.md).
#   - persona/model/session continuity are all resolved internally by query_via_api(), via
#     agent_persona.parse_agent()/the session marker file, derived from session_dir whenever one is given -
#     none of this is passed in from any caller.
#   - session_dir is the same already-existing, already-created directory chat_call.py's own
#     query_llm(..., session_dir=call_session_dir) passes to every provider - <SESSION_DIR>/<session_id>/chat/qwen
#     in practice today (the third path segment tracks whichever provider LLM_CHAT_TYPE currently names) -
#     not a working directory in the os.getcwd() sense, despite this module's own local variable naming before
#     this revision (see CODE_TODO.md for the cwd -> session_dir rename).
#   - Session continuity uses previous_response_id rather than resending full message history, mirroring
#     claude_interface.py's own resume=<session_id> marker-file approach in spirit (see that module's Notes)
#     but against a different underlying mechanism - DashScope stores the conversation server-side for its own
#     7-day TTL, this module never sees or stores the actual conversation content itself, only the response id.
#   - The local marker file (_SESSION_MARKER_FILENAME) lives inside session_dir, the same directory
#     claude_interface.py's own .claude_session_id marker lives in for the Claude-backed "chat" Call - so
#     utils_session/session_worker.py's existing whole-directory clearing (clear_all_session_directories() at
#     every application startup, and clear_session_directory() on a telegram_gateway-triggered session_reset)
#     already removes it for free. No new clearing logic was added anywhere for this - see CODE_TODO.md.
#   - The local TTL (settings.QWEN_SESSION_TTL_DAYS, default 2) is deliberately stricter than DashScope's own
#     7-day server-side context TTL, and is treated as an absolute session age from the marker's own original
#     creation - a continuously active conversation still expires 2 days after it first began, it does not
#     reset on every reply. This was a deliberate choice, not the only option (a sliding TTL that resets on
#     every turn was the alternative) - see CODE_TODO.md if this needs revisiting.
#   - The local TTL is a plain day-count cutoff and is not aligned to settings.SESSION_RESET_TIME. The scheduled reset already removes the whole session_dir, marker included, so the TTL is only a backstop for when no reset is configured, one is skipped, or its clearing fails. Alignment was removed 2026-09-20 - see CODE_TODO.md.
#   - Whether DashScope's own rejection of an invalid/expired previous_response_id is reliably detectable via
#     _is_expired_previous_response_error()'s heuristic is unconfirmed against a real account - see that
#     function's own Notes and CODE_TODO.md.
#   - Transient failures (HTTP 500/502/503/504, connection-level errors other than a timeout, and a response body cut short mid-read - http.client.IncompleteRead) are retried by api_retry.py::run_with_retry(), which wraps each asyncio.wait_for() call, so every attempt gets its own _OUTER_TIMEOUT_SECONDS bound. _post_response() only classifies the failure ("retryable") and never retries itself. HTTP 429 is deliberately not retried for Qwen, unlike DeepSeek - DashScope's 429s are per-minute RPM/TPM quotas (its docs say to wait a few minutes), traffic-burst limits and exhausted quotas, so a 2-4s backoff would rarely succeed and would only delay the failure by about 6s. The X-DashScope-Wait-Timeout request header (server-side queuing for burst limits) was considered and not adopted - see CODE_TODO.md. A timeout, inner or outer, is never retried, and exhausted retries return None exactly as any other failure always has. Independent of the previous_response_id fresh-conversation retry below, which is a 400/404 and so never retryable here - in the rare case both fire, each gets its own full set of attempts. Added 2026-09-20.
#   - An exhausted quota (HTTP 429 with insufficient_quota in the body) is never retried, even though it is a 429, and is the one failure that does not return None - query_via_api() returns agent_errors.billing_exhausted_response() instead, an "error" tool reply dict (error_type="billing_exhausted") that flows through call_dispatch_handler.py::message_dissect() like an agent's own error reply. Every other failure still returns None. DashScope's overdue-account response is not detected - its status and code are unconfirmed, see CODE_TODO.md. Added 2026-09-20.
#   - A successful call logs DashScope's own usage block (token counts) at info, with the model, so cost can be tracked from the log alone. Log-only, and logged as-is since its exact shape is unverified. Retry log lines carry the session_dir. Both added 2026-09-20.
#   - A 200 response whose reply is empty, whose "error" field is set, or whose "status" is failed/incomplete/cancelled is logged at warning with those fields. Log-only - the reply is still returned or None exactly as before, and it is never retried. The status values are the OpenAI Responses convention, unconfirmed against a real DashScope response. Added 2026-09-20.
#   - The session marker read-modify-write in query_via_api() takes no lock. Each session has one SessionWorker thread (utils_session/session_worker.py) that runs its turns one at a time, and call_dispatch_handler.py runs each turn's hops sequentially, so two calls for the same session_dir do not overlap in normal operation or during a global reset sweep. One known exception: utils_queue/message_handler.py::_handle_session_cleared() removes the worker from the registry before retire() lets its in-flight turn finish, so a message arriving in that window creates a second worker for the same session_id and session_dir. The two turns can then overlap here, and the first worker's cleanup afterwards removes the second worker's registry entry and wipes the shared directory. The cause is in session_worker.py/message_handler.py, and a lock in this file would only cover the overlap, not the wipe - see CODE_TODO.md. Checked by reading the code 2026-09-20.
#   - See agent_interface.py for the provider-agnostic dispatch that selects this module.
#
# =============================================================================
# I M P O R T   H E A D E R

import json
import asyncio
import logging
import http.client
import urllib.error
import urllib.request

from datetime import datetime, timedelta
from pathlib import Path

from ....config import settings
from ...utilities import application_time
from ..agent_persona import call_name_from_session_dir, parse_agent
from ..agent_errors import billing_exhausted_response, is_billing_failure
from ..api_retry import RETRYABLE_STATUS_CODES, run_with_retry

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_RESPONSES_API_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/responses"
_DEFAULT_MODEL = "qwen-plus"

# The HTTP statuses this module treats as transient - the shared set minus 429. DashScope's 429s are per-minute RPM/TPM quotas, traffic-burst limits or an exhausted quota, none of which a 2-4s backoff reliably clears, so retrying them mostly delays the failure by about 6s. See this module's own header Notes.
_RETRYABLE_STATUS_CODES = RETRYABLE_STATUS_CODES - {429}

# The outer asyncio-level ceiling wrapping the blocking HTTP call. Deliberately a little larger than
# settings.AGENT_QUERY_TIMEOUT_SECONDS (the inner urllib socket timeout, see _post_response()), not equal to it -
# in the normal/expected case the inner timeout fires first, is caught inside _post_response(), and returns a
# clean {"reply": None, ...} dict. This outer one is a safety net for cases the inner socket timeout doesn't
# cover on its own (e.g. thread-pool scheduling delay under load) - see CODE_TODO.md. Both are driven by the
# same shared setting Claude's own timeout uses, changed from a hardcoded 60s 2026-09-19.
_OUTER_TIMEOUT_SECONDS = settings.AGENT_QUERY_TIMEOUT_SECONDS + 10

# Marker file this module reads/writes inside a given session_dir to remember Qwen's own previous_response_id
# (and this application's own locally-tracked creation time) across separate query_via_api() calls - see
# _read_session_marker()/_write_session_marker(). Colocated with session_dir deliberately, not tracked
# anywhere else - see this module's own header Notes for why that means no new clearing logic was needed.
_SESSION_MARKER_FILENAME = ".qwen_session.json"

# =============================================================================

def _extract_output_text(payload: dict) -> str | None:
    """
    Extracts the assistant's reply text from a Responses API response envelope.

    Args:
        payload (dict):
            The decoded JSON response body.

    Returns:
        str | None:
            The reply text, or None if the response carried no usable text.

    Notes:
        - Prefers the envelope's own top-level "output_text" convenience field (the OpenAI Responses API
          convention DashScope documents itself as mirroring). Falls back to walking "output" (a list of
          message items, each with its own "content" list of typed parts) if "output_text" is absent -
          unverified against a real account which shape DashScope actually returns in practice, see CODE_TODO.md.
    """
    output_text = payload.get("output_text")
    if output_text:
        return output_text
    else:
        parts: list[str] = []
        for item in payload.get("output") or []:
            for content in item.get("content") or []:
                text = content.get("text")
                if text:
                    parts.append(text)
        return "".join(parts) or None

def _is_expired_previous_response_error(status_code: int, body_text: str) -> bool:
    """
    Best-effort heuristic deciding whether an HTTPError was caused specifically by an invalid/expired previous_response_id.

    Args:
        status_code (int):
            The HTTP status code DashScope returned.

        body_text (str):
            The raw (decoded) error response body.

    Returns:
        bool:
            True if this looks like an invalid/expired previous_response_id, specifically; False for every
            other request problem (bad model, bad token, malformed prompt, etc.).

    Notes:
        - DashScope's exact error shape for this specific condition is unconfirmed against a real account (no
          execution access available in this environment - see CODE_TODO.md). This checks for a 4xx status
          whose own body text mentions "response_id" - a reasonable guess, not a documented contract. Refine
          once real traffic surfaces the actual error format.
        - Deliberately narrow (status code AND keyword, not status code alone) - a bare 400 is also what a bad
          model string or malformed request would return, and those should not be treated as "start fresh",
          they should surface as an ordinary failure.
    """
    return status_code in (400, 404) and "response_id" in body_text.lower()

def _post_response(prompt: str, token: str, persona: str | None, model: str, previous_response_id: str | None) -> dict:
    """
    Posts a single request to DashScope's OpenAI-compatible Responses endpoint and returns the outcome.

    Args:
        prompt (str):
            The new user message for this turn only - never the full conversation history, since
            previous_response_id (when given) already carries that forward server-side.

        token (str):
            The DashScope (or compatible) API key.

        persona (str | None):
            Optional persona/system instructions for this call - sent as "instructions", not "input", so it
            applies on every turn regardless of previous_response_id (see this module's own header Notes).

        model (str):
            Which DashScope model string to request - see _resolve_agent()'s own Notes for how this is resolved.

        previous_response_id (str | None):
            The prior turn's own response id to resume from, if any and not locally expired.

    Returns:
        dict:
            {"reply": str | None, "response_id": str | None, "previous_response_id_rejected": bool, "retryable": bool, "billing_failure": bool} -
            "reply"/"response_id" are None on any failure. "previous_response_id_rejected" is True only when
            the failure looks specifically like DashScope rejecting previous_response_id itself (see
            _is_expired_previous_response_error()) - it is always False when previous_response_id was None to
            begin with, since there was nothing to reject.
            "retryable" is True only for a transient failure (see _RETRYABLE_STATUS_CODES, which excludes 429, a connection-level error that is not a timeout, or an http.client.IncompleteRead while reading a successful response body) and is consumed by api_retry.py::run_with_retry(), not by this module's own callers. "billing_failure" is True only when the account's quota is exhausted (see agent_errors.is_billing_failure()) - such a failure is never retryable, and query_via_api() returns billing_exhausted_response() on it.

    Notes:
        - Synchronous/blocking - only ever called via asyncio.to_thread().
        - Changed from a positional tuple return to a named dict 2026-09-19, so each of the three outcome
          values is read by name at the call site rather than by unpacking position.
    """
    body_payload: dict = {
        "model": model,
        "input": [{"role": "user", "content": prompt}],
        "stream": False
    }
    if persona:
        body_payload["instructions"] = persona
    if previous_response_id:
        body_payload["previous_response_id"] = previous_response_id

    body = json.dumps(body_payload).encode("utf-8")

    request = urllib.request.Request(
        _RESPONSES_API_URL,
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
        logger.info(f"Qwen (DashScope) usage: model={model} usage={payload.get('usage')}")
        reply = _extract_output_text(payload)
        status = payload.get("status")
        error = payload.get("error")
        if reply is None or error or status in ("failed", "incomplete", "cancelled"):
            logger.warning(f"Qwen (DashScope) returned HTTP 200 but the reply looks failed, incomplete or empty: model={model} status={status!r} error={error!r} incomplete_details={payload.get('incomplete_details')!r} reply_empty={reply is None}.")
        return {"reply": reply, "response_id": payload.get("id") or None, "previous_response_id_rejected": False, "retryable": False, "billing_failure": False}
    except urllib.error.HTTPError as error:
        body_text = error.read().decode(errors="replace").strip()
        logger.error(f"Qwen (DashScope) Responses API returned HTTP {error.code}: {body_text}")
        rejected = previous_response_id is not None and _is_expired_previous_response_error(error.code, body_text)
        billing_failure = is_billing_failure(error.code, body_text)
        return {"reply": None, "response_id": None, "previous_response_id_rejected": rejected, "retryable": error.code in _RETRYABLE_STATUS_CODES, "billing_failure": billing_failure}
    except (urllib.error.URLError, ConnectionError, http.client.IncompleteRead) as error:
        reason = getattr(error, "reason", error)
        logger.error(f"Qwen request failed at the connection level: {reason!r}")
        return {"reply": None, "response_id": None, "previous_response_id_rejected": False, "retryable": not isinstance(reason, TimeoutError), "billing_failure": False}
    except Exception:
        logger.exception("Qwen query failed - credential may be invalid/expired, the response was malformed, or the endpoint is unreachable.")
        return {"reply": None, "response_id": None, "previous_response_id_rejected": False, "retryable": False, "billing_failure": False}

def _resolve_agent(persona: str | None, session_dir: Path | None) -> dict:
    """
    Resolves this call's own persona text and model string, locally, right before querying.

    Args:
        persona (str | None):
            Fallback persona text, used only when session_dir is None.

        session_dir (Path | None):
            Working-directory anchor for this call - see call_name_from_session_dir()'s own Notes for the
            directory shape this is derived from.

    Returns:
        dict:
            {"persona": str | None, "model": str} - session_dir's own resolved persona body and model string
            if session_dir is given and a call_name can be derived from it; otherwise {"persona": persona,
            "model": _DEFAULT_MODEL} unchanged/as given.

    Notes:
        - Resolves persona and model from a single parse_agent() call rather than one each, to avoid reading
          and parsing the same library file twice per query.
        - _DEFAULT_MODEL is also the fallback whenever call_name resolves but that Call's own library file has
          no "model" field of its own (parse_agent() tolerates a missing field silently, per-field, returning
          model=None rather than raising) - e.g. every Qwen Call other than "chat" is still an empty
          placeholder library file today, so all of them fall back to _DEFAULT_MODEL until written.
        - Changed from a positional tuple return to a named dict 2026-09-19, so each of the two resolved
          values is read by name at the call site rather than by unpacking position.
    """
    call_name = call_name_from_session_dir(session_dir)
    if call_name is None:
        return {"persona": persona, "model": _DEFAULT_MODEL}
    else:
        agent = parse_agent(settings.LLM_TYPE_QWEN, call_name)
        return {"persona": agent.body, "model": agent.model or _DEFAULT_MODEL}

def _session_expiry_cutoff(created_at: datetime) -> datetime:
    """
    Computes the moment a session marker created at created_at should be treated as locally expired.

    Args:
        created_at (datetime):
            The marker's own originally-recorded creation time (timezone-aware, settings.TZ).

    Returns:
        datetime:
            created_at plus settings.QWEN_SESSION_TTL_DAYS.

    Notes:
        - Deliberately not aligned to settings.SESSION_RESET_TIME. The scheduled reset (utils_session/session_worker.py::trigger_timed_session_reset()) already removes the whole session_dir, this marker included, so the TTL is only a backstop for when no reset is configured, one is skipped, or its clearing fails. Alignment was removed 2026-09-20 - see CODE_TODO.md.
    """
    return created_at + timedelta(days=settings.QWEN_SESSION_TTL_DAYS)

def _read_session_marker(session_dir: Path | None) -> dict:
    """
    Reads session_dir's own remembered Qwen previous_response_id, if one exists and is not locally expired.

    Args:
        session_dir (Path | None):
            The working-directory anchor to check. None if this call has no session_dir at all.

    Returns:
        dict:
            {"response_id": str | None, "created_at": datetime | None} - both None if session_dir is None, no
            marker exists, the marker is malformed/unreadable, or the marker is locally expired (see
            _session_expiry_cutoff()). Both are always None together, never independently - callers may rely
            on that.

    Notes:
        - Never raises - any read/parse problem is treated the same as "nothing to resume from".
        - A locally-expired marker is logged at info and treated identically to no marker at all - the
          server-side previous_response_id may well still be valid (DashScope's own TTL is 7 days), this
          application simply chooses not to trust it past its own, stricter cutoff.
        - Changed from a positional tuple return to a named dict 2026-09-19, so each of the two resolved
          values is read by name at the call site rather than by unpacking position.
    """
    if session_dir is None:
        return {"response_id": None, "created_at": None}
    else:
        marker = session_dir / _SESSION_MARKER_FILENAME
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"response_id": None, "created_at": None}
        except (OSError, json.JSONDecodeError):
            logger.exception(f"Failed to read Qwen session marker at session_dir={session_dir} - starting a fresh conversation instead of resuming.")
            return {"response_id": None, "created_at": None}

        response_id = data.get("response_id") or None
        created_at_raw = data.get("created_at")
        if response_id is None or not created_at_raw:
            return {"response_id": None, "created_at": None}
        else:
            try:
                created_at = datetime.fromisoformat(created_at_raw)
            except ValueError:
                logger.warning(f"Qwen session marker at session_dir={session_dir} has an unparsable created_at={created_at_raw!r} - starting a fresh conversation instead of resuming.")
                return {"response_id": None, "created_at": None}

            if application_time() >= _session_expiry_cutoff(created_at):
                logger.info(f"Qwen session marker at session_dir={session_dir} exceeded its local TTL (created_at={created_at.isoformat()}, QWEN_SESSION_TTL_DAYS={settings.QWEN_SESSION_TTL_DAYS}) - starting a fresh conversation instead of resuming.")
                return {"response_id": None, "created_at": None}
            else:
                return {"response_id": response_id, "created_at": created_at}

def _write_session_marker(session_dir: Path | None, response_id: str | None, created_at: datetime | None) -> None:
    """
    Remembers response_id (and its own session's original creation time) as session_dir's own latest Qwen session.

    Args:
        session_dir (Path | None):
            The working-directory anchor to write into. A no-op if None.

        response_id (str | None):
            The response id captured from this call's own successful reply. A no-op if None/empty.

        created_at (datetime | None):
            The session's own original creation time to preserve, if this turn continued an existing,
            not-yet-locally-expired session (i.e. previous_response_id was actually used). None means this
            turn started a fresh conversation - application_time() is recorded as the new creation time.

    Returns:
        None

    Notes:
        - Only called after a confirmed-successful call, so a failed call leaves the prior marker in place.
        - created_at is deliberately preserved rather than refreshed on every successful turn - the local TTL
          is an absolute session age from first creation, not a sliding one reset by activity. See this
          module's own header Notes if that decision needs revisiting.
        - Best-effort - a write failure is logged but non-fatal.
    """
    if session_dir is None or not response_id:
        return
    else:
        payload = {"response_id": response_id, "created_at": (created_at or application_time()).isoformat()}
        try:
            (session_dir / _SESSION_MARKER_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            logger.exception(f"Failed to persist Qwen session marker for session_dir={session_dir} - the next call at this session_dir will start a fresh conversation instead of resuming.")

async def query_via_api(prompt: str, token: str, persona: str | None = None, session_dir: Path | None = None) -> str | dict | None:
    """
    Sends a prompt to Qwen, authenticated via a DashScope (or compatible) API key.

    Args:
        prompt (str):
            The prompt to send.

        token (str):
            The DashScope (or compatible) API key.

        persona (str | None):
            Fallback persona/system prompt, used only when session_dir is None - see _resolve_agent()'s own Notes.

        session_dir (Path | None):
            Working-directory anchor for this call - drives this call's own persona/model resolution (see
            _resolve_agent()) and its own session continuity (see _read_session_marker()/_write_session_marker()).

    Returns:
        str | dict | None:
            The assistant's text reply; an "error" tool reply dict if the account's quota is exhausted; or None on any other failure.

    Notes:
        - Runs the blocking HTTP call in a worker thread so it doesn't stall the event loop, bounded by
          _OUTER_TIMEOUT_SECONDS - see that constant's own Notes for why it's not equal to the inner
          per-request socket timeout.
        - A previous_response_id DashScope itself rejects as invalid/expired (previous_response_id_rejected)
          is retried once, immediately, as a fresh conversation - the end user gets a reply for this turn
          either way, rather than the whole call failing outright over a continuity mechanism they have no
          visibility into. See _is_expired_previous_response_error()'s own Notes on how this is detected.
        - A transient failure is retried by api_retry.py::run_with_retry(), which wraps each asyncio.wait_for() attempt, including the fresh-conversation one above - see this module's own header Notes. The return value is unchanged, still the reply text or None.
        - Returns agent_errors.billing_exhausted_response() (a dict, not text, and never None) when DashScope reports the account's quota as exhausted, on either the normal or the fresh-conversation request. No session marker is written for it. That is the one case where this function returns a dict rather than str | None - see agent_errors.py.
    """
    agent = _resolve_agent(persona, session_dir)
    session_marker = _read_session_marker(session_dir)
    previous_response_id = session_marker["response_id"]
    remembered_created_at = session_marker["created_at"]

    try:
        result = await run_with_retry(
            lambda: asyncio.wait_for(
                asyncio.to_thread(_post_response, prompt, token, agent["persona"], agent["model"], previous_response_id),
                timeout=_OUTER_TIMEOUT_SECONDS
            ),
            "Qwen",
            f"session_dir={session_dir}"
        )
    except asyncio.TimeoutError:
        logger.error(f"Qwen query for session_dir={session_dir} exceeded {_OUTER_TIMEOUT_SECONDS}s - abandoning it.")
        return None

    if result["previous_response_id_rejected"]:
        logger.warning(f"Qwen (DashScope) rejected previous_response_id={previous_response_id!r} as invalid/expired server-side - retrying this turn as a fresh conversation.")
        remembered_created_at = None
        try:
            result = await run_with_retry(
                lambda: asyncio.wait_for(
                    asyncio.to_thread(_post_response, prompt, token, agent["persona"], agent["model"], None),
                    timeout=_OUTER_TIMEOUT_SECONDS
                ),
                "Qwen",
                f"session_dir={session_dir}"
            )
        except asyncio.TimeoutError:
            logger.error(f"Qwen query (fresh-conversation retry) for session_dir={session_dir} exceeded {_OUTER_TIMEOUT_SECONDS}s - abandoning it.")
            return None

    # A billing failure and a rejected previous_response_id are mutually exclusive (rejected needs a 400/404, billing a 402/429), so one check here, after the optional fresh-conversation retry, covers both requests.
    if result["billing_failure"]:
        return billing_exhausted_response()
    else:
        if result["reply"] is not None:
            _write_session_marker(session_dir, result["response_id"], remembered_created_at)

        return result["reply"]

async def query_via_oauth(prompt: str, token: str, persona: str | None = None, session_dir: Path | None = None) -> str | None:
    """
    Not supported - Qwen's free OAuth login tier was discontinued.

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
    logger.warning("LLM_QWEN_ACCESS_TYPE=\"OAUTH\" is not supported - Qwen's OAuth login tier was discontinued, it is API-key-only today. Set LLM_QWEN_ACCESS_TYPE=\"API\" instead.")
    return None

# =============================================================================
