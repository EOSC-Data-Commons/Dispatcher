import sys
from app.services.im import IM
from vre_rocrate import RuntimePlatform
from abc import ABC, abstractmethod
from typing import Any, Callable, Mapping, Protocol, runtime_checkable
from app.exceptions import VREConfigurationError
import logging
from app.services.kubernetes import KubernetesClient
from app import constants

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
        self.svc_url = self.setup_service().rstrip("/")
        for key, value in kwargs.items():
            setattr(self, key, value)

    @abstractmethod
    def get_default_service(self) -> str:
        pass

    def setup_service(self) -> str:
        k8s_dest = self._get_kubernetes_destination()
        if k8s_dest is not None:
            return self._deploy_kubernetes_destination(k8s_dest)
        rp = self._get_runtime_platform()
        return self._resolve_service_url(rp)

    def _get_runtime_platform(self) -> str | RuntimePlatform | None:
        """Read runtimePlatform from the request package workflow descriptor."""
        if self.request_package is not None:
            return self.request_package.workflow.runtime_platform
        return None

    def _find_destination_entity(self) -> dict | None:
        """Resolve the deployment destination entity from the crate.

        Accepts either link property, checked in order:
          1. the root dataset's ``runsOn``;
          2. the workflow's ``runtimePlatform`` (the raw reference is preserved
             in ``workflow.properties`` even though the builder also exposes it
             as a ``RuntimePlatform`` object).
        Returns the raw destination entity dict, or None.
        """
        if self.request_package is None:
            return None
        ref = None
        root = self.request_package.get_entity("./")
        if isinstance(root, dict):
            ref = root.get("runsOn")
        if ref is None:
            ref = self.request_package.workflow.properties.get("runtimePlatform")
        entity_id = ref.get("@id") if isinstance(ref, dict) else ref
        if not isinstance(entity_id, str) or not entity_id:
            return None
        entity = self.request_package.get_entity(entity_id)
        return entity if isinstance(entity, dict) else None

    def _is_kubernetes_rocrate_destination(self, dest: dict) -> bool:
        """Whether *dest* is an InterLink/RO-Crate Kubernetes destination.

        True for a Service whose ``serviceType`` is ``Kubernetes`` or any
        destination that lists Helm/manifest Repos (``chartType``) in
        ``hasPart``. A plain ``RuntimePlatform`` (name/installUrl/chartName with
        no ``hasPart``) is False, so it takes the generic object path instead.
        """
        if dest.get("serviceType") == "Kubernetes":
            return True
        parts = dest.get("hasPart", [])
        if isinstance(parts, dict):
            parts = [parts]
        for part in parts:
            if isinstance(part, dict) and "@id" in part:
                part = self.request_package.get_entity(part["@id"]) or {}
            if isinstance(part, dict) and part.get("chartType"):
                return True
        return False

    def _get_kubernetes_destination(self) -> dict | None:
        """Return the fully-resolved InterLink Kubernetes destination, or None.

        Discovers the destination via ``runsOn`` or ``runtimePlatform`` and,
        when it is InterLink-shaped, returns it with ``hasPart`` ``@id``
        references expanded to the actual Repo entities. Returns None for
        non-Kubernetes or generic ``RuntimePlatform`` destinations so the
        standard flow runs.
        """
        dest = self._find_destination_entity()
        if dest is None or not self._is_kubernetes_rocrate_destination(dest):
            return None
        return self._expand_has_part(dest)

    def _expand_has_part(self, dest: dict) -> dict:
        """Return a copy of *dest* with ``hasPart`` @id references resolved.

        RO-Crate lists ``hasPart`` as reference objects (``{"@id": "#x"}``); the
        KubernetesClient's RO-Crate flow expects the concrete Repo entities, so
        resolve each one against the graph here.
        """
        resolved = dict(dest)
        parts = dest.get("hasPart", [])
        if isinstance(parts, dict):
            parts = [parts]
        expanded: list = []
        for part in parts:
            if isinstance(part, dict) and "@id" in part:
                entity = self.request_package.get_entity(part["@id"])
                expanded.append(entity if isinstance(entity, dict) else part)
            else:
                expanded.append(part)
        resolved["hasPart"] = expanded
        return resolved

    def _deploy_kubernetes_destination(self, dest: dict) -> str:
        """Deploy the InterLink/Helm charts described by a Kubernetes destination.

        Passes the destination as a dict so ``KubernetesClient.run_service``
        routes to the RO-Crate flow (``_run_rocrate_service``): install each
        chart in ``hasPart``, wait for the InterLink virtual node, and apply
        any manifests.
        """
        self.update_task_status(constants.KUBERNETES_SEQUENCE_STARTED)
        try:
            client = KubernetesClient(user_token=self.token)
            outputs = client.run_service(dest)
            self.update_task_status(constants.KUBERNETES_SEQUENCE_FINISHED)
        except Exception as exc:
            logger.error(f"Kubernetes deployment failed: {exc}")
            raise VREConfigurationError(
                f"Failed to deploy service to Kubernetes: {exc}"
            ) from exc
        if not outputs:
            raise VREConfigurationError("Failed to deploy service to Kubernetes")
        self.update_task_status(constants.KUBERNETES_SEQUENCE_SUCCESSFUL)
        return outputs.get("url", self.get_default_service())

    def _resolve_service_url(self, dest: str | RuntimePlatform | None) -> str:
        if dest is None:
            return self.get_default_service()

        # Plain string: direct URL (e.g. runtimePlatform: "https://usegalaxy.eu/")
        if isinstance(dest, str):
            return dest

        # RuntimePlatform with installUrl – delegate to Infrastructure Manager.
        if dest.install_url is not None:
            if dest.name == "Infrastructure Manager":
                logger.error(f"IM dest {dest}")
                im_client = self._im_factory(self.token, self.update_task_status)  # type: ignore[arg-type]
                if not isinstance(im_client, IMClientProtocol):
                    raise TypeError(
                        "Injected IM factory must return an object implementing IMClientProtocol"
                    )
                outputs = im_client.run_service(dest)
                if outputs is None:
                    raise VREConfigurationError("Failed to deploy service via IM")
                return outputs.get("url", self.get_default_service())
            if dest.name == "Kubernetes":
                logger.error(f"Kubernetes dest {dest}")
                chart_info = self._resolve_chart_info()
                if chart_info is None:
                    raise VREConfigurationError(
                        "Missing hasPart chart configuration for Kubernetes deployment"
                    )
                self.update_task_status(constants.KUBERNETES_SEQUENCE_STARTED)
                try:
                    kubernetes_client = KubernetesClient(user_token=self.token)
                    outputs = kubernetes_client.run_service(dest, chart_info)
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
            raise VREConfigurationError(f"Invalid runtimePlatform: {dest!r}")

        raise VREConfigurationError(f"Invalid runtimePlatform: {dest!r}")

    def _resolve_chart_info(self) -> dict | None:
        """Extract Helm chart metadata from the runtimePlatform raw entity."""
        if self.request_package is None:
            return None
        raw_rp = self.request_package.workflow.properties.get("runtimePlatform")
        if not isinstance(raw_rp, dict):
            return None
        entity_id = raw_rp.get("@id")
        if not entity_id:
            return None
        entity = self.request_package.get_entity(entity_id)
        if not entity:
            return None
        chart_name = entity.get("chartName")
        if not chart_name:
            return None
        return {"chartName": chart_name}

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
