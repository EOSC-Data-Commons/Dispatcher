from fastapi import FastAPI
from app.routers import requests
import app.internal.config as config
from fastapi.security.open_id_connect_url import OpenIdConnect
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException
from fastapi import Request
from fastapi import Depends
from fastapi import status
import string
import random
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
from typing import Annotated
from fastapi_oauth2.middleware import OAuth2Middleware
from fastapi_oauth2.router import router as oauth2_router
from fastapi_oauth2.config import OAuth2Config
from fastapi_oauth2.client import OAuth2Client
from fastapi_oauth2.claims import Claims
from social_core.backends.egi_checkin import EGICheckinOpenIdConnect
from app.dependencies import oauth2_scheme
import ssl
import os
from fastapi.responses import RedirectResponse
import yaml

with open("./app/api-config.yml", "r") as f:
    config = yaml.safe_load(f)

app = FastAPI()
app.include_router(oauth2_router)
app.include_router(requests.router)

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ssl_context.load_cert_chain(config['CERT_CHAIN_FILE'], keyfile=config['PRIVATE_KEY_FILE'])

class TestEGICheckinOpenIdConnect(EGICheckinOpenIdConnect):
    CHECKIN_ENV = config['EGI_CHECKIN_ENV']

client = OAuth2Client(
    backend=TestEGICheckinOpenIdConnect,
    scope=["openid email"],
    client_id=config["CLIENT_ID"],
    client_secret=config["CLIENT_SECRET"],
    redirect_uri=config["REDIRECT_URI"],
    claims=Claims(
        identity=lambda user: f"{user.provider}:{user.id}",
    )
)

app.add_middleware(OAuth2Middleware, config=OAuth2Config(clients=[client]))

@app.get("/")
async def root():
    return {"message": "API running"}

@app.get("/config")
def read_config():
    return config.config

@app.get("/oauth2/login")
async def test(request: Request):
    print(request)
    return RedirectResponse("/oauth2/egi-checkin/authorize")


@app.get("/oauth2/token")
async def get_token(token: Annotated[str, Depends(oauth2_scheme)]):
    return {"token": token}
