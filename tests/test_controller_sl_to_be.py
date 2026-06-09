# tests/test_controller_sl_to_be.py
import asyncio
import pytest
import pytest_asyncio
import time
from unittest.mock import MagicMock, AsyncMock, patch
import uuid

from bot_module.controller import (
    TradingController,
    LivePosition as Position,
    PartialTpOrderInfo,
)
from bot_module.strategy import SignalDirection
from bot_module import config as real_config
from bot_module.risk_manager import RiskManager


@pytest.fixture
def mock_data_consumer():
    mock_instance = AsyncMock()
    mock_instance.get_active_symbols.return_value = set()
    mock_instance.get_active_pairs.return_value = []
    mock_instance.start = AsyncMock()
    mock_instance.stop = AsyncMock()
    mock_instance.clear_all_subscriptions = AsyncMock()
    return mock_instance  # Return the instance itself


@pytest.fixture
def mock_executor():
    executor = AsyncMock()
    executor.market_type = "futures_usdtm"

    async def place_order_side_effect(*args, **kwargs):
        return {
            "error": False,
            "orderId": int(time.time() * 10000 + hash(str(kwargs))),
            "clientOrderId": kwargs.get(
                "newClientOrderId", f"mock-cid-{uuid.uuid4().hex[:8]}"
            ),
            "status": "NEW",
        }

    async def cancel_order_side_effect(*args, **kwargs):
        return {"error": False, "status": "CANCELED"}

    executor.place_order.side_effect = place_order_side_effect
    executor.cancel_order.side_effect = cancel_order_side_effect
    executor.fetch_exchange_info.return_value = {
        "symbols": [
            {
                "symbol": "TESTUSDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.001",
                        "maxQty": "10000",
                        "stepSize": "0.001",
                    },
                    {"filterType": "MIN_NOTIONAL", "minNotional": "5.0"},
                ],
            }
        ]
    }
    executor.start_user_data_stream = AsyncMock()
    executor.stop_user_data_stream = AsyncMock()
    return executor


@pytest.fixture
def mock_risk_manager():
    """Creates a full RiskManager mock with a fix for the synchronous method."""
    rm = AsyncMock(spec=RiskManager)
    rm.initialize_balance = AsyncMock()
    rm.assess_signal.return_value = (True, 10.0, 5.0)
    rm.update_trade_result = AsyncMock()
    rm.update_symbol_strategy_performance = AsyncMock()
    rm.is_symbol_trading_allowed.return_value = True
    rm.save_state = AsyncMock()

    # Explicitly mock the SYNCHRONOUS method using MagicMock
    rm._adjust_and_round_quantity = MagicMock(
        side_effect=lambda qty, *args, **kwargs: qty if qty is not None else 0.0
    )

    rm.stats = MagicMock()
    rm.stats.current_balance = 10000.0
    return rm


@pytest.fixture
def mock_trade_logger():
    logger_mock = MagicMock()
    logger_mock.log_event = MagicMock()
    logger_mock.start = MagicMock()
    logger_mock.stop = MagicMock()
    return logger_mock


@pytest.fixture
def mock_realtime_ml_logger():
    logger_mock = MagicMock()
    logger_mock.log_data = MagicMock()
    logger_mock.start = MagicMock()
    logger_mock.stop = MagicMock()
    return logger_mock


@pytest_asyncio.fixture
async def controller(
    mock_data_consumer,
    mock_executor,
    mock_risk_manager,
    mock_trade_logger,
    mock_realtime_ml_logger,
):
    with (
        patch(
            "bot_module.config.get_strategy_param",
            side_effect=lambda strategy, param, default: default,
        ),
        patch("bot_module.config.load_optimized_params"),
        patch.object(real_config, "SYMBOL_COOLDOWN_SECONDS", 1),
        patch.object(real_config, "PENDING_ENTRY_CHECK_INTERVAL_SECONDS", 5),
        patch.object(real_config, "LIMIT_ORDER_MAX_LIFETIME_SECONDS", 10),
        patch.object(real_config, "BE_SL_OFFSET_TICKS", 1),
        patch.object(real_config, "BE_MOVE_RETRY_DELAY_SECONDS", 0.1),
        patch.object(real_config, "LOG_REALTIME_ML_DATA", False),
    ):
        ctrl = TradingController(
            loop=asyncio.get_running_loop(),
            data_consumer=mock_data_consumer,
            live_executor=mock_executor,
            paper_executor=mock_executor,
            risk_manager=mock_risk_manager,
            user_id=1,
        )
        ctrl.trade_logger = mock_trade_logger
        ctrl.realtime_ml_logger = mock_realtime_ml_logger
        await ctrl._update_market_info_cache()
        yield ctrl


