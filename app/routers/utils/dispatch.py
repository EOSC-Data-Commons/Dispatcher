"""Shared dispatch/read/delete logic for the request routers.

Contract (design note: async-execution-architecture-v3.md):

- POSTs build the payload in the handler ⇒ invalid crate fails
  synchronously with 400, valid requests get 202 {task_id} immediately and
  the flow runs as an in-process asyncio task.
- GET unknown task_id → 404; owner mismatch → 403; anonymous flows
  (owner=NULL) stay open — the task_id acts as bearer credential and is
  excluded from listings.
- DELETE cancels the local task, destroys infra if im_inf_id, then marks
  DESTROYED (delivered) or FAILURE "cancelled by user" (in-flight).

Identity (Auth Design 1): every protected handler receives the caller's
own verified token from ``app.security.oauth2_scheme`` and passes it in;
anonymous routers pass an empty token. No middleware, no shared state.
"""

import asyncio
import logging
import uuid

from fastapi import HTTPException, Request
from vre_rocrate import VREPayloadBuilder

from app import security
from app.status_store import StatusStore, TaskRecord, TaskStatus, _utcnow
from app.vre_runner import execute_flow
from app.vres.base_vre import default_im_factory, vre_factory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# App-state accessors
# ---------------------------------------------------------------------------


def get_store(request: Request) -> StatusStore:
    return request.app.state.status_store


def get_registry(request: Request) -> dict[str, asyncio.Task]:
    return request.app.state.tasks


# ---------------------------------------------------------------------------
# Caller identity (Auth Design 1: per-request verified token)
# ---------------------------------------------------------------------------


def caller_identity(token: str) -> tuple[str | None, dict | None]:
    """Owner identity from the request's own verified access token: OIDC
    ``sub`` plus display name; (None, None) for anonymous callers (empty
    token). ``security.verify`` is local JWT verification (JWKS cached) —
    no userinfo round-trip."""
    if not token:
        return None, None
    user = security.verify(token)
    owner = {"sub": user.sub, "name": user.name}
    return user.sub, owner


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _build_payload(crate: dict, file_bytes_map: dict[str, bytes] | None):
    """Build the VRE payload synchronously ⇒ invalid crate is a 400."""
    try:
        return VREPayloadBuilder.build(crate, file_bytes_map)
    except Exception as exc:
        logger.info("Invalid RO-Crate rejected: %s", exc)
        raise HTTPException(status_code=400, detail=f"Invalid RO-Crate: {exc}")


def _is_im_backed(payload) -> bool:
    """Whether the payload's workflow targets an IM-deployed runtime."""
    rp = payload.workflow.runtime_platform
    return rp is not None and not isinstance(rp, str) and rp.install_url is not None


async def dispatch_flow(
    request: Request,
    token: str,
    *,
    crate: dict,
    file_bytes_map: dict[str, bytes] | None,
    anonymous: bool = False,
) -> str:
    """Validate, persist and spawn a flow; returns the new task_id.

    ``token`` is the caller's own verified access token (from
    ``oauth2_scheme``); empty for anonymous flows."""
    store = get_store(request)
    registry = get_registry(request)

    payload = _build_payload(crate, file_bytes_map)
    if not vre_factory.is_registered(payload.programming_language):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported workflow language {payload.programming_language}",
        )

    if anonymous:
        # Anonymous flows: owner=NULL, no caller credentials.
        sub, owner, token = None, None, ""
    else:
        sub, owner = caller_identity(token)

    # Resume eligibility: metadata-only IM flows. A zip+IM flow executes
    # normally but degrades to FAILED + orphan-reap on restart (file bytes
    # are never persisted). The user token is persisted for resume-eligible
    # flows only — IM lifecycle ops after a restart need it (see the design
    # note's open discussion on expiring tokens).
    resume_eligible = file_bytes_map is None and _is_im_backed(payload)

    record = TaskRecord(
        task_id=uuid.uuid4().hex,
        sub=sub,
        owner=owner,
        kind=payload.programming_language,
        crate=crate,
        im_token=(token or None) if resume_eligible else None,
    )
    await store.create(record)

    task = asyncio.create_task(
        execute_flow(
            record.task_id,
            store=store,
            registry=registry,
            token=token,
            payload=payload,
            resume_eligible=resume_eligible,
        )
    )
    registry[record.task_id] = task
    logger.info("Task created: %s (kind=%s)", record.task_id, record.kind)
    return record.task_id


