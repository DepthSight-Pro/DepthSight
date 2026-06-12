import pytest
import asyncio
import time
import pandas as pd
from datetime import timezone
from unittest.mock import MagicMock, AsyncMock, patch
from bot_module.controller import TradingController, LivePosition as Position
from bot_module.strategy import (
    SignalDirection,
    VisualBuilderStrategy,
)


@pytest.fixture
def mock_deps(mocker):
    consumer = AsyncMock()
    executor = AsyncMock()
    executor.market_type = "futures_usdtm"
    risk_manager = AsyncMock()
    # Mock calculate_scaled_in_quantity to return a fixed value for simplicity
    risk_manager.calculate_scaled_in_quantity = AsyncMock(return_value=1.0)
    # _adjust_and_round_quantity is a sync method in RiskManager
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
async def controller(mock_deps):
    with patch("bot_module.controller.get_strategy_instance", return_value=MagicMock()):
        ctrl = TradingController(
            loop=asyncio.get_running_loop(),
            data_consumer=lambda **kwargs: mock_deps["consumer"],
            live_executor=mock_deps["executor"],
            paper_executor=MagicMock(),
            risk_manager=mock_deps["risk_manager"],
            user_id=1,
        )
        ctrl.trade_logger = mock_deps["trade_logger"]

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
async def test_strategy_triggers_dca_grid_init():
    """Verify that strategy sets dca_grid_init_triggered for percentage step_type."""
    mgmt_config = {
        "positionManagement": [
            {
                "id": "dca_limit",
                "type": "dca_management",
                "params": {
                    "max_safety_orders": 2,
                    "step_type": "percentage",
                    "step_value": 1.0,
                },
            }
        ]
    }
    strategy = VisualBuilderStrategy(params={"config": mgmt_config})

    position = Position(
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        entry_price=100.0,
        initial_quantity=1.0,
        remaining_quantity=1.0,
        status="OPEN",
        entry_time=123.0,
        strategy="Test",
        initial_stop_loss=90.0,
        current_sl_price=90.0,
        initial_take_profit=110.0,
    )

    pair_info = {"last_price": 100.0, "symbol": "BTCUSDT", "is_live_mode": True}

    # First call should trigger initialization
    pos = await strategy._handle_dca_management(
        mgmt_config["positionManagement"][0], position, pair_info, {}, {}
    )
    assert pos.dca_grid_init_triggered is not None
    assert pos.dca_grid_init_triggered["max_safety_orders"] == 2

    # Simulate controller clearing the trigger and setting order_ids
    pos.dca_grid_init_triggered = None
    pos.dca_order_ids = [12345]

    # Second call should NOT trigger it again
    pos = await strategy._handle_dca_management(
        mgmt_config["positionManagement"][0], pos, pair_info, {}, {}
    )
    assert pos.dca_grid_init_triggered is None


@pytest.mark.asyncio
async def test_controller_executes_dca_grid_placement(controller, mock_deps):
    """Verify that controller places correct limit orders when dca_grid_init_triggered is set."""
    symbol = "BTCUSDT"
    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=100.0,
        initial_quantity=1.0,
        remaining_quantity=1.0,
        status="OPEN",
        entry_client_order_id="x-entry-123",
        entry_time=123.0,
        strategy="Test",
        initial_stop_loss=90.0,
        current_sl_price=90.0,
        initial_take_profit=110.0,
    )
    controller._active_positions[symbol] = position

    dca_params = {
        "max_safety_orders": 2,
        "step_type": "percentage",
        "step_value": 2.0,
        "step_multiplier": 1.5,
        "volume_multiplier": 2.0,
    }

    mock_deps["executor"].place_order.return_value = {"orderId": 999, "status": "NEW"}

    pair_info = {"last_price": 100.0, "symbol": symbol, "atr": 1.0}

    await controller._execute_dca_grid(position, dca_params, pair_info)

    # Should place 2 limit orders
    assert mock_deps["executor"].place_order.call_count == 2

    calls = mock_deps["executor"].place_order.call_args_list

    # SO 1: 2% from 100.0 -> 98.0
    # Qty SO 1: 1.0 * (2.0^1) = 2.0
    assert float(calls[0].kwargs["price"]) == 98.0
    assert float(calls[0].kwargs["quantity"]) == 2.0
    assert calls[0].kwargs["order_type"] == "LIMIT"
    assert calls[0].kwargs["newClientOrderId"].startswith("x-scalein-")

    # SO 2: Cumulative step: 2.0 + (2.0 * 1.5) = 5.0% -> 95.0
    # Qty SO 2: 1.0 * (2.0^2) = 4.0
    assert float(calls[1].kwargs["price"]) == 95.0
    assert float(calls[1].kwargs["quantity"]) == 4.0

    assert len(position.dca_order_ids) == 2
    assert position.dca_order_ids == [999, 999]


