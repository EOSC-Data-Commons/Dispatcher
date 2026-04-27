"""ScienceMesh VRE checker.

Validates ROCrates for ScienceMesh OCM sharing.
"""

from typing import Any, Dict, List, Tuple

from app.constants import SCIENCEMESH_PROGRAMMING_LANGUAGE

from ..package import RequestPackage
from .base import BaseChecker


class ScienceMeshChecker(BaseChecker):
    """Validates ROCrates for ScienceMesh OCM sharing.

    ScienceMesh requires specific custom entities (#receiver, #owner, #sender, #destination)
    with particular properties. This checker validates their presence and structure.
    """

    @property
    def language_identifier(self) -> str:
        return SCIENCEMESH_PROGRAMMING_LANGUAGE

    def _validate_custom_entity(
        self, package: RequestPackage, entity_id: str, required_props: List[str]
    ) -> List[str]:
        """Validate a custom entity has required properties."""
        errors: List[str] = []
        info = package.get_custom_entity_info(entity_id)

        if not info:
            errors.append(f"Missing required entity: {entity_id}")
            return errors

        for prop in required_props:
            if prop == "userid" and not info.userid:
                errors.append(f"Entity {entity_id} missing required property 'userid'")
            elif prop == "name" and not info.name:
                errors.append(f"Entity {entity_id} missing required property 'name'")
            elif prop == "url" and not info.properties.get("url"):
                errors.append(f"Entity {entity_id} missing required property 'url'")

        return errors

    def validate(self, package: RequestPackage) -> Tuple[bool, List[str]]:
        """Validate ScienceMesh ROCrate requirements."""
        errors: List[str] = []

        # Rule 1: Validate required custom entities
        receiver_errors = self._validate_custom_entity(package, "#receiver", ["userid"])
        owner_errors = self._validate_custom_entity(package, "#owner", ["userid"])
        sender_errors = self._validate_custom_entity(
            package, "#sender", ["userid", "name"]
        )
        destination_errors = self._validate_custom_entity(
            package, "#destination", ["url"]
        )

        errors.extend(receiver_errors)
        errors.extend(owner_errors)
        errors.extend(sender_errors)
        errors.extend(destination_errors)

        # Rule 2: Crate must have name and description for share notification
        metadata = package.get_crate_metadata()
        if not metadata.name:
            errors.append(
                "Crate missing 'name' property (required for share notification)"
            )
        if not metadata.description:
            errors.append(
                "Crate missing 'description' property (required for share notification)"
            )

        return len(errors) == 0, errors

    def get_requirements(self) -> Dict[str, Any]:
        return {
            "name": "ScienceMesh",
            "description": "ScienceMesh OCM sharing VRE",
            "version": "2.0.0",
            "required_entities": {
                "#receiver": {
                    "type": "Person | Organization",
                    "required_properties": [
                        {"name": "userid", "description": "Recipient user ID"}
                    ],
                    "description": "The recipient of the share",
                },
                "#owner": {
                    "type": "Person | Organization",
                    "required_properties": [
                        {"name": "userid", "description": "Owner user ID"}
                    ],
                    "description": "The owner of the shared resource",
                },
                "#sender": {
                    "type": "Person",
                    "required_properties": [
                        {"name": "userid", "description": "Sender user ID"},
                        {"name": "name", "description": "Sender display name"},
                    ],
                    "description": "The sender initiating the share",
                },
                "#destination": {
                    "type": "Service",
                    "required_properties": [
                        {"name": "url", "description": "Target service URL"}
                    ],
                    "description": "Target service URL for the share",
                },
            },
            "crate_requirements": {
                "name": "Required - displayed in share notification",
                "description": "Required - displayed in share notification",
            },
            "vre_access_pattern": {
                "description": "ScienceMesh VRE uses typed entity info:",
                "examples": [
                    "receiver = package.get_custom_entity_info('#receiver')",
                    "print(receiver.userid)  # Typed attribute access",
                    "metadata = package.get_crate_metadata()",
                    "print(metadata.name)  # Crate name",
                ],
            },
        }
