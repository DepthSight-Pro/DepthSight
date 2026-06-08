import logging
from typing import List

import redis.asyncio as redis
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select

from .. import crud, models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..dependencies import require_affiliate_role
from ..redis_client import get_redis_client


logger = logging.getLogger(__name__)

affiliate_router = APIRouter(
    prefix="/api/v1/affiliate",
    tags=["Affiliate"],
    dependencies=[Depends(require_affiliate_role)],
)


@affiliate_router.get("/dashboard", response_model=schemas.AffiliateDashboardStats)
async def get_affiliate_dashboard(
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: redis.Redis = Depends(get_redis_client),
):
    return await crud.get_affiliate_dashboard_stats(
        db, redis_client=redis, user_id=current_user.id
    )


@affiliate_router.get("/commissions", response_model=schemas.PaginatedCommissions)
async def get_affiliate_commissions(
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    skip = (page - 1) * page_size
    commissions, total = await crud.get_commissions_for_affiliate(
        db, affiliate_user_id=current_user.id, skip=skip, limit=page_size
    )
    return {"total": total, "commissions": commissions}


@affiliate_router.get("/referrals", response_model=schemas.PaginatedAffiliateReferrals)
async def get_affiliate_referrals(
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    skip = (page - 1) * page_size
    users, total = await crud.get_referrals_for_affiliate(
        db, affiliate_user_id=current_user.id, skip=skip, limit=page_size
    )

    referrals_with_payment_status: List[schemas.AffiliateReferral] = []
    for user in users:
        commission_exists_query = select(
            select(models.Commission).filter_by(referred_user_id=user.id).exists()
        )
        commission_exists = await db.scalar(commission_exists_query)

        referrals_with_payment_status.append(
            schemas.AffiliateReferral(
                id=user.id,
                username=user.username,
                registered_at=user.created_at,
                is_paying=commission_exists,
            )
        )

    return {"total": total, "referrals": referrals_with_payment_status}


@affiliate_router.get("/payouts", response_model=schemas.PaginatedAffiliatePayouts)
async def get_affiliate_payouts(
    page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100)
):
    return {"total": 0, "payouts": []}


@affiliate_router.post("/payout-details")
async def update_payout_details(
    payload: schemas.PayoutDetailsPayload,
    current_user: models.User = Depends(get_current_user),
):
    logger.info(
        "User %s updated payout address to: %s",
        current_user.id,
        payload.usdt_trc20_address,
    )
    return {"status": "ok", "message": "Payout details updated successfully."}


@affiliate_router.post("/request-payout")
async def request_payout(current_user: models.User = Depends(get_current_user)):
    logger.info("User %s requested a payout.", current_user.id)
    return {
        "status": "ok",
        "message": "Payout requested successfully. It will be processed soon.",
    }
