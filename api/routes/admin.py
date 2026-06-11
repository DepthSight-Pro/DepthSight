import logging
import json
import subprocess
from pathlib import Path
from typing import Optional, List
from datetime import timedelta, datetime, date
import pandas as pd
from pydantic import BaseModel

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .. import crud, models, schemas, security
from ..database import get_db
from ..dependencies import require_admin_role
from ..redis_client import get_redis_client
from ..plans import plans_config
from ..audit_logger import audit_logger, get_client_ip

logger = logging.getLogger(__name__)

# --- Admin Router ---
admin_router = APIRouter(
    prefix="/api/v1/admin", tags=["Admin"], dependencies=[Depends(require_admin_role)]
)


@admin_router.get("/test-admin")
async def test_admin_endpoint():
    return {"message": "Admin endpoint works!"}


@admin_router.get("/users", response_model=schemas.PaginatedUsers)
async def admin_get_users(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    plan: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Get a paginated list of users.
    Admin only.
    """
    users, total_count = await crud.get_users_paginated(
        db, skip=skip, limit=limit, search=search, plan=plan
    )
    return {"users": users, "total": total_count}


@admin_router.get("/users/{user_id}", response_model=schemas.User)
async def admin_get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    """
    Get details for a specific user.
    Admin only.
    """
    user = await crud.admin_get_user_details(db, user_id=user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@admin_router.get(
    "/users/{user_id}/details", response_model=schemas.AdminUserExtendedDetails
)
async def admin_get_user_extended(user_id: int, db: AsyncSession = Depends(get_db)):
    """
    Get extended details for a specific user including tasks, wallet and bonuses.
    Admin only.
    """
    details = await crud.admin_get_user_extended_details(db, user_id=user_id)
    if details is None:
        raise HTTPException(status_code=404, detail="User not found")
    # Explicitly convert to schema using model_validate
    return schemas.AdminUserExtendedDetails.model_validate(details)


@admin_router.get("/dashboard/stats", response_model=schemas.DashboardStats)
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    """
    Get key metrics for the admin dashboard.
    """
    stats = await crud.get_dashboard_stats(db)
    return stats


@admin_router.put("/users/{user_id}", response_model=schemas.User)
async def admin_update_user(
    user_id: int,
    update_data: schemas.AdminUserUpdate,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Update a user's plan or active status.
    Admin only.
    """
    existing_user = await crud.admin_get_user_details(db, user_id=user_id)
    if not existing_user:
        raise HTTPException(status_code=404, detail="User not found")

    previous_plan = existing_user.plan
    updated_user = await crud.admin_update_user(
        db, user_id=user_id, update_data=update_data
    )
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.commit()
    await db.refresh(updated_user)

    if update_data.plan is not None and update_data.plan != previous_plan:
        try:
            from ..depthsight_api import _sync_live_runtime_for_plan_change

            await _sync_live_runtime_for_plan_change(
                redis_client=redis_client,
                db=db,
                user_id=updated_user.id,
                previous_plan=previous_plan,
                new_plan=updated_user.plan,
            )
        except Exception as exc:
            logger.error(
                "Failed to sync live runtime after admin plan update for user_id=%s: %s",
                updated_user.id,
                exc,
                exc_info=True,
            )

    return updated_user


@admin_router.post(
    "/users/{user_id}/bonuses",
    response_model=schemas.ApiResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_issue_bonus(
    user_id: int,
    bonus_data: schemas.AdminBonusCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Manually issue an active bonus to a user.
    Admin only.
    """
    # Check that user exists
    user = await crud.admin_get_user_details(db, user_id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await crud.admin_create_bonus(db, user_id=user_id, bonus_data=bonus_data)
    await db.commit()
    return {
        "data": {
            "message": f"Bonus '{bonus_data.feature_name}' issued successfully to user {user_id}."
        }
    }


@admin_router.post("/users/{user_id}/impersonate", response_model=schemas.Token)
async def admin_impersonate_user(
    user_id: int,
    request: Request,  # To get IP
    db: AsyncSession = Depends(get_db),
    admin_user: models.User = Depends(require_admin_role),
):
    """
    Generate a short-lived token to log in as another user.
    Admin only.
    """
    target_user = await crud.admin_get_user_details(db, user_id=user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User to impersonate not found")

    if not target_user.is_active:
        raise HTTPException(
            status_code=403, detail="Cannot impersonate an inactive user."
        )

    # Log impersonation - critical security event
    audit_logger.admin_impersonation(
        admin_user_id=admin_user.id,
        admin_username=admin_user.username,
        target_user_id=target_user.id,
        target_username=target_user.username,
        ip_address=get_client_ip(request),
    )

    # Create short-lived token (e.g. for 5 minutes)
    impersonation_token_expires = timedelta(minutes=5)
    access_token = security.create_access_token(
        data={
            "sub": target_user.username,
            "imp": admin_user.id,  # Add claim for auditing
        },
        expires_delta=impersonation_token_expires,
    )
    return schemas.Token(access_token=access_token, token_type="bearer")


@admin_router.get("/bonuses/available", response_model=List[schemas.AvailableBonus])
async def get_available_bonuses():
    """
    Get a list of all bonuses that can be manually issued from the plans config.
    Admin only.
    """
    try:
        # plans_config is already imported at the top of the file
        bonus_config = plans_config.get_referral_bonus_config()
        # Assuming there might be another section for bonuses
        # For simplicity, take bonuses from referral program for now

        available_bonuses = []

        # Extract bonuses from config. This code can be expanded
        # if a separate 'issuable_bonuses' section appears in YML.
        referrer_bonus = bonus_config.get("referrer_bonus")
        referred_bonus = bonus_config.get("referred_user_bonus")

        if referrer_bonus:
            available_bonuses.append(
                schemas.AvailableBonus(
                    feature_name=referrer_bonus["feature_name"],
                    description=referrer_bonus.get(
                        "description",
                        f"Bonus for referrer: +{referrer_bonus['quantity']} {referrer_bonus['feature_name']}",
                    ),
                    default_quantity=referrer_bonus["quantity"],
                )
            )

        if referred_bonus:
            available_bonuses.append(
                schemas.AvailableBonus(
                    feature_name=referred_bonus["feature_name"],
                    description=referred_bonus.get(
                        "description",
                        f"Bonus for new user: +{referred_bonus['quantity']} {referred_bonus['feature_name']}",
                    ),
                    default_quantity=referred_bonus["quantity"],
                )
            )

        # Remove duplicates if feature_name is identical
        unique_bonuses = {b.feature_name: b for b in available_bonuses}

        return list(unique_bonuses.values())

    except Exception as e:
        # There is already error logging in plans.py, but let's add it here too
        logger.error(
            f"Failed to load available bonuses from config: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail="Could not load available bonuses configuration."
        )


@admin_router.get("/analytics/foundations", response_model=List[schemas.FoundationStat])
async def get_foundation_stats(
    source_type: str = Query(..., enum=["backtest", "live", "paper"]),
    db: AsyncSession = Depends(get_db),
):
    """
    Get foundation effectiveness statistics.
    Admin only.
    """
    stats = await crud.get_foundation_effectiveness_stats(db, source_type=source_type)
    return stats


@admin_router.get(
    "/analytics/market-sentiment", response_model=List[schemas.MarketSentimentStat]
)
async def get_market_sentiment_stats(
    source_type: str = Query(..., enum=["backtest", "live", "paper"]),
    db: AsyncSession = Depends(get_db),
):
    """
    Get market sentiment statistics.
    Admin only.
    """
    stats = await crud.get_market_sentiment(db, source_type=source_type)
    return stats


@admin_router.get("/health/tasks")
async def get_problematic_tasks(db: AsyncSession = Depends(get_db)):
    """
    Get list of problematic tasks (failed in last 24h or stuck running > 60 min).
    Admin only.
    """
    tasks = await crud.get_problematic_tasks(db)
    return {"data": tasks}


@admin_router.get("/health/metrics", response_model=schemas.SystemMetrics)
async def get_system_metrics(
    redis_client: redis.Redis = Depends(get_redis_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Get system-wide performance and health metrics.
    Admin only.
    """
    # TODO: Replace with real metric gathering logic
    return {
        "average_response_time_ms": 22.0,
        "uptime_30_days_percent": 99.98,
        "total_requests_24h": 1234567,
        "error_rate_24h": 0.02,
    }


@admin_router.post("/system/update")
async def trigger_system_update(
    current_user: models.User = Depends(require_admin_role),
):
    """
    Creates .update_trigger file inside /app/data to trigger a host-side git pull and docker rebuild.
    Admin only.
    """
    trigger_file = Path("data/.update_trigger")
    trigger_file.touch(exist_ok=True)
    return {
        "status": "updating",
        "message": "Update triggered. The system will restart in a few seconds.",
    }


@admin_router.get("/logs/errors")
async def get_all_error_logs(
    limit: int = Query(100, ge=1, le=500),
    level: str = Query("ERROR", enum=["ERROR", "WARNING"]),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Get recent error/warning logs from all users.
    Scans all user log histories in Redis and returns errors/warnings.
    Admin only.
    """
    try:
        # Get all user IDs from database
        result = await db.execute(select(models.User.id))
        user_ids = [row[0] for row in result.all()]

        error_logs = []

        # Scan each user's log history
        for user_id in user_ids:
            history_key = f"log_history:{user_id}"
            log_entries_json = await redis_client.lrange(history_key, 0, 99)

            for entry_json in log_entries_json:
                try:
                    log_entry = json.loads(entry_json)
                    # Filter by level (ERROR or WARNING)
                    if (
                        log_entry.get("level") in [level, "ERROR"]
                        if level == "ERROR"
                        else [level]
                    ):
                        log_entry["user_id"] = user_id  # Add user_id to log entry
                        error_logs.append(log_entry)
                except json.JSONDecodeError:
                    continue

        # Sort by timestamp (most recent first)
        error_logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        # Limit results
        error_logs = error_logs[:limit]

        return {"data": error_logs}
    except Exception as e:
        logger.error(f"Failed to retrieve error logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not retrieve error logs.")


# --- Affiliate Program Admin Endpoints ---


@admin_router.get(
    "/affiliates",
    response_model=schemas.PaginatedAdminUsers,
    summary="Get all affiliates with their statistics",
)
async def admin_get_affiliates(
    skip: int = 0, limit: int = 10, db: AsyncSession = Depends(get_db)
):
    """
    Retrieves a paginated list of all users with the 'affiliate' role,
    along with their referral and commission statistics.
    Admin only.
    """
    affiliates, total = await crud.get_affiliates_with_stats(db, skip=skip, limit=limit)

    # Pydantic's from_attributes=True will handle the attached 'stats' attribute
    # when validating against AffiliateWithStats schema.

    return {"total": total, "users": affiliates}


@admin_router.get(
    "/affiliates/{user_id}/commissions",
    response_model=schemas.PaginatedCommissions,
    summary="Get commissions for a specific affiliate",
)
async def admin_get_affiliate_commissions(
    user_id: int, skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)
):
    """
    Retrieves a paginated list of commissions for a specific affiliate.
    Admin only.
    """
    # First, check if the user is actually an affiliate
    user = await crud.admin_get_user_details(db, user_id=user_id)
    if not user or user.role != "affiliate":
        raise HTTPException(status_code=404, detail="Affiliate user not found")

    commissions, total = await crud.get_commissions_for_affiliate(
        db, affiliate_user_id=user_id, skip=skip, limit=limit
    )
    return {"total": total, "commissions": commissions}


@admin_router.get(
    "/affiliates/{user_id}/referrals",
    response_model=schemas.PaginatedAdminAffiliateReferrals,
    summary="Get referrals for a specific affiliate",
)
async def admin_get_affiliate_referrals(
    user_id: int, skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)
):
    """
    Retrieves a paginated list of referred users for a specific affiliate.
    Admin only.
    """
    # First, check if the user is actually an affiliate
    user = await crud.admin_get_user_details(db, user_id=user_id)
    if not user or user.role != "affiliate":
        raise HTTPException(status_code=404, detail="Affiliate user not found")

    users, total = await crud.get_referrals_for_affiliate(
        db, affiliate_user_id=user_id, skip=skip, limit=limit
    )
    return {"total": total, "referrals": users}

PIPELINE_LOG_FILE = Path("logs") / "download_pipeline.log"
_pipeline_process = None

class PipelineStartRequest(BaseModel):
    symbols: str
    data_types: str
    start_date: str = ""
    end_date: str = ""
    timeframes: str = "1m"
    update_only: bool = False
    enrich_only: bool = False
    delete_aggtrades: bool = False

class CatchUpRequest(BaseModel):
    delete_aggtrades: bool = True

@admin_router.post("/data-pipeline/start")
async def start_data_pipeline(req: PipelineStartRequest):
    global _pipeline_process
    
    if _pipeline_process is not None and _pipeline_process.poll() is None:
        raise HTTPException(status_code=400, detail="Pipeline is already running.")
        
    cmd = ["python", "scripts/download_pipeline.py"]
    cmd.extend(["--symbols", req.symbols])
    cmd.extend(["--data-types", req.data_types])
    cmd.extend(["--timeframes", req.timeframes])
    
    if req.update_only:
        cmd.append("--update")
    else:
        if not req.start_date or not req.end_date:
             raise HTTPException(status_code=400, detail="Start and end dates are required unless update_only is true.")
        cmd.extend(["--start-date", req.start_date])
        cmd.extend(["--end-date", req.end_date])
        
    if req.enrich_only:
        cmd.append("--enrich-only")
    if req.delete_aggtrades:
        cmd.append("--delete-aggtrades")
        
    # Ensure log directory exists
    PIPELINE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    log_file = open(PIPELINE_LOG_FILE, "w", encoding="utf-8")
    
    try:
        _pipeline_process = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(Path(__file__).parent.parent.parent.resolve())
        )
    except Exception as e:
        log_file.close()
        raise HTTPException(status_code=500, detail=str(e))
        
    return {"message": "Pipeline started successfully."}

@admin_router.get("/data-pipeline/status")
async def get_data_pipeline_status():
    global _pipeline_process
    
    is_running = _pipeline_process is not None and _pipeline_process.poll() is None
    
    logs = ""
    if PIPELINE_LOG_FILE.exists():
        try:
            with open(PIPELINE_LOG_FILE, "r", encoding="utf-8") as f:
                # Read last 100 lines
                lines = f.readlines()
                logs = "".join(lines[-100:])
        except Exception:
            pass
            
    return {
        "is_running": is_running,
        "logs": logs
    }

@admin_router.post("/data-pipeline/stop")
async def stop_data_pipeline():
    global _pipeline_process
    
    if _pipeline_process is None or _pipeline_process.poll() is not None:
        raise HTTPException(status_code=400, detail="Pipeline is not running.")
        
    _pipeline_process.terminate()
    try:
        _pipeline_process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _pipeline_process.kill()
        
    _pipeline_process = None
    return {"message": "Pipeline stopped."}


@admin_router.get("/data-pipeline/storage-info")
async def get_data_pipeline_storage_info():
    import pyarrow.parquet as pq
    project_root = Path(__file__).parent.parent.parent.resolve()
    base_path = project_root / "data_storage" / "binance" / "futures"
    
    if not base_path.exists():
        return {"symbols": []}
    
    symbols_data = []
    
    for symbol_dir in base_path.iterdir():
        if symbol_dir.is_dir():
            symbol = symbol_dir.name.upper()
            
            # 1. Detect all kline timeframes
            timeframes = []
            klines_1m_info = None
            for f in symbol_dir.glob("kline_*.parquet"):
                tf = f.name.replace("kline_", "").replace(".parquet", "")
                timeframes.append(tf)
                
                # Special check for 1m (main range and enrichment)
                if tf == "1m":
                    try:
                        pfile = pq.ParquetFile(f)
                        # Fast range check from metadata
                        # We still use pandas for index read if metadata is not enough
                        df_index = pd.read_parquet(f, columns=[], engine="pyarrow")
                        if len(df_index) > 0:
                            klines_1m_info = {
                                "start_date": df_index.index[0].date().isoformat(),
                                "end_date": df_index.index[-1].date().isoformat(),
                                "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
                                "is_enriched": "tape_total_count_5s" in pfile.schema.names
                            }
                    except Exception as e:
                        logger.error(f"Error inspecting {f}: {e}")

            info = {
                "symbol": symbol,
                "timeframes": sorted(timeframes),
                "klines_1m": klines_1m_info,
                "has_aggtrades": (symbol_dir / "aggTrade").exists(),
                "has_klines_1s": (symbol_dir / "klines_1s").exists(),
                "has_oi": (symbol_dir / "open_interest.parquet").exists(),
                "has_depth": (symbol_dir / "bookDepth").exists(),
            }
            symbols_data.append(info)
            
    return {"symbols": symbols_data}


@admin_router.post("/data-pipeline/catch-up")
async def catch_up_data_pipeline(req_params: CatchUpRequest):
    info = await get_data_pipeline_storage_info()
    
    # We'll determine data types based on what's already there
    # or just use the full suite for symbols that have at least some data
    target_symbols = [s["symbol"] for s in info["symbols"] if s["klines_1m"] is not None]
    
    if not target_symbols:
        raise HTTPException(status_code=400, detail="No symbols with existing history found.")
    
    # Find global min end_date to decide start point
    min_end_date = None
    for s in info["symbols"]:
        if s["klines_1m"]:
            ed = date.fromisoformat(s["klines_1m"]["end_date"])
            if min_end_date is None or ed < min_end_date:
                min_end_date = ed

    start_date = (min_end_date + timedelta(days=1)).isoformat()
    end_date = (datetime.utcnow().date() - timedelta(days=1)).isoformat()
    
    if start_date > end_date:
        return {"message": "Data is already up to date."}
        
    req = PipelineStartRequest(
        symbols=",".join(target_symbols),
        data_types="klines,aggTrades,open_interest,bookDepth",
        start_date=start_date,
        end_date=end_date,
        timeframes="1m,5m,15m,1h,4h,1d",
        delete_aggtrades=req_params.delete_aggtrades
    )
    return await start_data_pipeline(req)
