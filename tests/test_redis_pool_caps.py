"""Regression: per-controller Redis pools must be capped (EMFILE).

Every trading controller builds its own Redis clients (controller state,
risk-manager state, market-data fan-out). With the redis-py default of 50
connections per pool, 100+ controllers mean thousands of fds and
"OSError: [Errno 24] Too many open files" under burst load - observed as
~29k occurrences with the bot ballooning to ~7GB.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot_module import config
from bot_module.controller import TradingController


def _make_controller():
    """Minimal TradingController: real Redis client objects, everything else mocked.

    Constructing redis.Redis does NOT connect (lazy), so no server is needed;
    connection_pool.max_connections is readable immediately.
    """
    mock_consumer = AsyncMock()
    mock_paper_executor = MagicMock()
    mock_paper_executor.controller = None
    with (
        patch(
            "bot_module.controller.get_strategy_instance",
            return_value=MagicMock(),
        ),
        patch("bot_module.controller.STRATEGIES", {}),
    ):
        ctrl = TradingController(
            loop=asyncio.get_running_loop(),
            data_consumer=lambda **kwargs: mock_consumer,
            live_executor=MagicMock(),
            paper_executor=mock_paper_executor,
            risk_manager=MagicMock(),
            user_id=1,
        )
    return ctrl


def test_pool_cap_config_sane():
    assert isinstance(config.REDIS_POOL_MAX_CONNECTIONS, int)
    assert config.REDIS_POOL_MAX_CONNECTIONS >= 1
    # Must stay far below the redis-py default of 50, otherwise the cap is fiction.
    assert config.REDIS_POOL_MAX_CONNECTIONS <= 10


@pytest.mark.asyncio
async def test_controller_redis_pool_is_capped():
    ctrl = _make_controller()
    assert ctrl.redis_client is not None
    assert (
        ctrl.redis_client.connection_pool.max_connections
        == config.REDIS_POOL_MAX_CONNECTIONS
    )


def test_risk_manager_redis_pool_is_capped():
    from bot_module.risk_manager import RiskManager

    rm = RiskManager(
        executor=None,
        paper_executor=MagicMock(),
        user_id=1,
        db_session=MagicMock(),
        user_settings={"risk_management": {"riskPerTradePercent": 1.0}},
    )
    assert rm.redis_client is not None
    assert (
        rm.redis_client.connection_pool.max_connections
        == config.REDIS_POOL_MAX_CONNECTIONS
    )


@pytest.mark.asyncio
async def test_state_publish_is_serialized():
    """Concurrent _publish_state_to_redis calls must not stack.

    The method is fire-and-forget scheduled from ~10 call sites, so a burst
    used to run N concurrent publishes per controller, each checking out its
    own pool connection (pool growth -> EMFILE) and each holding a full state
    copy (memory). Now the second call is skipped while one is in flight.
    """
    ctrl = _make_controller()
    release = asyncio.Event()
    calls = 0

    async def slow_impl():
        nonlocal calls
        calls += 1
        await release.wait()

    ctrl._publish_state_to_redis_impl = slow_impl
    assert ctrl._publish_state_in_flight is False

    first = asyncio.ensure_future(ctrl._publish_state_to_redis())
    await asyncio.sleep(0.05)  # let the first call enter the impl
    assert calls == 1

    # A concurrent call while one is in flight must be skipped, not stacked.
    await ctrl._publish_state_to_redis()
    assert calls == 1

    release.set()
    await first
    assert ctrl._publish_state_in_flight is False

    # After release, publishing works again.
    await ctrl._publish_state_to_redis()
    assert calls == 2
