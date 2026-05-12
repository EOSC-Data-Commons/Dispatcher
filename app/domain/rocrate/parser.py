from __future__ import annotations
from copy import deepcopy
from typing import Any
from rocrate.rocrate import ROCrate
from .models import ParsedCrate, Entity


class ROCrateParser:
    @classmethod
    def parse(cls, source: dict[str, Any]) -> ParsedCrate:
        source_copy = deepcopy(source)
        crate = ROCrate(source=source_copy)
        entities: dict[str, Entity] = {}

        for raw_entity in crate.get_entities():
            eid = raw_entity.get("@id", "")
            entities[eid] = Entity(
                id=eid,
                type=raw_entity.type,
                properties=cls._extract_properties(raw_entity),
            )

        root_id = crate.root_dataset.get("@id", "./") if crate.root_dataset else "./"

        return ParsedCrate(
            root_id=root_id,
            entities=entities,
            raw=source,
        )

    @classmethod
    def _extract_properties(cls, raw_entity: Any) -> dict[str, Any]:
        props = dict(raw_entity.properties())
        result: dict[str, Any] = {}
        for key, value in props.items():
            result[key] = cls._normalize_value(value)
        return result

    @classmethod
    def _normalize_value(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [cls._normalize_value(item) for item in value]
        if isinstance(value, dict) and "@id" in value and len(value) == 1:
            return value
        if isinstance(value, dict):
            return {k: cls._normalize_value(v) for k, v in value.items()}
        return value
