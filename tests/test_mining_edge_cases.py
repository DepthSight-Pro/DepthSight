# tests/test_mining_edge_cases.py
"""
Edge-case coverage for the mining subsystem: banned nodes, telemetry HMAC,
wallet-gated activation, central-hub status, referrer binding and the public
node list.
"""

import datetime
import hashlib
import hmac
import json

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


def _make_app_config(
    user_id: int,
    weex: dict,
    mining_enabled: bool = True,
    notifications: dict = None,
) -> models.AppConfig:
    cfg = models.AppConfig(
        user_id=user_id,
        is_mining_enabled=mining_enabled,
        risk_management={},
        notifications=notifications or {},
        data_sources={},
    )
    cfg.exchange_settings = {"weex": weex}
    return cfg


async def test_banned_node_rejected_on_mining_endpoints(
    test_client: AsyncClient, db_session: AsyncSession
):
    """A banned node gets 403 from every node-credential-gated endpoint."""
    node = models.HubNode(
        node_uuid="banned-node",
        name="Banned",
        secret_hash=hashlib.sha256("sec-ban".encode()).hexdigest(),
        is_banned=True,
    )
    db_session.add(node)
    await db_session.commit()

    headers = {"X-Node-UUID": "banned-node", "X-Node-Secret": "sec-ban"}
    for path in ("/api/v1/hub/mining/status", "/api/v1/hub/mining/node-trades"):
        resp = await test_client.get(path, headers=headers)
        assert resp.status_code == 403
        assert "banned" in resp.json()["error"].lower()


