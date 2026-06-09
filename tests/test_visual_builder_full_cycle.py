# tests/test_visual_builder_full_cycle.py

import pytest
import asyncio
import time
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone
import pandas as pd
import logging

from bot_module.controller import TradingController, LivePosition as Position
from bot_module.strategy import SignalDirection
from bot_module.strategy import VisualBuilderStrategy, create_strategy_instance

try:
    from tests.test_e2e_full_cycle import setup_testnet_env, e2e_controller

    _ = [setup_testnet_env, e2e_controller]
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("bot_module.controller").setLevel(logging.DEBUG)


# ===========================================================================
#  UNIT TEST: Quick logic check without connecting to the exchange
# ===========================================================================


@pytest.fixture
def mock_controller_deps():
    """Mocks for TradingController dependencies."""
    consumer = AsyncMock()
    executor = AsyncMock()
    executor.market_type = "futures_usdtm"
    risk_manager = AsyncMock()
    risk_manager._adjust_and_round_quantity = MagicMock(
        side_effect=lambda q, symbol, price, lot_params, min_notional: q
    )
    trade_logger = MagicMock()

    return {
        "consumer": consumer,
        "executor": executor,
        "risk_manager": risk_manager,
        "trade_logger": trade_logger,
    }


@pytest.fixture
async def fast_controller(mock_controller_deps):
    """A minimal TradingController for testing."""
    with patch("bot_module.controller.get_strategy_instance", return_value=MagicMock()):
        ctrl = TradingController(
            loop=asyncio.get_running_loop(),
            data_consumer=lambda **kwargs: mock_controller_deps["consumer"],
            live_executor=mock_controller_deps["executor"],
            paper_executor=MagicMock(),
            risk_manager=mock_controller_deps["risk_manager"],
            user_id=1,
        )
        ctrl.trade_logger = mock_controller_deps["trade_logger"]

        async def mock_gmi(symbol, key, **kwargs):
            if key == "tick_size":
                return 0.01
            if key == "lot_params":
                return {"stepSize": 0.001}
            if key == "min_notional":
                return 5.0
            return None

        ctrl._get_market_info = AsyncMock(side_effect=mock_gmi)

        return ctrl


