"""Test OSCAR VRE"""

import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from vre_rocrate import OSCAR_PROGRAMMING_LANGUAGE
from app.constants import OSCAR_DEFAULT_SERVICE
from app.vres.oscar import VREOSCAR
from app.exceptions import VREConfigurationError, ExternalServiceError
from vre_rocrate import (
    VREPayload,
    WorkflowDescriptor,
    FileReference,
)

COWSAY_CRATE_URL = "https://github.com/grycap/oscar-hub/tree/main/crates/cowsay"
COWSAY_RAW_BASE = "https://raw.githubusercontent.com/grycap/oscar-hub/main/crates/cowsay/"

FDL_YAML = """functions:
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


def load_json(file_name):
    """Load a json file from the test directory"""
    abs_file_path = os.path.join(os.path.dirname(__file__), file_name)
    with open(abs_file_path, encoding="utf-8") as f:
        return json.load(f)


def _oscar_client():
    client = MagicMock()
    client.create_storage_client.return_value._get_client.return_value = MagicMock()
    return client


async def test_lifecycle(httpx_mock):
    """Async OSCAR-Hub flow: fdl.yml + script.sh fetched from the crate
    directory, service created and fed via MinIO upload, then torn down
    through the remembered delivered URL."""
    fdl = load_json("../fixtures/cowsay.json")
    httpx_mock.add_response(method="GET", url=f"{COWSAY_RAW_BASE}fdl.yml", text=FDL_YAML)
    httpx_mock.add_response(
        method="GET", url=f"{COWSAY_RAW_BASE}script.sh", text=fdl["script"]
    )

    payload = VREPayload(
        vre_type=OSCAR_PROGRAMMING_LANGUAGE,
        programming_language=OSCAR_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(
            id="#workflow",
            type="SoftwareSourceCode",
            url=COWSAY_CRATE_URL,
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
    client = _oscar_client()
    storage_client = client.create_storage_client.return_value
    storage_provider_client = storage_client._get_client.return_value
    vreoscar = VREOSCAR(
        token="dummy_token",
        request_id=0,
        payload=payload,
        oscar_client_factory=lambda _url, _token: client,
    )

    with patch("app.vres.oscar.secrets.token_hex", return_value="a1b2c3d4"):
        result = await vreoscar.post()

    service_name = "cowsay-a1b2c3d4"
    assert result == f"{OSCAR_DEFAULT_SERVICE}/system/services/{service_name}"
    created_service = client.create_service.call_args.args[0]
    assert created_service["name"] == service_name
    assert created_service["script"] == fdl["script"]
    client.create_storage_client.assert_called_once_with(service_name)
    storage_client._get_client.assert_called_once_with("minio.default")
    storage_provider_client.upload_url.assert_called_once_with(
        "https://example-files.online-convert.com/document/txt/example.txt",
        "cowsay/input/example.txt",
    )
    requested_urls = [str(r.url) for r in httpx_mock.get_requests()]
    assert any(url.endswith("fdl.yml") for url in requested_urls)
    assert any(url.endswith("script.sh") for url in requested_urls)
    assert not any(url.endswith("ro-crate-metadata.json") for url in requested_urls)

    await vreoscar.delete()
    client.remove_service.assert_called_once_with(service_name)


async def test_delete_uses_delivered_url_without_fdl_fetch(httpx_mock):
    """With a delivered_url hint (as dispatch passes on DELETE), teardown
    needs no FDL download and no extra round-trips."""
    delivered = f"{OSCAR_DEFAULT_SERVICE}/system/services/cowsay-a1b2c3d4"
    client = _oscar_client()
    vre = VREOSCAR(
        token="dummy_token",
        request_id=0,
        payload=VREPayload(
            vre_type=OSCAR_PROGRAMMING_LANGUAGE,
            programming_language=OSCAR_PROGRAMMING_LANGUAGE,
            workflow=WorkflowDescriptor(id="#wf", type="SoftwareSourceCode"),
            raw_crate={},
        ),
        oscar_client_factory=lambda _url, _token: client,
        delivered_url=delivered,
    )
    # NOTE: no responses registered — any fetch would fail the test.

    await vre.delete()

    client.remove_service.assert_called_once_with("cowsay-a1b2c3d4")


async def test_fdl_in_rocrate():
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
        payload=payload,
    )

    with pytest.raises(VREConfigurationError) as exc:
        await vreoscar._get_fdl_from_crate()
    assert "Missing OSCAR Hub directory URL in workflow entity" == str(exc.value)


async def test_oscar_creation_error(httpx_mock):
    httpx_mock.add_response(method="GET", url="http://some-url/fdl.yml", text=FDL_YAML)
    httpx_mock.add_response(
        method="GET", url="http://some-url/script.sh", text="#!/bin/sh\necho test\n"
    )
    client = _oscar_client()
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
        payload=payload,
        oscar_client_factory=lambda _url, _token: client,
    )

    with pytest.raises(ExternalServiceError) as exc:
        await vreoscar.post()
    assert "Error creating OSCAR service: Bad Request" == str(exc.value)


async def test_script_fetch_error():
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
        payload=payload,
    )
    fdl = "functions:\n  oscar:\n    - cluster:\n" "        name: test-service\n"

    with patch.object(
        vreoscar, "_fetch_file", new=AsyncMock(side_effect=[fdl, RuntimeError()])
    ):
        with pytest.raises(VREConfigurationError) as exc:
            await vreoscar._get_fdl_from_crate()

    assert "Failed to fetch OSCAR script" == str(exc.value)


async def test_synchronous_service_uses_run():
    payload = VREPayload(
        vre_type=OSCAR_PROGRAMMING_LANGUAGE,
        programming_language=OSCAR_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(
            id="#workflow",
            type="SoftwareSourceCode",
            url=COWSAY_CRATE_URL,
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
    client = _oscar_client()
    vreoscar = VREOSCAR(
        token="dummy_token",
        request_id=0,
        payload=payload,
        oscar_client_factory=lambda _url, _token: client,
    )
    fdl = {
        "name": "cowsay",
        "image": "ghcr.io/grycap/cowsay",
        "script": "#!/bin/sh\necho test\n",
    }

    with patch.object(vreoscar, "_get_fdl_from_crate", new=AsyncMock(return_value=fdl)):
        with patch("app.vres.oscar.secrets.token_hex", return_value="a1b2c3d4"):
            await vreoscar.post()

    run_args = client.run_service.call_args
    assert run_args.args == ("cowsay-a1b2c3d4",)
    assert os.path.basename(run_args.kwargs["input"]) == "input.txt"
    assert run_args.kwargs["timeout"] == 300
    client.create_storage_client.assert_not_called()
