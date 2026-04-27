"""ScienceMesh VRE implementation.

This module implements the ScienceMesh OCM sharing VRE, which creates
shares in the ScienceMesh federation using Open Cloud Mesh protocol.
"""

from typing import Any, Dict

import requests
from app.config import settings
from app.constants import (
    SCIENCEMESH_DEFAULT_SERVICE,
    SCIENCEMESH_PROGRAMMING_LANGUAGE,
)
from app.domain.rocrate.value_objects import CustomEntityInfo
from app.exceptions import MissingOCMParameters, ScienceMeshAPIError

from .base_vre import VRE, vre_factory

logging.basicConfig(level=logging.INFO)


class VREScienceMesh(VRE):
    """ScienceMesh OCM sharing VRE."""

    def get_default_service(self) -> str:
        """Return the default ScienceMesh service URL."""
        return SCIENCEMESH_DEFAULT_SERVICE

    def post(self) -> Dict[str, Any]:
        """Create an OCM share and return the response.

        Returns:
            JSON response from the ScienceMesh API.

        Raises:
            ScienceMeshAPIError: If the API request fails.
        """
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        data = self.create_ocm_share_request()

        try:
            logging.info(f"{self.__class__.__name__}: calling {self.svc_url}")
            response = requests.post(
                f"{self.svc_url}/ocm/shares",
                headers=headers,
                json=data,
            )
            logging.info(f"{self.__class__.__name__}: returned {response.text}")
            response.raise_for_status()
        except requests.RequestException as e:
            logging.error(f"{self.__class__.__name__}: API request failed: {e}")
            raise ScienceMeshAPIError("ScienceMesh API call failed") from e
        return response.json()

    def create_ocm_share_request(self) -> Dict[str, Any]:
        """Create the OCM share request payload.

        Uses typed value objects from RequestPackage instead of raw entity access.

        Returns:
            Dictionary containing the OCM share request data.

        Raises:
            MissingOCMParameters: If required entities are missing.
        """
        receiver = self.request_package.get_custom_entity_info("#receiver")
        owner = self.request_package.get_custom_entity_info("#owner")
        sender = self.request_package.get_custom_entity_info("#sender")
        destination_info = self.request_package.get_custom_entity_info("#destination")

        # Use destination URL if available, otherwise use service URL
        destination_url = (
            destination_info.properties.get("url") if destination_info else None
        )
        if not destination_url:
            destination_url = self.svc_url

        if not receiver or not owner or not sender:
            raise MissingOCMParameters(
                "Missing required entities (receiver, owner, sender) for OCM share request"
            )

        sender_userid = self._generate_userid(sender)

        crate_metadata = self.request_package.get_crate_metadata()

        # Create OCM share request JSON structure
        ocm_share_request = {
            "shareWith": receiver.userid,
            "name": crate_metadata.name,
            "description": crate_metadata.description,
            "providerId": "n/a",
            "resourceId": "n/a",
            "owner": owner.userid,
            "senderDisplayName": sender.name,
            "sender": sender_userid,
            "resourceType": "embedded",
            "shareType": "user",
            "protocol": {
                "name": "multi",
                "embedded": {"payload": self.request_package.generate_metadata()},
            },
        }
        return ocm_share_request

    def _generate_userid(self, sender: CustomEntityInfo) -> str:
        """Generate modified user ID for dispatcher domain.

        The sender user ID needs to be altered to match the dispatcher's
        public FQDN. E.g., rasmus.oscar.welander@egi.eu becomes
        rasmus.oscar.welander@<dispatcher public FQDN>.

        Args:
            sender: CustomEntityInfo for the sender.

        Returns:
            Modified user ID string.
        """
        sender_userid = sender.userid
        if sender_userid and "@" in sender_userid:
            sender_userid = sender_userid.split("@")[0] + "@" + settings.host
        return sender_userid or ""


vre_factory.register(SCIENCEMESH_PROGRAMMING_LANGUAGE, VREScienceMesh)