@pytest.mark.asyncio
async def test_full_entry_dca_cycle(fast_controller, mock_controller_deps):
    """
    UNIT TEST: Verifies strategy logic (signal + DCA trigger + scale-in fill)
    without connecting to the exchange. All exchange calls are mocked.
    """
    symbol = "BTCUSDT"

    # --- 1. CONFIGURATION ---
    full_config = {
        "entryConditions": {
            "id": "root",
            "type": "price_vs_level",
            "params": {
                "price_source": {"source": "candle", "key": "last_price", "shift": 0},
                "operator": "gt",
                "level_source": 10000.0,
            },
        },
        "positionManagement": [
            {
                "id": "dca1",
                "type": "dca_management",
                "params": {
                    "max_safety_orders": 3,
                    "volume_multiplier": 1.0,
                    "step_type": "percentage",
                    "step_value": 1.0,
                },
            }
        ],
        "initialization": {
            "id": "init1",
            "type": "action",
            "params": {
                "direction": "LONG",
                "order_type": "MARKET",
                "sl_value": 0,
                "sl_type": "percent_from_price",
                "tp_type": "percent_from_price",
                "tp_value": 3.0,
            },
        },
    }

    strategy = VisualBuilderStrategy(params={"config": full_config, "enabled": True})
    strategy.min_total_foundation_weight_threshold = -1.0

    # --- 2. STEP 1: ENTRY ---
    pair_info = {
        "symbol": symbol,
        "last_price": 10500.0,
        "tick_size": 0.01,
        "atr": 100.0,
        "is_live_mode": True,
    }
    market_data = {}

    signal, weight, trace = await strategy.check_signal(pair_info, market_data)
    assert signal is not None
    assert signal.direction == SignalDirection.LONG
    assert signal.trigger_price == 10500.0
    assert signal.stop_loss is None
    assert signal.take_profit == 10815.0  # 10500 * 1.03

    # --- 3. STEP 2: OPEN POSITION ---
    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=10500.0,
        initial_quantity=0.1,
        remaining_quantity=0.1,
        entry_time=time.time(),
        strategy=strategy.NAME,
        status="OPEN",
        initial_stop_loss=None,
        current_sl_price=None,
        initial_take_profit=10815.0,
    )
    position.strategy_config_id = "test-config"
    fast_controller._active_position_set(position)
    fast_controller.running_strategy_instances["test-config"] = (strategy, {})

    # --- 4. STEP 3: DCA TRIGGER ---
    now_dt = datetime.now(tz=timezone.utc)
    pair_info_dca = {
        "symbol": symbol,
        "last_price": 10300.0,
        "tick_size": 0.01,
        "atr": 100.0,
        "is_live_mode": True,
        "high": 10500.0,
        "low": 10280.0,
        "timestamp_dt": now_dt,
    }

    updated_pos, exit_details = await strategy.manage_position(
        position, pair_info_dca, market_data, prev_pair_info=None
    )

    # With the release of the new limit order logic, strategy now sets dca_grid_init_triggered
    assert position.dca_grid_init_triggered is not None

    # --- 5. STEP 4: CONTROLLER EXECUTION ---
    mock_controller_deps["executor"].place_order.return_value = {
        "orderId": 555,
        "status": "NEW",
    }

    data = {
        "e": "ORDER_TRADE_UPDATE",
        "o": {
            "s": symbol,
            "c": "x-scalein-1",
            "i": 555,
            "X": "FILLED",
            "S": "BUY",
            "q": "0.1",
            "z": "0.1",
            "ap": "10300.0",
            "x": "TRADE",
            "ot": "LIMIT",
        },
    }
    fast_controller._update_tp_after_scale_in = AsyncMock()

    await fast_controller._handle_order_update(data)
    await asyncio.sleep(0.1)

    assert position.entry_price == 10400.0
    assert position.dca_active_sos == 1
    assert fast_controller._update_tp_after_scale_in.called


