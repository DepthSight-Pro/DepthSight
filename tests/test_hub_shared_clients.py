"""Regression: hub hot path must reuse pooled HTTP clients (B13).

A fresh client per request means a fresh pool per request: no keep-alive or
TLS reuse on the path 200 federated nodes drive.
"""

import httpx
import pytest

import api.hub_proxy_router as hub_proxy_module
from api.hub_proxy_router import _get_shared_client


@pytest.fixture(autouse=True)
async def _reset_shared_proxy_client():
    """The shared client is process-global: never leak it into other tests."""
    prev_client, hub_proxy_module._shared_client = hub_proxy_module._shared_client, None
    if prev_client is not None and hasattr(prev_client, "aclose"):
        try:
            await prev_client.aclose()
        except Exception:
            pass
    yield
    client, hub_proxy_module._shared_client = hub_proxy_module._shared_client, None
    if client is not None and hasattr(client, "aclose"):
        try:
            await client.aclose()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_hub_proxy_client_is_shared_and_bounded():
    first = _get_shared_client()
    second = _get_shared_client()
    assert first is second
    assert isinstance(first, httpx.AsyncClient)
    assert first.timeout == httpx.Timeout(15.0)


@pytest.mark.asyncio
async def test_hub_http_session_is_shared_per_loop():
    from api.routes import config as config_routes

    first = config_routes._get_hub_http_session()
    second = config_routes._get_hub_http_session()
    assert first is second
    assert not first.closed
    await first.close()
    try:
        third = config_routes._get_hub_http_session()
        assert third is not first
        assert not third.closed
    finally:
        await third.close()
