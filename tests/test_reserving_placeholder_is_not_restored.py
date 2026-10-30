# File: tests/test_reserving_placeholder_is_not_restored.py
"""
A `RESERVING` position is an in-process mutex and must never outlive its process.
"""

import asyncio
import logging
import pytest

from bot_module.controller import LivePosition, TradingController

from .test_paper_exit_orders_survive_restart import (
    SYMBOL,
    USER_ID,
    _build_controller,
)

MARKET_TYPE = "futures_usdtm"


def _persisted_reserving_position() -> LivePosition:
    """A placeholder exactly as `_process_signal` creates it (controller.py:7862)."""
    from .test_paper_exit_orders_survive_restart import _persisted_position

    position = _persisted_position(
        entry_price=0.0,
        initial_quantity=0.0,
        remaining_quantity=0.0,
        status="RESERVING",
        client_order_id="RESERVE_1759848636000",
    )
    return position


def _snapshot(position: LivePosition) -> dict:
    """Serialised through the REAL producer, `LivePosition.to_dict`."""
    return {
        "serialization_format": "json",
        "timestamp": 1759848636.0,
        "monitored_symbols": [SYMBOL],
        "closing_managed_symbols": [],
        "last_known_symbols": [SYMBOL],
        "currently_managed_symbols": [SYMBOL],
        "active_positions": {f"paper:{SYMBOL}": position.to_dict()},
    }


@pytest.mark.asyncio
async def test_reserving_placeholder_is_not_restored_from_redis():
    """The core regression: a RESERVING record must not come back on startup."""
    controller, _, _ = _build_controller(_persisted_reserving_position())

    snapshot = controller.redis_client._snapshot
    raw = snapshot["active_positions"]
    assert any(
        v.get("status") == "RESERVING" for v in raw.values()
    ), f"test setup is wrong: no RESERVING record in {raw}"

    await controller._load_runtime_state()

    restored = controller._active_position_get(SYMBOL, MARKET_TYPE)
    assert restored is None, (
        f"A RESERVING placeholder was restored from Redis. It belongs to a "
        f"process that no longer exists, so nothing will ever release it: "
        f"{SYMBOL} is now blocked from trading permanently, is invisible to "
        f"/api/v1/positions, and consumes a max_concurrent_trades slot. "
        f"Restored record: status={getattr(restored, 'status', None)!r}"
    )


@pytest.mark.asyncio
async def test_discarded_reservation_is_reported_loudly(caplog):
    """Silently dropping it would hide a real stuck symbol."""
    controller, _, _ = _build_controller(_persisted_reserving_position())

    logging.getLogger("bot_module").propagate = True
    with caplog.at_level(logging.WARNING):
        await controller._load_runtime_state()

    warnings = [r for r in caplog.records if r.levelno >= 30]
    assert any("RESERVING" in r.getMessage() for r in warnings), (
        "Discarding a stuck reservation must be logged at WARNING or above. "
        f"Got: {[r.getMessage() for r in warnings]}"
    )


@pytest.mark.asyncio
async def test_resaving_state_does_not_persist_a_reservation():
    """Defence in depth: stop writing them in the first place."""
    controller, _, _ = _build_controller(_persisted_reserving_position())

    controller.symbol_selection_config = None
    snapshot_before = controller.redis_client._snapshot

    await controller._load_runtime_state()
    leaked = _persisted_reserving_position()
    async with controller._positions_dict_lock:
        controller._active_position_set(leaked)

    await controller._save_runtime_state()

    assert controller.redis_client._snapshot is not snapshot_before, (
        "_save_runtime_state did not write anything -- it probably raised and "
        "logged. A no-op save would make the assertion below vacuous."
    )
    assert (
        controller.redis_client._snapshot["serialization_format"] == "json"
        and "active_positions" in controller.redis_client._snapshot
    ), f"unexpected snapshot shape: {controller.redis_client._snapshot}"

    written = controller.redis_client._snapshot["active_positions"]
    assert not any(
        v.get("status") == "RESERVING" for v in written.values()
    ), (
        f"_save_runtime_state persisted a RESERVING placeholder: {written}. "
        f"It must be filtered out, or the record comes back on every restart."
    )


@pytest.mark.asyncio
async def test_a_real_open_position_still_restores():
    """The filter must not become a blunt instrument."""
    from .test_paper_exit_orders_survive_restart import _persisted_position

    controller, _, _ = _build_controller(_persisted_position())

    await controller._load_runtime_state()

    restored = controller._active_position_get(SYMBOL, MARKET_TYPE)
    assert restored is not None, (
        "A real OPEN position failed to restore. Dropping RESERVING must not "
        "cost us genuine position recovery across restarts."
    )
    assert restored.status == "OPEN"
    assert (restored.remaining_quantity or 0.0) > 0

