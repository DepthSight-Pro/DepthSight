# tests/test_hub_telemetry.py
import pytest
import hmac
import hashlib
import json
import datetime
from httpx import AsyncClient
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from api import models
from api.depthsight_api import app
from api.hub_router import router as hub_router
from tasks import _async_process_mining_epoch

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def ensure_hub_router_registered():
    """
    Dynamically registers the hub router on the app if it was not loaded on startup
    due to IS_CENTRAL_HUB being False by default.
    """
    has_hub = any(
        getattr(route, "path", "").startswith("/api/v1/hub") for route in app.routes
    )
    if not has_hub:
        app.include_router(hub_router)


async def test_post_telemetry_report(
    test_client: AsyncClient, db_session: AsyncSession
):
    """
    Test submitting an anonymous trade telemetry report with signature auth.
    """
    # 1. Create a dummy registered node
    node_uuid = "node-1234-test"
    node_secret = "super-secret-key-123"
    secret_hash = hashlib.sha256(node_secret.encode()).hexdigest()

    node = models.HubNode(
        node_uuid=node_uuid,
        name="TestNode",
        secret_hash=secret_hash,
    )
    db_session.add(node)

    # Enable mining config so report runs scoring
    config = models.MiningConfig(
        is_mining_enabled=True,
        eligible_exchanges=["weex"],
        daily_emission_base=1000.0,
    )
    db_session.add(config)
    await db_session.commit()

    payload = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entryPrice": 62500.0,
        "exitPrice": 63750.0,
        "pnlPercent": 2.0,
        "tradeDurationSec": 3600,
        "exitReason": "take_profit",
        "tradeMode": "LIVE",
        "strategyBlocks": [
            {"type": "triangle_breakout", "params": {"lookback": 20}},
            {"type": "volume_filter", "params": {"multiplier": 2.5}},
        ],
        "marketContext": {
            "session": "london",
            "natr": 0.075,
            "adx": 28.2,
            "volumeRatio": 1.5,
        },
        "exchangeId": "weex",
        "marketType": "futures",
        "brokerTradeId": "weex-order-1",
        "tradeVolumeUsdt": 10000.0,
    }

    body_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    signature = hmac.new(
        node_secret.encode("utf-8"), body_bytes, hashlib.sha256
    ).hexdigest()

    headers = {
        "X-Node-UUID": node_uuid,
        "X-Node-Secret": node_secret,
        "X-Node-Signature": signature,
        "Content-Type": "application/json",
    }

    response = await test_client.post(
        "/api/v1/hub/telemetry/report",
        content=body_bytes,
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["status"] == "success"

    # Query DB to check if report was stored and evaluated
    result = await db_session.execute(
        select(models.HubTelemetryReport).filter(
            models.HubTelemetryReport.symbol == "BTCUSDT"
        )
    )
    report_in_db = result.scalars().first()
    assert report_in_db is not None
    assert report_in_db.direction == "LONG"
    assert report_in_db.exchange_id == "weex"
    assert report_in_db.is_mining_eligible is True
    assert report_in_db.score > 0.0
    assert report_in_db.estimated_rebate_usdt > 0.0


async def test_get_mining_config(test_client: AsyncClient, db_session: AsyncSession):
    # Clear existing configs
    await db_session.execute(models.MiningConfig.__table__.delete())

    # Add a mock config
    config = models.MiningConfig(
        is_mining_enabled=True,
        eligible_exchanges=["weex", "bybit"],
        min_trade_duration_sec=45,
        referral_mining_boost=0.15,
    )
    db_session.add(config)
    await db_session.commit()

    response = await test_client.get("/api/v1/hub/mining/config")
    assert response.status_code == 200
    data = response.json()
    assert data["isMiningEnabled"] is True
    assert "weex" in data["eligibleExchanges"]
    assert data["minTradeDurationSec"] == 45
    assert data["referralMiningBoost"] == 0.15


async def test_nodes_referral_registration(
    test_client: AsyncClient, db_session: AsyncSession
):
    # Clear existing nodes
    await db_session.execute(models.HubNode.__table__.delete())
    await db_session.commit()  # 1. Register parent node
    reg_payload_parent = {
        "node_uuid": "parent-node-uuid",
        "name": "ParentNode",
        "node_secret": "secret-parent",
    }
    resp1 = await test_client.post(
        "/api/v1/hub/nodes/register", json=reg_payload_parent
    )
    assert resp1.status_code == 201
    parent_ref_code = resp1.json()["node_referral_code"]
    assert parent_ref_code.startswith("DSN-REF-")

    # 2. Register child node with parent referral code
    reg_payload_child = {
        "node_uuid": "child-node-uuid",
        "name": "ChildNode",
        "node_secret": "secret-child",
        "referrer_code": parent_ref_code,
    }
    resp2 = await test_client.post("/api/v1/hub/nodes/register", json=reg_payload_child)
    assert resp2.status_code == 201

    # Verify child is linked to parent in DB
    result = await db_session.execute(
        select(models.HubNode).where(models.HubNode.node_uuid == "child-node-uuid")
    )
    child_in_db = result.scalars().first()
    assert child_in_db is not None
    assert child_in_db.referrer_node_uuid == "parent-node-uuid"


async def test_mining_epoch_distribution(db_session: AsyncSession):
    # Clear epoch state
    await db_session.execute(models.MiningEpoch.__table__.delete())
    await db_session.execute(models.MiningLedger.__table__.delete())
    await db_session.execute(models.HubTelemetryReport.__table__.delete())
    await db_session.execute(models.HubNode.__table__.delete())
    await db_session.execute(models.MiningConfig.__table__.delete())
    await db_session.commit()

    # Setup Nodes (parent and child)
    parent = models.HubNode(node_uuid="parent-node", name="Parent", secret_hash="hash")
    child = models.HubNode(
        node_uuid="child-node",
        name="Child",
        secret_hash="hash",
        referrer_node_uuid="parent-node",
    )
    db_session.add(parent)
    db_session.add(child)

    # Setup Mining Config
    config = models.MiningConfig(
        is_mining_enabled=True,
        daily_emission_base=100.0,
        eligible_exchanges=["weex"],
        launch_date=datetime.date.today() - datetime.timedelta(days=2),
        referral_mining_boost=0.10,
    )
    db_session.add(config)
    await db_session.commit()

    # Create eligible trades for yesterday
    yesterday = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=1
    )

    report1 = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=10.0,
        exit_price=11.0,
        trade_mode="LIVE",
        node_uuid="child-node",
        estimated_rebate_usdt=10.0,  # Generates $10 rebate
        is_mining_eligible=True,
        verification_status="VERIFIED",
        created_at=yesterday,
    )
    db_session.add(report1)
    await db_session.commit()

    # Run the epoch processor task logic
    from contextlib import asynccontextmanager
    from unittest.mock import patch

    @asynccontextmanager
    async def mock_isolated_session():
        yield db_session

    with patch("api.database.get_isolated_worker_session", mock_isolated_session):
        await _async_process_mining_epoch()

    # Check child reward
    ledger_child = (
        (
            await db_session.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == "child-node"
                )
            )
        )
        .scalars()
        .first()
    )

    # Check parent referrer bonus
    ledger_parent = (
        (
            await db_session.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == "parent-node"
                )
            )
        )
        .scalars()
        .first()
    )

    assert ledger_child is not None
    assert (
        pytest.approx(ledger_child.base_reward, rel=1e-3) == 90.909
    )  # ~90.91% of daily emission pool
    assert ledger_child.welcome_bonus == 1000.0  # Child crosses $5 rebate threshold
    assert pytest.approx(ledger_child.total_reward, rel=1e-3) == 1090.909

    assert ledger_parent is not None
    assert (
        pytest.approx(ledger_parent.referral_bonus, rel=1e-3) == 9.091
    )  # ~9.09% referral daily boost
    assert ledger_parent.welcome_bonus == 1000.0  # Parent gets matching welcome bonus
    assert pytest.approx(ledger_parent.total_reward, rel=1e-3) == 1009.091


