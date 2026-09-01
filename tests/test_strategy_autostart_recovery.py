# tests/test_strategy_autostart_recovery.py
"""
Comprehensive tests for strategy autostart and position recovery upon controller reboot.
Verifies Redis state snapshot persistence, cold-boot PostgreSQL adoption, and lifecycle tracking.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot_module.controller import TradingController


class MockRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value):
        self.store[key] = value

    async def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture
def mock_controller():
    loop = asyncio.get_event_loop()
    consumer = AsyncMock()
    consumer.get_active_symbols.return_value = {"BTCUSDT"}
    consumer.get_active_pair_by_symbol.return_value = {
        "symbol": "BTCUSDT",
        "last_price": 50000.0,
        "high": 50100.0,
        "low": 49900.0,
        "close": 50000.0,
        "atr": 100.0,
        "tick_size": 0.1,
    }

    live_executor = AsyncMock()
    live_executor.market_type = "futures_usdtm"
    live_executor.get_open_positions.return_value = []
    live_executor.get_open_orders.return_value = []

    paper_executor = AsyncMock()
    risk_manager = MagicMock()
    risk_manager.user_telegram_chat_id = None
    risk_manager.max_concurrent_trades = 10

    redis_client = MockRedis()

    controller = TradingController(
        loop=loop,
        data_consumer=consumer,
        live_executor=live_executor,
        paper_executor=paper_executor,
        risk_manager=risk_manager,
        user_id=1,
        api_key_id=10,
        api_key_name="TestBybitKey",
    )
    controller.redis_client = redis_client
    return controller


@pytest.mark.asyncio
async def test_save_and_load_running_strategies_redis(mock_controller):
    """
    Verifies that running strategy instances are serialized into Redis on start
    and automatically restored upon _load_runtime_state.
    """
    controller = mock_controller
    strat_id = "strat-auto-123"
    payload = {
        "user_id": 1,
        "id": f"{strat_id}:inst1",
        "config_id": strat_id,
        "mode": "live",
        "symbol_selection_mode": "STATIC",
        "symbols": ["BTCUSDT"],
        "name": "MyTrendStrategy",
        "api_key_id": 10,
        "config_data": {
            "strategy_name": "VisualBuilderStrategy",
            "entryConditions": {
                "id": "c1",
                "type": "RSI",
                "params": {"period": 14, "operator": "lt", "value": 30.0},
            },
            "initialization": {
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "atr_multiplier",
                    "sl_value": 2.0,
                },
            },
        },
    }

    # 1. Start strategy
    await controller._handle_start_strategy_command(payload)
    assert len(controller.running_strategy_instances) == 1
    assert f"{strat_id}:inst1" in controller.running_strategy_instances

    # 2. Check that Redis got the snapshot
    raw_saved = await controller.redis_client.get(controller.redis_key_runtime_state)
    assert raw_saved is not None
    saved_snapshot = json.loads(raw_saved)
    assert "running_strategies" in saved_snapshot
    assert len(saved_snapshot["running_strategies"]) == 1
    assert saved_snapshot["running_strategies"][0]["config_id"] == strat_id

    # 3. Simulate controller reboot: clear running instances
    controller.running_strategy_instances.clear()
    assert len(controller.running_strategy_instances) == 0

    # 4. Load runtime state from Redis
    await controller._load_runtime_state()

    # 5. Verify strategy was restored
    assert len(controller.running_strategy_instances) == 1
    assert f"{strat_id}:inst1" in controller.running_strategy_instances
    restored_instance, restored_payload = controller.running_strategy_instances[
        f"{strat_id}:inst1"
    ]
    assert restored_payload["config_id"] == strat_id
    assert "BTCUSDT" in restored_payload["symbols"]


@pytest.mark.asyncio
async def test_stop_strategy_persists_removal_to_redis(mock_controller):
    """
    Verifies that stopping a strategy updates the Redis snapshot so it won't restart.
    """
    controller = mock_controller
    instance_id = "strat-stop-999:inst1"
    payload = {
        "user_id": 1,
        "id": instance_id,
        "config_id": "strat-stop-999",
        "mode": "live",
        "symbol_selection_mode": "DYNAMIC",
        "symbols": [],
        "name": "DynamicStrategy",
        "api_key_id": 10,
        "config_data": {
            "strategy_name": "VisualBuilderStrategy",
            "entryConditions": {
                "id": "c1",
                "type": "RSI",
                "params": {"period": 14, "operator": "lt", "value": 30.0},
            },
            "initialization": {
                "type": "open_position",
                "params": {"direction": "LONG"},
            },
        },
    }

    # Start and verify
    await controller._handle_start_strategy_command(payload)
    assert len(controller.running_strategy_instances) == 1

    # Stop strategy
    await controller._handle_stop_strategy_command(
        {"user_id": 1, "strategy_id": instance_id}
    )
    assert len(controller.running_strategy_instances) == 0

    # Check Redis snapshot has 0 running strategies
    raw_saved = await controller.redis_client.get(controller.redis_key_runtime_state)
    saved_snapshot = json.loads(raw_saved)
    assert len(saved_snapshot.get("running_strategies", [])) == 0


@pytest.mark.asyncio
async def test_cold_reboot_autostart_from_db_on_open_position(mock_controller):
    """
    Verifies that if Redis is empty but an open position exists on the exchange,
    the controller fetches the StrategyConfig from DB and automatically launches the strategy.
    """
    controller = mock_controller
    strat_uuid = "db-config-uuid-555"

    # Simulate exchange reporting an open position
    controller.executors["live"].get_open_positions.return_value = [
        {
            "symbol": "BTCUSDT",
            "positionAmt": "1.5",
            "entryPrice": "50000.0",
        }
    ]
    controller.executors["live"].get_open_orders.return_value = [
        {
            "symbol": "BTCUSDT",
            "type": "STOP_MARKET",
            "side": "SELL",
            "stopPrice": "49000.0",
            "orderId": "sl-111",
            "clientOrderId": "cid-sl-111",
        }
    ]

    # Mock DB returning the strategy config
    mock_strat_row = MagicMock()
    mock_strat_row.id = strat_uuid
    mock_strat_row.name = "DatabaseAutoStrategy"
    mock_strat_row.description = "Auto-started on reboot"
    mock_strat_row.symbol_selection_mode = "STATIC"
    mock_strat_row.symbols = ["BTCUSDT"]
    mock_strat_row.use_ml_confirmation = False
    mock_strat_row.foundation_weights = {}
    mock_strat_row.config_data = {
        "strategy_name": "VisualBuilderStrategy",
        "entryConditions": {
            "id": "c1",
            "type": "RSI",
            "params": {"period": 14, "operator": "lt", "value": 30.0},
        },
        "initialization": {"type": "open_position", "params": {"direction": "LONG"}},
        "positionManagement": [
            {
                "id": "pm_trail",
                "type": "trailing_stop",
                "params": {"type": "ATR", "value": 2.0},
            },
        ],
    }

    mock_trade_row = MagicMock()
    mock_trade_row.strategy_config_id = strat_uuid
    mock_trade_row.strategy_config = mock_strat_row
    mock_trade_row.trade_uuid = "x-entry-test123"

    async def mock_get_db_session():
        yield MagicMock()

    controller.get_db_session = mock_get_db_session

    with (
        patch(
            "api.crud.get_last_open_trade_for_symbol",
            AsyncMock(return_value=mock_trade_row),
        ),
        patch("api.crud.get_strategy_config", AsyncMock(return_value=mock_strat_row)),
        patch(
            "api.crud.get_strategy_config_by_id", AsyncMock(return_value=mock_strat_row)
        ),
    ):
        # Reconcile with exchange
        await controller._reconcile_positions_with_exchange()

        # 1. Position must be adopted
        active_pos = controller._active_position_get("BTCUSDT", "futures_usdtm")
        assert active_pos is not None
        assert active_pos.config_id == strat_uuid
        assert active_pos.current_sl_price == 49000.0

        # 2. Strategy MUST be auto-started in running pool
        assert len(controller.running_strategy_instances) == 1
        running_inst_key = list(controller.running_strategy_instances.keys())[0]
        running_inst, running_payload = controller.running_strategy_instances[
            running_inst_key
        ]
        assert running_payload["config_id"] == strat_uuid
        assert running_payload["name"] == "DatabaseAutoStrategy"
        assert "BTCUSDT" in running_payload["symbols"]
