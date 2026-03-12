"""
Rotating file logger factory.

Creates and returns a named logger with a rotating file handler. The caller
owns the log path and logger name. Parent directories are created if needed.

NOTE: logging.getLogger(name) returns the same instance for the same name
across the entire process. Callers must use unique logger names per agent
(e.g., "gmail-to-trello", "grooming") to avoid handler accumulation across
tests or restarts. See LESSONS.md: Python Logging / Logger Instance Reuse.
"""

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging(
    log_path: str,
    logger_name: str,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
    log_level: int = logging.INFO,
) -> logging.Logger:
    """
    Create and return a named logger with a rotating file handler.

    The caller owns the log path and logger name. This function creates
    parent directories if they don't exist. Does NOT add a StreamHandler;
    the caller may add one if console output is desired.

    If a logger with the given name already has handlers, they are cleared
    before adding the new rotating file handler. This makes the function
    idempotent for the same logger name within a process, though callers
    should prefer unique logger names to avoid cross-contamination.

    Args:
        log_path: Absolute or relative path to the log file.
        logger_name: Name for the logger (e.g. "gmail-to-trello").
        max_bytes: Maximum size of each log file before rotation. Default 5 MB.
        backup_count: Number of backup log files to keep. Default 3.
        log_level: Logging level (e.g. logging.INFO, logging.DEBUG). Default INFO.

    Returns:
        Configured Logger instance with a RotatingFileHandler.
    """
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)

    log = logging.getLogger(logger_name)
    log.setLevel(log_level)

    # Clear existing handlers to prevent accumulation if called multiple times
    # with the same logger name (see LESSONS.md: Logger Instance Reuse).
    if log.handlers:
        for handler in log.handlers[:]:
            handler.close()
            log.removeHandler(handler)

    handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setLevel(log_level)
    formatter = logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    log.addHandler(handler)

    return log
