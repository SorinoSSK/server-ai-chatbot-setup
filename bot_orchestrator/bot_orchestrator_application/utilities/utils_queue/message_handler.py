# =============================================================================
# File        : message_handler.py
# Description : File responsible for handling messages consumed from RabbitMQ.
# Author      : SorinoSSK
# Created On  : 2026-09-04
#
# Notes       :
#   - Owns its own JSON parsing so a malformed payload is logged and dropped rather than requeued forever.
#   - Orchestration/dispatch logic has not yet been defined - extend process_message() to route by
#     data["type"] to dedicated handlers once requirements are set.
#
# =============================================================================
# I M P O R T   H E A D E R

import json
import logging

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# =============================================================================

def process_message(payload: str) -> None:
    """
    Handle a single message consumed from RabbitMQ.

    Args:
        payload (str):
            Raw JSON-encoded message body.

    Returns:
        None

    Notes:
        - Invalid/non-object JSON is logged and dropped rather than raised, so it isn't requeued forever.
        - Currently only logs the received message - no dispatch logic has been implemented yet.
    """
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        logger.critical(f"Received RabbitMQ message with invalid JSON payload: {payload}")
        return

    if not isinstance(data, dict):
        logger.critical(f"Received RabbitMQ message with a non-object JSON payload: {payload}")
        return

    logger.info(f"Received RabbitMQ message type={data.get('type')} task_id={data.get('task_id')}.")

# =============================================================================
