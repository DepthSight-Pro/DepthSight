"""Fleet gauges + global admission cap (fail-open).

Two different units, deliberately kept apart:
  - running strategy instances: what a strategy start adds to, so this is
    what the cap gates;
  - bot controllers: one per (user x API key), created at bot bootstrap with
    no API involvement. They are the RAM unit (~45 MB each) and can therefore
    NOT be gated from the API - only observed.

The cap's worst failure mode is the opposite one: blocking trading because
telemetry is broken. These tests pin both ends - reject when the gauge says we
are full, never reject when we cannot tell.
"""

import fnmatch
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import fleet_capacity
from api.fleet_capacity import (
    FLEET_CONTROLLER_KEY_PREFIX,
    FLEET_STRATEGY_KEY_PREFIX,
    get_max_global_live_strategies,
    is_fleet_at_capacity,
    read_fleet_controllers,
    read_fleet_strategies,
)


class _FakeRedis:
    """Minimal Redis stand-in: async scan_iter + mget, like redis.asyncio."""

    def __init__(self, data=None, error=None):
        self._data = dict(data or {})
        self._error = error

    def scan_iter(self, match=None, count=None):
        async def _gen():
            if self._error:
                raise self._error
            for key in list(self._data):
                if match and not fnmatch.fnmatch(key, match):
                    continue
                yield key

        return _gen()

    async def mget(self, keys):
        if self._error:
            raise self._error
        return [self._data.get(key) for key in keys]

    async def get(self, key):
        return self._data.get(key)


def _strategy_key(shard_id):
    return f"{FLEET_STRATEGY_KEY_PREFIX}{shard_id}"


def _controller_key(shard_id):
    return f"{FLEET_CONTROLLER_KEY_PREFIX}{shard_id}"


# --- gauges ----------------------------------------------------------------


async def test_sums_gauges_across_shards():
    client = _FakeRedis(
        {
            _strategy_key(0): "91",
            _strategy_key(1): "88",
            _controller_key(0): "120",
            _controller_key(1): "118",
        }
    )
    assert await read_fleet_strategies(client) == (179, 2)
    assert await read_fleet_controllers(client) == (238, 2)


async def test_no_keys_means_empty_fleet_not_unknown():
    assert await read_fleet_strategies(_FakeRedis({})) == (0, 0)


async def test_gauges_do_not_read_each_other():
    """Strategy and controller counters must not bleed into one another."""
    client = _FakeRedis({_controller_key(0): "500"})
    assert await read_fleet_strategies(client) == (0, 0)
    assert await read_fleet_controllers(client) == (500, 1)


async def test_redis_failure_reports_unknown():
    """-1 is the "we cannot tell" signal callers fail open on."""
    client = _FakeRedis(error=ConnectionError("redis down"))
    assert await read_fleet_strategies(client) == (-1, 0)


async def test_garbage_values_are_skipped_not_summed():
    client = _FakeRedis({_strategy_key(0): "50", _strategy_key(1): "n/a"})
    assert await read_fleet_strategies(client) == (50, 1)


# --- cap configuration ------------------------------------------------------


def test_cap_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MAX_GLOBAL_LIVE_STRATEGIES", raising=False)
    assert get_max_global_live_strategies() == 0


def test_cap_reads_env(monkeypatch):
    monkeypatch.setenv("MAX_GLOBAL_LIVE_STRATEGIES", "800")
    assert get_max_global_live_strategies() == 800


def test_cap_rejects_garbage_and_negative(monkeypatch):
    monkeypatch.setenv("MAX_GLOBAL_LIVE_STRATEGIES", "many")
    assert get_max_global_live_strategies() == 0
    monkeypatch.setenv("MAX_GLOBAL_LIVE_STRATEGIES", "-5")
    assert get_max_global_live_strategies() == 0


# --- is_fleet_at_capacity ---------------------------------------------------


