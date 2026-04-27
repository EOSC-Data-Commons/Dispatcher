"""ROCrate domain layer - strict abstraction for ROCrate operations.

This module provides a clean abstraction layer for ROCrate operations,
separating ROCrate implementation details from VRE business logic.
All data is accessed through strictly-typed value objects.
"""

from .package import (
    RequestPackage,
    FileInfo,
    WorkflowInfo,
    WorkflowPartInfo,
    ServiceConfig,
    CustomEntityInfo,
    CrateMetadata,
)
from .factory import ROCrateFactory

__all__ = [
    "RequestPackage",
    "FileInfo",
    "WorkflowInfo",
    "WorkflowPartInfo",
    "ServiceConfig",
    "CustomEntityInfo",
    "CrateMetadata",
    "ROCrateFactory",
]
