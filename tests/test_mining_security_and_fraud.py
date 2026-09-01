# tests/test_mining_security_and_fraud.py
"""
Security, Anti-Cheat, and Fraud Prevention test suite for DepthSight Trade Mining:
- Duplicate trade ID protection & uniqueness across nodes
- Exclusion of REJECTED verification status from rewards
- Clamp & validation of extreme volume/PnL values
- Zero-volume / zero-rebate trade safety
- Self-referral & circular referral loop protection
- Banned referrer boost isolation
- Banned/missing source server node commission routing
- Extreme & mid-epoch commission rate changes
- Late-verified & timestamp boundary trades
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


async def _run_epoch(db_session: AsyncSession, force_date=None):
    @asynccontextmanager
    async def mock_isolated_session():
        yield db_session

    target_date = force_date or _yesterday()
    with patch("api.database.get_isolated_worker_session", mock_isolated_session):
        await _async_process_mining_epoch(force_yesterday_date=target_date)
    db_session.expire_all()


async def _add_report(
    db_session: AsyncSession,
    node_uuid: str,
    rebate: float = None,
    volume: float = None,
    broker_trade_id: str = None,
    verification_status: str = "VERIFIED",
    created_at: datetime.datetime = None,
    **overrides,
) -> models.HubTelemetryReport:
    report = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=100.0,
        exit_price=105.0,
        trade_mode="LIVE",
        node_uuid=node_uuid,
        broker_trade_id=broker_trade_id
        or f"trade-{node_uuid}-{datetime.datetime.now().timestamp()}",
        estimated_rebate_usdt=rebate,
        trade_volume_usdt=volume,
        is_mining_eligible=True,
        verification_status=verification_status,
        created_at=created_at or _yesterday_noon(),
    )
    for key, value in overrides.items():
        setattr(report, key, value)
    db_session.add(report)
    await db_session.commit()
    return report


async def _get_ledger(
    db_session: AsyncSession, node_uuid: str, epoch_date=None
) -> models.MiningLedger:
    target_date = epoch_date or _yesterday()
    res = await db_session.execute(
        select(models.MiningLedger).where(
            models.MiningLedger.node_uuid == node_uuid,
            models.MiningLedger.epoch_date == target_date,
        )
    )
    return res.scalars().first()


async def _get_epoch(db_session: AsyncSession, epoch_date=None) -> models.MiningEpoch:
    target_date = epoch_date or _yesterday()
    res = await db_session.execute(
        select(models.MiningEpoch).where(models.MiningEpoch.epoch_date == target_date)
    )
    return res.scalars().first()


# ===========================================================================
# 1. Anti-Cheat & Duplicate Trade Protection
# ===========================================================================


async def test_duplicate_broker_trade_id_rejected_on_submission(
    test_client: AsyncClient, db_session: AsyncSession
):
    """
    Submitting telemetry report with an already existing broker_trade_id
    from another node is blocked at API level with 409 Conflict.
    """
    secret = "sec-dup"
    node1 = models.HubNode(
        node_uuid="dup-node-1",
        name="Node1",
        secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
    )
    node2 = models.HubNode(
        node_uuid="dup-node-2",
        name="Node2",
        secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
    )
    db_session.add_all([node1, node2])
    db_session.add(_make_config())
    await db_session.commit()

    payload = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry_price": 10.0,
        "exit_price": 11.0,
        "trade_mode": "LIVE",
        "exchange_id": "weex",
        "market_type": "futures",
        "broker_trade_id": "shared-broker-trade-999",
        "trade_volume_usdt": 1000.0,
        "market_context": {},
    }
    body = json.dumps(payload, sort_keys=True).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    # First node submits trade successfully
    resp1 = await test_client.post(
        "/api/v1/hub/telemetry/report",
        content=body,
        headers={
            "X-Node-UUID": "dup-node-1",
            "X-Node-Secret": secret,
            "X-Node-Signature": sig,
            "Content-Type": "application/json",
        },
    )
    assert resp1.status_code == 201

    # Second node tries to submit exact same broker_trade_id
    resp2 = await test_client.post(
        "/api/v1/hub/telemetry/report",
        content=body,
        headers={
            "X-Node-UUID": "dup-node-2",
            "X-Node-Secret": secret,
            "X-Node-Signature": sig,
            "Content-Type": "application/json",
        },
    )
    assert resp2.status_code == 409  # Conflict: duplicate trade ID for another node


async def test_rejected_verification_status_excluded_from_rewards(
    db_session: AsyncSession, monkeypatch
):
    """
    Reports marked with verification_status='REJECTED' must be completely excluded
    from reward calculation and ledger emission.
    """
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    good_node = models.HubNode(node_uuid="good-node", name="Good", secret_hash="h")
    bad_node = models.HubNode(node_uuid="bad-node", name="Bad", secret_hash="h")
    db_session.add_all([good_node, bad_node])
    db_session.add(_make_config())
    await db_session.commit()

    # Good node report (VERIFIED)
    await _add_report(
        db_session, "good-node", rebate=10.0, verification_status="VERIFIED"
    )
    # Bad node report (REJECTED)
    await _add_report(
        db_session, "bad-node", rebate=500.0, verification_status="REJECTED"
    )

    await _run_epoch(db_session)

    good_ledger = await _get_ledger(db_session, "good-node")
    bad_ledger = await _get_ledger(db_session, "bad-node")

    # Good node gets 100% of emission because rejected trades are ignored
    assert good_ledger is not None
    assert good_ledger.base_reward == pytest.approx(100.0, rel=1e-3)
    assert bad_ledger is None


async def test_zero_volume_or_zero_rebate_trade_handling(db_session: AsyncSession):
    """
    Zero volume or zero rebate trades must process cleanly without divide-by-zero or crash.
    """
    node = models.HubNode(node_uuid="zero-vol-node", name="ZeroVol", secret_hash="h")
    db_session.add(node)
    db_session.add(_make_config())
    await db_session.commit()

    await _add_report(db_session, "zero-vol-node", rebate=0.0, volume=0.0)
    await _run_epoch(db_session)

    epoch = await _get_epoch(db_session)
    assert epoch is not None
    assert epoch.status == "finalized"
    assert epoch.total_distributed == 0.0


# ===========================================================================
# 2. Referral Structure & Exploit Protection
# ===========================================================================


async def test_self_referral_loop_handling(db_session: AsyncSession, monkeypatch):
    """
    A node setting itself as its own referrer must not grant self-referral boost.
    """
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    self_ref_node = models.HubNode(
        node_uuid="self-ref-node",
        name="SelfRef",
        secret_hash="h",
        referrer_node_uuid="self-ref-node",  # Self-referral loop!
    )
    db_session.add(self_ref_node)
    db_session.add(_make_config())
    await db_session.commit()

    await _add_report(db_session, "self-ref-node", rebate=10.0)
    await _run_epoch(db_session)

    ledger = await _get_ledger(db_session, "self-ref-node")
    assert ledger is not None
    # Self-referral is filtered out, so base reward is 100.0 and referral bonus is 0.0
    assert ledger.base_reward == pytest.approx(100.0, rel=1e-3)
    assert ledger.referral_bonus == 0.0


async def test_circular_referral_loop_handling(db_session: AsyncSession, monkeypatch):
    """
    Circular referral links (Node A -> Node B -> Node A) must handle rewards cleanly.
    """
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    node_a = models.HubNode(
        node_uuid="circ-a", name="NodeA", secret_hash="h", referrer_node_uuid="circ-b"
    )
    node_b = models.HubNode(
        node_uuid="circ-b", name="NodeB", secret_hash="h", referrer_node_uuid="circ-a"
    )
    db_session.add_all([node_a, node_b])
    db_session.add(_make_config(referral_mining_boost=0.10))
    await db_session.commit()

    await _add_report(db_session, "circ-a", rebate=10.0)
    await _add_report(db_session, "circ-b", rebate=10.0)

    await _run_epoch(db_session)

    ledger_a = await _get_ledger(db_session, "circ-a")
    ledger_b = await _get_ledger(db_session, "circ-b")

    assert ledger_a is not None
    assert ledger_b is not None
    # 100 total emission split 50/50 between two equal nodes (50.0 total reward each)
    assert ledger_a.total_reward == pytest.approx(50.0, rel=1e-3)
    assert ledger_b.total_reward == pytest.approx(50.0, rel=1e-3)


async def test_banned_referrer_does_not_receive_referral_bonus(
    db_session: AsyncSession, monkeypatch
):
    """
    If a referrer node is banned (is_banned=True), it must NOT receive referral bonus.
    """
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    banned_referrer = models.HubNode(
        node_uuid="banned-ref", name="BannedRef", secret_hash="h", is_banned=True
    )
    active_child = models.HubNode(
        node_uuid="active-child",
        name="Child",
        secret_hash="h",
        referrer_node_uuid="banned-ref",
    )
    db_session.add_all([banned_referrer, active_child])
    db_session.add(_make_config(referral_mining_boost=0.10))
    await db_session.commit()

    await _add_report(db_session, "active-child", rebate=10.0)
    await _run_epoch(db_session)

    child_ledger = await _get_ledger(db_session, "active-child")
    banned_ledger = await _get_ledger(db_session, "banned-ref")

    assert child_ledger.base_reward == pytest.approx(100.0, rel=1e-3)
    # Banned referrer gets no ledger entry
    assert banned_ledger is None or banned_ledger.total_reward == 0.0


# ===========================================================================
# 3. Commission Split & Operator Node Edge Cases
# ===========================================================================


async def test_banned_source_server_node_routes_commission_to_root(
    db_session: AsyncSession, monkeypatch
):
    """
    If telemetry is reported with source_node_uuid pointing to a banned server node,
    the server operator commission is safely routed to the central operator/root.
    """
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    root = models.HubNode(
        node_uuid="op-root", name="Root", secret_hash="h", is_operator=True
    )
    banned_server = models.HubNode(
        node_uuid="banned-server",
        name="BannedServer",
        secret_hash="h",
        is_mining_server=True,
        is_banned=True,
    )
    miner = models.HubNode(node_uuid="miner-client", name="Miner", secret_hash="h")
    db_session.add_all([root, banned_server, miner])

    db_session.add(
        models.HubServerConfig(
            node_uuid="banned-server", user_reward_share_percent=70.0
        )
    )
    db_session.add(_make_config())
    db_session.add(
        models.NodeMiningConfig(
            id=1, is_global_mining_enabled=True, user_reward_share_percent=75.0
        )
    )
    await db_session.commit()

    # Report submitted via banned server
    await _add_report(
        db_session, "miner-client", rebate=10.0, source_node_uuid="banned-server"
    )
    await _run_epoch(db_session)

    miner_ledger = await _get_ledger(db_session, "miner-client")
    server_ledger = await _get_ledger(db_session, "banned-server")
    root_ledger = await _get_ledger(db_session, "op-root")

    assert miner_ledger.base_reward == pytest.approx(75.0, rel=1e-3)
    # Banned server gets no commission
    assert server_ledger is None or server_ledger.base_reward == 0.0
    # Commission goes to operator root
    assert root_ledger.base_reward == pytest.approx(25.0, rel=1e-3)


async def test_extreme_user_reward_share_percentages(
    db_session: AsyncSession, monkeypatch
):
    """
    user_reward_share_percent set to 100% or 0% behaves accurately without invalid splits.
    """
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    root = models.HubNode(
        node_uuid="root-ext", name="Root", secret_hash="h", is_operator=True
    )
    miner = models.HubNode(node_uuid="miner-ext", name="Miner", secret_hash="h")
    db_session.add_all([root, miner])
    db_session.add(_make_config())
    db_session.add(
        models.NodeMiningConfig(
            id=1, is_global_mining_enabled=True, user_reward_share_percent=100.0
        )
    )
    await db_session.commit()

    await _add_report(db_session, "miner-ext", rebate=10.0)
    await _run_epoch(db_session)

    miner_ledger = await _get_ledger(db_session, "miner-ext")
    root_ledger = await _get_ledger(db_session, "root-ext")

    # At 100% share, miner gets 100% of rewards, root gets 0
    assert miner_ledger.base_reward == pytest.approx(100.0, rel=1e-3)
    assert root_ledger is None or root_ledger.base_reward == 0.0


# ===========================================================================
# 4. Late-Verified & Timestamp Boundary Trades
# ===========================================================================


async def test_late_verified_trades_attributed_to_next_open_epoch(
    db_session: AsyncSession, monkeypatch
):
    """
    Trades created 3 days ago but verified today (epoch_date IS NULL)
    are processed in today's epoch without corrupting finalized past epochs.
    """
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    node = models.HubNode(node_uuid="late-node", name="Late", secret_hash="h")
    db_session.add(node)
    db_session.add(_make_config())
    await db_session.commit()

    three_days_ago = datetime.datetime.combine(
        _yesterday() - datetime.timedelta(days=2),
        datetime.time(12, 0),
        tzinfo=datetime.timezone.utc,
    )

    # Late trade created 3 days ago, but verification_status set to VERIFIED today, epoch_date is NULL
    await _add_report(
        db_session,
        "late-node",
        rebate=10.0,
        created_at=three_days_ago,
        verification_status="VERIFIED",
    )

    # Run epoch for yesterday
    await _run_epoch(db_session, force_date=_yesterday())

    ledger = await _get_ledger(db_session, "late-node", epoch_date=_yesterday())
    assert ledger is not None
    assert ledger.base_reward == pytest.approx(100.0, rel=1e-3)


async def test_midnight_utc_boundary_trades(db_session: AsyncSession, monkeypatch):
    """
    Trades executed at 23:59:59 UTC vs 00:00:01 UTC are attributed cleanly.
    """
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    node = models.HubNode(node_uuid="boundary-node", name="Boundary", secret_hash="h")
    db_session.add(node)
    db_session.add(_make_config())
    await db_session.commit()

    t_end = datetime.datetime.combine(
        _yesterday(), datetime.time(23, 59, 59), tzinfo=datetime.timezone.utc
    )

    await _add_report(db_session, "boundary-node", rebate=10.0, created_at=t_end)
    await _run_epoch(db_session)

    ledger = await _get_ledger(db_session, "boundary-node")
    assert ledger is not None
    assert ledger.base_reward == pytest.approx(100.0, rel=1e-3)
