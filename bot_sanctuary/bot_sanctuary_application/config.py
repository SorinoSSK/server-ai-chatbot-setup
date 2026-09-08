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
        DEFAULT_LLM_TYPE                                        = ""
        DEFAULT_LLM_OAUTH_TOKEN                                 = ""
        self.LLM_TYPE                                           = os.getenv("LLM_TYPE") or DEFAULT_LLM_TYPE
        self.LLM_OAUTH_TOKEN                                    = os.getenv("LLM_OAUTH_TOKEN") or DEFAULT_LLM_OAUTH_TOKEN

        # Bot Identity - shared with telegram_gateway, same env var name/convention as
        # telegram_gateway/config.py's own TELEGRAM_BOT_NAME (both fed from the same root
        # config.ini CHATBOT_NAME value) - used here as the display name on the SMTP From
        # header (see utils_smtp/smtp_handler.py), so the mailer identifies as the same
        # persona the user already talks to on Telegram, rather than a second, separate name.
        DEFAULT_TELEGRAM_BOT_NAME                               = ""
        self.TELEGRAM_BOT_NAME                                  = os.getenv("TELEGRAM_BOT_NAME") or DEFAULT_TELEGRAM_BOT_NAME

        # Queue Connection (see bot_sanctuary/CODE_TODO.md §3)
        # Q_CHANNEL_IN/Q_CHANNEL_OUT are named from this application's own point of view, same convention
        # as telegram_gateway/config.py - IN is what this application consumes, OUT is what it publishes
        # to. Since the two applications talk to each other, that makes this application's IN telegram_gateway's
        # OUT, and vice versa - the literal queue name strings below are shared, durable RabbitMQ queues
        # that telegram_gateway itself already declares (see telegram_gateway/config.py's own Q_CHANNEL_IN/OUT).
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

        # SMTP / Mailer (see bot_sanctuary/CODE_TODO.md §4 - Tier 2 gateway_alert alerting)
        # SMTP_FROM_EMAIL/SMTP_USERNAME/SMTP_PASSWORD are never logged in full - see
        # utils_smtp/smtp_handler.py's masking helper.
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

        # gateway_alert notification throttle (see utils_queue/message_handler.py::_handle_gateway_alert(),
        # utils_redis/database.py) - a gateway_alert notification email fires at most once per this many
        # seconds (default 24h), no matter how many gateway_alert events arrive in between. Every
        # occurrence is still counted in Redis regardless of whether an email is actually sent for it.
        # Also used as a fixed (non-renewed) Redis TTL on both the occurrence counter and the notification
        # cooldown - see utils_redis/database.py's module Notes for why it is deliberately NOT refreshed on
        # every occurrence (a sliding/renewed TTL could never expire if occurrences never stopped arriving,
        # which would make the fallback reset impossible).
        DEFAULT_GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS           = 86400
        self.GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS              = get_env_int("GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS", DEFAULT_GATEWAY_ALERT_NOTIFY_COOLDOWN_SECONDS)

        # Redis Connection (see bot_sanctuary/CODE_TODO.md §4) - a separate Redis ACL user/credentials
        # from telegram_gateway's own REDIS_USERNAME/PASSWORD (same shared chatbot-redis container,
        # deliberately not the same login - see compose.dev.yml's redis service, which scopes this
        # application's user to only the "bot_sanctuary:*" key pattern). REDIS_DB also defaults to a
        # different logical database (1, vs telegram_gateway's 0) as a second, belt-and-braces layer of
        # separation on top of the ACL key-pattern restriction.
        # Deliberately NOT a hard startup dependency, unlike RabbitMQ - Redis here only backs a durability
        # nicety on an already-optional secondary feature (SMTP alerting); connects lazily on first use,
        # fails open (see utils_redis/database.py) rather than blocking or crashing application startup.
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
