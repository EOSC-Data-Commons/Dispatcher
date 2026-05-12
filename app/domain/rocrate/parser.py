from __future__ import annotations
from typing import Any
from rocrate.rocrate import ROCrate
from .models import ParsedCrate, Entity


class ROCrateParser:
    @classmethod
    def parse(cls, source: dict[str, Any]) -> ParsedCrate:
        crate = ROCrate(source=source)
        entities: dict[str, Entity] = {}

        for raw_entity in crate.get_entities():
            eid = raw_entity.get("@id", "")
            entities[eid] = Entity(
                id=eid,
                type=raw_entity.type,
                properties=cls._resolve_properties(crate, raw_entity),
            )

        root_id = crate.root_dataset.get("@id", "./") if crate.root_dataset else "./"

        return ParsedCrate(
            root_id=root_id,
            entities=entities,
            raw=source,
        )

    @classmethod
    def _resolve_properties(cls, crate: ROCrate, raw_entity: Any) -> dict[str, Any]:
        props = dict(raw_entity.properties())
        resolved: dict[str, Any] = {}
        for key, value in props.items():
            resolved[key] = cls._resolve_value(crate, value)
        return resolved

    @classmethod
    def _resolve_value(cls, crate: ROCrate, value: Any) -> Any:
        if isinstance(value, dict) and "@id" in value and len(value) == 1:
            ref = crate.dereference(value["@id"])
            if ref is not None:
                return cls._resolve_value(crate, ref)
        if isinstance(value, list):
            return [cls._resolve_value(crate, item) for item in value]
        if isinstance(value, dict):
            return {k: cls._resolve_value(crate, v) for k, v in value.items()}
        return value
