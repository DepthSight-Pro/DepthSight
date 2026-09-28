# tests/test_hedge_sync_step.py
"""SYNC_STEP exact-volume mode: quantization, entry verify, watchdog."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot_module import hedge_mirror as hm
from bot_module.controller import LivePosition, TradingController
from bot_module.datatypes import OrderMode, SignalDirection, StrategySignal

GROUP = "syncgrp1"
SYMBOL = "XRPUSDT"


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
    controller._hedge_paired_positions = set()
    controller.trade_logger = MagicMock()
    controller.trade_logger.log_event = MagicMock()
    controller.close_position = AsyncMock()
    controller._publish_hedge_command = AsyncMock()
    return controller


def _sync_hedge(leg="A", **overrides):
    cfg = {
        "enabled": True,
        "group_id": GROUP,
        "leg": leg,
        "invert": leg == "B",
        "side_mode": "OPPOSITE",
        "exit_policy": "INDEPENDENT",
        "size_mode": "SYNC_STEP",
        "notional_usd": 20.0,
        "qty_steps": {SYMBOL: 10.0},
        "entry_sync_timeout_sec": 120.0,
        "api_key_id": 11 if leg == "A" else 22,
        "sibling_api_key_id": 22 if leg == "A" else 11,
    }
    cfg.update(overrides)
    return cfg


def _register_sync_instance(controller, leg="A", **overrides):
    cfg = _sync_hedge(leg=leg, **overrides)
    controller.running_strategy_instances[f"cfg-1:{leg.lower()}"] = (
        MagicMock(),
        {
            "id": f"cfg-1:{leg.lower()}",
            "config_id": "cfg-1",
            "user_id": 1,
            "symbols": [SYMBOL],
            "symbol_selection_mode": "STATIC",
            "config_data": {"hedge": cfg},
        },
    )
    return cfg


def _sync_signal():
    return StrategySignal(
        strategy_name="TestStrategy",
        symbol=SYMBOL,
        direction=SignalDirection.LONG,
        stop_loss=1.50,
        take_profit=1.60,
        mode=OrderMode.MARKET,
        trigger_price=1.543,
        details={},
    )


def _sync_position(qty=10.0, entry_age_sec=0.0, entry_cid="test-entry-1"):
    return LivePosition(
        symbol=SYMBOL,
        direction=SignalDirection.LONG,
        entry_price=1.543,
        initial_quantity=qty,
        remaining_quantity=qty,
        entry_time=time.time() - entry_age_sec,
        strategy="TestStrategy",
        status="OPEN",
        config_id="cfg-1",
        user_id=1,
        api_key_id=11,
        market_type="futures_usdtm",
        entry_client_order_id=entry_cid,
        signal_details={
            "hedge_group_id": GROUP,
            "hedge_leg": "A",
            "hedge_exit_policy": "INDEPENDENT",
            "hedge_size_mode": "SYNC_STEP",
            "hedge_sibling_api_key_id": 22,
        },
    )


def _running_config(leg="A", **overrides):
    return {"config_data": {"hedge": _sync_hedge(leg=leg, **overrides)}}


@pytest.mark.asyncio
async def test_sync_quantize_applied():
    import fakeredis.aioredis

    controller = _bare_controller(fakeredis.aioredis.FakeRedis())
    out = await controller._apply_hedge_sync_step(
        signal=_sync_signal(),
        approved_qty=12.96,
        lot_params={"stepSize": "10", "minQty": "10", "maxQty": "1000"},
        running_instance_config=_running_config(),
        log_prefix="[Test]",
        market_type="futures_usdtm",
    )
    assert out == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_sync_quantize_fine_own_step():
    import fakeredis.aioredis

    controller = _bare_controller(fakeredis.aioredis.FakeRedis())
    out = await controller._apply_hedge_sync_step(
        signal=_sync_signal(),
        approved_qty=12.96,
        lot_params={"stepSize": "0.001", "minQty": "0.001", "maxQty": "100000"},
        running_instance_config=_running_config(),
        log_prefix="[Test]",
        market_type="futures_usdtm",
    )
    assert out == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_sync_abort_cancels_sibling():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    out = await controller._apply_hedge_sync_step(
        signal=_sync_signal(),
        approved_qty=5.0,  # rounds to zero on step 10
        lot_params={"stepSize": "10", "minQty": "10", "maxQty": "1000"},
        running_instance_config=_running_config(),
        log_prefix="[Test]",
        market_type="futures_usdtm",
    )
    assert out == 0.0
    controller._publish_hedge_command.assert_awaited_once()
    sent = controller._publish_hedge_command.await_args[0][0]
    assert sent["payload"]["api_key_id"] == 22
    assert "HEDGE_SYNC_FAIL" in sent["payload"]["reason"]


@pytest.mark.asyncio
async def test_sync_abort_below_own_min():
    import fakeredis.aioredis

    controller = _bare_controller(fakeredis.aioredis.FakeRedis())
    out = await controller._apply_hedge_sync_step(
        signal=_sync_signal(),
        approved_qty=12.0,
        lot_params={"stepSize": "1", "minQty": "20", "maxQty": "1000"},
        running_instance_config=_running_config(),
        log_prefix="[Test]",
        market_type="futures_usdtm",
    )
    assert out == 0.0


@pytest.mark.asyncio
async def test_sync_passthrough_non_sync_leg():
    import fakeredis.aioredis

    controller = _bare_controller(fakeredis.aioredis.FakeRedis())
    cfg = _sync_hedge()
    cfg["size_mode"] = "FIXED_NOTIONAL"
    out = await controller._apply_hedge_sync_step(
        signal=_sync_signal(),
        approved_qty=12.96,
        lot_params={"stepSize": "1", "minQty": "1", "maxQty": "1000"},
        running_instance_config={"config_data": {"hedge": cfg}},
        log_prefix="[Test]",
        market_type="futures_usdtm",
    )
    assert out is None


@pytest.mark.asyncio
async def test_entry_publish_and_matching_verify():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_sync_instance(controller, leg="A")
    pos = _sync_position(qty=10.0)
    controller._active_positions["futures_usdtm:XRPUSDT"] = pos

    await controller._publish_hedge_entry_event(pos, SYMBOL)
    own = json.loads(await redis_client.get(hm.hedge_entry_key(GROUP, SYMBOL, "A")))
    assert own["qty"] == pytest.approx(10.0)

    # Sibling filled the identical volume -> silence.
    await redis_client.set(
        hm.hedge_entry_key(GROUP, SYMBOL, "B"),
        json.dumps({"qty": 10.0, "ts": time.time()}),
        ex=600,
    )
    await controller._verify_hedge_entry_sync(pos, SYMBOL)
    controller.close_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_entry_mismatch_closes_both():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_sync_instance(controller, leg="A")
    pos = _sync_position(qty=10.0)
    controller._active_positions["futures_usdtm:XRPUSDT"] = pos
    await redis_client.set(
        hm.hedge_entry_key(GROUP, SYMBOL, "B"),
        json.dumps({"qty": 12.0, "ts": time.time()}),
        ex=600,
    )

    await controller._verify_hedge_entry_sync(pos, SYMBOL)
    await asyncio.sleep(0.2)

    controller.close_position.assert_awaited_once()
    args, _kwargs = controller.close_position.await_args
    assert args[0] == SYMBOL
    assert "HEDGE_SYNC_FAIL" in str(args[1])
    controller._publish_hedge_command.assert_awaited_once()


@pytest.mark.asyncio
async def test_watchdog_closes_lone_leg():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_sync_instance(controller, leg="A")
    pos = _sync_position(qty=10.0, entry_age_sec=300.0)
    controller._active_positions["futures_usdtm:XRPUSDT"] = pos

    await controller._check_hedge_entry_sync()
    await asyncio.sleep(0.2)

    controller.close_position.assert_awaited_once()


@pytest.mark.asyncio
async def test_watchdog_ignores_fresh_and_paired_legs():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_sync_instance(controller, leg="A")

    fresh = _sync_position(qty=10.0, entry_age_sec=5.0)
    controller._active_positions["futures_usdtm:XRPUSDT"] = fresh
    await controller._check_hedge_entry_sync()
    await asyncio.sleep(0.1)
    controller.close_position.assert_not_awaited()

    # Paired (sibling entry within window) even when old.
    old = _sync_position(qty=10.0, entry_age_sec=300.0)
    controller._active_positions["futures_usdtm:XRPUSDT"] = old
    await redis_client.set(
        hm.hedge_entry_key(GROUP, SYMBOL, "B"),
        json.dumps({"qty": 10.0, "ts": time.time() - 240.0}),
        ex=600,
    )
    await controller._check_hedge_entry_sync()
    await asyncio.sleep(0.1)
    controller.close_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_watchdog_disabled_by_zero_timeout():
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_sync_instance(controller, leg="A", entry_sync_timeout_sec=0.0)
    pos = _sync_position(qty=10.0, entry_age_sec=900.0)
    controller._active_positions["futures_usdtm:XRPUSDT"] = pos

    await controller._check_hedge_entry_sync()
    await asyncio.sleep(0.1)

    controller.close_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_watchdog_skips_latched_paired_leg():
    """A paired leg survives even after the sibling entry proof expires."""
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_sync_instance(controller, leg="A")
    pos = _sync_position(qty=10.0, entry_age_sec=900.0)
    controller._active_positions["futures_usdtm:XRPUSDT"] = pos
    controller._hedge_paired_positions.add("test-entry-1")

    await controller._check_hedge_entry_sync()
    await asyncio.sleep(0.1)

    controller.close_position.assert_not_awaited()


@pytest.mark.asyncio
async def test_watchdog_latches_on_fresh_sibling():
    """Seeing a fresh sibling entry latches the pair for its lifetime."""
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    controller = _bare_controller(redis_client)
    _register_sync_instance(controller, leg="A")
    pos = _sync_position(qty=10.0, entry_age_sec=300.0)
    controller._active_positions["futures_usdtm:XRPUSDT"] = pos
    await redis_client.set(
        hm.hedge_entry_key(GROUP, SYMBOL, "B"),
        json.dumps({"qty": 10.0, "ts": time.time() - 240.0}),
        ex=600,
    )

    await controller._check_hedge_entry_sync()
    assert "test-entry-1" in controller._hedge_paired_positions

    # Proof expires afterwards: the latched leg still survives.
    await redis_client.delete(hm.hedge_entry_key(GROUP, SYMBOL, "B"))
    await controller._check_hedge_entry_sync()
    await asyncio.sleep(0.1)

    controller.close_position.assert_not_awaited()
