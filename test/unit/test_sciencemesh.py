import uuid
from unittest.mock import patch
import pytest
from app.exceptions import (
    MissingOCMParameters,
    ScienceMeshAPIError,
    VREAuthenticationError,
)


async def test_post_errors_with_empty_rocrate(sciencemesh_vre, mock_token_user):
    sciencemesh_vre.payload.workflow_inputs = []

    with pytest.raises(MissingOCMParameters):
        await sciencemesh_vre.post()


async def test_post_errors_without_receiver_entity(sciencemesh_vre, mock_token_user):
    sciencemesh_vre.payload.workflow_inputs[0].default_value = None

    with pytest.raises(MissingOCMParameters):
        await sciencemesh_vre.post()


async def test_post_errors_on_invalid_api_response(
    sciencemesh_vre, httpx_mock, mock_token_user
):
    httpx_mock.add_response(
        method="POST",
        url=f"{sciencemesh_vre.svc_url}/ocm/shares",
        status_code=400,
    )

    with pytest.raises(ScienceMeshAPIError):
        await sciencemesh_vre.post()


async def test_post_returns_svc_url(sciencemesh_vre, httpx_mock, mock_token_user):
    json = {"data": "value"}

    httpx_mock.add_response(
        method="POST",
        url=f"{sciencemesh_vre.svc_url}/ocm/shares",
        status_code=200,
        json=json,
    )

    assert (
        await sciencemesh_vre.post()
        == sciencemesh_vre.svc_url + sciencemesh_vre.SERVICE_DEEP_LINK
    )


async def test_post_succeeds_without_destination_entity(
    sciencemesh_vre, httpx_mock, mock_token_user
):
    json = {"data": "value"}

    httpx_mock.add_response(
        method="POST",
        url=f"{sciencemesh_vre.svc_url}/ocm/shares",
        status_code=200,
        json=json,
    )
    assert (
        await sciencemesh_vre.post()
        == sciencemesh_vre.svc_url + sciencemesh_vre.SERVICE_DEEP_LINK
    )


async def test_post_sends_correct_ocm_share_request(
    sciencemesh_vre, httpx_mock, ocm_share_request, mock_token_user
):
    import json as _json

    httpx_mock.add_response(
        method="POST",
        url=f"{sciencemesh_vre.svc_url}/ocm/shares",
        status_code=200,
        json={},
    )
    await sciencemesh_vre.post()

    actual = _json.loads(httpx_mock.get_requests()[0].read())

    for key in ("providerId", "resourceId"):
        uuid.UUID(actual.pop(key))
        ocm_share_request.pop(key, None)

    assert actual == ocm_share_request


async def test_resource_id_is_deterministic_from_crate(
    sciencemesh_vre, mock_token_user
):
    """Same crate → same resourceId; different crate → different resourceId."""
    from app.vres.sciencemesh import VREScienceMesh
    import copy

    vre = sciencemesh_vre
    rid1 = (await vre.create_ocm_share_request())["resourceId"]
    rid2 = (await vre.create_ocm_share_request())["resourceId"]
    assert rid1 == rid2
    assert uuid.UUID(rid1)  # still uuid-formatted

    mutated = copy.deepcopy(vre.payload.raw_crate)
    mutated["@graph"][0]["name"] = "different title"
    other = VREScienceMesh(
        token="test-access-token",
        request_id=0,
        status_store=None,
        payload=type(vre.payload)(
            vre_type=vre.payload.vre_type,
            programming_language=vre.payload.programming_language,
            workflow=vre.payload.workflow,
            workflow_inputs=vre.payload.workflow_inputs,
            raw_crate=mutated,
        ),
    )
    assert (await other.create_ocm_share_request())["resourceId"] != rid1


async def test_create_ocm_share_uses_token_claims_for_owner_and_sender(
    sciencemesh_vre, mock_token_user
):
    result = await sciencemesh_vre.create_ocm_share_request()

    assert result["owner"] == "user@egi.eu"
    assert result["senderDisplayName"] == "ScienceMesh User"
    assert result["sender"].startswith("user@egi.eu@")


async def test_create_ocm_share_falls_back_name_to_email(
    sciencemesh_vre, mock_token_user
):
    from app.vres.utils.token_utils import TokenUser

    mock_token_user.return_value = TokenUser(
        sub="jdoe@example.com",
        name=None,
    )

    result = await sciencemesh_vre.create_ocm_share_request()

    assert result["owner"] == "jdoe@example.com"
    assert result["senderDisplayName"] == "jdoe@example.com"
    assert result["sender"].startswith("jdoe@example.com@")


async def test_token_extraction_raises_on_failure(sciencemesh_vre, mock_token_user):
    mock_token_user.side_effect = VREAuthenticationError("Token validation failed")

    with pytest.raises(VREAuthenticationError):
        await sciencemesh_vre.post()


async def test_token_extraction_raises_on_missing_email(
    sciencemesh_vre, mock_token_user
):
    mock_token_user.side_effect = VREAuthenticationError(
        "Missing 'email' in user identity from EGI Check-in"
    )

    with pytest.raises(VREAuthenticationError):
        await sciencemesh_vre.post()
