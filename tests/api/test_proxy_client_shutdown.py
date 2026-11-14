"""The LeetCode proxy's shared HTTP client is closed by the app lifespan, not by a deprecated router shutdown hook."""
import asyncio

import httpx

from maya_sawa.api import proxy


def test_the_router_registers_no_deprecated_shutdown_hook():
    assert proxy.router.on_shutdown == []


def test_close_http_client_closes_the_shared_client(monkeypatch):
    client = httpx.AsyncClient()
    monkeypatch.setattr(proxy, "http_client", client)
    asyncio.run(proxy.close_http_client())
    assert client.is_closed
