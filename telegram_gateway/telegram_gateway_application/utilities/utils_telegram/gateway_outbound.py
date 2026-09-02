# =============================================================================
# File        : gateway_outbound.py
# Description : File responsible for sending outgoing messages back to the Telegram Bot API.
# Author      : SorinoSSK
# Created On  : 2026-08-29
#
# Features    :
#   - Sends text, typing action, polls (and closes them), and photo/video/document/album to a Telegram chat.
#
# Notes       :
#   - send_message/send_poll/stop_poll/send_document/send_photo/send_video/send_media_group all retry up to TELEGRAM_SEND_MAX_ATTEMPTS times (TELEGRAM_SEND_RETRY_DELAY apart) on connection failures/timeouts only; other failures are not retried.
#   - On a rejected (non-retried) request, send_message/send_poll/send_photo/send_video/send_document/send_media_group
#     return a {"error": True, "status_code", "reason"} dict instead of False/None (except a 401/404, which is Tier 2 -
#     see below) - callers use this to report a Tier 1 delivery_failed event (see utils_queue/error_handling.py) so the
#     backend can retry the same task differently. stop_poll/send_typing_action don't - see their own docstrings.
#   - A connection-exhausted failure, or a 401/404 (see _config_failure_reason()), is reported to
#     utils_queue/error_handling.py as a Tier 2 signal (record_send_failure()) regardless of which function it came
#     from - a successful send re-arms it (record_send_success()).
#
# =============================================================================
# I M P O R T   H E A D E R

import time
import logging
import requests

from ...config import settings
from ..utils_queue.error_handling import record_send_success, record_send_failure

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# =============================================================================

