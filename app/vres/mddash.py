from .base_vre import VRE, vre_factory
import zipfile as zf
import io
import logging
import requests
import uuid
import tempfile
import time
from app.config import settings
from app.constants import MDDASH_DEFAULT_SERVICE, MDDASH_PROGRAMMING_LANGUAGE, MDDASH_DEFAULT_PROTOCOL

logging.basicConfig(level=logging.INFO)

class VREMDDash(VRE):
    def get_default_service(self):
        return MDDASH_DEFAULT_SERVICE

# TODO: more options to populate experiment must be supported, reference to MDDB in particular
# PDB only is proof of concept
    def post(self):

        self._login()
        self._start_server()
        self._wait_for_server()
        self._auth_mddash()
        self._create_experiment()
       
        return f"{self.svc_url}{self.singleuser}dash/"

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

    def _wait_for_server(self):
        url = self.svc_url
        url = url.rstrip("/")

        max_retries = 60
        retry_interval = 5
        server_ready = False

        user_api_url = url + '/hub/api/user'
    
        for i in range(max_retries):
            logging.info(f"--- Poll attempt {i+1}/{max_retries}")
    
            resp = self.session.get(user_api_url)
            resp.raise_for_status()
    
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
            raise RuntimeError(f"{self.user} did not start within {max_retries*retry_interval}s")

        self.singleuser = default_server.get("url","")
    
    def _auth_mddash(self):
        url = self.svc_url
        url = url.rstrip("/")

        resp = self.session.get(f"{url}{self.singleuser}dash/",allow_redirects=True)
        resp.raise_for_status()

        if "mddash-auth" not in self.session.cookies:
            raise RuntimeError("mddash-auth cookie not set")
        
    def _create_experiment(self):
        url = self.svc_url
        url = url.rstrip("/")

        pdb = '1L2Y' # XXX

        resp = self.session.post(
                f"{url}{self.singleuser}dash/api/experiments",
                data={
                    "experiment-name" : f"{self.task}: {pdb}",
                    "type": "pdb", # XXX
                    "pdb-id": pdb,
                    "notebooks-repo": MDDASH_DEFAULT_PROTOCOL # XXX
                })
        resp.raise_for_status()
        
vre_factory.register(MDDASH_PROGRAMMING_LANGUAGE, VREMDDash)
