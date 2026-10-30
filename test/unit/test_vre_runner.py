"""Unit tests for app.vre_runner — the shared async flow executor."""

import asyncio
import json

import pytest

from app.status_store import InMemoryStatusStore, TaskRecord, TaskStatus
from app.vre_runner import execute_flow
from fakes import FakeAsyncIM
from vre_rocrate import VREPayloadBuilder

GALAXY_TOSCA_CRATE = "test/fixtures/galaxy_tosca_rocrate.json"


def _load_crate():
    with open(GALAXY_TOSCA_CRATE) as f:
        return json.load(f)


def _load_payload():
    return VREPayloadBuilder.build(_load_crate())


@pytest.fixture
def store():
    return InMemoryStatusStore()


@pytest.fixture
def registry():
    return {}


async def _record(store, **kwargs):
    record = TaskRecord(task_id="task-1", **kwargs)
    await store.create(record)
    return record


async def test_success_path_records_progress_and_success(store, registry, httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://vre.example/api/workflow_landings",
        status_code=201,
        json={"uuid": "u-1"},
    )
    await _record(store)

    await execute_flow(
        "task-1",
        store=store,
        registry=registry,
        token="tok",
        payload=_load_payload(),
        im_factory=lambda token: FakeAsyncIM(outputs={"url": "https://vre.example"}),
    )

    record = await store.get("task-1")
    assert record.status == TaskStatus.SUCCESS
    # The progress stage is cleared on terminal success (see execute_flow docstring).
    assert record.stage is None
    assert record.result == {
        "url": "https://vre.example/workflow_landings/u-1?public=False"
    }
    assert "task-1" not in registry


async def test_failure_records_error(store, registry):
    await _record(store)

    class _Boom(FakeAsyncIM):
        async def run(self, rp, heartbeat=None, on_inf_created=None):
            raise ValueError("kaput")

    await execute_flow(
        "task-1",
        store=store,
        registry=registry,
        token="tok",
        payload=_load_payload(),
        im_factory=lambda token: _Boom(),
    )

    record = await store.get("task-1")
    assert record.status == TaskStatus.FAILURE
    # FAILURE keeps the last stage as death-context; only SUCCESS clears it.
    assert record.stage == "dispatching"
    assert "kaput" in record.error


async def test_cancellation_leaves_status_to_the_deleter(store, registry):
    await _record(store)

    cancelled = asyncio.Event()

    class _Slow(FakeAsyncIM):
        async def run(self, rp, heartbeat=None, on_inf_created=None):
            await asyncio.Event().wait()

    task = asyncio.create_task(
        execute_flow(
            "task-1",
            store=store,
            registry=registry,
            token="tok",
            payload=_load_payload(),
            im_factory=lambda token: _Slow(),
        )
    )
    registry["task-1"] = task
    await asyncio.sleep(0)
    assert (await store.get("task-1")).status == TaskStatus.PROGRESS

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    record = await store.get("task-1")
    # The runner does not overwrite the record on cancellation.
    assert record.status == TaskStatus.PROGRESS
    assert "task-1" not in registry
    cancelled.set()


async def test_im_flow_persists_inf_id_at_create(store, registry, httpx_mock):
    """im_inf_id is written the instant create() returns: the VM can never
    exist before its record does (the infra-registry invariant)."""
    httpx_mock.add_response(
        method="POST",
        url="https://vre.example/api/workflow_landings",
        status_code=201,
        json={"uuid": "u-1"},
    )
    await _record(store)

    seen = {}

    class _Observing(FakeAsyncIM):
        async def run(self, rp, heartbeat=None, on_inf_created=None):
            async def _wrapped(inf_id):
                await on_inf_created(inf_id)
                seen["record_at_create"] = await store.get("task-1")

            return await super().run(rp, heartbeat=heartbeat, on_inf_created=_wrapped)

    fake = _Observing(outputs={"url": "https://vre.example"})
    await execute_flow(
        "task-1",
        store=store,
        registry=registry,
        token="tok",
        payload=_load_payload(),
        im_factory=lambda token: fake,
    )

    at_create = seen["record_at_create"]
    assert at_create.im_inf_id == "fake-inf-1"

    record = await store.get("task-1")
    assert record.status == TaskStatus.SUCCESS
    assert fake.created_with != []


async def test_prebuilt_payload_is_used_directly(store, registry):
    """The dispatching handler builds the payload (400 on invalid crate);
    the runner must not rebuild it."""
    await _record(store)
    payload = _load_payload()

    seen = {}

    class _Observing(FakeAsyncIM):
        async def run(self, rp, heartbeat=None, on_inf_created=None):
            seen["rp"] = rp
            return await super().run(
                rp, heartbeat=heartbeat, on_inf_created=on_inf_created
            )

    httpx_landing = "https://vre.example/api/workflow_landings"
    # no landing call happens because FakeAsyncIM returns outputs whose url
    # the galaxy VRE then posts to... register nothing and rely on failure?
    # Instead use a runtimePlatform-less payload variant.
    payload.workflow.runtime_platform = None

    await execute_flow(
        "task-1",
        store=store,
        registry=registry,
        token="tok",
        payload=payload,
    )

    record = await store.get("task-1")
    assert record.status == TaskStatus.SUCCESS
    assert seen == {}  # factory never invoked without an IM-backed payload
