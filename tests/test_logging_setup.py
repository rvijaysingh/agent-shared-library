"""Tests for infra/logging_setup.py.

IMPORTANT: Each test uses a unique logger name to avoid the Python logging
global state problem (getLogger returns the same instance for the same name).
See LESSONS.md: Python Logging / Logger Instance Reuse.

Five categories:
1. Happy path — logger created, file written, correct name
2. Boundary/edge cases — parent dir creation, custom max_bytes
3. Graceful degradation — calling setup_logging twice with same name (idempotent)
4. Bad input/validation — unique names don't share handlers
5. Idempotency/state — re-calling setup_logging clears old handlers
"""

import logging
import os
import pytest

from agent_shared.infra.logging_setup import setup_logging


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

def test_setup_logging_returns_logger_with_correct_name(tmp_path):
    """setup_logging returns a Logger instance with the given name."""
    log_file = tmp_path / "test.log"
    logger = setup_logging(str(log_file), "test_name_happy")

    assert isinstance(logger, logging.Logger)
    assert logger.name == "test_name_happy"


def test_setup_logging_creates_log_file(tmp_path):
    """The log file is created on disk when the first message is written."""
    log_file = tmp_path / "app.log"
    logger = setup_logging(str(log_file), "test_creates_file")

    logger.info("hello")
    # Flush handlers
    for h in logger.handlers:
        h.flush()

    assert log_file.exists()


def test_setup_logging_writes_messages_to_file(tmp_path):
    """Messages logged at or above the configured level appear in the file."""
    log_file = tmp_path / "app.log"
    logger = setup_logging(str(log_file), "test_writes_messages")

    logger.info("important message")
    logger.debug("debug message")  # should not appear at INFO level
    for h in logger.handlers:
        h.flush()

    content = log_file.read_text(encoding="utf-8")
    assert "important message" in content
    assert "debug message" not in content


def test_setup_logging_default_level_is_info(tmp_path):
    """Default log level is INFO."""
    log_file = tmp_path / "app.log"
    logger = setup_logging(str(log_file), "test_default_level")

    assert logger.level == logging.INFO


# ---------------------------------------------------------------------------
# 2. Boundary / edge cases
# ---------------------------------------------------------------------------

def test_setup_logging_creates_parent_directories(tmp_path):
    """Parent directories of the log path are created automatically."""
    log_file = tmp_path / "subdir" / "nested" / "app.log"
    logger = setup_logging(str(log_file), "test_parent_dirs")

    logger.info("test")
    for h in logger.handlers:
        h.flush()

    assert log_file.exists()


def test_setup_logging_custom_log_level(tmp_path):
    """Custom log level is applied to both the logger and the handler."""
    log_file = tmp_path / "debug.log"
    logger = setup_logging(str(log_file), "test_custom_level", log_level=logging.DEBUG)

    assert logger.level == logging.DEBUG

    logger.debug("debug line")
    for h in logger.handlers:
        h.flush()

    content = log_file.read_text(encoding="utf-8")
    assert "debug line" in content


def test_setup_logging_rotating_handler_max_bytes(tmp_path):
    """RotatingFileHandler is configured with the given max_bytes."""
    log_file = tmp_path / "small.log"
    logger = setup_logging(str(log_file), "test_max_bytes", max_bytes=1024)

    from logging.handlers import RotatingFileHandler
    handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(handlers) == 1
    assert handlers[0].maxBytes == 1024


# ---------------------------------------------------------------------------
# 3. Graceful degradation
# ---------------------------------------------------------------------------

def test_setup_logging_idempotent_same_name_clears_old_handlers(tmp_path):
    """Calling setup_logging twice with the same name doesn't accumulate handlers."""
    log_file1 = tmp_path / "first.log"
    log_file2 = tmp_path / "second.log"

    # Set up logger twice with same name
    setup_logging(str(log_file1), "test_idempotent_same")
    logger = setup_logging(str(log_file2), "test_idempotent_same")

    # Should have exactly 1 handler (the second call replaced the first)
    assert len(logger.handlers) == 1


# ---------------------------------------------------------------------------
# 4. Bad input / validation
# ---------------------------------------------------------------------------

def test_setup_logging_unique_names_dont_share_handlers(tmp_path):
    """Two loggers with different names have independent handlers."""
    log_file_a = tmp_path / "a.log"
    log_file_b = tmp_path / "b.log"

    logger_a = setup_logging(str(log_file_a), "test_unique_a")
    logger_b = setup_logging(str(log_file_b), "test_unique_b")

    logger_a.info("message for A")
    logger_b.info("message for B")
    for h in logger_a.handlers + logger_b.handlers:
        h.flush()

    content_a = log_file_a.read_text(encoding="utf-8")
    content_b = log_file_b.read_text(encoding="utf-8")

    assert "message for A" in content_a
    assert "message for B" not in content_a
    assert "message for B" in content_b
    assert "message for A" not in content_b


# ---------------------------------------------------------------------------
# 5. Idempotency / state
# ---------------------------------------------------------------------------

def test_setup_logging_second_call_writes_to_new_file(tmp_path):
    """After re-calling setup_logging with same name, messages go to the new file."""
    log_file1 = tmp_path / "old.log"
    log_file2 = tmp_path / "new.log"

    setup_logging(str(log_file1), "test_reroute")
    logger = setup_logging(str(log_file2), "test_reroute")

    logger.info("goes to new file")
    for h in logger.handlers:
        h.flush()

    content_new = log_file2.read_text(encoding="utf-8")
    assert "goes to new file" in content_new

    # Old file may have been created but the new message should NOT be in it
    if log_file1.exists():
        content_old = log_file1.read_text(encoding="utf-8")
        assert "goes to new file" not in content_old
