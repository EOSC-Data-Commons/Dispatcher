"""
Request logging middleware for FastAPI application.

This middleware provides:
- Request ID generation and correlation
- Request/response logging for audit and debugging
- Performance timing metrics
"""

import logging
import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.logging_config import set_request_id


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for logging HTTP requests and responses.

    Adds request ID headers, logs request details, and captures
    response status codes and processing times.
    """

    def __init__(self, app):
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = str(uuid.uuid4())

        # Set request ID in context for log correlation
        set_request_id(request_id)

        logger = logging.getLogger("app.access")

        # Extract request details
        client_host = request.client.host if request.client else "unknown"
        client_port = request.client.port if request.client else 0

        # Log request start
        logger.info(
            f"Request started: {request.method} {request.url.path}",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "client": f"{client_host}:{client_port}",
                "query_params": (
                    str(request.query_params) if request.query_params else ""
                ),
            },
        )

        start_time = time.time()

        try:
            # Process request
            response = await call_next(request)

            # Calculate processing time
            process_time = time.time() - start_time

            # Log response
            logger.info(
                f"Request completed: {request.method} {request.url.path} - {response.status_code}",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "process_time_ms": round(process_time * 1000, 2),
                },
            )

            # Add request ID to response headers for tracing
            response.headers["X-Request-ID"] = request_id

            return response

        except Exception:
            # Calculate processing time even on error
            process_time = time.time() - start_time

            # Log the exception
            logger.error(
                f"Request failed: {request.method} {request.url.path} - Exception raised",
                exc_info=True,
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "process_time_ms": round(process_time * 1000, 2),
                },
            )

            # Re-raise the exception
            raise