async def test_no_cap_means_no_admission_check(monkeypatch):
    monkeypatch.delenv("MAX_GLOBAL_LIVE_STRATEGIES", raising=False)
    assert await is_fleet_at_capacity(_FakeRedis({_strategy_key(0): "99999"})) == (
        False,
        "cap disabled",
    )


async def test_at_capacity_blocks(monkeypatch):
    monkeypatch.setenv("MAX_GLOBAL_LIVE_STRATEGIES", "800")
    at_capacity, reason = await is_fleet_at_capacity(
        _FakeRedis({_strategy_key(0): "500", _strategy_key(1): "300"})
    )
    assert at_capacity is True
    assert "800" in reason


async def test_below_capacity_allows(monkeypatch):
    monkeypatch.setenv("MAX_GLOBAL_LIVE_STRATEGIES", "800")
    at_capacity, _ = await is_fleet_at_capacity(_FakeRedis({_strategy_key(0): "799"}))
    assert at_capacity is False


async def test_controllers_alone_never_trip_the_cap(monkeypatch):
    """Controllers are ungateable by design; they must not fake a full fleet.

    Otherwise a box full of idle controllers (every key on it) would block new
    strategies forever while trading capacity is free.
    """
    monkeypatch.setenv("MAX_GLOBAL_LIVE_STRATEGIES", "10")
    at_capacity, _ = await is_fleet_at_capacity(
        _FakeRedis({_controller_key(0): "5000"})
    )
    assert at_capacity is False


async def test_unreadable_gauge_fails_open(monkeypatch):
    """The critical property: a Redis outage must not stop trading."""
    monkeypatch.setenv("MAX_GLOBAL_LIVE_STRATEGIES", "1")
    at_capacity, reason = await is_fleet_at_capacity(
        _FakeRedis(error=ConnectionError("redis down"))
    )
    assert at_capacity is False
    assert "fail-open" in reason


async def test_no_shard_reporting_yet_fails_open(monkeypatch):
    """Right after a bot restart the gauge is empty: gate nothing."""
    monkeypatch.setenv("MAX_GLOBAL_LIVE_STRATEGIES", "1")
    at_capacity, reason = await is_fleet_at_capacity(_FakeRedis({}))
    assert at_capacity is False
    assert "fail-open" in reason


# --- wiring into the live-start path ----------------------------------------


@pytest.mark.asyncio
async def test_live_start_is_rejected_at_capacity(monkeypatch):
    """The start path must refuse a new bot once the fleet is full."""
    from api import depthsight_api

    monkeypatch.setenv("MAX_GLOBAL_LIVE_STRATEGIES", "800")
    monkeypatch.setattr(
        depthsight_api.crud, "get_active_api_keys_for_user", _async_return([])
    )
    with pytest.raises(HTTPException) as exc_info:
        await depthsight_api._enforce_live_strategy_limit(
            user=SimpleNamespace(id=42, plan="free"),
            request=SimpleNamespace(mode="live", api_key_id=None, config_id=None),
            db=None,
            redis_client=_FakeRedis({_strategy_key(0): "800"}),
        )
    assert exc_info.value.status_code == 429
    assert "capacity" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_live_start_passes_when_gauge_is_unreadable(monkeypatch):
    """Same outage, opposite outcome: the cap must not fire on missing data."""
    from api import depthsight_api

    monkeypatch.setenv("MAX_GLOBAL_LIVE_STRATEGIES", "1")
    monkeypatch.setattr(
        depthsight_api.crud, "get_active_api_keys_for_user", _async_return([])
    )
    monkeypatch.setattr(
        depthsight_api, "load_user_running_strategies", _async_return([])
    )
    # Free plan has live limit 0 and nothing is running, so the per-plan check
    # passes: reaching the end proves the capacity gate stayed out of the way.
    assert (
        await depthsight_api._enforce_live_strategy_limit(
            user=SimpleNamespace(id=42, plan="free"),
            request=SimpleNamespace(mode="live", api_key_id=None, config_id=None),
            db=None,
            redis_client=_FakeRedis(error=ConnectionError("redis down")),
        )
        is None
    )


