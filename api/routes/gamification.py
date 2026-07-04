import logging
from typing import List
from fastapi import APIRouter, Depends, status, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..dependencies import require_admin_role


logger = logging.getLogger(__name__)

gamification_router = APIRouter(
    prefix="/api/v1",
    tags=["Gamification"],
    dependencies=[Depends(get_current_user)],
)


@gamification_router.get(
    "/leaderboard",
    response_model=schemas.ApiResponseData[List[schemas.LeaderboardEntry]],
)
async def get_leaderboard(
    period: str = Query("all_time", enum=["weekly", "monthly", "all_time"]),
    category: str = Query("sharpe_ratio", enum=["sharpe_ratio", "net_pnl_percent"]),
    db: AsyncSession = Depends(get_db),
):
    """
    Get leaderboard data.
    """
    leaderboard_period = models.LeaderboardPeriod(period)
    leaderboard_entries = await crud.get_leaderboard(
        db, period=leaderboard_period, category=category
    )
    return {"data": leaderboard_entries}


@gamification_router.delete(
    "/leaderboard/{entry_id}", response_model=schemas.ApiResponseData[bool]
)
async def delete_leaderboard_entry(
    entry_id: str,
    current_user: models.User = Depends(require_admin_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a leaderboard entry (Admin only).
    """
    success = await crud.delete_leaderboard_entry(db, entry_id)
    return {"data": success}


@gamification_router.get(
    "/achievements", response_model=schemas.ApiResponseData[List[schemas.Achievement]]
)
async def get_achievements(db: AsyncSession = Depends(get_db)):
    """
    Get all achievements.
    """
    achievements = await crud.get_achievements(db)
    return {"data": achievements}


@gamification_router.get(
    "/users/{user_id}/achievements",
    response_model=schemas.ApiResponseData[List[schemas.UserAchievement]],
)
async def get_user_achievements(user_id: int, db: AsyncSession = Depends(get_db)):
    """
    Get user's achievements.
    """
    user_achievements = await crud.get_user_achievements(db, user_id=user_id)
    return {"data": user_achievements}


async def general_exception_handler_custom(request, exc: Exception):
    print(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Internal Server Error", "detail": str(exc)},
    )
