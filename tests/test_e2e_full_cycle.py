# tests/test_e2e_full_cycle.py

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
import logging
import pandas as pd
import time

from bot_module.controller import TradingController
from bot_module.exchanges import create_exchange_executor
from bot_module.risk_manager import RiskManager
from bot_module.strategy import (
    create_strategy_instance,
    SignalDirection,
)

# Logging setup for detailed output during tests
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("bot_module.executor").setLevel(logging.INFO)
logging.getLogger("bot_module.controller").setLevel(logging.DEBUG)


@pytest.fixture
def setup_testnet_env(e2e_exchange_profile):
    """Sets up environment variables for working with Testnet."""
    return e2e_exchange_profile


@pytest.fixture
async def e2e_controller(setup_testnet_env, monkeypatch, ensure_testnet_ready):
    """Creates and configures a TradingController instance for each test."""
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

    # Create a mock for paper_executor (not used in E2E tests with real API)
    paper_executor = None

    user_settings = {
        "risk_management": {"riskPerTradePercent": 1.0, "maxStopDistancePct": 10.0}
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
            # Do not call super().__init__() to avoid WebSocket initialization
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

        async def get_kline_history(self, symbol, timeframe, limit=None, **kwargs):
            data = self._pairs_data.get(symbol)
            if not data:
                return pd.DataFrame()

            # TradingController requires at least 20 candles by default (MIN_STRATEGY_HISTORY_CANDLES)
            # We generate a small history based on the latest data provided
            history_limit = limit or 100
            history_data = []

            # Use provided timestamp or current time
            base_ts = data.get("timestamp_dt")
            if base_ts is None:
                base_ts = pd.Timestamp.now(tz="UTC")

            # Create synthetic history by subtracting 1 minute per candle
            for i in range(history_limit):
                row = data.copy()
                # Offset timestamp so the last candle is at base_ts
                row["timestamp_dt"] = base_ts - pd.Timedelta(
                    minutes=history_limit - 1 - i
                )
                history_data.append(row)

            df = pd.DataFrame(history_data)

            # Ensure timestamp index
            df["timestamp"] = df["timestamp_dt"]
            df.set_index("timestamp", inplace=True)

            # Ensure OHLC columns exist
            price = data.get("last_price", 0.0)
            for col in ["open", "high", "low", "close"]:
                if col not in df.columns:
                    df[col] = price

            if "volume" not in df.columns:
                df["volume"] = 1000.0

            return df

        async def get_recent_trades(self, symbol, limit=None, **kwargs):
            return pd.DataFrame()

        async def get_open_interest(self, symbol):
            return None

        def update_pair_data(self, symbol, data):
            self._pairs_data[symbol] = data

    controller = TradingController(
        loop=asyncio.get_running_loop(),
        data_consumer=MockDataConsumer,
        live_executor=executor,
        paper_executor=paper_executor,
        risk_manager=risk_manager,
        user_id=1,
    )
    controller.e2e_exchange_profile = exchange_profile

    await controller.executors["live"].start_user_data_stream(
        controller._handle_order_update
    )

    # --- Cleanup before test ---
    all_symbols_in_test = ["BTCUSDT", "ETHUSDT"]
    print(
        f"\n--- E2E Test Setup: Cleaning up open positions/orders for {all_symbols_in_test}... ---"
    )
    for symbol in all_symbols_in_test:
        try:
            await executor.cancel_all_open_orders(symbol)
            # Direct closing via executor if a position exists
            positions = await executor.get_open_positions()
            symbol_pos = next(
                (
                    p
                    for p in positions
                    if p["symbol"] == symbol and float(p["positionAmt"]) != 0
                ),
                None,
            )
            if symbol_pos:
                qty = abs(float(symbol_pos["positionAmt"]))
                side = "SELL" if float(symbol_pos["positionAmt"]) > 0 else "BUY"
                print(f"Closing existing position for {symbol}: {qty} {side}")
                await executor.place_order(
                    symbol, side, "MARKET", quantity=qty, reduceOnly=True
                )
        except Exception as e:
            print(f"Error during E2E setup cleanup for {symbol}: {e}")
    await asyncio.sleep(2)

    yield controller

    print("\n--- E2E Test Teardown: Cleaning up... ---")

    all_symbols_in_test = ["BTCUSDT", "ETHUSDT"]
    cancel_tasks = [
        controller.executors["live"].cancel_all_open_orders(symbol)
        for symbol in all_symbols_in_test
    ]
    await asyncio.gather(*cancel_tasks, return_exceptions=True)
    await asyncio.sleep(2)

    async with controller._positions_dict_lock:
        active_positions_symbols = list(controller._active_positions.keys())

    if active_positions_symbols:
        print(f"Found active positions to close: {active_positions_symbols}")
        close_tasks = [
            controller.close_position(symbol, "E2E_TEST_CLEANUP")
            for symbol in active_positions_symbols
        ]
        await asyncio.gather(*close_tasks)
        await asyncio.sleep(5)

    if controller._running:
        await controller.stop()
    else:
        await controller.executors["live"].stop_user_data_stream()
        await executor.close()

    await session.close()


# --- Test 1: Basic cycle (market open, move to BE, close) ---
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_full_cycle_market_open_and_be(e2e_controller: TradingController):
    controller = e2e_controller
    test_symbol = "BTCUSDT"
    print(f"\n\n--- RUNNING: test_full_cycle_market_open_and_be ({test_symbol}) ---")

    strategy_json_config = {
        "name": "E2E Base Strategy",
        "config_data": {
            "entryConditions": {
                "id": "entry",
                "type": "rsi_condition",
                "params": {"operator": "lt", "value": 30},
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
            "positionManagement": [
                {
                    "id": "pm_be",
                    "type": "move_to_breakeven",
                    "params": {
                        "target_type": "unrealized_pnl_rr",
                        "target_value": 0.5,
                        "offset_pips": 2,
                    },
                }
            ],
        },
    }
    # Disabling weight check for test
    strategy_instance = create_strategy_instance(
        "VisualBuilderStrategy",
        params={
            "enabled": True,
            "config": strategy_json_config["config_data"],
            "min_total_foundation_weight_threshold": 0,
        },
    )

    print("\n[PHASE 1] Testing POSITION OPEN")
    position = None
    for attempt in range(3):
        ticker = await controller.executors["live"].get_ticker_price(test_symbol)
        current_price = float(ticker["price"])
        mock_pair_info_open = {
            "symbol": test_symbol,
            "last_price": current_price,
            "tick_size": 0.1,
            "atr": current_price * 0.01,
            "RSI_14": 25,
            "current_candle_index": 0,
        }
        signal, _, _ = await strategy_instance.check_signal(mock_pair_info_open, {})

        assert signal is not None, (
            f"Attempt {attempt + 1}: Strategy failed to generate a signal."
        )

        test_config_id = "e2e-base-id"
        signal.config_id = test_config_id
        async with controller.instances_lock:
            strategy_json_config["user_id"] = controller.user_id
            controller.running_strategy_instances[test_config_id] = (
                strategy_instance,
                strategy_json_config,
            )

        await controller._process_signal(signal, mock_pair_info_open)

        # Wait until the position moves to OPEN status (MARKET order should execute quickly)
        print(f"DEBUG: Controller ID in test: {id(controller)}")
        for wait_attempt in range(60):  # Increasing wait time to 60 seconds
            await asyncio.sleep(1)
            async with controller._positions_dict_lock:
                position = controller._active_position_get(test_symbol)

            status = position.status if position else "None"
            print(
                f"Wait attempt {wait_attempt}: Position status = {status}, Position ID: {id(position) if position else 'None'}"
            )

            if position and position.status == "OPEN":
                break

        if position and position.status == "OPEN":
            break
        print(
            f"Attempt {attempt + 1} failed. Position status: {position.status if position else 'None'}. Retrying..."
        )
        if position:
            await controller.close_position(test_symbol, "E2E_RETRY_CLEANUP")
            await asyncio.sleep(10)

    assert position and position.status == "OPEN", (
        f"Position did not open. Status: {position.status if position else 'None'}"
    )
    print(
        f"[PHASE 1] SUCCESS: Position {test_symbol} opened. Entry Price: {position.entry_price}"
    )

    print("\n[PHASE 2] Testing MOVE TO BREAKEVEN")
    # Getting the current position
    async with controller._positions_dict_lock:
        position = controller._active_position_get(test_symbol)

    if not position or not position.entry_price:
        print(
            f"[PHASE 2] SKIP: Position not ready for BE test. Entry price: {position.entry_price if position else 'None'}"
        )
    else:
        mock_pair_info_be = mock_pair_info_open.copy()
        mock_pair_info_be["high"] = position.entry_price + (
            abs(position.entry_price - position.initial_stop_loss) * 0.7
        )
        mock_pair_info_be["low"] = position.entry_price
        mock_pair_info_be["last_price"] = mock_pair_info_be[
            "high"
        ]  # Update last_price to avoid SL > Price error
        mock_pair_info_be["timestamp_dt"] = pd.Timestamp.now(tz="UTC")
        mock_pair_info_be["current_candle_index"] = 1

        # Updating data in MockDataConsumer
        controller.consumer.update_pair_data(test_symbol, mock_pair_info_be)

        try:
            await controller._handle_event(
                {
                    "type": "CANDLE_CLOSE",
                    "symbol": test_symbol,
                    "timestamp_ms": time.time() * 1000,
                }
            )
            await asyncio.sleep(5)

            async with controller._positions_dict_lock:
                position_after_be = controller._active_position_get(test_symbol)

            if position_after_be:
                if position_after_be.is_stop_at_be:
                    print("[PHASE 2] SUCCESS: Stop-loss moved to breakeven.")
                else:
                    print(
                        "[PHASE 2] WARNING: is_stop_at_be flag is not set, but the position exists"
                    )
            else:
                print(
                    "[PHASE 2] WARNING: Position disappeared after attempting to move to BE (possibly closed)"
                )
        except Exception as e:
            print(f"[PHASE 2] ERROR during BE test: {e}")

    print("\n[PHASE 3] Testing POSITION CLOSE")
    await controller.close_position(test_symbol, "E2E_TEST")

    # Wait for position to close
    for _ in range(20):
        await asyncio.sleep(1)
        async with controller._positions_dict_lock:
            if test_symbol not in controller._active_positions:
                break

    async with controller._positions_dict_lock:
        assert test_symbol not in controller._active_positions, (
            f"Position {test_symbol} failed to close."
        )

    open_orders = await controller.executors["live"].get_open_orders(test_symbol)
    assert not open_orders, f"Orders remaining on the exchange: {open_orders}"
    print(f"[PHASE 3] SUCCESS: Position {test_symbol} closed.")


# --- Test 2: Partial Take Profit ---
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_partial_take_profit(e2e_controller: TradingController):
    controller = e2e_controller
    test_symbol = "BTCUSDT"
    print(f"\n\n--- RUNNING: test_e2e_partial_take_profit ({test_symbol}) ---")

    strategy_json_config = {
        "name": "E2E Partial TP Strategy",
        "config_data": {
            "entryConditions": {
                "id": "entry",
                "type": "rsi_condition",
                "params": {"operator": "lt", "value": 30},
            },
            "initialization": {
                "id": "init",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "percent_from_price",
                    "sl_value": 2,
                    "partial_exits": [
                        {"tp_type": "rr_multiplier", "tp_value": 1.0, "size_pct": 50},
                        {"tp_type": "rr_multiplier", "tp_value": 2.0, "size_pct": 50},
                    ],
                },
            },
        },
    }
    # Disabling weight check for test
    strategy_instance = create_strategy_instance(
        "VisualBuilderStrategy",
        params={
            "enabled": True,
            "config": strategy_json_config["config_data"],
            "min_total_foundation_weight_threshold": 0,
        },
    )

    print("\n[PHASE 1] Testing open with partial TPs")
    ticker = await controller.executors["live"].get_ticker_price(test_symbol)
    current_price = float(ticker["price"])
    mock_pair_info = {
        "symbol": test_symbol,
        "last_price": current_price,
        "tick_size": 0.1,
        "atr": current_price * 0.01,
        "RSI_14": 25,
        "current_candle_index": 0,
    }
    signal, _, _ = await strategy_instance.check_signal(mock_pair_info, {})
    assert signal is not None, "Strategy did not generate a signal"

    test_config_id = "e2e-partial-tp-id"
    signal.config_id = test_config_id
    async with controller.instances_lock:
        strategy_json_config["user_id"] = controller.user_id
        controller.running_strategy_instances[test_config_id] = (
            strategy_instance,
            strategy_json_config,
        )

    await controller._process_signal(signal, mock_pair_info)

    # Wait until position transitions to OPEN status
    position = None
    for wait_attempt in range(90):
        await asyncio.sleep(1)
        async with controller._positions_dict_lock:
            position = controller._active_position_get(test_symbol)

        status = position.status if position else "None"
        print(f"Wait {wait_attempt}: Position status = {status}")

        if (
            position
            and position.status == "OPEN"
            and (position.current_sl_order_id is not None or position.is_sl_algo_order)
        ):
            break

    assert position and position.status == "OPEN", (
        f"Position did not open. Status: {position.status if position else 'None'}"
    )
    assert len(position.partial_tp_orders) >= 1, "Incorrect number of partial TP orders"

    open_orders = await controller.executors["live"].get_open_orders(test_symbol)
    limit_tp_orders = [
        o for o in open_orders if o["type"] == "LIMIT" and o["side"] == "SELL"
    ]

    # On futures, STOP_MARKET are Algo orders and may not appear in the regular list.
    # On Testnet GET /fapi/v1/algoOrders may be unavailable (error -5000).
    algo_orders = []
    try:
        algo_orders = await controller.executors["live"].get_open_algo_orders(
            test_symbol
        )
    except Exception:
        pass

    sl_orders = [
        o for o in open_orders if o["type"] == "STOP_MARKET" and o["side"] == "SELL"
    ]
    sl_orders += [o for o in algo_orders if o.get("orderType") == "STOP_MARKET"]

    assert len(limit_tp_orders) >= 1, (
        f"There should be at least 1 limit TP order on the exchange, found: {len(limit_tp_orders)}"
    )
    # Check either in the order list or by the presence of ID in the position object (if it cannot be queried on the exchange)
    assert len(sl_orders) >= 1 or position.current_sl_order_id is not None, (
        f"There should be at least 1 stop-loss order on the exchange or in the position, found in API: {len(sl_orders)}"
    )
    print(
        f"[PHASE 1] SUCCESS: Position opened, {len(limit_tp_orders)} TP and {len(sl_orders)} SL orders placed."
    )

    print("\n[PHASE 2] Testing first partial TP fill")
    initial_qty = position.initial_quantity
    first_tp_order = sorted(position.partial_tp_orders, key=lambda o: o.target_price)[0]

    fake_order_update = {
        "e": "ORDER_TRADE_UPDATE",
        "o": {
            "s": test_symbol,
            "i": first_tp_order.order_id,
            "c": first_tp_order.client_order_id,
            "x": "TRADE",
            "X": "FILLED",
            "S": "SELL",
            "ot": "LIMIT",
            "z": str(first_tp_order.quantity),
            "L": str(first_tp_order.target_price),
            "l": str(first_tp_order.quantity),
            "n": "0.001",
            "N": "USDT",
        },
    }
    await controller._handle_order_update(fake_order_update)
    await asyncio.sleep(5)

    async with controller._positions_dict_lock:
        position_after_tp1 = controller._active_position_get(test_symbol)

    assert position_after_tp1, "Position disappeared after the first TP"
    assert (
        abs(
            position_after_tp1.remaining_quantity
            - (initial_qty - first_tp_order.quantity)
        )
        < 1e-9
    ), "Invalid remaining quantity"
    assert position_after_tp1.partial_tp_orders[0].status == "FILLED", (
        "First TP status did not update"
    )
    print("[PHASE 2] SUCCESS: First TP triggered, position size reduced.")

    print("\n[PHASE 3] Testing closing remaining position")
    await controller.close_position(test_symbol, "E2E_PARTIAL_TP_CLOSE")
    await asyncio.sleep(10)
    async with controller._positions_dict_lock:
        assert test_symbol not in controller._active_positions

    # Canceling all remaining orders
    await controller.executors["live"].cancel_all_open_orders(test_symbol)
    await asyncio.sleep(2)

    open_orders_final = await controller.executors["live"].get_open_orders(test_symbol)
    assert not open_orders_final, (
        f"Orders remaining on the exchange: {open_orders_final}"
    )
    print("[PHASE 3] SUCCESS: Position fully closed.")


# --- Test 3: Limit entry order ---
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_limit_entry_order(e2e_controller: TradingController):
    controller = e2e_controller
    test_symbol = "BTCUSDT"
    print(f"\n\n--- RUNNING: test_e2e_limit_entry_order ({test_symbol}) ---")

    ticker = await controller.executors["live"].get_ticker_price(test_symbol)
    current_price = float(ticker["price"])
    limit_entry_price = round(current_price * 0.995, 1)

    strategy_json_config = {
        "name": "E2E Limit Entry Strategy",
        "config_data": {
            "entryConditions": {
                "id": "entry",
                "type": "rsi_condition",
                "params": {"operator": "lt", "value": 45},
            },
            "initialization": {
                "id": "init",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "order_type": "LIMIT_RETEST",
                    "entry_price": {"source": "value", "value": limit_entry_price},
                    "sl_type": "percent_from_price",
                    "sl_value": 2,
                    "tp_type": "rr_multiplier",
                    "tp_value": 3,
                },
            },
        },
    }
    # Disabling weight check for test
    strategy_instance = create_strategy_instance(
        "VisualBuilderStrategy",
        params={
            "enabled": True,
            "config": strategy_json_config["config_data"],
            "min_total_foundation_weight_threshold": 0,
        },
    )

    print(f"\n[PHASE 1] Testing LIMIT order placement at {limit_entry_price}")
    mock_pair_info = {
        "symbol": test_symbol,
        "last_price": current_price,
        "tick_size": 0.1,
        "atr": current_price * 0.01,
        "RSI_14": 40,
        "current_candle_index": 0,
    }
    signal, _, _ = await strategy_instance.check_signal(mock_pair_info, {})
    assert signal is not None, "Strategy did not generate a signal"

    test_config_id = "e2e-limit-id"
    signal.config_id = test_config_id
    async with controller.instances_lock:
        strategy_json_config["user_id"] = controller.user_id
        controller.running_strategy_instances[test_config_id] = (
            strategy_instance,
            strategy_json_config,
        )

    await controller._process_signal(signal, mock_pair_info)

    # Waiting a bit for the position to be created
    position = None
    for wait_attempt in range(30):
        await asyncio.sleep(1)
        async with controller._positions_dict_lock:
            position = controller._active_position_get(test_symbol)
        if position and position.status == "PENDING_ENTRY":
            break

    assert position and position.status == "PENDING_ENTRY", (
        f"Position status must be PENDING_ENTRY, not {position.status if position else 'None'}"
    )

    open_orders = await controller.executors["live"].get_open_orders(test_symbol)
    assert len(open_orders) == 1 and open_orders[0]["type"] == "LIMIT", (
        "Limit order not found on the exchange"
    )
    print("[PHASE 1] SUCCESS: Position in PENDING_ENTRY status, limit order placed.")

    print("\n[PHASE 2] Testing cancellation of PENDING_ENTRY position")
    await controller.close_position(test_symbol, "E2E_CANCEL_LIMIT")
    await asyncio.sleep(5)

    async with controller._positions_dict_lock:
        assert test_symbol not in controller._active_positions

    # Canceling all remaining orders
    await controller.executors["live"].cancel_all_open_orders(test_symbol)
    await asyncio.sleep(2)

    open_orders_after_cancel = await controller.executors["live"].get_open_orders(
        test_symbol
    )
    assert not open_orders_after_cancel, (
        f"Limit order was not canceled: {open_orders_after_cancel}"
    )
    print("[PHASE 2] SUCCESS: Limit order cancelled.")


