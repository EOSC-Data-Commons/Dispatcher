"""Unit tests for app.services.im_async — the dispatcher-side async IM wrapper.

The wire client (imclient.AsyncIMClient) is faked; TOSCA template fetching
goes through the shared httpx client and is intercepted by httpx_mock.
"""

import pytest

from app.config import settings
from app.exceptions import IMError
from app.services.im_async import AsyncIM, build_auth_config
from vre_rocrate import IMInputFile, RuntimePlatform

TOSCA_URL = "http://tosca.url/template.yaml"

TOSCA = """
topology_template:
  inputs:
    mem_size:
      default: 1
  node_templates:
    compute1:
      type: tosca.nodes.Compute
"""


class _FakeWireClient:
    """Exception-raising fake of imclient.AsyncIMClient."""

    def __init__(self, states=None, outputs=None, inf_id="inf-1"):
        self._inf_id = inf_id
        self._states = list(states) if states else []
        self._outputs = outputs if outputs is not None else {"url": "http://vre"}
        self.create_calls = []
        self.destroy_calls = []
        self.prop_calls = []
        self.closed = False

    async def create(self, desc, desc_type="radl", asyncr=False, dry_run=False):
        self.create_calls.append((desc, desc_type, asyncr))
        return self._inf_id

    async def get_infra_property(self, inf_id, prop):
        self.prop_calls.append((inf_id, prop))
        if prop == "state":
            state = self._states.pop(0) if self._states else {"state": "configured"}
            if isinstance(state, Exception):
                raise state
            return state
        if prop == "contmsg":
            return "deployment log"
        if prop == "outputs":
            return self._outputs
        raise AssertionError(f"unexpected prop {prop}")

    async def destroy(self, inf_id):
        self.destroy_calls.append(inf_id)

    async def aclose(self):
        self.closed = True


@pytest.fixture(autouse=True)
def im_settings(monkeypatch):
    monkeypatch.setattr(settings, "im_endpoint", "http://im.endpoint")
    monkeypatch.setattr(
        settings,
        "im_cloud_provider",
        {
            "type": "openstack",
            "host": "test.host",
            "username": "test_user",
            "auth_version": "3.x_oidc_access_token",
            "tenant": "test_tenant",
        },
    )
    monkeypatch.setattr(settings, "im_max_time", 600)
    monkeypatch.setattr(settings, "im_max_retries", 5)
    monkeypatch.setattr(settings, "im_sleep", 0)


def _make_im(client=None):
    return AsyncIM("test_token", client=client or _FakeWireClient())


def _rp(**kwargs):
    kwargs.setdefault("install_url", TOSCA_URL)
    return RuntimePlatform(name="Test", **kwargs)


class TestAuthConfig:
    def test_init_with_empty_token_raises_imerror(self):
        with pytest.raises(IMError, match="Access token not provided for IM."):
            AsyncIM("")

    def test_build_auth_config_openstack(self):
        auth = build_auth_config("test_token")
        assert len(auth) == 2
        assert auth[0]["type"] == "InfrastructureManager"
        assert auth[0]["token"] == "test_token"
        assert auth[1]["type"] == "OpenStack"
        assert auth[1]["host"] == "test.host"
        assert auth[1]["password"] == "test_token"

    def test_build_auth_config_openstack_static_password(self, monkeypatch):
        monkeypatch.setattr(
            settings,
            "im_cloud_provider",
            {
                "type": "openstack",
                "host": "test.host",
                "username": "test_user",
                "auth_version": "2.0",
                "tenant": "test_tenant",
                "password": "service-secret",
            },
        )

        auth = build_auth_config("test_token")

        assert auth[1]["password"] == "service-secret"

    def test_build_auth_config_egi(self, monkeypatch):
        monkeypatch.setattr(
            settings, "im_cloud_provider", {"type": "egi", "VO": "vo", "site": "site"}
        )

        auth = build_auth_config("test_token")

        assert len(auth) == 2
        assert auth[1]["type"] == "EGI"
        assert auth[1]["vo"] == "vo"
        assert auth[1]["host"] == "site"
        assert auth[1]["token"] == "test_token"

    def test_build_auth_config_missing_type_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "im_cloud_provider", {})

        with pytest.raises(IMError, match="Cloud provider type is not specified"):
            build_auth_config("test_token")

    def test_build_auth_config_unsupported_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "im_cloud_provider", {"type": "undefined"})

        with pytest.raises(IMError, match="Unsupported cloud provider type"):
            build_auth_config("test_token")


