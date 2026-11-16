import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from vre_rocrate import RuntimePlatform, VREPayload

from app.exceptions import IMError, VREConfigurationError
from app.status_store import StatusStore, TaskStatus

from .utils.health import check_service_alive

logger = logging.getLogger(__name__)


class ROCrateValidationError(Exception):
    pass


@runtime_checkable
class AsyncIMProtocol(Protocol):
    """IM contract consumed by VRE service resolution.

    The concrete async wire client lives in the IM repo
    (``imclient.AsyncIMClient``); the dispatcher-side wrapper
    (:class:`app.services.im_async.AsyncIM`) adapts it to this protocol.
    Tests inject ``FakeAsyncIM`` with scripted state transitions.
    """

    inf_id: str | None

    async def run(
        self,
        rp: RuntimePlatform,
        heartbeat: Callable[[str], Any] | None = None,
        on_inf_created: Callable[[str], Any] | None = None,
    ) -> Mapping[str, Any]: ...

    async def destroy(self, inf_id: str | None = None) -> None: ...

    async def aclose(self) -> None: ...


def default_im_factory(token: str | None) -> AsyncIMProtocol:
    """Instantiate the real dispatcher-side async IM wrapper; raises a clean
    :class:`IMError` when the async IM client package is not installed so
    development is never blocked on the IM repo's release."""
    from app.services.im_async import AsyncIM

    return AsyncIM(token)


class VRE(ABC):
    def __init__(
        self,
        token: str,
        request_id: str,
        status_store: StatusStore | None = None,
        im_factory: Callable[[str | None], AsyncIMProtocol] | None = None,
        payload: VREPayload | None = None,
        **kwargs,
    ) -> None:
        self.payload = payload
        self.token = token
        self._status_store = status_store
        self._request_id = request_id
        self._im_factory = im_factory or default_im_factory
        # Lazily resolved on first post(); tests assign `svc_url` directly.
        self.svc_url: str | None = None
        self._deployed_via_im = False
        for key, value in kwargs.items():
            setattr(self, key, value)

    @abstractmethod
    def get_default_service(self) -> str:
        pass

    def get_healthcheck_url(self) -> str:
        """URL probed by check_health() to verify provider availability.

        Override in subclasses to point to a lightweight provider-specific
        endpoint. The default probes the service root URL.
        """
        return self.svc_url

    async def check_health(self) -> None:
        """Fail fast if the VRE provider for the resolved service is
        unavailable.

        Skipped for services deployed via the Infrastructure Manager — their
        URL does not exist before deployment. The sync probe runs in a
        worker thread so the event loop is never blocked.
        """
        if self._deployed_via_im:
            return
        await asyncio.to_thread(check_service_alive, self.get_healthcheck_url())

    async def setup_service(self) -> str:
        """Resolve the service URL once (may run the whole IM sequence),
        then probe the provider if the URL is direct (not IM-deployed)."""
        if self.svc_url is None:
            rp = self._get_runtime_platform()
            self.svc_url = (await self._resolve_service_url(rp)).rstrip("/")
            await self.check_health()
        return self.svc_url

    def _get_runtime_platform(self) -> str | RuntimePlatform | None:
        """Read runtimePlatform from the VRE payload workflow descriptor."""
        if self.payload is not None:
            return self.payload.workflow.runtime_platform
        return None

    async def _resolve_service_url(self, dest: str | RuntimePlatform | None) -> str:
        if dest is None:
            return self.get_default_service()

        # Plain string: direct URL (e.g. runtimePlatform: "https://usegalaxy.eu/")
        if isinstance(dest, str):
            return dest

        # RuntimePlatform with installUrl – delegate to Infrastructure Manager.
        if dest.install_url is not None:
            logger.debug(f"IM dest {dest}")
            im_client = self._im_factory(self.token)
            if not isinstance(im_client, AsyncIMProtocol):
                raise TypeError(
                    "Injected IM factory must return an object implementing AsyncIMProtocol"
                )
            try:
                outputs = await im_client.run(
                    dest,
                    heartbeat=self.update_task_status,
                    on_inf_created=self._on_inf_created,
                )
            finally:
                await im_client.aclose()
            if outputs is None:
                raise VREConfigurationError("Failed to deploy service via IM")
            self._deployed_via_im = True
            return outputs.get("url", self.get_default_service())

        raise VREConfigurationError(f"Invalid runtimePlatform: {dest!r}")

    async def _on_inf_created(self, inf_id: str) -> None:
        """Persisted the instant create() returns: im_inf_id only (the
        infrastructure registry — cleanup's handle to the VM).

        A missing store here silently breaks the infra-registry invariant
        ("no VM without a record") — it must always be audible."""
        if self._status_store is None:
            logger.warning(
                "No status store: skipping infra bookkeeping for task %s "
                "(inf_id=%s would not be recorded)",
                self._request_id,
                inf_id,
            )
            return
        await self._status_store.update(self._request_id, im_inf_id=inf_id)

    async def update_task_status(self, stage: str) -> None:
        """Progress write into the status store; also the IM heartbeat —
        every write refreshes ``updated_at`` (the janitor's liveness signal)."""
        if self._status_store is None:
            logger.debug("No status store: progress stage %r not recorded", stage)
            return
        await self._status_store.update(
            self._request_id, status=TaskStatus.PROGRESS, stage=stage
        )

    @abstractmethod
    async def post(self):
        pass

    async def delete(self) -> None:
        """Tear down remote state left behind by ``post()`` (services, jobs,
        servers on shared infrastructure), if the VRE creates any.

        Part of every VRE's contract alongside :meth:`post`: VREs that
        provision remote state MUST override it with real teardown; VREs that
        only produce a URL inherit this no-op. Called best-effort by
        ``dispatch.delete_flow`` (errors are logged there, never raised).
        """
        logger.debug(
            "delete() not implemented for %s — nothing to do", type(self).__name__
        )


class VREFactory:
    instance: "VREFactory | None" = None
    table: dict[str, type] = {}

    def __new__(cls, *args, **kwargs):
        if not cls.instance:
            cls.instance = super(VREFactory, cls).__new__(cls, *args, **kwargs)
        return cls.instance

    def is_registered(self, vre_type):
        return vre_type in self.table

    def register(self, vre_type, cls):
        if self.is_registered(vre_type):
            raise ValueError(f"{vre_type} already registered")
        self.table[vre_type] = cls

    def __call__(
        self,
        token: str,
        request_id: str,
        status_store: StatusStore | None = None,
        payload: VREPayload | None = None,
        kind: str | None = None,
        **kwargs,
    ):
        """Construct a VRE. Dispatch passes ``payload`` (the language is
        read from it); DELETE-time teardown passes ``kind`` instead — the
        crate is gone by then, and the VRE only needs its ``delivered_url``
        hint (v4 D1)."""
        if payload is None:
            if kind is None:
                raise ValueError("payload is required (or kind for teardown)")
            elang = kind
        else:
            elang = payload.programming_language
        if not self.is_registered(elang):
            raise ValueError(f"Unsupported workflow language {elang}")
        logger.debug(f"elang {elang}")
        logger.debug(self.table[elang])
        return self.table[elang](
            token=token,
            request_id=request_id,
            status_store=status_store,
            payload=payload,
            **kwargs,
        )


vre_factory = VREFactory()

if __name__ == "__main__":
    with open(sys.argv[1]) as j:
        vre_factory(j.read())
