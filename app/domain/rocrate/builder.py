from __future__ import annotations
from typing import Any
from .models import ParsedCrate
from .request_package import RequestPackage
from .validator import ValidationPipeline
import app.constants as constants


class RequestPackageBuilder:
    @classmethod
    def build(cls, crate: ParsedCrate) -> RequestPackage:
        ValidationPipeline.validate_basic(crate)
        return RequestPackage.from_parsed_crate(crate)

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
