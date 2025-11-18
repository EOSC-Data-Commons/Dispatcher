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

    def post(self):
        request_id = str(uuid.uuid4())

        with tempfile.TemporaryDirectory() as temp_dir:
            self._unzip_request(temp_dir)

        self._login()
        self._start_server()
       
        return None

    def _unzip_request(self,repo):
        logging.debug(f"{__class__.__name__}: unzipping ROCrate")
        with io.BytesIO(self.body) as bytes_io:
            with zf.ZipFile(bytes_io) as zfile:
                for filename in zfile.namelist():
                    logging.debug("  " + filename)
                    if filename != "ro-crate-metadata.json":
                        with zfile.open(filename) as z, open(
                            f"{repo}/{filename}", "wb"
                        ) as f:
                            f.write(z.read())

    def _login(self):
        url = self.svc_url
        url = url.rstrip("/")
        
        bearer = { "Authorization": f"bearer {self.token}" }

        self.session = requests.Session()

        r = self.session.get(url + '/hub/login',headers=bearer)
        r.raise_for_status()

        r = self.session.get(url + '/hub/api/user')
        r.raise_for_status()
        logging.info(f"GET {url}/hub/api/user: {r.json()}")
        user = r.json()['name']

        logging.info(f"_xsrf: {self.session.cookies.get('_xsrf')}")
        r = self.session.post(f"{url}/hub/api/users/{user}/tokens",headers={ 'X-XSRFToken' : self.session.cookies.get('_xsrf')})
        r.raise_for_status()
    
        logging.info(f"token: {r.json()}")
        self.user = user
        self.api_token = r.json()['token']

    def _start_server(self):
        url = self.svc_url
        url = url.rstrip("/")


        r = self.session.post(f"{url}/hub/api/users/{self.user}/server",headers={'Authorization': 'token '+self.api_token })
        logging.info(f"POST server: {r.status_code} {r.text}")
        # XXX: 400 is OK, it means the server is already running

        #r = self.session.post(f"{url}/hub/api/users/{self.user}/tokens",headers={'Authorization': 'token '+self.api_token },json={"scopes": [f"access:servers!user={self.user}"]})

        # XXX: weak token, good enough to authenticate initial request 
        r = self.session.post(f"{url}/hub/api/users/{self.user}/tokens",
                              headers={'Authorization': 'token '+self.api_token },
                              json={"scopes": [f"read:users!user={self.user}", f"access:servers!server={self.user}"]}
                            )
        logging.info(f"POST tokens: {r.status_code} {r.text}")

        self.server_token = r.json()['token']


 



vre_factory.register(MDDASH_PROGRAMMING_LANGUAGE, VREMDDash)
