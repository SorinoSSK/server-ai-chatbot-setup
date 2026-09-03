# =============================================================================
# File        : button_prompt_handler.py
# Description : File responsible for building inline-keyboard button prompts and validating the callback_query presses they generate.
# Author      : SorinoSSK
# Created On  : 2026-09-01
#
# Features    :
#   - Validates an inline keyboard against the Bot API's size limits (message length,
#     buttons per row, total buttons, callback_data byte length).
#   - Registers each button's callback_data against a purpose/chat_id/payload, generic
#     to any feature that wants to issue buttons (not specific to draft expiry).
#   - Validates an incoming callback_query.data as genuinely bot-issued, consuming it
#     so each press is single-use.
#
# Notes       :
#   - In-memory only - not persisted, resets on application restart.
#   - Locked because registration can happen from either the poll thread or the
#     RabbitMQ consumer thread, while validation happens on the poll thread.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging
import secrets
import threading
import time

from ....config import settings
from ..gateway_outbound import send_message

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_lock = threading.RLock()

# callback_data -> {"chat_id": int, "purpose": str, "payload": dict, "created_at": float}
_registered_callbacks: dict[str, dict] = {}

# =============================================================================

def _prune_expired_callbacks() -> None:
    """
    Removes callback_data entries from _registered_callbacks older than settings.TELEGRAM_CALLBACK_TTL_SECONDS.

    Args:
        None

    Returns:
        None
    """
    now = time.monotonic()
    with _lock:
        for token, entry in list(_registered_callbacks.items()):
            if now - entry["created_at"] > settings.TELEGRAM_CALLBACK_TTL_SECONDS:
                _registered_callbacks.pop(token, None)

def register_bot_button(text: str, purpose: str, chat_id: int, payload: dict | None = None) -> dict | None:
    """
    Generates a bot-issued callback_data token and registers it, ready to slot into a keyboard row.

    Args:
        text (str):
            Button label shown to the user.

        purpose (str):
            Caller-defined tag, read back from validate_bot_callback() to route the press.

        chat_id (int):
            Chat the button is sent to - a press is only valid from the same chat.

        payload (dict | None, optional):
            Caller-defined context retrieved alongside the press.

    Returns:
        dict | None:
            {"text": text, "callback_data": token} or None if text is empty.

    Notes:
        - Token is a random opaque string, not derived from purpose/payload.
    """
    if not text:
        logger.error("Refused to register a button with empty text.")
        return None

    _prune_expired_callbacks()

    token = secrets.token_urlsafe(24)
    with _lock:
        _registered_callbacks[token] = {
            "chat_id": chat_id,
            "purpose": purpose,
            "payload": payload or {},
            "created_at": time.monotonic()
        }

    logger.info(f"Registered button for chat_id={chat_id} (purpose={purpose!r}).")
    return {"text": text, "callback_data": token}

def validate_inline_buttons(rows: list[list[dict]]) -> dict | None:
    """
    Validates button rows against Telegram's inline keyboard limits, wrapping them into reply_markup if valid.

    Args:
        rows (list[list[dict]]):
            Rows of buttons, each {"text": str, "callback_data": str}.

    Returns:
        dict | None:
            {"inline_keyboard": rows} if within limits; otherwise None (logged).

    Notes:
        - Enforces TELEGRAM_BUTTONS_MAX_PER_ROW (8), TELEGRAM_BUTTONS_MAX_TOTAL (100), and TELEGRAM_CALLBACK_DATA_MAX_BYTES (64) per the Telegram Bot API.
        - No documented limit on button text length itself - not enforced here.
    """
    total_buttons = sum(len(row) for row in rows)
    if total_buttons == 0:
        logger.error("Refused to validate an inline keyboard with no buttons.")
        return None

    if total_buttons > settings.TELEGRAM_BUTTONS_MAX_TOTAL:
        logger.error(f"Refused to validate an inline keyboard with {total_buttons} buttons - exceeds the {settings.TELEGRAM_BUTTONS_MAX_TOTAL} button limit.")
        return None

    for row in rows:
        if len(row) > settings.TELEGRAM_BUTTONS_MAX_PER_ROW:
            logger.error(f"Refused to validate an inline keyboard row with {len(row)} buttons - exceeds the {settings.TELEGRAM_BUTTONS_MAX_PER_ROW} per-row limit.")
            return None

        for button in row:
            callback_data = button.get("callback_data") or ""
            if not button.get("text") or not callback_data:
                logger.error(f"Refused to validate an inline keyboard with an invalid button: {button}.")
                return None

            callback_data_bytes = len(callback_data.encode("utf-8"))
            if callback_data_bytes > settings.TELEGRAM_CALLBACK_DATA_MAX_BYTES:
                logger.error(f"Refused to validate an inline keyboard - callback_data is {callback_data_bytes} bytes, exceeds the {settings.TELEGRAM_CALLBACK_DATA_MAX_BYTES} byte limit.")
                return None

    return {"inline_keyboard": rows}

