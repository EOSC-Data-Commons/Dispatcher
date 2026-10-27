"""OAuth2 routes: EGI Check-in login (fastapi-sso) — Auth Design 1.

The login flow (authorization-code redirect + state cookie) comes from
``fastapi-sso``'s generic OpenID provider; the session cookie holds the
IdP access token itself; every request is verified locally by
:mod:`app.security`. No middleware, no monkeypatching.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi_sso.sso.base import OpenID, SSOLoginError
from fastapi_sso.sso.generic import create_provider

from app import security
from app.config import settings

from .utils import oauth2_scheme

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/oauth2",
    tags=["oauth2"],
    responses={404: {"description": "Not found"}},
)

#: Registered with EGI Check-in as the redirect URI — do not change
#: without re-registering the client.
CALLBACK_PATH = "/oauth2/egi-checkin/token"

#: Scope requested at login; ``offline_access`` makes Check-in issue a
#: refresh token (captured via security.on_login_tokens for the janitor).
_LOGIN_SCOPE = [
    "openid",
    "email",
    "profile",
    "offline_access",
    "entitlements",
    "voperson_id",
    "voperson_external_affiliation",
    "eduperson_entitlement",
]


def _checkin_endpoints() -> dict:
    """OIDC endpoints of the configured Check-in realm."""
    base = f"{security.issuer()}/protocol/openid-connect"
    return {
        "authorization_endpoint": f"{base}/auth",
        "token_endpoint": f"{base}/token",
        "userinfo_endpoint": f"{base}/userinfo",
        "jwks_uri": f"{base}/certs",
    }


def _openid_from_response(response: dict, session=None) -> OpenID:
    """Map Check-in's userinfo to the OpenID shape fastapi-sso expects.

    Only fields we consume: ``id`` feeds the login-event seam. Email is
    deliberately not mapped (not in the access token, unused here).
    """
    return OpenID(
        provider="egi-checkin",
        id=response.get("sub"),
        display_name=response.get("preferred_username"),
    )


#: Generic OpenID provider class for EGI Check-in.
CheckinSSO = create_provider(
    name="egi-checkin",
    default_scope=_LOGIN_SCOPE,
    discovery_document=lambda sso: _checkin_endpoints(),
    response_convertor=_openid_from_response,
)


def _build_sso(redirect_uri: str) -> CheckinSSO:
    """A fresh provider instance per request (required: state and the
    OAuth client are single-use)."""
    return CheckinSSO(
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        redirect_uri=redirect_uri,
    )


def _callback_uri(request: Request) -> str:
    return str(request.base_url).rstrip("/") + CALLBACK_PATH


@router.get("/login")
async def login(request: Request):
    """Redirect to EGI Check-in; a state cookie travels with the request."""
    async with _build_sso(_callback_uri(request)) as sso:
        return await sso.get_login_redirect()


@router.get("/egi-checkin/token")
async def checkin_callback(request: Request):
    """Login callback: exchange the code for IdP tokens and set the *IdP
    access token* as the session cookie — the dispatcher never mints
    credentials of its own."""
    async with _build_sso(_callback_uri(request)) as sso:
        openid = await sso.verify_and_process(request)
        access_token = sso.access_token
        refresh_token = sso.refresh_token

    if not access_token:
        raise SSOLoginError(500, "provider returned no access_token")

    # Refresh-token capture seam for the (future) janitor — see the v4 plan.
    security.on_login_tokens(openid.id if openid else None, access_token, refresh_token)

    response = RedirectResponse(settings.redirect_uri or "/docs", status_code=303)
    response.set_cookie(
        security.SESSION_COOKIE,
        value=f"Bearer {access_token}",
        max_age=security.SESSION_MAX_AGE,
        expires=security.SESSION_MAX_AGE,
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout():
    """Delete the session cookie. No OIDC RP-initiated logout: the IdP
    session survives (documented limitation)."""
    response = RedirectResponse("/docs", status_code=303)
    response.delete_cookie(security.SESSION_COOKIE)
    return response


@router.get("/token")
async def get_token(
    token: Annotated[str, Depends(oauth2_scheme)],
):
    # The request's own credential (header, or cookie for browsers) —
    # handy for CLI callers that then reuse it as a Bearer token.
    return {"token": token}
