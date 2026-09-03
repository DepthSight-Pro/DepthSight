import datetime as dt
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from . import models, crud
from .push_sender import send_push_notification

logger = logging.getLogger(__name__)


def calculate_level(xp: int) -> int:
    """Calculates user level based on XP."""
    return int((xp / 100) ** (1 / 1.5)) + 1


MINING_ACHIEVEMENTS = {
    # Onboarding & Web3
    "mining_activated": {
        "name": "Genesis",
        "description": "Activate Trade Mining and accept telemetry sharing",
        "icon": "Pickaxe",
        "xp_reward": 50,
        "rarity": "COMMON",
    },
    "mining_wallet_linked": {
        "name": "Web3 Citizen",
        "description": "Link and verify an EVM wallet for mining",
        "icon": "Wallet",
        "xp_reward": 50,
        "rarity": "COMMON",
    },
    "mining_first_trade": {
        "name": "First Spark",
        "description": "Execute first trade successfully verified in the mining pool",
        "icon": "Sparkles",
        "xp_reward": 100,
        "rarity": "COMMON",
    },
    "welcome_bonus_claimed": {
        "name": "Golden Ticket",
        "description": "Generate $1.0 rebate and claim Welcome Bonus (1,000 $DEPTH)",
        "icon": "Ticket",
        "xp_reward": 250,
        "rarity": "RARE",
    },
    # Volume Milestones
    "mining_volume_1k": {
        "name": "Tunnel Miner",
        "description": "Reach $1,000 in cumulative trading volume",
        "icon": "CircleDollarSign",
        "xp_reward": 50,
        "rarity": "COMMON",
    },
    "mining_volume_10k": {
        "name": "Mining Foreman",
        "description": "Reach $10,000 in cumulative trading volume",
        "icon": "Coins",
        "xp_reward": 150,
        "rarity": "COMMON",
    },
    "mining_volume_100k": {
        "name": "Quarry Titan",
        "description": "Reach $100,000 in cumulative trading volume",
        "icon": "TrendingUp",
        "xp_reward": 500,
        "rarity": "RARE",
    },
    "mining_volume_1m": {
        "name": "Crypto Whale",
        "description": "Reach $1,000,000 in cumulative trading volume",
        "icon": "Fish",
        "xp_reward": 1500,
        "rarity": "EPIC",
    },
    "mining_volume_10m": {
        "name": "Market Maker",
        "description": "Reach $10,000,000 in cumulative trading volume",
        "icon": "Crown",
        "xp_reward": 5000,
        "rarity": "LEGENDARY",
    },
    # Daily Highs
    "mining_daily_volume_10k": {
        "name": "Stakhanovite",
        "description": "Generate $10,000 volume in a single 24-hour epoch",
        "icon": "Activity",
        "xp_reward": 200,
        "rarity": "RARE",
    },
    "mining_daily_volume_100k": {
        "name": "Market Tempest",
        "description": "Generate $100,000 volume in a single 24-hour epoch",
        "icon": "CloudLightning",
        "xp_reward": 750,
        "rarity": "EPIC",
    },
    "mining_daily_top_miner": {
        "name": "King of the Hill",
        "description": "Rank #1 in volume across all nodes in a daily epoch",
        "icon": "Trophy",
        "xp_reward": 2000,
        "rarity": "LEGENDARY",
    },
    "mining_daily_top5_miner": {
        "name": "Major League",
        "description": "Finish in the top 5 daily volume miners",
        "icon": "Medal",
        "xp_reward": 500,
        "rarity": "EPIC",
    },
    # Referrals & Social
    "mining_first_referral": {
        "name": "Network Partner",
        "description": "Invite your first user who activates mining",
        "icon": "UserPlus",
        "xp_reward": 100,
        "rarity": "COMMON",
    },
    "mining_5_referrals": {
        "name": "Squad Leader",
        "description": "Invite 5 active miners",
        "icon": "Users",
        "xp_reward": 300,
        "rarity": "RARE",
    },
    "mining_10_referrals": {
        "name": "Mining Brigade",
        "description": "Invite 10 active miners",
        "icon": "Network",
        "xp_reward": 750,
        "rarity": "EPIC",
    },
    "mining_50_referrals": {
        "name": "Mining Syndicate",
        "description": "Build a network of 50 active nodes",
        "icon": "Building",
        "xp_reward": 2500,
        "rarity": "LEGENDARY",
    },
    "mining_active_squad": {
        "name": "All Hands On Deck",
        "description": "Have 5+ referrals mining simultaneously on the same day",
        "icon": "Radio",
        "xp_reward": 500,
        "rarity": "EPIC",
    },
    "mining_mentor_bonus": {
        "name": "Mentor",
        "description": "Your referral claimed their Welcome Bonus",
        "icon": "GraduationCap",
        "xp_reward": 250,
        "rarity": "RARE",
    },
    "mining_ref_volume_100k": {
        "name": "Network Megaphone",
        "description": "Referral network combined volume exceeded $100,000",
        "icon": "Share2",
        "xp_reward": 1000,
        "rarity": "EPIC",
    },
    "mining_ref_earnings_100k": {
        "name": "Passive Income",
        "description": "Earn 100,000 $DEPTH purely from 10% referral bonuses",
        "icon": "Gem",
        "xp_reward": 3000,
        "rarity": "LEGENDARY",
    },
    # Streaks & Consistency
    "mining_streak_7d": {
        "name": "Weekly Marathon",
        "description": "Participate in mining emission for 7 consecutive epochs",
        "icon": "Flame",
        "xp_reward": 350,
        "rarity": "RARE",
    },
    "mining_streak_30d": {
        "name": "Iron Discipline",
        "description": "Unbroken mining streak for 30 consecutive epochs",
        "icon": "Shield",
        "xp_reward": 1500,
        "rarity": "EPIC",
    },
    "mining_epochs_100": {
        "name": "Network Veteran",
        "description": "Participate in 100 daily epochs in total",
        "icon": "Award",
        "xp_reward": 3000,
        "rarity": "LEGENDARY",
    },
    "mining_halving_survivor": {
        "name": "Halving Survivor",
        "description": "Be an active miner during an emission halving event",
        "icon": "Hourglass",
        "xp_reward": 2500,
        "rarity": "LEGENDARY",
    },
    # Token Milestones
    "mining_depth_1k": {
        "name": "First Thousand",
        "description": "Mine a cumulative total of 1,000 $DEPTH",
        "icon": "Coins",
        "xp_reward": 100,
        "rarity": "COMMON",
    },
    "mining_depth_10k": {
        "name": "Gold Reserve",
        "description": "Mine a cumulative total of 10,000 $DEPTH",
        "icon": "Boxes",
        "xp_reward": 500,
        "rarity": "RARE",
    },
    "mining_depth_100k": {
        "name": "Crypto Tycoon",
        "description": "Mine a cumulative total of 100,000 $DEPTH",
        "icon": "Crown",
        "xp_reward": 3000,
        "rarity": "LEGENDARY",
    },
    "mining_jackpot_epoch": {
        "name": "Hit the Jackpot",
        "description": "Receive over 5,000 $DEPTH in a single daily epoch",
        "icon": "Zap",
        "xp_reward": 1000,
        "rarity": "EPIC",
    },
    # Execution & Telemetry
    "mining_flawless_telemetry": {
        "name": "Flawless Stream",
        "description": "50 consecutive trades without a single verification rejection",
        "icon": "CheckCircle2",
        "xp_reward": 300,
        "rarity": "RARE",
    },
    "mining_high_speed_turnover": {
        "name": "High Frequency",
        "description": "Execute 50+ verified trades in a single trading day",
        "icon": "Gauge",
        "xp_reward": 250,
        "rarity": "RARE",
    },
    "mining_profitable": {
        "name": "In the Green",
        "description": "10 consecutive closed mining trades with positive PnL",
        "icon": "TrendingUp",
        "xp_reward": 250,
        "rarity": "RARE",
    },
    # Multi-exchange & Infra
    "mining_multi_exchange": {
        "name": "Arbitrageur",
        "description": "Mine trades on 2+ different exchanges within one week",
        "icon": "Shuffle",
        "xp_reward": 300,
        "rarity": "RARE",
    },
    "mining_all_exchanges": {
        "name": "Omnipresent",
        "description": "Link UIDs and mine trades on all supported exchanges",
        "icon": "Globe",
        "xp_reward": 750,
        "rarity": "EPIC",
    },
    "mining_node_operator": {
        "name": "Private Datacenter",
        "description": "Operate a mining server node hosting other miners",
        "icon": "Server",
        "xp_reward": 2000,
        "rarity": "LEGENDARY",
    },
    # Staking & Boosters
    "mining_boost_active": {
        "name": "Afterburner",
        "description": "Activate any mining boost multiplier",
        "icon": "Rocket",
        "xp_reward": 150,
        "rarity": "COMMON",
    },
    "mining_diamond_staker": {
        "name": "Diamond Staker",
        "description": "Lock $DEPTH for 360 days to unlock the maximum 2.0x multiplier",
        "icon": "HandHeart",
        "xp_reward": 2500,
        "rarity": "LEGENDARY",
    },
}


