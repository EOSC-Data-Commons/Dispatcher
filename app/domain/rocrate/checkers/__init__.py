"""ROCrate checkers registry and factory functions.

This module provides the central registry for VRE-specific checkers and
utility functions for accessing them.
"""

from typing import Dict, Type

from .base import BaseChecker

# Checker classes will be imported lazily to avoid circular imports
_CHECKER_REGISTRY: Dict[str, Type[BaseChecker]] = {}


def register_checker(
    language_identifier: str, checker_class: Type[BaseChecker]
) -> None:
    """Register a checker class for a language identifier.

    Args:
        language_identifier: The programming language identifier.
        checker_class: The checker class to register.
    """
    _CHECKER_REGISTRY[language_identifier] = checker_class


def get_checker(language_identifier: str) -> BaseChecker:
    """Get the appropriate checker for a language identifier.

    Args:
        language_identifier: The programming language identifier from the ROCrate.

    Returns:
        An instance of the appropriate checker class.

    Raises:
        ValueError: If no checker is registered for the given identifier.
    """
    checker_class = _CHECKER_REGISTRY.get(language_identifier)
    if checker_class is None:
        raise ValueError(
            f"No checker registered for language identifier: {language_identifier}"
        )
    return checker_class()


def get_checker_by_vre_type(vre_type: str) -> BaseChecker:
    """Get checker by VRE type name.

    Args:
        vre_type: The VRE type name (e.g., 'galaxy', 'jupyter').

    Returns:
        An instance of the appropriate checker class.

    Raises:
        ValueError: If the VRE type is not recognized.
    """
    # Map VRE type names to language identifiers
    vre_type_map = {
        "galaxy": "https://galaxyproject.org/",
        "jupyter": "https://jupyter.org",
        "binder": "https://jupyter.org/binder/",
        "oscar": "https://oscar.grycap.net/",
        "sciencemesh": "https://qa.cernbox.cern.ch",
        "scipion": "http://scipion.i2pc.es/",
    }
    lang_id = vre_type_map.get(vre_type.lower())
    if lang_id is None:
        raise ValueError(
            f"Unknown VRE type: {vre_type}. "
            f"Known types: {list(vre_type_map.keys())}"
        )
    return get_checker(lang_id)


def get_all_checkers() -> Dict[str, BaseChecker]:
    """Get all registered checkers.

    Returns:
        Dictionary mapping language identifiers to checker instances.
    """
    return {lang_id: cls() for lang_id, cls in _CHECKER_REGISTRY.items()}


def get_all_requirements() -> Dict[str, dict]:
    """Get requirements documentation for all VREs.

    Returns:
        Dictionary mapping language identifiers to requirements dictionaries.
    """
    return {
        lang_id: checker.get_requirements()
        for lang_id, checker in get_all_checkers().items()
    }
