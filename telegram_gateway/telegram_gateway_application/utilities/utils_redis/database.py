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

_chat_locks_guard = threading.Lock()
_chat_locks: dict[int, threading.Lock] = {}

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

def _get_redis_client() -> redis.Redis:
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

def _redis_write(key: str, value: str, ttl_seconds: int | None = None, nx: bool = False) -> bool:
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
        client = _get_redis_client()
        return bool(client.set(key, value, ex=ttl_seconds, nx=nx))
    except Exception:
        logger.exception("Failed to write to Redis.")
        return False

def _redis_read(key: str) -> str | None:
    """
    Reads a value from Redis.

    Args:
        key (str)

    Returns:
        str | None:
            The stored value if found; otherwise None (including on failure).
    """
    try:
        client = _get_redis_client()
        return client.get(key)
    except Exception:
        logger.exception("Failed to read from Redis.")
        return None

def _redis_delete(key: str) -> bool:
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
            client = _get_redis_client()
            return bool(client.delete(key))
        except Exception:
            if attempt < settings.REDIS_TASK_MAX_ATTEMPTS:
                logger.warning(f"Failed to delete key={key} from Redis (attempt {attempt}/{settings.REDIS_TASK_MAX_ATTEMPTS}). Retrying...")
                time.sleep(settings.REDIS_TASK_RETRY_DELAY)
            else:
                logger.exception(f"Failed to delete key={key} from Redis after {settings.REDIS_TASK_MAX_ATTEMPTS} attempts.")
                return False

def _get_chat_lock(chat_id: int) -> threading.Lock:
    """
    Retrieves (creating if needed) the per-chat_id lock used to serialise create_task_mapping() and create_poll_mapping() against reset_session() for the same chat_id.

    Args:
        chat_id (int)

    Returns:
        threading.Lock:
            The chat_id's dedicated lock, shared across all callers.

    Notes:
        - See CCR-013 (NON_COMPLIANCE_REPORT.md): without this, a task created in the narrow window around a session_reset could be written and indexed after reset_session() has already read session_tasks:<chat_id>, escaping deletion while its index entry is destroyed regardless.
          The same class of race applies to a poll's session_polls:<chat_id> indexing - see create_poll_mapping().
        - One Lock per chat_id, never removed - acceptable given chat_id count is bounded by TELEGRAM_ALLOWED_CHAT_IDS in this application's 1 user : 1 chat model.
        - Only sufficient because this application runs as a single process (see compose.dev.yml) - a horizontally-scaled deployment would need a Redis-side transaction/Lua script instead.
    """
    with _chat_locks_guard:
        lock = _chat_locks.get(chat_id)
        if lock is None:
            lock = threading.Lock()
            _chat_locks[chat_id] = lock
        return lock

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
            client = _get_redis_client()
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
    else:
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            logger.error(f"Stored mapping for task_id={task_id} is not valid JSON: {value}")
            return None

