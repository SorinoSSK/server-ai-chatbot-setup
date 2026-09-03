# =============================================================================
# File        : gateway_inbound.py
# Description : File responsible for receiving incoming updates from the Telegram Bot API.
# Author      : SorinoSSK
# Created On  : 2026-08-29
#
# Features    :
#   - Long-polls the Telegram Bot API for new updates (messages, button presses, poll answers, etc.)
#   - Resolves incoming photo/video/document to a fetchable URL and stages it as a
#     pending draft until an instruction (text) arrives, or the draft times out.
#
# Notes       :
#   - Uses Telegram's getUpdates long polling method, not webhooks.
#   - Updates missing a chat_id/user_id, or from a chat not in TELEGRAM_ALLOWED_CHAT_IDS, are skipped (unauthorised chats get one reply - see utils_gatekeeper/gatekeeper.py).
#   - poll_answer updates carry no chat_id of their own and are routed separately - see _handle_poll_answer() - correlating instead via the poll's own Redis mapping (see utils_telegram/utilities/poll_response_handler.py).
#   - Media without an instruction is staged as a Redis-backed draft (see utils_redis/database.py) until a text update finalises it, or it times out - see utilities/image_draft_handler.py.
#   - Only one pending draft per chat_id at a time.
#   - Album items (media_group_id) are never staged as a draft - the user is asked to resend one at a time; the reply is deduped per media_group_id.
#   - Accepted updates get a task_id via create_task_mapping() before being queued - chat_id/user_id live only in Redis, keyed by task_id.
#   - offset only advances once an update is fully handled - a failed update is retried up to TELEGRAM_UPDATE_MAX_ATTEMPTS times, halting its batch meanwhile.
#
# =============================================================================
# I M P O R T   H E A D E R

import time
import json
import logging
import requests

from ...config import settings
from ..utilities import ShutdownSignal
from ..utils_gatekeeper.gatekeeper import track_unauthorised_access
from ..utils_queue.queue import queue_push_task
from ..utils_redis.database import create_task_mapping, get_chat_draft, create_chat_draft, delete_chat_draft
from .gateway_outbound import send_message
from .utilities.typing_indicator import start_typing
from .utilities.image_draft_handler import start_draft_timer, stop_draft_timer, continue_draft_timer
from .utilities.button_prompt_handler import validate_bot_callback
from .utilities.poll_response_handler import handle_poll_answer

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_stop_polling_event = ShutdownSignal()

# Tracks failed attempts for the single update currently blocking offset advancement.
# In-memory only - never holds more than one entry, since a retry-pending update halts the batch (see poll_updates()) rather than letting others advance past it.
_update_attempts: dict[int, int] = {}

# Dedupes the "please resend one at a time" album reply per media_group_id - Telegram delivers each album item as its own separate update, all sharing one media_group_id.
# In-memory only - only ever touched from poll_updates()'s single thread, no lock needed.
_recent_media_groups: dict[str, float] = {}

# Maps a draft's media_type to the queue payload field it belongs in.
_MEDIA_FIELD_NAMES = {"image": "image_url", "video": "video_url", "file": "file_url"}

# =============================================================================

def _extract_chat_id(update: dict) -> int | None:
    """
    Extract the chat ID from a Telegram Update object, regardless of event type.

    Args:
        update (dict)

    Returns:
        int | None:
            The chat ID, or None if the event type carries no chat.

    Notes:
        - Covers message, edited_message, and callback_query only.
    """
    if "message" in update:
        return update["message"].get("chat", {}).get("id")
    if "edited_message" in update:
        return update["edited_message"].get("chat", {}).get("id")
    if "callback_query" in update:
        return update["callback_query"].get("message", {}).get("chat", {}).get("id")
    return None

def _extract_user_id(update: dict) -> int | None:
    """
    Extract the sender's user ID from a Telegram Update object, regardless of event type.

    Args:
        update (dict)

    Returns:
        int | None:
            The sender's user ID, or None if the event type carries no sender.

    Notes:
        - Covers message, edited_message, and callback_query only.
    """
    if "message" in update:
        return update["message"].get("from", {}).get("id")
    if "edited_message" in update:
        return update["edited_message"].get("from", {}).get("id")
    if "callback_query" in update:
        return update["callback_query"].get("from", {}).get("id")
    return None

