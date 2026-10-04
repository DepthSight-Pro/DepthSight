"""Hot-path kline backfill in redis fan-out mode.

Production incident: a silently dead 1h channel froze its cache for 3 days
with ZERO history download attempts - `_ensure_history_loaded` returned True
unconditionally in redis mode, and the on-demand path only triggers on row
count, never on staleness. These tests pin the fixed behavior: freshness is
verified, stale keys REST-backfill (throttled per key), fresh keys never hit
REST.
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from bot_module import data_consumer as dc_module
from bot_module.data_consumer import DataConsumer


@pytest.fixture()
def _clean_kline_state(monkeypatch):
    saved = {
        "cache": dict(dc_module._global_kline_cache),
        "df": dict(dc_module._global_kline_df_cache),
        "loaded": set(dc_module._global_history_loaded_keys),
        "tasks": dict(dc_module._global_history_download_tasks),
        "attempts": dict(dc_module._global_history_backfill_attempts),
        "updates": dict(dc_module._global_kline_last_update),
    }
    dc_module._global_kline_cache.clear()
    dc_module._global_kline_df_cache.clear()
    dc_module._global_history_loaded_keys.clear()
    dc_module._global_history_download_tasks.clear()
    dc_module._global_history_backfill_attempts.clear()
    dc_module._global_kline_last_update.clear()
    yield
    dc_module._global_kline_cache.clear()
    dc_module._global_kline_cache.update(saved["cache"])
    dc_module._global_kline_df_cache.clear()
    dc_module._global_kline_df_cache.update(saved["df"])
    dc_module._global_history_loaded_keys.clear()
    dc_module._global_history_loaded_keys.update(saved["loaded"])
    dc_module._global_history_download_tasks.clear()
    dc_module._global_history_download_tasks.update(saved["tasks"])
    dc_module._global_history_backfill_attempts.clear()
    dc_module._global_history_backfill_attempts.update(saved["attempts"])
    dc_module._global_kline_last_update.clear()
    dc_module._global_kline_last_update.update(saved["updates"])


def _df_ending(hours_ago, periods=30, freq="1h"):
    end = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    idx = pd.date_range(end=end, periods=periods, freq=freq, tz="UTC")
    return pd.DataFrame({"close": [100.0] * periods}, index=idx)


def _fake_downloader_factory(calls, fresh_df):
    async def fake_download(
        self,
        cache_key,
        symbol_uc,
        timeframe,
        market_type_for_loader,
        exchange_id="binance",
    ):
        from collections import deque

        calls.append(cache_key)
        rows = [
            (
                int(ts.timestamp() * 1000),
                100.0,
                101.0,
                99.0,
                100.5,
                10.0,
            )
            for ts in fresh_df.index
        ]
        dc_module._global_kline_cache[cache_key] = deque(rows, maxlen=1000)
        dc_module._global_kline_df_cache[cache_key] = fresh_df
        dc_module._global_history_loaded_keys.add(cache_key)
        return True

    return fake_download


def _seed_stale(symbol="TST1USDT", timeframe="1h", exchange="bitget"):
    from collections import deque

    key = dc_module._kline_cache_key(symbol, timeframe, exchange, "futures_usdtm")
    stale = _df_ending(72)
    rows = [
        (int(ts.timestamp() * 1000), 100.0, 101.0, 99.0, 100.0, 10.0)
        for ts in stale.index
    ]
    dc_module._global_kline_cache[key] = deque(rows, maxlen=1000)
    dc_module._global_kline_df_cache[key] = stale
    return key


@pytest.mark.asyncio
async def test_redis_mode_stale_cache_backfills(_clean_kline_state, monkeypatch):
    """Stale cache in redis mode must REST-backfill instead of returning True."""
    calls = []
    monkeypatch.setattr(
        DataConsumer,
        "_download_initial_kline_history_for_key",
        _fake_downloader_factory(calls, _df_ending(0)),
    )
    consumer = DataConsumer(market_data_mode="redis")
    key = _seed_stale()

    ok = await consumer._ensure_history_loaded(
        "kline_1h", "TST1USDT", "1h", "futures_usdtm", "bitget"
    )
    assert ok is True
    assert calls == [key], "exactly one backfill attempt expected"
    fresh, _age = dc_module.is_kline_fresh(dc_module._global_kline_df_cache[key], "1h")
    assert fresh is True


@pytest.mark.asyncio
async def test_backfill_attempts_throttled_per_key(_clean_kline_state, monkeypatch):
    """A second immediate ensure must not schedule another REST download."""
    calls = []
    monkeypatch.setattr(
        DataConsumer,
        "_download_initial_kline_history_for_key",
        _fake_downloader_factory(calls, _df_ending(0)),
    )
    # Pre-record a recent attempt without converging the cache.
    dc_module._global_history_backfill_attempts[
        (
            dc_module._kline_cache_key("TST2USDT", "1h", "bitget", "futures_usdtm"),
            None,
        )
    ] = __import__("time").monotonic()
    _seed_stale(symbol="TST2USDT")
    consumer = DataConsumer(market_data_mode="redis")

    ok = await consumer._ensure_history_loaded(
        "kline_1h", "TST2USDT", "1h", "futures_usdtm", "bitget"
    )
    assert ok is False
    assert calls == [], "throttled: no second download"


@pytest.mark.asyncio
async def test_redis_mode_fresh_cache_never_downloads(_clean_kline_state, monkeypatch):
    """Fresh cache in redis mode returns fast with zero REST traffic."""
    calls = []
    monkeypatch.setattr(
        DataConsumer,
        "_download_initial_kline_history_for_key",
        _fake_downloader_factory(calls, _df_ending(0)),
    )
    key = dc_module._kline_cache_key("TST3USDT", "1h", "bitget", "futures_usdtm")
    dc_module._global_kline_df_cache[key] = _df_ending(0)
    consumer = DataConsumer(market_data_mode="redis")

    ok = await consumer._ensure_history_loaded(
        "kline_1h", "TST3USDT", "1h", "futures_usdtm", "bitget"
    )
    assert ok is True
    assert calls == []
