# =============================================================================
# File        : config.py
# Description : Configuration file containing all settings required to run the application.
# Author      : SorinoSSK
# Created On  : 2026-08-29
#
# Features    :
#   - Application configuration
#
# =============================================================================
# I M P O R T   H E A D E R

import os

from pathlib import Path

# =============================================================================

class Settings:
    def __init__(self):
        # Application Common
        self.DATA_DIR = Path("/telegram_gateway/telegram_gateway_application/data")

        # Application Loggings
        DEFAULT_LOG_LEVEL                   = "INFO"
        DEFAULT_LOG_RETENTION_DAYS          = 30
        DEFAULT_LOG_MAX_SIZE_MB             = 100
        self.LOG_DIR                        = self.DATA_DIR / "logs"
        self.LOG_FILE                       = self.LOG_DIR / "telegram_gateway.log"
        self.LOG_LEVEL                      = os.getenv("LOG_LEVEL") or DEFAULT_LOG_LEVEL
        self.LOG_MAX_SIZE_MB                = get_env_int("LOG_MAX_SIZE_MB", DEFAULT_LOG_MAX_SIZE_MB)
        self.LOG_RETENTION_DAYS             = get_env_int("LOG_RETENTION_DAYS", DEFAULT_LOG_RETENTION_DAYS)

        # Telegram Bot Connection
        # NOTE: placeholder values - update TELEGRAM_BOT_TOKEN via env/.env before running.
        DEFAULT_TELEGRAM_BOT_TOKEN          = "REPLACE_WITH_BOT_TOKEN"
        DEFAULT_TELEGRAM_BOT_NAME           = "Rukia"
        DEFAULT_TELEGRAM_API_BASE_URL       = "https://api.telegram.org"
        DEFAULT_TELEGRAM_POLL_TIMEOUT       = 30
        DEFAULT_TELEGRAM_ALLOWED_CHAT_IDS   = "543086109"
        DEFAULT_TELEGRAM_ALLOWED_UPDATES    = "message,callback_query"
        self.TELEGRAM_BOT_TOKEN             = os.getenv("TELEGRAM_BOT_TOKEN") or DEFAULT_TELEGRAM_BOT_TOKEN
        self.TELEGRAM_BOT_NAME              = os.getenv("TELEGRAM_BOT_NAME") or DEFAULT_TELEGRAM_BOT_NAME
        self.TELEGRAM_API_BASE_URL          = os.getenv("TELEGRAM_API_BASE_URL") or DEFAULT_TELEGRAM_API_BASE_URL
        self.TELEGRAM_POLL_TIMEOUT          = get_env_int("TELEGRAM_POLL_TIMEOUT", DEFAULT_TELEGRAM_POLL_TIMEOUT)

        # Whitelist of chat IDs allowed to interact with the bot. Not using
        # get_env_int()-style parsing here - chat IDs for group/supergroup
        # chats are negative, and this is a set of values, not a single int.
        self.TELEGRAM_ALLOWED_CHAT_IDS = {
            int(chat_id.strip())
            for chat_id in (os.getenv("TELEGRAM_ALLOWED_CHAT_IDS") or DEFAULT_TELEGRAM_ALLOWED_CHAT_IDS).split(",")
            if chat_id.strip().lstrip("-").isdigit()
        }

        # Event types Telegram is asked to deliver - restricts what
        # getUpdates returns server-side (does not filter by chat).
        self.TELEGRAM_ALLOWED_UPDATES = [
            update_type.strip()
            for update_type in (os.getenv("TELEGRAM_ALLOWED_UPDATES") or DEFAULT_TELEGRAM_ALLOWED_UPDATES).split(",")
            if update_type.strip()
        ]

        # Queue Connection
        DEFAULT_Q_HOST                      = "chatbot-rabbitmq"
        DEFAULT_Q_USER                      = "chatbotAdmin"
        DEFAULT_Q_PASSWORD                  = "chatbotAdmin"
        DEFAULT_Q_PORT                      = 5672
        DEFAULT_Q_VHOST                     = "chatbot_vhost"
        DEFAULT_Q_CHANNEL_IN                = "telegram_gateway_inbound_queue"
        DEFAULT_Q_CHANNEL_OUT               = "telegram_gateway_outbound_queue"
        self.Q_HOST                         = os.getenv("Q_HOST") or DEFAULT_Q_HOST
        self.Q_USER                         = os.getenv("Q_USER") or DEFAULT_Q_USER
        self.Q_PASSWORD                     = os.getenv("Q_PASSWORD") or DEFAULT_Q_PASSWORD
        self.Q_PORT                         = get_env_int("Q_PORT", DEFAULT_Q_PORT)
        self.Q_VHOST                        = os.getenv("Q_VHOST") or DEFAULT_Q_VHOST
        self.Q_CHANNEL_IN                   = os.getenv("Q_CHANNEL_IN") or DEFAULT_Q_CHANNEL_IN
        self.Q_CHANNEL_OUT                  = os.getenv("Q_CHANNEL_OUT") or DEFAULT_Q_CHANNEL_OUT

        # Redis Connection
        DEFAULT_REDIS_HOST                  = "chatbot-redis"
        DEFAULT_REDIS_PORT                  = 6379
        DEFAULT_REDIS_DB                    = 0
        self.REDIS_HOST                     = os.getenv("REDIS_HOST") or DEFAULT_REDIS_HOST
        self.REDIS_PORT                     = get_env_int("REDIS_PORT", DEFAULT_REDIS_PORT)
        self.REDIS_DB                       = get_env_int("REDIS_DB", DEFAULT_REDIS_DB, minimum=0)

def get_env_int(name: str, default: int, minimum: int = 1) -> int:
        """
        Reads an integer environment variable, falling back to default if unset or invalid, clamped to minimum.

        Args:
            name (str):
                Name of the environment variable.

            default (int):
                Default value to return if the environment variable is not defined or contains an invalid integer value.

            minimum (int, optional):
                Lowest allowed value. Defaults to 1.

        Returns:
            int:
                The parsed integer value, constrained to be at least the specified minimum.

        Notes:
            Non-integer values fall back to default.
        """
        try:
            value = int(os.getenv(name) or default)
            return max(minimum, value)
        except ValueError:
            return default

# import settings for singleton
settings = Settings()
