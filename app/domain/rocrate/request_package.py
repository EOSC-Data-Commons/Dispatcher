from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any
from .models import ParsedCrate


@dataclass
class FormalParameter:
    id: str
    name: str
    additional_type: str | None = None
    encoding_format: str | None = None
    default_value: Any = None
    properties: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class FileReference:
    id: str
    name: str
    encoding_format: str | None = None
    url: str | None = None
    onedata_domain: str | None = None
    onedata_file_id: str | None = None
    properties: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class ServiceTarget:
    service_type: str | None = None
    url: str | None = None
    raw: dict[str, Any] | str = field(default_factory=dict, repr=False)


@dataclass
class WorkflowDescriptor:
    id: str
    type: str
    url: str | None = None
    programming_language_id: str | None = None
    runtime_platform: str | dict[str, Any] | None = None
    properties: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class RequestPackage:
    vre_type: str
    programming_language: str
    workflow: WorkflowDescriptor
    files: list[FileReference] = field(default_factory=list)
    service_target: ServiceTarget | None = None
    workflow_inputs: list[FormalParameter] = field(default_factory=list)
    workflow_outputs: list[FormalParameter] = field(default_factory=list)
    raw_crate: dict[str, Any] = field(default_factory=dict, repr=False)

    def files_by_encoding(self, encoding: str) -> list[FileReference]:
        return [f for f in self.files if f.encoding_format == encoding]

    def file_by_id(self, file_id: str) -> FileReference | None:
        for f in self.files:
            if f.id == file_id:
                return f
        return None

    @property
    def local_files(self) -> list[FileReference]:
        return [f for f in self.files if not f.id.startswith(("http://", "https://"))]

    @property
    def remote_files(self) -> list[FileReference]:
        return [f for f in self.files if f.id.startswith(("http://", "https://"))]

    @property
    def workflow_url(self) -> str | None:
        return self.workflow.url

    @property
    def input_files(self) -> list[FileReference]:
        return self.files

    @property
    def fdl_url(self) -> str | None:
        return self.workflow.url

    @property
    def script_files(self) -> list[FileReference]:
        return self.files_by_encoding("text/x-shellscript")

    @property
    def oscar_input_files(self) -> list[FileReference]:
        excluded = {f.id for f in self.script_files}
        return [f for f in self.files if f.id not in excluded]

    @property
    def tosca_file(self) -> FileReference | None:
        return next(
            (f for f in self.files if f.encoding_format == "text/yaml"),
            None,
        )

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        graph = self.raw_crate.get("@graph", [])
        for item in graph:
            if item.get("@id") == entity_id:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RequestPackage:
        workflow = WorkflowDescriptor(**data.pop("workflow"))
        service_target = data.pop("service_target", None)
        if service_target:
            service_target = ServiceTarget(**service_target)
        files = [FileReference(**f) for f in data.pop("files", [])]
        workflow_inputs = [
            FormalParameter(**p) for p in data.pop("workflow_inputs", [])
        ]
        workflow_outputs = [
            FormalParameter(**p) for p in data.pop("workflow_outputs", [])
        ]
        return cls(
            workflow=workflow,
            service_target=service_target,
            files=files,
            workflow_inputs=workflow_inputs,
            workflow_outputs=workflow_outputs,
            **data,
        )

    @staticmethod
    def _resolve_ref(crate: ParsedCrate, ref: object) -> object:
        if isinstance(ref, dict) and "@id" in ref:
            resolved = crate.get(ref["@id"])
            if resolved is not None:
                return resolved
            return ref
        return ref

    @classmethod
    def from_parsed_crate(cls, crate: ParsedCrate) -> RequestPackage:
        root = crate.root_dataset
        main = crate.main_entity
        if main is None:
            raise ValueError("Cannot build RequestPackage without mainEntity")

        lang_ref = main.get("programmingLanguage", {})
        lang_obj = cls._resolve_ref(crate, lang_ref)
        lang_id = lang_obj.get("identifier") if lang_obj is not None else None

        runtime_platform_raw = main.get("runtimePlatform")
        runtime_platform = cls._resolve_ref(crate, runtime_platform_raw)
        service_target = None
        if isinstance(runtime_platform, str):
            service_target = ServiceTarget(url=runtime_platform, raw=runtime_platform)
        elif runtime_platform is not None:
            service_target = ServiceTarget(
                service_type=runtime_platform.get("serviceType"),
                url=runtime_platform.get("url"),
                raw=runtime_platform_raw,
            )

        workflow = WorkflowDescriptor(
            id=main.id,
            type=main.type if isinstance(main.type, str) else main.type[0],
            url=main.get("url"),
            programming_language_id=lang_id,
            runtime_platform=runtime_platform,
            properties=main.properties,
        )

        files = cls._extract_files(
            crate, root.get("hasPart", []) if root else [], main.id
        )
        workflow_inputs = cls._extract_parameters(crate, main.get("input", []))
        workflow_outputs = cls._extract_parameters(crate, main.get("output", []))

        return cls(
            vre_type=lang_id or "unknown",
            programming_language=lang_id or "unknown",
            workflow=workflow,
            files=files,
            service_target=service_target,
            workflow_inputs=workflow_inputs,
            workflow_outputs=workflow_outputs,
            raw_crate=crate.raw,
        )

    @staticmethod
    def _extract_files(
        crate: ParsedCrate, has_part: list[Any], main_id: str
    ) -> list[FileReference]:
        files: list[FileReference] = []
        for ref in has_part:
            eid = ref if isinstance(ref, str) else ref.get("@id")
            if not eid or eid == main_id:
                continue
            entity = crate.get(eid)
            if entity is None:
                continue
            entity_types = (
                entity.type if isinstance(entity.type, list) else [entity.type]
            )
            if "File" not in entity_types:
                continue
            props = entity.properties
            files.append(
                FileReference(
                    id=entity.id,
                    name=props.get("name", entity.id),
                    encoding_format=props.get("encodingFormat"),
                    url=props.get("url") or entity.id,
                    onedata_domain=props.get("onedata:onezoneDomain"),
                    onedata_file_id=props.get("onedata:fileId"),
                    properties=props,
                )
            )
        return files

    @staticmethod
    def _extract_parameters(
        crate: ParsedCrate, param_refs: list[Any]
    ) -> list[FormalParameter]:
        params: list[FormalParameter] = []
        for ref in param_refs:
            eid = ref if isinstance(ref, str) else ref.get("@id")
            if not eid:
                continue
            entity = crate.get(eid)
            if entity is None:
                continue
            props = entity.properties
            params.append(
                FormalParameter(
                    id=entity.id,
                    name=props.get("name", entity.id),
                    additional_type=props.get("additionalType"),
                    encoding_format=props.get("encodingFormat"),
                    default_value=props.get("defaultValue"),
                    properties=props,
                )
            )
        return params
