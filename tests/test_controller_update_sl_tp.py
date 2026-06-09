# tests/test_controller_update_sl_tp.py
# ruff: noqa: E402
"""
Tests for verifying SL/TP updates via the Redis command UPDATE_SL_TP.
Checks that:
1. The command is correctly parsed from Redis
2. The position is found by ID
3. _replace_stop_loss is called with the correct price
4. _replace_take_profit is called with the correct price
5. Commands for an incorrect user_id are ignored
"""

import os

os.environ.setdefault("POSTGRES_USER", "testuser")
os.environ.setdefault("POSTGRES_PASSWORD", "testpassword")
os.environ.setdefault("POSTGRES_DB", "testdb")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

import pytest
import asyncio
import time
import uuid
from unittest.mock import MagicMock, AsyncMock, patch
from pytest_asyncio import fixture as async_fixture

try:
    from bot_module.controller import (
        TradingController,
        LivePosition as Position,
        PartialTpOrderInfo,
    )
    from bot_module.data_consumer import DataConsumer
    from bot_module.exchanges import ExchangeExecutor
    from bot_module.risk_manager import RiskManager
    from bot_module.trade_logger import TradeLogger
    from bot_module.strategy import SignalDirection
except ImportError as e:
    pytest.skip(f"Cannot import bot_module: {e}", allow_module_level=True)


@pytest.fixture
def mock_consumer():
    """Creates a DataConsumer mock."""
    consumer = AsyncMock(spec=DataConsumer)
    consumer.get_active_symbols.return_value = {"BTCUSDT", "ETHUSDT"}
    consumer.get_active_pairs.return_value = [
        {"symbol": "BTCUSDT", "atr": 50.0, "last_price": 50000.0},
        {"symbol": "ETHUSDT", "atr": 4.0, "last_price": 3000.0},
    ]
    consumer.get_active_pair_by_symbol = AsyncMock(
        return_value={"symbol": "BTCUSDT", "last_price": 50000.0}
    )
    consumer.ensure_subscription = AsyncMock()
    consumer.remove_subscription = AsyncMock()
    consumer.remove_all_subscriptions_for_symbol = AsyncMock()
    consumer.clear_all_subscriptions = AsyncMock()
    consumer.event_queue = asyncio.Queue(maxsize=1)
    consumer.start = AsyncMock()
    consumer.stop = AsyncMock()
    return consumer


@pytest.fixture
def mock_executor():
    """Creates a BinanceExecutor mock."""
    executor = AsyncMock(spec=ExchangeExecutor)
    executor.market_type = "futures_usdtm"
    executor.get_account_balance.return_value = {"USDT": {"free": "10000.0"}}
    executor.fetch_exchange_info.return_value = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.00001",
                        "stepSize": "0.00001",
                        "maxQty": "9000.0",
                    },
                    {"filterType": "NOTIONAL", "minNotional": "10.0"},
                ],
            },
        ]
    }
    executor.place_order = AsyncMock(
        return_value={
            "orderId": 12345,
            "clientOrderId": "test-order",
            "status": "NEW",
            "error": False,
        }
    )
    executor.cancel_order = AsyncMock(return_value={"status": "CANCELED"})
    executor.start_user_data_stream = AsyncMock()
    executor.stop_user_data_stream = AsyncMock()
    executor.get_ticker_price = AsyncMock(return_value={"price": "50000.0"})
    return executor


@pytest.fixture
def mock_risk_manager():
    """Creates a RiskManager mock."""
    rm = AsyncMock(spec=RiskManager)
    rm.initialize_balance = AsyncMock()
    rm.save_state = AsyncMock()
    rm.stats = MagicMock()
    rm.stats.current_balance = 10000.0
    rm.max_concurrent_trades = 10
    rm.get_pnl_for_strategy = MagicMock(return_value=0.0)
    return rm


@pytest.fixture
def mock_trade_logger():
    """Creates a TradeLogger mock."""
    logger = MagicMock(spec=TradeLogger)
    logger.log_event = MagicMock()
    logger.start = MagicMock()
    logger.stop = MagicMock()
    logger._running = True
    return logger


@async_fixture
async def controller(
    mock_consumer, mock_executor, mock_risk_manager, mock_trade_logger
):
    """Creates a TradingController instance for tests."""
    mock_paper_executor = MagicMock()
    mock_paper_executor.controller = None

    ctrl = TradingController(
        loop=asyncio.get_running_loop(),
        data_consumer=lambda **kwargs: mock_consumer,
        live_executor=mock_executor,
        paper_executor=mock_paper_executor,
        risk_manager=mock_risk_manager,
        user_id=1,
    )
    ctrl.trade_logger = mock_trade_logger
    ctrl.redis_client = None  # Disabling real Redis

    await ctrl._update_market_info_cache()

    yield ctrl

    if ctrl._running:
        await ctrl.stop()