async def test_telemetry_report_hmac_gate(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Telemetry submission requires all headers and a valid HMAC body signature."""
    secret = "sec-hmac"
    node = models.HubNode(
        node_uuid="hmac-node",
        name="HmacNode",
        secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
    )
    db_session.add(node)
    await db_session.commit()

    payload = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entry_price": 10.0,
        "exit_price": 11.0,
        "trade_mode": "LIVE",
        "exchange_id": "weex",
        "market_type": "futures",
        "broker_trade_id": "hmac-trade-1",
        "trade_volume_usdt": 100.0,
        "market_context": {},
    }

    # Missing all credentials.
    resp = await test_client.post("/api/v1/hub/telemetry/report", json=payload)
    assert resp.status_code == 401

    # Missing signature header.
    resp = await test_client.post(
        "/api/v1/hub/telemetry/report",
        json=payload,
        headers={"X-Node-UUID": "hmac-node", "X-Node-Secret": secret},
    )
    assert resp.status_code == 401

    # Invalid HMAC signature.
    body = json.dumps(payload, sort_keys=True).encode()
    resp = await test_client.post(
        "/api/v1/hub/telemetry/report",
        content=body,
        headers={
            "X-Node-UUID": "hmac-node",
            "X-Node-Secret": secret,
            "X-Node-Signature": "deadbeef",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 403

    # Valid HMAC signature.
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    resp = await test_client.post(
        "/api/v1/hub/telemetry/report",
        content=body,
        headers={
            "X-Node-UUID": "hmac-node",
            "X-Node-Secret": secret,
            "X-Node-Signature": signature,
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 201

    res = await db_session.execute(
        select(models.HubTelemetryReport).where(
            models.HubTelemetryReport.broker_trade_id == "hmac-trade-1"
        )
    )
    report = res.scalars().first()
    assert report is not None
    assert report.node_uuid == "hmac-node"
    assert report.verification_status == "PENDING"  # weex is verifiable


async def test_mining_activate_requires_wallet(
    authenticated_client_factory, db_session: AsyncSession
):
    """Activating mining without a wallet-derived node identity is rejected."""
    user = models.User(
        username="activate-user",
        email="activate-user@example.com",
        hashed_password="hash",
        is_active=True,
        role="user",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    db_session.add(_make_app_config(user.id, weex={}))
    await db_session.commit()

    client = await authenticated_client_factory(user)
    resp = await client.post("/api/v1/mining/activate", json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "WALLET_REQUIRED"

    # Even a mining_node_uuid without wallet_configured is rejected.
    cfg = await db_session.get(models.AppConfig, user.id)
    cfg.exchange_settings = {
        "weex": {"mining_node_uuid": "some-uuid", "mining_node_secret": "sec"}
    }
    await db_session.commit()
    resp = await client.post("/api/v1/mining/activate", json={})
    assert resp.status_code == 400
    assert resp.json()["error"] == "WALLET_REQUIRED"


async def test_mining_deactivate_disables_mining(
    authenticated_client_factory, db_session: AsyncSession
):
    """Deactivate flips is_mining_enabled off and telemetry sharing off."""
    user = models.User(
        username="deactivate-user",
        email="deactivate-user@example.com",
        hashed_password="hash",
        is_active=True,
        role="user",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    cfg = _make_app_config(
        user.id,
        weex={"mining_node_uuid": "n", "wallet_configured": True},
        notifications={"shareTelemetry": True},
    )
    db_session.add(cfg)
    await db_session.commit()

    client = await authenticated_client_factory(user)
    resp = await client.post("/api/v1/mining/deactivate")
    assert resp.status_code == 200
    assert resp.json()["data"]["success"] is True

    await db_session.refresh(cfg)
    assert cfg.is_mining_enabled is False
    assert cfg.notifications.get("shareTelemetry") is False


async def test_central_hub_status_uses_wallet_node(
    monkeypatch,
    authenticated_client_factory,
    db_session: AsyncSession,
):
    """In central mode the mining status resolves the wallet-derived node."""
    monkeypatch.setenv("IS_CENTRAL_HUB", "true")

    user = models.User(
        username="central-user",
        email="central-user@example.com",
        hashed_password="hash",
        is_active=True,
        role="user",
        referral_code="CENTRAL-REF-1",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    db_session.add(
        models.HubNode(
            node_uuid="wallet-central-node",
            name="WalletCentral",
            secret_hash="",
            node_referral_code="CENTRAL-REF-1",
        )
    )
    db_session.add(
        models.NodeMiningConfig(
            id=1, is_global_mining_enabled=True, user_reward_share_percent=75.0
        )
    )
    db_session.add(
        _make_app_config(
            user.id,
            weex={
                "mining_node_uuid": "wallet-central-node",
                "wallet_address": f"0x{user.id:040x}",
                "wallet_configured": True,
            },
        )
    )
    await db_session.commit()

    client = await authenticated_client_factory(user)
    resp = await client.get("/api/v1/mining/status")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["nodeUuid"] == "wallet-central-node"
    assert data["isMiningEnabled"] is True
    assert data["registeredOnHub"] is True


async def test_register_node_with_user_referrer_code(
    test_client: AsyncClient, db_session: AsyncSession
):
    """/nodes/register binds a referrer passed as the user's referral code."""
    referrer_user = models.User(
        username="referrer-user-e6",
        email="referrer-user-e6@example.com",
        hashed_password="hash",
        is_active=True,
        role="user",
        referral_code="USER-REF-E6",
    )
    db_session.add(referrer_user)
    db_session.add(
        models.HubNode(
            node_uuid="ref-node-e6",
            name="RefNode",
            secret_hash="h",
            node_referral_code="USER-REF-E6",
        )
    )
    await db_session.commit()

    resp = await test_client.post(
        "/api/v1/hub/nodes/register",
        json={
            "node_uuid": "new-node-e6",
            "name": "NewNode",
            "node_secret": "sec-new",
            "referrer_code": "USER-REF-E6",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["node_referral_code"]

    res = await db_session.execute(
        select(models.HubNode).where(models.HubNode.node_uuid == "new-node-e6")
    )
    new_node = res.scalars().first()
    assert new_node is not None
    assert new_node.referrer_node_uuid == "ref-node-e6"

    # Unknown referrer codes leave the node unlinked (legacy behaviour).
    resp = await test_client.post(
        "/api/v1/hub/nodes/register",
        json={
            "node_uuid": "new-node-e6b",
            "name": "NewNodeB",
            "node_secret": "sec-new-b",
            "referrer_code": "NO-SUCH-CODE",
        },
    )
    assert resp.status_code == 201
    res = await db_session.execute(
        select(models.HubNode).where(models.HubNode.node_uuid == "new-node-e6b")
    )
    new_node_b = res.scalars().first()
    assert new_node_b.referrer_node_uuid is None


async def test_nodes_list_hides_banned(
    test_client: AsyncClient, db_session: AsyncSession
):
    """The public node list only returns active, non-banned nodes."""
    now = datetime.datetime.now(datetime.timezone.utc)
    db_session.add(
        models.HubNode(
            node_uuid="list-node-ok",
            name="ListOk",
            secret_hash="h",
            last_ping=now,
        )
    )
    db_session.add(
        models.HubNode(
            node_uuid="list-node-ban",
            name="ListBan",
            secret_hash="h",
            last_ping=now,
            is_banned=True,
        )
    )
    await db_session.commit()

    resp = await test_client.get("/api/v1/hub/nodes")
    assert resp.status_code == 200
    nodes = resp.json()
    names = [n["name"] for n in nodes]
    assert "ListOk" in names
    assert "ListBan" not in names
