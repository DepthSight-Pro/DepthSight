# tests/test_realized_pnl_attribution.py
"""Exact per-config realized PnL attribution for strategy cards.

Cards must show their own config's lifetime realized PnL, never the
RiskManager pool keyed by strategy *class* name (shared by every strategy
on the account and growing with unrelated closes).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from api import crud
from bot_module.controller import TradingController


async def _make_trade(db_session, user_id, config_id, pnl, api_key_id=1):
    await crud.create_trade(
        db=db_session,
        user_id=user_id,
        trade_data={
            "trade_uuid": f"uuid-{config_id}-{pnl}-{api_key_id}-{id(object())}",
            "timestamp_close": datetime.now(timezone.utc),
            "symbol": "BTCUSDT",
            "strategy_config_id": config_id,
            "direction": "LONG",
            "entry_price": 100.0,
            "exit_price": 101.0,
            "pnl": pnl,
            "api_key_id": api_key_id,
        },
        trade_mode="LIVE",
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_get_realized_pnl_by_config_groups_and_scopes(db_session, test_user):
    await _make_trade(db_session, test_user.id, "cfg-a", 10.0, api_key_id=1)
    await _make_trade(db_session, test_user.id, "cfg-a", -4.0, api_key_id=1)
    await _make_trade(db_session, test_user.id, "cfg-a", 100.0, api_key_id=2)
    await _make_trade(db_session, test_user.id, "cfg-b", 7.0, api_key_id=1)
    await _make_trade(db_session, test_user.id, None, 50.0, api_key_id=1)

    totals = await crud.get_realized_pnl_by_config(
        db_session, user_id=test_user.id, api_key_id=1
    )
    assert totals == {"cfg-a": 6.0, "cfg-b": 7.0}

    other_key = await crud.get_realized_pnl_by_config(
        db_session, user_id=test_user.id, api_key_id=2
    )
    assert other_key == {"cfg-a": 100.0}


def _bare_controller():
    controller = TradingController.__new__(TradingController)
    controller._realized_pnl_by_config = {}
    controller._realized_pnl_seeded = False
    return controller


def test_accumulate_realized_pnl():
    controller = _bare_controller()
    controller._accumulate_realized_pnl("cfg-a", 10.0)
    controller._accumulate_realized_pnl("cfg-a", -4.0)
    controller._accumulate_realized_pnl("cfg-b", 7.0)
    assert controller._realized_pnl_by_config == {"cfg-a": 6.0, "cfg-b": 7.0}


def test_accumulate_realized_pnl_ignores_garbage():
    controller = _bare_controller()
    controller._accumulate_realized_pnl(None, 10.0)
    controller._accumulate_realized_pnl("", 10.0)
    controller._accumulate_realized_pnl("cfg-a", None)
    controller._accumulate_realized_pnl("cfg-a", float("nan"))
    controller._accumulate_realized_pnl("cfg-a", "not-a-number")
    assert controller._realized_pnl_by_config == {}


@pytest.mark.asyncio
async def test_seed_realized_pnl_by_config(monkeypatch):
    controller = _bare_controller()
    controller.user_id = 186
    controller.api_key_id = 54

    async def _fake_session():
        yield AsyncMock()

    controller.get_db_session = _fake_session
    monkeypatch.setattr(
        "api.crud.get_realized_pnl_by_config",
        AsyncMock(return_value={"cfg-a": 12.5}),
    )

    await controller._seed_realized_pnl_by_config()
    assert controller._realized_pnl_by_config == {"cfg-a": 12.5}
    assert controller._realized_pnl_seeded is True

    # Second call is a no-op (single seeding).
    await controller._seed_realized_pnl_by_config()
    assert controller._realized_pnl_by_config == {"cfg-a": 12.5}


@pytest.mark.asyncio
async def test_seed_realized_pnl_failure_is_fail_open(monkeypatch):
    controller = _bare_controller()
    controller.user_id = 186
    controller.api_key_id = 54

    async def _boom_session():
        raise RuntimeError("db down")
        yield

    controller.get_db_session = _boom_session
    await controller._seed_realized_pnl_by_config()
    assert controller._realized_pnl_by_config == {}
    assert controller._realized_pnl_seeded is False
