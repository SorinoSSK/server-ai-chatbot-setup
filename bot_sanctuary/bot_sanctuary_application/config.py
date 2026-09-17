# =============================================================================
# File        : config.py
# Description : Configuration file containing all settings required to run the application.
# Author      : SorinoSSK
# Created On  : 2026-09-06
#
# Features    :
#   - Environment-driven application configuration, with sensible defaults for every setting.
#
# Notes       :
#   - A single settings instance is constructed once and imported wherever configuration is needed.
#
# =============================================================================
# I M P O R T   H E A D E R

import os
import re

from pathlib import Path
from datetime import time
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# =============================================================================

@dataclass
class AgentPersona:
    """
    One agent's fully-parsed configuration, loaded from its own libraries/<llm_type>/<call_name>.json file.

    Shared across every LLM provider rather than defined per-provider, so a caller can detect a changed agent definition with a plain equality check.

    Attributes:
        body (str):
            The fully-resolved system prompt text, ready to hand to a provider's own "system prompt" mechanism.

        tools (list[str] | None):
            The agent definition's own declared tool list, if any.

        model (str | None):
            The agent definition's own declared model name, if any.

        persona (dict):
            The raw parsed JSON object the other fields were derived from.
    """
    body: str
    tools: "list[str] | None"
    model: "str | None"
    persona: dict

