from fastapi import APIRouter
from fastapi.responses import JSONResponse
from fastapi import UploadFile, Depends, Request
from rocrate.rocrate import ROCrate
from fastapi.exceptions import HTTPException
from .utils import parse_zipfile, parse_rocrate
from celery.result import AsyncResult
from app.celery.tasks import vre_from_zipfile, vre_from_rocrate
import logging
from typing import Dict

logger = logging.getLogger("uvicorn.error")

from .utils import oauth2_scheme

router = APIRouter(
    prefix="/anon_requests",
    tags=["anon_requests"],
    responses={404: {"description": "Not found"}},
)


@router.get("/{task_id}")
def status(task_id: str = ""):
    task = AsyncResult(task_id)
    return JSONResponse(
        {
            "task_id": task_id,
            "status": task.status,
            "result": (
                str(task.result) if isinstance(task.result, Exception) else task.result
            ),
        }
    )


@router.post("/zip_rocrate/")
def zip_rocrate(
    parsed_zipfile: (Dict, bytes) = Depends(parse_zipfile),
    request: Request = None,
):
    task = vre_from_zipfile.apply_async(args=[parsed_zipfile, "placeholder"])
    return JSONResponse({"task_id": task.id})


@router.post("/metadata_rocrate/")
def metadata_rocrate(
    data: Dict = Depends(parse_rocrate),
    request: Request = None,
):
    task = vre_from_rocrate.apply_async(args=[data, "placeholder"])

    return JSONResponse({"task_id": task.id})
