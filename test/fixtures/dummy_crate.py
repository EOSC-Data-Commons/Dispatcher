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
    Minimal entity that mimics the subset of a RO-Crate Entity used by RequestPackage.

    Entities must have @id and @type properties, and all other attributes are stored
    as additional properties accessible via dict-style access and .properties().
    """

    def __init__(self, _id: str = "", _type: str = "", **attrs: Any):
        self._id = _id
        self.type = _type
        self._attrs = attrs

    @property
    def id(self) -> str:
        return self._id

    # Support @id access pattern
    def get(self, key: str, default: Any = None) -> Any:
        if key == "@id":
            return self._id
        if key == "@type":
            return self.type
        return self._attrs.get(key, default)

    # Support dict-style access
    def __getitem__(self, key: str) -> Any:
        if key == "@id":
            return self._id
        if key == "@type":
            return self.type
        return self._attrs[key]

    # Return full entity as dict for graph serialization
    def properties(self) -> Dict[str, Any]:
        result = {"@id": self._id, "@type": self.type}
        result.update(self._attrs)
        return result


class DummyMetadata:
    """Dummy metadata object for testing."""

    def generate(self) -> Dict[str, Any]:
        """Return dummy metadata."""
        return {"@context": "test", "@graph": []}


class DummyCrate:
    """
    In-memory representation of a RO-Crate compatible with RequestPackage.

    Provides:
    - _graph: List of entity dicts with @id and @type
    - mainEntity: Reference or direct entity
    - root_dataset: Root dataset entity
    - name/description: Crate-level metadata
    - metadata: Metadata object with generate() method

    Note: To create a valid ROCrate for ROCrateFactory.create_from_dict(),
    use get_rocrate_dict() which includes @context and proper structure.
    """

    def __init__(
        self,
        main_entity: DummyEntity | None = None,
        other_entities: List[DummyEntity] | None = None,
        root_dataset: Dict[str, Any] | None = None,
        language_entity: DummyEntity | None = None,
        name: str | None = None,
        description: str | None = None,
    ):
        # Build list of all entities including root dataset and metadata descriptor
        all_entities: List[DummyEntity] = []

        # Create root dataset entity (required by RO-Crate spec)
        root_id = "./"
        root_props = {"@id": root_id, "@type": "Dataset"}
        if root_dataset:
            root_props.update(root_dataset)

        # Add mainEntity reference to root if present
        if main_entity:
            root_props["mainEntity"] = {"@id": main_entity.id}
            root_props["hasPart"] = [{"@id": main_entity.id}]
            self.name = name or main_entity.get("name")
            self.description = description or main_entity.get("description")
        else:
            self.name = name
            self.description = description

        # Create root entity
        root_entity = DummyEntity(_id=root_id, _type="Dataset", **root_props)
        all_entities.append(root_entity)

        # Add ro-crate-metadata.json descriptor (required by RO-Crate spec)
        metadata_descriptor = DummyEntity(
            _id="ro-crate-metadata.json",
            _type="CreativeWork",
            about={"@id": "./"},
            conformsTo={"@id": "https://w3id.org/ro/crate/1.1"},
        )
        all_entities.append(metadata_descriptor)

        # Add language entity if provided (for programmingLanguage reference)
        if language_entity:
            all_entities.append(language_entity)

        # Add main entity
        if main_entity:
            all_entities.append(main_entity)

        # Add other entities
        if other_entities:
            all_entities.extend(other_entities)

        # Store for later access
        self._entities = all_entities
        self.mainEntity = {"@id": main_entity.id} if main_entity else None
        self.root_dataset = root_props
        self.metadata = DummyMetadata()

    def get_entities(self) -> List[Dict[str, Any]]:
        """Return the graph as a list of entity dicts."""
        return [entity.properties() for entity in self._entities]

    def get_rocrate_dict(self) -> Dict[str, Any]:
        """
        Return a complete RO-Crate dictionary suitable for ROCrateFactory.create_from_dict().

        This includes both @context and @graph as required by the rocrate library.
        """
        return {
            "@context": "https://w3id.org/ro/crate/1.1/context",
            "@graph": [entity.properties() for entity in self._entities],
        }
