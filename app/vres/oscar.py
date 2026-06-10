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
from vre_rocrate import OSCAR_PROGRAMMING_LANGUAGE
from app.constants import OSCAR_DEFAULT_SERVICE

logging.basicConfig(level=logging.INFO)


class VREOSCAR(VRE):
    def __init__(self, token=None, **kwargs):
        super().__init__(token=token, **kwargs)
        self.fld_json = None

    def get_default_service(self):
        return OSCAR_DEFAULT_SERVICE

    def _get_fdl_from_crate(self):
        if self.fld_json:
            return self.fld_json

        fdl_url = self.request_package.workflow_url
        if not fdl_url:
            raise VREConfigurationError("Missing FDL URL in workflow entity")
        fdl_json = self._fetch_file(fdl_url, True)

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

        self._invoke_service(url, service_name, self.request_package.oscar_input_files)

        return service_url

    def _invoke_service(self, oscar_url, service_name, files):
        headers = {"Authorization": f"Bearer {self.token}"}
        url = f"{oscar_url}/job/{service_name}"
        for f in files:
            file_url = f.url or f.id
            try:
                logging.info(
                    "Creating invocation for service %s and file %s",
                    service_name,
                    file_url,
                )
                response = requests.get(file_url, timeout=60)
                response.raise_for_status()
                file_content = response.text
            except Exception as e:
                logging.error("Error fetching file %s: %s", file_url, e)
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
                    file_url,
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
