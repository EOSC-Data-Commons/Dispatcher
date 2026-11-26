"""Provider adapters: operate an already-resolved external service.

Interpreting ``runtimePlatform``, deploying IM infrastructure, resolving
the service URL, and registering that infrastructure are flow-runner
concerns. VRE implementations own only provider defaults, healthcheck
customization, provider-specific work in ``post()``, and remote teardown in
``delete()``. In particular, no VRE method can create IM infrastructure —
including teardown.
"""

import asyncio
import logging
import sys
from abc import ABC, abstractmethod

from vre_rocrate import VREPayload

from app.exceptions import VREConfigurationError
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
        payload: VREPayload | None = None,
        **kwargs,
    ) -> None:
        self.payload = payload
        self.token = token
        self._status_store = status_store
        self._request_id = request_id
        # Set by vre_runner.resolve_service before post(); provider unit
        # tests may set it directly. Teardown uses the delivered_url hint.
        self.svc_url: str | None = None
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
        return self.require_service_url()

    def require_service_url(self) -> str:
        """Return the flow-resolved service URL, or fail with a clear error.

        ``execute_flow`` guarantees this before invoking ``post()``. Unlike
        the retired ``setup_service()``, this method only validates state;
        it never performs service resolution or deploys infrastructure.
        """
        if self.svc_url is None:
            raise VREConfigurationError(
                "Service URL is not resolved; run the VRE through execute_flow "
                "or assign svc_url for a standalone provider test"
            )
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
        status_store: StatusStore,
        payload: VREPayload | None = None,
        kind: str | None = None,
        **kwargs,
    ):
        """Construct a VRE. Dispatch passes ``payload`` (the language is
        read from it); DELETE-time teardown passes ``kind`` instead — the
        crate is gone by then, and the VRE only needs its ``delivered_url``
        hint (v4 D1).

        ``status_store`` is required on every path: a VRE always writes
        flow progress (and, on the IM path, the infra-registry handle), so
        there is deliberately no store-less construction."""
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
