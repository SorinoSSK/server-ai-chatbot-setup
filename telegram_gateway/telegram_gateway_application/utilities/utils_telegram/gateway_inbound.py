# =============================================================================
# File        : gateway_inbound.py
# Description : File responsible for receiving incoming updates from the Telegram Bot API.
# Author      : SorinoSSK
# Created On  : 2026-08-29
#
# Features    :
#   - Long-polls the Telegram Bot API for new updates (messages, button presses, etc.)
#
# Notes       :
#   - Uses Telegram's getUpdates long polling method, not webhooks.
#   - Updates from chats not in settings.TELEGRAM_ALLOWED_CHAT_IDS are
#     ignored. Note: Telegram's API has no server-side chat filter - every
#     update is still fetched from Telegram regardless of chat, filtering
#     only happens once it reaches this loop.
#   - Accepted updates get a task_id via create_task_mapping() before being
#     queued - chat_id/user_id live only in Redis, keyed by task_id.
#   - If task mapping fails, the sender is notified directly instead of
#     queueing the update.
#
# =============================================================================
# I M P O R T   H E A D E R

import json
import time
import logging
import requests

from ...config import settings
from ..utilities import ShutdownSignal
from ..utils_queue.queue import queue_push_task
from ..utils_redis.database import create_task_mapping
from .gateway_outbound import send_message

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_stop_polling_event = ShutdownSignal()

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

def poll_updates() -> None:
    """
    Long-polls Telegram's getUpdates endpoint for new updates, advancing the offset each batch.

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
        - stop_polling() may take up to TELEGRAM_POLL_TIMEOUT + 10s to take effect if a request is in flight.
        - Filters event types via allowed_updates; chat filtering is separate - see _extract_chat_id().
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
                timeout=settings.TELEGRAM_POLL_TIMEOUT + 10
            )
            response.raise_for_status()
            payload = response.json()

            for update in payload.get("result", []):
                offset = update["update_id"] + 1

                chat_id = _extract_chat_id(update)
                if chat_id not in settings.TELEGRAM_ALLOWED_CHAT_IDS:
                    logger.debug(f"Ignored update from unauthorised chat_id={chat_id}: {update}")
                else:
                    logger.info(f"Received Telegram update: {update}")
                    task_id = create_task_mapping(chat_id, _extract_user_id(update))
                    if task_id:
                        queue_push_task({"task_id": task_id, "update": update})
                    else:
                        logger.error(f"Failed to create task mapping for chat_id={chat_id}. Message dropped.")
                        send_message(
                            chat_id,
                            f"{settings.TELEGRAM_BOT_NAME} have been working hard and might be sick. "
                            f"Could you check on {settings.TELEGRAM_BOT_NAME}?"
                        )

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
