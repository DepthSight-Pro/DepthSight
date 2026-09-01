# tests/test_mining_epoch_edges.py
"""
Edge-case coverage for the daily mining epoch processor
(tasks._async_process_mining_epoch): idempotency / double-count protection,
halving math, rebate backfill, welcome-bonus tiers, multi-node dilution and
operator-root fallbacks. These are unit tests that run the epoch processor
against the in-memory test DB.
"""

import datetime
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from api import models
from api.hub_router import _estimate_rebate
from tasks import _async_process_mining_epoch

pytestmark = pytest.mark.asyncio


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


async def _run_epoch(db_session: AsyncSession):
    @asynccontextmanager
    async def mock_isolated_session():
        yield db_session

    with patch("api.database.get_isolated_worker_session", mock_isolated_session):
        await _async_process_mining_epoch(force_yesterday_date=_yesterday())
    db_session.expire_all()


async def _add_report(
    db_session: AsyncSession,
    node_uuid: str,
    rebate: float = None,
    volume: float = None,
    **overrides,
) -> models.HubTelemetryReport:
    report = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=10.0,
        exit_price=11.0,
        trade_mode="LIVE",
        node_uuid=node_uuid,
        estimated_rebate_usdt=rebate,
        trade_volume_usdt=volume,
        is_mining_eligible=True,
        verification_status="VERIFIED",
        created_at=_yesterday_noon(),
    )
    for key, value in overrides.items():
        setattr(report, key, value)
    db_session.add(report)
    await db_session.commit()
    return report


async def _get_ledger(db_session: AsyncSession, node_uuid: str) -> models.MiningLedger:
    res = await db_session.execute(
        select(models.MiningLedger).where(
            models.MiningLedger.node_uuid == node_uuid,
            models.MiningLedger.epoch_date == _yesterday(),
        )
    )
    return res.scalars().first()


async def _get_epoch(db_session: AsyncSession) -> models.MiningEpoch:
    res = await db_session.execute(
        select(models.MiningEpoch).where(models.MiningEpoch.epoch_date == _yesterday())
    )
    return res.scalars().first()


# ---------------------------------------------------------------------------
# P1: Idempotency / double-count protection
# ---------------------------------------------------------------------------


async def test_epoch_skipped_when_finalized(db_session: AsyncSession, monkeypatch):
    """Re-processing an already-finalized epoch must not double-count."""
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    node = models.HubNode(node_uuid="idem-node", name="Idem", secret_hash="h")
    db_session.add(node)
    db_session.add(_make_config())
    await db_session.commit()

    await _add_report(db_session, "idem-node", rebate=10.0)
    await _run_epoch(db_session)

    ledger_after_first = await _get_ledger(db_session, "idem-node")
    assert ledger_after_first is not None
    base_after_first = ledger_after_first.base_reward
    assert base_after_first == pytest.approx(100.0, rel=1e-3)

    # A late-verified report lands after the epoch was finalized.
    late = await _add_report(db_session, "idem-node", rebate=20.0)
    await _run_epoch(db_session)

    ledger_after_second = await _get_ledger(db_session, "idem-node")
    assert ledger_after_second.base_reward == pytest.approx(base_after_first, rel=1e-3)
    # The late report is deferred (epoch_date stays NULL), not attributed twice.
    await db_session.refresh(late)
    assert late.epoch_date is None


async def test_ledger_upsert_is_additive(db_session: AsyncSession, monkeypatch):
    """A pre-existing MiningLedger row is added to, not overwritten."""
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    node = models.HubNode(node_uuid="upsert-node", name="Upsert", secret_hash="h")
    db_session.add(node)
    db_session.add(_make_config())
    db_session.add(
        models.MiningLedger(
            node_uuid="upsert-node",
            epoch_date=_yesterday(),
            base_reward=10.0,
            referral_bonus=0.0,
            welcome_bonus=0.0,
            boost_multiplier=1.0,
            total_reward=10.0,
            total_rebate_usdt=2.0,
            verified_trades_count=1,
        )
    )
    await db_session.commit()

    await _add_report(db_session, "upsert-node", rebate=10.0)
    await _run_epoch(db_session)

    ledger = await _get_ledger(db_session, "upsert-node")
    assert ledger.base_reward == pytest.approx(110.0, rel=1e-3)  # 10 + 100
    assert ledger.total_reward == pytest.approx(110.0, rel=1e-3)
    assert ledger.total_rebate_usdt == pytest.approx(12.0, rel=1e-3)
    assert ledger.verified_trades_count == 2


