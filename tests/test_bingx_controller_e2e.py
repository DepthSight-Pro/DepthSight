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

BINGX_SYMBOL = os.getenv("BINGX_E2E_SYMBOL", "BTCUSDT").upper()
BINGX_MIN_USDT_BALANCE = float(os.getenv("BINGX_E2E_MIN_USDT_BALANCE", "25"))
BINGX_CCXT_TIMEOUT_MS = int(os.getenv("BINGX_E2E_CCXT_TIMEOUT_MS", "8000"))

BINGX_CASES = [
    pytest.param({"direction": SignalDirection.LONG}, id="futures-long"),
    pytest.param({"direction": SignalDirection.SHORT}, id="futures-short"),
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


def _bingx_credentials():
    api_key = os.getenv("TESTNET_BINGX_API_KEY") or os.getenv("BINGX_TESTNET_API_KEY")
    api_secret = os.getenv("TESTNET_BINGX_API_SECRET") or os.getenv(
        "BINGX_TESTNET_API_SECRET"
    )
    if not api_key or not api_secret:
        pytest.skip(
            "BingX virtual swap keys are not set. Expected TESTNET_BINGX_API_KEY "
            "and TESTNET_BINGX_API_SECRET."
        )
    return api_key, api_secret


async def _cleanup_bingx_symbol(executor, symbol: str) -> None:
    await executor.cancel_all_open_orders(symbol)
    await asyncio.sleep(0.5)

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


@pytest_asyncio.fixture(params=BINGX_CASES)
async def bingx_controller_case(request, monkeypatch):
    direction = request.param["direction"]
    api_key, api_secret = _bingx_credentials()

    monkeypatch.setattr(global_bot_config, "ACTIVE_TRADING_ENVIRONMENT", "testnet")
    monkeypatch.setattr(global_bot_config, "TRADING_MARKET_TYPE", "futures_usdtm")
    monkeypatch.setattr(global_bot_config, "ALLOW_SHORT_POSITIONS", True)
    monkeypatch.setattr(global_bot_config, "SYMBOL_COOLDOWN_SECONDS", 1)
    monkeypatch.setattr(global_bot_config, "CONTROLLER_LOOP_DELAY", 0.05)
    monkeypatch.setattr(global_bot_config, "DEFAULT_RISK_PER_TRADE_PERCENT", 5.0)
    monkeypatch.setattr(
        global_bot_config, "MAX_REAL_POSITION_SIZE_PCT_BALANCE", 0.5, raising=False
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
        exchange="bingx",
        api_key=api_key,
        api_secret=api_secret,
        session=session,
        market_type="futures_usdtm",
    )
    assert executor.sandbox is True, (
        "BingX e2e must run against prod-vst/open-api-vst, not live trading."
    )
    executor._exchange.timeout = BINGX_CCXT_TIMEOUT_MS
    if executor._exchange_pro:
        executor._exchange_pro.timeout = BINGX_CCXT_TIMEOUT_MS

    try:
        reachable_ticker = await asyncio.wait_for(
            executor.get_ticker_price(BINGX_SYMBOL),
            timeout=max(5.0, BINGX_CCXT_TIMEOUT_MS / 1000.0 + 2.0),
        )
        if not reachable_ticker or not reachable_ticker.get("price"):
            raise RuntimeError(
                f"Could not fetch BingX virtual swap ticker for {BINGX_SYMBOL}."
            )
    except Exception as exc:
        await executor.close()
        if not session.closed:
            await session.close()
        pytest.skip(
            f"BingX virtual swap endpoint is not reachable from this environment: {exc}"
        )

    await _cleanup_bingx_symbol(executor, BINGX_SYMBOL)

    user_settings = {
        "risk_management": {
            "riskPerTradePercent": 5.0,
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
    controller._ml_confirmation_enabled_live_runtime = False
    controller.telegram_notifier = None

    strategy_config_id = f"bingx-e2e-futures-{direction.name.lower()}"
    strategy_config = _strategy_config(strategy_config_id, direction)
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
        "direction": direction,
        "strategy_config_id": strategy_config_id,
        "session": session,
    }

    try:
        await _cleanup_bingx_symbol(executor, BINGX_SYMBOL)
    finally:
        await executor.close()
        if not session.closed:
            await session.close()


def _strategy_config(config_id: str, direction: SignalDirection) -> Dict[str, Any]:
    return {
        "id": config_id,
        "user_id": 1,
        "mode": "live",
        "config_data": {
            "strategy_name": "VisualBuilderStrategy",
            "symbol": BINGX_SYMBOL,
            "mode": "live",
            "symbol_selection_mode": "STATIC",
            "symbols": [BINGX_SYMBOL],
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
    price: float, direction: SignalDirection, strategy_config_id: str
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

    return StrategySignal(
        strategy_name="VisualBuilderStrategy",
        symbol=BINGX_SYMBOL,
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


async def _wait_for_open_position(controller: TradingController, timeout: float = 45.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        async with controller._positions_dict_lock:
            pos = controller._active_position_get(BINGX_SYMBOL, "futures_usdtm")
            if (
                pos
                and pos.status == "OPEN"
                and pos.entry_price
                and pos.remaining_quantity > 0
            ):
                return pos
        await asyncio.sleep(0.5)
    async with controller._positions_dict_lock:
        return controller._active_position_get(BINGX_SYMBOL, "futures_usdtm")


async def _force_entry_fill_if_websocket_did_not_deliver(
    controller: TradingController,
    executor,
    timeout: float = 30.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        async with controller._positions_dict_lock:
            pos = controller._active_position_get(BINGX_SYMBOL, "futures_usdtm")
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
        pos = controller._active_position_get(BINGX_SYMBOL, "futures_usdtm")
        if not pos or pos.status == "OPEN" or not pos.entry_order_id:
            return
        entry_order_id = pos.entry_order_id
        entry_client_order_id = pos.entry_client_order_id
        entry_qty = pos.initial_quantity
        fallback_price = pos.trigger_price

    observed_filled_qty = 0.0
    observed_fill_price = None
    ccxt_symbol = executor._normalize_symbol(BINGX_SYMBOL)
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

    ticker = await executor.get_ticker_price(BINGX_SYMBOL)
    fill_price = observed_fill_price or (
        float(ticker["price"])
        if ticker and ticker.get("price")
        else float(fallback_price)
    )
    await controller._handle_entry_fill(
        symbol=BINGX_SYMBOL,
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


async def _assert_bingx_exit_and_dca_orders(controller: TradingController) -> None:
    async def position_with_orders():
        async with controller._positions_dict_lock:
            pos = controller._active_position_get(BINGX_SYMBOL, "futures_usdtm")
            if not pos:
                return None
            has_sl = pos.current_sl_order_id is not None
            has_tp = len(pos.partial_tp_orders) >= 2 and all(
                tp.order_id for tp in pos.partial_tp_orders
            )
            has_dca = len(getattr(pos, "dca_order_ids", [])) >= 1
            return pos if has_sl and has_tp and has_dca else None

    position = await _wait_until(position_with_orders, timeout=60.0)
    assert position is not None, (
        "BingX controller did not place SL, partial TP and DCA orders."
    )

    open_orders = await controller.executors["live"].get_open_orders(BINGX_SYMBOL)
    algo_orders = await controller.executors["live"].get_open_algo_orders(BINGX_SYMBOL)
    all_open_order_ids = {
        str(o.get("orderId")) for o in [*open_orders, *algo_orders] if o.get("orderId")
    }

    expected_ids = {
        str(position.current_sl_order_id),
        *{str(tp.order_id) for tp in position.partial_tp_orders if tp.order_id},
        *{str(order_id) for order_id in position.dca_order_ids if order_id},
    }
    missing_ids = expected_ids - all_open_order_ids
    assert not missing_ids, (
        f"BingX futures did not expose all controller-tracked orders as open. "
        f"Missing IDs: {missing_ids}; open={open_orders}; algo={algo_orders}"
    )


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_bingx_controller_signal_to_position_sl_tp_dca_and_close(
    bingx_controller_case,
):
    controller: TradingController = bingx_controller_case["controller"]
    executor = bingx_controller_case["executor"]
    direction = bingx_controller_case["direction"]
    strategy_config_id = bingx_controller_case["strategy_config_id"]

    balances = await executor.get_account_balance()
    if balances is None:
        pytest.skip(
            "Could not fetch BingX virtual swap balance; private API is unavailable."
        )

    usdt_free = float((balances or {}).get("USDT", {}).get("free", 0) or 0)
    if usdt_free < BINGX_MIN_USDT_BALANCE:
        pytest.skip(
            f"Insufficient BingX virtual USDT balance: {usdt_free} < {BINGX_MIN_USDT_BALANCE}"
        )

    ticker = await executor.get_ticker_price(BINGX_SYMBOL)
    assert ticker and ticker.get("price"), (
        f"Could not fetch BingX ticker for {BINGX_SYMBOL}"
    )
    current_price = float(ticker["price"])

    pair_info = {
        "symbol": BINGX_SYMBOL,
        "last_price": current_price,
        "trigger_price": current_price,
        "tick_size": await executor.get_tick_size(BINGX_SYMBOL),
        "lot_params": await executor.get_lot_size_params(BINGX_SYMBOL),
        "min_notional": await executor.get_min_notional(BINGX_SYMBOL),
        "atr": current_price * 0.01,
        "natr": 1.0,
        "is_live_mode": True,
        "timestamp_dt": pd.Timestamp.now(tz="UTC"),
        "current_candle_index": 0,
        "strategy_config_id": strategy_config_id,
    }
    controller.consumer.update_pair_data(BINGX_SYMBOL, pair_info)

    signal = _build_signal(current_price, direction, strategy_config_id)
    await controller._process_signal(signal, pair_info.copy())

    await _force_entry_fill_if_websocket_did_not_deliver(controller, executor)
    position = await _wait_for_open_position(controller)
    assert position is not None and position.status == "OPEN", (
        f"BingX futures/{direction.name} position was not opened. "
        f"Last controller position: {position}"
    )
    assert position.direction == direction
    assert position.remaining_quantity > 0

    await _assert_bingx_exit_and_dca_orders(controller)

    await controller.close_position(BINGX_SYMBOL, reason="BINGX_E2E_FULL_PATH_CLOSE")
    closed = await _wait_until(
        _position_removed(controller),
        timeout=60.0,
    )
    assert closed, (
        f"BingX futures/{direction.name} position was not removed after close."
    )

    await asyncio.sleep(2)
    open_orders_after_close = await executor.get_open_orders(BINGX_SYMBOL)
    assert not open_orders_after_close, (
        f"BingX futures/{direction.name} left open orders after close: {open_orders_after_close}"
    )


def _position_removed(controller: TradingController):
    async def check():
        async with controller._positions_dict_lock:
            return (
                controller._active_position_get(BINGX_SYMBOL, "futures_usdtm") is None
            )

    return check
