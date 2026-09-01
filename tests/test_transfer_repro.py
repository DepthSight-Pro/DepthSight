# tests/test_transfer_repro.py
"""
Reproduces the cross-server account "transfer" flow to find why a NEW node
gets created instead of the existing wallet node being re-keyed.
"""

import uuid

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from sqlalchemy.future import select

from api import crud, models
from api.depthsight_api import app
from api.hub_router import router as hub_router
from api.wallet_auth import (
    OWNERSHIP_PURPOSE_BIND,
    build_ownership_message,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def ensure_hub_router_registered():
    has_hub = any(
        getattr(route, "path", "").startswith("/api/v1/hub") for route in app.routes
    )
    if not has_hub:
        app.include_router(hub_router)


def _sign_ownership(acct: Account):
    message = build_ownership_message(acct.address, purpose=OWNERSHIP_PURPOSE_BIND)
    encoded = encode_defunct(text=message)
    sig = acct.sign_message(encoded)["signature"].hex()
    if not sig.startswith("0x"):
        sig = f"0x{sig}"
    return message, sig


def _wallet_uuid(addr: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"evm:{addr.strip().lower()}"))


async def _count_by_wallet(db_session, addr: str) -> int:
    res = await db_session.execute(
        select(models.HubNode).where(models.HubNode.wallet_address == addr.lower())
    )
    return len(res.scalars().all())


async def test_transfer_between_two_servers(test_client, db_session):
    """Server A binds wallet -> hub node. Server B binds same wallet -> RE-KEY, not new."""
    acct = Account.create()
    node_uuid = _wallet_uuid(acct.address)
    message, sig = _sign_ownership(acct)

    # Server A
    payload_a = {
        "node_uuid": node_uuid,
        "name": "DepthSightNode-A",
        "node_secret": "secret-A",
        "wallet_address": acct.address,
        "owner_signature": sig,
        "owner_message": message,
    }
    resp = await test_client.post("/api/v1/hub/nodes/register", json=payload_a)
    assert resp.status_code == 201

    # Server B - same wallet, new telemetry secret
    message2, sig2 = _sign_ownership(acct)
    payload_b = {
        "node_uuid": node_uuid,
        "name": "DepthSightNode-B",
        "node_secret": "secret-B",
        "wallet_address": acct.address,
        "owner_signature": sig2,
        "owner_message": message2,
    }
    resp = await test_client.post("/api/v1/hub/nodes/register", json=payload_b)
    assert resp.status_code in (200, 201)

    # Must be exactly ONE node for this wallet, re-keyed to secret-B
    assert await _count_by_wallet(db_session, acct.address) == 1

    res = await db_session.execute(
        select(models.HubNode)
        .where(models.HubNode.node_uuid == node_uuid)
        .execution_options(populate_existing=True)
    )
    node = res.scalars().first()
    import hashlib

    assert node.secret_hash == hashlib.sha256(b"secret-B").hexdigest()
    assert node.name == "DepthSightNode-B"


async def test_transfer_from_legacy_no_wallet_node(test_client, db_session):
    """
    Server A activated mining BEFORE wallet feature: hub node exists with the
    deterministic uuid but NO wallet_address. Server B binds wallet -> the SAME
    node must get the wallet bound (not a new node).
    """
    acct = Account.create()
    node_uuid = _wallet_uuid(acct.address)
    import hashlib

    # Legacy node created by activate_local_mining (no wallet info in payload)
    legacy_payload = {
        "node_uuid": node_uuid,
        "name": "DepthSightNode-legacy",
        "node_secret": "secret-A",
        "version": "1.0.0",
    }
    resp = await test_client.post("/api/v1/hub/nodes/register", json=legacy_payload)
    assert resp.status_code == 201

    # Server B binds the wallet with a valid owner signature
    message, sig = _sign_ownership(acct)
    bind_payload = {
        "node_uuid": node_uuid,
        "name": "DepthSightNode-B",
        "node_secret": "secret-B",
        "wallet_address": acct.address,
        "owner_signature": sig,
        "owner_message": message,
    }
    resp = await test_client.post("/api/v1/hub/nodes/register", json=bind_payload)
    assert resp.status_code in (200, 201)

    assert await _count_by_wallet(db_session, acct.address) == 1
    res = await db_session.execute(
        select(models.HubNode)
        .where(models.HubNode.node_uuid == node_uuid)
        .execution_options(populate_existing=True)
    )
    node = res.scalars().first()
    assert node.wallet_address == acct.address.lower()
    assert node.secret_hash == hashlib.sha256(b"secret-B").hexdigest()


