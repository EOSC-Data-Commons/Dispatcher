"""Liveness endpoint for the dispatcher itself.

Docker and orchestrators cannot distinguish a wedged process from a
serving one: process-up only means the interpreter is alive. ``GET
/healthz`` gives them something to ask — a 200 proves the event loop can
still serve requests, which is exactly what a container healthcheck needs.

This is deliberately *not* the VRE-provider healthcheck
(:mod:`app.vres.utils.health` probes external services before dispatch);
this route says nothing about VREs, the broker, or anything else the
dispatcher talks to.

The route carries no authentication so container-local probes (which
have no OIDC token) can reach it.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict:
    """Liveness probe: a trivial 200 proves the event loop can serve."""
    return {"status": "ok"}
