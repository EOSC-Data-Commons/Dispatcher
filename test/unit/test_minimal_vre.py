"""Tests for the minimal VRE start endpoint and helper."""

import pytest
from pydantic import ValidationError

from vre_rocrate import (
    MinimalVRERequest,
    MinimalFileInput,
    RequestPackage,
    RocrateBuilder,
    ROCrateParser,
    GALAXY_PROGRAMMING_LANGUAGE,
    OSCAR_PROGRAMMING_LANGUAGE,
    SCIPION_PROGRAMMING_LANGUAGE,
    BINDER_PROGRAMMING_LANGUAGE,
    JUPYTER_PROGRAMMING_LANGUAGE,
)


def _entity_by_id(graph: list[dict], eid: str) -> dict:
    """Return the first entity in *graph* whose ``@id`` matches *eid*."""
    return next(e for e in graph if e.get("@id") == eid)


# ---------------------------------------------------------------------------
# MinimalVRERequest validation
# ---------------------------------------------------------------------------

VALID_REQUEST_CASES = [
    ("galaxy", "https://dockstore.org/api/ga4gh/trs/v2/tools/test", None),
    ("oscar", "https://raw.githubusercontent.com/example/fdl.json", None),
    ("scipion", "workflow.json", [MinimalFileInput(name="workflow.json")]),
    ("binder", "notebook.ipynb", [MinimalFileInput(name="notebook.ipynb")]),
    ("jupyter", "notebook.ipynb", [MinimalFileInput(name="notebook.ipynb")]),
]

MISSING_WORKFLOW_CASES = ["galaxy", "oscar", "scipion", "binder", "jupyter"]


class TestMinimalVRERequest:
    """Validation of the MinimalVRERequest pydantic model."""

    @pytest.mark.parametrize("vre_type,workflow,files", VALID_REQUEST_CASES)
    def test_valid_request(self, vre_type, workflow, files):
        kwargs = {"vre_type": vre_type, "workflow": workflow}
        if files is not None:
            kwargs["files"] = files
        req = MinimalVRERequest(**kwargs)
        assert req.vre_type == vre_type
        assert req.workflow == workflow

    @pytest.mark.parametrize("vre_type", MISSING_WORKFLOW_CASES)
    def test_missing_workflow_raises(self, vre_type):
        with pytest.raises(ValidationError, match="workflow is required"):
            MinimalVRERequest(vre_type=vre_type)

    def test_unknown_vre_type_raises(self):
        with pytest.raises(ValidationError):
            MinimalVRERequest(vre_type="unknown")

    def test_with_files(self):
        req = MinimalVRERequest(
            vre_type="galaxy",
            workflow="https://example.com/workflow.ga",
            files=[
                MinimalFileInput(
                    name="sample.fastq",
                    url="https://data.example.org/sample.fastq",
                    encoding_format="application/fastq",
                )
            ],
        )
        assert len(req.files) == 1
        assert req.files[0].name == "sample.fastq"

    def test_with_runtime_platform_override(self):
        req = MinimalVRERequest(
            vre_type="galaxy",
            workflow="https://example.com/workflow.ga",
            runtime_platform="https://custom-galaxy.example.org/",
        )
        assert str(req.runtime_platform) == "https://custom-galaxy.example.org/"


# ---------------------------------------------------------------------------
# RequestPackage.from_minimal
# ---------------------------------------------------------------------------


