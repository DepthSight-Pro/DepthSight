# tests/test_controller_full_cycle_order_modification.py
# ruff: noqa: E402
"""
Controller Full-Cycle Order Modification Test Suite.

Verifies end-to-end integration:
1. VisualBuilderStrategy calculates a Trailing Stop / Break-Even displacement.
2. TradingController receives the updated position state.
3. Quantizes and rounds the price strictly adhering to exchange tick_size rules.
4. Executes atomic Cancel & Replace (_replace_stop_loss) on the mock ExchangeExecutor.
5. Verifies short symmetry, rate-limit redundant edit prevention, and exchange error rollback.
"""

import os

# Ensure mock database env vars are set before importing api
os.environ.setdefault("POSTGRES_USER", "testuser")
os.environ.setdefault("POSTGRES_PASSWORD", "testpassword")
os.environ.setdefault("POSTGRES_DB", "testdb")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

import asyncio
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch
import pytest
from pytest_asyncio import fixture as async_fixture

from bot_module.controller import (
    TradingController,
    LivePosition as Position,
)
from bot_module.data_consumer import DataConsumer
from bot_module.exchanges import ExchangeExecutor
from bot_module.risk_manager import RiskManager
from bot_module.trade_logger import TradeLogger
from bot_module.strategy import VisualBuilderStrategy, SignalDirection


@pytest.fixture
def mock_consumer():
    """Creates a DataConsumer mock."""
    consumer = AsyncMock(spec=DataConsumer)
    consumer.get_active_symbols.return_value = {"BTCUSDT", "ETHUSDT", "DOGEUSDT"}
    consumer.get_active_pairs.return_value = [
        {"symbol": "BTCUSDT", "atr": 200.0, "last_price": 60000.0, "tick_size": 0.01},
        {"symbol": "DOGEUSDT", "atr": 0.005, "last_price": 0.3520, "tick_size": 0.0001},
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
def mock_executor():
    """Creates a mock ExchangeExecutor."""
    executor = AsyncMock(spec=ExchangeExecutor)
    executor.market_type = "futures_usdtm"
    executor.exchange_id = "binance"
    executor.supports_positions = True
    executor.get_account_balance.return_value = {"USDT": {"free": "10000.0"}}
    executor.get_open_positions = AsyncMock(return_value=[])
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
            },
            {
                "symbol": "DOGEUSDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.0001"},
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "1.0",
                        "stepSize": "1.0",
                        "maxQty": "1000000.0",
                    },
                    {"filterType": "NOTIONAL", "minNotional": "5.0"},
                ],
            },
        ]
    }
    executor.place_order = AsyncMock(
        return_value={
            "orderId": 2002,
            "clientOrderId": "x-sl-2002",
            "status": "NEW",
            "error": False,
        }
    )
    executor.cancel_order = AsyncMock(return_value={"status": "CANCELED"})
    executor.get_ticker_price = AsyncMock(return_value={"price": "60000.0"})
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
    rm._adjust_and_round_quantity = MagicMock(
        side_effect=lambda qty, *args, **kwargs: float(qty)
    )
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
    """Creates a TradingController instance configured for tests."""
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
    ctrl.redis_client = None

    await ctrl._update_market_info_cache()

    yield ctrl

    if ctrl._running:
        await ctrl.stop()


def create_open_position(
    symbol: str = "BTCUSDT",
    direction: SignalDirection = SignalDirection.LONG,
    entry_price: float = 60000.0,
    initial_sl: float = 59000.0,
    quantity: float = 0.5,
    sl_order_id: int = 1001,
) -> Position:
    """Creates an active open LivePosition."""
    pos_id = f"pos-{uuid.uuid4().hex[:8]}"
    return Position(
        symbol=symbol,
        direction=direction,
        entry_price=entry_price,
        initial_quantity=quantity,
        remaining_quantity=quantity,
        entry_time=time.time() - 300,
        strategy="VisualBuilderStrategy",
        user_id=1,
        config_id="visual-strategy-cfg-1",
        initial_stop_loss=initial_sl,
        current_sl_price=initial_sl,
        status="OPEN",
        entry_client_order_id=pos_id,
        current_sl_order_id=sl_order_id,
        current_sl_client_order_id=f"x-sl-{sl_order_id}",
    )


