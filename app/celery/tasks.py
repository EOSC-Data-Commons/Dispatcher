from .worker import celery
from app.vres.base_vre import vre_factory
from rocrate.rocrate import ROCrate
from fastapi import UploadFile
from app.exceptions import GalaxyAPIError
from typing import Dict
import copy
from celery.exceptions import TaskError

@celery.task(name="vre_from_zipfile")
def vre_from_zipfile(parsed_zipfile: (ROCrate, UploadFile), token):
    vre_handler = vre_factory(*parsed_zipfile, token=token)
    return {"url": vre_handler.post()}


@celery.task(name="vre_from_rocrate", bind=True, autoretry_for=(GalaxyAPIError,), retry_backoff=True, max_retries=3)
def vre_from_rocrate(self, data: Dict, token):
    try:
        crate = ROCrate(source=copy.deepcopy(data))
        vre_handler = vre_factory(crate=crate, token=token)
        return {"url": vre_handler.post()}
    except Exception as e:
        raise self.retry(countdown=5, exc=e)