async def grant_achievement(db: AsyncSession, user_id: int, achievement_id: str):
    """
    Grants an achievement to a user and updates their XP and level.
    This function is designed to be called within a larger transaction.
    It does not commit or rollback, leaving that to the session's context manager.
    It checks for existing achievements to prevent IntegrityError and handles other exceptions internally.
    """

    # 1. Check if user already has the achievement to ensure idempotency
    try:
        existing_achievement_stmt = select(models.UserAchievement).where(
            models.UserAchievement.user_id == user_id,
            models.UserAchievement.achievement_id == achievement_id,
        )
        existing_achievement_result = await db.execute(existing_achievement_stmt)
        if existing_achievement_result.scalars().first():
            return None  # Already has it, do nothing.
    except Exception as e:
        logger.error(
            f"Error checking for existing achievement {achievement_id} for user {user_id}: {e}",
            exc_info=True,
        )
        return None

    try:
        # 2. Get the achievement details to find XP reward
        achievement = await db.get(models.Achievement, achievement_id)
        if not achievement:
            if achievement_id in MINING_ACHIEVEMENTS:
                meta = MINING_ACHIEVEMENTS[achievement_id]
                achievement = models.Achievement(
                    id=achievement_id,
                    name=meta["name"],
                    description=meta["description"],
                    icon=meta["icon"],
                    xp_reward=meta["xp_reward"],
                    rarity=models.Rarity[meta["rarity"]],
                )
                db.add(achievement)
                await db.flush()
            else:
                logger.warning(
                    f"Attempted to grant non-existent achievement '{achievement_id}' to user {user_id}"
                )
                return None

        # 3. Get the user
        user = await db.get(models.User, user_id)
        if not user:
            logger.error(
                f"Could not find user with ID {user_id} to grant achievement '{achievement_id}'"
            )
            return None

        # 4. Create and add the UserAchievement
        user_achievement = models.UserAchievement(
            user_id=user_id, achievement_id=achievement_id
        )
        db.add(user_achievement)

        # 5. Update user's XP and level
        user.xp += achievement.xp_reward
        new_level = calculate_level(user.xp)
        if new_level > user.level:
            user.level = new_level

        await db.flush()  # Flush changes to the DB to catch potential errors early

        logger.info(
            f"Granted achievement '{achievement_id}' to user {user_id}. New XP: {user.xp}"
        )

        # --- NEW: Send Push Notification for new achievement ---
        if user.push_subscription:
            try:
                send_push_notification(
                    subscription_info=user.push_subscription,
                    title="New achievement!",
                    body=f"You have unlocked an achievement: {achievement.name}!",
                    tag=f"achievement-{achievement_id}",
                )
            except Exception as push_exc:
                logger.error(
                    f"Failed to send push notification for achievement {achievement_id} to user {user_id}: {push_exc}",
                    exc_info=True,
                )
        # --- END NEW ---

        # --- Real-Time WebSocket broadcast (Steam / Game Notification) ---
        try:
            from .redis_client import get_redis_client
            import json

            redis = await get_redis_client()
            rarity_str = (
                achievement.rarity.value
                if hasattr(achievement.rarity, "value")
                else str(achievement.rarity)
            )
            event_payload = json.dumps(
                {
                    "type": "achievement_unlocked",
                    "achievement": {
                        "id": achievement.id,
                        "name": achievement.name,
                        "description": achievement.description,
                        "icon": achievement.icon,
                        "xp_reward": achievement.xp_reward,
                        "rarity": rarity_str,
                    },
                    "user_xp": user.xp,
                    "user_level": user.level,
                }
            )
            await redis.publish(f"user:{user_id}:notifications", event_payload)
            await redis.publish("achievement_unlocked", event_payload)
            await redis.close()
        except Exception as ws_err:
            logger.debug(f"Failed to publish achievement event to Redis: {ws_err}")
        # --- END Real-Time WebSocket broadcast ---

        return user_achievement
    except Exception as e:
        logger.error(
            f"Error during achievement grant for user {user_id}, achievement {achievement_id}: {e}",
            exc_info=True,
        )
        # Do not raise, just log and return None. This allows other achievements in the same transaction to succeed.
        return None