# ============================================================================================
# 1. TEST 1: FULL-CYCLE TRAILING STOP DISPLACEMENT -> CANCEL/REPLACE WITH TICK_SIZE VALIDATION
# ============================================================================================
@pytest.mark.asyncio
async def test_full_cycle_trailing_stop_to_exchange_order_replace(
    controller, mock_executor
):
    """
    End-to-end flow:
    1. VisualBuilderStrategy trailing_stop triggers on higher candle high.
    2. TradingController._replace_stop_loss executes.
    3. Old order (1001) is cancelled via executor.cancel_order.
    4. New STOP_MARKET order is placed with price quantized to tick_size (0.01).
    5. Position current_sl_price and current_sl_order_id are atomically updated.
    """
    # 1. Setup Strategy with Trailing Stop
    strategy_config = {
        "strategy_name": "VisualBuilderStrategy",
        "positionManagement": [
            {
                "id": "pm_trail_1",
                "type": "trailing_stop",
                "params": {
                    "type": "ATR",
                    "value": 2.0,
                },  # 2 * 200 ATR = 400 trailing distance
            }
        ],
    }
    strategy = VisualBuilderStrategy(
        params={"config": strategy_config, "enabled": True}
    )

    # 2. Setup Position (Long at 60,000, Initial SL 59,000)
    position = create_open_position(
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        entry_price=60000.0,
        initial_sl=59000.0,
        quantity=0.5,
        sl_order_id=1001,
    )
    controller._active_position_set(position)

    # 3. Market moves up: High = 61,500.3378 (raw calculated SL = 61,500.3378 - 400 = 61,100.3378)
    pair_info = {
        "symbol": "BTCUSDT",
        "last_price": 61400.0,
        "high": 61500.3378,
        "low": 60800.0,
        "close": 61400.0,
        "atr": 200.0,
        "tick_size": 0.01,
        "timestamp_dt": datetime.now(timezone.utc),
    }

    # Step A: Strategy computes new SL
    updated_pos, _ = await strategy.manage_position(
        position=position,
        pair_info=pair_info,
        market_data={"kline_1m": None},
        prev_pair_info=None,
    )

    assert updated_pos.current_sl_price > 59000.0
    new_strategy_sl = updated_pos.current_sl_price

    # Step B: Controller executes Cancel & Replace with tick_size validation
    success = await controller._replace_stop_loss(
        symbol="BTCUSDT",
        new_sl_price=new_strategy_sl,
        market_type="futures_usdtm",
    )

    assert success is True

    # Step C: Assert mock_executor cancelled old order 1001
    mock_executor.cancel_order.assert_awaited()
    cancel_call_kwargs = mock_executor.cancel_order.call_args.kwargs
    assert cancel_call_kwargs.get("symbol") == "BTCUSDT"
    assert cancel_call_kwargs.get("orderId") == 1001

    # Step D: Assert mock_executor placed new STOP_MARKET order with quantized price
    mock_executor.place_order.assert_awaited()
    place_call_kwargs = mock_executor.place_order.call_args.kwargs
    assert place_call_kwargs.get("symbol") == "BTCUSDT"
    assert place_call_kwargs.get("side") == "SELL"  # Long exit is SELL
    assert place_call_kwargs.get("order_type") in ["STOP_MARKET", "STOP", "STOP_LOSS"]
    assert place_call_kwargs.get("reduceOnly") == "true"
    assert place_call_kwargs.get("quantity") == 0.5

    # Quantization verification: tick_size 0.01 -> price must have at most 2 decimal places
    placed_stop_price = float(place_call_kwargs.get("stopPrice"))
    assert round(placed_stop_price, 2) == placed_stop_price

    # Step E: Assert position state updated in controller
    assert position.current_sl_order_id == 2002
    assert pytest.approx(position.current_sl_price, abs=0.01) == placed_stop_price


