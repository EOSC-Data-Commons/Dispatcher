from .vre import VRE,vre_factory
import requests

import logging
logger = logging.getLogger('django')

default_service = 'https://test.galaxyproject.org/'

class VREGalaxy(VRE):
    def post(self):
        public = False
     
        def modify_for_api_data_input(files):
            result = dict(map(lambda f: (f.properties()['name'], {
                "class": "File",
                "filetype": f.properties()['encodingFormat'].split("/")[-1],
                "location": f['url']
            }), files))
            return result
     
        files = [e for e in self.entities.values() if e.type == 'File']
        workflow_url = self.workflow.get("url")
        if workflow_url is None:
            raise HTTPException(status_code=400, detail="Missing url in workflow entity")
     
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

        url = url.rstrip('/')

        logger.info(f'{self.__class__.__name__}: calling {url} with {data}')

        response = requests.post(url + '/api/workflow_landings', headers=headers, json=data)
        logger.info(f'{self.__class__.__name__}: returned {response}, {response.json()}')
        landing_id = response.json()['uuid']
        url = f"{url}/workflow_landings/{landing_id}?public={public}"
        return url
 

vre_factory.register('https://galaxyproject.org/',VREGalaxy)
