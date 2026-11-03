from types import SimpleNamespace

from maya_sawa.core.security import SecurityMiddleware


def _request(peer: str, headers: dict[str, str]):
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers=headers,
    )


def test_forwarded_ip_is_used_only_for_trusted_proxy():
    middleware = object.__new__(SecurityMiddleware)
    middleware.trusted_proxies = []

    request = _request("203.0.113.10", {"x-forwarded-for": "198.51.100.9"})
    assert middleware._client_ip(request) == "203.0.113.10"


def test_forwarded_ip_is_used_for_private_proxy():
    middleware = object.__new__(SecurityMiddleware)
    middleware.trusted_proxies = [
        __import__("ipaddress").ip_network("10.0.0.0/8"),
    ]

    request = _request("10.0.0.20", {"x-forwarded-for": "198.51.100.9, 10.0.0.20"})
    assert middleware._client_ip(request) == "198.51.100.9"
