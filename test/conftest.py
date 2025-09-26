# test/conftest.py
import pytest
from unittest.mock import Mock, patch

from fixtures.dummy_crate import (
    DummyEntity,
    DummyCrate,
    WORKFLOW_URL,
    FILE_1,
    FILE_2,
)
from app.vres.galaxy import VREGalaxy
from app.vres.binder import VREBinder
from app.vres.sciencemesh import VREScienceMesh

pytest_plugins = ['pytest_asyncio']

@pytest.fixture
def dummy_galaxy_crate():
    workflow = DummyEntity(_type="Dataset", url=WORKFLOW_URL, name="myworkflow.ga")
    file1 = DummyEntity(_type="File", **FILE_1)
    file2 = DummyEntity(_type="File", **FILE_2)

    return DummyCrate(
        main_entity=workflow, other_entities=[file1, file2], root_dataset={}
    )


@pytest.fixture
def dummy_binder_crate():
    main = DummyEntity(
        _type="SoftwareSourceCode",
        url="https://github.com/example/notebook-repo",
        name="notebook-repo",
    )
    return DummyCrate(main_entity=main)


@pytest.fixture
def dummy_sciencemesh_crate():
    main = DummyEntity(
        _type="Dataset",
        url="https://example.org/somefile.txt",
        name="somefile.txt",
        encodingFormat="text/plain",
    )
    return DummyCrate(main_entity=main)


@pytest.fixture
def galaxy_vre(dummy_galaxy_crate):
    vre = VREGalaxy()
    vre.crate = dummy_galaxy_crate
    vre.svc_url = "https://usegalaxy.eu/"
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


@pytest.fixture
def mock_requests_post():
    with patch("requests.post") as _mock:
        yield _mock
