import json
import logging
import os

import redis.asyncio as redis
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..redis_client import get_redis_client


logger = logging.getLogger(__name__)
REDIS_COMMAND_CHANNEL = os.getenv("REDIS_COMMAND_CHANNEL", "bot_commands")

users_extra_router = APIRouter(
    prefix="/api/v1/users", tags=["Users"], dependencies=[Depends(get_current_user)]
)


@users_extra_router.post("/subscribe_push", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe_for_push_notifications(
    subscription: schemas.PushSubscription,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    logger.info("User '%s' subscribing for push notifications.", current_user.username)
    await crud.update_user_push_subscription(
        db, user_id=current_user.id, subscription=subscription.model_dump()
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@users_extra_router.post("/unsubscribe_push", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe_from_push_notifications(
    payload: schemas.PushUnsubscribePayload,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    logger.info(
        "User '%s' unsubscribing from push notifications for endpoint: %s",
        current_user.username,
        payload.endpoint,
    )
    await crud.delete_user_push_subscription(db, user_id=current_user.id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@users_extra_router.get(
    "/settings/symbol-selection",
    response_model=schemas.ApiResponseData[schemas.SymbolSelectionConfig],
)
async def get_symbol_selection_settings(
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info(
        "User '%s' (ID: %s) fetching symbol selection settings.",
        current_user.username,
        current_user.id,
    )

    if not current_user.symbol_selection_config:
        return {"data": schemas.SymbolSelectionConfig()}

    return {
        "data": schemas.SymbolSelectionConfig.model_validate(
            current_user.symbol_selection_config
        )
    }


@users_extra_router.put(
    "/settings/symbol-selection",
    response_model=schemas.ApiResponseData[schemas.SymbolSelectionConfig],
)
async def update_symbol_selection_settings(
    new_settings: schemas.SymbolSelectionConfig,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    logger.info(
        "User '%s' (ID: %s) updating symbol selection settings to: %s",
        current_user.username,
        current_user.id,
        new_settings.model_dump_json(),
    )

    await crud.update_user_symbol_selection_config(
        db, current_user.id, new_settings.model_dump()
    )
    await db.commit()

    try:
        reload_command = {
            "command": "RELOAD_CONFIG",
            "payload": {"user_id": current_user.id},
        }
        await redis_client.publish(REDIS_COMMAND_CHANNEL, json.dumps(reload_command))
        logger.info(
            "User '%s' (ID: %s) - RELOAD_CONFIG command published after symbol selection update.",
            current_user.username,
            current_user.id,
        )
    except Exception as e:
        logger.warning(
            "Failed to publish RELOAD_CONFIG after symbol selection update for user %s: %s",
            current_user.id,
            e,
        )

    return {"data": new_settings}
