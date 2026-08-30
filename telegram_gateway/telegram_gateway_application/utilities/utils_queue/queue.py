# =============================================================================
# File        : queue.py
# Description : File responsible for initialising, managing, and terminating RabbitMQ connections.
# Author      : SorinoSSK
# Created On  : 2026-08-29
#
# Features    :
#   - Manages task exchange through RabbitMQ queues to enable communication between backend systems.
#
# Notes       :
#   - Always use the helper functions in this file to enqueue and dequeue tasks.
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

# Publish and consume each use their own dedicated connection, confined to their own
# thread (publish: caller's thread, consume: _consumer_thread), since a pika
# BlockingConnection must not be shared or used concurrently across threads.
_lock_publish = threading.RLock()
_lock_consume = threading.RLock()

_connection_publish = None
_channel_publish = None

_connection_consume = None
_channel_consume = None

_consumer_thread = None
_consumer_running = False

# Tracks failed attempts per message body, so a deterministically-failing message is
# eventually dropped instead of being requeued forever. In-memory only - only ever
# touched from the single consumer thread (pika callbacks run sequentially), no lock needed.
_message_attempts: dict[bytes, int] = {}

# =============================================================================

def _build_rabbitmq_parameters() -> pika.ConnectionParameters:
    credentials = pika.PlainCredentials(settings.Q_USER, settings.Q_PASSWORD)
    return pika.ConnectionParameters(
        host=settings.Q_HOST,
        port=settings.Q_PORT,
        virtual_host=settings.Q_VHOST,
        credentials=credentials,
        heartbeat=settings.Q_HEARTBEAT,
        blocked_connection_timeout=settings.Q_BLOCKED_CONNECTION_TIMEOUT
    )

def initialise_rabbitmq_publish_connection() -> None:
    """
    Opens the RabbitMQ connection used for publishing, reused across requests.

    Args:
        None

    Returns:
        None

    Raises:
        RuntimeError:
            If the rabbitMQ connection cannot be established after all retry attempts.
        OperationalError:
            If rabbitMQ returns a connection error.
    """
    global _connection_publish, _channel_publish
    with _lock_publish:
        if _connection_publish is None or _connection_publish.is_closed:
            try:
                _connection_publish = pika.BlockingConnection(_build_rabbitmq_parameters())
                _channel_publish = _connection_publish.channel()
                logger.info("RabbitMQ publish connection initialised")

            except pika.exceptions.AMQPConnectionError as e:
                logger.critical(f"Failed to connect to RabbitMQ (publish): {e}")
                raise
        else:
            logger.warning("Reinitialisation of RabbitMQ publish connection occured. No new RabbitMQ initialisation is made.")

def initialise_rabbitmq_consume_connection() -> None:
    """
    Opens the RabbitMQ connection used by the background consumer thread.

    Args:
        None

    Returns:
        None

    Raises:
        RuntimeError:
            If the rabbitMQ connection cannot be established after all retry attempts.
        OperationalError:
            If rabbitMQ returns a connection error.
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
    Initialises both the publish and consume rabbitMQ connections.

    Args:
        None

    Returns:
        None

    Raises:
        RuntimeError:
            If either rabbitMQ connection cannot be established after all retry attempts.
        OperationalError:
            If rabbitMQ returns a connection error.
    """
    initialise_rabbitmq_publish_connection()
    initialise_rabbitmq_consume_connection()

def close_rabbitmq_connection() -> None:
    """
    Closes both the publish and consume rabbitMQ connections and channels if they exist.

    Args:
        None

    Returns:
        None
    """
    global _connection_publish, _channel_publish, _connection_consume, _channel_consume

    with _lock_publish:
        if _channel_publish and _channel_publish.is_open:
            _channel_publish.close()
            logger.info("RabbitMQ publish channel has been closed.")

        if _connection_publish and _connection_publish.is_open:
            _connection_publish.close()
            logger.info("RabbitMQ publish connection has been closed.")

    with _lock_consume:
        if _channel_consume and _channel_consume.is_open:
            _channel_consume.close()
            logger.info("RabbitMQ consume channel has been closed.")

        if _connection_consume and _connection_consume.is_open:
            _connection_consume.close()
            logger.info("RabbitMQ consume connection has been closed.")

def get_rabbitmq_publish_channel() -> pika.adapters.blocking_connection.BlockingChannel:
    """
    Retrieves an opened channel for publishing messages to rabbitMQ

    Args:
        None

    Returns:
        - pika.adapters.blocking_connection.BlockingChannel:
            Channel associated with the RabbitMQ publish connection, used for publishing messages.
    """
    global _connection_publish, _channel_publish

    with _lock_publish:
        if _connection_publish is None or _connection_publish.is_closed:
            initialise_rabbitmq_publish_connection()

        return _channel_publish

def get_rabbitmq_consume_channel() -> pika.adapters.blocking_connection.BlockingChannel:
    """
    Retrieves an opened channel for consuming messages from rabbitMQ

    Args:
        None

    Returns:
        - pika.adapters.blocking_connection.BlockingChannel:
            Channel associated with the RabbitMQ consume connection, used for consuming messages.
    """
    global _connection_consume, _channel_consume

    with _lock_consume:
        if _connection_consume is None or _connection_consume.is_closed:
            initialise_rabbitmq_consume_connection()

        return _channel_consume

