from .worker import celery
from app.vres.base_vre import vre_factory
from app.domain.rocrate.parser import ROCrateParser
from app.domain.rocrate.builder import RequestPackageBuilder
from app.domain.rocrate.request_package import RequestPackage
from app.exceptions import GalaxyAPIError
from typing import Dict
import copy
import app.constants as constants


@celery.task(
    name="vre_from_zipfile",
    bind=True,
)
def vre_from_zipfile(self, parsed_zipfile: tuple[Dict, bytes], token):
    rocrate_dict = copy.deepcopy(parsed_zipfile[0])
    parsed_crate = ROCrateParser.parse(rocrate_dict)
    package = RequestPackageBuilder.build(parsed_crate)
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


@celery.task(
    name="vre_from_minimal",
    autoretry_for=(GalaxyAPIError,),
    retry_backoff=True,
    max_retries=3,
    bind=True,
)
def vre_from_minimal(self, data: dict, file_bytes_map: dict[str, bytes], token: str):
    vre_type = data["vre_type"]
    lang_map = {
        "galaxy": constants.GALAXY_PROGRAMMING_LANGUAGE,
        "oscar": constants.OSCAR_PROGRAMMING_LANGUAGE,
        "scipion": constants.SCIPION_PROGRAMMING_LANGUAGE,
        "binder": constants.BINDER_PROGRAMMING_LANGUAGE,
        "jupyter": constants.JUPYTER_PROGRAMMING_LANGUAGE,
    }
    programming_language = lang_map[vre_type]
    workflow_url = str(data["workflow_url"]) if data.get("workflow_url") else None
    runtime_platform = (
        str(data["runtime_platform"]) if data.get("runtime_platform") else None
    )

    package = RequestPackage.from_minimal(
        vre_type=vre_type,
        programming_language=programming_language,
        workflow_url=workflow_url,
        files_data=data.get("files", []),
        file_bytes_map=file_bytes_map,
        runtime_platform=runtime_platform,
    )
    vre_handler = vre_factory(
        token=token,
        request_id=self.request.id,
        update_state=self.update_state,
        request_package=package,
    )
    return {"url": vre_handler.post()}
