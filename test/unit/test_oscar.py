import os
import json
from unittest.mock import MagicMock, patch
from rocrate.rocrate import ROCrate
from app.vres.oscar import VREOSCAR


def load_json(file_name):
    tests_path = os.path.dirname(os.path.abspath(__file__))
    abs_file_path = os.path.join(tests_path, file_name)
    with open(abs_file_path, 'r') as f:
        return json.load(f)


@patch("app.vres.oscar.requests.get")
@patch("app.vres.oscar.requests.post")
def test_post(mock_post, mock_get):
    crate = ROCrate(source=load_json('../oscar/ro-crate-metadata.json'))
    vreoscar = VREOSCAR(crate=crate, token="dummy_token")
    fdl = load_json('../oscar/cowsay.json')
    script_content = """
        #!/bin/sh
        if [ "$INPUT_TYPE" = "json" ]
        then
            jq '.message' "$INPUT_FILE_PATH" -r | /usr/games/cowsay
        else
            cat "$INPUT_FILE_PATH" | /usr/games/cowsay
        fi"""

    # Mock requests.get for FDL and script
    def get_side_effect(url):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        if url.endswith('.json'):
            mock_resp.json.return_value = fdl
            mock_resp.text = json.dumps(fdl)
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
    assert mock_post.call_count >= 2

    assert mock_post.call_args_list[0][0][0] == "https://oscar.grycap.net/system/services"
    fdl["script"] = script_content
    assert json.loads(mock_post.call_args_list[0][1]['data']) == fdl
    assert mock_post.call_args_list[0][1]['headers'] == {'Authorization': 'Bearer dummy_token'}

    assert mock_post.call_args_list[1][0][0] == "https://oscar.grycap.net/job/cowsay"
    assert mock_post.call_args_list[1][1]['data'] == "input file content"
    assert mock_post.call_args_list[1][1]['headers'] == {'Authorization': 'Bearer dummy_token'}