def delete_task_mapping(task_id: str, chat_id: int | None = None) -> bool:
    """
    Deletes the chat_id/user_id mapping stored for a task_id.

    Args:
        task_id (str)

        chat_id (int | None, optional):
            Pass this when the caller already has it (avoids a redundant Redis read) - used to also remove task_id from session_tasks:<chat_id>.
            Resolved via a fresh read if omitted. Defaults to None.

    Returns:
        bool:
            True if the mapping was deleted; otherwise False.

    Notes:
        - Keeps session_tasks:<chat_id> (see create_task_mapping()) in sync - best-effort, logged on failure, does not affect the return value.
    """
    if chat_id is None:
        mapping = get_task_mapping(task_id)
        chat_id = mapping.get("chat_id") if mapping else None

    deleted = _redis_delete(f"task:{task_id}")

    if chat_id is not None:
        try:
            _get_redis_client().srem(f"session_tasks:{chat_id}", task_id)
        except Exception:
            logger.exception(f"Failed to remove task_id={task_id} from session_tasks:{chat_id}.")

    return deleted

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
        - Also indexes task_id under session_tasks:<chat_id> (a Redis SET) so reset_session() can find every task belonging to a chat without a full keyspace SCAN.
          Best-effort - a failure here is logged but does not fail task creation itself.
        - Holds chat_id's lock (see _get_chat_lock()) across the write+index step, serialised against a concurrent reset_session() for the same chat_id - see CCR-013 (NON_COMPLIANCE_REPORT.md).
    """
    value = json.dumps({"chat_id": chat_id, "user_id": user_id})

    with _get_chat_lock(chat_id):
        for attempt in range(1, settings.REDIS_TASK_MAX_ATTEMPTS + 1):
            task_id = uuid.uuid4().hex
            if _redis_write(f"task:{task_id}", value, ttl_seconds, nx=True):
                try:
                    _get_redis_client().sadd(f"session_tasks:{chat_id}", task_id)
                except Exception:
                    logger.exception(f"Failed to index task_id={task_id} under session_tasks:{chat_id}. A future session reset may miss this task.")

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
            client = _get_redis_client()
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
    else:
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
    return _redis_delete(f"draft:{chat_id}")

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
        client = _get_redis_client()
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
    created = _redis_write(f"draft:{chat_id}", value, ttl_seconds=settings.DRAFT_MAPPING_TTL_SECONDS, nx=True)
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
        - Also indexes poll_id under session_polls:<chat_id> (a Redis SET) so reset_session() can find every open poll belonging to a chat without a full keyspace SCAN - mirrors session_tasks:<chat_id> (see create_task_mapping()).
          Best-effort - a failure here is logged but does not fail poll creation.
        - Holds chat_id's lock (see _get_chat_lock()) across the write+index step, serialised against a concurrent reset_session() for the same chat_id - mirrors create_task_mapping()'s own use of the same lock, closing the same class of race for session_polls:<chat_id> as well.
    """
    value = json.dumps({
        "chat_id": chat_id,
        "task_id": task_id,
        "message_id": message_id,
        "user_id": None,
        "option_ids": []
    })

    with _get_chat_lock(chat_id):
        created = _redis_write(f"poll:{poll_id}", value, ttl_seconds=settings.POLL_MAPPING_TTL_SECONDS, nx=True)
        if created:
            try:
                _get_redis_client().sadd(f"session_polls:{chat_id}", poll_id)
            except Exception:
                logger.exception(f"Failed to index poll_id={poll_id} under session_polls:{chat_id}. A future session reset may miss this poll.")

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
            client = _get_redis_client()
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
    else:
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
    else:
        mapping["user_id"] = user_id
        mapping["option_ids"] = option_ids
        return _redis_write(f"poll:{poll_id}", json.dumps(mapping), ttl_seconds=settings.POLL_MAPPING_TTL_SECONDS)

def delete_poll_mapping(poll_id: str, chat_id: int | None = None) -> bool:
    """
    Deletes the mapping stored for an open poll.

    Args:
        poll_id (str)

        chat_id (int | None, optional):
            Pass this when the caller already has it (avoids a redundant Redis read) - used to also remove poll_id from session_polls:<chat_id>.
            Resolved via a fresh read if omitted. Defaults to None.

    Returns:
        bool:
            True if the mapping was deleted; otherwise False.

    Notes:
        - Keeps session_polls:<chat_id> (see create_poll_mapping()) in sync - best-effort, logged on failure, does not affect the return value.
    """
    if chat_id is None:
        mapping = get_poll_mapping(poll_id)
        chat_id = mapping.get("chat_id") if mapping else None

    deleted = _redis_delete(f"poll:{poll_id}")

    if chat_id is not None:
        try:
            _get_redis_client().srem(f"session_polls:{chat_id}", poll_id)
        except Exception:
            logger.exception(f"Failed to remove poll_id={poll_id} from session_polls:{chat_id}.")

    return deleted

