# bot_module/data_consumer.py

import asyncio
import json
import logging
import websockets  # Ensure it is imported
from websockets.protocol import State  # Changed from websockets.enums
from websockets.exceptions import (
    ConnectionClosed,
    ConnectionClosedOK,
    WebSocketException,
    ConnectionClosedError,
    InvalidURI,
)
from typing import List, Dict, Any, Optional, Set, Tuple, TYPE_CHECKING
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
import pandas as pd
import pandas_ta as ta  # noqa: F401  # Imported for DataFrame .ta accessor side-effect
import time  # For unique stream IDs
import math
import uuid

from bot_module import config
from .data_loader import download_klines, download_open_interest  # Ensure imported
from .utils import (
    calculate_scalper_natr,
    add_relative_volume,
    add_volume_percentile_rank,
)

try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover
    redis_asyncio = None

if TYPE_CHECKING:
    from bot_module.exchanges import ExchangeExecutor  # Exchange executor type hinting
    from bot_module.controller import TradingController  # Import for type hinting

logger = logging.getLogger("bot_module.data_consumer")
if not logging.getLogger("bot_module").hasHandlers():
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    logger.warning(
        "Root logger 'bot_module' has no handlers for DataConsumer. Basic config applied."
    )

# Constants for caches and WebSocket
DEFAULT_KLINE_CACHE_SIZE_CONFIG = getattr(
    config, "DEFAULT_KLINE_CACHE_SIZE", 5000
)  # Use common parameter
DEFAULT_TRADE_CACHE_SIZE = getattr(
    config, "DEFAULT_TRADE_CACHE_SIZE", 100
)  # For aggTrade
BINANCE_WS_RECONNECT_DELAY_BASE = 5  # Seconds
BINANCE_WS_MAX_RECONNECT_DELAY = 60  # Seconds

# New constants for tape metrics
TAPE_METRIC_WINDOWS = [5, 10, 30, 60, 120]  # Seconds

# ============================================================================================
# GLOBAL WEBSOCKET SUBSCRIPTION REGISTRY (for multi-user mode)
# Prevents duplication of WebSocket connections when multiple users
# trade the same symbols.
# ============================================================================================
_global_ws_registry_lock = asyncio.Lock()
# Format: {stream_key: {'task': asyncio.Task, 'client': websocket, 'ref_count': int, 'consumers': set()}}
_global_ws_registry: Dict[str, Dict[str, Any]] = {}

# event_queue registry for broadcast
# When the global WebSocket receives data, it broadcasts events to ALL
# registered queues, not just the subscription creator's queue.
# Format: {stream_key: Set[asyncio.Queue]}
_global_event_queues: Dict[str, Set[asyncio.Queue]] = defaultdict(set)
_global_event_queues_lock = asyncio.Lock()

# Shared data cache available to all DataConsumer
_global_kline_cache: Dict[str, deque] = defaultdict(
    lambda: deque(maxlen=DEFAULT_KLINE_CACHE_SIZE_CONFIG)
)
_global_kline_df_cache: Dict[str, pd.DataFrame] = {}
_global_depth_cache: Dict[str, Dict[str, Any]] = {}
_global_agg_trade_deques: Dict[str, deque] = defaultdict(lambda: deque())
_global_cache_lock = asyncio.Lock()
_global_history_loaded_keys: Set[str] = set()
_global_history_download_tasks: Dict[str, asyncio.Task] = {}

# Global cache of indicators and pair data
# All DataConsumers will read/write here to see the same indicators (ATR, SMA, etc.)
_global_active_pairs: Dict[str, Dict[str, Any]] = defaultdict(dict)
_global_pairs_lock = asyncio.Lock()


async def _is_global_stream_active(
    stream_key: str, task: Optional[asyncio.Task] = None
) -> bool:
    async with _global_ws_registry_lock:
        entry = _global_ws_registry.get(stream_key)
        if not entry or entry.get("ref_count", 0) <= 0:
            return False
        if task is not None and entry.get("task") is not task:
            return False
        return True


def _build_kline_dataframe_from_cache_rows(
    data_list: List[Tuple[Any, ...]],
) -> pd.DataFrame:
    cols = ["open_time", "open", "high", "low", "close", "volume"]
    if not data_list:
        empty_df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        empty_df.index = pd.DatetimeIndex([], name="open_time", tz="UTC")
        return empty_df

    df = pd.DataFrame(data_list, columns=cols)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time")
    numeric_cols = ["open", "high", "low", "close", "volume"]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    df.dropna(subset=numeric_cols, inplace=True)
    return df


def _upsert_kline_dataframe_cache(
    df: Optional[pd.DataFrame], candle_tuple: Tuple[Any, ...]
) -> pd.DataFrame:
    ts = pd.to_datetime(int(candle_tuple[0]), unit="ms", utc=True)
    values = [
        float(candle_tuple[1]),
        float(candle_tuple[2]),
        float(candle_tuple[3]),
        float(candle_tuple[4]),
        float(candle_tuple[5]),
    ]
    cols = ["open", "high", "low", "close", "volume"]

    if df is None or df.empty:
        new_df = pd.DataFrame([values], columns=cols)
        new_df.index = pd.DatetimeIndex([ts], name="open_time")
        return new_df

    if df.index[-1] == ts:
        df.iloc[-1] = values
        return df

    df.loc[ts, cols] = values
    if len(df) > DEFAULT_KLINE_CACHE_SIZE_CONFIG:
        return df.iloc[-DEFAULT_KLINE_CACHE_SIZE_CONFIG:].copy()
    return df


def _build_recent_trades_dataframe_from_cache_rows(
    trades_list: List[Dict[str, Any]],
) -> pd.DataFrame:
    if not trades_list:
        empty_df = pd.DataFrame(columns=["price", "quantity", "is_buyer_maker"])
        empty_df.index = pd.DatetimeIndex([], name="timestamp", tz="UTC")
        return empty_df

    df = pd.DataFrame(trades_list)
    df["price"] = pd.to_numeric(df["p"])
    df["quantity"] = pd.to_numeric(df["q"])
    df["timestamp"] = pd.to_datetime(df["T"], unit="ms", utc=True)
    df["is_buyer_maker"] = df["m"]
    df = df[["timestamp", "price", "quantity", "is_buyer_maker"]].copy()
    df.set_index("timestamp", inplace=True)
    return df


def normalize_symbol_for_binance(raw_symbol: str) -> str:
    """Normalizes the symbol name to the standard Binance format (e.g., BTCUSDT)."""
    normalized = raw_symbol.replace("/", "")
    if normalized.endswith(":USDT"):
        normalized = normalized[:-5]
    return normalized.upper()  # Always return in uppercase


def _normalize_market_type_for_cache(market_type: Optional[str]) -> str:
    raw = (
        str(market_type or config.TRADING_MARKET_TYPE or "futures_usdtm")
        .strip()
        .lower()
    )
    if raw in {"futures", "future", "futures_usdtm", "usdtm", "linear"}:
        return "futures_usdtm"
    if raw == "spot":
        return "spot"
    return raw


def _kline_cache_key(
    symbol: str,
    timeframe: str,
    exchange: str = "binance",
    market_type: Optional[str] = None,
) -> str:
    return f"{exchange}:{_normalize_market_type_for_cache(market_type)}:{symbol.upper()}:{timeframe}"


def _trade_cache_key(
    symbol: str, exchange: str = "binance", market_type: Optional[str] = None
) -> str:
    return (
        f"{exchange}:{_normalize_market_type_for_cache(market_type)}:{symbol.upper()}"
    )


def _market_data_redis_event_channel(stream_key: str) -> str:
    return f"{getattr(config, 'MARKET_DATA_REDIS_EVENT_CHANNEL_PREFIX', 'depthsight:market_data:events')}:{stream_key}"


def _market_data_redis_snapshot_key(stream_key: str) -> str:
    return f"{getattr(config, 'MARKET_DATA_REDIS_SNAPSHOT_KEY_PREFIX', 'depthsight:market_data:snapshot')}:{stream_key}"


