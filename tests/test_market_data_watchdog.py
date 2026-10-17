"""Market-data pub/sub watchdog (night-run follow-up).

The command channel receives one `subscribe` per controller and then nothing
for the rest of the run, so "no command message for 30s" is normal operation,
not a dead connection. The old watchdog could not tell the difference and
reconnected 1361 times in an 11.3-hour night - every reconnect re-opening a
window in which a `subscribe` publish is dropped forever (pub/sub has no
replay). Reconnect must require actual transport failure.
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from market_data_service import MarketDataService


def _service() -> MarketDataService:
    svc = MarketDataService()
    svc.redis = MagicMock()
    svc.redis.ping = AsyncMock(return_value=True)
    svc.pubsub = MagicMock()
    svc._reconnect_pubsub = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_quiet_channel_with_healthy_server_never_reconnects():
    svc = _service()
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture()
    logging.getLogger("market_data_service").addHandler(handler)
    threshold = svc.WATCHDOG_IDLE_STREAK_BEFORE_CHECK
    try:
        for streak in range(1, 11):
            await svc._maybe_reconnect_pubsub(streak, 30)
    finally:
        logging.getLogger("market_data_service").removeHandler(handler)

    svc._reconnect_pubsub.assert_not_awaited()
    # No ping before the streak threshold; one per timeout after it.
    assert svc.redis.ping.await_count == 10 - threshold + 1
    assert not [r for r in records if r.levelno >= logging.WARNING]


@pytest.mark.asyncio
async def test_unreachable_server_reconnects_after_streak():
    svc = _service()
    svc.redis.ping = AsyncMock(side_effect=ConnectionError("redis gone"))

    await svc._maybe_reconnect_pubsub(1, 30)
    await svc._maybe_reconnect_pubsub(2, 30)
    svc._reconnect_pubsub.assert_not_awaited()

    await svc._maybe_reconnect_pubsub(svc.WATCHDOG_IDLE_STREAK_BEFORE_CHECK, 30)
    svc._reconnect_pubsub.assert_awaited_once()


@pytest.mark.asyncio
async def test_healthy_server_survives_endless_idle():
    """A fully subscribed, permanently quiet service must keep its
    subscription - this is the regression the night exposed."""
    svc = _service()
    for streak in range(1, 200):
        await svc._maybe_reconnect_pubsub(streak, 30)
    svc._reconnect_pubsub.assert_not_awaited()
    assert svc.redis.ping.await_count == 197


@pytest.mark.asyncio
async def test_reconnect_resubscribes_command_channel():
    """The reconnect path itself must still re-open the command channel."""
    svc = MarketDataService()
    svc.redis = MagicMock()
    svc.redis.pubsub.return_value = MagicMock(
        subscribe=AsyncMock(), unsubscribe=AsyncMock(), close=AsyncMock()
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "market_data_service.config.MARKET_DATA_REDIS_COMMAND_CHANNEL",
            "depthsight:market_data:commands",
            raising=False,
        )
        await svc._reconnect_pubsub()
    svc.redis.pubsub.return_value.subscribe.assert_awaited_once_with(
        "depthsight:market_data:commands"
    )
