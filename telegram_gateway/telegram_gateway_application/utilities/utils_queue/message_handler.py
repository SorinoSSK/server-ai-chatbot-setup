# =============================================================================
# File        : message_handler.py
# Description : File responsible for handling messages consumed from RabbitMQ.
# Author      : SorinoSSK
# Created On  : 2026-08-29
#
# Features    :
#   - Dispatches incoming queue messages by type - poll/image/video/album/file/text/completed/error.
#     See README.md for the payload shape per type.
#   - text messages may carry inline keyboard buttons - see utils_telegram/utilities/button_prompt_handler.py.
#   - poll messages start their answer-collection timer on send - see utils_telegram/utilities/poll_response_handler.py.
#   - A send rejected by Telegram (or by local validation) is reported as a Tier 1 delivery_failed event, per task_id - see error_handling.py.
#
# Notes       :
#   - Owns its own JSON parsing so a malformed payload is logged and dropped rather than requeued forever.
#   - Resolves chat_id/user_id from Redis via task_id.
#
# =============================================================================
# I M P O R T   H E A D E R

import html
import json
import logging

from ...config import settings
from ..utils_redis.database import get_task_mapping, delete_task_mapping, create_poll_mapping
from ..utils_telegram.gateway_outbound import send_message, send_poll, send_photo, send_video, send_media_group, send_document
from ..utils_telegram.utilities.button_prompt_handler import register_bot_button, send_message_with_buttons
from ..utils_telegram.utilities.typing_indicator import stop_typing
from ..utils_telegram.utilities.poll_response_handler import start_poll_timer
from .error_handling import push_tier1_delivery_failed

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# =============================================================================

def _handle_poll(task_id: str, chat_id: int, question: str, options: list, allows_multiple_answers: bool) -> None:
    """
    Handle a poll response payload - sends it via Telegram's sendPoll endpoint and starts its answer-collection timer.

    Args:
        task_id (str)

        chat_id (int)

        question (str)

        options (list)

        allows_multiple_answers (bool)

    Returns:
        None

    Notes:
        - Skipped (and logged) if question is missing. Null/invalid options are filtered out.
        - is_anonymous is not caller-configurable - see send_poll().
        - A rejected send (see send_poll()) is reported as a Tier 1 delivery_failed event - see error_handling.py.
          A connection failure or unauthorized token (Tier 2) is already recorded internally by send_poll() - nothing further to do here.
        - On a successful send, registers a poll:<poll_id> Redis mapping and starts its AWAITING FIRST ANSWER / DEBOUNCING timer (see utils_telegram/utilities/poll_response_handler.py) - without this, an incoming poll_answer update has nothing to correlate back to.
    """
    if not question:
        logger.error(f"Poll payload for chat_id={chat_id} is missing a question. Message dropped.")
        return

    valid_options = [option for option in (options or []) if option]
    result = send_poll(chat_id, question, valid_options, allows_multiple_answers)
    if result is None:
        return

    if result.get("error"):
        push_tier1_delivery_failed(task_id, "poll", result.get("status_code"), result.get("reason"))
        return

    poll_id = result["poll_id"]
    if create_poll_mapping(poll_id, chat_id, task_id, result["message_id"]):
        start_poll_timer(poll_id, chat_id)
    else:
        logger.error(f"Failed to create poll mapping for poll_id={poll_id} (task_id={task_id}). Answers to this poll will not be collected.")

