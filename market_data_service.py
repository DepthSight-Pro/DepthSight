from __future__ import annotations

import asyncio
import json
import logging
import signal
import time
from collections import defaultdict
from typing import Any, Dict, Optional, Set

import aiohttp
import redis.asyncio as redis_asyncio

from bot_module import config
from bot_module.data_consumer import (
    DataConsumer,
    _global_active_pairs,
    _global_agg_trade_deques,
    _global_cache_lock,
    _global_kline_cache,
    _global_pairs_lock,
    _kline_cache_key,
    _trade_cache_key,
)
from bot_module.exchanges import create_exchange_executor


logger = logging.getLogger("market_data_service")


def _snapshot_key(stream_key: str) -> str:
    return (
        f"{getattr(config, 'MARKET_DATA_REDIS_SNAPSHOT_KEY_PREFIX', 'depthsight:market_data:snapshot')}"
        f":{stream_key}"
    )


def _event_channel(stream_key: str) -> str:
    return (
        f"{getattr(config, 'MARKET_DATA_REDIS_EVENT_CHANNEL_PREFIX', 'depthsight:market_data:events')}"
        f":{stream_key}"
    )


class MarketDataService:
    """
    Central market-data fan-out service.

    Bot workers run DataConsumer in Redis mode and request subscriptions through
    MARKET_DATA_REDIS_COMMAND_CHANNEL. This service owns the real exchange
    streams, maintains one subscription per stream_key, writes warm snapshots,
    and publishes live payloads to worker-specific Redis channels.
    """

    def __init__(self) -> None:
        self.redis: Optional[redis_asyncio.Redis] = None
        self.pubsub: Optional[Any] = None
        self.consumers: Dict[str, DataConsumer] = {}
        self.session: Optional[aiohttp.ClientSession] = None
        self._stream_subscribers: Dict[str, Set[str]] = defaultdict(set)
        self._stream_specs: Dict[str, Dict[str, Any]] = {}
        self._stop_event = asyncio.Event()

    def _get_consumer(self, exchange_id: str) -> DataConsumer:
        """Dynamically creates or retrieves a DataConsumer for the specified exchange."""
        exchange_id = exchange_id.lower()
        if exchange_id not in self.consumers:
            logger.info("Creating DataConsumer for exchange: %s", exchange_id)
            futures_executor = create_exchange_executor(
                exchange=exchange_id,
                api_key="",
                api_secret="",
                session=self.session,
                market_type="futures_usdtm",
            )
            spot_executor = create_exchange_executor(
                exchange=exchange_id,
                api_key="",
                api_secret="",
                session=self.session,
                market_type="spot",
            )
            consumer = DataConsumer(
                loop=asyncio.get_running_loop(),
                executor=futures_executor,
                market_data_mode="direct",
                market_data_publish_callback=self._publish_market_payload,
            )
            consumer.set_market_executors(
                {"futures_usdtm": futures_executor, "spot": spot_executor}
            )
            consumer._running = True
            self.consumers[exchange_id] = consumer
        return self.consumers[exchange_id]

    async def start(self) -> None:
        timeout = aiohttp.ClientTimeout(total=config.API_REQUEST_TIMEOUT_SECONDS * 2)
        self.session = aiohttp.ClientSession(timeout=timeout)
        self.redis = redis_asyncio.Redis(
            host=config.MARKET_REDIS_HOST,
            port=config.MARKET_REDIS_PORT,
            db=config.MARKET_REDIS_DB,
            username=config.REDIS_USERNAME,
            password=config.REDIS_PASSWORD,
            decode_responses=True,
        )
        await self.redis.ping()
        self.pubsub = self.redis.pubsub()

        # Initialize default consumer (Binance)
        self._get_consumer("binance")

        await self.pubsub.subscribe(config.MARKET_DATA_REDIS_COMMAND_CHANNEL)
        logger.info(
            "MarketDataService listening on %s",
            config.MARKET_DATA_REDIS_COMMAND_CHANNEL,
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self.pubsub:
            try:
                await self.pubsub.unsubscribe(config.MARKET_DATA_REDIS_COMMAND_CHANNEL)
                await self.pubsub.close()
            except Exception:
                logger.debug("Error closing market-data pubsub.", exc_info=True)

        for exchange_id, consumer in self.consumers.items():
            try:
                await consumer.stop()
            except Exception:
                logger.debug(
                    "Error stopping market-data consumer for %s.",
                    exchange_id,
                    exc_info=True,
                )
        self.consumers.clear()

        if self.redis:
            await self.redis.close()
        if self.session:
            await self.session.close()

    async def run(self) -> None:
        await self.start()
        last_msg_time = time.monotonic()
        watchdog_timeout = getattr(config, "MDS_PUBSUB_WATCHDOG_SECONDS", 30)
        try:
            while not self._stop_event.is_set():
                if not self.pubsub:
                    await asyncio.sleep(0.1)
                    continue
                message = await self.pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message.get("type") == "message":
                    last_msg_time = time.monotonic()
                    raw = message.get("data")
                    payload = json.loads(raw) if isinstance(raw, str) else raw
                    await self._handle_command(payload)
                elif time.monotonic() - last_msg_time > watchdog_timeout:
                    logger.warning(
                        "Pubsub watchdog timeout (%ss) — no messages. Reconnecting...",
                        watchdog_timeout,
                    )
                    await self._reconnect_pubsub()
                    last_msg_time = time.monotonic()
        finally:
            await self.stop()

    async def _reconnect_pubsub(self) -> None:
        try:
            if self.pubsub:
                await self.pubsub.unsubscribe(config.MARKET_DATA_REDIS_COMMAND_CHANNEL)
                await self.pubsub.close()
        except Exception:
            logger.debug("Error closing stale pubsub.", exc_info=True)
        self.pubsub = self.redis.pubsub()
        await self.pubsub.subscribe(config.MARKET_DATA_REDIS_COMMAND_CHANNEL)
        logger.info(
            "Pubsub reconnected and re-subscribed to %s.",
            config.MARKET_DATA_REDIS_COMMAND_CHANNEL,
        )

    async def _handle_command(self, payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        command_type = payload.get("type")
        if command_type == "subscribe":
            await self._handle_subscribe(payload)
        elif command_type == "unsubscribe":
            await self._handle_unsubscribe(payload)

    async def _handle_subscribe(self, command: Dict[str, Any]) -> None:
        subscriber_id = str(command.get("subscriber_id") or "")
        if not subscriber_id:
            logger.warning("Ignoring market-data subscribe without subscriber_id.")
            return

        required_metrics = set(command.get("required_metrics") or [])
        needs_companion_orderbook = bool(command.get("needs_companion_orderbook"))

        for spec in self._command_stream_specs(command):
            if not isinstance(spec, dict):
                continue
            stream_key = str(spec.get("stream_key") or "")
            if not stream_key:
                continue

            subscribers = self._stream_subscribers[stream_key]
            was_empty = not subscribers
            subscribers.add(subscriber_id)
            self._stream_specs[stream_key] = dict(spec)

            data_type_key = spec.get("data_type_key") or command.get("data_type_key")
            symbol = spec.get("symbol") or command.get("symbol")
            market_type = spec.get("market_type") or command.get("market_type")
            exchange_id = spec.get("exchange_id") or "binance"

            consumer = self._get_consumer(exchange_id)

            if required_metrics:
                async with consumer._metrics_lock:
                    consumer._required_metrics[str(symbol).upper()].update(
                        required_metrics
                    )

            if was_empty:
                ensure_kwargs = {
                    "needs_companion_orderbook": needs_companion_orderbook,
                    "market_type": market_type,
                }
                if required_metrics:
                    ensure_kwargs["required_metrics"] = required_metrics
                await consumer.ensure_subscription(
                    data_type_key,
                    symbol,
                    **ensure_kwargs,
                )
            if required_metrics and str(data_type_key).startswith("kline_"):
                timeframe = str(data_type_key).split("_", 1)[1]
                await consumer._recalculate_kline_indicators(
                    str(symbol).upper(),
                    timeframe,
                    market_type=market_type,
                    exchange_id=exchange_id,
                )

            await self._write_snapshot_for_spec(spec)

    async def _handle_unsubscribe(self, command: Dict[str, Any]) -> None:
        subscriber_id = str(command.get("subscriber_id") or "")
        if not subscriber_id:
            return

        for spec in self._command_stream_specs(command):
            if not isinstance(spec, dict):
                continue
            stream_key = str(spec.get("stream_key") or "")
            if not stream_key:
                continue

            subscribers = self._stream_subscribers.get(stream_key)
            if not subscribers:
                continue
            subscribers.discard(subscriber_id)
            if subscribers:
                continue

            self._stream_subscribers.pop(stream_key, None)
            self._stream_specs.pop(stream_key, None)

            exchange_id = spec.get("exchange_id") or "binance"
            consumer = self._get_consumer(exchange_id)

            await consumer.remove_subscription(
                spec.get("data_type_key"),
                spec.get("symbol"),
                market_type=spec.get("market_type"),
            )

    async def _publish_market_payload(self, payload: Dict[str, Any]) -> None:
        redis_client = getattr(self, "redis", None)
        if not redis_client or not isinstance(payload, dict):
            return
        stream_key = payload.get("stream_key")
        if not stream_key:
            return
        data_type = str(payload.get("data_type_key", ""))
        symbol = str(payload.get("symbol", ""))
        market_type = str(payload.get("market_type", ""))
        payload_type = str(payload.get("type", ""))
        is_closed = None
        inner_payload = payload.get("payload")
        if isinstance(inner_payload, dict):
            k_data = inner_payload.get("k")
            if isinstance(k_data, dict):
                is_closed = k_data.get("x")
        channel = _event_channel(str(stream_key))
        logger.info(
            "Publishing market payload: type=%s stream_key=%s channel=%s data_type=%s symbol=%s market_type=%s is_closed=%s",
            payload_type,
            stream_key,
            channel,
            data_type,
            symbol,
            market_type,
            is_closed,
        )
        await redis_client.publish(channel, json.dumps(payload))

        spec = self._stream_specs.get(str(stream_key))
        if spec:
            await self._write_snapshot_for_spec(spec)

    async def _write_snapshot_for_spec(self, spec: Dict[str, Any]) -> bool:
        redis_client = getattr(self, "redis", None)
        if not redis_client or not isinstance(spec, dict):
            return False

        stream_key = str(spec.get("stream_key") or "")
        data_type_key = str(spec.get("data_type_key") or "")
        symbol = str(spec.get("symbol") or "").upper()
        market_type = spec.get("market_type")
        exchange_id = spec.get("exchange_id") or "binance"
        if not stream_key or not data_type_key or not symbol:
            return False

        snapshot: Optional[Dict[str, Any]] = None
        pair_state: Dict[str, Any] = {}
        async with _global_pairs_lock:
            pair_state = dict(_global_active_pairs.get(symbol, {}))

        if data_type_key.startswith("kline_"):
            timeframe = data_type_key.split("_", 1)[1]
            cache_key = _kline_cache_key(symbol, timeframe, exchange_id, market_type)
            async with _global_cache_lock:
                rows = list(_global_kline_cache.get(cache_key) or [])
            if not rows:
                return False
            snapshot = {
                "type": "market_snapshot",
                "stream_key": stream_key,
                "data_type_key": data_type_key,
                "symbol": symbol,
                "market_type": market_type,
                "exchange_id": exchange_id,
                "rows": rows,
                "pair_state": pair_state,
                "created_at_ms": int(time.time() * 1000),
            }
        elif data_type_key == "aggTrade":
            trade_key = _trade_cache_key(symbol, exchange_id, market_type)
            rows = list(_global_agg_trade_deques.get(trade_key) or [])
            if not rows:
                return False
            snapshot = {
                "type": "market_snapshot",
                "stream_key": stream_key,
                "data_type_key": data_type_key,
                "symbol": symbol,
                "market_type": market_type,
                "exchange_id": exchange_id,
                "rows": rows,
                "pair_state": pair_state,
                "created_at_ms": int(time.time() * 1000),
            }
        elif data_type_key == "depth":
            consumer = self._get_consumer(exchange_id)
            depth = await consumer.get_latest_depth(symbol, market_type)
            if not depth:
                return False
            snapshot = {
                "type": "market_snapshot",
                "stream_key": stream_key,
                "data_type_key": data_type_key,
                "symbol": symbol,
                "market_type": market_type,
                "exchange_id": exchange_id,
                "snapshot": depth,
                "pair_state": pair_state,
                "created_at_ms": int(time.time() * 1000),
            }
        elif data_type_key == "open_interest":
            consumer = self._get_consumer(exchange_id)
            df = await consumer.get_open_interest_history(symbol)
            if df is None or df.empty:
                return False
            rows = df.reset_index().to_dict(orient="records")
            snapshot = {
                "type": "market_snapshot",
                "stream_key": stream_key,
                "data_type_key": data_type_key,
                "symbol": symbol,
                "market_type": market_type,
                "exchange_id": exchange_id,
                "rows": rows,
                "pair_state": pair_state,
                "created_at_ms": int(time.time() * 1000),
            }

        if not snapshot:
            return False

        await redis_client.set(
            _snapshot_key(stream_key),
            json.dumps(snapshot, default=str),
            ex=getattr(config, "MARKET_DATA_REDIS_SNAPSHOT_TTL_SECONDS", 3600),
        )
        return True

    def _command_stream_specs(self, command: Dict[str, Any]) -> list[Dict[str, Any]]:
        stream_specs = command.get("stream_keys") or []
        if stream_specs:
            return [spec for spec in stream_specs if isinstance(spec, dict)]

        stream_key = command.get("stream_key")
        if not stream_key:
            return []

        return [
            {
                "stream_key": stream_key,
                "data_type_key": command.get("data_type_key"),
                "symbol": command.get("symbol"),
                "market_type": command.get("market_type"),
                "exchange_id": command.get("exchange_id") or "binance",
            }
        ]


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s",
    )
    service = MarketDataService()
    loop = asyncio.get_running_loop()
    for signame in ("SIGINT", "SIGTERM"):
        try:
            loop.add_signal_handler(getattr(signal, signame), service._stop_event.set)
        except (NotImplementedError, RuntimeError):
            pass
    await service.run()


if __name__ == "__main__":
    asyncio.run(main())
