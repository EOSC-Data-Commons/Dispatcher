import sys
from app.services.im import IM
from fastapi import HTTPException
from abc import ABC, abstractmethod
from typing import Any, Callable, Mapping, Protocol, runtime_checkable
from app.exceptions import VREError, VREConfigurationError
import logging

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
        body: Any | None = None,
        token: str | None = None,
        im_factory: Callable[[str | None], IMClientProtocol] | None = None,
    ) -> None:
        self.crate = crate
        self.body = body
        self.token = token
        self._im_factory = im_factory or self._default_im_factory
        self.svc_url = self.setup_service().rstrip("/")

    @abstractmethod
    def get_default_service(self) -> str:
        pass

    def setup_service(self):
        dest = getattr(self.crate, "root_dataset", {}).get("runsOn")
        return self._resolve_runs_on(dest)

    def _resolve_runs_on(self, dest: Mapping[str, Any] | None) -> str:
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
            outputs = im_client.run_service(dest)
            if outputs is None:
                raise VREConfigurationError("Failed to deploy service via IM")
            return outputs.get("url", self.get_default_service())

        # Anything else is an error.
        raise VREConfigurationError(
            f"Invalid service type in runsOn: {dest.get('serviceType')!r}"
        )

    @staticmethod
    def _default_im_factory(token: str | None) -> IMClientProtocol:
        from app.services.im import IM

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

    def __call__(self, crate, body=None, **kwargs):
        elang = crate.mainEntity.get("programmingLanguage").get("identifier")
        if not self.is_registered(elang):
            raise ValueError(f"Unsupported workflow language {elang}")
        logger.debug(f"crate {crate}")
        logger.debug(f"elang {elang}")
        logger.debug(self.table[elang])
        return self.table[elang](crate=crate, body=body, **kwargs)


vre_factory = VREFactory()

if __name__ == "__main__":
    with open(sys.argv[1]) as j:
        vre_factory(j.read())
