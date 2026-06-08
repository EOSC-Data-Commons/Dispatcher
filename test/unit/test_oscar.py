"""Test OSCAR VRE"""

import base64
import json
import os
import pytest
from unittest.mock import MagicMock, patch
from vre_rocrate import OSCAR_PROGRAMMING_LANGUAGE
from app.constants import OSCAR_DEFAULT_SERVICE
from app.vres.oscar import VREOSCAR
from app.exceptions import VREConfigurationError, ExternalServiceError
from vre_rocrate import (
    RequestPackage,
    WorkflowDescriptor,
    FileReference,
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
    request_package = RequestPackage(
        vre_type=OSCAR_PROGRAMMING_LANGUAGE,
        programming_language=OSCAR_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(
            id="#workflow",
            type="SoftwareSourceCode",
            url="https://raw.githubusercontent.com/micafer/Dispatcher/refs/heads/oscar-vre/test/oscar/cowsay.json",
            runtime_platform="https://oscar.vre.eosc-data-commons.eu",
        ),
        files=[
            FileReference(
                id="https://raw.githubusercontent.com/grycap/oscar/refs/heads/master/examples/cowsay/script.sh",
                name="script.sh",
                encoding_format="text/x-shellscript",
                url="https://raw.githubusercontent.com/grycap/oscar/refs/heads/master/examples/cowsay/script.sh",
            ),
            FileReference(
                id="https://example-files.online-convert.com/document/txt/example.txt",
                name="simpletext_input",
                encoding_format="text/txt",
                url="https://example-files.online-convert.com/document/txt/example.txt",
            ),
        ],
        raw_crate={},
    )
    vreoscar = VREOSCAR(
        token="dummy_token",
        request_id=0,
        update_state=None,
        request_package=request_package,
    )
    fdl = load_json("../fixtures/cowsay.json")
    script_content = """#!/bin/sh
if [ "$INPUT_TYPE" = "json" ]
then
    jq '.message' "$INPUT_FILE_PATH" -r | /usr/games/cowsay
else
    cat "$INPUT_FILE_PATH" | /usr/games/cowsay
fi"""

    def get_side_effect(url, **kwargs):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        if url.endswith(".json"):
            mock_resp.json.return_value = fdl
        elif url.endswith(".sh"):
            mock_resp.text = script_content
        elif url.endswith(".txt"):
            mock_resp.text = "input file content"
        else:
            mock_resp.status_code = 404
            mock_resp.text = "Not Found"
        return mock_resp

    mock_get.side_effect = get_side_effect
    mock_post.return_value.status_code = 201

    result = vreoscar.post()
    assert result == f"{OSCAR_DEFAULT_SERVICE}/system/services/cowsay"
    assert mock_post.call_count == 2

    assert (
        mock_post.call_args_list[0][0][0] == f"{OSCAR_DEFAULT_SERVICE}/system/services"
    )
    fdl["script"] = script_content
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


def test_fdl_in_rocrate():
    """Test Missing url of FDL file in OSCAR VRE"""
    request_package = RequestPackage(
        vre_type=OSCAR_PROGRAMMING_LANGUAGE,
        programming_language=OSCAR_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(id="#wf", type="SoftwareSourceCode"),
        raw_crate={},
    )
    vreoscar = VREOSCAR(
        token="dummy_token",
        request_id=0,
        update_state=None,
        request_package=request_package,
    )

    with pytest.raises(VREConfigurationError) as exc:
        vreoscar._get_fdl_from_crate()
    assert "Missing FDL URL in workflow entity" == str(exc.value)


@patch("app.vres.oscar.requests.get")
@patch("app.vres.oscar.requests.post")
def test_oscar_creation_error(mock_post, mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"name": "test_service"}
    mock_post.return_value.status_code = 400
    mock_post.return_value.text = "Bad Request"

    request_package = RequestPackage(
        vre_type=OSCAR_PROGRAMMING_LANGUAGE,
        programming_language=OSCAR_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(
            id="#workflow", type="SoftwareSourceCode", url="http://some-url"
        ),
        raw_crate={},
    )
    vreoscar = VREOSCAR(
        token="dummy_token",
        request_id=0,
        update_state=None,
        request_package=request_package,
    )

    with pytest.raises(ExternalServiceError) as exc:
        vreoscar.post()
    assert "Error creating OSCAR service: Bad Request" == str(exc.value)
