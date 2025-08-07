from .vre import VRE, vre_factory
import requests
import logging
import yaml
from fastapi import HTTPException

logging.basicConfig(level=logging.INFO)


class VREOSCAR(VRE):
    def get_default_service(self):
        return "https://some.oscar.instance/"

    def post(self):
        workflow_parts = self.workflow.get("hasPart", [])

        if not workflow_parts:
            raise HTTPException(
                status_code=400, detail="Missing hasPart in workflow entity"
            )

        fdl = None
        script = None
        for elem in workflow_parts:
            if elem.get("@type") == "File":
                if elem.get("encodingFormat") == "text/yaml":
                    # Get the FDL file
                    try:
                        fdl_url = self.entities.get(elem.get("@id")).get("url")
                        response = requests.get(fdl_url)
                        fdl = response.text
                        fdl_yaml = yaml.safe_load(fdl)
                    except Exception as ex:
                        raise HTTPException(
                            status_code=400, detail=f"Error getting service FDL: {ex}"
                        )
                elif elem.get("encodingFormat") == "text/x-shellscript":
                    # Get the script file
                    try:
                        script_url = self.entities.get(elem.get("@id")).get("url")
                        response = requests.get(script_url)
                        script = response.text
                    except Exception as ex:
                        raise HTTPException(
                            status_code=400, detail=f"Error getting service script: {ex}"
                        )
            else:
                raise HTTPException(
                    status_code=400, detail="Invalid hasPart type in workflow entity"
                )

        if not fdl:
            raise HTTPException(
                status_code=400, detail="Missing FDL in workflow entity"
            )

        if script:
            service = fdl_yaml["functions"]["oscar"][0]
            service_name = list(service.keys())[0]
            service[service_name]["script"] = script
            fdl = yaml.safe_dump(fdl_yaml)

        headers = {"Authorization": f"Bearer {self.token}"}
        url = self.svc_url
        response = requests.post(f"{url}/system/services", data=fdl, headers=headers)
        if response.status_code != 201:
            raise HTTPException(
                status_code=400, detail=f"Error creating OSCAR service: {response.text}"
            )

        return f"{url}/system/services/{service_name}"


vre_factory.register("https://oscar.grycap.net/", VREOSCAR)
