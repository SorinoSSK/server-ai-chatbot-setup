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
    """
    Loads and holds every environment-driven setting the application depends on.

    Each setting falls back to a sensible default when its environment variable is unset or invalid.
    A single instance (settings, below) is constructed once and imported everywhere else as the application's sole source of configuration.
    """

    def __init__(self):
        # Application Common
        self.DATA_DIR = Path("/telegram_gateway/telegram_gateway_application/data")

        # Application Loggings
        DEFAULT_LOG_LEVEL                                       = "INFO"
        DEFAULT_LOG_RETENTION_DAYS                              = 30
        DEFAULT_LOG_MAX_SIZE_MB                                 = 100
        self.LOG_DIR                                            = self.DATA_DIR / "logs"
        self.LOG_FILE                                           = self.LOG_DIR / "telegram_gateway.log"
        self.LOG_LEVEL                                          = os.getenv("LOG_LEVEL") or DEFAULT_LOG_LEVEL
        self.LOG_MAX_SIZE_MB                                    = get_env_int("LOG_MAX_SIZE_MB", DEFAULT_LOG_MAX_SIZE_MB)
        self.LOG_RETENTION_DAYS                                 = get_env_int("LOG_RETENTION_DAYS", DEFAULT_LOG_RETENTION_DAYS)

        # Telegram Bot Connection
        # NOTE: placeholder values - update TELEGRAM_BOT_TOKEN via env/.env before running.
        DEFAULT_TELEGRAM_BOT_TOKEN                              = "REPLACE_WITH_BOT_TOKEN"
        DEFAULT_TELEGRAM_BOT_NAME                               = ""
        DEFAULT_TELEGRAM_API_BASE_URL                           = "https://api.telegram.org"
        DEFAULT_TELEGRAM_POLL_TIMEOUT                           = 30
        DEFAULT_TELEGRAM_CLIENT_TIMEOUT                         = 10
        DEFAULT_TELEGRAM_ALLOWED_CHAT_IDS                       = ""
        DEFAULT_TELEGRAM_ALLOWED_UPDATES                        = "message,callback_query,poll_answer"
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
        DEFAULT_TELEGRAM_MESSAGE_MAX_LENGTH                     = 4096   # sendMessage text hard cap (Telegram Bot API)
        DEFAULT_TELEGRAM_CALLBACK_DATA_MAX_BYTES                = 64     # InlineKeyboardButton.callback_data hard cap, in UTF-8 bytes (Telegram Bot API)
        DEFAULT_TELEGRAM_BUTTONS_MAX_PER_ROW                    = 8      # inline keyboard row limit (Telegram Bot API)
        DEFAULT_TELEGRAM_BUTTONS_MAX_TOTAL                      = 100    # inline keyboard total button limit (Telegram Bot API)
        DEFAULT_TELEGRAM_CALLBACK_TTL_SECONDS                   = 3600   # how long a bot-issued callback_data stays valid/pressable before being treated as stale
        self.TELEGRAM_BOT_TOKEN                                 = os.getenv("TELEGRAM_BOT_TOKEN") or DEFAULT_TELEGRAM_BOT_TOKEN
        self.TELEGRAM_BOT_NAME                                  = os.getenv("TELEGRAM_BOT_NAME") or DEFAULT_TELEGRAM_BOT_NAME
        self.TELEGRAM_API_BASE_URL                              = os.getenv("TELEGRAM_API_BASE_URL") or DEFAULT_TELEGRAM_API_BASE_URL
        self.TELEGRAM_POLL_TIMEOUT                              = get_env_int("TELEGRAM_POLL_TIMEOUT", DEFAULT_TELEGRAM_POLL_TIMEOUT)
        self.TELEGRAM_CLIENT_TIMEOUT                            = get_env_int("TELEGRAM_CLIENT_TIMEOUT", DEFAULT_TELEGRAM_CLIENT_TIMEOUT)
        self.TELEGRAM_UNAUTHORISED_CACHE_SIZE                   = get_env_int("TELEGRAM_UNAUTHORISED_CACHE_SIZE", DEFAULT_TELEGRAM_UNAUTHORISED_CACHE_SIZE)
        self.TELEGRAM_UNAUTHORISED_EVICTION_WINDOW_PERCENT      = get_env_int("TELEGRAM_UNAUTHORISED_EVICTION_WINDOW_PERCENT", DEFAULT_TELEGRAM_UNAUTHORISED_EVICTION_WINDOW_PERCENT)
        self.TELEGRAM_UNAUTHORISED_ACCESS_COUNT_CAP             = get_env_int("TELEGRAM_UNAUTHORISED_ACCESS_COUNT_CAP", DEFAULT_TELEGRAM_UNAUTHORISED_ACCESS_COUNT_CAP)
        self.TELEGRAM_UPDATE_MAX_ATTEMPTS                       = get_env_int("TELEGRAM_UPDATE_MAX_ATTEMPTS", DEFAULT_TELEGRAM_UPDATE_MAX_ATTEMPTS)
        self.TELEGRAM_TYPING_INTERVAL_MIN                       = get_env_int("TELEGRAM_TYPING_INTERVAL_MIN", DEFAULT_TELEGRAM_TYPING_INTERVAL_MIN)
        self.TELEGRAM_TYPING_INTERVAL_MAX                       = get_env_int("TELEGRAM_TYPING_INTERVAL_MAX", DEFAULT_TELEGRAM_TYPING_INTERVAL_MAX)
        self.TELEGRAM_TYPING_MAX_PINGS_MIN                      = get_env_int("TELEGRAM_TYPING_MAX_PINGS_MIN", DEFAULT_TELEGRAM_TYPING_MAX_PINGS_MIN)
        self.TELEGRAM_TYPING_MAX_PINGS_MAX                      = get_env_int("TELEGRAM_TYPING_MAX_PINGS_MAX", DEFAULT_TELEGRAM_TYPING_MAX_PINGS_MAX)
        self.TELEGRAM_SEND_MAX_ATTEMPTS                         = get_env_int("TELEGRAM_SEND_MAX_ATTEMPTS", DEFAULT_TELEGRAM_SEND_MAX_ATTEMPTS)
        self.TELEGRAM_SEND_RETRY_DELAY                          = get_env_int("TELEGRAM_SEND_RETRY_DELAY", DEFAULT_TELEGRAM_SEND_RETRY_DELAY)
        self.TELEGRAM_CAPTION_MAX_LENGTH                        = get_env_int("TELEGRAM_CAPTION_MAX_LENGTH", DEFAULT_TELEGRAM_CAPTION_MAX_LENGTH)
        self.TELEGRAM_MESSAGE_MAX_LENGTH                        = get_env_int("TELEGRAM_MESSAGE_MAX_LENGTH", DEFAULT_TELEGRAM_MESSAGE_MAX_LENGTH)
        self.TELEGRAM_CALLBACK_DATA_MAX_BYTES                   = get_env_int("TELEGRAM_CALLBACK_DATA_MAX_BYTES", DEFAULT_TELEGRAM_CALLBACK_DATA_MAX_BYTES)
        self.TELEGRAM_BUTTONS_MAX_PER_ROW                       = get_env_int("TELEGRAM_BUTTONS_MAX_PER_ROW", DEFAULT_TELEGRAM_BUTTONS_MAX_PER_ROW)
        self.TELEGRAM_BUTTONS_MAX_TOTAL                         = get_env_int("TELEGRAM_BUTTONS_MAX_TOTAL", DEFAULT_TELEGRAM_BUTTONS_MAX_TOTAL)
        self.TELEGRAM_CALLBACK_TTL_SECONDS                      = get_env_int("TELEGRAM_CALLBACK_TTL_SECONDS", DEFAULT_TELEGRAM_CALLBACK_TTL_SECONDS)

        # Draft Handling (media received without an instruction yet - see utils_telegram/utilities/image_draft_handler.py)
        # The draft is kept alive by a repeating "keep-alive" cycle: each cycle, a notice (with a "give me a little while more" button) is sent partway through; if the user doesn't press it (or finalise the draft) before the cycle ends, the draft expires.
        # Pressing it grants one more cycle.
        # The final cycle sends a button-less last notice instead, since DRAFT_CLOSE_SECONDS is a hard cap.
        DEFAULT_DRAFT_CLOSE_SECONDS                             = 3300   # 55 min hard cap across all cycles (Telegram's file link is only guaranteed for 1 hour)
        DEFAULT_DRAFT_CYCLE_SECONDS                             = 300    # length of one keep-alive cycle (5 min)
        DEFAULT_DRAFT_CYCLE_NOTICE_LEAD_SECONDS                 = 180    # notice sent this long before each cycle ends (3 min - i.e. 2 min into a 5 min cycle)
        DEFAULT_DRAFT_TYPING_LEAD_SECONDS                       = 60     # "typing..." runs for the 1 min immediately before each cycle's notice/close
        DEFAULT_DRAFT_MAPPING_TTL_SECONDS                       = 3600   # Redis-side backstop, slightly beyond the hard cap
        DEFAULT_MEDIA_GROUP_DEDUPE_SECONDS                      = 86400  # window for deduping repeated album-item replies sharing one media_group_id (24h - covers items delayed by a client-side reconnect, not just burst arrival)
        self.DRAFT_CLOSE_SECONDS                                = get_env_int("DRAFT_CLOSE_SECONDS", DEFAULT_DRAFT_CLOSE_SECONDS)
        self.DRAFT_CYCLE_SECONDS                                = get_env_int("DRAFT_CYCLE_SECONDS", DEFAULT_DRAFT_CYCLE_SECONDS)
        self.DRAFT_CYCLE_NOTICE_LEAD_SECONDS                    = get_env_int("DRAFT_CYCLE_NOTICE_LEAD_SECONDS", DEFAULT_DRAFT_CYCLE_NOTICE_LEAD_SECONDS)
        self.DRAFT_TYPING_LEAD_SECONDS                          = get_env_int("DRAFT_TYPING_LEAD_SECONDS", DEFAULT_DRAFT_TYPING_LEAD_SECONDS)
        self.DRAFT_MAPPING_TTL_SECONDS                          = get_env_int("DRAFT_MAPPING_TTL_SECONDS", DEFAULT_DRAFT_MAPPING_TTL_SECONDS)
        self.MEDIA_GROUP_DEDUPE_SECONDS                         = get_env_int("MEDIA_GROUP_DEDUPE_SECONDS", DEFAULT_MEDIA_GROUP_DEDUPE_SECONDS)

        # Poll Handling (poll -> poll_answer correlation - see utils_telegram/utilities/poll_response_handler.py)
        # A poll is always sent non-anonymous (TELEGRAM_POLL_ANONYMOUS), so an answer can be attributed to its responder.
        # Two phases per poll, governed by one in-memory timer:
        #   - AWAITING FIRST ANSWER (POLL_TIMEOUT_SECONDS): closes with a chat message if nobody answers in time.
        #     No queue push.
        #   - DEBOUNCING (POLL_DEBOUNCE_INITIAL_SECONDS, shortened to POLL_DEBOUNCE_SUBSEQUENT_SECONDS on every further answer): once answered, compiles and pushes the latest answer once things go quiet - capped overall by POLL_GLOBAL_CAP_SECONDS from poll creation, regardless of how many times debouncing resets.
        DEFAULT_TELEGRAM_POLL_ANONYMOUS                         = False
        DEFAULT_POLL_TIMEOUT_SECONDS                            = 300  # 5 min hard cap while awaiting a first answer
        DEFAULT_POLL_DEBOUNCE_INITIAL_SECONDS                   = 120  # 2 min debounce after the first answer
        DEFAULT_POLL_DEBOUNCE_SUBSEQUENT_SECONDS                = 60   # 1 min debounce after every answer thereafter
        DEFAULT_POLL_GLOBAL_CAP_SECONDS                         = 480  # 8 min hard ceiling from poll creation (Telegram's own open_period/close_date maxes at 600s)
        DEFAULT_POLL_MAPPING_TTL_SECONDS                        = 600  # Redis-side backstop, slightly beyond the hard cap
        self.TELEGRAM_POLL_ANONYMOUS                            = get_env_bool("TELEGRAM_POLL_ANONYMOUS", DEFAULT_TELEGRAM_POLL_ANONYMOUS)
        self.POLL_TIMEOUT_SECONDS                               = get_env_int("POLL_TIMEOUT_SECONDS", DEFAULT_POLL_TIMEOUT_SECONDS)
        self.POLL_DEBOUNCE_INITIAL_SECONDS                      = get_env_int("POLL_DEBOUNCE_INITIAL_SECONDS", DEFAULT_POLL_DEBOUNCE_INITIAL_SECONDS)
        self.POLL_DEBOUNCE_SUBSEQUENT_SECONDS                   = get_env_int("POLL_DEBOUNCE_SUBSEQUENT_SECONDS", DEFAULT_POLL_DEBOUNCE_SUBSEQUENT_SECONDS)
        self.POLL_GLOBAL_CAP_SECONDS                            = get_env_int("POLL_GLOBAL_CAP_SECONDS", DEFAULT_POLL_GLOBAL_CAP_SECONDS)
        self.POLL_MAPPING_TTL_SECONDS                           = get_env_int("POLL_MAPPING_TTL_SECONDS", DEFAULT_POLL_MAPPING_TTL_SECONDS)

        # Error Handling (Tier 1/Tier 2 delivery failures - see utils_queue/error_handling.py)
        # Tier 2's "unreachable" alert only fires once this many consecutive connection-level send failures (across all sends) have accumulated - a single blip is expected noise, not a systemic signal.
        # A 401 ("unauthorized") bypasses this and fires immediately regardless.
        DEFAULT_GATEWAY_ALERT_FAILURE_THRESHOLD                 = 5
        self.GATEWAY_ALERT_FAILURE_THRESHOLD                    = get_env_int("GATEWAY_ALERT_FAILURE_THRESHOLD", DEFAULT_GATEWAY_ALERT_FAILURE_THRESHOLD)

        # Whitelist of chat IDs allowed to interact with the bot. Not using
        self.TELEGRAM_ALLOWED_CHAT_IDS = {
            int(chat_id.strip())
            for chat_id in (os.getenv("TELEGRAM_ALLOWED_CHAT_IDS") or DEFAULT_TELEGRAM_ALLOWED_CHAT_IDS).split(",")
            if chat_id.strip().lstrip("-").isdigit()
        }

        # Session Reset (see utils_session/session_reset_handler.py)
        # Whitelist of chat IDs allowed to trigger a session_reset. Same pattern as TELEGRAM_ALLOWED_CHAT_IDS above.
        DEFAULT_SESSION_RESET_ALLOWED_CHAT_IDS = ""
        self.SESSION_RESET_ALLOWED_CHAT_IDS = {
            int(chat_id.strip())
            for chat_id in (os.getenv("SESSION_RESET_ALLOWED_CHAT_IDS") or DEFAULT_SESSION_RESET_ALLOWED_CHAT_IDS).split(",")
            if chat_id.strip().lstrip("-").isdigit()
        }
        # Ceiling on how long a deferred session_reset may wait for its chat's open task_id(s) to
        # naturally complete before being forced through regardless (treated as abandoned for reset
        # purposes only) - backstops a completed/error that never arrives (a poll that timed out with
        # nothing pushed, an orphaned/expired task mapping, or any other stuck task) - see TODO.md §8.
        DEFAULT_PENDING_RESET_MAX_WAIT_SECONDS                  = 3600   # 1h - comfortably above POLL_GLOBAL_CAP_SECONDS/DRAFT_CLOSE_SECONDS, so a still-genuinely-in-flight poll/draft is never mistaken for a stuck one
        DEFAULT_PENDING_RESET_SWEEP_INTERVAL_SECONDS            = 60     # how often the ceiling above is checked
        self.PENDING_RESET_MAX_WAIT_SECONDS                     = get_env_int("PENDING_RESET_MAX_WAIT_SECONDS", DEFAULT_PENDING_RESET_MAX_WAIT_SECONDS)
        self.PENDING_RESET_SWEEP_INTERVAL_SECONDS               = get_env_int("PENDING_RESET_SWEEP_INTERVAL_SECONDS", DEFAULT_PENDING_RESET_SWEEP_INTERVAL_SECONDS)

        # Event types Telegram is asked to deliver - restricts what getUpdates returns server-side (does not filter by chat).
        self.TELEGRAM_ALLOWED_UPDATES = [
            update_type.strip()
            for update_type in (os.getenv("TELEGRAM_ALLOWED_UPDATES") or DEFAULT_TELEGRAM_ALLOWED_UPDATES).split(",")
            if update_type.strip()
        ]

        # Queue Connection
        DEFAULT_Q_HOST                                          = "chatbot-rabbitmq"
        DEFAULT_Q_USER                                          = ""
        DEFAULT_Q_PASSWORD                                      = ""
        DEFAULT_Q_PORT                                          = 5672
        DEFAULT_Q_VHOST                                         = "chatbot_vhost"
        DEFAULT_Q_CHANNEL_IN                                    = "telegram_gateway_inbound_queue"
        DEFAULT_Q_CHANNEL_OUT                                   = "telegram_gateway_outbound_queue"
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

        # Redis Connection
        DEFAULT_REDIS_HOST                                      = "chatbot-redis"
        DEFAULT_REDIS_PORT                                      = 6379
        DEFAULT_REDIS_USERNAME                                  = ""
        DEFAULT_REDIS_PASSWORD                                  = ""
        DEFAULT_REDIS_DB                                        = 0
        DEFAULT_REDIS_SOCKET_CONNECT_TIMEOUT                    = 5
        DEFAULT_REDIS_SOCKET_TIMEOUT                            = 5
        DEFAULT_REDIS_SOCKET_KEEPALIVE                          = True
        DEFAULT_REDIS_HEALTH_CHECK_INTERVAL                     = 30
        DEFAULT_REDIS_TASK_RETRY_DELAY                          = 1
        DEFAULT_REDIS_TASK_MAX_ATTEMPTS                         = 5
        DEFAULT_REDIS_TASK_MAPPING_TTL_SECONDS                  = 86400
        self.REDIS_HOST                                         = os.getenv("REDIS_HOST") or DEFAULT_REDIS_HOST
        self.REDIS_PORT                                         = get_env_int("REDIS_PORT", DEFAULT_REDIS_PORT)
        self.REDIS_USERNAME                                     = os.getenv("REDIS_USERNAME") or DEFAULT_REDIS_USERNAME
        self.REDIS_PASSWORD                                     = os.getenv("REDIS_PASSWORD") or DEFAULT_REDIS_PASSWORD
        self.REDIS_DB                                           = get_env_int("REDIS_DB", DEFAULT_REDIS_DB, minimum=0)
        self.REDIS_SOCKET_CONNECT_TIMEOUT                       = get_env_int("REDIS_SOCKET_CONNECT_TIMEOUT", DEFAULT_REDIS_SOCKET_CONNECT_TIMEOUT)
        self.REDIS_SOCKET_TIMEOUT                               = get_env_int("REDIS_SOCKET_TIMEOUT", DEFAULT_REDIS_SOCKET_TIMEOUT)
        self.REDIS_SOCKET_KEEPALIVE                             = get_env_bool("REDIS_SOCKET_KEEPALIVE", DEFAULT_REDIS_SOCKET_KEEPALIVE)
        self.REDIS_HEALTH_CHECK_INTERVAL                        = get_env_int("REDIS_HEALTH_CHECK_INTERVAL", DEFAULT_REDIS_HEALTH_CHECK_INTERVAL)
        self.REDIS_TASK_RETRY_DELAY                             = get_env_int("REDIS_TASK_RETRY_DELAY", DEFAULT_REDIS_TASK_RETRY_DELAY)
        self.REDIS_TASK_MAX_ATTEMPTS                            = get_env_int("REDIS_TASK_MAX_ATTEMPTS", DEFAULT_REDIS_TASK_MAX_ATTEMPTS)
        self.REDIS_TASK_MAPPING_TTL_SECONDS                     = get_env_int("REDIS_TASK_MAPPING_TTL_SECONDS", DEFAULT_REDIS_TASK_MAPPING_TTL_SECONDS)

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
