"""RSA JWT helpers for local verification tests — no network.

Builds real RS256 tokens against a locally generated key and patches
``app.security._jwks`` so ``verify()`` resolves the key offline.
"""

import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

DEV_ISSUER = "https://aai-dev.egi.eu/auth/realms/egi"

_SUB = "58249f7b3a5d393eb990b09960c0725d28186c9fcc28f7b876897a4023a27728@egi.eu"


def generate_rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def private_pem(key) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


class _SigningKey:
    """Duck-typed PyJWK: PyJWT only needs ``.key``."""

    def __init__(self, key):
        self.key = key.public_key()


class FakeJWKS:
    """Duck-typed PyJWKClient resolving every token to the local key."""

    def __init__(self, key):
        self._signing_key = _SigningKey(key)

    def get_signing_key_from_jwt(self, token):
        return self._signing_key


def make_token(key, claims_over=None, issuer=DEV_ISSUER, lifetime=3600, drop=()):
    """A Check-in-shaped RS256 token signed by *key*.

    ``claims_over`` merges over the defaults; ``drop`` removes claims
    (for the required-claim negative tests).
    """
    now = int(time.time())
    claims = {
        "exp": now + lifetime,
        "iat": now,
        "iss": issuer,
        "sub": _SUB,
        "scope": "openid profile email offline_access",
        "voperson_id": _SUB,
        "preferred_username": _SUB,
    }
    claims.update(claims_over or {})
    for name in drop:
        claims.pop(name, None)
    return jwt.encode(claims, private_pem(key), algorithm="RS256")


def patch_jwks(monkeypatch, key):
    """Point ``app.security.verify`` at the local key."""
    from app import security

    monkeypatch.setattr(security, "_jwks", lambda: FakeJWKS(key))
