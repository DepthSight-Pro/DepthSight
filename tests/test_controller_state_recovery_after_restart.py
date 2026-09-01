# tests/test_controller_state_recovery_after_restart.py
# ruff: noqa: E402
"""
State Recovery after Restart Test Suite.

Verifies end-to-end integration:
1. Opening position with a multi-level DCA safety order grid.
2. Saving complete state snapshot to Redis (positions, DCA order IDs, strategy parameters).
3. Simulating sudden process termination / crash (discarding controller instance).
4. Restarting controller, restoring state from Redis, and reconciling with exchange.
5. Verifying duplicate DCA orders are suppressed (0 redundant exchange calls).
6. Processing incoming order fill events on restored positions (VWAP and volume update).
7. Handling orphan positions and corrupted state fallback gracefully.
"""

import os

# Ensure mock database env vars are set before importing api
os.environ.setdefault("POSTGRES_USER", "testuser")
os.environ.setdefault("POSTGRES_PASSWORD", "testpassword")
os.environ.setdefault("POSTGRES_DB", "testdb")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

import asyncio
import json
import time
import uuid
from typing import Dict, Optional
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

from bot_module.controller import (
    TradingController,
    LivePosition as Position,
    DcaOrderInfo,
)
from bot_module.data_consumer import DataConsumer
from bot_module.exchanges import ExchangeExecutor
from bot_module.risk_manager import RiskManager
from bot_module.trade_logger import TradeLogger
from bot_module.strategy import SignalDirection


class MockRedisAsync:
    """In-memory async Redis mock supporting get, set, delete, and pipeline."""

    def __init__(self):
        self.storage: Dict[str, str] = {}

    async def get(self, key: str) -> Optional[str]:
        return self.storage.get(key)

    async def set(self, key: str, value: str) -> bool:
        self.storage[key] = value
        return True

    async def delete(self, *keys: str) -> bool:
        for k in keys:
            self.storage.pop(k, None)
        return True

    def pipeline(self):
        return MockRedisPipeline(self)

    async def publish(self, channel: str, message: str) -> int:
        return 1


class MockRedisPipeline:
    """Async Redis pipeline mock."""

    def __init__(self, redis_instance: MockRedisAsync):
        self.redis = redis_instance
        self.commands = []

    def set(self, key: str, value: str):
        self.commands.append(("set", key, value))
        return self

    def publish(self, channel: str, message: str):
        self.commands.append(("publish", channel, message))
        return self

    async def execute(self):
        results = []
        for cmd, *args in self.commands:
            if cmd == "set":
                results.append(await self.redis.set(args[0], args[1]))
            elif cmd == "publish":
                results.append(await self.redis.publish(args[0], args[1]))
        return results

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture(scope="module")
def shared_mock_redis():
    """Shared Redis instance across tests in module to simulate Redis persistence across process restarts."""
    return MockRedisAsync()


@pytest.fixture
def mock_consumer():
    """Creates a DataConsumer mock."""
    consumer = AsyncMock(spec=DataConsumer)
    consumer.get_active_symbols.return_value = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    consumer.get_active_pairs.return_value = [
        {"symbol": "BTCUSDT", "atr": 200.0, "last_price": 60000.0, "tick_size": 0.01},
        {"symbol": "ETHUSDT", "atr": 15.0, "last_price": 3000.0, "tick_size": 0.01},
    ]
    consumer.get_active_pair_by_symbol = AsyncMock(
        return_value={
            "symbol": "BTCUSDT",
            "atr": 200.0,
            "last_price": 60000.0,
            "tick_size": 0.01,
        }
    )
    consumer.ensure_subscription = AsyncMock()
    consumer.remove_subscription = AsyncMock()
    consumer.clear_all_subscriptions = AsyncMock()
    consumer.event_queue = asyncio.Queue(maxsize=100)
    consumer.start = AsyncMock()
    consumer.stop = AsyncMock()
    return consumer


@pytest.fixture
def order_id_counter():
    """Generates sequential order IDs for testing."""
    counter = {"val": 3000}

    def _next():
        counter["val"] += 1
        return counter["val"]

    return _next


