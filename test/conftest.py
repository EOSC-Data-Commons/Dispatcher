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
from app.vres.oscar import VREOSCAR
from app.vres.sciencemesh import VREScienceMesh
import io
import zipfile as zf
from app.config import settings
from app.domain.rocrate import ROCrateFactory
from app.constants import (
    BINDER_PROGRAMMING_LANGUAGE,
    SCIENCEMESH_PROGRAMMING_LANGUAGE,
    GALAXY_PROGRAMMING_LANGUAGE,
    OSCAR_PROGRAMMING_LANGUAGE,
)

pytest_plugins = ["pytest_asyncio"]


def _make_lang_entity(lang_id: str, identifier: str) -> DummyEntity:
    """Create a ComputerLanguage entity with proper reference format."""
    return DummyEntity(
        _id=lang_id,
        _type="ComputerLanguage",
        identifier={"@id": identifier},
    )


@pytest.fixture
def dummy_galaxy_crate():
    lang = _make_lang_entity("#galaxy-lang", GALAXY_PROGRAMMING_LANGUAGE)
    workflow = DummyEntity(
        _id="#workflow",
        _type="Dataset",
        url=WORKFLOW_URL,
        name="myworkflow.ga",
        programmingLanguage={"@id": "#galaxy-lang"},
    )
    file1 = DummyEntity(_id="#file1", _type="File", **FILE_1)
    file2 = DummyEntity(_id="#file2", _type="File", **FILE_2)

    return DummyCrate(
        main_entity=workflow, other_entities=[lang, file1, file2], root_dataset={}
    )


@pytest.fixture
def dummy_galaxy_crate_no_url():
    """Galaxy crate with no workflow URL — used to test WorkflowURLError."""
    lang = _make_lang_entity("#galaxy-lang", GALAXY_PROGRAMMING_LANGUAGE)
    workflow = DummyEntity(
        _id="#workflow",
        _type="Dataset",
        name="myworkflow.ga",
        programmingLanguage={"@id": "#galaxy-lang"},
        # No url property
    )
    return DummyCrate(main_entity=workflow, language_entity=lang)


@pytest.fixture
def dummy_galaxy_crate_onedata():
    workflow = DummyEntity(
        _id="#workflow",
        _type="Dataset",
        url=WORKFLOW_URL,
        name="myworkflow.ga",
    )
    file1 = DummyEntity(_id="#file1", _type="File", **FILE_1)
    file2 = DummyEntity(_id="#file2", _type="File", **FILE_2)
    file3 = DummyEntity(_id="#file3", _type="File", **ONE_DATA_FILE)

    return DummyCrate(
        main_entity=workflow, other_entities=[file1, file2, file3], root_dataset={}
    )


@pytest.fixture
def dummy_binder_crate():
    lang = _make_lang_entity("#binder-lang", BINDER_PROGRAMMING_LANGUAGE)
    main = DummyEntity(
        _id="#main",
        _type="SoftwareSourceCode",
        url="https://github.com/example/notebook-repo",
        name="notebook-repo",
        programmingLanguage={"@id": "#binder-lang"},
    )
    return DummyCrate(main_entity=main, language_entity=lang)


@pytest.fixture
def dummy_oscar_crate():
    lang = _make_lang_entity("#oscar-lang", OSCAR_PROGRAMMING_LANGUAGE)
    main = DummyEntity(
        _id="#main",
        _type="SoftwareSourceCode",
        name="test-service",
        programmingLanguage={"@id": "#oscar-lang"},
    )
    return DummyCrate(main_entity=main, language_entity=lang)


def _make_oscar_lang():
    """Shared OSCAR ComputerLanguage entity."""
    return _make_lang_entity("#oscar-lang", OSCAR_PROGRAMMING_LANGUAGE)


@pytest.fixture
def dummy_oscar_crate_no_hasparts():
    """OSCAR crate with no hasPart — triggers 'Missing FDL' error."""
    main = DummyEntity(
        _id="#main",
        _type="SoftwareSourceCode",
        name="test-service",
        url="http://example.com/service",
        programmingLanguage={"@id": "#oscar-lang"},
    )
    return DummyCrate(main_entity=main, language_entity=_make_oscar_lang())