def _send_media_with_caption(send_func, attempted_type: str, task_id: str, chat_id: int, url: str, message: str) -> None:
    """
    Sends media via send_func, splitting an overlong caption into a separate follow-up text message.

    Args:
        send_func (Callable[[int, str, str | None], bool | dict]):
            send_photo/send_video/send_document.

        attempted_type (str):
            "image" | "video" | "file" - passed straight through to a Tier 1 event, if raised.

        task_id (str)

        chat_id (int)

        url (str)

        message (str)

    Returns:
        None

    Notes:
        - Caption is cut to TELEGRAM_CAPTION_MAX_LENGTH; the remainder is sent as a follow-up message, only if the primary send succeeds.
        - A rejected primary send is reported as a Tier 1 delivery_failed event - see error_handling.py.
          A connection failure or unauthorized token (Tier 2) is already recorded internally by send_func - nothing further to do here.
          The follow-up remainder isn't itself Tier 1-reported, to avoid a second event for what's really one logical send.
    """
    if message and len(message) > settings.TELEGRAM_CAPTION_MAX_LENGTH:
        caption = message[:settings.TELEGRAM_CAPTION_MAX_LENGTH]
        remainder = message[settings.TELEGRAM_CAPTION_MAX_LENGTH:]
        result = send_func(chat_id, url, caption)
        if result is True:
            send_message(chat_id, remainder)
        elif isinstance(result, dict):
            push_tier1_delivery_failed(task_id, attempted_type, result.get("status_code"), result.get("reason"))
    else:
        result = send_func(chat_id, url, message)
        if isinstance(result, dict):
            push_tier1_delivery_failed(task_id, attempted_type, result.get("status_code"), result.get("reason"))

def _handle_image(task_id: str, chat_id: int, url: str, message: str) -> None:
    """
    Handle an image response payload - sends it via Telegram's sendPhoto endpoint.

    Args:
        task_id (str)

        chat_id (int)

        url (str)

        message (str):
            Optional caption.

    Returns:
        None
    """
    _send_media_with_caption(send_photo, "image", task_id, chat_id, url, message)

def _handle_video(task_id: str, chat_id: int, url: str, message: str) -> None:
    """
    Handle a video response payload - sends it via Telegram's sendVideo endpoint.

    Args:
        task_id (str)

        chat_id (int)

        url (str)

        message (str):
            Optional caption.

    Returns:
        None
    """
    _send_media_with_caption(send_video, "video", task_id, chat_id, url, message)

def _is_valid_album_item(item: dict) -> bool:
    """
    Checks whether an album item has a valid type ("photo"/"video") and a non-empty url.

    Args:
        item (dict)

    Returns:
        bool:
            True if item is a valid album item; otherwise False.
    """
    return isinstance(item, dict) and item.get("type") in ("photo", "video") and bool(item.get("url"))

def _send_album_chunk(task_id: str, chat_id: int, chunk: list) -> None:
    """
    Sends a single album chunk of at most 10 items, falling back to sendPhoto/sendVideo if it has only 1.

    Args:
        task_id (str)

        chat_id (int)

        chunk (list):
            1-10 dicts, each {"type": "photo" | "video", "url": "..."}.

    Returns:
        None

    Notes:
        - A rejected send is reported as a Tier 1 delivery_failed event, attempted_type="album" - see error_handling.py.
          Applies even for a 1-item chunk sent via sendPhoto/sendVideo, since it's still logically part of the album task.
          A connection failure or unauthorized token (Tier 2) is already recorded internally - nothing further to do here.
    """
    if len(chunk) < 2:
        item = chunk[0]
        if item.get("type") == "video":
            result = send_video(chat_id, item.get("url"))
        else:
            result = send_photo(chat_id, item.get("url"))
    else:
        result = send_media_group(chat_id, chunk)

    if isinstance(result, dict):
        push_tier1_delivery_failed(task_id, "album", result.get("status_code"), result.get("reason"))

