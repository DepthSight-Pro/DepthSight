import json
from pathlib import Path
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from api import crud, models
from api.gamification import (
    calculate_level,
    grant_achievement,
    check_and_grant_mining_achievements,
    MINING_ACHIEVEMENTS,
)

pytestmark = pytest.mark.asyncio


async def test_all_37_mining_achievements_registered():
    """Verify that all 37 mining achievements are properly defined."""
    assert len(MINING_ACHIEVEMENTS) == 37
    # Verify specific requested adjustment: 100k referral earnings
    assert "mining_ref_earnings_100k" in MINING_ACHIEVEMENTS
    meta = MINING_ACHIEVEMENTS["mining_ref_earnings_100k"]
    assert meta["xp_reward"] == 3000
    assert meta["rarity"] == "LEGENDARY"


async def test_translations_coverage():
    """Verify that all 37 mining achievements exist in ru and en account.json."""
    root = Path(__file__).parent.parent
    ru_path = root / "frontend" / "src" / "locales" / "ru" / "account.json"
    en_path = root / "frontend" / "src" / "locales" / "en" / "account.json"

    with open(ru_path, "r", encoding="utf-8") as f:
        ru_data = json.load(f)
    with open(en_path, "r", encoding="utf-8") as f:
        en_data = json.load(f)

    for ach_id in MINING_ACHIEVEMENTS:
        assert ach_id in ru_data, f"Missing {ach_id} in ru account.json"
        assert "name" in ru_data[ach_id]
        assert "description" in ru_data[ach_id]

        assert ach_id in en_data, f"Missing {ach_id} in en account.json"
        assert "name" in en_data[ach_id]
        assert "description" in en_data[ach_id]


async def test_grant_mining_achievement_and_level_up(
    db_session: AsyncSession,
    test_user: models.User,
):
    """Tests granting a mining achievement awards XP and recalculates level."""
    initial_xp = test_user.xp or 0
    initial_level = test_user.level or 1

    # Grant 'mining_activated' (50 XP)
    ua = await grant_achievement(db_session, test_user.id, "mining_activated")
    assert ua is not None
    assert ua.achievement_id == "mining_activated"

    await db_session.refresh(test_user)
    assert test_user.xp == initial_xp + 50
    assert test_user.level == calculate_level(test_user.xp)

    # Test idempotency: granting again should not grant extra XP
    ua_second = await grant_achievement(db_session, test_user.id, "mining_activated")
    assert ua_second is None
    await db_session.refresh(test_user)
    assert test_user.xp == initial_xp + 50

    # Grant a high XP achievement to verify level increase ('mining_volume_10m' gives 5000 XP)
    await grant_achievement(db_session, test_user.id, "mining_volume_10m")
    await db_session.refresh(test_user)
    assert test_user.xp == initial_xp + 50 + 5000
    expected_level = calculate_level(test_user.xp)
    assert test_user.level == expected_level
    assert test_user.level > initial_level


async def test_check_and_grant_mining_achievements_retroactive(
    db_session: AsyncSession,
    test_user: models.User,
):
    """Tests retroactive evaluation of mining achievements based on config and ledger."""
    # 1. Update AppConfig with mining enabled and wallet configured
    node_uuid = "test-node-achievement-uuid"
    config = await crud.get_config_model(db_session, user_id=test_user.id)
    if not config:
        config = models.AppConfig(
            user_id=test_user.id,
            is_mining_enabled=True,
            risk_management={},
            notifications={},
            data_sources={},
            exchange_settings={
                "mining_node_uuid": node_uuid,
                "wallet_configured": True,
            },
        )
        db_session.add(config)
    else:
        config.is_mining_enabled = True
        config.exchange_settings = {
            "mining_node_uuid": node_uuid,
            "wallet_configured": True,
        }

    # 2. Setup HubNode
    node = models.HubNode(
        node_uuid=node_uuid,
        name="TestNode",
        secret_hash="fake_hash_1",
        wallet_address="0x1234567890123456789012345678901234567890",
        is_mining_server=True,
        bybit_uid="11111",
        okx_uid="22222",
    )
    db_session.add(node)

    # 3. Setup MiningLedger with rewards & streaks
    import datetime

    today = datetime.date.today()
    for i in range(7):
        epoch_date = today - datetime.timedelta(days=i + 1)
        ledger = models.MiningLedger(
            node_uuid=node_uuid,
            epoch_date=epoch_date,
            base_reward=200.0,
            welcome_bonus=1000.0 if i == 0 else 0.0,
            boost_multiplier=2.0 if i == 0 else 1.2,
            total_reward=240.0,
            verified_trades_count=5,
        )
        db_session.add(ledger)

    # 4. Setup a referred node with welcome bonus claimed
    ref_node = models.HubNode(
        node_uuid="ref-node-1",
        name="RefNode",
        secret_hash="fake_hash_2",
        referrer_node_uuid=node_uuid,
        has_welcome_bonus=True,
    )
    db_session.add(ref_node)

    # 5. Setup Telemetry report with high volume and positive PnL
    now = datetime.datetime.now(datetime.timezone.utc)
    tel_report = models.HubTelemetryReport(
        node_uuid=node_uuid,
        symbol="BTCUSDT",
        direction="BUY",
        entry_price=60000.0,
        exit_price=61000.0,
        trade_volume_usdt=15000.0,
        pnl_percent=1.66,
        trade_mode="live",
        created_at=now,
        verification_status="VERIFIED",
    )
    db_session.add(tel_report)

    await db_session.commit()

    # Run check
    await check_and_grant_mining_achievements(db_session, test_user.id)
    await db_session.commit()

    # Query user achievements
    res = await db_session.execute(
        select(models.UserAchievement.achievement_id).where(
            models.UserAchievement.user_id == test_user.id
        )
    )
    unlocked = {row[0] for row in res}

    # Verify unlocked achievements
    assert "mining_activated" in unlocked
    assert "mining_wallet_linked" in unlocked
    assert "mining_node_operator" in unlocked
    assert "mining_multi_exchange" in unlocked
    assert "mining_all_exchanges" in unlocked
    assert "mining_first_trade" in unlocked
    assert "welcome_bonus_claimed" in unlocked
    assert "mining_boost_active" in unlocked
    assert "mining_streak_7d" in unlocked
    assert "mining_first_referral" in unlocked
    assert "mining_depth_1k" in unlocked
    assert "mining_mentor_bonus" in unlocked
    assert "mining_diamond_staker" in unlocked
    assert "mining_volume_1k" in unlocked
    assert "mining_volume_10k" in unlocked
    assert "mining_daily_volume_10k" in unlocked
