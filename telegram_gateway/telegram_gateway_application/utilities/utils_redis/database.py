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
import time
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

def redis_read(key: str) -> str | None:
    """
    Reads a value from Redis.

    Args:
        - key (str)

    Returns:
        - str | None:
            The stored value if found; otherwise None (including a missing key or a failure).

    Notes:
        - Catches any exception, so unknown/unexpected failures return None instead of propagating.
    """
    try:
        client = get_redis_client()
        return client.get(key)
    except Exception:
        logger.exception("Failed to read from Redis.")
        return None

def redis_delete(key: str) -> bool:
    """
    Deletes a key from Redis, retrying on a failed delete (e.g. a connection issue).

    Args:
        - key (str)

    Returns:
        - bool:
            True if a key was deleted; otherwise False (including a missing key or exhausted retries).

    Notes:
        - Only retries a raised exception (e.g. disconnection) - a missing key is not a
          failure, client.delete() returns 0 for it without raising, so no retry is needed there.
        - Retries up to settings.REDIS_TASK_MAX_ATTEMPTS times, waiting
          settings.REDIS_TASK_RETRY_DELAY seconds between attempts.
    """
    for attempt in range(1, settings.REDIS_TASK_MAX_ATTEMPTS + 1):
        try:
            client = get_redis_client()
            return bool(client.delete(key))
        except Exception:
            if attempt < settings.REDIS_TASK_MAX_ATTEMPTS:
                logger.warning(f"Failed to delete key={key} from Redis (attempt {attempt}/{settings.REDIS_TASK_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.REDIS_TASK_RETRY_DELAY)
            else:
                logger.exception(f"Failed to delete key={key} from Redis after {settings.REDIS_TASK_MAX_ATTEMPTS} attempts.")
                return False

def get_task_mapping(task_id: str) -> dict | None:
    """
    Retrieves the chat_id/user_id mapping stored for a task_id.

    Args:
        - task_id (str)

    Returns:
        - dict | None:
            {"chat_id": int, "user_id": int} if found and valid; otherwise None.

    Notes:
        - Talks to the Redis client directly rather than via redis_read(), so three
          distinct outcomes can be told apart and logged differently:
            - failed to read (a raised exception, e.g. a connection issue) - retried
              up to settings.REDIS_TASK_MAX_ATTEMPTS, waiting settings.REDIS_TASK_RETRY_DELAY
              seconds between attempts.
            - no exception, but the key does not exist (expired TTL, unknown task_id) -
              an expected outcome, not a fault, and not retried.
            - the stored value is not valid JSON - a corruption case, also not retried,
              since retrying does not change what is already stored.
        - Still returns None in all three cases - callers only need "found or not," not why.
    """
    value = None

    for attempt in range(1, settings.REDIS_TASK_MAX_ATTEMPTS + 1):
        try:
            client = get_redis_client()
            value = client.get(f"task:{task_id}")
            break
        except Exception:
            if attempt < settings.REDIS_TASK_MAX_ATTEMPTS:
                logger.warning(f"Failed to read task mapping for task_id={task_id} (attempt {attempt}/{settings.REDIS_TASK_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.REDIS_TASK_RETRY_DELAY)
            else:
                logger.exception(f"Failed to read task mapping for task_id={task_id} from Redis after {settings.REDIS_TASK_MAX_ATTEMPTS} attempts.")
                return None

    if value is None:
        logger.warning(f"No task mapping found for task_id={task_id} (expired or unknown).")
        return None

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        logger.error(f"Stored mapping for task_id={task_id} is not valid JSON: {value}")
        return None

def delete_task_mapping(task_id: str) -> bool:
    """
    Deletes the chat_id/user_id mapping stored for a task_id.

    Args:
        - task_id (str)

    Returns:
        - bool:
            True if a mapping was deleted; otherwise False (including if it was already gone).
    """
    return redis_delete(f"task:{task_id}")

def create_task_mapping(
    chat_id: int,
    user_id: int,
    ttl_seconds: int | None = settings.REDIS_TASK_MAPPING_TTL_SECONDS
) -> str | None:
    """
    Generates a task_id and maps it to the given chat_id/user_id pair in Redis.

    Args:
        - chat_id (int)

        - user_id (int)

        - ttl_seconds (int | None, optional):
            Seconds until the mapping expires. No expiry if None. Defaults to settings.REDIS_TASK_MAPPING_TTL_SECONDS.

    Returns:
        - str | None:
            The generated task_id if the mapping was stored successfully; otherwise None.

    Notes:
        - Stored as task:<task_id> -> json {"chat_id": chat_id, "user_id": user_id}.
        - This is the only place chat_id/user_id are persisted - queue payloads should carry task_id only, keeping agents identity-blind.
        - Writes with nx=True so an existing task_id is never overwritten - a collision regenerates a new task_id instead of failing outright.
        - Retries up to settings.REDIS_TASK_MAX_ATTEMPTS times, waiting
          settings.REDIS_TASK_RETRY_DELAY seconds between attempts.
        - Default TTL means an orphaned mapping (e.g. RabbitMQ down when the push was attempted) is
          not stuck in Redis forever - it expires on its own after settings.REDIS_TASK_MAPPING_TTL_SECONDS.
    """
    value = json.dumps({"chat_id": chat_id, "user_id": user_id})

    for attempt in range(1, settings.REDIS_TASK_MAX_ATTEMPTS + 1):
        task_id = uuid.uuid4().hex
        if redis_write(f"task:{task_id}", value, ttl_seconds, nx=True):
            return task_id
        elif attempt < settings.REDIS_TASK_MAX_ATTEMPTS:
            time.sleep(settings.REDIS_TASK_RETRY_DELAY)
        else:
            logger.error(f"Failed to create task mapping after {settings.REDIS_TASK_MAX_ATTEMPTS} attempts.")
            return None

def get_chat_draft(chat_id: int) -> dict | None:
    """
    Retrieves the pending draft (media awaiting an instruction) stored for a chat_id.

    Args:
        - chat_id (int)

    Returns:
        - dict | None:
            {"media_type": str, "media_url": str, "text": str, "has_caption": bool}
            if found and valid; otherwise None.

    Notes:
        - Same read/retry/corruption handling as get_task_mapping() - see there for details.
    """
    value = None

    for attempt in range(1, settings.REDIS_TASK_MAX_ATTEMPTS + 1):
        try:
            client = get_redis_client()
            value = client.get(f"draft:{chat_id}")
            break
        except Exception:
            if attempt < settings.REDIS_TASK_MAX_ATTEMPTS:
                logger.warning(f"Failed to read draft for chat_id={chat_id} (attempt {attempt}/{settings.REDIS_TASK_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.REDIS_TASK_RETRY_DELAY)
            else:
                logger.exception(f"Failed to read draft for chat_id={chat_id} from Redis after {settings.REDIS_TASK_MAX_ATTEMPTS} attempts.")
                return None

    if value is None:
        return None

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        logger.error(f"Stored draft for chat_id={chat_id} is not valid JSON: {value}")
        return None

def delete_chat_draft(chat_id: int) -> bool:
    """
    Deletes the pending draft stored for a chat_id.

    Args:
        - chat_id (int)

    Returns:
        - bool:
            True if a draft was deleted; otherwise False (including if it was already gone).
    """
    return redis_delete(f"draft:{chat_id}")

def create_chat_draft(chat_id: int, media_type: str, media_url: str, text: str, has_caption: bool) -> bool:
    """
    Stores a pending draft (media awaiting an instruction) for a chat_id.

    Args:
        - chat_id (int)

        - media_type (str):
            "image" | "video" | "file".

        - media_url (str)

        - text (str):
            The caption, if the media was sent with one; otherwise "".

        - has_caption (bool)

    Returns:
        - bool:
            True if the draft was stored successfully; otherwise False.

    Notes:
        - Stored as draft:<chat_id> -> json {"media_type", "media_url", "text", "has_caption"}.
        - Writes with nx=True - only one pending draft is allowed per chat_id at a time.
          Callers are expected to check get_chat_draft() first; this only refuses to
          overwrite an existing draft, it does not report which case occurred.
        - Unlike create_task_mapping(), this is a single attempt with no retry loop - the
          key is deterministic (not a randomly generated task_id), so retrying a failure
          here would just fail again if a draft already legitimately exists for this
          chat_id. A dropped write here simply means the user's media goes unacknowledged,
          which is easily recovered by resending - a lower-stakes failure than a task mapping.
        - TTL is settings.DRAFT_MAPPING_TTL_SECONDS, as a Redis-side backstop slightly
          beyond the draft timer's hard close (see utils_telegram/draft_timer.py) so a
          draft is never left in Redis indefinitely if the in-memory timer thread is lost
          (e.g. an application restart).
    """
    value = json.dumps({
        "media_type": media_type,
        "media_url": media_url,
        "text": text or "",
        "has_caption": has_caption
    })
    return redis_write(f"draft:{chat_id}", value, ttl_seconds=settings.DRAFT_MAPPING_TTL_SECONDS, nx=True)

# =============================================================================
