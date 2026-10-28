"""
Public keys that let OCM servers verify the signed requests of the Dispatcher.
"""

from fastapi import APIRouter

from app.config import settings
from app.constants import OCM_JWKS_PATH
from app.vres.utils.http_signature import load_signing_key, public_jwk

router = APIRouter(tags=["ocm"])


@router.get(OCM_JWKS_PATH)
def jwks():
    """JWK Set (RFC 7517) that ocm.json gives as jwksUri."""
    return {"keys": [public_jwk(load_signing_key(settings.ocm_signing_key_file))]}
