import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
import logging
import pandas as pd

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
    print("\n--- E2E Race Test Teardown ---")
    cancel_tasks = [
        controller.executors["live"].cancel_all_open_orders(s)
        for s in ["LTCUSDT", "XRPUSDT"]
    ]
    await asyncio.gather(*cancel_tasks, return_exceptions=True)

    async with controller._positions_dict_lock:
        active_positions_symbols = [
            str(k).split(":", 1)[-1] for k in controller._active_positions.keys()
        ]
        if active_positions_symbols:
            close_tasks = [
                controller.close_position(s, "TEARDOWN")
                for s in active_positions_symbols
            ]
            await asyncio.gather(*close_tasks)

    if controller._running:
        await controller.stop()
    else:
        await controller.executors["live"].stop_user_data_stream()
        await executor.close()
    await session.close()


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

    # Cleanup is handled by fixture teardown, but explicit cleanup is safer for race test
    for sym in open_symbols:
        await controller.close_position(sym, "RACE_TEST_END")
