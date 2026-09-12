# =============================================================================
# File        : database.py
# Description : Manages the Redis-backed gateway_alert notification throttle and a durable crash-recovery record of active tasks.
# Author      : SorinoSSK
# Created On  : 2026-09-07
#
# Features    :
#   - gateway_alert occurrence counting and once-per-cooldown notification throttling, durable across restarts.
#   - Early throttle reset on a confirmed gateway_recover event, backed by a fixed TTL fallback.
#   - Durable tracking of active task_ids for crash-recovery detection at startup.
#
# Notes       :
#   - Not a hard startup dependency - connects lazily on first use and fails open where noted.
#   - Every key is namespaced under "bot_sanctuary:" and scoped to this application's own Redis ACL user.
#   - See README.md for the throttle window, TTL fallback, and crash-recovery design rationale.
#
# =============================================================================
# I M P O R T   H E A D E R

import time
import logging

import redis

from ...config import settings
from ..utilities import application_time, application_time_diff

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_client = None

_COUNT_KEY = "bot_sanctuary:gateway_alert:count"
_LAST_NOTIFIED_KEY = "bot_sanctuary:gateway_alert:last_notified_at"

_ACTIVE_TASKS_KEY = "bot_sanctuary:active_tasks"

# =============================================================================

def _get_redis_client() -> redis.Redis:
    """
    Retrieves the shared Redis client, connecting it first if needed.

    Args:
        None

    Returns:
        redis.Redis

    Raises:
        redis.exceptions.RedisError:
            If the connection cannot be established.
            Callers in this module always catch this - see module Notes on fail-open behaviour.
    """
    global _client
    if _client is None:
        _client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            username=settings.REDIS_USERNAME,
            password=settings.REDIS_PASSWORD,
            socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
            socket_keepalive=settings.REDIS_SOCKET_KEEPALIVE,
            health_check_interval=settings.REDIS_HEALTH_CHECK_INTERVAL,
            decode_responses=True
        )
        _client.ping()
        logger.info("Redis connection initialised (gateway_alert throttle).")

    return _client

def close_redis_connection() -> None:
    """
    Closes the shared Redis connection if it exists.

    Args:
        None

    Returns:
        None
    """
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            logger.exception("Failed to cleanly close the Redis connection.")
        finally:
            _client = None
            logger.info("Redis connection has been closed.")

