"""Test VIP VRE"""

import pytest
from unittest.mock import patch
from vre_rocrate import VIP_PROGRAMMING_LANGUAGE
from app.constants import VIP_DEFAULT_SERVICE
from app.vres.vip import VREVIP
from app.exceptions import VREConfigurationError, ExternalServiceError
from vre_rocrate import (
    VREPayload,
    WorkflowDescriptor,
    FileReference,
    FormalParameter,
)


@pytest.fixture
def vip_payload():
    return VREPayload(
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
        workflow_inputs=[
            FormalParameter(
                id="#input-parameter_file",
                name="parameter_file",
                default_value={
                    "@id": "https://www.creatis.insa-lyon.fr/~abonnet/quest_param_117T_A.txt"
                },
            ),
            FormalParameter(
                id="#input-data_file",
                name="data_file",
                default_value={
                    "@id": "https://www.creatis.insa-lyon.fr/~abonnet/Rec003_Vox1.mrui"
                },
            ),
            FormalParameter(
                id="#input-zipped_folder",
                name="zipped_folder",
                default_value={
                    "@id": "https://www.creatis.insa-lyon.fr/~abonnet/basis_11_7.zip"
                },
            ),
        ],
        raw_crate={},
    )


@pytest.fixture
def mock_vault_key():
    """Mock vault_get_api_key to return a test key."""
    with patch("app.vres.vip.vault_get_api_key", return_value="test_api_key_123") as m:
        yield m


@patch("app.vres.vip.requests.post")
def test_post_success(mock_post, vip_payload, mock_vault_key):
    """Test VIP VRE post function returns /home on success."""
    mock_post.return_value.status_code = 200

    vrevip = VREVIP(
        token="dummy_token",
        request_id=42,
        update_state=None,
        payload=vip_payload,
    )

    result = vrevip.post()
    assert result == f"{VIP_DEFAULT_SERVICE}/home.html"

    mock_vault_key.assert_called_once_with("dummy_token", "vip")

    assert mock_post.call_count == 1
    call_args = mock_post.call_args_list[0]
    assert call_args[0][0] == f"{VIP_DEFAULT_SERVICE}/rest/executions"
    assert call_args[1]["headers"]["apikey"] == "test_api_key_123"
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


def test_vault_key_not_found(vip_payload):
    """Test VREConfigurationError raised when vault does not contain the key."""
    vrevip = VREVIP(
        token="dummy_token",
        request_id=0,
        update_state=None,
        payload=vip_payload,
    )

    with patch(
        "app.vres.vip.vault_get_api_key",
        side_effect=VREConfigurationError("Secret 'vip' not found in vault"),
    ):
        with pytest.raises(VREConfigurationError) as exc:
            vrevip.post()
        assert "not found in vault" in str(exc.value)


def test_missing_pipeline_identifier():
    """Test VREConfigurationError raised when workflow URL is missing."""
    payload = VREPayload(
        vre_type=VIP_PROGRAMMING_LANGUAGE,
        programming_language=VIP_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(id="#wf", type="SoftwareSourceCode"),
        raw_crate={},
    )
    vrevip = VREVIP(
        token="dummy_token",
        request_id=0,
        update_state=None,
        payload=payload,
    )

    with pytest.raises(VREConfigurationError) as exc:
        vrevip._get_pipeline_identifier()
    assert "Missing pipelineIdentifier" in str(exc.value)


@patch("app.vres.vip.requests.post")
def test_api_error(mock_post, vip_payload, mock_vault_key):
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
        payload=vip_payload,
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
        payload=None,
    )
    assert vrevip.get_default_service() == VIP_DEFAULT_SERVICE


def test_input_values_mapping(vip_payload):
    """Test _map_input_values correctly maps file names to URLs."""
    vrevip = VREVIP(
        token="dummy_token",
        request_id=0,
        update_state=None,
        payload=vip_payload,
    )

    result = vrevip._map_input_values()
    assert result == {
        "parameter_file": "https://www.creatis.insa-lyon.fr/~abonnet/quest_param_117T_A.txt",
        "data_file": "https://www.creatis.insa-lyon.fr/~abonnet/Rec003_Vox1.mrui",
        "zipped_folder": "https://www.creatis.insa-lyon.fr/~abonnet/basis_11_7.zip",
    }


def test_input_values_fallback_to_id():
    """Input-bound file with url=None resolves to the file's id."""
    payload = VREPayload(
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
        workflow_inputs=[
            FormalParameter(
                id="#input-local",
                name="local_file",
                default_value={"@id": "local-file-id"},
            ),
        ],
        raw_crate={},
    )
    vrevip = VREVIP(
        token="dummy_token",
        request_id=0,
        update_state=None,
        payload=payload,
    )

    result = vrevip._map_input_values()
    assert result == {"local_file": "local-file-id"}


def test_input_name_wins_over_file_name():
    """Payload key is the input parameter name, never the file's own name."""
    payload = VREPayload(
        vre_type=VIP_PROGRAMMING_LANGUAGE,
        programming_language=VIP_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(
            id="#workflow",
            type="SoftwareSourceCode",
            url="CQUEST/0.6",
        ),
        files=[
            FileReference(
                id="https://data.example.org/reads_1.fastq",
                name="sample_1",
                encoding_format="application/fastq",
                url="https://data.example.org/reads_1.fastq",
            ),
        ],
        workflow_inputs=[
            FormalParameter(
                id="#input-reads",
                name="reads",
                default_value={"@id": "https://data.example.org/reads_1.fastq"},
            ),
        ],
        raw_crate={},
    )
    vrevip = VREVIP(
        token="dummy_token",
        request_id=0,
        update_state=None,
        payload=payload,
    )

    assert vrevip._map_input_values() == {
        "reads": "https://data.example.org/reads_1.fastq"
    }


def test_scalar_input_included():
    """Scalar input parameters pass their literal value into the VIP payload."""
    payload = VREPayload(
        vre_type=VIP_PROGRAMMING_LANGUAGE,
        programming_language=VIP_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(
            id="#workflow",
            type="SoftwareSourceCode",
            url="CQUEST/0.6",
        ),
        workflow_inputs=[
            FormalParameter(
                id="#input-mode",
                name="mode",
                default_value="qual",
            ),
            FormalParameter(
                id="#input-iterations",
                name="iterations",
                default_value=1000,
            ),
        ],
        raw_crate={},
    )
    vrevip = VREVIP(
        token="dummy_token",
        request_id=0,
        update_state=None,
        payload=payload,
    )

    assert vrevip._map_input_values() == {"mode": "qual", "iterations": 1000}


def test_unresolvable_input_is_skipped():
    """@id reference to a file not in the package is dropped, not passed as-is."""
    payload = VREPayload(
        vre_type=VIP_PROGRAMMING_LANGUAGE,
        programming_language=VIP_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(
            id="#workflow",
            type="SoftwareSourceCode",
            url="CQUEST/0.6",
        ),
        workflow_inputs=[
            FormalParameter(
                id="#input-ghost",
                name="ghost_file",
                default_value={"@id": "https://nowhere.example/ghost.bin"},
            ),
        ],
        raw_crate={},
    )
    vrevip = VREVIP(
        token="dummy_token",
        request_id=0,
        update_state=None,
        payload=payload,
    )

    assert vrevip._map_input_values() == {}
