import json
import logging
from typing import Any, Iterable, Optional

from .plans import plans_config

logger = logging.getLogger(__name__)


def build_initialize_user_controller_command(user_id: int) -> dict:
    return {
        "command": "INITIALIZE_USER_CONTROLLER",
        "payload": {"user_id": int(user_id)},
    }


def build_activate_api_key_command(user_id: int, api_key_id: int) -> dict:
    return {
        "command": "ACTIVATE_API_KEY",
        "payload": {
            "user_id": int(user_id),
            "api_key_id": int(api_key_id),
        },
    }


def build_deactivate_api_key_command(user_id: int, api_key_id: int) -> dict:
    return {
        "command": "DEACTIVATE_API_KEY",
        "payload": {
            "user_id": int(user_id),
            "api_key_id": int(api_key_id),
        },
    }


def plan_allows_live_trading(plan_name: Optional[str]) -> bool:
    if not plan_name:
        return False

    plan_config = plans_config.get_plan(plan_name)
    permissions = set(plan_config.get("permissions", []))
    limits = plan_config.get("limits", {})

    has_live_permission = "allow_real_trading" in permissions
    has_live_limit = bool(limits.get("allow_real_trading", has_live_permission))

    if has_live_permission != has_live_limit:
        logger.warning(
            "Plan '%s' has inconsistent live-trading flags (permission=%s, limit=%s). "
            "Treating live trading as disabled until the config is aligned.",
            plan_name,
            has_live_permission,
            has_live_limit,
        )

    return has_live_permission and has_live_limit


def get_max_live_strategies(plan_name: Optional[str]) -> Optional[int]:
    if not plan_name:
        return None

    plan_config = plans_config.get_plan(plan_name)
    limits = plan_config.get("limits", {})
    limit = limits.get("max_live_strategies")

    if limit is None:
        return None

    try:
        return int(limit)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid max_live_strategies value for plan '%s': %r", plan_name, limit
        )
        return None


def get_active_api_key_ids(active_api_keys: Iterable[Any]) -> list[int]:
    api_key_ids: list[int] = []
    for api_key in active_api_keys:
        api_key_id = getattr(api_key, "id", None)
        try:
            if api_key_id is not None:
                api_key_ids.append(int(api_key_id))
        except (TypeError, ValueError):
            logger.warning("Skipping API key with invalid id: %r", api_key_id)
    return api_key_ids


async def load_user_running_strategies(
    redis_client,
    strategies_state_key: str,
    user_id: int,
    mode: Optional[str] = None,
) -> list[dict]:
    base_strategies_key = f"{strategies_state_key}:{user_id}"
    pattern = f"{base_strategies_key}:*"
    keys = await redis_client.keys(pattern)

    if not keys:
        return []

    values = await redis_client.mget(keys)
    strategies: list[dict] = []
    seen: set[tuple[Any, Any, Any]] = set()

    for raw_value in values:
        if not raw_value:
            continue

        try:
            payload = json.loads(raw_value)
        except (TypeError, json.JSONDecodeError):
            logger.warning(
                "Skipping invalid strategies payload from Redis for user_id=%s", user_id
            )
            continue

        if not isinstance(payload, list):
            continue

        for entry in payload:
            if not isinstance(entry, dict):
                continue

            if str(entry.get("user_id")) != str(user_id):
                continue

            entry_mode = entry.get("mode", "live")
            if mode is not None and entry_mode != mode:
                continue

            dedupe_key = (entry.get("id"), entry.get("api_key_id"), entry_mode)
            if dedupe_key in seen:
                continue

            seen.add(dedupe_key)
            strategies.append(entry)

    return strategies


def count_new_strategy_instances(
    *,
    config_id: str,
    target_api_key_ids: Iterable[int],
    running_strategies: Iterable[dict],
) -> int:
    running_pairs = {
        (entry.get("id"), entry.get("api_key_id")) for entry in running_strategies
    }
    new_pairs = {
        (config_id, api_key_id)
        for api_key_id in target_api_key_ids
        if (config_id, api_key_id) not in running_pairs
    }
    return len(new_pairs)
