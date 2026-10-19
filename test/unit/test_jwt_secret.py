"""get_jwt_secret: fail-closed resolution of the HS256 session-token key.

An empty jwt_secret lets anyone forge fastapi-oauth2 session tokens
(python-jose verifies HS256 with an empty key), so the resolver must
never hand back "". The value is always provided by the deployment
(ansible vault / local host_vars) — the app never generates one.
"""

import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi_oauth2.config import OAuth2Config
from fastapi_oauth2.middleware import OAuth2Middleware
from jose import jwt as jose_jwt
from starlette.testclient import TestClient

from app.config import get_jwt_secret


def test_configured_secret_is_returned():
    with patch("app.config.settings") as settings:
        settings.jwt_secret = "a-real-secret"
        assert get_jwt_secret() == "a-real-secret"


def test_empty_secret_fails_closed():
    with patch("app.config.settings") as settings:
        settings.jwt_secret = ""
        with pytest.raises(RuntimeError, match="jwt_secret"):
            get_jwt_secret()


def test_empty_key_forged_session_token_rejected():
    """Regression for the empty-jwt_secret hole: python-jose verifies HS256
    with an EMPTY key, so a token forged with key "" must not authenticate
    against an app configured with a real jwt_secret. (Production used to
    omit jwt_secret, which defaulted to "" — this test pins the fix.)"""
    app = FastAPI()
    app.add_middleware(
        OAuth2Middleware,
        config=OAuth2Config(clients=[], jwt_secret="test-session-secret"),
    )

    forged = jose_jwt.encode(
        {
            "sub": "mallory@egi.eu",
            "email": "mallory@example.org",
            "provider": "egi-checkin",
            "scope": ["openid", "email"],
            "exp": int(time.time()) + 3600,
        },
        "",
        algorithm="HS256",
    )

    client = TestClient(app)
    resp = client.get("/docs", headers={"Authorization": f"Bearer {forged}"})

    assert resp.status_code == 400
