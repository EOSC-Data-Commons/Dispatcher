from .worker import celery
from app.vres.base_vre import vre_factory
from vre_rocrate import RequestPackageBuilder
from app.exceptions import GalaxyAPIError
from app.services.secrets import SecretStore
from typing import Dict, Optional
import copy


def _resolve_api_key(secret_ref: Optional[str]) -> Optional[str]:
    """Resolve an opaque reference to the actual API key via SecretStore.

    Returns ``None`` when *secret_ref* is ``None`` (no API key was
    provided in the original request).
    """
    if secret_ref is None:
        return None
    store = SecretStore()
    api_key = store.get_and_delete(secret_ref)
    if api_key is None:
        raise ValueError(
            f"API key reference '{secret_ref}' not found in secret store "
            "(expired or already consumed)"
        )
    return api_key


@celery.task(
    name="vre_from_zipfile",
    bind=True,
)
def vre_from_zipfile(
    self,
    parsed_zipfile: tuple[Dict, dict[str, bytes]],
    token,
    secret_ref: Optional[str] = None,
):
    rocrate_dict = copy.deepcopy(parsed_zipfile[0])
    file_bytes_map = parsed_zipfile[1]
    package = RequestPackageBuilder.build(rocrate_dict, file_bytes_map)
    api_key = _resolve_api_key(secret_ref)
    vre_handler = vre_factory(
        token=token,
        request_id=self.request.id,
        update_state=self.update_state,
        request_package=package,
        api_key=api_key,
    )
    return {"url": vre_handler.post()}


@celery.task(
    name="vre_from_rocrate",
    autoretry_for=(GalaxyAPIError,),
    retry_backoff=True,
    max_retries=3,
    bind=True,
)
def vre_from_rocrate(self, data: Dict, token, secret_ref: Optional[str] = None):
    rocrate_dict = copy.deepcopy(data)
    package = RequestPackageBuilder.build(rocrate_dict)
    api_key = _resolve_api_key(secret_ref)
    vre_handler = vre_factory(
        token=token,
        request_id=self.request.id,
        update_state=self.update_state,
        request_package=package,
        api_key=api_key,
    )
    return {"url": vre_handler.post()}