async def test_get_mining_status(test_client: AsyncClient, db_session: AsyncSession):
    # Setup Node
    node_uuid = "node-status-test"
    node_secret = "secret-status"
    secret_hash = hashlib.sha256(node_secret.encode()).hexdigest()

    node = models.HubNode(
        node_uuid=node_uuid,
        name="StatusNode",
        secret_hash=secret_hash,
        total_mined=250.0,
    )
    db_session.add(node)

    # Setup Config
    config = models.MiningConfig(
        is_mining_enabled=True,
        eligible_exchanges=["weex"],
        daily_emission_base=500.0,
        launch_date=datetime.date.today(),
    )
    db_session.add(config)

    # 100% user share so a single participating node keeps the full emission
    # (default share would deduct 25% node commission).
    db_session.add(
        models.NodeMiningConfig(
            id=1, is_global_mining_enabled=True, user_reward_share_percent=100.0
        )
    )

    # Setup Ledger Entry
    ledger = models.MiningLedger(
        node_uuid=node_uuid,
        epoch_date=datetime.date.today() - datetime.timedelta(days=1),
        base_reward=250.0,
        referral_bonus=0.0,
        total_reward=250.0,
        total_rebate_usdt=5.0,
        verified_trades_count=1,
    )
    db_session.add(ledger)

    # yourEpochReward is a LIVE estimate computed from today's telemetry reports.
    # Seed one eligible report for today so the estimate is non-zero.
    report = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=62500.0,
        exit_price=63750.0,
        trade_mode="LIVE",
        node_uuid=node_uuid,
        trade_volume_usdt=10000.0,
        estimated_rebate_usdt=10.0,
        is_mining_eligible=True,
        created_at=datetime.datetime.combine(
            datetime.date.today(),
            datetime.time(12, 0),
            tzinfo=datetime.timezone.utc,
        ),
    )
    db_session.add(report)
    await db_session.commit()

    headers = {
        "X-Node-UUID": node_uuid,
        "X-Node-Secret": node_secret,
    }

    response = await test_client.get("/api/v1/hub/mining/status", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["isMiningEnabled"] is True
    assert "weex" in data["eligibleExchanges"]
    assert data["yourTotalMined"] == 250.0
    # Single participating node => it receives the full daily emission (500.0).
    assert data["yourEpochReward"] == 500.0


async def test_estimate_reward_net_of_commission_with_referral(
    test_client: AsyncClient, db_session: AsyncSession
):
    """
    The live estimate must match the daily MiningLedger calc: the node's base
    reward is net of the (1 - share) operator commission and the referrer node
    sees its referral bonus. Welcome bonus (one-time) is excluded.
    """
    await db_session.execute(models.HubNode.__table__.delete())
    await db_session.execute(models.MiningConfig.__table__.delete())
    await db_session.execute(models.NodeMiningConfig.__table__.delete())
    await db_session.execute(models.HubTelemetryReport.__table__.delete())
    await db_session.commit()

    # Operator root exists => commission is deducted from the miner node.
    admin = models.User(
        username="est-admin",
        email="est-admin@example.com",
        hashed_password="hash",
        is_active=True,
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    db_session.add(
        models.HubNode(
            node_uuid="est-root",
            name="Root",
            secret_hash="h",
            is_operator=True,
        )
    )

    parent = models.HubNode(
        node_uuid="est-parent",
        name="Parent",
        secret_hash=hashlib.sha256("secret-parent".encode()).hexdigest(),
    )
    child = models.HubNode(
        node_uuid="est-child",
        name="Child",
        secret_hash=hashlib.sha256("secret-child".encode()).hexdigest(),
        referrer_node_uuid="est-parent",
    )
    db_session.add_all([parent, child])
    db_session.add(
        models.NodeMiningConfig(
            id=1, is_global_mining_enabled=True, user_reward_share_percent=75.0
        )
    )
    db_session.add(
        models.MiningConfig(
            is_mining_enabled=True,
            eligible_exchanges=["weex"],
            daily_emission_base=100.0,
            launch_date=datetime.date.today(),
            referral_mining_boost=0.10,
        )
    )
    db_session.add(
        models.HubTelemetryReport(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=10.0,
            exit_price=11.0,
            trade_mode="LIVE",
            node_uuid="est-child",
            estimated_rebate_usdt=10.0,
            is_mining_eligible=True,
            created_at=datetime.datetime.combine(
                datetime.date.today(),
                datetime.time(12, 0),
                tzinfo=datetime.timezone.utc,
            ),
        )
    )
    await db_session.commit()

    # Child: gross base = 100/(10+1)*10 = 90.909, commission 25% => 68.18, no referral.
    resp = await test_client.get(
        "/api/v1/hub/mining/status",
        headers={"X-Node-UUID": "est-child", "X-Node-Secret": "secret-child"},
    )
    assert resp.status_code == 200
    assert resp.json()["yourEpochReward"] == pytest.approx(68.1818, rel=1e-3)

    # Parent: referral bonus only (no own trades): 1 * 100/11 = 9.09.
    resp = await test_client.get(
        "/api/v1/hub/mining/status",
        headers={"X-Node-UUID": "est-parent", "X-Node-Secret": "secret-parent"},
    )
    assert resp.status_code == 200
    assert resp.json()["yourEpochReward"] == pytest.approx(9.0909, rel=1e-3)


async def test_estimate_reward_wallet_referrer_resolution(
    test_client: AsyncClient, db_session: AsyncSession
):
    """
    A wallet-node referrer must receive the referral bonus in the live estimate.
    The referral is a wallet node whose user is linked via referred_by_user_id;
    the referrer's real HubNode is found through its referral_code.
    """
    await db_session.execute(models.HubNode.__table__.delete())
    await db_session.execute(models.MiningConfig.__table__.delete())
    await db_session.execute(models.NodeMiningConfig.__table__.delete())
    await db_session.execute(models.HubTelemetryReport.__table__.delete())
    await db_session.commit()

    admin = models.User(
        username="est2-admin",
        email="est2-admin@example.com",
        hashed_password="hash",
        is_active=True,
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    db_session.add(
        models.HubNode(
            node_uuid="est2-root",
            name="Root",
            secret_hash="h",
            is_operator=True,
        )
    )

    referrer = models.User(
        username="est2-referrer",
        email="est2-referrer@example.com",
        hashed_password="hash",
        is_active=True,
        role="user",
        referral_code="EST-REF-A",
    )
    db_session.add(referrer)
    await db_session.commit()
    await db_session.refresh(referrer)

    wallet_node = models.HubNode(
        node_uuid="est2-wallet-a",
        name="WalletA",
        secret_hash=hashlib.sha256("secret-a".encode()).hexdigest(),
        node_referral_code="EST-REF-A",
    )
    db_session.add(wallet_node)

    referral = models.User(
        username="est2-referral",
        email="est2-referral@example.com",
        hashed_password="hash",
        is_active=True,
        role="user",
        referred_by_user_id=referrer.id,
    )
    db_session.add(referral)
    await db_session.commit()
    await db_session.refresh(referral)

    db_session.add(
        models.AppConfig(
            user_id=referral.id,
            risk_management={},
            notifications={},
            data_sources={},
            exchange_settings={"weex": {"mining_node_uuid": "est2-referral-wallet"}},
        )
    )

    db_session.add(
        models.NodeMiningConfig(
            id=1, is_global_mining_enabled=True, user_reward_share_percent=75.0
        )
    )
    db_session.add(
        models.MiningConfig(
            is_mining_enabled=True,
            eligible_exchanges=["weex"],
            daily_emission_base=100.0,
            launch_date=datetime.date.today(),
            referral_mining_boost=0.10,
        )
    )
    db_session.add(
        models.HubTelemetryReport(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=10.0,
            exit_price=11.0,
            trade_mode="LIVE",
            node_uuid="est2-referral-wallet",
            estimated_rebate_usdt=10.0,
            is_mining_eligible=True,
            created_at=datetime.datetime.combine(
                datetime.date.today(),
                datetime.time(12, 0),
                tzinfo=datetime.timezone.utc,
            ),
        )
    )
    await db_session.commit()

    resp = await test_client.get(
        "/api/v1/hub/mining/status",
        headers={"X-Node-UUID": "est2-wallet-a", "X-Node-Secret": "secret-a"},
    )
    assert resp.status_code == 200
    # Referral bonus only: 1 * 100/11 = 9.09.
    assert resp.json()["yourEpochReward"] == pytest.approx(9.0909, rel=1e-3)


async def test_estimate_admin_wallet_node_referral_and_commission(
    test_client: AsyncClient, db_session: AsyncSession
):
    """
    Reproduces the live hub scenario: the admin (operator) bound a WALLET node
    and invited a second account which ALSO uses a wallet node and trades. The
    invitee's live estimate must be net of the 25% node commission (default 75%
    share), and the admin's estimate must show the referral bonus (resolved via
    the admin's wallet node in AppConfig).
    """
    await db_session.execute(models.HubNode.__table__.delete())
    await db_session.execute(models.MiningConfig.__table__.delete())
    await db_session.execute(models.NodeMiningConfig.__table__.delete())
    await db_session.execute(models.HubTelemetryReport.__table__.delete())
    await db_session.execute(models.AppConfig.__table__.delete())
    await db_session.commit()

    admin = models.User(
        username="op-admin",
        email="op-admin@example.com",
        hashed_password="hash",
        is_active=True,
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)

    admin_wallet = models.HubNode(
        node_uuid="op-admin-wallet",
        name="AdminWallet",
        secret_hash=hashlib.sha256("secret-op-admin".encode()).hexdigest(),
    )
    db_session.add(admin_wallet)
    db_session.add(
        models.AppConfig(
            user_id=admin.id,
            risk_management={},
            data_sources={},
            notifications={},
            exchange_settings={
                "weex": {"mining_node_uuid": "op-admin-wallet"},
            },
        )
    )

    invitee = models.User(
        username="invitee",
        email="invitee@example.com",
        hashed_password="hash",
        is_active=True,
        role="user",
        referred_by_user_id=admin.id,
    )
    db_session.add(invitee)
    await db_session.commit()
    await db_session.refresh(invitee)

    invitee_wallet = models.HubNode(
        node_uuid="op-invitee-wallet",
        name="InviteeWallet",
        secret_hash=hashlib.sha256("secret-invitee".encode()).hexdigest(),
    )
    db_session.add(invitee_wallet)
    db_session.add(
        models.AppConfig(
            user_id=invitee.id,
            risk_management={},
            data_sources={},
            notifications={},
            exchange_settings={
                "weex": {"mining_node_uuid": "op-invitee-wallet"},
            },
        )
    )
    db_session.add(
        models.NodeMiningConfig(
            id=1, is_global_mining_enabled=True, user_reward_share_percent=75.0
        )
    )
    db_session.add(
        models.MiningConfig(
            is_mining_enabled=True,
            eligible_exchanges=["weex"],
            daily_emission_base=100.0,
            launch_date=datetime.date.today(),
            referral_mining_boost=0.10,
        )
    )
    db_session.add(
        models.HubTelemetryReport(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=10.0,
            exit_price=11.0,
            trade_mode="LIVE",
            node_uuid="op-invitee-wallet",
            estimated_rebate_usdt=10.0,
            is_mining_eligible=True,
            created_at=datetime.datetime.combine(
                datetime.date.today(),
                datetime.time(12, 0),
                tzinfo=datetime.timezone.utc,
            ),
        )
    )
    await db_session.commit()

    # Invitee: gross 90.909 (diluted by referral points) minus 25% commission => 68.18.
    resp = await test_client.get(
        "/api/v1/hub/mining/status",
        headers={
            "X-Node-UUID": "op-invitee-wallet",
            "X-Node-Secret": "secret-invitee",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["yourEpochReward"] == pytest.approx(68.1818, rel=1e-3)

    # Admin: referral bonus only (1 * 100/11 = 9.09). Commission is NOT shown here.
    resp = await test_client.get(
        "/api/v1/hub/mining/status",
        headers={
            "X-Node-UUID": "op-admin-wallet",
            "X-Node-Secret": "secret-op-admin",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["yourEpochReward"] == pytest.approx(9.0909, rel=1e-3)


async def test_update_mining_config_admin(
    test_client: AsyncClient, db_session: AsyncSession
):
    # Setup global key override
    import api.hub_router as hr

    hr.HUB_ADMIN_API_KEY = "test-admin-secret-key-123"

    # Setup initial config in DB
    await db_session.execute(models.MiningConfig.__table__.delete())
    config = models.MiningConfig(
        is_mining_enabled=True,
        eligible_exchanges=["weex"],
        daily_emission_base=1000.0,
    )
    db_session.add(config)
    await db_session.commit()

    update_payload = {
        "isMiningEnabled": False,
        "eligibleExchanges": ["weex", "binance"],
        "minTradeDurationSec": 60,
    }

    headers = {
        "Authorization": "Bearer test-admin-secret-key-123",
        "Content-Type": "application/json",
    }

    response = await test_client.post(
        "/api/v1/hub/mining/config",
        json=update_payload,
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify updated row in DB
    db_session.expire_all()
    result = await db_session.execute(select(models.MiningConfig).limit(1))
    updated_cfg = result.scalars().first()
    assert updated_cfg is not None
    assert updated_cfg.is_mining_enabled is False
    assert "binance" in updated_cfg.eligible_exchanges
    assert updated_cfg.min_trade_duration_sec == 60


async def test_referrer_binding_is_one_time(
    test_client: AsyncClient, db_session: AsyncSession
):
    """P.4: A node can be linked to a referrer exactly once."""
    await db_session.execute(models.HubNode.__table__.delete())
    await db_session.commit()

    # 1. Register two potential referrers
    ref_a = {"node_uuid": "ref-a-node", "name": "RefA", "node_secret": "s-a"}
    ref_b = {"node_uuid": "ref-b-node", "name": "RefB", "node_secret": "s-b"}
    ra = await test_client.post("/api/v1/hub/nodes/register", json=ref_a)
    rb = await test_client.post("/api/v1/hub/nodes/register", json=ref_b)
    assert ra.status_code == 201
    assert rb.status_code == 201
    code_a = ra.json()["node_referral_code"]

    # 2. Register a child bound to A
    child = {
        "node_uuid": "child-one-time",
        "name": "Child",
        "node_secret": "s-child",
        "referrer_code": code_a,
    }
    resp = await test_client.post("/api/v1/hub/nodes/register", json=child)
    assert resp.status_code == 201

    result = await db_session.execute(
        select(models.HubNode).where(models.HubNode.node_uuid == "child-one-time")
    )
    child_db = result.scalars().first()
    assert child_db.referrer_node_uuid == "ref-a-node"

    # 3. Re-register the same node attempting to re-link to B -> rejected
    code_b = rb.json()["node_referral_code"]
    rebind = {
        "node_uuid": "child-one-time",
        "name": "Child",
        "node_secret": "s-child",
        "referrer_code": code_b,
    }
    resp = await test_client.post("/api/v1/hub/nodes/register", json=rebind)
    assert resp.status_code == 400

    # Referrer unchanged
    db_session.expire_all()
    result = await db_session.execute(
        select(models.HubNode).where(models.HubNode.node_uuid == "child-one-time")
    )
    child_db = result.scalars().first()
    assert child_db.referrer_node_uuid == "ref-a-node"


async def test_referrer_self_and_cycle_rejected(
    test_client: AsyncClient, db_session: AsyncSession
):
    """P.4: Self-referral and referral cycles are rejected."""
    await db_session.execute(models.HubNode.__table__.delete())
    await db_session.commit()

    # Self-referral: node registers using its own code is impossible on first
    # register (code is generated server-side), so simulate via re-registration.
    node = {"node_uuid": "self-node", "name": "Self", "node_secret": "s-self"}
    r1 = await test_client.post("/api/v1/hub/nodes/register", json=node)
    assert r1.status_code == 201
    own_code = r1.json()["node_referral_code"]

    re_self = {
        "node_uuid": "self-node",
        "name": "Self",
        "node_secret": "s-self",
        "referrer_code": own_code,
    }
    resp = await test_client.post("/api/v1/hub/nodes/register", json=re_self)
    assert resp.status_code == 400

    # Cycle: A -> B -> A
    a = {"node_uuid": "cycle-a", "name": "A", "node_secret": "s-a"}
    b = {"node_uuid": "cycle-b", "name": "B", "node_secret": "s-b"}
    ra = await test_client.post("/api/v1/hub/nodes/register", json=a)
    rb = await test_client.post("/api/v1/hub/nodes/register", json=b)
    code_a = ra.json()["node_referral_code"]
    code_b = rb.json()["node_referral_code"]

    # B refers A
    resp = await test_client.post(
        "/api/v1/hub/nodes/register",
        json={**b, "referrer_code": code_a},
    )
    assert resp.status_code == 201

    # A re-registers referring B -> would create cycle A -> B -> A
    resp = await test_client.post(
        "/api/v1/hub/nodes/register",
        json={**a, "referrer_code": code_b},
    )
    assert resp.status_code == 400


async def test_attribution_spoofing_rejected(
    test_client: AsyncClient, db_session: AsyncSession
):
    """P.5: A node cannot attribute telemetry to another user's node."""
    # 1. Create two unrelated registered nodes (different owners)
    node1 = models.HubNode(
        node_uuid="attr-node-1",
        name="Node1",
        secret_hash=hashlib.sha256("secret-1".encode()).hexdigest(),
        node_referral_code="REF-OWNER-1",
    )
    node2 = models.HubNode(
        node_uuid="attr-node-2",
        name="Node2",
        secret_hash=hashlib.sha256("secret-2".encode()).hexdigest(),
        node_referral_code="REF-OWNER-2",
    )
    db_session.add_all([node1, node2])
    await db_session.commit()

    # 2. Node1 submits telemetry attributed to Node2 -> forbidden
    payload = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entryPrice": 62500.0,
        "exitPrice": 63750.0,
        "tradeMode": "LIVE",
        "strategyBlocks": [],
        "marketContext": {},
        "exchangeId": "weex",
        "marketType": "futures",
        "brokerTradeId": "spoof-trade-1",
        "tradeVolumeUsdt": 1000.0,
        "attributionNodeUuid": "attr-node-2",
    }
    body_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    sig = hmac.new("secret-1".encode(), body_bytes, hashlib.sha256).hexdigest()
    headers = {
        "X-Node-UUID": "attr-node-1",
        "X-Node-Secret": "secret-1",
        "X-Node-Signature": sig,
        "Content-Type": "application/json",
    }
    resp = await test_client.post(
        "/api/v1/hub/telemetry/report", content=body_bytes, headers=headers
    )
    assert resp.status_code == 403

    # 3. Attributed to own node -> allowed
    payload2 = dict(payload)
    payload2["brokerTradeId"] = "spoof-trade-2"
    payload2["attributionNodeUuid"] = "attr-node-1"
    body_bytes2 = json.dumps(payload2, sort_keys=True).encode("utf-8")
    sig2 = hmac.new("secret-1".encode(), body_bytes2, hashlib.sha256).hexdigest()
    headers2 = {
        "X-Node-UUID": "attr-node-1",
        "X-Node-Secret": "secret-1",
        "X-Node-Signature": sig2,
        "Content-Type": "application/json",
    }
    resp = await test_client.post(
        "/api/v1/hub/telemetry/report", content=body_bytes2, headers=headers2
    )
    assert resp.status_code == 201

    result = await db_session.execute(
        select(models.HubTelemetryReport).where(
            models.HubTelemetryReport.broker_trade_id == "spoof-trade-2"
        )
    )
    stored = result.scalars().first()
    assert stored is not None
    assert stored.node_uuid == "attr-node-1"


async def test_attribution_to_own_wallet_node_allowed(
    test_client: AsyncClient, db_session: AsyncSession
):
    """P.5: A node may attribute to another node owned by the same wallet."""
    node1 = models.HubNode(
        node_uuid="w-node-1",
        name="WalletNode1",
        secret_hash=hashlib.sha256("secret-w1".encode()).hexdigest(),
        weex_uid="WE-OWNER-42",
    )
    node2 = models.HubNode(
        node_uuid="w-node-2",
        name="WalletNode2",
        secret_hash=hashlib.sha256("secret-w2".encode()).hexdigest(),
        weex_uid="WE-OWNER-42",
    )
    db_session.add_all([node1, node2])
    await db_session.commit()

    payload = {
        "symbol": "ETHUSDT",
        "direction": "SHORT",
        "entryPrice": 2000.0,
        "exitPrice": 1980.0,
        "tradeMode": "LIVE",
        "strategyBlocks": [],
        "marketContext": {},
        "exchangeId": "weex",
        "marketType": "futures",
        "brokerTradeId": "wallet-attr-1",
        "tradeVolumeUsdt": 500.0,
        "attributionNodeUuid": "w-node-2",
    }
    body_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    sig = hmac.new("secret-w1".encode(), body_bytes, hashlib.sha256).hexdigest()
    headers = {
        "X-Node-UUID": "w-node-1",
        "X-Node-Secret": "secret-w1",
        "X-Node-Signature": sig,
        "Content-Type": "application/json",
    }
    resp = await test_client.post(
        "/api/v1/hub/telemetry/report", content=body_bytes, headers=headers
    )
    assert resp.status_code == 201


async def test_welcome_bonus_pool_cap(db_session: AsyncSession, monkeypatch):
    """P.7: Welcome bonuses stop once the welcome pool is exhausted."""
    from contextlib import asynccontextmanager
    from unittest.mock import patch

    await db_session.execute(models.MiningEpoch.__table__.delete())
    await db_session.execute(models.MiningLedger.__table__.delete())
    await db_session.execute(models.HubTelemetryReport.__table__.delete())
    await db_session.execute(models.HubNode.__table__.delete())
    await db_session.execute(models.MiningConfig.__table__.delete())
    await db_session.commit()

    # Force a tiny pool cap (e.g. 1500) so halving stage 1 (1000) fits once
    monkeypatch.setenv("WELCOME_BONUS_MAX_POOL", "1500.0")
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "5.0")

    node_a = models.HubNode(
        node_uuid="pool-node-a",
        name="PoolA",
        secret_hash="hash",
        referrer_node_uuid="pool-parent",
        weex_uid="UID-A",
    )
    node_b = models.HubNode(
        node_uuid="pool-node-b",
        name="PoolB",
        secret_hash="hash",
        referrer_node_uuid="pool-parent",
        weex_uid="UID-B",
    )
    parent = models.HubNode(
        node_uuid="pool-parent",
        name="PoolParent",
        secret_hash="hash",
        weex_uid="UID-PARENT",
    )
    db_session.add_all([node_a, node_b, parent])

    config = models.MiningConfig(
        is_mining_enabled=True,
        daily_emission_base=100.0,
        eligible_exchanges=["weex"],
        launch_date=datetime.date.today() - datetime.timedelta(days=2),
    )
    db_session.add(config)
    await db_session.commit()

    yesterday = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=1
    )
    # Each node crosses the $5 rebate threshold for yesterday
    for node_id in ("pool-node-a", "pool-node-b"):
        db_session.add(
            models.HubTelemetryReport(
                symbol="BTCUSDT",
                direction="LONG",
                entry_price=10.0,
                exit_price=11.0,
                trade_mode="LIVE",
                node_uuid=node_id,
                estimated_rebate_usdt=10.0,
                is_mining_eligible=True,
                verification_status="VERIFIED",
                created_at=yesterday,
            )
        )
    await db_session.commit()

    @asynccontextmanager
    async def mock_isolated_session():
        yield db_session

    with patch("api.database.get_isolated_worker_session", mock_isolated_session):
        await _async_process_mining_epoch()

    db_session.expire_all()

    # Node A claimed the first 1000 bonus (pool 1000/1500).
    ledger_a = (
        (
            await db_session.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == "pool-node-a"
                )
            )
        )
        .scalars()
        .first()
    )
    assert ledger_a is not None
    assert ledger_a.welcome_bonus == 1000.0

    # The parent's matching bonus for A takes the remaining 500 (pool 1500/1500),
    # so node B's grant would exceed the cap and is skipped entirely.
    ledger_b = (
        (
            await db_session.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == "pool-node-b"
                )
            )
        )
        .scalars()
        .first()
    )
    assert ledger_b is not None
    assert ledger_b.welcome_bonus == 0.0

    # Parent receives a matching bonus for A (500) from the same pool.
    ledger_parent = (
        (
            await db_session.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == "pool-parent"
                )
            )
        )
        .scalars()
        .first()
    )
    assert ledger_parent is not None
    assert ledger_parent.welcome_bonus == 500.0


