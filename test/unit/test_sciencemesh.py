"""Unit tests for ScienceMesh VRE."""

import pytest
from app.domain.rocrate import ROCrateFactory
from app.exceptions import MissingOCMParameters, ScienceMeshAPIError
from fixtures.dummy_crate import DummyEntity, DummyCrate


def _make_sciencemesh_package(
    *, receiver=True, owner=True, sender=True, destination=True
):
    """Create a RequestPackage for ScienceMesh testing with configurable entities.

    Args:
        receiver: Include #receiver entity.
        owner: Include #owner entity.
        sender: Include #sender entity.
        destination: Include #destination entity.

    Returns:
        RequestPackage instance.
    """
    lang = DummyEntity(
        _id="#sciencemesh-jupyter",
        _type="ComputerLanguage",
        identifier={"@id": "https://qa.cernbox.cern.ch"},
    )
    main = DummyEntity(
        _id="#workflow",
        _type=["File", "SoftwareSourceCode", "ComputationalWorkflow"],
        name="test-notebook.ipynb",
        programmingLanguage={"@id": "#sciencemesh-jupyter"},
    )

    extra_entities = []
    if receiver:
        extra_entities.append(
            DummyEntity(
                _id="#receiver",
                _type="Person",
                userid="receiver@example.com",
            )
        )
    if owner:
        extra_entities.append(
            DummyEntity(
                _id="#owner",
                _type="Person",
                userid="owner@example.com",
            )
        )
    if sender:
        extra_entities.append(
            DummyEntity(
                _id="#sender",
                _type="Person",
                name="Sender Name",
                userid="sender@example.com",
            )
        )
    if destination:
        extra_entities.append(
            DummyEntity(
                _id="#destination",
                _type="Service",
                url="https://example.com",
            )
        )

    crate = DummyCrate(
        main_entity=main,
        other_entities=extra_entities,
        language_entity=lang,
    )
    return ROCrateFactory.create_from_dict(crate.get_rocrate_dict())


def _make_sciencemesh_vre(package):
    """Create a VREScienceMesh instance with the given package."""
    from app.vres.sciencemesh import VREScienceMesh

    vre = VREScienceMesh(
        request_package=package,
        token="test-token",
        request_id=0,
        update_state=None,
    )
    vre.svc_url = "https://sciencemesh.example.org"
    return vre


def test_post_errors_with_empty_rocrate():
    """post() should raise MissingOCMParameters when no entities are present."""
    package = _make_sciencemesh_package(
        receiver=False, owner=False, sender=False, destination=False
    )
    vre = _make_sciencemesh_vre(package)

    with pytest.raises(MissingOCMParameters):
        vre.post()


def test_post_errors_without_receiver_entity():
    """post() should raise MissingOCMParameters when #receiver is missing."""
    package = _make_sciencemesh_package(receiver=False)
    vre = _make_sciencemesh_vre(package)

    with pytest.raises(MissingOCMParameters):
        vre.post()


def test_post_errors_without_owner_entity():
    """post() should raise MissingOCMParameters when #owner is missing."""
    package = _make_sciencemesh_package(owner=False)
    vre = _make_sciencemesh_vre(package)

    with pytest.raises(MissingOCMParameters):
        vre.post()


def test_post_errors_without_sender_entity():
    """post() should raise MissingOCMParameters when #sender is missing."""
    package = _make_sciencemesh_package(sender=False)
    vre = _make_sciencemesh_vre(package)

    with pytest.raises(MissingOCMParameters):
        vre.post()


def test_post_errors_on_invalid_api_response(sciencemesh_vre, requests_mock):
    """post() should raise ScienceMeshAPIError on 400 response."""
    requests_mock.post(
        f"{sciencemesh_vre.svc_url}/ocm/shares",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        status_code=400,
    )

    with pytest.raises(ScienceMeshAPIError):
        sciencemesh_vre.post()


def test_post_returns_json(sciencemesh_vre, requests_mock):
    """post() should return the JSON response on success."""
    json = {"data": "value"}

    requests_mock.post(
        f"{sciencemesh_vre.svc_url}/ocm/shares",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        status_code=200,
        json=json,
    )

    assert sciencemesh_vre.post() == json


def test_post_succeeds_without_destination_entity(sciencemesh_vre, requests_mock):
    """post() should succeed even without #destination entity."""
    json = {"data": "value"}
    # Create a package without destination entity
    package = _make_sciencemesh_package(destination=False)
    vre = _make_sciencemesh_vre(package)

    requests_mock.post(
        f"{vre.svc_url}/ocm/shares",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        status_code=200,
        json=json,
    )
    assert vre.post() == json


def test_post_sends_correct_ocm_share_request(
    sciencemesh_vre, requests_mock, ocm_share_request
):
    """post() should send the correct OCM share request payload."""
    requests_mock.post(
        f"{sciencemesh_vre.svc_url}/ocm/shares",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        status_code=200,
        json={},
    )
    sciencemesh_vre.post()

    assert requests_mock.request_history[0].json() == ocm_share_request
