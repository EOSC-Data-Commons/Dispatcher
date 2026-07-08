import pytest
from unittest.mock import MagicMock, patch
from vre_rocrate import (
    FileReference,
    RequestPackage,
    SCIPION_PROGRAMMING_LANGUAGE,
    WorkflowDescriptor,
)

from app.constants import SCIPION_CONTAINER, SCIPION_DATA_DIR
from app.exceptions import VREConfigurationError
from app.vres.scipion import VREScipion

EXPECTED_DATASET_URL = "rsync://ftp.ebi.ac.uk/empiar/world_availability/12944/"
EXPECTED_WORKFLOW_URL = (
    "https://workflowhub.eu/workflows/1747/git/1/raw/workflow_simple.json"
)


def make_scipion_rocrate():
    """Build the Scipion RO-Crate metadata fixture used by vre_rocrate."""
    return {
        "@context": "https://w3id.org/ro/crate/1.1/context",
        "@graph": [
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "about": {"@id": "./"},
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
            },
            {
                "@id": "./",
                "@type": "Dataset",
                "name": "Scipion Example Workflow",
                "description": "This is an example of a workflow using the Scipion platform with TOSCA.",
                "datePublished": "2025-05-06T14:35:47+00:00",
                "license": {"@id": "https://spdx.org/licenses/GPL-3.0"},
                "creator": {"@id": "#author-dispatcher"},
                "mainEntity": {"@id": EXPECTED_WORKFLOW_URL},
                "hasPart": [
                    {"@id": EXPECTED_WORKFLOW_URL},
                    {"@id": EXPECTED_DATASET_URL},
                ],
            },
            {
                "@id": EXPECTED_WORKFLOW_URL,
                "@type": ["File", "SoftwareSourceCode", "ComputationalWorkflow"],
                "conformsTo": {
                    "@id": "https://bioschemas.org/profiles/ComputationalWorkflow/0.5-DRAFT-2020_07_21/"
                },
                "name": "Example scipion workflow",
                "description": "A simple Scipion workflow for demonstration purposes.",
                "programmingLanguage": {"@id": "#scipion-lang"},
                "creator": {"@id": "#author-dispatcher"},
                "dateCreated": "2025-05-06",
                "license": {"@id": "https://spdx.org/licenses/GPL-3.0"},
                "sdPublisher": {"@id": "#workflow-hub"},
                "version": "1.0.0",
                "runtimePlatform": {"@id": "#destination"},
                "input": [{"@id": "#input-empiar-dataset"}],
                "output": [{"@id": "#output-result"}],
            },
            {
                "@id": "#input-empiar-dataset",
                "@type": "FormalParameter",
                "conformsTo": {
                    "@id": "https://bioschemas.org/profiles/FormalParameter/0.1-DRAFT-2020_07_21/"
                },
                "name": "empiar_dataset",
                "defaultValue": {"@id": EXPECTED_DATASET_URL},
            },
            {
                "@id": "#output-result",
                "@type": "FormalParameter",
                "conformsTo": {
                    "@id": "https://bioschemas.org/profiles/FormalParameter/0.1-DRAFT-2020_07_21/"
                },
                "name": "result",
                "additionalType": {"@id": "http://edamontology.org/data_3671"},
                "encodingFormat": {"@id": "http://edamontology.org/format_2330"},
            },
            {
                "@id": "#scipion-lang",
                "@type": "ComputerLanguage",
                "identifier": SCIPION_PROGRAMMING_LANGUAGE,
                "name": "Scipion",
                "url": SCIPION_PROGRAMMING_LANGUAGE,
            },
            {
                "@id": EXPECTED_DATASET_URL,
                "@type": "Dataset",
                "name": "empiar_dataset",
            },
            {
                "@id": "#destination",
                "@type": "RuntimePlatform",
                "name": "Infrastructure Manager",
                "memoryRequirements": "4 GiB",
                "processorRequirements": ["2 vCPU"],
                "storageRequirements": "200 GiB",
                "installUrl": "https://raw.githubusercontent.com/grycap/tosca/refs/heads/eosc_beyond/templates/scipion.yaml",
            },
            {
                "@id": "#author-dispatcher",
                "@type": "Person",
                "name": "Dispatcher System",
            },
            {
                "@id": "#workflow-hub",
                "@type": "Organization",
                "name": "Example Workflow Hub",
                "url": "http://example.com/workflows/",
            },
            {
                "@id": "https://spdx.org/licenses/GPL-3.0",
                "@type": "CreativeWork",
                "name": "GNU General Public License v3.0",
                "alternateName": "GPL-3.0",
            },
            {
                "@id": "http://edamontology.org/data_3671",
                "@type": "Thing",
                "name": "Text",
            },
            {
                "@id": "http://edamontology.org/format_2330",
                "@type": "Thing",
                "name": "Plain text format",
            },
        ],
    }


def make_scipion_request_package(files=None, raw_crate=None):
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
        raw_crate={} if raw_crate is None else raw_crate,
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
        ],
        raw_crate=make_scipion_rocrate(),
    )

    class DummyIMClient:
        def run_service(self, _dest):
            return {"url": "https://scipion.example.org"}

    vre = VREScipion(
        token="test-token",
        request_id=0,
        update_state=lambda **_kwargs: None,
        im_factory=lambda _token: DummyIMClient(),
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
    assert wget_command == f"wget {workflow_url}"

    first_long_command = scipion_vre._execute_long_ssh_command.call_args[0][2]
    assert (
        first_long_command
        == f"rsync -avP {EXPECTED_DATASET_URL} {SCIPION_DATA_DIR}/{data_folder}"
    )

    launch_command = scipion_vre._execute_ssh_command.call_args_list[1][0][1]
    expected_run_command = (
        f"python {SCIPION_DATA_DIR}/scipion_EMPIAR.py {data_folder} "
        f"--template {SCIPION_DATA_DIR}/workflow_simple.json "
        f"--scipion-user-data {SCIPION_DATA_DIR}"
    )
    assert "nohup bash -lc" in launch_command
    assert expected_run_command in launch_command
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

    class DummyIMClient:
        def run_service(self, _dest):
            return {"url": "https://scipion.example.org"}

    vre = VREScipion(
        token="test-token",
        request_id=0,
        update_state=lambda **_kwargs: None,
        im_factory=lambda _token: DummyIMClient(),
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
