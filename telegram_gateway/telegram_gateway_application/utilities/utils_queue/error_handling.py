# =============================================================================
# File        : error_handling.py
# Description : Builds and pushes delivery-failure events onto Q_CHANNEL_OUT, split into Tier 1 (per-task, actionable) and Tier 2 (systemic, not actionable by any single task) failures.
# Author      : SorinoSSK
# Created On  : 2026-09-02
#
# Features    :
#   - Tier 1 - push_tier1_delivery_failed(): a specific send was rejected by Telegram, or failed local validation before ever reaching Telegram.
#     Reported per task_id, since the backend/orchestrator can react by retrying that same task differently (e.g. a different content type, a shorter message).
#   - Tier 2 - record_send_success()/record_send_failure(): Telegram is unreachable altogether, or the bot token itself is invalid/revoked (401/404) - not tied to any one task, since no per-task retry/tool-swap fixes either.
#     Tracks a rolling consecutive-failure count and fires a gateway_alert once per incident, re-arming only once a send succeeds again.
#
# Notes       :
#   - Deferred import of queue_push_task to avoid a circular import (queue.py -> message_handler.py -> ... -> queue.py), same pattern as utils_telegram/utilities/poll_response_handler.py::_push_poll_answer().
#   - Tier 2's counter/armed-state is in-memory only and resets on restart - acceptable, since a restart is itself a fresh start at reassessing whether Telegram is reachable.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging
import threading

from ...config import settings

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_consecutive_failures = 0
_alert_armed = True

# =============================================================================

def push_tier1_delivery_failed(task_id: str, attempted_type: str, status_code: int | None, reason: str) -> bool:
    """
    Pushes a Tier 1 (per-task, actionable) delivery-failure event onto Q_CHANNEL_OUT.

    Args:
        task_id (str)

        attempted_type (str):
            "image" | "video" | "album" | "file" | "text" | "poll".

        status_code (int | None):
            Telegram's HTTP status code, if the request reached Telegram; otherwise
            None (e.g. a local validation failure caught before any request was sent).

        reason (str):
            Telegram's own error description, or a local validation failure message.

    Returns:
        bool:
            True if pushed successfully; otherwise False.

    Notes:
        - Used only when a specific request was rejected (by Telegram, or by local validation) - never for connection-level failures, which carry no "wrong tool" signal and are reported via record_send_failure() instead.
    """
    from .queue import queue_push_task

    payload = {
        "task_id": task_id,
        "type": "delivery_failed",
        "tier": 1,
        "attempted_type": attempted_type,
        "status_code": status_code,
        "reason": reason
    }

    if not queue_push_task(payload):
        logger.error(f"Failed to push Tier 1 delivery_failed event for task_id={task_id} to RabbitMQ. Event dropped.")
        return False

    logger.info(f"Pushed Tier 1 delivery_failed event for task_id={task_id} (attempted_type={attempted_type}, status_code={status_code}).")
    return True

def record_send_success() -> None:
    """
    Resets Tier 2's consecutive-failure count and re-arms the alert.

    Args:
        None

    Returns:
        None

    Notes:
        - Intended to be called after any successful send - clears the slate so a past incident doesn't suppress the next genuine one.
    """
    global _consecutive_failures, _alert_armed

    with _lock:
        _consecutive_failures = 0
        _alert_armed = True

def record_send_failure(reason: str, status_code: int | None = None) -> None:
    """
    Records a Tier 2 send failure, pushing a gateway_alert once per incident.

    Args:
        reason (str):
            "unauthorized" | "not_found" | "unreachable".

        status_code (int | None, optional):
            Telegram's HTTP status code, if any (e.g. 401 for "unauthorized",
            404 for "not_found"). Defaults to None.

    Returns:
        None

    Notes:
        - reason="unauthorized"/"not_found" both fire immediately, bypassing the threshold - every endpoint the gateway hits is a fixed, hardcoded path, so either one is a permanent config issue (bad/revoked token), not a blip - no number of retries fixes it.
        - reason="unreachable" (connection/timeout exhaustion) only fires once GATEWAY_ALERT_FAILURE_THRESHOLD consecutive failures have accumulated across all sends - a single blip is expected noise, not a systemic signal.
        - Fires once per incident: re-armed only by record_send_success(), not by further failures, so an ongoing outage doesn't spam one alert per message.
    """
    global _consecutive_failures, _alert_armed

    if reason in ("unauthorized", "not_found"):
        with _lock:
            should_fire = _alert_armed
            _alert_armed = False
    else:
        with _lock:
            _consecutive_failures += 1
            should_fire = _alert_armed and _consecutive_failures >= settings.GATEWAY_ALERT_FAILURE_THRESHOLD
            if should_fire:
                _alert_armed = False

    if should_fire:
        _push_tier2_gateway_alert(reason, status_code)

def _push_tier2_gateway_alert(reason: str, status_code: int | None) -> bool:
    """
    Pushes a Tier 2 (systemic, not tied to any task) alert onto Q_CHANNEL_OUT, and always logs critically regardless of outcome.

    Args:
        reason (str):
            "unauthorized" | "not_found" | "unreachable".

        status_code (int | None)

    Returns:
        bool:
            True if pushed successfully; otherwise False.

    Notes:
        - task_id is deliberately None - this isn't about any single task, so consumers of Q_CHANNEL_OUT need to expect a task_id-less message of type="gateway_alert".
        - Always logged at CRITICAL first, regardless of the queue push outcome, so this stays visible via infra/log-based monitoring even if RabbitMQ itself is part of what's currently broken.
    """
    logger.critical(f"Gateway alert: Telegram delivery failed - reason={reason}, status_code={status_code}. Human intervention likely required.")

    from .queue import queue_push_task

    payload = {
        "task_id": None,
        "type": "gateway_alert",
        "tier": 2,
        "reason": reason,
        "status_code": status_code
    }

    if not queue_push_task(payload):
        logger.error("Failed to push Tier 2 gateway_alert event to RabbitMQ. Event dropped (already logged critically above).")
        return False

    logger.info(f"Pushed Tier 2 gateway_alert event (reason={reason}).")
    return True

# =============================================================================
