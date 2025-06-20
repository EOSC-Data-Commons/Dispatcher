import uuid
import requests
from rocrate.rocrate import ROCrate
import json
import zipfile
from fastapi import HTTPException
from .vre import vre_factory
from .galaxy import VREGalaxy
from .binder import VREBinder

import logging
logger = logging.getLogger('django')


async def post_request(request):
    # Generate a unique request_id
    request_id = str(uuid.uuid4())
    zip_file = None

    content_type= request.headers.get("content-type", None)


    if content_type == 'application/json':
        metadata = await request.body()
    elif content_type.split(';')[0] == 'multipart/form-data':
        async with request.form(max_files=1000, max_fields=1000) as form:
            metadata = None
            with zipfile.ZipFile(form["zipfile"].file) as zfile:
                for filename in zfile.namelist():
                    if filename == 'ro-crate-metadata.json':
                        with zfile.open(filename) as file:
                            metadata = file.read()

        if metadata is None:
            raise HTTPException(status_code=400, detail=f'ro-crate-metadata.json not found in zip')
    else:
        raise HTTPException(status_code=400, detail=f'Unrecognized content_type = {content_type}')

    try:
        vre_handler = vre_factory(metadata=metadata,zip_file=zip_file)

        # XXX: tentative, should queue the request somehow and track its progress
        return {'url': vre_handler.post()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'Handling request {request_id} failed:\n{e}')