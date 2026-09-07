# =============================================================================
# File        : queue.py
# Description : File responsible for initialising, managing, and terminating RabbitMQ connections.
# Author      : SorinoSSK
# Created On  : 2026-09-07
#
# Features    :
#   - Single shared RabbitMQ consume connection, read by the one background consumer thread that demultiplexes every inbound message from telegram_gateway (see bot_sanctuary/CODE_TODO.md §3).
#   - RabbitMQPublisher - a dedicated, caller-owned RabbitMQ publish connection per instance, deliberately not a shared/module-level connection - each session worker thread (see bot_sanctuary/CODE_TODO.md §3) is intended to own and publish through its own instance, since a pika BlockingConnection is not thread-safe and a lock around a shared one is documented as insufficient (the connection's I/O loop is tied to the thread that created it).
#
# Notes       :
#   - Always use the helper functions/classes in this file to consume/publish RabbitMQ messages.
#   - The session-routing layer (per-session worker threads - see bot_sanctuary/CODE_TODO.md §3) is not implemented yet - process_message() (utils_queue/message_handler.py) is currently a placeholder that logs and drops every session-scoped message rather than routing it to a session worker.
#
# =============================================================================
# I M P O R T   H E A D E R

import pika
import json
import time
import logging
import threading

from ...config import settings
from .message_handler import process_message

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# The single consume connection/channel is only ever touched by the one background consumer thread (see
# start_queue_consumer()) - this lock guards lifecycle transitions (start/stop/close), not concurrent use
# from multiple threads.
_lock_consume = threading.RLock()

_connection_consume = None
_channel_consume = None

_consumer_thread = None
_consumer_running = False

# Tracks failed processing attempts per message body, so a deterministically-failing message is
# eventually dropped instead of being requeued forever.
# In-memory only - only ever touched from the single consumer thread (pika callbacks run sequentially),
# no lock needed.
_message_attempts: dict[bytes, int] = {}

# =============================================================================

def _build_rabbitmq_parameters() -> pika.ConnectionParameters:
    """
    Builds the connection parameters shared by every RabbitMQ connection this application opens.

    Args:
        None

    Returns:
        pika.ConnectionParameters:
            Parameters built from the application's RabbitMQ configuration.
    """
    credentials = pika.PlainCredentials(settings.Q_USER, settings.Q_PASSWORD)
    return pika.ConnectionParameters(
        host=settings.Q_HOST,
        port=settings.Q_PORT,
        virtual_host=settings.Q_VHOST,
        credentials=credentials,
        heartbeat=settings.Q_HEARTBEAT,
        blocked_connection_timeout=settings.Q_BLOCKED_CONNECTION_TIMEOUT
    )

def _initialise_rabbitmq_consume_connection() -> None:
    """
    Opens the single RabbitMQ connection used by the background consumer thread.

    Args:
        None

    Returns:
        None

    Raises:
        pika.exceptions.AMQPConnectionError:
            If the connection cannot be established.
    """
    global _connection_consume, _channel_consume
    with _lock_consume:
        if _connection_consume is None or _connection_consume.is_closed:
            try:
                _connection_consume = pika.BlockingConnection(_build_rabbitmq_parameters())
                _channel_consume = _connection_consume.channel()
                logger.info("RabbitMQ consume connection initialised")

            except pika.exceptions.AMQPConnectionError as e:
                logger.critical(f"Failed to connect to RabbitMQ (consume): {e}")
                raise
        else:
            logger.warning("Reinitialisation of RabbitMQ consume connection occured. No new RabbitMQ initialisation is made.")

def initialise_rabbitmq_connection() -> None:
    """
    Initialises the RabbitMQ consume connection.

    Retries indefinitely, with a fixed delay between attempts, whenever RabbitMQ is not yet reachable - blocks the caller until the connection succeeds rather than giving up after a bounded number of attempts.

    Args:
        None

    Returns:
        None

    Notes:
        - Startup-only behaviour: intended for initialise.py::initialise_application(), so a transient RabbitMQ-not-up-yet race at container start does not crash-exit the whole application - same pattern as telegram_gateway/utilities/utils_queue/queue.py::initialise_rabbitmq_connection().
        - Any exception other than pika.exceptions.AMQPConnectionError still propagates immediately and is not retried.
    """
    while True:
        try:
            _initialise_rabbitmq_consume_connection()
            return
        except pika.exceptions.AMQPConnectionError as e:
            logger.warning(f"RabbitMQ not reachable yet at startup: {e}. Retrying in {settings.Q_CONNECT_RETRY_DELAY_SECONDS}s...")
            time.sleep(settings.Q_CONNECT_RETRY_DELAY_SECONDS)

