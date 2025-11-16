"""
Structured JSON Logging Configuration.

Provides centralized logging configuration with JSON formatting,
contextual information tracking, and dynamic log level management.
"""

import logging
import logging.config
import os
import sys
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Dict, Optional

from pythonjsonlogger import jsonlogger

# Context variables for request tracking
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
user_id_var: ContextVar[Optional[str]] = ContextVar("user_id", default=None)
correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """
    Custom JSON formatter with additional contextual information.

    Automatically includes request_id, user_id, and correlation_id
    from context variables when available.
    """

    def add_fields(
        self,
        log_record: Dict[str, Any],
        record: logging.LogRecord,
        message_dict: Dict[str, Any],
    ) -> None:
        """Add custom fields to log record."""
        super().add_fields(log_record, record, message_dict)

        # Add timestamp in ISO format
        log_record["timestamp"] = datetime.utcfromtimestamp(record.created).isoformat() + "Z"

        # Add log level
        log_record["level"] = record.levelname

        # Add logger name
        log_record["logger"] = record.name

        # Add source location
        log_record["source"] = {
            "file": record.pathname,
            "line": record.lineno,
            "function": record.funcName,
        }

        # Add process and thread info
        log_record["process"] = {
            "pid": record.process,
            "name": record.processName,
        }
        log_record["thread"] = {
            "id": record.thread,
            "name": record.threadName,
        }

        # Add context variables if available
        request_id = request_id_var.get()
        if request_id:
            log_record["request_id"] = request_id

        user_id = user_id_var.get()
        if user_id:
            log_record["user_id"] = user_id

        correlation_id = correlation_id_var.get()
        if correlation_id:
            log_record["correlation_id"] = correlation_id

        # Add exception info if present
        if record.exc_info:
            log_record["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
            }


def get_log_level_from_env() -> str:
    """Get log level from environment variable."""
    return os.getenv("LOG_LEVEL", "INFO").upper()


def configure_logging(
    log_level: Optional[str] = None,
    json_logs: bool = True,
    log_file: Optional[str] = None,
) -> None:
    """
    Configure application-wide logging.

    Args:
        log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_logs: Whether to use JSON format (True) or plain text (False)
        log_file: Optional log file path for file output
    """
    if log_level is None:
        log_level = get_log_level_from_env()

    # Create formatter
    if json_logs:
        formatter = CustomJsonFormatter(
            "%(timestamp)s %(level)s %(logger)s %(message)s",
            timestamp=True,
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # Configure handlers
    handlers: Dict[str, Dict[str, Any]] = {
        "console": {
            "class": "logging.StreamHandler",
            "level": log_level,
            "formatter": "json" if json_logs else "plain",
            "stream": sys.stdout,
        }
    }

    # Add file handler if log file specified
    if log_file:
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": log_level,
            "formatter": "json" if json_logs else "plain",
            "filename": log_file,
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
        }

    # Configure logging
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": CustomJsonFormatter,
                "format": "%(timestamp)s %(level)s %(logger)s %(message)s",
            },
            "plain": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": handlers,
        "root": {
            "level": log_level,
            "handlers": list(handlers.keys()),
        },
        "loggers": {
            # Set specific loggers to different levels if needed
            "uvicorn": {
                "level": "INFO",
                "handlers": list(handlers.keys()),
                "propagate": False,
            },
            "uvicorn.access": {
                "level": "INFO",
                "handlers": list(handlers.keys()),
                "propagate": False,
            },
            "sqlalchemy": {
                "level": "WARNING",
                "handlers": list(handlers.keys()),
                "propagate": False,
            },
            "ccxt": {
                "level": "WARNING",
                "handlers": list(handlers.keys()),
                "propagate": False,
            },
        },
    }

    logging.config.dictConfig(logging_config)


def set_log_level(level: str, logger_name: Optional[str] = None) -> None:
    """
    Dynamically change log level.

    Args:
        level: New log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        logger_name: Specific logger name, or None for root logger
    """
    level = level.upper()
    if level not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        raise ValueError(f"Invalid log level: {level}")

    logger = logging.getLogger(logger_name) if logger_name else logging.getLogger()
    logger.setLevel(level)

    # Also update all handlers
    for handler in logger.handlers:
        handler.setLevel(level)


def get_current_log_level(logger_name: Optional[str] = None) -> str:
    """
    Get current log level.

    Args:
        logger_name: Specific logger name, or None for root logger

    Returns:
        Current log level name
    """
    logger = logging.getLogger(logger_name) if logger_name else logging.getLogger()
    return logging.getLevelName(logger.level)


def set_request_context(
    request_id: Optional[str] = None,
    user_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> None:
    """
    Set request context variables for logging.

    Args:
        request_id: Unique request identifier
        user_id: User identifier
        correlation_id: Correlation ID for tracing across services
    """
    if request_id is not None:
        request_id_var.set(request_id)
    if user_id is not None:
        user_id_var.set(user_id)
    if correlation_id is not None:
        correlation_id_var.set(correlation_id)


def clear_request_context() -> None:
    """Clear all request context variables."""
    request_id_var.set(None)
    user_id_var.set(None)
    correlation_id_var.set(None)


# Initialize logging on module import
configure_logging()
