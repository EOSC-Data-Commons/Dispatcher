import json

from fastapi import Form
from pydantic import BaseModel, Field, HttpUrl, model_validator
from typing import List

from app.constants import VRE_TYPES


class MinimalFileInput(BaseModel):
    """Represents a file input for a minimal VRE request."""

    name: str
    url: HttpUrl | None = None
    encoding_format: str | None = None
    onedata_domain: str | None = None
    onedata_file_id: str | None = None


class MinimalVRERequest(BaseModel):
    """Represents a minimal VRE request payload.

    This model validates:
    - vre_type: Must be one of the supported VRE types
    - workflow: Required for Galaxy and OSCAR (URL or filename)
    - files: Optional list of file inputs
    - runtime_platform: Optional override for target service URL
    """

    vre_type: str = Field(..., description="VRE type identifier")
    workflow: str | None = Field(
        None,
        description="URL or filename of the workflow descriptor (required for Galaxy and OSCAR)",
    )
    files: List[MinimalFileInput] = Field(default_factory=list)
    runtime_platform: HttpUrl | None = Field(
        None, description="Optional override for the target service URL"
    )

    @model_validator(mode="after")
    def validate_vre_type(self):
        if self.vre_type not in VRE_TYPES:
            raise ValueError(
                f"vre_type must be one of {VRE_TYPES}, got '{self.vre_type}'"
            )
        return self

    @model_validator(mode="after")
    def validate_workflow_required(self):
        if self.workflow is None:
            raise ValueError("workflow is required")
        return self

    @model_validator(mode="after")
    def validate_workflow_in_files(self):
        if self.workflow is not None and not self.workflow.startswith(
            ("http://", "https://")
        ):
            file_names = {f.name for f in self.files}
            if self.workflow not in file_names:
                raise ValueError(
                    f"workflow '{self.workflow}' is a filename but was not found in files"
                )
        return self


def parse_minimal_vre_form(
    parsed_data: str = Form(..., description="JSON string of MinimalVRERequest")
) -> MinimalVRERequest:
    """Parse and validate MinimalVRERequest from a multipart form field."""
    data = json.loads(parsed_data)
    return MinimalVRERequest.model_validate(data)


__all__ = ["parse_minimal_vre_form", "MinimalVRERequest", "MinimalFileInput"]
