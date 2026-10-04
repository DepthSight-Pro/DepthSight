"""Regression: paper TP/SL simulation must actually close positions.

295 entries / 296 TPs / 0 closes were observed on a ladder run with 135k
PaperOrderCheck runs and zero fills. This test drives the exact production
path - place_order() then check_open_orders() against a moving price - and
proves a touch fills, closes the position, and records the exit economics.
"""

from unittest.mock import AsyncMock
import asyncio
from types import SimpleNamespace

import pytest

from api import models
from bot_module.paper_executor import PaperTradingExecutor


def _make_executor(db_session, user_id, prices):
    consumer = AsyncMock()
    consumer.get_latest_depth = AsyncMock(return_value=None)
    consumer.get_latest_price = AsyncMock(side_effect=lambda s: prices.get(s))
    return PaperTradingExecutor(
        user_id=user_id,
        db_session=db_session,
        data_consumer=consumer,
        redis_client=None,
    )


async def _db_trades(db_session, user_id):
    from sqlalchemy import select

    res = await db_session.execute(
        select(models.Trade)
        .where(models.Trade.user_id == user_id)
        .order_by(models.Trade.id)
    )
    return list(res.scalars().all())


@pytest.mark.asyncio
async def test_tp_limit_touch_fills_and_closes(db_session, test_user):
    prices = {"BTCUSDT": 83400.0}
    ex = _make_executor(db_session, test_user.id, prices)
    assert await ex._ensure_paper_wallet() is True

    entry = await ex.place_order(
        symbol="BTCUSDT", side="BUY", order_type="MARKET", quantity=0.24
    )
    assert entry.get("status") == "FILLED"
    assert "BTCUSDT" in ex._positions

    tp = await ex.place_order(
        symbol="BTCUSDT",
        side="SELL",
        order_type="LIMIT",
        quantity=0.24,
        price="83650.0",
    )
    assert tp.get("status") == "NEW"
    assert len(ex._open_orders) == 1

    # Below TP: nothing may happen.
    await ex.check_open_orders()
    assert len(ex._open_orders) == 1
    assert "BTCUSDT" in ex._positions

    # Touch TP: fill, close, record.
    prices["BTCUSDT"] = 83660.0
    await ex.check_open_orders()
    assert len(ex._open_orders) == 0
    assert "BTCUSDT" not in ex._positions

    trades = await _db_trades(db_session, test_user.id)
    exits = [t for t in trades if (t.pnl or 0) != 0]
    assert exits, "the TP fill must record an exit trade with PnL"
    assert exits[-1].pnl > 0


@pytest.mark.asyncio
async def test_stop_market_touch_fills_and_closes(db_session, test_user):
    prices = {"BTCUSDT": 83400.0}
    ex = _make_executor(db_session, test_user.id, prices)
    assert await ex._ensure_paper_wallet() is True

    entry = await ex.place_order(
        symbol="BTCUSDT", side="BUY", order_type="MARKET", quantity=0.24
    )
    assert entry.get("status") == "FILLED"

    sl = await ex.place_order(
        symbol="BTCUSDT",
        side="SELL",
        order_type="STOP_MARKET",
        quantity=0.24,
        stopPrice="83150.0",
    )
    assert sl.get("status") == "NEW"

    prices["BTCUSDT"] = 83140.0
    await ex.check_open_orders()
    assert len(ex._open_orders) == 0
    assert "BTCUSDT" not in ex._positions

    trades = await _db_trades(db_session, test_user.id)
    exits = [t for t in trades if (t.pnl or 0) != 0]
    assert exits, "the SL fill must record an exit trade with PnL"
    assert exits[-1].pnl < 0


