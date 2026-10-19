"""Tests for DispatcherAuthBackend: dual credentials at the auth middleware.

The fastapi-oauth2 session token (HS256, minted by the browser login flow)
keeps working unchanged; a raw EGI Check-in access token presented as a
Bearer token (Authorization header or cookie) is validated against the
Check-in userinfo endpoint with a short TTL cache.

The userinfo endpoint is faked at the HTTP transport (requests_mock), so
the tests exercise the real fetch code — URL, Bearer header, status
handling — instead of patching module internals.
"""

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


def test_raw_access_token_accepted_via_header(requests_mock):
    app = _make_app()
    requests_mock.get(_USERINFO_URL, json=_CLAIMS)

    client = TestClient(app)
    resp = client.get("/whoami", headers={"Authorization": "Bearer raw-egi-token"})

    assert resp.status_code == 200
    assert resp.json()["identity"] == "egi-checkin:bob@egi.eu"
    assert resp.json()["email"] == "bob@example.org"
    # the per-request provider handle carries the caller's own token
    assert resp.json()["access_token"] == "raw-egi-token"


def test_raw_access_token_accepted_via_cookie(requests_mock):
    app = _make_app()
    requests_mock.get(_USERINFO_URL, json={"sub": "carol@egi.eu"})

    client = TestClient(app)
    client.cookies.set("Authorization", "Bearer raw-egi-token")
    resp = client.get("/whoami")

    assert resp.status_code == 200
    assert resp.json()["identity"] == "egi-checkin:carol@egi.eu"
    assert resp.json()["access_token"] == "raw-egi-token"


def test_identity_matches_across_token_types(requests_mock):
    """The same person via either credential resolves to the same owner
    identity ({provider}:{sub})."""
    app = _make_app()
    token = _session_token("dave@egi.eu")
    requests_mock.get(_USERINFO_URL, json={"sub": "dave@egi.eu"})

    client = TestClient(app)
    via_session = client.get(
        "/whoami", headers={"Authorization": f"Bearer {token}"}
    ).json()
    via_raw = client.get(
        "/whoami", headers={"Authorization": "Bearer raw-dave-token"}
    ).json()

    assert via_session["identity"] == via_raw["identity"] == "egi-checkin:dave@egi.eu"


def test_invalid_raw_token_rejected(requests_mock):
    app = _make_app()
    requests_mock.get(_USERINFO_URL, status_code=401)

    client = TestClient(app)
    resp = client.get("/whoami", headers={"Authorization": "Bearer bogus"})

    assert resp.status_code == 400


def test_userinfo_missing_sub_rejected(requests_mock):
    app = _make_app()
    requests_mock.get(_USERINFO_URL, json={"email": "no-sub@example.org"})

    client = TestClient(app)
    resp = client.get("/whoami", headers={"Authorization": "Bearer raw-token"})

    assert resp.status_code == 400


def test_userinfo_non_dict_payload_rejected(requests_mock):
    app = _make_app()
    requests_mock.get(_USERINFO_URL, json=["not", "a", "dict"])

    client = TestClient(app)
    resp = client.get("/whoami", headers={"Authorization": "Bearer raw-token"})

    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------


def test_userinfo_claims_are_cached(requests_mock):
    app = _make_app()
    userinfo = requests_mock.get(_USERINFO_URL, json=dict(_CLAIMS))

    client = TestClient(app)
    first = client.get("/whoami", headers={"Authorization": "Bearer raw-egi-token"})
    second = client.get("/whoami", headers={"Authorization": "Bearer raw-egi-token"})

    assert first.status_code == second.status_code == 200
    # one upstream userinfo call for both requests
    assert userinfo.call_count == 1


def test_expired_cache_entry_refreshes(requests_mock):
    # negative TTL: every lookup is a miss
    app = _make_app(cache_ttl=-1.0)
    userinfo = requests_mock.get(
        _USERINFO_URL,
        response_list=[{"json": dict(_CLAIMS)}, {"status_code": 401}],
    )

    client = TestClient(app)
    first = client.get("/whoami", headers={"Authorization": "Bearer raw-egi-token"})
    second = client.get("/whoami", headers={"Authorization": "Bearer raw-egi-token"})

    assert first.status_code == 200
    assert second.status_code == 400
    assert userinfo.call_count == 2


def test_failed_validation_is_not_cached(requests_mock):
    """A rejected token must not poison the cache for a later valid retry."""
    app = _make_app()
    userinfo = requests_mock.get(
        _USERINFO_URL,
        response_list=[{"status_code": 401}, {"json": dict(_CLAIMS)}],
    )

    client = TestClient(app)
    first = client.get("/whoami", headers={"Authorization": "Bearer raw-egi-token"})
    second = client.get("/whoami", headers={"Authorization": "Bearer raw-egi-token"})

    assert first.status_code == 400
    assert second.status_code == 200
    assert userinfo.call_count == 2


# ---------------------------------------------------------------------------
# The userinfo fetch itself
# ---------------------------------------------------------------------------


def test_fetch_userinfo_claims_sends_bearer_header(requests_mock):
    requests_mock.get(_USERINFO_URL, json={"sub": "x@egi.eu"})

    claims = _fetch_userinfo_claims("the-token")

    assert claims == {"sub": "x@egi.eu"}
    sent = requests_mock.request_history[0]
    assert sent.method == "GET"
    assert sent.url == _USERINFO_URL
    assert sent.headers["Authorization"] == "Bearer the-token"


# ---------------------------------------------------------------------------
# Anonymous requests
# ---------------------------------------------------------------------------


def test_no_credentials_is_anonymous():
    client = TestClient(_make_app())
    resp = client.get("/whoami")

    assert resp.status_code == 200
    assert resp.json() == {"identity": None, "email": None, "access_token": None}
