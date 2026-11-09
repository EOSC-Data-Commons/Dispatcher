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
import os
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

import aiosqlite
import httpx

from app import http as app_http
from app.checkin import token_endpoint
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
        if self._db_path != ":memory:":
            # Same permission class as the task registry (v4 D6): the
            # refresh tokens in this table impersonate their users.
            os.chmod(self._db_path, 0o600)

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
        async with self._conn.execute("DELETE FROM credentials WHERE sub = ?", (sub,)):
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
            refresh_token=refresh_token
            or (previous.refresh_token if previous else None),
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


# ---------------------------------------------------------------------------
# Refresh exchange (D3)
# ---------------------------------------------------------------------------


async def exchange_refresh_token(
    store: CredentialStore,
    sub: str,
    *,
    token_url: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> str | None:
    """Exchange ``sub``'s stored refresh token for a fresh access token.

    Reads the user's row, POSTs ``grant_type=refresh_token`` to the
    Check-in token endpoint through the shared http/tenacity layer
    (transient failures retry; an ``invalid_grant`` 4xx fails fast), and
    writes the rotated refresh token back to the store (EGI rotates on
    every exchange; a provider that reuses tokens keeps the old one via
    the upsert COALESCE).

    Returns the fresh access token, or None when the user has no captured
    refresh token or the exchange was rejected (rotated out / revoked) —
    callers log and retry on the next scan (v4 §8.4).
    """
    record = await store.get(sub)
    if record is None or record.refresh_token is None:
        logger.warning(
            "No refresh token captured for %s — cannot exchange credentials", sub
        )
        return None

    url = token_url or token_endpoint()
    form = {
        "grant_type": "refresh_token",
        "refresh_token": record.refresh_token,
        "client_id": client_id or settings.client_id,
        "client_secret": client_secret or settings.client_secret,
    }
    try:
        response = await app_http.post(url, data=form, raise_for_status=False)
    except httpx.HTTPError as exc:
        logger.warning("Refresh-token exchange for %s failed: %s", sub, exc)
        return None

    if response.status_code != 200:
        logger.warning(
            "Refresh-token exchange for %s rejected (HTTP %d): %s",
            sub,
            response.status_code,
            response.text,
        )
        return None

    payload = response.json()
    access_token = payload.get("access_token")
    if not access_token:
        logger.warning("Refresh-token exchange for %s returned no access_token", sub)
        return None

    await store.upsert(sub, access_token, payload.get("refresh_token"))
    logger.info("Refreshed credentials for %s (rotation written back)", sub)
    return access_token