async def check_and_grant_retroactive_achievements(db: AsyncSession, user_id: int):
    """
    Checks for and grants achievements that can be awarded retroactively.
    This is typically called on user login.
    """
    # Get user's existing achievements to avoid redundant checks
    user_achievements_result = await db.execute(
        select(models.UserAchievement.achievement_id).where(
            models.UserAchievement.user_id == user_id
        )
    )
    user_achievements = {row[0] for row in user_achievements_result}

    # --- Onboarding & First Steps ---

    # first_save
    if "first_save" not in user_achievements:
        saved_strategies = await crud.get_strategy_configs_by_user(db, user_id=user_id)
        if saved_strategies:
            await grant_achievement(db, user_id, "first_save")

    # first_api_key
    if "first_api_key" not in user_achievements:
        api_keys = await crud.get_api_keys_for_user(db, user_id=user_id)
        if api_keys:
            await grant_achievement(db, user_id, "first_api_key")

    # --- Quantitative Achievements ---
    tasks, _ = await crud.get_tasks_by_user(
        db, user_id=user_id, limit=10000
    )  # Get all tasks

    backtest_count = sum(1 for task in tasks if task.task_type == "backtest")
    if backtest_count > 0 and "first_backtest" not in user_achievements:
        await grant_achievement(db, user_id, "first_backtest")
    if backtest_count >= 10 and "10_backtests" not in user_achievements:
        await grant_achievement(db, user_id, "10_backtests")
    if backtest_count >= 100 and "100_backtests" not in user_achievements:
        await grant_achievement(db, user_id, "100_backtests")
    if backtest_count >= 500 and "500_backtests" not in user_achievements:
        await grant_achievement(db, user_id, "500_backtests")

    optimization_count = sum(1 for task in tasks if task.task_type == "optimization")
    if optimization_count > 0 and "first_optimization" not in user_achievements:
        await grant_achievement(db, user_id, "first_optimization")
    if optimization_count >= 50 and "50_optimizations" not in user_achievements:
        await grant_achievement(db, user_id, "50_optimizations")

    # --- Total Trades in Backtests ---
    all_backtest_runs = await crud.get_all_backtest_runs_for_user(db, user_id=user_id)
    total_trades = 0
    for run in all_backtest_runs:
        if (
            run.status == "COMPLETED"
            and run.kpi_results_json
            and "trades" in run.kpi_results_json
        ):
            total_trades += run.kpi_results_json["trades"]

    if total_trades >= 1000 and "1000_trades_backtests" not in user_achievements:
        await grant_achievement(db, user_id, "1000_trades_backtests")
    if total_trades >= 10000 and "10000_trades_backtests" not in user_achievements:
        await grant_achievement(db, user_id, "10000_trades_backtests")

    if "save_10_strategies" not in user_achievements:
        saved_strategies = await crud.get_strategy_configs_by_user(db, user_id=user_id)
        if len(saved_strategies) >= 10:
            await grant_achievement(db, user_id, "save_10_strategies")

    # --- Trade Mining Achievements ---
    await check_and_grant_mining_achievements(db, user_id)


