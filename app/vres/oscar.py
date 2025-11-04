from .base_vre import VRE, vre_factory
import base64
import requests
import logging
import json
from app.exceptions import (
    VREConfigurationError,
    ExternalServiceError,
    ExternalDataSourceError,
)
from app.constants import OSCAR_DEFAULT_SERVICE, OSCAR_PROGRAMMING_LANGUAGE

logging.basicConfig(level=logging.INFO)


class VREOSCAR(VRE):
    def __init__(self, crate=None, body=None, token=None):
        super().__init__(crate, body, token)
        self.fld_json = None

    def get_default_service(self):
        return OSCAR_DEFAULT_SERVICE

    def _get_fdl_from_crate(self):
        if self.fld_json:
            return self.fld_json

        workflow_parts = self.crate.mainEntity.get("hasPart", [])
        if not workflow_parts:
            raise VREConfigurationError("Missing hasPart in workflow entity")

        fdl_json = None
        script = None

        for elem in workflow_parts:
            if not elem.get("@type") == "File":
                raise VREConfigurationError("Invalid hasPart type in workflow entity")

            ref_elem = self.crate.dereference(elem.get("@id"))
            if not ref_elem:
                logging.error("Could not dereference entity %s", elem.get("@id"))
                continue

            file_url = ref_elem.get("url")
            if not file_url:
                logging.error("File entity %s has no URL", elem.get("@id"))
                continue

            encoding = elem.get("encodingFormat")

            if encoding == "application/json":
                fdl_json = self._fetch_file(file_url, True)
            elif encoding == "text/x-shellscript":
                script = self._fetch_file(file_url)

        if not fdl_json:
            raise VREConfigurationError("Missing FDL in workflow entity")

        if script:
            fdl_json["script"] = script

        return fdl_json

    def _fetch_file(self, url, as_json=False):
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            if as_json:
                return response.json()
            return response.text
        except Exception as ex:
            raise ExternalDataSourceError("Network error while fetching files.") from ex

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
        non_input_files = []
        non_input_files.append(self.crate.root_dataset.get("runsOn").get("@id"))
        non_input_files.append(self.crate.mainEntity.get("@id"))
        for elem in self.crate.mainEntity.get("hasPart", []):
            if elem.get("@type") == "File":
                non_input_files.append(elem.get("@id"))
        return [
            e
            for e in self.crate.get_entities()
            if e.type == "File" and e.get("@id") not in non_input_files
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
                logging.error("Error fetching file %s: %s", f.get("url"), e)
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
                    f.get("url"),
                    response.text,
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
        response = requests.delete(
            f"{url}/system/services/{service_name}", headers=headers, timeout=60
        )
        if response.status_code != 204:
            raise ExternalServiceError(f"Error deleting OSCAR service: {response.text}")


vre_factory.register(OSCAR_PROGRAMMING_LANGUAGE, VREOSCAR)
