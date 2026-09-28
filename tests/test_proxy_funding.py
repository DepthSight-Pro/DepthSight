# tests/test_proxy_funding.py
"""Tests for the funding proxy (GET /api/v1/proxy/funding)."""

import sys
import types

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.auth import get_current_user
from api.routes import diagnostics as diag_module
from api.routes.diagnostics import diagnostics_router


@pytest.fixture
def funding_app():
    test_app = FastAPI()
    test_app.include_router(diagnostics_router)

    async def _fake_user():
        return types.SimpleNamespace(id=1, username="tester")

    test_app.dependency_overrides[get_current_user] = _fake_user
    return test_app


class _FakeFundingExchange:
    """Minimal ccxt-compatible stub for fetch_funding_rate."""

    instances = []
    payload = {}

    def __init__(self, config):
        self.config = config
        self.fetch_kwargs = None
        _FakeFundingExchange.instances.append(self)

    async def fetch_funding_rate(self, symbol, params=None):
        self.fetch_kwargs = {"symbol": symbol}
        return dict(_FakeFundingExchange.payload)

    async def close(self):
        return None


def _install_fake_ccxt(monkeypatch, payload):
    _FakeFundingExchange.instances = []
    _FakeFundingExchange.payload = payload
    fake_mod = types.ModuleType("ccxt.async_support")
    for name in ("binance", "bybit", "okx", "bitget", "weex"):
        setattr(fake_mod, name, _FakeFundingExchange)
    monkeypatch.setitem(sys.modules, "ccxt.async_support", fake_mod)
    monkeypatch.setitem(sys.modules, "ccxt", types.ModuleType("ccxt"))


async def _get(app, params):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/v1/proxy/funding", params=params)


async def test_weex_funding_normalized(funding_app, monkeypatch):
    diag_module._FUNDING_CACHE.clear()
    _install_fake_ccxt(
        monkeypatch,
        {
            "fundingRate": 0.0001,
            "nextFundingRate": 0.0002,
            "nextFundingTimestamp": 1790496000000,
            "info": {"collectCycle": 480, "nextFundingTime": 1790496000000},
        },
    )
    resp = await _get(funding_app, {"symbol": "ZECUSDT", "exchange": "weex_futures"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["exchange"] == "weex"
    assert data["symbol"] == "ZECUSDT"
    assert data["funding_rate"] == 0.0001
    assert data["predicted_rate"] == 0.0002
    assert data["next_funding_time_ms"] == 1790496000000
    assert data["interval_hours"] == 8.0
    inst = _FakeFundingExchange.instances[-1]
    assert inst.fetch_kwargs["symbol"] == "ZEC/USDT:USDT"


async def test_funding_cached_second_call(funding_app, monkeypatch):
    diag_module._FUNDING_CACHE.clear()
    _install_fake_ccxt(monkeypatch, {"fundingRate": 0.0003})
    params = {"symbol": "BTCUSDT", "exchange": "bybit"}
    first = await _get(funding_app, params)
    assert first.status_code == 200, first.text
    calls_after_first = len(_FakeFundingExchange.instances)
    second = await _get(funding_app, params)
    assert second.status_code == 200, second.text
    assert second.json()["funding_rate"] == 0.0003
    assert len(_FakeFundingExchange.instances) == calls_after_first


async def test_funding_unsupported_exchange_rejected(funding_app, monkeypatch):
    diag_module._FUNDING_CACHE.clear()
    _install_fake_ccxt(monkeypatch, {})
    resp = await _get(funding_app, {"symbol": "BTCUSDT", "exchange": "kraken"})
    assert resp.status_code == 400


async def test_funding_ccxt_failure_maps_to_502(funding_app, monkeypatch):
    diag_module._FUNDING_CACHE.clear()

    class _Boom(_FakeFundingExchange):
        async def fetch_funding_rate(self, *a, **k):
            raise RuntimeError("weex exploded")

    fake_mod = types.ModuleType("ccxt.async_support")
    fake_mod.weex = _Boom
    monkeypatch.setitem(sys.modules, "ccxt.async_support", fake_mod)
    monkeypatch.setitem(sys.modules, "ccxt", types.ModuleType("ccxt"))
    resp = await _get(funding_app, {"symbol": "ZECUSDT", "exchange": "weex"})
    assert resp.status_code == 502
