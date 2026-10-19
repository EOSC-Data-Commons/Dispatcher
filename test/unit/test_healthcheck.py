# test/unit/test_healthcheck.py
"""Test the fail-fast healthcheck of external VRE providers.

The healthcheck is globally disabled via an autouse fixture in conftest.py;
tests in this module re-enable it explicitly.
"""

import pytest
import requests as real_requests
from unittest.mock import Mock

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


def test_up_when_probe_succeeds(requests_mock, enable_healthcheck):
    """Any HTTP response below 500 means the provider is up (incl. 401/403/404)."""
    requests_mock.get("https://example.org", status_code=200)
    check_service_alive("https://example.org")  # must not raise


def test_raises_on_5xx_response(requests_mock, enable_healthcheck):
    requests_mock.get("https://example.org", status_code=503)
    with pytest.raises(VREUnavailableError) as exc:
        check_service_alive("https://example.org")
    assert "503" in str(exc.value)
    assert "https://example.org" in str(exc.value)


def test_raises_on_request_error(requests_mock, enable_healthcheck):
    """DNS/connection/TLS/timeout errors mean the provider is down."""
    err = real_requests.ConnectionError("connection refused")
    requests_mock.get("https://example.org", exc=err)
    with pytest.raises(VREUnavailableError) as exc:
        check_service_alive("https://example.org")
    assert "https://example.org" in str(exc.value)
    assert exc.value.__cause__ is err


def test_disabled_is_noop(requests_mock):
    """Globally disabled healthcheck (conftest fixture) must not probe at all."""
    requests_mock.get("https://example.org", status_code=200)
    check_service_alive("https://example.org")
    assert requests_mock.call_count == 0


def test_galaxy_probes_version_endpoint(requests_mock, enable_healthcheck):
    requests_mock.get("https://usegalaxy.eu/api/version", status_code=200)
    VREGalaxy(
        token="t",
        request_id=0,
        update_state=None,
        request_package=_package(GALAXY_PROGRAMMING_LANGUAGE),
    )
    assert requests_mock.call_count == 1


def test_vip_probes_public_pipelines(requests_mock, enable_healthcheck):
    requests_mock.get(
        "https://vip.creatis.insa-lyon.fr/rest/pipelines?public", status_code=200
    )
    VREVIP(
        token="t",
        request_id=0,
        update_state=None,
        request_package=_package(VIP_PROGRAMMING_LANGUAGE),
    )
    assert requests_mock.call_count == 1


def test_default_hook_probes_service_root(requests_mock, enable_healthcheck):
    """VREs without a provider-specific endpoint probe the service root."""
    requests_mock.get("https://scipion.i2pc.es", status_code=200)
    VREScipion(
        token="t",
        request_id=0,
        update_state=None,
        request_package=_package(SCIPION_PROGRAMMING_LANGUAGE),
    )
    assert requests_mock.call_count == 1


def test_init_fails_fast_when_provider_down(requests_mock, enable_healthcheck):
    requests_mock.get(
        "https://usegalaxy.eu/api/version",
        exc=real_requests.ConnectionError("connection refused"),
    )
    with pytest.raises(VREUnavailableError):
        VREGalaxy(
            token="t",
            request_id=0,
            update_state=None,
            request_package=_package(GALAXY_PROGRAMMING_LANGUAGE),
        )


def test_crate_specified_service_url_is_probed(requests_mock, enable_healthcheck):
    requests_mock.get("https://galaxy.example.org/api/version", status_code=200)
    VREGalaxy(
        token="t",
        request_id=0,
        update_state=None,
        request_package=_package(
            GALAXY_PROGRAMMING_LANGUAGE,
            runtime_platform="https://galaxy.example.org/",
        ),
    )
    # trailing slash stripped by __init__, Galaxy endpoint appended
    assert requests_mock.call_count == 1


def test_im_deployed_service_skips_healthcheck(requests_mock, enable_healthcheck):
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
    VREGalaxy(
        token="t",
        request_id=0,
        update_state=None,
        request_package=package,
        im_factory=im_factory,
    )
    assert requests_mock.call_count == 0