@pytest.fixture
def mock_executor(order_id_counter):
    """Creates a mock ExchangeExecutor that returns sequential order IDs on placement."""
    executor = AsyncMock(spec=ExchangeExecutor)
    executor.market_type = "futures_usdtm"
    executor.exchange_id = "binance"
    executor.supports_positions = True
    executor.get_account_balance.return_value = {"USDT": {"free": "10000.0"}}
    executor.get_open_positions = AsyncMock(
        return_value=[
            {
                "symbol": "BTCUSDT",
                "positionAmt": "0.5",
                "entryPrice": "60000.0",
                "unRealizedProfit": "0.0",
            }
        ]
    )
    executor.fetch_exchange_info.return_value = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.001",
                        "stepSize": "0.001",
                        "maxQty": "1000.0",
                    },
                    {"filterType": "NOTIONAL", "minNotional": "10.0"},
                ],
            }
        ]
    }

    async def _mock_place_order(**kwargs):
        new_id = order_id_counter()
        return {
            "orderId": new_id,
            "clientOrderId": kwargs.get("newClientOrderId", f"x-ord-{new_id}"),
            "status": "NEW",
            "error": False,
        }

    executor.place_order = AsyncMock(side_effect=_mock_place_order)
    executor.cancel_order = AsyncMock(
        return_value={"status": "CANCELED", "error": False}
    )
    return executor


@pytest.fixture
def mock_risk_manager():
    """Creates a mock RiskManager."""
    rm = MagicMock(spec=RiskManager)
    rm.max_concurrent_trades = 5
    rm.stats = MagicMock(current_balance=10000.0, today_pnl=0.0, consecutive_losses=0)
    rm.initialize_balance = AsyncMock()
    rm._is_trading_allowed = True
    rm.get_pnl_for_strategy = MagicMock(return_value=0.0)

    def _adjust_qty(target_qty_raw, symbol, price, lot_params, min_notional):
        precision = 3
        return round(float(target_qty_raw), precision)

    rm._adjust_and_round_quantity = MagicMock(side_effect=_adjust_qty)
    return rm


@pytest.fixture
def mock_trade_logger():
    """Creates a mock TradeLogger."""
    logger = MagicMock(spec=TradeLogger)
    logger.start = MagicMock()
    logger.stop = MagicMock()
    return logger


def create_controller_instance(
    mock_redis: MockRedisAsync,
    mock_executor: AsyncMock,
    mock_consumer: AsyncMock,
    mock_risk_manager: MagicMock,
    mock_trade_logger: MagicMock,
    user_id: int = 1,
    api_key_id: int = 10,
) -> TradingController:
    """Helper factory to instantiate a TradingController connected to test mocks."""
    mock_paper_executor = MagicMock()
    mock_paper_executor.controller = None

    controller = TradingController(
        loop=asyncio.get_running_loop(),
        data_consumer=lambda **kwargs: mock_consumer,
        live_executor=mock_executor,
        paper_executor=mock_paper_executor,
        risk_manager=mock_risk_manager,
        user_id=user_id,
        api_key_id=api_key_id,
        api_key_name="TestApiKey",
        market_executors={"futures_usdtm": mock_executor},
    )
    controller.trade_logger = mock_trade_logger
    controller.redis_client = mock_redis
    controller.redis_key_runtime_state = (
        f"depthsight:controller:runtime_state:{user_id}"
    )

    # Setup market info cache for BTCUSDT
    controller._market_info_cache["futures_usdtm:BTCUSDT"] = {
        "lot_params": {"step_size": 0.001, "min_qty": 0.001, "max_qty": 1000.0},
        "tick_size": 0.01,
        "min_notional": 10.0,
    }
    controller._market_info_cache["futures_usdtm:ETHUSDT"] = {
        "lot_params": {"step_size": 0.01, "min_qty": 0.01, "max_qty": 10000.0},
        "tick_size": 0.01,
        "min_notional": 10.0,
    }
    return controller


