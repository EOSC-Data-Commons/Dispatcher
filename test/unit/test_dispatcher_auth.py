"""Tests for DispatcherAuthBackend: dual credentials at the auth middleware.

The fastapi-oauth2 session token (HS256, minted by the browser login flow)
keeps working unchanged; a raw EGI Check-in access token presented as a
Bearer token (Authorization header or cookie) is validated against the
Check-in userinfo endpoint with a short TTL cache.
"""

from unittest.mock import Mock, patch

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi_oauth2.claims import Claims
from fastapi_oauth2.client import OAuth2Client
from fastapi_oauth2.config import OAuth2Config
from fastapi_oauth2.middleware import Auth
from social_core.backends.egi_checkin import EGICheckinOpenIdConnect
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.testclient import TestClient

from app.middleware.dispatcher_auth import (
    DispatcherAuthBackend,
    _fetch_userinfo_claims,
)

_USERINFO_URL = (
    "https://aai-dev.egi.eu/auth/realms/egi/protocol/openid-connect/userinfo"
)

_CLAIMS = {"sub": "bob@egi.eu", "email": "bob@example.org", "name": "Bob"}


class _DevCheckin(EGICheckinOpenIdConnect):
    """Check-in dev backend with explicit endpoint URLs.

    OAuth2Core reads the class attributes first, so building the client for
    tests makes no .well-known discovery call."""

    CHECKIN_ENV = "dev"
    AUTHORIZATION_URL = (
        "https://aai-dev.egi.eu/auth/realms/egi/protocol/openid-connect/auth"
    )
    ACCESS_TOKEN_URL = (
        "https://aai-dev.egi.eu/auth/realms/egi/protocol/openid-connect/token"
    )


def _make_app(cache_ttl: float = 60.0) -> FastAPI:
    """Bare app: the real auth backend + a probe route exposing what the
    request routers consume (identity claims + provider access token)."""
    client = OAuth2Client(
        backend=_DevCheckin,
        client_id="client-id",
        client_secret="client-secret",
        claims=Claims(identity=lambda user: f"{user.provider}:{user.sub}"),
    )
    backend = DispatcherAuthBackend(
        OAuth2Config(clients=[client], jwt_secret="test-session-secret"),
        cache_ttl=cache_ttl,
    )

    app = FastAPI()
    app.add_middleware(AuthenticationMiddleware, backend=backend)

    @app.get("/whoami")
    def whoami(request: Request):
        user = request.scope.get("user") or {}
        auth = request.scope.get("auth")
        provider = getattr(auth, "provider", None)
        return JSONResponse(
            {
                "identity": user.get("identity"),
                "email": user.get("email"),
                "access_token": getattr(provider, "access_token", None),
            }
        )

    return app


def _session_token(sub: str = "alice@egi.eu") -> str:
    """A session token as minted by the browser login flow. Must be called
    after _make_app so the shared Auth class attrs are populated."""
    return Auth.jwt_create(
        {
            "sub": sub,
            "email": "alice@example.org",
            "name": "Alice",
            "provider": "egi-checkin",
            "scope": ["openid", "email"],
        }
    )


def _patch_userinfo(claims=None, side_effect=None):
    """Patch the synchronous userinfo fetch used by the backend."""
    return patch(
        "app.middleware.dispatcher_auth._fetch_userinfo_claims",
        **(
            {"return_value": claims}
            if claims is not None
            else {"side_effect": side_effect}
        ),
    )


# ---------------------------------------------------------------------------
# Session tokens (unchanged behavior)
# ---------------------------------------------------------------------------


def test_session_token_accepted_via_header():
    app = _make_app()
    token = _session_token()

    client = TestClient(app)
    resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json()["identity"] == "egi-checkin:alice@egi.eu"
    assert resp.json()["email"] == "alice@example.org"


def test_session_token_accepted_via_cookie():
    app = _make_app()
    token = _session_token()

    client = TestClient(app)
    client.cookies.set("Authorization", f"Bearer {token}")
    resp = client.get("/whoami")

    assert resp.status_code == 200
    assert resp.json()["identity"] == "egi-checkin:alice@egi.eu"


# ---------------------------------------------------------------------------
# Raw EGI access tokens (new behavior)
# ---------------------------------------------------------------------------


def test_raw_access_token_accepted_via_header():
    app = _make_app()

    with _patch_userinfo(claims=_CLAIMS):
        client = TestClient(app)
        resp = client.get("/whoami", headers={"Authorization": "Bearer raw-egi-token"})

    assert resp.status_code == 200
    assert resp.json()["identity"] == "egi-checkin:bob@egi.eu"
    assert resp.json()["email"] == "bob@example.org"
    # the per-request provider handle carries the caller's own token
    assert resp.json()["access_token"] == "raw-egi-token"


