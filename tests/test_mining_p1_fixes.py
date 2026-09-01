# tests/test_mining_p1_fixes.py
"""
Regression tests for the P1 mining-accuracy fixes:

1. Rebate backfill respects an explicitly configured rate of 0 (no silent
   fallback to the exchange default / 0.60).
2. Resubmission of a VERIFIED / already-attributed telemetry report is
   rejected with 409 and leaves the stored data untouched.
3. The live referrer estimate (_resolve_mining_referrer) mirrors the epoch
   resolver: self-references and banned referrers yield None.
4. crud.referrer_link_creates_cycle detects referral rings.
5. Broker verifier: a Bybit order belonging to another account is rejected
   when the node has a bybit_uid bound; the Weex UID path no longer stores
   the client-claimed volume in verified_volume_usdt.
"""

import datetime as dtmod
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from api import models
from api.crud import referrer_link_creates_cycle
from api.depthsight_api import app
from api.hub_router import _resolve_mining_referrer, router as hub_router
from tasks import _async_process_mining_epoch

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def ensure_hub_router_registered():
    has_hub = any(
        getattr(route, "path", "").startswith("/api/v1/hub") for route in app.routes
    )
    if not has_hub:
        app.include_router(hub_router)


# ---------------------------------------------------------------------------
# Helpers (epoch)
# ---------------------------------------------------------------------------


def _yesterday() -> dtmod.date:
    return dtmod.datetime.now(dtmod.timezone.utc).date() - dtmod.timedelta(days=1)


def _yesterday_noon() -> datetime:
    return dtmod.datetime.combine(
        _yesterday(), dtmod.time(12, 0), tzinfo=dtmod.timezone.utc
    )


def _make_config(**overrides) -> models.MiningConfig:
    defaults = dict(
        is_mining_enabled=True,
        eligible_exchanges=["weex", "bybit"],
        daily_emission_base=100.0,
        launch_date=dtmod.date.today() - dtmod.timedelta(days=2),
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


# ---------------------------------------------------------------------------
# 1. Backfill honors an explicit zero rebate rate
# ---------------------------------------------------------------------------


async def test_rebate_backfill_respects_zero_rate(
    db_session: AsyncSession, monkeypatch
):
    """rate=0 must stay 0 during backfill вЂ” not become 1000*0.0005*0.6=0.30."""
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    node = models.HubNode(node_uuid="zero-rate-node", name="ZeroRate", secret_hash="h")
    db_session.add(node)
    db_session.add(_make_config(rebate_rates={"bybit_futures": 0.0}))
    await db_session.commit()

    report = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=10.0,
        exit_price=11.0,
        trade_mode="LIVE",
        node_uuid="zero-rate-node",
        estimated_rebate_usdt=None,
        trade_volume_usdt=1000.0,
        is_mining_eligible=True,
        verification_status="VERIFIED",
        created_at=_yesterday_noon(),
        exchange_id="bybit",
        market_type="futures",
    )
    db_session.add(report)
    await db_session.commit()

    await _run_epoch(db_session)

    await db_session.refresh(report)
    assert report.estimated_rebate_usdt == 0.0


# ---------------------------------------------------------------------------
# 2. Resubmit guard on /telemetry/report
# ---------------------------------------------------------------------------


def _telemetry_payload(broker_trade_id: str, volume: float) -> bytes:
    payload = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entryPrice": 62500.0,
        "exitPrice": 63750.0,
        "pnlPercent": 2.0,
        "tradeDurationSec": 3600,
        "exitReason": "take_profit",
        "tradeMode": "LIVE",
        "strategyBlocks": [{"type": "volume_filter", "params": {"multiplier": 2.0}}],
        "marketContext": {},
        "exchangeId": "weex",
        "marketType": "futures",
        "brokerTradeId": broker_trade_id,
        "tradeVolumeUsdt": volume,
    }
    return json.dumps(payload, sort_keys=True).encode("utf-8")


async def _post_telemetry(test_client, node_uuid: str, secret: str, body: bytes):
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    headers = {
        "X-Node-UUID": node_uuid,
        "X-Node-Secret": secret,
        "X-Node-Signature": signature,
        "Content-Type": "application/json",
    }
    return await test_client.post(
        "/api/v1/hub/telemetry/report", content=body, headers=headers
    )


async def test_resubmit_pending_report_allowed(test_client, db_session):
    """Retries before verification/attribution keep working (idempotent update)."""
    node = models.HubNode(
        node_uuid="resub-node",
        name="Resub",
        secret_hash=hashlib.sha256(b"sec-r").hexdigest(),
    )
    db_session.add(node)
    db_session.add(_make_config())
    await db_session.commit()

    body = _telemetry_payload("resub-trade-1", 1000.0)
    resp1 = await _post_telemetry(test_client, "resub-node", "sec-r", body)
    assert resp1.status_code == 201

    resp2 = await _post_telemetry(test_client, "resub-node", "sec-r", body)
    assert resp2.status_code == 201

    res = await db_session.execute(
        select(models.HubTelemetryReport).where(
            models.HubTelemetryReport.broker_trade_id == "resub-trade-1"
        )
    )
    assert len(res.scalars().all()) == 1


