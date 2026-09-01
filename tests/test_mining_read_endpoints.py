# tests/test_mining_read_endpoints.py
"""
HTTP coverage for the hub's user-facing mining read endpoints that had no tests:
/mining/referrals, /mining/node-trades, /mining/process-epoch,
/nodes/designate-operator and /telemetry/insights.
"""

import datetime
import hashlib

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from api import models
from api.depthsight_api import app
from api.hub_router import router as hub_router

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def ensure_hub_router_registered():
    has_hub = any(
        getattr(route, "path", "").startswith("/api/v1/hub") for route in app.routes
    )
    if not has_hub:
        app.include_router(hub_router)


async def test_mining_referrals_user_and_node_level(
    test_client: AsyncClient,
    authenticated_client_factory,
    db_session: AsyncSession,
):
    """User-level and node-level referrals are aggregated, deduped and gated."""

    referrer = models.User(
        username="ref-parent",
        email="ref-parent@example.com",
        hashed_password="hash",
        is_active=True,
        role="user",
        referral_code="REF-PARENT-CODE",
    )
    db_session.add(referrer)
    await db_session.commit()
    await db_session.refresh(referrer)

    # User-level referral: ref_user signed up under referrer.
    ref_user = models.User(
        username="ref-child",
        email="ref-child@example.com",
        hashed_password="hash",
        is_active=True,
        role="user",
        referred_by_user_id=referrer.id,
        referral_code="REF-CHILD-CODE",
    )
    db_session.add(ref_user)
    await db_session.commit()
    await db_session.refresh(ref_user)

    # The referrer's own mining node + a node-level referral.
    parent_node = models.HubNode(
        node_uuid="ref-parent-node",
        name="ParentNode",
        secret_hash=hashlib.sha256("ref-parent-secret".encode()).hexdigest(),
        node_referral_code="REF-PARENT-CODE",
    )
    child_node = models.HubNode(
        node_uuid="ref-child-node",
        name="ChildNode",
        secret_hash="hash",
        node_referral_code="REF-CHILD-CODE",
        referrer_node_uuid="ref-parent-node",
    )
    db_session.add_all([parent_node, child_node])

    # Parent earned 5.0 referral bonus from a past epoch.
    db_session.add(
        models.MiningLedger(
            node_uuid="ref-parent-node",
            epoch_date=datetime.date.today() - datetime.timedelta(days=2),
            base_reward=0.0,
            referral_bonus=5.0,
            welcome_bonus=0.0,
            boost_multiplier=1.0,
            total_reward=5.0,
            total_rebate_usdt=0.0,
            verified_trades_count=0,
        )
    )
    await db_session.commit()

    client = await authenticated_client_factory(referrer)
    resp = await client.get("/api/v1/hub/mining/referrals")
    assert resp.status_code == 200
    data = resp.json()["data"] if "data" in resp.json() else resp.json()
    assert data["totalInvited"] == 1  # ref_user (child_node deduped by user id)
    assert data["totalReferralRewardsDepth"] == pytest.approx(5.0, rel=1e-6)
    assert data["referrals"][0]["name"] == "ref-child"

    # Node-credential gate: spoofing another node's UUID with a bad secret is rejected.
    resp = await test_client.get(
        "/api/v1/hub/mining/referrals",
        headers={"X-Node-UUID": "ref-parent-node", "X-Node-Secret": "wrong-secret"},
    )
    assert resp.status_code == 403

    # Unauthenticated (no bearer) request still works without user scoping.
    resp = await test_client.get("/api/v1/hub/mining/referrals")
    assert resp.status_code == 200

    # The node-scoped view with valid credentials sees the node-level referral.
    resp = await test_client.get(
        "/api/v1/hub/mining/referrals",
        headers={
            "X-Node-UUID": "ref-parent-node",
            "X-Node-Secret": "ref-parent-secret",
        },
    )
    assert resp.status_code == 200
    node_view = resp.json()
    assert node_view["totalInvited"] == 1
    assert node_view["referrals"][0]["name"] == "ChildNode"


