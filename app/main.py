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

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi_oauth2.middleware import OAuth2Middleware
from fastapi_oauth2.router import router as oauth2_router
from fastapi_oauth2.config import OAuth2Config
from fastapi_oauth2.client import OAuth2Client
from fastapi_oauth2.claims import Claims
from fastapi_oauth2.exceptions import OAuth2AuthenticationError
from social_core.backends.egi_checkin import EGICheckinOpenIdConnect

from app import auth_middleware  # noqa: F401  — patches jwt_create/jwt_decode at import
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


@app.get("/oauth2/{provider}/token")
async def oauth2_token_callback(request: Request, provider: str):
    """Login callback (Auth Design 1): exchange the code for IdP tokens and
    set the *IdP access token* as the session cookie — the dispatcher
    never mints credentials of its own.

    Registered before the library router (first match wins). Cookie
    attributes mirror the library's ``token_redirect``; the value is the
    IdP access token itself. The refresh token, when issued, is handed to
    ``auth_middleware.on_login_tokens`` — the capture seam for the
    future janitor (see the v4 plan).
    """
    core = request.auth.clients[provider]
    data = await core.token_data(request)  # code → token exchange (+ userinfo)
    idp_tokens = dict(getattr(core._oauth_client, "token", None) or {})
    access_token = idp_tokens.get("access_token")
    if not access_token:
        raise OAuth2AuthenticationError(500, "provider returned no access_token")
    auth_middleware.on_login_tokens(
        data.get("sub"), access_token, idp_tokens.get("refresh_token")
    )
    response = RedirectResponse(core.redirect_uri or request.base_url)
    response.set_cookie(
        "Authorization",
        value=f"Bearer {access_token}",
        max_age=request.auth.expires,  # cookie lifetime ≈ token expires_in
        expires=request.auth.expires,
        secure=not request.auth.http,
        httponly=True,
        samesite=request.auth.same_site,
    )
    return response


# Include routers
app.include_router(oauth2_router)
app.include_router(requests.router)
app.include_router(auth.router)
if settings.anonymous_requests_enabled:
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
    if os.getenv("ENV") == "local":
        logger.info("Using dummy OAuth2 client for local development")
        return DummyOAuth2Client(
            backend=TestEGICheckinOpenIdConnect, client_id="", client_secret=""
        )
    return OAuth2Client(
        backend=TestEGICheckinOpenIdConnect,
        scope=[
            "openid",
            "email",
            "profile",
            "offline_access",
            "entitlements",
            "voperson_id",
            "voperson_external_affiliation",
            "eduperson_entitlement",
        ],
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        redirect_uri=settings.redirect_uri,
        # Claims are read from the JWT itself (Auth Design 1): the token
        # carries sub / preferred_username; email is not in the access
        # token and maps to "" — display only, never enforcement.
        claims=Claims(identity="sub", display_name="preferred_username"),
    )


def on_auth_error(conn, exc):
    """401 + WWW-Authenticate (the library default is a bare 400).

    Callers key refresh-vs-relogin on the error code:
    expired_token vs invalid_token.
    """
    expired = "expired" in str(exc).lower()
    return JSONResponse(
        {"detail": str(exc)},
        status_code=401,
        headers={
            "WWW-Authenticate": 'Bearer error="'
            + ("expired_token" if expired else "invalid_token")
            + '"'
        },
    )


app.add_middleware(
    OAuth2Middleware,
    config=OAuth2Config(
        clients=[get_oauth2_client()],
        # Cookie ≈ token lifetime (3600 s): sessions end when the IdP token
        # expires — accepted decision (Auth Design 1 validation, §4.2).
        # "lax" (was "none"): same-origin browser UX works; cross-site
        # API consumers must use the Authorization header.
        same_site="lax",
        jwt_expires=3600,
    ),
    on_error=on_auth_error,
)
