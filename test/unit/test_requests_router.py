"""Router contract tests (authenticated /requests + anonymous /anon_requests).

A minimal FastAPI app wires the routers against InMemoryStatusStore and a
fresh live-task registry; ``oauth2_scheme`` is dependency-overridden with
locally-signed RS256 tokens (Auth Design 1: dispatch derives the owner by
verifying the request's own token).
"""

import asyncio
import io
import json
import zipfile

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.routers import anonymous_requests, requests
from app.security import oauth2_scheme
from app.status_store import InMemoryStatusStore, ResumeStage, TaskRecord, TaskStatus
from fakes import FakeAsyncIM
from fixtures.jwt_helper import generate_rsa_key, make_token, patch_jwks

GALAXY_TOSCA_CRATE = "test/fixtures/galaxy_tosca_rocrate.json"
GALAXY_LANDING = "https://vre.example/api/workflow_landings"


def _load_crate():
    with open(GALAXY_TOSCA_CRATE) as f:
        return json.load(f)


IDENTITY = "oidc-sub-1234"
OTHER_IDENTITY = "someone-else"

#: The RSA key of the current test and the token its app mints (set by the
#: autouse fixture / _make_app; never read across tests).
_RSA_KEY: dict = {}
_LAST_TOKEN: dict = {}


@pytest.fixture(autouse=True)
def _auth_key(monkeypatch):
    """Local RSA key wired into app.security._jwks for every test."""
    rsa_key = generate_rsa_key()
    patch_jwks(monkeypatch, rsa_key)
    _RSA_KEY["key"] = rsa_key
    yield
    _RSA_KEY.clear()
    _LAST_TOKEN.clear()


def _make_app(store, registry, identity=IDENTITY):
    """Bare app: routers + oauth2_scheme overridden with a locally-signed
    token for *identity* (empty for anonymous callers)."""
    app = FastAPI()
    app.state.status_store = store
    app.state.tasks = registry

    if identity is None:
        token = ""
    else:
        token = make_token(
            _RSA_KEY["key"],
            claims_over={"sub": identity, "preferred_username": "Jane Doe"},
        )
    _LAST_TOKEN["token"] = token

    app.include_router(requests.router)
    app.include_router(anonymous_requests.router)
    app.dependency_overrides[oauth2_scheme] = lambda: token
    return app


@pytest.fixture
def store():
    return InMemoryStatusStore()


@pytest.fixture
def registry():
    return {}


@pytest.fixture
def fake_im():
    return FakeAsyncIM(outputs={"url": "https://vre.example"})


@pytest.fixture(autouse=True)
def _inject_im_factory(monkeypatch, fake_im):
    """Routers/dispatch create IM clients through default_im_factory."""
    monkeypatch.setattr("app.vres.base_vre.default_im_factory", lambda token: fake_im)
    monkeypatch.setattr(
        "app.routers.utils.dispatch.default_im_factory", lambda token: fake_im
    )


async def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _finished(registry, task_id):
    """Await the background flow task."""
    task = registry.get(task_id)
    if task is not None:
        await task


# ---------------------------------------------------------------------------
# POST contract: 202 shape, 400 on invalid crate
# ---------------------------------------------------------------------------


async def test_post_metadata_returns_202_task_id(store, registry, httpx_mock):
    httpx_mock.add_response(
        method="POST", url=GALAXY_LANDING, status_code=201, json={"uuid": "u-1"}
    )
    app = _make_app(store, registry)
    async with await _client(app) as client:
        resp = await client.post("/requests/metadata_rocrate/", json=_load_crate())

    assert resp.status_code == 202
    task_id = resp.json()["task_id"]
    assert task_id

    await _finished(registry, task_id)
    record = await store.get(task_id)
    assert record.status == TaskStatus.SUCCESS
    assert record.crate == _load_crate()
    assert record.sub == IDENTITY
    assert record.owner == {
        "sub": IDENTITY,
        "name": "Jane Doe",
    }
    assert record.kind == "https://galaxyproject.org/"


