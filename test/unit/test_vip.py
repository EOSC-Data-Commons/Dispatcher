"""Test VIP VRE"""

import pytest
from unittest.mock import MagicMock, patch
from vre_rocrate import VIP_PROGRAMMING_LANGUAGE
from app.constants import VIP_DEFAULT_SERVICE
from app.vres.vip import VREVIP
from app.exceptions import VREConfigurationError, ExternalServiceError
from vre_rocrate import (
    RequestPackage,
    WorkflowDescriptor,
    FileReference,
)


@pytest.fixture
def vip_request_package():
    return RequestPackage(
        vre_type=VIP_PROGRAMMING_LANGUAGE,
        programming_language=VIP_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(
            id="https://vip.creatis.insa-lyon.fr/rest/pipelines/CQUEST/0.6",
            url="https://vip.creatis.insa-lyon.fr/rest/pipelines/CQUEST/0.6",
            type="SoftwareSourceCode",
        ),
        files=[
            FileReference(
                id="https://www.creatis.insa-lyon.fr/~abonnet/quest_param_117T_A.txt",
                name="parameter_file",
                encoding_format="text/plain",
                url="https://www.creatis.insa-lyon.fr/~abonnet/quest_param_117T_A.txt",
            ),
            FileReference(
                id="https://www.creatis.insa-lyon.fr/~abonnet/Rec003_Vox1.mrui",
                name="data_file",
                encoding_format="application/octet-stream",
                url="https://www.creatis.insa-lyon.fr/~abonnet/Rec003_Vox1.mrui",
            ),
            FileReference(
                id="https://www.creatis.insa-lyon.fr/~abonnet/basis_11_7.zip",
                name="zipped_folder",
                encoding_format="application/zip",
                url="https://www.creatis.insa-lyon.fr/~abonnet/basis_11_7.zip",
            ),
        ],
        raw_crate={},
    )


@patch("app.vres.vip.requests.post")
def test_post_success(mock_post, vip_request_package):
    """Test VIP VRE post function returns /home on success."""
    mock_post.return_value.status_code = 200

    vrevip = VREVIP(
        token="dummy_token",
        request_id=42,
        update_state=None,
        request_package=vip_request_package,
    )

    result = vrevip.post()
    assert result == f"{VIP_DEFAULT_SERVICE}/home"

    assert mock_post.call_count == 1
    call_args = mock_post.call_args_list[0]
    assert call_args[0][0] == f"{VIP_DEFAULT_SERVICE}/rest/executions"
    assert "apikey" in call_args[1]["headers"]
    assert call_args[1]["headers"]["Content-Type"] == "application/json"

    payload = call_args[1]["json"]
    assert payload["name"] == "vip-execution-42"
    assert payload["pipelineIdentifier"] == "CQUEST/0.6"
    assert payload["resultsLocation"] == "/vip/Home"
    assert payload["inputValues"] == {
        "parameter_file": "https://www.creatis.insa-lyon.fr/~abonnet/quest_param_117T_A.txt",
        "data_file": "https://www.creatis.insa-lyon.fr/~abonnet/Rec003_Vox1.mrui",
        "zipped_folder": "https://www.creatis.insa-lyon.fr/~abonnet/basis_11_7.zip",
    }


def test_missing_pipeline_identifier():
    """Test VREConfigurationError raised when workflow URL is missing."""
    request_package = RequestPackage(
        vre_type=VIP_PROGRAMMING_LANGUAGE,
        programming_language=VIP_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(id="#wf", type="SoftwareSourceCode"),
        raw_crate={},
    )
    vrevip = VREVIP(
        token="dummy_token",
        request_id=0,
        update_state=None,
        request_package=request_package,
    )

    with pytest.raises(VREConfigurationError) as exc:
        vrevip._get_pipeline_identifier()
    assert "Missing pipelineIdentifier" in str(exc.value)


@patch("app.vres.vip.requests.post")
def test_api_error(mock_post, vip_request_package):
    """Test ExternalServiceError raised when VIP API returns an error."""
    mock_post.return_value.status_code = 500
    mock_post.return_value.text = "Internal Server Error"
    mock_post.return_value.raise_for_status.side_effect = __import__(
        "requests"
    ).HTTPError("500 Server Error")

    vrevip = VREVIP(
        token="dummy_token",
        request_id=0,
        update_state=None,
        request_package=vip_request_package,
    )

    with pytest.raises(ExternalServiceError) as exc:
        vrevip.post()
    assert "VIP API call failed" in str(exc.value)


def test_get_default_service():
    """Test get_default_service returns VIP_DEFAULT_SERVICE."""
    vrevip = VREVIP(
        token="dummy_token",
        request_id=0,
        update_state=None,
        request_package=None,
    )
    assert vrevip.get_default_service() == VIP_DEFAULT_SERVICE


def test_input_values_mapping(vip_request_package):
    """Test _map_input_values correctly maps file names to URLs."""
    vrevip = VREVIP(
        token="dummy_token",
        request_id=0,
        update_state=None,
        request_package=vip_request_package,
    )

    result = vrevip._map_input_values()
    assert result == {
        "parameter_file": "https://www.creatis.insa-lyon.fr/~abonnet/quest_param_117T_A.txt",
        "data_file": "https://www.creatis.insa-lyon.fr/~abonnet/Rec003_Vox1.mrui",
        "zipped_folder": "https://www.creatis.insa-lyon.fr/~abonnet/basis_11_7.zip",
    }


def test_input_values_fallback_to_id():
    """Test _map_input_values falls back to file id when url is None."""
    request_package = RequestPackage(
        vre_type=VIP_PROGRAMMING_LANGUAGE,
        programming_language=VIP_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(
            id="#workflow",
            type="SoftwareSourceCode",
            url="CQUEST/0.6",
        ),
        files=[
            FileReference(
                id="local-file-id",
                name="local_file",
                encoding_format="text/plain",
                url=None,
            ),
        ],
        raw_crate={},
    )
    vrevip = VREVIP(
        token="dummy_token",
        request_id=0,
        update_state=None,
        request_package=request_package,
    )

    result = vrevip._map_input_values()
    assert result == {"local_file": "local-file-id"}
