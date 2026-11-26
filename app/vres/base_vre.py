"""Provider adapters: operate an already-resolved external service.

Interpreting ``runtimePlatform``, deploying IM infrastructure, resolving
the service URL, and registering that infrastructure are flow-runner
concerns. Provider registrations carry default URLs; VRE implementations own
healthcheck customization, provider-specific work in ``post()``, and remote
teardown in ``delete()``. In particular, no VRE method can create IM infrastructure —
including teardown.
"""

import asyncio
import logging
import sys
from abc import ABC, abstractmethod

from vre_rocrate import VREPayload

from app.status_store import StatusStore, TaskStatus

from .utils.health import check_service_alive

logger = logging.getLogger(__name__)


class ROCrateValidationError(Exception):
    pass


class VRE(ABC):
    def __init__(
        self,
        token: str,
        request_id: str,
        status_store: StatusStore,
        svc_url: str,
        payload: VREPayload | None = None,
        **kwargs,
    ) -> None:
        self.payload = payload
        self.token = token
        self._status_store = status_store
        self._request_id = request_id
        # Resolution completes before construction, so an initialized VRE can
        # always operate its provider without a setup/validation phase.
        self.svc_url = svc_url.rstrip("/")
        for key, value in kwargs.items():
            setattr(self, key, value)

    def get_healthcheck_url(self) -> str:
        """URL probed by check_health() to verify provider availability.

        Override in subclasses to point to a lightweight provider-specific
        endpoint. The default probes the service root URL.
        """
        return self.svc_url

    async def check_health(self) -> None:
        """Fail fast if the provider for the resolved service is unavailable.

        The runner calls this only for non-IM services. The sync probe runs
        in a worker thread so the event loop is never blocked.
        """
        await asyncio.to_thread(check_service_alive, self.get_healthcheck_url())

    async def update_task_status(self, stage: str) -> None:
        """Progress write into the status store; also the IM heartbeat —
        every write refreshes ``updated_at`` (the janitor's liveness signal)."""
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
    table: dict[str, tuple[type[VRE], str]] = {}

    def __new__(cls, *args, **kwargs):
        if not cls.instance:
            cls.instance = super(VREFactory, cls).__new__(cls, *args, **kwargs)
        return cls.instance

    def is_registered(self, vre_type):
        return vre_type in self.table

    def register(self, vre_type, cls, default_service: str):
        if self.is_registered(vre_type):
            raise ValueError(f"{vre_type} already registered")
        self.table[vre_type] = (cls, default_service)

    def __call__(
        self,
        token: str,
        request_id: str,
        status_store: StatusStore,
        svc_url: str | None = None,
        payload: VREPayload | None = None,
        kind: str | None = None,
        **kwargs,
    ) -> VRE:
        """Construct a VRE, using its registered default when no URL is given.

        Dispatch passes ``payload`` (the language is read from it);
        DELETE-time teardown passes ``kind`` instead — the crate is gone by
        then, and the VRE only needs its ``delivered_url`` hint (v4 D1).
        """
        if payload is None:
            if kind is None:
                raise ValueError("payload is required (or kind for teardown)")
            elang = kind
        else:
            elang = payload.programming_language
        if not self.is_registered(elang):
            raise ValueError(f"Unsupported workflow language {elang}")

        vre_class, default_service = self.table[elang]
        if svc_url is None:
            svc_url = default_service
        logger.debug(f"Selected VRE {vre_class}")
        return vre_class(
            token=token,
            request_id=request_id,
            status_store=status_store,
            svc_url=svc_url,
            payload=payload,
            **kwargs,
        )


vre_factory = VREFactory()

if __name__ == "__main__":
    with open(sys.argv[1]) as j:
        vre_factory(j.read())
