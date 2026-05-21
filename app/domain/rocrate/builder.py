from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

from .models import ParsedCrate
from .request_package import RequestPackage
from .validator import ValidationPipeline
import app.constants as constants


class RequestPackageBuilder:
    @classmethod
    def build(
        cls,
        crate: ParsedCrate,
        file_bytes_map: dict[str, bytes] | None = None,
    ) -> RequestPackage:
        ValidationPipeline.validate_basic(crate)
        package = RequestPackage.from_parsed_crate(crate)
        if file_bytes_map:
            for fref in package.files:
                if fref.id in file_bytes_map:
                    fref.properties["content"] = file_bytes_map[fref.id]
        return package

    @classmethod
    def build_from_minimal(
        cls,
        data: dict[str, Any],
        file_bytes_map: dict[str, bytes],
    ) -> RequestPackage:
        vre_type = data["vre_type"]
        programming_language = constants.VRE_TYPE_TO_PROGRAMMING_LANGUAGE[vre_type]
        workflow = data.get("workflow")
        runtime_platform = (
            str(data["runtime_platform"]) if data.get("runtime_platform") else None
        )

        return RequestPackage.from_minimal(
            vre_type=vre_type,
            programming_language=programming_language,
            workflow_url=workflow,
            files_data=data.get("files", []),
            file_bytes_map=file_bytes_map,
            runtime_platform=runtime_platform,
        )


class RocrateBuilder:
    """Builds a complete ROCrate JSON dict from a minimal VRE request.

    Uses instance methods with shared state to construct individual entities
    and assemble them into a complete @graph.
    """

    def __init__(
        self,
        vre_type: str,
        programming_language: str,
        workflow_id: str,
        lang_id: str,
        runtime_platform: str | None,
        files_data: list[dict[str, Any]],
        now_iso: str,
    ):
        self.vre_type = vre_type
        self.programming_language = programming_language
        self.workflow_id = workflow_id
        self.lang_id = lang_id
        self.runtime_platform = runtime_platform
        self.files_data = files_data
        self.now_iso = now_iso
        self.graph: list[dict[str, Any]] = []
        self.result: dict[str, Any] | None = None

    def _add_metadata_descriptor(self) -> None:
        """Add the ro-crate-metadata.json descriptor entity to the graph."""
        self.graph.append(
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "about": {"@id": "./"},
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
            }
        )

    def _add_root_dataset(self) -> None:
        """Add the root Dataset entity with hasPart references to the graph."""
        root_has_part: list[dict[str, str]] = [{"@id": self.workflow_id}]
        for f in self.files_data:
            file_url = str(f["url"]) if f.get("url") else None
            file_id = file_url or f["name"]
            if file_id == self.workflow_id:
                continue
            root_has_part.append({"@id": file_id})

        self.graph.append(
            {
                "@id": "./",
                "@type": "Dataset",
                "name": "placeholder",
                "description": "placeholder",
                "datePublished": self.now_iso,
                "license": {"@id": "https://spdx.org/licenses/GPL-3.0"},
                "creator": {"@id": "#author-dispatcher"},
                "mainEntity": {"@id": self.workflow_id},
                "hasPart": root_has_part,
            }
        )

    def _add_workflow_entity(self) -> None:
        """Add the workflow (mainEntity) entity to the graph."""
        workflow_entity: dict[str, Any] = {
            "@id": self.workflow_id,
            "@type": ["File", "SoftwareSourceCode", "ComputationalWorkflow"],
            "name": "placeholder",
            "programmingLanguage": {"@id": self.lang_id},
        }
        if self.runtime_platform:
            workflow_entity["runtimePlatform"] = self.runtime_platform
        self.graph.append(workflow_entity)

    def _add_programming_language(self) -> None:
        """Add the programming language entity to the graph."""
        self.graph.append(
            {
                "@id": self.lang_id,
                "@type": "ComputerLanguage",
                "identifier": self.programming_language,
                "name": self.vre_type.capitalize(),
                "url": self.programming_language,
            }
        )

    def _add_file_entities(self) -> None:
        """Add file entities from the files_data list to the graph."""
        for f in self.files_data:
            file_url = str(f["url"]) if f.get("url") else None
            file_id = file_url or f["name"]
            if file_id == self.workflow_id:
                continue

            file_entity: dict[str, Any] = {
                "@id": file_id,
                "@type": "File",
                "name": f["name"],
            }
            if f.get("encoding_format"):
                file_entity["encodingFormat"] = f["encoding_format"]
            if file_url:
                file_entity["url"] = file_url
            if f.get("onedata_domain"):
                file_entity["onedata:onezoneDomain"] = f["onedata_domain"]
            if f.get("onedata_file_id"):
                file_entity["onedata:fileId"] = f["onedata_file_id"]
            self.graph.append(file_entity)

    def _add_supporting_entities(self) -> None:
        """Add supporting entities (author, license) to the graph."""
        self.graph.append(
            {
                "@id": "#author-dispatcher",
                "@type": "Person",
                "name": "Dispatcher System",
            }
        )
        self.graph.append(
            {
                "@id": "https://spdx.org/licenses/GPL-3.0",
                "@type": "CreativeWork",
                "name": "GNU General Public License v3.0",
                "alternateName": "GPL-3.0",
            }
        )

    def build(self) -> dict[str, Any]:
        """Build and return the complete ROCrate JSON dict.

        Returns:
            A complete ROCrate JSON structure with @context and @graph.
        """
        self._add_metadata_descriptor()
        self._add_root_dataset()
        self._add_workflow_entity()
        self._add_programming_language()
        self._add_file_entities()
        self._add_supporting_entities()
        self.result = {
            "@context": "https://w3id.org/ro/crate/1.1/context",
            "@graph": self.graph,
        }
        return self.result

    @staticmethod
    def build_from_minimal(data: dict[str, Any]) -> dict[str, Any]:
        """Convert a MinimalVRERequest dict into a complete ROCrate JSON dict.

        Args:
            data: The minimal VRE request data dictionary.

        Returns:
            A complete ROCrate JSON structure with @context and @graph.
        """
        vre_type: str = data["vre_type"]
        programming_language: str = constants.VRE_TYPE_TO_PROGRAMMING_LANGUAGE[vre_type]
        workflow: str = data["workflow"]
        runtime_platform: str | None = (
            str(data["runtime_platform"]) if data.get("runtime_platform") else None
        )
        files_data: list[dict[str, Any]] = data.get("files", [])

        lang_id = f"#{vre_type}-lang"
        now_iso = datetime.now(timezone.utc).isoformat()

        builder = RocrateBuilder(
            vre_type=vre_type,
            programming_language=programming_language,
            workflow_id=workflow,
            lang_id=lang_id,
            runtime_platform=runtime_platform,
            files_data=files_data,
            now_iso=now_iso,
        )

        return builder.build()
