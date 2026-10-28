"""OCM HTTP Message Signatures (RFC 9421), as the OCM spec profiles them."""

import base64
import hashlib
import json
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from requests import PreparedRequest
from requests.auth import AuthBase

from app.constants import OCM_SIGNATURE_TAG
from app.exceptions import OCMSigningKeyError


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def load_signing_key(path: str) -> Ed25519PrivateKey:
    """Read an Ed25519 private key from a PEM file, such as the output of
    `openssl genpkey -algorithm ed25519`."""
    try:
        with open(path, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
    except (OSError, ValueError, TypeError) as e:
        raise OCMSigningKeyError(f"Cannot load the OCM signing key {path!r}") from e
    if not isinstance(key, Ed25519PrivateKey):
        raise OCMSigningKeyError(f"The OCM signing key {path!r} is not an Ed25519 key")
    return key


def public_jwk(key: Ed25519PrivateKey) -> dict:
    """The public part of key as a JWK (RFC 8037). The kid is the RFC 7638
    thumbprint, thus a new key gets a new kid without a config change."""
    x = _b64url(
        key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    )
    # RFC 7638 hashes only the required members, sorted and without whitespace.
    required = json.dumps(
        {"crv": "Ed25519", "kty": "OKP", "x": x}, separators=(",", ":"), sort_keys=True
    )
    kid = _b64url(hashlib.sha256(required.encode()).digest())
    return {"kty": "OKP", "crv": "Ed25519", "x": x, "kid": kid, "alg": "Ed25519"}


class OCMSignatureAuth(AuthBase):
    """Signs a request with the components and parameters that the OCM spec requires.

    requests calls it after it encodes the body, thus the signature covers the bytes that are sent.
    """

    def __init__(self, key: Ed25519PrivateKey):
        self.key = key

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        digest = base64.b64encode(hashlib.sha256(request.body).digest()).decode()
        request.headers["Content-Digest"] = f"sha-256=:{digest}:"
        covered = {
            "@method": request.method,
            "@target-uri": request.url,
            "content-digest": request.headers["Content-Digest"],
            "content-length": request.headers["Content-Length"],
        }
        params = (
            "(" + " ".join(f'"{name}"' for name in covered) + ")"
            f";created={int(time.time())}"
            f';keyid="{public_jwk(self.key)["kid"]}"'
            f';alg="ed25519";tag="{OCM_SIGNATURE_TAG}"'
        )
        base = "".join(f'"{name}": {value}\n' for name, value in covered.items())
        base += f'"@signature-params": {params}'
        signature = base64.b64encode(self.key.sign(base.encode())).decode()
        request.headers["Signature-Input"] = f"sig1={params}"
        request.headers["Signature"] = f"sig1=:{signature}:"
        return request
