"""Shared fixtures for the unit tests (auth and elsewhere)."""

from types import SimpleNamespace

import pytest

from app.config import settings
from fixtures.jwt_helper import generate_rsa_key, patch_jwks


@pytest.fixture(autouse=True)
def dev_env():
    """Pin the Check-in environment for every unit test (guards against
    an EGI_CHECKIN_ENV variable overriding the default)."""
    original = settings.egi_checkin_env
    settings.egi_checkin_env = "dev"
    yield
    settings.egi_checkin_env = original


@pytest.fixture
def key(monkeypatch):
    """A locally-generated RSA key, with app.security._jwks patched to
    resolve it — verification works offline against tokens it signs."""
    rsa_key = generate_rsa_key()
    patch_jwks(monkeypatch, rsa_key)
    return rsa_key


@pytest.fixture
def stub_request():
    """A minimal Request stand-in (headers/cookies) for the credential
    tests."""

    def _make(headers=None, cookies=None):
        return SimpleNamespace(headers=headers or {}, cookies=cookies or {})

    return _make
