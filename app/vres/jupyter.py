import io
import json
from typing import Any, Dict, Optional
from .base_vre import VRE, vre_factory
import requests
import logging
from app import exceptions
from app.constants import (
    JUPYTER_DEFAULT_SERVICE,
    JUPYTER_PROGRAMMING_LANGUAGE,
)
import zipfile as zf
import time

logging.basicConfig(level=logging.INFO)


class VREJupyter(VRE):
    def get_default_service(self):
        return JUPYTER_DEFAULT_SERVICE

    def _get_headers(self, token_type, token):
        return {
            "Authorization": f"{token_type} {token}",
            "Accept": "application/json",
        }

    def post(self):
        user_name = self._get_username()
        self._start_jupyter_server(user_name)
        api_token = self._create_api_token(user_name)
        notebook_name, notebook_content = self._get_notebook_from_zipfile()
        self._wait_for_server_creation()
        self.upload_notebook(notebook_content, notebook_name, user_name, api_token)
        return f"{self.get_default_service()}/user/{user_name}"

    def _start_jupyter_server(self, user_name):
        url = f"{self.get_default_service()}/services/jwt/users/{user_name}/servers/"
        response = requests.post(url, headers=self._get_headers("Bearer", self.token))
        response.raise_for_status()
        print(response)

    def _get_notebook_from_zipfile(self):
        copied_file_name = ""
        with io.BytesIO(self.body) as bytes_io:
            with zf.ZipFile(bytes_io) as zfile:
                for filename in zfile.namelist():
                    if filename.endswith(".ipynb"):
                        copied_file_name = filename
                        with zfile.open(filename) as f:
                            notebook_content = json.load(f)
        return copied_file_name, notebook_content

    def _wait_for_server_creation(self):
        info = self._get_userinfo()

        while (info.get("server") is None) or (
            info.get("servers").get("").get("ready") == False
        ):
            time.sleep(10)
            info = self._get_userinfo()

    def _get_username(self):
        userinfo = self._get_userinfo()
        user_name = userinfo.get("name")
        return user_name

    def _get_userinfo(self):
        userinfo_url = f"{self.get_default_service()}/services/jwt/user"
        userinfo = requests.get(
            userinfo_url, headers=self._get_headers("Bearer", self.token)
        ).json()

        return userinfo

    def _create_api_token(self, username: Optional[str] = None) -> str:
        """Create a new API token for Jupyter Server API access."""
        url = f"{self.get_default_service()}/services/jwt/users/{username}/tokens"

        try:
            response = requests.post(
                url, headers=self._get_headers("Bearer", self.token)
            )
            response.raise_for_status()
            token_data = response.json()
            print(token_data)
            api_token = token_data.get("token")
            if not api_token:
                raise exceptions.ServiceError("Token not found in response")
            return api_token
        except requests.RequestException as e:
            logging.error(f"Failed to create API token: {e}")
            raise exceptions.ServiceError(f"Token creation failed: {e}")

    def upload_notebook(
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
            response = requests.put(url, headers=headers, data=json.dumps(payload))
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logging.error(f"Failed to upload notebook: {e}")
            raise exceptions.ServiceError(f"Upload failed: {e}")


vre_factory.register(JUPYTER_PROGRAMMING_LANGUAGE, VREJupyter)
