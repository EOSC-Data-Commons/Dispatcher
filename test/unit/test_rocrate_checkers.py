"""Unit tests for ROCrate checkers."""

import pytest
from unittest.mock import MagicMock
from app.domain.rocrate import RequestPackage
from app.domain.rocrate.checkers import (
    get_checker,
    get_checker_by_vre_type,
    GalaxyChecker,
    JupyterChecker,
    OSCARChecker,
    BinderChecker,
    ScienceMeshChecker,
    ScipionChecker,
)


class TestGalaxyChecker:
    """Test suite for GalaxyChecker."""

    @pytest.fixture
    def valid_package(self):
        """Create a mock package with valid Galaxy ROCrate."""
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

    def test_validate_valid(self, valid_package):
        """Test validation passes for valid Galaxy ROCrate."""
        checker = GalaxyChecker()
        is_valid, errors = checker.validate(valid_package)

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


class TestJupyterChecker:
    """Test suite for JupyterChecker."""

    def test_language_identifier(self):
        """Test language_identifier property returns correct value."""
        checker = JupyterChecker()
        assert checker.language_identifier == "https://jupyter.org"

    def test_validate_valid(self):
        """Test validation passes for valid Jupyter ROCrate."""
        package = MagicMock(spec=RequestPackage)
        workflow = MagicMock()
        workflow.language_identifier = "https://jupyter.org"
        package.get_workflow_info.return_value = workflow

        checker = JupyterChecker()
        is_valid, errors = checker.validate(package)

        assert is_valid is True
        assert errors == []

    def test_validate_wrong_language(self):
        """Test validation fails for wrong language identifier."""
        package = MagicMock(spec=RequestPackage)
        workflow = MagicMock()
        workflow.language_identifier = "https://galaxyproject.org/"
        package.get_workflow_info.return_value = workflow

        checker = JupyterChecker()
        is_valid, errors = checker.validate(package)

        assert is_valid is False
        assert len(errors) > 0


class TestOSCARChecker:
    """Test suite for OSCARChecker."""

    def test_language_identifier(self):
        """Test language_identifier property returns correct value."""
        checker = OSCARChecker()
        assert checker.language_identifier == "https://oscar.grycap.net/"

    def test_validate_missing_fdl(self):
        """Test validation fails when FDL is missing."""
        package = MagicMock(spec=RequestPackage)
        workflow = MagicMock()
        workflow.language_identifier = "https://oscar.grycap.net/"
        workflow.name = "Test Service"
        workflow.parts = [
            MagicMock(
                entity_id="#script",
                file_type="File",
                encoding_format="text/x-shellscript",
                url="https://example.com/script.sh",
            ),
        ]
        package.get_workflow_info.return_value = workflow

        checker = OSCARChecker()
        is_valid, errors = checker.validate(package)

        assert is_valid is False
        assert any("FDL" in error for error in errors)


class TestBinderChecker:
    """Test suite for BinderChecker."""

    def test_language_identifier(self):
        """Test language_identifier property returns correct value."""
        checker = BinderChecker()
        assert checker.language_identifier == "https://jupyter.org/binder/"

    def test_validate_valid(self):
        """Test validation passes for valid Binder ROCrate."""
        package = MagicMock(spec=RequestPackage)
        workflow = MagicMock()
        workflow.language_identifier = "https://jupyter.org/binder/"
        package.get_workflow_info.return_value = workflow

        checker = BinderChecker()
        is_valid, errors = checker.validate(package)

        assert is_valid is True
        assert errors == []


class TestScienceMeshChecker:
    """Test suite for ScienceMeshChecker."""

    def test_language_identifier(self):
        """Test language_identifier property returns correct value."""
        checker = ScienceMeshChecker()
        assert checker.language_identifier == "https://qa.cernbox.cern.ch"

    def test_validate_missing_entities(self):
        """Test validation fails when required entities are missing."""
        package = MagicMock(spec=RequestPackage)
        package.get_custom_entity_info.return_value = None
        package.get_crate_metadata.return_value = MagicMock(
            name="Test", description="Test desc"
        )

        checker = ScienceMeshChecker()
        is_valid, errors = checker.validate(package)

        assert is_valid is False
        assert len(errors) >= 4  # All 4 required entities missing

    def test_validate_valid(self):
        """Test validation passes for valid ScienceMesh ROCrate."""
        package = MagicMock(spec=RequestPackage)

        # Mock all required entities
        receiver = MagicMock()
        receiver.userid = "receiver@example.com"
        receiver.name = None

        owner = MagicMock()
        owner.userid = "owner@example.com"
        owner.name = None

        sender = MagicMock()
        sender.userid = "sender@example.com"
        sender.name = "Sender Name"

        destination = MagicMock()
        destination.properties = {"url": "https://example.com"}

        def get_entity(entity_id):
            if entity_id == "#receiver":
                return receiver
            elif entity_id == "#owner":
                return owner
            elif entity_id == "#sender":
                return sender
            elif entity_id == "#destination":
                return destination
            return None

        package.get_custom_entity_info.side_effect = get_entity
        package.get_crate_metadata.return_value = MagicMock(
            name="Test", description="Test desc"
        )

        checker = ScienceMeshChecker()
        is_valid, errors = checker.validate(package)

        assert is_valid is True
        assert errors == []


class TestScipionChecker:
    """Test suite for ScipionChecker."""

    def test_language_identifier(self):
        """Test language_identifier property returns correct value."""
        checker = ScipionChecker()
        assert checker.language_identifier == "http://scipion.i2pc.es/"

    def test_validate_valid(self):
        """Test validation passes for valid Scipion ROCrate."""
        package = MagicMock(spec=RequestPackage)
        workflow = MagicMock()
        workflow.language_identifier = "http://scipion.i2pc.es/"
        package.get_workflow_info.return_value = workflow

        checker = ScipionChecker()
        is_valid, errors = checker.validate(package)

        assert is_valid is True
        assert errors == []


class TestCheckerRegistry:
    """Test suite for checker registry functions."""

    def test_get_checker_by_language_id(self):
        """Test getting checker by language identifier."""
        checker = get_checker("https://galaxyproject.org/")
        assert isinstance(checker, GalaxyChecker)

    def test_get_checker_by_vre_type(self):
        """Test getting checker by VRE type name."""
        checker = get_checker_by_vre_type("galaxy")
        assert isinstance(checker, GalaxyChecker)

    def test_get_checker_invalid_language(self):
        """Test error on invalid language identifier."""
        with pytest.raises(ValueError):
            get_checker("invalid-language-id")

    def test_get_checker_invalid_vre_type(self):
        """Test error on invalid VRE type."""
        with pytest.raises(ValueError):
            get_checker_by_vre_type("invalid-vre")
