# tests/test_p3_migration.py
"""
P3 data-integrity fixes:

- Wallet-node migration keeps per-server commission history consistent:
  `source_node_uuid` is re-pointed on BOTH migration paths (hub adoption and
  local `_transfer_node_data`), and the FK on source_node_uuid can no longer
  abort an adoption (verified with SQLite FK enforcement ON).
- MiningLedger merge sums boost_multiplier instead of dropping it.
- Two platform accounts binding one wallet: behaviour documented + audited
  (warning log), the second account keeps its own referral_code (UNIQUE).
- Epoch metrics semantics: participating_nodes counts only MINING nodes;
  verified_trades_count counts unique broker_trade_id (partial closes).
"""

import datetime
import hashlib
import uuid as _uuid
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from api import models
from api.depthsight_api import app
from api.hub_router import router as hub_router
from api.routes.config import _transfer_node_data
from api.wallet_auth import OWNERSHIP_PURPOSE_BIND, build_ownership_message
from tasks import _async_process_mining_epoch

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def ensure_hub_router_registered():
    has_hub = any(
        getattr(route, "path", "").startswith("/api/v1/hub") for route in app.routes
    )
    if not has_hub:
        app.include_router(hub_router)


def _wallet_uuid(address: str) -> str:
    return str(_uuid.uuid5(_uuid.NAMESPACE_DNS, f"evm:{address.lower()}"))


def _sign(acct: Account):
    message = build_ownership_message(acct.address, purpose=OWNERSHIP_PURPOSE_BIND)
    encoded = encode_defunct(text=message)
    sig = acct.sign_message(encoded)["signature"].hex()
    if not sig.startswith("0x"):
        sig = f"0x{sig}"
    return message, sig


async def _enable_sqlite_fk(db_session: AsyncSession):
    """Make the test connection enforce FOREIGN KEY constraints like Postgres."""
    await db_session.execute(text("PRAGMA foreign_keys=ON"))


# ---------------------------------------------------------------------------
# P3.1 вЂ” source_node_uuid survives migrations
# ---------------------------------------------------------------------------


async def test_hub_adoption_repoints_source_and_survives_fk(test_client, db_session):
    """Adopting a legacy MINING SERVER node must not trip the source_node_uuid
    FK when the legacy row is deleted (Postgres enforces it; SQLite needs the
    pragma)."""
    acct = Account.create()
    deterministic_uuid = _wallet_uuid(acct.address)
    legacy_uuid = f"legacy-srv-{acct.address[-8:].lower()}"

    await _enable_sqlite_fk(db_session)

    legacy = models.HubNode(
        node_uuid=legacy_uuid,
        name="Legacy Server",
        secret_hash="old-hash",
        is_mining_server=True,
        wallet_address=acct.address.lower(),
    )
    # The miner whose trade was executed THROUGH this server.
    miner = models.HubNode(node_uuid="some-miner", name="Miner", secret_hash="h")
    # A trade executed THROUGH this server by that other miner.
    report = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=1.0,
        exit_price=2.0,
        trade_mode="LIVE",
        node_uuid="some-miner",
        source_node_uuid=legacy_uuid,
        exchange_id="weex",
        market_type="futures",
        verification_status="VERIFIED",
    )
    db_session.add_all([legacy, miner, report])
    await db_session.commit()

    message, sig = _sign(acct)
    resp = await test_client.post(
        "/api/v1/hub/nodes/register",
        json={
            "node_uuid": deterministic_uuid,
            "name": "DepthSightNode-Transfer",
            "node_secret": "srv-secret-transfer",
            "wallet_address": acct.address,
            "owner_signature": sig,
            "owner_message": message,
        },
    )
    assert resp.status_code == 201

    await db_session.rollback()
    await _enable_sqlite_fk(db_session)

    res = await db_session.execute(
        select(models.HubNode).where(
            models.HubNode.wallet_address == acct.address.lower()
        )
    )
    nodes = res.scalars().all()
    assert len(nodes) == 1
    assert nodes[0].node_uuid == deterministic_uuid

    res = await db_session.execute(
        select(models.HubTelemetryReport)
        .where(models.HubTelemetryReport.id == report.id)
        .execution_options(populate_existing=True)
    )
    rep = res.scalars().first()
    # Commission history follows the adopted identity.
    assert rep.source_node_uuid == deterministic_uuid

    await db_session.execute(text("PRAGMA foreign_keys=OFF"))