def record_gateway_alert_occurrence() -> int | None:
    """
    Increments the persistent gateway_alert occurrence counter, retrying on a failed attempt.

    Args:
        None

    Returns:
        int | None:
            The counter's new value if recorded successfully; otherwise None once retry attempts are exhausted.

    Notes:
        - A fixed cooldown-length TTL is applied only the first time the counter is created for a fresh window.
    """
    for attempt in range(1, settings.REDIS_TASK_MAX_ATTEMPTS + 1):
        try:
            client = _get_redis_client()
            new_count = client.incr(_COUNT_KEY)
            if client.ttl(_COUNT_KEY) < 0:
                client.expire(_COUNT_KEY, settings.GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS)
            return new_count
        except Exception:
            if attempt < settings.REDIS_TASK_MAX_ATTEMPTS:
                logger.warning(f"Failed to record gateway_alert occurrence in Redis (attempt {attempt}/{settings.REDIS_TASK_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.REDIS_TASK_RETRY_DELAY)
            else:
                logger.exception(f"Failed to record gateway_alert occurrence in Redis after {settings.REDIS_TASK_MAX_ATTEMPTS} attempts.")
                return None

def should_notify_gateway_alert() -> bool:
    """
    Checks whether a gateway_alert notification email should be sent now.

    Args:
        None

    Returns:
        bool:
            True if no notification has been sent within the cooldown window, or Redis is unavailable; otherwise False.

    Notes:
        - Fails open on a Redis outage - missing a throttle check occasionally is judged less harmful than suppressing every alert while Redis is down.
    """
    for attempt in range(1, settings.REDIS_TASK_MAX_ATTEMPTS + 1):
        try:
            client = _get_redis_client()
            last_notified_at = client.get(_LAST_NOTIFIED_KEY)
            if last_notified_at is None:
                return True
            else:
                return application_time_diff(float(last_notified_at)) >= settings.GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS
        except Exception:
            if attempt < settings.REDIS_TASK_MAX_ATTEMPTS:
                logger.warning(f"Failed to check gateway_alert notification throttle in Redis (attempt {attempt}/{settings.REDIS_TASK_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.REDIS_TASK_RETRY_DELAY)
            else:
                logger.exception(f"Failed to check gateway_alert notification throttle in Redis after {settings.REDIS_TASK_MAX_ATTEMPTS} attempts - failing open (allowing send).")
                return True

def reset_gateway_alert_throttle() -> None:
    """
    Clears the gateway_alert occurrence counter and notification cooldown, treating the incident as over.

    Args:
        None

    Returns:
        None

    Notes:
        - Called on receiving a gateway_recover event, which telegram_gateway only ever emits after a confirmed prior alert.
        - Does not replace the fixed TTL fallback on either key - see README.md for how the two mechanisms interact.
    """
    for attempt in range(1, settings.REDIS_TASK_MAX_ATTEMPTS + 1):
        try:
            client = _get_redis_client()
            client.delete(_COUNT_KEY, _LAST_NOTIFIED_KEY)
            logger.info("gateway_alert throttle reset (count + cooldown cleared) following a gateway_recover.")
            return
        except Exception:
            if attempt < settings.REDIS_TASK_MAX_ATTEMPTS:
                logger.warning(f"Failed to reset gateway_alert throttle in Redis (attempt {attempt}/{settings.REDIS_TASK_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.REDIS_TASK_RETRY_DELAY)
            else:
                logger.exception(f"Failed to reset gateway_alert throttle in Redis after {settings.REDIS_TASK_MAX_ATTEMPTS} attempts - the existing TTL fallback will still apply on schedule.")

def mark_gateway_alert_notified() -> None:
    """
    Records that a gateway_alert notification email was just sent, resetting the cooldown.

    Args:
        None

    Returns:
        None

    Notes:
        - Should only be called after a notification email has actually been sent successfully.
    """
    for attempt in range(1, settings.REDIS_TASK_MAX_ATTEMPTS + 1):
        try:
            client = _get_redis_client()
            client.set(_LAST_NOTIFIED_KEY, str(application_time().timestamp()), ex=settings.GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS)
            return
        except Exception:
            if attempt < settings.REDIS_TASK_MAX_ATTEMPTS:
                logger.warning(f"Failed to record gateway_alert notification timestamp in Redis (attempt {attempt}/{settings.REDIS_TASK_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.REDIS_TASK_RETRY_DELAY)
            else:
                logger.exception(f"Failed to record gateway_alert notification timestamp in Redis after {settings.REDIS_TASK_MAX_ATTEMPTS} attempts - next occurrence may re-notify sooner than intended.")

def mark_task_active(task_id: str, session_id: str) -> None:
    """
    Durably records that a task_id has been accepted by a SessionWorker but not yet finished.

    Args:
        task_id (str):
            Identifier of the accepted task.

        session_id (str):
            Session the task belongs to.

    Returns:
        None

    Notes:
        - Best-effort - a failed write is logged and non-fatal, consistent with this module's fail-open design.
    """
    for attempt in range(1, settings.REDIS_TASK_MAX_ATTEMPTS + 1):
        try:
            client = _get_redis_client()
            client.hset(_ACTIVE_TASKS_KEY, task_id, session_id)
            return
        except Exception:
            if attempt < settings.REDIS_TASK_MAX_ATTEMPTS:
                logger.warning(f"Failed to mark task_id={task_id} active in Redis (attempt {attempt}/{settings.REDIS_TASK_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.REDIS_TASK_RETRY_DELAY)
            else:
                logger.exception(f"Failed to mark task_id={task_id} active in Redis after {settings.REDIS_TASK_MAX_ATTEMPTS} attempts - this task_id will not be recoverable if a crash happens before it completes.")

def mark_task_complete(task_id: str) -> None:
    """
    Clears a task_id's durable active-task record.

    Args:
        task_id (str):
            Identifier of the task to clear.

    Returns:
        None

    Notes:
        - Must be called on every path a task_id can finish through, so it is not mistaken for a dangling task by a future startup sweep.
    """
    for attempt in range(1, settings.REDIS_TASK_MAX_ATTEMPTS + 1):
        try:
            client = _get_redis_client()
            client.hdel(_ACTIVE_TASKS_KEY, task_id)
            return
        except Exception:
            if attempt < settings.REDIS_TASK_MAX_ATTEMPTS:
                logger.warning(f"Failed to clear active-task record for task_id={task_id} in Redis (attempt {attempt}/{settings.REDIS_TASK_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.REDIS_TASK_RETRY_DELAY)
            else:
                logger.exception(f"Failed to clear active-task record for task_id={task_id} in Redis after {settings.REDIS_TASK_MAX_ATTEMPTS} attempts - it may be incorrectly treated as still active by a future startup sweep.")

def sweep_orphaned_sessions() -> dict[str, str]:
    """
    Retrieves every task_id currently recorded as active, along with the session_id it belongs to.

    Args:
        None

    Returns:
        dict[str, str]:
            {task_id: session_id} for every entry still recorded; empty dict on failure or if none exist.

    Notes:
        - Intended to be called once at startup, before any new task is accepted, to detect what a prior run left dangling.
        - Fails closed (empty dict) rather than open, since a failed sweep should assume nothing needs recovering.
    """
    for attempt in range(1, settings.REDIS_TASK_MAX_ATTEMPTS + 1):
        try:
            client = _get_redis_client()
            return client.hgetall(_ACTIVE_TASKS_KEY)
        except Exception:
            if attempt < settings.REDIS_TASK_MAX_ATTEMPTS:
                logger.warning(f"Failed to sweep active tasks in Redis (attempt {attempt}/{settings.REDIS_TASK_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.REDIS_TASK_RETRY_DELAY)
            else:
                logger.exception(f"Failed to sweep active tasks in Redis after {settings.REDIS_TASK_MAX_ATTEMPTS} attempts - assuming nothing needs recovering this startup.")
                return {}

# =============================================================================
