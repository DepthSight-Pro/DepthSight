# api/redis_client.py
import redis.asyncio as aioredis
import redis.exceptions as redis_exceptions
from fastapi import HTTPException, status
import logging

from bot_module import config as bot_config

logger = logging.getLogger(__name__)


async def get_redis_client() -> aioredis.Redis:
    """
    Dependency to get a Redis client.
    Attempts to reconnect if the connection is lost.
    """
    try:
        redis_password = bot_config.REDIS_PASSWORD
        if not redis_password:
            logger.warning(
                "SECURITY: Redis is configured WITHOUT authentication (no REDIS_PASSWORD). "
                "Set REDIS_PASSWORD in environment and enable 'requirepass' in redis.conf for production."
            )
        redis_client = aioredis.Redis(
            host=bot_config.REDIS_HOST,
            port=bot_config.REDIS_PORT,
            db=bot_config.REDIS_DB,
            username=bot_config.REDIS_USERNAME,
            password=redis_password,
            decode_responses=True,
        )
        await redis_client.ping()
        return redis_client
    except (
        redis_exceptions.ConnectionError,
        redis_exceptions.BusyLoadingError,
        redis_exceptions.TimeoutError,
        redis_exceptions.AuthenticationError,
    ) as e:
        logger.error(f"Failed to connect to Redis: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not establish connection to Redis service.",
        )
