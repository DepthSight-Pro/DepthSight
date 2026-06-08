import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

import api.depthsight_api as depthsight_api
from datetime import datetime, timezone
from tasks import celery_app, run_optimization_task

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..redis_client import get_redis_client
from ..plans import plans_config
from ..dependencies import (
    require_permission,
    check_concurrent_task_limit,
    increment_concurrent_task_counter,
)


class ModuleProxy:
    def __init__(self, getattr_fn):
        self._getattr_fn = getattr_fn

    def __getattr__(self, name):
        return getattr(self._getattr_fn(), name)

    def __call__(self, *args, **kwargs):
        return self._getattr_fn()(*args, **kwargs)


crud = ModuleProxy(lambda: depthsight_api.crud)
AsyncResult = ModuleProxy(lambda: depthsight_api.AsyncResult)

logger = logging.getLogger(__name__)

tasks_router = APIRouter(
    prefix="/api/v1",
    tags=["Tasks"],
    dependencies=[Depends(get_current_user)],
)


@tasks_router.get(
    "/tasks/all", response_model=schemas.ApiResponseData[schemas.PaginatedTasksResponse]
)
async def get_all_tasks(
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) listing all tasks (page: {page}, page_size: {page_size})."
    )
    skip = (page - 1) * page_size
    db_tasks, total_count = await crud.get_tasks_by_user(
        db, user_id=current_user.id, skip=skip, limit=page_size
    )

    response_tasks = []
    for task_in_db in db_tasks:
        celery_result = AsyncResult(task_in_db.task_id, app=celery_app)
        live_status = celery_result.state

        # If Celery reports PENDING, but the DB has a final state, trust the DB.
        final_status = live_status
        if live_status == "PENDING" and task_in_db.status in [
            "COMPLETED",
            "SUCCESS",
            "FAILURE",
            "STOPPED",
        ]:
            final_status = task_in_db.status

        progress_info_payload = None
        if (
            celery_result.state == "PROGRESS"
            and celery_result.info
            and isinstance(celery_result.info, dict)
        ):
            progress_data = celery_result.info.get("progress_info")
            if progress_data:
                try:
                    progress_info_payload = schemas.ProgressInfo(**progress_data)
                except Exception as e_parse:
                    logger.error(
                        f"Failed to parse progress_info for task {task_in_db.task_id} in /tasks/all: {e_parse}. Data: {progress_data}"
                    )
        response_task_data = schemas.TaskStatusResponse(
            task_id=task_in_db.task_id,
            status=final_status,  # Use the corrected status
            submitted_at=task_in_db.submitted_at,
            request_params=task_in_db.parameters,
            progress_info=progress_info_payload,
            results=task_in_db.results,
            error_message=task_in_db.error_message,
            completed_at=task_in_db.completed_at,
        )
        response_tasks.append(response_task_data)
    return {"data": {"tasks": response_tasks, "total": total_count}}


@tasks_router.get(
    "/tasks/{task_id}",
    response_model=schemas.ApiResponseData[schemas.TaskStatusResponse],
)
async def get_task_status_endpoint(
    task_id: str,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) requesting status for task {task_id}."
    )
    db_task = await crud.get_task(db=db, user_id=current_user.id, task_id=task_id)
    if not db_task:
        logger.warning(
            f"User '{current_user.username}' (ID: {current_user.id}) - Task {task_id} not found in DB."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found in DB"
        )

    celery_result = AsyncResult(task_id, app=celery_app)
    live_celery_status = celery_result.state

    response_data_dict = {
        "task_id": db_task.task_id,
        "status": live_celery_status,
        "submitted_at": db_task.submitted_at,
        "request_params": db_task.parameters,
        "completed_at": db_task.completed_at,
        "error_message": db_task.error_message,
        "results": db_task.results,
        "progress_info": None,
    }

    if (
        live_celery_status == "PROGRESS"
        and celery_result.info
        and isinstance(celery_result.info, dict)
    ):
        progress_data_raw = celery_result.info.get("progress_info")
        if progress_data_raw:
            try:
                if db_task.task_type == "optimization":
                    response_data_dict["progress_info"] = (
                        schemas.OptimizationProgressInfo(**progress_data_raw)
                    )
                    logger.debug(
                        f"Task {task_id} (optimization) progress parsed: {response_data_dict['progress_info']}"
                    )
                elif db_task.task_type == "backtest":
                    response_data_dict["progress_info"] = schemas.ProgressInfo(
                        **progress_data_raw
                    )  # Assuming ProgressInfo for backtest
                    logger.debug(
                        f"Task {task_id} (backtest) progress parsed: {response_data_dict['progress_info']}"
                    )
                elif (
                    db_task.task_type == "genetic_search"
                ):  # Assuming GeneticRunProgress for genetic_search task type
                    response_data_dict["progress_info"] = schemas.GeneticRunProgress(
                        **progress_data_raw
                    )
                    logger.debug(
                        f"Task {task_id} (genetic_search) progress parsed: {response_data_dict['progress_info']}"
                    )
                else:
                    logger.warning(
                        f"Task {task_id} has unknown task_type '{db_task.task_type}' for progress parsing. Raw progress: {progress_data_raw}"
                    )
            except Exception as e_parse:
                logger.error(
                    f"Failed to parse progress_info for task {task_id} (type: {db_task.task_type}): {e_parse}. Raw Data: {progress_data_raw}",
                    exc_info=True,
                )

    if (
        live_celery_status in ["SUCCESS", "FAILURE"]
        and db_task.status != live_celery_status
    ):
        logger.info(
            f"Task {task_id} (type: {db_task.task_type}) state mismatch. Celery: {live_celery_status}, DB: {db_task.status}. Syncing..."
        )
        results_from_celery = (
            celery_result.result if live_celery_status == "SUCCESS" else None
        )
        error_from_celery = (
            str(celery_result.info) if live_celery_status == "FAILURE" else None
        )

        if results_from_celery is not None and not isinstance(
            results_from_celery, dict
        ):
            logger.warning(
                f"Task {task_id}: Celery results are not a dict: {type(results_from_celery)}. Storing as is or converting if possible."
            )

        await crud.update_task_status(
            db, task_id, live_celery_status, results_from_celery, error_from_celery
        )
        await db.commit()

        response_data_dict["status"] = live_celery_status
        response_data_dict["results"] = results_from_celery
        response_data_dict["error_message"] = error_from_celery
        response_data_dict["completed_at"] = datetime.now(timezone.utc)
        logger.info(f"Task {task_id} DB status synced to {live_celery_status}.")

    return {"data": schemas.TaskStatusResponse(**response_data_dict)}


