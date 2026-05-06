"""
Centralized logging configuration for the dispatcher application.

This module provides production-ready logging setup that works well with
Docker deployments, outputting structured logs to stdout/stderr.
"""

import logging
import sys
from typing import Optional, Union

# Context variable for request ID correlation (used with middleware)
try:
    from contextvars import ContextVar

    request_id_var: ContextVar[str] = ContextVar("request_id", default="")
except ImportError:
    # Fallback for Python < 3.7
    request_id_var = None


class RequestIdFormatter(logging.Formatter):
    """
    Custom formatter that includes request ID in log messages.

    Format: timestamp - level - [module:line] [request_id] - message
    """

    def __init__(self, datefmt: str | None = None) -> None:
        super().__init__(
            "%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] "
            "[%(request_id)s] - %(message)s",
            datefmt=datefmt or "%Y-%m-%d %H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        # Inject request ID from context into the record
        if not hasattr(record, "request_id"):
            record.request_id = ""
        if request_id_var is not None:
            rid = request_id_var.get()
            if rid:
                record.request_id = rid
        return super().format(record)


def setup_logging(
    log_level: str = "INFO",
    log_format: str = "text",
    disable_uvicorn_access: bool = True,
) -> None:
    """
    Configure application-wide logging.

    This function should be called once at application startup.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Output format ('text' or 'json' for future expansion)
        disable_uvicorn_access: If True, disables uvicorn.access logger.
            Set to False to enable access logs (useful for debugging).
    """
    # Detect pytest environment
    is_pytest = "pytest" in sys.modules

    # Get the numeric log level
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Create formatter based on format type
    if log_format == "json":
        # Placeholder for future JSON structured logging
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
            '"logger": "%(name)s", "message": "%(message)s", '
            '"module": "%(module)s", "line": %(lineno)d}',
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    else:
        # Default text format for Docker stdout/stderr
        formatter = RequestIdFormatter()

    # Create console handler for stdout (< ERROR only)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    stdout_handler.addFilter(lambda record: record.levelno < logging.ERROR)
    stdout_handler.setFormatter(formatter)

    # Create console handler for stderr (errors and above)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.setFormatter(formatter)

    # Configure root logger (skip clearing handlers in pytest to preserve capture)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if not is_pytest:
        root_logger.handlers.clear()
    root_logger.addHandler(stdout_handler)
    root_logger.addHandler(stderr_handler)

    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.handlers = [stdout_handler, stderr_handler]
    uvicorn_logger.propagate = False

    uvicorn_access = logging.getLogger("uvicorn.access")
    if disable_uvicorn_access:
        uvicorn_access.handlers = []
        uvicorn_access.propagate = False
        uvicorn_access.disabled = True
    else:
        uvicorn_access.handlers = [stdout_handler]
        uvicorn_access.propagate = False
        uvicorn_access.disabled = False

    uvicorn_error = logging.getLogger("uvicorn.error")
    uvicorn_error.handlers = [stdout_handler, stderr_handler]
    uvicorn_error.propagate = False

    # Configure gunicorn if available
    gunicorn_logger = logging.getLogger("gunicorn.error")
    if gunicorn_logger.handlers:
        gunicorn_logger.handlers = [stderr_handler]
        gunicorn_logger.propagate = False

    gunicorn_access = logging.getLogger("gunicorn.access")
    if gunicorn_access.handlers:
        gunicorn_access.handlers = [stdout_handler]
        gunicorn_access.propagate = False


def set_request_id(request_id: str) -> None:
    """
    Set the request ID for the current context.

    This is used by the request logging middleware to correlate
    log messages with specific requests.

    Args:
        request_id: Unique request identifier
    """
    if request_id_var is not None:
        request_id_var.set(request_id)


def get_request_id() -> Optional[str]:
    """
    Get the request ID for the current context.

    Returns:
        Current request ID or None if not set
    """
    if request_id_var is not None:
        return request_id_var.get()
    return None
