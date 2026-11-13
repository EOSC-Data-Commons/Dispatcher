"""Lifespan wiring smoke test: the per-user credential store comes up with
the app (so logins can capture refresh tokens from the first one) and is
closed on shutdown."""

import ssl

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.credentials import SQLiteCredentialStore


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "credentials.db"))
    # app.main loads the TLS cert chain at import time; this test exercises
    # store wiring, not TLS.
    monkeypatch.setattr(
        ssl.SSLContext, "load_cert_chain", lambda self, *args, **kwargs: None
    )
    from app.main import app

    yield app


def test_lifespan_wires_and_closes_credential_store(app):
    with TestClient(app):
        store = app.state.credentials
        assert isinstance(store, SQLiteCredentialStore)
        assert store._conn is not None

    # Closed on shutdown.
    assert app.state.credentials._conn is None
