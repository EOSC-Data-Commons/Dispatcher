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

        lang = main.get("programmingLanguage")
        if lang is None or (isinstance(lang, str) and lang == ""):
            raise VREConfigurationError(
                "Missing main entity programmingLanguage object"
            )

        lang_id = lang.get("identifier") if isinstance(lang, dict) else None
        if lang_id is None:
            raise VREConfigurationError(
                "Missing programmingLanguage identifier inside ROCrate's mainEntity"
            )