async def test_welcome_bonus_uid_limit(db_session: AsyncSession, monkeypatch):
    """P.7: A single Weex UID can only claim the welcome bonus for one node."""
    from contextlib import asynccontextmanager
    from unittest.mock import patch

    await db_session.execute(models.MiningEpoch.__table__.delete())
    await db_session.execute(models.MiningLedger.__table__.delete())
    await db_session.execute(models.HubTelemetryReport.__table__.delete())
    await db_session.execute(models.HubNode.__table__.delete())
    await db_session.execute(models.MiningConfig.__table__.delete())
    await db_session.commit()

    monkeypatch.setenv("MAX_NODES_PER_UID", "1")
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "5.0")

    node_a = models.HubNode(
        node_uuid="uid-node-a",
        name="UidNodeA",
        secret_hash="hash",
        weex_uid="SHARED-UID",
    )
    node_b = models.HubNode(
        node_uuid="uid-node-b",
        name="UidNodeB",
        secret_hash="hash",
        weex_uid="SHARED-UID",
    )
    db_session.add_all([node_a, node_b])

    config = models.MiningConfig(
        is_mining_enabled=True,
        daily_emission_base=100.0,
        eligible_exchanges=["weex"],
        launch_date=datetime.date.today() - datetime.timedelta(days=2),
    )
    db_session.add(config)
    await db_session.commit()

    yesterday = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=1
    )
    for node_id in ("uid-node-a", "uid-node-b"):
        db_session.add(
            models.HubTelemetryReport(
                symbol="BTCUSDT",
                direction="LONG",
                entry_price=10.0,
                exit_price=11.0,
                trade_mode="LIVE",
                node_uuid=node_id,
                estimated_rebate_usdt=10.0,
                is_mining_eligible=True,
                verification_status="VERIFIED",
                created_at=yesterday,
            )
        )
    await db_session.commit()

    @asynccontextmanager
    async def mock_isolated_session():
        yield db_session

    with patch("api.database.get_isolated_worker_session", mock_isolated_session):
        await _async_process_mining_epoch()

    db_session.expire_all()

    ledger_a = (
        (
            await db_session.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == "uid-node-a"
                )
            )
        )
        .scalars()
        .first()
    )
    ledger_b = (
        (
            await db_session.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == "uid-node-b"
                )
            )
        )
        .scalars()
        .first()
    )

    # Exactly one of the two nodes claimed the bonus for the shared UID.
    assert ledger_a is not None and ledger_a.welcome_bonus == 1000.0
    assert ledger_b is not None and ledger_b.welcome_bonus == 0.0


