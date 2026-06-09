import pytest
import asyncio
import pandas as pd
import time
from unittest.mock import MagicMock, AsyncMock
import logging

from bot_module.controller import TradingController
from bot_module.exchanges import create_exchange_executor
from bot_module.risk_manager import RiskManager
from bot_module.strategy import create_strategy_instance

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


@pytest.fixture
def setup_testnet_env(e2e_exchange_profile):
    """Sets up environment variables for Testnet."""
    return e2e_exchange_profile


@pytest.fixture
async def e2e_controller_limited(setup_testnet_env, monkeypatch, ensure_testnet_ready):
    """Creates a TradingController with maxConcurrentTrades = 1."""
    monkeypatch.setattr(
        "bot_module.controller.crud.create_trade", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "bot_module.controller.crud.admin_get_user_details",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr("bot_module.controller.send_push_notification", MagicMock())

    import aiohttp

    session = aiohttp.ClientSession()
    exchange_profile = setup_testnet_env
    executor = create_exchange_executor(
        exchange=exchange_profile["exchange"],
        api_key=exchange_profile["api_key"],
        api_secret=exchange_profile["api_secret"],
        session=session,
        market_type=exchange_profile["market_type"],
    )
    await ensure_testnet_ready(executor, market_type=exchange_profile["market_type"])

    paper_executor = None

    # CRITICAL: Set maxConcurrentTrades to 1
    user_settings = {
        "risk_management": {
            "riskPerTradePercent": 1.0,
            "maxStopDistancePct": 10.0,
            "maxConcurrentTrades": 1,
        }
    }

    risk_manager = RiskManager(
        executor=executor,
        paper_executor=paper_executor,
        user_id=1,
        db_session=None,
        user_settings=user_settings,
    )

    from bot_module.data_consumer import DataConsumer

    class MockDataConsumer(DataConsumer):
        def __init__(self, loop, executor, event_queue, controller=None):
            self.loop = loop
            self.executor = executor
            self.event_queue = event_queue
            self.controller = controller
            self._pairs_data = {}
            self._running = False

        async def start(self):
            self._running = True

        async def stop(self):
            self._running = False

        async def clear_all_subscriptions(self):
            pass

        async def get_active_symbols(self):
            return set()

        async def get_latest_depth(self, symbol, market_type_requested=None):
            return None

        async def get_active_pair_by_symbol(self, symbol):
            return self._pairs_data.get(symbol)

        async def get_kline_history(
            self, symbol, timeframe, limit=None, **kwargs
        ):  # Added limit
            data = self._pairs_data.get(symbol)
            if not data:
                return pd.DataFrame()
            df = pd.DataFrame([data])
            if "timestamp_dt" in data:
                df["timestamp"] = data["timestamp_dt"]
                df.set_index("timestamp", inplace=True)
            price = data.get("last_price", 0.0)
            for col in ["open", "high", "low", "close"]:
                if col not in df.columns:
                    df[col] = price
            if "volume" not in df.columns:
                df["volume"] = 1000.0
            return df

        async def get_recent_trades(self, symbol, limit=None, **kwargs):
            return pd.DataFrame()  # Added limit

        async def get_open_interest(self, symbol):
            return None

        def update_pair_data(self, symbol, data):
            self._pairs_data[symbol] = data

        async def ensure_subscription(self, *args, **kwargs):
            pass  # Mock

        async def remove_all_subscriptions_for_symbol(self, *args):
            pass  # Mock

    controller = TradingController(
        loop=asyncio.get_running_loop(),
        data_consumer=MockDataConsumer,
        live_executor=executor,
        paper_executor=paper_executor,
        risk_manager=risk_manager,
        user_id=1,
    )
    controller.e2e_exchange_profile = exchange_profile

    try:
        await asyncio.wait_for(
            controller.executors["live"].start_user_data_stream(
                controller._handle_order_update
            ),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        pytest.fail("Timeout during user data stream startup in fixture.")

    yield controller

    # Teardown
    print(f"\n--- E2E Test Teardown: Starting at {time.time()} ---")

    # Cancel all open orders for both symbols used in tests
    print(f"[{time.time()}] Teardown: Cancelling all open orders...")
    cancel_tasks = [
        controller.executors["live"].cancel_all_open_orders(s)
        for s in ["BTCUSDT", "ETHUSDT", "LTCUSDT", "XRPUSDT"]
    ]
    await asyncio.gather(*cancel_tasks, return_exceptions=True)
    print(f"[{time.time()}] Teardown: Open orders cancellation complete.")

    async with controller._positions_dict_lock:
        active_positions_symbols = [
            str(k).split(":", 1)[-1] for k in controller._active_positions.keys()
        ]

    if active_positions_symbols:
        print(
            f"[{time.time()}] Teardown: Found active positions to close: {active_positions_symbols}"
        )
        close_tasks = [
            controller.close_position(s, "TEARDOWN_FIXTURE")
            for s in active_positions_symbols
        ]
        await asyncio.gather(
            *close_tasks, return_exceptions=True
        )  # Ensure exceptions don't block teardown
        print(f"[{time.time()}] Teardown: Active positions closure complete.")
    else:
        print(f"[{time.time()}] Teardown: No active positions found to close.")

    print(f"[{time.time()}] Teardown: Stopping controller and executors...")
    if controller._running:
        await controller.stop()
    else:
        await controller.executors["live"].stop_user_data_stream()
        await executor.close()
    print(f"[{time.time()}] Teardown: Controller and executors stopped.")

    print(f"[{time.time()}] Teardown: Closing aiohttp session...")
    await session.close()
    print(f"[{time.time()}] --- E2E Test Teardown: Finished at {time.time()} ---")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_max_concurrent_positions_limit(
    e2e_controller_limited: TradingController,
):
    controller = e2e_controller_limited

    # Setup strategy config
    strategy_json_config = {
        "name": "E2E Limit Test Strategy",
        "config_data": {
            "entryConditions": {
                "id": "entry",
                "type": "rsi_condition",
                "params": {"operator": "lt", "value": 100},
            },  # Always true for test
            "initialization": {
                "id": "init",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "percent_from_price",
                    "sl_value": 2,
                    "tp_type": "rr_multiplier",
                    "tp_value": 3,
                },
            },
        },
    }
    strategy_instance = create_strategy_instance(
        "VisualBuilderStrategy",
        params={
            "enabled": True,
            "config": strategy_json_config["config_data"],
            "min_total_foundation_weight_threshold": 0,
        },
    )

    # 1. Open First Position (BTCUSDT)
    print("\n[STEP 1] Opening first position: BTCUSDT")
    ticker = await controller.executors["live"].get_ticker_price("BTCUSDT")
    btc_price = float(ticker["price"])
    mock_btc = {
        "symbol": "BTCUSDT",
        "last_price": btc_price,
        "tick_size": 0.1,
        "atr": btc_price * 0.01,
        "RSI_14": 20,
        "current_candle_index": 0,
    }

    signal_btc, _, _ = await strategy_instance.check_signal(mock_btc, {})
    signal_btc.config_id = "btc_conf"

    async with controller.instances_lock:
        strategy_json_config["user_id"] = controller.user_id
        controller.running_strategy_instances["btc_conf"] = (
            strategy_instance,
            strategy_json_config,
        )

    # Use wait_for to avoid hanging
    try:
        await asyncio.wait_for(
            controller._process_signal(signal_btc, mock_btc), timeout=15.0
        )
    except asyncio.TimeoutError:
        pytest.fail("Timeout while processing BTC signal")

    # Wait for BTC to open
    btc_opened = False
    for _ in range(20):  # Reduced wait time
        await asyncio.sleep(1)
        async with controller._positions_dict_lock:
            pos = controller._active_position_get("BTCUSDT", "futures_usdtm")
            if pos and pos.status == "OPEN":
                btc_opened = True
                break

    assert btc_opened, "BTCUSDT failed to open position"
    print("[STEP 1] BTCUSDT Opened successfully")

    # 2. Attempt Second Position (ETHUSDT)
    print("\n[STEP 2] Attempting second position: ETHUSDT (Should be BLOCKED)")
    ticker_eth = await controller.executors["live"].get_ticker_price("ETHUSDT")
    eth_price = float(ticker_eth["price"])
    mock_eth = {
        "symbol": "ETHUSDT",
        "last_price": eth_price,
        "tick_size": 0.01,
        "atr": eth_price * 0.01,
        "RSI_14": 20,
        "current_candle_index": 0,
    }

    signal_eth, _, _ = await strategy_instance.check_signal(mock_eth, {})
    signal_eth.config_id = "eth_conf"

    async with controller.instances_lock:
        controller.running_strategy_instances["eth_conf"] = (
            strategy_instance,
            strategy_json_config,
        )

    # Process signal
    try:
        await asyncio.wait_for(
            controller._process_signal(signal_eth, mock_eth), timeout=5.0
        )
    except asyncio.TimeoutError:
        # If it timed out, maybe it was blocked but didn't return?
        # But rejection should be fast (no API call).
        print(
            "Warning: ETH signal processing timed out (this might be okay if it was just slow logging)"
        )

    # Wait a bit to verify it DOES NOT open
    await asyncio.sleep(3)

    async with controller._positions_dict_lock:
        pos_eth = controller._active_position_get("ETHUSDT", "futures_usdtm")
        pos_btc = controller._active_position_get("BTCUSDT", "futures_usdtm")

        print(f"Active positions: {list(controller._active_positions.keys())}")

        assert pos_btc is not None, "BTCUSDT should still be open"
        assert pos_eth is None, (
            "ETHUSDT should NOT be in active positions because maxConcurrentTrades=1"
        )

    print("[STEP 2] SUCCESS: ETHUSDT was blocked")

    # Cleanup
    await controller.close_position("BTCUSDT", "TEST_END")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_max_concurrent_positions_limit_race_condition(
    e2e_controller_limited: TradingController,
):
    """
    Tests that the concurrency limit holds even when two signals arrive simultaneously.
    maxConcurrentTrades is set to 1 in the fixture.
    """
    controller = e2e_controller_limited

    # Setup strategy config
    strategy_json_config = {
        "name": "E2E Race Strategy",
        "config_data": {
            "entryConditions": {
                "id": "entry",
                "type": "rsi_condition",
                "params": {"operator": "lt", "value": 100},
            },
            "initialization": {
                "id": "init",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "percent_from_price",
                    "sl_value": 2,
                    "tp_type": "rr_multiplier",
                    "tp_value": 3,
                },
            },
        },
    }

    strategy_instance = create_strategy_instance(
        "VisualBuilderStrategy",
        params={
            "enabled": True,
            "config": strategy_json_config["config_data"],
            "min_total_foundation_weight_threshold": 0,
        },
    )

    # Prepare two signals
    symbols = ["LTCUSDT", "XRPUSDT"]
    signals = []
    infos = []

    print(f"\n[RACE TEST] Attempting to open {symbols} simultaneously with limit=1")

    for sym in symbols:
        # Mock ticker and pair info
        ticker = await controller.executors["live"].get_ticker_price(sym)
        price = float(ticker["price"])
        pair_info = {
            "symbol": sym,
            "last_price": price,
            "tick_size": 0.01,
            "atr": price * 0.01,
            "RSI_14": 20,
            "current_candle_index": 0,
        }

        # Generate signal
        sig, _, _ = await strategy_instance.check_signal(pair_info, {})
        sig.config_id = f"conf_{sym}"

        # Register instance
        async with controller.instances_lock:
            strategy_json_config["user_id"] = controller.user_id
            controller.running_strategy_instances[sig.config_id] = (
                strategy_instance,
                strategy_json_config,
            )

        signals.append(sig)
        infos.append(pair_info)

    # Fire both signals concurrently
    # We use gather to run them "at the same time"
    await asyncio.gather(
        *(controller._process_signal(sig, info) for sig, info in zip(signals, infos))
    )

    # Wait for processing to settle
    await asyncio.sleep(5)

    # Verify results
    async with controller._positions_dict_lock:
        open_positions = [
            p for p in controller._active_positions.values() if p.status == "OPEN"
        ]
        open_symbols = [p.symbol for p in open_positions]
        print(f"[RACE TEST] Resulting open positions: {open_symbols}")

        assert len(open_positions) == 1, (
            f"Expected exactly 1 position to open, but found {len(open_positions)}: {open_symbols}"
        )
        assert open_symbols[0] in symbols, (
            f"Opened position {open_symbols[0]} is not one of the test symbols"
        )

    # Cleanup
    for sym in open_symbols:
        await controller.close_position(sym, "RACE_TEST_END")
