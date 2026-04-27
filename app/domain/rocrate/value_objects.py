"""Value objects for ROCrate data access.

This module defines strictly-typed data classes that represent
ROCrate entities. VREs should use these value objects instead of
accessing raw ROCrate entity dictionaries.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FileInfo:
    """Value object representing file information extracted from ROCrate.

    Attributes:
        name: The name of the file.
        encoding_format: The MIME type of the file (e.g., "text/plain").
        url: The URL where the file content can be accessed.
        entity_id: The @id of the entity in the ROCrate (e.g., "#file1").
        onedata_id: Onedata file ID if this is an Onedata file.
        onedata_domain: Onedata domain if this is an Onedata file.
    """

    name: str
    encoding_format: str
    url: str
    entity_id: Optional[str] = None
    onedata_id: Optional[str] = None
    onedata_domain: Optional[str] = None


@dataclass
class WorkflowPartInfo:
    """Value object representing a workflow part (hasPart item).

    Attributes:
        entity_id: The @id of the part entity.
        file_type: The resolved type after dereferencing (e.g., "File").
        encoding_format: The MIME type of the part.
        url: The URL where the part content can be accessed.
        name: Optional name of the part.
    """

    entity_id: str
    file_type: str
    encoding_format: str
    url: str
    name: Optional[str] = None


@dataclass
class WorkflowInfo:
    """Value object representing workflow metadata.

    Attributes:
        url: The workflow URL (e.g., TRS endpoint).
        language_identifier: The programming language identifier
            (e.g., "https://galaxyproject.org/").
        language_name: Human-readable language name.
        name: Optional workflow name.
        description: Optional workflow description.
        parts: List of workflow parts from hasPart.
    """

    url: str
    language_identifier: str
    language_name: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    parts: List[WorkflowPartInfo] = field(default_factory=list)


@dataclass
class ServiceConfig:
    """Value object representing service configuration (runsOn).

    Attributes:
        url: The service URL.
        service_type: Optional service type (e.g., "InfrastructureManager").
        name: Optional service name.
        memory_requirements: Optional memory requirement string.
        processor_requirements: List of processor requirements.
        storage_requirements: Optional storage requirement string.
    """

    url: str
    service_type: Optional[str] = None
    name: Optional[str] = None
    memory_requirements: Optional[str] = None
    processor_requirements: List[str] = field(default_factory=list)
    storage_requirements: Optional[str] = None


@dataclass
class CustomEntityInfo:
    """Value object for custom entities like #receiver, #owner, etc.

    Attributes:
        entity_id: The entity @id (e.g., "#receiver").
        entity_type: The @type of the entity (e.g., "Person").
        userid: The userid property if present.
        name: The name property if present.
        properties: Additional properties not covered by typed fields.
    """

    entity_id: str
    entity_type: str
    userid: Optional[str] = None
    name: Optional[str] = None
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CrateMetadata:
    """Value object for crate-level metadata.

    Attributes:
        name: The crate name.
        description: The crate description.
        date_published: Publication date string.
        license: License information.
    """

    name: Optional[str] = None
    description: Optional[str] = None
    date_published: Optional[str] = None
    license: Optional[str] = None
