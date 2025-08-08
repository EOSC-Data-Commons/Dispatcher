from .worker import celery
from app.vres.base_vre import vre_factory
from rocrate.rocrate import ROCrate
from fastapi import UploadFile


@celery.task(name="vre_from_zipfile")
def vre_from_zipfile(parsed_zipfile: (ROCrate, UploadFile), token):
    vre_handler = vre_factory(*parsed_zipfile, token=token)
    return {"url": vre_handler.post()}


@celery.task(name="vre_from_rocrate")
def vre_from_rocrate(data, token):
    vre_handler = vre_factory(crate=data, token=token)
    return {"url": vre_handler.post()}
