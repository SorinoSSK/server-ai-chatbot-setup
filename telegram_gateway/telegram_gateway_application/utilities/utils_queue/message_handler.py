# =============================================================================
# File        : message_handler.py
# Description : File responsible for handling messages consumed from RabbitMQ.
# Author      : SorinoSSK
# Created On  : 2026-08-29
#
# Features    :
#   - Dispatches incoming queue messages by type - poll/image/video/album/file/text/completed/error.
#     See README.md for the payload shape per type.
#
# Notes       :
#   - Owns its own JSON parsing (not pre-parsed by queue.py's consumer callback) so
#     a permanently malformed payload can be logged and dropped, rather than nacked
#     and requeued forever - see queue_consume_task()'s callback for the ack/nack split.
#   - Stops the typing indicator for task_id as soon as any message is received for
#     it - a response of any kind means "typing" no longer applies, regardless of
#     what type of action this message turns out to be.
#   - Resolves chat_id/user_id from Redis via task_id - this is the only place
#     that identity mapping is looked up on the response path.
#
# =============================================================================
# I M P O R T   H E A D E R

import html
import json
import logging

from ...config import settings
from ..utils_redis.database import get_task_mapping, delete_task_mapping
from ..utils_telegram.gateway_outbound import send_message, send_poll, send_photo, send_video, send_media_group, send_document
from ..utils_telegram.typing_indicator import stop_typing

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# =============================================================================

def _handle_poll(chat_id: int, question: str, options: list, is_anonymous: bool, allows_multiple_answers: bool) -> None:
    """
    Handle a poll response payload - sends it via Telegram's sendPoll endpoint.

    Args:
        - chat_id (int)
        - question (str)
        - options (list)
        - is_anonymous (bool)
        - allows_multiple_answers (bool)

    Returns:
        None

    Notes:
        - Sending is skipped (and logged) if question is missing.
        - Null/invalid entries in options are filtered out rather than rejecting the
          whole poll - unlike _handle_album(), which drops the entire payload if any
          item is invalid.
    """
    if not question:
        logger.error(f"Poll payload for chat_id={chat_id} is missing a question. Message dropped.")
    else:
        valid_options = [option for option in (options or []) if option]
        send_poll(chat_id, question, valid_options, is_anonymous, allows_multiple_answers)

def _send_media_with_caption(send_func, chat_id: int, url: str, message: str) -> None:
    """
    Sends media via send_func, splitting an overlong caption into a separate follow-up text message.

    Args:
        - send_func (Callable[[int, str, str | None], bool]):
            One of send_photo, send_video, send_document - all share this (chat_id, url, caption) shape.
        - chat_id (int)
        - url (str)
        - message (str)

    Returns:
        None

    Notes:
        - Telegram caps captions at settings.TELEGRAM_CAPTION_MAX_LENGTH characters and
          rejects the entire send outright if exceeded, rather than truncating it itself -
          so the caption is split here first, and anything beyond the cap is sent as a
          separate sendMessage instead of causing the whole send to fail.
        - The remainder is only sent if send_func succeeds - a failed primary send means
          there is no message the remainder would be captioning, so it is not sent either.
    """
    if message and len(message) > settings.TELEGRAM_CAPTION_MAX_LENGTH:
        caption = message[:settings.TELEGRAM_CAPTION_MAX_LENGTH]
        remainder = message[settings.TELEGRAM_CAPTION_MAX_LENGTH:]
        if send_func(chat_id, url, caption):
            send_message(chat_id, remainder)
    else:
        send_func(chat_id, url, message)

def _handle_image(chat_id: int, url: str, message: str) -> None:
    """
    Handle an image response payload - sends it via Telegram's sendPhoto endpoint.

    Args:
        - chat_id (int)
        - url (str)
        - message (str):
            Optional caption.

    Returns:
        None
    """
    _send_media_with_caption(send_photo, chat_id, url, message)

def _handle_video(chat_id: int, url: str, message: str) -> None:
    """
    Handle a video response payload - sends it via Telegram's sendVideo endpoint.

    Args:
        - chat_id (int)
        - url (str)
        - message (str):
            Optional caption.

    Returns:
        None
    """
    _send_media_with_caption(send_video, chat_id, url, message)

def _is_valid_album_item(item: dict) -> bool:
    """
    Checks whether an album item has a valid type and url.

    Args:
        - item (dict)

    Returns:
        - bool:
            True if item has type "photo" or "video" and a non-empty url; otherwise False.
    """
    return isinstance(item, dict) and item.get("type") in ("photo", "video") and bool(item.get("url"))

def _send_album_chunk(chat_id: int, chunk: list) -> None:
    """
    Sends a single album chunk of at most 10 items, falling back to sendPhoto/sendVideo if it has only 1.

    Args:
        - chat_id (int)
        - chunk (list):
            1-10 dicts, each {"type": "photo" | "video", "url": "..."}.

    Returns:
        None
    """
    if len(chunk) < 2:
        item = chunk[0]
        if item.get("type") == "video":
            send_video(chat_id, item.get("url"))
        else:
            send_photo(chat_id, item.get("url"))
    else:
        send_media_group(chat_id, chunk)

