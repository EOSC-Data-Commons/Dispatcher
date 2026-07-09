#!/usr/bin/env python3
"""Standalone test script for EGI Vault secret retrieval.

Usage:
    python test_vault.py <access_token> [key_id]

Examples:
    python test_vault.py "$ACCESS_TOKEN"
    python test_vault.py "$ACCESS_TOKEN" vip
    python test_vault.py "$ACCESS_TOKEN" custom-key
"""

import sys
import os

# Ensure the project root is on the import path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import settings
from app.vres.utils.vault import vault_get_api_key

# ---------------------------------------------------------------------------
# Override vault settings for the test — defaults match the ansible vars
# ---------------------------------------------------------------------------
settings.vault_url = os.environ.get("VAULT_URL", "https://secrets.egi.eu")
settings.vault_jwt_mount = os.environ.get("VAULT_JWT_MOUNT", "jwt")
settings.vault_kv_mount = os.environ.get("VAULT_KV_MOUNT", "secrets")
settings.vault_kv_version = int(os.environ.get("VAULT_KV_VERSION", "1"))
settings.vault_jwt_role = os.environ.get("VAULT_JWT_ROLE", "")


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <access_token> [key_id]", file=sys.stderr)
        sys.exit(1)

    access_token = sys.argv[1]
    key_id = sys.argv[2] if len(sys.argv) > 2 else "vip"

    print(f"Vault URL   : {settings.vault_url}")
    print(f"JWT mount   : {settings.vault_jwt_mount}")
    print(f"KV mount    : {settings.vault_kv_mount}  (v{settings.vault_kv_version})")
    print(f"Key ID      : {key_id}")
    print(f"Access token: {access_token[:20]}...{access_token[-10:]}")
    print("-" * 60)

    try:
        value = vault_get_api_key(access_token, key_id)
        print(f"\n✅ Success — retrieved secret for '{key_id}':")
        print(f"   {value}")
    except Exception as exc:
        print(f"\n❌ Failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
