# =============================================================================
# File        : gateway_inbound.py
# Description : File responsible for receiving incoming updates from the Telegram Bot API.
# Author      : SorinoSSK
# Created On  : 2026-08-29
#
# Features    :
#   - Long-polls the Telegram Bot API for new updates (messages, button presses, etc.)
#   - Resolves incoming photo/video/document to a fetchable URL and stages it as a
#     pending draft until an instruction (text) arrives, or the draft times out.
#
# Notes       :
#   - Uses Telegram's getUpdates long polling method, not webhooks.
#   - Updates missing a chat_id or user_id are logged as a warning and
#     skipped entirely - checked before the whitelist check.
#   - Updates from chats not in settings.TELEGRAM_ALLOWED_CHAT_IDS are
#     ignored. Note: Telegram's API has no server-side chat filter - every
#     update is still fetched from Telegram regardless of chat, filtering
#     only happens once it reaches this loop.
#   - Unauthorised chat_ids get a single reply via track_unauthorised_access() -
#     see utils_gatekeeper/gatekeeper.py for the cache/eviction behind this.
#     First-time unauthorised access is logged as a warning; repeats stay at debug.
#   - Media (photo/video/document) without an instruction is not queued as a task
#     immediately - it is staged as a Redis-backed draft (see utils_redis/database.py's
#     get/create/delete_chat_draft()) and only becomes a task once a text update
#     finalises it. See _draft_timer.py for the warning/hard-close timer that runs
#     while a draft is pending.
#   - Only one pending draft is allowed per chat_id at a time - further media
#     (single or part of an album) arriving while a draft is already pending is not
#     stored; the user is reminded about the existing draft instead.
#   - Album items (a media_group_id present on the message) are never staged as a
#     draft - Telegram delivers each item as its own separate update, so the user is
#     asked to resend them one at a time with individual instructions instead. The
#     reply is deduped per media_group_id so a multi-item album does not receive one
#     reply per item.
#   - Accepted updates get a task_id via create_task_mapping() before being
#     queued - chat_id/user_id live only in Redis, keyed by task_id. The queued
#     payload is {task_id, text, image_url, video_url, file_url} - at most one of
#     the three URL fields is ever non-empty, the other two are "".
#   - If task mapping or the RabbitMQ push fails, the sender is notified
#     directly (with a different message per failure) instead of queueing
#     the update. queue_push_task() itself retries RabbitMQ connection
#     failures - see queue.py - so a notification here implies retries
#     were already exhausted.
#   - start_typing() begins only after queue_push_task() succeeds - the typing
#     indicator has no meaning until an agent is actually able to pick up the task.
#   - offset only advances after an update is fully handled (including the
#     failure-notification paths above), not on receipt - an unexpected
#     exception mid-update leaves it unconfirmed, so Telegram redelivers it.
#     Retried up to TELEGRAM_UPDATE_MAX_ATTEMPTS times (see _update_attempts),
#     then given up on and skipped. Since offset is a single watermark, a
#     retry-pending update halts the rest of its batch - see poll_updates().
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
from .typing_indicator import start_typing
from .draft_timer import start_draft_timer, stop_draft_timer

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_stop_polling_event = ShutdownSignal()

# Tracks failed attempts for the single update currently blocking offset advancement.
# In-memory only - never holds more than one entry, since a retry-pending update
# halts the batch (see poll_updates()) rather than letting others advance past it.
_update_attempts: dict[int, int] = {}

# Dedupes the "please resend one at a time" album reply per media_group_id - Telegram
# delivers each album item as its own separate update, all sharing one media_group_id.
# In-memory only - only ever touched from poll_updates()'s single thread, no lock needed.
_recent_media_groups: dict[str, float] = {}

# Maps a draft's media_type to the queue payload field it belongs in.
_MEDIA_FIELD_NAMES = {"image": "image_url", "video": "video_url", "file": "file_url"}

# =============================================================================

