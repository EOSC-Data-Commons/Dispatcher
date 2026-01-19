# test/unit/test_galaxy.py
import pytest
import requests_mock
from app import constants
from app.exceptions import GalaxyAPIError, WorkflowURLError
from fixtures.dummy_crate import DummyEntity, DummyCrate, WORKFLOW_URL
from app.exceptions import WorkflowURLError


# TODO FILE1, FILE2 move somewhere else, split to 2 tests
def test_prepare_workflow_data_success(galaxy_vre):
    """_prepare_workflow_data must return the exact dict that Galaxy expects."""
    payload = galaxy_vre._prepare_workflow_data()
    assert payload["public"] is constants.GALAXY_PUBLIC_DEFAULT
    assert payload["workflow_target_type"] == constants.GALAXY_WORKFLOW_TARGET_TYPE
    assert payload["workflow_id"] == WORKFLOW_URL

    # The request_state must contain both files, correctly transformed
    request_state = payload["request_state"]
    assert set(request_state.keys()) == {"sample1.fastq", "sample2.fastq"}
    for spec in request_state.values():
        assert spec["class"] == "File"
        assert spec["filetype"] == "fastq"
        assert spec["location"].endswith(".fastq")


def test_prepare_workflow_onedata_success(galaxy_vre_onedata):
    """_prepare_workflow_data must return the exact dict that Galaxy expects."""
    payload = galaxy_vre_onedata._prepare_workflow_data()

    request_state = payload["request_state"]

    assert request_state["onedata_file"]["filetype"] == "tiff"
    assert (
        request_state["onedata_file"]["location"]
        == "https://demo.onedata.org/api/v3/onezone/shares/data/00000000007EADF3736861726547756964233964613065396530393037303130393062356433623965356632643832353138636830386464233665366232326436663332623633646233346663666163353365353265323333636864386261233437656434633633333638393264396361626239316435636430623161663436636830343438/content"
    )


def test_post_happy_path(galaxy_vre, requests_mock):
    data = {"uuid": "final-uuid-42"}
    requests_mock.post(
        galaxy_vre._get_api_url(),
        headers=galaxy_vre._get_headers(),
        status_code=201,
        json=data,
    )

    final_url = galaxy_vre.post()

    assert (
        final_url
        == f"{constants.GALAXY_DEFAULT_SERVICE}workflow_landings/final-uuid-42?public=False"
    )


def test_missing_workflow_url_causes_exception(galaxy_vre):
    missing_url = DummyEntity(_type="Dataset")  # no url
    galaxy_vre.crate = DummyCrate(main_entity=missing_url)

    with pytest.raises(WorkflowURLError):
        galaxy_vre.post()


def test_missing_uuid_in_response_causes_exception(galaxy_vre, requests_mock):
    """When the API response does not contain a UUID, ``post`` raises GalaxyAPIError."""
    empty_response = {}

    requests_mock.post(
        galaxy_vre._get_api_url(),
        headers=galaxy_vre._get_headers(),
        status_code=201,
        json=empty_response,
    )

    with pytest.raises(GalaxyAPIError):
        galaxy_vre.post()


def test_api_error_causes_custom_exception(galaxy_vre, requests_mock):
    """When the API fails, ``post`` raises GalaxyAPIError."""
    requests_mock.post(galaxy_vre._get_api_url(), status_code=400)

    with pytest.raises(GalaxyAPIError):
        galaxy_vre.post()
