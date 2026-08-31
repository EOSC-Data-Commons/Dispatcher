import sys
from app.services.im import IM
from vre_rocrate import RuntimePlatform
from abc import ABC, abstractmethod
from typing import Any, Callable, Mapping, Protocol, runtime_checkable
from app.exceptions import VREConfigurationError
import logging

logger = logging.getLogger(__name__)


class ROCrateValidationError(Exception):
    pass


@runtime_checkable
class IMClientProtocol(Protocol):
    """Minimal contract of the external IM client used by VRE.setup_service."""

    def run_service(self, rp: RuntimePlatform) -> Mapping[str, Any] | None: ...


class VRE(ABC):
    def __init__(
        self,
        token: str,
        request_id: int,
        update_state: Callable,
        im_factory: Callable[[str | None], IMClientProtocol] | None = None,
        request_package: Any | None = None,
        **kwargs,
    ) -> None:
        self.request_package = request_package
        self.token = token
        self._update_state = update_state
        self._request_id = request_id
        self._im_factory = im_factory or self._default_im_factory
        self.ssh = None
        self.svc_url = self.setup_service().rstrip("/")
        for key, value in kwargs.items():
            setattr(self, key, value)

    @abstractmethod
    def get_default_service(self) -> str:
        pass

    def setup_service(self) -> str:
        rp = self._get_runtime_platform()
        return self._resolve_service_url(rp)

    def _get_runtime_platform(self) -> str | RuntimePlatform | None:
        """Read runtimePlatform from the request package workflow descriptor."""
        if self.request_package is not None:
            return self.request_package.workflow.runtime_platform
        return None

    def _resolve_service_url(self, dest: str | RuntimePlatform | None) -> str:
        if dest is None:
            return self.get_default_service()

        # Plain string: direct URL (e.g. runtimePlatform: "https://usegalaxy.eu/")
        if isinstance(dest, str):
            return dest

        # RuntimePlatform with installUrl – delegate to Infrastructure Manager.
        if dest.install_url is not None:
            logger.error(f"IM dest {dest}")
            im_client = self._im_factory(self.token, self.update_task_status)  # type: ignore[arg-type]
            if not isinstance(im_client, IMClientProtocol):
                raise TypeError(
                    "Injected IM factory must return an object implementing IMClientProtocol"
                )
            outputs = im_client.run_service(dest)
            if outputs is None:
                raise VREConfigurationError("Failed to deploy service via IM")
            # Get also SSH information if available, for example to connect to a remote Scipion instance.
            self.ssh = outputs.get("ssh")
            return outputs.get("url", self.get_default_service())

        raise VREConfigurationError(f"Invalid runtimePlatform: {dest!r}")

    def update_task_status(self, stage):
        self._update_state(state="PROGRESS", meta={"stage": stage})

    @staticmethod
    def _default_im_factory(
        token: str | None, update_task_status: Callable[[str], None]
    ) -> IMClientProtocol:
        return IM(token, update_task_status)

    @abstractmethod
    def post(self):
        pass


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
        request_id: int,
        update_state: Callable,
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
            request_package=request_package,
            **kwargs,
        )


vre_factory = VREFactory()

if __name__ == "__main__":
    with open(sys.argv[1]) as j:
        vre_factory(j.read())