@pytest.fixture
def dummy_oscar_crate_invalid_type():
    """OSCAR crate with hasPart pointing to a non-File entity."""
    part = DummyEntity(_id="#not-a-file", _type="NotAFile", name="something")
    main = DummyEntity(
        _id="#main",
        _type="SoftwareSourceCode",
        name="test-service",
        url="http://example.com/service",
        programmingLanguage={"@id": "#oscar-lang"},
        hasPart=[{"@id": "#not-a-file"}],
    )
    return DummyCrate(
        main_entity=main,
        other_entities=[part],
        language_entity=_make_oscar_lang(),
    )


@pytest.fixture
def dummy_oscar_crate_no_fdl():
    """OSCAR crate with a File part that is not application/json."""
    part = DummyEntity(
        _id="#fdl",
        _type="File",
        name="script.sh",
        encodingFormat="text/plain",
        url="http://some-url",
    )
    main = DummyEntity(
        _id="#main",
        _type="SoftwareSourceCode",
        name="test-service",
        url="http://example.com/service",
        programmingLanguage={"@id": "#oscar-lang"},
        hasPart=[{"@id": "#fdl"}],
    )
    return DummyCrate(
        main_entity=main,
        other_entities=[part],
        language_entity=_make_oscar_lang(),
    )


@pytest.fixture
def dummy_oscar_crate_with_fdl():
    """OSCAR crate with a JSON FDL part — valid for service creation."""
    part = DummyEntity(
        _id="#fdl",
        _type="File",
        name="fdl.json",
        encodingFormat="application/json",
        url="http://some-url",
    )
    main = DummyEntity(
        _id="#main",
        _type="SoftwareSourceCode",
        name="test-service",
        url="http://example.com/service",
        programmingLanguage={"@id": "#oscar-lang"},
        hasPart=[{"@id": "#fdl"}],
    )
    return DummyCrate(
        main_entity=main,
        other_entities=[part],
        language_entity=_make_oscar_lang(),
    )


@pytest.fixture
def dummy_crate_with_unkown_vre_type():
    lang = _make_lang_entity("#unknown-lang", "random programming language")
    main = DummyEntity(
        _id="#main",
        _type="SoftwareSourceCode",
        name="unknown-service",
        programmingLanguage={"@id": "#unknown-lang"},
    )
    return DummyCrate(main_entity=main, language_entity=lang)


@pytest.fixture
def dummy_sciencemesh_crate():
    lang = _make_lang_entity("#sm-lang", SCIENCEMESH_PROGRAMMING_LANGUAGE)
    main = DummyEntity(
        _id="#main",
        _type="Dataset",
        url="https://example.org/somefile.txt",
        name="somefile.txt",
        encodingFormat="text/plain",
        programmingLanguage={"@id": "#sm-lang"},
    )
    return DummyCrate(main_entity=main, language_entity=lang)


@pytest.fixture
def galaxy_vre(dummy_galaxy_crate):
    """Create a Galaxy VRE instance with proper RequestPackage."""
    package = ROCrateFactory.create_from_dict(dummy_galaxy_crate.get_rocrate_dict())

    vre = VREGalaxy(
        request_package=package,
        token="test-token",
        request_id=0,
        update_state=None,
    )
    vre.svc_url = "https://usegalaxy.eu/"
    return vre


@pytest.fixture
def galaxy_vre_onedata(dummy_galaxy_crate_onedata):
    """Create a Galaxy VRE instance with Onedata files."""
    package = ROCrateFactory.create_from_dict(
        dummy_galaxy_crate_onedata.get_rocrate_dict()
    )

    vre = VREGalaxy(
        request_package=package,
        token="test-token",
        request_id=0,
        update_state=None,
    )
    vre.svc_url = "https://usegalaxy.eu/"
    return vre


@pytest.fixture
def galaxy_vre_no_url(dummy_galaxy_crate_no_url):
    """Create a Galaxy VRE instance with no workflow URL."""
    package = ROCrateFactory.create_from_dict(
        dummy_galaxy_crate_no_url.get_rocrate_dict()
    )
    vre = VREGalaxy(
        request_package=package,
        token="test-token",
        request_id=0,
        update_state=None,
    )
    vre.svc_url = "https://usegalaxy.eu/"
    return vre


def _make_oscar_vre(crate):
    """Create an OSCAR VRE from a DummyCrate."""
    package = ROCrateFactory.create_from_dict(crate.get_rocrate_dict())
    vre = VREOSCAR(
        request_package=package,
        token="dummy_token",
        request_id=0,
        update_state=None,
    )
    return vre


@pytest.fixture
def oscar_vre_no_hasparts(dummy_oscar_crate_no_hasparts):
    return _make_oscar_vre(dummy_oscar_crate_no_hasparts)


