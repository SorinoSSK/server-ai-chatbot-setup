# =============================================================================
# File        : codex_interface.py
# Description : Interfaces with Codex (OpenAI) via OpenAI's own Responses API, with previous_response_id-based session continuity.
# Author      : SorinoSSK
# Created On  : 2026-09-10
#
# Features    :
#   - query_via_api()   - sends a prompt to Codex, authenticated via an OpenAI API key.
#   - query_via_oauth() - not developed; always logs and returns None (see Notes).
#   - Session continuity via OpenAI's own previous_response_id, remembered in a per-session_dir marker file and subject to this application's own local TTL (settings.CODEX_SESSION_TTL_DAYS).
#
# Notes       :
#   - Rebuilt 2026-09-23 from an earlier revision that shelled out to the `codex` CLI (`codex exec`) for both
#     endpoints, delivering persona via a throwaway per-call AGENTS.md working directory. That approach is gone
#     entirely - this module now calls OpenAI's own REST endpoint directly, the same shape deepseek_interface.py/
#     qwen_interface.py already use for their own providers, rather than depending on the CLI being installed.
#   - No OpenAI Python SDK dependency - this calls the Responses API directly via stdlib urllib, wrapped in
#     asyncio.to_thread(), mirroring qwen_interface.py almost exactly (Qwen's DashScope endpoint documents
#     itself as OpenAI-compatible, so the two modules share the same response envelope shape).
#   - _RESPONSES_API_URL is OpenAI's own Responses API. _DEFAULT_MODEL is only ever used as a fallback for a
#     Call whose own libraries/codex/<call_name>.json is empty/missing (today: architect/coder/review/
#     documentation) - chat.json already overrides this explicitly to "gpt-5.6-terra".
#   - persona is delivered as the Responses API's own "instructions" field, resent on every call (including
#     resumed ones) - previous_response_id only carries the raw conversation forward, not any prior top-level
#     instructions, same convention qwen_interface.py already follows and documents.
#   - reasoning_effort is read off AgentPersona.persona (the raw parsed JSON parse_agent() already returns in
#     full), same as deepseek_interface.py's own convention, and sent as OpenAI's own nested "reasoning":
#     {"effort": ...} object - not a flat top-level field the way DashScope's Qwen endpoint accepts it. Omitted
#     entirely from the request body when unset. Accepted values are model-dependent and only partially
#     confirmed (e.g. gpt-5-codex rejects "minimal") - see CODE_TODO.md.
#   - persona/model/reasoning_effort/session continuity are all resolved internally by query_via_api(), via
#     agent_persona.parse_agent()/the session marker file, derived from session_dir whenever one is given -
#     none of this is passed in from any caller.
#   - Session continuity uses previous_response_id rather than resending full message history, the same
#     mechanism qwen_interface.py uses against DashScope - OpenAI stores the conversation server-side, this
#     module never sees or stores the actual conversation content itself, only the response id. The local TTL
#     (settings.CODEX_SESSION_TTL_DAYS, default 2) is this application's own trust cutoff, not a measurement of
#     OpenAI's own server-side retention window, which this module does not rely on being any particular
#     length - unconfirmed, see CODE_TODO.md.
#   - The local marker file (_SESSION_MARKER_FILENAME) lives inside session_dir, so
#     utils_session/session_worker.py's existing whole-directory clearing (clear_all_session_directories() at
#     every application startup, and clear_session_directory() on a telegram_gateway-triggered session_reset)
#     already removes it for free - no new clearing logic needed, same conclusion already reached for Claude's/
#     DeepSeek's/Qwen's own marker/transcript files.
#   - The local TTL is a plain day-count cutoff and is not aligned to settings.SESSION_RESET_TIME - the
#     scheduled reset already removes the whole session_dir, marker included, so the TTL is only a backstop for
#     when no reset is configured, one is skipped, or its clearing fails - same reasoning as Qwen's/DeepSeek's.
#   - Whether an invalid/expired previous_response_id is reliably detectable via
#     _is_expired_previous_response_error()'s heuristic is unconfirmed against a real account, mirroring
#     qwen_interface.py's own equivalent caveat - see CODE_TODO.md.
#   - Transient failures (HTTP 429/500/502/503/504, connection-level errors other than a timeout, and a
#     response body cut short mid-read - http.client.IncompleteRead) are retried by api_retry.py::run_with_retry(),
#     which wraps each asyncio.wait_for() call, so every attempt gets its own _OUTER_TIMEOUT_SECONDS bound.
#     _post_response() only classifies the failure ("retryable") and never retries itself. A timeout, inner or
#     outer, is never retried, and exhausted retries return None exactly as any other failure always has.
#   - An exhausted quota (HTTP 429 with insufficient_quota in the body, OpenAI's own documented convention) is
#     never retried, and is the one failure that does not return None - query_via_api() returns
#     agent_errors.billing_exhausted_response() instead, an "error" tool reply dict (error_type="billing_exhausted")
#     that flows through call_dispatch_handler.py::message_dissect() like an agent's own error reply. Every
#     other failure still returns None.
#   - A successful call logs OpenAI's own usage block (token counts) at info, with the model, so cost can be
#     tracked from the log alone. Log-only, logged as-is.
#   - A 200 response whose reply is empty, whose "error" field is set, or whose "status" is failed/incomplete/
#     cancelled is logged at warning with those fields. Log-only - the reply is still returned or None exactly
#     as before, and it is never retried.
#   - The session marker read-modify-write in query_via_api() takes no lock, same reasoning already documented
#     in deepseek_interface.py/qwen_interface.py's own header Notes - each session has one SessionWorker thread
#     running its turns one at a time, so two calls for the same session_dir do not overlap in normal operation.
#   - query_via_oauth() is a deliberate stub, not a partially-built path - see this module's own header Notes
#     above and CODE_TODO.md. Codex's former CLI-based OAuth login (codex login, the codex exec subprocess, the
#     per-call AGENTS.md working directory) has been removed entirely along with the CLI dependency itself, the
#     same way deepseek_interface.py/qwen_interface.py already stub out OAuth for their own providers.
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

