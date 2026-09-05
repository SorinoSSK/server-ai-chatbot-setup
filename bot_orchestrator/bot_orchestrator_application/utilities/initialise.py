# =============================================================================
# File        : initialise.py
# Description : Provides centralised application initialisation for the Bot Orchestrator application.
# Author      : SorinoSSK
# Created On  : 2026-09-04
#
# Features    :
#   - RabbitMQ queue initialisation.
#
# Notes       :
#   - Intended to be executed once during application startup.
#   - Initialisation order should follow application dependency requirements.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging

from .utils_queue.queue import (
    initialise_rabbitmq_connection,
    start_queue_consumer,
    stop_queue_consumer,
    close_rabbitmq_connection
)

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# =============================================================================

def initialise_application() -> None:
    """
    Initialises RabbitMQ and starts the RabbitMQ consumer.

    Args:
        None

    Returns:
        None

    Raises:
        pika.exceptions.AMQPConnectionError:
            If a RabbitMQ connection cannot be established.
    """

    # Initialise RabbitMQ connections and start RabbitMQ consumer
    initialise_rabbitmq_connection()
    start_queue_consumer()

    logger.info("Bot Orchestrator application initialised.")

def terminate_application() -> None:
    """
    Stops the RabbitMQ consumer, then closes the RabbitMQ connection.

    Args:
        None

    Returns:
        None
    """
    stop_queue_consumer()
    close_rabbitmq_connection()
    logger.info("Bot Orchestrator application terminated.")

# =============================================================================
