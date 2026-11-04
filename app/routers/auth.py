"""OAuth2 routes: EGI Check-in login (fastapi-sso) — Auth Design 1.

Routes only. The login flow comes from :mod:`app.checkin` (the provider)
and :mod:`app.security` (verification): the session cookie holds the
IdP access token itself; every request is verified locally.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi_sso.sso.base import SSOLoginError

from app import security
from app.checkin import REDIRECT_PATH, build_sso
from app.config import settings
from app.security import oauth2_scheme

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/oauth2",
    tags=["oauth2"],
    responses={404: {"description": "Not found"}},
)


def _redirect_uri(request: Request) -> str:
    return str(request.base_url).rstrip("/") + REDIRECT_PATH


@router.get("/login")
async def login(request: Request):
    """Redirect to EGI Check-in; a state cookie travels with the request."""
    async with build_sso(_redirect_uri(request)) as sso:
        return await sso.get_login_redirect()


@router.get("/egi-checkin/token")
async def checkin_redirect(request: Request):
    """OIDC redirection endpoint: receives the browser back from
    Check-in, exchanges the code for IdP tokens, and sets the *IdP access
    token* as the session cookie — the dispatcher never mints
    credentials of its own."""
    async with build_sso(_redirect_uri(request)) as sso:
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
