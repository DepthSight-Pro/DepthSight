# tests/test_hedge_spread_exit.py
"""Controller spread take-profit (SPREAD_PROFIT_EXIT) with a fake Redis."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot_module import hedge_mirror as hm
from bot_module.controller import LivePosition, TradingController
from bot_module.datatypes import SignalDirection

GROUP = "spreadgrp1"
SYMBOL = "BTCUSDT"


def _bare_controller(redis_client):
    controller = TradingController.__new__(TradingController)
    controller.user_id = 1
    controller.api_key_id = 11
    controller.redis_client = redis_client
    controller.loop = asyncio.get_running_loop()
    controller._positions_dict_lock = asyncio.Lock()
    controller.instances_lock = asyncio.Lock()
    controller.running_strategy_instances = {}
    controller._active_positions = {}
    controller.consumer = MagicMock()
    controller.consumer.get_latest_price = AsyncMock(return_value=105.0)
    controller.close_position = AsyncMock()
    controller._publish_hedge_command = AsyncMock()
    return controller


def _hedge_config(leg="A", policy="SPREAD_PROFIT_EXIT"):
    return {
        "enabled": True,
        "group_id": GROUP,
        "leg": leg,
        "invert": leg == "B",
        "side_mode": "OPPOSITE",
        "exit_policy": policy,
        "size_mode": "FIXED_NOTIONAL",
        "notional_usd": 100.0,
        "spread_exit_threshold_pct": 0.5,
        "spread_exit_cooldown_sec": 60.0,
        "api_key_id": 11 if leg == "A" else 22,
        "sibling_api_key_id": 22 if leg == "A" else 11,
    }


def _register_instance(controller, leg="A", policy="SPREAD_PROFIT_EXIT"):
    cfg = _hedge_config(leg=leg, policy=policy)
    controller.running_strategy_instances[f"cfg-1:{leg.lower()}"] = (
        MagicMock(),
        {
            "id": f"cfg-1:{leg.lower()}",
            "config_id": "cfg-1",
            "symbols": [SYMBOL],
            "symbol_selection_mode": "STATIC",
            "config_data": {"hedge": cfg},
        },
    )
    return cfg


def _open_position(
    direction=SignalDirection.LONG, leg="A", policy="SPREAD_PROFIT_EXIT"
):
    return LivePosition(
        symbol=SYMBOL,
        direction=direction,
        entry_price=100.0,
        initial_quantity=1.0,
        remaining_quantity=1.0,
        entry_time=time.time(),
        strategy="TestStrategy",
        status="OPEN",
        config_id="cfg-1",
        user_id=1,
        api_key_id=11,
        market_type="futures_usdtm",
        signal_details={
            "hedge_group_id": GROUP,
            "hedge_leg": leg,
            "hedge_exit_policy": policy,
            "hedge_sibling_api_key_id": 22,
        },
    )


def _sibling_payload(pnl=0.6, direction="SHORT", age_sec=0.0):
    return {
        "mark": 95.0,
        "pnl": pnl,
        "qty": 1.0,
        "entry": 100.0,
        "direction": direction,
        "ts": time.time() - age_sec,
        "api_key_id": 22,
    }


@pytest.mark.asyncio
async def test_spread_exit_fires_and_closes_both():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_instance(controller, leg="A")
    controller._active_positions["futures_usdtm:BTCUSDT"] = _open_position()
    # Sibling SHORT pnl +0.6; mine LONG (105-100)*1 = +5.0 -> pair +5.6
    # on $200 combined = +2.8% >= 0.5% -> fires.
    await redis_client.set(
        hm.hedge_mark_key(GROUP, SYMBOL, "B"),
        json.dumps(_sibling_payload(pnl=0.6)),
        ex=30,
    )

    await controller._check_hedge_spread_exits()
    # Closes are fire-and-forget tasks: let the loop run them.
    await asyncio.sleep(0.2)

    controller.close_position.assert_awaited_once()
    args, _kwargs = controller.close_position.await_args
    assert args[0] == SYMBOL
    assert "HEDGE_SPREAD" in str(args[1])
    controller._publish_hedge_command.assert_awaited_once()
    sent = controller._publish_hedge_command.await_args[0][0]
    assert sent["command"] == "CLOSE_POSITION"
    assert sent["payload"]["api_key_id"] == 22
    assert "HEDGE_SPREAD" in sent["payload"]["reason"]
    # Cooldown armed so a fresh pair can't instantly re-trigger.
    assert await redis_client.get(hm.hedge_cooldown_key(GROUP, SYMBOL)) is not None
    # Own mark published for the sibling to read.
    own = json.loads(await redis_client.get(hm.hedge_mark_key(GROUP, SYMBOL, "A")))
    assert own["pnl"] == pytest.approx(5.0)
    # Spread-exit stats recorded for pair ranking.
    stats = await redis_client.hgetall(hm.hedge_spread_stats_key(GROUP, SYMBOL))
    assert stats.get("exits") == "1"
    assert float(stats.get("dev_sum_pct", "0")) == pytest.approx(2.8)
    assert float(stats.get("last_ts", "0")) > 0


@pytest.mark.asyncio
async def test_spread_exit_skips_below_threshold():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_instance(controller, leg="A")
    controller.consumer.get_latest_price = AsyncMock(return_value=100.1)
    controller._active_positions["futures_usdtm:BTCUSDT"] = _open_position()
    await redis_client.set(
        hm.hedge_mark_key(GROUP, SYMBOL, "B"),
        json.dumps(_sibling_payload(pnl=0.1)),
        ex=30,
    )

    await controller._check_hedge_spread_exits()

    controller.close_position.assert_not_awaited()
    controller._publish_hedge_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_spread_exit_skips_stale_sibling():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_instance(controller, leg="A")
    controller._active_positions["futures_usdtm:BTCUSDT"] = _open_position()
    await redis_client.set(
        hm.hedge_mark_key(GROUP, SYMBOL, "B"),
        json.dumps(_sibling_payload(pnl=50.0, age_sec=30.0)),
        ex=60,
    )

    await controller._check_hedge_spread_exits()

    controller.close_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_spread_exit_skips_same_direction_sibling():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_instance(controller, leg="A")
    controller._active_positions["futures_usdtm:BTCUSDT"] = _open_position()
    await redis_client.set(
        hm.hedge_mark_key(GROUP, SYMBOL, "B"),
        json.dumps(_sibling_payload(pnl=50.0, direction="LONG")),
        ex=30,
    )

    await controller._check_hedge_spread_exits()

    controller.close_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_spread_exit_ignores_non_spread_policy():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_instance(controller, leg="A", policy="INDEPENDENT")
    controller._active_positions["futures_usdtm:BTCUSDT"] = _open_position(
        policy="INDEPENDENT"
    )
    await redis_client.set(
        hm.hedge_mark_key(GROUP, SYMBOL, "B"),
        json.dumps(_sibling_payload(pnl=50.0)),
        ex=30,
    )

    await controller._check_hedge_spread_exits()

    controller.close_position.assert_not_awaited()
    assert await redis_client.get(hm.hedge_mark_key(GROUP, SYMBOL, "A")) is None


def _race_position(policy="SPREAD_PROFIT_EXIT"):
    return _open_position(policy=policy)


@pytest.mark.asyncio
async def test_race_fallback_spread_individual_exit_publishes():
    """SPREAD legs must not survive alone: a plain TP/SL closes the sibling."""
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    controller._publish_hedge_command = AsyncMock()

    controller._maybe_publish_hedge_race_close(
        _race_position(policy="SPREAD_PROFIT_EXIT"), "TAKE_PROFIT"
    )
    await asyncio.sleep(0.2)

    controller._publish_hedge_command.assert_awaited_once()
    sent = controller._publish_hedge_command.await_args[0][0]
    assert sent["command"] == "CLOSE_POSITION"
    assert sent["payload"]["api_key_id"] == 22


@pytest.mark.asyncio
async def test_race_fallback_skips_hedge_reasons():
    """HEDGE_SPREAD / HEDGE_RACE exits never re-broadcast (loop guard)."""
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    controller._publish_hedge_command = AsyncMock()

    controller._maybe_publish_hedge_race_close(
        _race_position(policy="SPREAD_PROFIT_EXIT"), "HEDGE_SPREAD:spreadgr"
    )
    controller._maybe_publish_hedge_race_close(
        _race_position(policy="RACE_FINAL_MARKET"), "HEDGE_RACE:spreadgr"
    )
    await asyncio.sleep(0.2)

    controller._publish_hedge_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_race_fallback_skips_independent():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    controller._publish_hedge_command = AsyncMock()

    controller._maybe_publish_hedge_race_close(
        _race_position(policy="INDEPENDENT"), "TAKE_PROFIT"
    )
    await asyncio.sleep(0.2)

    controller._publish_hedge_command.assert_not_awaited()
