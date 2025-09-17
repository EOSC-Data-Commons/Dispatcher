# test/fixtures/dummy_crate.py
from __future__ import annotations
from typing import List, Dict, Any


class DummyEntity:
    """
    Minimal entity that mimics the subset of a RO‑Crate Entity used by the VRE code.
    """

    def __init__(self, _type: str, **attrs: Any):
        self.type = _type
        self._attrs = attrs

    # The VRE code calls .properties() on File entities
    def properties(self) -> Dict[str, Any]:
        return self._attrs

    # The VRE code also accesses items like a dict (e.g. entity["url"])
    def __getitem__(self, key: str) -> Any:
        return self._attrs[key]

    # And sometimes uses .get()
    def get(self, key: str, default: Any = None) -> Any:
        return self._attrs.get(key, default)


class DummyCrate:
    """
    Very small in‑memory representation of a RO‑Crate.
    Only the attributes accessed by the VRE implementations are provided.
    """

    def __init__(
        self, main_entity: DummyEntity, other_entities: List[DummyEntity] | None = None
    ):
        self.mainEntity = main_entity
        self._entities = other_entities or []

    def get_entities(self) -> List[DummyEntity]:
        return self._entities
