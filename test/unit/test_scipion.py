import json
import os
import pytest
from unittest.mock import MagicMock, patch
from rocrate.rocrate import ROCrate

from app.constants import SCIPION_COMMAND
from app.exceptions import VREConfigurationError
from app.vres.scipion import VREScipion

EXPECTED_DATASET_URL = "rsync://ftp.ebi.ac.uk/empiar/world_availability/13496"


def load_json(file_name):
    """Load a json file from the test directory"""
    abs_file_path = os.path.join(os.path.dirname(__file__), file_name)
    with open(abs_file_path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def scipion_vre():
    crate = ROCrate(source=load_json("../scipion_tosca/ro-crate-metadata.json"))

    class DummyIMClient:
        def run_service(self, _dest):
            return {"url": "https://scipion.example.org"}

    vre = VREScipion(
        crate=crate,
        token="test-token",
        request_id=0,
        update_state=lambda **_kwargs: None,
        im_factory=lambda _token: DummyIMClient(),
    )
    vre.ssh = {
        "node_ip": {"value": "worker.example.org"},
        "node_creds": {
            "value": {
                "user": "scipion",
                "token": "dummy-key",
            }
        },
    }
    return vre


def test_post_without_ssh_raises(scipion_vre):
    scipion_vre.ssh = None

    with pytest.raises(VREConfigurationError, match="Missing 'ssh' information"):
        scipion_vre.post()


def test_execute_long_ssh_command_timeout(scipion_vre):
    ssh_client = MagicMock()
    scipion_vre._execute_ssh_command = MagicMock(return_value="12345\n")

    with pytest.raises(VREConfigurationError, match="timed out"):
        scipion_vre._execute_long_ssh_command(
            scipion_vre.ssh,
            ssh_client,
            "long-running-command",
            poll_seconds=0,
            timeout_seconds=0,
        )


def test_execute_long_ssh_command_recovers_after_disconnect(scipion_vre):
    old_client = MagicMock()
    new_client = MagicMock()

    scipion_vre._get_ssh_client = MagicMock(return_value=new_client)
    scipion_vre._execute_ssh_command = MagicMock(
        side_effect=[
            "4321\n",  # launch_command -> PID
            Exception("socket closed"),  # first poll fails
            "0\n",  # poll after reconnect -> finished successfully
            "workflow completed",  # cat log output
            "",  # cleanup command
        ]
    )

    out = scipion_vre._execute_long_ssh_command(
        scipion_vre.ssh,
        old_client,
        "run-workflow",
        poll_seconds=0,
        timeout_seconds=10,
    )

    assert out == "workflow completed"
    old_client.close.assert_called_once()
    scipion_vre._get_ssh_client.assert_called_once_with(scipion_vre.ssh)


def test_post_happy_path(scipion_vre):
    ssh_client = MagicMock()
    scipion_vre._get_ssh_client = MagicMock(return_value=ssh_client)
    scipion_vre._execute_ssh_command = MagicMock(return_value="ok")
    scipion_vre._execute_long_ssh_command = MagicMock(side_effect=["sync-ok", "run-ok"])

    final_url = scipion_vre.post()

    assert final_url == scipion_vre.svc_url
    scipion_vre._get_ssh_client.assert_called_once_with(scipion_vre.ssh)
    assert scipion_vre._execute_ssh_command.call_count == 1
    assert scipion_vre._execute_long_ssh_command.call_count == 2

    workflow_url = scipion_vre._get_workflow_url()
    wget_command = scipion_vre._execute_ssh_command.call_args[0][1]
    assert wget_command == f"wget {workflow_url}"

    first_long_command = scipion_vre._execute_long_ssh_command.call_args_list[0][0][2]
    second_long_command = scipion_vre._execute_long_ssh_command.call_args_list[1][0][2]
    assert first_long_command == f"rsync -avP {EXPECTED_DATASET_URL} 13496"
    assert (
        second_long_command
        == f"{SCIPION_COMMAND} workflow_2D_xmipp.json.template 13496"
    )
    ssh_client.close.assert_called_once()


def test_get_data_set_url_prefers_haspart_file():
    crate = ROCrate(source=load_json("../scipion_tosca/ro-crate-metadata.json"))

    class DummyIMClient:
        def run_service(self, _dest):
            return {"url": "https://scipion.example.org"}

    vre = VREScipion(
        crate=crate,
        token="test-token",
        request_id=0,
        update_state=lambda **_kwargs: None,
        im_factory=lambda _token: DummyIMClient(),
    )

    assert vre._get_data_set_url() == EXPECTED_DATASET_URL


@patch("app.vres.scipion.paramiko.SSHClient")
def test_get_ssh_client_uses_nested_ssh_schema(mock_ssh_client_cls, scipion_vre):
    ssh_client = MagicMock()
    mock_ssh_client_cls.return_value = ssh_client

    fake_pkey = object()
    scipion_vre._get_private_key = MagicMock(return_value=fake_pkey)

    client = scipion_vre._get_ssh_client(scipion_vre.ssh)

    assert client is ssh_client
    scipion_vre._get_private_key.assert_called_once_with("dummy-key")
    ssh_client.connect.assert_called_once_with(
        hostname="worker.example.org",
        username="scipion",
        pkey=fake_pkey,
    )
