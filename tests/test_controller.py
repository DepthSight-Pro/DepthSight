# tests/test_controller.py
# ruff: noqa: E402

import os

os.environ.setdefault("POSTGRES_USER", "testuser")
os.environ.setdefault("POSTGRES_PASSWORD", "testpassword")
os.environ.setdefault("POSTGRES_DB", "testdb")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

import pytest
import asyncio

# Use a decorator from pytest_asyncio
from pytest_asyncio import fixture as async_fixture
import time
from unittest.mock import MagicMock, AsyncMock, patch
import pandas as pd
import json
import math
from datetime import datetime, timezone
from typing import Optional, Callable
import uuid

# Import the class under test and dependencies
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
    from bot_module.strategy import (
        BaseStrategy,
        StrategySignal,
        SignalDirection,
        OrderMode,
        get_strategy_instance,
        PartialTarget,
    )
    from bot_module import config
except ImportError as e:
    print(f"ImportError in test_controller.py: {e}")
    pytest.skip(
        f"Cannot import bot_module components for TradingController tests: {e}",
        allow_module_level=True,
    )


# --- Fixtures ---
@pytest.fixture
def mock_consumer():
    """Creates a DataConsumer mock."""
    consumer = AsyncMock(spec=DataConsumer)
    consumer.get_active_symbols.return_value = {"BTCUSDT", "ETHUSDT"}
    consumer.get_active_pairs.return_value = [
        {
            "symbol": "BTCUSDT",
            "atr": 50.0,
            "natr": 0.1,
            "last_price": 50000.0,
            "relative_volume": 1.5,
        },
        {
            "symbol": "ETHUSDT",
            "atr": 4.0,
            "natr": 0.1,
            "last_price": 3000.0,
            "relative_volume": 1.2,
        },
        {
            "symbol": "ADAUSDT",
            "atr": 0.05,
            "natr": 0.1,
            "last_price": 1.5,
            "relative_volume": 0.8,
        },
    ]
    kline_index = pd.to_datetime(
        pd.date_range(end=datetime.now(timezone.utc), periods=60, freq="1min"), utc=True
    )
    consumer.get_kline_history.return_value = (
        pd.DataFrame(
            {
                "open_time": kline_index,
                "open": [50000.0 + i * 10 - 5 for i in range(60)],
                "high": [50000.0 + i * 10 + 5 for i in range(60)],
                "low": [50000.0 + i * 10 - 10 for i in range(60)],
                "close": [50000.0 + i * 10 for i in range(60)],
                "volume": [100 + i for i in range(60)],
            }
        )
        .set_index("open_time")
        .copy()
    )
    consumer.get_latest_depth.return_value = {
        "bids": [["49999.0", "1.0"]],
        "asks": [["50001.0", "1.0"]],
        "lastUpdateId": 12345,
    }
    trade_index = pd.to_datetime([datetime.now(timezone.utc)], utc=True)
    consumer.get_recent_trades.return_value = pd.DataFrame(
        {
            "price": [50000.0],
            "quantity": [0.1],
            "is_buyer_maker": [False],
            "agg_trade_id": [123],
        },
        index=trade_index,
    )

    consumer.ensure_subscription = AsyncMock()
    consumer.remove_subscription = AsyncMock()
    consumer.remove_all_subscriptions_for_symbol = AsyncMock()
    consumer.clear_all_subscriptions = AsyncMock()
    consumer.event_queue = asyncio.Queue(maxsize=1)
    consumer.start = AsyncMock()
    consumer.stop = AsyncMock()
    consumer._metrics_lock = AsyncMock()
    consumer._required_metrics = {}
    return consumer


@pytest.fixture
def mock_executor():
    """Creates a BinanceExecutor mock."""
    executor = AsyncMock(spec=ExchangeExecutor)
    executor.market_type = "futures_usdtm"
    executor.supports_positions = True
    executor.get_account_balance.return_value = {
        "USDT": {"free": "10000.0", "locked": "0.0"}
    }
    executor.get_open_positions.return_value = []
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
            {
                "symbol": "ETHUSDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.001",
                        "stepSize": "0.001",
                        "maxQty": "90000.0",
                    },
                    {"filterType": "NOTIONAL", "minNotional": "10.0"},
                ],
            },
            {
                "symbol": "ADAUSDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.0001"},
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.1",
                        "stepSize": "0.1",
                        "maxQty": "9000000.0",
                    },
                    {"filterType": "NOTIONAL", "minNotional": "5.0"},
                ],
            },
        ]
    }
    executor.place_order = AsyncMock()
    executor.cancel_order = AsyncMock()
    executor.start_user_data_stream = AsyncMock()
    executor.stop_user_data_stream = AsyncMock()
    return executor


@pytest.fixture
def mock_risk_manager():
    """Creates a full RiskManager mock."""
    rm = AsyncMock(spec=RiskManager)
    rm.initialize_balance = AsyncMock()
    rm.update_balance = AsyncMock(return_value=True)
    rm.assess_signal = AsyncMock(
        return_value=(True, 0.01, 100.0, None)
    )  # approved, qty, risk, rejection_reason
    rm.update_trade_result = AsyncMock()
    rm.update_symbol_strategy_performance = AsyncMock()
    rm.is_symbol_trading_allowed = AsyncMock(return_value=True)
    rm.save_state = AsyncMock()

    # Explicitly mocking a SYNCHRONOUS method using MagicMock,
    # so that it does not return a coroutine.
    rm._adjust_and_round_quantity = MagicMock(
        side_effect=lambda qty, *args, **kwargs: qty if qty is not None else 0.0
    )

    rm.stats = MagicMock()
    rm.stats.current_balance = 10000.0
    rm.max_concurrent_trades = 10  # Maximum number of simultaneous trades
    return rm


@pytest.fixture
def mock_trade_logger():
    logger_instance = MagicMock(spec=TradeLogger)
    logger_instance.log_event = MagicMock()
    logger_instance.start = MagicMock()
    logger_instance.stop = MagicMock()
    setattr(logger_instance, "_running", True)
    return logger_instance


@pytest.fixture
def mock_strategy_instance():
    instance = MagicMock(spec=BaseStrategy)
    instance.NAME = "MockStrategyA"
    instance.required_data_types = {"kline_1m", "depth", "aggTrade"}
    instance.check_signal = AsyncMock(return_value=None)
    instance.check_signal_sync = MagicMock(return_value=None)
    instance.enabled = True
    instance.lookback_period = 20
    instance._get_param = MagicMock(
        side_effect=lambda param_name, default=None: (
            default if param_name != "candle_timeframe" else "1m"
        )
    )
    return instance


@async_fixture
async def controller(
    mock_consumer, mock_executor, mock_risk_manager, mock_trade_logger, monkeypatch
):
    ctrl = None
    active_strategy_instances_for_patch = {}

    def mock_get_strategy_instance_fixture(strategy_name):
        if strategy_name not in active_strategy_instances_for_patch:
            mock_strat = MagicMock(spec=BaseStrategy)
            mock_strat.NAME = strategy_name
            strategy_config = test_strategy_defaults.get(strategy_name, {})
            mock_strat.enabled = strategy_config.get("enabled", False)
            cfg_tf = strategy_config.get("candle_timeframe", "1m")
            mock_strat.candle_timeframe = cfg_tf
            mock_strat._get_param = MagicMock(
                side_effect=lambda pname, default=None: (
                    cfg_tf if pname == "candle_timeframe" else default
                )
            )
            req_types_default = {f"kline_{cfg_tf}"}
            if strategy_name in [
                "FakeBreakout",
                "AggTradeReversal",
                "VolumeBreakout",
                "FirstPullbacksInTrend",
                "OnlineAgentStrategy",
                "MockStrategyA",
                "ConsolidationImpulse",
            ]:
                req_types_default.add("aggTrade")
            if strategy_name in [
                "DensityBounce",
                "OnlineAgentStrategy",
                "MockStrategyA",
            ]:
                req_types_default.add("depth")
            mock_strat.required_data_types = req_types_default
            mock_strat.required_indicators = set()
            mock_strat.check_signal = AsyncMock(return_value=None)
            mock_strat.check_signal_sync = MagicMock(return_value=None)
            active_strategy_instances_for_patch[strategy_name] = mock_strat
        return active_strategy_instances_for_patch[strategy_name]

    test_strategy_defaults = {
        "FirstPullbacksInTrend": {"enabled": True, "candle_timeframe": "1m"},
        "MockStrategyA": {"enabled": True, "candle_timeframe": "1m"},
        "ConsolidationImpulse": {"enabled": True, "candle_timeframe": "1m"},
        "VolumeBreakout": {"enabled": True, "candle_timeframe": "1m"},
        "FakeBreakout": {"enabled": True, "candle_timeframe": "1m"},
        "DensityBounce": {"enabled": True, "candle_timeframe": "5m"},
        "AggTradeReversal": {"enabled": True, "candle_timeframe": "1m"},
        "OnlineAgentStrategy": {"enabled": False, "candle_timeframe": "1m"},
    }

    if not hasattr(config, "STRATEGY_DEFAULTS"):
        monkeypatch.setattr(config, "STRATEGY_DEFAULTS", {})

    original_strategy_defaults = config.STRATEGY_DEFAULTS.copy()
    monkeypatch.setattr(config, "STRATEGY_DEFAULTS", test_strategy_defaults)

    original_get_strategy_param = config.get_strategy_param

    def mock_get_strategy_param_for_test(strategy_name, param_name, default=None):
        if (
            strategy_name in test_strategy_defaults
            and param_name in test_strategy_defaults[strategy_name]
        ):
            return test_strategy_defaults[strategy_name][param_name]
        return original_get_strategy_param(strategy_name, param_name, default)

    monkeypatch.setattr(config, "get_strategy_param", mock_get_strategy_param_for_test)

    known_strategy_names = set(test_strategy_defaults.keys())
    patched_strategies_dict = {
        s_name: MagicMock(__name__=s_name) for s_name in known_strategy_names
    }

    # Creating a mock for paper executor
    mock_paper_executor = MagicMock()
    mock_paper_executor.controller = None

    with (
        patch(
            "bot_module.controller.get_strategy_instance",
            side_effect=mock_get_strategy_instance_fixture,
        ),
        patch("bot_module.controller.STRATEGIES", patched_strategies_dict),
    ):
        try:
            ctrl = TradingController(
                loop=asyncio.get_running_loop(),
                data_consumer=lambda **kwargs: mock_consumer,
                live_executor=mock_executor,
                paper_executor=mock_paper_executor,
                risk_manager=mock_risk_manager,
                user_id=1,
            )
            ctrl._test_strategy_defaults_fixture = test_strategy_defaults
            ctrl.trade_logger = mock_trade_logger

            # Pre-fill running_strategy_instances as if they were started via API/Redis
            for strat_name, strat_config in test_strategy_defaults.items():
                if strat_config["enabled"]:
                    instance = mock_get_strategy_instance_fixture(
                        strat_name
                    )  # Using our mock generator
                    config_id = f"test-config-{strat_name}"
                    mock_config_payload = {
                        "id": config_id,
                        "user_id": 1,
                        "symbol_selection_mode": "DYNAMIC",
                        "config_data": {"strategy_name": strat_name, "params": {}},
                    }
                    ctrl.running_strategy_instances[config_id] = (
                        instance,
                        mock_config_payload,
                    )

            await ctrl._update_market_info_cache()
            initial_symbols = await mock_consumer.get_active_symbols()
            if initial_symbols:
                ctrl._last_known_symbols_from_consumer = initial_symbols.copy()
                await (
                    ctrl._update_monitored_symbols()
                )  # Now this call will work correctly
            yield ctrl
        finally:
            if ctrl and getattr(ctrl, "_running", False):
                await ctrl.stop()
            monkeypatch.setattr(config, "STRATEGY_DEFAULTS", original_strategy_defaults)
            monkeypatch.setattr(
                config, "get_strategy_param", original_get_strategy_param
            )


