from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch
import datetime
import json
import hmac
import hashlib
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from api import models
from api.depthsight_api import app
from api.hub_router import (
    router as hub_router,
    _get_exchange_multiplier,
    _resolve_report_multiplier,
    estimate_live_epoch_reward,
)
from tasks import _async_process_mining_epoch


@pytest.fixture(autouse=True)
def ensure_hub_router_registered():
    has_hub = any(
        getattr(route, "path", "").startswith("/api/v1/hub") for route in app.routes
    )
    if not has_hub:
        app.include_router(hub_router)


def _yesterday_date():
    return datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(
        days=1
    )


def _yesterday_noon():
    y = _yesterday_date()
    return datetime.datetime.combine(
        y, datetime.time(12, 0), tzinfo=datetime.timezone.utc
    )


def test_get_exchange_multiplier_matching():
    """Verify multiplier resolution rules: exact match, base/prefix match, case insensitivity, defaults, and bounds."""
    cfg = models.MiningConfig(
        exchange_multipliers={
            "bitget": 2.0,
            "bitget_futures": 2.5,
            "bybit": 1.0,
            "weex": 1.2,
            "low_bound": -5.0,
            "invalid_val": "not_a_number",  # type: ignore
        }
    )

    # 1. Exact match
    assert _get_exchange_multiplier(cfg, "bitget_futures") == 2.5
    assert _get_exchange_multiplier(cfg, "bybit") == 1.0

    # 2. Base/prefix match (fallback to prefix before underscore)
    assert _get_exchange_multiplier(cfg, "bitget_spot") == 2.0
    assert _get_exchange_multiplier(cfg, "bitget_swap") == 2.0

    # 3. Case insensitivity and whitespace trimming
    assert _get_exchange_multiplier(cfg, "  BITGET_FUTURES  ") == 2.5
    assert _get_exchange_multiplier(cfg, "Bitget_Spot") == 2.0

    # 4. Default 1.0 for unmatched exchanges
    assert _get_exchange_multiplier(cfg, "binance_futures") == 1.0
    assert _get_exchange_multiplier(cfg, "unknown_exchange") == 1.0
    assert _get_exchange_multiplier(cfg, None) == 1.0
    assert _get_exchange_multiplier(None, "bitget") == 1.0

    # 5. Safe bounds: negative/zero clamped to 0.1, invalid string fallback to 1.0
    assert _get_exchange_multiplier(cfg, "low_bound") == 0.1
    assert _get_exchange_multiplier(cfg, "invalid_val") == 1.0


