"""Task status persistence (design note: plans/async-execution-architecture-v3.md §State).

Two backends behind the :class:`StatusStore` protocol:

- :class:`SQLiteStatusStore` — production. One SQLite file in WAL mode with
  ``synchronous=FULL`` (per-commit durability by default, zero added
  services), accessed via ``aiosqlite`` whose dedicated thread + internal
  request queue give the async bridge and write serialization for free.
  Schema evolution runs through ``PRAGMA user_version`` + an ordered
  migration list from day one.
- :class:`InMemoryStatusStore` — tests.

Every write refreshes ``updated_at`` — this doubles as the janitor's
heartbeat signal. Records carry a uniform TTL (``expires_at``), filtered on
read; ``DESTROYED`` rows and expired rows are excluded from
:meth:`StatusStore.list_active`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import aiosqlite

from app.config import settings

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Task status vocabulary (terminal: SUCCESS, FAILURE, DESTROYED)."""

    PENDING = "PENDING"
    PROGRESS = "PROGRESS"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DESTROYED = "DESTROYED"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _dt_or_none(value: str | None) -> datetime | None:
    return _dt(value) if value is not None else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _json_or_none(value: str | None) -> Any:
    return json.loads(value) if value is not None else None


def _dump_or_none(value: Any) -> str | None:
    return json.dumps(value) if value is not None else None


@dataclass
class TaskRecord:
    """One row of the ``tasks`` table, in Python form.

    Slim by design (v4): no crate, no IM outputs, no per-flow token, no
    resume stage — those existed only for v3's restart-resume, which is
    dropped. ``im_inf_id`` stays: it is the infrastructure registry that
    lets cleanup find (and destroy) a half-deployed VM after a crash."""

    task_id: str
    sub: str | None = None  # owner identity: OIDC sub (anonymous flows: None)
    owner: dict[str, Any] | None = None  # {"sub", "name"} | None
    kind: str = ""
    status: TaskStatus = TaskStatus.PENDING
    stage: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    im_inf_id: str | None = None
    destroyed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        now = _utcnow()
        if self.created_at is None:
            self.created_at = now
        if self.updated_at is None:
            self.updated_at = now
        if self.expires_at is None:
            self.expires_at = self.created_at + timedelta(seconds=settings.status_ttl)

    def is_expired(self, now: datetime | None = None) -> bool:
        return self.expires_at <= (now or _utcnow())


#: Fields writable via ``StatusStore.update`` (mapped to columns; every
#: update also refreshes ``updated_at``).
_UPDATABLE_FIELDS = frozenset(
    {
        "status",
        "stage",
        "result",
        "error",
        "im_inf_id",
        "destroyed_at",
    }
)


@runtime_checkable
class StatusStore(Protocol):
    """Persistence contract consumed by routers, the flow executor and the
    recovery manager. A RESP/Postgres backend for multi-instance deployments
    is a documented future option behind this same interface."""

    async def create(self, record: TaskRecord) -> None:
        """Insert a new record (fails if ``task_id`` already exists)."""
        ...

    async def get(
        self, task_id: str, *, include_expired: bool = False
    ) -> TaskRecord | None:
        """Fetch one record; expired rows read as absent (404 semantics)
        unless ``include_expired`` is set."""
        ...

    async def list_by_sub(self, sub: str) -> list[TaskRecord]:
        """Caller-owned listing (``WHERE sub = ?``), expired rows excluded."""
        ...

    async def list_active(self) -> list[TaskRecord]:
        """Non-expired, non-DESTROYED records — the janitor's scan set."""
        ...

    async def update(self, task_id: str, **fields: Any) -> TaskRecord | None:
        """Apply a partial update (see ``_UPDATABLE_FIELDS``) and refresh
        ``updated_at``. Returns the fresh record, or None when unknown."""
        ...

    async def aclose(self) -> None:
        """Release resources (no-op for the in-memory backend)."""
        ...


