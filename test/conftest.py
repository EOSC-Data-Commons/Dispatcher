# test/conftest.py
import os
from pathlib import Path
import pytest
from unittest.mock import Mock, patch
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
from app.config import settings
from rocrate.rocrate import ROCrate
from app.constants import (
    BINDER_PROGRAMMING_LANGUAGE,
    SCIENCEMESH_PROGRAMMING_LANGUAGE,
    GALAXY_PROGRAMMING_LANGUAGE,
    OSCAR_PROGRAMMING_LANGUAGE,
)
from app.services.im import IM
from app.domain.rocrate.request_package import (
    RequestPackage,
    WorkflowDescriptor,
    FileReference,
)

pytest_plugins = ["pytest_asyncio"]


def _build_request_package(crate: DummyCrate, lang_id: str) -> RequestPackage:
    """Build a RequestPackage from a DummyCrate for tests."""
    main = crate.main_entity
    workflow = WorkflowDescriptor(
        id=main.id,
        type=main.type,
        url=main.get("url"),
        programming_language_id=lang_id,
        runtime_platform=main.get("runtimePlatform"),
        properties=main.properties,
    )
    files = []
    for e in crate.get_entities():
        if e.type == "File":
            files.append(
                FileReference(
                    id=e.id,
                    name=e.get("name", e.id),
                    encoding_format=e.get("encodingFormat"),
                    url=e.get("url") or e.id,
                    onedata_domain=e.get("onedata:onezoneDomain"),
                    onedata_file_id=e.get("onedata:fileId"),
                    properties=e.properties,
                )
            )
    return RequestPackage(
        vre_type=lang_id,
        programming_language=lang_id,
        workflow=workflow,
        files=files,
        raw_crate={},
    )


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
    readme = DummyEntity(
        _type="File",
        **{"@id": "README.md", "name": "README.md", "content": b"# Test"},
    )
    input_file = DummyEntity(
        _type="File",
        **{"@id": "input.txt", "name": "input.txt", "content": b"test data"},
    )
    script = DummyEntity(
        _type="File",
        **{"@id": "script.py", "name": "script.py", "content": b"print('hello')"},
    )
    return DummyCrate(main_entity=main, other_entities=[readme, input_file, script])


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
        token="test-token",
        request_id=0,
        update_state=None,
        request_package=_build_request_package(
            dummy_galaxy_crate, GALAXY_PROGRAMMING_LANGUAGE
        ),
    )
    vre.svc_url = "https://usegalaxy.eu/"
    return vre


@pytest.fixture
def galaxy_vre_onedata(dummy_galaxy_crate_onedata):
    vre = VREGalaxy(
        token="test-token",
        request_id=0,
        update_state=None,
        request_package=_build_request_package(
            dummy_galaxy_crate_onedata, GALAXY_PROGRAMMING_LANGUAGE
        ),
    )
    vre.svc_url = "https://usegalaxy.eu/"
    return vre


@pytest.fixture(autouse=True)
def tmp_dir_setup(tmpdir):
    """Fixture to execute asserts before and after a test is run"""
    settings.git_repos = tmpdir
    settings.host = ""
    yield


@pytest.fixture
def binder_vre(dummy_binder_crate):
    vre = VREBinder(
        token="test-token",
        request_id=0,
        update_state=None,
        request_package=_build_request_package(
            dummy_binder_crate, BINDER_PROGRAMMING_LANGUAGE
        ),
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
    from app.domain.rocrate.parser import ROCrateParser
    from app.domain.rocrate.builder import RequestPackageBuilder

    parsed = ROCrateParser.parse(sciencemesh_rocrate.metadata.generate())
    package = RequestPackageBuilder.build(parsed)
    vre = VREScienceMesh(
        token="test-token",
        request_id=0,
        update_state=None,
        request_package=package,
    )
    vre.svc_url = "https://sciencemesh.example.org"
    return vre


@pytest.fixture
def ocm_share_request(sciencemesh_vre):
    pkg = sciencemesh_vre.request_package
    receiver = pkg.get_entity("#receiver")
    owner = pkg.get_entity("#owner")
    sender = pkg.get_entity("#sender")
    root = pkg.get_entity("./")

    ocm_share_request = {
        "shareWith": receiver.get("userid"),
        "name": root.get("name", "") if root else "",
        "description": root.get("description", "") if root else "",
        "providerId": "n/a",
        "resourceId": "n/a",
        "owner": owner.get("userid"),
        "senderDisplayName": sender.get("name"),
        "sender": sciencemesh_vre.generate_ocm_address(sender),
        "resourceType": "embedded",
        "shareType": "user",
        "protocol": {
            "name": "multi",
            "embedded": {"payload": pkg.raw_crate},
        },
    }
    return ocm_share_request


@pytest.fixture
def mock_requests_post():
    with patch("requests.post") as _mock:
        yield _mock


@pytest.fixture
def im_service(mock_settings):
    im = IM("test_token")
    im.client = Mock()
    im.inf_id = "test_inf_id"
    return im
