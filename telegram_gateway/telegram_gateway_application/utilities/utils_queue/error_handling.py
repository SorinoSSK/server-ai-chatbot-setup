# =============================================================================
# File        : error_handling.py
# Description : Builds and pushes delivery-failure events onto Q_CHANNEL_OUT, split into Tier 1 (per-task, actionable) and Tier 2 (systemic, not actionable by any single task) failures.
# Author      : SorinoSSK
# Created On  : 2026-09-02
#
# Features    :
#   - Tier 1 - push_tier1_delivery_failed(): a specific send was rejected by Telegram, or failed local validation before ever reaching Telegram.
#     Reported per task_id, since the backend/orchestrator can react by retrying that same task differently (e.g. a different content type, a shorter message).
#     Also marks that task_id as having a retry outstanding (set_pending_retry()), so its corrective reply isn't left with nowhere to land - see utils_queue/message_handler.py::_handle_completed().
#   - Tier 2 - record_send_success()/record_send_failure(): Telegram is unreachable altogether, or the bot token itself is invalid/revoked (401/404) - not tied to any one task, since no per-task retry/tool-swap fixes either.
#     Tracks a rolling consecutive-failure count and fires a gateway_alert once per incident, re-arming only once a send succeeds again.
#     That re-arming send also pushes a gateway_recover event - but only if it's actually closing out a prior alert, not on every ordinary success - see record_send_success().
#
# Notes       :
#   - Deferred import of queue_push_task to avoid a circular import (queue.py -> message_handler.py -> ... -> queue.py), same pattern as utils_telegram/utilities/poll_response_handler.py::_push_poll_answer().
#   - Tier 2's consecutive-failure counter resets on restart - deliberately, since a restart is itself a fresh start at reassessing whether Telegram is reachable.
#     The armed/disarmed flag (whether an incident is currently outstanding) is persisted separately - see load_tier2_alert_state() - so a gateway_alert resolved via restart (e.g. a 401/404 fixed by updating TELEGRAM_BOT_TOKEN) still receives its paired gateway_recover. Closes CCR-019 (CODE_NON_COMPLIANCE.md).
#   - _lock's scope covers the persist-and-publish step (set_tier2_alert_armed() + _push_tier2_gateway_alert()/_push_tier2_gateway_recover()) on top of the state mutation itself, for the armed<->disarmed transition branches only - not just the read/write of _alert_armed/_consecutive_failures.
#     A dedicated second lock scoped only to the publish step was tried first and rejected: it prevented two publishes overlapping, but did not guarantee publish order matched transition order - after releasing _lock, which thread reaches a second lock first is scheduler-dependent, not tied to which thread mutated state first. Guaranteeing order requires the decision and the publish to be one uninterrupted critical section under the same lock, which is what this does.
#     Accepted cost, explicit user decision: a transitioning call now holds _lock for the full publish duration (up to Q_PUSH_MAX_ATTEMPTS x Q_PUSH_RETRY_DELAY, ~30s, if RabbitMQ is also unreachable) - during that window every other thread's record_send_success()/record_send_failure() call (i.e. every send_*() in gateway_outbound.py, across every concurrent thread) blocks too, not just the two threads actually racing. Judged acceptable because this worst case only arises when RabbitMQ is unreachable at the same time Telegram delivery is failing/recovering - the system is already broadly degraded in that scenario, so the added internal lock contention is not the dominant concern. Closes CCR-020 (CODE_NON_COMPLIANCE.md).
#
# =============================================================================
# I M P O R T   H E A D E R

import logging
import threading

from ...config import settings
from ..utils_redis.database import generate_session, get_tier2_alert_armed, set_tier2_alert_armed, set_pending_retry

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_consecutive_failures = 0
_alert_armed = True

# =============================================================================

def load_tier2_alert_state() -> None:
    """
    Loads Tier 2's armed/disarmed flag from Redis at startup, so an incident left outstanding by a prior run isn't silently forgotten.

    Args:
        None

    Returns:
        None

    Notes:
        - Intended to be called once during initialise_application(), after Redis is initialised and before any send can run - see utilities/initialise.py.
        - _consecutive_failures is deliberately NOT restored here - it resets to 0 on every restart by design (see module Notes) - only the armed/disarmed flag (whether an incident is currently outstanding) is restart-persistent. Closes CCR-019 (CODE_NON_COMPLIANCE.md).
    """
    global _alert_armed

    with _lock:
        _alert_armed = get_tier2_alert_armed()

    if _alert_armed:
        logger.info("Tier 2 alert state loaded from Redis: armed (no incident outstanding).")
    else:
        logger.warning("Tier 2 alert state loaded from Redis: disarmed - an incident was left outstanding by a prior run. The next successful send will push a gateway_recover.")

