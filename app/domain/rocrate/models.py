from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    id: str
    type: str | list[str]
    properties: dict[str, Any] = field(default_factory=dict, repr=False)

    def get(self, key: str, default: Any = None) -> Any:
        return self.properties.get(key, default)


class _MetadataProxy:
    """Proxy that wraps the raw crate dict and exposes ``generate()``."""

    def __init__(self, raw: dict[str, Any]):
        self._raw = raw

    def generate(self) -> dict[str, Any]:
        return self._raw


@dataclass
class ParsedCrate:
    root_id: str
    entities: dict[str, Entity]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def root_dataset(self) -> Entity | None:
        return self.entities.get(self.root_id)

    @property
    def main_entity(self) -> Entity | None:
        root = self.root_dataset
        if root is None:
            return None
        main_ref = root.get("mainEntity")
        if main_ref is None:
            return None
        if isinstance(main_ref, dict):
            return self.entities.get(main_ref.get("@id", ""))
        if isinstance(main_ref, str):
            return self.entities.get(main_ref)
        eid = getattr(main_ref, "id", None) or main_ref.get("@id", "")
        return self.entities.get(eid)

    @property
    def name(self) -> str | None:
        root = self.root_dataset
        return root.get("name") if root else None

    @property
    def description(self) -> str | None:
        root = self.root_dataset
        return root.get("description") if root else None

    @property
    def metadata(self) -> _MetadataProxy:
        return _MetadataProxy(self.raw)

    def get(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id)

    def get_entities(self) -> list[Entity]:
        return list(self.entities.values())


@dataclass
class IMInputFile:
    """Typed descriptor for a file to stage into the deployed service."""

    url: str
    destination: str | None = None
    compute_node: str | None = None


@dataclass
class RuntimePlatform:
    """Domain representation of a RO-Crate RuntimePlatform entity."""

    name: str
    install_url: str | None = None
    memory: str | None = None
    num_cpus: int = 1
    num_gpus: int = 0
    storage: str | None = None
    input_files: list[IMInputFile] = field(default_factory=list)

    @classmethod
    def from_dict(cls, dest: dict[str, Any]) -> RuntimePlatform:
        """Build RuntimePlatform from a RO-Crate RuntimePlatform dict."""
        cpus = dest.get("processorRequirements")
        num_cpus = 1
        num_gpus = 0
        if isinstance(cpus, str) and "vCPU" in cpus:
            num_cpus = int(cpus.replace("vCPU", "").strip())
        elif isinstance(cpus, list):
            for cpu in cpus:
                if "vCPU" in cpu:
                    num_cpus = int(cpu.replace("vCPU", "").strip())
                if "GPU" in cpu:
                    num_gpus = int(cpu.replace("GPU", "").strip())

        input_files = []
        for raw_file in dest.get("input", []):
            if raw_file.get("@type") != "File":
                logger.warning("Input is not of type File, skipping.")
                continue
            file_url = raw_file.get("@id")
            if not file_url:
                logger.warning("Input does not have a @id, skipping.")
                continue
            content_location = raw_file.get("contentLocation")
            compute_node = None
            destination = content_location
            if content_location and ":" in content_location:
                parts = content_location.split(":", 1)
                compute_node = parts[0]
                destination = parts[1]
            input_files.append(
                IMInputFile(
                    url=file_url,
                    destination=destination,
                    compute_node=compute_node,
                )
            )

        return cls(
            name=dest.get("name", "Infrastructure Manager"),
            install_url=dest.get("installUrl"),
            memory=dest.get("memoryRequirements"),
            num_cpus=num_cpus,
            num_gpus=num_gpus,
            storage=dest.get("storageRequirements"),
            input_files=input_files,
        )