class _ExpectObjectContaining:
    def __init__(self, subset):
        self.subset = subset

    def __eq__(self, other):
        if not isinstance(other, dict):
            return False
        try:
            return all(k in other and other[k] == v for k, v in self.subset.items())
        except Exception:
            return False

    def __repr__(self):
        return f"<EXPECT OBJECT CONTAINING {self.subset!r}>"


expect = _ExpectObjectContaining


def create_mock_executor_place_order_sequence(
    symbol: str, last_price_provider: Optional[Callable[[], float]] = None
):
    order_id_counter = iter(range(1001, 1030))

    async def side_effect_func(*args, **kwargs):
        current_id = next(order_id_counter)
        order_type = kwargs.get("order_type", kwargs.get("type", "UNKNOWN")).upper()
        if len(args) > 2 and "type" not in kwargs and "order_type" not in kwargs:
            order_type = str(args[2]).upper()

        client_order_id = kwargs.get("newClientOrderId", f"mock-cid-{current_id}")
        quantity_arg = kwargs.get("quantity", args[3] if len(args) > 3 else "0")
        price_arg = kwargs.get("price", args[4] if len(args) > 4 else "0")
        stop_price_arg = kwargs.get("stopPrice", kwargs.get("stop_price", "0"))

        try:
            quantity_f = float(quantity_arg) if quantity_arg else 0.0
        except (ValueError, TypeError):
            quantity_f = 0.0
        try:
            price_f = float(price_arg) if price_arg else 0.0
        except (ValueError, TypeError):
            price_f = 0.0
        try:
            stop_price_f = float(stop_price_arg) if stop_price_arg else 0.0
        except (ValueError, TypeError):
            stop_price_f = 0.0

        status = "NEW"
        fills = []
        executed_qty = "0.0"
        cummulative_quote_qty = "0.0"
        avg_price = "0.0"

        if order_type == "MARKET":
            status = "FILLED"
            executed_qty = f"{quantity_f:.8f}"
            fill_price_market = 50000.0
            if last_price_provider:
                try:
                    provided_price = last_price_provider()
                    if provided_price is not None and provided_price > 0:
                        fill_price_market = provided_price
                except Exception:
                    pass
            fills = [
                {
                    "price": f"{fill_price_market:.8f}",
                    "qty": f"{quantity_f:.8f}",
                    "commission": "0.0",
                    "commissionAsset": "USDT",
                }
            ]
            cummulative_quote_qty = f"{fill_price_market * quantity_f:.8f}"
            avg_price = f"{fill_price_market:.8f}"
        elif order_type == "LIMIT":
            avg_price = f"{price_f:.8f}" if price_f > 0 else "0.0"
        elif order_type in ["STOP_MARKET", "TAKE_PROFIT_MARKET"]:
            avg_price = "0.0"
            price_f = 0.0

        response = {
            "symbol": symbol,
            "orderId": current_id,
            "clientOrderId": client_order_id,
            "transactTime": int(time.time() * 1000),
            "price": f"{price_f:.8f}",
            "origQty": f"{quantity_f:.8f}",
            "executedQty": executed_qty,
            "cummulativeQuoteQty": cummulative_quote_qty,
            "status": status,
            "timeInForce": kwargs.get("timeInForce", "GTC"),
            "type": order_type,
            "side": kwargs.get("side", args[1] if len(args) > 1 else "UNKNOWN"),
            "stopPrice": f"{stop_price_f:.8f}",
            "fills": fills,
            "origQuoteOrderQty": kwargs.get("quoteOrderQty", "0.0"),
            "avgPrice": avg_price,
            "error": False,
            "msg": "",
        }
        return response

    return side_effect_func


def make_position_for_market(
    symbol: str = "BTCUSDT",
    market_type: str = "futures_usdtm",
    *,
    status: str = "OPEN",
    entry_order_id: Optional[int] = None,
    entry_client_order_id: Optional[str] = None,
    quantity: float = 0.01,
) -> Position:
    return Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=50000.0,
        initial_quantity=quantity,
        remaining_quantity=quantity,
        entry_time=time.time(),
        strategy="MarketAwareStrategy",
        initial_stop_loss=49000.0,
        current_sl_price=49000.0,
        initial_take_profit=52000.0,
        status=status,
        entry_order_id=entry_order_id,
        entry_client_order_id=entry_client_order_id,
        market_type=market_type,
        mode="live",
        user_id=1,
        config_id=f"cfg-{market_type}",
    )


# --- Tests ---
@pytest.mark.asyncio
async def test_controller_start_stop(
    controller, mock_consumer, mock_executor, mock_risk_manager, mock_trade_logger
):
    assert controller._running is False
    await controller.start()
    assert controller._running is True
    assert controller._main_task is not None and not controller._main_task.done()
    assert (
        controller._config_reload_task is not None
        and not controller._config_reload_task.done()
    )
    assert (
        controller._market_info_update_task is not None
        and not controller._market_info_update_task.done()
    )

    await asyncio.sleep(0.1)

    await controller.stop()
    assert controller._running is False
    assert controller._main_task is None
    assert controller._config_reload_task is None
    assert controller._market_info_update_task is None

    mock_trade_logger.start.assert_called_once()
    mock_risk_manager.initialize_balance.assert_called_once()
    mock_consumer.start.assert_called_once()
    assert controller.executors["live"].start_user_data_stream.called
    controller.executors["live"].fetch_exchange_info.assert_called()

    mock_consumer.clear_all_subscriptions.assert_called_once()
    assert controller.executors["live"].stop_user_data_stream.called
    mock_consumer.stop.assert_called_once()
    mock_trade_logger.stop.assert_called_once()


@pytest.mark.asyncio
async def test_update_monitored_symbols_add(controller, mock_consumer):
    # Strategy launch simulation logic moved to the `controller` fixture.
    # Now the controller already comes with running strategies and monitored symbols.
    # This test now checks the addition of a NEW symbol.

    mock_consumer.ensure_subscription.reset_mock()
    mock_consumer.remove_all_subscriptions_for_symbol.reset_mock()

    # Initially we have "BTCUSDT", "ETHUSDT" from the fixture.
    # Add "ADAUSDT" from the consumer to check the addition logic.
    new_symbols = {"BTCUSDT", "ETHUSDT", "ADAUSDT"}
    controller._last_known_symbols_from_consumer = new_symbols.copy()

    await controller._update_monitored_symbols()

    # Assert
    # consumer.get_active_pairs returns data for all 3, but strategies are running
    # in DYNAMIC mode, so they must track all 3 symbols.
    # Mock consumer returns 3 active symbols from get_active_pairs
    assert controller._monitored_symbols == {"BTCUSDT", "ETHUSDT", "ADAUSDT"}

    # Checking that _active_strategies was created for all symbols
    assert (
        len(controller._active_strategies) == 0
    )  # This structure is no longer used to determine subscriptions
    # Instead, _update_monitored_symbols works with running_strategy_instances
    # Keep the check for ensure_subscription calls

    expected_ensure_calls = set()

    # Getting all running instances
    async with controller.instances_lock:
        running_instances = list(controller.running_strategy_instances.values())

    for symbol in new_symbols:
        for strategy_instance, config in running_instances:
            # Checking that the strategy is DYNAMIC and works with this symbol
            if config.get("symbol_selection_mode") == "DYNAMIC":
                for data_key in strategy_instance.required_data_types:
                    if (
                        data_key
                        and isinstance(data_key, str)
                        and data_key != "kline_None"
                    ):
                        expected_ensure_calls.add(f"{data_key}:{symbol}")

    actual_ensure_calls_set = set()
    for call_item in mock_consumer.ensure_subscription.call_args_list:
        args, kwargs = call_item
        if len(args) == 2 and args[0] != "kline_None":
            actual_ensure_calls_set.add(f"{args[0]}:{args[1]}")

    assert actual_ensure_calls_set == expected_ensure_calls
    mock_consumer.remove_all_subscriptions_for_symbol.assert_not_called()


@pytest.mark.asyncio
async def test_update_monitored_symbols_remove(
    controller: TradingController, mock_consumer
):
    symbol_to_remove = "BTCUSDT"
    symbol_to_keep = "ETHUSDT"

    # Initially all strategies are running (from the controller fixture),
    # and both symbols are monitored (since mock_consumer returns them).
    assert controller._monitored_symbols == {symbol_to_remove, symbol_to_keep}

    # "Stop" all strategies except for one that will work with ETHUSDT
    async with controller.instances_lock:
        # Find the config for MockStrategyA, which we want to keep
        keep_config_id = "test-config-MockStrategyA"
        instance_to_keep, config_to_keep = controller.running_strategy_instances[
            keep_config_id
        ]

        # Replace all running instances with only one
        controller.running_strategy_instances.clear()
        controller.running_strategy_instances[keep_config_id] = (
            instance_to_keep,
            config_to_keep,
        )

        # Specify that it only works with ETHUSDT
        config_to_keep["symbol_selection_mode"] = "STATIC"
        config_to_keep["symbols"] = [symbol_to_keep]

    mock_consumer.remove_all_subscriptions_for_symbol.reset_mock()
    # The consumer now also returns only ETHUSDT
    controller._last_known_symbols_from_consumer = {symbol_to_keep}

    await controller._update_monitored_symbols()
    await asyncio.sleep(0.01)

    assert controller._monitored_symbols == {symbol_to_keep}
    mock_consumer.remove_all_subscriptions_for_symbol.assert_called_once_with(
        symbol_to_remove
    )


