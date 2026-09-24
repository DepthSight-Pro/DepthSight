# tests/test_mining_epoch_gating.py
"""
Gating: an epoch must wait for EVERYONE (manual XLSX and automatic broker
API confirmations alike). Even a single PENDING report for the epoch window
blocks finalization, regardless of how many trades are already VERIFIED.
Covers tasks._async_process_mining_epoch pending-block behavior.
"""

import datetime
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from api import models
from tasks import _async_process_mining_epoch

pytestmark = pytest.mark.asyncio


def _yesterday() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(
        days=1
    )


def _yesterday_noon() -> datetime.datetime:
    return datetime.datetime.combine(
        _yesterday(), datetime.time(12, 0), tzinfo=datetime.timezone.utc
    )


def _make_config(**overrides) -> models.MiningConfig:
    defaults = dict(
        is_mining_enabled=True,
        eligible_exchanges=["weex", "bitget"],
        daily_emission_base=100.0,
        launch_date=datetime.date.today() - datetime.timedelta(days=2),
        referral_mining_boost=0.10,
        rebate_rates={},
    )
    defaults.update(overrides)
    return models.MiningConfig(**defaults)


async def _run_epoch(db_session: AsyncSession):
    @asynccontextmanager
    async def mock_isolated_session():
        yield db_session

    with patch("api.database.get_isolated_worker_session", mock_isolated_session):
        await _async_process_mining_epoch(force_yesterday_date=_yesterday())
    db_session.expire_all()


async def _add_report(
    db_session: AsyncSession, status: str, exchange: str, node_uuid: str
) -> models.HubTelemetryReport:
    report = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=10.0,
        exit_price=11.0,
        trade_mode="LIVE",
        exchange_id=exchange,
        node_uuid=node_uuid,
        estimated_rebate_usdt=0.05,
        trade_volume_usdt=100.0,
        is_mining_eligible=True,
        verification_status=status,
        created_at=_yesterday_noon(),
    )
    db_session.add(report)
    await db_session.commit()
    return report


async def _get_epoch(db_session: AsyncSession):
    res = await db_session.execute(
        select(models.MiningEpoch).where(models.MiningEpoch.epoch_date == _yesterday())
    )
    return res.scalars().first()


async def test_epoch_waits_for_pending_despite_verified(
    db_session: AsyncSession,
    monkeypatch,
):
    """One VERIFIED weex + one PENDING bitget (no broker keys in tests, so the
    Bitget path retains it as PENDING) -> epoch must NOT finalize."""
    monkeypatch.delenv("BITGET_BROKER_API_KEY", raising=False)
    monkeypatch.delenv("BITGET_BROKER_API_SECRET", raising=False)
    monkeypatch.delenv("BITGET_BROKER_API_PASSPHRASE", raising=False)
    # hub_private reads credentials at import time; force clients to None.
    monkeypatch.setattr("hub_private.broker_verifier._get_bitget_client", lambda: None)
    monkeypatch.setattr("hub_private.broker_verifier._get_weex_client", lambda: None)
    monkeypatch.setattr("hub_private.broker_verifier._get_bybit_client", lambda: None)
    monkeypatch.setattr("hub_private.broker_verifier._get_okx_client", lambda: None)

    db_session.add(_make_config())
    await db_session.commit()

    verified = await _add_report(db_session, "VERIFIED", "weex", "node-a")
    pending = await _add_report(db_session, "PENDING", "bitget", "virtual-999")

    await _run_epoch(db_session)

    assert await _get_epoch(db_session) is None
    await db_session.refresh(verified)
    await db_session.refresh(pending)
    assert verified.epoch_date is None
    assert pending.verification_status == "PENDING"


async def test_epoch_finalizes_once_all_resolved(db_session: AsyncSession, monkeypatch):
    """After the pending trade is confirmed, the epoch finalizes with both."""
    monkeypatch.setattr("hub_private.broker_verifier._get_bitget_client", lambda: None)
    monkeypatch.setattr("hub_private.broker_verifier._get_weex_client", lambda: None)
    monkeypatch.setattr("hub_private.broker_verifier._get_bybit_client", lambda: None)
    monkeypatch.setattr("hub_private.broker_verifier._get_okx_client", lambda: None)

    db_session.add(_make_config())
    await db_session.commit()

    await _add_report(db_session, "VERIFIED", "weex", "node-a")
    pending = await _add_report(db_session, "PENDING", "bitget", "virtual-999")

    await _run_epoch(db_session)
    assert await _get_epoch(db_session) is None

    # Operator resolves the pending trade (e.g. via XLSX import).
    pending.verification_status = "VERIFIED"
    pending.is_verified = True
    pending.verified_at = datetime.datetime.now(datetime.timezone.utc)
    await db_session.commit()

    await _run_epoch(db_session)
    epoch = await _get_epoch(db_session)
    assert epoch is not None
    assert epoch.status == "finalized"
    assert epoch.total_rebate_pool == pytest.approx(0.10)
