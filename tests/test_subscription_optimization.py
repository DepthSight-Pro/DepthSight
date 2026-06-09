# tests/test_subscription_optimization.py
"""
Tests to verify data subscription optimization:
1. Verify that required_data_types returns only the necessary data for different configurations
2. Verify that the global WebSocket registry prevents duplicate subscriptions
3. Verify that requires_spot_orderbook is correctly determined
4. Verify that event broadcasting works for multiple users
"""

import pytest
import asyncio
import json
from collections import defaultdict
from websockets.protocol import State
from unittest.mock import MagicMock, AsyncMock, patch

# Import modules under test
try:
    from bot_module.strategy import VisualBuilderStrategy
    from bot_module.genetic_adapter import GeneticCompatibleStrategy
    from bot_module.data_consumer import (
        DataConsumer,
        _global_active_pairs,
        _global_cache_lock,
        _global_kline_cache,
        _global_pairs_lock,
        _global_ws_registry,
        _global_event_queues,
    )
    from bot_module import config
    from market_data_service import MarketDataService
except ImportError:
    pytest.skip(
        "Skipping subscription optimization tests: bot_module not found.",
        allow_module_level=True,
    )


# ==============================================================================
# TESTS FOR required_data_types
# ==============================================================================


class TestRequiredDataTypes:
    """Tests to verify that strategies return only the required data types."""

    def test_minimal_strategy_no_extra_subscriptions(self):
        """
        A strategy with minimal configuration (only trend_direction)
        should NOT require depth, aggTrade, or higher timeframes.
        """
        minimal_config = {
            "entryTrigger": {"type": "on_candle_close"},
            "conditions": {
                "type": "AND",
                "children": [
                    {
                        "type": "trend_direction",
                        "params": {"sma_fast_period": 10, "sma_slow_period": 50},
                    }
                ],
            },
        }

        strategy = VisualBuilderStrategy(
            params={"config": minimal_config, "candle_timeframe": "5m"}
        )

        required = strategy.required_data_types

        # There should be only the main timeframe
        assert "kline_5m" in required, "Must require the main timeframe"

        # There should be NO extra subscriptions
        assert "depth" not in required, (
            "Should not require depth without order book blocks"
        )
        assert "aggTrade" not in required, (
            "Should not require aggTrade without tape blocks"
        )
        assert "kline_1d" not in required, (
            "Should not require kline_1d without significant_level"
        )
        assert "kline_1h" not in required, (
            "Should not require kline_1h without significant_level"
        )
        assert "kline_4h" not in required, (
            "Should not require kline_4h without significant_level"
        )

    def test_orderbook_strategy_requires_depth(self):
        """
        A strategy with an order_book_zone block MUST require depth.
        """
        orderbook_config = {
            "entryTrigger": {"type": "on_candle_close"},
            "conditions": {
                "type": "AND",
                "children": [
                    {
                        "type": "order_book_zone",
                        "params": {"side": "bids", "range_value": 1.0},
                    }
                ],
            },
        }

        strategy = VisualBuilderStrategy(
            params={"config": orderbook_config, "candle_timeframe": "1m"}
        )

        required = strategy.required_data_types

        assert "depth" in required, "Should require depth for order_book_zone"
        assert "kline_1m" in required, "Must require the main timeframe"

    def test_tape_strategy_requires_aggtrade(self):
        """
        A strategy with a tape_analysis block MUST require aggTrade.
        """
        tape_config = {
            "entryTrigger": {"type": "on_candle_close"},
            "conditions": {
                "type": "AND",
                "children": [
                    {"type": "tape_analysis", "params": {"time_window_sec": 5}}
                ],
            },
        }

        strategy = VisualBuilderStrategy(
            params={"config": tape_config, "candle_timeframe": "1m"}
        )

        required = strategy.required_data_types

        assert "aggTrade" in required, "Should require aggTrade for tape_analysis"

    def test_open_interest_strategy_requires_open_interest_feed(self):
        """
        A strategy with open_interest should require open_interest history.
        """
        oi_config = {
            "entryTrigger": {"type": "on_candle_close"},
            "conditions": {
                "type": "AND",
                "children": [{"type": "open_interest", "params": {"lookback": 5}}],
            },
        }

        strategy = VisualBuilderStrategy(
            params={"config": oi_config, "candle_timeframe": "1m"}
        )

        required = strategy.required_data_types

        assert "open_interest" in required, (
            "Should require open_interest for the open_interest block"
        )

    def test_significant_level_requires_higher_timeframes(self):
        """
        A strategy with a significant_level block MUST require higher timeframes.
        """
        level_config = {
            "entryTrigger": {"type": "on_candle_close"},
            "conditions": {
                "type": "AND",
                "children": [
                    {"type": "significant_level", "params": {"lookback": 100}}
                ],
            },
        }

        strategy = VisualBuilderStrategy(
            params={"config": level_config, "candle_timeframe": "1m"}
        )

        required = strategy.required_data_types

        assert "kline_1h" in required, "Should require kline_1h for significant_level"
        assert "kline_4h" in required, "Should require kline_4h for significant_level"
        assert "kline_1d" in required, "Should require kline_1d for significant_level"

    def test_genetic_strategy_minimal_requirements(self):
        """
        A genetic strategy with only indicator blocks
        should NOT require depth or aggTrade.
        """
        genetic_config = {
            "entryTrigger": {"type": "on_candle_close"},
            "conditions": {
                "type": "AND",
                "children": [
                    {
                        "type": "time_filter",
                        "params": {"start_hour_utc": 8, "end_hour_utc": 20},
                    },
                    {
                        "type": "trend_filter",
                        "params": {"indicator": "SMA", "threshold": 50},
                    },
                    {
                        "type": "ma_cross_condition",
                        "params": {"fast_period": 9, "slow_period": 21},
                    },
                ],
            },
        }

        strategy = GeneticCompatibleStrategy(
            params={"config": genetic_config, "candle_timeframe": "5m"}
        )

        required = strategy.required_data_types

        # There should be only the main timeframe
        assert "kline_5m" in required, "Must require the main timeframe"

        # There should NOT be depth and aggTrade for purely indicator strategies
        assert "depth" not in required, (
            "Genetic strategy without order book should not require depth"
        )
        assert "aggTrade" not in required, (
            "Genetic strategy without tape should not require aggTrade"
        )


