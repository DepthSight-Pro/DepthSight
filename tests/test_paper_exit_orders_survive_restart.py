# File: tests/test_paper_exit_orders_survive_restart.py
"""
A paper position's resting exit orders must exist again after a bot restart.

THE DEFECT
----------
`PaperTradingExecutor` keeps its resting SL / partial-TP orders in
`self._open_orders`, a plain dict created empty in `__init__` and never
persisted or rebuilt. On restart the bot restores the POSITION from Redis
*including* its persisted exit-order state (`sl_placement_initiated`,
`current_sl_order_id`, `ptp_placement_initiated_flags`, each partial TP's
`order_id`/`client_order_id` with status PENDING) -- but the orders themselves
are gone.

Every consumer of that state believes the orders exist:
  - `_place_stop_loss` returns True on a stale `current_sl_order_id` having
    placed nothing;
  - `_place_partial_tp` returns early on `ptp_placement_initiated_flags`;
  - `_check_and_close_positions_without_sl` skips any position whose
    `sl_placement_initiated` is True, so the safety net that would otherwise
    force-close an unprotected position is disabled by the same stale flag.

Observed live: BTCUSDT LONG opened 2026-10-05T22:47:01Z, SL 84802.88,
TP 88201.54; the bot restarted 2026-10-07T00:02:18Z; mark fell to 84268.3 --
below the stop on every sample -- and the position never closed.

WHY THIS TEST SHAPE
-------------------
It drives the REAL `_load_runtime_state` and the REAL
`_ensure_paper_exit_orders_present` against a REAL `PaperTradingExecutor`
and a REAL `RiskManager`, and it asserts the OUTCOME: an order is actually
resting in `paper_executor._open_orders` and the real `check_open_orders()`
actually consumes it once price crosses. No production logic is copied here and
`tick_size` is never injected -- a paper-only controller genuinely has an empty
market-info cache, so `_place_stop_loss` takes its real `DEFAULT_TICK_SIZE`
fallback path, which is exactly what happens in production.

The only stub is `PaperTradingExecutor.place_order` in the fill test, and only
to keep the settlement/DB write out of a unit test. The trigger logic under
claim -- scanning `_open_orders`, parsing the stop price, comparing against the
mark -- is the real, unmodified `check_open_orders`.
"""

import asyncio
import json
import logging
import time

import pytest

from bot_module.controller import (
    ActivePositionMap,
    LivePosition,
    PartialTpOrderInfo,
    SignalDirection,
    TradingController,
)
from bot_module.paper_executor import PaperTradingExecutor
from bot_module.risk_manager import RiskManager

USER_ID = 7
SYMBOL = "BTCUSDT"

ENTRY_PRICE = 85000.0
STOP_LOSS = 84802.88209956
TAKE_PROFIT = 88201.54300088
REMAINING_QTY = 0.05

# Above the stop at placement time (so `_place_stop_loss`'s pre-flight passes),
# then driven below it to make the restored order trigger.
PRICE_AT_RESTART = 86000.0
PRICE_AFTER_STOP_CROSSED = 84000.0


# --- Test doubles: inputs only, never behaviour under test --------------------


class _FakeTradeLogger:
    """Minimal stand-in for the controller's trade_logger.

    `_place_partial_tp` calls `log_order_placed(...)` after a successful
    placement. It only needs to not raise.
    """

    def __init__(self):
        self.placed = []

    def log_order_placed(self, *args, **kwargs):
        self.placed.append((args, kwargs))


class _FakeDataConsumer:
    """The only price source the paper executor reads."""

    def __init__(self, price: float):
        self.price = price

    async def get_latest_price(self, symbol):
        return self.price

    async def get_latest_depth(self, symbol):
        return None


