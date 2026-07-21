import pytest
import shlex
from unittest.mock import MagicMock, patch
from vre_rocrate import (
    FileReference,
    RequestPackage,
    SCIPION_PROGRAMMING_LANGUAGE,
    WorkflowDescriptor,
)

from app.constants import SCIPION_CONTAINER, SCIPION_DATA_DIR, SCIPION_USER
from app.exceptions import VREConfigurationError
from app.vres.scipion import VREScipion

EXPECTED_DATASET_URL = "rsync://ftp.ebi.ac.uk/empiar/world_availability/12944"
EXPECTED_WORKFLOW_URL = (
    "https://workflowhub.eu/workflows/1747/git/1/raw/workflow_simple.json"
)


def make_scipion_request_package(files=None):
    return RequestPackage(
        vre_type=SCIPION_PROGRAMMING_LANGUAGE,
        programming_language=SCIPION_PROGRAMMING_LANGUAGE,
        workflow=WorkflowDescriptor(
            id="#workflow",
            type="SoftwareSourceCode",
            url=EXPECTED_WORKFLOW_URL,
            programming_language_id=SCIPION_PROGRAMMING_LANGUAGE,
        ),
        files=[] if files is None else files,
        raw_crate={},
    )


@pytest.fixture
def scipion_vre():
    request_package = make_scipion_request_package(
        files=[
            FileReference(
                id=EXPECTED_DATASET_URL,
                name="empiar_dataset",
                url=EXPECTED_DATASET_URL,
            )
        ]
    )

    vre = VREScipion(
        token="test-token",
        request_id=0,
        update_state=lambda **_kwargs: None,
        request_package=request_package,
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
    data_folder = EXPECTED_DATASET_URL.split("/")[-1]
    ssh_client = MagicMock()
    scipion_vre._get_ssh_client = MagicMock(return_value=ssh_client)
    scipion_vre._execute_ssh_command = MagicMock(side_effect=["ok", "12345"])
    scipion_vre._execute_long_ssh_command = MagicMock(return_value="sync-ok")

    final_url = scipion_vre.post()

    assert final_url == scipion_vre.svc_url
    scipion_vre._get_ssh_client.assert_called_once_with(scipion_vre.ssh)
    assert scipion_vre._execute_ssh_command.call_count == 2
    assert scipion_vre._execute_long_ssh_command.call_count == 1

    workflow_url = scipion_vre._get_workflow_url()
    wget_command = scipion_vre._execute_ssh_command.call_args_list[0][0][1]
    assert (
        wget_command
        == f"sudo su - {SCIPION_USER} -c 'wget {workflow_url} -O {SCIPION_DATA_DIR}/{workflow_url.split('/')[-1]}'"
    )

    first_long_command = scipion_vre._execute_long_ssh_command.call_args[0][2]
    assert (
        first_long_command
        == f"sudo su - {SCIPION_USER} -c 'rsync -avP {EXPECTED_DATASET_URL} {SCIPION_DATA_DIR}'"
    )

    launch_command = scipion_vre._execute_ssh_command.call_args_list[1][0][1]
    expected_run_command = (
        f"sudo su - {SCIPION_USER} -c '"
        f"python {SCIPION_DATA_DIR}/scipion_EMPIAR.py {data_folder} "
        f"--template {SCIPION_DATA_DIR}/workflow_simple.json "
        f"--scipion-user-data {SCIPION_DATA_DIR} "
        f"--container {SCIPION_CONTAINER}'"
    )
    assert "nohup bash -lc" in launch_command
    launched_run_command = shlex.split(launch_command)[3]
    assert expected_run_command in launched_run_command
    assert "</dev/null >/tmp/scipion-workflow.log 2>&1 & echo $!" in launch_command

    ssh_client.close.assert_called_once()


def test_get_data_set_url_reads_request_package_input_file():
    request_package = make_scipion_request_package(
        files=[
            FileReference(
                id=EXPECTED_DATASET_URL,
                name="10146",
                url=EXPECTED_DATASET_URL,
            )
        ]
    )

    vre = VREScipion(
        token="test-token",
        request_id=0,
        update_state=lambda **_kwargs: None,
        request_package=request_package,
    )

    assert vre._get_data_set_url() == EXPECTED_DATASET_URL


def test_get_data_set_url_errors_without_input_files(scipion_vre):
    scipion_vre.request_package = make_scipion_request_package()

    with pytest.raises(VREConfigurationError, match="No data file with URL found"):
        scipion_vre._get_data_set_url()


@patch("app.vres.scipion.paramiko.SSHClient")
def test_get_ssh_client(mock_ssh_client_cls, scipion_vre):
    ssh_client = MagicMock()
    mock_ssh_client_cls.return_value = ssh_client

    fake_pkey = object()
    VREScipion._get_private_key = MagicMock(return_value=fake_pkey)

    client = scipion_vre._get_ssh_client(scipion_vre.ssh)

    assert client is ssh_client
    VREScipion._get_private_key.assert_called_once_with("dummy-key")
    ssh_client.connect.assert_called_once_with(
        hostname="worker.example.org",
        username="scipion",
        pkey=fake_pkey,
    )
