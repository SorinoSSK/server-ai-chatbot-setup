# =============================================================================
# File        : gateway_outbound.py
# Description : File responsible for sending outgoing messages back to the Telegram Bot API.
# Author      : SorinoSSK
# Created On  : 2026-08-29
#
# Features    :
#   - Sends a text message back to a Telegram chat via the sendMessage endpoint.
#   - Sends a "typing..." chat action via the sendChatAction endpoint.
#   - Sends a poll to a Telegram chat via the sendPoll endpoint.
#   - Sends a file to a Telegram chat via the sendDocument endpoint.
#   - Sends a photo, video, or album to a Telegram chat via sendPhoto/sendVideo/sendMediaGroup.
#
# =============================================================================
# I M P O R T   H E A D E R

import time
import logging
import requests

from ...config import settings

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# =============================================================================

def send_message(chat_id: int | str, text: str, parse_mode: str | None = None) -> bool:
    """
    Send a text message back to a Telegram chat via the Bot API.

    Args:
        - chat_id (int | str):
            Identifier of the Telegram chat to send the message to.

        - text (str):
            Message content to send.

        - parse_mode (str | None, optional):
            Telegram formatting mode (e.g. "HTML") to enable tags like <b> in text. Defaults to None (plain text).

    Returns:
        - bool:
            True if the message was sent successfully; otherwise False.

    Notes:
        - Callers are responsible for escaping any untrusted text embedded alongside
          intentional tags when parse_mode is set - unescaped <, >, or & in untrusted
          content can break the formatting or the request entirely.
        - Retries up to settings.TELEGRAM_SEND_MAX_ATTEMPTS times, waiting settings.TELEGRAM_SEND_RETRY_DELAY
          seconds between attempts - but only for connection failures/timeouts. Any other failure (e.g. an
          authorisation error) is not retried, since retrying would not change the outcome.
    """
    api_url = f"{settings.TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    for attempt in range(1, settings.TELEGRAM_SEND_MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                api_url,
                json=payload,
                timeout=settings.TELEGRAM_CLIENT_TIMEOUT
            )
            response.raise_for_status()
            return True
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < settings.TELEGRAM_SEND_MAX_ATTEMPTS:
                logger.warning(f"Failed to send message to Telegram (attempt {attempt}/{settings.TELEGRAM_SEND_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.TELEGRAM_SEND_RETRY_DELAY)
            else:
                logger.exception(f"Failed to send message to Telegram after {settings.TELEGRAM_SEND_MAX_ATTEMPTS} attempts.")
                return False
        except requests.exceptions.RequestException:
            logger.exception("Failed to send message to Telegram. Not retrying.")
            return False

def send_typing_action(chat_id: int | str) -> bool:
    """
    Send a "typing..." chat action to a Telegram chat via the Bot API.

    Args:
        - chat_id (int | str):
            Identifier of the Telegram chat to send the action to.

    Returns:
        - bool:
            True if the action was sent successfully; otherwise False.

    Notes:
        - Telegram clears the indicator client-side after 5 seconds - see utils_telegram/typing_indicator.py for repeated calls.
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
        return True
    except requests.exceptions.RequestException:
        logger.exception("Failed to send typing action to Telegram.")
        return False

def send_poll(chat_id: int | str, question: str, options: list, is_anonymous: bool = True, allows_multiple_answers: bool = False) -> bool:
    """
    Send a poll to a Telegram chat via the Bot API.

    Args:
        - chat_id (int | str):
            Identifier of the Telegram chat to send the poll to.

        - question (str)

        - options (list):
            Plain option strings - converted to Telegram's required InputPollOption shape internally.

        - is_anonymous (bool, optional):
            Defaults to True.

        - allows_multiple_answers (bool, optional):
            Defaults to False.

    Returns:
        - bool:
            True if the poll was sent successfully; otherwise False.

    Notes:
        - Telegram requires options as an Array of InputPollOption (each {"text": "..."}),
          not plain strings - this function does that conversion.
        - Retries up to settings.TELEGRAM_SEND_MAX_ATTEMPTS times, waiting settings.TELEGRAM_SEND_RETRY_DELAY
          seconds between attempts - but only for connection failures/timeouts. Any other failure (e.g. an
          authorisation error) is not retried, since retrying would not change the outcome.
    """
    api_url = f"{settings.TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/sendPoll"

    payload = {
        "chat_id": chat_id,
        "question": question,
        "options": [{"text": option} for option in options],
        "is_anonymous": is_anonymous,
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
            return True
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < settings.TELEGRAM_SEND_MAX_ATTEMPTS:
                logger.warning(f"Failed to send poll to Telegram (attempt {attempt}/{settings.TELEGRAM_SEND_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.TELEGRAM_SEND_RETRY_DELAY)
            else:
                logger.exception(f"Failed to send poll to Telegram after {settings.TELEGRAM_SEND_MAX_ATTEMPTS} attempts.")
                return False
        except requests.exceptions.RequestException:
            logger.exception("Failed to send poll to Telegram. Not retrying.")
            return False

def send_document(chat_id: int | str, url: str, caption: str | None = None) -> bool:
    """
    Send a file to a Telegram chat via the Bot API, from a URL.

    Args:
        - chat_id (int | str):
            Identifier of the Telegram chat to send the file to.

        - url (str):
            Publicly reachable URL Telegram will fetch the file from.

        - caption (str | None, optional):
            Defaults to None.

    Returns:
        - bool:
            True if the file was sent successfully; otherwise False.

    Notes:
        - Telegram only supports sending a document by URL for .pdf and .zip files - any
          other file type sent this way will be rejected by Telegram; a direct multipart
          upload would be required instead, which this function does not implement.
        - Retries up to settings.TELEGRAM_SEND_MAX_ATTEMPTS times, waiting settings.TELEGRAM_SEND_RETRY_DELAY
          seconds between attempts - but only for connection failures/timeouts. Any other failure (e.g. an
          authorisation error) is not retried, since retrying would not change the outcome.
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
            return True
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < settings.TELEGRAM_SEND_MAX_ATTEMPTS:
                logger.warning(f"Failed to send document to Telegram (attempt {attempt}/{settings.TELEGRAM_SEND_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.TELEGRAM_SEND_RETRY_DELAY)
            else:
                logger.exception(f"Failed to send document to Telegram after {settings.TELEGRAM_SEND_MAX_ATTEMPTS} attempts.")
                return False
        except requests.exceptions.RequestException:
            logger.exception("Failed to send document to Telegram. Not retrying.")
            return False

def send_photo(chat_id: int | str, url: str, caption: str | None = None) -> bool:
    """
    Send a photo to a Telegram chat via the Bot API, from a URL.

    Args:
        - chat_id (int | str):
            Identifier of the Telegram chat to send the photo to.

        - url (str):
            Publicly reachable URL Telegram will fetch the photo from.

        - caption (str | None, optional):
            Defaults to None.

    Returns:
        - bool:
            True if the photo was sent successfully; otherwise False.

    Notes:
        - Retries up to settings.TELEGRAM_SEND_MAX_ATTEMPTS times, waiting settings.TELEGRAM_SEND_RETRY_DELAY
          seconds between attempts - but only for connection failures/timeouts. Any other failure (e.g. an
          authorisation error) is not retried, since retrying would not change the outcome.
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
            return True
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < settings.TELEGRAM_SEND_MAX_ATTEMPTS:
                logger.warning(f"Failed to send photo to Telegram (attempt {attempt}/{settings.TELEGRAM_SEND_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.TELEGRAM_SEND_RETRY_DELAY)
            else:
                logger.exception(f"Failed to send photo to Telegram after {settings.TELEGRAM_SEND_MAX_ATTEMPTS} attempts.")
                return False
        except requests.exceptions.RequestException:
            logger.exception("Failed to send photo to Telegram. Not retrying.")
            return False

def send_video(chat_id: int | str, url: str, caption: str | None = None) -> bool:
    """
    Send a video to a Telegram chat via the Bot API, from a URL.

    Args:
        - chat_id (int | str):
            Identifier of the Telegram chat to send the video to.

        - url (str):
            Publicly reachable URL Telegram will fetch the video from.

        - caption (str | None, optional):
            Defaults to None.

    Returns:
        - bool:
            True if the video was sent successfully; otherwise False.

    Notes:
        - Retries up to settings.TELEGRAM_SEND_MAX_ATTEMPTS times, waiting settings.TELEGRAM_SEND_RETRY_DELAY
          seconds between attempts - but only for connection failures/timeouts. Any other failure (e.g. an
          authorisation error) is not retried, since retrying would not change the outcome.
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
            return True
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < settings.TELEGRAM_SEND_MAX_ATTEMPTS:
                logger.warning(f"Failed to send video to Telegram (attempt {attempt}/{settings.TELEGRAM_SEND_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.TELEGRAM_SEND_RETRY_DELAY)
            else:
                logger.exception(f"Failed to send video to Telegram after {settings.TELEGRAM_SEND_MAX_ATTEMPTS} attempts.")
                return False
        except requests.exceptions.RequestException:
            logger.exception("Failed to send video to Telegram. Not retrying.")
            return False

def send_media_group(chat_id: int | str, items: list) -> bool:
    """
    Send an album (2-10 items) to a Telegram chat via the Bot API.

    Args:
        - chat_id (int | str):
            Identifier of the Telegram chat to send the album to.

        - items (list):
            2-10 dicts, each {"type": "photo" | "video", "url": "..."}.

    Returns:
        - bool:
            True if the album was sent successfully; otherwise False.

    Notes:
        - No caption support - sendMediaGroup captions are set per item, not accepted here.
        - Retries up to settings.TELEGRAM_SEND_MAX_ATTEMPTS times, waiting settings.TELEGRAM_SEND_RETRY_DELAY
          seconds between attempts - but only for connection failures/timeouts. Any other failure (e.g. an
          authorisation error) is not retried, since retrying would not change the outcome.
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
            return True
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < settings.TELEGRAM_SEND_MAX_ATTEMPTS:
                logger.warning(f"Failed to send album to Telegram (attempt {attempt}/{settings.TELEGRAM_SEND_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.TELEGRAM_SEND_RETRY_DELAY)
            else:
                logger.exception(f"Failed to send album to Telegram after {settings.TELEGRAM_SEND_MAX_ATTEMPTS} attempts.")
                return False
        except requests.exceptions.RequestException:
            logger.exception("Failed to send album to Telegram. Not retrying.")
            return False

# =============================================================================
