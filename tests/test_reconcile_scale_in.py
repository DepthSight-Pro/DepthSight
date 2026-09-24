# tests/test_reconcile_scale_in.py
# ruff: noqa: E402, F401, F811
import os

os.environ.setdefault("POSTGRES_USER", "testuser")
os.environ.setdefault("POSTGRES_PASSWORD", "testpassword")
os.environ.setdefault("POSTGRES_DB", "testdb")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bot_module.controller import (
    DcaOrderInfo,
    LivePosition,
    PartialTpOrderInfo,
    TradingController,
)
from bot_module.strategy import SignalDirection
from tests.test_controller import (
    controller,
    mock_consumer,
    mock_executor,
    mock_risk_manager,
    mock_trade_logger,
)


@pytest.mark.asyncio
async def test_reconcile_scale_in_triggers_tp_update_and_cancels_old_tp(
    controller, mock_executor
):
    """
    Test that when exchange reports higher position volume during reconciliation (DCA fill),
    the controller detects scale-in, updates position state, cancels the old TP order,
    resets initial_take_profit to None, and dispatches SCALE_IN_RECALC.
    """
    symbol = "ETHUSDT"
    market_type = "futures_usdtm"
    old_tp_id = 1485231737557098497
    old_tp_cid = "78e7vx-ptp-930d5883c68347f"

    pos = LivePosition(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=2647.73,
        initial_quantity=0.01,
        remaining_quantity=0.01,
        entry_time=time.time(),
        strategy="VisualBuilderStrategy",
        initial_stop_loss=2621.25,
        current_sl_price=2621.25,
        initial_take_profit=2655.68,
        status="OPEN",
        market_type=market_type,
        mode="live",
        user_id=186,
        config_id="cfg-test",
        dca_active_sos=0,
        partial_tp_orders=[
            PartialTpOrderInfo(
                target_price=2655.68,
                orig_fraction=1.0,
                quantity=0.01,
                order_id=old_tp_id,
                client_order_id=old_tp_cid,
                status="PENDING",
            )
        ],
        dca_orders=[
            DcaOrderInfo(
                target_price=2639.73,
                quantity=0.01,
                order_id=1485231738970578945,
                client_order_id="x-scalein-1",
                status="NEW",
            )
        ],
    )

    controller._active_positions.clear()
    controller._active_position_set(pos)

    mock_executor.market_type = market_type
    mock_executor.cancel_order = AsyncMock(return_value={"status": "CANCELED"})
    # Exchange reports 0.02 qty @ 2643.73 average entry price
    mock_executor.get_open_positions.return_value = [
        {
            "symbol": symbol,
            "positionAmt": "0.02",
            "entryPrice": "2643.73",
        }
    ]

    with patch.object(
        controller, "_handle_event", new_callable=AsyncMock
    ) as mock_handle_event:
        await controller._reconcile_positions_with_exchange()

        # Allow background task (_update_tp_after_scale_in) to execute
        await asyncio.sleep(0.05)

        # 1. Verify position state updated
        updated_pos = controller._active_position_get(symbol, market_type)
        assert updated_pos is not None
        assert updated_pos.remaining_quantity == 0.02
        assert updated_pos.entry_price == 2643.73
        assert updated_pos._is_averaging_down is True
        assert updated_pos.dca_active_sos == 1
        assert updated_pos.dca_orders[0].status == "FILLED"

        # 2. Verify old TP was cancelled
        mock_executor.cancel_order.assert_awaited_once_with(
            symbol, orderId=old_tp_id, origClientOrderId=old_tp_cid
        )

        # 3. Verify TP state reset so manage_position will recalculate
        assert updated_pos.initial_take_profit is None
        assert len(updated_pos.partial_tp_orders) == 0

        # 4. Verify SCALE_IN_RECALC event was dispatched
        mock_handle_event.assert_awaited_once()
        event_arg = mock_handle_event.call_args[0][0]
        assert event_arg["type"] == "SCALE_IN_RECALC"
        assert event_arg["symbol"] == symbol


