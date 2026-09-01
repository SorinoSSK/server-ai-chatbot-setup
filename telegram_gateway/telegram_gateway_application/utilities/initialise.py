# =============================================================================
# File        : initialise.py
# Description : Provides centralised application initialisation for the Telegram Gateway application.
# Author      : SorinoSSK
# Created On  : 2026-08-29
#
# Features    :
#   - RabbitMQ queue initialisation.
#   - Redis connection initialisation.
#   - Closes out drafts orphaned by a previous run before polling resumes.
#
# Notes       :
#   - Intended to be executed once during application startup.
#   - Initialisation order should follow application dependency requirements.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging
import threading

from .utils_queue.queue import (
    initialise_rabbitmq_connection,
    start_queue_consumer,
    stop_queue_consumer,
    close_rabbitmq_connection
)
from .utils_redis.database import initialise_redis_connection, close_redis_connection
from .utils_telegram.gateway_inbound import poll_updates, stop_polling
from .utils_telegram.utilities.image_draft_handler import close_orphaned_drafts

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# =============================================================================

def initialise_application() -> None:
    """
    Initialises RabbitMQ and starts the RabbitMQ consumer and Telegram polling threads.

    Args:
        None

    Returns:
        None

    Raises:
        redis.exceptions.RedisError:
            If the Redis connection cannot be established.

        pika.exceptions.AMQPConnectionError:
            If a RabbitMQ connection cannot be established.
    """

    # Initialise RabbitMQ connections and start RabbitMQ consumer
    initialise_rabbitmq_connection()
    start_queue_consumer()

    # Initialise Redis - required before polling starts, since poll_updates() uses it for task mapping.
    initialise_redis_connection()

    # Close out any draft left behind by a previous run before new messages can arrive -
    # its in-memory keep-alive timer did not survive the restart (see image_draft_handler.py).
    close_orphaned_drafts()

    # Starts the Telegram long polling loop on its own thread.
    threading.Thread(target=poll_updates, daemon=True).start()

    logger.info("Telegram Gateway application initialised.")

def terminate_application() -> None:
    """
    Stops Telegram polling and the RabbitMQ consumer, then closes the RabbitMQ connection.

    Args:
        None

    Returns:
        None
    """
    stop_polling()
    stop_queue_consumer()
    close_rabbitmq_connection()
    close_redis_connection()
    logger.info("Telegram Gateway application terminated.")

# =============================================================================
