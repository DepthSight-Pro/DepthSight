# tests/test_mining_catchup_loop.py
"""
Coverage for per-day epoch attribution and the catch-up loop
(tasks._async_process_open_epochs + day-bounded sweep in
tasks._async_process_mining_epoch):

- two days of leftovers close as TWO epochs in one driver run (no absorption);
- an old PENDING day does not block a newer epoch;
- a late trade whose own day is already finalized is forward-credited,
  never orphaned;
- calendar completion backfills empty finalized rows for idle days.
"""

import datetime
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.future import select

from api import models
from tasks import _async_process_open_epochs

pytestmark = pytest.mark.asyncio


def _day(n: int) -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(
        days=n
    )


def _noon(day: datetime.date) -> datetime.datetime:
    return datetime.datetime.combine(
        day, datetime.time(12, 0), tzinfo=datetime.timezone.utc
    )


def _make_config(**overrides) -> models.MiningConfig:
    defaults = dict(
        is_mining_enabled=True,
        eligible_exchanges=["weex"],
        daily_emission_base=100.0,
        launch_date=_day(10),
        referral_mining_boost=0.0,
        rebate_rates={},
    )
    defaults.update(overrides)
    return models.MiningConfig(**defaults)


def _add_report(
    db_session,
    node_uuid: str,
    day: datetime.date,
    rebate: float = 10.0,
    volume: float = 20000.0,
    status: str = "VERIFIED",
    eligible: bool = True,
    broker_id: str = None,
):
    report = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=50000.0,
        exit_price=50100.0,
        trade_mode="LIVE",
        node_uuid=node_uuid,
        estimated_rebate_usdt=rebate,
        trade_volume_usdt=volume,
        is_mining_eligible=eligible,
        verification_status=status,
        created_at=_noon(day),
        exchange_id="weex_futures",
        market_type="futures",
        mining_multiplier=1.0,
        broker_trade_id=broker_id or f"trade-{node_uuid}-{day.isoformat()}",
    )
    db_session.add(report)
    return report


async def _run_driver(db_session, **kwargs):
    @asynccontextmanager
    async def mock_isolated_session():
        yield db_session

    with patch("api.database.get_isolated_worker_session", mock_isolated_session):
        result = await _async_process_open_epochs(**kwargs)
    db_session.expire_all()
    return result


async def _epoch(db_session, day: datetime.date):
    res = await db_session.execute(
        select(models.MiningEpoch).where(models.MiningEpoch.epoch_date == day)
    )
    return res.scalars().first()


async def _reports_in_epoch(db_session, day: datetime.date):
    res = await db_session.execute(
        select(models.HubTelemetryReport).where(
            models.HubTelemetryReport.epoch_date == day
        )
    )
    return res.scalars().all()


async def test_two_days_close_as_two_epochs_without_absorption(db_session, monkeypatch):
    """Leftovers of two days settle into their OWN epochs in one driver run."""
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    day_old, day_new = _day(2), _day(1)
    node = models.HubNode(node_uuid="loop-node", name="Loop", secret_hash="h")
    db_session.add(node)
    db_session.add(_make_config())
    await db_session.commit()

    _add_report(db_session, "loop-node", day_old, rebate=10.0)
    _add_report(db_session, "loop-node", day_new, rebate=10.0)
    await db_session.commit()

    processed = await _run_driver(db_session, calendar_days=0)

    assert day_old in processed
    assert day_new in processed

    old_epoch = await _epoch(db_session, day_old)
    new_epoch = await _epoch(db_session, day_new)
    assert old_epoch is not None and old_epoch.status == "finalized"
    assert new_epoch is not None and new_epoch.status == "finalized"

    old_reports = await _reports_in_epoch(db_session, day_old)
    new_reports = await _reports_in_epoch(db_session, day_new)
    assert len(old_reports) == 1
    assert len(new_reports) == 1
    # No cross-attribution: created day == epoch day.
    assert old_reports[0].created_at.date() == day_old
    assert new_reports[0].created_at.date() == day_new
    # Equal rebates on different days earn equal rewards (no dilution).
    assert old_reports[0].reward_tokens == pytest.approx(new_reports[0].reward_tokens)


async def test_old_pending_does_not_block_new_epoch(db_session, monkeypatch):
    """A stuck PENDING day must not hold the newer epoch hostage."""
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    day_old, day_new = _day(2), _day(1)
    node = models.HubNode(node_uuid="stuck-node", name="Stuck", secret_hash="h")
    db_session.add(node)
    db_session.add(_make_config())
    await db_session.commit()

    _add_report(db_session, "stuck-node", day_old, rebate=10.0, status="PENDING")
    _add_report(db_session, "stuck-node", day_new, rebate=10.0)
    await db_session.commit()

    with patch("hub_private.tasks.verify_epoch_trades", new=AsyncMock(return_value={})):
        processed = await _run_driver(db_session, calendar_days=0)

    # New epoch finalized despite the old PENDING; old day left open.
    assert day_new in processed
    new_epoch = await _epoch(db_session, day_new)
    assert new_epoch is not None and new_epoch.status == "finalized"
    assert await _epoch(db_session, day_old) is None
    new_reports = await _reports_in_epoch(db_session, day_new)
    assert len(new_reports) == 1


async def test_late_trade_forward_credited_when_own_day_finalized(
    db_session, monkeypatch
):
    """A trade verified after its own epoch finalized is credited forward."""
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    day_old, day_new = _day(2), _day(1)
    node = models.HubNode(node_uuid="late-node", name="Late", secret_hash="h")
    db_session.add(node)
    db_session.add(_make_config())
    await db_session.commit()

    # Day-old settles first (its only trade).
    _add_report(db_session, "late-node", day_old, rebate=10.0)
    await db_session.commit()
    await _run_driver(db_session, calendar_days=0)
    assert (await _epoch(db_session, day_old)).status == "finalized"

    # Late arrival: created on the finalized day, verified only now.
    late = _add_report(
        db_session, "late-node", day_old, rebate=10.0, broker_id="late-trade-1"
    )
    _add_report(db_session, "late-node", day_new, rebate=10.0)
    await db_session.commit()

    await _run_driver(db_session, calendar_days=0)

    await db_session.refresh(late)
    # Not orphaned: credited into the currently settling epoch.
    assert late.epoch_date == day_new
    assert late.reward_tokens > 0.0


async def test_calendar_backfills_empty_row(db_session, monkeypatch):
    """Idle days get finalized zero rows (chart continuity)."""
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    db_session.add(_make_config())
    await db_session.commit()

    await _run_driver(db_session, calendar_days=2)

    for day in (_day(2), _day(1)):
        epoch = await _epoch(db_session, day)
        assert epoch is not None and epoch.status == "finalized"
        assert epoch.total_distributed == pytest.approx(0.0)