async def test_post_invalid_crate_is_400_not_async_failure(store, registry):
    app = _make_app(store, registry)
    async with await _client(app) as client:
        resp = await client.post("/requests/metadata_rocrate/", json={"bad": "crate"})

    assert resp.status_code == 400
    assert (await store.list_active()) == []  # nothing persisted


async def test_post_unsupported_language_is_400(store, registry):
    crate = _load_crate()
    for entity in crate["@graph"]:
        if entity.get("@id") == "#galaxy-lang":
            entity["identifier"] = "https://unknown.example/lang"
    app = _make_app(store, registry)
    async with await _client(app) as client:
        resp = await client.post("/requests/metadata_rocrate/", json=crate)

    assert resp.status_code == 400
    assert (await store.list_active()) == []


def _zip_bytes(crate: dict, files: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ro-crate-metadata.json", json.dumps(crate))
        for name, content in (files or {}).items():
            zf.writestr(name, content)
    buf.seek(0)
    return buf.getvalue()


async def test_post_zip_returns_202(store, registry, httpx_mock):
    httpx_mock.add_response(
        method="POST", url=GALAXY_LANDING, status_code=201, json={"uuid": "u-1"}
    )
    app = _make_app(store, registry)
    async with await _client(app) as client:
        resp = await client.post(
            "/requests/zip_rocrate/",
            files={
                "zipfile": (
                    "crate.zip",
                    _zip_bytes(_load_crate(), {"notebook.ipynb": b"{}"}),
                    "application/zip",
                )
            },
        )

    assert resp.status_code == 202
    task_id = resp.json()["task_id"]
    await _finished(registry, task_id)

    record = await store.get(task_id)
    assert record.status == TaskStatus.SUCCESS
    # zip+IM flow: infra is registered but NOT resume-eligible, and no
    # token is persisted (bytes are never stored; degrade + resubmit).
    assert record.im_inf_id == "fake-inf-1"
    assert record.resume_stage == ResumeStage.NONE
    assert record.im_token is None


async def test_post_metadata_im_flow_is_resume_eligible_and_persists_token(
    store, registry, httpx_mock
):
    httpx_mock.add_response(
        method="POST", url=GALAXY_LANDING, status_code=201, json={"uuid": "u-1"}
    )
    app = _make_app(store, registry)
    async with await _client(app) as client:
        resp = await client.post("/requests/metadata_rocrate/", json=_load_crate())

    task_id = resp.json()["task_id"]
    await _finished(registry, task_id)

    record = await store.get(task_id)
    assert record.status == TaskStatus.SUCCESS
    assert record.im_inf_id == "fake-inf-1"
    # Resume-eligible flows persist the caller's own (verified) token.
    assert record.im_token == _LAST_TOKEN["token"]


async def test_post_zip_invalid_zip_is_400(store, registry):
    app = _make_app(store, registry)
    async with await _client(app) as client:
        resp = await client.post(
            "/requests/zip_rocrate/",
            files={"zipfile": ("crate.zip", b"not a zip", "application/zip")},
        )

    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET contract: 404 unknown, 403 owner mismatch, anonymous open
# ---------------------------------------------------------------------------


async def test_get_unknown_task_is_404(store, registry):
    app = _make_app(store, registry)
    async with await _client(app) as client:
        resp = await client.get("/requests/no-such-task")

    assert resp.status_code == 404


async def test_get_returns_status_shape(store, registry):
    await store.create(
        TaskRecord(
            task_id="t-1",
            sub=IDENTITY,
            status=TaskStatus.SUCCESS,
            result={"url": "https://vre.example"},
        )
    )
    app = _make_app(store, registry)
    async with await _client(app) as client:
        resp = await client.get("/requests/t-1")

    assert resp.status_code == 200
    assert resp.json() == {
        "task_id": "t-1",
        "status": "SUCCESS",
        "result": {"url": "https://vre.example"},
    }


async def test_get_other_users_task_is_403(store, registry):
    await store.create(TaskRecord(task_id="t-1", sub=OTHER_IDENTITY))
    app = _make_app(store, registry, identity=IDENTITY)
    async with await _client(app) as client:
        resp = await client.get("/requests/t-1")

    assert resp.status_code == 403


async def test_get_owned_task_without_identity_is_403(store, registry):
    await store.create(TaskRecord(task_id="t-1", sub=OTHER_IDENTITY))
    app = _make_app(store, registry, identity=None)
    async with await _client(app) as client:
        resp = await client.get("/requests/t-1")

    assert resp.status_code == 403


async def test_anonymous_record_is_open_by_bearer_task_id(store, registry):
    await store.create(TaskRecord(task_id="anon-1", sub=None))
    app = _make_app(store, registry, identity=None)
    async with await _client(app) as client:
        resp = await client.get("/anon_requests/anon-1")

    assert resp.status_code == 200
    assert resp.json()["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Listing: caller-owned only
# ---------------------------------------------------------------------------


async def test_listing_returns_only_caller_records(store, registry):
    await store.create(TaskRecord(task_id="mine-1", sub=IDENTITY))
    await store.create(TaskRecord(task_id="mine-2", sub=IDENTITY))
    await store.create(TaskRecord(task_id="not-mine", sub=OTHER_IDENTITY))
    await store.create(TaskRecord(task_id="anon", sub=None))  # excluded

    app = _make_app(store, registry, identity=IDENTITY)
    async with await _client(app) as client:
        resp = await client.get("/requests/")

    assert resp.status_code == 200
    ids = {task["task_id"] for task in resp.json()}
    assert ids == {"mine-1", "mine-2"}


# ---------------------------------------------------------------------------
# DELETE contract
# ---------------------------------------------------------------------------


async def test_delete_unknown_task_is_404(store, registry):
    app = _make_app(store, registry)
    async with await _client(app) as client:
        resp = await client.delete("/requests/no-such-task")

    assert resp.status_code == 404


async def test_delete_other_users_task_is_403(store, registry):
    await store.create(TaskRecord(task_id="t-1", sub=OTHER_IDENTITY))
    app = _make_app(store, registry, identity=IDENTITY)
    async with await _client(app) as client:
        resp = await client.delete("/requests/t-1")

    assert resp.status_code == 403


async def test_delete_delivered_flow_marks_destroyed_and_destroys_infra(
    store, registry, fake_im
):
    await store.create(
        TaskRecord(
            task_id="t-1",
            sub=IDENTITY,
            status=TaskStatus.SUCCESS,
            result={"url": "https://vre.example"},
            im_inf_id="infra-1",
            im_token="dispatch-token",
        )
    )
    app = _make_app(store, registry)
    async with await _client(app) as client:
        resp = await client.delete("/requests/t-1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "DESTROYED"
    assert "result" not in body
    assert fake_im.destroyed == ["infra-1"]
    record = await store.get("t-1")
    assert record.destroyed_at is not None
    # DESTROYED nulls the delivered URL: there is no artifact to point at
    assert record.result is None
    assert record.stage is None


async def test_delete_non_im_flow_invokes_vre_teardown(store, registry, monkeypatch):
    """DELETE on a delivered non-IM flow must call the VRE's own delete()
    (e.g. OSCAR cluster service teardown), best-effort."""
    seen = {"deleted": 0}

    class _Spy:
        async def delete(self):
            seen["deleted"] += 1

    monkeypatch.setattr(
        "app.routers.utils.dispatch.VREPayloadBuilder.build",
        staticmethod(lambda crate: object()),
    )
    monkeypatch.setattr(
        "app.routers.utils.dispatch.vre_factory",
        lambda **kwargs: _Spy(),
    )
    await store.create(
        TaskRecord(
            task_id="t-1",
            sub=IDENTITY,
            status=TaskStatus.SUCCESS,
            crate={"@graph": []},
            kind="oscar",
        )
    )
    app = _make_app(store, registry)
    async with await _client(app) as client:
        resp = await client.delete("/requests/t-1")

    assert resp.status_code == 200
    assert resp.json()["status"] == "DESTROYED"
    assert seen["deleted"] == 1


async def test_delete_im_backed_flow_skips_vre_teardown(
    store, registry, fake_im, monkeypatch
):
    """IM-backed flows rely on the infra destroy for teardown; the VRE hook
    must NOT fire (calling it would resurrect a deployment via setup_service)."""

    class _Spy:
        async def delete(self): ...

    called = []
    monkeypatch.setattr(
        "app.routers.utils.dispatch.vre_factory",
        lambda **kwargs: called.append(True) or _Spy(),
    )

    await store.create(
        TaskRecord(
            task_id="t-1",
            sub=IDENTITY,
            status=TaskStatus.SUCCESS,
            crate={"@graph": []},
            im_inf_id="infra-1",
            im_token="t",
        )
    )
    app = _make_app(store, registry)
    async with await _client(app) as client:
        resp = await client.delete("/requests/t-1")

    assert resp.status_code == 200
    assert fake_im.destroyed == ["infra-1"]
    assert called == []


async def test_delete_inflight_flow_cancels_and_marks_failure(
    store, registry, monkeypatch
):
    await store.create(TaskRecord(task_id="t-1", sub=IDENTITY))

    started = asyncio.Event()
    resume = asyncio.Event()

    class _Blocking(FakeAsyncIM):
        async def run(self, rp, heartbeat=None, on_inf_created=None):
            started.set()
            await resume.wait()

    blocking = _Blocking()
    monkeypatch.setattr("app.vres.base_vre.default_im_factory", lambda token: blocking)
    monkeypatch.setattr(
        "app.routers.utils.dispatch.default_im_factory", lambda token: blocking
    )

    app = _make_app(store, registry)
    async with await _client(app) as client:
        resp = await client.post("/requests/metadata_rocrate/", json=_load_crate())
        task_id = resp.json()["task_id"]
        await asyncio.wait_for(started.wait(), timeout=5)

        resp = await client.delete(f"/requests/{task_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "FAILURE"
    assert body["error"] == "cancelled by user"


async def test_delete_anonymous_flow_works_without_identity(store, registry):
    await store.create(
        TaskRecord(task_id="anon-1", sub=None, status=TaskStatus.SUCCESS)
    )
    app = _make_app(store, registry, identity=None)
    async with await _client(app) as client:
        resp = await client.delete("/anon_requests/anon-1")

    assert resp.status_code == 200
    assert resp.json()["status"] == "DESTROYED"


async def test_delete_destroyed_flow_is_idempotent(store, registry, fake_im):
    from app.status_store import _utcnow

    await store.create(
        TaskRecord(
            task_id="t-1",
            sub=IDENTITY,
            status=TaskStatus.DESTROYED,
            destroyed_at=_utcnow(),
        )
    )
    app = _make_app(store, registry)
    async with await _client(app) as client:
        resp = await client.delete("/requests/t-1")

    assert resp.status_code == 200
    assert resp.json()["status"] == "DESTROYED"
    assert fake_im.destroyed == []


# ---------------------------------------------------------------------------
# Anonymous POST
# ---------------------------------------------------------------------------


async def test_anonymous_post_creates_owner_less_record(store, registry, httpx_mock):
    httpx_mock.add_response(
        method="POST", url=GALAXY_LANDING, status_code=201, json={"uuid": "u-1"}
    )
    app = _make_app(store, registry, identity=None)
    async with await _client(app) as client:
        resp = await client.post("/anon_requests/metadata_rocrate/", json=_load_crate())

    assert resp.status_code == 202
    task_id = resp.json()["task_id"]
    await _finished(registry, task_id)

    record = await store.get(task_id)
    assert record.sub is None
    assert record.owner is None
    assert record.status == TaskStatus.SUCCESS
    # anonymous IM flows carry no credentials for resume either
    assert record.im_token is None


async def test_anonymous_records_excluded_from_owner_listing(store, registry):
    app = _make_app(store, registry, identity=IDENTITY)
    await store.create(TaskRecord(task_id="anon", sub=None))
    async with await _client(app) as client:
        resp = await client.get("/requests/")

    assert resp.json() == []
