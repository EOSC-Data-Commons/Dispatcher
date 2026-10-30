"""Unit tests for app.services.janitor — the recovery manager."""

import asyncio
from datetime import timedelta

import pytest

from app.credentials import InMemoryCredentialStore
from app.services.janitor import RecoveryManager
from app.status_store import (
    InMemoryStatusStore,
    TaskRecord,
    TaskStatus,
    _utcnow,
)
from fakes import FakeAsyncIM

DEV_TOKEN_ENDPOINT = (
    "https://aai-dev.egi.eu/auth/realms/egi/protocol/openid-connect/token"
)


@pytest.fixture
def store():
    return InMemoryStatusStore()


@pytest.fixture
def registry():
    return {}


@pytest.fixture
def credentials():
    return InMemoryCredentialStore()


def _janitor(store, registry, fake_im, credentials=None, **kwargs):
    return RecoveryManager(
        store,
        registry,
        credential_store=credentials,
        im_factory=lambda token: fake_im,
        **kwargs,
    )


async def _add(store, **kwargs):
    record = TaskRecord(task_id=kwargs.pop("task_id", "t-1"), **kwargs)
    await store.create(record)
    return record


async def test_live_local_task_is_left_alone(store, registry):
    await _add(store, status=TaskStatus.PROGRESS, im_inf_id="infra-1")
    fake = FakeAsyncIM()
    janitor = _janitor(store, registry, fake)

    never = asyncio.create_task(asyncio.Event().wait())
    registry["t-1"] = never
    try:
        await janitor.scan_once()
    finally:
        never.cancel()
        await asyncio.gather(never, return_exceptions=True)

    assert fake.destroyed == []
    record = await store.get("t-1")
    assert record.status == TaskStatus.PROGRESS


async def test_stale_pending_marks_worker_lost(store, registry, monkeypatch):
    await _add(store, status=TaskStatus.PENDING)
    janitor = _janitor(store, registry, FakeAsyncIM(), stale_timeout=1)

    aged = _utcnow() + timedelta(seconds=2)
    monkeypatch.setattr("app.services.janitor._utcnow", lambda: aged)

    await janitor.scan_once()

    record = await store.get("t-1")
    assert record.status == TaskStatus.FAILURE
    assert record.error == "worker lost"


async def test_fresh_progress_is_not_marked_lost(store, registry, monkeypatch):
    await _add(store, status=TaskStatus.PROGRESS)
    janitor = _janitor(store, registry, FakeAsyncIM(), stale_timeout=3600)

    await janitor.scan_once()

    record = await store.get("t-1")
    assert record.status == TaskStatus.PROGRESS


async def test_stale_progress_with_infra_marks_lost_and_reaps(
    store, registry, monkeypatch
):
    await _add(store, status=TaskStatus.PROGRESS, im_inf_id="infra-9")
    fake = FakeAsyncIM()
    janitor = _janitor(store, registry, fake, stale_timeout=1)
    aged = _utcnow() + timedelta(seconds=2)
    monkeypatch.setattr("app.services.janitor._utcnow", lambda: aged)

    await janitor.scan_once()

    record = await store.get("t-1")
    assert record.status == TaskStatus.FAILURE
    assert record.error == "worker lost"
    assert fake.destroyed == ["infra-9"]
    assert record.destroyed_at is not None


async def test_failed_with_infra_is_reaped(store, registry):
    await _add(store, status=TaskStatus.FAILURE, im_inf_id="infra-5")
    fake = FakeAsyncIM()
    janitor = _janitor(store, registry, fake)

    await janitor.scan_once()

    assert fake.destroyed == ["infra-5"]
    record = await store.get("t-1")
    assert record.status == TaskStatus.FAILURE  # status unchanged on reap
    assert record.destroyed_at is not None


async def test_failed_destroy_failure_retries_next_scan(store, registry, caplog):
    await _add(store, status=TaskStatus.FAILURE, im_inf_id="infra-5")
    fake = FakeAsyncIM(destroy_raises=RuntimeError("401 Unauthorized"))
    janitor = _janitor(store, registry, fake)

    with caplog.at_level("WARNING", logger="app.services.janitor"):
        await janitor.scan_once()
        await janitor.scan_once()

    record = await store.get("t-1")
    assert record.destroyed_at is None
    assert not fake.destroyed  # destroy kept failing
    warnings = [r for r in caplog.records if "Failed to destroy infra" in r.message]
    assert len(warnings) == 2  # retried on the next scan


async def test_failed_without_infra_needs_no_action(store, registry):
    await _add(store, status=TaskStatus.FAILURE)
    fake = FakeAsyncIM()
    janitor = _janitor(store, registry, fake)

    await janitor.scan_once()

    assert fake.destroyed == []


async def test_delivered_infra_survives_when_ttl_off(store, registry):
    await _add(store, status=TaskStatus.SUCCESS, im_inf_id="infra-1")
    fake = FakeAsyncIM()
    janitor = _janitor(store, registry, fake)  # infra_max_lifetime=None default

    await janitor.scan_once()

    assert fake.destroyed == []
    record = await store.get("t-1")
    assert record.status == TaskStatus.SUCCESS


