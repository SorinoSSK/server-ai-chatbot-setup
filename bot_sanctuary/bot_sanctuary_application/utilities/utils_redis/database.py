# =============================================================================
# File        : database.py
# Description : File responsible for the Redis-backed gateway_alert notification throttle - remembers when the last gateway_alert notification email was sent, and a running count of how many gateway_alert events have been received, so the throttle survives an application restart. Both carry a fixed, guaranteed 24h (GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS) fallback expiry.
# Author      : SorinoSSK
# Created On  : 2026-09-07
#
# Features    :
#   - record_gateway_alert_occurrence() - increments a persistent counter every time a gateway_alert is received, regardless of whether a notification email is actually sent for it.
#   - should_notify_gateway_alert() / mark_gateway_alert_notified() - the once-per-GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS throttle gate - see utils_queue/message_handler.py::_handle_gateway_alert().
#   - Both the counter and the cooldown carry a fixed Redis TTL (GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS), applied once when each key starts a fresh window and deliberately never extended afterwards - see module Notes.
#
# Notes       :
#   - Deliberately not a hard startup dependency - see config.py's Redis Connection section.
#     Redis is only used here for a durability nicety on an already-optional, secondary feature (SMTP alerting); bot_sanctuary's primary RabbitMQ pipeline must not be blocked or crashed by it.
#   - Connects lazily, on first use, with a single attempt (not the infinite-retry-at-startup pattern used for RabbitMQ, since this isn't a startup-time concern at all) - a connection failure is caught and treated as fail-open (see should_notify_gateway_alert()'s own Notes for the reasoning), never raised.
#   - Every key here is namespaced "bot_sanctuary:..." - this application's Redis ACL user is scoped to only that key pattern (see compose.dev.yml's redis service), so it can share the same Redis container as telegram_gateway without being able to read/write its session/task/draft/poll state.
#   - The TTL on _COUNT_KEY/_LAST_NOTIFIED_KEY is set once, when each key starts a fresh window, and is never refreshed/extended by a later occurrence - deliberately, not an oversight. A TTL that gets renewed on every new occurrence would never actually expire for as long as occurrences kept arriving at all, which would make the fallback reset impossible in a sustained-failure scenario - the whole point of a fallback is a guaranteed ceiling that fires on schedule regardless of how much more data shows up in the meantime. Both keys therefore self-clear exactly GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS after they were first written, full stop - no assumption that further data will or won't arrive either way.
#
# =============================================================================
# I M P O R T   H E A D E R

import time
import logging

import redis

from ...config import settings

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_client = None

_COUNT_KEY = "bot_sanctuary:gateway_alert:count"
_LAST_NOTIFIED_KEY = "bot_sanctuary:gateway_alert:last_notified_at"

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
    Increments the persistent gateway_alert occurrence counter.

    Args:
        None

    Returns:
        int | None:
            The counter's new value if recorded successfully; otherwise None (Redis unavailable - logged, non-fatal - the occurrence is simply not counted this time).

    Notes:
        - A fixed GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS TTL is applied to _COUNT_KEY only the first time it's created for a fresh window (detected via TTL(_COUNT_KEY) < 0, i.e. "exists with no expiry yet") - deliberately not reapplied/extended on every later occurrence within that same window. This guarantees the counter reverts to 0 exactly GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS after the window began, no matter how many further occurrences arrive in between - see module Notes on why a renewed-on-every-occurrence TTL would be an unreliable fallback.
    """
    try:
        client = _get_redis_client()
        new_count = client.incr(_COUNT_KEY)
        if client.ttl(_COUNT_KEY) < 0:
            client.expire(_COUNT_KEY, settings.GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS)
        return new_count
    except Exception:
        logger.exception("Failed to record gateway_alert occurrence in Redis.")
        return None

def should_notify_gateway_alert() -> bool:
    """
    Checks whether a gateway_alert notification email should be sent now.

    Args:
        None

    Returns:
        bool:
            True if no notification has been sent within the last GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS (or none has ever been sent, or Redis is unavailable); otherwise False.

    Notes:
        - Fails open: if Redis is unreachable, returns True (allows the send) rather than False.
          Missing one throttle check occasionally is judged less harmful than silently suppressing every future alert for as long as Redis happens to be down, on the one path whose entire purpose is warning a human that something else is already broken.
        - The `last_notified_at is None` branch also covers _LAST_NOTIFIED_KEY's fixed TTL expiring (see mark_gateway_alert_notified()) - once Redis drops that key exactly GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS after it was written, this reads back as "no notification sent" and allows the next occurrence through, same as if none had ever been sent - the time-diff branch below is then largely a redundant guard (clock-skew safety), since the TTL itself already enforces the same window.
    """
    try:
        client = _get_redis_client()
        last_notified_at = client.get(_LAST_NOTIFIED_KEY)
        if last_notified_at is None:
            return True
        else:
            return (time.time() - float(last_notified_at)) >= settings.GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS
    except Exception:
        logger.exception("Failed to check gateway_alert notification throttle in Redis - failing open (allowing send).")
        return True

def mark_gateway_alert_notified() -> None:
    """
    Records that a gateway_alert notification email was just sent, resetting the cooldown.

    Args:
        None

    Returns:
        None

    Notes:
        - Only call this after a notification email has actually been sent successfully - see utils_queue/message_handler.py::_handle_gateway_alert().
          Marking on a failed send would suppress every subsequent occurrence for the full cooldown despite nothing having gone out.
        - A failure here (logged, non-fatal) means the next occurrence may re-notify sooner than intended - preferable to the alternative of failing the whole request over a best-effort durability write.
        - Sets a fixed GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS TTL on write, not refreshed anywhere else afterwards - the TTL literally *is* the cooldown here, guaranteed to lapse exactly on schedule regardless of how many further occurrences arrive in the meantime (see module Notes on why a renewed TTL would be an unreliable fallback).
    """
    try:
        client = _get_redis_client()
        client.set(_LAST_NOTIFIED_KEY, str(time.time()), ex=settings.GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS)
    except Exception:
        logger.exception("Failed to record gateway_alert notification timestamp in Redis - next occurrence may re-notify sooner than intended.")

# =============================================================================
