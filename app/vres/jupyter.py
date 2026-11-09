import asyncio
import json
from typing import Any, Dict, Optional

import httpx

from .base_vre import VRE, vre_factory
import logging
from app import exceptions
from app import http as app_http
from app.config import settings
from vre_rocrate import JUPYTER_PROGRAMMING_LANGUAGE
from app.constants import JUPYTER_DEFAULT_SERVICE

logger = logging.getLogger(__name__)


class VREJupyter(VRE):
    def get_default_service(self):
        return JUPYTER_DEFAULT_SERVICE

    def _get_headers(self, token_type, token):
        return {
            "Authorization": f"{token_type} {token}",
            "Accept": "application/json",
        }

    async def post(self):
        await self.setup_service()
        user_name = await self._get_username()
        await self._start_jupyter_server(user_name)
        await self.update_task_status("Jupyter server starting")
        api_token = await self._create_api_token(user_name)
        notebook_name, notebook_content = self._get_notebook_from_crate()
        await self._wait_for_server_creation()
        await self.upload_notebook(
            notebook_content, notebook_name, user_name, api_token
        )
        return f"{self.get_default_service()}/user/{user_name}"

    async def _get_username(self):
        userinfo = await self._get_userinfo()
        user_name = userinfo.get("name")
        if not user_name:
            raise exceptions.VREAuthenticationError(
                "Username not found in userinfo response"
            )
        return user_name

    async def _get_userinfo(self):
        userinfo_url = f"{self.get_default_service()}/services/jwt/user"
        response = await app_http.get(
            userinfo_url, headers=self._get_headers("Bearer", self.token)
        )
        return response.json()

    async def _start_jupyter_server(self, user_name):
        url = f"{self.get_default_service()}/services/jwt/users/{user_name}/servers/"
        try:
            await app_http.post(url, headers=self._get_headers("Bearer", self.token))
        except httpx.HTTPError as e:
            logger.error(f"Failed to start Jupyter server: {e}")
            raise exceptions.ExternalServiceError(
                f"Jupyter server start failed: {e}"
            ) from e

    async def _create_api_token(self, username: Optional[str] = None) -> str:
        """Create a new API token for Jupyter Server API access."""
        url = f"{self.get_default_service()}/services/jwt/users/{username}/tokens"

        try:
            response = await app_http.post(
                url, headers=self._get_headers("Bearer", self.token)
            )
            token_data = response.json()
            logger.debug(f"Token data: {token_data}")
            api_token = token_data.get("token")
            if not api_token:
                raise exceptions.InvalidResponseError("Token not found in response")
            return api_token
        except httpx.HTTPError as e:
            logger.error(f"Failed to create API token: {e}")
            raise exceptions.ExternalServiceError(f"Token creation failed: {e}")

    def _get_notebook_from_crate(self):
        for fref in self.payload.files:
            if fref.id.endswith(".ipynb"):
                content = fref.properties.get("content")
                if content is not None:
                    if isinstance(content, bytes):
                        content = json.loads(content.decode())
                    return fref.id, content
        raise exceptions.VREConfigurationError("No .ipynb notebook found in crate")

    async def _wait_for_server_creation(self):
        """Bounded readiness wait (fixes the previously unbounded poll loop)."""
        max_time = settings.jupyter_wait_max_time
        poll = settings.jupyter_poll_interval
        waited = 0
        while waited < max_time:
            info = await self._get_userinfo()
            servers = info.get("servers") or {}
            server_ready = (info.get("server") is not None) and servers.get("", {}).get(
                "ready", False
            )
            if server_ready:
                logger.info("Jupyter server is ready.")
                return
            await asyncio.sleep(poll)
            waited += poll
        raise exceptions.ExternalServiceError(
            f"Jupyter server did not become ready within {max_time}s"
        )

    async def upload_notebook(
        self,
        notebook_content: Dict[str, Any],
        filename: str,
        username: Optional[str],
        api_token,
    ) -> Dict[str, Any]:
        """Upload a notebook file to the user's Jupyter server."""
        url = f"{self.get_default_service()}/user/{username}/api/contents/{filename}"

        headers = self._get_headers("token", api_token)
        payload = {
            "type": "notebook",
            "format": "json",
            "content": notebook_content,
        }

        try:
            response = await app_http.put(
                url, headers=headers, content=json.dumps(payload)
            )
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to upload notebook: {e}")
            raise exceptions.ExternalServiceError(f"Upload failed: {e}") from e


vre_factory.register(JUPYTER_PROGRAMMING_LANGUAGE, VREJupyter)
