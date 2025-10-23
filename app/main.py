from app.routers import requests
from app.routers import auth
from fastapi import FastAPI
from typing import Annotated
from fastapi_oauth2.middleware import OAuth2Middleware
from fastapi_oauth2.router import router as oauth2_router
from fastapi_oauth2.config import OAuth2Config
from fastapi_oauth2.client import OAuth2Client
from fastapi_oauth2.claims import Claims
from social_core.backends.egi_checkin import EGICheckinOpenIdConnect
from fastapi.responses import JSONResponse
import ssl
from app.config import settings
from app.exceptions import GalaxyAPIError

app = FastAPI()
app.include_router(oauth2_router)
app.include_router(requests.router)
app.include_router(auth.router)

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ssl_context.load_cert_chain(settings.cert_chain_file, keyfile=settings.private_key_file)


class TestEGICheckinOpenIdConnect(EGICheckinOpenIdConnect):
    CHECKIN_ENV = settings.egi_checkin_env


client = OAuth2Client(
    backend=TestEGICheckinOpenIdConnect,
    scope=[
        "openid email profile entitlements voperson_id voperson_external_affiliation eduperson_entitlement"
    ],
    client_id=settings.client_id,
    client_secret=settings.client_secret,
    redirect_uri=settings.redirect_uri,
    claims=Claims(
        identity=lambda user: f"{user.provider}:{user.id}",
    ),
)

app.add_middleware(OAuth2Middleware, config=OAuth2Config(clients=[client]))


@app.get("/")
async def root():
    return {"message": "API running"}