async def test_empty_epoch_writes_finalized(db_session: AsyncSession):
    """No eligible reports => a finalized zero-reward MiningEpoch is written."""
    db_session.add(_make_config())
    await db_session.commit()

    await _run_epoch(db_session)

    epoch = await _get_epoch(db_session)
    assert epoch is not None
    assert epoch.status == "finalized"
    assert epoch.daily_emission == 0.0
    assert epoch.total_distributed == 0.0
    assert epoch.participating_nodes == 0


async def test_zero_rebate_pool_finalizes(db_session: AsyncSession):
    """Eligible reports with no rebate and no volume finalize with zero payout."""
    node = models.HubNode(node_uuid="zeronode", name="Zero", secret_hash="h")
    db_session.add(node)
    db_session.add(_make_config())
    await db_session.commit()

    await _add_report(db_session, "zeronode", rebate=None, volume=None)
    await _run_epoch(db_session)

    epoch = await _get_epoch(db_session)
    assert epoch is not None
    assert epoch.status == "finalized"
    assert epoch.total_rebate_pool == 0.0
    assert epoch.total_distributed == 0.0
    assert epoch.participating_nodes == 1
    assert await _get_ledger(db_session, "zeronode") is None


async def test_epoch_skipped_when_mining_disabled(db_session: AsyncSession):
    """Mining disabled (or missing config) => no epoch, no ledger."""
    node = models.HubNode(node_uuid="off-node", name="Off", secret_hash="h")
    db_session.add(node)
    db_session.add(_make_config(is_mining_enabled=False))
    await db_session.commit()
    await _add_report(db_session, "off-node", rebate=10.0)

    await _run_epoch(db_session)

    assert await _get_epoch(db_session) is None
    assert await _get_ledger(db_session, "off-node") is None


async def test_total_mined_and_operator_fee_accumulate(
    db_session: AsyncSession, monkeypatch
):
    """HubNode.total_mined and MiningConfig.total_operator_fee_collected update."""
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    root = models.HubNode(
        node_uuid="fee-root", name="Root", secret_hash="h", is_operator=True
    )
    miner = models.HubNode(node_uuid="fee-miner", name="Miner", secret_hash="h")
    db_session.add_all([root, miner])
    db_session.add(_make_config())
    db_session.add(
        models.NodeMiningConfig(
            id=1, is_global_mining_enabled=True, user_reward_share_percent=75.0
        )
    )
    await db_session.commit()

    await _add_report(db_session, "fee-miner", rebate=10.0)
    await _run_epoch(db_session)

    miner_ledger = await _get_ledger(db_session, "fee-miner")
    root_ledger = await _get_ledger(db_session, "fee-root")
    assert miner_ledger.base_reward == pytest.approx(75.0, rel=1e-3)
    assert root_ledger.base_reward == pytest.approx(25.0, rel=1e-3)

    cfg = (
        (
            await db_session.execute(
                select(models.MiningConfig).where(models.MiningConfig.id == 1)
            )
        )
        .scalars()
        .first()
    )
    assert cfg.total_operator_fee_collected == pytest.approx(25.0, rel=1e-3)

    db_session.expire_all()
    miner_node = (
        (
            await db_session.execute(
                select(models.HubNode).where(models.HubNode.node_uuid == "fee-miner")
            )
        )
        .scalars()
        .first()
    )
    root_node = (
        (
            await db_session.execute(
                select(models.HubNode).where(models.HubNode.node_uuid == "fee-root")
            )
        )
        .scalars()
        .first()
    )
    assert miner_node.total_mined == pytest.approx(75.0, rel=1e-3)
    assert root_node.total_mined == pytest.approx(25.0, rel=1e-3)


# ---------------------------------------------------------------------------
# P2: Reward-math branches
# ---------------------------------------------------------------------------


async def test_halving_reduces_emission(db_session: AsyncSession, monkeypatch):
    """daily_emission halves every halving_interval_days after launch."""
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    node = models.HubNode(node_uuid="half-node", name="Half", secret_hash="h")
    db_session.add(node)
    db_session.add(
        _make_config(
            daily_emission_base=100.0,
            halving_interval_days=365,
            launch_date=_yesterday() - datetime.timedelta(days=800),
        )
    )
    await db_session.commit()

    await _add_report(db_session, "half-node", rebate=10.0)
    await _run_epoch(db_session)

    epoch = await _get_epoch(db_session)
    assert epoch.daily_emission == pytest.approx(25.0, rel=1e-6)  # 100 / 2**2
    ledger = await _get_ledger(db_session, "half-node")
    assert ledger.base_reward == pytest.approx(25.0, rel=1e-3)


