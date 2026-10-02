from .base_vre import VRE, vre_factory
import base64
import requests
import logging
import json
from urllib.parse import urljoin, urlparse

import yaml
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

        crate_url = self.payload.workflow_url
        if not crate_url:
            raise VREConfigurationError(
                "Missing OSCAR Hub directory URL in workflow entity"
            )

        crate_base_url = self._crate_base_url(crate_url)
        metadata = self._fetch_file(
            urljoin(crate_base_url, "ro-crate-metadata.json"), True
        )
        fdl_reference = self._find_fdl_reference(metadata)
        fdl_url = self._resolve_crate_reference(crate_base_url, fdl_reference)

        try:
            fdl = yaml.safe_load(self._fetch_file(fdl_url))
        except yaml.YAMLError as ex:
            raise VREConfigurationError("Invalid FDL YAML in OSCAR Hub crate") from ex

        fdl_json = self._extract_oscar_service(fdl)
        script_reference = fdl_json.get("script")
        if not isinstance(script_reference, str) or not script_reference.strip():
            raise VREConfigurationError("Missing script reference in OSCAR FDL")
        fdl_json["script"] = self._fetch_file(
            self._resolve_crate_reference(crate_base_url, script_reference)
        )

        return fdl_json

    @staticmethod
    def _crate_base_url(crate_url):
        """Return a fetchable base URL for an OSCAR Hub service directory."""
        parsed = urlparse(crate_url)
        path_parts = parsed.path.strip("/").split("/")
        if parsed.netloc.lower() == "github.com" and len(path_parts) >= 5:
            owner, repository, view, ref, *directory = path_parts
            if view == "tree" and directory:
                raw_path = "/".join([owner, repository, ref, *directory])
                return f"https://raw.githubusercontent.com/{raw_path}/"

        return crate_url.rstrip("/") + "/"

    @staticmethod
    def _find_fdl_reference(metadata):
        graph = metadata.get("@graph") if isinstance(metadata, dict) else None
        if not isinstance(graph, list):
            raise VREConfigurationError("Invalid OSCAR Hub RO-Crate metadata")

        entities = {
            entity.get("@id"): entity
            for entity in graph
            if isinstance(entity, dict) and isinstance(entity.get("@id"), str)
        }
        root = entities.get("./")
        parts = root.get("hasPart", []) if isinstance(root, dict) else []
        if isinstance(parts, dict):
            parts = [parts]

        for part in parts:
            part_id = part.get("@id") if isinstance(part, dict) else None
            entity = entities.get(part_id, {})
            encoding = str(entity.get("encodingFormat", "")).lower()
            if part_id and (
                encoding in {"text/yaml", "application/yaml", "application/x-yaml"}
                or part_id.lower().endswith((".yml", ".yaml"))
            ):
                return entity.get("url") or part_id

        raise VREConfigurationError("Missing FDL YAML in OSCAR Hub RO-Crate")

    @staticmethod
    def _extract_oscar_service(fdl):
        try:
            definitions = fdl["functions"]["oscar"]
        except (KeyError, TypeError) as ex:
            raise VREConfigurationError(
                "FDL does not contain OSCAR service definitions"
            ) from ex

        if not isinstance(definitions, list):
            raise VREConfigurationError("Invalid OSCAR service definitions in FDL")
        services = [
            service
            for definition in definitions
            if isinstance(definition, dict)
            for service in definition.values()
            if isinstance(service, dict)
        ]
        if len(services) != 1:
            raise VREConfigurationError(
                "FDL must contain exactly one OSCAR service definition"
            )

        service = dict(services[0])
        if not service.get("name"):
            raise VREConfigurationError("Missing service name in OSCAR FDL")
        return service

    @staticmethod
    def _resolve_crate_reference(crate_base_url, reference):
        if not isinstance(reference, str) or not reference.strip():
            raise VREConfigurationError("Invalid file reference in OSCAR Hub crate")
        return urljoin(crate_base_url, reference)

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

        self._invoke_service(url, service_name, self.payload.oscar_input_files)

        return service_url

    def _invoke_service(self, oscar_url, service_name, files):
        headers = {"Authorization": f"Bearer {self.token}"}
        url = f"{oscar_url}/job/{service_name}"
        for f in files:
            file_url = f.url or f.id
            try:
                logger.info(
                    f"Creating invocation for service {service_name} and file {file_url}"
                )
                response = requests.get(file_url, timeout=60)
                response.raise_for_status()
                file_content = response.text
            except Exception as e:
                logger.error(f"Error fetching file {file_url}: {e}")
                continue
            response = requests.post(
                url,
                headers=headers,
                data=base64.b64encode(file_content.encode()),
                timeout=60,
            )
            if response.status_code != 201:
                logger.error(
                    f"Error invoking OSCAR service for file {file_url}: {response.text}"
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