def _handle_album(task_id: str, chat_id: int, items: list) -> None:
    """
    Handle an album response payload - sends it via Telegram's sendMediaGroup endpoint.

    Args:
        task_id (str)

        chat_id (int)

        items (list):
            Dicts, each {"type": "photo" | "video", "url": "..."}.

    Returns:
        None

    Notes:
        - Dropped (and logged) if items is missing/invalid, or any item is invalid.
        - More than 10 items is split into chunks of 10 - see _send_album_chunk().
    """
    if not items or not isinstance(items, list):
        logger.error(f"Album payload for chat_id={chat_id} is missing a valid items list. Message dropped.")
    elif not all(_is_valid_album_item(item) for item in items):
        logger.error(f"Album payload for chat_id={chat_id} contains an item with a missing/invalid type or url. Message dropped.")
    elif len(items) > 10:
        logger.info(f"Album payload for chat_id={chat_id} has {len(items)} items. Splitting into multiple sends.")
        for start in range(0, len(items), 10):
            _send_album_chunk(task_id, chat_id, items[start:start + 10])
    else:
        _send_album_chunk(task_id, chat_id, items)

def _handle_file(task_id: str, chat_id: int, url: str, message: str) -> None:
    """
    Handle a file response payload - sends it via Telegram's sendDocument endpoint.

    Args:
        task_id (str)

        chat_id (int)

        url (str)

        message (str):
            Optional caption.

    Returns:
        None
    """
    _send_media_with_caption(send_document, "file", task_id, chat_id, url, message)

def _build_button_rows(chat_id: int, rows: list[list[dict]]) -> list[list[dict]]:
    """
    Registers each button spec into a bot-issued callback_data token, ready for send_message_with_buttons().

    Args:
        chat_id (int)

        rows (list[list[dict]]):
            Rows of button specs, each {"text": str, "purpose": str, "payload": dict (optional)}.

    Returns:
        list[list[dict]]:
            Rows of registered buttons, each {"text": str, "callback_data": str}.

    Notes:
        - A button that fails to register (see register_bot_button()) is dropped; a row left empty is dropped too.
    """
    built_rows = []
    for row in rows:
        built_row = [
            registered
            for button in row
            if (registered := register_bot_button(
                button.get("text"),
                button.get("purpose"),
                chat_id,
                button.get("payload")
            )) is not None
        ]
        if built_row:
            built_rows.append(built_row)

    return built_rows

def _handle_text(task_id: str, chat_id: int, message: str, buttons: list[list[dict]] | None = None) -> None:
    """
    Handle a text response payload - sends message to the user as-is, optionally with inline keyboard buttons.

    Args:
        task_id (str)

        chat_id (int)

        message (str)

        buttons (list[list[dict]] | None, optional):
            Rows of button specs - see _build_button_rows(). Defaults to None.

    Returns:
        None

    Notes:
        - Falls back to a plain send_message() if buttons is missing/empty, or if every button fails to register.
        - A rejected send (Telegram, or local validation - see send_message_with_buttons()) is reported as a Tier 1 delivery_failed event - see error_handling.py.
          A connection failure or unauthorized token (Tier 2) is already recorded internally - nothing further to do here.
    """
    rows = _build_button_rows(chat_id, buttons) if buttons else []
    if rows:
        result = send_message_with_buttons(chat_id, message, rows)
    else:
        result = send_message(chat_id, message)

    if isinstance(result, dict):
        push_tier1_delivery_failed(task_id, "text", result.get("status_code"), result.get("reason"))

def _format_duration(seconds: int) -> str | None:
    """
    Formats a duration in seconds into a short human-readable string.

    Args:
        seconds (int)

    Returns:
        str | None:
            e.g. "45 seconds", "2 hours 15 minutes" - or None if seconds is not positive.
    """
    if seconds <= 0:
        return None

    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"

    hours = minutes // 60
    remaining_minutes = minutes % 60
    if remaining_minutes:
        return f"{hours} hour{'s' if hours != 1 else ''} {remaining_minutes} minute{'s' if remaining_minutes != 1 else ''}"
    else:
        return f"{hours} hour{'s' if hours != 1 else ''}"

def _handle_completed(task_id: str) -> None:
    """
    Handle a completed marker payload - deletes the task's Redis mapping.

    Args:
        task_id (str)

    Returns:
        None
    """
    deleted = delete_task_mapping(task_id)
    logger.info(f"Task task_id={task_id} completed. Is mapping deleted successfully: {deleted}.")