class Settings:
    """
    Loads and holds every environment-driven setting the application depends on.

    Each setting falls back to a sensible default when its environment variable is unset or invalid.
    A single instance (settings, below) is constructed once and imported everywhere else as the application's sole source of configuration.
    """

    def __init__(self):
        # Application Common
        self.DATA_DIR = Path("/bot_sanctuary/bot_sanctuary_application/data")

        # Application Logging
        DEFAULT_LOG_LEVEL                                       = "INFO"
        DEFAULT_LOG_RETENTION_DAYS                              = 30
        DEFAULT_LOG_MAX_SIZE_MB                                 = 100
        self.LOG_DIR                                            = self.DATA_DIR / "logs"
        self.LOG_FILE                                           = self.LOG_DIR / "bot_sanctuary.log"
        self.LOG_LEVEL                                          = os.getenv("LOG_LEVEL") or DEFAULT_LOG_LEVEL
        self.LOG_MAX_SIZE_MB                                    = get_env_int("LOG_MAX_SIZE_MB", DEFAULT_LOG_MAX_SIZE_MB)
        self.LOG_RETENTION_DAYS                                 = get_env_int("LOG_RETENTION_DAYS", DEFAULT_LOG_RETENTION_DAYS)

        # Timezone (see get_env_timezone(), utilities/logging_setup.py)
        # Every wall-clock timing decision this application makes, and its own log timestamps, are anchored to this value rather than the container's OS-level local time directly.
        # Deliberately reads the standard "TZ" name, not a project-prefixed one, since that's also what the container's own OS layer already expects.
        DEFAULT_TZ                                              = "UTC"
        self.TZ                                                 = get_env_timezone("TZ", DEFAULT_TZ)

        # LLM Provider - each named Call resolves its own LLM_<CALL>_TYPE, falling back to LLM_CHAT_TYPE.
        DEFAULT_LLM_CHAT_TYPE                                   = ""
        self.LLM_CHAT_TYPE                                      = os.getenv("LLM_CHAT_TYPE") or DEFAULT_LLM_CHAT_TYPE

        self.LLM_ARCHITECT_TYPE                                 = os.getenv("LLM_ARCHITECT_TYPE") or self.LLM_CHAT_TYPE
        self.LLM_CODER_TYPE                                     = os.getenv("LLM_CODER_TYPE") or self.LLM_CHAT_TYPE
        self.LLM_REVIEW_TYPE                                    = os.getenv("LLM_REVIEW_TYPE") or self.LLM_CHAT_TYPE
        self.LLM_DOCUMENTATION_TYPE                             = os.getenv("LLM_DOCUMENTATION_TYPE") or self.LLM_CHAT_TYPE

        # Agent Call Pipeline (see utils_calls/call_dispatch_handler.py)
        # Bounds a single turn's dispatch_queue-driven hop count (each handoff and each corrective retry both
        # consume one hop) - so a misbehaving/looping Call chain can never run indefinitely.
        DEFAULT_CALL_MAX_HOPS                                   = 5
        self.CALL_MAX_HOPS                                      = get_env_int("CALL_MAX_HOPS", DEFAULT_CALL_MAX_HOPS)

        DEFAULT_LLM_CLAUDE_ACCESS_TYPE                          = ""
        DEFAULT_LLM_CLAUDE_TOKEN                                = ""
        DEFAULT_LLM_CODEX_ACCESS_TYPE                           = ""
        DEFAULT_LLM_CODEX_TOKEN                                 = ""
        DEFAULT_LLM_DEEPSEEK_ACCESS_TYPE                        = "API"
        DEFAULT_LLM_DEEPSEEK_TOKEN                              = ""
        DEFAULT_LLM_QWEN_ACCESS_TYPE                            = "API"
        DEFAULT_LLM_QWEN_TOKEN                                  = ""
        self.LLM_CLAUDE_ACCESS_TYPE                             = os.getenv("LLM_CLAUDE_ACCESS_TYPE") or DEFAULT_LLM_CLAUDE_ACCESS_TYPE
        self.LLM_CLAUDE_TOKEN                                   = os.getenv("LLM_CLAUDE_TOKEN") or DEFAULT_LLM_CLAUDE_TOKEN
        self.LLM_CODEX_ACCESS_TYPE                              = os.getenv("LLM_CODEX_ACCESS_TYPE") or DEFAULT_LLM_CODEX_ACCESS_TYPE
        self.LLM_CODEX_TOKEN                                    = os.getenv("LLM_CODEX_TOKEN") or DEFAULT_LLM_CODEX_TOKEN
        self.LLM_DEEPSEEK_ACCESS_TYPE                           = os.getenv("LLM_DEEPSEEK_ACCESS_TYPE") or DEFAULT_LLM_DEEPSEEK_ACCESS_TYPE
        self.LLM_DEEPSEEK_TOKEN                                 = os.getenv("LLM_DEEPSEEK_TOKEN") or DEFAULT_LLM_DEEPSEEK_TOKEN
        self.LLM_QWEN_ACCESS_TYPE                               = os.getenv("LLM_QWEN_ACCESS_TYPE") or DEFAULT_LLM_QWEN_ACCESS_TYPE
        self.LLM_QWEN_TOKEN                                     = os.getenv("LLM_QWEN_TOKEN") or DEFAULT_LLM_QWEN_TOKEN

        # Agent Session Platform (see utils_agents/services/claude_session_service.py)
        # Global, provider-agnostic timeouts for any always-on, persistent-connection agent session platform -
        # not specific to Claude, even though it's the only provider with one implemented today.
        DEFAULT_AGENT_QUERY_TIMEOUT_SECONDS                     = 120
        DEFAULT_AGENT_SHUTDOWN_TIMEOUT_SECONDS                  = 30
        self.AGENT_QUERY_TIMEOUT_SECONDS                        = get_env_int("AGENT_QUERY_TIMEOUT_SECONDS", DEFAULT_AGENT_QUERY_TIMEOUT_SECONDS)
        self.AGENT_SHUTDOWN_TIMEOUT_SECONDS                     = get_env_int("AGENT_SHUTDOWN_TIMEOUT_SECONDS", DEFAULT_AGENT_SHUTDOWN_TIMEOUT_SECONDS)

        # Bot Identity
        DEFAULT_TELEGRAM_BOT_NAME                               = ""
        self.TELEGRAM_BOT_NAME                                  = os.getenv("TELEGRAM_BOT_NAME") or DEFAULT_TELEGRAM_BOT_NAME

        # Queue Connection
        DEFAULT_Q_HOST                                          = "chatbot-rabbitmq"
        DEFAULT_Q_USER                                          = ""
        DEFAULT_Q_PASSWORD                                      = ""
        DEFAULT_Q_PORT                                          = 5672
        DEFAULT_Q_VHOST                                         = "chatbot_vhost"
        DEFAULT_Q_CHANNEL_IN                                    = "telegram_gateway_outbound_queue"
        DEFAULT_Q_CHANNEL_OUT                                   = "telegram_gateway_inbound_queue"
        DEFAULT_Q_PUSH_MAX_ATTEMPTS                             = 30
        DEFAULT_Q_PUSH_RETRY_DELAY                              = 1
        DEFAULT_Q_HEARTBEAT                                     = 600
        DEFAULT_Q_BLOCKED_CONNECTION_TIMEOUT                    = 300
        DEFAULT_Q_CONSUME_RETRY_DELAY                           = 1
        DEFAULT_Q_CONSUME_MAX_ATTEMPTS                          = 5
        DEFAULT_Q_CONNECT_RETRY_DELAY_SECONDS                   = 5
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
        self.Q_CONNECT_RETRY_DELAY_SECONDS                      = get_env_int("Q_CONNECT_RETRY_DELAY_SECONDS", DEFAULT_Q_CONNECT_RETRY_DELAY_SECONDS)

        # SMTP / Mailer
        DEFAULT_SMTP_ENABLE_MAILER                              = False
        DEFAULT_SMTP_FORCE_SSL                                  = False
        DEFAULT_SMTP_AUTH_TYPE                                  = "LOGIN"
        DEFAULT_SMTP_SKIP_TLS                                   = False
        DEFAULT_SMTP_HOST                                       = ""
        DEFAULT_SMTP_PORT                                       = 587
        DEFAULT_SMTP_FROM_EMAIL                                 = ""
        DEFAULT_SMTP_TO_EMAIL                                   = ""
        DEFAULT_SMTP_USERNAME                                   = ""
        DEFAULT_SMTP_PASSWORD                                   = ""
        self.SMTP_ENABLE_MAILER                                 = get_env_bool("SMTP_ENABLE_MAILER", DEFAULT_SMTP_ENABLE_MAILER)
        self.SMTP_FORCE_SSL                                     = get_env_bool("SMTP_FORCE_SSL", DEFAULT_SMTP_FORCE_SSL)
        self.SMTP_AUTH_TYPE                                     = os.getenv("SMTP_AUTH_TYPE") or DEFAULT_SMTP_AUTH_TYPE
        self.SMTP_SKIP_TLS                                      = get_env_bool("SMTP_SKIP_TLS", DEFAULT_SMTP_SKIP_TLS)
        self.SMTP_HOST                                          = os.getenv("SMTP_HOST") or DEFAULT_SMTP_HOST
        self.SMTP_PORT                                          = get_env_int("SMTP_PORT", DEFAULT_SMTP_PORT)
        self.SMTP_FROM_EMAIL                                    = os.getenv("SMTP_FROM_EMAIL") or DEFAULT_SMTP_FROM_EMAIL
        self.SMTP_TO_EMAIL                                      = os.getenv("SMTP_TO_EMAIL") or DEFAULT_SMTP_TO_EMAIL
        self.SMTP_USERNAME                                      = os.getenv("SMTP_USERNAME") or DEFAULT_SMTP_USERNAME
        self.SMTP_PASSWORD                                      = os.getenv("SMTP_PASSWORD") or DEFAULT_SMTP_PASSWORD

        # gateway_alert Throttle
        DEFAULT_GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS           = 86400
        self.GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS              = get_env_int("GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS", DEFAULT_GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS)

        # Redis Retry
        DEFAULT_REDIS_TASK_MAX_ATTEMPTS                         = 5
        DEFAULT_REDIS_TASK_RETRY_DELAY                          = 1
        self.REDIS_TASK_MAX_ATTEMPTS                            = get_env_int("REDIS_TASK_MAX_ATTEMPTS", DEFAULT_REDIS_TASK_MAX_ATTEMPTS)
        self.REDIS_TASK_RETRY_DELAY                             = get_env_int("REDIS_TASK_RETRY_DELAY", DEFAULT_REDIS_TASK_RETRY_DELAY)

        # Session Routing
        DEFAULT_SESSION_INBOX_MAX_SIZE                          = 100
        self.SESSION_INBOX_MAX_SIZE                             = get_env_int("SESSION_INBOX_MAX_SIZE", DEFAULT_SESSION_INBOX_MAX_SIZE)
        self.SESSION_DIR                                        = self.DATA_DIR / "sessions"

        DEFAULT_SESSION_SHUTDOWN_TIMEOUT_SECONDS                = 30
        self.SESSION_SHUTDOWN_TIMEOUT_SECONDS                   = get_env_int("SESSION_SHUTDOWN_TIMEOUT_SECONDS", DEFAULT_SESSION_SHUTDOWN_TIMEOUT_SECONDS, minimum=0)

        # Session Reset (see utils_session/session_worker.py::trigger_timed_session_reset())
        # Optional daily timed global session reset - this application decides and fires it itself, on its own schedule.
        # Empty (the default) means no timed reset at all.
        # Accepts either a 24-hour ("13:00") or a 12-hour ("1:00pm") clock value - see get_env_time() for the exact parsing rules.
        # Interpreted as a wall-clock time in settings.TZ (see above), not whatever zone the host/container happens to be running in.
        DEFAULT_SESSION_RESET_TIME                              = ""
        self.SESSION_RESET_TIME                                 = get_env_time("SESSION_RESET_TIME", DEFAULT_SESSION_RESET_TIME)

        # Redis Connection
        DEFAULT_REDIS_HOST                                      = "chatbot-redis"
        DEFAULT_REDIS_PORT                                      = 6379
        DEFAULT_REDIS_USERNAME                                  = ""
        DEFAULT_REDIS_PASSWORD                                  = ""
        DEFAULT_REDIS_DB                                        = 1
        DEFAULT_REDIS_SOCKET_CONNECT_TIMEOUT                    = 5
        DEFAULT_REDIS_SOCKET_TIMEOUT                            = 5
        DEFAULT_REDIS_SOCKET_KEEPALIVE                          = True
        DEFAULT_REDIS_HEALTH_CHECK_INTERVAL                     = 30
        self.REDIS_HOST                                         = os.getenv("REDIS_HOST") or DEFAULT_REDIS_HOST
        self.REDIS_PORT                                         = get_env_int("REDIS_PORT", DEFAULT_REDIS_PORT)
        self.REDIS_USERNAME                                     = os.getenv("REDIS_USERNAME") or DEFAULT_REDIS_USERNAME
        self.REDIS_PASSWORD                                     = os.getenv("REDIS_PASSWORD") or DEFAULT_REDIS_PASSWORD
        self.REDIS_DB                                           = get_env_int("REDIS_DB", DEFAULT_REDIS_DB, minimum=0)
        self.REDIS_SOCKET_CONNECT_TIMEOUT                       = get_env_int("REDIS_SOCKET_CONNECT_TIMEOUT", DEFAULT_REDIS_SOCKET_CONNECT_TIMEOUT)
        self.REDIS_SOCKET_TIMEOUT                               = get_env_int("REDIS_SOCKET_TIMEOUT", DEFAULT_REDIS_SOCKET_TIMEOUT)
        self.REDIS_SOCKET_KEEPALIVE                             = get_env_bool("REDIS_SOCKET_KEEPALIVE", DEFAULT_REDIS_SOCKET_KEEPALIVE)
        self.REDIS_HEALTH_CHECK_INTERVAL                        = get_env_int("REDIS_HEALTH_CHECK_INTERVAL", DEFAULT_REDIS_HEALTH_CHECK_INTERVAL)

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