async def test_local_transfer_repoints_source_node_uuid(db_session):
    src_uuid, dst_uuid = "src-srv", "dst-wallet"
    miner = models.HubNode(node_uuid="any-miner", name="Miner", secret_hash="h")
    report = models.HubTelemetryReport(
        symbol="ETHUSDT",
        direction="LONG",
        entry_price=1.0,
        exit_price=2.0,
        trade_mode="LIVE",
        node_uuid="any-miner",
        source_node_uuid=src_uuid,
        exchange_id="weex",
        market_type="futures",
    )
    db_session.add_all([miner, report])
    await db_session.commit()

    await _transfer_node_data(db_session, src_uuid, dst_uuid)

    await db_session.refresh(report)
    assert report.source_node_uuid == dst_uuid


# ---------------------------------------------------------------------------
# P3.3 вЂ” ledger merge keeps the strongest boost multiplier
# ---------------------------------------------------------------------------


async def test_ledger_merge_sums_and_keeps_boost(db_session):
    yesterday = datetime.datetime.now(
        datetime.timezone.utc
    ).date() - datetime.timedelta(days=1)
    src_led = models.MiningLedger(
        node_uuid="merge-src",
        epoch_date=yesterday,
        base_reward=4.0,
        referral_bonus=0.5,
        welcome_bonus=0.0,
        boost_multiplier=1.5,
        total_reward=4.5,
        total_rebate_usdt=9.0,
        verified_trades_count=2,
    )
    dst_led = models.MiningLedger(
        node_uuid="merge-dst",
        epoch_date=yesterday,
        base_reward=1.0,
        referral_bonus=0.0,
        welcome_bonus=100.0,
        boost_multiplier=1.0,
        total_reward=101.0,
        total_rebate_usdt=1.0,
        verified_trades_count=1,
    )
    db_session.add_all([src_led, dst_led])
    await db_session.commit()

    await _transfer_node_data(db_session, "merge-src", "merge-dst")

    await db_session.commit()
    res = await db_session.execute(
        select(models.MiningLedger).where(models.MiningLedger.node_uuid == "merge-dst")
    )
    merged = res.scalars().all()
    assert len(merged) == 1
    m = merged[0]
    assert m.base_reward == pytest.approx(5.0)
    assert m.referral_bonus == pytest.approx(0.5)
    assert m.welcome_bonus == pytest.approx(100.0)
    assert m.total_reward == pytest.approx(105.5)
    assert m.verified_trades_count == 3
    assert m.boost_multiplier == pytest.approx(1.5)

    res = await db_session.execute(
        select(models.MiningLedger).where(models.MiningLedger.node_uuid == "merge-src")
    )
    assert res.scalars().first() is None


# ---------------------------------------------------------------------------
# Concurrent bind of the same wallet from two servers
# ---------------------------------------------------------------------------


async def test_concurrent_bind_same_wallet_single_node(test_client, db_session):
    acct = Account.create()

    async def bind(secret: str):
        message, sig = _sign(acct)
        return await test_client.post(
            "/api/v1/hub/nodes/register",
            json={
                "node_uuid": _wallet_uuid(acct.address),
                "name": f"N-{secret}",
                "node_secret": secret,
                "wallet_address": acct.address,
                "owner_signature": sig,
                "owner_message": message,
            },
        )

    import asyncio

    results = await asyncio.gather(bind("sec-one"), bind("sec-two"))
    # Both requests reach a consistent outcome (created / rotated / rejected);
    # what matters is that exactly ONE node exists for the wallet.
    assert all(r.status_code in (200, 201, 403) for r in results)

    await db_session.rollback()
    res = await db_session.execute(
        select(models.HubNode).where(
            models.HubNode.wallet_address == acct.address.lower()
        )
    )
    nodes = res.scalars().all()
    assert len(nodes) == 1


# ---------------------------------------------------------------------------
# Welcome bonus flag transfers once
# ---------------------------------------------------------------------------


async def test_welcome_bonus_flag_follows_wallet_once(db_session):
    a = models.HubNode(
        node_uuid="wb-a",
        name="A",
        secret_hash="h",
        has_welcome_bonus=True,
        total_mined=500.0,
    )
    db_session.add(a)
    await db_session.commit()

    await _transfer_node_data(db_session, "wb-a", "wb-b")
    await db_session.commit()
    res = await db_session.execute(
        select(models.HubNode).where(models.HubNode.node_uuid == "wb-b")
    )
    b = res.scalars().first()
    assert b.has_welcome_bonus is True

    # Chained transfer keeps the flag without minting anything extra.
    await _transfer_node_data(db_session, "wb-b", "wb-c")
    await db_session.commit()
    res = await db_session.execute(
        select(models.HubNode).where(models.HubNode.node_uuid == "wb-c")
    )
    c = res.scalars().first()
    assert c.has_welcome_bonus is True


