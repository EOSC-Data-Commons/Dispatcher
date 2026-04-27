"""Galaxy VRE implementation.

This module implements the Galaxy workflow execution VRE, which submits
workflows to Galaxy instances using the Galaxy API.
"""

from typing import Any, Dict

from app.domain.rocrate.value_objects import FileInfo
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
    """Galaxy workflow execution VRE."""

    def get_default_service(self) -> str:
        """Return the default Galaxy service URL."""
        return GALAXY_DEFAULT_SERVICE

    def post(self) -> str:
        """Submit workflow to Galaxy and return the landing URL."""
        data = self._prepare_workflow_data()
        response_data = self._send_workflow_request(data)
        landing_id = self._extract_landing_id(response_data)
        return self._build_final_url(landing_id)

    def _prepare_workflow_data(self) -> Dict[str, Any]:
        """Prepare the workflow data for the API request.

        Returns:
            Dictionary containing workflow submission data for Galaxy API.
        """
        workflow = self.request_package.get_workflow_info()
        files = self.request_package.get_file_info_list()

        return {
            "public": GALAXY_PUBLIC_DEFAULT,
            "request_state": self._modify_for_api_data_input(files),
            "workflow_id": workflow.url,
            "workflow_target_type": GALAXY_WORKFLOW_TARGET_TYPE,
        }

    def _modify_for_api_data_input(self, files: list[FileInfo]) -> Dict[str, Any]:
        """Convert FileInfo objects to Galaxy API format.

        Args:
            files: List of FileInfo objects from RequestPackage.

        Returns:
            Dict mapping file names to their metadata for Galaxy API.
        """
        result: Dict[str, Any] = {}
        for file_info in files:
            result[file_info.name] = {
                "class": "File",
                "filetype": (
                    file_info.encoding_format.split("/")[-1]
                    if file_info.encoding_format
                    else ""
                ),
                "location": file_info.url,
            }
        return result

    def _send_workflow_request(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Send the workflow request to the Galaxy API.

        Args:
            data: Workflow submission data.

        Returns:
            JSON response from the Galaxy API.

        Raises:
            GalaxyAPIError: If the API request fails.
        """
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

    def _get_api_url(self) -> str:
        """Build the Galaxy API URL for workflow landings."""
        url = self.svc_url.rstrip("/")
        return f"{url}/api/workflow_landings"

    def _get_headers(self) -> Dict[str, str]:
        """Return headers for Galaxy API requests."""
        return {"Content-Type": "application/json", "Accept": "application/json"}

    def _extract_landing_id(self, response_data: Dict[str, Any]) -> str:
        """Extract the landing ID from the API response.

        Args:
            response_data: JSON response from Galaxy API.

        Returns:
            The UUID of the workflow landing.

        Raises:
            GalaxyAPIError: If UUID is missing from response.
        """
        uuid = response_data.get("uuid")
        if uuid is None:
            logging.error(
                f"{self.__class__.__name__}: Galaxy API response missing 'uuid' field"
            )
            raise exceptions.GalaxyAPIError("Galaxy API response missing 'uuid' field")
        return uuid

    def _build_final_url(self, landing_id: str) -> str:
        """Build the final workflow landing URL.

        Args:
            landing_id: The UUID of the workflow landing.

        Returns:
            Complete URL to access the workflow landing page.
        """
        url = self.svc_url.rstrip("/")
        return f"{url}/workflow_landings/{landing_id}?public={GALAXY_PUBLIC_DEFAULT}"


vre_factory.register(GALAXY_PROGRAMMING_LANGUAGE, VREGalaxy)
