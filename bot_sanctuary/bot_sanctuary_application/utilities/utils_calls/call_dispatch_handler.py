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
#   - Entry point is always "chat" (CODE_TODO.md §5 Phase 4). Every hop - the initial entry, a handoff, or a
#     corrective retry - is expressed the same way: a {"target_call": "<call_name>", "prompt": "..."} item on
#     dispatch_queue. dispatch_call() never decides a call_name/prompt itself; it only ever consumes the queue.
#   - dispatch_queue is owned by the calling SessionWorker (utils_session/session_worker.py), one per session,
#     and passed in explicitly by every function here - never module-level/thread-local state. Since a
#     SessionWorker only ever processes one batch at a time, on its own single persistent thread, this needs
#     no locking of its own.
#   - settings.CALL_MAX_HOPS bounds the loop, so a Call chain (handoffs and/or corrective retries) can never
#     run forever.
#   - No Call other than "chat" is wired to this dict-based handle() contract yet (architect/coder/review/
#     documentation_call.py still return str | None) - a target_call naming any of them would break today. Not
#     reachable in practice, since chat_call never actually returns a call pass yet (no handoff logic built).
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

_ENTRY_CALL_NAME = "chat"

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
        - A common LLM habit despite an explicit instruction not to (see libraries/claude/chat.json's own
          "# JSON String Safety" section) - stripping it here is a cheap, safe normalisation that costs nothing
          when no fence is present, and salvages an otherwise-valid JSON reply that would only fail
          json.loads() because of the wrapping fence characters themselves, not the JSON content inside it.
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
        - Only ever needed on dispatch_call()'s hop-limit path - every other terminal path (an unrecognised
          target_call, a raised exception, a None reply) returns before message_dissect() ever gets a chance
          to queue a further item, so the queue is already empty. The hop-limit path is different: its very
          last iteration may have queued a further hop (a handoff or a retry) that the loop then never
          consumes - left alone, that item would leak into this same SessionWorker's next turn, since
          dispatch_queue is reused across turns, not recreated per turn.
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
            The session's own dispatch queue (SessionWorker.dispatch_queue) - already seeded with this turn's
            entry hop ({"target_call": "chat", "prompt": <the turn's prompt>}) by execute_dispatch_call().

        session_dir (Path):
            This session's own on-disk root directory (SessionWorker.session_dir, i.e. SESSION_DIR/<session_id>),
            passed straight through to every Call's handle() - see chat_call.py's own Notes for how it derives
            its own Call/LLM-scoped leaf directory from this root.

    Returns:
        dict:
            {"message": dict | None, "error_type": str | None, "error_message": str | None}.
            "message" is set (both error fields None) once message_dissect() confirms a Call's reply is a
            valid tool call - see agent_tools.py's own TOOLS list/format for its shape. Ready to hand straight
            to agent_tools.execute_tool().
            "error_type"/"error_message" are set ("message" None) if a Call raised, returned None, named an
            unrecognised target_call, or the loop exceeded settings.CALL_MAX_HOPS.

    Notes:
        - Every iteration pulls exactly one {"target_call", "prompt"} item off dispatch_queue, calls that
          Call's handle(prompt), and hands the result to message_dissect() - which itself decides whether to
          queue a further hop (a handoff or a corrective retry - message_dissect() returns None, and the loop
          continues) or return a final tool message (message_dissect() returns non-None, and the loop stops).
        - dispatch_call() never inspects a Call's result itself, and never decides a target_call/prompt of its
          own - both are entirely message_dissect()'s responsibility.
        - session_dir is passed to every Call's handle() the same way, regardless of target_call - only
          chat_call.py actually consumes it today (see its own Notes); architect_call.py/coder_call.py/
          review_call.py/documentation_call.py are still on the older handle(prompt)-only contract, and would
          raise if a target_call ever actually named one of them - not reachable in practice yet, same known,
          flagged-not-fixed gap already recorded elsewhere for this contract (see CODE_TODO.md §5).
    """
    for _ in range(settings.CALL_MAX_HOPS):
        item = dispatch_queue.get_nowait()
        call = call_router.get_call(item["target_call"])
        if call is None:
            return {"message": None, "error_type": "call_pipeline_failed", "error_message": f"{item['target_call']!r} is not a recognised agent - please try again."}
        else:
            try:
                result = await call.handle(item["prompt"], session_dir)
            except Exception:
                logger.exception(f"{item['target_call']} Call raised while handling a turn - reporting back as an error instead of propagating.")
                return {"message": None, "error_type": "call_pipeline_failed", "error_message": "Something went wrong while generating a reply. Please try again."}

            if result is None:
                return {"message": None, "error_type": "call_pipeline_unavailable", "error_message": "The chat agent is not currently available. Please try again later."}
            else:
                outcome = message_dissect(dispatch_queue, item["target_call"], result)
                if outcome is not None:
                    return outcome
                # else: message_dissect() already queued the next hop (a handoff or a corrective retry) - loop again.

    _drain(dispatch_queue)
    return {"message": None, "error_type": "call_pipeline_failed", "error_message": "Too many handoffs between agents - please try again."}

def execute_dispatch_call(publisher: "RabbitMQPublisher", session_id: str, task_id: str, prompt: str, dispatch_queue: "queue.Queue", session_dir: Path) -> None:
    """
    Runs one agent Call pipeline turn and publishes its outcome against task_id, via the caller's own publisher.

    Args:
        publisher (RabbitMQPublisher):
            The calling thread's own publisher (a SessionWorker's long-lived instance, or a disposable one) -
            see utils_queue/queue.py's own module header on why this is never shared across threads.

        session_id (str)

        task_id (str):
            The still-open task_id this turn's reply/error/completed must be published against.

        prompt (str):
            The (possibly coalesced) input text for this turn.

        dispatch_queue (queue.Queue):
            The calling SessionWorker's own dispatch queue (SessionWorker.dispatch_queue) - seeded here with
            this turn's entry hop, then consumed by dispatch_call(). Never shared across sessions/threads,
            same as publisher.

        session_dir (Path):
            The calling SessionWorker's own on-disk session root directory (SessionWorker.session_dir), passed
            straight through to dispatch_call() and from there to every Call's handle().

    Returns:
        None

    Notes:
        - A successful message is published as-is (tools_check - agent_tools.execute_tool()), then "completed" to
          close task_id out - publishing a reply alone does not close a task_id on telegram_gateway's side (see
          its README's Response Queue Message Payloads), only "completed"/"error" do. "completed" itself is
          always this function's own decision (agent_tools.execute_completed()), never the agent's - "completed"
          is deliberately not one of TOOLS, so an agent's own reply can never end a task silently; it remains
          free to choose any other tool, including "error".
        - A poll is the deliberate exception to the line above - its task_id is left open, uncompleted, since
          telegram_gateway routes that same task_id's eventual poll_answer/poll_timed_out back here once the poll
          concludes (see its README's "Poll answers"/"poll_timed_out" sections) - closing it early here would
          contradict that. That later turn is responsible for actually closing it out.
        - A "text" reply carrying buttons gets the same open-task_id treatment as a poll, for a related but
          simpler reason - completing task_id the instant the buttons are sent would be wrong regardless of
          whether/how a press is ever routed back; completion for this task_id happens whenever a future send for
          this chat finally isn't itself a button/poll message, not on this send. Unlike poll, no dedicated
          press-routing/expiry mechanism exists (or is needed) for this - it is a plain per-message rule, not a
          cross-task_id tracking feature.
        - A message that itself fails validation/publish (agent_tools.execute_tool() returning a corrective
          message) falls back to publishing "error" instead, so task_id is never left silently open - a failed
          fallback too is logged and left for a future session reset to eventually clear.
        - mark_task_complete() is only called once task_id is actually closed out on telegram_gateway's side (a
          successful "completed" or "error" publish) - this is what wires up CODE_TODO.md §3's previously open
          "not yet wired for a batch's final task_id" crash-recovery gap. Not called for a poll or a buttons-
          carrying text reply either, for the same reason - task_id is still genuinely open from bot_sanctuary's
          own crash-recovery point of view too.
        - Runs the (async) dispatch_call() synchronously via asyncio.run() - the caller (a SessionWorker's run
          loop) is plain, synchronous code, one batch at a time; there is no shared event loop to schedule onto
          instead. asyncio.run() runs its event loop on this same calling thread, never a new one - this is
          what keeps dispatch_queue's put()/get_nowait() calls (here and inside dispatch_call()) on the one
          thread that owns it.
        - dispatch_call() already converts a Call failure into an error_type/error_message pair rather than
          raising - the try/except below is a further, defensive backstop only (e.g. an asyncio-level failure),
          since an uncaught exception here would otherwise propagate into the calling thread (a SessionWorker's
          own run loop) and kill it outright, permanently stranding that session_id's inbox rather than merely
          failing one turn.
    """
    dispatch_queue.put({"target_call": _ENTRY_CALL_NAME, "prompt": prompt})
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

def message_dissect(dispatch_queue: "queue.Queue", target_call: str, result: dict | str) -> dict | None:
    """
    Decides what a Call's handle() result actually is, and drives whatever happens next - the single place
    deciding between a call pass (a handoff to another Call/LLM) and a tool call (final, meant for
    telegram_gateway), and feeding a corrective retry back to the same Call's own LLM if result is neither,
    or is a tool call that fails its own format validation.

    Args:
        dispatch_queue (queue.Queue):
            This session's own dispatch queue (SessionWorker.dispatch_queue) - the next hop (a retry or a
            handoff) is queued here, for dispatch_call()'s loop to pick up and feed into that Call's LLM.

        target_call (str):
            The Call that just produced result - reused as the retry target if result needs correcting.

        result (dict | str):
            Whatever call.handle(prompt) returned.

    Returns:
        dict | None:
            {"message": result, "error_type": None, "error_message": None} - a tool call that passed
            agent_tools.validate_message(). Final - hand this straight back to execute_dispatch_call for
            telegram_gateway.
            None - a call pass, or a corrective retry, has already been queued onto dispatch_queue.
            dispatch_call()'s loop should continue.

    Notes:
        - A str result has a wrapping ```json/``` code fence stripped (_strip_code_fence()) before json.loads()
          is attempted - a cheap, safe normalisation, see that function's own docstring.
        - A result that still isn't valid JSON after that is logged at WARNING with its raw text - direct
          evidence for diagnosing what pattern (an unescaped quote, a literal newline, prose-only, a code
          fence this stripping didn't catch) is actually occurring in practice, rather than only inferring it
          from user-reported examples after the fact.
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
        dispatch_queue.put({
            "target_call": target_call,
            "prompt": "That reply was not valid JSON. Reply again with exactly one JSON object from your available tools - nothing else, no other text before or after it, no code fence (a call pass, `{target_call: <a call name>, message: <your input>}`, is also accepted if that's what you intended)."
        })
        return None
    elif "target_call" in validate_msg and "message" in validate_msg:
        dispatch_queue.put({"target_call": validate_msg["target_call"], "prompt": validate_msg["message"]})
        return None
    else:
        tool_error = agent_tools.validate_message(validate_msg)
        if tool_error is None:
            return {"message": validate_msg, "error_type": None, "error_message": None}
        else:
            dispatch_queue.put({
                "target_call": target_call,
                "prompt": f"Your previous reply was invalid: {tool_error}\nRespond again with a corrected JSON object."
            })
            return None

# =============================================================================
