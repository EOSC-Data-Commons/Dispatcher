import json
import logging
from typing import Dict

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException
from rocrate.rocrate import ROCrate

from .utils import parse_zipfile, parse_rocrate, oauth2_scheme, MinimalVRERequest
from celery.result import AsyncResult
from app.celery.tasks import vre_from_zipfile, vre_from_rocrate, vre_from_minimal
from app.domain.rocrate.builder import RocrateBuilder

logger = logging.getLogger("uvicorn.error")


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
    parsed_data: str = Form(..., description="JSON string of MinimalVRERequest"),
    token: str = Depends(oauth2_scheme),
    uploaded_files: list[UploadFile] = File(default_factory=list),
    request: Request = None,
):
    data = json.loads(parsed_data)
    validated = MinimalVRERequest.model_validate(data)
    file_bytes_map = {}
    for f in uploaded_files:
        content = f.file.read()
        file_bytes_map[f.filename or "unknown"] = content
    task = vre_from_minimal.apply_async(
        args=[
            validated.model_dump(mode="json"),
            file_bytes_map,
            request.auth.provider.access_token,
        ]
    )
    return JSONResponse({"task_id": task.id})


@router.post("/minimal_to_rocrate/")
def minimal_to_rocrate(
    parsed_data: MinimalVRERequest,
    token: str = Depends(oauth2_scheme),
):
    rocrate_json = RocrateBuilder.build_from_minimal(
        parsed_data.model_dump(mode="json")
    )
    return JSONResponse(rocrate_json)
