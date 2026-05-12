import pytest
from app.exceptions import MissingOCMParameters, ScienceMeshAPIError


def _remove_entity(package, entity_id: str):
    """Remove an entity from the raw_crate @graph."""
    graph = package.raw_crate.get("@graph", [])
    package.raw_crate["@graph"] = [
        item for item in graph if item.get("@id") != entity_id
    ]


def test_post_errors_with_empty_rocrate(sciencemesh_vre):
    sciencemesh_vre.request_package.raw_crate = {"@graph": []}

    with pytest.raises(MissingOCMParameters):
        sciencemesh_vre.post()


def test_post_errors_without_receiver_entity(sciencemesh_vre):
    _remove_entity(sciencemesh_vre.request_package, "#receiver")

    with pytest.raises(MissingOCMParameters):
        sciencemesh_vre.post()


def test_post_errors_without_owner_entity(sciencemesh_vre):
    _remove_entity(sciencemesh_vre.request_package, "#owner")

    with pytest.raises(MissingOCMParameters):
        sciencemesh_vre.post()


def test_post_errors_without_sender_entity(sciencemesh_vre):
    _remove_entity(sciencemesh_vre.request_package, "#sender")

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


def test_post_returns_json(sciencemesh_vre, requests_mock):
    json = {"data": "value"}

    requests_mock.post(
        f"{sciencemesh_vre.svc_url}/ocm/shares",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        status_code=200,
        json=json,
    )

    assert sciencemesh_vre.post() == json


def test_post_succeeds_without_destination_entity(sciencemesh_vre, requests_mock):
    json = {"data": "value"}
    _remove_entity(sciencemesh_vre.request_package, "#destination")

    requests_mock.post(
        f"{sciencemesh_vre.svc_url}/ocm/shares",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        status_code=200,
        json=json,
    )
    assert sciencemesh_vre.post() == json


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

    assert requests_mock.request_history[0].json() == ocm_share_request
