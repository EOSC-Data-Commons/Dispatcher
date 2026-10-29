"""VRE-layer identity adapter — error translation for local verification.

Check-in access tokens are standard RS256 JWTs (validated against a
live token, 2026-10-27). :func:`app.security.verify` does the work and
returns :class:`app.security.TokenUser`; this adapter only translates
its failures into the VRE domain error. ``TokenUser`` is re-exported so
VRE callers have one import site.

See ``plans/Auth Design 1 — Dispatcher validation.md``.
"""

import logging

import jwt as pyjwt

from app import security
from app.exceptions import VREAuthenticationError
from app.security import TokenUser

logger = logging.getLogger(__name__)


def extract_user_from_token(access_token: str) -> TokenUser:
    """Resolve the user behind *access_token* by verifying it locally.

    Raises :class:`VREAuthenticationError` when the token is invalid,
    expired, or from the wrong issuer.
    """
    try:
        return security.verify(access_token)
    except pyjwt.PyJWTError as e:
        logger.error("Access token rejected by local verification: %s", e)
        raise VREAuthenticationError(
            "Failed to fetch user identity from EGI Check-in"
        ) from e