async def test_operator_fee_safe_share_fallback(db_session: AsyncSession, monkeypatch):
    """
    P.8: A legacy NodeMiningConfig with user_reward_share_percent = 0.0 must not
    silently hand 100% of node rewards to the operator. The safe 75% user share
    fallback applies, so the miner node keeps 75% and the operator gets 25%.
    """
    from contextlib import asynccontextmanager
    from unittest.mock import patch

    await db_session.execute(models.MiningEpoch.__table__.delete())
    await db_session.execute(models.MiningLedger.__table__.delete())
    await db_session.execute(models.HubTelemetryReport.__table__.delete())
    await db_session.execute(models.HubNode.__table__.delete())
    await db_session.execute(models.NodeMiningConfig.__table__.delete())
    await db_session.execute(models.MiningConfig.__table__.delete())
    await db_session.commit()

    # Disable welcome bonuses so operator fee math is clean (base reward only).
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")

    operator_node = models.HubNode(
        node_uuid="op-fallback-node",
        name="OperatorNode",
        secret_hash="hash",
        is_operator=True,
    )
    miner_node = models.HubNode(
        node_uuid="miner-fallback-node",
        name="MinerNode",
        secret_hash="hash",
    )
    db_session.add_all([operator_node, miner_node])

    config = models.MiningConfig(
        is_mining_enabled=True,
        daily_emission_base=100.0,
        eligible_exchanges=["weex"],
        launch_date=datetime.date.today() - datetime.timedelta(days=2),
    )
    db_session.add(config)

    # Legacy dangerous value: 0.0 user share.
    node_cfg = models.NodeMiningConfig(user_reward_share_percent=0.0)
    db_session.add(node_cfg)
    await db_session.commit()

    yesterday = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=1
    )
    db_session.add(
        models.HubTelemetryReport(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=10.0,
            exit_price=11.0,
            trade_mode="LIVE",
            node_uuid="miner-fallback-node",
            estimated_rebate_usdt=10.0,
            is_mining_eligible=True,
            verification_status="VERIFIED",
            created_at=yesterday,
        )
    )
    await db_session.commit()

    @asynccontextmanager
    async def mock_isolated_session():
        yield db_session

    with patch("api.database.get_isolated_worker_session", mock_isolated_session):
        await _async_process_mining_epoch()

    db_session.expire_all()

    miner_ledger = (
        (
            await db_session.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == "miner-fallback-node"
                )
            )
        )
        .scalars()
        .first()
    )
    operator_ledger = (
        (
            await db_session.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == "op-fallback-node"
                )
            )
        )
        .scalars()
        .first()
    )

    # daily_emission = 100, single node: base_reward = 100.
    # With fallback share 0.75 the operator takes only 25% (25), node keeps 75%.
    assert miner_ledger is not None
    assert miner_ledger.base_reward == pytest.approx(75.0)
    assert operator_ledger is not None
    assert operator_ledger.base_reward == pytest.approx(25.0)