def test_raw_access_token_accepted_via_cookie():
    app = _make_app()

    with _patch_userinfo(claims={"sub": "carol@egi.eu"}):
        client = TestClient(app)
        client.cookies.set("Authorization", "Bearer raw-egi-token")
        resp = client.get("/whoami")

    assert resp.status_code == 200
    assert resp.json()["identity"] == "egi-checkin:carol@egi.eu"
    assert resp.json()["access_token"] == "raw-egi-token"


def test_identity_matches_across_token_types():
    """The same person via either credential resolves to the same owner
    identity ({provider}:{sub})."""
    app = _make_app()
    token = _session_token("dave@egi.eu")

    with _patch_userinfo(claims={"sub": "dave@egi.eu"}):
        client = TestClient(app)
        via_session = client.get(
            "/whoami", headers={"Authorization": f"Bearer {token}"}
        ).json()
        via_raw = client.get(
            "/whoami", headers={"Authorization": "Bearer raw-dave-token"}
        ).json()

    assert via_session["identity"] == via_raw["identity"] == "egi-checkin:dave@egi.eu"


def test_invalid_raw_token_rejected():
    app = _make_app()

    with _patch_userinfo(side_effect=requests.HTTPError("401 Unauthorized")):
        client = TestClient(app)
        resp = client.get("/whoami", headers={"Authorization": "Bearer bogus"})

    assert resp.status_code == 400


def test_userinfo_missing_sub_rejected():
    app = _make_app()

    with _patch_userinfo(claims={"email": "no-sub@example.org"}):
        client = TestClient(app)
        resp = client.get("/whoami", headers={"Authorization": "Bearer raw-token"})

    assert resp.status_code == 400


def test_userinfo_non_dict_payload_rejected():
    app = _make_app()

    with _patch_userinfo(claims=["not", "a", "dict"]):
        client = TestClient(app)
        resp = client.get("/whoami", headers={"Authorization": "Bearer raw-token"})

    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------


def test_userinfo_claims_are_cached():
    app = _make_app()
    fetch = Mock(return_value=dict(_CLAIMS))

    with patch("app.middleware.dispatcher_auth._fetch_userinfo_claims", fetch):
        client = TestClient(app)
        first = client.get("/whoami", headers={"Authorization": "Bearer raw-egi-token"})
        second = client.get(
            "/whoami", headers={"Authorization": "Bearer raw-egi-token"}
        )

    assert first.status_code == second.status_code == 200
    # one upstream userinfo call for both requests
    assert fetch.call_count == 1


def test_expired_cache_entry_refreshes():
    # negative TTL: every lookup is a miss
    app = _make_app(cache_ttl=-1.0)
    fetch = Mock(side_effect=[dict(_CLAIMS), requests.HTTPError("401")])

    with patch("app.middleware.dispatcher_auth._fetch_userinfo_claims", fetch):
        client = TestClient(app)
        first = client.get("/whoami", headers={"Authorization": "Bearer raw-egi-token"})
        second = client.get(
            "/whoami", headers={"Authorization": "Bearer raw-egi-token"}
        )

    assert first.status_code == 200
    assert second.status_code == 400
    assert fetch.call_count == 2


def test_failed_validation_is_not_cached():
    """A rejected token must not poison the cache for a later valid retry."""
    app = _make_app()
    fetch = Mock(side_effect=[requests.HTTPError("401"), dict(_CLAIMS)])

    with patch("app.middleware.dispatcher_auth._fetch_userinfo_claims", fetch):
        client = TestClient(app)
        first = client.get("/whoami", headers={"Authorization": "Bearer raw-egi-token"})
        second = client.get(
            "/whoami", headers={"Authorization": "Bearer raw-egi-token"}
        )

    assert first.status_code == 400
    assert second.status_code == 200
    assert fetch.call_count == 2


# ---------------------------------------------------------------------------
# The userinfo fetch itself
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_userinfo_claims_sends_bearer_header():
    with patch(
        "app.middleware.dispatcher_auth.requests.get",
        return_value=_FakeResponse({"sub": "x@egi.eu"}),
    ) as mock_get:
        claims = _fetch_userinfo_claims("the-token")

    assert claims == {"sub": "x@egi.eu"}
    assert mock_get.call_args[0][0] == _USERINFO_URL
    assert mock_get.call_args[1]["headers"]["Authorization"] == "Bearer the-token"


# ---------------------------------------------------------------------------
# Anonymous requests
# ---------------------------------------------------------------------------


def test_no_credentials_is_anonymous():
    client = TestClient(_make_app())
    resp = client.get("/whoami")

    assert resp.status_code == 200
    assert resp.json() == {"identity": None, "email": None, "access_token": None}
