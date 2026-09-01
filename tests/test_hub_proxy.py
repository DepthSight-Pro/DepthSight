# tests/test_hub_proxy.py
import pytest
from httpx import AsyncClient, ASGITransport, Response
from fastapi import FastAPI
import httpx

import api.hub_proxy_router as hub_proxy_module
from api.hub_proxy_router import router as hub_proxy_router

pytestmark = pytest.mark.asyncio


@pytest.fixture
def proxy_app():
    test_app = FastAPI()
    test_app.include_router(hub_proxy_router)
    return test_app


class _MockProxyClient:
    captured = []
    return_status = 200
    return_json = {}
    raise_exc = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def request(self, method, url, **kwargs):
        if self.raise_exc:
            raise self.raise_exc
        self.captured.append(
            {
                "method": method,
                "url": str(url),
                "headers": kwargs.get("headers"),
                "content": kwargs.get("content"),
            }
        )
        return Response(
            self.return_status,
            json=self.return_json,
            headers={"content-type": "application/json"},
        )


async def test_hub_proxy_get_forwarding(proxy_app, monkeypatch):
    """Verify GET requests (with query params) are forwarded to the central hub."""
    monkeypatch.setenv("FEDERATION_HUB_URL", "https://mock.depthsight.test/api/v1/hub")

    _MockProxyClient.captured = []
    _MockProxyClient.return_status = 200
    _MockProxyClient.return_json = [{"title": "Test News", "content": "Hello"}]
    _MockProxyClient.raise_exc = None

    monkeypatch.setattr(hub_proxy_module.httpx, "AsyncClient", _MockProxyClient)

    transport = ASGITransport(app=proxy_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/hub/news?limit=10&page=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Test News"

    assert len(_MockProxyClient.captured) == 1
    assert _MockProxyClient.captured[0]["method"] == "GET"
    assert (
        _MockProxyClient.captured[0]["url"]
        == "https://mock.depthsight.test/api/v1/hub/news?limit=10&page=1"
    )


async def test_hub_proxy_post_forwarding(proxy_app, monkeypatch):
    """Verify POST requests with JSON payload are forwarded to the central hub."""
    monkeypatch.setenv("FEDERATION_HUB_URL", "https://mock.depthsight.test/api/v1/hub")

    _MockProxyClient.captured = []
    _MockProxyClient.return_status = 201
    _MockProxyClient.return_json = {"status": "received", "ticket_id": "123"}
    _MockProxyClient.raise_exc = None

    monkeypatch.setattr(hub_proxy_module.httpx, "AsyncClient", _MockProxyClient)

    transport = ASGITransport(app=proxy_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"category": "Bug Report", "message": "Something is broken"}
        resp = await client.post("/api/v1/hub/feedback", json=payload)
        assert resp.status_code == 201
        assert resp.json()["status"] == "received"

    assert len(_MockProxyClient.captured) == 1
    assert _MockProxyClient.captured[0]["method"] == "POST"
    assert (
        _MockProxyClient.captured[0]["url"]
        == "https://mock.depthsight.test/api/v1/hub/feedback"
    )


async def test_hub_proxy_unreachable_hub(proxy_app, monkeypatch):
    """Verify proper 502 Bad Gateway is returned when the central hub is unreachable."""
    monkeypatch.setenv("FEDERATION_HUB_URL", "https://mock.depthsight.test/api/v1/hub")

    _MockProxyClient.captured = []
    _MockProxyClient.raise_exc = httpx.ConnectError("Connection refused")

    monkeypatch.setattr(hub_proxy_module.httpx, "AsyncClient", _MockProxyClient)

    transport = ASGITransport(app=proxy_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/hub/strategies")
        assert resp.status_code == 502
        assert "unreachable" in resp.json()["detail"].lower()
