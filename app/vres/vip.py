from .base_vre import VRE, vre_factory
import requests
import logging
from app import exceptions
from vre_rocrate import VIP_PROGRAMMING_LANGUAGE
from app.constants import VIP_DEFAULT_SERVICE, VIP_DEFAULT_RESULTS_LOCATION

logging.basicConfig(level=logging.INFO)

# Hardcoded per-user API key for VIP
VIP_API_KEY = "9pr5fpfnom57hphp06ee9co70f"


class VREVIP(VRE):
    def get_default_service(self) -> str:
        return VIP_DEFAULT_SERVICE

    def post(self) -> str:
        payload = self._build_payload()
        headers = {
            "apikey": VIP_API_KEY,
            "Content-Type": "application/json",
        }
        url = f"{self.svc_url}/rest/executions"

        logging.info("Creating VIP execution: %s", payload["name"])
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
        except requests.RequestException as e:
            logging.error("VIP API request failed: %s", e)
            raise exceptions.ExternalServiceError("VIP API call failed") from e

        # VIP API returns no response body on success
        return f"{self.svc_url}/home"

    def _build_payload(self) -> dict:
        name = self._get_execution_name()
        pipeline_identifier = self._get_pipeline_identifier()
        input_values = self._map_input_values()

        return {
            "name": name,
            "pipelineIdentifier": pipeline_identifier,
            "resultsLocation": VIP_DEFAULT_RESULTS_LOCATION,
            "inputValues": input_values,
        }

    def _get_execution_name(self) -> str:
        return f"vip-execution-{self._request_id}"

    def _get_pipeline_identifier(self) -> str:
        pipeline = self.request_package.workflow_url
        if pipeline is None:
            raise exceptions.VREConfigurationError(
                "Missing pipelineIdentifier (workflow URL) in VIP request"
            )
        return pipeline

    def _map_input_values(self) -> dict:
        result = {}
        for f in self.request_package.input_files:
            file_url = f.url or f.id
            result[f.name] = file_url
        return result


vre_factory.register(VIP_PROGRAMMING_LANGUAGE, VREVIP)
