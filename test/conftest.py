# test/conftest.py
import os
import pytest
from unittest.mock import patch
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
import io
import zipfile as zf
from app.config import settings

pytest_plugins = ["pytest_asyncio"]


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


@pytest.fixture(autouse=True)
def tmp_dir_setup(tmpdir):
    """Fixture to execute asserts before and after a test is run"""
    settings.git_repos = tmpdir
    settings.host = ""
    yield


def create_test_zip_body():
    # Create a ZIP file in memory with test content
    zip_buffer = io.BytesIO()
    with zf.ZipFile(zip_buffer, "w") as zip_file:
        zip_file.writestr("ro-crate-metadata.json", '{"@context": "..."}')
        zip_file.writestr("README.md", "# Test")
        zip_file.writestr("input.txt", "test data")
        zip_file.writestr("script.py", "print('hello')")

    return zip_buffer.getvalue()


@pytest.fixture
def binder_vre(dummy_binder_crate):
    vre = VREBinder()
    vre.crate = dummy_binder_crate
    vre.svc_url = "https://mybinder.org"
    vre.body = create_test_zip_body()

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
