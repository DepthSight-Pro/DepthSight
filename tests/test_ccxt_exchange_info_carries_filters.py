"""fetch_exchange_info() and get_symbol_info() MUST return the same shape.
"""

import asyncio
from typing import Any, Dict

import pytest

from bot_module.exchanges.ccxt_executor import CcxtExecutor


def _market(
    symbol: str,
    base: str,
    *,
    swap: bool = True,
    spot: bool = False,
    price_precision: Any = 8,
    amount_precision: Any = 8,
) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "id": symbol,
        "base": base,
        "quote": "USDT",
        "active": True,
        "swap": swap,
        "spot": spot,
        "type": "swap" if swap else "spot",
        "precision": {"price": price_precision, "amount": amount_precision},
        "limits": {
            "amount": {"min": 0.001, "max": 1000000.0},
            "cost": {"min": 5.0},
        },
        "contractSize": 1.0,
    }


def _executor(raw_markets: Dict[str, Any], market_type: str) -> CcxtExecutor:
    """Build a real CcxtExecutor without running its network constructor."""
    executor = object.__new__(CcxtExecutor)

    class _FakeExchange:
        def __init__(self, markets):
            self.markets = markets
            self.precisionMode = 4  # ccxt.TICK_SIZE -> precision IS a step

        async def load_markets(self):
            return self.markets

    executor._exchange = _FakeExchange(raw_markets)
    executor.exchange_id = "okx"
    executor.market_type = market_type
    executor.supports_positions = True
    executor.supports_shorting = True
    executor.sandbox = False
    return executor


def _entry_by_symbol(info: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    for entry in info["symbols"]:
        if entry.get("symbol") == symbol:
            return entry
    raise AssertionError(f"{symbol} missing from fetch_exchange_info output")


def _tick_size(entry: Dict[str, Any]) -> float:
    for f in entry.get("filters", []) or []:
        if f.get("filterType") == "PRICE_FILTER":
            return float(f["tickSize"])
    raise AssertionError(
        "No PRICE_FILTER in entry -- the controller's cache parser reads "
        f"`filters` and would store tick_size=None. Entry: {entry}"
    )


# --------------------------------------------------------------------------
# The contract.
# --------------------------------------------------------------------------


def test_futures_exchange_info_includes_price_filter():
    markets = {
        "BTC/USDT:USDT": _market("BTC/USDT:USDT", "BTC", swap=True),
        "ETH/USDT:USDT": _market("ETH/USDT:USDT", "ETH", swap=True),
    }
    executor = _executor(markets, "futures_usdtm")
    info = asyncio.run(executor.fetch_exchange_info())

    for symbol in ("BTCUSDT", "ETHUSDT"):
        entry = _entry_by_symbol(info, symbol)
        assert _tick_size(entry) > 0
        assert entry["tick_size"] > 0
        assert entry["lot_params"]["stepSize"] > 0
        assert entry["min_notional"] > 0


def test_spot_exchange_info_includes_price_filter():
    markets = {
        "BTC/USDT": _market("BTC/USDT", "BTC", swap=False, spot=True),
    }
    executor = _executor(markets, "spot")
    info = asyncio.run(executor.fetch_exchange_info())

    entry = _entry_by_symbol(info, "BTCUSDT")
    assert _tick_size(entry) > 0


def test_get_symbol_info_and_fetch_exchange_info_agree():
    """The two functions must not drift -- that drift WAS the bug."""
    markets = {"BTC/USDT:USDT": _market("BTC/USDT:USDT", "BTC", swap=True)}
    executor = _executor(markets, "futures_usdtm")

    single = asyncio.run(executor.get_symbol_info("BTCUSDT"))
    bulk = _entry_by_symbol(
        asyncio.run(executor.fetch_exchange_info()), "BTCUSDT"
    )

    for field in ("tick_size", "lot_params", "min_notional"):
        assert single.get(field) == bulk.get(field), (
            f"get_symbol_info() and fetch_exchange_info() disagree on {field}: "
            f"{single.get(field)!r} vs {bulk.get(field)!r}"
        )
    assert _tick_size(bulk) == _tick_size(single)


def test_top_volume_safety_net_entries_carry_filters():
    """A pair the swap/quote filter drops must still get a tick_size."""
    markets = {
        "BTC/USDT:USDT": _market("BTC/USDT:USDT", "BTC", swap=False),
        "ETH/USDT:USDT": _market("ETH/USDT:USDT", "ETH", swap=True),
    }
    executor = _executor(markets, "futures_usdtm")
    info = asyncio.run(executor.fetch_exchange_info())

    btc = _entry_by_symbol(info, "BTCUSDT")
    assert _tick_size(btc) > 0, (
        "BTCUSDT came from the hardcoded top-volume safety net and carried no "
        "precision -- exactly the deployed failure."
    )
    assert btc["lot_params"]["stepSize"] > 0


def test_every_symbol_ccxt_actually_knows_has_a_tick_size():
    bases = ("BTC", "ETH", "SOL", "XRP")
    markets = {
        f"{base}/USDT:USDT": _market(f"{base}/USDT:USDT", base, swap=True)
        for base in bases
    }
    executor = _executor(markets, "futures_usdtm")
    info = asyncio.run(executor.fetch_exchange_info())

    by_symbol = {e["symbol"]: e for e in info["symbols"]}
    for base in bases:
        entry = by_symbol[f"{base}USDT"]
        assert _tick_size(entry) > 0, (
            f"{base}USDT is known to ccxt but was emitted without a PRICE_FILTER."
        )

    unknown = [s for s, e in by_symbol.items() if not e.get("filters")]
    assert all(
        s not in by_symbol or s not in {f"{b}USDT" for b in bases} for s in unknown
    )
    for symbol in unknown:
        assert f"{symbol[:-4]}/USDT:USDT" not in markets