@pytest.fixture
def oscar_vre_invalid_type(dummy_oscar_crate_invalid_type):
    return _make_oscar_vre(dummy_oscar_crate_invalid_type)


@pytest.fixture
def oscar_vre_no_fdl(dummy_oscar_crate_no_fdl):
    return _make_oscar_vre(dummy_oscar_crate_no_fdl)


@pytest.fixture
def oscar_vre_with_fdl(dummy_oscar_crate_with_fdl):
    return _make_oscar_vre(dummy_oscar_crate_with_fdl)


@pytest.fixture(autouse=True)
def tmp_dir_setup(tmpdir):
    """Fixture to execute asserts before and after a test is run"""
    settings.git_repos = tmpdir
    settings.host = ""
    yield


def create_test_zip_body():
    """Create a test ZIP file in memory with standard content."""
    zip_buffer = io.BytesIO()
    with zf.ZipFile(zip_buffer, "w") as zip_file:
        zip_file.writestr("ro-crate-metadata.json", '{"@context": "..."}')
        zip_file.writestr("README.md", "# Test")
        zip_file.writestr("input.txt", "test data")
        zip_file.writestr("script.py", "print('hello')")

    return zip_buffer.getvalue()


@pytest.fixture
def binder_vre(dummy_binder_crate):
    """Create a Binder VRE instance with proper RequestPackage."""
    package = ROCrateFactory.create_from_dict(dummy_binder_crate.get_rocrate_dict())

    vre = VREBinder(
        request_package=package,
        token="test-token",
        request_id=0,
        update_state=None,
        body=create_test_zip_body(),
    )
    vre.svc_url = "https://mybinder.org"
    return vre


@pytest.fixture
def valid_rocrate_dict():
    """Minimal valid RO-Crate dict with Galaxy workflow."""
    return {
        "@context": "https://w3id.org/ro/crate/1.1/context",
        "@graph": [
            {
                "@id": "./",
                "@type": "Dataset",
                "mainEntity": {"@id": "#workflow"},
                "hasPart": [{"@id": "#workflow"}],
            },
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "about": {"@id": "./"},
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
            },
            {
                "@id": "#galaxy-lang",
                "@type": "ComputerLanguage",
                "identifier": {"@id": "https://galaxyproject.org/"},
                "name": "Galaxy",
            },
            {
                "@id": "#workflow",
                "@type": "SoftwareApplication",
                "url": "https://example.com/workflow",
                "programmingLanguage": {"@id": "#galaxy-lang"},
            },
        ],
    }


@pytest.fixture
def sciencemesh_rocrate():
    """Load ScienceMesh ROCrate from test fixtures directory."""
    test_dir = Path(os.path.abspath(__file__))
    metadata_dir = test_dir.parent.joinpath("sciencemesh")
    return ROCrateFactory.create_from_file(str(metadata_dir))


@pytest.fixture
def sciencemesh_vre(sciencemesh_rocrate):
    """Create a ScienceMesh VRE instance."""
    vre = VREScienceMesh(
        request_package=sciencemesh_rocrate,
        token="test-token",
        request_id=0,
        update_state=None,
    )
    vre.svc_url = "https://sciencemesh.example.org"
    return vre


@pytest.fixture
def ocm_share_request(sciencemesh_vre):
    """Create expected OCM share request for test assertions."""
    receiver = sciencemesh_vre.request_package.get_custom_entity_info("#receiver")
    owner = sciencemesh_vre.request_package.get_custom_entity_info("#owner")
    sender = sciencemesh_vre.request_package.get_custom_entity_info("#sender")

    sender_userid = sender.userid
    if sender_userid and "@" in sender_userid:
        sender_userid = sender_userid.split("@")[0] + "@" + settings.host

    crate_metadata = sciencemesh_vre.request_package.get_crate_metadata()

    return {
        "shareWith": receiver.userid,
        "name": crate_metadata.name,
        "description": crate_metadata.description,
        "providerId": "n/a",
        "resourceId": "n/a",
        "owner": owner.userid,
        "senderDisplayName": sender.name,
        "sender": sender_userid,
        "resourceType": "embedded",
        "shareType": "user",
        "protocol": {
            "name": "multi",
            "embedded": {
                "payload": sciencemesh_vre.request_package.generate_metadata()
            },
        },
    }


@pytest.fixture
def mock_requests_post():
    """Mock for requests.post calls."""
    with patch("requests.post") as _mock:
        yield _mock
