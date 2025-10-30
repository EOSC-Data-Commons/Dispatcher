"""Test OSCAR VRE"""
import base64
import json
import os
from unittest.mock import MagicMock, patch
from rocrate.rocrate import ROCrate
from app.vres.oscar import VREOSCAR


def load_json(file_name):
    """Load a json file from the test directory"""
    abs_file_path = os.path.join(os.path.dirname(__file__), file_name)
    with open(abs_file_path, encoding='utf-8') as f:
        return json.load(f)


@patch("app.vres.oscar.requests.get")
@patch("app.vres.oscar.requests.post")
@patch("app.vres.oscar.requests.delete")
def test_lifecycle(mock_delete, mock_post, mock_get):
    """Test OSCAR VRE post function"""
    crate = ROCrate(source=load_json('../oscar/ro-crate-metadata.json'))
    vreoscar = VREOSCAR(crate=crate, token="dummy_token")
    fdl = load_json('../oscar/cowsay.json')
    script_content = """#!/bin/sh
if [ "$INPUT_TYPE" = "json" ]
then
    jq '.message' "$INPUT_FILE_PATH" -r | /usr/games/cowsay
else
    cat "$INPUT_FILE_PATH" | /usr/games/cowsay
fi"""

    # Mock requests.get for FDL and script
    def get_side_effect(url, **kwargs):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        if url.endswith('.json'):
            mock_resp.json.return_value = fdl
        elif url.endswith('.sh'):
            mock_resp.text = script_content
        elif url.endswith('.txt'):
            mock_resp.text = "input file content"
        else:
            mock_resp.status_code = 404
            mock_resp.text = "Not Found"
        return mock_resp
    mock_get.side_effect = get_side_effect

    # Mock requests.post for service creation and invocation
    mock_post.return_value.status_code = 201

    result = vreoscar.post()
    assert result == "https://oscar.grycap.net/system/services/cowsay"
    assert mock_post.call_count == 2

    assert mock_post.call_args_list[0][0][0] == "https://oscar.grycap.net/system/services"
    fdl["script"] = script_content
    assert mock_post.call_args_list[0][1]['json'] == fdl
    assert mock_post.call_args_list[0][1]['headers'] == {'Authorization': 'Bearer dummy_token',
                                                         "Content-Type": "application/json"}

    assert mock_post.call_args_list[1][0][0] == "https://oscar.grycap.net/job/cowsay"
    assert mock_post.call_args_list[1][1]['data'] == base64.b64encode(b"input file content")
    assert mock_post.call_args_list[1][1]['headers'] == {'Authorization': 'Bearer dummy_token'}

    mock_delete.return_value.status_code = 204
    vreoscar.delete()
    assert mock_delete.call_count == 1
    assert mock_delete.call_args_list[0][0][0] == "https://oscar.grycap.net/system/services/cowsay"
