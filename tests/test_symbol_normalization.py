# File: tests/test_symbol_normalization.py
"""
The dashed symbol form produced an unsellable market.

Live evidence, 2026-10-10:

    ERROR - Error fetching OHLCV on okx for BTC-USDT:
    okx does not have market symbol BTC-/USDT:USDT

``_normalize_symbol`` stripped only the trailing quote:

    base = "BTC-USDT"[:-4]   ->  "BTC-"      # separator survives
    f"{base}/USDT:USDT"      ->  "BTC-/USDT:USDT"

So every strategy whose stored config used OKX's native ``BTC-USDT`` form fetched
**zero** candles, for every timeframe, forever. The error was logged but the failure
mode is silent in the UI: the strategy simply never trades.

These tests call the real method on a real executor instance, including the
``supports_positions`` branch that OKX actually takes.
"""

import pytest

from bot_module.exchanges.ccxt_executor import CcxtExecutor


class _Exec(CcxtExecutor):
    """Minimal instance: _normalize_symbol touches only supports_positions."""

    def __init__(self, supports_positions: bool):
        self.supports_positions = supports_positions
        self.exchange_id = "okx"


CASES_POSITIONAL = [
    # (input, expected) -- OKX swap path
    ("BTCUSDT", "BTC/USDT:USDT"),
    ("BTC-USDT", "BTC/USDT:USDT"),   # <- the bug
    ("btc-usdt", "BTC/USDT:USDT"),   # <- and lowercase
    ("ETH-USDT", "ETH/USDT:USDT"),
    ("BTC-USDT-SWAP", "BTC/USDT:USDT"),
]


@pytest.mark.parametrize("raw,expected", CASES_POSITIONAL)
def test_dashed_symbol_normalizes_like_the_plain_form(raw, expected):
    ex = _Exec(supports_positions=True)
    assert ex._normalize_symbol(raw) == expected


@pytest.mark.parametrize("raw", ["BTCUSDT", "BTC-USDT"])
def test_dashed_and_plain_agree(raw):
    """The dashed form must be indistinguishable from the plain form."""
    assert _Exec(supports_positions=True)._normalize_symbol(raw) == _Exec(
        supports_positions=True
    )._normalize_symbol("BTCUSDT")


@pytest.mark.parametrize("raw", ["BTCUSDT", "BTC-USDT"])
def test_spot_path_is_also_fixed(raw):
    ex = _Exec(supports_positions=False)
    assert ex._normalize_symbol(raw) == "BTC/USDT"


def test_already_normalized_symbols_are_untouched():
    ex = _Exec(supports_positions=True)
    assert ex._normalize_symbol("BTC/USDT:USDT") == "BTC/USDT:USDT"
    assert ex._normalize_symbol("BTC/USDT") == "BTC/USDT:USDT"


def test_no_market_ends_with_a_stray_separator():
    """The exact shape that failed in production must never be produced."""
    ex = _Exec(supports_positions=True)
    for raw in ("BTC-USDT", "btc-usdt", " BTC-USDT "):
        base = ex._normalize_symbol(raw).split("/")[0]
        assert base.endswith("-") is False
        assert base.endswith("_") is False