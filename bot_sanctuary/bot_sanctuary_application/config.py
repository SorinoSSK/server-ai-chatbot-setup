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
#   - Minimal starting shape - only the settings needed for logging, the LLM provider identity/credential, and RabbitMQ connectivity, so far.
#   - Session registry / agent-call settings are added as their owning modules are built (see bot_sanctuary/CODE_TODO.md).
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
        # More than one provider's credentials can be configured at once (see the per-provider settings
        # below) - there is no longer a single "current" provider/credential pair. All four LLM_TYPE values
        # ("claude", "codex", "deepseek", "qwen") are wired programmatically (utils_agents/claude_interface.py,
        # codex_interface.py, deepseek_interface.py, qwen_interface.py), each dispatched by an explicit
        # llm_type argument (utils_agents/agent_interface.py::query_llm()), not a single global setting.
        #
        # LLM_CHAT_TYPE selects which provider the Chat Call (utils_calls/chat_call.py - entry/default,
        # conversation & routing only, persona "Rukia") uses. Also the fallback for every other named
        # Call's own LLM_<CALL>_TYPE below, when that Call's own setting is left unset - so a deployment
        # only needs to configure LLM_CHAT_TYPE and every Call defaults to using the same provider, unless
        # deliberately overridden per Call.
        #
        # LLM_ARCHITECT_TYPE/LLM_CODER_TYPE/LLM_REVIEW_TYPE/LLM_DOCUMENTATION_TYPE - one setting per
        # remaining named Call (see bot_sanctuary/CODE_TODO.md §5), each falling back to LLM_CHAT_TYPE if
        # unset. This is what "on hold" per-Call provider routing (previously deferred, see §2/§5's history)
        # actually looks like now that the Call pipeline itself has real scaffolding to attach it to -
        # each Call can be pointed at a different provider (e.g. Coder=claude, Review=qwen), or left to
        # inherit LLM_CHAT_TYPE by leaving its own setting unset.
        #
        # LLM_<PROVIDER>_ACCESS_TYPE/LLM_<PROVIDER>_TOKEN - one credential pair per provider, since the
        # startup smoke test (utils_agents/agent_interface.py::test_llm_tokens()) now tests every provider
        # that has a token configured, not just one. "OAUTH" (a Claude Code OAuth token/Codex CLI login
        # session) only means anything for "claude"/"codex" - "deepseek"/"qwen" are API-key-only (DeepSeek
        # has no OAuth mechanism at all; Qwen's free OAuth login tier was discontinued 2026-04-15), so their
        # own ACCESS_TYPE defaults straight to "API" rather than requiring it be set explicitly.
        DEFAULT_LLM_CHAT_TYPE                                   = ""
        self.LLM_CHAT_TYPE                                      = os.getenv("LLM_CHAT_TYPE") or DEFAULT_LLM_CHAT_TYPE

        self.LLM_ARCHITECT_TYPE                                 = os.getenv("LLM_ARCHITECT_TYPE") or self.LLM_CHAT_TYPE
        self.LLM_CODER_TYPE                                     = os.getenv("LLM_CODER_TYPE") or self.LLM_CHAT_TYPE
        self.LLM_REVIEW_TYPE                                    = os.getenv("LLM_REVIEW_TYPE") or self.LLM_CHAT_TYPE
        self.LLM_DOCUMENTATION_TYPE                             = os.getenv("LLM_DOCUMENTATION_TYPE") or self.LLM_CHAT_TYPE

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

        # Bot Identity - persona name shared with telegram_gateway, used as the SMTP From display name.
        DEFAULT_TELEGRAM_BOT_NAME                               = ""
        self.TELEGRAM_BOT_NAME                                  = os.getenv("TELEGRAM_BOT_NAME") or DEFAULT_TELEGRAM_BOT_NAME

        # Queue Connection - Q_CHANNEL_IN/Q_CHANNEL_OUT are named from this application's own point of view.
        DEFAULT_Q_HOST                                          = "chatbot-rabbitmq"
        DEFAULT_Q_USER                                          = ""
        DEFAULT_Q_PASSWORD                                      = ""
        DEFAULT_Q_PORT                                          = 5672
        DEFAULT_Q_VHOST                                         = "chatbot_vhost"
        DEFAULT_Q_CHANNEL_IN                                    = "telegram_gateway_outbound_queue"  # telegram_gateway's Q_CHANNEL_OUT - what this application consumes
        DEFAULT_Q_CHANNEL_OUT                                   = "telegram_gateway_inbound_queue"   # telegram_gateway's Q_CHANNEL_IN - what this application publishes to
        DEFAULT_Q_PUSH_MAX_ATTEMPTS                             = 30
        DEFAULT_Q_PUSH_RETRY_DELAY                              = 1
        DEFAULT_Q_HEARTBEAT                                     = 600
        DEFAULT_Q_BLOCKED_CONNECTION_TIMEOUT                    = 300
        DEFAULT_Q_CONSUME_RETRY_DELAY                           = 1
        DEFAULT_Q_CONSUME_MAX_ATTEMPTS                          = 5
        DEFAULT_Q_CONNECT_RETRY_DELAY_SECONDS                   = 5      # delay between startup connection attempts while RabbitMQ is not yet reachable (see utils_queue/queue.py::initialise_rabbitmq_connection())
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

        # SMTP / Mailer - used for Tier 2 gateway_alert alerting. Credentials are never logged in full.
        DEFAULT_SMTP_ENABLE_MAILER                              = False    # inert (send_mail() is a no-op) until explicitly turned on
        DEFAULT_SMTP_FORCE_SSL                                  = False    # True: connect via implicit TLS (smtplib.SMTP_SSL, typically port 465) instead of STARTTLS
        DEFAULT_SMTP_AUTH_TYPE                                  = "LOGIN"  # "NONE" (case-insensitive) skips authentication entirely; any other value authenticates via SMTP_USERNAME/SMTP_PASSWORD - smtplib.login() negotiates the actual SASL mechanism itself, so no further distinction between mechanism names is made here
        DEFAULT_SMTP_SKIP_TLS                                   = False    # True: no TLS at all (plain SMTP, typically port 25) - only appropriate for a trusted internal relay; ignored if SMTP_FORCE_SSL is also True
        DEFAULT_SMTP_HOST                                       = ""
        DEFAULT_SMTP_PORT                                       = 587
        DEFAULT_SMTP_FROM_EMAIL                                 = ""
        DEFAULT_SMTP_TO_EMAIL                                   = ""       # default alert recipient - lets test_smtp_configuration()/future gateway_alert wiring resolve a recipient from config rather than requiring one be passed manually every time
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

        # gateway_alert notification throttle - minimum seconds between notification emails, also used as the fixed Redis TTL fallback (see utils_redis/database.py).
        DEFAULT_GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS           = 86400
        self.GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS              = get_env_int("GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS", DEFAULT_GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS)

        # Redis per-call retry - bounded retry applied to every individual Redis call (see utils_redis/database.py).
        DEFAULT_REDIS_TASK_MAX_ATTEMPTS                         = 5
        DEFAULT_REDIS_TASK_RETRY_DELAY                          = 1
        self.REDIS_TASK_MAX_ATTEMPTS                            = get_env_int("REDIS_TASK_MAX_ATTEMPTS", DEFAULT_REDIS_TASK_MAX_ATTEMPTS)
        self.REDIS_TASK_RETRY_DELAY                             = get_env_int("REDIS_TASK_RETRY_DELAY", DEFAULT_REDIS_TASK_RETRY_DELAY)

        # Session routing - bounds each SessionWorker's own inbox (see utils_session/session_worker.py).
        DEFAULT_SESSION_INBOX_MAX_SIZE                          = 100
        self.SESSION_INBOX_MAX_SIZE                             = get_env_int("SESSION_INBOX_MAX_SIZE", DEFAULT_SESSION_INBOX_MAX_SIZE)

        # Session on-disk directory - one subfolder per session_id, itself split into fresh "generation"
        # subfolders (see utils_session/session_worker.py). Intended as a stable Claude Agent SDK cwd anchor
        # for a future session-resume feature (see bot_sanctuary/CODE_TODO.md §5) - not yet wired into any
        # actual LLM call. No conversation history is kept here today, per explicit instruction ("I do not
        # intend to keep sessions for now") - this is lifecycle scaffolding only.
        self.SESSION_DIR                                        = self.DATA_DIR / "sessions"

        # Bounds how long terminate_application() waits for each SessionWorker to finish on shutdown - 0 waits indefinitely.
        DEFAULT_SESSION_SHUTDOWN_TIMEOUT_SECONDS                = 30
        self.SESSION_SHUTDOWN_TIMEOUT_SECONDS                   = get_env_int("SESSION_SHUTDOWN_TIMEOUT_SECONDS", DEFAULT_SESSION_SHUTDOWN_TIMEOUT_SECONDS, minimum=0)

        # Redis Connection - a separate Redis ACL user/credentials from telegram_gateway's own, sharing the same container. Not a hard startup dependency; connects lazily and fails open (see utils_redis/database.py).
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

# import settings for singleton
settings = Settings()
