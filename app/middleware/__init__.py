"""Middleware package for the dispatcher application."""

from app.middleware.request_logging import RequestLoggingMiddleware

__all__ = ["RequestLoggingMiddleware"]
