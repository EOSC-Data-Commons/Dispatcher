from .vre import VRE, vre_factory
import requests
import logging
from fastapi import HTTPException

logging.basicConfig(level=logging.INFO)


class VREOSCAR(VRE):
    def get_default_service(self):
        return "https://some.oscar.instance/"

    def post(self):
        workflow_parts = self.workflow.get("hasPart", [])

        if not workflow_parts or len(workflow_parts) < 2:
            raise HTTPException(
                status_code=400, detail="Missing hasPart in workflow entity"
            )

        fdl = None
        script = None
        for elem in workflow_parts:
            if elem.get("@type") == "File":
                if elem.get("encodingFormat") == "text/yaml":
                    # Get the FDL file
                    fdl_url = self.entities.get(elem.get("@id")).get("url")
                    response = requests.get(fdl_url)
                    fdl = response.text
                elif elem.get("encodingFormat") == "text/x-shellscript":
                    # Get the script file
                    script_url = self.entities.get(elem.get("@id")).get("url")
                    response = requests.get(script_url)
                    script = response.text
            else:
                raise HTTPException(
                    status_code=400, detail="Invalid hasPart type in workflow entity"
                )

        # @TODO: create OSCAR service with the FDL and script and return the service URL
        self.svc_url

        return ""


vre_factory.register("https://oscar.grycap.net/", VREOSCAR)
