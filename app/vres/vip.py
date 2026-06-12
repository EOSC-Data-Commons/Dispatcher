from .base_vre import VRE, vre_factory
import requests
import logging
from app import exceptions
from vre_rocrate import VIP_PROGRAMMING_LANGUAGE
from app.constants import VIP_DEFAULT_SERVICE, VIP_DEFAULT_RESULTS_LOCATION

logger = logging.getLogger(__name__)


class VREVIP(VRE):
    def get_default_service(self) -> str:
        return VIP_DEFAULT_SERVICE

    def post(self) -> str:
        api_key = getattr(self, "api_key", None)
        if not api_key:
            raise exceptions.VREConfigurationError(
                "Missing API key: provide API-Key header in the request"
            )

        payload = self._build_payload()
        headers = {
            "apikey": api_key,
            "Content-Type": "application/json",
        }
        url = f"{self.svc_url}/rest/executions"

        logger.info("Creating VIP execution: %s", payload["name"])
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error("VIP API request failed: %s", e)
            raise exceptions.ExternalServiceError("VIP API call failed") from e

        # VIP API returns no response body on success
        return f"{self.svc_url}/home.html"

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
        return self._parse_pipeline_identifier(pipeline)

    @staticmethod
    def _parse_pipeline_identifier(url: str) -> str:
        """Extract pipeline name/version from a VIP pipeline URL.

        Example:
            'https://vip.creatis.insa-lyon.fr/rest/pipelines/CQUEST/0.6'
            -> 'CQUEST/0.6'
        """
        from urllib.parse import urlparse

        path = urlparse(url).path.strip("/")
        parts = path.split("/")
        # The pipeline identifier is the last two path segments
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"
        raise exceptions.VREConfigurationError(
            f"Cannot parse pipeline identifier from URL: {url}"
        )

    def _map_input_values(self) -> dict:
        result = {}
        for f in self.request_package.input_files:
            file_url = f.url or f.id
            result[f.name] = file_url
        return result


vre_factory.register(VIP_PROGRAMMING_LANGUAGE, VREVIP)
