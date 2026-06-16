from .worker import celery
from app.vres.base_vre import vre_factory
from vre_rocrate import RequestPackageBuilder
from app.exceptions import GalaxyAPIError, VREAuthenticationError
from app.services.secrets import SecretStore
from typing import Callable, Dict, Optional, Tuple
import copy


def _resolve_api_key(
    secret_ref: Optional[str],
) -> Tuple[Optional[str], Callable[[], None]]:
    """Read the API key referenced by *secret_ref*, returning it and a
    cleanup callable that should be invoked only after a successful
    ``post()``.

    The secret is *not* consumed during resolution so that Celery
    auto‑retries can re‑read it.  The returned *cleanup* callable
    performs the one‑time delete.
    """
    if secret_ref is None:
        return None, lambda: None
    store = SecretStore()
    api_key = store.get(secret_ref)
    if api_key is None:
        raise VREAuthenticationError(
            f"API key reference '{secret_ref}' not found in secret store " "(expired)"
        )
    return api_key, lambda: store.delete(secret_ref)


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
    api_key, cleanup = _resolve_api_key(secret_ref)
    vre_handler = vre_factory(
        token=token,
        request_id=self.request.id,
        update_state=self.update_state,
        request_package=package,
        api_key=api_key,
    )
    result = vre_handler.post()
    cleanup()
    return {"url": result}


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
    api_key, cleanup = _resolve_api_key(secret_ref)
    vre_handler = vre_factory(
        token=token,
        request_id=self.request.id,
        update_state=self.update_state,
        request_package=package,
        api_key=api_key,
    )
    result = vre_handler.post()
    cleanup()
    return {"url": result}
