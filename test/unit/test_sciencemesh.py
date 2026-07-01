import uuid
from unittest.mock import patch
import pytest
from app.exceptions import (
    MissingOCMParameters,
    ScienceMeshAPIError,
    VREAuthenticationError,
)


def test_post_errors_with_empty_rocrate(sciencemesh_vre, mock_token_user):
    sciencemesh_vre.request_package.ocm_data = None

    with pytest.raises(MissingOCMParameters):
        sciencemesh_vre.post()


def test_post_errors_without_receiver_entity(sciencemesh_vre, mock_token_user):
    sciencemesh_vre.request_package.ocm_data.receiver_userid = None

    with pytest.raises(MissingOCMParameters):
        sciencemesh_vre.post()


def test_post_errors_on_invalid_api_response(
    sciencemesh_vre, requests_mock, mock_token_user
):
    requests_mock.post(
        f"{sciencemesh_vre.svc_url}/ocm/shares",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        status_code=400,
    )

    with pytest.raises(ScienceMeshAPIError):
        sciencemesh_vre.post()


def test_post_returns_svc_url(sciencemesh_vre, requests_mock, mock_token_user):
    json = {"data": "value"}

    requests_mock.post(
        f"{sciencemesh_vre.svc_url}/ocm/shares",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        status_code=200,
        json=json,
    )

    assert sciencemesh_vre.post() == sciencemesh_vre.svc_url


def test_post_succeeds_without_destination_entity(
    sciencemesh_vre, requests_mock, mock_token_user
):
    json = {"data": "value"}

    requests_mock.post(
        f"{sciencemesh_vre.svc_url}/ocm/shares",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        status_code=200,
        json=json,
    )
    assert sciencemesh_vre.post() == sciencemesh_vre.svc_url


def test_post_sends_correct_ocm_share_request(
    sciencemesh_vre, requests_mock, ocm_share_request, mock_token_user
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


def test_create_ocm_share_uses_token_claims_for_owner_and_sender(
    sciencemesh_vre, mock_token_user
):
    result = sciencemesh_vre.create_ocm_share_request()

    assert result["owner"] == "rasmus.oscar.welander@egi.eu"
    assert result["senderDisplayName"] == "Rasmus Oscar Welander"
    assert result["sender"].startswith("rasmus.oscar.welander@egi.eu@")


def test_create_ocm_share_falls_back_name_to_email(sciencemesh_vre, mock_token_user):
    from app.services.token_utils import TokenUser

    mock_token_user.return_value = TokenUser(
        email="jdoe@example.com",
        name=None,
    )

    result = sciencemesh_vre.create_ocm_share_request()

    assert result["owner"] == "jdoe@example.com"
    assert result["senderDisplayName"] == "jdoe@example.com"
    assert result["sender"].startswith("jdoe@example.com@")


def test_token_extraction_raises_on_failure(sciencemesh_vre, mock_token_user):
    mock_token_user.side_effect = VREAuthenticationError("Token validation failed")

    with pytest.raises(VREAuthenticationError):
        sciencemesh_vre.post()


def test_token_extraction_raises_on_missing_email(sciencemesh_vre, mock_token_user):
    mock_token_user.side_effect = VREAuthenticationError(
        "Missing 'email' in user identity from EGI Check-in"
    )

    with pytest.raises(VREAuthenticationError):
        sciencemesh_vre.post()
