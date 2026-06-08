from datetime import date
from fastapi import Depends, HTTPException, status
from typing import Any
from .models import User
from .auth import get_current_user
from .redis_client import get_redis_client
from .plans import plans_config
import redis.asyncio as redis
import logging

logger = logging.getLogger(__name__)

# Features for which we track execution in Celery
TASK_FEATURES = [
    "run_backtest",
    "run_portfolio_backtest",
    "run_optimization",
    "run_genetic_search",
    "generate_dataset",
    "train_model",
]


def require_permission(permission_name: str):
    """
    FastAPI dependency factory to check access permissions.
    """

    async def dependency(user: User = Depends(get_current_user)):
        user_plan = plans_config.get_plan(user.plan)
        if permission_name not in user_plan.get("permissions", []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your current plan ({user.plan}) does not allow you to use this feature: {permission_name}",
            )
        return user

    return dependency


# --- Concurrent Tasks Management ---
def check_concurrent_task_limit(feature: str):
    """
    FastAPI dependency factory to check and increment concurrent task counter.
    """

    async def dependency(
        user: User = Depends(get_current_user),
        redis_client: redis.Redis = Depends(get_redis_client),
    ):
        if feature not in TASK_FEATURES:
            return user

        user_plan_config = plans_config.get_plan(user.plan)
        limits = user_plan_config.get("limits", {})
        concurrent_limit = limits.get("max_concurrent_tasks", -1)

        if concurrent_limit == -1:
            return user

        redis_key = f"concurrent_tasks:user:{user.id}"
        current_tasks_raw = await redis_client.get(redis_key)
        current_tasks = int(current_tasks_raw) if current_tasks_raw else 0

        if current_tasks >= concurrent_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"You have reached the maximum number of concurrent tasks ({concurrent_limit}) for your plan. Please wait for some tasks to complete.",
            )
        return user

    return dependency


async def increment_concurrent_task_counter(user_id: int, redis_client: redis.Redis):
    redis_key = f"concurrent_tasks:user:{user_id}"
    current_tasks = await redis_client.incr(redis_key)
    if current_tasks == 1:
        await redis_client.expire(redis_key, 3600 * 24)
    return current_tasks


async def decrement_concurrent_task_counter(user_id: int, redis_client: redis.Redis):
    redis_key = f"concurrent_tasks:user:{user_id}"
    if await redis_client.exists(redis_key):
        await redis_client.decr(redis_key)


# --- Usage Quotas ---
def check_usage_quota(feature: str):
    """Checks the daily usage quota for a feature."""

    async def dependency(
        user: User = Depends(get_current_user),
        redis_client: redis.Redis = Depends(get_redis_client),
    ):
        user_plan_config = plans_config.get_plan(user.plan)
        quota_key = f"{feature}_per_day"
        limit = user_plan_config.get("quotas", {}).get(quota_key)

        if limit is None or limit == -1:
            return user

        today = date.today().isoformat()
        redis_key = f"usage_quota:user:{user.id}:{feature}:{today}"

        current_usage_raw = await redis_client.get(redis_key)
        current_usage = int(current_usage_raw) if current_usage_raw else 0

        if current_usage >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"You have exceeded the usage limit ({limit}) for {feature} today. Upgrade your plan for more.",
            )
        return user

    return dependency


async def increment_usage_quota(user_id: int, feature: str, redis_client: redis.Redis):
    today = date.today().isoformat()
    redis_key = f"usage_quota:user:{user_id}:{feature}:{today}"
    await redis_client.incr(redis_key)
    await redis_client.expire(redis_key, 3600 * 48)


async def get_redis_client_for_quota() -> redis.Redis:
    return await get_redis_client()


async def require_admin_role(user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires admin privileges.",
        )
    return user


async def require_affiliate_role(user: User = Depends(get_current_user)):
    if user.role not in ["affiliate", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires affiliate or admin rights.",
        )
    return user


# --- Tier Validations ---
def _has_restricted_blocks(params: Any, restricted_list: list) -> bool:
    if not restricted_list:
        return False

    restricted_set = set(restricted_list)

    def walk(node: Any) -> bool:
        if isinstance(node, dict):
            node_type = node.get("type")
            if isinstance(node_type, str) and node_type in restricted_set:
                return True

            composite_type = node.get("compositeType")
            if isinstance(composite_type, str) and composite_type in restricted_set:
                return True

            if (
                "partial_exits" in restricted_set
                and isinstance(node.get("partial_exits"), list)
                and len(node["partial_exits"]) > 0
            ):
                return True

            return any(walk(value) for value in node.values())

        if isinstance(node, list):
            return any(walk(item) for item in node)

        return False

    return walk(params)


def is_strategy_pro_only(params: dict) -> bool:
    pro_blocks = plans_config.get_block_restrictions().get("pro_only", [])
    return _has_restricted_blocks(params, pro_blocks)


def is_strategy_kline_only(params: dict) -> bool:
    kline_blocks = plans_config.get_block_restrictions().get("kline_only", [])
    return _has_restricted_blocks(params, kline_blocks)
