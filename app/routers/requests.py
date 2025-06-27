from fastapi import APIRouter
from app.internal.vre import vre_factory

from fastapi import UploadFile, Depends
from rocrate.rocrate import ROCrate
from fastapi.exceptions import HTTPException
from app.dependencies import zipfile_parser, parse_rocrate
import uuid

router = APIRouter(
    prefix="/requests",
    tags=["requests"],
    responses={404: {"description": "Not found"}},
)


@router.post("/zip_rocrate/")
async def zip_rocrate(parsed_zipfile: (ROCrate, UploadFile) = Depends(zipfile_parser)):
    try:
        request_id = str(uuid.uuid4())
        vre_handler = vre_factory(*parsed_zipfile)
        # XXX: tentative, should queue the request somehow and track its progress
        return {"url": await vre_handler.post()}
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Handling request {request_id} failed:\n{e}"
        )


@router.post("/metadata_rocrate/")
async def metadata_rocrate(data: ROCrate = Depends(parse_rocrate)):
    try:
        request_id = str(uuid.uuid4())
        vre_handler = vre_factory(crate=data)
        return {"url": await vre_handler.post()}
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Handling request {request_id} failed:\n{e}"
        )