class TestCreate:
    async def test_create_returns_inf_id_and_assembles_tosca(self, httpx_mock):
        httpx_mock.add_response(method="GET", url=TOSCA_URL, text=TOSCA)
        client = _FakeWireClient()

        im = _make_im(client)
        inf_id = await im.create(_rp(memory="4GB"))

        assert inf_id == "inf-1"
        assert im.inf_id == "inf-1"
        desc, desc_type, asyncr = client.create_calls[0]
        assert desc_type == "yaml"
        assert asyncr is True  # never block the create call on allocation
        assert "mem_size" in desc
        assert "default: 4GB" in desc

    async def test_create_no_install_url_raises(self):
        im = _make_im()

        with pytest.raises(IMError, match="no installUrl"):
            await im.create(RuntimePlatform(name="Test"))

    async def test_create_tosca_fetch_failure_raises(self, httpx_mock):
        httpx_mock.add_response(method="GET", url=TOSCA_URL, status_code=404)
        im = _make_im()

        with pytest.raises(IMError, match="Failed to fetch TOSCA template"):
            await im.create(_rp())

    async def test_create_im_failure_raises_imerror(self, httpx_mock):
        import httpx

        httpx_mock.add_response(method="GET", url=TOSCA_URL, text=TOSCA)

        class _FailingCreate(_FakeWireClient):
            async def create(self, desc, desc_type="radl", asyncr=False, dry_run=False):
                request = httpx.Request("POST", "http://im/infrastructures")
                response = httpx.Response(400, request=request)
                raise httpx.HTTPStatusError("bad", request=request, response=response)

        im = _make_im(_FailingCreate())

        with pytest.raises(IMError, match="Failed to deploy service"):
            await im.create(_rp())


