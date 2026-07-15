"""Test MDDash VRE"""

import pytest
from unittest.mock import MagicMock, patch
from requests.exceptions import RequestException
from vre_rocrate import MDDASH_PROGRAMMING_LANGUAGE
from app.constants import MDDASH_DEFAULT_SERVICE
from app.vres.mddash import VREMDDash, MDDashContext
from app.exceptions import (
    VREConfigurationError,
    VREAuthenticationError,
    ExternalServiceError,
)
from vre_rocrate import (
    RequestPackage,
    WorkflowDescriptor,
    FileReference,
)


def _build_package(pdb_name="1L2Y"):
    """Build a minimal RequestPackage for MDDash tests."""
    return RequestPackage(
        vre_type=MDDASH_PROGRAMMING_LANGUAGE,
        programming_language=MDDASH_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(
            id="#workflow",
            type="ComputationalWorkflow",
            url="https://github.com/sb-ncbr/mddash-notebooks.git",
        ),
        files=[
            FileReference(
                id="https://www.ebi.ac.uk/pdbe/entry-files/download/pdb1l2y.ent",
                name=pdb_name,
                encoding_format="chemical/x-pdb",
                url="https://www.ebi.ac.uk/pdbe/entry-files/download/pdb1l2y.ent",
            ),
        ],
    )


def _make_vre(package=None):
    """Create a VREMDDash instance with sensible defaults."""
    return VREMDDash(
        token="dummy_token",
        request_id=42,
        update_state=MagicMock(),
        request_package=package or _build_package(),
    )


def _make_ctx(session=None, user="testuser", xsrf_token="mock-xsrf", singleuser=""):
    """Create an MDDashContext with sensible test defaults."""
    return MDDashContext(
        session=session or MagicMock(),
        user=user,
        xsrf_token=xsrf_token,
        singleuser=singleuser,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def successful_session():
    """Mock requests.Session that satisfies the full post() call chain."""
    session = MagicMock()

    login = MagicMock(text="logged in")
    home = MagicMock(text="home")
    user = MagicMock()
    user.json.return_value = {"name": "testuser"}

    start = MagicMock(status_code=201, text="server started")

    ready = MagicMock(status_code=200)
    ready.json.return_value = {
        "servers": {"": {"ready": True, "stopped": False, "url": "/user/testuser/"}}
    }

    auth = MagicMock(status_code=200)
    create = MagicMock(status_code=200)

    session.get.side_effect = [login, home, user, ready, auth]
    session.post.side_effect = [start, create]
    session.cookies.get.return_value = "mock-xsrf-token"
    session.cookies.__contains__.return_value = True
    return session


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_get_default_service():
    """get_default_service returns MDDASH_DEFAULT_SERVICE."""
    vre = VREMDDash(
        token="dummy_token",
        request_id=0,
        update_state=None,
        request_package=None,
    )
    assert vre.get_default_service() == MDDASH_DEFAULT_SERVICE


@patch("app.vres.mddash.requests.Session")
def test_post_success(mock_session_cls, successful_session):
    """post returns the correct MDDash URL on success."""
    mock_session_cls.return_value = successful_session

    result = _make_vre().post()
    assert result == f"{MDDASH_DEFAULT_SERVICE}/user/testuser/dash/auth/create-login-token"


# ---------------------------------------------------------------------------
# _create_experiment errors
# ---------------------------------------------------------------------------


@patch("app.vres.mddash.VREMDDash._auth_mddash")
@patch("app.vres.mddash.VREMDDash._wait_for_server")
@patch("app.vres.mddash.VREMDDash._start_server")
@patch("app.vres.mddash.VREMDDash._login")
def test_post_missing_pdb_file(*_):
    """post raises VREConfigurationError when no PDB file is present."""
    package = RequestPackage(
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
        vre.post()
    assert "No PDB file" in str(exc.value)


def test_create_experiment_request_failure():
    """_create_experiment raises ExternalServiceError when POST fails."""
    vre = _make_vre()
    session = MagicMock()
    session.post.side_effect = RequestException("connection refused")
    ctx = _make_ctx(session=session, singleuser="/user/testuser/")

    with pytest.raises(ExternalServiceError) as exc:
        vre._create_experiment(ctx)
    assert "Failed to create MDDash experiment" in str(exc.value)


# ---------------------------------------------------------------------------
# _login errors
# ---------------------------------------------------------------------------


@patch("app.vres.mddash.requests.Session")
def test_login_request_failure(mock_session):
    """_login raises ExternalServiceError when a GET request fails."""
    mock_session.return_value.get.side_effect = RequestException("connection refused")

    vre = _make_vre()
    vre.svc_url = MDDASH_DEFAULT_SERVICE

    with pytest.raises(ExternalServiceError) as exc:
        vre._login()
    assert "MDDash login failed" in str(exc.value)


# ---------------------------------------------------------------------------
# _start_server errors
# ---------------------------------------------------------------------------


def test_start_server_request_failure():
    """_start_server raises ExternalServiceError when POST fails."""
    vre = _make_vre()
    session = MagicMock()
    session.post.side_effect = RequestException("connection refused")
    ctx = _make_ctx(session=session)

    with pytest.raises(ExternalServiceError) as exc:
        vre._start_server(ctx)
    assert "Failed to start MDDash server" in str(exc.value)


# ---------------------------------------------------------------------------
# _wait_for_server errors
# ---------------------------------------------------------------------------


def test_wait_for_server_request_failure():
    """_wait_for_server raises ExternalServiceError when poll GET fails."""
    vre = _make_vre()
    session = MagicMock()
    session.get.side_effect = RequestException("connection refused")
    ctx = _make_ctx(session=session)

    with pytest.raises(ExternalServiceError) as exc:
        vre._wait_for_server(ctx)
    assert "MDDash server poll failed" in str(exc.value)


@patch("time.sleep")
def test_wait_for_server_timeout(*_):
    """_wait_for_server raises ExternalServiceError when server never becomes ready."""
    vre = _make_vre()

    not_ready_resp = MagicMock(status_code=200)
    not_ready_resp.json.return_value = {"servers": {}}

    session = MagicMock()
    session.get.return_value = not_ready_resp
    ctx = _make_ctx(session=session)

    with pytest.raises(ExternalServiceError) as exc:
        vre._wait_for_server(ctx)
    assert "did not start within" in str(exc.value)


# ---------------------------------------------------------------------------
# _auth_mddash errors
# ---------------------------------------------------------------------------


def test_auth_mddash_request_failure():
    """_auth_mddash raises ExternalServiceError when GET fails."""
    vre = _make_vre()
    session = MagicMock()
    session.get.side_effect = RequestException("connection refused")
    ctx = _make_ctx(session=session, singleuser="/user/testuser/")

    with pytest.raises(ExternalServiceError) as exc:
        vre._auth_mddash(ctx)
    assert "MDDash auth failed" in str(exc.value)


def test_post_missing_mddash_auth_cookie():
    """_auth_mddash raises VREAuthenticationError when mddash-auth cookie is not set."""
    vre = _make_vre()
    session = MagicMock()
    session.cookies.__contains__.return_value = False
    ctx = _make_ctx(session=session, singleuser="/user/testuser/")

    with pytest.raises(VREAuthenticationError) as exc:
        vre._auth_mddash(ctx)
    assert "mddash-auth cookie not set" in str(exc.value)
