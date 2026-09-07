# tests/test_position_adoption_and_runtime_state.py
"""
Unit tests for position adoption, algo order handling, duplicate SL cleanup,
and multi-key Redis runtime state isolation.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot_module.controller import LivePosition, PartialTpOrderInfo, TradingController
from bot_module.datatypes import SignalDirection
from bot_module.exchanges.ccxt_executor import CcxtExecutor


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
def make_controller():
    def _create(user_id=186, api_key_id=1, api_key_name="TestKey"):
        loop = asyncio.get_event_loop()
        consumer = AsyncMock()
        consumer.get_active_symbols.return_value = {"ETHUSDT"}
        consumer.get_active_pair_by_symbol.return_value = {
            "symbol": "ETHUSDT",
            "last_price": 2500.0,
            "high": 2510.0,
            "low": 2490.0,
            "close": 2500.0,
            "atr": 20.0,
            "tick_size": 0.01,
        }

        live_executor = AsyncMock()
        live_executor.market_type = "futures_usdtm"
        live_executor.get_open_positions.return_value = []
        live_executor.get_open_orders.return_value = []
        live_executor.get_open_algo_orders = AsyncMock(return_value=[])

        paper_executor = AsyncMock()
        risk_manager = MagicMock()
        risk_manager.user_telegram_chat_id = None
        risk_manager.max_concurrent_trades = 5

        controller = TradingController(
            loop=loop,
            data_consumer=consumer,
            live_executor=live_executor,
            paper_executor=paper_executor,
            risk_manager=risk_manager,
            user_id=user_id,
            api_key_id=api_key_id,
            api_key_name=api_key_name,
        )

        async def mock_db():
            yield AsyncMock()

        controller.get_db_session = mock_db
        return controller

    return _create


@pytest.mark.asyncio
async def test_redis_runtime_state_isolation_by_api_key(make_controller):
    """
    Verifies that two controllers with same user_id but different api_key_id
    (e.g., OKX and WEEX) do not overwrite each other's runtime state.
    """
    redis = MockRedis()
    ctrl_weex = make_controller(user_id=186, api_key_id=10, api_key_name="WEEX")
    ctrl_okx = make_controller(user_id=186, api_key_id=20, api_key_name="OKX")
    ctrl_weex.redis_client = redis
    ctrl_okx.redis_client = redis

    # Ensure keys are distinct
    assert ctrl_weex.redis_key_runtime_state == "depthsight:controller:runtime_state:186:10"
    assert ctrl_okx.redis_key_runtime_state == "depthsight:controller:runtime_state:186:20"

    # Start strategy on WEEX
    payload_weex = {
        "user_id": 186,
        "id": "strat_weex:inst1",
        "config_id": "strat_weex",
        "mode": "live",
        "symbol_selection_mode": "STATIC",
        "symbols": ["ETHUSDT"],
        "name": "WeexStrategy",
        "api_key_id": 10,
        "config_data": {"strategy_name": "VisualBuilderStrategy"},
    }
    await ctrl_weex._handle_start_strategy_command(payload_weex)

    # Start strategy on OKX
    payload_okx = {
        "user_id": 186,
        "id": "strat_okx:inst1",
        "config_id": "strat_okx",
        "mode": "live",
        "symbol_selection_mode": "STATIC",
        "symbols": ["BTCUSDT"],
        "name": "OkxStrategy",
        "api_key_id": 20,
        "config_data": {"strategy_name": "VisualBuilderStrategy"},
    }
    await ctrl_okx._handle_start_strategy_command(payload_okx)

    # Verify both snapshots exist independently
    raw_weex = await redis.get("depthsight:controller:runtime_state:186:10")
    raw_okx = await redis.get("depthsight:controller:runtime_state:186:20")
    assert raw_weex is not None
    assert raw_okx is not None

    weex_data = json.loads(raw_weex)
    okx_data = json.loads(raw_okx)
    assert weex_data["running_strategies"][0]["config_id"] == "strat_weex"
    assert okx_data["running_strategies"][0]["config_id"] == "strat_okx"


@pytest.mark.asyncio
async def test_redis_runtime_state_fallback_legacy_key(make_controller):
    """
    Verifies backward compatibility: if scoped key doesn't exist,
    controller falls back to legacy depthsight:controller:runtime_state:{user_id}.
    """
    redis = MockRedis()
    ctrl = make_controller(user_id=186, api_key_id=10, api_key_name="WEEX")
    ctrl.redis_client = redis

    # Populate legacy key with serialization_format=json
    legacy_payload = {
        "serialization_format": "json",
        "timestamp": 1788700000.0,
        "running_strategies": [
            {
                "user_id": 186,
                "id": "legacy_strat:inst1",
                "config_id": "legacy_strat",
                "mode": "live",
                "symbol_selection_mode": "STATIC",
                "symbols": ["ETHUSDT"],
                "name": "LegacyStrategy",
                "api_key_id": 10,
                "config_data": {"strategy_name": "VisualBuilderStrategy"},
            }
        ],
    }
    await redis.set("depthsight:controller:runtime_state:186", json.dumps(legacy_payload))

    # Load runtime state
    await ctrl._load_runtime_state()

    assert len(ctrl.running_strategy_instances) == 1
    assert "legacy_strat:inst1" in ctrl.running_strategy_instances


@pytest.mark.asyncio
async def test_ccxt_weex_open_algo_orders_fetch():
    """
    Verifies that get_open_algo_orders on WEEX passes params={'type': 'swap', 'trigger': True}.
    """
    executor = CcxtExecutor(
        exchange_id="weex",
        api_key="k",
        api_secret="s",
        market_type="futures_usdtm",
        password="p",
    )
    mock_exchange = AsyncMock()
    mock_exchange.fetch_open_orders.return_value = [
        {
            "id": "791462386857935224",
            "symbol": "ETH/USDT:USDT",
            "type": "market",
            "side": "sell",
            "amount": 0.006,
            "triggerPrice": 2461.26,
            "info": {
                "orderId": "791462386857935224",
                "clientOrderId": "b-WEEX111159-x-sl-20d75d38d5b04c",
                "orderType": "STOP_MARKET",
                "triggerPrice": "2461.26",
            },
        }
    ]
    executor._exchange = mock_exchange

    orders = await executor.get_open_algo_orders("ETHUSDT")
    assert len(orders) == 1
    assert orders[0]["orderId"] == "791462386857935224"
    assert orders[0]["type"] == "STOP_MARKET"
    assert float(orders[0]["stopPrice"]) == 2461.26

    # Verify fetch_open_orders called with trigger=True and type=swap
    mock_exchange.fetch_open_orders.assert_called_once()
    call_args = mock_exchange.fetch_open_orders.call_args
    assert call_args[1]["params"] == {"type": "swap", "trigger": True}


@pytest.mark.asyncio
async def test_ccxt_cancel_algo_order_parameters():
    """
    Verifies that cancel_order passes exchange-specific trigger flags for WEEX, OKX, Bitget.
    """
    for exch, expected_params in [
        ("weex", {"type": "swap", "trigger": True}),
        ("okx", {"trigger": True}),
        ("bitget", {"productType": "usdt-futures", "stop": True, "trigger": True}),
    ]:
        executor = CcxtExecutor(
            exchange_id=exch,
            api_key="k",
            api_secret="s",
            market_type="futures_usdtm",
            password="p",
        )
        mock_exchange = AsyncMock()
        executor._exchange = mock_exchange

        await executor.cancel_order("ETHUSDT", orderId=12345, is_algo_order=True)
        mock_exchange.cancel_order.assert_called_once()
        _, _, params = mock_exchange.cancel_order.call_args[0]
        for k, v in expected_params.items():
            assert params.get(k) == v, f"{exch} expected {k}={v} in params, got {params}"


@pytest.mark.asyncio
async def test_build_adopted_position_adopts_sl_and_cancels_duplicates(make_controller):
    """
    Verifies that _build_adopted_position:
    1. Fetches both regular and algo orders.
    2. Adopts the SL closest to current position quantity.
    3. Cancels any redundant duplicate SL orders on exchange.
    4. Adopts existing DCA and TP orders.
    """
    controller = make_controller(user_id=186, api_key_id=10, api_key_name="WEEX")
    live_executor = controller.executors["live"]

    # Regular orders: 1 Take Profit, 1 DCA Limit
    live_executor.get_open_orders.return_value = [
        {
            "orderId": "tp_1",
            "clientOrderId": "x-ptp-111",
            "type": "LIMIT",
            "side": "SELL",
            "price": 2550.0,
            "origQty": 0.006,
            "reduceOnly": True,
        },
        {
            "orderId": "dca_1",
            "clientOrderId": "x-scalein-222",
            "type": "LIMIT",
            "side": "BUY",
            "price": 2450.0,
            "origQty": 0.007,
            "reduceOnly": False,
        },
    ]

    # Algo orders: 2 Stop Losses (one matching current size 0.006, one duplicate from previous run 0.003)
    live_executor.get_open_algo_orders.return_value = [
        {
            "orderId": "sl_dup_1",
            "clientOrderId": "x-sl-dup",
            "type": "STOP_MARKET",
            "side": "SELL",
            "stopPrice": 2460.0,
            "origQty": 0.003,
            "is_algo_order": True,
        },
        {
            "orderId": "sl_primary",
            "clientOrderId": "x-sl-primary",
            "type": "STOP_MARKET",
            "side": "SELL",
            "stopPrice": 2461.26,
            "origQty": 0.006,
            "is_algo_order": True,
        },
    ]

    adopted = await controller._build_adopted_position(
        symbol="ETHUSDT",
        exch_data={"positionAmt": "0.006", "entryPrice": "2500.0"},
        market_type="futures_usdtm",
        executor=live_executor,
    )

    # 1. Primary SL adopted
    assert adopted.current_sl_order_id == "sl_primary"
    assert adopted.current_sl_client_order_id == "x-sl-primary"
    assert adopted.current_sl_price == 2461.26
    assert adopted.is_sl_algo_order is True

    # 2. Duplicate SL was cancelled
    live_executor.cancel_order.assert_called_once_with(
        "ETHUSDT",
        orderId="sl_dup_1",
        origClientOrderId="x-sl-dup",
        is_algo_order=True,
    )

    # 3. TP adopted
    assert len(adopted.partial_tp_orders) == 1
    assert adopted.partial_tp_orders[0].order_id == "tp_1"
    assert adopted.partial_tp_orders[0].target_price == 2550.0

    # 4. DCA adopted
    assert len(adopted.dca_orders) == 1
    assert adopted.dca_orders[0].order_id == "dca_1"
    assert "dca_1" in adopted.dca_order_ids
    assert adopted.dca_grid_init_triggered is True


@pytest.mark.asyncio
async def test_execute_dca_grid_aborts_for_adopted_position(make_controller):
    """
    Verifies that _execute_dca_grid immediately exits for adopted positions,
    preventing duplicate DCA orders and inadvertent taker fills.
    """
    controller = make_controller(user_id=186, api_key_id=10, api_key_name="WEEX")
    live_executor = controller.executors["live"]

    pos = LivePosition(
        symbol="ETHUSDT",
        direction=SignalDirection.LONG,
        entry_price=2497.52,
        initial_quantity=0.006,
        remaining_quantity=0.006,
        entry_time=12345.0,
        strategy="VisualBuilderStrategy",
        status="OPEN",
        user_id=186,
        mode="live",
        market_type="futures_usdtm",
        api_key_id=10,
        is_adopted=True,
        dca_order_ids=["weex-dca-1"],
    )
    controller._active_position_set(pos)

    dca_params = {
        "max_safety_orders": 3,
        "volume_multiplier": 1.3,
        "step_type": "percentage",
        "step_value": 0.3,
    }
    pair_info = {"last_price": 2490.0}

    await controller._execute_dca_grid(pos, dca_params, pair_info)

    # Ensure no orders were placed!
    live_executor.place_order.assert_not_called()
    assert pos.dca_grid_init_in_progress is False


@pytest.mark.asyncio
async def test_redis_runtime_state_legacy_key_ignores_mismatched_api_key(make_controller):
    """
    Verifies that when loading runtime state from legacy key, positions and strategies
    with non-matching or missing api_key_id are NOT restored.
    """
    redis = MockRedis()
    ctrl_weex = make_controller(user_id=186, api_key_id=10, api_key_name="WEEX")
    ctrl_weex.redis_client = redis

    # Populate legacy key with a strategy belonging to OKX (api_key_id=20) and an unkeyed position
    legacy_payload = {
        "serialization_format": "json",
        "timestamp": 1788700000.0,
        "active_positions": {
            "futures_usdtm:BTCUSDT": {
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "entry_price": 65000.0,
                "initial_quantity": 0.1,
                "remaining_quantity": 0.1,
                "entry_time": 1788700000.0,
                "strategy": "OKXStrategy",
                "status": "OPEN",
                "api_key_id": 20,  # OKX
            }
        },
        "running_strategies": [
            {
                "user_id": 186,
                "id": "okx_strat:inst1",
                "config_id": "okx_strat",
                "mode": "live",
                "symbol_selection_mode": "STATIC",
                "symbols": ["BTCUSDT"],
                "name": "OKXStrategy",
                "api_key_id": 20,  # Belongs to OKX
                "config_data": {"strategy_name": "VisualBuilderStrategy"},
            },
            {
                "user_id": 186,
                "id": "legacy_strat_no_key:inst2",
                "config_id": "no_key_strat",
                "mode": "live",
                "symbol_selection_mode": "STATIC",
                "symbols": ["ETHUSDT"],
                "name": "NoKeyStrategy",
                # api_key_id is None
                "config_data": {"strategy_name": "VisualBuilderStrategy"},
            },
        ],
    }
    await redis.set("depthsight:controller:runtime_state:186", json.dumps(legacy_payload))

    await ctrl_weex._load_runtime_state()

    # WEEX controller (api_key_id=10) should NOT restore either strategy
    assert len(ctrl_weex.running_strategy_instances) == 0
    # And should NOT restore the BTCUSDT position
    assert len(ctrl_weex._active_positions) == 0


@pytest.mark.asyncio
async def test_build_adopted_position_matches_db_strategy_config(make_controller):
    """
    Verifies that _build_adopted_position successfully queries DB StrategyConfigs
    and normalizes symbols (e.g. 'ETHUSDT' matching 'ETH/USDT').
    """
    ctrl = make_controller(user_id=186, api_key_id=20, api_key_name="OKX")

    mock_config = MagicMock()
    mock_config.id = "strat-okx-123"
    mock_config.name = "OKX Momentum Scalper"
    mock_config.symbols = ["ETH/USDT"]
    mock_config.symbol_selection_mode = "STATIC"
    mock_config.config_data = {"api_key_id": 20}

    async def mock_db_session():
        yield MagicMock()

    ctrl.get_db_session = mock_db_session

    from unittest.mock import patch
    with patch("api.crud.get_strategy_configs_by_user", AsyncMock(return_value=[mock_config])):
        adopted = await ctrl._build_adopted_position(
            symbol="ETHUSDT",
            exch_data={"positionAmt": "0.5", "entryPrice": "2600.0"},
            market_type="futures_usdtm",
            executor=ctrl.executors["live"],
        )

    assert adopted is not None
    assert adopted.config_id == "strat-okx-123"
    assert adopted.strategy == "OKX Momentum Scalper"
    assert adopted.is_adopted is True
    assert adopted.api_key_id == 20


@pytest.mark.asyncio
async def test_build_adopted_position_adopts_dca_grid_orders(make_controller):
    """
    Verifies that _build_adopted_position adopts DCA limit orders even when
    ccxt_executor returns 'stopPrice': '0', and correctly parses the limit price.
    Also tests broker-tagged clientOrderIds and multiple DCA orders.
    """
    ctrl = make_controller(user_id=186, api_key_id=20, api_key_name="OKX")

    # Mock open orders on exchange: 2 DCA grid orders (BUY below entry 2500) and 1 SL order
    mock_orders = [
        {
            "orderId": "dca-ord-1",
            "clientOrderId": "bb39c7c267cfBCDExscalein01",
            "type": "LIMIT",
            "side": "BUY",
            "price": "2480.0",
            "stopPrice": "0",  # Triggers Python string '0' truthiness bug if not handled
            "origQty": "0.005",
            "status": "NEW",
        },
        {
            "orderId": "dca-ord-2",
            "clientOrderId": "bb39c7c267cfBCDExscalein02",
            "type": "LIMIT",
            "side": "BUY",
            "price": "2460.0",
            "stopPrice": "0",
            "origQty": "0.008",
            "status": "NEW",
        },
        {
            "orderId": "sl-ord-1",
            "clientOrderId": "bb39c7c267cfBCDExsl01",
            "type": "STOP_MARKET",
            "side": "SELL",
            "price": "0",
            "stopPrice": "2430.0",
            "origQty": "0.005",
            "status": "NEW",
        },
        {
            "orderId": "tp-ord-1",
            "clientOrderId": "bb39c7c267cfBCDExptp01",
            "type": "LIMIT",
            "side": "SELL",
            "price": "2550.0",
            "stopPrice": "0",
            "origQty": "0.005",
            "status": "NEW",
        },
    ]

    ctrl.executors["live"].get_open_orders = AsyncMock(return_value=mock_orders)

    adopted = await ctrl._build_adopted_position(
        symbol="ETHUSDT",
        exch_data={"positionAmt": "0.005", "entryPrice": "2500.0"},
        market_type="futures_usdtm",
        executor=ctrl.executors["live"],
    )

    assert adopted is not None
    # 1. Verify SL adopted
    assert adopted.current_sl_order_id == "sl-ord-1"
    assert adopted.current_sl_price == 2430.0

    # 2. Verify TP adopted with REAL price (not 0.0)
    assert len(adopted.partial_tp_orders) == 1
    assert adopted.partial_tp_orders[0].target_price == 2550.0
    assert adopted.initial_take_profit == 2550.0

    # 3. Verify DCA orders adopted with REAL prices (not 0.0)
    assert len(adopted.dca_orders) == 2
    assert adopted.dca_orders[0].target_price == 2480.0
    assert adopted.dca_orders[0].order_id == "dca-ord-1"
    assert adopted.dca_orders[1].target_price == 2460.0
    assert adopted.dca_orders[1].order_id == "dca-ord-2"
    assert "dca-ord-1" in adopted.dca_order_ids
    assert "dca-ord-2" in adopted.dca_order_ids
    assert adopted.dca_grid_init_triggered is True
    assert adopted.dca_active_sos == 2


@pytest.mark.asyncio
async def test_build_adopted_position_adopts_short_dca_orders(make_controller):
    """
    Verifies that for SHORT positions, DCA orders (SELL above entry) are correctly adopted.
    """
    ctrl = make_controller(user_id=186, api_key_id=10, api_key_name="WEEX")

    mock_orders = [
        {
            "orderId": "weex-dca-1",
            "clientOrderId": "b-broker-x-scalein-short1",
            "type": "LIMIT",
            "side": "SELL",
            "price": "2550.0",
            "stopPrice": "0",
            "origQty": "0.01",
            "status": "NEW",
        }
    ]
    ctrl.executors["live"].get_open_orders = AsyncMock(return_value=mock_orders)

    adopted = await ctrl._build_adopted_position(
        symbol="ETHUSDT",
        exch_data={"positionAmt": "-0.01", "entryPrice": "2500.0"},
        market_type="futures_usdtm",
        executor=ctrl.executors["live"],
    )

    assert adopted is not None
    assert adopted.direction == SignalDirection.SHORT
    assert len(adopted.dca_orders) == 1
    assert adopted.dca_orders[0].target_price == 2550.0
    assert "weex-dca-1" in adopted.dca_order_ids


@pytest.mark.asyncio
async def test_position_close_stops_auto_started_strategy(make_controller):
    """
    Verifies that when an adopted position closes, its auto_started_strategy_id
    is passed to _handle_stop_strategy_command so it doesn't keep running.
    """
    ctrl = make_controller(user_id=186, api_key_id=10, api_key_name="WEEX")

    # Mock _handle_stop_strategy_command
    ctrl._handle_stop_strategy_command = AsyncMock()
    ctrl._publish_state_to_redis = AsyncMock()
    ctrl.rm.update_trade_result = AsyncMock()

    # Create an adopted position with auto_started_strategy_id
    pos = LivePosition(
        symbol="ETHUSDT",
        direction=SignalDirection.LONG,
        entry_price=2500.0,
        initial_quantity=0.01,
        remaining_quantity=0.01,
        entry_time=1788700000.0,
        strategy="New Strategy",
        status="OPEN",
        user_id=186,
        api_key_id=10,
        is_adopted=True,
        auto_started_strategy_id="NewStrategyConfig:inst999",
    )
    ctrl._active_position_set(pos)

    # Process position close via final exit
    await ctrl._handle_final_exit(
        symbol="ETHUSDT",
        reason="TAKE_PROFIT",
        exit_price=2550.0,
        commission=0.01,
        commission_asset="USDT",
        order_id=999,
        client_order_id="close-ord-1",
    )

    # Allow spawned tasks to run
    await asyncio.sleep(0.1)

    # Verify stop strategy command was invoked for the auto-started strategy
    ctrl._handle_stop_strategy_command.assert_awaited()
    call_args = ctrl._handle_stop_strategy_command.call_args[0][0]
    assert call_args["strategy_id"] == "NewStrategyConfig:inst999"
    assert call_args["user_id"] == 186


@pytest.mark.asyncio
async def test_final_exit_cancels_stop_loss_with_algo_flag(make_controller):
    """
    Verifies that when a strategy triggers _handle_final_exit, any active Stop Loss
    is cancelled with is_algo_order=True, and cancel_all_open_orders is also called.
    """
    ctrl = make_controller(user_id=186, api_key_id=10, api_key_name="OKX")
    ctrl._publish_state_to_redis = AsyncMock()
    ctrl.rm.update_trade_result = AsyncMock()

    mock_executor = ctrl.executors["live"]
    mock_executor.cancel_order = AsyncMock(return_value={"status": "cancelled"})
    mock_executor.cancel_all_open_orders = AsyncMock(return_value={"status": "success"})
    mock_executor.supports_positions = True

    # Create a position with an active Stop Loss
    pos = LivePosition(
        symbol="ETHUSDT",
        direction=SignalDirection.LONG,
        entry_price=2500.0,
        initial_quantity=0.01,
        remaining_quantity=0.01,
        entry_time=1788700000.0,
        strategy="TestStrategy",
        status="OPEN",
        user_id=186,
        api_key_id=10,
        market_type="futures_usdtm",
        current_sl_order_id="algo-sl-987654",
        current_sl_client_order_id="x-sl-client-123",
        is_sl_algo_order=False,  # e.g., was not set during adoption
    )
    ctrl._active_position_set(pos)

    # Trigger final exit by Take Profit
    await ctrl._handle_final_exit(
        symbol="ETHUSDT",
        reason="TAKE_PROFIT",
        exit_price=2600.0,
        commission=0.01,
        commission_asset="USDT",
        order_id=55555,  # The TP order ID
        client_order_id="tp-ord-55555",
        market_type="futures_usdtm",
    )

    # 1. Verify cancel_order was called for the Stop Loss with is_algo_order=True
    mock_executor.cancel_order.assert_awaited()
    cancel_calls = mock_executor.cancel_order.await_args_list
    sl_cancels = [
        call for call in cancel_calls
        if str(call.kwargs.get("orderId")) == "algo-sl-987654"
    ]
    assert len(sl_cancels) == 1
    assert sl_cancels[0].kwargs.get("is_algo_order") is True
    assert sl_cancels[0].kwargs.get("symbol") == "ETHUSDT"

    # 2. Verify Hard Reset cancel_all_open_orders was also called
    mock_executor.cancel_all_open_orders.assert_awaited_with("ETHUSDT")


@pytest.mark.asyncio
async def test_cancel_all_exit_orders_cancels_sl_and_ptp(make_controller):
    """
    Verifies that _cancel_all_exit_orders cancels both SL and pending partial TPs,
    setting is_algo_order=True on futures.
    """
    ctrl = make_controller(user_id=186, api_key_id=10, api_key_name="OKX")
    mock_executor = ctrl.executors["live"]
    mock_executor.cancel_order = AsyncMock(return_value={"status": "cancelled"})
    mock_executor.supports_positions = True

    pos = LivePosition(
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        entry_price=60000.0,
        initial_quantity=0.1,
        remaining_quantity=0.1,
        entry_time=1788700000.0,
        strategy="TestStrategy",
        status="OPEN",
        user_id=186,
        api_key_id=10,
        market_type="futures_usdtm",
        current_sl_order_id="sl-1111",
        current_sl_client_order_id="cli-sl-1111",
        is_sl_algo_order=True,
    )
    pos.partial_tp_orders = [
        PartialTpOrderInfo(target_price=61000.0, orig_fraction=0.5, quantity=0.05, order_id=2222, status="PENDING")
    ]
    ctrl._active_position_set(pos)

    await ctrl._cancel_all_exit_orders("BTCUSDT", "MANUAL_CLOSE", market_type="futures_usdtm")

    assert mock_executor.cancel_order.await_count == 2
    calls = mock_executor.cancel_order.await_args_list
    # Find SL cancel
    sl_call = next(c for c in calls if str(c.kwargs.get("orderId")) == "sl-1111")
    assert sl_call.kwargs.get("is_algo_order") is True
    # Find TP cancel
    tp_call = next(c for c in calls if str(c.kwargs.get("orderId")) == "2222")
    assert tp_call.kwargs.get("is_algo_order") is False


@pytest.mark.asyncio
async def test_ccxt_okx_cancel_all_open_orders_queries_and_cancels_algos():
    """
    Verifies that on OKX, cancel_all_open_orders cancels regular orders and also
    fetches open algo orders (stop=True, ordType=conditional) and cancels each with stop=True.
    """
    executor = CcxtExecutor(
        exchange_id="okx",
        api_key="k",
        api_secret="s",
        market_type="futures_usdtm",
        password="p",
    )
    mock_exchange = AsyncMock()
    # Mock regular cancel_all_orders failing or completing
    mock_exchange.cancel_all_orders.return_value = [{"id": "reg-1"}]
    # Mock privatePostTradeCancelAlgos for algo cancel
    mock_exchange.privatePostTradeCancelAlgos = AsyncMock(return_value={"code": "0"})
    mock_exchange.privatePostTradeCancelOrder = AsyncMock(return_value={"code": "0"})
    mock_exchange.cancel_order = AsyncMock(return_value={"code": "0"})
    mock_exchange.fetch_open_orders = AsyncMock(side_effect=[
        # Call 1: stop=True trigger orders
        [{"id": "okx-algo-1", "symbol": "ETH/USDT:USDT", "type": "market", "info": {"algoId": "okx-algo-1"}}],
        # Call 2: ordType=conditional
        [{"id": "okx-algo-2", "symbol": "ETH/USDT:USDT", "type": "market", "info": {"algoId": "okx-algo-2"}}],
        # Call 3: ordType=oco
        [],
    ])
    executor._exchange = mock_exchange

    res = await executor.cancel_all_open_orders("ETHUSDT")
    assert res.get("status") in ["OK", "success"]
    # Verify fetch_open_orders was called to find open algo orders
    assert mock_exchange.fetch_open_orders.call_count >= 2
    # Verify cancel_order was called for each algo order
    assert mock_exchange.cancel_order.call_count == 2
    for call in mock_exchange.cancel_order.call_args_list:
        params = call[0][2] if len(call[0]) > 2 else call[1].get("params", {})
        assert params.get("stop") is True
        assert params.get("trigger") is True


@pytest.mark.asyncio
async def test_ccxt_weex_cancel_all_open_orders_cancels_swap_trigger_orders():
    """
    Verifies that on WEEX, cancel_all_open_orders calls cancel_all_orders with
    params={'type': 'swap', 'trigger': True} to remove hanging trigger stops.
    """
    executor = CcxtExecutor(
        exchange_id="weex",
        api_key="k",
        api_secret="s",
        market_type="futures_usdtm",
        password="p",
    )
    mock_exchange = AsyncMock()
    mock_exchange.cancel_all_orders.return_value = [{"id": "weex-1"}]
    executor._exchange = mock_exchange

    res = await executor.cancel_all_open_orders("ETHUSDT")
    assert res.get("status") in ["OK", "success"]
    # Verify cancel_all_orders was called twice: regular swap and trigger swap
    assert mock_exchange.cancel_all_orders.call_count == 2
    calls = mock_exchange.cancel_all_orders.call_args_list
    assert calls[0][1]["params"] == {"type": "swap"}
    assert calls[1][1]["params"] == {"type": "swap", "trigger": True}


def test_client_order_ids_match_distinguishes_broker_prefixed_orders():
    """
    Verifies that _client_order_ids_match does NOT produce false positives
    between entry, take-profit, and stop-loss orders sharing common broker prefixes.
    """
    # WEEX broker prefix
    entry_weex = "b-WEEX111159-x-entry-64b6e140747"
    tp_weex = "b-WEEX111159-x-ptp-ff137e06e32e4"
    sl_weex = "b-WEEX111159-x-sl-20d75d38d5b04c"

    assert TradingController._client_order_ids_match(entry_weex, tp_weex) is False
    assert TradingController._client_order_ids_match(entry_weex, sl_weex) is False
    assert TradingController._client_order_ids_match(tp_weex, sl_weex) is False

    # OKX broker prefix
    entry_okx = "bb39c7c267cfBCDExentry64b6e140747"
    tp_okx = "bb39c7c267cfBCDExptpff137e06e32e4"
    sl_okx = "bb39c7c267cfBCDExsl20d75d38d5b04c"

    assert TradingController._client_order_ids_match(entry_okx, tp_okx) is False
    assert TradingController._client_order_ids_match(entry_okx, sl_okx) is False
    assert TradingController._client_order_ids_match(tp_okx, sl_okx) is False

    # True matches across internal and broker-prefixed versions
    assert TradingController._client_order_ids_match("x-entry-64b6e140747", entry_weex) is True
    assert TradingController._client_order_ids_match("x-ptp-ff137e06e32e4", tp_weex) is True
    assert TradingController._client_order_ids_match("x-entry-64b6e140747", entry_okx) is True


@pytest.mark.asyncio
async def test_reconcile_positions_calls_handle_final_exit_when_closed_on_exchange(make_controller):
    """
    Verifies that when a position is closed on the exchange (e.g. by exchange TP/SL),
    _reconcile_positions_with_exchange calls _handle_final_exit so the trade is saved to DB.
    """
    ctrl = make_controller(user_id=186, api_key_id=10, api_key_name="WEEX")
    ctrl._handle_final_exit = AsyncMock()

    mock_executor = ctrl.executors["live"]
    mock_executor.market_type = "futures_usdtm"
    mock_executor.get_open_positions = AsyncMock(return_value=[])  # 0 open positions on exchange
    mock_executor.get_ticker_price = AsyncMock(return_value={"price": "2514.14"})

    # Internal position exists
    pos = LivePosition(
        symbol="ETHUSDT",
        direction=SignalDirection.LONG,
        entry_price=2506.31,
        initial_quantity=0.003,
        remaining_quantity=0.003,
        entry_time=1788735128.0,
        strategy="VisualBuilderStrategy",
        status="OPEN",
        user_id=186,
        api_key_id=10,
        market_type="futures_usdtm",
    )
    ctrl._active_position_set(pos)

    await ctrl._reconcile_positions_with_exchange()

    # Verify _handle_final_exit was called with exit price
    ctrl._handle_final_exit.assert_awaited_once()
    kwargs = ctrl._handle_final_exit.call_args.kwargs
    assert kwargs["symbol"] == "ETHUSDT"
    assert kwargs["reason"] == "CLOSED_ON_EXCHANGE"
    assert kwargs["exit_price"] == 2514.14