def push_tier1_delivery_failed(task_id: str, attempted_type: str, status_code: int | None, reason: str) -> bool:
    """
    Pushes a Tier 1 (per-task, actionable) delivery-failure event onto Q_CHANNEL_OUT.

    Args:
        task_id (str)

        attempted_type (str):
            "image" | "video" | "album" | "file" | "text" | "poll".

        status_code (int | None):
            Telegram's HTTP status code, if the request reached Telegram; otherwise None (e.g. a local validation failure caught before any request was sent).

        reason (str):
            Telegram's own error description, or a local validation failure message.

    Returns:
        bool:
            True if pushed successfully; otherwise False.

    Notes:
        - Used only when a specific request was rejected (by Telegram, or by local validation) - never for connection-level failures, which carry no "wrong tool" signal and are reported via record_send_failure() instead.
        - session_id is resolved via generate_session() and is mandatory on every outbound payload - see utils_redis/database.py.
        - Once actually pushed, also marks task_id as having a retry outstanding (set_pending_retry()) - see utils_queue/message_handler.py::_handle_completed(), which checks this before tearing down the task's mapping, so the corrective reply bot_sanctuary is expected to publish for this same task_id still has somewhere to land. Not set at all if the push itself fails - no retry is realistically coming for an event that never reached bot_sanctuary.
    """
    from .queue import queue_push_task

    session_id = generate_session(task_id=task_id)
    if not session_id:
        logger.error(f"Failed to resolve session_id for task_id={task_id}. Tier 1 delivery_failed event dropped.")
        return False
    else:
        payload = {
            "task_id": task_id,
            "session_id": session_id,
            "type": "delivery_failed",
            "tier": 1,
            "attempted_type": attempted_type,
            "status_code": status_code,
            "reason": reason
        }

        if not queue_push_task(payload):
            logger.error(f"Failed to push Tier 1 delivery_failed event for task_id={task_id} to RabbitMQ. Event dropped.")
            return False
        else:
            set_pending_retry(task_id)
            logger.info(f"Pushed Tier 1 delivery_failed event for task_id={task_id} (attempted_type={attempted_type}, status_code={status_code}).")
            return True

def record_send_success(status_code: int | None = None) -> None:
    """
    Resets Tier 2's consecutive-failure count and re-arms the alert, pushing a gateway_recover event if this success is closing out a prior alert.

    Args:
        status_code (int | None, optional):
            Telegram's HTTP status code from the response that just succeeded (typically 200). Defaults to None.

    Returns:
        None

    Notes:
        - Intended to be called after any successful send - clears the slate so a past incident doesn't suppress the next genuine one.
        - _push_tier2_gateway_recover() fires exactly once per incident - only when this success follows an armed-off state (i.e. record_send_failure() had already fired a gateway_alert) - not on every ordinary success. Mirrors record_send_failure()'s own "once per incident" behaviour.
        - The armed flag is persisted to Redis (set_tier2_alert_armed()) only on this transition, not on every ordinary success - see load_tier2_alert_state(). Closes CCR-019 (CODE_NON_COMPLIANCE.md).
        - Logged here (rather than inside _push_tier2_gateway_recover()) so the recovery transition itself is always visible in the logs regardless of whether the queue push succeeds - this behaviour hasn't been through testing yet, so the extra visibility is deliberate while that's confirmed.
        - The persist-and-publish step below runs inside the same _lock as the state mutation above, not after releasing it - guarantees this transition's publish can't be reordered relative to record_send_failure()'s own transition. See _lock's module-level Notes. Closes CCR-020 (CODE_NON_COMPLIANCE.md).
    """
    global _consecutive_failures, _alert_armed

    with _lock:
        was_alerted = not _alert_armed
        _consecutive_failures = 0
        _alert_armed = True

        if was_alerted:
            set_tier2_alert_armed(True)
            logger.info(f"Telegram delivery recovered after a prior Tier 2 alert - status_code={status_code}.")
            _push_tier2_gateway_recover(status_code)

