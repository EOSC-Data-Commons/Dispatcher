"""Test OSCAR VRE"""

import json
import os
import pytest
from unittest.mock import MagicMock, patch
from vre_rocrate import OSCAR_PROGRAMMING_LANGUAGE
from app.constants import OSCAR_DEFAULT_SERVICE
from app.vres.oscar import VREOSCAR
from app.exceptions import VREConfigurationError, ExternalServiceError
from vre_rocrate import (
    VREPayload,
    WorkflowDescriptor,
    FileReference,
)


def load_json(file_name):
    """Load a json file from the test directory"""
    abs_file_path = os.path.join(os.path.dirname(__file__), file_name)
    with open(abs_file_path, encoding="utf-8") as f:
        return json.load(f)


@patch("app.vres.oscar.requests.get")
def test_lifecycle(mock_get):
    """Test OSCAR VRE post function"""
    payload = VREPayload(
        vre_type=OSCAR_PROGRAMMING_LANGUAGE,
        programming_language=OSCAR_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(
            id="#workflow",
            type="SoftwareSourceCode",
            url="https://github.com/grycap/oscar-hub/tree/main/crates/cowsay",
            runtime_platform="https://oscar.vre.eosc-data-commons.eu",
        ),
        files=[
            FileReference(
                id="https://example-files.online-convert.com/document/txt/example.txt",
                name="simpletext_input",
                encoding_format="text/txt",
                url="https://example-files.online-convert.com/document/txt/example.txt",
            ),
        ],
        raw_crate={},
    )
    client = MagicMock()
    storage_client = client.create_storage_client.return_value
    vreoscar = VREOSCAR(
        token="dummy_token",
        request_id=0,
        update_state=None,
        payload=payload,
        oscar_client_factory=lambda _url, _token: client,
    )
    fdl = load_json("../fixtures/cowsay.json")
    metadata = {
        "@graph": [
            {
                "@id": "./",
                "@type": ["Dataset", "Service"],
                "serviceType": "asynchronous",
                "hasPart": [{"@id": "fdl.yml"}, {"@id": "script.sh"}],
            },
            {
                "@id": "fdl.yml",
                "@type": ["File", "SoftwareSourceCode"],
                "encodingFormat": "text/yaml",
            },
            {"@id": "script.sh", "@type": ["File", "SoftwareSourceCode"]},
        ]
    }
    fdl_yaml = """functions:
  oscar:
    - oscar-replica:
        name: cowsay
        cpu: '1.0'
        memory: 1Gi
        image: ghcr.io/grycap/cowsay
        input:
          - storage_provider: minio
            path: cowsay/input
        output:
          - storage_provider: minio
            path: cowsay/output
        script: script.sh
        isolation_level: SERVICE
        visibility: private
"""
    script = fdl["script"]

    def get_side_effect(url, **kwargs):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        if url.endswith("ro-crate-metadata.json"):
            mock_resp.json.return_value = metadata
        elif url.endswith("fdl.yml"):
            mock_resp.text = fdl_yaml
        elif url.endswith("script.sh"):
            mock_resp.text = script
        elif url.endswith(".txt"):
            mock_resp.text = "input file content"
            mock_resp.content = b"input file content"
        else:
            mock_resp.status_code = 404
            mock_resp.text = "Not Found"
        return mock_resp

    mock_get.side_effect = get_side_effect

    with patch("app.vres.oscar.secrets.token_hex", return_value="a1b2c3d4"):
        result = vreoscar.post()

    service_name = "cowsay-a1b2c3d4"
    assert result == f"{OSCAR_DEFAULT_SERVICE}/system/services/{service_name}"
    created_service = client.create_service.call_args.args[0]
    assert created_service["name"] == service_name
    assert created_service["script"] == fdl["script"]
    client.create_storage_client.assert_called_once_with(service_name)
    upload_args = storage_client.upload_file.call_args.args
    assert upload_args[0] == "minio.default"
    assert os.path.basename(upload_args[1]) == "example.txt"
    assert upload_args[2] == "cowsay/input"

    vreoscar.delete()
    client.remove_service.assert_called_once_with(service_name)


def test_fdl_in_rocrate():
    """Test missing OSCAR Hub directory URL in OSCAR VRE."""
    payload = VREPayload(
        vre_type=OSCAR_PROGRAMMING_LANGUAGE,
        programming_language=OSCAR_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(id="#wf", type="SoftwareSourceCode"),
        raw_crate={},
    )
    vreoscar = VREOSCAR(
        token="dummy_token",
        request_id=0,
        update_state=None,
        payload=payload,
    )

    with pytest.raises(VREConfigurationError) as exc:
        vreoscar._get_fdl_from_crate()
    assert "Missing OSCAR Hub directory URL in workflow entity" == str(exc.value)


@patch("app.vres.oscar.requests.get")
def test_oscar_creation_error(mock_get):
    metadata = {
        "@graph": [
            {"@id": "./", "hasPart": {"@id": "service.yaml"}},
            {"@id": "service.yaml", "encodingFormat": "text/yaml"},
        ]
    }

    def get_side_effect(url, **kwargs):
        response = MagicMock(status_code=200)
        if url.endswith("ro-crate-metadata.json"):
            response.json.return_value = metadata
        elif url.endswith("service.yaml"):
            response.text = (
                "functions:\n  oscar:\n    - cluster:\n"
                "        name: test_service\n        script: script.sh\n"
            )
        elif url.endswith("script.sh"):
            response.text = "#!/bin/sh\necho test\n"
        return response

    mock_get.side_effect = get_side_effect
    client = MagicMock()
    client.create_service.side_effect = RuntimeError("Bad Request")

    payload = VREPayload(
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
        payload=payload,
        oscar_client_factory=lambda _url, _token: client,
    )

    with pytest.raises(ExternalServiceError) as exc:
        vreoscar.post()
    assert "Error creating OSCAR service: Bad Request" == str(exc.value)


def test_synchronous_service_uses_run():
    payload = VREPayload(
        vre_type=OSCAR_PROGRAMMING_LANGUAGE,
        programming_language=OSCAR_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(
            id="#workflow",
            type="SoftwareSourceCode",
            url="https://github.com/grycap/oscar-hub/tree/main/crates/cowsay",
        ),
        files=[
            FileReference(
                id="input.txt",
                name="input.txt",
                encoding_format="text/plain",
                properties={"content": b'{"message": "Hello"}'},
            )
        ],
        raw_crate={},
    )
    client = MagicMock()
    vreoscar = VREOSCAR(
        token="dummy_token",
        request_id=0,
        update_state=None,
        payload=payload,
        oscar_client_factory=lambda _url, _token: client,
    )
    vreoscar.service_type = "synchronous"

    vreoscar._invoke_service(client, "cowsay", payload.oscar_input_files)

    run_args = client.run_service.call_args
    assert run_args.args == ("cowsay",)
    assert os.path.basename(run_args.kwargs["input"]) == "input.txt"
    assert run_args.kwargs["timeout"] == 300