@pytest.mark.asyncio
async def test_update_monitored_symbols_remove_with_position(
    controller, mock_consumer, mock_executor, mock_strategy_instance
):
    symbol_to_remove = "BTCUSDT"
    symbol_to_keep = "ETHUSDT"

    # "Stop" all strategies, leaving only one for ETHUSDT
    async with controller.instances_lock:
        keep_config_id = "test-config-MockStrategyA"
        instance_to_keep, config_to_keep = controller.running_strategy_instances[
            keep_config_id
        ]
        controller.running_strategy_instances.clear()
        controller.running_strategy_instances[keep_config_id] = (
            instance_to_keep,
            config_to_keep,
        )
        config_to_keep["symbol_selection_mode"] = "STATIC"
        config_to_keep["symbols"] = [symbol_to_keep]

    # Create a position for a symbol that is no longer tracked by strategies
    position_to_manage = Position(
        symbol=symbol_to_remove,
        direction=SignalDirection.LONG,
        entry_price=50000.0,
        initial_quantity=0.01,
        remaining_quantity=0.01,
        entry_time=time.time(),
        strategy="SomeOldStrategy",
        initial_stop_loss=49000.0,
        current_sl_price=49000.0,
        initial_take_profit=51000.0,
        status="OPEN",
        current_sl_order_id=555,
    )
    controller._active_positions[symbol_to_remove] = position_to_manage

    controller._last_known_symbols_from_consumer = {symbol_to_keep}
    mock_consumer.remove_all_subscriptions_for_symbol.reset_mock()

    await controller._update_monitored_symbols()
    await asyncio.sleep(0.05)

    assert symbol_to_remove in controller._closing_managed_symbols
    assert controller._monitored_symbols == {symbol_to_remove, symbol_to_keep}
    mock_consumer.remove_all_subscriptions_for_symbol.assert_not_called()


@pytest.mark.asyncio
async def test_handle_event_routes_tick_for_on_tick_trigger(controller):
    symbol = "BTCUSDT"
    mock_instance = MagicMock(spec=BaseStrategy)
    mock_instance.NAME = "OnTickVisualStrategy"
    mock_instance.required_data_types = set()

    controller.running_strategy_instances.clear()
    controller.running_strategy_instances["tick-config"] = (
        mock_instance,
        {
            "id": "tick-config",
            "user_id": 1,
            "symbol_selection_mode": "STATIC",
            "symbols": [symbol],
            "config_data": {"entryTrigger": {"type": "on_tick"}},
        },
    )

    controller.consumer.get_active_pair_by_symbol = AsyncMock(
        return_value={"symbol": symbol, "last_price": 50000.0, "atr": 50.0}
    )
    controller._gather_market_data_for_required_keys = AsyncMock(return_value={})
    controller._get_market_info = AsyncMock(return_value=0.01)

    with patch.object(
        controller, "_check_and_process_signal_for_instance", new_callable=AsyncMock
    ) as mock_check:
        await controller._handle_event(
            {
                "type": "TICK",
                "symbol": symbol,
                "price": 50010.0,
                "timestamp_ms": 1234567890,
            }
        )

    mock_check.assert_awaited_once()
    _, _, called_symbol, pair_info = mock_check.await_args.args
    assert called_symbol == symbol
    assert pair_info["last_price"] == pytest.approx(50010.0)
    assert pair_info["strategy_config_id"] == "tick-config"


@pytest.mark.asyncio
async def test_handle_tv_webhook_signal_command_processes_external_signal(controller):
    symbol = "BTCUSDT"
    config_id = "tv-config"
    controller.redis_client = MagicMock()
    controller.redis_client.set = AsyncMock(return_value=True)
    mock_instance = MagicMock(spec=BaseStrategy)
    mock_instance.NAME = "VisualBuilderStrategy"
    mock_instance.required_data_types = set()

    signal = StrategySignal(
        strategy_name=mock_instance.NAME,
        symbol=symbol,
        direction=SignalDirection.LONG,
        stop_loss=49500.0,
        take_profit=51000.0,
        partial_targets=[PartialTarget(price=51000.0, fraction=1.0)],
        trigger_price=50000.0,
        mode=OrderMode.MARKET,
        details={"strategy_config_id": config_id},
    )
    mock_instance.build_external_signal = MagicMock(
        return_value=(signal, {"result": True})
    )

    controller.running_strategy_instances.clear()
    controller.running_strategy_instances[config_id] = (
        mock_instance,
        {
            "id": config_id,
            "user_id": 1,
            "api_key_id": None,
            "config_data": {
                "strategy_name": "VisualBuilderStrategy",
                "signal_source": "tradingview_webhook",
                "symbol": symbol,
            },
        },
    )

    controller.consumer.get_active_pair_by_symbol = AsyncMock(
        return_value={"symbol": symbol, "last_price": 50000.0, "atr": 50.0}
    )
    controller._get_market_info = AsyncMock(return_value=0.01)
    controller._gather_market_data_for_strategy = AsyncMock(return_value={})

    created_tasks = []
    original_create_task = controller.loop.create_task

    def task_spy(coro, *, name=None):
        task = original_create_task(coro, name=name)
        created_tasks.append(task)
        return task

    with (
        patch.object(controller.loop, "create_task", side_effect=task_spy),
        patch.object(
            controller, "_process_signal", new_callable=AsyncMock
        ) as mock_process_signal,
    ):
        await controller._handle_tv_webhook_signal_command(
            {
                "user_id": 1,
                "config_id": config_id,
                "action": "buy",
                "symbol": "BINANCE:BTCUSDT.P",
                "normalized_symbol": symbol,
            }
        )

        if created_tasks:
            await asyncio.gather(*[task for task in created_tasks if not task.done()])

    mock_instance.build_external_signal.assert_called_once()
    mock_process_signal.assert_awaited_once()
    controller.redis_client.set.assert_awaited()
    status_payload = json.loads(controller.redis_client.set.await_args.args[1])
    assert status_payload["status"] == "queued_for_execution"


@pytest.mark.asyncio
async def test_handle_tv_webhook_signal_command_skips_mismatched_api_key(controller):
    symbol = "BTCUSDT"
    config_id = "tv-config-api-key"
    controller.api_key_id = 77
    controller.redis_client = MagicMock()
    controller.redis_client.set = AsyncMock(return_value=True)

    mock_instance = MagicMock(spec=BaseStrategy)
    mock_instance.NAME = "VisualBuilderStrategy"
    mock_instance.required_data_types = set()
    mock_instance.build_external_signal = MagicMock()

    controller.running_strategy_instances.clear()
    controller.running_strategy_instances[config_id] = (
        mock_instance,
        {
            "id": config_id,
            "user_id": 1,
            "api_key_id": 77,
            "config_data": {
                "strategy_name": "VisualBuilderStrategy",
                "signal_source": "tradingview_webhook",
                "symbol": symbol,
            },
        },
    )

    with patch.object(
        controller, "_process_signal", new_callable=AsyncMock
    ) as mock_process_signal:
        await controller._handle_tv_webhook_signal_command(
            {
                "user_id": 1,
                "config_id": config_id,
                "api_key_id": 99,
                "action": "buy",
                "symbol": "BINANCE:BTCUSDT.P",
                "normalized_symbol": symbol,
            }
        )

    mock_instance.build_external_signal.assert_not_called()
    mock_process_signal.assert_not_awaited()
    controller.redis_client.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_tv_webhook_signal_command_skips_non_webhook_strategy(controller):
    symbol = "BTCUSDT"
    config_id = "tv-config-internal"
    controller.redis_client = MagicMock()
    controller.redis_client.set = AsyncMock(return_value=True)

    mock_instance = MagicMock(spec=BaseStrategy)
    mock_instance.NAME = "VisualBuilderStrategy"
    mock_instance.required_data_types = set()
    mock_instance.build_external_signal = MagicMock()

    controller.running_strategy_instances.clear()
    controller.running_strategy_instances[config_id] = (
        mock_instance,
        {
            "id": config_id,
            "user_id": 1,
            "api_key_id": None,
            "config_data": {
                "strategy_name": "VisualBuilderStrategy",
                "signal_source": "internal",
                "symbol": symbol,
            },
        },
    )

    with patch.object(
        controller, "_process_signal", new_callable=AsyncMock
    ) as mock_process_signal:
        await controller._handle_tv_webhook_signal_command(
            {
                "user_id": 1,
                "config_id": config_id,
                "action": "buy",
                "symbol": "BINANCE:BTCUSDT.P",
                "normalized_symbol": symbol,
            }
        )

    mock_instance.build_external_signal.assert_not_called()
    mock_process_signal.assert_not_awaited()
    controller.redis_client.set.assert_awaited()
    status_payload = json.loads(controller.redis_client.set.await_args.args[1])
    assert status_payload["status"] == "ignored_wrong_signal_source"


@pytest.mark.xfail(reason="Requires Redis connection - needs additional mocking")
@pytest.mark.asyncio
async def test_process_signal_approved_market(
    controller, mock_risk_manager, mock_executor, mock_trade_logger
):
    strategy_name = "FirstPullbacksInTrend"
    symbol = "BTCUSDT"

    mock_instance = get_strategy_instance(strategy_name)
    mock_config = {
        "id": "test-config-id-123",
        "user_id": 1,
        "config_data": {"strategy_name": strategy_name, "params": {}},
        "use_ml_confirmation": False,
    }
    async with controller.instances_lock:
        controller.running_strategy_instances[mock_config["id"]] = (
            mock_instance,
            mock_config,
        )

    signal = StrategySignal(
        strategy_name=strategy_name,
        symbol=symbol,
        direction=SignalDirection.LONG,
        stop_loss=49500.0,
        take_profit=51000.0,
        partial_targets=[PartialTarget(price=51000.0, fraction=1.0)],
        trigger_price=50000.0,
        mode=OrderMode.MARKET,
        details={},
    )

    pair_info = {"symbol": symbol, "atr": 50.0, "last_price": 50000.0}
    mock_risk_manager.assess_signal.return_value = (
        True,
        0.01,
        100.0,
        None,
    )  # approved, qty, risk, rejection_reason
    mock_executor.place_order.side_effect = create_mock_executor_place_order_sequence(
        symbol, last_price_provider=lambda: 50000.0
    )

    # Tracking and waiting for background tasks
    created_tasks = []
    original_create_task = controller.loop.create_task

    def task_spy(coro, *, name=None):
        task = original_create_task(coro, name=name)
        created_tasks.append(task)
        return task

    with patch.object(controller.loop, "create_task", side_effect=task_spy):
        await controller._process_signal(signal, pair_info)

        # Waiting for all created tasks to complete
        if created_tasks:
            await asyncio.gather(*[t for t in created_tasks if not t.done()])

    # 1. Entry (MARKET) -> FILLED
    # 2. SL (STOP_MARKET)
    # 3. TP (LIMIT)
    assert mock_executor.place_order.call_count == 3