class TestRequestPackageFromMinimal:
    """Building a RequestPackage from minimal VRE payload data."""

    def test_galaxy_package(self):
        package = RequestPackage.from_minimal(
            vre_type="galaxy",
            programming_language=GALAXY_PROGRAMMING_LANGUAGE,
            workflow_url="https://dockstore.org/api/ga4gh/trs/v2/tools/test",
            files_data=[
                {
                    "name": "sample.fastq",
                    "url": "https://data.example.org/sample.fastq",
                    "encoding_format": "application/fastq",
                }
            ],
            file_bytes_map={},
        )

        assert package.programming_language == GALAXY_PROGRAMMING_LANGUAGE
        assert (
            package.workflow.url == "https://dockstore.org/api/ga4gh/trs/v2/tools/test"
        )
        assert len(package.files) == 1
        assert package.files[0].name == "sample.fastq"
        assert package.files[0].url == "https://data.example.org/sample.fastq"

    def test_oscar_package(self):
        package = RequestPackage.from_minimal(
            vre_type="oscar",
            programming_language=OSCAR_PROGRAMMING_LANGUAGE,
            workflow_url="https://raw.githubusercontent.com/example/fdl.json",
            files_data=[],
            file_bytes_map={},
        )

        assert package.programming_language == OSCAR_PROGRAMMING_LANGUAGE
        assert (
            package.workflow.url == "https://raw.githubusercontent.com/example/fdl.json"
        )
        assert len(package.files) == 0

    def test_scipion_package(self):
        package = RequestPackage.from_minimal(
            vre_type="scipion",
            programming_language=SCIPION_PROGRAMMING_LANGUAGE,
            workflow_url=None,
            files_data=[],
            file_bytes_map={},
        )

        assert package.programming_language == SCIPION_PROGRAMMING_LANGUAGE
        assert package.workflow.url is None

    def test_binder_package_with_uploaded_files(self):
        package = RequestPackage.from_minimal(
            vre_type="binder",
            programming_language=BINDER_PROGRAMMING_LANGUAGE,
            workflow_url=None,
            files_data=[
                {"name": "notebook.ipynb", "url": None, "encoding_format": None},
                {"name": "requirements.txt", "url": None, "encoding_format": None},
            ],
            file_bytes_map={
                "notebook.ipynb": b'{"cells": []}',
                "requirements.txt": b"numpy==1.21.0",
            },
        )

        assert package.programming_language == BINDER_PROGRAMMING_LANGUAGE
        assert len(package.files) == 2
        assert package.files[0].properties["content"] == b'{"cells": []}'
        assert package.files[1].properties["content"] == b"numpy==1.21.0"

    def test_jupyter_package_with_uploaded_notebook(self):
        package = RequestPackage.from_minimal(
            vre_type="jupyter",
            programming_language=JUPYTER_PROGRAMMING_LANGUAGE,
            workflow_url=None,
            files_data=[
                {"name": "notebook.ipynb", "url": None, "encoding_format": None},
            ],
            file_bytes_map={
                "notebook.ipynb": b'{"cells": []}',
            },
        )

        assert package.programming_language == JUPYTER_PROGRAMMING_LANGUAGE
        assert len(package.files) == 1
        assert package.files[0].properties["content"] == b'{"cells": []}'

    def test_runtime_platform_override(self):
        package = RequestPackage.from_minimal(
            vre_type="galaxy",
            programming_language=GALAXY_PROGRAMMING_LANGUAGE,
            workflow_url="https://example.com/workflow.ga",
            files_data=[],
            file_bytes_map={},
            runtime_platform="https://custom-galaxy.example.org/",
        )

        assert package.workflow.runtime_platform == "https://custom-galaxy.example.org/"

    def test_onedata_file(self):
        package = RequestPackage.from_minimal(
            vre_type="galaxy",
            programming_language=GALAXY_PROGRAMMING_LANGUAGE,
            workflow_url="https://example.com/workflow.ga",
            files_data=[
                {
                    "name": "onedata_file",
                    "url": None,
                    "encoding_format": "image/tiff",
                    "onedata_domain": "demo.onedata.org",
                    "onedata_file_id": "00000000007EADF37368",
                }
            ],
            file_bytes_map={},
        )

        assert package.files[0].onedata_domain == "demo.onedata.org"
        assert package.files[0].onedata_file_id == "00000000007EADF37368"


# ---------------------------------------------------------------------------
# RocrateBuilder.build_from_minimal
# ---------------------------------------------------------------------------


