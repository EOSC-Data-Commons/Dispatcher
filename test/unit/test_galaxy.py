# test/unit/test_galaxy.py
import pytest
import requests_mock
from app import constants
from app.exceptions import GalaxyAPIError, WorkflowURLError
from fixtures.dummy_crate import DummyEntity, DummyCrate, WORKFLOW_URL
from app.exceptions import WorkflowURLError


# TODO FILE1, FILE2 move somewhere else
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
