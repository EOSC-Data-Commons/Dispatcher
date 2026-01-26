from .base_vre import VRE, vre_factory
import requests
import logging
from fastapi import HTTPException

logging.basicConfig(level=logging.INFO)


class VREHaddock(VRE):

    def get_default_service(self):
        return "https://www.bonvinlab.org/software/haddock3/"

    def post(self):
        public = False

        def modify_for_api_data_input(files):
            result = dict(
                map(
                    lambda f: (
                        f.properties()["name"],
                        {
                            "class": "File",
                            "filetype": f.properties()["encodingFormat"].split("/")[-1],
                            "location": f["url"],
                        },
                    ),
                    files,
                )
            )
            return result

        # TODO: vygenerovat heslo v mainu
        # zadne cookies nedostanu
        def register(url, password="password123"):
            data = {
                "username": "dummy@example.com",
                "password": password,
                "password2": password,
            }
            response = requests.post(f"{url}/register/", data=data)
            print("Status:", response.status_code)
            return response

        def login():
            return

        def upload():
            return

        def prepare_scenario():
            return

        files = [e for e in self.crate.get_entities() if e.type == "File"]
        workflow_url = self.crate.mainEntity.get("url")
        if workflow_url is None:
            raise HTTPException(
                status_code=400, detail="Missing url in workflow entity"
            )

        data = {
            "public": public,
            "request_state": modify_for_api_data_input(files),
            "workflow_id": workflow_url,
            "workflow_target_type": "trs_url",
        }

        url = self.svc_url

        logging.info(f"{self.__class__.__name__}: calling {url} with {data}")

        return url


vre_factory.register("https://www.bonvinlab.org/software/haddock3/", VREHaddock)
