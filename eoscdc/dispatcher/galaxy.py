from .vre import VRE,vre_factory
import requests

default_service = 'https://test.galaxyproject.org/'

class VREGalaxy(VRE):
    def post(self):
        public = False
     
        def modify_for_api_data_input(files):
            result = dict(map(lambda f: (f.properties()['name'], {
                "class": "File",
                "filetype": f.properties()['encodingFormat'].split("/")[-1],
                "location": f.id
            }), files))
            return result
     
        files = [e for e in self.entities.values() if e.type == 'File']
        workflow_url = self.workflow.get("url")
        if workflow_url is None:
            raise ValueError("Missing url in workflow entity")
     
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
     
        data = {
            "public": public,
            "request_state": modify_for_api_data_input(files), 
            "workflow_id": workflow_url,
            "workflow_target_type": "trs_url"
        }

        svc = self.root.get('runsOn')
        if svc is None:
            url = default_service
        else:
            url = svc['url'] 

        url += 'api/workflow_landings'

        response = requests.post(url, headers=headers, json=data)
        landing_id = response.json()['uuid']
        url = f"{url}/{landing_id}?public={public}"
        return url
 

vre_factory.register('https://galaxyproject.org/',VREGalaxy)
