"""Unit tests for RequestPackage class."""

import pytest
from unittest.mock import MagicMock
from app.domain.rocrate import RequestPackage, ROCrateFactory
from app.domain.rocrate.value_objects import FileInfo, WorkflowInfo, ServiceConfig
from app.exceptions import WorkflowURLError, VREConfigurationError


class TestRequestPackage:
    """Test suite for RequestPackage class."""

    @pytest.fixture
    def mock_crate(self):
        """Create a mock ROCrate instance with test data matching real RO-Crate format."""
        crate = MagicMock()
        crate._graph = [
            {
                "@id": "./",
                "@type": "Dataset",
                "mainEntity": {"@id": "#workflow"},
                "hasPart": [{"@id": "#workflow"}, {"@id": "#file1"}],
            },
            {
                "@id": "#workflow",
                "@type": ["File", "SoftwareSourceCode"],
                "url": "https://example.com/workflow",
                "name": "Test Workflow",
                "programmingLanguage": {
                    "@id": "#galaxy-lang"
                },  # Reference to language entity
                "hasPart": [{"@id": "#file1"}],
            },
            {
                "@id": "#galaxy-lang",
                "@type": "ComputerLanguage",
                "identifier": {"@id": "https://galaxyproject.org/"},
                "name": "Galaxy",
            },
            {
                "@id": "#file1",
                "@type": "File",
                "name": "input.txt",
                "url": "https://example.com/input.txt",
                "encodingFormat": "text/plain",
            },
            {
                "@id": "#receiver",
                "@type": "Person",
                "userid": "user@example.com",
                "name": "Test User",
            },
        ]
        crate.mainEntity = crate._graph[1]
        crate.root_dataset = crate._graph[0]
        return crate

    def test_init(self, mock_crate):
        """Test RequestPackage initialization."""
        package = RequestPackage(mock_crate)
        assert package is not None

    def test_get_workflow_info(self, mock_crate):
        """Test get_workflow_info returns correct WorkflowInfo."""
        package = RequestPackage(mock_crate)
        workflow = package.get_workflow_info()

        assert isinstance(workflow, WorkflowInfo)
        assert workflow.url == "https://example.com/workflow"
        assert workflow.language_identifier == "https://galaxyproject.org/"
        assert workflow.name == "Test Workflow"
        assert len(workflow.parts) == 1

    def test_get_workflow_url_missing(self, mock_crate):
        """Test WorkflowURLError when URL is missing."""
        # Set mainEntity to have no url property
        mock_crate.mainEntity = {"@id": "#workflow"}
        # Also need to update _graph so cache doesn't have old data
        mock_crate._graph[1] = {"@id": "#workflow", "@type": "SoftwareSourceCode"}
        package = RequestPackage(mock_crate)
        package._cache_valid = False  # Force cache refresh
        with pytest.raises(WorkflowURLError):
            package.get_workflow_url()

    def test_get_file_info_list(self, mock_crate):
        """Test get_file_info_list returns correct FileInfo objects."""
        package = RequestPackage(mock_crate)
        files = package.get_file_info_list()

        # Should return only File-type entities (not the workflow which is Dataset type)
        file_entities = [f for f in files if f.entity_id != "#workflow"]
        assert len(file_entities) == 1
        file_info = file_entities[0]
        assert isinstance(file_info, FileInfo)
        assert file_info.name == "input.txt"
        assert file_info.encoding_format == "text/plain"
        assert file_info.url == "https://example.com/input.txt"
        assert file_info.entity_id == "#file1"

    def test_get_service_config(self, mock_crate):
        """Test get_service_config returns correct ServiceConfig."""
        # Add runsOn to root dataset
        mock_crate.root_dataset["runsOn"] = {
            "url": "https://example.com/service",
            "serviceType": "InfrastructureManager",
            "memoryRequirements": "4 GiB",
            "processorRequirements": ["2 vCPU"],
        }
        package = RequestPackage(mock_crate)
        config = package.get_service_config()

        assert config is not None
        assert config.url == "https://example.com/service"
        assert config.service_type == "InfrastructureManager"
        assert config.memory_requirements == "4 GiB"
        assert config.processor_requirements == ["2 vCPU"]

    def test_get_service_config_none(self, mock_crate):
        """Test get_service_config returns None when no runsOn."""
        mock_crate.root_dataset = {}
        package = RequestPackage(mock_crate)
        config = package.get_service_config()
        assert config is None

    def test_get_custom_entity_info(self, mock_crate):
        """Test get_custom_entity_info returns correct CustomEntityInfo."""
        package = RequestPackage(mock_crate)
        entity = package.get_custom_entity_info("#receiver")

        assert entity is not None
        assert entity.entity_id == "#receiver"
        assert entity.entity_type == "Person"
        assert entity.userid == "user@example.com"
        assert entity.name == "Test User"

    def test_get_custom_entity_info_not_found(self, mock_crate):
        """Test get_custom_entity_info returns None when not found."""
        package = RequestPackage(mock_crate)
        entity = package.get_custom_entity_info("#nonexistent")
        assert entity is None

    def test_get_crate_metadata(self, mock_crate):
        """Test get_crate_metadata returns correct CrateMetadata."""
        mock_crate.name = "Test Crate"
        mock_crate.description = "A test crate"
        mock_crate.root_dataset["datePublished"] = "2024-01-01"
        mock_crate.root_dataset["license"] = "CC-BY-4.0"

        package = RequestPackage(mock_crate)
        metadata = package.get_crate_metadata()

        assert metadata.name == "Test Crate"
        assert metadata.description == "A test crate"
        assert metadata.date_published == "2024-01-01"
        assert metadata.license == "CC-BY-4.0"


class TestROCrateFactory:
    """Test suite for ROCrateFactory class."""

    def test_create_from_dict(self, valid_rocrate_dict):
        """Test creating package from dictionary."""
        package = ROCrateFactory.create_from_dict(valid_rocrate_dict)
        assert package is not None
        workflow = package.get_workflow_info()
        assert workflow.url == "https://example.com/workflow"
        assert workflow.language_identifier == "https://galaxyproject.org/"
        assert workflow.language_name == "Galaxy"

    def test_create_from_json(self, valid_rocrate_dict):
        """Test creating package from JSON string."""
        import json

        json_str = json.dumps(valid_rocrate_dict)
        package = ROCrateFactory.create_from_json(json_str)
        assert package is not None
        workflow = package.get_workflow_info()
        assert workflow.url == "https://example.com/workflow"
        assert workflow.language_identifier == "https://galaxyproject.org/"
        assert workflow.language_name == "Galaxy"
