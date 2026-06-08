import asyncio
import platform
import sys
import logging
import time

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import aiohttp
from bot_module import config

# Force mainnet environment so we connect to live public market data feeds
config.ACTIVE_TRADING_ENVIRONMENT = "mainnet"

from bot_module.exchanges import create_exchange_executor
from bot_module.data_consumer import DataConsumer
from bot_module.strategy import StrategySignal, SignalDirection, OrderMode, PartialTarget

# Configure logging to show info messages
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(name)s] - %(message)s"
)
logger = logging.getLogger("verify_exchanges_public")

async def test_exchange(exchange_name: str, market_type: str = "futures_usdtm"):
    logger.info(f"\n========================================\nSTARTING TEST FOR EXCHANGE: {exchange_name.upper()} ({market_type})\n========================================")
    
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
            logger.info(f"[{exchange_name}] Executor initialized. ID={executor.exchange_id}, Sandbox={executor.sandbox}")
        except Exception as e:
            logger.error(f"[{exchange_name}] Failed to initialize executor: {e}", exc_info=True)
            return {"exchange": exchange_name, "rest": "FAILED", "websocket": "SKIPPED", "signal": "SKIPPED", "error": str(e)}

        # 2. Test REST Connectivity
        logger.info(f"[{exchange_name}] Testing REST connectivity (fetching BTCUSDT ticker)...")
        rest_status = "FAILED"
        last_price = None
        try:
            ticker = await executor.get_ticker_price("BTCUSDT")
            if ticker and "price" in ticker:
                last_price = float(ticker["price"])
                logger.info(f"[{exchange_name}] REST Success! BTCUSDT Price = {last_price}")
                rest_status = "SUCCESS"
            else:
                logger.error(f"[{exchange_name}] REST returned invalid ticker: {ticker}")
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
            market_data_mode="direct"  # bypass Redis fan-out
        )
        
        # Override _running since we aren't calling consumer.start()
        consumer._running = True
        
        try:
            # Subscribing to public "depth" (orderbook) stream
            logger.info(f"[{exchange_name}] Subscribing to BTCUSDT depth stream...")
            await consumer.ensure_subscription("depth", "BTCUSDT")
            
            # Wait for the orderbook cache to be populated
            logger.info(f"[{exchange_name}] Waiting for orderbook cache to be populated (timeout=10s)...")
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
                logger.info(f"[{exchange_name}] WebSocket Success! Cached event bids={len(event.get('bids', []))}, asks={len(event.get('asks', []))}")
                ws_payload_preview = {
                    "bids_count": len(event.get("bids", [])),
                    "asks_count": len(event.get("asks", [])),
                    "first_bid": event.get("bids", [["N/A"]])[0][0] if event.get("bids") else "N/A",
                    "first_ask": event.get("asks", [["N/A"]])[0][0] if event.get("asks") else "N/A",
                }
                websocket_status = "SUCCESS"
            else:
                logger.error(f"[{exchange_name}] Orderbook cache was not populated.")
        except Exception as e:
            logger.error(f"[{exchange_name}] WebSocket/Subscription failed: {e}", exc_info=True)
        finally:
            # Clean up consumer and cancel subscription tasks
            logger.info(f"[{exchange_name}] Stopping DataConsumer...")
            await consumer.stop()

        # 4. Test Mock Strategy Signal Generation
        logger.info(f"[{exchange_name}] Testing Strategy Signal Generation...")
        signal_status = "FAILED"
        try:
            # We construct a StrategySignal using this exchange details and the last price
            price_for_sig = last_price or 65000.0
            sig = StrategySignal(
                strategy_name="VerificationTestStrategy",
                symbol="BTCUSDT",
                direction=SignalDirection.LONG,
                stop_loss=price_for_sig * 0.99,
                take_profit=price_for_sig * 1.02,
                mode=OrderMode.MARKET,
                trigger_price=price_for_sig,
                details={
                    "exchange_id": executor.exchange_id,
                    "market_type": market_type,
                    "foundation_total_weight": 100.0,
                },
                partial_targets=[
                    PartialTarget(price=price_for_sig * 1.01, fraction=0.5),
                    PartialTarget(price=price_for_sig * 1.02, fraction=0.5)
                ]
            )
            
            # Verify fields
            assert sig.symbol == "BTCUSDT"
            assert sig.direction == SignalDirection.LONG
            assert sig.details["exchange_id"] == executor.exchange_id
            
            logger.info(f"[{exchange_name}] Signal generation Success! Generated: {sig}")
            signal_status = "SUCCESS"
        except Exception as e:
            logger.error(f"[{exchange_name}] Signal generation test failed: {e}", exc_info=True)

        # Clean up CCXT exchange instances
        try:
            if hasattr(executor, "_exchange") and executor._exchange:
                await executor._exchange.close()
            if hasattr(executor, "_exchange_pro") and executor._exchange_pro:
                await executor._exchange_pro.close()
        except Exception as e:
            logger.debug(f"[{exchange_name}] Error closing exchange connections: {e}")

        return {
            "exchange": exchange_name,
            "rest": rest_status,
            "websocket": websocket_status,
            "signal": signal_status,
            "price": last_price,
            "preview": ws_payload_preview
        }

async def main():
    exchanges = ["binance", "bybit", "okx", "bitget", "gate", "bingx"]
    results = []
    
    for ex in exchanges:
        try:
            res = await test_exchange(ex)
            results.append(res)
        except Exception as e:
            logger.critical(f"Unhandled exception testing {ex}: {e}", exc_info=True)
            results.append({
                "exchange": ex,
                "rest": "FAILED",
                "websocket": "FAILED",
                "signal": "FAILED",
                "error": str(e)
            })

    # Print summary table
    print("\n" + "="*100)
    print("                      EXCHANGES PUBLIC VERIFICATION SUMMARY")
    print("="*100)
    print(f"{'EXCHANGE':<15} | {'REST (Ticker)':<15} | {'WS (Orderbook)':<15} | {'SIGNAL':<15} | {'PREVIEW':<30}")
    print("-"*100)
    for r in results:
        preview_str = "N/A"
        if r.get("preview"):
            b = r["preview"]["bids_count"]
            a = r["preview"]["asks_count"]
            bid = r["preview"]["first_bid"]
            ask = r["preview"]["first_ask"]
            preview_str = f"bids={b}, asks={a} (bid:{bid}/ask:{ask})"
        print(f"{r['exchange'].upper():<15} | {r['rest']:<15} | {r['websocket']:<15} | {r['signal']:<15} | {preview_str:<30}")
    print("="*100 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
