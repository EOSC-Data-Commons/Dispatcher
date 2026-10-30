"""Unit tests for app.status_store — CRUD, owner index, TTL, infra fields,
for both the SQLite (WAL) and in-memory backends."""

import aiosqlite
import pytest

from app.status_store import (
    InMemoryStatusStore,
    ResumeStage,
    SQLiteStatusStore,
    TaskRecord,
    TaskStatus,
)


@pytest.fixture(params=["sqlite", "memory"])
async def store(request, tmp_path):
    if request.param == "sqlite":
        store = SQLiteStatusStore(str(tmp_path / "tasks.db"))
        await store.connect()
        yield store
        await store.aclose()
    else:
        yield InMemoryStatusStore()


def _record(task_id="task-1", **kwargs) -> TaskRecord:
    kwargs.setdefault("sub", "egi:1234-abcd")
    kwargs.setdefault(
        "owner", {"sub": "egi:1234-abcd", "name": "Jane", "email": "j@x.io"}
    )
    kwargs.setdefault("kind", "galaxy")
    return TaskRecord(task_id=task_id, **kwargs)


class TestCRUD:
    async def test_create_and_get_roundtrip(self, store):
        record = _record(
            crate={"@graph": []},
            result={"url": "https://vre.example"},
            stage="booting",
            error="oops",
        )

        await store.create(record)
        fetched = await store.get(record.task_id)

        assert fetched is not None
        assert fetched.task_id == record.task_id
        assert fetched.sub == record.sub
        assert fetched.owner == record.owner
        assert fetched.kind == "galaxy"
        assert fetched.status == TaskStatus.PENDING
        assert fetched.stage == "booting"
        assert fetched.result == {"url": "https://vre.example"}
        assert fetched.error == "oops"
        assert fetched.crate == {"@graph": []}
        assert fetched.created_at is not None
        assert fetched.updated_at is not None
        assert fetched.expires_at is not None

    async def test_get_unknown_returns_none(self, store):
        assert await store.get("nope") is None

    async def test_anonymous_record_roundtrip(self, store):
        record = TaskRecord(task_id="anon-1", kind="jupyter")

        await store.create(record)
        fetched = await store.get("anon-1")

        assert fetched.sub is None
        assert fetched.owner is None
        assert fetched.im_inf_id is None
        assert fetched.resume_stage == ResumeStage.NONE

    async def test_update_status_stage_result_error(self, store):
        await store.create(_record())

        updated = await store.update(
            "task-1",
            status=TaskStatus.FAILURE,
            stage="deploy",
            error="kaput",
        )

        assert updated.status == TaskStatus.FAILURE
        assert updated.stage == "deploy"
        assert updated.error == "kaput"
        fetched = await store.get("task-1")
        assert fetched.status == TaskStatus.FAILURE
        assert fetched.error == "kaput"

    async def test_update_result_and_outputs_json(self, store):
        await store.create(_record())

        await store.update(
            "task-1",
            status=TaskStatus.SUCCESS,
            result={"url": "https://vre.example"},
            im_outputs={"url": "https://vre.example", "extra": 42},
        )

        fetched = await store.get("task-1")
        assert fetched.status == TaskStatus.SUCCESS
        assert fetched.result["url"] == "https://vre.example"
        assert fetched.im_outputs == {"url": "https://vre.example", "extra": 42}

    async def test_update_unknown_task_returns_none(self, store):
        assert await store.update("nope", status=TaskStatus.FAILURE) is None

    async def test_update_rejects_unknown_fields(self, store):
        await store.create(_record())

        with pytest.raises(ValueError):
            await store.update("task-1", sub="other:999")

    async def test_update_refreshes_updated_at(self, store, monkeypatch):
        from app import status_store as ss

        past = ss._utcnow()
        await store.create(_record())

        later = past.replace(year=past.year + 1)
        monkeypatch.setattr(ss, "_utcnow", lambda: later)
        updated = await store.update("task-1", stage="still going")

        assert updated.updated_at == later

    async def test_heartbeat_write_with_no_fields(self, store):
        await store.create(_record())

        updated = await store.update("task-1")

        assert updated is not None
        assert updated.status == TaskStatus.PENDING


class TestOwnerIndex:
    async def test_list_by_sub_returns_only_callers_records(self, store):
        await store.create(_record("t1", sub="egi:1"))
        await store.create(_record("t2", sub="egi:2"))
        await store.create(_record("t3", sub="egi:1"))
        await store.create(TaskRecord(task_id="anon", kind="x"))  # anonymous

        mine = await store.list_by_sub("egi:1")

        assert {r.task_id for r in mine} == {"t1", "t3"}

    async def test_list_by_sub_empty(self, store):
        await store.create(_record("t1", sub="egi:1"))

        assert await store.list_by_sub("egi:nobody") == []


