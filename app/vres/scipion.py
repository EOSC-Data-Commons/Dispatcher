from .base_vre import VRE, vre_factory
import io
import paramiko
import logging
import shlex
import time
import uuid
from app.exceptions import VREConfigurationError, WorkflowURLError
from app.constants import (
    SCIPION_COMMAND,
    SCIPION_DEFAULT_SERVICE,
    SCIPION_PROGRAMMING_LANGUAGE,
    SCIPION_MAX_EXECUTION_TIME_SECONDS,
)

logging.basicConfig(level=logging.INFO)


class VREScipion(VRE):
    def get_default_service(self):
        return SCIPION_DEFAULT_SERVICE

    def post(self):
        if not self.ssh:
            raise VREConfigurationError("Missing 'ssh' information for Scipion VRE")

        ssh_client = None
        try:
            # Step 1: Connect to the remote service via SSH
            logging.debug(f"Connecting to remote service via SSH")
            ssh_client = self._get_ssh_client(self.ssh)

            # Step 2: Download the workflow
            workflow_url = self._get_workflow_url()
            logging.info(f"Downloading workflow from {workflow_url}")
            get_workflow_command = f"wget {workflow_url}"
            stdout = self._execute_ssh_command(ssh_client, get_workflow_command)
            logging.debug(f"Workflow download output: {stdout}")

            # Step 3: Download the data set
            self.update_task_status("Downloading data")
            data_url = self._get_data_set_url()
            logging.info(f"Downloading data from {data_url}")
            data_folder = data_url.split("/")[-1]
            get_data_command = f"rsync -avP {data_url} {data_folder}"
            out = self._execute_long_ssh_command(self.ssh, ssh_client, get_data_command)
            logging.debug(f"Data download output: {out}")

            # Step 4: Run the workflow with the data
            self.update_task_status("Executing workflow")
            workflow_file = workflow_url.split("/")[-1]
            run_command = f"{SCIPION_COMMAND} {workflow_file} {data_folder}"
            logging.info(f"Run workflow with command: {run_command}")
            out = self._execute_long_ssh_command(self.ssh, ssh_client, run_command)
            self.update_task_status("Workflow execution completed")
            logging.debug(f"Workflow execution output: {out}")
        except Exception as e:
            logging.error(f"Error during SSH operations: {str(e)}")
            raise VREConfigurationError(f"Error during SSH operations: {str(e)}")
        finally:
            if ssh_client:
                ssh_client.close()

        return self.svc_url

    @staticmethod
    def _execute_ssh_command(ssh_client, command):
        """Execute a command over SSH and return its output, raising an error if it fails."""
        _, stdout, stderr = ssh_client.exec_command(command)
        return_code = stdout.channel.recv_exit_status()
        if return_code != 0:
            out = stdout.read().decode() + stderr.read().decode()
            logging.error(f"Command '{command}' failed: {out}")
            raise VREConfigurationError(f"Command '{command}' failed: {out}")
        return stdout.read().decode()

    def _execute_long_ssh_command(
        self,
        ssh_info,
        ssh_client,
        command,
        poll_seconds=10,
        timeout_seconds=SCIPION_MAX_EXECUTION_TIME_SECONDS,
    ):
        """Execute a long-running command over SSH, polling for completion and handling reconnects."""
        run_id = uuid.uuid4().hex
        log_file = f"/tmp/scipion-{run_id}.log"
        rc_file = f"/tmp/scipion-{run_id}.rc"

        wrapped_command = (
            f"{command} > {shlex.quote(log_file)} 2>&1; "
            f"echo $? > {shlex.quote(rc_file)}"
        )
        launch_command = (
            f"nohup bash -lc {shlex.quote(wrapped_command)} "
            f"</dev/null >/dev/null 2>&1 & echo $!"
        )

        pid = self._execute_ssh_command(ssh_client, launch_command).strip()
        logging.info(f"Started long remote command with PID {pid}")

        deadline = time.time() + timeout_seconds
        status = "RUNNING"

        while time.time() < deadline:
            try:
                status = self._execute_ssh_command(
                    ssh_client,
                    (
                        f"if [ -f {shlex.quote(rc_file)} ]; then "
                        f"cat {shlex.quote(rc_file)}; "
                        f"else echo RUNNING; fi"
                    ),
                ).strip()
            except Exception as exc:
                logging.warning(
                    f"SSH connection lost while polling, reconnecting: {exc}"
                )
                try:
                    ssh_client.close()
                except Exception:
                    pass
                ssh_client = self._get_ssh_client(ssh_info)
                continue

            if status != "RUNNING":
                break

            time.sleep(poll_seconds)

        if status == "RUNNING":
            raise VREConfigurationError(
                f"Command '{command}' timed out after {timeout_seconds} seconds"
            )

        output = self._execute_ssh_command(ssh_client, f"cat {shlex.quote(log_file)}")
        self._execute_ssh_command(
            ssh_client,
            f"rm -f {shlex.quote(log_file)} {shlex.quote(rc_file)}",
        )

        if status != "0":
            raise VREConfigurationError(
                f"Command '{command}' failed with exit code {status}: {output}"
            )

        return output

    def _get_data_set_url(self):
        """Extract data set URL from the crate."""
        for elem in self.crate.root_dataset.get("hasPart", []):
            if elem.get("@type") == "File":
                if elem.get("url"):
                    return elem.get("url")
        raise VREConfigurationError(
            "No data file with URL found in crate's root dataset"
        )

    def _get_workflow_url(self):
        """Extract workflow URL from the crate."""
        workflow_url = self.crate.mainEntity.get("url")
        if workflow_url is None:
            # checked here, as some other vres might be actual files
            logging.error(f"{self.__class__.__name__}: Missing url in workflow entity")
            raise WorkflowURLError("Missing url in workflow entity")
        return workflow_url

    @staticmethod
    def _get_ssh_client(ssh_info):
        """Create and return an paramiko SSH client based on the provided SSH info."""
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        key_str = ssh_info.get("node_creds", {}).get("value", {}).get("token")
        if not key_str:
            raise VREConfigurationError("Missing SSH private key in 'ssh' information")
        pkey = VREScipion._get_private_key(key_str)
        hostname = ssh_info.get("node_ip").get("value")
        if not hostname:
            raise VREConfigurationError("Missing SSH hostname in 'ssh' information")
        username = ssh_info.get("node_creds", {}).get("value", {}).get("user")
        if not username:
            raise VREConfigurationError("Missing SSH username in 'ssh' information")

        ssh_client.connect(hostname=hostname, username=username, pkey=pkey)
        return ssh_client

    @staticmethod
    def _get_private_key(key_str):
        """Try to parse the private key string with different key types."""
        for kype in [paramiko.RSAKey, paramiko.ECDSAKey, paramiko.Ed25519Key]:
            try:
                return kype.from_private_key(io.StringIO(key_str))
            except Exception:
                pass
        raise VREConfigurationError("Invalid private key")


vre_factory.register(SCIPION_PROGRAMMING_LANGUAGE, VREScipion)
