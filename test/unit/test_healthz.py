"""Healthz/readyz endpoints: the dispatcher's own liveness and readiness
probes."""

import httpx
import pytest
from fastapi import FastAPI

from app.routers.healthz import router as healthz_router
from app.status_store import InMemoryStatusStore


@pytest.mark.asyncio
async def test_healthz_returns_ok_without_auth():
    """The liveness probe answers 200 without authentication — container
    probes carry no OIDC token."""
    app = FastAPI()
    app.include_router(healthz_router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readyz_ok_when_store_answers():
    """Readiness actually exercises the status store: an unusable store
    fails every dispatch at record creation, and readiness should say so
    before traffic discovers it the hard way (v4 D6)."""
    app = FastAPI()
    app.include_router(healthz_router)
    app.state.status_store = InMemoryStatusStore()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_readyz_503_when_store_not_wired():
    app = FastAPI()
    app.include_router(healthz_router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/readyz")

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_readyz_503_when_store_unusable():
    class _Broken:
        async def list_active(self):
            raise RuntimeError("disk error")

    app = FastAPI()
    app.include_router(healthz_router)
    app.state.status_store = _Broken()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/readyz")

    assert response.status_code == 503