class TestRocrateBuilder:
    """Tests for RocrateBuilder.build_from_minimal()."""

    def test_galaxy_rocrate_structure(self):
        """Verify a galaxy minimal request produces a valid ROCrate structure."""
        workflow_url = "https://dockstore.org/api/ga4gh/trs/v2/tools/test"
        data = {
            "vre_type": "galaxy",
            "workflow": workflow_url,
            "files": [
                {
                    "name": "sample.fastq",
                    "url": "https://data.example.org/sample.fastq",
                    "encoding_format": "application/fastq",
                }
            ],
        }
        crate = RocrateBuilder.build_from_minimal(data)

        assert crate["@context"] == "https://w3id.org/ro/crate/1.1/context"
        assert isinstance(crate["@graph"], list)

        graph = crate["@graph"]

        root = _entity_by_id(graph, "./")
        assert root["@type"] == "Dataset"
        assert root["mainEntity"] == {"@id": workflow_url}

        workflow = _entity_by_id(graph, workflow_url)
        assert "ComputationalWorkflow" in workflow["@type"]
        assert workflow["programmingLanguage"] == {"@id": "#galaxy-lang"}

        lang = _entity_by_id(graph, "#galaxy-lang")
        assert lang["@type"] == "ComputerLanguage"
        assert lang["identifier"] == GALAXY_PROGRAMMING_LANGUAGE

        file_entity = _entity_by_id(graph, "https://data.example.org/sample.fastq")
        assert file_entity["@type"] == "File"
        assert file_entity["name"] == "sample.fastq"
        assert file_entity["encodingFormat"] == "application/fastq"

    def test_oscar_rocrate_structure(self):
        """Verify an oscar minimal request produces a valid ROCrate structure."""
        workflow_url = "https://raw.githubusercontent.com/example/fdl.json"
        data = {
            "vre_type": "oscar",
            "workflow": workflow_url,
            "files": [
                {
                    "name": "script.sh",
                    "url": "https://raw.githubusercontent.com/grycap/oscar/master/examples/cowsay/script.sh",
                    "encoding_format": "text/x-shellscript",
                }
            ],
        }
        crate = RocrateBuilder.build_from_minimal(data)

        graph = crate["@graph"]

        lang = _entity_by_id(graph, "#oscar-lang")
        assert lang["identifier"] == OSCAR_PROGRAMMING_LANGUAGE

        workflow = _entity_by_id(graph, workflow_url)
        assert "ComputationalWorkflow" in workflow["@type"]

    def test_scipion_rocrate_no_workflow(self):
        """Verify a scipion request without workflow produces valid ROCrate."""
        data = {
            "vre_type": "scipion",
            "workflow": "workflow.json",
            "files": [],
        }
        crate = RocrateBuilder.build_from_minimal(data)

        graph = crate["@graph"]
        lang = _entity_by_id(graph, "#scipion-lang")
        assert lang["identifier"] == SCIPION_PROGRAMMING_LANGUAGE

        workflow = _entity_by_id(graph, "workflow.json")
        assert "ComputationalWorkflow" in workflow["@type"]

    def test_runtime_platform_override(self):
        """Verify runtime_platform override appears in the ROCrate."""
        workflow_url = "https://example.com/workflow.ga"
        data = {
            "vre_type": "galaxy",
            "workflow": workflow_url,
            "runtime_platform": "https://custom-galaxy.example.org/",
            "files": [],
        }
        crate = RocrateBuilder.build_from_minimal(data)

        workflow = _entity_by_id(crate["@graph"], workflow_url)
        assert workflow["runtimePlatform"] == "https://custom-galaxy.example.org/"

    def test_onedata_file_in_rocrate(self):
        """Verify onedata file attributes appear in the ROCrate."""
        data = {
            "vre_type": "galaxy",
            "workflow": "https://example.com/workflow.ga",
            "files": [
                {
                    "name": "onedata_file",
                    "url": None,
                    "encoding_format": "image/tiff",
                    "onedata_domain": "demo.onedata.org",
                    "onedata_file_id": "00000000007EADF37368",
                }
            ],
        }
        crate = RocrateBuilder.build_from_minimal(data)

        file_entity = _entity_by_id(crate["@graph"], "onedata_file")
        assert file_entity["onedata:onezoneDomain"] == "demo.onedata.org"
        assert file_entity["onedata:fileId"] == "00000000007EADF37368"

    def test_rocrate_has_required_entities(self):
        """Verify the generated ROCrate contains all required supporting entities."""
        data = {
            "vre_type": "binder",
            "workflow": "notebook.ipynb",
            "files": [],
        }
        crate = RocrateBuilder.build_from_minimal(data)

        graph = crate["@graph"]
        ids = {e["@id"] for e in graph}

        assert "ro-crate-metadata.json" in ids
        assert "./" in ids
        assert "notebook.ipynb" in ids
        assert "#binder-lang" in ids
        assert "#author-dispatcher" in ids
        assert "https://spdx.org/licenses/GPL-3.0" in ids

    def test_rocrate_can_be_parsed_back(self):
        """Verify the generated ROCrate can be parsed by ROCrateParser."""
        workflow_url = "https://dockstore.org/api/ga4gh/trs/v2/tools/test"
        data = {
            "vre_type": "galaxy",
            "workflow": workflow_url,
            "files": [
                {
                    "name": "sample.fastq",
                    "url": "https://data.example.org/sample.fastq",
                    "encoding_format": "application/fastq",
                }
            ],
        }
        crate = RocrateBuilder.build_from_minimal(data)

        parsed = ROCrateParser.parse(crate)
        assert parsed.root_id == "./"
        assert parsed.main_entity is not None
        assert parsed.main_entity.id == workflow_url
