"""RequestPackage - strict ROCrate abstraction with value objects.

This module provides high-level methods that return value objects instead of
raw ROCrate entities. VREs should never need to know about @id, @type,
or any other ROCrate-specific structure.

Example:
    >>> package = ROCrateFactory.create_from_dict(crate_data)
    >>> workflow = package.get_workflow_info()
    >>> print(workflow.url)  # Typed access, not dict["url"]
    >>> files = package.get_file_info_list()
    >>> for f in files:
    ...     print(f.name, f.url)  # All typed attributes
"""

import warnings
from typing import Any, Dict, List, Optional, Tuple

from app.exceptions import WorkflowURLError, VREConfigurationError

from .value_objects import (
    FileInfo,
    WorkflowInfo,
    WorkflowPartInfo,
    ServiceConfig,
    CustomEntityInfo,
    CrateMetadata,
)


class RequestPackage:
    """Strict ROCrate abstraction that hides all implementation details.

    This class provides high-level methods that return value objects instead of
    raw ROCrate entities. VREs should never need to know about @id, @type,
    or any other ROCrate-specific structure.
    """

    def __init__(self, crate: Any) -> None:
        """Initialize with a ROCrate instance (internal use only).

        Args:
            crate: The ROCrate instance to wrap. This is an internal detail;
                   VREs should use ROCrateFactory to create instances.
        """
        self._crate = crate
        self._main_entity_cache: Optional[Dict[str, Any]] = None
        self._root_dataset_cache: Optional[Dict[str, Any]] = None
        self._entities_cache: Optional[Dict[str, Dict[str, Any]]] = None
        self._cache_valid = False

    def _ensure_cache(self) -> None:
        """Build internal caches from the ROCrate."""
        if self._cache_valid:
            return

        # Build entity lookup dictionary
        self._entities_cache = {}
        graph = getattr(self._crate, "_graph", [])
        if not graph:
            # Try alternative access pattern via get_entities
            get_entities = getattr(self._crate, "get_entities", None)
            if get_entities:
                entities = get_entities()
                graph = [
                    e.properties() if hasattr(e, "properties") else dict(e)
                    for e in entities
                ]

        for entity in graph:
            entity_id = entity.get("@id", "")
            if entity_id:
                self._entities_cache[entity_id] = entity

        # Cache main entity as plain dict
        main_entity_ref = getattr(self._crate, "mainEntity", None)
        if main_entity_ref:
            if isinstance(main_entity_ref, dict):
                self._main_entity_cache = main_entity_ref
            else:
                # It's a reference object
                main_id = (
                    getattr(main_entity_ref, "get", lambda k, d=None: d)("@id", "")
                    if hasattr(main_entity_ref, "get")
                    else ""
                )
                self._main_entity_cache = self._entities_cache.get(main_id, {})

        # Cache root dataset
        root_dataset = getattr(self._crate, "root_dataset", None)
        if root_dataset:
            if isinstance(root_dataset, dict):
                self._root_dataset_cache = root_dataset
            else:
                self._root_dataset_cache = (
                    root_dataset.properties()
                    if hasattr(root_dataset, "properties")
                    else dict(root_dataset)
                )

        self._cache_valid = True

    def refresh(self) -> None:
        """Refresh internal caches."""
        self._cache_valid = False
        self._ensure_cache()

    # =========================================================================
    # HIGH-LEVEL METHODS RETURNING VALUE OBJECTS
    # =========================================================================

    def get_workflow_info(self) -> WorkflowInfo:
        """Get complete workflow information as a value object.

        This method resolves all references and returns a fully populated
        WorkflowInfo object. VREs don't need to dereference anything.

        Returns:
            WorkflowInfo with all resolved data.

        Raises:
            VREConfigurationError: If mainEntity is missing or invalid.
            WorkflowURLError: If workflow URL is missing.
        """
        self._ensure_cache()

        if not self._main_entity_cache:
            raise VREConfigurationError("Missing mainEntity in ROCrate")

        # Get workflow URL
        url = self._main_entity_cache.get("url")
        if not url:
            raise WorkflowURLError("Workflow missing 'url' property")

        # Get language information
        lang = self._main_entity_cache.get("programmingLanguage", {})
        lang_id = ""
        lang_name = None

        if isinstance(lang, dict):
            lang_id = lang.get("identifier", "")
            lang_name = lang.get("name")
        else:
            # Try to resolve reference
            if hasattr(lang, "get"):
                lang_id = lang.get("@id", "")
            lang_obj = self._entities_cache.get(lang_id, {})
            if lang_obj:
                # Try to get identifier from the referenced entity
                identifier = lang_obj.get("identifier", "")
                if isinstance(identifier, dict):
                    lang_id = identifier.get("@id", "")
                elif isinstance(identifier, str):
                    lang_id = identifier
                lang_name = lang_obj.get("name")

        # Get workflow parts (hasPart)
        parts: List[WorkflowPartInfo] = []
        has_part_refs = self._main_entity_cache.get("hasPart", [])

        for part_ref in has_part_refs:
            part_id = part_ref.get("@id", "") if isinstance(part_ref, dict) else ""
            part_entity = self._entities_cache.get(part_id, {})

            # Resolve actual type (may be array or reference)
            part_type = part_entity.get("@type", "File")
            if isinstance(part_type, list):
                part_type = part_type[0] if part_type else "File"

            parts.append(
                WorkflowPartInfo(
                    entity_id=part_id,
                    file_type=part_type,
                    encoding_format=part_entity.get("encodingFormat", ""),
                    url=part_entity.get("url", ""),
                    name=part_entity.get("name"),
                )
            )

        return WorkflowInfo(
            url=url,
            language_identifier=lang_id,
            language_name=lang_name,
            name=self._main_entity_cache.get("name"),
            description=self._main_entity_cache.get("description"),
            parts=parts,
        )

    def get_file_info_list(self) -> List[FileInfo]:
        """Get all file entities as value objects.

        Returns a list of FileInfo objects with all relevant data resolved.
        Onedata files are handled specially to construct the content URL.

        Returns:
            List of FileInfo objects for all File entities.
        """
        self._ensure_cache()

        result: List[FileInfo] = []
        if not self._entities_cache:
            return result

        for entity_id, entity in self._entities_cache.items():
            entity_type = entity.get("@type", "")
            # Handle both single type and array of types
            is_file = entity_type == "File" or (
                isinstance(entity_type, list) and "File" in entity_type
            )

            if is_file:
                # Check for Onedata metadata
                onedata_id = entity.get("onedata:fileId")
                onedata_domain = entity.get("onedata:onezoneDomain")

                if onedata_id and onedata_domain:
                    url = f"https://{onedata_domain}/api/v3/onezone/shares/data/{onedata_id}/content"
                else:
                    url = entity.get("url", "")

                result.append(
                    FileInfo(
                        name=entity.get("name", ""),
                        encoding_format=entity.get("encodingFormat", ""),
                        url=url,
                        entity_id=entity_id,
                        onedata_id=onedata_id,
                        onedata_domain=onedata_domain,
                    )
                )

        return result

    def get_workflow_parts_as_files(self) -> List[FileInfo]:
        """Get workflow hasPart items as file information.

        This is a convenience method for VREs that need the input files
        specified in the workflow's hasPart list.

        Returns:
            List of FileInfo objects for File-type parts.
        """
        workflow = self.get_workflow_info()
        result: List[FileInfo] = []

        for part in workflow.parts:
            if part.file_type == "File":
                result.append(
                    FileInfo(
                        name=part.name or part.entity_id,
                        encoding_format=part.encoding_format,
                        url=part.url,
                        entity_id=part.entity_id,
                    )
                )

        return result

    def get_service_config(self) -> Optional[ServiceConfig]:
        """Get runsOn service configuration as a value object.

        Returns:
            ServiceConfig if runsOn is present, None otherwise.
        """
        self._ensure_cache()

        if not self._root_dataset_cache:
            return None

        runs_on = self._root_dataset_cache.get("runsOn")
        if not runs_on:
            return None

        # Handle both dict and reference formats
        if isinstance(runs_on, dict):
            service_data = runs_on
        else:
            service_id = (
                getattr(runs_on, "get", lambda k, d=None: d)("@id", "")
                if hasattr(runs_on, "get")
                else ""
            )
            service_data = self._entities_cache.get(service_id, {})

        # Extract processor requirements
        proc_req = service_data.get("processorRequirements", [])
        if isinstance(proc_req, str):
            proc_req = [proc_req]
        elif proc_req is None:
            proc_req = []

        return ServiceConfig(
            url=service_data.get("url", ""),
            service_type=service_data.get("serviceType"),
            name=service_data.get("name"),
            memory_requirements=service_data.get("memoryRequirements"),
            processor_requirements=proc_req,
            storage_requirements=service_data.get("storageRequirements"),
        )

    def get_custom_entity_info(self, entity_id: str) -> Optional[CustomEntityInfo]:
        """Get a custom entity by ID as a value object.

        Args:
            entity_id: The entity ID (e.g., "#receiver", "#owner").

        Returns:
            CustomEntityInfo with resolved properties, or None if not found.
        """
        self._ensure_cache()

        entity = self._entities_cache.get(entity_id)
        if not entity:
            return None

        # Collect additional properties (excluding @ prefixed)
        additional_props = {k: v for k, v in entity.items() if not k.startswith("@")}

        return CustomEntityInfo(
            entity_id=entity_id,
            entity_type=str(entity.get("@type", "")),
            userid=entity.get("userid"),
            name=entity.get("name"),
            properties=additional_props,
        )

    def get_crate_metadata(self) -> CrateMetadata:
        """Get crate-level metadata as a value object.

        Returns:
            CrateMetadata with name, description, datePublished, license.
        """
        self._ensure_cache()

        return CrateMetadata(
            name=getattr(self._crate, "name"),
            description=getattr(self._crate, "description"),
            date_published=(
                self._root_dataset_cache.get("datePublished")
                if self._root_dataset_cache
                else None
            ),
            license=(
                self._root_dataset_cache.get("license")
                if self._root_dataset_cache
                else None
            ),
        )

    def get_fdl_config(self) -> Optional[Dict[str, Any]]:
        """Get Function Definition Language (FDL) configuration for OSCAR.

        This method fetches and parses the FDL JSON file referenced in the
        workflow's hasPart.

        Returns:
            Parsed FDL JSON as a dictionary, or None if not found.

        Raises:
            VREConfigurationError: If FDL fetch fails.
        """
        import requests

        workflow = self.get_workflow_info()

        for part in workflow.parts:
            if part.encoding_format == "application/json":
                try:
                    response = requests.get(part.url, timeout=30)
                    response.raise_for_status()
                    return response.json()
                except Exception as e:
                    raise VREConfigurationError(f"Failed to fetch FDL: {e}") from e

        return None

    def get_script_content(self) -> Optional[str]:
        """Get script content referenced in workflow hasPart.

        This method fetches shell script content from the URL specified
        in hasPart.

        Returns:
            Script content as a string, or None if not found.

        Raises:
            VREConfigurationError: If script fetch fails.
        """
        import requests

        workflow = self.get_workflow_info()

        for part in workflow.parts:
            if part.encoding_format == "text/x-shellscript":
                try:
                    response = requests.get(part.url, timeout=30)
                    response.raise_for_status()
                    return response.text
                except Exception as e:
                    raise VREConfigurationError(f"Failed to fetch script: {e}") from e

        return None

    def generate_metadata(self) -> Dict[str, Any]:
        """Generate the full ROCrate metadata as a dictionary.

        This is used when the complete ROCrate needs to be serialized,
        e.g., for ScienceMesh OCM shares.

        Returns:
            The generated metadata dictionary.
        """
        metadata_obj = getattr(self._crate, "metadata", None)
        if metadata_obj is None:
            return {}
        generate_method = getattr(metadata_obj, "generate", None)
        if generate_method is None:
            return {}
        return generate_method()

    # =========================================================================
    # DEPRECATED METHODS - WILL BE REMOVED IN NEXT VERSION
    # =========================================================================

    def get_workflow_url(self) -> str:
        """Deprecated: Use get_workflow_info().url instead."""
        warnings.warn(
            "get_workflow_url() is deprecated. Use get_workflow_info().url instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.get_workflow_info().url

    def get_workflow_entity(self) -> Any:
        """Deprecated: Use get_workflow_info() instead."""
        warnings.warn(
            "get_workflow_entity() is deprecated. Use get_workflow_info() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._ensure_cache()
        return self._main_entity_cache

    def get_workflow_parts(self) -> List[Any]:
        """Deprecated: Use get_workflow_parts_as_files() instead."""
        warnings.warn(
            "get_workflow_parts() is deprecated. Use get_workflow_parts_as_files() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return [p.__dict__ for p in self.get_workflow_parts_as_files()]

    def get_file_entities(self) -> List[Any]:
        """Deprecated: Use get_file_info_list() instead."""
        warnings.warn(
            "get_file_entities() is deprecated. Use get_file_info_list() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return [f.__dict__ for f in self.get_file_info_list()]

    def extract_file_info(self, files: List[Any]) -> List[Tuple[str, str, str]]:
        """Deprecated: Use get_file_info_list() instead."""
        warnings.warn(
            "extract_file_info() is deprecated. Use get_file_info_list() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return [(f.name, f.encoding_format, f.url) for f in self.get_file_info_list()]

    def get_runs_on_service(self) -> Optional[Dict[str, Any]]:
        """Deprecated: Use get_service_config() instead."""
        warnings.warn(
            "get_runs_on_service() is deprecated. Use get_service_config() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        config = self.get_service_config()
        return config.__dict__ if config else None

    def get_custom_entity(self, entity_id: str) -> Optional[Any]:
        """Deprecated: Use get_custom_entity_info() instead."""
        warnings.warn(
            "get_custom_entity() is deprecated. Use get_custom_entity_info() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        info = self.get_custom_entity_info(entity_id)
        return info.properties if info else None

    def get_crate_name(self) -> Optional[str]:
        """Deprecated: Use get_crate_metadata().name instead."""
        warnings.warn(
            "get_crate_name() is deprecated. Use get_crate_metadata().name instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.get_crate_metadata().name

    def get_crate_description(self) -> Optional[str]:
        """Deprecated: Use get_crate_metadata().description instead."""
        warnings.warn(
            "get_crate_description() is deprecated. "
            "Use get_crate_metadata().description instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.get_crate_metadata().description

    def dereference(self, entity_id: str) -> Optional[Any]:
        """Deprecated: This method will be removed. Request specific data instead."""
        warnings.warn(
            "dereference() is deprecated and will be removed. "
            "Use specific methods like get_custom_entity_info() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._ensure_cache()
        return self._entities_cache.get(entity_id)

    def get_main_entity_property(self, prop: str, default: Any = None) -> Any:
        """Deprecated: Use get_workflow_info() instead."""
        warnings.warn(
            "get_main_entity_property() is deprecated. Use get_workflow_info() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._ensure_cache()
        if self._main_entity_cache is None:
            return default
        return self._main_entity_cache.get(prop, default)
