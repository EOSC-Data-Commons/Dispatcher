"""Unit tests for vault.py — EGI Secret Store client (async, httpx)."""

import httpx
import pytest
from unittest.mock import patch

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
        return_value=TokenUser(sub="user@example.com", name="Test User"),
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


_LOGIN_URL = "https://vault.example.com/v1/auth/jwt/login"
_SECRET_V1 = "https://vault.example.com/v1/secrets/users/user%40example.com/api-keys"
_SECRET_V2 = (
    "https://vault.example.com/v1/secrets/data/users/user%40example.com/api-keys"
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_retrieves_secret_kv_v1(httpx_mock, mock_extract_user):
    """Secret is successfully retrieved using KV v1."""
    settings.vault_kv_version = 1

    httpx_mock.add_response(
        method="POST",
        url=_LOGIN_URL,
        json={"auth": {"client_token": "vault-client-token-123"}},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{_SECRET_V1}/vip",
        json={"data": {"value": "my-api-key"}},
    )

    result = await vault_get_api_key("access-token", "vip")

    assert result == "my-api-key"

    requests = httpx_mock.get_requests()
    # Verify JWT login call
    login_req = requests[0]
    assert login_req.method == "POST"
    assert login_req.read() is not None
    import json as _json

    assert _json.loads(login_req.read()) == {
        "jwt": "access-token",
        "role": "test-role",
    }

    # Verify GET call uses the vault token
    get_req = requests[1]
    assert get_req.method == "GET"
    assert get_req.headers["X-Vault-Token"] == "vault-client-token-123"


async def test_retrieves_secret_kv_v2(httpx_mock, mock_extract_user):
    """Secret is successfully retrieved using KV v2 (data wrapped under data.data)."""
    settings.vault_kv_version = 2

    httpx_mock.add_response(
        method="POST",
        url=_LOGIN_URL,
        json={"auth": {"client_token": "vault-token"}},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{_SECRET_V2}/my-key",
        json={"data": {"data": {"value": "my-kv2-key"}}},
    )

    result = await vault_get_api_key("access-token", "my-key")

    assert result == "my-kv2-key"

    # KV v2 path includes /data/ segment
    get_req = httpx_mock.get_requests()[1]
    assert "/data/" in str(get_req.url)


async def test_vault_auth_failure_raises_vault_error(httpx_mock, mock_extract_user):
    """Vault JWT auth returning non-200 raises VaultError."""
    httpx_mock.add_response(method="POST", url=_LOGIN_URL, status_code=403)

    with pytest.raises(VaultError) as exc:
        await vault_get_api_key("bad-token", "vip")

    assert "Vault authentication failed" in str(exc.value)


async def test_vault_auth_request_exception_raises_vault_error(
    httpx_mock, mock_extract_user
):
    """Vault JWT auth network failure raises VaultError."""
    for _ in range(4):  # transport errors are retried
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"), method="POST", url=_LOGIN_URL
        )

    with pytest.raises(VaultError) as exc:
        await vault_get_api_key("token", "vip")

    assert "Vault authentication request failed" in str(exc.value)


async def test_access_denied_raises_vre_authentication_error(
    httpx_mock, mock_extract_user
):
    """401 or 403 on secret GET raises VREAuthenticationError."""
    for status in (401, 403):
        httpx_mock.add_response(
            method="POST",
            url=_LOGIN_URL,
            json={"auth": {"client_token": "vault-token"}},
        )
        httpx_mock.add_response(
            method="GET", url=f"{_SECRET_V1}/vip", status_code=status
        )

        with pytest.raises(VREAuthenticationError) as exc:
            await vault_get_api_key("token", "vip")

        assert "Vault access denied" in str(exc.value)
        assert str(status) in str(exc.value)


async def test_unexpected_status_raises_vault_error(httpx_mock, mock_extract_user):
    """Unexpected non-200/401/403/404 status raises VaultError."""
    httpx_mock.add_response(
        method="POST",
        url=_LOGIN_URL,
        json={"auth": {"client_token": "vault-token"}},
    )
    httpx_mock.add_response(method="GET", url=f"{_SECRET_V1}/vip", status_code=418)

    with pytest.raises(VaultError) as exc:
        await vault_get_api_key("token", "vip")

    assert "Vault read failed" in str(exc.value)


async def test_missing_value_field_raises_vre_configuration_error(
    httpx_mock, mock_extract_user
):
    """Secret data missing 'value' field raises VREConfigurationError."""
    httpx_mock.add_response(
        method="POST",
        url=_LOGIN_URL,
        json={"auth": {"client_token": "vault-token"}},
    )
    httpx_mock.add_response(
        method="GET", url=f"{_SECRET_V1}/vip", json={"data": {}}  # no "value" key
    )

    with pytest.raises(VREConfigurationError) as exc:
        await vault_get_api_key("token", "vip")

    assert "contains no 'value' field" in str(exc.value)


async def test_secret_not_found_raises_vre_configuration_error(
    httpx_mock, mock_extract_user
):
    """404 on secret GET raises VREConfigurationError."""
    httpx_mock.add_response(
        method="POST",
        url=_LOGIN_URL,
        json={"auth": {"client_token": "vault-token"}},
    )
    httpx_mock.add_response(
        method="GET", url=f"{_SECRET_V1}/missing-key", status_code=404
    )

    with pytest.raises(VREConfigurationError) as exc:
        await vault_get_api_key("token", "missing-key")

    assert "not found in vault" in str(exc.value)
    assert "missing-key" in str(exc.value)
    assert "user@example.com" in str(exc.value)


async def test_read_request_exception_raises_vault_error(httpx_mock, mock_extract_user):
    """Network failure during secret GET raises VaultError."""
    httpx_mock.add_response(
        method="POST",
        url=_LOGIN_URL,
        json={"auth": {"client_token": "vault-token"}},
    )
    for _ in range(4):  # transport errors are retried
        httpx_mock.add_exception(
            httpx.ConnectError("Connection reset"),
            method="GET",
            url=f"{_SECRET_V1}/vip",
        )

    with pytest.raises(VaultError) as exc:
        await vault_get_api_key("token", "vip")

    assert "Vault read request failed" in str(exc.value)


async def test_user_sub_used_in_path(httpx_mock, mock_extract_user):
    """The user's sub claim is URL-encoded when building the KV path."""
    httpx_mock.add_response(
        method="POST",
        url=_LOGIN_URL,
        json={"auth": {"client_token": "vault-token"}},
    )
    httpx_mock.add_response(
        method="GET", url=f"{_SECRET_V1}/vip", json={"data": {"value": "key"}}
    )

    await vault_get_api_key("token", "vip")

    get_req = httpx_mock.get_requests()[1]
    assert "user%40example.com" in str(get_req.url)


def test_token_user_exposes_sub_claim():
    """TokenUser.sub carries the verified token's sub claim — the
    email-shaped EGI user id — which callers use as the user identity."""
    user = TokenUser(sub="sub@example.com", name="Name")
    assert user.sub == "sub@example.com"
