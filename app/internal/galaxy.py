from .vre import VRE, vre_factory
from .im import IM
import aiohttp
import logging
from fastapi import HTTPException

logging.basicConfig(level=logging.INFO)

default_service = "https://usegalaxy.eu/"


class VREGalaxy(VRE):
    async def post(self):
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
            if svc.get("type") == "Service":
                url = svc["url"]
            elif svc.get("type") == "SoftwareApplication":
                # Send this destination to the IM to deploy the service
                # and get the URL of the deployed service
                im = IM(self.access_token)
                url = im.run_service(svc)
                if url is None:
                    raise HTTPException(
                        status_code=400, detail="Failed to deploy service"
                    )
            else:
                raise HTTPException(
                    status_code=400, detail="Invalid service type in runsOn"
                )

        url = url.rstrip("/")

        logging.info(f"{self.__class__.__name__}: calling {url} with {data}")

        response = None
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url + "/api/workflow_landings", headers=headers, json=data
            ) as resp:
                response = await resp.json()
                print(response)

        logging.info(f"{self.__class__.__name__}: returned {response}")
        landing_id = response["uuid"]
        url = f"{url}/workflow_landings/{landing_id}?public={public}"
        return url


vre_factory.register("https://galaxyproject.org/", VREGalaxy)
