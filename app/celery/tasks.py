from .worker import celery
from app.vres.base_vre import vre_factory
from rocrate.rocrate import ROCrate
from fastapi import UploadFile
from app.exceptions import GalaxyAPIError
from typing import Dict
import copy


@celery.task(
    name="vre_from_zipfile",
    bind=True,
)
def vre_from_zipfile(self, parsed_zipfile: tuple[Dict, bytes], token):
    crate = ROCrate(source=copy.deepcopy(parsed_zipfile[0]))
    zip_file = parsed_zipfile[1]
    vre_handler = vre_factory(
        crate=crate, body=zip_file, token=token, update_state=self.update_state
    )
    return {"url": vre_handler.post()}


@celery.task(
    name="vre_from_rocrate",
    autoretry_for=(GalaxyAPIError,),
    retry_backoff=True,
    max_retries=3,
    bind=True,
)
def vre_from_rocrate(self, data: Dict, token):
    crate = ROCrate(source=copy.deepcopy(data))
    vre_handler = vre_factory(crate=crate, token=token, update_state=self.update_state)
    return {"url": vre_handler.post()}
