from .base_vre import VRE, vre_factory
import logging
import time
from typing import Any, Callable
from urllib.parse import unquote

import requests

from app import exceptions
from app.config import settings
from app.constants import (
    RRP_CREATE_PROJECT_PATH,
    RRP_DEFAULT_BRANCH,
    RRP_DEFAULT_RESOURCES,
    RRP_DEFAULT_SERVICE,
    RRP_DOI_URL_PREFIX,
    RRP_ROOT_PATH_PREFIX,
)
from vre_rocrate import RRP_PROGRAMMING_LANGUAGE

logger = logging.getLogger(__name__)

RRP_PROJECT_DESCRIPTION = "Created via EOSC Dispatcher"
RRP_INPUT_PARAM_PREFIX = "#input-"
RRP_DATA_AVAILABLE = "Available"
RRP_CREATION_READY = "Ready"
RRP_EXECUTION_SUCCESS = "Success"


class VRERRP(VRE):
    """Launch a project on the Reproducible Research Platform (RRP).

    Mirrors the RRP flow of the reference implementation in req-packager's
    mocked dispatcher: create a project (docker image + zenodo data mounts),
    wait until it is ready, clone the tool repository, check out the default
    branch, stage the data and finally return the project's URL.
    """

    def get_default_service(self) -> str:
        return RRP_DEFAULT_SERVICE

    def post(self) -> str:
        image = self._get_docker_image()
        repository_url = self._get_repository_url()
        data_mounts = self._build_data_mounts()

        project_url, location = self._create_project(image, data_mounts)

        self.update_task_status("Waiting for RRP project creation")
        self._poll_until(
            project_url,
            lambda project: project.get("creationStatus") == RRP_CREATION_READY,
            "project creation",
        )

        self.update_task_status("Cloning tool repository")
        execution_url = self._clone_repository(project_url, repository_url)
        self._poll_until(
            execution_url,
            lambda execution: execution.get("status") == RRP_EXECUTION_SUCCESS,
            "repository clone",
        )

        self.update_task_status("Checking out branch")
        self._checkout_branch(project_url)

        self.update_task_status("Staging data")
        self._retrieve_data(project_url)
        self._poll_until(
            project_url,
            lambda project: self._is_all_data_available(project, data_mounts),
            "data staging",
        )

        return f"{self.svc_url}/projects/{self._project_code(location)}"

    # ------------------------------------------------------------------
    # Project creation
    # ------------------------------------------------------------------

    def _create_project(self, image: str, data_mounts: list[dict]) -> tuple[str, str]:
        """Create an RRP project; return its API URL and Location header."""
        payload = {
            "image": image,
            "name": f"eosc-{self._request_id}",
            "description": RRP_PROJECT_DESCRIPTION,
            "resources": RRP_DEFAULT_RESOURCES,
            "dataMounts": data_mounts,
        }
        response = self._request(
            "POST",
            f"{self.svc_url}{RRP_CREATE_PROJECT_PATH}",
            json=payload,
        )
        try:
            body = response.json()
        except ValueError as e:
            raise exceptions.InvalidResponseError(
                "RRP project creation returned a non-JSON body"
            ) from e
        project_url = body.get("id")
        if not project_url:
            raise exceptions.InvalidResponseError(
                "RRP project creation response misses the project 'id'"
            )
        return project_url, response.headers.get("Location", "")

    def _clone_repository(self, project_url: str, repository_url: str) -> str:
        response = self._request(
            "POST", f"{project_url}/clone", json={"repositoryUrl": repository_url}
        )
        try:
            body = response.json()
        except ValueError as e:
            raise exceptions.InvalidResponseError(
                "RRP clone returned a non-JSON body"
            ) from e
        execution_url = body.get("execution")
        if not execution_url:
            raise exceptions.InvalidResponseError(
                "RRP clone response misses the 'execution' URL"
            )
        return execution_url

    def _checkout_branch(self, project_url: str) -> None:
        self._request(
            "POST", f"{project_url}/checkout", json={"ref": RRP_DEFAULT_BRANCH}
        )

    def _retrieve_data(self, project_url: str) -> None:
        self._request("POST", f"{project_url}/data")

    # ------------------------------------------------------------------
    # Payload assembly
    # ------------------------------------------------------------------

    def _get_docker_image(self) -> str:
        """Docker image of the tool, carried on the crate's workflow entity."""
        image = self.payload.workflow.docker_image
        if not isinstance(image, str) or not image:
            raise exceptions.MissingRRPParameters(
                "Missing 'dockerImage' on the workflow to dispatch to RRP"
            )
        return image

    def _get_repository_url(self) -> str:
        """Tool repository URL: the crate's workflow URL."""
        url = self.payload.workflow_url
        if not url:
            raise exceptions.MissingRRPParameters(
                "Missing tool repository URL (workflow URL) to dispatch to RRP"
            )
        return url

    def _build_data_mounts(self) -> list[dict]:
        """Build dataMounts from the crate's file-bound input slots.

        mountPath is the tool-declared slot id (FormalParameter id minus
        the ``#input-`` prefix), path is the file's dataset-relative path
        (see ``_file_dataset_path``).
        """
        doi = self._get_dataset_doi()
        mounts = []
        for param in self.payload.workflow_inputs:
            file_ref = self.payload.file_for_input(param)
            if file_ref is None:
                continue
            mounts.append(
                {
                    "mountPath": param.id.removeprefix(RRP_INPUT_PARAM_PREFIX),
                    "source": {"type": "zenodo", "doi": doi},
                    "path": self._file_dataset_path(file_ref),
                }
            )
        return mounts

    def _get_dataset_doi(self) -> str:
        dataset = self.payload.input_dataset
        if dataset is None:
            raise exceptions.MissingRRPParameters(
                "Missing dataset in the crate to dispatch to RRP"
            )
        url = dataset.url
        if not url.startswith(RRP_DOI_URL_PREFIX):
            raise exceptions.MissingRRPParameters(
                f"RRP dispatch requires a doi.org dataset URL, got: {url!r}"
            )
        doi = url.removeprefix(RRP_DOI_URL_PREFIX)
        if not doi:
            raise exceptions.MissingRRPParameters(
                "Empty DOI in the crate's dataset URL"
            )
        return doi

    def _file_dataset_path(self, file_ref) -> str:
        """Dataset-relative path of a file: the URL-decoded segment after the
        first '/files/' in its URL (zenodo layout), falling back to its name."""
        url = file_ref.url or ""
        marker = "/files/"
        idx = url.find(marker)
        if idx != -1:
            path = url[idx + len(marker) :].split("?", 1)[0].split("#", 1)[0]
            return unquote(path).removeprefix(RRP_ROOT_PATH_PREFIX)
        return (file_ref.name or file_ref.id).removeprefix(RRP_ROOT_PATH_PREFIX)

    @staticmethod
    def _is_all_data_available(project: dict, data_mounts: list[dict]) -> bool:
        data_status = project.get("dataStatus", {})
        return all(
            data_status.get(mount.get("mountPath", ""), {}).get("status", "")
            == RRP_DATA_AVAILABLE
            for mount in data_mounts
        )

    @staticmethod
    def _project_code(location: str) -> str:
        if not location:
            raise exceptions.InvalidResponseError(
                "RRP project creation response misses the 'Location' header"
            )
        return location.rstrip("/").rsplit("/", maxsplit=1)[-1]

    # ------------------------------------------------------------------
    # Transport helpers
    # ------------------------------------------------------------------

    def _request(self, method: str, url: str, json: dict | None = None) -> Any:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        try:
            response = requests.request(
                method, url, headers=headers, json=json, timeout=60
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"{self.__class__.__name__}: RRP API request failed: {e}")
            raise exceptions.RRPAPIError("RRP API call failed") from e
        return response

    def _poll_until(
        self, url: str, is_done: Callable[[dict], bool], stage: str
    ) -> dict:
        max_attempts = settings.rrp_poll_max_attempts
        for attempt in range(1, max_attempts + 1):
            try:
                project = self._request("GET", url).json()
            except ValueError as e:
                raise exceptions.InvalidResponseError(
                    f"RRP {stage} poll returned a non-JSON body"
                ) from e
            if is_done(project):
                return project
            logger.info(
                f"{self.__class__.__name__}: waiting for {stage} "
                f"(attempt {attempt}/{max_attempts})"
            )
            time.sleep(settings.rrp_poll_interval_seconds)
        raise exceptions.RRPAPIError(
            f"RRP {stage} did not complete after {max_attempts} attempts"
        )


vre_factory.register(RRP_PROGRAMMING_LANGUAGE, VRERRP)
