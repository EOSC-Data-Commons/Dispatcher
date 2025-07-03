from fastapi import APIRouter
from app.internal.vre import vre_factory
from fastapi.responses import JSONResponse
from fastapi import UploadFile, Depends
from rocrate.rocrate import ROCrate
from fastapi.exceptions import HTTPException
from app.dependencies import zipfile_parser, parse_rocrate
import uuid
from celery.result import AsyncResult
from app.tasks import galaxy_from_zipfile, galaxy_from_rocrate

router = APIRouter(
    prefix="/requests",
    tags=["requests"],
    responses={404: {"description": "Not found"}},
)


@router.get("/status")
def status(id: str):
    return AsyncResult(id).result


@router.post("/zip_rocrate/")
def zip_rocrate(parsed_zipfile: (ROCrate, UploadFile) = Depends(zipfile_parser)):
    task = galaxy_from_zipfile.apply_async(args=[parsed_zipfile], serializer="pickle")
    return JSONResponse({"task_id": task.id})

@router.post("/metadata_rocrate/")
def metadata_rocrate(data: ROCrate = Depends(parse_rocrate)):
    task = galaxy_from_rocrate.apply_async(args=[data], serializer="pickle")
    return JSONResponse({"task_id": task.id})