@pytest.mark.asyncio
async def test_epoch_reward_multiplier_weights_emission_without_inflation(
    db_session, monkeypatch
):
    """
    Verify that multipliers weight points in the daily pool:
    - Node A (Bybit 1.0x, $10 rebate) gets 10 points.
    - Node B (Bitget 2.0x, $10 rebate) gets 20 points.
    - Total points = 30. Bitget node gets 2/3 of tokens, Bybit gets 1/3.
    - Total distributed matches daily emission (zero inflation).
    - Real USD rebates remain untouched ($10 each).
    """
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    yesterday = _yesterday_date()

    node_bybit = models.HubNode(
        node_uuid="node-bybit-1", name="Bybit Miner", secret_hash="hash"
    )
    node_bitget = models.HubNode(
        node_uuid="node-bitget-2", name="Bitget Miner", secret_hash="hash"
    )

    emission = 300.0
    cfg = models.MiningConfig(
        id=1,
        is_mining_enabled=True,
        eligible_exchanges=["bybit_futures", "bitget_futures"],
        daily_emission_base=emission,
        launch_date=yesterday - datetime.timedelta(days=1),
        referral_mining_boost=0.0,
        exchange_multipliers={
            "bybit": 1.0,
            "bybit_futures": 1.0,
            "bitget": 2.0,
            "bitget_futures": 2.0,
        },
    )
    db_session.add_all([node_bybit, node_bitget, cfg])

    rep_bybit = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=50000.0,
        exit_price=50100.0,
        trade_mode="LIVE",
        node_uuid="node-bybit-1",
        estimated_rebate_usdt=10.0,
        trade_volume_usdt=20000.0,
        is_mining_eligible=True,
        verification_status="VERIFIED",
        created_at=_yesterday_noon(),
        exchange_id="bybit_futures",
        market_type="futures",
        mining_multiplier=1.0,
        broker_trade_id="trade-bybit-101",
    )

    rep_bitget = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=50000.0,
        exit_price=50100.0,
        trade_mode="LIVE",
        node_uuid="node-bitget-2",
        estimated_rebate_usdt=10.0,
        trade_volume_usdt=20000.0,
        is_mining_eligible=True,
        verification_status="VERIFIED",
        created_at=_yesterday_noon(),
        exchange_id="bitget_futures",
        market_type="futures",
        mining_multiplier=2.0,
        broker_trade_id="trade-bitget-201",
    )

    db_session.add_all([rep_bybit, rep_bitget])
    await db_session.commit()

    @asynccontextmanager
    async def mock_isolated_session():
        yield db_session

    # Process the epoch using the test DB session
    with patch("api.database.get_isolated_worker_session", mock_isolated_session):
        await _async_process_mining_epoch(force_yesterday_date=yesterday)
    db_session.expire_all()

    # 1. Verify MiningEpoch total distribution
    epoch_res = await db_session.execute(
        select(models.MiningEpoch).where(models.MiningEpoch.epoch_date == yesterday)
    )
    epoch = epoch_res.scalars().first()
    assert epoch is not None
    assert epoch.status == "finalized"
    assert epoch.total_rebate_pool == pytest.approx(20.0, abs=1e-3)
    assert epoch.total_distributed == pytest.approx(emission, abs=1e-3)
    assert epoch.participating_nodes == 2

    # 2. Verify Ledgers
    ledger_bybit_res = await db_session.execute(
        select(models.MiningLedger).where(
            models.MiningLedger.node_uuid == "node-bybit-1",
            models.MiningLedger.epoch_date == yesterday,
        )
    )
    ledger_bybit = ledger_bybit_res.scalars().first()

    ledger_bitget_res = await db_session.execute(
        select(models.MiningLedger).where(
            models.MiningLedger.node_uuid == "node-bitget-2",
            models.MiningLedger.epoch_date == yesterday,
        )
    )
    ledger_bitget = ledger_bitget_res.scalars().first()

    assert ledger_bybit is not None
    assert ledger_bitget is not None

    # Node A gets 10 / 30 = 1/3 of 300 = 100
    assert ledger_bybit.base_reward == pytest.approx(100.0, abs=1e-3)
    # Node B gets 20 / 30 = 2/3 of 300 = 200 (exactly 2x Node A)
    assert ledger_bitget.base_reward == pytest.approx(200.0, abs=1e-3)

    # Multiplier did not alter USD rebates
    assert ledger_bybit.total_rebate_usdt == pytest.approx(10.0, abs=1e-3)
    assert ledger_bitget.total_rebate_usdt == pytest.approx(10.0, abs=1e-3)

    # 3. Verify report attribution
    await db_session.refresh(rep_bybit)
    await db_session.refresh(rep_bitget)
    assert rep_bybit.reward_tokens == pytest.approx(100.0, abs=1e-3)
    assert rep_bitget.reward_tokens == pytest.approx(200.0, abs=1e-3)


