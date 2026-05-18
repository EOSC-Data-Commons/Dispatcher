from fastapi import APIRouter
from fastapi.responses import JSONResponse
from fastapi import UploadFile, Depends, Request, Form, File
from rocrate.rocrate import ROCrate
from fastapi.exceptions import HTTPException
from .utils import parse_zipfile, parse_rocrate
from .utils.minimal_vre import MinimalVRERequest
from celery.result import AsyncResult
from app.celery.tasks import vre_from_zipfile, vre_from_rocrate, vre_from_minimal
import logging
import json
from typing import Dict

logger = logging.getLogger("uvicorn.error")

from .utils import oauth2_scheme

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
    parsed_zipfile: tuple[Dict, dict[str, bytes]] = Depends(parse_zipfile),
    request: Request = None,
):
    task = vre_from_zipfile.apply_async(
        args=[parsed_zipfile, request.auth.provider.access_token]
    )
    return JSONResponse({"task_id": task.id})


@router.post("/metadata_rocrate/")
def metadata_rocrate(
    token: str = Depends(oauth2_scheme),
    data: Dict = Depends(parse_rocrate),
    request: Request = None,
):
    task = vre_from_rocrate.apply_async(args=[data, request.auth.provider.access_token])

    return JSONResponse({"task_id": task.id})


@router.post("/minimal_vre/")
def minimal_vre(
    token: str = Depends(oauth2_scheme),
    data: str = Form(..., description="JSON string of MinimalVRERequest"),
    uploaded_files: list[UploadFile] = File(default_factory=list),
    request: Request = None,
):
    parsed_data = MinimalVRERequest(**json.loads(data))
    file_bytes_map = {}
    for f in uploaded_files:
        content = f.file.read()
        file_bytes_map[f.filename or "unknown"] = content
    task = vre_from_minimal.apply_async(
        args=[
            parsed_data.model_dump(mode="json"),
            file_bytes_map,
            request.auth.provider.access_token,
        ]
    )
    return JSONResponse({"task_id": task.id})