_RESPONSES_API_URL = "https://api.openai.com/v1/responses"
_DEFAULT_MODEL = "gpt-5.6-terra"

# The outer asyncio-level ceiling wrapping the blocking HTTP call. Deliberately a little larger than
# settings.AGENT_QUERY_TIMEOUT_SECONDS (the inner urllib socket timeout, see _post_response()), not equal to
# it, so the inner timeout fires first in the normal/expected case. Both are driven by the same shared setting
# Claude's/DeepSeek's/Qwen's own timeout handling also uses.
_OUTER_TIMEOUT_SECONDS = settings.AGENT_QUERY_TIMEOUT_SECONDS + 10

# Marker file this module reads/writes inside a given session_dir to remember Codex's own previous_response_id
# (and this application's own locally-tracked creation time) across separate query_via_api() calls - see
# _read_session_marker()/_write_session_marker(). Colocated with session_dir deliberately, not tracked
# anywhere else - see this module's own header Notes for why that means no new clearing logic was needed.
_SESSION_MARKER_FILENAME = ".codex_session.json"

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
        - Prefers the envelope's own top-level "output_text" convenience field. Falls back to walking "output"
          (a list of message items, each with its own "content" list of typed parts) if "output_text" is
          absent - mirrors qwen_interface.py's own equivalent function exactly, since both target the same
          Responses API envelope shape.
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
            The HTTP status code OpenAI returned.

        body_text (str):
            The raw (decoded) error response body.

    Returns:
        bool:
            True if this looks like an invalid/expired previous_response_id, specifically; False for every
            other request problem (bad model, bad token, malformed prompt, etc.).

    Notes:
        - Unconfirmed against a real account - see CODE_TODO.md. Checks for a 4xx status whose own body text
          mentions "previous_response_id" or "response_id" - a reasonable guess based on OpenAI's documented
          error-object shape, not a verified contract. Refine once real traffic surfaces the actual error text.
        - Deliberately narrow (status code AND keyword, not status code alone) - a bare 400 is also what a bad
          model string or malformed request would return, and those should not be treated as "start fresh".
    """
    lowered = body_text.lower()
    return status_code in (400, 404) and ("previous_response_id" in lowered or "response_id" in lowered)

def _post_response(prompt: str, token: str, persona: str | None, model: str, reasoning_effort: str | None, previous_response_id: str | None) -> dict:
    """
    Posts a single request to OpenAI's Responses API and returns the outcome.

    Args:
        prompt (str):
            The new user message for this turn only - never the full conversation history, since
            previous_response_id (when given) already carries that forward server-side.

        token (str):
            The OpenAI API key.

        persona (str | None):
            Optional persona/system instructions for this call - sent as "instructions", not "input", so it
            applies on every turn regardless of previous_response_id.

        model (str):
            Which OpenAI model string to request - see _resolve_agent()'s own Notes for how this is resolved.

        reasoning_effort (str | None):
            Optional reasoning-effort level (e.g. "high") - sent as OpenAI's own nested "reasoning": {"effort":
            ...} object, omitted from the request body entirely when None.

        previous_response_id (str | None):
            The prior turn's own response id to resume from, if any and not locally expired.

    Returns:
        dict:
            {"reply": str | None, "response_id": str | None, "previous_response_id_rejected": bool, "retryable": bool, "billing_failure": bool} -
            "reply"/"response_id" are None on any failure. "previous_response_id_rejected" is True only when
            the failure looks specifically like OpenAI rejecting previous_response_id itself (see
            _is_expired_previous_response_error()) - always False when previous_response_id was None to begin
            with. "retryable" is True only for a transient failure (see api_retry.RETRYABLE_STATUS_CODES, a
            connection-level error that is not a timeout, or an http.client.IncompleteRead while reading a
            successful response body) and is consumed by api_retry.py::run_with_retry(), not by this module's
            own callers. "billing_failure" is True only when the account's quota is exhausted (see
            agent_errors.is_billing_failure()) - such a failure is never retryable, and query_via_api() returns
            billing_exhausted_response() on it.

    Notes:
        - Synchronous/blocking - only ever called via asyncio.to_thread().
        - Classifies only - it never retries itself, see api_retry.py::run_with_retry().
    """
    body_payload: dict = {
        "model": model,
        "input": [{"role": "user", "content": prompt}],
        "stream": False
    }
    if persona:
        body_payload["instructions"] = persona
    if reasoning_effort:
        body_payload["reasoning"] = {"effort": reasoning_effort}
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
        logger.info(f"Codex (OpenAI) usage: model={model} usage={payload.get('usage')}")
        reply = _extract_output_text(payload)
        status = payload.get("status")
        error = payload.get("error")
        if reply is None or error or status in ("failed", "incomplete", "cancelled"):
            logger.warning(f"Codex (OpenAI) returned HTTP 200 but the reply looks failed, incomplete or empty: model={model} status={status!r} error={error!r} incomplete_details={payload.get('incomplete_details')!r} reply_empty={reply is None}.")
        return {"reply": reply, "response_id": payload.get("id") or None, "previous_response_id_rejected": False, "retryable": False, "billing_failure": False}
    except urllib.error.HTTPError as error:
        body_text = error.read().decode(errors="replace").strip()
        logger.error(f"Codex (OpenAI) Responses API returned HTTP {error.code}: {body_text}")
        rejected = previous_response_id is not None and _is_expired_previous_response_error(error.code, body_text)
        billing_failure = is_billing_failure(error.code, body_text)
        return {"reply": None, "response_id": None, "previous_response_id_rejected": rejected, "retryable": error.code in RETRYABLE_STATUS_CODES, "billing_failure": billing_failure}
    except (urllib.error.URLError, ConnectionError, http.client.IncompleteRead) as error:
        reason = getattr(error, "reason", error)
        logger.error(f"Codex request failed at the connection level: {reason!r}")
        return {"reply": None, "response_id": None, "previous_response_id_rejected": False, "retryable": not isinstance(reason, TimeoutError), "billing_failure": False}
    except Exception:
        logger.exception("Codex query failed - credential may be invalid/expired, the response was malformed, or the endpoint is unreachable.")
        return {"reply": None, "response_id": None, "previous_response_id_rejected": False, "retryable": False, "billing_failure": False}

def _resolve_agent(persona: str | None, session_dir: Path | None) -> dict:
    """
    Resolves this call's own persona text, model string and reasoning_effort, locally, right before querying.

    Args:
        persona (str | None):
            Fallback persona text, used only when session_dir is None.

        session_dir (Path | None):
            Working-directory anchor for this call - see call_name_from_session_dir()'s own Notes for the
            directory shape this is derived from.

    Returns:
        dict:
            {"persona": str | None, "model": str, "reasoning_effort": str | None} - session_dir's own resolved
            values if session_dir is given and a call_name can be derived from it; otherwise {"persona":
            persona, "model": _DEFAULT_MODEL, "reasoning_effort": None} unchanged/as given.

    Notes:
        - reasoning_effort has no dedicated AgentPersona attribute - read off AgentPersona.persona (the raw
          parsed JSON parse_agent() already returns in full) instead, same convention deepseek_interface.py uses.
        - _DEFAULT_MODEL is also the fallback whenever call_name resolves but that Call's own library file has
          no "model" field of its own - every Codex Call other than "chat" is still an empty placeholder
          library file today, so all of them fall back to _DEFAULT_MODEL until written.
    """
    call_name = call_name_from_session_dir(session_dir)
    if call_name is None:
        return {"persona": persona, "model": _DEFAULT_MODEL, "reasoning_effort": None}
    else:
        agent = parse_agent(settings.LLM_TYPE_CODEX, call_name)
        return {
            "persona": agent.body or persona,
            "model": agent.model or _DEFAULT_MODEL,
            "reasoning_effort": agent.persona.get("reasoning_effort") or None
        }

def _session_expiry_cutoff(created_at: datetime) -> datetime:
    """
    Computes the moment a session marker created at created_at should be treated as locally expired.

    Args:
        created_at (datetime):
            The marker's own originally-recorded creation time (timezone-aware, settings.TZ).

    Returns:
        datetime:
            created_at plus settings.CODEX_SESSION_TTL_DAYS.

    Notes:
        - Deliberately not aligned to settings.SESSION_RESET_TIME - see this module's own header Notes.
        - Mirrors qwen_interface.py's own equivalent function. Kept as a separate copy rather than a shared
          helper, since each reads its own provider's TTL setting - same convention already established there.
    """
    return created_at + timedelta(days=settings.CODEX_SESSION_TTL_DAYS)

def _read_session_marker(session_dir: Path | None) -> dict:
    """
    Reads session_dir's own remembered Codex previous_response_id, if one exists and is not locally expired.

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
        - A locally-expired marker is logged at info and treated identically to no marker at all.
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
            logger.exception(f"Failed to read Codex session marker at session_dir={session_dir} - starting a fresh conversation instead of resuming.")
            return {"response_id": None, "created_at": None}

        response_id = data.get("response_id") or None
        created_at_raw = data.get("created_at")
        if response_id is None or not created_at_raw:
            return {"response_id": None, "created_at": None}
        else:
            try:
                created_at = datetime.fromisoformat(created_at_raw)
            except ValueError:
                logger.warning(f"Codex session marker at session_dir={session_dir} has an unparsable created_at={created_at_raw!r} - starting a fresh conversation instead of resuming.")
                return {"response_id": None, "created_at": None}

            if application_time() >= _session_expiry_cutoff(created_at):
                logger.info(f"Codex session marker at session_dir={session_dir} exceeded its local TTL (created_at={created_at.isoformat()}, CODEX_SESSION_TTL_DAYS={settings.CODEX_SESSION_TTL_DAYS}) - starting a fresh conversation instead of resuming.")
                return {"response_id": None, "created_at": None}
            else:
                return {"response_id": response_id, "created_at": created_at}

