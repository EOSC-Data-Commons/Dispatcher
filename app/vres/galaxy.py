from .base_vre import VRE, vre_factory
import requests
import logging
from app import exceptions
from app.constants import (
    GALAXY_DEFAULT_SERVICE,
    GALAXY_PROGRAMMING_LANGUAGE,
    GALAXY_PUBLIC_DEFAULT,
    GALAXY_WORKFLOW_TARGET_TYPE,
)

logging.basicConfig(level=logging.INFO)


class VREGalaxy(VRE):
    def get_default_service(self):
        return GALAXY_DEFAULT_SERVICE

    def post(self):
        data = self._prepare_workflow_data()
        response_data = self._send_workflow_request(data)
        landing_id = self._extract_landing_id(response_data)
        return self._build_final_url(landing_id)

    def _prepare_workflow_data(self):
        """Prepare the workflow data for the API request."""
        files = self.request_package.get_file_entities()
        workflow_url = self.request_package.get_workflow_url()

        return {
            "public": GALAXY_PUBLIC_DEFAULT,
            "request_state": self._modify_for_api_data_input(files),
            "workflow_id": workflow_url,
            "workflow_target_type": GALAXY_WORKFLOW_TARGET_TYPE,
        }

    def _modify_for_api_data_input(self, files):
        """Convert file entities to API-compatible format.

        Uses RequestPackage to extract file info and builds the Galaxy API format.

        Args:
            files: List of file entities from the crate.

        Returns:
            Dict mapping file names to their metadata for Galaxy API.
        """
        result = {}
        for name, file_type, location in self.request_package.extract_file_info(files):
            result[name] = {
                "class": "File",
                "filetype": file_type.split("/")[-1] if file_type else "",
                "location": location,
            }
        return result

    def _send_workflow_request(self, data):
        """Send the workflow request to the Galaxy API."""
        headers = self._get_headers()

        api_url = self._get_api_url()

        logging.info(f"{self.__class__.__name__}: calling {api_url} with {data}")

        try:
            print(f"Sending request to Galaxy API... {data}")
            response = requests.post(api_url, headers=headers, json=data)
            response.raise_for_status()
        except requests.RequestException as e:
            logging.error(f"{self.__class__.__name__}: API request failed: {e}")
            raise exceptions.GalaxyAPIError("Galaxy API call failed") from e
        return response.json()

    def _get_api_url(self):
        url = self.svc_url.rstrip("/")
        api_url = f"{url}/api/workflow_landings"
        return api_url

    def _get_headers(self):
        return {"Content-Type": "application/json", "Accept": "application/json"}

    def _extract_landing_id(self, response_data):
        """Extract the landing ID from the API response."""
        uuid = response_data.get("uuid")
        if uuid is None:
            logging.error(
                f"{self.__class__.__name__}: Galaxy API response missing 'uuid' field"
            )
            raise exceptions.GalaxyAPIError("Galaxy API response missing 'uuid' field")
        return uuid

    def _build_final_url(self, landing_id):
        """Build the final workflow landing URL."""
        url = self.svc_url.rstrip("/")
        public = GALAXY_PUBLIC_DEFAULT
        return f"{url}/workflow_landings/{landing_id}?public={public}"


vre_factory.register(GALAXY_PROGRAMMING_LANGUAGE, VREGalaxy)

