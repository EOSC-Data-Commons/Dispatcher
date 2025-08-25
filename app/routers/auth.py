from .utils import oauth2_scheme
from fastapi.responses import RedirectResponse
from fastapi import Depends, Request, APIRouter
from typing import Annotated


router = APIRouter(
    prefix="/oauth2",
    tags=["oauth2"],
    responses={404: {"description": "Not found"}},
)


@router.get("/login")
async def test(request: Request):
    print(request)
    return RedirectResponse("/oauth2/egi-checkin/authorize")


@router.get("/token")
async def get_token(token: Annotated[str, Depends(oauth2_scheme)], request: Request = None):
    return {"token": request.auth.provider.access_token}
