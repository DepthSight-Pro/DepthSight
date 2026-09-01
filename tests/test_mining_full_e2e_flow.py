# tests/test_mining_full_e2e_flow.py
"""
Full End-to-End (E2E) Integration test for DepthSight Trade Mining:
Simulates a real multi-node ecosystem lifecycle:
1. Hub Operator Root setup & MiningConfig initialization with real production emission (547,945.21 $DEPTH/day).
2. Referrer (Node A) wallet binding & referral code generation.
3. Mining Server S registration with custom commission split (80% user / 20% server).
4. Child Node B invited via Node A's referral code & wallet binding.
5. HMAC signed telemetry submission via HTTP POST endpoints.
6. Trade verification & daily epoch execution (_async_process_mining_epoch).
7. Full financial ledger audit & PWA API read endpoints verification.
"""

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

REAL_DAILY_EMISSION = 547945.21  # Production default daily emission base


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


async def _run_epoch(db_session: AsyncSession):
    @asynccontextmanager
    async def mock_isolated_session():
        yield db_session

    with patch("api.database.get_isolated_worker_session", mock_isolated_session):
        await _async_process_mining_epoch(force_yesterday_date=_yesterday())
    db_session.expire_all()


async def test_full_mining_lifecycle_e2e(
    test_client: AsyncClient, db_session: AsyncSession
):
    """
    Complete E2E multi-node mining lifecycle test with real production daily emission (547,945.21 $DEPTH/day):
    - Node A (Referrer, Direct)
    - Node B (Referred by Node A, routed via Server S)
    - Server S (Mining Server with 80/20 share)
    - Operator Root (Central Hub)
    """
    # -----------------------------------------------------------------------
    # Step 1: Initialize Global Mining Config & Hub Operator Root
    # -----------------------------------------------------------------------
    op_root = models.HubNode(
        node_uuid="op-root-e2e",
        name="HubOperatorRoot",
        secret_hash=hashlib.sha256(b"sec-op").hexdigest(),
        is_operator=True,
    )
    db_session.add(op_root)

    mining_cfg = models.MiningConfig(
        id=1,
        is_mining_enabled=True,
        eligible_exchanges=["weex"],
        daily_emission_base=REAL_DAILY_EMISSION,  # 547,945.21 $DEPTH
        launch_date=datetime.date.today() - datetime.timedelta(days=2),
        referral_mining_boost=0.10,
    )
    node_cfg = models.NodeMiningConfig(
        id=1,
        is_global_mining_enabled=True,
        user_reward_share_percent=75.0,  # Central default: 75% user, 25% hub operator
    )
    db_session.add_all([mining_cfg, node_cfg])
    await db_session.commit()

    # -----------------------------------------------------------------------
    # Step 2: Register Referrer (Node A) & Binding
    # -----------------------------------------------------------------------
    sec_a = "sec-node-a"
    node_a = models.HubNode(
        node_uuid="node-a-uuid",
        name="NodeA_Referrer",
        secret_hash=hashlib.sha256(sec_a.encode()).hexdigest(),
        node_referral_code="REF-CODE-A",
        wallet_address="0x1111111111111111111111111111111111111111",
        weex_uid="WEEX-UID-A",
    )
    db_session.add(node_a)

    # -----------------------------------------------------------------------
    # Step 3: Register Mining Server S (Custom 80/20 Commission Split)
    # -----------------------------------------------------------------------
    sec_s = "sec-server-s"
    server_s = models.HubNode(
        node_uuid="server-s-uuid",
        name="MiningServerS",
        secret_hash=hashlib.sha256(sec_s.encode()).hexdigest(),
        is_mining_server=True,
        wallet_address="0xSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSS",
    )
    db_session.add(server_s)
    db_session.add(
        models.HubServerConfig(
            node_uuid="server-s-uuid", user_reward_share_percent=80.0
        )
    )

    # -----------------------------------------------------------------------
    # Step 4: Register Child Node B (Referred by Node A)
    # -----------------------------------------------------------------------
    sec_b = "sec-node-b"
    node_b = models.HubNode(
        node_uuid="node-b-uuid",
        name="NodeB_Child",
        secret_hash=hashlib.sha256(sec_b.encode()).hexdigest(),
        node_referral_code="REF-CODE-B",
        referrer_node_uuid="node-a-uuid",  # Referred by Node A!
        wallet_address="0x2222222222222222222222222222222222222222",
        weex_uid="WEEX-UID-B",
    )
    db_session.add(node_b)
    await db_session.commit()

    # -----------------------------------------------------------------------
    # Step 5: Telemetry Submissions via HTTP API with HMAC Signatures
    # -----------------------------------------------------------------------

    # Trade 1: Submitted by Node A (direct to hub). Volume $10k, Rebate $5.0
    payload_a = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry_price": 60000.0,
        "exit_price": 61500.0,
        "pnl_percent": 2.5,
        "trade_duration_sec": 1200,
        "trade_mode": "LIVE",
        "exchange_id": "weex",
        "market_type": "futures",
        "broker_trade_id": "trade-e2e-a-100",
        "trade_volume_usdt": 10000.0,
        "strategy_blocks": [{"type": "breakout", "params": {}}],
        "market_context": {},
    }
    body_a = json.dumps(payload_a, sort_keys=True).encode()
    sig_a = hmac.new(sec_a.encode(), body_a, hashlib.sha256).hexdigest()

    resp_a = await test_client.post(
        "/api/v1/hub/telemetry/report",
        content=body_a,
        headers={
            "X-Node-UUID": "node-a-uuid",
            "X-Node-Secret": sec_a,
            "X-Node-Signature": sig_a,
            "Content-Type": "application/json",
        },
    )
    assert resp_a.status_code == 201

    # Trade 2: Submitted by Node B (routed via Mining Server S). Volume $10k, Rebate $5.0
    payload_b = {
        "symbol": "ETHUSDT",
        "direction": "SHORT",
        "entry_price": 3000.0,
        "exit_price": 2940.0,
        "pnl_percent": 2.0,
        "trade_duration_sec": 1800,
        "trade_mode": "LIVE",
        "exchange_id": "weex",
        "market_type": "futures",
        "broker_trade_id": "trade-e2e-b-200",
        "trade_volume_usdt": 10000.0,
        "source_node_uuid": "server-s-uuid",  # Mined via Server S!
        "strategy_blocks": [{"type": "grid", "params": {}}],
        "market_context": {},
    }
    body_b = json.dumps(payload_b, sort_keys=True).encode()
    sig_b = hmac.new(sec_b.encode(), body_b, hashlib.sha256).hexdigest()

    resp_b = await test_client.post(
        "/api/v1/hub/telemetry/report",
        content=body_b,
        headers={
            "X-Node-UUID": "node-b-uuid",
            "X-Node-Secret": sec_b,
            "X-Node-Signature": sig_b,
            "Content-Type": "application/json",
        },
    )
    assert resp_b.status_code == 201

    # Set created_at to yesterday for epoch processing
    reports_res = await db_session.execute(select(models.HubTelemetryReport))
    for r in reports_res.scalars().all():
        r.created_at = _yesterday_noon()
        r.verification_status = "VERIFIED"
    await db_session.commit()

    # -----------------------------------------------------------------------
    # Step 6: Process Daily Mining Epoch
    # -----------------------------------------------------------------------
    await _run_epoch(db_session)

    # -----------------------------------------------------------------------
    # Step 7: Comprehensive Financial Ledger Audit with Real Production Emission
    # -----------------------------------------------------------------------
    epoch_res = await db_session.execute(
        select(models.MiningEpoch).where(models.MiningEpoch.epoch_date == _yesterday())
    )
    epoch = epoch_res.scalars().first()
    assert epoch is not None
    assert epoch.status == "finalized"
    # New semantics: only nodes that actually MINED (base_points > 0).
    # Node A + Node B mined; Server S and Operator Root only receive commission.
    assert epoch.participating_nodes == 2

    # Fetch Ledgers
    res_ledger_a = await db_session.execute(
        select(models.MiningLedger).where(
            models.MiningLedger.node_uuid == "node-a-uuid",
            models.MiningLedger.epoch_date == _yesterday(),
        )
    )
    ledger_a = res_ledger_a.scalars().first()

    res_ledger_b = await db_session.execute(
        select(models.MiningLedger).where(
            models.MiningLedger.node_uuid == "node-b-uuid",
            models.MiningLedger.epoch_date == _yesterday(),
        )
    )
    ledger_b = res_ledger_b.scalars().first()

    res_ledger_s = await db_session.execute(
        select(models.MiningLedger).where(
            models.MiningLedger.node_uuid == "server-s-uuid",
            models.MiningLedger.epoch_date == _yesterday(),
        )
    )
    ledger_s = res_ledger_s.scalars().first()

    res_ledger_op = await db_session.execute(
        select(models.MiningLedger).where(
            models.MiningLedger.node_uuid == "op-root-e2e",
            models.MiningLedger.epoch_date == _yesterday(),
        )
    )
    ledger_op = res_ledger_op.scalars().first()

    # Math Verification for Real Daily Emission (547,945.21 $DEPTH/day):
    # Total points = 10.5. Token value per point = 547945.21 / 10.5 = 52185.258095
    # Node A base = 195694.7178 $DEPTH
    # Node A referral bonus = 26092.6290 $DEPTH
    # Node B base = 208741.0323 $DEPTH
    # Server S commission = 52185.2580 $DEPTH
    # Operator Root fee = 65231.5726 $DEPTH

    assert ledger_a is not None
    assert ledger_a.base_reward == pytest.approx(195694.7178, rel=1e-3)
    assert ledger_a.referral_bonus == pytest.approx(26092.6290, rel=1e-3)

    assert ledger_b is not None
    assert ledger_b.base_reward == pytest.approx(208741.0323, rel=1e-3)

    assert ledger_s is not None
    assert ledger_s.base_reward == pytest.approx(
        52185.2580, rel=1e-3
    )  # 20% commission on Node B

    assert ledger_op is not None
    assert ledger_op.base_reward == pytest.approx(
        65231.5726, rel=1e-3
    )  # 25% operator fee on Node A

    # Total Base Emissions + Referral Bonus + Fees must equal EXACTLY REAL_DAILY_EMISSION (547,945.21 $DEPTH)!
    total_distributed_epoch = (
        ledger_a.base_reward
        + ledger_a.referral_bonus
        + ledger_b.base_reward
        + ledger_s.base_reward
        + ledger_op.base_reward
    )
    assert total_distributed_epoch == pytest.approx(REAL_DAILY_EMISSION, rel=1e-3)

    # -----------------------------------------------------------------------
    # Step 8: Verify Read API Endpoints
    # -----------------------------------------------------------------------
    headers_a = {"X-Node-UUID": "node-a-uuid", "X-Node-Secret": sec_a}
    resp_status_a = await test_client.get(
        "/api/v1/hub/mining/status", headers=headers_a
    )
    assert resp_status_a.status_code == 200
    status_data_a = resp_status_a.json()
    assert status_data_a["yourTotalMined"] > 200000.0

    resp_ref_a = await test_client.get(
        "/api/v1/hub/mining/referrals", headers=headers_a
    )
    assert resp_ref_a.status_code == 200
    ref_data_a = resp_ref_a.json()
    assert len(ref_data_a["referrals"]) == 1
    assert ref_data_a["referrals"][0]["name"] == "NodeB_Child"
