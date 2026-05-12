from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Entity:
    id: str
    type: str | list[str]
    properties: dict[str, Any] = field(default_factory=dict, repr=False)

    def get(self, key: str, default: Any = None) -> Any:
        return self.properties.get(key, default)


@dataclass
class ParsedCrate:
    root_id: str
    entities: dict[str, Entity]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def root_dataset(self) -> Entity | None:
        return self.entities.get(self.root_id)

    @property
    def main_entity(self) -> Entity | None:
        root = self.root_dataset
        if root is None:
            return None
        main_ref = root.get("mainEntity")
        if main_ref is None:
            return None
        if isinstance(main_ref, dict):
            return self.entities.get(main_ref.get("@id", ""))
        if isinstance(main_ref, str):
            return self.entities.get(main_ref)
        eid = getattr(main_ref, "id", None) or main_ref.get("@id", "")
        return self.entities.get(eid)

    def get(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id)
