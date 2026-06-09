# tests/test_controller_integration.py

import pytest
import pytest_asyncio
import asyncio
import json
from unittest.mock import patch, AsyncMock

import fakeredis.aioredis
from bot_module.controller import TradingController
from bot_module import config as bot_config


# --- Fixtures ---
@pytest.fixture
def mock_consumer():
    # Returning a mock CLASS, which will return a mock INSTANCE when called
    mock_instance = AsyncMock()
    mock_instance.start = AsyncMock()
    mock_instance.stop = AsyncMock()
    mock_instance.clear_all_subscriptions = AsyncMock()
    return lambda **kwargs: mock_instance


@pytest.fixture
def mock_executor():
    executor = AsyncMock()
    executor.update_position_sl_tp = AsyncMock(return_value=True)
    executor.close_all_user_positions = AsyncMock(return_value=True)
    executor.start_user_data_stream = AsyncMock()
    executor.stop_user_data_stream = AsyncMock()
    return executor


@pytest.fixture
def mock_risk_manager():
    # Using a full mock to avoid dependency on its constructor
    rm = AsyncMock()
    rm.initialize_balance = AsyncMock()
    rm.save_state = AsyncMock()
    # Adding values to avoid TypeError in periodic tasks
    rm.allocated_margin = 0.0
    return rm


@pytest_asyncio.fixture
async def controller_with_fake_redis(mock_consumer, mock_executor, mock_risk_manager):
    fake_redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)

    with patch("bot_module.controller.redis.Redis", return_value=fake_redis_client):
        controller = TradingController(
            loop=asyncio.get_running_loop(),
            data_consumer=mock_consumer,
            live_executor=mock_executor,
            paper_executor=mock_executor,
            risk_manager=mock_risk_manager,
            user_id=1,
        )

        yield controller, fake_redis_client
        if hasattr(controller, "_running") and controller._running:
            await controller.stop()
        await fake_redis_client.aclose()


# --- Final parameterized test ---


@pytest.mark.parametrize(
    "command_info",
    [
        {
            "name": "START_STRATEGY",
            "payload": {
                "id": "cfg-1",
                "user_id": 1,
                "config_data": {"strategy_name": "Test"},
            },
            "target_path": "bot_module.controller.TradingController._handle_start_strategy_command",
        },
        {
            "name": "STOP_STRATEGY",
            "payload": {"strategy_id": "inst-1", "user_id": 1},
            "target_path": "bot_module.controller.TradingController._handle_stop_strategy_command",
        },
        {
            "name": "UPDATE_SL_TP",
            "payload": {"position_id": "pos-1", "user_id": 1, "new_stop_loss": 50000},
            "target_path": "bot_module.controller.TradingController._redis_command_listener",
        },
        {
            "name": "EMERGENCY_STOP",
            "payload": {"user_id": 1},
            "target_path": "bot_module.controller.TradingController._redis_command_listener",
        },
        {
            "name": "CLOSE_POSITION",
            "payload": {"symbol": "BTCUSDT", "user_id": 1},
            "target_path": "bot_module.controller.TradingController.close_position",
        },
    ],
)
@pytest.mark.asyncio
async def test_all_redis_commands_are_processed(
    controller_with_fake_redis, command_info
):
    controller, fake_redis_client = controller_with_fake_redis

    # ARRANGE
    # (Arrange for CLOSE_POSITION moved after controller.start() to avoid reconciliation deletion)

    with patch(
        command_info["target_path"], new_callable=AsyncMock
    ) as mock_target_method:
        await controller.start()
        await asyncio.sleep(0.1)

        # ARRANGE after start (to avoid initial reconciliation deleting our fake position)
        if command_info["name"] == "CLOSE_POSITION":
            from bot_module.strategy import SignalDirection
            from bot_module.controller import LivePosition as Position

            # Creating a fake position
            fake_position = Position(
                symbol="BTCUSDT",
                direction=SignalDirection.LONG,
                entry_price=50000,
                initial_quantity=0.1,
                remaining_quantity=0.1,
                entry_time=0,
                strategy="Test",
                initial_stop_loss=49000,
                current_sl_price=49000,
                initial_take_profit=51000,
                user_id=1,
                status="OPEN",
            )
            controller._active_positions["BTCUSDT"] = fake_position

        command = {"command": command_info["name"], "payload": command_info["payload"]}
        await fake_redis_client.publish(
            bot_config.REDIS_COMMAND_CHANNEL, json.dumps(command)
        )
        await asyncio.sleep(0.5)
        assert mock_target_method.await_count >= 1, (
            f"Expected {command_info['target_path']} to have been awaited."
        )