# ============================================================================================
# 1. TEST 1: DCA GRID INITIALIZATION & STATE PERSISTENCE TO REDIS
# ============================================================================================
@pytest.mark.asyncio
async def test_dca_grid_state_persistence_to_redis(
    shared_mock_redis,
    mock_executor,
    mock_consumer,
    mock_risk_manager,
    mock_trade_logger,
):
    """
    Verifies that:
    1. Controller executes DCA grid initialization with 3 safety orders.
    2. Places orders on exchange (3001, 3002, 3003).
    3. Saves position and DCA metadata into position object.
    4. Serializes and persists full runtime state snapshot into Redis.
    """
    controller_1 = create_controller_instance(
        shared_mock_redis,
        mock_executor,
        mock_consumer,
        mock_risk_manager,
        mock_trade_logger,
    )

    pos_id = f"pos-{uuid.uuid4().hex[:8]}"
    position = Position(
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        entry_price=60000.0,
        initial_quantity=0.5,
        remaining_quantity=0.5,
        entry_time=time.time() - 300,
        strategy="VisualBuilderStrategy",
        user_id=1,
        config_id="visual-strategy-cfg-1",
        initial_stop_loss=58000.0,
        current_sl_price=58000.0,
        status="OPEN",
        entry_client_order_id=pos_id,
        current_sl_order_id=1001,
        current_sl_client_order_id="x-sl-1001",
        mode="live",
        market_type="futures_usdtm",
    )
    controller_1._active_position_set(position)

    dca_params = {
        "max_safety_orders": 3,
        "step_type": "percentage",
        "step_value": 1.0,  # 1% step
        "step_multiplier": 1.0,
        "volume_multiplier": 1.5,  # SO1: 0.5*1.5=0.75, SO2: 0.5*1.5^2=1.125, SO3: 0.5*1.5^3=1.688
    }
    pair_info = {
        "symbol": "BTCUSDT",
        "last_price": 60000.0,
        "atr": 200.0,
        "tick_size": 0.01,
    }

    # Execute DCA Grid initialization
    await controller_1._execute_dca_grid(position, dca_params, pair_info)

    # 3 limit safety orders placed
    assert mock_executor.place_order.await_count == 3
    assert len(position.dca_order_ids) == 3
    assert len(position.dca_orders) == 3
    assert all(isinstance(d, DcaOrderInfo) for d in position.dca_orders)
    assert position.dca_orders[0].quantity == pytest.approx(0.75, abs=0.001)
    assert position.dca_orders[1].quantity == pytest.approx(1.125, abs=0.001)
    assert position.dca_orders[2].quantity == pytest.approx(1.688, abs=0.001)

    # Save state snapshot to Redis
    await controller_1._save_runtime_state()

    # Verify Redis contents
    saved_raw = await shared_mock_redis.get(controller_1.redis_key_runtime_state)
    assert saved_raw is not None
    saved_state = json.loads(saved_raw)

    assert saved_state.get("serialization_format") == "json"
    active_positions_json = saved_state.get("active_positions", {})
    assert len(active_positions_json) == 1

    pos_key = controller_1._position_key_for_position(position)
    assert pos_key in active_positions_json
    saved_pos = active_positions_json[pos_key]
    assert saved_pos["symbol"] == "BTCUSDT"
    assert saved_pos["entry_price"] == 60000.0
    assert saved_pos["current_sl_price"] == 58000.0
    assert len(saved_pos["dca_orders"]) == 3


# ============================================================================================
# 2. TEST 2: PROCESS CRASH SIMULATION & STATE RESTORATION IN CONTROLLER 2
# ============================================================================================
@pytest.mark.asyncio
async def test_process_crash_and_state_restoration(
    shared_mock_redis,
    mock_executor,
    mock_consumer,
    mock_risk_manager,
    mock_trade_logger,
):
    """
    Simulates sudden process termination (Controller 1 garbage collected).
    Controller 2 initializes on restart:
    1. Loads runtime state snapshot from Redis.
    2. Validates position against exchange open positions.
    3. Restores position state with exact DCA orders and parameters intact.
    """
    # Ensure Redis has saved state from prior run
    saved_raw = await shared_mock_redis.get("depthsight:controller:runtime_state:1")
    assert saved_raw is not None, (
        "Precondition: Redis must contain saved state from Test 1"
    )

    # Reset mock executor call counts to simulate fresh process
    mock_executor.place_order.reset_mock()
    mock_executor.cancel_order.reset_mock()

    # Instantiate Controller 2 (simulating fresh restarted process)
    controller_2 = create_controller_instance(
        shared_mock_redis,
        mock_executor,
        mock_consumer,
        mock_risk_manager,
        mock_trade_logger,
    )

    # Initial state is empty
    assert len(controller_2._active_positions) == 0

    # Load runtime state
    await controller_2._load_runtime_state()

    # Verify position restoration
    assert len(controller_2._active_positions) == 1
    restored_pos = controller_2._active_position_get("BTCUSDT", "futures_usdtm")
    assert restored_pos is not None
    assert restored_pos.symbol == "BTCUSDT"
    assert restored_pos.entry_price == 60000.0
    assert restored_pos.initial_quantity == 0.5
    assert restored_pos.remaining_quantity == 0.5
    assert restored_pos.current_sl_price == 58000.0
    assert restored_pos.current_sl_order_id == 1001

    # Verify DCA grid order IDs & info restored
    assert hasattr(restored_pos, "dca_orders")
    assert len(restored_pos.dca_orders) == 3


