from .base_vre import VRE, vre_factory
from dataclasses import dataclass
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


@dataclass
class MDDashContext:
    """Transient per-invocation state that flows explicitly through the MDDash
    request pipeline.  No mutable state leaks onto the VRE instance itself."""

    session: requests.Session
    user: str
    xsrf_token: str
    singleuser: str = ""


class VREMDDash(VRE):
    def get_default_service(self):
        return MDDASH_DEFAULT_SERVICE

    def post(self):
        self.update_task_status("logging in to MDDash")
        ctx = self._login()

        self.update_task_status("starting MDDash server")
        self._start_server(ctx)

        self.update_task_status("waiting for MDDash server")
        ctx = self._wait_for_server(ctx)

        self.update_task_status("authenticating with MDDash")
        self._auth_mddash(ctx)

        self.update_task_status("creating MDDash experiment")
        self._create_experiment(ctx)

        return f"{self.svc_url}{ctx.singleuser}dash/"

    def _login(self) -> MDDashContext:
        url = self.svc_url
        bearer = {"Authorization": f"token {self.token}"}
        session = requests.Session()

        logger.info(bearer)
        try:
            r = session.get(url + "/hub/jwt_login", headers=bearer)
            logger.info(f"Call GET {url}/hub/jwt_login")
            r.raise_for_status()

            r = session.get(url + "/hub/home", headers=bearer)
            logger.info(f"Call GET {url}/hub/home")
            r.raise_for_status()
            xsrf_token = session.cookies.get("_xsrf")

            r = session.get(url + "/hub/api/user", headers=bearer)
            logger.info(f"Call GET {url}/hub/api/user: {r.json()}")
            r.raise_for_status()

            user = r.json()["name"]
        except requests.RequestException as e:
            logger.error(f"MDDash login failed: {e}")
            raise exceptions.ExternalServiceError(f"MDDash login failed: {e}") from e

        return MDDashContext(session=session, user=user, xsrf_token=xsrf_token)

    def _start_server(self, ctx: MDDashContext) -> None:
        url = self.svc_url

        try:
            r = ctx.session.post(
                f"{url}/hub/api/users/{ctx.user}/servers/",
                headers={
                    "X-XSRFToken": ctx.xsrf_token,
                    "Content-Type": "application/json",
                    "Referer": f"{url}/hub/home",
                },
                json={"_xsrf": ctx.xsrf_token},
            )
            if r.status_code != 400:  # OK, server already exists
                r.raise_for_status()
            logger.info(f"{url}/hub/api/users/{ctx.user}/servers: {r.text}")
        except requests.RequestException as e:
            logger.error(f"Failed to start MDDash server: {e}")
            raise exceptions.ExternalServiceError(
                f"Failed to start MDDash server: {e}"
            ) from e

    def _wait_for_server(self, ctx: MDDashContext) -> MDDashContext:
        url = self.svc_url

        max_retries = 60
        retry_interval = 5
        server_ready = False

        user_api_url = url + "/hub/api/user"

        for i in range(max_retries):
            logger.info(f"--- Poll attempt {i+1}/{max_retries}")

            try:
                resp = ctx.session.get(user_api_url)
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
                f"{ctx.user} did not start within {max_retries * retry_interval}s"
            )

        singleuser = default_server.get("url", "")
        ctx.singleuser = singleuser
        return ctx

    def _auth_mddash(self, ctx: MDDashContext) -> None:
        url = self.svc_url

        try:
            resp = ctx.session.get(f"{url}{ctx.singleuser}dash/", allow_redirects=True)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"MDDash auth failed: {e}")
            raise exceptions.ExternalServiceError(f"MDDash auth failed: {e}") from e

        if "mddash-auth" not in ctx.session.cookies:
            raise exceptions.VREAuthenticationError("mddash-auth cookie not set")

    def _create_experiment(self, ctx: MDDashContext) -> None:
        url = self.svc_url

        pdb_files = self.request_package.input_files
        if not pdb_files:
            raise exceptions.VREConfigurationError(
                "No PDB file found in request package"
            )
        pdb = pdb_files[0].name

        notebooks_repo = self.request_package.workflow.url or MDDASH_DEFAULT_PROTOCOL

        try:
            resp = ctx.session.post(
                f"{url}{ctx.singleuser}dash/api/experiments",
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