@pytest.mark.asyncio
async def test_estimate_live_epoch_reward_with_multipliers(db_session):
    """Verify that live epoch reward estimation weights points by exchange multiplier."""
    cfg = models.MiningConfig(
        id=1,
        is_mining_enabled=True,
        daily_emission_base=600.0,
        referral_mining_boost=0.0,
        exchange_multipliers={
            "bybit": 1.0,
            "bitget": 2.0,
        },
    )
    node1 = models.HubNode(node_uuid="live-bybit", name="Live Bybit", secret_hash="h")
    node2 = models.HubNode(node_uuid="live-bitget", name="Live Bitget", secret_hash="h")
    db_session.add_all([cfg, node1, node2])
    await db_session.commit()

    rep_bybit = models.HubTelemetryReport(
        symbol="BTCUSDT",
        node_uuid="live-bybit",
        estimated_rebate_usdt=5.0,
        exchange_id="bybit_futures",
        mining_multiplier=1.0,
        is_mining_eligible=True,
    )
    rep_bitget = models.HubTelemetryReport(
        symbol="BTCUSDT",
        node_uuid="live-bitget",
        estimated_rebate_usdt=5.0,
        exchange_id="bitget_futures",
        mining_multiplier=2.0,
        is_mining_eligible=True,
    )

    reports = [rep_bybit, rep_bitget]

    reward_bybit = await estimate_live_epoch_reward(
        db_session, cfg, 600.0, "live-bybit", reports
    )
    reward_bitget = await estimate_live_epoch_reward(
        db_session, cfg, 600.0, "live-bitget", reports
    )

    # Total points = (5 * 1.0) + (5 * 2.0) = 15 points
    # Token value = 600 / 15 = 40 tokens/point
    # Gross: Bybit = 200, Bitget = 400
    # Net (75% default user share): Bybit = 150, Bitget = 300
    assert reward_bybit == pytest.approx(150.0, abs=1e-3)
    assert reward_bitget == pytest.approx(300.0, abs=1e-3)
    assert reward_bitget == pytest.approx(2.0 * reward_bybit, abs=1e-3)


@pytest.mark.asyncio
async def test_mining_config_multipliers_api(
    test_client: AsyncClient, db_session, monkeypatch
):
    """Verify that /mining/config exposes and accepts exchange_multipliers with admin auth."""
    monkeypatch.setenv("HUB_ADMIN_API_KEY", "test-admin-secret-xyz")
    monkeypatch.setattr("api.hub_router.HUB_ADMIN_API_KEY", "test-admin-secret-xyz")

    cfg = models.MiningConfig(
        id=1,
        is_mining_enabled=True,
        eligible_exchanges=["bitget_futures", "bybit_futures"],
        exchange_multipliers={"bitget": 2.0, "bybit": 1.0},
    )
    db_session.add(cfg)
    await db_session.commit()

    # 1. GET /mining/config returns exchangeMultipliers
    res = await test_client.get("/api/v1/hub/mining/config")
    assert res.status_code == 200
    body = res.json()
    assert "exchangeMultipliers" in body
    assert body["exchangeMultipliers"].get("bitget") == 2.0
    assert body["exchangeMultipliers"].get("bybit") == 1.0

    # 2. POST /mining/config updates multipliers
    update_payload = {
        "exchangeMultipliers": {
            "bitget": 3.0,
            "bitget_futures": 3.0,
            "weex": 1.5,
        }
    }
    update_res = await test_client.post(
        "/api/v1/hub/mining/config",
        json=update_payload,
        headers={"Authorization": "Bearer test-admin-secret-xyz"},
    )
    assert update_res.status_code == 200

    # Verify updated in DB
    db_session.expire_all()
    cfg_res = await db_session.execute(select(models.MiningConfig).limit(1))
    updated_cfg = cfg_res.scalars().first()
    assert updated_cfg.exchange_multipliers.get("bitget") == 3.0
    assert updated_cfg.exchange_multipliers.get("weex") == 1.5


