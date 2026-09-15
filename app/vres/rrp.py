from .base_vre import VRE, vre_factory
import requests
import logging
from app import exceptions
from app.constants import RRP_PROGRAMMING_LANGUAGE, RRP_DEFAULT_SERVICE

logging.basicConfig(level=logging.INFO)


class VRERrp(VRE):
    # XXX: _get_workflow_url is not used yet, it contains the link to the remote ipynb contain a computation workflow.
    def _get_workflow_url(self):
        """Extract workflow URL from the crate."""
        workflow_url = self.crate.mainEntity.get("url")
        if workflow_url is None:
            # checked here, as some other vres might be actual files
            logging.error(f"{self.__class__.__name__}: Missing url in workflow entity")
            raise exceptions.WorkflowURLError("Missing url in workflow entity")
        return workflow_url

    def post(self):
        # NOTE: to align with galaxy:
        # this post request creates a rrp project and return the url to the
        # project page, not open the project.

        # URL of the local Flask proxy see `rrp_vre_proxy.py`
        PROXY_URL = self.svc_url

        # Backend URL that the proxy should forward to
        BACKEND_URL = "https://rrp-eosc.ethz.ch"

        # Use a session to store cookies automatically
        session = requests.Session()


        # Common headers including the X-Backend-Url header
        HEADERS = {"X-Backend-Url": BACKEND_URL, "Content-Type": "application/json"}

        # FIXME: don't commit with the real username and passward
        # login_data = {"user": "xxx", "password": "yyyy"}

        resp = session.post(f"{PROXY_URL}/api/login", json=login_data, headers=HEADERS)
        print(resp)
        print("Login response:", resp.status_code)

        # - step 1: create the project and it will fetch the image
        # project_data = {
        #     "type": "createFromExternalCatalog",
        #     "image": "reproducibleresearchplatform/rrp-tst:q75v54b-cunya",
        #     "environmentType": "jupyterlab",
        # }
        #
        # resp = session.post(
        #     f"{PROXY_URL}/api/projects", json=project_data, headers=HEADERS
        # )
        # print("Create project response:", resp.status_code)
        # print(resp.headers)
        # project_code = resp.headers.get("Location") # this return api/projects/xxxx, I need to extract the xxxx from it.

        # hard code for testing
        project_code = "8mihracs"

        # trigger the running of the project
        # -> get the url?
        # polling until the state is ready

        # keep on getting state until it is ready
        resp = session.get(f"{PROXY_URL}/api/projects/{project_code}", headers=HEADERS)
        print("Project status:", resp.status_code)
        print(resp.json())

        # - step 2: trigger the jupter to start (when the project is ready)
        start_req = {
          "type": 'start',
          "remote": False,
        }
        resp = session.post(f"{PROXY_URL}/api/projects/{project_code}", json=start_req, headers=HEADERS)
        print(resp)

        callback_url = f"{BACKEND_URL}/projects/{project_code}"

        return callback_url

    def get_default_service(self) -> str:
        return RRP_DEFAULT_SERVICE


vre_factory.register(RRP_PROGRAMMING_LANGUAGE, VRERrp)
