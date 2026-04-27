"""ROCrate checkers registry and factory functions.

This module provides the central registry for VRE-specific checkers and
utility functions for accessing them.
"""

from typing import Dict, Type

from app.constants import (
    GALAXY_PROGRAMMING_LANGUAGE,
    JUPYTER_PROGRAMMING_LANGUAGE,
    BINDER_PROGRAMMING_LANGUAGE,
    OSCAR_PROGRAMMING_LANGUAGE,
    SCIENCEMESH_PROGRAMMING_LANGUAGE,
    SCIPION_PROGRAMMING_LANGUAGE,
)

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
    # Map VRE type names to language identifiers using constants
    vre_type_map = {
        "galaxy": GALAXY_PROGRAMMING_LANGUAGE,
        "jupyter": JUPYTER_PROGRAMMING_LANGUAGE,
        "binder": BINDER_PROGRAMMING_LANGUAGE,
        "oscar": OSCAR_PROGRAMMING_LANGUAGE,
        "sciencemesh": SCIENCEMESH_PROGRAMMING_LANGUAGE,
        "scipion": SCIPION_PROGRAMMING_LANGUAGE,
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


# Lazy imports of checker implementations to avoid circular dependencies
def _load_checkers() -> None:
    """Lazy load all checker implementations and register them."""
    from .galaxy import GalaxyChecker
    from .jupyter import JupyterChecker
    from .oscar import OSCARChecker
    from .binder import BinderChecker
    from .sciencemesh import ScienceMeshChecker
    from .scipion import ScipionChecker

    register_checker(GALAXY_PROGRAMMING_LANGUAGE, GalaxyChecker)
    register_checker(JUPYTER_PROGRAMMING_LANGUAGE, JupyterChecker)
    register_checker(BINDER_PROGRAMMING_LANGUAGE, BinderChecker)
    register_checker(OSCAR_PROGRAMMING_LANGUAGE, OSCARChecker)
    register_checker(SCIENCEMESH_PROGRAMMING_LANGUAGE, ScienceMeshChecker)
    register_checker(SCIPION_PROGRAMMING_LANGUAGE, ScipionChecker)


# Pre-register checkers on module import
_load_checkers()
