"""Shared flow executor: one asyncio orchestrator per flow, zero Celery.

Spawned as an ``asyncio.Task`` by the dispatching handler (and by the
recovery manager for resume); the live handle sits in the process-local
task registry.  Status transitions (PENDING -> PROGRESS -> SUCCESS |
FAILURE) are written to the :class:`StatusStore` — every write refreshes
``updated_at``, the janitor's heartbeat signal.

A flow interrupted by ``DELETE`` (task cancellation) propagates
``CancelledError`` untouched: the DELETE handler owns the final status
write (DESTROYED vs FAILURE "cancelled by user"), so the two never race.
"""

import asyncio
import logging
from typing import Callable

from vre_rocrate import VREPayload

from app.status_store import StatusStore, TaskStatus
from app.vres.base_vre import AsyncIMProtocol, vre_factory

logger = logging.getLogger(__name__)


async def execute_flow(
    task_id: str,
    *,
    store: StatusStore,
    registry: dict[str, asyncio.Task],
    token: str,
    payload: VREPayload,
    resume_eligible: bool = False,
    resume_inf_id: str | None = None,
    im_factory: Callable[[str | None], AsyncIMProtocol] | None = None,
) -> None:
    """Run a single VRE flow end to end and record its outcome.

    The payload is always built by the *caller* of this function — never
    here: the dispatching handler builds it so an invalid crate fails the
    request synchronously with 400, and the recovery manager rebuilds it
    from the record's crate_json at respawn. Exactly one build site per
    entry point.

    Args:
        task_id: The task record id (also the registry key).
        store: Status store for progress/result persistence.
        registry: Live-task registry (entry removed on completion).
        token: Caller's access token ("" for anonymous flows).
        payload: Pre-built flow payload (REQUIRED).
        resume_eligible: Metadata-only IM flows get ``resume_stage=IM_WAIT``
            at create; zip+IM flows degrade to FAILED on restart.
        resume_inf_id: Set by the janitor continuation: the IM server kept
            provisioning; re-poll instead of re-creating.
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
            resume_eligible=resume_eligible,
            resume_inf_id=resume_inf_id,
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
