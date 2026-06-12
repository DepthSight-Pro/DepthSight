# tests/test_data_consumer.py
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, patch
import pandas as pd
import websockets
import websockets.protocol  # Added for State enum

try:
    from bot_module import data_consumer
    from bot_module.data_consumer import DataConsumer, normalize_symbol_for_binance
    from bot_module import config as global_config
    from bot_module.exchanges import ExchangeExecutor
except ImportError:
    pytest.skip(
        "Skipping DataConsumer tests: bot_module components not found.",
        allow_module_level=True,
    )


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


# Class MockPersistentWebSocket remains unchanged


class MockPersistentWebSocket:
    def __init__(self):
        self.open = True
        self.sent_messages = []
        self._message_queue = asyncio.Queue()
        self.path = ""
        self._closed_event = asyncio.Event()
        self.connect_kwargs = {}

    @property
    def state(self):
        if self.open:
            return websockets.protocol.State.OPEN
        else:
            return websockets.protocol.State.CLOSED

    async def mock_connect_method(self, uri, **kwargs):
        self.path = uri
        self.open = True
        self._message_queue = asyncio.Queue()
        self._closed_event.clear()
        self.connect_kwargs = kwargs
        return self

    async def send(self, message):
        if not self.open:
            raise websockets.exceptions.ConnectionClosed(None, None)
        self.sent_messages.append(message)

    async def recv(self):
        if not self.open and self._message_queue.empty():
            raise websockets.exceptions.ConnectionClosedOK(
                None, None, "Connection closed and queue empty"
            )

        fut_msg = asyncio.create_task(self._message_queue.get())
        fut_closed = asyncio.create_task(self._closed_event.wait())

        done, pending = await asyncio.wait(
            [fut_msg, fut_closed], return_when=asyncio.FIRST_COMPLETED
        )

        for task_in_pending in pending:
            if not task_in_pending.done():
                task_in_pending.cancel()
                try:
                    await task_in_pending
                except asyncio.CancelledError:
                    pass

        if fut_closed.done():
            if not fut_msg.done() or (fut_msg.done() and fut_msg.result() is None):
                self.open = False
                raise websockets.exceptions.ConnectionClosed(None, None)

        if fut_msg.done():
            msg = fut_msg.result()
            if msg is None:
                self.open = False
                raise websockets.exceptions.ConnectionClosed(None, None)
            return msg

        self.open = False
        raise websockets.exceptions.ConnectionClosed(None, None)

    async def close(self, code=1000, reason=""):
        if self.open:
            self.open = False
            await self._message_queue.put(None)
            self._closed_event.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.recv()
        except websockets.exceptions.ConnectionClosed:
            raise StopAsyncIteration

    async def push_message_to_client(self, message_json_str):
        if self.open:
            await self._message_queue.put(message_json_str)


# Fixtures mock_executor and simple_main_app_ws_server remain unchanged


@pytest.fixture
def mock_executor():
    executor = AsyncMock(spec=ExchangeExecutor)
    executor.fetch_exchange_info.return_value = {
        "symbols": [
            {"symbol": "BTCUSDT", "status": "TRADING", "isSpotTradingAllowed": True},
            {"symbol": "ETHUSDT", "status": "TRADING", "isSpotTradingAllowed": True},
            {"symbol": "VALIDSPOT", "status": "TRADING", "isSpotTradingAllowed": True},
            {"symbol": "XYZUSDT", "status": "TRADING", "isSpotTradingAllowed": False},
        ]
    }
    executor.exchange_id = "binance"
    executor.market_type = "spot"
    executor.sandbox = False
    return executor


