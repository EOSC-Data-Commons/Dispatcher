import logging
import requests
import time
import yaml
from imclient import IMClient
from app.config import settings


logging.basicConfig(level=logging.INFO)

default_im_endpoint = "https://appsgrycap.i3m.upv.es/im-dev/"


class IM:
    def __init__(self, access_token: str):
        auth = self._build_auth_config(access_token)

        if settings.im_endpoint:
            im_endpoint = settings.im_endpoint
        else:
            im_endpoint = default_im_endpoint
        self.client = IMClient.init_client(im_endpoint, auth)
        self.inf_id = None

    def _build_auth_config(self, access_token: str) -> list:
        """Build authentication configuration based on deployment type."""
        auth = [{"type": "InfrastructureManager", "token": access_token}]
        if not settings.im_cloud_provider.get("type"):
            raise ValueError("Cloud provider type is not specified in the configuration.")

        if settings.im_cloud_provider["type"].lower() == "openstack":
            for key in ["host", "username", "auth_version", "tenant"]:
                if key not in settings.im_cloud_provider:
                    raise ValueError(f"Missing {key} field in the OpenStack configuration")
            ost_auth = {
                "id": "eodcostcloud",
                "type": "OpenStack",
                "host": settings.im_cloud_provider["host"],
                "username": settings.im_cloud_provider["username"],
                "auth_version": settings.im_cloud_provider["auth_version"],
                "tenant": settings.im_cloud_provider["tenant"]
            }
            if settings.im_cloud_provider["auth_version"] == "3.x_oidc_access_token":
                ost_auth["password"] = access_token
            else:
                if "password" not in settings.im_cloud_provider:
                    raise ValueError(f"Missing {key} field in the OpenStack configuration")
                ost_auth["password"] = settings.im_cloud_provider["password"]
            if "domain" in settings.im_cloud_provider:
                ost_auth["domain"] = settings.im_cloud_provider["domain"]
            if "region" in settings.im_cloud_provider:
                ost_auth["service_region"] = settings.im_cloud_provider["region"]
            auth.append(ost_auth)
        elif settings.im_cloud_provider["type"].lower() == "egi":
            for key in ["VO", "site"]:
                if key not in settings.im_cloud_provider:
                    raise ValueError(f"Missing {key} field in the EGI configuration")
            auth.append({
                "id": "eodcegicloud",
                "type": "EGI",
                "vo": settings.im_cloud_provider["VO"],
                "token": access_token,
                "host": settings.im_cloud_provider["site"]
            })
        else:
            raise ValueError(
                f"Unsupported cloud provider type: {settings.im_cloud_provider['type']}"
            )
        return auth

    @staticmethod
    def _get_tosca_template(url: str) -> str:
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            logging.exception(f"Error fetching TOSCA template from {url}")
            raise Exception(f"Failed to fetch TOSCA template from: {url}")

    @staticmethod
    def _add_inputs_to_tosca_template(tosca_template: str, service: dict) -> str:
        memory = service.get("memoryRequirements", "2 GiB")
        cpus = service.get("processorRequirements", "1 vCPU")
        storage = service.get("storageRequirements", "0 GiB")
        tosca_dict = yaml.safe_load(tosca_template)
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

        inputs = tosca_dict["topology_template"]["inputs"]
        inputs["mem_size"]["default"] = memory
        inputs["num_gpus"]["default"] = num_gpus
        inputs["num_cpus"]["default"] = num_cpus
        inputs["disk_size"]["default"] = storage
        return yaml.dump(tosca_dict)

    def _gen_tosca_template(self, service: dict) -> str:
        """
        Generates a TOSCA template for the service.
        """
        # @TODO: get the TOSCA template from the service entity
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

        return tosca_template

    def deploy_service(self, service: dict) -> str:
        tosca_template = self._gen_tosca_template(service)
        success, inf_id = self.client.create(tosca_template, desc_type="yaml")
        if not success:
            logging.error(f"Failed to deploy service: {inf_id}")
            raise Exception(f"Failed to deploy service: {inf_id}")
        logging.info(f"Service deployed successfully with ID: {inf_id}")
        self.inf_id = inf_id
        return inf_id

    def wait_for_service(self) -> None:
        if self.inf_id is None:
            raise Exception("No service deployed yet.")
        logging.info(f"Waiting for service {self.inf_id} to be ready...")

        max_time = 36000  # 10h
        wait = 0
        unknown_count = 0
        state = "pending"
        pending_states = ["pending", "running", "unknown"]

        while state in pending_states and unknown_count < 3 and wait < max_time:
            success, res = self.client.get_infra_property(self.inf_id, "state")

            if success:
                state = res["state"]
            else:
                state = "unknown"

            if state == "unknown":
                unknown_count += 1

            if state in pending_states:
                logging.debug(f"The infrastructure is in state: {state}. Wait ...")
                time.sleep(30)
                wait += 30

        if state == "configured":
            logging.info(f"Service {self.inf_id} is ready.")
        elif wait >= max_time:
            raise TimeoutError("Timeout waiting for service to be ready.")
        else:
            if state == "unconfigured":
                success, inflog = self.client.get_infra_property(self.inf_id, "contmsg")
                if success:
                    logging.debug(f"Deployment log: {inflog}")
                else:
                    logging.debug("Failed to get deployment log.")
            raise Exception(
                f"Service did not reach 'configured' state. Current state: {state}"
            )

    def get_service_outputs(self) -> str:
        if self.inf_id is None:
            raise Exception("No service deployed yet.")
        success, res = self.client.get_infra_property(self.inf_id, "outputs")
        if not success:
            raise Exception("Failed to get service outputs.")
        # Assuming the service URL is the only output
        return res

    def destroy_service(self) -> None:
        if self.inf_id is None:
            return
        success, res = self.client.destroy(self.inf_id)
        if not success:
            raise Exception(f"Failed to destroy service: {res}")
        logging.info(f"Service {self.inf_id} destroyed successfully.")
        self.inf_id = None

    def run_service(self, service: dict) -> str:
        try:
            self.deploy_service(service)
            self.wait_for_service()
            return self.get_service_outputs()
        except Exception as e:
            try:
                logging.error(f"Error during service deployment: {e}")
                inflog = self.client.get_infra_property(self.inf_id, "contmsg")
                logging.debug(f"Deployment log: {inflog}")
                self.destroy_service()
            except Exception:
                logging.exception(f"Failed to destroy service after error")
        return None
