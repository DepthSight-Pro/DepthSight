import datetime as dt
from datetime import timezone, timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api import models, security


@pytest.fixture
async def admin_auth(db_session: AsyncSession):
    admin = models.User(
        username="mining_analytics_admin",
        email="admin_analytics@example.com",
        hashed_password="hash",
        is_active=True,
        role="admin",
        plan="pro",
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)

    token = security.create_access_token({"sub": admin.username})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def regular_user_auth(db_session: AsyncSession):
    user = models.User(
        username="mining_analytics_user",
        email="user_analytics@example.com",
        hashed_password="hash",
        is_active=True,
        role="user",
        plan="free",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = security.create_access_token({"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def sample_mining_data(db_session: AsyncSession):
    # Ensure mining config exists
    cfg = models.MiningConfig(
        id=1,
        is_mining_enabled=True,
        daily_emission_base=500000.0,
        rebate_rates={"weex_futures": 0.0004, "bybit_futures": 0.0003},
        exchange_multipliers={"bitget": 2.0, "bybit": 1.5},
    )
    db_session.add(cfg)

    # Add 2 nodes
    node1 = models.HubNode(
        node_uuid="node-uuid-1",
        name="DepthNode-Alpha",
        secret_hash="secret1",
        last_ping=dt.datetime.now(timezone.utc),
        total_mined=1000.0,
    )
    node2 = models.HubNode(
        node_uuid="node-uuid-2",
        name="DepthNode-Beta",
        secret_hash="secret2",
        last_ping=dt.datetime.now(timezone.utc) - timedelta(minutes=30),
        total_mined=500.0,
    )
    db_session.add_all([node1, node2])

    today = dt.datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)

    # Add an epoch with 'finalized' status as produced by tasks.py
    epoch = models.MiningEpoch(
        epoch_date=yesterday,
        daily_emission=500000.0,
        total_rebate_pool=250.0,
        total_distributed=125000.0,
        participating_nodes=2,
        status="finalized",
        processed_at=dt.datetime.now(timezone.utc),
    )
    db_session.add(epoch)

    # Add telemetry reports
    trade1 = models.HubTelemetryReport(
        id="trade-1",
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=60000.0,
        exit_price=60600.0,
        pnl_percent=1.0,
        trade_duration_sec=120,
        trade_mode="LIVE",
        node_uuid="node-uuid-1",
        exchange_id="weex_futures",
        broker_trade_id="WX-001",
        trade_volume_usdt=5000.0,
        estimated_rebate_usdt=2.0,
        is_mining_eligible=True,
        is_verified=True,
        verification_status="VERIFIED",
        verified_volume_usdt=5000.0,
        reward_tokens=150.0,
        epoch_date=yesterday,
        strategy_blocks=[
            {"type": "rsi_filter", "params": {"length": 14, "threshold": 30}},
            {"type": "take_profit", "params": {"target": 1.5}},
        ],
        market_context={
            "session": "london",
            "natr": 0.45,
            "adx": 28.2,
            "volume_ratio": 1.75,
        },
        created_at=dt.datetime.now(timezone.utc) - timedelta(hours=2),
    )
    trade2 = models.HubTelemetryReport(
        id="trade-2",
        symbol="ETHUSDT",
        direction="SHORT",
        entry_price=3000.0,
        exit_price=2970.0,
        pnl_percent=1.0,
        trade_duration_sec=90,
        trade_mode="LIVE",
        node_uuid="node-uuid-1",
        exchange_id="bybit_futures",
        broker_trade_id="BY-001",
        trade_volume_usdt=3000.0,
        estimated_rebate_usdt=0.9,
        is_mining_eligible=True,
        is_verified=False,
        verification_status="PENDING",
        created_at=dt.datetime.now(timezone.utc) - timedelta(hours=1),
    )
    trade3 = models.HubTelemetryReport(
        id="trade-3",
        symbol="SOLUSDT",
        direction="LONG",
        entry_price=150.0,
        exit_price=149.0,
        pnl_percent=-0.6,
        trade_duration_sec=15,
        trade_mode="LIVE",
        node_uuid="node-uuid-2",
        exchange_id="weex_futures",
        broker_trade_id="WX-002",
        trade_volume_usdt=1000.0,
        estimated_rebate_usdt=0.4,
        is_mining_eligible=False,
        verification_status="ERROR",
        verification_error="DURATION_TOO_SHORT",
        created_at=dt.datetime.now(timezone.utc) - timedelta(minutes=30),
    )
    trade4 = models.HubTelemetryReport(
        id="trade-4",
        symbol="DOGEUSDT",
        direction="LONG",
        entry_price=0.15,
        exit_price=0.16,
        pnl_percent=6.6,
        trade_duration_sec=120,
        trade_mode="LIVE",
        node_uuid="node-uuid-1",
        exchange_id="bitget_futures",
        broker_trade_id="BG-001",
        trade_volume_usdt=2000.0,
        estimated_rebate_usdt=1.0,
        is_mining_eligible=True,
        is_verified=True,
        verification_status="VERIFIED",
        verified_volume_usdt=2000.0,
        mining_multiplier=1.0,  # Initially stamped 1.0 in DB, should resolve to 2.0 via config
        created_at=dt.datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    db_session.add_all([trade1, trade2, trade3, trade4])
    await db_session.commit()


@pytest.mark.asyncio
async def test_mining_analytics_auth_required(
    test_client: AsyncClient, regular_user_auth: dict
):
    # No auth
    resp = await test_client.get("/api/v1/hub/mining/analytics")
    assert resp.status_code == 403

    # Non-admin auth
    resp2 = await test_client.get(
        "/api/v1/hub/mining/analytics", headers=regular_user_auth
    )
    assert resp2.status_code == 403


@pytest.mark.asyncio
async def test_mining_analytics_summary(
    test_client: AsyncClient,
    admin_auth: dict,
    sample_mining_data,
):
    resp = await test_client.get("/api/v1/hub/mining/analytics", headers=admin_auth)
    assert resp.status_code == 200
    data = resp.json()

    # Network KPIs
    assert "totalUsers" in data
    assert "totalNodes" in data
    assert data["totalNodes"] >= 2
    assert "activeExchanges" in data
    assert "weex_futures" in data["activeExchanges"]
    assert "bybit_futures" in data["activeExchanges"]
    assert data["isMiningEnabled"] is True

    # Trade Mining KPIs
    assert data["totalTrades"] == 4
    assert data["verifiedCount"] == 2
    assert data["pendingCount"] == 1
    assert data["errorCount"] == 1
    assert data["verificationRate"] == 50.0
    assert data["totalVerifiedVolumeUsdt"] == 7000.0

    # Epochs
    assert len(data["epochs"]) >= 1
    ep = data["epochs"][0]
    assert ep["dailyEmission"] == 500000.0
    assert ep["participatingNodes"] == 2
    assert ep["status"] == "closed"

    # Exchange breakdown
    ex_list = data["exchangeBreakdown"]
    assert len(ex_list) >= 2
    weex_stat = next(x for x in ex_list if x["exchangeId"] == "weex_futures")
    assert weex_stat["tradeCount"] == 2
    assert weex_stat["verifiedCount"] == 1
    assert weex_stat["errorCount"] == 1
    assert weex_stat["verifiedVolumeUsdt"] == 5000.0
    assert weex_stat["verifiedRebateUsdt"] == 2.0

    # Node breakdown
    node_list = data["nodeBreakdown"]
    assert len(node_list) >= 2
    node1 = next(n for n in node_list if n["nodeUuid"] == "node-uuid-1")
    assert node1["isOnline"] is True
    assert node1["name"] == "DepthNode-Alpha"
    assert node1["tradeCount"] == 3

    # Daily trends
    assert len(data["dailyTrends"]) >= 1

    # Epoch trends
    assert len(data["epochTrends"]) >= 1


@pytest.mark.asyncio
async def test_mining_analytics_trades_pagination_and_filters(
    test_client: AsyncClient,
    admin_auth: dict,
    sample_mining_data,
):
    # 1. Basic pagination
    resp = await test_client.get(
        "/api/v1/hub/mining/analytics/trades?page=1&limit=2",
        headers=admin_auth,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4
    assert data["page"] == 1
    assert data["limit"] == 2
    assert data["totalPages"] == 2
    assert len(data["items"]) == 2

    # Verify resolved node name
    assert data["items"][0]["nodeName"] in ["DepthNode-Alpha", "DepthNode-Beta"]

    # 2. Filter by status
    resp_verified = await test_client.get(
        "/api/v1/hub/mining/analytics/trades?status_filter=VERIFIED",
        headers=admin_auth,
    )
    assert resp_verified.status_code == 200
    verified_data = resp_verified.json()
    assert verified_data["total"] == 2
    assert verified_data["items"][0]["verificationStatus"] == "VERIFIED"
    t1 = next(item for item in verified_data["items"] if item["id"] == "trade-1")
    assert len(t1["strategyBlocks"]) == 2
    assert t1["strategyBlocks"][0]["type"] == "rsi_filter"
    assert t1["marketContext"]["session"] == "london"
    assert t1["marketContext"]["natr"] == 0.45
    assert t1["marketContext"]["adx"] == 28.2

    # 3. Filter by exchange
    resp_bybit = await test_client.get(
        "/api/v1/hub/mining/analytics/trades?exchange=bybit_futures",
        headers=admin_auth,
    )
    assert resp_bybit.status_code == 200
    bybit_data = resp_bybit.json()
    assert bybit_data["total"] == 1
    assert bybit_data["items"][0]["exchangeId"] == "bybit_futures"
    assert bybit_data["items"][0]["miningMultiplier"] == 1.5

    # 4. Search by symbol
    resp_search = await test_client.get(
        "/api/v1/hub/mining/analytics/trades?search=SOL",
        headers=admin_auth,
    )
    assert resp_search.status_code == 200
    search_data = resp_search.json()
    assert search_data["total"] == 1
    assert search_data["items"][0]["symbol"] == "SOLUSDT"
    assert search_data["items"][0]["verificationError"] == "DURATION_TOO_SHORT"

    # 5. Dynamic multiplier test for bitget (configured 2.0, stamped 1.0 -> resolves to 2.0)
    resp_bitget = await test_client.get(
        "/api/v1/hub/mining/analytics/trades?exchange=bitget_futures",
        headers=admin_auth,
    )
    assert resp_bitget.status_code == 200
    bitget_data = resp_bitget.json()
    assert bitget_data["total"] == 1
    assert bitget_data["items"][0]["miningMultiplier"] == 2.0
