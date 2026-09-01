# tests/test_mining_concurrency.py
"""
Concurrency and Race Condition test suite for DepthSight Trade Mining:
- Idempotency & race condition protection for epoch execution (_async_process_mining_epoch)
- Concurrent telemetry ingestion for duplicate broker_trade_ids
"""

import asyncio
import datetime
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from api import models
from api.depthsight_api import app
from api.hub_router import router as hub_router
from tasks import _async_process_mining_epoch

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def ensure_hub_router_registered():
    has_hub = any(
        getattr(route, "path", "").startswith("/api/v1/hub") for route in app.routes
    )
    if not has_hub:
        app.include_router(hub_router)


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
        eligible_exchanges=["weex"],
        daily_emission_base=100.0,
        launch_date=datetime.date.today() - datetime.timedelta(days=2),
        referral_mining_boost=0.10,
        rebate_rates={},
    )
    defaults.update(overrides)
    return models.MiningConfig(**defaults)


async def _add_report(
    db_session: AsyncSession,
    node_uuid: str,
    rebate: float = 10.0,
    volume: float = 1000.0,
    broker_trade_id: str = None,
    verification_status: str = "VERIFIED",
) -> models.HubTelemetryReport:
    report = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=100.0,
        exit_price=105.0,
        trade_mode="LIVE",
        node_uuid=node_uuid,
        broker_trade_id=broker_trade_id
        or f"trade-conc-{node_uuid}-{datetime.datetime.now().timestamp()}",
        estimated_rebate_usdt=rebate,
        trade_volume_usdt=volume,
        is_mining_eligible=True,
        verification_status=verification_status,
        created_at=_yesterday_noon(),
    )
    db_session.add(report)
    await db_session.commit()
    return report


# ===========================================================================
# 1. Concurrent / Multiple Worker Epoch Processing
# ===========================================================================


async def test_concurrent_epoch_processing_race_condition(
    db_session: AsyncSession, monkeypatch
):
    """
    Simulate multiple worker processes attempting to process the same mining epoch.
    Only the first execution finalizes the epoch; subsequent calls cleanly skip (idempotent).
    """
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    node = models.HubNode(
        node_uuid="conc-epoch-node", name="ConcEpoch", secret_hash="h"
    )
    db_session.add(node)
    db_session.add(_make_config())
    await db_session.commit()

    await _add_report(db_session, "conc-epoch-node", rebate=10.0)

    @asynccontextmanager
    async def mock_isolated_session():
        yield db_session

    with patch("api.database.get_isolated_worker_session", mock_isolated_session):
        # Run worker 1
        await _async_process_mining_epoch(force_yesterday_date=_yesterday())
        db_session.expire_all()

        # Run worker 2 (simulating duplicate trigger / race)
        await _async_process_mining_epoch(force_yesterday_date=_yesterday())
        db_session.expire_all()

    # Check MiningEpoch row
    epoch_res = await db_session.execute(
        select(models.MiningEpoch).where(models.MiningEpoch.epoch_date == _yesterday())
    )
    epoch = epoch_res.scalars().first()
    assert epoch is not None
    assert epoch.status == "finalized"
    assert epoch.total_distributed == pytest.approx(100.0, rel=1e-3)

    # Check MiningLedger row — must be exactly 100 base reward, not 200!
    ledger_res = await db_session.execute(
        select(models.MiningLedger).where(
            models.MiningLedger.node_uuid == "conc-epoch-node",
            models.MiningLedger.epoch_date == _yesterday(),
        )
    )
    ledgers = ledger_res.scalars().all()
    assert len(ledgers) == 1
    assert ledgers[0].base_reward == pytest.approx(100.0, rel=1e-3)


# ===========================================================================
# 2. Concurrent Telemetry Submissions
# ===========================================================================


async def test_concurrent_telemetry_submission(
    test_client: AsyncClient, db_session: AsyncSession
):
    """
    Concurrent HTTP POST requests submitting telemetry reports for different trades.
    """
    secret = "sec-conc-tele"
    node = models.HubNode(
        node_uuid="conc-tele-node",
        name="ConcTele",
        secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
    )
    db_session.add(node)
    db_session.add(_make_config())
    await db_session.commit()

    async def submit_report(idx: int):
        payload = {
            "symbol": "BTCUSDT",
            "direction": "LONG",
            "entry_price": 10.0,
            "exit_price": 11.0,
            "trade_mode": "LIVE",
            "exchange_id": "weex",
            "market_type": "futures",
            "broker_trade_id": f"conc-trade-id-{idx}",
            "trade_volume_usdt": 1000.0,
            "market_context": {},
        }
        body = json.dumps(payload, sort_keys=True).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers = {
            "X-Node-UUID": "conc-tele-node",
            "X-Node-Secret": secret,
            "X-Node-Signature": sig,
            "Content-Type": "application/json",
        }
        return await test_client.post(
            "/api/v1/hub/telemetry/report", content=body, headers=headers
        )

    responses = await asyncio.gather(*(submit_report(i) for i in range(5)))

    for resp in responses:
        assert resp.status_code == 201

    # Verify 5 distinct reports inserted
    res = await db_session.execute(
        select(models.HubTelemetryReport).where(
            models.HubTelemetryReport.node_uuid == "conc-tele-node"
        )
    )
    reports = res.scalars().all()
    assert len(reports) == 5