@pytest.mark.asyncio
async def test_handle_order_update_entry_filled(
    controller, mock_executor, mock_trade_logger
):
    strategy_name = "FirstPullbacksInTrend"
    symbol = "ETHUSDT"
    client_order_id = "x-bot-entry1"
    order_id = 12345
    initial_qty = 0.5
    entry_price = 3000.0
    sl = 2950.0
    tp = 3100.0
    planned_risk = 100.0

    controller.executors["live"].market_type = "futures_usdtm"

    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=None,
        initial_quantity=initial_qty,
        remaining_quantity=initial_qty,
        entry_time=time.time(),
        strategy=strategy_name,
        initial_stop_loss=sl,
        current_sl_price=sl,
        initial_take_profit=tp,
        status="PENDING_ENTRY",
        entry_order_id=order_id,
        entry_client_order_id=client_order_id,
        entry_order_status="NEW",
        initial_risk_usd_planned=planned_risk,
        original_partial_targets_plan=[PartialTarget(price=tp, fraction=1.0)],
    )
    controller._active_positions[symbol] = position

    exec_report = {
        "e": "ORDER_TRADE_UPDATE",
        "E": time.time() * 1000,
        "o": {
            "s": symbol,
            "c": client_order_id,
            "i": order_id,
            "S": "BUY",
            "ot": "MARKET",
            "x": "TRADE",
            "X": "FILLED",
            "q": str(initial_qty),
            "z": str(initial_qty),
            "l": str(initial_qty),
            "L": str(entry_price),
            "ap": str(entry_price),
            "n": "0.003",
            "N": "ETH",
            "rp": "0",
        },
    }
    mock_executor.place_order.side_effect = create_mock_executor_place_order_sequence(
        symbol
    )
    mock_executor.get_ticker_price = AsyncMock(return_value={"price": str(entry_price)})

    await controller._handle_order_update(exec_report)
    await asyncio.sleep(
        0.7
    )  # Increased because _handle_entry_fill contains asyncio.sleep(0.5)

    assert symbol in controller._active_positions
    updated_position = controller._active_positions[symbol]
    assert updated_position.status == "OPEN"
    assert updated_position.entry_price == entry_price
    assert updated_position.time_status_open is not None

    assert mock_executor.place_order.call_count == 2
    calls = mock_executor.place_order.call_args_list

    sl_call_args, sl_call_kwargs = calls[0]
    assert (
        sl_call_kwargs["symbol"] == symbol
        and sl_call_kwargs["side"] == "SELL"
        and sl_call_kwargs["order_type"] == "STOP_MARKET"
    )
    assert (
        math.isclose(float(sl_call_kwargs["stopPrice"]), sl)
        and sl_call_kwargs["quantity"] == initial_qty
    )

    tp_call_args, tp_call_kwargs = calls[1]
    assert (
        tp_call_kwargs["symbol"] == symbol
        and tp_call_kwargs["side"] == "SELL"
        and tp_call_kwargs["order_type"] == "LIMIT"
    )
    assert (
        math.isclose(float(tp_call_kwargs["price"]), tp)
        and tp_call_kwargs["quantity"] == initial_qty
    )
    assert tp_call_kwargs.get("timeInForce") == "GTC"
    assert tp_call_kwargs.get("reduceOnly") == "true"


@pytest.mark.asyncio
async def test_handle_order_update_entry_filled_duplicate(
    controller, mock_executor, mock_trade_logger
):
    strategy_name = "FirstPullbacksInTrend"
    symbol = "ETHUSDT"
    client_order_id = "x-bot-entry1-dup"
    order_id = 123456
    initial_qty = 0.5
    entry_price = 3000.0
    sl = 2950.0
    tp = 3100.0
    planned_risk = 100.0

    controller.executors["live"].market_type = "futures_usdtm"

    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=None,
        initial_quantity=initial_qty,
        remaining_quantity=initial_qty,
        entry_time=time.time(),
        strategy=strategy_name,
        initial_stop_loss=sl,
        current_sl_price=sl,
        initial_take_profit=tp,
        status="PENDING_ENTRY",
        entry_order_id=order_id,
        entry_client_order_id=client_order_id,
        entry_order_status="NEW",
        initial_risk_usd_planned=planned_risk,
        original_partial_targets_plan=[PartialTarget(price=tp, fraction=1.0)],
    )
    controller._active_positions[symbol] = position

    exec_report = {
        "e": "ORDER_TRADE_UPDATE",
        "E": time.time() * 1000,
        "o": {
            "s": symbol,
            "c": client_order_id,
            "i": order_id,
            "S": "BUY",
            "ot": "MARKET",
            "x": "TRADE",
            "X": "FILLED",
            "q": str(initial_qty),
            "z": str(initial_qty),
            "l": str(initial_qty),
            "L": str(entry_price),
            "ap": str(entry_price),
            "n": "0.003",
            "N": "ETH",
            "rp": "0",
        },
    }
    mock_executor.place_order.side_effect = create_mock_executor_place_order_sequence(
        symbol
    )
    mock_executor.get_ticker_price = AsyncMock(return_value={"price": str(entry_price)})

    # First call - should process
    await controller._handle_order_update(exec_report)
    await asyncio.sleep(0.1)

    # Second call (duplicate) - should be skipped
    await controller._handle_order_update(exec_report)
    await asyncio.sleep(0.7)

    assert symbol in controller._active_positions
    updated_position = controller._active_positions[symbol]
    assert updated_position.status == "OPEN"
    assert updated_position.entry_fill_processed is True

    # Place order should only have been called twice (1 SL, 1 TP) for the first call
    # If the second call was processed, call_count would be larger.
    assert mock_executor.place_order.call_count == 2


@pytest.mark.asyncio
async def test_spot_with_active_sl_tracks_tp_virtual_and_rearms_sl(
    controller, mock_executor
):
    symbol = "ETHUSDT"
    mock_executor.market_type = "spot"
    mock_executor.supports_positions = False
    mock_executor.get_ticker_price = AsyncMock(return_value={"price": "3000.0"})
    mock_executor.cancel_order.return_value = {"status": "CANCELED"}

    async def place_order_side_effect(**kwargs):
        if kwargs["order_type"] == "MARKET":
            return {
                "orderId": 9001,
                "clientOrderId": kwargs.get("newClientOrderId"),
                "executedQty": str(kwargs["quantity"]),
                "avgPrice": "3100.0",
            }
        if kwargs["order_type"] == "STOP_LOSS":
            return {
                "orderId": 9002,
                "clientOrderId": kwargs.get("newClientOrderId"),
                "status": "NEW",
                "stopPrice": str(kwargs["stopPrice"]),
            }
        return {"orderId": 9999, "status": "NEW"}

    mock_executor.place_order.side_effect = place_order_side_effect

    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=3000.0,
        initial_quantity=0.5,
        remaining_quantity=0.5,
        entry_time=time.time(),
        strategy="Test",
        initial_stop_loss=2950.0,
        current_sl_price=2950.0,
        initial_take_profit=3100.0,
        status="OPEN",
        entry_client_order_id="x-entry-spot-vtp",
        current_sl_order_id=111,
        current_sl_client_order_id="x-sl-old",
        partial_tp_orders=[
            PartialTpOrderInfo(
                target_price=3100.0,
                orig_fraction=0.5,
                quantity=0.25,
                status="VIRTUAL_PENDING",
            )
        ],
        market_type="spot",
    )
    controller._active_positions[symbol] = position

    triggered = await controller._check_spot_virtual_tp_triggers(
        symbol,
        high_price=3100.0,
        low_price=3000.0,
        last_price=3100.0,
    )
    await asyncio.sleep(0.2)

    assert triggered is True
    mock_executor.cancel_order.assert_called_with(
        symbol=symbol,
        orderId=111,
        origClientOrderId="x-sl-old",
        is_algo_order=False,
    )

    order_types = [
        call.kwargs["order_type"] for call in mock_executor.place_order.call_args_list
    ]
    assert order_types[0] == "MARKET"
    assert "STOP_LOSS" in order_types

    updated = controller._active_positions[symbol]
    assert updated.remaining_quantity == pytest.approx(0.25)
    assert updated.partial_tp_orders[0].status == "FILLED"
    assert updated.current_sl_order_id == 9002


@pytest.mark.asyncio
async def test_spot_no_stop_mode_places_real_tp(controller, mock_executor):
    symbol = "ETHUSDT"
    mock_executor.market_type = "spot"
    mock_executor.supports_positions = False
    mock_executor.place_order.return_value = {
        "orderId": 7001,
        "clientOrderId": "x-ptp-real",
        "status": "NEW",
    }

    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=3000.0,
        initial_quantity=0.5,
        remaining_quantity=0.5,
        entry_time=time.time(),
        strategy="Test",
        initial_stop_loss=None,
        current_sl_price=None,
        initial_take_profit=3100.0,
        no_stop_loss=True,
        signal_details={"no_stop_loss": True},
        status="OPEN",
        entry_client_order_id="x-entry-spot-no-sl",
        partial_tp_orders=[
            PartialTpOrderInfo(
                target_price=3100.0, orig_fraction=1.0, quantity=0.5, status="PENDING"
            )
        ],
        market_type="spot",
    )
    controller._active_positions[symbol] = position

    await controller._place_partial_tp(position, 3100.0, 0.5, 1.0, 0)

    mock_executor.place_order.assert_called_once()
    assert mock_executor.place_order.call_args.kwargs["order_type"] == "LIMIT"
    assert controller._active_positions[symbol].partial_tp_orders[0].order_id == 7001


@pytest.mark.asyncio
async def test_spot_after_sl_cancel_places_real_tp_even_with_sl_price(
    controller, mock_executor
):
    symbol = "ETHUSDT"
    mock_executor.market_type = "spot"
    mock_executor.supports_positions = False
    mock_executor.place_order.return_value = {
        "orderId": 7002,
        "clientOrderId": "x-ptp-after-sl-cancel",
        "status": "NEW",
    }

    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=3000.0,
        initial_quantity=0.5,
        remaining_quantity=0.5,
        entry_time=time.time(),
        strategy="Test",
        initial_stop_loss=2950.0,
        current_sl_price=2950.0,
        current_sl_order_id=None,
        current_sl_client_order_id=None,
        sl_placement_initiated=False,
        initial_take_profit=3100.0,
        status="OPEN",
        entry_client_order_id="x-entry-spot-sl-cancelled",
        partial_tp_orders=[
            PartialTpOrderInfo(
                target_price=3100.0, orig_fraction=1.0, quantity=0.5, status="PENDING"
            )
        ],
        market_type="spot",
    )
    controller._active_positions[symbol] = position

    await controller._place_partial_tp(position, 3100.0, 0.5, 1.0, 0)

    mock_executor.place_order.assert_called_once()
    assert mock_executor.place_order.call_args.kwargs["order_type"] == "LIMIT"
    assert controller._active_positions[symbol].partial_tp_orders[0].order_id == 7002


