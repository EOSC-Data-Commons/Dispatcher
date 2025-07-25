from .vre import VRE, vre_factory
import aiohttp
import logging
from fastapi import HTTPException

logging.basicConfig(level=logging.INFO)

default_service = "https://usegalaxy.eu/"


class VREGalaxy(VRE):
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

        files = [e for e in self.entities.values() if e.type == "File"]
        workflow_url = self.workflow.get("url")
        if workflow_url is None:
            raise HTTPException(
                status_code=400, detail="Missing url in workflow entity"
            )

        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        data = {
            "public": public,
            "request_state": modify_for_api_data_input(files),
            "workflow_id": workflow_url,
            "workflow_target_type": "trs_url",
        }
        svc = self.root.get("runsOn")
        if svc is None:
            url = default_service
        else:
            url = self.get_service(svc).get(["url"])

        url = url.rstrip("/")

        logging.info(f"{self.__class__.__name__}: calling {url} with {data}")

        response = None
        response = requests.post(
            f"{url}/api/workflow_landings", headers=headers, json=data
        ).json()
        logging.info(f"{self.__class__.__name__}: returned {response}")
        landing_id = response["uuid"]
        url = f"{url}/workflow_landings/{landing_id}?public={public}"
        return url


vre_factory.register("https://galaxyproject.org/", VREGalaxy)