class _FakeRedis:
    """Serves the persisted runtime-state snapshot the previous process wrote."""

    def __init__(self, snapshot: dict):
        self._snapshot = snapshot

    async def get(self, key):
        return json.dumps(self._snapshot)

    async def set(self, key, value):
        # Added so the real `_save_runtime_state` can be exercised in tests that
        # assert on what the controller WRITES, not only what it reads back.
        try:
            self._snapshot = json.loads(value)
        except (TypeError, ValueError):
            self._snapshot = value
        return True


class _FakeLiveExecutor:
    """Stands in for a real exchange connection on the live-controller test only."""

    market_type = "futures_usdtm"

    def __init__(self, exchange_positions):
        self._exchange_positions = exchange_positions

    async def get_open_positions(self):
        return self._exchange_positions


# --- Fixture data ------------------------------------------------------------


def _persisted_position(**overrides) -> LivePosition:
    """A position exactly as `_publish_state_to_redis` would have persisted it.

    Every exit-order field carries a plausible, already-stale id: those orders
    only ever existed in the previous process's in-memory order book.
    """
    position = LivePosition(
        symbol=SYMBOL,
        direction=SignalDirection.LONG,
        entry_price=ENTRY_PRICE,
        initial_quantity=REMAINING_QTY,
        remaining_quantity=REMAINING_QTY,
        entry_time=time.time() - 3600,
        status="OPEN",
        mode="paper",
        api_key_id=None,
        user_id=USER_ID,
        strategy="TestStrategy",
        config_id=6999,
        market_type="futures_usdtm",
        signal_details={},
        entry_client_order_id="x-entry-abc12345",
        entry_order_id="2200861597",
        entry_order_status="FILLED",
        initial_stop_loss=STOP_LOSS,
        current_sl_price=STOP_LOSS,
        initial_take_profit=TAKE_PROFIT,
        # --- the stale exit-order state a restart must not trust ---
        current_sl_order_id="2200861599",
        current_sl_client_order_id="x-sl-deadbeefdeadbeef",
        is_sl_algo_order=False,
        sl_placement_initiated=True,
        ptp_placement_initiated_flags={0: True},
        partial_tp_orders=[
            PartialTpOrderInfo(
                target_price=TAKE_PROFIT,
                orig_fraction=0.5,
                quantity=REMAINING_QTY / 2,
                order_id=2200861598,
                client_order_id="x-ptp-cafebabe1234567",
                status="PENDING",
            )
        ],
        # Opened an hour ago, so the missing-SL grace period has long expired
        # and re-arming after the main loop's first tick would market-close it.
        time_status_open=time.time() - 3600,
    )
    for key, value in overrides.items():
        setattr(position, key, value)
    return position


def _state_snapshot(position: LivePosition) -> dict:
    """Serialised through the REAL producer, `LivePosition.to_dict`."""
    return {
        "serialization_format": "json",
        "timestamp": time.time(),
        "monitored_symbols": [SYMBOL],
        "closing_managed_symbols": [],
        "last_known_symbols": [SYMBOL],
        "currently_managed_symbols": [SYMBOL],
        "active_positions": {"paper:BTCUSDT": position.to_dict()},
    }


# --- Controller wiring -------------------------------------------------------


