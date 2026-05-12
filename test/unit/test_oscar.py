"""Test OSCAR VRE"""

import base64
import json
import os
import pytest
from unittest.mock import MagicMock, patch
from app.constants import OSCAR_DEFAULT_SERVICE
from app.vres.oscar import VREOSCAR
from app.exceptions import VREConfigurationError, ExternalServiceError
from fixtures.dummy_crate import DummyEntity, DummyCrate


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
    main = DummyEntity(
        _type="SoftwareSourceCode",
        **{
            "@id": "#workflow",
            "url": "https://raw.githubusercontent.com/micafer/Dispatcher/refs/heads/oscar-vre/test/oscar/cowsay.json",
            "runtimePlatform": "https://oscar.vre.eosc-data-commons.eu",
        },
    )
    script_entity = DummyEntity(
        _type="File",
        **{
            "@id": "https://raw.githubusercontent.com/grycap/oscar/refs/heads/master/examples/cowsay/script.sh",
            "encodingFormat": "text/x-shellscript",
        },
    )
    input_entity = DummyEntity(
        _type="File",
        **{
            "@id": "https://example-files.online-convert.com/document/txt/example.txt",
            "name": "simpletext_input",
            "encodingFormat": "text/txt",
        },
    )
    crate = DummyCrate(main_entity=main, other_entities=[script_entity, input_entity])
    vreoscar = VREOSCAR(
        crate=crate, token="dummy_token", request_id=0, update_state=None
    )
    fdl = load_json("../oscar/cowsay.json")
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


def test_no_hasparts():
    """Test Missing url in OSCAR VRE"""
    main = DummyEntity(_type="SoftwareSourceCode")
    crate = DummyCrate(main_entity=main)
    vreoscar = VREOSCAR(
        crate=crate, token="dummy_token", request_id=0, update_state=None
    )

    with pytest.raises(VREConfigurationError) as exc:
        vreoscar._get_fdl_from_crate()
    assert "Missing url in workflow entity" == str(exc.value)


def test_missing_url():
    """Test Missing url in OSCAR VRE"""
    main = DummyEntity(_type="SoftwareSourceCode")
    crate = DummyCrate(main_entity=main)
    vreoscar = VREOSCAR(
        crate=crate, token="dummy_token", request_id=0, update_state=None
    )

    with pytest.raises(VREConfigurationError) as exc:
        vreoscar._get_fdl_from_crate()
    assert "Missing url in workflow entity" == str(exc.value)


@patch("app.vres.oscar.requests.get")
@patch("app.vres.oscar.requests.post")
def test_oscar_creation_error(mock_post, mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"name": "test_service"}
    mock_post.return_value.status_code = 400
    mock_post.return_value.text = "Bad Request"

    main = DummyEntity(
        _type="SoftwareSourceCode",
        **{"@id": "#workflow", "url": "http://some-url"},
    )
    crate = DummyCrate(main_entity=main)
    vreoscar = VREOSCAR(
        crate=crate, token="dummy_token", request_id=0, update_state=None
    )

    with pytest.raises(ExternalServiceError) as exc:
        vreoscar.post()
    assert "Error creating OSCAR service: Bad Request" == str(exc.value)
