"""User identity from EGI Check-in access tokens.

Check-in access tokens are standard RS256 JWTs (validated against a live
token, 2026-10-27): identity is verified and read from the token claims
locally via :mod:`app.security` — no userinfo round-trip per call.

See ``plans/Auth Design 1 — Dispatcher validation.md``.
"""

from dataclasses import dataclass
import logging

import jwt as pyjwt

from app import security
from app.exceptions import VREAuthenticationError

logger = logging.getLogger(__name__)


@dataclass
class TokenUser:
    email: str
    name: str | None


def extract_user_from_token(access_token: str) -> TokenUser:
    """Resolve the user behind *access_token* by verifying it locally.

    Raises :class:`VREAuthenticationError` when the token is invalid,
    expired, or from the wrong issuer.
    """
    try:
        claims = security.verify(access_token)
    except pyjwt.PyJWTError as e:
        logger.error("Access token rejected by local verification: %s", e)
        raise VREAuthenticationError(
            "Failed to fetch user identity from EGI Check-in"
        ) from e

    # verify() requires the "sub" claim, so it is always present here.
    email = claims["sub"]
    name = claims.get("preferred_username")

    logger.debug(f"Extracted user from token: email={email}, name={name}")
    return TokenUser(email=email, name=name)
