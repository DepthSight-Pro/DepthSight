#!/usr/bin/env python3
"""Diagnostic script for the Market Data pipeline.

Checks each link in the chain:
  1. Redis connectivity
  2. Market Data Service presence (via Redis command channel)
  3. Active subscriptions on DataConsumer (via Redis state)
  4. Market data flow (injects a test payload and traces it)
  5. Controller event queue health

Usage:
    python scripts/diagnose_data_pipeline.py
"""

import asyncio
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("diag")


async def diagnose():
    import redis.asyncio as redis_asyncio
    import bot_module.config as config

    passed = 0
    total = 0

    def ok(msg):
        nonlocal passed
        passed += 1
        log.info("  PASS: %s", msg)

    def fail(msg):
        log.error("  FAIL: %s", msg)

    # ------------------------------------------------------------------
    log.info("=" * 60)
    log.info("MARKET DATA PIPELINE DIAGNOSTIC")
    log.info("=" * 60)

    # ---- 1. Redis connectivity ----
    total += 1
    log.info("\n[1/5] Redis connectivity")
    try:
        r = redis_asyncio.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=config.REDIS_DB,
            username=config.REDIS_USERNAME,
            password=config.REDIS_PASSWORD,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        await r.ping()
        info = await r.info("server")
        log.info("  Redis version: %s", info.get("redis_version", "unknown"))
        ok(f"Redis ping OK ({config.REDIS_HOST}:{config.REDIS_PORT})")
    except Exception as e:
        fail(f"Cannot connect to Redis: {e}")
        log.error("  FIX: Ensure Redis is running on %s:%s",
                  config.REDIS_HOST, config.REDIS_PORT)
        return

    # ---- 2. MDS command channel - check if MDS is subscribed ----
    total += 1
    log.info("\n[2/5] Market Data Service presence")
    try:
        cmd_channel = config.MARKET_DATA_REDIS_COMMAND_CHANNEL
        num_subs = await r.pubsub_numsub(cmd_channel)
        # num_subs returns list of (channel, count) tuples
        sub_count = 0
        for ch, cnt in (num_subs or []):
            sub_count = cnt
        if sub_count and int(sub_count) > 0:
            ok(f"MDS is subscribed to '{cmd_channel}' ({sub_count} subscriber(s))")
        else:
            fail(f"No subscriber on '{cmd_channel}' — MDS is NOT running")
            log.error("  FIX: Start market_data_service.py")
    except Exception as e:
        log.warning("  Could not check MDS subscriptions: %s", e)
        # Not critical - MDS might be running but pubsub_numsub may not be supported
        log.info("  SKIP (pubsub_numsub not supported by Redis config)")

    # ---- 3. Check for any recent market data snapshots in Redis ----
    total += 1
    log.info("\n[3/5] Market data snapshots in Redis")
    try:
        snapshot_prefix = getattr(
            config, "MARKET_DATA_REDIS_SNAPSHOT_KEY_PREFIX",
            "depthsight:market_data:snapshot"
        )
        cursor = 0
        snapshot_keys = []
        while True:
            cursor, keys = await r.scan(
                cursor=cursor, match=f"{snapshot_prefix}:*", count=100
            )
            snapshot_keys.extend(keys)
            if cursor == 0:
                break

        if snapshot_keys:
            log.info("  Found %d snapshot(s) in Redis:", len(snapshot_keys))
            for sk in snapshot_keys[:10]:
                raw = await r.get(sk)
                if raw:
                    try:
                        snap = json.loads(raw) if isinstance(raw, str) else raw
                        created = snap.get("created_at_ms", 0)
                        age_s = (time.time() * 1000 - created) / 1000 if created else -1
                        stream = snap.get("stream_key", "?")
                        log.info("    %s (age: %.0fs) — %s", sk, age_s, stream)
                    except Exception:
                        pass
            ok("Snapshots present — data has flowed through MDS")
        else:
            fail("No snapshots found — no data has flowed through MDS")
            log.error("  FIX: Check MDS logs for exchange WebSocket connectivity")
    except Exception as e:
        log.warning("  Could not check snapshots: %s", e)

    # ---- 4. Check if exchange data is flowing via Redis event channels ----
    total += 1
    log.info("\n[4/5] Market data events in Redis (last 10 seconds)")
    try:
        event_prefix = getattr(
            config, "MARKET_DATA_REDIS_EVENT_CHANNEL_PREFIX",
            "depthsight:market_data:events"
        )
        cursor = 0
        event_channels = []
        while True:
            cursor, keys = await r.scan(
                cursor=cursor, match=f"{event_prefix}:*", count=100
            )
            event_channels.extend(keys)
            if cursor == 0:
                break

        if event_channels:
            log.info("  Found %d event channel(s) in Redis:", len(event_channels))
            # Try to listen for a few seconds on the first active channel
            test_channel = event_channels[0]
            log.info("  Listening on '%s' for 3s...", test_channel)
            pubsub = r.pubsub()
            await pubsub.subscribe(test_channel)
            received = []
            start = time.time()
            while time.time() - start < 3:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if msg and msg.get("type") == "message":
                    received.append(msg)
            await pubsub.unsubscribe(test_channel)

            if received:
                ok(f"Received {len(received)} event(s) in 3s — data IS flowing")
                for m in received[:3]:
                    try:
                        d = json.loads(m["data"]) if isinstance(m["data"], str) else m["data"]
                        log.info("    Sample: type=%s stream=%s",
                                 d.get("data_type_key", "?"),
                                 d.get("stream_key", "?"))
                    except Exception:
                        log.info("    (raw)")
            else:
                fail("No events received in 3s — data is NOT flowing through Redis")
                log.error("  FIX: Check if Rust WebSocket connector or MDS is publishing data")
        else:
            fail("No event channels found — no subscriptions have been created")
            log.error("  FIX: Check if bot workers have subscribed (restart if needed)")
    except Exception as e:
        log.warning("  Could not check events: %s", e)

    # ---- 5. Inject test mock payload and verify DataConsumer processes it ----
    total += 1
    log.info("\n[5/5] Test: inject mock kline payload via Redis (fakeredis)")
    try:
        from bot_module.data_consumer import DataConsumer
        from unittest.mock import AsyncMock

        queue = asyncio.Queue()
        mock_executor = AsyncMock()
        mock_executor.market_type = "futures_usdtm"
        mock_executor.get_symbol_info = AsyncMock(return_value=None)

        consumer = DataConsumer(
            loop=asyncio.get_event_loop(),
            executor=mock_executor,
            event_queue=queue,
            market_data_mode="redis",
        )
        consumer._running = True

        stream_key = "diag:test:kline_1m"
        consumer._redis_market_stream_keys.add(stream_key)

        test_payload = {
            "type": "market_payload",
            "stream_key": stream_key,
            "data_type_key": "kline_1m",
            "symbol": "DIAGUSDT",
            "market_type": "futures_usdtm",
            "exchange_id": "binance",
            "payload": {
                "e": "kline",
                "k": {
                    "t": int(time.time() * 1000),
                    "o": "100.0",
                    "h": "101.0",
                    "l": "99.0",
                    "c": "100.5",
                    "v": "1000",
                    "x": True,
                },
            },
        }

        await consumer._handle_redis_market_payload(test_payload)

        try:
            event = queue.get_nowait()
            assert event["type"] == "CANDLE_CLOSE"
            assert event["symbol"] == "DIAGUSDT"
            df_test = await consumer.get_kline_history("DIAGUSDT", "1m")
            assert df_test is not None and not df_test.empty
            assert float(df_test["close"].iloc[-1]) == 100.5
            ok("Test kline payload processed correctly (CANDLE_CLOSE + cache)")
        except asyncio.QueueEmpty:
            fail("No CANDLE_CLOSE event in queue after injecting payload")
            log.error("  FIX: Check DataConsumer._handle_redis_market_payload → _update_local_cache")

        await consumer.clear_all_subscriptions()
        await consumer.stop()

    except Exception as e:
        log.error("  Test inject failed with exception: %s", e)
        import traceback
        traceback.print_exc()

    # ---- Summary ----
    log.info("\n" + "=" * 60)
    log.info("RESULT: %d / %d checks passed", passed, total)
    log.info("=" * 60)

    await r.close()
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(diagnose())
    sys.exit(0 if success else 1)
