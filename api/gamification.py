from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from . import models, crud
import logging

from .push_sender import send_push_notification  # New import

logger = logging.getLogger(__name__)


def calculate_level(xp: int) -> int:
    """Calculates user level based on XP."""
    return int((xp / 100) ** (1 / 1.5)) + 1


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
