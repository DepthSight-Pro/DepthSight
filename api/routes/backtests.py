import logging
import os
from datetime import datetime, timezone
import api.depthsight_api as depthsight_api
from typing import List, Optional, Any

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from celery.result import AsyncResult

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..redis_client import get_redis_client
from ..plans import plans_config
from ..dependencies import (
    require_permission,
    check_concurrent_task_limit,
    check_usage_quota,
    increment_concurrent_task_counter,
    increment_usage_quota,
    is_strategy_kline_only,
)
from tasks import celery_app, run_backtest_task


class ModuleProxy:
    def __init__(self, getattr_fn):
        self._getattr_fn = getattr_fn

    def __getattr__(self, name):
        return getattr(self._getattr_fn(), name)

    def __call__(self, *args, **kwargs):
        return self._getattr_fn()(*args, **kwargs)


crud = ModuleProxy(lambda: depthsight_api.crud)
data_loader = ModuleProxy(lambda: depthsight_api.data_loader)
grant_achievement = ModuleProxy(lambda: depthsight_api.grant_achievement)


# Rate limiting fallback
def get_limit_value(val: str) -> str:
    return val


# Mock limiter if not available in context
class MockLimiter:
    def limit(self, *args, **kwargs):
        return lambda func: func


limiter = MockLimiter()

logger = logging.getLogger(__name__)

backtests_router = APIRouter(
    prefix="/api/v1/backtests",
    tags=["Backtests"],
    dependencies=[Depends(get_current_user)],
)


