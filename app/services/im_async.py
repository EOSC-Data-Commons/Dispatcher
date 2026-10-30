"""Dispatcher-side async IM wrapper.

Owns everything dispatcher-domain about IM interactions, per the
async-execution design note:

- infrastructure auth-config assembly (settings cloud provider + user token),
- TOSCA fetch + assembly (via :mod:`app.services.im_tosca`),
- the bounded wait loop **with heartbeat** — progress (``updated_at``) is
  written on every poll iteration so the janitor's liveness check keeps
  working during 30–60 min deployments,
- failure handling (fetch contmsg to logs, destroy, raise),
- the ``run(rp, heartbeat)`` / ``resume(inf_id, heartbeat)`` composites.

The wire client is ``imclient.AsyncIMClient`` from the IM repo (installed
editable); it raises ``httpx.HTTPStatusError``/``httpx.TransportError`` on
failure. ``create`` is never retried (a retried create = a VM); the wait loop
tolerates ``im_max_retries`` consecutive "unknown" states exactly like the
retired synchronous implementation.
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Mapping

import httpx
import yaml

import app.constants as constants
from app import http as app_http
from app.config import settings
from app.exceptions import IMError
from app.services.im_tosca import assemble_tosca_template
from vre_rocrate import RuntimePlatform

logger = logging.getLogger(__name__)

#: Progress heartbeat callback: writes the stage to the task record, which
#: refreshes ``updated_at`` (the janitor's liveness signal).
Heartbeat = Callable[[str], Awaitable[None]]

#: Called the instant ``create()`` returns, so ``im_inf_id`` is persisted
#: before the infrastructure can outlive its record.
OnInfCreated = Callable[[str], Awaitable[None]]


async def _noop_heartbeat(_stage: str) -> None:
    pass


def build_auth_config(access_token: str) -> list[dict]:
    """Build the IM auth-data list from settings + the caller's access token.

    Same format the retired synchronous ``IM._build_auth_config`` produced —
    fed verbatim to ``AsyncIMClient.init_client``.
    """
    auth = [{"type": "InfrastructureManager", "token": access_token}]
    if not settings.im_cloud_provider.get("type"):
        raise IMError("Cloud provider type is not specified in the configuration.")

    if settings.im_cloud_provider["type"].lower() == "openstack":
        for key in ["host", "username", "auth_version", "tenant"]:
            if key not in settings.im_cloud_provider:
                raise IMError(f"Missing {key} field in the OpenStack configuration")
        ost_auth = {
            "id": "eodcostcloud",
            "type": "OpenStack",
            "host": settings.im_cloud_provider["host"],
            "username": settings.im_cloud_provider["username"],
            "auth_version": settings.im_cloud_provider["auth_version"],
            "tenant": settings.im_cloud_provider["tenant"],
        }
        if settings.im_cloud_provider["auth_version"] == "3.x_oidc_access_token":
            ost_auth["password"] = access_token
        else:
            if "password" not in settings.im_cloud_provider:
                raise IMError("Missing password field in the OpenStack configuration")
            ost_auth["password"] = settings.im_cloud_provider["password"]
        if "domain" in settings.im_cloud_provider:
            ost_auth["domain"] = settings.im_cloud_provider["domain"]
        if "region" in settings.im_cloud_provider:
            ost_auth["service_region"] = settings.im_cloud_provider["region"]
        auth.append(ost_auth)
    elif settings.im_cloud_provider["type"].lower() == "egi":
        for key in ["VO", "site"]:
            if key not in settings.im_cloud_provider:
                raise IMError(f"Missing {key} field in the EGI configuration")
        auth.append(
            {
                "id": "eodcegicloud",
                "type": "EGI",
                "vo": settings.im_cloud_provider["VO"],
                "token": access_token,
                "host": settings.im_cloud_provider["site"],
            }
        )
    else:
        raise IMError(
            f"Unsupported cloud provider type: {settings.im_cloud_provider['type']}"
        )
    return auth


def make_im_client(access_token: str):
    """Instantiate the real ``AsyncIMClient``; clean IMError when the async
    client package is unavailable."""
    try:
        from imclient import AsyncIMClient
    except ImportError as exc:
        raise IMError("async IM client not installed") from exc
    return AsyncIMClient.init_client(
        settings.im_endpoint,
        build_auth_config(access_token),
        ssl_verify=settings.im_ssl_verify,
    )


class AsyncIM:
    """Async IM orchestrator implementing the dispatcher's ``AsyncIMProtocol``.

    The wrapped HTTP client is injectable for tests; any owned client
    resources are released via :meth:`aclose` (invoked by the VRE layer in a
    ``finally``).
    """

    def __init__(self, access_token: str | None, client: Any | None = None):
        if not access_token:
            raise IMError("Access token not provided for IM.")
        self._client = client if client is not None else make_im_client(access_token)
        self.inf_id: str | None = None

    async def aclose(self) -> None:
        """Release the underlying HTTP connection pool."""
        close = getattr(self._client, "aclose", None)
        if close is not None:
            await close()

    # -- TOSCA --------------------------------------------------------------

    async def _tosca_yaml(self, rp: RuntimePlatform) -> str:
        if rp.install_url is None:
            raise IMError("RuntimePlatform has no installUrl")
        try:
            resp = await app_http.get(rp.install_url)
        except httpx.HTTPError as exc:
            logger.exception("Error fetching TOSCA template from %s", rp.install_url)
            raise IMError(
                f"Failed to fetch TOSCA template from: {rp.install_url}"
            ) from exc
        tosca_template = yaml.safe_load(resp.text)
        tosca_template = assemble_tosca_template(tosca_template, rp)
        return yaml.safe_dump(tosca_template)

    # -- IM client wrappers --------------------------------------------------

    async def create(self, rp: RuntimePlatform) -> str:
        """Create the infrastructure; never retried (a retried create = a VM)."""
        desc = await self._tosca_yaml(rp)
        try:
            # asyncr=True: never block the HTTP call on allocation; the waiter
            # polls with heartbeat anyway (blocking creates are an IM-server
            # anti-pattern — upward of a minute on busy clouds).
            inf_id = await self._client.create(desc, desc_type="yaml", asyncr=True)
        except httpx.HTTPError as exc:
            logger.error("Failed to deploy service: %s", exc)
            raise IMError(f"Failed to deploy service: {exc}") from exc
        logger.info("Service deployed successfully with ID: %s", inf_id)
        self.inf_id = str(inf_id)
        return str(inf_id)

    async def get_property(self, inf_id: str, prop: str) -> Any:
        """Get an infrastructure property ("state" | "contmsg" | "outputs")."""
        try:
            return await self._client.get_infra_property(inf_id, prop)
        except httpx.HTTPError as exc:
            raise IMError(
                f"Failed to get infrastructure property {prop}: {exc}"
            ) from exc

    async def destroy(self, inf_id: str | None = None) -> None:
        inf_id = inf_id or self.inf_id
        if inf_id is None:
            return
        try:
            await self._client.destroy(inf_id)
        except httpx.HTTPError as exc:
            raise IMError(f"Failed to destroy service: {exc}") from exc
        logger.info("Service %s destroyed successfully.", inf_id)
        if inf_id == self.inf_id:
            self.inf_id = None

    # -- bounded wait loop with heartbeat ------------------------------------

    async def wait_for_ready(self, heartbeat: Heartbeat | None = None) -> None:
        """Wait for the 'configured' state; bounded by im_max_time /
        im_max_retries / im_sleep. The heartbeat runs on **every** poll
        iteration. On failure: contmsg to logs, destroy, raise IMError —
        identical semantics to the retired synchronous implementation."""
        if self.inf_id is None:
            raise IMError("No service deployed yet.")
        heartbeat = heartbeat or _noop_heartbeat
        logger.info("Waiting for service %s to be ready...", self.inf_id)

        max_time = settings.im_max_time
        wait = 0
        retries = 0
        state = "pending"
        pending_states = ["pending", "running", "unknown"]

        while (
            state in pending_states
            and retries < settings.im_max_retries
            and wait < max_time
        ):
            try:
                state = "unknown"
                res = await self._client.get_infra_property(self.inf_id, "state")
                state = res["state"]
            except Exception as exc:
                logger.exception("Error getting infrastructure state: %s", exc)

            if state == "unknown":
                retries += 1

            # Heartbeat on every poll iteration — liveness depends on it.
            await heartbeat(f"IM state: {state}")

            if state in pending_states:
                logger.debug("The infrastructure is in state: %s. Wait ...", state)
                await asyncio.sleep(settings.im_sleep)
                wait += settings.im_sleep

        if state == "configured":
            logger.info("Service %s is ready.", self.inf_id)
            return

        msg = f"Service did not reach 'configured' state. Current state: {state}."
        if wait >= max_time:
            msg += "(Timeout)"
        logger.error(msg)

        await self._log_contmsg()
        await self._destroy_after_error()
        raise IMError(msg)

    async def _log_contmsg(self) -> None:
        try:
            inflog = await self._client.get_infra_property(self.inf_id, "contmsg")
            logger.debug("Deployment log: %s", inflog)
        except Exception as exc:
            logger.exception("Error getting deployment log: %s", exc)

    async def _destroy_after_error(self) -> None:
        try:
            logger.debug("Destroying service after error.")
            await self.destroy()
        except Exception:
            logger.exception("Failed to destroy service after error")

    # -- composites -----------------------------------------------------------

    async def get_service_outputs(self) -> Mapping[str, Any]:
        if self.inf_id is None:
            raise IMError("No service deployed yet.")
        try:
            return await self._client.get_infra_property(self.inf_id, "outputs")
        except httpx.HTTPError as exc:
            raise IMError("Failed to get service outputs.") from exc

    async def run(
        self,
        rp: RuntimePlatform,
        heartbeat: Heartbeat | None = None,
        on_inf_created: OnInfCreated | None = None,
    ) -> Mapping[str, Any]:
        """Full IM sequence: create -> (persist inf_id) -> wait -> outputs."""
        heartbeat = heartbeat or _noop_heartbeat
        await heartbeat(constants.IM_SEQUENCE_STARTED)
        inf_id = await self.create(rp)
        if on_inf_created is not None:
            # Persisted the instant create() returns: a VM can never exist
            # before its record does.
            await on_inf_created(inf_id)
        await self.wait_for_ready(heartbeat)
        await heartbeat(constants.IM_SEQUENCE_FINISHED)
        outputs = await self.get_service_outputs()
        await heartbeat(constants.IM_SEQUENCE_SUCCESSFUL)
        return outputs

    async def resume(
        self, inf_id: str, heartbeat: Heartbeat | None = None
    ) -> Mapping[str, Any]:
        """Continuation after a worker restart: the server kept provisioning;
        re-poll state, then fetch outputs (no second create)."""
        heartbeat = heartbeat or _noop_heartbeat
        self.inf_id = inf_id
        await heartbeat(constants.IM_SEQUENCE_STARTED)
        await self.wait_for_ready(heartbeat)
        await heartbeat(constants.IM_SEQUENCE_FINISHED)
        outputs = await self.get_service_outputs()
        await heartbeat(constants.IM_SEQUENCE_SUCCESSFUL)
        return outputs
