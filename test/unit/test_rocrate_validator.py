"""Tests for ValidationPipeline — basic ROCrate structure validation."""

import pytest

from vre_rocrate import ROCrateParser, ValidationPipeline, CrateValidationError


class TestValidationPipeline:
    """Unit tests for ValidationPipeline.validate_basic()."""

    def test_valid_crate_passes(self, galaxy_rocrate_source):
        parsed = ROCrateParser.parse(galaxy_rocrate_source)
        ValidationPipeline.validate_basic(parsed)

    def test_missing_main_entity_raises(self):
        source = {
            "@context": "https://w3id.org/ro/crate/1.1/context",
            "@graph": [
                {"@id": "./", "@type": "Dataset"},
                {
                    "@id": "ro-crate-metadata.json",
                    "@type": "CreativeWork",
                    "about": {"@id": "./"},
                    "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                },
            ],
        }
        parsed = ROCrateParser.parse(source)
        with pytest.raises(CrateValidationError, match="Missing mainEntity"):
            ValidationPipeline.validate_basic(parsed)

    def test_missing_programming_language_raises(self):
        source = {
            "@context": "https://w3id.org/ro/crate/1.1/context",
            "@graph": [
                {"@id": "./", "@type": "Dataset", "mainEntity": {"@id": "#wf"}},
                {"@id": "#wf", "@type": "File"},
                {
                    "@id": "ro-crate-metadata.json",
                    "@type": "CreativeWork",
                    "about": {"@id": "./"},
                    "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                },
            ],
        }
        parsed = ROCrateParser.parse(source)
        with pytest.raises(CrateValidationError, match="programmingLanguage"):
            ValidationPipeline.validate_basic(parsed)

    def test_missing_language_identifier_raises(self):
        source = {
            "@context": "https://w3id.org/ro/crate/1.1/context",
            "@graph": [
                {"@id": "./", "@type": "Dataset", "mainEntity": {"@id": "#wf"}},
                {
                    "@id": "#wf",
                    "@type": "File",
                    "programmingLanguage": {"@id": "#lang"},
                },
                {"@id": "#lang", "@type": "ComputerLanguage", "name": "Test"},
                {
                    "@id": "ro-crate-metadata.json",
                    "@type": "CreativeWork",
                    "about": {"@id": "./"},
                    "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                },
            ],
        }
        parsed = ROCrateParser.parse(source)
        with pytest.raises(CrateValidationError, match="identifier"):
            ValidationPipeline.validate_basic(parsed)
