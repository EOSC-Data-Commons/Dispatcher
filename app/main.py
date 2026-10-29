"""
FastAPI application entry point for the dispatcher service.

This module initializes the application and configures logging. Request
authentication is not middleware: every protected route depends on
``app.security.oauth2_scheme``, which verifies the request's own
credential (Authorization header or session cookie) via
``app.security`` — the Auth Design 1 resource-server model.
"""

import logging
import ssl
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routers import requests, auth, anonymous_requests
from app.config import settings
from app.logging_config import setup_logging
from app.middleware.request_logging import RequestLoggingMiddleware

# Initialize logging before anything else
setup_logging(
    log_level=settings.log_level,
    log_format=settings.log_format,
    disable_uvicorn_access=True,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    # Startup
    logger.info("Dispatcher service starting...")
    logger.info(f"Log level: {settings.log_level}")
    logger.info(f"EGI Checkin environment: {settings.egi_checkin_env}")
    logger.info(f"Host: {settings.host}")
    yield
    # Shutdown
    logger.info("Dispatcher service shutting down...")


app = FastAPI(title="Dispatcher Service", lifespan=lifespan)

# Add request logging middleware
app.add_middleware(RequestLoggingMiddleware)

# Include routers
app.include_router(requests.router)
app.include_router(auth.router)
if settings.anonymous_requests_enabled:
    app.include_router(anonymous_requests.router)

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ssl_context.load_cert_chain(settings.cert_chain_file, keyfile=settings.private_key_file)
