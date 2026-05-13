import sys
from app.services.im import IM
from abc import ABC, abstractmethod
from typing import Any, Callable, Mapping, Protocol, runtime_checkable
from app.exceptions import VREError, VREConfigurationError
import logging
import app.constants as constants

logger = logging.getLogger()


class ROCrateValidationError(Exception):
    pass


@runtime_checkable
class IMClientProtocol(Protocol):
    """Minimal contract of the external IM client used by VRE.setup_service."""

    def run_service(self, dest: Mapping[str, Any]) -> Mapping[str, Any] | None: ...


class VRE(ABC):
    def __init__(
        self,
        token: str,
        request_id: int,
        update_state: Callable,
        body: Any | None = None,
        im_factory: Callable[[str | None], IMClientProtocol] | None = None,
        request_package: Any | None = None,
        **kwargs,
    ) -> None:
        self.request_package = request_package
        self.body = body
        self.token = token
        self._update_state = update_state
        self._request_id = request_id
        self._im_factory = im_factory or self._default_im_factory
        self.svc_url = self.setup_service().rstrip("/")
        for key, value in kwargs.items():
            setattr(self, key, value)

    @abstractmethod
    def get_default_service(self) -> str:
        pass

    def setup_service(self) -> str:
        dest = self._get_runtime_platform()
        return self._resolve_runs_on(dest)

    def _get_runtime_platform(self) -> Mapping[str, Any] | None:
        """Read runtimePlatform from the request package workflow descriptor."""
        if self.request_package is not None:
            rp = self.request_package.workflow.runtime_platform
            if rp is not None:
                # If it's an Entity (from ParsedCrate), return its properties dict
                if hasattr(rp, "properties"):
                    return dict(rp.properties)
                return rp
        return None

    def _resolve_runs_on(self, dest: Mapping[str, Any] | str | None) -> str:
        if dest is None:
            return self.get_default_service()

        # Plain string: direct URL (e.g. runtimePlatform: "https://usegalaxy.eu/")
        if isinstance(dest, str):
            return dest

        # RuntimePlatform with installUrl – delegate to Infrastructure Manager.
        if dest.get("installUrl") is not None:
            logger.error(f"IM dest {dest}")
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

        # No explicit service type – the dict is expected to contain a direct URL.
        if dest.get("serviceType") is None:
            return dest.get("url", self.get_default_service())

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

    def __call__(
        self,
        token: str,
        request_id: int,
        update_state: Callable,
        body: Any | None = None,
        request_package: Any | None = None,
        **kwargs,
    ):
        if request_package is None:
            raise ValueError("request_package is required")
        elang = request_package.programming_language
        if not self.is_registered(elang):
            raise ValueError(f"Unsupported workflow language {elang}")
        logger.debug(f"elang {elang}")
        logger.debug(self.table[elang])
        return self.table[elang](
            token=token,
            request_id=request_id,
            update_state=update_state,
            body=body,
            request_package=request_package,
            **kwargs,
        )


vre_factory = VREFactory()

if __name__ == "__main__":
    with open(sys.argv[1]) as j:
        vre_factory(j.read())
