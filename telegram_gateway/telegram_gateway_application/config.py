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
        DEFAULT_TELEGRAM_CLIENT_TIMEOUT     = 10
        DEFAULT_TELEGRAM_ALLOWED_CHAT_IDS   = ""
        DEFAULT_TELEGRAM_ALLOWED_UPDATES    = "message,callback_query"
        DEFAULT_TELEGRAM_UNAUTHORISED_CACHE_SIZE                = 100
        DEFAULT_TELEGRAM_UNAUTHORISED_EVICTION_WINDOW_PERCENT   = 10
        DEFAULT_TELEGRAM_UNAUTHORISED_ACCESS_COUNT_CAP          = 1000
        DEFAULT_TELEGRAM_UPDATE_MAX_ATTEMPTS                    = 3
        DEFAULT_TELEGRAM_TYPING_INTERVAL_MIN                    = 5
        DEFAULT_TELEGRAM_TYPING_INTERVAL_MAX                    = 14
        DEFAULT_TELEGRAM_TYPING_MAX_PINGS_MIN                   = 5
        DEFAULT_TELEGRAM_TYPING_MAX_PINGS_MAX                   = 8
        DEFAULT_TELEGRAM_SEND_MAX_ATTEMPTS                      = 3
        DEFAULT_TELEGRAM_SEND_RETRY_DELAY                       = 1
        DEFAULT_TELEGRAM_CAPTION_MAX_LENGTH                     = 1024
        self.TELEGRAM_BOT_TOKEN             = os.getenv("TELEGRAM_BOT_TOKEN") or DEFAULT_TELEGRAM_BOT_TOKEN
        self.TELEGRAM_BOT_NAME              = os.getenv("TELEGRAM_BOT_NAME") or DEFAULT_TELEGRAM_BOT_NAME
        self.TELEGRAM_API_BASE_URL          = os.getenv("TELEGRAM_API_BASE_URL") or DEFAULT_TELEGRAM_API_BASE_URL
        self.TELEGRAM_POLL_TIMEOUT          = get_env_int("TELEGRAM_POLL_TIMEOUT", DEFAULT_TELEGRAM_POLL_TIMEOUT)
        self.TELEGRAM_CLIENT_TIMEOUT        = get_env_int("TELEGRAM_CLIENT_TIMEOUT", DEFAULT_TELEGRAM_CLIENT_TIMEOUT)
        self.TELEGRAM_UNAUTHORISED_CACHE_SIZE                   = get_env_int("TELEGRAM_UNAUTHORISED_CACHE_SIZE", DEFAULT_TELEGRAM_UNAUTHORISED_CACHE_SIZE)
        self.TELEGRAM_UNAUTHORISED_EVICTION_WINDOW_PERCENT      = get_env_int("TELEGRAM_UNAUTHORISED_EVICTION_WINDOW_PERCENT", DEFAULT_TELEGRAM_UNAUTHORISED_EVICTION_WINDOW_PERCENT)
        self.TELEGRAM_UNAUTHORISED_ACCESS_COUNT_CAP             = get_env_int("TELEGRAM_UNAUTHORISED_ACCESS_COUNT_CAP", DEFAULT_TELEGRAM_UNAUTHORISED_ACCESS_COUNT_CAP)
        self.TELEGRAM_UPDATE_MAX_ATTEMPTS   = get_env_int("TELEGRAM_UPDATE_MAX_ATTEMPTS", DEFAULT_TELEGRAM_UPDATE_MAX_ATTEMPTS)
        self.TELEGRAM_TYPING_INTERVAL_MIN   = get_env_int("TELEGRAM_TYPING_INTERVAL_MIN", DEFAULT_TELEGRAM_TYPING_INTERVAL_MIN)
        self.TELEGRAM_TYPING_INTERVAL_MAX   = get_env_int("TELEGRAM_TYPING_INTERVAL_MAX", DEFAULT_TELEGRAM_TYPING_INTERVAL_MAX)
        self.TELEGRAM_TYPING_MAX_PINGS_MIN  = get_env_int("TELEGRAM_TYPING_MAX_PINGS_MIN", DEFAULT_TELEGRAM_TYPING_MAX_PINGS_MIN)
        self.TELEGRAM_TYPING_MAX_PINGS_MAX  = get_env_int("TELEGRAM_TYPING_MAX_PINGS_MAX", DEFAULT_TELEGRAM_TYPING_MAX_PINGS_MAX)
        self.TELEGRAM_SEND_MAX_ATTEMPTS     = get_env_int("TELEGRAM_SEND_MAX_ATTEMPTS", DEFAULT_TELEGRAM_SEND_MAX_ATTEMPTS)
        self.TELEGRAM_SEND_RETRY_DELAY      = get_env_int("TELEGRAM_SEND_RETRY_DELAY", DEFAULT_TELEGRAM_SEND_RETRY_DELAY)
        self.TELEGRAM_CAPTION_MAX_LENGTH    = get_env_int("TELEGRAM_CAPTION_MAX_LENGTH", DEFAULT_TELEGRAM_CAPTION_MAX_LENGTH)

        # Draft Handling (media received without an instruction yet - see utils_telegram/draft_timer.py)
        DEFAULT_DRAFT_CLOSE_SECONDS          = 3300   # 55 min hard close (Telegram's file link is only guaranteed for 1 hour)
        DEFAULT_DRAFT_WARNING_LEAD_SECONDS   = 120    # warning sent 2 min before the hard close
        DEFAULT_DRAFT_TYPING_LEAD_SECONDS    = 60     # "typing..." runs for the 1 min immediately before the warning
        DEFAULT_DRAFT_MAPPING_TTL_SECONDS    = 3600   # Redis-side backstop, slightly beyond the hard close
        DEFAULT_MEDIA_GROUP_DEDUPE_SECONDS   = 10     # window for deduping repeated album-item replies sharing one media_group_id
        self.DRAFT_CLOSE_SECONDS            = get_env_int("DRAFT_CLOSE_SECONDS", DEFAULT_DRAFT_CLOSE_SECONDS)
        self.DRAFT_WARNING_LEAD_SECONDS     = get_env_int("DRAFT_WARNING_LEAD_SECONDS", DEFAULT_DRAFT_WARNING_LEAD_SECONDS)
        self.DRAFT_TYPING_LEAD_SECONDS      = get_env_int("DRAFT_TYPING_LEAD_SECONDS", DEFAULT_DRAFT_TYPING_LEAD_SECONDS)
        self.DRAFT_MAPPING_TTL_SECONDS      = get_env_int("DRAFT_MAPPING_TTL_SECONDS", DEFAULT_DRAFT_MAPPING_TTL_SECONDS)
        self.MEDIA_GROUP_DEDUPE_SECONDS     = get_env_int("MEDIA_GROUP_DEDUPE_SECONDS", DEFAULT_MEDIA_GROUP_DEDUPE_SECONDS)

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
        DEFAULT_Q_PUSH_MAX_ATTEMPTS         = 30
        DEFAULT_Q_PUSH_RETRY_DELAY          = 1
        DEFAULT_Q_HEARTBEAT                 = 600
        DEFAULT_Q_BLOCKED_CONNECTION_TIMEOUT= 300
        DEFAULT_Q_CONSUME_RETRY_DELAY       = 1
        DEFAULT_Q_CONSUME_MAX_ATTEMPTS      = 5
        self.Q_HOST                         = os.getenv("Q_HOST") or DEFAULT_Q_HOST
        self.Q_USER                         = os.getenv("Q_USER") or DEFAULT_Q_USER
        self.Q_PASSWORD                     = os.getenv("Q_PASSWORD") or DEFAULT_Q_PASSWORD
        self.Q_PORT                         = get_env_int("Q_PORT", DEFAULT_Q_PORT)
        self.Q_VHOST                        = os.getenv("Q_VHOST") or DEFAULT_Q_VHOST
        self.Q_CHANNEL_IN                   = os.getenv("Q_CHANNEL_IN") or DEFAULT_Q_CHANNEL_IN
        self.Q_CHANNEL_OUT                  = os.getenv("Q_CHANNEL_OUT") or DEFAULT_Q_CHANNEL_OUT
        self.Q_PUSH_MAX_ATTEMPTS            = get_env_int("Q_PUSH_MAX_ATTEMPTS", DEFAULT_Q_PUSH_MAX_ATTEMPTS)
        self.Q_PUSH_RETRY_DELAY             = get_env_int("Q_PUSH_RETRY_DELAY", DEFAULT_Q_PUSH_RETRY_DELAY)
        self.Q_HEARTBEAT                    = get_env_int("Q_HEARTBEAT", DEFAULT_Q_HEARTBEAT)
        self.Q_BLOCKED_CONNECTION_TIMEOUT   = get_env_int("Q_BLOCKED_CONNECTION_TIMEOUT", DEFAULT_Q_BLOCKED_CONNECTION_TIMEOUT)
        self.Q_CONSUME_RETRY_DELAY          = get_env_int("Q_CONSUME_RETRY_DELAY", DEFAULT_Q_CONSUME_RETRY_DELAY)
        self.Q_CONSUME_MAX_ATTEMPTS         = get_env_int("Q_CONSUME_MAX_ATTEMPTS", DEFAULT_Q_CONSUME_MAX_ATTEMPTS)

        # Redis Connection
        DEFAULT_REDIS_HOST                  = "chatbot-redis"
        DEFAULT_REDIS_PORT                  = 6379
        DEFAULT_REDIS_DB                    = 0
        DEFAULT_REDIS_TASK_RETRY_DELAY      = 1
        DEFAULT_REDIS_TASK_MAX_ATTEMPTS     = 5
        DEFAULT_REDIS_TASK_MAPPING_TTL_SECONDS = 86400
        self.REDIS_HOST                     = os.getenv("REDIS_HOST") or DEFAULT_REDIS_HOST
        self.REDIS_PORT                     = get_env_int("REDIS_PORT", DEFAULT_REDIS_PORT)
        self.REDIS_DB                       = get_env_int("REDIS_DB", DEFAULT_REDIS_DB, minimum=0)
        self.REDIS_TASK_RETRY_DELAY         = get_env_int("REDIS_TASK_RETRY_DELAY", DEFAULT_REDIS_TASK_RETRY_DELAY)
        self.REDIS_TASK_MAX_ATTEMPTS        = get_env_int("REDIS_TASK_MAX_ATTEMPTS", DEFAULT_REDIS_TASK_MAX_ATTEMPTS)
        self.REDIS_TASK_MAPPING_TTL_SECONDS = get_env_int("REDIS_TASK_MAPPING_TTL_SECONDS", DEFAULT_REDIS_TASK_MAPPING_TTL_SECONDS)

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
