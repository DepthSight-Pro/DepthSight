import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from typing import List
from datetime import datetime, timezone, timedelta
from .. import crud, models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..gamification import grant_achievement
from ..redis_client import get_redis_client
from ..plans import plans_config


logger = logging.getLogger(__name__)

account_router = APIRouter(
    prefix="/api/v1/account",
    tags=["Account"],
    dependencies=[Depends(get_current_user)],
)


@account_router.get(
    "/status",
    response_model=schemas.ApiResponseData[schemas.AccountStatusData],
    summary="Get account status, plan and quotas",
)
async def get_account_status(
    current_user: models.User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns information on user's current plan and quota usage.
    """
    user_plan_name = current_user.plan
    plan_config = plans_config.get_plan(user_plan_name)
    if not plan_config:
        raise HTTPException(status_code=404, detail="Plan not found")

    quotas_config = plan_config.get("quotas", {})
    quota_statuses = []

    now = datetime.now(timezone.utc)

    for quota_key, limit in quotas_config.items():
        # We only process quotas that have a defined period
        period_map = {"day": "_per_day", "week": "_per_week", "month": "_per_month"}
        period = next((p for p, s in period_map.items() if s in quota_key), None)
        if not period:
            continue

        date_str = ""
        if period == "day":
            date_str = now.strftime("%Y-%m-%d")
        elif period == "week":
            start_of_week = now - timedelta(days=now.weekday())
            date_str = start_of_week.strftime("%Y-%m-%d")
        elif period == "month":
            date_str = now.strftime("%Y-%m")

        redis_key = f"usage:{current_user.id}:{quota_key}:{date_str}"

        used_value_raw = await redis_client.get(redis_key)
        used_value = int(used_value_raw) if used_value_raw else 0

        quota_statuses.append(
            schemas.QuotaStatus(
                name=quota_key,  # Send the key instead of the display name
                used=used_value,
                limit=limit,
                period=period,
            )
        )

    referral_config = plans_config.get_referral_bonus_config()

    # Get user bonuses
    bonuses = await crud.get_user_bonuses(db, user_id=current_user.id)
    bonus_infos = [schemas.BonusInfo.model_validate(bonus) for bonus in bonuses]

    account_status_data = schemas.AccountStatusData(
        planName=user_plan_name,
        planExpiresAt=current_user.plan_expires_at,
        quotas=quota_statuses,
        bonuses=bonus_infos,
        referral_program=referral_config,
    )

    return schemas.ApiResponseData[schemas.AccountStatusData](data=account_status_data)


@account_router.get(
    "/paper",
    response_model=schemas.ApiResponseData[List[schemas.PaperWallet]],
    summary="Get paper trading account balances",
)
async def get_paper_wallet(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Retrieves the paper trading wallet balances for the current user.
    If the wallet does not exist, it initializes it with the default balance.
    """
    wallet_assets = await crud.get_paper_wallet(db, user_id=current_user.id)

    # If wallet is empty (e.g. for new user), create it
    if not wallet_assets:
        wallet_assets = await crud.init_or_reset_paper_wallet(
            db, user_id=current_user.id
        )
        await db.commit()

    return {"data": wallet_assets}


@account_router.post(
    "/paper/reset",
    response_model=schemas.ApiResponseData[List[schemas.PaperWallet]],
    summary="Reset paper trading account",
)
async def reset_paper_wallet(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Resets the paper trading account for the current user to the default initial balance.
    """
    logger.info(f"User '{current_user.username}' resetting paper trading account.")

    updated_wallet = await crud.init_or_reset_paper_wallet(db, user_id=current_user.id)

    # Grant 'reset_paper' achievement
    await grant_achievement(db, current_user.id, "reset_paper")

    await db.commit()

    return {"data": updated_wallet}
