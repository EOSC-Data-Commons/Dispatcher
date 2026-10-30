"""Per-user VRE credentials (v4 design note, §8): the refresh-token store.

Purpose: the ONLY long-lived per-user data. Cleanup runs after the dispatch
that started it has ended (janitor reaps, orphan destroys), when the
caller's access token (~1 h) is long gone. At login we therefore capture
the EGI refresh token plus the access token, keyed by OIDC ``sub``;
:meth:`CredentialStore.upsert` is fed from the
:func:`app.security.on_login_tokens` login seam, and cleanup exchanges the
refresh token for a fresh access token (:func:`app.credentials.exchange` —
D3) whenever it needs IM credentials.

Two backends behind the :class:`CredentialStore` protocol, mirroring
:mod:`app.status_store`:

- :class:`SQLiteCredentialStore` — production. Same SQLite file as the
  task records (``settings.db_path``): one file to back up, one permission
  class to protect. Owns its own connection (WAL allows several) and a
  single idempotent ``CREATE TABLE`` — no ``user_version`` migrations here,
  the status store owns that pragma on the shared file.
- :class:`InMemoryCredentialStore` — tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

import aiosqlite

from app.config import settings

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


#: Access tokens live ~1 h (Check-in issues 3600 s tokens — validated
#: live, see app/security.py). The stored ``expires_at`` records when the
#: stored access token stops being usable, so cleanup can prefer a refresh
#: exchange over a stale token.
ACCESS_TOKEN_TTL = 3600


@dataclass(frozen=True)
class CredentialRecord:
    """One row of the ``credentials`` table, in Python form."""

    sub: str
    access_token: str
    refresh_token: str | None
    updated_at: datetime
    expires_at: datetime

    def is_expired(self, now: datetime | None = None) -> bool:
        return self.expires_at <= (now or _utcnow())


@runtime_checkable
class CredentialStore(Protocol):
    """Persistence contract for per-user VRE credentials."""

    async def upsert(
        self, sub: str, access_token: str, refresh_token: str | None
    ) -> None:
        """Write the freshest login tokens for ``sub``.

        A ``None`` refresh token (login without one) keeps the previously
        captured refresh token: a later re-login must not silently drop
        the janitor's only credential for that user.
        """
        ...

    async def get(self, sub: str) -> CredentialRecord | None:
        """The stored credentials for ``sub``, or None when never captured."""
        ...

    async def delete(self, sub: str) -> None:
        """Forget ``sub`` (revoked/rotated-out credentials, manual cleanup)."""
        ...

    async def aclose(self) -> None:
        """Release resources (no-op for the in-memory backend)."""
        ...


# ---------------------------------------------------------------------------
# SQLite backend
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS credentials (
  sub            TEXT PRIMARY KEY,
  access_token   TEXT NOT NULL,
  refresh_token  TEXT,
  updated_at     TEXT NOT NULL,
  expires_at     TEXT NOT NULL
);
"""

_UPSERT_SQL = """
INSERT INTO credentials (sub, access_token, refresh_token, updated_at, expires_at)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(sub) DO UPDATE SET
  access_token = excluded.access_token,
  refresh_token = COALESCE(excluded.refresh_token, credentials.refresh_token),
  updated_at = excluded.updated_at,
  expires_at = excluded.expires_at
"""


def _iso(value: datetime) -> str:
    return value.isoformat()


class SQLiteCredentialStore:
    """SQLite backend; same file as the task records by default."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self._conn is not None:
            return
        from pathlib import Path

        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=FULL")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def aclose(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @staticmethod
    def _row_to_record(row: aiosqlite.Row) -> CredentialRecord:
        return CredentialRecord(
            sub=row["sub"],
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
        )

    async def upsert(
        self, sub: str, access_token: str, refresh_token: str | None
    ) -> None:
        now = _utcnow()
        async with self._conn.execute(
            _UPSERT_SQL,
            (
                sub,
                access_token,
                refresh_token,
                _iso(now),
                _iso(now + timedelta(seconds=ACCESS_TOKEN_TTL)),
            ),
        ):
            pass
        await self._conn.commit()

    async def get(self, sub: str) -> CredentialRecord | None:
        async with self._conn.execute(
            "SELECT * FROM credentials WHERE sub = ?", (sub,)
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_record(row) if row is not None else None

    async def delete(self, sub: str) -> None:
        async with self._conn.execute(
            "DELETE FROM credentials WHERE sub = ?", (sub,)
        ):
            pass
        await self._conn.commit()


# ---------------------------------------------------------------------------
# In-memory backend (tests)
# ---------------------------------------------------------------------------


class InMemoryCredentialStore:
    """Dict-backed :class:`CredentialStore` for unit tests."""

    def __init__(self) -> None:
        self._records: dict[str, CredentialRecord] = {}

    async def connect(self) -> None:
        pass

    async def upsert(
        self, sub: str, access_token: str, refresh_token: str | None
    ) -> None:
        previous = self._records.get(sub)
        now = _utcnow()
        self._records[sub] = CredentialRecord(
            sub=sub,
            access_token=access_token,
            # Same COALESCE rule as the SQLite backend.
            refresh_token=refresh_token or (previous.refresh_token if previous else None),
            updated_at=now,
            expires_at=now + timedelta(seconds=ACCESS_TOKEN_TTL),
        )

    async def get(self, sub: str) -> CredentialRecord | None:
        record = self._records.get(sub)
        return replace(record) if record is not None else None

    async def delete(self, sub: str) -> None:
        self._records.pop(sub, None)

    async def aclose(self) -> None:
        pass
