"""Regression: market-data blobs must be shared process-wide (shared-DC phase 1).

One DataConsumer per controller used to mean N copies of the same depth
snapshots (full L2 ladders). All instances must alias the single
process-global dict; readers already copy on read.
"""

import pytest

from bot_module.data_consumer import DataConsumer


def _depth_snapshot():
    return {
        "lastUpdateId": 1,
        "bids": [[83400.0, 1.5], [83399.0, 2.0]],
        "asks": [[83401.0, 1.0], [83402.0, 3.0]],
        "full_l2_depth": {
            "bids": [[83400.0, 1.5]],
            "asks": [[83401.0, 1.0]],
        },
        "aggregated_depth": {"bids": [], "asks": []},
        "cached_at_ms": 1,
    }


@pytest.mark.asyncio
async def test_depth_cache_is_shared_across_instances():
    first = DataConsumer()
    second = DataConsumer()
    assert first._latest_depth_cache is second._latest_depth_cache


@pytest.mark.asyncio
async def test_depth_written_by_one_is_read_by_other():
    first = DataConsumer()
    second = DataConsumer()
    first._latest_depth_cache["BTCUSDT_futures"] = _depth_snapshot()

    got = await second.get_latest_depth("BTCUSDT", market_type_requested="futures")

    assert got is not None
    assert got["bids"][0][0] == 83400.0
    assert got["asks"][0][0] == 83401.0


@pytest.mark.asyncio
async def test_depth_read_returns_copy_not_alias():
    # Contract (unchanged by sharing): the top-level dict is a copy, so
    # replacing keys cannot corrupt the cache. Nested level lists are shared
    # by design (copy-on-read would cost a deepcopy per read per controller);
    # verified by grep that no caller mutates them in place.
    first = DataConsumer()
    first._latest_depth_cache["BTCUSDT_futures"] = _depth_snapshot()

    got = await first.get_latest_depth("BTCUSDT", market_type_requested="futures")
    got["cached_at_ms"] = 999
    got["injected"] = True

    again = await first.get_latest_depth("BTCUSDT", market_type_requested="futures")
    assert again["cached_at_ms"] == 1
    assert "injected" not in again
