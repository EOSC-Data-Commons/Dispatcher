"""EGI Secret Store (HashiCorp Vault) client for per-user secret retrieval.

Adapted from the data-commons-search vault module.  This module is
synchronous (requests-based) because Celery workers are synchronous.

Users authenticate via their EGI Check-in access token (JWT auth).
Secrets are stored at: {kv_mount}/users/{sub}/api-keys/{key_id}

The user identity (``sub`` claim) is resolved by calling the EGI Check-in
userinfo endpoint — EGI access tokens are opaque and do not carry user
claims in the token body.
"""

import logging
from urllib.parse import quote

import requests

from app.config import settings
from app.exceptions import VaultError, VREAuthenticationError, VREConfigurationError
from app.vres.utils.token_utils import TokenUser, extract_user_from_token

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_vault_token(access_token: str) -> str:
    """Exchange an EGI Check-in access token for a Vault client token via JWT auth."""
    url = f"{settings.vault_url}/v1/auth/{settings.vault_jwt_mount}/login"
    body: dict[str, str] = {"jwt": access_token}
    if settings.vault_jwt_role:
        body["role"] = settings.vault_jwt_role

    try:
        resp = requests.post(url, json=body, timeout=30)
        if resp.status_code != 200:
            logger.warning(
                "Vault JWT auth failed (%d): %s", resp.status_code, resp.text
            )
            raise VaultError(f"Vault authentication failed: {resp.status_code}")
        return resp.json()["auth"]["client_token"]
    except requests.RequestException as exc:
        raise VaultError(f"Vault authentication request failed: {exc}") from exc


def _kv_data_path(user_sub: str, key_id: str) -> str:
    """Build the Vault REST path for reading a secret.

    KV v1 uses the path directly; KV v2 wraps with ``/data/``.
    """
    id_enc = quote(user_sub, safe="")
    key_enc = quote(key_id, safe="")
    if settings.vault_kv_version == 2:
        return f"{settings.vault_kv_mount}/data/users/{id_enc}/api-keys/{key_enc}"
    return f"{settings.vault_kv_mount}/users/{id_enc}/api-keys/{key_enc}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def vault_get_api_key(access_token: str, key_id: str) -> str:
    """Retrieve a named secret from the user's Vault namespace.

    Args:
        access_token: EGI Check-in access token (used for Vault JWT auth).
        key_id: The key identifier to fetch (e.g. ``"vip"``).

    Returns:
        The secret value.

    Raises:
        VREAuthenticationError: Vault authentication failed.
        VREConfigurationError: The requested secret was not found.
        VaultError: Any other vault-related error.
    """
    user: TokenUser = extract_user_from_token(access_token)
    vault_token = _get_vault_token(access_token)
    path = _kv_data_path(user.sub, key_id)

    try:
        resp = requests.get(
            f"{settings.vault_url}/v1/{path}",
            headers={"X-Vault-Token": vault_token},
            timeout=30,
        )
        if resp.status_code == 404:
            raise VREConfigurationError(
                f"Secret '{key_id}' not found in vault for user '{user.sub}'"
            )
        if resp.status_code == 401 or resp.status_code == 403:
            raise VREAuthenticationError(
                f"Vault access denied ({resp.status_code}): {resp.text}"
            )
        if resp.status_code != 200:
            raise VaultError(f"Vault read failed ({resp.status_code}): {resp.text}")

        payload = resp.json()
        # KV v2 wraps data under data.data; KV v1 puts fields directly under data
        secret_data = (
            payload["data"]["data"]
            if settings.vault_kv_version == 2
            else payload["data"]
        )
        value = secret_data.get("value")
        if value is None:
            raise VREConfigurationError(
                f"Secret '{key_id}' exists but contains no 'value' field"
            )
        return value
    except requests.RequestException as exc:
        raise VaultError(f"Vault read request failed: {exc}") from exc
