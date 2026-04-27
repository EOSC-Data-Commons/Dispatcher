"""Base classes for VRE-specific ROCrate checkers.

This module defines the abstract base class and protocols for implementing
VRE-specific validators.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple

from ..package import RequestPackage


class BaseChecker(ABC):
    """Abstract base class for VRE-specific ROCrate validators.

    All VRE checkers should inherit from this class and implement
    the required methods.

    Example:
        >>> class MyChecker(BaseChecker):
        ...     @property
        ...     def language_identifier(self) -> str:
        ...         return "https://example.org/"
        ...
        ...     def validate(self, package: RequestPackage) -> Tuple[bool, List[str]]:
        ...         # Implement validation logic
        ...         return True, []
        ...
        ...     def get_requirements(self) -> dict:
        ...         return {"name": "MyVRE", ...}
    """

    @property
    @abstractmethod
    def language_identifier(self) -> str:
        """Return the programming language identifier for this VRE.

        This is used to map ROCrates to their appropriate checkers.

        Returns:
            The language identifier string (e.g., "https://galaxyproject.org/")
        """
        pass

    @abstractmethod
    def validate(self, package: RequestPackage) -> Tuple[bool, List[str]]:
        """Validate the ROCrate for this VRE.

        Args:
            package: The RequestPackage wrapping the ROCrate to validate.

        Returns:
            Tuple of (is_valid, list_of_error_messages).
            - is_valid: True if the ROCrate passes all validation checks
            - list_of_error_messages: Empty list if valid, otherwise contains
              human-readable error messages describing validation failures.
        """
        pass

    @abstractmethod
    def get_requirements(self) -> dict:
        """Return a dictionary describing what this VRE requires in the ROCrate.

        This method returns structured documentation that can be exposed via API
        to help frontend developers understand what ROCrate structure is expected.

        Returns:
            Dictionary containing:
            - name: Human-readable VRE name
            - description: Brief description of the VRE
            - required_entities: Dict of required entities with their specifications
            - optional_entities: Dict of optional entities with their specifications
            - example_metadata: Optional example ROCrate metadata
        """
        pass
