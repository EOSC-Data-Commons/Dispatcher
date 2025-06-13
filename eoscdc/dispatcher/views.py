from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Request
import uuid
import requests
from rocrate.rocrate import ROCrate
import json
import zipfile

from .vre import vre_factory
from .galaxy import VREGalaxy
from .binder import VREBinder

import logging
logger = logging.getLogger('django')


class CreateRequestView(APIView):
    def post(self, request):
        # Generate a unique request_id
        request_id = str(uuid.uuid4())
        zip_file = None

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

        try:
            vre_handler = vre_factory(metadata=metadata,zip_file=zip_file)
    
            # XXX: tentative, should queue the request somehow and track its progress
            return Response({'url',vre_handler.post()})
        except Exception as e:
            return Response({'error': f'Handling request {request_id} failed:\n{e}'})
    

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