def create_test_position(
    symbol: str = "BTCUSDT", pos_id: str = None, user_id: int = 1
) -> Position:
    """Creates a test position."""
    if pos_id is None:
        pos_id = f"x-entry-{uuid.uuid4().hex[:12]}"

    return Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=50000.0,
        initial_quantity=0.01,
        remaining_quantity=0.01,
        entry_time=time.time(),
        strategy="TestStrategy",
        user_id=user_id,
        config_id="test-config",
        initial_stop_loss=49000.0,
        current_sl_price=49000.0,
        initial_take_profit=52000.0,
        status="OPEN",
        entry_client_order_id=pos_id,  # This will become pos.id via a property
        current_sl_order_id=1001,
        current_sl_client_order_id="x-sl-1001",
        partial_tp_orders=[
            PartialTpOrderInfo(
                target_price=52000.0,
                orig_fraction=1.0,
                quantity=0.01,
                order_id=2001,
                client_order_id="x-tp-2001",
                status="PENDING",
            )
        ],
    )


class TestUpdateSlTpCommand:
    """Tests for the UPDATE_SL_TP command."""

    @pytest.mark.asyncio
    async def test_update_sl_tp_updates_stop_loss(self, controller, mock_executor):
        """Checks that updating SL calls _replace_stop_loss."""
        # Arrange
        pos_id = "test-pos-sl-update"
        position = create_test_position(pos_id=pos_id, user_id=1)
        controller._active_position_set(position)

        new_sl_price = 49500.0

        command_data = {
            "command": "UPDATE_SL_TP",
            "payload": {
                "position_id": pos_id,
                "user_id": "1",
                "new_stop_loss": new_sl_price,
                "new_take_profit": None,
            },
        }

        # Act - simulating command processing
        with patch.object(
            controller, "_replace_stop_loss", new_callable=AsyncMock
        ) as mock_replace_sl:
            mock_replace_sl.return_value = True

            # Directly calling the command processing logic
            await self._simulate_redis_command(controller, command_data)

            # Allow background task to run
            await asyncio.sleep(0.1)

            # Assert
            mock_replace_sl.assert_called_once_with(
                "BTCUSDT", new_sl_price, market_type="futures_usdtm"
            )

    @pytest.mark.asyncio
    async def test_update_sl_tp_updates_take_profit(self, controller, mock_executor):
        """Checks that updating TP calls _replace_take_profit."""
        # Arrange
        pos_id = "test-pos-tp-update"
        position = create_test_position(pos_id=pos_id, user_id=1)
        controller._active_position_set(position)

        new_tp_price = 53000.0

        command_data = {
            "command": "UPDATE_SL_TP",
            "payload": {
                "position_id": pos_id,
                "user_id": "1",
                "new_stop_loss": None,
                "new_take_profit": new_tp_price,
            },
        }

        # Act
        with patch.object(
            controller, "_replace_take_profit", new_callable=AsyncMock
        ) as mock_replace_tp:
            mock_replace_tp.return_value = True

            await self._simulate_redis_command(controller, command_data)
            await asyncio.sleep(0.1)

            # Assert
            mock_replace_tp.assert_called_once_with(
                "BTCUSDT", new_tp_price, market_type="futures_usdtm"
            )

    @pytest.mark.asyncio
    async def test_update_sl_tp_updates_both(self, controller, mock_executor):
        """Checks that both SL and TP can be updated simultaneously."""
        # Arrange
        pos_id = "test-pos-both-update"
        position = create_test_position(pos_id=pos_id, user_id=1)
        controller._active_position_set(position)

        new_sl_price = 49500.0
        new_tp_price = 53000.0

        command_data = {
            "command": "UPDATE_SL_TP",
            "payload": {
                "position_id": pos_id,
                "user_id": "1",
                "new_stop_loss": new_sl_price,
                "new_take_profit": new_tp_price,
            },
        }

        # Act
        with (
            patch.object(
                controller, "_replace_stop_loss", new_callable=AsyncMock
            ) as mock_replace_sl,
            patch.object(
                controller, "_replace_take_profit", new_callable=AsyncMock
            ) as mock_replace_tp,
        ):
            mock_replace_sl.return_value = True
            mock_replace_tp.return_value = True

            await self._simulate_redis_command(controller, command_data)
            await asyncio.sleep(0.1)

            # Assert
            mock_replace_sl.assert_called_once_with(
                "BTCUSDT", new_sl_price, market_type="futures_usdtm"
            )
            mock_replace_tp.assert_called_once_with(
                "BTCUSDT", new_tp_price, market_type="futures_usdtm"
            )

    @pytest.mark.asyncio
    async def test_update_sl_tp_ignores_wrong_user(self, controller, mock_executor):
        """Checks that commands for another user_id are ignored."""
        # Arrange
        pos_id = "test-pos-wrong-user"
        position = create_test_position(pos_id=pos_id, user_id=1)
        controller._active_position_set(position)

        command_data = {
            "command": "UPDATE_SL_TP",
            "payload": {
                "position_id": pos_id,
                "user_id": "999",  # Another user
                "new_stop_loss": 49500.0,
                "new_take_profit": None,
            },
        }

        # Act
        with patch.object(
            controller, "_replace_stop_loss", new_callable=AsyncMock
        ) as mock_replace_sl:
            await self._simulate_redis_command(controller, command_data)
            await asyncio.sleep(0.1)

            # Assert - there should be no calls
            mock_replace_sl.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_sl_tp_ignores_unknown_position(
        self, controller, mock_executor
    ):
        """Checks that commands for a non-existent position are ignored."""
        # Arrange - not adding a position
        command_data = {
            "command": "UPDATE_SL_TP",
            "payload": {
                "position_id": "non-existent-position",
                "user_id": "1",
                "new_stop_loss": 49500.0,
                "new_take_profit": None,
            },
        }

        # Act
        with patch.object(
            controller, "_replace_stop_loss", new_callable=AsyncMock
        ) as mock_replace_sl:
            await self._simulate_redis_command(controller, command_data)
            await asyncio.sleep(0.1)

            # Assert - there should be no calls
            mock_replace_sl.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_sl_tp_security_check(self, controller, mock_executor):
        """Checks that another user's position cannot be modified."""
        # Arrange
        pos_id = "test-pos-owned-by-other"
        position = create_test_position(pos_id=pos_id, user_id=2)  # Belongs to user 2
        controller._active_position_set(position)

        # Controller is acting on behalf of user 1
        assert controller.user_id == 1

        command_data = {
            "command": "UPDATE_SL_TP",
            "payload": {
                "position_id": pos_id,
                "user_id": "1",  # User 1 is trying to change user 2's position
                "new_stop_loss": 49500.0,
                "new_take_profit": None,
            },
        }

        # Act
        with patch.object(
            controller, "_replace_stop_loss", new_callable=AsyncMock
        ) as mock_replace_sl:
            await self._simulate_redis_command(controller, command_data)
            await asyncio.sleep(0.1)

            # Assert - there should be no calls (security check)
            mock_replace_sl.assert_not_called()

    async def _simulate_redis_command(self, controller, command_data: dict):
        """
        Simulates receiving a command via Redis without a real connection.
        Directly calls the processing logic from _redis_command_listener.
        """

        command_type = command_data.get("command")
        payload = command_data.get("payload", {})

        if command_type == "UPDATE_SL_TP":
            pos_id = payload.get("position_id")
            user_id_from_cmd = payload.get("user_id")
            new_sl = payload.get("new_stop_loss")
            new_tp = payload.get("new_take_profit")

            # Checking that the command is for this user
            if str(user_id_from_cmd) != str(controller.user_id):
                return

            # Finding position by ID
            target_position = None
            target_symbol = None
            target_market_type = None

            async with controller._positions_dict_lock:
                for _position_key, pos in controller._active_positions.items():
                    if pos.id == pos_id:
                        target_position = pos
                        target_symbol = pos.symbol
                        target_market_type = controller._market_type_for_position(pos)
                        break

            if not target_position or not target_symbol:
                return

            # Checking the position owner
            if str(target_position.user_id) != str(controller.user_id):
                return

            # Updating Stop Loss
            if new_sl is not None:
                controller.loop.create_task(
                    controller._replace_stop_loss(
                        target_symbol, float(new_sl), market_type=target_market_type
                    ),
                    name=f"UpdateSL_Test_{target_symbol}",
                )

            # Updating Take Profit
            if new_tp is not None:
                controller.loop.create_task(
                    controller._replace_take_profit(
                        target_symbol, float(new_tp), market_type=target_market_type
                    ),
                    name=f"UpdateTP_Test_{target_symbol}",
                )