async def test_mining_node_trades_filters_and_pagination(
    test_client: AsyncClient, db_session: AsyncSession
):
    """node-trades shows own + referred nodes, honors filters and pagination."""
    node_secret = "secret-trades"
    node = models.HubNode(
        node_uuid="trades-node",
        name="TradesNode",
        secret_hash=hashlib.sha256(node_secret.encode()).hexdigest(),
    )
    child = models.HubNode(
        node_uuid="trades-child",
        name="TradesChild",
        secret_hash="hash",
        referrer_node_uuid="trades-node",
    )
    db_session.add_all([node, child])

    base = {
        "direction": "LONG",
        "entry_price": 10.0,
        "exit_price": 11.0,
        "trade_mode": "LIVE",
        "is_mining_eligible": True,
        "created_at": datetime.datetime.now(datetime.timezone.utc),
    }
    db_session.add_all(
        [
            models.HubTelemetryReport(
                **base,
                symbol="BTCUSDT",
                node_uuid="trades-node",
                exchange_id="weex",
                market_type="futures",
                verification_status="VERIFIED",
                trade_volume_usdt=100.0,
                broker_trade_id="t1",
            ),
            models.HubTelemetryReport(
                **base,
                symbol="BTCUSDT",
                node_uuid="trades-child",
                exchange_id="bybit",
                market_type="linear",
                verification_status="PENDING",
                trade_volume_usdt=200.0,
                broker_trade_id="t2",
            ),
            models.HubTelemetryReport(
                **base,
                symbol="ETHUSDT",
                node_uuid="trades-node",
                exchange_id="weex",
                market_type="futures",
                verification_status="VERIFIED",
                trade_volume_usdt=300.0,
                broker_trade_id="unique-search-target-1",
            ),
        ]
    )
    await db_session.commit()

    headers = {
        "X-Node-UUID": "trades-node",
        "X-Node-Secret": node_secret,
    }

    resp = await test_client.get("/api/v1/hub/mining/node-trades", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 3  # own + child

    resp = await test_client.get(
        "/api/v1/hub/mining/node-trades", headers=headers, params={"exchange": "bybit"}
    )
    assert resp.json()["total"] == 1

    resp = await test_client.get(
        "/api/v1/hub/mining/node-trades",
        headers=headers,
        params={"status_filter": "VERIFIED"},
    )
    assert resp.json()["total"] == 2

    resp = await test_client.get(
        "/api/v1/hub/mining/node-trades",
        headers=headers,
        params={"search": "unique-search"},
    )
    assert resp.json()["total"] == 1

    resp = await test_client.get(
        "/api/v1/hub/mining/node-trades", headers=headers, params={"limit": 2}
    )
    body = resp.json()
    assert body["total"] == 3
    assert body["totalPages"] == 2
    assert len(body["items"]) == 2

    # Bad secret rejected.
    resp = await test_client.get(
        "/api/v1/hub/mining/node-trades",
        headers={"X-Node-UUID": "trades-node", "X-Node-Secret": "bad"},
    )
    assert resp.status_code == 403


async def test_process_epoch_admin_trigger(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Manual epoch trigger is admin-only and runs the epoch processor."""
    import api.hub_router as hr

    hr.HUB_ADMIN_API_KEY = "test-admin-key-epoch"

    node = models.HubNode(node_uuid="trig-node", name="Trig", secret_hash="h")
    db_session.add(node)
    db_session.add(
        models.MiningConfig(
            is_mining_enabled=True,
            eligible_exchanges=["weex"],
            daily_emission_base=100.0,
            launch_date=datetime.date.today() - datetime.timedelta(days=2),
        )
    )
    await db_session.commit()
    db_session.add(
        models.HubTelemetryReport(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=10.0,
            exit_price=11.0,
            trade_mode="LIVE",
            node_uuid="trig-node",
            estimated_rebate_usdt=10.0,
            is_mining_eligible=True,
            verification_status="VERIFIED",
            created_at=datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=1),
        )
    )
    await db_session.commit()

    # Unauthorized rejected.
    resp = await test_client.post("/api/v1/hub/mining/process-epoch")
    assert resp.status_code == 403

    from contextlib import asynccontextmanager
    from unittest.mock import patch

    @asynccontextmanager
    async def mock_isolated_session():
        yield db_session

    with patch("api.database.get_isolated_worker_session", mock_isolated_session):
        resp = await test_client.post(
            "/api/v1/hub/mining/process-epoch",
            headers={"Authorization": "Bearer test-admin-key-epoch"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    res = await db_session.execute(
        select(models.MiningLedger).where(models.MiningLedger.node_uuid == "trig-node")
    )
    assert res.scalars().first() is not None


async def test_process_epoch_requires_past_epoch_date(
    test_client: AsyncClient, db_session: AsyncSession
):
    """The manual epoch trigger rejects today / future / malformed dates with 400."""
    import api.hub_router as hr

    hr.HUB_ADMIN_API_KEY = "test-admin-key-epoch"
    auth = {"Authorization": "Bearer test-admin-key-epoch"}

    utc_today = datetime.datetime.now(datetime.timezone.utc).date()

    resp = await test_client.post(
        "/api/v1/hub/mining/process-epoch",
        headers=auth,
        json={"epoch_date": (utc_today + datetime.timedelta(days=1)).isoformat()},
    )
    assert resp.status_code == 400
    assert "past day" in resp.json()["detail"]

    resp = await test_client.post(
        "/api/v1/hub/mining/process-epoch",
        headers=auth,
        json={"epoch_date": utc_today.isoformat()},
    )
    assert resp.status_code == 400

    resp = await test_client.post(
        "/api/v1/hub/mining/process-epoch",
        headers=auth,
        json={"epoch_date": "not-a-date"},
    )
    assert resp.status_code == 400


async def test_process_epoch_accepts_past_epoch_date(
    test_client: AsyncClient, db_session: AsyncSession
):
    """A valid past epoch_date is forwarded to the epoch processor."""
    import api.hub_router as hr

    hr.HUB_ADMIN_API_KEY = "test-admin-key-epoch"

    from unittest.mock import patch

    seen = {}

    async def fake_process(**kwargs):
        seen["kwargs"] = kwargs

    target = (
        datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=3)
    ).isoformat()

    with patch("tasks._async_process_mining_epoch", side_effect=fake_process):
        resp = await test_client.post(
            "/api/v1/hub/mining/process-epoch",
            headers={"Authorization": "Bearer test-admin-key-epoch"},
            json={"epoch_date": target},
        )
    assert resp.status_code == 200
    assert seen["kwargs"]["force_yesterday_date"] is not None
    assert seen["kwargs"]["force_yesterday_date"].isoformat() == target


async def test_process_epoch_accepts_empty_body(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Calling the trigger without a body still defaults to yesterday."""
    import api.hub_router as hr

    hr.HUB_ADMIN_API_KEY = "test-admin-key-epoch"

    from unittest.mock import patch

    seen = {}

    async def fake_process(**kwargs):
        seen["kwargs"] = kwargs

    with patch("tasks._async_process_mining_epoch", side_effect=fake_process):
        resp = await test_client.post(
            "/api/v1/hub/mining/process-epoch",
            headers={"Authorization": "Bearer test-admin-key-epoch"},
        )
    assert resp.status_code == 200
    expected = datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(
        days=1
    )
    assert seen["kwargs"]["force_yesterday_date"] == expected


async def test_designate_operator_endpoint(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Designate-operator requires admin auth and the node's own secret."""
    import api.hub_router as hr

    hr.HUB_ADMIN_API_KEY = "test-admin-key-op"
    node = models.HubNode(
        node_uuid="op-designate-node",
        name="Designate",
        secret_hash=hashlib.sha256("secret-op".encode()).hexdigest(),
    )
    db_session.add(node)
    await db_session.commit()

    base_payload = {"node_uuid": "op-designate-node", "name": "Designate"}

    # Unauthorized.
    resp = await test_client.post(
        "/api/v1/hub/nodes/designate-operator",
        json={**base_payload, "node_secret": "secret-op"},
    )
    assert resp.status_code == 403

    headers = {"Authorization": "Bearer test-admin-key-op"}

    # Wrong secret.
    resp = await test_client.post(
        "/api/v1/hub/nodes/designate-operator",
        json={**base_payload, "node_secret": "wrong-secret"},
        headers=headers,
    )
    assert resp.status_code == 403

    # Unknown node.
    resp = await test_client.post(
        "/api/v1/hub/nodes/designate-operator",
        json={"node_uuid": "missing-node", "name": "Missing", "node_secret": "s"},
        headers=headers,
    )
    assert resp.status_code == 404

    # Success.
    resp = await test_client.post(
        "/api/v1/hub/nodes/designate-operator",
        json={**base_payload, "node_secret": "secret-op"},
        headers=headers,
    )
    assert resp.status_code == 200

    db_session.expire_all()
    updated = (
        (
            await db_session.execute(
                select(models.HubNode).where(
                    models.HubNode.node_uuid == "op-designate-node"
                )
            )
        )
        .scalars()
        .first()
    )
    assert updated.is_operator is True


async def test_telemetry_insights_aggregation(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Insights require >=5 trades per combo and sort by win rate."""
    now = datetime.datetime.now(datetime.timezone.utc)

    def _report(symbol, blocks, pnl, reason="take_profit"):
        return models.HubTelemetryReport(
            symbol=symbol,
            direction="LONG",
            entry_price=10.0,
            exit_price=11.0,
            pnl_percent=pnl,
            trade_mode="LIVE",
            node_uuid="ins-node",
            strategy_blocks=blocks,
            market_context={},
            exit_reason=reason,
            is_mining_eligible=True,
            created_at=now,
        )

    reports = []
    # Combo "a + b": 5 trades, all winners => 100% win rate, avg 3.0.
    for i in range(5):
        reports.append(
            _report(
                "BTCUSDT",
                [{"type": "a"}, {"type": "b"}],
                float(i + 1),
                "take_profit" if i < 3 else "stop_loss",
            )
        )
    # Combo "x": only 3 trades => below the threshold, excluded.
    for i in range(3):
        reports.append(_report("BTCUSDT", [{"type": "x"}], -1.0))
    db_session.add_all(reports)
    await db_session.commit()

    resp = await test_client.get("/api/v1/hub/telemetry/insights")
    assert resp.status_code == 200
    insights = resp.json()
    assert len(insights) == 1
    combo = insights[0]
    assert combo["comboKey"] == "a + b"
    assert combo["totalTrades"] == 5
    assert combo["winRate"] == 100.0
    assert combo["avgPnlPercent"] == pytest.approx(3.0, abs=1e-3)
    assert combo["bestExitReasons"][0] == "take_profit"

    # Symbol filter: combo present only for the matching symbol.
    resp = await test_client.get(
        "/api/v1/hub/telemetry/insights", params={"symbol": "ETHUSDT"}
    )
    assert resp.status_code == 200
    assert resp.json() == []
