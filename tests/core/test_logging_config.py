"""
Tests for structured logging configuration.

Tests JSON formatting, context variables, and log level management.
"""

import json
import logging
from io import StringIO

import pytest

from src.core.logging_config import (
    CustomJsonFormatter,
    clear_request_context,
    configure_logging,
    correlation_id_var,
    get_current_log_level,
    request_id_var,
    set_log_level,
    set_request_context,
    user_id_var,
)


@pytest.fixture(autouse=True)
def reset_logging():
    """Reset logging configuration after each test."""
    yield
    # Clear context variables
    clear_request_context()
    # Reset to default logging
    logging.root.handlers = []
    configure_logging()


@pytest.fixture
def json_log_handler():
    """Create a handler that captures JSON logs."""
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    formatter = CustomJsonFormatter()
    handler.setFormatter(formatter)
    return handler, stream


class TestCustomJsonFormatter:
    """Tests for CustomJsonFormatter."""

    def test_json_format_basic(self, json_log_handler):
        """Test basic JSON log formatting."""
        handler, stream = json_log_handler
        logger = logging.getLogger("test_logger")
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)

        logger.info("Test message")

        stream.seek(0)
        log_line = stream.read().strip()
        log_data = json.loads(log_line)

        assert log_data["message"] == "Test message"
        assert log_data["level"] == "INFO"
        assert log_data["logger"] == "test_logger"
        assert "timestamp" in log_data
        assert "source" in log_data
        assert "process" in log_data
        assert "thread" in log_data

    def test_json_format_with_extra_fields(self, json_log_handler):
        """Test JSON formatting with extra fields."""
        handler, stream = json_log_handler
        logger = logging.getLogger("test_logger")
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)

        logger.info("Test message", extra={"user_id": "123", "action": "login"})

        stream.seek(0)
        log_line = stream.read().strip()
        log_data = json.loads(log_line)

        assert log_data["user_id"] == "123"
        assert log_data["action"] == "login"

    def test_json_format_with_exception(self, json_log_handler):
        """Test JSON formatting with exception info."""
        handler, stream = json_log_handler
        logger = logging.getLogger("test_logger")
        logger.handlers = [handler]
        logger.setLevel(logging.ERROR)

        try:
            raise ValueError("Test error")
        except ValueError:
            logger.error("Error occurred", exc_info=True)

        stream.seek(0)
        log_line = stream.read().strip()
        log_data = json.loads(log_line)

        assert "exception" in log_data
        assert log_data["exception"]["type"] == "ValueError"
        assert "Test error" in log_data["exception"]["message"]


class TestRequestContext:
    """Tests for request context management."""

    def test_set_request_context(self, json_log_handler):
        """Test setting request context variables."""
        handler, stream = json_log_handler
        logger = logging.getLogger("test_logger")
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)

        set_request_context(
            request_id="req-123",
            user_id="user-456",
            correlation_id="corr-789",
        )

        logger.info("Test message")

        stream.seek(0)
        log_line = stream.read().strip()
        log_data = json.loads(log_line)

        assert log_data["request_id"] == "req-123"
        assert log_data["user_id"] == "user-456"
        assert log_data["correlation_id"] == "corr-789"

    def test_partial_request_context(self, json_log_handler):
        """Test setting partial request context."""
        handler, stream = json_log_handler
        logger = logging.getLogger("test_logger")
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)

        set_request_context(request_id="req-123")

        logger.info("Test message")

        stream.seek(0)
        log_line = stream.read().strip()
        log_data = json.loads(log_line)

        assert log_data["request_id"] == "req-123"
        assert "user_id" not in log_data
        assert "correlation_id" not in log_data

    def test_clear_request_context(self, json_log_handler):
        """Test clearing request context."""
        handler, stream = json_log_handler
        logger = logging.getLogger("test_logger")
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)

        set_request_context(request_id="req-123")
        clear_request_context()

        logger.info("Test message")

        stream.seek(0)
        log_line = stream.read().strip()
        log_data = json.loads(log_line)

        assert "request_id" not in log_data

    def test_context_isolation(self):
        """Test that context variables are isolated."""
        set_request_context(request_id="req-123")

        assert request_id_var.get() == "req-123"

        clear_request_context()

        assert request_id_var.get() is None


