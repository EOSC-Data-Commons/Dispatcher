"""ROCrateFactory - factory for creating ROCrate wrappers.

This module provides a factory pattern for creating RequestPackage instances,
centralizing ROCrate instantiation logic.
"""

import copy
import json
from typing import Any, Dict

from rocrate.rocrate import ROCrate

from .package import RequestPackage


class ROCrateFactory:
    """Factory class for creating RequestPackage instances.

    This factory centralizes all ROCrate instantiation logic, making it easy
    to change the underlying ROCrate library or add validation layers.

    Example:
        >>> package = ROCrateFactory.create_from_dict({"@graph": [...]})
        >>> package = ROCrateFactory.create_from_json('{"@graph": [...]}')
        >>> package = ROCrateFactory.create_from_file("ro-crate-metadata.json")
    """

    @staticmethod
    def create_from_dict(data: Dict[str, Any]) -> RequestPackage:
        """Create a RequestPackage from a dictionary.

        Args:
            data: Dictionary containing ROCrate metadata.

        Returns:
            A new RequestPackage instance wrapping the created ROCrate.
        """
        crate = ROCrate(source=copy.deepcopy(data))
        return RequestPackage(crate)

    @staticmethod
    def create_from_json(json_str: str) -> RequestPackage:
        """Create a RequestPackage from a JSON string.

        Args:
            json_str: JSON string containing ROCrate metadata.

        Returns:
            A new RequestPackage instance wrapping the created ROCrate.
        """
        data = json.loads(json_str)
        return ROCrateFactory.create_from_dict(data)

    @staticmethod
    def create_from_source(source: Any) -> RequestPackage:
        """Create a RequestPackage from any ROCrate source.

        Args:
            source: Any valid ROCrate source (dict, file path, URL, etc.)

        Returns:
            A new RequestPackage instance wrapping the created ROCrate.
        """
        crate = ROCrate(source=copy.deepcopy(source))
        return RequestPackage(crate)

    @staticmethod
    def create_from_file(file_path: str) -> RequestPackage:
        """Create a RequestPackage from a file path.

        Args:
            file_path: Path to the ROCrate metadata file.

        Returns:
            A new RequestPackage instance wrapping the created ROCrate.
        """
        crate = ROCrate(source=file_path)
        return RequestPackage(crate)
