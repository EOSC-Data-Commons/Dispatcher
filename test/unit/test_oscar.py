"""Test OSCAR VRE"""

import base64
import json
import os
import pytest
from unittest.mock import MagicMock, patch
from rocrate.rocrate import ROCrate
from app.constants import OSCAR_DEFAULT_SERVICE
from app.vres.oscar import VREOSCAR
from app.exceptions import (
    ExternalServiceError,
    WorkflowURLError,
)


def load_json(file_name):
    """Load a json file from the test directory"""
    abs_file_path = os.path.join(os.path.dirname(__file__), file_name)
    with open(abs_file_path, encoding="utf-8") as f:
        return json.load(f)


@patch("app.vres.oscar.requests.get")
@patch("app.vres.oscar.requests.post")
@patch("app.vres.oscar.requests.delete")
def test_lifecycle(mock_delete, mock_post, mock_get):
    """Test OSCAR VRE post function"""
    crate = ROCrate(source=load_json("../oscar/ro-crate-metadata.json"))
    vreoscar = VREOSCAR(
        crate=crate, token="dummy_token", request_id=0, update_state=None
    )
    fdl = load_json("../oscar/cowsay.json")

    # Mock requests.get for FDL and script
    def get_side_effect(url, **kwargs):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        if url.endswith(".json"):
            mock_resp.json.return_value = fdl
        elif url.endswith(".txt"):
            mock_resp.text = "input file content"
        else:
            mock_resp.status_code = 404
            mock_resp.text = "Not Found"
        return mock_resp

    mock_get.side_effect = get_side_effect

    # Mock requests.post for service creation and invocation
    mock_post.return_value.status_code = 201

    result = vreoscar.post()
    assert result == f"{OSCAR_DEFAULT_SERVICE}/system/services/cowsay"
    assert mock_post.call_count == 2

    assert (
        mock_post.call_args_list[0][0][0] == f"{OSCAR_DEFAULT_SERVICE}/system/services"
    )
    assert mock_post.call_args_list[0][1]["json"] == fdl
    assert mock_post.call_args_list[0][1]["headers"] == {
        "Authorization": "Bearer dummy_token",
        "Content-Type": "application/json",
    }

    assert mock_post.call_args_list[1][0][0] == f"{OSCAR_DEFAULT_SERVICE}/job/cowsay"
    assert mock_post.call_args_list[1][1]["data"] == base64.b64encode(
        b"input file content"
    )
    assert mock_post.call_args_list[1][1]["headers"] == {
        "Authorization": "Bearer dummy_token"
    }

    mock_delete.return_value.status_code = 204
    vreoscar.delete()
    assert mock_delete.call_count == 1
    assert (
        mock_delete.call_args_list[0][0][0]
        == f"{OSCAR_DEFAULT_SERVICE}/system/services/cowsay"
    )


def test_no_hasparts():
    """Test Missing workflow url in OSCAR VRE"""
    crate = MagicMock()
    crate.mainEntity = {"hasPart": []}
    crate.root_dataset = {}
    vreoscar = VREOSCAR(
        crate=crate, token="dummy_token", request_id=0, update_state=None
    )

    with pytest.raises(WorkflowURLError) as exc:
        vreoscar._get_fdl_from_crate()
    assert "Missing url in workflow entity" == str(exc.value)


@patch("app.vres.oscar.requests.get")
def test_invalid_entity_type(mock_get):
    """Test network failure while fetching OSCAR FDL"""
    crate = MagicMock()
    crate.mainEntity = {"url": "http://some-url"}
    crate.root_dataset = {}
    mock_get.side_effect = Exception("connection error")
    vreoscar = VREOSCAR(
        crate=crate, token="dummy_token", request_id=0, update_state=None
    )

    with pytest.raises(WorkflowURLError) as exc:
        vreoscar._get_fdl_from_crate()
    assert "Network error while fetching FDL." == str(exc.value)


@patch("app.vres.oscar.requests.get")
def test_fdl_missing(mock_get):
    """Test invalid JSON payload while fetching OSCAR FDL"""
    crate = MagicMock()
    crate.mainEntity = {"url": "http://some-url"}
    crate.root_dataset = {}
    mock_get.return_value.raise_for_status.return_value = None
    mock_get.return_value.json.side_effect = ValueError("invalid json")
    vreoscar = VREOSCAR(
        crate=crate, token="dummy_token", request_id=0, update_state=None
    )

    with pytest.raises(WorkflowURLError) as exc:
        vreoscar._get_fdl_from_crate()
    assert "Network error while fetching FDL." == str(exc.value)


@patch("app.vres.oscar.requests.get")
def test_fdl_http_error(mock_get):
    """Test HTTP error while fetching OSCAR FDL"""
    crate = MagicMock()
    crate.mainEntity = {"url": "http://some-url"}
    crate.root_dataset = {}
    mock_get.return_value.raise_for_status.side_effect = Exception("404")
    vreoscar = VREOSCAR(
        crate=crate, token="dummy_token", request_id=0, update_state=None
    )

    with pytest.raises(WorkflowURLError) as exc:
        vreoscar._get_fdl_from_crate()
    assert "Network error while fetching FDL." == str(exc.value)


@patch("app.vres.oscar.requests.get")
@patch("app.vres.oscar.requests.post")
def test_oscar_creation_error(mock_post, mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.raise_for_status.return_value = None
    mock_get.return_value.json.return_value = {"name": "test_service"}
    mock_post.return_value.status_code = 400
    mock_post.return_value.text = "Bad Request"

    crate = MagicMock()
    crate.mainEntity = {"url": "http://some-url"}
    crate.root_dataset = {}
    vreoscar = VREOSCAR(
        crate=crate, token="dummy_token", request_id=0, update_state=None
    )

    with pytest.raises(ExternalServiceError) as exc:
        vreoscar.post()
    assert "Error creating OSCAR service: Bad Request" == str(exc.value)