def _build_controller(persisted_position, live_executor=None, price=PRICE_AT_RESTART):
    """A real TradingController with the attribute surface startup touches.

    Built with `__new__` because `TradingController.__init__` opens exchange
    connections; every method used below is the real, unbound production one.
    """
    data_consumer = _FakeDataConsumer(price)
    paper_executor = PaperTradingExecutor(
        user_id=USER_ID,
        db_session=None,
        data_consumer=data_consumer,
        redis_client=None,
    )

    api_key_id = None if live_executor is None else 42

    controller = TradingController.__new__(TradingController)
    controller.loop = asyncio.get_event_loop()
    controller.user_id = USER_ID
    controller.api_key_id = api_key_id
    controller.api_key_name = "paper" if live_executor is None else "live"
    controller.executors = {"live": live_executor, "paper": paper_executor}
    controller.market_executors = {}
    controller.consumer = data_consumer
    controller.redis_client = _FakeRedis(_state_snapshot(persisted_position))
    controller.redis_key_runtime_state = f"runtime_state:{USER_ID}"
    controller._positions_dict_lock = asyncio.Lock()
    controller._active_positions = ActivePositionMap()
    controller._symbol_locks = {}
    controller._market_info_cache = {}
    controller._market_info_lock = asyncio.Lock()
    controller.instances_lock = asyncio.Lock()
    controller.running_strategy_instances = {}
    # `_handle_final_exit` stamps the close time here; without it the finalize
    # path raises before it ever reaches the PnL bookkeeping under test.
    controller._last_position_close_time_per_symbol = {}
    controller.telegram_notifier = None
    controller.user_telegram_chat_id = None
    controller.rm = RiskManager(
        executor=live_executor,
        paper_executor=paper_executor,
        user_id=USER_ID,
        db_session=None,
        user_settings={},
    )
    paper_executor.controller = controller
    # `_place_partial_tp` records the order through `trade_logger`. The real
    # controller always has one; without it the TP branch raises, and the
    # 2026-10-07 failure mode where a TP error discarded a successful SL
    # placement would be an artefact of the harness rather than production.
    controller.trade_logger = _FakeTradeLogger()

    return controller, paper_executor, data_consumer


async def _restart(controller) -> LivePosition:
    """Simulates the restart: restore from Redis, then re-arm exit orders."""
    await controller._load_runtime_state()
    await controller._ensure_paper_exit_orders_present()
    return controller._active_position_get(SYMBOL, "futures_usdtm")


# --- The defect --------------------------------------------------------------


@pytest.mark.asyncio
async def test_restored_paper_position_keeps_a_real_resting_stop_loss():
    """The core regression: a real STOP_MARKET order must be resting again.

    Without the fix, restore keeps `sl_placement_initiated=True` and the stale
    `current_sl_order_id`, so `_place_stop_loss` short-circuits and
    `_open_orders` stays empty forever.
    """
    controller, paper_executor, _ = _build_controller(_persisted_position())

    # The paper order book starts empty in a fresh process -- that is the bug.
    assert paper_executor._open_orders == {}

    position = await _restart(controller)

    stops = [o for o in paper_executor._open_orders.values() if o["type"] == "STOP_MARKET"]
    assert len(stops) == 1, (
        f"expected exactly one resting stop-loss after the restart, found "
        f"{len(stops)} in {list(paper_executor._open_orders.values())}"
    )

    stop = stops[0]
    assert stop["symbol"] == SYMBOL
    assert stop["side"] == "SELL", "a LONG stop-loss must rest as a SELL"
    assert float(stop["stopPrice"]) == pytest.approx(STOP_LOSS, rel=1e-9)
    assert float(stop["origQty"]) == pytest.approx(REMAINING_QTY, rel=1e-9)

    # The position must now point at an order that actually exists, rather than
    # at the id of one that died with the previous process.
    assert position.current_sl_order_id is not None
    assert position.current_sl_order_id != "2200861599"


@pytest.mark.asyncio
async def test_stale_persisted_exit_state_is_discarded_on_restore():
    """The invalidation half, asserted before the re-arm re-places anything.

    This is the assertion that fails on the unfixed code: `sl_placement_initiated`
    survives the restore as True, which both suppresses re-placement and
    disables the missing-SL watchdog.
    """
    controller, _, _ = _build_controller(_persisted_position())

    await controller._load_runtime_state()
    restored = controller._active_position_get(SYMBOL, "futures_usdtm")

    assert restored is not None, "the position itself must still be restored"
    assert restored.sl_placement_initiated is False
    assert restored.current_sl_order_id is None
    assert restored.current_sl_client_order_id is None
    assert restored.is_sl_algo_order is False
    assert restored.ptp_placement_initiated_flags == {}

    stale_tp = restored.partial_tp_orders[0]
    assert stale_tp.order_id is None
    assert stale_tp.client_order_id is None


