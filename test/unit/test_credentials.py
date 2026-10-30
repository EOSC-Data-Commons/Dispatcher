"""Unit tests for the per-user credential store (v4 plan, D2)."""

import pytest

from app.credentials import (
    ACCESS_TOKEN_TTL,
    CredentialStore,
    InMemoryCredentialStore,
    SQLiteCredentialStore,
)
from app.status_store import InMemoryStatusStore, SQLiteStatusStore


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


def test_in_memory_store_satisfies_protocol():
    assert isinstance(InMemoryCredentialStore(), CredentialStore)
    assert isinstance(SQLiteCredentialStore(":memory:"), CredentialStore)