# ==============================================================================
# TESTS FOR requires_spot_orderbook
# ==============================================================================


class TestRequiresSpotOrderbook:
    """Tests to verify the determination of spot orderbook necessity."""

    def test_orderbook_zone_requires_spot(self):
        """Strategy with order_book_zone should require a spot order book."""
        config = {"conditions": {"type": "order_book_zone", "params": {"side": "bids"}}}

        strategy = VisualBuilderStrategy(params={"config": config})

        assert strategy.requires_spot_orderbook

    def test_l2_microstructure_requires_spot(self):
        """Strategy with l2_microstructure should require a spot order book."""
        config = {"conditions": {"type": "l2_microstructure", "params": {}}}

        strategy = VisualBuilderStrategy(params={"config": config})

        assert strategy.requires_spot_orderbook

    def test_l2_microstructure_check_alias_requires_spot(self):
        """Legacy alias l2_microstructure_check should request spot orderbook and depth."""
        config = {"conditions": {"type": "l2_microstructure_check", "params": {}}}

        strategy = VisualBuilderStrategy(params={"config": config})

        assert strategy.requires_spot_orderbook
        assert "depth" in strategy.required_data_types

    def test_trend_only_no_spot_required(self):
        """A strategy with only trend_direction should NOT require the spot orderbook."""
        config = {
            "conditions": {"type": "trend_direction", "params": {"sma_fast_period": 10}}
        }

        strategy = VisualBuilderStrategy(params={"config": config})

        assert not strategy.requires_spot_orderbook

    def test_nested_orderbook_block_detected(self):
        """Nested order_book_zone should be detected."""
        config = {
            "conditions": {
                "type": "AND",
                "children": [
                    {"type": "trend_direction", "params": {}},
                    {
                        "type": "OR",
                        "children": [
                            {"type": "order_book_zone", "params": {"side": "asks"}}
                        ],
                    },
                ],
            }
        }

        strategy = VisualBuilderStrategy(params={"config": config})

        assert strategy.requires_spot_orderbook


# ==============================================================================
# TESTS FOR GLOBAL WEBSOCKET REGISTRY
# ==============================================================================


class QueueBackedWebSocket:
    def __init__(self):
        self.open = True
        self.path = "/btcusdt@kline_1m"
        self.messages = asyncio.Queue()

    @property
    def state(self):
        return State.OPEN if self.open else State.CLOSED

    async def close(self, code=1000, reason=""):
        if self.open:
            self.open = False
            await self.messages.put(None)

    async def push_json(self, payload):
        await self.messages.put(json.dumps(payload))

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.messages.get()
        if message is None:
            raise StopAsyncIteration
        return message


class FakeRedisSnapshotClient:
    def __init__(self, snapshot=None):
        self.snapshot = snapshot
        self.published = []
        self.set_calls = []

    async def get(self, key):
        return json.dumps(self.snapshot) if self.snapshot else None

    async def set(self, key, value, ex=None):
        self.set_calls.append((key, json.loads(value), ex))
        return True

    async def publish(self, channel, payload):
        self.published.append((channel, json.loads(payload)))
        return 1

    async def close(self):
        return None


class FakePubSub:
    def __init__(self):
        self.subscribed = []
        self.unsubscribed = []

    async def subscribe(self, channel):
        self.subscribed.append(channel)

    async def unsubscribe(self, channel):
        self.unsubscribed.append(channel)

    async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
        await asyncio.sleep(min(timeout or 0, 0.01))
        return None

    async def close(self):
        return None


class InMemoryRedisBus:
    def __init__(self):
        self.values = {}
        self.subscribers = defaultdict(set)

    def client(self):
        return InMemoryRedisClient(self)

    async def publish(self, channel, payload):
        queues = list(self.subscribers.get(channel, set()))
        for queue in queues:
            await queue.put({"type": "message", "channel": channel, "data": payload})
        return len(queues)


class InMemoryRedisClient:
    def __init__(self, bus):
        self.bus = bus
        self.published = []
        self.set_calls = []

    def pubsub(self):
        return InMemoryPubSub(self.bus)

    async def get(self, key):
        return self.bus.values.get(key)

    async def set(self, key, value, ex=None):
        self.bus.values[key] = value
        self.set_calls.append((key, json.loads(value), ex))
        return True

    async def publish(self, channel, payload):
        decoded = json.loads(payload) if isinstance(payload, str) else payload
        self.published.append((channel, decoded))
        return await self.bus.publish(channel, payload)

    async def close(self):
        return None