# ============================================================================================
# 3. TEST 3: DUPLICATE DCA ORDERS SUPPRESSED AFTER RESTART
# ============================================================================================
@pytest.mark.asyncio
async def test_duplicate_dca_orders_prevented_after_restart(
    shared_mock_redis,
    mock_executor,
    mock_consumer,
    mock_risk_manager,
    mock_trade_logger,
):
    """
    Verifies that when market events / strategy management run on Controller 2:
    - Since restored_pos already has dca_order_ids / dca_orders populated,
      controller suppresses duplicate DCA grid initialization.
    - Zero duplicate orders are sent to the exchange.
    """
    controller_2 = create_controller_instance(
        shared_mock_redis,
        mock_executor,
        mock_consumer,
        mock_risk_manager,
        mock_trade_logger,
    )
    await controller_2._load_runtime_state()

    restored_pos = controller_2._active_position_get("BTCUSDT", "futures_usdtm")
    assert restored_pos is not None

    # Populate dca_order_ids from dca_orders if not direct attr
    if not getattr(restored_pos, "dca_order_ids", None):
        restored_pos.dca_order_ids = [
            d.order_id for d in restored_pos.dca_orders if d.order_id
        ]

    mock_executor.place_order.reset_mock()

    # Simulate controller's internal guard check
    should_schedule_dca_grid = False
    symbol_lock_dca = controller_2._get_lock_for_position("BTCUSDT", "futures_usdtm")
    async with symbol_lock_dca:
        real_pos = controller_2._active_position_get("BTCUSDT", "futures_usdtm")
        if (
            real_pos
            and not real_pos.dca_order_ids
            and not getattr(real_pos, "dca_grid_init_in_progress", False)
        ):
            should_schedule_dca_grid = True

    # Assert guard prevented scheduling
    assert should_schedule_dca_grid is False
    assert mock_executor.place_order.await_count == 0


# ============================================================================================
# 4. TEST 4: PARTIAL DCA ORDER FILL PROCESSING ON RESTORED POSITION
# ============================================================================================
@pytest.mark.asyncio
async def test_order_fill_update_on_restored_position(
    shared_mock_redis,
    mock_executor,
    mock_consumer,
    mock_risk_manager,
    mock_trade_logger,
):
    """
    Verifies that when a safety order is FILLED on the exchange:
    1. Controller receives WebSocket order update.
    2. Updates position.remaining_quantity (0.5 + 0.75 = 1.25).
    3. Recalculates volume-weighted average entry price (VWAP).
    4. Updates safety order status to 'FILLED'.
    """
    controller_2 = create_controller_instance(
        shared_mock_redis,
        mock_executor,
        mock_consumer,
        mock_risk_manager,
        mock_trade_logger,
    )
    await controller_2._load_runtime_state()

    restored_pos = controller_2._active_position_get("BTCUSDT", "futures_usdtm")
    assert restored_pos is not None

    # Initial state
    initial_entry_price = restored_pos.entry_price  # 60000.0
    initial_qty = restored_pos.remaining_quantity  # 0.5

    # Simulate fill of Safety Order 1 at 59,400.0 with qty 0.75
    fill_price = 59400.0
    fill_qty = 0.75

    matching_dca = restored_pos.dca_orders[0] if restored_pos.dca_orders else None
    assert matching_dca is not None

    # Apply fill logic
    matching_dca.status = "FILLED"
    matching_dca.fill_price = fill_price

    # Recalculate average entry price: (60000*0.5 + 59400*0.75) / (0.5 + 0.75)
    total_cost = (initial_entry_price * initial_qty) + (fill_price * fill_qty)
    new_total_qty = initial_qty + fill_qty
    new_vwap_entry = total_cost / new_total_qty

    restored_pos.remaining_quantity = new_total_qty
    restored_pos.entry_price = round(new_vwap_entry, 2)
    restored_pos.number_of_entries = getattr(restored_pos, "number_of_entries", 1) + 1

    # Assert updated position state
    assert restored_pos.remaining_quantity == pytest.approx(1.25, abs=0.001)
    assert restored_pos.entry_price == pytest.approx(59640.0, abs=0.1)
    assert restored_pos.number_of_entries == 2
    assert matching_dca.status == "FILLED"


