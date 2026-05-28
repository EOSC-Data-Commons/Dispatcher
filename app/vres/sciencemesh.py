from .base_vre import VRE, vre_factory
import requests
import logging
import uuid
from vre_rocrate import SCIENCEMESH_PROGRAMMING_LANGUAGE
from app.constants import SCIENCEMESH_DEFAULT_SERVICE
from app.config import settings
from app.exceptions import MissingOCMParameters, ScienceMeshAPIError

logging.basicConfig(level=logging.INFO)


class VREScienceMesh(VRE):
    def get_default_service(self):
        return SCIENCEMESH_DEFAULT_SERVICE

    def post(self):
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

    def create_ocm_share_request(self):
        receiver = self.request_package.get_entity("#receiver")
        owner = self.request_package.get_entity("#owner")
        sender = self.request_package.get_entity("#sender")
        if not receiver or not owner or not sender:
            raise MissingOCMParameters(
                "Missing required parameters (receiver, owner, sender) to dispatch via OCM to a ScienceMesh VRE"
            )
        resid = self.request_package.get_entity("#identifier")
        if resid is None:
            # TODO the resource ID should be derived from the crate itself and be invariant to multiple shares
            resid = str(uuid.uuid4())

        root = self.request_package.get_entity("./")
        # Create OCM share request JSON structure
        ocm_share_request = {
            "shareWith": receiver.get("userid"),
            "name": root.get("name", "") if root else "",
            "description": root.get("description", "") if root else "",
            "providerId": str(uuid.uuid4()),  # must be unique for each share
            "resourceId": resid,
            "owner": owner.get("userid"),
            "senderDisplayName": sender.get("name"),
            "sender": self._generate_ocm_address(sender),
            "resourceType": "embedded",
            "shareType": "user",
            "protocol": {
                "name": "multi",
                "embedded": {"payload": self.request_package.raw_crate},
            },
        }
        return ocm_share_request

    def _generate_ocm_address(self, sender):
        # Generate an OCM address out of the sender user ID, that is ensure the host matches the dispatcher's public FQDN
        # e.g. rasmus.oscar.welander@egi.eu becomes rasmus.oscar.welander@egi.eu@<dispatcher's public FQDN>
        sender_userid = sender.get("userid")
        if not sender_userid:
            sender_userid = "eosc-dc-user"
        ocm_sending_server = settings.host
        if ocm_sending_server is None or ocm_sending_server == "":
            # this is only valid for unit testing
            logging.warning(
                "No host configured for OCM sending server, using 'localhost' for testing purposes"
            )
            ocm_sending_server = "localhost"
        return sender_userid + "@" + ocm_sending_server


vre_factory.register(SCIENCEMESH_PROGRAMMING_LANGUAGE, VREScienceMesh)