_LAST_MINING_CHECK: dict[int, float] = {}
MINING_CHECK_COOLDOWN_SEC = 180.0  # 3 minutes cooldown


async def check_and_grant_mining_achievements(
    db: AsyncSession, user_id: int, use_cooldown: bool = False
):
    """
    Checks and awards trade mining achievements for a user.
    Called on user login/retroactive check and mining events.
    Optionally enforces a 3-minute cooldown (used during high-frequency polling).
    """
    try:
        import time

        now_ts = time.time()
        if (
            use_cooldown
            and (now_ts - _LAST_MINING_CHECK.get(user_id, 0.0))
            < MINING_CHECK_COOLDOWN_SEC
        ):
            return
        if use_cooldown:
            _LAST_MINING_CHECK[user_id] = now_ts

        user_achievements_result = await db.execute(
            select(models.UserAchievement.achievement_id).where(
                models.UserAchievement.user_id == user_id
            )
        )
        user_achievements = {row[0] for row in user_achievements_result}

        # Short-circuit: if user already has all mining achievements, nothing left to check
        if set(MINING_ACHIEVEMENTS.keys()).issubset(user_achievements):
            return

        config = await crud.get_config_model(db, user_id=user_id)
        if not config:
            return

        exchange_settings = dict(config.exchange_settings or {})
        mining_node_uuid = (
            (exchange_settings.get("bybit") or {}).get("mining_node_uuid")
            or (exchange_settings.get("okx") or {}).get("mining_node_uuid")
            or (exchange_settings.get("weex") or {}).get("mining_node_uuid")
            or (exchange_settings.get("binance") or {}).get("mining_node_uuid")
            or exchange_settings.get("mining_node_uuid")
        )
        wallet_configured = (
            (exchange_settings.get("bybit") or {}).get("wallet_configured", False)
            or (exchange_settings.get("okx") or {}).get("wallet_configured", False)
            or (exchange_settings.get("weex") or {}).get("wallet_configured", False)
            or (exchange_settings.get("binance") or {}).get("wallet_configured", False)
            or exchange_settings.get("wallet_configured", False)
        )

        # 1. Onboarding & Web3
        if config.is_mining_enabled and "mining_activated" not in user_achievements:
            await grant_achievement(db, user_id, "mining_activated")

        if wallet_configured and "mining_wallet_linked" not in user_achievements:
            await grant_achievement(db, user_id, "mining_wallet_linked")

        if not mining_node_uuid:
            return

        # Check HubNode if exists
        node_res = await db.execute(
            select(models.HubNode).where(models.HubNode.node_uuid == mining_node_uuid)
        )
        node = node_res.scalars().first()
        if node:
            if node.wallet_address and "mining_wallet_linked" not in user_achievements:
                await grant_achievement(db, user_id, "mining_wallet_linked")
            if (
                node.is_mining_server
                and "mining_node_operator" not in user_achievements
            ):
                await grant_achievement(db, user_id, "mining_node_operator")

            # Exchange diversity check
            linked_uids = sum(1 for uid in [node.bybit_uid, node.okx_uid] if uid)
            if linked_uids >= 2 and "mining_multi_exchange" not in user_achievements:
                await grant_achievement(db, user_id, "mining_multi_exchange")
            if (
                node.bybit_uid
                and node.okx_uid
                and "mining_all_exchanges" not in user_achievements
            ):
                await grant_achievement(db, user_id, "mining_all_exchanges")

        # Check MiningLedger records for node
        ledger_stmt = select(models.MiningLedger).where(
            models.MiningLedger.node_uuid == mining_node_uuid
        )
        ledger_res = await db.execute(ledger_stmt)
        ledgers = ledger_res.scalars().all()

        if ledgers:
            # First trade
            total_verified_trades = sum(
                entry.verified_trades_count for entry in ledgers
            )
            if (
                total_verified_trades > 0
                and "mining_first_trade" not in user_achievements
            ):
                await grant_achievement(db, user_id, "mining_first_trade")

            # Welcome bonus
            if (
                any(entry.welcome_bonus > 0 for entry in ledgers)
                and "welcome_bonus_claimed" not in user_achievements
            ):
                await grant_achievement(db, user_id, "welcome_bonus_claimed")

            # Boost active
            if (
                any(entry.boost_multiplier > 1.0 for entry in ledgers)
                and "mining_boost_active" not in user_achievements
            ):
                await grant_achievement(db, user_id, "mining_boost_active")

            # Total $DEPTH mined
            total_mined = sum(entry.total_reward for entry in ledgers)
            if total_mined >= 1000 and "mining_depth_1k" not in user_achievements:
                await grant_achievement(db, user_id, "mining_depth_1k")
            if total_mined >= 10000 and "mining_depth_10k" not in user_achievements:
                await grant_achievement(db, user_id, "mining_depth_10k")
            if total_mined >= 100000 and "mining_depth_100k" not in user_achievements:
                await grant_achievement(db, user_id, "mining_depth_100k")

            # Jackpot epoch
            if (
                any(entry.total_reward >= 5000 for entry in ledgers)
                and "mining_jackpot_epoch" not in user_achievements
            ):
                await grant_achievement(db, user_id, "mining_jackpot_epoch")

            # Referral earnings milestone (100,000 $DEPTH)
            total_ref_bonus = sum(entry.referral_bonus for entry in ledgers)
            if (
                total_ref_bonus >= 100000
                and "mining_ref_earnings_100k" not in user_achievements
            ):
                await grant_achievement(db, user_id, "mining_ref_earnings_100k")

            # Streaks / Epoch count
            epochs_count = len(ledgers)
            if epochs_count >= 7 and "mining_streak_7d" not in user_achievements:
                await grant_achievement(db, user_id, "mining_streak_7d")
            if epochs_count >= 30 and "mining_streak_30d" not in user_achievements:
                await grant_achievement(db, user_id, "mining_streak_30d")
            if epochs_count >= 100 and "mining_epochs_100" not in user_achievements:
                await grant_achievement(db, user_id, "mining_epochs_100")

            # Diamond staker (locked for 360 days -> 2.0x boost)
            if (
                any(entry.boost_multiplier >= 2.0 for entry in ledgers)
                and "mining_diamond_staker" not in user_achievements
            ):
                await grant_achievement(db, user_id, "mining_diamond_staker")

        # Check Referrals Network
        ref_stmt = select(models.HubNode).where(
            models.HubNode.referrer_node_uuid == mining_node_uuid
        )
        ref_res = await db.execute(ref_stmt)
        referred_nodes = ref_res.scalars().all()
        ref_count = len(referred_nodes)

        if ref_count >= 1 and "mining_first_referral" not in user_achievements:
            await grant_achievement(db, user_id, "mining_first_referral")
        if ref_count >= 5 and "mining_5_referrals" not in user_achievements:
            await grant_achievement(db, user_id, "mining_5_referrals")
        if ref_count >= 10 and "mining_10_referrals" not in user_achievements:
            await grant_achievement(db, user_id, "mining_10_referrals")
        if ref_count >= 50 and "mining_50_referrals" not in user_achievements:
            await grant_achievement(db, user_id, "mining_50_referrals")

        # Referral bonuses: mentor bonus & network volume & active squad
        if referred_nodes:
            if (
                any(n.has_welcome_bonus for n in referred_nodes)
                and "mining_mentor_bonus" not in user_achievements
            ):
                await grant_achievement(db, user_id, "mining_mentor_bonus")

            ref_uuids = [n.node_uuid for n in referred_nodes]
            ref_tel_stmt = select(models.HubTelemetryReport).where(
                models.HubTelemetryReport.node_uuid.in_(ref_uuids)
            )
            ref_tel_res = await db.execute(ref_tel_stmt)
            ref_reports = ref_tel_res.scalars().all()

            if ref_reports:
                total_ref_vol = sum(
                    r.trade_volume_usdt or r.verified_volume_usdt or 0.0
                    for r in ref_reports
                )
                if (
                    total_ref_vol >= 100000
                    and "mining_ref_volume_100k" not in user_achievements
                ):
                    await grant_achievement(db, user_id, "mining_ref_volume_100k")

                # Active squad: 5+ referrals mining on same date
                day_ref_map = {}
                for r in ref_reports:
                    if r.created_at:
                        d = r.created_at.date()
                        day_ref_map.setdefault(d, set()).add(r.node_uuid)
                if (
                    any(len(nodes) >= 5 for nodes in day_ref_map.values())
                    and "mining_active_squad" not in user_achievements
                ):
                    await grant_achievement(db, user_id, "mining_active_squad")

        # Telemetry reports checks (volume, speed, pnl)
        telemetry_achievements = {
            "mining_volume_1k",
            "mining_volume_10k",
            "mining_volume_100k",
            "mining_volume_1m",
            "mining_volume_10m",
            "mining_first_trade",
            "mining_daily_volume_10k",
            "mining_daily_volume_100k",
            "mining_high_speed_turnover",
            "mining_flawless_telemetry",
            "mining_profitable",
        }
        if not telemetry_achievements.issubset(user_achievements):
            telemetry_stmt = select(models.HubTelemetryReport).where(
                models.HubTelemetryReport.node_uuid == mining_node_uuid
            )
            telemetry_res = await db.execute(telemetry_stmt)
            reports = telemetry_res.scalars().all()
        else:
            reports = []

        if reports:
            total_vol = sum(
                r.trade_volume_usdt or r.verified_volume_usdt or 0.0 for r in reports
            )
            if total_vol >= 1000 and "mining_volume_1k" not in user_achievements:
                await grant_achievement(db, user_id, "mining_volume_1k")
            if total_vol >= 10000 and "mining_volume_10k" not in user_achievements:
                await grant_achievement(db, user_id, "mining_volume_10k")
            if total_vol >= 100000 and "mining_volume_100k" not in user_achievements:
                await grant_achievement(db, user_id, "mining_volume_100k")
            if total_vol >= 1000000 and "mining_volume_1m" not in user_achievements:
                await grant_achievement(db, user_id, "mining_volume_1m")
            if total_vol >= 10000000 and "mining_volume_10m" not in user_achievements:
                await grant_achievement(db, user_id, "mining_volume_10m")

            if (
                any(
                    (r.is_mining_eligible or r.verification_status == "VERIFIED")
                    for r in reports
                )
                and "mining_first_trade" not in user_achievements
            ):
                await grant_achievement(db, user_id, "mining_first_trade")

            # Daily volume & high frequency
            day_vols = {}
            day_counts = {}
            for r in reports:
                d = r.created_at.date() if r.created_at else None
                if d:
                    vol = r.trade_volume_usdt or r.verified_volume_usdt or 0.0
                    day_vols[d] = day_vols.get(d, 0.0) + vol
                    day_counts[d] = day_counts.get(d, 0) + 1

            if (
                any(v >= 10000 for v in day_vols.values())
                and "mining_daily_volume_10k" not in user_achievements
            ):
                await grant_achievement(db, user_id, "mining_daily_volume_10k")
            if (
                any(v >= 100000 for v in day_vols.values())
                and "mining_daily_volume_100k" not in user_achievements
            ):
                await grant_achievement(db, user_id, "mining_daily_volume_100k")
            if (
                any(c >= 50 for c in day_counts.values())
                and "mining_high_speed_turnover" not in user_achievements
            ):
                await grant_achievement(db, user_id, "mining_high_speed_turnover")

            # Consecutive streaks: flawless telemetry & profitable
            sorted_reports = sorted(
                reports,
                key=lambda x: (
                    x.created_at
                    if x.created_at
                    else dt.datetime.min.replace(tzinfo=dt.timezone.utc)
                ),
            )
            cur_flawless = 0
            max_flawless = 0
            cur_profitable = 0
            max_profitable = 0
            for r in sorted_reports:
                if r.verification_status != "REJECTED":
                    cur_flawless += 1
                    max_flawless = max(max_flawless, cur_flawless)
                else:
                    cur_flawless = 0

                if r.pnl_percent is not None and r.pnl_percent > 0:
                    cur_profitable += 1
                    max_profitable = max(max_profitable, cur_profitable)
                else:
                    cur_profitable = 0

            if (
                max_flawless >= 50
                and "mining_flawless_telemetry" not in user_achievements
            ):
                await grant_achievement(db, user_id, "mining_flawless_telemetry")
            if max_profitable >= 10 and "mining_profitable" not in user_achievements:
                await grant_achievement(db, user_id, "mining_profitable")
    except Exception as e:
        logger.error(
            f"Error checking mining achievements for user {user_id}: {e}", exc_info=True
        )