@pytest.mark.asyncio
async def test_telemetry_report_assigns_multiplier(
    test_client: AsyncClient, db_session
):
    """Verify that telemetry report endpoint automatically stamps mining_multiplier on report."""
    node_uuid = "node-mult-test"
    node_secret = "secret-mult-test"
    secret_hash = hashlib.sha256(node_secret.encode()).hexdigest()

    node = models.HubNode(node_uuid=node_uuid, name="MultNode", secret_hash=secret_hash)
    cfg = models.MiningConfig(
        id=1,
        is_mining_enabled=True,
        eligible_exchanges=["bitget", "bybit"],
        exchange_multipliers={"bitget": 2.0, "bybit": 1.0},
    )
    db_session.add_all([node, cfg])
    await db_session.commit()

    payload_bitget = {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "entryPrice": 60000.0,
        "exitPrice": 60500.0,
        "pnlPercent": 1.0,
        "tradeDurationSec": 300,
        "tradeMode": "LIVE",
        "strategyBlocks": [],
        "marketContext": {
            "session": "london",
            "natr": 0.05,
            "adx": 25.0,
            "volumeRatio": 1.2,
        },
        "exchangeId": "bitget",
        "marketType": "futures",
        "brokerTradeId": "bitget-trade-999",
        "tradeVolumeUsdt": 1000.0,
    }

    body_bytes = json.dumps(payload_bitget, sort_keys=True).encode("utf-8")
    sig = hmac.new(node_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    headers = {
        "X-Node-UUID": node_uuid,
        "X-Node-Secret": node_secret,
        "X-Node-Signature": sig,
        "Content-Type": "application/json",
    }

    resp = await test_client.post(
        "/api/v1/hub/telemetry/report",
        content=body_bytes,
        headers=headers,
    )
    assert resp.status_code == 201

    # Query the created report from DB
    rep_res = await db_session.execute(
        select(models.HubTelemetryReport).where(
            models.HubTelemetryReport.broker_trade_id == "bitget-trade-999"
        )
    )
    rep = rep_res.scalars().first()
    assert rep is not None
    assert rep.mining_multiplier == 2.0


def test_resolve_report_multiplier_prefers_live_config():
    """
    Live config wins over the stamped value so a newly enabled multiplier is
    reflected immediately; the stamped value is a fallback only for exchanges
    that have no entry in the current config.
    """
    cfg = models.MiningConfig(exchange_multipliers={"bitget": 2.0})

    stamped_1 = SimpleNamespace(exchange_id="bitget_futures", mining_multiplier=1.0)
    stamped_3 = SimpleNamespace(exchange_id="weex_futures", mining_multiplier=3.0)
    stamped_none = SimpleNamespace(exchange_id="weex_futures", mining_multiplier=None)
    no_exchange = SimpleNamespace(exchange_id=None, mining_multiplier=5.0)

    assert _resolve_report_multiplier(cfg, stamped_1) == 2.0
    assert _resolve_report_multiplier(cfg, stamped_3) == 3.0
    assert _resolve_report_multiplier(cfg, stamped_none) == 1.0
    assert _resolve_report_multiplier(cfg, no_exchange) == 5.0
    assert _resolve_report_multiplier(None, stamped_3) == 3.0


@pytest.mark.asyncio
async def test_estimate_live_reward_uses_live_config_over_stamped(db_session):
    """
    Regression for Today's Est. Reward: reports stamped with 1.0 before the
    multiplier was enabled (or saved via the local crud path that never stamps
    it) must be weighted by the LIVE config multiplier. The epoch settlement
    in tasks.py shares the same semantics via _resolve_report_mult.
    """
    cfg = models.MiningConfig(
        id=1,
        is_mining_enabled=True,
        daily_emission_base=600.0,
        referral_mining_boost=0.0,
        exchange_multipliers={"bybit": 1.0, "bitget": 2.0},
    )
    node = models.HubNode(node_uuid="live-stale", name="Live Stale", secret_hash="h")
    db_session.add_all([cfg, node])
    await db_session.commit()

    # Stamped 1.0 (submitted before the multiplier was enabled).
    rep_stale = models.HubTelemetryReport(
        symbol="BTCUSDT",
        direction="LONG",
        entry_price=60000.0,
        exit_price=60500.0,
        trade_mode="LIVE",
        node_uuid="live-stale",
        estimated_rebate_usdt=10.0,
        exchange_id="bitget_futures",
        mining_multiplier=1.0,
        is_mining_eligible=True,
    )
    # Stamped 3.0 with no config entry anymore -> stamped fallback must win.
    rep_legacy = models.HubTelemetryReport(
        symbol="ETHUSDT",
        direction="SHORT",
        entry_price=3000.0,
        exit_price=2980.0,
        trade_mode="LIVE",
        node_uuid="live-stale",
        estimated_rebate_usdt=10.0,
        exchange_id="weex_futures",
        mining_multiplier=3.0,
        is_mining_eligible=True,
    )
    db_session.add_all([rep_stale, rep_legacy])
    await db_session.commit()

    reward = await estimate_live_epoch_reward(
        db_session, cfg, 600.0, "live-stale", [rep_stale, rep_legacy]
    )

    # Points: bitget 10*2.0 (live config) + weex 10*3.0 (stamped) = 50 pts.
    # token/pt = 600/50 = 12 -> gross = 600, net (75% default share) = 450.
    # With the old stamped-priority logic it would be 360.
    assert reward == pytest.approx(450.0, abs=1e-3)