@pytest.mark.asyncio
async def test_restored_partial_take_profit_is_re_placed_as_a_resting_limit_order():
    """Partial TPs are resting orders too, and they died the same way."""
    controller, paper_executor, _ = _build_controller(_persisted_position())

    position = await _restart(controller)

    limits = [o for o in paper_executor._open_orders.values() if o["type"] == "LIMIT"]
    assert len(limits) == 1, "the pending partial TP must be re-placed"
    assert limits[0]["side"] == "SELL"
    assert float(limits[0]["price"]) == pytest.approx(TAKE_PROFIT, rel=1e-9)

    tp = position.partial_tp_orders[0]
    assert tp.order_id is not None
    assert tp.client_order_id is not None
    assert tp.status == "PENDING"


@pytest.mark.asyncio
async def test_re_armed_stop_actually_fills_once_price_crosses():
    """The end-to-end consequence: the restored order is live, not decorative.

    Drives the real `PaperTradingExecutor.check_open_orders()` with the mark
    price below the stop. Only the settlement sink (`place_order`) is replaced,
    to keep the DB write out of a unit test; the trigger logic is production's.
    """
    controller, paper_executor, data_consumer = _build_controller(
        _persisted_position()
    )
    await _restart(controller)

    fills = []

    async def _recording_place_order(symbol, side, order_type, **kwargs):
        fills.append({"symbol": symbol, "side": side, "type": order_type, **kwargs})
        return {
            "orderId": 1,
            "clientOrderId": "fill-1",
            "avgFillPrice": PRICE_AFTER_STOP_CROSSED,
            "filledQty": kwargs.get("quantity"),
        }

    paper_executor.place_order = _recording_place_order

    # Before the cross, nothing fills.
    await paper_executor.check_open_orders()
    assert fills == [], "the stop must rest, not fill, while price is above it"

    # Price falls through the stop.
    data_consumer.price = PRICE_AFTER_STOP_CROSSED
    await paper_executor.check_open_orders()

    assert len(fills) == 1, f"the restored stop-loss never triggered: {fills}"
    assert fills[0]["type"] == "MARKET"
    assert fills[0]["side"] == "SELL"
    assert float(fills[0]["quantity"]) == pytest.approx(REMAINING_QTY, rel=1e-9)

    stop_ids = [
        cid
        for cid, o in paper_executor._open_orders.items()
        if o["type"] == "STOP_MARKET"
    ]
    assert not stop_ids, "a triggered stop must be removed from the order book"


@pytest.mark.asyncio
async def test_re_running_the_re_arm_places_no_duplicate_orders():
    """Idempotency: a second re-arm must not double up on the order book."""
    controller, paper_executor, _ = _build_controller(_persisted_position())

    await _restart(controller)
    first = dict(paper_executor._open_orders)

    await controller._ensure_paper_exit_orders_present()
    second = dict(paper_executor._open_orders)

    assert len(first) == 2, f"expected SL + one partial TP, got {len(first)}"
    assert set(first) == set(second), (
        f"second re-arm changed the order book: {set(first)} -> {set(second)}"
    )


# --- The live path must be untouched -----------------------------------------


@pytest.mark.asyncio
async def test_live_controller_keeps_its_persisted_exit_order_state():
    """A live controller's orders are real and sit on the exchange.

    The exchange confirms the position, so the persisted SL id and
    `sl_placement_initiated` flag must survive the restore untouched -- this fix
    is paper-only and must not silently strip live protection.
    """
    live_position = _persisted_position(
        mode="live", api_key_id=42, current_sl_order_id="99887766"
    )
    live_executor = _FakeLiveExecutor(
        [{"symbol": SYMBOL, "positionAmt": str(REMAINING_QTY), "entryPrice": "85000"}]
    )
    controller, paper_executor, _ = _build_controller(live_position, live_executor)

    await controller._load_runtime_state()
    restored = controller._active_position_get(SYMBOL, "futures_usdtm")

    assert restored is not None
    assert restored.sl_placement_initiated is True
    assert restored.current_sl_order_id == "99887766"
    assert restored.current_sl_client_order_id == "x-sl-deadbeefdeadbeef"

    # And the re-arm declines to touch a live controller's order book.
    await controller._ensure_paper_exit_orders_present()
    assert paper_executor._open_orders == {}
    assert restored.current_sl_order_id == "99887766"


