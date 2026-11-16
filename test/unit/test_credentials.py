"""Unit tests for the per-user credential store (v4 plan, D2/D3)."""

import httpx
import pytest

from app.credentials import (
    ACCESS_TOKEN_TTL,
    CredentialStore,
    InMemoryCredentialStore,
    SQLiteCredentialStore,
    exchange_refresh_token,
)
from app.status_store import InMemoryStatusStore, SQLiteStatusStore

_DEV_TOKEN_ENDPOINT = (
    "https://aai-dev.egi.eu/auth/realms/egi/protocol/openid-connect/token"
)


def _stores():
    return [
        ("in-memory", InMemoryCredentialStore()),
        ("sqlite", SQLiteCredentialStore(":memory:")),
    ]


@pytest.mark.parametrize("name,store", _stores(), ids=[n for n, _ in _stores()])
async def test_upsert_then_get(name, store):
    await store.connect()
    await store.upsert("sub-1", "access-1", "refresh-1")

    record = await store.get("sub-1")

    assert record is not None
    assert record.sub == "sub-1"
    assert record.access_token == "access-1"
    assert record.refresh_token == "refresh-1"
    assert not record.is_expired()
    await store.aclose()


@pytest.mark.parametrize("name,store", _stores(), ids=[n for n, _ in _stores()])
async def test_upsert_replaces_access_token(name, store):
    await store.connect()
    await store.upsert("sub-1", "access-1", "refresh-1")
    await store.upsert("sub-1", "access-2", "refresh-2")

    record = await store.get("sub-1")

    assert record.access_token == "access-2"
    assert record.refresh_token == "refresh-2"
    await store.aclose()


@pytest.mark.parametrize("name,store", _stores(), ids=[n for n, _ in _stores()])
async def test_upsert_without_refresh_keeps_old_refresh(name, store):
    await store.connect()
    """A re-login without a refresh token must not drop the captured one —
    it is the janitor's only credential for that user."""
    await store.upsert("sub-1", "access-1", "refresh-1")
    await store.upsert("sub-1", "access-2", None)

    record = await store.get("sub-1")

    assert record.access_token == "access-2"
    assert record.refresh_token == "refresh-1"
    await store.aclose()


@pytest.mark.parametrize("name,store", _stores(), ids=[n for n, _ in _stores()])
async def test_get_unknown_sub_is_none(name, store):
    await store.connect()
    assert await store.get("nobody") is None
    await store.aclose()


@pytest.mark.parametrize("name,store", _stores(), ids=[n for n, _ in _stores()])
async def test_delete_forgets_credentials(name, store):
    await store.connect()
    await store.upsert("sub-1", "access-1", "refresh-1")
    await store.delete("sub-1")

    assert await store.get("sub-1") is None
    await store.delete("sub-1")  # idempotent
    await store.aclose()


async def test_access_token_ttl_is_set():
    store = InMemoryCredentialStore()
    await store.upsert("sub-1", "access-1", "refresh-1")

    record = await store.get("sub-1")

    delta = (record.expires_at - record.updated_at).total_seconds()
    assert delta == ACCESS_TOKEN_TTL
    assert record.is_expired(now=record.expires_at)


async def test_sqlite_store_shares_the_status_store_file(tmp_path):
    """Production runs both stores on one SQLite file (one backup, one
    permission class) — they must coexist."""
    db = str(tmp_path / "dispatcher.db")

    status = SQLiteStatusStore(db)
    await status.connect()
    creds = SQLiteCredentialStore(db)
    await creds.connect()

    from app.status_store import TaskRecord

    await status.create(TaskRecord(task_id="t-1", kind="k"))
    await creds.upsert("sub-1", "access-1", "refresh-1")

    assert (await status.get("t-1")).task_id == "t-1"
    assert (await creds.get("sub-1")).access_token == "access-1"

    await creds.aclose()
    await status.aclose()


async def test_sqlite_file_hygiene_600(tmp_path):
    """The credential file carries refresh tokens — owner-only (v4 D6)."""
    import os
    import stat

    db = str(tmp_path / "creds.db")
    store = SQLiteCredentialStore(db)
    await store.connect()

    assert stat.S_IMODE(os.stat(db).st_mode) == 0o600
    await store.aclose()