def get_env_bool(name: str, default: bool) -> bool:
        """
        Reads a boolean environment variable, falling back to default if unset.

        Args:
            name (str):
                Environment variable name.

            default (bool):
                Fallback if unset.

        Returns:
            bool:
                True only if the env var is set and equals "true" (case-insensitive); otherwise default.
        """
        value = os.getenv(name)
        return default if value is None else value.strip().lower() == "true"

def get_env_timezone(name: str, default: str) -> ZoneInfo:
        """
        Reads an IANA timezone name environment variable, falling back to default if unset or unrecognised.

        Args:
            name (str):
                Environment variable name.

            default (str):
                Fallback IANA timezone name if unset or invalid - must itself be a valid zone (e.g. "UTC").

        Returns:
            ZoneInfo:
                The resolved timezone.

        Notes:
            - Falls back to default, silently, on an unrecognised zone name - same "disable/fall back rather than crash" convention as get_env_int()/get_env_bool() in this file.
            - Requires the tzdata PyPI package on a base image with no system IANA timezone database (e.g. python:3.12.4-slim) - zoneinfo falls back to it automatically.
            - Catches ZoneInfoNotFoundError, ValueError, and OSError, not just ZoneInfoNotFoundError - a malformed key (e.g. an absolute path, or a tzdata directory rather than a leaf zone such as "America" instead of "America/New_York") can raise any of the three.
        """
        raw_value = os.getenv(name) or default
        try:
            return ZoneInfo(raw_value)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            return ZoneInfo(default)

