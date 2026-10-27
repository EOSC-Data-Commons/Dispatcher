"""Unit tests for token_utils.py — EGI Check-in user identity extraction.

Since Auth Design 1, identity is extracted by verifying the JWT locally
(no userinfo round-trip); tests sign real RS256 tokens with a local key.
"""

import jwt as pyjwt
import pytest

from app.config import settings
from app.exceptions import VREAuthenticationError
from app.vres.utils.token_utils import TokenUser, extract_user_from_token
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


# ---------------------------------------------------------------------------
# TokenUser tests
# ---------------------------------------------------------------------------


class TestTokenUser:
    """Tests for the TokenUser dataclass."""

    def test_creates_with_email_and_name(self):
        user = TokenUser(email="jdoe@example.com", name="John Doe")
        assert user.email == "jdoe@example.com"
        assert user.name == "John Doe"

    def test_creates_with_name_none(self):
        user = TokenUser(email="jdoe@example.com", name=None)
        assert user.email == "jdoe@example.com"
        assert user.name is None

    def test_has_no_sub_attribute(self):
        """Regression: TokenUser must not expose a 'sub' field.

        The 'sub' OIDC claim is stored as 'email', not as a separate field.
        """
        user = TokenUser(email="sub@example.com", name="Name")
        assert not hasattr(user, "sub")


# ---------------------------------------------------------------------------
# extract_user_from_token tests
# ---------------------------------------------------------------------------


def test_extracts_email_and_name(key):
    """Successful extraction returns TokenUser with both fields."""
    user = extract_user_from_token(make_token(key))

    assert user.email.endswith("@egi.eu")
    assert user.name == user.email  # preferred_username is the same id


def test_extracts_email_without_name(key):
    """When preferred_username is missing, name is None."""
    token = make_token(key, drop=("preferred_username",))

    user = extract_user_from_token(token)

    assert user.email.endswith("@egi.eu")
    assert user.name is None


def test_raises_on_expired_token(key):
    token = make_token(key, lifetime=-1000)

    with pytest.raises(VREAuthenticationError) as exc:
        extract_user_from_token(token)

    assert "Failed to fetch user identity" in str(exc.value)


def test_raises_on_garbage_token():
    with pytest.raises(VREAuthenticationError):
        extract_user_from_token("not-a-jwt")


def test_raises_on_wrong_issuer(key):
    token = make_token(key, issuer="https://evil.example/realms/main")

    with pytest.raises(VREAuthenticationError):
        extract_user_from_token(token)


def test_raises_on_missing_sub(key):
    """A token without 'sub' is rejected by verification itself."""
    token = make_token(key, drop=("sub",))

    with pytest.raises(VREAuthenticationError):
        extract_user_from_token(token)
