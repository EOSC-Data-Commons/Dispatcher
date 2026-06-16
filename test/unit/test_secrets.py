"""Unit tests for SecretStore."""

import uuid
from unittest.mock import MagicMock

import pytest

from app.services.secrets import SecretStore


@pytest.fixture
def secret_store():
    """Return a SecretStore whose Redis client is a MagicMock.

    The mock accumulates keys in an in-memory dict so that GET+DELETE
    round-trips behave like real Redis.
    """
    store = SecretStore("redis://localhost:6379/0")
    mock_redis = MagicMock()
    _data: dict[str, str] = {}

    def setex(key: str, ttl: int, value: str) -> None:
        _data[key] = value

    mock_redis.setex = setex

    def register_script(lua_code: str):
        def execute(keys: list[str]) -> bytes | None:
            key = keys[0]
            value = _data.pop(key, None)
            if value is None:
                return None
            return value.encode("utf-8")

        return execute

    mock_redis.register_script = register_script

    store._redis = mock_redis
    return store


def test_put_returns_uuid_string(secret_store):
    ref = secret_store.put("secret-value")
    assert isinstance(ref, str)
    uuid.UUID(ref)  # must be a valid UUID


def test_put_stores_value(secret_store):
    ref = secret_store.put("my-api-key", ttl=120)
    result = secret_store.get_and_delete(ref)
    assert result == "my-api-key"


def test_get_and_delete_retrieves_value(secret_store):
    ref = secret_store.put("top-secret")
    result = secret_store.get_and_delete(ref)
    assert result == "top-secret"


def test_get_and_delete_removes_value(secret_store):
    ref = secret_store.put("one-time-secret")
    secret_store.get_and_delete(ref)  # consume it
    result = secret_store.get_and_delete(ref)  # try again
    assert result is None


def test_get_and_delete_unknown_key_returns_none(secret_store):
    result = secret_store.get_and_delete("nonexistent-ref")
    assert result is None


def test_expired_key_returns_none(secret_store):
    result = secret_store.get_and_delete("expired-key")
    assert result is None


def test_default_url_falls_back_when_env_not_set(monkeypatch):
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    store = SecretStore()
    assert "redis://" in store._redis_url


def test_roundtrip_put_get_and_delete_flow(secret_store):
    ref1 = secret_store.put("secret-A")
    ref2 = secret_store.put("secret-B")

    assert secret_store.get_and_delete(ref2) == "secret-B"
    assert secret_store.get_and_delete(ref1) == "secret-A"

    # Both consumed
    assert secret_store.get_and_delete(ref1) is None
    assert secret_store.get_and_delete(ref2) is None