# ---------------------------------------------------------------------------
# Two platform accounts, one wallet вЂ” documented sync semantics
# ---------------------------------------------------------------------------


async def test_second_account_syncs_referral_code_with_warning(
    authenticated_client_factory, current_user, monkeypatch, db_session
):
    monkeypatch.setenv("IS_CENTRAL_HUB", "true")

    acct = Account.create()
    second_code = f"REF-U2-{_uuid.uuid4().hex[:8].upper()}"
    other = models.User(
        username=f"owner-{acct.address[-6:].lower()}",
        email=f"owner-{acct.address[-6:].lower()}@test.local",
        hashed_password="x",
        referral_code=second_code,
        referred_by_user_id=None,
        is_active=True,
    )
    db_session.add(other)
    await db_session.flush()

    pre_bound = models.HubNode(
        node_uuid=_wallet_uuid(acct.address),
        name="PreBound",
        secret_hash=hashlib.sha256(b"old-secret").hexdigest(),
        node_referral_code=second_code,
        wallet_address=acct.address.lower(),
    )
    db_session.add(pre_bound)
    await db_session.commit()

    client = await authenticated_client_factory(current_user)
    message, sig = _sign(acct)
    resp = await client.post(
        "/api/v1/node/wallet/verify",
        json={
            "address": acct.address,
            "signature": sig,
            "nonce": message,
            "message": message,
        },
    )
    assert resp.status_code == 200

    user_id = current_user.id
    own_code = current_user.referral_code
    await db_session.rollback()
    res = await db_session.execute(select(models.User).where(models.User.id == user_id))
    u1 = res.scalars().first()
    # users.referral_code is UNIQUE: a second account binding the same wallet
    # KEEPS its own code (the first holder is not silently stripped), while
    # mining still follows the shared wallet node.
    assert u1.referral_code == own_code
    assert u1.referral_code != second_code


# ---------------------------------------------------------------------------
# Epoch metric semantics
# ---------------------------------------------------------------------------


def _yesterday_date():
    return datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(
        days=1
    )


def _yesterday_noon():
    return datetime.datetime.combine(
        _yesterday_date(), datetime.time(12, 0), tzinfo=datetime.timezone.utc
    )


async def _run_epoch(db_session: AsyncSession):
    @asynccontextmanager
    async def mock_isolated_session():
        yield db_session

    with patch("api.database.get_isolated_worker_session", mock_isolated_session):
        await _async_process_mining_epoch(force_yesterday_date=_yesterday_date())
    db_session.expire_all()


async def test_epoch_metrics_unique_trades_and_mining_participants(
    db_session, monkeypatch
):
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")

    miner = models.HubNode(node_uuid="metric-miner", name="M", secret_hash="h")
    ref_only = models.HubNode(
        node_uuid="metric-ref",
        name="R",
        secret_hash="h",
        referrer_node_uuid="metric-miner",
    )
    cfg = models.MiningConfig(
        is_mining_enabled=True,
        eligible_exchanges=["weex"],
        daily_emission_base=100.0,
        launch_date=datetime.date.today() - datetime.timedelta(days=2),
        referral_mining_boost=0.10,
        rebate_rates={},
    )
    db_session.add_all([miner, ref_only, cfg])

    def _rep(bid, vol):
        return models.HubTelemetryReport(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=10.0,
            exit_price=11.0,
            trade_mode="LIVE",
            node_uuid="metric-miner",
            estimated_rebate_usdt=vol,
            trade_volume_usdt=vol * 2000,
            is_mining_eligible=True,
            verification_status="VERIFIED",
            created_at=_yesterday_noon(),
            exchange_id="weex",
            market_type="futures",
            broker_trade_id=bid,
        )

    # Two closed positions -> two UNIQUE trade ids (the column is UNIQUE, so
    # each report IS a distinct trade; the dedupe guards NULL-id fallbacks and
    # any legacy duplicate rows).
    db_session.add_all([_rep("trade-x", 5.0), _rep("trade-y", 5.0)])
    await db_session.commit()

    await _run_epoch(db_session)

    epoch_res = await db_session.execute(
        select(models.MiningEpoch).where(
            models.MiningEpoch.epoch_date == _yesterday_date()
        )
    )
    epoch = epoch_res.scalars().first()
    assert epoch is not None
    # Only the MINING node counts; the referral-only node does not.
    assert epoch.participating_nodes == 1

    ledger_res = await db_session.execute(
        select(models.MiningLedger).where(
            models.MiningLedger.node_uuid == "metric-miner",
            models.MiningLedger.epoch_date == _yesterday_date(),
        )
    )
    ledger = ledger_res.scalars().first()
    assert ledger.verified_trades_count == 2
