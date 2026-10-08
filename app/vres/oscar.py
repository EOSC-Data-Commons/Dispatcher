import json
import logging
import os
import secrets
import tempfile
from oscar_python.client import Client
from urllib.parse import urljoin, urlparse

import requests
import yaml

from .base_vre import VRE, vre_factory
from app.exceptions import (
    VREConfigurationError,
    ExternalServiceError,
    ExternalDataSourceError,
)
from vre_rocrate import OSCAR_PROGRAMMING_LANGUAGE
from app.constants import OSCAR_DEFAULT_SERVICE

logger = logging.getLogger(__name__)


class VREOSCAR(VRE):
    def __init__(self, token=None, oscar_client_factory=None, **kwargs):
        super().__init__(token=token, **kwargs)
        self.fld_json = None
        self.service_type = None
        self._oscar_client_factory = (
            oscar_client_factory or self._default_oscar_client_factory
        )

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
        self.service_type = self._get_service_type(metadata)
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
    def _get_service_type(metadata):
        graph = metadata.get("@graph") if isinstance(metadata, dict) else None
        if not isinstance(graph, list):
            return None
        root = next(
            (
                entity
                for entity in graph
                if isinstance(entity, dict) and entity.get("@id") == "./"
            ),
            None,
        )
        service_type = root.get("serviceType") if root else None
        if isinstance(service_type, str):
            return service_type.strip().lower()
        return None

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

    def _write_input_file(self, directory, file_reference):
        source = file_reference.url or file_reference.id
        filename = os.path.basename(urlparse(source).path) or file_reference.name
        content = file_reference.properties.get("content")
        if content is None:
            content = self._fetch_file(source, as_binary=True)
        if isinstance(content, str):
            content = content.encode()
        local_path = os.path.join(directory, filename)
        with open(local_path, "wb") as stream:
            stream.write(content)
        return local_path

    def _fetch_file(self, url, as_json=False, as_binary=False):
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            if as_json:
                return response.json()
            if as_binary:
                return response.content
            return response.text
        except Exception as ex:
            raise ExternalDataSourceError("Network error while fetching files.") from ex

    @staticmethod
    def _default_oscar_client_factory(endpoint, token):
        return Client(
            options={
                "cluster_id": "dispatcher",
                "endpoint": endpoint,
                "oidc_token": token,
                "ssl": True,
            }
        )

    def post(self):
        fdl_json = self._get_fdl_from_crate()
        self.fld_json = fdl_json
        service_name = f'{fdl_json["name"]}-{secrets.token_hex(4)}'
        fdl_json["name"] = service_name

        logger.info(f"Creating OSCAR service {service_name}")
        logger.debug(f"FDL: {json.dumps(fdl_json)}")
        url = self.svc_url
        client = self._oscar_client_factory(url, self.token)
        try:
            client.create_service(fdl_json)
        except Exception as ex:
            raise ExternalServiceError(f"Error creating OSCAR service: {ex}") from ex

        if self.service_type == "synchronous":
            self._invoke_service(client, service_name, self.payload.oscar_input_files)
        else:
            self._upload_input_files(
                client, service_name, fdl_json, self.payload.oscar_input_files
            )

        return f"{url}/system/services/{service_name}"

    def _upload_input_files(self, client, service_name, service, files):
        inputs = service.get("input")
        if not isinstance(inputs, list) or not inputs:
            raise VREConfigurationError("OSCAR service does not define an input path")
        storage_input = next(
            (
                item
                for item in inputs
                if isinstance(item, dict)
                and item.get("storage_provider", item.get("provider"))
                in {"minio", "minio.default"}
            ),
            None,
        )
        input_path = storage_input.get("path") if storage_input else None
        if not isinstance(input_path, str) or not input_path.strip(" /"):
            raise VREConfigurationError(
                "OSCAR service does not define a MinIO input path"
            )
        provider = storage_input.get(
            "storage_provider", storage_input.get("provider", "minio")
        )
        if provider == "minio":
            provider = "minio.default"

        try:
            storage_client = client.create_storage_client(service_name)
            with tempfile.TemporaryDirectory(prefix="dispatcher-oscar-") as directory:
                for file_reference in files:
                    local_path = self._write_input_file(directory, file_reference)
                    storage_client.upload_file(provider, local_path, input_path)
        except Exception as ex:
            raise ExternalServiceError(
                f"Error uploading OSCAR input file: {ex}"
            ) from ex

    def _invoke_service(self, client, service_name, files):
        for file_reference in files:
            try:
                with tempfile.TemporaryDirectory(
                    prefix="dispatcher-oscar-"
                ) as directory:
                    local_path = self._write_input_file(directory, file_reference)
                    client.run_service(service_name, input=local_path, timeout=300)
            except Exception as ex:
                raise ExternalServiceError(
                    f"Error invoking OSCAR service: {ex}"
                ) from ex

    def delete(self):
        fdl_json = self._get_fdl_from_crate()
        service_name = fdl_json["name"]

        logger.info(f"Deleting OSCAR service {service_name}")
        client = self._oscar_client_factory(self.svc_url, self.token)
        try:
            client.remove_service(service_name)
        except Exception as ex:
            raise ExternalServiceError(f"Error deleting OSCAR service: {ex}") from ex


vre_factory.register(OSCAR_PROGRAMMING_LANGUAGE, VREOSCAR)
