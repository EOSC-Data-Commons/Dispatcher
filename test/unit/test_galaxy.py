# test/unit/test_galaxy.py
import pytest
import requests
from unittest.mock import Mock
from  app.vres import constants 
from app.exceptions import GalaxyAPIError, WorkflowURLError


def test_get_default_service():
    from app.vres.galaxy import VREGalaxy
    assert VREGalaxy().get_default_service() == constants.GALAXY_DEFAULT_SERVICE


def test_prepare_workflow_data_success(galaxy_vre):
    """_prepare_workflow_data must return the exact dict that Galaxy expects."""
    payload = galaxy_vre._prepare_workflow_data()
    assert payload["public"] is constants.GALAXY_PUBLIC_DEFAULT
    assert payload["workflow_target_type"] == constants.GALAXY_WORKFLOW_TARGET_TYPE
    assert payload["workflow_id"] == "https://workflow.example.org/myworkflow.ga"

    # The request_state must contain both files, correctly transformed
    request_state = payload["request_state"]
    assert set(request_state.keys()) == {"sample1.fastq", "sample2.fastq"}
    for name, spec in request_state.items():
        assert spec["class"] == "File"
        assert spec["filetype"] == "fastq"
        assert spec["location"].endswith(".fastq")


def test_get_workflow_url_missing():
    """When the workflow entity does not provide a URL the VRE raises."""
    from app.vres.galaxy import VREGalaxy
    from app.exceptions import WorkflowURLError

    # Crate with a main entity that *doesn't* have a `url` attribute
    broken = DummyEntity(_type="Dataset")          # no url key
    crate = DummyCrate(main_entity=broken)

    vre = VREGalaxy()
    vre.crate = crate

    with pytest.raises(WorkflowURLError) as exc:
        vre._get_workflow_url()
    assert "Missing url in workflow entity" in str(exc.value)


def test_send_workflow_request_success(galaxy_vre, mock_requests_post):
    """A happy‑path POST should return the decoded JSON payload."""
    dummy_response = {"uuid": "abcdef-12345"}

    # Configure the mock ``requests.post`` to behave like a successful response
    mock_resp = Mock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = dummy_response
    mock_requests_post.return_value = mock_resp

    data = {"dummy": "payload"}
    result = galaxy_vre._send_workflow_request(data)

    # Verify that we called the right URL with the right headers + payload
    expected_url = f"{constants.GALAXY_DEFAULT_SERVICE}api/workflow_landings"
    mock_requests_post.assert_called_once_with(
        expected_url,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        json=data,
    )
    assert result == dummy_response


def test_send_workflow_request_http_error(galaxy_vre, mock_requests_post):
    """Any RequestException must be wrapped in GalaxyAPIError."""
    mock_requests_post.side_effect = requests.RequestException("boom")

    with pytest.raises(GalaxyAPIError) as exc:
        galaxy_vre._send_workflow_request({"foo": "bar"})
    assert "Galaxy API call failed" in str(exc.value)


def test_extract_landing_id_success(galaxy_vre):
    """UUID extraction works when present."""
    payload = {"uuid": "my-landing-id"}
    assert galaxy_vre._extract_landing_id(payload) == "my-landing-id"


def test_extract_landing_id_missing(galaxy_vre):
    """Missing UUID raises GalaxyAPIError."""
    with pytest.raises(GalaxyAPIError):
        galaxy_vre._extract_landing_id({})


def test_build_final_url(galaxy_vre):
    """The final URL must contain the landing id and the public flag (False)."""
    landing_id = "deadbeef-1234"
    expected = f"{constants.GALAXY_DEFAULT_SERVICE}workflow_landings/deadbeef-1234?public=False"
    assert galaxy_vre._build_final_url(landing_id) == expected


def test_post_happy_path(galaxy_vre, mock_requests_post):
    """
    End‑to‑end of the public ``post`` method while still mocking the HTTP call.
    """
    # --- arrange --------------------------------------------------------
    # 1️⃣ payload that _prepare_workflow_data will produce
    payload = galaxy_vre._prepare_workflow_data()

    # 2️⃣ mock the HTTP response
    mock_resp = Mock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"uuid": "final-uuid-42"}
    mock_requests_post.return_value = mock_resp

    # --- act -----------------------------------------------------------
    final_url = galaxy_vre.post()

    # --- assert --------------------------------------------------------
    # 1️⃣ the HTTP request was performed exactly once
    mock_requests_post.assert_called_once()
    # 2️⃣ the final URL is correctly assembled
    assert final_url == f"{constants.GALAXY_DEFAULT_SERVICE}workflow_landings/final-uuid-42?public=False"


def test_post_propagates_missing_workflow_url(galaxy_vre):
    """If the crate is malformed, the exception bubbles up unchanged."""
    # replace the crate with one that lacks a workflow URL
    broken = DummyEntity(_type="Dataset")          # no url
    galaxy_vre.crate = DummyCrate(main_entity=broken)

    with pytest.raises(WorkflowURLError):
        galaxy_vre.post()


def test_post_propagates_missing_uuid(galaxy_vre, mock_requests_post):
    """When the API response does not contain a UUID, ``post`` raises GalaxyAPIError."""
    mock_resp = Mock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"some": "thing"}   # no uuid
    mock_requests_post.return_value = mock_resp

    with pytest.raises(GalaxyAPIError):
        galaxy_vre.post()