async def test_operator_fee_goes_to_flagged_node(db_session: AsyncSession, monkeypatch):
    """
    P.9: The operator fee must go to the explicitly flagged is_operator node,
    not to whichever node happens to be the first row of the hub_nodes table.
    """
    from contextlib import asynccontextmanager
    from unittest.mock import patch

    await db_session.execute(models.MiningEpoch.__table__.delete())
    await db_session.execute(models.MiningLedger.__table__.delete())
    await db_session.execute(models.HubTelemetryReport.__table__.delete())
    await db_session.execute(models.HubNode.__table__.delete())
    await db_session.execute(models.NodeMiningConfig.__table__.delete())
    await db_session.execute(models.MiningConfig.__table__.delete())
    await db_session.commit()

    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")

    # Registered FIRST (would win a LIMIT 1 query) but is NOT the operator.
    first_node = models.HubNode(
        node_uuid="first-registered-node",
        name="FirstNode",
        secret_hash="hash",
        is_operator=False,
    )
    # Registered SECOND, but explicitly flagged as the operator.
    operator_node = models.HubNode(
        node_uuid="op-flagged-node",
        name="OperatorNode",
        secret_hash="hash",
        is_operator=True,
    )
    miner_node = models.HubNode(
        node_uuid="miner-node-9997",
        name="MinerNode",
        secret_hash="hash",
    )
    db_session.add_all([first_node, operator_node, miner_node])

    config = models.MiningConfig(
        is_mining_enabled=True,
        daily_emission_base=100.0,
        eligible_exchanges=["weex"],
        launch_date=datetime.date.today() - datetime.timedelta(days=2),
    )
    db_session.add(config)
    await db_session.commit()

    yesterday = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=1
    )
    db_session.add(
        models.HubTelemetryReport(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=10.0,
            exit_price=11.0,
            trade_mode="LIVE",
            node_uuid="miner-node-9997",
            estimated_rebate_usdt=10.0,
            is_mining_eligible=True,
            verification_status="VERIFIED",
            created_at=yesterday,
        )
    )
    await db_session.commit()

    @asynccontextmanager
    async def mock_isolated_session():
        yield db_session

    with patch("api.database.get_isolated_worker_session", mock_isolated_session):
        await _async_process_mining_epoch()

    db_session.expire_all()

    first_ledger = (
        (
            await db_session.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == "first-registered-node"
                )
            )
        )
        .scalars()
        .first()
    )
    operator_ledger = (
        (
            await db_session.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == "op-flagged-node"
                )
            )
        )
        .scalars()
        .first()
    )

    # The first row of the table gets NOTHING; the flagged operator gets 25%.
    assert first_ledger is None
    assert operator_ledger is not None
    assert operator_ledger.base_reward == pytest.approx(25.0)


