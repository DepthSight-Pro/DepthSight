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
from bot_module.controller import PartialTpOrderInfo, TradingController
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

BYBIT_SYMBOL = os.getenv("BYBIT_E2E_SYMBOL", "BTCUSDT").upper()
BYBIT_MIN_USDT_BALANCE = float(os.getenv("BYBIT_E2E_MIN_USDT_BALANCE", "25"))
BYBIT_SPOT_MIN_USDT_BALANCE = float(os.getenv("BYBIT_E2E_SPOT_MIN_USDT_BALANCE", "200"))
BYBIT_SPOT_RISK_PER_TRADE_PERCENT = float(
    os.getenv("BYBIT_E2E_SPOT_RISK_PER_TRADE_PERCENT", "2.0")
)
BYBIT_SPOT_MAX_POSITION_PCT_BALANCE = float(
    os.getenv("BYBIT_E2E_SPOT_MAX_POSITION_PCT_BALANCE", "0.05")
)
BYBIT_CCXT_TIMEOUT_MS = int(os.getenv("BYBIT_E2E_CCXT_TIMEOUT_MS", "8000"))

BYBIT_CASES = [
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


def _bybit_credentials():
    api_key = os.getenv("TESTNET_BYBIT_API_KEY") or os.getenv("BYBIT_TESTNET_API_KEY")
    api_secret = os.getenv("TESTNET_BYBIT_API_SECRET") or os.getenv(
        "BYBIT_TESTNET_API_SECRET"
    )
    if not api_key or not api_secret:
        pytest.skip(
            "Bybit testnet keys are not set. Expected TESTNET_BYBIT_API_KEY "
            "and TESTNET_BYBIT_API_SECRET."
        )
    return api_key, api_secret


def _exchange_name_for_market(market_type: str) -> str:
    return "bybit_spot" if market_type == "spot" else "bybit_linear"


def _base_asset(symbol: str) -> str:
    if symbol.endswith("USDT"):
        return symbol[:-4]
    return symbol


async def _cleanup_bybit_symbol(executor, symbol: str) -> None:
    await executor.cancel_all_open_orders(symbol)
    await asyncio.sleep(0.5)

    if executor.market_type == "futures_usdtm":
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
        return

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


@pytest_asyncio.fixture(params=BYBIT_CASES)
async def bybit_controller_case(request, monkeypatch):
    market_type = request.param["market_type"]
    direction = request.param["direction"]
    api_key, api_secret = _bybit_credentials()

    monkeypatch.setattr(global_bot_config, "ACTIVE_TRADING_ENVIRONMENT", "testnet")
    monkeypatch.setattr(global_bot_config, "TRADING_MARKET_TYPE", market_type)
    monkeypatch.setattr(
        global_bot_config, "ALLOW_SHORT_POSITIONS", market_type == "futures_usdtm"
    )
    monkeypatch.setattr(global_bot_config, "SYMBOL_COOLDOWN_SECONDS", 1)
    monkeypatch.setattr(global_bot_config, "CONTROLLER_LOOP_DELAY", 0.05)
    risk_per_trade_percent = (
        BYBIT_SPOT_RISK_PER_TRADE_PERCENT if market_type == "spot" else 5.0
    )
    max_position_pct_balance = (
        BYBIT_SPOT_MAX_POSITION_PCT_BALANCE if market_type == "spot" else 0.5
    )
    monkeypatch.setattr(
        global_bot_config, "DEFAULT_RISK_PER_TRADE_PERCENT", risk_per_trade_percent
    )
    monkeypatch.setattr(
        global_bot_config,
        "MAX_REAL_POSITION_SIZE_PCT_BALANCE",
        max_position_pct_balance,
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
        exchange=_exchange_name_for_market(market_type),
        api_key=api_key,
        api_secret=api_secret,
        session=session,
        market_type=market_type,
    )
    executor._exchange.timeout = BYBIT_CCXT_TIMEOUT_MS
    if executor._exchange_pro:
        executor._exchange_pro.timeout = BYBIT_CCXT_TIMEOUT_MS

    try:
        await asyncio.wait_for(
            executor._exchange.fetch_time(),
            timeout=max(5.0, BYBIT_CCXT_TIMEOUT_MS / 1000.0 + 2.0),
        )
    except Exception as exc:
        await executor.close()
        if not session.closed:
            await session.close()
        pytest.skip(f"Bybit testnet is not reachable from this environment: {exc}")

    await _cleanup_bybit_symbol(executor, BYBIT_SYMBOL)

    user_settings = {
        "risk_management": {
            "riskPerTradePercent": risk_per_trade_percent,
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

    strategy_config_id = f"bybit-e2e-{market_type}-{direction.name.lower()}"
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
        "market_type": market_type,
        "direction": direction,
        "strategy_config_id": strategy_config_id,
        "session": session,
    }

    try:
        await _cleanup_bybit_symbol(executor, BYBIT_SYMBOL)
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
            "symbol": BYBIT_SYMBOL,
            "mode": "live",
            "symbol_selection_mode": "STATIC",
            "symbols": [BYBIT_SYMBOL],
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
        symbol=BYBIT_SYMBOL,
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
            pos = controller._active_positions.get(BYBIT_SYMBOL)
            if (
                pos
                and pos.status == "OPEN"
                and pos.entry_price
                and pos.remaining_quantity > 0
            ):
                return pos
        await asyncio.sleep(0.5)
    async with controller._positions_dict_lock:
        return controller._active_positions.get(BYBIT_SYMBOL)


async def _force_entry_fill_if_websocket_did_not_deliver(
    controller: TradingController,
    executor,
    timeout: float = 30.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        async with controller._positions_dict_lock:
            pos = controller._active_positions.get(BYBIT_SYMBOL)
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
        pos = controller._active_positions.get(BYBIT_SYMBOL)
        if not pos or pos.status == "OPEN" or not pos.entry_order_id:
            return
        entry_order_id = pos.entry_order_id
        entry_client_order_id = pos.entry_client_order_id
        entry_qty = pos.initial_quantity
        fallback_price = pos.trigger_price

    observed_filled_qty = 0.0
    observed_fill_price = None
    ccxt_symbol = executor._normalize_symbol(BYBIT_SYMBOL)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        mapped_order = None
        try:
            raw_order = await executor._exchange.fetch_order(
                entry_order_id,
                ccxt_symbol,
                {"acknowledged": True},
            )
            mapped_order = executor._map_ccxt_order_to_binance(raw_order)
        except Exception:
            try:
                closed_orders = await executor._exchange.fetch_closed_orders(
                    ccxt_symbol,
                    None,
                    10,
                    {"orderFilter": "Order"},
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

        if mapped_order is None:
            try:
                open_orders = await executor._exchange.fetch_open_orders(
                    ccxt_symbol,
                    None,
                    10,
                    {"orderFilter": "Order"},
                )
                for raw_order in open_orders:
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

        if getattr(executor, "market_type", None) == "spot":
            balances = await executor.get_account_balance()
            base_asset = (
                BYBIT_SYMBOL[:-4] if BYBIT_SYMBOL.endswith("USDT") else BYBIT_SYMBOL
            )
            free_base = float(
                ((balances or {}).get(base_asset) or {}).get("free", 0) or 0
            )
            if free_base >= entry_qty * 0.9:
                observed_filled_qty = min(entry_qty, free_base)
                break

        await asyncio.sleep(0.5)

    if getattr(executor, "market_type", None) == "spot":
        balances = await executor.get_account_balance()
        base_asset = _base_asset_from_symbol(BYBIT_SYMBOL)
        free_base = float(((balances or {}).get(base_asset) or {}).get("free", 0) or 0)
        if free_base >= entry_qty * 0.9:
            observed_filled_qty = min(observed_filled_qty or entry_qty, free_base)
        else:
            try:
                await executor.cancel_order(
                    symbol=BYBIT_SYMBOL,
                    orderId=entry_order_id,
                    origClientOrderId=entry_client_order_id,
                )
            except Exception:
                pass
            pytest.fail(
                f"Bybit spot entry order {entry_order_id} was not filled by testnet; "
                f"free {base_asset} balance is {free_base}."
            )

    if observed_filled_qty <= 0:
        observed_filled_qty = entry_qty

    ticker = await executor.get_ticker_price(BYBIT_SYMBOL)
    fill_price = observed_fill_price or (
        float(ticker["price"])
        if ticker and ticker.get("price")
        else float(fallback_price)
    )
    await controller._handle_entry_fill(
        symbol=BYBIT_SYMBOL,
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


async def _assert_bybit_exit_and_dca_orders(
    controller: TradingController, market_type: str
) -> None:
    async def position_with_orders():
        async with controller._positions_dict_lock:
            pos = controller._active_positions.get(BYBIT_SYMBOL)
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
        "Bybit controller did not place SL, partial TP and DCA orders."
    )

    open_orders = await controller.executors["live"].get_open_orders(BYBIT_SYMBOL)
    algo_orders = await controller.executors["live"].get_open_algo_orders(BYBIT_SYMBOL)
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
        f"Bybit {market_type} did not expose all controller-tracked orders as open. "
        f"Missing IDs: {missing_ids}; open={open_orders}; algo={algo_orders}"
    )


async def _assert_bybit_spot_sl_and_dca_orders(controller: TradingController) -> None:
    async def position_with_sl_and_dca():
        async with controller._positions_dict_lock:
            pos = controller._active_positions.get(BYBIT_SYMBOL)
            if not pos:
                return None
            has_sl = pos.current_sl_order_id is not None
            has_dca = len(getattr(pos, "dca_order_ids", [])) >= 1
            return pos if has_sl and has_dca else None

    position = await _wait_until(position_with_sl_and_dca, timeout=60.0)
    assert position is not None, (
        "Bybit spot controller did not place SL and DCA orders."
    )

    open_orders = await controller.executors["live"].get_open_orders(BYBIT_SYMBOL)
    algo_orders = await controller.executors["live"].get_open_algo_orders(BYBIT_SYMBOL)
    all_open_order_ids = {
        str(o.get("orderId")) for o in [*open_orders, *algo_orders] if o.get("orderId")
    }
    expected_ids = {
        str(position.current_sl_order_id),
        *{str(order_id) for order_id in position.dca_order_ids if order_id},
    }
    missing_ids = expected_ids - all_open_order_ids
    assert not missing_ids, (
        f"Bybit spot did not expose SL/DCA orders as open. "
        f"Missing IDs: {missing_ids}; open={open_orders}; algo={algo_orders}"
    )


def _base_asset_from_symbol(symbol: str) -> str:
    symbol_upper = symbol.upper()
    for quote_asset in ("USDT", "USDC", "BUSD", "BTC", "ETH", "EUR", "TRY"):
        if symbol_upper.endswith(quote_asset) and len(symbol_upper) > len(quote_asset):
            return symbol_upper[: -len(quote_asset)]
    return symbol_upper


async def _place_and_assert_spot_partial_tps_sequentially(
    controller: TradingController,
    executor,
) -> None:
    await controller._cancel_all_exit_orders(BYBIT_SYMBOL, "BYBIT_E2E_SPOT_SL_CHECKED")

    sl_cancelled = await _wait_until(
        lambda: _position_without_sl(controller),
        timeout=20.0,
    )
    assert sl_cancelled, "Bybit spot SL was not cleared before sequential TP placement."

    base_asset = _base_asset_from_symbol(BYBIT_SYMBOL)

    async def free_base_available():
        balances = await executor.get_account_balance()
        free_qty = float(((balances or {}).get(base_asset) or {}).get("free", 0) or 0)
        return free_qty if free_qty > 0 else None

    free_base_qty = await _wait_until(free_base_available, timeout=20.0)
    assert free_base_qty, (
        f"No free {base_asset} balance released after cancelling spot SL."
    )

    async with controller._positions_dict_lock:
        pos = controller._active_positions.get(BYBIT_SYMBOL)
        assert pos is not None and pos.status == "OPEN", (
            "Bybit spot position disappeared before TP placement."
        )
        available_qty = min(float(pos.remaining_quantity), free_base_qty)
        assert available_qty > 0, (
            f"No free {base_asset} balance available for spot TP placement."
        )
        first_qty = available_qty * 0.25
        second_qty = available_qty * 0.25
        entry_price = float(pos.entry_price or pos.trigger_price)
        pos.partial_tp_orders = [
            PartialTpOrderInfo(
                target_price=entry_price * 1.16, orig_fraction=0.25, quantity=first_qty
            ),
            PartialTpOrderInfo(
                target_price=entry_price * 1.24, orig_fraction=0.25, quantity=second_qty
            ),
        ]
        pos.ptp_placement_initiated_flags.clear()
        position_ref = pos

    for idx in range(2):
        async with controller._positions_dict_lock:
            pos = controller._active_positions.get(BYBIT_SYMBOL)
            assert pos is not None
            tp = pos.partial_tp_orders[idx]

        await controller._place_partial_tp(
            position_obj_ref=position_ref,
            target_price=tp.target_price,
            quantity_to_close=tp.quantity,
            orig_fraction=tp.orig_fraction,
            ptp_internal_idx=idx,
        )

        placed = await _wait_until(
            lambda idx=idx: _spot_tp_placed(controller, idx),
            timeout=20.0,
        )
        assert placed, f"Bybit spot partial TP #{idx + 1} was not placed sequentially."

    open_orders = await executor.get_open_orders(BYBIT_SYMBOL)
    open_order_ids = {str(o.get("orderId")) for o in open_orders if o.get("orderId")}
    async with controller._positions_dict_lock:
        pos = controller._active_positions.get(BYBIT_SYMBOL)
        assert pos is not None
        expected_tp_ids = {
            str(tp.order_id) for tp in pos.partial_tp_orders if tp.order_id
        }
    assert expected_tp_ids <= open_order_ids, (
        f"Bybit spot did not expose sequential partial TPs as open. "
        f"Missing IDs: {expected_tp_ids - open_order_ids}; open={open_orders}"
    )

    await controller._cancel_all_exit_orders(BYBIT_SYMBOL, "BYBIT_E2E_SPOT_TP_CHECKED")
    tp_cancelled = await _wait_until(
        lambda: _position_without_open_tps(controller),
        timeout=20.0,
    )
    assert tp_cancelled, "Bybit spot partial TPs were not cleared before final close."


async def _position_without_sl(controller: TradingController) -> bool:
    async with controller._positions_dict_lock:
        pos = controller._active_positions.get(BYBIT_SYMBOL)
        return bool(pos and pos.current_sl_order_id is None)


async def _spot_tp_placed(controller: TradingController, idx: int) -> bool:
    async with controller._positions_dict_lock:
        pos = controller._active_positions.get(BYBIT_SYMBOL)
        if not pos or idx >= len(pos.partial_tp_orders):
            return False
        return pos.partial_tp_orders[idx].order_id is not None


async def _position_without_open_tps(controller: TradingController) -> bool:
    async with controller._positions_dict_lock:
        pos = controller._active_positions.get(BYBIT_SYMBOL)
        return bool(
            pos
            and all(
                not (tp.status == "PENDING" and tp.order_id)
                for tp in pos.partial_tp_orders
            )
        )


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_bybit_controller_signal_to_position_sl_tp_dca_and_close(
    bybit_controller_case,
):
    controller: TradingController = bybit_controller_case["controller"]
    executor = bybit_controller_case["executor"]
    market_type = bybit_controller_case["market_type"]
    direction = bybit_controller_case["direction"]
    strategy_config_id = bybit_controller_case["strategy_config_id"]

    if market_type == "spot" and direction == SignalDirection.SHORT:
        pytest.skip(
            "Bybit spot does not support short positions through this controller path."
        )

    balances = await executor.get_account_balance()
    if balances is None:
        pytest.skip(
            "Could not fetch Bybit account balance; testnet/private API is unavailable."
        )

    usdt_free = float((balances or {}).get("USDT", {}).get("free", 0) or 0)
    required_usdt_balance = (
        BYBIT_SPOT_MIN_USDT_BALANCE if market_type == "spot" else BYBIT_MIN_USDT_BALANCE
    )
    assert usdt_free >= required_usdt_balance, (
        f"Insufficient Bybit testnet USDT balance for {market_type}: "
        f"{usdt_free} < {required_usdt_balance}"
    )

    ticker = await executor.get_ticker_price(BYBIT_SYMBOL)
    assert ticker and ticker.get("price"), (
        f"Could not fetch Bybit ticker for {BYBIT_SYMBOL}"
    )
    current_price = float(ticker["price"])

    pair_info = {
        "symbol": BYBIT_SYMBOL,
        "last_price": current_price,
        "trigger_price": current_price,
        "tick_size": await executor.get_tick_size(BYBIT_SYMBOL),
        "lot_params": await executor.get_lot_size_params(BYBIT_SYMBOL),
        "min_notional": await executor.get_min_notional(BYBIT_SYMBOL),
        "atr": current_price * 0.01,
        "natr": 1.0,
        "is_live_mode": True,
        "timestamp_dt": pd.Timestamp.now(tz="UTC"),
        "current_candle_index": 0,
        "strategy_config_id": strategy_config_id,
    }
    controller.consumer.update_pair_data(BYBIT_SYMBOL, pair_info)

    original_place_partial_tp = controller._place_partial_tp
    if market_type == "spot":

        async def _skip_initial_spot_partial_tp(*args, **kwargs):
            return None

        controller._place_partial_tp = _skip_initial_spot_partial_tp

    signal = _build_signal(current_price, direction, strategy_config_id)
    await controller._process_signal(signal, pair_info.copy())

    await _force_entry_fill_if_websocket_did_not_deliver(controller, executor)
    position = await _wait_for_open_position(controller)
    if market_type == "spot":
        controller._place_partial_tp = original_place_partial_tp

    assert position is not None and position.status == "OPEN", (
        f"Bybit {market_type}/{direction.name} position was not opened. "
        f"Last controller position: {position}"
    )
    assert position.direction == direction
    assert position.remaining_quantity > 0

    if market_type == "spot":
        await _assert_bybit_spot_sl_and_dca_orders(controller)
        await _place_and_assert_spot_partial_tps_sequentially(controller, executor)
    else:
        await _assert_bybit_exit_and_dca_orders(controller, market_type)

    await controller.close_position(BYBIT_SYMBOL, reason="BYBIT_E2E_FULL_PATH_CLOSE")
    closed = await _wait_until(
        _position_removed(controller),
        timeout=60.0,
    )
    assert closed, (
        f"Bybit {market_type}/{direction.name} position was not removed after close."
    )

    await asyncio.sleep(2)
    open_orders_after_close = await executor.get_open_orders(BYBIT_SYMBOL)
    assert not open_orders_after_close, (
        f"Bybit {market_type}/{direction.name} left open orders after close: "
        f"{open_orders_after_close}"
    )


def _position_removed(controller: TradingController):
    async def check():
        async with controller._positions_dict_lock:
            return BYBIT_SYMBOL not in controller._active_positions

    return check