@pytest.mark.asyncio
async def test_successful_sl_placement_clears_initiated_flag(controller, mock_executor):
    symbol = "ETHUSDT"
    mock_executor.market_type = "spot"
    mock_executor.supports_positions = False
    mock_executor.get_open_positions.return_value = []
    mock_executor.get_ticker_price.return_value = {"price": "3000.0"}
    mock_executor.place_order.return_value = {
        "orderId": 8001,
        "clientOrderId": "x-sl-new",
        "status": "NEW",
    }
    controller._market_info_cache[symbol] = {
        "tick_size": 0.01,
        "lot_params": {"minQty": 0.001, "maxQty": 100000.0, "stepSize": 0.001},
        "min_notional": 1.0,
    }

    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=3000.0,
        initial_quantity=0.5,
        remaining_quantity=0.5,
        entry_time=time.time(),
        strategy="Test",
        initial_stop_loss=2950.0,
        current_sl_price=2950.0,
        initial_take_profit=None,
        status="OPEN",
        entry_client_order_id="x-entry-sl-flag",
        market_type="spot",
    )
    controller._active_positions[symbol] = position

    placed = await controller._place_stop_loss(position)

    assert placed is True
    updated = controller._active_positions[symbol]
    assert updated.current_sl_order_id == 8001
    assert updated.sl_placement_initiated is False


@pytest.mark.asyncio
async def test_close_position_treats_untradable_spot_remainder_as_dust(
    controller, mock_executor
):
    symbol = "XRPUSDT"
    mock_executor.market_type = "spot"
    mock_executor.supports_positions = False
    mock_executor.cancel_all_open_orders.return_value = {"success": True}
    mock_executor.get_account_balance.return_value = {
        "XRP": {"free": "0.0000645", "locked": "0"}
    }
    mock_executor.get_ticker_price.return_value = {"price": "2.0"}
    controller._market_info_cache[symbol] = {
        "tick_size": 0.0001,
        "lot_params": {"minQty": 0.0001, "maxQty": 100000000.0, "stepSize": 0.0001},
        "min_notional": 1.0,
    }

    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=2.0,
        initial_quantity=0.0000645,
        remaining_quantity=0.0000645,
        entry_time=time.time(),
        strategy="Test",
        initial_stop_loss=None,
        current_sl_price=None,
        initial_take_profit=None,
        status="OPEN",
        entry_client_order_id="x-entry-dust",
        market_type="spot",
    )
    controller._active_positions[symbol] = position

    await controller.close_position(symbol, reason="TEST_DUST_CLOSE")

    mock_executor.place_order.assert_not_called()
    assert symbol not in controller._active_positions


@pytest.mark.asyncio
async def test_close_position_stops_retry_on_spot_precision_rejection(
    controller, mock_executor
):
    symbol = "XRPUSDT"
    mock_executor.market_type = "spot"
    mock_executor.supports_positions = False
    mock_executor.cancel_all_open_orders.return_value = {"success": True}
    mock_executor.get_account_balance.return_value = {
        "XRP": {"free": "0.0000645", "locked": "0"}
    }
    mock_executor.get_ticker_price.return_value = {"price": "2.0"}
    mock_executor.get_lot_size_params = AsyncMock(return_value=None)
    mock_executor.get_min_notional = AsyncMock(return_value=None)
    mock_executor.place_order.return_value = {
        "error": True,
        "code": -999,
        "msg": "bybit amount of XRP/USDT must be greater than minimum amount precision of 0.0001",
    }
    controller._market_info_cache.pop(symbol, None)

    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=2.0,
        initial_quantity=0.0000645,
        remaining_quantity=0.0000645,
        entry_time=time.time(),
        strategy="Test",
        initial_stop_loss=None,
        current_sl_price=None,
        initial_take_profit=None,
        status="OPEN",
        entry_client_order_id="x-entry-precision-dust",
        market_type="spot",
    )
    controller._active_positions[symbol] = position

    await controller.close_position(symbol, reason="TEST_PRECISION_DUST_CLOSE")

    mock_executor.place_order.assert_called_once()
    assert symbol not in controller._active_positions


@pytest.mark.asyncio
async def test_close_position_waits_for_spot_locked_balance_before_close(
    controller, mock_executor
):
    symbol = "XRPUSDT"
    mock_executor.market_type = "spot"
    mock_executor.supports_positions = False
    mock_executor.cancel_all_open_orders.return_value = {"success": True}
    mock_executor.get_account_balance.side_effect = [
        {"XRP": {"free": "0.0000645", "locked": "2.0"}},
        {"XRP": {"free": "2.0", "locked": "0"}},
    ]
    mock_executor.get_ticker_price.return_value = {"price": "2.0"}

    async def mock_place_order(*args, **kwargs):
        controller._active_position_pop(symbol, "spot")
        return {
            "orderId": 9101,
            "clientOrderId": "x-close-ok",
            "status": "FILLED",
        }

    mock_executor.place_order = AsyncMock(side_effect=mock_place_order)
    controller._market_info_cache[symbol] = {
        "tick_size": 0.0001,
        "lot_params": {"minQty": 0.0001, "maxQty": 100000000.0, "stepSize": 0.0001},
        "min_notional": 1.0,
    }

    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=2.0,
        initial_quantity=2.0,
        remaining_quantity=2.0,
        entry_time=time.time(),
        strategy="Test",
        initial_stop_loss=None,
        current_sl_price=None,
        initial_take_profit=None,
        status="OPEN",
        entry_client_order_id="x-entry-locked-release",
        market_type="spot",
    )
    controller._active_positions["spot:XRPUSDT"] = position

    await controller.close_position(symbol, reason="TEST_LOCKED_RELEASE_CLOSE")

    mock_executor.place_order.assert_called_once()
    assert mock_executor.place_order.call_args.kwargs["quantity"] == pytest.approx(2.0)
    assert "spot:XRPUSDT" not in controller._active_positions


def test_strategy_signal_treats_zero_stop_as_no_stop_loss():
    signal = StrategySignal(
        strategy_name="Test",
        symbol="ETHUSDT",
        direction=SignalDirection.LONG,
        stop_loss=0.0,
        take_profit=3100.0,
        trigger_price=3000.0,
        mode=OrderMode.MARKET,
    )

    assert signal.stop_loss is None
    assert signal.no_stop_loss is True