class TestLogLevelManagement:
    """Tests for dynamic log level management."""

    def test_get_current_log_level_root(self):
        """Test getting current log level for root logger."""
        set_log_level("INFO")
        level = get_current_log_level()

        assert level == "INFO"

    def test_get_current_log_level_specific_logger(self):
        """Test getting current log level for specific logger."""
        logger = logging.getLogger("test.logger")
        logger.setLevel(logging.DEBUG)

        level = get_current_log_level("test.logger")

        assert level == "DEBUG"

    def test_set_log_level_root(self):
        """Test setting log level for root logger."""
        set_log_level("DEBUG")

        assert logging.root.level == logging.DEBUG

    def test_set_log_level_specific_logger(self):
        """Test setting log level for specific logger."""
        logger = logging.getLogger("test.logger")

        set_log_level("WARNING", "test.logger")

        assert logger.level == logging.WARNING

    def test_set_log_level_invalid(self):
        """Test setting invalid log level raises error."""
        with pytest.raises(ValueError, match="Invalid log level"):
            set_log_level("INVALID")

    def test_set_log_level_updates_handlers(self):
        """Test that setting log level updates handlers."""
        handler = logging.StreamHandler()
        logger = logging.getLogger("test.logger")
        logger.addHandler(handler)

        set_log_level("ERROR", "test.logger")

        assert handler.level == logging.ERROR


class TestLoggingConfiguration:
    """Tests for logging configuration."""

    def test_configure_logging_json_format(self):
        """Test configuring logging with JSON format."""
        configure_logging(log_level="INFO", json_logs=True)

        root_logger = logging.getLogger()

        assert root_logger.level == logging.INFO
        assert len(root_logger.handlers) > 0

    def test_configure_logging_plain_format(self):
        """Test configuring logging with plain format."""
        configure_logging(log_level="DEBUG", json_logs=False)

        root_logger = logging.getLogger()

        assert root_logger.level == logging.DEBUG

    def test_configure_logging_with_file(self, tmp_path):
        """Test configuring logging with file output."""
        log_file = tmp_path / "test.log"

        configure_logging(log_level="INFO", log_file=str(log_file))

        # Write a log message
        logger = logging.getLogger("test")
        logger.info("Test message")

        # Verify file was created and contains log
        assert log_file.exists()
        content = log_file.read_text()
        assert "Test message" in content

    def test_configure_logging_specific_loggers(self):
        """Test that specific loggers are configured."""
        configure_logging()

        uvicorn_logger = logging.getLogger("uvicorn")
        sqlalchemy_logger = logging.getLogger("sqlalchemy")

        # These loggers should be configured
        assert uvicorn_logger.level == logging.INFO
        assert sqlalchemy_logger.level == logging.WARNING


class TestLoggingLevels:
    """Tests for different logging levels."""

    def test_debug_level_logs_all(self, json_log_handler):
        """Test DEBUG level logs all messages."""
        handler, stream = json_log_handler
        logger = logging.getLogger("test")
        logger.handlers = [handler]
        logger.setLevel(logging.DEBUG)

        logger.debug("Debug")
        logger.info("Info")
        logger.warning("Warning")
        logger.error("Error")

        stream.seek(0)
        logs = stream.read()

        assert "Debug" in logs
        assert "Info" in logs
        assert "Warning" in logs
        assert "Error" in logs

    def test_info_level_filters_debug(self, json_log_handler):
        """Test INFO level filters debug messages."""
        handler, stream = json_log_handler
        logger = logging.getLogger("test")
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)

        logger.debug("Debug")
        logger.info("Info")

        stream.seek(0)
        logs = stream.read()

        assert "Debug" not in logs
        assert "Info" in logs

    def test_error_level_only_errors(self, json_log_handler):
        """Test ERROR level only logs errors and critical."""
        handler, stream = json_log_handler
        logger = logging.getLogger("test")
        logger.handlers = [handler]
        logger.setLevel(logging.ERROR)

        logger.info("Info")
        logger.warning("Warning")
        logger.error("Error")

        stream.seek(0)
        logs = stream.read()

        assert "Info" not in logs
        assert "Warning" not in logs
        assert "Error" in logs
