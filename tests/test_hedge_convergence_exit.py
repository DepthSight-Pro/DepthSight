# tests/test_hedge_convergence_exit.py
"""Controller convergence exit (SPREAD_CONVERGENCE_EXIT) with a fake Redis."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot_module import hedge_mirror as hm
from bot_module.controller import LivePosition, TradingController
from bot_module.datatypes import SignalDirection

GROUP = "convgrp001"
SYMBOL = "BTCUSDT"

# Entry proof prices: A fills at 110, B at 100 -> entry spread = +9.5238%
# of mid. With ratio_pct=80 the trigger level is 20% of that = 1.9048%.
PRICE_A = 110.0
PRICE_B = 100.0
ENTRY_SPREAD = round((PRICE_A - PRICE_B) / ((PRICE_A + PRICE_B) / 2) * 100.0, 6)
TRIGGER_SPREAD = round(ENTRY_SPREAD * 0.2, 6)


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
    controller.consumer.get_latest_price = AsyncMock(return_value=101.0)
    controller.close_position = AsyncMock()
    controller._publish_hedge_command = AsyncMock()
    return controller


def _hedge_config(leg="A", policy="SPREAD_CONVERGENCE_EXIT"):
    return {
        "enabled": True,
        "group_id": GROUP,
        "leg": leg,
        "invert": leg == "B",
        "side_mode": "OPPOSITE",
        "exit_policy": policy,
        "size_mode": "FIXED_NOTIONAL",
        "notional_usd": 100.0,
        "spread_exit_cooldown_sec": 60.0,
        "spread_convergence_ratio_pct": 80.0,
        "spread_convergence_target_pct": 0.0,
        "api_key_id": 11 if leg == "A" else 22,
        "sibling_api_key_id": 22 if leg == "A" else 11,
    }


def _register_instance(controller, leg="A", policy="SPREAD_CONVERGENCE_EXIT"):
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
    direction=SignalDirection.LONG, leg="A", policy="SPREAD_CONVERGENCE_EXIT"
):
    return LivePosition(
        symbol=SYMBOL,
        direction=direction,
        entry_price=110.0 if leg == "A" else 100.0,
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
            "hedge_sibling_api_key_id": 22 if leg == "A" else 11,
        },
    )


def _sibling_mark(mark=100.0, direction="SHORT", age_sec=0.0):
    return {
        "mark": mark,
        "qty": 1.0,
        "direction": direction,
        "ts": time.time() - age_sec,
        "api_key_id": 22,
    }


async def _seed_entry_proofs(redis_client, ts=None):
    now = ts if ts is not None else time.time()
    await redis_client.set(
        hm.hedge_entry_key(GROUP, SYMBOL, "A"),
        json.dumps({"qty": 1.0, "price": PRICE_A, "ts": now, "leg": "A"}),
        ex=hm.HEDGE_ENTRY_TTL_SEC,
    )
    await redis_client.set(
        hm.hedge_entry_key(GROUP, SYMBOL, "B"),
        json.dumps({"qty": 1.0, "price": PRICE_B, "ts": now, "leg": "B"}),
        ex=hm.HEDGE_ENTRY_TTL_SEC,
    )


def test_entry_spread_matches_formula():
    assert ENTRY_SPREAD == pytest.approx(
        (110.0 - 100.0) / ((110.0 + 100.0) / 2) * 100.0
    )
    assert ENTRY_SPREAD == pytest.approx(9.5238, abs=1e-3)
    assert TRIGGER_SPREAD == pytest.approx(1.9048, abs=1e-3)


@pytest.mark.asyncio
async def test_convergence_exit_fires_and_closes_both():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_instance(controller, leg="A")
    position = _open_position()
    controller._active_positions["futures_usdtm:BTCUSDT"] = position
    # Own (A) mark narrows to ~0.99% < 20%-of-entry trigger; sibling (B) at 100.
    controller.consumer.get_latest_price = AsyncMock(return_value=101.0)
    await _seed_entry_proofs(redis_client)
    await redis_client.set(
        hm.hedge_mark_key(GROUP, SYMBOL, "B"),
        json.dumps(_sibling_mark(mark=100.0)),
        ex=30,
    )

    await controller._check_hedge_spread_exits()
    await asyncio.sleep(0.2)

    controller.close_position.assert_awaited_once()
    args, _kwargs = controller.close_position.await_args
    assert args[0] == SYMBOL
    assert "HEDGE_CONVERGENCE" in str(args[1])
    controller._publish_hedge_command.assert_awaited_once()
    sent = controller._publish_hedge_command.await_args[0][0]
    assert sent["command"] == "CLOSE_POSITION"
    assert sent["payload"]["api_key_id"] == 22
    assert "HEDGE_CONVERGENCE" in sent["payload"]["reason"]
    # Cooldown armed so the sibling cannot instantly close again.
    assert await redis_client.get(hm.hedge_cooldown_key(GROUP, SYMBOL)) is not None
    # Own exchange mark published for the sibling controller to read.
    own = json.loads(await redis_client.get(hm.hedge_mark_key(GROUP, SYMBOL, "A")))
    assert own["mark"] == pytest.approx(101.0)
    assert own["direction"] == "LONG"
    # Entry spread cached on the position for subsequent ticks.
    assert float(position.signal_details["hedge_entry_spread_pct"]) == pytest.approx(
        ENTRY_SPREAD, abs=1e-4
    )


@pytest.mark.asyncio
async def test_convergence_exit_skips_when_spread_widens():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_instance(controller, leg="A")
    controller._active_positions["futures_usdtm:BTCUSDT"] = _open_position()
    controller.consumer.get_latest_price = AsyncMock(return_value=102.5)
    await _seed_entry_proofs(redis_client)
    await redis_client.set(
        hm.hedge_mark_key(GROUP, SYMBOL, "B"),
        json.dumps(_sibling_mark(mark=100.0)),
        ex=30,
    )

    await controller._check_hedge_spread_exits()

    controller.close_position.assert_not_awaited()
    controller._publish_hedge_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_convergence_exit_uses_absolute_target():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    cfg = _register_instance(controller, leg="A")
    cfg["spread_convergence_ratio_pct"] = 0.0
    cfg["spread_convergence_target_pct"] = 0.5
    controller._active_positions["futures_usdtm:BTCUSDT"] = _open_position()
    controller.consumer.get_latest_price = AsyncMock(return_value=100.5)
    await _seed_entry_proofs(redis_client)
    await redis_client.set(
        hm.hedge_mark_key(GROUP, SYMBOL, "B"),
        json.dumps(_sibling_mark(mark=100.0)),
        ex=30,
    )

    await controller._check_hedge_spread_exits()
    await asyncio.sleep(0.2)

    # current ~0.5% is at the 0.5% absolute target while entry was 9.52%.
    controller.close_position.assert_awaited_once()
    args, _ = controller.close_position.await_args
    assert "HEDGE_CONVERGENCE" in str(args[1])


@pytest.mark.asyncio
async def test_convergence_exit_leg_b_orientation():
    """The mirrored leg measures (A - B) oriented the same way; abs decides."""
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_instance(controller, leg="B")
    position = _open_position(direction=SignalDirection.SHORT, leg="B")
    controller._active_positions["futures_usdtm:BTCUSDT"] = position
    controller.consumer.get_latest_price = AsyncMock(return_value=101.0)
    await _seed_entry_proofs(redis_client)
    await redis_client.set(
        hm.hedge_mark_key(GROUP, SYMBOL, "A"),
        json.dumps(
            {
                "mark": 100.0,
                "qty": 1.0,
                "direction": "LONG",
                "ts": time.time(),
                "api_key_id": 11,
            }
        ),
        ex=30,
    )

    await controller._check_hedge_spread_exits()
    await asyncio.sleep(0.2)

    controller.close_position.assert_awaited_once()
    args, _ = controller.close_position.await_args
    assert "HEDGE_CONVERGENCE" in str(args[1])


@pytest.mark.asyncio
async def test_convergence_exit_skips_missing_entry_proofs():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_instance(controller, leg="A")
    controller._active_positions["futures_usdtm:BTCUSDT"] = _open_position()
    controller.consumer.get_latest_price = AsyncMock(return_value=100.1)
    # No entry proofs at all: data-driven exit stays dormant.
    await redis_client.set(
        hm.hedge_mark_key(GROUP, SYMBOL, "B"),
        json.dumps(_sibling_mark(mark=100.0)),
        ex=30,
    )

    await controller._check_hedge_spread_exits()

    controller.close_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_convergence_exit_skips_stale_entry_proofs():
    """Proofs from a previous cycle (older than the entry window) never fire."""
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_instance(controller, leg="A")
    controller._active_positions["futures_usdtm:BTCUSDT"] = _open_position()
    controller.consumer.get_latest_price = AsyncMock(return_value=100.1)
    await _seed_entry_proofs(redis_client, ts=time.time() - 3600.0)
    await redis_client.set(
        hm.hedge_mark_key(GROUP, SYMBOL, "B"),
        json.dumps(_sibling_mark(mark=100.0)),
        ex=30,
    )

    await controller._check_hedge_spread_exits()

    controller.close_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_convergence_exit_skips_stale_sibling_mark():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_instance(controller, leg="A")
    controller._active_positions["futures_usdtm:BTCUSDT"] = _open_position()
    await _seed_entry_proofs(redis_client)
    await redis_client.set(
        hm.hedge_mark_key(GROUP, SYMBOL, "B"),
        json.dumps(_sibling_mark(mark=100.0, age_sec=30.0)),
        ex=60,
    )

    await controller._check_hedge_spread_exits()

    controller.close_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_convergence_exit_skips_same_direction_sibling():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_instance(controller, leg="A")
    controller._active_positions["futures_usdtm:BTCUSDT"] = _open_position()
    await _seed_entry_proofs(redis_client)
    await redis_client.set(
        hm.hedge_mark_key(GROUP, SYMBOL, "B"),
        json.dumps(_sibling_mark(mark=100.0, direction="LONG")),
        ex=30,
    )

    await controller._check_hedge_spread_exits()

    controller.close_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_convergence_exit_cooldown_blocks():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_instance(controller, leg="A")
    controller._active_positions["futures_usdtm:BTCUSDT"] = _open_position()
    controller.consumer.get_latest_price = AsyncMock(return_value=100.1)
    await _seed_entry_proofs(redis_client)
    await redis_client.set(
        hm.hedge_mark_key(GROUP, SYMBOL, "B"),
        json.dumps(_sibling_mark(mark=100.0)),
        ex=30,
    )
    await redis_client.set(
        hm.hedge_cooldown_key(GROUP, SYMBOL),
        str(time.time() - 10.0),
        ex=300,
    )

    await controller._check_hedge_spread_exits()

    controller.close_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_convergence_own_mark_published_for_sibling():
    """Even without a trigger the leg must keep publishing its mark."""
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_instance(controller, leg="A")
    controller._active_positions["futures_usdtm:BTCUSDT"] = _open_position()
    controller.consumer.get_latest_price = AsyncMock(return_value=102.5)
    await _seed_entry_proofs(redis_client)

    await controller._check_hedge_spread_exits()

    own = json.loads(await redis_client.get(hm.hedge_mark_key(GROUP, SYMBOL, "A")))
    assert own["mark"] == pytest.approx(102.5)
    assert own["direction"] == "LONG"
    assert float(own["ts"]) == pytest.approx(time.time(), abs=5.0)


@pytest.mark.asyncio
async def test_entry_publish_for_convergence_includes_mark_and_direction():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_instance(controller, leg="A")
    controller.consumer.get_latest_price = AsyncMock(return_value=105.0)

    await controller._publish_hedge_entry_event(_open_position(), SYMBOL)

    proof = json.loads(await redis_client.get(hm.hedge_entry_key(GROUP, SYMBOL, "A")))
    assert proof["price"] == pytest.approx(110.0)
    assert proof["mark"] == pytest.approx(105.0)
    assert proof["direction"] == "LONG"
    assert proof["leg"] == "A"


@pytest.mark.asyncio
async def test_entry_publish_skipped_for_other_policies():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_instance(controller, leg="A", policy="RACE_FINAL_MARKET")
    controller.consumer.get_latest_price = AsyncMock(return_value=105.0)

    await controller._publish_hedge_entry_event(
        _open_position(policy="RACE_FINAL_MARKET"), SYMBOL
    )

    assert await redis_client.get(hm.hedge_entry_key(GROUP, SYMBOL, "A")) is None


@pytest.mark.asyncio
async def test_race_fallback_convergence_individual_exit_publishes():
    """A convergence leg must not survive alone after its own TP/SL."""
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    controller._publish_hedge_command = AsyncMock()

    controller._maybe_publish_hedge_race_close(
        _open_position(policy="SPREAD_CONVERGENCE_EXIT"), "TAKE_PROFIT"
    )
    await asyncio.sleep(0.2)

    controller._publish_hedge_command.assert_awaited_once()
    sent = controller._publish_hedge_command.await_args[0][0]
    assert sent["command"] == "CLOSE_POSITION"
    assert sent["payload"]["api_key_id"] == 22


@pytest.mark.asyncio
async def test_race_fallback_skips_convergence_reasons():
    """HEDGE_CONVERGENCE exits never re-broadcast (loop guard)."""
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    controller._publish_hedge_command = AsyncMock()

    controller._maybe_publish_hedge_race_close(
        _open_position(policy="SPREAD_CONVERGENCE_EXIT"),
        f"{hm.HEDGE_CONVERGENCE_REASON_PREFIX}:{GROUP[:8]}",
    )
    await asyncio.sleep(0.2)

    controller._publish_hedge_command.assert_not_awaited()
