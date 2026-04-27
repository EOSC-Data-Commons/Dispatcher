"""OSCAR VRE checker.

Validates ROCrates for OSCAR container deployment.
"""

from typing import Any, Dict, List, Tuple

from app.constants import OSCAR_PROGRAMMING_LANGUAGE

from ..package import RequestPackage
from .base import BaseChecker


class OSCARChecker(BaseChecker):
    """Validates ROCrates for OSCAR container deployment.

    OSCAR requires FDL JSON and optionally a shell script. This checker
    validates that these resources are properly referenced in the ROCrate.
    """

    @property
    def language_identifier(self) -> str:
        return OSCAR_PROGRAMMING_LANGUAGE

    def validate(self, package: RequestPackage) -> Tuple[bool, List[str]]:
        """Validate OSCAR ROCrate requirements."""
        errors: List[str] = []

        # Get workflow info
        try:
            workflow = package.get_workflow_info()
        except Exception as e:
            errors.append(f"Invalid workflow structure: {e}")
            return False, errors

        # Rule 1: Main entity must have name
        if not workflow.name:
            errors.append(
                "Main entity missing 'name' property (required for service name)"
            )

        # Rule 2: Language identifier must be OSCAR
        if workflow.language_identifier != OSCAR_PROGRAMMING_LANGUAGE:
            errors.append(
                f"Expected OSCAR language identifier, got '{workflow.language_identifier}'"
            )

        # Rule 3: Must have FDL JSON in hasPart
        fdl_found = any(p.encoding_format == "application/json" for p in workflow.parts)
        if not fdl_found:
            errors.append(
                "Missing FDL (Function Definition Language) JSON file in hasPart. "
                "Required encodingFormat: application/json"
            )

        # Rule 4: All parts must be accessible (have URLs)
        for part in workflow.parts:
            if part.file_type == "File" and not part.url:
                errors.append(f"File '{part.entity_id}' missing 'url' property")

        return len(errors) == 0, errors

    def get_requirements(self) -> Dict[str, Any]:
        return {
            "name": "OSCAR",
            "description": "OSCAR container deployment VRE",
            "version": "2.0.0",
            "required_entities": {
                "mainEntity": {
                    "type": "SoftwareApplication",
                    "required_properties": [
                        {"name": "name", "description": "Service name"},
                        {
                            "name": "programmingLanguage",
                            "description": f"Must have identifier '{OSCAR_PROGRAMMING_LANGUAGE}'",
                        },
                    ],
                },
                "hasPart": {
                    "type": "array",
                    "required_items": [
                        {
                            "encodingFormat": "application/json",
                            "description": "Function Definition Language (FDL) JSON file",
                        }
                    ],
                    "optional_items": [
                        {
                            "encodingFormat": "text/x-shellscript",
                            "description": "Optional shell script for service execution",
                        }
                    ],
                },
            },
            "vre_access_pattern": {
                "description": "OSCAR VRE uses specialized methods:",
                "examples": [
                    "fdl = package.get_fdl_config()      # Returns parsed FDL dict",
                    "script = package.get_script_content()  # Returns script string",
                ],
            },
        }