def close_rabbitmq_connection() -> None:
    """
    Closes the RabbitMQ consume channel/connection if they exist.

    Args:
        None

    Returns:
        None

    Notes:
        - Only closes the shared consume connection - a RabbitMQPublisher's own connection (see below) is closed by whoever owns it, via its own close() method, not here.
    """
    global _connection_consume, _channel_consume

    with _lock_consume:
        if _channel_consume and _channel_consume.is_open:
            _channel_consume.close()
            logger.info("RabbitMQ consume channel has been closed.")

        if _connection_consume and _connection_consume.is_open:
            _connection_consume.close()
            logger.info("RabbitMQ consume connection has been closed.")

def _get_rabbitmq_consume_channel() -> pika.adapters.blocking_connection.BlockingChannel:
    """
    Retrieves an opened channel for consuming messages from RabbitMQ, initialising it if needed.

    Args:
        None

    Returns:
        pika.adapters.blocking_connection.BlockingChannel

    Raises:
        pika.exceptions.AMQPConnectionError:
            If the connection needs to be (re)initialised and cannot be established.
    """
    global _connection_consume, _channel_consume

    with _lock_consume:
        if _connection_consume is None or _connection_consume.is_closed:
            _initialise_rabbitmq_consume_connection()

        return _channel_consume

def queue_consume_task() -> None:
    """
    Consumes messages from RabbitMQ in a loop, reconnecting automatically on connection failures.

    Runs until _consumer_running is cleared (see stop_queue_consumer()).

    Args:
        None

    Returns:
        None

    Notes:
        - An undecodable message body is dropped (not requeued) - retrying cannot fix it.
        - Other processing failures are requeued and retried up to Q_CONSUME_MAX_ATTEMPTS times (tracked per body in _message_attempts), then dropped.
        - Mirrors telegram_gateway/utilities/utils_queue/queue.py::queue_consume_task() - see there for the established pattern this follows.
    """
    global _consumer_running
    while True:
        with _lock_consume:
            running = _consumer_running
        if not running:
            break
        else:
            try:
                channel = _get_rabbitmq_consume_channel()
                channel.queue_declare(queue=settings.Q_CHANNEL_IN, durable=True)

                def callback(ch, method, properties, body):
                    try:
                        payload = body.decode()
                    except UnicodeDecodeError:
                        logger.error("Received RabbitMQ message with an undecodable body. Dropping (not requeued).")
                        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                        return

                    try:
                        process_message(payload)
                        ch.basic_ack(delivery_tag=method.delivery_tag)
                        _message_attempts.pop(body, None)
                    except Exception:
                        attempts = _message_attempts.get(body, 0) + 1
                        _message_attempts[body] = attempts

                        if attempts >= settings.Q_CONSUME_MAX_ATTEMPTS:
                            logger.exception(f"Giving up on message after {attempts} attempts. Dropping (not requeued).")
                            _message_attempts.pop(body, None)
                            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                        else:
                            logger.exception(f"Failed to process incoming RabbitMQ message (attempt {attempts}/{settings.Q_CONSUME_MAX_ATTEMPTS}). Requeuing...")
                            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

                channel.basic_consume(
                    queue=settings.Q_CHANNEL_IN,
                    on_message_callback=callback,
                    auto_ack=False
                )
                logger.info("RabbitMQ consumer started")
                channel.start_consuming()
            except (
                pika.exceptions.AMQPConnectionError,
                pika.exceptions.StreamLostError,
                pika.exceptions.ChannelWrongStateError,
            ):
                logger.warning("RabbitMQ consumer disconnected. Reconnecting...")
                time.sleep(settings.Q_CONSUME_RETRY_DELAY)
            except Exception:
                logger.exception("Unexpected RabbitMQ consumer error detected.")
                time.sleep(settings.Q_CONSUME_RETRY_DELAY)

def start_queue_consumer() -> None:
    """
    Start the background queue consumer thread if it is not already running.

    Args:
        None

    Returns:
        None
    """
    global _consumer_thread
    global _consumer_running
    with _lock_consume:
        if _consumer_running:
            return
        else:
            _consumer_running = True
            _consumer_thread = threading.Thread(
                target=queue_consume_task,
                daemon=True
            )
            _consumer_thread.start()

