"""
Request router for anonymous (unauthenticated) VRE requests.

Anonymous flows are persisted with ``owner=NULL`` — the task_id acts as a
bearer credential and anonymous records never appear in listings.
"""

import logging
from typing import Dict

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

from .utils import parse_zipfile
from .utils.dispatch import (
    delete_flow,
    dispatch_flow,
    get_owned_record,
    public_record,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/anon_requests",
    tags=["anon_requests"],
    responses={404: {"description": "Not found"}},
)


@router.get("/{task_id}")
async def status(request: Request, task_id: str):
    """Task status; 404 unknown id, 403 when the record is owner-bound."""
    record = await get_owned_record(request, token="", task_id=task_id)
    return JSONResponse(public_record(record))


@router.delete("/{task_id}")
async def destroy(request: Request, task_id: str):
    """Cancel/destroy an anonymous flow (bearer task_id semantics)."""
    body = await delete_flow(request, token="", task_id=task_id)
    return JSONResponse(body)


@router.post("/zip_rocrate/", status_code=202)
async def zip_rocrate(
    request: Request,
    parsed_zipfile: tuple[Dict, dict[str, bytes]] = Depends(parse_zipfile),
):
    crate, file_bytes_map = parsed_zipfile
    task_id = await dispatch_flow(
        request, token="", crate=crate, file_bytes_map=file_bytes_map, anonymous=True
    )
    return JSONResponse({"task_id": task_id}, status_code=202)


@router.post("/metadata_rocrate/", status_code=202)
async def metadata_rocrate(request: Request, data: Dict = Body(...)):
    task_id = await dispatch_flow(
        request, token="", crate=data, file_bytes_map=None, anonymous=True
    )
    return JSONResponse({"task_id": task_id}, status_code=202)
