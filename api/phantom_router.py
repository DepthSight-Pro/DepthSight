# api/phantom_router.py
# API endpoints for Phantom Trade (BE Analysis) functionality

import logging
from typing import Optional
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from . import models, schemas
from .database import get_db
from .auth import get_current_user

logger = logging.getLogger(__name__)

phantom_router = APIRouter(
    prefix="/api/v1/analytics/phantom",
    tags=["Phantom Trades / BE Analysis"],
    dependencies=[Depends(get_current_user)],
)


@phantom_router.get("/stats", response_model=schemas.BEAnalysisStats)
async def get_be_analysis_stats(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    strategy: Optional[str] = Query(None, description="Filter by strategy"),
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get aggregated BE (Breakeven) analysis statistics.
    Shows how effective BE was - how many times it saved from loss vs stolen potential profit.
    """
    from_date = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=days)

    # Build filter conditions
    conditions = [
        models.PhantomTrade.user_id == current_user.id,
        models.PhantomTrade.be_trigger_time >= from_date,
    ]

    if symbol:
        conditions.append(models.PhantomTrade.symbol == symbol)
    if strategy:
        conditions.append(models.PhantomTrade.strategy == strategy)

    # Query phantom trades
    query = select(models.PhantomTrade).where(and_(*conditions))
    result = await db.execute(query)
    phantom_trades = result.scalars().all()

    if not phantom_trades:
        return schemas.BEAnalysisStats(
            total_be_trades=0,
            tp_would_hit=0,
            sl_would_hit=0,
            timeout=0,
            be_saved_pct=0.0,
            be_stolen_pct=0.0,
            avg_mfe_after_be=0.0,
            avg_mae_after_be=0.0,
            avg_phantom_pnl_if_tp=0.0,
            avg_phantom_pnl_if_sl=0.0,
            by_outcome={},
            recommendation=None,
        )

    # Calculate statistics
    total = len(phantom_trades)
    tp_hits = [p for p in phantom_trades if p.phantom_status == "TP_HIT"]
    sl_hits = [p for p in phantom_trades if p.phantom_status == "SL_HIT"]
    timeouts = [p for p in phantom_trades if p.phantom_status == "TIMEOUT"]

    tp_count = len(tp_hits)
    sl_count = len(sl_hits)
    timeout_count = len(timeouts)

    # Calculate averages safely
    def safe_avg(items, attr):
        vals = [getattr(p, attr) for p in items if getattr(p, attr) is not None]
        return sum(vals) / len(vals) if vals else 0.0

    avg_mfe = safe_avg(phantom_trades, "mfe_after_be")
    avg_mae = safe_avg(phantom_trades, "mae_after_be")
    avg_pnl_tp = safe_avg(tp_hits, "phantom_pnl_pct") if tp_hits else 0.0
    avg_pnl_sl = safe_avg(sl_hits, "phantom_pnl_pct") if sl_hits else 0.0

    def outcome_stats(items):
        return schemas.BEStatsByOutcome(
            count=len(items),
            avg_phantom_pnl_pct=safe_avg(items, "phantom_pnl_pct"),
            total_phantom_pnl_pct=sum((p.phantom_pnl_pct or 0.0) for p in items),
            avg_candles_to_resolution=safe_avg(items, "candles_to_resolution"),
        )

    by_outcome = {
        "TP_HIT": outcome_stats(tp_hits),
        "SL_HIT": outcome_stats(sl_hits),
        "TIMEOUT": outcome_stats(timeouts),
    }

    return schemas.BEAnalysisStats(
        total_be_trades=total,
        tp_would_hit=tp_count,
        sl_would_hit=sl_count,
        timeout=timeout_count,
        be_saved_pct=(sl_count / total * 100) if total > 0 else 0.0,
        be_stolen_pct=(tp_count / total * 100) if total > 0 else 0.0,
        avg_mfe_after_be=avg_mfe,
        avg_mae_after_be=avg_mae,
        avg_phantom_pnl_if_tp=avg_pnl_tp,
        avg_phantom_pnl_if_sl=avg_pnl_sl,
        by_outcome=by_outcome,
        recommendation=None,
    )


@phantom_router.get("/trades", response_model=schemas.PaginatedPhantomTradesResponse)
async def get_phantom_trades(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    strategy: Optional[str] = Query(None, description="Filter by strategy"),
    phantom_status: Optional[str] = Query(
        None, description="Filter by status: TP_HIT, SL_HIT, TIMEOUT"
    ),
    skip: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=200, description="Number of items to return"),
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get paginated list of phantom trades for BE analysis.
    """
    # Build filter conditions
    conditions = [models.PhantomTrade.user_id == current_user.id]

    if symbol:
        conditions.append(models.PhantomTrade.symbol == symbol)
    if strategy:
        conditions.append(models.PhantomTrade.strategy == strategy)
    if phantom_status:
        conditions.append(models.PhantomTrade.phantom_status == phantom_status)

    # Count total
    count_query = select(func.count(models.PhantomTrade.id)).where(and_(*conditions))
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Fetch items
    query = (
        select(models.PhantomTrade)
        .where(and_(*conditions))
        .order_by(models.PhantomTrade.be_trigger_time.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    trades = result.scalars().all()

    return schemas.PaginatedPhantomTradesResponse(
        total=total,
        trades=[schemas.PhantomTradeResponse.model_validate(t) for t in trades],
    )


@phantom_router.get("/scatter-data", response_model=schemas.BEScatterDataResponse)
async def get_be_scatter_data(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get scatter plot data for BE analysis visualization.
    Returns MFE, MAE, and phantom PnL for each BE trade.
    """
    from_date = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=days)

    query = select(models.PhantomTrade).where(
        and_(
            models.PhantomTrade.user_id == current_user.id,
            models.PhantomTrade.be_trigger_time >= from_date,
        )
    )
    result = await db.execute(query)
    trades = result.scalars().all()

    points = []
    for t in trades:
        points.append(
            schemas.BEScatterDataPoint(
                trade_id=t.real_trade_id,
                symbol=t.symbol,
                direction=t.direction,
                entry_time=t.entry_time,
                phantom_status=t.phantom_status,
                real_pnl_pct=t.real_pnl_pct,
                mfe_after_be=t.mfe_after_be or 0.0,
                mae_after_be=t.mae_after_be or 0.0,
                phantom_pnl_pct=t.phantom_pnl_pct,
                candles_to_resolution=t.candles_to_resolution or 0,
            )
        )

    return schemas.BEScatterDataResponse(
        points=points,
        total_points=len(points),
        avg_mfe=sum((p.mfe_after_be or 0.0) for p in points) / len(points)
        if points
        else 0.0,
        avg_mae=sum((p.mae_after_be or 0.0) for p in points) / len(points)
        if points
        else 0.0,
    )
