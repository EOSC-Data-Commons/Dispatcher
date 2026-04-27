"""Jupyter VRE implementation.

This module implements the Jupyter notebook execution VRE, which creates
Jupyter servers and uploads notebooks for interactive analysis.
"""

import io
import json
import logging
import time
from typing import Any, Dict, Optional

import requests
from app import exceptions
from app.constants import JUPYTER_DEFAULT_SERVICE, JUPYTER_PROGRAMMING_LANGUAGE

from .base_vre import VRE, vre_factory

logging.basicConfig(level=logging.INFO)


class VREJupyter(VRE):
    """Jupyter notebook execution VRE."""

    def get_default_service(self) -> str:
        """Return the default Jupyter service URL."""
        return JUPYTER_DEFAULT_SERVICE

    def _get_headers(self, token_type: str, token: str) -> Dict[str, str]:
        """Build headers for API requests.

        Args:
            token_type: Type of token (e.g., "Bearer", "token").
            token: The authentication token.

        Returns:
            Dictionary of headers for the request.
        """
        return {
            "Authorization": f"{token_type} {token}",
            "Accept": "application/json",
        }

    def post(self) -> str:
        """Create Jupyter server and upload notebook.

        Returns:
            URL to access the Jupyter server.
        """
        user_name = self._get_username()
        self._start_jupyter_server(user_name)
        api_token = self._create_api_token(user_name)
        notebook_name, notebook_content = self._get_notebook_from_zipfile()
        self._wait_for_server_creation()
        self.upload_notebook(notebook_content, notebook_name, user_name, api_token)
        return f"{self.get_default_service()}/user/{user_name}"

    def _get_username(self) -> str:
        """Get username from the service.

        Returns:
            The username for the current session.
        """
        userinfo = self._get_userinfo()
        user_name = userinfo.get("name")
        if not user_name:
            raise exceptions.ServiceError("Username not found in userinfo")
        return user_name

    def _get_userinfo(self) -> Dict[str, Any]:
        """Fetch user information from the service.

        Returns:
            Dictionary containing user information.
        """
        userinfo_url = f"{self.get_default_service()}/services/jwt/user"
        response = requests.get(
            userinfo_url, headers=self._get_headers("Bearer", self.token)
        )
        response.raise_for_status()
        return response.json()

    def _start_jupyter_server(self, user_name: str) -> None:
        """Start a Jupyter server for the user.

        Args:
            user_name: The username to start the server for.
        """
        url = f"{self.get_default_service()}/services/jwt/users/{user_name}/servers/"
        response = requests.post(url, headers=self._get_headers("Bearer", self.token))
        response.raise_for_status()

    def _create_api_token(self, username: Optional[str] = None) -> str:
        """Create a new API token for Jupyter Server API access.

        Args:
            username: Optional username to create token for.

        Returns:
            The newly created API token.

        Raises:
            ServiceError: If token creation fails or token not found.
        """
        url = f"{self.get_default_service()}/services/jwt/users/{username}/tokens"

        try:
            response = requests.post(
                url, headers=self._get_headers("Bearer", self.token)
            )
            response.raise_for_status()
            token_data = response.json()
            api_token = token_data.get("token")
            if not api_token:
                raise exceptions.ServiceError("Token not found in response")
            return api_token
        except requests.RequestException as e:
            logging.error(f"Failed to create API token: {e}")
            raise exceptions.ServiceError(f"Token creation failed: {e}") from e

    def _get_notebook_from_zipfile(self) -> tuple[str, Dict[str, Any]]:
        """Extract notebook from the ZIP file body.

        Returns:
            Tuple of (notebook_filename, notebook_content).

        Raises:
            ServiceError: If no notebook is found in the ZIP.
        """
        import zipfile

        copied_file_name = ""
        notebook_content: Dict[str, Any] = {}

        if not self.body:
            raise exceptions.ServiceError("No body provided for notebook extraction")

        with io.BytesIO(self.body) as bytes_io:
            with zipfile.ZipFile(bytes_io) as zfile:
                for filename in zfile.namelist():
                    if filename.endswith(".ipynb"):
                        copied_file_name = filename
                        with zfile.open(filename) as f:
                            notebook_content = json.load(f)
                        break

        if not copied_file_name:
            raise exceptions.ServiceError("No notebook (.ipynb) found in ZIP file")

        return copied_file_name, notebook_content

    def _wait_for_server_creation(self) -> None:
        """Wait for the Jupyter server to be ready."""
        info = self._get_userinfo()

        while (info.get("server") is None) or (
            info.get("servers", {}).get("", {}).get("ready") is False
        ):
            time.sleep(10)
            info = self._get_userinfo()

    def upload_notebook(
        self,
        notebook_content: Dict[str, Any],
        filename: str,
        username: Optional[str],
        api_token: str,
    ) -> Dict[str, Any]:
        """Upload a notebook file to the user's Jupyter server.

        Args:
            notebook_content: The notebook JSON content.
            filename: The filename to save as.
            username: The username for the server path.
            api_token: The API token for authentication.

        Returns:
            Response from the upload request.

        Raises:
            ServiceError: If upload fails.
        """
        url = f"{self.get_default_service()}/user/{username}/api/contents/{filename}"

        headers = self._get_headers("token", api_token)
        payload = {
            "type": "notebook",
            "format": "json",
            "content": notebook_content,
        }

        try:
            response = requests.put(url, headers=headers, data=json.dumps(payload))
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"Failed to upload notebook: {e}")
            raise exceptions.ServiceError(f"Upload failed: {e}") from e


vre_factory.register(JUPYTER_PROGRAMMING_LANGUAGE, VREJupyter)
