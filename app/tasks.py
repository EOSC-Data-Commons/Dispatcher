from app.worker import celery
from app.internal.vre import vre_factory
from rocrate.rocrate import ROCrate
from fastapi import UploadFile, Depends
from app.internal.galaxy import VREGalaxy
from app.internal.binder import VREBinder
from fastapi.exceptions import HTTPException


@celery.task(name="galaxy_from_zipfile")
def galaxy_from_zipfile(parsed_zipfile: (ROCrate, UploadFile), token):
    vre_handler = vre_factory(*parsed_zipfile, token=token)
    return {"url": vre_handler.post()}

@celery.task(name="galaxy_from_rocrate")
def galaxy_from_rocrate(data, token):
    vre_handler = vre_factory(crate=data, token=token)
    return {"url": vre_handler.post()}