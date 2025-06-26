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
import io

app = FastAPI()

def parse_rocrate(data: dict):
    try:
        return ROCrate(source=data)
    except (ValueError, KeyError) as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid ROCrate data. Reason: {e}"
        )

def parse_json_metadata(metadata: str):
    try:
        return json.loads(metadata)
    except json.decoder.JSONDecodeError as json_exception:
        raise HTTPException(
            status_code=400, detail=f"Handling request failed. Invalid JSON format: \n{json_exception}"
        )

async def zipfile_parser(zipfile: UploadFile):
    metadata = None
    response = await zipfile.read()

    with zf.ZipFile(io.BytesIO(response)) as zfile:
        for filename in zfile.namelist():
            if filename == "ro-crate-metadata.json":
                with zfile.open(filename) as file:
                    metadata = file.read()
    if metadata is None:
        raise HTTPException(
            status_code=400, detail=f"ro-crate-metadata.json not found in zip"
        )
    rocrate_json = parse_json_metadata(metadata)
    return  (parse_rocrate(rocrate_json), zipfile)

@app.post("/requests/zip_rocrate/")
async def zip_rocrate(parsed_zipfile: (ROCrate, UploadFile) = Depends(zipfile_parser)):
    try:
        vre_handler = vre_factory(*parsed_zipfile)
        # XXX: tentative, should queue the request somehow and track its progress
        return {"url": await vre_handler.post()}
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Handling request {request_id} failed:\n{e}"
        )


@app.post("/requests/metadata_rocrate/")
async def metadata_rocrate(data: ROCrate = Depends(parse_rocrate)):
    try:
        request_id = str(uuid.uuid4())
        vre_handler = vre_factory(crate=data)
        return {"url": await vre_handler.post()}
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Handling request {request_id} failed:\n{e}"
        )