async def test_telemetry_source_server_stored_and_validated(
    test_client: AsyncClient, db_session: AsyncSession
):
    """sourceNodeUuid is stored, and only flagged mining servers may be used."""
    await db_session.execute(models.HubTelemetryReport.__table__.delete())
    await db_session.execute(models.HubNode.__table__.delete())
    await db_session.commit()

    db_session.add(
        models.HubNode(
            node_uuid="src-miner",
            name="Miner",
            secret_hash=hashlib.sha256("secret-miner".encode()).hexdigest(),
            is_mining_server=False,
        )
    )
    db_session.add(
        models.HubNode(
            node_uuid="src-server",
            name="ServerNode",
            secret_hash=hashlib.sha256("secret-server".encode()).hexdigest(),
            is_mining_server=True,
        )
    )
    db_session.add(
        models.HubNode(
            node_uuid="src-plain",
            name="PlainNode",
            secret_hash=hashlib.sha256("secret-plain".encode()).hexdigest(),
            is_mining_server=False,
        )
    )
    await db_session.commit()

    def _make_payload(trade_id: str, source: str):
        return {
            "symbol": "BTCUSDT",
            "direction": "LONG",
            "entryPrice": 10.0,
            "exitPrice": 11.0,
            "tradeMode": "LIVE",
            "strategyBlocks": [],
            "marketContext": {},
            "exchangeId": "weex",
            "marketType": "futures",
            "brokerTradeId": trade_id,
            "tradeVolumeUsdt": 1000.0,
            "attributionNodeUuid": "src-miner",
            "sourceNodeUuid": source,
        }

    # 1. Valid mining-server source -> accepted and stored.
    p1 = _make_payload("src-ok-1", "src-server")
    b1 = json.dumps(p1, sort_keys=True).encode("utf-8")
    h1 = {
        "X-Node-UUID": "src-miner",
        "X-Node-Secret": "secret-miner",
        "X-Node-Signature": hmac.new(
            "secret-miner".encode(), b1, hashlib.sha256
        ).hexdigest(),
        "Content-Type": "application/json",
    }
    resp1 = await test_client.post(
        "/api/v1/hub/telemetry/report", content=b1, headers=h1
    )
    assert resp1.status_code == 201

    stored = (
        (
            await db_session.execute(
                select(models.HubTelemetryReport).where(
                    models.HubTelemetryReport.broker_trade_id == "src-ok-1"
                )
            )
        )
        .scalars()
        .first()
    )
    assert stored is not None
    assert stored.source_node_uuid == "src-server"

    # 2. Non-server node as source -> rejected.
    p2 = _make_payload("src-bad-1", "src-plain")
    b2 = json.dumps(p2, sort_keys=True).encode("utf-8")
    h2 = {
        "X-Node-UUID": "src-miner",
        "X-Node-Secret": "secret-miner",
        "X-Node-Signature": hmac.new(
            "secret-miner".encode(), b2, hashlib.sha256
        ).hexdigest(),
        "Content-Type": "application/json",
    }
    resp2 = await test_client.post(
        "/api/v1/hub/telemetry/report", content=b2, headers=h2
    )
    assert resp2.status_code == 403


