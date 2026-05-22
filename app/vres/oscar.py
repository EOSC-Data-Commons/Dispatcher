from .base_vre import VRE, vre_factory
import base64
import requests
import logging
import json
from app.exceptions import (
    ExternalServiceError,
    WorkflowURLError,
)
from app.constants import OSCAR_DEFAULT_SERVICE, OSCAR_PROGRAMMING_LANGUAGE

logging.basicConfig(level=logging.INFO)


class VREOSCAR(VRE):
    def __init__(self, crate=None, body=None, token=None, **kwargs):
        super().__init__(crate, body=body, token=token, **kwargs)
        self.fld_json = None

    def get_default_service(self):
        return OSCAR_DEFAULT_SERVICE

    def _get_fdl_from_crate(self):
        if self.fld_json:
            return self.fld_json

        fdl_url = self.crate.mainEntity.get("url")
        if fdl_url is None:
            raise WorkflowURLError("Missing url in workflow entity")
        return self._fetch_json_file(fdl_url)

    def _fetch_json_file(self, url):
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as ex:
            raise WorkflowURLError("Network error while fetching FDL.") from ex

    def post(self):
        fdl_json = self._get_fdl_from_crate()
        self.fld_json = fdl_json
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

    def _get_input_files(self):
        # Get all files except the workflow and destination
        return [
            e for e in self.crate.root_dataset.get("hasPart", []) if e.type == "File"
        ]

    def _invoke_service(self, oscar_url, service_name, files):
        headers = {"Authorization": f"Bearer {self.token}"}
        url = f"{oscar_url}/job/{service_name}"
        for f in files:
            try:
                logging.info(
                    "Creating invocation for service %s and file %s",
                    service_name,
                    f.get("url"),
                )
                response = requests.get(f.get("url"), timeout=60)
                response.raise_for_status()
                file_content = response.text
            except Exception as e:
                logging.error(
                    "Error fetching file %s: %s, Ignoring...", f.get("url"), e
                )
                continue

            try:
                response = requests.post(
                    url,
                    headers=headers,
                    data=base64.b64encode(file_content.encode()),
                    timeout=60,
                )
                if response.status_code != 201:
                    logging.error(
                        "Error invoking OSCAR service for file %s: %s",
                        f.get("url"),
                        response.text,
                    )
            except Exception as e:
                logging.error(
                    "Error invoking OSCAR service for file %s: %s, Ignoring...",
                    f.get("url"),
                    e,
                )

    def delete(self):
        fdl_json = self._get_fdl_from_crate()
        service_name = fdl_json["name"]

        logging.info("Deleting OSCAR service %s", service_name)
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        url = self.svc_url
        try:
            response = requests.delete(
                f"{url}/system/services/{service_name}", headers=headers, timeout=60
            )
            if response.status_code != 204:
                raise ExternalServiceError(
                    f"Error deleting OSCAR service: {response.text}"
                )
        except Exception as e:
            logging.error("Error deleting OSCAR service %s: %s", service_name, e)


vre_factory.register(OSCAR_PROGRAMMING_LANGUAGE, VREOSCAR)