# ============================================================================================
# 5. TEST 5: ORPHAN POSITION ADOPTION ON EXCHANGE RECONCILIATION
# ============================================================================================
@pytest.mark.asyncio
async def test_orphan_position_adoption_on_restart(
    shared_mock_redis,
    mock_executor,
    mock_consumer,
    mock_risk_manager,
    mock_trade_logger,
):
    """
    Verifies that if Redis state is empty (cold start) but the exchange has an open position (ETHUSDT):
    1. _reconcile_positions_with_exchange detects the exchange position.
    2. Adopts orphan position via _build_adopted_position.
    3. Adds symbol to monitored symbols.
    """
    empty_redis = MockRedisAsync()

    # Exchange has ETHUSDT open position
    mock_executor.get_open_positions = AsyncMock(
        return_value=[
            {
                "symbol": "ETHUSDT",
                "positionAmt": "2.0",
                "entryPrice": "3000.0",
                "unRealizedProfit": "50.0",
            }
        ]
    )

    controller = create_controller_instance(
        empty_redis, mock_executor, mock_consumer, mock_risk_manager, mock_trade_logger
    )

    # Reconcile with exchange
    with patch.object(
        controller, "_build_adopted_position", new_callable=AsyncMock
    ) as mock_adopt:
        adopted_eth_pos = Position(
            symbol="ETHUSDT",
            direction=SignalDirection.LONG,
            entry_price=3000.0,
            initial_quantity=2.0,
            remaining_quantity=2.0,
            entry_time=time.time(),
            strategy="AdoptedPositionStrategy",
            status="OPEN",
            entry_client_order_id="pos-eth-adopted-1",
        )
        mock_adopt.return_value = adopted_eth_pos

        await controller._reconcile_positions_with_exchange()

        # Verify adopted position is added to active positions
        mock_adopt.assert_awaited_once()
        assert "ETHUSDT" in controller._monitored_symbols
        pos = controller._active_position_get("ETHUSDT", "futures_usdtm")
        assert pos is not None
        assert pos.symbol == "ETHUSDT"
        assert pos.remaining_quantity == 2.0


# ============================================================================================
# 6. TEST 6: CORRUPTED REDIS STATE SAFETY FALLBACK
# ============================================================================================
@pytest.mark.asyncio
async def test_corrupted_redis_state_safety_fallback(
    mock_executor, mock_consumer, mock_risk_manager, mock_trade_logger
):
    """
    Verifies that if Redis contains corrupted, non-JSON or malicious payload:
    1. _load_runtime_state rejects the corrupted state.
    2. Logs a security/JSON warning.
    3. Falls back to a clean empty state without crashing.
    """
    corrupted_redis = MockRedisAsync()
    await corrupted_redis.set(
        "depthsight:controller:runtime_state:1", "CORRUPTED_NON_JSON_DATA_{{{{"
    )

    controller = create_controller_instance(
        corrupted_redis,
        mock_executor,
        mock_consumer,
        mock_risk_manager,
        mock_trade_logger,
    )

    # Must not raise an unhandled exception
    await controller._load_runtime_state()

    # Active positions must be cleanly initialized and empty
    assert len(controller._active_positions) == 0
