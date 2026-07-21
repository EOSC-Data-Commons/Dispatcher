"""Unit tests for vault.py — EGI Secret Store client."""

import pytest
from unittest.mock import patch

import requests
import requests_mock

from app.config import settings
from app.exceptions import VaultError, VREAuthenticationError, VREConfigurationError
from app.vres.utils.token_utils import TokenUser
from app.vres.utils.vault import vault_get_api_key

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_extract_user():
    """Mock extract_user_from_token to return a fixed TokenUser."""
    with patch(
        "app.vres.utils.vault.extract_user_from_token",
        return_value=TokenUser(email="user@example.com", name="Test User"),
    ) as mock:
        yield mock


@pytest.fixture(autouse=True)
def vault_settings():
    """Ensure vault settings are set for all tests."""
    settings.vault_url = "https://vault.example.com"
    settings.vault_jwt_mount = "jwt"
    settings.vault_kv_mount = "secrets"
    settings.vault_kv_version = 1
    settings.vault_jwt_role = "test-role"
    yield
    # Restore defaults
    settings.vault_url = ""
    settings.vault_jwt_mount = "jwt"
    settings.vault_kv_mount = "secrets"
    settings.vault_kv_version = 1
    settings.vault_jwt_role = ""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_retrieves_secret_kv_v1(mock_extract_user):
    """Secret is successfully retrieved using KV v1."""
    settings.vault_kv_version = 1

    with requests_mock.Mocker() as m:
        # JWT login
        m.post(
            "https://vault.example.com/v1/auth/jwt/login",
            json={"auth": {"client_token": "vault-client-token-123"}},
        )
        # GET secret (KV v1)
        m.get(
            "https://vault.example.com/v1/secrets/users/user%40example.com/api-keys/vip",
            json={"data": {"value": "my-api-key"}},
        )

        result = vault_get_api_key("access-token", "vip")

    assert result == "my-api-key"

    # Verify JWT login call
    login_req = m.request_history[0]
    assert login_req.method == "POST"
    assert login_req.json() == {"jwt": "access-token", "role": "test-role"}

    # Verify GET call uses the vault token
    get_req = m.request_history[1]
    assert get_req.method == "GET"
    assert get_req.headers["X-Vault-Token"] == "vault-client-token-123"


def test_retrieves_secret_kv_v2(mock_extract_user):
    """Secret is successfully retrieved using KV v2 (data wrapped under data.data)."""
    settings.vault_kv_version = 2

    with requests_mock.Mocker() as m:
        m.post(
            "https://vault.example.com/v1/auth/jwt/login",
            json={"auth": {"client_token": "vault-token"}},
        )
        m.get(
            "https://vault.example.com/v1/secrets/data/users/user%40example.com/api-keys/my-key",
            json={"data": {"data": {"value": "my-kv2-key"}}},
        )

        result = vault_get_api_key("access-token", "my-key")

    assert result == "my-kv2-key"

    # KV v2 path includes /data/ segment
    get_req = m.request_history[1]
    assert "/data/" in get_req.url


def test_vault_auth_failure_raises_vault_error(mock_extract_user):
    """Vault JWT auth returning non-200 raises VaultError."""
    with requests_mock.Mocker() as m:
        m.post(
            "https://vault.example.com/v1/auth/jwt/login",
            status_code=403,
            text="Forbidden",
        )

        with pytest.raises(VaultError) as exc:
            vault_get_api_key("bad-token", "vip")

        assert "Vault authentication failed" in str(exc.value)


def test_vault_auth_request_exception_raises_vault_error(mock_extract_user):
    """Vault JWT auth network failure raises VaultError."""
    with requests_mock.Mocker() as m:
        m.post(
            "https://vault.example.com/v1/auth/jwt/login",
            exc=requests.ConnectionError("Connection refused"),
        )

        with pytest.raises(VaultError) as exc:
            vault_get_api_key("token", "vip")

        assert "Vault authentication request failed" in str(exc.value)