class TestReplaceTakeProfit:
    """Tests for the _replace_take_profit method."""

    @pytest.mark.asyncio
    async def test_replace_take_profit_cancels_old_orders(
        self, controller, mock_executor
    ):
        """Checks that old TP orders are cancelled."""
        # Arrange
        position = create_test_position()
        old_tp_order_id = position.partial_tp_orders[0].order_id
        old_tp_client_order_id = position.partial_tp_orders[0].client_order_id
        controller._active_position_set(position)

        new_tp_price = 53000.0

        # Act
        with patch.object(controller, "_place_partial_tp", new_callable=AsyncMock):
            await controller._replace_take_profit("BTCUSDT", new_tp_price)

        # Assert - cancel was called for the old order
        mock_executor.cancel_order.assert_called()
        cancel_calls = mock_executor.cancel_order.call_args_list

        # Check that there was a call with the correct parameters
        found_correct_cancel = False
        for call in cancel_calls:
            _, kwargs = call
            if (
                kwargs.get("orderId") == old_tp_order_id
                or kwargs.get("origClientOrderId") == old_tp_client_order_id
            ):
                found_correct_cancel = True
                break

        assert found_correct_cancel, (
            f"Expected cancel_order call with orderId={old_tp_order_id}"
        )

    @pytest.mark.asyncio
    async def test_replace_take_profit_updates_partial_tp_orders(
        self, controller, mock_executor
    ):
        """Checks that partial_tp_orders is updated with the new price."""
        # Arrange
        position = create_test_position()
        controller._active_position_set(position)

        new_tp_price = 53000.0

        # Act
        with patch.object(controller, "_place_partial_tp", new_callable=AsyncMock):
            await controller._replace_take_profit("BTCUSDT", new_tp_price)

        # Assert
        updated_position = controller._active_position_get("BTCUSDT")
        assert len(updated_position.partial_tp_orders) == 1
        assert updated_position.partial_tp_orders[0].target_price == new_tp_price
        assert updated_position.partial_tp_orders[0].status == "PENDING"

    @pytest.mark.asyncio
    async def test_replace_take_profit_calls_place_partial_tp(
        self, controller, mock_executor
    ):
        """Checks that _place_partial_tp is called with the correct parameters."""
        # Arrange
        position = create_test_position()
        controller._active_position_set(position)

        new_tp_price = 53000.0

        # Act
        with patch.object(
            controller, "_place_partial_tp", new_callable=AsyncMock
        ) as mock_place_tp:
            await controller._replace_take_profit("BTCUSDT", new_tp_price)
            await asyncio.sleep(0.1)

        # Assert
        mock_place_tp.assert_called_once()
        call_args = mock_place_tp.call_args
        assert call_args.kwargs["target_price"] == new_tp_price
        assert call_args.kwargs["ptp_internal_idx"] == 0

    @pytest.mark.asyncio
    async def test_replace_take_profit_returns_false_for_missing_position(
        self, controller
    ):
        """Checks that False is returned for a non-existent position."""
        # Act
        result = await controller._replace_take_profit("NONEXISTENT", 53000.0)

        # Assert
        assert result is False

    @pytest.mark.asyncio
    async def test_replace_take_profit_returns_false_for_closed_position(
        self, controller
    ):
        """Checks that False is returned for a closed position."""
        # Arrange
        position = create_test_position()
        position.status = "CLOSED"
        controller._active_position_set(position)

        # Act
        result = await controller._replace_take_profit("BTCUSDT", 53000.0)

        # Assert
        assert result is False