@tasks_router.post(
    "/optimizations",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=schemas.ApiResponseData,
    summary="Start optimization",
    dependencies=[
        Depends(require_permission("run_optimization")),
        Depends(check_concurrent_task_limit("run_optimization")),
    ],
)
async def run_optimization(
    request: schemas.OptimizationRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) started optimization: {request.strategy_name} for symbol {request.symbol}."
    )

    user_plan = plans_config.get_plan(current_user.plan)
    limits = user_plan.get("limits", {})
    priority = limits.get("celery_task_priority", 9)

    try:
        celery_task = run_optimization_task.apply_async(
            args=[request.model_dump(), current_user.id], priority=priority
        )
        await increment_concurrent_task_counter(current_user.id, redis_client)
        logger.info(
            f"Optimization task {celery_task.id} queued for user '{current_user.username}' (ID: {current_user.id}) with priority {priority}."
        )
        return {"data": {"task_id": celery_task.id, "status": "pending"}}
    except Exception as e:
        logger.error(
            f"User '{current_user.username}' (ID: {current_user.id}) - Failed to queue optimization task for {request.strategy_name}. Error: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to queue optimization task: {str(e)}",
        )


@tasks_router.get(
    "/optimizations/{task_id}",
    response_model=schemas.ApiResponseData[schemas.TaskStatusResponse],
    summary="Optimization task status",
)
async def get_optimization_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) requested status for optimization task {task_id}."
    )
    db_task = await crud.get_task(db=db, user_id=current_user.id, task_id=task_id)
    if not db_task:
        logger.warning(
            f"User '{current_user.username}' (ID: {current_user.id}) - Optimization task {task_id} not found in DB."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Optimization task not found in DB",
        )

    celery_result = AsyncResult(task_id, app=celery_app)
    live_celery_status = celery_result.state

    response_data_dict = {
        "task_id": db_task.task_id,
        "status": live_celery_status,
        "submitted_at": db_task.submitted_at,
        "request_params": db_task.parameters,
        "completed_at": db_task.completed_at,
        "error_message": db_task.error_message,
        "results": db_task.results,
        "progress_info": None,
    }

    if (
        live_celery_status == "PROGRESS"
        and celery_result.info
        and isinstance(celery_result.info, dict)
    ):
        progress_data_raw = celery_result.info.get("progress_info")
        if progress_data_raw:
            try:
                response_data_dict["progress_info"] = schemas.OptimizationProgressInfo(
                    **progress_data_raw
                )
                logger.debug(
                    f"Optimization task {task_id} progress parsed: {response_data_dict['progress_info']}"
                )
            except Exception as e_parse:
                logger.error(
                    f"User '{current_user.username}' (ID: {current_user.id}) - Failed to parse OptimizationProgressInfo for optimization task {task_id}: {e_parse}. Raw Data: {progress_data_raw}",
                    exc_info=True,
                )

    if (
        live_celery_status in ["SUCCESS", "FAILURE"]
        and db_task.status != live_celery_status
    ):
        logger.info(
            f"Optimization task {task_id} for user '{current_user.username}' (ID: {current_user.id}): Celery status ({live_celery_status}) differs from DB ({db_task.status}). Syncing DB."
        )
        commit_needed = False
        if live_celery_status == "SUCCESS":
            final_celery_results = celery_result.result
            await crud.update_task_status(
                db, task_id, live_celery_status, final_celery_results, None
            )
            response_data_dict["results"] = final_celery_results
            response_data_dict["error_message"] = None
            response_data_dict["completed_at"] = datetime.now(timezone.utc)
            commit_needed = True
        elif live_celery_status == "FAILURE":
            error_msg_from_celery = str(celery_result.info)
            await crud.update_task_status(
                db, task_id, live_celery_status, None, error_msg_from_celery
            )
            response_data_dict["error_message"] = error_msg_from_celery
            response_data_dict["results"] = None
            response_data_dict["completed_at"] = datetime.now(timezone.utc)
            commit_needed = True
        if commit_needed:
            await db.commit()
            response_data_dict["status"] = live_celery_status
    return {"data": schemas.TaskStatusResponse(**response_data_dict)}