def queue_push_task(payload: dict) -> bool:
    """
    Push a task into a RabbitMQ queue, retrying on connection failure up to Q_PUSH_MAX_ATTEMPTS times.

    Args:
        - payload (dict)

    Returns:
        - bool:
            True if the message was successfully published to RabbitMQ; otherwise, False once all attempts are exhausted.

    Notes:
        - UnroutableError is not retried - the queue/binding itself is misconfigured, so retrying would not help.
        - AMQPConnectionError/StreamLostError/ChannelWrongStateError/ChannelClosed are retried, with
          Q_PUSH_RETRY_DELAY seconds between attempts - these are the failure types expected if RabbitMQ
          itself is down/restarting, or the broker force-closed the channel.
        - Any other exception is intentionally left uncaught here, rather than added to the retry set -
          see poll_updates()'s outer except Exception, which logs the full traceback instead of folding
          an unexpected bug into the same retry-and-give-up path as a genuine outage.
    """
    for attempt in range(1, settings.Q_PUSH_MAX_ATTEMPTS + 1):
        try:
            channel = get_rabbitmq_publish_channel()
            channel.queue_declare(queue=settings.Q_CHANNEL_OUT, durable=True)
            channel.basic_publish(
                exchange="",
                routing_key=settings.Q_CHANNEL_OUT,
                body=json.dumps(payload),
                properties=pika.BasicProperties(
                    delivery_mode=pika.DeliveryMode.Persistent
                )
            )
            return True
        except pika.exceptions.UnroutableError:
            logger.error("RabbitMQ rejected task as unroutable. Not retrying.")
            return False
        except (
            pika.exceptions.AMQPConnectionError,
            pika.exceptions.StreamLostError,
            pika.exceptions.ChannelWrongStateError,
            pika.exceptions.ChannelClosed,
        ):
            logger.warning(f"RabbitMQ push attempt {attempt}/{settings.Q_PUSH_MAX_ATTEMPTS} failed.")
            if attempt < settings.Q_PUSH_MAX_ATTEMPTS:
                time.sleep(settings.Q_PUSH_RETRY_DELAY)

    logger.error(f"Failed to push task to RabbitMQ after {settings.Q_PUSH_MAX_ATTEMPTS} attempts.")
    return False

def queue_pull_task() -> dict | None:
    """
    Pull one task from a RabbitMQ queue.

    Args:
        None

    Returns:
        - dict | None:
            Returns message received from queue; otherwise None.
    """
    channel = get_rabbitmq_consume_channel()
    channel.queue_declare(queue=settings.Q_CHANNEL_IN, durable=True)
    # Ack the message later
    method_frame, header_frame, body = channel.basic_get(queue=settings.Q_CHANNEL_IN, auto_ack=False)
    if method_frame is None:
        return None
    else:
        payload = json.loads(body.decode())
        channel.basic_ack(delivery_tag=method_frame.delivery_tag)
        return payload

def queue_consume_task():
    """
    Consumes messages from RabbitMQ in a loop, reconnecting automatically on connection failures.

    Args:
        None

    Returns:
        None:
           Runs indefinitely while the consumer flag is enabled and does not return a meaningful value.

    Raises:
        pika.exceptions.AMQPConnectionError:
            Propagated internally to trigger reconnection handling.
        pika.exceptions.StreamLostError:
            Propagated internally to trigger reconnection handling.
        pika.exceptions.ChannelWrongStateError:
            Propagated internally to trigger reconnection handling.
    Notes:
        - Declares the queue before consuming.
        - Acks processed messages.
        - An undecodable message body is dropped immediately (not requeued) - the bytes
          never change on redelivery, so retrying cannot fix it.
        - Any other processing failure is requeued and retried up to Q_CONSUME_MAX_ATTEMPTS
          times (tracked per message body in _message_attempts), then dropped - see
          message_handler.py's process_message() for failures it deliberately does not
          raise (and so never reach this retry logic in the first place).
        - Reconnects automatically on connection/stream/channel failures.
        - Controlled by the global _consumer_running flag.
    """
    global _consumer_running
    while True:
        with _lock_consume:
            running = _consumer_running
        if not running:
            break
        try:
            channel = get_rabbitmq_consume_channel()
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

def start_queue_consumer():
    """
    Start the background queue consumer thread if it is not already running.

    Args:
        None

    Returns:
        None:
            This function initializes and starts the consumer thread when the consumer is not already active.

    Raises:
        None

    Notes:
        - Tracks thread state via `_consumer_thread` and `_consumer_running`.
        - Spawns a daemon thread running `queue_consume_task`.
        - No-op if already running.
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

def stop_queue_consumer():
    """
    Stop the background queue consumer.

    Args:
        None

    Returns:
        None:
            Updates the consumer state to indicate that the queue consumer should stop processing.

    Raises:
        None

    Notes:
        - Sets `_consumer_running` to False.
        - Schedules a thread-safe `stop_consuming()` if a channel is blocked in `start_consuming()`.
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
