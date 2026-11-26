import pytest
import requests

from app.exceptions import OCMSigningKeyError
from app.vres.utils.http_signature import (
    OCMSignatureAuth,
    load_signing_key,
    public_jwk,
)

# The kid and x of the RFC 8037, Appendix A key
RFC8037_KID = "kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k"
RFC8037_X = "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo"

# The request body of Appendix B of the OCM spec
APPENDIX_B_BODY = """{
  "shareWith": "marie@receiver.example.org",
  "name": "spec.yaml",
  "providerId": "7c084226-d9a1-11e6-bf26-cec0c932ce01",
  "owner": "einstein@sender.example.org",
  "sender": "einstein@sender.example.org",
  "ownerDisplayName": "Albert Einstein",
  "senderDisplayName": "Albert Einstein",
  "shareType": "user",
  "resourceType": "file",
  "protocol": {
    "name": "multi",
    "webdav": {
      "uri": "spec.yaml",
      "sharedSecret": "hfiuhworzwnur98d3wjiwhr",
      "permissions": ["read", "write"]
    }
  }
}"""


def test_public_jwk_has_rfc7638_thumbprint_as_kid(ocm_signing_key):
    assert public_jwk(ocm_signing_key) == {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": RFC8037_X,
        "kid": RFC8037_KID,
        "alg": "Ed25519",
    }


def test_signs_appendix_b_request(ocm_signing_key, appendix_b_clock):
    request = requests.Request(
        "POST",
        "https://receiver.example.org/ocm/shares",
        data=APPENDIX_B_BODY.encode(),
        auth=OCMSignatureAuth(ocm_signing_key),
    ).prepare()

    assert (
        request.headers["Content-Digest"]
        == "sha-256=:/Uz47cfD1HOdMTIqcWjd84iMLQ4gVJdC7ZFACf1ViqU=:"
    )
    assert request.headers["Content-Length"] == "521"
    # Appendix B with the keyid of this key
    assert request.headers["Signature-Input"] == (
        'sig1=("@method" "@target-uri" "content-digest" "content-length")'
        f';created=1785060500;keyid="{RFC8037_KID}";alg="ed25519";tag="ocm"'
    )
    # openssl pkeyutl -sign -rawin of the Appendix B signature base with this keyid
    assert request.headers["Signature"] == (
        "sig1=:fApI+fFjQdRPvfMSPcwVyGfJhx68xabH5U9zxUwVeH5AgWVNwhHfyszoeCj4HMnqV9HbIU/zWXUDM+iCU66CDg==:"
    )


def test_load_signing_key_raises_for_missing_file(tmp_path):
    with pytest.raises(OCMSigningKeyError):
        load_signing_key(str(tmp_path / "missing.pem"))


def test_jwks_publishes_public_signing_key(ocm_signing_key, wellknown_client):
    response = wellknown_client.get("/.well-known/jwks.json")

    assert response.status_code == 200
    assert response.json() == {
        "keys": [
            {
                "kty": "OKP",
                "crv": "Ed25519",
                "x": RFC8037_X,
                "kid": RFC8037_KID,
                "alg": "Ed25519",
            }
        ]
    }
