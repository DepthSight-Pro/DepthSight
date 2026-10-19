"""Event-loop backpressure: tracked task set, hard in-flight cap, dedupe.

The 2026-10-17 night run piled ~300 pending HandleEvent_CANDLE_CLOSE tasks
per controller (24-25k per shard): _run_main_loop spawned a fire-and-forget
task per queued event, so a saturated handler (60s asyncpg connect timeouts)
let the pile grow without bound and starved the event loop into a DB-wide
timeout storm. These tests pin the replacement behavior:

- duplicate CANDLE_CLOSE redeliveries collapse to one handler run
- distinct candles/ticks are never dropped, only delayed by the cap
- the in-flight task set never exceeds MAX_INFLIGHT_EVENT_TASKS
- loop shutdown cancels and awaits all pending handler tasks
- handler exceptions are surfaced and their bookkeeping is released
"""

import asyncio
import time

import pytest

from bot_module.controller import TradingController


class _LoopHarness(TradingController):
    """TradingController exposing only what _run_main_loop touches.

    Bypasses the heavyweight real __init__ (DB sessions, executors, model
    pipeline); the methods under test are taken from the real class.
    """

    def __init__(self, max_inflight=4, handler_delay=0.02):
        self.loop = asyncio.get_running_loop()
        self.event_queue = asyncio.Queue(maxsize=1000)
        self._event_handler_semaphore = asyncio.Semaphore(64)
        self._max_inflight_events = max_inflight
        self._event_tasks = set()
        self._event_task_dedupe_keys = {}
        self._inflight_event_keys = set()
        self._running = True
        self.user_id = 1
        self.handler_delay = handler_delay
        self.raise_in_handler = False
        self.handled = []
        self.inflight_seen = []

    async def _run_periodic_tasks(self):
        try:
            while self._running:
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            pass

    async def _handle_event(self, event):
        # The task is already in the set when the handler starts, so the
        # recorded length includes itself: cap violations show up as > cap.
        self.inflight_seen.append(len(self._event_tasks))
        self.handled.append(event)
        if self.raise_in_handler:
            raise RuntimeError("boom")
        await asyncio.sleep(self.handler_delay)


def _candle(ts, symbol="BTCUSDT", timeframe="1m"):
    return {
        "type": "CANDLE_CLOSE",
        "symbol": symbol,
        "timeframe": timeframe,
        "market_type": "futures_usdtm",
        "timestamp_ms": ts,
    }


def _tick(price, symbol="BTCUSDT"):
    return {
        "type": "TICK",
        "symbol": symbol,
        "price": price,
        "market_type": "futures_usdtm",
    }


@pytest.fixture
def harness_factory():
    async def _make(**kwargs):
        return _LoopHarness(**kwargs)

    return _make


async def _stop(harness, loop_task):
    harness._running = False
    loop_task.cancel()
    await asyncio.gather(loop_task, return_exceptions=True)
    for task in asyncio.all_tasks():
        if task.get_name() == "ControllerPeriodicTasks":
            task.cancel()
    await asyncio.sleep(0)


async def _run_until_idle(harness, timeout=5.0):
    """Run the real main loop until the queue and task set drain."""
    harness._running = True
    loop_task = harness.loop.create_task(harness._run_main_loop())
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if harness.event_queue.empty() and not harness._event_tasks:
            break
        await asyncio.sleep(0.01)
    await _stop(harness, loop_task)


async def test_duplicate_candle_redeliveries_collapse(harness_factory):
    harness = await harness_factory(max_inflight=8, handler_delay=0.05)
    for _ in range(50):
        harness.event_queue.put_nowait(_candle(ts=1000))
    await _run_until_idle(harness)
    assert len(harness.handled) == 1
    assert harness.handled[0]["timestamp_ms"] == 1000


async def test_distinct_candles_are_not_dropped(harness_factory):
    harness = await harness_factory(max_inflight=8)
    for ts in (1000, 1100):
        harness.event_queue.put_nowait(_candle(ts))
    await _run_until_idle(harness)
    assert sorted(e["timestamp_ms"] for e in harness.handled) == [1000, 1100]


async def test_candle_key_released_after_handler_completes(harness_factory):
    harness = await harness_factory(max_inflight=4, handler_delay=0.01)
    harness.event_queue.put_nowait(_candle(1000))
    await _run_until_idle(harness)
    assert len(harness.handled) == 1
    # The dedupe key must not leak: a later redelivery (after completion) is
    # handled again instead of being dropped forever.
    assert harness._inflight_event_keys == set()
    harness.event_queue.put_nowait(_candle(1000))
    await _run_until_idle(harness)
    assert len(harness.handled) == 2


async def test_inflight_cap_is_enforced_without_losing_ticks(harness_factory):
    harness = await harness_factory(max_inflight=4, handler_delay=0.02)
    for i in range(20):
        harness.event_queue.put_nowait(_tick(price=100.0 + i))
    await _run_until_idle(harness)
    assert len(harness.handled) == 20
    assert max(harness.inflight_seen) <= 4


async def test_shutdown_cancels_pending_event_tasks(harness_factory):
    harness = await harness_factory(max_inflight=4, handler_delay=5.0)
    for i in range(10):
        harness.event_queue.put_nowait(_tick(price=i))
    loop_task = harness.loop.create_task(harness._run_main_loop())
    await asyncio.sleep(0.05)
    await _stop(harness, loop_task)
    assert harness._event_tasks == set()
    leftover = [
        t for t in asyncio.all_tasks() if t.get_name().startswith("HandleEvent_")
    ]
    assert leftover == []


async def test_handler_exception_is_surfaced_and_released(harness_factory):
    import logging

    # The bot_module logger has propagate=False (dedicated handlers), so
    # caplog (root-attached) cannot see it; capture on the logger itself.
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    capture = _Capture()
    target = logging.getLogger("bot_module")
    target.addHandler(capture)
    try:
        harness = await harness_factory(max_inflight=4)
        harness.raise_in_handler = True
        harness.event_queue.put_nowait(_tick(price=1))
        await _run_until_idle(harness)
    finally:
        target.removeHandler(capture)
    assert any("Unhandled error in event handler" in r.getMessage() for r in records)
    assert harness._event_tasks == set()