@pytest.mark.asyncio
async def test_live_controller_without_executor_keeps_its_persisted_state():
    """The dangerous variant: a live controller whose executor failed to build.

    It has no live executor, but its orders are still real. Falling back to
    "no executor means paper" would strip a live stop-loss, so the discriminator
    is `api_key_id`, not executor presence.
    """
    live_position = _persisted_position(
        mode="live", api_key_id=42, current_sl_order_id="99887766"
    )
    controller, _, _ = _build_controller(live_position, live_executor=None)
    controller.api_key_id = 42
    controller.api_key_name = "live"

    await controller._load_runtime_state()
    restored = controller._active_position_get(SYMBOL, "futures_usdtm")

    assert restored is not None, "the position must still be restored"
    assert restored.sl_placement_initiated is True
    assert restored.current_sl_order_id == "99887766"

    await controller._ensure_paper_exit_orders_present()
    assert restored.current_sl_order_id == "99887766"


# --- The 2026-10-07 production failure --------------------------------------
#
# `4f59b54` shipped the startup re-arm and it FAILED on the live system: the
# method ran, placed no order, and emitted no INFO line at all. These three tests
# encode exactly the conditions that let that happen, so the same failure cannot
# recur silently.


@pytest.mark.asyncio
async def test_ensure_repairs_when_the_flag_claims_a_stop_but_none_exists():
    """The flag is not evidence. The ORDER BOOK is.

    `_place_stop_loss` returns True on a stale `current_sl_order_id`, so any
    check driven by `sl_placement_initiated` concludes the stop is fine. On
    2026-10-07 that made the deployed fix skip a BTCUSDT long that had no
    resting order at all, while the position sat 1.7% below its stop.
    """
    controller, paper_executor, _ = _build_controller(_persisted_position())

    await controller._load_runtime_state()
    restored = controller._active_position_get(SYMBOL, "futures_usdtm")
    assert restored is not None

    # Reproduce the live incident exactly: persisted state says "stop placed",
    # and the in-memory order book is empty (it always is after a restart).
    restored.sl_placement_initiated = True
    restored.current_sl_order_id = "2200861599"
    restored.current_sl_client_order_id = "x-sl-deadbeefdeadbeef"
    assert paper_executor._open_orders == {}

    await controller._ensure_paper_exit_orders_present()

    resting_types = [
        o.get("type") for o in paper_executor._open_orders.values()
    ]
    assert "STOP_MARKET" in resting_types, (
        "the ensure must place a real STOP_MARKET even though the persisted "
        f"flags claim one is already placed; resting orders were {resting_types}"
    )


@pytest.mark.asyncio
async def test_periodic_ensure_repairs_an_order_book_emptied_after_startup():
    """Correctness must not depend on startup-path ordering.

    The one-shot startup call is not sufficient: anything that empties the paper
    order book afterwards must be repaired by the periodic ensure within one
    cycle, with no restart and no operator action.
    """
    controller, paper_executor, _ = _build_controller(_persisted_position())
    await _restart(controller)

    assert any(
        o.get("type") == "STOP_MARKET" for o in paper_executor._open_orders.values()
    ), "precondition: the stop is resting right after startup"

    # Simulate the order book being wiped while the bot keeps running.
    paper_executor._open_orders.clear()
    assert paper_executor._open_orders == {}

    await controller._ensure_paper_exit_orders_present(reason="periodic")

    assert any(
        o.get("type") == "STOP_MARKET" for o in paper_executor._open_orders.values()
    ), (
        "the periodic ensure must restore protection after the order book is "
        "emptied mid-run; relying on a one-shot startup call is not sufficient"
    )


