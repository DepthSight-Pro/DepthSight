import pytest
import pandas as pd
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock
from bot_module.strategy import VisualBuilderStrategy, _get_idx_for_timestamp
from bot_module.data_consumer import DataConsumer

# --- TESTS FOR STRATEGY.PY ---


def test_strategy_volatility_indicator_requirements():
    """Check that volatility_filter adds ATR and BBW to the required indicators."""
    config_data = {
        "entryConditions": [],
        "filters": [
            {
                "id": "vol_filt",
                "type": "volatility_filter",
                "params": {
                    "indicator": "ATR",
                    "period": 14,
                    "operator": "gt",
                    "value": 0.5,
                },
            },
            {
                "id": "bbw_filt",
                "type": "volatility_filter",
                "params": {
                    "indicator": "BBW",
                    "period": 20,
                    "std_dev": 2.0,
                    "operator": "gt",
                    "value": 0.05,
                },
            },
        ],
    }
    # We pass this as 'config' to the strategy parameters
    strategy = VisualBuilderStrategy({"config": config_data})

    required = strategy.required_indicators
    # ATR
    assert "ATR_14" in required
    # Bollinger Bands Width (Bandwidth)
    assert "BBL_20_2.0" in required
    assert "BBU_20_2.0" in required
    assert "BBB_20_2.0" in required


def test_non_monotonic_index_handling():
    """Check that time search does not crash on a non-monotonic index."""
    dates = [
        datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
        datetime(2024, 1, 1, 10, 5, tzinfo=timezone.utc),
        datetime(2024, 1, 1, 10, 3, tzinfo=timezone.utc),  # Monotonicity violation
    ]
    df = pd.DataFrame({"close": [100, 101, 102]}, index=pd.DatetimeIndex(dates))

    # Previously this caused ValueError: index must be monotonic
    # Now it should return len(df) - 1
    idx = _get_idx_for_timestamp(df, datetime(2024, 1, 1, 10, 4, tzinfo=timezone.utc))
    assert idx == 2


def test_volume_confirmation_live_index_default():
    """Check that volume_confirmation in live (without index) uses the last candle."""
    strategy = VisualBuilderStrategy({"config": {}})

    market_data = {
        "kline_1m": pd.DataFrame(
            {
                "open": [10, 11],
                "high": [12, 13],
                "low": [8, 9],
                "close": [11, 12],
                "volume": [100, 200],
            },
            index=pd.date_range("2024-01-01", periods=2, freq="1min"),
        )
    }
    pair_info = {
        "symbol": "BTCUSDT",
        "candle_timeframe": "1m",
    }  # No current_candle_index

    # Should not crash, should return a result (filter success or failure - doesn't matter, main thing is no Exception)
    res, details = strategy._check_foundation_volume_confirmation_wrapper(
        pair_info, market_data, {}, {}
    )
    assert isinstance(res, bool)


# --- TESTS FOR DATA_CONSUMER.PY ---


@pytest.mark.asyncio
async def test_ccxt_pro_ws_optimization():
    """Check that CCXT Pro WS sends CANDLE_CLOSE only once."""
    consumer = DataConsumer()
    consumer._running = True

    mock_executor = MagicMock()
    mock_ccxt_pro = AsyncMock()
    mock_executor._exchange_pro = mock_ccxt_pro

    # candle format: [timestamp, open, high, low, close, volume]
    c1_ts = 1700000000000
    c1 = [c1_ts, 10, 11, 9, 10.5, 100]
    c2_ts = 1700000060000
    c2 = [c2_ts, 11.5, 13, 11, 12, 50]

    # Emulate: Two candles arrive at once (the first is closed, the second is open)
    mock_ccxt_pro.watch_ohlcv.return_value = [c1, c2]

    consumer._update_local_cache = AsyncMock()

    # Start and interrupt after a short time
    task = asyncio.create_task(
        consumer._ccxt_pro_data_ws_loop(
            "BTCUSDT", "kline_1m", "stream_id", "futures", mock_executor
        )
    )
    await asyncio.sleep(0.1)
    consumer._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.TimeoutError, Exception):
        pass

    calls = consumer._update_local_cache.call_args_list

    # There should be at least 2 calls (c1 and c2) in the very first iteration
    assert len(calls) >= 2

    # The first candle in the iteration (c1) must be marked as closed (x=True)
    # since it is not the last one in the list [c1, c2]
    c1_call = next(c for c in calls if c[0][2]["k"]["t"] == c1_ts)
    assert c1_call[0][2]["k"]["x"] is True

    # The second candle (c2) must be open (x=False)
    c2_call = next(c for c in calls if c[0][2]["k"]["t"] == c2_ts)
    assert c2_call[0][2]["k"]["x"] is False

    # Ensure that the close was sent for c1
    closed_calls = [
        c for c in calls if c[0][2]["k"]["x"] is True and c[0][2]["k"]["t"] == c1_ts
    ]
    assert len(closed_calls) == 1


@pytest.mark.asyncio
async def test_data_consumer_unsubscription_logic():
    """Check that unsubscription correctly parses new stream_id with prefixes."""
    consumer = DataConsumer()
    # Force direct mode to ensure it uses _binance_market_data_ws_tasks
    consumer._use_redis_market_data = False

    # exchange:market:symbol@type
    stream_id_1 = "binance:futures_usdtm:btcusdt@kline_1m"
    stream_id_2 = "gateio:futures_usdtm:btcusdt@aggTrade"
    stream_id_3 = "binance:futures_usdtm:ethusdt@kline_1m"

    # Mock remove_subscription so that it actually deletes from the dictionary
    async def side_effect(dt_key, symbol, market_type=None):
        # We need to find all keys in _binance_market_data_ws_tasks that match this unsubscription.
        # DataConsumer uses multiple formats for keys, so we check for both symbol and dt_key.
        async with consumer._binance_market_data_ws_lock:
            to_pop = []
            symbol_lc = symbol.lower()
            dt_key_lc = dt_key.lower()
            for stream_id in consumer._binance_market_data_ws_tasks:
                if symbol_lc in stream_id.lower() and dt_key_lc in stream_id.lower():
                    to_pop.append(stream_id)

            for key in to_pop:
                consumer._binance_market_data_ws_tasks.pop(key, None)

    consumer.remove_subscription = AsyncMock(side_effect=side_effect)
    consumer._binance_market_data_ws_lock = asyncio.Lock()

    mock_task = MagicMock()
    consumer._binance_market_data_ws_tasks = {
        stream_id_1: mock_task,
        stream_id_2: mock_task,
        stream_id_3: mock_task,
    }

    # Populate global registry NOT NECESSARY anymore because it uses _binance_market_data_ws_tasks keys
    # but let's keep it if it's used elsewhere, although the logic we just read uses .keys()

    await consumer.remove_all_subscriptions_for_symbol("BTCUSDT")

    assert stream_id_1 not in consumer._binance_market_data_ws_tasks
    assert stream_id_2 not in consumer._binance_market_data_ws_tasks
    assert stream_id_3 in consumer._binance_market_data_ws_tasks