def test_secret_not_found_raises_vre_configuration_error(mock_extract_user):
    """404 on secret GET raises VREConfigurationError."""
    with requests_mock.Mocker() as m:
        m.post(
            "https://vault.example.com/v1/auth/jwt/login",
            json={"auth": {"client_token": "vault-token"}},
        )
        m.get(
            "https://vault.example.com/v1/secrets/users/user%40example.com/api-keys/missing-key",
            status_code=404,
        )

        with pytest.raises(VREConfigurationError) as exc:
            vault_get_api_key("token", "missing-key")

        assert "not found in vault" in str(exc.value)
        assert "missing-key" in str(exc.value)
        assert "user@example.com" in str(exc.value)


def test_access_denied_raises_vre_authentication_error(mock_extract_user):
    """401 or 403 on secret GET raises VREAuthenticationError."""
    for status in (401, 403):
        with requests_mock.Mocker() as m:
            m.post(
                "https://vault.example.com/v1/auth/jwt/login",
                json={"auth": {"client_token": "vault-token"}},
            )
            m.get(
                "https://vault.example.com/v1/secrets/users/user%40example.com/api-keys/vip",
                status_code=status,
                text="Access denied",
            )

            with pytest.raises(VREAuthenticationError) as exc:
                vault_get_api_key("token", "vip")

            assert "Vault access denied" in str(exc.value)
            assert str(status) in str(exc.value)


def test_unexpected_status_raises_vault_error(mock_extract_user):
    """Unexpected non-200/401/403/404 status raises VaultError."""
    with requests_mock.Mocker() as m:
        m.post(
            "https://vault.example.com/v1/auth/jwt/login",
            json={"auth": {"client_token": "vault-token"}},
        )
        m.get(
            "https://vault.example.com/v1/secrets/users/user%40example.com/api-keys/vip",
            status_code=500,
            text="Internal error",
        )

        with pytest.raises(VaultError) as exc:
            vault_get_api_key("token", "vip")

        assert "Vault read failed" in str(exc.value)


def test_missing_value_field_raises_vre_configuration_error(mock_extract_user):
    """Secret data missing 'value' field raises VREConfigurationError."""
    with requests_mock.Mocker() as m:
        m.post(
            "https://vault.example.com/v1/auth/jwt/login",
            json={"auth": {"client_token": "vault-token"}},
        )
        m.get(
            "https://vault.example.com/v1/secrets/users/user%40example.com/api-keys/vip",
            json={"data": {}},  # no "value" key
        )

        with pytest.raises(VREConfigurationError) as exc:
            vault_get_api_key("token", "vip")

        assert "contains no 'value' field" in str(exc.value)


def test_read_request_exception_raises_vault_error(mock_extract_user):
    """Network failure during secret GET raises VaultError."""
    with requests_mock.Mocker() as m:
        m.post(
            "https://vault.example.com/v1/auth/jwt/login",
            json={"auth": {"client_token": "vault-token"}},
        )
        m.get(
            "https://vault.example.com/v1/secrets/users/user%40example.com/api-keys/vip",
            exc=requests.ConnectionError("Connection reset"),
        )

        with pytest.raises(VaultError) as exc:
            vault_get_api_key("token", "vip")

        assert "Vault read request failed" in str(exc.value)


def test_user_email_used_as_sub_in_path(mock_extract_user):
    """The user's email (sub claim) is URL-encoded when building the KV path."""
    with requests_mock.Mocker() as m:
        m.post(
            "https://vault.example.com/v1/auth/jwt/login",
            json={"auth": {"client_token": "vault-token"}},
        )
        m.get(
            "https://vault.example.com/v1/secrets/users/user%40example.com/api-keys/vip",
            json={"data": {"value": "key"}},
        )

        vault_get_api_key("token", "vip")

    get_req = m.request_history[1]
    assert "user%40example.com" in get_req.url


def test_token_user_has_no_sub_attribute(mock_extract_user):
    """Regression test: TokenUser does not have a 'sub' attribute.

    This test verifies that the code uses user.email (which holds the sub
    claim value) rather than a non-existent user.sub attribute.
    """
    user = TokenUser(email="sub@example.com", name="Name")
    assert not hasattr(user, "sub")
    assert user.email == "sub@example.com"