class _FakeController:
    """Minimal stand-in: dict lock + positions + finalization recorder."""

    def __init__(self):
        self._positions_dict_lock = asyncio.Lock()
        self._active_positions = {}
        self.finalized = []

    def _active_position_get(self, symbol, market_type=None):
        return self._active_positions.get(symbol)

    async def _handle_final_exit(self, symbol, reason, *args, **kwargs):
        self.finalized.append((symbol, reason))
        self._active_positions.pop(symbol, None)


def _controller_position():
    return SimpleNamespace(
        status="OPEN",
        remaining_quantity=0.24,
        current_sl_order_id=None,
        current_sl_client_order_id=None,
        partial_tp_orders=[],
        entry_client_order_id="x-entry-test",
    )


@pytest.mark.asyncio
async def test_tp_fill_finalizes_controller_position(db_session, test_user):
    """A paper TP fill must not leave the controller position stuck in CLOSING.

    Observed in prod: fills simulated fine, but nothing ever called the
    controller finalization - no POSITION_CLOSED, no RM update, no re-entry,
    positions leaking in memory. The fill must drive _handle_final_exit.
    """
    prices = {"BTCUSDT": 83400.0}
    ex = _make_executor(db_session, test_user.id, prices)
    assert await ex._ensure_paper_wallet() is True

    fake = _FakeController()
    fake._active_positions["BTCUSDT"] = _controller_position()
    ex.controller = fake

    await ex.place_order(
        symbol="BTCUSDT",
        side="SELL",
        order_type="LIMIT",
        quantity=0.24,
        price="83650.0",
    )
    assert len(ex._open_orders) == 1

    prices["BTCUSDT"] = 83660.0
    await ex.check_open_orders()

    assert len(ex._open_orders) == 0
    assert fake.finalized == [("BTCUSDT", "PAPER_TP_FILLED")]
    assert "BTCUSDT" not in fake._active_positions


@pytest.mark.asyncio
async def test_sl_fill_finalizes_controller_position(db_session, test_user):
    prices = {"BTCUSDT": 83400.0}
    ex = _make_executor(db_session, test_user.id, prices)
    assert await ex._ensure_paper_wallet() is True

    fake = _FakeController()
    fake._active_positions["BTCUSDT"] = _controller_position()
    ex.controller = fake

    await ex.place_order(
        symbol="BTCUSDT",
        side="SELL",
        order_type="STOP_MARKET",
        quantity=0.24,
        stopPrice="83150.0",
    )
    assert len(ex._open_orders) == 1

    prices["BTCUSDT"] = 83140.0
    await ex.check_open_orders()

    assert len(ex._open_orders) == 0
    assert fake.finalized == [("BTCUSDT", "PAPER_SL_FILLED")]
    assert "BTCUSDT" not in fake._active_positions


@pytest.mark.asyncio
async def test_market_fill_releases_session_pin(db_session, test_user, monkeypatch):
    """Regression (A14 refresh pin): refresh() after the fill commit opens a
    new transaction on the ambient long-lived session that pure reads never
    return: ~1 pinned pool connection per traded controller (the 02:00 knee
    at ~340 controllers on a 350 pool). A release commit must follow refresh.
    """
    prices = {"BTCUSDT": 83400.0}
    ex = _make_executor(db_session, test_user.id, prices)
    assert await ex._ensure_paper_wallet() is True

    events = []
    orig_commit = db_session.commit
    orig_refresh = db_session.refresh

    async def rec_commit(*args, **kwargs):
        events.append("commit")
        return await orig_commit(*args, **kwargs)

    async def rec_refresh(*args, **kwargs):
        events.append("refresh")
        return await orig_refresh(*args, **kwargs)

    monkeypatch.setattr(db_session, "commit", rec_commit)
    monkeypatch.setattr(db_session, "refresh", rec_refresh)

    entry = await ex.place_order(
        symbol="BTCUSDT", side="BUY", order_type="MARKET", quantity=0.24
    )
    assert entry.get("status") == "FILLED"
    assert "refresh" in events
    assert events[-1] == "commit", f"a release commit must follow refresh, got {events}"