class TestWaitForReady:
    async def test_wait_success_first_poll(self):
        client = _FakeWireClient()
        im = _make_im(client)
        im.inf_id = "inf-1"
        heartbeats = []

        async def heartbeat(stage):
            heartbeats.append(stage)

        await im.wait_for_ready(heartbeat)

        assert client.prop_calls == [("inf-1", "state")]
        # Heartbeat fires on every poll iteration.
        assert heartbeats == ["IM state: configured"]

    async def test_wait_heartbeats_every_poll_iteration(self):
        client = _FakeWireClient(
            states=[{"state": "pending"}, {"state": "running"}, {"state": "configured"}]
        )
        im = _make_im(client)
        im.inf_id = "inf-1"
        heartbeats = []

        async def heartbeat(stage):
            heartbeats.append(stage)

        await im.wait_for_ready(heartbeat)

        assert heartbeats == [
            "IM state: pending",
            "IM state: running",
            "IM state: configured",
        ]
        assert client.destroy_calls == []

    async def test_wait_failure_logs_contmsg_destroys_and_raises(self):
        client = _FakeWireClient(states=[{"state": "failed"}])
        im = _make_im(client)
        im.inf_id = "inf-1"

        with pytest.raises(IMError, match="Current state: failed"):
            await im.wait_for_ready()

        assert ("inf-1", "state") in client.prop_calls
        assert ("inf-1", "contmsg") in client.prop_calls
        assert client.destroy_calls == ["inf-1"]
        assert im.inf_id is None

    async def test_wait_retries_unknown_states_until_max_retries(
        self, im_settings, monkeypatch
    ):
        monkeypatch.setattr(settings, "im_max_retries", 3)
        monkeypatch.setattr(settings, "im_max_time", 100)

        client = _FakeWireClient(states=[Exception("state retrieval error")] * 10)
        im = _make_im(client)
        im.inf_id = "inf-1"

        with pytest.raises(IMError, match="Current state: unknown"):
            await im.wait_for_ready()

        state_calls = [c for c in client.prop_calls if c == ("inf-1", "state")]
        assert len(state_calls) == 3
        assert client.destroy_calls == ["inf-1"]

    async def test_wait_succeeds_with_fewer_failures_than_max_retries(
        self, monkeypatch
    ):
        monkeypatch.setattr(settings, "im_max_retries", 3)
        monkeypatch.setattr(settings, "im_max_time", 100)

        client = _FakeWireClient(
            states=[
                Exception("temporary error"),
                Exception("temporary error"),
                {"state": "configured"},
            ]
        )
        im = _make_im(client)
        im.inf_id = "inf-1"

        await im.wait_for_ready()

        assert client.destroy_calls == []
        assert im.inf_id == "inf-1"

    async def test_wait_timeout_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "im_max_time", 10)
        monkeypatch.setattr(settings, "im_sleep", 5)

        async def _instant_sleep(_seconds):
            pass

        import asyncio

        monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

        client = _FakeWireClient(states=[{"state": "running"}] * 10)
        im = _make_im(client)
        im.inf_id = "inf-1"

        with pytest.raises(IMError, match="Timeout"):
            await im.wait_for_ready()

        assert client.destroy_calls == ["inf-1"]

    async def test_wait_without_deployment_raises(self):
        im = _make_im()
        im.inf_id = None

        with pytest.raises(IMError, match="No service deployed yet"):
            await im.wait_for_ready()


class TestDestroy:
    async def test_destroy_clears_inf_id(self):
        client = _FakeWireClient()
        im = _make_im(client)
        im.inf_id = "inf-1"

        await im.destroy()

        assert client.destroy_calls == ["inf-1"]
        assert im.inf_id is None

    async def test_destroy_without_service_is_noop(self):
        client = _FakeWireClient()
        im = _make_im()
        im.inf_id = None

        await im.destroy()

        assert client.destroy_calls == []


class TestRunComposite:
    async def test_run_full_sequence(self, httpx_mock):
        httpx_mock.add_response(method="GET", url=TOSCA_URL, text=TOSCA)
        client = _FakeWireClient(outputs={"url": "http://vre.example"})
        im = _make_im(client)
        heartbeats = []
        inf_created = []

        async def heartbeat(stage):
            heartbeats.append(stage)

        async def record_inf(inf_id):
            inf_created.append(inf_id)

        outputs = await im.run(_rp(), heartbeat=heartbeat, on_inf_created=record_inf)

        assert outputs == {"url": "http://vre.example"}
        assert inf_created == ["inf-1"]
        assert heartbeats[0] == "IM sequence started"
        assert "IM sequence finished" in heartbeats
        assert heartbeats[-1] == "IM sequence successful"
        assert ("inf-1", "outputs") in client.prop_calls

    async def test_run_error_cleans_up_and_raises(self, httpx_mock):
        httpx_mock.add_response(method="GET", url=TOSCA_URL, text=TOSCA)
        client = _FakeWireClient(states=[{"state": "failed"}])
        im = _make_im(client)

        with pytest.raises(IMError, match="Current state: failed"):
            await im.run(_rp())

        assert ("inf-1", "contmsg") in client.prop_calls
        assert client.destroy_calls == ["inf-1"]


class TestClose:
    async def test_aclose_closes_client(self):
        client = _FakeWireClient()
        im = _make_im(client)

        await im.aclose()

        assert client.closed is True
