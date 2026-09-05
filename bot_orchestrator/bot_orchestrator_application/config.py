# =============================================================================
# File        : config.py
# Description : Configuration file containing all settings required to run the application.
# Author      : SorinoSSK
# Created On  : 2026-09-04
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
    """
    Loads and holds every environment-driven setting the application depends on.

    Each setting falls back to a sensible default when its environment variable is unset or invalid.
    A single instance (settings, below) is constructed once and imported everywhere else as the application's sole source of configuration.
    """

    def __init__(self):
        # Application Common
        self.DATA_DIR = Path("/bot_orchestrator/bot_orchestrator_application/data")

        # Application Loggings
        DEFAULT_LOG_LEVEL                                       = "INFO"
        DEFAULT_LOG_RETENTION_DAYS                              = 30
        DEFAULT_LOG_MAX_SIZE_MB                                 = 100
        self.LOG_DIR                                            = self.DATA_DIR / "logs"
        self.LOG_FILE                                           = self.LOG_DIR / "bot_orchestrator.log"
        self.LOG_LEVEL                                          = os.getenv("LOG_LEVEL") or DEFAULT_LOG_LEVEL
        self.LOG_MAX_SIZE_MB                                    = get_env_int("LOG_MAX_SIZE_MB", DEFAULT_LOG_MAX_SIZE_MB)
        self.LOG_RETENTION_DAYS                                 = get_env_int("LOG_RETENTION_DAYS", DEFAULT_LOG_RETENTION_DAYS)

        # Queue Connection
        DEFAULT_Q_HOST                                          = "chatbot-rabbitmq"
        DEFAULT_Q_USER                                          = ""
        DEFAULT_Q_PASSWORD                                      = ""
        DEFAULT_Q_PORT                                          = 5672
        DEFAULT_Q_VHOST                                         = "chatbot_vhost"
        DEFAULT_Q_CHANNEL_IN                                    = "bot_orchestrator_inbound_queue"
        DEFAULT_Q_CHANNEL_OUT                                   = "bot_orchestrator_outbound_queue"
        DEFAULT_Q_PUSH_MAX_ATTEMPTS                             = 30
        DEFAULT_Q_PUSH_RETRY_DELAY                              = 1
        DEFAULT_Q_HEARTBEAT                                     = 600
        DEFAULT_Q_BLOCKED_CONNECTION_TIMEOUT                    = 300
        DEFAULT_Q_CONSUME_RETRY_DELAY                           = 1
        DEFAULT_Q_CONSUME_MAX_ATTEMPTS                          = 5
        self.Q_HOST                                             = os.getenv("Q_HOST") or DEFAULT_Q_HOST
        self.Q_USER                                             = os.getenv("Q_USER") or DEFAULT_Q_USER
        self.Q_PASSWORD                                         = os.getenv("Q_PASSWORD") or DEFAULT_Q_PASSWORD
        self.Q_PORT                                             = get_env_int("Q_PORT", DEFAULT_Q_PORT)
        self.Q_VHOST                                            = os.getenv("Q_VHOST") or DEFAULT_Q_VHOST
        self.Q_CHANNEL_IN                                       = os.getenv("Q_CHANNEL_IN") or DEFAULT_Q_CHANNEL_IN
        self.Q_CHANNEL_OUT                                      = os.getenv("Q_CHANNEL_OUT") or DEFAULT_Q_CHANNEL_OUT
        self.Q_PUSH_MAX_ATTEMPTS                                = get_env_int("Q_PUSH_MAX_ATTEMPTS", DEFAULT_Q_PUSH_MAX_ATTEMPTS)
        self.Q_PUSH_RETRY_DELAY                                 = get_env_int("Q_PUSH_RETRY_DELAY", DEFAULT_Q_PUSH_RETRY_DELAY)
        self.Q_HEARTBEAT                                        = get_env_int("Q_HEARTBEAT", DEFAULT_Q_HEARTBEAT)
        self.Q_BLOCKED_CONNECTION_TIMEOUT                       = get_env_int("Q_BLOCKED_CONNECTION_TIMEOUT", DEFAULT_Q_BLOCKED_CONNECTION_TIMEOUT)
        self.Q_CONSUME_RETRY_DELAY                              = get_env_int("Q_CONSUME_RETRY_DELAY", DEFAULT_Q_CONSUME_RETRY_DELAY)
        self.Q_CONSUME_MAX_ATTEMPTS                             = get_env_int("Q_CONSUME_MAX_ATTEMPTS", DEFAULT_Q_CONSUME_MAX_ATTEMPTS)

def get_env_int(name: str, default: int, minimum: int = 1) -> int:
        """
        Reads an integer environment variable, falling back to default if unset or invalid, clamped to minimum.

        Args:
            name (str):
                Environment variable name.

            default (int):
                Fallback if unset or invalid.

            minimum (int, optional):
                Lowest allowed value. Defaults to 1.

        Returns:
            int:
                Parsed value, clamped to minimum.
        """
        try:
            value = int(os.getenv(name) or default)
            return max(minimum, value)
        except ValueError:
            return max(minimum, default)

# import settings for singleton
settings = Settings()