def _write_session_marker(session_dir: Path | None, response_id: str | None, created_at: datetime | None) -> None:
    """
    Remembers response_id (and its own session's original creation time) as session_dir's own latest Codex session.

    Args:
        session_dir (Path | None):
            The working-directory anchor to write into. A no-op if None.

        response_id (str | None):
            The response id captured from this call's own successful reply. A no-op if None/empty.

        created_at (datetime | None):
            The session's own original creation time to preserve, if this turn continued an existing,
            not-yet-locally-expired session. None means this turn started a fresh conversation -
            application_time() is recorded as the new creation time.

    Returns:
        None

    Notes:
        - Only called after a confirmed-successful call, so a failed call leaves the prior marker in place.
        - created_at is deliberately preserved rather than refreshed on every successful turn - the local TTL
          is an absolute session age from first creation, not a sliding one reset by activity.
        - Best-effort - a write failure is logged but non-fatal.
    """
    if session_dir is None or not response_id:
        return
    else:
        payload = {"response_id": response_id, "created_at": (created_at or application_time()).isoformat()}
        try:
            (session_dir / _SESSION_MARKER_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            logger.exception(f"Failed to persist Codex session marker for session_dir={session_dir} - the next call at this session_dir will start a fresh conversation instead of resuming.")

async def query_via_api(prompt: str, token: str, persona: str | None = None, session_dir: Path | None = None) -> str | dict | None:
    """
    Sends a prompt to Codex, authenticated via an OpenAI API key.

    Args:
        prompt (str):
            The prompt to send.

        token (str):
            The OpenAI API key.

        persona (str | None):
            Fallback persona/system prompt, used only when session_dir is None - see _resolve_agent()'s own Notes.

        session_dir (Path | None):
            Working-directory anchor for this call - drives this call's own persona/model/reasoning_effort
            resolution (see _resolve_agent()) and its own session continuity (see
            _read_session_marker()/_write_session_marker()).

    Returns:
        str | dict | None:
            The assistant's text reply; an "error" tool reply dict if the account's quota is exhausted; or None on any other failure.

    Notes:
        - Runs the blocking HTTP call in a worker thread so it doesn't stall the event loop, bounded by
          _OUTER_TIMEOUT_SECONDS.
        - A previous_response_id OpenAI itself rejects as invalid/expired (previous_response_id_rejected) is
          retried once, immediately, as a fresh conversation - the end user gets a reply for this turn either
          way, rather than the whole call failing outright over a continuity mechanism they have no visibility
          into. See _is_expired_previous_response_error()'s own Notes on how this is detected.
        - A transient failure is retried by api_retry.py::run_with_retry(), which wraps each asyncio.wait_for() attempt, including the fresh-conversation one above. The return value is unchanged, still the reply text or None.
        - Returns agent_errors.billing_exhausted_response() (a dict, not text, and never None) when OpenAI
          reports the account's quota as exhausted, on either the normal or the fresh-conversation request. No
          session marker is written for it. That is the one case where this function returns a dict rather
          than str | None - see agent_errors.py.
    """
    agent = _resolve_agent(persona, session_dir)
    session_marker = _read_session_marker(session_dir)
    previous_response_id = session_marker["response_id"]
    remembered_created_at = session_marker["created_at"]

    try:
        result = await run_with_retry(
            lambda: asyncio.wait_for(
                asyncio.to_thread(_post_response, prompt, token, agent["persona"], agent["model"], agent["reasoning_effort"], previous_response_id),
                timeout=_OUTER_TIMEOUT_SECONDS
            ),
            "Codex",
            f"session_dir={session_dir}"
        )
    except asyncio.TimeoutError:
        logger.error(f"Codex query for session_dir={session_dir} exceeded {_OUTER_TIMEOUT_SECONDS}s - abandoning it.")
        return None

    if result["previous_response_id_rejected"]:
        logger.warning(f"Codex (OpenAI) rejected previous_response_id={previous_response_id!r} as invalid/expired server-side - retrying this turn as a fresh conversation.")
        remembered_created_at = None
        try:
            result = await run_with_retry(
                lambda: asyncio.wait_for(
                    asyncio.to_thread(_post_response, prompt, token, agent["persona"], agent["model"], agent["reasoning_effort"], None),
                    timeout=_OUTER_TIMEOUT_SECONDS
                ),
                "Codex",
                f"session_dir={session_dir}"
            )
        except asyncio.TimeoutError:
            logger.error(f"Codex query (fresh-conversation retry) for session_dir={session_dir} exceeded {_OUTER_TIMEOUT_SECONDS}s - abandoning it.")
            return None

    # A billing failure and a rejected previous_response_id are mutually exclusive (rejected needs a 400/404, billing a 429), so one check here, after the optional fresh-conversation retry, covers both requests.
    if result["billing_failure"]:
        return billing_exhausted_response()
    else:
        if result["reply"] is not None:
            _write_session_marker(session_dir, result["response_id"], remembered_created_at)

        return result["reply"]

async def query_via_oauth(prompt: str, token: str, persona: str | None = None, session_dir: Path | None = None) -> str | None:
    """
    Not developed - Codex is API-key-only in this application.

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

    Notes:
        - Codex previously shelled out to the `codex` CLI's own persisted ChatGPT/OAuth login session for this
          endpoint (see this module's own header Notes). That path - and the CLI dependency it required - was
          removed 2026-09-23 in favour of query_via_api()'s direct OpenAI Responses API call. This is a
          deliberate scope decision, not an oversight - see CODE_TODO.md.
    """
    logger.warning("LLM_CODEX_ACCESS_TYPE=\"OAUTH\" is not developed - set LLM_CODEX_ACCESS_TYPE=\"API\" instead.")
    return None

# =============================================================================
