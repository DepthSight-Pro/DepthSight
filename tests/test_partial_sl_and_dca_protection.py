import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from bot_module.controller import TradingController, LivePosition
from bot_module.strategy import SignalDirection


@pytest.fixture
def mock_deps():
    consumer = AsyncMock()
    executor = AsyncMock()
    executor.market_type = "futures_usdtm"
    executor.cancel_order = AsyncMock(return_value={"status": "CANCELED"})
    executor.cancel_all_open_orders = AsyncMock(return_value={"status": "OK"})
    risk_manager = AsyncMock()
    risk_manager._adjust_and_round_quantity = MagicMock(
        side_effect=lambda q, symbol, price, lot_params, min_notional: round(q, 6)
    )
    trade_logger = MagicMock()
    telegram_notifier = MagicMock()
    return {
        "consumer": consumer,
        "executor": executor,
        "risk_manager": risk_manager,
        "trade_logger": trade_logger,
        "telegram_notifier": telegram_notifier,
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
            telegram_notifier=mock_deps["telegram_notifier"],
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
async def test_partial_sl_fill_triggers_emergency_close(controller, mock_deps):
    """Verify that a partial SL fill detects remainder and triggers emergency close with alert."""
    symbol = "ETHUSDT"
    pos = LivePosition(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=2500.0,
        initial_quantity=0.017,
        remaining_quantity=0.017,
        entry_time=123.0,
        strategy="Test",
        status="OPEN",
        current_sl_order_id=555,
        current_sl_client_order_id="x-sl-test-123",
        current_sl_price=2480.0,
        mode="live",
        market_type="futures_usdtm",
    )
    controller._active_positions[symbol] = pos

    controller.close_position = AsyncMock()
    controller._handle_final_exit = AsyncMock()

    order_update_event = {
        "e": "ORDER_TRADE_UPDATE",
        "o": {
            "s": symbol,
            "i": 555,
            "c": "x-sl-test-123",
            "X": "FILLED",
            "x": "TRADE",
            "z": "0.011",  # Partial: 0.011 < 0.017!
            "q": "0.011",
            "ap": "2480.0",
            "L": "2480.0",
            "l": "0.011",
            "n": "0.01",
            "N": "USDT",
            "S": "SELL",
            "ot": "STOP_MARKET",
            "rp": "-0.22",
        },
    }

    await controller._handle_order_update(order_update_event)
    await asyncio.sleep(0.05)

    # Remainder should be 0.006
    assert pos.remaining_quantity == pytest.approx(0.006)
    # Emergency close should have been called for remainder
    controller.close_position.assert_called_once_with(
        symbol, reason="SL_PARTIAL_REMAINDER", market_type="futures_usdtm"
    )
    # _handle_final_exit should NOT have been called yet
    controller._handle_final_exit.assert_not_called()
    # Telegram alert should have been sent
    assert mock_deps["telegram_notifier"].bot_error.called
    assert (
        "PARTIAL SL DETECTED"
        in mock_deps["telegram_notifier"].bot_error.call_args[0][0]
    )
    # Trade logger event logged
    events = [
        call.kwargs.get("event_type")
        for call in mock_deps["trade_logger"].log_event.call_args_list
    ]
    assert "SL_PARTIAL_FILL_DETECTED" in events


@pytest.mark.asyncio
async def test_full_sl_fill_normal_exit(controller, mock_deps):
    """Verify that a full SL fill triggers _handle_final_exit normally."""
    symbol = "ETHUSDT"
    pos = LivePosition(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=2500.0,
        initial_quantity=0.017,
        remaining_quantity=0.017,
        entry_time=123.0,
        strategy="Test",
        status="OPEN",
        current_sl_order_id=555,
        current_sl_client_order_id="x-sl-test-123",
        current_sl_price=2480.0,
        mode="live",
        market_type="futures_usdtm",
    )
    controller._active_positions[symbol] = pos

    controller.close_position = AsyncMock()
    controller._handle_final_exit = AsyncMock()

    order_update_event = {
        "e": "ORDER_TRADE_UPDATE",
        "o": {
            "s": symbol,
            "i": 555,
            "c": "x-sl-test-123",
            "X": "FILLED",
            "x": "TRADE",
            "z": "0.017",  # Full: 0.017 == 0.017
            "q": "0.017",
            "ap": "2480.0",
            "L": "2480.0",
            "l": "0.017",
            "n": "0.01",
            "N": "USDT",
            "S": "SELL",
            "ot": "STOP_MARKET",
            "rp": "-0.34",
        },
    }

    await controller._handle_order_update(order_update_event)
    await asyncio.sleep(0.05)

    controller._handle_final_exit.assert_called_once()
    controller.close_position.assert_not_called()


@pytest.mark.asyncio
async def test_sl_replace_failure_retries_and_alerts(controller, mock_deps):
    """Verify that SL replacement failure retries 3 times, sets sl_coverage_incomplete, and alerts."""
    symbol = "ETHUSDT"
    pos = LivePosition(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=2500.0,
        initial_quantity=0.017,
        remaining_quantity=0.017,
        entry_time=123.0,
        strategy="Test",
        status="OPEN",
        current_sl_order_id=111,
        current_sl_client_order_id="x-sl-old",
        current_sl_price=2480.0,
        mode="live",
        market_type="futures_usdtm",
    )
    controller._active_positions[symbol] = pos

    # Simulate _place_stop_loss always failing
    controller._place_stop_loss = AsyncMock(return_value=False)
    controller.close_position = AsyncMock()

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await controller._replace_stop_loss(
            symbol, 2485.0, market_type="futures_usdtm"
        )

    assert res is False
    # Initial call + 3 retries = 4 attempts
    assert controller._place_stop_loss.call_count == 4
    # 1 sleep during cancel_old_sl (0.1s) + 3 retries (2.0s, 4.0s, 8.0s) = 4 sleep calls
    assert mock_sleep.call_count == 4
    # Emergency market close scheduled
    controller.close_position.assert_called_once_with(
        symbol, reason="EMERGENCY_SL_REPLACE_FAILED", market_type="futures_usdtm"
    )
    # Telegram alert sent
    assert mock_deps["telegram_notifier"].bot_error.called
    assert (
        "CRITICAL: SL PLACEMENT FAILED"
        in mock_deps["telegram_notifier"].bot_error.call_args[0][0]
    )
    # Trade logger logged failure
    events = [
        call.kwargs.get("event_type")
        for call in mock_deps["trade_logger"].log_event.call_args_list
    ]
    assert "SL_ORDER_MOVED_FAILED" in events


@pytest.mark.asyncio
async def test_dca_grid_skips_orders_beyond_current_market_price(controller, mock_deps):
    """Verify that DCA grid skips orders whose limit price is at or beyond current market price."""
    symbol = "BTCUSDT"
    position = LivePosition(
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
        mode="live",
        market_type="futures_usdtm",
    )
    controller._active_positions[symbol] = position

    dca_params = {
        "max_safety_orders": 2,
        "step_type": "percentage",
        "step_value": 2.0,  # SO 1: 98.0
        "step_multiplier": 1.5,  # SO 2: 95.0
        "volume_multiplier": 2.0,
    }

    mock_deps["executor"].place_order.return_value = {"orderId": 999, "status": "NEW"}

    # Market price has already dropped to 96.0!
    # SO 1 price is 98.0 >= 96.0 -> MUST BE SKIPPED (would fill as taker)
    # SO 2 price is 95.0 < 96.0 -> MUST BE PLACED
    pair_info = {"last_price": 96.0, "symbol": symbol, "atr": 1.0}

    await controller._execute_dca_grid(position, dca_params, pair_info)

    # Only 1 order placed (SO 2), SO 1 was skipped
    assert mock_deps["executor"].place_order.call_count == 1
    call = mock_deps["executor"].place_order.call_args
    assert float(call.kwargs["price"]) == 95.0


@pytest.mark.asyncio
async def test_dca_grid_caps_base_qty_for_adopted_position(controller, mock_deps):
    """Verify that DCA grid on adopted position caps base_qty to remaining_quantity."""
    symbol = "ETHUSDT"
    position = LivePosition(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=2500.0,
        initial_quantity=0.010,  # Blown-up initial_quantity
        remaining_quantity=0.006,  # Actual remaining quantity on exchange
        status="OPEN",
        entry_client_order_id="x-entry-123_orphan_abc123",
        entry_time=123.0,
        strategy="Test",
        initial_stop_loss=2400.0,
        current_sl_price=2400.0,
        initial_take_profit=2600.0,
        mode="live",
        market_type="futures_usdtm",
        is_adopted=True,
    )
    controller._active_positions[symbol] = position

    dca_params = {
        "max_safety_orders": 1,
        "step_type": "percentage",
        "step_value": 2.0,
        "step_multiplier": 1.0,
        "volume_multiplier": 1.3,
    }

    mock_deps["executor"].place_order.return_value = {"orderId": 999, "status": "NEW"}
    pair_info = {"last_price": 2500.0, "symbol": symbol, "atr": 10.0}

    await controller._execute_dca_grid(position, dca_params, pair_info)

    assert mock_deps["executor"].place_order.call_count == 1
    call = mock_deps["executor"].place_order.call_args
    # base_qty should be capped to 0.006, so SO 1 qty = 0.006 * 1.3 = 0.0078
    assert float(call.kwargs["quantity"]) == pytest.approx(0.0078)


@pytest.mark.asyncio
async def test_build_adopted_position_unique_client_id(controller, mock_deps):
    """Verify that _build_adopted_position generates unique client_id with _orphan_ and sets is_adopted."""
    symbol = "ETHUSDT"
    exch_data = {
        "positionAmt": 0.006,
        "entryPrice": 2500.0,
        "symbol": symbol,
    }

    mock_trade = MagicMock()
    mock_trade.strategy_config = MagicMock()
    mock_trade.strategy_config.name = "TestStrategy"
    mock_trade.strategy_config_id = 10
    mock_trade.trade_uuid = "x-entry-39a86f32cc7444"

    mock_deps["executor"].get_open_orders = AsyncMock(return_value=[])

    with patch(
        "api.crud.get_last_open_trade_for_symbol", AsyncMock(return_value=mock_trade)
    ):

        async def fake_session():
            yield MagicMock()

        controller.get_db_session = fake_session

        adopted = await controller._build_adopted_position(
            symbol, exch_data, "futures_usdtm", mock_deps["executor"]
        )

    assert adopted is not None
    assert adopted.is_adopted is True
    assert adopted.initial_quantity == 0.006
    assert adopted.remaining_quantity == 0.006
    assert adopted.entry_client_order_id.startswith("x-entry-39a86f32cc7444_orphan_")
    assert adopted.entry_client_order_id != "x-entry-39a86f32cc7444"