@pytest.mark.asyncio
async def test_tp_update_logic_in_main_loop(controller, mock_deps):
    """Verify that TP is re-placed if missing or changed in the main loop."""
    symbol = "BTCUSDT"
    # Position with NO TP orders
    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=100.0,
        initial_quantity=1.0,
        remaining_quantity=1.0,
        status="OPEN",
        entry_time=123.0,
        strategy="Test",
        initial_stop_loss=90.0,
        current_sl_price=90.0,
        initial_take_profit=110.0,
    )
    position.partial_tp_orders = []  # Missing!
    controller._active_positions[symbol] = position

    # Mock strategy to return the same position
    mock_strat = MagicMock()
    mock_strat.manage_position = AsyncMock(return_value=(position, None))
    controller.running_strategy_instances["test-cfg"] = (mock_strat, {})
    position.config_id = "test-cfg"

    # Mock _replace_take_profit
    controller._replace_take_profit = AsyncMock()

    pair_info = {
        "symbol": symbol,
        "last_price": 100.0,
        "high": 105.0,
        "low": 95.0,
        "close": 100.0,
    }
    mock_deps["consumer"].get_active_pair_by_symbol = AsyncMock(return_value=pair_info)
    mock_deps["consumer"].get_kline_history = AsyncMock(
        return_value=pd.DataFrame(
            {
                "high": [105.0],
                "low": [95.0],
                "close": [100.0],
                "open": [100.0],
                "volume": [100.0],
            },
            index=[pd.Timestamp.now(tz=timezone.utc)],
        )
    )

    # Simulate CANDLE_CLOSE event which triggers position management
    await controller._handle_event(
        {"type": "CANDLE_CLOSE", "symbol": symbol, "timestamp_ms": time.time() * 1000}
    )

    # Should detect missing TP and call _replace_take_profit
    controller._replace_take_profit.assert_called_once_with(
        symbol, 110.0, market_type="futures_usdtm", partial_targets=None
    )


@pytest.mark.asyncio
async def test_tp_recalculation_upon_reset():
    """Verify that strategy recalculates TP after position.initial_take_profit is reset (simulating DCA)."""
    mgmt_config = {
        "initialization": {
            "type": "open_position",
            "params": {"tp_type": "percent_from_price", "tp_value": 2.0},
        },
        "positionManagement": [],
    }
    strategy = VisualBuilderStrategy(params={"config": mgmt_config})

    position = Position(
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        entry_price=100.0,
        initial_quantity=1.0,
        remaining_quantity=1.0,
        status="OPEN",
        entry_time=123.0,
        strategy="Test",
        initial_stop_loss=90.0,
        current_sl_price=90.0,
        initial_take_profit=102.0,
    )

    # Simulate Scale-In: Update entry price and clear TP
    position.entry_price = 90.0
    position.initial_take_profit = None

    pair_info = {
        "symbol": "BTCUSDT",
        "last_price": 90.0,
        "tick_size": 0.01,
        "timestamp_dt": "2026-01-01 00:00:00",
        "is_live_mode": True,
        "high": 90.5,
        "low": 89.5,
    }

    # Call manage_position - should trigger recalculation
    updated_pos, _ = await strategy.manage_position(position, pair_info, {}, None)

    # Check that TP is now 91.80 (2% from 90.0)
    assert updated_pos.initial_take_profit == 91.80


@pytest.mark.asyncio
async def test_dca_order_cancellation_on_exit(controller, mock_deps):
    """Verify that DCA safety orders are cancelled when _handle_final_exit is called."""
    symbol = "BTCUSDT"
    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=100.0,
        initial_quantity=1.0,
        remaining_quantity=1.0,
        status="OPEN",
        entry_time=123.0,
        strategy="Test",
        initial_stop_loss=90.0,
        current_sl_price=90.0,
        initial_take_profit=110.0,
    )
    # Add simulated DCA order IDs
    position.dca_order_ids = [777, 888]
    controller._active_positions[symbol] = position

    # Simulate final exit (e.g. by TP)
    await controller._handle_final_exit(
        symbol=symbol,
        reason="TEST_EXIT",
        exit_price=110.0,
        commission=0,
        commission_asset="USDT",
        order_id=111,
        client_order_id="x-tp-111",
    )

    # Wait for background cancellation tasks
    await asyncio.sleep(0.1)

    # Check that executor.cancel_all_open_orders was called for the symbol
    # This replaces individual cancel_order calls for 777 and 888
    mock_deps["executor"].cancel_all_open_orders.assert_called_with(symbol)

    print(f"Verified: All open orders for {symbol} were cancelled via Hard Reset.")