def stop_queue_consumer() -> None:
    """
    Stop the background queue consumer.

    Args:
        None

    Returns:
        None

    Notes:
        - Does not wait for the consumer thread to actually terminate.
    """
    global _consumer_running
    with _lock_consume:
        _consumer_running = False
        if _connection_consume and _connection_consume.is_open and _channel_consume:
            try:
                _connection_consume.add_callback_threadsafe(_channel_consume.stop_consuming)
            except Exception:
                logger.exception("Failed to schedule RabbitMQ consumer stop.")

# =============================================================================
# P U B L I S H I N G  (per-thread, not shared - see module header)

class RabbitMQPublisher:
    """
    Thin, thread-owned wrapper around a single RabbitMQ connection/channel used for publishing results back to telegram_gateway.

    Deliberately not shared/module-level and not thread-safe by design - intended to be created and used from within exactly one thread (a future session worker - see bot_sanctuary/CODE_TODO.md §3) for its entire lifetime, never passed across threads or shared.
    Each instance owns and lazily opens its own connection on first publish() call.

    Example:
        publisher = RabbitMQPublisher()
        ...
        publisher.publish({"task_id": "...", "session_id": "...", "type": "text", "text": "..."})
        ...
        publisher.close()
    """

    def __init__(self):
        self._connection = None
        self._channel = None

    def _ensure_connection(self) -> None:
        """
        Opens this instance's connection/channel if not already open.

        Args:
            None

        Returns:
            None

        Raises:
            pika.exceptions.AMQPConnectionError:
                If the connection cannot be established.
        """
        if self._connection is None or self._connection.is_closed:
            self._connection = pika.BlockingConnection(_build_rabbitmq_parameters())
            self._channel = self._connection.channel()

    def publish(self, payload: dict) -> bool:
        """
        Publishes payload to Q_CHANNEL_OUT, retrying on connection failure up to Q_PUSH_MAX_ATTEMPTS times.

        Args:
            payload (dict)

        Returns:
            bool:
                True if published successfully; otherwise False once attempts are exhausted.

        Notes:
            - UnroutableError is not retried (misconfigured queue/binding). Connection-level failures are.
            - Mirrors telegram_gateway/utilities/utils_queue/queue.py::queue_push_task()'s retry behaviour, but against this instance's own connection rather than a shared module-level one.
        """
        for attempt in range(1, settings.Q_PUSH_MAX_ATTEMPTS + 1):
            try:
                self._ensure_connection()
                self._channel.queue_declare(queue=settings.Q_CHANNEL_OUT, durable=True)
                self._channel.basic_publish(
                    exchange="",
                    routing_key=settings.Q_CHANNEL_OUT,
                    body=json.dumps(payload),
                    properties=pika.BasicProperties(
                        delivery_mode=pika.DeliveryMode.Persistent
                    )
                )
                logger.info(f"Published task result to RabbitMQ queue={settings.Q_CHANNEL_OUT} (task_id={payload.get('task_id')}).")
                return True
            except pika.exceptions.UnroutableError:
                logger.error("RabbitMQ rejected task result as unroutable. Not retrying.")
                return False
            except (
                pika.exceptions.AMQPConnectionError,
                pika.exceptions.StreamLostError,
                pika.exceptions.ChannelWrongStateError,
                pika.exceptions.ChannelClosed,
            ):
                logger.warning(f"RabbitMQ publish attempt {attempt}/{settings.Q_PUSH_MAX_ATTEMPTS} failed.")
                self._connection = None
                self._channel = None
                if attempt < settings.Q_PUSH_MAX_ATTEMPTS:
                    time.sleep(settings.Q_PUSH_RETRY_DELAY)

        logger.error(f"Failed to publish task result to RabbitMQ after {settings.Q_PUSH_MAX_ATTEMPTS} attempts.")
        return False

    def close(self) -> None:
        """
        Closes this instance's channel/connection if open.

        Args:
            None

        Returns:
            None
        """
        try:
            if self._channel and self._channel.is_open:
                self._channel.close()
            if self._connection and self._connection.is_open:
                self._connection.close()
        except Exception:
            logger.exception("Failed to cleanly close a RabbitMQPublisher's connection.")
        finally:
            self._connection = None
            self._channel = None
            logger.info("RabbitMQ publish connection has been closed.")

# =============================================================================
