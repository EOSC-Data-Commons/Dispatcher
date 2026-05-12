from __future__ import annotations
from app.exceptions import VREConfigurationError
from .models import ParsedCrate


class ValidationPipeline:
    @classmethod
    def validate_basic(cls, crate: ParsedCrate) -> None:
        main = crate.main_entity
        if main is None:
            raise VREConfigurationError("Missing mainEntity inside ROCrate")

        if isinstance(main.type, str) and main.type == "":
            raise VREConfigurationError("Missing main entity object")

        lang_ref = main.get("programmingLanguage")
        if lang_ref is None or (isinstance(lang_ref, str) and lang_ref == ""):
            raise VREConfigurationError(
                "Missing main entity programmingLanguage object"
            )

        lang = cls._resolve_ref(crate, lang_ref)
        if lang is None:
            raise VREConfigurationError("Cannot resolve programmingLanguage reference")

        lang_id = lang.get("identifier")
        if lang_id is None:
            raise VREConfigurationError(
                "Missing programmingLanguage identifier inside ROCrate's mainEntity"
            )

    @staticmethod
    def _resolve_ref(crate: ParsedCrate, ref: object) -> object:
        if isinstance(ref, dict) and "@id" in ref:
            return crate.get(ref["@id"])
        if isinstance(ref, str):
            return crate.get(ref)
        return ref
