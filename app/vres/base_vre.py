import sys
from app.services.im import IM
from abc import ABC, abstractmethod
from typing import Any, Callable, Mapping, Protocol, runtime_checkable
from app.exceptions import VREError, VREConfigurationError
import logging
import app.constants as constants
from app.domain.rocrate import RequestPackage, ServiceConfig

logger = logging.getLogger("uvicorn.error")


class ROCrateValidationError(Exception):
    pass


@runtime_checkable
class IMClientProtocol(Protocol):
    """Minimal contract of the external IM client used by VRE.setup_service."""

    def run_service(self, dest: Mapping[str, Any]) -> Mapping[str, Any] | None: ...


class VRE(ABC):
    """Base class for all VRE implementations.

    This class requires a RequestPackage instance, which provides strict
    abstraction over ROCrate. VREs should never receive raw ROCrate instances.
    """

    def __init__(
        self,
        request_package: RequestPackage,
        token: str,
        request_id: int,
        update_state: Callable,
        body: Any | None = None,
        im_factory: Callable[[str | None], IMClientProtocol] | None = None,
        **kwargs,
    ) -> None:
        # Strict type checking - must be RequestPackage
        if not isinstance(request_package, RequestPackage):
            raise TypeError(
                f"VRE expects RequestPackage instance, got {type(request_package).__name__}. "
                "Use ROCrateFactory.create_from_dict() to create a RequestPackage."
            )

        self.request_package = request_package
        self.body = body
        self.token = token
        self._update_state = update_state
        self._request_id = request_id
        self._im_factory = im_factory or self._default_im_factory
        self.svc_url = self.setup_service().rstrip("/")

        # Store any additional kwargs for subclasses
        for key, value in kwargs.items():
            setattr(self, key, value)

    @abstractmethod
    def get_default_service(self) -> str:
        """Return the default service URL for this VRE."""
        pass

    def setup_service(self) -> str:
        """Set up the service by resolving runsOn configuration.

        Uses the ServiceConfig value object from RequestPackage.
        """
        service_config = self.request_package.get_service_config()

        if service_config is None:
            return self.get_default_service()

        # No explicit service type – use the URL directly
        if service_config.service_type is None:
            return service_config.url or self.get_default_service()

        # Infrastructure Manager case
        if service_config.service_type == "InfrastructureManager":
            im_client = self._im_factory(self.token)
            if not isinstance(im_client, IMClientProtocol):
                raise TypeError(
                    "Injected IM factory must return an object implementing IMClientProtocol"
                )
            self.update_task_status(constants.IM_SEQUENCE_STARTED)

            # Convert ServiceConfig to mapping for IM client
            dest: Mapping[str, Any] = {
                "url": service_config.url,
                "serviceType": service_config.service_type,
                "memoryRequirements": service_config.memory_requirements,
                "processorRequirements": service_config.processor_requirements,
                "storageRequirements": service_config.storage_requirements,
            }
            outputs = im_client.run_service(dest)
            self.update_task_status(constants.IM_SEQUENCE_FINISHED)
            self.update_task_status(constants.IM_SEQUENCE_SUCCESSFUL)

            if outputs is None:
                raise VREConfigurationError("Failed to deploy service via IM")
            return outputs.get("url", self.get_default_service())

        raise VREConfigurationError(
            f"Invalid service type in runsOn: {service_config.service_type!r}"
        )

    def update_task_status(self, stage: str) -> None:
        """Update the task status with the given stage."""
        self._update_state(state="PROGRESS", meta={"stage": stage})

    @staticmethod
    def _default_im_factory(token: str | None) -> IMClientProtocol:
        return IM(token)

    @abstractmethod
    def post(self) -> str:
        """Execute the VRE-specific workflow and return the result URL."""
        pass


class VREFactory:
    """Factory for creating VRE instances from RequestPackage."""

    instance = None
    table = {}

    def __new__(cls, *args, **kwargs):
        if not cls.instance:
            cls.instance = super(VREFactory, cls).__new__(cls, *args, **kwargs)
        return cls.instance

    def is_registered(self, vre_type: str) -> bool:
        """Check if a VRE type is registered."""
        return vre_type in self.table

    def register(self, vre_type: str, cls: type) -> None:
        """Register a VRE class for a language identifier."""
        if self.is_registered(vre_type):
            raise ValueError(f"{vre_type} already registered")
        self.table[vre_type] = cls

    def __call__(
        self,
        request_package: RequestPackage,
        token: str,
        request_id: int,
        update_state: Callable,
        body: Any | None = None,
        **kwargs,
    ) -> VRE:
        """Create a VRE instance from a RequestPackage.

        Args:
            request_package: The RequestPackage containing the ROCrate data.
            token: Authentication token.
            request_id: Unique request identifier.
            update_state: Callback for updating task state.
            body: Optional request body (e.g., ZIP file content).
            **kwargs: Additional keyword arguments passed to VRE constructor.

        Returns:
            An instantiated VRE.

        Raises:
            ValueError: If the language identifier is not registered.
        """
        # Get language identifier from the workflow info
        workflow = request_package.get_workflow_info()
        elang = workflow.language_identifier

        if not self.is_registered(elang):
            raise ValueError(f"Unsupported workflow language {elang}")

        logger.debug(f"Creating VRE for language: {elang}")
        logger.debug(f"VRE class: {self.table[elang]}")

        return self.table[elang](
            request_package=request_package,
            token=token,
            request_id=request_id,
            update_state=update_state,
            body=body,
            **kwargs,
        )


vre_factory = VREFactory()

if __name__ == "__main__":
    with open(sys.argv[1]) as j:
        vre_factory(j.read())