@pytest.fixture
async def data_consumer_instance(mock_executor):
    global_config.BINANCE_SPOT_MAINNET_MARKET_DATA_WS_URL = "wss://test.binance.spot/ws"
    global_config.BINANCE_FUTURES_USDTM_MAINNET_MARKET_DATA_WS_URL = (
        "wss://test.binance.futures/ws"
    )
    consumer = DataConsumer(
        loop=asyncio.get_running_loop(),
        executor=mock_executor,
        market_data_mode="direct",
    )
    # Link local keys to global ones to match application behavior (app adds to global but checks local)
    consumer._history_loaded_keys = data_consumer._global_history_loaded_keys
    yield consumer
    if consumer._running:
        await consumer.stop()


@pytest.fixture
async def simple_main_app_ws_server():
    active_connections = set()

    async def handler(websocket, path=None):
        active_connections.add(websocket)
        try:
            initial_pairs_msg = {
                "type": "active_pairs_update",
                "data": [{"symbol": "BTC/USDT"}, {"symbol": "ETHUSDT"}],
            }
            await websocket.send(json.dumps(initial_pairs_msg))
            async for message in websocket:
                pass
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            active_connections.discard(websocket)

    host = "127.0.0.1"
    start_server = await websockets.serve(handler, host, 0)
    server_address = start_server.sockets[0].getsockname()
    server_url = f"ws://{host}:{server_address[1]}"
    yield server_url
    start_server.close()
    await start_server.wait_closed()


def test_normalize_symbol():
    assert normalize_symbol_for_binance("BTC/USDT") == "BTCUSDT"
    assert normalize_symbol_for_binance("ethusdt") == "ETHUSDT"


@pytest.mark.asyncio
async def test_non_binance_history_uses_executor_ohlcv(monkeypatch):
    executor = AsyncMock()
    executor.exchange_id = "bybit"
    executor.market_type = "futures_usdtm"
    executor.fetch_ohlcv.return_value = [[1710000000000, 100, 110, 90, 105, 12]]

    consumer = DataConsumer(loop=asyncio.get_running_loop(), executor=executor)
    monkeypatch.setattr(
        data_consumer,
        "download_klines",
        AsyncMock(side_effect=AssertionError("binance loader must not be used")),
    )

    cache_key = data_consumer._kline_cache_key("BTCUSDT", "1m", "futures_usdtm")
    await consumer._download_initial_kline_history_for_key(
        cache_key, "BTCUSDT", "1m", "futures_usdtm"
    )

    executor.fetch_ohlcv.assert_awaited_once()
    assert cache_key in data_consumer._global_history_loaded_keys
    assert list(data_consumer._global_kline_cache[cache_key]) == [
        (1710000000000, 100.0, 110.0, 90.0, 105.0, 12.0)
    ]


# Tests start_stop and active_pairs_update remain unchanged


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


@pytest.mark.asyncio
async def test_data_consumer_start_stop(data_consumer_instance, monkeypatch):
    mock_main_app_ws = MockPersistentWebSocket()
    # We still need to patch connect to return our mock, but we use the patched_connect as base if needed
    # Actually, just mocking it to return our mock is enough for this test
    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = mock_main_app_ws.mock_connect_method
        monkeypatch.setattr(global_config, "SYMBOL_SOURCE_MODE", "MAIN_APP")
        data_consumer_instance._main_app_ws_url = "ws://mock-main-app-server:1234"
        await data_consumer_instance.start()
        assert data_consumer_instance._running
        await asyncio.sleep(0.1)
        await data_consumer_instance.stop()
        assert not data_consumer_instance._running


@pytest.mark.asyncio
async def test_active_pairs_update_from_main_app_ws(
    data_consumer_instance, simple_main_app_ws_server, monkeypatch
):
    monkeypatch.setattr(global_config, "SYMBOL_SOURCE_MODE", "MAIN_APP")
    monkeypatch.setattr(data_consumer, "BINANCE_WS_RECONNECT_DELAY_BASE", 0.1)
    data_consumer_instance._main_app_ws_url = simple_main_app_ws_server

    await data_consumer_instance.start()

    # Wait for symbols to appear in cache (async update from mock server)
    found = False
    for _ in range(30):
        active_symbols = await data_consumer_instance.get_active_symbols()
        if "BTCUSDT" in active_symbols:
            found = True
            break
        await asyncio.sleep(0.1)

    assert found, "BTCUSDT not found in active symbols after WS update"
    await data_consumer_instance.stop()


