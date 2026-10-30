"""Test MDDash VRE (async, httpx cookie flow via httpx_mock)."""

import asyncio

import httpx
import pytest
from unittest.mock import patch

from vre_rocrate import MDDASH_PROGRAMMING_LANGUAGE
from app.config import settings
from app.constants import MDDASH_DEFAULT_SERVICE
from app.vres.mddash import VREMDDash, MDDashContext
from app.exceptions import (
    VREConfigurationError,
    VREAuthenticationError,
    ExternalServiceError,
)
from vre_rocrate import (
    VREPayload,
    WorkflowDescriptor,
    FormalParameter,
)

SVC = MDDASH_DEFAULT_SERVICE
USER = "testuser"
SINGLEUSER = f"/user/{USER}/"


def _build_package(pdb_id="1L2Y"):
    """Build a minimal VREPayload for MDDash tests (scalar pdb_id input)."""
    return VREPayload(
        vre_type=MDDASH_PROGRAMMING_LANGUAGE,
        programming_language=MDDASH_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(
            id="#workflow",
            type="ComputationalWorkflow",
            url="https://github.com/sb-ncbr/mddash-notebooks.git",
        ),
        workflow_inputs=[
            FormalParameter(
                id="#input-pdb_id",
                name="pdb_id",
                default_value=pdb_id,
            ),
        ],
    )


def _make_vre(package=None):
    """Create a VREMDDash instance with sensible defaults."""
    return VREMDDash(
        token="dummy_token",
        request_id=42,
        status_store=None,
        payload=package or _build_package(),
    )


def _make_ctx(session=None, user=USER, xsrf_token="mock-xsrf", singleuser=SINGLEUSER):
    """Create an MDDashContext with sensible test defaults."""
    return MDDashContext(
        session=session or httpx.AsyncClient(),
        user=user,
        xsrf_token=xsrf_token,
        singleuser=singleuser,
    )


@pytest.fixture(autouse=True)
def _no_poll_sleep(monkeypatch):
    """Bounded poll loops must not sleep in tests."""
    monkeypatch.setattr(settings, "mddash_poll_interval", 1)
    monkeypatch.setattr(settings, "mddash_wait_max_time", 3)


def _register_login(httpx_mock):
    """Register the responses MDDash's login flow expects, in order."""
    httpx_mock.add_response(method="GET", url=f"{SVC}/hub/jwt_login", text="logged in")
    httpx_mock.add_response(
        method="GET",
        url=f"{SVC}/hub/home",
        text="home",
        headers={"set-cookie": "_xsrf=mock-xsrf"},
    )
    httpx_mock.add_response(
        method="GET", url=f"{SVC}/hub/api/user", json={"name": USER}
    )


