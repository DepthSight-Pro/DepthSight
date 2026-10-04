"""Lazy private streams: sibling isolation, demand gating, REST fallback.

One shared loop per (exchange, api_key) replaces one stream per controller
(exchanges cap simultaneous private WS per IP; single-session exchanges kick
the second login). Controllers with no live demand get no stream; fills
arrive via the streamless REST poller instead.
"""

from types import SimpleNamespace
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot_module import config as bot_config
from bot_module import private_stream_registry as reg
from bot_module.controller import TradingController


@pytest.fixture(autouse=True)
def _clean_registry():
    reg.reset_registry()
    yield
    reg.reset_registry()


def _bare_controller(**overrides):
    ctrl = TradingController.__new__(TradingController)
    ctrl.user_id = 7
    ctrl.api_key_id = 4
    ctrl.executors = {}
    ctrl.market_executors = {}
    ctrl._active_positions = {}
    ctrl._private_stream_keys = set()
    ctrl._private_stream_idle_since = None
    ctrl._private_stream_last_poll = 0.0
    ctrl._private_stream_last_open_attempt = 0.0
    for k, v in overrides.items():
        setattr(ctrl, k, v)
    return ctrl


def _live_position(**overrides):
    base = dict(
        mode="live",
        status="OPEN",
        symbol="BTCUSDT",
        market_type="futures_usdtm",
        entry_client_order_id="x-entry-aaa",
        entry_order_id=111,
        current_sl_order_id=None,
        current_sl_client_order_id=None,
        partial_tp_orders=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_sibling_order_detection():
    ctrl = _bare_controller()
    ctrl._active_positions = {"BTCUSDT": _live_position()}
    assert ctrl._is_sibling_order("x-entry-aaa") is False  # mine
    assert ctrl._is_sibling_order("x-entry-bbb") is True  # sibling's
    assert ctrl._is_sibling_order("x-ptp-zzz") is True
    assert ctrl._is_sibling_order("manual-123") is False  # truly manual: process
    assert ctrl._is_sibling_order("x-close-999") is False  # forced closes flow
    assert ctrl._is_sibling_order(None) is False
    assert ctrl._is_sibling_order("") is False


def test_sibling_guard_needs_live_position():
    ctrl = _bare_controller()
    # No positions at all: nothing known, but also nothing to clash with.
    # Our-format cids with no live position are treated as sibling-shaped;
    # the handler returns early on missing position anyway.
    assert ctrl._is_sibling_order("x-entry-aaa") is True


def test_demand_gate():
    ctrl = _bare_controller()
    assert ctrl._live_stream_demand() is False
    ctrl._active_positions = {"BTCUSDT": _live_position(status="OPEN")}
    assert ctrl._live_stream_demand() is True
    ctrl._active_positions = {"BTCUSDT": _live_position(status="CLOSED")}
    assert ctrl._live_stream_demand() is False
    ctrl._active_positions = {"BTCUSDT": _live_position(mode="paper")}
    assert ctrl._live_stream_demand() is False
    ctrl._active_positions = {"BTCUSDT": _live_position(status="PENDING_ENTRY")}
    assert ctrl._live_stream_demand() is True


def test_stream_policy(monkeypatch):
    ctrl = _bare_controller()
    monkeypatch.setattr(bot_config, "PRIVATE_WS_MODE", "auto")
    monkeypatch.setattr(bot_config, "PRIVATE_WS_POLL_ONLY_EXCHANGES", {"weex"})
    assert ctrl._private_stream_policy("bitget") == "stream"
    assert ctrl._private_stream_policy("weex") == "poll"
    monkeypatch.setattr(bot_config, "PRIVATE_WS_MODE", "never")
    assert ctrl._private_stream_policy("bitget") == "poll"
    monkeypatch.setattr(bot_config, "PRIVATE_WS_MODE", "always")
    assert ctrl._private_stream_policy("weex") == "stream"


@pytest.mark.asyncio
async def test_ensure_skips_poll_only_and_kill_switch(monkeypatch):
    from unittest.mock import patch as upatch

    ctrl = _bare_controller()
    monkeypatch.setattr(bot_config, "PRIVATE_WS_POLL_ONLY_EXCHANGES", {"weex"})
    monkeypatch.setattr(bot_config, "PRIVATE_WS_MODE", "auto")
    with upatch.object(reg, "ensure_stream", AsyncMock(return_value=True)) as ens:
        # Fake a weex executor needing a stream.
        ex = MagicMock()
        ex.exchange_id = "weex"
        ex.api_key = "K"
        ctrl.executors = {"live": ex}
        ctrl._active_positions = {"BTCUSDT": _live_position()}
        assert await ctrl._ensure_private_streams() is True  # poller covers
        ens.assert_not_awaited()

    monkeypatch.setattr(bot_config, "PRIVATE_WS_MODE", "never")
    with upatch.object(reg, "ensure_stream", AsyncMock(return_value=True)) as ens:
        assert await ctrl._ensure_private_streams() is True
        ens.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_opens_and_tracks_key(monkeypatch):
    from unittest.mock import patch as upatch

    ctrl = _bare_controller()
    monkeypatch.setattr(bot_config, "PRIVATE_WS_MODE", "auto")
    monkeypatch.setattr(bot_config, "PRIVATE_WS_POLL_ONLY_EXCHANGES", set())
    ex = MagicMock()
    ex.exchange_id = "bitget"
    ex.api_key = "K"
    ctrl.executors = {"live": ex}
    with upatch.object(reg, "ensure_stream", AsyncMock(return_value=True)) as ens:
        assert await ctrl._ensure_private_streams() is True
        ens.assert_awaited_once()
    assert ("bitget", "K") in ctrl._private_stream_keys


@pytest.mark.asyncio
async def test_reaper_releases_after_idle(monkeypatch):
    from unittest.mock import patch as upatch

    ctrl = _bare_controller()
    ctrl._private_stream_keys = {("bitget", "K")}
    # No live positions -> no demand.
    with upatch.object(reg, "release_stream", AsyncMock()) as rel:
        await ctrl._private_stream_reaper_tick(1000.0)
        rel.assert_not_awaited()  # first tick only arms the idle timer
        await ctrl._private_stream_reaper_tick(1000.0 + 60)
        rel.assert_not_awaited()  # 60s < default 300s timeout
        await ctrl._private_stream_reaper_tick(1000.0 + 301)
        rel.assert_awaited_once_with("bitget", "K", (7, 4))
    assert ctrl._private_stream_keys == set()


@pytest.mark.asyncio
async def test_streamless_poll_delivers_missing_fill(monkeypatch):
    ctrl = _bare_controller()
    monkeypatch.setattr(bot_config, "PRIVATE_WS_POLL_INTERVAL_SECONDS", 15.0)
    monkeypatch.setattr(bot_config, "PRIVATE_WS_POLL_JITTER_SECONDS", 0.0)

    fill_event = {"e": "ORDER_TRADE_UPDATE", "o": {"c": "x-ptp-abc", "X": "FILLED"}}
    executor = MagicMock()
    executor.get_open_orders = AsyncMock(return_value=[])
    executor.get_open_algo_orders = AsyncMock(return_value=[])
    executor.fetch_order_event = AsyncMock(return_value=fill_event)
    ctrl._executor_for_market_type = MagicMock(return_value=executor)
    ctrl._handle_order_update = AsyncMock()

    tp = SimpleNamespace(status="NEW", order_id=123, client_order_id="x-ptp-abc")
    ctrl._active_positions = {
        "BTCUSDT": _live_position(partial_tp_orders=[tp]),
    }

    delivered = await ctrl._streamless_poll_once()
    assert delivered == 1
    ctrl._handle_order_update.assert_awaited_once_with(fill_event)
    executor.fetch_order_event.assert_awaited_once_with("BTCUSDT", "123")


@pytest.mark.asyncio
async def test_streamless_poll_skips_open_orders():
    ctrl = _bare_controller()
    executor = MagicMock()
    executor.get_open_orders = AsyncMock(return_value=[{"clientOrderId": "x-ptp-abc"}])
    executor.get_open_algo_orders = AsyncMock(return_value=[])
    executor.fetch_order_event = AsyncMock()
    ctrl._executor_for_market_type = MagicMock(return_value=executor)
    ctrl._handle_order_update = AsyncMock()

    tp = SimpleNamespace(status="NEW", order_id=123, client_order_id="x-ptp-abc")
    ctrl._active_positions = {
        "BTCUSDT": _live_position(partial_tp_orders=[tp]),
    }

    assert await ctrl._streamless_poll_once() == 0
    ctrl._handle_order_update.assert_not_awaited()
    executor.fetch_order_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_streamless_poll_tick_throttles(monkeypatch):
    ctrl = _bare_controller()
    monkeypatch.setattr(bot_config, "PRIVATE_WS_POLL_INTERVAL_SECONDS", 60.0)
    monkeypatch.setattr(bot_config, "PRIVATE_WS_POLL_JITTER_SECONDS", 0.0)
    ctrl._active_positions = {"BTCUSDT": _live_position()}
    ctrl._stream_executors = MagicMock(return_value=[])
    ctrl._streamless_poll_once = AsyncMock(return_value=0)

    await ctrl._streamless_poll_tick(1000.0)
    ctrl._streamless_poll_once.assert_awaited_once()
    # Second tick inside the interval: skipped.
    await ctrl._streamless_poll_tick(1001.0)
    assert ctrl._streamless_poll_once.await_count == 1


def _stale_kline_df(hours_old=72, periods=30):
    from datetime import datetime, timezone as _tz

    import pandas as pd

    end = datetime.now(_tz.utc) - timedelta(hours=hours_old)
    idx = pd.date_range(end=end, periods=periods, freq="1h", tz="UTC")
    return pd.DataFrame({"close": [100.0] * periods}, index=idx)


def _fresh_kline_df(periods=30):
    from datetime import datetime, timezone as _tz

    import pandas as pd

    end = datetime.now(_tz.utc)
    idx = pd.date_range(end=end, periods=periods, freq="1h", tz="UTC")
    return pd.DataFrame({"close": [100.0] * periods}, index=idx)


@pytest.mark.asyncio
async def test_history_watchdog_backfills_stale_key(monkeypatch):
    """Watchdog WARNING-alerts and force backfills a silently dead channel."""

    from bot_module import data_consumer as dc_module

    key = "bitget:futures_usdtm:TSTW1USDT@kline_1h"
    cache_key = dc_module._kline_cache_key("TSTW1USDT", "1h", "bitget", "futures_usdtm")
    dc_module._global_kline_df_cache[cache_key] = _stale_kline_df()
    try:
        consumer = SimpleNamespace(
            _redis_market_stream_keys={key},
            _ensure_history_loaded=AsyncMock(return_value=True),
        )
        ctrl = _bare_controller(consumer=consumer)
        monkeypatch.setattr(bot_config, "HISTORY_WATCHDOG_INTERVAL_SECONDS", 60.0)

        await ctrl._history_watchdog_tick(100000.0)
        consumer._ensure_history_loaded.assert_awaited_once()
        _, kwargs = consumer._ensure_history_loaded.call_args
        assert (
            kwargs.get("force", False) is True
            or consumer._ensure_history_loaded.call_args.args[5] is True
        )

        # Second tick inside the interval: throttled, no second backfill.
        await ctrl._history_watchdog_tick(100001.0)
        assert consumer._ensure_history_loaded.await_count == 1
    finally:
        dc_module._global_kline_df_cache.pop(cache_key, None)


@pytest.mark.asyncio
async def test_history_watchdog_silent_when_fresh(monkeypatch):
    """Fresh keys produce no backfill traffic at all."""
    from bot_module import data_consumer as dc_module

    key = "bitget:futures_usdtm:TSTW2USDT@kline_1h"
    cache_key = dc_module._kline_cache_key("TSTW2USDT", "1h", "bitget", "futures_usdtm")
    dc_module._global_kline_df_cache[cache_key] = _fresh_kline_df()
    try:
        consumer = SimpleNamespace(
            _redis_market_stream_keys={key},
            _ensure_history_loaded=AsyncMock(return_value=True),
        )
        ctrl = _bare_controller(consumer=consumer)
        monkeypatch.setattr(bot_config, "HISTORY_WATCHDOG_INTERVAL_SECONDS", 60.0)

        await ctrl._history_watchdog_tick(100000.0)
        consumer._ensure_history_loaded.assert_not_awaited()
    finally:
        dc_module._global_kline_df_cache.pop(cache_key, None)


@pytest.mark.asyncio
async def test_gather_staleness_triggers_backfill():
    """A stale-but-fat cache must re-ensure (not just row-count trigger)."""
    stale = _stale_kline_df()
    fresh = _fresh_kline_df()
    consumer = SimpleNamespace(
        get_kline_history=AsyncMock(side_effect=[stale, fresh]),
        _ensure_history_loaded=AsyncMock(return_value=True),
    )
    ctrl = _bare_controller(consumer=consumer)

    out = await ctrl._gather_market_data_for_required_keys(
        "TSTW3USDT", {"kline_1h"}, "test", market_type="futures_usdtm"
    )
    assert out is not None
    assert out["kline_1h"] is fresh
    consumer._ensure_history_loaded.assert_awaited_once()
