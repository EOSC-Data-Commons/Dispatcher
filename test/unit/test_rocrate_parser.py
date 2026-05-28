"""Tests for ROCrateParser — parsing ROCrate JSON into ParsedCrate."""

import json
from pathlib import Path

import pytest

from vre_rocrate import ROCrateParser


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the directory containing ROCrate fixture files."""
    return Path(__file__).parent.parent


def _load_json(fixtures_dir: Path, file_name: str) -> dict:
    """Load a JSON fixture file from the fixtures directory."""
    with open(fixtures_dir / file_name, encoding="utf-8") as f:
        return json.load(f)


PARSER_CASES = [
    ("galaxy/ro-crate-metadata.json", "https://dockstore.org/"),
    ("oscar/ro-crate-metadata.json", "https://raw.githubusercontent.com/"),
]


class TestROCrateParser:
    """Unit tests for ROCrateParser.parse()."""

    @pytest.mark.parametrize("fixture_path,expected_prefix", PARSER_CASES)
    def test_parse_crate(self, fixtures_dir, fixture_path, expected_prefix):
        source = _load_json(fixtures_dir, fixture_path)
        parsed = ROCrateParser.parse(source)
        assert parsed.root_id == "./"
        assert parsed.main_entity is not None
        assert parsed.main_entity.id.startswith(expected_prefix)

    def test_parse_resolves_references(self, fixtures_dir):
        source = _load_json(fixtures_dir, "galaxy/ro-crate-metadata.json")
        parsed = ROCrateParser.parse(source)
        lang_ref = parsed.main_entity.get("programmingLanguage")
        assert isinstance(lang_ref, dict)
        assert lang_ref.get("@id") == "#galaxy-lang"
        lang = parsed.get("#galaxy-lang")
        assert lang is not None
        assert lang.get("identifier") == "https://galaxyproject.org/"
