import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from maya_sawa.core.auth import keycloak


REQUEST = SimpleNamespace(headers={"authorization": "Bearer fixture"})


def stub_auth(monkeypatch, roles, realm_roles, downstream_status):
    async def authenticated(_request):
        return {"_roles": roles, "realm_access": {"roles": realm_roles}}

    def verify_role(request):
        assert request.url.path.endswith("/palais-access/verify-read")
        assert request.headers["authorization"] == "Bearer fixture"
        return httpx.Response(downstream_status)

    client_factory = httpx.AsyncClient
    monkeypatch.setattr(keycloak, "require_authenticated", authenticated)
    monkeypatch.setattr(keycloak.httpx, "AsyncClient",
                        lambda **options: client_factory(transport=httpx.MockTransport(verify_role), **options))


@pytest.mark.parametrize("roles, realm_roles, downstream_status, denied", [
    (["palais-checker"], ["palais-checker"], 204, None),
    (["manage-users"], [], 503, None),
    (["palais-checker"], [], 204, 403),
    (["palais-checker"], ["palais-checker"], 403, 403),
    (["palais-checker"], ["palais-checker"], 503, 503),
    ([], [], 204, 403),
])
def test_palais_reader_role(monkeypatch, roles, realm_roles, downstream_status, denied):
    stub_auth(monkeypatch, roles, realm_roles, downstream_status)
    if denied is None:
        assert asyncio.run(keycloak.require_palais_reader(REQUEST))["_roles"] == roles
    else:
        with pytest.raises(HTTPException) as error:
            asyncio.run(keycloak.require_palais_reader(REQUEST))
        assert error.value.status_code == denied


def test_checker_cannot_use_management_dependency(monkeypatch):
    stub_auth(monkeypatch, ["palais-checker"], ["palais-checker"], 204)
    with pytest.raises(HTTPException) as error:
        asyncio.run(keycloak.require_manage_users_request(REQUEST))
    assert error.value.status_code == 403
