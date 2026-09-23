# =============================================================================
# File        : call_dispatch_handler.py
# Description : Runs a single turn of the agent Call pipeline for a session's coalesced input, and publishes its outcome back to telegram_gateway.
# Author      : SorinoSSK
# Created On  : 2026-09-12
#
# Features    :
#   - dispatch_call() - consumes a session's own dispatch_queue, one hop at a time, until message_dissect() hands back a final tool message.
#   - message_dissect() - the single place deciding whether a Call's result is a call pass (handoff), a valid tool call, or needs a corrective retry - and queues whichever applies.
#   - execute_dispatch_call() - seeds dispatch_queue with the turn's entry hop, runs dispatch_call(), and publishes its outcome via utils_agents/agent_tools.py, on the caller's own thread/publisher.
#
# Notes       :
#   - Entry point is always "chat" - every hop is expressed as one {"target_call", "prompt", "coding_allowed"} item on dispatch_queue.
#   - dispatch_queue is owned by the calling SessionWorker, one per session, and passed in explicitly.
#   - settings.CALL_MAX_HOPS bounds the loop, so a Call chain can never run forever.
#   - No Call other than "chat" is wired to this handoff contract yet - see CODE_TODO.md.
#   - coding_allowed is threaded through every hop (execute_dispatch_call() seeds it, message_dissect() carries
#     it forward onto every further hop it queues) and enforced by message_dissect() against a call pass's own
#     requested target_call - see that function's own Notes. Not yet consulted anywhere else (e.g. no
#     filesystem/code-tool gating exists yet - §6, CODE_TODO.md).
#   - See README.md for the full Call pipeline design rationale.
#
# =============================================================================
# I M P O R T   H E A D E R

import json
import re
import queue
import asyncio
import logging

from pathlib import Path
from typing import TYPE_CHECKING

from ...config import settings
from . import call_router
from ..utils_agents import agent_tools
from ..utils_redis.database import mark_task_complete

if TYPE_CHECKING:
    from ..utils_queue.queue import RabbitMQPublisher

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_ENTRY_CALL_NAME = settings.CALL_NAME_CHAT

# Matches a reply wrapped in a ```json ... ``` (or plain ``` ... ```) code fence, capturing the content between
# the fences - see _strip_code_fence()'s own docstring for why this is stripped before json.loads() is attempted.
_CODE_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)

# =============================================================================

def _strip_code_fence(text: str) -> str:
    """
    Strips a wrapping ```json ... ```/``` ... ``` code fence from text, if present.

    Args:
        text (str):
            A Call's raw reply text, prior to any json.loads() attempt.

    Returns:
        str:
            text with its wrapping code fence removed, if it had one; otherwise text unchanged.

    Notes:
        - A cheap, safe normalisation that costs nothing when no fence is present.
    """
    match = _CODE_FENCE_PATTERN.match(text.strip())
    return match.group(1).strip() if match else text

def _drain(dispatch_queue: "queue.Queue") -> None:
    """
    Empties dispatch_queue of every currently-queued item.

    Args:
        dispatch_queue (queue.Queue):
            The session's own dispatch queue (SessionWorker.dispatch_queue).

    Returns:
        None

    Notes:
        - Only needed on dispatch_call()'s hop-limit path, to stop a leftover hop leaking into the next turn.
    """
    while True:
        try:
            dispatch_queue.get_nowait()
        except queue.Empty:
            return

