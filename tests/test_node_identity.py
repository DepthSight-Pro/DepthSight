# tests/test_node_identity.py
"""Exchange-agnostic mining identity resolution (no hardcoded exchange list).

Covers bot_module.node_identity collectors plus the two consumers that must
agree (hub live estimate vs daily epoch): a bitget-only owner must resolve
in both, and an unknown future exchange must work with zero code changes.
"""

import datetime
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import select

from api import models
from bot_module.node_identity import (
    collect_mining_node_uuids,
    collect_wallet_addresses,
    find_identity_pair,
    iter_identity_sections,
    primary_mining_node_uuid,
    primary_wallet_address,
)
from tasks import _async_process_mining_epoch


# ---------------------------------------------------------------------------
# Pure collector unit tests (no DB).
# ---------------------------------------------------------------------------


def test_collectors_cover_all_exchange_sections():
    settings = {
        "bitget": {"mining_node_uuid": "uuid-bitget", "wallet_address": "0xBbBb"},
        "okx": {"mining_node_uuid": "uuid-okx", "wallet_address": "0xCcCc"},
        "bybit": {"mining_node_uuid": "uuid-bybit"},
        "binance": {"wallet_address": "0xDdDd"},
        "weex": {"mining_node_uuid": "uuid-weex", "wallet_address": "0xEeEe"},
    }
    uuids = collect_mining_node_uuids(settings)
    assert set(uuids) == {"uuid-bitget", "uuid-okx", "uuid-bybit", "uuid-weex"}
    wallets = collect_wallet_addresses(settings)
    assert {w.lower() for w in wallets} == {"0xbbbb", "0xcccc", "0xdddd", "0xeeee"}


def test_collectors_support_unknown_future_exchange_without_code_changes():
    settings = {
        "mexc": {"mining_node_uuid": "uuid-mexc", "wallet_address": "0xFfFf"},
    }
    assert collect_mining_node_uuids(settings) == ["uuid-mexc"]
    assert collect_wallet_addresses(settings) == ["0xFfFf"]
    assert primary_mining_node_uuid(settings) == "uuid-mexc"
    assert primary_wallet_address(settings) == "0xFfFf"
    uuid, secret = find_identity_pair(
        {"mexc": {"mining_node_uuid": "uuid-mexc", "mining_node_secret": "sec"}}
    )
    assert (uuid, secret) == ("uuid-mexc", "sec")


def test_collectors_top_level_fallback_and_empty():
    assert collect_mining_node_uuids(None) == []
    assert collect_wallet_addresses({}) == []
    assert primary_mining_node_uuid({}) is None
    assert primary_wallet_address(None) is None
    assert find_identity_pair({}) == (None, None)
    settings = {"mining_node_uuid": "uuid-top", "wallet_address": "0xAbAb"}
    assert primary_mining_node_uuid(settings) == "uuid-top"
    assert primary_wallet_address(settings) == "0xAbAb"


def test_collectors_legacy_weex_priority_and_normalization():
    settings = {
        "bitget": {"mining_node_uuid": "uuid-bitget", "wallet_address": " 0xBbBb "},
        "weex": {"mining_node_uuid": "uuid-weex", "wallet_address": "0xEeEe"},
    }
    # weex first for backward compatibility with the historical behavior.
    assert primary_mining_node_uuid(settings) == "uuid-weex"
    assert primary_wallet_address(settings) == "0xEeEe"
    # Wallet matching is case-insensitive, duplicates collapse.
    dup = {"bitget": {"wallet_address": "0xAAAA"}, "okx": {"wallet_address": "0xaaaa"}}
    assert collect_wallet_addresses(dup) == ["0xAAAA"]


def test_find_identity_pair_never_mixes_sections():
    settings = {
        "bybit": {"mining_node_uuid": "uuid-bybit"},
        "okx": {"mining_node_uuid": "uuid-okx", "mining_node_secret": "sec-okx"},
    }
    uuid, secret = find_identity_pair(settings)
    # First uuid in priority order wins; its secret comes from the SAME
    # section (or top level) — never borrowed from another section (that mix
    # fails hub auth). A missing secret surfaces as None so callers fall back
    # cleanly instead of authenticating as the wrong node.
    assert uuid == "uuid-bybit"
    assert secret is None
    assert (uuid, secret) != ("uuid-bybit", "sec-okx")


def test_iter_identity_sections_deterministic_order():
    settings = {"zeta": {"a": 1}, "alpha": {"b": 2}, "top_scalar": "x"}
    names = [name for name, _ in iter_identity_sections(settings)]
    assert names[0] == "alpha"
    assert names[-1] == ""  # top-level pseudo-section last


# ---------------------------------------------------------------------------
# Hub live-estimate fallback via a bitget-only owner (the production case:
# explicit node link missing, owner resolvable only through bitget settings).
# ---------------------------------------------------------------------------


