"""Unit tests for app.security — local JWT verification (Auth Design 1)."""

from types import SimpleNamespace

import jwt as pyjwt
import pytest
from fastapi import HTTPException

from app import security
from app.config import settings
from fixtures.jwt_helper import (
    DEV_ISSUER,
    generate_rsa_key,
    make_token,
    patch_jwks,
)


@pytest.fixture(autouse=True)
def dev_env():
    original = settings.egi_checkin_env
    settings.egi_checkin_env = "dev"
    yield
    settings.egi_checkin_env = original


@pytest.fixture
def key():
    return generate_rsa_key()


@pytest.fixture
def jwks(key, monkeypatch):
    patch_jwks(monkeypatch, key)
    return key


# ---------------------------------------------------------------------------
# verify()
# ---------------------------------------------------------------------------


def test_verify_accepts_valid_token(jwks, key):
    claims = security.verify(make_token(key))
    assert claims["sub"].endswith("@egi.eu")
    assert claims["iss"] == DEV_ISSUER


def test_verify_rejects_wrong_issuer(jwks, key):
    token = make_token(key, issuer="https://evil.example/realms/main")
    with pytest.raises(pyjwt.InvalidIssuerError):
        security.verify(token)


def test_verify_rejects_expired_token(jwks, key):
    token = make_token(key, lifetime=-1000)
    with pytest.raises(pyjwt.ExpiredSignatureError):
        security.verify(token)


def test_verify_rejects_foreign_signature(jwks, key):
    # Signed by a different key than the (patched) JWKS publishes.
    token = make_token(generate_rsa_key())
    with pytest.raises(pyjwt.InvalidSignatureError):
        security.verify(token)


def test_verify_requires_core_claims(jwks, key):
    with pytest.raises(pyjwt.PyJWTError):
        security.verify(make_token(key, drop=("sub",)))


# ---------------------------------------------------------------------------
# access_token_from_request()
# ---------------------------------------------------------------------------


def _request(headers=None, cookies=None):
    return SimpleNamespace(headers=headers or {}, cookies=cookies or {})


def test_token_from_header():
    req = _request(headers={"Authorization": "Bearer abc"})
    assert security.access_token_from_request(req) == "abc"


def test_token_from_cookie():
    # The library sets the cookie value with the Bearer prefix.
    req = _request(cookies={"Authorization": "Bearer abc"})
    assert security.access_token_from_request(req) == "abc"


def test_header_takes_precedence_over_cookie():
    req = _request(
        headers={"Authorization": "Bearer header-token"},
        cookies={"Authorization": "Bearer cookie-token"},
    )
    assert security.access_token_from_request(req) == "header-token"


def test_no_token_returns_none():
    assert security.access_token_from_request(_request()) is None


# ---------------------------------------------------------------------------
# get_principal()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_principal_builds_principal(jwks, key):
    token = make_token(key)
    principal = await security.get_principal(
        _request(headers={"Authorization": f"Bearer {token}"})
    )

    assert principal.subject.endswith("@egi.eu")
    assert principal.raw_token == token
    assert "offline_access" in principal.scopes


@pytest.mark.asyncio
async def test_get_principal_401_without_token():
    with pytest.raises(HTTPException) as exc:
        await security.get_principal(_request())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_principal_401_expired_with_error_code(jwks, key):
    token = make_token(key, lifetime=-1000)
    with pytest.raises(HTTPException) as exc:
        await security.get_principal(
            _request(headers={"Authorization": f"Bearer {token}"})
        )
    assert exc.value.status_code == 401
    assert 'error="expired_token"' in exc.value.headers["WWW-Authenticate"]
