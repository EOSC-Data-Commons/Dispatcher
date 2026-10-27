"""Neutralize fastapi-oauth2's token minting (Auth Design 1).

The library mints its own HS256 JWT as the session cookie — a second
credential system with a shared symmetric secret. The two patches below
make the library's cookie path carry the *IdP access token itself*, so
one credential, one validator, and one code path serve both browser
sessions and Bearer callers.

fastapi-oauth2 seams (verified against the installed 1.3.0):

- ``Auth.jwt_create`` — ``OAuth2Core.token_redirect`` uses it to build
  the cookie value. Patched to pass through ``_access_token`` instead of
  minting.
- ``Auth.jwt_decode`` — ``OAuth2Backend.authenticate`` uses it to
  validate the cookie. Patched to verify the IdP JWT via
  :mod:`app.security` and inject the fields the middleware expects.

These are unadvertised library internals: the ``fastapi-oauth2`` pin in
requirements is load-bearing.
"""

import logging

from fastapi_oauth2 import middleware as _fo_middleware
from fastapi_oauth2.exceptions import OAuth2AuthenticationError

from app import security

logger = logging.getLogger(__name__)

#: Claims key the middleware resolves ``auth.provider`` by.
PROVIDER = "egi-checkin"


def _jwt_create(token_data: dict) -> str:
    access_token = token_data.get("_access_token")
    if not access_token:
        raise OAuth2AuthenticationError(500, "no provider access token in callback")
    return access_token  # the IdP token IS the session credential


def _jwt_decode(token: str) -> dict:
    claims = dict(security.verify(token))
    claims["provider"] = PROVIDER  # authenticate() looks auth.provider up by this
    scope = claims.get("scope", "")
    if isinstance(scope, str):
        claims["scope"] = sorted(scope.split())
    elif isinstance(scope, list):
        claims["scope"] = sorted(scope)
    claims["_expires_at"] = claims["exp"]
    return claims


# Import-time patch, before the app serves any request.
_fo_middleware.Auth.jwt_create = classmethod(lambda cls, data: _jwt_create(dict(data)))
_fo_middleware.Auth.jwt_decode = staticmethod(_jwt_decode)


def on_login_tokens(
    sub: str | None, access_token: str, refresh_token: str | None
) -> None:
    """Login-event seam for later phases.

    The login callback (``app.main.oauth2_token_callback``) calls this
    with everything Check-in issued. Today it only logs at debug level;
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
