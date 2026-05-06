import logging
import requests
import copy
import time
import yaml
from typing import Any, Mapping
from imclient import IMClient
from app.config import settings
from app.exceptions import IMError

logging.basicConfig(level=logging.INFO)


class IM:

    GET_DATA_NODE_TEMPLATE = {
        "type": "tosca.nodes.SoftwareComponent",
        "interfaces": {
            "Standard": {
                "configure": {
                    "implementation": (
                        "https://raw.githubusercontent.com/grycap/"
                        "tosca/main/artifacts/download_data.yml"
                    ),
                    "inputs": {
                        "data_url": "",
                        "local_path": "/opt",
                        "wait_to_download": True,
                        "max_download_time": 1800,
                        "unarchive_file": False,
                    },
                }
            }
        },
        "requirements": [{"host": "simple_node"}],
    }

    def __init__(self, access_token: str | None):
        if not access_token:
            raise IMError("Access token not provided for IM.")
        auth = self._build_auth_config(access_token)

        im_endpoint = settings.im_endpoint

        self.client = IMClient.init_client(im_endpoint, auth)
        self.inf_id = None

    def _build_auth_config(self, access_token: str) -> list:
        """Build authentication configuration based on deployment type."""
        auth = [{"type": "InfrastructureManager", "token": access_token}]
        if not settings.im_cloud_provider.get("type"):
            raise IMError("Cloud provider type is not specified in the configuration.")

        if settings.im_cloud_provider["type"].lower() == "openstack":
            for key in ["host", "username", "auth_version", "tenant"]:
                if key not in settings.im_cloud_provider:
                    raise IMError(f"Missing {key} field in the OpenStack configuration")
            ost_auth = {
                "id": "eodcostcloud",
                "type": "OpenStack",
                "host": settings.im_cloud_provider["host"],
                "username": settings.im_cloud_provider["username"],
                "auth_version": settings.im_cloud_provider["auth_version"],
                "tenant": settings.im_cloud_provider["tenant"],
            }
            if settings.im_cloud_provider["auth_version"] == "3.x_oidc_access_token":
                ost_auth["password"] = access_token
            else:
                if "password" not in settings.im_cloud_provider:
                    raise IMError(
                        f"Missing password field in the OpenStack configuration"
                    )
                ost_auth["password"] = settings.im_cloud_provider["password"]
            if "domain" in settings.im_cloud_provider:
                ost_auth["domain"] = settings.im_cloud_provider["domain"]
            if "region" in settings.im_cloud_provider:
                ost_auth["service_region"] = settings.im_cloud_provider["region"]
            auth.append(ost_auth)
        elif settings.im_cloud_provider["type"].lower() == "egi":
            for key in ["VO", "site"]:
                if key not in settings.im_cloud_provider:
                    raise IMError(f"Missing {key} field in the EGI configuration")
            auth.append(
                {
                    "id": "eodcegicloud",
                    "type": "EGI",
                    "vo": settings.im_cloud_provider["VO"],
                    "token": access_token,
                    "host": settings.im_cloud_provider["site"],
                }
            )
        else:
            raise IMError(
                f"Unsupported cloud provider type: {settings.im_cloud_provider['type']}"
            )
        return auth

    @staticmethod
    def _get_tosca_template(url: str) -> dict:
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return yaml.safe_load(response.text)
        except requests.RequestException:
            logging.exception(f"Error fetching TOSCA template from {url}")
            raise IMError(f"Failed to fetch TOSCA template from: {url}")

    @staticmethod
    def _update_input_default(inputs: dict, key: str, value: Any) -> None:
        if value:
            if inputs.get(key, {}).get("default") is not None:
                inputs[key]["default"] = value
            else:
                logging.warning(f"The TOSCA template does not define '{key}' input.")

    @staticmethod
    def _add_inputs_to_tosca_template(
        tosca_template: dict, service: Mapping[str, Any]
    ) -> dict:
        memory = service.get("memoryRequirements")
        cpus = service.get("processorRequirements")
        storage = service.get("storageRequirements")
        num_cpus = 1  # Default value
        num_gpus = 0  # Default value
        if isinstance(cpus, str) and "vCPU" in cpus:
            num_cpus = int(cpus.replace("vCPU", "").strip())
        elif isinstance(cpus, list):
            for cpu in cpus:
                if "vCPU" in cpu:
                    num_cpus = int(cpu.replace("vCPU", "").strip())
                if "GPU" in cpu:
                    num_gpus = int(cpu.replace("GPU", "").strip())

        inputs = tosca_template["topology_template"]["inputs"]
        IM._update_input_default(inputs, "mem_size", memory)
        IM._update_input_default(inputs, "num_gpus", num_gpus)
        IM._update_input_default(inputs, "num_cpus", num_cpus)
        IM._update_input_default(inputs, "disk_size", storage)

        return tosca_template

    def _get_compute_nodes(self, tosca_dict: dict) -> dict:
        """Extracts compute nodes from the TOSCA template."""
        compute_nodes = {}
        node_templates = tosca_dict.get("topology_template", {}).get(
            "node_templates", {}
        )
        for node_name, node in node_templates.items():
            if node.get("type").endswith("Compute"):
                compute_nodes[node_name] = node
        return compute_nodes

    def _validate_input_file(self, input_file: dict) -> bool:
        """Validates if the input is of type File and has a url."""
        if input_file.get("@type") != "File":
            logging.warning("Input is not of type File, skipping.")
            return False
        if not input_file.get("url"):
            logging.warning("Input does not have a url, skipping.")
            return False
        return True

    def _parse_compute_and_dest(self, input_file: dict, compute_nodes: dict) -> tuple:
        """Parses contentLocation to extract compute node name and destination path."""
        content_location = input_file.get("contentLocation")
        compute_name = None
        if content_location and ":" in content_location:
            parts = content_location.split(":")
            return parts[0], parts[1]
        if compute_nodes:
            compute_name = list(compute_nodes.keys())[0]
        return compute_name, content_location

    def _validate_compute_node(self, compute_name: str, compute_nodes: dict) -> bool:
        """Validates if the compute node exists in the TOSCA template."""
        if not compute_name:
            logging.error("No compute node available.")
            return False
        if compute_name and compute_name not in compute_nodes:
            logging.error(
                "Compute node %s not found in TOSCA template, skipping file.",
                compute_name,
            )
            return False
        return True

    @staticmethod
    def _gen_get_data_node(
        file_url: str, file_dest: str, compute_name: Mapping[str, Any]
    ) -> dict:
        get_data = copy.deepcopy(IM.GET_DATA_NODE_TEMPLATE)
        get_data_inputs = get_data["interfaces"]["Standard"]["configure"]["inputs"]
        if file_dest:
            get_data_inputs["local_path"] = file_dest
        get_data_inputs["data_url"] = file_url
        get_data["requirements"][0]["host"] = compute_name
        return get_data

    def _add_files_to_tosca_template(
        self, tosca_template: dict, service: Mapping[str, Any]
    ) -> dict:
        """Adds input files to the TOSCA template for staging in."""
        input_files = service.get("input", [])
        if not input_files:
            return tosca_template

        compute_nodes = self._get_compute_nodes(tosca_template)
        node_templates = tosca_template.get("topology_template", {}).get(
            "node_templates", {}
        )

        for i, input_file in enumerate(input_files):
            if not self._validate_input_file(input_file):
                continue

            compute_name, file_dest = self._parse_compute_and_dest(
                input_file, compute_nodes
            )
            if not self._validate_compute_node(compute_name, compute_nodes):
                continue

            node_templates[f"get_data_{i}"] = self._gen_get_data_node(
                input_file.get("url"), file_dest, compute_name
            )

        return tosca_template

    def _gen_tosca_template(self, service: Mapping[str, Any]) -> dict:
        """
        Generates a TOSCA template for the service.
        """
        # get the TOSCA template from the service entity
        # get the memory and CPU requirements
        # edit the inputs of the TOSCA template
        # (we must use allways the same names for the inputs for cpu and memory, etc.)
        tosca_template_url = None
        has_part = service.get("hasPart", [])
        if has_part and has_part[0].get("encodingFormat") == "text/yaml":
            # Assuming the first part is the TOSCA template
            tosca_template_url = has_part[0].get("url")

        if not tosca_template_url:
            raise Exception("TOSCA template URL not found in service entity.")

        # Fetch the TOSCA template from the URL
        tosca_template = self._get_tosca_template(tosca_template_url)
        # Add inputs to the TOSCA template
        tosca_template = self._add_inputs_to_tosca_template(tosca_template, service)
        # Add input files to stage in
        tosca_template = self._add_files_to_tosca_template(tosca_template, service)

        return tosca_template

    def deploy_service(self, service: Mapping[str, Any]) -> str:
        """Deploys the service using using the TOSCA from the service."""
        tosca_template = self._gen_tosca_template(service)
        success, inf_id = self.client.create(
            yaml.safe_dump(tosca_template), desc_type="yaml"
        )
        if not success:
            logging.error(f"Failed to deploy service: {inf_id}")
            raise IMError(f"Failed to deploy service: {inf_id}")
        logging.info(f"Service deployed successfully with ID: {inf_id}")
        self.inf_id = inf_id
        return str(inf_id)

    def wait_for_service(self) -> None:
        """Waits for the service to be in 'configured' state, indicating it's ready."""
        if self.inf_id is None:
            raise IMError("No service deployed yet.")
        logging.info(f"Waiting for service {self.inf_id} to be ready...")

        max_time = settings.im_max_time
        wait = 0
        retries = 0
        state = "pending"
        pending_states = ["pending", "running", "unknown"]

        while (
            state in pending_states
            and retries < settings.im_max_retries
            and wait < max_time
        ):
            try:
                state = "unknown"
                success, res = self.client.get_infra_property(self.inf_id, "state")
                if success:
                    state = res["state"]
                else:
                    logging.error(
                        f"Failed to get infrastructure state: {res} ({retries + 1}/{settings.im_max_retries})."
                    )
            except Exception as e:
                logging.exception(
                    f"Error getting infrastructure state: {e} ({retries + 1}/{settings.im_max_retries})."
                )
                success = False

            if state == "unknown":
                retries += 1

            if state in pending_states:
                logging.debug(f"The infrastructure is in state: {state}. Wait ...")
                time.sleep(settings.im_sleep)
                wait += settings.im_sleep

        if state == "configured":
            logging.info(f"Service {self.inf_id} is ready.")
        else:
            msg = f"Service did not reach 'configured' state. Current state: {state}."
            if wait >= max_time:
                msg += "(Timeout)"
            logging.error(msg)

            try:
                # Get deployment log for debugging
                success, inflog = self.client.get_infra_property(self.inf_id, "contmsg")
                if success:
                    logging.debug(f"Deployment log: {inflog}")
                else:
                    logging.error(f"Failed to get deployment log {inflog}.")
            except Exception as e:
                logging.exception(f"Error getting deployment log: {e}")

            try:
                logging.debug("Destroying service after error.")
                self.destroy_service()
            except Exception:
                logging.exception("Failed to destroy service after error")

            raise IMError(msg)

    def get_service_outputs(self) -> Mapping[str, Any]:
        if self.inf_id is None:
            raise IMError("No service deployed yet.")
        success, res = self.client.get_infra_property(self.inf_id, "outputs")
        if not success:
            raise IMError("Failed to get service outputs.")
        # Assuming the service URL is the only output
        return res

    def destroy_service(self) -> None:
        if self.inf_id is None:
            return
        success, res = self.client.destroy(self.inf_id)
        if not success:
            raise IMError(f"Failed to destroy service: {res}")
        logging.info(f"Service {self.inf_id} destroyed successfully.")
        self.inf_id = None

    def run_service(self, dest: Mapping[str, Any]) -> Mapping[str, Any]:
        self.deploy_service(dest)
        self.wait_for_service()
        return self.get_service_outputs()
