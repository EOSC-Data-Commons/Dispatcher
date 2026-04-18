import os
from typing import Optional
from app.routers import requests, auth, anonymous_requests
from fastapi import FastAPI
from fastapi_oauth2.middleware import OAuth2Middleware
from fastapi_oauth2.router import router as oauth2_router
from fastapi_oauth2.config import OAuth2Config
from fastapi_oauth2.client import OAuth2Client
from fastapi_oauth2.claims import Claims
from social_core.backends.egi_checkin import EGICheckinOpenIdConnect
import ssl
from app.config import settings

app = FastAPI()
app.include_router(oauth2_router)
app.include_router(requests.router)
app.include_router(auth.router)
app.include_router(anonymous_requests.router)

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ssl_context.load_cert_chain(settings.cert_chain_file, keyfile=settings.private_key_file)


class TestEGICheckinOpenIdConnect(EGICheckinOpenIdConnect):
    CHECKIN_ENV = settings.egi_checkin_env


class DummyOAuth2Client(OAuth2Client):
    async def authenticate(self, code: Optional[str] = None, **kwargs):
        return {
            "id": "dummy-user",
            "email": "dev@example.com",
            "name": "Dev User",
            "picture": None,
        }


def get_oauth2_client() -> OAuth2Client:
    if os.getenv("ENV") == "development":
        return DummyOAuth2Client(
            backend=TestEGICheckinOpenIdConnect, client_id="", client_secret=""
        )
    return OAuth2Client(
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


app.add_middleware(
    OAuth2Middleware,
    config=OAuth2Config(clients=[get_oauth2_client()], same_site="none"),
)