def _handle_album(chat_id: int, items: list) -> None:
    """
    Handle an album response payload - sends it via Telegram's sendMediaGroup endpoint.

    Args:
        - chat_id (int)
        - items (list):
            Dicts, each {"type": "photo" | "video", "url": "..."}.

    Returns:
        None

    Notes:
        - Sending is skipped (and logged) if items is missing/not a list, or if any
          item has a missing/invalid type or url - see _is_valid_album_item().
        - More than 10 items is split into multiple sends, chunked at 10 each - see
          _send_album_chunk(), including its single-item fallback for the final chunk
          if the total count is not a multiple of 10.
    """
    if not items or not isinstance(items, list):
        logger.error(f"Album payload for chat_id={chat_id} is missing a valid items list. Message dropped.")
    elif not all(_is_valid_album_item(item) for item in items):
        logger.error(f"Album payload for chat_id={chat_id} contains an item with a missing/invalid type or url. Message dropped.")
    elif len(items) > 10:
        logger.info(f"Album payload for chat_id={chat_id} has {len(items)} items. Splitting into multiple sends.")
        for start in range(0, len(items), 10):
            _send_album_chunk(chat_id, items[start:start + 10])
    else:
        _send_album_chunk(chat_id, items)

def _handle_file(chat_id: int, url: str, message: str) -> None:
    """
    Handle a file response payload - sends it via Telegram's sendDocument endpoint.

    Args:
        - chat_id (int)
        - url (str)
        - message (str):
            Optional caption.

    Returns:
        None
    """
    _send_media_with_caption(send_document, chat_id, url, message)

def _handle_text(chat_id: int, message: str) -> None:
    """
    Handle a text response payload - sends message to the user as-is.

    Args:
        - chat_id (int)
        - message (str)

    Returns:
        None
    """
    send_message(chat_id, message)

def _format_duration(seconds: int) -> str | None:
    """
    Formats a duration in seconds into a short human-readable string.

    Args:
        - seconds (int)

    Returns:
        - str | None:
            e.g. "45 seconds", "5 minutes", "2 hours 15 minutes" - or None if seconds is not positive.
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
        - task_id (str)

    Returns:
        None

    Notes:
        - delete_task_mapping() is a safe no-op if the mapping is already gone (e.g. TTL expiry).
    """
    deleted = delete_task_mapping(task_id)
    logger.info(f"Task task_id={task_id} completed. Is mapping deleted successfully: {deleted}.")

def _handle_error(task_id: str, chat_id: int, error_type: str, message: str) -> None:
    """
    Handle an error payload - notifies the user and cleans up the task's Redis mapping.

    Args:
        - task_id (str)
        - chat_id (int)
        - error_type (str)
        - message (str):
            For "token_exhausted", this carries the nap_duration_left in seconds (a
            countdown, not a fixed total) - reused rather than a separate field. For
            any other error_type, this is free-text sent back to the user as-is.

    Returns:
        None

    Notes:
        - "token_exhausted": message is parsed as nap_duration_left (seconds remaining).
          If it is missing, not a valid number, or not positive (see _format_duration()),
          the duration is simply omitted from the reply rather than failing.
        - Anything else (unknown error_type): responds with a sweeter wrapper around message,
          using Telegram's HTML parse_mode - message is escaped since it is untrusted, agent-supplied text.
        - Same cleanup as _handle_completed() - deletes the task's Redis mapping.
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
        - payload (str):
            Raw JSON-encoded message body, expected to contain a task_id field.

    Returns:
        None

    Notes:
        - Invalid JSON is logged as critical and dropped (returns without raising) -
          this results in an ack, not a requeue, since a malformed payload will
          never succeed no matter how many times it is redelivered.
        - stop_typing() is a safe no-op if no typing loop is active for task_id.
        - A missing Redis mapping (e.g. expired TTL, or an unknown task_id) is logged and dropped.
        - Dispatches by data["type"] to a _handle_* function.
        - An unrecognised type is logged and dropped.
        - Valid JSON that is not a JSON object (e.g. a bare number/string/array) is also
          logged and dropped - same as invalid JSON, since data.get(...) below requires
          a dict and this would otherwise raise instead of failing gracefully.
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
                    chat_id,
                    data.get("question"),
                    data.get("options"),
                    data.get("is_anonymous"),
                    data.get("allows_multiple_answers")
                )
            elif message_type == "image":
                _handle_image(chat_id, data.get("url"), data.get("caption"))
            elif message_type == "video":
                _handle_video(chat_id, data.get("url"), data.get("caption"))
            elif message_type == "album":
                _handle_album(chat_id, data.get("items"))
            elif message_type == "file":
                _handle_file(chat_id, data.get("url"), data.get("caption"))
            elif message_type == "text":
                _handle_text(chat_id, data.get("text"))
            elif message_type == "completed":
                _handle_completed(task_id)
            elif message_type == "error":
                _handle_error(task_id, chat_id, data.get("error_type"), data.get("message"))
            else:
                logger.error(f"Received RabbitMQ message with unknown type={message_type}: {payload}")

# =============================================================================