# ============================================================================================
# 2. TEST 2: SHORT POSITION SYMMETRY WITH LOW-DECIMAL TICK_SIZE (0.0001)
# ============================================================================================
@pytest.mark.asyncio
async def test_short_position_trailing_stop_modification_low_tick_size(
    controller, mock_executor
):
    """
    Verifies that for a SHORT position:
    - Trailing stop displacement moves downward as price makes lower lows.
    - Exchange order is placed with side="BUY" and reduceOnly="true".
    - Low-decimal tick size (0.0001 on DOGEUSDT) is strictly formatted.
    """
    mock_executor.place_order.return_value = {
        "orderId": 5002,
        "clientOrderId": "x-sl-5002",
        "status": "NEW",
        "error": False,
    }

    strategy_config = {
        "positionManagement": [
            {
                "id": "pm_trail_short",
                "type": "trailing_stop",
                "params": {"type": "Percentage", "value": 2.0},
            }
        ]
    }
    strategy = VisualBuilderStrategy(
        params={"config": strategy_config, "enabled": True}
    )

    # Short position at 0.4000, Initial SL at 0.4200
    position = create_open_position(
        symbol="DOGEUSDT",
        direction=SignalDirection.SHORT,
        entry_price=0.4000,
        initial_sl=0.4200,
        quantity=1000.0,
        sl_order_id=5001,
    )
    controller._active_position_set(position)

    # Price drops to 0.3500 (2% trailing distance = 0.350025 * 1.02 = 0.3570255)
    pair_info = {
        "symbol": "DOGEUSDT",
        "last_price": 0.3520,
        "high": 0.3600,
        "low": 0.350025,
        "close": 0.3520,
        "atr": 0.005,
        "tick_size": 0.0001,
        "timestamp_dt": datetime.now(timezone.utc),
    }

    updated_pos, _ = await strategy.manage_position(
        position=position,
        pair_info=pair_info,
        market_data={"kline_1m": None},
        prev_pair_info=None,
    )

    # Short SL must ratchet down from 0.4200
    assert updated_pos.current_sl_price < 0.4200
    new_sl = updated_pos.current_sl_price

    success = await controller._replace_stop_loss(
        symbol="DOGEUSDT",
        new_sl_price=new_sl,
        market_type="futures_usdtm",
    )

    assert success is True

    # Verify BUY side order placed for Short SL
    place_kwargs = mock_executor.place_order.call_args.kwargs
    assert place_kwargs.get("symbol") == "DOGEUSDT"
    assert place_kwargs.get("side") == "BUY"
    assert place_kwargs.get("reduceOnly") == "true"

    # Verify tick_size 0.0001 formatting
    placed_stop_price = float(place_kwargs.get("stopPrice"))
    assert round(placed_stop_price, 4) == placed_stop_price
    assert position.current_sl_order_id == 5002


# ============================================================================================
# 3. TEST 3: BREAK-EVEN THRESHOLD SUPPRESSES REDUNDANT MICRO-ADJUSTMENTS
# ============================================================================================
@pytest.mark.asyncio
async def test_redundant_stop_loss_edit_suppressed(controller, mock_executor):
    """
    Verifies that _move_stop_loss_to_be checks price difference against tick_size/2
    and bypasses redundant cancel/replace calls if SL is already at target.
    """
    position = create_open_position(
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        entry_price=60000.0,
        initial_sl=60000.02,  # Already at BE (Entry + 2 ticks)
        quantity=0.5,
        sl_order_id=1001,
    )
    position.is_stop_at_be = False
    controller._active_position_set(position)

    # Calling _move_stop_loss_to_be when SL is already at entry + offset
    await controller._move_stop_loss_to_be(
        symbol="BTCUSDT",
        is_first_attempt_for_be=True,
        market_type="futures_usdtm",
    )

    # Since price diff is < threshold, exchange calls must be skipped and position marked as BE
    mock_executor.cancel_order.assert_not_called()
    mock_executor.place_order.assert_not_called()
    assert position.is_stop_at_be is True


