"""Test RRP VRE"""

import pytest
from unittest.mock import MagicMock, patch

import requests

from app.constants import RRP_DEFAULT_SERVICE
from app.exceptions import ExternalServiceError, MissingRRPParameters
from app.vres.rrp import VRERRP
from vre_rocrate import (
    DatasetReference,
    VREPayload,
    WorkflowDescriptor,
    FileReference,
    FormalParameter,
)

RRP_BACKEND = "https://rrp-eosc.example.org"
RRP_PROJECT_API_URL = f"{RRP_BACKEND}/external/dispatcher/v1/projects/123"
RRP_PROJECT_UI_URL = f"{RRP_BACKEND}/projects/abc-123"
RRP_EXECUTION_URL = f"{RRP_BACKEND}/external/dispatcher/v1/executions/1"
RRP_DOCKER_IMAGE = "reproducibleresearchplatform/rrp-eosc:cell-doubling-time_1.0.1"
RRP_REPOSITORY_URL = (
    "https://gitlab.ethz.ch/Reproducible-Research-Platform/tools/Cell-Doubling-Time"
)

FILE_0_URL = "https://zenodo.org/records/20507550/files/image_0.tif"
FILE_1_URL = "https://zenodo.org/records/20507550/files/raw%2Fimage_1.tif"

DATASET_URL = "https://doi.org/10.5281/zenodo.20507550"


class MockResponse:
    def __init__(self, json_data=None, headers=None, status_error=None):
        self._json_data = json_data
        self.headers = headers or {}
        if status_error is not None:
            self.raise_for_status = MagicMock(side_effect=status_error)
        else:
            self.raise_for_status = MagicMock()

    def json(self):
        if self._json_data is None:
            raise ValueError("No JSON body")
        return self._json_data


def _rrp_payload(
    with_dataset=True, docker_image=RRP_DOCKER_IMAGE, workflow_url=RRP_REPOSITORY_URL
):
    raw_crate_graph = [
        {
            "@id": "./",
            "@type": "Dataset",
            "name": "Root dataset for tool: RRP tool",
        },
    ]
    return VREPayload(
        vre_type="https://rrp-eosc.ethz.ch/",
        programming_language="https://rrp-eosc.ethz.ch/",
        input_dataset=(
            DatasetReference(
                url=DATASET_URL,
                name="Cell doubling time dataset",
                description="Microscopy images for measuring cell doubling times",
            )
            if with_dataset
            else None
        ),
        workflow=WorkflowDescriptor(
            id=workflow_url or "some-tool",
            url=workflow_url,
            type="SoftwareSourceCode",
            docker_image=docker_image,
        ),
        files=[
            FileReference(id=FILE_0_URL, name="image_0.tif", url=FILE_0_URL),
            FileReference(
                id=FILE_1_URL, name="__ROOT__/raw/image_1.tif", url=FILE_1_URL
            ),
        ],
        workflow_inputs=[
            FormalParameter(
                id="#input-image_0.tif",
                name="Image 0 (TIF)",
                default_value={"@id": FILE_0_URL},
            ),
            FormalParameter(
                id="#input-image_1.tif",
                name="Image 1 (TIF)",
                default_value={"@id": FILE_1_URL},
            ),
        ],
        raw_crate={"@graph": raw_crate_graph},
    )


@pytest.fixture
def rrp_vre():
    vre = VRERRP(
        token="dummy_token",
        request_id=42,
        update_state=MagicMock(),
        payload=_rrp_payload(),
    )
    vre.svc_url = RRP_BACKEND
    return vre


def _full_success_responses():
    """Responses for the complete happy-path call sequence."""
    return [
        # create project
        MockResponse(
            json_data={"id": RRP_PROJECT_API_URL},
            headers={"Location": RRP_PROJECT_UI_URL},
        ),
        # poll project creation
        MockResponse(json_data={"creationStatus": "Ready"}),
        # clone repository
        MockResponse(json_data={"execution": RRP_EXECUTION_URL}),
        # poll clone execution
        MockResponse(json_data={"status": "Success"}),
        # checkout branch
        MockResponse(json_data={}),
        # trigger data retrieval
        MockResponse(json_data={}),
        # poll data staging
        MockResponse(
            json_data={
                "creationStatus": "Ready",
                "dataStatus": {
                    "image_0.tif": {"status": "Available"},
                    "image_1.tif": {"status": "Available"},
                },
            }
        ),
    ]


@patch("app.vres.rrp.time.sleep")
@patch("app.vres.rrp.requests.request")
def test_post_success(mock_request, mock_sleep, rrp_vre):
    mock_request.side_effect = _full_success_responses()

    result = rrp_vre.post()

    assert result == RRP_PROJECT_UI_URL
    assert mock_request.call_count == 7
    assert mock_sleep.call_count == 0

    methods = [call.args[0] for call in mock_request.call_args_list]
    assert methods == ["POST", "GET", "POST", "GET", "POST", "POST", "GET"]

    create_call = mock_request.call_args_list[0]
    assert create_call.args[1] == f"{RRP_BACKEND}/external/dispatcher/v1/projects"
    assert create_call.kwargs["headers"]["Authorization"] == "Bearer dummy_token"

    payload = create_call.kwargs["json"]
    assert payload["image"] == RRP_DOCKER_IMAGE
    assert payload["name"] == "eosc-42"
    assert payload["resources"] == {"cpu": 1.0, "memMb": 2048}
    assert payload["dataMounts"] == [
        {
            "mountPath": "image_0.tif",
            "source": {"type": "zenodo", "doi": "10.5281/zenodo.20507550"},
            "path": "image_0.tif",
        },
        {
            "mountPath": "image_1.tif",
            "source": {"type": "zenodo", "doi": "10.5281/zenodo.20507550"},
            "path": "raw/image_1.tif",
        },
    ]

    clone_call = mock_request.call_args_list[2]
    assert clone_call.args[1] == f"{RRP_PROJECT_API_URL}/clone"
    assert clone_call.kwargs["json"] == {"repositoryUrl": RRP_REPOSITORY_URL}

    checkout_call = mock_request.call_args_list[4]
    assert checkout_call.args[1] == f"{RRP_PROJECT_API_URL}/checkout"
    assert checkout_call.kwargs["json"] == {"ref": "main"}

    data_call = mock_request.call_args_list[5]
    assert data_call.args[1] == f"{RRP_PROJECT_API_URL}/data"

    stages = [
        call.kwargs["meta"]["stage"] for call in rrp_vre._update_state.call_args_list
    ]
    assert stages == [
        "Waiting for RRP project creation",
        "Cloning tool repository",
        "Checking out branch",
        "Staging data",
    ]