@pytest.mark.asyncio
async def test_ensure_subscription_for_kline_and_history_load(
    data_consumer_instance, monkeypatch
):
    data_consumer_instance._running = True

    monkeypatch.setattr(global_config, "TRADING_MARKET_TYPE", "spot")
    symbol = "VALIDSPOT"
    timeframe = "1m"
    data_type_key = f"kline_{timeframe}"

    # Mock _ccxt_pro_data_ws_loop to avoid real CCXT Pro logic
    monkeypatch.setattr(
        data_consumer.DataConsumer, "_ccxt_pro_data_ws_loop", AsyncMock()
    )

    with patch(
        "bot_module.data_consumer.download_klines", new_callable=AsyncMock
    ) as mock_download:
        mock_download.return_value = pd.DataFrame()

        await data_consumer_instance.ensure_subscription(data_type_key, symbol)
        await asyncio.sleep(0.2)

        mock_download.assert_called_once()
        cache_key_hist = "binance:spot:VALIDSPOT:1m"
        # App adds to global registry, and our fixture linked them
        from bot_module import data_consumer as dc_mod

        assert cache_key_hist in dc_mod._global_history_loaded_keys

        task_key = "binance:spot:validspot@kline_1m"
        assert task_key in data_consumer_instance._binance_market_data_ws_tasks


@pytest.mark.asyncio
async def test_kline_data_processing_from_mock_ws(data_consumer_instance, monkeypatch):
    data_consumer_instance._running = True

    symbol = "VALIDSPOT"
    timeframe = "1m"
    monkeypatch.setattr(global_config, "TRADING_MARKET_TYPE", "spot")
    monkeypatch.setattr(global_config, "ACTIVE_TRADING_ENVIRONMENT", "mainnet")

    hist_df = pd.DataFrame(
        [
            [
                pd.to_datetime("2023-01-01 12:00:00", utc=True),
                100,
                101,
                99,
                100.5,
                10.0,
                1,
            ]
        ],
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "number_of_trades",
        ],
    ).set_index("open_time")

    # Mock CCXT Pro watch_ohlcv
    kline_start_time = int(
        (hist_df.index[-1] + pd.Timedelta(minutes=1)).timestamp() * 1000
    )
    ohlcv_data = [[kline_start_time, 110, 112, 109, 111.5, 1000]]

    mock_exchange_pro = AsyncMock()

    async def mock_watch_ohlcv(*args, **kwargs):
        if mock_exchange_pro.watch_ohlcv.call_count == 1:
            return ohlcv_data
        await asyncio.Future()  # hang

    mock_exchange_pro.watch_ohlcv = AsyncMock(side_effect=mock_watch_ohlcv)
    data_consumer_instance._executor._exchange_pro = mock_exchange_pro

    with patch(
        "bot_module.data_consumer.download_klines", new_callable=AsyncMock
    ) as mock_download:
        mock_download.return_value = hist_df

        await data_consumer_instance.ensure_subscription(f"kline_{timeframe}", symbol)

        # wait for message to be processed
        for _ in range(30):
            kline_cache = await data_consumer_instance.get_kline_history(
                symbol, timeframe
            )
            if kline_cache is not None and len(kline_cache) == 2:
                break
            await asyncio.sleep(0.1)

        kline_cache = await data_consumer_instance.get_kline_history(symbol, timeframe)
        assert len(kline_cache) == 2
        assert float(kline_cache["close"].iloc[-1]) == 111.5


