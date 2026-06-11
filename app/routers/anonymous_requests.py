"""
Request router for anonymous (unauthenticated) VRE requests.
"""

from typing import Dict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi import Body, Depends, Request
from .utils import parse_zipfile
from celery.result import AsyncResult
from app.celery.tasks import vre_from_zipfile, vre_from_rocrate
import logging

from app.celery.tasks import vre_from_zipfile, vre_from_rocrate
from celery.result import AsyncResult

from .utils import parse_zipfile

logger = logging.getLogger(__name__)

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
    parsed_zipfile: tuple[Dict, dict[str, bytes]] = Depends(parse_zipfile),
    request: Request = None,
):
    task = vre_from_zipfile.apply_async(args=[parsed_zipfile, ""])
    logger.info(f"Task created: {task.id}")
    return JSONResponse({"task_id": task.id})


@router.post("/metadata_rocrate/")
def metadata_rocrate(
    data: Dict = Body(...),
    request: Request = None,
):
    task = vre_from_rocrate.apply_async(args=[data, ""])
    logger.info(f"Task created: {task.id}")
    return JSONResponse({"task_id": task.id})
