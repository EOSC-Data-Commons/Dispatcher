import logging
from typing import Annotated, Dict

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse

from app.security import oauth2_scheme

from .utils import parse_zipfile
from .utils.dispatch import (
    delete_flow,
    dispatch_flow,
    get_owned_record,
    get_store,
    caller_identity,
    public_record,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/requests",
    tags=["requests"],
    responses={404: {"description": "Not found"}},
)


@router.get("/")
async def list_tasks(request: Request, token: Annotated[str, Depends(oauth2_scheme)]):
    """Caller-owned listing (indexed WHERE sub = ?); anonymous records are
    excluded (they are reachable only by bearer task_id)."""
    sub, _ = caller_identity(token)
    if sub is None:
        return JSONResponse([])
    store = get_store(request)
    records = await store.list_by_sub(sub)
    return JSONResponse([public_record(record) for record in records])


@router.get("/{task_id}")
async def status(
    request: Request,
    task_id: str,
    token: Annotated[str, Depends(oauth2_scheme)],
):
    """Task status; 404 unknown id, 403 on owner mismatch."""
    record = await get_owned_record(request, token, task_id)
    return JSONResponse(public_record(record))


@router.delete("/{task_id}")
async def destroy(
    request: Request,
    task_id: str,
    token: Annotated[str, Depends(oauth2_scheme)],
):
    """Cancel the flow and/or tear down delivered infra (owner-enforced)."""
    body = await delete_flow(request, token, task_id)
    return JSONResponse(body)


@router.post("/zip_rocrate/", status_code=202)
async def zip_rocrate(
    request: Request,
    token: Annotated[str, Depends(oauth2_scheme)],
    parsed_zipfile: Annotated[tuple[Dict, dict[str, bytes]], Depends(parse_zipfile)],
):
    crate, file_bytes_map = parsed_zipfile
    task_id = await dispatch_flow(
        request, token, crate=crate, file_bytes_map=file_bytes_map
    )
    return JSONResponse({"task_id": task_id}, status_code=202)


@router.post("/metadata_rocrate/", status_code=202)
async def metadata_rocrate(
    request: Request,
    token: Annotated[str, Depends(oauth2_scheme)],
    data: Dict = Body(...),
):
    task_id = await dispatch_flow(request, token, crate=data, file_bytes_map=None)
    return JSONResponse({"task_id": task_id}, status_code=202)
