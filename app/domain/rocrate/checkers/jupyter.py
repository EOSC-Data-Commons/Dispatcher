"""Jupyter VRE checker.

Validates ROCrates for Jupyter notebook execution.
"""

from typing import Any, Dict, List, Tuple

from app.constants import JUPYTER_PROGRAMMING_LANGUAGE

from ..package import RequestPackage
from .base import BaseChecker


class JupyterChecker(BaseChecker):
    """Validates ROCrates for Jupyter notebook execution.

    Jupyter extraction happens from ZIP body, not ROCrate. This checker
    performs minimal validation on the ROCrate structure.
    """

    @property
    def language_identifier(self) -> str:
        return JUPYTER_PROGRAMMING_LANGUAGE

    def validate(self, package: RequestPackage) -> Tuple[bool, List[str]]:
        """Validate Jupyter ROCrate requirements."""
        errors: List[str] = []

        try:
            workflow = package.get_workflow_info()
        except Exception as e:
            # Jupyter may not have URL, notebook comes from ZIP
            pass

        # Rule: Language identifier must be Jupyter
        lang_id = ""
        try:
            workflow = package.get_workflow_info()
            lang_id = workflow.language_identifier
        except Exception:
            pass

        if lang_id and lang_id != JUPYTER_PROGRAMMING_LANGUAGE:
            errors.append(f"Expected Jupyter language identifier, got '{lang_id}'")

        return len(errors) == 0, errors

    def get_requirements(self) -> Dict[str, Any]:
        return {
            "name": "Jupyter",
            "description": "Jupyter notebook execution VRE",
            "version": "2.0.0",
            "required_entities": {
                "mainEntity": {
                    "type": "Notebook | SoftwareSourceCode",
                    "required_properties": [
                        {
                            "name": "programmingLanguage",
                            "description": f"Must have identifier '{JUPYTER_PROGRAMMING_LANGUAGE}'",
                        }
                    ],
                    "description": "Main notebook entity",
                }
            },
            "notes": [
                "Notebook content is extracted from ZIP file body, not ROCrate",
                "ROCrate serves as metadata container only",
                "VRE accesses metadata through RequestPackage value objects",
            ],
            "vre_access_pattern": {
                "description": "Jupyter VRE primarily uses ZIP body:",
                "examples": [
                    "metadata = package.get_crate_metadata()",
                    "workflow = package.get_workflow_info()  # For language check only",
                ],
            },
        }
