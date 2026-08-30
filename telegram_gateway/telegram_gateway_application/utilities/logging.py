# =============================================================================
# File        : logging.py
# Description : Configures application logging, including console output, file rotation,
#               retention policy, and log formatting.
#
# Author      : SorinoSSK
# Created On  : 2026-08-29
#
# Notes       :
#   - Centralized logging configuration for the application.
#   - Supports daily log rotation and log retention management.
#   - To be initialised during application entry points on startup.*
# =============================================================================
# I M P O R T   H E A D E R

import os
import logging
from concurrent_log_handler import ConcurrentTimedRotatingFileHandler
from ..config import settings

# =============================================================================

def setup_logging() -> logging.Logger:
    """
    Configures the root logger with console output and a daily/size-based rotating file handler.

    Features:
        - Console logging for real-time visibility.
        - Configurable minimum logging level.
        - Daily log file rotation at midnight.
        - Size-based log rotation when the configured file size limit is reached.
        - Automatic cleanup of expired log files based on the retention period.
        - Prevention of duplicate handlers during application reloads.

    Configuration:
        LOG_DIR:
            Directory where log files are stored.

        LOG_FILE:
            Path to the active log file.

        LOG_LEVEL:
            Minimum severity level to log (e.g. DEBUG, INFO, WARNING, ERROR, CRITICAL).

        LOG_MAX_SIZE_MB:
            Maximum size of a log file in megabyte before rotation occurs.

        LOG_RETENTION_DAYS:
            Number of days to retain historical log files.

    Args:
        None

    Returns:
        logging.Logger:
            The initialized logger instance associated with the current module.

    Raises:
        OSError:
            If the log directory cannot be created or the log file cannot be written.

        PermissionError:
            If the application does not have sufficient permissions to create or write log files.

    Notes:
        Clears existing root logger handlers first to prevent duplicate log entries; call once at startup.
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