async def test_rebate_backfill_from_volume(db_session: AsyncSession, monkeypatch):
    """Missing estimated_rebate_usdt is recomputed from volume * 0.0005 * rate."""
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    node = models.HubNode(node_uuid="backfill-node", name="Backfill", secret_hash="h")
    db_session.add(node)
    db_session.add(_make_config(rebate_rates={"weex_futures": 0.10}))
    await db_session.commit()

    report = await _add_report(db_session, "backfill-node", rebate=None, volume=1000.0)

    await _run_epoch(db_session)

    await db_session.refresh(report)
    assert report.estimated_rebate_usdt == pytest.approx(0.05, rel=1e-6)
    epoch = await _get_epoch(db_session)
    assert epoch.total_rebate_pool == pytest.approx(0.05, rel=1e-6)
    ledger = await _get_ledger(db_session, "backfill-node")
    assert ledger.base_reward == pytest.approx(100.0, rel=1e-3)


async def test_estimate_rebate_fallback_chain():
    """Rebate-rate lookup: exact exchange_market key, then exchange, then 0.60."""
    config = models.MiningConfig(
        is_mining_enabled=True,
        eligible_exchanges=["weex"],
        daily_emission_base=100.0,
        rebate_rates={"weex_futures": 0.10, "bybit": 0.05},
    )
    exact = SimpleNamespace(
        trade_volume_usdt=1000.0, exchange_id="weex", market_type="futures"
    )
    exchange_fallback = SimpleNamespace(
        trade_volume_usdt=1000.0, exchange_id="bybit", market_type="spot"
    )
    default = SimpleNamespace(
        trade_volume_usdt=1000.0, exchange_id="binance", market_type="spot"
    )
    zero = SimpleNamespace(
        trade_volume_usdt=0.0, exchange_id="weex", market_type="futures"
    )

    assert _estimate_rebate(exact, config) == pytest.approx(0.05, rel=1e-6)
    assert _estimate_rebate(exchange_fallback, config) == pytest.approx(0.025, rel=1e-6)
    assert _estimate_rebate(default, config) == pytest.approx(0.30, rel=1e-6)
    assert _estimate_rebate(zero, config) == 0.0


async def test_welcome_bonus_halving_stages(db_session: AsyncSession):
    """Welcome bonus shrinks as the pool passes 50M/75M/87.5M thresholds."""
    cases = [
        (60_000_000.0, 500.0),
        (80_000_000.0, 250.0),
        (90_000_000.0, 125.0),
    ]
    for pool_used, expected in cases:
        node = models.HubNode(node_uuid="tier-node", name="Tier", secret_hash="h")
        db_session.add(node)
        db_session.add(_make_config())
        # Push welcome_pool_used into the desired tier via a prior ledger entry.
        db_session.add(
            models.MiningLedger(
                node_uuid="seed-node",
                epoch_date=_yesterday() - datetime.timedelta(days=30),
                base_reward=0.0,
                referral_bonus=0.0,
                welcome_bonus=pool_used,
                boost_multiplier=1.0,
                total_reward=pool_used,
                total_rebate_usdt=0.0,
                verified_trades_count=0,
            )
        )
        await db_session.commit()

        await _add_report(db_session, "tier-node", rebate=10.0)
        await _run_epoch(db_session)

        ledger = await _get_ledger(db_session, "tier-node")
        assert ledger.welcome_bonus == pytest.approx(expected, rel=1e-6)
        await db_session.execute(models.MiningLedger.__table__.delete())
        await db_session.execute(models.MiningEpoch.__table__.delete())
        await db_session.execute(models.HubTelemetryReport.__table__.delete())
        await db_session.execute(models.HubNode.__table__.delete())
        await db_session.execute(models.MiningConfig.__table__.delete())
        await db_session.commit()


async def test_multi_node_epoch_dilution(db_session: AsyncSession, monkeypatch):
    """Two mining nodes split the pool proportional to their rebates."""
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    node_a = models.HubNode(node_uuid="dilute-a", name="A", secret_hash="h")
    node_b = models.HubNode(node_uuid="dilute-b", name="B", secret_hash="h")
    db_session.add_all([node_a, node_b])
    db_session.add(_make_config())
    await db_session.commit()

    await _add_report(db_session, "dilute-a", rebate=10.0)
    await _add_report(db_session, "dilute-b", rebate=20.0)
    await _run_epoch(db_session)

    # total_pts = 30, token_per_pt = 100/30.
    ledger_a = await _get_ledger(db_session, "dilute-a")
    ledger_b = await _get_ledger(db_session, "dilute-b")
    assert ledger_a.base_reward == pytest.approx(33.3333, rel=1e-3)
    assert ledger_b.base_reward == pytest.approx(66.6667, rel=1e-3)


