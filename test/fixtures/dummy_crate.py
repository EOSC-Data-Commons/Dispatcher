# test/fixtures/dummy_crate.py
from __future__ import annotations
from typing import List, Dict, Any

WORKFLOW_URL = "https://workflow.example.org/myworkflow.ga"

FILE_1 = {
    "name": "sample1.fastq",
    "encodingFormat": "application/fastq",
    "url": "https://data.example.org/sample1.fastq",
}
FILE_2 = {
    "name": "sample2.fastq",
    "encodingFormat": "application/fastq",
    "url": "https://data.example.org/sample2.fastq",
}


ONE_DATA_FILE = {
    "name": "onedata_file",
    "encodingFormat": "image/tiff",
    "onedata:onezoneDomain": "demo.onedata.org",
    "onedata:spaceId": "6e6b22d6f32b63db34fcfac53e52e233chd8ba",
    "onedata:fileId": "00000000007EADF3736861726547756964233964613065396530393037303130393062356433623965356632643832353138636830386464233665366232326436663332623633646233346663666163353365353265323333636864386261233437656434633633333638393264396361626239316435636430623161663436636830343438",
    "onedata:publicAccess": True,
}


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
    In‑memory representation of a RO‑Crate.  Only the attributes accessed
    by the VRE code are provided.
    """

    def __init__(
        self,
        main_entity: DummyEntity,
        other_entities: List[DummyEntity] | None = None,
        root_dataset: Dict[str, Any] | None = None,
    ):
        self.mainEntity = main_entity
        self._entities = other_entities or []
        # ``root_dataset`` is what ``VRE.setup_service`` looks at.
        self.root_dataset = root_dataset or {}
        self._custom_entities: Dict[str, Any] = {}
        self.name = getattr(main_entity, "name", None) if main_entity else None
        self.description = (
            getattr(main_entity, "description", None) if main_entity else None
        )
        self.metadata = DummyMetadata()

    def get_entities(self) -> List[DummyEntity]:
        return self._entities

    def get(self, entity_id: str, default: Any = None) -> Any:
        """Get a custom entity by ID."""
        return self._custom_entities.get(entity_id, default)

    def set_custom_entity(self, entity_id: str, entity: Any) -> None:
        """Set a custom entity for testing."""
        self._custom_entities[entity_id] = entity

    def delete(self, entity_id: str) -> None:
        """Delete a custom entity."""
        self._custom_entities.pop(entity_id, None)


class DummyMetadata:
    """Dummy metadata object for testing."""

    def generate(self) -> Dict[str, Any]:
        """Return dummy metadata."""
        return {"@context": "test", "@graph": []}