# ---------------------------------------------------------------------------
# Read / owner enforcement
# ---------------------------------------------------------------------------


def public_record(record: TaskRecord) -> dict:
    """The GET/DELETE response shape: {task_id, status, stage?, result?, error?}.

    A DESTROYED record still carries ``result`` in the store (audit value:
    "what did we just tear down?"), but it is suppressed in responses — the
    artifact no longer exists and returning a dead URL would misrepresent
    the state."""
    body: dict = {"task_id": record.task_id, "status": record.status.value}
    if record.stage is not None:
        body["stage"] = record.stage
    if record.result is not None and record.status != TaskStatus.DESTROYED:
        body["result"] = record.result
    if record.error is not None:
        body["error"] = record.error
    return body


def enforce_owner(record: TaskRecord, token: str) -> None:
    """403 on owner mismatch; anonymous (owner=NULL) records stay open —
    the task_id acts as bearer credential."""
    if record.sub is None:
        return
    sub, _ = caller_identity(token)
    if sub != record.sub:
        raise HTTPException(status_code=403, detail="Not the task owner")


async def get_owned_record(request: Request, token: str, task_id: str) -> TaskRecord:
    store = get_store(request)
    record = await store.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Unknown task_id")
    enforce_owner(record, token)
    return record


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


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

    Skipped for IM-backed flows: the infra destroy just above handles their
    teardown (the VRE state lives on the VM itself), and calling ``delete()``
    would needlessly resurrect an IM deployment via ``setup_service()``.
    """
    if record.im_inf_id or record.crate is None:
        return
    try:
        payload = VREPayloadBuilder.build(record.crate)
        vre = vre_factory(
            token=token,
            request_id=record.task_id,
            status_store=store,
            payload=payload,
            # Teardown hint: the URL post() already delivered. Lets VREs skip
            # re-deriving their remote resource (e.g. OSCAR needs no FDL
            # re-download to learn its service name).
            delivered_url=(record.result or {}).get("url") if record.result else None,
        )
        await vre.delete()
        logger.info(
            "VRE session torn down for task %s (kind=%s)", record.task_id, record.kind
        )
    except Exception:
        logger.exception("VRE delete() failed for task %s", record.task_id)


async def delete_flow(request: Request, token: str, task_id: str) -> dict:
    """Cancel local work, destroy infra if any, then mark the terminal state:
    DESTROYED when delivered, FAILURE "cancelled by user" when in-flight."""
    store = get_store(request)
    registry = get_registry(request)

    record = await get_owned_record(request, token, task_id)

    if record.status == TaskStatus.DESTROYED:
        # Repeat DELETE of a torn-down flow is idempotent.
        return public_record(record)

    task = registry.pop(task_id, None)
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    if record.im_inf_id:
        await destroy_infra_best_effort(record.im_inf_id, token)
    else:
        # Non-IM flows may still have remote state (OSCAR services, …) —
        # best-effort VRE teardown; IM-backed flows rely on the infra destroy.
        await delete_vre_remote_state_best_effort(token, record, store)

    if record.status == TaskStatus.SUCCESS:
        # Null the delivered URL: a DESTROYED flow no longer offers its
        # artifact to anyone (and responses must never advertise dead links).
        updated = await store.update(
            task_id,
            status=TaskStatus.DESTROYED,
            stage=None,
            result=None,
            destroyed_at=_utcnow(),
        )
    else:
        updated = await store.update(
            task_id,
            status=TaskStatus.FAILURE,
            error="cancelled by user",
            destroyed_at=_utcnow(),
        )
    return public_record(updated)