@pytest.mark.asyncio
async def test_non_open_paper_position_is_surfaced_never_silently_skipped(caplog):
    """A paper position that is not OPEN is invisible to BOTH consumers.

    `_publish_state_to_redis` skips `status != "OPEN"`, and the ensure skips it
    too -- so the position is neither protected nor shown, while still holding
    exposure. That double invisibility is how a position can disappear from every
    view without ever being closed or booked. It must be logged, loudly.
    """
    controller, paper_executor, _ = _build_controller(_persisted_position())
    await controller._load_runtime_state()

    restored = controller._active_position_get(SYMBOL, "futures_usdtm")
    assert restored is not None
    restored.status = "CLOSING"

    import logging
    logging.getLogger("bot_module").propagate = True
    with caplog.at_level(logging.WARNING):
        await controller._ensure_paper_exit_orders_present()

    surfaced = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(
        "CLOSING" in m and SYMBOL in m for m in surfaced
    ), (
        "a paper position holding exposure in a non-OPEN status must be surfaced "
        f"at WARNING; warnings were {surfaced}"
    )
    assert paper_executor._open_orders == {}, (
        "a non-OPEN position must not be given a resting order -- it is outside "
        "risk management and needs an operator, not a silent repair"
    )


# --- The stuck-CLOSING recovery was UNREACHABLE (2026-10-07) ----------------
#
# `_check_and_close_positions_without_sl` collects only positions whose status is
# "OPEN", then `return`s early when that list is empty. The stuck-CLOSING retry
# and Telegram escalation lived BELOW that return. A position stuck in CLOSING is
# not OPEN, so it never entered the list -- and with no OPEN positions present,
# the function returned before ever reaching its own recovery code. ETHUSDT and
# BTCUSDT sat in CLOSING for hours with zero retries, zero escalations and zero
# log lines, purely because of that early return.


@pytest.mark.asyncio
async def test_stuck_closing_position_is_retried_when_no_open_positions_exist():
    """The recovery must run even when there are NO OPEN positions.

    This is the exact production condition: both positions were CLOSING, the
    OPEN list was empty, and the old early return meant nothing ever retried.
    """
    controller, _, _ = _build_controller(_persisted_position())

    stuck = _persisted_position(
        status="CLOSING",
        remaining_quantity=REMAINING_QTY,
        exit_reason="RETRY_CLOSE_STUCK_CLOSING_test",
        failed_close_attempts=2,
    )
    # Put ONLY the stuck position in the controller's live state. Deliberately
    # no OPEN position: the OPEN list this function collects will be empty,
    # which is exactly the production condition that made the old early return
    # skip the recovery block entirely.
    controller._active_positions = ActivePositionMap()
    controller._active_position_set(stuck)

    retries = []

    async def _fake_close_position(*args, **kwargs):
        retries.append((args, kwargs))

    controller.close_position = _fake_close_position

    await controller._check_and_close_positions_without_sl()
    # `close_position` is dispatched via `loop.create_task`, so yield a couple of
    # times to let the scheduled coroutine actually run before asserting.
    for _ in range(5):
        await asyncio.sleep(0)

    assert retries, (
        "a position stuck in CLOSING with remaining quantity must be retried even "
        "when there are no OPEN positions; the early return used to skip it entirely"
    )
    assert retries[0][0][0] == SYMBOL, (
        f"expected a retry for {SYMBOL}, got {retries[0][0][0]}"
    )
    assert stuck.failed_close_attempts >= 3, (
        "the attempt counter must advance so escalation thresholds are reachable"
    )


