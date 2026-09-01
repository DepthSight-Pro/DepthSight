import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from bot_module import data_consumer
from bot_module.data_consumer import DataConsumer
from bot_module.controller import TradingController


@pytest.fixture(autouse=True)
async def clear_global_data_consumer_state():
    data_consumer._global_ws_registry.clear()
    data_consumer._global_event_queues.clear()
    data_consumer._global_kline_cache.clear()
    data_consumer._global_kline_df_cache.clear()
    data_consumer._global_depth_cache.clear()
    data_consumer._global_agg_trade_deques.clear()
    data_consumer._global_history_loaded_keys.clear()
    data_consumer._global_history_download_tasks.clear()
    data_consumer._global_active_pairs.clear()
    yield
    data_consumer._global_ws_registry.clear()
    data_consumer._global_event_queues.clear()
    data_consumer._global_kline_cache.clear()
    data_consumer._global_kline_df_cache.clear()
    data_consumer._global_depth_cache.clear()
    data_consumer._global_agg_trade_deques.clear()
    data_consumer._global_history_loaded_keys.clear()
    data_consumer._global_history_download_tasks.clear()
    data_consumer._global_active_pairs.clear()


@pytest.mark.asyncio
async def test_ensure_history_loaded_min_candles():
    mock_executor = MagicMock()
    mock_executor.exchange_id = "weex"
    mock_executor.sandbox = False
    mock_executor.market_type = "futures_usdtm"

    # Return 30 candles on fetch_ohlcv
    mock_ohlcv = [
        [1600000000000 + i * 60000, 1.0, 1.1, 0.9, 1.0, 100.0] for i in range(30)
    ]
    mock_fetch = AsyncMock(return_value=mock_ohlcv)
    mock_executor.fetch_ohlcv = mock_fetch

    consumer = DataConsumer(
        executor=mock_executor,
        market_data_mode="direct",
    )

    # 1. Load history with min_candles=20
    res = await consumer._ensure_history_loaded(
        "kline_1m", "XRPUSDT", "1m", "futures_usdtm", "weex", min_candles=20
    )
    assert res is True
    assert mock_fetch.call_count == 1

    df = await consumer.get_kline_history("XRPUSDT", "1m", market_type="futures_usdtm")
    assert df is not None
    assert len(df) == 30

    # 2. Call again without force or with min_candles=20 -> cache hit, no new fetch
    res2 = await consumer._ensure_history_loaded(
        "kline_1m", "XRPUSDT", "1m", "futures_usdtm", "weex", min_candles=20
    )
    assert res2 is True
    assert mock_fetch.call_count == 1

    # 3. Call with min_candles=50 (more than in cache) -> triggers download
    mock_ohlcv_50 = [
        [1600000000000 + i * 60000, 1.0, 1.1, 0.9, 1.0, 100.0] for i in range(50)
    ]
    mock_fetch.return_value = mock_ohlcv_50
    res3 = await consumer._ensure_history_loaded(
        "kline_1m", "XRPUSDT", "1m", "futures_usdtm", "weex", min_candles=50
    )
    assert res3 is True
    assert mock_fetch.call_count == 2

    df50 = await consumer.get_kline_history(
        "XRPUSDT", "1m", market_type="futures_usdtm"
    )
    assert len(df50) == 50


@pytest.mark.asyncio
async def test_get_kline_history_on_demand_backfill():
    mock_executor = MagicMock()
    mock_executor.exchange_id = "weex"
    mock_executor.sandbox = False
    mock_executor.market_type = "futures_usdtm"

    mock_ohlcv = [
        [1600000000000 + i * 60000, 1.0, 1.1, 0.9, 1.0, 100.0] for i in range(25)
    ]
    mock_executor.fetch_ohlcv = AsyncMock(return_value=mock_ohlcv)

    consumer = DataConsumer(
        executor=mock_executor,
        market_data_mode="direct",
    )

    # Request with min_candles=20 when cache is empty -> triggers backfill
    df = await consumer.get_kline_history(
        "XRPUSDT", "1m", market_type="futures_usdtm", min_candles=20
    )
    assert df is not None
    assert len(df) == 25


@pytest.mark.asyncio
async def test_controller_gather_market_data_backfills_missing_candles():
    mock_executor = MagicMock()
    mock_executor.exchange_id = "weex"
    mock_executor.sandbox = False
    mock_executor.market_type = "futures_usdtm"

    # Setup executor to return 30 candles on backfill
    mock_ohlcv_30 = [
        [1600000000000 + i * 60000, 1.0, 1.1, 0.9, 1.0, 100.0] for i in range(30)
    ]
    mock_executor.fetch_ohlcv = AsyncMock(return_value=mock_ohlcv_30)

    consumer = DataConsumer(
        executor=mock_executor,
        market_data_mode="direct",
    )

    # Prepopulate cache with only 5 candles (< 20 required)
    cache_key = "weex:futures_usdtm:XRPUSDT:1m"
    for i in range(5):
        data_consumer._global_kline_cache[cache_key].append(
            (1600000000000 + i * 60000, 1.0, 1.1, 0.9, 1.0, 100.0)
        )
    data_consumer._global_history_loaded_keys.add(cache_key)

    controller = TradingController(
        loop=asyncio.get_running_loop(),
        data_consumer=consumer,
        live_executor=mock_executor,
        paper_executor=AsyncMock(),
        risk_manager=MagicMock(),
        user_id=1,
    )
    controller.executor = mock_executor

    market_data = await controller._gather_market_data_for_required_keys(
        log_prefix="[TestGather]",
        symbol="XRPUSDT",
        required_data_keys={"kline_1m"},
        market_type="futures_usdtm",
    )

    assert market_data is not None
    assert "kline_1m" in market_data
    assert len(market_data["kline_1m"]) >= 20
