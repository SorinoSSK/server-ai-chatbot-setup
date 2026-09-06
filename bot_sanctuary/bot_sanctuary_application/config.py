# =============================================================================
# File        : config.py
# Description : Configuration file containing all settings required to run the application.
# Author      : SorinoSSK
# Created On  : 2026-09-06
#
# Features    :
#   - Application configuration
#
# Notes       :
#   - Minimal starting shape - only the settings needed for logging, plus the LLM
#     provider identity/credential, so far. Queue Connection / agent-call settings
#     are added as their owning modules are built (see bot_sanctuary/CODE_TODO.md).
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
        self.DATA_DIR = Path("/bot_sanctuary/bot_sanctuary_application/data")

        # Application Loggings
        DEFAULT_LOG_LEVEL                                       = "INFO"
        DEFAULT_LOG_RETENTION_DAYS                              = 30
        DEFAULT_LOG_MAX_SIZE_MB                                 = 100
        self.LOG_DIR                                            = self.DATA_DIR / "logs"
        self.LOG_FILE                                           = self.LOG_DIR / "bot_sanctuary.log"
        self.LOG_LEVEL                                          = os.getenv("LOG_LEVEL") or DEFAULT_LOG_LEVEL
        self.LOG_MAX_SIZE_MB                                    = get_env_int("LOG_MAX_SIZE_MB", DEFAULT_LOG_MAX_SIZE_MB)
        self.LOG_RETENTION_DAYS                                 = get_env_int("LOG_RETENTION_DAYS", DEFAULT_LOG_RETENTION_DAYS)

        # LLM Provider (see bot_sanctuary/CODE_TODO.md - Authentication)
        DEFAULT_LLM_TYPE                                        = ""
        DEFAULT_LLM_OAUTH_TOKEN                                 = ""
        self.LLM_TYPE                                           = os.getenv("LLM_TYPE") or DEFAULT_LLM_TYPE
        self.LLM_OAUTH_TOKEN                                    = os.getenv("LLM_OAUTH_TOKEN") or DEFAULT_LLM_OAUTH_TOKEN

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
