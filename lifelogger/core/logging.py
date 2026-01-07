"""Structured logging for lifelogger.

Uses Python's standard logging with structured output.
Can be configured for JSON output in production.
"""

import logging
import sys
from datetime import datetime
from typing import Any

from lifelogger.core.config import get_settings


class StructuredFormatter(logging.Formatter):
    """Formatter that outputs structured log messages."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as structured text."""
        # Base fields
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "message", "asctime",
            ):
                log_data[key] = value

        # Format as readable structured output
        extra_str = ""
        extra_fields = {k: v for k, v in log_data.items()
                       if k not in ("timestamp", "level", "logger", "message", "exception")}
        if extra_fields:
            extra_str = " " + " ".join(f"{k}={v}" for k, v in extra_fields.items())

        base = f"[{log_data['timestamp']}] {log_data['level']:8} {log_data['logger']}: {log_data['message']}{extra_str}"

        if "exception" in log_data:
            base += f"\n{log_data['exception']}"

        return base


class JSONFormatter(logging.Formatter):
    """Formatter that outputs JSON log messages."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        import json

        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in log_data:
                continue
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "message", "asctime",
            ):
                try:
                    json.dumps(value)  # Check if serializable
                    log_data[key] = value
                except (TypeError, ValueError):
                    log_data[key] = str(value)

        return json.dumps(log_data)


def setup_logging(
    level: str | None = None,
    json_format: bool = False,
) -> logging.Logger:
    """Set up logging for lifelogger.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to settings.
        json_format: If True, output JSON formatted logs.

    Returns:
        The root lifelogger logger.
    """
    settings = get_settings()
    log_level = level or settings.log_level

    # Create logger
    logger = logging.getLogger("lifelogger")
    logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers
    logger.handlers.clear()

    # Create handler
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(getattr(logging, log_level.upper()))

    # Set formatter
    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(StructuredFormatter())

    logger.addHandler(handler)

    # Don't propagate to root logger
    logger.propagate = False

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a specific module.

    Args:
        name: Logger name, typically __name__

    Returns:
        Logger instance
    """
    return logging.getLogger(f"lifelogger.{name}")


# Convenience loggers for common operations
class LogContext:
    """Context manager for structured logging with timing."""

    def __init__(
        self,
        logger: logging.Logger,
        operation: str,
        **extra: Any,
    ):
        self.logger = logger
        self.operation = operation
        self.extra = extra
        self.start_time: datetime | None = None

    def __enter__(self) -> "LogContext":
        self.start_time = datetime.utcnow()
        self.logger.info(
            f"Starting {self.operation}",
            extra={"operation": self.operation, **self.extra},
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        duration = (datetime.utcnow() - self.start_time).total_seconds()

        if exc_type:
            self.logger.error(
                f"Failed {self.operation}",
                extra={
                    "operation": self.operation,
                    "duration_seconds": duration,
                    "error": str(exc_val),
                    **self.extra,
                },
                exc_info=True,
            )
        else:
            self.logger.info(
                f"Completed {self.operation}",
                extra={
                    "operation": self.operation,
                    "duration_seconds": duration,
                    **self.extra,
                },
            )


# Initialize default logging on import
_default_logger = setup_logging()
