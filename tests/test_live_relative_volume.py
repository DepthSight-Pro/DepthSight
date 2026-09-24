# tests/test_live_relative_volume.py
"""Regression tests for live relative_volume computation (DataConsumer).

Bug: VisualBuilder "rel_vol_filter" in live trading always rejected signals with
``rel_vol_filter(relative_volume=1.0000, ...)``. The strategy declared only the
warmup dummy ``VOL_LOOKBACK_{n}``, which ``_recalculate_kline_indicators`` did
not recognize, so the ``relative_volume`` column was never computed and
``pair_info.get("relative_volume", 1.0)`` fell back to the 1.0 default.
"""

import asyncio

import pandas as pd
import pytest

from bot_module.data_consumer import (
    DataConsumer,
    _global_active_pairs,
    _global_cache_lock,
    _global_history_loaded_keys,
    _global_kline_cache,
    _global_kline_df_cache,
    _global_pairs_lock,
    _kline_cache_key,
)
from bot_module.strategy import VisualBuilderStrategy


@pytest.fixture()
async def consumer():
    loop = asyncio.get_running_loop()
    instance = DataConsumer(loop=loop, executor=None)
    yield instance
    if instance._running:
        await instance.stop()


@pytest.fixture(autouse=True)
async def clear_global_state():
    _global_active_pairs.clear()
    _global_history_loaded_keys.clear()
    _global_kline_cache.clear()
    _global_kline_df_cache.clear()
    yield
    _global_active_pairs.clear()
    _global_history_loaded_keys.clear()
    _global_kline_cache.clear()
    _global_kline_df_cache.clear()


def _volume_spike_df(num_candles: int = 60, spike_mult: float = 5.0) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=num_candles, freq="1min", tz="UTC")
    volumes = [100.0] * num_candles
    volumes[-1] = 100.0 * spike_mult
    return pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": volumes,
        },
        index=dates,
    )


@pytest.mark.asyncio
async def test_vol_lookback_metric_triggers_real_relative_volume(consumer):
    """A legacy VOL_LOOKBACK_20 request must populate pair_info['relative_volume']."""
    symbol = "RVUSDT"
    timeframe = "1m"
    df = _volume_spike_df()
    cache_key = _kline_cache_key(symbol, timeframe, "binance", "futures_usdtm")
    async with _global_cache_lock:
        _global_kline_df_cache[cache_key] = df

    async with consumer._metrics_lock:
        consumer._required_metrics[symbol] = {"VOL_LOOKBACK_20"}

    await consumer._recalculate_kline_indicators(
        symbol, timeframe, market_type="futures_usdtm", exchange_id="binance"
    )

    async with _global_pairs_lock:
        pair_state = dict(_global_active_pairs.get(symbol, {}))
    assert "relative_volume" in pair_state
    assert pair_state["relative_volume"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_live_rel_vol_filter_passes_on_volume_spike(consumer):
    """End-to-end: consumer indicator -> pair_info -> rel_vol_filter passes."""
    symbol = "RVUSDT"
    timeframe = "1m"
    df = _volume_spike_df()
    cache_key = _kline_cache_key(symbol, timeframe, "binance", "futures_usdtm")
    async with _global_cache_lock:
        _global_kline_df_cache[cache_key] = df

    strat = VisualBuilderStrategy(
        {
            "config": {
                "filters": {
                    "type": "rel_vol_filter",
                    "params": {
                        "lookback_period": 20,
                        "rel_vol_threshold": 2.2,
                    },
                }
            }
        }
    )
    async with consumer._metrics_lock:
        consumer._required_metrics[symbol] = set(strat.required_indicators)

    await consumer._recalculate_kline_indicators(
        symbol, timeframe, market_type="futures_usdtm", exchange_id="binance"
    )
    pair_info = await consumer.get_active_pair_by_symbol(symbol)
    assert pair_info is not None
    assert pair_info.get("relative_volume", 1.0) == pytest.approx(5.0)

    passed, details = strat._check_filter_rel_vol(
        pair_info, {}, {"lookback_period": 20, "rel_vol_threshold": 2.2}, {}
    )
    assert passed is True
    assert details["relative_volume"] == pytest.approx(5.0)
