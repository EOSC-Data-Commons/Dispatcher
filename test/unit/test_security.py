"""Unit tests for app.security — local JWT verification (Auth Design 1)."""

import jwt as pyjwt
import pytest

from app import security
from fixtures.jwt_helper import (
    DEV_ISSUER,
    generate_rsa_key,
    make_token,
)

# ---------------------------------------------------------------------------
# verify()
# ---------------------------------------------------------------------------


def test_verify_accepts_valid_token(key):
    claims = security.verify(make_token(key))
    assert claims["sub"].endswith("@egi.eu")
    assert claims["iss"] == DEV_ISSUER


def test_verify_rejects_wrong_issuer(key):
    token = make_token(key, issuer="https://evil.example/realms/main")
    with pytest.raises(pyjwt.InvalidIssuerError):
        security.verify(token)


def test_verify_rejects_expired_token(key):
    token = make_token(key, lifetime=-1000)
    with pytest.raises(pyjwt.ExpiredSignatureError):
        security.verify(token)


def test_verify_rejects_foreign_signature(key):
    # Signed by a different key than the (patched) JWKS publishes.
    token = make_token(generate_rsa_key())
    with pytest.raises(pyjwt.InvalidSignatureError):
        security.verify(token)


def test_verify_requires_core_claims(key):
    with pytest.raises(pyjwt.PyJWTError):
        security.verify(make_token(key, drop=("sub",)))


# ---------------------------------------------------------------------------
# access_token_from_request()
# ---------------------------------------------------------------------------


def test_token_from_header(stub_request):
    req = stub_request(headers={"Authorization": "Bearer abc"})
    assert security.access_token_from_request(req) == "abc"


def test_token_from_cookie(stub_request):
    # The library sets the cookie value with the Bearer prefix.
    req = stub_request(cookies={security.SESSION_COOKIE: "Bearer abc"})
    assert security.access_token_from_request(req) == "abc"


def test_header_takes_precedence_over_cookie(stub_request):
    req = stub_request(
        headers={"Authorization": "Bearer header-token"},
        cookies={security.SESSION_COOKIE: "Bearer cookie-token"},
    )
    assert security.access_token_from_request(req) == "header-token"


def test_no_token_returns_none(stub_request):
    assert security.access_token_from_request(stub_request()) is None