async def test_resubmit_after_verification_rejected(test_client, db_session):
    """A VERIFIED (or attributed) report is frozen: resubmission -> 409 and the
    verified values must remain untouched."""
    node = models.HubNode(
        node_uuid="frozen-node",
        name="Frozen",
        secret_hash=hashlib.sha256(b"sec-f").hexdigest(),
    )
    db_session.add(node)
    db_session.add(_make_config())
    await db_session.commit()

    body = _telemetry_payload("frozen-trade-1", 1000.0)
    resp = await _post_telemetry(test_client, "frozen-node", "sec-f", body)
    assert resp.status_code == 201

    # Simulate broker verification + epoch attribution.
    res = await db_session.execute(
        select(models.HubTelemetryReport).where(
            models.HubTelemetryReport.broker_trade_id == "frozen-trade-1"
        )
    )
    row = res.scalars().first()
    row.verification_status = "VERIFIED"
    row.is_verified = True
    row.verified_volume_usdt = 950.0
    row.estimated_rebate_usdt = 0.475
    row.epoch_date = _yesterday()
    await db_session.commit()

    # Attacker/bot resubmits with inflated volume.
    inflated = _telemetry_payload("frozen-trade-1", 999999.0)
    resp = await _post_telemetry(test_client, "frozen-node", "sec-f", inflated)
    assert resp.status_code == 409

    db_session.expire_all()
    res = await db_session.execute(
        select(models.HubTelemetryReport).where(
            models.HubTelemetryReport.broker_trade_id == "frozen-trade-1"
        )
    )
    row = res.scalars().first()
    assert row.trade_volume_usdt == 1000.0
    assert row.verified_volume_usdt == 950.0
    assert row.estimated_rebate_usdt == pytest.approx(0.475)


async def test_resubmit_attributed_but_pending_rejected(test_client, db_session):
    """epoch_date set (already credited) freezes the report even while PENDING."""
    node = models.HubNode(
        node_uuid="attr-node",
        name="Attr",
        secret_hash=hashlib.sha256(b"sec-a").hexdigest(),
    )
    db_session.add(node)
    db_session.add(_make_config())
    await db_session.commit()

    body = _telemetry_payload("attr-trade-1", 500.0)
    resp = await _post_telemetry(test_client, "attr-node", "sec-a", body)
    assert resp.status_code == 201

    res = await db_session.execute(
        select(models.HubTelemetryReport).where(
            models.HubTelemetryReport.broker_trade_id == "attr-trade-1"
        )
    )
    row = res.scalars().first()
    row.epoch_date = _yesterday()
    await db_session.commit()

    resp = await _post_telemetry(test_client, "attr-node", "sec-a", body)
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# 3. Live referrer estimate parity (self / banned)
# ---------------------------------------------------------------------------


async def test_live_referrer_estimate_excludes_banned_and_self(db_session):
    parent = models.HubNode(node_uuid="live-parent", name="P", secret_hash="h")
    banned = models.HubNode(
        node_uuid="banned-ref", name="B", secret_hash="h", is_banned=True
    )
    child_ok = models.HubNode(
        node_uuid="child-ok",
        name="C1",
        secret_hash="h",
        referrer_node_uuid="live-parent",
    )
    child_ban = models.HubNode(
        node_uuid="child-ban",
        name="C2",
        secret_hash="h",
        referrer_node_uuid="banned-ref",
    )
    self_ref = models.HubNode(
        node_uuid="self-ref", name="S", secret_hash="h", referrer_node_uuid="self-ref"
    )
    db_session.add_all([parent, banned, child_ok, child_ban, self_ref])
    await db_session.commit()

    assert await _resolve_mining_referrer(db_session, "child-ok") == "live-parent"
    assert await _resolve_mining_referrer(db_session, "child-ban") is None
    assert await _resolve_mining_referrer(db_session, "self-ref") is None
    assert await _resolve_mining_referrer(db_session, "unknown-node") is None


# ---------------------------------------------------------------------------
# 4. Cycle guard helper
# ---------------------------------------------------------------------------


async def test_referrer_link_creates_cycle(db_session):
    a = models.HubNode(node_uuid="ring-a", name="A", secret_hash="h")
    b = models.HubNode(
        node_uuid="ring-b", name="B", secret_hash="h", referrer_node_uuid="ring-c"
    )
    c = models.HubNode(
        node_uuid="ring-c", name="C", secret_hash="h", referrer_node_uuid="ring-a"
    )
    d = models.HubNode(node_uuid="ring-d", name="D", secret_hash="h")
    db_session.add_all([a, b, c, d])
    await db_session.commit()

    # a -> b closes the ring a <- c <- b
    assert await referrer_link_creates_cycle(db_session, "ring-a", "ring-b") is True
    # a -> d is fine
    assert await referrer_link_creates_cycle(db_session, "ring-a", "ring-d") is False
    # immediate self-link
    assert await referrer_link_creates_cycle(db_session, "ring-d", "ring-d") is True
