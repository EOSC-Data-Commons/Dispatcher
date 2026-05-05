"""
Request router for authenticated VRE requests.
"""

from typing import Dict

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import JSONResponse
from rocrate.rocrate import ROCrate

from app.logging_config import get_logger
from app.celery.tasks import vre_from_zipfile, vre_from_rocrate
from celery.result import AsyncResult

from .utils import oauth2_scheme, parse_zipfile, parse_rocrate

logger = get_logger(__name__)

router = APIRouter(
    prefix="/requests",
    tags=["requests"],
    responses={404: {"description": "Not found"}},
)


@router.get("/{task_id}")
def status(token: str = Depends(oauth2_scheme), task_id: str = ""):
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
    token: str = Depends(oauth2_scheme),
    parsed_zipfile: (Dict, bytes) = Depends(parse_zipfile),
    request: Request = None,
):
    task = vre_from_zipfile.apply_async(
        args=[parsed_zipfile, request.auth.provider.access_token]
    )
    logger.info(f"Task created: {task.id}")
    return JSONResponse({"task_id": task.id})


@router.post("/metadata_rocrate/")
def metadata_rocrate(
    token: str = Depends(oauth2_scheme),
    data: Dict = Depends(parse_rocrate),
    request: Request = None,
):
    task = vre_from_rocrate.apply_async(args=[data, request.auth.provider.access_token])
    logger.info(f"Task created: {task.id}")
    return JSONResponse({"task_id": task.id})
