# =============================================================================
# File        : gateway_outbound.py
# Description : File responsible for sending outgoing messages back to the Telegram Bot API.
# Author      : SorinoSSK
# Created On  : 2026-08-29
#
# Features    :
#   - Sends a text message back to a Telegram chat via the sendMessage endpoint.
#
# =============================================================================
# I M P O R T   H E A D E R

import logging
import requests

from ...config import settings

# =============================================================================
# G L O B A L   V A R I A B L E

logger = logging.getLogger(__name__)

# =============================================================================

def send_message(chat_id: int | str, text: str) -> bool:
    """
    Send a text message back to a Telegram chat via the Bot API.

    Args:
        - chat_id (int | str):
            Identifier of the Telegram chat to send the message to.

        - text (str):
            Message content to send.

    Returns:
        - bool:
            True if the message was sent successfully; otherwise False.
    """
    api_url = f"{settings.TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            api_url,
            json={
                "chat_id": chat_id,
                "text": text
            }
        )
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException:
        logger.exception("Failed to send message to Telegram.")
        return False

# =============================================================================
