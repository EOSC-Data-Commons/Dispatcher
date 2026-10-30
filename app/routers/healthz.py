"""Health endpoints for the dispatcher itself.

Docker and orchestrators cannot distinguish a wedged process from a
serving one: process-up only means the interpreter is alive. ``GET
/healthz`` gives them something to ask — a 200 proves the event loop can
still serve requests, which is exactly what a container healthcheck needs.

``GET /readyz`` answers a different question: can the dispatcher do its
job? In this architecture an unusable status store fails every dispatch
at record creation, so readiness actually exercises the store (a trivial
query) instead of discovering the failure the hard way on traffic.

This is deliberately *not* the VRE-provider healthcheck
(:mod:`app.vres.utils.health` probes external services before dispatch);
these routes say nothing about VREs, IM, or anything else the
dispatcher talks to.

Both routes carry no authentication so container-local probes (which
have no OIDC token) can reach them.
"""

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict:
    """Liveness probe: a trivial 200 proves the event loop can serve."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> dict:
    """Readiness probe: the status store must answer a trivial query."""
    store = getattr(request.app.state, "status_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="status store not wired")
    try:
        await store.list_active()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"status store unusable: {exc}")
    return {"status": "ready"}
