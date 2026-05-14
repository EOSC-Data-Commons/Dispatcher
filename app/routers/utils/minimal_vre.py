from pydantic import BaseModel, Field, HttpUrl, model_validator
from typing import Literal, List


class MinimalFileInput(BaseModel):
    name: str
    url: HttpUrl | None = None
    encoding_format: str | None = None
    onedata_domain: str | None = None
    onedata_file_id: str | None = None


class MinimalVRERequest(BaseModel):
    vre_type: Literal[
        "galaxy",
        "oscar",
        "scipion",
        "binder",
        "jupyter",
    ] = Field(..., description="VRE type identifier")
    workflow_url: HttpUrl | None = Field(
        None,
        description="URL of the workflow descriptor (required for Galaxy and OSCAR)",
    )
    files: List[MinimalFileInput] = Field(default_factory=list)
    runtime_platform: HttpUrl | None = Field(
        None, description="Optional override for the target service URL"
    )

    @model_validator(mode="after")
    def validate_workflow_url_required(self):
        if self.vre_type in ("galaxy", "oscar") and self.workflow_url is None:
            raise ValueError(f"workflow_url is required for vre_type '{self.vre_type}'")
        return self
