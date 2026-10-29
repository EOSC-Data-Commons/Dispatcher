"""JWT verification and request credentials — the single source of trust.

The dispatcher acts as an OAuth2 resource server (Auth Design 1): it
validates IdP-issued JWTs locally via JWKS and mints no credentials of
its own. One token type, one validator, for both browser sessions
(cookie) and Bearer callers (header).

This module owns *trust* and nothing else: verification, the request
credential, and the session constants. The EGI Check-in realm facts —
issuer map, endpoints, login flow — live in :mod:`app.checkin`; this
module anchors its issuer pin and JWKS URL to ``checkin.issuer()``. The
HTTP routes live in :mod:`app.routers.auth`.

Validated against a live Check-in token on 2026-10-27 (aai-dev):
RS256, `kid`-addressed JWKS, 3600 s lifetime, no `aud` claim (none is
emitted — do not require one), `sub` / `voperson_id` /
`preferred_username` present, `scope` a space-delimited string.
See ``plans/Auth Design 1 — Dispatcher validation.md``.
"""

import logging
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.checkin import issuer

logger = logging.getLogger(__name__)

#: Algorithms accepted for verification — pinned, never both HMAC and RSA.
ALGORITHMS = ("RS256",)

LEEWAY_SECONDS = 30

#: Session cookie carrying the Bearer credential (browser logins).
SESSION_COOKIE = "Authorization"

#: Cookie lifetime ≈ the IdP token lifetime (Check-in issues 3600 s):
#: sessions end when the token expires and the user re-logs in — accepted
#: decision (Auth Design 1 validation, §4.2).
SESSION_MAX_AGE = 3600


@runtime_checkable
class SigningKey(Protocol):
    """What verify() needs from a resolved signing key."""

    key: Any  # the key material PyJWT accepts


@runtime_checkable
class JWKSSource(Protocol):
    """The key-source seam.

    ``_jwks()`` returns one; the production implementation is PyJWT's
    PyJWKClient, the tests substitute fixtures.jwt_helper.FakeJWKS.
    Declared here so the implicit interface the fakes already implement
    is explicit — this is documentation, not a second implementation.
    """

    def get_signing_key_from_jwt(self, token: str) -> SigningKey: ...


@lru_cache(maxsize=1)
def _jwks() -> JWKSSource:
    url = f"{issuer()}/protocol/openid-connect/certs"
    logger.info("Using Check-in JWKS at %s", url)
    return PyJWKClient(url, cache_keys=True)


def verify(token: str) -> dict:
    """The only place a token becomes trusted.

    Checks the signature (RS256 via the realm's JWKS), the issuer (pinned
    per environment) and expiry. No audience validation: Check-in emits
    no ``aud`` claim (verified live); the issuer pin plus signature is
    the compensating control.
    """
    return jwt.decode(
        token,
        _jwks().get_signing_key_from_jwt(token).key,
        algorithms=list(ALGORITHMS),
        issuer=issuer(),
        leeway=LEEWAY_SECONDS,
        options={"require": ["exp", "iat", "iss", "sub"]},
    )


def access_token_from_request(request: Request) -> str | None:
    """The request's own credential: Authorization header (Bearer) first,
    then the Authorization cookie (browser sessions — the cookie value
    carries the ``Bearer`` prefix too).
    """
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer ") :]
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        return cookie[len("Bearer ") :] if cookie.startswith("Bearer ") else cookie
    return None


def on_login_tokens(
    sub: str | None, access_token: str, refresh_token: str | None
) -> None:
    """Login-event seam for later phases.

    The login callback (``app/routers/auth.py``) calls this with
    everything Check-in issued. Today it only logs at debug level;
    the janitor session (v4 plan, D2) replaces the body with a write to
    the per-user credentials store, so out-of-band IM lifecycle
    operations can exchange the refresh token for a fresh access token.

    ``offline_access`` is requested in the client scope so refresh
    tokens ARE issued — capturing one later requires no config change.
    """
    logger.debug(
        "Login for %s (refresh token %s)",
        sub,
        "issued" if refresh_token else "not issued",
    )


# --- request credential (FastAPI dependency) --------------------------------
#
# OpenAPI integration: shows the Authorize dialog for pasting Bearer
# tokens. Browser users never need it — they authenticate via cookie.

_bearer = HTTPBearer(auto_error=False, bearerFormat="JWT")


async def oauth2_scheme(
    request: Request,
    # OpenAPI registration only (the Authorize dialog): the credential
    # itself is read from the request below, header first then cookie.
    _credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """The request's own verified access token, or a 401.

    Every protected route depends on this, so verification (RS256 via
    JWKS, issuer pin, expiry) happens per request with no middleware:
    Authorization header first (CLI/service callers), then the session
    cookie (browser logins).
    """
    token = access_token_from_request(request)
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )
    try:
        verify(token)
    except jwt.PyJWTError as exc:
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