async def test_hub_server_config_upsert_via_ping(
    test_client: AsyncClient, db_session: AsyncSession
):
    """A mining server's /nodes/ping registers/refreshes its HubServerConfig."""
    await db_session.execute(models.HubNode.__table__.delete())
    await db_session.execute(models.HubServerConfig.__table__.delete())
    await db_session.commit()

    reg = await test_client.post(
        "/api/v1/hub/nodes/register",
        json={
            "node_uuid": "ping-server-node",
            "name": "PingServer",
            "node_secret": "secret-ping",
            "is_mining_server": True,
        },
    )
    assert reg.status_code == 201

    headers = {
        "X-Node-UUID": "ping-server-node",
        "X-Node-Secret": "secret-ping",
    }
    ping1 = await test_client.post(
        "/api/v1/hub/nodes/ping",
        json={"latency_ms": 3.0, "version": "1.0.0", "user_reward_share_percent": 60.0},
        headers=headers,
    )
    assert ping1.status_code == 200

    cfg = (
        (
            await db_session.execute(
                select(models.HubServerConfig).where(
                    models.HubServerConfig.node_uuid == "ping-server-node"
                )
            )
        )
        .scalars()
        .first()
    )
    assert cfg is not None
    assert cfg.user_reward_share_percent == pytest.approx(60.0)

    # Refresh with a new value.
    ping2 = await test_client.post(
        "/api/v1/hub/nodes/ping",
        json={"latency_ms": 3.0, "version": "1.0.0", "user_reward_share_percent": 70.0},
        headers=headers,
    )
    assert ping2.status_code == 200
    db_session.expire_all()
    cfg = (
        (
            await db_session.execute(
                select(models.HubServerConfig).where(
                    models.HubServerConfig.node_uuid == "ping-server-node"
                )
            )
        )
        .scalars()
        .first()
    )
    assert cfg.user_reward_share_percent == pytest.approx(70.0)


async def _run_epoch(db_session):
    from contextlib import asynccontextmanager
    from unittest.mock import patch

    @asynccontextmanager
    async def mock_isolated_session():
        yield db_session

    with patch("api.database.get_isolated_worker_session", mock_isolated_session):
        await _async_process_mining_epoch()
    db_session.expire_all()