async def dispatch_call(dispatch_queue: "queue.Queue", session_dir: Path) -> dict:
    """
    Runs a single turn of the agent Call pipeline, consuming dispatch_queue one hop at a time.

    Args:
        dispatch_queue (queue.Queue):
            The session's own dispatch queue, already seeded with this turn's entry hop by execute_dispatch_call().

        session_dir (Path):
            This session's own on-disk root directory, passed straight through to every Call's handle().

    Returns:
        dict:
            {"message": dict | None, "error_type": str | None, "error_message": str | None}. "message" is set once a Call's reply is confirmed valid; the error fields are set otherwise.

    Notes:
        - Each iteration pulls one hop off dispatch_queue and hands its result to message_dissect(), which decides whether to queue a further hop or return a final tool message.
        - Only "chat" is wired to this contract today - see CODE_TODO.md.
        - item["coding_allowed"] is read here and passed both to call.handle() (an advisory hint only - see
          chat_call.py's own Notes) and through to message_dissect() (the actual enforcement) - always present
          on a hop item by construction (execute_dispatch_call() seeds it on the entry hop, message_dissect()
          carries it forward onto every further hop it queues). This function itself never inspects it or acts
          on it directly, in either case.
        - Every Call's own handle(prompt, session_dir, coding_allowed) signature is now uniform - see
          chat_call.py's own Notes on what coding_allowed means there. architect_call.py/coder_call.py/
          review_call.py/documentation_call.py were not updated to accept it (nor session_dir, an
          already-existing, separately-flagged gap) - unreachable today regardless, since "chat" is still the
          only Call dispatch_call() ever starts with or can be handed off to - see CODE_TODO.md.
    """
    for _ in range(settings.CALL_MAX_HOPS):
        item = dispatch_queue.get_nowait()
        call = call_router.get_call(item["target_call"])
        if call is None:
            return {"message": None, "error_type": "call_pipeline_failed", "error_message": f"{item['target_call']!r} is not a recognised agent - please try again."}
        else:
            try:
                result = await call.handle(item["prompt"], session_dir, item["coding_allowed"])
            except Exception:
                logger.exception(f"{item['target_call']} Call raised while handling a turn - reporting back as an error instead of propagating.")
                return {"message": None, "error_type": "call_pipeline_failed", "error_message": "Something went wrong while generating a reply. Please try again."}

            if result is None:
                return {"message": None, "error_type": "call_pipeline_unavailable", "error_message": "The chat agent is not currently available. Please try again later."}
            else:
                outcome = message_dissect(dispatch_queue, item["target_call"], result, item["coding_allowed"])
                if outcome is not None:
                    return outcome
                # else: message_dissect() already queued the next hop (a handoff or a corrective retry) - loop again.

    _drain(dispatch_queue)
    return {"message": None, "error_type": "call_pipeline_failed", "error_message": "Too many handoffs between agents - please try again."}

def execute_dispatch_call(publisher: "RabbitMQPublisher", session_id: str, task_id: str, prompt: str, dispatch_queue: "queue.Queue", session_dir: Path, coding_allowed: bool) -> None:
    """
    Runs one agent Call pipeline turn and publishes its outcome against task_id, via the caller's own publisher.

    Args:
        publisher (RabbitMQPublisher):
            The calling thread's own publisher - never shared across threads.

        session_id (str)

        task_id (str):
            The still-open task_id this turn's reply/error/completed must be published against.

        prompt (str):
            The (possibly coalesced) input text for this turn.

        dispatch_queue (queue.Queue):
            The calling SessionWorker's own dispatch queue, seeded here with this turn's entry hop.

        session_dir (Path):
            The calling SessionWorker's own on-disk session root directory.

        coding_allowed (bool):
            The calling SessionWorker's own resolved coding_allowed for this turn (see
            session_worker.py::_extract_coding_allowed()) - seeded onto the entry hop and carried forward onto
            every further hop by message_dissect(), which also enforces it against a call pass's own requested
            target_call (see that function's own Notes) - not yet consulted anywhere else (§5 Phase 6 plan,
            CODE_TODO.md).

    Returns:
        None

    Notes:
        - A successful reply is published, then closed with "completed" - a poll or a buttons-carrying text reply is left open instead, since a further turn will close it later.
        - A message that fails validation/publish falls back to publishing "error" instead, so task_id is never left silently open.
        - See README.md for the full close-out and crash-recovery design.
    """
    dispatch_queue.put({"target_call": _ENTRY_CALL_NAME, "prompt": prompt, "coding_allowed": coding_allowed})
    try:
        outcome = asyncio.run(dispatch_call(dispatch_queue, session_dir))
    except Exception:
        logger.exception(f"session_id={session_id}: dispatch_call() raised unexpectedly for task_id={task_id} - closing it out with an error instead of leaving it/the calling thread stranded.")
        outcome = {"message": None, "error_type": "call_pipeline_failed", "error_message": "Something went wrong while generating a reply. Please try again."}

    message = outcome["message"]
    error_type = outcome["error_type"]
    error_message = outcome["error_message"]

    if error_type is not None:
        tool_error = agent_tools.execute_tool(publisher, task_id, session_id, {"type": "error", "error_type": error_type, "message": error_message or ""})
        if tool_error is not None:
            logger.error(f"session_id={session_id}: failed to publish error for task_id={task_id} - {tool_error}")
        else:
            mark_task_complete(task_id)
            logger.info(f"session_id={session_id}: closed task_id={task_id} with error_type={error_type!r}.")
    else:
        tool_error = agent_tools.execute_tool(publisher, task_id, session_id, message)
        if tool_error is not None:
            logger.warning(f"session_id={session_id}: failed to publish message for task_id={task_id} ({tool_error}) - falling back to an error close-out.")
            fallback_error = agent_tools.execute_tool(
                publisher, task_id, session_id,
                {"type": "error", "error_type": "reply_delivery_failed", "message": tool_error}
            )
            if fallback_error is not None:
                logger.error(f"session_id={session_id}: failed to close task_id={task_id} via the error fallback too - {fallback_error}. task_id remains open until a future session reset.")
            else:
                mark_task_complete(task_id)
        elif message.get("type") == "poll" or (message.get("type") == "text" and message.get("buttons")):
            logger.info(f"session_id={session_id}: published {message['type']} for task_id={task_id} - leaving it open (poll, or a text reply carrying buttons).")
        else:
            completed_error = agent_tools.execute_completed(publisher, task_id, session_id)
            if completed_error is not None:
                logger.error(f"session_id={session_id}: reply published for task_id={task_id}, but failed to close it out with completed - {completed_error}. task_id remains open until a future session reset.")
            else:
                mark_task_complete(task_id)
                logger.info(f"session_id={session_id}: closed task_id={task_id} after publishing its reply.")