class TestTTL:
    async def _expired(self, store, task_id="old-1"):
        from datetime import timedelta

        from app.status_store import _utcnow

        record = _record(task_id)
        record.expires_at = _utcnow() - timedelta(seconds=1)
        await store.create(record)
        return record

    async def test_expired_reads_as_absent(self, store):
        await self._expired(store)

        assert await store.get("old-1") is None

    async def test_expired_visible_with_flag(self, store):
        await self._expired(store)

        fetched = await store.get("old-1", include_expired=True)
        assert fetched is not None
        assert fetched.task_id == "old-1"

    async def test_expired_excluded_from_owner_listing(self, store):
        await self._expired(store)
        await store.create(_record("fresh", sub="egi:1234-abcd"))

        mine = await store.list_by_sub("egi:1234-abcd")

        assert {r.task_id for r in mine} == {"fresh"}

    async def test_expired_excluded_from_active_scan(self, store):
        await self._expired(store)
        await store.create(_record("fresh"))

        active = await store.list_active()

        assert {r.task_id for r in active} == {"fresh"}


class TestInfraFields:
    async def test_im_fields_persist(self, store):
        await store.create(_record())

        await store.update(
            "task-1",
            im_inf_id="infra-42",
            resume_stage=ResumeStage.IM_WAIT,
        )

        fetched = await store.get("task-1")
        assert fetched.im_inf_id == "infra-42"
        assert fetched.resume_stage == ResumeStage.IM_WAIT

    async def test_im_token_persisted_for_resume(self, store):
        record = _record(im_token="bearer-xyz")

        await store.create(record)
        fetched = await store.get("task-1")

        assert fetched.im_token == "bearer-xyz"

    async def test_destroyed_at_marked(self, store):
        from app.status_store import _utcnow

        await store.create(_record(status=TaskStatus.SUCCESS))
        now = _utcnow()

        await store.update("task-1", status=TaskStatus.DESTROYED, destroyed_at=now)

        fetched = await store.get("task-1")
        assert fetched.status == TaskStatus.DESTROYED
        assert fetched.destroyed_at == now

    async def test_active_scan_excludes_destroyed(self, store):
        from app.status_store import _utcnow

        await store.create(_record("t1", status=TaskStatus.SUCCESS))
        await store.create(
            _record("t2", status=TaskStatus.DESTROYED, destroyed_at=_utcnow())
        )

        active = await store.list_active()

        assert {r.task_id for r in active} == {"t1"}

    async def test_active_scan_includes_failed_with_infra(self, store):
        await store.create(_record("t1", status=TaskStatus.FAILURE))

        await store.update("t1", im_inf_id="infra-9")

        active = await store.list_active()
        assert {r.task_id for r in active} == {"t1"}
        assert active[0].destroyed_at is None


class TestSQLiteSpecifics:
    async def test_wal_and_full_synchronous_pragmas(self, tmp_path):
        db_path = str(tmp_path / "pragmas.db")
        store = SQLiteStatusStore(db_path)
        await store.connect()

        async with aiosqlite.connect(db_path) as conn:
            async with conn.execute("PRAGMA journal_mode") as cur:
                (journal_mode,) = await cur.fetchone()
            async with conn.execute("PRAGMA synchronous") as cur:
                (synchronous,) = await cur.fetchone()

        await store.aclose()
        assert journal_mode.lower() == "wal"
        assert synchronous == 2  # FULL

    async def test_user_version_set_after_migration(self, tmp_path):
        db_path = str(tmp_path / "versioned.db")
        store = SQLiteStatusStore(db_path)
        await store.connect()

        async with aiosqlite.connect(db_path) as conn:
            async with conn.execute("PRAGMA user_version") as cur:
                (version,) = await cur.fetchone()

        await store.aclose()
        assert version == 1

    async def test_reconnect_runs_migrations_idempotently(self, tmp_path):
        db_path = str(tmp_path / "idempotent.db")
        store = SQLiteStatusStore(db_path)
        await store.connect()
        await store.create(_record("persisted"))
        await store.aclose()

        # Reopen: schema init must not clobber existing data.
        store2 = SQLiteStatusStore(db_path)
        await store2.connect()

        fetched = await store2.get("persisted")
        await store2.aclose()
        assert fetched is not None
        assert fetched.task_id == "persisted"
