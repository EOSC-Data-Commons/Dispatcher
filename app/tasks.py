from app.worker import celery
from app.internal.vre import vre_factory
from rocrate.rocrate import ROCrate
from fastapi import UploadFile, Depends
from app.internal.galaxy import VREGalaxy
from app.internal.binder import VREBinder


@celery.task(name="galaxy_from_zipfile")
def galaxy_from_zipfile(parsed_zipfile: (ROCrate, UploadFile)):
    vre_handler = vre_factory(*parsed_zipfile)
    return {"url": vre_handler.post()}
