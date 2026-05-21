from __future__ import annotations
from app.exceptions import VREConfigurationError
from .models import ParsedCrate


def _validate_main_entity(crate: ParsedCrate) -> None:
    """Validate that the crate has a valid mainEntity.

    Raises:
        VREConfigurationError: If mainEntity is missing or invalid.
    """
    main = crate.main_entity
    if main is None:
        raise VREConfigurationError("Missing mainEntity inside ROCrate")

    if isinstance(main.type, str) and main.type == "":
        raise VREConfigurationError("Missing main entity object")


def _validate_programming_language(
    crate: ParsedCrate,
    main: object,
) -> None:
    """Validate that the main entity has a valid programmingLanguage.

    Raises:
        VREConfigurationError: If programmingLanguage is missing or invalid.
    """
    lang_ref = main.get("programmingLanguage")
    if lang_ref is None or (isinstance(lang_ref, str) and lang_ref == ""):
        raise VREConfigurationError("Missing main entity programmingLanguage object")

    lang = _resolve_ref(crate, lang_ref)
    if lang is None:
        raise VREConfigurationError("Cannot resolve programmingLanguage reference")

    lang_id = lang.get("identifier")
    if lang_id is None:
        raise VREConfigurationError(
            "Missing programmingLanguage identifier inside ROCrate's mainEntity"
        )


def _resolve_ref(crate: ParsedCrate, ref: object) -> object:
    """Resolve a reference to an entity in the crate.

    Args:
        crate: The parsed crate containing entities.
        ref: The reference to resolve (can be a string @id, dict with @id, or direct entity).

    Returns:
        The resolved Entity or None if not found.
    """
    if isinstance(ref, dict) and "@id" in ref:
        return crate.get(ref["@id"])
    if isinstance(ref, str):
        return crate.get(ref)
    return ref


class ValidationPipeline:
    """Pipeline for validating ROCrate structures."""

    @classmethod
    def validate_basic(cls, crate: ParsedCrate) -> None:
        """Perform basic validation of a parsed ROCrate.

        This validates:
        - mainEntity exists and is valid
        - programmingLanguage is defined and resolvable
        - programmingLanguage has an identifier

        Args:
            crate: The parsed crate to validate.

        Raises:
            VREConfigurationError: If any validation step fails.
        """
        _validate_main_entity(crate)
        _validate_programming_language(crate, crate.main_entity)

    @classmethod
    def validate_workflow_required_fields(cls, crate: ParsedCrate) -> None:
        """Validate that workflow-related required fields are present.

        This can be extended to check for additional workflow-specific requirements.

        Args:
            crate: The parsed crate to validate.

        Raises:
            VREConfigurationError: If required workflow fields are missing.
        """
        main = crate.main_entity
        if main is None:
            return  # Already caught by validate_basic

        # Check for common workflow properties that might be required
        # This is a placeholder for future extensions
        pass
