import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import HTTPException

from maya_sawa.core.auth import keycloak

RESOURCE = 'https://example.test/publisher/mcp'


@pytest.fixture
def token(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(keycloak, '_find_key', lambda kid: {})
    monkeypatch.setattr(keycloak, '_public_key_from_jwk', lambda jwk: private.public_key())
    monkeypatch.setattr(keycloak, '_issuer', lambda: 'https://issuer.test/realm')
    monkeypatch.setattr(keycloak.Config, 'KEYCLOAK_CLIENT_ID', 'general-api')
    def encode(**changes):
        payload = {'iss': 'https://issuer.test/realm', 'exp': int(time.time()) + 600,
                   'sub': 'owner', 'aud': 'general-api', **changes}
        b64 = lambda value: base64.urlsafe_b64encode(value).decode().rstrip('=')
        unsigned = b64(json.dumps({'alg': 'RS256', 'kid': 'test'}).encode()) + '.' + b64(json.dumps(payload).encode())
        signature = private.sign(unsigned.encode(), padding.PKCS1v15(), hashes.SHA256())
        return unsigned + '.' + b64(signature)
    return encode


def test_existing_general_api_audience_behavior_is_preserved(token):
    assert keycloak._verify_rs256(token())['sub'] == 'owner'
    assert keycloak._verify_rs256(token(aud=[], azp='general-api'))['sub'] == 'owner'


@pytest.mark.parametrize('change', [{'exp': 1}, {'iss': 'https://wrong.test'}, {'aud': 'other'}])
def test_existing_token_validation_rejects_expired_wrong_issuer_and_audience(token, change):
    with pytest.raises(HTTPException):
        keycloak._verify_rs256(token(**change))


def test_publisher_token_cannot_be_used_on_general_api(token):
    with pytest.raises(HTTPException):
        keycloak._verify_rs256(token(aud=RESOURCE, azp='birch-publisher'))
    assert keycloak.verify_resource_bearer_token(token(aud=RESOURCE), RESOURCE)['sub'] == 'owner'


def test_resource_requires_actual_audience_and_expiration(token):
    for claims in [{'aud': [], 'azp': RESOURCE}, {'aud': RESOURCE, 'exp': None}]:
        with pytest.raises(HTTPException):
            keycloak.verify_resource_bearer_token(token(**claims), RESOURCE)
