# tests/test_controller_new_features.py
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import pandas as pd

from bot_module.controller import TradingController, LivePosition as Position
from bot_module.strategy import SignalDirection
from bot_module.data_consumer import DataConsumer


@pytest.fixture
def mock_loop():
    return MagicMock(spec=asyncio.AbstractEventLoop)


@pytest.fixture
def mock_data_consumer():
    # Use MagicMock with spec=DataConsumer so the isinstance check passes
    # and the controller didn't try to call it as a class.
    mock_instance = MagicMock(spec=DataConsumer)
    # Configuring asynchronous methods
    mock_instance.get_active_pair_by_symbol = AsyncMock(
        return_value={"last_price": 51000.0}
    )
    mock_instance.start = AsyncMock()
    mock_instance.stop = AsyncMock()
    mock_instance.get_latest_depth = AsyncMock(return_value={})
    return mock_instance


@pytest.fixture
def mock_executor():
    executor = AsyncMock()
    executor.place_order = AsyncMock(return_value={"error": False})
    return executor


@pytest.fixture
def mock_risk_manager():
    rm = AsyncMock()
    rm.calculate_scaled_in_quantity.return_value = 0.1
    # Mock the synchronous method used for adjustment as well
    rm._adjust_and_round_quantity = MagicMock(
        side_effect=lambda qty, *args, **kwargs: qty
    )
    return rm


@pytest.fixture
def mock_telegram_notifier():
    return AsyncMock()


@pytest.fixture
def trading_controller(
    mock_loop,
    mock_data_consumer,
    mock_executor,
    mock_risk_manager,
    mock_telegram_notifier,
):
    controller = TradingController(
        loop=mock_loop,
        data_consumer=mock_data_consumer,
        live_executor=mock_executor,
        paper_executor=MagicMock(),  # Added missing paper_executor
        risk_manager=mock_risk_manager,
        user_id=1,
        telegram_notifier=mock_telegram_notifier,
    )
    # Mock _get_market_info since it is used internally
    controller._get_market_info = AsyncMock(
        return_value={"stepSize": "0.001", "minQty": "0.001"}
    )

    # Add a mock for the strategy instance so _handle_event can find it
    mock_strategy_instance = AsyncMock()
    mock_strategy_instance.manage_position.return_value = (
        MagicMock(),
        None,
    )  # Return (position, no exit signal)
    controller.running_strategy_instances["mock_config_id"] = (
        mock_strategy_instance,
        {"config_id": "mock_config_id", "symbol_selection_mode": "DYNAMIC"},
    )

    # Leave executors as a dictionary, but put a mock in it.
    # This allows TradingController._executor_for_market_type to work correctly.
    controller.executors = {"live": mock_executor, "paper": MagicMock()}
    controller.live_executor = mock_executor

    # market_executors should contain the executors themselves, not dictionaries {'live': ...}
    controller.market_executors = {"futures_usdtm": mock_executor}

    return controller


@pytest.fixture
def mock_position():
    # Replace MagicMock with a real Position instance for **vars() to work correctly
    position = Position(
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        entry_price=50000.0,
        initial_quantity=1.0,
        remaining_quantity=1.0,
        entry_time=0,
        strategy="TestStrategy",
        initial_stop_loss=49500.0,
        current_sl_price=49500.0,
        initial_take_profit=55000.0,
        status="OPEN",
        number_of_entries=1,
        max_entries=3,
        market_type="futures_usdtm",
    )
    # Add mocks for rules since they are lists of dictionaries
    position.scale_in_rules = [
        {
            "type": "scale_in",
            "params": {"add_size_pct_of_initial_risk": 50, "max_entries": 3},
            "children": [{"type": "price_vs_level", "params": {}}],
        }
    ]
    position.conditional_management_rules = [
        {
            "type": "conditional_management",
            "if_conditions": {
                "type": "AND",
                "children": [{"type": "price_vs_level", "params": {}}],
            },
            "then_actions": [
                {
                    "type": "modify_stop_loss",
                    "params": {
                        "new_sl_price": {
                            "source": "position_state",
                            "key": "entry_price",
                        }
                    },
                }
            ],
        }
    ]
    # Mock config_id, which is used in _handle_event to find the strategy
    position.config_id = "mock_config_id"
    return position


@pytest.mark.asyncio
async def test_check_scale_in_conditions_met(trading_controller, mock_position):
    pair_info = {"last_price": 51000.0}  # Current price is needed for calculation
    with patch.object(
        trading_controller, "_evaluate_position_condition_tree", return_value=(True, {})
    ):
        await trading_controller._check_scale_in_conditions(mock_position, pair_info)

        trading_controller.rm.calculate_scaled_in_quantity.assert_called_once()
        trading_controller.live_executor.place_order.assert_called_once()
        # assert mock_position.number_of_entries == 2 # This field is updated in _handle_order_update, so we don't check it here


@pytest.mark.asyncio
async def test_execute_management_actions_modify_sl(trading_controller, mock_position):
    with patch.object(
        trading_controller, "_resolve_position_value", return_value=50000.0
    ):
        with patch.object(
            trading_controller, "_replace_stop_loss", new_callable=AsyncMock
        ) as mock_replace_sl:
            actions = mock_position.conditional_management_rules[0]["then_actions"]
            await trading_controller._execute_management_actions(
                mock_position, actions, {}, {}
            )

            # _replace_stop_loss takes symbol (str), not a position object
            mock_replace_sl.assert_called_once_with(
                mock_position.symbol, 50000.0, market_type="futures_usdtm"
            )


@pytest.mark.asyncio
async def test_handle_event_calls_new_logic(trading_controller, mock_position):
    # Get the mock strategy instance from the controller
    mock_strategy_instance = trading_controller.running_strategy_instances[
        "mock_config_id"
    ][0]

    # Ensure manage_position returns a correct tuple to avoid errors further on
    # Use a copy of the real position object instead of MagicMock to avoid TypeError when comparing floats
    import copy

    mocked_updated_pos = copy.deepcopy(mock_position)
    mocked_updated_pos.scale_in_triggered = None  # Indicate that there was no scaling
    mock_strategy_instance.manage_position.return_value = (mocked_updated_pos, None)

    trading_controller._active_positions["BTCUSDT"] = mock_position

    # Mock _gather_market_data_for_strategy so it returns a non-None value
    with patch.object(
        trading_controller,
        "_gather_market_data_for_strategy",
        return_value={"kline_1m": pd.DataFrame({"close": [100]})},
    ):
        # Simulating an event
        await trading_controller._handle_event(
            {"type": "CANDLE_CLOSE", "symbol": "BTCUSDT", "timestamp_ms": 0}
        )

        # Check that the correct method was called
        mock_strategy_instance.manage_position.assert_called_once()
