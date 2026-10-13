"""Dual-credential authentication backend.

The dispatcher accepts two credentials on protected endpoints:

1. the fastapi-oauth2 session token (HS256) minted after the browser login
   flow and carried in the ``Authorization`` cookie — handled by
   :class:`fastapi_oauth2.middleware.OAuth2Backend` unchanged;
2. a raw EGI Check-in access token presented by API clients as a Bearer
   token (Authorization header or cookie) — validated against the Check-in
   userinfo endpoint of the configured environment, with a small in-process
   TTL cache so consecutive calls do not hit userinfo every time.

A raw-token success produces the same ``Auth``/``User`` shapes the session
path produces, except that ``auth.provider`` is a *per-request* handle
carrying the caller's own access token — never the shared ``OAuth2Core``
singleton, so concurrent callers cannot clobber each other's tokens where
``request.auth.provider.access_token`` is consumed (e.g. ``/requests/*``,
``/oauth2/token``).
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import requests
from fastapi.security.utils import get_authorization_scheme_param
from jose import jwt as jose_jwt
from jose.exceptions import JWTError
from starlette.authentication import AuthenticationError
from starlette.requests import Request

from fastapi_oauth2.claims import Claims
from fastapi_oauth2.middleware import Auth, OAuth2Backend, User

from app.config import settings
from app.vres.utils.token_utils import _CHECKIN_USERINFO_URLS

logger = logging.getLogger(__name__)


@dataclass
class ProviderHandle:
    """Per-request provider view carrying the caller's own access token."""

    provider: str
    access_token: str
    claims: Claims | None


class _ClaimsCache:
    """Tiny in-process TTL cache: raw token -> userinfo claims."""

    def __init__(self, ttl: float, max_entries: int = 1024) -> None:
        self._ttl = ttl
        self._max = max_entries
        self._entries: dict[str, tuple[float, dict]] = {}

    def get(self, token: str) -> dict | None:
        entry = self._entries.get(token)
        if entry is None:
            return None
        expires_at, claims = entry
        if expires_at < time.time():
            self._entries.pop(token, None)
            return None
        return claims

    def put(self, token: str, claims: dict) -> None:
        if len(self._entries) >= self._max:
            now = time.time()  # cheap trim: evict all expired entries
            self._entries = {t: e for t, e in self._entries.items() if e[0] >= now}
        self._entries[token] = (time.time() + self._ttl, claims)


def _token_scope(token: str) -> list[str]:
    """Unverified read of the JWT ``scope`` claim (the token's validity is
    established by the userinfo call anyway); [] for opaque payloads."""
    try:
        claims = jose_jwt.get_unverified_claims(token)
    except JWTError:
        return []
    scope = claims.get("scope", "")
    return scope.split() if isinstance(scope, str) else list(scope or [])


def _fetch_userinfo_claims(access_token: str) -> dict:
    """Full userinfo claim set for *access_token* from the EGI Check-in
    federation backend. Synchronous GET — the backend runs it in a worker
    thread off the event loop (see :meth:`DispatcherAuthBackend._claims`)."""
    userinfo_url = _CHECKIN_USERINFO_URLS.get(settings.egi_checkin_env)
    response = requests.get(
        userinfo_url,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


class DispatcherAuthBackend(OAuth2Backend):
    """fastapi-oauth2 backend that additionally accepts raw Check-in tokens.

    Inherits ``OAuth2Backend.__init__`` so the shared ``Auth`` class attrs
    (``clients``, ``same_site``, ``http``...) stay populated for the
    authorize/callback machinery; ``authenticate()`` only adds the raw-token
    fallback on top of the unchanged session-token path.
    """

    def __init__(self, config, cache_ttl: float) -> None:
        super().__init__(config)
        self._cache = _ClaimsCache(cache_ttl)

    async def authenticate(self, request: Request) -> Optional[Tuple[Auth, User]]:
        try:
            return await super().authenticate(request)
        except AuthenticationError:
            authorization = request.headers.get(
                "Authorization", request.cookies.get("Authorization")
            )
            scheme, param = get_authorization_scheme_param(authorization or "")
            if not scheme or not param:
                raise
            return await self._authenticate_access_token(param)

    async def _authenticate_access_token(self, token: str) -> Tuple[Auth, User]:
        claims = await self._claims(token)
        provider = Auth.clients.get("egi-checkin")
        claims_cfg = provider.claims if provider else {}
        scope = _token_scope(token) or (provider.scope if provider else None) or []

        auth = Auth(scopes=scope)
        auth.provider = ProviderHandle(
            provider="egi-checkin", access_token=token, claims=claims_cfg
        )
        user = User({**claims, "provider": "egi-checkin", "scope": scope})
        return auth, user.use_claims(claims_cfg)

    async def _claims(self, token: str) -> dict:
        cached = self._cache.get(token)
        if cached is not None:
            return cached
        try:
            claims = await asyncio.to_thread(_fetch_userinfo_claims, token)
        except requests.RequestException as exc:
            logger.debug("Raw access-token validation failed: %s", exc)
            raise AuthenticationError("Invalid EGI Check-in access token")
        if not isinstance(claims, dict) or not claims.get("sub"):
            raise AuthenticationError("Check-in userinfo response missing 'sub'")
        self._cache.put(token, claims)
        return claims
