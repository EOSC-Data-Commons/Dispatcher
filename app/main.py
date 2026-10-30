"""
FastAPI application entry point for the dispatcher service.

This module initializes the application and configures logging. Request
authentication is not middleware: every protected route depends on
``app.security.oauth2_scheme``, which verifies the request's own
credential (Authorization header or session cookie) via
``app.security`` — the Auth Design 1 resource-server model.
"""

import asyncio
import logging
import ssl
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routers import requests, auth, anonymous_requests, healthz
from app.config import settings
from app.credentials import SQLiteCredentialStore
from app.http import close_http_client, init_http_client
from app.logging_config import setup_logging
from app.middleware.request_logging import RequestLoggingMiddleware
from app.services.janitor import RecoveryManager
from app.status_store import SQLiteStatusStore

# Initialize logging before anything else
setup_logging(
    log_level=settings.log_level,
    log_format=settings.log_format,
    disable_uvicorn_access=True,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan wiring: shared HTTP client, SQLite status store, live-task
    registry, and the recovery manager (startup scan + periodic janitor).

    Operated as a single uvicorn worker: flows live in the receiving
    worker's memory, so the "does anyone own this flow?" liveness check is
    unambiguous (see the design note)."""
    # Startup
    logger.info("Dispatcher service starting...")
    logger.info(f"Log level: {settings.log_level}")
    logger.info(f"EGI Checkin environment: {settings.egi_checkin_env}")
    logger.info(f"Host: {settings.host}")

    init_http_client()
    store = SQLiteStatusStore(settings.db_path)
    await store.connect()
    app.state.status_store = store
    credentials = SQLiteCredentialStore(settings.db_path)
    await credentials.connect()
    app.state.credentials = credentials
    app.state.tasks: dict[str, asyncio.Task] = {}

    recovery = RecoveryManager(store, app.state.tasks, credential_store=credentials)
    await recovery.scan_once()  # startup: reap pre-restart orphans
    janitor = asyncio.create_task(recovery.run_periodic())
    try:
        yield
    finally:
        # Shutdown
        logger.info("Dispatcher service shutting down...")
        recovery.stop()
        janitor.cancel()
        await asyncio.gather(janitor, return_exceptions=True)
        live = list(app.state.tasks.values())
        for task in live:
            task.cancel()
        await asyncio.gather(*live, return_exceptions=True)
        await close_http_client()
        await credentials.aclose()
        await store.aclose()


app = FastAPI(title="Dispatcher Service", lifespan=lifespan)

# Add request logging middleware
app.add_middleware(RequestLoggingMiddleware)

# Include routers
app.include_router(healthz.router)
app.include_router(requests.router)
app.include_router(auth.router)
if settings.anonymous_requests_enabled:
    app.include_router(anonymous_requests.router)

# TLS context for direct (non-compose) runs; compose passes --ssl flags to
# uvicorn command line instead.
ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
if settings.cert_chain_file:
    ssl_context.load_cert_chain(
        settings.cert_chain_file, keyfile=settings.private_key_file
    )
