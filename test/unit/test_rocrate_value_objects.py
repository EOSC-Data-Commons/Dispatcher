"""Unit tests for ROCrate value objects."""

import pytest
from app.domain.rocrate.value_objects import (
    FileInfo,
    WorkflowInfo,
    WorkflowPartInfo,
    ServiceConfig,
    CustomEntityInfo,
    CrateMetadata,
)


class TestFileInfo:
    """Test suite for FileInfo dataclass."""

    def test_minimal_creation(self):
        """Test creating FileInfo with only required fields."""
        info = FileInfo(
            name="test.txt",
            encoding_format="text/plain",
            url="https://example.com/file.txt",
        )
        assert info.name == "test.txt"
        assert info.encoding_format == "text/plain"
        assert info.url == "https://example.com/file.txt"
        assert info.entity_id is None
        assert info.onedata_id is None
        assert info.onedata_domain is None

    def test_full_creation(self):
        """Test creating FileInfo with all fields."""
        info = FileInfo(
            name="test.txt",
            encoding_format="text/plain",
            url="https://example.com/file.txt",
            entity_id="#file1",
            onedata_id="abc123",
            onedata_domain="example.onezone.io",
        )
        assert info.name == "test.txt"
        assert info.entity_id == "#file1"
        assert info.onedata_id == "abc123"
        assert info.onedata_domain == "example.onezone.io"

    def test_equality(self):
        """Test FileInfo equality."""
        info1 = FileInfo(
            name="test.txt",
            encoding_format="text/plain",
            url="https://example.com/file.txt",
        )
        info2 = FileInfo(
            name="test.txt",
            encoding_format="text/plain",
            url="https://example.com/file.txt",
        )
        info3 = FileInfo(
            name="other.txt",
            encoding_format="text/plain",
            url="https://example.com/file.txt",
        )

        assert info1 == info2
        assert info1 != info3


class TestWorkflowPartInfo:
    """Test suite for WorkflowPartInfo dataclass."""

    def test_minimal_creation(self):
        """Test creating WorkflowPartInfo with only required fields."""
        part = WorkflowPartInfo(
            entity_id="#part1",
            file_type="File",
            encoding_format="text/plain",
            url="https://example.com/file.txt",
        )
        assert part.entity_id == "#part1"
        assert part.file_type == "File"
        assert part.encoding_format == "text/plain"
        assert part.url == "https://example.com/file.txt"
        assert part.name is None

    def test_with_name(self):
        """Test creating WorkflowPartInfo with name."""
        part = WorkflowPartInfo(
            entity_id="#part1",
            file_type="File",
            encoding_format="text/plain",
            url="https://example.com/file.txt",
            name="input.txt",
        )
        assert part.name == "input.txt"


class TestWorkflowInfo:
    """Test suite for WorkflowInfo dataclass."""

    def test_minimal_creation(self):
        """Test creating WorkflowInfo with only required fields."""
        workflow = WorkflowInfo(
            url="https://example.com/workflow",
            language_identifier="https://galaxyproject.org/",
        )
        assert workflow.url == "https://example.com/workflow"
        assert workflow.language_identifier == "https://galaxyproject.org/"
        assert workflow.language_name is None
        assert workflow.name is None
        assert workflow.description is None
        assert workflow.parts == []

    def test_full_creation(self):
        """Test creating WorkflowInfo with all fields."""
        parts = [
            WorkflowPartInfo(
                entity_id="#file1",
                file_type="File",
                encoding_format="text/plain",
                url="https://example.com/file1.txt",
            ),
        ]
        workflow = WorkflowInfo(
            url="https://example.com/workflow",
            language_identifier="https://galaxyproject.org/",
            language_name="Galaxy",
            name="My Workflow",
            description="A test workflow",
            parts=parts,
        )
        assert workflow.language_name == "Galaxy"
        assert workflow.name == "My Workflow"
        assert workflow.description == "A test workflow"
        assert len(workflow.parts) == 1


class TestServiceConfig:
    """Test suite for ServiceConfig dataclass."""

    def test_minimal_creation(self):
        """Test creating ServiceConfig with only required fields."""
        config = ServiceConfig(url="https://example.com/service")
        assert config.url == "https://example.com/service"
        assert config.service_type is None
        assert config.name is None
        assert config.memory_requirements is None
        assert config.processor_requirements == []
        assert config.storage_requirements is None

    def test_full_creation(self):
        """Test creating ServiceConfig with all fields."""
        config = ServiceConfig(
            url="https://example.com/service",
            service_type="InfrastructureManager",
            name="My Service",
            memory_requirements="4 GiB",
            processor_requirements=["2 vCPU", "1 GPU"],
            storage_requirements="100 GiB",
        )
        assert config.service_type == "InfrastructureManager"
        assert config.name == "My Service"
        assert config.memory_requirements == "4 GiB"
        assert config.processor_requirements == ["2 vCPU", "1 GPU"]
        assert config.storage_requirements == "100 GiB"


class TestCustomEntityInfo:
    """Test suite for CustomEntityInfo dataclass."""

    def test_minimal_creation(self):
        """Test creating CustomEntityInfo with only required fields."""
        info = CustomEntityInfo(entity_id="#receiver", entity_type="Person")
        assert info.entity_id == "#receiver"
        assert info.entity_type == "Person"
        assert info.userid is None
        assert info.name is None
        assert info.properties == {}

    def test_full_creation(self):
        """Test creating CustomEntityInfo with all fields."""
        info = CustomEntityInfo(
            entity_id="#receiver",
            entity_type="Person",
            userid="user@example.com",
            name="John Doe",
            properties={"email": "john@example.com"},
        )
        assert info.userid == "user@example.com"
        assert info.name == "John Doe"
        assert info.properties == {"email": "john@example.com"}


class TestCrateMetadata:
    """Test suite for CrateMetadata dataclass."""

    def test_minimal_creation(self):
        """Test creating CrateMetadata with no fields."""
        metadata = CrateMetadata()
        assert metadata.name is None
        assert metadata.description is None
        assert metadata.date_published is None
        assert metadata.license is None

    def test_full_creation(self):
        """Test creating CrateMetadata with all fields."""
        metadata = CrateMetadata(
            name="My Research Data",
            description="A dataset for analysis",
            date_published="2024-01-01",
            license="CC-BY-4.0",
        )
        assert metadata.name == "My Research Data"
        assert metadata.description == "A dataset for analysis"
        assert metadata.date_published == "2024-01-01"
        assert metadata.license == "CC-BY-4.0"
