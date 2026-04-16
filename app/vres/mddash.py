from .base_vre import VRE, vre_factory
import zipfile as zf
import io
import logging
import requests
import uuid
import tempfile
from app.config import settings
from app.constants import MDDASH_DEFAULT_SERVICE, MDDASH_PROGRAMMING_LANGUAGE

logging.basicConfig(level=logging.INFO)

class VREMDDash(VRE):
    def get_default_service(self):
        return MDDASH_DEFAULT_SERVICE

# TODO: more options to populate experiment must be supported, reference to MDDB in particular
# PDB only is proof of concept
    def post(self):

        self._login()
        self._start_server()
       
        return None

    def _login(self):
        url = self.svc_url
        url = url.rstrip("/")
        
        bearer = { "Authorization": f"token {self.token}" }
        self.session = requests.Session()

        logging.info(bearer)
        r = self.session.get(url + '/hub/jwt_login',headers=bearer)
        r.raise_for_status()
        logging.info(f"GET {url}/hub/jwt_login {r.text}")
    
        r = self.session.get(url + "/hub/home",headers=bearer)
        r.raise_for_status()
        logging.info(f"GET {url}/hub/home {r.text}")
        self.xsrf_token = self.session.cookies.get("_xsrf")

        r = self.session.get(url + "/hub/api/user",headers=bearer)
        r.raise_for_status()
        logging.info(f"GET {url}/hub/api/user: {r.json()}")

        self.user = r.json()['name']


    def _start_server(self):
        url = self.svc_url
        url = url.rstrip("/")

        r = self.session.post(
                f"{url}/hub/api/users/{self.user}/servers/",
                headers = {
                    "X-XSRFToken": self.xsrf_token,
                    "Content-Type": "application/json",
                    "Referer": f"{url}/hub/home"
                },
                json={"_xsrf": self.xsrf_token}
        )
        if (r.status_code != 400):  # OK, server already exists
            r.raise_for_status()
        logging.info(f"{url}/hub/api/users/{self.user}/servers: {r.text}")

        
vre_factory.register(MDDASH_PROGRAMMING_LANGUAGE, VREMDDash)
