"""Request router for VRE operations.

This module defines API endpoints for submitting ROCrate requests
and checking task status.
"""

import logging
from typing import Dict

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.celery.tasks import vre_from_zipfile, vre_from_rocrate
from .utils import parse_zipfile, parse_rocrate, oauth2_scheme

logger = logging.getLogger("uvicorn.error")

router = APIRouter(
    prefix="/requests",
    tags=["requests"],
    responses={404: {"description": "Not found"}},
)


@router.get("/{task_id}")
def status(
    token: str = Depends(oauth2_scheme),
    task_id: str = "",
) -> Dict[str, str]:
    """Get the status of a VRE task.

    Args:
        token: Authentication token.
        task_id: The Celery task ID to check.

    Returns:
        Dictionary containing task status and result.
    """
    task = AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": task.status,
        "result": (
            str(task.result) if isinstance(task.result, Exception) else task.result
        ),
    }


@router.post("/zip_rocrate/")
def zip_rocrate(
    token: str = Depends(oauth2_scheme),
    parsed_zipfile: tuple[Dict, bytes] = Depends(parse_zipfile),
    request: Request = None,
) -> Dict[str, str]:
    """Submit a ZIP file containing a ROCrate for VRE processing.

    Args:
        token: Authentication token.
        parsed_zipfile: Parsed ZIP file (metadata dict, bytes).
        request: FastAPI request object.

    Returns:
        Dictionary containing the Celery task ID.
    """
    task = vre_from_zipfile.apply_async(
        args=[parsed_zipfile, request.auth.provider.access_token]
    )
    return {"task_id": task.id}


@router.post("/metadata_rocrate/")
def metadata_rocrate(
    token: str = Depends(oauth2_scheme),
    data: Dict = Depends(parse_rocrate),
    request: Request = None,
) -> Dict[str, str]:
    """Submit ROCrate metadata directly for VRE processing.

    Args:
        token: Authentication token.
        data: ROCrate metadata dictionary.
        request: FastAPI request object.

    Returns:
        Dictionary containing the Celery task ID.
    """
    task = vre_from_rocrate.apply_async(args=[data, request.auth.provider.access_token])
    return {"task_id": task.id}


@router.get("/vre-requirements")
async def get_vre_requirements() -> Dict[str, dict]:
    """Return ROCrate requirements for all supported VREs.

    This endpoint provides frontend developers with structured documentation
    about what each VRE requires in the ROCrate.

    Returns:
        Dictionary mapping language identifiers to requirements dictionaries.
    """
    from app.domain.rocrate.checkers import get_all_requirements

    return get_all_requirements()
