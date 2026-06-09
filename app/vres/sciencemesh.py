from .base_vre import VRE, vre_factory
import requests
import logging
import uuid
from vre_rocrate import SCIENCEMESH_PROGRAMMING_LANGUAGE
from app.constants import SCIENCEMESH_DEFAULT_SERVICE
from app.config import settings
from app.exceptions import MissingOCMParameters, ScienceMeshAPIError

logger = logging.getLogger(__name__)


class VREScienceMesh(VRE):
    def get_default_service(self):
        return SCIENCEMESH_DEFAULT_SERVICE

    def post(self):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        data = self.create_ocm_share_request()

        try:
            logger.info(f"{self.__class__.__name__}: calling {self.svc_url}")
            response = requests.post(
                f"{self.svc_url}/ocm/shares",
                headers=headers,
                json=data,
            )
            logger.info(f"{self.__class__.__name__}: returned {response.text}")
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"{self.__class__.__name__}: API request failed: {e}")
            raise ScienceMeshAPIError("ScienceMesh API call failed") from e
        return response.json()

    def create_ocm_share_request(self):
        pkg = self.request_package
        ocm = pkg.ocm_data
        if ocm is None:
            raise MissingOCMParameters(
                "Missing OCM data (receiver, owner, sender) to dispatch via OCM to a ScienceMesh VRE"
            )
        receiver = ocm.receiver_userid
        owner = ocm.owner_userid
        sender_userid = ocm.sender_userid
        sender_name = ocm.sender_name
        if not receiver or not owner or not sender_userid:
            raise MissingOCMParameters(
                "Missing required parameters (receiver, owner, sender) to dispatch via OCM to a ScienceMesh VRE"
            )
        resid = ocm.resource_id
        if resid is None:
            # TODO the resource ID should be derived from the crate itself and be invariant to multiple shares
            resid = str(uuid.uuid4())

        ocm_share_request = {
            "shareWith": receiver,
            "name": ocm.root_name or "",
            "description": ocm.root_description or "",
            "providerId": str(uuid.uuid4()),  # must be unique for each share
            "resourceId": resid,
            "owner": owner,
            "senderDisplayName": sender_name,
            "sender": self._generate_ocm_address(sender_userid),
            "resourceType": "embedded",
            "shareType": "user",
            "protocol": {
                "name": "multi",
                "embedded": {"payload": pkg.raw_crate},
            },
        }
        return ocm_share_request

    def _generate_ocm_address(self, sender_userid: str | None):
        # Generate an OCM address out of the sender user ID, that is ensure the host matches the dispatcher's public FQDN
        # e.g. rasmus.oscar.welander@egi.eu becomes rasmus.oscar.welander@egi.eu@<dispatcher's public FQDN>
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
