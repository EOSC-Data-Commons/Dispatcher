from fastapi import FastAPI
from app.routers import requests

app = FastAPI()
app.include_router(requests.router)


@app.get("/")
async def root():
    return {"message": "API running"}
