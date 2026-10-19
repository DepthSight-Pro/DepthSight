"""Fleet-size gauge + global live-strategy admission cap (fail-open).

Every bot shard publishes two counters to Redis every minute
(`bot_runner._log_pool_telemetry_once`):

- `depthsight:fleet:strategies:<shard>` - running strategy instances. This is
  the unit a strategy start ADDS to, so it is the unit the cap enforces.
- `depthsight:fleet:controllers:<shard>` - bot controllers (one per user x
  API key). Controllers are created by the bot at bootstrap for every key it
  finds, independent of any API decision, so they cannot be gated here - they
  are published for capacity visibility only.

Why a Redis gauge instead of a DB count: what matters is what the workers run
RIGHT NOW. Controller and strategy lifecycle lives in worker memory, so a DB
count lags starts/stops and would add a query to the start-strategy hot path.

Fail-open is deliberate. If the gauge is missing, stale or Redis itself is
unreachable, starting is ALLOWED: losing visibility must never degrade into
"nobody can trade". The cap is a load guard, not access control.
"""

import logging
import os
from typing import List, Tuple

import redis.asyncio as redis


logger = logging.getLogger(__name__)

FLEET_STRATEGY_KEY_PREFIX = "depthsight:fleet:strategies:"
FLEET_CONTROLLER_KEY_PREFIX = "depthsight:fleet:controllers:"
# Must exceed the publish interval (60s) several times over so a crashed or
# restarted shard drops out of the sum instead of being counted forever. A
# too-short TTL would let a briefly stalled shard read as freed capacity.
FLEET_KEY_TTL_SECONDS = 180
# Backwards-compatible alias (the original name of the TTL knob).
FLEET_CONTROLLER_KEY_TTL_SECONDS = FLEET_KEY_TTL_SECONDS


def fleet_strategy_key(shard_id) -> str:
    return f"{FLEET_STRATEGY_KEY_PREFIX}{shard_id}"


def fleet_controller_key(shard_id) -> str:
    """Per-shard controller gauge. Shard-scoped so workers never overwrite each other."""
    return f"{FLEET_CONTROLLER_KEY_PREFIX}{shard_id}"


def get_max_global_live_strategies() -> int:
    """Global live-strategy admission cap. 0 (default) = cap disabled."""
    try:
        value = int(os.environ.get("MAX_GLOBAL_LIVE_STRATEGIES", 0))
    except (TypeError, ValueError):
        return 0
    return max(0, value)


async def _sum_gauge(redis_client: redis.Redis, prefix: str) -> Tuple[int, int]:
    """Sum one gauge family. Returns (-1, 0) when unreadable, (0, 0) when empty."""
    try:
        keys: List[str] = [
            key async for key in redis_client.scan_iter(match=f"{prefix}*", count=100)
        ]
        if not keys:
            return 0, 0
        values = await redis_client.mget(keys)
        total = 0
        reporting = 0
        for raw in values:
            if raw is None:
                continue
            try:
                total += int(raw)
            except (TypeError, ValueError):
                continue
            reporting += 1
        return total, reporting
    except Exception as exc:
        logger.warning(f"Fleet gauge {prefix} unavailable: {type(exc).__name__}: {exc}")
        return -1, 0


async def read_fleet_strategies(redis_client: redis.Redis) -> Tuple[int, int]:
    """(running strategy instances, shards reporting)."""
    return await _sum_gauge(redis_client, FLEET_STRATEGY_KEY_PREFIX)


async def read_fleet_controllers(redis_client: redis.Redis) -> Tuple[int, int]:
    """(bot controllers, shards reporting)."""
    return await _sum_gauge(redis_client, FLEET_CONTROLLER_KEY_PREFIX)


async def is_fleet_at_capacity(redis_client: redis.Redis) -> Tuple[bool, str]:
    """Check the admission cap. Fail-open: `(False, reason)` when unknown.

    Returns `(True, reason)` only when the gauge is readable AND the number of
    running strategy instances is at or above the configured cap.

    The gauge counts EVERY running instance (paper and live alike - both cost
    RAM and DB work), while the cap only gates NEW LIVE starts. A platform
    already running 200 paper strategies therefore has 200 fewer promo slots
    than the raw cap number suggests; the admin dashboard card shows both the
    used count and the cap so the headroom is visible.
    """
    cap = get_max_global_live_strategies()
    if cap <= 0:
        return False, "cap disabled"
    total, shards = await read_fleet_strategies(redis_client)
    if total < 0:
        return False, "gauge unavailable (fail-open)"
    if shards == 0:
        # No shard has published yet: we know nothing, so we gate nothing.
        return False, "no shard reporting yet (fail-open)"
    if total >= cap:
        return True, (
            f"{total} strategy instances running on {shards} shard(s), cap={cap}"
        )
    return False, f"{total}/{cap} strategy instances"
