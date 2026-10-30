import asyncio
import json
import logging
import os
import secrets
import tempfile
from oscar_python.client import Client
from urllib.parse import urljoin, urlparse

import yaml

from .base_vre import VRE, vre_factory
from app import http as app_http
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
        self.fdl_json = None
        self._oscar_client_factory = (
            oscar_client_factory or self._default_oscar_client_factory
        )

    def get_default_service(self):
        return OSCAR_DEFAULT_SERVICE

    async def _get_fdl_from_crate(self):
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
            fdl = yaml.safe_load(await self._fetch_file(fdl_url))
        except yaml.YAMLError as ex:
            raise VREConfigurationError("Invalid FDL YAML in OSCAR Hub crate") from ex
        try:
            script = await self._fetch_file(script_url)
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

    async def _write_input_file(self, directory, file_reference):
        source = file_reference.url or file_reference.id
        filename = os.path.basename(urlparse(source).path) or file_reference.name
        content = file_reference.properties.get("content")
        if content is None:
            content = await self._fetch_file(source, as_binary=True)
        if isinstance(content, str):
            content = content.encode()
        local_path = os.path.join(directory, filename)
        with open(local_path, "wb") as stream:
            stream.write(content)
        return local_path

    async def _fetch_file(self, url, as_binary=False):
        try:
            response = await app_http.get(url, timeout=60)
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

    def _get_service_type(self, fdl_json):
        if "input" in fdl_json:
            return "asynchronous"
        return "synchronous"

    async def post(self):
        url = await self.setup_service()
        fdl_json = await self._get_fdl_from_crate()
        self.fdl_json = fdl_json
        service_name = f'{fdl_json["name"]}-{secrets.token_hex(4)}'
        fdl_json["name"] = service_name

        logger.info(f"Creating OSCAR service {service_name}")
        logger.debug(f"FDL: {json.dumps(fdl_json)}")
        client = self._oscar_client_factory(url, self.token)
        try:
            # oscar_python is a synchronous SDK — never block the event loop.
            await asyncio.to_thread(client.create_service, fdl_json)
        except Exception as ex:
            raise ExternalServiceError(f"Error creating OSCAR service: {ex}") from ex

        if self._get_service_type(fdl_json) == "synchronous":
            await self._invoke_service(client, service_name, self.payload.oscar_input_files)
        else:
            await self._upload_input_files(
                client, service_name, fdl_json, self.payload.oscar_input_files
            )

        # Remember what we delivered: delete() prefers the dispatch hint
        # (delivered_url kwarg) but falls back to this, so post-then-delete
        # on one instance needs no FDL re-download either.
        self.delivered_url = f"{url}/system/services/{service_name}"
        return self.delivered_url

    async def _upload_input_files(self, client, service_name, service, files):
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
            storage_client = await asyncio.to_thread(
                client.create_storage_client, service_name
            )
            for file_reference in files:
                filename = (
                    os.path.basename(urlparse(file_reference.url).path)
                    or file_reference.name
                )
                destination = os.path.join(input_path, filename)
                await asyncio.to_thread(
                    lambda: storage_client._get_client(provider).upload_url(
                        file_reference.url, destination
                    )
                )
        except Exception as ex:
            raise ExternalServiceError(
                f"Error uploading OSCAR input file: {ex}"
            ) from ex

    async def _invoke_service(self, client, service_name, files):
        for file_reference in files:
            try:
                with tempfile.TemporaryDirectory(
                    prefix="dispatcher-oscar-"
                ) as directory:
                    local_path = await self._write_input_file(directory, file_reference)
                    await asyncio.to_thread(
                        client.run_service,
                        service_name,
                        input=local_path,
                        timeout=300,
                    )
            except Exception as ex:
                raise ExternalServiceError(
                    f"Error invoking OSCAR service: {ex}"
                ) from ex

    async def delete(self):
        # Prefer the delivered URL (dispatch.delete_flow hint, or remembered
        # by post()): the service name is its basename, so teardown needs
        # no FDL re-download and no setup_service round-trip. The crate
        # fallback exists for direct same-instance use without either.
        delivered = getattr(self, "delivered_url", None)
        if delivered:
            service_name = delivered.rstrip("/").rsplit("/", 1)[-1]
            url = delivered.rsplit("/system/services/", 1)[0]
        else:
            fdl_json = await self._get_fdl_from_crate()
            service_name = fdl_json["name"]
            url = await self.setup_service()

        logger.info(f"Deleting OSCAR service {service_name}")
        client = self._oscar_client_factory(url, self.token)
        try:
            await asyncio.to_thread(client.remove_service, service_name)
        except Exception as ex:
            raise ExternalServiceError(f"Error deleting OSCAR service: {ex}") from ex


vre_factory.register(OSCAR_PROGRAMMING_LANGUAGE, VREOSCAR)
