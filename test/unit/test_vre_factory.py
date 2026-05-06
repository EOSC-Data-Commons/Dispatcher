import pytest
from unittest.mock import MagicMock
from app.vres.base_vre import vre_factory
from app.vres.binder import VREBinder
from app.vres.sciencemesh import VREScienceMesh
from app.vres.galaxy import VREGalaxy
from app.vres.oscar import VREOSCAR
from app.domain.rocrate import RequestPackage
from app.domain.rocrate.value_objects import WorkflowInfo
from app.constants import (
    BINDER_PROGRAMMING_LANGUAGE,
    SCIENCEMESH_PROGRAMMING_LANGUAGE,
    GALAXY_PROGRAMMING_LANGUAGE,
    OSCAR_PROGRAMMING_LANGUAGE,
)


def _create_minimal_package(
    language_identifier: str, url: str | None = None
) -> RequestPackage:
    """Create a minimal RequestPackage with the given language identifier.

    This creates a mock ROCrate object that matches real RO-Crate format:
    programmingLanguage references a ComputerLanguage entity with identifier.@id.
    """
    # Create a mock crate that matches real RO-Crate format
    lang_entity_id = "#lang"
    mock_crate = MagicMock()
    mock_crate._graph = [
        {
            "@id": "./",
            "@type": "Dataset",
            "mainEntity": {"@id": "#workflow"},
            "hasPart": [{"@id": "#workflow"}],
        },
        {
            "@id": "#workflow",
            "@type": "SoftwareSourceCode",
            "url": url or "https://example.org/workflow",
            "programmingLanguage": {
                "@id": lang_entity_id
            },  # Reference to language entity
        },
        {
            "@id": lang_entity_id,
            "@type": "ComputerLanguage",
            "identifier": {"@id": language_identifier},  # Nested @id for identifier
        },
    ]
    mock_crate.mainEntity = mock_crate._graph[1]
    mock_crate.root_dataset = mock_crate._graph[0]

    return RequestPackage(mock_crate)


def test_factory_creates_sciencemesh_vre():
    """Test that factory creates ScienceMesh VRE from RequestPackage."""
    package = _create_minimal_package(
        language_identifier=SCIENCEMESH_PROGRAMMING_LANGUAGE,
        url="https://example.org/file.txt",
    )

    vre = vre_factory(
        request_package=package,
        token="test-token",
        request_id=0,
        update_state=None,
    )
    assert isinstance(vre, VREScienceMesh)


def test_factory_creates_binder_vre():
    """Test that factory creates Binder VRE from RequestPackage."""
    package = _create_minimal_package(
        language_identifier=BINDER_PROGRAMMING_LANGUAGE,
        url="https://github.com/example/repo",
    )

    vre = vre_factory(
        request_package=package,
        token="test-token",
        request_id=0,
        update_state=None,
    )
    assert isinstance(vre, VREBinder)


def test_factory_creates_galaxy_vre():
    """Test that factory creates Galaxy VRE from RequestPackage."""
    package = _create_minimal_package(
        language_identifier=GALAXY_PROGRAMMING_LANGUAGE,
        url="https://workflow.example.org/workflow.ga",
    )

    vre = vre_factory(
        request_package=package,
        token="test-token",
        request_id=0,
        update_state=None,
    )
    assert isinstance(vre, VREGalaxy)


def test_factory_creates_oscar_vre():
    """Test that factory creates OSCAR VRE from RequestPackage."""
    package = _create_minimal_package(
        language_identifier=OSCAR_PROGRAMMING_LANGUAGE,
        url=None,  # OSCAR doesn't require URL
    )

    vre = vre_factory(
        request_package=package,
        token="test-token",
        request_id=0,
        update_state=None,
    )
    assert isinstance(vre, VREOSCAR)


def test_factory_errors_on_unknown_vre_type():
    """Test that factory raises ValueError for unknown VRE types."""
    package = _create_minimal_package(
        language_identifier="unknown-language-identifier",
    )

    with pytest.raises(ValueError, match="Unsupported workflow language"):
        vre_factory(
            request_package=package,
            token="test-token",
            request_id=0,
            update_state=None,
        )
