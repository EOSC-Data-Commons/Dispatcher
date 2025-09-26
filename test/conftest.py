# test/conftest.py
import pytest
from unittest.mock import Mock, patch

from fixtures.dummy_crate import (
    DummyEntity,
    DummyCrate,
    WORKFLOW_URL,
    FILE_1,
    FILE_2,)
from app.vres.galaxy import VREGalaxy
from app.vres.binder import VREBinder
from app.vres.sciencemesh import VREScienceMesh

pytest_plugins = ['pytest_asyncio']

# ----------------------------------------------------------------------
# Dummy crate fixtures -------------------------------------------------
# ----------------------------------------------------------------------
@pytest.fixture
def dummy_galaxy_crate():
    workflow = DummyEntity(_type="Dataset", url=WORKFLOW_URL, name="myworkflow.ga")
    file1 = DummyEntity(_type="File", **FILE_1)
    file2 = DummyEntity(_type="File", **FILE_2)

    # ``root_dataset`` is empty → ``VRE.setup_service`` will fall back to the
    # default service URL (GALAXY_DEFAULT_SERVICE).  That is exactly what we
    # want for the majority of unit tests.
    return DummyCrate(main_entity=workflow,
                      other_entities=[file1, file2],
                      root_dataset={})

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