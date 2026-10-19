import logging
from typing import Annotated, Dict

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

from .utils import parse_zipfile, oauth2_scheme
from celery.result import AsyncResult
from app.celery.tasks import vre_from_zipfile, vre_from_rocrate

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/requests",
    tags=["requests"],
    responses={404: {"description": "Not found"}},
)


@router.get("/{task_id}")
def status(token: Annotated[str, Depends(oauth2_scheme)], task_id: str = ""):
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
    token: Annotated[str, Depends(oauth2_scheme)],
    parsed_zipfile: Annotated[tuple[Dict, dict[str, bytes]], Depends(parse_zipfile)],
    request: Request = None,
):
    task = vre_from_zipfile.apply_async(
        args=[parsed_zipfile, request.auth.provider.access_token]
    )
    logger.info(f"Task created: {task.id}")
    return JSONResponse({"task_id": task.id})


@router.post("/metadata_rocrate/")
def metadata_rocrate(
    token: Annotated[str, Depends(oauth2_scheme)],
    data: Dict = Body(...),
    request: Request = None,
):
    task = vre_from_rocrate.apply_async(args=[data, request.auth.provider.access_token])
    logger.info(f"Task created: {task.id}")
    return JSONResponse({"task_id": task.id})
