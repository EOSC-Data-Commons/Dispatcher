"""Recovery manager (janitor): startup scan + periodic loop.

Durability model (v4: no resume — a restart kills the flow):

- At startup, a PENDING/PROGRESS record with no live local task is an
  orphan by definition ⇒ FAILED("worker lost") immediately, its infra
  reaped. No grace period: no second worker can own the flow.
- Periodic: stale in-flight flows (task disappeared without writing an
  outcome) ⇒ same FAILED("worker lost"); FAILED with im_inf_id &
  undestroyed ⇒ destroy, retrying on later scans when the call fails;
  infra_max_lifetime set ⇒ TTL-destroy of delivered VMs — OFF by default.

Destroy auth (v4 §8): reaps exchange the owner's refresh token
(credential store, D2/D3) for a fresh access token; no/rotated-out
refresh token ⇒ log and retry next scan.
"""

import asyncio
import logging
from datetime import datetime

from app.config import settings
from app.credentials import CredentialStore, exchange_refresh_token
from app.status_store import StatusStore, TaskRecord, TaskStatus, _utcnow
from app.vres.base_vre import AsyncIMProtocol, default_im_factory
from typing import Callable

logger = logging.getLogger(__name__)


class RecoveryManager:
    def __init__(
        self,
        store: StatusStore,
        registry: dict[str, asyncio.Task],
        *,
        credential_store: CredentialStore | None = None,
        im_factory: Callable[[str | None], AsyncIMProtocol] | None = None,
        interval: float | None = None,
        stale_timeout: float | None = None,
        infra_max_lifetime: float | None = None,
        reap_failure_threshold: int | None = None,
    ):
        self._store = store
        self._registry = registry
        self._credentials = credential_store
        self._im_factory = im_factory or default_im_factory
        self._interval = interval if interval is not None else settings.janitor_interval
        self._stale_timeout = (
            stale_timeout if stale_timeout is not None else settings.stale_task_timeout
        )
        self._infra_max_lifetime = (
            infra_max_lifetime
            if infra_max_lifetime is not None
            else settings.infra_max_lifetime
        )
        self._reap_failure_threshold = (
            reap_failure_threshold
            if reap_failure_threshold is not None
            else settings.reap_failure_threshold
        )
        #: Per-record reap attempt counters (task_id -> consecutive
        #: failures) and the alerting surface (D6): a reap-failure counter
        #: plus the worklist of records stuck past the threshold.
        self._reap_attempts: dict[str, int] = {}
        self.reap_failures = 0
        self._stopped = asyncio.Event()

    @property
    def reap_worklist(self) -> list[str]:
        """Records whose infra destroy kept failing past the threshold —
        the visible worklist for operators (each entry is a task_id with
        live paid infrastructure the janitor cannot reap)."""
        return [
            task_id
            for task_id, attempts in self._reap_attempts.items()
            if attempts >= self._reap_failure_threshold
        ]

    def stop(self) -> None:
        self._stopped.set()

    async def run_periodic(self) -> None:
        """A scan every ``janitor_interval`` seconds (the startup scan is
        :meth:`startup_scan`, run once from the app lifespan)."""
        while not self._stopped.is_set():
            try:
                await self.scan_once()
            except Exception:
                logger.exception("Recovery manager scan failed")
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    async def startup_scan(self) -> None:
        """The restart rule (v4): a PENDING/PROGRESS record with no live
        local task is an orphan *by definition* — the process that ran it
        just restarted, and no second worker can own the flow. Marked
        FAILED("worker lost") immediately (no stale grace period); its
        infra is reaped. Leftover FAILED-but-undestroyed infra from the
        previous run is reaped here too (retrying on later scans if the
        destroy call fails)."""
        records = await self._store.list_active()
        orphans = 0
        for record in records:
            if self._registry.get(record.task_id) is not None:
                continue
            try:
                if record.status in (TaskStatus.PENDING, TaskStatus.PROGRESS):
                    await self._mark_worker_lost(record)
                    orphans += 1
                elif (
                    record.status == TaskStatus.FAILURE
                    and record.im_inf_id
                    and not record.destroyed_at
                ):
                    await self._reap_infra(record, _utcnow())
            except Exception:
                logger.exception("Startup reconcile failed for task %s", record.task_id)
        if orphans:
            logger.warning(
                "Startup scan: %d orphaned flow(s) marked FAILED (worker lost)",
                orphans,
            )

    async def scan_once(self) -> None:
        """One periodic reconciliation pass over the active (non-expired)
        records: stale in-flight flows (task disappeared without writing an
        outcome), reap retries, TTL destroys."""
        records = await self._store.list_active()
        now = _utcnow()
        for record in records:
            task = self._registry.get(record.task_id)
            if task is not None and not task.done():
                # A live local task owns the flow and its heartbeats.
                continue
            try:
                await self._reconcile(record, now)
            except Exception:
                logger.exception("Failed to reconcile task %s", record.task_id)

    # ------------------------------------------------------------------
    # Reconciliation rules
    # ------------------------------------------------------------------

    async def _reconcile(self, record: TaskRecord, now: datetime) -> None:
        if record.status in (TaskStatus.PENDING, TaskStatus.PROGRESS):
            if self._is_stale(record, now):
                await self._mark_worker_lost(record)
        elif (
            record.status == TaskStatus.FAILURE
            and record.im_inf_id
            and not record.destroyed_at
        ):
            await self._reap_infra(record, now)
        elif (
            record.status == TaskStatus.SUCCESS
            and record.im_inf_id
            and not record.destroyed_at
            and self._infra_ttl_exceeded(record, now)
        ):
            # Delivered-VM TTL destroy (off unless infra_max_lifetime is set).
            await self._reap_infra(record, now, destroyed_status=TaskStatus.DESTROYED)

    def _is_stale(self, record: TaskRecord, now: datetime) -> bool:
        age = (now - record.updated_at).total_seconds()
        return age > self._stale_timeout

    def _infra_ttl_exceeded(self, record: TaskRecord, now: datetime) -> bool:
        if self._infra_max_lifetime is None:
            return False
        age = (now - record.created_at).total_seconds()
        return age > self._infra_max_lifetime

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def _mark_worker_lost(self, record: TaskRecord) -> None:
        logger.warning(
            "Task %s marked FAILED: stale heartbeat (worker lost)", record.task_id
        )
        await self._store.update(
            record.task_id,
            status=TaskStatus.FAILURE,
            error="worker lost",
        )
        if record.im_inf_id and not record.destroyed_at:
            await self._reap_infra(record, _utcnow())

    def _count_reap_failure(self, record: TaskRecord, reason: str, *args) -> None:
        """A reap did not happen (auth gap or destroy failure): count it,
        retry next scan, and escalate to ERROR + the worklist past the
        threshold — warning-forever is not alerting (v4 D6)."""
        self.reap_failures += 1
        attempts = self._reap_attempts.get(record.task_id, 0) + 1
        self._reap_attempts[record.task_id] = attempts
        log = (
            logger.error if attempts >= self._reap_failure_threshold else logger.warning
        )
        log(
            "Infra %s of task %s NOT reaped (attempt %d): " + reason,
            record.im_inf_id,
            record.task_id,
            attempts,
            *args,
        )

    async def _reap_infra(
        self,
        record: TaskRecord,
        now: datetime,
        destroyed_status: TaskStatus | None = None,
    ) -> None:
        """Best-effort infra destroy; repeated on later scans when the call
        fails. Auth via the owner's refresh token (v4 §8): the per-flow
        token is gone with the record slim."""
        token: str | None = None
        if self._credentials is not None and record.sub is not None:
            token = await exchange_refresh_token(self._credentials, record.sub)
            if token is None:
                self._count_reap_failure(
                    record, "no usable credentials for sub %s", record.sub
                )
                return
        try:
            im = self._im_factory(token)
            try:
                await im.destroy(record.im_inf_id)
            finally:
                await im.aclose()
        except Exception as exc:
            self._count_reap_failure(record, "destroy failed: %s", exc)
            return
        self._reap_attempts.pop(record.task_id, None)
        logger.info(
            "Reaped orphaned infra %s of task %s", record.im_inf_id, record.task_id
        )
        # The record may have changed status since the scan snapshot (e.g.
        # just marked worker-lost): only the destroy bookkeeping is written
        # unless an explicit target status was requested.
        fields: dict = {"destroyed_at": now}
        if destroyed_status is not None:
            fields["status"] = destroyed_status
            if destroyed_status == TaskStatus.DESTROYED:
                # Match delete_flow: DESTROYED clears the progress stage and
                # nulls the delivered URL (the artifact no longer exists).
                fields["stage"] = None
                fields["result"] = None
        await self._store.update(record.task_id, **fields)
