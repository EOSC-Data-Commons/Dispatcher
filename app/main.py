from fastapi import FastAPI, Request
from .views import post_request
from pydantic import BaseModel, BaseConfig

app = FastAPI()
BaseConfig.arbitrary_types_allowed = True

class Item(BaseModel):
    name: str

@app.post("/requests/")
async def post(request: Request):
    return await post_request(request)


@app.post("/test/")
async def test(request: Request):
    return await request.json()
