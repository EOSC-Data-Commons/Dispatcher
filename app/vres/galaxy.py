from .base_vre import VRE, vre_factory
import requests
import logging
from app import exceptions 
logging.basicConfig(level=logging.INFO)


class VREGalaxy(VRE):
    def get_default_service(self):
        return "https://usegalaxy.eu/"

    def post(self):
        data = self._prepare_workflow_data()
        response_data = self._send_workflow_request(data)
        landing_id = self._extract_landing_id(response_data)
        return self._build_final_url(landing_id)

    def _prepare_workflow_data(self):
        """Prepare the workflow data for the API request."""
        files = self._get_workflow_files()
        workflow_url = self._get_workflow_url()
        
        return {
            "public": False,
            "request_state": self._modify_for_api_data_input(files),
            "workflow_id": workflow_url,
            "workflow_target_type": "trs_url",
        }

    def _get_workflow_files(self):
        """Extract file entities from the crate."""
        return [e for e in self.crate.get_entities() if e.type == "File"]

    def _get_workflow_url(self):
        """Extract workflow URL from the crate."""
        workflow_url = self.crate.mainEntity.get("url")
        if workflow_url is None:
            logging.error(f"{self.__class__.__name__}: Missing url in workflow entity")
            raise exceptions.WorkflowURLError()
        return workflow_url

    def _modify_for_api_data_input(self, files):
        """Convert file entities to API-compatible format."""
        result = {}
        for f in files:
            properties = f.properties()
            result[properties["name"]] = {
                "class": "File",
                "filetype": properties["encodingFormat"].split("/")[-1],
                "location": f["url"],
            }
        return result

    def _send_workflow_request(self, data):
        """Send the workflow request to the Galaxy API."""
        headers = {
            "Content-Type": "application/json", 
            "Accept": "application/json"
        }
        
        url = self.svc_url.rstrip("/")
        api_url = f"{url}/api/workflow_landings"
        
        logging.info(f"{self.__class__.__name__}: calling {api_url} with {data}")
        
        try:
            response = requests.post(api_url, headers=headers, json=data)
            response.raise_for_status()
        except requests.RequestException as e:
            logging.error(f"{self.__class__.__name__}: API request failed: {e}")
            raise exceptions.GalaxyAPIError() from e
        return response.json()

    def _extract_landing_id(self, response_data):
        """Extract the landing ID from the API response."""
        uuid = response_data.get("uuid")
        if uuid is None:
            logging.error(f"{self.__class__.__name__}: Galaxy API response missing 'uuid' field")
            raise exceptions.InvalidGalaxyResponseError()
        return uuid
        
    def _build_final_url(self, landing_id):
        """Build the final workflow landing URL."""
        url = self.svc_url.rstrip("/")
        public = False
        return f"{url}/workflow_landings/{landing_id}?public={public}"

vre_factory.register("https://galaxyproject.org/", VREGalaxy)
