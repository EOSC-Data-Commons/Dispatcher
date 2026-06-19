"""
FastAPI application entry point for the dispatcher service.

This module initializes the application, configures logging, and sets up
middleware for request handling and authentication.
"""

import logging
import os
import ssl
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi_oauth2.middleware import OAuth2Middleware
from fastapi_oauth2.router import router as oauth2_router
from fastapi_oauth2.config import OAuth2Config
from fastapi_oauth2.client import OAuth2Client
from fastapi_oauth2.claims import Claims
from social_core.backends.egi_checkin import EGICheckinOpenIdConnect

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

# Add request logging middleware (must be added before OAuth2 middleware)
app.add_middleware(RequestLoggingMiddleware)

# Include routers
app.include_router(oauth2_router)
app.include_router(requests.router)
app.include_router(auth.router)
app.include_router(anonymous_requests.router)

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ssl_context.load_cert_chain(settings.cert_chain_file, keyfile=settings.private_key_file)


class TestEGICheckinOpenIdConnect(EGICheckinOpenIdConnect):
    CHECKIN_ENV = settings.egi_checkin_env


class DummyOAuth2Client(OAuth2Client):
    async def authenticate(self, code: Optional[str] = None, **kwargs):
        return {
            "id": "dummy-user",
            "email": "dev@example.com",
            "name": "Dev User",
            "picture": None,
        }


def get_oauth2_client() -> OAuth2Client:
    if os.getenv("ENV") == "development":
        logger.info("Using dummy OAuth2 client for local development")
        return DummyOAuth2Client(
            backend=TestEGICheckinOpenIdConnect, client_id="", client_secret=""
        )
    return OAuth2Client(
        backend=TestEGICheckinOpenIdConnect,
        scope=[
            "openid email profile entitlements voperson_id voperson_external_affiliation eduperson_entitlement"
        ],
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        redirect_uri=settings.redirect_uri,
        claims=Claims(
            identity=lambda user: f"{user.provider}:{user.id}",
        ),
    )


app.add_middleware(
    OAuth2Middleware,
    config=OAuth2Config(clients=[get_oauth2_client()], same_site="none"),
)
