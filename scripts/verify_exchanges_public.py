import asyncio
import platform
import logging
import time
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import aiohttp
from bot_module import config
from bot_module.exchanges import create_exchange_executor
from bot_module.data_consumer import DataConsumer
from bot_module.strategy import (
    StrategySignal,
    SignalDirection,
    OrderMode,
    PartialTarget,
)

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Force mainnet environment so we connect to live public market data feeds
config.ACTIVE_TRADING_ENVIRONMENT = "mainnet"

# Configure logging to show info messages
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - [%(name)s] - %(message)s"
)
logger = logging.getLogger("verify_exchanges_public")


async def test_exchange(exchange_name: str, market_type: str = "futures_usdtm"):
    logger.info(
        f"\n========================================\nSTARTING TEST FOR EXCHANGE: {exchange_name.upper()} ({market_type})\n========================================"
    )

    timeout = aiohttp.ClientTimeout(total=config.API_REQUEST_TIMEOUT_SECONDS * 2)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # 1. Initialize CCXT Executor
        logger.info(f"[{exchange_name}] Initializing executor...")
        executor = None
        try:
            executor = create_exchange_executor(
                exchange=exchange_name,
                api_key="",
                api_secret="",
                session=session,
                market_type=market_type,
            )
            logger.info(
                f"[{exchange_name}] Executor initialized. ID={executor.exchange_id}, Sandbox={executor.sandbox}"
            )
        except Exception as e:
            logger.error(
                f"[{exchange_name}] Failed to initialize executor: {e}", exc_info=True
            )
            return {
                "exchange": exchange_name,
                "rest": "FAILED",
                "websocket": "SKIPPED",
                "signal": "SKIPPED",
                "error": str(e),
            }

        # 2. Test REST Connectivity
        logger.info(
            f"[{exchange_name}] Testing REST connectivity (fetching BTCUSDT ticker)..."
        )
        rest_status = "FAILED"
        last_price = None
        try:
            ticker = await executor.get_ticker_price("BTCUSDT")
            if ticker and "price" in ticker:
                last_price = float(ticker["price"])
                logger.info(
                    f"[{exchange_name}] REST Success! BTCUSDT Price = {last_price}"
                )
                rest_status = "SUCCESS"
            else:
                logger.error(
                    f"[{exchange_name}] REST returned invalid ticker: {ticker}"
                )
        except Exception as e:
            logger.error(f"[{exchange_name}] REST call failed: {e}", exc_info=True)

        # 3. Test WebSocket Connectivity & DataConsumer Subscription
        logger.info(f"[{exchange_name}] Testing WebSocket/DataConsumer Subscription...")
        websocket_status = "FAILED"
        ws_payload_preview = None

        # Instantiate DataConsumer
        consumer = DataConsumer(
            loop=asyncio.get_running_loop(),
            executor=executor,
            event_queue=None,
            market_data_mode="direct",  # bypass Redis fan-out
        )

        # Override _running since we aren't calling consumer.start()
        consumer._running = True

        try:
            # Subscribing to public "depth" (orderbook) stream
            logger.info(f"[{exchange_name}] Subscribing to BTCUSDT depth stream...")
            await consumer.ensure_subscription("depth", "BTCUSDT")

            # Wait for the orderbook cache to be populated
            logger.info(
                f"[{exchange_name}] Waiting for orderbook cache to be populated (timeout=10s)..."
            )
            cache_key = "BTCUSDT_futures"
            event = None
            start_time = time.time()

            while time.time() - start_time < 10.0:
                async with consumer._data_cache_lock:
                    if cache_key in consumer._latest_depth_cache:
                        event = consumer._latest_depth_cache[cache_key]
                        break
                await asyncio.sleep(0.2)

            if event:
                logger.info(
                    f"[{exchange_name}] WebSocket Success! Cached event bids={len(event.get('bids', []))}, asks={len(event.get('asks', []))}"
                )
                ws_payload_preview = {
                    "bids_count": len(event.get("bids", [])),
                    "asks_count": len(event.get("asks", [])),
                    "first_bid": event.get("bids", [["N/A"]])[0][0]
                    if event.get("bids")
                    else "N/A",
                    "first_ask": event.get("asks", [["N/A"]])[0][0]
                    if event.get("asks")
                    else "N/A",
                }
                websocket_status = "SUCCESS"
            else:
                logger.error(
                    f"[{exchange_name}] WebSocket Timeout! No orderbook data received."
                )
        except Exception as e:
            logger.error(f"[{exchange_name}] WebSocket test failed: {e}", exc_info=True)
        finally:
            # Cleanup subscription
            try:
                await consumer.ensure_unsubscription("depth", "BTCUSDT")
            except Exception:
                pass

        # 4. Test Strategy Signal Structure
        logger.info(f"[{exchange_name}] Testing Strategy Signal structure...")
        signal_status = "FAILED"
        try:
            # Just verify we can create a StrategySignal object
            test_signal = StrategySignal(
                asset="BTCUSDT",
                exchange=exchange_name,
                strategy_name="public_test",
                direction=SignalDirection.LONG,
                order_mode=OrderMode.MARKET,
                entry_price=last_price or 60000.0,
                tp_targets=[
                    PartialTarget(price=(last_price or 60000.0) * 1.01, size_pct=100)
                ],
                sl_price=(last_price or 60000.0) * 0.99,
                timestamp=time.time(),
            )
            logger.info(
                f"[{exchange_name}] Signal Structure Success! Created {test_signal.direction} signal."
            )
            signal_status = "SUCCESS"
        except Exception as e:
            logger.error(f"[{exchange_name}] Signal structure test failed: {e}")

        return {
            "exchange": exchange_name,
            "rest": rest_status,
            "websocket": websocket_status,
            "signal": signal_status,
            "preview": ws_payload_preview,
        }


async def main():
    exchanges_to_test = ["binance", "bybit", "bitget", "gateio", "okx", "bingx"]

    results = []
    for exc in exchanges_to_test:
        try:
            res = await test_exchange(exc)
            results.append(res)
        except Exception as e:
            logger.error(f"Unhandled error testing {exc}: {e}")
            results.append(
                {
                    "exchange": exc,
                    "rest": "ERROR",
                    "websocket": "ERROR",
                    "signal": "FAILED",
                    "error": str(e),
                }
            )

    # Print summary table
    print("\n" + "=" * 100)
    print("                      EXCHANGES PUBLIC VERIFICATION SUMMARY")
    print("=" * 100)
    print(
        f"{'EXCHANGE':<15} | {'REST (Ticker)':<15} | {'WS (Orderbook)':<15} | {'SIGNAL':<15} | {'PREVIEW':<30}"
    )
    print("-" * 100)
    for r in results:
        preview_str = "N/A"
        if r.get("preview"):
            b = r["preview"]["bids_count"]
            a = r["preview"]["asks_count"]
            bid = r["preview"]["first_bid"]
            ask = r["preview"]["first_ask"]
            preview_str = f"bids={b}, asks={a} (bid:{bid}/ask:{ask})"
        print(
            f"{r['exchange'].upper():<15} | {r['rest']:<15} | {r['websocket']:<15} | {r['signal']:<15} | {preview_str:<30}"
        )
    print("=" * 100 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
