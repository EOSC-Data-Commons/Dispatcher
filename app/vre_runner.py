"""HTTP-independent VRE flow lifecycle: execution and remote teardown.

A flow is spawned as an ``asyncio.Task`` by the dispatching handler; its
live handle sits in the process-local task registry. Status transitions
(PENDING -> PROGRESS -> SUCCESS | FAILURE) are written to the
:class:`StatusStore` — every write refreshes ``updated_at``, the janitor's
heartbeat signal.

A flow interrupted by ``DELETE`` (task cancellation) propagates
``CancelledError`` untouched: the DELETE handler owns the final status
write (DESTROYED vs FAILURE "cancelled by user"), so the two never race.
The best-effort IM and VRE remote-teardown helpers for that DELETE live
here beside execution, not in the router adapter, so the lifecycle
contract is cohesive and remains free of HTTP dependencies.
"""

import asyncio
import logging
from typing import Callable

from vre_rocrate import VREPayload

from app.status_store import StatusStore, TaskRecord, TaskStatus
from app.vres.base_vre import AsyncIMProtocol, default_im_factory, vre_factory

logger = logging.getLogger(__name__)


async def execute_flow(
    task_id: str,
    *,
    store: StatusStore,
    registry: dict[str, asyncio.Task],
    token: str,
    payload: VREPayload,
    im_factory: Callable[[str | None], AsyncIMProtocol] | None = None,
) -> None:
    """Run a single VRE flow end to end and record its outcome.

    The payload is always built by the *caller* of this function — never
    here: the dispatching handler builds it so an invalid crate fails the
    request synchronously with 400. Exactly one build site.

    A restart kills the flow outright (v4: no resume): the janitor marks
    the orphaned record FAILED("worker lost") and reaps its infra.

    Args:
        task_id: The task record id (also the registry key).
        store: Status store for progress/result persistence.
        registry: Live-task registry (entry removed on completion).
        token: Caller's access token ("" for anonymous flows).
        payload: Pre-built flow payload (REQUIRED).
        im_factory: Injectable IM factory (tests inject FakeAsyncIM).
    """
    try:
        await store.update(task_id, status=TaskStatus.PROGRESS, stage="dispatching")
        vre = vre_factory(
            token=token,
            request_id=task_id,
            status_store=store,
            payload=payload,
            im_factory=im_factory,
        )
        result = await vre.post()
        # Terminal-success transitions clear the progress stage: the flow is
        # done, there is no "current step" anymore (a frozen in-flight stage
        # like "waiting for X" would contradict the SUCCESS status).
        # FAILURE keeps its last stage on purpose — it is the context of which
        # step the flow died in.
        await store.update(
            task_id, status=TaskStatus.SUCCESS, stage=None, result={"url": result}
        )
        logger.info("Flow %s finished successfully", task_id)
    except asyncio.CancelledError:
        # DELETE owns the final status write; just stop running.
        logger.info("Flow %s cancelled", task_id)
        raise
    except Exception as exc:
        logger.exception("Flow %s failed", task_id)
        await store.update(task_id, status=TaskStatus.FAILURE, error=str(exc))
    finally:
        registry.pop(task_id, None)


async def destroy_infra_best_effort(inf_id: str, token: str) -> None:
    """Destroy an IM infrastructure, logging (never raising) failures —
    e.g. an expired user token on late DELETE (documented limitation)."""
    try:
        im = default_im_factory(token)
        try:
            await im.destroy(inf_id)
        finally:
            await im.aclose()
        logger.info("Infra %s destroyed on user request", inf_id)
    except Exception:
        logger.exception("Failed to destroy infra %s on user request", inf_id)


async def delete_vre_remote_state_best_effort(
    token: str, record: TaskRecord, store: StatusStore
) -> None:
    """Invoke the VRE's own ``delete()`` teardown (remote state left by
    ``post()`` on shared infrastructure — e.g. OSCAR cluster services),
    best-effort: failures are logged, never raised.

    The crate is gone at DELETE time (v4: never persisted), so the VRE is
    constructed by ``kind`` with the delivered URL as the only hint.
    Skipped for IM-backed flows: the infra destroy above handles their
    teardown (the VRE state lives on the VM itself), and calling
    ``delete()`` would needlessly resurrect an IM deployment via
    ``setup_service()``.
    """
    if record.im_inf_id or not record.result or not record.result.get("url"):
        return
    try:
        vre = vre_factory(
            token=token,
            request_id=record.task_id,
            status_store=store,
            kind=record.kind,
            # Teardown hint: the URL post() already delivered. Lets VREs
            # skip re-deriving their remote resource (e.g. OSCAR needs no
            # FDL re-download to learn its service name).
            delivered_url=record.result.get("url"),
        )
        await vre.delete()
        logger.info(
            "VRE session torn down for task %s (kind=%s)", record.task_id, record.kind
        )
    except Exception:
        logger.exception("VRE delete() failed for task %s", record.task_id)