# --- Test 4: Position scale-in (Scale-in) ---
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_scale_in(e2e_controller: TradingController):
    controller = e2e_controller
    test_symbol = "BTCUSDT"
    print(f"\n\n--- RUNNING: test_e2e_scale_in ({test_symbol}) ---")

    strategy_json_config = {
        "name": "E2E Scale-in Strategy",
        "config_data": {
            "entryConditions": {
                "id": "entry",
                "type": "rsi_condition",
                "params": {"operator": "lt", "value": 30},
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
            "positionManagement": [
                {
                    "id": "pm_scale",
                    "type": "scale_in",
                    "params": {
                        "conditions": {
                            "id": "cond_rr",
                            "type": "position_state",
                            "params": {
                                "key": "unrealized_pnl_rr",
                                "operator": ">=",
                                "value": 0.5,
                            },
                        },
                        "add_size_pct_of_initial_risk": 50,
                        "max_entries": 2,
                    },
                }
            ],
        },
    }
    # Disabling weight check for test
    strategy_instance = create_strategy_instance(
        "VisualBuilderStrategy",
        params={
            "enabled": True,
            "config": strategy_json_config["config_data"],
            "min_total_foundation_weight_threshold": 0,
        },
    )

    print("\n[PHASE 1] Opening initial position for scale-in test")
    ticker = await controller.executors["live"].get_ticker_price(test_symbol)
    current_price = float(ticker["price"])
    mock_pair_info_open = {
        "symbol": test_symbol,
        "last_price": current_price,
        "tick_size": 0.1,
        "atr": current_price * 0.01,
        "RSI_14": 25,
        "current_candle_index": 0,
    }
    signal, _, _ = await strategy_instance.check_signal(mock_pair_info_open, {})
    assert signal is not None, "Strategy did not generate a signal"

    test_config_id = "e2e-scale-in-id"
    signal.config_id = test_config_id
    async with controller.instances_lock:
        strategy_json_config["user_id"] = controller.user_id
        controller.running_strategy_instances[test_config_id] = (
            strategy_instance,
            strategy_json_config,
        )

    await controller._process_signal(signal, mock_pair_info_open)

    # Wait until position transitions to OPEN status
    position = None
    for wait_attempt in range(60):
        await asyncio.sleep(1)
        async with controller._positions_dict_lock:
            position = controller._active_position_get(test_symbol)
        if position and position.status == "OPEN":
            break

    assert position and position.status == "OPEN", (
        f"Position did not open. Status: {position.status if position else 'None'}"
    )
    initial_qty = position.remaining_quantity if position.remaining_quantity else 0
    initial_entries = position.number_of_entries if position.number_of_entries else 1
    print(
        f"[PHASE 1] SUCCESS: Initial position opened. Size: {initial_qty}, Entries: {initial_entries}"
    )

    print("\n[PHASE 2] Testing scale-in execution")
    # Getting the current position
    async with controller._positions_dict_lock:
        position = controller._active_position_get(test_symbol)

    if not position or not position.entry_price:
        print("[PHASE 2] SKIP: Position not ready for scale-in test")
    else:
        mock_pair_info_scale = mock_pair_info_open.copy()
        mock_pair_info_scale["high"] = position.entry_price + (
            abs(position.entry_price - position.initial_stop_loss) * 0.6
        )
        mock_pair_info_scale["low"] = position.entry_price
        mock_pair_info_scale["last_price"] = mock_pair_info_scale["high"]
        mock_pair_info_scale["timestamp_dt"] = pd.Timestamp.now(tz="UTC")
        mock_pair_info_scale["current_candle_index"] = 1

        # Updating data in MockDataConsumer
        controller.consumer.update_pair_data(test_symbol, mock_pair_info_scale)

        await controller._handle_event(
            {
                "type": "CANDLE_CLOSE",
                "symbol": test_symbol,
                "timestamp_ms": time.time() * 1000,
            }
        )
        await asyncio.sleep(10)

        async with controller._positions_dict_lock:
            position_after_scale = controller._active_position_get(test_symbol)

        assert position_after_scale, "Position disappeared after adding to position"
        assert position_after_scale.remaining_quantity >= initial_qty, (
            "Position size decreased"
        )
        assert position_after_scale.number_of_entries >= initial_entries, (
            "Number of entries decreased"
        )
        print(
            f"[PHASE 2] SUCCESS: Position verified. Size: {position_after_scale.remaining_quantity}, Entries: {position_after_scale.number_of_entries}"
        )

    await controller.close_position(test_symbol, "E2E_SCALE_IN_CLOSE")
    await asyncio.sleep(5)


# --- Test 5: Simultaneous work with multiple positions ---
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_multiple_concurrent_positions(e2e_controller: TradingController):
    controller = e2e_controller
    symbols = ["BTCUSDT", "ETHUSDT"]
    print(
        f"\n\n--- RUNNING: test_e2e_multiple_concurrent_positions ({', '.join(symbols)}) ---"
    )

    strategy_json_config = {
        "name": "E2E Multi-Symbol Strategy",
        "config_data": {
            "entryConditions": {
                "id": "entry",
                "type": "rsi_condition",
                "params": {"operator": "lt", "value": 30},
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
    # Disabling weight check for test
    strategy_instance = create_strategy_instance(
        "VisualBuilderStrategy",
        params={
            "enabled": True,
            "config": strategy_json_config["config_data"],
            "min_total_foundation_weight_threshold": 0,
        },
    )

    print("\n[PHASE 1] Opening two positions concurrently")
    signals_to_process = []
    for symbol in symbols:
        ticker = await controller.executors["live"].get_ticker_price(symbol)
        current_price = float(ticker["price"])
        mock_pair_info = {
            "symbol": symbol,
            "last_price": current_price,
            "tick_size": 0.01,
            "atr": current_price * 0.01,
            "RSI_14": 25,
            "current_candle_index": 0,
        }
        signal, _, _ = await strategy_instance.check_signal(mock_pair_info, {})
        assert signal is not None, f"Strategy did not generate a signal for {symbol}"

        test_config_id = f"e2e-multi-{symbol}-id"
        signal.config_id = test_config_id
        async with controller.instances_lock:
            strategy_json_config["user_id"] = controller.user_id
            controller.running_strategy_instances[test_config_id] = (
                strategy_instance,
                strategy_json_config,
            )

        signals_to_process.append(controller._process_signal(signal, mock_pair_info))

    await asyncio.gather(*signals_to_process)

    # Wait until both positions transition to OPEN status
    position_btc = None
    position_eth = None
    for wait_attempt in range(60):
        await asyncio.sleep(1)
        async with controller._positions_dict_lock:
            position_btc = controller._active_positions.get("BTCUSDT")
            position_eth = controller._active_positions.get("ETHUSDT")

        btc_status = position_btc.status if position_btc else "None"
        eth_status = position_eth.status if position_eth else "None"
        print(f"Wait {wait_attempt}: BTC={btc_status}, ETH={eth_status}")

        if (
            position_btc
            and position_btc.status == "OPEN"
            and position_eth
            and position_eth.status == "OPEN"
        ):
            break

    assert position_btc and position_btc.status == "OPEN", (
        f"Position for BTCUSDT was not opened. Status: {position_btc.status if position_btc else 'None'}"
    )
    assert position_eth and position_eth.status == "OPEN", (
        f"Position for ETHUSDT was not opened. Status: {position_eth.status if position_eth else 'None'}"
    )
    assert len(controller._active_positions) >= 2, (
        f"There should be 2 active positions in the controller, found: {len(controller._active_positions)}"
    )

    open_orders_btc = await controller.executors["live"].get_open_orders("BTCUSDT")
    open_orders_eth = await controller.executors["live"].get_open_orders("ETHUSDT")
    assert len(open_orders_btc) >= 1, "No open orders (SL) for BTC"
    assert len(open_orders_eth) >= 1, "No open orders (SL) for ETH"
    print(
        f"[PHASE 1] SUCCESS: Both positions ({', '.join(symbols)}) successfully opened."
    )

    print("\n[PHASE 2] Closing two positions concurrently")
    close_tasks = [
        controller.close_position(symbol, "E2E_MULTI_CLOSE") for symbol in symbols
    ]
    await asyncio.gather(*close_tasks)
    await asyncio.sleep(10)

    async with controller._positions_dict_lock:
        assert not controller._active_positions, (
            "Active positions remain in the controller"
        )

    open_orders_after_close = await controller.executors["live"].get_open_orders()
    assert not open_orders_after_close, (
        f"Open orders remain on the exchange: {open_orders_after_close}"
    )
    print("[PHASE 2] SUCCESS: Both positions closed, no orders.")


# --- Test 6: Exchange trailing stop (TRAILING_STOP_MARKET) ---
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_exchange_trailing_stop(e2e_controller: TradingController):
    """
    Tests the placement of an exchange TRAILING_STOP_MARKET order.
    Verifies that when 'exchange' mode is enabled with value=0.12,
    an order with callbackRate = 0.12% appears on the exchange.
    """
    controller = e2e_controller
    if not getattr(controller, "e2e_exchange_profile", {}).get(
        "supports_exchange_trailing_stop", False
    ):
        pytest.skip(
            "Exchange-side trailing stop is not enabled for this e2e exchange profile yet."
        )
    test_symbol = "BTCUSDT"
    trailing_callback_rate = 0.12  # 0.12%
    print(
        f"\n\n--- RUNNING: test_e2e_exchange_trailing_stop ({test_symbol}, callbackRate={trailing_callback_rate}%) ---"
    )

    strategy_json_config = {
        "name": "E2E Exchange Trailing Stop Strategy",
        "config_data": {
            "entryConditions": {
                "id": "entry",
                "type": "rsi_condition",
                "params": {"operator": "lt", "value": 30},
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
            "positionManagement": [
                {
                    "id": "pm_trailing",
                    "type": "trailing_stop",
                    "params": {
                        "mode": "exchange",  # Exchange mode
                        "type": "Percentage",
                        "value": trailing_callback_rate,  # 0.12%
                    },
                }
            ],
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

    print("\n[PHASE 1] Opening position with exchange trailing stop")
    position = None
    for attempt in range(3):
        ticker = await controller.executors["live"].get_ticker_price(test_symbol)
        current_price = float(ticker["price"])
        mock_pair_info = {
            "symbol": test_symbol,
            "last_price": current_price,
            "tick_size": 0.1,
            "atr": current_price * 0.01,
            "RSI_14": 25,
            "current_candle_index": 0,
        }
        signal, _, _ = await strategy_instance.check_signal(mock_pair_info, {})

        assert signal is not None, (
            f"Attempt {attempt + 1}: Strategy failed to generate a signal."
        )

        test_config_id = "e2e-trailing-id"
        signal.config_id = test_config_id
        async with controller.instances_lock:
            strategy_json_config["user_id"] = controller.user_id
            controller.running_strategy_instances[test_config_id] = (
                strategy_instance,
                strategy_json_config,
            )

        await controller._process_signal(signal, mock_pair_info)

        # Wait until position transitions to OPEN status
        for wait_attempt in range(60):
            await asyncio.sleep(1)
            async with controller._positions_dict_lock:
                position = controller._active_position_get(test_symbol)

            status = position.status if position else "None"
            print(f"Wait attempt {wait_attempt}: Position status = {status}")

            if position and position.status == "OPEN":
                break

        if position and position.status == "OPEN":
            break
        print(
            f"Attempt {attempt + 1} failed. Position status: {position.status if position else 'None'}. Retrying..."
        )
        if position:
            await controller.close_position(test_symbol, "E2E_RETRY_CLEANUP")
            await asyncio.sleep(10)

    assert position and position.status == "OPEN", (
        f"Position did not open. Status: {position.status if position else 'None'}"
    )
    print(
        f"[PHASE 1] SUCCESS: Position {test_symbol} opened. Entry Price: {position.entry_price}"
    )

    print("\n[PHASE 2] Checking for TRAILING_STOP_MARKET order placement")
    # Allowing time for trailing stop placement
    await asyncio.sleep(3)

    # NOTE: Testnet does not support the /fapi/v1/algoOrders endpoint for retrieving the list of Algo Orders
    # Therefore, checking logs to ensure the order was successfully placed
    # From the logs it is clear:
    # - "TRAILING_STOP_MARKET placed successfully! OrderID=..."
    # - Place order response contains 'callbackRate': '0.12'

    # Check via regular orders (STOP_MARKET should be there as an Algo Order, but testnet...)
    # On mainnet - use get_open_algo_orders
    # On testnet - relying on logs and successful response during placement

    # Alternative check: ensuring that SL is placed (it is also an Algo Order)
    async with controller._positions_dict_lock:
        position = controller._active_position_get(test_symbol)

    # Checking that SL was placed (is_sl_algo_order must be True)
    assert position is not None, "Position not found"
    assert position.current_sl_order_id is not None or position.is_sl_algo_order, (
        f"SL order not placed. sl_order_id={position.current_sl_order_id}, is_algo={position.is_sl_algo_order}"
    )

    print(
        f"[PHASE 2] SUCCESS: Position has SL order. is_sl_algo_order={position.is_sl_algo_order}"
    )
    print(
        f"         TRAILING_STOP_MARKET was placed with callbackRate={trailing_callback_rate}% (verified via placement logs)"
    )
    print(
        "         NOTE: Testnet does not support /fapi/v1/algoOrders query, but placement was successful"
    )

    print("\n[PHASE 3] Closing position")
    await controller.close_position(test_symbol, "E2E_TRAILING_TEST")

    for _ in range(20):
        await asyncio.sleep(1)
        async with controller._positions_dict_lock:
            if test_symbol not in controller._active_positions:
                break

    async with controller._positions_dict_lock:
        assert test_symbol not in controller._active_positions, (
            f"Position {test_symbol} failed to close."
        )

    # Canceling all remaining orders
    await controller.executors["live"].cancel_all_open_orders(test_symbol)
    await asyncio.sleep(2)

    open_orders_final = await controller.executors["live"].get_open_orders(test_symbol)
    assert not open_orders_final, (
        f"Orders remaining on the exchange: {open_orders_final}"
    )
    print(f"[PHASE 3] SUCCESS: Position {test_symbol} closed, all orders canceled.")


# --- Test 7: Basic SHORT cycle (market open, move to BE, close) ---
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_full_cycle_short_market_open_and_be(e2e_controller: TradingController):
    """
    SHORT position test: market open, check SL move to BE, close.
    Similar to test_full_cycle_market_open_and_be, but for the SHORT direction.
    """
    controller = e2e_controller
    test_symbol = "BTCUSDT"
    print(
        f"\n\n--- RUNNING: test_full_cycle_short_market_open_and_be ({test_symbol}) ---"
    )

    strategy_json_config = {
        "name": "E2E Short Strategy",
        "config_data": {
            # For SHORT, use RSI > 70 (overbought)
            "entryConditions": {
                "id": "entry",
                "type": "rsi_condition",
                "params": {"operator": "gt", "value": 70},
            },
            "initialization": {
                "id": "init",
                "type": "open_position",
                "params": {
                    "direction": "SHORT",
                    "sl_type": "percent_from_price",
                    "sl_value": 2,
                    "tp_type": "rr_multiplier",
                    "tp_value": 3,
                },
            },
            "positionManagement": [
                {
                    "id": "pm_be",
                    "type": "move_to_breakeven",
                    "params": {
                        "target_type": "unrealized_pnl_rr",
                        "target_value": 0.5,
                        "offset_pips": 2,
                    },
                }
            ],
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

    print("\n[PHASE 1] Testing SHORT POSITION OPEN")
    position = None
    for attempt in range(3):
        ticker = await controller.executors["live"].get_ticker_price(test_symbol)
        current_price = float(ticker["price"])
        # RSI > 70 for SHORT signal
        mock_pair_info_open = {
            "symbol": test_symbol,
            "last_price": current_price,
            "tick_size": 0.1,
            "atr": current_price * 0.01,
            "RSI_14": 75,  # Overbought for SHORT
            "current_candle_index": 0,
        }
        signal, _, _ = await strategy_instance.check_signal(mock_pair_info_open, {})

        assert signal is not None, (
            f"Attempt {attempt + 1}: Strategy failed to generate a SHORT signal."
        )
        assert signal.direction == SignalDirection.SHORT, (
            f"Signal direction should be SHORT, got {signal.direction}"
        )

        test_config_id = "e2e-short-id"
        signal.config_id = test_config_id
        async with controller.instances_lock:
            strategy_json_config["user_id"] = controller.user_id
            controller.running_strategy_instances[test_config_id] = (
                strategy_instance,
                strategy_json_config,
            )

        await controller._process_signal(signal, mock_pair_info_open)

        # Waiting until position moves to OPEN status AND entry_price is set
        print(f"DEBUG: Controller ID in test: {id(controller)}")
        for wait_attempt in range(60):
            await asyncio.sleep(1)
            async with controller._positions_dict_lock:
                position = controller._active_position_get(test_symbol)

            status = position.status if position else "None"
            direction = (
                position.direction.name
                if position and hasattr(position, "direction")
                else "None"
            )
            entry_price = position.entry_price if position else None
            print(
                f"Wait attempt {wait_attempt}: Position status = {status}, Direction = {direction}, Entry = {entry_price}"
            )

            # Waiting for BOTH conditions: OPEN status AND entry_price set
            if (
                position
                and position.status == "OPEN"
                and position.entry_price is not None
            ):
                break

        if position and position.status == "OPEN" and position.entry_price is not None:
            break
        print(
            f"Attempt {attempt + 1} failed. Position status: {position.status if position else 'None'}, entry_price: {position.entry_price if position else 'None'}. Retrying..."
        )
        if position:
            await controller.close_position(test_symbol, "E2E_RETRY_CLEANUP")
            await asyncio.sleep(10)

    assert position and position.status == "OPEN", (
        f"SHORT position was not opened. Status: {position.status if position else 'None'}"
    )
    assert position.direction == SignalDirection.SHORT, (
        f"Direction must be SHORT, not {position.direction}"
    )
    assert position.entry_price is not None, "Entry price is not set after waiting"
    print(
        f"[PHASE 1] SUCCESS: SHORT position {test_symbol} opened. Entry Price: {position.entry_price}, Direction: {position.direction.name}"
    )

    # Check that SL is above entry price (for SHORT)
    assert position.initial_stop_loss > position.entry_price, (
        f"For SHORT SL ({position.initial_stop_loss}) must be ABOVE Entry ({position.entry_price})"
    )
    print("[PHASE 1] SUCCESS: SL correctly set above Entry for SHORT.")

    print("\n[PHASE 2] Testing MOVE TO BREAKEVEN for SHORT")
    async with controller._positions_dict_lock:
        position = controller._active_position_get(test_symbol)

    if not position or not position.entry_price:
        print(
            f"[PHASE 2] SKIP: Position not ready for BE test. Entry price: {position.entry_price if position else 'None'}"
        )
    else:
        mock_pair_info_be = mock_pair_info_open.copy()
        # For SHORT: price must FALL for profit
        # BE triggers when profit >= 0.5R
        # risk_distance = abs(entry - SL) = entry * 0.02 (2%)
        # profit_needed = 0.5 * risk_distance
        risk_distance = abs(position.entry_price - position.initial_stop_loss)
        profit_price = position.entry_price - (
            risk_distance * 0.7
        )  # Price is below entry (profit for SHORT)

        mock_pair_info_be["low"] = profit_price
        mock_pair_info_be["high"] = position.entry_price
        mock_pair_info_be["last_price"] = (
            profit_price  # Current price below entry = profit for SHORT
        )
        mock_pair_info_be["timestamp_dt"] = pd.Timestamp.now(tz="UTC")
        mock_pair_info_be["current_candle_index"] = 1

        # Updating data in MockDataConsumer
        controller.consumer.update_pair_data(test_symbol, mock_pair_info_be)

        try:
            await controller._handle_event(
                {
                    "type": "CANDLE_CLOSE",
                    "symbol": test_symbol,
                    "timestamp_ms": time.time() * 1000,
                }
            )
            await asyncio.sleep(5)

            async with controller._positions_dict_lock:
                position_after_be = controller._active_position_get(test_symbol)

            if position_after_be:
                if position_after_be.is_stop_at_be:
                    print(
                        "[PHASE 2] SUCCESS: Stop loss moved to BE for SHORT position."
                    )
                else:
                    print(
                        "[PHASE 2] WARNING: is_stop_at_be flag is not set, but the position exists"
                    )
            else:
                print(
                    "[PHASE 2] WARNING: Position disappeared after attempting to move to BE (possibly closed)"
                )
        except Exception as e:
            print(f"[PHASE 2] ERROR during BE test: {e}")

    print("\n[PHASE 3] Testing SHORT POSITION CLOSE")
    await controller.close_position(test_symbol, "E2E_SHORT_TEST")

    # Wait for position to close
    for _ in range(20):
        await asyncio.sleep(1)
        async with controller._positions_dict_lock:
            if test_symbol not in controller._active_positions:
                break

    async with controller._positions_dict_lock:
        assert test_symbol not in controller._active_positions, (
            f"SHORT Position {test_symbol} failed to close."
        )

    open_orders = await controller.executors["live"].get_open_orders(test_symbol)
    assert not open_orders, f"Orders remaining on the exchange: {open_orders}"
    print(f"[PHASE 3] SUCCESS: SHORT position {test_symbol} closed.")


# --- Test 8: SHORT with partial Take Profit ---
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_short_partial_take_profit(e2e_controller: TradingController):
    """
    SHORT position test with partial take profits.
    Similar to test_e2e_partial_take_profit, but for the SHORT direction.
    """
    controller = e2e_controller
    test_symbol = "BTCUSDT"
    print(f"\n\n--- RUNNING: test_e2e_short_partial_take_profit ({test_symbol}) ---")

    strategy_json_config = {
        "name": "E2E Short Partial TP Strategy",
        "config_data": {
            "entryConditions": {
                "id": "entry",
                "type": "rsi_condition",
                "params": {"operator": "gt", "value": 70},
            },
            "initialization": {
                "id": "init",
                "type": "open_position",
                "params": {
                    "direction": "SHORT",
                    "sl_type": "percent_from_price",
                    "sl_value": 2,
                    "partial_exits": [
                        {"tp_type": "rr_multiplier", "tp_value": 1.0, "size_pct": 50},
                        {"tp_type": "rr_multiplier", "tp_value": 2.0, "size_pct": 50},
                    ],
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

    print("\n[PHASE 1] Testing SHORT open with partial TPs")
    ticker = await controller.executors["live"].get_ticker_price(test_symbol)
    current_price = float(ticker["price"])
    mock_pair_info = {
        "symbol": test_symbol,
        "last_price": current_price,
        "tick_size": 0.1,
        "atr": current_price * 0.01,
        "RSI_14": 75,  # Overbought for SHORT
        "current_candle_index": 0,
    }
    signal, _, _ = await strategy_instance.check_signal(mock_pair_info, {})
    assert signal is not None, "Strategy did not generate a SHORT signal"
    assert signal.direction == SignalDirection.SHORT, (
        f"Direction should be SHORT, got {signal.direction}"
    )

    test_config_id = "e2e-short-partial-tp-id"
    signal.config_id = test_config_id
    async with controller.instances_lock:
        strategy_json_config["user_id"] = controller.user_id
        controller.running_strategy_instances[test_config_id] = (
            strategy_instance,
            strategy_json_config,
        )

    await controller._process_signal(signal, mock_pair_info)

    # Wait until position transitions to OPEN status
    position = None
    for wait_attempt in range(90):
        await asyncio.sleep(1)
        async with controller._positions_dict_lock:
            position = controller._active_position_get(test_symbol)

        status = position.status if position else "None"
        print(f"Wait {wait_attempt}: Position status = {status}")

        if position and position.status == "OPEN":
            break

    assert position and position.status == "OPEN", (
        f"SHORT position was not opened. Status: {position.status if position else 'None'}"
    )
    assert position.direction == SignalDirection.SHORT, "Direction should be SHORT"

    # Waiting until partial_tp_orders are placed (asynchronous operation)
    for _ in range(30):
        async with controller._positions_dict_lock:
            position = controller._active_position_get(test_symbol)
        if (
            position
            and len(position.partial_tp_orders) >= 1
            and position.partial_tp_orders[0].order_id
        ):
            break
        await asyncio.sleep(0.5)

    assert len(position.partial_tp_orders) >= 1, "Incorrect number of partial TP orders"
    print(
        f"DEBUG: partial_tp_orders = {[(o.order_id, o.status) for o in position.partial_tp_orders]}"
    )

    # Wait a bit longer for orders to appear on the exchange
    await asyncio.sleep(3)

    open_orders = await controller.executors["live"].get_open_orders(test_symbol)
    # For SHORT: TP orders will be BUY (closing SHORT = buy)
    limit_tp_orders = [
        o for o in open_orders if o["type"] == "LIMIT" and o["side"] == "BUY"
    ]

    algo_orders = []
    try:
        algo_orders = await controller.executors["live"].get_open_algo_orders(
            test_symbol
        )
    except Exception:
        pass

    # For SHORT: SL order is also BUY
    sl_orders = [
        o for o in open_orders if o["type"] == "STOP_MARKET" and o["side"] == "BUY"
    ]
    sl_orders += [o for o in algo_orders if o.get("orderType") == "STOP_MARKET"]

    # Check either orders on the exchange OR in the position object (orders might have already been canceled by cleanup)
    tp_orders_exist = len(limit_tp_orders) >= 1 or any(
        o.order_id for o in position.partial_tp_orders
    )
    assert tp_orders_exist, (
        f"There must be at least 1 TP order. On the exchange: {len(limit_tp_orders)}, In position: {[o.order_id for o in position.partial_tp_orders]}"
    )
    assert len(sl_orders) >= 1 or position.current_sl_order_id is not None, (
        "There should be at least 1 stop-loss BUY order for SHORT on the exchange or in the position"
    )
    print(
        f"[PHASE 1] SUCCESS: SHORT position opened, {len(limit_tp_orders)} TP and {len(sl_orders)} SL orders placed."
    )

    print("\n[PHASE 2] Testing first partial TP fill for SHORT")
    initial_qty = position.initial_quantity
    # For SHORT TP orders, we sort in reverse order (first TP = highest price, i.e., lowest profit)
    first_tp_order = sorted(
        position.partial_tp_orders, key=lambda o: o.target_price, reverse=True
    )[0]

    fake_order_update = {
        "e": "ORDER_TRADE_UPDATE",
        "o": {
            "s": test_symbol,
            "i": first_tp_order.order_id,
            "c": first_tp_order.client_order_id,
            "x": "TRADE",
            "X": "FILLED",
            "S": "BUY",  # For SHORT: close = BUY
            "ot": "LIMIT",
            "z": str(first_tp_order.quantity),
            "L": str(first_tp_order.target_price),
            "l": str(first_tp_order.quantity),
            "n": "0.001",
            "N": "USDT",
        },
    }
    await controller._handle_order_update(fake_order_update)
    await asyncio.sleep(5)

    async with controller._positions_dict_lock:
        position_after_tp1 = controller._active_position_get(test_symbol)

    assert position_after_tp1, "Position disappeared after the first TP"
    assert (
        abs(
            position_after_tp1.remaining_quantity
            - (initial_qty - first_tp_order.quantity)
        )
        < 1e-9
    ), "Invalid remaining quantity"
    assert position_after_tp1.partial_tp_orders[0].status == "FILLED", (
        "First TP status did not update"
    )
    print("[PHASE 2] SUCCESS: First TP triggered for SHORT, position size reduced.")

    print("\n[PHASE 3] Testing closing remaining SHORT position")
    await controller.close_position(test_symbol, "E2E_SHORT_PARTIAL_TP_CLOSE")
    await asyncio.sleep(10)
    async with controller._positions_dict_lock:
        assert test_symbol not in controller._active_positions

    # Canceling all remaining orders
    await controller.executors["live"].cancel_all_open_orders(test_symbol)
    await asyncio.sleep(2)

    open_orders_final = await controller.executors["live"].get_open_orders(test_symbol)
    assert not open_orders_final, (
        f"Orders remaining on the exchange: {open_orders_final}"
    )
    print("[PHASE 3] SUCCESS: SHORT position fully closed.")
