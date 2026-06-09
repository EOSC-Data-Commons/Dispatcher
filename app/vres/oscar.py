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

logger = logging.getLogger(__name__)


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

        script = None
        for sf in self.request_package.script_files:
            file_url = sf.url or sf.id
            if file_url:
                script = self._fetch_file(file_url)
                break

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

        logger.info(f"Creating OSCAR service {service_name}")
        logger.debug(f"FDL: {json.dumps(fdl_json)}")
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
        return self.request_package.oscar_input_files

    def _invoke_service(self, oscar_url, service_name, files):
        headers = {"Authorization": f"Bearer {self.token}"}
        url = f"{oscar_url}/job/{service_name}"
        for f in files:
            file_url = f.url or f.id
            try:
                logger.info(
                    f"Creating invocation for service {service_name} and file {f.get('url')}"
                )
                response = requests.get(file_url, timeout=60)
                response.raise_for_status()
                file_content = response.text
            except Exception as e:
                logger.error(f"Error fetching file {f.get('url')}: {e}")
                continue
            response = requests.post(
                url,
                headers=headers,
                data=base64.b64encode(file_content.encode()),
                timeout=60,
            )
            if response.status_code != 201:
                logger.error(
                    f"Error invoking OSCAR service for file {f.get('url')}: {response.text}"
                )

    def delete(self):
        fdl_json = self._get_fdl_from_crate()
        service_name = fdl_json["name"]

        logger.info(f"Deleting OSCAR service {service_name}")
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
