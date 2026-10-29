"""EGI Check-in login provider (fastapi-sso).

Everything EGI-Check-in-specific about the login flow: the realm's OIDC
endpoints, the requested scope, the provider class, and a per-request
factory. The HTTP routes live in :mod:`app.routers.auth`; token
verification in :mod:`app.security`.
"""

from typing import Any, Protocol, runtime_checkable

from fastapi_sso.sso.base import OpenID
from fastapi_sso.sso.generic import create_provider
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app import security
from app.config import settings

#: Registered with EGI Check-in as the redirect URI (the OIDC
#: redirection endpoint) — do not change without re-registering the
#: client. Named "redirect" per OAuth vocabulary; GLOSSARY.md reserves
#: "callback URL" for the dispatch result.
REDIRECT_PATH = "/oauth2/egi-checkin/token"

#: Scope requested at login; ``offline_access`` makes Check-in issue a
#: refresh token (captured via security.on_login_tokens for the janitor).
LOGIN_SCOPE = [
    "openid",
    "email",
    "profile",
    "offline_access",
    "entitlements",
    "voperson_id",
    "voperson_external_affiliation",
    "eduperson_entitlement",
]


def _endpoints() -> dict:
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
    default_scope=LOGIN_SCOPE,
    discovery_document=lambda sso: _endpoints(),
    response_convertor=_openid_from_response,
)


@runtime_checkable
class LoginProvider(Protocol):
    """The login-flow seam: what the routes consume from build_sso().

    Deliberately narrow (interface segregation) — only the members the
    routes touch, with the no-argument call shapes they actually use.
    fastapi-sso's SSOBase and the test fake both conform; the routes
    never name this type (structural typing), the factory annotates it.
    """

    async def __aenter__(self) -> "LoginProvider": ...
    async def __aexit__(self, *args: object) -> None: ...
    async def get_login_redirect(self) -> RedirectResponse: ...
    async def verify_and_process(self, request: Request) -> Any: ...

    @property
    def access_token(self) -> str | None: ...

    @property
    def refresh_token(self) -> str | None: ...


def build_sso(redirect_uri: str) -> LoginProvider:
    """A fresh provider instance per request (required: state and the
    OAuth client are single-use)."""
    return CheckinSSO(
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        redirect_uri=redirect_uri,
    )
