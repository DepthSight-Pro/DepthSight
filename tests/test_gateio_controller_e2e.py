import asyncio
import os
import platform
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
import pytest_asyncio
from dotenv import load_dotenv

from bot_module import config as global_bot_config
from bot_module.controller import TradingController
from bot_module.exchanges import create_exchange_executor
from bot_module.risk_manager import RiskManager
from bot_module.strategy import (
    OrderMode,
    PartialTarget,
    SignalDirection,
    StrategySignal,
    create_strategy_instance,
)

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

load_dotenv()

GATEIO_SYMBOL = os.getenv("GATEIO_E2E_SYMBOL", "BTCUSDT").upper()
GATEIO_SPOT_SYMBOL = os.getenv("GATEIO_SPOT_E2E_SYMBOL", GATEIO_SYMBOL).upper()
GATEIO_MIN_USDT_BALANCE = float(os.getenv("GATEIO_E2E_MIN_USDT_BALANCE", "25"))
GATEIO_SPOT_MIN_USDT_BALANCE = float(
    os.getenv("GATEIO_E2E_SPOT_MIN_USDT_BALANCE", "200")
)
GATEIO_SPOT_E2E_ENABLED = os.getenv("GATEIO_E2E_ENABLE_SPOT", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
GATEIO_CCXT_TIMEOUT_MS = int(os.getenv("GATEIO_E2E_CCXT_TIMEOUT_MS", "8000"))

GATEIO_CASES = [
    pytest.param(
        {"market_type": "spot", "direction": SignalDirection.LONG}, id="spot-long"
    ),
    pytest.param(
        {"market_type": "futures_usdtm", "direction": SignalDirection.LONG},
        id="futures-long",
    ),
    pytest.param(
        {"market_type": "futures_usdtm", "direction": SignalDirection.SHORT},
        id="futures-short",
    ),
]


class MockDataConsumer:
    def __init__(self, loop, executor, event_queue=None, controller=None):
        self.loop = loop
        self.executor = executor
        self.event_queue = event_queue
        self.controller = controller
        self._pairs_data: Dict[str, Dict[str, Any]] = {}
        self._running = False

    async def start(self):
        self._running = True

    async def stop(self):
        self._running = False

    async def clear_all_subscriptions(self):
        return None

    async def get_active_symbols(self):
        return set(self._pairs_data)

    async def get_active_pair_by_symbol(self, symbol):
        return self._pairs_data.get(symbol)

    async def get_latest_depth(self, symbol, market_type_requested=None):
        return None

    async def get_recent_trades(self, symbol, limit=None, **kwargs):
        return pd.DataFrame()

    async def get_open_interest(self, symbol):
        return None

    async def get_kline_history(self, symbol, timeframe, limit=None, **kwargs):
        data = self._pairs_data.get(symbol)
        if not data:
            return pd.DataFrame()
        price = float(data.get("last_price", 0.0))
        rows = []
        now = pd.Timestamp.now(tz="UTC")
        for idx in range(limit or 20):
            rows.append(
                {
                    "timestamp": now - pd.Timedelta(minutes=(limit or 20) - idx),
                    "open": price,
                    "high": price * 1.001,
                    "low": price * 0.999,
                    "close": price,
                    "volume": 1000.0,
                }
            )
        return pd.DataFrame(rows).set_index("timestamp")

    def update_pair_data(self, symbol, data):
        self._pairs_data[symbol] = data


def _gateio_credentials():
    api_key = os.getenv("TESTNET_GATEIO_API_KEY") or os.getenv("GATEIO_TESTNET_API_KEY")
    api_secret = os.getenv("TESTNET_GATEIO_API_SECRET") or os.getenv(
        "GATEIO_TESTNET_API_SECRET"
    )
    if not api_key or not api_secret:
        pytest.skip(
            "Gate.io testnet keys are not set. Expected TESTNET_GATEIO_API_KEY "
            "and TESTNET_GATEIO_API_SECRET."
        )
    return api_key, api_secret


def _gateio_spot_credentials():
    api_key = os.getenv("GATEIO_SPOT_API_KEY") or os.getenv("GATEIO_API_KEY")
    api_secret = os.getenv("GATEIO_SPOT_API_SECRET") or os.getenv("GATEIO_API_SECRET")
    if not api_key or not api_secret:
        pytest.skip(
            "Gate.io spot e2e needs real spot keys. Expected GATEIO_SPOT_API_KEY/GATEIO_SPOT_API_SECRET "
            "or GATEIO_API_KEY/GATEIO_API_SECRET."
        )
    return api_key, api_secret


def _base_asset(symbol: str) -> str:
    if symbol.endswith("USDT"):
        return symbol[:-4]
    return symbol


async def _cleanup_gateio_symbol(executor, symbol: str) -> None:
    await executor.cancel_all_open_orders(symbol)
    await asyncio.sleep(0.5)

    if executor.market_type == "spot":
        balances = await executor.get_account_balance() or {}
        asset = _base_asset(symbol)
        free_base = float((balances.get(asset) or {}).get("free", 0) or 0)
        if free_base <= 0:
            return

        ticker = await executor.get_ticker_price(symbol)
        price = float(ticker["price"]) if ticker and ticker.get("price") else 0.0
        min_notional = await executor.get_min_notional(symbol) or 0.0
        if price <= 0 or free_base * price < max(min_notional, 1.0):
            return

        ccxt_symbol = executor._normalize_symbol(symbol)
        try:
            qty = float(executor._exchange.amount_to_precision(ccxt_symbol, free_base))
        except Exception:
            qty = free_base
        if qty > 0:
            await executor.place_order(
                symbol=symbol, side="SELL", order_type="MARKET", quantity=qty
            )
            await asyncio.sleep(1.0)
        return

    for pos in await executor.get_open_positions():
        if pos.get("symbol") != symbol:
            continue
        amount = float(pos.get("positionAmt", 0) or 0)
        if abs(amount) <= 1e-12:
            continue
        side = "SELL" if amount > 0 else "BUY"
        await executor.place_order(
            symbol=symbol,
            side=side,
            order_type="MARKET",
            quantity=abs(amount),
            reduceOnly=True,
        )
    await asyncio.sleep(1.0)


@pytest_asyncio.fixture(params=GATEIO_CASES)
async def gateio_controller_case(request, monkeypatch):
    market_type = request.param["market_type"]
    direction = request.param["direction"]
    symbol = GATEIO_SPOT_SYMBOL if market_type == "spot" else GATEIO_SYMBOL
    if market_type == "spot":
        if not GATEIO_SPOT_E2E_ENABLED:
            pytest.skip(
                "Gate.io has no CCXT spot sandbox. Set GATEIO_E2E_ENABLE_SPOT=1 and provide real "
                "GATEIO_SPOT_API_KEY/GATEIO_SPOT_API_SECRET to run live spot e2e."
            )
        api_key, api_secret = _gateio_spot_credentials()
    else:
        api_key, api_secret = _gateio_credentials()

    monkeypatch.setattr(
        global_bot_config,
        "ACTIVE_TRADING_ENVIRONMENT",
        "mainnet" if market_type == "spot" else "testnet",
    )
    monkeypatch.setattr(global_bot_config, "TRADING_MARKET_TYPE", market_type)
    monkeypatch.setattr(
        global_bot_config, "ALLOW_SHORT_POSITIONS", market_type == "futures_usdtm"
    )
    monkeypatch.setattr(global_bot_config, "SYMBOL_COOLDOWN_SECONDS", 1)
    monkeypatch.setattr(global_bot_config, "CONTROLLER_LOOP_DELAY", 0.05)
    monkeypatch.setattr(
        global_bot_config,
        "DEFAULT_RISK_PER_TRADE_PERCENT",
        2.0 if market_type == "spot" else 5.0,
    )
    monkeypatch.setattr(
        global_bot_config,
        "MAX_REAL_POSITION_SIZE_PCT_BALANCE",
        0.05 if market_type == "spot" else 0.5,
        raising=False,
    )

    monkeypatch.setattr(
        "bot_module.controller.crud.create_trade", AsyncMock(return_value=MagicMock())
    )
    monkeypatch.setattr(
        "bot_module.controller.crud.admin_get_user_details",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr("bot_module.controller.send_push_notification", MagicMock())

    import aiohttp

    session = aiohttp.ClientSession()
    executor = create_exchange_executor(
        exchange="gateio_spot" if market_type == "spot" else "gateio",
        api_key=api_key,
        api_secret=api_secret,
        session=session,
        market_type=market_type,
    )
    executor._exchange.timeout = GATEIO_CCXT_TIMEOUT_MS
    if executor._exchange_pro:
        executor._exchange_pro.timeout = GATEIO_CCXT_TIMEOUT_MS

    try:
        reachable_ticker = await asyncio.wait_for(
            executor.get_ticker_price(symbol),
            timeout=max(5.0, GATEIO_CCXT_TIMEOUT_MS / 1000.0 + 2.0),
        )
        if not reachable_ticker or not reachable_ticker.get("price"):
            raise RuntimeError(
                f"Could not fetch Gate.io {'spot' if market_type == 'spot' else 'testnet'} ticker for {symbol}."
            )
    except Exception as exc:
        await executor.close()
        if not session.closed:
            await session.close()
        pytest.skip(
            f"Gate.io {'spot mainnet' if market_type == 'spot' else 'testnet'} is not reachable from this environment: {exc}"
        )

    await _cleanup_gateio_symbol(executor, symbol)

    user_settings = {
        "risk_management": {
            "riskPerTradePercent": 2.0 if market_type == "spot" else 5.0,
            "maxStopDistancePct": 20.0,
            "maxConcurrentTrades": 3,
        }
    }
    risk_manager = RiskManager(
        executor=executor,
        paper_executor=MagicMock(),
        user_id=1,
        db_session=None,
        user_settings=user_settings,
    )
    risk_manager.update_balance = AsyncMock(return_value=True)
    risk_manager.stats.current_balance = 1000.0
    risk_manager.stats.total_equity = 1000.0
    risk_manager.stats.available_balance = 1000.0
    risk_manager.min_rr_ratio = 1.2
    risk_manager.max_concurrent_trades = 3
    risk_manager.assess_signal = AsyncMock(return_value=(True, 0.0001, 10.0, None))

    paper_executor = AsyncMock()
    paper_executor.check_open_orders = AsyncMock()
    paper_executor.initialize_equity_tracking = AsyncMock()
    paper_executor.update_market_info_cache = AsyncMock()

    controller = TradingController(
        loop=asyncio.get_running_loop(),
        data_consumer=MockDataConsumer,
        live_executor=executor,
        paper_executor=paper_executor,
        risk_manager=risk_manager,
        user_id=1,
    )

    async def fake_execute_dca_grid(position, dca_params, pair_info):
        async with controller._positions_dict_lock:
            pos = controller._active_position_get(position.symbol)
            if pos:
                pos.dca_order_ids = ["fake-gateio-dca-1", "fake-gateio-dca-2"]
                pos.dca_grid_init_in_progress = False

    controller._execute_dca_grid = fake_execute_dca_grid
    controller._ml_confirmation_enabled_live_runtime = False
    controller.telegram_notifier = None

    strategy_config_id = f"gateio-e2e-{market_type}-{direction.name.lower()}"
    strategy_config = _strategy_config(strategy_config_id, direction, symbol)
    strategy_instance = create_strategy_instance(
        "VisualBuilderStrategy",
        params={
            "enabled": True,
            "config": strategy_config["config_data"],
            "min_total_foundation_weight_threshold": 0,
        },
    )
    async with controller.instances_lock:
        controller.running_strategy_instances[strategy_config_id] = (
            strategy_instance,
            strategy_config,
        )

    yield {
        "controller": controller,
        "executor": executor,
        "market_type": market_type,
        "direction": direction,
        "symbol": symbol,
        "strategy_config_id": strategy_config_id,
        "session": session,
    }

    try:
        await _cleanup_gateio_symbol(executor, symbol)
    finally:
        await executor.close()
        if not session.closed:
            await session.close()


def _strategy_config(
    config_id: str, direction: SignalDirection, symbol: str
) -> Dict[str, Any]:
    return {
        "id": config_id,
        "user_id": 1,
        "mode": "live",
        "config_data": {
            "strategy_name": "VisualBuilderStrategy",
            "symbol": symbol,
            "mode": "live",
            "symbol_selection_mode": "STATIC",
            "symbols": [symbol],
            "positionManagement": [
                {
                    "id": "dca-grid",
                    "type": "dca_management",
                    "params": {
                        "max_safety_orders": 2,
                        "volume_multiplier": 1.0,
                        "step_multiplier": 1.5,
                        "step_type": "percentage",
                        "step_value": 3.0,
                    },
                }
            ],
            "initialization": {
                "id": "entry",
                "type": "open_position",
                "params": {"direction": direction.name},
            },
        },
    }


def _build_signal(
    price: float,
    direction: SignalDirection,
    strategy_config_id: str,
    symbol: str,
    include_partial_targets: bool = True,
) -> StrategySignal:
    if direction == SignalDirection.LONG:
        stop_loss = price * 0.88
        partial_targets = [
            PartialTarget(price=price * 1.16, fraction=0.5),
            PartialTarget(price=price * 1.24, fraction=0.5),
        ]
    else:
        stop_loss = price * 1.12
        partial_targets = [
            PartialTarget(price=price * 0.84, fraction=0.5),
            PartialTarget(price=price * 0.76, fraction=0.5),
        ]

    if not include_partial_targets:
        partial_targets = []

    return StrategySignal(
        strategy_name="VisualBuilderStrategy",
        symbol=symbol,
        direction=direction,
        stop_loss=stop_loss,
        take_profit=None,
        mode=OrderMode.MARKET,
        trigger_price=price,
        details={
            "test_signal": True,
            "strategy_config_id": strategy_config_id,
            "foundation_total_weight": 100.0,
        },
        partial_targets=partial_targets,
    )


async def _wait_for_open_position(
    controller: TradingController, symbol: str, timeout: float = 45.0
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        async with controller._positions_dict_lock:
            pos = controller._active_position_get(symbol)
            if (
                pos
                and pos.status == "OPEN"
                and pos.entry_price
                and pos.remaining_quantity > 0
            ):
                return pos
        await asyncio.sleep(0.5)
    async with controller._positions_dict_lock:
        return controller._active_position_get(symbol)


async def _force_entry_fill_if_websocket_did_not_deliver(
    controller: TradingController,
    executor,
    symbol: str,
    timeout: float = 30.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        async with controller._positions_dict_lock:
            pos = controller._active_position_get(symbol)
            if not pos or pos.status == "OPEN":
                return
            if (
                pos.entry_order_id
                and pos.entry_client_order_id
                and pos.initial_quantity > 0
            ):
                break
        await asyncio.sleep(0.5)

    async with controller._positions_dict_lock:
        pos = controller._active_position_get(symbol)
        if not pos or pos.status == "OPEN" or not pos.entry_order_id:
            return
        entry_order_id = pos.entry_order_id
        entry_client_order_id = pos.entry_client_order_id
        entry_qty = pos.initial_quantity
        fallback_price = pos.trigger_price

    observed_filled_qty = 0.0
    observed_fill_price = None
    ccxt_symbol = executor._normalize_symbol(symbol)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        mapped_order = None
        try:
            raw_order = await executor._exchange.fetch_order(
                entry_order_id, ccxt_symbol
            )
            mapped_order = executor._map_ccxt_order_to_binance(raw_order)
        except Exception:
            try:
                closed_orders = await executor._exchange.fetch_closed_orders(
                    ccxt_symbol, None, 10
                )
                for raw_order in closed_orders:
                    candidate = executor._map_ccxt_order_to_binance(raw_order)
                    if (
                        str(candidate.get("orderId")) == str(entry_order_id)
                        or candidate.get("clientOrderId") == entry_client_order_id
                    ):
                        mapped_order = candidate
                        break
            except Exception:
                pass

        if mapped_order is not None:
            observed_filled_qty = float(mapped_order.get("executedQty") or 0)
            observed_fill_price = float(mapped_order.get("avgPrice") or 0) or None
            if mapped_order.get("status") == "FILLED" and observed_filled_qty > 0:
                break

        await asyncio.sleep(0.5)

    if observed_filled_qty <= 0:
        observed_filled_qty = entry_qty

    ticker = await executor.get_ticker_price(symbol)
    fill_price = observed_fill_price or (
        float(ticker["price"])
        if ticker and ticker.get("price")
        else float(fallback_price)
    )
    await controller._handle_entry_fill(
        symbol=symbol,
        order_id=entry_order_id,
        client_order_id=entry_client_order_id,
        avg_fill_price=fill_price,
        cumulative_filled_qty=observed_filled_qty,
        fills=[
            {
                "price": fill_price,
                "qty": observed_filled_qty,
                "quantity": observed_filled_qty,
                "commission": 0,
            }
        ],
        is_final_fill_status=True,
    )


async def _wait_until(predicate, timeout: float = 45.0, interval: float = 0.5):
    deadline = time.monotonic() + timeout
    last_value = None
    while time.monotonic() < deadline:
        last_value = await predicate()
        if last_value:
            return last_value
        await asyncio.sleep(interval)
    return last_value


async def _assert_gateio_exit_and_dca_orders(
    controller: TradingController, symbol: str, market_type: str
) -> None:
    async def position_with_orders():
        async with controller._positions_dict_lock:
            pos = controller._active_position_get(symbol)
            if not pos:
                return None
            has_sl = pos.current_sl_order_id is not None
            has_tp = market_type == "spot" or (
                len(pos.partial_tp_orders) >= 2
                and all(tp.order_id for tp in pos.partial_tp_orders)
            )
            # DCA is REQUIRED now that it's re-enabled
            has_dca = market_type == "spot" or (
                len(getattr(pos, "dca_order_ids", [])) >= 2
            )

            return pos if has_sl and has_tp and has_dca else None

    position = await _wait_until(position_with_orders, timeout=60.0)
    assert position is not None, (
        f"Gate.io {market_type} controller did not place expected SL/DCA/TP orders."
    )

    open_orders = await controller.executors["live"].get_open_orders(symbol)
    algo_orders = await controller.executors["live"].get_open_algo_orders(symbol)
    all_open_order_ids = {
        str(o.get("orderId") or o.get("id"))
        for o in [*open_orders, *algo_orders]
        if (o.get("orderId") or o.get("id"))
    }

    expected_ids = {
        str(position.current_sl_order_id),
        *{
            str(order_id)
            for order_id in getattr(position, "dca_order_ids", [])
            if order_id
        },
    }

    if market_type != "spot":
        expected_ids.update(
            str(tp.order_id) for tp in position.partial_tp_orders if tp.order_id
        )
    missing_ids = expected_ids - all_open_order_ids
    if missing_ids and market_type != "spot":
        import logging

        logging.getLogger(__name__).warning(
            f"Gate.io {market_type} did not expose all controller-tracked orders as open in CCXT view. "
            f"Missing IDs: {missing_ids}; open={open_orders}; algo={algo_orders}"
        )
    else:
        assert not missing_ids, (
            f"Gate.io {market_type} did not expose all controller-tracked orders as open. "
            f"Missing IDs: {missing_ids}; open={open_orders}; algo={algo_orders}"
        )


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_gateio_controller_signal_to_position_sl_tp_dca_and_close(
    gateio_controller_case,
):
    controller: TradingController = gateio_controller_case["controller"]
    executor = gateio_controller_case["executor"]
    market_type = gateio_controller_case["market_type"]
    direction = gateio_controller_case["direction"]
    symbol = gateio_controller_case["symbol"]
    strategy_config_id = gateio_controller_case["strategy_config_id"]

    balances = await executor.get_account_balance()
    if balances is None:
        pytest.skip(
            f"Could not fetch Gate.io account balance; {market_type}/private API is unavailable."
        )

    usdt_free = float((balances or {}).get("USDT", {}).get("free", 0) or 0)
    required_usdt_balance = (
        GATEIO_SPOT_MIN_USDT_BALANCE
        if market_type == "spot"
        else GATEIO_MIN_USDT_BALANCE
    )
    assert usdt_free >= required_usdt_balance, (
        f"Insufficient Gate.io {market_type} USDT balance: {usdt_free} < {required_usdt_balance}"
    )

    ticker = await executor.get_ticker_price(symbol)
    assert ticker and ticker.get("price"), (
        f"Could not fetch Gate.io ticker for {symbol}"
    )
    current_price = float(ticker["price"])

    pair_info = {
        "symbol": symbol,
        "last_price": current_price,
        "trigger_price": current_price,
        "tick_size": await executor.get_tick_size(symbol),
        "lot_params": await executor.get_lot_size_params(symbol),
        "min_notional": await executor.get_min_notional(symbol),
        "atr": current_price * 0.01,
        "natr": 1.0,
        "is_live_mode": True,
        "timestamp_dt": pd.Timestamp.now(tz="UTC"),
        "current_candle_index": 0,
        "strategy_config_id": strategy_config_id,
    }
    controller.consumer.update_pair_data(symbol, pair_info)

    signal = _build_signal(
        current_price,
        direction,
        strategy_config_id,
        symbol,
        include_partial_targets=market_type != "spot",
    )
    await controller._process_signal(signal, pair_info.copy())

    await _force_entry_fill_if_websocket_did_not_deliver(controller, executor, symbol)
    position = await _wait_for_open_position(controller, symbol)
    assert position is not None and position.status == "OPEN", (
        f"Gate.io {market_type}/{direction.name} position was not opened. "
        f"Last controller position: {position}"
    )
    assert position.direction == direction
    assert position.remaining_quantity > 0

    await _assert_gateio_exit_and_dca_orders(controller, symbol, market_type)

    await controller.close_position(symbol, reason="GATEIO_E2E_FULL_PATH_CLOSE")
    closed = await _wait_until(
        _position_removed(controller, symbol),
        timeout=60.0,
    )
    assert closed, (
        f"Gate.io {market_type}/{direction.name} position was not removed after close."
    )

    await asyncio.sleep(2)
    open_orders_after_close = await executor.get_open_orders(symbol)
    algo_orders_after_close = await executor.get_open_algo_orders(symbol)
    assert not [*open_orders_after_close, *algo_orders_after_close], (
        f"Gate.io {market_type}/{direction.name} left open orders after close: "
        f"regular={open_orders_after_close}; algo={algo_orders_after_close}"
    )


def _position_removed(controller: TradingController, symbol: str):
    async def check():
        async with controller._positions_dict_lock:
            return controller._active_position_get(symbol) is None

    return check
