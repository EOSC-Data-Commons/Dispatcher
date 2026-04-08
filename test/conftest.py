# test/conftest.py
import os
from pathlib import Path
import pytest
from unittest.mock import patch
from fixtures.dummy_crate import (
    DummyEntity,
    DummyCrate,
    WORKFLOW_URL,
    FILE_1,
    FILE_2,
    ONE_DATA_FILE,
)
from app.vres.galaxy import VREGalaxy
from app.vres.binder import VREBinder
from app.vres.sciencemesh import VREScienceMesh
import io
import zipfile as zf
from app.config import settings
from rocrate.rocrate import ROCrate
from app.constants import (
    BINDER_PROGRAMMING_LANGUAGE,
    SCIENCEMESH_PROGRAMMING_LANGUAGE,
    GALAXY_PROGRAMMING_LANGUAGE,
    OSCAR_PROGRAMMING_LANGUAGE,
)

pytest_plugins = ["pytest_asyncio"]


@pytest.fixture
def dummy_galaxy_crate():
    workflow = DummyEntity(
        _type="Dataset",
        url=WORKFLOW_URL,
        name="myworkflow.ga",
        programmingLanguage={
            "identifier": GALAXY_PROGRAMMING_LANGUAGE,
        },
    )
    file1 = DummyEntity(_type="File", **FILE_1)
    file2 = DummyEntity(_type="File", **FILE_2)

    return DummyCrate(
        main_entity=workflow, other_entities=[file1, file2], root_dataset={}
    )


@pytest.fixture
def dummy_galaxy_crate_onedata():
    workflow = DummyEntity(_type="Dataset", url=WORKFLOW_URL, name="myworkflow.ga")
    file1 = DummyEntity(_type="File", **FILE_1)
    file2 = DummyEntity(_type="File", **FILE_2)
    file3 = DummyEntity(_type="File", **ONE_DATA_FILE)

    return DummyCrate(
        main_entity=workflow, other_entities=[file1, file2, file3], root_dataset={}
    )


@pytest.fixture
def dummy_binder_crate():
    main = DummyEntity(
        _type="SoftwareSourceCode",
        url="https://github.com/example/notebook-repo",
        name="notebook-repo",
        programmingLanguage={
            "identifier": BINDER_PROGRAMMING_LANGUAGE,
        },
    )
    return DummyCrate(main_entity=main)


@pytest.fixture
def dummy_oscar_crate():
    main = DummyEntity(
        _type="SoftwareSourceCode",
        programmingLanguage={
            "identifier": OSCAR_PROGRAMMING_LANGUAGE,
        },
    )
    return DummyCrate(main_entity=main)


@pytest.fixture
def dummy_crate_with_unkown_vre_type():
    main = DummyEntity(
        _type="SoftwareSourceCode",
        programmingLanguage={
            "identifier": "random programming language",
        },
    )
    return DummyCrate(main_entity=main)


@pytest.fixture
def dummy_sciencemesh_crate():
    main = DummyEntity(
        _type="Dataset",
        url="https://example.org/somefile.txt",
        name="somefile.txt",
        encodingFormat="text/plain",
        programmingLanguage={
            "identifier": SCIENCEMESH_PROGRAMMING_LANGUAGE,
        },
    )
    return DummyCrate(main_entity=main)


@pytest.fixture
def galaxy_vre(dummy_galaxy_crate):
    vre = VREGalaxy(
        crate=dummy_galaxy_crate,
        token="test-token",
        request_id=0,
        update_state=None,
    )
    vre.svc_url = "https://usegalaxy.eu/"
    return vre


@pytest.fixture
def galaxy_vre_onedata(dummy_galaxy_crate_onedata):
    vre = VREGalaxy(
        crate=dummy_galaxy_crate_onedata,
        token="test-token",
        request_id=0,
        update_state=None,
    )
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
    vre = VREBinder(
        crate=dummy_binder_crate,
        token="test-token",
        request_id=0,
        update_state=None,
        body=create_test_zip_body(),
    )
    vre.svc_url = "https://mybinder.org"
    return vre


@pytest.fixture
def sciencemesh_rocrate():
    test_dir = Path(os.path.abspath(__file__))
    metadata_path = test_dir.parent.joinpath("sciencemesh", "ro-crate-metadata.json")
    return ROCrate(os.path.dirname(metadata_path))


@pytest.fixture
def sciencemesh_vre(sciencemesh_rocrate):
    vre = VREScienceMesh(
        crate=sciencemesh_rocrate,
        token="test-token",
        request_id=0,
        update_state=None,
    )
    vre.svc_url = "https://sciencemesh.example.org"
    return vre


@pytest.fixture
def ocm_share_request(sciencemesh_vre):
    receiver = sciencemesh_vre.crate.get("#receiver")
    owner = sciencemesh_vre.crate.get("#owner")
    sender = sciencemesh_vre.crate.get("#sender")

    sender_userid = sender.get("userid")
    if sender_userid and "@" in sender_userid:
        sender_userid = sender_userid.split("@")[0] + "@" + settings.host

    ocm_share_request = {
        "shareWith": receiver.get("userid"),
        "name": sciencemesh_vre.crate.mainEntity.get("name"),
        "description": sciencemesh_vre.crate.mainEntity.get("description"),
        "providerId": "n/a",
        "resourceId": "n/a",
        "owner": owner.get("userid"),
        "senderDisplayName": sender.get("name"),
        "sender": sender_userid,
        "resourceType": "ro-crate",
        "shareType": "user",
        "protocols": {
            "name": "multi",
            "rocrate": sciencemesh_vre.crate.metadata.generate(),
        },
    }
    return ocm_share_request


@pytest.fixture
def mock_requests_post():
    with patch("requests.post") as _mock:
        yield _mock
