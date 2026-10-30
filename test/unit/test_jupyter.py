"""Test Jupyter VRE (async, bounded poll loop, httpx)."""

import asyncio

import pytest

from app.config import settings
from app.constants import JUPYTER_DEFAULT_SERVICE
from app.vres.jupyter import VREJupyter
from app.exceptions import (
    ExternalServiceError,
    VREAuthenticationError,
    VREConfigurationError,
)
from vre_rocrate import (
    JUPYTER_PROGRAMMING_LANGUAGE,
    VREPayload,
    WorkflowDescriptor,
    FileReference,
)

SVC = JUPYTER_DEFAULT_SERVICE
USER = "jane"
NOTEBOOK = {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 4}


def _make_vre(payload=None):
    if payload is None:
        payload = VREPayload(
            vre_type=JUPYTER_PROGRAMMING_LANGUAGE,
            programming_language=JUPYTER_PROGRAMMING_LANGUAGE,
            workflow=WorkflowDescriptor(
                id="#workflow",
                type="ComputationalWorkflow",
            ),
            files=[
                FileReference(
                    id="analysis.ipynb",
                    name="analysis.ipynb",
                    properties={"content": __import__("json").dumps(NOTEBOOK).encode()},
                )
            ],
            raw_crate={},
        )
    return VREJupyter(
        token="dummy_token",
        request_id=7,
        status_store=None,
        payload=payload,
    )


def _register_full_flow(httpx_mock):
    httpx_mock.add_response(
        method="GET", url=f"{SVC}/services/jwt/user", json={"name": USER}
    )
    httpx_mock.add_response(
        method="POST", url=f"{SVC}/services/jwt/users/{USER}/servers/", status_code=201
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{SVC}/services/jwt/users/{USER}/tokens",
        json={"token": "api-token-1"},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{SVC}/services/jwt/user",
        json={"name": USER, "server": "/user/jane/", "servers": {"": {"ready": True}}},
    )
    httpx_mock.add_response(
        method="PUT",
        url=f"{SVC}/user/{USER}/api/contents/analysis.ipynb",
        json={"path": "analysis.ipynb"},
    )


async def test_post_happy_path(httpx_mock):
    _register_full_flow(httpx_mock)

    result = await _make_vre().post()

    assert result == f"{SVC}/user/{USER}"
    put = httpx_mock.get_requests()[-1]
    assert put.method == "PUT"
    assert put.headers["Authorization"] == "token api-token-1"


async def test_username_missing_raises_auth_error(httpx_mock):
    httpx_mock.add_response(method="GET", url=f"{SVC}/services/jwt/user", json={})

    with pytest.raises(VREAuthenticationError):
        await _make_vre().post()


async def test_start_server_failure_raises(httpx_mock):
    httpx_mock.add_response(
        method="GET", url=f"{SVC}/services/jwt/user", json={"name": USER}
    )
    httpx_mock.add_response(
        method="POST", url=f"{SVC}/services/jwt/users/{USER}/servers/", status_code=401
    )

    with pytest.raises(ExternalServiceError) as exc:
        await _make_vre().post()
    assert "Jupyter server start failed" in str(exc.value)


async def test_missing_notebook_raises_configuration_error(httpx_mock):
    httpx_mock.add_response(
        method="GET", url=f"{SVC}/services/jwt/user", json={"name": USER}
    )
    httpx_mock.add_response(
        method="POST", url=f"{SVC}/services/jwt/users/{USER}/servers/", status_code=201
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{SVC}/services/jwt/users/{USER}/tokens",
        json={"token": "api-token-1"},
    )
    payload = VREPayload(
        vre_type=JUPYTER_PROGRAMMING_LANGUAGE,
        programming_language=JUPYTER_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(id="#workflow", type="ComputationalWorkflow"),
        files=[],
        raw_crate={},
    )

    with pytest.raises(VREConfigurationError):
        await _make_vre(payload=payload).post()


async def test_wait_for_server_bounded_timeout(httpx_mock, monkeypatch):
    """The readiness wait is bounded (was an unbounded loop) and fails clean."""
    monkeypatch.setattr(settings, "jupyter_poll_interval", 1)
    monkeypatch.setattr(settings, "jupyter_wait_max_time", 2)

    async def _instant_sleep(_seconds):
        pass

    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    for _ in range(2):
        httpx_mock.add_response(
            method="GET",
            url=f"{SVC}/services/jwt/user",
            json={"name": USER, "server": None, "servers": {}},
        )

    vre = _make_vre()
    with pytest.raises(ExternalServiceError) as exc:
        await vre._wait_for_server_creation()
    assert "did not become ready" in str(exc.value)


async def test_wait_for_server_missing_default_entry(httpx_mock, monkeypatch):
    """A userinfo without the "" server entry must not raise KeyError/AttributeError."""
    monkeypatch.setattr(settings, "jupyter_poll_interval", 1)
    monkeypatch.setattr(settings, "jupyter_wait_max_time", 3)

    async def _instant_sleep(_seconds):
        pass

    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    httpx_mock.add_response(
        method="GET",
        url=f"{SVC}/services/jwt/user",
        json={"name": USER, "server": "/user/jane/", "servers": None},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{SVC}/services/jwt/user",
        json={"name": USER, "server": "/user/jane/", "servers": {"": {"ready": True}}},
    )

    await _make_vre()._wait_for_server_creation()


async def test_upload_notebook_error_mapped_to_service_error(httpx_mock):
    """Regression: upload errors map to ExternalServiceError (previously the
    non-existent exceptions.ServiceError blew up with AttributeError)."""
    for _ in range(4):  # 5xx responses are retried per-call
        httpx_mock.add_response(
            method="PUT",
            url=f"{SVC}/user/{USER}/api/contents/analysis.ipynb",
            status_code=500,
        )

    with pytest.raises(ExternalServiceError) as exc:
        await _make_vre().upload_notebook(NOTEBOOK, "analysis.ipynb", USER, "t")
    assert "Upload failed" in str(exc.value)
