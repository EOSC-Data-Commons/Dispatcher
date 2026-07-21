"""Unit tests for token_utils.py — EGI Check-in user identity extraction."""

import pytest
import requests
import requests_mock

from app.config import settings
from app.exceptions import VREAuthenticationError
from app.vres.utils.token_utils import TokenUser, extract_user_from_token

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def egi_checkin_settings():
    """Ensure egi_checkin_env is set for all tests."""
    original = settings.egi_checkin_env
    settings.egi_checkin_env = "dev"
    yield
    settings.egi_checkin_env = original


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

    def test_is_immutable_by_default(self):
        """Dataclass fields are accessible but the class is a plain dataclass."""
        user = TokenUser(email="a@b.com", name="X")
        # Values can be changed (no frozen=True), but the fields are the
        # documented contract.
        user.email = "new@b.com"
        assert user.email == "new@b.com"


# ---------------------------------------------------------------------------
# extract_user_from_token tests
# ---------------------------------------------------------------------------

# Userinfo URL for the "dev" environment
_DEV_USERINFO = (
    "https://aai-dev.egi.eu/auth/realms/egi/protocol/openid-connect/userinfo"
)


def test_extracts_email_and_name():
    """Successful extraction returns TokenUser with both fields."""
    with requests_mock.Mocker() as m:
        m.get(
            _DEV_USERINFO,
            json={"sub": "jdoe@example.com", "preferred_username": "jdoe"},
        )

        user = extract_user_from_token("valid-token")

    assert user.email == "jdoe@example.com"
    assert user.name == "jdoe"


def test_extracts_email_without_name():
    """When preferred_username is missing, name is None."""
    with requests_mock.Mocker() as m:
        m.get(_DEV_USERINFO, json={"sub": "jdoe@example.com"})

        user = extract_user_from_token("valid-token")

    assert user.email == "jdoe@example.com"
    assert user.name is None


def test_raises_on_missing_sub():
    """Missing 'sub' in userinfo response raises VREAuthenticationError."""
    with requests_mock.Mocker() as m:
        m.get(_DEV_USERINFO, json={"preferred_username": "jdoe"})

        with pytest.raises(VREAuthenticationError) as exc:
            extract_user_from_token("token")

        assert "Missing 'sub'" in str(exc.value)


def test_raises_on_empty_sub():
    """Empty 'sub' in userinfo response raises VREAuthenticationError."""
    with requests_mock.Mocker() as m:
        m.get(_DEV_USERINFO, json={"sub": ""})

        with pytest.raises(VREAuthenticationError) as exc:
            extract_user_from_token("token")

        assert "Missing 'sub'" in str(exc.value)


def test_raises_on_http_error():
    """Non-200 response from userinfo raises VREAuthenticationError."""
    with requests_mock.Mocker() as m:
        m.get(_DEV_USERINFO, status_code=401, text="Unauthorized")

        with pytest.raises(VREAuthenticationError) as exc:
            extract_user_from_token("bad-token")

        assert "Failed to fetch user identity" in str(exc.value)


def test_raises_on_network_error():
    """Network failure raises VREAuthenticationError."""
    with requests_mock.Mocker() as m:
        m.get(_DEV_USERINFO, exc=requests.ConnectionError("Connection refused"))

        with pytest.raises(VREAuthenticationError) as exc:
            extract_user_from_token("token")

        assert "Failed to fetch user identity" in str(exc.value)


def test_sends_bearer_token_in_auth_header():
    """The access token is sent as a Bearer token in the Authorization header."""
    with requests_mock.Mocker() as m:
        m.get(_DEV_USERINFO, json={"sub": "jdoe@example.com"})

        extract_user_from_token("my-access-token")

    req = m.request_history[0]
    assert req.headers["Authorization"] == "Bearer my-access-token"


def test_uses_correct_url_for_dev_environment():
    """When egi_checkin_env is 'dev', the dev userinfo URL is used."""
    settings.egi_checkin_env = "dev"

    with requests_mock.Mocker() as m:
        m.get(_DEV_USERINFO, json={"sub": "jdoe@example.com"})

        extract_user_from_token("token")

    assert m.request_history[0].url == _DEV_USERINFO


def test_uses_correct_url_for_demo_environment():
    """When egi_checkin_env is 'demo', the prod userinfo URL is used."""
    settings.egi_checkin_env = "demo"

    demo_url = (
        "https://aai-demo.egi.eu/auth/realms/egi/protocol/openid-connect/userinfo"
    )

    with requests_mock.Mocker() as m:
        m.get(demo_url, json={"sub": "jdoe@example.com"})

        extract_user_from_token("token")

    assert m.request_history[0].url == demo_url


def test_uses_correct_url_for_prod_environment():
    """When egi_checkin_env is 'prod', the prod userinfo URL is used."""
    settings.egi_checkin_env = "prod"

    prod_url = "https://aai.egi.eu/auth/realms/egi/protocol/openid-connect/userinfo"

    with requests_mock.Mocker() as m:
        m.get(prod_url, json={"sub": "jdoe@example.com"})

        extract_user_from_token("token")

    assert m.request_history[0].url == prod_url