@pytest.mark.asyncio
async def test_process_signal_allows_same_symbol_in_spot_and_futures(
    controller, mock_executor
):
    symbol = "BTCUSDT"
    controller._active_positions.clear()
    controller._recent_signals.clear()
    controller._signal_throttle_period = 0
    controller._symbol_cooldown_duration = 0
    controller._market_info_cache[symbol] = {
        "tick_size": 0.01,
        "lot_params": {"minQty": 0.00001, "maxQty": 9000.0, "stepSize": 0.00001},
        "min_notional": 10.0,
    }

    mock_executor.market_type = "futures_usdtm"
    mock_executor.supports_positions = True
    mock_executor.get_open_positions.return_value = []
    mock_executor.place_order = AsyncMock(
        return_value={
            "orderId": 1001,
            "clientOrderId": "x-futures-entry",
            "status": "FILLED",
            "executedQty": "0.01",
            "origQty": "0.01",
            "avgPrice": "50000.0",
            "fills": [
                {
                    "price": "50000.0",
                    "qty": "0.01",
                    "commission": "0",
                    "commissionAsset": "USDT",
                }
            ],
            "error": False,
        }
    )

    spot_executor = AsyncMock(spec=ExchangeExecutor)
    spot_executor.market_type = "spot"
    spot_executor.supports_positions = False
    spot_executor.get_open_positions.return_value = []
    spot_executor.place_order = AsyncMock(
        return_value={
            "orderId": 2001,
            "clientOrderId": "x-spot-entry",
            "status": "FILLED",
            "executedQty": "0.01",
            "origQty": "0.01",
            "avgPrice": "50000.0",
            "fills": [
                {
                    "price": "50000.0",
                    "qty": "0.01",
                    "commission": "0",
                    "commissionAsset": "USDT",
                }
            ],
            "error": False,
        }
    )
    controller.market_executors["futures_usdtm"] = mock_executor
    controller.market_executors["spot"] = spot_executor

    strategy = MagicMock()
    strategy.NAME = "MarketAwareStrategy"
    controller.running_strategy_instances.clear()
    controller.running_strategy_instances["futures-cfg"] = (
        strategy,
        {
            "id": "futures-cfg",
            "user_id": 1,
            "mode": "live",
            "config_data": {
                "strategy_name": "MarketAwareStrategy",
                "marketType": "FUTURES",
                "params": {},
            },
        },
    )
    controller.running_strategy_instances["spot-cfg"] = (
        strategy,
        {
            "id": "spot-cfg",
            "user_id": 1,
            "mode": "live",
            "config_data": {
                "strategy_name": "MarketAwareStrategy",
                "marketType": "SPOT",
                "params": {},
            },
        },
    )

    def make_signal(config_id: str, market_type: str) -> StrategySignal:
        return StrategySignal(
            strategy_name="MarketAwareStrategy",
            symbol=symbol,
            direction=SignalDirection.LONG,
            stop_loss=49000.0,
            take_profit=52000.0,
            trigger_price=50000.0,
            mode=OrderMode.MARKET,
            details={"strategy_config_id": config_id, "market_type": market_type},
        )

    with (
        patch(
            "bot_module.controller.crud.admin_get_user_details",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(controller, "_handle_entry_fill", new_callable=AsyncMock),
    ):
        await controller._process_signal(
            make_signal("futures-cfg", "futures_usdtm"),
            {
                "symbol": symbol,
                "atr": 50.0,
                "last_price": 50000.0,
                "market_type": "futures_usdtm",
            },
        )
        await controller._process_signal(
            make_signal("spot-cfg", "spot"),
            {
                "symbol": symbol,
                "atr": 50.0,
                "last_price": 50000.0,
                "market_type": "spot",
            },
        )
        await controller._process_signal(
            make_signal("futures-cfg", "futures_usdtm"),
            {
                "symbol": symbol,
                "atr": 50.0,
                "last_price": 50000.0,
                "market_type": "futures_usdtm",
            },
        )

    assert len(controller._active_positions) == 2
    assert controller._active_position_get(symbol, "futures_usdtm") is not None
    assert controller._active_position_get(symbol, "spot") is not None
    assert controller._active_positions.get(symbol) is None
    mock_executor.place_order.assert_called_once()
    spot_executor.place_order.assert_called_once()


@pytest.mark.asyncio
async def test_order_update_routes_same_symbol_by_event_market_type(controller):
    symbol = "BTCUSDT"
    controller._active_positions.clear()
    futures_position = make_position_for_market(
        symbol,
        "futures_usdtm",
        status="PENDING_ENTRY",
        entry_order_id=101,
        entry_client_order_id="x-futures-entry",
    )
    spot_position = make_position_for_market(
        symbol,
        "spot",
        status="PENDING_ENTRY",
        entry_order_id=202,
        entry_client_order_id="x-spot-entry",
    )
    controller._active_position_set(futures_position)
    controller._active_position_set(spot_position)

    futures_event = {
        "e": "ORDER_TRADE_UPDATE",
        "o": {
            "s": symbol,
            "i": 101,
            "c": "x-futures-entry",
            "X": "FILLED",
            "x": "TRADE",
            "S": "BUY",
            "ot": "MARKET",
            "q": "0.01",
            "z": "0.01",
            "ap": "50000",
            "l": "0.01",
            "L": "50000",
            "n": "0",
            "N": "USDT",
            "rp": "0",
        },
    }
    spot_event = {
        "e": "executionReport",
        "s": symbol,
        "i": 202,
        "c": "x-spot-entry",
        "X": "FILLED",
        "x": "TRADE",
        "S": "BUY",
        "o": "MARKET",
        "q": "0.01",
        "z": "0.01",
        "p": "50000",
        "l": "0.01",
        "L": "50000",
        "n": "0",
        "N": "USDT",
    }

    entry_fill_calls = []

    async def capture_entry_fill(**kwargs):
        entry_fill_calls.append(kwargs)

    with patch.object(controller, "_handle_entry_fill", capture_entry_fill):
        await controller._handle_order_update(futures_event)
        await asyncio.sleep(0)
        assert len(entry_fill_calls) == 1
        assert entry_fill_calls[-1]["order_id"] == "101"
        assert entry_fill_calls[-1]["market_type"] == "futures_usdtm"

        entry_fill_calls.clear()
        await controller._handle_order_update(spot_event)
        await asyncio.sleep(0)
        assert len(entry_fill_calls) == 1
        assert entry_fill_calls[-1]["order_id"] == "202"
        assert entry_fill_calls[-1]["market_type"] == "spot"


@pytest.mark.asyncio
async def test_close_position_requires_market_type_when_symbol_is_ambiguous(
    controller, mock_executor
):
    symbol = "BTCUSDT"
    controller._active_positions.clear()
    controller._active_position_set(make_position_for_market(symbol, "futures_usdtm"))
    controller._active_position_set(make_position_for_market(symbol, "spot"))

    await controller.close_position(symbol, reason="TEST_AMBIGUOUS_CLOSE")

    assert controller._active_position_get(symbol, "futures_usdtm") is not None
    assert controller._active_position_get(symbol, "spot") is not None
    mock_executor.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_close_position_with_market_type_closes_only_that_market(
    controller, mock_executor
):
    symbol = "BTCUSDT"
    controller._active_positions.clear()
    futures_position = make_position_for_market(symbol, "futures_usdtm")
    spot_position = make_position_for_market(symbol, "spot")
    controller._active_position_set(futures_position)
    controller._active_position_set(spot_position)

    spot_executor = AsyncMock(spec=ExchangeExecutor)
    spot_executor.market_type = "spot"
    spot_executor.supports_positions = False
    spot_executor.get_account_balance.return_value = {
        "BTC": {"free": "0.01", "locked": "0"}
    }
    spot_executor.get_ticker_price.return_value = {"price": "50000.0"}

    async def mock_place_order_spot(*args, **kwargs):
        controller._active_position_pop("BTCUSDT", "spot")
        return {
            "orderId": 3001,
            "clientOrderId": "x-close-spot",
            "status": "FILLED",
        }

    spot_executor.place_order = AsyncMock(side_effect=mock_place_order_spot)
    controller.market_executors["spot"] = spot_executor
    controller._market_info_cache[symbol] = {
        "tick_size": 0.01,
        "lot_params": {"minQty": 0.00001, "maxQty": 9000.0, "stepSize": 0.00001},
        "min_notional": 10.0,
    }

    with patch.object(
        controller, "_handle_final_exit", new_callable=AsyncMock
    ) as mock_final_exit:
        await controller.close_position(
            symbol, reason="TEST_SPOT_CLOSE", market_type="spot"
        )

    assert controller._active_position_get(symbol, "spot") is None
    assert controller._active_position_get(symbol, "futures_usdtm") is futures_position
    spot_executor.place_order.assert_called_once()
    mock_executor.place_order.assert_not_called()
    mock_final_exit.assert_called_once()
    assert mock_final_exit.call_args.kwargs["market_type"] == "spot"


@pytest.mark.asyncio
async def test_reconcile_futures_does_not_remove_same_symbol_spot_position(
    controller, mock_executor
):
    symbol = "BTCUSDT"
    controller._active_positions.clear()
    controller._active_position_set(make_position_for_market(symbol, "futures_usdtm"))
    spot_position = make_position_for_market(symbol, "spot")
    controller._active_position_set(spot_position)
    mock_executor.market_type = "futures_usdtm"
    mock_executor.get_open_positions.return_value = []

    await controller._reconcile_positions_with_exchange()

    assert controller._active_position_get(symbol, "futures_usdtm") is None
    assert controller._active_position_get(symbol, "spot") is spot_position


def test_restore_coerces_active_positions_to_market_aware_map(controller):
    futures_position = make_position_for_market("BTCUSDT", "futures_usdtm")
    spot_position = make_position_for_market("BTCUSDT", "spot")

    restored = controller._coerce_active_position_map(
        {
            "BTCUSDT": futures_position,
            ("spot", "BTCUSDT"): spot_position,
        }
    )

    assert len(restored) == 2
    assert restored.get_by_symbol("BTCUSDT", "futures_usdtm") is futures_position
    assert restored.get_by_symbol("BTCUSDT", "spot") is spot_position
    assert restored.get("BTCUSDT") is None


@pytest.mark.asyncio
async def test_handle_order_update_sl_rejected(controller, mock_executor):
    strategy_name = "FirstPullbacksInTrend"
    symbol = "BTCUSDT"
    initial_qty = 0.01
    entry_price = 50000.0
    sl_order_id = 555
    sl_client_order_id = "x-sl-reject"
    sl_price = 49500.0
    tp_target_price = 51000.0
    tp_order_id = 666
    tp_client_order_id = "x-tp-reject"
    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=entry_price,
        initial_quantity=initial_qty,
        remaining_quantity=initial_qty,
        entry_time=time.time(),
        strategy=strategy_name,
        initial_stop_loss=sl_price,
        current_sl_price=sl_price,
        initial_take_profit=tp_target_price,
        status="OPEN",
        entry_order_id=123,
        entry_client_order_id="x-entry-slreject",
        current_sl_order_id=sl_order_id,
        current_sl_client_order_id=sl_client_order_id,
        partial_tp_orders=[
            PartialTpOrderInfo(
                target_price=tp_target_price,
                orig_fraction=1.0,
                quantity=initial_qty,
                order_id=tp_order_id,
                client_order_id=tp_client_order_id,
                status="PENDING",
            )
        ],
    )
    controller._active_positions[symbol] = position
    exec_report_sl_reject = {
        "e": "ORDER_TRADE_UPDATE",
        "o": {
            "s": symbol,
            "c": sl_client_order_id,
            "i": sl_order_id,
            "S": "SELL",
            "ot": "STOP_MARKET",
            "x": "REJECTED",
            "X": "REJECTED",
            "q": str(initial_qty),
            "z": "0.0",
            "l": "0.0",
            "L": "0.0",
            "ap": "0.0",
        },
    }

    # Mock get_ticker_price for preflight check in _place_stop_loss
    mock_executor.get_ticker_price = AsyncMock(return_value={"price": str(entry_price)})
    mock_executor.place_order.side_effect = create_mock_executor_place_order_sequence(
        symbol
    )

    with patch.object(
        controller, "_place_stop_loss", wraps=controller._place_stop_loss
    ) as spy_place_sl:
        await controller._handle_order_update(exec_report_sl_reject)
        await asyncio.sleep(0.1)
        spy_place_sl.assert_called_once()

    assert symbol in controller._active_positions
    updated_position = controller._active_positions[symbol]
    assert updated_position.status == "OPEN"
    mock_executor.place_order.assert_called_once()
    assert updated_position.current_sl_order_id == 1001
    assert updated_position.current_sl_price == sl_price


@pytest.mark.asyncio
async def test_handle_order_update_entry_canceled_open_partial_fill(
    controller, mock_executor
):
    symbol = "ETHUSDT"
    client_order_id = "x-entry-partial"
    order_id = 999
    original_qty = 1.0
    filled_qty = 0.4
    entry_price = 3000.0
    sl = 2950.0
    tp = 3100.0

    controller.executors["live"].market_type = "futures_usdtm"

    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=entry_price,
        initial_quantity=original_qty,
        remaining_quantity=original_qty,
        entry_time=time.time(),
        strategy="Test",
        initial_stop_loss=sl,
        current_sl_price=sl,
        initial_take_profit=tp,
        status="OPEN",
        entry_order_id=order_id,
        entry_client_order_id=client_order_id,
        current_sl_order_id=5550,
        current_sl_client_order_id="x-sl-old",
        original_partial_targets_plan=[PartialTarget(price=tp, fraction=1.0)],
        partial_tp_orders=[
            PartialTpOrderInfo(
                target_price=tp,
                orig_fraction=1.0,
                quantity=original_qty,
                order_id=6660,
                client_order_id="x-tp-old",
                status="PENDING",
            )
        ],
    )
    controller._active_positions[symbol] = position

    exec_report = {
        "e": "ORDER_TRADE_UPDATE",
        "o": {
            "s": symbol,
            "c": client_order_id,
            "i": order_id,
            "S": "BUY",
            "ot": "LIMIT",
            "x": "CANCELED",
            "X": "CANCELED",
            "q": str(original_qty),
            "z": str(filled_qty),
            "ap": str(entry_price),
        },
    }

    mock_executor.cancel_order.return_value = {"status": "CANCELED"}
    mock_executor.place_order.side_effect = create_mock_executor_place_order_sequence(
        symbol
    )
    mock_executor.get_ticker_price = AsyncMock(return_value={"price": str(entry_price)})

    await controller._handle_order_update(exec_report)
    await asyncio.sleep(0.15)

    assert controller._active_positions[symbol].initial_quantity == filled_qty
    # Checking that cancel_order was called for old orders
    assert mock_executor.cancel_order.call_count >= 2

    assert mock_executor.place_order.call_count == 2
    sl_call_kwargs = mock_executor.place_order.call_args_list[0].kwargs
    tp_call_kwargs = mock_executor.place_order.call_args_list[1].kwargs
    assert math.isclose(sl_call_kwargs["quantity"], filled_qty)
    assert math.isclose(tp_call_kwargs["quantity"], filled_qty)