class InMemoryPubSub:
    def __init__(self, bus):
        self.bus = bus
        self.queue = asyncio.Queue()
        self.channels = set()

    async def subscribe(self, channel):
        self.channels.add(channel)
        self.bus.subscribers[channel].add(self.queue)

    async def unsubscribe(self, channel):
        self.channels.discard(channel)
        self.bus.subscribers[channel].discard(self.queue)

    async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
        try:
            return await asyncio.wait_for(self.queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def close(self):
        for channel in list(self.channels):
            await self.unsubscribe(channel)


async def run_market_data_command_loop_once_ready(
    service, stop_event, ready_event=None
):
    await service.pubsub.subscribe(config.MARKET_DATA_REDIS_COMMAND_CHANNEL)
    if ready_event:
        ready_event.set()
    while not stop_event.is_set():
        message = await service.pubsub.get_message(
            ignore_subscribe_messages=True, timeout=0.05
        )
        if not message or message.get("type") != "message":
            continue
        raw = message.get("data")
        payload = json.loads(raw) if isinstance(raw, str) else raw
        await service._handle_command(payload)


class TestGlobalWebSocketRegistry:
    """Tests to verify that subscriptions are not duplicated in multi-user mode."""

    @pytest.fixture
    def mock_executor(self):
        """Creates a mock executor for DataConsumer."""
        executor = MagicMock()
        executor.exchange_id = "binance"
        executor.market_type = "futures_usdtm"
        executor.sandbox = False
        executor.fetch_exchange_info = AsyncMock(
            return_value={
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "pair": "BTCUSDT",
                        "status": "TRADING",
                        "contractType": "PERPETUAL",
                        "quoteAsset": "USDT",
                        "isSpotTradingAllowed": True,
                    }
                ]
            }
        )
        return executor

    @pytest.fixture
    def reset_global_registry(self):
        """Clears the global registry before and after the test."""
        from bot_module.data_consumer import _global_kline_cache, _global_kline_df_cache

        for entry in list(_global_ws_registry.values()):
            task = entry.get("task")
            if task and not task.done():
                task.cancel()
        _global_ws_registry.clear()
        _global_event_queues.clear()
        _global_kline_cache.clear()
        _global_kline_df_cache.clear()
        yield
        for entry in list(_global_ws_registry.values()):
            task = entry.get("task")
            if task and not task.done():
                task.cancel()
        _global_ws_registry.clear()
        _global_event_queues.clear()
        _global_kline_cache.clear()
        _global_kline_df_cache.clear()

    @pytest.mark.asyncio
    async def test_subscription_ref_count_increases(
        self, mock_executor, reset_global_registry, monkeypatch
    ):
        """
        When two DataConsumers subscribe to the same stream,
        ref_count should increase instead of creating a new WebSocket.
        """

        # Patch history loading and WebSocket creation
        async def mock_ensure_history(*args, **kwargs):
            return True

        async def mock_ws_loop(*args, **kwargs):
            while True:
                await asyncio.sleep(1)

        monkeypatch.setattr(DataConsumer, "_ensure_history_loaded", mock_ensure_history)
        monkeypatch.setattr(DataConsumer, "_binance_data_ws_loop", mock_ws_loop)
        monkeypatch.setattr(config, "TRADING_MARKET_TYPE", "futures_usdtm")
        monkeypatch.setattr(config, "USE_COMPANION_ORDERBOOK_ANALYSIS", False)
        monkeypatch.setattr(
            config,
            "BINANCE_FUTURES_USDTM_MAINNET_MARKET_DATA_WS_URL",
            "wss://fstream.binance.com/ws",
        )
        monkeypatch.setattr(config, "ACTIVE_TRADING_ENVIRONMENT", "mainnet")

        loop = asyncio.get_event_loop()

        # Creating two DataConsumers (as for two users)
        consumer1 = DataConsumer(loop=loop, executor=mock_executor)
        consumer2 = DataConsumer(loop=loop, executor=mock_executor)

        # First one subscribes
        await consumer1.ensure_subscription("kline_1m", "BTCUSDT")

        # Check that the record is created with ref_count = 1
        stream_key = "binance:futures_usdtm:btcusdt@kline_1m"
        assert stream_key in _global_ws_registry, (
            f"Record {stream_key} should be created in the global registry. Available: {list(_global_ws_registry.keys())}"
        )
        assert _global_ws_registry[stream_key]["ref_count"] == 1, (
            "ref_count should be 1 after the first subscription"
        )

        # The second one subscribes to the same stream
        await consumer2.ensure_subscription("kline_1m", "BTCUSDT")

        # ref_count must increase to 2
        assert _global_ws_registry[stream_key]["ref_count"] == 2, (
            "ref_count must increase to 2"
        )

        # There should be only one WebSocket task
        assert (
            len([k for k in _global_ws_registry.keys() if "btcusdt@kline_1m" in k]) == 1
        ), "There should be only one entry in the registry, not two"

    @pytest.mark.asyncio
    async def test_subscription_ref_count_decreases(
        self, mock_executor, reset_global_registry, monkeypatch
    ):
        """
        Upon unsubscription, ref_count decreases. The WebSocket closes only when ref_count = 0.
        """

        async def mock_ensure_history(*args, **kwargs):
            return True

        async def mock_ws_loop(*args, **kwargs):
            try:
                while True:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass

        monkeypatch.setattr(DataConsumer, "_ensure_history_loaded", mock_ensure_history)
        monkeypatch.setattr(DataConsumer, "_binance_data_ws_loop", mock_ws_loop)
        monkeypatch.setattr(config, "TRADING_MARKET_TYPE", "futures_usdtm")
        monkeypatch.setattr(config, "USE_COMPANION_ORDERBOOK_ANALYSIS", False)
        monkeypatch.setattr(
            config,
            "BINANCE_FUTURES_USDTM_MAINNET_MARKET_DATA_WS_URL",
            "wss://fstream.binance.com/ws",
        )
        monkeypatch.setattr(config, "ACTIVE_TRADING_ENVIRONMENT", "mainnet")

        loop = asyncio.get_event_loop()

        consumer1 = DataConsumer(loop=loop, executor=mock_executor)
        consumer2 = DataConsumer(loop=loop, executor=mock_executor)

        stream_key = "binance:futures_usdtm:btcusdt@kline_1m"

        # Both subscribe
        await consumer1.ensure_subscription("kline_1m", "BTCUSDT")
        await consumer2.ensure_subscription("kline_1m", "BTCUSDT")

        assert _global_ws_registry[stream_key]["ref_count"] == 2

        # First one unsubscribes
        await consumer1.remove_subscription("kline_1m", "BTCUSDT")

        # ref_count should decrease to 1, WebSocket should remain
        assert stream_key in _global_ws_registry, (
            "The record must remain in the registry"
        )
        assert _global_ws_registry[stream_key]["ref_count"] == 1, (
            "ref_count must decrease to 1"
        )

        # Second one unsubscribes
        await consumer2.remove_subscription("kline_1m", "BTCUSDT")

        # Now the record must be deleted
        assert stream_key not in _global_ws_registry, (
            "Record should be deleted when ref_count = 0"
        )

    @pytest.mark.asyncio
    async def test_event_broadcast_to_all_queues(
        self, mock_executor, reset_global_registry, monkeypatch
    ):
        """
        CRITICAL TEST: When two users are subscribed to the same stream,
        events must be broadcast to BOTH of their queues, not just one.
        """

        async def mock_ensure_history(*args, **kwargs):
            return True

        async def mock_ws_loop(*args, **kwargs):
            while True:
                await asyncio.sleep(1)

        monkeypatch.setattr(DataConsumer, "_ensure_history_loaded", mock_ensure_history)
        monkeypatch.setattr(DataConsumer, "_binance_data_ws_loop", mock_ws_loop)
        monkeypatch.setattr(config, "TRADING_MARKET_TYPE", "futures_usdtm")
        monkeypatch.setattr(config, "USE_COMPANION_ORDERBOOK_ANALYSIS", False)
        monkeypatch.setattr(
            config,
            "BINANCE_FUTURES_USDTM_MAINNET_MARKET_DATA_WS_URL",
            "wss://fstream.binance.com/ws",
        )
        monkeypatch.setattr(config, "ACTIVE_TRADING_ENVIRONMENT", "mainnet")

        loop = asyncio.get_event_loop()

        # Create two queues — for each user
        queue1 = asyncio.Queue()
        queue2 = asyncio.Queue()

        # Create two DataConsumer with different queues
        consumer1 = DataConsumer(loop=loop, executor=mock_executor, event_queue=queue1)
        consumer2 = DataConsumer(loop=loop, executor=mock_executor, event_queue=queue2)

        # Both subscribe to the same stream
        await consumer1.ensure_subscription("kline_1m", "BTCUSDT")
        await consumer2.ensure_subscription("kline_1m", "BTCUSDT")

        stream_key = "binance:futures_usdtm:btcusdt@kline_1m"

        # Checking that both queues are registered for broadcast
        assert stream_key in _global_event_queues, (
            "stream_key should be in _global_event_queues"
        )
        assert queue1 in _global_event_queues[stream_key], "queue1 must be registered"
        assert queue2 in _global_event_queues[stream_key], "queue2 must be registered"
        assert len(_global_event_queues[stream_key]) == 2, (
            "There must be exactly 2 queues"
        )

        # Simulating event receipt via _update_local_cache
        test_payload = {
            "e": "kline",
            "k": {
                "t": 1699999999000,
                "o": "100.0",
                "h": "101.0",
                "l": "99.0",
                "c": "100.5",
                "v": "1000.0",
                "x": True,  # Candle is closed
            },
        }

        # Call _update_local_cache directly (simulates receiving data from WebSocket)
        await consumer1._update_local_cache(
            "kline_1m", "BTCUSDT", test_payload, market_type="futures_usdtm"
        )

        # Check that BOTH queues received the event!
        assert not queue1.empty(), "queue1 should receive an event"
        assert not queue2.empty(), "queue2 should receive an event"

        event1 = queue1.get_nowait()
        event2 = queue2.get_nowait()

        assert event1["type"] == "CANDLE_CLOSE", "Event type must be CANDLE_CLOSE"
        assert event2["type"] == "CANDLE_CLOSE", "Event type must be CANDLE_CLOSE"
        assert event1["symbol"] == "BTCUSDT", "Symbol must be BTCUSDT"
        assert event2["symbol"] == "BTCUSDT", "Symbol must be BTCUSDT"

    @pytest.mark.asyncio
    async def test_stream_survives_creator_consumer_stop_for_other_subscribers(
        self, mock_executor, reset_global_registry, monkeypatch
    ):
        async def mock_ensure_history(*args, **kwargs):
            return True

        async def mock_valid_symbols(*args, **kwargs):
            return {"BTCUSDT"}

        async def noop_recalculate(*args, **kwargs):
            return None

        monkeypatch.setattr(DataConsumer, "_ensure_history_loaded", mock_ensure_history)
        monkeypatch.setattr(
            DataConsumer, "_get_valid_symbols_from_exchange_info", mock_valid_symbols
        )
        monkeypatch.setattr(
            DataConsumer, "_recalculate_kline_indicators", noop_recalculate
        )
        monkeypatch.setattr(config, "TRADING_MARKET_TYPE", "futures_usdtm")
        monkeypatch.setattr(config, "USE_COMPANION_ORDERBOOK_ANALYSIS", False)
        monkeypatch.setattr(
            config,
            "BINANCE_FUTURES_USDTM_MAINNET_MARKET_DATA_WS_URL",
            "wss://fstream.binance.com/ws",
        )
        monkeypatch.setattr(config, "ACTIVE_TRADING_ENVIRONMENT", "mainnet")

        queue1 = asyncio.Queue()
        queue2 = asyncio.Queue()
        fake_ws = QueueBackedWebSocket()

        with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = fake_ws

            consumer1 = DataConsumer(
                loop=asyncio.get_event_loop(),
                executor=mock_executor,
                event_queue=queue1,
            )
            consumer2 = DataConsumer(
                loop=asyncio.get_event_loop(),
                executor=mock_executor,
                event_queue=queue2,
            )
            consumer1._running = True
            consumer2._running = True

            await consumer1.ensure_subscription("kline_1m", "BTCUSDT")
            for _ in range(20):
                if mock_connect.await_count:
                    break
                await asyncio.sleep(0.01)
            await consumer2.ensure_subscription("kline_1m", "BTCUSDT")

            first_payload = {
                "e": "kline",
                "k": {
                    "t": 1699999999000,
                    "o": "100",
                    "h": "101",
                    "l": "99",
                    "c": "100.5",
                    "v": "1000",
                    "x": True,
                },
            }
            await fake_ws.push_json(first_payload)
            assert (await asyncio.wait_for(queue1.get(), timeout=1))[
                "type"
            ] == "CANDLE_CLOSE"
            assert (await asyncio.wait_for(queue2.get(), timeout=1))[
                "type"
            ] == "CANDLE_CLOSE"

            await consumer1.clear_all_subscriptions()
            await consumer1.stop()

            stream_key = "binance:futures_usdtm:btcusdt@kline_1m"
            assert stream_key in _global_ws_registry
            assert _global_ws_registry[stream_key]["ref_count"] == 1

            second_payload = {
                "e": "kline",
                "k": {
                    "t": 1700000059000,
                    "o": "101",
                    "h": "102",
                    "l": "100",
                    "c": "101.5",
                    "v": "900",
                    "x": True,
                },
            }
            await fake_ws.push_json(second_payload)
            event2 = await asyncio.wait_for(queue2.get(), timeout=1)

            assert event2["type"] == "CANDLE_CLOSE"
            assert event2["symbol"] == "BTCUSDT"
            assert event2["timestamp_ms"] == 1700000059000
            assert queue1.empty()

            await consumer2.clear_all_subscriptions()
            await consumer2.stop()

    @pytest.mark.asyncio
    async def test_redis_market_payload_updates_local_cache_and_event_queue(
        self, mock_executor, reset_global_registry
    ):
        queue = asyncio.Queue()
        consumer = DataConsumer(
            loop=asyncio.get_event_loop(),
            executor=mock_executor,
            event_queue=queue,
            market_data_mode="redis",
        )
        stream_key = "binance:futures_usdtm:btcusdt@kline_1m"
        consumer._redis_market_stream_keys.add(stream_key)
        consumer._recalculate_kline_indicators = AsyncMock()

        await consumer._handle_redis_market_payload(
            {
                "type": "market_payload",
                "stream_key": stream_key,
                "data_type_key": "kline_1m",
                "symbol": "BTCUSDT",
                "market_type": "futures_usdtm",
                "exchange_id": "binance",
                "payload": {
                    "e": "kline",
                    "k": {
                        "t": 1700000000000,
                        "o": "100",
                        "h": "101",
                        "l": "99",
                        "c": "100.5",
                        "v": "10",
                        "x": True,
                    },
                },
            }
        )

        event = queue.get_nowait()
        assert event["type"] == "CANDLE_CLOSE"
        assert event["symbol"] == "BTCUSDT"
        df = await consumer.get_kline_history(
            "BTCUSDT", "1m", market_type="futures_usdtm"
        )
        assert df is not None
        assert df["close"].iloc[-1] == 100.5
        consumer._recalculate_kline_indicators.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_market_data_service_refcounts_redis_subscribers(
        self, reset_global_registry
    ):
        service = MarketDataService.__new__(MarketDataService)
        service._stream_subscribers = defaultdict(set)
        service._stream_specs = {}

        consumer = AsyncMock()
        service.consumer = consumer

        command_a = {
            "type": "subscribe",
            "subscriber_id": "worker-a",
            "stream_keys": [
                {
                    "stream_key": "binance:futures_usdtm:btcusdt@kline_1m",
                    "data_type_key": "kline_1m",
                    "symbol": "BTCUSDT",
                    "market_type": "futures_usdtm",
                    "exchange_id": "binance",
                }
            ],
        }
        command_b = dict(command_a, subscriber_id="worker-b")

        await service._handle_subscribe(command_a)
        await service._handle_subscribe(command_b)

        consumer.ensure_subscription.assert_awaited_once_with(
            "kline_1m",
            "BTCUSDT",
            needs_companion_orderbook=False,
            market_type="futures_usdtm",
        )
        assert service._stream_subscribers[
            "binance:futures_usdtm:btcusdt@kline_1m"
        ] == {"worker-a", "worker-b"}

        await service._handle_unsubscribe(
            {
                "type": "unsubscribe",
                "subscriber_id": "worker-a",
                "stream_keys": command_a["stream_keys"],
            }
        )
        consumer.remove_subscription.assert_not_awaited()

        await service._handle_unsubscribe(
            {
                "type": "unsubscribe",
                "subscriber_id": "worker-b",
                "stream_keys": command_a["stream_keys"],
            }
        )
        consumer.remove_subscription.assert_awaited_once_with(
            "kline_1m", "BTCUSDT", market_type="futures_usdtm"
        )

    @pytest.mark.asyncio
    async def test_market_data_service_merges_required_metrics_for_central_indicator_calc(
        self, reset_global_registry
    ):
        service = MarketDataService.__new__(MarketDataService)
        service._stream_subscribers = defaultdict(set)
        service._stream_specs = {}
        service.redis = FakeRedisSnapshotClient()

        consumer = AsyncMock()
        consumer._metrics_lock = asyncio.Lock()
        consumer._required_metrics = defaultdict(set)
        consumer._recalculate_kline_indicators = AsyncMock()
        service.consumer = consumer

        command = {
            "type": "subscribe",
            "subscriber_id": "worker-a",
            "required_metrics": ["RSI_14", "ATR_14"],
            "stream_keys": [
                {
                    "stream_key": "binance:futures_usdtm:btcusdt@kline_1m",
                    "data_type_key": "kline_1m",
                    "symbol": "BTCUSDT",
                    "market_type": "futures_usdtm",
                    "exchange_id": "binance",
                }
            ],
        }

        await service._handle_subscribe(command)

        assert consumer._required_metrics["BTCUSDT"] == {"RSI_14", "ATR_14"}
        consumer.ensure_subscription.assert_awaited_once_with(
            "kline_1m",
            "BTCUSDT",
            required_metrics={"RSI_14", "ATR_14"},
            needs_companion_orderbook=False,
            market_type="futures_usdtm",
        )
        consumer._recalculate_kline_indicators.assert_awaited_once_with(
            "BTCUSDT",
            "1m",
            market_type="futures_usdtm",
            exchange_id="binance",
        )

    @pytest.mark.asyncio
    async def test_redis_indicator_update_applies_central_pair_state(
        self, mock_executor, reset_global_registry
    ):
        consumer = DataConsumer(
            loop=asyncio.get_event_loop(),
            executor=mock_executor,
            event_queue=asyncio.Queue(),
            market_data_mode="redis",
        )
        stream_key = "binance:futures_usdtm:btcusdt@kline_1m"
        consumer._redis_market_stream_keys.add(stream_key)

        await consumer._handle_redis_market_payload(
            {
                "type": "indicator_update",
                "stream_key": stream_key,
                "data_type_key": "kline_1m",
                "symbol": "BTCUSDT",
                "market_type": "futures_usdtm",
                "exchange_id": "binance",
                "indicators": {"rsi_14": 55.5, "atr": 12.25},
            }
        )

        pair_info = await consumer.get_active_pair_by_symbol("BTCUSDT")
        assert pair_info is not None
        assert pair_info["rsi_14"] == 55.5
        assert pair_info["atr"] == 12.25

    @pytest.mark.asyncio
    async def test_redis_subscription_loads_shared_kline_snapshot_without_local_history(
        self, mock_executor, reset_global_registry, monkeypatch
    ):
        stream_key = "binance:futures_usdtm:btcusdt@kline_1m"
        snapshot = {
            "type": "market_snapshot",
            "stream_key": stream_key,
            "data_type_key": "kline_1m",
            "symbol": "BTCUSDT",
            "market_type": "futures_usdtm",
            "exchange_id": "binance",
            "rows": [[1700000000000, 100, 101, 99, 100.5, 10]],
            "pair_state": {"rsi_14": 61.0, "atr": 2.5},
        }
        consumer = DataConsumer(
            loop=asyncio.get_event_loop(),
            executor=mock_executor,
            event_queue=asyncio.Queue(),
            market_data_mode="redis",
        )
        consumer._redis_market_client = FakeRedisSnapshotClient(snapshot)
        consumer._redis_market_pubsub = FakePubSub()
        consumer._ensure_history_loaded = AsyncMock(
            side_effect=AssertionError("worker must not download history in redis mode")
        )
        monkeypatch.setattr(config, "MARKET_DATA_REDIS_SNAPSHOT_WAIT_SECONDS", 0)

        try:
            await consumer.ensure_subscription(
                "kline_1m", "BTCUSDT", market_type="futures_usdtm"
            )

            consumer._ensure_history_loaded.assert_not_awaited()
            df = await consumer.get_kline_history(
                "BTCUSDT", "1m", market_type="futures_usdtm"
            )
            assert df is not None
            assert df["close"].iloc[-1] == 100.5
            pair_info = await consumer.get_active_pair_by_symbol("BTCUSDT")
            assert pair_info["rsi_14"] == 61.0
            assert pair_info["atr"] == 2.5
            assert consumer._redis_market_client.published[0][1]["type"] == "subscribe"
        finally:
            consumer._running = True
            await consumer.stop()

    @pytest.mark.asyncio
    async def test_market_data_service_writes_kline_snapshot_to_redis(
        self, reset_global_registry, monkeypatch
    ):
        service = MarketDataService.__new__(MarketDataService)
        service.redis = FakeRedisSnapshotClient()
        service.consumer = AsyncMock()
        monkeypatch.setattr(config, "MARKET_DATA_REDIS_SNAPSHOT_TTL_SECONDS", 123)

        cache_key = "binance:futures_usdtm:BTCUSDT:1m"
        async with _global_cache_lock:
            _global_kline_cache[cache_key].clear()
            _global_kline_cache[cache_key].extend(
                [
                    (1700000000000, 100.0, 101.0, 99.0, 100.5, 10.0),
                    (1700000060000, 100.5, 102.0, 100.0, 101.5, 12.0),
                ]
            )
        async with _global_pairs_lock:
            _global_active_pairs["BTCUSDT"].update({"rsi_14": 58.0, "atr": 1.25})

        ok = await service._write_snapshot_for_spec(
            {
                "stream_key": "binance:futures_usdtm:btcusdt@kline_1m",
                "data_type_key": "kline_1m",
                "symbol": "BTCUSDT",
                "market_type": "futures_usdtm",
                "exchange_id": "binance",
            }
        )

        assert ok is True
        assert service.redis.set_calls
        _key, payload, ttl = service.redis.set_calls[0]
        assert ttl == 123
        assert payload["type"] == "market_snapshot"
        assert payload["rows"][-1][4] == 101.5
        assert payload["pair_state"]["rsi_14"] == 58.0
        assert payload["pair_state"]["atr"] == 1.25

    @pytest.mark.asyncio
    async def test_redis_command_service_snapshot_worker_load_flow(
        self, mock_executor, reset_global_registry, monkeypatch
    ):
        bus = InMemoryRedisBus()
        service = MarketDataService.__new__(MarketDataService)
        service.redis = bus.client()
        service.pubsub = bus.client().pubsub()
        service._stream_subscribers = defaultdict(set)
        service._stream_specs = {}
        consumer_for_service = AsyncMock()
        consumer_for_service._metrics_lock = asyncio.Lock()
        consumer_for_service._required_metrics = defaultdict(set)
        consumer_for_service._recalculate_kline_indicators = AsyncMock()
        service.consumer = consumer_for_service

        cache_key = "binance:futures_usdtm:BTCUSDT:1m"
        async with _global_cache_lock:
            _global_kline_cache[cache_key].clear()
            _global_kline_cache[cache_key].extend(
                [
                    (1700000000000, 100.0, 101.0, 99.0, 100.5, 10.0),
                    (1700000060000, 100.5, 102.0, 100.0, 101.5, 12.0),
                ]
            )
        async with _global_pairs_lock:
            _global_active_pairs["BTCUSDT"].update({"rsi_14": 63.0, "atr": 1.5})

        worker = DataConsumer(
            loop=asyncio.get_event_loop(),
            executor=mock_executor,
            event_queue=asyncio.Queue(),
            market_data_mode="redis",
        )
        worker._redis_market_client = bus.client()
        worker._redis_market_pubsub = bus.client().pubsub()
        worker._ensure_history_loaded = AsyncMock(
            side_effect=AssertionError("worker must not download history in redis mode")
        )
        monkeypatch.setattr(config, "MARKET_DATA_REDIS_SNAPSHOT_WAIT_SECONDS", 1.0)

        stop_event = asyncio.Event()
        ready_event = asyncio.Event()
        service_task = asyncio.create_task(
            run_market_data_command_loop_once_ready(service, stop_event, ready_event)
        )
        await asyncio.wait_for(ready_event.wait(), timeout=1)
        try:
            await worker.ensure_subscription(
                "kline_1m",
                "BTCUSDT",
                required_metrics={"RSI_14", "ATR_14"},
                market_type="futures_usdtm",
            )

            worker._ensure_history_loaded.assert_not_awaited()
            consumer_for_service.ensure_subscription.assert_awaited_once_with(
                "kline_1m",
                "BTCUSDT",
                required_metrics={"RSI_14", "ATR_14"},
                needs_companion_orderbook=False,
                market_type="futures_usdtm",
            )
            df = await worker.get_kline_history(
                "BTCUSDT", "1m", market_type="futures_usdtm"
            )
            assert df is not None
            assert df["close"].iloc[-1] == 101.5
            pair_info = await worker.get_active_pair_by_symbol("BTCUSDT")
            assert pair_info["rsi_14"] == 63.0
            assert pair_info["atr"] == 1.5
        finally:
            worker._running = True
            await worker.stop()
            stop_event.set()
            await asyncio.gather(service_task, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_redis_two_workers_share_one_service_stream_and_receive_live_events(
        self, mock_executor, reset_global_registry, monkeypatch
    ):
        bus = InMemoryRedisBus()
        service = MarketDataService.__new__(MarketDataService)
        service.redis = bus.client()
        service.pubsub = bus.client().pubsub()
        service._stream_subscribers = defaultdict(set)
        service._stream_specs = {}
        consumer_for_service = AsyncMock()
        consumer_for_service._metrics_lock = asyncio.Lock()
        consumer_for_service._required_metrics = defaultdict(set)
        consumer_for_service._recalculate_kline_indicators = AsyncMock()
        service.consumer = consumer_for_service
        monkeypatch.setattr(config, "MARKET_DATA_REDIS_SNAPSHOT_WAIT_SECONDS", 0)

        queue1 = asyncio.Queue()
        queue2 = asyncio.Queue()
        worker1 = DataConsumer(
            loop=asyncio.get_event_loop(),
            executor=mock_executor,
            event_queue=queue1,
            market_data_mode="redis",
        )
        worker2 = DataConsumer(
            loop=asyncio.get_event_loop(),
            executor=mock_executor,
            event_queue=queue2,
            market_data_mode="redis",
        )
        worker1._redis_market_client = bus.client()
        worker1._redis_market_pubsub = bus.client().pubsub()
        worker2._redis_market_client = bus.client()
        worker2._redis_market_pubsub = bus.client().pubsub()

        stop_event = asyncio.Event()
        ready_event = asyncio.Event()
        service_task = asyncio.create_task(
            run_market_data_command_loop_once_ready(service, stop_event, ready_event)
        )
        await asyncio.wait_for(ready_event.wait(), timeout=1)
        try:
            await worker1.ensure_subscription(
                "kline_1m", "BTCUSDT", market_type="futures_usdtm"
            )
            await worker2.ensure_subscription(
                "kline_1m", "BTCUSDT", market_type="futures_usdtm"
            )

            for _ in range(40):
                subscribers = service._stream_subscribers.get(
                    "binance:futures_usdtm:btcusdt@kline_1m", set()
                )
                if len(subscribers) == 2:
                    break
                await asyncio.sleep(0.025)

            consumer_for_service.ensure_subscription.assert_awaited_once()
            assert service._stream_subscribers[
                "binance:futures_usdtm:btcusdt@kline_1m"
            ] == {
                worker1._market_data_subscriber_id,
                worker2._market_data_subscriber_id,
            }

            await service._publish_market_payload(
                {
                    "type": "market_payload",
                    "stream_key": "binance:futures_usdtm:btcusdt@kline_1m",
                    "data_type_key": "kline_1m",
                    "symbol": "BTCUSDT",
                    "market_type": "futures_usdtm",
                    "exchange_id": "binance",
                    "payload": {
                        "e": "kline",
                        "k": {
                            "t": 1700000120000,
                            "o": "101",
                            "h": "103",
                            "l": "100",
                            "c": "102.5",
                            "v": "15",
                            "x": True,
                        },
                    },
                }
            )

            event1 = await asyncio.wait_for(queue1.get(), timeout=1)
            event2 = await asyncio.wait_for(queue2.get(), timeout=1)
            assert event1["type"] == "CANDLE_CLOSE"
            assert event2["type"] == "CANDLE_CLOSE"
            df1 = await worker1.get_kline_history(
                "BTCUSDT", "1m", market_type="futures_usdtm"
            )
            df2 = await worker2.get_kline_history(
                "BTCUSDT", "1m", market_type="futures_usdtm"
            )
            assert df1["close"].iloc[-1] == 102.5
            assert df2["close"].iloc[-1] == 102.5
        finally:
            worker1._running = True
            worker2._running = True
            await worker1.stop()
            await worker2.stop()
            stop_event.set()
            await asyncio.gather(service_task, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_redis_unsubscribe_refcount_closes_stream_only_after_last_worker(
        self, mock_executor, reset_global_registry, monkeypatch
    ):
        bus = InMemoryRedisBus()
        service = MarketDataService.__new__(MarketDataService)
        service.redis = bus.client()
        service.pubsub = bus.client().pubsub()
        service._stream_subscribers = defaultdict(set)
        service._stream_specs = {}
        consumer_for_service = AsyncMock()
        consumer_for_service._metrics_lock = asyncio.Lock()
        consumer_for_service._required_metrics = defaultdict(set)
        consumer_for_service._recalculate_kline_indicators = AsyncMock()
        service.consumer = consumer_for_service
        monkeypatch.setattr(config, "MARKET_DATA_REDIS_SNAPSHOT_WAIT_SECONDS", 0)

        worker1 = DataConsumer(
            loop=asyncio.get_event_loop(),
            executor=mock_executor,
            event_queue=asyncio.Queue(),
            market_data_mode="redis",
        )
        worker2 = DataConsumer(
            loop=asyncio.get_event_loop(),
            executor=mock_executor,
            event_queue=asyncio.Queue(),
            market_data_mode="redis",
        )
        worker1._redis_market_client = bus.client()
        worker1._redis_market_pubsub = bus.client().pubsub()
        worker2._redis_market_client = bus.client()
        worker2._redis_market_pubsub = bus.client().pubsub()

        stream_key = "binance:futures_usdtm:btcusdt@kline_1m"
        stop_event = asyncio.Event()
        ready_event = asyncio.Event()
        service_task = asyncio.create_task(
            run_market_data_command_loop_once_ready(service, stop_event, ready_event)
        )
        await asyncio.wait_for(ready_event.wait(), timeout=1)
        try:
            await worker1.ensure_subscription(
                "kline_1m", "BTCUSDT", market_type="futures_usdtm"
            )
            await worker2.ensure_subscription(
                "kline_1m", "BTCUSDT", market_type="futures_usdtm"
            )
            for _ in range(40):
                if len(service._stream_subscribers.get(stream_key, set())) == 2:
                    break
                await asyncio.sleep(0.025)

            await worker1.clear_all_subscriptions()
            for _ in range(40):
                if service._stream_subscribers.get(stream_key) == {
                    worker2._market_data_subscriber_id
                }:
                    break
                await asyncio.sleep(0.025)
            consumer_for_service.remove_subscription.assert_not_awaited()
            assert service._stream_subscribers[stream_key] == {
                worker2._market_data_subscriber_id
            }

            await worker2.clear_all_subscriptions()
            for _ in range(40):
                if stream_key not in service._stream_subscribers:
                    break
                await asyncio.sleep(0.025)
            consumer_for_service.remove_subscription.assert_awaited_once_with(
                "kline_1m",
                "BTCUSDT",
                market_type="futures_usdtm",
            )
            assert stream_key not in service._stream_subscribers
        finally:
            worker1._running = True
            worker2._running = True
            await worker1.stop()
            await worker2.stop()
            stop_event.set()
            await asyncio.gather(service_task, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_global_cache_shared_between_consumers(
        self, mock_executor, reset_global_registry, monkeypatch
    ):
        """
        CRITICAL TEST: Data written by one DataConsumer must be
        visible to another DataConsumer via the global cache.
        """
        from bot_module.data_consumer import _global_kline_cache, _global_cache_lock

        async def mock_ensure_history(*args, **kwargs):
            return True

        async def mock_ws_loop(*args, **kwargs):
            while True:
                await asyncio.sleep(1)

        monkeypatch.setattr(DataConsumer, "_ensure_history_loaded", mock_ensure_history)
        monkeypatch.setattr(DataConsumer, "_binance_data_ws_loop", mock_ws_loop)
        monkeypatch.setattr(config, "TRADING_MARKET_TYPE", "futures_usdtm")
        monkeypatch.setattr(config, "USE_COMPANION_ORDERBOOK_ANALYSIS", False)
        monkeypatch.setattr(
            config,
            "BINANCE_FUTURES_USDTM_MAINNET_MARKET_DATA_WS_URL",
            "wss://fstream.binance.com/ws",
        )
        monkeypatch.setattr(config, "ACTIVE_TRADING_ENVIRONMENT", "mainnet")

        loop = asyncio.get_event_loop()

        # Create two DataConsumer (for two users)
        consumer1 = DataConsumer(loop=loop, executor=mock_executor)
        consumer2 = DataConsumer(loop=loop, executor=mock_executor)

        # Both subscribe
        await consumer1.ensure_subscription("kline_1m", "BTCUSDT")
        await consumer2.ensure_subscription("kline_1m", "BTCUSDT")

        # Consumer1 receives data and writes it to the global cache via _update_local_cache
        test_payload = {
            "e": "kline",
            "k": {
                "t": 1699999999000,
                "o": "100.0",
                "h": "101.0",
                "l": "99.0",
                "c": "100.5",
                "v": "1000.0",
                "x": False,  # Candle is NOT closed — to avoid recalculating indicators
            },
        }

        await consumer1._update_local_cache(
            "kline_1m", "BTCUSDT", test_payload, market_type="futures_usdtm"
        )

        # Consumer2 should see this data via get_kline_history!
        cache_key = "binance:futures_usdtm:BTCUSDT:1m"

        async with _global_cache_lock:
            global_cache_data = list(_global_kline_cache.get(cache_key, []))

        assert len(global_cache_data) > 0, "Global cache must contain data"
        assert global_cache_data[-1][0] == 1699999999000, "Timestamp must match"
        assert global_cache_data[-1][4] == 100.5, "Close price must be 100.5"

        # Now Consumer2 receives this data — checking that get_kline_history works
        df = await consumer2.get_kline_history("BTCUSDT", "1m")

        assert df is not None, "Consumer2 should receive data from the global cache"
        assert len(df) > 0, "DataFrame must not be empty"
        assert df["close"].iloc[-1] == 100.5, "Close price in DataFrame should be 100.5"


# ==============================================================================
# INTEGRATION TESTS
# ==============================================================================


class TestSubscriptionIntegration:
    """Integration tests to verify the entire subscription chain."""

    def test_complex_strategy_correct_requirements(self):
        """
        A complex strategy with different block types should
        correctly determine all necessary subscriptions.
        """
        complex_config = {
            "entryTrigger": {"type": "on_candle_close"},
            "conditions": {
                "type": "AND",
                "children": [
                    {"type": "trend_direction", "params": {"sma_fast_period": 10}},
                    {
                        "type": "order_book_zone",
                        "params": {"side": "bids", "range_value": 1.0},
                    },
                    {"type": "tape_analysis", "params": {"time_window_sec": 5}},
                    {"type": "significant_level", "params": {"lookback": 100}},
                ],
            },
        }

        strategy = VisualBuilderStrategy(
            params={"config": complex_config, "candle_timeframe": "5m"}
        )

        required = strategy.required_data_types

        # All necessary subscriptions must be present
        assert "kline_5m" in required, "Main timeframe"
        assert "depth" in required, "depth for order_book_zone"
        assert "aggTrade" in required, "aggTrade for tape_analysis"
        assert "kline_1h" in required, "kline_1h for significant_level"
        assert "kline_4h" in required, "kline_4h for significant_level"
        assert "kline_1d" in required, "kline_1d for significant_level"

        # Should require spot orderbook
        assert strategy.requires_spot_orderbook

    def test_empty_config_fallback(self):
        """Strategy without configuration should have minimal requirements."""
        strategy = VisualBuilderStrategy(params={"candle_timeframe": "1m"})

        required = strategy.required_data_types

        # There must be at least one kline
        assert any(r.startswith("kline_") for r in required), (
            "There must be at least one kline"
        )

        # Should not require spot orderbook
        assert not strategy.requires_spot_orderbook
