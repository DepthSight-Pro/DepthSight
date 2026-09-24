# tests/test_tape_metrics_names.py
"""Tape metric naming contract between DataConsumer and strategy blocks.

The strategy tape blocks (tape_analysis / tape_condition) read
tape_{buy_volume_usd,...,avg_trade_size_usd}_{window}s and
tape_accel_mult_{volume,count}_{window}s_60s keys from pair_info.
This test feeds synthetic trades through the real
DataConsumer._recalculate_tape_metrics and asserts every strategy-facing
key is produced, finite, and internally consistent.
"""

import asyncio
import math
import time

import pytest

from bot_module import data_consumer as dc_module
from bot_module.data_consumer import (
    DataConsumer,
    _trade_cache_key,
    TAPE_METRIC_WINDOWS,
)

STRATEGY_SUFFIXES = [
    "buy_volume_usd",
    "sell_volume_usd",
    "total_volume_usd",
    "buy_count",
    "sell_count",
    "total_count",
    "delta_volume_usd",
    "delta_count",
    "buy_sell_ratio_volume",
    "buy_sell_ratio_count",
    "avg_trade_size_usd",
]


def _make_trades(now_ms: int, n: int = 150):
    trades = []
    for i in range(n):
        trades.append(
            {
                # Spread over the last 120s so all standard windows are covered.
                "T": now_ms - (120_000 * i // max(n - 1, 1)),
                "p": str(60000.0 + (i % 7)),
                "q": str(0.05 + 0.01 * (i % 5)),
                "m": bool(i % 2),
            }
        )
    return sorted(trades, key=lambda t: t["T"])


@pytest.mark.asyncio
async def test_recalculate_produces_strategy_tape_names():
    symbol = "TESTUSDT"
    exchange_id = "binance"
    market_type = "futures_usdtm"
    now_ms = int(time.time() * 1000)

    cache_key = _trade_cache_key(symbol, exchange_id, market_type)
    dc_module._global_agg_trade_deques[cache_key].extend(_make_trades(now_ms, n=150))

    consumer = DataConsumer(loop=asyncio.get_running_loop(), market_data_mode="direct")
    try:
        await consumer._recalculate_tape_metrics(
            symbol,
            now_ms,
            market_type=market_type,
            exchange_id=exchange_id,
        )

        async with dc_module._global_pairs_lock:
            pair_state = dict(dc_module._global_active_pairs.get(symbol, {}))

        # Legacy keys still present (backward compatibility).
        for window in TAPE_METRIC_WINDOWS:
            for key in (
                f"tape_count_{window}s",
                f"tape_volume_{window}s",
                f"tape_delta_{window}s",
                f"tape_avg_volume_per_sec_{window}s",
                f"tape_avg_count_per_sec_{window}s",
            ):
                assert key in pair_state, f"legacy key missing: {key}"

        # Strategy-facing keys for every window.
        for window in TAPE_METRIC_WINDOWS:
            for suffix in STRATEGY_SUFFIXES:
                key = f"tape_{suffix}_{window}s"
                assert key in pair_state, f"strategy key missing: {key}"
                val = pair_state[key]
                assert isinstance(val, (int, float)), f"{key} not numeric: {val!r}"
                assert math.isfinite(float(val)), f"{key} not finite: {val!r}"
            for suffix in ("volume", "count"):
                key = f"tape_accel_mult_{suffix}_{window}s_60s"
                assert key in pair_state, f"accel key missing: {key}"
                assert math.isfinite(float(pair_state[key])), f"{key} not finite"

        # Internal consistency on the 30s window.
        w = 30
        buy_v = pair_state[f"tape_buy_volume_usd_{w}s"]
        sell_v = pair_state[f"tape_sell_volume_usd_{w}s"]
        assert pair_state[f"tape_total_volume_usd_{w}s"] == pytest.approx(
            buy_v + sell_v
        )
        assert pair_state[f"tape_delta_volume_usd_{w}s"] == pytest.approx(
            buy_v - sell_v
        )
        assert pair_state[f"tape_delta_{w}s"] == pytest.approx(buy_v - sell_v)
        buy_c = pair_state[f"tape_buy_count_{w}s"]
        sell_c = pair_state[f"tape_sell_count_{w}s"]
        assert pair_state[f"tape_total_count_{w}s"] == buy_c + sell_c
        assert pair_state[f"tape_delta_count_{w}s"] == buy_c - sell_c
    finally:
        dc_module._global_agg_trade_deques.pop(cache_key, None)
        dc_module._global_agg_trade_deques.pop(symbol, None)
        async with dc_module._global_pairs_lock:
            dc_module._global_active_pairs.pop(symbol, None)


@pytest.mark.asyncio
async def test_empty_tape_produces_neutral_keys():
    symbol = "EMPTYUSDT"
    now_ms = int(time.time() * 1000)
    consumer = DataConsumer(loop=asyncio.get_running_loop(), market_data_mode="direct")
    try:
        await consumer._recalculate_tape_metrics(
            symbol, now_ms, market_type="futures_usdtm", exchange_id="binance"
        )
        async with dc_module._global_pairs_lock:
            pair_state = dict(dc_module._global_active_pairs.get(symbol, {}))
        # No trades at all: recalculation is a no-op, nothing must appear.
        assert pair_state == {} or all(
            math.isfinite(float(v)) for v in pair_state.values()
        )
    finally:
        async with dc_module._global_pairs_lock:
            dc_module._global_active_pairs.pop(symbol, None)
