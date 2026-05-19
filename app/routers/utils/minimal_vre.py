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
    workflow: str | None = Field(
        None,
        description="URL or filename of the workflow descriptor (required for Galaxy and OSCAR)",
    )
    files: List[MinimalFileInput] = Field(default_factory=list)
    runtime_platform: HttpUrl | None = Field(
        None, description="Optional override for the target service URL"
    )

    @model_validator(mode="after")
    def validate_workflow_required(self):
        if self.vre_type in ("galaxy", "oscar") and self.workflow is None:
            raise ValueError(f"workflow is required for vre_type '{self.vre_type}'")
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
