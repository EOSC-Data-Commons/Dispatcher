from __future__ import annotations
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
        workflow_url = str(data["workflow_url"]) if data.get("workflow_url") else None
        runtime_platform = (
            str(data["runtime_platform"]) if data.get("runtime_platform") else None
        )

        return RequestPackage.from_minimal(
            vre_type=vre_type,
            programming_language=programming_language,
            workflow_url=workflow_url,
            files_data=data.get("files", []),
            file_bytes_map=file_bytes_map,
            runtime_platform=runtime_platform,
        )


class RocrateBuilder:
    """Builds a complete ROCrate JSON dict from a minimal VRE request."""

    @staticmethod
    def build_from_minimal(data: dict[str, Any]) -> dict[str, Any]:
        """Convert a MinimalVRERequest dict into a complete ROCrate JSON dict."""
        vre_type: str = data["vre_type"]
        programming_language: str = constants.VRE_TYPE_TO_PROGRAMMING_LANGUAGE[vre_type]
        workflow: str = data["workflow"]
        runtime_platform: str | None = (
            str(data["runtime_platform"]) if data.get("runtime_platform") else None
        )
        files_data: list[dict[str, Any]] = data.get("files", [])

        lang_id = f"#{vre_type}-lang"
        now_iso = datetime.now(timezone.utc).isoformat()

        workflow_id: str = workflow

        graph: list[dict[str, Any]] = []

        # 1. ro-crate-metadata.json descriptor
        graph.append(
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "about": {"@id": "./"},
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
            }
        )

        # 2. Root Dataset
        root_has_part: list[dict[str, str]] = [{"@id": workflow_id}]
        for f in files_data:
            file_url = str(f["url"]) if f.get("url") else None
            file_id = file_url or f["name"]
            root_has_part.append({"@id": file_id})

        graph.append(
            {
                "@id": "./",
                "@type": "Dataset",
                "name": "placeholder",
                "description": "placeholder",
                "datePublished": now_iso,
                "license": {"@id": "https://spdx.org/licenses/GPL-3.0"},
                "creator": {"@id": "#author-dispatcher"},
                "mainEntity": {"@id": workflow_id},
                "hasPart": root_has_part,
            }
        )

        # 3. Workflow (mainEntity)
        workflow_entity: dict[str, Any] = {
            "@id": workflow_id,
            "@type": ["File", "SoftwareSourceCode", "ComputationalWorkflow"],
            "name": "placeholder",
            "programmingLanguage": {"@id": lang_id},
        }
        if runtime_platform:
            workflow_entity["runtimePlatform"] = runtime_platform
        graph.append(workflow_entity)

        # 4. Programming Language entity
        graph.append(
            {
                "@id": lang_id,
                "@type": "ComputerLanguage",
                "identifier": programming_language,
                "name": vre_type.capitalize(),
                "url": programming_language,
            }
        )

        # 5. File entities
        for f in files_data:
            file_url = str(f["url"]) if f.get("url") else None
            file_id = file_url or f["name"]
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
            graph.append(file_entity)

        # 6. Supporting entities
        graph.append(
            {
                "@id": "#author-dispatcher",
                "@type": "Person",
                "name": "Dispatcher System",
            }
        )
        graph.append(
            {
                "@id": "https://spdx.org/licenses/GPL-3.0",
                "@type": "CreativeWork",
                "name": "GNU General Public License v3.0",
                "alternateName": "GPL-3.0",
            }
        )

        return {
            "@context": "https://w3id.org/ro/crate/1.1/context",
            "@graph": graph,
        }
