# ruff: noqa: E402
# bot_module/controller.py

import asyncio
import logging
import time
import uuid
from typing import Dict, Optional, Any, Set, List, Tuple, Union, Callable
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_UP, ROUND_DOWN, InvalidOperation
import pandas as pd
import json
from pathlib import Path
import pandas_ta as ta
import redis.asyncio as redis
import copy

from api import crud
from api.database import get_db as _default_get_db
from api.push_sender import send_push_notification  # New import
from api.schemas import SymbolSelectionConfig  # Import the new schema

# Importing module components
from bot_module import config
from bot_module.feature_extractor import FeatureExtractor
from bot_module.model_pipeline import ModelPipeline
from bot_module.realtime_ml_logger import RealtimeMLLogger
from bot_module.data_consumer import DataConsumer
from bot_module.executor import BinanceExecutor
from bot_module.paper_executor import PaperTradingExecutor
from bot_module.risk_manager import RiskManager
from bot_module.trade_logger import TradeLogger
from bot_module.telegram_notifier import TelegramNotifier
from bot_module.strategy import SignalDirection
from bot_module.strategy import (
    StrategySignal,
    get_strategy_instance,
    create_strategy_instance,
    BaseStrategy,
    OrderMode,
    PartialTarget,
    STRATEGIES,  # noqa: F401 — re-exported for test patching
)

try:
    # Import OnlineAgentStrategy if available
    from bot_module.ml_strategy import OnlineAgentStrategy
except ImportError:
    OnlineAgentStrategy = None  # Stub if the module is not found
    if hasattr(config, "USE_ML_AGENT"):
        config.USE_ML_AGENT = False


logger = logging.getLogger("bot_module.controller")
# Check in case the logger is not configured globally
if not logging.getLogger("bot_module").hasHandlers():
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    logger.warning("Root logger 'bot_module' has no handlers. Basic config applied.")

if OnlineAgentStrategy is None:
    logging.getLogger("bot_module.controller").warning(
        "OnlineAgentStrategy not found, ML agent disabled."
    )

from bot_module.datatypes import BasePosition
from bot_module.phantom_tracker import (
    get_phantom_tracker,
)  # Phantom trade tracking for BE analysis


def _normalize_position_market_type(raw_market_type: Optional[Any]) -> str:
    raw = (
        str(raw_market_type or config.TRADING_MARKET_TYPE or "futures_usdtm")
        .strip()
        .lower()
        .replace("-", "_")
    )
    if raw in {"futures", "future", "futures_usdtm", "usdtm", "linear", "perp", "swap"}:
        return "futures_usdtm"
    if raw == "spot":
        return "spot"
    return raw or "futures_usdtm"


def _make_position_key(market_type: Optional[Any], symbol: str) -> str:
    return f"{_normalize_position_market_type(market_type)}:{str(symbol).upper()}"


class ActivePositionMap(dict):
    """
    Stores live positions by market-aware key while preserving legacy symbol-only
    reads when the symbol is unambiguous.
    """

    @staticmethod
    def _market_type_for_value(position: Any) -> str:
        direct_market_type = getattr(position, "market_type", None)
        if direct_market_type:
            return _normalize_position_market_type(direct_market_type)
        signal_details = getattr(position, "signal_details", None)
        if isinstance(signal_details, dict):
            for key in ("market_type", "marketType", "market"):
                if signal_details.get(key):
                    return _normalize_position_market_type(signal_details[key])
        return _normalize_position_market_type(None)

    @classmethod
    def key_for_position(cls, position: Any) -> str:
        return _make_position_key(
            cls._market_type_for_value(position), getattr(position, "symbol", "")
        )

    @staticmethod
    def key_for_symbol(symbol: str, market_type: Optional[Any]) -> str:
        return _make_position_key(market_type, symbol)

    @staticmethod
    def _is_composite_key(key: Any) -> bool:
        return isinstance(key, str) and ":" in key

    def _normalize_key(self, key: Any) -> Any:
        if isinstance(key, tuple) and len(key) == 2:
            return _make_position_key(key[0], key[1])
        if self._is_composite_key(key):
            market_type, symbol = str(key).split(":", 1)
            return _make_position_key(market_type, symbol)
        return str(key).upper() if isinstance(key, str) else key

    def _matching_keys(
        self, symbol: str, market_type: Optional[Any] = None
    ) -> List[str]:
        symbol_upper = str(symbol).upper()
        if market_type is not None:
            key = _make_position_key(market_type, symbol_upper)
            return [key] if dict.__contains__(self, key) else []
        return [
            key
            for key, position in dict.items(self)
            if str(getattr(position, "symbol", "")).upper() == symbol_upper
        ]

    def get_by_symbol(
        self, symbol: str, market_type: Optional[Any] = None, default: Any = None
    ) -> Any:
        if market_type is not None:
            return dict.get(self, _make_position_key(market_type, symbol), default)
        normalized_key = self._normalize_key(symbol)
        if dict.__contains__(self, normalized_key):
            return dict.get(self, normalized_key, default)
        matches = self._matching_keys(symbol)
        if len(matches) == 1:
            return dict.get(self, matches[0], default)
        return default

    def pop_by_symbol(
        self, symbol: str, market_type: Optional[Any] = None, default: Any = None
    ) -> Any:
        if market_type is not None:
            return dict.pop(self, _make_position_key(market_type, symbol), default)
        normalized_key = self._normalize_key(symbol)
        if dict.__contains__(self, normalized_key):
            return dict.pop(self, normalized_key)
        matches = self._matching_keys(symbol)
        if len(matches) == 1:
            return dict.pop(self, matches[0])
        return default

    def __setitem__(self, key: Any, value: Any) -> None:
        if hasattr(value, "symbol"):
            key = self.key_for_position(value)
        else:
            key = self._normalize_key(key)
        dict.__setitem__(self, key, value)

    def __getitem__(self, key: Any) -> Any:
        normalized_key = self._normalize_key(key)
        if dict.__contains__(self, normalized_key):
            return dict.__getitem__(self, normalized_key)
        if isinstance(key, str):
            matches = self._matching_keys(key)
            if len(matches) == 1:
                return dict.__getitem__(self, matches[0])
        raise KeyError(key)

    def get(self, key: Any, default: Any = None) -> Any:
        normalized_key = self._normalize_key(key)
        if dict.__contains__(self, normalized_key):
            return dict.get(self, normalized_key, default)
        if isinstance(key, str):
            return self.get_by_symbol(key, default=default)
        return default

    def __contains__(self, key: Any) -> bool:
        normalized_key = self._normalize_key(key)
        if dict.__contains__(self, normalized_key):
            return True
        if isinstance(key, str):
            return len(self._matching_keys(key)) == 1
        return False

    def __delitem__(self, key: Any) -> None:
        normalized_key = self._normalize_key(key)
        if dict.__contains__(self, normalized_key):
            dict.__delitem__(self, normalized_key)
            return
        if isinstance(key, str):
            matches = self._matching_keys(key)
            if len(matches) == 1:
                dict.__delitem__(self, matches[0])
                return
        raise KeyError(key)


# --- Dataclass for storing information about an active position ---
@dataclass
class PartialTpOrderInfo:
    # Information about one partial TP order
    target_price: float
    orig_fraction: float  # Initial share of the starting position
    quantity: float  # Actual quantity in the order (after rounding)
    order_id: Optional[Union[str, int]] = None
    client_order_id: Optional[str] = None
    status: str = "PENDING"  # PENDING, VIRTUAL_PENDING, VIRTUAL_TRIGGERING, FILLED, CANCELLED, FAILED
    fill_price: Optional[float] = None
    commission: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_price": self.target_price,
            "orig_fraction": self.orig_fraction,
            "quantity": self.quantity,
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "status": self.status,
            "fill_price": self.fill_price,
            "commission": self.commission,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PartialTpOrderInfo":
        return cls(**data)


@dataclass
class DcaOrderInfo:
    target_price: float
    quantity: float
    order_id: Optional[Union[str, int]] = None
    client_order_id: Optional[str] = None
    status: str = "PENDING"
    fill_price: Optional[float] = None
    commission: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_price": self.target_price,
            "quantity": self.quantity,
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "status": self.status,
            "fill_price": self.fill_price,
            "commission": self.commission,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DcaOrderInfo":
        return cls(**data)


@dataclass
class LivePosition(BasePosition):
    """Extends BasePosition with fields specific to live trading."""

    status: str = "PENDING_ENTRY"  # PENDING_ENTRY, OPEN, CLOSING, CLOSED
    entry_order_id: Optional[Union[str, int]] = None
    current_sl_order_id: Optional[Union[str, int]] = None
    current_sl_client_order_id: Optional[str] = None
    entry_client_order_id: Optional[str] = None
    entry_order_status: str = "PENDING"
    partial_tp_orders: List[PartialTpOrderInfo] = field(default_factory=list)
    dca_orders: List[DcaOrderInfo] = field(default_factory=list)
    execution_events: List[Dict[str, Any]] = field(default_factory=list)
    original_partial_targets_plan: Optional[List[PartialTarget]] = None
    time_status_open: Optional[float] = None
    pnl: Optional[float] = 0.0
    closed_time: Optional[float] = None
    exit_reason: Optional[str] = None
    total_commission: Optional[float] = None
    entry_commission: float = 0.0  # Total entry commission (including DCA entries)
    sl_placement_initiated: bool = False
    is_sl_algo_order: bool = False  # True if SL is placed via Algo Order API
    ptp_placement_initiated_flags: Dict[int, bool] = field(default_factory=dict)
    exit_orders_scheduled_by_process_signal: bool = False
    scale_in_rules: Optional[List[Dict[str, Any]]] = field(default_factory=list)
    conditional_management_rules: Optional[List[Dict[str, Any]]] = field(
        default_factory=list
    )
    entry_atr: Optional[float] = None
    trigger_price: Optional[float] = None
    mode: str = "live"  # Add mode to distinguish between live and paper
    market_type: str = "futures_usdtm"
    entry_fill_processed: bool = False

    # Counter for failed close attempts (for escalation)
    failed_close_attempts: int = 0

    # Maximum floating profit and loss during the trade (for analytics)
    max_floating_profit: Optional[float] = (
        None  # MFP - Maximum floating profit in USD (positive value)
    )
    max_floating_loss: Optional[float] = (
        None  # MFL - Maximum floating loss in USD (positive value representing loss)
    )

    api_key_id: Optional[int] = None  # ID of the API key used for this position

    # Accumulated real PnL from the exchange ('rp' field from Binance Futures WebSocket)
    # Summed across all partial executions (partial TP + final exit)
    accumulated_realized_pnl_from_exchange: float = 0.0

    _is_averaging_down: bool = False

    @property
    def has_partial_tp(self) -> bool:
        return bool(self.partial_tp_orders)

    @property
    def first_partial_tp_filled(self) -> bool:
        return any(tp.status == "FILLED" for tp in self.partial_tp_orders)

    @property
    def id(self) -> Optional[str]:
        if self.entry_client_order_id:
            return self.entry_client_order_id
        if self.entry_order_id:
            return str(self.entry_order_id)
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the position to a dictionary suitable for JSON."""
        data = vars(self).copy()
        # Handle Enums
        if isinstance(data.get("direction"), SignalDirection):
            data["direction"] = data["direction"].value

        # Handle nested dataclasses
        data["partial_tp_orders"] = [tp.to_dict() for tp in self.partial_tp_orders]
        data["dca_orders"] = [dca.to_dict() for dca in getattr(self, "dca_orders", [])]

        if self.original_partial_targets_plan:
            data["original_partial_targets_plan"] = [
                {"price": pt.price, "fraction": pt.fraction}
                for pt in self.original_partial_targets_plan
            ]

        # Handle ptp_placement_initiated_flags (JSON keys must be strings)
        data["ptp_placement_initiated_flags"] = {
            str(k): v for k, v in self.ptp_placement_initiated_flags.items()
        }

        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LivePosition":
        """Restores a position from a dictionary."""
        # Restore Enums
        if "direction" in data and isinstance(data["direction"], str):
            data["direction"] = SignalDirection(data["direction"])

        # Restore nested dataclasses
        if "partial_tp_orders" in data:
            data["partial_tp_orders"] = [
                PartialTpOrderInfo.from_dict(tp) for tp in data["partial_tp_orders"]
            ]

        if "dca_orders" in data:
            data["dca_orders"] = [
                DcaOrderInfo.from_dict(dca) for dca in data["dca_orders"]
            ]
        else:
            data["dca_orders"] = []

        if data.get("original_partial_targets_plan"):
            data["original_partial_targets_plan"] = [
                PartialTarget(price=pt["price"], fraction=pt["fraction"])
                for pt in data["original_partial_targets_plan"]
            ]

        # Restore ptp_placement_initiated_flags (convert keys back to int)
        if "ptp_placement_initiated_flags" in data:
            data["ptp_placement_initiated_flags"] = {
                int(k): v for k, v in data["ptp_placement_initiated_flags"].items()
            }

        # Filter out unexpected keys to prevent __init__ errors
        import inspect

        valid_keys = {k for k in inspect.signature(cls).parameters}
        filtered_data = {k: v for k, v in data.items() if k in valid_keys}

        return cls(**filtered_data)


def calculate_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Calculates the last ATR value for the DataFrame."""
    if df is None or len(df) < period:
        return None
    try:
        # Ensure that columns have the correct type
        df["high"] = pd.to_numeric(df["high"])
        df["low"] = pd.to_numeric(df["low"])
        df["close"] = pd.to_numeric(df["close"])

        # Using pandas_ta for calculation
        atr_series = ta.atr(df["high"], df["low"], df["close"], length=period)
        if atr_series is None or atr_series.empty:
            return None
        # Returning the last non-NaN value
        last_atr = atr_series.dropna().iloc[-1]
        return float(last_atr) if pd.notna(last_atr) else None
    except Exception:
        # logger.error(...) can be added if needed
        return None


class TradingController:
    """
    Central component managing trading logic:
    - Receives data from DataConsumer.
    - Runs strategies to generate signals.
    - Validates signals via RiskManager.
    - Executes orders via Executor.
    - Tracks positions and processes order updates.
    - Logs events via TradeLogger.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        data_consumer: Union[Callable[..., DataConsumer], DataConsumer],
        live_executor: BinanceExecutor,
        paper_executor: PaperTradingExecutor,
        risk_manager: RiskManager,
        user_id: int,
        api_key_id: Optional[int] = None,
        telegram_notifier: Optional[TelegramNotifier] = None,
        get_db: Optional[Callable] = None,
        market_executors: Optional[Dict[str, Any]] = None,
        api_key_name: Optional[str] = None,
    ):
        self.loop = loop if loop else asyncio.get_running_loop()

        self.event_queue = asyncio.Queue(maxsize=1000)
        self._event_handler_semaphore = asyncio.Semaphore(
            int(getattr(config, "MAX_PARALLEL_EVENT_HANDLERS", 64))
        )

        self.paper_executor = paper_executor
        self.executors = {"live": live_executor, "paper": paper_executor}
        self.market_executors: Dict[str, Any] = market_executors or {}

        # Fine-grained locking setup
        self._positions_dict_lock = asyncio.Lock()  # Protects the dict structure
        self._symbol_locks: Dict[
            str, asyncio.Lock
        ] = {}  # Protects individual positions

        # Set a backlink to the controller in the paper executor
        if paper_executor:
            paper_executor.controller = self

        # The old self.executor is now self.executors['live'] for RiskManager and DataConsumer
        live_executor_ref = self.executors["live"]

        # "Smart" initialization
        if isinstance(data_consumer, DataConsumer):
            # If a ready-made object was passed to us, just use it
            self.consumer = data_consumer
            self.consumer.event_queue = self.event_queue  # And setting its queue
            self.consumer.controller = (
                self  # Set a reference to the controller for passing screener data
            )
        elif callable(data_consumer):
            # If a class was passed (it is callable), create the object ourselves
            self.consumer = data_consumer(
                loop=self.loop,
                executor=live_executor_ref,  # DataConsumer uses the live executor for market data
                event_queue=self.event_queue,
                controller=self,  # Pass the controller instance
            )
        else:
            # If something unclear was passed, raise an error
            raise TypeError(
                f"data_consumer must be a DataConsumer class or instance, not {type(data_consumer)}"
            )

        if self.market_executors and hasattr(self.consumer, "set_market_executors"):
            self.consumer.set_market_executors(self.market_executors)

        self.rm = risk_manager
        self.user_id = user_id
        self.api_key_id = api_key_id
        self.telegram_notifier = telegram_notifier
        self.api_key_name = api_key_name
        self.user_telegram_chat_id: Optional[str] = None  # Per-user Telegram chat ID

        self.get_db_session = get_db if get_db is not None else _default_get_db
        logger.info("TradingController initialized with DB session factory.")

        # Pass notifier and loop to risk_manager IMMEDIATELY
        if self.rm:
            self.rm.telegram_notifier = self.telegram_notifier
            self.rm.loop_from_controller = self.loop
            self.rm.user_telegram_chat_id = (
                None  # Will be set when user config is loaded
            )

        self.trade_logger = TradeLogger(max_queue_size=config.SIGNAL_QUEUE_MAX_SIZE)
        self.realtime_ml_logger: Optional[RealtimeMLLogger] = None  # If used
        if getattr(config, "LOG_REALTIME_ML_DATA", False):  # If used
            self.realtime_ml_logger = RealtimeMLLogger(
                log_file_path=getattr(config, "LOG_FILE_REALTIME_ML", None),
                max_queue_size=config.SIGNAL_QUEUE_MAX_SIZE,
            )

        # Initializing Redis client for Controller
        try:
            self.redis_client = redis.Redis(
                host=config.REDIS_HOST,
                port=config.REDIS_PORT,
                db=config.REDIS_DB,
                username=config.REDIS_USERNAME,
                password=config.REDIS_PASSWORD,
                decode_responses=True,
            )
            self.redis_key_positions = "depthsight:state:positions"  # Key for positions
            self.redis_key_strategies = (
                config.REDIS_STATE_KEY_STRATEGIES
            )  # Key for strategies
            self.redis_key_runtime_state = f"depthsight:controller:runtime_state:{self.user_id}"  # Key for full state
            logger.info(
                "TradingController initialized Redis client for state publishing."
            )
        except Exception as e:
            logger.error(f"Failed to initialize Redis client in TradingController: {e}")
            self.redis_client = None

        self._running = False
        self._main_task: Optional[asyncio.Task] = None
        self._config_reload_task: Optional[asyncio.Task] = None
        self._config_reload_interval = 60  # Seconds
        self._market_info_update_interval = 3600  # Seconds
        self._market_info_update_task: Optional[asyncio.Task] = None
        self._dynamic_symbol_selection_task: Optional[asyncio.Task] = (
            None  # New task for dynamic symbol selection
        )
        self._equity_recording_task: Optional[asyncio.Task] = (
            None  # Task for periodic equity recording
        )
        self._equity_recording_interval = 300  # 5 minutes

        # **Key change:** Changing the strategy storage structure.
        # Old structure: self._active_strategies: Dict[str, List[BaseStrategy]] # symbol -> [instances]
        # New structure:
        self.running_strategy_instances: Dict[
            str, Tuple[BaseStrategy, dict]
        ] = {}  # config_id -> (instance, full_config_dict)
        self.instances_lock = asyncio.Lock()  # Lock to protect the new dictionary

        # Adding a task to listen for commands from Redis
        self._redis_listener_task: Optional[asyncio.Task] = None
        # HFT event listener
        self._redis_hft_listener_task: Optional[asyncio.Task] = None

        # States
        self._monitored_symbols: Set[str] = (
            set()
        )  # Symbols for which strategies are running
        self._closing_managed_symbols: Set[str] = (
            set()
        )  # Symbols with open positions that have left monitoring
        self._last_known_symbols_from_consumer: Set[str] = set()  # To track changes
        self._active_strategies: Dict[str, List[BaseStrategy]] = defaultdict(
            list
        )  # symbol -> [strategy_instance]
        self._active_positions: ActivePositionMap = (
            ActivePositionMap()
        )  # market_type:symbol -> Position

        self._recent_signals: Dict[
            Tuple[str, str, str, SignalDirection], float
        ] = {}  # (market, symbol, strategy_name, direction) -> time
        self._signal_throttle_period: float = 10.0  # Seconds (can be moved to config)

        # attributes for dynamic symbol selection
        self.symbol_selection_config: SymbolSelectionConfig = (
            SymbolSelectionConfig()
        )  # Default config
        self.full_screener_list: List[
            Dict[str, Any]
        ] = []  # Stores the full unfiltered list from screener
        self.currently_managed_symbols: Set[str] = (
            set()
        )  # Symbols currently being managed by the dynamic selection
        self._screener_update_queue = asyncio.Queue(
            maxsize=1
        )  # Queue for screener updates

        # Market information cache (filters, precision)
        self._market_info_cache: Dict[str, Dict[str, Any]] = {}
        self._market_info_lock = asyncio.Lock()

        self._last_position_close_time_per_symbol: Dict[
            str, float
        ] = {}  # market_type:symbol -> close time
        self._symbol_cooldown_duration: float = config.get_strategy_param(
            "TradingController",
            "symbol_cooldown_seconds",
            default=getattr(config, "SYMBOL_COOLDOWN_SECONDS", 300.0),
        )
        self._processing_signal_for_symbol: Set[str] = set()
        self._processing_lock = (
            asyncio.Lock()
        )  # General lock for critical sections, if needed. Not actively used yet.
        self._processing_signal_lock = (
            asyncio.Lock()
        )  # Lock to protect _processing_signal_for_symbol

        self._ml_confirmation_pipeline_live: Optional[ModelPipeline] = None
        self._ml_confirmation_feature_extractor_live: Optional[FeatureExtractor] = None
        self._ml_confirmation_enabled_live_runtime: bool = False

        self._last_missing_sl_check_time: float = 0.0
        self.sl_placement_grace_period: float = (
            config.CONTROLLER_SL_PLACEMENT_GRACE_PERIOD_SECONDS
        )
        self.missing_sl_check_interval: float = (
            config.CONTROLLER_MISSING_SL_CHECK_INTERVAL_SECONDS
        )

        logger.info("TradingController initialized.")
        if self.telegram_notifier:
            logger.info("TelegramNotifier instance received by TradingController.")
        else:
            logger.info(
                "TelegramNotifier not provided to TradingController (notifications may be disabled)."
            )
        logger.info(
            f"Symbol cooldown after close: {self._symbol_cooldown_duration} seconds."
        )

    def _position_uses_no_stop_loss_mode(
        self, position: Optional[LivePosition]
    ) -> bool:
        if position is None:
            return False
        signal_details = (
            position.signal_details if isinstance(position.signal_details, dict) else {}
        )
        return bool(
            getattr(position, "no_stop_loss", False)
            or signal_details.get("no_stop_loss") is True
        )

    def _position_has_active_stop_target(
        self, position: Optional[LivePosition]
    ) -> bool:
        if position is None:
            return False
        sl_price = getattr(position, "current_sl_price", None)
        return sl_price is not None and sl_price > 0

    def _position_is_intentional_no_sl_mode(
        self, position: Optional[LivePosition]
    ) -> bool:
        return self._position_uses_no_stop_loss_mode(
            position
        ) and not self._position_has_active_stop_target(position)

    @staticmethod
    def _executor_is_spot(executor: Any) -> bool:
        return "spot" in str(getattr(executor, "market_type", "")).lower()

    @staticmethod
    def _normalize_market_type(raw_market_type: Optional[Any]) -> str:
        return _normalize_position_market_type(raw_market_type)

    def _position_key(self, symbol: str, market_type: Optional[Any]) -> str:
        return ActivePositionMap.key_for_symbol(symbol, market_type)

    def _position_key_for_position(self, position: LivePosition) -> str:
        return ActivePositionMap.key_for_position(position)

    def _get_lock_for_position(
        self, symbol: str, market_type: Optional[Any] = None
    ) -> asyncio.Lock:
        """Returns (or creates) a per-symbol lock. Thread-safe in asyncio (single-threaded)."""
        key = self._position_key(symbol, market_type)
        if key not in self._symbol_locks:
            self._symbol_locks[key] = asyncio.Lock()
        return self._symbol_locks[key]

    async def _cleanup_symbol_lock(
        self, symbol: str, market_type: Optional[Any] = None
    ):
        """Cleans up a per-symbol lock if it's no longer being used."""
        key = self._position_key(symbol, market_type)
        lock = self._symbol_locks.get(key)
        if lock and not lock.locked():
            del self._symbol_locks[key]

    def _active_position_get(
        self, symbol: str, market_type: Optional[Any] = None
    ) -> Optional[LivePosition]:
        # NOTE: Dictionary read is safe in asyncio, but writing should be under _positions_dict_lock
        return self._active_positions.get_by_symbol(symbol, market_type)

    def _active_position_set(self, position: LivePosition) -> str:
        key = self._position_key_for_position(position)
        self._active_positions[key] = position
        return key

    def _active_position_pop(
        self, symbol: str, market_type: Optional[Any] = None
    ) -> Optional[LivePosition]:
        popped = self._active_positions.pop_by_symbol(symbol, market_type)
        if popped:
            # We schedule the cleanup to run soon (without blocking), so if anything
            # currently holds the lock, it won't crash, and it will be deleted after release.
            self.loop.create_task(self._cleanup_symbol_lock(symbol, market_type))
        return popped

    def _active_positions_for_symbol(self, symbol: str) -> List[LivePosition]:
        symbol_upper = str(symbol).upper()
        return [
            pos
            for pos in self._active_positions.values()
            if str(getattr(pos, "symbol", "")).upper() == symbol_upper
        ]

    def _coerce_active_position_map(
        self, positions: Optional[Dict[Any, LivePosition]]
    ) -> ActivePositionMap:
        coerced = ActivePositionMap()
        for key, pos in (positions or {}).items():
            if pos is None:
                continue
            if not getattr(pos, "market_type", None):
                pos.market_type = self._market_type_for_position(pos)
            coerced[key] = pos
        return coerced

    def _market_type_for_strategy_config(
        self, config_dict: Optional[Dict[str, Any]]
    ) -> str:
        config_dict = config_dict or {}
        config_data = (
            config_dict.get("config_data") if isinstance(config_dict, dict) else {}
        )
        if not isinstance(config_data, dict):
            config_data = {}
        return self._normalize_market_type(
            config_data.get("marketType")
            or config_data.get("market_type")
            or config_dict.get("market_type")
            or config_dict.get("marketType")
        )

    def _companion_market_type(self, market_type: Optional[str]) -> Optional[str]:
        normalized = self._normalize_market_type(market_type)
        if (
            normalized == "futures_usdtm"
            and config.ANALYZE_SPOT_ORDERBOOK_FOR_FUTURES_TRADES
        ):
            return "spot"
        if normalized == "spot" and config.ANALYZE_FUTURES_ORDERBOOK_FOR_SPOT_TRADES:
            return "futures_usdtm"
        return None

    def _executor_for_market_type(
        self, market_type: Optional[str], mode: str = "live"
    ) -> Optional[Any]:
        if mode == "paper":
            return self.executors.get("paper")
        normalized = self._normalize_market_type(market_type)
        if normalized in self.market_executors:
            return self.market_executors.get(normalized)
        live_executor = self.executors.get("live")
        if (
            self._normalize_market_type(getattr(live_executor, "market_type", None))
            == normalized
        ):
            return live_executor
        return None

    def _market_type_for_position(self, position: Optional[LivePosition]) -> str:
        direct_market_type = (
            getattr(position, "market_type", None) if position else None
        )
        if direct_market_type:
            return self._normalize_market_type(direct_market_type)
        signal_details = (
            position.signal_details
            if position and isinstance(position.signal_details, dict)
            else {}
        )
        for key in ("market_type", "marketType", "market"):
            if signal_details.get(key):
                return self._normalize_market_type(signal_details[key])
        executor = (
            self.executors.get(getattr(position, "mode", "live")) if position else None
        )
        return self._normalize_market_type(
            getattr(executor, "market_type", None) or config.TRADING_MARKET_TYPE
        )

    def _leverage_for_position(self, position: Optional[LivePosition]) -> Optional[Any]:
        signal_details = (
            position.signal_details
            if position and isinstance(position.signal_details, dict)
            else {}
        )
        for key in ("leverage", "leverage_x", "leverageX", "leverage_multiplier"):
            if signal_details.get(key) is not None:
                return signal_details[key]
        for attr in ("leverage", "leverage_x"):
            value = getattr(position, attr, None) if position else None
            if value is not None:
                return value
        return None

    def _position_should_use_virtual_spot_tps(
        self, position: Optional[LivePosition], executor: Any
    ) -> bool:
        return (
            position is not None
            and self._executor_is_spot(executor)
            and self._position_has_active_stop_target(position)
            and not self._position_is_intentional_no_sl_mode(position)
        )

    def _position_has_exchange_spot_sl_lock(
        self, position: Optional[LivePosition], executor: Any
    ) -> bool:
        return self._position_should_use_virtual_spot_tps(position, executor) and (
            getattr(position, "current_sl_order_id", None) is not None
            or bool(getattr(position, "sl_placement_initiated", False))
        )

    @staticmethod
    def _tp_is_virtual_pending(tp: PartialTpOrderInfo) -> bool:
        return tp.status in {"VIRTUAL_PENDING", "PENDING_PLACEMENT"} and not tp.order_id

    @staticmethod
    def _is_exit_target_valid(
        target_price: Optional[float],
        entry_price: Optional[float],
        sl_price: Optional[float],
        direction: SignalDirection,
    ) -> bool:
        if target_price is None or entry_price is None or entry_price <= 0:
            return False
        if direction == SignalDirection.LONG:
            if target_price <= entry_price:
                return False
            return sl_price is None or target_price > sl_price
        if direction == SignalDirection.SHORT:
            if target_price >= entry_price:
                return False
            return sl_price is None or target_price < sl_price
        return False

    async def load_symbol_selection_config(self) -> bool:
        """
        Loads the user's symbol selection configuration from the API.
        Returns True if the configuration has changed, False otherwise.
        """
        log_prefix = "[LoadSymbolSelectionConfig]"
        try:
            async for db in self.get_db_session():
                user_config_data = await crud.get_user_symbol_selection_config(
                    db, self.user_id
                )

                new_config = SymbolSelectionConfig()  # Default
                if user_config_data:
                    new_config = SymbolSelectionConfig.model_validate(user_config_data)
                    # logger.debug(f"{log_prefix} Loaded config for user {self.user_id}: {new_config.model_dump_json()}")
                else:
                    logger.info(
                        f"{log_prefix} No custom symbol selection config found for user {self.user_id}. Using default."
                    )

                if new_config != self.symbol_selection_config:
                    logger.info(
                        f"{log_prefix} Configuration changed! Old Mode: {self.symbol_selection_config.mode}, New Mode: {new_config.mode}"
                    )
                    self.symbol_selection_config = new_config
                    return True

                return False

        except Exception as e:
            logger.error(
                f"{log_prefix} Failed to load symbol selection config for user {self.user_id}: {e}",
                exc_info=True,
            )
            # Fallback to default on error, but only if we don't have one yet
            if not self.symbol_selection_config:
                self.symbol_selection_config = SymbolSelectionConfig()
            return False

    def _queue_current_screener_snapshot(self) -> bool:
        """Reuses the latest screener snapshot to re-apply dynamic symbol limits immediately."""
        if not self.full_screener_list or self._screener_update_queue.full():
            return False
        try:
            self._screener_update_queue.put_nowait(
                {"data": list(self.full_screener_list)}
            )
            return True
        except asyncio.QueueFull:
            return False

    async def _apply_symbol_selection_config_change(self, config_changed: bool) -> None:
        if not config_changed:
            return

        log_prefix = "[ApplySymbolSelectionConfig]"
        logger.info(
            f"{log_prefix} Applying symbol selection config immediately for user_id={self.user_id}."
        )

        if self.symbol_selection_config.mode in ("DYNAMIC_NATR", "DYNAMIC_ORACLE"):
            if self._queue_current_screener_snapshot():
                logger.info(
                    f"{log_prefix} Current screener snapshot queued for immediate re-filtering."
                )
            else:
                self.currently_managed_symbols.clear()
                await self._check_and_update_symbols()
            return

        self.currently_managed_symbols.clear()
        await self._check_and_update_symbols()

    async def _reload_runtime_settings(self) -> None:
        await self.reload_user_app_config()
        config_changed = await self.load_symbol_selection_config()
        await self._apply_symbol_selection_config_change(config_changed)

    @staticmethod
    def _config_section_to_dict(section: Any) -> Dict[str, Any]:
        if section is None:
            return {}
        if isinstance(section, dict):
            return dict(section)
        if hasattr(section, "model_dump"):
            try:
                return section.model_dump(mode="json", by_alias=True)
            except TypeError:
                return section.model_dump(by_alias=True)
        if hasattr(section, "dict"):
            return section.dict()
        if isinstance(section, str):
            try:
                return json.loads(section)
            except json.JSONDecodeError:
                return {}
        return {}

    async def start(self):
        if self._running:
            logger.warning("TradingController is already running.")
            return
        self._running = True

        logger.info(
            f"Controller for user_id={self.user_id} starting. Loading user-specific configuration..."
        )
        try:
            async for db in self.get_db_session():
                app_config = await crud.get_config(db, user_id=self.user_id)
                if app_config and self.rm:
                    logger.info("Applying user-specific runtime settings.")
                    runtime_settings = {
                        "risk_management": self._config_section_to_dict(
                            app_config.risk_management
                        ),
                        "backtest_risk_management": self._config_section_to_dict(
                            app_config.backtest_risk_management
                        ),
                        "notifications": self._config_section_to_dict(
                            app_config.notifications
                        ),
                    }
                    self.rm.apply_user_settings(runtime_settings)
                    self.user_telegram_chat_id = self.rm.user_telegram_chat_id
                    logger.info(
                        f"RiskManager configured for user {self.user_id}: Max Concurrent Trades = {self.rm.max_concurrent_trades}"
                    )
                    if self.user_telegram_chat_id:
                        logger.info(
                            f"Loaded per-user Telegram Chat ID for user {self.user_id}: {self.user_telegram_chat_id[:8]}..."
                        )
                    else:
                        logger.info(
                            f"No per-user Telegram Chat ID configured for user {self.user_id}. Using global config."
                        )

                    # Update RiskManager attributes using .get() for the dictionary

                elif not (app_config and self.rm):
                    logger.warning(
                        f"Could not load AppConfig or Risk Management settings for user_id={self.user_id}. Using defaults."
                    )
        except Exception as e:
            logger.error(
                f"Failed to load user configuration on startup: {e}", exc_info=True
            )

        logger.info("Starting TradingController...")

        # Load initial symbol selection config
        await self.load_symbol_selection_config()

        await self._load_runtime_state()

        # Synchronization with the exchange (picking up "lost" positions and removing closed ones)
        await self._reconcile_positions_with_exchange()

        if self.realtime_ml_logger:
            self.realtime_ml_logger.start()

        self.trade_logger.start()
        await self.rm.initialize_balance()
        await self.consumer.start()
        executors_for_stream = [
            self.executors.get("live"),
            *self.market_executors.values(),
        ]
        started_executor_ids = set()
        for stream_executor in executors_for_stream:
            if stream_executor is None:
                continue
            executor_identity = id(stream_executor)
            if executor_identity in started_executor_ids:
                continue
            started_executor_ids.add(executor_identity)
            if hasattr(stream_executor, "start_user_data_stream"):
                await stream_executor.start_user_data_stream(self._handle_order_update)

        self._redis_listener_task = self.loop.create_task(
            self._redis_command_listener(), name="RedisCommandListener"
        )
        # Starting HFT event listener
        self._redis_hft_listener_task = self.loop.create_task(
            self._redis_hft_event_listener(), name="RedisHftEventListener"
        )

        await self._update_market_info_cache()
        self._market_info_update_task = self.loop.create_task(
            self._run_market_info_updater(), name="MarketInfoUpdater"
        )

        self._main_task = self.loop.create_task(
            self._run_main_loop(), name="ControllerMainLoop"
        )
        self._config_reload_task = self.loop.create_task(
            self._run_config_reloader(), name="ConfigReloader"
        )

        # Start the dynamic symbol selection loop
        self._dynamic_symbol_selection_task = self.loop.create_task(
            self._dynamic_symbol_selection_loop(), name="DynamicSymbolSelectionLoop"
        )

        # Start the periodic equity recording loop for paper mode dashboard
        self._equity_recording_task = self.loop.create_task(
            self._run_equity_recorder(), name="EquityRecorder"
        )

        # Initialize Phantom Trade Tracker for BE analysis
        # Phantom trades are created in _handle_final_exit when STOP_LOSS_BE occurs
        # Updates happen in _manage_symbol when new klines are received (lazy - only for symbols with active phantoms)
        if config.PHANTOM_TRACKING_ENABLED and config.PHANTOM_TRACKING_MODE in (
            "live",
            "all",
        ):
            get_phantom_tracker()
            logger.info(
                f"PhantomTracker initialized for LIVE BE analysis. Mode: {config.PHANTOM_TRACKING_MODE}"
            )

        logger.debug("Waiting briefly for initial symbol list...")
        await asyncio.sleep(0.5)
        logger.debug("Initial wait finished, checking symbols...")
        await self._check_and_update_symbols()

        if config.ML_CONFIRMATION_ENABLED:
            logger.info(
                "[MLConfirmLive] Live ML Confirmation is ENABLED in config. Initializing components..."
            )
            try:
                self._ml_confirmation_feature_extractor_live = FeatureExtractor()
                logger.info(
                    "[MLConfirmLive] Initialized FeatureExtractor for live ML confirmation."
                )

                conf_model_path_str_live = getattr(
                    config, "ML_CONFIRMATION_MODEL_PATH", None
                )
                if conf_model_path_str_live:
                    conf_model_path_live = Path(conf_model_path_str_live)
                    # Pass the path for lazy or immediate loading, depending on the ModelPipeline implementation
                    self._ml_confirmation_pipeline_live = ModelPipeline(
                        model_path=conf_model_path_live
                    )
                    if self._ml_confirmation_pipeline_live.load_model(
                        conf_model_path_live
                    ):  # Explicitly loading
                        logger.info(
                            f"[MLConfirmLive] Live ML Confirmation model loaded successfully from: {conf_model_path_live}"
                        )
                        if (
                            self._ml_confirmation_feature_extractor_live
                            and self._ml_confirmation_pipeline_live.active_features
                        ):
                            self._ml_confirmation_feature_extractor_live.set_active_features(
                                self._ml_confirmation_pipeline_live.active_features
                            )
                            logger.info(
                                f"[MLConfirmLive] Active features set for FE: {len(self._ml_confirmation_pipeline_live.active_features)}"
                            )
                            self._ml_confirmation_enabled_live_runtime = (
                                True  # Successful initialization
                            )

                            # Logging information about the need for aggTrade
                            aggtrade_features_needed = [
                                f
                                for f in self._ml_confirmation_feature_extractor_live.aggtrade_feature_configs.keys()
                                if f
                                in self._ml_confirmation_pipeline_live.active_features
                            ]
                            if aggtrade_features_needed:
                                logger.info(
                                    f"[MLConfirmLive] ML model uses aggTrade features: {aggtrade_features_needed}. "
                                    f"aggTrade subscription will be automatically enabled for strategies with use_ml_confirmation=True"
                                )
                            else:
                                logger.info(
                                    "[MLConfirmLive] ML model does not require aggTrade features."
                                )
                        else:
                            logger.error(
                                "[MLConfirmLive] Failed to set active features for FE or pipeline has no active features. Live ML Confirmation will be SKIPPED."
                            )
                    else:
                        logger.error(
                            f"[MLConfirmLive] Failed to load Live ML Confirmation model from {conf_model_path_live}. Live ML Confirmation will be SKIPPED."
                        )
                else:
                    logger.error(
                        "[MLConfirmLive] ML_CONFIRMATION_MODEL_PATH not configured. Live ML Confirmation will be SKIPPED."
                    )
            except Exception as e_conf_init_live:
                logger.error(
                    f"[MLConfirmLive] Error initializing live ML confirmation components: {e_conf_init_live}. Live ML Confirmation DISABLED.",
                    exc_info=True,
                )
                self._ml_confirmation_enabled_live_runtime = False
        else:
            logger.info("[MLConfirmLive] Live ML Confirmation is DISABLED in config.")
            self._ml_confirmation_enabled_live_runtime = False

        logger.info("TradingController started successfully.")

    async def stop(self):
        """Stops the controller and all its components."""
        if not self._running:
            logger.info("TradingController is not running.")
            return
        logger.info("Stopping TradingController...")
        self._running = False

        if self.realtime_ml_logger and self.realtime_ml_logger._running:
            logger.debug("Stopping RealtimeMLLogger...")
            self.realtime_ml_logger.stop()

        tasks_to_cancel = [
            self._main_task,
            self._config_reload_task,
            self._market_info_update_task,
            self._redis_listener_task,
            self._redis_hft_listener_task,  # Add HFT listener
            self._dynamic_symbol_selection_task,  # Add the new task here
            self._equity_recording_task,  # Equity recording task
        ]
        logger.info(f"Attempting to cancel {len(tasks_to_cancel)} background tasks...")
        for task in tasks_to_cancel:
            if task and not task.done():
                task_name = task.get_name()
                logger.debug(f"Cancelling task: {task_name}")
                task.cancel()
                await asyncio.sleep(0)

        valid_tasks = [t for t in tasks_to_cancel if t is not None]
        if valid_tasks:
            logger.info(
                f"Waiting for {len(valid_tasks)} tasks to finish cancellation..."
            )
            try:
                await asyncio.wait_for(
                    asyncio.gather(*valid_tasks, return_exceptions=True), timeout=5.0
                )
                logger.info("Controller tasks finished cancellation process.")
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for controller tasks to cancel.")
                for task in valid_tasks:
                    if not task.done():
                        logger.warning(
                            f"  Task still pending after timeout: {task.get_name()}"
                        )
            except Exception as e:
                logger.error(f"Error waiting for task cancellation: {e}", exc_info=True)
        else:
            logger.debug("No valid controller tasks to wait for cancellation.")

        self._main_task = None
        self._config_reload_task = None
        self._market_info_update_task = None
        self._dynamic_symbol_selection_task = None  # Clear the reference
        self._equity_recording_task = None  # Clear the reference
        logger.debug("Controller task references cleared.")

        logger.info("Stopping dependent components...")
        logger.debug("Clearing DataConsumer subscriptions...")
        await self.consumer.clear_all_subscriptions()
        logger.debug("Stopping Executor User Data Stream...")
        live_executor = self.executors.get("live")
        executors_for_stream_stop = [live_executor, *self.market_executors.values()]
        stopped_executor_ids = set()
        for stream_executor in executors_for_stream_stop:
            if stream_executor is None:
                continue
            executor_identity = id(stream_executor)
            if executor_identity in stopped_executor_ids:
                continue
            stopped_executor_ids.add(executor_identity)
            if hasattr(stream_executor, "stop_user_data_stream"):
                await stream_executor.stop_user_data_stream()
        logger.debug("Stopping DataConsumer...")
        await self.consumer.stop()
        executors_to_close = []
        if live_executor is not None:
            executors_to_close.append(live_executor)
        executors_to_close.extend(self.market_executors.values())
        closed_executor_ids = set()
        for executor_to_close in executors_to_close:
            if executor_to_close is None:
                continue
            executor_identity = id(executor_to_close)
            if executor_identity in closed_executor_ids:
                continue
            closed_executor_ids.add(executor_identity)
            close_method = getattr(executor_to_close, "close", None)
            if callable(close_method):
                try:
                    await close_method()
                except Exception as exc:
                    logger.error(
                        "Error closing executor during controller stop: %s",
                        exc,
                        exc_info=True,
                    )
        logger.debug("Stopping TradeLogger...")
        if hasattr(self, "trade_logger") and self.trade_logger._running:
            self.trade_logger.stop()
        logger.debug("Dependent components stopped.")

        # Saving state before closing Redis
        await self._save_runtime_state()

        if self.redis_client:
            try:
                logger.info("Closing Redis client...")
                await self.redis_client.close()
                logger.info("Redis client closed. Disconnecting connection pool...")
                await self.redis_client.connection_pool.disconnect()
                logger.info("Redis connection pool disconnected.")
            except Exception as e:
                logger.error(f"Error closing Redis client: {e}", exc_info=True)

        logger.info("TradingController stopped.")

    async def _redis_command_listener(self):
        """Listens to the command channel in Redis and processes incoming commands."""
        from bot_module.redis_handler import user_id_context

        if not self.redis_client:
            logger.error(
                "Redis client is not initialized. Command listener cannot start."
            )
            return

        logger.info(
            f"Starting Redis command listener on channel: '{config.REDIS_COMMAND_CHANNEL}'"
        )
        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe(config.REDIS_COMMAND_CHANNEL)

        while self._running:
            try:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message["type"] == "message":
                    token = user_id_context.set(self.user_id)
                    try:
                        command_data = json.loads(message["data"])
                        command_type = command_data.get("command")
                        payload = command_data.get("payload")

                        logger.info(f"Received command '{command_type}' via Redis.")

                        if command_type == "START_STRATEGY":
                            await self._handle_start_strategy_command(payload)
                        elif command_type == "STOP_STRATEGY":
                            await self._handle_stop_strategy_command(payload)
                        elif command_type == "TV_WEBHOOK_SIGNAL":
                            await self._handle_tv_webhook_signal_command(payload)

                        # Adding a handler for the new command
                        elif command_type == "CLOSE_POSITION":
                            user_id_from_cmd = payload.get("user_id")
                            if str(user_id_from_cmd) != str(self.user_id):
                                continue

                            cmd_api_key_id = payload.get("api_key_id")
                            if (
                                cmd_api_key_id is not None
                                and self.api_key_id is not None
                                and int(cmd_api_key_id) != self.api_key_id
                            ):
                                continue

                            symbol_to_close = payload.get("symbol")
                            market_type_to_close = payload.get(
                                "market_type"
                            ) or payload.get("marketType")

                            if not symbol_to_close or user_id_from_cmd is None:
                                logger.error(
                                    f"Invalid CLOSE_POSITION payload: {payload}"
                                )
                                continue

                            # Important check: ensure the position belongs to the user
                            symbol_lock = self._get_lock_for_position(
                                symbol_to_close, market_type_to_close
                            )
                            async with symbol_lock:
                                position = self._active_position_get(
                                    symbol_to_close, market_type_to_close
                                )
                                if not position:
                                    logger.warning(
                                        f"Received CLOSE_POSITION for {symbol_to_close}, but no active position found."
                                    )
                                    continue

                                if str(position.user_id) != str(user_id_from_cmd):
                                    logger.error(
                                        f"SECURITY: User {user_id_from_cmd} attempted to close position for {symbol_to_close} owned by user {position.user_id}. Denied."
                                    )
                                    continue

                            # If all checks pass, initiate closure
                            logger.info(
                                f"Processing CLOSE_POSITION command for {symbol_to_close} from user {user_id_from_cmd}."
                            )
                            self.loop.create_task(
                                self.close_position(
                                    symbol_to_close,
                                    reason="MANUAL_CLOSE_API",
                                    market_type=market_type_to_close,
                                ),
                                name=f"ManualCloseAPI_{symbol_to_close}",
                            )

                        elif command_type == "UPDATE_SL_TP":
                            # Updating SL/TP via Redis command
                            pos_id = payload.get("position_id")
                            user_id_from_cmd = payload.get("user_id")
                            new_sl = payload.get("new_stop_loss")
                            new_tp = payload.get("new_take_profit")

                            logger.info(
                                f"Handling UPDATE_SL_TP for pos_id: {pos_id} -> SL:{new_sl}, TP:{new_tp}"
                            )

                            # Checking that the command is for this user
                            if str(user_id_from_cmd) != str(self.user_id):
                                logger.debug(
                                    f"UPDATE_SL_TP command for user {user_id_from_cmd}, skipping (we are user {self.user_id})."
                                )
                                continue

                            # Finding position by ID
                            target_position: Optional[LivePosition] = None
                            target_symbol: Optional[str] = None
                            target_market_type: Optional[str] = None

                            async with self._positions_dict_lock:
                                for (
                                    _position_key,
                                    pos,
                                ) in self._active_positions.items():
                                    if pos.id == pos_id:
                                        target_position = pos
                                        target_symbol = pos.symbol
                                        target_market_type = (
                                            self._market_type_for_position(pos)
                                        )
                                        break

                            if not target_position or not target_symbol:
                                logger.warning(
                                    f"UPDATE_SL_TP: Position with ID {pos_id} not found in active positions."
                                )
                                continue

                            # Checking the position owner
                            if str(target_position.user_id) != str(self.user_id):
                                logger.error(
                                    f"SECURITY: User {self.user_id} tried to update SL/TP for position {pos_id} owned by user {target_position.user_id}. Denied."
                                )
                                continue

                            # Updating Stop Loss
                            if new_sl is not None:
                                logger.info(
                                    f"UPDATE_SL_TP: Updating SL for {target_symbol} to {new_sl}"
                                )
                                self.loop.create_task(
                                    self._replace_stop_loss(
                                        target_symbol,
                                        float(new_sl),
                                        market_type=target_market_type,
                                    ),
                                    name=f"UpdateSL_API_{target_symbol}",
                                )

                            # Updating Take Profit
                            if new_tp is not None:
                                logger.info(
                                    f"UPDATE_SL_TP: Updating TP for {target_symbol} to {new_tp}"
                                )
                                self.loop.create_task(
                                    self._replace_take_profit(
                                        target_symbol,
                                        float(new_tp),
                                        market_type=target_market_type,
                                    ),
                                    name=f"UpdateTP_API_{target_symbol}",
                                )

                            logger.info(f"UPDATE_SL_TP completed for position {pos_id}")

                        elif command_type == "EMERGENCY_STOP":
                            user_id = payload.get("user_id")
                            if str(user_id) != str(self.user_id):
                                continue
                            logger.info(
                                f"Handling EMERGENCY_STOP for user_id: {user_id}"
                            )
                            # await self.executor.close_all_user_positions(user_id=user_id)

                        elif command_type == "TEST_NOTIFICATION":
                            user_id = payload.get("user_id")
                            chat_id = payload.get("chat_id")
                            if str(user_id) != str(self.user_id):
                                continue
                            logger.info(
                                f"Handling TEST_NOTIFICATION for user_id: {user_id}, chat_id: {chat_id}"
                            )
                            if self.telegram_notifier:
                                self.loop.create_task(
                                    self.telegram_notifier.send_test_message(
                                        chat_id=chat_id
                                    ),
                                    name=f"TestNotify_{user_id}",
                                )
                            else:
                                logger.warning(
                                    "TelegramNotifier not available for TEST_NOTIFICATION."
                                )

                        # Instant configuration reload
                        elif command_type == "RELOAD_CONFIG":
                            user_id = payload.get("user_id")
                            if str(user_id) != str(self.user_id):
                                continue  # Command for another user
                            logger.info(
                                f"Handling RELOAD_CONFIG for user_id: {user_id} - Applying settings immediately."
                            )
                            # Instantly reload settings without waiting for the 60-second interval
                            self.loop.create_task(
                                self._reload_runtime_settings(),
                                name=f"ImmediateConfigReload_{user_id}",
                            )
                    finally:
                        user_id_context.reset(token)

            except asyncio.CancelledError:
                logger.info("Redis command listener task cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in Redis command listener: {e}", exc_info=True)
                await asyncio.sleep(5)  # Pause before retry

        await pubsub.unsubscribe(config.REDIS_COMMAND_CHANNEL)
        logger.info("Redis command listener stopped.")

    async def _redis_hft_event_listener(self):
        """Listens to the HFT event channel in Redis and sends notifications to Telegram."""
        if not self.redis_client:
            logger.error(
                "[HFT-Listener] Redis client not initialized. HFT event listener cannot start."
            )
            return

        if not self.telegram_notifier:
            logger.warning(
                "[HFT-Listener] Telegram notifier not available. HFT event listener will not start."
            )
            return

        hft_events_channel = "hft:events"
        logger.info(
            f"[HFT-Listener] ✅ STARTING listener on channel: '{hft_events_channel}' (user_id={self.user_id})"
        )

        # Create a new connection or pubsub object, separate from the command one, to avoid conflicts
        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe(hft_events_channel)
        logger.info(
            f"[HFT-Listener] ✅ Successfully subscribed to '{hft_events_channel}'"
        )

        while self._running:
            try:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message["type"] == "message":
                    try:
                        payload = json.loads(message["data"])
                        event_type = payload.get("type")

                        # DEBUG: Log all events received
                        logger.debug(
                            f"[HFT] Received event type='{event_type}' from Redis: {list(payload.keys())}"
                        )

                        # Mapping events Rust -> Python methods
                        # Rust event types: bot_started, bot_stopped, signal, trade, error

                        if event_type:
                            # Check if the event belongs to this user if user_id is present
                            event_user_id = payload.get("user_id")
                            # Allowing events:
                            #  - without user_id (None)
                            #  - with user_id=0 (autobots from screener)
                            #  - with user_id equal to ours
                            if (
                                event_user_id is not None
                                and event_user_id != 0
                                and int(event_user_id) != int(self.user_id)
                            ):
                                logger.debug(
                                    f"[HFT] Skipping event for user {event_user_id} (we are {self.user_id})"
                                )
                                continue  # Ignore events for other users

                            # === SPECIAL HANDLING for trade event (ENTRY) ===
                            # When Rust HFT bot opens a new position, we need to "adopt" it
                            # so that subsequent sl_placed events can be processed.
                            if event_type == "trade":
                                symbol_tr = payload.get("symbol")
                                market_type_tr = self._normalize_market_type(
                                    payload.get("market_type")
                                    or payload.get("marketType")
                                )
                                side_tr = payload.get("side")  # "BUY" or "SELL"
                                price_tr = payload.get("price")
                                qty_tr = payload.get("qty")
                                realized_pnl = payload.get("realized_pnl")
                                bot_id_tr = payload.get("bot_id", "unknown")

                                # Only process entry trades (no realized_pnl = entry)
                                if (
                                    symbol_tr
                                    and side_tr
                                    and price_tr
                                    and realized_pnl is None
                                ):
                                    symbol_lock_tr = self._get_lock_for_position(
                                        symbol_tr, market_type_tr
                                    )
                                    async with symbol_lock_tr:
                                        existing_pos = self._active_position_get(
                                            symbol_tr, market_type_tr
                                        )
                                        if existing_pos is None:
                                            # Create new adopted position for HFT trade
                                            direction = (
                                                SignalDirection.LONG
                                                if side_tr.upper() == "BUY"
                                                else SignalDirection.SHORT
                                            )
                                            try:
                                                qty_float = (
                                                    float(qty_tr) if qty_tr else 0.0
                                                )
                                                price_float = float(price_tr)
                                            except (ValueError, TypeError):
                                                qty_float = 0.0
                                                price_float = 0.0

                                            adopted_pos = LivePosition(
                                                symbol=symbol_tr,
                                                direction=direction,
                                                entry_price=price_float,
                                                initial_quantity=qty_float,
                                                remaining_quantity=qty_float,
                                                entry_time=time.time(),
                                                strategy=f"HFT:{bot_id_tr}",
                                                initial_stop_loss=None,
                                                initial_take_profit=None,
                                                current_sl_price=0.0,
                                                status="OPEN",
                                                entry_client_order_id=f"hft-{bot_id_tr}-{int(time.time() * 1000)}",
                                                user_id=self.user_id,
                                                config_id=None,
                                                mode="live",
                                                market_type=market_type_tr,
                                                api_key_id=self.api_key_id,
                                            )
                                            async with self._positions_dict_lock:
                                                self._active_position_set(adopted_pos)
                                            self._monitored_symbols.add(symbol_tr)
                                            logger.info(
                                                f"[HFT:trade] Adopted ENTRY position {symbol_tr} {direction.name} @ {price_float}"
                                            )
                                        else:
                                            logger.debug(
                                                f"[HFT:trade] Position {symbol_tr} already exists. Ignoring entry event."
                                            )
                                # Continue to forward to Telegram (don't skip)

                            # === SPECIAL HANDLING for sl_placed event ===
                            # This event comes from the Rust HFT bot when it places a Stop Loss order.
                            # We need to "adopt" this SL into our internal position state.
                            if event_type == "sl_placed":
                                symbol_from_event = payload.get("symbol")
                                market_type_from_event = self._normalize_market_type(
                                    payload.get("market_type")
                                    or payload.get("marketType")
                                )
                                sl_order_id_from_event = payload.get("sl_order_id")
                                sl_price_from_event = payload.get("sl_price")

                                if symbol_from_event and sl_order_id_from_event:
                                    symbol_lock_sl = self._get_lock_for_position(
                                        symbol_from_event, market_type_from_event
                                    )
                                    async with symbol_lock_sl:
                                        position = self._active_position_get(
                                            symbol_from_event, market_type_from_event
                                        )
                                        if position and position.status == "OPEN":
                                            # Update position with SL info from Rust bot
                                            if position.current_sl_order_id is None:
                                                try:
                                                    position.current_sl_order_id = int(
                                                        sl_order_id_from_event
                                                    )
                                                except (ValueError, TypeError):
                                                    position.current_sl_order_id = None
                                                position.current_sl_client_order_id = (
                                                    f"rust-sl-{sl_order_id_from_event}"
                                                )
                                                if sl_price_from_event:
                                                    try:
                                                        position.current_sl_price = (
                                                            float(sl_price_from_event)
                                                        )
                                                        if (
                                                            position.initial_stop_loss
                                                            is None
                                                        ):
                                                            position.initial_stop_loss = float(
                                                                sl_price_from_event
                                                            )
                                                    except (ValueError, TypeError):
                                                        pass
                                                position.sl_placement_initiated = False
                                                logger.info(
                                                    f"[HFT:sl_placed] Adopted SL {sl_order_id_from_event} @ {sl_price_from_event} for {symbol_from_event}"
                                                )
                                            else:
                                                logger.debug(
                                                    f"[HFT:sl_placed] Position {symbol_from_event} already has SL {position.current_sl_order_id}. Ignoring."
                                                )
                                        else:
                                            logger.debug(
                                                f"[HFT:sl_placed] No OPEN position found for {symbol_from_event}. Ignoring."
                                            )
                                continue  # Don't forward sl_placed to Telegram

                            # === SPECIAL HANDLING for position_closed event ===
                            # When Rust HFT bot closes a position, we need to remove it from our state
                            if event_type == "position_closed":
                                symbol_pc = payload.get("symbol")
                                market_type_pc = self._normalize_market_type(
                                    payload.get("market_type")
                                    or payload.get("marketType")
                                )
                                if symbol_pc:
                                    symbol_lock_pc = self._get_lock_for_position(
                                        symbol_pc, market_type_pc
                                    )
                                    async with symbol_lock_pc:
                                        async with self._positions_dict_lock:
                                            if self._active_position_get(
                                                symbol_pc, market_type_pc
                                            ):
                                                self._active_position_pop(
                                                    symbol_pc, market_type_pc
                                                )
                                                logger.info(
                                                    f"[HFT:position_closed] Removed position {symbol_pc} from active positions"
                                                )
                                            else:
                                                logger.debug(
                                                    f"[HFT:position_closed] Position {symbol_pc} not found in active positions"
                                                )
                                # Continue to forward to Telegram (don't skip)

                            # WHITELIST: Send only known important event types to Telegram
                            # All other types (heartbeat, status, log, etc.) are ignored
                            ALLOWED_HFT_EVENT_TYPES = (
                                "signal",
                                "trade",
                                "error",
                                "position_closed",
                            )
                            if event_type not in ALLOWED_HFT_EVENT_TYPES:
                                logger.debug(
                                    f"[HFT] Skipping non-whitelisted event type: '{event_type}'"
                                )
                                continue  # Ignore unknown/service event types

                            logger.info(
                                f"[HFT] --> Forwarding '{event_type}' to Telegram notifier"
                            )

                            # Sending to Telegram
                            self.loop.create_task(
                                self.telegram_notifier.hft_event(
                                    subtype=event_type,
                                    event_data=payload,
                                    chat_id=self.user_telegram_chat_id,  # Use user-specific chat_id if available
                                ),
                                name=f"HftNotify_{event_type}",
                            )

                    except json.JSONDecodeError:
                        logger.warning(
                            f"Failed to decode HFT event JSON: {message['data']}"
                        )
                    except Exception as e:
                        logger.error(f"Error processing HFT event: {e}", exc_info=True)

            except asyncio.CancelledError:
                logger.info("HFT event listener cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in HFT event listener: {e}", exc_info=True)
                await asyncio.sleep(5)

        await pubsub.unsubscribe(hft_events_channel)
        logger.info("HFT event listener stopped.")

    async def _handle_start_strategy_command(self, payload: dict):
        """Processes the command to start a strategy instance."""
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "[_handle_start_strategy_command] Received payload: %s",
                json.dumps(payload, default=str),
            )
        command_user_id = payload.get("user_id")
        if command_user_id != self.user_id:
            return  # Not for this user's controller

        # If the command specifies an api_key_id, only the matching controller should process it.
        # If api_key_id is not specified (None), ALL controllers for this user will process the command (legacy behavior).
        command_api_key_id = payload.get("api_key_id")
        import os

        logger.info(
            f"[_handle_start_strategy_command] PID: {os.getpid()}, Controller Key ID: {self.api_key_id}, Command Key ID: {command_api_key_id}"
        )

        if command_api_key_id is not None and str(command_api_key_id) != str(
            self.api_key_id
        ):
            logger.info(
                f"[_handle_start_strategy_command] Skipping: Command is for api_key_id={command_api_key_id}, "
                f"but this controller is for api_key_id={self.api_key_id}."
            )
            return

        config_id = payload.get("id")

        # Get the strategy class name from config_data.
        config_data = payload.get("config_data", {})

        # Correct potential typo from API payload ---
        if (
            "min_foundation_weight_threshold" in config_data
            and "min_total_foundation_weight_threshold" not in config_data
        ):
            logger.warning(
                f"Correcting 'min_foundation_weight_threshold' typo to 'min_total_foundation_weight_threshold' for config_id {config_id}"
            )
            config_data["min_total_foundation_weight_threshold"] = config_data.pop(
                "min_foundation_weight_threshold"
            )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "[_handle_start_strategy_command] Extracted config_data: %s",
                json.dumps(config_data, default=str),
            )
        strategy_name = config_data.get("strategy_name")

        # Fallback for old configurations without strategy_name
        # Note: if strategy_name is already set (e.g., GeneticStrategy), do not overwrite
        if not strategy_name:
            # Auto-detect GeneticStrategy based on config fields
            config_symbol = config_data.get("symbol", "")
            config_name = config_data.get("name", "")
            if config_symbol == "GENETIC" or "genetic" in config_name.lower():
                strategy_name = "GeneticStrategy"
                logger.info(
                    f"Auto-detected GeneticStrategy from config (symbol={config_symbol}, name={config_name})"
                )
            else:
                strategy_name = "VisualBuilderStrategy"
            config_data["strategy_name"] = strategy_name
            logger.warning(
                f"Missing strategy_name in config_data for config_id {config_id}, using detected/default: {strategy_name}"
            )
        else:
            logger.info(f"Using provided strategy_name: {strategy_name}")

        strategy_market_type = self._normalize_market_type(
            config_data.get("marketType") or config_data.get("market_type")
        )
        config_data["market_type"] = strategy_market_type
        config_data["marketType"] = (
            "SPOT" if strategy_market_type == "spot" else "FUTURES"
        )

        if not config_id or not strategy_name:
            # Improving logging for clearer debugging
            logger.error(
                f"Invalid START_STRATEGY payload: missing 'id' or 'strategy_name' inside 'config_data'. Payload: {payload}"
            )
            return

        log_prefix = f"[StartCmd:{strategy_name}:{config_id[:8]}]"

        async with self.instances_lock:
            if config_id in self.running_strategy_instances:
                logger.warning(f"{log_prefix} Strategy instance is already running.")
                return

            params_for_instance = config_data.copy()
            params_for_instance["config"] = config_data

            instance = create_strategy_instance(
                strategy_name, params=params_for_instance
            )

            if not instance:
                logger.error(
                    f"{log_prefix} Could not create instance for strategy '{strategy_name}'."
                )
                return

            # Adding start time to payload
            payload["started_at"] = datetime.now(timezone.utc).isoformat()

            # Ensure api_key_id is present in the payload for tracking
            if payload.get("api_key_id") is None:
                payload["api_key_id"] = self.api_key_id

            # Save the instance and its full configuration
            self.running_strategy_instances[config_id] = (instance, payload)
            logger.info(
                f"{log_prefix} Instance created and added to running pool. Total running: {len(self.running_strategy_instances)}"
            )

        # After adding a strategy, the list of tracked symbols needs to be updated
        await self._update_monitored_symbols()

    async def _handle_tv_webhook_signal_command(self, payload: dict):
        command_user_id = payload.get("user_id")
        if command_user_id != self.user_id:
            return

        command_api_key_id = payload.get("api_key_id")
        if command_api_key_id is not None and command_api_key_id != self.api_key_id:
            logger.debug(
                f"[_handle_tv_webhook_signal_command] Command is for api_key_id={command_api_key_id}, "
                f"but this controller is for api_key_id={self.api_key_id}. Skipping."
            )
            return

        config_id = payload.get("config_id")
        source = payload.get("source") or "tradingview_webhook"
        action = str(payload.get("action", "")).lower()
        if not config_id or action not in {"buy", "sell"}:
            logger.error(f"Invalid TV_WEBHOOK_SIGNAL payload: {payload}")
            if config_id:
                await self._update_tv_webhook_status(
                    config_id,
                    "invalid_payload",
                    "Webhook payload is missing config_id or action.",
                    source=source,
                    action=action or None,
                    symbol=payload.get("normalized_symbol") or payload.get("symbol"),
                    event_id=payload.get("event_id"),
                    api_key_id=command_api_key_id,
                )
            return

        async with self.instances_lock:
            running_entry = self.running_strategy_instances.get(config_id)

        if not running_entry:
            logger.info(
                f"[TVWebhook:{config_id[:8]}] Strategy instance is not running on this controller."
            )
            await self._update_tv_webhook_status(
                config_id,
                "ignored_not_running",
                "Strategy instance is not running on this controller.",
                source=source,
                action=action,
                symbol=payload.get("normalized_symbol") or payload.get("symbol"),
                event_id=payload.get("event_id"),
                api_key_id=command_api_key_id,
            )
            return

        instance, config_dict = running_entry
        config_data = config_dict.get("config_data", {}) or {}
        market_type = self._market_type_for_strategy_config(config_dict)

        # HYBRID MODE HANDLING
        signal_id_from_webhook = payload.get("signal_id")
        if config_data.get("signal_source") != "tradingview_webhook":
            if signal_id_from_webhook and hasattr(instance, "register_tv_signal"):
                # Handle as foundation signal (Hybrid mode)
                # Find TTL in strategy config
                ttl_seconds = 60  # Default

                # Recursive search for the block with matching signal_id to get its TTL
                def find_ttl(node, sid):
                    if not isinstance(node, dict):
                        return None
                    if (
                        node.get("type") == "tradingview_signal"
                        and node.get("params", {}).get("signal_id") == sid
                    ):
                        return node.get("params", {}).get("ttl_seconds")
                    children = node.get("children")
                    if isinstance(children, list):
                        for c in children:
                            res = find_ttl(c, sid)
                            if res:
                                return res
                    return None

                config_ttl = find_ttl(
                    config_data.get("entryConditions"), signal_id_from_webhook
                )
                if config_ttl:
                    ttl_seconds = int(config_ttl)

                instance.register_tv_signal(signal_id_from_webhook, ttl_seconds)

                await self._update_tv_webhook_status(
                    config_id,
                    "hybrid_signal_registered",
                    f"Hybrid TV signal '{signal_id_from_webhook}' registered with TTL {ttl_seconds}s.",
                    source=source,
                    action=action,
                    symbol=payload.get("normalized_symbol")
                    or payload.get("symbol"),  # Corrected to use payload symbol
                    event_id=payload.get("event_id"),
                    api_key_id=command_api_key_id,
                )
                return

            await self._update_tv_webhook_status(
                config_id,
                "ignored_wrong_signal_source",
                f"Strategy is in '{config_data.get('signal_source')}' mode and this webhook contains no signal_id for hybrid processing.",
                source=source,
                action=action,
                symbol=payload.get("normalized_symbol") or payload.get("symbol"),
                event_id=payload.get("event_id"),
                api_key_id=command_api_key_id,
            )
            logger.warning(
                f"[TVWebhook:{config_id[:8]}] Strategy is not configured for TradingView webhook mode. Ignored."
            )
            return

        configured_symbol = "".join(
            ch for ch in str(config_data.get("symbol", "")).upper() if ch.isalnum()
        )
        incoming_symbol = "".join(
            ch
            for ch in str(
                payload.get("normalized_symbol") or payload.get("symbol") or ""
            ).upper()
            if ch.isalnum()
        )
        symbol = incoming_symbol or configured_symbol
        if not symbol:
            logger.error(
                f"[TVWebhook:{config_id[:8]}] Could not resolve symbol from payload/config."
            )
            await self._update_tv_webhook_status(
                config_id,
                "rejected_runtime",
                "Could not resolve symbol from webhook payload or strategy config.",
                source=source,
                action=action,
                event_id=payload.get("event_id"),
                api_key_id=command_api_key_id,
            )
            return

        if (
            configured_symbol
            and incoming_symbol
            and configured_symbol != incoming_symbol
        ):
            logger.warning(
                f"[TVWebhook:{config_id[:8]}] Symbol mismatch. Configured={configured_symbol}, incoming={incoming_symbol}."
            )
            await self._update_tv_webhook_status(
                config_id,
                "rejected_runtime",
                f"Runtime symbol mismatch. Expected {configured_symbol}, got {incoming_symbol}.",
                source=source,
                action=action,
                symbol=symbol,
                event_id=payload.get("event_id"),
                api_key_id=command_api_key_id,
            )
            return

        pair_info = await self.consumer.get_active_pair_by_symbol(symbol)
        if not pair_info:
            logger.warning(
                f"[TVWebhook:{config_id[:8]}] No pair info available for {symbol}."
            )
            await self._update_tv_webhook_status(
                config_id,
                "rejected_runtime",
                f"No pair info available for {symbol}.",
                source=source,
                action=action,
                symbol=symbol,
                event_id=payload.get("event_id"),
                api_key_id=command_api_key_id,
            )
            return

        pair_info = dict(pair_info)
        pair_info["symbol"] = symbol
        pair_info["strategy_config_id"] = config_id
        pair_info["market_type"] = market_type

        payload_price = payload.get("price")
        if isinstance(payload_price, (int, float)):
            pair_info["last_price"] = float(payload_price)

        pair_info["tick_size"] = (
            await self._get_market_info(symbol, "tick_size", market_type=market_type)
            or config.DEFAULT_TICK_SIZE
        )

        market_data = await self._gather_market_data_for_strategy(
            instance, symbol, market_type=market_type
        )
        if market_data is None:
            logger.warning(
                f"[TVWebhook:{config_id[:8]}] Missing market data for {symbol}."
            )
            await self._update_tv_webhook_status(
                config_id,
                "rejected_runtime",
                f"Missing market data for {symbol}.",
                source=source,
                action=action,
                symbol=symbol,
                event_id=payload.get("event_id"),
                api_key_id=command_api_key_id,
            )
            return

        try:
            signal_result, trace = instance.build_external_signal(
                config_data,
                pair_info,
                market_data,
                action=action,
                webhook_payload=payload,
            )
        except Exception as exc:
            logger.error(
                f"[TVWebhook:{config_id[:8]}] Error while building external signal: {exc}",
                exc_info=True,
            )
            await self._update_tv_webhook_status(
                config_id,
                "error_build_signal",
                f"Error while building external signal: {exc}",
                source=source,
                action=action,
                symbol=symbol,
                event_id=payload.get("event_id"),
                api_key_id=command_api_key_id,
            )
            return

        if trace and isinstance(trace, dict):
            logger.info(
                f"[TVWebhook:{config_id[:8]}] Webhook trace result: {trace.get('rejection_reason', 'passed')}"
            )

        if isinstance(signal_result, StrategySignal):
            if signal_result.details is None:
                signal_result.details = {}
            signal_result.details["strategy_config_id"] = config_id
            signal_result.details["market_type"] = market_type
            signal_result.details["marketType"] = (
                "SPOT" if market_type == "spot" else "FUTURES"
            )
            await self._update_tv_webhook_status(
                config_id,
                "queued_for_execution",
                "Webhook signal passed filters and was queued for execution.",
                source=source,
                action=action,
                symbol=symbol,
                event_id=payload.get("event_id"),
                api_key_id=command_api_key_id,
                trace=trace if isinstance(trace, dict) else None,
            )
            self.loop.create_task(
                self._process_signal(
                    signal_result, pair_info, market_data_snapshot=market_data
                ),
                name=f"ProcessTvWebhook_{config_id}_{symbol}",
            )
            return

        await self._update_tv_webhook_status(
            config_id,
            "rejected_runtime",
            "Webhook signal did not pass runtime filters.",
            source=source,
            action=action,
            symbol=symbol,
            event_id=payload.get("event_id"),
            api_key_id=command_api_key_id,
            trace=trace if isinstance(trace, dict) else None,
        )

    async def _update_tv_webhook_status(
        self,
        config_id: str,
        status_value: str,
        message: Optional[str] = None,
        *,
        source: str = "tradingview_webhook",
        action: Optional[str] = None,
        symbol: Optional[str] = None,
        event_id: Optional[str] = None,
        api_key_id: Optional[int] = None,
        trace: Optional[Dict[str, Any]] = None,
    ):
        if not self.redis_client or not config_id:
            return

        payload: Dict[str, Any] = {
            "config_id": config_id,
            "status": status_value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "message": message,
            "source": source,
            "action": action,
            "symbol": symbol,
            "event_id": event_id,
            "api_key_id": api_key_id,
        }
        if trace:
            payload["trace"] = json.loads(json.dumps(trace, default=str))

        try:
            await self.redis_client.set(
                f"tv:webhook:last:{self.user_id}:{config_id}",
                json.dumps(payload, default=str),
                ex=60 * 60 * 24 * 7,
            )
        except Exception as exc:
            logger.warning(
                f"[TVWebhook:{config_id[:8]}] Failed to persist webhook status: {exc}"
            )

    async def _handle_stop_strategy_command(self, payload: dict):
        """Processes the command to stop a strategy instance."""
        command_user_id = payload.get("user_id")
        if command_user_id != self.user_id:
            return  # Not for this user's controller

        config_id = payload.get("strategy_id")  # API sends 'strategy_id'
        if not config_id:
            logger.error(
                f"Invalid STOP_STRATEGY payload: missing 'strategy_id'. Payload: {payload}"
            )
            return

        log_prefix = f"[StopCmd:{config_id[:8]}]"

        async with self.instances_lock:
            if config_id not in self.running_strategy_instances:
                # This is expected behavior when multiple controllers exist for the same user.
                logger.debug(
                    f"{log_prefix} Strategy instance not found on this controller (api_key_id={self.api_key_id}). Skipping."
                )
                return

            # Removing the instance from the pool of workers
            instance, config_data = self.running_strategy_instances.pop(config_id)
            logger.info(
                f"{log_prefix} Instance '{instance.NAME}' removed from running pool. Total remaining: {len(self.running_strategy_instances)}"
            )

        # After deletion, we need to re-check if we still need data for this symbol
        await self._check_and_update_symbols()

    async def _check_scale_in_conditions(
        self, position: LivePosition, pair_info: Dict[str, Any]
    ):
        log_prefix = f"[ScaleInCheck:{position.symbol}]"

        if not position.scale_in_rules:
            return

        if position.max_entries and position.number_of_entries >= position.max_entries:
            return

        market_data = {}
        # Fetch required data for condition evaluation
        # This part needs to be adapted based on what conditions can be used for scale-in
        # For now, we assume that the required data is already in pair_info or can be fetched

        for rule in position.scale_in_rules:
            conditions = rule.get("children", [])
            if not conditions:
                continue

            conditions_met, _ = await self._evaluate_position_condition_tree(
                rule, position, pair_info, market_data
            )

            if conditions_met:
                logger.info(f"{log_prefix} Scale-in conditions met.")

                add_size_pct = rule.get("params", {}).get(
                    "add_size_pct_of_initial_risk", 100
                )

                position_market_type = self._market_type_for_position(position)
                lot_params = await self._get_market_info(
                    position.symbol, "lot_params", market_type=position_market_type
                )
                min_notional = await self._get_market_info(
                    position.symbol, "min_notional", market_type=position_market_type
                )
                current_price = pair_info.get("last_price")

                if not current_price:
                    logger.error(
                        f"{log_prefix} Could not get current price for {position.symbol}. Cannot scale in."
                    )
                    return

                new_quantity = await self.rm.calculate_scaled_in_quantity(
                    position, add_size_pct, current_price, lot_params, min_notional
                )

                if not new_quantity or new_quantity <= 0:
                    logger.warning(
                        f"{log_prefix} Calculated scale-in quantity is invalid: {new_quantity}"
                    )
                    return

                binance_side = (
                    "BUY" if position.direction == SignalDirection.LONG else "SELL"
                )
                scale_in_order_params = {
                    "symbol": position.symbol,
                    "side": binance_side,
                    "quantity": new_quantity,
                    "type": "MARKET",
                    "newClientOrderId": f"x-scalein-{uuid.uuid4().hex[:14]}",
                    "entry_client_order_id": position.entry_client_order_id,
                    "strategy_config_id": position.config_id,
                    "signal_details": position.signal_details,
                }

                executor = self._executor_for_market_type(
                    position_market_type, mode=position.mode
                )
                if not executor:
                    logger.error(
                        f"{log_prefix} Executor for market '{position_market_type}' not found. Cannot scale in."
                    )
                    return

                scale_in_order_response = await executor.place_order(
                    **scale_in_order_params
                )

                if scale_in_order_response and not scale_in_order_response.get("error"):
                    logger.info(
                        f"{log_prefix} Scale-in order placed: {scale_in_order_response}"
                    )
                    # The position will be updated in the _handle_order_update method
                    # We just need to increment the number of entries for now.
                    position.number_of_entries += 1
                else:
                    logger.error(
                        f"{log_prefix} Scale-in order failed: {scale_in_order_response}"
                    )

    async def _execute_management_actions(
        self,
        position: LivePosition,
        actions: List[Dict[str, Any]],
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
    ):
        log_prefix = f"[MgmtActions:{position.symbol}]"
        context = {"pair_info": pair_info, "market_data": market_data, "trace": {}}

        for action in actions:
            action_type = action.get("type")
            params = action.get("params", {})

            if action_type == "modify_stop_loss":
                new_sl_price_param = params.get("new_sl_price")
                if not new_sl_price_param:
                    logger.warning(
                        f"{log_prefix} 'new_sl_price' not specified in modify_stop_loss action."
                    )
                    continue

                new_sl_price = await self._resolve_position_value(
                    new_sl_price_param, position, pair_info, market_data, context
                )

                if (
                    not new_sl_price
                    or not isinstance(new_sl_price, (int, float))
                    or new_sl_price <= 0
                ):
                    logger.warning(
                        f"{log_prefix} Could not resolve a valid new_sl_price: {new_sl_price}"
                    )
                    continue

                logger.info(
                    f"{log_prefix} Executing modify_stop_loss. New SL price: {new_sl_price}"
                )
                # Pass position.symbol (str) instead of the entire position object
                await self._replace_stop_loss(
                    position.symbol,
                    new_sl_price,
                    market_type=self._market_type_for_position(position),
                )
            else:
                logger.warning(
                    f"{log_prefix} Unknown management action type: {action_type}"
                )

    async def _evaluate_position_condition_tree(
        self,
        node: Dict[str, Any],
        position: LivePosition,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
    ) -> Tuple[bool, Dict[str, Any]]:
        node_type = node.get("type")
        node_id = node.get("id", "unknown")
        children = node.get("children", [])
        trace = {"id": node_id, "type": node_type, "result": False, "details": {}}
        context = {"pair_info": pair_info, "market_data": market_data, "trace": trace}

        if node_type in ["AND", "OR"]:
            trace["children"] = []
            if not children:
                is_true = node_type == "AND"
                trace["result"] = is_true
                trace["details"] = {"info": "Empty logic gate evaluated."}
                return (is_true, trace)

            child_results = []
            for child_node in children:
                (
                    child_result,
                    child_trace,
                ) = await self._evaluate_position_condition_tree(
                    child_node, position, pair_info, market_data
                )
                child_results.append(child_result)
                trace["children"].append(child_trace)

            trace["result"] = (
                all(child_results) if node_type == "AND" else any(child_results)
            )
            return (trace["result"], trace)
        else:
            params = node.get("params", {})
            trace["params"] = params
            result = False
            details = {}

            try:
                if node_type == "price_vs_level":
                    price_source = params.get("price_source")
                    operator = params.get("operator", "gt")
                    level_source = params.get("level_source")

                    left_value = await self._resolve_position_value(
                        price_source, position, pair_info, market_data, context
                    )
                    right_value = await self._resolve_position_value(
                        level_source, position, pair_info, market_data, context
                    )

                    details["left_value_resolved"] = left_value
                    details["right_value_resolved"] = right_value

                    if left_value is not None and right_value is not None:
                        try:
                            left_float = float(left_value)
                            right_float = float(right_value)
                            if operator == "gt":
                                result = left_float > right_float
                            elif operator == "lt":
                                result = left_float < right_float
                            else:
                                details["error"] = f"Unknown operator: {operator}"
                                result = False
                        except (ValueError, TypeError) as e:
                            details["error"] = (
                                f"Could not convert resolved values to float: {e}"
                            )
                            result = False
                    else:
                        details["error"] = (
                            "One or both dynamic values could not be resolved."
                        )
                        result = False
                else:
                    details["error"] = f"Unknown condition type: {node_type}"
                    result = False

            except Exception as e:
                details["error"] = (
                    f"Exception during evaluation of '{node_type}': {str(e)}"
                )
                result = False

            trace["result"] = result
            trace["details"] = details
            return (result, trace)

    async def _resolve_position_value(
        self,
        param_value: Any,
        position: LivePosition,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Any:
        if isinstance(param_value, dict) and "source" in param_value:
            source = param_value["source"]
            key = param_value.get("key")
            shift = int(param_value.get("shift", 0))

            if source == "position_state":
                if key == "entry_price":
                    return position.entry_price
                elif key == "current_size_qty":
                    return position.remaining_quantity
                elif key == "unrealized_pnl_pct":
                    if (
                        position.entry_price
                        and position.entry_price > 0
                        and position.initial_quantity > 0
                    ):
                        pnl = (
                            pair_info.get("last_price", 0) - position.entry_price
                        ) * position.remaining_quantity
                        if position.direction == SignalDirection.SHORT:
                            pnl = -pnl
                        return (
                            pnl / (position.entry_price * position.initial_quantity)
                        ) * 100
                    return 0.0
                elif key == "time_in_trade_sec":
                    return time.time() - position.entry_time
                elif key == "number_of_entries":
                    return position.number_of_entries
                return None

            elif source == "candle":
                timeframe = param_value.get(
                    "timeframe", pair_info.get("candle_timeframe", "1m")
                )
                kline_key = f"kline_{timeframe}"
                candles_df = market_data.get(kline_key)
                current_index = pair_info.get("current_candle_index")

                if candles_df is not None and current_index is not None:
                    target_index = current_index - shift
                    if 0 <= target_index < len(candles_df):
                        return candles_df.iloc[target_index][key]
                return None

            elif source == "indicator":
                indicator_key = f"{key.upper()}_{pair_info.get('candle_timeframe', '1m')}"  # Simplified
                return pair_info.get(indicator_key)

            elif source == "block_result":
                block_id = param_value.get("block_id")
                trace = context.get("trace")
                if block_id and trace:
                    # This needs a function to find block in trace, which is in strategy.py
                    # For now, this will not be supported in scale-in conditions
                    pass
                return None

        return param_value

    async def _log_signal_context_for_ml(
        self,
        signal: StrategySignal,
        pair_info: Dict[str, Any],
        controller_client_order_id: str,
        initial_risk_usd: Optional[float],
        market_data_snapshot: Optional[Dict[str, Any]] = None,
    ):
        """Collects and logs the signal context for ML, including the order book."""
        if not self.realtime_ml_logger or not getattr(
            config, "LOG_REALTIME_ML_DATA", False
        ):
            return

        log_prefix = f"[MLContextLog:{signal.symbol}]"
        try:
            signal_market_type = self._normalize_market_type(
                (signal.details or {}).get("market_type")
                if isinstance(signal.details, dict)
                else None
            )
            depth_to_log = getattr(config, "REALTIME_ML_ORDERBOOK_DEPTH_SNAPSHOT", 10)
            orderbook_snapshot_trading = None
            orderbook_snapshot_analysis = None

            def _snapshot_from_depth(depth_obj: Any) -> Optional[Dict[str, Any]]:
                if not isinstance(depth_obj, dict):
                    return None
                bids = depth_obj.get("bids", [])
                asks = depth_obj.get("asks", [])
                if not isinstance(bids, list) or not isinstance(asks, list):
                    return None
                return {
                    "bids": bids[:depth_to_log],
                    "asks": asks[:depth_to_log],
                    "lastUpdateId": depth_obj.get("lastUpdateId"),
                }

            if market_data_snapshot:
                orderbook_snapshot_trading = _snapshot_from_depth(
                    market_data_snapshot.get("depth_trading")
                    or market_data_snapshot.get("depth")
                )
                orderbook_snapshot_analysis = _snapshot_from_depth(
                    market_data_snapshot.get("depth_companion_full_l2")
                    or market_data_snapshot.get("depth_analysis")
                )

            # 1. Use snapshot from shared market_data (if passed), otherwise perform fallback-fetch.

            # Trading orderbook (fallback fetch only when not available in shared snapshot)
            if orderbook_snapshot_trading is None:
                depth_data_trading = await self.consumer.get_latest_depth(
                    signal.symbol, market_type_requested=signal_market_type
                )
                if depth_data_trading:
                    orderbook_snapshot_trading = _snapshot_from_depth(
                        depth_data_trading
                    )

            # Analysis orderbook (fallback fetch only when not available in shared snapshot)
            if (
                orderbook_snapshot_analysis is None
                and config.USE_COMPANION_ORDERBOOK_ANALYSIS
            ):
                companion_market_type_log: Optional[str] = None
                companion_market_type_log = self._companion_market_type(
                    signal_market_type
                )

                if companion_market_type_log:
                    depth_data_analysis = await self.consumer.get_latest_depth(
                        signal.symbol, market_type_requested=companion_market_type_log
                    )
                    if depth_data_analysis:
                        orderbook_snapshot_analysis = _snapshot_from_depth(
                            depth_data_analysis
                        )

            # 2. Getting "raw" features (requires FeatureExtractor and data)
            # This is the complex part for real-time.
            # IMPORTANT: FeatureExtractor must be available here, and data must be present.
            # For simplicity, we'll leave a placeholder for now, but this will need to be implemented.
            raw_features_live = {}  # STUB
            # orderbook_features_live should be extracted from orderbook_snapshot_trading or orderbook_snapshot_analysis
            orderbook_features_live_trading = {}  # STUB
            orderbook_features_live_analysis = {}  # STUB

            # Approximate concept (REQUIRES INFRASTRUCTURE IMPROVEMENT):
            # if hasattr(self, 'feature_extractor_instance') and self.feature_extractor_instance:
            #     kline_tf = signal.details.get('candle_timeframe', self._get_param(signal.strategy_name, 'candle_timeframe', '1m'))
            #     kline_history_df = await self.consumer.get_kline_history(signal.symbol, kline_tf)
            #     agg_trades_df = await self.consumer.get_recent_trades(signal.symbol) # or list
            #     if kline_history_df is not None and not kline_history_df.empty:
            #         current_candle_data = kline_history_df.iloc[-1].to_dict()
            #         # Supplement current_candle_data from pair_info (SMA, RSI, etc.)
            #         for k_pi, v_pi in pair_info.items():
            #             if k_pi not in current_candle_data: current_candle_data[k_pi] = v_pi
            #         current_idx = len(kline_history_df) - 1
            #         current_ts_ms = int(kline_history_df.index[-1].timestamp() * 1000) # Correct timestamp of the candle end is needed
            #
            #         raw_features_live = self.feature_extractor_instance.extract_features_optimized(
            #             current_candle_data=current_candle_data,
            #             agg_trades_list=agg_trades_df.to_dict('records') if agg_trades_df is not None else None, # Example
            #             full_kline_history=kline_history_df,
            #             current_index=current_idx,
            #             current_timestamp_ms=current_ts_ms
            #         )
            #         # orderbook_features_live_trading = self.feature_extractor_instance.extract_orderbook_features(orderbook_snapshot_trading)
            #         # orderbook_features_live_analysis = self.feature_extractor_instance.extract_orderbook_features(orderbook_snapshot_analysis)

            # 3. Forming a log entry
            context_data_for_log = {
                "signal_timestamp": datetime.fromtimestamp(
                    signal.signal_time, tz=timezone.utc
                ).isoformat(),
                "controller_client_order_id": controller_client_order_id,
                "original_signal_client_order_id": signal.details.get(
                    "original_client_order_id_for_ml_log", controller_client_order_id
                ),
                "strategy": signal.strategy_name,
                "symbol": signal.symbol,
                "direction": signal.direction.name,
                "signal_trigger_price": signal.trigger_price,
                "signal_entry_price": signal.entry_price,
                "signal_sl": signal.stop_loss,
                "signal_tp": signal.take_profit,
                "initial_risk_usd_planned": initial_risk_usd,
                "raw_features_live_json": raw_features_live,
                # Log specific orderbooks
                "orderbook_snapshot_trading_json": orderbook_snapshot_trading,
                "orderbook_snapshot_analysis_json": orderbook_snapshot_analysis,
                # For backward compatibility or general use, 'orderbook_snapshot_json' can be the trading one
                "orderbook_snapshot_json": orderbook_snapshot_trading,
                "orderbook_features_live_trading_json": orderbook_features_live_trading,
                "orderbook_features_live_analysis_json": orderbook_features_live_analysis,
                "signal_details_json": signal.details,
            }

            self.realtime_ml_logger.log_data(
                event_type="SIGNAL_CONTEXT", data=context_data_for_log
            )
            log_message_parts = [
                f"{log_prefix} Logged SIGNAL_CONTEXT for ML (CID: {controller_client_order_id})."
            ]
            if orderbook_snapshot_trading:
                log_message_parts.append("Trading OB included.")
            if orderbook_snapshot_analysis:
                log_message_parts.append("Analysis OB included.")
            logger.info(" ".join(log_message_parts))

        except Exception as e:
            logger.error(
                f"{log_prefix} Error logging signal context for ML: {e}", exc_info=True
            )

    async def _build_adopted_position(
        self, symbol: str, exch_data: Dict[str, Any], market_type: str, executor: Any
    ) -> Optional[LivePosition]:
        """Helper to build an adopted position object with DB and API lookups."""
        qty = float(exch_data["positionAmt"])
        entry_price = float(exch_data["entryPrice"])
        direction = SignalDirection.LONG if qty > 0 else SignalDirection.SHORT

        assigned_strategy_name = "Unknown/Manual"
        assigned_config_id = None
        entry_client_id = f"adopted-{uuid.uuid4().hex[:8]}"

        # DB lookup
        try:
            async for db in self.get_db_session():
                last_trade = await crud.get_last_open_trade_for_symbol(
                    db, self.user_id, symbol
                )
                if last_trade:
                    assigned_strategy_name = (
                        last_trade.strategy_config.name
                        if last_trade.strategy_config
                        else str(last_trade.strategy_config_id)
                    )
                    assigned_config_id = last_trade.strategy_config_id
                    if last_trade.trade_uuid and last_trade.trade_uuid.startswith(
                        "x-entry-"
                    ):
                        entry_client_id = last_trade.trade_uuid
                    break
        except Exception as e:
            logger.error(f"Adopt:{symbol}: DB error: {e}")

        adopted_pos = LivePosition(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            initial_quantity=abs(qty),
            remaining_quantity=abs(qty),
            entry_time=time.time(),
            strategy=assigned_strategy_name,
            status="OPEN",
            entry_client_order_id=entry_client_id,
            user_id=self.user_id,
            config_id=assigned_config_id,
            mode="live",
            market_type=market_type,
            api_key_id=self.api_key_id,
            current_sl_price=0.0,
        )

        # SL lookup (API call)
        try:
            open_orders = await executor.get_open_orders(symbol)
            for o in open_orders:
                o_type = o.get("type")
                o_side = o.get("side")
                o_price = float(o.get("stopPrice") or o.get("price") or 0)
                o_id = o.get("orderId")
                o_cid = o.get("clientOrderId")

                is_sl = False
                if (direction == SignalDirection.LONG and o_side == "SELL") or (
                    direction == SignalDirection.SHORT and o_side == "BUY"
                ):
                    if o_type in ["STOP_MARKET", "STOP_LOSS", "STOP_LOSS_LIMIT"]:
                        is_sl = True

                if is_sl:
                    adopted_pos.current_sl_price = o_price
                    adopted_pos.current_sl_order_id = o_id
                    adopted_pos.current_sl_client_order_id = o_cid
                    adopted_pos.initial_stop_loss = o_price
                    break
        except Exception as e:
            logger.error(f"Adopt:{symbol}: API error: {e}")

        return adopted_pos

    async def _reconcile_positions_with_exchange(self):
        """
        Synchronizes the internal state of positions with the actual state on the exchange.
        Optimized using fine-grained locks and snapshotting to avoid blocking the event loop.
        """
        log_prefix = f"[ReconcilePositions:{self.api_key_name}]"
        logger.info(f"{log_prefix} Starting reconciliation with exchange...")

        executor = self.executors.get("live")
        if not executor:
            logger.warning(
                f"{log_prefix} Live executor not available. Skipping reconciliation."
            )
            return
        reconcile_market_type = self._normalize_market_type(
            getattr(executor, "market_type", None)
        )

        try:
            # 1. Getting real positions from the exchange (NO LOCK)
            exchange_positions_raw = await executor.get_open_positions()
            exchange_positions_map = {
                p["symbol"]: p
                for p in exchange_positions_raw
                if float(p.get("positionAmt", 0)) != 0
            }
            logger.info(
                f"{log_prefix} Exchange reports {len(exchange_positions_map)} open positions."
            )

            # 2. Fast snapshot of internal positions
            async with self._positions_dict_lock:
                internal_snapshot = {
                    k: v
                    for k, v in self._active_positions.items()
                    if self._market_type_for_position(v) == reconcile_market_type
                }

            # 3. Calculate diff
            to_close = []  # Keys to close internally
            to_update = []  # (symbol, exch_data) pairs to update

            for position_key, internal_pos in internal_snapshot.items():
                symbol = internal_pos.symbol
                if symbol not in exchange_positions_map:
                    to_close.append((position_key, symbol))
                else:
                    to_update.append((symbol, exchange_positions_map.pop(symbol)))

            # exchange_positions_map now contains only ORPHANS
            to_adopt = list(exchange_positions_map.items())

            # 4. Apply updates and closures under per-symbol locks
            for position_key, symbol in to_close:
                symbol_lock = self._get_lock_for_position(symbol, reconcile_market_type)
                async with symbol_lock:
                    # Re-check if it's still in the dict and status is OPEN
                    current_pos = self._active_position_get(
                        symbol, reconcile_market_type
                    )
                    if current_pos and current_pos.status in {"OPEN", "CLOSING"}:
                        logger.warning(
                            f"{log_prefix} Position {symbol} exists internally but NOT on exchange. Marking as CLOSED."
                        )
                        current_pos.status = "CLOSED"
                        current_pos.exit_reason = "CLOSED_WHILE_OFFLINE"
                        current_pos.closed_time = time.time()
                        current_pos.remaining_quantity = 0.0
                        async with self._positions_dict_lock:
                            self._active_position_pop(symbol, reconcile_market_type)

            for symbol, exch_data in to_update:
                symbol_lock = self._get_lock_for_position(symbol, reconcile_market_type)
                async with symbol_lock:
                    internal_pos = self._active_position_get(
                        symbol, reconcile_market_type
                    )
                    if not internal_pos:
                        continue

                    exch_qty = float(exch_data["positionAmt"])
                    exch_entry_price = float(exch_data["entryPrice"])
                    exch_direction = (
                        SignalDirection.LONG if exch_qty > 0 else SignalDirection.SHORT
                    )

                    # Update direction
                    if internal_pos.direction != exch_direction:
                        logger.warning(
                            f"{log_prefix} Direction conflict for {symbol}. Overwriting."
                        )
                        internal_pos.direction = exch_direction

                    # Update quantity and price
                    internal_pos.remaining_quantity = abs(exch_qty)
                    if internal_pos.initial_quantity < internal_pos.remaining_quantity:
                        internal_pos.initial_quantity = internal_pos.remaining_quantity
                    internal_pos.entry_price = exch_entry_price

            # 5. Adopt orphans (Heavy operations like DB queries and API calls done without global lock)
            for symbol, exch_data in to_adopt:
                logger.warning(f"{log_prefix} Adopting orphan: {symbol}")
                adopted_pos = await self._build_adopted_position(
                    symbol, exch_data, reconcile_market_type, executor
                )
                if adopted_pos:
                    async with self._positions_dict_lock:
                        self._active_position_set(adopted_pos)
                    self._monitored_symbols.add(symbol)

            # Updating subscriptions after reconcile
            await self._update_monitored_symbols()
            logger.info(f"{log_prefix} Reconciliation complete.")

        except Exception as e:
            logger.error(
                f"{log_prefix} Error during reconciliation: {e}", exc_info=True
            )

    async def _save_runtime_state(self):
        """
        Saves the full state of the controller (positions, managed symbols, etc.) to Redis
        using JSON for portability and security.
        """
        if not self.redis_client:
            return

        log_prefix = "[SaveRuntimeState]"
        try:
            # Collect data that is critically important for recovery
            # JSON-compatible serialization under dictionary lock to prevent iteration errors
            async with self._positions_dict_lock:
                serialized_positions = {
                    k: v.to_dict() for k, v in self._active_positions.items()
                }

            state_snapshot = {
                "active_positions": serialized_positions,
                "monitored_symbols": list(self._monitored_symbols),
                "closing_managed_symbols": list(self._closing_managed_symbols),
                "last_known_symbols": list(self._last_known_symbols_from_consumer),
                "currently_managed_symbols": list(self.currently_managed_symbols),
                "symbol_selection_config": self.symbol_selection_config.model_dump()
                if self.symbol_selection_config
                else None,
                "timestamp": time.time(),
                "serialization_format": "json",
            }

            await self.redis_client.set(
                self.redis_key_runtime_state, json.dumps(state_snapshot)
            )
            logger.debug(
                f"{log_prefix} Successfully saved runtime state for user {self.user_id}. Positions: {len(serialized_positions)}"
            )

        except Exception as e:
            logger.error(
                f"{log_prefix} Failed to save runtime state: {e}", exc_info=True
            )

    async def _load_runtime_state(self):
        """
        Loads the saved controller state from Redis at startup.
        Restores active positions and symbol lists.
        """
        if not self.redis_client:
            return

        log_prefix = "[LoadRuntimeState]"
        try:
            raw_data = await self.redis_client.get(self.redis_key_runtime_state)
            if not raw_data:
                logger.info(
                    f"{log_prefix} No saved runtime state found for user {self.user_id}. Starting fresh."
                )
                return

            try:
                state_snapshot = json.loads(raw_data)
                logger.debug(f"{log_prefix} State loaded using JSON format.")
            except (json.JSONDecodeError, TypeError) as json_err:
                logger.warning(
                    f"{log_prefix} SECURITY WARNING: State is not in valid JSON format. "
                    f"Skipping loading of unverified checkpoint to prevent pickle vulnerability: {json_err}"
                )
                return

            if (
                not isinstance(state_snapshot, dict)
                or state_snapshot.get("serialization_format") != "json"
            ):
                logger.warning(
                    f"{log_prefix} SECURITY WARNING: serialization_format is not 'json'. "
                    f"Skipping loading to prevent potential pickle vulnerability."
                )
                return

            # Restoring state metadata
            timestamp = state_snapshot.get("timestamp", 0)
            age = time.time() - timestamp
            logger.info(
                f"{log_prefix} Found saved state from {datetime.fromtimestamp(timestamp, tz=timezone.utc)} (Age: {age:.1f}s)."
            )

            # Restore symbol sets
            self._monitored_symbols = set(state_snapshot.get("monitored_symbols", []))
            self._closing_managed_symbols = set(
                state_snapshot.get("closing_managed_symbols", [])
            )
            self._last_known_symbols_from_consumer = set(
                state_snapshot.get("last_known_symbols", [])
            )
            self.currently_managed_symbols = set(
                state_snapshot.get("currently_managed_symbols", [])
            )

            # Restore positions (with exchange verification)
            restored_positions_raw = state_snapshot.get("active_positions", {})
            if restored_positions_raw:
                logger.info(
                    f"{log_prefix} Found {len(restored_positions_raw)} positions in saved state. Validating with exchange..."
                )

                # 1. Deserialize all positions first
                restored_positions_objects = {}
                for k, v in restored_positions_raw.items():
                    try:
                        pos = LivePosition.from_dict(v)

                        # Backfill api_key_id if missing
                        if getattr(pos, "api_key_id", None) is None:
                            pos.api_key_id = self.api_key_id

                        restored_positions_objects[k] = pos
                    except Exception as e:
                        logger.error(
                            f"{log_prefix} Error deserializing position {k}: {e}"
                        )

                validated_positions = {}
                # 2. Getting real positions from the exchange for verification
                try:
                    live_executor = self.executors.get("live")
                    if live_executor:
                        exchange_positions = await live_executor.get_open_positions()
                        exchange_symbols = {
                            p["symbol"]
                            for p in exchange_positions
                            if float(p.get("positionAmt", 0)) != 0
                        }

                        for _position_key, pos in restored_positions_objects.items():
                            symbol = getattr(pos, "symbol", None)
                            if not symbol:
                                try:
                                    symbol = str(_position_key).split(":", 1)[-1]
                                except Exception:
                                    continue

                            if symbol in exchange_symbols:
                                validated_positions[
                                    self._position_key_for_position(pos)
                                ] = pos
                                logger.info(
                                    f"{log_prefix} Position {symbol} verified on exchange. Restored."
                                )
                            else:
                                logger.warning(
                                    f"{log_prefix} Position {symbol} NOT found on exchange. Skipping restoration."
                                )
                    else:
                        # If no live executor, we can't verify, so we just restore all
                        validated_positions = restored_positions_objects

                except Exception as exch_err:
                    logger.error(
                        f"{log_prefix} Failed to verify positions with exchange: {exch_err}. Restoring all as-is."
                    )
                    validated_positions = restored_positions_objects

                # 3. Finally set the validated positions under lock
                async with self._positions_dict_lock:
                    for pos in validated_positions.values():
                        self._active_position_set(pos)

                logger.info(
                    f"{log_prefix} Successfully restored {len(validated_positions)} positions."
                )

        except Exception as e:
            logger.error(
                f"{log_prefix} Failed to load runtime state: {e}", exc_info=True
            )
            # If loading failed, it's better to start with a clean state than a corrupted one
            logger.warning(
                f"{log_prefix} Clearing potentially corrupted state to avoid issues."
            )
            self._active_positions = ActivePositionMap()

    async def _publish_state_to_redis(self):
        """
        Collects data on running strategies, active positions, and the OVERALL portfolio state,
        and then publishes them to Redis.
        """
        if not self.redis_client:
            return

        position_pnl_cache: Dict[str, float] = {}
        positions_to_publish = []

        # 1. Collecting data on POSITIONS
        async with self._positions_dict_lock:
            active_positions_copy = list(self._active_positions.values())

        total_unrealized_pnl = 0.0
        total_initial_margin = 0.0

        for pos in active_positions_copy:
            if pos.status != "OPEN":
                continue

            # Getting the current price
            mark_price = pos.entry_price  # Default fallback
            pair_info = await self.consumer.get_active_pair_by_symbol(pos.symbol)
            if pair_info and pair_info.get("last_price"):
                mark_price = pair_info["last_price"]
            else:
                # If there is no data in the DataConsumer cache, request the price directly from the exchange
                # This is critically important for adopted positions after a restart,
                # when DataConsumer is not yet subscribed to the symbol
                live_executor = self.executors.get("live")
                if live_executor:
                    try:
                        ticker_data = await live_executor.get_ticker_price(pos.symbol)
                        if ticker_data and ticker_data.get("price"):
                            mark_price = float(ticker_data["price"])
                            logger.debug(
                                f"[PublishState] Fetched mark_price from API for {pos.symbol}: {mark_price}"
                            )
                    except Exception as e_ticker:
                        logger.warning(
                            f"[PublishState] Failed to fetch ticker price for {pos.symbol}: {e_ticker}"
                        )

            pnl, pnl_percent = 0.0, 0.0
            if pos.entry_price and pos.entry_price > 0 and pos.initial_quantity > 0:
                pnl_calc = (mark_price - pos.entry_price) * pos.remaining_quantity
                if pos.direction == SignalDirection.SHORT:
                    pnl_calc = -pnl_calc

                position_pnl_cache[pos.entry_client_order_id] = pnl_calc
                pnl = pnl_calc
                pnl_percent = (pnl / (pos.entry_price * pos.initial_quantity)) * 100

                # Update max floating profit/loss (MPP/MPU)
                # Update max floating profit (positive values)
                if pnl_calc > 0:
                    if (
                        pos.max_floating_profit is None
                        or pnl_calc > pos.max_floating_profit
                    ):
                        pos.max_floating_profit = pnl_calc
                # Update max floating loss (stored as positive value representing loss)
                elif pnl_calc < 0:
                    loss_abs = abs(pnl_calc)
                    if (
                        pos.max_floating_loss is None
                        or loss_abs > pos.max_floating_loss
                    ):
                        pos.max_floating_loss = loss_abs

                # Summing up for the portfolio
                total_unrealized_pnl += pnl
                # Rough margin estimation (excluding leverage if it's not stored in pos)
                # If leverage is stored in RM, it's better to take it from there, but for the UI for now:
                total_initial_margin += (
                    pos.entry_price * pos.remaining_quantity
                ) / 1.0  # Assume 1x for display safety or take the actual leverage
            # Get the current TP from partial_tp_orders (the first PENDING order)
            current_tp = pos.initial_take_profit  # Fallback to initial
            if pos.partial_tp_orders:
                for ptp in pos.partial_tp_orders:
                    if ptp.status in {
                        "PENDING",
                        "PENDING_PLACEMENT",
                        "VIRTUAL_PENDING",
                    }:
                        current_tp = ptp.target_price
                        break

            # Fallback for existing positions in memory without api_key_id
            if pos.api_key_id is None:
                pos.api_key_id = self.api_key_id

            pos_data = {
                "id": pos.entry_client_order_id,
                "symbol": pos.symbol,
                "strategy": pos.strategy,
                "direction": pos.direction.name,
                "size": pos.remaining_quantity,
                "entry_price": pos.entry_price,
                "mark_price": mark_price,
                "pnl": round(pnl, 4),
                "pnl_percent": round(pnl_percent, 4),
                "entry_time": datetime.fromtimestamp(
                    pos.entry_time, timezone.utc
                ).isoformat(),
                "stop_loss": pos.current_sl_price,
                "take_profit": current_tp,
                "user_id": pos.user_id,
                "mode": pos.mode,
                "api_key_id": pos.api_key_id,  # Added api_key_id with fallback
                "market_type": self._market_type_for_position(pos),
                "is_stop_at_be": getattr(pos, "is_stop_at_be", False),
                "signal_details_json": pos.signal_details,  # Decision trace for foundation analytics
                "executions": list(pos.execution_events)
                if hasattr(pos, "execution_events")
                else [],
                "partial_tp_orders": [ptp.to_dict() for ptp in pos.partial_tp_orders]
                if hasattr(pos, "partial_tp_orders")
                else [],
                "dca_orders": [dca.to_dict() for dca in pos.dca_orders]
                if hasattr(pos, "dca_orders")
                else [],
            }

            positions_to_publish.append(pos_data)

        # 2. Collecting data about STRATEGIES
        strategies_to_publish = []
        async with self.instances_lock:
            instances_copy = dict(self.running_strategy_instances)

        for config_id, (instance, config_dict) in instances_copy.items():
            symbols_str = "Dynamic (All)"
            if config_dict.get("symbol_selection_mode") == "STATIC":
                symbols_list = config_dict.get("symbols", [])
                symbols_str = ", ".join(symbols_list) if symbols_list else "None"

            # Strategy PnL = Realized (from RM) + Unrealized (from current positions)
            realized_pnl = self.rm.get_pnl_for_strategy(
                symbol=None, strategy_name=instance.NAME
            )

            unrealized_pnl_strat = 0.0
            instance_open_positions = 0
            for pos in active_positions_copy:
                if pos.config_id == config_id:
                    unrealized_pnl_strat += position_pnl_cache.get(
                        pos.entry_client_order_id, 0.0
                    )
                    instance_open_positions += 1

            total_instance_pnl = realized_pnl + unrealized_pnl_strat

            # Fallback for strategies
            strat_api_key_id = config_dict.get("api_key_id")
            if strat_api_key_id is None:
                strat_api_key_id = self.api_key_id
                # Optional: Persist back to dict so we don't check every time (race condition safe as it's a dict read)
                config_dict["api_key_id"] = self.api_key_id

            strat_data = {
                "id": config_id,
                "strategy_name": instance.NAME,
                "symbol": symbols_str,
                "market_type": config_dict.get("config_data", {})
                .get("marketType", "PAPER")
                .lower(),
                "status": "in_position" if instance_open_positions > 0 else "running",
                "pnl": round(total_instance_pnl, 4),
                "open_positions": instance_open_positions,
                "started_at": config_dict.get(
                    "started_at", datetime.now(timezone.utc).isoformat()
                ),
                "params": config_dict.get("config_data", {}).get("params", {}),
                "user_id": config_dict.get("user_id"),
                "api_key_id": strat_api_key_id,  # Added api_key_id with fallback
                "symbol_selection_mode": config_dict.get(
                    "symbol_selection_mode", "STATIC"
                ),
                "mode": config_dict.get("mode", "live"),
            }
            strategies_to_publish.append(strat_data)

        # 3. Collecting PORTFOLIO data
        # Getting balance from RiskManager
        wallet_balance = self.rm.stats.current_balance  # Wallet balance (without PnL)
        equity = wallet_balance + total_unrealized_pnl  # Equity (including PnL)

        portfolio_status_data = {
            "user_id": self.user_id,
            "total_wallet_balance": round(wallet_balance, 2),
            "total_unrealized_pnl": round(total_unrealized_pnl, 2),
            "total_equity": round(equity, 2),
            "today_pnl": round(self.rm.stats.today_pnl, 2),
            "consecutive_losses": self.rm.stats.consecutive_losses,
            "is_trading_allowed": getattr(self.rm, "_is_trading_allowed", True),
            "margin_usage_percent": 0.0,
            "active_positions_count": len(positions_to_publish),
            "active_strategies_count": len(strategies_to_publish),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        # If there is data on used margin in RM, use it
        if hasattr(self.rm, "allocated_margin"):
            portfolio_status_data["margin_usage_percent"] = (
                round((self.rm.allocated_margin / wallet_balance) * 100, 2)
                if wallet_balance > 0
                else 0.0
            )

        # 4. Publishing to Redis
        try:
            async with self.redis_client.pipeline() as pipe:
                # IMPORTANT: Using keys with user_id AND api_key_id for data isolation between controllers!
                # This prevents data from one controller being overwritten by another (race condition).
                # New Format: key:user_id:api_key_id
                key_pos = f"{config.REDIS_STATE_KEY_POSITIONS}:{self.user_id}:{self.api_key_id}"
                key_strat = f"{config.REDIS_STATE_KEY_STRATEGIES}:{self.user_id}:{self.api_key_id}"
                key_port = f"{getattr(config, 'REDIS_STATE_KEY_PORTFOLIO', 'depthsight:state:portfolio')}:{self.user_id}:{self.api_key_id}"

                pipe.set(key_pos, json.dumps(positions_to_publish))
                pipe.set(key_strat, json.dumps(strategies_to_publish))
                pipe.set(key_port, json.dumps(portfolio_status_data))

                # Notifications - using user-scoped channels for isolation
                notification_payload = json.dumps({"user_id": self.user_id})
                pipe.publish(
                    f"depthsight:events:positions:{self.user_id}", notification_payload
                )
                pipe.publish(
                    f"depthsight:events:strategies:{self.user_id}", notification_payload
                )
                pipe.publish(
                    f"depthsight:events:portfolio:{self.user_id}", notification_payload
                )

                await pipe.execute()

            # logger.debug(f"Published state (Pos, Strat, Port) to Redis for user {self.user_id}.")
        except Exception as e:
            logger.error(
                f"Failed to publish state to Redis for user {self.user_id}: {e}",
                exc_info=True,
            )

    async def reload_user_app_config(self):
        """
        Reloads the general AppConfig for the user from the database.
        Updates Telegram Chat ID and Risk Manager settings dynamically.
        """
        log_prefix = "[ReloadUserAppConfig]"
        try:
            async for db in self.get_db_session():
                app_config = await crud.get_config(db, user_id=self.user_id)
                if app_config:
                    # 1. Update Notifications (Telegram Chat ID)
                    # app_config.notifications is a dict (JSON column)
                    notif_settings = self._config_section_to_dict(
                        app_config.notifications
                    )
                    if self.rm:
                        runtime_settings = {
                            "risk_management": self._config_section_to_dict(
                                app_config.risk_management
                            ),
                            "backtest_risk_management": self._config_section_to_dict(
                                app_config.backtest_risk_management
                            ),
                            "notifications": notif_settings,
                        }
                        prev_chat_id = self.user_telegram_chat_id
                        self.rm.apply_user_settings(runtime_settings)
                        self.user_telegram_chat_id = self.rm.user_telegram_chat_id
                        if prev_chat_id != self.user_telegram_chat_id:
                            logger.info(
                                f"{log_prefix} Telegram Chat ID changed for user {self.user_id}. Updating."
                            )
                    new_chat_id = notif_settings.get("telegramChatId")

                    if new_chat_id and new_chat_id != self.user_telegram_chat_id:
                        logger.info(
                            f"{log_prefix} Telegram Chat ID changed for user {self.user_id}. Updating."
                        )
                        self.user_telegram_chat_id = new_chat_id
                        if self.rm:
                            self.rm.user_telegram_chat_id = new_chat_id

                else:
                    logger.warning(
                        f"{log_prefix} Could not load AppConfig for user {self.user_id}."
                    )

                break  # Break after one successful load

        except Exception as e:
            logger.error(
                f"{log_prefix} Failed to reload user app config: {e}", exc_info=True
            )

    async def _run_config_reloader(self):
        """Periodically checks and reloads optimized parameters and symbol selection settings."""
        reload_interval = self._config_reload_interval
        logger.info(f"Config reloader task started (Interval: {reload_interval}s).")
        while self._running:
            try:
                await asyncio.sleep(reload_interval)
            except asyncio.CancelledError:
                logger.info("Config reloader task cancelled during sleep.")
                break
            if not self._running:
                logger.info(
                    "Config reloader task exiting because controller is stopped."
                )
                break
            try:
                # 1. Reload optimized params (static/global)
                config.load_optimized_params()

                # 2. Reload user symbol selection config
                config_changed = await self.load_symbol_selection_config()
                await self._apply_symbol_selection_config_change(config_changed)

                # 3. Reload general User App Config (Notifications, Risk)
                await self.reload_user_app_config()

            except asyncio.CancelledError:
                logger.info("Config reloader task cancelled.")
                break
            except Exception as e:
                logger.error(f"Error reloading config: {e}", exc_info=True)
        logger.info("Config reloader task finished.")

    async def _run_market_info_updater(self):
        """Periodically updates the market information cache."""
        update_interval = self._market_info_update_interval
        logger.info(f"Market info updater task started (Interval: {update_interval}s).")
        while self._running:
            try:
                await asyncio.sleep(update_interval)
            except asyncio.CancelledError:
                logger.info("Market info updater task cancelled during sleep.")
                break
            if not self._running:
                logger.info(
                    "Market info updater task exiting because controller is stopped."
                )
                break
            try:
                logger.info("Running periodic market info update...")
                await self._update_market_info_cache(force=True)
            except asyncio.CancelledError:
                logger.info("Market info updater task cancelled.")
                break
            except Exception as e:
                logger.error(f"Error updating market info cache: {e}", exc_info=True)
        logger.info("Market info updater task finished.")

    async def _run_equity_recorder(self):
        """Periodically writes an equity point to Redis for plotting on the dashboard."""
        log_prefix = f"[EquityRecorder:user_{self.user_id}]"
        logger.info(
            f"{log_prefix} Equity recorder task started (Interval: {self._equity_recording_interval}s)."
        )

        while self._running:
            try:
                await asyncio.sleep(self._equity_recording_interval)
            except asyncio.CancelledError:
                logger.info(
                    f"{log_prefix} Equity recorder task cancelled during sleep."
                )
                break

            if not self._running:
                logger.info(
                    f"{log_prefix} Equity recorder task exiting because controller is stopped."
                )
                break

            try:
                # Recording equity point for paper mode
                paper_executor = self.executors.get("paper")
                if paper_executor and hasattr(paper_executor, "_record_equity_point"):
                    await paper_executor._record_equity_point()
                    logger.debug(
                        f"{log_prefix} Recorded periodic equity point for paper mode."
                    )

                # TODO: Can add a record for live mode if a live balance chart is needed
            except asyncio.CancelledError:
                logger.info(f"{log_prefix} Equity recorder task cancelled.")
                break
            except Exception as e:
                logger.error(
                    f"{log_prefix} Error recording equity point: {e}", exc_info=True
                )

        logger.info(f"{log_prefix} Equity recorder task finished.")

    async def _handle_event_with_context(self, event: Dict[str, Any]):
        """Wrapper to set user_id context for logging around event handling."""
        from bot_module.redis_handler import user_id_context

        token = user_id_context.set(self.user_id)
        try:
            async with self._event_handler_semaphore:
                await self._handle_event(event)
        finally:
            user_id_context.reset(token)

    async def _run_main_loop(self):
        """Main event loop of the controller."""
        logger.info("Controller event loop started.")
        # Periodic tasks remain but are started separately
        self.loop.create_task(
            self._run_periodic_tasks(), name="ControllerPeriodicTasks"
        )

        while self._running:
            try:
                # Blocking wait for a new event (tick or candle close)
                event = await self.event_queue.get()

                # Starting event processing in a separate task WITH CONTEXT
                self.loop.create_task(
                    self._handle_event_with_context(event),
                    name=f"HandleEvent_{event.get('type')}_{event.get('symbol')}",
                )

            except asyncio.CancelledError:
                logger.info("Controller event loop cancelled.")
                break
            except Exception as e:
                logger.critical(
                    f"Critical error in controller event loop: {e}", exc_info=True
                )
                await asyncio.sleep(5)  # Pause in case of a critical error

        logger.info("Controller event loop finished.")

    async def _run_periodic_tasks(self):
        """Performs tasks that should run on a timer rather than on events."""
        from bot_module.redis_handler import user_id_context

        last_symbol_check_time = 0
        symbol_check_interval = 5

        last_pending_entry_check_time = 0

        last_state_publish_time = 0
        state_publish_interval = 2

        last_rm_save_time = 0
        rm_save_interval = 30

        # Initializing variables for reconciliation
        last_reconcile_time = 0
        reconcile_interval = (
            60  # Reconciliation once per minute (sufficient for prevention)
        )

        while self._running:
            token = user_id_context.set(self.user_id)
            try:
                now = time.monotonic()
                # On every tick of the periodic task, check pending orders in paper mode
                if self.executors.get("paper"):
                    self.loop.create_task(
                        self.executors["paper"].check_open_orders(),
                        name=f"PeriodicPaperOrderCheck_User{self.user_id}",
                    )

                # 1. Checking symbol list updates
                if now - last_symbol_check_time >= symbol_check_interval:
                    await self._check_and_update_symbols()
                    last_symbol_check_time = now

                # 2. Checking "stale" limit orders
                if (
                    now - last_pending_entry_check_time
                    >= config.PENDING_ENTRY_CHECK_INTERVAL_SECONDS
                ):
                    await self._check_and_manage_pending_entry_orders()
                    last_pending_entry_check_time = now

                # 3. Checking positions without stop-losses
                if (
                    now - self._last_missing_sl_check_time
                    >= self.missing_sl_check_interval
                ):
                    await self._check_and_close_positions_without_sl()
                    self._last_missing_sl_check_time = now

                # 4. Publishing state to Redis
                if now - last_state_publish_time >= state_publish_interval:
                    await self._publish_state_to_redis()
                    # Save the full state for recovery
                    await self._save_runtime_state()
                    last_state_publish_time = now

                # 5. Saving Risk Manager state
                if now - last_rm_save_time >= rm_save_interval:
                    await self.rm.save_state()
                    last_rm_save_time = now

                # 6. Periodic reconciliation with the exchange (protection against duplicates)
                if now - last_reconcile_time >= reconcile_interval:
                    # Run in background to avoid blocking the loop
                    self.loop.create_task(
                        self._reconcile_positions_with_exchange(),
                        name=f"PeriodicReconcile_{self.user_id}",
                    )
                    last_reconcile_time = now

            except Exception as e:
                logger.error(f"Error in periodic tasks loop: {e}", exc_info=True)
            finally:
                user_id_context.reset(token)

            await asyncio.sleep(1)

    async def _dynamic_symbol_selection_loop(self):
        """
        New bot brain. This asyncio.Task will run in parallel with the main run loop.
        It is triggered every time a new active_pairs_update message arrives from DataConsumer.
        """
        from bot_module.redis_handler import user_id_context

        log_prefix = "[DynamicSymbolSelection]"
        logger.info(f"{log_prefix} Dynamic symbol selection loop started.")

        while self._running:
            token = user_id_context.set(self.user_id)
            try:
                # Waiting for a new list from the screener
                screener_data = await self._screener_update_queue.get()
                try:
                    self.full_screener_list = screener_data.get("data", [])

                    # Calculating statistics by oracle modes
                    oracle_stats = {}
                    for symbol_data in self.full_screener_list:
                        regime = symbol_data.get("oracle_regime")
                        if regime is not None:
                            oracle_stats[regime] = oracle_stats.get(regime, 0) + 1

                    # Generating string with statistics
                    oracle_stats_str = ", ".join(
                        [
                            f"Regime {r}: {count}"
                            for r, count in sorted(oracle_stats.items())
                        ]
                    )
                    logger.info(
                        f"{log_prefix} Received screener update: {len(self.full_screener_list)} symbols. Oracle stats: [{oracle_stats_str}]"
                    )

                    # Breakeven check when changing mode
                    # Create a dictionary for fast lookup by symbol
                    screener_map = {
                        item["symbol"]: item for item in self.full_screener_list
                    }

                    # Get the list of active symbols in a safe manner
                    async with self._positions_dict_lock:
                        active_positions_for_check = list(
                            self._active_positions.values()
                        )

                    for position_snapshot in active_positions_for_check:
                        symbol = position_snapshot.symbol
                        # Getting the position for reading
                        position_for_check = None
                        symbol_lock_check = self._get_lock_for_position(
                            symbol, self._market_type_for_position(position_snapshot)
                        )
                        async with symbol_lock_check:
                            pos = self._active_position_get(
                                symbol,
                                self._market_type_for_position(position_snapshot),
                            )
                            if pos and pos.status == "OPEN":
                                position_for_check = pos

                        if not position_for_check:
                            continue

                        # Finding the strategy instance
                        strategy_instance = None
                        if position_for_check.config_id:
                            async with self.instances_lock:
                                instance_tuple = self.running_strategy_instances.get(
                                    position_for_check.config_id
                                )
                                if instance_tuple:
                                    strategy_instance = instance_tuple[0]

                        # Checking the strategy condition
                        if strategy_instance and symbol in screener_map:
                            # Use the current price from consumer, not the outdated one from screener
                            # The screener is updated every 3 minutes, so its price may be outdated
                            live_pair_info = (
                                await self.consumer.get_active_pair_by_symbol(symbol)
                            )

                            # Enriching screener_data with current price
                            enriched_screener_data = screener_map[symbol].copy()
                            if live_pair_info and live_pair_info.get("last_price"):
                                enriched_screener_data["close"] = live_pair_info[
                                    "last_price"
                                ]
                                enriched_screener_data["last_price"] = live_pair_info[
                                    "last_price"
                                ]
                                logger.debug(
                                    f"{log_prefix} [{symbol}] Using live price {live_pair_info['last_price']} instead of screener price {screener_map[symbol].get('close')}"
                                )

                            action_type, action_value = (
                                strategy_instance.check_on_screener_update(
                                    position_for_check, enriched_screener_data
                                )
                            )

                            if action_type == "CLOSE_POSITION":
                                logger.warning(
                                    f"{log_prefix} [{symbol}] Strategy signaled IMMEDIATE CLOSE due to Regime Change (Losing trade)."
                                )
                                self.loop.create_task(
                                    self.close_position(
                                        symbol,
                                        reason="REGIME_CHANGE_LOSS_CUT",
                                        market_type=self._market_type_for_position(
                                            position_for_check
                                        ),
                                    ),
                                    name=f"RegimeChangeClose_{symbol}",
                                )

                            elif action_type == "MOVE_SL":
                                new_sl_price = action_value
                                logger.info(
                                    f"{log_prefix} [{symbol}] Strategy signaled Breakeven on Regime Change (Winning trade). Moving SL to {new_sl_price}"
                                )

                                success = await self._replace_stop_loss(
                                    symbol,
                                    new_sl_price,
                                    market_type=self._market_type_for_position(
                                        position_for_check
                                    ),
                                )

                                if success:
                                    symbol_lock_after = self._get_lock_for_position(
                                        symbol,
                                        self._market_type_for_position(
                                            position_for_check
                                        ),
                                    )
                                    async with symbol_lock_after:
                                        pos_after = self._active_position_get(
                                            symbol,
                                            self._market_type_for_position(
                                                position_for_check
                                            ),
                                        )
                                        if pos_after:
                                            pos_after.is_stop_at_be = True

                                    if self.telegram_notifier:
                                        tick_size = await self._get_market_info(
                                            symbol,
                                            "tick_size",
                                            market_type=self._market_type_for_position(
                                                position_for_check
                                            ),
                                        )
                                        self.loop.create_task(
                                            self.telegram_notifier.sl_moved_to_be(
                                                symbol=symbol,
                                                new_sl_price=new_sl_price,
                                                entry_price=position_for_check.entry_price,
                                                entry_client_order_id=position_for_check.entry_client_order_id,
                                                tick_size=tick_size,
                                                chat_id=self.user_telegram_chat_id,
                                                market_type=self._market_type_for_position(
                                                    position_for_check
                                                ),
                                                leverage=self._leverage_for_position(
                                                    position_for_check
                                                ),
                                                reason="Oracle Regime Change (Regime Change)",
                                                api_key_name=self.api_key_name,
                                            ),
                                            name=f"NotifyRegimeChangeBE_{symbol}",
                                        )
                                else:
                                    # Notification about move error
                                    logger.error(
                                        f"{log_prefix} [{symbol}] Failed to move SL to BE on Regime Change!"
                                    )
                                    if self.telegram_notifier:
                                        self.loop.create_task(
                                            self.telegram_notifier.bot_error(
                                                error_description=f"Failed to move SL to BE when changing Oracle mode for {symbol}.",
                                                module_function="_dynamic_symbol_selection_loop",
                                                action_taken=f"Attempting to set SL {new_sl_price}. The position remains with the old stop.",
                                                chat_id=self.user_telegram_chat_id,
                                                api_key_name=self.api_key_name,
                                            ),
                                            name=f"NotifyRegimeChangeBE_Fail_{symbol}",
                                        )

                    if not self.full_screener_list:
                        logger.warning(
                            f"{log_prefix} Received empty screener list. No symbols to process."
                        )
                        # If the list is empty, it might be necessary to stop managing all symbols
                        await self._stop_managing_all_symbols()
                        # continue - remove continue to reach finally

                    else:
                        # Applying filtering logic depending on self.symbol_selection_config.mode
                        mode = self.symbol_selection_config.mode
                        filtered_and_sorted_symbols: List[Dict[str, Any]] = []

                        if mode == "STATIC":
                            # In static mode, we do nothing; symbols are managed manually via strategies
                            # But we must ensure that _currently_managed_symbols matches what the strategies want
                            # This will be handled in _update_monitored_symbols
                            logger.debug(
                                f"{log_prefix} Mode is STATIC. Skipping dynamic filtering."
                            )
                            # For STATIC mode, desired_symbols_set will be formed from the running strategies
                            # in _update_monitored_symbols. Here we just skip.
                            pass  # continue replaced with pass
                        elif mode == "DYNAMIC_NATR":
                            logger.debug(
                                f"{log_prefix} Mode is DYNAMIC_NATR. Filtering by min_natr={self.symbol_selection_config.min_natr}"
                            )
                            min_natr = self.symbol_selection_config.min_natr
                            filtered_and_sorted_symbols = [
                                s
                                for s in self.full_screener_list
                                if s.get("NATR 1/30 (1m)", 0.0) >= min_natr
                            ]
                            filtered_and_sorted_symbols.sort(
                                key=lambda x: x.get("NATR 1/30 (1m)", 0.0), reverse=True
                            )
                        elif mode == "DYNAMIC_ORACLE":
                            required_regime = self.symbol_selection_config.oracle_regime
                            # IMPORTANT: oracle_confidence in settings is in percent (0-100),
                            # and from the screener it comes in fractions (0-1). Normalizing!
                            min_confidence_raw = (
                                self.symbol_selection_config.oracle_confidence or 0.0
                            )
                            min_confidence = (
                                min_confidence_raw / 100.0
                                if min_confidence_raw > 1
                                else min_confidence_raw
                            )
                            logger.debug(
                                f"{log_prefix} Mode is DYNAMIC_ORACLE. Filtering by regime={required_regime}, confidence>={min_confidence} (raw: {min_confidence_raw})"
                            )
                            filtered_and_sorted_symbols = [
                                s
                                for s in self.full_screener_list
                                if s.get("oracle_regime") == required_regime
                                and s.get("oracle_confidence", 0.0) >= min_confidence
                            ]
                            # Sort by NATR (volatility) to select the most active coins within the mode
                            filtered_and_sorted_symbols.sort(
                                key=lambda x: x.get("NATR 1/30 (1m)", 0.0), reverse=True
                            )
                        else:
                            logger.warning(
                                f"{log_prefix} Unknown symbol selection mode: {mode}. Skipping dynamic filtering."
                            )
                            # continue

                        if (
                            filtered_and_sorted_symbols or mode == "STATIC"
                        ):  # Only proceed if we have symbols or we skipped filtering
                            # Apply a limit on the number of simultaneous symbols
                            max_concurrent = (
                                self.symbol_selection_config.max_concurrent_symbols
                            )
                            desired_symbols_set = {
                                s["symbol"]
                                for s in filtered_and_sorted_symbols[:max_concurrent]
                            }
                            logger.info(
                                f"{log_prefix} Desired symbols (top {max_concurrent}): {desired_symbols_set}"
                            )

                            # Synchronization with self.currently_managed_symbols
                            current_managed_set = self.currently_managed_symbols.copy()
                            changed = False

                            # New targets — batch all changes before calling _update_monitored_symbols
                            for symbol in desired_symbols_set:
                                if symbol not in current_managed_set:
                                    logger.info(
                                        f"{log_prefix} New target: {symbol}. Starting management."
                                    )
                                    self._last_known_symbols_from_consumer.add(symbol)
                                    changed = True

                            # Obsolete targets
                            for symbol in current_managed_set:
                                if symbol not in desired_symbols_set:
                                    logger.info(
                                        f"{log_prefix} Outdated target: {symbol}. Stopping management."
                                    )
                                    if symbol in self._last_known_symbols_from_consumer:
                                        self._last_known_symbols_from_consumer.remove(
                                            symbol
                                        )
                                    changed = True

                            if changed:
                                await self._update_monitored_symbols()

                            self.currently_managed_symbols = desired_symbols_set.copy()
                            logger.info(
                                f"{log_prefix} Currently managed symbols: {self.currently_managed_symbols}"
                            )

                finally:
                    self._screener_update_queue.task_done()

            except asyncio.CancelledError:
                logger.info(f"{log_prefix} Dynamic symbol selection loop cancelled.")
                break
            except Exception as e:
                logger.error(
                    f"{log_prefix} Error in dynamic symbol selection loop: {e}",
                    exc_info=True,
                )
                await asyncio.sleep(5)  # Pause in case of error
            finally:
                user_id_context.reset(token)

        logger.info(f"{log_prefix} Dynamic symbol selection loop finished.")

    async def start_managing_symbol(self, symbol: str):
        """
        Starts managing the symbol: subscribes to data and allows strategies to work.
        """
        log_prefix = f"[ManageSymbol:{symbol}]"
        logger.info(f"{log_prefix} Starting to manage symbol.")
        # Adding the symbol to _last_known_symbols_from_consumer so that _update_monitored_symbols picks it up
        self._last_known_symbols_from_consumer.add(symbol)
        await self._update_monitored_symbols()
        # Here you can add logic to start strategies if they are in DYNAMIC mode
        # But for now, strategies pick up symbols from _last_known_symbols_from_consumer themselves

    async def stop_managing_symbol(self, symbol: str):
        """
        Stops searching for new entries for the symbol.
        IF there is an open position — leaves it to finish (moving it to managed close mode).
        """
        log_prefix = f"[ManageSymbol:{symbol}]"
        logger.info(
            f"{log_prefix} Stopping management of symbol (removing from dynamic selection)."
        )

        # Remove the symbol from the list so that strategies no longer open NEW positions
        if symbol in self._last_known_symbols_from_consumer:
            self._last_known_symbols_from_consumer.remove(symbol)

        # Do not force close the position!
        async with self._positions_dict_lock:
            if self._active_positions_for_symbol(symbol):
                # Position exists. We do NOT close it.
                # We simply allow _update_monitored_symbols to move it to _closing_managed_symbols.
                # This will preserve the data subscription (candles/order book), and manage_position will continue to work.
                logger.info(
                    f"{log_prefix} Open position exists. It will be maintained in 'closing_managed' mode until SL/TP/BE hit."
                )

                # Note: The logic for moving to BE when changing mode has already executed
                # in _dynamic_symbol_selection_loop BEFORE calling this method.
            else:
                logger.debug(f"{log_prefix} No open position. Clean stop.")

        # Updating subscriptions will do all the magic (move to managed close or unsubscribe)
        await self._update_monitored_symbols()

    async def _stop_managing_all_symbols(self):
        """Stops management of all symbols, for example, when the screener list is empty."""
        log_prefix = "[ManageSymbol:ALL]"
        logger.info(
            f"{log_prefix} Stopping management of all currently managed symbols."
        )

        symbols_to_stop = list(self.currently_managed_symbols)
        for symbol in symbols_to_stop:
            await self.stop_managing_symbol(symbol)

        self.currently_managed_symbols.clear()
        self._last_known_symbols_from_consumer.clear()
        await self._update_monitored_symbols()

    async def _handle_event(self, event):
        """Processes a single event from the queue."""
        event_type = event.get("type")
        symbol = event.get("symbol")
        if not symbol:
            return
        event_market_type = self._normalize_market_type(event.get("market_type"))
        event_has_market_type = bool(event.get("market_type"))

        # DEBUG level — events that are too frequent (every aggTrade tick)
        logger.debug(f"[HEARTBEAT] Received event '{event_type}' for symbol {symbol}")
        if event_type == "CANDLE_CLOSE":
            logger.info(
                "[ControllerEvent:%s] Received CANDLE_CLOSE timeframe=%s market_type=%s timestamp_ms=%s",
                symbol,
                event.get("timeframe"),
                event_market_type,
                event.get("timestamp_ms"),
            )

        if event_type == "TICK":
            tick_price = event.get("price")
            if tick_price is not None:
                await self._check_spot_virtual_tp_triggers(
                    symbol,
                    high_price=float(tick_price),
                    low_price=float(tick_price),
                    last_price=float(tick_price),
                )

        # 1. Open position management (by candle close or forced recalculation after DCA)
        if event_type in ("CANDLE_CLOSE", "SCALE_IN_RECALC"):
            position_to_manage = None
            strategy_instance = None
            strategy_config_dict = (
                None  # strategy configuration to get the trading timeframe
            )
            pair_info = None  # Initialize to avoid UnboundLocalError in Phantom block

            symbol_lock_mgmt = self._get_lock_for_position(
                symbol, event_market_type if event_has_market_type else None
            )
            async with symbol_lock_mgmt:
                position = self._active_position_get(
                    symbol, event_market_type if event_has_market_type else None
                )
                if position and position.status == "OPEN":
                    position_market_type = self._market_type_for_position(position)
                    if (
                        event_has_market_type
                        and position_market_type != event_market_type
                    ):
                        logger.debug(
                            f"[PositionMgmt:{symbol}] Skipping {position_market_type} position on {event_market_type} event."
                        )
                    else:
                        position_to_manage = LivePosition(**vars(position))
                    if position.config_id:
                        async with self.instances_lock:
                            instance_tuple = self.running_strategy_instances.get(
                                position.config_id
                            )
                            if instance_tuple:
                                strategy_instance = instance_tuple[0]
                                strategy_config_dict = instance_tuple[
                                    1
                                ]  # NEW: extracting config_dict

            # Log why strategy_instance might be None
            if position_to_manage and not strategy_instance:
                logger.warning(
                    f"[PositionMgmt:{symbol}] Position exists but no strategy_instance found. "
                    f"config_id={getattr(position_to_manage, 'config_id', 'N/A')}, "
                    f"strategy={getattr(position_to_manage, 'strategy', 'N/A')}. "
                    f"Position management will NOT run for this position!"
                )

            if position_to_manage and strategy_instance:
                log_prefix_pm = f"[PositionMgmt:{symbol}]"
                logger.debug(f"{log_prefix_pm} Checking position ...")

                pair_info = await self.consumer.get_active_pair_by_symbol(symbol)
                if pair_info:
                    position_market_type = self._market_type_for_position(
                        position_to_manage
                    )
                    pair_info["market_type"] = position_market_type
                    market_data = await self._gather_market_data_for_strategy(
                        strategy_instance, symbol, market_type=position_market_type
                    )

                    if market_data is not None:
                        # Use the TRADING timeframe from the strategy configuration
                        # Previously, the timeframe was taken from the event, which could result in a 5m filter instead of a 1m trading TF

                        # 1. Determine the trading timeframe from the strategy configuration
                        trading_timeframe = "1m"  # Default
                        if strategy_config_dict:
                            entry_trigger = strategy_config_dict.get(
                                "config_data", {}
                            ).get("entryTrigger", {})
                            trading_timeframe = entry_trigger.get("timeframe", "1m")

                        # Log if the event timeframe differs from the trading one
                        event_timeframe = event.get("timeframe", "1m")
                        if event_timeframe != trading_timeframe:
                            logger.debug(
                                f"{log_prefix_pm} Event TF ({event_timeframe}) differs from trading TF ({trading_timeframe}). "
                                f"Using trading TF for position management."
                            )

                        # 2. Find the DataFrame with candles of the TRADING timeframe
                        kline_key = f"kline_{trading_timeframe}"
                        candles_df = market_data.get(kline_key)

                        # 2. If candles exist, take the last one and enrich pair_info
                        if candles_df is not None and not candles_df.empty:
                            last_candle = candles_df.iloc[-1]
                            pair_info.update(
                                last_candle.to_dict()
                            )  # Adding open, high, low, close...

                            # timestamp_dt is often an index, not a column
                            # to_dict() does not include the index, so timestamp_dt might be missing
                            if "timestamp_dt" not in pair_info:
                                # Trying to get from the DataFrame index (usually it's open_time)
                                try:
                                    candle_timestamp = candles_df.index[-1]
                                    if hasattr(candle_timestamp, "to_pydatetime"):
                                        pair_info["timestamp_dt"] = (
                                            candle_timestamp.to_pydatetime()
                                        )
                                    else:
                                        pair_info["timestamp_dt"] = candle_timestamp
                                    logger.debug(
                                        f"{log_prefix_pm} Added timestamp_dt={pair_info['timestamp_dt']} from DataFrame index."
                                    )
                                except Exception as e_ts:
                                    logger.warning(
                                        f"{log_prefix_pm} Could not extract timestamp_dt from index: {e_ts}"
                                    )

                            logger.debug(
                                f"{log_prefix_pm} Enriched pair_info with last candle data for trading TF {trading_timeframe}."
                            )
                        else:
                            logger.warning(
                                f"{log_prefix_pm} Could not find kline data for '{kline_key}' in market_data. 'pair_info' will be incomplete for manage_position."
                            )

                        # Adding tick_size to pair_info
                        # Without tick_size, the _handle_move_to_breakeven function cannot work
                        if "tick_size" not in pair_info:
                            tick_size = await self._get_market_info(
                                symbol,
                                "tick_size",
                                market_type=self._market_type_for_position(
                                    position_to_manage
                                ),
                            )
                            if tick_size:
                                pair_info["tick_size"] = tick_size
                                logger.debug(
                                    f"{log_prefix_pm} Added tick_size={tick_size} to pair_info for position management."
                                )
                            else:
                                logger.warning(
                                    f"{log_prefix_pm} Could not get tick_size for {symbol}. Breakeven logic may not work!"
                                )

                        # Indicating that this is live mode
                        # In live mode, SL/TP orders are executed on the exchange,
                        # therefore manage_position MUST NOT return exit_details for them
                        pair_info["is_live_mode"] = True

                        virtual_tp_triggered = (
                            await self._check_spot_virtual_tp_triggers(
                                symbol,
                                high_price=pair_info.get("high")
                                or pair_info.get("last_price")
                                or pair_info.get("close"),
                                low_price=pair_info.get("low")
                                or pair_info.get("last_price")
                                or pair_info.get("close"),
                                last_price=pair_info.get("last_price")
                                or pair_info.get("close"),
                            )
                        )
                        if virtual_tp_triggered:
                            return

                        # Adapter for compatibility (leave as is)
                        compatible_pos = copy.deepcopy(position_to_manage)

                        # 2. Add/replace attributes so they match the backtester's expectations.
                        #    - `partial_targets` instead of `partial_tp_orders`
                        #    - `partial_fills` and `executions` that are not in LivePosition

                        # Convert the list of PartialTpOrderInfo objects into a list of tuples, as in the backtester
                        compatible_pos.partial_targets = [
                            (
                                ptp.target_price,
                                ptp.orig_fraction,
                                ptp.status == "FILLED",
                            )
                            for ptp in getattr(compatible_pos, "partial_tp_orders", [])
                        ]
                        compatible_pos.partial_fills = []  # Simulating an empty list
                        compatible_pos.executions = []  # Simulating an empty list

                        # 3. Calling manage_position with a compatible object
                        (
                            updated_pos_obj,
                            exit_details,
                        ) = await strategy_instance.manage_position(
                            compatible_pos,
                            pair_info,
                            market_data,
                            None,  # Now pair_info contains candle data
                        )

                        # What manage_position returned
                        logger.warning(
                            f"{log_prefix_pm} [PM_RETURN] is_stop_at_be={getattr(updated_pos_obj, 'is_stop_at_be', 'N/A')}, "
                            f"current_sl={updated_pos_obj.current_sl_price}, "
                            f"be_reason={getattr(updated_pos_obj, 'be_trigger_reason', 'N/A')}"
                        )

                        # A. Processing EXIT signal
                        if exit_details:
                            logger.info(
                                f"{log_prefix_pm} Strategy signaled EXIT. Reason: {exit_details.get('reason')}. Closing position."
                            )
                            self.loop.create_task(
                                self.close_position(
                                    symbol,
                                    reason=exit_details["reason"],
                                    market_type=self._market_type_for_position(
                                        position_to_manage
                                    ),
                                ),
                                name=f"StrategyMgmtClose_{symbol}",
                            )
                            return  # Exiting because the position is closing

                        # B. Process the SCALING signal (if any)
                        # B.1 Processing DCA grid initialization
                        if (
                            hasattr(updated_pos_obj, "dca_grid_init_triggered")
                            and updated_pos_obj.dca_grid_init_triggered
                        ):
                            dca_params = updated_pos_obj.dca_grid_init_triggered
                            should_schedule_dca_grid = False
                            symbol_lock_dca = self._get_lock_for_position(
                                symbol,
                                self._market_type_for_position(position_to_manage),
                            )
                            async with symbol_lock_dca:
                                real_pos = self._active_position_get(
                                    symbol,
                                    self._market_type_for_position(position_to_manage),
                                )
                                if (
                                    real_pos
                                    and not real_pos.dca_order_ids
                                    and not getattr(
                                        real_pos, "dca_grid_init_in_progress", False
                                    )
                                ):
                                    real_pos.dca_grid_init_triggered = None
                                    real_pos.dca_grid_init_in_progress = True
                                    position_to_manage = LivePosition(**vars(real_pos))
                                    should_schedule_dca_grid = True
                            if should_schedule_dca_grid:
                                logger.info(
                                    f"{log_prefix_pm} Strategy signaled DCA_GRID_INIT. Params: {dca_params}"
                                )
                                self.loop.create_task(
                                    self._execute_dca_grid(
                                        position_to_manage, dca_params, pair_info
                                    ),
                                    name=f"ExecuteDCAGridInit_{symbol}",
                                )

                        # B.2 Processing the signal for GRID INITIALIZATION (if any)
                        if (
                            hasattr(updated_pos_obj, "grid_init_triggered")
                            and updated_pos_obj.grid_init_triggered
                        ):
                            grid_params = updated_pos_obj.grid_init_triggered
                            logger.info(
                                f"{log_prefix_pm} Strategy signaled GRID_INIT. Params: {grid_params}"
                            )
                            self.loop.create_task(
                                self._execute_grid_ladder(
                                    position_to_manage, grid_params
                                ),
                                name=f"ExecuteGridInit_{symbol}",
                            )
                            symbol_lock_grid = self._get_lock_for_position(
                                symbol,
                                self._market_type_for_position(position_to_manage),
                            )
                            async with symbol_lock_grid:
                                real_pos = self._active_position_get(
                                    symbol,
                                    self._market_type_for_position(position_to_manage),
                                )
                                if real_pos:
                                    real_pos.grid_init_triggered = None

                        if (
                            hasattr(updated_pos_obj, "scale_in_triggered")
                            and updated_pos_obj.scale_in_triggered
                        ):
                            add_size_pct = updated_pos_obj.scale_in_triggered.get(
                                "add_size_pct"
                            )
                            logger.info(
                                f"{log_prefix_pm} Strategy signaled SCALE-IN. Add size pct: {add_size_pct}"
                            )
                            self.loop.create_task(
                                self._execute_scale_in(
                                    position_to_manage, add_size_pct, pair_info
                                ),
                                name=f"ExecuteScaleIn_{symbol}",
                            )
                            symbol_lock_scale = self._get_lock_for_position(
                                symbol,
                                self._market_type_for_position(position_to_manage),
                            )
                            async with symbol_lock_scale:
                                real_pos = self._active_position_get(
                                    symbol,
                                    self._market_type_for_position(position_to_manage),
                                )
                                if real_pos:
                                    real_pos.scale_in_triggered = None

                        # B. Processing STOP-LOSS CHANGE
                        symbol_lock_sl_change = self._get_lock_for_position(
                            symbol, self._market_type_for_position(position_to_manage)
                        )
                        async with symbol_lock_sl_change:
                            current_pos = self._active_position_get(
                                symbol,
                                self._market_type_for_position(position_to_manage),
                            )
                            if current_pos and current_pos.status == "OPEN":
                                # Comparing our real stop with what the strategy returned
                                # Force SL replacement on SCALE_IN_RECALC to update quantity,
                                # or if the strategy explicitly moved the SL.
                                if (
                                    current_pos.current_sl_price
                                    != updated_pos_obj.current_sl_price
                                ) or event_type == "SCALE_IN_RECALC":
                                    logger.info(
                                        f"{log_prefix_pm} SL update needed (Price change or SCALE_IN_RECALC volume update). SL: {current_pos.current_sl_price} -> {updated_pos_obj.current_sl_price}"
                                    )

                                    self.loop.create_task(
                                        self._replace_stop_loss(
                                            symbol,
                                            updated_pos_obj.current_sl_price,
                                            market_type=self._market_type_for_position(
                                                current_pos
                                            ),
                                        ),
                                        name=f"StrategyMgmtMoveSL_{symbol}",
                                    )

                                # Moved OUTSIDE the SL price comparison block
                                # BE notification should be sent on any change of the is_stop_at_be flag,
                                # even if the SL hasn't physically moved (e.g., trailing has already moved past the breakeven point)

                                # Logging the state of BE flags
                                logger.info(
                                    f"{log_prefix_pm} [BE_DIAG] current_pos.is_stop_at_be={current_pos.is_stop_at_be}, "
                                    f"updated_pos_obj.is_stop_at_be={getattr(updated_pos_obj, 'is_stop_at_be', 'N/A')}, "
                                    f"SL: {current_pos.current_sl_price} -> {updated_pos_obj.current_sl_price}"
                                )

                                if (
                                    not current_pos.is_stop_at_be
                                    and updated_pos_obj.is_stop_at_be
                                ):
                                    if self.telegram_notifier:
                                        # Extract tick_size, it should be in pair_info
                                        ts_notify = pair_info.get("tick_size")

                                        # Using the real reason from the position if it is set
                                        be_reason = (
                                            getattr(
                                                updated_pos_obj,
                                                "be_trigger_reason",
                                                None,
                                            )
                                            or "Strategy Trigger (R:R / Trailing)"
                                        )

                                        # Getting diagnostic data for debugging
                                        be_diag_data = getattr(
                                            updated_pos_obj, "be_diagnostic_data", None
                                        )

                                        # Use the new SL (can be either modified or current)
                                        new_sl_for_notify = (
                                            updated_pos_obj.current_sl_price
                                        )

                                        self.loop.create_task(
                                            self.telegram_notifier.sl_moved_to_be(
                                                symbol=symbol,
                                                new_sl_price=new_sl_for_notify,
                                                entry_price=current_pos.entry_price,
                                                entry_client_order_id=current_pos.entry_client_order_id,
                                                tick_size=ts_notify,
                                                chat_id=self.user_telegram_chat_id,
                                                reason=be_reason,  # Using the real reason
                                                diagnostic_data=be_diag_data,
                                                market_type=self._market_type_for_position(
                                                    current_pos
                                                ),
                                                leverage=self._leverage_for_position(
                                                    current_pos
                                                ),
                                                api_key_name=self.api_key_name,
                                            ),
                                            name=f"NotifyStratBE_{symbol}",
                                        )

                                # Synchronize the break-even flag (important to do this AFTER checking the notification)
                                current_pos.is_stop_at_be = (
                                    updated_pos_obj.is_stop_at_be
                                )

                                # D. Processing TAKE-PROFIT CHANGE
                                # If the strategy changed the main TP OR we have no active TP orders (e.g., after averaging)
                                if updated_pos_obj.initial_take_profit is not None and (
                                    abs(
                                        (current_pos.initial_take_profit or 0)
                                        - updated_pos_obj.initial_take_profit
                                    )
                                    > 1e-9
                                    or not current_pos.partial_tp_orders
                                ):
                                    logger.info(
                                        f"{log_prefix_pm} Strategy signaled TP update or missing TP. Target: {updated_pos_obj.initial_take_profit}"
                                    )
                                    self.loop.create_task(
                                        self._replace_take_profit(
                                            symbol,
                                            updated_pos_obj.initial_take_profit,
                                            market_type=self._market_type_for_position(
                                                current_pos
                                            ),
                                            partial_targets=getattr(
                                                updated_pos_obj, "partial_targets", None
                                            ),
                                        ),
                                        name=f"StrategyMgmtUpdateTP_{symbol}",
                                    )
                    else:
                        logger.warning(
                            f"{log_prefix_pm} Could not gather market_data for {symbol}. Skipping position management."
                        )
                else:
                    logger.warning(
                        f"{log_prefix_pm} Could not get pair_info for {symbol}. Skipping position management."
                    )

        # 1.5 Lazy Phantom Trade Update (for BE analysis)
        # Only called when there's new kline data for this symbol
        # update() internally skips symbols without active phantoms (O(1) check per symbol)
        if config.PHANTOM_TRACKING_ENABLED and config.PHANTOM_TRACKING_MODE in (
            "live",
            "all",
        ):
            try:
                phantom_tracker = get_phantom_tracker()
                if (
                    phantom_tracker.active_count > 0
                ):  # Skip if no active phantoms at all
                    # Get price data from pair_info (already loaded above OR fetch if missing)
                    if pair_info is None:
                        pair_info = await self.consumer.get_active_pair_by_symbol(
                            symbol
                        )

                    if pair_info and "close" in pair_info:
                        from datetime import datetime, timezone

                        resolved = phantom_tracker.update(
                            symbol=symbol,
                            current_price=pair_info.get("close", 0),
                            current_time=datetime.now(timezone.utc),
                            high_price=pair_info.get("high"),
                            low_price=pair_info.get("low"),
                        )
                        # TODO: Save resolved phantoms to DB if needed
                        if resolved:
                            logger.info(
                                f"[PhantomTracker] {len(resolved)} phantom(s) resolved for {symbol}"
                            )
            except Exception as pt_err:
                logger.error(
                    f"[PhantomTracker] Error updating phantoms for {symbol}: {pt_err}",
                    exc_info=True,
                )

        # 2. Checking entry signals (logic remains unchanged)
        await self._check_signals_for_symbol_on_event(symbol, event)

    async def _handle_scale_in_fill(
        self,
        symbol: str,
        fill_price: float,
        filled_qty: float,
        client_order_id: str,
        market_type: Optional[str] = None,
    ):
        """
        Processes the execution of an averaging order (DCA/Scale-In).
        Recalculates the average entry price and initiates a TP update.
        """
        log_prefix = f"[ScaleInFill:{symbol}]"
        symbol_lock = self._get_lock_for_position(symbol, market_type)
        async with symbol_lock:
            position = self._active_position_get(symbol, market_type)
            if not position or position.status != "OPEN":
                return

            old_qty = position.remaining_quantity
            old_entry = position.entry_price

            # Recalculating the average entry price (Breaking news: math is cool)
            new_total_qty = old_qty + filled_qty
            new_avg_entry = (
                (old_qty * old_entry) + (filled_qty * fill_price)
            ) / new_total_qty

            logger.info(
                f"{log_prefix} Scale-in filled. Updating entry: {old_entry:.8f} -> {new_avg_entry:.8f}, Qty: {old_qty:.8f} -> {new_total_qty:.8f}"
            )

            position.entry_price = new_avg_entry
            position.initial_quantity += (
                filled_qty  # Increasing the base for % PnL calculation
            )
            position.remaining_quantity = new_total_qty
            self._append_execution_event(
                position,
                event_type="ENTRY",
                execution_type="SCALE_IN",
                price=fill_price,
                quantity=filled_qty,
                client_order_id=client_order_id,
            )

            # Incrementing the DCA counter (if applicable)
            if position.dca_active_sos is not None:
                position.dca_active_sos += 1

            # Determine if this was an averaging down (DCA) or averaging up (Pyramiding) fill
            if position.direction == SignalDirection.LONG:
                position._is_averaging_down = fill_price < old_entry
            else:
                position._is_averaging_down = fill_price > old_entry

            # Reset the trigger flag so the strategy can trigger again on the next bar
            position.scale_in_triggered = None

            # Initiating Take Profit order update
            self.loop.create_task(
                self._update_tp_after_scale_in(
                    symbol, market_type=self._market_type_for_position(position)
                ),
                name=f"UpdateTP_{symbol}_AfterDCA",
            )

    async def _update_tp_after_scale_in(
        self, symbol: str, market_type: Optional[str] = None
    ):
        """
        Cancels current TP orders and asks the strategy to recalculate new ones.
        """
        log_prefix = f"[UpdateTP:{symbol}]"
        logger.info(
            f"{log_prefix} Entry price changed. Replacing Take Profit orders..."
        )

        symbol_lock = self._get_lock_for_position(symbol, market_type)
        async with symbol_lock:
            position = self._active_position_get(symbol, market_type)
            if not position or position.status != "OPEN":
                return

            # 1. Canceling existing TP
            tp_order_ids = []
            if position.partial_tp_orders:
                for ptp in position.partial_tp_orders:
                    if ptp.order_id and ptp.status != "FILLED":
                        tp_order_ids.append((ptp.order_id, ptp.client_order_id))

            if tp_order_ids:
                logger.info(
                    f"{log_prefix} Cancelling {len(tp_order_ids)} existing TP orders before replacement."
                )
                executor = self._executor_for_market_type(
                    self._market_type_for_position(position), mode=position.mode
                )
                if not executor:
                    logger.error(
                        f"{log_prefix} Executor for market '{self._market_type_for_position(position)}' not found. Cannot cancel TP orders."
                    )
                    return
                for oid, cid in tp_order_ids:
                    await executor.cancel_order(
                        symbol, orderId=oid, origClientOrderId=cid
                    )

            # Clear the order list and reset the static TP so that manage_position recalculates it from the new price
            # This should ALWAYS happen during averaging, even if no orders were found on the exchange.
            position.partial_tp_orders = [
                p for p in position.partial_tp_orders if p.status == "FILLED"
            ]
            position.initial_take_profit = None
            logger.info(
                f"{log_prefix} TP state reset for recalculation (Entry changed)."
            )

        # 2. Initiating an immediate recalculation without waiting for the next tick or candle close.
        logger.info(
            f"{log_prefix} Triggering immediate position management cycle after scale-in."
        )
        self.loop.create_task(
            self._handle_event(
                {
                    "type": "SCALE_IN_RECALC",
                    "symbol": symbol,
                    "market_type": self._market_type_for_position(position),
                }
            ),
            name=f"ImmediateRecalcAfterScaleIn_{symbol}",
        )

    async def _execute_dca_grid(
        self, position: "LivePosition", dca_params: dict, pair_info: dict
    ):
        """
        Initializes a grid of limit orders (DCA) for an open position.
        """
        log_prefix = f"[DCAGridInit:{position.symbol}]"
        max_sos = int(dca_params.get("max_safety_orders", 0))
        position_market_type = self._market_type_for_position(position)
        if max_sos <= 0:
            symbol_lock_dca = self._get_lock_for_position(
                position.symbol, position_market_type
            )
            async with symbol_lock_dca:
                pos = self._active_position_get(position.symbol, position_market_type)
                if pos:
                    pos.dca_grid_init_in_progress = False
                    pos.dca_grid_init_triggered = None
            return

        logger.info(
            f"{log_prefix} Initializing {max_sos} DCA Limit Safety Orders upfront."
        )

        step_type = dca_params.get("step_type", "percentage")
        step_value_raw = dca_params.get("step_value", 1.0)

        # Allow dynamic values if it's a dict (although usually it's a number for the grid)
        if isinstance(step_value_raw, dict):
            step_value = float(step_value_raw.get("value", 1.0))
        else:
            step_value = float(step_value_raw)

        step_multiplier = float(dca_params.get("step_multiplier", 1.0))
        vol_mult = float(dca_params.get("volume_multiplier", 1.0))

        entry_price = position.entry_price
        if not entry_price:
            logger.error(
                f"{log_prefix} Cannot initialize DCA grid without entry_price."
            )
            symbol_lock_no_entry = self._get_lock_for_position(
                position.symbol, position_market_type
            )
            async with symbol_lock_no_entry:
                pos = self._active_position_get(position.symbol, position_market_type)
                if pos:
                    pos.dca_grid_init_in_progress = False
                    pos.dca_grid_init_triggered = None
            return

        executor = self._executor_for_market_type(
            position_market_type, mode=position.mode
        )
        if not executor:
            logger.error(
                f"{log_prefix} Executor for market '{position_market_type}' not found. Cannot initialize DCA grid."
            )
            return

        lot_params = await self._get_market_info(
            position.symbol, "lot_params", market_type=position_market_type
        )
        tick_size = (
            await self._get_market_info(
                position.symbol, "tick_size", market_type=position_market_type
            )
            or 0.1
        )
        min_notional = (
            await self._get_market_info(
                position.symbol, "min_notional", market_type=position_market_type
            )
            or 0.0
        )

        binance_side = "BUY" if position.direction == SignalDirection.LONG else "SELL"
        rounding_mode = (
            ROUND_DOWN if position.direction == SignalDirection.LONG else ROUND_UP
        )

        dca_order_ids = []
        dca_order_infos = []
        current_cumulative_deviation = 0.0
        current_step = step_value

        for i in range(max_sos):
            # Calculating deviation for current SO
            # SO 1: deviation = step_value
            # SO 2: deviation = step_value + step_value * step_multiplier
            # SO 3: deviation = (prev_deviation) + (prev_step * step_multiplier)
            if i == 0:
                current_cumulative_deviation = step_value
            else:
                current_step *= step_multiplier
                current_cumulative_deviation += current_step

            target_price_raw = entry_price
            if step_type == "percentage":
                if position.direction == SignalDirection.LONG:
                    target_price_raw = entry_price * (
                        1 - current_cumulative_deviation / 100.0
                    )
                else:
                    target_price_raw = entry_price * (
                        1 + current_cumulative_deviation / 100.0
                    )
            elif step_type == "atr":
                atr = pair_info.get("atr")
                if atr and atr > 0:
                    if position.direction == SignalDirection.LONG:
                        target_price_raw = entry_price - (
                            atr * current_cumulative_deviation
                        )
                    else:
                        target_price_raw = entry_price + (
                            atr * current_cumulative_deviation
                        )
                else:
                    logger.warning(
                        f"{log_prefix} ATR not available for DCA grid calculation. Skipping level {i + 1}."
                    )
                    continue
            else:
                logger.warning(
                    f"{log_prefix} Unsupported step_type '{step_type}' for upfront limit grid."
                )
                continue

            rounded_price = self._round_price(
                target_price_raw, tick_size, rounding_mode
            )
            if rounded_price is None or rounded_price <= 0:
                continue

            # Checking if the SO price is beyond the stop-loss
            if position.current_sl_price is not None:
                if (
                    position.direction == SignalDirection.LONG
                    and rounded_price <= position.current_sl_price
                ):
                    logger.warning(
                        f"{log_prefix} Skipping SO #{i + 1} at {rounded_price} because it is at or below SL ({position.current_sl_price})."
                    )
                    continue
                elif (
                    position.direction == SignalDirection.SHORT
                    and rounded_price >= position.current_sl_price
                ):
                    logger.warning(
                        f"{log_prefix} Skipping SO #{i + 1} at {rounded_price} because it is at or above SL ({position.current_sl_price})."
                    )
                    continue

            # Calculating the volume for this step based on the initial quantity (initial_quantity)
            # This prevents volume "explosion" when the price approaches the stop-loss.
            # The first safety order should already apply the multiplier.
            # SO 1 (i=0): quantity = initial_quantity * (vol_mult^1)
            # SO 2 (i=1): quantity = initial_quantity * (vol_mult^2)
            base_qty = position.initial_quantity
            target_qty_raw = base_qty * (vol_mult ** (i + 1))

            new_quantity = self.rm._adjust_and_round_quantity(
                target_qty_raw, position.symbol, rounded_price, lot_params, min_notional
            )

            if not new_quantity or new_quantity <= 0:
                logger.warning(
                    f"{log_prefix} Calculated invalid quantity for SO #{i + 1} at price {rounded_price}. Raw: {target_qty_raw}"
                )
                continue

            order_params = {
                "symbol": position.symbol,
                "side": binance_side,
                "quantity": new_quantity,
                "order_type": "LIMIT",
                "price": f"{rounded_price:.8f}",
                "timeInForce": "GTC",
                "newClientOrderId": f"x-scalein-{uuid.uuid4().hex[:14]}",
                "entry_client_order_id": position.entry_client_order_id,
                "strategy_config_id": position.config_id,
            }

            resp = await executor.place_order(**order_params)
            if resp and not resp.get("error"):
                order_id = resp.get("orderId")
                logger.info(
                    f"{log_prefix} Placed SO #{i + 1} at {rounded_price:.8f} (Qty: {new_quantity})"
                )
                dca_order_ids.append(order_id)
                dca_order_infos.append(
                    DcaOrderInfo(
                        target_price=rounded_price,
                        quantity=new_quantity,
                        order_id=order_id,
                        client_order_id=order_params["newClientOrderId"],
                        status="NEW",
                    )
                )
            else:
                logger.error(f"{log_prefix} Failed to place SO #{i + 1}: {resp}")

        symbol_lock_final = self._get_lock_for_position(
            position.symbol, position_market_type
        )
        async with symbol_lock_final:
            pos = self._active_position_get(position.symbol, position_market_type)
            if pos:
                if not hasattr(pos, "dca_order_ids"):
                    pos.dca_order_ids = []
                pos.dca_order_ids.extend(dca_order_ids)
                if not hasattr(pos, "dca_orders"):
                    pos.dca_orders = []
                pos.dca_orders.extend(dca_order_infos)
                pos.dca_grid_init_in_progress = False
                pos.dca_grid_init_triggered = None
                logger.info(
                    f"{log_prefix} Successfully placed {len(dca_order_ids)} out of {max_sos} DCA Safety Orders."
                )

    async def _execute_grid_ladder(self, position: "LivePosition", grid_params: dict):
        """
        Initializes the order grid (Grid) for an open position.
        """
        log_prefix = f"[GridInit:{position.symbol}]"
        levels = grid_params.get("levels", 10)
        upper = grid_params.get("upper_bound")
        lower = grid_params.get("lower_bound")

        if not upper or not lower:
            logger.error(
                f"{log_prefix} Grid bounds missing. Upper: {upper}, Lower: {lower}"
            )
            return

        logger.info(
            f"{log_prefix} Initializing {levels} grid levels between {lower} and {upper}"
        )

        # Grid price calculation
        prices = []
        step = (upper - lower) / (levels - 1)
        for i in range(levels):
            prices.append(lower + (step * i))

        # Calculating volume for each level
        # For now, simply divide the total risk by the number of levels (simplified)
        position_market_type = self._market_type_for_position(position)
        executor = self._executor_for_market_type(
            position_market_type, mode=position.mode
        )
        if not executor:
            logger.error(
                f"{log_prefix} Executor for market '{position_market_type}' not found. Cannot initialize grid ladder."
            )
            return

        lot_params = await self._get_market_info(
            position.symbol, "lot_params", market_type=position_market_type
        )
        tick_size = (
            await self._get_market_info(
                position.symbol, "tick_size", market_type=position_market_type
            )
            or 0.1
        )
        min_notional = (
            await self._get_market_info(
                position.symbol, "min_notional", market_type=position_market_type
            )
            or 0.0
        )

        # We take the total grid volume from the initial risk or the specified config
        # To start, we simply use a fixed lot or calculation from RM
        total_qty = (
            position.initial_quantity * 2
        )  # Example: grid is 2 times larger than the entry
        qty_per_level = total_qty / levels

        binance_side = "BUY" if position.direction == SignalDirection.LONG else "SELL"

        grid_orders = []
        for price in prices:
            rounded_price = self._round_price(price, tick_size)
            rounded_qty = self.rm._adjust_and_round_quantity(
                qty_per_level, position.symbol, price, lot_params, min_notional
            )

            order_params = {
                "symbol": position.symbol,
                "side": binance_side,
                "quantity": rounded_qty,
                "order_type": "LIMIT",
                "price": rounded_price,
                "timeInForce": "GTC",
                "newClientOrderId": f"x-grid-{uuid.uuid4().hex[:14]}",
            }

            resp = await executor.place_order(**order_params)
            if resp and not resp.get("error"):
                grid_orders.append(resp.get("orderId"))

        symbol_lock_grid = self._get_lock_for_position(
            position.symbol, position_market_type
        )
        async with symbol_lock_grid:
            pos = self._active_position_get(position.symbol, position_market_type)
            if pos:
                pos.grid_order_ids = grid_orders
                logger.info(
                    f"{log_prefix} Successfully placed {len(grid_orders)} grid orders."
                )

    async def _execute_scale_in(
        self, position: LivePosition, add_size_pct: float, pair_info: Dict[str, Any]
    ):
        """
        Executes the scaling decision made by the strategy.
        """
        log_prefix = f"[ExecuteScaleIn:{position.symbol}]"

        position_market_type = self._market_type_for_position(position)
        executor = self._executor_for_market_type(
            position_market_type, mode=position.mode
        )
        if not executor:
            logger.error(
                f"{log_prefix} Executor for market '{position_market_type}' not found. Cannot scale in."
            )
            return

        lot_params = await self._get_market_info(
            position.symbol, "lot_params", market_type=position_market_type
        )
        min_notional = await self._get_market_info(
            position.symbol, "min_notional", market_type=position_market_type
        )
        current_price = pair_info.get("last_price")

        if not current_price:
            logger.error(
                f"{log_prefix} Could not get current price for {position.symbol}. Cannot scale in."
            )
            return

        new_quantity = await self.rm.calculate_scaled_in_quantity(
            position, add_size_pct, current_price, lot_params, min_notional
        )

        if not new_quantity or new_quantity <= 0:
            logger.warning(
                f"{log_prefix} Calculated scale-in quantity is invalid: {new_quantity}"
            )
            return

        binance_side = "BUY" if position.direction == SignalDirection.LONG else "SELL"
        scale_in_order_params = {
            "symbol": position.symbol,
            "side": binance_side,
            "quantity": new_quantity,
            "order_type": "MARKET",
            "newClientOrderId": f"x-scalein-{uuid.uuid4().hex[:14]}",
            "entry_client_order_id": position.entry_client_order_id,
            "strategy_config_id": position.config_id,
            "signal_details": position.signal_details,
        }

        scale_in_order_response = await executor.place_order(**scale_in_order_params)

        if scale_in_order_response and not scale_in_order_response.get("error"):
            logger.info(
                f"{log_prefix} Scale-in order placed: {scale_in_order_response}"
            )
            # Position will update automatically via _handle_order_update
        else:
            logger.error(
                f"{log_prefix} Scale-in order failed: {scale_in_order_response}"
            )

    async def _gather_market_data_for_required_keys(
        self,
        symbol: str,
        required_data_keys: Set[str],
        log_prefix: str,
        market_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch market data for an arbitrary set of required keys."""
        start_ts = time.perf_counter()
        if not required_data_keys:
            return {}
        normalized_market_type = self._normalize_market_type(market_type)

        market_data: Dict[str, Any] = {}

        def _is_depth_snapshot_stale(depth_obj: Optional[Dict[str, Any]]) -> bool:
            if not isinstance(depth_obj, dict):
                return False
            max_age_ms = int(getattr(config, "MAX_DEPTH_SNAPSHOT_AGE_MS", 1500))
            if max_age_ms <= 0:
                return False
            snapshot_ts = depth_obj.get("event_time_ms") or depth_obj.get(
                "cached_at_ms"
            )
            if not snapshot_ts:
                return False
            try:
                age_ms = int(time.time() * 1000) - int(snapshot_ts)
            except (TypeError, ValueError):
                return False
            return age_ms > max_age_ms

        def _extract_depth_views(
            depth_obj: Optional[Dict[str, Any]],
        ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
            if not isinstance(depth_obj, dict):
                return {}, {}
            full_l2 = depth_obj.get("full_l2_depth")
            if not isinstance(full_l2, dict):
                bids = (
                    depth_obj.get("bids")
                    if isinstance(depth_obj.get("bids"), list)
                    else []
                )
                asks = (
                    depth_obj.get("asks")
                    if isinstance(depth_obj.get("asks"), list)
                    else []
                )
                full_l2 = {
                    "lastUpdateId": depth_obj.get("lastUpdateId"),
                    "bids": bids,
                    "asks": asks,
                }
            aggregated = depth_obj.get("aggregated_depth")
            if not isinstance(aggregated, dict):
                aggregated = {}
            return full_l2, aggregated

        async def fetch_data(key: str, sym: str):
            data = None
            try:
                if key.startswith("kline_"):
                    # Supports "kline_1m" and "kline_1m_BTCUSDT"
                    parts = key.split("_")
                    if len(parts) == 3:
                        timeframe = parts[1]
                        target_symbol = parts[2]
                    else:
                        timeframe = parts[1] if len(parts) > 1 else "1m"
                        target_symbol = sym
                    data = await self.consumer.get_kline_history(
                        target_symbol, timeframe, market_type=normalized_market_type
                    )
                elif key == "depth":
                    trading_raw = await self.consumer.get_latest_depth(
                        sym, market_type_requested=normalized_market_type
                    )
                    if _is_depth_snapshot_stale(trading_raw):
                        logger.debug(
                            f"{log_prefix} Trading depth snapshot is stale. Discarding."
                        )
                        trading_raw = None

                    if trading_raw:
                        depth_trading, depth_analysis = _extract_depth_views(
                            trading_raw
                        )
                        market_data["depth_trading"] = depth_trading
                        market_data["depth_analysis"] = depth_analysis
                    else:
                        market_data["depth_trading"] = {}
                        market_data["depth_analysis"] = {}

                    # Backward compatibility for strategies that still read "depth".
                    market_data["depth"] = market_data.get("depth_trading", {})

                    companion_market_type = None
                    if config.USE_COMPANION_ORDERBOOK_ANALYSIS:
                        companion_market_type = self._companion_market_type(
                            normalized_market_type
                        )

                    if companion_market_type:
                        companion_raw = await self.consumer.get_latest_depth(
                            sym, market_type_requested=companion_market_type
                        )
                        if _is_depth_snapshot_stale(companion_raw):
                            logger.debug(
                                f"{log_prefix} Companion depth snapshot is stale. Discarding."
                            )
                            companion_raw = None
                        if companion_raw:
                            comp_full_l2, comp_agg = _extract_depth_views(companion_raw)
                            market_data["depth_companion_full_l2"] = comp_full_l2
                            market_data["depth_companion_aggregated"] = comp_agg
                        else:
                            market_data["depth_companion_full_l2"] = {}
                            market_data["depth_companion_aggregated"] = {}
                    else:
                        market_data["depth_companion_full_l2"] = {}
                        market_data["depth_companion_aggregated"] = {}
                    return
                elif key == "aggTrade":
                    data = await self.consumer.get_recent_trades(
                        sym, market_type=normalized_market_type
                    )
                elif key == "open_interest":
                    data = await self.consumer.get_open_interest(sym)

                if data is not None:
                    market_data[key] = data
                else:
                    logger.warning(
                        f"{log_prefix} Received None for required data key '{key}'."
                    )
            except Exception as e:
                logger.error(
                    f"{log_prefix} Error fetching market data for key '{key}': {e}"
                )

        fetch_tasks = [fetch_data(key, symbol) for key in required_data_keys]
        if fetch_tasks:
            await asyncio.gather(*fetch_tasks)

        try:
            missing = [k for k in required_data_keys if market_data.get(k) is None]
            if missing:
                logger.warning(
                    f"{log_prefix} Could not gather all required data. Missing: {missing}"
                )
                return None

            # Checking minimum history for candles
            # This prevents 'Operand was None' errors when calculating indicators/conditions,
            # while DataConsumer has not yet had time to load the full history.
            MIN_HISTORY_REQUIRED = int(
                getattr(config, "MIN_STRATEGY_HISTORY_CANDLES", 20)
            )
            for k in required_data_keys:
                if k.startswith("kline_"):
                    df = market_data.get(k)
                    if df is not None and len(df) < MIN_HISTORY_REQUIRED:
                        logger.warning(
                            f"{log_prefix} Insufficient history for {k}. Got {len(df)}, need {MIN_HISTORY_REQUIRED}. Waiting for cache priming."
                        )
                        return None

            return market_data
        finally:
            elapsed_ms = (time.perf_counter() - start_ts) * 1000.0
            slow_ms = float(getattr(config, "MARKET_DATA_GATHER_SLOW_LOG_MS", 30.0))
            if elapsed_ms >= slow_ms:
                logger.warning(
                    f"{log_prefix} Slow market-data gather: {elapsed_ms:.2f}ms for {len(required_data_keys)} keys"
                )

    async def _gather_market_data_for_strategy(
        self,
        strategy_instance: BaseStrategy,
        symbol: str,
        market_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Collects all necessary market data for the specified strategy instance.
        Returns a dictionary with data or None in case of an error.
        """
        log_prefix = f"[GatherData:{strategy_instance.NAME}:{symbol}]"
        required_data_keys = set(strategy_instance.required_data_types)
        return await self._gather_market_data_for_required_keys(
            symbol, required_data_keys, log_prefix, market_type=market_type
        )

    async def _check_signals_for_symbol_on_event(
        self, symbol: str, event: Dict[str, Any]
    ):
        event_market_type = self._normalize_market_type(event.get("market_type"))
        """Checks signals for a symbol based on the incoming event."""
        # Check if a position already exists or if signal processing is in progress
        symbol_lock_check = self._get_lock_for_position(symbol, event_market_type)
        async with symbol_lock_check:
            if self._active_position_get(symbol, event_market_type):
                return
        async with self._processing_signal_lock:
            if f"{event_market_type}:{symbol}" in self._processing_signal_for_symbol:
                return

        # Get all running strategy instances
        async with self.instances_lock:
            running_instances = list(self.running_strategy_instances.values())

        if not running_instances:
            logger.info(
                "[SignalCheck:%s] Skipping %s: no running strategy instances.",
                symbol,
                event.get("type"),
            )
            return

        applicable_instances: List[Tuple[BaseStrategy, dict]] = []
        for instance, config_dict in running_instances:
            strategy_market_type = self._market_type_for_strategy_config(config_dict)
            if strategy_market_type != event_market_type:
                logger.debug(
                    "[SignalCheck:%s] Strategy %s skipped: market_type mismatch strategy=%s event=%s.",
                    symbol,
                    getattr(instance, "NAME", type(instance).__name__),
                    strategy_market_type,
                    event_market_type,
                )
                continue
            mode = config_dict.get("symbol_selection_mode", "DYNAMIC")
            symbols_for_instance = []
            if mode == "DYNAMIC":
                global_mode = self.symbol_selection_config.mode
                if global_mode in ("DYNAMIC_NATR", "DYNAMIC_ORACLE"):
                    symbols_for_instance = list(self.currently_managed_symbols)
                else:
                    symbols_for_instance = list(self._last_known_symbols_from_consumer)
            elif mode == "STATIC":
                symbols_for_instance = config_dict.get("symbols", [])

            if symbol not in symbols_for_instance:
                logger.debug(
                    "[SignalCheck:%s] Strategy %s skipped: symbol not monitored for mode=%s symbols=%s.",
                    symbol,
                    getattr(instance, "NAME", type(instance).__name__),
                    mode,
                    symbols_for_instance,
                )
                continue

            config_data = config_dict.get("config_data", {})
            trigger_type = config_data.get("entryTrigger", {}).get("type")

            if event["type"] == "TICK" and trigger_type in {
                "on_tick",
                "on_condition_met",
            }:
                applicable_instances.append((instance, config_dict))
            elif event["type"] == "CANDLE_CLOSE" and trigger_type == "on_candle_close":
                event_tf = event.get("timeframe")
                strategy_tf = (
                    config_data.get("entryTrigger", {}).get("timeframe")
                    or config_data.get("tradingTimeframe")
                    or "1m"
                )

                # Verify timeframe matching.
                if not event_tf or event_tf == strategy_tf:
                    applicable_instances.append((instance, config_dict))
                else:
                    logger.debug(
                        f"[SignalCheck:{symbol}] Timeframe mismatch: Event={event_tf}, Strategy={strategy_tf}. Skipping."
                    )

        if not applicable_instances:
            logger.info(
                "[SignalCheck:%s] No applicable strategy instances for event=%s timeframe=%s market_type=%s.",
                symbol,
                event.get("type"),
                event.get("timeframe"),
                event_market_type,
            )
            return

        logger.info(
            f"[SignalCheck:{symbol}] Event {event['type']} ({event.get('timeframe', 'TICK')}) matched {len(applicable_instances)} instance(s)."
        )

        pair_info_base = await self.consumer.get_active_pair_by_symbol(symbol)
        if not pair_info_base:
            logger.warning(
                "[SignalCheck:%s] Skipping checks: pair_info is missing in DataConsumer cache.",
                symbol,
            )
            return

        pair_info_base["timestamp_dt"] = datetime.fromtimestamp(
            event["timestamp_ms"] / 1000, tz=timezone.utc
        )
        if event["type"] == "TICK":
            pair_info_base["last_price"] = event["price"]
        pair_info_base["tick_size"] = (
            await self._get_market_info(
                symbol, "tick_size", market_type=event_market_type
            )
            or config.DEFAULT_TICK_SIZE
        )

        required_union: Set[str] = set()
        for instance, _cfg in applicable_instances:
            required_union.update(instance.required_data_types)

        logger.info(f"[SignalCheck:{symbol}] required_data_keys={required_union}")

        shared_market_data = await self._gather_market_data_for_required_keys(
            symbol=symbol,
            required_data_keys=required_union,
            log_prefix=f"[SignalCheck:{symbol}:{event_market_type}:SharedGather]",
            market_type=event_market_type,
        )
        if shared_market_data is None:
            logger.warning(
                f"[SignalCheck:{symbol}] Skipping checks due to missing shared market data."
            )
            return

        for instance, config_dict in applicable_instances:
            pair_info_for_instance = pair_info_base.copy()
            pair_info_for_instance["strategy_config_id"] = config_dict.get("id")
            pair_info_for_instance["market_type"] = event_market_type
            await self._check_and_process_signal_for_instance(
                instance,
                config_dict,
                symbol,
                pair_info_for_instance,
                shared_market_data=shared_market_data,
                market_type=event_market_type,
            )

    async def _check_and_process_signal_for_instance(
        self,
        instance: BaseStrategy,
        config_dict: Dict[str, Any],
        symbol: str,
        pair_info: dict,
        shared_market_data: Optional[Dict[str, Any]] = None,
        market_type: Optional[str] = None,
    ):
        """
        Helper function. Checks the signal from a single strategy instance for a single symbol,
        collects market data, and passes the signal for processing.
        """
        log_prefix = f"[SignalCheck:{instance.NAME}:{symbol}]"
        start_ts = time.perf_counter()
        normalized_market_type = self._normalize_market_type(
            market_type or self._market_type_for_strategy_config(config_dict)
        )

        # CALLING THE NEW HELPER METHOD
        if shared_market_data is not None:
            # Keep full snapshot: orderbook checks rely on depth_trading/depth_analysis
            # while required_data_types usually contains only "depth".
            market_data = dict(shared_market_data)
            missing = [
                k
                for k in instance.required_data_types
                if shared_market_data.get(k) is None
            ]
            if missing:
                logger.warning(
                    f"{log_prefix} Skipping strategy due to missing shared data: {missing}"
                )
                return
        else:
            market_data = await self._gather_market_data_for_strategy(
                instance, symbol, market_type=normalized_market_type
            )
            if market_data is None:
                logger.warning(
                    f"{log_prefix} Skipping signal check due to missing data."
                )
                return

        # Call signal check
        try:
            pair_info["is_live_mode"] = True
            # logger.info(f"{log_prefix} Calling strategy.check_signal()...")
            # MODIFICATION: Capture trace for HFT publishing
            signal_result, weight, trace = await instance.check_signal(
                pair_info, market_data
            )

            # HFT DATA PUBLISHING
            # If the strategy returned features in the trace, we publish them to Redis for the HFT bot.
            if trace and isinstance(trace, dict) and self.redis_client:
                # 1. Publish to hft:symbols
                if "features" in trace:
                    features = trace["features"]
                    hft_symbol_data = {
                        "symbol": symbol,
                        "NATR 1/30 (1m)": features.get(
                            "scalper_natr", 0.0
                        ),  # Matches Rust alias
                        "relative_volume": features.get("relative_volume", 1.0),
                    }
                    try:
                        await self.redis_client.publish(
                            "hft:symbols", json.dumps(hft_symbol_data)
                        )
                        logger.debug(
                            f"[HFT:Publish] Symbol data for {symbol} sent to Redis"
                        )
                    except Exception as e:
                        logger.warning(
                            f"[HFT:Publish] Failed to publish symbol data: {e}"
                        )

                # 2. Publish to hft:oracle
                if "oracle_regime" in trace:
                    oracle_data = {
                        "regime": trace.get("oracle_regime", 0),
                        "confidence": trace.get("oracle_confidence", 0.0),
                    }
                    try:
                        await self.redis_client.publish(
                            "hft:oracle", json.dumps(oracle_data)
                        )
                        logger.debug("[HFT:Publish] Oracle data sent to Redis")
                    except Exception as e:
                        logger.warning(
                            f"[HFT:Publish] Failed to publish oracle data: {e}"
                        )
                    # `let mut stream = pubsub.on_message(); ... let payload: SymbolData = serde_json::from_str(...)`
                    # So it expects a single SymbolData object per message on that channel.

                    if "features" in trace and self.redis_client:
                        try:
                            # Use fire-and-forget task to avoid blocking
                            self.loop.create_task(
                                self.redis_client.publish(
                                    "hft:symbols", json.dumps(hft_symbol_data)
                                ),
                                name=f"PubHftSym_{symbol}",
                            )
                        except Exception as e_pub:
                            logger.error(
                                f"{log_prefix} Failed to publish to hft:symbols: {e_pub}"
                            )

                # 2. Publish to hft:oracle (Only for BTCUSDT usually, or if configured)
                # Rust expects `OracleUpdate { regime: i32, confidence: f64 }`
                if "oracle_regime" in trace and symbol == "BTCUSDT":
                    regime = trace.get("oracle_regime", -1)
                    # Confidence might be in 'prob' or we need to pass it from strategy
                    # In previous step we put 'prob' in trace
                    confidence = trace.get("prob", 0.0) * 100  # Convert 0-1 to 0-100%

                    oracle_payload = {
                        "regime": int(regime),
                        "confidence": float(confidence),
                    }

                    if self.redis_client:
                        try:
                            self.loop.create_task(
                                self.redis_client.publish(
                                    "hft:oracle", json.dumps(oracle_payload)
                                ),
                                name="PubHftOracle",
                            )
                        except Exception as e_pub:
                            logger.error(
                                f"{log_prefix} Failed to publish to hft:oracle: {e_pub}"
                            )

            if signal_result is None and trace and isinstance(trace, dict):
                rejection = trace.get("rejection_reason", "")
                if rejection == "filter":
                    reasons = instance._get_failure_reasons(trace)
                    logger.info(
                        f"{log_prefix} Signal REJECTED by filters: {', '.join(reasons)}"
                    )
                elif rejection == "entry_conditions":
                    reasons = instance._get_failure_reasons(trace)
                    logger.info(
                        f"{log_prefix} Signal REJECTED by entry conditions: {', '.join(reasons)}"
                    )
                elif rejection == "weight_threshold":
                    logger.info(
                        f"{log_prefix} Signal REJECTED by weight threshold (weight={weight:.2f})."
                    )
                elif rejection in ("external_signal_required",):
                    pass
                elif trace.get("result") is False:
                    reasons = instance._get_failure_reasons(trace)
                    logger.info(
                        f"{log_prefix} Signal REJECTED: {', '.join(reasons) if reasons else 'no details'}"
                    )
                else:
                    logger.info(f"{log_prefix} Signal REJECTED (weight={weight:.2f}).")
            if isinstance(signal_result, StrategySignal):
                if signal_result.details is None:
                    signal_result.details = {}
                strategy_config_id = pair_info.get("strategy_config_id")
                if strategy_config_id and isinstance(signal_result.details, dict):
                    signal_result.details.setdefault(
                        "strategy_config_id", strategy_config_id
                    )
                if isinstance(signal_result.details, dict):
                    signal_result.details["market_type"] = normalized_market_type
                    signal_result.details["marketType"] = (
                        "SPOT" if normalized_market_type == "spot" else "FUTURES"
                    )
                self.loop.create_task(
                    self._process_signal(
                        signal_result, pair_info, market_data_snapshot=market_data
                    ),
                    name=f"ProcessSignal_{signal_result.strategy_name}_{symbol}",
                )
        except Exception as e:
            logger.error(
                f"{log_prefix} Exception during strategy.check_signal(): {e}",
                exc_info=True,
            )
        finally:
            elapsed_ms = (time.perf_counter() - start_ts) * 1000.0
            slow_ms = float(getattr(config, "SIGNAL_PIPELINE_SLOW_LOG_MS", 40.0))
            if elapsed_ms >= slow_ms:
                logger.warning(f"{log_prefix} Slow signal pipeline: {elapsed_ms:.2f}ms")

    async def _check_and_close_positions_without_sl(self):
        """
        Checks all active positions in "OPEN" status.
        If a position does not have a set stop-loss (current_sl_order_id is None)
        and enough time has passed since opening (sl_placement_grace_period),
        the position is forcibly closed at market price.
        """
        log_prefix = f"[MissingSLCheck:{self.api_key_name}]"
        now = time.time()
        positions_to_process_for_missing_sl: List[
            LivePosition
        ] = []  # Collecting copies of Position objects

        # Getting copies of position objects under lock
        async with self._positions_dict_lock:
            for position_obj in list(
                self._active_positions.values()
            ):  # list() for copy
                if position_obj.status == "OPEN":
                    # Make a copy to work with it outside the lock if needed
                    positions_to_process_for_missing_sl.append(
                        LivePosition(**vars(position_obj))
                    )

        if not positions_to_process_for_missing_sl:
            logger.debug(f"{log_prefix} No OPEN positions to check for missing SL.")
            return

        logger.info(
            f"{log_prefix} Checking {len(positions_to_process_for_missing_sl)} OPEN positions for missing SLs..."
        )

        for pos_copy in positions_to_process_for_missing_sl:  # Iterating through copies
            symbol = pos_copy.symbol
            entry_cid = pos_copy.entry_client_order_id or "UnknownCID"
            pos_log_prefix = f"[{log_prefix}:{symbol}:{entry_cid}]"

            sl_order_id_present = pos_copy.current_sl_order_id is not None

            if sl_order_id_present:
                logger.debug(
                    f"{pos_log_prefix} SL order ID {pos_copy.current_sl_order_id} is present. OK."
                )
                continue  # Stop loss exists, skipping

            # If the position is in "no SL mode", skip the check
            if self._position_is_intentional_no_sl_mode(pos_copy):
                logger.debug(
                    f"{pos_log_prefix} Position is in NO_STOP_LOSS mode. Skipping missing SL check."
                )
                continue

            # If SL is currently being placed (BE/trailing), do not consider it an "absence of SL"
            if pos_copy.sl_placement_initiated:
                logger.debug(
                    f"{pos_log_prefix} sl_placement_initiated=True. SL is being placed. Skipping check."
                )
                continue

            # No stop-loss, checking grace period
            if pos_copy.time_status_open is None:
                logger.warning(
                    f"{pos_log_prefix} Position is OPEN but 'time_status_open' is not set. Cannot determine grace period. Skipping this check cycle."
                )
                # It might be worth setting time_status_open here if it's missing and the position has been OPEN for a long time
                # But this might be a sign of another problem.
                symbol_lock_time = self._get_lock_for_position(
                    symbol, self._market_type_for_position(pos_copy)
                )
                async with symbol_lock_time:  # Check and set, if necessary, under lock
                    actual_pos = self._active_position_get(
                        symbol, self._market_type_for_position(pos_copy)
                    )
                    if (
                        actual_pos
                        and actual_pos.status == "OPEN"
                        and actual_pos.time_status_open is None
                    ):
                        logger.warning(
                            f"{pos_log_prefix} Setting 'time_status_open' for already OPEN position."
                        )
                        actual_pos.time_status_open = (
                            time.time()
                        )  # Setting now, the check will be on the next iteration
                continue

            time_since_opened = now - pos_copy.time_status_open
            logger.debug(
                f"{pos_log_prefix} No SL ID. Time since status OPEN: {time_since_opened:.1f}s (Grace: {self.sl_placement_grace_period}s)"
            )

            if time_since_opened > self.sl_placement_grace_period:
                logger.critical(
                    f"{pos_log_prefix} Position OPEN for {time_since_opened:.1f}s without SL. Grace period ({self.sl_placement_grace_period}s) EXCEEDED. Scheduling emergency closure."
                )

                needs_closure_confirmed = False
                symbol_lock_emerg = self._get_lock_for_position(
                    symbol, self._market_type_for_position(pos_copy)
                )
                async with symbol_lock_emerg:
                    current_pos_in_active = self._active_position_get(
                        symbol, self._market_type_for_position(pos_copy)
                    )
                    if (
                        current_pos_in_active
                        and current_pos_in_active.status == "OPEN"
                        and current_pos_in_active.current_sl_order_id is None
                        and not current_pos_in_active.sl_placement_initiated
                    ):  # ADDED: Do not close if SL is currently being placed
                        # IMPORTANT: Do NOT set the CLOSING status here!
                        # This will call close_position(). If set here,
                        # then close_position() will see the CLOSING status and exit immediately,
                        # without performing a real close.
                        # Just mark the exit reason for logging.
                        current_pos_in_active.exit_reason = (
                            f"EMERGENCY_NO_SL_FOR_{entry_cid}"
                        )
                        needs_closure_confirmed = True
                    else:
                        logger.info(
                            f"{pos_log_prefix} Position state changed or SL appeared before emergency close could be dispatched. Skipping closure."
                        )

                if needs_closure_confirmed:
                    reason_for_closure = f"EMERGENCY_NO_SL_DETECTED_FOR_{entry_cid}"
                    self.loop.create_task(
                        self.close_position(
                            symbol,
                            reason_for_closure,
                            market_type=self._market_type_for_position(pos_copy),
                        ),
                        name=f"EmergencyCloseMissingSL_{symbol}",
                    )
                    # Sending notification to Telegram
                    if (
                        self.telegram_notifier
                    ):  # Checking that the notifier is available
                        error_description_for_tg = (
                            f"Position {symbol} ({entry_cid}) open for too long "
                            f"({time_since_opened:.0f}c) WITHOUT STOP-LOSS! "
                            f"Forcibly closing."
                        )
                        action_taken_for_tg = f"Position closure initiated {symbol} due to: {reason_for_closure}"

                        # Instead of a generic bot_error, a special method can be created in notifier
                        # or use send_message if bot_error is not semantically appropriate.
                        # For example, we use bot_error, but pass more specific information.
                        self.loop.create_task(
                            self.telegram_notifier.bot_error(
                                error_description=error_description_for_tg,
                                module_function="TradingController._check_and_close_positions_without_sl",
                                action_taken=action_taken_for_tg,
                                chat_id=self.user_telegram_chat_id,
                                # exc_info does not need to be passed, as this is not a Python exception, but a logical error/risk
                                api_key_name=self.api_key_name,
                            ),
                            name=f"TelegramNotify_MissingSL_{symbol}",
                        )
            else:
                logger.debug(
                    f"{pos_log_prefix} Position OPEN for {time_since_opened:.1f}s without SL. Within grace period."
                )

        # Second level of protection: checking positions stuck in CLOSING status
        async with self._positions_dict_lock:
            stuck_closing_positions = [
                (
                    pos.symbol,
                    self._market_type_for_position(pos),
                    pos.entry_client_order_id or "UnknownCID",
                    pos.exit_reason,
                    pos.failed_close_attempts,
                )
                for pos in list(self._active_positions.values())
                if pos.status == "CLOSING" and pos.remaining_quantity > 0
            ]

        for (
            symbol,
            position_market_type,
            entry_cid,
            exit_reason,
            failed_attempts,
        ) in stuck_closing_positions:
            stuck_log_prefix = f"[{log_prefix}:StuckCLOSING:{symbol}:{entry_cid}]"

            # Incrementing the failed attempts counter
            symbol_lock_stuck = self._get_lock_for_position(
                symbol, position_market_type
            )
            async with symbol_lock_stuck:
                stuck_position = self._active_position_get(symbol, position_market_type)
                if stuck_position:
                    stuck_position.failed_close_attempts += 1
                    failed_attempts = stuck_position.failed_close_attempts

            logger.warning(
                f"{stuck_log_prefix} Position still in CLOSING status with remaining qty > 0. Attempt #{failed_attempts}."
            )

            reason_for_retry_closure = (
                exit_reason or f"RETRY_CLOSE_STUCK_CLOSING_{entry_cid}"
            )
            self.loop.create_task(
                self.close_position(
                    symbol, reason_for_retry_closure, market_type=position_market_type
                ),
                name=f"RetryCloseStuckClosing_{symbol}",
            )

            # NOTIFICATION ESCALATION
            if self.telegram_notifier:
                if failed_attempts >= 5:
                    # CRITICAL escalation — immediate intervention required
                    self.loop.create_task(
                        self.telegram_notifier.bot_error(
                            error_description=f"🚨 CRITICAL ESCALATION: Position {symbol} ({entry_cid}) does not close after {failed_attempts} attempts! MANUAL CLOSURE REQUIRED!",
                            module_function="TradingController._check_and_close_positions_without_sl",
                            action_taken=f"Attempt #{failed_attempts}. Position may be unprotected!",
                            chat_id=self.user_telegram_chat_id,
                            api_key_name=self.api_key_name,
                        ),
                        name=f"TelegramNotify_CriticalEscalation_{symbol}",
                    )
                elif failed_attempts >= 3:
                    # Elevated notification
                    self.loop.create_task(
                        self.telegram_notifier.bot_error(
                            error_description=f"⚠️ Position {symbol} ({entry_cid}) stuck in CLOSING! This is attempt #{failed_attempts}.",
                            module_function="TradingController._check_and_close_positions_without_sl",
                            action_taken=f"Position closure re-initiated {symbol}",
                            chat_id=self.user_telegram_chat_id,
                            api_key_name=self.api_key_name,
                        ),
                        name=f"TelegramNotify_StuckClosing_{symbol}",
                    )
                else:
                    # Normal notification only on the first attempt
                    if failed_attempts == 1:
                        self.loop.create_task(
                            self.telegram_notifier.bot_error(
                                error_description=f"Position {symbol} ({entry_cid}) stuck in CLOSING status! Retrying closure.",
                                module_function="TradingController._check_and_close_positions_without_sl",
                                action_taken=f"Position closure re-initiated {symbol}",
                                chat_id=self.user_telegram_chat_id,
                                api_key_name=self.api_key_name,
                            ),
                            name=f"TelegramNotify_StuckClosing_{symbol}",
                        )

    async def _check_and_update_symbols(self):
        """
        Checks the current list of symbols from DataConsumer and triggers an update if it has changed.
        IMPORTANT: In DYNAMIC_NATR and DYNAMIC_ORACLE modes, symbol management occurs via
        _dynamic_symbol_selection_loop, so this function should not overwrite _last_known_symbols_from_consumer.
        """
        try:
            mode = self.symbol_selection_config.mode

            # In dynamic modes, symbols are managed via _dynamic_symbol_selection_loop
            if mode in ("DYNAMIC_NATR", "DYNAMIC_ORACLE"):
                # logger.debug(f"[CheckSymbols] Mode is {mode}. Symbol management handled by dynamic selection loop. Skipping.")

                # If we just switched from STATIC to DYNAMIC, _last_known might contain old symbols
                # Synchronizing _last_known_symbols_from_consumer with currently_managed_symbols
                if (
                    self.currently_managed_symbols
                    != self._last_known_symbols_from_consumer
                ):
                    logger.info(
                        f"[CheckSymbols] Syncing _last_known_symbols_from_consumer with currently_managed_symbols: {len(self.currently_managed_symbols)} symbols."
                    )
                    self._last_known_symbols_from_consumer = (
                        self.currently_managed_symbols.copy()
                    )
                    await self._update_monitored_symbols()
                return

            # In STATIC mode, we use the old logic (take all symbols from the cache if they are not limited by the strategy config)
            # IMPORTANT: If we switched from DYNAMIC to STATIC, we need to ensure that we see all available symbols,
            # so that strategies configured to STATIC can choose their own.
            current_symbols = await self.consumer.get_active_symbols()
            if current_symbols != self._last_known_symbols_from_consumer:
                # Getting statistics on oracle modes for new symbols
                oracle_stats = {}
                for symbol in current_symbols:
                    pair_info = await self.consumer.get_active_pair_by_symbol(symbol)
                    if pair_info:
                        regime = pair_info.get("oracle_regime")
                        if regime is not None:
                            oracle_stats[regime] = oracle_stats.get(regime, 0) + 1

                oracle_stats_str = (
                    ", ".join(
                        [
                            f"Regime {r}: {count}"
                            for r, count in sorted(oracle_stats.items())
                        ]
                    )
                    if oracle_stats
                    else "No oracle data"
                )

                logger.info(
                    f"Detected change in active symbols (STATIC mode). Old: {len(self._last_known_symbols_from_consumer)}, New: {len(current_symbols)}. Oracle stats: [{oracle_stats_str}]"
                )
                self._last_known_symbols_from_consumer = current_symbols.copy()
                await self._update_monitored_symbols()
        except Exception as e:
            logger.error(f"Error checking/updating symbols: {e}", exc_info=True)

    async def _update_monitored_symbols(self):
        """
        Updates the list of tracked symbols and data subscriptions.
        New logic:
        1. Determines which symbols are required by running strategy instances.
        2. Determines which symbols have open positions.
        3. Unsubscribes from symbols that are no longer needed and have no positions.
        4. For symbols that are no longer needed but have a position, moves them to "managed close" status.
        5. Subscribes to all necessary data for active and managed symbols.
        """
        log_prefix = f"[UpdateMonitoredSymbols:{self.api_key_name}]"
        logger.info(
            f"{log_prefix} Updating monitored symbols and data subscriptions..."
        )

        try:
            # Step 1: Determining required symbols from strategies and positions
            required_symbols_from_strategies: Set[str] = set()
            async with self.instances_lock:
                running_instances = list(self.running_strategy_instances.values())

            for instance, config_dict in running_instances:
                config_data = config_dict.get("config_data", {})
                pinned_symbol = config_data.get("symbol")

                # If the strategy has a hardcoded symbol (e.g., from the editor), it is ALWAYS needed
                if pinned_symbol:
                    required_symbols_from_strategies.add(pinned_symbol)

                mode = config_dict.get("symbol_selection_mode", "DYNAMIC")
                if mode == "DYNAMIC":
                    # In dynamic modes, we use
                    # currently_managed_symbols, which are already filtered by settings
                    global_mode = self.symbol_selection_config.mode
                    if global_mode in ("DYNAMIC_NATR", "DYNAMIC_ORACLE"):
                        required_symbols_from_strategies.update(
                            self.currently_managed_symbols
                        )
                    else:
                        # In STATIC (global) mode, we take all symbols from the screener
                        required_symbols_from_strategies.update(
                            self._last_known_symbols_from_consumer
                        )
                elif mode == "STATIC":
                    required_symbols_from_strategies.update(
                        config_dict.get("symbols", [])
                    )

            async with self._positions_dict_lock:
                open_positions_symbols = {
                    pos.symbol for pos in self._active_positions.values()
                }

            # Final set of symbols that should be under monitoring
            newly_required_symbols = required_symbols_from_strategies.union(
                open_positions_symbols
            )

            # Step 2: Determining what to unsubscribe from
            # Calculate symbols that are no longer required by STRATEGIES but might have been in monitoring earlier.
            symbols_no_longer_needed_by_strategies = (
                self._monitored_symbols - required_symbols_from_strategies
            )

            # Iterating through these "obsolete" symbols
            for symbol in list(symbols_no_longer_needed_by_strategies):
                if symbol in open_positions_symbols:
                    # Symbol is no longer needed by strategies, but there is a position for it
                    logger.info(
                        f"{log_prefix} Symbol {symbol} is no longer monitored by strategies, but has an open position. Moving to managed close state."
                    )
                    self._closing_managed_symbols.add(symbol)
                else:
                    # The symbol is no longer needed by strategies or for position management
                    logger.debug(
                        f"{log_prefix} Symbol {symbol} no longer required. Unsubscribing from all data."
                    )
                    await self.consumer.remove_all_subscriptions_for_symbol(symbol)
                    if hasattr(self.consumer, "_metrics_lock"):
                        async with self.consumer._metrics_lock:
                            if symbol in self.consumer._required_metrics:
                                del self.consumer._required_metrics[symbol]

            # Step 3: Collect all necessary data for subscription
            all_required_data_types: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
            all_required_metrics: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
            # OPTIMIZATION: Collect information about the need for a spot order book
            all_requires_spot_orderbook: Dict[str, bool] = defaultdict(bool)

            for instance, config_dict in running_instances:
                config_data = config_dict.get("config_data", {})
                pinned_symbol = config_data.get("symbol")

                symbols_for_instance = []
                if pinned_symbol:
                    symbols_for_instance.append(pinned_symbol)

                mode = config_dict.get("symbol_selection_mode", "DYNAMIC")
                if mode == "DYNAMIC":
                    # In dynamic modes, use filtered symbols
                    global_mode = self.symbol_selection_config.mode
                    if global_mode in ("DYNAMIC_NATR", "DYNAMIC_ORACLE"):
                        for sym in self.currently_managed_symbols:
                            if sym not in symbols_for_instance:
                                symbols_for_instance.append(sym)
                    else:
                        for sym in self._last_known_symbols_from_consumer:
                            if sym not in symbols_for_instance:
                                symbols_for_instance.append(sym)
                elif mode == "STATIC":
                    for sym in config_dict.get("symbols", []):
                        if sym not in symbols_for_instance:
                            symbols_for_instance.append(sym)

                strategy_market_type = self._market_type_for_strategy_config(
                    config_dict
                )

                # Check if ML-confirmation is enabled for this strategy
                uses_ml_confirmation = config_dict.get("use_ml_confirmation", False)

                for symbol in symbols_for_instance:
                    if (
                        symbol in newly_required_symbols
                    ):  # Checking that the symbol is still needed
                        symbol_market_key = (symbol, strategy_market_type)
                        all_required_data_types[symbol_market_key].update(
                            instance.required_data_types
                        )
                        all_required_metrics[symbol_market_key].update(
                            instance.required_indicators
                        )
                        # OPTIMIZATION: Check if a spot order book is needed for this strategy
                        if (
                            hasattr(instance, "requires_spot_orderbook")
                            and instance.requires_spot_orderbook
                        ):
                            all_requires_spot_orderbook[symbol] = True

                        # Adding aggTrade if ML-confirmation is enabled
                        # ML model uses aggtrade features (buyer_ratio, volume_imbalance, etc.)
                        if (
                            uses_ml_confirmation
                            and self._ml_confirmation_enabled_live_runtime
                        ):
                            if (
                                "aggTrade"
                                not in all_required_data_types[symbol_market_key]
                            ):
                                all_required_data_types[symbol_market_key].add(
                                    "aggTrade"
                                )
                                logger.debug(
                                    f"[UpdateMonitoredSymbols] Added aggTrade subscription for {symbol} (ML confirmation enabled)"
                                )

            # Add requirements for all open positions (including those in managed close)
            async with self._positions_dict_lock:
                open_position_market_keys = [
                    (pos.symbol, self._market_type_for_position(pos))
                    for pos in self._active_positions.values()
                ]
            for symbol_market_key in open_position_market_keys:
                all_required_data_types[symbol_market_key].add("kline_1m")
                all_required_data_types[symbol_market_key].add("depth")

            # Step 4: Updating state and subscribing
            self._monitored_symbols = newly_required_symbols.copy()

            subscription_tasks = []
            for (symbol, market_type), data_types in all_required_data_types.items():
                metrics_for_symbol = all_required_metrics.get((symbol, market_type))
                needs_spot_ob = all_requires_spot_orderbook.get(symbol, False)
                for data_type in data_types:
                    # Parsing data_type to determine the subscription symbol
                    # Can be "kline_1m" or "kline_1m_BTCUSDT"
                    sub_symbol = symbol
                    sub_data_type = data_type

                    if data_type.startswith("kline_"):
                        parts = data_type.split("_")
                        if len(parts) == 3:
                            # Format: kline_{timeframe}_{symbol}
                            timeframe = parts[1]
                            sub_symbol = parts[2]  # Use symbol from the key
                            sub_data_type = f"kline_{timeframe}"

                    # Passing the needs_companion_orderbook flag only for depth
                    subscription_tasks.append(
                        self.consumer.ensure_subscription(
                            sub_data_type,
                            sub_symbol,
                            required_metrics=metrics_for_symbol
                            if sub_symbol == symbol
                            else None,
                            needs_companion_orderbook=needs_spot_ob
                            if data_type == "depth"
                            else False,
                            market_type=market_type,
                        )
                    )

            if subscription_tasks:
                await asyncio.gather(*subscription_tasks, return_exceptions=True)
                logger.info(
                    f"{log_prefix} DataConsumer subscription update process finished for {len(all_required_data_types)} symbols."
                )

        except Exception as e:
            logger.error(f"{log_prefix} Error: {e}", exc_info=True)

    async def _check_signals_for_symbol(
        self, symbol: str, pair_info: Dict[str, Any], strategies: List[BaseStrategy]
    ):
        log_prefix = f"[SignalCheck:{symbol}]"

        # 1. Collecting all unique data types required for ALL strategies of this symbol
        required_data_keys: Set[str] = set()
        for strategy in strategies:
            required_data_keys.update(strategy.required_data_types)

        if not required_data_keys:
            return

        # 2. Requesting all necessary data AT ONCE
        market_data: Dict[str, Any] = {}
        fetch_tasks = []

        def _is_depth_snapshot_stale(depth_obj: Optional[Dict[str, Any]]) -> bool:
            if not isinstance(depth_obj, dict):
                return False
            max_age_ms = int(getattr(config, "MAX_DEPTH_SNAPSHOT_AGE_MS", 1500))
            if max_age_ms <= 0:
                return False
            snapshot_ts = depth_obj.get("event_time_ms") or depth_obj.get(
                "cached_at_ms"
            )
            if not snapshot_ts:
                return False
            try:
                age_ms = int(time.time() * 1000) - int(snapshot_ts)
            except (TypeError, ValueError):
                return False
            return age_ms > max_age_ms

        def _extract_depth_views(
            depth_obj: Optional[Dict[str, Any]],
        ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
            if not isinstance(depth_obj, dict):
                return {}, {}
            full_l2 = depth_obj.get("full_l2_depth")
            if not isinstance(full_l2, dict):
                bids = (
                    depth_obj.get("bids")
                    if isinstance(depth_obj.get("bids"), list)
                    else []
                )
                asks = (
                    depth_obj.get("asks")
                    if isinstance(depth_obj.get("asks"), list)
                    else []
                )
                full_l2 = {
                    "lastUpdateId": depth_obj.get("lastUpdateId"),
                    "bids": bids,
                    "asks": asks,
                }
            aggregated = depth_obj.get("aggregated_depth")
            if not isinstance(aggregated, dict):
                aggregated = {}
            return full_l2, aggregated

        async def fetch_data(key, sym):
            data = None
            try:
                if key.startswith("kline_"):
                    # Parse the key: can be "kline_1m" or "kline_1m_BTCUSDT"
                    parts = key.split("_")
                    if len(parts) == 3:
                        # Format: kline_{timeframe}_{symbol} (e.g., kline_1m_BTCUSDT)
                        timeframe = parts[1]
                        target_symbol = parts[2]
                    else:
                        # Format: kline_{timeframe} (e.g., kline_1m)
                        timeframe = parts[1]
                        target_symbol = sym

                    data = await self.consumer.get_kline_history(
                        target_symbol, timeframe
                    )
                elif key == "depth":
                    # Requesting both order books if needed
                    trading_depth = await self.consumer.get_latest_depth(
                        sym, market_type_requested=config.TRADING_MARKET_TYPE
                    )
                    if _is_depth_snapshot_stale(trading_depth):
                        trading_depth = None
                    analysis_depth = None
                    if config.USE_COMPANION_ORDERBOOK_ANALYSIS:
                        companion_market = (
                            "spot"
                            if config.TRADING_MARKET_TYPE == "futures_usdtm"
                            else "futures_usdtm"
                        )
                        analysis_depth = await self.consumer.get_latest_depth(
                            sym, market_type_requested=companion_market
                        )
                        if _is_depth_snapshot_stale(analysis_depth):
                            analysis_depth = None

                    trading_full_l2, trading_agg = _extract_depth_views(trading_depth)
                    analysis_full_l2, analysis_agg = _extract_depth_views(
                        analysis_depth
                    )
                    market_data["depth_trading"] = trading_full_l2
                    market_data["depth_analysis"] = (
                        analysis_agg if analysis_agg else trading_agg
                    )
                    # For backward compatibility
                    market_data["depth"] = trading_full_l2
                    market_data["depth_companion_full_l2"] = analysis_full_l2
                    market_data["depth_companion_aggregated"] = analysis_agg
                    return  # Exiting because order books are processed separately
                elif key == "aggTrade":
                    data = await self.consumer.get_recent_trades(sym)
                elif key == "open_interest":
                    data = await self.consumer.get_open_interest(sym)

                if data is not None:
                    market_data[key] = data
                else:
                    logger.warning(
                        f"{log_prefix} Received None for required data key '{key}'."
                    )

            except Exception as e:
                logger.error(f"{log_prefix} Error fetching data for key '{key}': {e}")

        for key in required_data_keys:
            fetch_tasks.append(fetch_data(key, symbol))

        if fetch_tasks:
            await asyncio.gather(*fetch_tasks)

        logger.debug(
            f"{log_prefix} Fetched market_data for strategies. Available keys: {list(market_data.keys())}"
        )

        # 3. Call each strategy, passing it the full set of data
        signal_tasks = []
        for strategy in strategies:
            # Check that all data needed SPECIFICALLY BY THIS strategy has been successfully loaded
            can_run = all(
                market_data.get(req_key) is not None
                for req_key in strategy.required_data_types
            )

            if not can_run:
                missing = [
                    k
                    for k in strategy.required_data_types
                    if market_data.get(k) is None
                ]
                logger.warning(
                    f"{log_prefix} Skipping strategy {strategy.NAME} due to missing data: {missing}"
                )
                continue

            # Copy only the data needed by this strategy to avoid confusion
            strategy_market_data = {
                key: market_data.get(key) for key in strategy.required_data_types
            }

            pair_info_for_strategy = pair_info.copy()
            pair_info_for_strategy["is_live_mode"] = True
            signal_tasks.append(
                self.loop.create_task(
                    strategy.check_signal(pair_info_for_strategy, strategy_market_data),
                    name=f"CheckSignal_{strategy.NAME}_{symbol}",
                )
            )

        if signal_tasks:
            generated_signals = await asyncio.gather(
                *signal_tasks, return_exceptions=True
            )
            for i, result in enumerate(generated_signals):
                if isinstance(result, StrategySignal):
                    self.loop.create_task(
                        self._process_signal(
                            result,
                            pair_info.copy(),
                            market_data_snapshot=strategy_market_data,
                        ),
                        name=f"ProcessSignal_{result.strategy_name}_{symbol}",
                    )
                elif isinstance(result, Exception):
                    logger.error(
                        f"{log_prefix} Error in signal check task '{signal_tasks[i].get_name()}': {result}",
                        exc_info=result,
                    )

    def _round_price(
        self, price: float, tick_size: float, rounding_mode: str = ROUND_DOWN
    ) -> Optional[float]:
        """Rounds the price according to tick_size."""
        if price <= 0 or tick_size <= 0:
            return None
        try:
            price_dec = Decimal(str(price))
            tick_dec = Decimal(str(tick_size))
            rounded_price = float(
                (price_dec / tick_dec).quantize(Decimal("0"), rounding=rounding_mode)
                * tick_dec
            )
            return rounded_price
        except (InvalidOperation, TypeError) as e:
            logger.error(
                f"[RoundPrice] Error rounding price {price} with tick_size {tick_size}: {e}"
            )
            return None

    async def _process_signal(
        self,
        signal: StrategySignal,
        pair_info: Dict[str, Any],
        market_data_snapshot: Optional[Dict[str, Any]] = None,
    ):
        """
        Processes a signal from the strategy: validates via RiskManager,
        places orders, and creates a Position object.
        """
        log_prefix = f"[ProcessSignal:{signal.strategy_name}:{signal.symbol}:{signal.direction.name}]"
        logger.info(f"{log_prefix} --- START PROCESSING SIGNAL ---")
        logger.debug(f"{log_prefix} Received Signal Object: {signal}")
        logger.debug(f"{log_prefix} Received Pair Info: {pair_info}")
        initial_market_type = self._normalize_market_type(
            (
                (signal.details or {}).get("market_type")
                if isinstance(signal.details, dict)
                else None
            )
            or pair_info.get("market_type")
        )
        processing_key = f"{initial_market_type}:{signal.symbol}"

        # Protection against parallel processing of the same symbol
        async with self._processing_signal_lock:
            if processing_key in self._processing_signal_for_symbol:
                logger.debug(
                    f"{log_prefix} Signal for {processing_key} already being processed. Skipping."
                )
                return
            self._processing_signal_for_symbol.add(processing_key)

        try:
            # 1. PRELIMINARY CHECKS AND THROTTLING

            signal_key_throttle = (
                initial_market_type,
                signal.symbol,
                signal.strategy_name,
                signal.direction,
            )
            last_identical_signal_time = self._recent_signals.get(
                signal_key_throttle, 0
            )
            current_time = time.time()

            if current_time - last_identical_signal_time < self._signal_throttle_period:
                logger.debug(
                    f"{log_prefix} Signal throttled. Last identical signal was {current_time - last_identical_signal_time:.1f}s ago (Limit: {self._signal_throttle_period}s)."
                )
                return

            last_close_time_for_symbol = self._last_position_close_time_per_symbol.get(
                self._position_key(signal.symbol, initial_market_type), 0
            )
            if (
                current_time - last_close_time_for_symbol
                < self._symbol_cooldown_duration
            ):
                remaining_cooldown = self._symbol_cooldown_duration - (
                    current_time - last_close_time_for_symbol
                )
                logger.info(
                    f"{log_prefix} Signal for {signal.symbol} REJECTED. Symbol is in cooldown. Remaining: {remaining_cooldown:.1f}s."
                )
                self.trade_logger.log_event(
                    event_type="SIGNAL_REJECTED_COOLDOWN",
                    data={
                        "symbol": signal.symbol,
                        "strategy": signal.strategy_name,
                        "direction": signal.direction.name,
                        "reason": f"Symbol cooldown active, remaining {remaining_cooldown:.1f}s",
                        "details": signal.details,
                    },
                )
                return

            async with self._positions_dict_lock:
                if self._active_position_get(signal.symbol, initial_market_type):
                    logger.info(
                        f"{log_prefix} Signal ignored. Active {initial_market_type} position already exists for {signal.symbol}."
                    )
                    return

                # Check for max concurrent trades
                active_count = sum(
                    1
                    for p in self._active_positions.values()
                    if p.status in ("OPEN", "PENDING_ENTRY", "RESERVING")
                )
                if active_count >= self.rm.max_concurrent_trades:
                    logger.warning(
                        f"{log_prefix} Signal REJECTED. Max concurrent trades reached ({active_count}/{self.rm.max_concurrent_trades})."
                    )
                    self.trade_logger.log_event(
                        event_type="SIGNAL_REJECTED_MAX_TRADES",
                        data={
                            "symbol": signal.symbol,
                            "strategy": signal.strategy_name,
                            "direction": signal.direction.name,
                            "reason": f"Max trades reached ({active_count}/{self.rm.max_concurrent_trades})",
                            "details": signal.details,
                        },
                    )
                    return

                # Reserve the slot to prevent other signals from taking it while we do API calls
                placeholder_position = LivePosition(
                    symbol=signal.symbol,
                    direction=signal.direction,
                    entry_price=0.0,
                    initial_quantity=0.0,
                    remaining_quantity=0.0,
                    entry_time=time.time(),
                    strategy=signal.strategy_name,
                    initial_stop_loss=None,
                    current_sl_price=None,
                    initial_take_profit=None,
                    status="RESERVING",
                    market_type=initial_market_type,
                    client_order_id=f"RESERVE_{int(time.time() * 1000)}",
                )
                self._active_position_set(placeholder_position)

            logger.info(
                f"{log_prefix} Passed initial checks (throttle, cooldown, existing position). Reserved slot."
            )

            # Now we use the symbol lock for the heavy lifting
            symbol_lock = self._get_lock_for_position(
                signal.symbol, initial_market_type
            )
            async with symbol_lock:
                # Re-verify the placeholder is still ours
                pos_check = self._active_position_get(
                    signal.symbol, initial_market_type
                )
                if not pos_check or pos_check.status != "RESERVING":
                    logger.warning(f"{log_prefix} Placeholder position lost. Aborting.")
                    return

                if not await self.rm.is_symbol_trading_allowed(signal.symbol):
                    logger.warning(
                        f"{log_prefix} Signal REJECTED by rm.is_symbol_trading_allowed (general block)."
                    )
                    self.trade_logger.log_event(
                        event_type="SIGNAL_REJECTED_RISK_BLOCK",
                        data={
                            "symbol": signal.symbol,
                            "strategy": signal.strategy_name,
                            "direction": signal.direction.name,
                            "reason": "Symbol blocked by RiskManager (general block)",
                            "details": signal.details,
                        },
                    )
                    # Cleanup the placeholder
                    async with self._positions_dict_lock:
                        self._active_position_pop(signal.symbol, initial_market_type)
                    return

            # 2. CONFIGURATION SEARCH AND ML-FLAG CHECK
            running_instance_config = None
            instance_user_id = None
            instance_config_id = None
            target_config_id = (
                signal.details.get("strategy_config_id")
                if isinstance(signal.details, dict)
                else None
            )

            async with self.instances_lock:
                if (
                    target_config_id
                    and target_config_id in self.running_strategy_instances
                ):
                    _instance, config_dict = self.running_strategy_instances[
                        target_config_id
                    ]
                    running_instance_config = config_dict
                    instance_config_id = target_config_id
                else:
                    for config_id_key, (
                        instance,
                        config_dict,
                    ) in self.running_strategy_instances.items():
                        if instance.NAME == signal.strategy_name:
                            running_instance_config = config_dict
                            instance_config_id = config_id_key
                            break

            if not running_instance_config:
                logger.error(
                    f"{log_prefix} CRITICAL: Running configuration not found for strategy '{signal.strategy_name}'. Signal ignored."
                )
                return

            # NEW: Get mode and select executor
            mode = running_instance_config.get(
                "mode", "live"
            )  # Default to 'live' for safety
            market_type = self._market_type_for_strategy_config(running_instance_config)
            if isinstance(signal.details, dict):
                signal.details["market_type"] = market_type
                signal.details["marketType"] = (
                    "SPOT" if market_type == "spot" else "FUTURES"
                )
            executor = self._executor_for_market_type(market_type, mode=mode)
            if not executor:
                logger.error(
                    f"{log_prefix} No executor found for mode='{mode}', market='{market_type}'. Signal ignored."
                )
                return
            logger.info(
                f"{log_prefix} Using executor for mode: '{mode}', market: '{market_type}'"
            )

            config_data_for_signal = (
                running_instance_config.get("config_data", {})
                if isinstance(running_instance_config, dict)
                else {}
            )
            management_blocks_for_signal = []
            if isinstance(config_data_for_signal, dict):
                management_blocks_for_signal = config_data_for_signal.get(
                    "positionManagement", config_data_for_signal.get("management", [])
                )

            def _uses_dca_or_grid_management(node):
                if isinstance(node, dict):
                    if str(node.get("type", "")).lower() in {
                        "dca_management",
                        "grid_management",
                    }:
                        return True
                    return any(
                        _uses_dca_or_grid_management(value) for value in node.values()
                    )
                if isinstance(node, list):
                    return any(_uses_dca_or_grid_management(item) for item in node)
                return False

            if _uses_dca_or_grid_management(management_blocks_for_signal):
                if not isinstance(signal.details, dict):
                    signal.details = {}
                signal.details["uses_dca_or_grid_management"] = True
                signal.details["skip_min_rr_for_dca_grid"] = True

            use_ml_confirmation_flag = running_instance_config.get(
                "use_ml_confirmation", False
            )
            instance_user_id = running_instance_config.get("user_id")

            logger.info(
                f"{log_prefix} Found parent config '{instance_config_id}'. User ID: {instance_user_id}, Use ML Confirmation: {use_ml_confirmation_flag}"
            )

            # 3. ML SIGNAL CONFIRMATION (if enabled)
            ml_confirmed_this_signal_live = True
            ml_confirm_proba_1_live: Optional[float] = None
            ml_confirm_proba_0_live: Optional[float] = None

            if use_ml_confirmation_flag:
                logger.info(
                    f"{log_prefix} ML confirmation is ENABLED for this instance. Running check..."
                )

                if (
                    self._ml_confirmation_enabled_live_runtime
                    and self._ml_confirmation_feature_extractor_live
                    and self._ml_confirmation_pipeline_live
                ):
                    is_strategy_eligible_for_ml_confirm = (
                        not config.ML_CONFIRMATION_STRATEGIES
                        or signal.strategy_name in config.ML_CONFIRMATION_STRATEGIES
                    )

                    if is_strategy_eligible_for_ml_confirm:
                        try:
                            default_tf_entry = config.get_strategy_param(
                                signal.strategy_name, "entry_timeframe", "1m"
                            )
                            signal_main_tf = config.get_strategy_param(
                                signal.strategy_name,
                                "candle_timeframe",
                                default_tf_entry,
                            )

                            live_kline_history_df: Optional[
                                pd.DataFrame
                            ] = await self.consumer.get_kline_history(
                                signal.symbol,
                                signal_main_tf,
                                limit=200,
                                market_type=market_type,
                            )
                            live_agg_trades_list: Optional[List[Dict[str, Any]]] = None

                            # DETAILED ML LOGGING
                            agg_trades_count = 0
                            if self._ml_confirmation_feature_extractor_live.aggtrade_feature_configs:
                                live_agg_df = await self.consumer.get_recent_trades(
                                    signal.symbol, limit=200, market_type=market_type
                                )
                                if live_agg_df is not None:
                                    live_agg_trades_list = live_agg_df.to_dict(
                                        "records"
                                    )
                                    agg_trades_count = len(live_agg_trades_list)
                                    logger.info(
                                        f"{log_prefix} LIVE ML: Got {agg_trades_count} aggTrade records for feature extraction"
                                    )
                                else:
                                    logger.warning(
                                        f"{log_prefix} LIVE ML: No aggTrade data available for {signal.symbol}. AggTrade features will be zero."
                                    )
                            else:
                                logger.debug(
                                    f"{log_prefix} LIVE ML: No aggTrade features configured, skipping aggTrade fetch."
                                )

                            if (
                                live_kline_history_df is None
                                or live_kline_history_df.empty
                            ):
                                logger.warning(
                                    f"{log_prefix} LIVE ML Confirm: Missing kline data for {signal_main_tf}. Skipping confirmation (fail-open)."
                                )
                            else:
                                current_candle_data_for_fe_live = (
                                    live_kline_history_df.iloc[-1].to_dict()
                                )
                                for k_pi, v_pi in pair_info.items():
                                    current_candle_data_for_fe_live[k_pi] = v_pi
                                current_candle_data_for_fe_live[
                                    "time_since_last_signal_sec"
                                ] = pair_info.get(
                                    "time_since_last_signal_sec", float("inf")
                                )
                                current_candle_data_for_fe_live["candle_timeframe"] = (
                                    signal_main_tf
                                )

                                live_current_index = len(live_kline_history_df) - 1

                                last_kline_ts_live = live_kline_history_df.index[-1]
                                tf_minutes = 1
                                if (
                                    signal_main_tf.endswith("m")
                                    and signal_main_tf[:-1].isdigit()
                                ):
                                    tf_minutes = int(signal_main_tf[:-1])
                                elif (
                                    signal_main_tf.endswith("h")
                                    and signal_main_tf[:-1].isdigit()
                                ):
                                    tf_minutes = int(signal_main_tf[:-1]) * 60
                                candle_duration_live_td = timedelta(minutes=tf_minutes)
                                approx_current_candle_end_ts_live_ms = int(
                                    (
                                        last_kline_ts_live + candle_duration_live_td
                                    ).timestamp()
                                    * 1000
                                )

                                raw_features_live = self._ml_confirmation_feature_extractor_live.extract_features_optimized(
                                    current_candle_data=current_candle_data_for_fe_live,
                                    agg_trades_list=live_agg_trades_list,
                                    full_kline_history=live_kline_history_df,
                                    current_index=live_current_index,
                                    current_timestamp_ms=approx_current_candle_end_ts_live_ms,
                                )

                                if raw_features_live:
                                    # Logging extracted features for debugging
                                    logger.info(
                                        f"{log_prefix} LIVE ML: Extracted {len(raw_features_live)} features. "
                                        f"Sample values: { {k: f'{v:.4f}' for k, v in list(raw_features_live.items())[:3]} }"
                                    )
                                    norm_features_live = self._ml_confirmation_feature_extractor_live.normalize_features(
                                        raw_features_live
                                    )
                                    if norm_features_live:
                                        proba_map_live = self._ml_confirmation_pipeline_live.predict_proba_one(
                                            norm_features_live
                                        )
                                        if proba_map_live:
                                            ml_confirm_proba_1_live = (
                                                proba_map_live.get(1, 0.0)
                                            )
                                            ml_confirm_proba_0_live = (
                                                proba_map_live.get(0, 0.0)
                                            )

                                            approved_by_ml_pred_live = False
                                            if (
                                                ml_confirm_proba_1_live
                                                >= config.ML_CONFIRMATION_PROBABILITY_THRESHOLD
                                            ):
                                                approved_by_ml_pred_live = True
                                                if (
                                                    config.ML_CONFIRMATION_REJECT_IF_OPPOSITE_HIGH_PROB
                                                    and ml_confirm_proba_0_live
                                                    >= config.ML_CONFIRMATION_OPPOSITE_PROB_THRESHOLD
                                                ):
                                                    approved_by_ml_pred_live = False
                                                    logger.info(
                                                        f"{log_prefix} LIVE ML REJECTED (OppositeProb High): P(1)={ml_confirm_proba_1_live:.3f}, P(0)={ml_confirm_proba_0_live:.3f} vs Thr={config.ML_CONFIRMATION_OPPOSITE_PROB_THRESHOLD:.2f}"
                                                    )

                                            if approved_by_ml_pred_live:
                                                logger.info(
                                                    f"{log_prefix} LIVE ML Confirmed. P(1)={ml_confirm_proba_1_live:.3f}, P(0)={ml_confirm_proba_0_live:.3f}"
                                                )
                                            else:
                                                ml_confirmed_this_signal_live = False
                                                logger.info(
                                                    f"{log_prefix} LIVE ML REJECTED (Threshold/Opposite). P(1)={ml_confirm_proba_1_live:.3f} (Thr={config.ML_CONFIRMATION_PROBABILITY_THRESHOLD:.2f}), P(0)={ml_confirm_proba_0_live:.3f}"
                                                )
                                        else:
                                            logger.warning(
                                                f"{log_prefix} LIVE ML Confirm: predict_proba_one returned None. Allowing signal (fail-open)."
                                            )
                                    else:
                                        logger.warning(
                                            f"{log_prefix} LIVE ML Confirm: Failed to normalize features. Allowing signal (fail-open)."
                                        )
                                else:
                                    logger.warning(
                                        f"{log_prefix} LIVE ML Confirm: Failed to extract features. Allowing signal (fail-open)."
                                    )
                        except Exception as e_ml_live_proc:
                            logger.error(
                                f"{log_prefix} Error during LIVE ML confirmation processing: {e_ml_live_proc}",
                                exc_info=True,
                            )
                            ml_confirmed_this_signal_live = True
                    else:
                        logger.debug(
                            f"{log_prefix} Strategy '{signal.strategy_name}' not in ML_CONFIRMATION_STRATEGIES. Skipping LIVE ML confirmation."
                        )
                else:
                    logger.debug(
                        f"{log_prefix} Live ML Confirmation not enabled or components not ready. Skipping."
                    )

                signal.details["ml_confirmed_live"] = ml_confirmed_this_signal_live
                signal.details["ml_confirm_proba_1_live"] = ml_confirm_proba_1_live
                signal.details["ml_confirm_proba_0_live"] = ml_confirm_proba_0_live
                signal.details["ml_threshold_good_live"] = (
                    config.ML_CONFIRMATION_PROBABILITY_THRESHOLD
                )
                if config.ML_CONFIRMATION_REJECT_IF_OPPOSITE_HIGH_PROB:
                    signal.details["ml_threshold_bad_reject_live"] = (
                        config.ML_CONFIRMATION_OPPOSITE_PROB_THRESHOLD
                    )

            if not ml_confirmed_this_signal_live:
                logger.warning(f"{log_prefix} Signal REJECTED by LIVE ML confirmation.")
                self.trade_logger.log_event(
                    event_type="SIGNAL_REJECTED_ML_LIVE",
                    data={
                        "symbol": signal.symbol,
                        "strategy": signal.strategy_name,
                        "direction": signal.direction.name,
                        "reason": "Live ML Confirmation Failed/Rejected",
                        "ml_prob_good_signal": ml_confirm_proba_1_live,
                        "ml_prob_bad_signal": ml_confirm_proba_0_live,
                        "ml_threshold_good": config.ML_CONFIRMATION_PROBABILITY_THRESHOLD,
                        "ml_threshold_bad_reject": config.ML_CONFIRMATION_OPPOSITE_PROB_THRESHOLD
                        if config.ML_CONFIRMATION_REJECT_IF_OPPOSITE_HIGH_PROB
                        else None,
                        "details": signal.details,
                    },
                )
                return

            self._recent_signals[signal_key_throttle] = current_time

            # 4. CHECK VIA RISK MANAGER

            lot_params = await self._get_market_info(
                signal.symbol, "lot_params", market_type=market_type
            )
            min_notional = await self._get_market_info(
                signal.symbol, "min_notional", market_type=market_type
            )
            logger.debug(
                f"{log_prefix} LotParams: {lot_params}, MinNotional: {min_notional}"
            )

            # Receiving FOUR values from assess_signal
            (
                approved_by_rm,
                initial_quantity_adj,
                initial_risk_usd_planned_val,
                rejection_reason,
            ) = await self.rm.assess_signal(
                signal, lot_params, min_notional, mode=mode, executor_override=executor
            )
            logger.info(
                f"{log_prefix} RiskManager assess_signal result: Approved={approved_by_rm}, Qty={initial_quantity_adj}, RiskPlanned=${initial_risk_usd_planned_val}, Reason='{rejection_reason}'"
            )

            if (
                not approved_by_rm
                or initial_quantity_adj is None
                or initial_quantity_adj <= 0
            ):
                # Use the received reason for a more accurate log
                final_rejection_reason = (
                    rejection_reason or "Unknown reason from RiskManager"
                )
                if initial_quantity_adj is None or initial_quantity_adj <= 0:
                    final_rejection_reason = f"Risk Manager calculated invalid quantity ({initial_quantity_adj})"

                logger.warning(
                    f"{log_prefix} Signal REJECTED. Reason: {final_rejection_reason}."
                )
                self.trade_logger.log_event(
                    event_type="SIGNAL_REJECTED",
                    data={
                        "symbol": signal.symbol,
                        "strategy": signal.strategy_name,
                        "direction": signal.direction.name,
                        "reason": final_rejection_reason,
                        **signal.details,
                    },
                )
                return

            final_initial_quantity = initial_quantity_adj
            entry_client_order_id = f"x-entry-{uuid.uuid4().hex[:14]}"

            if self.realtime_ml_logger and getattr(
                config, "LOG_REALTIME_ML_DATA", False
            ):
                self.loop.create_task(
                    self._log_signal_context_for_ml(
                        signal,
                        pair_info,
                        entry_client_order_id,
                        initial_risk_usd_planned_val,
                        market_data_snapshot=market_data_snapshot,
                    ),
                    name=f"LogMLContext_{signal.symbol}_{entry_client_order_id}",
                )

            self.trade_logger.log_event(
                event_type="SIGNAL_APPROVED",
                data={
                    "symbol": signal.symbol,
                    "strategy": signal.strategy_name,
                    "direction": signal.direction.name,
                    "entry_price": signal.entry_price,
                    "initial_stop_loss": signal.stop_loss,
                    "initial_take_profit": signal.take_profit,
                    "quantity": final_initial_quantity,
                    "client_order_id": entry_client_order_id,
                    "details": signal.details,
                    "initial_risk_usd_planned": initial_risk_usd_planned_val,
                },
            )
            logger.info(
                f"{log_prefix} Signal APPROVED by RiskManager. Final Qty: {final_initial_quantity}, EntryCID: {entry_client_order_id}"
            )

            # 5. PLACING AN ENTRY ORDER

            # ==============================================================================
            # 🔥 CRITICAL PROTECTION: PRE-FLIGHT API CHECK 🔥
            # Making a direct request to the exchange: "Do I ALREADY have a position for this symbol?"
            # ==============================================================================
            try:
                real_positions = (
                    await executor.get_open_positions()
                    if getattr(executor, "supports_positions", False)
                    else []
                )
                # Search for a position by symbol where the size is not 0
                existing_on_exchange = next(
                    (
                        p
                        for p in real_positions
                        if p["symbol"] == signal.symbol and float(p["positionAmt"]) != 0
                    ),
                    None,
                )

                if existing_on_exchange:
                    logger.critical(
                        f"{log_prefix} STOP! Exchange already has position for {signal.symbol}: {existing_on_exchange}. Aborting duplicate entry."
                    )

                    # Urgently synchronizing local state
                    async with self._positions_dict_lock:
                        # If we don't have this position, create an "orphan" so the controller knows about it
                        if not self._active_position_get(signal.symbol, market_type):
                            logger.info(
                                f"{log_prefix} Adopting found position immediately to prevent further spam."
                            )

                    # Aborting execution, do not send the order!
                    return
            except Exception as e_preflight:
                # If the check failed due to a network error, it's better to skip the entry than to duplicate it
                logger.error(
                    f"{log_prefix} Pre-flight check failed: {e_preflight}. Aborting signal for safety.",
                    exc_info=True,
                )
                return

            binance_side = "BUY" if signal.direction == SignalDirection.LONG else "SELL"

            entry_order_params = {
                "symbol": signal.symbol,
                "side": binance_side,
                "quantity": final_initial_quantity,
                "newClientOrderId": entry_client_order_id,
                # For grouping trades by positions in the DB
                "entry_client_order_id": entry_client_order_id,
                "strategy_config_id": pair_info.get("strategy_config_id"),
                "signal_details": signal.details,
            }

            schedule_exits_immediately = False

            if signal.mode == OrderMode.MARKET:
                entry_order_params["type"] = "MARKET"
                schedule_exits_immediately = False
            elif signal.mode in [OrderMode.LIMIT_BREAK, OrderMode.LIMIT_RETEST]:
                if signal.entry_price is None:
                    logger.error(
                        f"{log_prefix} LIMIT order requires entry_price. Signal: {signal}"
                    )
                    return
                tick_size = (
                    await self._get_market_info(
                        signal.symbol, "tick_size", market_type=market_type
                    )
                    or config.DEFAULT_TICK_SIZE
                )
                rounding_mode = (
                    ROUND_DOWN if signal.direction == SignalDirection.LONG else ROUND_UP
                )
                rounded_entry = self._round_price(
                    signal.entry_price, tick_size, rounding_mode
                )
                if rounded_entry is None or rounded_entry <= 0:
                    logger.error(
                        f"{log_prefix} Invalid rounded LIMIT price {rounded_entry}. Original: {signal.entry_price}. Signal: {signal}"
                    )
                    return
                entry_order_params.update(
                    {
                        "type": "LIMIT",
                        "price": f"{rounded_entry:.8f}",
                        "timeInForce": "GTC",
                    }
                )
                schedule_exits_immediately = False
            else:
                logger.error(
                    f"{log_prefix} Unsupported order mode: {signal.mode}. Signal: {signal}"
                )
                return

            # Initializing variables before their possible use
            scale_in_rules = []
            max_entries = None
            conditional_management_rules = []
            dca_management_params = None

            if running_instance_config and "config_data" in running_instance_config:
                config_data = running_instance_config["config_data"]
                management_rules = config_data.get(
                    "management", config_data.get("positionManagement", [])
                )
                for rule in management_rules:
                    if rule.get("type") == "scale_in":
                        scale_in_rules.append(rule)
                        if "params" in rule and "max_entries" in rule["params"]:
                            max_entries = rule["params"]["max_entries"]
                    elif rule.get("type") == "conditional_management":
                        conditional_management_rules.append(rule)
                    elif (
                        rule.get("type") == "dca_management"
                        and dca_management_params is None
                    ):
                        dca_management_params = copy.deepcopy(rule.get("params", {}))

            # Create position BEFORE placing the order to avoid race condition
            # when ORDER_UPDATE arrives before the position is added to _active_positions
            new_position = LivePosition(
                symbol=signal.symbol,
                direction=signal.direction,
                entry_price=None,  # Will be updated after execution
                initial_quantity=final_initial_quantity,
                remaining_quantity=final_initial_quantity,
                entry_time=time.time(),
                strategy=signal.strategy_name,
                initial_stop_loss=signal.stop_loss,
                initial_take_profit=signal.take_profit,
                current_sl_price=signal.stop_loss,
                entry_atr=pair_info.get("atr"),
                no_stop_loss=signal.no_stop_loss,
                trigger_price=signal.trigger_price,
                signal_details=signal.details,
                entry_order_id=None,  # Will be set after placement
                entry_client_order_id=entry_client_order_id,
                entry_order_status="PENDING",  # Temporary status
                status="PENDING_ENTRY",
                time_status_open=None,
                move_sl_to_be_enabled=signal.move_sl_to_be_on_first_tp,
                partial_tp_orders=[],
                original_partial_targets_plan=list(signal.partial_targets)
                if signal.partial_targets
                else None,
                initial_risk_usd_planned=initial_risk_usd_planned_val,
                exit_orders_scheduled_by_process_signal=schedule_exits_immediately,
                user_id=instance_user_id,
                config_id=instance_config_id,
                scale_in_rules=scale_in_rules,
                max_entries=max_entries,
                conditional_management_rules=conditional_management_rules,
                dca_management_params=dca_management_params,
                mode=mode,
                market_type=market_type,
                api_key_id=self.api_key_id,
            )

            # Add position to the dictionary BEFORE placing the order
            async with self._positions_dict_lock:
                self._active_position_set(new_position)
            logger.info(
                f"{log_prefix} Position record pre-created with status PENDING_ENTRY. Will be updated after order placement."
            )

            entry_order_response: Optional[Dict[str, Any]] = None
            try:
                logger.info(f"{log_prefix} Placing ENTRY order: {entry_order_params}")
                symbol_arg = entry_order_params.pop("symbol")
                side_arg = entry_order_params.pop("side")
                type_arg = entry_order_params.pop("type")
                logger.debug(
                    f"{log_prefix} Prepared entry order params: {entry_order_params}"
                )
                entry_order_response = await executor.place_order(
                    symbol=symbol_arg,
                    side=side_arg,
                    order_type=type_arg,
                    **entry_order_params,
                )
                logger.info(
                    f"{log_prefix} Executor place_order response: {entry_order_response}"
                )
            except Exception as e_exec:
                logger.error(
                    f"{log_prefix} Exception placing entry order: {e_exec}",
                    exc_info=True,
                )

                # Do not delete the position immediately on timeout
                is_timeout = isinstance(e_exec, (asyncio.TimeoutError,))

                if is_timeout:
                    # Do not delete! Mark as 'UNKNOWN' so that reconcile can handle it
                    pos_to_update = self._active_position_get(
                        signal.symbol, market_type
                    )
                    if pos_to_update:
                        pos_to_update.status = "UNKNOWN_ENTRY_STATE"
                        logger.critical(
                            f"{log_prefix} Timeout during order placement! Keeping position in UNKNOWN_ENTRY_STATE for reconciliation."
                        )
                else:
                    # If it's an explicit error (e.g., "Insufficient Balance"), it can be deleted
                    async with self._positions_dict_lock:
                        if self._active_position_get(signal.symbol, market_type):
                            self._active_position_pop(signal.symbol, market_type)
                return

            if not entry_order_response or entry_order_response.get("error"):
                err_msg = (
                    entry_order_response.get("msg", "Unknown error")
                    if isinstance(entry_order_response, dict)
                    else "No response"
                )
                logger.error(
                    f"{log_prefix} Entry order placement FAILED. Response: {err_msg}"
                )
                self.trade_logger.log_event(
                    event_type="ORDER_FAILED",
                    data={
                        "order_type": "ENTRY",
                        "reason": err_msg,
                        **(entry_order_response or {}),
                    },
                )
                # Remove the position because the order was not placed
                async with self._positions_dict_lock:
                    if self._active_position_get(signal.symbol, market_type):
                        self._active_position_pop(signal.symbol, market_type)
                return

            entry_order_id_resp = entry_order_response.get("orderId")
            if entry_order_id_resp is not None:
                entry_order_id_resp = str(entry_order_id_resp)
            entry_order_status_resp = entry_order_response.get(
                "status", "UNKNOWN"
            ).upper()
            position_status_init = "PENDING_ENTRY"
            calculated_entry_price_for_pos = None

            if signal.mode == OrderMode.MARKET and entry_order_status_resp == "FILLED":
                position_status_init = "OPEN"
                avg_price_from_resp_market_str = entry_order_response.get(
                    "avgPrice", entry_order_response.get("price")
                )
                avg_price_from_resp_market = (
                    float(avg_price_from_resp_market_str)
                    if avg_price_from_resp_market_str
                    else 0.0
                )

                if avg_price_from_resp_market == 0 and entry_order_response.get(
                    "fills"
                ):
                    avg_price_from_resp_market = (
                        await self._calculate_avg_fill_price(
                            entry_order_response.get("fills", [])
                        )
                        or 0.0
                    )

                if avg_price_from_resp_market > 0:
                    calculated_entry_price_for_pos = avg_price_from_resp_market
                else:
                    logger.error(
                        f"{log_prefix} Could not determine entry price for immediately FILLED MARKET order. Using trigger_price ({signal.trigger_price}) fallback."
                    )
                    calculated_entry_price_for_pos = signal.trigger_price

            logger.info(
                f"{log_prefix} Entry order placed: ID={entry_order_id_resp}, ClientID={entry_client_order_id}, BinanceStatus={entry_order_status_resp}, InternalPosStatus={position_status_init}"
            )
            self.trade_logger.log_event(
                event_type="ORDER_PLACED",
                data={"order_type": "ENTRY", **entry_order_response},
            )

            planned_partial_tp_orders_initial: List[PartialTpOrderInfo] = []
            initial_tp_status = (
                "VIRTUAL_PENDING"
                if self._position_should_use_virtual_spot_tps(new_position, executor)
                else "PENDING_PLACEMENT"
            )
            if signal.partial_targets and signal.mode == OrderMode.MARKET:
                for pt_config in signal.partial_targets:
                    qty_pt_raw = final_initial_quantity * pt_config.fraction
                    qty_pt_adj = self.rm._adjust_and_round_quantity(
                        qty_pt_raw,
                        signal.symbol,
                        pt_config.price,
                        lot_params,
                        min_notional,
                    )

                    if qty_pt_adj is not None and qty_pt_adj > 0:
                        planned_partial_tp_orders_initial.append(
                            PartialTpOrderInfo(
                                target_price=pt_config.price,
                                orig_fraction=pt_config.fraction,
                                quantity=qty_pt_adj,
                                status=initial_tp_status,
                            )
                        )

            # Updating position with data from the exchange response
            symbol_lock_update = self._get_lock_for_position(signal.symbol, market_type)
            async with symbol_lock_update:
                position = self._active_position_get(signal.symbol, market_type)
                if position:
                    position.entry_order_id = entry_order_id_resp
                    position.entry_order_status = entry_order_status_resp

                    # Only update status from PENDING_ENTRY. If WS already set it to OPEN/CLOSED, don't revert.
                    if position.status == "PENDING_ENTRY":
                        position.status = position_status_init
                        if position_status_init == "OPEN":
                            position.time_status_open = time.time()
                            # Only set initial TP plan if transitioning to OPEN here
                            if (
                                not position.partial_tp_orders
                                and planned_partial_tp_orders_initial
                            ):
                                position.partial_tp_orders = (
                                    planned_partial_tp_orders_initial
                                )

                    # Only update entry_price if WS hasn't already set it (from _HandleEntryFill)
                    if (
                        position.entry_price is None
                        and calculated_entry_price_for_pos is not None
                        and calculated_entry_price_for_pos > 0
                    ):
                        position.entry_price = calculated_entry_price_for_pos

            logger.info(
                f"{log_prefix} Position record updated after order placement. Status: {position_status_init}. Original TP plan saved ({len(new_position.original_partial_targets_plan or [])} targets). For User ID: {new_position.user_id}, Config ID: {new_position.config_id}"
            )

            if new_position.user_id and new_position.status in [
                "PENDING_ENTRY",
                "OPEN",
            ]:
                async for db_session in (
                    self.get_db_session()
                ):  # Use async for to iterate over the generator
                    user = await crud.admin_get_user_details(
                        db_session, new_position.user_id
                    )
                    if user and user.push_subscription:
                        try:
                            self.loop.create_task(
                                asyncio.to_thread(
                                    send_push_notification,
                                    subscription_info=user.push_subscription,
                                    title="Position opened!",
                                    body=f"Opened {new_position.direction.name} position for {new_position.symbol} ({new_position.strategy})",
                                    tag=f"position-opened-{new_position.entry_client_order_id}",
                                ),
                                name=f"PushNotify_PosOpened_{new_position.symbol}",
                            )
                        except Exception as push_exc:
                            logger.error(
                                f"Failed to send push notification for position opened {new_position.entry_client_order_id} to user {new_position.user_id}: {push_exc}",
                                exc_info=True,
                            )

            # 6. TELEGRAM NOTIFICATION (POSITION OPENING)
            if self.telegram_notifier and new_position.status in [
                "PENDING_ENTRY",
                "OPEN",
            ]:
                tick_size_for_tg = (
                    await self._get_market_info(
                        new_position.symbol, "tick_size", market_type=market_type
                    )
                    or config.DEFAULT_TICK_SIZE
                )
                base_asset_from_symbol = new_position.symbol
                if "USDT" in new_position.symbol.upper():
                    base_asset_from_symbol = new_position.symbol.upper().replace(
                        "USDT", ""
                    )
                elif "BUSD" in new_position.symbol.upper():
                    base_asset_from_symbol = new_position.symbol.upper().replace(
                        "BUSD", ""
                    )

                partial_targets_info_for_tg = []
                if new_position.original_partial_targets_plan:
                    lot_params_for_ptp = await self._get_market_info(
                        new_position.symbol, "lot_params", market_type=market_type
                    )
                    min_notional_for_ptp = await self._get_market_info(
                        new_position.symbol, "min_notional", market_type=market_type
                    )

                    for pt_plan in new_position.original_partial_targets_plan:
                        qty_for_this_pt_raw = (
                            new_position.initial_quantity * pt_plan.fraction
                        )
                        qty_for_this_pt_adj = self.rm._adjust_and_round_quantity(
                            qty_for_this_pt_raw,
                            new_position.symbol,
                            pt_plan.price,
                            lot_params_for_ptp,
                            min_notional_for_ptp,
                        )
                        partial_targets_info_for_tg.append(
                            {
                                "price": pt_plan.price,
                                "orig_fraction": pt_plan.fraction,
                                "quantity": qty_for_this_pt_adj
                                if qty_for_this_pt_adj is not None
                                else qty_for_this_pt_raw,
                            }
                        )

                self.loop.create_task(
                    self.telegram_notifier.new_position(
                        symbol=new_position.symbol,
                        direction=new_position.direction,
                        entry_price=new_position.entry_price
                        if new_position.entry_price is not None
                        else new_position.trigger_price,
                        quantity=new_position.initial_quantity,
                        base_asset=base_asset_from_symbol,
                        stop_loss=new_position.initial_stop_loss,
                        take_profit=new_position.initial_take_profit,
                        strategy=new_position.strategy,
                        client_order_id=new_position.entry_client_order_id,
                        signal_details=new_position.signal_details,
                        partial_targets_info=partial_targets_info_for_tg,
                        tick_size=tick_size_for_tg,
                        chat_id=self.user_telegram_chat_id,
                        market_type=self._market_type_for_position(new_position),
                        leverage=self._leverage_for_position(new_position),
                        api_key_name=self.api_key_name,
                    ),
                    name=f"TelegramNotify_NewPos_{new_position.symbol}",
                )

            # 7. PLACING SL/TP (if the MARKET order was FILLED immediately)

            if schedule_exits_immediately:
                logger.info(
                    f"{log_prefix} Scheduling exit orders immediately for {signal.mode} order."
                )
                exit_order_placement_coroutines = []

                if self._position_has_active_stop_target(new_position):
                    exit_order_placement_coroutines.append(
                        self._place_stop_loss(new_position)
                    )

                # Exchange trailing stop (if mode='exchange')
                exit_order_placement_coroutines.append(
                    self._place_exchange_trailing_stop(new_position)
                )

                use_virtual_spot_tps_now = self._position_should_use_virtual_spot_tps(
                    new_position, executor
                )

                if new_position.partial_tp_orders:
                    for i, ptp_info_item in enumerate(new_position.partial_tp_orders):
                        if use_virtual_spot_tps_now and ptp_info_item.status in {
                            "PENDING_PLACEMENT",
                            "VIRTUAL_PENDING",
                        }:
                            ptp_info_item.status = "VIRTUAL_PENDING"
                            logger.info(
                                f"{log_prefix} Spot TP #{i + 1} will be tracked virtually because SL locks base balance."
                            )
                        elif ptp_info_item.status == "PENDING_PLACEMENT":
                            exit_order_placement_coroutines.append(
                                self._place_partial_tp(
                                    new_position,
                                    ptp_info_item.target_price,
                                    ptp_info_item.quantity,
                                    ptp_info_item.orig_fraction,
                                    i,
                                )
                            )
                elif (
                    new_position.initial_take_profit is not None
                    and not use_virtual_spot_tps_now
                ):
                    qty_for_final_tp = self.rm._adjust_and_round_quantity(
                        new_position.initial_quantity,
                        signal.symbol,
                        new_position.initial_take_profit,
                        lot_params,
                        min_notional,
                    )
                    if qty_for_final_tp is not None and qty_for_final_tp > 0:
                        exit_order_placement_coroutines.append(
                            self._place_partial_tp(
                                new_position,
                                new_position.initial_take_profit,
                                qty_for_final_tp,
                                1.0,
                                -1,
                            )
                        )
                    else:
                        logger.error(
                            f"{log_prefix} Cannot place final TP for price {new_position.initial_take_profit}: Invalid quantity {qty_for_final_tp}. Skipping."
                        )

                if exit_order_placement_coroutines:
                    logger.info(
                        f"{log_prefix} Placing {len(exit_order_placement_coroutines)} exit order(s) synchronously for reliability."
                    )
                    try:
                        await asyncio.gather(
                            *exit_order_placement_coroutines, return_exceptions=True
                        )
                    except Exception as e:
                        logger.error(
                            f"{log_prefix} Error while placing exit orders: {e}",
                            exc_info=True,
                        )

            # 8. PROCESSING INSTANT MARKET ORDER EXECUTION
            if position_status_init == "OPEN":
                logger.info(
                    f"{log_prefix} Entry order (MARKET) reported as FILLED by REST API. Triggering fill handler..."
                )

                self.loop.create_task(
                    self._handle_entry_fill(
                        symbol=signal.symbol,
                        order_id=entry_order_id_resp,
                        client_order_id=entry_client_order_id,
                        avg_fill_price=new_position.entry_price,
                        cumulative_filled_qty=float(
                            entry_order_response.get("executedQty", 0)
                        ),
                        fills=entry_order_response.get("fills", []),
                        is_final_fill_status=True,
                        market_type=market_type,
                    ),
                    name=f"HandleImmediateFill_{signal.symbol}",
                )

            logger.info(f"{log_prefix} --- END PROCESSING SIGNAL ---")

        except Exception as e_proc_sig:
            logger.error(
                f"{log_prefix} UNEXPECTED EXCEPTION in _process_signal: {e_proc_sig}",
                exc_info=True,
            )
        finally:
            async with self._processing_signal_lock:
                if processing_key in self._processing_signal_for_symbol:
                    self._processing_signal_for_symbol.remove(processing_key)

    async def _handle_entry_fill(
        self,
        symbol: str,
        order_id,
        client_order_id: str,
        avg_fill_price: float,  # Average price of ALL executions of this order at the moment
        cumulative_filled_qty: float,  # Total executed quantity for this order
        fills: List[Dict],  # Details of the LAST execution (or all if REST API)
        is_final_fill_status: bool = False,  # New flag: True if it is FILLED or CANCELED/REJ/EXP
        market_type: Optional[str] = None,
    ):
        log_prefix = f"[_HandleEntryFill:{symbol}:{order_id}({client_order_id[:8]})]"
        logger.info(
            f"{log_prefix} --- STARTING ENTRY FILL HANDLING --- (FinalStatusUpdate: {is_final_fill_status})"
        )
        logger.debug(
            f"{log_prefix} Input: avg_fill_price_report={avg_fill_price}, cum_filled_qty_report={cumulative_filled_qty}, num_fills_details={len(fills)}"
        )

        position_to_manage_exits: Optional[LivePosition] = None
        dca_position_to_initialize: Optional[LivePosition] = None
        dca_params_to_initialize: Optional[Dict[str, Any]] = None
        executor_for_entry_fill = await self._get_executor_for_symbol(
            symbol, market_type=market_type
        )
        is_spot_market_for_entry_fill = self._executor_is_spot(executor_for_entry_fill)

        symbol_lock = self._get_lock_for_position(symbol, market_type)
        async with symbol_lock:
            position = self._active_position_get(symbol, market_type)

            if not position:
                logger.error(
                    f"{log_prefix} Position for symbol '{symbol}' not found. Cannot handle entry fill."
                )
                return

            if getattr(position, "entry_fill_processed", False):
                logger.info(
                    f"{log_prefix} Entry fill has already been processed for position {position.entry_client_order_id}. Skipping duplicate call."
                )
                return

            intentional_no_sl_mode = self._position_is_intentional_no_sl_mode(position)

            logger.info(
                f"{log_prefix} Found active position. Current PosStatus='{position.status}', EntryOrderID={position.entry_order_id}, CumFilledNow={cumulative_filled_qty:.8f}"
            )
            logger.debug(
                "%s Controller ID=%s Position ID=%s", log_prefix, id(self), id(position)
            )

            if position.status not in ["PENDING_ENTRY", "OPEN"]:
                logger.warning(
                    f"{log_prefix} Position status is '{position.status}', not PENDING_ENTRY or OPEN. Skipping."
                )
                return

            is_first_time_status_open = position.status == "PENDING_ENTRY"
            if is_first_time_status_open:
                position.status = "OPEN"
                position.time_status_open = time.time()
                logger.info(
                    f"{log_prefix} Position status changed from PENDING_ENTRY to OPEN. time_status_open set."
                )

            # More robust status update logic
            if is_final_fill_status:
                position.entry_fill_processed = True
                current_order_binance_status = position.entry_order_status
                if current_order_binance_status not in [
                    "FILLED",
                    "CANCELED",
                    "REJECTED",
                    "EXPIRED",
                    "CANCELED_WITH_PARTIAL_FILL",
                ]:
                    # Compare cumulative filled qty with the originally intended quantity
                    if cumulative_filled_qty >= position.initial_quantity * (
                        1 - 1e-9
                    ):  # Use tolerance for float comparison
                        position.entry_order_status = "FILLED"
                    elif cumulative_filled_qty > 0:
                        position.entry_order_status = "CANCELED_WITH_PARTIAL_FILL"
                    else:
                        position.entry_order_status = "CANCELED_NO_FILL"
                    logger.info(
                        f"{log_prefix} Entry order status updated to (effective) '{position.entry_order_status}' due to final fill update."
                    )

            # Accumulating entry commission
            for fill in fills:
                try:
                    fill_comm = float(fill.get("commission", 0))
                    if fill_comm > 0:
                        position.entry_commission += fill_comm
                        logger.info(
                            f"{log_prefix} Added entry fill commission: {fill_comm}. Total entry_commission={position.entry_commission}"
                        )
                except Exception as e:
                    logger.error(f"{log_prefix} Error adding fill commission: {e}")

            # Recalculate the average entry price based on the TOTAL executed volume if there is a previous price
            # avg_fill_price from the argument is the AVERAGE of ALL executions of this order up to the current moment.
            self._append_fill_execution_events(
                position,
                event_type="ENTRY",
                execution_type="ENTRY",
                fills=fills,
                fallback_price=avg_fill_price,
                fallback_quantity=cumulative_filled_qty,
                order_id=order_id,
                client_order_id=client_order_id,
            )

            effective_entry_price_candidate = (
                avg_fill_price  # Using the overall average price
            )

            if (
                effective_entry_price_candidate is not None
                and effective_entry_price_candidate > 0
            ):
                if (
                    position.entry_price is None
                    or abs(position.entry_price - effective_entry_price_candidate)
                    > 1e-9 * effective_entry_price_candidate
                    or is_first_time_status_open
                ):
                    logger.info(
                        f"{log_prefix} Updating position entry_price from {position.entry_price} to {effective_entry_price_candidate:.8f}"
                    )
                    position.entry_price = effective_entry_price_candidate
            elif position.entry_price is None:
                fallback_price = position.trigger_price or (
                    position.signal_details.get("entry_price")
                    if position.signal_details
                    else None
                )
                if fallback_price:
                    logger.warning(
                        f"{log_prefix} Using trigger/signal price as fallback for entry: {fallback_price:.8f}"
                    )
                    position.entry_price = fallback_price
                else:
                    logger.error(
                        f"{log_prefix} CRITICAL: Cannot determine entry price for position!"
                    )

            logger.debug(
                f"{log_prefix} Final effective entry_price for position: {position.entry_price}"
            )

            if (
                cumulative_filled_qty <= 0 and is_final_fill_status
            ):  # If final status and 0 executed
                logger.error(
                    f"{log_prefix} Entry final fill with zero/negative qty ({cumulative_filled_qty}). Removing position."
                )
                self._active_position_pop(symbol, market_type)
                # Canceling exit orders is not needed here, as they should not have been placed
                return

            # Updating initial_quantity and remaining_quantity to the CURRENT executed
            if (
                abs(cumulative_filled_qty - position.initial_quantity)
                > 1e-9 * position.initial_quantity
                or is_first_time_status_open
            ):
                logger.info(
                    f"{log_prefix} Position initial_quantity updating from {position.initial_quantity:.8f} to {cumulative_filled_qty:.8f}"
                )
                position.initial_quantity = cumulative_filled_qty
            # remaining_quantity must always be equal to initial_quantity at this stage (before the first exit)
            if (
                abs(cumulative_filled_qty - position.remaining_quantity)
                > 1e-9 * cumulative_filled_qty
                or is_first_time_status_open
            ):
                logger.info(
                    f"{log_prefix} Position remaining_quantity updating from {position.remaining_quantity:.8f} to {cumulative_filled_qty:.8f}"
                )
                position.remaining_quantity = cumulative_filled_qty

            should_check_immediate_dca = (
                is_first_time_status_open or is_final_fill_status
            )
            if should_check_immediate_dca:
                dca_params_candidate = copy.deepcopy(
                    getattr(position, "dca_management_params", None)
                )
                if dca_params_candidate:
                    step_type = dca_params_candidate.get("step_type", "percentage")
                    max_sos = int(dca_params_candidate.get("max_safety_orders", 0) or 0)
                    if (
                        max_sos > 0
                        and step_type in ["percentage", "atr"]
                        and not position.dca_order_ids
                        and not getattr(position, "dca_grid_init_in_progress", False)
                    ):
                        position.dca_grid_init_triggered = None
                        position.dca_grid_init_in_progress = True
                        dca_position_to_initialize = LivePosition(**vars(position))
                        dca_params_to_initialize = dca_params_candidate
                        logger.info(
                            f"{log_prefix} Scheduling immediate DCA grid initialization after entry fill."
                        )

            # Recalculation and placement of SL
            # SL price should be recalculated only once upon the first execution or if the entry price has changed significantly
            # Here we will always recalculate SL and cancel/place a new one.
            if (
                position.entry_price
                and position.entry_price > 0
                and not intentional_no_sl_mode
            ):
                original_signal_sl = position.initial_stop_loss  # From signal
                original_signal_entry_price = (
                    position.trigger_price or position.signal_details.get("entry_price")
                )

                if (
                    original_signal_entry_price
                    and original_signal_entry_price > 0
                    and original_signal_sl is not None
                ):
                    stop_loss_distance_abs = abs(
                        Decimal(str(original_signal_entry_price))
                        - Decimal(str(original_signal_sl))
                    )
                    new_sl_price_dec = (
                        (Decimal(str(position.entry_price)) - stop_loss_distance_abs)
                        if position.direction == SignalDirection.LONG
                        else (
                            Decimal(str(position.entry_price)) + stop_loss_distance_abs
                        )
                    )
                    tick_size_sl = (
                        await self._get_market_info(
                            symbol,
                            "tick_size",
                            market_type=self._market_type_for_position(position),
                        )
                        or config.DEFAULT_TICK_SIZE
                    )
                    rounded_new_sl_price = self._round_price(
                        float(new_sl_price_dec),
                        tick_size_sl,
                        ROUND_DOWN
                        if position.direction == SignalDirection.LONG
                        else ROUND_UP,
                    )
                    if rounded_new_sl_price and rounded_new_sl_price > 0:
                        if position.current_sl_price is None:
                            logger.info(
                                f"{log_prefix} SL price recalculated to {rounded_new_sl_price:.8f}. Previous: NONE"
                            )
                            position.current_sl_price = rounded_new_sl_price
                            position.sl_placement_initiated = False
                            if position.current_sl_order_id:
                                logger.info(
                                    f"{log_prefix} Old SL order {position.current_sl_order_id} will be cancelled for SL price update."
                                )
                        else:
                            if (
                                abs(position.current_sl_price - rounded_new_sl_price)
                                > tick_size_sl / 2
                            ):  # If the SL price has changed
                                logger.info(
                                    f"{log_prefix} SL price recalculated to {rounded_new_sl_price:.8f}. Previous: {position.current_sl_price if position.current_sl_price is not None else 'NONE'}"
                                )
                                position.current_sl_price = rounded_new_sl_price
                                # Resetting flags so SL can be repositioned
                                position.sl_placement_initiated = False
                                if position.current_sl_order_id:  # If there was an old SL, it will need to be canceled
                                    logger.info(
                                        f"{log_prefix} Old SL order {position.current_sl_order_id} will be cancelled for SL price update."
                                    )
                        # else: # SL price has not changed significantly
                    else:
                        logger.error(
                            f"{log_prefix} Failed to recalculate a valid SL price. Using previous: {position.current_sl_price}"
                        )

            # Logic for TP - only if it is the FINAL ENTRY STATUS
            if is_final_fill_status:
                logger.info(
                    f"{log_prefix} Final fill status for entry. Proceeding to place/update Take Profit orders based on final qty {position.initial_quantity:.8f}."
                )
                use_virtual_spot_tps = self._position_should_use_virtual_spot_tps(
                    position, executor_for_entry_fill
                )
                planned_tp_status = (
                    "VIRTUAL_PENDING" if use_virtual_spot_tps else "PENDING_PLACEMENT"
                )

                # First, cancel all existing PTP orders (if any from the previous step)
                # This is important if, for example, the entry was MARKET and TPs were placed immediately, and then a fill event arrived
                old_ptp_orders_to_cancel_ids: List[
                    Tuple[Optional[int], Optional[str]]
                ] = []
                for ptp_in_pos in position.partial_tp_orders:
                    if ptp_in_pos.order_id:
                        old_ptp_orders_to_cancel_ids.append(
                            (ptp_in_pos.order_id, ptp_in_pos.client_order_id)
                        )

                position.partial_tp_orders.clear()  # Clearing the old list of placed TP
                position.ptp_placement_initiated_flags.clear()  # Resetting flags

                if old_ptp_orders_to_cancel_ids:
                    logger.info(
                        f"{log_prefix} Found {len(old_ptp_orders_to_cancel_ids)} PTP orders to cancel before placing new ones."
                    )
                    # Cancellation tasks will be created below, before placing new ones

                # Now creating new TPs based on original_partial_targets_plan and the CURRENT position.initial_quantity
                new_planned_ptps: List[PartialTpOrderInfo] = []

                if position.initial_quantity > 0:
                    position_market_type = self._market_type_for_position(position)
                    lot_p_recalc_final = await self._get_market_info(
                        symbol, "lot_params", market_type=position_market_type
                    )
                    min_n_recalc_final = await self._get_market_info(
                        symbol, "min_notional", market_type=position_market_type
                    )

                    # Collect all candidate targets (both partial and final)
                    targets_to_plan = []
                    if position.original_partial_targets_plan:
                        for orig_pt_plan in position.original_partial_targets_plan:
                            targets_to_plan.append(
                                {
                                    "price": orig_pt_plan.price,
                                    "fraction": orig_pt_plan.fraction,
                                }
                            )

                    total_partial_fraction_sum = sum(
                        t["fraction"] for t in targets_to_plan
                    )
                    remaining_fraction = 1.0 - total_partial_fraction_sum

                    if remaining_fraction > 0.01 and position.initial_take_profit:
                        targets_to_plan.append(
                            {
                                "price": position.initial_take_profit,
                                "fraction": remaining_fraction,
                            }
                        )

                    # Filter to get only valid targets
                    valid_targets = []
                    entry_p_check = position.entry_price
                    sl_p_check = (
                        position.current_sl_price
                        if self._position_has_active_stop_target(position)
                        else None
                    )

                    for t in targets_to_plan:
                        is_valid = self._is_exit_target_valid(
                            t["price"],
                            entry_p_check,
                            sl_p_check,
                            position.direction,
                        )
                        if is_valid:
                            valid_targets.append(t)
                        else:
                            logger.warning(
                                f"{log_prefix} TP target {t['price']} is no longer valid against entry {entry_p_check} / SL {sl_p_check}. Skipping."
                            )

                    placed_qty_sum = 0.0
                    placed_fractions_sum = 0.0

                    for idx, t in enumerate(valid_targets):
                        is_last = idx == len(valid_targets) - 1

                        if is_last:
                            # The last valid target gets all the leftover quantity
                            qty_pt_adj_final = (
                                position.initial_quantity - placed_qty_sum
                            )
                            # Round to stepSize just in case of tiny float representation errors
                            if (
                                lot_p_recalc_final
                                and lot_p_recalc_final.get("stepSize", 0) > 0
                            ):
                                step = Decimal(str(lot_p_recalc_final["stepSize"]))
                                qty_dec = Decimal(f"{qty_pt_adj_final:.12f}")
                                qty_pt_adj_final = float(
                                    (qty_dec / step).quantize(
                                        Decimal("0"), rounding=ROUND_DOWN
                                    )
                                    * step
                                )
                        else:
                            qty_pt_raw_final = position.initial_quantity * t["fraction"]
                            qty_pt_adj_final = self.rm._adjust_and_round_quantity(
                                qty_pt_raw_final,
                                symbol,
                                t["price"],
                                lot_p_recalc_final,
                                min_n_recalc_final,
                            )

                        if qty_pt_adj_final and qty_pt_adj_final > 0:
                            new_planned_ptps.append(
                                PartialTpOrderInfo(
                                    target_price=t["price"],
                                    orig_fraction=t["fraction"],
                                    quantity=qty_pt_adj_final,
                                    status=planned_tp_status,
                                )
                            )
                            placed_qty_sum += qty_pt_adj_final
                            placed_fractions_sum += t["fraction"]
                            logger.info(
                                f"{log_prefix} Planned TP at {t['price']:.8f} (qty {qty_pt_adj_final:.8f}, is_last={is_last})."
                            )
                        else:
                            logger.warning(
                                f"{log_prefix} Cannot calculate valid quantity for TP target {t['price']}. Skipping."
                            )

                    position.partial_tp_orders = (
                        new_planned_ptps  # Updating the TP list for placement
                    )
                    logger.info(
                        f"{log_prefix} Re-planned {len(new_planned_ptps)} partial TPs based on final entry quantity {position.initial_quantity:.8f}."
                    )

                # Check for emergency closure if TP is not possible
                if (
                    not position.partial_tp_orders
                    and position.initial_quantity > 0
                    and not is_spot_market_for_entry_fill
                ):
                    logger.critical(
                        f"{log_prefix} CRITICAL: Position {client_order_id} for {symbol} has final entry quantity {position.initial_quantity:.8f} but NO Take Profit orders could be planned! Initiating emergency close."
                    )
                    # Save the position to pass to close_position, as it will be removed from _active_positions
                    pos_for_emergency_close = LivePosition(**vars(position))
                    self._active_position_pop(symbol, market_type)
                    # SL cancellation (if it managed to be placed) will occur inside close_position
                    self.loop.create_task(
                        self.close_position(
                            pos_for_emergency_close.symbol,
                            f"EMERGENCY_NO_TP_POSSIBLE_FOR_{client_order_id}",
                            market_type=market_type,
                        ),
                        name=f"EmergencyCloseNoTP_{symbol}",
                    )
                    return  # Exiting as the position is closing

            position_to_manage_exits = (
                position  # Passing the current object for order management
            )

        # Operations AFTER releasing the lock
        if dca_position_to_initialize and dca_params_to_initialize:
            pair_info_for_dca_grid = {"symbol": symbol}
            if dca_position_to_initialize.entry_atr is not None:
                pair_info_for_dca_grid["atr"] = dca_position_to_initialize.entry_atr
            self.loop.create_task(
                self._execute_dca_grid(
                    dca_position_to_initialize,
                    dca_params_to_initialize,
                    pair_info_for_dca_grid,
                ),
                name=f"ExecuteDCAGridInitOnEntry_{symbol}",
            )

        if position_to_manage_exits:
            logger.info(
                f"{log_prefix} Proceeding to manage exit orders for position (EntryCID: {position_to_manage_exits.entry_client_order_id})."
            )

            # Cancel the old SL if it existed and its price or quantity changed
            # (The sl_placement_initiated flag and current_sl_order_id were reset if the SL needs to be replaced)
            if (
                position_to_manage_exits.current_sl_order_id
            ):  # If SL already existed, but price/quantity changed
                symbol_lock_exit_check = self._get_lock_for_position(
                    symbol, market_type
                )
                async with symbol_lock_exit_check:  # Quick check under lock
                    position = self._active_position_get(symbol, market_type)

                    if (
                        position
                        and not position.sl_placement_initiated
                        and position.current_sl_order_id is not None
                    ):  # If repositioning is needed
                        old_sl_id_to_cancel = position.current_sl_order_id
                        old_sl_cid_to_cancel = position.current_sl_client_order_id
                        old_sl_is_algo = (
                            position.is_sl_algo_order
                        )  # Remembering the order type for cancellation
                        position.current_sl_order_id = (
                            None  # Reset so that _place_stop_loss can work
                        )
                        position.current_sl_client_order_id = None
                        position.is_sl_algo_order = False  # Resetting flag
                        logger.info(
                            f"{log_prefix} Creating task to cancel old SL ID {old_sl_id_to_cancel} (AlgoOrder={old_sl_is_algo}) before placing new one."
                        )
                        executor_for_cancel = self.executors.get(
                            position_to_manage_exits.mode, self.executors.get("live")
                        )
                        self.loop.create_task(
                            executor_for_cancel.cancel_order(
                                symbol=symbol,
                                orderId=old_sl_id_to_cancel,
                                origClientOrderId=old_sl_cid_to_cancel,
                                is_algo_order=old_sl_is_algo,
                            ),
                            name=f"CancelOldSL_ForUpdate_{symbol}",
                        )
                        await asyncio.sleep(
                            0.1
                        )  # Small pause for API cancellation processing

            # Placement/replacement of SL
            if self._position_has_active_stop_target(position_to_manage_exits):
                self.loop.create_task(
                    self._place_stop_loss(position_to_manage_exits),
                    name=f"PlaceSL_{symbol}_{client_order_id}",
                )
            else:
                logger.info(
                    f"{log_prefix} No active SL target for position {position_to_manage_exits.entry_client_order_id}. SL placement skipped."
                )

            # Placing an exchange trailing stop (if mode='exchange' in the config)
            self.loop.create_task(
                self._place_exchange_trailing_stop(position_to_manage_exits),
                name=f"PlaceExchTrailing_{symbol}_{client_order_id}",
            )

            # Schedule TP placement(s)
            use_virtual_spot_tps_for_exit_mgmt = (
                self._position_should_use_virtual_spot_tps(
                    position_to_manage_exits, executor_for_entry_fill
                )
            )
            if position_to_manage_exits.partial_tp_orders:
                logger.info(
                    f"{log_prefix} Scheduling {len(position_to_manage_exits.partial_tp_orders)} TP(s) for position {position_to_manage_exits.entry_client_order_id}."
                )
                for i, ptp_info_item in enumerate(
                    list(position_to_manage_exits.partial_tp_orders)
                ):  # Iterate over a copy if modifying
                    # Check if this PTP actually needs placement (e.g., no order_id yet, or a specific status)
                    # The status 'PENDING_PLACEMENT' is set when TPs are (re)calculated inside the lock.
                    if use_virtual_spot_tps_for_exit_mgmt and ptp_info_item.status in {
                        "PENDING_PLACEMENT",
                        "VIRTUAL_PENDING",
                    }:
                        ptp_info_item.status = "VIRTUAL_PENDING"
                        logger.info(
                            f"{log_prefix} Spot TP #{i + 1} is virtual; no LIMIT TP order will be placed while SL is active."
                        )
                    elif ptp_info_item.status == "PENDING_PLACEMENT":
                        logger.debug(
                            f"{log_prefix} Scheduling PTP #{i} (Target: {ptp_info_item.target_price}, Qty: {ptp_info_item.quantity}) for {position_to_manage_exits.entry_client_order_id}"
                        )
                        self.loop.create_task(
                            self._place_partial_tp(
                                position_to_manage_exits,
                                ptp_info_item.target_price,
                                ptp_info_item.quantity,
                                ptp_info_item.orig_fraction,
                                i,
                            ),
                            name=f"PlacePTP_{symbol}_{client_order_id}_idx{i}",
                        )
            else:
                logger.info(
                    f"{log_prefix} No partial TPs to schedule for placement for position {position_to_manage_exits.entry_client_order_id}."
                )

        # Publish state immediately after entry fill
        self.loop.create_task(
            self._publish_state_to_redis(),
            name=f"PublishState_EntryFill_{symbol}",
        )

    async def _handle_partial_tp_fill(
        self,
        symbol: str,
        tp_index: int,
        fill_price: float,
        commission: float,
        commission_asset: str,
        realized_pnl_from_exchange: float = 0.0,
        exchange_pnl_available: bool = False,
        market_type: Optional[str] = None,
    ):
        log_prefix = f"[_HandlePartialFill:{symbol}:TPidx={tp_index}]"  # Using the index for the log
        logger.debug(
            f"{log_prefix} --- STARTING PARTIAL TP FILL HANDLING --- FillPrice={fill_price}, Comm={commission}{commission_asset}"
        )

        move_sl_needed = False  # Initializing here
        position_closed_fully_by_this_tp = False  # Initializing
        entry_cid_for_log = "N/A"
        final_exit_order_id = None
        final_exit_client_order_id = None

        symbol_lock = self._get_lock_for_position(symbol, market_type)
        async with symbol_lock:
            position = self._active_position_get(symbol, market_type)
            if not position:
                logger.warning(
                    f"{log_prefix} Position not found for {symbol}. Fill event might be late or for already closed pos."
                )
                return
            if position.status != "OPEN":
                logger.warning(
                    f"{log_prefix} Position status is '{position.status}', not OPEN. Ignoring partial fill."
                )
                return

            entry_cid_for_log = position.entry_client_order_id or symbol
            ptp_info_object = position.partial_tp_orders[tp_index]

            logger.debug(
                f"{log_prefix} Matched PTP object: Target={ptp_info_object.target_price}, Qty={ptp_info_object.quantity}, CurrentStatus={ptp_info_object.status}"
            )

            if ptp_info_object.status == "FILLED":
                logger.debug(
                    f"{log_prefix} PTP already marked as FILLED. Skipping redundant processing."
                )
                return

            # Updating information about partial TP
            filled_quantity_for_this_tp = (
                ptp_info_object.quantity
            )  # Assuming that partial TP is always fully executed
            ptp_info_object.status = "FILLED"
            ptp_info_object.fill_price = fill_price
            ptp_info_object.commission = commission
            self._append_execution_event(
                position,
                event_type="EXIT",
                execution_type="PARTIAL_TAKE_PROFIT",
                price=fill_price,
                quantity=filled_quantity_for_this_tp,
                order_id=ptp_info_object.order_id,
                client_order_id=ptp_info_object.client_order_id,
                commission=commission,
                commission_asset=commission_asset,
            )
            logger.info(
                f"{log_prefix} PTP #{tp_index + 1} (Target: {ptp_info_object.target_price:.8f}) marked as FILLED. Qty: {filled_quantity_for_this_tp:.8f} @ {fill_price:.8f}"
            )

            # Accumulating real PnL from the exchange for partial TPs
            if realized_pnl_from_exchange != 0.0:
                position.accumulated_realized_pnl_from_exchange += (
                    realized_pnl_from_exchange
                )
                logger.info(
                    f"{log_prefix} Accumulated realized PnL from exchange: {position.accumulated_realized_pnl_from_exchange:.4f} (added {realized_pnl_from_exchange:.4f} from this PTP)"
                )

            final_exit_order_id = ptp_info_object.order_id
            final_exit_client_order_id = ptp_info_object.client_order_id

            # Updating the remaining quantity in the position
            old_remaining_qty = position.remaining_quantity
            position.remaining_quantity -= filled_quantity_for_this_tp
            logger.info(
                f"{log_prefix} Final check in _handle_partial_tp_fill for {symbol}. New remaining_quantity: {position.remaining_quantity}, Initial: {position.initial_quantity}, Status: {position.status}"
            )
            if position.remaining_quantity < 0:
                position.remaining_quantity = 0  # Should not be negative
            logger.info(
                f"{log_prefix} Position remaining quantity updated: {old_remaining_qty:.8f} -> {position.remaining_quantity:.8f}"
            )

            # Checking for full position closure
            # If the remaining quantity is very small (less than the minimum lot step), we consider the position closed
            min_step_qty_check = 0.0
            lot_params_for_rem_check = await self._get_market_info(
                symbol,
                "lot_params",
                market_type=self._market_type_for_position(position),
            )
            if lot_params_for_rem_check and lot_params_for_rem_check.get("stepSize"):
                min_step_qty_check = float(lot_params_for_rem_check["stepSize"])

            # Using a small multiplier to avoid float precision issues
            if (
                position.remaining_quantity < (min_step_qty_check * 0.5)
                and min_step_qty_check > 0
            ):
                position.remaining_quantity = (
                    0.0  # Forcing reset to zero if less than half a step
                )

            if position.remaining_quantity == 0.0:
                position_closed_fully_by_this_tp = True
            else:
                if position.move_sl_to_be_enabled and not position.is_stop_at_be:
                    num_prev_filled_tps = sum(
                        1
                        for ptp in position.partial_tp_orders[:tp_index]
                        if ptp.status == "FILLED"
                    )
                    is_first_tp_to_trigger_be = num_prev_filled_tps == 0

                    if is_first_tp_to_trigger_be:
                        logger.info(
                            f"{log_prefix} Pos {entry_cid_for_log}: First TP (idx {tp_index}) to trigger BE filled. Scheduling SL move."
                        )
                        # Do not set position.is_stop_at_be = True here
                        move_sl_needed = True

        # Actions AFTER releasing the lock
        if position_closed_fully_by_this_tp:
            logger.info(
                f"{log_prefix} Pos {entry_cid_for_log}: Triggering final exit handling as position is marked fully closed by this TP."
            )
            await self._handle_final_exit(
                symbol,
                f"ALL_TP_CLOSED_BY_TP_{tp_index + 1}",
                fill_price,
                commission,
                commission_asset,
                final_exit_order_id,
                final_exit_client_order_id,
                realized_pnl_from_exchange=0.0,  # Already added to accumulated_realized_pnl_from_exchange above
                exchange_pnl_available=exchange_pnl_available,
                market_type=self._market_type_for_position(position),
            )
        elif move_sl_needed:
            logger.info(
                f"{log_prefix} Pos {entry_cid_for_log}: Creating task to move SL to BE."
            )
            self.loop.create_task(
                self._move_stop_loss_to_be(
                    symbol,
                    is_first_attempt_for_be=True,
                    market_type=self._market_type_for_position(position),
                ),
                name=f"MoveSLtoBE_{symbol}_{entry_cid_for_log}",
            )
        else:
            logger.info(
                f"{log_prefix} Pos {entry_cid_for_log}: No SL move to BE needed or position not fully closed by this TP."
            )

        # Notification is sent even if SL moves to BE, as these are different events
        if not position_closed_fully_by_this_tp and self.telegram_notifier:
            # Get current position data AGAIN, as it might have changed
            # Alternatively, if we are sure that the necessary data is in ptp_info_object and position (snapshot under lock), they can be used
            current_pos_for_tg: Optional[LivePosition] = None
            symbol_lock = self._get_lock_for_position(symbol, market_type)
            async with symbol_lock:  # Fast read
                current_pos_for_tg = self._active_position_get(symbol, market_type)

            if current_pos_for_tg:  # Ensure the position still exists
                ptp_info_for_tg = current_pos_for_tg.partial_tp_orders[
                    tp_index
                ]  # Must be the same object

                tick_size_for_tg_ptp = (
                    await self._get_market_info(
                        symbol,
                        "tick_size",
                        market_type=self._market_type_for_position(current_pos_for_tg),
                    )
                    or config.DEFAULT_TICK_SIZE
                )
                base_asset_ptp = symbol.upper().replace("USDT", "")  # Simplified

                self.loop.create_task(
                    self.telegram_notifier.partial_tp_filled(
                        symbol=symbol,
                        tp_index=tp_index,  # 0-based
                        fill_price=fill_price,
                        closed_quantity=ptp_info_for_tg.quantity,  # Quantity of this TP order
                        fraction_of_initial=ptp_info_for_tg.orig_fraction,  # Original share of this TP
                        base_asset=base_asset_ptp,
                        remaining_quantity=current_pos_for_tg.remaining_quantity,
                        entry_client_order_id=current_pos_for_tg.entry_client_order_id,
                        tp_order_id=str(ptp_info_for_tg.order_id)
                        if ptp_info_for_tg.order_id
                        else None,
                        tick_size=tick_size_for_tg_ptp,
                        chat_id=self.user_telegram_chat_id,
                        market_type=self._market_type_for_position(current_pos_for_tg),
                        leverage=self._leverage_for_position(current_pos_for_tg),
                        api_key_name=self.api_key_name,
                    ),
                    name=f"TelegramNotify_PartialTP_{symbol}_{tp_index}",
                )

    async def _handle_final_exit(
        self,
        symbol: str,
        reason: str,
        exit_price: float,
        commission: float,
        commission_asset: Optional[str],
        order_id: Optional[int],
        client_order_id: Optional[str],
        realized_pnl_from_exchange: float = 0.0,
        exchange_pnl_available: bool = False,
        market_type: Optional[str] = None,
    ):
        # order_id and client_order_id here are the IDs of the order that TRIGGERED the final exit
        log_prefix = f"[_HandleFinalExit:{symbol}:{reason}]"
        logger.info(
            f"{log_prefix} Entered. Position symbol: {symbol}, Current _active_positions keys: {list(self._active_positions.keys())}"
        )
        position_to_process_copy: Optional[LivePosition] = None
        # List of tuples: (symbol_to_cancel, order_id_to_cancel, client_order_id_to_cancel, is_algo_order)
        orders_to_cancel_after_lock: List[
            Tuple[str, Optional[int], Optional[str], bool]
        ] = []

        symbol_lock = self._get_lock_for_position(symbol, market_type)
        async with symbol_lock:
            position = self._active_position_get(symbol, market_type)
            if not position:
                logger.warning(
                    f"{log_prefix} Position not found for {symbol} in _active_positions. Already handled or race condition? Current keys: {list(self._active_positions.keys())}"
                )
                return
            if position.status == "CLOSED":
                logger.warning(
                    f"{log_prefix} Position for {symbol} already CLOSED. Ignoring duplicate processing."
                )
                return

            logger.info(
                f"{log_prefix} Processing final exit. Current pos status: {position.status}."
            )

            # Collect order IDs for cancellation BEFORE the position is deleted or its status changes such that,
            # that _cancel_all_exit_orders will not be able to find them.
            # Exclude the order that has already been filled and triggered this exit (order_id).
            if position.current_sl_order_id is not None and str(
                position.current_sl_order_id
            ) != str(order_id):
                orders_to_cancel_after_lock.append(
                    (
                        symbol,
                        position.current_sl_order_id,
                        position.current_sl_client_order_id,
                        position.is_sl_algo_order,
                    )
                )

            for ptp in position.partial_tp_orders:
                if (
                    ptp.status == "PENDING"
                    and ptp.order_id is not None
                    and str(ptp.order_id) != str(order_id)
                ):
                    orders_to_cancel_after_lock.append(
                        (symbol, ptp.order_id, ptp.client_order_id, False)
                    )  # TP orders are not Algo orders

            if hasattr(position, "dca_orders") and position.dca_orders:
                for dca in position.dca_orders:
                    if (
                        dca.status in {"PENDING", "NEW"}
                        and dca.order_id is not None
                        and str(dca.order_id) != str(order_id)
                    ):
                        orders_to_cancel_after_lock.append(
                            (symbol, dca.order_id, dca.client_order_id, False)
                        )

            if hasattr(position, "dca_order_ids") and position.dca_order_ids:
                for dca_id in position.dca_order_ids:
                    if str(dca_id) != str(order_id):
                        already_in = any(
                            str(o[1]) == str(dca_id)
                            for o in orders_to_cancel_after_lock
                        )
                        if not already_in:
                            orders_to_cancel_after_lock.append(
                                (symbol, dca_id, None, False)
                            )

            # Updating main position information
            position.status = "CLOSED"
            position.exit_reason = reason
            position.closed_time = time.time()
            self._last_position_close_time_per_symbol[
                self._position_key(symbol, self._market_type_for_position(position))
            ] = position.closed_time

            # PnL and commission calculation
            total_commission_calculated = Decimal(str(position.entry_commission or 0))
            entry_price_dec = (
                Decimal(str(position.entry_price))
                if position.entry_price is not None
                else Decimal("0.0")
            )
            qty_closed_by_final_event = position.remaining_quantity

            if qty_closed_by_final_event > 0 and exit_price > 0:
                self._append_execution_event(
                    position,
                    event_type="EXIT",
                    execution_type="FINAL_EXIT",
                    price=exit_price,
                    quantity=qty_closed_by_final_event,
                    order_id=order_id,
                    client_order_id=client_order_id,
                    commission=commission,
                    commission_asset=commission_asset,
                )

            # Sum commissions for all partial TPs and the current event
            for ptp_order in position.partial_tp_orders:
                if ptp_order.commission is not None:
                    total_commission_calculated += Decimal(str(ptp_order.commission))
            total_commission_calculated += Decimal(str(commission))

            # PRIORITY: Real PnL from the exchange ('rp' field from Binance Futures WebSocket)
            # accumulated_realized_pnl_from_exchange contains PnL from already closed partial TPs.
            total_exchange_realized_pnl = (
                position.accumulated_realized_pnl_from_exchange
                + realized_pnl_from_exchange
            )

            if exchange_pnl_available:
                # Use PnL from the exchange, even if it is 0.0 (this is a valid result).
                position.pnl = total_exchange_realized_pnl
                logger.info(
                    f"{log_prefix} Using EXCHANGE realized PnL: {position.pnl:.4f} "
                    f"(accumulated={position.accumulated_realized_pnl_from_exchange:.4f}, "
                    f"this_event={realized_pnl_from_exchange:.4f}, "
                    f"exchange_pnl_available={exchange_pnl_available})"
                )
            else:
                # Fallback: calculated PnL (if the exchange did not return 'rp', for example for spot)
                total_pnl_calculated = Decimal("0.0")
                for ptp_order in position.partial_tp_orders:
                    if (
                        ptp_order.status == "FILLED"
                        and ptp_order.fill_price is not None
                        and entry_price_dec > 0
                    ):
                        fill_price_ptp_dec = Decimal(str(ptp_order.fill_price))
                        qty_ptp_dec = Decimal(str(ptp_order.quantity))
                        pnl_partial = (
                            fill_price_ptp_dec - entry_price_dec
                        ) * qty_ptp_dec
                        if position.direction == SignalDirection.SHORT:
                            pnl_partial = -pnl_partial
                        total_pnl_calculated += pnl_partial

                if reason != "ALL_PARTIAL_TP":  # If not fully closed by partials
                    qty_closed_by_this_event = position.remaining_quantity
                    if (
                        qty_closed_by_this_event > 0
                        and exit_price > 0
                        and entry_price_dec > 0
                    ):
                        exit_price_dec_event = Decimal(str(exit_price))
                        qty_closed_dec_event = Decimal(str(qty_closed_by_this_event))
                        pnl_this_event = (
                            exit_price_dec_event - entry_price_dec
                        ) * qty_closed_dec_event
                        if position.direction == SignalDirection.SHORT:
                            pnl_this_event = -pnl_this_event
                        total_pnl_calculated += pnl_this_event

                position.pnl = float(total_pnl_calculated)
                logger.warning(
                    f"{log_prefix} Exchange realized PnL ('rp') not available for this close event — "
                    f"using CALCULATED PnL fallback: {position.pnl:.4f}"
                )

            position.total_commission = float(total_commission_calculated)
            position.remaining_quantity = 0.0

            logger.info(
                f"{log_prefix} Final PnL: {position.pnl:.4f}. Total Commission: {position.total_commission:.8f}"
            )

            position_to_process_copy = LivePosition(
                **vars(position)
            )  # Capture state before potential deletion

            if self._active_position_get(
                symbol, self._market_type_for_position(position)
            ):
                logger.info(
                    f"{log_prefix} About to delete '{symbol}' from _active_positions. Current state of object for this symbol: {self._active_position_get(symbol, self._market_type_for_position(position))}"
                )
                self._active_position_pop(
                    symbol, self._market_type_for_position(position)
                )
                logger.info(
                    f"{log_prefix} Successfully deleted '{symbol}' from _active_positions. Remaining keys: {list(self._active_positions.keys())}"
                )
            else:
                logger.error(
                    f"{log_prefix} CRITICAL UNEXPECTED: '{symbol}' was NOT IN _active_positions right before attempted deletion, though it was present at the start of _handle_final_exit. _active_positions keys: {list(self._active_positions.keys())}"
                )

        # Operations after releasing lock
        executor_for_cancel = self.executors.get(
            position_to_process_copy.mode if position_to_process_copy else "live",
            self.executors.get("live"),
        )

        if orders_to_cancel_after_lock:
            logger.info(
                f"{log_prefix} Scheduling cancellation of {len(orders_to_cancel_after_lock)} associated exit orders for {symbol}."
            )
            tasks = []
            for (
                sym_cancel,
                oid_cancel,
                cid_cancel,
                is_algo,
            ) in orders_to_cancel_after_lock:
                if oid_cancel:  # Ensure that orderId is not None
                    tasks.append(
                        executor_for_cancel.cancel_order(
                            symbol=sym_cancel,
                            orderId=oid_cancel,
                            origClientOrderId=cid_cancel,
                            is_algo_order=is_algo,
                        )
                    )
            if tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=10.0,
                    )
                    logger.info(
                        f"{log_prefix} Associated exit orders for {symbol} cancelled successfully."
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        f"{log_prefix} Timeout cancelling associated exit orders for {symbol}. Moving on to hard reset."
                    )
                except Exception as e:
                    logger.error(
                        f"{log_prefix} Error cancelling associated exit orders: {e}",
                        exc_info=True,
                    )

        # HARD RESET: Cancel ALL open orders for this symbol to be 100% safe
        # This should ALWAYS happen when closing a position, even if the orders_to_cancel_after_lock list is empty
        logger.info(
            f"{log_prefix} Triggering symbol-wide 'Hard Reset' order cancellation for {symbol}."
        )
        try:
            await asyncio.wait_for(
                executor_for_cancel.cancel_all_open_orders(symbol),
                timeout=10.0,
            )
            logger.info(
                f"{log_prefix} Hard Reset: All open orders for {symbol} cancelled successfully."
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"{log_prefix} Hard Reset: Timeout cancelling open orders for {symbol}. Scheduling background retry."
            )
            self.loop.create_task(
                executor_for_cancel.cancel_all_open_orders(symbol),
                name=f"FinalExitHardCancelRetry_{symbol}",
            )
        except Exception as e:
            logger.error(
                f"{log_prefix} Hard Reset: Error cancelling open orders: {e}",
                exc_info=True,
            )

        if position_to_process_copy:
            await self.rm.update_trade_result(
                symbol, position_to_process_copy.pnl, exit_reason=reason
            )  # Global risk update

            # NEW: CREATE PHANTOM TRADE FOR BE ANALYSIS
            # When exiting by STOP_LOSS_BE, create a phantom trade for tracking
            # what would have happened if BE had not triggered
            if reason == "STOP_LOSS_BE" and config.PHANTOM_TRACKING_ENABLED:
                try:
                    phantom_tracker = get_phantom_tracker()

                    # Direction can be an Enum, converting to string
                    direction_str = (
                        position_to_process_copy.direction.name
                        if hasattr(position_to_process_copy.direction, "name")
                        else str(position_to_process_copy.direction)
                    )

                    phantom_tracker.create_phantom(
                        real_trade_id=position_to_process_copy.entry_client_order_id,
                        user_id=position_to_process_copy.user_id or 0,
                        symbol=symbol,
                        direction=direction_str,
                        entry_price=position_to_process_copy.entry_price,
                        entry_time=datetime.fromtimestamp(
                            position_to_process_copy.entry_time, tz=timezone.utc
                        ),
                        initial_stop_loss=position_to_process_copy.initial_stop_loss,
                        initial_take_profit=position_to_process_copy.initial_take_profit
                        or 0.0,
                        be_trigger_time=datetime.fromtimestamp(
                            position_to_process_copy.closed_time, tz=timezone.utc
                        ),
                        be_exit_price=exit_price,
                        real_pnl_pct=0.0,  # BE exit is ~0% PnL
                        strategy_config_id=position_to_process_copy.config_id,
                    )
                    logger.info(
                        f"{log_prefix} Phantom trade created for BE analysis. Will track TP={position_to_process_copy.initial_take_profit}, SL={position_to_process_copy.initial_stop_loss}"
                    )
                except Exception as phantom_err:
                    logger.error(
                        f"{log_prefix} Failed to create phantom trade: {phantom_err}",
                        exc_info=True,
                    )

            # Call update_symbol_strategy_performance
            if position_to_process_copy.initial_risk_usd_planned is not None:
                await self.rm.update_symbol_strategy_performance(
                    symbol=symbol,
                    strategy_name=position_to_process_copy.strategy,
                    pnl_usd=position_to_process_copy.pnl,  # Actual PnL of the trade
                    initial_risk_usd_planned=position_to_process_copy.initial_risk_usd_planned,
                )
            else:
                logger.warning(
                    f"{log_prefix} `initial_risk_usd_planned` not found for position {position_to_process_copy.entry_client_order_id}. Cannot update strategy-symbol performance."
                )

            # Log position closure
            self.trade_logger.log_event(
                event_type="POSITION_CLOSED",
                data={
                    "symbol": symbol,
                    "strategy": position_to_process_copy.strategy,
                    "pnl": position_to_process_copy.pnl,
                    "exit_reason": reason,
                    "exit_price": exit_price,
                    "order_id": order_id,
                    "client_order_id": client_order_id,
                    "commission": position_to_process_copy.total_commission,
                    "entry_client_order_id": position_to_process_copy.entry_client_order_id,
                    "initial_risk_usd_planned": position_to_process_copy.initial_risk_usd_planned,  # Log it
                },
            )
            logger.info(
                f"{log_prefix} Position for {symbol} fully processed and closed successfully."
            )

            # Send Push Notification for Position Closed
            if position_to_process_copy.user_id:
                async for db_session in self.get_db_session():  # Using async for
                    try:
                        user = await crud.admin_get_user_details(
                            db_session, position_to_process_copy.user_id
                        )
                        if user and user.push_subscription:
                            self.loop.create_task(
                                asyncio.to_thread(
                                    send_push_notification,  # Run sync function in a thread
                                    subscription_info=user.push_subscription,
                                    title="Position closed!",
                                    body=f"Position for {position_to_process_copy.symbol} ({position_to_process_copy.strategy}) closed. PnL: {position_to_process_copy.pnl:.2f} USD. Reason: {reason}",
                                    tag=f"position-closed-{position_to_process_copy.entry_client_order_id}",
                                ),
                                name=f"PushNotify_PosClosed_{position_to_process_copy.symbol}",
                            )
                    except Exception as push_exc:
                        logger.error(
                            f"Failed to send push notification for position closed {position_to_process_copy.entry_client_order_id} to user {position_to_process_copy.user_id}: {push_exc}",
                            exc_info=True,
                        )

            logger.info(
                f"{log_prefix} Position for {symbol} fully processed and closed successfully."
            )

            # Sending a Telegram notification about position closure
            if self.telegram_notifier:
                duration_s = None
                if (
                    position_to_process_copy.closed_time
                    and position_to_process_copy.entry_time
                ):
                    duration_s = (
                        position_to_process_copy.closed_time
                        - position_to_process_copy.entry_time
                    )

                tick_size_for_tg_close = (
                    await self._get_market_info(
                        position_to_process_copy.symbol,
                        "tick_size",
                        market_type=self._market_type_for_position(
                            position_to_process_copy
                        ),
                    )
                    or config.DEFAULT_TICK_SIZE
                )

                base_asset_closed = (
                    position_to_process_copy.symbol.upper()
                )  # Simplified
                quote_asset_closed = "USDT"  # Assuming USDT, will need to clarify
                if "USDT" in base_asset_closed:
                    base_asset_closed = base_asset_closed.replace("USDT", "")
                elif "BUSD" in base_asset_closed:
                    base_asset_closed = base_asset_closed.replace("BUSD", "")

                self.loop.create_task(
                    self.telegram_notifier.position_closed(
                        symbol=position_to_process_copy.symbol,
                        direction=position_to_process_copy.direction,
                        # direction_enum=position_to_process_copy.direction, # Pass Enum for % formatting
                        entry_price=position_to_process_copy.entry_price,
                        exit_price=exit_price,  # Price at which it was actually closed
                        pnl=position_to_process_copy.pnl,
                        quote_asset=quote_asset_closed,  # Or from commission_asset, if available and relevant
                        exit_reason=reason,
                        # closed_quantity is usually equal to initial_quantity if the position is closed entirely by a single event
                        closed_quantity=position_to_process_copy.initial_quantity,
                        initial_quantity=position_to_process_copy.initial_quantity,
                        base_asset=base_asset_closed,
                        duration_seconds=duration_s,
                        entry_client_order_id=position_to_process_copy.entry_client_order_id,
                        exit_order_id=str(order_id)
                        if order_id
                        else None,  # ID of the order that led to closing
                        tick_size=tick_size_for_tg_close,
                        chat_id=self.user_telegram_chat_id,
                        market_type=self._market_type_for_position(
                            position_to_process_copy
                        ),
                        leverage=self._leverage_for_position(position_to_process_copy),
                        api_key_name=self.api_key_name,
                    ),
                    name=f"TelegramNotify_PosClosed_{position_to_process_copy.symbol}",
                )

            if hasattr(self.trade_logger, "log_closed_trade_to_diary"):
                try:
                    # Collecting data for the diary
                    duration_s = None
                    if (
                        position_to_process_copy.closed_time
                        and position_to_process_copy.entry_time
                    ):
                        duration_s = (
                            position_to_process_copy.closed_time
                            - position_to_process_copy.entry_time
                        )

                    # PnL calculation in %
                    pnl_percent_val = None
                    if (
                        position_to_process_copy.pnl is not None
                        and position_to_process_copy.entry_price is not None
                        and position_to_process_copy.initial_quantity is not None
                        and position_to_process_copy.entry_price > 0
                        and position_to_process_copy.initial_quantity > 0
                    ):
                        entry_value = (
                            position_to_process_copy.entry_price
                            * position_to_process_copy.initial_quantity
                        )
                        if entry_value != 0:
                            pnl_percent_val = (
                                position_to_process_copy.pnl / entry_value
                            ) * 100

                    # R/R calculation by prices (simplified, if initial_take_profit exists)
                    rr_ratio_prices_val = None
                    if (
                        position_to_process_copy.initial_take_profit is not None
                        and position_to_process_copy.initial_stop_loss is not None
                        and position_to_process_copy.entry_price is not None
                    ):
                        profit_dist = abs(
                            position_to_process_copy.initial_take_profit
                            - position_to_process_copy.entry_price
                        )
                        loss_dist = abs(
                            position_to_process_copy.entry_price
                            - position_to_process_copy.initial_stop_loss
                        )
                        if loss_dist > 1e-9:  # Avoiding division by zero
                            rr_ratio_prices_val = profit_dist / loss_dist

                    # Actual trade risk
                    actual_trade_risk_usd_val = None
                    if (
                        position_to_process_copy.entry_price is not None
                        and position_to_process_copy.initial_stop_loss is not None
                        and position_to_process_copy.initial_quantity is not None
                    ):
                        actual_trade_risk_usd_val = (
                            abs(
                                position_to_process_copy.entry_price
                                - position_to_process_copy.initial_stop_loss
                            )
                            * position_to_process_copy.initial_quantity
                        )

                    # Details of grounds and signal
                    foundation_details_from_signal = {}
                    signal_specific_details = {}
                    if isinstance(position_to_process_copy.signal_details, dict):
                        f_met_log = position_to_process_copy.signal_details.get(
                            "foundation_met_details_log"
                        )
                        if f_met_log:
                            try:
                                foundation_details_from_signal = json.loads(f_met_log)
                            except Exception:
                                foundation_details_from_signal = {"raw_log": f_met_log}

                        # Copying the remaining details, excluding those already extracted and service ones
                        excluded_keys_for_specific = [
                            "foundation_total_weight",
                            "foundation_met_details_log",
                            "ml_confirmed_live",
                            "ml_confirm_proba_1_live",
                            "ml_confirm_proba_0_live",
                            "ml_threshold_good_live",
                            "ml_threshold_bad_reject_live",
                        ]
                        signal_specific_details = {
                            k: v
                            for k, v in position_to_process_copy.signal_details.items()
                            if k not in excluded_keys_for_specific
                        }

                    diary_data = {
                        "close_timestamp_utc": datetime.fromtimestamp(
                            position_to_process_copy.closed_time, timezone.utc
                        ).isoformat(timespec="microseconds")
                        if position_to_process_copy.closed_time
                        else None,
                        "symbol": position_to_process_copy.symbol,
                        "strategy_name": position_to_process_copy.strategy,
                        "direction": position_to_process_copy.direction.name,
                        "entry_price": position_to_process_copy.entry_price,
                        "exit_price": exit_price,  # Actual exit price
                        "quantity": position_to_process_copy.initial_quantity,  # Total trade volume
                        "pnl_usd": position_to_process_copy.pnl,
                        "pnl_percent": pnl_percent_val,
                        "commission_usd": position_to_process_copy.total_commission,  # Total commission
                        "initial_risk_usd_planned": position_to_process_copy.initial_risk_usd_planned,
                        "actual_trade_risk_usd": actual_trade_risk_usd_val,
                        "rr_ratio_prices": rr_ratio_prices_val,
                        "trade_duration_sec": duration_s,
                        "exit_reason": reason,
                        "foundation_total_weight": position_to_process_copy.signal_details.get(
                            "foundation_total_weight"
                        ),
                        "foundation_details_json": foundation_details_from_signal,
                        "signal_specific_details_json": signal_specific_details,
                        "entry_client_order_id": position_to_process_copy.entry_client_order_id,
                        "ml_confirmed_live": position_to_process_copy.signal_details.get(
                            "ml_confirmed_live"
                        ),
                        "ml_prob_good_signal_live": position_to_process_copy.signal_details.get(
                            "ml_confirm_proba_1_live"
                        ),
                        "api_key_id": self.api_key_id,
                    }
                    self.trade_logger.log_closed_trade_to_diary(diary_data)
                    logger.info(
                        f"{log_prefix} Closed trade logged to Trader Diary for {symbol}."
                    )
                except Exception as e_diary:
                    logger.error(
                        f"{log_prefix} Error logging trade to Trader Diary for {symbol}: {e_diary}",
                        exc_info=True,
                    )

            # Saving the trade to the database
            try:
                logger.info(
                    f"{log_prefix} Preparing to save closed trade to database for user_id={self.user_id}."
                )

                # Collect data for saving in the format expected by crud.create_trade
                # Determine trade_mode from the position (upper case for DB compatibility)
                trade_mode_for_db = (position_to_process_copy.mode or "live").upper()
                signal_details_for_db = (
                    copy.deepcopy(position_to_process_copy.signal_details)
                    if isinstance(position_to_process_copy.signal_details, dict)
                    else {}
                )
                signal_details_for_db["execution_events"] = list(
                    position_to_process_copy.execution_events
                )

                trade_data_for_db = {
                    "trade_uuid": position_to_process_copy.entry_client_order_id,  # Use Client Order ID as a unique trade ID
                    "timestamp_close": datetime.fromtimestamp(
                        position_to_process_copy.closed_time, timezone.utc
                    )
                    if position_to_process_copy.closed_time
                    else datetime.now(timezone.utc),
                    "timestamp_entry": datetime.fromtimestamp(
                        position_to_process_copy.entry_time, timezone.utc
                    )
                    if position_to_process_copy.entry_time
                    else None,
                    "timestamp_signal": datetime.fromtimestamp(
                        position_to_process_copy.entry_time, timezone.utc
                    )
                    if position_to_process_copy.entry_time
                    else None,
                    "symbol": position_to_process_copy.symbol,
                    "strategy_config_id": position_to_process_copy.config_id,  # Using config_id as strategy_config_id
                    "direction": position_to_process_copy.direction.name,
                    "entry_price": position_to_process_copy.entry_price,
                    "exit_price": exit_price,
                    "pnl": position_to_process_copy.pnl,
                    "commission": position_to_process_copy.total_commission,
                    "exit_reason": reason,
                    "quantity": position_to_process_copy.initial_quantity,
                    "position_entry_id": position_to_process_copy.entry_client_order_id,  # For grouping partial exits
                    "is_final_exit": True,  # This is the final position exit
                    # Signal details with decision trace for analytics
                    "signal_details_json": signal_details_for_db,
                    # Maximum floating profit and loss during the trade
                    "max_floating_profit": position_to_process_copy.max_floating_profit,
                    "max_floating_loss": position_to_process_copy.max_floating_loss,
                    # API key ID for multi-account tracking
                    "api_key_id": self.api_key_id,
                }

                # Get the DB session and call the save function
                async for db in self.get_db_session():
                    try:
                        await crud.create_trade(
                            db=db,
                            user_id=self.user_id,
                            trade_data=trade_data_for_db,
                            trade_mode=trade_mode_for_db,
                        )
                        await db.commit()  # Committing transaction
                        logger.info(
                            f"{log_prefix} Successfully saved trade to database."
                        )
                    except Exception as e_inner:
                        await db.rollback()
                        raise e_inner
                    finally:
                        break  # Exiting the loop after one iteration
            except Exception as e_db_save:
                logger.error(
                    f"{log_prefix} CRITICAL: Failed to save trade to database for user_id={self.user_id}, symbol={symbol}. Error: {e_db_save}",
                    exc_info=True,
                )

            # Logging the closure for ML context
            if self.realtime_ml_logger and getattr(
                config, "LOG_REALTIME_ML_DATA", False
            ):
                actual_entry_price = position_to_process_copy.entry_price
                # Calculation of y_true (simplified, requires refinement for real-time)
                y_true_val = None
                if position_to_process_copy.pnl is not None:
                    y_true_val = 1 if position_to_process_copy.pnl > 0 else 0

                ml_close_log_data = {
                    "controller_client_order_id": position_to_process_copy.entry_client_order_id,
                    "close_timestamp": datetime.fromtimestamp(
                        position_to_process_copy.closed_time, tz=timezone.utc
                    ).isoformat()
                    if position_to_process_copy.closed_time
                    else None,
                    "actual_entry_price": actual_entry_price,
                    "actual_exit_price": exit_price,
                    "pnl": position_to_process_copy.pnl,
                    "exit_reason": reason,
                    "commission": position_to_process_copy.total_commission,
                    "y_true": y_true_val,
                    # These fields are not needed for TRADE_RESULT, they are from SIGNAL_CONTEXT
                    "signal_timestamp": None,
                    "strategy": None,
                    "symbol": None,
                    "direction": None,
                    "signal_trigger_price": None,
                    "signal_entry_price": None,
                    "signal_sl": None,
                    "signal_tp": None,
                    "initial_risk_usd_planned": None,
                    "raw_features_live_json": None,
                    "orderbook_snapshot_json": None,
                    "orderbook_features_live_json": None,
                    "signal_details_json": None,
                }
                self.realtime_ml_logger.log_data(
                    event_type="TRADE_RESULT", data=ml_close_log_data
                )
                logger.info(
                    f"{log_prefix} Logged TRADE_RESULT for ML (EntryCID: {position_to_process_copy.entry_client_order_id})."
                )

            # Final data unsubscription
            is_managed_close = False
            # Not using a lock, as this set only changes in _update_monitored_symbols
            if symbol in self._closing_managed_symbols:
                is_managed_close = True
                self._closing_managed_symbols.remove(symbol)

            if is_managed_close:
                logger.info(
                    f"Position for {symbol} (which was in managed close state) is now fully closed. Unsubscribing from its data streams."
                )
                self.loop.create_task(
                    self.consumer.remove_all_subscriptions_for_symbol(symbol),
                    name=f"FinalUnsubscribeManagedClose_{symbol}",
                )

        else:
            logger.warning(
                f"{log_prefix} Position data was not available for post-lock processing for {symbol}."
            )

        # Publish state immediately after final exit
        self.loop.create_task(
            self._publish_state_to_redis(),
            name=f"PublishState_FinalExit_{symbol}",
        )

    async def _move_stop_loss_to_be(
        self,
        symbol: str,
        is_first_attempt_for_be: bool = True,
        market_type: Optional[str] = None,
    ):
        log_prefix = f"[_MoveSLtoBE:{symbol}]"
        logger.info(
            f"{log_prefix} --- ENTERING _move_stop_loss_to_be (Top Level). IsFirstAttempt={is_first_attempt_for_be}"
        )

        new_sl_price_to_set: Optional[float] = None

        current_position_entry_price: Optional[float] = None
        current_position_sl_price: Optional[float] = None
        current_position_direction: Optional[SignalDirection] = None
        tick_size_for_be_calc: Optional[float] = None
        is_already_at_be_in_pos_object: bool = False

        symbol_lock = self._get_lock_for_position(symbol, market_type)
        async with symbol_lock:
            position = self._active_position_get(symbol, market_type)

            if not position:
                logger.warning(f"{log_prefix} EXIT: Position not found.")
                return
            if position.status != "OPEN":
                logger.warning(
                    f"{log_prefix} EXIT: Position status is '{position.status}', not OPEN."
                )
                return

            logger.debug(
                f"{log_prefix} Inside lock: Pos status OPEN. is_first_attempt_for_be={is_first_attempt_for_be}, position.is_stop_at_be={position.is_stop_at_be}"
            )

            if not is_first_attempt_for_be and position.is_stop_at_be:
                logger.info(f"{log_prefix} EXIT: SL already at BE (non-first attempt).")
                return

            if is_first_attempt_for_be and position.is_stop_at_be:
                logger.warning(
                    f"{log_prefix} Proceeding: is_first_attempt_for_be=True, but position.is_stop_at_be is already True. THIS IS UNEXPECTED for a clean BE move."
                )

            current_position_entry_price = position.entry_price
            current_position_sl_price = position.current_sl_price
            current_position_direction = position.direction
            is_already_at_be_in_pos_object = position.is_stop_at_be

            if current_position_entry_price is None:
                logger.error(f"{log_prefix} EXIT: Entry price not set.")
                return

            tick_size_for_be_calc = await self._get_market_info(
                symbol,
                "tick_size",
                market_type=self._market_type_for_position(position),
            )
            if tick_size_for_be_calc is None or tick_size_for_be_calc <= 0:
                logger.error(
                    f"{log_prefix} EXIT: Cannot get valid tick_size for BE calculation. Aborting BE move."
                )
                return

            logger.debug(
                f"{log_prefix} Params for BE calc: Entry={current_position_entry_price}, CurrSL={current_position_sl_price if current_position_sl_price is not None else 'NONE'}, TickSize={tick_size_for_be_calc}"
            )

            entry_dec = Decimal(str(current_position_entry_price))
            tick_dec = Decimal(str(tick_size_for_be_calc))

            # Use 'config' imported in this file
            num_ticks_offset_for_be = getattr(config, "BE_SL_OFFSET_TICKS", 1)
            offset_value_dec = tick_dec * Decimal(str(num_ticks_offset_for_be))
            logger.debug(
                f"{log_prefix} Offset ticks for BE: {num_ticks_offset_for_be}, Offset value decimal: {offset_value_dec}"
            )

            calculated_be_sl_price_dec: Decimal
            if current_position_direction == SignalDirection.LONG:
                calculated_be_sl_price_dec = entry_dec + offset_value_dec
            else:  # SHORT
                calculated_be_sl_price_dec = entry_dec - offset_value_dec
            logger.debug(
                f"{log_prefix} Calculated BE SL price (decimal, pre-round): {calculated_be_sl_price_dec}"
            )

            final_be_sl_price_candidate = self._round_price(
                float(calculated_be_sl_price_dec),
                tick_size_for_be_calc,
                ROUND_DOWN
                if current_position_direction == SignalDirection.LONG
                else ROUND_UP,
            )
            logger.debug(
                f"{log_prefix} Final BE SL price candidate (after _round_price): {final_be_sl_price_candidate}"
            )

            if final_be_sl_price_candidate is None or final_be_sl_price_candidate <= 0:
                logger.error(
                    f"{log_prefix} EXIT: Calculated BE SL price is invalid ({final_be_sl_price_candidate}). Original decimal: {calculated_be_sl_price_dec}. Cannot move."
                )
                return

            logger.info(
                f"{log_prefix} Calculated new BE SL price: {final_be_sl_price_candidate:.8f} (Entry: {current_position_entry_price}, OffsetTicks: {num_ticks_offset_for_be}, PrevSL: {current_position_sl_price if current_position_sl_price is not None else 'NONE'})"
            )

            is_worse = False
            if (
                current_position_sl_price is not None
                and current_position_direction == SignalDirection.LONG
                and final_be_sl_price_candidate < current_position_sl_price
            ):
                is_worse = True
            elif (
                current_position_sl_price is not None
                and current_position_direction == SignalDirection.SHORT
                and final_be_sl_price_candidate > current_position_sl_price
            ):
                is_worse = True

            if is_worse:
                logger.warning(
                    f"{log_prefix} Calculated BE SL {final_be_sl_price_candidate:.8f} is worse than current {current_position_sl_price:.8f}. Using current SL as target."
                )
                final_be_sl_price_candidate = current_position_sl_price

            price_difference_abs = (
                abs(final_be_sl_price_candidate - current_position_sl_price)
                if current_position_sl_price is not None
                else float("inf")
            )
            threshold_for_same_price = tick_size_for_be_calc / 2
            logger.debug(
                f"{log_prefix} Price diff check: |{final_be_sl_price_candidate} - {current_position_sl_price if current_position_sl_price is not None else 'NONE'}| = {price_difference_abs} vs threshold {threshold_for_same_price}"
            )

            if price_difference_abs < threshold_for_same_price:
                logger.info(
                    f"{log_prefix} EXIT: New BE SL price effectively same as current. No move needed."
                )
                if is_first_attempt_for_be and not is_already_at_be_in_pos_object:
                    position.is_stop_at_be = True
                    logger.info(
                        f"{log_prefix} Marking is_stop_at_be=True as SL is already effectively at BE."
                    )
                return

            new_sl_price_to_set = final_be_sl_price_candidate
            logger.info(f"{log_prefix} new_sl_price_to_set = {new_sl_price_to_set}")

        if new_sl_price_to_set is not None:
            logger.info(
                f"{log_prefix} CALLING _replace_stop_loss with price: {new_sl_price_to_set:.8f}"
            )
            success_replace = await self._replace_stop_loss(
                symbol,
                new_sl_price_to_set,
                market_type=self._market_type_for_position(position),
            )

            if success_replace:
                symbol_lock_be_final = self._get_lock_for_position(
                    symbol, self._market_type_for_position(position)
                )
                async with symbol_lock_be_final:
                    pos_after_be_move = self._active_position_get(
                        symbol, self._market_type_for_position(position)
                    )
                    if pos_after_be_move and pos_after_be_move.status == "OPEN":
                        current_tick_size = (
                            tick_size_for_be_calc if tick_size_for_be_calc else 1e-9
                        )
                        if pos_after_be_move.current_sl_price is not None and abs(
                            pos_after_be_move.current_sl_price - new_sl_price_to_set
                        ) < (current_tick_size / 2):
                            pos_after_be_move.is_stop_at_be = True
                            logger.info(
                                f"{log_prefix} SL successfully moved to BE price {new_sl_price_to_set:.8f}. Marked is_stop_at_be=True."
                            )

                            # Notification about moving SL to breakeven
                            if self.telegram_notifier:
                                tick_size_for_tg_be = (
                                    tick_size_for_be_calc  # Already exists
                                )
                                self.loop.create_task(
                                    self.telegram_notifier.sl_moved_to_be(
                                        symbol=symbol,
                                        new_sl_price=new_sl_price_to_set,  # Price that was attempted to be set
                                        entry_price=pos_after_be_move.entry_price,  # Entry price from position
                                        entry_client_order_id=pos_after_be_move.entry_client_order_id,
                                        tick_size=tick_size_for_tg_be,
                                        chat_id=self.user_telegram_chat_id,
                                        reason="First partial TP executed",
                                        market_type=self._market_type_for_position(
                                            pos_after_be_move
                                        ),
                                        leverage=self._leverage_for_position(
                                            pos_after_be_move
                                        ),
                                        api_key_name=self.api_key_name,
                                    ),
                                    name=f"TelegramNotify_SLtoBE_{symbol}",
                                )
                        else:
                            logger.warning(
                                f"{log_prefix} SL replacement reported success, but pos.current_sl_price ({pos_after_be_move.current_sl_price}) differs from target BE SL ({new_sl_price_to_set}). Not marking is_stop_at_be=True yet."
                            )
                    elif pos_after_be_move:
                        logger.warning(
                            f"{log_prefix} SL replacement reported success, but pos status is '{pos_after_be_move.status}'. Not marking BE flag."
                        )
                    else:
                        logger.warning(
                            f"{log_prefix} SL replacement reported success, but position for {symbol} not found after BE move. Cannot mark BE flag."
                        )
            else:
                logger.error(
                    f"{log_prefix} _replace_stop_loss FAILED or returned False."
                )
                if is_first_attempt_for_be:
                    # Use 'config' imported in this file
                    retry_delay_be = getattr(config, "BE_MOVE_RETRY_DELAY_SECONDS", 60)
                    logger.info(
                        f"{log_prefix} Scheduling a retry for BE move in {retry_delay_be}s because replace_stop_loss failed."
                    )
                    self.loop.call_later(
                        retry_delay_be,
                        lambda: asyncio.create_task(
                            self._move_stop_loss_to_be(
                                symbol,
                                is_first_attempt_for_be=False,
                                market_type=self._market_type_for_position(position),
                            )
                        ),
                    )
        else:
            logger.debug(
                f"{log_prefix} No new SL price was determined to set for BE. (is_first_attempt_for_be={is_first_attempt_for_be})"
            )

    async def _replace_stop_loss(
        self, symbol: str, new_sl_price: float, market_type: Optional[str] = None
    ) -> bool:
        log_prefix = f"[_ReplaceSL:{symbol}:ToPrice={new_sl_price:.8f}]"
        logger.info(f"{log_prefix} --- ENTERING _replace_stop_loss ---")

        old_sl_id_to_cancel: Optional[int] = None
        old_sl_cid_to_cancel: Optional[str] = None
        entry_cid_for_log_at_replace: str = symbol

        position_ref_for_new_sl: Optional[LivePosition] = None

        symbol_lock = self._get_lock_for_position(symbol, market_type)
        async with symbol_lock:
            position = self._active_position_get(symbol, market_type)
            if not position:
                logger.warning(f"{log_prefix} Position not found. Cannot replace SL.")
                return False
            if position.status != "OPEN":
                logger.warning(
                    f"{log_prefix} Position status is '{position.status}', not OPEN. Cannot replace SL."
                )
                return False

            entry_cid_for_log_at_replace = position.entry_client_order_id or symbol

            old_sl_id_to_cancel = position.current_sl_order_id
            old_sl_cid_to_cancel = position.current_sl_client_order_id
            old_sl_is_algo = (
                position.is_sl_algo_order
            )  # Remembering the order type for cancellation

            position.current_sl_price = new_sl_price
            logger.debug(
                f"{log_prefix} Updated position.current_sl_price to {new_sl_price:.8f}"
            )

            position.current_sl_order_id = None
            position.current_sl_client_order_id = None
            position.sl_placement_initiated = False
            position.is_sl_algo_order = False  # Resetting flag

            position_ref_for_new_sl = position

        if old_sl_id_to_cancel or old_sl_cid_to_cancel:
            executor = await self._get_executor_for_symbol(
                symbol, market_type=market_type
            )
            if executor:
                logger.info(
                    f"{log_prefix} Cancelling old SL order (ID: {old_sl_id_to_cancel}, ClientID: {old_sl_cid_to_cancel}, AlgoOrder={old_sl_is_algo})..."
                )
                self.loop.create_task(
                    executor.cancel_order(
                        symbol=symbol,
                        orderId=old_sl_id_to_cancel,
                        origClientOrderId=old_sl_cid_to_cancel,
                        is_algo_order=old_sl_is_algo,
                    ),
                    name=f"CancelOldSL_ForReplace_{symbol}_{old_sl_id_to_cancel or old_sl_cid_to_cancel}",
                )
                logger.debug(f"{log_prefix} Old SL cancellation task created.")
                await asyncio.sleep(0.1)
            else:
                logger.error(
                    f"{log_prefix} Could not get executor to cancel old SL order. Proceeding to place new one, but old one may remain."
                )

        if not position_ref_for_new_sl:
            logger.error(
                f"{log_prefix} EXIT: Position reference for new SL is None after lock release."
            )
            return False

        logger.info(
            f"{log_prefix} CALLING _place_stop_loss for position {position_ref_for_new_sl.entry_client_order_id or symbol}"
        )
        # skip_preflight_check=True because this is a stop REPLACEMENT (BE/trailing)
        # If the price has already moved past the new level, the stop will simply trigger on the exchange — this is normal
        place_success = await self._place_stop_loss(
            position_ref_for_new_sl, skip_preflight_check=True
        )
        logger.info(f"{log_prefix} _place_stop_loss returned: {place_success}")

        if place_success:
            logger.info(
                f"{log_prefix} New SL successfully placed (or placement initiated by _place_stop_loss)."
            )

            final_new_sl_order_id = position_ref_for_new_sl.current_sl_order_id
            final_new_sl_client_order_id = (
                position_ref_for_new_sl.current_sl_client_order_id
            )

            self.trade_logger.log_event(
                event_type="SL_ORDER_MOVED_SUCCESS",
                data={
                    "symbol": symbol,
                    "new_sl_price": new_sl_price,
                    "old_sl_order_id": old_sl_id_to_cancel,
                    "new_sl_order_id": final_new_sl_order_id,
                    "new_sl_client_order_id": final_new_sl_client_order_id,
                    "entry_client_order_id": entry_cid_for_log_at_replace,
                },
            )
            logger.info(f"{log_prefix} --- EXITING _replace_stop_loss (SUCCESS) ---")
            return True
        else:
            logger.error(
                f"{log_prefix} Failed to place new SL (returned by _place_stop_loss)."
            )
            self.trade_logger.log_event(
                event_type="SL_ORDER_MOVED_FAILED",
                data={
                    "symbol": symbol,
                    "new_sl_price": new_sl_price,
                    "reason": "Failed to place new SL order (via _place_stop_loss)",
                    "entry_client_order_id": entry_cid_for_log_at_replace,
                },
            )
            logger.error(f"{log_prefix} --- EXITING _replace_stop_loss (FAILURE) ---")
            return False

    async def _replace_take_profit(
        self,
        symbol: str,
        new_tp_price: float,
        market_type: Optional[str] = None,
        partial_targets: Optional[List[Tuple[float, float, bool]]] = None,
    ) -> bool:
        """
        Replaces the take-profit order for the specified position.
        Cancels existing PENDING TP orders and places a new one at the new price.

        Arguments:
            symbol: Position symbol
            new_tp_price: New price for take-profit
            market_type: Market type (e.g. spot, futures)
            partial_targets: Optional list of tuples (price, fraction, is_filled)

        Returns:
            True if TP is successfully replaced, False otherwise
        """
        log_prefix = f"[_ReplaceTP:{symbol}:ToPrice={new_tp_price:.8f}]"
        logger.info(f"{log_prefix} --- ENTERING _replace_take_profit ---")

        old_tp_orders_to_cancel: List[Tuple[Optional[int], Optional[str]]] = []
        position_ref_for_new_tp: Optional[LivePosition] = None
        entry_cid_for_log: str = symbol

        symbol_lock = self._get_lock_for_position(symbol, market_type)
        async with symbol_lock:
            position = self._active_position_get(symbol, market_type)
            if not position:
                logger.warning(f"{log_prefix} Position not found. Cannot replace TP.")
                return False
            if position.status != "OPEN":
                logger.warning(
                    f"{log_prefix} Position status is '{position.status}', not OPEN. Cannot replace TP."
                )
                return False

            entry_cid_for_log = position.entry_client_order_id or symbol

            # Collect information about old TP orders that need to be canceled
            for ptp in position.partial_tp_orders:
                if ptp.status == "PENDING" and (ptp.order_id or ptp.client_order_id):
                    old_tp_orders_to_cancel.append((ptp.order_id, ptp.client_order_id))

            # Resetting old TP orders from the position
            total_quantity = position.remaining_quantity
            if total_quantity <= 0:
                logger.warning(
                    f"{log_prefix} Position has no remaining quantity. Cannot replace TP."
                )
                return False

            # Create a new TP list. If partial_targets are provided, use them. Otherwise, 100% at new_tp_price.
            new_ptp_orders = []
            if partial_targets and len(partial_targets) > 0:
                lot_params = await self._get_market_info(
                    symbol, "lot_params", market_type=market_type
                )
                step_size = 0.0
                if lot_params:
                    try:
                        step_size = float(lot_params.get("stepSize") or 0.0)
                    except (ValueError, TypeError):
                        pass

                accumulated_qty = 0.0
                active_targets = []

                for pt in partial_targets:
                    # Support both list of tuples/lists and PartialTarget objects
                    if isinstance(pt, (tuple, list)):
                        pt_price = pt[0]
                        pt_frac = pt[1]
                        pt_filled = pt[2] if len(pt) > 2 else False
                    else:
                        pt_price = getattr(pt, "price", None)
                        pt_frac = getattr(pt, "fraction", None)
                        pt_filled = getattr(pt, "is_filled", False)

                    if pt_price is None or pt_frac is None:
                        continue
                    if pt_filled:
                        continue
                    active_targets.append((pt_price, pt_frac))

                active_fractions_sum = sum(frac for _, frac in active_targets)
                rem_frac = 1.0 - active_fractions_sum
                if rem_frac > 0.01:
                    active_targets.append((new_tp_price, rem_frac))

                for idx, (pt_price, pt_frac) in enumerate(active_targets):
                    is_last_target = idx == len(active_targets) - 1
                    if is_last_target:
                        pt_qty = total_quantity - accumulated_qty
                    else:
                        pt_qty_raw = total_quantity * pt_frac
                        if step_size > 0:
                            pt_qty = round(pt_qty_raw / step_size) * step_size
                        else:
                            pt_qty = pt_qty_raw

                    if step_size > 0:
                        pt_qty = round(pt_qty / step_size) * step_size

                    if pt_qty > 0:
                        if accumulated_qty + pt_qty > total_quantity:
                            pt_qty = total_quantity - accumulated_qty
                        if pt_qty > 0:
                            new_ptp_orders.append(
                                PartialTpOrderInfo(
                                    target_price=pt_price,
                                    orig_fraction=pt_frac,
                                    quantity=pt_qty,
                                    status="PENDING",
                                )
                            )
                            accumulated_qty += pt_qty
            else:
                new_ptp_orders = [
                    PartialTpOrderInfo(
                        target_price=new_tp_price,
                        orig_fraction=1.0,  # 100% of position
                        quantity=total_quantity,
                        order_id=None,
                        client_order_id=None,
                        status="PENDING",
                    )
                ]

            position.partial_tp_orders = new_ptp_orders
            # Resetting initiation flags for new TP
            position.ptp_placement_initiated_flags = {}

            position_ref_for_new_tp = position

        # 1. Canceling old TP orders
        if old_tp_orders_to_cancel:
            executor = await self._get_executor_for_symbol(
                symbol, market_type=market_type
            )
            if executor:
                logger.info(
                    f"{log_prefix} Cancelling {len(old_tp_orders_to_cancel)} old TP order(s)..."
                )
                cancel_tasks = []
                for order_id, client_order_id in old_tp_orders_to_cancel:
                    cancel_tasks.append(
                        executor.cancel_order(
                            symbol=symbol,
                            orderId=order_id,
                            origClientOrderId=client_order_id,
                        )
                    )
                if cancel_tasks:
                    try:
                        await asyncio.gather(*cancel_tasks, return_exceptions=True)
                    except Exception as e:
                        logger.warning(
                            f"{log_prefix} Exception waiting for cancel tasks: {e}"
                        )
            else:
                logger.error(
                    f"{log_prefix} Could not get executor to cancel old TP orders."
                )

        if not position_ref_for_new_tp:
            logger.error(f"{log_prefix} Position reference lost after lock release.")
            return False

        # 2. Placing new TP orders
        logger.info(
            f"{log_prefix} Placing new TP orders for position {entry_cid_for_log}"
        )

        try:
            for idx, ptp in enumerate(position_ref_for_new_tp.partial_tp_orders):
                if (
                    ptp.status == "PENDING"
                    and not ptp.order_id
                    and not ptp.client_order_id
                ):
                    await self._place_partial_tp(
                        position_obj_ref=position_ref_for_new_tp,
                        target_price=ptp.target_price,
                        quantity_to_close=ptp.quantity,
                        orig_fraction=ptp.orig_fraction,
                        ptp_internal_idx=idx,
                    )

            # Checking the result
            symbol_lock_tp_final = self._get_lock_for_position(symbol, market_type)
            async with symbol_lock_tp_final:
                updated_pos = self._active_position_get(symbol, market_type)
                if updated_pos and updated_pos.partial_tp_orders:
                    first_tp = updated_pos.partial_tp_orders[0]
                    if first_tp.order_id or first_tp.client_order_id:
                        logger.info(
                            f"{log_prefix} New TP order(s) placed successfully."
                        )

                        self.trade_logger.log_event(
                            event_type="TP_ORDER_MOVED_SUCCESS",
                            data={
                                "symbol": symbol,
                                "new_tp_price": new_tp_price,
                                "old_tp_count": len(old_tp_orders_to_cancel),
                                "new_tp_count": len(updated_pos.partial_tp_orders),
                                "entry_client_order_id": entry_cid_for_log,
                            },
                        )
                        logger.info(
                            f"{log_prefix} --- EXITING _replace_take_profit (SUCCESS) ---"
                        )
                        return True

            # If failed to get order ID, assume placement is deferred
            logger.info(
                f"{log_prefix} TP order placement initiated, waiting for confirmation via order update."
            )
            logger.info(
                f"{log_prefix} --- EXITING _replace_take_profit (INITIATED) ---"
            )
            return True

        except Exception as e:
            logger.error(
                f"{log_prefix} Exception during TP placement: {e}", exc_info=True
            )
            self.trade_logger.log_event(
                event_type="TP_ORDER_MOVED_FAILED",
                data={
                    "symbol": symbol,
                    "new_tp_price": new_tp_price,
                    "reason": str(e),
                    "entry_client_order_id": entry_cid_for_log,
                },
            )
            logger.error(f"{log_prefix} --- EXITING _replace_take_profit (FAILURE) ---")
            return False

    async def _check_spot_virtual_tp_triggers(
        self,
        symbol: str,
        high_price: Optional[float] = None,
        low_price: Optional[float] = None,
        last_price: Optional[float] = None,
    ) -> bool:
        if high_price is None and low_price is None and last_price is None:
            return False

        price_for_log = last_price or high_price or low_price
        spot_market_type = "spot"
        executor = await self._get_executor_for_symbol(
            symbol, market_type=spot_market_type
        )
        if not executor or not self._executor_is_spot(executor):
            return False

        selected_idx: Optional[int] = None
        selected_tp: Optional[PartialTpOrderInfo] = None

        symbol_lock = self._get_lock_for_position(symbol, spot_market_type)
        async with symbol_lock:
            position = self._active_position_get(symbol, spot_market_type)
            if not position or position.status != "OPEN":
                return False
            if not self._position_should_use_virtual_spot_tps(position, executor):
                return False

            candidates: List[Tuple[int, PartialTpOrderInfo]] = []
            for idx, tp in enumerate(position.partial_tp_orders):
                if not self._tp_is_virtual_pending(tp):
                    continue
                target = tp.target_price
                hit = False
                if position.direction == SignalDirection.LONG:
                    hit = high_price is not None and high_price >= target
                elif position.direction == SignalDirection.SHORT:
                    hit = low_price is not None and low_price <= target
                if hit:
                    candidates.append((idx, tp))

            if not candidates:
                return False

            candidates.sort(
                key=lambda item: item[1].target_price,
                reverse=(position.direction == SignalDirection.SHORT),
            )
            selected_idx, selected_tp = candidates[0]
            selected_tp.status = "VIRTUAL_TRIGGERING"
            logger.info(
                f"[SpotVirtualTP:{symbol}] Virtual TP #{selected_idx + 1} hit at market price "
                f"{price_for_log}. Target={selected_tp.target_price}, qty={selected_tp.quantity}."
            )

        await self._execute_spot_virtual_tp(
            symbol, selected_idx, market_type=spot_market_type
        )
        return True

    async def _execute_spot_virtual_tp(
        self, symbol: str, tp_index: int, market_type: Optional[str] = "spot"
    ) -> None:
        log_prefix = f"[SpotVirtualTP:{symbol}:idx={tp_index}]"
        executor = await self._get_executor_for_symbol(symbol, market_type=market_type)
        if not executor:
            logger.error(
                f"{log_prefix} No executor available. Cannot execute virtual TP."
            )
            return
        order_id_to_cancel: Optional[int] = None
        client_id_to_cancel: Optional[str] = None
        sl_is_algo = False
        close_side = "SELL"
        close_qty = 0.0
        target_price = 0.0
        entry_cid = symbol

        symbol_lock_exec = self._get_lock_for_position(symbol, market_type)
        async with symbol_lock_exec:
            position = self._active_position_get(symbol, market_type)
            if not position or position.status != "OPEN":
                logger.warning(
                    f"{log_prefix} Position not found/open before virtual TP execution."
                )
                return
            if tp_index >= len(position.partial_tp_orders):
                logger.warning(f"{log_prefix} TP index no longer exists.")
                return

            tp = position.partial_tp_orders[tp_index]
            if tp.status != "VIRTUAL_TRIGGERING":
                logger.warning(
                    f"{log_prefix} TP status is {tp.status}, expected VIRTUAL_TRIGGERING."
                )
                return

            order_id_to_cancel = position.current_sl_order_id
            client_id_to_cancel = position.current_sl_client_order_id
            sl_is_algo = position.is_sl_algo_order
            position.current_sl_order_id = None
            position.current_sl_client_order_id = None
            position.is_sl_algo_order = False
            position.sl_placement_initiated = True

            close_side = "SELL" if position.direction == SignalDirection.LONG else "BUY"
            close_qty = min(float(tp.quantity), float(position.remaining_quantity))
            target_price = float(tp.target_price)
            entry_cid = position.entry_client_order_id or symbol

        try:
            if order_id_to_cancel:
                cancel_resp = await executor.cancel_order(
                    symbol=symbol,
                    orderId=order_id_to_cancel,
                    origClientOrderId=client_id_to_cancel,
                    is_algo_order=sl_is_algo,
                )
                if isinstance(cancel_resp, dict) and cancel_resp.get("error"):
                    logger.warning(
                        f"{log_prefix} SL cancel returned error before virtual TP close: {cancel_resp}"
                    )
                else:
                    await asyncio.sleep(0.2)

            position_market_type = (
                self._market_type_for_position(position)
                if position
                else getattr(executor, "market_type", None)
            )
            lot_params = await self._get_market_info(
                symbol, "lot_params", market_type=position_market_type
            )
            min_notional = await self._get_market_info(
                symbol, "min_notional", market_type=position_market_type
            )
            adjusted_qty = self.rm._adjust_and_round_quantity(
                close_qty, symbol, target_price, lot_params, min_notional
            )
            if adjusted_qty is None or adjusted_qty <= 0:
                raise ValueError(
                    f"Invalid virtual TP close quantity after rounding: {adjusted_qty}"
                )

            response = await executor.place_order(
                symbol=symbol,
                side=close_side,
                order_type="MARKET",
                quantity=adjusted_qty,
                reduceOnly=None,
                newClientOrderId=f"x-vtp-{uuid.uuid4().hex[:12]}",
                entry_client_order_id=entry_cid,
                exit_type="VIRTUAL_PARTIAL_TP",
            )
            if isinstance(response, dict) and response.get("error"):
                raise RuntimeError(f"Market close failed: {response}")

        except Exception as exc:
            logger.error(
                f"{log_prefix} Failed to execute virtual TP. Re-arming SL if possible: {exc}",
                exc_info=True,
            )
            position_for_sl: Optional[LivePosition] = None
            symbol_lock_err = self._get_lock_for_position(symbol, market_type)
            async with symbol_lock_err:
                position = self._active_position_get(symbol, market_type)
                if position and tp_index < len(position.partial_tp_orders):
                    position.partial_tp_orders[tp_index].status = "VIRTUAL_PENDING"
                    position.sl_placement_initiated = False
                    position_for_sl = LivePosition(**vars(position))
            if position_for_sl and self._position_has_active_stop_target(
                position_for_sl
            ):
                self.loop.create_task(
                    self._place_stop_loss(position_for_sl),
                    name=f"RearmSL_AfterVirtualTPFail_{symbol}",
                )
            return

        fill_price = target_price
        order_id_resp = None
        client_id_resp = None
        executed_qty = adjusted_qty
        if isinstance(response, dict):
            order_id_resp = response.get("orderId")
            client_id_resp = response.get("clientOrderId")
            for key in ("avgPrice", "average", "price"):
                try:
                    candidate = float(response.get(key) or 0)
                    if candidate > 0:
                        fill_price = candidate
                        break
                except (TypeError, ValueError):
                    pass
            for key in ("executedQty", "filled", "amount", "origQty"):
                try:
                    candidate_qty = float(response.get(key) or 0)
                    if candidate_qty > 0:
                        executed_qty = candidate_qty
                        break
                except (TypeError, ValueError):
                    pass

        position_closed = False
        move_sl_to_be = False
        position_for_new_sl: Optional[LivePosition] = None

        symbol_lock_finish = self._get_lock_for_position(symbol, market_type)
        async with symbol_lock_finish:
            position = self._active_position_get(symbol, market_type)
            if not position or tp_index >= len(position.partial_tp_orders):
                logger.warning(
                    f"{log_prefix} Position/TP disappeared after market close."
                )
                return

            tp = position.partial_tp_orders[tp_index]
            actual_closed_qty = min(
                float(executed_qty), float(position.remaining_quantity)
            )
            tp.status = "FILLED"
            tp.fill_price = fill_price
            tp.order_id = order_id_resp
            tp.client_order_id = client_id_resp
            tp.quantity = actual_closed_qty

            self._append_execution_event(
                position,
                event_type="EXIT",
                execution_type="VIRTUAL_PARTIAL_TAKE_PROFIT",
                price=fill_price,
                quantity=actual_closed_qty,
                order_id=order_id_resp,
                client_order_id=client_id_resp,
                commission=0.0,
                commission_asset=None,
            )

            old_remaining = position.remaining_quantity
            position.remaining_quantity = max(
                0.0, position.remaining_quantity - actual_closed_qty
            )
            position.sl_placement_initiated = False
            logger.info(
                f"{log_prefix} Virtual TP market close filled. Qty {actual_closed_qty:.8f} @ {fill_price:.8f}. "
                f"Remaining {old_remaining:.8f} -> {position.remaining_quantity:.8f}."
            )

            min_step_qty = 0.0
            if lot_params and lot_params.get("stepSize"):
                min_step_qty = float(lot_params["stepSize"])
            if min_step_qty > 0 and position.remaining_quantity < min_step_qty * 0.5:
                position.remaining_quantity = 0.0

            position_closed = position.remaining_quantity <= 0
            if not position_closed:
                filled_before_or_at_this_tp = sum(
                    1 for item in position.partial_tp_orders if item.status == "FILLED"
                )
                move_sl_to_be = bool(
                    position.move_sl_to_be_enabled
                    and not position.is_stop_at_be
                    and filled_before_or_at_this_tp == 1
                )
                position_for_new_sl = LivePosition(**vars(position))

        if position_closed:
            await self._handle_final_exit(
                symbol,
                f"ALL_TP_CLOSED_BY_VIRTUAL_TP_{tp_index + 1}",
                fill_price,
                0.0,
                None,
                order_id_resp,
                client_id_resp,
                realized_pnl_from_exchange=0.0,
                exchange_pnl_available=False,
                market_type=self._market_type_for_position(position),
            )
            return

        if move_sl_to_be:
            self.loop.create_task(
                self._move_stop_loss_to_be(
                    symbol, is_first_attempt_for_be=True, market_type=market_type
                ),
                name=f"MoveSLtoBE_AfterVirtualTP_{symbol}",
            )
        elif position_for_new_sl and self._position_has_active_stop_target(
            position_for_new_sl
        ):
            self.loop.create_task(
                self._place_stop_loss(position_for_new_sl),
                name=f"PlaceSL_AfterVirtualTP_{symbol}",
            )

    async def _place_stop_loss(
        self, position_obj_ref: LivePosition, skip_preflight_check: bool = False
    ) -> bool:
        """
        Places or replaces a stop-loss order for the specified position.
        This method is idempotent and fault-tolerant.

        - Idempotency: If SL is already being placed or is placed, it will not duplicate actions.
        - Fault tolerance: In case of any placement error (invalid parameters, API error, exception),
        the method will send a critical notification to Telegram and initiate an emergency
        market close of the position to protect capital.

        Args:
            position_obj_ref: Reference to the Position object for which SL needs to be placed.

        Returns:
            True if the SL order is successfully placed (or was already placed/in progress).
            False if a critical error occurred that led to the position being closed.
        """
        # Prefix for logs, using the position's Client Order ID for easy identification
        entry_client_order_id_for_log = (
            position_obj_ref.entry_client_order_id or position_obj_ref.symbol
        )
        log_prefix = (
            f"[_PlaceSL:{position_obj_ref.symbol}:{entry_client_order_id_for_log[:8]}]"
        )

        logger.info(f"{log_prefix} --- Attempting to place Stop-Loss ---")

        # Step 1: State check and data collection under lock
        # This block must be as fast as possible to avoid blocking other operations.
        symbol_to_use: str = position_obj_ref.symbol
        position_market_type = self._market_type_for_position(position_obj_ref)
        remaining_qty_to_use: Optional[float] = None
        direction_to_use: Optional[SignalDirection] = None
        sl_price_to_use: Optional[float] = None
        can_place_sl = False

        symbol_lock = self._get_lock_for_position(symbol_to_use, position_market_type)
        async with symbol_lock:
            # Get the most up-to-date version of the position, as position_obj_ref might be outdated
            current_pos_in_db = self._active_position_get(
                symbol_to_use, position_market_type
            )

            # Checking that the position still exists and is in the correct status
            if not current_pos_in_db or current_pos_in_db.status != "OPEN":
                logger.warning(
                    f"{log_prefix} Position not found or not in OPEN status (Status: {current_pos_in_db.status if current_pos_in_db else 'None'}). Canceling SL placement."
                )
                return False

            # Check if SL has already been placed or is in the process of being placed (idempotency)
            if current_pos_in_db.sl_placement_initiated:
                logger.debug(
                    f"{log_prefix} SL placement already initiated. Skipping duplicate attempt."
                )
                return True if current_pos_in_db.current_sl_order_id else False

            if current_pos_in_db.current_sl_order_id:
                logger.info(
                    f"{log_prefix} SL order ID {current_pos_in_db.current_sl_order_id} already exists. Skipping placement."
                )
                return True

            if current_pos_in_db.remaining_quantity <= 0:
                logger.warning(
                    f"{log_prefix} Remaining quantity is zero or less. Impossible to place SL."
                )
                return False

            if self._position_is_intentional_no_sl_mode(current_pos_in_db):
                logger.info(
                    f"{log_prefix} Position is intentionally running without an SL. Placement skipped."
                )
                return True

            sl_price_to_use = current_pos_in_db.current_sl_price
            if sl_price_to_use is None or sl_price_to_use <= 0:
                logger.info(
                    f"{log_prefix} Warning: Valid SL price is missing ({sl_price_to_use}). We assume that the stop-loss order is DISABLED for this position (placement skipped)."
                )
                return True

            # Set a flag to prevent parallel placement attempts
            current_pos_in_db.sl_placement_initiated = True
            logger.info(f"{log_prefix} Flag sl_placement_initiated=True is set.")

            # Copy necessary data for use outside the lock
            remaining_qty_to_use = current_pos_in_db.remaining_quantity
            direction_to_use = current_pos_in_db.direction
            can_place_sl = True

        # If something went wrong during the check under lock
        if not can_place_sl:
            return False

        # Stage 2: Order preparation and placement (outside the lock)
        new_sl_client_id = f"x-sl-{uuid.uuid4().hex[:16]}"
        close_side = "SELL" if direction_to_use == SignalDirection.LONG else "BUY"

        # CRITICAL IMPROVEMENT: Synchronization with the real position size on the exchange
        # This prevents situations where the internal remaining_quantity is outdated or incorrect
        executor = await self._get_executor_for_symbol(
            symbol_to_use, market_type=position_market_type
        )
        if executor:
            try:
                exchange_positions = await executor.get_open_positions()
                exchange_pos_data = next(
                    (
                        p
                        for p in exchange_positions
                        if p["symbol"] == symbol_to_use
                        and float(p.get("positionAmt", 0)) != 0
                    ),
                    None,
                )
                if exchange_pos_data:
                    real_qty = abs(float(exchange_pos_data["positionAmt"]))
                    if abs(remaining_qty_to_use - real_qty) > 1e-9:
                        logger.warning(
                            f"{log_prefix} SYNC: Internal qty {remaining_qty_to_use:.8f} differs from exchange qty {real_qty:.8f}. Using exchange value!"
                        )
                        remaining_qty_to_use = real_qty
                        # Also updating the internal state
                        symbol_lock_qty_sync = self._get_lock_for_position(
                            symbol_to_use, position_market_type
                        )
                        async with symbol_lock_qty_sync:
                            pos_for_qty_sync = self._active_position_get(
                                symbol_to_use, position_market_type
                            )
                            if pos_for_qty_sync:
                                pos_for_qty_sync.remaining_quantity = real_qty
                else:
                    logger.warning(
                        f"{log_prefix} No position found on exchange for {symbol_to_use}. Proceeding with internal qty {remaining_qty_to_use:.8f}"
                    )
            except Exception as sync_err:
                logger.error(
                    f"{log_prefix} Failed to sync position qty with exchange: {sync_err}. Proceeding with internal qty {remaining_qty_to_use:.8f}"
                )

        position_market_type = self._market_type_for_position(position_obj_ref)
        lot_params = await self._get_market_info(
            symbol_to_use, "lot_params", market_type=position_market_type
        )
        min_notional = await self._get_market_info(
            symbol_to_use, "min_notional", market_type=position_market_type
        )
        tick_size = (
            await self._get_market_info(
                symbol_to_use, "tick_size", market_type=position_market_type
            )
            or config.DEFAULT_TICK_SIZE
        )

        adj_qty = self.rm._adjust_and_round_quantity(
            remaining_qty_to_use,
            symbol_to_use,
            sl_price_to_use,
            lot_params,
            min_notional,
        )

        if adj_qty is None or adj_qty <= 0:
            logger.error(
                f"{log_prefix} Invalid quantity {remaining_qty_to_use:.8f} for SL (price {sl_price_to_use:.8f}) after adjustment."
            )
            symbol_lock_fail_qty = self._get_lock_for_position(
                symbol_to_use, position_market_type
            )
            async with symbol_lock_fail_qty:
                pos_on_fail_qty = self._active_position_get(
                    symbol_to_use, position_market_type
                )
                if pos_on_fail_qty and pos_on_fail_qty.sl_placement_initiated:
                    pos_on_fail_qty.sl_placement_initiated = (
                        False  # Reset flag on error
                    )

            # NOTIFICATION
            if self.telegram_notifier:
                self.loop.create_task(
                    self.telegram_notifier.bot_error(
                        error_description=f"CRITICAL ERROR: Invalid quantity for SL on {symbol_to_use}!",
                        module_function="_place_stop_loss",
                        action_taken=f"Emergency position closure initiated {symbol_to_use}.",
                        chat_id=self.user_telegram_chat_id,
                        api_key_name=self.api_key_name,
                    ),
                    name=f"Notify_SLQtyFail_{symbol_to_use}",
                )

            self.loop.create_task(
                self.close_position(
                    symbol_to_use,
                    "EMERGENCY_SL_QTY_INVALID",
                    market_type=position_market_type,
                )
            )
            return False

        rounding_mode_sl = (
            ROUND_DOWN if direction_to_use == SignalDirection.LONG else ROUND_UP
        )
        rounded_sl_price = self._round_price(
            sl_price_to_use, tick_size, rounding_mode_sl
        )

        if rounded_sl_price is None or rounded_sl_price <= 0:
            logger.error(
                f"{log_prefix} Invalid rounded SL price ({rounded_sl_price}). Unable to place SL."
            )
            symbol_lock_fail_price = self._get_lock_for_position(
                symbol_to_use, position_market_type
            )
            async with symbol_lock_fail_price:  # Resetting the flag
                pos_fail_price = self._active_position_get(
                    symbol_to_use, position_market_type
                )
                if pos_fail_price and pos_fail_price.sl_placement_initiated:
                    pos_fail_price.sl_placement_initiated = False

            # NOTIFICATION
            if self.telegram_notifier:
                self.loop.create_task(
                    self.telegram_notifier.bot_error(
                        error_description=f"CRITICAL ERROR: Invalid price for SL on {symbol_to_use}!",
                        module_function="_place_stop_loss",
                        action_taken=f"Emergency position closure initiated {symbol_to_use}.",
                        chat_id=self.user_telegram_chat_id,
                        api_key_name=self.api_key_name,
                    ),
                    name=f"Notify_SLPriceFail_{symbol_to_use}",
                )

            self.loop.create_task(
                self.close_position(
                    symbol_to_use,
                    "EMERGENCY_SL_PRICE_INVALID",
                    market_type=position_market_type,
                )
            )
            return False

        sl_params_for_executor = {
            "quantity": adj_qty,
            "stopPrice": rounded_sl_price,
            "newClientOrderId": new_sl_client_id,
            "strategy_config_id": position_obj_ref.config_id,
            "entry_client_order_id": position_obj_ref.entry_client_order_id,
            "signal_details": position_obj_ref.signal_details,
        }

        executor = await self._get_executor_for_symbol(
            symbol_to_use, market_type=position_market_type
        )
        if not executor:
            logger.error(
                f"{log_prefix} Could not determine executor. Aborting SL placement."
            )
            return False

        if executor.market_type == "futures_usdtm":
            order_type_for_sl_api = "STOP_MARKET"
            sl_params_for_executor["reduceOnly"] = "true"
        else:
            # For Binance Spot, STOP_MARKET is often not available.
            # STOP_LOSS is a market order that triggers when stopPrice is reached.
            order_type_for_sl_api = "STOP_LOSS"

        # PRE-FLIGHT CHECK
        # Skip this check when REPLACING a stop (BE/trailing) because:
        # 1. If the price has already moved past the new stop level, the stop will simply trigger — this is normal
        # 2. Emergency closure when replacing a stop breaks the BE/trailing logic
        if not skip_preflight_check:
            try:
                # Get the latest market price for verification
                ticker_info = await executor.get_ticker_price(symbol=symbol_to_use)
                if not ticker_info or "price" not in ticker_info:
                    raise ValueError(
                        "Could not fetch current price for pre-flight SL check."
                    )

                current_market_price = float(ticker_info["price"])

                # Checking the immediate trigger condition
                if (
                    direction_to_use == SignalDirection.LONG
                    and rounded_sl_price >= current_market_price
                ):
                    error_msg = f"Stop-loss price ({rounded_sl_price}) is at or above current market price ({current_market_price}). Order would trigger immediately."
                    logger.critical(
                        f"{log_prefix} CRITICAL: {error_msg} Position is unprotected."
                    )
                    raise ValueError(
                        error_msg
                    )  # Raising an exception to get into the error handling block below

                if (
                    direction_to_use == SignalDirection.SHORT
                    and rounded_sl_price <= current_market_price
                ):
                    error_msg = f"Stop-loss price ({rounded_sl_price}) is at or below current market price ({current_market_price}). Order would trigger immediately."
                    logger.critical(
                        f"{log_prefix} CRITICAL: {error_msg} Position is unprotected."
                    )
                    raise ValueError(error_msg)  # Raising an exception

            except (ValueError, KeyError, TypeError) as pre_flight_exc:
                logger.error(
                    f"{log_prefix} Pre-flight SL check failed: {pre_flight_exc}. Closing position for safety.",
                    exc_info=True,
                )
                # If the check fails, emergency close the position as it is not protected
                self.loop.create_task(
                    self.close_position(
                        symbol_to_use,
                        "EMERGENCY_SL_PREFLIGHT_CHECK_FAILED",
                        market_type=position_market_type,
                    )
                )
                return False  # Returning False as SL placement failed
        else:
            logger.info(
                f"{log_prefix} Skipping pre-flight SL check (skip_preflight_check=True, likely BE/trailing replacement)."
            )

        logger.info(
            f"{log_prefix} Placing SL (API Type: {order_type_for_sl_api}). Parameters: {sl_params_for_executor}"
        )
        sl_resp: Optional[Dict[str, Any]] = None
        try:
            sl_resp = await executor.place_order(
                symbol=symbol_to_use,
                side=close_side,
                order_type=order_type_for_sl_api,
                **sl_params_for_executor,
            )
            logger.info(f"{log_prefix} Exchange response for SL placement: {sl_resp}")
        except Exception as e:
            logger.error(
                f"{log_prefix} EXCEPTION during SL placement: {e}", exc_info=True
            )
            symbol_lock_except = self._get_lock_for_position(
                symbol_to_use, position_market_type
            )
            async with symbol_lock_except:
                pos_on_except = self._active_position_get(
                    symbol_to_use, position_market_type
                )
                if pos_on_except and pos_on_except.sl_placement_initiated:
                    pos_on_except.sl_placement_initiated = False

            # NOTIFICATION
            if self.telegram_notifier:
                self.loop.create_task(
                    self.telegram_notifier.bot_error(
                        error_description=f"CRITICAL ERROR: Exception when placing SL on {symbol_to_use}!",
                        module_function="_place_stop_loss",
                        action_taken=f"Emergency position closure initiated. Error: {e}",
                        chat_id=self.user_telegram_chat_id,
                        api_key_name=self.api_key_name,
                    ),
                    name=f"Notify_SLExcept_{symbol_to_use}",
                )

            self.loop.create_task(
                self.close_position(
                    symbol_to_use,
                    "EMERGENCY_SL_EXCEPTION",
                    market_type=position_market_type,
                )
            )
            return False

        # Stage 3: Processing the response and updating the state under lock
        if sl_resp and not sl_resp.get("error"):
            # Algo Order API returns 'algoId' and 'clientAlgoId' instead of 'orderId' and 'clientOrderId'
            order_id_resp = sl_resp.get("orderId") or sl_resp.get("algoId")
            client_id_resp = sl_resp.get("clientOrderId") or sl_resp.get(
                "clientAlgoId", new_sl_client_id
            )
            is_algo_order = "algoId" in sl_resp or (
                executor
                and getattr(executor, "exchange_id", "") == "bitget"
                and not getattr(executor, "supports_positions", True)
            )  # Remember that this is an Algo Order for subsequent cancellation

            symbol_lock_after_place = self._get_lock_for_position(
                symbol_to_use, position_market_type
            )
            async with symbol_lock_after_place:
                pos_after_place = self._active_position_get(
                    symbol_to_use, position_market_type
                )
                if pos_after_place and pos_after_place.status == "OPEN":
                    if pos_after_place.current_sl_order_id is None:
                        pos_after_place.current_sl_order_id = order_id_resp
                        pos_after_place.current_sl_client_order_id = client_id_resp
                        # Save the flag that this is an Algo Order (for correct cancellation)
                        pos_after_place.is_sl_algo_order = is_algo_order
                        pos_after_place.sl_placement_initiated = False
                        logger.info(
                            f"{log_prefix} SL order PLACED. ID={order_id_resp} (AlgoOrder={is_algo_order}). Position object updated."
                        )
                        return True
                    else:
                        logger.warning(
                            f"{log_prefix} SL was placed (ID {order_id_resp}), but a different SL ID ({pos_after_place.current_sl_order_id}) already exists. Canceling new SL."
                        )
                        executor_for_cancel = self.executors.get(
                            pos_after_place.mode if pos_after_place else "live",
                            self.executors.get("live"),
                        )
                        self.loop.create_task(
                            executor_for_cancel.cancel_order(
                                symbol=symbol_to_use,
                                orderId=order_id_resp,
                                origClientOrderId=client_id_resp,
                                is_algo_order=is_algo_order,
                            )
                        )
                        return False
                else:
                    logger.warning(
                        f"{log_prefix} SL placed (ID {order_id_resp}), but the position is already closed or not found. Canceling this 'orphaned' SL."
                    )
                    if order_id_resp:
                        # Position not found, using 'live' by default
                        executor_for_cancel = self.executors.get("live")
                        self.loop.create_task(
                            executor_for_cancel.cancel_order(
                                symbol=symbol_to_use,
                                orderId=order_id_resp,
                                origClientOrderId=client_id_resp,
                                is_algo_order=is_algo_order,
                            )
                        )
                    return False
        else:  # Error from API
            err_msg = (
                sl_resp.get("msg", "Unknown error")
                if isinstance(sl_resp, dict)
                else "No response"
            )
            logger.critical(
                f"{log_prefix} FAILED TO PLACE SL! Position is not protected. API response: {err_msg}."
            )
            symbol_lock_api_fail = self._get_lock_for_position(
                symbol_to_use, position_market_type
            )
            async with symbol_lock_api_fail:
                pos_on_api_fail = self._active_position_get(
                    symbol_to_use, position_market_type
                )
                if pos_on_api_fail and pos_on_api_fail.sl_placement_initiated:
                    pos_on_api_fail.sl_placement_initiated = False  # Resetting flag

            # NOTIFICATION
            if self.telegram_notifier:
                self.loop.create_task(
                    self.telegram_notifier.bot_error(
                        error_description=f"CRITICAL ERROR: API rejected SL placement for {symbol_to_use}!",
                        module_function="_place_stop_loss",
                        action_taken=f"Emergency closure initiated. API response: {err_msg}",
                        chat_id=self.user_telegram_chat_id,
                        api_key_name=self.api_key_name,
                    ),
                    name=f"Notify_SLApiFail_{symbol_to_use}",
                )

            self.loop.create_task(
                self.close_position(
                    symbol_to_use,
                    "EMERGENCY_SL_API_FAIL",
                    market_type=position_market_type,
                )
            )
            return False

    async def _place_exchange_trailing_stop(
        self, position_obj_ref: LivePosition
    ) -> bool:
        """
        Places an exchange TRAILING_STOP_MARKET order if the trailing_stop block
        in the strategy configuration has mode='exchange'.

        TRAILING_STOP_MARKET on Binance:
        - activationPrice: trailing activation price (optional)
        - callbackRate: callback percentage (0.1 - 5.0)

        Returns:
            True if the order is placed successfully, False otherwise
        """
        symbol = position_obj_ref.symbol
        entry_cid = position_obj_ref.entry_client_order_id or symbol
        log_prefix = f"[_PlaceExchangeTrailing:{symbol}:{entry_cid[:8]}]"

        # Get the config_id of the position to retrieve the strategy config
        config_id = position_obj_ref.config_id
        if not config_id:
            logger.debug(
                f"{log_prefix} No config_id in position, skipping exchange trailing stop."
            )
            return False

        # Getting strategy configuration
        strategy_config = None
        async with self.instances_lock:
            instance_tuple = self.running_strategy_instances.get(config_id)
            if instance_tuple:
                _, strategy_config = instance_tuple

        if not strategy_config:
            logger.debug(
                f"{log_prefix} Strategy config not found for config_id={config_id}."
            )
            return False

        # Looking for a trailing_stop block with mode='exchange' in the management section
        config_data = strategy_config.get("config_data", {})
        management_blocks = config_data.get(
            "positionManagement", config_data.get("management", [])
        )

        trailing_block = None
        for block in management_blocks:
            if block.get("type") == "trailing_stop":
                params = block.get("params", {})
                if params.get("mode") == "exchange":
                    trailing_block = block
                    break

        if not trailing_block:
            logger.debug(
                f"{log_prefix} No trailing_stop block with mode='exchange' found."
            )
            return False

        params = trailing_block.get("params", {})
        ts_type = params.get("type", "Percentage")  # ATR or Percentage
        ts_value = params.get("value", 2.0)

        # Convert the value to callbackRate (0.1 - 5.0 for Binance)
        callback_rate = None
        if ts_type == "Percentage":
            # Direct use of percentage
            callback_rate = float(ts_value)
        elif ts_type == "ATR":
            # Convert ATR to percentage via entry_price and ATR at the time of entry
            atr = position_obj_ref.entry_atr
            entry_price = position_obj_ref.entry_price
            if atr and entry_price and entry_price > 0:
                atr_value = atr * float(ts_value)  # ATR * multiplier
                callback_rate = (atr_value / entry_price) * 100.0  # Percentage of price
                logger.info(
                    f"{log_prefix} ATR mode: ATR={atr}, multiplier={ts_value}, callback_rate={callback_rate:.2f}%"
                )
            else:
                logger.error(
                    f"{log_prefix} Cannot calculate callbackRate from ATR: entry_atr={atr}, entry_price={entry_price}"
                )
                return False

        if callback_rate is None:
            logger.error(
                f"{log_prefix} Failed to calculate callbackRate for type={ts_type}"
            )
            return False

        # Binance limits callbackRate from 0.1 to 5.0
        callback_rate = max(0.1, min(5.0, callback_rate))
        logger.info(
            f"{log_prefix} Final callbackRate: {callback_rate:.2f}% (clamped to 0.1-5.0)"
        )

        # Getting parameters for the order
        quantity = position_obj_ref.remaining_quantity
        if not quantity or quantity <= 0:
            logger.error(f"{log_prefix} Invalid remaining_quantity: {quantity}")
            return False

        direction = position_obj_ref.direction
        close_side = "SELL" if direction == SignalDirection.LONG else "BUY"

        executor = self.executors.get(position_obj_ref.mode, self.executors.get("live"))

        trailing_order_params = {
            "quantity": quantity,
            "callbackRate": callback_rate,
            "workingType": "CONTRACT_PRICE",  # Use contract price
            "reduceOnly": "true",
            "newClientOrderId": f"x-tslmkt-{uuid.uuid4().hex[:12]}",
        }

        # Optionally, activationPrice can be added to activate trailing at a specific level
        # Leaving it without for now - trailing activates immediately

        logger.info(
            f"{log_prefix} Placing TRAILING_STOP_MARKET order: {trailing_order_params}"
        )

        try:
            resp = await executor.place_order(
                symbol=symbol,
                side=close_side,
                order_type="TRAILING_STOP_MARKET",
                **trailing_order_params,
            )

            if resp and not resp.get("error"):
                order_id = resp.get("orderId") or resp.get("algoId")
                logger.info(
                    f"{log_prefix} TRAILING_STOP_MARKET placed successfully! OrderID={order_id}"
                )
                # order_id can be saved to the position if necessary
                return True
            else:
                err_msg = resp.get("msg", "Unknown error") if resp else "No response"
                logger.error(
                    f"{log_prefix} Failed to place TRAILING_STOP_MARKET: {err_msg}"
                )
                return False
        except Exception as e:
            logger.error(
                f"{log_prefix} Exception placing TRAILING_STOP_MARKET: {e}",
                exc_info=True,
            )
            return False

    async def _place_partial_tp(
        self,
        position_obj_ref: LivePosition,
        target_price: float,
        quantity_to_close: float,
        orig_fraction: float,  # Saving for possible identification/logging
        ptp_internal_idx: Optional[int] = None,
    ) -> None:  # Index in the position.partial_tp_orders list or -1 for the final one
        entry_client_order_id_for_log = (
            position_obj_ref.entry_client_order_id or position_obj_ref.symbol
        )
        idx_log_str = (
            f"Idx={ptp_internal_idx}"
            if ptp_internal_idx is not None and ptp_internal_idx >= 0
            else "FinalTP"
        )
        log_prefix = f"[_PlacePTP:{entry_client_order_id_for_log}:{idx_log_str}:Tgt={target_price:.8f},Qty={quantity_to_close:.8f}]"

        new_tp_client_id = f"x-ptp-{uuid.uuid4().hex[:15]}"  # Unique ID for the order

        symbol_to_use: Optional[str] = position_obj_ref.symbol
        position_market_type = self._market_type_for_position(position_obj_ref)
        direction_to_use: Optional[SignalDirection] = None
        can_place_ptp = False
        # Key for the initiated flag: index from the partial_tp_orders list, or -1 if it is a final TP not from the list
        flag_key_for_initiated_check = (
            ptp_internal_idx
            if ptp_internal_idx is not None and ptp_internal_idx >= 0
            else -1
        )

        symbol_lock = self._get_lock_for_position(symbol_to_use, position_market_type)
        async with symbol_lock:
            current_pos_in_db = self._active_position_get(
                symbol_to_use, position_market_type
            )

            if not current_pos_in_db or current_pos_in_db.status != "OPEN":
                logger.warning(
                    f"{log_prefix} Pos {entry_client_order_id_for_log}: Not found or not OPEN in DB (Status: {current_pos_in_db.status if current_pos_in_db else 'None'}). Skipping PTP."
                )
                return

            if current_pos_in_db.remaining_quantity <= 0:  # Checking remaining quantity
                logger.warning(
                    f"{log_prefix} Pos {entry_client_order_id_for_log}: Rem. qty zero or less ({current_pos_in_db.remaining_quantity:.8f}). Cannot place PTP."
                )
                return

            # Check if this TP has already been initiated
            if current_pos_in_db.ptp_placement_initiated_flags.get(
                flag_key_for_initiated_check, False
            ):
                logger.debug(
                    f"{log_prefix} Pos {entry_client_order_id_for_log}: PTP (key {flag_key_for_initiated_check}) placement already initiated. Skipping."
                )
                return

            # Check if there is already an active order for this specific TP (if it is from the list)
            ptp_info_object_in_pos: Optional[PartialTpOrderInfo] = None
            is_this_final_tp_not_in_list = False

            if flag_key_for_initiated_check >= 0 and flag_key_for_initiated_check < len(
                current_pos_in_db.partial_tp_orders
            ):
                ptp_candidate = current_pos_in_db.partial_tp_orders[
                    flag_key_for_initiated_check
                ]
                # Additionally check the price and original share match to ensure it is the same TP
                if (
                    abs(ptp_candidate.target_price - target_price) < 1e-9 * target_price
                    and abs(ptp_candidate.orig_fraction - orig_fraction) < 1e-9
                ):
                    ptp_info_object_in_pos = ptp_candidate
                    if (
                        ptp_info_object_in_pos.order_id
                        or ptp_info_object_in_pos.client_order_id
                    ):
                        logger.debug(
                            f"{log_prefix} Pos {entry_client_order_id_for_log}: PTP (key {flag_key_for_initiated_check}) order ID/CliID already exists (ID: {ptp_info_object_in_pos.order_id}, Status: {ptp_info_object_in_pos.status}). Skipping."
                        )
                        return
            elif flag_key_for_initiated_check == -1:  # Final TP
                is_this_final_tp_not_in_list = True  # Assuming that for the final TP (not from the list) there is no entry in partial_tp_orders yet
                # (or it will be added later if successfully placed)

            # Set the flag that placement is initiated
            current_pos_in_db.ptp_placement_initiated_flags[
                flag_key_for_initiated_check
            ] = True
            logger.info(
                f"{log_prefix} Pos {entry_client_order_id_for_log}: Marking ptp_placement_initiated_flags[{flag_key_for_initiated_check}]=True."
            )

            direction_to_use = current_pos_in_db.direction
            can_place_ptp = True

        if not can_place_ptp:  # If something went wrong under the lock
            return

        # Order side for closing
        close_side = "SELL" if direction_to_use == SignalDirection.LONG else "BUY"

        # Ensure that quantity_to_close is valid
        if quantity_to_close <= 0:
            logger.error(
                f"{log_prefix} Pos {entry_client_order_id_for_log}: Invalid quantity_to_close ({quantity_to_close:.8f}) for PTP. Cannot place."
            )
            symbol_lock_fail_qty_ptp = self._get_lock_for_position(
                symbol_to_use, position_market_type
            )
            async with symbol_lock_fail_qty_ptp:  # Resetting flag on error
                pos_on_fail_qty_ptp = self._active_position_get(
                    symbol_to_use, position_market_type
                )
                if (
                    pos_on_fail_qty_ptp
                    and pos_on_fail_qty_ptp.ptp_placement_initiated_flags.get(
                        flag_key_for_initiated_check, False
                    )
                ):
                    pos_on_fail_qty_ptp.ptp_placement_initiated_flags[
                        flag_key_for_initiated_check
                    ] = False
            return

        # Use LIMIT order for TP
        order_type_for_api = "LIMIT"

        # Rounding TP price to tick step
        tick_size_tp = (
            await self._get_market_info(
                symbol_to_use, "tick_size", market_type=position_market_type
            )
            or config.DEFAULT_TICK_SIZE
        )
        # Price rounding for TP limit order:
        # - For LONG position (TP is SELL): round UP (to get the best or the same price)
        # - For SHORT position (TP is BUY): round DOWN (to get the best or the same price)
        rounding_mode_tp = (
            ROUND_UP if direction_to_use == SignalDirection.LONG else ROUND_DOWN
        )
        rounded_target_price = self._round_price(
            target_price, tick_size_tp, rounding_mode_tp
        )

        if rounded_target_price is None or rounded_target_price <= 0:
            logger.error(
                f"{log_prefix} Pos {entry_client_order_id_for_log}: Invalid rounded target_price ({rounded_target_price}) for PTP. Original: {target_price}. Cannot place."
            )
            symbol_lock_fail_price_ptp = self._get_lock_for_position(
                symbol_to_use, position_market_type
            )
            async with symbol_lock_fail_price_ptp:  # Resetting the flag
                pos_on_fail_price_ptp = self._active_position_get(
                    symbol_to_use, position_market_type
                )
                if (
                    pos_on_fail_price_ptp
                    and pos_on_fail_price_ptp.ptp_placement_initiated_flags.get(
                        flag_key_for_initiated_check, False
                    )
                ):
                    pos_on_fail_price_ptp.ptp_placement_initiated_flags[
                        flag_key_for_initiated_check
                    ] = False
            return

        # 1. Get the correct executor for the current position
        executor = await self._get_executor_for_symbol(
            symbol_to_use, market_type=position_market_type
        )
        if not executor:
            logger.error(
                f"{log_prefix} Pos {entry_client_order_id_for_log}: Could not determine executor. Aborting PTP placement."
            )
            # Resetting the flag if failed to get executor
            symbol_lock_fail_exec_ptp = self._get_lock_for_position(
                symbol_to_use, position_market_type
            )
            async with symbol_lock_fail_exec_ptp:
                pos_on_fail_exec = self._active_position_get(
                    symbol_to_use, position_market_type
                )
                if (
                    pos_on_fail_exec
                    and pos_on_fail_exec.ptp_placement_initiated_flags.get(
                        flag_key_for_initiated_check, False
                    )
                ):
                    pos_on_fail_exec.ptp_placement_initiated_flags[
                        flag_key_for_initiated_check
                    ] = False
            return

        # 2. Forming order parameters
        symbol_lock_params_ptp = self._get_lock_for_position(
            symbol_to_use, position_market_type
        )
        async with symbol_lock_params_ptp:
            pos_for_virtual_check = self._active_position_get(
                symbol_to_use, position_market_type
            )
            if pos_for_virtual_check and self._position_has_exchange_spot_sl_lock(
                pos_for_virtual_check, executor
            ):
                if (
                    flag_key_for_initiated_check >= 0
                    and flag_key_for_initiated_check
                    < len(pos_for_virtual_check.partial_tp_orders)
                ):
                    virtual_tp = pos_for_virtual_check.partial_tp_orders[
                        flag_key_for_initiated_check
                    ]
                    virtual_tp.status = "VIRTUAL_PENDING"
                    virtual_tp.order_id = None
                    virtual_tp.client_order_id = None
                elif is_this_final_tp_not_in_list:
                    pos_for_virtual_check.partial_tp_orders.append(
                        PartialTpOrderInfo(
                            target_price=target_price,
                            orig_fraction=orig_fraction,
                            quantity=quantity_to_close,
                            status="VIRTUAL_PENDING",
                        )
                    )
                pos_for_virtual_check.ptp_placement_initiated_flags[
                    flag_key_for_initiated_check
                ] = False
                logger.info(
                    f"{log_prefix} Spot TP will be tracked virtually because active SL locks base balance."
                )
                return

        tp_params_to_send = {
            "quantity": quantity_to_close,
            "price": f"{rounded_target_price:.8f}",
            "timeInForce": "GTC",
            "newClientOrderId": new_tp_client_id,
            "strategy_config_id": position_obj_ref.config_id,  # Add strategy_config_id for paper trading
            "entry_client_order_id": position_obj_ref.entry_client_order_id,
            "signal_details": position_obj_ref.signal_details,
        }

        # 3. Use the obtained executor to check market_type
        if executor.market_type == "futures_usdtm":
            if getattr(executor, "exchange_id", "") == "gateio":
                order_type_for_api = "TAKE_PROFIT_MARKET"
                tp_params_to_send["stopPrice"] = float(rounded_target_price)
                tp_params_to_send["reduceOnly"] = "true"
                tp_params_to_send.pop("price", None)
                tp_params_to_send.pop("timeInForce", None)
            else:
                tp_params_to_send["reduceOnly"] = "true"

        logger.info(
            f"{log_prefix} Pos {entry_client_order_id_for_log}: Preparing to place LIMIT TP. RoundedPrice: {rounded_target_price:.8f}, Qty: {quantity_to_close:.8f}, ClientID: {new_tp_client_id}, ReduceOnly: {tp_params_to_send.get('reduceOnly', 'N/A')}"
        )

        tp_resp = None
        try:
            # 4. Use the obtained executor to send the order
            tp_resp = await executor.place_order(
                symbol=symbol_to_use,
                side=close_side,
                order_type=order_type_for_api,  # "LIMIT"
                **tp_params_to_send,
            )
            logger.info(
                f"{log_prefix} Pos {entry_client_order_id_for_log}: LIMIT TP order placement response: {tp_resp}"
            )
        except Exception as e:
            logger.error(
                f"{log_prefix} Pos {entry_client_order_id_for_log}: Exception placing LIMIT TP: {e}",
                exc_info=True,
            )
            symbol_lock_except_ptp = self._get_lock_for_position(
                symbol_to_use, position_market_type
            )
            async with symbol_lock_except_ptp:  # Resetting the flag
                pos_on_except_ptp = self._active_position_get(
                    symbol_to_use, position_market_type
                )
                if (
                    pos_on_except_ptp
                    and pos_on_except_ptp.ptp_placement_initiated_flags.get(
                        flag_key_for_initiated_check, False
                    )
                ):
                    pos_on_except_ptp.ptp_placement_initiated_flags[
                        flag_key_for_initiated_check
                    ] = False
            self.trade_logger.log_event(
                event_type="TP_ORDER_FAILED",
                data={
                    "symbol": symbol_to_use,
                    "target_price": target_price,
                    "reason": f"Executor exception: {str(e)}",
                    "params": tp_params_to_send,
                    "entry_client_order_id": entry_client_order_id_for_log,
                },
            )
            return

        symbol_lock_after_tp_resp = self._get_lock_for_position(
            symbol_to_use, position_market_type
        )
        async with symbol_lock_after_tp_resp:
            pos_in_lock_after_place = self._active_position_get(
                symbol_to_use, position_market_type
            )
            if not pos_in_lock_after_place:
                logger.error(
                    f"{log_prefix} Pos {entry_client_order_id_for_log}: Position disappeared before LIMIT TP response processed."
                )
                if tp_resp and not tp_resp.get("error") and tp_resp.get("orderId"):
                    logger.warning(
                        f"{log_prefix} Pos gone, attempting to cancel orphaned LIMIT TP ID {tp_resp.get('orderId')} for {entry_client_order_id_for_log}"
                    )
                    executor_for_cancel = self.executors.get(
                        position_obj_ref.mode if position_obj_ref else "live",
                        self.executors.get("live"),
                    )
                    self.loop.create_task(
                        executor_for_cancel.cancel_order(
                            symbol=symbol_to_use,
                            orderId=tp_resp.get("orderId"),
                            origClientOrderId=new_tp_client_id,
                        )
                    )
                return

            ptp_info_to_update: Optional[PartialTpOrderInfo] = None
            created_new_ptp_for_final_tp_in_lock = False

            if flag_key_for_initiated_check >= 0 and flag_key_for_initiated_check < len(
                pos_in_lock_after_place.partial_tp_orders
            ):
                # Updating existing PartialTpOrderInfo
                ptp_candidate_in_lock = pos_in_lock_after_place.partial_tp_orders[
                    flag_key_for_initiated_check
                ]
                if (
                    abs(ptp_candidate_in_lock.target_price - target_price)
                    < 1e-9 * target_price
                    and abs(ptp_candidate_in_lock.orig_fraction - orig_fraction) < 1e-9
                    and abs(ptp_candidate_in_lock.quantity - quantity_to_close)
                    < 1e-9 * quantity_to_close
                ):
                    ptp_info_to_update = ptp_candidate_in_lock
            elif is_this_final_tp_not_in_list:
                # If this is a final TP that was not in the list, it will be added below if the order is successful
                pass

            if tp_resp and not tp_resp.get("error"):
                order_id_resp = tp_resp.get("orderId")
                client_id_resp = tp_resp.get("clientOrderId", new_tp_client_id)
                logger.info(
                    f"{log_prefix} Pos {entry_client_order_id_for_log}: LIMIT TP order PLACED. ID={order_id_resp}, ClientID={client_id_resp}"
                )

                if ptp_info_to_update:
                    ptp_info_to_update.order_id = order_id_resp
                    ptp_info_to_update.client_order_id = client_id_resp
                    ptp_info_to_update.status = "PENDING"
                elif (
                    is_this_final_tp_not_in_list
                ):  # This is the final TP that was not part of the list
                    new_final_tp_entry = PartialTpOrderInfo(
                        target_price=target_price,  # Use the original (not rounded) target price for the object
                        orig_fraction=orig_fraction,
                        quantity=quantity_to_close,
                        order_id=order_id_resp,
                        client_order_id=client_id_resp,
                        status="PENDING",
                    )
                    pos_in_lock_after_place.partial_tp_orders.append(new_final_tp_entry)
                    created_new_ptp_for_final_tp_in_lock = True
                    logger.info(
                        f"{log_prefix} Pos {entry_client_order_id_for_log}: Added final LIMIT TP as new entry to partial_tp_orders."
                    )
                else:
                    logger.error(
                        f"{log_prefix} Pos {entry_client_order_id_for_log}: Could not find PTP info object for successful LIMIT TP placement. This is unexpected. Index: {ptp_internal_idx}, Target: {target_price}"
                    )

                self.trade_logger.log_event(
                    event_type="TP_ORDER_PLACED",
                    data={
                        "order_type": "LIMIT_TP",
                        "entry_client_order_id": entry_client_order_id_for_log,
                        **tp_resp,
                    },
                )

            else:  # Placement error from Executor
                err_msg_tp = (
                    tp_resp.get("msg", "Unknown error")
                    if isinstance(tp_resp, dict)
                    else "No response"
                )
                logger.error(
                    f"{log_prefix} Pos {entry_client_order_id_for_log}: FAILED TO PLACE LIMIT TP. Response: {err_msg_tp}"
                )

                if ptp_info_to_update:
                    ptp_info_to_update.status = "FAILED"
                    ptp_info_to_update.client_order_id = new_tp_client_id
                elif is_this_final_tp_not_in_list:
                    new_failed_final_tp_entry = PartialTpOrderInfo(
                        target_price=target_price,
                        orig_fraction=orig_fraction,
                        quantity=quantity_to_close,
                        status="FAILED",
                        client_order_id=new_tp_client_id,
                    )
                    pos_in_lock_after_place.partial_tp_orders.append(
                        new_failed_final_tp_entry
                    )
                    created_new_ptp_for_final_tp_in_lock = True
                # Resetting the flag if placement failed
                if pos_in_lock_after_place.ptp_placement_initiated_flags.get(
                    flag_key_for_initiated_check, False
                ):
                    pos_in_lock_after_place.ptp_placement_initiated_flags[
                        flag_key_for_initiated_check
                    ] = False
                    logger.warning(
                        f"{log_prefix} Pos {entry_client_order_id_for_log}: LIMIT TP placement failed (API error). Reset ptp_placement_initiated_flags[{flag_key_for_initiated_check}]."
                    )

                self.trade_logger.log_event(
                    event_type="TP_ORDER_FAILED",
                    data={
                        "symbol": symbol_to_use,
                        "target_price": target_price,
                        "reason": f"Binance error: {err_msg_tp}",
                        "params": tp_params_to_send,
                        "entry_client_order_id": entry_client_order_id_for_log,
                        **(tp_resp or {}),
                    },
                )

            if (
                created_new_ptp_for_final_tp_in_lock
            ):  # If a new element was added, re-sort
                pos_in_lock_after_place.partial_tp_orders.sort(
                    key=lambda x: x.target_price,
                    reverse=(
                        pos_in_lock_after_place.direction == SignalDirection.SHORT
                    ),
                )
                logger.debug(
                    f"{log_prefix} Pos {entry_client_order_id_for_log}: partial_tp_orders list re-sorted after adding final LIMIT TP."
                )

    async def _cancel_all_exit_orders(
        self,
        symbol: str,
        reason: str,
        exclude_order_id: Optional[int] = None,
        market_type: Optional[str] = None,
    ):
        """Cancels ALL active exit orders (SL and partial TPs) for the position."""
        log_prefix = f"[_CancelAllExits:{symbol}:{reason}]"
        # List of tuples: (order_id, client_order_id, is_algo_order)
        orders_to_cancel_details: List[Tuple[Optional[int], Optional[str], bool]] = []

        symbol_lock_cancel_all = self._get_lock_for_position(symbol, market_type)
        async with symbol_lock_cancel_all:
            position = self._active_position_get(symbol, market_type)
            # Checking that the position exists
            if not position:
                logger.debug(
                    f"{log_prefix} Position not found for cancellation. Already removed or never existed for this cancellation context."
                )
                return

            # Collect SL order if it exists and is not excluded
            if (
                position.current_sl_order_id
                and position.current_sl_order_id != exclude_order_id
            ):
                orders_to_cancel_details.append(
                    (
                        position.current_sl_order_id,
                        position.current_sl_client_order_id,
                        position.is_sl_algo_order,
                    )
                )
                # Clear from position object to prevent re-cancellation attempts
                position.current_sl_order_id = None
                position.current_sl_client_order_id = None
                position.is_sl_algo_order = False
                position.sl_placement_initiated = False

            # Collect PENDING partial TP orders that are not excluded
            new_ptp_list_after_cancel = []
            for ptp in position.partial_tp_orders:
                if (
                    ptp.status == "PENDING"
                    and ptp.order_id
                    and ptp.order_id != exclude_order_id
                ):
                    orders_to_cancel_details.append(
                        (ptp.order_id, ptp.client_order_id, False)
                    )  # TP orders are not Algo orders
                    ptp.status = "CANCELLED"  # Mark as cancelled in the position object
                new_ptp_list_after_cancel.append(ptp)
            position.partial_tp_orders = new_ptp_list_after_cancel

        if not orders_to_cancel_details:
            logger.debug(
                f"{log_prefix} No active exit orders matching criteria to cancel for symbol {symbol}."
            )
            return

        executor = await self._get_executor_for_symbol(symbol, market_type=market_type)
        if not executor:
            logger.warning(
                f"{log_prefix} Could not determine executor for {symbol}. Cannot cancel orders."
            )
            return

        logger.info(
            f"{log_prefix} Attempting to cancel {len(orders_to_cancel_details)} exit orders for {symbol}..."
        )
        cancel_tasks = [
            executor.cancel_order(
                symbol=symbol, orderId=oid, origClientOrderId=cid, is_algo_order=is_algo
            )
            for oid, cid, is_algo in orders_to_cancel_details
            if oid
        ]

        if cancel_tasks:
            results = await asyncio.gather(*cancel_tasks, return_exceptions=True)
            for i, res in enumerate(results):
                oid_res, cid_res, _ = orders_to_cancel_details[i]
                if isinstance(res, Exception):
                    logger.error(
                        f"{log_prefix} Exception cancelling order for {symbol} (ID={oid_res}, ClientID={cid_res}): {res}"
                    )
                elif isinstance(res, dict) and res.get("error"):
                    logger.error(
                        f"{log_prefix} Failed to cancel order for {symbol} (ID={oid_res}): {res.get('msg')}"
                    )
                else:
                    logger.info(
                        f"{log_prefix} Order for {symbol} (ID={oid_res}) cancelled successfully or was not found."
                    )
            logger.info(f"{log_prefix} Finished cancelling exit orders for {symbol}.")

    async def _adjust_position_to_partial_entry(
        self, symbol: str, filled_qty: float, market_type: Optional[str] = None
    ):
        """Adjusts the position and exit orders after a partial entry (when the entry order is CANCELED/REJECTED with partial execution)."""
        log_prefix = f"[_AdjustPartialEntry:{symbol}]"
        logger.warning(
            f"{log_prefix} Adjusting position for partial entry. Filled Qty: {filled_qty:.8f}"
        )

        old_sl_id_to_cancel: Optional[int] = None
        old_sl_cid_to_cancel: Optional[str] = None
        old_ptp_orders_to_cancel: List[Tuple[Optional[int], Optional[str]]] = []
        position_to_reschedule: Optional[LivePosition] = (
            None  # This will be the modified position object
        )

        # Stage 1: Collecting old order IDs and updating position information under lock
        symbol_lock_adj_partial = self._get_lock_for_position(symbol, market_type)
        async with symbol_lock_adj_partial:
            position = self._active_position_get(symbol, market_type)
            if not position or position.status != "OPEN":
                logger.error(
                    f"{log_prefix} Position not found or not OPEN. Cannot adjust."
                )
                return

            # First, collect IDs of old orders for cancellation
            old_sl_id_to_cancel = position.current_sl_order_id
            old_sl_cid_to_cancel = position.current_sl_client_order_id
            old_sl_is_algo_order = (
                position.is_sl_algo_order
            )  # Remembering the order type for cancellation
            for ptp in position.partial_tp_orders:
                if ptp.status == "PENDING" and ptp.order_id:  # If the order was placed
                    old_ptp_orders_to_cancel.append((ptp.order_id, ptp.client_order_id))

            # Now updating the position
            initial_qty_before = position.initial_quantity
            if filled_qty >= initial_qty_before * (1 - 1e-9):  # With tolerance
                logger.warning(
                    f"{log_prefix} Filled qty {filled_qty} >= initial {initial_qty_before}. No significant quantity adjustment needed, but will re-check exit orders."
                )
                # In this case, we might still want to recreate orders if, for example, one of them was canceled manually
                # But the main logic here is for the case when filled_qty < initial_qty_before

            position.initial_quantity = filled_qty
            position.remaining_quantity = filled_qty
            logger.info(
                f"{log_prefix} Position quantities updated: Initial={filled_qty:.8f}, Remaining={filled_qty:.8f}"
            )

            # Reset current exit order IDs in the position object, as they will be repositioned
            position.current_sl_order_id = None
            position.current_sl_client_order_id = None
            position.sl_placement_initiated = False
            logger.debug(
                f"{log_prefix} Reset position.sl_placement_initiated to False."
            )

            # Recalculate quantities for partial TP based on the new filled_qty
            position.ptp_placement_initiated_flags.clear()
            logger.debug(
                f"{log_prefix} Cleared position.ptp_placement_initiated_flags."
            )
            position_market_type = self._market_type_for_position(position)
            lot_params = await self._get_market_info(
                symbol, "lot_params", market_type=position_market_type
            )
            min_notional = await self._get_market_info(
                symbol, "min_notional", market_type=position_market_type
            )

            new_partial_tp_list = []
            for ptp_config in (
                position.partial_tp_orders
            ):  # Iterate through the ORIGINAL TP fractions (orig_fraction)
                new_ptp_qty_raw = (
                    filled_qty * ptp_config.orig_fraction
                )  # orig_fraction of the initial configuration
                new_ptp_qty = self.rm._adjust_and_round_quantity(
                    new_ptp_qty_raw,
                    symbol,
                    ptp_config.target_price,
                    lot_params,
                    min_notional,
                )

                if new_ptp_qty is not None and new_ptp_qty > 0:
                    # Create a new PartialTpOrderInfo object for the new list
                    # Status PENDING, order_id and client_order_id will be None, as the order will need to be replaced
                    new_partial_tp_list.append(
                        PartialTpOrderInfo(
                            target_price=ptp_config.target_price,
                            orig_fraction=ptp_config.orig_fraction,  # Saving the original share
                            quantity=new_ptp_qty,  # New, adjusted quantity
                            status="PENDING",
                        )
                    )
                    logger.debug(
                        f"{log_prefix} Adjusted partial TP target {ptp_config.target_price:.4f}, new qty {new_ptp_qty:.8f}"
                    )
                else:
                    logger.warning(
                        f"{log_prefix} Partial TP target {ptp_config.target_price:.4f} skipped: new qty {new_ptp_qty_raw:.8f} -> {new_ptp_qty} is invalid."
                    )

            position.partial_tp_orders = (
                new_partial_tp_list  # Replacing the old list with a new one
            )
            position_to_reschedule = (
                position  # Save the reference to the modified position object
            )

        # Stage 2: Canceling old orders (outside of lock)
        cancel_tasks_old_coroutines = []
        executor_for_cancel = (
            self._executor_for_market_type(
                self._market_type_for_position(position_to_reschedule)
                if position_to_reschedule
                else None,
                mode=position_to_reschedule.mode if position_to_reschedule else "live",
            )
            if position_to_reschedule
            else self.executors.get("live")
        )
        if not executor_for_cancel:
            logger.error(
                f"{log_prefix} Executor for rescheduled position not found. Cannot cancel old exit orders."
            )
            return
        if old_sl_id_to_cancel:  # Ensure it's not None
            logger.info(
                f"{log_prefix} Scheduling cancellation of old SL: ID={old_sl_id_to_cancel}, ClientID={old_sl_cid_to_cancel}, IsAlgo={old_sl_is_algo_order}"
            )
            cancel_tasks_old_coroutines.append(
                executor_for_cancel.cancel_order(
                    symbol=symbol,
                    orderId=old_sl_id_to_cancel,
                    origClientOrderId=old_sl_cid_to_cancel,
                    is_algo_order=old_sl_is_algo_order,
                )
            )
        for oid, ocid in old_ptp_orders_to_cancel:
            if oid:  # Ensure orderId is not None
                logger.info(
                    f"{log_prefix} Scheduling cancellation of old PTP: ID={oid}, ClientID={ocid}"
                )
                cancel_tasks_old_coroutines.append(
                    executor_for_cancel.cancel_order(
                        symbol=symbol, orderId=oid, origClientOrderId=ocid
                    )
                )

        if cancel_tasks_old_coroutines:
            logger.info(
                f"{log_prefix} Attempting to cancel {len(cancel_tasks_old_coroutines)} old exit orders due to partial entry adjustment..."
            )
            # Create tasks and then gather them
            actual_tasks_for_gather = [
                self.loop.create_task(coro) for coro in cancel_tasks_old_coroutines
            ]
            results = await asyncio.gather(
                *actual_tasks_for_gather, return_exceptions=True
            )

            for i, res in enumerate(results):
                # Log result of each cancellation
                # Attempt to get orderId/clientOrderId from the coroutine arguments if possible (complex)
                # For now, just log generic success/failure based on result
                if isinstance(res, Exception):
                    logger.error(
                        f"{log_prefix} Error cancelling an old exit order (task {i + 1}/{len(actual_tasks_for_gather)}): {res}"
                    )
                elif isinstance(res, dict) and res.get("error"):
                    logger.error(
                        f"{log_prefix} Failed to cancel an old exit order (task {i + 1}/{len(actual_tasks_for_gather)}): API Error Msg: {res.get('msg')}"
                    )
                else:
                    logger.info(
                        f"{log_prefix} Successfully cancelled or confirmed cancellation for an old exit order (task {i + 1}/{len(actual_tasks_for_gather)}). Response: {res}"
                    )
            logger.info(f"{log_prefix} Finished cancelling old exit orders.")
        else:
            logger.info(f"{log_prefix} No old exit orders found to cancel.")

        # Stage 3: Recreating tasks for placing new exit orders (outside the lock)
        if position_to_reschedule:
            # _reschedule_exit_orders will take the lock itself to place new orders
            await self._reschedule_exit_orders(
                position_to_reschedule
            )  # Call the new method

    async def _reschedule_exit_orders(self, position_obj: LivePosition):
        """
        Places new SL and TP orders for the position.
        It is assumed that position_obj is already updated (e.g., quantity, SL price, TP definitions).
        This function is called after position adjustment due to partial entry.
        """
        log_prefix = f"[_RescheduleExits:{position_obj.symbol}:{position_obj.entry_client_order_id[:8]}]"
        logger.info(
            f"{log_prefix} Rescheduling exit orders. PosStatus: {position_obj.status}, RemQty: {position_obj.remaining_quantity}"
        )

        if position_obj.status != "OPEN" or position_obj.remaining_quantity <= 0:
            logger.warning(
                f"{log_prefix} Position not OPEN or zero/negative remaining quantity. Skipping rescheduling."
            )
            return

        # Placing Stop-Loss
        # _place_stop_loss will check itself if placement is needed (sl_placement_initiated, current_sl_order_id)
        # and will take a lock to update the position object.
        self.loop.create_task(
            self._place_stop_loss(position_obj),
            name=f"Rescheduled_PlaceSL_{position_obj.symbol}",
        )
        logger.info(f"{log_prefix} Task created for _place_stop_loss.")

        # Placing Take-Profit orders
        # partial_tp_orders in position_obj must already be recalculated for the new initial_quantity
        # and have a PENDING status (or similar, indicating the need for placement).

        # First, get current market data for rounding and checking TP quantities
        position_market_type = self._market_type_for_position(position_obj)
        lot_params = await self._get_market_info(
            position_obj.symbol, "lot_params", market_type=position_market_type
        )
        min_notional = await self._get_market_info(
            position_obj.symbol, "min_notional", market_type=position_market_type
        )

        if position_obj.partial_tp_orders:
            logger.info(
                f"{log_prefix} Position has {len(position_obj.partial_tp_orders)} PTP targets to evaluate for rescheduling."
            )
            for i, ptp_info in enumerate(
                list(position_obj.partial_tp_orders)
            ):  # list() for a copy if we are going to modify it
                # Condition: the order does not yet have an ID and its placement has not been initiated previously
                # The 'PENDING' status (set in _adjust_position_to_partial_entry) signals the need for placement.
                if ptp_info.status == "PENDING" and ptp_info.order_id is None:
                    # The ptp_info.quantity should already be adjusted in _adjust_position_to_partial_entry
                    # Check it again for validity just in case.
                    final_ptp_qty = self.rm._adjust_and_round_quantity(
                        ptp_info.quantity,
                        position_obj.symbol,
                        ptp_info.target_price,
                        lot_params,
                        min_notional,
                    )
                    if final_ptp_qty and final_ptp_qty > 0:
                        logger.info(
                            f"{log_prefix} Scheduling PTP #{i} (Target: {ptp_info.target_price}, AdjQty: {final_ptp_qty})"
                        )
                        self.loop.create_task(
                            self._place_partial_tp(
                                position_obj,
                                ptp_info.target_price,
                                final_ptp_qty,  # Using the double-checked quantity
                                ptp_info.orig_fraction,
                                i,
                            ),
                            name=f"Rescheduled_PlacePTP_{position_obj.symbol}_idx{i}",
                        )
                    else:
                        logger.warning(
                            f"{log_prefix} PTP #{i} (Target: {ptp_info.target_price}) skipped during reschedule: invalid quantity {final_ptp_qty} (raw was {ptp_info.quantity})."
                        )
                else:
                    logger.debug(
                        f"{log_prefix} PTP #{i} (Target: {ptp_info.target_price}) skipped: Status={ptp_info.status}, OrderID={ptp_info.order_id}."
                    )

        # If there are no partial TPs, but there is initial_take_profit (general TP)
        elif (
            position_obj.initial_take_profit is not None
            and position_obj.remaining_quantity > 0
        ):
            logger.info(
                f"{log_prefix} No partial TPs, checking for final TP at {position_obj.initial_take_profit}."
            )
            final_tp_price = position_obj.initial_take_profit
            qty_for_final_tp = self.rm._adjust_and_round_quantity(
                position_obj.remaining_quantity,  # All remaining volume
                position_obj.symbol,
                final_tp_price,
                lot_params,
                min_notional,
            )
            if qty_for_final_tp and qty_for_final_tp > 0:
                logger.info(
                    f"{log_prefix} Scheduling final TP (Target: {final_tp_price}, Qty: {qty_for_final_tp})"
                )
                self.loop.create_task(
                    self._place_partial_tp(
                        position_obj,
                        final_tp_price,
                        qty_for_final_tp,
                        1.0,  # 100% fraction for final TP
                        -1,  # Special index for the final TP
                    ),
                    name=f"Rescheduled_PlaceFinalTP_{position_obj.symbol}",
                )
            else:
                logger.warning(
                    f"{log_prefix} Final TP skipped: invalid quantity {qty_for_final_tp} (raw was {position_obj.remaining_quantity})."
                )
        else:
            logger.info(
                f"{log_prefix} No partial TPs and no final TP defined for rescheduling."
            )

    async def _calculate_avg_fill_price(
        self, fills: List[Dict[str, Any]]
    ) -> Optional[float]:
        """Calculates the average execution price based on the list of trades (fills)."""
        if not fills:
            return None
        total_cost = Decimal("0")
        total_qty = Decimal("0")
        log_prefix = "[CalcAvgFillPrice]"
        # logger.debug(f"{log_prefix} Calculating avg price from {len(fills)} fills: {fills}")
        try:
            for i, fill in enumerate(fills):
                price_str = fill.get("price")
                qty_str = fill.get("qty")
                if price_str is None or qty_str is None:
                    continue
                try:
                    price = Decimal(price_str)
                    qty = Decimal(qty_str)
                    if price > 0 and qty > 0:
                        total_cost += price * qty
                        total_qty += qty
                except (InvalidOperation, TypeError):
                    continue
            if total_qty > 0:
                return float(total_cost / total_qty)
            else:
                return None
        except Exception as e:
            logger.error(f"{log_prefix} Error: {e}. Fills: {fills}", exc_info=True)
            return None

    def _append_execution_event(
        self,
        position: LivePosition,
        *,
        event_type: str,
        execution_type: str,
        price: Optional[float],
        quantity: Optional[float],
        order_id: Optional[int] = None,
        client_order_id: Optional[str] = None,
        commission: Optional[float] = None,
        commission_asset: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        try:
            price_value = float(price) if price is not None else 0.0
            qty_value = float(quantity) if quantity is not None else 0.0
        except (TypeError, ValueError):
            return

        if price_value <= 0 or qty_value <= 0:
            return

        event = {
            "timestamp": (timestamp or datetime.now(timezone.utc)).isoformat(),
            "price": price_value,
            "quantity": qty_value,
            "type": event_type,
            "execution_type": execution_type,
            "order_id": order_id,
            "client_order_id": client_order_id,
            "commission": commission,
            "commission_asset": commission_asset,
        }

        for existing in position.execution_events:
            if (
                existing.get("type") == event["type"]
                and existing.get("execution_type") == event["execution_type"]
                and existing.get("order_id") == event["order_id"]
                and existing.get("client_order_id") == event["client_order_id"]
                and abs(float(existing.get("price") or 0) - price_value) < 1e-12
                and abs(float(existing.get("quantity") or 0) - qty_value) < 1e-12
            ):
                return

        position.execution_events.append(event)

    def _append_fill_execution_events(
        self,
        position: LivePosition,
        *,
        event_type: str,
        execution_type: str,
        fills: List[Dict[str, Any]],
        fallback_price: Optional[float],
        fallback_quantity: Optional[float],
        order_id: Optional[int],
        client_order_id: Optional[str],
    ) -> None:
        appended = False
        for fill in fills or []:
            try:
                price = float(fill.get("price") or 0)
                quantity = float(fill.get("qty") or fill.get("quantity") or 0)
                commission = float(fill.get("commission") or 0)
            except (TypeError, ValueError):
                continue

            if price > 0 and quantity > 0:
                self._append_execution_event(
                    position,
                    event_type=event_type,
                    execution_type=execution_type,
                    price=price,
                    quantity=quantity,
                    order_id=order_id,
                    client_order_id=client_order_id,
                    commission=commission,
                    commission_asset=fill.get("commissionAsset")
                    or fill.get("commission_asset"),
                )
                appended = True

        if not appended:
            self._append_execution_event(
                position,
                event_type=event_type,
                execution_type=execution_type,
                price=fallback_price,
                quantity=fallback_quantity,
                order_id=order_id,
                client_order_id=client_order_id,
            )

    async def _handle_order_update(self, data: Dict[str, Any]):
        raw_event_type = data.get("e")
        raw_symbol = data.get("s")  # Can be None for ACCOUNT_UPDATE
        raw_client_order_id = data.get(
            "c"
        )  # Binance Futures 'c', Spot 'C' (will be processed below)
        raw_order_id = data.get("i")  # Binance 'i'
        raw_order_status = data.get("X")  # Binance 'X'

        logger.info(
            f"[RawOrderUpdateReceive] Event: {raw_event_type}, Symbol: {raw_symbol}, CliOrdID: {raw_client_order_id}, OrdID: {raw_order_id}, Status: {raw_order_status}"
        )

        event_type_raw = data.get("e")

        if event_type_raw == "outboundAccountPosition":  # Spot balance/position update
            logger.debug(
                "[OrderUpdate:BalanceEvent] Received outboundAccountPosition. Scheduling balance update."
            )
            self.loop.create_task(
                self.rm.update_balance(),
                name="RMUpdateBalance_From_outboundAccountPosition",
            )
            return
        if event_type_raw == "ACCOUNT_UPDATE":  # Futures balance/position update
            logger.debug(
                f"[OrderUpdate:BalanceEvent] Received ACCOUNT_UPDATE (futures). Data: {data.get('a')}. Scheduling balance update."
            )

            async def update_balance_and_save_rm_state():
                if await self.rm.update_balance():
                    # If the balance is successfully updated, save/publish the state
                    await self.rm.save_state()

            self.loop.create_task(
                update_balance_and_save_rm_state(),
                name="RMUpdateAndSave_From_AcctUpdate",
            )
            return
        if (
            event_type_raw == "balanceUpdate"
        ):  # Spot balance change (deposit, withdrawal, fee)
            logger.debug(
                f"[OrderUpdate:BalanceEvent] Received balanceUpdate: Asset={data.get('a')}, Delta={data.get('d')}. Scheduling balance update."
            )
            self.loop.create_task(
                self.rm.update_balance(), name="RMUpdateBalance_From_balanceUpdate"
            )
            return

        # Focus only on events related to orders
        if (
            event_type_raw != "executionReport"
            and event_type_raw != "ORDER_TRADE_UPDATE"
        ):
            logger.debug(
                f"[OrderUpdate:SkipEvent] Skipping event type: {event_type_raw}"
            )
            return

        # Parsing the main order object 'o' (for futures) or the root object (for spot)
        order_data_payload: Dict[str, Any]
        is_futures_event = False
        if event_type_raw == "ORDER_TRADE_UPDATE":  # Futures
            order_data_payload = data.get("o", {})
            is_futures_event = True
            if not order_data_payload:
                logger.error(
                    f"[OrderUpdate:FuturesParseFail] 'o' field missing in ORDER_TRADE_UPDATE. Data: {data}"
                )
                return
        elif event_type_raw == "executionReport":  # Spot
            order_data_payload = data
        else:  # Should not happen due to the check above, but for completeness
            logger.error(
                f"[OrderUpdate:UnknownEvent] Unexpected event type {event_type_raw} for order processing. Data: {data}"
            )
            return
        event_market_type = "futures_usdtm" if is_futures_event else "spot"

        # Extraction and type casting for key order fields
        try:
            symbol = order_data_payload.get("s")
            order_id_raw = order_data_payload.get("i")
            if order_id_raw is None or order_id_raw == "":
                order_id = -1
            else:
                try:
                    order_id = str(int(order_id_raw))
                except (ValueError, TypeError):
                    order_id = str(order_id_raw)

            # Client Order ID: 'c' for futures, 'C' (origClientOrderId) or 'c' (newClientOrderId) for spot
            client_order_id = order_data_payload.get("c")
            if (
                not client_order_id and event_type_raw == "executionReport"
            ):  # Attempt for spot
                client_order_id = order_data_payload.get(
                    "C"
                )  # Original client order ID
                if not client_order_id:
                    client_order_id = order_data_payload.get(
                        "newClientOrderId"
                    )  # If it was a cancel-replace

            execution_type = order_data_payload.get("x", "").upper()  # Execution Type
            order_status = order_data_payload.get("X", "").upper()  # Order Status
            side = order_data_payload.get("S", "").upper()  # Side
            order_type_str = order_data_payload.get(
                "ot" if is_futures_event else "o", ""
            ).upper()  # Order Type ('o' for spot, 'ot' for futures)

            quantity_ordered_str = order_data_payload.get("q", "0")  # Original Quantity
            quantity_filled_cumulative_str = order_data_payload.get(
                "z", "0"
            )  # Cumulative Filled Quantity

            # Average execution price for the order ('ap' for futures, for spot it could be 'L' or 'p' depending on the situation)
            avg_price_filled_str = order_data_payload.get(
                "ap", "0.0"
            )  # Futures average price
            if not avg_price_filled_str or float(avg_price_filled_str) == 0.0:
                avg_price_filled_str = order_data_payload.get(
                    "L", "0.0"
                )  # Last filled price (can be for spot or futures if ap=0)
                # If this is a FILLED MARKET order on spot, the price may be in 'p'
                if (
                    (not avg_price_filled_str or float(avg_price_filled_str) == 0.0)
                    and event_type_raw == "executionReport"
                    and order_status == "FILLED"
                    and order_type_str == "MARKET"
                ):
                    avg_price_filled_str = order_data_payload.get("p", "0.0")
            avg_price_filled = (
                float(avg_price_filled_str) if avg_price_filled_str else 0.0
            )

            last_filled_qty_str = order_data_payload.get(
                "l", "0"
            )  # Last Filled Quantity
            last_filled_price_str = order_data_payload.get(
                "L", "0"
            )  # Last Filled Price
            commission_str = order_data_payload.get("n", "0")  # Commission Amount
            commission_asset = order_data_payload.get("N")  # Commission Asset

            # Realized PnL from the exchange (Binance Futures, 'rp' field).
            # Important: rp=0.0 can be a valid value, so the presence of the field is tracked separately.
            exchange_pnl_available = bool(
                is_futures_event and ("rp" in order_data_payload)
            )
            realized_pnl_from_exchange = 0.0
            if exchange_pnl_available:
                realized_pnl_str = order_data_payload.get("rp")
                realized_pnl_from_exchange = (
                    float(realized_pnl_str)
                    if realized_pnl_str not in (None, "")
                    else 0.0
                )

            # Casting to required types
            quantity_ordered = float(quantity_ordered_str)
            quantity_filled_cumulative = float(quantity_filled_cumulative_str)
            last_filled_qty = float(last_filled_qty_str)
            last_filled_price = float(last_filled_price_str)
            commission = float(commission_str)

            # Forming the 'fills' list for _handle_entry_fill
            # Important: These are details of the LAST execution, not all of them. For full history, a different approach is needed.
            fills_data_for_handler: List[Dict] = []
            if execution_type == "TRADE":  # If this is a trade event
                fills_data_for_handler = [
                    {
                        "price": str(last_filled_price),  # L
                        "qty": str(last_filled_qty),  # l
                        "commission": str(commission),  # n
                        "commissionAsset": commission_asset,  # N
                        "tradeId": order_data_payload.get(
                            "t", -1
                        ),  # t - trade ID (in both event types)
                    }
                ]

            # Checking for the presence of all critical fields
            if not all(
                [
                    symbol,
                    client_order_id,
                    order_id != -1,
                    execution_type,
                    order_status,
                    side,
                    order_type_str,
                ]
            ):
                logger.warning(
                    f"[OrderUpdate:ParsingFail] Missing core fields. EventType: {event_type_raw}, Payload: {order_data_payload}, OriginalData: {data}"
                )
                return
        except (ValueError, TypeError, KeyError) as e:
            logger.error(
                f"[OrderUpdate:ParsingError] Error parsing fields: {e}. EventType: {event_type_raw}, Payload: {order_data_payload}, OriginalData: {data}",
                exc_info=True,
            )
            return

        # Generating prefix for logs
        log_cid_short = client_order_id[:10] if client_order_id else str(order_id)
        log_prefix = f"[OrderUpdate:{symbol}:{log_cid_short}:{order_type_str}:{side}]"

        logger.info(
            f"{log_prefix} Event: ExecType='{execution_type}', OrderStatus='{order_status}', "
            f"QtyFill='{quantity_filled_cumulative:.8f}/{quantity_ordered:.8f}', LastFill='{last_filled_qty:.8f}@{last_filled_price:.8f}', "
            f"AvgPrice='{avg_price_filled:.8f}', RealizedPnL_rp='{realized_pnl_from_exchange:.6f}', "
            f"ExchangePnLAvailable={exchange_pnl_available}, "
            f"Comm='{commission}{commission_asset if commission_asset else ''}' (OrderID: {order_id})"
        )
        self.trade_logger.log_event(
            event_type="ORDER_UPDATE_RAW", data=data
        )  # Logging raw event

        # Main update processing logic
        symbol_lock = self._get_lock_for_position(symbol, event_market_type)
        async with symbol_lock:
            position = self._active_position_get(symbol, event_market_type)

            if not position:
                logger.debug(
                    f"{log_prefix} No active position found for symbol {symbol}. Ignoring update."
                )
                return

            initial_pos_status_log = position.status  # To track position status changes
            logger.debug(
                f"{log_prefix} Found active position. Initial PosStatus='{initial_pos_status_log}', OrderID being processed: {order_id}."
            )

            # 1. Processing the ENTRY order
            is_entry_order_event = (
                position.entry_order_id is not None
                and str(position.entry_order_id) == str(order_id)
            ) or (
                position.entry_client_order_id == client_order_id
                and position.entry_client_order_id is not None
            )

            if is_entry_order_event:
                logger.info(
                    f"{log_prefix} Matches ENTRY order (PosStoredOrderID: {position.entry_order_id}, PosStoredCliID: {position.entry_client_order_id})."
                )

                if position.status in ["CLOSING", "CLOSED"]:
                    logger.warning(
                        f"{log_prefix} Position already '{position.status}'. Ignoring late update for entry order {order_id}."
                    )
                    if position.status != initial_pos_status_log:
                        logger.info(
                            f"{log_prefix} Position status changed (final check): '{initial_pos_status_log}' -> '{position.status}'."
                        )
                    return

                # Determining if this update is final for the entry order
                # Final statuses: FILLED, CANCELED, REJECTED, EXPIRED
                is_final_status_for_entry_order = order_status in [
                    "FILLED",
                    "CANCELED",
                    "REJECTED",
                    "EXPIRED",
                ]

                logger.info(
                    f"{log_prefix} Processing entry order. OrderStatus from event: '{order_status}', ExecutionType: '{execution_type}', IsFinalForLogic: {is_final_status_for_entry_order}, CumQty: {quantity_filled_cumulative:.8f}"
                )

                # Log ORDER_UPDATE if it's a fill event or a final status update for the entry order
                if (
                    order_status == "FILLED"
                    or (
                        is_final_status_for_entry_order
                        and execution_type != "TRADE"
                        and execution_type != "CANCELED"
                    )
                ):  # Avoid double logging for simple CANCELED if _handle_entry_fill also logs it
                    log_data_for_order_update = {
                        "symbol": symbol,
                        "orderId": order_id,
                        "clientOrderId": client_order_id,
                        "status": order_status,  # The final or current relevant status
                        "side": side,
                        "type": order_type_str,
                        "executedQty": quantity_filled_cumulative,
                        "avgPrice": avg_price_filled,
                        "lastFilledQty": last_filled_qty,
                        "lastFilledPrice": last_filled_price,
                        "commission": commission,
                        "commissionAsset": commission_asset,
                        "executionType": execution_type,  # Include execution type
                    }
                    logger.debug(
                        f"{log_prefix} Logging 'ORDER_UPDATE' event for trade_logger. Data: {log_data_for_order_update}"
                    )
                    self.trade_logger.log_event(
                        event_type="ORDER_UPDATE", data=log_data_for_order_update
                    )

                # Add specific handling for CANCELED with partial fill
                if order_status == "CANCELED" and quantity_filled_cumulative > 0:
                    logger.info(
                        f"{log_prefix} Entry order CANCELED with partial fill. Adjusting position."
                    )
                    self.loop.create_task(
                        self._adjust_position_to_partial_entry(
                            symbol,
                            quantity_filled_cumulative,
                            market_type=event_market_type,
                        ),
                        name=f"AdjustPartialEntry_{symbol}",
                    )
                    return  # We handled it, so we can exit.

                # _handle_entry_fill is called if:
                # 1. This is a trade event (execution_type == "TRADE") - to process each partial or full execution.
                # 2. This is the final order status (even if there is no trade, e.g., CANCELED without executions) - for finalization.
                if execution_type == "TRADE" or is_final_status_for_entry_order:
                    self.loop.create_task(
                        self._handle_entry_fill(
                            symbol=symbol,
                            order_id=order_id,
                            client_order_id=client_order_id,
                            avg_fill_price=avg_price_filled,  # This is the overall average price for the order
                            cumulative_filled_qty=quantity_filled_cumulative,  # Total executed quantity
                            fills=fills_data_for_handler,  # Details of the LAST trade
                            is_final_fill_status=is_final_status_for_entry_order,  # Passing the flag
                            market_type=event_market_type,
                        ),
                        name=f"HandleEntryUpdate_{symbol}_{order_id}_{execution_type}_{order_status}",
                    )

                # If this is NOT a final status and NOT a TRADE event (e.g., just NEW or PENDING_CANCEL),
                # then we can only update the order status in the position object if it is not yet in a final state.
                elif not is_final_status_for_entry_order:
                    if position.entry_order_status not in [
                        "FILLED",
                        "CANCELED",
                        "REJECTED",
                        "EXPIRED",
                        "CANCELED_WITH_PARTIAL_FILL",
                        "CANCELED_NO_FILL",
                    ]:  # Custom statuses
                        position.entry_order_status = (
                            order_status  # Updating to current, non-final status
                        )
                        logger.debug(
                            f"{log_prefix} Entry order status in position object updated to (non-final) '{order_status}'."
                        )

                if (
                    position.status != initial_pos_status_log
                ):  # Logging POSITION status change
                    logger.info(
                        f"{log_prefix} Position status changed during ENTRY update: '{initial_pos_status_log}' -> '{position.status}'."
                    )
                logger.debug(
                    f"{log_prefix} Finished processing ENTRY order update for OrderID: {order_id}."
                )
                return  # Exit, as the event has been processed for the entry order

            # 2. Stop-Loss order processing
            is_sl_order_event = (
                position.current_sl_order_id is not None
                and str(position.current_sl_order_id) == str(order_id)
            ) or (
                position.current_sl_client_order_id == client_order_id
                and position.current_sl_client_order_id is not None
            )

            if is_sl_order_event:
                logger.info(
                    f"{log_prefix} Matches SL order (PosSLOrderID: {position.current_sl_order_id}, PosSLCliID: {position.current_sl_client_order_id}). Event OrderID: {order_id}"
                )

                if order_status == "FILLED":
                    if position.status == "OPEN":
                        logger.info(f"{log_prefix} SL order FILLED. Closing position.")
                        # For STOP_MARKET order with FILLED status:
                        # 'ap' (avg_price_filled) is the weighted average price across ALL fills of the order (best choice for exit price)
                        # 'L' (last_filled_price) — price of only the LAST fill (not accurate if the order was executed in parts)
                        exit_price_sl_fill = (
                            avg_price_filled
                            if avg_price_filled > 0
                            else last_filled_price
                        )  # Priority AP (average across all fills), then L
                        if (
                            exit_price_sl_fill <= 0
                        ):  # If both AP and L = 0, take the stop price from the order
                            exit_price_sl_fill = (
                                position.current_sl_price
                            )  # Price at which the SL was placed

                        # Accumulate rp from this final fill event into accumulated_realized_pnl
                        # (intermediate PARTIALLY_FILLED have already been accumulated below)
                        # Pass 0.0 to _handle_final_exit, as we add it manually, similar to partial TP
                        if realized_pnl_from_exchange != 0.0:
                            position.accumulated_realized_pnl_from_exchange += (
                                realized_pnl_from_exchange
                            )
                            logger.info(
                                f"{log_prefix} SL FILLED: Added final rp={realized_pnl_from_exchange:.4f} to accumulated. Total accumulated={position.accumulated_realized_pnl_from_exchange:.4f}"
                            )

                        self.loop.create_task(
                            self._handle_final_exit(
                                symbol,
                                "STOP_LOSS_BE"
                                if position.is_stop_at_be
                                else "STOP_LOSS",
                                exit_price_sl_fill,
                                commission,
                                commission_asset,
                                order_id,
                                client_order_id,
                                realized_pnl_from_exchange=0.0,  # Already added to accumulated above
                                exchange_pnl_available=exchange_pnl_available,
                                market_type=event_market_type,
                            ),
                            name=f"HandleExit_SLFill_{symbol}_{order_id}",
                        )
                    else:
                        logger.warning(
                            f"{log_prefix} SL order FILLED, but PosStatus is '{position.status}'. Likely already handled or race condition."
                        )
                        position.current_sl_order_id = None
                        position.current_sl_client_order_id = None

                elif order_status == "PARTIALLY_FILLED":
                    # SL order executed partially — accumulating rp for accurate final PnL
                    if position.status == "OPEN":
                        if realized_pnl_from_exchange != 0.0:
                            position.accumulated_realized_pnl_from_exchange += (
                                realized_pnl_from_exchange
                            )
                            logger.info(
                                f"{log_prefix} SL PARTIALLY_FILLED: Accumulated rp={realized_pnl_from_exchange:.4f}. "
                                f"Total accumulated={position.accumulated_realized_pnl_from_exchange:.4f}. "
                                f"LastFillQty={last_filled_qty:.8f}@{last_filled_price:.8f}"
                            )
                        else:
                            logger.info(
                                f"{log_prefix} SL PARTIALLY_FILLED: rp=0, nothing to accumulate. "
                                f"LastFillQty={last_filled_qty:.8f}@{last_filled_price:.8f}"
                            )
                    else:
                        logger.warning(
                            f"{log_prefix} SL PARTIALLY_FILLED, but PosStatus is '{position.status}'. Ignoring."
                        )

                elif order_status in ["CANCELED", "REJECTED", "EXPIRED"]:
                    logger.warning(f"{log_prefix} SL order is {order_status}.")
                    if position.status == "OPEN":  # Only if the position is still OPEN
                        logger.critical(
                            f"{log_prefix} CRITICAL: SL order for OPEN position {client_order_id} is {order_status}! Position UNPROTECTED. Attempting to replace SL immediately."
                        )
                        position.current_sl_order_id = None
                        position.current_sl_client_order_id = None
                        position.sl_placement_initiated = (
                            False  # Reset the flag so that _place_stop_loss triggers
                        )

                        self.loop.create_task(
                            self._place_stop_loss(position),
                            name=f"ReplaceSL_After_{order_status}_{symbol}_{order_id}",
                        )
                    else:  # Position is no longer OPEN (CLOSING or CLOSED)
                        logger.info(
                            f"{log_prefix} SL order {order_status} (PosStatus: {position.status}). Clearing SL IDs from position object."
                        )
                        position.current_sl_order_id = None
                        position.current_sl_client_order_id = None

                elif order_status == "NEW":  # SL order has just been placed
                    logger.debug(
                        f"{log_prefix} SL order is NEW. Ensuring IDs are set in position object."
                    )
                    if str(position.current_sl_order_id) != str(order_id):
                        position.current_sl_order_id = order_id
                    if position.current_sl_client_order_id != client_order_id:
                        position.current_sl_client_order_id = client_order_id
                else:
                    logger.info(
                        f"{log_prefix} SL order has unhandled status '{order_status}'."
                    )

                if position.status != initial_pos_status_log:
                    logger.info(
                        f"{log_prefix} Position status changed during SL update: '{initial_pos_status_log}' -> '{position.status}'."
                    )
                logger.debug(
                    f"{log_prefix} Finished processing SL order update for OrderID: {order_id}."
                )
                return

            # 3. Partial Take-Profit order processing
            ptp_match_idx: Optional[int] = None
            ptp_info_object: Optional[PartialTpOrderInfo] = None
            for idx, ptp_item in enumerate(position.partial_tp_orders):
                if (
                    ptp_item.order_id is not None
                    and str(ptp_item.order_id) == str(order_id)
                ) or (
                    ptp_item.client_order_id == client_order_id
                    and ptp_item.client_order_id is not None
                ):
                    ptp_match_idx = idx
                    ptp_info_object = ptp_item
                    break

            if ptp_info_object is not None and ptp_match_idx is not None:
                logger.info(
                    f"{log_prefix} Matches PARTIAL TP order #{ptp_match_idx + 1} "
                    f"(Target: {ptp_info_object.target_price:.8f}, Qty: {ptp_info_object.quantity:.8f}, "
                    f"StoredOrderID: {ptp_info_object.order_id}, StoredCliID: {ptp_info_object.client_order_id}). Event OrderID: {order_id}"
                )

                current_status_of_this_ptp_in_pos = ptp_info_object.status

                if order_status == "FILLED":
                    if current_status_of_this_ptp_in_pos == "FILLED":
                        logger.debug(
                            f"{log_prefix} Partial TP #{ptp_match_idx + 1} (ID: {order_id}) already marked FILLED in position object. Skipping redundant processing."
                        )
                    elif position.status != "OPEN":
                        logger.warning(
                            f"{log_prefix} Partial TP #{ptp_match_idx + 1} (ID: {order_id}) FILLED, but PosStatus is '{position.status}'. Ignoring update."
                        )
                    else:  # Position is OPEN and this PTP has not yet been marked as FILLED
                        logger.info(
                            f"{log_prefix} Partial TP #{ptp_match_idx + 1} (ID: {order_id}) detected as FILLED. Calling _handle_partial_tp_fill."
                        )
                        # For LIMIT TP, the execution price is the order price, but it's better to take it from L if available
                        exit_price_ptp_fill = (
                            last_filled_price
                            if last_filled_price > 0
                            else avg_price_filled
                        )
                        if exit_price_ptp_fill <= 0:
                            exit_price_ptp_fill = (
                                ptp_info_object.target_price
                            )  # Fallback to target price

                        self.loop.create_task(
                            self._handle_partial_tp_fill(
                                symbol,
                                ptp_match_idx,
                                exit_price_ptp_fill,
                                commission,
                                commission_asset,
                                realized_pnl_from_exchange=realized_pnl_from_exchange,
                                exchange_pnl_available=exchange_pnl_available,
                                market_type=event_market_type,
                            ),
                            name=f"HandlePartialFill_{symbol}_{ptp_match_idx}_{order_id}",
                        )

                elif order_status in ["CANCELED", "REJECTED", "EXPIRED"]:
                    logger.warning(
                        f"{log_prefix} Partial TP #{ptp_match_idx + 1} (ID: {order_id}) is {order_status}."
                    )
                    if (
                        current_status_of_this_ptp_in_pos != "FILLED"
                    ):  # If it was not executed before cancellation
                        ptp_info_object.status = (
                            "CANCELLED"  # Or EXPIRED, for simplicity CANCELLED
                        )
                        # Keep order_id and client_order_id to avoid accidentally trying to re-place it
                        # If it was cancelled by mistake and the position is still open, different logic is needed for replacement.

                elif order_status == "NEW":  # PTP order has just been placed
                    logger.debug(
                        f"{log_prefix} Partial TP #{ptp_match_idx + 1} (ID: {order_id}) is NEW. Ensuring IDs and status are set in position object."
                    )
                    if str(ptp_info_object.order_id) != str(order_id):
                        ptp_info_object.order_id = order_id
                    if ptp_info_object.client_order_id != client_order_id:
                        ptp_info_object.client_order_id = client_order_id
                    if (
                        current_status_of_this_ptp_in_pos != "FILLED"
                    ):  # Do not overwrite FILLED
                        ptp_info_object.status = "PENDING"  # Or "NEW", for consistency with other "active" ones
                else:
                    logger.info(
                        f"{log_prefix} Partial TP #{ptp_match_idx + 1} (ID: {order_id}) has unhandled status '{order_status}'."
                    )

                if position.status != initial_pos_status_log:
                    logger.info(
                        f"{log_prefix} Position status changed during PTP update: '{initial_pos_status_log}' -> '{position.status}'."
                    )
                logger.debug(
                    f"{log_prefix} Finished processing PTP order update for OrderID: {order_id}."
                )
                return

            # 3.5 Processing the Scaling order (Scale-In / DCA)
            is_scale_in_event = (
                client_order_id is not None and client_order_id.startswith("x-scalein-")
            )
            if is_scale_in_event:
                logger.info(
                    f"{log_prefix} Matches SCALE-IN/DCA order (ClientOrderID: {client_order_id})."
                )
                if hasattr(position, "dca_orders") and position.dca_orders:
                    for dca_item in position.dca_orders:
                        if (
                            dca_item.order_id is not None
                            and str(dca_item.order_id) == str(order_id)
                        ) or (
                            dca_item.client_order_id == client_order_id
                            and dca_item.client_order_id is not None
                        ):
                            dca_item.status = order_status
                            if order_status == "FILLED":
                                dca_item.fill_price = (
                                    avg_price_filled
                                    if avg_price_filled > 0
                                    else last_filled_price
                                )
                            break

                if order_status == "FILLED":
                    fill_price = (
                        avg_price_filled if avg_price_filled > 0 else last_filled_price
                    )
                    self.loop.create_task(
                        self._handle_scale_in_fill(
                            symbol,
                            fill_price,
                            quantity_filled_cumulative,
                            client_order_id,
                            market_type=event_market_type,
                        ),
                        name=f"HandleScaleInFill_{symbol}_{order_id}",
                    )
                return

            # 4. Processing the Forced Close order (created by close_position)
            # Assuming that client_order_id for such orders starts with "x-close-"
            is_forced_close_event = (position.status == "CLOSING") and (
                client_order_id is not None and client_order_id.startswith("x-close-")
            )

            if is_forced_close_event:
                logger.info(
                    f"{log_prefix} Matches FORCED CLOSE order (ClientOrderID: {client_order_id})."
                )
                if order_status == "FILLED":
                    logger.info(f"{log_prefix} Forced CLOSE order FILLED.")
                    # Execution price for MARKET close: ap (weighted average) is preferred over L (last fill)
                    exit_price_fclose_fill = (
                        avg_price_filled if avg_price_filled > 0 else last_filled_price
                    )
                    if exit_price_fclose_fill <= 0 and fills_data_for_handler:
                        avg_from_fills = await self._calculate_avg_fill_price(
                            fills_data_for_handler
                        )
                        if avg_from_fills and avg_from_fills > 0:
                            exit_price_fclose_fill = avg_from_fills
                    if (
                        exit_price_fclose_fill <= 0 and quantity_filled_cumulative > 0
                    ):  # If still 0, but something has been executed
                        logger.error(
                            f"{log_prefix} Cannot determine fill price for forced close {client_order_id}. Using 0, PnL will be incorrect."
                        )
                        exit_price_fclose_fill = 0.0  # Will lead to incorrect PnL

                    # Accumulating rp from the final fill event
                    if realized_pnl_from_exchange != 0.0:
                        position.accumulated_realized_pnl_from_exchange += (
                            realized_pnl_from_exchange
                        )
                        logger.info(
                            f"{log_prefix} ForcedClose FILLED: Added final rp={realized_pnl_from_exchange:.4f} to accumulated. Total={position.accumulated_realized_pnl_from_exchange:.4f}"
                        )

                    reason_fce = (
                        position.exit_reason or "FORCED_CLOSE_FROM_UPDATE"
                    )  # Using the reason from the position
                    self.loop.create_task(
                        self._handle_final_exit(
                            symbol,
                            reason_fce,
                            exit_price_fclose_fill,
                            commission,
                            commission_asset,
                            order_id,
                            client_order_id,
                            realized_pnl_from_exchange=0.0,  # Already added to accumulated above
                            exchange_pnl_available=exchange_pnl_available,
                            market_type=event_market_type,
                        ),
                        name=f"HandleExit_ForcedCloseFill_{symbol}_{order_id}",
                    )

                elif order_status == "PARTIALLY_FILLED":
                    # Forced close order partially filled — accumulating rp
                    if realized_pnl_from_exchange != 0.0:
                        position.accumulated_realized_pnl_from_exchange += (
                            realized_pnl_from_exchange
                        )
                        logger.info(
                            f"{log_prefix} ForcedClose PARTIALLY_FILLED: Accumulated rp={realized_pnl_from_exchange:.4f}. "
                            f"Total={position.accumulated_realized_pnl_from_exchange:.4f}"
                        )

                elif order_status in [
                    "CANCELED",
                    "REJECTED",
                    "EXPIRED",
                ]:  # This is a very bad situation
                    logger.critical(
                        f"{log_prefix} CRITICAL: Forced CLOSE order FAILED ({order_status}) for {client_order_id}! Position may still be open or partially open. Manual intervention likely needed."
                    )
                    # Here you can add logic for a retry of closing or notification
                    self.trade_logger.log_event(
                        event_type="FORCED_CLOSE_ORDER_FAILED_API",
                        data={
                            **order_data_payload,
                            "symbol": symbol,
                            "reason": f"Forced close API order {order_status}",
                        },  # Passing order_data_payload
                    )
                elif order_status == "NEW":
                    logger.debug(f"{log_prefix} Forced CLOSE order is NEW.")
                else:
                    logger.info(
                        f"{log_prefix} Forced CLOSE order has unhandled status '{order_status}'."
                    )

                if position.status != initial_pos_status_log:
                    logger.info(
                        f"{log_prefix} Position status changed during FORCED_CLOSE update: '{initial_pos_status_log}' -> '{position.status}'."
                    )
                logger.debug(
                    f"{log_prefix} Finished processing FORCED_CLOSE order update for OrderID: {order_id}."
                )
                return

            # 5. Detection of external/unknown SL orders (e.g., from Rust bot)
            # If the position is OPEN but we have no SL ID, check if this "unknown" order is a stop-loss.
            if position.status == "OPEN" and position.current_sl_order_id is None:
                is_potential_sl = False

                # Direction check
                if position.direction == SignalDirection.LONG and side == "SELL":
                    is_potential_sl = True
                elif position.direction == SignalDirection.SHORT and side == "BUY":
                    is_potential_sl = True

                # Checking order type
                if is_potential_sl:
                    if order_type_str not in [
                        "STOP_MARKET",
                        "STOP_LOSS",
                        "STOP_LOSS_LIMIT",
                    ]:
                        is_potential_sl = False

                if is_potential_sl:
                    # Extracting stop price
                    # For futures in 'o', this field is 'sp'. We parsed 'o' into order_data_payload
                    stop_price_str = order_data_payload.get("sp")
                    # For spot in executionReport this is 'P' (stopPrice)
                    if not stop_price_str and not is_futures_event:
                        stop_price_str = order_data_payload.get("P")

                    stop_price = float(stop_price_str) if stop_price_str else 0.0

                    if stop_price > 0 and order_status in ["NEW", "PARTIALLY_FILLED"]:
                        logger.info(
                            f"{log_prefix} Found EXTERNAL SL order {order_id} (CliID: {client_order_id}) for unprotected position. Adopting."
                        )

                        position.current_sl_order_id = order_id
                        position.current_sl_client_order_id = client_order_id
                        position.current_sl_price = stop_price

                        # If this is the first stop, it can be considered initial
                        if position.initial_stop_loss is None:
                            position.initial_stop_loss = stop_price

                        # Reset placement flags if they were set
                        position.sl_placement_initiated = False

                        logger.info(
                            f"{log_prefix} Successfully ADOPTED external SL {order_id} at price {stop_price}."
                        )

                        # Can exit since we processed it as SL
                        logger.debug(
                            f"{log_prefix} Finished processing ADOPTED SL order update."
                        )
                        return

            # 6. Unknown/Unexpected order (possibly placed manually)
            if position.status == "OPEN":  # Only if the position is still active
                logger.warning(
                    f"{log_prefix} Update for UNKNOWN/UNEXPECTED order {order_id} (CliID: {client_order_id or 'N/A'}) received while position is OPEN."
                )
                if order_status == "FILLED":
                    logger.warning(f"{log_prefix} UNKNOWN order {order_id} was FILLED.")

                    # Check if this order closes our position
                    is_opposing_trade = (
                        side == "SELL" and position.direction == SignalDirection.LONG
                    ) or (side == "BUY" and position.direction == SignalDirection.SHORT)

                    # We assume it closes the entire position if the quantity matches the remaining one with a small tolerance
                    # quantity_filled_cumulative here is the filled quantity for THIS unknown order
                    lot_step_size = 1e-8
                    if isinstance(position.signal_details, dict):
                        lot_step_size = float(
                            position.signal_details.get("lot_step_size", 1e-8)
                        )
                    closes_entire_known_position = is_opposing_trade and (
                        abs(quantity_filled_cumulative - position.remaining_quantity)
                        < (lot_step_size * 0.5)
                    )  # Comparison with half of the lot step

                    if closes_entire_known_position:
                        logger.warning(
                            f"{log_prefix} Position for {symbol} appears FULLY CLOSED by UNKNOWN order {order_id}. Treating as MANUAL_CLOSE_DETECTED."
                        )
                        exit_price_manual_fill = (
                            avg_price_filled
                            if avg_price_filled > 0
                            else last_filled_price
                        )
                        if exit_price_manual_fill <= 0:
                            exit_price_manual_fill = 0.0  # Fallback

                        self.loop.create_task(
                            self._handle_final_exit(
                                symbol,
                                "MANUAL_CLOSE_DETECTED",
                                exit_price_manual_fill,
                                commission,
                                commission_asset,
                                order_id,
                                client_order_id,
                                realized_pnl_from_exchange=realized_pnl_from_exchange,
                                exchange_pnl_available=exchange_pnl_available,
                                market_type=event_market_type,
                            ),
                            name=f"HandleExit_ManualDetectFill_{symbol}_{order_id}",
                        )
                    elif (
                        is_opposing_trade and quantity_filled_cumulative > 0
                    ):  # Partially closes
                        logger.warning(
                            f"{log_prefix} Position for {symbol} appears PARTIALLY CLOSED by UNKNOWN order {order_id}. Executed Qty: {quantity_filled_cumulative:.8f}. Current remaining: {position.remaining_quantity:.8f}"
                        )
                        # This is a complex case. Ideally, remaining_quantity should be updated.
                        # And, possibly, move SL/TP.
                        # For now, for safety, the closure of the remainder can be initiated.
                        if quantity_filled_cumulative < position.remaining_quantity:
                            logger.warning(
                                f"{log_prefix} Initiating closure of remaining quantity for {symbol} due to partial manual close detection."
                            )
                            self.loop.create_task(
                                self.close_position(
                                    symbol,
                                    f"REMAINDER_AFTER_MANUAL_PARTIAL_CLOSE_{order_id}",
                                    market_type=event_market_type,
                                ),
                                name=f"CloseRemainderManual_{symbol}",
                            )
                        else:  # Executed more than was in the position? Strange.
                            logger.error(
                                f"{log_prefix} Unknown order {order_id} filled more ({quantity_filled_cumulative}) than remaining ({position.remaining_quantity}). Closing as if fully closed."
                            )
                            exit_price_manual_fill_err = (
                                avg_price_filled
                                if avg_price_filled > 0
                                else last_filled_price
                            )
                            self.loop.create_task(
                                self._handle_final_exit(
                                    symbol,
                                    "MANUAL_CLOSE_DETECTED_OVERFILL",
                                    exit_price_manual_fill_err,
                                    commission,
                                    commission_asset,
                                    order_id,
                                    client_order_id,
                                    realized_pnl_from_exchange=realized_pnl_from_exchange,
                                    exchange_pnl_available=exchange_pnl_available,
                                    market_type=event_market_type,
                                ),
                                name=f"HandleExit_ManualDetectOverfill_{symbol}",
                            )

                    else:  # Does not close or increase the position (not opposite or quantity is 0)
                        logger.info(
                            f"{log_prefix} Unknown FILLED order {order_id} does not appear to close current position or is not opposing. "
                            f"Side: {side}, PosDirection: {position.direction.name}, Opposing={is_opposing_trade}, QtyFilled={quantity_filled_cumulative:.8f}. No automated action taken."
                        )
                else:  # Unknown order status is not FILLED
                    logger.info(
                        f"{log_prefix} Unknown order {order_id} has status '{order_status}'. No specific action taken for OPEN position."
                    )

            # Final check of position status change if it was not deleted
            current_pos_after_logic = self._active_position_get(
                symbol, event_market_type
            )  # Getting again, as it might have been deleted
            if (
                current_pos_after_logic
                and current_pos_after_logic.status != initial_pos_status_log
            ):
                logger.info(
                    f"{log_prefix} Position status changed during this update (final check for {order_id}): '{initial_pos_status_log}' -> '{current_pos_after_logic.status}'."
                )

        logger.debug(
            f"{log_prefix} Finished processing order update (end of function) for OrderID: {order_id}."
        )

    async def _update_market_info_cache(self, force: bool = False):
        log_prefix = "[MarketInfoCache]"
        try:
            exchange_info = await self.executors["live"].fetch_exchange_info(
                force_update=force
            )
            if exchange_info and isinstance(exchange_info.get("symbols"), list):
                new_cache = {}
                processed_count = 0
                for symbol_data in exchange_info["symbols"]:
                    symbol = symbol_data.get("symbol")
                    if not symbol:
                        continue
                    tick_size = None
                    lot_params = None
                    min_notional = None
                    filters = symbol_data.get("filters", [])
                    if isinstance(filters, list):
                        for f in filters:
                            f_type = f.get("filterType")
                            try:
                                if f_type == "PRICE_FILTER":
                                    tick_size = float(f.get("tickSize"))
                                elif f_type == "LOT_SIZE":
                                    lot_params = {
                                        "minQty": float(f["minQty"]),
                                        "maxQty": float(f["maxQty"]),
                                        "stepSize": float(f["stepSize"]),
                                    }
                                elif f_type == "NOTIONAL" or f_type == "MIN_NOTIONAL":
                                    m_key = (
                                        "minNotional"
                                        if "minNotional" in f
                                        else ("notional" if "notional" in f else None)
                                    )
                                    if m_key and f.get(m_key):
                                        min_notional = float(f.get(m_key))
                            except Exception:
                                pass  # Ignore parsing errors of individual filters

                    symbol_key = symbol.upper()
                    info_payload = {
                        "tick_size": tick_size,
                        "lot_params": lot_params,
                        "min_notional": min_notional,
                    }
                    new_cache[symbol_key] = info_payload
                    new_cache[
                        f"{self._normalize_market_type(getattr(self.executors.get('live'), 'market_type', None))}:{symbol_key}"
                    ] = info_payload
                    processed_count += 1
                async with self._market_info_lock:
                    if self._market_info_cache != new_cache:
                        self._market_info_cache = new_cache
                        logger.info(
                            f"{log_prefix} Updated. Processed {processed_count} symbols."
                        )
            else:
                logger.warning(f"{log_prefix} Failed: Invalid data from executor.")
            async with self._market_info_lock:
                current_cache = dict(self._market_info_cache)
            for extra_market_type, extra_executor in self.market_executors.items():
                normalized_extra_market = self._normalize_market_type(extra_market_type)
                if normalized_extra_market == self._normalize_market_type(
                    getattr(self.executors.get("live"), "market_type", None)
                ):
                    continue
                if extra_executor is None:
                    continue
                extra_info = await extra_executor.fetch_exchange_info(
                    force_update=force, specific_market_type=normalized_extra_market
                )
                if not extra_info or not isinstance(extra_info.get("symbols"), list):
                    logger.warning(
                        f"{log_prefix} Failed: Invalid data from executor for market {normalized_extra_market}."
                    )
                    continue
                extra_processed = 0
                for symbol_data in extra_info["symbols"]:
                    symbol = (
                        symbol_data.get("symbol") or symbol_data.get("pair") or ""
                    ).upper()
                    if not symbol:
                        continue
                    tick_size = None
                    lot_params = None
                    min_notional = None
                    filters = symbol_data.get("filters", [])
                    if isinstance(filters, list):
                        for f in filters:
                            f_type = f.get("filterType")
                            try:
                                if f_type == "PRICE_FILTER":
                                    tick_size = float(f.get("tickSize"))
                                elif f_type == "LOT_SIZE":
                                    lot_params = {
                                        "minQty": float(f["minQty"]),
                                        "maxQty": float(f["maxQty"]),
                                        "stepSize": float(f["stepSize"]),
                                    }
                                elif f_type == "MARKET_LOT_SIZE" and lot_params is None:
                                    lot_params = {
                                        "minQty": float(f["minQty"]),
                                        "maxQty": float(f["maxQty"]),
                                        "stepSize": float(f["stepSize"]),
                                    }
                                elif f_type == "NOTIONAL" or f_type == "MIN_NOTIONAL":
                                    m_key = (
                                        "minNotional"
                                        if "minNotional" in f
                                        else ("notional" if "notional" in f else None)
                                    )
                                    if m_key and f.get(m_key):
                                        min_notional = float(f.get(m_key))
                            except Exception:
                                pass
                    current_cache[f"{normalized_extra_market}:{symbol}"] = {
                        "tick_size": tick_size,
                        "lot_params": lot_params,
                        "min_notional": min_notional,
                    }
                    extra_processed += 1
                async with self._market_info_lock:
                    self._market_info_cache = current_cache
                if extra_processed:
                    logger.info(
                        f"{log_prefix} Updated {extra_processed} symbols for market {normalized_extra_market}."
                    )
        except Exception as e:
            logger.error(f"{log_prefix} Error: {e}", exc_info=True)

    async def _get_market_info(
        self, symbol: str, key: str, market_type: Optional[str] = None
    ) -> Optional[Any]:
        async with self._market_info_lock:  # Protecting cache reading
            symbol_key = symbol.upper()
            if market_type:
                market_key = f"{self._normalize_market_type(market_type)}:{symbol_key}"
                market_value = self._market_info_cache.get(market_key, {}).get(key)
                if market_value is not None:
                    return market_value
            return self._market_info_cache.get(symbol_key, {}).get(key)
        # If on-demand loading is needed if not in cache:
        # data = self._market_info_cache.get(symbol, {}).get(key)
        # if data is None:
        #     await self._update_market_info_cache(force=True) # A more specific update for a single symbol can be done
        #     data = self._market_info_cache.get(symbol, {}).get(key)
        # return data

    async def _get_executor_for_symbol(
        self, symbol: str, market_type: Optional[str] = None
    ) -> Optional[Union[BinanceExecutor, PaperTradingExecutor]]:
        symbol_lock = self._get_lock_for_position(symbol, market_type)
        async with symbol_lock:
            position = self._active_position_get(symbol, market_type)
            if not position:
                logger.warning(
                    f"[_get_executor_for_symbol] Position not found for symbol {symbol} market={market_type}. Cannot determine mode."
                )
                return None

        mode = position.mode
        executor = self._executor_for_market_type(
            self._market_type_for_position(position), mode=mode
        )
        if not executor:
            logger.error(
                f"[_get_executor_for_symbol] Executor for mode '{mode}' and market '{self._market_type_for_position(position)}' not found."
            )
            return None
        return executor

    async def close_position(
        self,
        symbol: str,
        reason: str = "MANUAL_CLOSE",
        market_type: Optional[str] = None,
    ):
        """
        Reliably closes the position for the specified symbol.
        Attempts to close the position until confirmation is received from the exchange,
        or until the timeout expires.
        """
        normalized_market_type = (
            self._normalize_market_type(market_type) if market_type else None
        )
        log_prefix = f"[ClosePosition:{symbol}:{normalized_market_type or 'auto'}]"
        logger.info(
            f"{log_prefix} === START OF RELIABLE CLOSURE PROCEDURE. Reason: {reason} ==="
        )

        # Step 1: Set internal status and cancel related orders
        position_obj_snapshot = None

        logger.debug(f"{log_prefix} Acquiring lock to set CLOSING status...")
        # Since we might not know the market_type yet, we try to find it first without a lock
        # if it's already specified. If not, we'll need to lock based on symbol if we find a unique one.
        if normalized_market_type:
            symbol_lock = self._get_lock_for_position(symbol, normalized_market_type)
            async with symbol_lock:
                position = self._active_position_get(symbol, normalized_market_type)
                if not position:
                    logger.info(
                        f"{log_prefix} Position not found in active ones. Procedure completed."
                    )
                    return

                if position.status == "CLOSED":
                    logger.info(
                        f"{log_prefix} Position is already closed (status=CLOSED). Procedure completed."
                    )
                    return

                # If the position is already in CLOSING status, but remaining_quantity = 0, we also exit
                if position.status == "CLOSING" and position.remaining_quantity <= 0:
                    logger.info(
                        f"{log_prefix} Position is already in CLOSING status with zero balance. Waiting for finalization."
                    )
                    return

                # For positions in CLOSING status with remaining_quantity > 0 — this is a retry, continuing
                if position.status == "CLOSING":
                    logger.warning(
                        f"{log_prefix} Position is already in CLOSING status, but remaining_quantity={position.remaining_quantity:.8f} > 0. This is a retry of the closure."
                    )
                else:
                    # Set the CLOSING status only if it is not already set
                    position.status = "CLOSING"
                    self.loop.create_task(
                        self._publish_state_to_redis(),
                        name=f"PublishState_Closing_{symbol}",
                    )

                position.exit_reason = reason
                # Creating a copy for subsequent processing, even if the position is deleted
                position_obj_snapshot = copy.deepcopy(position)
                logger.info(
                    f"{log_prefix} Internal position status: 'CLOSING'. Remaining qty: {position.remaining_quantity:.8f}"
                )
        else:
            # Ambiguous case - search across all markets
            async with self._positions_dict_lock:
                matching_positions = self._active_positions_for_symbol(symbol)

            if len(matching_positions) > 1:
                logger.error(
                    f"{log_prefix} Multiple active positions exist for {symbol}. "
                    "market_type is required to close a specific position."
                )
                return
            elif len(matching_positions) == 0:
                logger.info(f"{log_prefix} No active position found for {symbol}.")
                return

            position_to_lock = matching_positions[0]
            normalized_market_type = self._market_type_for_position(position_to_lock)

            symbol_lock = self._get_lock_for_position(symbol, normalized_market_type)
            async with symbol_lock:
                position = self._active_position_get(symbol, normalized_market_type)
                if not position or position.status == "CLOSED":
                    return

                position.status = "CLOSING"
                position.exit_reason = reason
                self.loop.create_task(
                    self._publish_state_to_redis(),
                    name=f"PublishState_Closing_{symbol}",
                )
                position_obj_snapshot = copy.deepcopy(position)
                logger.info(
                    f"{log_prefix} Internal position status: 'CLOSING' ({normalized_market_type}). Remaining qty: {position.remaining_quantity:.8f}"
                )

        # Wrap _cancel_all_exit_orders with timeout to prevent hanging
        try:
            await asyncio.wait_for(
                self._cancel_all_exit_orders(
                    symbol, f"FORCED_CLOSE_{reason}", market_type=normalized_market_type
                ),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"{log_prefix} Timeout cancelling exit orders. Proceeding to force close."
            )
        except Exception as e:
            logger.error(f"{log_prefix} Error cancelling exit orders: {e}")

        # Step 2: Closing loop with verification and retries
        is_confirmed_closed = False
        max_retries = 120  # Attempts every 0.5 seconds, total 1 minute (was 5 sec)
        retry_delay = 0.5  # Seconds

        executor = await self._get_executor_for_symbol(
            symbol, market_type=normalized_market_type
        )
        if not executor:
            logger.critical(
                f"{log_prefix} Could not determine executor for {symbol}. Aborting close procedure."
            )
            # Since we can't determine the executor, we can't close. This is a critical failure.
            if self.telegram_notifier:
                self.loop.create_task(
                    self.telegram_notifier.bot_error(
                        error_description=f"CRITICAL ERROR: Failed to determine the executor for closing the position on {symbol}!",
                        module_function="close_position",
                        action_taken="Closing procedure interrupted. Manual intervention required!",
                        chat_id=self.user_telegram_chat_id,
                        api_key_name=self.api_key_name,
                    )
                )
            return

        # Synchronization with the actual position size on the exchange
        # This is critical for futures to avoid closing only part of the position due to outdated data
        is_spot_market = self._executor_is_spot(executor) or not getattr(
            executor, "supports_positions", False
        )
        position_market_type = (
            self._market_type_for_position(position_obj_snapshot)
            if position_obj_snapshot
            else getattr(executor, "market_type", None)
        )

        try:
            cancel_all_response = await asyncio.wait_for(
                executor.cancel_all_open_orders(symbol), timeout=10.0
            )
            if isinstance(cancel_all_response, dict) and cancel_all_response.get(
                "error"
            ):
                logger.warning(
                    f"{log_prefix} Could not cancel all open orders before close: {cancel_all_response}"
                )
            else:
                logger.info(
                    f"{log_prefix} All open orders for {symbol} cancelled before market close."
                )
            await asyncio.sleep(0.25)
        except asyncio.TimeoutError:
            logger.warning(
                f"{log_prefix} Timeout while cancelling all open orders before close. Proceeding to market close."
            )
        except Exception as cancel_all_error:
            logger.warning(
                f"{log_prefix} Error cancelling all open orders before close: {cancel_all_error}",
                exc_info=True,
            )

        if getattr(executor, "supports_positions", False):
            try:
                exchange_positions = await executor.get_open_positions()
                exchange_pos_data = next(
                    (
                        p
                        for p in exchange_positions
                        if p["symbol"] == symbol and float(p.get("positionAmt", 0)) != 0
                    ),
                    None,
                )
                if exchange_pos_data:
                    real_qty = abs(float(exchange_pos_data["positionAmt"]))
                    symbol_lock_sync1 = self._get_lock_for_position(
                        symbol, normalized_market_type
                    )
                    async with symbol_lock_sync1:
                        position_for_sync = self._active_position_get(
                            symbol, normalized_market_type
                        )
                        if position_for_sync:
                            internal_qty = position_for_sync.remaining_quantity
                            qty_diff = abs(internal_qty - real_qty)
                            if qty_diff > 1e-9:
                                qty_diff_pct = (
                                    (qty_diff / real_qty * 100) if real_qty > 0 else 0
                                )
                                if real_qty < internal_qty:
                                    logger.info(
                                        f"{log_prefix} SYNC: Internal qty {internal_qty} > Exchange qty {real_qty}. Assuming PARTIAL CLOSE/PTP occurred externally. Syncing to {real_qty}."
                                    )
                                    position_for_sync.remaining_quantity = real_qty
                                else:
                                    logger.warning(
                                        f"{log_prefix} SYNC: Internal qty {internal_qty} < Exchange qty {real_qty}. Resyncing."
                                    )
                                    position_for_sync.remaining_quantity = real_qty

                                    if self.telegram_notifier and qty_diff_pct > 1.0:
                                        self.loop.create_task(
                                            self.telegram_notifier.bot_error(
                                                error_description=f"⚠️ DESYNCHRONIZATION (Position Increased?!) for {symbol}! "
                                                f"Locally: {internal_qty:.4f}, Exchange: {real_qty:.4f}",
                                                module_function="close_position",
                                                action_taken="Synchronized with the exchange.",
                                                chat_id=self.user_telegram_chat_id,
                                                api_key_name=self.api_key_name,
                                            )
                                        )
                else:
                    logger.warning(
                        f"{log_prefix} No position found on exchange for {symbol}. Triggering final exit to sync with DB and clean up."
                    )
                    last_price_info = None
                    try:
                        last_price_info = await executor.get_ticker_price(symbol)
                    except Exception as e_price:
                        logger.warning(
                            f"{log_prefix} Could not fetch price for final exit: {e_price}"
                        )
                    approx_exit_price = (
                        float(last_price_info["price"])
                        if last_price_info and "price" in last_price_info
                        else 0.0
                    )

                    await self._handle_final_exit(
                        symbol=symbol,
                        reason=reason,
                        exit_price=approx_exit_price,
                        commission=0.0,
                        commission_asset="USDT",
                        order_id=None,
                        client_order_id=None,
                        market_type=normalized_market_type,
                    )

                    if self.telegram_notifier:
                        self.loop.create_task(
                            self.telegram_notifier.bot_error(
                                error_description=f"⚠️ Position {symbol} is missing on the exchange, but was in the bot's memory!",
                                module_function="close_position",
                                action_taken=f"Position removed from internal state and final exit processed. Closing reason: {reason}",
                                chat_id=self.user_telegram_chat_id,
                                api_key_name=self.api_key_name,
                            )
                        )
                    return
            except Exception as sync_error:
                logger.error(
                    f"{log_prefix} Failed to sync with exchange before close: {sync_error}. Proceeding with internal data."
                )

        close_order_placed = False

        for attempt in range(max_retries):
            # 1. Checking the position status
            # For futures, check via REST API
            if getattr(executor, "supports_positions", False):
                try:
                    exchange_positions = await executor.get_open_positions()
                    exchange_pos_data = next(
                        (
                            p
                            for p in exchange_positions
                            if p["symbol"] == symbol
                            and float(p.get("positionAmt", 0)) != 0
                        ),
                        None,
                    )
                    if not exchange_pos_data:
                        logger.info(
                            f"{log_prefix} Position {symbol} is missing on the exchange according to REST API data. Closing confirmed."
                        )
                        # Cleanup and pop is deferred to _handle_final_exit
                        is_confirmed_closed = True
                        break
                    else:
                        real_qty = abs(float(exchange_pos_data["positionAmt"]))
                        symbol_lock_resync = self._get_lock_for_position(
                            symbol, normalized_market_type
                        )
                        async with symbol_lock_resync:
                            position_for_sync = self._active_position_get(
                                symbol, normalized_market_type
                            )
                            if position_for_sync:
                                position_for_sync.remaining_quantity = real_qty
                except Exception as sync_err:
                    logger.error(
                        f"{log_prefix} Position synchronization error via REST API: {sync_err}"
                    )

            # Retrieve direction and qty for spot check and order placement
            current_direction = None
            current_qty = 0.0
            async with self._get_lock_for_position(symbol, normalized_market_type):
                pos = self._active_position_get(symbol, normalized_market_type)
                if pos:
                    current_direction = pos.direction
                    current_qty = pos.remaining_quantity
                else:
                    is_confirmed_closed = True
                    break

            if (
                not getattr(executor, "supports_positions", False)
                and current_direction == SignalDirection.LONG
            ):
                try:
                    balances = await executor.get_account_balance()
                    symbol_upper = symbol.upper()
                    base_asset = symbol_upper
                    for quote_asset in (
                        "USDT",
                        "USDC",
                        "BUSD",
                        "BTC",
                        "ETH",
                        "EUR",
                        "TRY",
                    ):
                        if symbol_upper.endswith(quote_asset) and len(
                            symbol_upper
                        ) > len(quote_asset):
                            base_asset = symbol_upper[: -len(quote_asset)]
                            break
                    base_balance = (balances or {}).get(base_asset, {})
                    free_base_qty = float(base_balance.get("free", 0) or 0)
                    locked_base_qty = float(base_balance.get("locked", 0) or 0)
                    if free_base_qty > 0 and free_base_qty < current_qty:
                        if locked_base_qty > 0 and free_base_qty < current_qty * 0.5:
                            logger.info(
                                f"{log_prefix} SPOT SYNC: Free {base_asset} balance is only "
                                f"{free_base_qty:.8f} while {locked_base_qty:.8f} is still locked. "
                                "Waiting for cancelled spot exit orders to release funds."
                            )
                            await asyncio.sleep(retry_delay)
                            continue
                        logger.info(
                            f"{log_prefix} SPOT SYNC: Internal qty {current_qty:.8f} > "
                            f"free {base_asset} balance {free_base_qty:.8f}. Closing available free balance."
                        )
                        current_qty = free_base_qty
                        symbol_lock_base_sync = self._get_lock_for_position(
                            symbol, normalized_market_type
                        )
                        async with symbol_lock_base_sync:
                            position_for_sync = self._active_position_get(
                                symbol, normalized_market_type
                            )
                            if position_for_sync:
                                position_for_sync.remaining_quantity = free_base_qty
                    total_qty = free_base_qty + locked_base_qty
                    lot_params_sync = await self._get_market_info(
                        symbol, "lot_params", market_type=position_market_type
                    )
                    if not lot_params_sync and hasattr(executor, "get_lot_size_params"):
                        try:
                            lot_params_sync = await executor.get_lot_size_params(symbol)
                        except Exception:
                            pass
                    min_qty_sync = float((lot_params_sync or {}).get("minQty", 0) or 0)
                    step_size_sync = float(
                        (lot_params_sync or {}).get("stepSize", 0) or 0
                    )

                    if (
                        total_qty <= 0
                        or (min_qty_sync > 0 and total_qty < min_qty_sync)
                        or (step_size_sync > 0 and total_qty < step_size_sync)
                        or total_qty < 1e-9
                    ):
                        logger.info(
                            f"{log_prefix} SPOT SYNC: Total {base_asset} balance is {total_qty:.8f} "
                            f"(free={free_base_qty:.8f}, locked={locked_base_qty:.8f}), "
                            f"which is below minimum tradable quantity/step size ({min_qty_sync}/{step_size_sync}). Closing confirmed."
                        )
                        symbol_lock_spot_closed = self._get_lock_for_position(
                            symbol, normalized_market_type
                        )
                        async with symbol_lock_spot_closed:
                            position_for_sync = self._active_position_get(
                                symbol, normalized_market_type
                            )
                            if position_for_sync:
                                position_for_sync.remaining_quantity = 0.0
                        is_confirmed_closed = True
                        break
                    elif free_base_qty <= 0:
                        logger.warning(
                            f"{log_prefix} SPOT SYNC: Free {base_asset} balance is {free_base_qty:.8f} "
                            f"while locked balance is {locked_base_qty:.8f}. "
                            "Open orders may still be locking funds."
                        )
                        await asyncio.sleep(retry_delay)
                        continue
                except Exception as spot_sync_error:
                    logger.warning(
                        f"{log_prefix} Failed to sync spot balance before close: {spot_sync_error}",
                        exc_info=True,
                    )

            if current_qty <= 0:
                logger.warning(
                    f"{log_prefix} Position has zero size but is not deleted. Confirming close."
                )
                # Cleanup and pop is deferred to _handle_final_exit
                is_confirmed_closed = True
                break

            # If we have already sent an order, but the futures position is still open on the exchange -
            # perhaps the order is still being processed or has partially filled. Don't spam with orders!
            if close_order_placed:
                logger.info(
                    f"{log_prefix} Waiting for the execution of an already sent close order (Attempt {attempt + 1}/{max_retries})."
                )
                await asyncio.sleep(retry_delay)
                continue

            # 3. Placing a MARKET order to close
            close_side = "SELL" if current_direction == SignalDirection.LONG else "BUY"

            # Rounding quantity to exchange stepSize
            lot_params = await self._get_market_info(
                symbol, "lot_params", market_type=position_market_type
            )
            if (
                is_spot_market
                and not lot_params
                and hasattr(executor, "get_lot_size_params")
            ):
                try:
                    lot_params = await executor.get_lot_size_params(symbol)
                except Exception as lot_params_error:
                    logger.warning(
                        f"{log_prefix} Could not fetch live lot params for spot close: {lot_params_error}"
                    )
            adjusted_qty = current_qty
            if lot_params:
                step_size = lot_params.get("stepSize", 0)
                if step_size and step_size > 0:
                    from decimal import Decimal, ROUND_DOWN

                    step = Decimal(str(step_size))
                    qty_dec = Decimal(str(current_qty))
                    adjusted_qty = float(
                        (qty_dec / step).quantize(Decimal("0"), rounding=ROUND_DOWN)
                        * step
                    )
                    if adjusted_qty != current_qty:
                        logger.info(
                            f"{log_prefix} Qty rounded: {current_qty:.8f} -> {adjusted_qty:.8f} (stepSize={step_size})"
                        )

            min_qty = float((lot_params or {}).get("minQty", 0) or 0)
            min_notional = await self._get_market_info(
                symbol, "min_notional", market_type=position_market_type
            )
            if (
                is_spot_market
                and min_notional is None
                and hasattr(executor, "get_min_notional")
            ):
                try:
                    min_notional = await executor.get_min_notional(symbol)
                except Exception as min_notional_error:
                    logger.warning(
                        f"{log_prefix} Could not fetch live minNotional for spot close: {min_notional_error}"
                    )
            notional_price: Optional[float] = None
            if is_spot_market and min_notional is not None and min_notional > 0:
                try:
                    ticker_for_notional = await executor.get_ticker_price(symbol)
                    notional_price = (
                        float(ticker_for_notional.get("price") or 0)
                        if ticker_for_notional
                        else None
                    )
                except Exception as ticker_error:
                    logger.warning(
                        f"{log_prefix} Could not fetch ticker for spot dust notional check: {ticker_error}"
                    )

            precision_error_message = ""
            if is_spot_market and adjusted_qty > 0:
                try:
                    ccxt_symbol = (
                        executor._normalize_symbol(symbol)
                        if hasattr(executor, "_normalize_symbol")
                        else symbol
                    )
                    exchange_obj = getattr(executor, "_exchange", None)
                    if exchange_obj and hasattr(exchange_obj, "amount_to_precision"):
                        precision_qty = float(
                            exchange_obj.amount_to_precision(ccxt_symbol, adjusted_qty)
                        )
                        if precision_qty != adjusted_qty:
                            logger.info(
                                f"{log_prefix} Qty precision-adjusted by exchange: "
                                f"{adjusted_qty:.8f} -> {precision_qty:.8f}"
                            )
                            adjusted_qty = precision_qty
                except Exception as precision_error:
                    precision_error_message = str(precision_error)

            spot_qty_below_filters = is_spot_market and (
                adjusted_qty <= 0
                or bool(precision_error_message)
                or (min_qty > 0 and adjusted_qty < min_qty)
                or (
                    min_notional is not None
                    and min_notional > 0
                    and notional_price is not None
                    and notional_price > 0
                    and adjusted_qty * notional_price < min_notional
                )
            )
            if spot_qty_below_filters:
                logger.warning(
                    f"{log_prefix} Spot residual qty {current_qty:.8f} rounds to non-tradable "
                    f"qty {adjusted_qty:.8f} (minQty={min_qty}, minNotional={min_notional}). "
                    "Treating it as dust and closing the internal position after open-order cancellation."
                )
                symbol_lock_dust_rem = self._get_lock_for_position(
                    symbol, normalized_market_type
                )
                async with symbol_lock_dust_rem:
                    position_for_sync = self._active_position_get(
                        symbol, normalized_market_type
                    )
                    if position_for_sync:
                        position_for_sync.remaining_quantity = 0.0
                is_confirmed_closed = True
                break

            if adjusted_qty <= 0:
                logger.error(
                    f"{log_prefix} Adjusted qty is zero or negative ({adjusted_qty}). Trying with original qty {current_qty}."
                )
                adjusted_qty = current_qty  # Fallback

            logger.info(
                f"{log_prefix} Attempt {attempt + 1}/{max_retries}: Sending MARKET order to close {adjusted_qty} {symbol} ({close_side})."
            )

            close_params = {
                "symbol": symbol,
                "side": close_side,
                "order_type": "MARKET",
                "quantity": adjusted_qty,
                "reduceOnly": True
                if getattr(executor, "supports_positions", False)
                else None,
                "newClientOrderId": f"x-close-{uuid.uuid4().hex[:12]}",
                "entry_client_order_id": position.entry_client_order_id
                if position
                else None,
                "strategy_config_id": position.config_id if position else None,
                "exit_type": "FINAL_EXIT",
                "signal_details": position.signal_details if position else None,
            }

            response = await executor.place_order(**close_params)

            if response.get("error"):
                error_msg_lower = str(response.get("msg") or response).lower()
                if is_spot_market and (
                    "minimum amount precision" in error_msg_lower
                    or "min amount" in error_msg_lower
                    or "minimum amount" in error_msg_lower
                    or "minnotional" in error_msg_lower
                    or "min notional" in error_msg_lower
                ):
                    logger.warning(
                        f"{log_prefix} Exchange rejected spot close qty {adjusted_qty:.8f} as non-tradable dust. "
                        "Stopping retries and closing internal position."
                    )
                    symbol_lock_dust_final = self._get_lock_for_position(
                        symbol, normalized_market_type
                    )
                    async with symbol_lock_dust_final:
                        position_for_sync = self._active_position_get(
                            symbol, normalized_market_type
                        )
                        if position_for_sync:
                            position_for_sync.remaining_quantity = 0.0
                    is_confirmed_closed = True
                    break
                logger.error(f"{log_prefix} Error when sending close order: {response}")
            else:
                logger.info(
                    f"{log_prefix} Close order sent. ID: {response.get('orderId')}"
                )
                close_order_placed = True

            await asyncio.sleep(retry_delay)

        # Final processing and result logging
        if is_confirmed_closed:
            logger.info(f"{log_prefix} Closing procedure completed successfully.")
            # Use _handle_final_exit for consistent processing (DB entry, PnL, etc.)
            # Since we don't have the exact exit price from WebSocket, we can take the last ticker price
            # or pass 0 so that PnL is calculated later or manually.
            try:
                final_cancel_response = await asyncio.wait_for(
                    executor.cancel_all_open_orders(symbol), timeout=10.0
                )
                if isinstance(
                    final_cancel_response, dict
                ) and final_cancel_response.get("error"):
                    logger.warning(
                        f"{log_prefix} Could not cancel remaining open orders after close: {final_cancel_response}"
                    )
                else:
                    logger.info(
                        f"{log_prefix} Remaining open orders for {symbol} cancelled after close confirmation."
                    )
            except asyncio.TimeoutError:
                logger.warning(
                    f"{log_prefix} Timeout while cancelling remaining open orders after close confirmation."
                )
            except Exception as final_cancel_error:
                logger.warning(
                    f"{log_prefix} Error cancelling remaining open orders after close confirmation: {final_cancel_error}",
                    exc_info=True,
                )

            last_price_info = await executor.get_ticker_price(symbol)
            approx_exit_price = (
                float(last_price_info["price"])
                if last_price_info and "price" in last_price_info
                else 0.0
            )

            # Important: _handle_final_exit will remove the position from _active_positions.
            # We call it only once, being sure that everything is closed on the exchange.
            await self._handle_final_exit(
                symbol=symbol,
                reason=reason,
                exit_price=approx_exit_price,
                commission=0,  # We don't know the exact commission, can leave it as 0
                commission_asset="USDT",
                order_id=None,  # Closing order ID is not that important to us
                client_order_id=None,
                market_type=normalized_market_type,
            )
        else:
            logger.critical(
                f"{log_prefix} CRITICAL ERROR: FAILED to confirm position closure after {max_retries} attempts! Manual intervention required!"
            )
            # Here we need to add sending a notification to Telegram or another monitoring system
            if self.telegram_notifier:
                self.loop.create_task(
                    self.telegram_notifier.bot_error(
                        error_description=f"FAILED TO CLOSE POSITION for {symbol}!",
                        module_function="close_position",
                        action_taken=f"After {max_retries} attempts the position may still be open. MANUAL INTERVENTION REQUIRED!",
                        chat_id=self.user_telegram_chat_id,
                        api_key_name=self.api_key_name,
                    )
                )

        logger.info(
            f"{log_prefix} === COMPLETION OF THE RELIABLE CLOSURE PROCEDURE ==="
        )

    async def _check_and_manage_pending_entry_orders(self):
        """
        Checks all active limit entry orders (PENDING_ENTRY status).
        Cancels the order if:
        1. It has existed longer than LIMIT_ORDER_MAX_LIFETIME_SECONDS.
        2. Entry foundations are no longer valid.
        """
        log_prefix_main = "[ManagePendingEntry]"
        now = time.time()

        # Collect positions for processing outside the main lock
        async with self._positions_dict_lock:
            positions_to_evaluate = [
                p
                for p in self._active_positions.values()
                if p.status == "PENDING_ENTRY" and p.entry_order_id is not None
            ]

        if not positions_to_evaluate:
            return

        logger.debug(
            f"{log_prefix_main} Checking {len(positions_to_evaluate)} PENDING_ENTRY positions."
        )

        for position_ref in positions_to_evaluate:
            log_prefix_pos = f"[{log_prefix_main}:{position_ref.symbol}]"

            symbol_lock = self._get_lock_for_position(
                position_ref.symbol, position_ref.market_type
            )
            async with symbol_lock:
                # Re-check status under symbol lock
                current_pos = self._active_position_get(
                    position_ref.symbol, position_ref.market_type
                )
                if (
                    not current_pos
                    or current_pos.entry_order_id != position_ref.entry_order_id
                    or current_pos.status != "PENDING_ENTRY"
                ):
                    continue

                order_age = now - current_pos.entry_time

            # 1. Check by maximum lifetime
            if order_age > config.LIMIT_ORDER_MAX_LIFETIME_SECONDS:
                logger.info(
                    f"{log_prefix_pos} Entry order {position_ref.entry_order_id} (age: {order_age:.0f}s) exceeded max lifetime ({config.LIMIT_ORDER_MAX_LIFETIME_SECONDS}s). Cancelling."
                )

                order_id_to_cancel_timeout = position_ref.entry_order_id
                client_order_id_timeout = position_ref.entry_client_order_id
                symbol_timeout = position_ref.symbol
                strategy_timeout = position_ref.strategy

                symbol_lock_timeout = self._get_lock_for_position(
                    symbol_timeout, self._market_type_for_position(position_ref)
                )
                async with symbol_lock_timeout:
                    async with self._positions_dict_lock:  # Lock for deletion
                        pos_timeout = self._active_position_get(
                            symbol_timeout, self._market_type_for_position(position_ref)
                        )
                        if (
                            pos_timeout
                            and pos_timeout.entry_order_id == order_id_to_cancel_timeout
                        ):
                            self._active_position_pop(
                                symbol_timeout,
                                self._market_type_for_position(position_ref),
                            )
                        else:  # If the position is suddenly already deleted or changed, do not attempt to cancel the order
                            logger.warning(
                                f"{log_prefix_pos} Position changed during timeout check. Not cancelling order {order_id_to_cancel_timeout}."
                            )
                            continue

                executor_for_cancel = self._executor_for_market_type(
                    self._market_type_for_position(position_ref), mode=position_ref.mode
                )
                if not executor_for_cancel:
                    logger.error(
                        f"{log_prefix_pos} Executor for market '{self._market_type_for_position(position_ref)}' not found. Cannot cancel pending entry."
                    )
                    continue
                self.loop.create_task(
                    executor_for_cancel.cancel_order(
                        symbol=symbol_timeout, orderId=order_id_to_cancel_timeout
                    ),
                    name=f"CancelPendingEntryTimeout_{symbol_timeout}",
                )
                self.trade_logger.log_event(
                    event_type="ENTRY_ORDER_CANCELLED_TIMEOUT",
                    data={
                        "symbol": symbol_timeout,
                        "strategy": strategy_timeout,
                        "client_order_id": client_order_id_timeout,
                        "order_id": order_id_to_cancel_timeout,
                        "reason": f"Exceeded max lifetime ({order_age:.0f}s > {config.LIMIT_ORDER_MAX_LIFETIME_SECONDS}s)",
                    },
                )
                self._last_position_close_time_per_symbol[
                    self._position_key(
                        symbol_timeout, self._market_type_for_position(position_ref)
                    )
                ] = now
                continue  # Moving to the next position

            # 2. Re-checking foundations (Foundations)
            log_prefix_recheck = (
                f"[{log_prefix_main}:RecheckFoundations:{position_ref.symbol}]"
            )
            logger.debug(
                f"{log_prefix_recheck} Re-checking foundations for entry order {position_ref.entry_order_id}."
            )

            # Getting current pair_info
            active_pairs_list = await self.consumer.get_active_pairs()
            pair_info_raw = next(
                (
                    p
                    for p in active_pairs_list
                    if p.get("symbol") == position_ref.symbol
                ),
                None,
            )

            if not pair_info_raw:
                logger.warning(
                    f"{log_prefix_recheck} No pair_info from consumer for {position_ref.symbol}. Cannot recheck foundations."
                )
                continue

            pair_info_enriched: Optional[Dict[str, Any]] = None
            try:
                position_market_type = self._market_type_for_position(position_ref)
                tick_size = (
                    await self._get_market_info(
                        position_ref.symbol,
                        "tick_size",
                        market_type=position_market_type,
                    )
                    or config.DEFAULT_TICK_SIZE
                )
                # lot_params and min_notional are not needed here for check_foundations, but might be needed for other checks
                atr_value = pair_info_raw.get("atr")
                last_price_value = pair_info_raw.get("last_price")

                if (
                    atr_value is None
                    or atr_value <= 0
                    or last_price_value is None
                    or last_price_value <= 0
                ):
                    logger.warning(
                        f"{log_prefix_recheck} Invalid ATR ({atr_value}) or LastPrice ({last_price_value}) for {position_ref.symbol}. Cannot recheck."
                    )
                    continue

                pair_info_enriched = {
                    **pair_info_raw,
                    "tick_size": tick_size,
                    "atr": atr_value,
                    "last_price": last_price_value,
                    # Adding 'lot_params' and 'min_notional' just in case some strategy uses them in check_foundations
                    "lot_params": await self._get_market_info(
                        position_ref.symbol,
                        "lot_params",
                        market_type=position_market_type,
                    ),
                    "min_notional": await self._get_market_info(
                        position_ref.symbol,
                        "min_notional",
                        market_type=position_market_type,
                    ),
                }
            except Exception as e:
                logger.error(
                    f"{log_prefix_recheck} Error enriching pair_info for recheck: {e}"
                )
                continue

            if pair_info_enriched is None:
                continue  # If enrichment failed

            strategy_instance = get_strategy_instance(position_ref.strategy)
            if not strategy_instance:
                logger.error(
                    f"{log_prefix_recheck} Could not get strategy instance for {position_ref.strategy}. Cannot recheck."
                )
                continue

            # Loading market_data for the strategy
            required_data_keys_recheck = strategy_instance.required_data_types
            market_data_for_recheck: Dict[str, Any] = {}
            fetch_tasks_recheck = []

            async def fetch_data_for_recheck(key_to_fetch: str, symbol_to_fetch: str):
                try:
                    parts = key_to_fetch.split("_")
                    data_type = parts[0]
                    data = None
                    if data_type == "kline":
                        timeframe = parts[1] if len(parts) > 1 else "1m"
                        kline_symbol = parts[2] if len(parts) > 2 else symbol_to_fetch
                        data = await self.consumer.get_kline_history(
                            kline_symbol, timeframe, market_type=position_market_type
                        )
                    elif data_type == "depth":
                        depth_raw = await self.consumer.get_latest_depth(
                            symbol_to_fetch, market_type_requested=position_market_type
                        )
                        depth_snapshot_ts = None
                        if isinstance(depth_raw, dict):
                            depth_snapshot_ts = depth_raw.get(
                                "event_time_ms"
                            ) or depth_raw.get("cached_at_ms")
                        max_age_ms = int(
                            getattr(config, "MAX_DEPTH_SNAPSHOT_AGE_MS", 1500)
                        )
                        if depth_snapshot_ts and max_age_ms > 0:
                            try:
                                if (
                                    int(time.time() * 1000) - int(depth_snapshot_ts)
                                ) > max_age_ms:
                                    depth_raw = None
                            except (TypeError, ValueError):
                                pass
                        if depth_raw:
                            full_l2 = depth_raw.get("full_l2_depth")
                            if not isinstance(full_l2, dict):
                                full_l2 = {
                                    "lastUpdateId": depth_raw.get("lastUpdateId"),
                                    "bids": depth_raw.get("bids", [])
                                    if isinstance(depth_raw.get("bids"), list)
                                    else [],
                                    "asks": depth_raw.get("asks", [])
                                    if isinstance(depth_raw.get("asks"), list)
                                    else [],
                                }
                            aggregated = depth_raw.get("aggregated_depth")
                            if not isinstance(aggregated, dict):
                                aggregated = {}
                            market_data_for_recheck["depth_trading"] = full_l2
                            market_data_for_recheck["depth_analysis"] = aggregated
                        else:
                            market_data_for_recheck["depth_trading"] = {}
                            market_data_for_recheck["depth_analysis"] = {}
                        market_data_for_recheck["depth"] = market_data_for_recheck.get(
                            "depth_trading", {}
                        )
                        data = market_data_for_recheck.get("depth")
                    elif data_type == "aggTrade":
                        data = await self.consumer.get_recent_trades(
                            symbol_to_fetch, market_type=position_market_type
                        )

                    if data is not None:
                        is_empty_data = False
                        if isinstance(data, list) and not data:
                            is_empty_data = True
                        elif isinstance(data, pd.DataFrame) and data.empty:
                            is_empty_data = True
                        elif isinstance(data, dict) and not data:
                            is_empty_data = True

                        if not is_empty_data:
                            market_data_for_recheck[key_to_fetch] = data
                        # else: # Can log if data is empty, but this might be expected
                        #    logger.debug(f"{log_prefix_recheck} Fetched empty data for {key_to_fetch} on {symbol_to_fetch}")
                except Exception as e_fetch:
                    logger.error(
                        f"{log_prefix_recheck} Error fetching data for recheck key '{key_to_fetch}' for {symbol_to_fetch}: {e_fetch}"
                    )

            for key_req_recheck in required_data_keys_recheck:
                fetch_tasks_recheck.append(
                    self.loop.create_task(
                        fetch_data_for_recheck(key_req_recheck, position_ref.symbol),
                        name=f"RecheckFetch_{position_ref.symbol}_{key_req_recheck}",
                    )
                )

            if fetch_tasks_recheck:
                await asyncio.gather(*fetch_tasks_recheck, return_exceptions=True)

            # Checking if all necessary data for check_foundations has been loaded
            can_recheck_foundations = True
            for req_key_recheck in required_data_keys_recheck:
                fetched_data_recheck = market_data_for_recheck.get(req_key_recheck)
                is_missing_or_empty_recheck = False
                if fetched_data_recheck is None:
                    is_missing_or_empty_recheck = True
                elif (
                    isinstance(fetched_data_recheck, list) and not fetched_data_recheck
                ):
                    is_missing_or_empty_recheck = True
                elif (
                    isinstance(fetched_data_recheck, pd.DataFrame)
                    and fetched_data_recheck.empty
                ):
                    is_missing_or_empty_recheck = True
                elif (
                    isinstance(fetched_data_recheck, dict) and not fetched_data_recheck
                ):
                    is_missing_or_empty_recheck = True

                if is_missing_or_empty_recheck:
                    can_recheck_foundations = False
                    logger.warning(
                        f"{log_prefix_recheck} Missing or empty market data for '{req_key_recheck}'. Cannot recheck foundations accurately."
                    )
                    break

            if not can_recheck_foundations:
                continue  # Move to the next position if we cannot re-check this one

            foundations_now_raw = strategy_instance.check_foundations(
                pair_info_enriched.copy(), market_data_for_recheck.copy()
            )
            foundations_now = (
                foundations_now_raw[0]
                if isinstance(foundations_now_raw, tuple)
                else foundations_now_raw
            )

            if not isinstance(foundations_now, dict):
                logger.warning(
                    f"{log_prefix_recheck} strategy.check_foundations() returned type '{type(foundations_now).__name__}' instead of dict. Cannot re-check foundations."
                )
                continue  # Moving to the next position

            initial_foundation_weight = position_ref.signal_details.get(
                "foundation_total_weight", 0.0
            )
            # Ensure that check_foundations returns 'foundation_total_weight'.
            # If not, this logic will not work.
            # BaseStrategy.check_foundations does not calculate 'foundation_total_weight', check_signal_sync does this.
            # We need check_foundations in strategies to calculate and return 'foundation_total_weight' itself.
            # For now, assume it does not return it, and we use MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD.

            # FIXED FOUNDATIONS CHECK LOGIC
            # check_foundations returns a dictionary where keys are foundation types and values are bool or objects (OrderbookAnalysisResult).
            # We need to sum the weights of the executed reasons.

            current_foundation_weight_calculated = 0.0
            foundation_weights_config: Dict[str, float] = getattr(
                config, "FOUNDATION_WEIGHTS", {}
            )
            min_weight_threshold_config: float = getattr(
                config, "MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD", 50.0
            )

            if not foundation_weights_config:
                logger.warning(
                    f"{log_prefix_recheck} FOUNDATION_WEIGHTS not configured. Skipping foundation-based cancellation for order {position_ref.entry_order_id}."
                )
            else:
                for found_key, weight_pct in foundation_weights_config.items():
                    is_met_now = False
                    foundation_value_now = foundations_now.get(found_key)
                    if found_key == "orderbook":  # FOUNDATION_ORDERBOOK
                        if (
                            isinstance(foundation_value_now, object)
                            and hasattr(foundation_value_now, "nearest_support")
                            and hasattr(foundation_value_now, "nearest_resistance")
                        ):  # Checking for OrderbookAnalysisResult
                            # For example, consider it completed if there is at least some info
                            if (
                                foundation_value_now.nearest_support
                                or foundation_value_now.nearest_resistance
                            ):
                                is_met_now = True
                    elif found_key == "pattern":  # FOUNDATION_PATTERN
                        is_met_now = (
                            foundations_now.get("pattern_detected", "None") != "None"
                        )
                    elif found_key == "trend":  # FOUNDATION_TREND
                        is_met_now = foundations_now.get(
                            "trend_detected", "None"
                        ) not in ["None", "FLAT"]
                    elif isinstance(foundation_value_now, bool):
                        is_met_now = foundation_value_now

                    if is_met_now:
                        current_foundation_weight_calculated += weight_pct

                logger.debug(
                    f"{log_prefix_recheck} Order {position_ref.entry_order_id}: InitialWeight={initial_foundation_weight:.1f}%, CurrentWeightCalculated={current_foundation_weight_calculated:.1f}%, Threshold={min_weight_threshold_config:.1f}%"
                )

                if current_foundation_weight_calculated < min_weight_threshold_config:
                    logger.info(
                        f"{log_prefix_recheck} Foundations for entry order {position_ref.entry_order_id} no longer valid "
                        f"(CurrentWeight: {current_foundation_weight_calculated:.1f}% < Threshold: {min_weight_threshold_config:.1f}%). InitialWeight was: {initial_foundation_weight:.1f}%. Cancelling."
                    )

                    # Cancellation block with re-check under lock
                    order_id_to_cancel_found = position_ref.entry_order_id
                    client_order_id_found = position_ref.entry_client_order_id
                    symbol_found = position_ref.symbol
                    strategy_found = position_ref.strategy

                    symbol_lock_recheck = self._get_lock_for_position(
                        symbol_found, self._market_type_for_position(position_ref)
                    )
                    async with symbol_lock_recheck:
                        async with self._positions_dict_lock:
                            pos_to_cancel_recheck = self._active_position_get(
                                symbol_found,
                                self._market_type_for_position(position_ref),
                            )
                            if (
                                pos_to_cancel_recheck
                                and pos_to_cancel_recheck.status == "PENDING_ENTRY"
                                and pos_to_cancel_recheck.entry_order_id
                                == order_id_to_cancel_found
                            ):
                                self._active_position_pop(
                                    symbol_found,
                                    self._market_type_for_position(position_ref),
                                )
                            else:
                                logger.warning(
                                    f"{log_prefix_recheck} Position {symbol_found} changed/removed during foundation recheck (weight check). Not cancelling order {order_id_to_cancel_found}."
                                )
                                continue  # Skipping cancellation if the position is no longer the same

                    executor_for_cancel = self._executor_for_market_type(
                        self._market_type_for_position(position_ref),
                        mode=position_ref.mode,
                    )
                    if not executor_for_cancel:
                        logger.error(
                            f"{log_prefix_recheck} Executor for market '{self._market_type_for_position(position_ref)}' not found. Cannot cancel pending entry."
                        )
                        continue
                    self.loop.create_task(
                        executor_for_cancel.cancel_order(
                            symbol=symbol_found, orderId=order_id_to_cancel_found
                        ),
                        name=f"CancelPendEntryFoundFail_{symbol_found}",
                    )
                    self.trade_logger.log_event(
                        event_type="ENTRY_ORDER_CANCELLED_FOUNDATIONS",
                        data={
                            "symbol": symbol_found,
                            "strategy": strategy_found,
                            "client_order_id": client_order_id_found,
                            "order_id": order_id_to_cancel_found,
                            "reason": f"Foundations no longer valid (Weight: {current_foundation_weight_calculated:.1f}% < {min_weight_threshold_config:.1f}%)",
                        },
                    )
                    self._last_position_close_time_per_symbol[
                        self._position_key(
                            symbol_found, self._market_type_for_position(position_ref)
                        )
                    ] = time.time()
                else:
                    logger.debug(
                        f"{log_prefix_recheck} Foundations for entry order {position_ref.entry_order_id} still valid."
                    )

        logger.debug(f"{log_prefix_main} Finished checking pending entry orders.")
