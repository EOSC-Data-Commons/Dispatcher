import uuid
import requests
from rocrate.rocrate import ROCrate
import json
import zipfile
from fastapi import HTTPException, UploadFile
from .vre import vre_factory
from .galaxy import VREGalaxy
from .binder import VREBinder


def prepare_galaxy_landing(metadata: ROCrate):
    try:
        request_id = str(uuid.uuid4())
        vre_handler = vre_factory(crate=metadata)
        return {"url": vre_handler.post()}
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Handling request {request_id} failed:\n{e}"
        )


def prepare_galaxy_landing(metadata: ROCrate, zip_file: UploadFile):
    try:
        vre_handler = vre_factory(metadata=metadata, zip_file=zip_file)
        # XXX: tentative, should queue the request somehow and track its progress
        return {"url": vre_handler.post()}
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Handling request {request_id} failed:\n{e}"
        )
