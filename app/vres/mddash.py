from .base_vre import VRE, vre_factory
import requests
import logging
import time
from app import exceptions
from vre_rocrate import MDDASH_PROGRAMMING_LANGUAGE
from app.constants import (
    MDDASH_DEFAULT_SERVICE,
    MDDASH_DEFAULT_PROTOCOL,
)

logger = logging.getLogger(__name__)


class VREMDDash(VRE):
    def get_default_service(self):
        return MDDASH_DEFAULT_SERVICE

    def post(self):
        self.update_task_status("logging in to MDDash")
        self._login()

        self.update_task_status("starting MDDash server")
        self._start_server()

        self.update_task_status("waiting for MDDash server")
        self._wait_for_server()

        self.update_task_status("authenticating with MDDash")
        self._auth_mddash()

        self.update_task_status("creating MDDash experiment")
        self._create_experiment()

        return f"{self.svc_url}{self.singleuser}dash/"

    def _login(self):
        url = self.svc_url
        bearer = {"Authorization": f"token {self.token}"}
        self.session = requests.Session()

        logger.info(bearer)
        try:
            r = self.session.get(url + "/hub/jwt_login", headers=bearer)
            r.raise_for_status()
            logger.info(f"GET {url}/hub/jwt_login {r.text}")

            r = self.session.get(url + "/hub/home", headers=bearer)
            r.raise_for_status()
            logger.info(f"GET {url}/hub/home {r.text}")
            self.xsrf_token = self.session.cookies.get("_xsrf")

            r = self.session.get(url + "/hub/api/user", headers=bearer)
            r.raise_for_status()
            logger.info(f"GET {url}/hub/api/user: {r.json()}")

            self.user = r.json()["name"]
        except requests.RequestException as e:
            logger.error(f"MDDash login failed: {e}")
            raise exceptions.ExternalServiceError(f"MDDash login failed: {e}") from e

    def _start_server(self):
        url = self.svc_url

        try:
            r = self.session.post(
                f"{url}/hub/api/users/{self.user}/servers/",
                headers={
                    "X-XSRFToken": self.xsrf_token,
                    "Content-Type": "application/json",
                    "Referer": f"{url}/hub/home",
                },
                json={"_xsrf": self.xsrf_token},
            )
            if r.status_code != 400:  # OK, server already exists
                r.raise_for_status()
            logger.info(f"{url}/hub/api/users/{self.user}/servers: {r.text}")
        except requests.RequestException as e:
            logger.error(f"Failed to start MDDash server: {e}")
            raise exceptions.ExternalServiceError(
                f"Failed to start MDDash server: {e}"
            ) from e

    def _wait_for_server(self):
        url = self.svc_url

        max_retries = 60
        retry_interval = 5
        server_ready = False

        user_api_url = url + "/hub/api/user"

        for i in range(max_retries):
            logger.info(f"--- Poll attempt {i+1}/{max_retries}")

            try:
                resp = self.session.get(user_api_url)
                resp.raise_for_status()
            except requests.RequestException as e:
                logger.error(f"MDDash server poll failed: {e}")
                raise exceptions.ExternalServiceError(
                    f"MDDash server poll failed: {e}"
                ) from e

            if resp.status_code == 200:
                user_info = resp.json()
                servers = user_info.get("servers", {})
                default_server = servers.get("", {})

                is_ready = default_server.get("ready", False)
                is_stopped = default_server.get("stopped", True)

                if is_ready and not is_stopped:
                    server_ready = True
                    break

            time.sleep(retry_interval)

        if not server_ready:
            raise exceptions.ExternalServiceError(
                f"{self.user} did not start within {max_retries * retry_interval}s"
            )

        self.singleuser = default_server.get("url", "")

    def _auth_mddash(self):
        url = self.svc_url

        try:
            resp = self.session.get(
                f"{url}{self.singleuser}dash/", allow_redirects=True
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"MDDash auth failed: {e}")
            raise exceptions.ExternalServiceError(f"MDDash auth failed: {e}") from e

        if "mddash-auth" not in self.session.cookies:
            raise exceptions.VREAuthenticationError("mddash-auth cookie not set")

    def _create_experiment(self):
        url = self.svc_url

        pdb_files = self.request_package.input_files
        if not pdb_files:
            raise exceptions.VREConfigurationError(
                "No PDB file found in request package"
            )
        pdb = pdb_files[0].name

        notebooks_repo = self.request_package.workflow.url or MDDASH_DEFAULT_PROTOCOL

        try:
            resp = self.session.post(
                f"{url}{self.singleuser}dash/api/experiments",
                data={
                    "experiment-name": f"{self._request_id}: {pdb}",
                    "type": "pdb",
                    "pdb-id": pdb,
                    "notebooks-repo": notebooks_repo,
                },
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to create MDDash experiment: {e}")
            raise exceptions.ExternalServiceError(
                f"Failed to create MDDash experiment: {e}"
            ) from e


vre_factory.register(MDDASH_PROGRAMMING_LANGUAGE, VREMDDash)