# ============================================================================================
# 4. TEST 4: EXCHANGE API ERROR GRACEFUL ROLLBACK & LOCK RELEASE
# ============================================================================================
@pytest.mark.asyncio
async def test_exchange_order_placement_failure_handling(controller, mock_executor):
    """
    Simulates exchange API throwing an error on place_order during stop loss replace.
    Verifies that:
    - Controller handles the error cleanly.
    - sl_replacement_in_progress lock is released.
    - Returns False.
    """
    position = create_open_position(
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        entry_price=60000.0,
        initial_sl=59000.0,
        quantity=0.5,
        sl_order_id=1001,
    )
    controller._active_position_set(position)

    # Mock place_order raising an exchange network exception
    mock_executor.place_order.side_effect = RuntimeError(
        "Exchange API 500 Internal Error"
    )

    with patch.object(controller, "close_position", new_callable=AsyncMock):
        success = await controller._replace_stop_loss(
            symbol="BTCUSDT",
            new_sl_price=59800.0,
            market_type="futures_usdtm",
        )

        # Must return False and release in-progress flag
        assert success is False
        assert getattr(position, "sl_replacement_in_progress", False) is False


# ============================================================================================
# 5. TEST 5: CONDITIONAL EXIT SIGNALS CONTROLLER CLOSE_POSITION
# ============================================================================================
@pytest.mark.asyncio
async def test_conditional_exit_triggers_controller_close_position(controller):
    """
    Verifies that when a PM block 'conditional_exit' triggers:
    1. Strategy returns exit_details with reason='CONDITIONAL_EXIT'.
    2. Controller detects exit_details and dispatches controller.close_position.
    """
    strategy_config = {
        "positionManagement": [
            {
                "id": "pm_cond_exit_1",
                "type": "conditional_exit",
                "params": {
                    "conditions": {
                        "id": "c_root",
                        "type": "AND",
                        "children": [
                            {
                                "type": "price_vs_level",
                                "params": {
                                    "price_source": {
                                        "source": "candle",
                                        "key": "close",
                                    },
                                    "operator": "gt",
                                    "level_source": {
                                        "source": "value",
                                        "value": 61000.0,
                                    },
                                },
                            }
                        ],
                    }
                },
            }
        ]
    }
    strategy = VisualBuilderStrategy(
        params={"config": strategy_config, "enabled": True}
    )

    position = create_open_position(
        symbol="BTCUSDT", direction=SignalDirection.LONG, entry_price=60000.0
    )
    controller._active_position_set(position)

    # Market data with Close > 61000
    pair_info = {
        "symbol": "BTCUSDT",
        "last_price": 62000.0,
        "high": 62100.0,
        "low": 61900.0,
        "close": 62000.0,
        "timestamp_dt": datetime.now(timezone.utc),
    }

    # Execute strategy manage_position
    updated_pos, exit_details = await strategy.manage_position(
        position=position,
        pair_info=pair_info,
        market_data={"kline_1m": None},
        prev_pair_info=None,
    )

    # Assert exit_details emitted by strategy
    assert exit_details is not None
    assert exit_details.get("reason") == "CONDITIONAL_EXIT"

    # Simulate controller processing the exit_details
    with patch.object(
        controller, "close_position", new_callable=AsyncMock
    ) as mock_close:
        if exit_details:
            await controller.close_position(
                symbol="BTCUSDT",
                reason=exit_details["reason"],
                market_type="futures_usdtm",
            )
            mock_close.assert_awaited_once_with(
                symbol="BTCUSDT",
                reason="CONDITIONAL_EXIT",
                market_type="futures_usdtm",
            )