async def test_hub_adopts_legacy_node_without_wallet(test_client, db_session):
    """
    A legacy node created BEFORE wallet support (random uuid, NO wallet_address)
    owned by the same account must be adopted under the deterministic wallet uuid
    when the wallet is registered, so mining data, referral code and referral links
    carry over instead of being orphaned on a brand-new node.
    """
    import hashlib
    from datetime import date

    acct = Account.create()
    deterministic_uuid = _wallet_uuid(acct.address)
    legacy_uuid = f"legacy-{uuid.uuid4().hex[:8]}"

    # Legacy node: random uuid, no wallet_address, carries the mining history.
    legacy = models.HubNode(
        node_uuid=legacy_uuid,
        name="DepthSightNode-legacy",
        secret_hash=hashlib.sha256(b"old-secret").hexdigest(),
        node_referral_code="DSN-REF-LEGACY-1234",
        total_mined=42.0,
        has_welcome_bonus=True,
        weex_uid="weex-123",
    )
    db_session.add(legacy)
    await db_session.flush()

    telemetry = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="long",
        entry_price=100.0,
        exit_price=110.0,
        trade_mode="futures",
        strategy_blocks=[],
        market_context={},
        node_uuid=legacy_uuid,
        trade_volume_usdt=1000.0,
        estimated_rebate_usdt=5.0,
        is_mining_eligible=True,
        epoch_date=date(2026, 1, 1),
    )
    db_session.add(telemetry)
    ledger = models.MiningLedger(
        node_uuid=legacy_uuid,
        epoch_date=date(2026, 1, 1),
        total_reward=10.0,
    )
    db_session.add(ledger)
    await db_session.commit()

    # The account already knows this wallet (bound on the hub earlier) but its
    # mining node is still the legacy pre-wallet node.
    cfg = await crud.get_config_model(db_session, 1)
    cfg.exchange_settings = {
        "weex": {
            "mining_node_uuid": legacy_uuid,
            "wallet_address": acct.address.lower(),
        }
    }
    await db_session.commit()

    message, sig = _sign_ownership(acct)
    resp = await test_client.post(
        "/api/v1/hub/nodes/register",
        json={
            "node_uuid": deterministic_uuid,
            "name": "DepthSightNode-Transfer",
            "node_secret": "telemetry-secret-new",
            "wallet_address": acct.address,
            "owner_signature": sig,
            "owner_message": message,
        },
    )
    assert resp.status_code == 201

    # Exactly ONE node for this wallet, adopted under the deterministic uuid.
    res = await db_session.execute(
        select(models.HubNode)
        .where(models.HubNode.wallet_address == acct.address.lower())
        .execution_options(populate_existing=True)
    )
    nodes = res.scalars().all()
    assert len(nodes) == 1
    adopted = nodes[0]
    assert adopted.node_uuid == deterministic_uuid
    assert adopted.node_referral_code == "DSN-REF-LEGACY-1234"
    assert adopted.total_mined == 42.0
    assert adopted.has_welcome_bonus is True
    assert adopted.weex_uid == "weex-123"
    assert adopted.secret_hash == hashlib.sha256(b"telemetry-secret-new").hexdigest()

    # Mining history carried over to the deterministic uuid.
    tel_res = await db_session.execute(
        select(models.HubTelemetryReport).where(
            models.HubTelemetryReport.node_uuid == deterministic_uuid
        )
    )
    assert len(tel_res.scalars().all()) == 1
    led_res = await db_session.execute(
        select(models.MiningLedger).where(
            models.MiningLedger.node_uuid == deterministic_uuid
        )
    )
    assert len(led_res.scalars().all()) == 1

    # The legacy row is gone (no orphaned duplicate).
    old_res = await db_session.execute(
        select(models.HubNode).where(models.HubNode.node_uuid == legacy_uuid)
    )
    assert old_res.scalars().first() is None
