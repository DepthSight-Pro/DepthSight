import pytest
import asyncio
import time
from unittest.mock import MagicMock

from bot_module.controller import TradingController, LivePosition, PartialTpOrderInfo
from bot_module.strategy import SignalDirection


@pytest.fixture
def base_position():
    return LivePosition(
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        status="OPEN",
        entry_price=10000.0,
        initial_quantity=1.0,
        remaining_quantity=1.0,
        number_of_entries=1,
        initial_take_profit=11000.0,
        current_sl_price=9000.0,
        entry_time=time.time(),
        strategy="TestStrategy",
        partial_tp_orders=[
            PartialTpOrderInfo(
                target_price=10500.0,
                orig_fraction=0.5,
                quantity=0.5,
                status="PENDING",
                order_id=1,
            ),
            PartialTpOrderInfo(
                target_price=11000.0,
                orig_fraction=0.5,
                quantity=0.5,
                status="PENDING",
                order_id=2,
            ),
        ],
    )


@pytest.fixture
def mock_controller():
    controller = MagicMock(spec=TradingController)
    # Ensure properties exist
    controller._active_positions = {}

    # Keep the actual implementation of _replace_take_profit from TradingController
    def mock_get_lock(symbol, market_type):
        return asyncio.Lock()

    controller._get_lock_for_position = mock_get_lock
    controller._active_position_get = lambda symbol, market_type: (
        controller._active_positions.get(symbol)
    )

    # We want to use the REAL _replace_take_profit method bound to this mock object
    controller._replace_take_profit = TradingController._replace_take_profit.__get__(
        controller, TradingController
    )

    return controller


@pytest.mark.asyncio
async def test_replace_take_profit_with_partial_targets(mock_controller, base_position):
    # Setup
    mock_controller._active_positions["BTCUSDT"] = base_position

    # New partial targets: 30% at 10200, 70% at 10800
    new_partial_targets = [(10200.0, 0.3, False), (10800.0, 0.7, False)]

    # Execute
    success = await mock_controller._replace_take_profit(
        symbol="BTCUSDT", new_tp_price=10800.0, partial_targets=new_partial_targets
    )

    # Assert
    assert success is True
    assert len(base_position.partial_tp_orders) == 2

    # Check that new partial orders were created with correct fractions and prices
    assert base_position.partial_tp_orders[0].target_price == 10200.0
    assert base_position.partial_tp_orders[0].orig_fraction == 0.3
    assert base_position.partial_tp_orders[0].quantity == 0.3  # 1.0 total qty * 0.3

    assert base_position.partial_tp_orders[1].target_price == 10800.0
    assert base_position.partial_tp_orders[1].orig_fraction == 0.7
    assert base_position.partial_tp_orders[1].quantity == 0.7


@pytest.mark.asyncio
async def test_replace_take_profit_without_partial_targets(
    mock_controller, base_position
):
    # Setup
    mock_controller._active_positions["BTCUSDT"] = base_position

    # Execute without partial targets (fallback logic)
    success = await mock_controller._replace_take_profit(
        symbol="BTCUSDT", new_tp_price=10800.0
    )

    # Assert
    assert success is True
    assert len(base_position.partial_tp_orders) == 1

    # Check that a single order was created for 100% of the quantity
    assert base_position.partial_tp_orders[0].target_price == 10800.0
    assert base_position.partial_tp_orders[0].orig_fraction == 1.0
    assert base_position.partial_tp_orders[0].quantity == 1.0
