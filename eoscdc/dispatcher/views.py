from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Request
import uuid
import requests
from rocrate.rocrate import ROCrate
import json
import zipfile

import logging
logger = logging.getLogger('django')


class CreateRequestView(APIView):
    def post(self, request):
        # Generate a unique request_id
        def modify_for_api_data_input(files):
            result = dict(map(lambda f: (f.properties()['name'], {
                "class": "File",
                "filetype": f.properties()['encodingFormat'].split("/")[-1],
                "location": f.id
            }), files))
            return result

        request_id = str(uuid.uuid4())
        logger.debug(f'{request_id}: {request.content_type}')

        if request.content_type == 'application/json':
            metadata = request.body
        elif request.content_type.split(';')[0] == 'multipart/form-data':
            zip_file = next(iter(request.FILES.values()))
            if not zipfile.is_zipfile(zip_file):
                return Response({'error': 'not a zip'})

            metadata = None
            with zipfile.ZipFile(zip_file) as zfile:
                for filename in zfile.namelist():
                    if filename == 'ro-crate-metadata.json':
                        with zfile.open(filename) as file:
                            metadata = file.read()

            if metadata is None:
                return Response({'error': f'ro-crate-metadata.json not found in zip'})
        else:
            return Response({'error': f'Unrecognized content_type = {request.content_type}'})

        crate = ROCrate(source=json.loads(metadata)) 
        public = False
        workflows = [e for e in crate.get_entities() if e.type == ['File', 'SoftwareSourceCode', 'ComputationalWorkflow']]
        files = [e for e in crate.get_entities() if e.type == 'File']
        if workflows == []:    
            return Response({"error": "No workflow present in request ROCrate"}, status=400)
        if workflows[0].get("url") is None:
            return Response({"error": "Missing URL for specified Workflow"}, status=400)
        workflow_url = workflows[0].get("url")
        url = 'https://test.galaxyproject.org/api/workflow_landings'

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
        response = requests.post(url, headers=headers, json=data)
        landing_id = response.json()['uuid']
        url = f"https://test.galaxyproject.org/workflow_landings/{landing_id}?public={public}"
        return Response({"url": url})

class GetRequestStatusView(APIView):
    def get(self, request, request_id):
        try:
            req = Request.objects.get(request_id=request_id)
            data = {
                "status": req.status,
                "redirect_url": req.redirect_url
            }
            return Response(data)
        except Request.DoesNotExist:
            return Response({"error": "Request not found"}, status=404)

