"""Unit tests for SecretStore."""

import uuid
from unittest.mock import MagicMock

import pytest

from app.services.secrets import SecretStore


@pytest.fixture
def secret_store():
    """Return a SecretStore with an in-memory mock Redis client.

    Backs *setex* / *get* / *delete* so that all SecretStore methods work
    transparently without a real Redis.
    """
    store = SecretStore("redis://localhost:6379/0")
    mock_redis = MagicMock()
    _data: dict[str, str] = {}

    def setex(key: str, ttl: int, value: str) -> None:
        _data[key] = value

    mock_redis.setex = setex

    def get(key: str) -> bytes | None:
        raw = _data.get(key)
        if raw is None:
            return None
        return raw.encode("utf-8")

    mock_redis.get = get

    def delete(key: str) -> None:
        _data.pop(key, None)

    mock_redis.delete = delete

    store._redis = mock_redis
    return store


# ---------------------------------------------------------------------------
# put
# ---------------------------------------------------------------------------


def test_put_returns_uuid_string(secret_store):
    ref = secret_store.put("secret-value")
    assert isinstance(ref, str)
    uuid.UUID(ref)  # must be a valid UUID


def test_put_then_get_returns_original_value(secret_store):
    ref = secret_store.put("my-api-key", ttl=120)
    result = secret_store.get(ref)
    assert result == "my-api-key"


# ---------------------------------------------------------------------------
# get (non-destructive read)
# ---------------------------------------------------------------------------


def test_get_retrieves_value(secret_store):
    ref = secret_store.put("top-secret")
    result = secret_store.get(ref)
    assert result == "top-secret"


def test_get_does_not_delete(secret_store):
    ref = secret_store.put("top-secret")
    secret_store.get(ref)
    result = secret_store.get(ref)
    assert result == "top-secret"


def test_get_unknown_key_returns_none(secret_store):
    result = secret_store.get("nonexistent-ref")
    assert result is None


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_removes_value(secret_store):
    ref = secret_store.put("delete-me")
    secret_store.delete(ref)
    assert secret_store.get(ref) is None


def test_delete_missing_key_is_noop(secret_store):
    secret_store.delete("nonexistent-ref")


# ---------------------------------------------------------------------------
# TTL / expiry
# ---------------------------------------------------------------------------


def test_expired_key_returns_none(secret_store):
    result = secret_store.get("expired-key")
    assert result is None


# ---------------------------------------------------------------------------
# Default URL
# ---------------------------------------------------------------------------


def test_default_url_falls_back_when_env_not_set(monkeypatch):
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    store = SecretStore()
    assert "redis://" in store._redis_url


# ---------------------------------------------------------------------------
# Retry-friendly pattern: get + use + delete only on success
# ---------------------------------------------------------------------------


def test_get_then_delete_after_success(secret_store):
    """Simulate a retry-safe flow: read secret, do work, then delete."""
    ref = secret_store.put("retry-safe-secret")

    # Attempt 1 — read without consuming
    key1 = secret_store.get(ref)
    assert key1 == "retry-safe-secret"

    # Simulate failure; retry attempt — secret still readable
    key2 = secret_store.get(ref)
    assert key2 == "retry-safe-secret"

    # Success — now clean up
    secret_store.delete(ref)
    assert secret_store.get(ref) is None


# ---------------------------------------------------------------------------
# Roundtrip
# ---------------------------------------------------------------------------


def test_roundtrip_put_get_delete_flow(secret_store):
    ref1 = secret_store.put("secret-A")
    ref2 = secret_store.put("secret-B")

    assert secret_store.get(ref2) == "secret-B"
    secret_store.delete(ref2)

    assert secret_store.get(ref1) == "secret-A"
    secret_store.delete(ref1)

    # Both consumed
    assert secret_store.get(ref1) is None
    assert secret_store.get(ref2) is None
