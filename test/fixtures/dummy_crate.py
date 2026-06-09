# test/fixtures/dummy_crate.py
from __future__ import annotations
from typing import List, Dict, Any

WORKFLOW_URL = "https://workflow.example.org/myworkflow.ga"

FILE_1 = {
    "name": "sample1.fastq",
    "encodingFormat": "application/fastq",
    "@id": "https://data.example.org/sample1.fastq",
}
FILE_2 = {
    "name": "sample2.fastq",
    "encodingFormat": "application/fastq",
    "@id": "https://data.example.org/sample2.fastq",
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
    """Minimal entity that mimics a ROCrate entity for test fixtures."""

    def __init__(self, _type: str, **attrs: Any):
        self.type = _type
        self.id = attrs.pop("@id", "")
        self.properties = attrs

    def get(self, key: str, default: Any = None) -> Any:
        return self.properties.get(key, default)


class DummyCrate:
    """In‑memory representation of a crate for building RequestPackage fixtures."""

    def __init__(
        self,
        main_entity: DummyEntity,
        other_entities: List[DummyEntity] | None = None,
        root_dataset: Dict[str, Any] | None = None,
    ):
        self.main_entity = main_entity
        self.mainEntity = main_entity  # backward compat
        self._entities = other_entities or []
        self.root_dataset = root_dataset or {}

    def get_entities(self) -> List[DummyEntity]:
        return self._entities
