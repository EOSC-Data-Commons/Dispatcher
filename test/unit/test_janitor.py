"""Unit tests for app.services.janitor — the recovery manager."""

import asyncio
import json
from datetime import timedelta

import pytest

from app.services.janitor import RecoveryManager
from app.status_store import (
    InMemoryStatusStore,
    ResumeStage,
    TaskRecord,
    TaskStatus,
    _utcnow,
)
from fakes import FakeAsyncIM

GALAXY_TOSCA_CRATE = "test/fixtures/galaxy_tosca_rocrate.json"
GALAXY_LANDING = "https://vre.example/api/workflow_landings"


def _load_crate():
    with open(GALAXY_TOSCA_CRATE) as f:
        return json.load(f)


@pytest.fixture
def store():
    return InMemoryStatusStore()


@pytest.fixture
def registry():
    return {}


def _janitor(store, registry, fake_im, **kwargs):
    return RecoveryManager(store, registry, im_factory=lambda token: fake_im, **kwargs)


async def _add(store, **kwargs):
    record = TaskRecord(task_id=kwargs.pop("task_id", "t-1"), **kwargs)
    await store.create(record)
    return record


async def test_respawns_im_wait_continuation_and_reaches_success(
    store, registry, httpx_mock
):
    httpx_mock.add_response(
        method="POST", url=GALAXY_LANDING, status_code=201, json={"uuid": "u-1"}
    )
    await _add(
        store,
        status=TaskStatus.PROGRESS,
        crate=_load_crate(),
        im_inf_id="infra-77",
        im_token="dispatch-token",
        resume_stage=ResumeStage.IM_WAIT,
    )
    fake = FakeAsyncIM(outputs={"url": "https://vre.example"})
    janitor = _janitor(store, registry, fake)

    await janitor.scan_once()
    task = registry.get("t-1")
    assert task is not None, "continuation must be respawned into the registry"
    await task

    assert fake.resumed_with == ["infra-77"]
    record = await store.get("t-1")
    assert record.status == TaskStatus.SUCCESS
    assert record.result == {
        "url": "https://vre.example/workflow_landings/u-1?public=False"
    }


async def test_live_local_task_is_left_alone(store, registry):
    await _add(
        store,
        status=TaskStatus.PROGRESS,
        im_inf_id="infra-1",
        resume_stage=ResumeStage.IM_WAIT,
    )
    fake = FakeAsyncIM()
    janitor = _janitor(store, registry, fake)

    never = asyncio.create_task(asyncio.Event().wait())
    registry["t-1"] = never
    try:
        await janitor.scan_once()
    finally:
        never.cancel()
        await asyncio.gather(never, return_exceptions=True)

    assert fake.resumed_with == []
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


async def test_stale_non_resumable_with_infra_destroys_infra(
    store, registry, monkeypatch
):
    await _add(
        store,
        status=TaskStatus.PROGRESS,
        im_inf_id="infra-9",
        im_token="tok",
        resume_stage=ResumeStage.NONE,  # zip+IM flows degrade, never resume
    )
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
    await _add(
        store,
        status=TaskStatus.FAILURE,
        im_inf_id="infra-5",
        im_token="tok",
    )
    fake = FakeAsyncIM()
    janitor = _janitor(store, registry, fake)

    await janitor.scan_once()

    assert fake.destroyed == ["infra-5"]
    record = await store.get("t-1")
    assert record.status == TaskStatus.FAILURE  # status unchanged on reap
    assert record.destroyed_at is not None


async def test_failed_destroy_failure_retries_next_scan(store, registry, caplog):
    await _add(
        store,
        status=TaskStatus.FAILURE,
        im_inf_id="infra-5",
        im_token="tok",
    )
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
    await _add(
        store,
        status=TaskStatus.SUCCESS,
        im_inf_id="infra-1",
        im_token="tok",
    )
    fake = FakeAsyncIM()
    janitor = _janitor(store, registry, fake)  # infra_max_lifetime=None default

    await janitor.scan_once()

    assert fake.destroyed == []
    record = await store.get("t-1")
    assert record.status == TaskStatus.SUCCESS


async def test_delivered_infra_ttl_destroy_when_enabled(store, registry, monkeypatch):
    await _add(
        store,
        status=TaskStatus.SUCCESS,
        im_inf_id="infra-old",
        im_token="tok",
    )
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
    await _add(
        store,
        status=TaskStatus.SUCCESS,
        im_inf_id="infra-young",
        im_token="tok",
    )
    fake = FakeAsyncIM()
    janitor = _janitor(store, registry, fake, infra_max_lifetime=3600)

    await janitor.scan_once()

    assert fake.destroyed == []


async def test_respawn_without_token_fails_flow_and_later_reaps_infra(
    store, registry, httpx_mock
):
    """Expiring-token limitation: resume without a usable token fails; the
    leftover infra is then destroyed (best-effort) on a later scan."""
    await _add(
        store,
        status=TaskStatus.PROGRESS,
        crate=_load_crate(),
        im_inf_id="infra-77",
        im_token=None,
        resume_stage=ResumeStage.IM_WAIT,
    )

    class _NoToken(FakeAsyncIM):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            from app.exceptions import IMError

            self._init_error = IMError("Access token not provided for IM.")

    def _factory(token):
        if not token:
            from app.exceptions import IMError

            raise IMError("Access token not provided for IM.")
        return FakeAsyncIM(outputs={"url": "https://vre.example"})

    janitor = RecoveryManager(store, registry, im_factory=_factory)

    await janitor.scan_once()
    task = registry.get("t-1")
    assert task is not None
    await task  # flow fails without a token

    record = await store.get("t-1")
    assert record.status == TaskStatus.FAILURE

    fake2 = FakeAsyncIM()
    janitor2 = _janitor(store, registry, fake2)
    # second scan: FAILED + infra => reaped (factory now yields a working fake)
    await RecoveryManager(
        store,
        registry,
        im_factory=lambda token: fake2,
    ).scan_once()

    assert fake2.destroyed == ["infra-77"]


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