def _extract_chat_id(update: dict) -> int | None:
    """
    Extract the chat ID from a Telegram Update object, regardless of event type.

    Args:
        - update (dict):
            A single Update object as returned by the getUpdates endpoint.

    Returns:
        - int | None:
            The chat ID the update belongs to, or None if the event type is
            not one that carries a chat (e.g. inline_query).

    Notes:
        - Covers message, edited_message, and callback_query only - see the README event-types doc; extend for other types.
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
        - update (dict):
            A single Update object as returned by the getUpdates endpoint.

    Returns:
        - int | None:
            The user ID that sent the update, or None if the event type is
            not one that carries a sender.

    Notes:
        - Covers message, edited_message, and callback_query only - see the README event-types doc; extend for other types.
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
        - message (dict):
            The "message" (or "edited_message") object of an Update.

    Returns:
        - dict | None:
            {"media_type": "image" | "video" | "file", "file_id": str,
             "caption": str | None, "media_group_id": str | None}
            or None if the message carries no photo/video/document.

    Notes:
        - photo/video/document are mutually exclusive on a single Telegram message.
        - Photos arrive as an array of resolutions - the last entry is the largest,
          per Telegram's documented ordering (smallest -> largest).
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
        - file_id (str)

    Returns:
        - str | None:
            The download URL if resolved successfully; otherwise None.

    Notes:
        - The resulting URL embeds settings.TELEGRAM_BOT_TOKEN and is only guaranteed
          valid by Telegram for at least 1 hour from this call - callers should not
          resolve it far in advance of when it will actually be used, and should not log it.
        - Retries up to settings.TELEGRAM_SEND_MAX_ATTEMPTS times, waiting settings.TELEGRAM_SEND_RETRY_DELAY
          seconds between attempts - but only for connection failures/timeouts. Any other failure (e.g. an
          authorisation error, or an invalid/expired file_id) is not retried, since retrying would not change the outcome.
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

def _should_reply_to_album(media_group_id: str) -> bool:
    """
    Determines whether an album reply should be sent for this media_group_id, deduping repeats.

    Args:
        - media_group_id (str)

    Returns:
        - bool:
            True if this is the first item seen for this media_group_id (a reply
            should be sent); otherwise False.

    Notes:
        - Entries are pruned by age (settings.MEDIA_GROUP_DEDUPE_SECONDS) rather than an
          explicit "album finished" signal, since Telegram gives no such signal - album
          items simply arrive as a short burst of separate updates sharing one media_group_id.
    """
    now = time.monotonic()
    for group_id, seen_at in list(_recent_media_groups.items()):
        if now - seen_at > settings.MEDIA_GROUP_DEDUPE_SECONDS:
            _recent_media_groups.pop(group_id, None)

    if media_group_id in _recent_media_groups:
        return False

    _recent_media_groups[media_group_id] = now
    return True

def _send_still_curious(chat_id: int, media_type: str) -> None:
    """
    Replies that a pending draft's media is still on file, ignoring newly arrived media.

    Args:
        - chat_id (int)
        - media_type (str):
            "image" | "video" | "file" - the pending draft's media_type.

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
        - chat_id (int)
        - user_id (int)
        - text (str)
        - image_url (str, optional)
        - video_url (str, optional)
        - file_url (str, optional)

    Returns:
        None

    Notes:
        - At most one of image_url/video_url/file_url is expected to be non-empty -
          all three are always present in the queued payload, empty ones as "".
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

def _handle_update(chat_id: int, user_id: int, update: dict) -> None:
    """
    Routes an accepted (authorised) update through the media/draft/finalisation flow.

    Args:
        - chat_id (int)
        - user_id (int)
        - update (dict)

    Returns:
        None

    Notes:
        - See module Notes above for the overall draft flow this implements.
    """
    message = update.get("message") or update.get("edited_message") or {}
    media = _extract_media(message)

    if media and media["media_group_id"]:
        if _should_reply_to_album(media["media_group_id"]):
            existing_draft = get_chat_draft(chat_id)
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

    Args:
        None

    Returns:
        None:
            Runs until stop_polling() is called and does not return a meaningful value.

    Raises:
        None:
            Request and unexpected errors are caught internally to keep the
            polling loop alive.

    Notes:
        - Requires settings.TELEGRAM_BOT_TOKEN to be set.
        - stop_polling() may take up to TELEGRAM_POLL_TIMEOUT + TELEGRAM_CLIENT_TIMEOUT to take effect if a request is in flight.
        - Filters event types via allowed_updates; chat filtering is separate - see _extract_chat_id().
        - Requires Redis to be initialised - see create_task_mapping().
        - An update that fails unexpectedly halts the rest of its batch (break) -
          offset cannot skip past it while still retrying it. See _update_attempts.
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
        - Sets the stop event checked at the top of each poll_updates() iteration.
        - Does not interrupt an in-flight request (see poll_updates() notes).
        - Does not wait for the polling loop to actually terminate.
    """
    _stop_polling_event.set()

# =============================================================================
