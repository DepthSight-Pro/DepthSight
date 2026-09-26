# tests/test_kline_freshness.py
"""Kline history recency: never evaluate or serve stale caches as current.

Covers the 2026-09-26 incident (4-day-old HTF snapshot evaluated and traded
on right after resubscribe):
- is_kline_fresh / parse_timeframe_minutes unit behavior,
- _ensure_history_loaded re-downloads stale caches instead of trusting count,
- _apply_market_snapshot rejects stale snapshots without clobbering local data.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from bot_module import data_consumer as dc_module
from bot_module.controller import TradingController
from bot_module.data_consumer import (
    DataConsumer,
    is_kline_fresh,
    parse_timeframe_minutes,
)


def _df_ending_at(end: datetime, n: int = 60, freq: str = "15min") -> pd.DataFrame:
    idx = pd.date_range(end=end, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 10.0,
        },
        index=idx,
    )


def test_parse_timeframe_minutes():
    assert parse_timeframe_minutes("1m") == 1
    assert parse_timeframe_minutes("15m") == 15
    assert parse_timeframe_minutes("1h") == 60
    assert parse_timeframe_minutes("4h") == 240
    assert parse_timeframe_minutes("1d") == 1440
    assert parse_timeframe_minutes("1w") == 10080
    assert parse_timeframe_minutes("15M") == 15
    assert parse_timeframe_minutes("bogus") is None
    assert parse_timeframe_minutes(None) is None
    assert parse_timeframe_minutes("") is None


def test_is_kline_fresh_recent():
    now = datetime.now(timezone.utc)
    df = _df_ending_at(now - timedelta(minutes=5))
    fresh, age = is_kline_fresh(df, "15m")
    assert fresh is True
    assert isinstance(age, str)


def test_is_kline_fresh_stale():
    now = datetime.now(timezone.utc)
    df = _df_ending_at(now - timedelta(days=4, hours=2))
    fresh, age = is_kline_fresh(df, "15m")
    assert fresh is False
    assert "4d" in age


def test_is_kline_fresh_boundary():
    # Limit is 3x timeframe by default: 45m for 15m.
    now = datetime.now(timezone.utc)
    assert is_kline_fresh(_df_ending_at(now - timedelta(minutes=44)), "15m")[0] is True
    assert is_kline_fresh(_df_ending_at(now - timedelta(minutes=46)), "15m")[0] is False


def test_is_kline_fresh_degenerate():
    assert is_kline_fresh(None, "15m") == (False, "empty or unreadable history")
    assert is_kline_fresh(pd.DataFrame(), "15m")[0] is False
    # Unknown timeframe or naive index: cannot judge -> fresh (fail-open here,
    # fail-closed happens at evaluation via explicit checks).
    assert is_kline_fresh(_df_ending_at(datetime.now(timezone.utc)), "3x")[0] is True
    naive = _df_ending_at(datetime.now(timezone.utc))
    naive.index = naive.index.tz_localize(None)
    assert is_kline_fresh(naive, "15m")[0] is True


@pytest.fixture
def clean_kline_globals():
    saved_cache = dict(dc_module._global_kline_cache)
    saved_df = dict(dc_module._global_kline_df_cache)
    saved_keys = set(dc_module._global_history_loaded_keys)
    saved_tasks = dict(dc_module._global_history_download_tasks)
    saved_pairs = dict(dc_module._global_active_pairs)
    yield
    dc_module._global_kline_cache.clear()
    dc_module._global_kline_cache.update(saved_cache)
    dc_module._global_kline_df_cache.clear()
    dc_module._global_kline_df_cache.update(saved_df)
    dc_module._global_history_loaded_keys.clear()
    dc_module._global_history_loaded_keys.update(saved_keys)
    dc_module._global_history_download_tasks.clear()
    dc_module._global_history_download_tasks.update(saved_tasks)
    dc_module._global_active_pairs.clear()
    dc_module._global_active_pairs.update(saved_pairs)


def _consumer():
    executor = SimpleNamespace(
        exchange_id="bitget", market_type="futures_usdtm", sandbox=False
    )
    return DataConsumer(
        loop=asyncio.get_running_loop(),
        executor=executor,
        market_data_mode="direct",
    )


def _seed_cache(symbol, timeframe, end, n=60, exchange="bitget"):
    now_ms = int(end.timestamp() * 1000)
    step_ms = {"1m": 60000, "15m": 900000, "1h": 3600000}[timeframe]
    rows = [
        (now_ms - (n - 1 - i) * step_ms, 100.0, 101.0, 99.0, 100.5, 10.0)
        for i in range(n)
    ]
    cache_key = dc_module._kline_cache_key(symbol, timeframe, exchange, "futures_usdtm")
    dc_module._global_kline_cache[cache_key].extend(rows)
    dc_module._global_kline_df_cache[cache_key] = (
        dc_module._build_kline_dataframe_from_cache_rows(rows)
    )
    dc_module._global_history_loaded_keys.add(cache_key)
    return cache_key


@pytest.mark.asyncio
async def test_ensure_redownloads_stale_cache(clean_kline_globals, monkeypatch):
    """Stale-but-full cache must trigger a download, not short-circuit True."""
    now = datetime.now(timezone.utc)
    cache_key = _seed_cache("ZECUSDT", "15m", now - timedelta(days=4, hours=2), n=60)
    consumer = _consumer()
    download = AsyncMock()
    monkeypatch.setattr(consumer, "_download_initial_kline_history_for_key", download)
    result = await consumer._ensure_history_loaded(
        "kline_15m", "ZECUSDT", "15m", "futures_usdtm", "bitget"
    )
    assert download.await_count == 1
    assert result is False
    assert cache_key in dc_module._global_kline_cache


@pytest.mark.asyncio
async def test_ensure_keeps_fresh_cache(clean_kline_globals, monkeypatch):
    now = datetime.now(timezone.utc)
    _seed_cache("ZECUSDT", "15m", now - timedelta(minutes=5), n=60)
    consumer = _consumer()
    download = AsyncMock()
    monkeypatch.setattr(consumer, "_download_initial_kline_history_for_key", download)
    result = await consumer._ensure_history_loaded(
        "kline_15m", "ZECUSDT", "15m", "futures_usdtm", "bitget"
    )
    assert result is True
    assert download.await_count == 0


@pytest.mark.asyncio
async def test_snapshot_gate_rejects_stale_rows(clean_kline_globals):
    """A stale snapshot must not clobber the local deque."""
    now = datetime.now(timezone.utc)
    consumer = _consumer()
    fresh_key = _seed_cache("ZECUSDT", "15m", now - timedelta(minutes=5), n=60)
    before = list(dc_module._global_kline_cache[fresh_key])

    stale_ms = int((now - timedelta(days=4)).timestamp() * 1000)
    stale_rows = [
        [stale_ms - (59 - i) * 900000, 1.0, 1.0, 1.0, 1.0, 1.0] for i in range(60)
    ]
    stale_snapshot = {
        "type": "market_snapshot",
        "stream_key": "bitget:futures_usdtm:zecusdt@kline_15m",
        "data_type_key": "kline_15m",
        "symbol": "ZECUSDT",
        "market_type": "futures_usdtm",
        "exchange_id": "bitget",
        "rows": stale_rows,
    }
    assert await consumer._apply_market_snapshot(stale_snapshot) is False
    assert list(dc_module._global_kline_cache[fresh_key]) == before


class _RecordHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@pytest.mark.asyncio
async def test_controller_gather_skips_stale_as_warmup(clean_kline_globals):
    """Stale cache => gather returns None with WARMUP (not REJECTED), no check."""
    now = datetime.now(timezone.utc)
    stale_df = _df_ending_at(now - timedelta(days=4, hours=2), n=60)

    consumer = MagicMock()
    # NOTE: TradingController calls a *callable* data_consumer, so stub
    # methods must be attached after construction, on controller.consumer.
    controller = TradingController(
        loop=asyncio.get_running_loop(),
        data_consumer=consumer,
        live_executor=MagicMock(),
        paper_executor=AsyncMock(),
        risk_manager=MagicMock(),
        user_id=1,
    )
    for name in (
        "get_latest_depth",
        "get_recent_trades",
        "get_open_interest",
        "_ensure_history_loaded",
    ):
        setattr(controller.consumer, name, AsyncMock(return_value=True))
    controller.consumer.get_kline_history = AsyncMock(return_value=stale_df)
    handler = _RecordHandler()
    logger = logging.getLogger("bot_module.controller")
    logger.addHandler(handler)
    try:
        result = await controller._gather_market_data_for_required_keys(
            log_prefix="[TestWarmup]",
            symbol="ZECUSDT",
            required_data_keys={"kline_15m"},
            market_type="futures_usdtm",
        )
    finally:
        logger.removeHandler(handler)
    assert result is None
    assert any("WARMUP" in msg for msg in handler.messages), handler.messages


@pytest.mark.asyncio
async def test_controller_gather_passes_fresh_data(clean_kline_globals):
    now = datetime.now(timezone.utc)
    fresh_df = _df_ending_at(now - timedelta(minutes=5), n=60)

    consumer = MagicMock()
    controller = TradingController(
        loop=asyncio.get_running_loop(),
        data_consumer=consumer,
        live_executor=MagicMock(),
        paper_executor=AsyncMock(),
        risk_manager=MagicMock(),
        user_id=1,
    )
    for name in (
        "get_latest_depth",
        "get_recent_trades",
        "get_open_interest",
        "_ensure_history_loaded",
    ):
        setattr(controller.consumer, name, AsyncMock(return_value=True))
    controller.consumer.get_kline_history = AsyncMock(return_value=fresh_df)
    result = await controller._gather_market_data_for_required_keys(
        log_prefix="[TestWarmup]",
        symbol="ZECUSDT",
        required_data_keys={"kline_15m"},
        market_type="futures_usdtm",
    )
    assert result is not None
    assert "kline_15m" in result


@pytest.mark.asyncio
async def test_snapshot_gate_accepts_fresh_rows(clean_kline_globals):
    consumer = _consumer()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    # Ascending, like the production deque (oldest first, newest last).
    rows = [[now_ms - (59 - i) * 900000, 1.0, 1.0, 1.0, 1.0, 1.0] for i in range(60)]
    snapshot = {
        "type": "market_snapshot",
        "stream_key": "bitget:futures_usdtm:zecusdt@kline_15m",
        "data_type_key": "kline_15m",
        "symbol": "ZECUSDT",
        "market_type": "futures_usdtm",
        "exchange_id": "bitget",
        "rows": rows,
    }
    assert await consumer._apply_market_snapshot(snapshot) is True
    cache_key = dc_module._kline_cache_key("ZECUSDT", "15m", "bitget", "futures_usdtm")
    assert len(dc_module._global_kline_cache[cache_key]) == 60
