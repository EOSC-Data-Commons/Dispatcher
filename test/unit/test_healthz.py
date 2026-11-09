"""Healthz endpoint: the dispatcher's own liveness probe."""

import httpx
import pytest
from fastapi import FastAPI

from app.routers.healthz import router as healthz_router


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
