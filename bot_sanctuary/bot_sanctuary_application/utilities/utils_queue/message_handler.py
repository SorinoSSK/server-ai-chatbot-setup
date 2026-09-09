# =============================================================================
# File        : message_handler.py
# Description : Determines the effective type of each message consumed from RabbitMQ and routes it accordingly.
# Author      : SorinoSSK
# Created On  : 2026-09-07
#
# Features    :
#   - Message type resolution and routing for every message consumed from RabbitMQ.
#   - Systemic gateway_alert/gateway_recover notification handling, throttled and Redis-backed.
#   - Session-scoped message routing to the owning per-session worker.
#   - Session teardown handling on session_cleared - stops the owning SessionWorker (if any) and removes
#     that session_id's on-disk session directory (see utils_session/session_worker.py).
#
# Notes       :
#   - Owns its own JSON parsing so a malformed payload is logged and dropped rather than requeued forever.
#   - See README.md for the full message routing and gateway_alert/gateway_recover notification design.
#
# =============================================================================
# I M P O R T   H E A D E R

import json
import logging

from ...config import settings
from ..utils_smtp.smtp_handler import send_mail
from ..utils_redis.database import (
    record_gateway_alert_occurrence,
    should_notify_gateway_alert,
    mark_gateway_alert_notified,
    reset_gateway_alert_throttle
)
from ..utils_session.session_worker import clear_session_directory, get_or_create_session_worker, remove_session_worker

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# =============================================================================

def _build_gateway_alert_message() -> str:
    """
    Builds the gateway_alert notification email's body text.

    Args:
        None

    Returns:
        str

    Notes:
        - Uses settings.TELEGRAM_BOT_NAME (falling back to "The bot" if unset) rather than a hardcoded persona name.
    """
    bot_name = settings.TELEGRAM_BOT_NAME or "The bot"
    return (
        f"Hello brother,\n\n"
        f"{bot_name} is having some trouble sending message out of telegram. "
        f"it appear to be dead, just letting you know that {bot_name} might not be available."
    )

def _handle_gateway_alert(data: dict) -> None:
    """
    Handles a gateway_alert (systemic) event - telegram_gateway itself cannot reach Telegram.

    Args:
        data (dict):
            Decoded gateway_alert payload.

    Returns:
        None

    Notes:
        - Every occurrence is logged critically and counted, regardless of whether a notification is actually sent.
        - The notification email itself is throttled - a suppressed occurrence is logged at INFO, not silently dropped.
    """
    reason = data.get("reason")
    status_code = data.get("status_code")
    occurrence_count = record_gateway_alert_occurrence()
    logger.critical(
        f"Received gateway_alert from telegram_gateway: reason={reason}, status_code={status_code} "
        f"(occurrence #{occurrence_count if occurrence_count is not None else '?'})."
    )

    if not should_notify_gateway_alert():
        logger.info(
            f"gateway_alert notification suppressed - already notified within the last "
            f"{settings.GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS}s."
        )
        return
    elif not settings.SMTP_TO_EMAIL:
        logger.error("Cannot send gateway_alert notification - SMTP_TO_EMAIL is unset.")
        return
    else:
        bot_name = settings.TELEGRAM_BOT_NAME or "The bot"
        sent = send_mail(
            subject=f"{bot_name} - Telegram Gateway Alert",
            body=_build_gateway_alert_message(),
            to_addresses=settings.SMTP_TO_EMAIL
        )
        if sent:
            mark_gateway_alert_notified()
            logger.info("gateway_alert notification email sent.")
        else:
            logger.error("gateway_alert notification email failed to send - see send_mail()'s own log above. Not marking as notified, so the next occurrence retries.")

def _handle_gateway_recover(data: dict) -> None:
    """
    Handles a gateway_recover (systemic) event - telegram_gateway has successfully sent again after a prior alert.

    Args:
        data (dict):
            Decoded gateway_recover payload.

    Returns:
        None

    Notes:
        - Resets the gateway_alert throttle, so a future, unrelated incident starts fresh.
    """
    status_code = data.get("status_code")
    logger.info(f"Received gateway_recover from telegram_gateway (status_code={status_code}) - clearing gateway_alert throttle.")
    reset_gateway_alert_throttle()

def _handle_session_cleared(data: dict) -> None:
    """
    Handles a session_cleared acknowledgement, stopping any worker owning the named session and removing
    its on-disk session directory.

    Args:
        data (dict):
            Decoded session_cleared payload.

    Returns:
        None

    Notes:
        - No active worker for the named session is a normal, expected case, and is logged at INFO rather than as a warning.
        - clear_session_directory() is called unconditionally (even if no worker was found) - a session's
          on-disk directory can outlive its SessionWorker (e.g. after a prior stop() without a matching
          clear), so this does not skip cleanup just because nothing was currently active. The next message
          for this session_id builds a brand new SessionWorker (and a fresh generation subfolder) from
          scratch - see utils_session/session_worker.py's own Notes on why a fresh generation matters.
    """
    session_id = data.get("session_id")
    if not session_id:
        logger.error(f"Received session_cleared with missing session_id. Message dropped: {data}")
    else:
        worker = remove_session_worker(session_id)
        if worker is not None:
            worker.stop()
            logger.info(f"Stopped SessionWorker for session_id={session_id} following session_cleared (chat_id={data.get('chat_id')}).")
        else:
            logger.info(f"Received session_cleared for session_id={session_id} (chat_id={data.get('chat_id')}) - no active SessionWorker found, nothing to stop.")

        clear_session_directory(session_id)

def _dispatch_to_session(data: dict) -> None:
    """
    Routes a session-scoped message to its owning session worker, creating one if this is a new session.

    Args:
        data (dict):
            Decoded session-scoped payload (a task, poll_timed_out, or delivery_failed message).

    Returns:
        None

    Raises:
        RuntimeError:
            If the owning session's inbox is full - propagated so the message is not acknowledged and remains eligible for redelivery.

    Notes:
        - A missing session_id is a permanently malformed message and is logged and dropped rather than raised.
    """
    session_id = data.get("session_id")
    if not session_id:
        logger.error(f"Received session-scoped message with missing session_id. Message dropped: {data}")
    else:
        if not get_or_create_session_worker(session_id).submit(data):
            raise RuntimeError(f"Session inbox full for session_id={session_id} (task_id={data.get('task_id')}) - not yet acked, eligible for redelivery.")

def process_message(payload: str) -> None:
    """
    Handle a single message consumed from RabbitMQ.

    Args:
        payload (str):
            Raw JSON-encoded message body.

    Returns:
        None

    Notes:
        - Invalid/non-object JSON is logged and dropped rather than raised.
        - The Task Queue Payload (see telegram_gateway/README.md) carries no explicit "type" field - treated here as an implicit "task" type.
    """
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        logger.critical(f"Received RabbitMQ message with invalid JSON payload: {payload}")
        return

    if not isinstance(data, dict):
        logger.critical(f"Received RabbitMQ message with a non-object JSON payload: {payload}")
        return
    else:
        message_type = data.get("type") or "task"

        if message_type == "gateway_alert":
            _handle_gateway_alert(data)
        elif message_type == "gateway_recover":
            _handle_gateway_recover(data)
        elif message_type == "session_cleared":
            _handle_session_cleared(data)
        else:
            _dispatch_to_session(data)

# =============================================================================
