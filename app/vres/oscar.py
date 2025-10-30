from .base_vre import VRE, vre_factory
import base64
import requests
import logging
import json
from fastapi import HTTPException

logging.basicConfig(level=logging.INFO)


class VREOSCAR(VRE):
    def __init__(self, crate=None, body=None, token=None):
        super().__init__(crate, body, token)
        self.fld_json = None

    def get_default_service(self):
        return "https://some.oscar.instance/"

    def _get_fdl_from_crate(self):
        if self.fld_json:
            return self.fld_json

        workflow_parts = self.crate.mainEntity.get("hasPart", [])

        if not workflow_parts:
            raise HTTPException(
                status_code=400, detail="Missing hasPart in workflow entity"
            )

        fdl_json = None
        script = None
        for elem in workflow_parts:
            if elem.get("@type") == "File":
                if elem.get("encodingFormat") == "text/json":
                    # Get the FDL file
                    try:
                        fdl_url = self.crate.dereference(elem.get("@id")).get("url")
                        response = requests.get(fdl_url, timeout=30)
                        fdl_json = response.json()
                    except Exception as ex:
                        raise HTTPException(
                            status_code=400, detail=f"Error getting service FDL: {ex}"
                        )
                elif elem.get("encodingFormat") == "text/x-shellscript":
                    # Get the script file
                    try:
                        script_url = self.crate.dereference(elem.get("@id")).get("url")
                        response = requests.get(script_url, timeout=30)
                        script = response.text
                    except Exception as ex:
                        raise HTTPException(
                            status_code=400, detail=f"Error getting service script: {ex}"
                        )
            else:
                raise HTTPException(
                    status_code=400, detail="Invalid hasPart type in workflow entity"
                )

        if not fdl_json:
            raise HTTPException(
                status_code=400, detail="Missing FDL in workflow entity"
            )

        if script:
            fdl_json["script"] = script

        self.fld_json = fdl_json
        return fdl_json

    def post(self):
        fdl_json = self._get_fdl_from_crate()
        service_name = fdl_json["name"]

        logging.info(f"Creating OSCAR service {service_name}")
        logging.debug(f"FDL: {json.dumps(fdl_json)}")
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        url = self.svc_url
        response = requests.post(f"{url}/system/services", headers=headers, json=fdl_json, timeout=60)
        if response.status_code != 201:
            raise HTTPException(
                status_code=400, detail=f"Error creating OSCAR service: {response.text}"
            )

        service_url = f"{url}/system/services/{service_name}"

        files = self._get_input_files()
        self._invoke_service(url, service_name, files)

        return service_url

    def _get_input_files(self):
        # Get all files except the workflow and destination
        non_input_files = []
        non_input_files.append(self.crate.root_dataset.get("runsOn").get('@id'))
        non_input_files.append(self.crate.mainEntity.get('@id'))
        for elem in self.crate.mainEntity.get("hasPart", []):
            if elem.get("@type") == "File":
                non_input_files.append(elem.get("@id"))
        return [e for e in self.crate.get_entities() if e.type == "File" and e.get('@id') not in non_input_files]

    def _invoke_service(self, oscar_url, service_name, files):
        headers = {"Authorization": f"Bearer {self.token}"}
        url = f"{oscar_url}/job/{service_name}"
        for f in files:
            try:
                logging.info(f"Creating invocation for service {service_name} and file {f.get('url')}")
                response = requests.get(f.get("url"), timeout=60)
                file_content = response.text
            except Exception as e:
                logging.error(f"Error fetching file {f.get('url')}: {e}")
                continue
            response = requests.post(url, headers=headers, data=base64.b64encode(file_content.encode()), timeout=60)
            if response.status_code != 201:
                logging.error(
                    f"Error invoking OSCAR service for file {f.get('url')}: {response.text}"
                )

    def delete(self):
        fdl_json = self._get_fdl_from_crate()
        service_name = fdl_json["name"]

        logging.info(f"Deleting OSCAR service {service_name}")
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        url = self.svc_url
        response = requests.delete(f"{url}/system/services/{service_name}", headers=headers, timeout=60)
        if response.status_code != 204:
            raise HTTPException(
                status_code=400, detail=f"Error deleting OSCAR service: {response.text}"
            )


vre_factory.register("https://oscar.grycap.net/", VREOSCAR)