@patch("app.vres.rrp.time.sleep")
@patch("app.vres.rrp.requests.request")
def test_post_polls_until_ready(mock_request, mock_sleep, rrp_vre):
    responses = _full_success_responses()
    # project creation needs three polls before it is Ready
    responses[1] = MockResponse(json_data={"creationStatus": "Pending"})
    responses.insert(2, MockResponse(json_data={"creationStatus": "Pending"}))
    responses.insert(3, MockResponse(json_data={"creationStatus": "Ready"}))
    # data staging needs a second poll
    responses.append(responses[-1])
    responses[-2] = MockResponse(
        json_data={
            "creationStatus": "Ready",
            "dataStatus": {
                "image_0.tif": {"status": "Available"},
                "image_1.tif": {"status": "Pending"},
            },
        }
    )
    mock_request.side_effect = responses

    result = rrp_vre.post()

    assert result == RRP_PROJECT_UI_URL
    assert mock_request.call_count == 10
    assert mock_sleep.call_count == 3


@patch("app.vres.rrp.requests.request")
def test_post_create_project_fails(mock_request, rrp_vre):
    mock_request.return_value = MockResponse(
        status_error=requests.HTTPError("500 Server Error")
    )

    with pytest.raises(ExternalServiceError):
        rrp_vre.post()


@patch("app.vres.rrp.time.sleep")
@patch("app.vres.rrp.requests.request")
def test_post_poll_timeout(mock_request, mock_sleep, rrp_vre):
    from app.config import settings

    never_ready = MockResponse(json_data={"creationStatus": "Pending"})
    responses = [
        # create project
        MockResponse(
            json_data={"id": RRP_PROJECT_API_URL},
            headers={"Location": RRP_PROJECT_UI_URL},
        ),
    ]
    # project creation never reaches Ready
    responses.extend([never_ready] * settings.rrp_poll_max_attempts)
    mock_request.side_effect = responses

    with pytest.raises(ExternalServiceError) as exc:
        rrp_vre.post()
    assert "did not complete" in str(exc.value)
    assert mock_request.call_count == settings.rrp_poll_max_attempts + 1


@patch("app.vres.rrp.requests.request")
def test_post_missing_docker_image(mock_request, rrp_vre):
    rrp_vre.payload.workflow.docker_image = None

    with pytest.raises(MissingRRPParameters) as exc:
        rrp_vre.post()
    assert "dockerImage" in str(exc.value)
    mock_request.assert_not_called()


@patch("app.vres.rrp.requests.request")
def test_post_missing_repository_url(mock_request, rrp_vre):
    rrp_vre.payload.workflow.url = None

    with pytest.raises(MissingRRPParameters) as exc:
        rrp_vre.post()
    assert "repository URL" in str(exc.value)
    mock_request.assert_not_called()


@patch("app.vres.rrp.requests.request")
def test_post_missing_dataset(mock_request, rrp_vre):
    rrp_vre.payload = _rrp_payload(with_dataset=False)

    with pytest.raises(MissingRRPParameters) as exc:
        rrp_vre.post()
    assert "dataset" in str(exc.value)
    mock_request.assert_not_called()


@patch("app.vres.rrp.requests.request")
def test_post_non_doi_dataset_url(mock_request, rrp_vre):
    rrp_vre.payload.input_dataset = DatasetReference(
        url="https://example.com/not-a-doi"
    )

    with pytest.raises(MissingRRPParameters) as exc:
        rrp_vre.post()
    assert "doi.org" in str(exc.value)
    mock_request.assert_not_called()


def test_file_dataset_path_decodes_zenodo_url(rrp_vre):
    file_ref = FileReference(
        id="https://zenodo.org/records/20507550/files/raw%2Fimage_1.tif?download=1",
        name="image_1.tif",
        url="https://zenodo.org/records/20507550/files/raw%2Fimage_1.tif?download=1",
    )
    assert rrp_vre._file_dataset_path(file_ref) == "raw/image_1.tif"


def test_file_dataset_path_falls_back_to_name(rrp_vre):
    file_ref = FileReference(
        id="https://example.org/data/foo.csv",
        name="__ROOT__/bar/foo.csv",
        url="https://example.org/data/foo.csv",
    )
    assert rrp_vre._file_dataset_path(file_ref) == "bar/foo.csv"


def test_default_service():
    vre = VRERRP(
        token="dummy_token",
        request_id=0,
        update_state=MagicMock(),
        payload=_rrp_payload(),
    )
    assert vre.svc_url == RRP_DEFAULT_SERVICE