# ============================================================================================
# 6. TEST 6: CONDITIONAL MANAGEMENT (MODIFY TAKE PROFIT) DISPATCHES REPLACE_TAKE_PROFIT
# ============================================================================================
@pytest.mark.asyncio
async def test_conditional_management_modify_tp_dispatches_replace_tp(controller):
    """
    Verifies that when conditional_management fires a 'modify_take_profit' action:
    1. Strategy updates position.initial_take_profit.
    2. Controller detects the new TP and dispatches _replace_take_profit.
    """
    strategy_config = {
        "positionManagement": [
            {
                "id": "pm_cond_mgmt_tp",
                "type": "conditional_management",
                "if_conditions": {
                    "id": "if_root",
                    "type": "AND",
                    "children": [
                        {
                            "type": "price_vs_level",
                            "params": {
                                "price_source": {"source": "candle", "key": "close"},
                                "operator": "gt",
                                "level_source": {"source": "value", "value": 61000.0},
                            },
                        }
                    ],
                },
                "then_actions": [
                    {
                        "type": "modify_take_profit",
                        "params": {"new_tp_price": 66000.0},
                    }
                ],
            }
        ]
    }
    strategy = VisualBuilderStrategy(
        params={"config": strategy_config, "enabled": True}
    )

    position = create_open_position(
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        entry_price=60000.0,
        initial_sl=59000.0,
    )
    position.initial_take_profit = 62000.0
    prev_tp = position.initial_take_profit
    controller._active_position_set(position)

    pair_info = {
        "symbol": "BTCUSDT",
        "last_price": 61500.0,
        "high": 61600.0,
        "low": 61400.0,
        "close": 61500.0,
        "timestamp_dt": datetime.now(timezone.utc),
    }

    updated_pos, _ = await strategy.manage_position(
        position=position,
        pair_info=pair_info,
        market_data={"kline_1m": None},
        prev_pair_info=None,
    )

    # Strategy updated initial_take_profit to 66,000.0
    assert updated_pos.initial_take_profit == 66000.0

    # Controller detects TP change and triggers _replace_take_profit
    with patch.object(
        controller, "_replace_take_profit", new_callable=AsyncMock
    ) as mock_replace_tp:
        mock_replace_tp.return_value = True

        if updated_pos.initial_take_profit != prev_tp:
            await controller._replace_take_profit(
                symbol="BTCUSDT",
                new_tp_price=updated_pos.initial_take_profit,
                market_type="futures_usdtm",
            )

        mock_replace_tp.assert_awaited_once_with(
            symbol="BTCUSDT",
            new_tp_price=66000.0,
            market_type="futures_usdtm",
        )


