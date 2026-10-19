#!/usr/bin/env python
"""Audit live controllers for duplicate strategy instances (read-only).

Two instances of the SAME source config covering the SAME symbol inside one
controller means two strategies fight over one position: double entries, double
SL/TP, conflicting exits. On paper that is noise; with live money it is a
double trade.

The duplicate guard (controller.py `_has_overlapping_running_instance`) can
only compare what the stored payload contains. A payload without a symbol list
made the guard blind, so this script reports BOTH problems:

  DUP   - one controller holds 2+ instances of the same source config
  BLIND - a stored instance has no usable symbol list (guard cannot compare)

Usage (inside the api container, which has Redis and the bot's env):
    python scripts/audit_duplicate_instances.py
    python scripts/audit_duplicate_instances.py --redis-host redis

Never writes: it only scans runtime-state keys and prints a report.
"""

import argparse
import asyncio
import json
import os
import sys


def _symbols_of(payload: dict) -> set:
    raw = payload.get("symbols")
    if not raw:
        config_data = payload.get("config_data") or {}
        single = config_data.get("symbol")
        raw = [single] if single else []
    return {str(s).strip().upper() for s in raw if str(s).strip()}


async def audit(redis_client) -> int:
    pattern = "depthsight:controller:runtime_state:*"
    keys = [k async for k in redis_client.scan_iter(match=pattern, count=200)]
    if not keys:
        print("No controller runtime state found - nothing is running.")
        return 0

    dup_controllers = []
    blind_controllers = []
    total_instances = 0

    for key in keys:
        try:
            raw = await redis_client.get(key)
        except Exception as exc:
            print(f"  [warn] {key}: {type(exc).__name__}: {exc}")
            continue
        if not raw:
            continue
        try:
            state = json.loads(raw)
        except (TypeError, ValueError):
            continue

        strategies = state.get("running_strategies") or []
        total_instances += len(strategies)

        by_source = {}
        for payload in strategies:
            if not isinstance(payload, dict):
                continue
            source = payload.get("config_id") or payload.get("id")
            by_source.setdefault(source, []).append(payload)
            if not _symbols_of(payload):
                blind_controllers.append((key, source))

        for source, group in by_source.items():
            if len(group) < 2:
                continue
            covered = {}
            for payload in group:
                for symbol in _symbols_of(payload) or {"<unknown>"}:
                    covered.setdefault(symbol, 0)
                    covered[symbol] += 1
            conflicting = {s: n for s, n in covered.items() if n > 1}
            dup_controllers.append((key, source, len(group), conflicting))

    print(f"controllers with runtime state: {len(keys)}")
    print(f"strategy instances in total:    {total_instances}")
    print(f"controllers with DUPLICATES:   {len(dup_controllers)}")
    print(f"instances with UNKNOWN symbols: {len(blind_controllers)}")

    if dup_controllers:
        print("\n=== duplicate instances (same source config in one controller) ===")
        for key, source, count, conflicting in dup_controllers[:20]:
            short = str(source)[:8]
            print(f"  {key}  source={short}  instances={count}  overlap={conflicting}")
        if len(dup_controllers) > 20:
            print(f"  ... and {len(dup_controllers) - 20} more")

    if blind_controllers:
        print("\n=== instances the duplicate guard cannot compare ===")
        for key, source in blind_controllers[:20]:
            print(f"  {key}  source={str(source)[:8]}")
        if len(blind_controllers) > 20:
            print(f"  ... and {len(blind_controllers) - 20} more")

    if not dup_controllers and not blind_controllers:
        print("\nNo duplicate instances and no blind payloads. Clean.")
    return len(dup_controllers)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--redis-host", default=os.environ.get("REDIS_HOST", "redis"))
    parser.add_argument(
        "--redis-port", type=int, default=int(os.environ.get("REDIS_PORT", 6379))
    )
    parser.add_argument(
        "--redis-user", default=os.environ.get("REDIS_USERNAME", "") or None
    )
    args = parser.parse_args()

    import redis.asyncio as aioredis

    client = aioredis.Redis(
        host=args.redis_host,
        port=args.redis_port,
        username=args.redis_user,
        password=os.environ.get("REDIS_PASSWORD") or None,
        socket_timeout=10,
    )
    try:
        return await audit(client)
    finally:
        await client.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
