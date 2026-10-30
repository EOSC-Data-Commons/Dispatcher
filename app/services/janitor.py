"""Recovery manager (janitor): startup scan + periodic loop.

Per the async-execution design note's durability model ("resume, don't queue"):

- PROGRESS + resume_stage=IM_WAIT + im_inf_id + no live local task ⇒
  **respawn continuation**: rebuild the payload from crate_json, re-poll IM
  state (the server kept provisioning), fetch outputs, run VRE steps →
  SUCCESS, with the same failure semantics as a live flow.
- Stale (updated_at older than stale_task_timeout), non-resumable ⇒
  FAILED("worker lost").
- FAILED with im_inf_id & undestroyed ⇒ destroy (covers post-IM crashes and
  zip+IM degrade; token expiry here is the design note's documented
  limitation and surfaces as a warning each scan).
- infra_max_lifetime set ⇒ TTL-destroy of delivered VMs — OFF by default.
- T2 (Jupyter/MDDash) resume is out of scope: restart ⇒ FAILED + resubmit.
"""

import asyncio
import logging
from datetime import datetime

from vre_rocrate import VREPayloadBuilder

from app.config import settings
from app.status_store import ResumeStage, StatusStore, TaskRecord, TaskStatus, _utcnow
from app.vre_runner import execute_flow
from app.vres.base_vre import AsyncIMProtocol, default_im_factory
from typing import Callable

logger = logging.getLogger(__name__)


class RecoveryManager:
    def __init__(
        self,
        store: StatusStore,
        registry: dict[str, asyncio.Task],
        *,
        im_factory: Callable[[str | None], AsyncIMProtocol] | None = None,
        interval: float | None = None,
        stale_timeout: float | None = None,
        infra_max_lifetime: float | None = None,
    ):
        self._store = store
        self._registry = registry
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
        self._stopped = asyncio.Event()

    def stop(self) -> None:
        self._stopped.set()

    async def run_periodic(self) -> None:
        """Startup scan, then a scan every ``janitor_interval`` seconds."""
        while not self._stopped.is_set():
            try:
                await self.scan_once()
            except Exception:
                logger.exception("Recovery manager scan failed")
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    async def scan_once(self) -> None:
        """One reconciliation pass over the active (non-TTL-expired) records."""
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
            if (
                record.status == TaskStatus.PROGRESS
                and record.resume_stage == ResumeStage.IM_WAIT
                and record.im_inf_id
            ):
                await self._respawn(record)
                return
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

    async def _respawn(self, record: TaskRecord) -> None:
        """Respawn an IM-in-flight continuation (resume, don't queue)."""
        try:
            # The respawn path is this entry point's single payload-build site:
            # the recovery manager rebuilds from the persisted crate_json, just
            # as the dispatching handler builds from the request body.
            payload = VREPayloadBuilder.build(record.crate)
        except Exception as exc:
            logger.error(
                "Task %s marked FAILED: crate no longer builds a payload "
                "on resume (%s)",
                record.task_id,
                exc,
            )
            await self._store.update(
                record.task_id,
                status=TaskStatus.FAILURE,
                error=f"invalid crate on resume: {exc}",
            )
            return
        logger.info(
            "Respawning continuation of task %s from infra %s",
            record.task_id,
            record.im_inf_id,
        )
        task = asyncio.create_task(
            execute_flow(
                record.task_id,
                store=self._store,
                registry=self._registry,
                token=record.im_token or "",
                payload=payload,
                resume_eligible=True,
                resume_inf_id=record.im_inf_id,
                im_factory=self._im_factory,
            )
        )
        self._registry[record.task_id] = task

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

    async def _reap_infra(
        self,
        record: TaskRecord,
        now: datetime,
        destroyed_status: TaskStatus | None = None,
    ) -> None:
        """Best-effort infra destroy; repeated on later scans when the call
        fails (e.g. expired user token — documented limitation)."""
        try:
            im = self._im_factory(record.im_token)
            try:
                await im.destroy(record.im_inf_id)
            finally:
                await im.aclose()
        except Exception as exc:
            logger.warning(
                "Failed to destroy infra %s of task %s: %s",
                record.im_inf_id,
                record.task_id,
                exc,
            )
            return
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