def _extract_media(message: dict) -> dict | None:
    """
    Extracts photo/video/document details from a Telegram message, if present.

    Args:
        message (dict):
            The "message" (or "edited_message") object of an Update.

    Returns:
        dict | None:
            {"media_type", "file_id", "caption", "media_group_id"} or None if no media.

    Notes:
        - Photos arrive as an array of resolutions - the last entry is the largest.
    """
    if message.get("photo"):
        file_id = message["photo"][-1].get("file_id")
        media_type = "image"
    elif message.get("video"):
        file_id = message["video"].get("file_id")
        media_type = "video"
    elif message.get("document"):
        file_id = message["document"].get("file_id")
        media_type = "file"
    else:
        return None

    return {
        "media_type": media_type,
        "file_id": file_id,
        "caption": message.get("caption"),
        "media_group_id": message.get("media_group_id")
    }

def _resolve_file_url(file_id: str) -> str | None:
    """
    Resolves a Telegram file_id to a temporary, publicly-fetchable download URL via getFile.

    Args:
        file_id (str)

    Returns:
        str | None:
            The download URL if resolved successfully; otherwise None.

    Notes:
        - URL embeds the bot token and is only guaranteed valid for at least 1 hour - do not resolve it far in advance, and do not log it.
    """
    api_url = f"{settings.TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/getFile"

    for attempt in range(1, settings.TELEGRAM_SEND_MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                api_url,
                json={"file_id": file_id},
                timeout=settings.TELEGRAM_CLIENT_TIMEOUT
            )
            response.raise_for_status()
            file_path = response.json().get("result", {}).get("file_path")
            if not file_path:
                logger.error(f"getFile response for file_id={file_id} is missing file_path.")
                return None
            return f"{settings.TELEGRAM_API_BASE_URL}/file/bot{settings.TELEGRAM_BOT_TOKEN}/{file_path}"
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < settings.TELEGRAM_SEND_MAX_ATTEMPTS:
                logger.warning(f"Failed to resolve file_id={file_id} via getFile (attempt {attempt}/{settings.TELEGRAM_SEND_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.TELEGRAM_SEND_RETRY_DELAY)
            else:
                logger.exception(f"Failed to resolve file_id={file_id} via getFile after {settings.TELEGRAM_SEND_MAX_ATTEMPTS} attempts.")
                return None
        except requests.exceptions.RequestException:
            logger.exception(f"Failed to resolve file_id={file_id} via getFile. Not retrying.")
            return None

def _prune_recent_media_groups() -> None:
    """
    Removes media_group_id entries from _recent_media_groups older than settings.MEDIA_GROUP_DEDUPE_SECONDS.

    Args:
        None

    Returns:
        None
    """
    now = time.monotonic()
    for group_id, seen_at in list(_recent_media_groups.items()):
        if now - seen_at > settings.MEDIA_GROUP_DEDUPE_SECONDS:
            _recent_media_groups.pop(group_id, None)

def _should_reply_to_album(media_group_id: str) -> bool:
    """
    Determines whether an album reply should be sent for this media_group_id, deduping repeats.

    Args:
        media_group_id (str)

    Returns:
        bool:
            True if this is the first item seen for this media_group_id; otherwise False.

    Notes:
        - Pruned by age (MEDIA_GROUP_DEDUPE_SECONDS), not an "album finished" signal - Telegram gives no such signal.
        - Pruning itself happens in _handle_update().
    """
    if media_group_id in _recent_media_groups:
        return False

    _recent_media_groups[media_group_id] = time.monotonic()
    return True

def _send_still_curious(chat_id: int, media_type: str) -> None:
    """
    Replies that a pending draft's media is still on file, ignoring newly arrived media.

    Args:
        chat_id (int)

        media_type (str):
            "image" | "video" | "file" - used to word the reply message.

    Returns:
        None
    """
    send_message(
        chat_id,
        f"{settings.TELEGRAM_BOT_NAME} is still curious about the {media_type} you sent earlier - "
        f"is there anything you'd like {settings.TELEGRAM_BOT_NAME} to do with it?"
    )

def _push_task(chat_id: int, user_id: int, text: str, image_url: str = "", video_url: str = "", file_url: str = "") -> None:
    """
    Creates a task mapping and pushes the task payload to RabbitMQ, notifying the user on failure.

    Args:
        chat_id (int)

        user_id (int)

        text (str)

        image_url (str, optional):
            Defaults to "".

        video_url (str, optional):
            Defaults to "".

        file_url (str, optional):
            Defaults to "".

    Returns:
        None

    Notes:
        - At most one of image_url/video_url/file_url is expected to be non-empty.
        - start_typing() begins only after queue_push_task() succeeds.
    """
    task_id = create_task_mapping(chat_id, user_id)
    if not task_id:
        logger.error(f"Failed to create task mapping for chat_id={chat_id}. Message dropped.")
        send_message(
            chat_id,
            f"{settings.TELEGRAM_BOT_NAME} have been working hard and might be sick. "
            f"Could you check on {settings.TELEGRAM_BOT_NAME}?"
        )
    elif not queue_push_task({
        "task_id": task_id,
        "text": text or "",
        "image_url": image_url or "",
        "video_url": video_url or "",
        "file_url": file_url or ""
    }):
        logger.error(f"Failed to push task_id={task_id} to RabbitMQ for chat_id={chat_id}. Message dropped.")
        send_message(
            chat_id,
            f"{settings.TELEGRAM_BOT_NAME} is bedridden and will try to help you when "
            f"{settings.TELEGRAM_BOT_NAME} gets better."
        )
    else:
        start_typing(task_id, chat_id)
        logger.info(f"Pushed task_id={task_id} for chat_id={chat_id} to the outbound queue.")

def _handle_poll_answer(poll_answer: dict) -> None:
    """
    Routes a poll_answer update to poll_response_handler.py's debounce loop.

    Args:
        poll_answer (dict):
            Telegram's PollAnswer object - {"poll_id", "user", "option_ids", ...}.

    Returns:
        None

    Notes:
        - Carries no chat_id of its own - correlates back to one via the poll_id mapping created when the poll was sent (see message_handler.py::_handle_poll()).
          No separate TELEGRAM_ALLOWED_CHAT_IDS check is needed here, since that mapping only ever exists for a poll the gateway itself sent to an already-authorised chat.
        - A poll_id with no active timer (unknown, already closed, or expired) is logged and ignored, rather than treated as an error.
    """
    poll_id = poll_answer.get("poll_id")
    user_id = (poll_answer.get("user") or {}).get("id")
    option_ids = poll_answer.get("option_ids") or []

    if not poll_id or user_id is None:
        logger.warning(f"Ignored invalid poll_answer update: {poll_answer}")
    elif not handle_poll_answer(poll_id, user_id, option_ids):
        logger.warning(f"Received poll_answer for unknown/already-closed poll_id={poll_id}.")

def _handle_update(chat_id: int, user_id: int, update: dict) -> None:
    """
    Routes an accepted (authorised) update through the media/draft/finalisation flow.

    Args:
        chat_id (int)

        user_id (int)

        update (dict)

    Returns:
        None

    Notes:
        - See module Notes above for the overall draft flow.
        - Prunes _recent_media_groups on every update, not just album items.
        - callback_query updates are validated via validate_bot_callback() here, rather than falling through to the text branch (which would otherwise read them as empty-text).
        - "draft_continue" (see utils_telegram/utilities/image_draft_handler.py) is the only callback purpose currently wired up; any other purpose is logged and otherwise ignored.
    """
    _prune_recent_media_groups()

    if "callback_query" in update:
        callback_data = update["callback_query"].get("data") or ""
        result = validate_bot_callback(callback_data, chat_id)
        if result is None:
            logger.warning(f"Ignored unrecognised callback_query from chat_id={chat_id}.")
        elif result["purpose"] == "draft_continue":
            if not continue_draft_timer(chat_id):
                logger.warning(f"Received draft_continue callback for chat_id={chat_id} but no active draft timer.")
        else:
            logger.info(
                f"Validated callback_query from chat_id={chat_id} for purpose={result['purpose']!r} "
                f"- no handler wired up for this purpose yet."
            )
        return

    message = update.get("message") or update.get("edited_message") or {}
    media = _extract_media(message)

    if media and media["media_group_id"]:
        if _should_reply_to_album(media["media_group_id"]):
            existing_draft = get_chat_draft(chat_id)
            logger.info(f"Prompted chat_id={chat_id} to resend album (media_group_id={media['media_group_id']}) items individually.")
            if existing_draft:
                _send_still_curious(chat_id, existing_draft["media_type"])
            else:
                send_message(
                    chat_id,
                    f"Ooh, {settings.TELEGRAM_BOT_NAME} loves a good album! Could you send them one "
                    f"at a time with instructions for each, please?"
                )
        return

    if media:
        existing_draft = get_chat_draft(chat_id)
        if existing_draft:
            logger.info(f"New {media['media_type']} for chat_id={chat_id} ignored - {existing_draft['media_type']} draft already pending.")
            _send_still_curious(chat_id, existing_draft["media_type"])
            return

        media_url = _resolve_file_url(media["file_id"])
        if not media_url:
            logger.error(f"Failed to resolve file_id={media['file_id']} for chat_id={chat_id}. Draft not created.")
            send_message(
                chat_id,
                f"{settings.TELEGRAM_BOT_NAME} had trouble receiving that - could you try resending it?"
            )
            return

        caption = media["caption"] or ""
        if create_chat_draft(chat_id, media["media_type"], media_url, caption, bool(caption)):
            start_draft_timer(chat_id, media["media_type"])
        else:
            logger.error(f"Failed to create draft for chat_id={chat_id}. Message dropped.")
        return

    text = message.get("text") or ""
    existing_draft = get_chat_draft(chat_id)
    if existing_draft:
        stop_draft_timer(chat_id)
        delete_chat_draft(chat_id)
        logger.info(f"Finalising {existing_draft['media_type']} draft for chat_id={chat_id} into a task.")

        if existing_draft["has_caption"] and existing_draft["text"]:
            final_text = f"{existing_draft['text']} {text}".strip()
        else:
            final_text = text

        field_name = _MEDIA_FIELD_NAMES[existing_draft["media_type"]]
        _push_task(chat_id, user_id, final_text, **{field_name: existing_draft["media_url"]})
    else:
        _push_task(chat_id, user_id, text)

def poll_updates() -> None:
    """
    Long-polls Telegram's getUpdates endpoint for new updates, advancing the offset per handled update.

    Runs until stop_polling() is called. Errors are caught internally to keep the loop alive.

    Args:
        None

    Returns:
        None

    Notes:
        - stop_polling() may take up to TELEGRAM_POLL_TIMEOUT + TELEGRAM_CLIENT_TIMEOUT to take effect if a request is in flight.
        - Requires Redis to be initialised - see create_task_mapping().
    """
    api_url = f"{settings.TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = None

    while not _stop_polling_event.is_terminating():
        try:
            # Timeout is the maximum time telegram will hold the connection open before returning an empty result.
            params = {
                "timeout": settings.TELEGRAM_POLL_TIMEOUT,
                "allowed_updates": json.dumps(settings.TELEGRAM_ALLOWED_UPDATES)
            }
            if offset is not None:
                params["offset"] = offset

            # Timeout is the maximum time the request will wait for a response before raising a timeout exception.
            response = requests.get(
                api_url,
                params=params,
                timeout=settings.TELEGRAM_POLL_TIMEOUT + settings.TELEGRAM_CLIENT_TIMEOUT
            )
            response.raise_for_status()
            payload = response.json()

            for update in payload.get("result", []):
                update_id = update["update_id"]

                try:
                    if "poll_answer" in update:
                        # Carries no chat_id of its own - see _handle_poll_answer() Notes.
                        _handle_poll_answer(update["poll_answer"])
                    else:
                        chat_id = _extract_chat_id(update)
                        user_id = _extract_user_id(update)

                        if chat_id is None or user_id is None:
                            logger.warning(f"Ignored invalid update - missing chat_id or user_id: {update}")
                        elif chat_id not in settings.TELEGRAM_ALLOWED_CHAT_IDS:
                            if track_unauthorised_access(chat_id):
                                logger.warning(f"First unauthorised access from chat_id={chat_id}: {update}")
                                send_message(
                                    chat_id,
                                    f"Hello, I'm {settings.TELEGRAM_BOT_NAME}! I'd love to get to know you, but I only "
                                    f"talk to family for now. Could you ask my brother to let you in?\n"
                                    f"Just share this chatroom ID with him: <code>{chat_id}</code>",
                                    parse_mode="HTML"
                                )
                            else:
                                logger.debug(f"Ignored update from unauthorised chat_id={chat_id}: {update}")
                        else:
                            logger.info(f"Received Telegram update: {update}")
                            _handle_update(chat_id, user_id, update)

                    # Only confirmed to Telegram once fully handled - see offset Notes above.
                    offset = update_id + 1
                    _update_attempts.pop(update_id, None)

                except Exception:
                    attempts = _update_attempts.get(update_id, 0) + 1
                    _update_attempts[update_id] = attempts

                    if attempts >= settings.TELEGRAM_UPDATE_MAX_ATTEMPTS:
                        logger.exception(f"Giving up on update_id={update_id} after {attempts} failed attempts: {update}")
                        offset = update_id + 1
                        _update_attempts.pop(update_id, None)
                    else:
                        logger.exception(f"Unexpected error processing update_id={update_id} (attempt {attempts}/{settings.TELEGRAM_UPDATE_MAX_ATTEMPTS}). Will retry next poll.")
                        break

        except requests.exceptions.RequestException:
            logger.exception("Telegram long polling request failed. Retrying...")
            time.sleep(5)
        except Exception:
            logger.exception("Unexpected error during Telegram long polling.")
            time.sleep(5)

def stop_polling() -> None:
    """
    Stop the Telegram long polling loop.

    Args:
        None

    Returns:
        None

    Notes:
        - Does not interrupt an in-flight request, nor wait for the loop to actually terminate.
    """
    _stop_polling_event.set()

# =============================================================================
