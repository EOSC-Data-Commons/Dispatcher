"""Lifespan wiring smoke test: shared HTTP client, SQLite store, task
registry and recovery manager come up with the app (single uvicorn worker
model), and the old Celery dependencies are gone from the app graph."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.status_store import SQLiteStatusStore


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "lifespan.db"))
    monkeypatch.setattr(settings, "janitor_interval", 3600)
    from app.main import app

    yield app


def test_lifespan_wires_store_registry_and_http_client(app):
    from app import http as app_http

    with TestClient(app):
        assert isinstance(app.state.status_store, SQLiteStatusStore)
        assert app.state.tasks == {}
        assert app_http.get_http_client() is not None

    assert app_http._client is None  # closed on shutdown


def test_celery_is_not_part_of_the_app():
    """P5: the Celery tier is deleted from the code path entirely."""
    with pytest.raises(ModuleNotFoundError):
        import app.celery  # noqa: F401
