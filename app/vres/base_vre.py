import sys
import asyncio
from app.services.im import IM
from app.services.kubernetes import KubernetesClient
from abc import ABC, abstractmethod
from typing import Any, Callable, Mapping, Optional, Protocol, runtime_checkable
from app.exceptions import VREError, VREConfigurationError
import logging
import app.constants as constants

logger = logging.getLogger("uvicorn.error")


class ROCrateValidationError(Exception):
    pass


@runtime_checkable
class IMClientProtocol(Protocol):
    """Minimal contract of the external IM client used by VRE.setup_service."""

    def run_service(self, dest: Mapping[str, Any]) -> Mapping[str, Any] | None: ...


class VRE(ABC):
    def __init__(
        self,
        crate: Any | None = None,
        update_state: Optional[Callable] = None,
        body: Any | None = None,
        token: str | None = None,
        im_factory: Callable[[str | None], IMClientProtocol] | None = None,
        **kwargs,
    ) -> None:
        self.crate = crate
        self.body = body
        self.token = token
        self._update_state = update_state
        self._im_factory = im_factory or self._default_im_factory
        # Run async setup_service in sync context
        self.svc_url = None
        # Store any additional kwargs for subclasses
        for key, value in kwargs.items():
            setattr(self, key, value)

    @abstractmethod
    def get_default_service(self) -> str:
        pass

    async def setup_service(self):
        dest = getattr(self.crate, "root_dataset", {}).get("runsOn")
        self.svc_url = (await self._resolve_runs_on(dest)).rstrip("/")
        return self

    async def _resolve_runs_on(self, dest: Mapping[str, Any] | None) -> str:
        if dest is None:
            return self.get_default_service()

        # No explicit service type – the dict is expected to contain a direct URL.
        if dest.get("serviceType") is None:
            return dest.get("url", self.get_default_service())

        # Infrastructure Manager case – delegate to the injected client.
        if dest.get("serviceType") == "InfrastructureManager":
            im_client = self._im_factory(self.token)  # type: ignore[arg-type]
            if not isinstance(im_client, IMClientProtocol):
                raise TypeError(
                    "Injected IM factory must return an object implementing IMClientProtocol"
                )
            self.update_task_status(constants.IM_SEQUENCE_STARTED)
            outputs = im_client.run_service(dest)
            self.update_task_status(constants.IM_SEQUENCE_FINISHED)
            if outputs is None:
                raise VREConfigurationError("Failed to deploy service via IM")
            self.update_task_status(constants.IM_SEQUENCE_SUCCESSFUL)
            return outputs.get("url", self.get_default_service())

        # Kubernetes case – delegate to Kubernetes deployment.
        if dest.get("serviceType") == "Kubernetes":
            self.update_task_status(constants.KUBERNETES_SEQUENCE_STARTED)
            try:
                kubernetes_client = KubernetesClient()
                outputs = await kubernetes_client.run_service(
                    dest, getattr(self.crate, "root_dataset", {})
                )
                self.update_task_status(constants.KUBERNETES_SEQUENCE_FINISHED)
                if outputs is None:
                    raise VREConfigurationError(
                        "Failed to deploy service to Kubernetes"
                    )
                self.update_task_status(constants.KUBERNETES_SEQUENCE_SUCCESSFUL)
                return outputs.get("url", self.get_default_service())
            except Exception as e:
                logger.error(f"Kubernetes deployment failed: {e}")
                raise VREConfigurationError(
                    f"Failed to deploy service to Kubernetes: {e}"
                )

        # Anything else is an error.
        raise VREConfigurationError(
            f"Invalid service type in runsOn: {dest.get('serviceType')!r}"
        )

    def update_task_status(self, stage):
        self._update_state(state="PROGRESS", meta={"stage": stage})

    @staticmethod
    def _default_im_factory(token: str | None) -> IMClientProtocol:
        return IM(token)

    @abstractmethod
    def post(self):
        pass


class VREFactory:
    instance = None
    table = {}

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

    async def __call__(
        self,
        crate,
        body=None,
        update_state: Optional[Callable] = None,
        **kwargs,
    ):
        elang = crate.mainEntity.get("programmingLanguage").get("identifier")
        if not self.is_registered(elang):
            raise ValueError(f"Unsupported workflow language {elang}")
        logger.debug(f"crate {crate}")
        logger.debug(f"elang {elang}")
        logger.debug(self.table[elang])
        instance = self.table[elang](
            crate=crate, body=body, update_state=update_state, **kwargs
        )
        return await instance.setup_service()


vre_factory = VREFactory()

if __name__ == "__main__":
    with open(sys.argv[1]) as j:
        vre_factory(j.read())