async def test_epoch_server_commission_wallet_node(
    db_session: AsyncSession, monkeypatch
):
    """A wallet node mined through a 60% server keeps 60%, server keeps 40%."""
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    await db_session.execute(models.MiningEpoch.__table__.delete())
    await db_session.execute(models.MiningLedger.__table__.delete())
    await db_session.execute(models.HubTelemetryReport.__table__.delete())
    await db_session.execute(models.HubNode.__table__.delete())
    await db_session.execute(models.MiningConfig.__table__.delete())
    await db_session.execute(models.HubServerConfig.__table__.delete())
    await db_session.commit()

    server_node = models.HubNode(
        node_uuid="srv-node",
        name="ServerNode",
        secret_hash="hash",
        is_mining_server=True,
    )
    wallet_node = models.HubNode(
        node_uuid="wlt-node", name="WalletNode", secret_hash="hash"
    )
    db_session.add_all([server_node, wallet_node])
    db_session.add(
        models.HubServerConfig(node_uuid="srv-node", user_reward_share_percent=60.0)
    )
    db_session.add(
        models.MiningConfig(
            is_mining_enabled=True,
            daily_emission_base=100.0,
            eligible_exchanges=["weex"],
            launch_date=datetime.date.today() - datetime.timedelta(days=2),
        )
    )
    await db_session.commit()

    yesterday = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=1
    )
    report = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=10.0,
        exit_price=11.0,
        trade_mode="LIVE",
        node_uuid="wlt-node",
        source_node_uuid="srv-node",
        estimated_rebate_usdt=10.0,
        is_mining_eligible=True,
        verification_status="VERIFIED",
        created_at=yesterday,
    )
    db_session.add(report)
    await db_session.commit()

    await _run_epoch(db_session)

    wallet_ledger = (
        (
            await db_session.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == "wlt-node"
                )
            )
        )
        .scalars()
        .first()
    )
    server_ledger = (
        (
            await db_session.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == "srv-node"
                )
            )
        )
        .scalars()
        .first()
    )

    # daily_emission = 100, single node: gross base = 100. Server share 60%.
    assert wallet_ledger is not None
    assert wallet_ledger.base_reward == pytest.approx(60.0)
    assert wallet_ledger.total_reward == pytest.approx(60.0)
    assert server_ledger is not None
    assert server_ledger.base_reward == pytest.approx(40.0)
    fresh_report = (
        (
            await db_session.execute(
                select(models.HubTelemetryReport).where(
                    models.HubTelemetryReport.node_uuid == "wlt-node"
                )
            )
        )
        .scalars()
        .first()
    )
    assert fresh_report is not None
    assert fresh_report.reward_tokens == pytest.approx(60.0)


async def test_epoch_mixed_sources_per_report(db_session: AsyncSession, monkeypatch):
    """A node split across a local server (60%) and the hub (75%) is cut per report."""
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    await db_session.execute(models.MiningEpoch.__table__.delete())
    await db_session.execute(models.MiningLedger.__table__.delete())
    await db_session.execute(models.HubTelemetryReport.__table__.delete())
    await db_session.execute(models.HubNode.__table__.delete())
    await db_session.execute(models.MiningConfig.__table__.delete())
    await db_session.execute(models.NodeMiningConfig.__table__.delete())
    await db_session.execute(models.HubServerConfig.__table__.delete())
    await db_session.commit()

    root_node = models.HubNode(
        node_uuid="hub-root-node", name="HubRoot", secret_hash="hash", is_operator=True
    )
    server_node = models.HubNode(
        node_uuid="mix-srv-node",
        name="MixServer",
        secret_hash="hash",
        is_mining_server=True,
    )
    wallet_node = models.HubNode(
        node_uuid="mix-wlt-node", name="MixWallet", secret_hash="hash"
    )
    db_session.add_all([root_node, server_node, wallet_node])
    db_session.add(
        models.HubServerConfig(node_uuid="mix-srv-node", user_reward_share_percent=60.0)
    )
    db_session.add(
        models.MiningConfig(
            is_mining_enabled=True,
            daily_emission_base=100.0,
            eligible_exchanges=["weex"],
            launch_date=datetime.date.today() - datetime.timedelta(days=2),
        )
    )
    db_session.add(models.NodeMiningConfig(user_reward_share_percent=75.0))
    await db_session.commit()

    yesterday = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=1
    )
    db_session.add(
        models.HubTelemetryReport(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=10.0,
            exit_price=11.0,
            trade_mode="LIVE",
            node_uuid="mix-wlt-node",
            source_node_uuid="mix-srv-node",
            estimated_rebate_usdt=10.0,
            is_mining_eligible=True,
            verification_status="VERIFIED",
            created_at=yesterday,
        )
    )
    db_session.add(
        models.HubTelemetryReport(
            symbol="ETHUSDT",
            direction="SHORT",
            entry_price=2000.0,
            exit_price=1980.0,
            trade_mode="LIVE",
            node_uuid="mix-wlt-node",
            source_node_uuid=None,
            estimated_rebate_usdt=10.0,
            is_mining_eligible=True,
            verification_status="VERIFIED",
            created_at=yesterday,
        )
    )
    await db_session.commit()

    await _run_epoch(db_session)

    wallet_ledger = (
        (
            await db_session.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == "mix-wlt-node"
                )
            )
        )
        .scalars()
        .first()
    )
    server_ledger = (
        (
            await db_session.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == "mix-srv-node"
                )
            )
        )
        .scalars()
        .first()
    )
    root_ledger = (
        (
            await db_session.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == "hub-root-node"
                )
            )
        )
        .scalars()
        .first()
    )
    reports = (
        (
            await db_session.execute(
                select(models.HubTelemetryReport).where(
                    models.HubTelemetryReport.node_uuid == "mix-wlt-node"
                )
            )
        )
        .scalars()
        .all()
    )
    by_trade = {r.symbol: r for r in reports}

    # Gross base = 100 split 50/50 across the two reports.
    # Report via 60% server: net 30, fee 20 -> server.
    # Report via NULL (hub): net 37.5, fee 12.5 -> hub root.
    assert wallet_ledger is not None
    assert wallet_ledger.base_reward == pytest.approx(67.5)
    assert server_ledger is not None
    assert server_ledger.base_reward == pytest.approx(20.0)
    assert root_ledger is not None
    assert root_ledger.base_reward == pytest.approx(12.5)
    assert by_trade["BTCUSDT"].reward_tokens == pytest.approx(30.0)
    assert by_trade["ETHUSDT"].reward_tokens == pytest.approx(37.5)


async def test_hub_node_public_domain_and_active_nodes_endpoint(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Verify registration/ping with public_domain and GET /hub/nodes response format."""
    reg_resp = await test_client.post(
        "/api/v1/hub/nodes/register",
        json={
            "node_uuid": "domain-test-node",
            "name": "DomainNode",
            "node_secret": "secret123",
            "version": "2.1.0",
            "is_mining_server": True,
            "user_reward_share_percent": 85.0,
            "public_domain": "node.testdomain.com",
        },
    )
    assert reg_resp.status_code == 201

    ping_resp = await test_client.post(
        "/api/v1/hub/nodes/ping",
        json={
            "latency_ms": 15.5,
            "version": "2.1.0",
            "user_reward_share_percent": 85.0,
            "public_domain": "node.testdomain.com",
        },
        headers={
            "X-Node-UUID": "domain-test-node",
            "X-Node-Secret": "secret123",
        },
    )
    assert ping_resp.status_code == 200

    nodes_resp = await test_client.get("/api/v1/hub/nodes")
    assert nodes_resp.status_code == 200
    data = nodes_resp.json()
    assert isinstance(data, list)

    target_node = next((n for n in data if n.get("name") == "DomainNode"), None)
    assert target_node is not None
    assert target_node["public_domain"] == "node.testdomain.com"
    assert target_node["user_reward_share_percent"] == 85.0
    assert target_node["is_mining_server"] is True
    assert target_node["latency_ms"] == pytest.approx(15.5)
