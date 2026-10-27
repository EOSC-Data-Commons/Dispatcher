"""Request credential: Authorization header (Bearer) or the session cookie.

Replaces fastapi-oauth2's OAuth2AuthorizationCodeBearer. The dependency
returns the request's own *verified* access token — header first (CLI
and service callers; also the Swagger Authorize dialog), then the
session cookie (browser logins). See ``app/security.py`` and
``plans/Auth Design 1 — Dispatcher validation.md``.
"""

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import security

# OpenAPI integration: shows the Authorize dialog for pasting Bearer
# tokens. Browser users never need it — they authenticate via cookie.
_bearer = HTTPBearer(auto_error=False, bearerFormat="JWT")


async def oauth2_scheme(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """The request's own verified access token, or a 401.

    Every protected route depends on this, so verification (RS256 via
    JWKS, issuer pin, expiry) happens per request with no middleware.
    """
    token = security.access_token_from_request(request)
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )
    try:
        security.verify(token)
    except pyjwt.PyJWTError as exc:
        expired = "expired" in str(exc).lower()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            str(exc),
            headers={
                "WWW-Authenticate": 'Bearer error="'
                + ("expired_token" if expired else "invalid_token")
                + '"'
            },
        ) from exc
    return token