class DataConsumer:
    def __init__(
        self,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        executor: Optional["ExchangeExecutor"] = None,
        event_queue: Optional[asyncio.Queue] = None,
        controller: Optional["TradingController"] = None,
        market_data_mode: Optional[str] = None,
        market_data_publish_callback: Optional[Any] = None,
    ):
        self.loop = loop or asyncio.get_event_loop()
        self._executor = executor
        self.trading_market_type = getattr(executor, "market_type", None)
        self._market_executors: Dict[str, "ExchangeExecutor"] = {}
        if executor is not None:
            self._market_executors[
                _normalize_market_type_for_cache(getattr(executor, "market_type", None))
            ] = executor
        self.event_queue = event_queue
        self.controller = controller  # New attribute
        self._running = False
        self._market_data_mode = (
            (
                market_data_mode
                or getattr(config, "MARKET_DATA_FANOUT_MODE", "direct")
                or "direct"
            )
            .strip()
            .lower()
        )
        self._use_redis_market_data = self._market_data_mode in {
            "redis",
            "redis_pubsub",
            "pubsub",
        }
        self._market_data_publish_callback = market_data_publish_callback
        self._market_data_subscriber_id = f"dc-{uuid.uuid4().hex}"
        self._redis_market_client: Optional[Any] = None
        self._redis_market_pubsub: Optional[Any] = None
        self._redis_market_listener_task: Optional[asyncio.Task] = None
        self._redis_market_stream_keys: Set[str] = set()
        self._redis_market_stream_specs: Dict[str, Dict[str, Any]] = {}
        self._redis_market_lock = asyncio.Lock()

        # Old caches and states (some will be replaced)
        self._active_pairs_from_main_app: List[
            Dict[str, Any]
        ] = []  # Used to get the list of symbols
        self._active_symbols_set: Set[str] = set()
        self._pairs_lock = asyncio.Lock()
        self.pair_update_queue = asyncio.Queue(maxsize=1)

        # WebSocket and subscription management (leave as is)
        self._main_app_ws_task: Optional[asyncio.Task] = None
        self._main_app_ws: Optional[websockets.WebSocketClientProtocol] = None
        self._main_app_ws_connect_lock = asyncio.Lock()
        self._main_app_ws_url = config.MAIN_APP_WS_URL
        self._required_streams_for_main_app: Set[str] = set()
        self._last_sent_subscriptions_to_main_app: Set[str] = set()
        self._binance_market_data_ws_tasks: Dict[str, asyncio.Task] = {}
        self._binance_market_data_clients: Dict[
            str, websockets.WebSocketClientProtocol
        ] = {}
        self._binance_market_data_ws_lock = asyncio.Lock()
        self._requested_binance_streams: Set[str] = set()

        # Raw data caches
        self.kline_deque_maxlen = DEFAULT_KLINE_CACHE_SIZE_CONFIG
        self._kline_cache: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self.kline_deque_maxlen)
        )
        self._latest_depth_cache: Dict[str, Dict[str, Any]] = {}
        self._aggtrade_cache_df: Dict[
            str, pd.DataFrame
        ] = {}  # Leave for backward compatibility if someone is using it
        self._open_interest_cache: Dict[str, pd.DataFrame] = {}
        self._data_cache_lock = asyncio.Lock()
        self._binance_market_data_base_url = (
            config.BINANCE_MARKET_DATA_WS_URL_FOR_CONSUMER
        )

        # Adjust URL for sandbox if necessary
        if self._executor and getattr(self._executor, "sandbox", False):
            if "binance" in getattr(self._executor, "exchange_id", ""):
                if "spot" in self._effective_market_type():
                    self._binance_market_data_base_url = (
                        config.BINANCE_SPOT_TESTNET_MARKET_DATA_WS_URL
                    )
                else:
                    self._binance_market_data_base_url = (
                        config.BINANCE_FUTURES_TESTNET_MARKET_DATA_WS_URL
                    )

        # NEW ATTRIBUTES for Specs
        # Central cache storing ALL data for the pair (price, indicators, metrics)
        self._active_pairs: Dict[str, Dict[str, Any]] = defaultdict(dict)

        # Cache for storing recent trades (aggTrade) in deque format
        self.agg_trade_maxlen_seconds = (
            300  # 5 minutes, maximum window for tape analysis
        )
        self._agg_trade_deques: Dict[str, deque] = defaultdict(lambda: deque())

        # Dictionary for storing necessary metrics and indicators for each symbol
        self._required_metrics: Dict[str, Set[str]] = defaultdict(set)
        self._metrics_lock = asyncio.Lock()  # Lock to protect _required_metrics

        # Loading history (no changes)
        self._history_download_semaphore = asyncio.Semaphore(
            getattr(config, "MAX_CONCURRENT_HISTORY_DOWNLOADS", 3)
        )
        self._history_loaded_keys: Set[str] = set()
        self._history_download_tasks: Dict[str, asyncio.Task] = {}

        # Valid symbol caches (unchanged)
        self._valid_symbols_cache: Dict[str, Set[str]] = {}
        self._valid_symbols_cache_last_update: Dict[str, float] = {}
        self._valid_symbols_cache_ttl: float = 3600.0 * 6
        self._valid_symbols_cache_lock = asyncio.Lock()

        logger.info(
            "DataConsumer initialized with new real-time processing capabilities."
        )

    def _effective_market_type(self) -> str:
        return getattr(self, "trading_market_type", None) or config.TRADING_MARKET_TYPE

    def set_market_executors(self, executors: Dict[str, "ExchangeExecutor"]) -> None:
        if not hasattr(self, "_market_executors"):
            self._market_executors = {}
        if not hasattr(self, "_executor"):
            self._executor = None
        for market_type, executor in (executors or {}).items():
            self._market_executors[_normalize_market_type_for_cache(market_type)] = (
                executor
            )

    def _executor_for_market(
        self, market_type: Optional[str] = None
    ) -> Optional["ExchangeExecutor"]:
        normalized = _normalize_market_type_for_cache(
            market_type or self._effective_market_type()
        )
        return self._market_executors.get(normalized) or self._executor

    async def start(self):
        if self._running:
            logger.warning("DataConsumer is already running.")
            return
        self._running = True
        logger.info("Starting DataConsumer... market_data_mode=%s", self._market_data_mode)
        if self._use_redis_market_data:
            started = await self._ensure_redis_market_data_started()
            logger.info(
                "_ensure_redis_market_data_started returned %s (client=%s pubsub=%s listener_task=%s)",
                started,
                self._redis_market_client is not None,
                self._redis_market_pubsub is not None,
                self._redis_market_listener_task is not None and not self._redis_market_listener_task.done(),
            )
            if not started:
                self._running = False
                return

        # NEW SOURCE SELECTION LOGIC
        source_mode = getattr(config, "SYMBOL_SOURCE_MODE", "MAIN_APP").upper()
        logger.info(f"Symbol source mode: {source_mode}")

        if source_mode == "MAIN_APP":
            if (
                websockets
                and self._main_app_ws_url
                and self._main_app_ws_url.startswith(("ws://", "wss://"))
            ):
                self._main_app_ws_task = self.loop.create_task(
                    self._main_app_ws_loop(), name="MainAppWSLoop"
                )
            else:
                logger.critical(
                    f"SYMBOL_SOURCE_MODE is 'MAIN_APP', but MAIN_APP_WS_URL ('{self._main_app_ws_url}') is not configured or invalid. DataConsumer cannot get symbols."
                )
                self._running = False
                return
        elif source_mode == "STATIC_LIST":
            logger.info("Using STATIC_LIST as symbol source.")
            static_symbols = getattr(config, "SYMBOL_SOURCE_STATIC_LIST", [])
            if not static_symbols:
                logger.error(
                    "STATIC_LIST mode is enabled, but SYMBOL_SOURCE_STATIC_LIST is empty in config."
                )
            else:
                # Convert the list of strings into the format expected by _update_active_pairs_from_ws
                # We don't know all the details (atr, price), so we only pass the symbol
                pairs_data = [{"symbol": sym.upper()} for sym in static_symbols]
                await self._update_active_pairs_from_ws(pairs_data)
                # Signaling the controller that the list is ready
                self.pair_update_queue.put_nowait(True)

        elif source_mode == "JSON_FILE":
            json_path = getattr(config, "SYMBOL_SOURCE_JSON_FILE_PATH", None)
            logger.info(f"Using JSON_FILE ('{json_path}') as symbol source.")
            if not json_path:
                logger.error(
                    "JSON_FILE mode enabled, but SYMBOL_SOURCE_JSON_FILE_PATH is not configured."
                )
            else:
                try:
                    with open(json_path, "r") as f:
                        symbols_from_file = json.load(f)
                    if isinstance(symbols_from_file, list) and all(
                        isinstance(s, str) for s in symbols_from_file
                    ):
                        pairs_data = [
                            {"symbol": sym.upper()} for sym in symbols_from_file
                        ]
                        await self._update_active_pairs_from_ws(pairs_data)
                        self.pair_update_queue.put_nowait(True)
                    else:
                        logger.error(
                            f"Invalid format in {json_path}. Expected a JSON array of strings."
                        )
                except FileNotFoundError:
                    logger.error(f"JSON file not found at path: {json_path}")
                except json.JSONDecodeError:
                    logger.error(f"Error decoding JSON from file: {json_path}")
        else:
            logger.error(
                f"Unknown SYMBOL_SOURCE_MODE: '{source_mode}'. DataConsumer will not receive symbols."
            )
        # END OF NEW LOGIC

        logger.info("DataConsumer started.")

    async def stop(self):
        if not self._running:
            logger.info("DataConsumer is not running.")
            return
        logger.info("Stopping DataConsumer...")
        self._running = False

        # Main App WebSocket Shutdown
        main_app_task_ref: Optional[asyncio.Task] = None
        main_app_client_ref: Optional[websockets.WebSocketClientProtocol] = None

        if self._main_app_ws_task and not self._main_app_ws_task.done():
            self._main_app_ws_task.cancel()
            main_app_task_ref = self._main_app_ws_task

        # Store client ref and clear instance variable to prevent re-use
        main_app_client_ref = self._main_app_ws
        self._main_app_ws = None

        await asyncio.sleep(0)  # Allow cancellation to propagate for main_app_ws_task

        if main_app_client_ref and main_app_client_ref.state == State.OPEN:
            client_path_info = (
                main_app_client_ref.path
                if hasattr(main_app_client_ref, "path")
                else "N/A"
            )
            logger.debug(
                f"Attempting to close Main App WebSocket client (Path: {client_path_info})."
            )
            try:
                await asyncio.wait_for(
                    main_app_client_ref.close(
                        code=1000, reason="DataConsumer stopping"
                    ),
                    timeout=2.0,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"Timeout closing Main App WS client (Path: {client_path_info})."
                )
            except Exception as e:
                logger.error(
                    f"Error closing Main App WS client (Path: {client_path_info}): {e}",
                    exc_info=True,
                )

        if main_app_task_ref:
            logger.debug(
                f"DataConsumer waiting for Main App WS task ({main_app_task_ref.get_name()}) to complete cancellation..."
            )
            try:
                # No shield, directly await with gather for consistent error handling
                results = await asyncio.gather(
                    main_app_task_ref, return_exceptions=True
                )
                res = results[0]  # Since it's a single task in gather
                task_name = main_app_task_ref.get_name()
                if isinstance(res, asyncio.CancelledError):
                    logger.debug(f"Task {task_name} was cancelled as expected.")
                elif isinstance(res, Exception):
                    logger.error(
                        f"Error during cancellation of task {task_name}: {res}",
                        exc_info=res
                        if not isinstance(res, asyncio.CancelledError)
                        else False,
                    )
            except (
                Exception
            ) as e_gather_main:  # Should not happen with return_exceptions=True
                logger.error(
                    f"Unexpected error gathering Main App WS task: {e_gather_main}",
                    exc_info=True,
                )

        # Binance Market Data WebSockets Shutdown
        await self.clear_all_subscriptions()

        binance_tasks_to_await_refs: List[asyncio.Task] = []
        binance_clients_to_close_refs: List[websockets.WebSocketClientProtocol] = []

        async with self._binance_market_data_ws_lock:
            for task_id, task in list(
                self._binance_market_data_ws_tasks.items()
            ):  # Iterate over a copy
                if task and not task.done():
                    task.cancel()
                    binance_tasks_to_await_refs.append(task)

                client = self._binance_market_data_clients.pop(task_id, None)
                if client:
                    binance_clients_to_close_refs.append(client)
            self._binance_market_data_ws_tasks.clear()  # Clear the tasks dict

        await asyncio.sleep(0)  # Allow cancellation to propagate for Binance tasks

        # Close Binance clients
        for client in binance_clients_to_close_refs:
            if client and client.state == State.OPEN:
                logger.debug(
                    f"Attempting to close Binance WS client (Path: {client.path})."
                )
                try:
                    await asyncio.wait_for(
                        client.close(code=1000, reason="DataConsumer stopping"),
                        timeout=2.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        f"Timeout closing a Binance WS client (Path: {client.path})."
                    )
                except Exception as e:
                    logger.error(
                        f"Error closing a Binance WS client (Path: {client.path}): {e}",
                        exc_info=True,
                    )

        # Await Binance tasks
        if binance_tasks_to_await_refs:
            logger.debug(
                f"DataConsumer waiting for {len(binance_tasks_to_await_refs)} Binance WS tasks to complete cancellation..."
            )
            results = await asyncio.gather(
                *binance_tasks_to_await_refs, return_exceptions=True
            )
            for i, res in enumerate(results):
                task = binance_tasks_to_await_refs[i]
                task_name = (
                    task.get_name() if hasattr(task, "get_name") else f"BinanceTask_{i}"
                )
                if isinstance(res, asyncio.CancelledError):
                    logger.debug(f"Task {task_name} was cancelled as expected.")
                elif isinstance(res, Exception):
                    logger.error(
                        f"Error or unexpected result during cancellation of task {task_name}: {res}",
                        exc_info=res
                        if not isinstance(res, asyncio.CancelledError)
                        else False,
                    )

        if hasattr(self, "pair_update_queue"):
            while not self.pair_update_queue.empty():
                try:
                    self.pair_update_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

        if (
            self._redis_market_listener_task
            and not self._redis_market_listener_task.done()
        ):
            self._redis_market_listener_task.cancel()
            try:
                await asyncio.gather(
                    self._redis_market_listener_task, return_exceptions=True
                )
            except Exception:
                pass
        self._redis_market_listener_task = None
        if self._redis_market_pubsub:
            try:
                await self._redis_market_pubsub.close()
            except Exception:
                logger.debug("Error closing Redis market-data pubsub.", exc_info=True)
            self._redis_market_pubsub = None
        if self._redis_market_client:
            try:
                await self._redis_market_client.close()
            except Exception:
                logger.debug("Error closing Redis market-data client.", exc_info=True)
            self._redis_market_client = None

        logger.info("DataConsumer stopped.")

    async def get_active_pairs(self) -> List[Dict[str, Any]]:
        async with self._pairs_lock:
            return list(self._active_pairs_from_main_app)

    async def get_active_symbols(self) -> Set[str]:
        async with self._pairs_lock:
            return self._active_symbols_set.copy()

    async def _get_kline_history_legacy(
        self, symbol: str, timeframe: str, limit: int = DEFAULT_KLINE_CACHE_SIZE_CONFIG
    ) -> Optional[pd.DataFrame]:
        cache_key = f"{symbol.upper()}:{timeframe}"
        log_prefix_get = f"[DataConsumerGetKline:{cache_key}]"
        df: Optional[pd.DataFrame] = None
        # Using GLOBAL cache for multi-user mode
        async with _global_cache_lock:
            cache_deque = _global_kline_cache.get(cache_key)
            if cache_deque:
                cols = ["open_time", "open", "high", "low", "close", "volume"]
                try:
                    data_list = list(cache_deque)[-limit:]
                    if not data_list:
                        df = pd.DataFrame(columns=cols).set_index(pd.to_datetime([]))
                    else:
                        df = pd.DataFrame(data_list, columns=cols)
                        df["open_time"] = pd.to_datetime(
                            df["open_time"], unit="ms", utc=True
                        )
                        df = df.set_index("open_time")
                        numeric_cols = ["open", "high", "low", "close", "volume"]
                        df[numeric_cols] = df[numeric_cols].apply(
                            pd.to_numeric, errors="coerce"
                        )
                        df.dropna(subset=numeric_cols, inplace=True)
                except Exception as e:
                    logger.error(
                        f"Error converting kline cache for {cache_key} to DataFrame: {e}"
                    )
                    df = None

                if df is None or df.empty:
                    logger.warning(
                        f"{log_prefix_get} Returning EMPTY or None DataFrame from cache after processing. Deque length was {len(cache_deque) if cache_deque else 'N/A'}."
                    )
                    return df
                else:
                    logger.debug(
                        f"{log_prefix_get} Returning DataFrame with {len(df)} rows from cache. Last candle time: {df.index[-1] if not df.empty else 'N/A'}"
                    )
                    return df.copy()
            else:
                logger.warning(
                    f"{log_prefix_get} No kline data IN CACHE (deque not found). Returning None."
                )
                return None

    async def get_kline_history(
        self,
        symbol: str,
        timeframe: str,
        limit: int = DEFAULT_KLINE_CACHE_SIZE_CONFIG,
        market_type: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        executor = self._executor_for_market(market_type)
        exchange_id = (
            getattr(executor, "exchange_id", "binance") if executor else "binance"
        )
        if getattr(executor, "sandbox", False):
            if not exchange_id.endswith("_testnet"):
                exchange_id = f"{exchange_id}_testnet"
        cache_key = _kline_cache_key(
            symbol, timeframe, exchange_id, market_type or self._effective_market_type()
        )
        log_prefix_get = f"[DataConsumerGetKline:{cache_key}]"
        data_list: List[Tuple[Any, ...]] = []
        deque_len = 0

        # Copy raw cache rows under the lock, then build the DataFrame off the event loop.
        async with _global_cache_lock:
            cached_df = _global_kline_df_cache.get(cache_key)
            if cached_df is not None:
                result_df = (
                    cached_df.iloc[-limit:].copy()
                    if limit and limit < len(cached_df)
                    else cached_df.copy()
                )
                if result_df.empty:
                    logger.warning(
                        f"{log_prefix_get} Returning EMPTY or None DataFrame from cached snapshot."
                    )
                else:
                    logger.debug(
                        f"{log_prefix_get} Returning DataFrame with {len(result_df)} rows from cached snapshot. Last candle time: {result_df.index[-1] if not result_df.empty else 'N/A'}"
                    )
                return result_df

            cache_deque = _global_kline_cache.get(cache_key)
            if cache_deque:
                deque_len = len(cache_deque)
                data_list = list(cache_deque)[-limit:]

        if not data_list:
            if deque_len > 0:
                empty_df = _build_kline_dataframe_from_cache_rows(data_list)
                logger.warning(
                    f"{log_prefix_get} Returning EMPTY or None DataFrame from cache after processing. Deque length was {deque_len}."
                )
                return empty_df
            legacy_cache_key = f"{symbol.upper()}:{timeframe}"
            if legacy_cache_key != cache_key:
                cache_deque = _global_kline_cache.get(legacy_cache_key)
                if cache_deque:
                    data_list = list(cache_deque)[-limit:]
                    deque_len = len(cache_deque)
                else:
                    logger.warning(
                        f"{log_prefix_get} No kline data IN CACHE (deque not found). Returning None."
                    )
                    return None
            else:
                logger.warning(
                    f"{log_prefix_get} No kline data IN CACHE (deque not found). Returning None."
                )
                return None

        try:
            df = await asyncio.to_thread(
                _build_kline_dataframe_from_cache_rows, data_list
            )
        except Exception as e:
            logger.error(
                f"Error converting kline cache for {cache_key} to DataFrame: {e}"
            )
            return None

        async with _global_cache_lock:
            if cache_key not in _global_kline_df_cache and not df.empty:
                _global_kline_df_cache[cache_key] = df.copy()

        if df.empty:
            logger.warning(
                f"{log_prefix_get} Returning EMPTY or None DataFrame from cache after processing. Deque length was {deque_len or 'N/A'}."
            )
            return df

        logger.debug(
            f"{log_prefix_get} Returning DataFrame with {len(df)} rows from cache. Last candle time: {df.index[-1] if not df.empty else 'N/A'}"
        )
        return df.copy()

    def _normalize_depth_levels(
        self, levels: Any, max_levels: Optional[int] = None
    ) -> List[List[float]]:
        """
        Normalize depth levels to [[price, qty], ...] float pairs.
        Invalid rows are skipped.
        """
        if not isinstance(levels, list) or not levels:
            return []

        limit = len(levels) if max_levels is None else min(len(levels), max_levels)
        normalized: List[List[float]] = []
        for i in range(limit):
            level = levels[i]
            if not isinstance(level, (list, tuple)) or len(level) < 2:
                continue
            try:
                price = float(level[0])
                qty = float(level[1])
            except (ValueError, TypeError):
                continue
            if price <= 0 or qty <= 0:
                continue
            normalized.append([price, qty])
        return normalized

    async def get_latest_depth(
        self, symbol: str, market_type_requested: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        uc_symbol = symbol.upper()

        # Normalization of market_type_requested for the cache key
        market_type_for_cache_lookup = (
            self._effective_market_type().lower()
        )  # By default
        if market_type_requested:
            market_type_for_cache_lookup = market_type_requested.lower()

        if market_type_for_cache_lookup == "futures_usdtm":
            market_type_for_cache_lookup = "futures"

        cache_key = f"{uc_symbol}_{market_type_for_cache_lookup}"

        log_prefix = f"[GetLatestDepth:{symbol}(uc:{uc_symbol},mkt_req:{market_type_requested},mkt_key_lookup:{market_type_for_cache_lookup})->CacheKey:'{cache_key}']"

        async with self._data_cache_lock:
            depth_data = self._latest_depth_cache.get(cache_key)
            if depth_data:
                # Backfill old cache records to enriched format on first read.
                if "full_l2_depth" not in depth_data:
                    bids = self._normalize_depth_levels(depth_data.get("bids", []))
                    asks = self._normalize_depth_levels(depth_data.get("asks", []))
                    full_l2_depth = {
                        "lastUpdateId": depth_data.get("lastUpdateId"),
                        "bids": bids,
                        "asks": asks,
                    }
                    market_price = (
                        (bids[0][0] + asks[0][0]) / 2.0 if bids and asks else 0.0
                    )
                    aggregated_depth = (
                        self._aggregate_depth(full_l2_depth, market_price)
                        if market_price > 0
                        else {"bids": [], "asks": []}
                    )
                    depth_data = {
                        **depth_data,
                        "bids": bids,
                        "asks": asks,
                        "full_l2_depth": full_l2_depth,
                        "aggregated_depth": aggregated_depth,
                        "cached_at_ms": int(
                            depth_data.get("cached_at_ms") or (time.time() * 1000)
                        ),
                    }
                    self._latest_depth_cache[cache_key] = depth_data

                logger.debug(
                    f"{log_prefix} Data FOUND in cache. LastUpdateId: {depth_data.get('lastUpdateId')}, Bids: {len(depth_data.get('bids', []))}, Asks: {len(depth_data.get('asks', []))}"
                )
                return depth_data.copy()
            else:
                logger.debug(
                    f"{log_prefix} Data NOT FOUND in cache for key '{cache_key}'. "
                    f"Known keys in _latest_depth_cache: {list(self._latest_depth_cache.keys())}"
                )
                return None

    async def _get_recent_trades_legacy(
        self, symbol: str, limit: int = DEFAULT_TRADE_CACHE_SIZE
    ) -> Optional[pd.DataFrame]:
        """
        Gets the latest aggTrade deals from the global cache _global_agg_trade_deques.
        IMPORTANT: Data is written to _global_agg_trade_deques, not to _aggtrade_cache_df!
        """
        uc_symbol = symbol.upper()

        # Reading from the global cache where data is actually written
        trade_deque = _global_agg_trade_deques.get(uc_symbol)

        if trade_deque and len(trade_deque) > 0:
            # Convert deque to DataFrame
            trades_list = list(trade_deque)[-limit:]  # Take the last N records
            if trades_list:
                try:
                    df = pd.DataFrame(trades_list)
                    # Renaming columns for compatibility with the ML model
                    df["price"] = pd.to_numeric(df["p"])
                    df["quantity"] = pd.to_numeric(df["q"])
                    df["timestamp"] = pd.to_datetime(df["T"], unit="ms", utc=True)
                    df["is_buyer_maker"] = df["m"]
                    df = df[["timestamp", "price", "quantity", "is_buyer_maker"]].copy()
                    df.set_index("timestamp", inplace=True)
                    logger.debug(
                        f"[get_recent_trades] Returning {len(df)} trades for {uc_symbol}"
                    )
                    return df
                except Exception as e:
                    logger.error(
                        f"[get_recent_trades] Error converting trade deque to DataFrame for {uc_symbol}: {e}"
                    )
                    return None

        logger.debug(f"[get_recent_trades] No aggTrade data in cache for {uc_symbol}")
        return None

    async def get_recent_trades(
        self,
        symbol: str,
        limit: int = DEFAULT_TRADE_CACHE_SIZE,
        market_type: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Gets the latest aggTrade deals from the global cache _global_agg_trade_deques.
        IMPORTANT: Data is written to _global_agg_trade_deques, not to _aggtrade_cache_df!
        """
        uc_symbol = symbol.upper()
        executor = self._executor_for_market(market_type)
        exchange_id = (
            getattr(executor, "exchange_id", "binance") if executor else "binance"
        )
        if getattr(executor, "sandbox", False):
            if not exchange_id.endswith("_testnet"):
                exchange_id = f"{exchange_id}_testnet"

        trade_deque = _global_agg_trade_deques.get(
            _trade_cache_key(
                uc_symbol, exchange_id, market_type or self._effective_market_type()
            )
        )
        if not trade_deque:
            trade_deque = _global_agg_trade_deques.get(uc_symbol)

        if trade_deque and len(trade_deque) > 0:
            # Copy raw rows first, then offload DataFrame construction from the event loop.
            trades_list = list(trade_deque)[-limit:]
            if trades_list:
                try:
                    df = await asyncio.to_thread(
                        _build_recent_trades_dataframe_from_cache_rows, trades_list
                    )
                    logger.debug(
                        f"[get_recent_trades] Returning {len(df)} trades for {uc_symbol}"
                    )
                    return df
                except Exception as e:
                    logger.error(
                        f"[get_recent_trades] Error converting trade deque to DataFrame for {uc_symbol}: {e}"
                    )
                    return None

        logger.debug(f"[get_recent_trades] No aggTrade data in cache for {uc_symbol}")
        return None

    async def get_open_interest(
        self, symbol: str, limit: int = 100
    ) -> Optional[pd.DataFrame]:
        # This is a placeholder. In a real implementation, this would fetch data from the exchange.
        # For now, we will return a dummy DataFrame.
        async with self._data_cache_lock:
            df = self._open_interest_cache.get(symbol.upper())
            if df is not None and not df.empty:
                return df.iloc[-limit:].copy()
            else:
                # Create a dummy dataframe
                data = {
                    "timestamp": pd.to_datetime(
                        pd.date_range(
                            end=datetime.now(timezone.utc), periods=100, freq="1min"
                        )
                    ),
                    "open_interest": [100 + i + (i * 0.1) for i in range(100)],
                }
                df = pd.DataFrame(data).set_index("timestamp")
                self._open_interest_cache[symbol.upper()] = df
                return df.iloc[-limit:].copy()

    async def _get_valid_symbols_from_exchange_info(
        self, market_type_to_fetch: str, force_update: bool = False
    ) -> Set[str]:
        log_prefix_val_sym = f"[ValidSymbolsFetch:{market_type_to_fetch}]"
        async with self._valid_symbols_cache_lock:
            now = time.time()
            cached_symbols = self._valid_symbols_cache.get(market_type_to_fetch)
            last_update = self._valid_symbols_cache_last_update.get(
                market_type_to_fetch, 0.0
            )

            if (
                not force_update
                and cached_symbols is not None
                and (now - last_update < self._valid_symbols_cache_ttl)
            ):
                logger.debug(
                    f"{log_prefix_val_sym} Returning {len(cached_symbols)} symbols from cache."
                )
                return cached_symbols.copy()

            executor = self._executor_for_market(market_type_to_fetch)
            if executor is None:
                logger.error(f"{log_prefix_val_sym} Executor instance not available.")
                return cached_symbols.copy() if cached_symbols is not None else set()

            logger.info(
                f"{log_prefix_val_sym} Updating valid symbols cache from exchange info..."
            )
            try:
                exchange_info_data = await executor.fetch_exchange_info(
                    force_update=True, specific_market_type=market_type_to_fetch
                )

                new_symbols_set = set()
                if not exchange_info_data or not isinstance(
                    exchange_info_data.get("symbols"), list
                ):
                    logger.error(
                        f"{log_prefix_val_sym} Failed to fetch or parse valid symbols list for {market_type_to_fetch}. Response: {exchange_info_data}"
                    )
                    return (
                        cached_symbols.copy() if cached_symbols is not None else set()
                    )

                symbols_from_api = exchange_info_data["symbols"]

                if market_type_to_fetch == "spot":
                    for s_data in symbols_from_api:
                        # More robust check for spot symbols
                        is_spot = s_data.get("isSpotTradingAllowed", False)
                        if s_data.get("status") == "TRADING" and is_spot:
                            new_symbols_set.add(s_data["symbol"])

                elif market_type_to_fetch == "futures_usdtm":
                    for s_data in symbols_from_api:
                        if (
                            s_data.get("status") == "TRADING"
                            and s_data.get("contractType") == "PERPETUAL"
                            and s_data.get("quoteAsset") == "USDT"
                            and "pair" in s_data
                        ):
                            new_symbols_set.add(s_data["pair"])

                self._valid_symbols_cache[market_type_to_fetch] = new_symbols_set
                self._valid_symbols_cache_last_update[market_type_to_fetch] = (
                    time.time()
                )
                logger.info(
                    f"{log_prefix_val_sym} Cache updated. Found {len(new_symbols_set)} valid TRADING symbols for {market_type_to_fetch}."
                )
                return new_symbols_set.copy()

            except Exception as e:
                logger.error(
                    f"{log_prefix_val_sym} Error updating symbols cache for {market_type_to_fetch}: {e}",
                    exc_info=True,
                )
                return cached_symbols.copy() if cached_symbols is not None else set()

    def _stream_specs_for_subscription(
        self,
        data_type_key: str,
        symbol: str,
        needs_companion_orderbook: bool = False,
        market_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        uc_symbol = symbol.upper()
        lc_symbol = symbol.lower()
        effective_market_type = _normalize_market_type_for_cache(
            market_type or self._effective_market_type()
        )
        markets_to_subscribe: Set[str] = set()

        if data_type_key == "depth":
            markets_to_subscribe.add(effective_market_type)
            if needs_companion_orderbook and config.USE_COMPANION_ORDERBOOK_ANALYSIS:
                if (
                    effective_market_type == "futures_usdtm"
                    and config.ANALYZE_SPOT_ORDERBOOK_FOR_FUTURES_TRADES
                ):
                    markets_to_subscribe.add("spot")
                elif (
                    effective_market_type == "spot"
                    and config.ANALYZE_FUTURES_ORDERBOOK_FOR_SPOT_TRADES
                ):
                    markets_to_subscribe.add("futures_usdtm")
        else:
            markets_to_subscribe.add(effective_market_type)

        specs: List[Dict[str, Any]] = []
        for market_type_sub in markets_to_subscribe:
            executor_for_market = self._executor_for_market(market_type_sub)
            exchange_id = (
                getattr(executor_for_market, "exchange_id", "binance")
                if executor_for_market
                else "binance"
            )
            if getattr(
                executor_for_market, "sandbox", False
            ) and not exchange_id.endswith("_testnet"):
                exchange_id = f"{exchange_id}_testnet"

            if data_type_key == "depth":
                stream_suffix = getattr(config, "BINANCE_DEPTH_STREAM_NAME", "@depth")
            elif data_type_key.startswith("kline_"):
                timeframe = data_type_key.split("_", 1)[1]
                stream_suffix = f"@kline_{timeframe}"
            elif data_type_key == "aggTrade":
                stream_suffix = "@aggTrade"
            elif data_type_key == "open_interest":
                stream_suffix = "@openInterest"
            else:
                continue

            stream_part = f"{lc_symbol}{stream_suffix}"
            stream_key = f"{exchange_id}:{market_type_sub}:{stream_part}"
            specs.append(
                {
                    "stream_key": stream_key,
                    "stream_part": stream_part,
                    "exchange_id": exchange_id,
                    "market_type": market_type_sub,
                    "data_type_key": data_type_key,
                    "symbol": uc_symbol,
                    "needs_companion_orderbook": needs_companion_orderbook,
                }
            )
        logger.debug("_stream_specs_for_subscription(%s, %s) -> %s", data_type_key, symbol, specs)
        return specs

    async def _ensure_redis_market_data_started(self) -> bool:
        if not self._use_redis_market_data:
            return True
        if redis_asyncio is None:
            logger.error(
                "redis.asyncio is not available; Redis market-data fan-out cannot start."
            )
            return False
        async with self._redis_market_lock:
            if self._redis_market_client is None:
                self._redis_market_client = redis_asyncio.Redis(
                    host=config.MARKET_REDIS_HOST,
                    port=config.MARKET_REDIS_PORT,
                    db=config.MARKET_REDIS_DB,
                    username=config.REDIS_USERNAME,
                    password=config.REDIS_PASSWORD,
                    decode_responses=True,
                )
                self._redis_market_pubsub = self._redis_market_client.pubsub()
                # Verify Redis connectivity immediately
                try:
                    await self._redis_market_client.ping()
                    logger.info("Redis market client PING OK (host=%s port=%s db=%s user=%s)",
                                config.MARKET_REDIS_HOST, config.MARKET_REDIS_PORT,
                                config.MARKET_REDIS_DB, config.REDIS_USERNAME)
                except Exception as e:
                    logger.error("Redis market client PING FAILED (host=%s port=%s db=%s user=%s): %s",
                                 config.MARKET_REDIS_HOST, config.MARKET_REDIS_PORT,
                                 config.MARKET_REDIS_DB, config.REDIS_USERNAME, e,
                                 exc_info=True)
            if (
                self._redis_market_listener_task is None
                or self._redis_market_listener_task.done()
            ):
                self._redis_market_listener_task = self.loop.create_task(
                    self._redis_market_data_listener(),
                    name=f"RedisMarketDataListener_{self._market_data_subscriber_id}",
                )
        return True

    async def _publish_market_data_command(self, payload: Dict[str, Any]) -> None:
        if not await self._ensure_redis_market_data_started():
            return
        assert self._redis_market_client is not None
        await self._redis_market_client.publish(
            getattr(
                config,
                "MARKET_DATA_REDIS_COMMAND_CHANNEL",
                "depthsight:market_data:commands",
            ),
            json.dumps(payload),
        )

    async def _redis_market_data_listener(self) -> None:
        log_prefix = f"[RedisMarketData:{self._market_data_subscriber_id}]"
        logger.info("%s listener started. mode=%s host=%s:%s db=%s user=%s", log_prefix,
                    self._market_data_mode,
                    config.MARKET_REDIS_HOST, config.MARKET_REDIS_PORT,
                    config.MARKET_REDIS_DB, config.REDIS_USERNAME)
        last_heartbeat_log = time.monotonic()
        pubsub_broken_since: float = 0.0
        had_subscriptions: bool = False
        try:
            while True:
                if not self._redis_market_pubsub:
                    await asyncio.sleep(0.1)
                    continue
                # Heartbeat log every 30s to confirm listener is alive
                if time.monotonic() - last_heartbeat_log > 30:
                    logger.info("%s listener alive. stream_keys=%d",
                                log_prefix,
                                len(self._redis_market_stream_keys),
                                )
                    last_heartbeat_log = time.monotonic()
                try:
                    # MUST hold lock: get_message and subscribe share the same pubsub connection.
                    # A real redis-py PubSub read with timeout=0.0 is a pure poll and can
                    # repeatedly return None under load; wait briefly for socket data instead.
                    async with self._redis_market_lock:
                        message = await self._redis_market_pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=1.0
                        )
                    if not message:
                        continue
                except RuntimeError as e:
                    if "pubsub connection not set" in str(e):
                        has_subs = len(self._redis_market_stream_keys) > 0
                        now = time.monotonic()
                        if not has_subs and not had_subscriptions:
                            # Expected: pubsub not subscribed yet — wait silently
                            await asyncio.sleep(0.1)
                            continue
                        # We HAVE subscriptions but connection dropped — track/report
                        had_subscriptions = True
                        if pubsub_broken_since == 0:
                            pubsub_broken_since = now
                            logger.warning("%s pubsub connection dropped after subscribe, will retry... (stream_keys=%d)",
                                           log_prefix, len(self._redis_market_stream_keys))
                        elif now - pubsub_broken_since > 10:
                            logger.error("%s pubsub broken for 10s after subscribe. Attempting reconnect... (stream_keys=%d)",
                                         log_prefix, len(self._redis_market_stream_keys))
                            async with self._redis_market_lock:
                                self._redis_market_pubsub = self._redis_market_client.pubsub()
                                for sk in list(self._redis_market_stream_keys):
                                    ch = _market_data_redis_event_channel(sk)
                                    try:
                                        await self._redis_market_pubsub.subscribe(ch)
                                    except Exception as sub_e:
                                        logger.error("%s reconnect subscribe failed for %s: %s", log_prefix, sk, sub_e)
                            logger.info("%s reconnect attempt finished.", log_prefix)
                            pubsub_broken_since = 0
                            had_subscriptions = False
                        await asyncio.sleep(0.5)
                        continue
                    raise
                else:
                    pubsub_broken_since = 0

                if not message:
                    continue
                msg_type = message.get("type")
                if isinstance(msg_type, bytes):
                    msg_type = msg_type.decode("utf-8")
                if msg_type != "message":
                    logger.debug(
                        "%s ignored Redis pubsub envelope: type=%r channel=%r",
                        log_prefix,
                        msg_type,
                        message.get("channel"),
                    )
                    continue
                try:
                    raw = message.get("data")
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    payload = json.loads(raw) if isinstance(raw, str) else raw
                    await self._handle_redis_market_payload(payload)
                except Exception as e:
                    logger.error(
                        "%s failed to process market payload: %s",
                        log_prefix,
                        e,
                        exc_info=True,
                    )
        except asyncio.CancelledError:
            logger.info("%s listener cancelled.", log_prefix)
        finally:
            logger.info("%s listener stopped.", log_prefix)

    async def _handle_redis_market_payload(self, message: Dict[str, Any]) -> None:
        if not isinstance(message, dict):
            return
        if message.get("type") == "indicator_update":
            await self._apply_pair_state_update(message)
            return
        if message.get("type") != "market_payload":
            return
        stream_key = message.get("stream_key")
        if stream_key not in self._redis_market_stream_keys:
            logger.warning(
                "[RedisMarketData] Received market_payload for UNSUBSCRIBED stream_key=%s",
                stream_key,
            )
            return
        logger.debug(
            "[RedisMarketData] Received market_payload: stream_key=%s symbol=%s data_type=%s",
            stream_key,
            message.get("symbol"),
            message.get("data_type_key"),
        )
        await self._update_local_cache(
            str(message.get("data_type_key") or ""),
            str(message.get("symbol") or ""),
            message.get("payload"),
            market_type=message.get("market_type"),
            exchange_id=message.get("exchange_id") or "binance",
        )

    async def _apply_pair_state_update(self, message: Dict[str, Any]) -> bool:
        stream_key = message.get("stream_key")
        if stream_key and stream_key not in self._redis_market_stream_keys:
            return False
        symbol = str(message.get("symbol") or "").upper()
        if not symbol:
            return False
        updates: Dict[str, Any] = {}
        for source_key in ("pair_state", "indicators", "metrics"):
            source_value = message.get(source_key)
            if isinstance(source_value, dict):
                updates.update(source_value)
        if not updates:
            return False
        clean_updates: Dict[str, Any] = {}
        for key, value in updates.items():
            if value is None:
                continue
            if isinstance(value, (int, float, str, bool)):
                clean_updates[str(key)] = value
        if not clean_updates:
            return False
        async with _global_pairs_lock:
            _global_active_pairs[symbol].update(clean_updates)
        async with self._pairs_lock:
            local_pair_state = self._active_pairs.get(symbol, {})
            local_pair_state.update(clean_updates)
            self._active_pairs[symbol] = local_pair_state
        return True

    async def _load_market_snapshot_from_redis(self, spec: Dict[str, Any]) -> bool:
        if not self._redis_market_client:
            return False
        stream_key = spec.get("stream_key")
        if not stream_key:
            return False
        raw = await self._redis_market_client.get(
            _market_data_redis_snapshot_key(str(stream_key))
        )
        if not raw:
            return False
        try:
            snapshot = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            logger.warning("[RedisMarketData] Invalid snapshot JSON for %s", stream_key)
            return False
        return await self._apply_market_snapshot(snapshot)

    async def _wait_for_market_snapshot_from_redis(self, spec: Dict[str, Any]) -> bool:
        wait_seconds = float(
            getattr(config, "MARKET_DATA_REDIS_SNAPSHOT_WAIT_SECONDS", 5.0)
        )
        if wait_seconds <= 0:
            return await self._load_market_snapshot_from_redis(spec)
        deadline = time.monotonic() + wait_seconds
        while True:
            if await self._load_market_snapshot_from_redis(spec):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.1)

    async def _apply_market_snapshot(self, snapshot: Dict[str, Any]) -> bool:
        if not isinstance(snapshot, dict) or snapshot.get("type") != "market_snapshot":
            return False
        data_type_key = str(snapshot.get("data_type_key") or "")
        symbol = str(snapshot.get("symbol") or "").upper()
        market_type = snapshot.get("market_type")
        exchange_id = snapshot.get("exchange_id") or "binance"
        if not data_type_key or not symbol:
            return False

        async with _global_cache_lock:
            if data_type_key.startswith("kline_"):
                timeframe = data_type_key.split("_", 1)[1]
                cache_key = _kline_cache_key(
                    symbol, timeframe, exchange_id, market_type
                )
                rows = []
                for row in snapshot.get("rows") or []:
                    try:
                        rows.append(
                            (
                                int(row[0]),
                                float(row[1]),
                                float(row[2]),
                                float(row[3]),
                                float(row[4]),
                                float(row[5]),
                            )
                        )
                    except (TypeError, ValueError, IndexError):
                        continue
                if not rows:
                    return False
                cache_deque = _global_kline_cache[cache_key]
                cache_deque.clear()
                cache_deque.extend(rows)
                _global_kline_df_cache[cache_key] = (
                    _build_kline_dataframe_from_cache_rows(rows)
                )
                legacy_cache_key = f"{exchange_id}:{symbol}:{timeframe}"
                if legacy_cache_key != cache_key:
                    legacy_deque = _global_kline_cache[legacy_cache_key]
                    legacy_deque.clear()
                    legacy_deque.extend(rows)
                    _global_kline_df_cache[legacy_cache_key] = _global_kline_df_cache[
                        cache_key
                    ].copy()
                _global_history_loaded_keys.add(cache_key)
                _global_history_loaded_keys.add(legacy_cache_key)
                async with _global_pairs_lock:
                    _global_active_pairs[symbol]["last_price"] = float(rows[-1][4])
                await self._apply_pair_state_update(
                    {
                        "type": "indicator_update",
                        "symbol": symbol,
                        "pair_state": snapshot.get("pair_state") or {},
                    }
                )
                return True

            if data_type_key == "aggTrade":
                rows = [
                    row for row in (snapshot.get("rows") or []) if isinstance(row, dict)
                ]
                if not rows:
                    return False
                trade_key = _trade_cache_key(symbol, exchange_id, market_type)
                trade_deque = _global_agg_trade_deques[trade_key]
                trade_deque.clear()
                trade_deque.extend(rows)
                legacy_deque = _global_agg_trade_deques[symbol]
                legacy_deque.clear()
                legacy_deque.extend(rows)
                async with _global_pairs_lock:
                    _global_active_pairs[symbol]["last_price"] = float(rows[-1]["p"])
                await self._apply_pair_state_update(
                    {
                        "type": "indicator_update",
                        "symbol": symbol,
                        "pair_state": snapshot.get("pair_state") or {},
                    }
                )
                return True

        if data_type_key == "depth":
            snapshot_payload = snapshot.get("snapshot")
            if not isinstance(snapshot_payload, dict):
                return False
            market_type_for_cache = (
                "futures"
                if "futures" in str(market_type or "")
                else str(market_type or self._effective_market_type()).lower()
            )
            self._latest_depth_cache[f"{symbol}_{market_type_for_cache}"] = (
                snapshot_payload
            )
            await self._apply_pair_state_update(
                {
                    "type": "indicator_update",
                    "symbol": symbol,
                    "pair_state": snapshot.get("pair_state") or {},
                }
            )
            return True

        if data_type_key == "open_interest":
            rows = snapshot.get("rows") or []
            if not rows:
                return False
            try:
                df = pd.DataFrame(rows)
                if "timestamp" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
                    df.set_index("timestamp", inplace=True)
                self._open_interest_cache[symbol] = df
                await self._apply_pair_state_update(
                    {
                        "type": "indicator_update",
                        "symbol": symbol,
                        "pair_state": snapshot.get("pair_state") or {},
                    }
                )
                return True
            except Exception as e:
                logger.warning(
                    "[RedisMarketData] Failed to apply open_interest snapshot for %s: %s",
                    symbol,
                    e,
                )
                return False

        return False

    async def _ensure_subscription_via_redis(
        self,
        data_type_key: str,
        symbol: str,
        required_metrics: Optional[Set[str]] = None,
        needs_companion_orderbook: bool = False,
        market_type: Optional[str] = None,
    ) -> None:
        uc_symbol = symbol.upper()
        if required_metrics:
            async with self._metrics_lock:
                self._required_metrics[uc_symbol].update(required_metrics)

        if not await self._ensure_redis_market_data_started():
            return

        specs = self._stream_specs_for_subscription(
            data_type_key, symbol, needs_companion_orderbook, market_type
        )
        new_specs: List[Dict[str, Any]] = []
        for spec in specs:
            stream_key = spec["stream_key"]
            if stream_key in self._redis_market_stream_keys:
                continue
            channel = _market_data_redis_event_channel(stream_key)
            async with self._redis_market_lock:
                if self._redis_market_pubsub:
                    try:
                        await self._redis_market_pubsub.subscribe(channel)
                        logger.info("[RedisMarketData] subscribed to channel=%s (stream_key=%s)", channel, stream_key)
                    except Exception as sub_e:
                        logger.error("[RedisMarketData] subscribe FAILED for channel=%s (stream_key=%s): %s",
                                     channel, stream_key, sub_e,
                                     exc_info=True)
                        continue
                else:
                    logger.error("[RedisMarketData] CANNOT SUBSCRIBE: _redis_market_pubsub is None! stream_key=%s", stream_key)
                    continue
                self._redis_market_stream_keys.add(stream_key)
                self._redis_market_stream_specs[stream_key] = spec
            new_specs.append(spec)
            logger.info("[RedisMarketData] added stream_key to local set: %s", stream_key)

            # Load historical kline data from exchange REST API for cache priming
            dk = spec.get("data_type_key", data_type_key)
            if dk.startswith("kline_"):
                tf = dk.split("_", 1)[1]
                exch = spec.get("exchange_id", "")
                mt = spec.get("market_type", "")
                sym = spec.get("symbol", uc_symbol)
                await self._ensure_history_loaded(dk, sym, tf, mt, exch)

        if new_specs:
            await self._publish_market_data_command(
                {
                    "type": "subscribe",
                    "subscriber_id": self._market_data_subscriber_id,
                    "subscription_key": f"{data_type_key}:{uc_symbol}:{_normalize_market_type_for_cache(market_type or self._effective_market_type())}:{int(bool(needs_companion_orderbook))}",
                    "data_type_key": data_type_key,
                    "symbol": uc_symbol,
                    "market_type": _normalize_market_type_for_cache(
                        market_type or self._effective_market_type()
                    ),
                    "required_metrics": sorted(required_metrics)
                    if required_metrics
                    else [],
                    "needs_companion_orderbook": needs_companion_orderbook,
                    "stream_keys": new_specs,
                }
            )
            for spec in new_specs:
                loaded = await self._wait_for_market_snapshot_from_redis(spec)
                if loaded:
                    logger.info(
                        "[RedisMarketData] loaded shared snapshot for %s",
                        spec["stream_key"],
                    )
                else:
                    logger.info(
                        "[RedisMarketData] shared snapshot not ready for %s; live payloads will fill local cache.",
                        spec["stream_key"],
                    )

    async def _remove_subscription_via_redis(
        self, data_type_key: str, symbol: str
    ) -> None:
        matching_specs = self._stream_specs_for_subscription(
            data_type_key, symbol, needs_companion_orderbook=True
        )
        matching_keys = {spec["stream_key"] for spec in matching_specs}
        removed_specs: List[Dict[str, Any]] = []
        for stream_key in list(self._redis_market_stream_keys):
            if stream_key not in matching_keys:
                continue
            spec = self._redis_market_stream_specs.get(stream_key) or {}
            channel = _market_data_redis_event_channel(stream_key)
            async with self._redis_market_lock:
                if self._redis_market_pubsub:
                    await self._redis_market_pubsub.unsubscribe(channel)
                self._redis_market_stream_keys.discard(stream_key)
                self._redis_market_stream_specs.pop(stream_key, None)
            removed_specs.append(spec)
            logger.info("[RedisMarketData] unsubscribed locally from %s", stream_key)

        if removed_specs:
            first = removed_specs[0]
            await self._publish_market_data_command(
                {
                    "type": "unsubscribe",
                    "subscriber_id": self._market_data_subscriber_id,
                    "subscription_key": f"{data_type_key}:{symbol.upper()}:{_normalize_market_type_for_cache(first.get('market_type'))}:1",
                    "data_type_key": first.get("data_type_key") or data_type_key,
                    "symbol": first.get("symbol") or symbol.upper(),
                    "market_type": first.get("market_type"),
                    "stream_keys": removed_specs,
                }
            )

    async def ensure_subscription(
        self,
        data_type_key: str,
        symbol: str,
        required_metrics: Optional[Set[str]] = None,
        needs_companion_orderbook: bool = False,
        market_type: Optional[str] = None,
    ):
        if self._use_redis_market_data:
            await self._ensure_subscription_via_redis(
                data_type_key,
                symbol,
                required_metrics=required_metrics,
                needs_companion_orderbook=needs_companion_orderbook,
                market_type=market_type,
            )
            return

        """
        Subscribes to data of the specified type for the symbol.
        
        OPTIMIZATION: The needs_companion_orderbook parameter controls the subscription to 
        the spot orderbook for futures trading (and vice versa). Subscription to companion
        occurs ONLY if the strategy explicitly requires it (there are orderbook blocks).
        """
        uc_symbol = symbol.upper()
        if required_metrics:
            async with self._metrics_lock:
                self._required_metrics[uc_symbol].update(required_metrics)
                logger.debug(
                    f"[DataSubEnsure:{uc_symbol}] Updated required metrics. Now: {self._required_metrics[uc_symbol]}"
                )
        uc_symbol = symbol.upper()
        if required_metrics:
            async with self._metrics_lock:
                self._required_metrics[uc_symbol].update(required_metrics)
                logger.debug(
                    f"[DataSubEnsure:{uc_symbol}] Updated required metrics. Now: {self._required_metrics[uc_symbol]}"
                )
        uc_symbol = symbol.upper()
        lc_symbol = symbol.lower()
        log_prefix = f"[DataSubEnsure:{data_type_key}:{uc_symbol}]"

        at_least_one_subscription_made = False

        markets_to_subscribe = set()
        effective_market_type = _normalize_market_type_for_cache(
            market_type or self._effective_market_type()
        )
        if data_type_key == "depth":
            markets_to_subscribe.add(effective_market_type)
            # OPTIMIZATION: Subscribe to the companion orderbook ONLY if the strategy requires it
            if needs_companion_orderbook and config.USE_COMPANION_ORDERBOOK_ANALYSIS:
                # Depending on the settings, add a "paired" market for order book analysis
                if (
                    effective_market_type == "futures_usdtm"
                    and config.ANALYZE_SPOT_ORDERBOOK_FOR_FUTURES_TRADES
                ):
                    markets_to_subscribe.add("spot")
                    logger.info(
                        f"{log_prefix} Strategy requires spot orderbook - adding companion subscription."
                    )
                elif (
                    effective_market_type == "spot"
                    and config.ANALYZE_FUTURES_ORDERBOOK_FOR_SPOT_TRADES
                ):
                    markets_to_subscribe.add("futures_usdtm")
                    logger.info(
                        f"{log_prefix} Strategy requires futures orderbook - adding companion subscription."
                    )
        else:
            # For kline and aggTrade, we subscribe only to the main market
            markets_to_subscribe.add(effective_market_type)

        logger.debug(
            f"{log_prefix} Identified required markets: {list(markets_to_subscribe)}"
        )

        for market_type_sub in markets_to_subscribe:
            executor_for_market = self._executor_for_market(market_type_sub)
            exchange_id = (
                getattr(executor_for_market, "exchange_id", "binance")
                if executor_for_market
                else "binance"
            )
            if getattr(executor_for_market, "sandbox", False):
                if not exchange_id.endswith("_testnet"):
                    exchange_id = f"{exchange_id}_testnet"
            is_binance = exchange_id.startswith("binance")
            valid_symbols = await self._get_valid_symbols_from_exchange_info(
                market_type_sub
            )
            if uc_symbol not in valid_symbols:
                logger.warning(
                    f"{log_prefix} Symbol '{uc_symbol}' is NOT valid for market '{market_type_sub}'. Subscription SKIPPED."
                )
                continue

            # Getting URL dynamically from config
            is_testnet = getattr(self._executor, "sandbox", False)
            ws_base_url = ""

            if market_type_sub == "spot":
                ws_base_url = (
                    config.BINANCE_SPOT_TESTNET_MARKET_DATA_WS_URL
                    if is_testnet
                    else config.BINANCE_SPOT_MAINNET_MARKET_DATA_WS_URL
                )
            elif market_type_sub == "futures_usdtm":
                # For futures, there is no testnet URL in the config; we assume it will be added if needed.
                # It exists for mainnet.
                if is_testnet:
                    ws_base_url = getattr(
                        config, "BINANCE_FUTURES_TESTNET_MARKET_DATA_WS_URL", ""
                    )  # Safe retrieval
                else:  # mainnet
                    ws_base_url = (
                        config.BINANCE_FUTURES_USDTM_MAINNET_MARKET_DATA_WS_URL
                    )

            if is_binance and not ws_base_url:
                logger.error(
                    f"{log_prefix} Could not determine WS base URL for market '{market_type_sub}' and env '{config.ACTIVE_TRADING_ENVIRONMENT}'. Skipping."
                )
                continue

            stream_suffix = ""
            if data_type_key == "depth":
                stream_suffix = getattr(config, "BINANCE_DEPTH_STREAM_NAME", "@depth")
            elif data_type_key.startswith("kline_"):
                timeframe = data_type_key.split("_", 1)[1]
                stream_suffix = f"@kline_{timeframe}"
            elif data_type_key == "aggTrade":
                stream_suffix = "@aggTrade"

            elif data_type_key == "open_interest":
                # Stream for OI is called @openInterest
                stream_suffix = "@openInterest"
            else:
                logger.warning(
                    f"{log_prefix} Unknown data_type_key '{data_type_key}'. Cannot create stream."
                )
                continue

            binance_stream_part = f"{lc_symbol}{stream_suffix}"
            # Unique key including exchange_id to prevent cross-account contamination
            task_and_client_key = (
                f"{exchange_id}:{market_type_sub}:{binance_stream_part}"
            )
            full_ws_url = f"{ws_base_url}/{binance_stream_part}"

            if data_type_key.startswith("kline_"):
                timeframe = data_type_key.split("_", 1)[1]
                history_loaded = await self._ensure_history_loaded(
                    data_type_key, uc_symbol, timeframe, market_type_sub, exchange_id
                )
                if not history_loaded:
                    logger.error(
                        f"{log_prefix} Kline history FAILED for exchange '{exchange_id}', market '{market_type_sub}'. WebSocket will NOT be started."
                    )
                    continue

            # GLOBAL REGISTRY WITH BROADCAST
            # One WebSocket per unique stream, events are broadcast to ALL queues
            async with _global_ws_registry_lock:
                if task_and_client_key in _global_ws_registry:
                    # Subscription ALREADY exists — just adding our queue to the broadcast list
                    registry_entry = _global_ws_registry[task_and_client_key]
                    consumer_id = id(self)

                    if consumer_id not in registry_entry["consumers"]:
                        registry_entry["ref_count"] += 1
                        registry_entry["consumers"].add(consumer_id)
                        logger.info(
                            f"{log_prefix} Reusing EXISTING global WebSocket: {task_and_client_key} "
                            f"(ref_count now: {registry_entry['ref_count']})"
                        )

                    at_least_one_subscription_made = True
                else:
                    # Creating a NEW global subscription
                    if not is_binance:
                        logger.info(
                            f"{log_prefix} Using CCXT Pro for non-Binance exchange: {exchange_id}"
                        )
                        task = self.loop.create_task(
                            self._ccxt_pro_data_ws_loop(
                                uc_symbol,
                                data_type_key,
                                task_and_client_key,
                                market_type_sub,
                                executor_for_market,
                                exchange_id,
                            ),
                            name=f"CcxtProWS_{exchange_id}_{uc_symbol}_{data_type_key}_{market_type_sub}",
                        )
                    else:
                        logger.info(
                            f"{log_prefix} Creating NEW global WebSocket: {task_and_client_key} for URL {full_ws_url}"
                        )
                        task = self.loop.create_task(
                            self._binance_data_ws_loop(
                                uc_symbol,
                                data_type_key,
                                task_and_client_key,
                                full_ws_url,
                                market_type_sub,
                                exchange_id,
                            ),
                            name=f"BinanceWS_{exchange_id}_{uc_symbol}_{data_type_key}_{market_type_sub}",
                        )

                    _global_ws_registry[task_and_client_key] = {
                        "task": task,
                        "client": None,
                        "ref_count": 1,
                        "consumers": {id(self)},
                    }
                    at_least_one_subscription_made = True

            # Registering event_queue for broadcast (if any)
            if self.event_queue:
                async with _global_event_queues_lock:
                    _global_event_queues[task_and_client_key].add(self.event_queue)
                    logger.debug(
                        f"{log_prefix} Registered event_queue for broadcast on {task_and_client_key}"
                    )

            # Also to the local registry for compatibility
            async with self._binance_market_data_ws_lock:
                if task_and_client_key not in self._binance_market_data_ws_tasks:
                    self._binance_market_data_ws_tasks[task_and_client_key] = (
                        _global_ws_registry.get(task_and_client_key, {}).get("task")
                    )

        if at_least_one_subscription_made:
            async with self._data_cache_lock:
                internal_requested_key = f"{data_type_key}:{uc_symbol}"
                self._requested_binance_streams.add(internal_requested_key)
                logger.debug(
                    f"{log_prefix} Added '{internal_requested_key}' to _requested_binance_streams."
                )

    async def _ensure_history_loaded(
        self,
        data_type_key: str,
        symbol_uc: str,
        timeframe: str,
        market_type: str,
        exchange_id: str = "binance",
    ) -> bool:
        """
        Universal history loading dispatcher.

        Checks if history has already been loaded for the given data type (kline, open_interest).
        If not - starts the corresponding loading task.
        If the task is already in progress - waits for its completion.
        Guarantees that multiple simultaneous downloads will not be started for the same resource.

        Args:
            data_type_key (str): Data type key, for example "kline_5m" or "open_interest".
            symbol_uc (str): Symbol in uppercase (e.g., "BTCUSDT").
            timeframe (str): Timeframe (relevant for kline, ignored for OI).
            market_type (str): Market type (e.g., "futures_usdtm").

        Returns:
            bool: True if history was successfully loaded (or was loaded previously), False in case of error.
        """
        # Step 1: Define a unique key for the cache and a prefix for logs
        log_prefix_base = f"[HistLoadEnsure:{symbol_uc}]"
        cache_key = ""

        if data_type_key.startswith("kline_"):
            cache_key = _kline_cache_key(symbol_uc, timeframe, exchange_id, market_type)
            log_prefix = f"[{log_prefix_base}:{timeframe}]"
        elif data_type_key == "open_interest":
            cache_key = f"oi:{symbol_uc}"  # Unique key for Open Interest
            log_prefix = f"[{log_prefix_base}:OI]"
        else:
            # For other data types (aggTrade, depth), history is not loaded by this method
            return True

        logger.debug(
            f"{log_prefix} Called for symbol {symbol_uc}, market: {market_type}."
        )

        # Step 2: Check if the history has already been loaded or if the task is already active (GLOBALLY)
        async with _global_cache_lock:
            if cache_key in _global_history_loaded_keys:
                logger.debug(
                    f"{log_prefix} History already loaded (global cache hit). Returning True."
                )
                return True
            active_download_task = _global_history_download_tasks.get(cache_key)

        # Step 3: If the task is already running, wait for its completion
        if active_download_task and not active_download_task.done():
            logger.debug(
                f"{log_prefix} History download task already active. Awaiting..."
            )
            try:
                # `shield` protects the task from cancellation if the current coroutine is cancelled
                await asyncio.wait_for(
                    asyncio.shield(active_download_task), timeout=60.0
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"{log_prefix} Timeout waiting for existing history download task."
                )

            # Re-checking status after waiting (GLOBALLY)
            async with _global_cache_lock:
                is_loaded_after_wait = cache_key in _global_history_loaded_keys
                logger.debug(
                    f"{log_prefix} Existing download task awaited. History loaded: {is_loaded_after_wait}."
                )
                return is_loaded_after_wait

        # Step 4: If we are here, it means the history needs to be loaded
        logger.info(
            f"{log_prefix} Scheduling new history download (market: {market_type})."
        )

        # Step 5: Choosing which coroutine to launch for loading
        task_coro = None
        if data_type_key.startswith("kline_"):
            task_coro = self._download_initial_kline_history_for_key(
                cache_key, symbol_uc, timeframe, market_type, exchange_id
            )
        elif data_type_key == "open_interest":
            task_coro = self._download_initial_oi_history_for_key(
                cache_key, symbol_uc, market_type
            )
        else:
            # We should not get here due to the check in Step 1, but this is a safe fallback
            return True

        # Step 6: Creating and registering a new task (GLOBALLY)
        new_task = self.loop.create_task(
            task_coro, name=f"HistDownload_{cache_key.replace(':', '_')}"
        )
        async with _global_cache_lock:
            _global_history_download_tasks[cache_key] = new_task

        # Step 7: Waiting for the new task to complete
        try:
            await asyncio.wait_for(asyncio.shield(new_task), timeout=60.0)
        except asyncio.TimeoutError:
            logger.warning(
                f"{log_prefix} Timeout waiting for new history download task."
            )

        # Step 8: Final check and return of the result (using GLOBAL cache)
        async with _global_cache_lock:
            is_loaded_after_new_task = cache_key in _global_history_loaded_keys
            logger.debug(
                f"{log_prefix} New download task awaited. History loaded: {is_loaded_after_new_task}."
            )
            return is_loaded_after_new_task

    async def _download_initial_oi_history_for_key(
        self, cache_key: str, symbol_uc: str, market_type_for_loader: str
    ):
        """Loads the initial Open Interest history for a symbol."""
        log_prefix = f"[OIHistDownload:{cache_key}]"
        try:
            async with self._history_download_semaphore:
                logger.info(f"{log_prefix} Starting download...")
                end_dt = datetime.now(timezone.utc)
                start_dt = end_dt - timedelta(days=7)

                df_history = await download_open_interest(
                    symbol=symbol_uc,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    market_type=market_type_for_loader,
                )

                if df_history is None or df_history.empty:
                    logger.warning(f"{log_prefix} No historical OI data downloaded.")

                async with self._data_cache_lock:
                    if df_history is not None:
                        self._open_interest_cache[symbol_uc] = df_history
                        logger.info(
                            f"{log_prefix} Successfully loaded and cached {len(df_history)} OI records."
                        )

                    self._history_loaded_keys.add(cache_key)
        except Exception as e:
            logger.error(f"{log_prefix} Error: {e}", exc_info=True)
        finally:
            async with self._data_cache_lock:
                if cache_key in self._history_download_tasks:
                    del self._history_download_tasks[cache_key]

    async def get_active_pair_by_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Finds information for a specific symbol in the GLOBAL cache `_global_active_pairs`,
        which contains enriched data (indicators, metrics).
        We use the global cache for multi-user mode.
        """
        uc_symbol = symbol.upper()
        async with _global_pairs_lock:
            if uc_symbol in _global_active_pairs:
                result = _global_active_pairs[uc_symbol].copy()
                # IMPORTANT: Add symbol to the result, as the strategy expects it!
                result["symbol"] = uc_symbol
                return result
        return None

    async def get_latest_price(self, symbol: str) -> Optional[float]:
        """
        Helper method for quickly getting the last known price for a symbol.
        """
        pair_data = await self.get_active_pair_by_symbol(symbol)
        if pair_data and "last_price" in pair_data:
            return pair_data["last_price"]
        return None

    async def _download_initial_oi_history_for_key(
        self, cache_key: str, symbol_uc: str, market_type_for_loader: str
    ):
        """Loads the initial Open Interest history for a symbol."""
        log_prefix = f"[OIHistDownload:{cache_key}]"
        try:
            async with self._history_download_semaphore:
                if not self._executor:
                    logger.error(
                        f"{log_prefix} Executor not available. Cannot download OI history."
                    )
                    return

                logger.info(f"{log_prefix} Starting download...")
                # Assume that the executor has a method for loading OI history
                # It should return a list of dictionaries or a DataFrame
                df_history = await self._executor.fetch_open_interest_history(
                    symbol=symbol_uc,
                    period="5m",  # Most frequent interval for OI
                    limit=1000,  # Loading the last 1000 points (approximately 3.5 days)
                )

                if df_history is None or df_history.empty:
                    logger.warning(f"{log_prefix} No historical OI data downloaded.")
                    # Even if there is no data, mark it as "loaded" so as not to try again
                    async with self._data_cache_lock:
                        self._history_loaded_keys.add(cache_key)
                    return

                # Converting DataFrame to the required format
                df_history = df_history.rename(
                    columns={"sumOpenInterest": "open_interest"}
                )
                df_history = df_history[
                    ["open_interest"]
                ]  # Keeping only the required column
                df_history.index.name = "timestamp"

                async with self._data_cache_lock:
                    self._open_interest_cache[symbol_uc] = df_history
                    self._history_loaded_keys.add(cache_key)
                    logger.info(
                        f"{log_prefix} Successfully loaded and cached {len(df_history)} OI records."
                    )
        except Exception as e:
            logger.error(f"{log_prefix} Error: {e}", exc_info=True)
        finally:
            async with self._data_cache_lock:
                if cache_key in self._history_download_tasks:
                    del self._history_download_tasks[cache_key]

    async def _download_initial_kline_history_for_key(
        self,
        cache_key: str,
        symbol_uc: str,
        timeframe: str,
        market_type_for_loader: str,
        exchange_id: str = "binance",
    ):
        log_prefix = f"[HistDownload:{cache_key}]"
        try:
            async with self._history_download_semaphore:
                logger.info(
                    f"{log_prefix} Starting download... Market type for DataLoader: {market_type_for_loader}"
                )
                end_dt = datetime.now(timezone.utc)
                lookback_days = getattr(config, "REALTIME_HISTORY_LOOKBACK_DAYS", 3)
                start_dt = end_dt - timedelta(days=lookback_days)

                executor_for_market = self._executor_for_market(market_type_for_loader)
                exchange_id = (
                    getattr(executor_for_market, "exchange_id", "binance")
                    if executor_for_market
                    else "binance"
                )
                if getattr(executor_for_market, "sandbox", False):
                    if not exchange_id.endswith("_testnet"):
                        exchange_id = f"{exchange_id}_testnet"
                is_binance = exchange_id.startswith("binance")
                if not is_binance and hasattr(executor_for_market, "fetch_ohlcv"):
                    since_ms = int(start_dt.timestamp() * 1000)
                    ohlcv_rows = await executor_for_market.fetch_ohlcv(
                        symbol_uc, timeframe, since=since_ms, limit=1000
                    )
                    historical_candles_tuples = []
                    for row in ohlcv_rows or []:
                        try:
                            ts_ms, o, h, l_val, c, v = (
                                int(row[0]),
                                float(row[1]),
                                float(row[2]),
                                float(row[3]),
                                float(row[4]),
                                float(row[5]),
                            )
                            if not any(map(math.isnan, [o, h, l_val, c, v])):
                                historical_candles_tuples.append(
                                    (ts_ms, o, h, l_val, c, v)
                                )
                        except (TypeError, ValueError, IndexError) as e:
                            logger.warning(
                                f"{log_prefix} Error parsing CCXT OHLCV row: {row}, error: {e}"
                            )

                    async with _global_cache_lock:
                        cache_deque = _global_kline_cache[cache_key]
                        existing_live_candles = list(cache_deque)
                        merged_map = {
                            int(candle[0]): candle
                            for candle in historical_candles_tuples
                        }
                        for live_candle in existing_live_candles:
                            merged_map[int(live_candle[0])] = live_candle
                        sorted_merged_candles = sorted(
                            list(merged_map.values()), key=lambda x: int(x[0])
                        )
                        cache_deque.clear()
                        cache_deque.extend(sorted_merged_candles)
                        _global_kline_df_cache[cache_key] = (
                            _build_kline_dataframe_from_cache_rows(
                                sorted_merged_candles
                            )
                        )
                        legacy_cache_key = f"{exchange_id}:{symbol_uc}:{timeframe}"
                        if legacy_cache_key != cache_key:
                            legacy_deque = _global_kline_cache[legacy_cache_key]
                            legacy_deque.clear()
                            legacy_deque.extend(sorted_merged_candles)
                            _global_kline_df_cache[legacy_cache_key] = (
                                _global_kline_df_cache[cache_key].copy()
                            )
                        _global_history_loaded_keys.add(cache_key)
                        _global_history_loaded_keys.add(legacy_cache_key)
                    logger.info(
                        f"{log_prefix} Successfully loaded/cached {len(historical_candles_tuples)} CCXT hist klines (merged with {len(existing_live_candles)} live, total in cache: {len(cache_deque)})."
                    )
                    return

                df_history = await download_klines(
                    symbol_uc,
                    timeframe,
                    start_dt,
                    end_dt,
                    market_type=market_type_for_loader,
                )

                if df_history is None:
                    logger.error(
                        f"{log_prefix} download_klines returned None. History download FAILED."
                    )
                    return
                if df_history.empty:
                    logger.warning(
                        f"{log_prefix} No historical data downloaded (empty DataFrame). Processing will continue, and history will be marked as loaded (empty)."
                    )

                historical_candles_tuples = []
                for index_ts, row in df_history.iterrows():
                    try:
                        ts_ms = int(index_ts.timestamp() * 1000)
                        o, h, l_val, c, v = (
                            float(row["open"]),
                            float(row["high"]),
                            float(row["low"]),
                            float(row["close"]),
                            float(row["volume"]),
                        )
                        if not any(map(math.isnan, [o, h, l_val, c, v])):
                            historical_candles_tuples.append((ts_ms, o, h, l_val, c, v))
                    except (TypeError, ValueError, KeyError) as e:
                        logger.warning(
                            f"{log_prefix} Error parsing row: {row}, error: {e}"
                        )
                        continue

                if not historical_candles_tuples and not df_history.empty:
                    logger.warning(
                        f"{log_prefix} No valid tuples from historical data, though df_history was not empty. Downloaded df head:\n{df_history.head().to_string()}"
                    )
                elif not historical_candles_tuples and df_history.empty:
                    logger.info(
                        f"{log_prefix} historical_candles_tuples is empty because df_history was empty. Proceeding to mark history loaded."
                    )

            # Using GLOBAL cache for multi-user mode
            async with _global_cache_lock:
                cache_deque = _global_kline_cache[cache_key]

                existing_live_candles = list(cache_deque)

                merged_map = {
                    int(candle[0]): candle for candle in historical_candles_tuples
                }
                for live_candle in existing_live_candles:
                    merged_map[int(live_candle[0])] = live_candle

                sorted_merged_candles = sorted(
                    list(merged_map.values()), key=lambda x: int(x[0])
                )

                cache_deque.clear()
                cache_deque.extend(sorted_merged_candles)
                _global_kline_df_cache[cache_key] = (
                    _build_kline_dataframe_from_cache_rows(sorted_merged_candles)
                )
                legacy_cache_key = f"{exchange_id}:{symbol_uc}:{timeframe}"
                if legacy_cache_key != cache_key:
                    legacy_deque = _global_kline_cache[legacy_cache_key]
                    legacy_deque.clear()
                    legacy_deque.extend(sorted_merged_candles)
                    _global_kline_df_cache[legacy_cache_key] = _global_kline_df_cache[
                        cache_key
                    ].copy()

                _global_history_loaded_keys.add(cache_key)
                _global_history_loaded_keys.add(legacy_cache_key)
                logger.info(
                    f"{log_prefix} Successfully loaded/cached {len(historical_candles_tuples)} hist klines (merged with {len(existing_live_candles)} live, total in cache: {len(cache_deque)})."
                )
        except asyncio.CancelledError:
            logger.info(f"{log_prefix} Download task cancelled.")
        except Exception as e:
            logger.error(f"{log_prefix} Error: {e}", exc_info=True)
        finally:
            async with _global_cache_lock:
                if cache_key in _global_history_download_tasks:
                    del _global_history_download_tasks[cache_key]

    async def remove_subscription(
        self, data_type_key: str, symbol: str, market_type: Optional[str] = None
    ):
        if self._use_redis_market_data:
            await self._remove_subscription_via_redis(data_type_key, symbol)
            return

        uc_symbol = symbol.upper()
        lc_symbol = symbol.lower()
        log_prefix = f"[DataSubRemove:{data_type_key}:{uc_symbol}]"

        stream_ids_to_stop: List[str] = []
        target_market_type = _normalize_market_type_for_cache(
            market_type or self._effective_market_type()
        )

        if data_type_key == "depth":
            possible_markets = {target_market_type}
            if market_type is None and config.USE_COMPANION_ORDERBOOK_ANALYSIS:
                possible_markets.add("spot")
                possible_markets.add("futures_usdtm")

            stream_suffix = getattr(config, "BINANCE_DEPTH_STREAM_NAME", "@depth")
            for mkt_type in possible_markets:
                stream_part = f"{lc_symbol}{stream_suffix}"
                # Try both formats for unsubscription
                stream_ids_to_stop.append(f"{stream_part}:{mkt_type}")
                executor_for_mkt = self._executor_for_market(mkt_type)
                mkt_exchange_id = (
                    getattr(executor_for_mkt, "exchange_id", "binance")
                    if executor_for_mkt
                    else "binance"
                )
                stream_ids_to_stop.append(f"{mkt_exchange_id}:{mkt_type}:{stream_part}")

        elif (
            data_type_key.startswith("kline_")
            or data_type_key == "aggTrade"
            or data_type_key == "open_interest"
        ):
            stream_suffix = ""
            if data_type_key.startswith("kline_"):
                timeframe = data_type_key.split("_", 1)[1]
                stream_suffix = f"@kline_{timeframe}"
            elif data_type_key == "aggTrade":
                stream_suffix = "@aggTrade"
            elif data_type_key == "open_interest":
                stream_suffix = "@openInterest"  # Stream name from Binance

            stream_part = f"{lc_symbol}{stream_suffix}"
            # For these types, unsubscription occurs only from the main market
            stream_ids_to_stop.append(f"{stream_part}:{target_market_type}")
            executor_for_mkt = self._executor_for_market(target_market_type)
            mkt_exchange_id = (
                getattr(executor_for_mkt, "exchange_id", "binance")
                if executor_for_mkt
                else "binance"
            )
            stream_ids_to_stop.append(
                f"{mkt_exchange_id}:{target_market_type}:{stream_part}"
            )
        else:
            logger.warning(
                f"{log_prefix} Unknown data_type_key for unsubscription: {data_type_key}"
            )
            return

        logger.info(f"{log_prefix} Identified stream IDs to stop: {stream_ids_to_stop}")

        for task_and_client_key in stream_ids_to_stop:
            should_actually_close = False
            task_to_cancel: Optional[asyncio.Task] = None
            client_to_close: Optional[websockets.WebSocketClientProtocol] = None

            # Remove our queue from the broadcast list
            if self.event_queue:
                async with _global_event_queues_lock:
                    if task_and_client_key in _global_event_queues:
                        _global_event_queues[task_and_client_key].discard(
                            self.event_queue
                        )
                        logger.debug(
                            f"{log_prefix} Removed event_queue from broadcast for {task_and_client_key}"
                        )

            # === GLOBAL REGISTRY CHECK ===
            async with _global_ws_registry_lock:
                if task_and_client_key in _global_ws_registry:
                    registry_entry = _global_ws_registry[task_and_client_key]
                    # Remove this consumer from the list
                    registry_entry["consumers"].discard(id(self))
                    registry_entry["ref_count"] -= 1

                    if registry_entry["ref_count"] <= 0:
                        # No one else is using this subscription - closing
                        should_actually_close = True
                        task_to_cancel = registry_entry.get("task")
                        client_to_close = registry_entry.get("client")
                        del _global_ws_registry[task_and_client_key]
                        # Clear the queue list as well
                        async with _global_event_queues_lock:
                            _global_event_queues.pop(task_and_client_key, None)
                        logger.info(
                            f"{log_prefix} Ref count reached 0 for {task_and_client_key}. Closing WebSocket."
                        )
                    else:
                        # Other users are still using this subscription
                        logger.info(
                            f"{log_prefix} Decreased ref_count for {task_and_client_key} "
                            f"(ref_count now: {registry_entry['ref_count']}). WebSocket stays open."
                        )
                else:
                    # Not in the global registry - possibly an old format
                    should_actually_close = True

            # Remove from local registry
            async with self._binance_market_data_ws_lock:
                local_task = self._binance_market_data_ws_tasks.pop(
                    task_and_client_key, None
                )
                local_client = self._binance_market_data_clients.pop(
                    task_and_client_key, None
                )
                if not task_to_cancel:
                    task_to_cancel = local_task
                if not client_to_close:
                    client_to_close = local_client

            # Closing WebSocket ONLY if ref_count reached 0
            if should_actually_close:
                if client_to_close and client_to_close.state == State.OPEN:
                    logger.info(
                        f"{log_prefix} Attempting to gracefully close WebSocket client for {task_and_client_key}."
                    )
                    try:
                        await asyncio.wait_for(
                            client_to_close.close(
                                code=1000, reason="Client unsubscribing"
                            ),
                            timeout=2.0,
                        )
                        await asyncio.sleep(0.01)
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"{log_prefix} Timeout closing WebSocket client for {task_and_client_key}."
                        )
                    except Exception as e_close:
                        logger.error(
                            f"{log_prefix} Error closing WebSocket client for {task_and_client_key}: {e_close}"
                        )

                if task_to_cancel and not task_to_cancel.done():
                    logger.info(
                        f"{log_prefix} Cancelling WebSocket task: {task_and_client_key}"
                    )
                    task_to_cancel.cancel()
                    try:
                        await asyncio.wait_for(task_to_cancel, timeout=2.0)
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"{log_prefix} Timeout waiting for task {task_and_client_key} to cancel."
                        )
                    except asyncio.CancelledError:
                        logger.debug(
                            f"{log_prefix} Task {task_and_client_key} confirmed cancelled."
                        )
                    except Exception as e:
                        logger.error(
                            f"{log_prefix} Error awaiting cancelled task {task_and_client_key}: {e}"
                        )
                else:
                    logger.debug(
                        f"{log_prefix} No active task found for {task_and_client_key} or task already done."
                    )

        # Clearing caches
        if data_type_key.startswith("kline_"):
            timeframe = data_type_key.split("_", 1)[1]
            executor_for_mkt = self._executor_for_market(target_market_type)
            mkt_exchange_id = (
                getattr(executor_for_mkt, "exchange_id", "binance")
                if executor_for_mkt
                else "binance"
            )
            if getattr(executor_for_mkt, "sandbox", False):
                if not mkt_exchange_id.endswith("_testnet"):
                    mkt_exchange_id = f"{mkt_exchange_id}_testnet"
            cache_key = _kline_cache_key(
                uc_symbol, timeframe, mkt_exchange_id, target_market_type
            )
            async with self._data_cache_lock:
                self._history_loaded_keys.discard(cache_key)
                if cache_key in self._kline_cache:
                    del self._kline_cache[cache_key]
                    logger.info(f"{log_prefix} Cleared kline cache for {cache_key}.")
        elif data_type_key == "aggTrade":
            async with self._data_cache_lock:
                if uc_symbol in self._aggtrade_cache_df:
                    del self._aggtrade_cache_df[uc_symbol]
                    logger.info(f"{log_prefix} Cleared aggTrade cache for {uc_symbol}.")
        elif data_type_key == "open_interest":
            async with self._data_cache_lock:
                if uc_symbol in self._open_interest_cache:
                    del self._open_interest_cache[uc_symbol]
                    logger.info(
                        f"{log_prefix} Cleared open_interest cache for {uc_symbol}."
                    )

        logger.info(
            f"{log_prefix} Unsubscription process finished for {data_type_key}:{uc_symbol}."
        )

    async def remove_all_subscriptions_for_symbol(self, symbol: str):
        if self._use_redis_market_data:
            uc_symbol = symbol.upper()
            for stream_key, spec in list(self._redis_market_stream_specs.items()):
                if str(spec.get("symbol", "")).upper() == uc_symbol:
                    await self._remove_subscription_via_redis(
                        str(spec.get("data_type_key") or ""), uc_symbol
                    )
            return

        uc_symbol = symbol.upper()
        logger.info(f"[DataSubMgmt] Removing ALL subscriptions for symbol: {uc_symbol}")
        binance_stream_ids_to_remove = []
        async with self._binance_market_data_ws_lock:  # Collecting keys under lock
            for stream_id in list(
                self._binance_market_data_ws_tasks.keys()
            ):  # list() for copy
                parts = stream_id.split(":")
                stream_part = parts[-1] if len(parts) >= 3 else stream_id
                if stream_part.startswith(uc_symbol.lower() + "@"):
                    binance_stream_ids_to_remove.append(stream_id)
        for stream_id in binance_stream_ids_to_remove:
            try:
                parts = stream_id.split(":")
                stream_name_part = parts[-1] if len(parts) >= 3 else stream_id

                symbol_lower, type_part = stream_name_part.split("@", 1)

                dt_key = ""
                if type_part.startswith("kline_"):
                    dt_key = type_part
                elif type_part == "aggTrade":
                    dt_key = "aggTrade"
                elif type_part == "openInterest":  # Note the stream name from Binance
                    dt_key = "open_interest"
                elif type_part == "depth":
                    dt_key = "depth"

                if dt_key:
                    await self.remove_subscription(dt_key, symbol_lower.upper())
            except Exception as e:
                logger.error(
                    f"Error parsing stream_id '{stream_id}' for clear_all: {e}"
                )

    async def clear_all_subscriptions(self):
        if self._use_redis_market_data:
            for stream_key, spec in list(self._redis_market_stream_specs.items()):
                await self._publish_market_data_command(
                    {
                        "type": "unsubscribe",
                        "subscriber_id": self._market_data_subscriber_id,
                        "stream_key": stream_key,
                        "data_type_key": spec.get("data_type_key"),
                        "symbol": spec.get("symbol"),
                        "market_type": spec.get("market_type"),
                        "exchange_id": spec.get("exchange_id") or "binance",
                    }
                )
                channel = _market_data_redis_event_channel(stream_key)
                if self._redis_market_pubsub:
                    await self._redis_market_pubsub.unsubscribe(channel)
            self._redis_market_stream_keys.clear()
            self._redis_market_stream_specs.clear()
            return

        logger.info("[DataSubMgmt] Clearing ALL subscriptions.")
        all_binance_stream_ids_copy = []
        async with self._binance_market_data_ws_lock:
            all_binance_stream_ids_copy = list(
                self._binance_market_data_ws_tasks.keys()
            )
        for stream_id in all_binance_stream_ids_copy:
            try:
                parts = stream_id.split(":")
                stream_name_part = parts[-1] if len(parts) >= 3 else stream_id
                symbol_lower, type_part = stream_name_part.split("@", 1)
                dt_key = (
                    type_part
                    if type_part == "aggTrade"
                    else type_part.replace("kline_", "kline_")
                )
                if dt_key:
                    await self.remove_subscription(dt_key, symbol_lower.upper())
            except Exception as e:
                logger.error(
                    f"Error parsing stream_id '{stream_id}' for clear_all: {e}"
                )
        main_app_streams_to_clear_copy = []
        async with self._main_app_ws_connect_lock:
            main_app_streams_to_clear_copy = list(self._required_streams_for_main_app)
            self._required_streams_for_main_app.clear()
        if (
            main_app_streams_to_clear_copy
        ):  # If there were any subscriptions to main_app
            logger.info(
                "[DataSubMgmt] Cleared all required streams for main_app. Sending empty subscription list."
            )
            self.loop.create_task(
                self._send_subscriptions_to_main_app(force_send=True),
                name="SendClearSubMainApp",
            )

    async def _main_app_ws_loop(self):
        reconnect_delay = BINANCE_WS_RECONNECT_DELAY_BASE
        logger.info(f"Starting main_app_ws_loop. Connecting to {self._main_app_ws_url}")
        while self._running:
            websocket = None
            if not self._main_app_ws_url or not self._main_app_ws_url.startswith(
                ("ws://", "wss://")
            ):
                logger.warning(
                    f"MAIN_APP_WS_URL ('{self._main_app_ws_url}') is invalid or not set. Loop will pause."
                )
                await asyncio.sleep(reconnect_delay)
                continue

            try:
                async with self._main_app_ws_connect_lock:
                    logger.debug(
                        f"Attempting WS connection to {self._main_app_ws_url} (MainApp)"
                    )

                    # BROWSER MASKING
                    # This will make Cloudflare think we are Chrome and let us through
                    # even without configuring IP whitelists.
                    extra_headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Origin": "https://screener.depthsight.pro",
                        "Accept-Language": "en-US,en;q=0.9",
                    }

                    connect_kwargs = {
                        "ping_interval": 20,
                        "ping_timeout": 10,
                        "open_timeout": 10,
                    }
                    # Robust compatibility for websockets v13+ (additional_headers)
                    # and older versions (extra_headers)
                    import websockets

                    if hasattr(websockets, "asyncio"):
                        connect_kwargs["additional_headers"] = extra_headers
                    else:
                        connect_kwargs["extra_headers"] = extra_headers

                    try:
                        websocket = await websockets.connect(
                            self._main_app_ws_url, **connect_kwargs
                        )
                    except TypeError as e:
                        # Fallback if our detection was wrong
                        if (
                            "additional_headers" in str(e)
                            and "extra_headers" not in connect_kwargs
                        ):
                            connect_kwargs.pop("additional_headers", None)
                            connect_kwargs["extra_headers"] = extra_headers
                            websocket = await websockets.connect(
                                self._main_app_ws_url, **connect_kwargs
                            )
                        elif (
                            "extra_headers" in str(e)
                            and "additional_headers" not in connect_kwargs
                        ):
                            connect_kwargs.pop("extra_headers", None)
                            connect_kwargs["additional_headers"] = extra_headers
                            websocket = await websockets.connect(
                                self._main_app_ws_url, **connect_kwargs
                            )
                        else:
                            raise
                    self._main_app_ws = websocket
                    logger.info(f"Connected to main_app_ws at {self._main_app_ws_url}")
                    reconnect_delay = BINANCE_WS_RECONNECT_DELAY_BASE
                    # No longer sending depth subscriptions upon connection,
                    # since the controller itself will call ensure_subscription,
                    # which will update kline/aggTrade/depth subscriptions directly from Binance.
                    # self.loop.create_task(self._send_subscriptions_to_main_app(force_send=True), name="SendInitialSubMainApp")

                async for message in websocket:
                    if not self._running:
                        break
                    try:
                        data = json.loads(message)
                        msg_type = data.get("type")

                        if msg_type == "active_pairs_update":
                            pairs_data = data.get("data")
                            if isinstance(pairs_data, list):
                                # Pass the full screener data to the controller's queue
                                if (
                                    self.controller
                                    and self.controller._screener_update_queue
                                ):
                                    try:
                                        # Clear queue to ensure only the latest update is processed
                                        while not self.controller._screener_update_queue.empty():
                                            self.controller._screener_update_queue.get_nowait()
                                        await (
                                            self.controller._screener_update_queue.put(
                                                {"data": pairs_data}
                                            )
                                        )
                                        logger.debug(
                                            "[MainAppWS] Sent active_pairs_update to controller's screener queue."
                                        )
                                    except asyncio.QueueFull:
                                        logger.warning(
                                            "[MainAppWS] Controller's screener update queue full. Dropping update."
                                        )
                                else:
                                    logger.warning(
                                        "[MainAppWS] Controller or its screener_update_queue not available. Cannot pass active_pairs_update."
                                    )

                                # Also update local cache for compatibility with other parts of DataConsumer
                                await self._update_active_pairs_from_ws(pairs_data)
                        else:
                            logger.debug(
                                f"Unhandled message type from main_app_ws: {msg_type}"
                            )

                    except json.JSONDecodeError:
                        logger.warning(
                            f"Non-JSON from main_app_ws: {str(message)[:100]}"
                        )
                    except Exception as e_proc:
                        logger.error(
                            f"Error processing main_app_ws message: {e_proc}",
                            exc_info=True,
                        )

            except InvalidURI:
                logger.error(
                    f"Invalid URI for MainApp WS: {self._main_app_ws_url}. Loop will pause."
                )
            except websockets.exceptions.InvalidStatusCode as e_status:
                logger.error(
                    f"Main_app_ws connection FAILED with HTTP status {e_status.status_code}. "
                    f"This usually means the URL '{self._main_app_ws_url}' is a regular HTTP endpoint, not a WebSocket. "
                    f"Please check your server and the 'MAIN_APP_WS_URL' config."
                )
            except (
                ConnectionClosed,
                ConnectionClosedOK,
                WebSocketException,
                OSError,
                asyncio.TimeoutError,
            ) as e_conn:
                logger.warning(
                    f"Main_app_ws connection error/closed: {type(e_conn).__name__} - {e_conn}"
                )
            except asyncio.CancelledError:
                logger.info("Main_app_ws_loop cancelled.")
                break
            except Exception as e_outer:
                logger.error(
                    f"Unexpected error in main_app_ws_loop: {e_outer}", exc_info=True
                )
            finally:
                async with self._main_app_ws_connect_lock:
                    if self._main_app_ws is websocket:
                        self._main_app_ws = None
                if (
                    websocket
                    and hasattr(websocket, "protocol")
                    and websocket.protocol.state == State.OPEN
                ):  # Check hasattr
                    try:
                        await websocket.close(code=1001)
                    except Exception:
                        pass
                logger.debug("Main_app_ws connection cleaned up from loop.")

            if self._running:
                logger.info(f"Reconnecting to main_app_ws in {reconnect_delay:.1f}s...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(
                    reconnect_delay * 1.5, BINANCE_WS_MAX_RECONNECT_DELAY
                )
            else:
                break
        logger.info("Main_app_ws_loop finished.")

    async def _update_active_pairs_from_ws(
        self, new_pairs_data: List[Dict[str, Any]]
    ) -> bool:
        log_prefix = "[UpdateActivePairs]"
        new_symbols_set = set()
        validated_pairs_temp = []
        skipped_count = 0

        # NATR filtering removed
        # We accept ALL data from the screener and update the cache.
        # The decision on what to trade (and what to subscribe to) is made by the Controller.
        logger.info(
            f"{log_prefix} Received {len(new_pairs_data)} pairs from screener. Updating cache for ALL pairs."
        )

        # Using the full list
        pairs_to_process = new_pairs_data

        for item_raw in pairs_to_process:
            if not isinstance(item_raw, dict) or "symbol" not in item_raw:
                skipped_count += 1
                continue

            item = item_raw.copy()
            raw_symbol_name = item["symbol"]
            normalized_symbol_name = normalize_symbol_for_binance(raw_symbol_name)
            item["symbol"] = normalized_symbol_name
            symbol = item["symbol"]

            if not symbol:
                skipped_count += 1
                continue

            # Saving raw data for backward compatibility
            validated_pairs_temp.append(item)
            new_symbols_set.add(symbol)

            # Updating our new central cache
            async with self._pairs_lock:
                # Transfer only key information, the rest will be calculated
                current_pair_state = self._active_pairs[symbol]
                current_pair_state["symbol"] = symbol

                # Updating last_price if it was received
                last_price_from_ranking = item.get("last_price")
                if (
                    isinstance(last_price_from_ranking, (int, float))
                    and last_price_from_ranking > 0
                ):
                    current_pair_state["last_price"] = last_price_from_ranking

                # Save NATR if it came from the screener
                # Screener uses the key "NATR 1/30 (1m)", but we save under both keys
                natr_from_screener = item.get("NATR 1/30 (1m)")
                if isinstance(natr_from_screener, (int, float)):
                    current_pair_state["NATR 1/30 (1m)"] = (
                        natr_from_screener  # Original key
                    )
                    current_pair_state["natr"] = natr_from_screener  # Standardized key

                # Save oracle data if it arrived
                oracle_regime_from_screener = item.get("oracle_regime")
                if oracle_regime_from_screener is not None:
                    current_pair_state["oracle_regime"] = oracle_regime_from_screener

                oracle_confidence_from_screener = item.get("oracle_confidence")
                if isinstance(oracle_confidence_from_screener, (int, float)):
                    current_pair_state["oracle_confidence"] = (
                        oracle_confidence_from_screener
                    )

                # Other basic fields can be added if they come from main_app
                # For example, 24h volume, etc.
                volume_usd_val = item.get("_numeric_volume_24h")
                if volume_usd_val:
                    current_pair_state["volume_24h_usd"] = volume_usd_val

        if skipped_count > 0:
            logger.warning(
                f"{log_prefix} Skipped {skipped_count} invalid items from pairs data."
            )

        updated = False
        symbols_added_now = set()
        symbols_removed_now = set()

        async with self._pairs_lock:
            # Check if the list has changed OR if this is the first load of a non-empty list
            is_first_non_empty_load = not self._active_symbols_set and new_symbols_set
            if new_symbols_set != self._active_symbols_set or is_first_non_empty_load:
                symbols_added_now = new_symbols_set - self._active_symbols_set
                symbols_removed_now = self._active_symbols_set - new_symbols_set

                self._active_pairs_from_main_app = validated_pairs_temp
                self._active_symbols_set = new_symbols_set.copy()

                for symbol_to_remove in symbols_removed_now:
                    if symbol_to_remove in self._active_pairs:
                        del self._active_pairs[symbol_to_remove]
                    if symbol_to_remove in self._agg_trade_deques:
                        del self._agg_trade_deques[symbol_to_remove]

                updated = True
                logger.info(
                    f"{log_prefix} Active symbols list UPDATED. New count: {len(self._active_symbols_set)}"
                )
                if symbols_added_now:
                    logger.info(f"  Added symbols: {len(symbols_added_now)}")
                if symbols_removed_now:
                    logger.info(f"  Removed symbols: {len(symbols_removed_now)}")

            elif self._active_pairs_from_main_app != validated_pairs_temp:
                self._active_pairs_from_main_app = validated_pairs_temp
                updated = True
                logger.info(
                    f"{log_prefix} Active pairs data REFRESHED (symbols unchanged)."
                )

        # Automatic unsubscription removed
        # DataConsumer should not decide on its own when to unsubscribe, as this breaks the Controller's logic.
        # Controller will call remove_subscription itself when it no longer needs the symbol.
        # if updated and symbols_removed_now:
        #     for symbol_to_remove in symbols_removed_now:
        #         await self.remove_all_subscriptions_for_symbol(symbol_to_remove)

        return updated

    async def _recalculate_tape_metrics(
        self,
        symbol: str,
        current_time_ms: int,
        market_type: Optional[str] = None,
        exchange_id: str = "binance",
    ):
        """Recalculates all tape metrics for the given symbol."""
        uc_symbol = symbol.upper()
        normalized_market_type = _normalize_market_type_for_cache(
            market_type or self._effective_market_type()
        )
        trade_deque = _global_agg_trade_deques.get(
            _trade_cache_key(uc_symbol, exchange_id, normalized_market_type)
        )
        if not trade_deque:
            trade_deque = _global_agg_trade_deques.get(uc_symbol)
        if not trade_deque:
            return

        # 1. Removing old trades from deque
        min_time_ms = current_time_ms - (self.agg_trade_maxlen_seconds * 1000)
        while trade_deque and trade_deque[0]["T"] < min_time_ms:
            trade_deque.popleft()

        # 2. Calculate metrics
        if not trade_deque:  # If deque is empty after clearing
            return

        trades_df = pd.DataFrame(list(trade_deque))
        trades_df["price"] = pd.to_numeric(trades_df["p"])
        trades_df["quantity"] = pd.to_numeric(trades_df["q"])
        trades_df["volume_usd"] = trades_df["price"] * trades_df["quantity"]
        trades_df["timestamp"] = pd.to_datetime(trades_df["T"], unit="ms")
        trades_df.set_index("timestamp", inplace=True)

        # Delta: buy volume (maker - seller) minus sell volume (maker - buyer)
        trades_df["signed_volume"] = trades_df.apply(
            lambda row: -row["volume_usd"] if row["m"] else row["volume_usd"], axis=1
        )

        calculated_metrics = {}
        now = pd.to_datetime(current_time_ms, unit="ms")

        for window in TAPE_METRIC_WINDOWS:
            start_time = now - timedelta(seconds=window)
            window_df = trades_df[trades_df.index >= start_time]

            if not window_df.empty:
                calculated_metrics[f"tape_count_{window}s"] = len(window_df)
                calculated_metrics[f"tape_volume_{window}s"] = window_df[
                    "volume_usd"
                ].sum()
                calculated_metrics[f"tape_delta_{window}s"] = window_df[
                    "signed_volume"
                ].sum()
                calculated_metrics[f"tape_avg_volume_per_sec_{window}s"] = (
                    window_df["volume_usd"].sum() / window
                )
                calculated_metrics[f"tape_avg_count_per_sec_{window}s"] = (
                    len(window_df) / window
                )
            else:
                calculated_metrics[f"tape_count_{window}s"] = 0
                calculated_metrics[f"tape_volume_{window}s"] = 0.0
                calculated_metrics[f"tape_delta_{window}s"] = 0.0
                calculated_metrics[f"tape_avg_volume_per_sec_{window}s"] = 0.0
                calculated_metrics[f"tape_avg_count_per_sec_{window}s"] = 0.0

        # 3. Update central cache
        async with _global_pairs_lock:
            _global_active_pairs[uc_symbol].update(calculated_metrics)
        async with self._pairs_lock:
            self._active_pairs[uc_symbol].update(calculated_metrics)

        if self._market_data_publish_callback and calculated_metrics:
            try:
                await self._market_data_publish_callback(
                    {
                        "type": "indicator_update",
                        "stream_key": f"{exchange_id}:{normalized_market_type}:{uc_symbol.lower()}@aggTrade",
                        "data_type_key": "aggTrade",
                        "symbol": uc_symbol,
                        "market_type": normalized_market_type,
                        "exchange_id": exchange_id,
                        "metrics": calculated_metrics,
                        "pair_state": calculated_metrics,
                        "published_at_ms": int(time.time() * 1000),
                    }
                )
            except Exception as e:
                logger.error(
                    "[DataConsumer] Failed to publish tape metric update for %s: %s",
                    uc_symbol,
                    e,
                    exc_info=True,
                )

    def _parse_indicator_string(self, indicator_name: str) -> Optional[Dict[str, Any]]:
        """Parses the indicator string into parameters for pandas_ta."""
        if not indicator_name or not isinstance(indicator_name, str):
            return None

        parts = indicator_name.lower().split("_")
        kind = parts[0]

        try:
            # 1. Simple indicators (one parameter - length)
            # ADX ADDED HERE
            if kind in ["sma", "ema", "rsi", "atr", "wma", "hma", "rma", "adx"]:
                if len(parts) > 1 and parts[1].isdigit():
                    return {"kind": kind, "length": int(parts[1])}

            # 2. Bollinger Bands (BB_20_2.0)
            elif kind == "bb":
                if len(parts) > 2:
                    return {
                        "kind": "bbands",
                        "length": int(parts[1]),
                        "std": float(parts[2]),
                    }

            # 3. Bollinger Width (BBW_20_2.0) - sometimes used separately
            elif kind == "bbw":
                if len(parts) > 2:
                    return {
                        "kind": "bbands",
                        "length": int(parts[1]),
                        "std": float(parts[2]),
                    }

            # 4. Stochastic (STOCH_14_3_3)
            elif kind == "stoch" or kind.startswith("stoch"):
                # Format: STOCH_k_d_smooth (e.g., STOCH_14_3_3)
                if len(parts) >= 4:
                    return {
                        "kind": "stoch",
                        "k": int(parts[1]),
                        "d": int(parts[2]),
                        "smooth_k": int(parts[3]),
                    }

            # 5. MACD (MACD_12_26_9)
            elif kind == "macd":
                # Trying to find digits in parts
                nums = [int(p) for p in parts if p.isdigit()]
                if len(nums) >= 3:
                    return {
                        "kind": "macd",
                        "fast": nums[0],
                        "slow": nums[1],
                        "signal": nums[2],
                    }

        except (ValueError, IndexError):
            logger.warning(f"Could not parse indicator string: {indicator_name}")
            return None
        return None

    def _find_col_in_df(self, df: pd.DataFrame, indicator_name: str) -> Optional[str]:
        """Searches for a column name in the DataFrame generated by pandas_ta."""
        # 1. Direct match (ideal case)
        up_name = indicator_name.upper()
        if up_name in df.columns:
            return up_name

        # 2. Prefix search for composite indicators
        parts = indicator_name.lower().split("_")
        kind = parts[0]

        # ADX (pandas_ta creates ADX_14, DMP_14, DMN_14. We need ADX_14)
        if kind == "adx":
            # If just ADX was requested, look for any ADX_ column
            candidates = [c for c in df.columns if c.startswith("ADX_")]
            if candidates:
                return candidates[0]

        # MACD (MACD_..., MACDh_..., MACDs_...)
        elif kind == "macd":
            # If looking for a histogram
            if "hist" in indicator_name.lower():
                candidates = [c for c in df.columns if c.startswith("MACDh_")]
                if candidates:
                    return candidates[0]
            # If looking for the MACD line
            else:
                candidates = [c for c in df.columns if c.startswith("MACD_")]
                if candidates:
                    return candidates[0]

        # Bollinger Bands (BBL_..., BBU_..., BBB_...)
        elif kind == "bb":
            # BB creates several columns. This method is called when we are looking for a specific value.
            # But if we subscribed to 'BB_20_2', all columns BBL, BBU, BBB will fall into the cache.
            # Here we return None because 'BB_20_2' is not a single column, but a group.
            # The saving logic in _recalculate_kline_indicators should be smarter (see below).
            pass

        # Stochastic (STOCHk_..., STOCHd_...)
        elif kind == "stoch":
            # Same thing, this is a column group.
            pass

        # Attempting to find by partial match (for STOCHk, etc.)
        # If the strategy requested specifically 'STOCHk_14_3_3'
        if kind.startswith("stoch"):
            if up_name in df.columns:
                return up_name

        return None

    async def _recalculate_kline_indicators(
        self,
        symbol: str,
        timeframe: str,
        market_type: Optional[str] = None,
        exchange_id: str = "binance",
    ):
        """
        [FLEXIBLE VERSION]
        Recalculates only the necessary indicators for the symbol and timeframe.
        """
        uc_symbol = symbol.upper()

        async with self._metrics_lock:
            required_for_symbol = self._required_metrics.get(uc_symbol, set())

        required_indicators = {
            m for m in required_for_symbol if not m.startswith("tape_")
        }
        if not required_indicators:
            return

        normalized_market_type = _normalize_market_type_for_cache(
            market_type or self._effective_market_type()
        )
        kline_df_orig = await self.get_kline_history(
            uc_symbol, timeframe, market_type=normalized_market_type
        )
        if kline_df_orig is None or kline_df_orig.empty:
            return

        kline_df = kline_df_orig.copy()
        calculated_indicators = {}

        # 1. Calculation of indicators via pandas_ta
        ta_indicators_to_run = []
        custom_indicators = set()
        for ind_name in required_indicators:
            parsed = self._parse_indicator_string(ind_name)
            if parsed:
                ta_indicators_to_run.append(parsed)
            elif ind_name.upper() in ["NATR_30", "RELATIVE_VOLUME", "IS_VOLUME_SPIKE"]:
                custom_indicators.add(ind_name.upper())

        if ta_indicators_to_run:
            try:
                # Replacing ta.Strategy with an iterative call
                # This approach is more compatible with older versions of pandas-ta, where the Strategy class might not exist.
                # Original code with error:
                # ta_strategy = ta.Strategy(name="DynamicIndicators", ta=ta_indicators_to_run)
                # kline_df.ta.strategy(ta_strategy)

                for indicator_definition in ta_indicators_to_run:
                    params = indicator_definition.copy()
                    kind = params.pop("kind", None)
                    if not kind:
                        logger.warning(
                            f"[IndicatorCalc:{uc_symbol}] Missing indicator without 'kind': {indicator_definition}"
                        )
                        continue

                    # Ensure the indicator will be added to the DataFrame
                    params["append"] = True

                    # Get the required function from the .ta accessor (e.g., kline_df.ta.sma)
                    indicator_function = getattr(kline_df.ta, kind, None)

                    if indicator_function and callable(indicator_function):
                        # Call the function with its parameters (e.g., indicator_function(length=50, append=True))
                        indicator_function(**params)
                    else:
                        logger.warning(
                            f"[IndicatorCalc:{uc_symbol}] Failed to find function for indicator 'ta.{kind}'"
                        )
            except Exception as e:
                logger.error(
                    f"[IndicatorCalc:{uc_symbol}] Failed to calculate pandas_ta indicators: {e}",
                    exc_info=True,
                )

        # 2. Calculation of custom indicators
        if "NATR_30" in custom_indicators:
            try:
                # Calculating scalping NATR using the methodology from utils.py
                kline_df = calculate_scalper_natr(kline_df, period=30)
                logger.debug(
                    f"[IndicatorCalc:{uc_symbol}] NATR_30 calculated (scalper formula)."
                )
            except Exception as e:
                logger.error(
                    f"[IndicatorCalc:{uc_symbol}] Error calculating NATR_30: {e}",
                    exc_info=True,
                )

        if "RELATIVE_VOLUME" in custom_indicators:
            try:
                kline_df = add_relative_volume(kline_df, period=20)
                logger.debug(
                    f"[IndicatorCalc:{uc_symbol}] relative_volume calculated (period=20)."
                )
            except Exception as e:
                logger.error(
                    f"[IndicatorCalc:{uc_symbol}] Error calculating relative_volume: {e}",
                    exc_info=True,
                )

        if "IS_VOLUME_SPIKE" in custom_indicators:
            try:
                kline_df = add_volume_percentile_rank(kline_df, period=1000, percentile=90)
                logger.debug(
                    f"[IndicatorCalc:{uc_symbol}] is_volume_spike calculated (period=1000, pct=90)."
                )
            except Exception as e:
                logger.error(
                    f"[IndicatorCalc:{uc_symbol}] Error calculating is_volume_spike: {e}",
                    exc_info=True,
                )

        # 3. Saving calculated indicators to the GLOBAL cache
        # This is critically important for multi-user mode
        publish_update: Optional[Dict[str, Any]] = None
        try:
            if not kline_df.empty:
                last_candle = kline_df.iloc[-1]

                # Use the GLOBAL cache so that all DataConsumers see the indicators
                async with _global_pairs_lock:
                    global_pair_state = _global_active_pairs[uc_symbol]

                    # Also update the LOCAL cache of the current instance for backward compatibility and tests
                    async with self._pairs_lock:
                        local_pair_state = self._active_pairs.get(uc_symbol, {})

                    for col in kline_df.columns:
                        if col.lower() in [
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                            "open_time",
                        ]:
                            continue

                        val = last_candle[col]
                        if pd.notna(val):
                            val_float = float(val)
                            calculated_indicators[col.lower()] = val_float
                            global_pair_state[col.lower()] = val_float
                            local_pair_state[col.lower()] = val_float

                            # Accounting for ATRr and ATR
                            col_upper = col.upper()
                            # pandas_ta may name the column ATR_14 or ATRr_14
                            if col_upper.startswith("ATR_") or col_upper.startswith(
                                "ATRR_"
                            ):
                                calculated_indicators["atr"] = val_float
                                global_pair_state["atr"] = val_float
                                local_pair_state["atr"] = val_float

                    # Saving local cache back (in case it was created as a new dictionary)
                    async with self._pairs_lock:
                        self._active_pairs[uc_symbol] = local_pair_state

                    if self._market_data_publish_callback and calculated_indicators:
                        publish_update = {
                            "type": "indicator_update",
                            "stream_key": f"{exchange_id}:{normalized_market_type}:{uc_symbol.lower()}@kline_{timeframe}",
                            "data_type_key": f"kline_{timeframe}",
                            "symbol": uc_symbol,
                            "market_type": normalized_market_type,
                            "exchange_id": exchange_id,
                            "indicators": calculated_indicators,
                            "pair_state": calculated_indicators,
                            "published_at_ms": int(time.time() * 1000),
                        }

        except Exception as e:
            logger.error(f"Error saving indicators to global cache: {e}")
            return

        if publish_update:
            await self._market_data_publish_callback(publish_update)

    def _aggregate_depth(
        self, full_depth: Dict[str, Any], market_price: float
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Aggregates the full L2 order book into 10 percent "buckets".
        """
        if not market_price or market_price <= 0:
            return {"bids": [], "asks": []}

        # Defining bin boundaries (from -5% to +5% with 1% step)
        percentages = [-5, -4, -3, -2, -1, 1, 2, 3, 4, 5]
        buckets = {p: {"notional": 0.0, "volume": 0.0} for p in percentages}

        # Bids aggregation
        for price_str, qty_str in full_depth.get("bids", []):
            try:
                price = float(price_str)
                qty = float(qty_str)
                deviation = ((price / market_price) - 1) * 100

                # Finding the nearest "bucket" from below
                bucket_key = max(
                    [p for p in percentages if p <= deviation], default=None
                )
                if bucket_key is not None:
                    buckets[bucket_key]["notional"] += price * qty
                    buckets[bucket_key]["volume"] += qty
            except (ValueError, TypeError):
                continue

        # Asks aggregation
        for price_str, qty_str in full_depth.get("asks", []):
            try:
                price = float(price_str)
                qty = float(qty_str)
                deviation = ((price / market_price) - 1) * 100

                # Finding the nearest "bucket" from above
                bucket_key = min(
                    [p for p in percentages if p >= deviation], default=None
                )
                if bucket_key is not None:
                    buckets[bucket_key]["notional"] += price * qty
                    buckets[bucket_key]["volume"] += qty
            except (ValueError, TypeError):
                continue

        aggregated_bids = []
        aggregated_asks = []
        for p in sorted(buckets.keys()):
            avg_price = (
                (buckets[p]["notional"] / buckets[p]["volume"])
                if buckets[p]["volume"] > 0
                else 0
            )

            record = {
                "percentage": p,
                "depth": buckets[p]["notional"],  # Use notional as "depth"
                "notional": buckets[p]["notional"],
                "avg_price": avg_price,
            }
            if p < 0:
                aggregated_bids.append(record)
            else:
                aggregated_asks.append(record)

        return {
            "bids": sorted(
                aggregated_bids, key=lambda x: x["percentage"], reverse=True
            ),
            "asks": sorted(aggregated_asks, key=lambda x: x["percentage"]),
        }

    async def _update_local_cache(
        self,
        data_type_key: str,
        symbol: str,
        payload: Any,
        market_type: Optional[str] = None,
        exchange_id: str = "binance",
    ):
        uc_symbol = symbol.upper()
        log_prefix_base = f"[CacheUpdate:{data_type_key}:{uc_symbol}]"

        # 1. UPDATING GLOBAL CACHES (for multi-user mode)
        # Using global caches so that all DataConsumer see the same data
        async with _global_cache_lock:
            # Kline processing
            if data_type_key.startswith("kline_"):
                timeframe = data_type_key.split("_", 1)[1]
                cache_key = _kline_cache_key(
                    uc_symbol,
                    timeframe,
                    exchange_id,
                    market_type or self._effective_market_type(),
                )
                kline_cache_deque = _global_kline_cache[cache_key]

                if (
                    isinstance(payload, dict)
                    and payload.get("e") == "kline"
                    and payload.get("k")
                ):
                    k_data = payload["k"]
                    try:
                        candle_tuple = (
                            int(k_data["t"]),
                            float(k_data["o"]),
                            float(k_data["h"]),
                            float(k_data["l"]),
                            float(k_data["c"]),
                            float(k_data["v"]),
                        )

                        # Updating or adding a candle to the deque
                        if (
                            kline_cache_deque
                            and kline_cache_deque[-1][0] == candle_tuple[0]
                        ):
                            kline_cache_deque[-1] = candle_tuple
                        else:
                            kline_cache_deque.append(candle_tuple)
                        _global_kline_df_cache[cache_key] = (
                            _upsert_kline_dataframe_cache(
                                _global_kline_df_cache.get(cache_key), candle_tuple
                            )
                        )
                        legacy_cache_key = f"{exchange_id}:{uc_symbol}:{timeframe}"
                        if legacy_cache_key != cache_key:
                            legacy_deque = _global_kline_cache[legacy_cache_key]
                            if legacy_deque and legacy_deque[-1][0] == candle_tuple[0]:
                                legacy_deque[-1] = candle_tuple
                            else:
                                legacy_deque.append(candle_tuple)
                            _global_kline_df_cache[legacy_cache_key] = (
                                _upsert_kline_dataframe_cache(
                                    _global_kline_df_cache.get(legacy_cache_key),
                                    candle_tuple,
                                )
                            )

                        # Updating last_price in the GLOBAL cache
                        async with _global_pairs_lock:
                            _global_active_pairs[uc_symbol]["last_price"] = (
                                candle_tuple[4]
                            )  # close price

                        # If the candle is closed, trigger indicator recalculation
                        if k_data.get("x", False) and not self._use_redis_market_data:
                            self.loop.create_task(
                                self._recalculate_kline_indicators(
                                    uc_symbol,
                                    timeframe,
                                    market_type=market_type
                                    or self._effective_market_type(),
                                    exchange_id=exchange_id,
                                )
                            )

                    except (ValueError, TypeError, KeyError) as e:
                        logger.warning(
                            f"{log_prefix_base} Error parsing Binance kline payload: {e}"
                        )

            # AggTrade processing
            elif data_type_key == "aggTrade":
                if isinstance(payload, dict) and payload.get("e") == "aggTrade":
                    try:
                        trade_data = {
                            "T": int(payload["T"]),  # Timestamp
                            "p": payload["p"],  # Price
                            "q": payload["q"],  # Quantity
                            "m": bool(payload["m"]),  # Is buyer maker
                        }
                        _global_agg_trade_deques[
                            _trade_cache_key(
                                uc_symbol,
                                exchange_id,
                                market_type or self._effective_market_type(),
                            )
                        ].append(trade_data)
                        _global_agg_trade_deques[uc_symbol].append(trade_data)

                        # Updating last_price in the GLOBAL cache
                        async with _global_pairs_lock:
                            _global_active_pairs[uc_symbol]["last_price"] = float(
                                trade_data["p"]
                            )

                        # Starting recalculation of tape metrics
                        if not self._use_redis_market_data:
                            self.loop.create_task(
                                self._recalculate_tape_metrics(
                                    uc_symbol,
                                    trade_data["T"],
                                    market_type=market_type
                                    or self._effective_market_type(),
                                    exchange_id=exchange_id,
                                )
                            )

                    except (ValueError, TypeError, KeyError) as e:
                        logger.warning(
                            f"{log_prefix_base} Error parsing aggTrade payload: {e}"
                        )

            # Depth processing (remains unchanged)
            elif data_type_key == "depth":
                # Restored logic for processing and caching the L2 order book
                if (
                    isinstance(payload, dict)
                    and payload.get("e") == "depthUpdate"
                    and market_type
                ):
                    uc_symbol_local = payload["s"].upper()

                    market_type_for_cache = (
                        "futures" if "futures" in market_type else market_type.lower()
                    )
                    cache_key = f"{uc_symbol_local}_{market_type_for_cache}"

                    bids = self._normalize_depth_levels(payload.get("b", []))
                    asks = self._normalize_depth_levels(payload.get("a", []))
                    full_l2_depth = {
                        "lastUpdateId": payload.get("u"),
                        "bids": bids,
                        "asks": asks,
                    }
                    market_price = (
                        (bids[0][0] + asks[0][0]) / 2.0 if bids and asks else 0.0
                    )
                    aggregated_depth = (
                        self._aggregate_depth(full_l2_depth, market_price)
                        if market_price > 0
                        else {"bids": [], "asks": []}
                    )

                    # Enriched format keeps backward compatibility:
                    # - bids/asks/lastUpdateId for legacy users
                    # - full_l2_depth/aggregated_depth for advanced orderbook logic
                    self._latest_depth_cache[cache_key] = {
                        "lastUpdateId": payload.get("u"),
                        "bids": bids,
                        "asks": asks,
                        "full_l2_depth": full_l2_depth,
                        "aggregated_depth": aggregated_depth,
                        "event_time_ms": int(payload.get("E") or 0),
                        "cached_at_ms": int(time.time() * 1000),
                    }

        # 2. BROADCAST EVENTS TO ALL REGISTERED QUEUES
        # Defining stream_key to get the list of queues
        stream_key = None
        if data_type_key.startswith("kline_"):
            timeframe = data_type_key.split("_", 1)[1]
            stream_key = f"{exchange_id}:{market_type or self._effective_market_type()}:{uc_symbol.lower()}@kline_{timeframe}"
        elif data_type_key == "aggTrade":
            stream_key = f"{exchange_id}:{market_type or self._effective_market_type()}:{uc_symbol.lower()}@aggTrade"
        elif data_type_key == "depth":
            stream_key = f"{exchange_id}:{market_type or self._effective_market_type()}:{uc_symbol.lower()}{getattr(config, 'BINANCE_DEPTH_STREAM_NAME', '@depth')}"
        elif data_type_key == "open_interest":
            stream_key = f"{exchange_id}:{market_type or self._effective_market_type()}:{uc_symbol.lower()}@openInterest"

        if self._market_data_publish_callback and stream_key:
            logger.info(
                "[BroadcastCheck] stream_key=%s data_type_key=%s",
                stream_key,
                data_type_key,
            )
            try:
                await self._market_data_publish_callback(
                    {
                        "type": "market_payload",
                        "stream_key": stream_key,
                        "data_type_key": data_type_key,
                        "symbol": uc_symbol,
                        "market_type": _normalize_market_type_for_cache(
                            market_type or self._effective_market_type()
                        ),
                        "exchange_id": exchange_id,
                        "payload": payload,
                        "published_at_ms": int(time.time() * 1000),
                    }
                )
            except Exception as e:
                logger.error(
                    "[DataConsumer] Failed to publish market payload for %s: %s",
                    stream_key,
                    e,
                    exc_info=True,
                )

        event_to_push = None
        if data_type_key.startswith("kline_"):
            k_data = payload.get("k", {})
            if k_data.get("x", False):
                timeframe = data_type_key.split("_", 1)[1]
                event_to_push = {
                    "type": "CANDLE_CLOSE",
                    "symbol": uc_symbol,
                    "timeframe": timeframe,
                    "market_type": _normalize_market_type_for_cache(
                        market_type or self._effective_market_type()
                    ),
                    "timestamp_ms": int(k_data["t"]),
                }
        elif data_type_key == "aggTrade":
            event_to_push = {
                "type": "TICK",
                "symbol": uc_symbol,
                "market_type": _normalize_market_type_for_cache(
                    market_type or self._effective_market_type()
                ),
                "price": float(payload["p"]),
                "quantity": float(payload["q"]),
                "timestamp_ms": int(payload["T"]),
            }

        if event_to_push and stream_key:
            logger.info(
                "[DataConsumer] Enqueue market event: type=%s stream_key=%s symbol=%s timeframe=%s market_type=%s",
                event_to_push.get("type"),
                stream_key,
                event_to_push.get("symbol"),
                event_to_push.get("timeframe"),
                event_to_push.get("market_type"),
            )
            # Broadcast to ALL registered queues
            async with _global_event_queues_lock:
                queues_to_notify = _global_event_queues.get(stream_key, set()).copy()

            for queue in queues_to_notify:
                try:
                    queue.put_nowait(event_to_push)
                except asyncio.QueueFull:
                    logger.warning(
                        "[DataConsumer] Event queue full during broadcast. Event dropped."
                    )
            if (
                self._use_redis_market_data
                and self.event_queue
                and self.event_queue not in queues_to_notify
            ):
                try:
                    self.event_queue.put_nowait(event_to_push)
                except asyncio.QueueFull:
                    logger.warning(
                        "[DataConsumer] Local event queue full during market-data update. Event dropped."
                    )

    async def _send_subscriptions_to_main_app(self, force_send: bool = False):
        log_prefix = "[SendSubMainApp]"
        async with self._main_app_ws_connect_lock:
            current_required_main_app_actual = (
                self._required_streams_for_main_app.copy()
            )
            ws = self._main_app_ws
            send_needed = (
                current_required_main_app_actual
                != self._last_sent_subscriptions_to_main_app
            ) or force_send
            if send_needed:
                if not ws or not ws.open:
                    logger.warning(
                        f"{log_prefix} Cannot send: Main app WS not connected."
                    )
                    return
                streams_to_send_now = [
                    s
                    for s in current_required_main_app_actual
                    if s.startswith("depth:")
                ]
                if (
                    not streams_to_send_now
                    and not self._last_sent_subscriptions_to_main_app
                    and not force_send
                ):
                    return
                logger.info(
                    f"{log_prefix} Updating subscriptions to main_app. Sending {len(streams_to_send_now)} depth streams: {streams_to_send_now if streams_to_send_now else 'EMPTY LIST (to clear)'}"
                )
                message = {"action": "subscribe", "streams": streams_to_send_now}
                try:
                    await asyncio.wait_for(ws.send(json.dumps(message)), timeout=5.0)
                    self._last_sent_subscriptions_to_main_app = (
                        current_required_main_app_actual
                    )
                    logger.info(
                        f"{log_prefix} Sent subscription request to main_app successfully."
                    )
                except Exception as e:
                    logger.error(
                        f"{log_prefix} Error sending subscriptions to main_app: {e}"
                    )

    async def _binance_data_ws_loop(
        self,
        symbol_uc: str,
        data_type_key: str,
        binance_stream_id: str,
        ws_url_to_use: str,
        market_type_for_cache: str,
        exchange_id: str = "binance",
    ):
        log_prefix = f"[BinanceWS:{data_type_key}:{symbol_uc}:{market_type_for_cache}]"
        logger.info(
            f"{log_prefix} Task started. Initial self._running: {self._running}. Target URL: {ws_url_to_use}"
        )  # New log
        reconnect_delay = getattr(config, "BINANCE_WS_RECONNECT_DELAY_BASE", 5)
        current_task = asyncio.current_task()

        # logger.info(f"{log_prefix} Starting WebSocket loop. URL: {ws_url_to_use}.") # Replaced by the one above
        for _ in range(20):
            if await _is_global_stream_active(binance_stream_id, current_task):
                break
            await asyncio.sleep(0)

        while await _is_global_stream_active(binance_stream_id, current_task):
            websocket = None
            try:
                logger.info(
                    f"{log_prefix} Attempting actual connection to URL: {ws_url_to_use} with ping_interval=20, ping_timeout=10, open_timeout=15"
                )
                try:
                    websocket = await websockets.connect(
                        ws_url_to_use,
                        ping_interval=20,
                        ping_timeout=10,
                        open_timeout=15,
                    )
                except Exception as e_connect:
                    logger.error(
                        f"{log_prefix} DIRECT connect attempt FAILED: {type(e_connect).__name__} - {e_connect}",
                        exc_info=True,
                    )
                    # Re-raise or handle to ensure the outer loop's reconnect logic is triggered
                    raise  # This will be caught by the outer try-except block

                logger.info(f"{log_prefix} Successfully connected to Binance WS. websocket_state={websocket.state}")
                async with self._binance_market_data_ws_lock:
                    if (
                        self._binance_market_data_ws_tasks.get(binance_stream_id)
                        is asyncio.current_task()
                    ):
                        self._binance_market_data_clients[binance_stream_id] = websocket
                async with _global_ws_registry_lock:
                    registry_entry = _global_ws_registry.get(binance_stream_id)
                    if registry_entry and registry_entry.get("task") is current_task:
                        registry_entry["client"] = websocket

                reconnect_delay = getattr(config, "BINANCE_WS_RECONNECT_DELAY_BASE", 5)

                logger.info(f"{log_prefix} Starting message loop.")
                async for message in websocket:
                    if not await _is_global_stream_active(
                        binance_stream_id, current_task
                    ):
                        logger.info(
                            f"{log_prefix} Stream removed from global registry. Closing WS."
                        )
                        break

                    try:
                        parsed_message = json.loads(message)
                        payload_to_process = (
                            parsed_message if "e" in parsed_message else None
                        )

                        if payload_to_process:
                            await self._update_local_cache(
                                data_type_key,
                                symbol_uc,
                                payload_to_process,
                                market_type=market_type_for_cache,
                                exchange_id=exchange_id,
                            )
                            logger.info(
                                "%s UpdateLocalCache called for msg_type=%s",
                                log_prefix,
                                parsed_message.get("e", "?"),
                            )
                        else:
                            logger.warning(
                                f"{log_prefix} Unknown message structure: {str(parsed_message)[:300]}"
                            )

                    except json.JSONDecodeError:
                        logger.warning(
                            f"{log_prefix} Non-JSON message: {str(message)[:100]}"
                        )
                    except Exception as e_proc:
                        logger.error(
                            f"{log_prefix} Error processing message: {e_proc}",
                            exc_info=True,
                        )

            except (
                ConnectionRefusedError,
                InvalidURI,
            ) as e:  # InvalidURI is already imported
                logger.error(
                    f"{log_prefix} Unrecoverable WS error: {type(e).__name__} - {e}. The loop for this task will stop."
                )
                break  # Exiting the while self._running loop

            except (
                ConnectionClosed,
                ConnectionClosedOK,
                ConnectionClosedError,
                OSError,
                asyncio.TimeoutError,
                WebSocketException,
            ) as e:  # More specific WS exceptions, InvalidStatus is a subclass of WebSocketException
                logger.warning(
                    f"{log_prefix} WS connection closed/error: {type(e).__name__} - {e}."
                )
                # Log state BEFORE deciding to reconnect
                is_task_still_active = await _is_global_stream_active(
                    binance_stream_id, current_task
                )

                logger.debug(
                    f"{log_prefix} State before reconnect decision: task_active_in_global_registry={is_task_still_active}"
                )

                if is_task_still_active:
                    # Reconnect logic is handled by the loop continuing and re-attempting connection after a delay
                    logger.info(
                        f"{log_prefix} Will attempt to reconnect on the next iteration if conditions allow."
                    )
                else:
                    logger.info(
                        f"{log_prefix} Not attempting reconnect because stream was removed from global registry."
                    )
                    break  # Break from the main while self._running loop

            except asyncio.CancelledError:
                logger.info(f"{log_prefix} WS task explicitly cancelled.")
                break  # Exit the loop

            except Exception as e_outer:
                logger.error(
                    f"{log_prefix} Unexpected WS error in outer loop: {e_outer}",
                    exc_info=True,
                )

            finally:
                if websocket and websocket.state == State.OPEN:
                    if self.loop.is_running():
                        try:
                            await websocket.close()
                        except RuntimeError as e:
                            if "Event loop is closed" in str(e):
                                logger.warning(
                                    f"{log_prefix} Could not close websocket, event loop is already closed."
                                )
                            else:
                                raise  # Re-raise other RuntimeErrors
                    else:
                        logger.warning(
                            f"{log_prefix} Event loop not running, cannot close websocket for {binance_stream_id}."
                        )
                async with self._binance_market_data_ws_lock:
                    self._binance_market_data_clients.pop(binance_stream_id, None)
                async with _global_ws_registry_lock:
                    registry_entry = _global_ws_registry.get(binance_stream_id)
                    if registry_entry and registry_entry.get("client") is websocket:
                        registry_entry["client"] = None

            if not await _is_global_stream_active(binance_stream_id, current_task):
                break

            logger.info(f"{log_prefix} Reconnecting in {reconnect_delay:.1f}s...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 1.5, 60)

        logger.info(f"{log_prefix} WS loop finished.")
        async with _global_ws_registry_lock:
            registry_entry = _global_ws_registry.get(binance_stream_id)
            if registry_entry and registry_entry.get("task") is current_task:
                logger.warning(
                    f"{log_prefix} Removing stale global registry entry for finished stream task: {binance_stream_id}"
                )
                del _global_ws_registry[binance_stream_id]
                async with _global_event_queues_lock:
                    _global_event_queues.pop(binance_stream_id, None)
        async with self._binance_market_data_ws_lock:
            self._binance_market_data_ws_tasks.pop(binance_stream_id, None)

    async def _ccxt_pro_data_ws_loop(
        self,
        symbol: str,
        data_type_key: str,
        stream_id: str,
        market_type: str,
        executor: Optional["ExchangeExecutor"] = None,
        exchange_id: str = "binance",
    ):
        log_prefix = f"[CcxtProWS:{data_type_key}:{symbol}:{market_type}]"
        logger.info(f"{log_prefix} Task started for CCXT Pro streaming.")

        executor = executor or self._executor_for_market(market_type)
        # We need the ccxt.pro exchange instance. It is usually inside self._executor._exchange_pro
        ccxt_pro_client = getattr(executor, "_exchange_pro", None)
        if ccxt_pro_client is None:
            logger.error(
                f"{log_prefix} CCXT Pro client is NOT available on the executor. Cannot stream."
            )
            return

        ccxt_symbol = symbol.upper()
        # Some exchanges need CCXT format like "BTC/USDT" or "BTC/USDT:USDT"
        if hasattr(executor, "_normalize_symbol"):
            ccxt_symbol = executor._normalize_symbol(symbol)

        last_emitted_closed_ts = (
            set()
        )  # Using a local set to track emitted closures in this task
        prev_last_candle_data = None
        is_first_batch = True

        while self._running:
            try:
                if data_type_key.startswith("kline_"):
                    timeframe = data_type_key.split("_", 1)[1]
                    # watch_ohlcv returns an array of arrays: [[timestamp, open, high, low, close, volume], ...]
                    ohlcv_list = await asyncio.wait_for(
                        ccxt_pro_client.watch_ohlcv(ccxt_symbol, timeframe),
                        timeout=30.0,
                    )
                    if ohlcv_list:
                        logger.info(
                            f"{log_prefix} Received {len(ohlcv_list)} candles from {ccxt_symbol}, "
                            f"last_ts={ohlcv_list[-1][0]}"
                        )
                        current_last_ts = ohlcv_list[-1][0]

                        # 1. Checking if the previous 'last' candle has closed
                        if (
                            prev_last_candle_data is not None
                            and current_last_ts > prev_last_candle_data[0]
                        ):
                            # The previous 'current' candle is now definitely closed.
                            prev_ts = prev_last_candle_data[0]

                            if prev_ts not in last_emitted_closed_ts:
                                # Emitting close using saved data
                                payload = {
                                    "e": "kline",
                                    "k": {
                                        "t": prev_ts,
                                        "o": str(prev_last_candle_data[1]),
                                        "h": str(prev_last_candle_data[2]),
                                        "l": str(prev_last_candle_data[3]),
                                        "c": str(prev_last_candle_data[4]),
                                        "v": str(prev_last_candle_data[5]),
                                        "x": True,
                                    },
                                }
                                await self._update_local_cache(
                                    data_type_key,
                                    symbol,
                                    payload,
                                    market_type,
                                    exchange_id,
                                )
                                last_emitted_closed_ts.add(prev_ts)

                        # 2. Processing the current (open) candle and missed closed ones (if any)
                        for i, candle in enumerate(ohlcv_list):
                            candle_ts = candle[0]
                            is_closed = candle_ts < current_last_ts

                            if is_closed:
                                if candle_ts in last_emitted_closed_ts:
                                    continue
                                last_emitted_closed_ts.add(candle_ts)

                                # IMPORTANT: If this is the FIRST packet after subscription, we emit only
                                # The MOST RECENT closed candle from the list (the one immediately before the current one),
                                # to avoid spamming with the entire old history (e.g., 500 candles).
                                if is_first_batch and i < len(ohlcv_list) - 2:
                                    continue

                            # Reformat to Binance Payload
                            payload = {
                                "e": "kline",
                                "k": {
                                    "t": candle_ts,
                                    "o": str(candle[1]),
                                    "h": str(candle[2]),
                                    "l": str(candle[3]),
                                    "c": str(candle[4]),
                                    "v": str(candle[5]),
                                    "x": is_closed,
                                },
                            }
                            logger.info(
                                f"{log_prefix} Updating local cache for candle ts={candle_ts} is_closed={is_closed}"
                            )
                            await self._update_local_cache(
                                data_type_key, symbol, payload, market_type, exchange_id
                            )

                        # Clear old TS from the set if it is too large
                        if len(last_emitted_closed_ts) > 100:
                            min_ts = min(last_emitted_closed_ts)
                            last_emitted_closed_ts.remove(min_ts)

                        prev_last_candle_data = ohlcv_list[-1]
                        is_first_batch = False  # Subsequent updates will emit closes

                elif data_type_key == "aggTrade":
                    # watch_trades returns a list of trade dictionaries
                    trades = await ccxt_pro_client.watch_trades(ccxt_symbol)
                    if trades:
                        for trade in trades:
                            # Reformat to Binance payload
                            payload = {
                                "e": "aggTrade",
                                "T": trade.get("timestamp", int(time.time() * 1000)),
                                "p": str(trade.get("price", "0")),
                                "q": str(trade.get("amount", "0")),
                                "m": trade.get("side", "").lower()
                                == "sell",  # Sell order filled
                            }
                            await self._update_local_cache(
                                data_type_key, symbol, payload, market_type, exchange_id
                            )

                elif data_type_key == "depth":
                    # watch_order_book returns unified orderbook
                    limit = 50 if exchange_id == "bybit" else None
                    orderbook = await ccxt_pro_client.watch_order_book(
                        ccxt_symbol, limit
                    )
                    if orderbook:
                        # Reformat to Binance payload
                        payload = {
                            "e": "depthUpdate",
                            "s": symbol,
                            "E": int(time.time() * 1000),
                            "u": orderbook.get("nonce"),
                            "b": [
                                [str(level[0]), str(level[1])]
                                for level in orderbook.get("bids", [])
                            ],
                            "a": [
                                [str(level[0]), str(level[1])]
                                for level in orderbook.get("asks", [])
                            ],
                        }
                        await self._update_local_cache(
                            data_type_key, symbol, payload, market_type, exchange_id
                        )

                # Check stream is still relevant
                async with _global_ws_registry_lock:
                    if stream_id not in _global_ws_registry:
                        break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"{log_prefix} Error in CCXT Pro stream: {e}", exc_info=True
                )
                await asyncio.sleep(5)

        logger.info(f"{log_prefix} CCXT Pro stream finished.")
        async with self._binance_market_data_ws_lock:
            self._binance_market_data_ws_tasks.pop(stream_id, None)
