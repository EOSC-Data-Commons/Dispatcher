from .base_vre import VRE, vre_factory
import requests
import logging
from app.constants import SCIENCEMESH_DEFAULT_SERVICE, SCIENCEMESH_PROGRAMMING_LANGUAGE
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
                f"{self.svc_url}/ocm/shares", headers=headers, json=data
            )
            logging.info(f"{self.__class__.__name__}: returned {response.text}")
            response.raise_for_status()
        except requests.RequestException as e:
            logging.error(f"{self.__class__.__name__}: API request failed: {e}")
            raise ScienceMeshAPIError("ScienceMesh API call failed") from e
        return response.json()

    def create_ocm_share_request(self):
        receiver = self.crate.get("#receiver")
        owner = self.crate.get("#owner")
        sender = self.crate.get("#sender")
        destination = self.crate.get("#destination")
        if destination is None:
            destination = {"url": self.svc_url}

        if not receiver or not owner or not sender or not destination:
            raise MissingOCMParameters(
                "Missing required entities (receiver, owner, sender, destination) for OCM share request"
            )

        # The sender user ID needs to be altered to match the dispatcher's public FQDN
        # e.g. rasmus.oscar.welander@egi.eu becomes rasmus.oscar.welander@<dispatcher public FQDN>
        sender_userid = sender.get("userid")
        if sender_userid and "@" in sender_userid:
            sender_userid = sender_userid.split("@")[0] + "@" + "dispatcher.egi.eu"

        # Create OCM share request JSON structure
        ocm_share_request = {
            "shareWith": receiver.get("userid"),
            "name": self.crate.mainEntity.get("name"),
            "description": self.crate.mainEntity.get("description"),
            "providerId": "n/a",
            "resourceId": "n/a",
            "owner": owner.get("userid"),
            "senderDisplayName": sender.get("name"),
            "sender": sender_userid,
            "resourceType": "ro-crate",
            "shareType": "user",
            "protocol": {"name": "multi", "embedded": {"payload": self.crate.metadata.generate()}},
        }
        return ocm_share_request

    def _generate_userid(self, sender):
        # The sender user ID needs to be altered to match the dispatcher's public FQDN
        # e.g. rasmus.oscar.welander@egi.eu becomes rasmus.oscar.welander@<dispatcher public FQDN>
        sender_userid = sender.get("userid")
        if sender_userid and "@" in sender_userid:
            sender_userid = sender_userid.split("@")[0] + "@" + settings.host
        return sender_userid


vre_factory.register(SCIENCEMESH_PROGRAMMING_LANGUAGE, VREScienceMesh)
