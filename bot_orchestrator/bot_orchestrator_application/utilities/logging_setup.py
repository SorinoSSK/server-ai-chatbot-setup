# =============================================================================
# File        : logging_setup.py
# Description : Configures application logging, including console output, file rotation, retention policy, and log formatting.
# Author      : SorinoSSK
# Created On  : 2026-09-04
#
# Features    :
#   - Console and daily/size-based rotating file logging, with retention management.
#
# Notes       :
#   - Centralised logging configuration for the application.
#   - Intended to be initialised once during application entry points on startup.
# =============================================================================
# I M P O R T   H E A D E R

import logging
from concurrent_log_handler import ConcurrentTimedRotatingFileHandler
from ..config import settings

# =============================================================================

def setup_logging() -> logging.Logger:
    """
    Configures the root logger with console output and a daily/size-based rotating file handler.

    Args:
        None

    Returns:
        logging.Logger:
            The configured root logger.

    Notes:
        - Clears existing handlers first to avoid duplicates; call once at startup.
    """
    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    log_max_size = settings.LOG_MAX_SIZE_MB * 1024 * 1024

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Prevent duplicate handlers during reload
    if root_logger.handlers:
        root_logger.handlers.clear()

    # Console output
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Daily rotation
    file_handler = ConcurrentTimedRotatingFileHandler(
        filename=str(settings.LOG_FILE),
        when="midnight",
        interval=1,
        backupCount=settings.LOG_RETENTION_DAYS,
        maxBytes=log_max_size,
        encoding="utf-8"
    )

    file_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    logger = logging.getLogger(__name__)
    logger.info("Logging initialized")

    return logger
