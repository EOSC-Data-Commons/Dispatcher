"""JWT verification against EGI Check-in — the single source of trust.

The dispatcher acts as an OAuth2 resource server (Auth Design 1): it
validates IdP-issued JWTs locally via JWKS and mints no credentials of
its own. One token type, one validator, for both browser sessions
(cookie) and Bearer callers (header).

Validated against a live Check-in token on 2026-10-27 (aai-dev):
RS256, `kid`-addressed JWKS, 3600 s lifetime, no `aud` claim (none is
emitted — do not require one), `sub` / `voperson_id` /
`preferred_username` present, `scope` a space-delimited string.
See ``plans/Auth Design 1 — Dispatcher validation.md``.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import HTTPException, Request, status
from jwt import PyJWKClient

from app.config import settings

logger = logging.getLogger(__name__)

#: Realm issuers keyed by the ``egi_checkin_env`` setting.
CHECKIN_ISSUERS = {
    "prod": "https://aai.egi.eu/auth/realms/egi",
    "demo": "https://aai-demo.egi.eu/auth/realms/egi",
    "dev": "https://aai-dev.egi.eu/auth/realms/egi",
}

#: Algorithms accepted for verification — pinned, never both HMAC and RSA.
ALGORITHMS = ("RS256",)

LEEWAY_SECONDS = 30


def issuer() -> str:
    """The Check-in realm issuer for the configured environment."""
    try:
        return CHECKIN_ISSUERS[settings.egi_checkin_env]
    except KeyError:
        raise ValueError(
            f"Unknown egi_checkin_env: {settings.egi_checkin_env!r}"
        ) from None


@lru_cache(maxsize=1)
def _jwks() -> PyJWKClient:
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


@dataclass(frozen=True)
class Principal:
    """The authenticated caller, uniform for cookie and header traffic."""

    subject: str
    scopes: frozenset[str]
    claims: dict
    raw_token: str  # forwarded to VREs; never log it


def principal_from(claims: dict, token: str) -> Principal:
    scope = claims.get("scope", "")
    if isinstance(scope, str):
        scopes = frozenset(scope.split())
    else:
        scopes = frozenset(scope)
    return Principal(
        subject=str(claims["sub"]),
        scopes=scopes,
        claims=claims,
        raw_token=token,
    )


def access_token_from_request(request: Request) -> str | None:
    """The request's own credential: Authorization header (Bearer) first,
    then the Authorization cookie (browser sessions — the cookie value
    carries the ``Bearer`` prefix too).
    """
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer ") :]
    cookie = request.cookies.get("Authorization")
    if cookie:
        return cookie[len("Bearer ") :] if cookie.startswith("Bearer ") else cookie
    return None


async def get_principal(request: Request) -> Principal:
    """Route dependency: a verified Principal or a 401 with the Bearer
    error contract (``expired_token`` vs ``invalid_token``)."""
    token = access_token_from_request(request)
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )
    try:
        return principal_from(verify(token), token)
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
