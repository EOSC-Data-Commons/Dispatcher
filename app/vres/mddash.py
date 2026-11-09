import asyncio
from dataclasses import dataclass

import httpx

from .base_vre import VRE, vre_factory
import logging
from app import exceptions
from app import http as app_http
from app.config import settings
from vre_rocrate import MDDASH_PROGRAMMING_LANGUAGE
from app.constants import (
    MDDASH_DEFAULT_SERVICE,
    MDDASH_DEFAULT_PROTOCOL,
    MDDASH_PDB_INPUT_PARAM,
)

logger = logging.getLogger(__name__)


@dataclass
class MDDashContext:
    """Transient per-invocation state that flows explicitly through the MDDash
    request pipeline.  No mutable state leaks onto the VRE instance itself.

    ``session`` carries this flow's cookie jar (JWT login + xsrf + mddash-auth
    cookies); it is deliberately per-flow, not the shared app client, so
    user sessions never leak between dispatcher flows.
    """

    session: httpx.AsyncClient
    user: str
    xsrf_token: str
    singleuser: str = ""


class VREMDDash(VRE):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Settings snapshots taken once at construction (also test-tunable
        # per instance afterwards) instead of being read at call sites.
        self.wait_max_time = settings.mddash_wait_max_time
        self.poll_interval = settings.mddash_poll_interval

    def get_default_service(self):
        return MDDASH_DEFAULT_SERVICE

    async def post(self):
        # The service URL is resolved exactly once per flow: here.
        svc_url = await self.setup_service()
        await self.update_task_status("logging in to MDDash")
        ctx = await self._login(svc_url)

        try:
            await self.update_task_status("starting MDDash server")
            await self._start_server(svc_url, ctx)

            await self.update_task_status("waiting for MDDash server")
            ctx = await self._wait_for_server(svc_url, ctx)

            await self.update_task_status("authenticating with MDDash")
            await self._auth_mddash(svc_url, ctx)

            await self.update_task_status("creating MDDash experiment")
            await self._create_experiment(svc_url, ctx)

            await self.update_task_status("requesting MDDash login token")
            mddash_token = await self._request_token(svc_url, ctx)
        finally:
            await ctx.session.aclose()

        return f"{svc_url}{ctx.singleuser}dash/auth/login-token?token={mddash_token}"

    async def _login(self, svc_url: str) -> MDDashContext:
        bearer = {"Authorization": f"token {self.token}"}
        session = httpx.AsyncClient()

        try:
            r = await app_http.get(
                svc_url + "/hub/jwt_login", headers=bearer, client=session
            )
            logger.info(f"Call GET {svc_url}/hub/jwt_login")

            r = await app_http.get(
                svc_url + "/hub/home", headers=bearer, client=session
            )
            logger.info(f"Call GET {svc_url}/hub/home")
            xsrf_token = session.cookies.get("_xsrf")

            r = await app_http.get(
                svc_url + "/hub/api/user", headers=bearer, client=session
            )
            logger.info(f"Call GET {svc_url}/hub/api/user: {r.json()}")

            user = r.json()["name"]
        except httpx.HTTPError as e:
            await session.aclose()
            logger.error(f"MDDash login failed: {e}")
            raise exceptions.ExternalServiceError(f"MDDash login failed: {e}") from e

        return MDDashContext(session=session, user=user, xsrf_token=xsrf_token)

    async def _start_server(self, svc_url: str, ctx: MDDashContext) -> None:
        try:
            r = await app_http.post(
                f"{svc_url}/hub/api/users/{ctx.user}/servers/",
                headers={
                    "X-XSRFToken": ctx.xsrf_token,
                    "Content-Type": "application/json",
                    "Referer": f"{svc_url}/hub/home",
                },
                json={"_xsrf": ctx.xsrf_token},
                client=ctx.session,
                raise_for_status=False,
            )
            if r.status_code != 400:  # OK, server already exists
                r.raise_for_status()
            logger.info(f"{svc_url}/hub/api/users/{ctx.user}/servers: {r.text}")
        except httpx.HTTPError as e:
            logger.error(f"Failed to start MDDash server: {e}")
            raise exceptions.ExternalServiceError(
                f"Failed to start MDDash server: {e}"
            ) from e

    async def _wait_for_server(self, svc_url: str, ctx: MDDashContext) -> MDDashContext:
        max_time = self.wait_max_time
        poll = self.poll_interval
        waited = 0
        server_ready = False
        default_server: dict = {}

        user_api_url = svc_url + "/hub/api/user"

        while waited < max_time:
            logger.info(f"--- Poll attempt after {waited}s/{max_time}s")

            try:
                resp = await app_http.get(user_api_url, client=ctx.session)
            except httpx.HTTPError as e:
                logger.error(f"MDDash server poll failed: {e}")
                raise exceptions.ExternalServiceError(
                    f"MDDash server poll failed: {e}"
                ) from e

            user_info = resp.json()
            servers = user_info.get("servers", {})
            default_server = servers.get("", {})

            is_ready = default_server.get("ready", False)
            is_stopped = default_server.get("stopped", True)

            if is_ready and not is_stopped:
                server_ready = True
                break

            await asyncio.sleep(poll)
            waited += poll

        if not server_ready:
            raise exceptions.ExternalServiceError(
                f"{ctx.user} did not start within {max_time}s"
            )

        singleuser = default_server.get("url", "")
        ctx.singleuser = singleuser
        return ctx

    async def _auth_mddash(self, svc_url: str, ctx: MDDashContext) -> None:
        try:
            await app_http.get(
                f"{svc_url}{ctx.singleuser}dash/",
                client=ctx.session,
                follow_redirects=True,
            )
        except httpx.HTTPError as e:
            logger.error(f"MDDash auth failed: {e}")
            raise exceptions.ExternalServiceError(f"MDDash auth failed: {e}") from e

        if ctx.session.cookies.get("mddash-auth") is None:
            raise exceptions.VREAuthenticationError("mddash-auth cookie not set")

    def _pdb_id(self) -> str:
        """Read the scalar PDB accession from the pdb_id workflow input."""
        param = self.payload.input_by_name(MDDASH_PDB_INPUT_PARAM)
        if param is None or not isinstance(param.default_value, str):
            raise exceptions.VREConfigurationError(
                "Missing 'pdb_id' scalar input in MDDash request"
            )
        return param.default_value

    async def _create_experiment(self, svc_url: str, ctx: MDDashContext) -> None:
        pdb = self._pdb_id()

        notebooks_repo = self.payload.workflow.url or MDDASH_DEFAULT_PROTOCOL

        try:
            await app_http.post(
                f"{svc_url}{ctx.singleuser}dash/api/experiments",
                data={
                    "experiment-name": f"{self._request_id}: {pdb}",
                    "type": "pdb",
                    "pdb-id": pdb,
                    "notebooks-repo": notebooks_repo,
                },
                client=ctx.session,
            )
        except httpx.HTTPError as e:
            logger.error(f"Failed to create MDDash experiment: {e}")
            raise exceptions.ExternalServiceError(
                f"Failed to create MDDash experiment: {e}"
            ) from e

    async def _request_token(self, svc_url: str, ctx: MDDashContext) -> str:
        try:
            resp = await app_http.post(
                f"{svc_url}{ctx.singleuser}dash/auth/create-login-token",
                client=ctx.session,
            )

        except httpx.HTTPError as e:
            logger.error(f"Failed to request MDDash token: {e}")
            raise exceptions.ExternalServiceError(
                f"Failed to request MDDash token: {e}"
            ) from e

        t = resp.json()
        logger.info(f"Token retrieved, valid for {t['expires_in']} seconds")
        return t["token"]


vre_factory.register(MDDASH_PROGRAMMING_LANGUAGE, VREMDDash)
