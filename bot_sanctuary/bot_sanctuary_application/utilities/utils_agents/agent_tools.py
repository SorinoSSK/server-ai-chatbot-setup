# =============================================================================
# File        : agent_tools.py
# Description : Validates an agent-produced message against telegram_gateway's own Response Queue Message Payload format, and publishes it once valid.
# Author      : SorinoSSK
# Created On  : 2026-09-12
#
# Features    :
#   - TOOLS - the tool list (name/description/format) an LLM is told it may reply with.
#   - execute_tool() - validates a message and, if valid, publishes it to telegram_gateway.
#   - execute_completed() - publishes the "completed" close-out directly - bot_sanctuary's own decision, never the agent's.
#
# Notes       :
#   - A message is exactly telegram_gateway's own per-type payload shape, minus task_id/session_id (added here) -
#     see telegram_gateway/README.md's "Response Queue Message Payloads" section for the authoritative format.
#   - session_reset/bot_started excluded on purpose - those are orchestrator-only actions (a whitelisted admin
#     command or this application's own schedule - see utils_session/session_worker.py), never agent-decided.
#   - "completed" is deliberately not in TOOLS - an agent's own reply must never end a task with silence; only
#     bot_sanctuary itself (call_dispatch_handler.py::execute_dispatch_call()'s own close-out step, via
#     execute_completed() below) may decide a task is finished with no further reply. The agent remains free to
#     choose any other tool, including "error" - only "completed" is reserved.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..utils_queue.queue import RabbitMQPublisher

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

TOOLS = [
    {"name": "poll", "description": "Send a poll.", "format": '{"type": "poll", "question": "...", "options": ["...", "..."], "allows_multiple_answers": false}'},
    {"name": "image", "description": "Send a single image.", "format": '{"type": "image", "url": "...", "caption": "..." (optional)}'},
    {"name": "video", "description": "Send a single video.", "format": '{"type": "video", "url": "...", "caption": "..." (optional)}'},
    {"name": "album", "description": "Send a group of photos/videos together.", "format": '{"type": "album", "items": [{"type": "photo" | "video", "url": "..."}, ...]}'},
    {"name": "file", "description": "Send a .pdf/.zip document.", "format": '{"type": "file", "url": "...", "caption": "..." (optional)}'},
    {"name": "text", "description": "Send a plain text reply, optionally with buttons.", "format": '{"type": "text", "text": "...", "buttons": [[{"text": "...", "purpose": "...", "payload": {...} (optional)}]] (optional)}'},
    {"name": "error", "description": "End this task abnormally, notifying the user.", "format": '{"type": "error", "error_type": "...", "message": "..." (optional)}'},
]

_TOOL_NAMES = [tool["name"] for tool in TOOLS]

# =============================================================================

def _tool_instructions() -> str:
    """
    Builds the tool list/format instructions used by build_tool_prompt().

    Args:
        None

    Returns:
        str:
            "Respond with..." followed by every tool's name/description/format.
    """
    lines = ["Respond with exactly one JSON object, choosing whichever of these tools fits your reply - no other text:"]
    for tool in TOOLS:
        lines.append(f"- {tool['name']}: {tool['description']} Format: {tool['format']}")
    return "\n".join(lines)

def build_tool_prompt(prompt: str) -> str:
    """
    Appends tool instructions to prompt, so the LLM's own reply is one of TOOLS' formats - not decided in Python.

    Args:
        prompt (str):
            The turn's own prompt/context.

    Returns:
        str:
            prompt, followed by the list of available tools and the format each one expects.
    """
    return f"{prompt}\n\n{_tool_instructions()}"

def _is_valid_album_item(item: dict) -> bool:
    """
    Checks whether an album item has a valid type ("photo"/"video") and a non-empty url.

    Args:
        item (dict)

    Returns:
        bool
    """
    return isinstance(item, dict) and item.get("type") in ("photo", "video") and bool(item.get("url"))

