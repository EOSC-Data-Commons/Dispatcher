from fastapi import FastAPI
from app.routers import requests
from app.internal.galaxy import VREGalaxy
from app.internal.binder import VREBinder

import app.internal.config as config

app = FastAPI()
app.include_router(requests.router)


@app.get("/")
async def root():
    return {"message": "API running"}


@app.get("/config")
def read_config():
    return config.config