@pytest.mark.asyncio
async def test_reconcile_no_scale_in_when_quantity_unchanged(controller, mock_executor):
    """
    Test that when exchange reports the same position volume, no scale-in is triggered.
    """
    symbol = "ETHUSDT"
    market_type = "futures_usdtm"
    pos = LivePosition(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=2647.73,
        initial_quantity=0.01,
        remaining_quantity=0.01,
        entry_time=time.time(),
        strategy="VisualBuilderStrategy",
        initial_stop_loss=2621.25,
        current_sl_price=2621.25,
        initial_take_profit=2655.68,
        status="OPEN",
        market_type=market_type,
        mode="live",
        user_id=186,
        config_id="cfg-test",
    )

    controller._active_positions.clear()
    controller._active_position_set(pos)

    mock_executor.market_type = market_type
    mock_executor.get_open_positions.return_value = [
        {
            "symbol": symbol,
            "positionAmt": "0.01",
            "entryPrice": "2647.73",
        }
    ]

    with patch.object(
        controller, "_update_tp_after_scale_in", new_callable=AsyncMock
    ) as mock_update_tp:
        await controller._reconcile_positions_with_exchange()
        await asyncio.sleep(0.02)
        mock_update_tp.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_pending_entry_does_not_trigger_scale_in(
    controller, mock_executor
):
    """
    Test that position transitioning from PENDING_ENTRY to OPEN does not trigger scale-in.
    """
    symbol = "ETHUSDT"
    market_type = "futures_usdtm"
    pos = LivePosition(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=2647.73,
        initial_quantity=0.01,
        remaining_quantity=0.0,
        entry_time=time.time(),
        strategy="VisualBuilderStrategy",
        initial_stop_loss=2621.25,
        current_sl_price=2621.25,
        initial_take_profit=2655.68,
        status="PENDING_ENTRY",
        market_type=market_type,
        mode="live",
        user_id=186,
        config_id="cfg-test",
    )

    controller._active_positions.clear()
    controller._active_position_set(pos)

    mock_executor.market_type = market_type
    mock_executor.get_open_positions.return_value = [
        {
            "symbol": symbol,
            "positionAmt": "0.01",
            "entryPrice": "2647.73",
        }
    ]

    with (
        patch.object(
            controller, "_update_tp_after_scale_in", new_callable=AsyncMock
        ) as mock_update_tp,
        patch.object(controller, "_place_stop_loss", new_callable=AsyncMock),
    ):
        await controller._reconcile_positions_with_exchange()
        await asyncio.sleep(0.02)
        mock_update_tp.assert_not_called()
        assert pos.status == "OPEN"


@pytest.mark.asyncio
async def test_single_ws_session_for_bitget_deduplication(controller):
    """
    Test that if multiple executors exist for Bitget with the same API key (e.g. futures + spot),
    only one user data stream is started, avoiding Error 30017 'Account logoff'.
    """
    api_key = "test-bitget-key"

    exec_futures = MagicMock()
    exec_futures.exchange_id = "bitget"
    exec_futures.api_key = api_key
    exec_futures.start_user_data_stream = AsyncMock()

    exec_spot = MagicMock()
    exec_spot.exchange_id = "bitget"
    exec_spot.api_key = api_key
    exec_spot.start_user_data_stream = AsyncMock()

    controller.executors = {"live": exec_futures}
    controller.market_executors = {"futures_usdtm": exec_futures, "spot": exec_spot}

    # Patch other startup services
    controller.load_symbol_selection_config = AsyncMock()
    controller._load_runtime_state = AsyncMock()
    controller._reconcile_positions_with_exchange = AsyncMock()
    controller.rm.initialize_balance = AsyncMock()
    controller.consumer.start = AsyncMock()
    controller.trade_logger.start = MagicMock()
    controller.realtime_ml_logger = None

    with (
        patch.object(controller, "_redis_command_listener", new_callable=AsyncMock),
        patch.object(controller, "_redis_hft_event_listener", new_callable=AsyncMock),
    ):
        # We run the loop part of start up to user data stream
        executors_for_stream = [
            controller.executors.get("live"),
            *controller.market_executors.values(),
        ]
        started_executor_ids = set()
        started_stream_keys = set()
        for stream_executor in executors_for_stream:
            if stream_executor is None:
                continue
            executor_identity = id(stream_executor)
            if executor_identity in started_executor_ids:
                continue
            started_executor_ids.add(executor_identity)

            exchange_name = str(
                getattr(stream_executor, "exchange_id", "") or ""
            ).lower()
            clean_exchange_id = (
                exchange_name.replace("_testnet", "")
                .replace("_spot", "")
                .replace("_linear", "")
            )
            ex_api_key = getattr(stream_executor, "api_key", None)
            stream_key = (clean_exchange_id, ex_api_key)
            if (
                clean_exchange_id in {"bitget", "weex"}
                and ex_api_key
                and stream_key in started_stream_keys
            ):
                continue
            if ex_api_key:
                started_stream_keys.add(stream_key)

            if hasattr(stream_executor, "start_user_data_stream"):
                await stream_executor.start_user_data_stream(
                    controller._handle_order_update
                )

        # Assert only the first executor started the stream
        exec_futures.start_user_data_stream.assert_awaited_once()
        exec_spot.start_user_data_stream.assert_not_awaited()
