"""Test OSCAR VRE"""

import json
import os
import pytest
from requests.exceptions import HTTPError
from unittest.mock import MagicMock, create_autospec, patch
from vre_rocrate import OSCAR_PROGRAMMING_LANGUAGE
from app.constants import OSCAR_DEFAULT_SERVICE
from app.vres.oscar import VREOSCAR, OscarClient
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
    client = create_autospec(OscarClient, instance=True)
    vreoscar = VREOSCAR(
        token="dummy_token",
        request_id=0,
        update_state=MagicMock(),
        payload=payload,
        oscar_client_factory=lambda _url, _token: client,
    )
    fdl = load_json("../fixtures/cowsay.json")
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
        if url.endswith("fdl.yml"):
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
    assert result == OSCAR_DEFAULT_SERVICE
    created_service = client.create_service.call_args.args[0]
    assert created_service["name"] == service_name
    assert created_service["script"] == fdl["script"]
    client.upload_url.assert_called_once_with(
        service_name,
        "minio.default",
        "https://example-files.online-convert.com/document/txt/example.txt",
        "cowsay/input/example.txt",
    )
    requested_urls = [call.args[0] for call in mock_get.call_args_list]
    assert any(url.endswith("fdl.yml") for url in requested_urls)
    assert any(url.endswith("script.sh") for url in requested_urls)
    assert not any(url.endswith("ro-crate-metadata.json") for url in requested_urls)


def test_invalid_client_factory():
    payload = VREPayload(
        vre_type=OSCAR_PROGRAMMING_LANGUAGE,
        programming_language=OSCAR_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(id="#wf", type="SoftwareSourceCode"),
        raw_crate={},
    )
    with pytest.raises(VREConfigurationError):
        VREOSCAR(
            token="dummy_token",
            request_id=0,
            update_state=MagicMock(),
            payload=payload,
            oscar_client_factory=lambda _url, _token: object(),
        )


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
        update_state=MagicMock(),
        payload=payload,
    )

    with pytest.raises(VREConfigurationError) as exc:
        vreoscar._get_fdl_from_crate()
    assert "Missing OSCAR Hub directory URL in workflow entity" == str(exc.value)


@patch("app.vres.oscar.requests.get")
def test_oscar_creation_error(mock_get):
    def get_side_effect(url, **kwargs):
        response = MagicMock(status_code=200)
        if url.endswith("fdl.yml"):
            response.text = (
                "functions:\n  oscar:\n    - cluster:\n"
                "        name: test_service\n        script: script.sh\n"
            )
        elif url.endswith("script.sh"):
            response.text = "#!/bin/sh\necho test\n"
        return response

    mock_get.side_effect = get_side_effect
    client = create_autospec(OscarClient, instance=True)
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
        update_state=MagicMock(),
        payload=payload,
        oscar_client_factory=lambda _url, _token: client,
    )

    with pytest.raises(ExternalServiceError) as exc:
        vreoscar.post()
    assert "Error creating OSCAR service: Bad Request" == str(exc.value)


def test_script_fetch_error():
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
        update_state=MagicMock(),
        payload=payload,
    )
    fdl = "functions:\n  oscar:\n    - cluster:\n" "        name: test-service\n"

    with patch.object(vreoscar, "_fetch_file", side_effect=[fdl, RuntimeError()]):
        with pytest.raises(VREConfigurationError) as exc:
            vreoscar._get_fdl_from_crate()

    assert "Failed to fetch OSCAR script" == str(exc.value)


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
    client = create_autospec(OscarClient, instance=True)
    vreoscar = VREOSCAR(
        token="dummy_token",
        request_id=0,
        update_state=MagicMock(),
        payload=payload,
        oscar_client_factory=lambda _url, _token: client,
    )
    fdl = {
        "name": "cowsay",
        "image": "ghcr.io/grycap/cowsay",
        "script": "#!/bin/sh\necho test\n",
    }

    with patch.object(vreoscar, "_get_fdl_from_crate", return_value=fdl):
        with patch("app.vres.oscar.secrets.token_hex", return_value="a1b2c3d4"):
            vreoscar.post()

    run_args = client.run_service.call_args
    assert run_args.args == ("cowsay-a1b2c3d4",)
    assert os.path.basename(run_args.kwargs["file_content"]) == b'{"message": "Hello"}'
    assert run_args.kwargs["timeout"] == 300
    client.upload_url.assert_not_called()


ENDPOINT = "https://oscar.example.org"


def test_client_create_service(requests_mock):
    requests_mock.get(f"{ENDPOINT}/system/services/svc", status_code=404)
    post = requests_mock.post(f"{ENDPOINT}/system/services", status_code=201)
    OscarClient(ENDPOINT, "tok").create_service({"name": "svc"})
    assert post.last_request.headers["Authorization"] == "Bearer tok"
    assert post.last_request.json() == {"name": "svc"}


def test_client_create_existing_service(requests_mock):
    requests_mock.get(f"{ENDPOINT}/system/services/svc", status_code=200)
    with pytest.raises(ValueError):
        OscarClient(ENDPOINT, "tok").create_service({"name": "svc"})


def test_client_remove_and_run_service(requests_mock, tmp_path):
    delete = requests_mock.delete(f"{ENDPOINT}/system/services/svc")
    run = requests_mock.post(f"{ENDPOINT}/run/svc", text="ok")
    client = OscarClient(ENDPOINT, "tok")
    client.remove_service("svc")
    assert delete.called
    input_file = tmp_path / "in.txt"
    input_file.write_bytes(b"hello")
    client.run_service("svc", file_content=b"hello", timeout=5)
    assert run.last_request.body == b"aGVsbG8="


