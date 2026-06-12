# tests/test_e2e_data_consumer.py
import asyncio
import logging
import pytest
import websockets
from websockets.protocol import State
import pandas as pd
from unittest.mock import patch, AsyncMock

from bot_module import config as global_config
from bot_module import data_consumer
from bot_module.data_consumer import DataConsumer
from bot_module.exchanges import ExchangeExecutor

logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
async def clear_global_data_consumer_state():
    from bot_module import data_consumer

    # Clear all global state containers
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
    # Cleanup after test
    data_consumer._global_ws_registry.clear()
    data_consumer._global_event_queues.clear()
    data_consumer._global_kline_cache.clear()
    data_consumer._global_kline_df_cache.clear()
    data_consumer._global_depth_cache.clear()
    data_consumer._global_agg_trade_deques.clear()
    data_consumer._global_history_loaded_keys.clear()
    data_consumer._global_history_download_tasks.clear()
    data_consumer._global_active_pairs.clear()


# --- Utility for creating full mock DataFrames ---
def create_full_mock_df(rows=1):
    now = pd.Timestamp.now(tz="UTC")
    index = [now - pd.Timedelta(minutes=i) for i in range(rows, 0, -1)]
    return pd.DataFrame(
        {
            "open": [100.0] * rows,
            "high": [102.0] * rows,
            "low": [99.0] * rows,
            "close": [101.0] * rows,
            "volume": [1000.0] * rows,
            "number_of_trades": [10] * rows,  # Added
        },
        index=pd.to_datetime(index),
    ).set_index(pd.DatetimeIndex(index, name="open_time"))


# --- Fixtures ---
@pytest.fixture
async def mock_ws_server():
    server_state = {"active_connections": set(), "connected_paths": []}

    # path is now None by default, as in real websockets.serve
    async def handler(websocket, path=None):
        actual_path = path
        if actual_path is None:
            if hasattr(websocket, "path"):
                actual_path = websocket.path
            elif hasattr(websocket, "request") and hasattr(websocket.request, "path"):
                actual_path = websocket.request.path
            else:
                actual_path = ""
        server_state["active_connections"].add(websocket)
        server_state["connected_paths"].append(actual_path)
        try:
            await websocket.wait_closed()
        finally:
            server_state["active_connections"].discard(websocket)

    server = await websockets.serve(handler, "127.0.0.1", 0)
    server_url = f"ws://{server.sockets[0].getsockname()[0]}:{server.sockets[0].getsockname()[1]}"
    yield server_url, server_state
    server.close()
    await server.wait_closed()


@pytest.fixture
def mock_executor():
    executor = AsyncMock(spec=ExchangeExecutor)
    executor.exchange_id = "binance"
    executor.fetch_exchange_info.return_value = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "pair": "BTCUSDT",
                "status": "TRADING",
                "isSpotTradingAllowed": True,
                "contractType": "PERPETUAL",
                "quoteAsset": "USDT",
            },
            {
                "symbol": "ETHUSDT",
                "pair": "ETHUSDT",
                "status": "TRADING",
                "isSpotTradingAllowed": True,
                "contractType": "PERPETUAL",
                "quoteAsset": "USDT",
            },
        ]
    }
    return executor


# --- Patch for websockets.connect compatibility ---
@pytest.fixture(autouse=True)
def patch_websockets_connect():
    # Use the top-level websockets.connect which is compatible across versions
    original_connect = websockets.connect

    async def side_effect(uri, **kwargs):
        # Handle potential parameter renaming in different websockets versions if needed
        # but for now just call original_connect
        return await original_connect(uri, **kwargs)

    with patch("websockets.connect", side_effect=side_effect) as m:
        yield m


# --- TESTS ---
@pytest.mark.asyncio
async def test_kline_subscription_and_history_load(mock_executor, monkeypatch):
    monkeypatch.setattr(global_config, "ACTIVE_TRADING_ENVIRONMENT", "mainnet")
    monkeypatch.setattr(global_config, "TRADING_MARKET_TYPE", "spot")

    # Mock CCXT Pro watch_ohlcv
    mock_exchange_pro = AsyncMock()
    mock_exchange_pro.watch_ohlcv = AsyncMock(side_effect=asyncio.Future)
    mock_executor._exchange_pro = mock_exchange_pro

    monkeypatch.setattr(global_config, "MAIN_APP_WS_URL", "ws://dummy-url-for-test")

    consumer = DataConsumer(
        loop=asyncio.get_running_loop(),
        executor=mock_executor,
        market_data_mode="direct",
    )
    # Link local keys to global ones to match application behavior
    consumer._history_loaded_keys = data_consumer._global_history_loaded_keys
    try:
        await consumer.start()
        with patch(
            "bot_module.data_consumer.download_klines", new_callable=AsyncMock
        ) as mock_download:
            mock_download.return_value = create_full_mock_df()
            await consumer.ensure_subscription("kline_1m", "BTCUSDT")
            await asyncio.sleep(0.1)

            assert (
                "binance:spot:btcusdt@kline_1m"
                in consumer._binance_market_data_ws_tasks
            )
            mock_exchange_pro.watch_ohlcv.assert_awaited()
    finally:
        if consumer._running:
            await consumer.stop()


