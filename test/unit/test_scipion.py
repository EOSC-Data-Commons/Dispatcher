import pytest
from unittest.mock import MagicMock

from app.constants import SCIPION_COMMAND, SCIPION_PROGRAMMING_LANGUAGE
from app.exceptions import VREConfigurationError
from app.vres.scipion import VREScipion
from fixtures.dummy_crate import DummyCrate, DummyEntity, WORKFLOW_URL


@pytest.fixture
def scipion_vre():
    workflow = DummyEntity(
        _type="Dataset",
        url=WORKFLOW_URL,
        programmingLanguage={"identifier": SCIPION_PROGRAMMING_LANGUAGE},
    )
    data_file = DummyEntity(
        _type="File",
        name="dataset.mrc",
        encodingFormat="application/octet-stream",
        url="https://data.example.org/dataset.mrc",
    )
    crate = DummyCrate(
        main_entity=workflow, other_entities=[data_file], root_dataset={}
    )

    vre = VREScipion(
        crate=crate,
        token="test-token",
        request_id=0,
        update_state=None,
    )
    vre.ssh = {
        "host": "worker.example.org",
        "port": 22,
        "username": "scipion",
        "key": "dummy-key",
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

    wget_command = scipion_vre._execute_ssh_command.call_args[0][1]
    assert wget_command == f"wget {WORKFLOW_URL}"

    first_long_command = scipion_vre._execute_long_ssh_command.call_args_list[0][0][2]
    second_long_command = scipion_vre._execute_long_ssh_command.call_args_list[1][0][2]
    assert (
        first_long_command
        == "rsync -avP https://data.example.org/dataset.mrc /opt/dataset.mrc"
    )
    assert second_long_command == f"{SCIPION_COMMAND} myworkflow.ga /opt/dataset.mrc"
    ssh_client.close.assert_called_once()