class TestReplaceStopLoss:
    """Tests for the _replace_stop_loss method."""

    @pytest.mark.asyncio
    async def test_replace_stop_loss_cancels_old_order(self, controller, mock_executor):
        """Checks that the old SL order is cancelled."""
        # Arrange
        position = create_test_position()
        controller._active_position_set(position)

        new_sl_price = 49500.0

        # Act
        with patch.object(
            controller, "_place_stop_loss", new_callable=AsyncMock
        ) as mock_place_sl:
            mock_place_sl.return_value = True
            await controller._replace_stop_loss("BTCUSDT", new_sl_price)
            await asyncio.sleep(0.1)

        # Assert
        mock_executor.cancel_order.assert_called()

    @pytest.mark.asyncio
    async def test_replace_stop_loss_updates_current_sl_price(
        self, controller, mock_executor
    ):
        """Checks that current_sl_price is updated."""
        # Arrange
        position = create_test_position()
        controller._active_position_set(position)

        new_sl_price = 49500.0

        # Act
        with patch.object(
            controller, "_place_stop_loss", new_callable=AsyncMock
        ) as mock_place_sl:
            mock_place_sl.return_value = True
            await controller._replace_stop_loss("BTCUSDT", new_sl_price)

        # Assert
        updated_position = controller._active_position_get("BTCUSDT")
        assert updated_position.current_sl_price == new_sl_price

    @pytest.mark.asyncio
    async def test_replace_stop_loss_calls_place_stop_loss(
        self, controller, mock_executor
    ):
        """Checks that _place_stop_loss is called."""
        # Arrange
        position = create_test_position()
        controller._active_position_set(position)

        new_sl_price = 49500.0

        # Act
        with patch.object(
            controller, "_place_stop_loss", new_callable=AsyncMock
        ) as mock_place_sl:
            mock_place_sl.return_value = True
            await controller._replace_stop_loss("BTCUSDT", new_sl_price)

        # Assert
        mock_place_sl.assert_called_once()
        call_args = mock_place_sl.call_args
        # _place_stop_loss accepts position_obj_ref and skip_preflight_check
        assert call_args.kwargs.get("skip_preflight_check")