# ---------------------------------------------------------------------------
# SQLite backend
# ---------------------------------------------------------------------------

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS tasks (
  task_id        TEXT PRIMARY KEY,
  sub            TEXT,
  owner_json     TEXT,
  kind           TEXT,
  status         TEXT NOT NULL,
  stage          TEXT,
  result_json    TEXT,
  error          TEXT,
  crate_json     TEXT,
  im_inf_id      TEXT,
  im_outputs_json TEXT,
  im_token       TEXT,
  resume_stage   TEXT,
  destroyed_at   TEXT,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL,
  expires_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_sub ON tasks(sub);
CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(status, updated_at);
"""

#: v4 slim: the v3 resume columns go (drop the crate, the IM outputs, the
#: per-flow token, the resume stage). No deployment carried them outside
#: prototype databases.
_MIGRATION_V2 = """
ALTER TABLE tasks DROP COLUMN crate_json;
ALTER TABLE tasks DROP COLUMN im_outputs_json;
ALTER TABLE tasks DROP COLUMN im_token;
ALTER TABLE tasks DROP COLUMN resume_stage;
"""

#: Ordered migration list: ``_MIGRATIONS[v]`` migrates schema version
#: ``v`` -> ``v + 1``; version is tracked in ``PRAGMA user_version``.
_MIGRATIONS: list[str] = [_SCHEMA_V1, _MIGRATION_V2]

_INSERT_SQL = """
INSERT INTO tasks (
  task_id, sub, owner_json, kind, status, stage, result_json, error,
  im_inf_id, destroyed_at, created_at, updated_at, expires_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_COLUMN_OF_FIELD = {
    "status": "status",
    "stage": "stage",
    "result": "result_json",
    "error": "error",
    "im_inf_id": "im_inf_id",
    "destroyed_at": "destroyed_at",
}


class SQLiteStatusStore:
    """SQLite (WAL + synchronous=FULL) production backend."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the connection and apply pending schema migrations."""
        if self._conn is not None:
            return
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=FULL")
        await self._migrate()

    async def _migrate(self) -> None:
        assert self._conn is not None
        async with self._conn.execute("PRAGMA user_version") as cur:
            row = await cur.fetchone()
            version = row[0]
        while version < len(_MIGRATIONS):
            logger.info("Applying tasks schema migration v%d", version)
            await self._conn.executescript(_MIGRATIONS[version])
            version += 1
            await self._conn.execute(f"PRAGMA user_version = {version}")
        await self._conn.commit()

    async def aclose(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _row_to_record(row: aiosqlite.Row) -> TaskRecord:
        return TaskRecord(
            task_id=row["task_id"],
            sub=row["sub"],
            owner=_json_or_none(row["owner_json"]),
            kind=row["kind"],
            status=TaskStatus(row["status"]),
            stage=row["stage"],
            result=_json_or_none(row["result_json"]),
            error=row["error"],
            im_inf_id=row["im_inf_id"],
            destroyed_at=_dt_or_none(row["destroyed_at"]),
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
            expires_at=_dt(row["expires_at"]),
        )

    # -- protocol implementation -------------------------------------------

    async def create(self, record: TaskRecord) -> None:
        async with self._conn.execute(
            _INSERT_SQL,
            (
                record.task_id,
                record.sub,
                _dump_or_none(record.owner),
                record.kind,
                record.status.value,
                record.stage,
                _dump_or_none(record.result),
                record.error,
                record.im_inf_id,
                _iso(record.destroyed_at),
                _iso(record.created_at),
                _iso(record.updated_at),
                _iso(record.expires_at),
            ),
        ):
            pass
        await self._conn.commit()

    async def get(
        self, task_id: str, *, include_expired: bool = False
    ) -> TaskRecord | None:
        async with self._conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        record = self._row_to_record(row)
        if record.is_expired() and not include_expired:
            return None
        return record

    async def list_by_sub(self, sub: str) -> list[TaskRecord]:
        async with self._conn.execute(
            "SELECT * FROM tasks WHERE sub = ? AND expires_at > ? ORDER BY created_at",
            (sub, _iso(_utcnow())),
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_record(row) for row in rows]

    async def list_active(self) -> list[TaskRecord]:
        async with self._conn.execute(
            "SELECT * FROM tasks WHERE status != ? AND expires_at > ?",
            (TaskStatus.DESTROYED.value, _iso(_utcnow())),
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_record(row) for row in rows]

    async def update(self, task_id: str, **fields: Any) -> TaskRecord | None:
        unknown = set(fields) - _UPDATABLE_FIELDS
        if unknown:
            raise ValueError(f"Cannot update task fields: {sorted(unknown)}")
        assignments: list[str] = []
        values: list[Any] = []
        for attr, value in fields.items():
            column = _COLUMN_OF_FIELD[attr]
            if attr == "result":
                value = _dump_or_none(value)
            elif attr == "status":
                value = value.value
            elif attr == "destroyed_at":
                value = _iso(value) if isinstance(value, datetime) else value
            assignments.append(f"{column} = ?")
            values.append(value)
        assignments.append("updated_at = ?")
        values.append(_iso(_utcnow()))
        values.append(task_id)
        async with self._conn.execute(
            f"UPDATE tasks SET {', '.join(assignments)} WHERE task_id = ?",
            tuple(values),
        ) as cur:
            changed = cur.rowcount
        await self._conn.commit()
        if not changed:
            return None
        return await self.get(task_id, include_expired=True)


# ---------------------------------------------------------------------------
# In-memory backend (tests)
# ---------------------------------------------------------------------------


class InMemoryStatusStore:
    """Dict-backed :class:`StatusStore` for unit tests."""

    def __init__(self) -> None:
        self._records: dict[str, TaskRecord] = {}

    async def create(self, record: TaskRecord) -> None:
        if record.task_id in self._records:
            raise ValueError(f"Task {record.task_id} already exists")
        self._records[record.task_id] = replace(record)

    async def get(
        self, task_id: str, *, include_expired: bool = False
    ) -> TaskRecord | None:
        record = self._records.get(task_id)
        if record is None:
            return None
        if record.is_expired() and not include_expired:
            return None
        return replace(record)

    async def list_by_sub(self, sub: str) -> list[TaskRecord]:
        return [
            replace(record)
            for record in self._records.values()
            if record.sub == sub and not record.is_expired()
        ]

    async def list_active(self) -> list[TaskRecord]:
        return [
            replace(record)
            for record in self._records.values()
            if record.status != TaskStatus.DESTROYED and not record.is_expired()
        ]

    async def update(self, task_id: str, **fields: Any) -> TaskRecord | None:
        unknown = set(fields) - _UPDATABLE_FIELDS
        if unknown:
            raise ValueError(f"Cannot update task fields: {sorted(unknown)}")
        record = self._records.get(task_id)
        if record is None:
            return None
        for attr, value in fields.items():
            setattr(record, attr, value)
        record.updated_at = _utcnow()
        return replace(record)

    async def aclose(self) -> None:
        pass