# ===========================================================================
#  E2E TEST: Full DCA cycle on Binance Testnet
# ===========================================================================


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_dca_grid_on_testnet(e2e_controller: TradingController):
    """
    E2E TEST: Opens a position on the testnet, checks DCA triggering,
    and verifies that the scale-in order is placed on the exchange.

    Uses the same infrastructure as test_e2e_full_cycle.py.
    Run: pytest tests/test_visual_builder_full_cycle.py -m e2e -v
    """
    controller = e2e_controller
    test_symbol = "BTCUSDT"
    print(f"\n\n--- RUNNING: test_e2e_dca_grid_on_testnet ({test_symbol}) ---")

    strategy_json_config = {
        "name": "E2E DCA Strategy",
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
                    "sl_value": 0,
                    "tp_type": "percent_from_price",
                    "tp_value": 5,
                    "risk_value": 5,
                },
            },
            "positionManagement": [
                {
                    "id": "dca1",
                    "type": "dca_management",
                    "params": {
                        "max_safety_orders": 5,
                        "volume_multiplier": 1.5,
                        "step_multiplier": 1.5,
                        "step_type": "percentage",
                        "step_value": 2.0,
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

    # --- PHASE 1: Open position at market price ---
    print("\n[PHASE 1] Opening initial LONG position for DCA test")
    position = None
    mock_pair_info = None
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
            "timestamp_dt": pd.Timestamp.now(tz="UTC"),
        }
        signal, _, _ = await strategy_instance.check_signal(mock_pair_info, {})

        assert signal is not None, (
            f"Attempt {attempt + 1}: Strategy failed to generate a signal."
        )

        test_config_id = "e2e-dca-id"
        signal.config_id = test_config_id
        async with controller.instances_lock:
            strategy_json_config["user_id"] = controller.user_id
            controller.running_strategy_instances[test_config_id] = (
                strategy_instance,
                strategy_json_config,
            )

        await controller._process_signal(signal, mock_pair_info)

        for wait_attempt in range(60):
            await asyncio.sleep(1)
            async with controller._positions_dict_lock:
                position = controller._active_position_get(test_symbol, "futures_usdtm")

            status = position.status if position else "None"
            print(f"Wait attempt {wait_attempt}: Position status = {status}")

            if position and position.status == "OPEN":
                break

        if position and position.status == "OPEN":
            break
        print(f"Attempt {attempt + 1} failed. Retrying...")
        if position:
            await controller.close_position(test_symbol, "E2E_RETRY_CLEANUP")
            await asyncio.sleep(10)

    assert position and position.status == "OPEN", (
        f"Position did not open. Status: {position.status if position else 'None'}"
    )

    initial_entry_price = position.entry_price
    initial_qty = position.remaining_quantity
    print(
        f"[PHASE 1] SUCCESS: Position opened. Entry: {initial_entry_price}, Qty: {initial_qty}"
    )

    # --- PHASE 2: Position management trigger for placing the DCA grid ---
    print("\n[PHASE 2] Executing Position Management for DCA Limit Grid Init")

    # Update consumer data and send CANDLE_CLOSE (will trigger pm -> dca grid init)
    controller.consumer.update_pair_data(test_symbol, mock_pair_info)
    await controller._handle_event(
        {
            "type": "CANDLE_CLOSE",
            "symbol": test_symbol,
            "timestamp_ms": time.time() * 1000,
        }
    )

    # Wait until the grid places its asynchronous orders
    print("Waiting for DCA limit orders to be placed...")
    await asyncio.sleep(15)

    async with controller._positions_dict_lock:
        position_after_grid = controller._active_position_get(
            test_symbol, "futures_usdtm"
        )

    dca_order_ids = getattr(position_after_grid, "dca_order_ids", [])
    print(
        f"DCA orders saved in position object: {len(dca_order_ids)} orders -> {dca_order_ids}"
    )

    # Load real orders from Binance Testnet
    open_orders = await controller.executors["live"].get_open_orders(test_symbol)
    limit_orders = [
        o for o in open_orders if o["type"] == "LIMIT" and o["side"] == "BUY"
    ]

    print(
        f"[PHASE 2] API returned {len(limit_orders)} BUY LIMIT orders. Expecting at least 3 (our DCA grid)."
    )

    # Checking order prices and volumes
    for i, order in enumerate(
        sorted(limit_orders, key=lambda x: float(x["price"]), reverse=True)
    ):
        price = float(order["price"])
        qty = float(order["origQty"])
        print(f"  SO #{i + 1}: Price={price}, Qty={qty}")
        # SO 1 should be ~2% below entry
        # SO 2 should be ~2.6% below entry
        # SO 3 should be ~3.38% below entry
        # Qty should grow by 1.3x each step

    assert len(dca_order_ids) > 0, (
        "Controller did not save the DCA grid ID in the position object!"
    )
    assert len(limit_orders) >= 3, "DCA Grid orders are not placed on the testnet!"

    # --- PHASE 3: Closing ---
    print("\n[PHASE 3] Closing position and cleaning up orders")
    await controller.close_position(test_symbol, "E2E_DCA_TEST")
    await asyncio.sleep(5)

    await controller.executors["live"].cancel_all_open_orders(test_symbol)
    await asyncio.sleep(5)

    open_orders = await controller.executors["live"].get_open_orders(test_symbol)
    assert not open_orders, f"Orders remaining on the exchange: {open_orders}"
    print(f"[PHASE 3] SUCCESS: Position {test_symbol} closed, all orders cancelled.")


# --- E2E TEST: Grid Management on Binance Testnet ---
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_grid_management_on_testnet(e2e_controller: TradingController):
    """
    E2E TEST: Opens a position on the testnet and verifies the triggering
    and placement of LIMIT grid orders (Grid).
    """
    controller = e2e_controller
    test_symbol = "BTCUSDT"
    print(f"\n\n--- RUNNING: test_e2e_grid_management_on_testnet ({test_symbol}) ---")

    # Get the current price to dynamically place the grid
    ticker = await controller.executors["live"].get_ticker_price(test_symbol)
    current_price = float(ticker["price"])

    strategy_json_config = {
        "name": "E2E Grid Strategy",
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
                    "sl_value": 3,
                    "tp_type": "percent_from_price",
                    "tp_value": 3,
                },
            },
            "positionManagement": [
                {
                    "id": "grid1",
                    "type": "grid_management",
                    "params": {
                        "levels": 5,
                        "upper_bound": current_price * 1.05,
                        "lower_bound": current_price * 0.95,
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

    # --- PHASE 1: Open position at market price ---
    print("\n[PHASE 1] Opening initial LONG position for Grid test")
    position = None
    mock_pair_info = {
        "symbol": test_symbol,
        "last_price": current_price,
        "tick_size": 0.1,
        "atr": current_price * 0.01,
        "RSI_14": 25,
        "current_candle_index": 0,
        "timestamp_dt": pd.Timestamp.now(tz="UTC"),
    }
    signal, _, _ = await strategy_instance.check_signal(mock_pair_info, {})

    assert signal is not None, "Strategy failed to generate a signal."

    test_config_id = "e2e-grid-id"
    signal.config_id = test_config_id
    async with controller.instances_lock:
        strategy_json_config["user_id"] = controller.user_id
        controller.running_strategy_instances[test_config_id] = (
            strategy_instance,
            strategy_json_config,
        )

    await controller._process_signal(signal, mock_pair_info)

    for wait_attempt in range(60):
        await asyncio.sleep(1)
        async with controller._positions_dict_lock:
            position = controller._active_position_get(test_symbol, "futures_usdtm")
        if position and position.status == "OPEN":
            break

    assert position and position.status == "OPEN", (
        f"Position did not open. Status: {position.status if position else 'None'}"
    )

    # --- PHASE 2: Position management trigger for placing the Grid ---
    print("\n[PHASE 2] Executing Position Management for Grid Init")

    # Update consumer data and send CANDLE_CLOSE (will trigger pm -> grid init)
    controller.consumer.update_pair_data(test_symbol, mock_pair_info)
    await controller._handle_event(
        {
            "type": "CANDLE_CLOSE",
            "symbol": test_symbol,
            "timeframe": "1m",
            "timestamp_ms": time.time() * 1000,
        }
    )

    # Wait until the grid places its asynchronous orders
    print("Waiting for grid orders to be placed...")
    await asyncio.sleep(15)

    async with controller._positions_dict_lock:
        position_after_grid = controller._active_position_get(
            test_symbol, "futures_usdtm"
        )

    grid_order_ids = getattr(position_after_grid, "grid_order_ids", [])
    print(
        f"Grid orders saved in position object: {len(grid_order_ids)} orders -> {grid_order_ids}"
    )

    # Load real orders from Binance Testnet
    open_orders = await controller.executors["live"].get_open_orders(test_symbol)
    limit_orders = [o for o in open_orders if o["type"] == "LIMIT"]

    print(
        f"[PHASE 2] API returned {len(limit_orders)} LIMIT orders. Expecting at least 5 (our grid)."
    )
    assert len(grid_order_ids) > 0, (
        "Controller did not save the grid ID in the position object!"
    )

    # Ensure that LIMIT orders are actually created on the exchange (our grid)
    limit_order_ids_on_exchange = [o["orderId"] for o in limit_orders]
    placed_grid_orders = [
        gid for gid in grid_order_ids if gid in limit_order_ids_on_exchange
    ]
    print(
        f"[PHASE 2] Successfully verified {len(placed_grid_orders)} grid orders directly on the exchange."
    )
    assert len(placed_grid_orders) > 0, "Grid orders are not placed on testnet!"

    # --- PHASE 3: Closing ---
    print("\n[PHASE 3] Closing position and cleaning up orders")
    await controller.close_position(test_symbol, "E2E_GRID_TEST")
    await asyncio.sleep(5)

    await controller.executors["live"].cancel_all_open_orders(test_symbol)
    await asyncio.sleep(5)