@pytest.mark.asyncio
async def test_handle_order_update_sl_filled(
    controller, mock_risk_manager, mock_executor, mock_trade_logger
):
    strategy_name = "FirstPullbacksInTrend"
    symbol = "BTCUSDT"
    initial_qty = 0.01
    entry_price = 50000.0
    sl_order_id = 555
    sl_client_order_id = "x-sl-1"
    sl_price = 49500.0
    tp_target_price = 51000.0
    tp_order_id = 666
    tp_client_order_id = "x-tp-1"
    planned_risk = 100.0

    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=entry_price,
        initial_quantity=initial_qty,
        remaining_quantity=initial_qty,
        entry_time=time.time(),
        strategy=strategy_name,
        initial_stop_loss=sl_price,
        current_sl_price=sl_price,
        initial_take_profit=tp_target_price,
        status="OPEN",
        entry_order_id=123,
        entry_client_order_id="x-entry-slfill",
        current_sl_order_id=sl_order_id,
        current_sl_client_order_id=sl_client_order_id,
        partial_tp_orders=[
            PartialTpOrderInfo(
                target_price=tp_target_price,
                orig_fraction=1.0,
                quantity=initial_qty,
                order_id=tp_order_id,
                client_order_id=tp_client_order_id,
                status="PENDING",
            )
        ],
        initial_risk_usd_planned=planned_risk,
    )
    controller._active_positions[symbol] = position

    exec_report_sl = {
        "e": "ORDER_TRADE_UPDATE",
        "o": {
            "s": symbol,
            "c": sl_client_order_id,
            "i": sl_order_id,
            "S": "SELL",
            "ot": "STOP_MARKET",
            "x": "TRADE",
            "X": "FILLED",
            "q": str(initial_qty),
            "z": str(initial_qty),
            "l": str(initial_qty),
            "L": str(sl_price),
            "ap": str(sl_price),
            "n": "0.1",
            "N": "USDT",
        },
    }

    mock_executor.cancel_order.return_value = {
        "symbol": symbol,
        "orderId": tp_order_id,
        "status": "CANCELED",
    }
    mock_risk_manager.update_trade_result.reset_mock()
    mock_risk_manager.update_symbol_strategy_performance.reset_mock()

    await controller._handle_order_update(exec_report_sl)
    await asyncio.sleep(0.1)

    assert symbol not in controller._active_positions
    mock_executor.cancel_order.assert_called_with(
        symbol=symbol,
        orderId=tp_order_id,
        origClientOrderId=tp_client_order_id,
        is_algo_order=False,
    )

    expected_pnl = (sl_price - entry_price) * initial_qty
    mock_risk_manager.update_trade_result.assert_called_once()
    assert mock_risk_manager.update_trade_result.call_args[0][0] == symbol
    assert math.isclose(
        mock_risk_manager.update_trade_result.call_args[0][1], expected_pnl
    )

    mock_risk_manager.update_symbol_strategy_performance.assert_called_once_with(
        symbol=symbol,
        strategy_name=strategy_name,
        pnl_usd=pytest.approx(expected_pnl),
        initial_risk_usd_planned=planned_risk,
    )
    mock_trade_logger.log_event.assert_any_call(
        event_type="POSITION_CLOSED",
        data=expect({"exit_reason": "STOP_LOSS", "pnl": pytest.approx(expected_pnl)}),
    )


@pytest.mark.asyncio
async def test_handle_order_update_tp_filled(controller, mock_executor):
    symbol = "ETHUSDT"
    sl_order_id = 555
    sl_client_order_id = "x-sl-2"
    tp_order_id = 666
    tp_client_order_id = "x-tp-2"

    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=3000.0,
        initial_quantity=0.5,
        remaining_quantity=0.5,
        entry_time=time.time(),
        strategy="Test",
        initial_stop_loss=2950.0,
        current_sl_price=2950.0,
        initial_take_profit=3100.0,
        status="OPEN",
        entry_order_id=456,
        current_sl_order_id=sl_order_id,
        current_sl_client_order_id=sl_client_order_id,
        partial_tp_orders=[
            PartialTpOrderInfo(
                target_price=3100.0,
                orig_fraction=1.0,
                quantity=0.5,
                order_id=tp_order_id,
                client_order_id=tp_client_order_id,
                status="PENDING",
            )
        ],
    )
    controller._active_positions[symbol] = position

    exec_report_tp = {
        "e": "ORDER_TRADE_UPDATE",
        "o": {
            "s": symbol,
            "c": tp_client_order_id,
            "i": tp_order_id,
            "S": "SELL",
            "ot": "LIMIT",
            "x": "TRADE",
            "X": "FILLED",
            "z": "0.5",
            "l": "0.5",
            "L": "3100.0",
        },
    }

    mock_executor.cancel_order.return_value = {"status": "CANCELED"}
    await controller._handle_order_update(exec_report_tp)
    await asyncio.sleep(0.1)

    assert symbol not in controller._active_positions
    mock_executor.cancel_order.assert_called_with(
        symbol=symbol,
        orderId=sl_order_id,
        origClientOrderId=sl_client_order_id,
        is_algo_order=False,
    )


@pytest.mark.asyncio
async def test_place_stop_loss_failure_triggers_emergency_close(
    controller, mock_executor
):
    strategy_name = "FirstPullbacksInTrend"
    symbol = "BTCUSDT"

    mock_notifier = MagicMock()
    mock_notifier.bot_error = AsyncMock()
    mock_notifier.position_closed = AsyncMock()
    controller.telegram_notifier = mock_notifier

    entry_price = 50000.0
    initial_qty = 0.01
    sl_price = 49500.0

    # Add missing attributes to avoid TypeError when accessing them in the code
    position_to_protect = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=entry_price,
        initial_quantity=initial_qty,
        remaining_quantity=initial_qty,
        entry_time=time.time(),
        strategy=strategy_name,
        user_id=1,
        config_id="test-cfg",
        initial_stop_loss=sl_price,
        current_sl_price=sl_price,
        initial_take_profit=51000.0,
        status="OPEN",
        entry_client_order_id=f"test-entry-{uuid.uuid4().hex[:4]}",
        signal_details={
            "lot_step_size": "0.00001"
        },  # For comparison in _handle_order_update
    )
    controller._active_positions[symbol] = position_to_protect

    async def faulty_place_order(*args, **kwargs):
        order_type = kwargs.get("order_type")
        if order_type != "MARKET":
            raise ConnectionError("Exchange is unavailable")
        return {
            "status": "FILLED",
            "orderId": 9999,
            "clientOrderId": kwargs.get("newClientOrderId"),
            "error": False,
        }

    mock_executor.place_order.side_effect = faulty_place_order
    # Adding get_ticker_price so the preflight check passes
    mock_executor.get_ticker_price = AsyncMock(return_value={"price": str(entry_price)})
    # Add get_open_positions so that synchronization with the exchange works correctly
    mock_executor.get_open_positions = AsyncMock(
        return_value=[
            {
                "symbol": symbol,
                "positionAmt": str(initial_qty),
                "entryPrice": str(entry_price),
            }
        ]
    )

    success = await controller._place_stop_loss(position_to_protect)
    await asyncio.sleep(0.5)

    assert success is False
    # After an SL error, the position must be closed urgently; bot_error is called from close_position
    # but the notification might not be sent if there is no chat_id

    # Check that there was an attempt to place an SL (which failed) and then a MARKET order to close
    assert mock_executor.place_order.call_count >= 1

    # The last call must be a MARKET order to close
    last_call = mock_executor.place_order.call_args
    assert last_call.kwargs["symbol"] == symbol
    assert last_call.kwargs["side"] == "SELL"
    assert last_call.kwargs["order_type"] == "MARKET"
    assert last_call.kwargs["quantity"] == initial_qty


@pytest.mark.asyncio
async def test_check_and_close_positions_without_sl_triggers_for_old_position(
    controller, mock_executor
):
    """
    The test verifies that a position without a stop-loss is actually CLOSED (removed from _active_positions),
    rather than just transitioning to CLOSING status.

    This is a regression test for the bug from 17.12.2025, when the position remained open.
    """
    strategy_name = "FirstPullbacksInTrend"
    symbol = "ETHUSDT"
    grace_period = controller.sl_placement_grace_period

    mock_notifier = MagicMock()
    mock_notifier.bot_error = AsyncMock()
    mock_notifier.position_closed = AsyncMock()
    controller.telegram_notifier = mock_notifier

    initial_qty = 0.5
    stale_position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=3000.0,
        initial_quantity=initial_qty,
        remaining_quantity=initial_qty,
        entry_time=time.time() - (grace_period * 3),
        strategy=strategy_name,
        user_id=1,
        config_id="test-cfg",
        initial_stop_loss=2950.0,
        current_sl_price=2950.0,
        initial_take_profit=3100.0,  # Required parameter
        status="OPEN",
        current_sl_order_id=None,
        sl_placement_initiated=False,
        time_status_open=time.time() - (grace_period * 2),
    )
    controller._active_position_set(stale_position)

    # Call counter to track attempts
    place_order_call_count = 0

    async def mock_place_order_with_fill(*args, **kwargs):
        nonlocal place_order_call_count
        place_order_call_count += 1
        order_type = kwargs.get("order_type", "UNKNOWN")
        if order_type == "MARKET":
            # Simulate successful execution of a MARKET order
            # In a real system, a WebSocket update arrives after order execution,
            # which calls _handle_final_exit and removes the position.
            # Here we simulate this behavior directly:
            async with controller._positions_dict_lock:
                pos = controller._active_position_get(symbol, "futures_usdtm")
                if pos:
                    # Set remaining_quantity = 0 so that close_position sees it
                    pos.remaining_quantity = 0
            return {
                "status": "FILLED",
                "orderId": 8888,
                "error": False,
                "executedQty": str(initial_qty),
            }
        return {"status": "NEW", "orderId": 8888, "error": False}

    mock_executor.place_order.side_effect = mock_place_order_with_fill
    mock_executor.get_ticker_price = AsyncMock(return_value={"price": "3000.0"})

    # Add get_open_positions dynamically so that synchronization with the exchange works correctly
    async def mock_get_open_positions():
        if (
            controller._active_position_get(symbol, "futures_usdtm") is None
            or controller._active_position_get(
                symbol, "futures_usdtm"
            ).remaining_quantity
            <= 0
        ):
            return []
        return [
            {"symbol": symbol, "positionAmt": str(initial_qty), "entryPrice": "3000.0"}
        ]

    mock_executor.get_open_positions.side_effect = mock_get_open_positions

    # Mocking _handle_final_exit so it simply removes the position
    async def mock_handle_final_exit(*args, **kwargs):
        symbol_arg = kwargs.get("symbol")
        async with controller._positions_dict_lock:
            if controller._active_position_get(symbol_arg, "futures_usdtm"):
                controller._active_position_pop(symbol_arg, "futures_usdtm")

    with patch.object(
        controller, "_handle_final_exit", side_effect=mock_handle_final_exit
    ):
        # Calling the check
        await controller._check_and_close_positions_without_sl()

        # Give time for close_position() to execute
        await asyncio.sleep(1.5)

    # MAIN TEST: the position must be REMOVED from active ones after successful closing
    assert controller._active_position_get(symbol, "futures_usdtm") is None, (
        f"Position {symbol} should be removed after emergency closing, but it is still in _active_positions"
    )

    # Telegram notification must be sent
    mock_notifier.bot_error.assert_called()

    # MARKET order to close must be sent
    assert place_order_call_count >= 1, (
        "There should be at least one place_order call for closing"
    )


