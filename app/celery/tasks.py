"""Celery tasks for VRE processing.

This module defines asynchronous tasks for creating VRE instances from
ROCrate data, either from ZIP files or direct metadata.
"""

from typing import Dict

from .worker import celery
from app.domain.rocrate import ROCrateFactory
from app.exceptions import GalaxyAPIError
from app.vres.base_vre import vre_factory


@celery.task(name="vre_from_zipfile", bind=True)
def vre_from_zipfile(
    self, parsed_zipfile: tuple[Dict, bytes], token: str
) -> Dict[str, str]:
    """Create a VRE from a parsed ZIP file containing a ROCrate.

    Args:
        parsed_zipfile: Tuple of (metadata_dict, zip_file_bytes).
        token: Authentication token for the VRE.

    Returns:
        Dictionary containing the result URL.
    """
    package = ROCrateFactory.create_from_source(parsed_zipfile[0])
    zip_file = parsed_zipfile[1]

    vre_handler = vre_factory(
        request_package=package,
        token=token,
        request_id=self.request.id,
        update_state=self.update_state,
        body=zip_file,
    )
    return {"url": vre_handler.post()}


@celery.task(
    name="vre_from_rocrate",
    autoretry_for=(GalaxyAPIError,),
    retry_backoff=True,
    max_retries=3,
    bind=True,
)
def vre_from_rocrate(self, data: Dict, token: str) -> Dict[str, str]:
    """Create a VRE from ROCrate metadata dictionary.

    Args:
        data: ROCrate metadata as a dictionary.
        token: Authentication token for the VRE.

    Returns:
        Dictionary containing the result URL.
    """
    package = ROCrateFactory.create_from_dict(data)

    vre_handler = vre_factory(
        request_package=package,
        token=token,
        request_id=self.request.id,
        update_state=self.update_state,
    )
    return {"url": vre_handler.post()}
