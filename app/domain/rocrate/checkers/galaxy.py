"""Galaxy VRE checker.

Validates ROCrates for Galaxy workflow execution.
"""

from typing import Any, Dict, List, Tuple

from app.constants import GALAXY_PROGRAMMING_LANGUAGE

from ..package import RequestPackage
from .base import BaseChecker


class GalaxyChecker(BaseChecker):
    """Validates ROCrates for Galaxy workflow execution."""

    @property
    def language_identifier(self) -> str:
        return GALAXY_PROGRAMMING_LANGUAGE

    def validate(self, package: RequestPackage) -> Tuple[bool, List[str]]:
        """Validate Galaxy ROCrate requirements."""
        errors: List[str] = []

        # Try to get workflow info - this will fail if structure is invalid
        try:
            workflow = package.get_workflow_info()
        except Exception as e:
            errors.append(f"Invalid workflow structure: {e}")
            return False, errors

        # Rule 1: Workflow URL must be valid
        if not workflow.url:
            errors.append("Workflow missing 'url' property")

        # Rule 2: Language identifier must be Galaxy
        if workflow.language_identifier != GALAXY_PROGRAMMING_LANGUAGE:
            errors.append(
                f"Expected Galaxy language identifier '{GALAXY_PROGRAMMING_LANGUAGE}', "
                f"got '{workflow.language_identifier}'"
            )

        # Rule 3: HasPart must contain at least one file
        if not workflow.parts:
            errors.append("Workflow missing 'hasPart' with input files")
        else:
            file_parts = [p for p in workflow.parts if p.file_type == "File"]
            if not file_parts:
                errors.append("No File-type entities found in hasPart")

            # Rule 4: Each file part must have a URL
            for part in file_parts:
                if not part.url:
                    errors.append(f"File '{part.entity_id}' missing 'url' property")

        return len(errors) == 0, errors

    def get_requirements(self) -> Dict[str, Any]:
        return {
            "name": "Galaxy",
            "description": "Galaxy workflow execution VRE",
            "version": "2.0.0",
            "required_entities": {
                "mainEntity": {
                    "type": "HowTo | SoftwareApplication",
                    "required_properties": [
                        {"name": "url", "description": "Workflow URL (TRS format)"},
                        {
                            "name": "programmingLanguage",
                            "description": f"Must have identifier '{GALAXY_PROGRAMMING_LANGUAGE}'",
                        },
                    ],
                    "description": "Main workflow entity pointing to a Galaxy workflow",
                },
                "hasPart": {
                    "type": "array",
                    "min_items": 1,
                    "item_requirements": [
                        {
                            "type": "File",
                            "required_properties": [
                                {"name": "@id", "description": "Entity identifier"},
                                {"name": "url", "description": "File content URL"},
                            ],
                        }
                    ],
                    "description": "List of input files for the workflow",
                },
            },
            "optional_entities": {
                "runsOn": {
                    "description": "Service configuration specifying the Galaxy instance URL"
                }
            },
            "vre_access_pattern": {
                "description": "VREs access data through RequestPackage value objects:",
                "examples": [
                    "workflow = package.get_workflow_info()  # Returns WorkflowInfo",
                    "files = package.get_file_info_list()   # Returns List[FileInfo]",
                    "service = package.get_service_config() # Returns ServiceConfig",
                ],
            },
        }