def _classify_rejection(exc: requests.exceptions.RequestException) -> tuple[int | None, str]:
    """
    Extracts an HTTP status code and Telegram's own error description from a rejected (non-retried) request.

    Args:
        exc (requests.exceptions.RequestException)

    Returns:
        tuple[int | None, str]:
            (status_code, reason). status_code is None if no response was ever received at all.
            reason falls back to str(exc) if Telegram's response body isn't parseable JSON.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return None, str(exc)

    try:
        reason = response.json().get("description") or str(exc)
    except ValueError:
        reason = str(exc)

    return response.status_code, reason

def _config_failure_reason(status_code: int | None) -> str | None:
    """
    Maps a rejection's HTTP status code to a Tier 2 "configuration" reason, if applicable.

    Args:
        status_code (int | None)

    Returns:
        str | None:
            "unauthorized" for 401 (invalid/revoked bot token), "not_found" for 404
            (every endpoint hit here is a fixed, hardcoded path, so a 404 can't mean
            "wrong URL" - it means the token doesn't resolve to a real bot). None otherwise.

    Notes:
        - Both are permanent, config-level failures - no per-task retry or different
          request content fixes either, so callers treat them identically to Tier 2
          (see error_handling.py::record_send_failure()), not as a Tier 1 rejection.
    """
    if status_code == 401:
        return "unauthorized"
    if status_code == 404:
        return "not_found"
    return None

def send_message(chat_id: int | str, text: str, parse_mode: str | None = None, reply_markup: dict | None = None) -> bool | dict:
    """
    Send a text message back to a Telegram chat via the Bot API.

    Args:
        chat_id (int | str)

        text (str)

        parse_mode (str | None, optional):
            e.g. "HTML" to enable tags like <b>. Defaults to None.

        reply_markup (dict | None, optional):
            Raw reply_markup (e.g. inline keyboard).
            See utils_telegram/utilities/button_prompt_handler.py for building/validating one.

    Returns:
        bool | dict:
            True if sent successfully. {"error": True, "status_code", "reason"} if Telegram rejected
            the request (Tier 1 - see module Notes). False if unreachable, unauthorized, or not found (Tier 2 -
            already recorded internally, nothing further for the caller to report).

    Notes:
        - Callers must escape untrusted text embedded alongside tags when parse_mode is set.
    """
    api_url = f"{settings.TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup

    for attempt in range(1, settings.TELEGRAM_SEND_MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                api_url,
                json=payload,
                timeout=settings.TELEGRAM_CLIENT_TIMEOUT
            )
            response.raise_for_status()
            logger.info(f"Sent message to chat_id={chat_id}.")
            record_send_success()
            return True
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < settings.TELEGRAM_SEND_MAX_ATTEMPTS:
                logger.warning(f"Failed to send message to Telegram (attempt {attempt}/{settings.TELEGRAM_SEND_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.TELEGRAM_SEND_RETRY_DELAY)
            else:
                logger.exception(f"Failed to send message to Telegram after {settings.TELEGRAM_SEND_MAX_ATTEMPTS} attempts.")
                record_send_failure("unreachable")
                return False
        except requests.exceptions.RequestException as exc:
            status_code, reason = _classify_rejection(exc)
            config_failure = _config_failure_reason(status_code)
            if config_failure:
                logger.exception(f"Failed to send message to Telegram - {config_failure}. Not retrying.")
                record_send_failure(config_failure, status_code)
                return False
            logger.exception("Failed to send message to Telegram. Not retrying.")
            return {"error": True, "status_code": status_code, "reason": reason}

def send_typing_action(chat_id: int | str) -> bool:
    """
    Send a "typing..." chat action to a Telegram chat via the Bot API.

    Args:
        chat_id (int | str)

    Returns:
        bool:
            True if sent successfully; otherwise False.

    Notes:
        - Telegram clears the indicator client-side after 5 seconds - see utilities/typing_indicator.py.
        - Not Tier 1-eligible - ephemeral, non-critical, not worth reporting per-task. Still feeds Tier 2
          (record_send_success()/record_send_failure()) on a connection failure or 401, since either is
          still evidence towards a systemic issue regardless of which endpoint hit it.
    """
    api_url = f"{settings.TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/sendChatAction"

    try:
        response = requests.post(
            api_url,
            json={
                "chat_id": chat_id,
                "action": "typing"
            },
            timeout=settings.TELEGRAM_CLIENT_TIMEOUT
        )
        response.raise_for_status()
        logger.debug(f"Sent typing action to chat_id={chat_id}.")
        record_send_success()
        return True
    except requests.exceptions.RequestException as exc:
        status_code, _ = _classify_rejection(exc)
        if status_code is None:
            record_send_failure("unreachable")
        else:
            config_failure = _config_failure_reason(status_code)
            if config_failure:
                record_send_failure(config_failure, status_code)
        logger.exception("Failed to send typing action to Telegram.")
        return False

def send_poll(chat_id: int | str, question: str, options: list, allows_multiple_answers: bool = False) -> dict | None:
    """
    Send a poll to a Telegram chat via the Bot API.

    Args:
        chat_id (int | str)

        question (str)

        options (list):
            Plain strings - converted to Telegram's InputPollOption shape internally.

        allows_multiple_answers (bool, optional):
            Defaults to False.

    Returns:
        dict | None:
            {"poll_id": str, "message_id": int} if sent successfully.
            {"error": True, "status_code", "reason"} if Telegram rejected the request (Tier 1 - see gateway_outbound.py module Notes).
            None if unreachable, unauthorized, or not found (Tier 2 - already recorded internally).

    Notes:
        - is_anonymous is not caller-configurable - always settings.TELEGRAM_POLL_ANONYMOUS,
          since correlating an answer back to a responder (see utils_telegram/utilities/poll_response_handler.py)
          requires a non-anonymous poll.
        - No open_period/close_date is set - Telegram caps these at 600s and they can't be
          adjusted once sent, which doesn't fit the debounced/extendable closing handled
          by poll_response_handler.py. The poll is closed explicitly via stop_poll() instead.
    """
    api_url = f"{settings.TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/sendPoll"

    payload = {
        "chat_id": chat_id,
        "question": question,
        "options": [{"text": option} for option in options],
        "is_anonymous": settings.TELEGRAM_POLL_ANONYMOUS,
        "allows_multiple_answers": allows_multiple_answers
    }

    for attempt in range(1, settings.TELEGRAM_SEND_MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                api_url,
                json=payload,
                timeout=settings.TELEGRAM_CLIENT_TIMEOUT
            )
            response.raise_for_status()
            result = response.json().get("result", {})
            poll_id = result.get("poll", {}).get("id")
            message_id = result.get("message_id")
            if not poll_id or message_id is None:
                logger.error(f"sendPoll response for chat_id={chat_id} is missing poll.id or message_id.")
                return None

            logger.info(f"Sent poll to chat_id={chat_id} (poll_id={poll_id}).")
            record_send_success()
            return {"poll_id": poll_id, "message_id": message_id}
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < settings.TELEGRAM_SEND_MAX_ATTEMPTS:
                logger.warning(f"Failed to send poll to Telegram (attempt {attempt}/{settings.TELEGRAM_SEND_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.TELEGRAM_SEND_RETRY_DELAY)
            else:
                logger.exception(f"Failed to send poll to Telegram after {settings.TELEGRAM_SEND_MAX_ATTEMPTS} attempts.")
                record_send_failure("unreachable")
                return None
        except requests.exceptions.RequestException as exc:
            status_code, reason = _classify_rejection(exc)
            config_failure = _config_failure_reason(status_code)
            if config_failure:
                logger.exception(f"Failed to send poll to Telegram - {config_failure}. Not retrying.")
                record_send_failure(config_failure, status_code)
                return None
            logger.exception("Failed to send poll to Telegram. Not retrying.")
            return {"error": True, "status_code": status_code, "reason": reason}

def stop_poll(chat_id: int | str, message_id: int) -> bool:
    """
    Closes an open poll via Telegram's stopPoll endpoint.

    Args:
        chat_id (int | str)

        message_id (int):
            The message_id of the poll, as returned by send_poll().

    Returns:
        bool:
            True if closed successfully; otherwise False.

    Notes:
        - stopPoll closes by chat_id + message_id, not poll_id.
        - Also returns False (logged, not retried) if the poll was already closed -
          callers that treat closing as best-effort cleanup should not fail hard on this.
        - Not Tier 1-eligible - closing is best-effort cleanup, not a delivery. Still feeds
          Tier 2 on a connection failure or 401 (see gateway_outbound.py module Notes).
    """
    api_url = f"{settings.TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/stopPoll"

    payload = {
        "chat_id": chat_id,
        "message_id": message_id
    }

    for attempt in range(1, settings.TELEGRAM_SEND_MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                api_url,
                json=payload,
                timeout=settings.TELEGRAM_CLIENT_TIMEOUT
            )
            response.raise_for_status()
            logger.info(f"Stopped poll for chat_id={chat_id} (message_id={message_id}).")
            record_send_success()
            return True
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < settings.TELEGRAM_SEND_MAX_ATTEMPTS:
                logger.warning(f"Failed to stop poll on Telegram (attempt {attempt}/{settings.TELEGRAM_SEND_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.TELEGRAM_SEND_RETRY_DELAY)
            else:
                logger.exception(f"Failed to stop poll on Telegram after {settings.TELEGRAM_SEND_MAX_ATTEMPTS} attempts.")
                record_send_failure("unreachable")
                return False
        except requests.exceptions.RequestException as exc:
            status_code, _ = _classify_rejection(exc)
            config_failure = _config_failure_reason(status_code)
            if config_failure:
                record_send_failure(config_failure, status_code)
            logger.exception(f"Failed to stop poll on Telegram for chat_id={chat_id} - already closed, or another error. Not retrying.")
            return False

def send_document(chat_id: int | str, url: str, caption: str | None = None) -> bool:
    """
    Send a file to a Telegram chat via the Bot API, from a URL.

    Args:
        chat_id (int | str)

        url (str):
            Publicly reachable URL Telegram will fetch the file from.

        caption (str | None, optional):
            Defaults to None.

    Returns:
        bool | dict:
            True if sent successfully. {"error": True, "status_code", "reason"} if Telegram rejected
            the request (Tier 1 - see module Notes). False if unreachable, unauthorized, or not found (Tier 2 -
            already recorded internally).

    Notes:
        - Telegram only supports sending a document by URL for .pdf and .zip files - other types are rejected (a multipart upload is not implemented).
    """
    api_url = f"{settings.TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/sendDocument"

    payload = {
        "chat_id": chat_id,
        "document": url
    }
    if caption:
        payload["caption"] = caption

    for attempt in range(1, settings.TELEGRAM_SEND_MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                api_url,
                json=payload,
                timeout=settings.TELEGRAM_CLIENT_TIMEOUT
            )
            response.raise_for_status()
            logger.info(f"Sent document to chat_id={chat_id}.")
            record_send_success()
            return True
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < settings.TELEGRAM_SEND_MAX_ATTEMPTS:
                logger.warning(f"Failed to send document to Telegram (attempt {attempt}/{settings.TELEGRAM_SEND_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.TELEGRAM_SEND_RETRY_DELAY)
            else:
                logger.exception(f"Failed to send document to Telegram after {settings.TELEGRAM_SEND_MAX_ATTEMPTS} attempts.")
                record_send_failure("unreachable")
                return False
        except requests.exceptions.RequestException as exc:
            status_code, reason = _classify_rejection(exc)
            config_failure = _config_failure_reason(status_code)
            if config_failure:
                logger.exception(f"Failed to send document to Telegram - {config_failure}. Not retrying.")
                record_send_failure(config_failure, status_code)
                return False
            logger.exception("Failed to send document to Telegram. Not retrying.")
            return {"error": True, "status_code": status_code, "reason": reason}

def send_photo(chat_id: int | str, url: str, caption: str | None = None) -> bool:
    """
    Send a photo to a Telegram chat via the Bot API, from a URL.

    Args:
        chat_id (int | str)

        url (str):
            Publicly reachable URL Telegram will fetch the photo from.

        caption (str | None, optional):
            Defaults to None.

    Returns:
        bool | dict:
            True if sent successfully. {"error": True, "status_code", "reason"} if Telegram rejected
            the request (Tier 1 - see module Notes). False if unreachable, unauthorized, or not found (Tier 2 -
            already recorded internally).
    """
    api_url = f"{settings.TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/sendPhoto"

    payload = {
        "chat_id": chat_id,
        "photo": url
    }
    if caption:
        payload["caption"] = caption

    for attempt in range(1, settings.TELEGRAM_SEND_MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                api_url,
                json=payload,
                timeout=settings.TELEGRAM_CLIENT_TIMEOUT
            )
            response.raise_for_status()
            logger.info(f"Sent photo to chat_id={chat_id}.")
            record_send_success()
            return True
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < settings.TELEGRAM_SEND_MAX_ATTEMPTS:
                logger.warning(f"Failed to send photo to Telegram (attempt {attempt}/{settings.TELEGRAM_SEND_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.TELEGRAM_SEND_RETRY_DELAY)
            else:
                logger.exception(f"Failed to send photo to Telegram after {settings.TELEGRAM_SEND_MAX_ATTEMPTS} attempts.")
                record_send_failure("unreachable")
                return False
        except requests.exceptions.RequestException as exc:
            status_code, reason = _classify_rejection(exc)
            config_failure = _config_failure_reason(status_code)
            if config_failure:
                logger.exception(f"Failed to send photo to Telegram - {config_failure}. Not retrying.")
                record_send_failure(config_failure, status_code)
                return False
            logger.exception("Failed to send photo to Telegram. Not retrying.")
            return {"error": True, "status_code": status_code, "reason": reason}

def send_video(chat_id: int | str, url: str, caption: str | None = None) -> bool:
    """
    Send a video to a Telegram chat via the Bot API, from a URL.

    Args:
        chat_id (int | str)

        url (str):
            Publicly reachable URL Telegram will fetch the video from.

        caption (str | None, optional):
            Defaults to None.

    Returns:
        bool | dict:
            True if sent successfully. {"error": True, "status_code", "reason"} if Telegram rejected
            the request (Tier 1 - see module Notes). False if unreachable, unauthorized, or not found (Tier 2 -
            already recorded internally).
    """
    api_url = f"{settings.TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/sendVideo"

    payload = {
        "chat_id": chat_id,
        "video": url
    }
    if caption:
        payload["caption"] = caption

    for attempt in range(1, settings.TELEGRAM_SEND_MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                api_url,
                json=payload,
                timeout=settings.TELEGRAM_CLIENT_TIMEOUT
            )
            response.raise_for_status()
            logger.info(f"Sent video to chat_id={chat_id}.")
            record_send_success()
            return True
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < settings.TELEGRAM_SEND_MAX_ATTEMPTS:
                logger.warning(f"Failed to send video to Telegram (attempt {attempt}/{settings.TELEGRAM_SEND_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.TELEGRAM_SEND_RETRY_DELAY)
            else:
                logger.exception(f"Failed to send video to Telegram after {settings.TELEGRAM_SEND_MAX_ATTEMPTS} attempts.")
                record_send_failure("unreachable")
                return False
        except requests.exceptions.RequestException as exc:
            status_code, reason = _classify_rejection(exc)
            config_failure = _config_failure_reason(status_code)
            if config_failure:
                logger.exception(f"Failed to send video to Telegram - {config_failure}. Not retrying.")
                record_send_failure(config_failure, status_code)
                return False
            logger.exception("Failed to send video to Telegram. Not retrying.")
            return {"error": True, "status_code": status_code, "reason": reason}

def send_media_group(chat_id: int | str, items: list) -> bool:
    """
    Send an album (2-10 items) to a Telegram chat via the Bot API.

    Args:
        chat_id (int | str)

        items (list):
            2-10 dicts, each {"type": "photo" | "video", "url": "..."}.

    Returns:
        bool | dict:
            True if sent successfully. {"error": True, "status_code", "reason"} if Telegram rejected
            the request (Tier 1 - see module Notes). False if unreachable, unauthorized, or not found (Tier 2 -
            already recorded internally).

    Notes:
        - No caption support - sendMediaGroup captions are set per item, not accepted here.
    """
    api_url = f"{settings.TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMediaGroup"

    payload = {
        "chat_id": chat_id,
        "media": [{"type": item.get("type"), "media": item.get("url")} for item in items]
    }

    for attempt in range(1, settings.TELEGRAM_SEND_MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                api_url,
                json=payload,
                timeout=settings.TELEGRAM_CLIENT_TIMEOUT
            )
            response.raise_for_status()
            logger.info(f"Sent album ({len(items)} items) to chat_id={chat_id}.")
            record_send_success()
            return True
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < settings.TELEGRAM_SEND_MAX_ATTEMPTS:
                logger.warning(f"Failed to send album to Telegram (attempt {attempt}/{settings.TELEGRAM_SEND_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.TELEGRAM_SEND_RETRY_DELAY)
            else:
                logger.exception(f"Failed to send album to Telegram after {settings.TELEGRAM_SEND_MAX_ATTEMPTS} attempts.")
                record_send_failure("unreachable")
                return False
        except requests.exceptions.RequestException as exc:
            status_code, reason = _classify_rejection(exc)
            config_failure = _config_failure_reason(status_code)
            if config_failure:
                logger.exception(f"Failed to send album to Telegram - {config_failure}. Not retrying.")
                record_send_failure(config_failure, status_code)
                return False
            logger.exception("Failed to send album to Telegram. Not retrying.")
            return {"error": True, "status_code": status_code, "reason": reason}

# =============================================================================