def send_message_with_buttons(chat_id: int | str, text: str, rows: list[list[dict]], parse_mode: str | None = None) -> bool | dict:
    """
    Sends a text message with an inline keyboard attached, validating both against Telegram's limits.

    Args:
        chat_id (int | str)

        text (str)

        rows (list[list[dict]]):
            Rows of buttons - see validate_inline_buttons().

        parse_mode (str | None, optional):
            See send_message(). Defaults to None.

    Returns:
        bool | dict:
            True if sent successfully.
            {"error": True, "status_code", "reason"} if either local validation failed, or Telegram rejected the request (Tier 1 - see utils_telegram/gateway_outbound.py module Notes; status_code is None for a local validation failure, since no request was ever sent).
            False if unreachable or unauthorized (Tier 2 - already recorded internally by send_message()).

    Notes:
        - Fails closed (no send) if text exceeds TELEGRAM_MESSAGE_MAX_LENGTH or the keyboard fails validation - unlike caption overflow elsewhere, text is not split into a follow-up, since the buttons must stay attached to this one message.
    """
    if len(text) > settings.TELEGRAM_MESSAGE_MAX_LENGTH:
        reason = f"text is {len(text)} characters, exceeds the {settings.TELEGRAM_MESSAGE_MAX_LENGTH} character limit"
        logger.error(f"Refused to send message to chat_id={chat_id} - {reason}.")
        return {"error": True, "status_code": None, "reason": reason}

    keyboard = validate_inline_buttons(rows)
    if keyboard is None:
        reason = "inline keyboard failed validation"
        logger.error(f"Refused to send message to chat_id={chat_id} - {reason}.")
        return {"error": True, "status_code": None, "reason": reason}

    return send_message(chat_id, text, parse_mode=parse_mode, reply_markup=keyboard)

def validate_bot_callback(callback_data: str, chat_id: int) -> dict | None:
    """
    Validates that callback_data was genuinely issued by the bot to this chat, consuming it.

    Args:
        callback_data (str):
            The callback_query.data received from Telegram.

        chat_id (int):
            The chat the callback_query came from.

    Returns:
        dict | None:
            {"purpose": str, "payload": dict} if valid; otherwise None (logged).

    Notes:
        - Single-use: removed from the registry regardless of outcome, so a replay can't be validated twice.
    """
    _prune_expired_callbacks()

    with _lock:
        entry = _registered_callbacks.pop(callback_data, None)

    if entry is None:
        logger.warning(f"Rejected callback_data from chat_id={chat_id} - not a currently registered bot-issued button (expired, already used, or forged).")
        return None

    if entry["chat_id"] != chat_id:
        logger.warning(f"Rejected callback_data from chat_id={chat_id} - registered to a different chat_id={entry['chat_id']}.")
        return None

    logger.info(f"Validated button press from chat_id={chat_id} (purpose={entry['purpose']!r}).")
    return {"purpose": entry["purpose"], "payload": entry["payload"]}

# =============================================================================