def test_in_memory_store_satisfies_protocol():
    assert isinstance(InMemoryCredentialStore(), CredentialStore)
    assert isinstance(SQLiteCredentialStore(":memory:"), CredentialStore)


# ---------------------------------------------------------------------------
# exchange_refresh_token (D3)
# ---------------------------------------------------------------------------


async def test_exchange_returns_access_token_and_writes_rotation_back(httpx_mock):
    store = InMemoryCredentialStore()
    await store.upsert("sub-1", "old-access", "old-refresh")
    httpx_mock.add_response(
        method="POST",
        url=_DEV_TOKEN_ENDPOINT,
        json={"access_token": "new-access", "refresh_token": "new-refresh"},
    )

    token = await exchange_refresh_token(store, "sub-1")

    assert token == "new-access"
    record = await store.get("sub-1")
    assert record.access_token == "new-access"
    assert record.refresh_token == "new-refresh"


async def test_exchange_sends_oauth_refresh_grant(httpx_mock):
    store = InMemoryCredentialStore()
    await store.upsert("sub-1", "old-access", "old-refresh")
    httpx_mock.add_response(
        method="POST",
        url=_DEV_TOKEN_ENDPOINT,
        json={"access_token": "new-access", "refresh_token": "new-refresh"},
    )

    await exchange_refresh_token(store, "sub-1", client_id="cid", client_secret="cs")

    import urllib.parse

    body = urllib.parse.parse_qs(httpx_mock.get_requests()[0].read().decode())
    assert body["grant_type"] == ["refresh_token"]
    assert body["refresh_token"] == ["old-refresh"]
    assert body["client_id"] == ["cid"]
    assert body["client_secret"] == ["cs"]


async def test_exchange_without_rotation_keeps_old_refresh_token(httpx_mock):
    """A provider that reuses refresh tokens: None response field must not
    blank the stored one (upsert COALESCE)."""
    store = InMemoryCredentialStore()
    await store.upsert("sub-1", "old-access", "old-refresh")
    httpx_mock.add_response(
        method="POST",
        url=_DEV_TOKEN_ENDPOINT,
        json={"access_token": "new-access"},
    )

    token = await exchange_refresh_token(store, "sub-1")

    assert token == "new-access"
    assert (await store.get("sub-1")).refresh_token == "old-refresh"


async def test_exchange_without_stored_credentials_makes_no_call(httpx_mock):
    store = InMemoryCredentialStore()

    assert await exchange_refresh_token(store, "sub-1") is None
    assert httpx_mock.get_requests() == []


async def test_exchange_without_refresh_token_makes_no_call(httpx_mock):
    store = InMemoryCredentialStore()
    await store.upsert("sub-1", "access-only", None)

    assert await exchange_refresh_token(store, "sub-1") is None
    assert httpx_mock.get_requests() == []


async def test_exchange_on_rejected_grant_returns_none_and_keeps_row(httpx_mock):
    """Rotated-out / revoked refresh token: log + None, retry next scan —
    the row must survive untouched."""
    store = InMemoryCredentialStore()
    await store.upsert("sub-1", "old-access", "old-refresh")
    httpx_mock.add_response(
        method="POST",
        url=_DEV_TOKEN_ENDPOINT,
        status_code=400,
        json={"error": "invalid_grant"},
    )

    assert await exchange_refresh_token(store, "sub-1") is None

    record = await store.get("sub-1")
    assert record.access_token == "old-access"
    assert record.refresh_token == "old-refresh"


async def test_exchange_on_transport_error_returns_none(httpx_mock):
    store = InMemoryCredentialStore()
    await store.upsert("sub-1", "old-access", "old-refresh")
    for _ in range(4):  # transport errors are retried (conftest: 4 attempts)
        httpx_mock.add_exception(
            httpx.ConnectError("connection refused"),
            method="POST",
            url=_DEV_TOKEN_ENDPOINT,
        )

    assert await exchange_refresh_token(store, "sub-1") is None
