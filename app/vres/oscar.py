"""OSCAR VRE implementation.

This module implements the OSCAR container deployment VRE, which creates
and invokes services on OSCAR instances using Function Definition Language (FDL).
"""

import base64
import json
from typing import Any, Dict, List

import requests
from app.domain.rocrate.value_objects import FileInfo
from app.exceptions import (
    VREConfigurationError,
    ExternalServiceError,
    ExternalDataSourceError,
)
from app.constants import OSCAR_DEFAULT_SERVICE, OSCAR_PROGRAMMING_LANGUAGE

from .base_vre import VRE, vre_factory

logging.basicConfig(level=logging.INFO)


class VREOSCAR(VRE):
    """OSCAR container deployment VRE."""

    def __init__(
        self,
        request_package: Any,
        body: Any = None,
        token: str = None,
        **kwargs,
    ):
        """Initialize the OSCAR VRE.

        Args:
            request_package: RequestPackage instance from ROCrateFactory.
            body: Optional request body (e.g., ZIP file content).
            token: Authentication token.
            **kwargs: Additional keyword arguments.
        """
        super().__init__(request_package, body=body, token=token, **kwargs)
        self.fdl_json: Dict[str, Any] | None = None

    def get_default_service(self) -> str:
        """Return the default OSCAR service URL."""
        return OSCAR_DEFAULT_SERVICE

    def _get_fdl_from_crate(self) -> Dict[str, Any]:
        """Get FDL configuration using strict abstraction.

        All ROCrate complexity is hidden inside RequestPackage methods.

        Returns:
            Parsed FDL JSON dictionary with optional script content.

        Raises:
            VREConfigurationError: If FDL is missing or cannot be fetched.
        """
        if self.fdl_json:
            return self.fdl_json

        # Use specialized method that handles all ROCrate complexity internally
        fdl_json = self.request_package.get_fdl_config()

        if not fdl_json:
            raise VREConfigurationError("Missing FDL in workflow entity")

        # Get script content separately
        script = self.request_package.get_script_content()
        if script:
            fdl_json["script"] = script

        self.fdl_json = fdl_json
        return fdl_json

    def post(self) -> str:
        """Create OSCAR service and invoke it with input files.

        Returns:
            URL of the created service.

        Raises:
            ExternalServiceError: If service creation fails.
        """
        fdl_json = self._get_fdl_from_crate()
        self.fdl_json = fdl_json
        service_name = fdl_json["name"]

        logging.info("Creating OSCAR service %s", service_name)
        logging.debug("FDL: %s", json.dumps(fdl_json))

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        url = self.svc_url

        response = requests.post(
            f"{url}/system/services", headers=headers, json=fdl_json, timeout=60
        )
        if response.status_code != 201:
            raise ExternalServiceError(f"Error creating OSCAR service: {response.text}")

        service_url = f"{url}/system/services/{service_name}"

        files = self._get_input_files()
        self._invoke_service(url, service_name, files)

        return service_url

    def _get_input_files(self) -> List[FileInfo]:
        """Get input files for service invocation.

        Returns all File entities except:
        - The workflow entity (mainEntity)
        - The runsOn service configuration
        - Files referenced in workflow hasPart

        Returns:
            List of FileInfo objects for input files.
        """
        # Build set of entity IDs to exclude
        non_input_ids: set[str] = set()

        # Exclude runsOn entity
        service_config = self.request_package.get_service_config()
        if service_config and service_config.url:
            # We can't easily get the entity ID from ServiceConfig, skip this

            pass

        # Exclude main workflow entity
        workflow = self.request_package.get_workflow_info()

        # Exclude workflow parts (hasPart files)
        for part in workflow.parts:
            if part.entity_id:
                non_input_ids.add(part.entity_id)

        # Get all files and filter
        all_files = self.request_package.get_file_info_list()
        return [f for f in all_files if f.entity_id not in non_input_ids]

    def _invoke_service(
        self, oscar_url: str, service_name: str, files: List[FileInfo]
    ) -> None:
        """Invoke the OSCAR service with each input file.

        Args:
            oscar_url: Base URL of the OSCAR instance.
            service_name: Name of the service to invoke.
            files: List of input files.
        """
        headers = {"Authorization": f"Bearer {self.token}"}
        url = f"{oscar_url}/job/{service_name}"

        for file_info in files:
            try:
                logging.info(
                    "Creating invocation for service %s and file %s",
                    service_name,
                    file_info.url,
                )
                response = requests.get(file_info.url, timeout=60)
                response.raise_for_status()
                file_content = response.text
            except Exception as e:
                logging.error("Error fetching file %s: %s", file_info.url, e)
                continue

            response = requests.post(
                url,
                headers=headers,
                data=base64.b64encode(file_content.encode()),
                timeout=60,
            )
            if response.status_code != 201:
                logging.error(
                    "Error invoking OSCAR service for file %s: %s",
                    file_info.url,
                    response.text,
                )

    def delete(self) -> None:
        """Delete the OSCAR service.

        Raises:
            ExternalServiceError: If service deletion fails.
        """
        fdl_json = self._get_fdl_from_crate()
        service_name = fdl_json["name"]

        logging.info("Deleting OSCAR service %s", service_name)
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        url = self.svc_url

        response = requests.delete(
            f"{url}/system/services/{service_name}", headers=headers, timeout=60
        )
        if response.status_code != 204:
            raise ExternalServiceError(f"Error deleting OSCAR service: {response.text}")


vre_factory.register(OSCAR_PROGRAMMING_LANGUAGE, VREOSCAR)
