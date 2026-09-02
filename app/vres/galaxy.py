from .base_vre import VRE, vre_factory
import requests
import logging
from urllib.parse import urlparse
from app import exceptions
from vre_rocrate import GALAXY_PROGRAMMING_LANGUAGE
from app.constants import (
    GALAXY_DEFAULT_SERVICE,
    GALAXY_PUBLIC_DEFAULT,
    GALAXY_WORKFLOW_TARGET_TYPE,
    WORKFLOWHUB_TRS_API,
)

logger = logging.getLogger(__name__)


class VREGalaxy(VRE):
    def get_default_service(self):
        return GALAXY_DEFAULT_SERVICE

    def post(self):
        data = self._prepare_workflow_data()
        response_data = self._send_workflow_request(data)
        landing_id = self._extract_landing_id(response_data)
        return self._build_final_url(landing_id)

    def _prepare_workflow_data(self):
        """Prepare the workflow data for the API request."""
        files = self._get_workflow_files()
        workflow_url = self._get_workflow_url()

        return {
            "public": GALAXY_PUBLIC_DEFAULT,
            "request_state": self._modify_for_api_data_input(files),
            "workflow_id": workflow_url,
            "workflow_target_type": GALAXY_WORKFLOW_TARGET_TYPE,
        }

    def _get_workflow_files(self):
        """Extract file references from the request package."""
        return self.request_package.input_files

    def _get_workflow_url(self):
        """Extract workflow URL from the request package, resolving bare
        WorkflowHub page URLs to versioned TRS URLs (fallback, #161)."""
        workflow_url = self.request_package.workflow_url
        if workflow_url is None:
            # checked here, as some other vres might be actual files
            logger.error(f"{self.__class__.__name__}: Missing url in workflow entity")
            raise exceptions.WorkflowURLError("Missing url in workflow entity")
        tool_id = self._workflowhub_tool_id(workflow_url)
        if tool_id is None:
            return workflow_url
        resolved = self._resolve_trs_url(tool_id)
        logger.info(f"{self.__class__.__name__}: resolved {workflow_url} -> {resolved}")
        return resolved

    @staticmethod
    def _workflowhub_tool_id(url):
        """Return the numeric id of a bare WorkflowHub workflow page URL
        ('/workflows/{id}'), else None.

        TRS URLs, raw-descriptor URLs (…/git/{v}/raw/…) and non-WorkflowHub
        hosts are already concrete and must pass through untouched.
        """
        parsed = urlparse(url)
        if parsed.netloc != "workflowhub.eu":
            return None
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "workflows":
            return parts[1]
        return None

    def _resolve_trs_url(self, tool_id):
        """Resolve a WorkflowHub tool id to a versioned TRS URL."""
        api_url = f"{WORKFLOWHUB_TRS_API}/tools/{tool_id}/versions"
        try:
            response = requests.get(api_url, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"{self.__class__.__name__}: WorkflowHub lookup failed: {e}")
            raise exceptions.ExternalDataSourceError(
                "WorkflowHub TRS lookup failed"
            ) from e
        version_id = self._pick_version_id(response.json(), tool_id)
        return f"{api_url}/{version_id}"

    def _pick_version_id(self, versions, tool_id):
        """Pick the TRS version id matching the workflow's pinned version,
        or the latest one when unpinned."""
        if not versions:
            raise exceptions.WorkflowConfigurationError(
                f"WorkflowHub tool {tool_id} has no versions"
            )
        wanted = self.request_package.workflow.tool_version
        if wanted is not None:
            for version in versions:
                if version.get("name") == wanted:
                    return version["id"]
            raise exceptions.WorkflowConfigurationError(
                f"WorkflowHub tool {tool_id} has no version named {wanted!r}"
            )
        # NOTE: no version pinned — launch the latest (max numeric id)
        logger.warning(
            f"{self.__class__.__name__}: no tool version pinned, "
            f"using the latest WorkflowHub version"
        )
        try:
            return max(versions, key=lambda v: int(v["id"]))["id"]
        except (KeyError, TypeError, ValueError):
            return versions[0]["id"]

    def _modify_for_api_data_input(self, files):
        """Convert file references to API-compatible format."""
        result = {}
        for f in files:
            file_meta = {
                "class": "File",
                "filetype": (
                    f.encoding_format.split("/")[-1] if f.encoding_format else "unknown"
                ),
            }

            if f.onedata_file_id:
                file_meta["location"] = (
                    f"https://{f.onedata_domain}/api/v3/onezone/shares/data/{f.onedata_file_id}/content"
                )
            else:
                file_meta["location"] = f.url or f.id

            result[f.name] = file_meta

        return result

    def _send_workflow_request(self, data):
        """Send the workflow request to the Galaxy API."""
        headers = self._get_headers()

        api_url = self._get_api_url()

        logger.info(f"{self.__class__.__name__}: calling {api_url} with {data}")

        try:
            response = requests.post(api_url, headers=headers, json=data)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"{self.__class__.__name__}: API request failed: {e}")
            raise exceptions.GalaxyAPIError("Galaxy API call failed") from e
        return response.json()

    def _get_api_url(self):
        url = self.svc_url.rstrip("/")
        api_url = f"{url}/api/workflow_landings"
        return api_url

    def _get_headers(self):
        return {"Content-Type": "application/json", "Accept": "application/json"}

    def _extract_landing_id(self, response_data):
        """Extract the landing ID from the API response."""
        uuid = response_data.get("uuid")
        if uuid is None:
            logger.error(
                f"{self.__class__.__name__}: Galaxy API response missing 'uuid' field"
            )
            raise exceptions.GalaxyAPIError("Galaxy API response missing 'uuid' field")
        return uuid

    def _build_final_url(self, landing_id):
        """Build the final workflow landing URL."""
        url = self.svc_url.rstrip("/")
        public = GALAXY_PUBLIC_DEFAULT
        return f"{url}/workflow_landings/{landing_id}?public={public}"


vre_factory.register(GALAXY_PROGRAMMING_LANGUAGE, VREGalaxy)