def has_open_tasks(chat_id: int) -> bool:
    """
    Checks whether a chat_id currently has any open task_id indexed under session_tasks:<chat_id>.

    Args:
        chat_id (int)

    Returns:
        bool:
            True if at least one task_id is indexed, or on a Redis failure (see Notes); otherwise False.

    Notes:
        - Used to decide whether a session_reset can apply immediately or must be deferred until every open task naturally completes - see utils_session/session_reset_handler.py.
        - On a Redis failure, defaults to True (treated as still open) rather than False, so an uncertain read can only ever delay a reset, never force one through prematurely.
    """
    try:
        return _get_redis_client().scard(f"session_tasks:{chat_id}") > 0
    except Exception:
        logger.exception(f"Failed to check session_tasks for chat_id={chat_id}. Treating as still open (deferring).")
        return True

def get_session_poll_ids(chat_id: int) -> list[str]:
    """
    Retrieves every open poll_id currently indexed under a chat_id.

    Args:
        chat_id (int)

    Returns:
        list[str]:
            poll_ids indexed under session_polls:<chat_id>; empty list if none, or on failure.

    Notes:
        - An open poll always has an open task_id, so it's only ever encountered on the deferred path (never the immediate-apply path) - see utils_session/session_reset_handler.py.
          The deferred path itself never force-closes anything while genuinely waiting; only its PENDING_RESET_MAX_WAIT_SECONDS force-through backstop (§8, TODO.md) calls this defensively before applying, in case a misconfigured ceiling ever forces through while a poll is still technically alive - see poll_response_handler.py::stop_poll_for_reset().
    """
    try:
        return list(_get_redis_client().smembers(f"session_polls:{chat_id}"))
    except Exception:
        logger.exception(f"Failed to read session_polls for chat_id={chat_id}.")
        return []

def _get_or_create_session(chat_id: int) -> str | None:
    """
    Retrieves the permanent session_id for a chat_id, creating one if it doesn't exist yet.

    Args:
        chat_id (int)

    Returns:
        str | None:
            The session_id if resolved/created successfully; otherwise None.

    Notes:
        - Stored as session:<chat_id> -> session_id, with no TTL - permanent until reset_session() clears it.
        - Writes with nx=True; a race against another creation for the same chat_id re-reads the winner's value rather than overwriting it (unlike create_task_mapping(), the key is deterministic per chat_id, so a losing writer can just re-read instead of generating a fresh id).
    """
    existing = _redis_read(f"session:{chat_id}")
    if existing:
        return existing
    else:
        session_id = uuid.uuid4().hex
        if _redis_write(f"session:{chat_id}", session_id, nx=True):
            logger.info(f"Created session mapping session_id={session_id} for chat_id={chat_id}.")
            return session_id
        else:
            # Second read to verify if write is failed due to a race against another creation for the same chat_id
            existing = _redis_read(f"session:{chat_id}")
            if existing:
                return existing
            else:
                logger.error(f"Failed to create or read session mapping for chat_id={chat_id}.")
                return None

def generate_session(chat_id: int | None = None, task_id: str | None = None) -> str | None:
    """
    Resolves the permanent session_id for a chat, lazily creating one if needed.

    Args:
        chat_id (int | None, optional):
            Direct path - used whenever a chat_id is already known (e.g. a task being pushed). Defaults to None.

        task_id (str | None, optional):
            Indirect path - used when only a task_id is known (e.g. a poll answer push, which carries no chat_id of its own).
            The task's chat_id is resolved via its Redis mapping first. Defaults to None.

    Returns:
        str | None:
            The session_id if resolved successfully; otherwise None.

    Notes:
        - Exactly one of chat_id/task_id is expected; chat_id takes priority if both are given.
        - task_id path: a resolved chat_id with no existing session mapping is an unexpected corner case - a session is expected to already exist by the time any task is created.
          Logged as CRITICAL, then self-healed by creating a fresh one rather than failing the caller outright (e.g. dropping an already-submitted poll answer) - the corner case stays visible in logs either way.
        - Intended to be called immediately before every message is built for RabbitMQ - see gateway_inbound.py::_push_task(), poll_response_handler.py::_push_poll_answer(), error_handling.py::push_tier1_delivery_failed().
    """
    if chat_id is not None:
        return _get_or_create_session(chat_id)
    elif task_id is not None:
        mapping = get_task_mapping(task_id)
        if mapping is None:
            logger.error(f"Could not resolve session_id for task_id={task_id} - no task mapping found.")
            return None
        else:
            resolved_chat_id = mapping.get("chat_id")
            session_id = _redis_read(f"session:{resolved_chat_id}")
            if session_id is None:
                logger.critical(
                    f"No session mapping found for chat_id={resolved_chat_id} (resolved via task_id={task_id}). "
                    f"This should never happen - a session is expected to already exist by the time any task is "
                    f"created. Creating a new one so this message isn't dropped."
                )
                return _get_or_create_session(resolved_chat_id)
            else:
                return session_id
    else:
        logger.error("generate_session() called without chat_id or task_id. Cannot resolve a session.")
        return None