@pytest.mark.asyncio
async def test_paper_mode_skips_the_capacity_gate(monkeypatch):
    """Paper bots cost RAM too, but the cap is scoped to live starts only."""
    from api import depthsight_api

    monkeypatch.setenv("MAX_GLOBAL_LIVE_STRATEGIES", "1")
    called = []

    async def _track(*args, **kwargs):
        called.append(True)
        return False, "cap disabled"

    monkeypatch.setattr(depthsight_api, "is_fleet_at_capacity", _track)
    await depthsight_api._enforce_live_strategy_limit(
        user=SimpleNamespace(id=42, plan="free"),
        request=SimpleNamespace(mode="paper", api_key_id=None, config_id=None),
        db=None,
        redis_client=_FakeRedis({_strategy_key(0): "9999"}),
    )
    assert called == []


def _async_return(value):
    from unittest.mock import AsyncMock

    return AsyncMock(return_value=value)


def test_fleet_module_exposes_key_helpers():
    assert fleet_capacity.fleet_strategy_key(3) == f"{FLEET_STRATEGY_KEY_PREFIX}3"
    assert fleet_capacity.fleet_controller_key(3) == f"{FLEET_CONTROLLER_KEY_PREFIX}3"


# --- admin dashboard endpoint -------------------------------------------------


async def test_dashboard_stats_include_both_gauges(monkeypatch):
    from api.routes import admin as admin_routes

    monkeypatch.setenv("MAX_GLOBAL_LIVE_STRATEGIES", "800")
    monkeypatch.setattr(
        admin_routes.crud, "get_dashboard_stats", _async_return(_stats(7, 9))
    )
    stats = await admin_routes.get_dashboard_stats(
        db=None,
        redis_client=_FakeRedis(
            {
                _strategy_key(0): "500",
                _strategy_key(1): "301",
                _controller_key(0): "612",
                _controller_key(1): "610",
            }
        ),
    )
    assert stats.fleet_strategies == 801
    assert stats.fleet_controllers == 1222
    assert stats.fleet_shards_reporting == 2
    assert stats.fleet_strategy_cap == 800


async def test_dashboard_reports_unknown_before_the_first_sample(monkeypatch):
    """The observed "0 right after a restart" trap: never claim an idle fleet."""
    from api.routes import admin as admin_routes

    monkeypatch.setenv("MAX_GLOBAL_LIVE_STRATEGIES", "800")
    monkeypatch.setattr(
        admin_routes.crud, "get_dashboard_stats", _async_return(_stats(7, 9))
    )
    stats = await admin_routes.get_dashboard_stats(db=None, redis_client=_FakeRedis({}))
    assert stats.fleet_strategies == -1
    assert stats.fleet_controllers == -1
    assert stats.new_users_last_7_days == 7


async def test_dashboard_survives_an_unreadable_gauge(monkeypatch):
    """A dead gauge must degrade the dashboard, never break it."""
    from api.routes import admin as admin_routes

    monkeypatch.setenv("MAX_GLOBAL_LIVE_STRATEGIES", "800")
    monkeypatch.setattr(
        admin_routes.crud, "get_dashboard_stats", _async_return(_stats(7, 9))
    )
    stats = await admin_routes.get_dashboard_stats(
        db=None, redis_client=_FakeRedis(error=ConnectionError("redis down"))
    )
    assert stats.fleet_strategies == -1
    assert stats.new_users_last_7_days == 7


def _stats(new_users, tasks_run):
    from api import schemas

    return schemas.DashboardStats(
        new_users_last_7_days=new_users,
        tasks_run_last_7_days=tasks_run,
        task_counts_by_type={"backtest": 4},
    )
