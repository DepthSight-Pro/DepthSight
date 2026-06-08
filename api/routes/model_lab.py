import json
import logging
import os
from pathlib import Path
from typing import Any, List

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..dependencies import (
    check_concurrent_task_limit,
    increment_concurrent_task_counter,
    require_permission,
)
from ..plans import plans_config
from ..redis_client import get_redis_client


logger = logging.getLogger(__name__)


def create_model_lab_router(
    generate_dataset_task: Any, train_model_task: Any
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/model-lab",
        tags=["Model Lab"],
        dependencies=[Depends(get_current_user)],
    )

    @router.post(
        "/datasets",
        response_model=schemas.DatasetRunResponse,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[
            Depends(require_permission("generate_dataset")),
            Depends(check_concurrent_task_limit("generate_dataset")),
        ],
    )
    async def create_dataset_generation_task(
        run_create: schemas.DatasetRunCreate,
        current_user: models.User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
        redis_client: redis.Redis = Depends(get_redis_client),
    ):
        logger.info(
            "User '%s' creating dataset '%s'", current_user.username, run_create.name
        )

        user_plan = plans_config.get_plan(current_user.plan)
        limits = user_plan.get("limits", {})
        priority = limits.get("celery_task_priority", 9)

        try:
            db_run = await crud.create_dataset_run(
                db, user_id=current_user.id, run_create=run_create, celery_task_id=""
            )
            await db.flush()

            task = generate_dataset_task.apply_async(
                args=[db_run.id, current_user.id], priority=priority
            )
            await increment_concurrent_task_counter(current_user.id, redis_client)

            db_run.celery_task_id = task.id
            await db.commit()
            await db.refresh(db_run)

            logger.info(
                "Dataset generation task %s queued for run %s with priority %s",
                task.id,
                db_run.id,
                priority,
            )
            return db_run
        except Exception as e:
            logger.error(
                "Failed to create dataset generation task: %s", e, exc_info=True
            )
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to queue dataset generation task: {str(e)}",
            )

    @router.get("/datasets", response_model=List[schemas.DatasetRunResponse])
    async def list_dataset_runs(
        current_user: models.User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        return await crud.get_dataset_runs_by_user(db, user_id=current_user.id)

    @router.get("/datasets/{run_id}", response_model=schemas.DatasetRunResponse)
    async def get_dataset_run_details(
        run_id: str,
        current_user: models.User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        db_run = await crud.get_dataset_run(db, user_id=current_user.id, run_id=run_id)
        if not db_run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dataset run not found"
            )
        return db_run

    @router.delete("/datasets/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_dataset_run(
        run_id: str,
        current_user: models.User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        db_run = await crud.get_dataset_run(db, user_id=current_user.id, run_id=run_id)
        if not db_run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dataset run not found"
            )

        if db_run.file_path:
            try:
                file_to_delete = Path(db_run.file_path)
                if file_to_delete.exists():
                    os.remove(file_to_delete)
                    logger.info("Deleted dataset file: %s", file_to_delete)
            except Exception as e:
                logger.error("Error deleting dataset file %s: %s", db_run.file_path, e)

        await crud.delete_dataset_run(db, user_id=current_user.id, run_id=run_id)
        await db.commit()
        logger.info("Deleted dataset run %s from DB.", run_id)
        return None

    @router.post(
        "/train",
        response_model=schemas.TrainingRunResponse,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[
            Depends(require_permission("train_model")),
            Depends(check_concurrent_task_limit("train_model")),
        ],
    )
    async def create_model_training_task(
        run_create: schemas.TrainingRunCreate,
        current_user: models.User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
        redis_client: redis.Redis = Depends(get_redis_client),
    ):
        logger.info(
            "User '%s' creating training run on dataset '%s'",
            current_user.username,
            run_create.dataset_id,
        )

        user_plan = plans_config.get_plan(current_user.plan)
        limits = user_plan.get("limits", {})
        priority = limits.get("celery_task_priority", 9)

        try:
            db_run = await crud.create_training_run(
                db, user_id=current_user.id, run_create=run_create, celery_task_id=""
            )
            await db.flush()

            task = train_model_task.apply_async(
                args=[db_run.id, current_user.id], priority=priority
            )
            await increment_concurrent_task_counter(current_user.id, redis_client)

            db_run.celery_task_id = task.id
            await db.commit()
            await db.refresh(db_run)

            logger.info(
                "Model training task %s queued for run %s with priority %s",
                task.id,
                db_run.id,
                priority,
            )
            return db_run
        except ValueError as e:
            await db.rollback()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.get("/train", response_model=List[schemas.TrainingRunResponse])
    async def list_training_runs(
        current_user: models.User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        return await crud.get_training_runs_by_user(db, user_id=current_user.id)

    @router.get("/train/{run_id}", response_model=schemas.TrainingRunResponse)
    async def get_training_run_details(
        run_id: str,
        current_user: models.User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        db_run = await crud.get_training_run(db, user_id=current_user.id, run_id=run_id)
        if not db_run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Training run not found"
            )
        return db_run

    @router.get("/train/{run_id}/report", response_model=schemas.ModelTrainingReport)
    async def get_training_run_report(
        run_id: str,
        current_user: models.User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        db_run = await crud.get_training_run(db, user_id=current_user.id, run_id=run_id)
        if not db_run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Training run not found"
            )
        if db_run.status != "COMPLETED" or not db_run.report_path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Training report is not available for this run.",
            )

        report_path = Path(db_run.report_path)
        if not report_path.exists():
            logger.error(
                "Report file not found at path: %s for run_id: %s", report_path, run_id
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Report file is missing.",
            )

        try:
            with open(report_path, "r") as f:
                report_data = json.load(f)
            return schemas.ModelTrainingReport(**report_data)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logger.error("Failed to read or parse report file %s: %s", report_path, e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to load training report.",
            )

    @router.delete("/train/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_training_run(
        run_id: str,
        current_user: models.User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        db_run = await crud.get_training_run(db, user_id=current_user.id, run_id=run_id)
        if not db_run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Training run not found"
            )

        for file_str_path in [db_run.model_path, db_run.report_path]:
            if file_str_path:
                try:
                    file = Path(file_str_path)
                    if file.exists():
                        os.remove(file)
                        logger.info("Deleted training artifact: %s", file)
                except Exception as e:
                    logger.error(
                        "Error deleting artifact file %s: %s", file_str_path, e
                    )

        await crud.delete_training_run(db, user_id=current_user.id, run_id=run_id)
        await db.commit()
        logger.info("Deleted training run %s from DB.", run_id)
        return None

    return router
