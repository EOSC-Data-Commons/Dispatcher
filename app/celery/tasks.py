from .worker import celery
from app.vres.base_vre import vre_factory
from vre_rocrate import ROCrateParser, RequestPackageBuilder
from app.exceptions import GalaxyAPIError
from typing import Dict
import copy


@celery.task(
    name="vre_from_zipfile",
    bind=True,
)
def vre_from_zipfile(self, parsed_zipfile: tuple[Dict, dict[str, bytes]], token):
    rocrate_dict = copy.deepcopy(parsed_zipfile[0])
    file_bytes_map = parsed_zipfile[1]
    parsed_crate = ROCrateParser.parse(rocrate_dict)
    package = RequestPackageBuilder.build(parsed_crate, file_bytes_map)
    vre_handler = vre_factory(
        token=token,
        request_id=self.request.id,
        update_state=self.update_state,
        request_package=package,
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
    rocrate_dict = copy.deepcopy(data)
    parsed_crate = ROCrateParser.parse(rocrate_dict)
    package = RequestPackageBuilder.build(parsed_crate)
    vre_handler = vre_factory(
        token=token,
        request_id=self.request.id,
        update_state=self.update_state,
        request_package=package,
    )
    return {"url": vre_handler.post()}
