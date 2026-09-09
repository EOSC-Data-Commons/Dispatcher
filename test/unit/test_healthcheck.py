# test/unit/test_healthcheck.py
"""Test the fail-fast healthcheck of external VRE providers.

The healthcheck is globally disabled via an autouse fixture in conftest.py;
tests in this module re-enable it explicitly.
"""

import pytest
import requests as real_requests
from unittest.mock import Mock, patch

from app.config import settings
from app.exceptions import VREUnavailableError
from app.vres.galaxy import VREGalaxy
from app.vres.vip import VREVIP
from app.vres.scipion import VREScipion
from app.vres.utils.health import check_service_alive
from vre_rocrate import (
    RequestPackage,
    WorkflowDescriptor,
    RuntimePlatform,
    GALAXY_PROGRAMMING_LANGUAGE,
    VIP_PROGRAMMING_LANGUAGE,
    SCIPION_PROGRAMMING_LANGUAGE,
)


@pytest.fixture
def enable_healthcheck():
    """Re-enable the healthcheck disabled globally in conftest. Restore afterwards."""
    settings.vre_healthcheck_enabled = True
    yield
    settings.vre_healthcheck_enabled = False


def _package(lang_id: str, runtime_platform=None) -> RequestPackage:
    return RequestPackage(
        vre_type=lang_id,
        programming_language=lang_id,
        workflow=WorkflowDescriptor(
            id="#wf", type="SoftwareSourceCode", runtime_platform=runtime_platform
        ),
        raw_crate={},
    )


@patch("app.vres.utils.health.requests.get")
def test_up_when_probe_succeeds(mock_get, enable_healthcheck):
    """Any HTTP response below 500 means the provider is up (incl. 401/403/404)."""
    mock_get.return_value = Mock(status_code=200)
    check_service_alive("https://example.org")  # must not raise


@patch("app.vres.utils.health.requests.get")
def test_raises_on_5xx_response(mock_get, enable_healthcheck):
    mock_get.return_value = Mock(status_code=503)
    with pytest.raises(VREUnavailableError) as exc:
        check_service_alive("https://example.org")
    assert "503" in str(exc.value)
    assert "https://example.org" in str(exc.value)


@patch("app.vres.utils.health.requests.get")
def test_raises_on_request_error(mock_get, enable_healthcheck):
    """DNS/connection/TLS/timeout errors mean the provider is down."""
    err = real_requests.ConnectionError("connection refused")
    mock_get.side_effect = err
    with pytest.raises(VREUnavailableError) as exc:
        check_service_alive("https://example.org")
    assert "https://example.org" in str(exc.value)
    assert exc.value.__cause__ is err


def test_disabled_is_noop():
    """Globally disabled healthcheck (conftest fixture) must not probe at all."""
    with patch("app.vres.utils.health.requests.get") as mock_get:
        check_service_alive("https://example.org")
    mock_get.assert_not_called()


@patch("app.vres.utils.health.requests.get")
def test_galaxy_probes_version_endpoint(mock_get, enable_healthcheck):
    mock_get.return_value = Mock(status_code=200)
    VREGalaxy(
        token="t",
        request_id=0,
        update_state=None,
        request_package=_package(GALAXY_PROGRAMMING_LANGUAGE),
    )
    mock_get.assert_called_once()
    assert mock_get.call_args[0][0] == "https://usegalaxy.eu/api/version"


@patch("app.vres.utils.health.requests.get")
def test_vip_probes_public_pipelines(mock_get, enable_healthcheck):
    mock_get.return_value = Mock(status_code=200)
    VREVIP(
        token="t",
        request_id=0,
        update_state=None,
        request_package=_package(VIP_PROGRAMMING_LANGUAGE),
    )
    mock_get.assert_called_once()
    assert (
        mock_get.call_args[0][0]
        == "https://vip.creatis.insa-lyon.fr/rest/pipelines?public"
    )


@patch("app.vres.utils.health.requests.get")
def test_default_hook_probes_service_root(mock_get, enable_healthcheck):
    """VREs without a provider-specific endpoint probe the service root."""
    mock_get.return_value = Mock(status_code=200)
    VREScipion(
        token="t",
        request_id=0,
        update_state=None,
        request_package=_package(SCIPION_PROGRAMMING_LANGUAGE),
    )
    mock_get.assert_called_once()
    assert mock_get.call_args[0][0] == "https://scipion.i2pc.es"


@patch("app.vres.utils.health.requests.get")
def test_init_fails_fast_when_provider_down(mock_get, enable_healthcheck):
    mock_get.side_effect = real_requests.ConnectionError("connection refused")
    with pytest.raises(VREUnavailableError):
        VREGalaxy(
            token="t",
            request_id=0,
            update_state=None,
            request_package=_package(GALAXY_PROGRAMMING_LANGUAGE),
        )


@patch("app.vres.utils.health.requests.get")
def test_crate_specified_service_url_is_probed(mock_get, enable_healthcheck):
    mock_get.return_value = Mock(status_code=200)
    vre = VREGalaxy(
        token="t",
        request_id=0,
        update_state=None,
        request_package=_package(
            GALAXY_PROGRAMMING_LANGUAGE,
            runtime_platform="https://galaxy.example.org/",
        ),
    )
    # trailing slash stripped by __init__, Galaxy endpoint appended
    mock_get.assert_called_once()
    assert mock_get.call_args[0][0] == "https://galaxy.example.org/api/version"
    assert vre.svc_url == "https://galaxy.example.org"


def test_im_deployed_service_skips_healthcheck():
    """IM-deployed services do not exist at resolution time — no probe."""
    package = RequestPackage(
        vre_type=GALAXY_PROGRAMMING_LANGUAGE,
        programming_language=GALAXY_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(
            id="#wf",
            type="SoftwareSourceCode",
            runtime_platform=RuntimePlatform(
                name="gxy", install_url="https://example.org/galaxy.yaml"
            ),
        ),
        raw_crate={},
    )
    im_factory = lambda token, update: Mock(  # noqa: E731
        run_service=Mock(return_value={"url": "https://deployed.example.org"})
    )
    with patch("app.vres.base_vre.check_service_alive") as mock_check:
        vre = VREGalaxy(
            token="t",
            request_id=0,
            update_state=None,
            request_package=package,
            im_factory=im_factory,
        )
    mock_check.assert_not_called()
    assert vre.svc_url == "https://deployed.example.org"