def message_dissect(dispatch_queue: "queue.Queue", target_call: str, result: dict | str, coding_allowed: bool) -> dict | None:
    """
    Decides what a Call's handle() result actually is, and drives whatever happens next.

    The single place deciding between a call pass (a handoff), a valid tool call, and a corrective retry.

    Args:
        dispatch_queue (queue.Queue):
            This session's own dispatch queue - the next hop, if any, is queued here.

        target_call (str):
            The Call that just produced result - reused as the retry target if result needs correcting.

        result (dict | str):
            Whatever call.handle(prompt) returned.

        coding_allowed (bool):
            This turn's own resolved coding_allowed (see execute_dispatch_call()'s own Notes) - carried forward
            onto every further hop this function queues, so it survives the whole turn's hop chain rather than
            only the entry hop. Enforced against a call pass's own requested target_call below (§5 Phase 6,
            CODE_TODO.md) - not yet consulted anywhere else (e.g. no filesystem/code-tool gating exists yet).

    Returns:
        dict | None:
            A final outcome dict once result passes validation; otherwise None, once a further hop has been queued.

    Notes:
        - A str result has a wrapping code fence stripped before json.loads() is attempted.
        - Invalid JSON is logged at WARNING with its raw text, for diagnosis. Its own corrective-retry prompt
          omits the "a call pass is also accepted" clause when coding_allowed is False, so it never offers a
          reply shape that would just be corrected away again by the check below.
        - A call pass to any target_call other than settings.CALL_NAME_CHAT is itself rejected when
          coding_allowed is False - queued as a corrective retry back to the same (always "chat" today) Call,
          rather than as the requested handoff. This is the first actual enforcement of coding_allowed anywhere
          in this codebase - every other hop this function queues merely carries the flag forward unread.
    """
    if isinstance(result, dict):
        validate_msg = result
    else:
        try:
            validate_msg = json.loads(_strip_code_fence(result))
        except (json.JSONDecodeError, TypeError):
            validate_msg = None

    if validate_msg is None:
        logger.warning(f"{target_call} Call's reply was not valid JSON - queuing a corrective retry. Raw reply: {result!r}")
        if coding_allowed:
            invalid_json_prompt = "That reply was not valid JSON. Reply again with exactly one JSON object from your available tools - nothing else, no other text before or after it, no code fence (a call pass, `{target_call: <a call name>, message: <your input>}`, is also accepted if that's what you intended)."
        else:
            invalid_json_prompt = "That reply was not valid JSON. Reply again with exactly one JSON object from your available tools - nothing else, no other text before or after it, no code fence."
        dispatch_queue.put({
            "target_call": target_call,
            "prompt": invalid_json_prompt,
            "coding_allowed": coding_allowed
        })
        return None
    elif "target_call" in validate_msg and "message" in validate_msg:
        if not coding_allowed and validate_msg["target_call"] != settings.CALL_NAME_CHAT:
            logger.warning(f"{target_call} Call attempted a handoff to target_call={validate_msg['target_call']!r} without coding_allowed - queuing a corrective retry instead of the requested handoff.")
            dispatch_queue.put({
                "target_call": target_call,
                "prompt": "You do not have permission to hand off to another agent right now. Please answer this directly instead.",
                "coding_allowed": coding_allowed
            })
        else:
            dispatch_queue.put({"target_call": validate_msg["target_call"], "prompt": validate_msg["message"], "coding_allowed": coding_allowed})
        return None
    else:
        tool_error = agent_tools.validate_message(validate_msg)
        if tool_error is None:
            return {"message": validate_msg, "error_type": None, "error_message": None}
        else:
            dispatch_queue.put({
                "target_call": target_call,
                "prompt": f"Your previous reply was invalid: {tool_error}\nRespond again with a corrected JSON object.",
                "coding_allowed": coding_allowed
            })
            return None

# =============================================================================