# Matches "H:MM"/"HH:MM", optionally followed by "am"/"pm" (case-insensitive, with or without a space).
# The am/pm group is what distinguishes a 24-hour value from a 12-hour one - see get_env_time().
_TIME_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})\s*([AaPp][Mm])?$")

def get_env_time(name: str, default: str = "") -> time | None:
        """
        Reads a wall-clock time environment variable, accepting either a 24-hour or a 12-hour clock value.

        Args:
            name (str):
                Environment variable name.

            default (str, optional):
                Fallback raw value if unset. Defaults to "" (no timed value at all).

        Returns:
            time | None:
                The parsed time, or None if unset/blank/unparsable.

        Notes:
            - No am/pm suffix is always read as a 24-hour hour (0-23) - e.g. "13:00" is 1pm, "09:00" is 9am.
            - An am/pm suffix is read as a 12-hour hour (1-12) and converted the usual way, with one deliberate exception: an hour of 12 - "12:00am" as much as "12:00pm" - is always taken to mean noon, never midnight. Midnight can only be expressed via the 24-hour form ("00:00").
            - Returns a plain time with no tzinfo of its own - the caller is responsible for interpreting it against settings.TZ, not the container's raw local time.
            - Falls back to None (not default re-parsed) on anything unparsable - an invalid value disables the timed feature it configures rather than risking a silently-wrong time.
        """
        raw_value = (os.getenv(name) or default).strip()
        if not raw_value:
            return None

        match = _TIME_PATTERN.match(raw_value)
        if not match:
            return None

        hour, minute, meridiem = int(match.group(1)), int(match.group(2)), match.group(3)
        if not (0 <= minute <= 59):
            return None
        elif meridiem is None:
            if not (0 <= hour <= 23):
                return None
            else:
                return time(hour, minute)
        else:
            if not (1 <= hour <= 12):
                return None
            elif hour == 12:
                # Both "12:00am" and "12:00pm" mean noon here - see this function's own docstring Notes.
                return time(12, minute)
            elif meridiem.lower() == "pm":
                return time(hour + 12, minute)
            else:
                return time(hour, minute)

settings = Settings()
