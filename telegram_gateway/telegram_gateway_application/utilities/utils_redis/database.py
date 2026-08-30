# =============================================================================
# File        : database.py
# Description : File responsible for initialising, managing, and terminating the Redis connection.
# Author      : SorinoSSK
# Created On  : 2026-08-29
#
# Features    :
#   - Manages a shared Redis connection used for session/task state storage.
#
# Notes       :
#   - Always use the helper functions in this file to read/write Redis state.
#
# =============================================================================
# I M P O R T   H E A D E R

import json
import uuid
import logging
import threading

import redis

from ...config import settings

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_client = None

# =============================================================================

def initialise_redis_connection() -> None:
    """
    Opens the shared Redis connection, reused across the application.

    Args:
        None

    Returns:
        None

    Raises:
        redis.exceptions.RedisError:
            If the Redis connection cannot be established.
    """
    global _client
    with _lock:
        if _client is None:
            try:
                _client = redis.Redis(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    db=settings.REDIS_DB,
                    decode_responses=True
                )
                _client.ping()
                logger.info("Redis connection initialised")

            except redis.exceptions.RedisError as e:
                logger.critical(f"Failed to connect to Redis: {e}")
                raise
        else:
            logger.warning("Reinitialisation of Redis connection occured. No new Redis initialisation is made.")

def get_redis_client() -> redis.Redis:
    """
    Retrieves the shared Redis client, initialising it first if needed.

    Args:
        None

    Returns:
        - redis.Redis:
            The shared Redis client instance.
    """
    global _client
    with _lock:
        if _client is None:
            initialise_redis_connection()

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
    with _lock:
        if _client is not None:
            _client.close()
            _client = None
            logger.info("Redis connection has been closed.")

def redis_write(key: str, value: str, ttl_seconds: int | None = None, nx: bool = False) -> bool:
    """
    Writes a key-value pair to Redis, optionally with a TTL.

    Args:
        - key (str)

        - value (str)

        - ttl_seconds (int | None, optional):
            Seconds until the key expires. No expiry if None. Defaults to None.

        - nx (bool, optional):
            Only write if the key does not already exist. Defaults to False.

    Returns:
        - bool:
            True if the write succeeded; otherwise False (including a
            no-op skip caused by nx=True and an existing key).

    Notes:
        - Accepts str only - callers are responsible for serialising (e.g. json.dumps) complex values first.
        - Catches any exception, not just redis.exceptions.RedisError, so unknown/unexpected failures still return False instead of propagating.
    """
    try:
        client = get_redis_client()
        return bool(client.set(key, value, ex=ttl_seconds, nx=nx))
    except Exception:
        logger.exception("Failed to write to Redis.")
        return False

def create_task_mapping(chat_id: int, user_id: int, ttl_seconds: int | None = None, max_attempts: int = 5) -> str | None:
    """
    Generates a task_id and maps it to the given chat_id/user_id pair in Redis.

    Args:
        - chat_id (int)

        - user_id (int)

        - ttl_seconds (int | None, optional):
            Seconds until the mapping expires. No expiry if None. Defaults to None.

        - max_attempts (int, optional):
            Number of task_id generations to try before giving up. Defaults to 5.

    Returns:
        - str | None:
            The generated task_id if the mapping was stored successfully; otherwise None.

    Notes:
        - Stored as task:<task_id> -> json {"chat_id": chat_id, "user_id": user_id}.
        - This is the only place chat_id/user_id are persisted - queue payloads should carry task_id only, keeping agents identity-blind.
        - Writes with nx=True so an existing task_id is never overwritten - a collision regenerates a new task_id instead of failing outright.
    """
    value = json.dumps({"chat_id": chat_id, "user_id": user_id})

    for _ in range(max_attempts):
        task_id = uuid.uuid4().hex
        if redis_write(f"task:{task_id}", value, ttl_seconds, nx=True):
            return task_id

    logger.error(f"Failed to create task mapping after {max_attempts} attempts.")
    return None

# =============================================================================
