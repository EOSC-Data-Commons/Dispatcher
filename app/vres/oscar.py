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
from app.constants import OSCAR_DEFAULT_SERVICE, OSCAR_RUN_TIMEOUT

logger = logging.getLogger(__name__)


class VREOSCAR(VRE):
    def __init__(self, token=None, oscar_client_factory=None, **kwargs):
        super().__init__(token=token, **kwargs)
        self.fdl_json = None
        self._oscar_client_factory = (
            oscar_client_factory or self._default_oscar_client_factory
        )

    def get_default_service(self):
        return OSCAR_DEFAULT_SERVICE

    def _get_fdl_from_crate(self):
        if self.fdl_json:
            return self.fdl_json

        crate_url = self.payload.workflow_url
        if not crate_url:
            raise VREConfigurationError(
                "Missing OSCAR Hub directory URL in workflow entity"
            )

        crate_base_url = self._crate_base_url(crate_url)
        fdl_url = urljoin(crate_base_url, "fdl.yml")
        script_url = urljoin(crate_base_url, "script.sh")

        try:
            fdl = yaml.safe_load(self._fetch_file(fdl_url))
        except yaml.YAMLError as ex:
            raise VREConfigurationError("Invalid FDL YAML in OSCAR Hub crate") from ex
        try:
            script = self._fetch_file(script_url)
        except Exception as ex:
            raise VREConfigurationError("Failed to fetch OSCAR script") from ex

        fdl_json = self._extract_oscar_service(fdl)
        fdl_json["script"] = script

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

    def _fetch_file(self, url, as_binary=False):
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
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

    def _service_is_async(self, fdl_json):
        return "input" in fdl_json

    def post(self):
        fdl_json = self._get_fdl_from_crate()
        self.fdl_json = fdl_json
        service_name = f'{fdl_json["name"]}-{secrets.token_hex(4)}'
        fdl_json["name"] = service_name

        self.update_task_status(f"Creating OSCAR service {service_name}")
        logger.debug(f"FDL: {json.dumps(fdl_json)}")
        client = self._oscar_client_factory(self.svc_url, self.token)
        try:
            client.create_service(fdl_json)
        except Exception as ex:
            raise ExternalServiceError(f"Error creating OSCAR service: {ex}") from ex

        self.update_task_status(f"Invoking OSCAR service {service_name}")
        if self._service_is_async(fdl_json):
            self._upload_input_files(client, service_name, fdl_json)
        else:
            self._invoke_service(client, service_name, self.payload.oscar_input_files)

        return self.svc_url

    def _upload_input_files(self, client, service_name, service):
        files = self.payload.oscar_input_files
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

        storage_client = client.create_storage_client(service_name)
        for file_reference in files:
            filename = (
                os.path.basename(urlparse(file_reference.url).path)
                or file_reference.name
            )
            logger.debug(f"Uploading OSCAR input file {filename}")
            success = storage_client._get_client(provider).upload_url(
                file_reference.url, os.path.join(input_path, filename)
            )
            if not success:
                logger.error(f"Error uploading OSCAR input file {filename}")

    def _invoke_service(self, client, service_name, files):
        for file_reference in files:
            try:
                with tempfile.TemporaryDirectory(
                    prefix="dispatcher-oscar-"
                ) as directory:
                    local_path = self._write_input_file(directory, file_reference)
                    resp = client.run_service(
                        service_name, input=local_path, timeout=OSCAR_RUN_TIMEOUT
                    )
                    resp.raise_for_status()
                    logger.debug(f"OSCAR service {service_name} invoked successfully")
            except Exception as ex:
                logger.error(f"Error invoking OSCAR service: {ex}")

    def delete(self):
        fdl_json = self._get_fdl_from_crate()
        service_name = fdl_json["name"]
        # TOOD: this is not the name used in the service creation, which includes a random suffix.
        # We need to store the actual service name somewhere to be able to delete it.

        logger.info(f"Deleting OSCAR service {service_name}")
        client = self._oscar_client_factory(self.svc_url, self.token)
        try:
            client.remove_service(service_name)
        except Exception as ex:
            raise ExternalServiceError(f"Error deleting OSCAR service: {ex}") from ex


vre_factory.register(OSCAR_PROGRAMMING_LANGUAGE, VREOSCAR)
