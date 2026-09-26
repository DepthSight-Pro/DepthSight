import asyncio
import json
import logging
import os
import secrets

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..push_sender import (
    DEFAULT_PUSH_URL,
    PUSH_EXPIRED,
    send_push_notification,
)
from ..redis_client import get_redis_client

try:
    from bot_module import config as bot_config
except ImportError:

    class MockConfig:
        REDIS_COMMAND_CHANNEL = "depthsight:commands"

    bot_config = MockConfig()


logger = logging.getLogger(__name__)
# NOTE: must match the channel the bot subscribes to
# (bot_module.config.REDIS_COMMAND_CHANNEL, default "depthsight:commands").
# A hardcoded "bot_commands" here silently drops TEST_NOTIFICATION.
REDIS_COMMAND_CHANNEL = getattr(
    bot_config, "REDIS_COMMAND_CHANNEL", "depthsight:commands"
)

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


@notifications_router.post("/push-test")
async def send_test_push_notification(
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sends a test Web Push to the caller's stored subscription.

    Returns {"status": sent|expired|failed|not_configured|no_subscription}.
    Expired subscriptions are removed so the client resubscribes on next launch.
    """
    subscription = current_user.push_subscription
    if not subscription or not isinstance(subscription, dict):
        return {"status": "no_subscription"}

    status = await asyncio.to_thread(
        send_push_notification,
        dict(subscription),
        "DepthSight test",
        "Push notifications are working. Trading events will arrive here.",
        "depthsight-push-test",
        DEFAULT_PUSH_URL,
    )
    if status == PUSH_EXPIRED:
        try:
            await crud.delete_user_push_subscription(db, user_id=current_user.id)
            await db.commit()
        except Exception as e:
            logger.error("Failed to clear expired push subscription: %s", e)
    return {"status": status}