def reset_session(chat_id: int) -> str | None:
    """
    Wipes a chat's permanent session_id mapping, every task_id mapping created under it, its pending draft (if any), and any leftover open-poll indexing.

    Args:
        chat_id (int)

    Returns:
        str | None:
            The session_id that was cleared, captured via a read before deletion; None if chat_id had no session_id set.

    Notes:
        - Destroys task_id mappings alongside session_id deliberately: once a session is reset, the backend has already unwound whatever state it held for it, so a leftover task_id mapping could no longer resolve to anything meaningful - any further response arriving under an old task_id is dropped the same way an unknown/expired one already is (see message_handler.py::process_message()).
        - Reads task_ids from session_tasks:<chat_id> (see create_task_mapping()) rather than a full keyspace SCAN.
        - Also deletes the chat's pending draft (see delete_chat_draft()) and, defensively, session_polls:<chat_id> - see CCR-012 (NON_COMPLIANCE_REPORT.md).
          Any open poll is expected to already be closed out (and its own poll:<poll_id>/session_polls entry removed) by the caller before this runs - see utils_queue/message_handler.py::_handle_session_reset() - this is just a final sweep of the index itself in case one was missed; it does not touch Telegram or any in-memory poll/draft timer, since this module has no visibility into either.
        - Best-effort - a failure reading session_tasks is logged; whatever can still be deleted, is.
        - Holds chat_id's lock (see _get_chat_lock()) across the read-then-delete sequence, serialised against a concurrent create_task_mapping() for the same chat_id - see CCR-013 (NON_COMPLIANCE_REPORT.md).
          Without this, a task written and indexed in the narrow window between this function's read and its delete of session_tasks:<chat_id> could escape deletion entirely while still losing its index entry.
    """
    with _get_chat_lock(chat_id):
        cleared_session_id = _redis_read(f"session:{chat_id}")

        try:
            client = _get_redis_client()
            task_ids = client.smembers(f"session_tasks:{chat_id}")
        except Exception:
            logger.exception(f"Failed to read session_tasks for chat_id={chat_id}. Task mappings may be left behind.")
            task_ids = set()

        for task_id in task_ids:
            _redis_delete(f"task:{task_id}")

        _redis_delete(f"session_tasks:{chat_id}")
        _redis_delete(f"session:{chat_id}")
        delete_chat_draft(chat_id)
        _redis_delete(f"session_polls:{chat_id}")

    logger.info(f"Session reset for chat_id={chat_id}: cleared session mapping, {len(task_ids)} task mapping(s), pending draft, and poll indexing.")
    return cleared_session_id

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
        client = _get_redis_client()
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

