from fastapi import FastAPI, Header,UploadFile, Depends
from .views import post_request, prepare_galaxy_landing
from pydantic import BaseModel
from typing import Annotated
from fastapi.exceptions import HTTPException
from rocrate.rocrate import ROCrate
import zipfile as zf
import json


app = FastAPI()


def zipfile_parser(zipfile: UploadFile):
    metadata = None
    with zf.ZipFile(zipfile.file) as zfile:
        for filename in zfile.namelist():
            if filename == 'ro-crate-metadata.json':
                with zfile.open(filename) as file:
                    metadata = file.read()
    if metadata is None:
        raise HTTPException(status_code=400, detail=f'ro-crate-metadata.json not found in zip')
    return (ROCrate(source=json.loads(metadata)), zipfile)


@app.post("/requests/zip_rocrate/")
async def zip_rocrate(parsed_zipfile: (ROCrate, UploadFile) = Depends(zipfile_parser), content_type: Annotated[str | None, Header()] = None):
    return prepare_galaxy_landing(*parsed_zipfile)

def checker(data: dict):
    try:
       return ROCrate(source=data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid ROCrate data. Reason: {e}")

@app.post("/requests/metadata_rocrate/")
async def metadata_rocrate(data: dict = Depends(checker)):
    return prepare_galaxy_landing(data)