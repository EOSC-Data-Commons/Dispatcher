# test/conftest.py
import pytest
from unittest.mock import Mock, patch

from test.fixtures.dummy_crate import DummyEntity, DummyCrate
from app.vre.galaxy import VREGalaxy
from app.vre.binder import VREBinder
from app.vre.sciencemesh import VREScienceMesh


# ----------------------------------------------------------------------
# Dummy crate fixtures -------------------------------------------------
# ----------------------------------------------------------------------
@pytest.fixture
def dummy_galaxy_crate():
    """
    Crate containing:
      * a workflow (mainEntity) with a valid TRS URL
      * two File entities that will become input files
    """
    workflow = DummyEntity(
        _type="Dataset",
        url="https://workflow.example.org/myworkflow.ga",
        name="myworkflow.ga",
    )
    file1 = DummyEntity(
        _type="File",
        name="sample1.fastq",
        encodingFormat="application/fastq",
        url="https://data.example.org/sample1.fastq",
    )
    file2 = DummyEntity(
        _type="File",
        name="sample2.fastq",
        encodingFormat="application/fastq",
        url="https://data.example.org/sample2.fastq",
    )
    return DummyCrate(main_entity=workflow, other_entities=[file1, file2])


@pytest.fixture
def dummy_binder_crate():
    """
    Minimal crate for the Binder VRE – only a mainEntity with a git URL
    is required for the current implementation.
    """
    main = DummyEntity(
        _type="SoftwareSourceCode",
        url="https://github.com/example/notebook-repo",
        name="notebook-repo",
    )
    return DummyCrate(main_entity=main)


@pytest.fixture
def dummy_sciencemesh_crate():
    """
    Example crate for ScienceMesh – the real    implementation uses a
    `Dataset` entity with a `url` that points at a remote file.
    """
    main = DummyEntity(
        _type="Dataset",
        url="https://example.org/somefile.txt",
        name="somefile.txt",
        encodingFormat="text/plain",
    )
    return DummyCrate(main_entity=main)


# ----------------------------------------------------------------------
# VRE instances --------------------------------------------------------
# ----------------------------------------------------------------------
@pytest.fixture
def galaxy_vre(dummy_galaxy_crate):
    vre = VREGalaxy()
    vre.crate = dummy_galaxy_crate
    vre.svc_url = "https://usegalaxy.eu/"          # deterministic base URL
    return vre


@pytest.fixture
def binder_vre(dummy_binder_crate):
    vre = VREBinder()
    vre.crate = dummy_binder_crate
    vre.svc_url = "https://mybinder.org"
    return vre


@pytest.fixture
def sciencemesh_vre(dummy_sciencemesh_crate):
    vre = VREScienceMesh()
    vre.crate = dummy_sciencemesh_crate
    vre.svc_url = "https://sciencemesh.example.org"
    return vre


# ----------------------------------------------------------------------
# Mock helpers ---------------------------------------------------------
# ----------------------------------------------------------------------
@pytest.fixture
def mock_requests_post():
    """
    Patches ``requests.post`` for the duration of a test and returns a Mock
    that behaves like the ``Response`` object used in the VRE code.
    """
    with patch("requests.post") as _mock:
        yield _mock