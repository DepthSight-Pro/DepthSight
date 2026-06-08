import logging
import uuid
from typing import List

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from .. import crud, models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..redis_client import get_redis_client
from ..dependencies import (
    require_permission,
    check_concurrent_task_limit,
    check_usage_quota,
    increment_concurrent_task_counter,
    increment_usage_quota,
)
from ..plans import plans_config
from bot_module import config as bot_config
from tasks import celery_app, run_genetic_search_task
from celery.result import AsyncResult

logger = logging.getLogger(__name__)


# Rate limiting fallback
def get_limit_value(val: str) -> str:
    return val


# Mock limiter if not available in context
class MockLimiter:
    def limit(self, *args, **kwargs):
        return lambda func: func


limiter = MockLimiter()

discovery_router = APIRouter(
    prefix="/api/v1/discovery",
    tags=["Discovery"],
    dependencies=[Depends(get_current_user)],
)


@discovery_router.get("/system-resources")
async def get_system_resources(
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get server resource usage and queue status for genetic algorithm runs.
    Returns CPU usage, RAM usage, and queue information.
    """
    import psutil

    # Get system metrics
    cpu_count = psutil.cpu_count(logical=True)
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()

    # Get queue status - count pending/running genetic runs
    running_count = await db.scalar(
        select(func.count(models.GeneticRun.id)).where(
            models.GeneticRun.status == "RUNNING"
        )
    )
    pending_count = await db.scalar(
        select(func.count(models.GeneticRun.id)).where(
            models.GeneticRun.status == "PENDING"
        )
    )

    # Get configuration from bot_module.config
    max_concurrent_runs = bot_config.GENETIC_MAX_CONCURRENT_RUNS
    cores_per_run = bot_config.GENETIC_CORES_PER_RUN

    return {
        "system": {
            "cpu_count": cpu_count,
            "cpu_percent": round(cpu_percent, 1),
            "ram_total_gb": round(memory.total / (1024**3), 1),
            "ram_used_gb": round(memory.used / (1024**3), 1),
            "ram_available_gb": round(memory.available / (1024**3), 1),
            "ram_percent": memory.percent,
        },
        "queue": {
            "running": running_count or 0,
            "pending": pending_count or 0,
            "max_concurrent": max_concurrent_runs,
            "cores_per_run": cores_per_run,
            "total_allocated_cores": (running_count or 0) * cores_per_run,
        },
        "user_position": {
            # Position in queue for current user (if they have pending runs)
            "has_pending": False,  # TODO: implement user-specific queue position
            "estimated_wait_minutes": 0,
        },
    }


@discovery_router.post(
    "/runs",
    response_model=schemas.GeneticRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_permission("run_genetic_search")),
        Depends(check_concurrent_task_limit("run_genetic_search")),
        Depends(check_usage_quota("run_genetic_search")),
    ],
)
@limiter.limit(
    get_limit_value("genetic")
)  # Most resource-intensive operation - strict limit
async def create_genetic_run_endpoint(
    request: Request,  # Required for slowapi
    run_create: schemas.GeneticRunCreate,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) creating new genetic run with config: {run_create.config_json}"
    )

    user_plan = plans_config.get_plan(current_user.plan)
    limits = user_plan.get("limits", {})
    priority = limits.get("celery_task_priority", 9)

    try:
        db_run = await crud.create_genetic_run(
            db=db,
            user_id=current_user.id,
            config_json=run_create.config_json,
            initial_status="PENDING",
        )
        # CRITICAL: Commit the transaction BEFORE dispatching Celery task
        # This ensures the GeneticRun record exists when the worker looks for it
        await db.commit()
        await db.refresh(db_run)

        # Now dispatch the Celery task (record is guaranteed to exist)
        celery_task_handle = run_genetic_search_task.apply_async(
            args=[str(db_run.id), current_user.id], priority=priority
        )
        await increment_concurrent_task_counter(current_user.id, redis_client)
        await increment_usage_quota(current_user.id, "run_genetic_search", redis_client)

        # Update the record with Celery task ID
        db_run.celery_task_id = celery_task_handle.id
        await db.commit()

        logger.info(
            f"User '{current_user.username}' (ID: {current_user.id}) - Genetic run {db_run.id} created and task {celery_task_handle.id} dispatched with priority {priority}."
        )
        return schemas.GeneticRunResponse.model_validate(db_run)
    except Exception as e:
        logger.error(
            f"User '{current_user.username}' (ID: {current_user.id}) - Failed to create genetic run: {e}",
            exc_info=True,
        )
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create genetic run: {str(e)}",
        )


@discovery_router.get("/runs", response_model=List[schemas.GeneticRunResponse])
async def list_genetic_runs(
    skip: int = 0,
    limit: int = 100,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) listing their genetic runs (skip: {skip}, limit: {limit})."
    )
    db_runs = await crud.get_genetic_runs_for_user(
        db=db, user_id=current_user.id, skip=skip, limit=limit
    )
    return [schemas.GeneticRunResponse.model_validate(run) for run in db_runs]


@discovery_router.get("/runs/{run_id}", response_model=schemas.GeneticRunResponse)
async def get_genetic_run_details(
    run_id: str,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) requesting details for genetic run {run_id}."
    )
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid run_id format: '{run_id}' is not a valid UUID.",
        )

    db_run = await crud.get_genetic_run(db=db, run_id=run_id, user_id=current_user.id)
    if not db_run:
        logger.warning(
            f"User '{current_user.username}' (ID: {current_user.id}) - Genetic run {run_id} not found."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Genetic run not found"
        )

    response_data = schemas.GeneticRunResponse.model_validate(db_run)

    if response_data.status in ["RUNNING", "PENDING"] and response_data.celery_task_id:
        try:
            task_result = AsyncResult(response_data.celery_task_id, app=celery_app)
            if (
                task_result.state == "PROGRESS"
                and task_result.info
                and isinstance(task_result.info, dict)
            ):
                progress_data_raw = task_result.info.get("progress_info")
                if progress_data_raw:
                    try:
                        live_progress = schemas.GeneticRunProgress(**progress_data_raw)
                        response_data.progress = live_progress
                        logger.debug(
                            f"User '{current_user.username}' (ID: {current_user.id}) - Fetched and applied live Celery progress for run {run_id}: {response_data.progress.model_dump_json(exclude_none=True)}"
                        )
                    except Exception as e_parse_live:
                        logger.error(
                            f"User '{current_user.username}' (ID: {current_user.id}) - Failed to parse live Celery progress for run {run_id}: {e_parse_live}. Raw: {progress_data_raw}",
                            exc_info=True,
                        )
                else:
                    logger.debug(
                        f"User '{current_user.username}' (ID: {current_user.id}) - Celery task {response_data.celery_task_id} is PROGRESS but 'progress_info' field is missing in meta for run {run_id}."
                    )

            if task_result.state in ["SUCCESS", "FAILURE"] and db_run.status not in [
                "COMPLETED",
                "FAILED",
                "STOPPED",
            ]:
                logger.info(
                    f"GeneticRun {run_id} state mismatch. Celery: {task_result.state}, DB: {db_run.status}. Syncing..."
                )
                new_status = "COMPLETED" if task_result.state == "SUCCESS" else "FAILED"
                error_msg = (
                    str(task_result.info) if task_result.state == "FAILURE" else None
                )

                updated_run = await crud.update_genetic_run_status(
                    db, run_id, new_status, error_message=error_msg
                )
                await db.commit()

                if updated_run:
                    response_data = schemas.GeneticRunResponse.model_validate(
                        updated_run
                    )
                    logger.info(
                        f"GeneticRun {run_id} DB status synced to {new_status}."
                    )
                else:
                    logger.error(
                        f"Failed to update and refresh GeneticRun {run_id} after Celery sync."
                    )

            elif db_run.status == "RUNNING" and task_result.state not in [
                "PROGRESS",
                "PENDING",
                "SUCCESS",
                "FAILURE",
            ]:
                logger.warning(
                    f"User '{current_user.username}' (ID: {current_user.id}) - DB run {run_id} is RUNNING, but Celery task {response_data.celery_task_id} is {task_result.state}. Status might be stale or task interrupted."
                )
        except Exception as e_celery:
            logger.error(
                f"User '{current_user.username}' (ID: {current_user.id}) - Error checking Celery status for task {response_data.celery_task_id} (run {run_id}): {e_celery}",
                exc_info=True,
            )

    return response_data


@discovery_router.post(
    "/runs/{run_id}/stop", response_model=schemas.GeneticRunStatusResponse
)
async def stop_genetic_run(
    run_id: str,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) attempting to stop genetic run {run_id}."
    )
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid run_id format: '{run_id}' is not a valid UUID.",
        )

    db_run = await crud.get_genetic_run(db=db, run_id=run_id, user_id=current_user.id)
    if not db_run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Genetic run not found"
        )

    if db_run.status in ["COMPLETED", "FAILED", "STOPPED"]:
        logger.info(
            f"User '{current_user.username}' (ID: {current_user.id}) - Genetic run {run_id} is already in a final state: {db_run.status}."
        )
        return schemas.GeneticRunStatusResponse(
            run_id=db_run.id,
            status=db_run.status,
            celery_task_id=db_run.celery_task_id,
            message="Run already in a final state.",
        )

    if not db_run.celery_task_id:
        logger.warning(
            f"User '{current_user.username}' (ID: {current_user.id}) - Cannot stop genetic run {run_id}: No Celery task ID associated."
        )
        updated_run_no_task = await crud.update_genetic_run_status(
            db=db,
            run_id=run_id,
            status="STOPPED",
            error_message="Stopped: No Celery task ID found to revoke.",
        )
        await db.commit()
        if updated_run_no_task:
            return schemas.GeneticRunStatusResponse(
                run_id=updated_run_no_task.id,
                status=updated_run_no_task.status,
                celery_task_id=updated_run_no_task.celery_task_id,
                message="Run marked as STOPPED (no task ID).",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run has no associated task ID to stop.",
        )

    try:
        celery_app.control.revoke(
            db_run.celery_task_id, terminate=True, signal="SIGUSR1"
        )
        logger.info(
            f"User '{current_user.username}' (ID: {current_user.id}) - Revoke command sent for Celery task {db_run.celery_task_id} of genetic run {run_id}."
        )
    except Exception as e_revoke:
        logger.error(
            f"User '{current_user.username}' (ID: {current_user.id}) - Failed to send revoke command for task {db_run.celery_task_id} (run {run_id}): {e_revoke}",
            exc_info=True,
        )

    updated_run = await crud.update_genetic_run_status(
        db=db,
        run_id=run_id,
        status="STOPPED",
        error_message="Manually stopped by user.",
    )
    await db.commit()
    if not updated_run:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update run status after stop attempt.",
        )

    return schemas.GeneticRunStatusResponse(
        run_id=updated_run.id,
        status=updated_run.status,
        celery_task_id=updated_run.celery_task_id,
        message="Stop command issued; run status updated to STOPPED.",
    )


@discovery_router.get(
    "/runs/{run_id}/results", response_model=List[schemas.FoundStrategyResponse]
)
async def get_genetic_run_results(
    run_id: str,
    limit: int = Query(10, ge=1, le=100),
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) requesting results for genetic run {run_id} (limit: {limit})."
    )
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid run_id format: '{run_id}' is not a valid UUID.",
        )

    db_run = await crud.get_genetic_run(db=db, run_id=run_id, user_id=current_user.id)
    if not db_run:
        logger.warning(
            f"User '{current_user.username}' (ID: {current_user.id}) - Genetic run {run_id} not found when trying to fetch results."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Genetic run not found"
        )

    found_strategies = await crud.get_found_strategies_for_run(
        db=db, run_id=run_id, limit=limit
    )
    return [schemas.FoundStrategyResponse.model_validate(fs) for fs in found_strategies]