@pytest.mark.asyncio
async def test_companion_depth_subscription(mock_executor, mock_ws_server, monkeypatch):
    ws_url, server_state = mock_ws_server
    monkeypatch.setattr(global_config, "TRADING_MARKET_TYPE", "futures_usdtm")
    monkeypatch.setattr(global_config, "USE_COMPANION_ORDERBOOK_ANALYSIS", True)
    monkeypatch.setattr(
        global_config, "ANALYZE_SPOT_ORDERBOOK_FOR_FUTURES_TRADES", True
    )
    monkeypatch.setattr(
        global_config, "BINANCE_FUTURES_USDTM_MAINNET_MARKET_DATA_WS_URL", ws_url
    )
    monkeypatch.setattr(
        global_config, "BINANCE_SPOT_MAINNET_MARKET_DATA_WS_URL", ws_url
    )

    # Mock MAIN_APP_WS_URL to avoid unnecessary connections
    monkeypatch.setattr(global_config, "MAIN_APP_WS_URL", "ws://dummy-url-for-test")
    original_websockets_connect_func = websockets.connect  # Save the original
    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:

        async def side_effect_connect(uri, **kwargs):
            if "dummy-url-for-test" in uri:
                mock_ws = AsyncMock()
                mock_ws.close.return_value = asyncio.sleep(0)
                mock_ws.__aiter__.return_value = [].__iter__()
                mock_ws.state = State.OPEN
                return mock_ws
            return await original_websockets_connect_func(
                uri, **kwargs
            )  # Call the original for the others

        mock_connect.side_effect = side_effect_connect

        consumer = DataConsumer(
            loop=asyncio.get_running_loop(),
            executor=mock_executor,
            market_data_mode="direct",
        )
        # Link local keys to global ones to match application behavior
        consumer._history_loaded_keys = data_consumer._global_history_loaded_keys

        with patch.object(
            consumer.loop, "create_task", new_callable=AsyncMock
        ) as mock_create_task:
            mock_create_task.return_value = (
                AsyncMock()
            )  # The mock should return a mock task
            try:
                consumer._running = True
                await consumer.ensure_subscription(
                    "depth", "ETHUSDT", needs_companion_orderbook=True
                )

                assert mock_create_task.call_count == 2
                assert (
                    "binance:futures_usdtm:ethusdt@depth"
                    in consumer._binance_market_data_ws_tasks
                )
                assert (
                    "binance:spot:ethusdt@depth"
                    in consumer._binance_market_data_ws_tasks
                )
            finally:
                consumer._running = False
                if consumer._running:
                    await consumer.stop()


@pytest.mark.asyncio
async def test_unsubscription_logic(mock_executor, monkeypatch):
    monkeypatch.setattr(global_config, "TRADING_MARKET_TYPE", "spot")
    monkeypatch.setattr(global_config, "ACTIVE_TRADING_ENVIRONMENT", "mainnet")

    # Mock CCXT Pro watch_ohlcv
    mock_exchange_pro = AsyncMock()
    mock_exchange_pro.watch_ohlcv = AsyncMock(side_effect=asyncio.Future)
    mock_executor._exchange_pro = mock_exchange_pro

    # Mock MAIN_APP_WS_URL to avoid unnecessary connections
    monkeypatch.setattr(global_config, "MAIN_APP_WS_URL", "ws://dummy-url-for-test")

    consumer = DataConsumer(
        loop=asyncio.get_running_loop(),
        executor=mock_executor,
        market_data_mode="direct",
    )
    # Link local keys to global ones to match application behavior
    consumer._history_loaded_keys = data_consumer._global_history_loaded_keys

    try:
        await consumer.start()
        with patch(
            "bot_module.data_consumer.download_klines", new_callable=AsyncMock
        ) as mock_download:
            mock_download.return_value = create_full_mock_df()

            await consumer.ensure_subscription("kline_1m", "ETHUSDT")
            await asyncio.sleep(0.2)
            assert (
                "binance:spot:ethusdt@kline_1m"
                in consumer._binance_market_data_ws_tasks
            )
            mock_exchange_pro.watch_ohlcv.assert_awaited()

            await consumer.remove_subscription("kline_1m", "ETHUSDT")
            await asyncio.sleep(0.2)
            assert (
                "binance:spot:ethusdt@kline_1m"
                not in consumer._binance_market_data_ws_tasks
            )
    finally:
        if consumer._running:
            await consumer.stop()


