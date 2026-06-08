import json
import logging
import os
import secrets

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status

from .. import models, schemas
from ..auth import get_current_user
from ..redis_client import get_redis_client


logger = logging.getLogger(__name__)
REDIS_COMMAND_CHANNEL = os.getenv("REDIS_COMMAND_CHANNEL", "bot_commands")

notifications_router = APIRouter(
    prefix="/api/v1/notifications",
    tags=["Notifications"],
    dependencies=[Depends(get_current_user)],
)


@notifications_router.get("/vapid_public_key")
async def get_vapid_public_key():
    vapid_public_key = os.getenv("VAPID_PUBLIC_KEY")
    if not vapid_public_key:
        logger.error("VAPID_PUBLIC_KEY is not set in environment variables.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Notification service is not configured.",
        )
    return {"public_key": vapid_public_key}


@notifications_router.post("/test", status_code=status.HTTP_200_OK)
async def test_telegram_notification(
    request: schemas.TestNotificationRequest,
    current_user: models.User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    logger.info(
        "User '%s' requested test notification to chat_id: %s",
        current_user.username,
        request.chat_id,
    )

    command = {
        "command": "TEST_NOTIFICATION",
        "payload": {"user_id": current_user.id, "chat_id": request.chat_id},
    }

    try:
        await redis_client.publish(REDIS_COMMAND_CHANNEL, json.dumps(command))
        return {"message": "Test notification command sent to bot."}
    except Exception as e:
        logger.error(
            "Failed to publish test notification command: %s", e, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to communicate with the bot.",
        )


@notifications_router.get(
    "/telegram/bind-url", response_model=schemas.TelegramBindingLink
)
async def get_telegram_binding_url(
    current_user: models.User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    token = secrets.token_urlsafe(12)
    redis_key = f"tg_bind:{token}"

    await redis_client.set(redis_key, current_user.id, ex=600)

    bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "DepthSightBot")
    if bot_username.startswith("@"):
        bot_username = bot_username[1:]

    url = f"https://t.me/{bot_username}?start={token}"
    return {"url": url}
