import base64
import json
import logging
import os
import secrets
import tempfile
from typing import Callable, Protocol, runtime_checkable
from urllib.parse import urljoin, urlparse

import boto3
import requests
import yaml
from botocore.exceptions import BotoCoreError, ClientError

from .base_vre import VRE, vre_factory
from app.exceptions import (
    VREConfigurationError,
    ExternalServiceError,
    ExternalDataSourceError,
)
from vre_rocrate import OSCAR_PROGRAMMING_LANGUAGE
from app.constants import OSCAR_DEFAULT_SERVICE, OSCAR_RUN_TIMEOUT

logger = logging.getLogger(__name__)

OSCAR_DEFAULT_TIMEOUT = 60
OSCAR_DEFAULT_MINIO_ENDPOINT = "http://minio-service.minio:9000"


@runtime_checkable
class OscarClientProtocol(Protocol):
    """Minimal contract of the OSCAR client used by VREOSCAR."""

    def create_service(self, service_definition: dict): ...

    def remove_service(self, name: str): ...

    def run_service(self, name: str, input_path=None, timeout=None): ...

    def upload_url(
        self, service_name: str, provider: str, url: str, remote_path: str
    ) -> bool: ...


class OscarClient:
    """Minimal OSCAR REST API client authenticated with an OIDC token."""

    def __init__(self, endpoint, token, verify=True, timeout=OSCAR_DEFAULT_TIMEOUT):
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.verify = verify
        self.timeout = timeout

    def _request(self, method, path, token=None, timeout=None, **kwargs):
        headers = {"Authorization": f"Bearer {token or self.token}"}
        headers.update(kwargs.pop("headers", {}))
        response = requests.request(
            method,
            f"{self.endpoint}{path}",
            headers=headers,
            verify=self.verify,
            timeout=timeout or self.timeout,
            **kwargs,
        )
        response.raise_for_status()
        return response

    def get_service(self, name):
        return self._request("GET", f"/system/services/{name}")

    def create_service(self, service_definition):
        exists = requests.get(
            f"{self.endpoint}/system/services/{service_definition['name']}",
            headers={"Authorization": f"Bearer {self.token}"},
            verify=self.verify,
            timeout=self.timeout,
        )
        if exists.status_code == 200:
            raise ValueError(
                f"A service with name '{service_definition['name']}' "
                "is already present on the cluster"
            )
        return self._request(
            "POST",
            "/system/services",
            data=json.dumps(service_definition),
            headers={"Content-Type": "application/json"},
        )

    def remove_service(self, name):
        return self._request("DELETE", f"/system/services/{name}")

    def run_service(self, name, input_path=None, timeout=None):
        """Synchronously invoke a service sending a file as base64 body."""
        data = None
        if input_path:
            with open(input_path, "rb") as stream:
                data = base64.b64encode(stream.read())
        return self._request(
            "POST",
            f"/run/{name}",
            timeout=timeout,
            data=data,
            headers={"Content-Type": "application/json"},
        )

    def _get_storage_credentials(self, service_name, provider):
        """Resolve credentials for a '<type>.<name>' storage provider."""
        provider_type, _, provider_name = provider.partition(".")
        if provider_type == "minio" and provider_name == "default":
            # Get default MinIO credentials the cluster config.
            return self._request("GET", "/system/config").json()["minio_provider"]
        service = self.get_service(service_name).json()
        credentials = (
            (service.get("storage_providers") or {})
            .get(provider_type, {})
            .get(provider_name)
        )
        if credentials is None:
            raise ValueError(
                f'Storage provider "{provider}" is not defined in service "{service_name}"'
            )
        return credentials

    def upload_url(self, service_name, provider, url, remote_path):
        """Stream the content of a URL to '<bucket>/<key>' in a service's S3/MinIO provider.

        Returns True on success and False otherwise.
        """
        provider_type = provider.split(".")[0]
        if provider_type not in ("minio", "s3"):
            raise ValueError(f'Unsupported storage provider type "{provider_type}"')
        creds = self._get_storage_credentials(service_name, provider)

        bucket, _, key = remote_path.lstrip("/").partition("/")
        if not bucket or not key:
            raise ValueError(f"Invalid remote path '{remote_path}'")

        endpoint = creds.get("endpoint") or (
            OSCAR_DEFAULT_MINIO_ENDPOINT if provider_type == "minio" else None
        )
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=creds.get("region") or None,
            verify=creds.get("verify", True),
            aws_access_key_id=creds.get("access_key"),
            aws_secret_access_key=creds.get("secret_key"),
        )
        logger.debug(f"Uploading from URL '{url}' to bucket '{bucket}' key '{key}'")
        try:
            with requests.get(url, stream=True, timeout=(5, 60)) as response:
                response.raise_for_status()
                response.raw.decode_content = True
                content_type = response.headers.get(
                    "content-type", "application/octet-stream"
                )
                s3.upload_fileobj(
                    response.raw, bucket, key, ExtraArgs={"ContentType": content_type}
                )
            return True
        except (requests.RequestException, BotoCoreError, ClientError) as ex:
            logger.error(f"Error uploading URL {url}: {ex}")
            return False


class VREOSCAR(VRE):
    def __init__(
        self,
        token=None,
        oscar_client_factory: Callable[[str, str], OscarClientProtocol] | None = None,
        **kwargs,
    ):
        super().__init__(token=token, **kwargs)
        self.fdl_json = None
        factory = oscar_client_factory or self._default_oscar_client_factory
        self.client = factory(self.svc_url, self.token)
        if not isinstance(self.client, OscarClientProtocol):
            raise VREConfigurationError(
                "Injected OSCAR client factory must return an object "
                "implementing OscarClientProtocol"
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
        return OscarClient(endpoint, token)

    def _service_is_async(self, fdl_json):
        return "input" in fdl_json

    def post(self):
        fdl_json = self._get_fdl_from_crate()
        self.fdl_json = fdl_json
        service_name = f'{fdl_json["name"]}-{secrets.token_hex(4)}'
        fdl_json["name"] = service_name

        self.update_task_status(f"Creating OSCAR service {service_name}")
        logger.debug(f"FDL: {json.dumps(fdl_json)}")
        try:
            self.client.create_service(fdl_json)
        except Exception as ex:
            raise ExternalServiceError(f"Error creating OSCAR service: {ex}") from ex

        self.update_task_status(f"Invoking OSCAR service {service_name}")
        if self._service_is_async(fdl_json):
            self._upload_input_files(service_name, fdl_json)
        else:
            self._invoke_service(service_name, self.payload.oscar_input_files)

        return self.svc_url

    def _upload_input_files(self, service_name, service):
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

        for file_reference in files:
            filename = (
                os.path.basename(urlparse(file_reference.url).path)
                or file_reference.name
            )
            logger.debug(f"Uploading OSCAR input file {filename}")
            self.client.upload_url(
                service_name,
                provider,
                file_reference.url,
                os.path.join(input_path, filename),
            )

    def _invoke_service(self, service_name, files):
        for file_reference in files:
            try:
                with tempfile.TemporaryDirectory(
                    prefix="dispatcher-oscar-"
                ) as directory:
                    local_path = self._write_input_file(directory, file_reference)
                    resp = self.client.run_service(
                        service_name,
                        input_path=local_path,
                        timeout=OSCAR_RUN_TIMEOUT,
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
        try:
            self.client.remove_service(service_name)
        except Exception as ex:
            raise ExternalServiceError(f"Error deleting OSCAR service: {ex}") from ex


vre_factory.register(OSCAR_PROGRAMMING_LANGUAGE, VREOSCAR)
