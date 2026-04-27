"""Scipion VRE checker.

Validates ROCrates for Scipion workflow execution.
"""

from typing import Any, Dict, List, Tuple

from app.constants import SCIPION_PROGRAMMING_LANGUAGE

from ..package import RequestPackage
from .base import BaseChecker


class ScipionChecker(BaseChecker):
    """Validates ROCrates for Scipion workflow execution."""

    @property
    def language_identifier(self) -> str:
        return SCIPION_PROGRAMMING_LANGUAGE

    def validate(self, package: RequestPackage) -> Tuple[bool, List[str]]:
        """Validate Scipion ROCrate requirements."""
        errors: List[str] = []

        try:
            workflow = package.get_workflow_info()
        except Exception as e:
            errors.append(f"Invalid workflow structure: {e}")
            return False, errors

        # Rule: Language identifier must be Scipion
        if workflow.language_identifier != SCIPION_PROGRAMMING_LANGUAGE:
            errors.append(
                f"Expected Scipion language identifier, got '{workflow.language_identifier}'"
            )

        return len(errors) == 0, errors

    def get_requirements(self) -> Dict[str, Any]:
        return {
            "name": "Scipion",
            "description": "Scipion workflow execution VRE",
            "version": "2.0.0",
            "required_entities": {
                "mainEntity": {
                    "type": "SoftwareApplication",
                    "required_properties": [
                        {
                            "name": "programmingLanguage",
                            "description": f"Must have identifier '{SCIPION_PROGRAMMING_LANGUAGE}'",
                        }
                    ],
                    "description": "Main workflow entity",
                }
            },
        }
