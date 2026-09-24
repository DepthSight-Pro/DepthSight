# tests/test_proxy_klines.py
"""Tests for the unified multi-exchange klines proxy (GET /proxy/klines)."""

import sys
import types

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.auth import get_current_user
from api.routes import diagnostics as diag_module
from api.routes.diagnostics import (
    _normalize_kline_exchange,
    _to_ccxt_swap_symbol,
    diagnostics_router,
)


@pytest.fixture
def klines_app():
    test_app = FastAPI()
    test_app.include_router(diagnostics_router)

    async def _fake_user():
        return types.SimpleNamespace(id=1, username="tester")

    test_app.dependency_overrides[get_current_user] = _fake_user
    return test_app


class _FakeExchange:
    """Minimal ccxt-compatible stub recording constructor/fetch kwargs."""

    instances = []

    def __init__(self, config):
        self.config = config
        self.fetch_kwargs = None
        _FakeExchange.instances.append(self)

    async def fetch_ohlcv(
        self, symbol, timeframe=None, since=None, limit=None, params=None
    ):
        self.fetch_kwargs = {
            "symbol": symbol,
            "timeframe": timeframe,
            "since": since,
            "limit": limit,
        }
        return _FakeExchange.rows

    async def close(self):
        return None


def _install_fake_ccxt(monkeypatch, rows):
    _FakeExchange.instances = []
    _FakeExchange.rows = rows
    fake_mod = types.ModuleType("ccxt.async_support")
    for name in ("binance", "bybit", "okx", "bitget", "weex"):
        setattr(fake_mod, name, _FakeExchange)
    monkeypatch.setitem(sys.modules, "ccxt.async_support", fake_mod)
    monkeypatch.setitem(sys.modules, "ccxt", types.ModuleType("ccxt"))
    return fake_mod


def _request(app, params):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_okx_klines_normalized(klines_app, monkeypatch):
    rows = [
        [1700000060000, 100.0, 102.0, 99.0, 101.0, 10.0],
        [1700000000000, 98.0, 100.0, 97.0, 99.0, 11.0],
    ]
    _install_fake_ccxt(monkeypatch, rows)
    async with _request(klines_app, None) as client:
        resp = await client.get(
            "/api/v1/proxy/klines",
            params={
                "symbol": "BTCUSDT",
                "interval": "15m",
                "exchange": "okx_futures",
                "limit": 40,
            },
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Sorted ascending by timestamp despite reversed input
    assert [r[0] for r in data] == [1700000000000, 1700000060000]
    assert data[0][1:6] == [98.0, 100.0, 97.0, 99.0, 11.0]
    inst = _FakeExchange.instances[-1]
    assert inst.config["options"] == {"defaultType": "swap"}
    assert inst.fetch_kwargs["symbol"] == "BTC/USDT:USDT"
    assert inst.fetch_kwargs["timeframe"] == "15m"
    assert inst.fetch_kwargs["limit"] == 40


async def test_endtime_filter_and_limit_clamp(klines_app, monkeypatch):
    rows = [
        [1700000000000, 1.0, 1.0, 1.0, 1.0, 5.0],
        [1700000060000, 2.0, 2.0, 2.0, 2.0, 6.0],
    ]
    _install_fake_ccxt(monkeypatch, rows)
    async with _request(klines_app, None) as client:
        resp = await client.get(
            "/api/v1/proxy/klines",
            params={
                "symbol": "ETHUSDT",
                "interval": "1h",
                "exchange": "bitget",
                "endTime": 1700000000000,
                "limit": 5000,
            },
        )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1
    assert _FakeExchange.instances[-1].fetch_kwargs["limit"] == 1000


async def test_unsupported_exchange_rejected(klines_app, monkeypatch):
    _install_fake_ccxt(monkeypatch, [])
    async with _request(klines_app, None) as client:
        resp = await client.get(
            "/api/v1/proxy/klines",
            params={"symbol": "BTCUSDT", "interval": "15m", "exchange": "kraken"},
        )
    assert resp.status_code == 400


async def test_unsupported_interval_rejected(klines_app, monkeypatch):
    _install_fake_ccxt(monkeypatch, [])
    async with _request(klines_app, None) as client:
        resp = await client.get(
            "/api/v1/proxy/klines",
            params={"symbol": "BTCUSDT", "interval": "3h", "exchange": "weex"},
        )
    assert resp.status_code == 400


async def test_ccxt_failure_maps_to_502(klines_app, monkeypatch):
    class _Boom(_FakeExchange):
        async def fetch_ohlcv(self, *a, **k):
            raise RuntimeError("weex exploded")

    fake_mod = types.ModuleType("ccxt.async_support")
    fake_mod.weex = _Boom
    monkeypatch.setitem(sys.modules, "ccxt.async_support", fake_mod)
    monkeypatch.setitem(sys.modules, "ccxt", types.ModuleType("ccxt"))
    async with _request(klines_app, None) as client:
        resp = await client.get(
            "/api/v1/proxy/klines",
            params={"symbol": "BTCUSDT", "interval": "1m", "exchange": "weex"},
        )
    assert resp.status_code == 502


def test_symbol_and_exchange_normalizers():
    assert _to_ccxt_swap_symbol("BTCUSDT") == "BTC/USDT:USDT"
    assert _to_ccxt_swap_symbol("ETHUSDC") == "ETH/USDC:USDC"
    assert _to_ccxt_swap_symbol("BTC/USDT") == "BTC/USDT:USDT"
    assert _normalize_kline_exchange("OKX_futures") == "okx"
    assert _normalize_kline_exchange("weex_usdtm") == "weex"
    assert _normalize_kline_exchange("bitget_spot") == "bitget"
    assert _normalize_kline_exchange(None) == "binance"
    assert "weex" in diag_module.SUPPORTED_KLINE_EXCHANGES