def _register_full_flow(httpx_mock):
    """Register the complete happy-path post() call chain."""
    _register_login(httpx_mock)
    httpx_mock.add_response(
        method="POST", url=f"{SVC}/hub/api/users/{USER}/servers/", status_code=201
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{SVC}/hub/api/user",
        json={"servers": {"": {"ready": True, "stopped": False, "url": SINGLEUSER}}},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{SVC}{SINGLEUSER}dash/",
        status_code=200,
        headers={"set-cookie": "mddash-auth=yes"},
    )
    httpx_mock.add_response(
        method="POST", url=f"{SVC}{SINGLEUSER}dash/api/experiments", status_code=200
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{SVC}{SINGLEUSER}dash/auth/create-login-token",
        json={"token": "token", "expires_in": 5},
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_get_default_service():
    """get_default_service returns MDDASH_DEFAULT_SERVICE."""
    vre = VREMDDash(
        token="dummy_token",
        request_id=0,
        status_store=None,
        payload=None,
    )
    assert vre.get_default_service() == MDDASH_DEFAULT_SERVICE


async def test_post_success(httpx_mock):
    """post returns the correct MDDash URL on success."""
    _register_full_flow(httpx_mock)

    result = await _make_vre().post()
    assert (
        result
        == f"{MDDASH_DEFAULT_SERVICE}/user/testuser/dash/auth/login-token?token=token"
    )


async def test_post_registers_xsrf_and_experiment_payload(httpx_mock):
    """The flow sends the xsrf cookie-derived token and the experiment form."""
    _register_full_flow(httpx_mock)

    await _make_vre().post()

    requests = httpx_mock.get_requests()
    start = next(
        r for r in requests if r.method == "POST" and r.url.path.endswith("/servers/")
    )
    assert start.headers["X-XSRFToken"] == "mock-xsrf"
    experiment = next(
        r for r in requests if r.url.path.endswith("dash/api/experiments")
    )
    body = experiment.read().decode()
    assert "experiment-name=42%3A+1L2Y" in body
    assert "pdb-id=1L2Y" in body


# ---------------------------------------------------------------------------
# _create_experiment errors
# ---------------------------------------------------------------------------


async def test_post_missing_pdb_id(httpx_mock):
    """post raises VREConfigurationError when the pdb_id input parameter is absent."""
    # Flow fails in _create_experiment before its HTTP call: register only
    # the responses up to the mddash auth step.
    _register_login(httpx_mock)
    httpx_mock.add_response(
        method="POST", url=f"{SVC}/hub/api/users/{USER}/servers/", status_code=201
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{SVC}/hub/api/user",
        json={"servers": {"": {"ready": True, "stopped": False, "url": SINGLEUSER}}},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{SVC}{SINGLEUSER}dash/",
        status_code=200,
        headers={"set-cookie": "mddash-auth=yes"},
    )
    package = VREPayload(
        vre_type=MDDASH_PROGRAMMING_LANGUAGE,
        programming_language=MDDASH_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(
            id="#workflow",
            type="ComputationalWorkflow",
            url="https://github.com/sb-ncbr/mddash-notebooks.git",
        ),
    )
    vre = _make_vre(package=package)
    with pytest.raises(VREConfigurationError) as exc:
        await vre.post()
    assert "pdb_id" in str(exc.value)


async def test_create_experiment_request_failure(httpx_mock):
    """_create_experiment raises ExternalServiceError when POST fails."""
    for _ in range(4):  # 5xx responses are retried per-call
        httpx_mock.add_response(
            method="POST",
            url=f"{SVC}{SINGLEUSER}dash/api/experiments",
            status_code=500,
        )
    vre = _make_vre()

    with pytest.raises(ExternalServiceError) as exc:
        await vre._create_experiment(SVC, _make_ctx())
    assert "Failed to create MDDash experiment" in str(exc.value)


# ---------------------------------------------------------------------------
# _login errors
# ---------------------------------------------------------------------------


async def test_login_request_failure(httpx_mock):
    """_login raises ExternalServiceError when a GET request fails."""
    httpx_mock.add_response(method="GET", url=f"{SVC}/hub/jwt_login", status_code=401)

    vre = _make_vre()

    with pytest.raises(ExternalServiceError) as exc:
        await vre._login(SVC)
    assert "MDDash login failed" in str(exc.value)


# ---------------------------------------------------------------------------
# _start_server errors
# ---------------------------------------------------------------------------


async def test_start_server_request_failure(httpx_mock):
    """_start_server raises ExternalServiceError when POST fails."""
    for _ in range(4):
        httpx_mock.add_response(
            method="POST",
            url=f"{SVC}/hub/api/users/{USER}/servers/",
            status_code=500,
        )
    vre = _make_vre()

    with pytest.raises(ExternalServiceError) as exc:
        await vre._start_server(SVC, _make_ctx())
    assert "Failed to start MDDash server" in str(exc.value)


async def test_start_server_tolerates_already_running(httpx_mock):
    """A 400 from JupyterHub means 'server already exists' — tolerated."""
    httpx_mock.add_response(
        method="POST",
        url=f"{SVC}/hub/api/users/{USER}/servers/",
        status_code=400,
        text="already running",
    )
    vre = _make_vre()

    await vre._start_server(SVC, _make_ctx())


# ---------------------------------------------------------------------------
# _wait_for_server errors
# ---------------------------------------------------------------------------


async def test_wait_for_server_request_failure(httpx_mock):
    """_wait_for_server raises ExternalServiceError when poll GET fails."""
    httpx_mock.add_response(method="GET", url=f"{SVC}/hub/api/user", status_code=401)
    vre = _make_vre()

    with pytest.raises(ExternalServiceError) as exc:
        await vre._wait_for_server(SVC, _make_ctx())
    assert "MDDash server poll failed" in str(exc.value)


async def _instant_sleep(_seconds):
    """Test double for asyncio.sleep: poll instantly."""


async def test_wait_for_server_timeout(httpx_mock, monkeypatch):
    """_wait_for_server raises ExternalServiceError when server never becomes ready."""
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    for _ in range(3):
        httpx_mock.add_response(
            method="GET", url=f"{SVC}/hub/api/user", json={"servers": {}}
        )
    vre = _make_vre()

    with pytest.raises(ExternalServiceError) as exc:
        await vre._wait_for_server(SVC, _make_ctx())
    assert "did not start within" in str(exc.value)


async def test_wait_for_server_eventually_ready(httpx_mock, monkeypatch):
    """Polls continue until the default server reports ready."""
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    httpx_mock.add_response(
        method="GET",
        url=f"{SVC}/hub/api/user",
        json={"servers": {"": {"ready": False, "stopped": True}}},
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{SVC}/hub/api/user",
        json={"servers": {"": {"ready": True, "stopped": False, "url": SINGLEUSER}}},
    )
    vre = _make_vre()

    ctx = await vre._wait_for_server(SVC, _make_ctx())

    assert ctx.singleuser == SINGLEUSER
    assert len(httpx_mock.get_requests()) == 2


# ---------------------------------------------------------------------------
# _auth_mddash errors
# ---------------------------------------------------------------------------


async def test_auth_mddash_request_failure(httpx_mock):
    """_auth_mddash raises ExternalServiceError when GET fails."""
    httpx_mock.add_response(
        method="GET", url=f"{SVC}/user/testuser/dash/", status_code=401
    )
    vre = _make_vre()

    with pytest.raises(ExternalServiceError) as exc:
        await vre._auth_mddash(SVC, _make_ctx())
    assert "MDDash auth failed" in str(exc.value)


async def test_post_missing_mddash_auth_cookie(httpx_mock):
    """_auth_mddash raises VREAuthenticationError when mddash-auth cookie is not set."""
    httpx_mock.add_response(
        method="GET", url=f"{SVC}/user/testuser/dash/", status_code=200
    )
    vre = _make_vre()

    with pytest.raises(VREAuthenticationError) as exc:
        await vre._auth_mddash(SVC, _make_ctx())
    assert "mddash-auth cookie not set" in str(exc.value)
