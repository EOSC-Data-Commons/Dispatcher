# test/unit/test_healthcheck.py
"""Test the fail-fast healthcheck of external VRE providers.

The healthcheck is globally disabled via an autouse fixture in conftest.py;
tests in this module re-enable it explicitly.
"""

import httpx
import pytest

from app.config import settings
from app.constants import GALAXY_DEFAULT_SERVICE
from app.exceptions import VREUnavailableError
from app.vres.galaxy import VREGalaxy
from app.vres.vip import VREVIP
from app.vres.scipion import VREScipion
from app.vres.base_vre import vre_factory
from app.vres.utils.health import check_service_alive
from app.status_store import InMemoryStatusStore
from app.vre_runner import resolve_service
from fakes import FakeAsyncIM
from vre_rocrate import (
    VREPayload,
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


def _payload(lang_id: str, runtime_platform=None) -> VREPayload:
    return VREPayload(
        vre_type=lang_id,
        programming_language=lang_id,
        workflow=WorkflowDescriptor(
            id="#wf", type="SoftwareSourceCode", runtime_platform=runtime_platform
        ),
        raw_crate={},
    )


async def _resolved_vre(payload, im_factory=None):
    svc_url, deployed_via_im = await resolve_service(
        token="t", payload=payload, im_factory=im_factory
    )
    vre = vre_factory(
        token="t",
        request_id=0,
        status_store=InMemoryStatusStore(),
        programming_language=payload.programming_language,
        svc_url=svc_url,
        payload=payload,
    )
    if not deployed_via_im:
        await vre.check_health()
    return vre


def test_vre_requires_resolved_service_url_at_construction():
    """An initialized VRE always has its service URL; there is no setup phase."""
    with pytest.raises(TypeError, match="svc_url"):
        VREScipion(
            token="t",
            request_id=0,
            status_store=InMemoryStatusStore(),
            payload=_payload(SCIPION_PROGRAMMING_LANGUAGE),
        )


@pytest.mark.parametrize("status_code", [200, 401, 403, 404, 408, 429])
async def test_up_when_probe_succeeds(httpx_mock, enable_healthcheck, status_code):
    """Any HTTP response below 500 means the provider is reachable."""
    httpx_mock.add_response(url="https://example.org", status_code=status_code)
    await check_service_alive("https://example.org")  # must not raise


async def test_raises_on_5xx_response(httpx_mock, enable_healthcheck):
    httpx_mock.add_response(url="https://example.org", status_code=503)
    with pytest.raises(VREUnavailableError) as exc:
        await check_service_alive("https://example.org")
    assert "503" in str(exc.value)
    assert "https://example.org" in str(exc.value)


async def test_raises_on_request_error(httpx_mock, enable_healthcheck):
    """DNS/connection/TLS/timeout errors mean the provider is down."""
    err = httpx.ConnectError("connection refused")
    httpx_mock.add_exception(err, url="https://example.org")
    with pytest.raises(VREUnavailableError) as exc:
        await check_service_alive("https://example.org")
    assert "https://example.org" in str(exc.value)
    assert exc.value.__cause__ is err


async def test_raises_on_malformed_url(enable_healthcheck):
    with pytest.raises(VREUnavailableError):
        await check_service_alive("http://[")


async def test_disabled_is_noop(httpx_mock):
    """Globally disabled healthcheck (conftest fixture) must not probe at all."""
    await check_service_alive("https://example.org")
    assert len(httpx_mock.get_requests()) == 0


async def test_galaxy_probes_version_endpoint(httpx_mock, enable_healthcheck):
    httpx_mock.add_response(url="https://usegalaxy.eu/api/version", status_code=200)
    vre = await _resolved_vre(_payload(GALAXY_PROGRAMMING_LANGUAGE))
    assert isinstance(vre, VREGalaxy)
    assert len(httpx_mock.get_requests()) == 1


async def test_vip_probes_public_pipelines(httpx_mock, enable_healthcheck):
    httpx_mock.add_response(
        url="https://vip.creatis.insa-lyon.fr/rest/pipelines?public", status_code=200
    )
    vre = await _resolved_vre(_payload(VIP_PROGRAMMING_LANGUAGE))
    assert isinstance(vre, VREVIP)
    assert len(httpx_mock.get_requests()) == 1


async def test_default_hook_probes_service_root(httpx_mock, enable_healthcheck):
    """VREs without a provider-specific endpoint probe the service root."""
    httpx_mock.add_response(url="https://scipion.i2pc.es", status_code=200)
    await _resolved_vre(_payload(SCIPION_PROGRAMMING_LANGUAGE))
    assert len(httpx_mock.get_requests()) == 1


async def test_setup_fails_fast_when_provider_down(httpx_mock, enable_healthcheck):
    httpx_mock.add_exception(
        httpx.ConnectError("connection refused"),
        url="https://usegalaxy.eu/api/version",
    )
    with pytest.raises(VREUnavailableError):
        await _resolved_vre(_payload(GALAXY_PROGRAMMING_LANGUAGE))


async def test_crate_specified_service_url_is_probed(httpx_mock, enable_healthcheck):
    httpx_mock.add_response(
        url="https://galaxy.example.org/api/version", status_code=200
    )
    vre = await _resolved_vre(
        _payload(
            GALAXY_PROGRAMMING_LANGUAGE,
            runtime_platform="https://galaxy.example.org/",
        ),
    )
    # trailing slash stripped on resolution, Galaxy endpoint appended
    assert vre.svc_url == "https://galaxy.example.org"
    assert len(httpx_mock.get_requests()) == 1


async def test_im_deployed_service_skips_healthcheck(httpx_mock, enable_healthcheck):
    """IM-deployed services do not exist at resolution time — no probe."""
    payload = VREPayload(
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
    vre = await _resolved_vre(
        payload,
        im_factory=lambda token: FakeAsyncIM(
            outputs={"url": "https://deployed.example.org"}
        ),
    )
    assert vre.svc_url == "https://deployed.example.org"
    assert len(httpx_mock.get_requests()) == 0


async def test_im_without_url_uses_registered_default_without_healthcheck(
    httpx_mock, enable_healthcheck
):
    payload = _payload(
        GALAXY_PROGRAMMING_LANGUAGE,
        RuntimePlatform(name="gxy", install_url="https://example.org/galaxy.yaml"),
    )

    vre = await _resolved_vre(payload, im_factory=lambda token: FakeAsyncIM(outputs={}))

    assert vre.svc_url == GALAXY_DEFAULT_SERVICE.rstrip("/")
    assert len(httpx_mock.get_requests()) == 0