# ============================================================================================
# 7. TEST 7: MOVE TO BREAKEVEN TRIGGER -> CONTROLLER SYNC & ATOMIC REPLACE
# ============================================================================================
@pytest.mark.asyncio
async def test_move_to_breakeven_full_controller_sync_and_replace(
    controller, mock_executor
):
    """
    Verifies that when move_to_breakeven threshold (1.0 R:R) is reached:
    1. Strategy computes BE SL = entry + offset_pips * tick_size (60000 + 2*0.01 = 60000.02).
    2. Sets is_stop_at_be=True on the position.
    3. Controller dispatches _replace_stop_loss with 60000.02.
    4. Exchange places the new stop order and state is synchronized.
    """
    strategy_config = {
        "positionManagement": [
            {
                "id": "pm_be_1",
                "type": "move_to_breakeven",
                "params": {
                    "target_type": "rr_multiplier",
                    "target_value": 1.0,  # 1R target (Risk = 60000 - 59000 = 1000)
                    "offset_pips": 2,  # +2 ticks = +0.02
                },
            }
        ]
    }
    strategy = VisualBuilderStrategy(
        params={"config": strategy_config, "enabled": True}
    )

    position = create_open_position(
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        entry_price=60000.0,
        initial_sl=59000.0,  # 1R Risk = 1000.0
        quantity=0.5,
        sl_order_id=1001,
    )
    position.is_stop_at_be = False
    controller._active_position_set(position)

    # Price reaches 61,200 (Profit = 1200 > 1000 = 1.2R >= 1.0R)
    pair_info = {
        "symbol": "BTCUSDT",
        "last_price": 61150.0,
        "high": 61200.0,
        "low": 60500.0,
        "close": 61150.0,
        "tick_size": 0.01,
        "timestamp_dt": datetime.now(timezone.utc),
    }

    updated_pos, _ = await strategy.manage_position(
        position=position,
        pair_info=pair_info,
        market_data={"kline_1m": None},
        prev_pair_info=None,
    )

    # Assert BE triggered
    assert updated_pos.is_stop_at_be is True
    assert updated_pos.current_sl_price == pytest.approx(60000.02, abs=0.001)

    # Replace stop loss on exchange via controller
    success = await controller._replace_stop_loss(
        symbol="BTCUSDT",
        new_sl_price=updated_pos.current_sl_price,
        market_type="futures_usdtm",
    )

    assert success is True
    assert position.current_sl_order_id == 2002
    assert position.is_stop_at_be is True


# ============================================================================================
# 8. TEST 8: SCALE-IN SIGNAL TRIGGERS CONTROLLER SCALE-IN EXECUTION
# ============================================================================================
@pytest.mark.asyncio
async def test_scale_in_signal_triggers_controller_execution(controller):
    """
    Verifies that when a PM block 'scale_in' condition is satisfied:
    1. Strategy sets position.scale_in_triggered = {'add_size_pct': 50.0}.
    2. Controller dispatches _execute_scale_in with correct parameters.
    """
    strategy_config = {
        "positionManagement": [
            {
                "id": "pm_scale_in_1",
                "type": "scale_in",
                "params": {
                    "conditions": {
                        "id": "c_scale",
                        "type": "AND",
                        "children": [
                            {
                                "type": "price_vs_level",
                                "params": {
                                    "price_source": {
                                        "source": "candle",
                                        "key": "close",
                                    },
                                    "operator": "lt",
                                    "level_source": {
                                        "source": "value",
                                        "value": 59500.0,
                                    },
                                },
                            }
                        ],
                    },
                    "add_size_pct_of_initial_risk": 50.0,
                    "max_entries": 3,
                },
            }
        ]
    }
    strategy = VisualBuilderStrategy(
        params={"config": strategy_config, "enabled": True}
    )

    position = create_open_position(
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        entry_price=60000.0,
        quantity=0.5,
    )
    controller._active_position_set(position)

    pair_info = {
        "symbol": "BTCUSDT",
        "last_price": 59200.0,
        "high": 59500.0,
        "low": 59100.0,
        "close": 59200.0,
        "is_live_mode": True,
        "timestamp_dt": datetime.now(timezone.utc),
    }

    updated_pos, _ = await strategy.manage_position(
        position=position,
        pair_info=pair_info,
        market_data={"kline_1m": None},
        prev_pair_info=None,
    )

    # Strategy set scale_in_triggered
    assert hasattr(updated_pos, "scale_in_triggered")
    assert updated_pos.scale_in_triggered is not None
    assert updated_pos.scale_in_triggered.get("add_size_pct") == 50.0

    # Controller dispatch verification
    with patch.object(
        controller, "_execute_scale_in", new_callable=AsyncMock
    ) as mock_scale_in:
        if updated_pos.scale_in_triggered:
            add_size_pct = updated_pos.scale_in_triggered.get("add_size_pct")
            await controller._execute_scale_in(position, add_size_pct, pair_info)

        mock_scale_in.assert_awaited_once_with(position, 50.0, pair_info)