def _make_user(db_session, username, email, referral_code=None, referred_by=None):
    user = models.User(
        username=username,
        email=email,
        hashed_password="somehashedpassword",
        is_active=True,
        role="user",
        referral_code=referral_code,
        referred_by_user_id=referred_by,
    )
    db_session.add(user)
    return user


def _make_config(db_session, user_id, exchange_settings):
    cfg = models.AppConfig(
        user_id=user_id,
        risk_management={},
        notifications={},
        data_sources={},
        exchange_settings=exchange_settings,
        is_mining_enabled=True,
    )
    db_session.add(cfg)
    return cfg


@pytest.mark.asyncio
async def test_hub_referrer_fallback_through_bitget_settings(db_session):
    from api.hub_router import _resolve_mining_referrer

    inviter = _make_user(
        db_session, "ni_inviter", "ni_inviter@example.com", referral_code="REF-NI-INV"
    )
    referred = _make_user(
        db_session, "ni_referred", "ni_referred@example.com", referral_code="REF-NI-REF"
    )
    await db_session.commit()
    await db_session.refresh(inviter)
    await db_session.refresh(referred)
    referred.referred_by_user_id = inviter.id

    db_session.add(
        models.HubNode(
            node_uuid="ni-inviter-node",
            name="NiInviter",
            secret_hash="secret",
            node_referral_code="REF-NI-INV",
            total_mined=0.0,
        )
    )
    # Volume node: NO explicit referrer link (the production gap).
    db_session.add(
        models.HubNode(
            node_uuid="ni-vol-node",
            name="NiVol",
            secret_hash="secret",
            bitget_uid="uid_ni",
            wallet_address="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            total_mined=0.0,
        )
    )
    # Owner resolvable ONLY through the bitget section (weex absent).
    _make_config(
        db_session,
        referred.id,
        {
            "bitget": {
                "mining_node_uuid": "ni-vol-node",
                "wallet_address": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            }
        },
    )
    _make_config(
        db_session,
        inviter.id,
        {
            "bitget": {
                "mining_node_uuid": "ni-inviter-node",
                "wallet_address": "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            }
        },
    )
    await db_session.commit()

    assert await _resolve_mining_referrer(db_session, "ni-vol-node") == (
        "ni-inviter-node"
    )


# ---------------------------------------------------------------------------
# Daily epoch with bitget-only settings: referral_points must accrue.
# ---------------------------------------------------------------------------


def _yesterday_date():
    return datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(
        days=1
    )


def _yesterday_noon():
    y = _yesterday_date()
    return datetime.datetime.combine(
        y, datetime.time(12, 0), tzinfo=datetime.timezone.utc
    )


@pytest.mark.asyncio
async def test_epoch_referral_bonus_with_bitget_only_settings(db_session, monkeypatch):
    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    yesterday = _yesterday_date()

    inviter = _make_user(
        db_session, "ep_inviter", "ep_inviter@example.com", referral_code="REF-EP-INV"
    )
    referred = _make_user(
        db_session, "ep_referred", "ep_referred@example.com", referral_code="REF-EP-REF"
    )
    await db_session.commit()
    await db_session.refresh(inviter)
    await db_session.refresh(referred)
    referred.referred_by_user_id = inviter.id

    db_session.add(
        models.HubNode(
            node_uuid="ep-inviter-node",
            name="EpInviter",
            secret_hash="secret",
            node_referral_code="REF-EP-INV",
            total_mined=0.0,
        )
    )
    db_session.add(
        models.HubNode(
            node_uuid="ep-vol-node",
            name="EpVol",
            secret_hash="secret",
            bitget_uid="uid_ep",
            wallet_address="0xcccccccccccccccccccccccccccccccccccccccc",
            total_mined=0.0,
        )
    )
    _make_config(
        db_session,
        referred.id,
        {
            "bitget": {
                "mining_node_uuid": "ep-vol-node",
                "wallet_address": "0xcccccccccccccccccccccccccccccccccccccccc",
            }
        },
    )
    _make_config(
        db_session,
        inviter.id,
        {
            "bitget": {
                "mining_node_uuid": "ep-inviter-node",
                "wallet_address": "0xdddddddddddddddddddddddddddddddddddddddd",
            }
        },
    )

    cfg = models.MiningConfig(
        id=1,
        is_mining_enabled=True,
        eligible_exchanges=["bitget_futures"],
        daily_emission_base=300.0,
        launch_date=yesterday - datetime.timedelta(days=1),
        referral_mining_boost=0.10,
        exchange_multipliers={"bitget": 1.0, "bitget_futures": 1.0},
    )
    db_session.add(cfg)
    db_session.add(
        models.HubTelemetryReport(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=50000.0,
            exit_price=50100.0,
            trade_mode="LIVE",
            node_uuid="ep-vol-node",
            estimated_rebate_usdt=10.0,
            trade_volume_usdt=20000.0,
            is_mining_eligible=True,
            verification_status="VERIFIED",
            created_at=_yesterday_noon(),
            exchange_id="bitget_futures",
            market_type="futures",
            mining_multiplier=1.0,
            broker_trade_id="trade-ep-301",
        )
    )
    await db_session.commit()

    @asynccontextmanager
    async def mock_isolated_session():
        yield db_session

    with patch("api.database.get_isolated_worker_session", mock_isolated_session):
        await _async_process_mining_epoch(force_yesterday_date=yesterday)
    db_session.expire_all()

    ledger_res = await db_session.execute(
        select(models.MiningLedger).where(
            models.MiningLedger.node_uuid == "ep-inviter-node",
            models.MiningLedger.epoch_date == yesterday,
        )
    )
    inviter_ledger = ledger_res.scalars().first()
    assert inviter_ledger is not None
    # 10 base pts + 10*0.10 referral pts = 11 pts; 300/11 per point.
    assert inviter_ledger.referral_bonus == pytest.approx(300.0 / 11.0, abs=1e-3)
    assert inviter_ledger.base_reward == pytest.approx(0.0, abs=1e-3)


@pytest.mark.asyncio
async def test_estimate_and_epoch_agree_on_bitget_referral(db_session, monkeypatch):
    """Parity lock: hub live estimate and daily epoch attribute the same
    bitget-settings referral to the same inviter node with equal bonus."""
    from api.hub_router import _get_active_mining_config, estimate_live_epoch_reward

    monkeypatch.setenv("MIN_WELCOME_REBATE_USDT", "999999999.0")
    yesterday = _yesterday_date()

    inviter = _make_user(
        db_session, "pa_inviter", "pa_inviter@example.com", referral_code="REF-PA-INV"
    )
    referred = _make_user(
        db_session, "pa_referred", "pa_referred@example.com", referral_code="REF-PA-REF"
    )
    await db_session.commit()
    await db_session.refresh(inviter)
    await db_session.refresh(referred)
    referred.referred_by_user_id = inviter.id

    db_session.add(
        models.HubNode(
            node_uuid="pa-inviter-node",
            name="PaInviter",
            secret_hash="secret",
            node_referral_code="REF-PA-INV",
            total_mined=0.0,
        )
    )
    db_session.add(
        models.HubNode(
            node_uuid="pa-vol-node",
            name="PaVol",
            secret_hash="secret",
            bitget_uid="uid_pa",
            wallet_address="0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            total_mined=0.0,
        )
    )
    _make_config(
        db_session,
        referred.id,
        {
            "bitget": {
                "mining_node_uuid": "pa-vol-node",
                "wallet_address": "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            }
        },
    )
    _make_config(
        db_session,
        inviter.id,
        {
            "bitget": {
                "mining_node_uuid": "pa-inviter-node",
                "wallet_address": "0xffffffffffffffffffffffffffffffffffffffff",
            }
        },
    )
    db_session.add(
        models.MiningConfig(
            id=1,
            is_mining_enabled=True,
            eligible_exchanges=["bitget_futures"],
            daily_emission_base=300.0,
            launch_date=yesterday - datetime.timedelta(days=1),
            referral_mining_boost=0.10,
            exchange_multipliers={"bitget": 1.0, "bitget_futures": 1.0},
        )
    )
    db_session.add(
        models.HubTelemetryReport(
            symbol="BTCUSDT",
            direction="LONG",
            entry_price=50000.0,
            exit_price=50100.0,
            trade_mode="LIVE",
            node_uuid="pa-vol-node",
            estimated_rebate_usdt=10.0,
            trade_volume_usdt=20000.0,
            is_mining_eligible=True,
            verification_status="VERIFIED",
            created_at=_yesterday_noon(),
            exchange_id="bitget_futures",
            market_type="futures",
            mining_multiplier=1.0,
            broker_trade_id="trade-pa-401",
        )
    )
    await db_session.commit()

    # Live estimate first (inviter has no own volume: total == referral bonus).
    reports_res = await db_session.execute(select(models.HubTelemetryReport))
    reports = reports_res.scalars().all()
    mining_cfg = await _get_active_mining_config(db_session)
    estimate_total = await estimate_live_epoch_reward(
        db_session, mining_cfg, 300.0, "pa-inviter-node", reports
    )
    assert estimate_total == pytest.approx(300.0 / 11.0, abs=1e-3)

    # Then the epoch on the same fixture.
    @asynccontextmanager
    async def mock_isolated_session():
        yield db_session

    with patch("api.database.get_isolated_worker_session", mock_isolated_session):
        await _async_process_mining_epoch(force_yesterday_date=yesterday)
    db_session.expire_all()

    ledger_res = await db_session.execute(
        select(models.MiningLedger).where(
            models.MiningLedger.node_uuid == "pa-inviter-node",
            models.MiningLedger.epoch_date == yesterday,
        )
    )
    inviter_ledger = ledger_res.scalars().first()
    assert inviter_ledger is not None
    assert inviter_ledger.referral_bonus == pytest.approx(300.0 / 11.0, abs=1e-3)
    # Same reports, same math: estimate and epoch agree exactly.
    assert estimate_total == pytest.approx(
        float(inviter_ledger.referral_bonus), abs=1e-3
    )
