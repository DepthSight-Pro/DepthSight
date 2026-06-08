# data_recorder.py
import asyncio
import ccxt.pro as ccxtpro
import json
import logging
import msgpack
import zstandard
from datetime import datetime, timezone
from pathlib import Path
import aiofiles
from typing import Dict, Any
import ccxt

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(name)s] - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("data_recorder.log", mode="a", encoding="utf-8"),
    ],
)
logger = logging.getLogger("DataRecorder")


class L2StreamRecorder:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.storage_path = Path(config.get("storage_path", "L2_data"))
        self.exchanges: Dict[str, ccxtpro.Exchange] = {}
        self.compressor = zstandard.ZstdCompressor(
            level=3
        )  # level=3 good ratio of speed and compression
        self._running = True
        self._active_writers: Dict[
            str, aiofiles.threadpool.binary.AsyncBufferedIOBase
        ] = {}
        self._writer_locks: Dict[str, asyncio.Lock] = {}
        self._current_file_path: Dict[str, Path] = {}

    async def _initialize_exchanges(self):
        """Initializes ccxt.pro exchange instances."""
        for ex_name, ex_config in self.config.get("exchanges", {}).items():
            if ex_config.get("enabled", False):
                try:
                    exchange_class = getattr(ccxtpro, ex_name)
                    # newUpdates: True - required to receive updates, not snapshots
                    self.exchanges[ex_name] = exchange_class({"newUpdates": True})
                    logger.info(f"Initialized exchange: {ex_name}")
                except AttributeError:
                    logger.error(f"Exchange '{ex_name}' not found in ccxt.pro.")
                except Exception as e:
                    logger.error(f"Failed to initialize {ex_name}: {e}")

    def _get_file_path(self, exchange: str, symbol: str) -> Path:
        """Generates a file path based on the current time (hourly file)."""
        now_utc = datetime.now(timezone.utc)
        # Normalizing the symbol for the filename
        symbol_safe = symbol.replace("/", "_").replace(":", "_")

        # Structure: base_path / exchange / symbol / YYYY / MM / DD /
        day_path = (
            self.storage_path / exchange / symbol_safe / now_utc.strftime("%Y/%m/%d")
        )
        day_path.mkdir(parents=True, exist_ok=True)

        # Filename: HH-00-00.bin.zst
        filename = f"{now_utc.strftime('%H')}-00-00.bin.zst"
        return day_path / filename

    async def _get_writer(self, exchange: str, symbol: str):
        """Gets or creates a file descriptor for writing. Rotates files by the hour."""
        stream_key = f"{exchange}_{symbol}"

        if stream_key not in self._writer_locks:
            self._writer_locks[stream_key] = asyncio.Lock()

        async with self._writer_locks[stream_key]:
            new_path = self._get_file_path(exchange, symbol)

            # Checking if the file needs to be rotated
            if self._current_file_path.get(stream_key) != new_path:
                # Closing the old file if it existed
                if stream_key in self._active_writers:
                    old_writer = self._active_writers.pop(stream_key)
                    await old_writer.close()
                    logger.info(
                        f"Closed L2 file: {self._current_file_path.get(stream_key)}"
                    )

                # Opening a new file for writing
                logger.info(f"Opening new L2 file for {stream_key}: {new_path}")
                writer = await aiofiles.open(new_path, "ab")  # 'ab' - append binary
                self._active_writers[stream_key] = writer
                self._current_file_path[stream_key] = new_path
                return writer
            else:
                return self._active_writers[stream_key]

    async def _record_loop(self, exchange_name: str, symbol: str, market_type: str):
        """Main listening and writing loop for a single thread."""
        exchange = self.exchanges[exchange_name]
        log_prefix = f"[{exchange_name.upper()}:{symbol}:{market_type.upper()}]"

        params = {"type": market_type} if market_type == "future" else {}

        while self._running:
            try:
                # Correct way to iterate over the ccxt.pro asynchronous generator
                async for orderbook in exchange.watch_order_book(symbol, None, params):
                    if not self._running:
                        break

                    writer = await self._get_writer(exchange_name, symbol)
                    lock = self._writer_locks.get(f"{exchange_name}_{symbol}")

                    if not writer or not lock:
                        logger.error(
                            f"{log_prefix} Could not get a writer or lock. Stopping loop for this symbol."
                        )
                        return

                    data_to_write = {
                        "ts": orderbook["timestamp"],
                        "bids": orderbook["bids"],
                        "asks": orderbook["asks"],
                        "nonce": orderbook.get("nonce"),
                    }

                    packed_data = msgpack.packb(data_to_write, use_bin_type=True)
                    compressed_data = self.compressor.compress(packed_data)

                    async with lock:
                        await writer.write(compressed_data)

            except ccxt.NetworkError as e:
                logger.warning(
                    f"{log_prefix} Network error: {e}. Reconnecting in 5s..."
                )
                await asyncio.sleep(5)
            except ccxt.ExchangeError as e:
                logger.error(
                    f"{log_prefix} Exchange error: {e}. Reconnecting in 30s..."
                )
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                logger.info(f"{log_prefix} Task was cancelled.")
                break
            except Exception as e:
                logger.error(
                    f"{log_prefix} Unhandled error in record loop: {e}", exc_info=True
                )
                await asyncio.sleep(10)

    async def start(self):
        """Starts all necessary writing loops."""
        await self._initialize_exchanges()

        tasks = []
        for ex_name, ex_config in self.config.get("exchanges", {}).items():
            if ex_name not in self.exchanges:
                continue

            for market_type, symbols in ex_config.get("markets", {}).items():
                if not isinstance(symbols, list):
                    continue
                # ccxt.pro uses 'future' for USDT-M futures
                ccxt_market_type = "future" if market_type == "futures" else market_type

                for symbol in symbols:
                    task = asyncio.create_task(
                        self._record_loop(ex_name, symbol, ccxt_market_type)
                    )
                    tasks.append(task)

        if tasks:
            logger.info(f"Starting {len(tasks)} recording loops...")
            await asyncio.gather(*tasks)
        else:
            logger.warning("No symbols configured for recording.")

    async def stop(self):
        """Stops all loops and closes resources."""
        logger.info("Stopping recorder and closing all resources...")
        self._running = False

        # Closing all ccxt.pro exchange instances
        for exchange in self.exchanges.values():
            try:
                await exchange.close()
            except Exception as e:
                logger.error(f"Error closing exchange {exchange.id}: {e}")

        # Closing all file descriptors
        for stream_key, writer in self._active_writers.items():
            try:
                lock = self._writer_locks.get(stream_key)
                if lock:
                    async with lock:
                        await writer.close()
                else:
                    await writer.close()
                logger.info(f"Closed file for stream {stream_key}")
            except Exception as e:
                logger.error(f"Error closing writer for {stream_key}: {e}")

        self._active_writers.clear()
        self._current_file_path.clear()

        # Waiting for tasks to complete (optional)
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if tasks:
            logger.info(f"Cancelling {len(tasks)} running tasks...")
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("Recorder stopped.")


async def main():
    try:
        with open("recorder_config.json", "r") as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.critical("Configuration file 'recorder_config.json' not found.")
        return
    except json.JSONDecodeError:
        logger.critical(
            "Error decoding 'recorder_config.json'. Please check its format."
        )
        return

    recorder = L2StreamRecorder(config)

    try:
        await recorder.start()
    except asyncio.CancelledError:
        logger.info("Main task cancelled.")
    finally:
        await recorder.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Recorder interrupted by user. Shutting down.")
