# =============================================================================
# File        : message_handler.py
# Description : File responsible for handling messages consumed from RabbitMQ.
# Author      : SorinoSSK
# Created On  : 2026-09-07
#
# Features    :
#   - Decodes each message from Q_CHANNEL_IN and determines its effective type.
#     The Task Queue Payload (see telegram_gateway/README.md) carries no explicit "type" field - treated here as an implicit "task" type, alongside "poll_timed_out"/"delivery_failed" (also session-routable).
#     The two remaining types are not session-routable: "gateway_alert" (systemic, task_id/session_id both null) and "session_cleared" (a session teardown signal, not further work for a session).
#   - _handle_gateway_alert() notifies SMTP_TO_EMAIL by mail, throttled to at most once every GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS (default 24h) via the Redis-backed throttle in utils_redis/database.py - every occurrence is still counted regardless of whether a notification is actually sent for it.
#
# Notes       :
#   - Owns its own JSON parsing so a malformed payload is logged and dropped rather than requeued forever.
#   - Session routing (per-session worker threads - see bot_sanctuary/CODE_TODO.md §3) is not implemented yet - _dispatch_to_session() is currently a placeholder that logs and drops.
#     Wiring it to an actual session registry/worker is deliberately deferred to a follow-up change; this file's current scope is RabbitMQ connectivity only.
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
    mark_gateway_alert_notified
)

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
        - Uses settings.TELEGRAM_BOT_NAME (falling back to "The bot" if unset) rather than a hardcoded persona name, same convention already used for the SMTP From header (utils_smtp/smtp_handler.py) and for telegram_gateway's own user-facing persona messages (e.g. message_handler.py's "{TELEGRAM_BOT_NAME} is exhausted and is taking a nap.").
    """
    bot_name = settings.TELEGRAM_BOT_NAME or "The bot"
    return (
        f"Hello brother,\n\n"
        f"{bot_name} is having some trouble sending message out of telegram. "
        f"it appear to be dead, just letting you know that {bot_name} might not be available."
    )

def _handle_gateway_alert(data: dict) -> None:
    """
    Handles a gateway_alert (Tier 2, systemic) event - telegram_gateway itself cannot reach Telegram, so no per-session routing applies (task_id/session_id are both null on this payload).

    Args:
        data (dict)

    Returns:
        None

    Notes:
        - Every occurrence is logged critically and counted in Redis (record_gateway_alert_occurrence()), regardless of whether a notification email is actually sent for it - see module Features.
        - The notification email itself is throttled to at most once every GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS (should_notify_gateway_alert()) - a suppressed occurrence is logged at INFO, not silently dropped.
        - mark_gateway_alert_notified() is only called after a successful send - a failed send (SMTP down, SMTP_ENABLE_MAILER unset, etc.) leaves the cooldown untouched so the next occurrence retries, rather than a failed attempt silently consuming the day's one notification.
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

def _handle_session_cleared(data: dict) -> None:
    """
    Handles a session_cleared acknowledgement - the session_id it names has just been wiped on the gateway side, so any owning session worker should stop rather than receive further work.

    Args:
        data (dict)

    Returns:
        None

    Notes:
        - Placeholder: only logs for now.
          Intended to reap the corresponding session worker and drop it from the session registry once that layer exists - see bot_sanctuary/CODE_TODO.md §3.
    """
    logger.info(
        f"Received session_cleared for session_id={data.get('session_id')} (chat_id={data.get('chat_id')}). "
        f"Session worker teardown not yet implemented - see CODE_TODO.md §3."
    )

def _dispatch_to_session(data: dict) -> None:
    """
    Routes a session-scoped message (an implicit task, poll_timed_out, or delivery_failed) to its owning session worker, creating one if this is a new session_id.

    Args:
        data (dict)

    Returns:
        None

    Notes:
        - Placeholder: only logs and drops for now.
          Intended to look up/create a session worker keyed by session_id and hand data to its inbox once that layer exists - see bot_sanctuary/CODE_TODO.md §3.
    """
    session_id = data.get("session_id")
    if not session_id:
        logger.error(f"Received session-scoped message with missing session_id. Message dropped: {data}")
    else:
        logger.warning(
            f"Session routing not yet implemented - dropping message for session_id={session_id} "
            f"(task_id={data.get('task_id')}, type={data.get('type') or 'task'}). See CODE_TODO.md §3."
        )

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
        elif message_type == "session_cleared":
            _handle_session_cleared(data)
        else:
            _dispatch_to_session(data)

# =============================================================================
