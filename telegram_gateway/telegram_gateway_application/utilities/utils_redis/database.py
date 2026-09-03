# =============================================================================
# File        : database.py
# Description : File responsible for initialising, managing, and terminating the Redis connection.
# Author      : SorinoSSK
# Created On  : 2026-08-29
#
# Features    :
#   - Manages a shared Redis connection used for session/task/draft/poll state storage.
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
            If the connection cannot be established.
    """
    global _client
    with _lock:
        if _client is None:
            try:
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
        redis.Redis:
            The shared Redis client.

    Raises:
        redis.exceptions.RedisError:
            If the connection needs to be (re)initialised and cannot be established.
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
        key (str)

        value (str)

        ttl_seconds (int | None, optional):
            Seconds until expiry. No expiry if None. Defaults to None.

        nx (bool, optional):
            Only write if the key does not already exist. Defaults to False.

    Returns:
        bool:
            True if written; otherwise False (including a no-op skip from nx=True).

    Notes:
        - Accepts str only - callers must serialise complex values first (e.g. json.dumps).
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
        key (str)

    Returns:
        str | None:
            The stored value if found; otherwise None (including on failure).
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
        key (str)

    Returns:
        bool:
            True if a key was deleted; otherwise False (including a missing key or exhausted retries).

    Notes:
        - Retries only a raised exception - a missing key returns 0 without raising, not a failure.
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
        task_id (str)

    Returns:
        dict | None:
            {"chat_id": int, "user_id": int} if found and valid; otherwise None.

    Notes:
        - Distinguishes (via logging only) a read failure (retried), a missing key (expired/unknown, not retried), and corrupt JSON (not retried) - all return None.
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
        task_id (str)

    Returns:
        bool:
            True if the mapping was deleted; otherwise False.
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
        chat_id (int)

        user_id (int)

        ttl_seconds (int | None, optional):
            Defaults to settings.REDIS_TASK_MAPPING_TTL_SECONDS.

    Returns:
        str | None:
            The generated task_id if stored successfully; otherwise None.

    Notes:
        - Stored as task:<task_id> -> json {"chat_id", "user_id"} - the only place identity is persisted.
        - Writes with nx=True; a collision regenerates a new task_id rather than overwriting.
    """
    value = json.dumps({"chat_id": chat_id, "user_id": user_id})

    for attempt in range(1, settings.REDIS_TASK_MAX_ATTEMPTS + 1):
        task_id = uuid.uuid4().hex
        if redis_write(f"task:{task_id}", value, ttl_seconds, nx=True):
            logger.info(f"Created task mapping task_id={task_id} for chat_id={chat_id}.")
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
        chat_id (int)

    Returns:
        dict | None:
            {"media_type", "media_url", "text", "has_caption"} if found and valid; otherwise None.

    Notes:
        - Same read/retry/corruption handling as get_task_mapping().
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
        chat_id (int)

    Returns:
        bool:
            True if the draft was deleted; otherwise False.
    """
    return redis_delete(f"draft:{chat_id}")

def get_all_chat_draft_ids() -> list[int]:
    """
    Retrieves the chat_id of every currently pending draft in Redis.

    Args:
        None

    Returns:
        list[int]:
            chat_ids with a draft:<chat_id> key present; empty list on failure.

    Notes:
        - Used on startup to sweep up drafts whose in-memory keep-alive timer did not survive an application restart (see utils_telegram/utilities/image_draft_handler.py).
        - Uses SCAN (not KEYS) so it doesn't block Redis on a large keyspace.
    """
    try:
        client = get_redis_client()
        chat_ids = []
        for key in client.scan_iter(match="draft:*"):
            try:
                chat_ids.append(int(key.split(":", 1)[1]))
            except (IndexError, ValueError):
                logger.error(f"Skipped malformed draft key while sweeping Redis: {key}")

        return chat_ids
    except Exception:
        logger.exception("Failed to sweep Redis for pending drafts.")
        return []

def create_chat_draft(chat_id: int, media_type: str, media_url: str, text: str, has_caption: bool) -> bool:
    """
    Stores a pending draft (media awaiting an instruction) for a chat_id.

    Args:
        chat_id (int)

        media_type (str):
            "image" | "video" | "file".

        media_url (str)

        text (str):
            The caption, if any; otherwise "".

        has_caption (bool)

    Returns:
        bool:
            True if stored successfully; otherwise False.

    Notes:
        - Stored as draft:<chat_id> -> json {media_type, media_url, text, has_caption}.
        - Writes with nx=True; only one pending draft allowed per chat_id at a time.
        - TTL is a Redis-side backstop slightly beyond the draft timer's hard close (see utils_telegram/utilities/image_draft_handler.py), in case the in-memory timer is lost.
    """
    value = json.dumps({
        "media_type": media_type,
        "media_url": media_url,
        "text": text or "",
        "has_caption": has_caption
    })
    created = redis_write(f"draft:{chat_id}", value, ttl_seconds=settings.DRAFT_MAPPING_TTL_SECONDS, nx=True)
    if created:
        logger.info(f"Created {media_type} draft for chat_id={chat_id}.")
    else:
        logger.warning(f"Did not create {media_type} draft for chat_id={chat_id} - a draft may already be pending, or the write failed.")

    return created

def create_poll_mapping(poll_id: str, chat_id: int, task_id: str, message_id: int) -> bool:
    """
    Stores the chat_id/task_id/message_id mapping for an open poll, ready to be resolved from a poll_answer update.

    Args:
        poll_id (str)

        chat_id (int)

        task_id (str)

        message_id (int):
            The poll message's message_id - required to close it later via stopPoll (which takes chat_id + message_id, not poll_id).

    Returns:
        bool:
            True if stored successfully; otherwise False.

    Notes:
        - Stored as poll:<poll_id> -> json {chat_id, task_id, message_id, user_id, option_ids}.
        - user_id/option_ids start empty - unknown until a poll_answer update arrives - see update_poll_answer().
        - Writes with nx=True.
          TTL is a Redis-side backstop beyond the poll's hard cap (see utils_telegram/utilities/poll_response_handler.py) in case the in-memory timer is lost.
    """
    value = json.dumps({
        "chat_id": chat_id,
        "task_id": task_id,
        "message_id": message_id,
        "user_id": None,
        "option_ids": []
    })
    created = redis_write(f"poll:{poll_id}", value, ttl_seconds=settings.POLL_MAPPING_TTL_SECONDS, nx=True)
    if created:
        logger.info(f"Created poll mapping poll_id={poll_id} for chat_id={chat_id} (task_id={task_id}).")
    else:
        logger.warning(f"Did not create poll mapping poll_id={poll_id} - it may already exist, or the write failed.")

    return created

def get_poll_mapping(poll_id: str) -> dict | None:
    """
    Retrieves the mapping stored for an open poll.

    Args:
        poll_id (str)

    Returns:
        dict | None:
            {"chat_id", "task_id", "message_id", "user_id", "option_ids"} if found and valid; otherwise None.

    Notes:
        - Same read/retry/corruption handling as get_task_mapping().
    """
    value = None

    for attempt in range(1, settings.REDIS_TASK_MAX_ATTEMPTS + 1):
        try:
            client = get_redis_client()
            value = client.get(f"poll:{poll_id}")
            break
        except Exception:
            if attempt < settings.REDIS_TASK_MAX_ATTEMPTS:
                logger.warning(f"Failed to read poll mapping for poll_id={poll_id} (attempt {attempt}/{settings.REDIS_TASK_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.REDIS_TASK_RETRY_DELAY)
            else:
                logger.exception(f"Failed to read poll mapping for poll_id={poll_id} from Redis after {settings.REDIS_TASK_MAX_ATTEMPTS} attempts.")
                return None

    if value is None:
        return None

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        logger.error(f"Stored poll mapping for poll_id={poll_id} is not valid JSON: {value}")
        return None

def update_poll_answer(poll_id: str, user_id: int, option_ids: list) -> bool:
    """
    Updates the latest answer recorded against an open poll's mapping.

    Args:
        poll_id (str)

        user_id (int):
            The responder's id, per Telegram's poll_answer update.

        option_ids (list):
            The responder's currently selected option indices, per Telegram's poll_answer update.

    Returns:
        bool:
            True if updated successfully; otherwise False (including an unknown poll_id).

    Notes:
        - Overwrites user_id/option_ids with the latest state - see poll_response_handler.py for how repeated answers (debounced) are handled.
        - Refreshes the TTL back to settings.POLL_MAPPING_TTL_SECONDS on every call, since this record is the restart-recovery backstop for whatever the poll's actual latest answer is - see close_orphaned_polls().
    """
    mapping = get_poll_mapping(poll_id)
    if mapping is None:
        logger.warning(f"Could not update poll answer for poll_id={poll_id} - no mapping found.")
        return False

    mapping["user_id"] = user_id
    mapping["option_ids"] = option_ids
    return redis_write(f"poll:{poll_id}", json.dumps(mapping), ttl_seconds=settings.POLL_MAPPING_TTL_SECONDS)

def delete_poll_mapping(poll_id: str) -> bool:
    """
    Deletes the mapping stored for an open poll.

    Args:
        poll_id (str)

    Returns:
        bool:
            True if the mapping was deleted; otherwise False.
    """
    return redis_delete(f"poll:{poll_id}")

def get_all_poll_ids() -> list[str]:
    """
    Retrieves the poll_id of every currently open poll mapping in Redis.

    Args:
        None

    Returns:
        list[str]:
            poll_ids with a poll:<poll_id> key present; empty list on failure.

    Notes:
        - Used on startup to sweep up polls whose in-memory timer did not survive an application restart (see utils_telegram/utilities/poll_response_handler.py).
        - Uses SCAN (not KEYS) so it doesn't block Redis on a large keyspace.
    """
    try:
        client = get_redis_client()
        poll_ids = []
        for key in client.scan_iter(match="poll:*"):
            try:
                poll_ids.append(key.split(":", 1)[1])
            except IndexError:
                logger.error(f"Skipped malformed poll key while sweeping Redis: {key}")

        return poll_ids
    except Exception:
        logger.exception("Failed to sweep Redis for open polls.")
        return []

# =============================================================================
