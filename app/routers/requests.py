from fastapi import APIRouter
from app.internal.vre import vre_factory
from fastapi.responses import JSONResponse
from fastapi import UploadFile, Depends
from rocrate.rocrate import ROCrate
from fastapi.exceptions import HTTPException
from app.dependencies import zipfile_parser, parse_rocrate
import uuid
from celery.result import AsyncResult
from app.tasks import vre_from_zipfile, vre_from_rocrate
import logging

logger = logging.getLogger("uvicorn.error")

from typing import Annotated
from app.dependencies import oauth2_scheme

router = APIRouter(
    prefix="/requests",
    tags=["requests"],
    responses={404: {"description": "Not found"}},
)


@router.get("/{task_id}")
def status(token: str = Depends(oauth2_scheme), task_id: str = ""):
    task = AsyncResult(task_id)
    if task.failed():
        raise HTTPException(status_code=400, detail=f"Handling request failed:\n{task.result}")
    return JSONResponse({"task_id": task_id, "status": AsyncResult(task_id).status, "result": AsyncResult(task_id).result})


@router.post("/zip_rocrate/")
def zip_rocrate(token: str = Depends(oauth2_scheme), parsed_zipfile: (ROCrate, UploadFile) = Depends(zipfile_parser)):
    task = vre_from_zipfile.apply_async(args=[parsed_zipfile, token], serializer="pickle")
    return JSONResponse({"task_id": task.id})
    

@router.post("/metadata_rocrate/")
def metadata_rocrate(token: str = Depends(oauth2_scheme), data: ROCrate = Depends(parse_rocrate)):
    task = vre_from_rocrate.apply_async(args=[data, token], serializer="pickle")
    return JSONResponse({"task_id": task.id})