@pytest.mark.asyncio
async def test_live_data_processing(mock_executor, monkeypatch):
    monkeypatch.setattr(global_config, "ACTIVE_TRADING_ENVIRONMENT", "mainnet")
    monkeypatch.setattr(global_config, "TRADING_MARKET_TYPE", "futures_usdtm")

    consumer = DataConsumer(
        loop=asyncio.get_running_loop(),
        executor=mock_executor,
        market_data_mode="direct",
    )
    # Link local keys to global ones to match application behavior
    consumer._history_loaded_keys = data_consumer._global_history_loaded_keys

    try:
        consumer._running = True

        # Mock MAIN_APP_WS_URL to avoid unnecessary connections
        monkeypatch.setattr(global_config, "MAIN_APP_WS_URL", "ws://dummy-url-for-test")
        original_websockets_connect_func = websockets.connect  # Save the original
        with (
            patch("websockets.connect", new_callable=AsyncMock) as mock_connect,
            patch.object(consumer, "_binance_data_ws_loop", AsyncMock()),
        ):  # Patch _binance_data_ws_loop

            async def side_effect_connect(uri, **kwargs):
                if "dummy-url-for-test" in uri:
                    mock_ws = AsyncMock()
                    mock_ws.close.return_value = asyncio.sleep(0)
                    mock_ws.__aiter__.return_value = [].__iter__()
                    mock_ws.state = State.OPEN
                    return mock_ws
                return await original_websockets_connect_func(
                    uri, **kwargs
                )  # Call the original for the others

            mock_connect.side_effect = side_effect_connect

            await consumer.ensure_subscription("depth", "BTCUSDT")
            await consumer.ensure_subscription("aggTrade", "BTCUSDT")

        depth_msg = {
            "e": "depthUpdate",
            "s": "BTCUSDT",
            "E": 123456789,
            "u": 123,
            "b": [["60000.0", "10.0"]],
            "a": [["60001.0", "12.0"]],
        }
        agg_trade_msg = {
            "e": "aggTrade",
            "s": "BTCUSDT",
            "E": 123456789,
            "a": 555,
            "p": "60000.5",
            "q": "0.5",
            "m": True,
            "T": 1678886400000,
        }

        await consumer._update_local_cache(
            "depth", "BTCUSDT", depth_msg, market_type="futures_usdtm"
        )
        await consumer._update_local_cache(
            "aggTrade", "BTCUSDT", agg_trade_msg, market_type="futures_usdtm"
        )

        depth_cache = await consumer.get_latest_depth("BTCUSDT", "futures_usdtm")
        assert depth_cache is not None
        assert depth_cache["lastUpdateId"] == 123

        async with consumer._data_cache_lock:
            # App updates global deque, check it
            trade_deque = data_consumer._global_agg_trade_deques.get("BTCUSDT")
            assert trade_deque is not None and len(trade_deque) == 1
            assert trade_deque[0]["p"] == "60000.5"

    finally:
        consumer._running = False
        if consumer._running:
            await consumer.stop()


@pytest.mark.asyncio
async def test_reconnection_on_drop(mock_executor, monkeypatch):
    monkeypatch.setattr(global_config, "TRADING_MARKET_TYPE", "spot")
    monkeypatch.setattr(global_config, "ACTIVE_TRADING_ENVIRONMENT", "mainnet")
    monkeypatch.setattr(global_config, "BINANCE_WS_RECONNECT_DELAY_BASE", 0.05)

    # Mock CCXT Pro watch_ohlcv to raise an error to simulate disconnect, then hang
    mock_exchange_pro = AsyncMock()

    async def mock_watch_ohlcv(*args, **kwargs):
        if mock_exchange_pro.watch_ohlcv.call_count <= 2:
            raise Exception("Simulated connection drop")
        await asyncio.Future()  # hang on 3rd attempt

    mock_exchange_pro.watch_ohlcv = AsyncMock(side_effect=mock_watch_ohlcv)
    mock_executor._exchange_pro = mock_exchange_pro

    # Mock MAIN_APP_WS_URL to avoid unnecessary connections
    monkeypatch.setattr(global_config, "MAIN_APP_WS_URL", "ws://dummy-url-for-test")

    consumer = DataConsumer(
        loop=asyncio.get_running_loop(),
        executor=mock_executor,
        market_data_mode="direct",
    )
    # Link local keys to global ones to match application behavior
    consumer._history_loaded_keys = data_consumer._global_history_loaded_keys

    try:
        await consumer.start()
        with patch(
            "bot_module.data_consumer.download_klines", new_callable=AsyncMock
        ) as mock_download:
            mock_download.return_value = create_full_mock_df()

            # Patch the sleep function specifically within the data_consumer module to avoid the 5s wait
            original_sleep = asyncio.sleep

            async def fast_sleep(delay):
                if delay == 5:  # Only fast-forward the backoff sleep
                    await original_sleep(0.01)
                else:
                    await original_sleep(delay)

            with patch(
                "bot_module.data_consumer.asyncio.sleep", side_effect=fast_sleep
            ):
                await consumer.ensure_subscription("kline_1m", "BTCUSDT")

                # Wait for retries to happen
                for _ in range(50):
                    if mock_exchange_pro.watch_ohlcv.call_count >= 3:
                        break
                    await asyncio.sleep(0.05)  # Use real sleep for test polling

        assert mock_exchange_pro.watch_ohlcv.call_count >= 2, (
            f"Expected multiple watch_ohlcv calls due to retries, received: {mock_exchange_pro.watch_ohlcv.call_count}"
        )
    finally:
        if consumer._running:
            await consumer.stop()