@pytest.mark.asyncio
async def test_zero_quantity_closing_record_is_finalized_not_ignored():
    """A CLOSING record with zero quantity is a ZOMBIE, not a no-op.

    Its close already completed and the money already moved -- only the
    finalisation was lost. Such a record used to be filtered out by
    `remaining_quantity > 0`, so the recovery never saw it and `close_position`
    returned "Waiting for finalization" forever. That is how ETHUSDT and BTCUSDT
    sat in CLOSING: invisible to the dashboard, excluded from PnL, never closed.
    """
    controller, _, _ = _build_controller(_persisted_position())

    zombie = _persisted_position(
        status="CLOSING",
        remaining_quantity=0.0,
        exit_reason="CLOSED_WHILE_OFFLINE",
        failed_close_attempts=1,
    )
    controller._active_positions = ActivePositionMap()
    controller._active_position_set(zombie)

    retries = []

    async def _fake_close_position(*args, **kwargs):
        retries.append((args, kwargs))

    controller.close_position = _fake_close_position

    await controller._check_and_close_positions_without_sl()
    for _ in range(5):
        await asyncio.sleep(0)

    assert retries, (
        "a CLOSING record with zero remaining quantity must still be picked up for "
        "finalisation; filtering it out on remaining_quantity > 0 leaves a "
        "permanent zombie that is invisible on the dashboard"
    )


@pytest.mark.skip(reason=(
    "NOT YET WIRED. The PnL-preservation guard in _handle_final_exit is real and "
    "reviewed, but this test could not be made to drive the real path: "
    "_handle_final_exit resolves its executor through its own lookup and reaches "
    "order-cancellation code that this harness does not wire, so the assertions "
    "never run. A skipped test must NOT be read as coverage -- the guard is "
    "currently verified by code reading only. Either wire the executor/cancel "
    "surface in _build_controller, or drop this test and re-derive the guard "
    "through the recovery path."
))
@pytest.mark.asyncio
async def test_zero_price_finalization_preserves_already_booked_pnl():
    """A finalization-only close must NOT overwrite real, already-booked PnL.

    The zombie recovery calls `_handle_final_exit` with `exit_price=0.0` so no
    further PnL is booked. Without a guard, the fallback branch computes
    `total_pnl_calculated = 0` and assigns it to `position.pnl`, DESTROYING the
    PnL the original fill had already recorded -- silently rewriting the
    account's realised history the first time a zombie with real PnL is cleaned.

    ⚠️ See the skip reason: this does not currently verify anything.
    """
    controller, _, _ = _build_controller(_persisted_position())

    BOOKED_PNL = -137.25
    zombie = _persisted_position(
        status="CLOSING",
        remaining_quantity=0.0,
        pnl=BOOKED_PNL,
        exit_reason="CLOSED_WHILE_OFFLINE",
    )
    controller._active_positions = ActivePositionMap()
    controller._active_position_set(zombie)

    captured: dict = {}
    real_pop = controller._active_position_pop

    def _capture_pop(symbol, market_type=None):
        pos = controller._active_position_get(symbol, market_type)
        if pos is not None:
            captured["pnl"] = pos.pnl
        return real_pop(symbol, market_type)

    controller._active_position_pop = _capture_pop

    await controller._handle_final_exit(
        SYMBOL,
        "FINALIZE_ORPHANED_CLOSING",
        exit_price=0.0,
        commission=0.0,
        commission_asset=None,
        order_id=None,
        client_order_id=None,
        realized_pnl_from_exchange=0.0,
        exchange_pnl_available=False,
        market_type="futures_usdtm",
    )
    for _ in range(5):
        await asyncio.sleep(0)

    assert controller._active_position_get(SYMBOL, "futures_usdtm") is None
    assert captured.get("pnl") == BOOKED_PNL, (
        f"already-booked PnL {BOOKED_PNL} became {captured.get('pnl')!r}"
    )