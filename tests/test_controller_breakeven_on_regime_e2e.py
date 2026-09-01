import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from bot_module.controller import TradingController, LivePosition
from bot_module.strategy import BaseStrategy
from bot_module.datatypes import SignalDirection
from bot_module.data_consumer import DataConsumer


# --- FIXTURES ---
@pytest.fixture
def mock_consumer():
    # Use spec=DataConsumer to pass the isinstance check
    consumer = MagicMock(spec=DataConsumer)
    # Explicitly override async methods as AsyncMock
    # IMPORTANT: last_price = None so that the price from screener_data['close'] is used
    consumer.get_active_pair_by_symbol = AsyncMock(
        return_value={
            "tick_size": 0.01,
            "last_price": None,  # Do not overwrite the price from screener!
            "symbol": "BTCUSDT",
        }
    )
    consumer.remove_all_subscriptions_for_symbol = AsyncMock(return_value=True)
    consumer.ensure_subscription = AsyncMock(return_value=True)
    return consumer


@pytest.fixture
def mock_executor():
    executor = MagicMock()
    executor.place_order = AsyncMock(return_value={"orderId": 123, "status": "NEW"})
    executor.cancel_order = AsyncMock(
        return_value={"orderId": 456, "status": "CANCELED"}
    )
    return executor


@pytest.fixture
def mock_paper_executor():
    executor = MagicMock()
    return executor


@pytest.fixture
def mock_risk_manager():
    rm = MagicMock()
    return rm


@pytest.fixture
def mock_telegram_notifier():
    tn = MagicMock()
    tn.sl_moved_to_be = AsyncMock()
    return tn


@pytest.fixture
def mock_db_session_factory():
    async def get_db_mock():
        yield MagicMock()

    return get_db_mock


@pytest.fixture
async def controller_fixture(
    mock_consumer,
    mock_executor,
    mock_paper_executor,
    mock_risk_manager,
    mock_telegram_notifier,
    mock_db_session_factory,
):
    with patch(
        "bot_module.controller.TradingController._get_market_info",
        new_callable=AsyncMock,
    ) as mock_get_market_info:
        mock_get_market_info.return_value = 0.01

        controller = TradingController(
            loop=asyncio.get_running_loop(),
            data_consumer=mock_consumer,
            live_executor=mock_executor,
            paper_executor=mock_paper_executor,
            risk_manager=mock_risk_manager,
            user_id=1,
            telegram_notifier=mock_telegram_notifier,
            get_db=mock_db_session_factory,
        )
        controller._running = True
        yield controller
        controller._running = False


# --- TESTS ---


@pytest.mark.asyncio
async def test_regime_change_winning_trade_moves_sl(
    controller_fixture, mock_telegram_notifier
):
    """
    Scenario: Price is ABOVE entry (we are in the black).
    Expectation: Move SL to BE.
    """
    controller = controller_fixture
    symbol = "BTCUSDT"
    entry_price = 50000.0
    current_price = 50500.0  # PLUS

    # Setup Strategy & Position
    strategy = BaseStrategy(params={"breakeven_on_regime_change": True})
    strategy.NAME = "TestStrategy"
    config_id = "test_config_1"

    async with controller.instances_lock:
        controller.running_strategy_instances[config_id] = (
            strategy,
            {"config_id": config_id, "symbol_selection_mode": "DYNAMIC"},
        )

    position = LivePosition(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=entry_price,
        initial_quantity=1,
        remaining_quantity=1,
        entry_time=1000,
        strategy=strategy.NAME,
        initial_stop_loss=49000.0,
        current_sl_price=49000.0,
        initial_take_profit=55000.0,
        config_id=config_id,
        signal_details={"oracle_regime": 1},  # Old regime
    )
    position.status = "OPEN"

    async with controller._positions_dict_lock:
        controller._active_position_set(position)

    # Mocking
    with patch.object(
        controller, "_replace_stop_loss", new_callable=AsyncMock
    ) as mock_replace_sl:
        mock_replace_sl.return_value = True

        # Simulate Screener Update (Regime 1 -> 0)
        screener_payload = {
            "data": [
                {
                    "symbol": symbol,
                    "oracle_regime": 0,
                    "close": current_price,
                }
            ]
        }
        await controller._screener_update_queue.put(screener_payload)

        # Run Loop briefly
        loop_task = asyncio.create_task(controller._dynamic_symbol_selection_loop())
        await asyncio.sleep(0.1)
        await controller._screener_update_queue.join()
        controller._running = False
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        # ASSERTIONS
        # 1. Stop loss move to entry price must be called
        mock_replace_sl.assert_called_once_with(
            symbol, entry_price, market_type="futures_usdtm"
        )

        # 2. BE flag must be set
        pos = controller._active_position_get(symbol)
        assert pos is not None
        assert pos.is_stop_at_be is True


@pytest.mark.asyncio
async def test_regime_change_losing_trade_closes_position(controller_fixture):
    """
    Scenario: Price is BELOW entry (we are in the red).
    Expectation: Immediate position closure (Panic Sell).
    """
    controller = controller_fixture
    symbol = "ETHUSDT"
    entry_price = 3000.0
    current_price = 2900.0  # MINUS

    strategy = BaseStrategy(params={"breakeven_on_regime_change": True})
    strategy.NAME = "TestStrategy"
    config_id = "test_config_2"

    async with controller.instances_lock:
        controller.running_strategy_instances[config_id] = (
            strategy,
            {"config_id": config_id, "symbol_selection_mode": "DYNAMIC"},
        )

    position = LivePosition(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=entry_price,
        initial_quantity=10,
        remaining_quantity=10,
        entry_time=1000,
        strategy=strategy.NAME,
        initial_stop_loss=2800.0,
        current_sl_price=2800.0,
        initial_take_profit=3500.0,
        config_id=config_id,
        signal_details={"oracle_regime": 1},
    )
    position.status = "OPEN"

    async with controller._positions_dict_lock:
        controller._active_position_set(position)

    # Mocking close_position AND _replace_stop_loss
    with (
        patch.object(
            controller, "close_position", new_callable=AsyncMock
        ) as mock_close,
        patch.object(
            controller, "_replace_stop_loss", new_callable=AsyncMock
        ) as mock_replace_sl,
    ):
        # Simulate Screener Update (Regime 1 -> 0)
        screener_payload = {
            "data": [
                {
                    "symbol": symbol,
                    "oracle_regime": 0,
                    "close": current_price,
                }
            ]
        }
        await controller._screener_update_queue.put(screener_payload)

        loop_task = asyncio.create_task(controller._dynamic_symbol_selection_loop())
        await asyncio.sleep(0.1)
        await controller._screener_update_queue.join()
        controller._running = False
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        # ASSERTIONS
        # 1. _replace_stop_loss MUST NOT be called (no point in setting BE for a losing position)
        mock_replace_sl.assert_not_called()

        # 2. close_position MUST be called
        mock_close.assert_called_once()
        # Check call arguments (symbol and reason)
        args, kwargs = mock_close.call_args
        assert args[0] == symbol
        assert kwargs.get("reason") == "REGIME_CHANGE_LOSS_CUT"
