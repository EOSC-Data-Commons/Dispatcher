"""DEPRECATED: This module has been moved to app.domain.rocrate.

Please update your imports:
    OLD: from app.vres.request_package import RequestPackage
    NEW: from app.domain.rocrate import RequestPackage

This module will be removed in a future version.
"""

import warnings
from typing import Any

# Issue deprecation warning
warnings.warn(
    "app.vres.request_package is deprecated. " "Use app.domain.rocrate instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export for backward compatibility
from app.domain.rocrate.package import RequestPackage
from app.domain.rocrate.value_objects import (
    FileInfo,
    WorkflowInfo,
    WorkflowPartInfo,
    ServiceConfig,
    CustomEntityInfo,
    CrateMetadata,
)

__all__ = [
    "RequestPackage",
    "FileInfo",
    "WorkflowInfo",
    "WorkflowPartInfo",
    "ServiceConfig",
    "CustomEntityInfo",
    "CrateMetadata",
]
