"""Request Package wrapper for RoCrate operations.

This module provides a streamlined interface to access RoCrate data,
encapsulating implementation details and providing type-safe access methods.
"""

from typing import Any, Dict, List, Optional
from app.exceptions import WorkflowURLError, VREConfigurationError


class RequestPackage:
    """Wrapper class for RoCrate that provides streamlined access to crate data.

    This class encapsulates all RoCrate access patterns used across VRE implementations,
    providing a consistent and testable interface while hiding the underlying
    RoCrate library details.
    """

    def __init__(self, crate: Any) -> None:
        """Initialize the RequestPackage with a RoCrate instance.

        Args:
            crate: The RoCrate instance to wrap.
        """
        self._crate = crate

    @property
    def _main_entity(self) -> Any:
        """Get the main entity from the crate (cached for performance)."""
        if not hasattr(self, "_main_entity_cache"):
            self._main_entity_cache = self._get_main_entity_raw()
        return self._main_entity_cache

    @_main_entity.setter
    def _main_entity(self, value: Any) -> None:
        """Set the main entity cache."""
        self._main_entity_cache = value

    def _get_main_entity_raw(self) -> Any:
        """Get the raw main entity from the crate."""
        return self._crate.mainEntity

    def refresh(self) -> None:
        """Refresh the cached main entity. Call this after changing the underlying crate."""
        self._main_entity_cache = self._get_main_entity_raw()

    def get_workflow_url(self) -> str:
        """Extract workflow URL from the main entity.

        Returns:
            The workflow URL as a string.

        Raises:
            WorkflowURLError: If the workflow URL is missing.
        """
        url = self._main_entity.get("url") if self._main_entity else None
        if url is None:
            raise WorkflowURLError("Missing url in workflow entity")
        return url

    def get_workflow_entity(self) -> Any:
        """Get the main workflow entity.

        Returns:
            The main entity object.
        """
        return self._main_entity

    def get_workflow_parts(self) -> List[Any]:
        """Get the hasPart list from the main workflow entity.

        Returns:
            List of workflow part entities, or empty list if not present.
        """
        if self._main_entity is None:
            return []
        return self._main_entity.get("hasPart", [])

    def get_file_entities(self) -> List[Any]:
        """Get all entities of type File.

        Returns:
            List of file entities.
        """
        return [
            e for e in self._crate.get_entities() if getattr(e, "type", None) == "File"
        ]

    def extract_file_info(self, files: List[Any]) -> List[tuple[str, str, str]]:
        """Extract file information from file entities.

        For each file entity, extracts name, type (encodingFormat), and location.
        The location is determined based on whether the file is an Onedata file
        or a standard URL file.

        Args:
            files: List of file entities to process.

        Returns:
            List of tuples (name, type, location) for each file.
        """
        result = []
        for f in files:
            properties = f.properties()
            name = properties.get("name", "")
            file_type = properties.get("encodingFormat", "")

            if self._is_onedata_file(properties):
                location = self._get_onedata_location(properties)
            else:
                location = f.get("url", "")

            result.append((name, file_type, location))
        return result

    def _is_onedata_file(self, properties: Dict[str, Any]) -> bool:
        """Check if the file is an Onedata file.

        Args:
            properties: The file properties dict.

        Returns:
            True if the file has Onedata metadata, False otherwise.
        """
        return "onedata:fileId" in properties

    def _get_onedata_location(self, properties: Dict[str, Any]) -> str:
        """Build the Onedata file content URL.

        Args:
            properties: The file properties dict containing Onedata metadata.

        Returns:
            The Onedata file content URL.
        """
        oz_domain = properties.get("onedata:onezoneDomain", "")
        file_id = properties.get("onedata:fileId", "")
        return f"https://{oz_domain}/api/v3/onezone/shares/data/{file_id}/content"

    def get_runs_on_service(self) -> Optional[Dict[str, Any]]:
        """Get the runsOn service configuration from the root dataset.

        Returns:
            The runsOn configuration dict or None if not present.
        """
        root_dataset = getattr(self._crate, "root_dataset", {})
        return root_dataset.get("runsOn")

    def get_custom_entity(self, entity_id: str) -> Optional[Any]:
        """Get a custom entity by its ID (e.g., #receiver, #owner).

        Args:
            entity_id: The entity ID to look up (e.g., "#receiver").

        Returns:
            The entity if found, None otherwise.
        """
        return self._crate.get(entity_id)

    def get_crate_name(self) -> Optional[str]:
        """Get the name of the crate.

        Returns:
            The crate name or None if not present.
        """
        return getattr(self._crate, "name", None)

    def get_crate_description(self) -> Optional[str]:
        """Get the description of the crate.

        Returns:
            The crate description or None if not present.
        """
        return getattr(self._crate, "description", None)

    def dereference(self, entity_id: str) -> Optional[Any]:
        """Dereference an entity by its @id.

        Args:
            entity_id: The entity ID to dereference.

        Returns:
            The dereferenced entity or None if not found.
        """
        return self._crate.dereference(entity_id)

    def get_main_entity_property(self, prop: str, default: Any = None) -> Any:
        """Get a property from the main entity.

        Args:
            prop: The property name to retrieve.
            default: Default value if property is not present.

        Returns:
            The property value or default.
        """
        if self._main_entity is None:
            return default
        return self._main_entity.get(prop, default)

    def generate_metadata(self) -> Dict[str, Any]:
        """Generate the metadata JSON representation of the crate.

        Returns:
            The generated metadata as a dictionary.
        """
        return self._crate.metadata.generate()

    @property
    def main_entity(self) -> Any:
        """Property accessor for main entity (for backward compatibility)."""
        return self._main_entity
