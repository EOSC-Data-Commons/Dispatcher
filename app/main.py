from fastapi import FastAPI, Header, UploadFile, Depends
from typing import Annotated
from fastapi.exceptions import HTTPException
from rocrate.rocrate import ROCrate
import zipfile as zf
import json
import uuid
from .vre import vre_factory
from .galaxy import VREGalaxy
from .binder import VREBinder

app = FastAPI()


def zipfile_parser(zipfile: UploadFile):
    metadata = None
    with zf.ZipFile(zipfile.file) as zfile:
        for filename in zfile.namelist():
            if filename == "ro-crate-metadata.json":
                with zfile.open(filename) as file:
                    metadata = file.read()
    if metadata is None:
        raise HTTPException(
            status_code=400, detail=f"ro-crate-metadata.json not found in zip"
        )
    return (ROCrate(source=json.loads(metadata)), zipfile)


@app.post("/requests/zip_rocrate/")
async def zip_rocrate(parsed_zipfile: (ROCrate, UploadFile) = Depends(zipfile_parser)):
    try:
        vre_handler = vre_factory(*parsed_zipfile)
        # XXX: tentative, should queue the request somehow and track its progress
        return {"url": vre_handler.post()}
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Handling request {request_id} failed:\n{e}"
        )


def checker(data: dict):
    try:
        return ROCrate(source=data)
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid ROCrate data. Reason: {e}"
        )


@app.post("/requests/metadata_rocrate/")
async def metadata_rocrate(data: ROCrate = Depends(checker)):
    try:
        request_id = str(uuid.uuid4())
        vre_handler = vre_factory(crate=data)
        return {"url": vre_handler.post()}
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Handling request {request_id} failed:\n{e}"
        )