def record_send_failure(reason: str, status_code: int | None = None) -> None:
    """
    Records a Tier 2 send failure, pushing a gateway_alert once per incident.

    Args:
        reason (str):
            "unauthorized" | "not_found" | "unreachable".

        status_code (int | None, optional):
            Telegram's HTTP status code, if any (e.g. 401 for "unauthorized", 404 for "not_found"). Defaults to None.

    Returns:
        None

    Notes:
        - reason="unauthorized"/"not_found" both fire immediately, bypassing the threshold - every endpoint the gateway hits is a fixed, hardcoded path, so either one is a permanent config issue (bad/revoked token), not a blip - no number of retries fixes it.
        - reason="unreachable" (connection/timeout exhaustion) only fires once GATEWAY_ALERT_FAILURE_THRESHOLD consecutive failures have accumulated across all sends - a single blip is expected noise, not a systemic signal.
        - Fires once per incident: re-armed only by record_send_success(), not by further failures, so an ongoing outage doesn't spam one alert per message.
        - The disarmed flag is persisted to Redis (set_tier2_alert_armed()) only on the transition that actually fires - see load_tier2_alert_state(). Closes CCR-019 (CODE_NON_COMPLIANCE.md).
        - The persist-and-publish step below runs inside the same _lock as the state mutation above, not after releasing it - guarantees this transition's publish can't be reordered relative to record_send_success()'s own transition. See _lock's module-level Notes. Closes CCR-020 (CODE_NON_COMPLIANCE.md).
    """
    global _consecutive_failures, _alert_armed

    with _lock:
        if reason in ("unauthorized", "not_found"):
            should_fire = _alert_armed
            _alert_armed = False
        else:
            _consecutive_failures += 1
            should_fire = _alert_armed and _consecutive_failures >= settings.GATEWAY_ALERT_FAILURE_THRESHOLD
            if should_fire:
                _alert_armed = False

        if should_fire:
            set_tier2_alert_armed(False)
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
        - task_id and session_id are both deliberately None - this isn't about any single task or chat, so consumers of Q_CHANNEL_OUT need to expect a task_id/session_id-less message of type="gateway_alert".
        - Always logged at CRITICAL first, regardless of the queue push outcome, so this stays visible via infra/log-based monitoring even if RabbitMQ itself is part of what's currently broken.
    """
    logger.critical(f"Gateway alert: Telegram delivery failed - reason={reason}, status_code={status_code}. Human intervention likely required.")

    from .queue import queue_push_task

    payload = {
        "task_id": None,
        "session_id": None,
        "type": "gateway_alert",
        "tier": 2,
        "reason": reason,
        "status_code": status_code
    }

    if not queue_push_task(payload):
        logger.error("Failed to push Tier 2 gateway_alert event to RabbitMQ. Event dropped (already logged critically above).")
        return False
    else:
        logger.info(f"Pushed Tier 2 gateway_alert event (reason={reason}).")
        return True

def _push_tier2_gateway_recover(status_code: int | None) -> None:
    """
    Pushes a Tier 2 (systemic, not tied to any task) recovery event onto Q_CHANNEL_OUT, mirroring _push_tier2_gateway_alert()'s payload shape.

    Args:
        status_code (int | None):
            Telegram's HTTP status code from the response that triggered the recovery (typically 200).

    Returns:
        None

    Notes:
        - task_id and session_id are both deliberately None, same as _push_tier2_gateway_alert() - see its Notes.
        - reason is always "recovered" - fixed, unlike gateway_alert's reason, which reflects what actually failed.
        - Called only by record_send_success() once per incident - see its Notes. The recovery transition itself is already logged there; this function only logs the push outcome, same convention as every other queue-push helper in this file.
    """
    from .queue import queue_push_task

    payload = {
        "task_id": None,
        "session_id": None,
        "type": "gateway_recover",
        "tier": 2,
        "reason": "recovered",
        "status_code": status_code
    }

    if not queue_push_task(payload):
        logger.error("Failed to push Tier 2 gateway_recover event to RabbitMQ. Event dropped.")
    else:
        logger.info(f"Pushed Tier 2 gateway_recover event (status_code={status_code}).")

# =============================================================================
