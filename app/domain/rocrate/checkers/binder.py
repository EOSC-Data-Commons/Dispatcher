"""Binder VRE checker.

Validates ROCrates for Binder repository creation.
"""

from typing import Any, Dict, List, Tuple

from app.constants import BINDER_PROGRAMMING_LANGUAGE

from ..package import RequestPackage
from .base import BaseChecker


class BinderChecker(BaseChecker):
    """Validates ROCrates for Binder repository creation.

    Binder extracts files from ZIP body. ROCrate provides metadata only.
    """

    @property
    def language_identifier(self) -> str:
        return BINDER_PROGRAMMING_LANGUAGE

    def validate(self, package: RequestPackage) -> Tuple[bool, List[str]]:
        """Validate Binder ROCrate requirements."""
        errors: List[str] = []

        try:
            workflow = package.get_workflow_info()
        except Exception as e:
            errors.append(f"Invalid workflow structure: {e}")
            return False, errors

        # Rule: Language identifier must be Binder
        if workflow.language_identifier != BINDER_PROGRAMMING_LANGUAGE:
            errors.append(
                f"Expected Binder language identifier, got '{workflow.language_identifier}'"
            )

        return len(errors) == 0, errors

    def get_requirements(self) -> Dict[str, Any]:
        return {
            "name": "Binder",
            "description": "Binder repository creation VRE",
            "version": "2.0.0",
            "required_entities": {
                "mainEntity": {
                    "type": "SoftwareSourceCode",
                    "required_properties": [
                        {
                            "name": "programmingLanguage",
                            "description": f"Must have identifier '{BINDER_PROGRAMMING_LANGUAGE}'",
                        }
                    ],
                    "description": "Main repository entity",
                }
            },
            "notes": [
                "Repository files are extracted from ZIP file body",
                "ROCrate provides metadata about the repository",
            ],
        }