@pytest.mark.asyncio
async def test_check_and_close_positions_without_sl_retries_stuck_closing(
    controller, mock_executor
):
    """
    The test verifies that positions stuck in CLOSING status are re-closed.

    This is a second level of protection: if the first closing attempt failed,
    the next check cycle should retry the attempt.
    """
    strategy_name = "FirstPullbacksInTrend"
    symbol = "BTCUSDT"

    mock_notifier = MagicMock()
    mock_notifier.bot_error = AsyncMock()
    mock_notifier.position_closed = AsyncMock()
    controller.telegram_notifier = mock_notifier

    initial_qty = 0.01
    # Create a position that is already in CLOSING status but not yet closed
    stuck_position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=50000.0,
        initial_quantity=initial_qty,
        remaining_quantity=initial_qty,  # remaining > 0!
        entry_time=time.time() - 300,  # Opened a long time ago
        strategy=strategy_name,
        user_id=1,
        config_id="test-cfg",
        initial_stop_loss=49000.0,
        current_sl_price=49000.0,
        initial_take_profit=52000.0,  # Required parameter
        status="CLOSING",  # ALREADY in CLOSING status
        current_sl_order_id=None,
        exit_reason="EMERGENCY_NO_SL_DETECTED_PREVIOUS",
    )
    controller._active_position_set(stuck_position)

    async def mock_place_order_success(*args, **kwargs):
        order_type = kwargs.get("order_type", "UNKNOWN")
        if order_type == "MARKET":
            # Simulating position removal after order execution
            async with controller._positions_dict_lock:
                pos = controller._active_position_get(symbol, "futures_usdtm")
                if pos:
                    pos.remaining_quantity = 0
            return {
                "status": "FILLED",
                "orderId": 9999,
                "error": False,
                "executedQty": str(initial_qty),
            }

    mock_executor.place_order.side_effect = mock_place_order_success
    mock_executor.get_ticker_price = AsyncMock(return_value={"price": "50000.0"})

    # Add get_open_positions dynamically so that synchronization with the exchange works correctly
    async def mock_get_open_positions_stuck():
        if (
            controller._active_position_get(symbol, "futures_usdtm") is None
            or controller._active_position_get(
                symbol, "futures_usdtm"
            ).remaining_quantity
            <= 0
        ):
            return []
        return [
            {"symbol": symbol, "positionAmt": str(initial_qty), "entryPrice": "50000.0"}
        ]

    mock_executor.get_open_positions.side_effect = mock_get_open_positions_stuck

    # Directly calling close_position for a position in CLOSING status
    # This tests that close_position will continue working even if the status is already CLOSING
    # Note: close_position will remove the position itself when it sees remaining_quantity = 0
    await controller.close_position(symbol, "RETRY_CLOSE_TEST")
    await asyncio.sleep(0.2)

    # The position must be removed after successful re-closure
    assert controller._active_position_get(symbol, "futures_usdtm") is None, (
        f"Stuck position {symbol} should be deleted after re-closing"
    )

    # Check that place_order was called (MARKET order for closure)
    assert mock_executor.place_order.called, "place_order must be called for closing"


@pytest.mark.asyncio
async def test_close_position_syncs_with_exchange_before_closing(
    controller, mock_executor
):
    """
    The test verifies that close_position synchronizes remaining_quantity with the exchange
    before sending a closing order.

    This is a regression test for a bug where a position was partially closed due to
    desynchronization between the local remaining_quantity and the actual size on the exchange.
    """
    strategy_name = "FirstPullbacksInTrend"
    symbol = "PTBUSDT"

    # Local position size (deprecated)
    internal_qty = 1000.0
    # Real size on the exchange
    exchange_qty = 2548.0

    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=0.006,
        initial_quantity=exchange_qty,
        remaining_quantity=internal_qty,  # Desynchronization!
        entry_time=time.time() - 3600,
        strategy=strategy_name,
        user_id=1,
        config_id="test-cfg",
        initial_stop_loss=0.005,
        current_sl_price=0.005,
        initial_take_profit=0.007,
        status="OPEN",
        current_sl_order_id=None,
    )
    controller._active_position_set(position)

    # Mock get_open_positions returns the real size from the exchange dynamically
    async def mock_get_open_positions_sync():
        if (
            controller._active_position_get(symbol, "futures_usdtm") is None
            or controller._active_position_get(
                symbol, "futures_usdtm"
            ).remaining_quantity
            <= 0
        ):
            return []
        return [
            {"symbol": symbol, "positionAmt": str(exchange_qty), "entryPrice": "0.006"}
        ]

    mock_executor.get_open_positions.side_effect = mock_get_open_positions_sync

    captured_qty = None

    async def mock_place_order_capture(*args, **kwargs):
        nonlocal captured_qty
        captured_qty = kwargs.get("quantity")
        # Simulating closing
        async with controller._positions_dict_lock:
            pos = controller._active_position_get(symbol, "futures_usdtm")
            if pos:
                pos.remaining_quantity = 0
        return {
            "status": "FILLED",
            "orderId": 1234,
            "error": False,
            "executedQty": str(captured_qty),
        }

    mock_executor.place_order.side_effect = mock_place_order_capture
    mock_executor.get_ticker_price = AsyncMock(return_value={"price": "0.006"})

    # Calling close_position
    await controller.close_position(symbol, "TEST_SYNC")
    await asyncio.sleep(0.2)

    # MAIN TEST: place_order must be called with the ACTUAL size from the exchange, not the local one!
    assert captured_qty == exchange_qty, (
        f"close_position should use the size from the exchange ({exchange_qty}), not local ({internal_qty}). "
        f"Actually used: {captured_qty}"
    )

    # Position should be deleted
    assert controller._active_position_get(symbol, "futures_usdtm") is None, (
        f"Position {symbol} should be deleted after closing"
    )


@pytest.mark.asyncio
async def test_close_position_with_small_qty_below_minqty(controller, mock_executor):
    """
    Test for the bug from 02.01.2026 with LIGHTUSDT:
    A position with remaining_quantity below the exchange's minQty should be successfully closed
    via a reduceOnly order (the exchange allows closing any remaining balances).

    This is a regression test for the case where _adjust_and_round_quantity returns None
    due to too small a quantity, but close_position should still close the position.
    """
    strategy_name = "FirstPullbacksInTrend"
    symbol = "LIGHTUSDT"

    mock_notifier = MagicMock()
    mock_notifier.bot_error = AsyncMock()
    mock_notifier.position_closed = AsyncMock()
    controller.telegram_notifier = mock_notifier

    # Simulating a case with a very small quantity (below minQty)
    small_qty = 0.4  # This is less than the typical minQty
    entry_price = 0.01

    position = Position(
        symbol=symbol,
        direction=SignalDirection.LONG,
        entry_price=entry_price,
        initial_quantity=7.0,
        remaining_quantity=small_qty,  # Little remains due to partial TP
        entry_time=time.time() - 3600,
        strategy=strategy_name,
        user_id=1,
        config_id="test-cfg",
        initial_stop_loss=0.009,
        current_sl_price=0.009,
        initial_take_profit=0.012,
        status="OPEN",
        current_sl_order_id=None,
        entry_client_order_id="test-light-entry",
    )
    controller._active_position_set(position)

    # Mock get_open_positions returns the real size from the exchange dynamically
    async def mock_get_open_positions_small():
        if (
            controller._active_position_get(symbol, "futures_usdtm") is None
            or controller._active_position_get(
                symbol, "futures_usdtm"
            ).remaining_quantity
            <= 0
        ):
            return []
        return [
            {
                "symbol": symbol,
                "positionAmt": str(small_qty),
                "entryPrice": str(entry_price),
            }
        ]

    mock_executor.get_open_positions.side_effect = mock_get_open_positions_small

    captured_qty = None
    captured_reduce_only = None

    async def mock_place_order_capture(*args, **kwargs):
        nonlocal captured_qty, captured_reduce_only
        captured_qty = kwargs.get("quantity")
        captured_reduce_only = kwargs.get("reduceOnly")
        # Simulating closing
        async with controller._positions_dict_lock:
            pos = controller._active_position_get(symbol, "futures_usdtm")
            if pos:
                pos.remaining_quantity = 0
        return {
            "status": "FILLED",
            "orderId": 1234,
            "error": False,
            "executedQty": str(captured_qty),
        }

    mock_executor.place_order.side_effect = mock_place_order_capture
    mock_executor.get_ticker_price = AsyncMock(return_value={"price": str(entry_price)})

    # Call close_position with emergency closure reason due to invalid SL
    await controller.close_position(symbol, "EMERGENCY_SL_QTY_INVALID")
    await asyncio.sleep(0.2)

    # MAIN TEST 1: place_order MUST be called even with a small quantity
    assert mock_executor.place_order.called, (
        f"close_position must call place_order even for a small quantity {small_qty}"
    )

    # MAIN TEST 2: Quantity must be correctly rounded (not 0)
    assert captured_qty is not None and captured_qty > 0, (
        f"Quantity for the closing order must be > 0, but received {captured_qty}"
    )

    # MAIN TEST 3: reduceOnly must be True
    assert captured_reduce_only, (
        "The closing order must have reduceOnly=True to bypass the minQty filter"
    )

    # Position should be deleted
    assert symbol not in controller._active_positions, (
        f"Position {symbol} should be deleted after closing"
    )
