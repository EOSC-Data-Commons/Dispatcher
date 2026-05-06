"""Unit tests for ROCrate validation via parse_rocrate."""

import pytest
from unittest.mock import MagicMock
from fastapi.exceptions import HTTPException
from app.domain.rocrate import ROCrateFactory, RequestPackage
from app.domain.rocrate.checkers import GalaxyChecker
from app.routers.utils.vre import parse_rocrate


def create_valid_rocrate_json():
    """Create a valid RO-Crate JSON for testing."""
    return {
        "@context": "https://w3id.org/ro/crate/1.1/context",
        "@graph": [
            {
                "@id": "./",
                "@type": "Dataset",
                "datePublished": "2025-09-26T14:09:25+00:00",
                "mainEntity": {"@id": "#workflow"},
                "hasPart": [{"@id": "#workflow"}],
            },
            {
                "@id": "#workflow",
                "@type": "File",
                "url": "https://example.com/workflow",
                "programmingLanguage": {"@id": "#galaxy-lang"},
            },
            {
                "@id": "#galaxy-lang",
                "@type": "ComputerLanguage",
                "name": "Galaxy",
                "identifier": {"@id": "https://galaxyproject.org/"},
            },
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "about": {"@id": "./"},
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
            },
        ],
    }


def create_rocrate_json_without_main_entity():
    """Create RO-Crate JSON without mainEntity."""
    return {
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


def create_rocrate_json_with_invalid_programming_language():
    """Create RO-Crate JSON with invalid programmingLanguage (string instead of ref)."""
    data = create_valid_rocrate_json()
    for item in data["@graph"]:
        if item.get("@id") == "#workflow":
            item["programmingLanguage"] = "cwl"  # Invalid: should be {"@id": "..."}
            break
    return data


def test_parse_rocrate_valid():
    """Test that parse_rocrate succeeds for valid RO-Crate."""
    json_data = create_valid_rocrate_json()
    result = parse_rocrate(json_data)
    assert result == json_data


def test_parse_rocrate_with_vre_type_validation():
    """Test that parse_rocrate validates against VRE-specific checker."""
    # Add hasPart with a file to satisfy Galaxy checker requirements
    json_data = create_valid_rocrate_json()
    # Add a file entity
    json_data["@graph"].append(
        {
            "@id": "#file1",
            "@type": "File",
            "name": "input.txt",
            "url": "https://example.com/input.txt",
            "encodingFormat": "text/plain",
        }
    )
    # Update workflow's hasPart
    for item in json_data["@graph"]:
        if item.get("@id") == "#workflow":
            item["hasPart"] = [{"@id": "#file1"}]
            break
    # Also update root dataset's hasPart
    for item in json_data["@graph"]:
        if item.get("@id") == "./":
            item["hasPart"] = [{"@id": "#workflow"}, {"@id": "#file1"}]
            break

    # Validate as Galaxy type
    result = parse_rocrate(json_data, vre_type="galaxy")
    assert result == json_data


def test_parse_rocrate_missing_main_entity():
    """Test that parse_rocrate raises HTTPException when mainEntity is missing and vre_type is specified."""
    json_data = create_rocrate_json_without_main_entity()
    # Without vre_type, parse_rocrate just validates basic structure (which passes)
    # With vre_type, it creates a RequestPackage and calls validate(), which will fail
    with pytest.raises(HTTPException) as exc_info:
        parse_rocrate(json_data, vre_type="galaxy")
    assert exc_info.value.status_code == 400
    # The error should mention mainEntity or workflow structure
    assert "Invalid ROCrate" in str(exc_info.value.detail)


def test_parse_rocrate_invalid_programming_language():
    """Test that parse_rocrate handles invalid programmingLanguage format."""
    json_data = create_rocrate_json_with_invalid_programming_language()
    # This should still work because the code handles both reference and inline formats
    # but the language_identifier will be empty
    result = parse_rocrate(json_data)
    assert result == json_data


def test_parse_rocrate_wrong_vre_type():
    """Test that parse_rocrate fails when VRE type doesn't match."""
    # Create a Jupyter RO-Crate with URL
    jupyter_data = {
        "@context": "https://w3id.org/ro/crate/1.1/context",
        "@graph": [
            {
                "@id": "./",
                "@type": "Dataset",
                "mainEntity": {"@id": "#workflow"},
                "hasPart": [{"@id": "#workflow"}],
            },
            {
                "@id": "#workflow",
                "@type": "SoftwareSourceCode",
                "url": "https://example.com/notebook.ipynb",
                "programmingLanguage": {"@id": "#jupyter-lang"},
            },
            {
                "@id": "#jupyter-lang",
                "@type": "ComputerLanguage",
                "identifier": {"@id": "https://jupyter.org"},
            },
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "about": {"@id": "./"},
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
            },
        ],
    }
    # Try to validate as Galaxy - should fail because language identifier doesn't match
    with pytest.raises(HTTPException) as exc_info:
        parse_rocrate(jupyter_data, vre_type="galaxy")
    assert exc_info.value.status_code == 400
    # Error should mention language mismatch
    assert "language" in str(exc_info.value.detail).lower() or "Galaxy" in str(
        exc_info.value.detail
    )


class TestGalaxyCheckerDirectly:
    """Tests for GalaxyChecker using RequestPackage."""

    @pytest.fixture
    def valid_galaxy_package(self):
        """Create a mock RequestPackage with valid Galaxy RO-Crate."""
        package = MagicMock(spec=RequestPackage)
        workflow = MagicMock()
        workflow.url = "https://example.com/workflow"
        workflow.language_identifier = "https://galaxyproject.org/"
        workflow.name = "Test Workflow"
        workflow.parts = [
            MagicMock(
                entity_id="#file1",
                file_type="File",
                encoding_format="text/plain",
                url="https://example.com/file.txt",
            ),
        ]
        package.get_workflow_info.return_value = workflow
        return package

    def test_language_identifier(self):
        """Test language_identifier property returns correct value."""
        checker = GalaxyChecker()
        assert checker.language_identifier == "https://galaxyproject.org/"

    def test_validate_valid(self, valid_galaxy_package):
        """Test validation passes for valid Galaxy RO-Crate."""
        checker = GalaxyChecker()
        is_valid, errors = checker.validate(valid_galaxy_package)

        assert is_valid is True
        assert errors == []

    def test_validate_missing_url(self):
        """Test validation fails when workflow URL is missing."""
        package = MagicMock(spec=RequestPackage)
        workflow = MagicMock()
        workflow.url = None
        workflow.language_identifier = "https://galaxyproject.org/"
        workflow.parts = []
        package.get_workflow_info.return_value = workflow

        checker = GalaxyChecker()
        is_valid, errors = checker.validate(package)

        assert is_valid is False
        assert any("url" in error for error in errors)

    def test_validate_wrong_language(self):
        """Test validation fails for wrong language identifier."""
        package = MagicMock(spec=RequestPackage)
        workflow = MagicMock()
        workflow.url = "https://example.com/workflow"
        workflow.language_identifier = "https://jupyter.org"
        workflow.parts = []
        package.get_workflow_info.return_value = workflow

        checker = GalaxyChecker()
        is_valid, errors = checker.validate(package)

        assert is_valid is False
        assert any("Galaxy" in error for error in errors)