@patch("app.vres.oscar.boto3.client")
def test_client_upload_url(mock_boto, requests_mock):
    requests_mock.get(f"{ENDPOINT}/system/services/svc", json={"storage_providers": {}})
    requests_mock.get(
        f"{ENDPOINT}/system/config",
        json={
            "minio_provider": {
                "endpoint": "https://minio.example.org",
                "region": "",
                "verify": True,
                "access_key": "ak",
                "secret_key": "sk",
            }
        },
    )
    requests_mock.get(
        "https://files.example.org/a.txt",
        content=b"data",
        headers={"content-type": "text/plain"},
    )
    ok = OscarClient(ENDPOINT, "tok").upload_url(
        "svc", "minio.default", "https://files.example.org/a.txt", "bucket/in/a.txt"
    )
    assert ok is None
    assert mock_boto.call_args.kwargs["endpoint_url"] == "https://minio.example.org"
    assert mock_boto.call_args.kwargs["region_name"] is None
    upload = mock_boto.return_value.upload_fileobj
    assert upload.call_args.args[1:] == ("bucket", "in/a.txt")
    assert upload.call_args.kwargs["ExtraArgs"] == {"ContentType": "text/plain"}


def test_client_upload_url_download_error(requests_mock):
    requests_mock.get(f"{ENDPOINT}/system/services/svc", json={"storage_providers": {}})
    requests_mock.get(
        f"{ENDPOINT}/system/config", json={"minio_provider": {"endpoint": ""}}
    )
    requests_mock.get("https://files.example.org/a.txt", status_code=404)
    with patch("app.vres.oscar.boto3.client"):
        with pytest.raises(HTTPError):
            OscarClient(ENDPOINT, "tok").upload_url(
                "svc", "minio.default", "https://files.example.org/a.txt", "b/a.txt"
            )


def test_async_uploads_attempt_all_files_and_raise_when_one_fails():
    payload = VREPayload(
        vre_type=OSCAR_PROGRAMMING_LANGUAGE,
        programming_language=OSCAR_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(id="#wf", type="SoftwareSourceCode"),
        files=[
            FileReference(
                id="https://files.example.org/one.txt",
                name="one.txt",
                encoding_format="text/plain",
                url="https://files.example.org/one.txt",
            ),
            FileReference(
                id="https://files.example.org/two.txt",
                name="two.txt",
                encoding_format="text/plain",
                url="https://files.example.org/two.txt",
            ),
        ],
        raw_crate={},
    )
    client = create_autospec(OscarClient, instance=True)
    client.upload_url.side_effect = [RuntimeError("upload failed"), None]
    vre = VREOSCAR(
        token="tok",
        request_id=0,
        update_state=MagicMock(),
        payload=payload,
        oscar_client_factory=lambda _url, _token: client,
    )

    with pytest.raises(
        ExternalServiceError, match="One or more OSCAR input files failed to upload"
    ):
        vre._upload_input_files(
            "svc", {"input": [{"provider": "minio", "path": "bucket/in"}]}
        )

    assert client.upload_url.call_count == 2


def test_async_upload_exception_does_not_skip_later_files():
    payload = VREPayload(
        vre_type=OSCAR_PROGRAMMING_LANGUAGE,
        programming_language=OSCAR_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(id="#wf", type="SoftwareSourceCode"),
        files=[
            FileReference(
                id="https://files.example.org/one.txt",
                name="one.txt",
                encoding_format="text/plain",
                url="https://files.example.org/one.txt",
            ),
            FileReference(
                id="https://files.example.org/two.txt",
                name="two.txt",
                encoding_format="text/plain",
                url="https://files.example.org/two.txt",
            ),
        ],
        raw_crate={},
    )
    client = create_autospec(OscarClient, instance=True)
    client.upload_url.side_effect = [RuntimeError("upload failed"), True]
    vre = VREOSCAR(
        token="tok",
        request_id=0,
        update_state=MagicMock(),
        payload=payload,
        oscar_client_factory=lambda _url, _token: client,
    )

    with pytest.raises(ExternalServiceError):
        vre._upload_input_files(
            "svc", {"input": [{"provider": "minio", "path": "bucket/in"}]}
        )

    assert client.upload_url.call_count == 2


def test_post_removes_created_service_after_invocation_failure():
    payload = VREPayload(
        vre_type=OSCAR_PROGRAMMING_LANGUAGE,
        programming_language=OSCAR_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(id="#wf", type="SoftwareSourceCode"),
        raw_crate={},
    )
    client = create_autospec(OscarClient, instance=True)
    vre = VREOSCAR(
        token="tok",
        request_id=0,
        update_state=MagicMock(),
        payload=payload,
        oscar_client_factory=lambda _url, _token: client,
    )
    fdl = {"name": "svc", "input": [{"provider": "minio", "path": "bucket/in"}]}
    with patch.object(vre, "_get_fdl_from_crate", return_value=fdl), patch(
        "app.vres.oscar.secrets.token_hex", return_value="deadbeef"
    ), patch.object(
        vre, "_upload_input_files", side_effect=ExternalServiceError("upload failed")
    ):
        with pytest.raises(ExternalServiceError, match="upload failed"):
            vre.post()

    client.remove_service.assert_called_once_with("svc-deadbeef")