@pytest.mark.asyncio
async def test_sl_moves_to_be_after_first_tp(
    controller: TradingController, mock_executor: MagicMock
):
    symbol = "TESTUSDT"
    entry_price_val = 100.0
    initial_sl_price = 98.0
    first_tp_price = 101.0
    initial_qty = 10.0

    async def mock_get_market_info(sym, key, **kwargs):
        if sym == symbol:
            if key == "tick_size":
                return 0.01
            if key == "lot_params":
                return {"minQty": 0.001, "maxQty": 10000.0, "stepSize": 0.001}
        return None

    controller._get_market_info = AsyncMock(side_effect=mock_get_market_info)

    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=entry_price_val,
        initial_quantity=initial_qty,
        remaining_quantity=initial_qty,
        entry_time=time.time(),
        strategy="TestStrategy",
        initial_stop_loss=initial_sl_price,
        current_sl_price=initial_sl_price,
        initial_take_profit=102.0,
        entry_order_id=1000,
        entry_client_order_id="test-entry-1",
        entry_order_status="FILLED",
        status="OPEN",
        move_sl_to_be_enabled=True,
        is_stop_at_be=False,
        partial_tp_orders=[
            PartialTpOrderInfo(
                target_price=first_tp_price,
                orig_fraction=0.5,
                quantity=5.0,
                status="PENDING",
                client_order_id="ptp-1-placed",
                order_id=3001,
            ),
            PartialTpOrderInfo(
                target_price=102.0,
                orig_fraction=0.5,
                quantity=5.0,
                status="PENDING",
                client_order_id="ptp-2-placed",
                order_id=3002,
            ),
        ],
        sl_placement_initiated=True,
        current_sl_order_id=2000,
        current_sl_client_order_id="initial-sl-1",
    )
    async with controller._positions_dict_lock:
        controller._active_position_set(position)

    first_tp_order_id = 3001
    first_tp_client_order_id = "ptp-1-placed"

    tp_fill_event_data = {
        "e": "ORDER_TRADE_UPDATE",
        "o": {
            "s": symbol,
            "c": first_tp_client_order_id,
            "i": first_tp_order_id,
            "S": "SELL",
            "ot": "LIMIT",
            "x": "TRADE",
            "X": "FILLED",
            "l": "5.0",
            "z": "5.0",
            "L": str(first_tp_price),
        },
    }

    # Use asyncio.Event for reliable synchronization
    sl_placement_finished_event = asyncio.Event()
    original_place_sl = controller._place_stop_loss

    async def place_sl_wrapper(*args, **kwargs):
        # Call the real method
        result = await original_place_sl(*args, **kwargs)
        # Signal that the method has completed
        sl_placement_finished_event.set()
        return result

    mock_executor.cancel_order.reset_mock()
    mock_executor.place_order.reset_mock()

    with patch.object(controller, "_place_stop_loss", side_effect=place_sl_wrapper):
        await controller._handle_order_update(tp_fill_event_data)

        # Wait until _place_stop_loss is called and completes
        try:
            await asyncio.wait_for(sl_placement_finished_event.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail("Method _place_stop_loss was not called within 2 seconds.")

    expected_be_sl_price = round(
        entry_price_val + (0.01 * real_config.BE_SL_OFFSET_TICKS), 2
    )

    # Checks should now pass, as we have waited for the entire chain to complete
    mock_executor.cancel_order.assert_any_call(
        symbol=symbol,
        orderId=2000,
        origClientOrderId="initial-sl-1",
        is_algo_order=False,
    )

    found_new_sl_placement = False
    for call_item in mock_executor.place_order.call_args_list:
        _, kwargs_call = call_item
        if (
            kwargs_call.get("order_type") == "STOP_MARKET"
            and kwargs_call.get("symbol") == symbol
        ):
            assert (
                abs(float(kwargs_call.get("stopPrice", 0)) - expected_be_sl_price)
                < 0.001
            )
            assert (
                abs(float(kwargs_call.get("quantity", 0)) - (initial_qty - 5.0)) < 1e-9
            )
            assert kwargs_call.get("reduceOnly") == "true"
            found_new_sl_placement = True
            break
    assert found_new_sl_placement, (
        f"New SL order with BE price {expected_be_sl_price} was not placed. Calls: {mock_executor.place_order.call_args_list}"
    )

    async with controller._positions_dict_lock:
        final_position = controller._active_position_get(symbol)
        assert final_position is not None
        assert final_position.is_stop_at_be is True
