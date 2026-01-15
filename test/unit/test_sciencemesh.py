import pytest
import requests_mock
from rocrate.rocrate import ROCrate
from app.exceptions import MissingOCMParameters, ScienceMeshAPIError
from pathlib import Path
import os


def test_missing_uuid_in_response_causes_exception(sciencemesh_vre):
    """"""
    sciencemesh_vre.crate = ROCrate()

    with pytest.raises(MissingOCMParameters):
        sciencemesh_vre.post()


def test_reading_example_rocrate(sciencemesh_vre, requests_mock):
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


def test_post_fails_without_receiver_entity(sciencemesh_vre, sciencemesh_rocrate):
    sciencemesh_vre.crate = ROCrate(sciencemesh_rocrate)
    sciencemesh_vre.crate.delete("#receiver")

    with pytest.raises(MissingOCMParameters):
        sciencemesh_vre.post()


def test_post_fails_without_owner_entity(sciencemesh_vre, sciencemesh_rocrate):
    sciencemesh_vre.crate = ROCrate(sciencemesh_rocrate)
    sciencemesh_vre.crate.delete("#owner")

    with pytest.raises(MissingOCMParameters):
        sciencemesh_vre.post()


def test_post_fails_without_sender_entity(sciencemesh_vre, sciencemesh_rocrate):
    sciencemesh_vre.crate = ROCrate(sciencemesh_rocrate)
    sciencemesh_vre.crate.delete("#sender")

    with pytest.raises(MissingOCMParameters):
        sciencemesh_vre.post()


def test_post_succeeds_without_destination_entity(sciencemesh_vre, requests_mock):
    sciencemesh_vre.crate.delete("#destination")
    requests_mock.post(
        f"{sciencemesh_vre.svc_url}/ocm/shares",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        status_code=200,
        json={},
    )
    assert sciencemesh_vre.post() == {}


def test_post_succeeds_sends_correct_request(
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