@backtests_router.get(
    "/{run_id}/klines",
    response_model=schemas.ApiResponseData[List[List[Any]]],
    summary="Get Klines used in a specific backtest",
)
async def get_backtest_klines(
    run_id: str,
    timeframe: str = Query(..., description="Candle timeframe, e.g. '1m', '15m'"),
    start_time: Optional[float] = Query(
        None, description="Start timestamp in milliseconds (optional)"
    ),
    end_time: Optional[float] = Query(
        None, description="End timestamp in milliseconds (optional)"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Loads and returns historical data (klines) for a specific backtest run.
    Can accept optional time frames to load only part of the data.
    """
    logger.info(
        f"User '{current_user.username}' requesting klines for backtest {run_id} ({timeframe})"
    )

    db_run = await crud.get_backtest_run_by_any_id(
        db, user_id=current_user.id, identity=run_id
    )
    if not db_run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Backtest run not found"
        )

    # Original time frames of the entire backtest
    run_start_dt = db_run.start_date
    run_end_dt = db_run.end_date

    # By default, use the full range of the backtest
    final_start_dt = run_start_dt
    final_end_dt = run_end_dt

    if start_time:
        # Convert timestamp from request to datetime
        final_start_dt = datetime.fromtimestamp(start_time / 1000, tz=timezone.utc)
        logger.debug(
            f"Request start_time provided. Final start set to {final_start_dt}"
        )

    if end_time:
        # Convert timestamp from request to datetime and select the earlier date
        req_end_dt = datetime.fromtimestamp(end_time / 1000, tz=timezone.utc)
        final_end_dt = req_end_dt
        logger.debug(f"Request end_time provided. Final end set to {final_end_dt}")

    try:
        # Added await keyword
        klines_df = await data_loader.download_klines(
            symbol=db_run.symbol,
            timeframe=timeframe,
            start_dt=final_start_dt,
            end_dt=final_end_dt,
            market_type=db_run.market_type,
        )

        # Now klines_df will be a real DataFrame, and this check will succeed
        if klines_df is None or klines_df.empty:
            return {"data": []}

        df_for_json = klines_df[["open", "high", "low", "close", "volume"]].copy()
        df_for_json.index = df_for_json.index.astype("int64") // 1_000_000
        df_for_json.reset_index(inplace=True)
        klines_list = df_for_json.values.tolist()

        return {"data": klines_list}

    except Exception as e:
        logger.error(f"Failed to load klines for backtest {run_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve kline data.",
        )


@backtests_router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=schemas.ApiResponse,
    dependencies=[Depends(require_permission("run_backtest"))],
)
@limiter.limit(
    get_limit_value("backtest")
)  # Protection against resource-intensive tasks abuse
async def run_backtest(
    request: Request,  # Required for slowapi - must be named exactly 'request'
    backtest_request: schemas.BacktestRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    from ..depthsight_api import (
        _check_symbol_permissions,
        _check_intracandle_trigger_permission,
        _enforce_strategy_plan_restrictions,
        _enforce_backtest_engine_access,
    )

    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) submitting backtest: {backtest_request.strategy_name} for {backtest_request.symbol}"
    )

    symbols_to_check = [
        s.strip().upper() for s in backtest_request.symbol.split(",") if s.strip()
    ]
    await _check_symbol_permissions(current_user, symbols_to_check)

    if backtest_request.params and "config_data" in backtest_request.params:
        _check_intracandle_trigger_permission(
            current_user, backtest_request.params["config_data"]
        )

    user_plan = plans_config.get_plan(current_user.plan)
    limits = user_plan.get("limits", {})

    duration_limit = limits.get("max_backtest_duration_days")
    if duration_limit is not None and duration_limit != -1:
        start_dt = datetime.fromisoformat(backtest_request.start_date.replace("Z", ""))
        end_dt = datetime.fromisoformat(backtest_request.end_date.replace("Z", ""))
        duration_days = (end_dt - start_dt).days
        if duration_days > duration_limit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Backtest duration ({duration_days} days) exceeds your plan's limit of {duration_limit} days.",
            )

    priority = limits.get("celery_task_priority", 9)

    logger.info(
        f"Backtest request data for user {current_user.id}: {backtest_request.model_dump()}"
    )

    try:
        engine = schemas.normalize_backtest_engine(
            backtest_request.params.get("backtest_engine")
            if backtest_request.params
            else None,
            default="vector",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    strategy_payload = backtest_request.params or {}
    _enforce_strategy_plan_restrictions(strategy_payload, current_user)
    _enforce_backtest_engine_access(current_user, engine)

    # If standard/free user tries to use PRO strategy blocks
    if False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This strategy contains elements available on the PRO plan only.",
        )

    # Tier-based backend validation for KLINE ONLY blocks (Vector doesn't support them)
    is_kline_only = is_strategy_kline_only(strategy_payload)

    # If pro user tries to use Vector Engine with KLINE_ONLY strategy blocks
    if is_kline_only and engine == "vector":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Turbo engine does not support some blocks of your strategy. Please use Precision engine instead.",
        )

    quota_feature = f"run_{engine}_backtest"

    # Dynamic dependency checks
    concurrent_dep = check_concurrent_task_limit(
        "run_backtest"
    )  # Concurrent limit can remain global for backtests
    await concurrent_dep(current_user, redis_client)

    usage_dep = check_usage_quota(quota_feature)
    await usage_dep(current_user, redis_client)

    try:
        celery_task = run_backtest_task.apply_async(
            args=[backtest_request.model_dump(), current_user.id], priority=priority
        )
        # Increment counter ONLY after successful task launch
        await increment_concurrent_task_counter(current_user.id, redis_client)
        # Increment daily usage quota for the specific engine
        await increment_usage_quota(current_user.id, quota_feature, redis_client)

        logger.info(
            f"Backtest task {celery_task.id} queued for user '{current_user.username}' (ID: {current_user.id}) with priority {priority}"
        )
        return {"data": {"task_id": celery_task.id, "status": "pending"}}
    except Exception as e:
        # If task was not started, counter was not incremented, do nothing
        logger.error(
            f"Failed to queue backtest task for user {current_user.id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to queue backtest task: {str(e)}",
        )


@backtests_router.get(
    "",
    response_model=schemas.ApiResponseData[List[schemas.BacktestRunListItem]],
)
async def list_backtests(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) listing backtest runs."
    )
    db_runs = await crud.get_all_backtest_runs_for_user(db, user_id=current_user.id)
    response_items = []
    if db_runs:
        for run in db_runs:
            pnl = None
            win_rate = None
            if run.kpi_results_json:
                pnl = run.kpi_results_json.get("total_pnl")
                win_rate = run.kpi_results_json.get("win_rate")
            item = schemas.BacktestRunListItem(
                id=run.id,
                task_id=run.task_id or "N/A",
                strategy_name=run.strategy_name,
                symbol=run.symbol,
                status=run.status,
                created_at=run.created_at,
                completed_at=run.completed_at,
                pnl=pnl,
                win_rate=win_rate,
            )
            response_items.append(item)
    return {"data": response_items}


@backtests_router.get(
    "/{run_id}",
    response_model=schemas.ApiResponseData[schemas.BacktestRunDetails],
)
async def get_backtest_details(
    run_id: str,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) fetching details for backtest run/task {run_id}"
    )

    db_run = await crud.get_backtest_run_by_any_id(
        db, user_id=current_user.id, identity=run_id
    )

    if not db_run:
        task_in_db = await crud.get_task(db, user_id=current_user.id, task_id=run_id)
        if not task_in_db:
            logger.warning(
                f"User '{current_user.username}' (ID: {current_user.id}) - Backtest run or task {run_id} not found."
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Backtest run not found"
            )

        empty_run_details = schemas.BacktestRunDetails(
            id=run_id,
            task_id=task_in_db.task_id,
            strategy_name=task_in_db.parameters.get("strategy_name", "N/A"),
            symbol=task_in_db.parameters.get("symbol", "N/A"),
            status=task_in_db.status,
            created_at=task_in_db.submitted_at,
            start_date=task_in_db.parameters.get("start_date"),
            end_date=task_in_db.parameters.get("end_date"),
            initial_balance=task_in_db.parameters.get("initial_balance", 0),
            parameters_json=task_in_db.parameters,
            trades=[],
        )
        return {"data": empty_run_details}

    for trade in db_run.trades:
        trade.symbol = db_run.symbol
        trade.strategy_name = db_run.strategy_name

    response_data = schemas.BacktestRunDetails.model_validate(db_run)
    
    # Try to populate tick_size from parameters_json if it's there
    if not response_data.tick_size and db_run.parameters_json:
        response_data.tick_size = db_run.parameters_json.get("tick_size")
    
    # If still not there, maybe it's in kpi_results_json
    if not response_data.tick_size and db_run.kpi_results_json:
        response_data.tick_size = db_run.kpi_results_json.get("tick_size")

    if response_data.status in ["PENDING", "RUNNING"] and response_data.task_id:
        try:
            celery_result = AsyncResult(response_data.task_id, app=celery_app)
            if (
                celery_result.state == "PROGRESS"
                and celery_result.info
                and isinstance(celery_result.info, dict)
            ):
                progress_info_data = celery_result.info.get("progress_info")
                if progress_info_data and hasattr(response_data, "progress_info"):
                    try:
                        # This line will now receive correct data and won't raise an error
                        response_data.progress_info = schemas.ProgressInfo(
                            **progress_info_data
                        )
                    except Exception as e_parse:
                        logger.error(
                            f"Failed to parse progress_info for task {response_data.task_id}: {e_parse}. Data: {progress_info_data}"
                        )
            if (
                celery_result.state in ["SUCCESS", "FAILURE"]
                and response_data.status != celery_result.state
            ):
                logger.info(
                    f"Celery task {response_data.task_id} has final state {celery_result.state}, DB state is {response_data.status}. Syncing DB for run {run_id}."
                )
                if celery_result.state == "SUCCESS":
                    final_results = celery_result.result
                    if final_results and isinstance(final_results, dict):
                        kpi = final_results.get("kpi_results")
                        equity = final_results.get("equity_curve")
                        await crud.update_backtest_run_results(
                            db, run_id=db_run.id, kpi_results=kpi, equity_curve=equity
                        )
                        await crud.update_task_status(
                            db, db_run.task_id, "COMPLETED", final_results, None
                        )
                    else:
                        logger.warning(
                            f"Celery task {db_run.task_id} for run {run_id} succeeded but returned no/invalid results: {final_results}"
                        )
                        await crud.update_backtest_run_status(
                            db,
                            run_id=db_run.id,
                            status="COMPLETED",
                            error_message="Celery task succeeded but results were not in the expected format.",
                        )
                        await crud.update_task_status(
                            db,
                            db_run.task_id,
                            "COMPLETED",
                            {
                                "detail": "Celery task succeeded but results were not in the expected format."
                            },
                            None,
                        )
                elif celery_result.state == "FAILURE":
                    error_msg = str(celery_result.info)
                    await crud.update_backtest_run_status(
                        db, run_id=db_run.id, status="FAILED", error_message=error_msg
                    )
                    await crud.update_task_status(
                        db, db_run.task_id, "FAILED", None, error_msg
                    )
                await db.commit()
                refreshed_db_run = await crud.get_backtest_run_with_trades(
                    db, user_id=current_user.id, run_id=run_id
                )
                if refreshed_db_run:
                    response_data = schemas.BacktestRunDetails.model_validate(
                        refreshed_db_run
                    )
                else:
                    logger.error(
                        f"Failed to refresh db_run {run_id} for user '{current_user.username}' (ID: {current_user.id}) after Celery sync."
                    )
        except Exception as e_celery:
            logger.error(
                f"Error checking Celery status for task {response_data.task_id} (run {run_id}): {e_celery}"
            )
    return {"data": response_data}


@backtests_router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backtest(
    run_id: str,  # run_id here is the task_id from URL
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) attempting to delete task with ID: {run_id}."
    )

    deleted_item = await crud.delete_backtest_run(
        db, user_id=current_user.id, task_id_to_delete=run_id
    )

    if not deleted_item:
        logger.warning(
            f"User '{current_user.username}' (ID: {current_user.id}) - Failed to delete item {run_id}. Not found or not authorized."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )

    await db.commit()
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) successfully deleted item {run_id}."
    )
    return None


@backtests_router.post(
    "/{run_id}/share",
    response_model=schemas.ApiResponseData[schemas.ShareResponseData],
    summary="Create public link to backtest result",
)
async def create_shareable_backtest_link(
    run_id: str,
    share_data: schemas.ShareCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    from ..depthsight_api import _validate_backtest_for_leaderboard

    """
    Creates or returns an existing public link for a specific backtest result.
    If specified, performs validation and adds the result to the leaderboard candidates.
    """
    # 1. Check that the backtest exists, is completed and belongs to the user
    backtest_run = await crud.get_backtest_run(
        db, run_id=run_id, user_id=current_user.id
    )
    if not backtest_run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backtest run not found or you do not have permission to share it.",
        )

    if backtest_run.status != "COMPLETED" or not backtest_run.kpi_results_json:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot share an incomplete backtest.",
        )

    # 2. Create or update the link record in the DB. This must be done before the leaderboard
    # to obtain the 'public_slug' for association.
    shared_backtest = await crud.create_or_update_shared_backtest(
        db, run_id=run_id, user_id=current_user.id, settings=share_data
    )
    # Use flush to get the object without committing the transaction
    await db.flush()
    await db.refresh(shared_backtest)

    # 3. If user wants to publish in leaderboard, perform validation
    if share_data.publish_to_leaderboard:
        logger.info(
            f"User {current_user.id} attempting to publish backtest {run_id} to leaderboard."
        )

        # This function will raise HTTPException if validation fails
        await _validate_backtest_for_leaderboard(backtest_run)

        # If validation succeeds, create a candidate entry in the leaderboard.
        # Rank will be updated by a periodic task.
        await crud.create_leaderboard_entry(
            db,
            user_id=current_user.id,
            backtest_run=backtest_run,
            shared_backtest_slug=shared_backtest.public_slug,
        )
        logger.info(
            f"Backtest {run_id} passed validation and was added as a leaderboard candidate."
        )
        await grant_achievement(db, current_user.id, "contender")

    # 4. Save all changes in the DB
    await db.commit()
    await db.refresh(shared_backtest)

    # Grant 'show_off' achievement
    await grant_achievement(db, current_user.id, "show_off")

    # 5. Form URL
    frontend_url = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")
    share_url = f"{frontend_url}/s/{shared_backtest.public_slug}"

    # 6. Return response
    response_data = schemas.ShareResponseData(
        shareUrl=share_url, publicSlug=shared_backtest.public_slug
    )
    return {"data": response_data}
