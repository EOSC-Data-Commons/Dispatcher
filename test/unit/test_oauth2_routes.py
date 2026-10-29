"""Unit tests for the request-credential dependency and login routes."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi_sso.sso.base import OpenID

from app import security
from app.config import settings
from app.routers import auth as auth_router
from app.security import oauth2_scheme
from fixtures.jwt_helper import generate_rsa_key, make_token, patch_jwks


@pytest.fixture(autouse=True)
def dev_env():
    original = settings.egi_checkin_env
    settings.egi_checkin_env = "dev"
    yield
    settings.egi_checkin_env = original


@pytest.fixture
def key(monkeypatch):
    rsa_key = generate_rsa_key()
    patch_jwks(monkeypatch, rsa_key)
    return rsa_key


def _request(headers=None, cookies=None):
    return SimpleNamespace(headers=headers or {}, cookies=cookies or {})


# ---------------------------------------------------------------------------
# oauth2_scheme dependency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheme_returns_verified_header_token(key):
    token = make_token(key)
    result = await oauth2_scheme(_request(headers={"Authorization": f"Bearer {token}"}))
    assert result == token


@pytest.mark.asyncio
async def test_scheme_accepts_session_cookie(key):
    token = make_token(key)
    result = await oauth2_scheme(
        _request(cookies={security.SESSION_COOKIE: f"Bearer {token}"})
    )
    assert result == token


@pytest.mark.asyncio
async def test_scheme_401_without_credential():
    with pytest.raises(HTTPException) as exc:
        await oauth2_scheme(_request())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_scheme_401_expired_token_with_error_code(key):
    token = make_token(key, lifetime=-1000)
    with pytest.raises(HTTPException) as exc:
        await oauth2_scheme(_request(headers={"Authorization": f"Bearer {token}"}))
    assert exc.value.status_code == 401
    assert 'error="expired_token"' in exc.value.headers["WWW-Authenticate"]


@pytest.mark.asyncio
async def test_scheme_401_garbage_token(key):
    with pytest.raises(HTTPException) as exc:
        await oauth2_scheme(_request(headers={"Authorization": "Bearer not-a-jwt"}))
    assert exc.value.status_code == 401
    assert 'error="invalid_token"' in exc.value.headers["WWW-Authenticate"]


# ---------------------------------------------------------------------------
# login routes (fake SSO provider)
# ---------------------------------------------------------------------------


class _FakeSSO:
    """Stands in for the fastapi-sso provider: no network, fixed tokens."""

    def __init__(self, redirect_uri=None):
        self.redirect_uri = redirect_uri

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get_login_redirect(self):
        return RedirectResponse("https://checkin.example/auth", status_code=303)

    async def verify_and_process(self, request):
        return OpenID(id="sub@egi.eu", provider="egi-checkin")

    @property
    def access_token(self):
        return "access-tok"

    @property
    def refresh_token(self):
        return "refresh-tok"


@pytest.fixture
def app(monkeypatch):
    captured = {}

    def fake_build(redirect_uri):
        captured["redirect_uri"] = redirect_uri
        return _FakeSSO(redirect_uri)

    login_events = []
    monkeypatch.setattr(auth_router, "build_sso", fake_build)
    monkeypatch.setattr(
        security,
        "on_login_tokens",
        lambda sub, access, refresh: login_events.append((sub, access, refresh)),
    )

    app = FastAPI()
    app.include_router(auth_router.router)
    app.state.captured = captured
    app.state.login_events = login_events
    return app


@pytest.mark.asyncio
async def test_login_redirects_to_provider(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://test"
    ) as client:
        response = await client.get("/oauth2/login", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "https://checkin.example/auth"
    # The callback URL handed to the provider matches the registered path.
    assert app.state.captured["redirect_uri"].endswith(auth_router.CALLBACK_PATH)


@pytest.mark.asyncio
async def test_callback_sets_idp_token_as_cookie(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://test"
    ) as client:
        response = await client.get("/oauth2/egi-checkin/token", follow_redirects=False)

    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    # Starlette quotes cookie values that contain spaces.
    assert 'Authorization="Bearer access-tok"' in cookie
    assert "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()
    # Refresh-token capture seam fired with everything Check-in issued.
    assert app.state.login_events == [("sub@egi.eu", "access-tok", "refresh-tok")]


@pytest.mark.asyncio
async def test_logout_deletes_session_cookie(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://test"
    ) as client:
        response = await client.get("/oauth2/logout", follow_redirects=False)

    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    assert security.SESSION_COOKIE in cookie
    assert "Max-Age=0" in cookie or "1970" in cookie