async def test_welcome_threshold_from_prior_history(db_session: AsyncSession):
    """Cumulative rebate from previous epochs counts toward the $5 threshold."""
    node = models.HubNode(node_uuid="cum-node", name="Cum", secret_hash="h")
    db_session.add(node)
    db_session.add(_make_config())
    # Prior epoch already earned 4.5 USDT rebate.
    db_session.add(
        models.MiningLedger(
            node_uuid="cum-node",
            epoch_date=_yesterday() - datetime.timedelta(days=30),
            base_reward=0.0,
            referral_bonus=0.0,
            welcome_bonus=0.0,
            boost_multiplier=1.0,
            total_reward=0.0,
            total_rebate_usdt=4.5,
            verified_trades_count=1,
        )
    )
    await db_session.commit()

    # 4.5 + 1.0 = 5.5 >= threshold => welcome bonus granted this epoch.
    await _add_report(db_session, "cum-node", rebate=1.0)
    await _run_epoch(db_session)

    ledger = await _get_ledger(db_session, "cum-node")
    assert ledger.welcome_bonus == pytest.approx(1000.0, rel=1e-6)


async def test_operator_root_falls_back_to_admin_wallet(
    db_session: AsyncSession, monkeypatch
):
    """No is_operator flag => commission routes to the first admin's wallet node."""
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    admin = models.User(
        username="op-fallback-admin",
        email="op-fallback-admin@example.com",
        hashed_password="hash",
        is_active=True,
        role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    db_session.add(
        models.AppConfig(
            user_id=admin.id,
            risk_management={},
            notifications={},
            data_sources={},
            exchange_settings={"weex": {"mining_node_uuid": "admin-wallet-node"}},
        )
    )
    admin_wallet = models.HubNode(
        node_uuid="admin-wallet-node", name="AdminWallet", secret_hash="h"
    )
    miner = models.HubNode(node_uuid="fb-miner", name="Miner", secret_hash="h")
    db_session.add_all([admin_wallet, miner])
    db_session.add(_make_config())
    db_session.add(
        models.NodeMiningConfig(
            id=1, is_global_mining_enabled=True, user_reward_share_percent=75.0
        )
    )
    await db_session.commit()

    await _add_report(db_session, "fb-miner", rebate=10.0)
    await _run_epoch(db_session)

    miner_ledger = await _get_ledger(db_session, "fb-miner")
    admin_ledger = await _get_ledger(db_session, "admin-wallet-node")
    assert miner_ledger.base_reward == pytest.approx(75.0, rel=1e-3)
    assert admin_ledger.base_reward == pytest.approx(25.0, rel=1e-3)


async def test_referrer_welcome_clamped_at_pool_edge(
    db_session: AsyncSession, monkeypatch
):
    """Referrer matching welcome bonus is clamped by the remaining pool."""
    monkeypatch.setenv("WELCOME_BONUS_MAX_POOL", "1500.0")
    referrer = models.HubNode(node_uuid="clamp-ref", name="Referrer", secret_hash="h")
    child = models.HubNode(
        node_uuid="clamp-child",
        name="Child",
        secret_hash="h",
        referrer_node_uuid="clamp-ref",
    )
    db_session.add_all([referrer, child])
    db_session.add(_make_config())
    # Pool already at 100: child grant = min(1000, 1400) = 1000, referrer gets
    # min(1000, remaining 400) = 400.
    db_session.add(
        models.MiningLedger(
            node_uuid="seed-pool",
            epoch_date=_yesterday() - datetime.timedelta(days=30),
            base_reward=0.0,
            referral_bonus=0.0,
            welcome_bonus=100.0,
            boost_multiplier=1.0,
            total_reward=100.0,
            total_rebate_usdt=0.0,
            verified_trades_count=0,
        )
    )
    await db_session.commit()

    await _add_report(db_session, "clamp-child", rebate=10.0)
    await _run_epoch(db_session)

    child_ledger = await _get_ledger(db_session, "clamp-child")
    ref_ledger = await _get_ledger(db_session, "clamp-ref")
    assert child_ledger.welcome_bonus == pytest.approx(1000.0, rel=1e-6)
    assert ref_ledger.welcome_bonus == pytest.approx(400.0, rel=1e-6)