def set_pending_reset(chat_id: int, task_id: str) -> bool:
    """
    Stores (or overwrites) a chat_id's deferred session_reset, awaiting every currently open task_id for that chat to naturally complete.

    Args:
        chat_id (int)

        task_id (str):
            The task_id the session_reset instruction arrived on - kept for traceability only; readiness is decided by has_open_tasks(), not by this task_id specifically.

    Returns:
        bool:
            True if stored successfully; otherwise False.

    Notes:
        - Stored as pending_reset:<chat_id> -> json {"task_id", "created_at"}, with no TTL - see utils_session/session_reset_handler.py.
          This store must outlive whatever task it's waiting on, since a task can legitimately stay open for an unbounded duration; only an explicit clear_pending_reset() call resolves it.
        - `created_at` (time.time(), on write) is not itself the resolution mechanism - it's read back by utils_session/session_reset_handler.py's PENDING_RESET_MAX_WAIT_SECONDS backstop, so a reset stuck waiting on a task_id that never sends completed/error doesn't wait forever - see §8 (TODO.md).
        - Writes with nx=False (default) - a repeat trigger while one is already pending just overwrites it (including a fresh `created_at`), since only the most recent session_reset instruction matters once it's finally applied.
    """
    value = json.dumps({"task_id": task_id, "created_at": time.time()})
    written = _redis_write(f"pending_reset:{chat_id}", value)
    if written:
        logger.info(f"Stored pending reset for chat_id={chat_id} (task_id={task_id}).")
    else:
        logger.error(f"Failed to store pending reset for chat_id={chat_id} (task_id={task_id}).")

    return written

def _get_pending_reset_info(chat_id: int) -> dict | None:
    """
    Retrieves the {"task_id", "created_at"} a deferred session_reset is stored against for a chat_id.

    Args:
        chat_id (int)

    Returns:
        dict | None:
            {"task_id": str, "created_at": float} if a reset is pending for chat_id; otherwise None (including corrupt stored JSON, logged as an error).
    """
    value = _redis_read(f"pending_reset:{chat_id}")
    if value is None:
        return None
    else:
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            logger.error(f"Stored pending reset for chat_id={chat_id} is not valid JSON: {value}")
            return None

def get_pending_reset(chat_id: int) -> str | None:
    """
    Retrieves the task_id a deferred session_reset is stored against for a chat_id, if any.

    Args:
        chat_id (int)

    Returns:
        str | None:
            The task_id if a reset is pending for chat_id; otherwise None.
    """
    info = _get_pending_reset_info(chat_id)
    return info.get("task_id") if info else None

def clear_pending_reset(chat_id: int) -> bool:
    """
    Deletes the deferred session_reset marker for a chat_id.

    Args:
        chat_id (int)

    Returns:
        bool:
            True if a pending reset was deleted; otherwise False.
    """
    return _redis_delete(f"pending_reset:{chat_id}")

def get_all_pending_resets() -> list[tuple[int, str, float]]:
    """
    Retrieves every currently deferred session_reset in Redis.

    Args:
        None

    Returns:
        list[tuple[int, str, float]]:
            (chat_id, task_id, created_at) for every pending_reset:<chat_id> key present; empty list on failure.

    Notes:
        - Used on startup to resync deferred resets that may have become resolvable while the gateway was down, and by the periodic PENDING_RESET_MAX_WAIT_SECONDS backstop sweep - see utils_session/session_reset_handler.py::resync_pending_resets()/_enforce_pending_reset_ceiling().
        - `created_at` is whatever was written by set_pending_reset() - used by the callers above to decide whether a pending reset has been waiting too long, not interpreted here.
        - Uses SCAN (not KEYS) so it doesn't block Redis on a large keyspace.
    """
    try:
        client = _get_redis_client()
        pending_resets = []
        for key in client.scan_iter(match="pending_reset:*"):
            try:
                chat_id = int(key.split(":", 1)[1])
            except (IndexError, ValueError):
                logger.error(f"Skipped malformed pending_reset key while sweeping Redis: {key}")
                continue

            value = client.get(key)
            if not value:
                continue
            else:
                try:
                    info = json.loads(value)
                    task_id = info["task_id"]
                    created_at = info["created_at"]
                except (json.JSONDecodeError, TypeError, KeyError):
                    logger.error(f"Skipped pending_reset key with invalid JSON while sweeping Redis: {key}")
                    continue

            pending_resets.append((chat_id, task_id, created_at))

        return pending_resets
    except Exception:
        logger.exception("Failed to sweep Redis for pending resets.")
        return []

# =============================================================================