def validate_message(message: dict) -> str | None:
    """
    Validates message against its telegram_gateway payload shape.

    Args:
        message (dict):
            {"type": "...", ...fields} - see the TOOLS table above/telegram_gateway's README for the exact format.

    Returns:
        str | None:
            None if valid; otherwise a corrective message naming the expected format.
    """
    tool_name = message.get("type")
    tool = next((tool for tool in TOOLS if tool["name"] == tool_name), None)

    if tool is None:
        return f"{tool_name!r} is not a recognised tool. Available tools: {', '.join(_TOOL_NAMES)}."
    elif tool_name == "poll" and (not message.get("question") or not message.get("options")):
        return f"poll requires a non-empty 'question' and 'options'. Format: {tool['format']}"
    elif tool_name in ("image", "video", "file") and not message.get("url"):
        return f"{tool_name} requires a non-empty 'url'. Format: {tool['format']}"
    elif tool_name == "album" and not (isinstance(message.get("items"), list) and message.get("items") and all(_is_valid_album_item(item) for item in message["items"])):
        return f"album requires a non-empty 'items' list, each with type \"photo\" or \"video\" and a non-empty 'url'. Format: {tool['format']}"
    elif tool_name == "text" and not message.get("text"):
        return f"text requires a non-empty 'text'. Format: {tool['format']}"
    elif tool_name == "error" and not message.get("error_type"):
        return f"error requires a non-empty 'error_type'. Format: {tool['format']}"
    else:
        return None

def execute_tool(publisher: "RabbitMQPublisher", task_id: str, session_id: str, message: dict) -> str | None:
    """
    Validates message and, if valid, publishes it to telegram_gateway.

    Args:
        publisher (RabbitMQPublisher):
            The calling thread's own publisher - never shared across threads.

        task_id (str)

        session_id (str)

        message (dict):
            {"type": "...", ...fields} - the agent's own reply, in telegram_gateway's payload format.

    Returns:
        str | None:
            None if published successfully.
            Otherwise, a corrective message naming the expected format - meant to be handed back to the agent
            that produced message, so it can retry with a corrected one.
    """
    error = validate_message(message)
    if error is not None:
        logger.warning(f"Rejected message (task_id={task_id}, session_id={session_id}) - {error}")
        return error
    else:
        payload = {"task_id": task_id, "session_id": session_id, **message}
        if publisher.publish(payload):
            logger.info(f"Published {message['type']!r} message for task_id={task_id} (session_id={session_id}) to telegram_gateway.")
            return None
        else:
            logger.error(f"Failed to publish {message['type']!r} message for task_id={task_id} (session_id={session_id}).")
            return "Failed to deliver the message to telegram_gateway - please try again."

def execute_completed(publisher: "RabbitMQPublisher", task_id: str, session_id: str) -> str | None:
    """
    Publishes a "completed" close-out for task_id directly - bypasses TOOLS/validate_message() entirely, since
    "completed" is deliberately not a choice available to an agent (see TOOLS above) - only bot_sanctuary's own
    dispatch logic (call_dispatch_handler.py::execute_dispatch_call()) decides a task ends with no further reply.

    Args:
        publisher (RabbitMQPublisher):
            The calling thread's own publisher - never shared across threads.

        task_id (str)

        session_id (str)

    Returns:
        str | None:
            None if published successfully.
            Otherwise, an error string describing the publish failure (never a corrective message meant for an
            agent, unlike execute_tool()'s own return - there is no agent reply to correct here).
    """
    payload = {"task_id": task_id, "session_id": session_id, "type": "completed"}
    if publisher.publish(payload):
        logger.info(f"Published 'completed' message for task_id={task_id} (session_id={session_id}) to telegram_gateway.")
        return None
    else:
        logger.error(f"Failed to publish 'completed' message for task_id={task_id} (session_id={session_id}).")
        return "Failed to deliver the completed close-out to telegram_gateway - please try again."

# =============================================================================
