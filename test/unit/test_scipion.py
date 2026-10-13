import pytest
import shlex
from unittest.mock import MagicMock, patch
from vre_rocrate import (
    FileReference,
    FormalParameter,
    VREPayload,
    SCIPION_PROGRAMMING_LANGUAGE,
    WorkflowDescriptor,
)

from app.constants import SCIPION_INSTANCE, SCIPION_DATA_DIR, SCIPION_USER
from app.exceptions import VREConfigurationError
from app.vres.scipion import VREScipion

EXPECTED_DATASET_URL = "rsync://ftp.ebi.ac.uk/empiar/world_availability/12944"
EXPECTED_WORKFLOW_URL = (
    "https://workflowhub.eu/workflows/1747/git/1/raw/workflow_simple.json"
)


def make_scipion_payload(files=None):
    return VREPayload(
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
    payload = make_scipion_payload(
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
        payload=payload,
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


@pytest.mark.parametrize("streaming", [None, False, True])
def test_post_happy_path(scipion_vre, streaming):
    if streaming is not None:
        scipion_vre.payload.workflow_inputs.append(
            FormalParameter(id="#streaming", name="streaming", default_value=streaming)
        )
    data_folder = EXPECTED_DATASET_URL.split("/")[-1]
    ssh_client = MagicMock()
    scipion_vre._get_ssh_client = MagicMock(return_value=ssh_client)
    scipion_vre._execute_ssh_command = MagicMock(
        side_effect=["ok", "67890", "12345"] if streaming else ["ok", "12345"]
    )
    scipion_vre._execute_long_ssh_command = MagicMock(return_value="sync-ok")

    final_url = scipion_vre.post()

    assert final_url == scipion_vre.svc_url
    scipion_vre._get_ssh_client.assert_called_once_with(scipion_vre.ssh)
    assert scipion_vre._execute_ssh_command.call_count == (3 if streaming else 2)

    workflow_url = scipion_vre._get_workflow_url()
    wget_command = scipion_vre._execute_ssh_command.call_args_list[0][0][1]
    assert (
        wget_command
        == f"sudo su - {SCIPION_USER} -c 'wget {workflow_url} -O {SCIPION_DATA_DIR}/{workflow_url.split('/')[-1]}'"
    )

    expected_data_command = f"sudo su - {SCIPION_USER} -c 'rsync -avP {EXPECTED_DATASET_URL} {SCIPION_DATA_DIR}'"
    if streaming:
        scipion_vre._execute_long_ssh_command.assert_not_called()
        download_command = scipion_vre._execute_ssh_command.call_args_list[1][0][1]
        assert shlex.split(download_command)[:3] == ["nohup", "bash", "-lc"]
        assert shlex.split(download_command)[3] == expected_data_command
        assert (
            "</dev/null >/tmp/scipion-download.log 2>&1 & echo $!" in download_command
        )
    else:
        scipion_vre._execute_long_ssh_command.assert_called_once_with(
            scipion_vre.ssh, ssh_client, expected_data_command
        )

    launch_command = scipion_vre._execute_ssh_command.call_args_list[-1][0][1]
    expected_run_command = (
        f"sudo su - {SCIPION_USER} -c '"
        f"python {SCIPION_DATA_DIR}/scipion_EMPIAR.py {data_folder} "
        f"--template {SCIPION_DATA_DIR}/workflow_simple.json "
        f"--scipion-user-data {SCIPION_DATA_DIR} "
        f"--instance {SCIPION_INSTANCE}'"
    )
    assert "nohup bash -lc" in launch_command
    launched_run_command = shlex.split(launch_command)[3]
    assert expected_run_command in launched_run_command
    assert "</dev/null >/tmp/scipion-workflow.log 2>&1 & echo $!" in launch_command

    ssh_client.close.assert_called_once()


def test_get_data_set_url_reads_payload_input_file():
    payload = make_scipion_payload(
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
        payload=payload,
    )

    assert vre._get_data_set_url() == EXPECTED_DATASET_URL


def test_get_data_set_url_errors_without_input_files(scipion_vre):
    scipion_vre.payload = make_scipion_payload()

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
