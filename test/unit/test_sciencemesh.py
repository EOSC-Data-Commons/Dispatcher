import uuid
import pytest
from app.exceptions import MissingOCMParameters, ScienceMeshAPIError


def test_post_errors_with_empty_rocrate(sciencemesh_vre):
    sciencemesh_vre.request_package.ocm_data = None

    with pytest.raises(MissingOCMParameters):
        sciencemesh_vre.post()


def test_post_errors_without_receiver_entity(sciencemesh_vre):
    sciencemesh_vre.request_package.ocm_data.receiver_userid = None

    with pytest.raises(MissingOCMParameters):
        sciencemesh_vre.post()


def test_post_errors_without_owner_entity(sciencemesh_vre):
    sciencemesh_vre.request_package.ocm_data.owner_userid = None

    with pytest.raises(MissingOCMParameters):
        sciencemesh_vre.post()


def test_post_errors_without_sender_entity(sciencemesh_vre):
    sciencemesh_vre.request_package.ocm_data.sender_userid = None

    with pytest.raises(MissingOCMParameters):
        sciencemesh_vre.post()


def test_post_errors_on_invalid_api_response(sciencemesh_vre, requests_mock):
    requests_mock.post(
        f"{sciencemesh_vre.svc_url}/ocm/shares",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        status_code=400,
    )

    with pytest.raises(ScienceMeshAPIError):
        sciencemesh_vre.post()


def test_post_returns_svc_url(sciencemesh_vre, requests_mock):
    json = {"data": "value"}

    requests_mock.post(
        f"{sciencemesh_vre.svc_url}/ocm/shares",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        status_code=200,
        json=json,
    )

    assert sciencemesh_vre.post() == sciencemesh_vre.svc_url


def test_post_succeeds_without_destination_entity(sciencemesh_vre, requests_mock):
    json = {"data": "value"}

    requests_mock.post(
        f"{sciencemesh_vre.svc_url}/ocm/shares",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        status_code=200,
        json=json,
    )
    assert sciencemesh_vre.post() == sciencemesh_vre.svc_url


def test_post_sends_correct_ocm_share_request(
    sciencemesh_vre, requests_mock, ocm_share_request
):
    requests_mock.post(
        f"{sciencemesh_vre.svc_url}/ocm/shares",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        status_code=200,
        json={},
    )
    sciencemesh_vre.post()

    actual = requests_mock.request_history[0].json()

    for key in ("providerId", "resourceId"):
        uuid.UUID(actual.pop(key))
        ocm_share_request.pop(key, None)

    assert actual == ocm_share_request