def _handle_error(task_id: str, chat_id: int, error_type: str, message: str) -> None:
    """
    Handle an error payload - notifies the user and cleans up the task's Redis mapping.

    Args:
        task_id (str)

        chat_id (int)

        error_type (str)

        message (str):
            For "token_exhausted", nap_duration_left in seconds; otherwise free text.

    Returns:
        None

    Notes:
        - "token_exhausted": duration is omitted from the reply if message is missing/invalid.
        - Any other error_type: message is HTML-escaped and sent as-is (untrusted, agent-supplied).
    """
    if error_type == "token_exhausted":
        try:
            nap_duration_left = int(message)
        except (TypeError, ValueError):
            nap_duration_left = None

        duration_text = _format_duration(nap_duration_left) if nap_duration_left is not None else None

        if duration_text is not None:
            send_message(
                chat_id,
                f"{settings.TELEGRAM_BOT_NAME} is exhausted and is taking a nap.\n"
                f"{duration_text} left."
            )
        else:
            send_message(chat_id, f"{settings.TELEGRAM_BOT_NAME} is exhausted and is taking a nap.")
    else:
        send_message(
            chat_id,
            f"Oh nooo, {settings.TELEGRAM_BOT_NAME} is having difficulty managing a problem.\n"
            f"<b>Error:</b>\n"
            f"{html.escape(message or '')}",
            parse_mode="HTML"
        )

    deleted = delete_task_mapping(task_id)
    logger.info(f"Task task_id={task_id} errored (error_type={error_type}). Is mapping deleted successfully: {deleted}.")

def process_message(payload: str) -> None:
    """
    Handle a single message consumed from RabbitMQ.

    Args:
        payload (str):
            Raw JSON-encoded message body, expected to contain a task_id field.

    Returns:
        None

    Notes:
        - Invalid/non-object JSON, a missing task_id, an unknown task_id mapping, or an unrecognised type are each logged and dropped rather than raised.
        - Dispatches by data["type"] to a _handle_* function.
    """
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        logger.critical(f"Received RabbitMQ message with invalid JSON payload: {payload}")
        return

    if not isinstance(data, dict):
        logger.critical(f"Received RabbitMQ message with a non-object JSON payload: {payload}")
        return

    task_id = data.get("task_id")
    if not task_id:
        logger.critical(f"Received RabbitMQ message with missing task_id field: {payload}")
    else:
        stop_typing(task_id)

        mapping = get_task_mapping(task_id)
        if not mapping:
            logger.error(f"No task mapping found in Redis for task_id={task_id}. Message dropped.")
        else:
            chat_id = mapping.get("chat_id")
            user_id = mapping.get("user_id")

            message_type = data.get("type")
            if message_type == "poll":
                _handle_poll(
                    task_id,
                    chat_id,
                    data.get("question"),
                    data.get("options"),
                    data.get("allows_multiple_answers")
                )
            elif message_type == "image":
                _handle_image(task_id, chat_id, data.get("url"), data.get("caption"))
            elif message_type == "video":
                _handle_video(task_id, chat_id, data.get("url"), data.get("caption"))
            elif message_type == "album":
                _handle_album(task_id, chat_id, data.get("items"))
            elif message_type == "file":
                _handle_file(task_id, chat_id, data.get("url"), data.get("caption"))
            elif message_type == "text":
                _handle_text(task_id, chat_id, data.get("text"), data.get("buttons"))
            elif message_type == "completed":
                _handle_completed(task_id)
            elif message_type == "error":
                _handle_error(task_id, chat_id, data.get("error_type"), data.get("message"))
            else:
                logger.error(f"Received RabbitMQ message with unknown type={message_type}: {payload}")

            if message_type in ("poll", "image", "video", "album", "file", "text"):
                logger.info(f"Routed {message_type} response for task_id={task_id} (chat_id={chat_id}) to its handler.")

# =============================================================================
