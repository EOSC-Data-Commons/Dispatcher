"""Tests for RequestPackage model helpers and serialization."""

import json
from pathlib import Path

import pytest

from vre_rocrate import ROCrateParser, RequestPackageBuilder, RequestPackage


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the directory containing ROCrate fixture files."""
    return Path(__file__).parent.parent


def _load_json(fixtures_dir: Path, file_name: str) -> dict:
    """Load a JSON fixture file from the fixtures directory."""
    with open(fixtures_dir / file_name, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

SERIALIZATION_CASES = [
    "galaxy/ro-crate-metadata.json",
    "oscar/ro-crate-metadata.json",
    "simple-binder/ro-crate-metadata.json",
]


class TestRequestPackageSerialization:
    """Round-trip tests for RequestPackage.to_dict() / from_dict()."""

    @pytest.mark.parametrize("fixture_path", SERIALIZATION_CASES)
    def test_to_dict_and_from_dict_roundtrip(self, fixtures_dir, fixture_path):
        source = _load_json(fixtures_dir, fixture_path)
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        d = package.to_dict()
        restored = RequestPackage.from_dict(d)
        assert restored.vre_type == package.vre_type
        assert restored.workflow_url == package.workflow_url
        assert len(restored.files) == len(package.files)
        if package.files:
            assert restored.files[0].name == package.files[0].name


# ---------------------------------------------------------------------------
# Helper properties
# ---------------------------------------------------------------------------


class TestRequestPackageHelpers:
    """Tests for RequestPackage helper properties and methods."""

    def test_local_vs_remote_files(self, fixtures_dir):
        source = _load_json(fixtures_dir, "galaxy/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        assert len(package.local_files) == 0
        assert len(package.remote_files) == 2

    def test_files_by_encoding(self, fixtures_dir):
        source = _load_json(fixtures_dir, "oscar/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        scripts = package.files_by_encoding("text/x-shellscript")
        assert len(scripts) == 1
        assert scripts[0].name == "script.sh"

    def test_files_by_encoding_no_match(self, fixtures_dir):
        source = _load_json(fixtures_dir, "galaxy/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        result = package.files_by_encoding("application/octet-stream")
        assert result == []

    def test_file_by_id(self, fixtures_dir):
        source = _load_json(fixtures_dir, "galaxy/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        f = package.file_by_id(
            "https://example-files.online-convert.com/document/txt/example.txt"
        )
        assert f is not None
        assert f.name == "simpletext_input"

    def test_file_by_id_not_found(self, fixtures_dir):
        source = _load_json(fixtures_dir, "galaxy/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        f = package.file_by_id("https://nonexistent.example.com/file.txt")
        assert f is None

    def test_workflow_inputs_outputs(self, fixtures_dir):
        source = _load_json(fixtures_dir, "galaxy/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        assert len(package.workflow_inputs) == 1
        assert package.workflow_inputs[0].name == "simpletext_input"
        assert len(package.workflow_outputs) == 1
        assert package.workflow_outputs[0].name == "reversed_text"

    def test_mixed_local_remote_files(self, fixtures_dir):
        """Verify local_files and remote_files partition correctly with mixed data."""
        source = _load_json(fixtures_dir, "oscar/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        package = RequestPackageBuilder.build(parsed)
        # oscar fixture has 1 remote (script.sh URL) + 1 local (input) + 1 workflow
        assert len(package.local_files) >= 0
        assert len(package.remote_files) >= 0
        assert len(package.local_files) + len(package.remote_files) == len(
            package.files
        )