async def test_delivered_infra_ttl_destroy_when_enabled(store, registry, monkeypatch):
    await _add(store, status=TaskStatus.SUCCESS, im_inf_id="infra-old")
    fake = FakeAsyncIM()
    janitor = _janitor(store, registry, fake, infra_max_lifetime=60)
    aged = _utcnow() + timedelta(seconds=120)
    monkeypatch.setattr("app.services.janitor._utcnow", lambda: aged)

    await janitor.scan_once()

    assert fake.destroyed == ["infra-old"]
    record = await store.get("t-1")
    assert record.status == TaskStatus.DESTROYED
    assert record.destroyed_at is not None


async def test_delivered_infra_within_ttl_untouched(store, registry):
    await _add(store, status=TaskStatus.SUCCESS, im_inf_id="infra-young")
    fake = FakeAsyncIM()
    janitor = _janitor(store, registry, fake, infra_max_lifetime=3600)

    await janitor.scan_once()

    assert fake.destroyed == []


# ---------------------------------------------------------------------------
# Reap auth via the refresh-token exchange (v4 §8, D3/D4)
# ---------------------------------------------------------------------------


async def test_reap_exchanges_refresh_token_for_im_credentials(
    store, registry, credentials, httpx_mock
):
    """A reap for an owner-bound record exchanges the owner's refresh
    token and hands the fresh access token to the IM factory."""
    await _add(store, status=TaskStatus.FAILURE, im_inf_id="infra-5", sub="sub-1")
    await credentials.upsert("sub-1", "old-access", "old-refresh")
    httpx_mock.add_response(
        method="POST",
        url=DEV_TOKEN_ENDPOINT,
        json={"access_token": "fresh-access", "refresh_token": "fresh-refresh"},
    )

    seen_tokens = []

    def factory(token):
        seen_tokens.append(token)
        return FakeAsyncIM()

    janitor = RecoveryManager(
        store, registry, credential_store=credentials, im_factory=factory
    )
    await janitor.scan_once()

    assert seen_tokens == ["fresh-access"]
    record = await store.get("t-1")
    assert record.destroyed_at is not None
    # Rotation written back to the credential store.
    rotated = await credentials.get("sub-1")
    assert rotated.access_token == "fresh-access"
    assert rotated.refresh_token == "fresh-refresh"


async def test_reap_with_failed_exchange_defers_destroy_to_next_scan(
    store, registry, credentials, httpx_mock, caplog
):
    """No/rotated-out refresh token: log + skip, retry next scan (v4 §8.4)."""
    await _add(store, status=TaskStatus.FAILURE, im_inf_id="infra-5", sub="sub-1")
    await credentials.upsert("sub-1", "old-access", "old-refresh")
    httpx_mock.add_response(
        method="POST",
        url=DEV_TOKEN_ENDPOINT,
        status_code=400,
        json={"error": "invalid_grant"},
    )

    attempts = []

    def factory(token):
        attempts.append(token)
        return FakeAsyncIM()

    janitor = RecoveryManager(
        store, registry, credential_store=credentials, im_factory=factory
    )
    with caplog.at_level("WARNING", logger="app.services.janitor"):
        await janitor.scan_once()

    assert attempts == []  # destroy never attempted without credentials
    record = await store.get("t-1")
    assert record.destroyed_at is None
    deferred = [r for r in caplog.records if "deferred to next scan" in r.message]
    assert len(deferred) == 1


async def test_reap_without_captured_credentials_defers_destroy(
    store, registry, credentials
):
    """Owner never logged in since the credential store landed: no row —
    defer (retry next scan), never destroy blind."""
    await _add(store, status=TaskStatus.FAILURE, im_inf_id="infra-5", sub="sub-1")

    attempts = []

    def factory(token):
        attempts.append(token)
        return FakeAsyncIM()

    janitor = RecoveryManager(
        store, registry, credential_store=credentials, im_factory=factory
    )
    await janitor.scan_once()

    assert attempts == []
    assert (await store.get("t-1")).destroyed_at is None


async def test_reap_of_anonymous_record_uses_no_token(store, registry):
    """Anonymous flows never had credentials; the destroy is attempted
    anyway (sub is None — there is nothing to exchange)."""
    await _add(store, status=TaskStatus.FAILURE, im_inf_id="infra-5")  # sub=None
    seen_tokens = []

    def factory(token):
        seen_tokens.append(token)
        return FakeAsyncIM()

    janitor = RecoveryManager(store, registry, im_factory=factory)
    await janitor.scan_once()

    assert seen_tokens == [None]
    assert (await store.get("t-1")).destroyed_at is not None


async def test_run_periodic_scans_then_stops(store, registry):
    fake = FakeAsyncIM()
    janitor = _janitor(store, registry, fake, interval=0.01)

    scans = []

    original = janitor.scan_once

    async def _counting():
        scans.append(1)
        await original()
        if len(scans) >= 3:
            janitor.stop()

    janitor.scan_once = _counting

    await asyncio.wait_for(janitor.run_periodic(), timeout=5)

    assert len(scans) == 3
