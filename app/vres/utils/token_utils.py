"""Utilities for extracting user identity from EGI Check-in access tokens.

The access tokens issued by EGI Check-in are opaque — they do not contain
user claims in the JWT payload.  Instead we call the federation-backend
userinfo endpoint with the token as a Bearer.
"""

from dataclasses import dataclass
import logging

import requests

from app.config import settings
from app.exceptions import VREAuthenticationError

logger = logging.getLogger(__name__)

# Federation-backend userinfo URLs keyed by the egi_checkin_env setting.
_CHECKIN_USERINFO_URLS = {
    "prod": "https://aai.egi.eu/auth/realms/egi/protocol/openid-connect/userinfo",
    "demo": "https://aai-demo.egi.eu/auth/realms/egi/protocol/openid-connect/userinfo",
    "dev": "https://aai-dev.egi.eu/auth/realms/egi/protocol/openid-connect/userinfo",
}


@dataclass
class TokenUser:
    email: str
    name: str | None


def extract_user_from_token(access_token: str) -> TokenUser:
    """Resolve the user identity behind *access_token* via the EGI Check-in
    federation backend.

    Raises :class:`VREAuthenticationError` when the call fails or the
    response does not contain a non-empty ``sub`` field.
    """
    userinfo_url = _CHECKIN_USERINFO_URLS.get(settings.egi_checkin_env)

    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = requests.get(userinfo_url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch userinfo from EGI Check-in: {e}")
        raise VREAuthenticationError(
            "Failed to fetch user identity from EGI Check-in"
        ) from e

    email = data.get("sub")
    if not email:
        logger.error("EGI Check-in userinfo response missing 'sub' field")
        raise VREAuthenticationError("Missing 'sub' in user identity from EGI Check-in")

    name = data.get("preferred_username")

    logger.debug(f"Extracted user from token: email={email}, name={name}")
    return TokenUser(email=email, name=name)