@pytest.mark.asyncio
async def test_kline_snapshot_cache_updates_last_candle(data_consumer_instance):
    symbol = "BTCUSDT"
    timeframe = "1m"
    cache_key = "binance:futures_usdtm:BTCUSDT:1m"

    first_payload = {
        "e": "kline",
        "s": symbol,
        "k": {
            "t": 1700000000000,
            "o": "100",
            "h": "101",
            "l": "99",
            "c": "100.5",
            "v": "10",
            "x": False,
        },
    }
    updated_payload = {
        "e": "kline",
        "s": symbol,
        "k": {
            "t": 1700000000000,
            "o": "100",
            "h": "102",
            "l": "98.5",
            "c": "101.5",
            "v": "12",
            "x": False,
        },
    }

    await data_consumer_instance._update_local_cache(
        "kline_1m", symbol, first_payload, market_type="futures_usdtm"
    )

    assert cache_key in data_consumer._global_kline_df_cache
    first_df = await data_consumer_instance.get_kline_history(
        symbol, timeframe, market_type="futures_usdtm"
    )
    assert first_df is not None
    assert len(first_df) == 1
    assert float(first_df["close"].iloc[-1]) == pytest.approx(100.5)

    await data_consumer_instance._update_local_cache(
        "kline_1m", symbol, updated_payload, market_type="futures_usdtm"
    )

    updated_df = await data_consumer_instance.get_kline_history(
        symbol, timeframe, market_type="futures_usdtm"
    )
    assert updated_df is not None
    assert len(updated_df) == 1
    assert float(updated_df["high"].iloc[-1]) == pytest.approx(102.0)
    assert float(updated_df["close"].iloc[-1]) == pytest.approx(101.5)


# Test invalid_symbol remains unchanged


@pytest.mark.asyncio
async def test_subscription_to_invalid_symbol(data_consumer_instance, monkeypatch):
    data_consumer_instance._running = True  # Let's add it just in case
    monkeypatch.setattr(global_config, "TRADING_MARKET_TYPE", "spot")
    invalid_symbol = "XYZUSDT"
    await data_consumer_instance.ensure_subscription("kline_1m", invalid_symbol)
    await asyncio.sleep(0.1)
    assert not data_consumer_instance._binance_market_data_ws_tasks


@pytest.mark.asyncio
async def test_aggtrade_data_processing_from_mock_ws(
    data_consumer_instance, monkeypatch
):
    data_consumer_instance._running = True

    monkeypatch.setattr(global_config, "TRADING_MARKET_TYPE", "spot")
    monkeypatch.setattr(global_config, "ACTIVE_TRADING_ENVIRONMENT", "mainnet")
    symbol = "VALIDSPOT"

    trade_data = [
        {
            "symbol": "VALIDSPOT",
            "id": "12345",
            "timestamp": 1699999999000,
            "datetime": "2023-11-14T12:00:00.000Z",
            "side": "buy",
            "price": 100.5,
            "amount": 1.0,
            "info": {
                "m": True,  # isBuyerMaker
            },
        }
    ]
    mock_exchange_pro = AsyncMock()

    async def mock_watch_trades(*args, **kwargs):
        if mock_exchange_pro.watch_trades.call_count == 1:
            return trade_data
        await asyncio.Future()  # hang

    mock_exchange_pro.watch_trades = AsyncMock(side_effect=mock_watch_trades)
    data_consumer_instance._executor._exchange_pro = mock_exchange_pro
    data_consumer_instance.event_queue = asyncio.Queue()

    await data_consumer_instance.ensure_subscription("aggTrade", symbol)

    # wait for message to be processed
    event = None
    for _ in range(30):
        if not data_consumer_instance.event_queue.empty():
            event = data_consumer_instance.event_queue.get_nowait()
            break
        await asyncio.sleep(0.1)

    assert event is not None
    assert event["type"] == "TICK"
    assert event["symbol"] == "VALIDSPOT"
    assert event["price"] == 100.5
    assert event["quantity"] == 1.0
    assert event["timestamp_ms"] == 1699999999000
