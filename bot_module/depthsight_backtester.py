# ruff: noqa: E402
# bot_module/depthsight_backtester.py
import asyncio
import logging
import time

import pandas as pd
import numpy as np
import msgpack
import zstandard
from pathlib import Path
from typing import Dict, Optional, Any, List, Tuple, Callable
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_UP, ROUND_DOWN
from collections import deque, defaultdict, OrderedDict
import random
import csv
import json
import os
import math
import functools

# Module component imports (from SimpleBacktester)
# Attempting to import pandas_ta
PANDAS_TA_AVAILABLE = False
try:
    import pandas_ta as ta

    PANDAS_TA_AVAILABLE = True
    logger_backtest_init = logging.getLogger("bot_module.backtester_init")
    logger_backtest_init.debug("pandas_ta library successfully imported.")
except ImportError:
    logger_backtest_init = logging.getLogger("bot_module.backtester_init")
    logger_backtest_init.warning(
        "Library 'pandas_ta' not found. Indicator pre-calculation will be limited."
    )
    ta = None

from bot_module import (
    config,
)
from .utils import (
    round_price_by_tick,
)
from .execution_simulator import (
    simulate_market_order_execution,
    OrderExecutionResult,
)
from .strategy import (
    STRATEGIES,
    create_strategy_instance,
    BaseStrategy,
)
from .ml_strategy import OnlineAgentStrategy
from .model_pipeline import ModelPipeline
from .feature_extractor import FeatureExtractor
from .risk_manager import RiskManager
from .datatypes import (
    BacktestPositionState,
    BtSymbolStrategyPerformanceStats,
    SignalDirection,
    OrderMode,
    StrategySignal,
)
import numba
from bot_module.oracle import Oracle

# Imports for DB operations (from DepthSightBacktester)
from sqlalchemy.orm import Session
import uuid

# Logging configuration
logger = logging.getLogger("bot_module.depthsight")  # Main logger
logger_backtest = logging.getLogger(
    "bot_module.depthsight.backtest"
)  # Nested for general backtest

if not logging.getLogger("bot_module").hasHandlers():
    logging.basicConfig(level=logging.INFO, format=config.LOG_FORMAT)
    logger.warning(
        "Root logger 'bot_module' has no handlers for DepthSight. Basic config applied."
    )


# Numba function (from SimpleBacktester)
@numba.jit(nopython=True)
def _get_ml_target_label_numba(
    klines_high_np, klines_low_np, start_idx, end_idx, sl_target, tp_target, is_long
):
    """Optimized version for Numba"""
    label = 0
    if start_idx + 1 > end_idx:
        return label
    if end_idx >= len(klines_high_np) or end_idx >= len(klines_low_np):
        return label

    for j in range(start_idx + 1, end_idx + 1):
        if j >= len(klines_high_np) or j >= len(klines_low_np):
            break

        future_high = klines_high_np[j]
        future_low = klines_low_np[j]

        if np.isnan(future_high) or np.isnan(future_low):
            continue

        if is_long:
            if future_low <= sl_target:
                label = 0
                break
            if future_high >= tp_target:
                label = 1
                break
        else:  # SHORT
            if future_high >= sl_target:
                label = 0
                break
            if future_low <= tp_target:
                label = 1
                break
    return label


# Constants for logging ML data (from SimpleBacktester)
FOUNDATION_KEYS = [
    "market_activity",
    "level",
    "pattern",
    "volume_confirmation",
    "orderbook",
    "trend",
    "round_number_level",
]
DETAIL_FEATURE_KEYS_TO_FLATTEN = [
    "signal_quality_score",
    "fake_breakout_score",
    "momentum_3",
    "rel_volume_spike_20",
    "volatility_spike_20",
    "body_pct",
    "wick_pct",
    "range_compression_20",
    "buyer_ratio_50",
    "volume_imbalance_50",
    "avg_trade_size_norm_50",
    "trade_rate_30s",
    "liquidity_shift_score_50",
    "agg_delta_10s",
    "agg_delta_30s",
    "agg_delta_1m",
    "time_since_last_signal_sec",
]
FIELDNAMES_ML_CONFIRMATION = (
    [
        "timestamp_signal",
        "timestamp_close",
        "client_order_id",
        "strategy",
        "symbol",
        "direction",
        "mode",
        "signal_trigger_price",
        "signal_entry_price",
        "signal_sl",
        "signal_tp",
        "actual_entry_price",
        "actual_exit_price",
        "avg_weighted_exit_price",
        "num_partial_tp_hits",
        "quantity",
        "pnl",
        "exit_reason",
        "commission",
        "y_true",
        "pattern_detected",
        "trend_detected",
    ]
    + [f"foundation_{f}" for f in FOUNDATION_KEYS]
    + [f"feature_{f}" for f in DETAIL_FEATURE_KEYS_TO_FLATTEN]
    + ["raw_features_json", "bt_ml_confirmed", "bt_ml_proba_1", "bt_ml_proba_0"]
)


def count_funding_periods(dt_start: datetime, dt_end: datetime) -> int:
    t_start = dt_start.astimezone(timezone.utc) if dt_start.tzinfo else dt_start.replace(tzinfo=timezone.utc)
    t_end = dt_end.astimezone(timezone.utc) if dt_end.tzinfo else dt_end.replace(tzinfo=timezone.utc)
    
    periods = 0
    t_curr = t_start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while t_curr <= t_end:
        if t_curr.hour % 8 == 0:
            if t_curr > t_start:
                periods += 1
        t_curr += timedelta(hours=1)
    return periods


def calculate_position_funding_pnl(executions: List[Dict[str, Any]], is_short: bool, funding_rate: float) -> float:
    if len(executions) < 2 or funding_rate == 0.0:
        return 0.0
        
    sorted_execs = sorted(executions, key=lambda x: x["timestamp"])
    total_funding_pnl_usd = 0.0
    current_qty = 0.0
    
    for idx in range(len(sorted_execs) - 1):
        exec_prev = sorted_execs[idx]
        exec_curr = sorted_execs[idx + 1]
        
        qty_change = float(exec_prev["quantity"])
        if exec_prev["type"] == "ENTRY":
            current_qty += qty_change
        elif exec_prev["type"] == "EXIT":
            current_qty -= qty_change
            
        if current_qty <= 1e-12:
            continue
            
        t_prev = exec_prev["timestamp"]
        t_curr = exec_curr["timestamp"]
        
        if isinstance(t_prev, str):
            t_prev_dt = pd.to_datetime(t_prev)
        else:
            t_prev_dt = t_prev
            
        if isinstance(t_curr, str):
            t_curr_dt = pd.to_datetime(t_curr)
        else:
            t_curr_dt = t_curr
            
        n_periods = count_funding_periods(t_prev_dt, t_curr_dt)
        if n_periods > 0:
            price = float(exec_prev["price"])
            position_value_usd = current_qty * price
            funding_multiplier = 1.0 if is_short else -1.0
            funding_pnl_usd = funding_multiplier * n_periods * position_value_usd * funding_rate
            total_funding_pnl_usd += funding_pnl_usd
            
    return total_funding_pnl_usd


class L2HistoricalDataReader:
    """
    Provides efficient access to historical L2 order book data.
    Reads compressed files and caches their content for fast lookup.
    """

    def __init__(self, storage_path: str):
        self.storage_path = Path(storage_path)
        if not self.storage_path.exists():
            logger.warning(f"L2 storage path does not exist: {self.storage_path}")
        self.cache_max_size = 20
        # Using OrderedDict to implement LRU cache
        self._file_records_cache: "OrderedDict[Path, List[Dict[str, Any]]]" = (
            OrderedDict()
        )
        self._cache_lock = asyncio.Lock()
        logger.info(
            f"L2HistoricalDataReader initialized. Storage path: {self.storage_path}"
        )

    def _get_l2_data_path(self, symbol: str, timestamp_ms: int) -> Path:
        dt_utc = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        symbol_safe = symbol.replace("/", "_").replace(":", "_")
        day_path = (
            self.storage_path / "binance" / symbol_safe / dt_utc.strftime("%Y/%m/%d")
        )
        filename = f"{dt_utc.strftime('%H')}-00-00.bin.zst"
        return day_path / filename

    async def _get_records_from_file(
        self, data_file_path: Path
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Unpacks the file and caches its content using LRU logic.
        """
        async with self._cache_lock:
            if data_file_path in self._file_records_cache:
                # Move the element to the end to mark it as "recently used"
                self._file_records_cache.move_to_end(data_file_path)
                logger.debug(f"L2 cache HIT for: {data_file_path}")
                return self._file_records_cache[data_file_path]

            if not data_file_path.exists():
                return None

            logger.info(
                f"L2 cache MISS. Decompressing and caching L2 data from: {data_file_path}"
            )
            try:
                dctx = zstandard.ZstdDecompressor()
                with open(data_file_path, "rb") as f_compressed:
                    with dctx.stream_reader(f_compressed) as reader:
                        records = list(msgpack.Unpacker(reader, raw=False))

                if records:
                    records.sort(key=lambda x: x.get("ts", 0))

                # Check cache size BEFORE adding a new element
                if len(self._file_records_cache) >= self.cache_max_size:
                    # Removing the oldest element (the first one)
                    oldest_path, _ = self._file_records_cache.popitem(last=False)
                    logger.debug(f"L2 cache full. Evicting oldest item: {oldest_path}")

                self._file_records_cache[data_file_path] = records
                logger.info(
                    f"Cached {len(records)} L2 records from {data_file_path}. Cache size: {len(self._file_records_cache)}/{self.cache_max_size}"
                )
                return records
            except Exception as e:
                logger.error(
                    f"Failed to read/decompress L2 file {data_file_path}: {e}",
                    exc_info=True,
                )
                # Do not cache the error so it can be retried
                return None

    async def get_book_snapshot_at(
        self, symbol: str, timestamp_ms: int
    ) -> Optional[Dict[str, Any]]:
        """Finds and returns the last order book snapshot before the specified time."""
        logger.debug(
            f"[{symbol}] L2HistoricalDataReader.get_book_snapshot_at called for ts {timestamp_ms}"
        )  # Changed to DEBUG
        data_file = self._get_l2_data_path(symbol, timestamp_ms)
        records = await self._get_records_from_file(data_file)

        if records is None:  # If the file is not found or there is a reading error
            return None

        last_valid_record = None
        # Simple linear search. For very large files, it can be optimized with binary search.
        for record in records:
            if record.get("ts", 0) <= timestamp_ms:
                last_valid_record = record
            else:
                # Since the records are sorted, we can stop as soon as we have passed the required timestamp
                break

        return last_valid_record


# MAIN BACKTESTER CLASS
class DepthSightBacktester:
    """
    A hybrid backtester that can work both with and without L2 data,
    and includes all the functionality of SimpleBacktester.
    """

    collect_data_mode: bool
    kline_data_array: Optional[np.ndarray]
    kline_index_map: Dict[str, int]
    backtest_trade_log_path: Optional[Path]
    actual_trading_start_dt: Optional[datetime]
    _log_ml_confirmation_data: bool
    _ml_confirmation_context_buffer: Dict[str, Any]
    _ml_confirmation_log_path: Optional[Path]
    _feature_extractor_instance: Optional[FeatureExtractor]
    _last_signal_timestamp_per_symbol_strategy: Dict[Tuple[str, str], float]
    y_true_min_move_pct: float
    y_true_max_drawdown_pct: float
    _ml_confirmation_pipeline: Optional[ModelPipeline]
    _ml_confirmation_feature_extractor: Optional[FeatureExtractor]
    _enable_ml_confirmation_backtest: bool
    oracle: Optional[Oracle]
    oracle_regime: Optional[int]
    oracle_confidence: Optional[float]

    # bot_module/depthsight_backtester.py

    def __init__(
        self,
        strategy_name: str,
        symbol: str,
        params: Dict[str, Any],
        historical_data: Dict[str, Optional[pd.DataFrame]],
        initial_balance: float,
        min_trades_required: int,
        risk_params: Dict[str, float],
        backtest_risk_params: Dict[str, float],
        execution_config: Dict[str, float],
        strategy_defaults: Dict[str, Dict[str, Any]],
        ml_training_config: Dict[str, Any],
        ml_sim_log_path: Optional[str],
        market_type: str = "futures_usdtm",
        min_foundation_weight_threshold: Optional[float] = None,
        backtest_log_config: Optional[Dict[str, Any]] = None,
        actual_trading_start_dt: Optional[datetime] = None,
        exchange_info: Optional[Dict[str, Any]] = None,
        ml_training_mode: bool = False,
        ml_agent_instance: Optional[OnlineAgentStrategy] = None,
        collect_data_mode: bool = False,
        log_ml_confirmation_data: bool = False,
        ml_confirmation_log_path: Optional[str] = None,
        y_true_min_move_pct: float = 0.15,
        y_true_max_drawdown_pct: float = 0.10,
        enable_ml_confirmation_backtest: bool = False,
        ml_confirmation_model_path_override: Optional[str] = None,
        _config_override: Optional[Any] = None,
        l2_reader: Optional[L2HistoricalDataReader] = None,
        l2_storage_path: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
        run_id: Optional[str] = None,
        db_session: Optional[Session] = None,
        strategy_json: Optional[Dict[str, Any]] = None,
        foundation_weights: Optional[Dict[str, float]] = None,
        include_eod_in_log: bool = False,
    ):
        if historical_data:
            loaded_keys_in_backtester = list(historical_data.keys())
            logger.info(
                f"LOG #3 [Backtester]: Backtester received historical_data with keys: {loaded_keys_in_backtester}"
            )
        else:
            logger.info(
                "LOG #3 [Backtester]: Backtester received EMPTY (None) historical_data!"
            )

        if self._is_visual_strategy_config(params):
            # Do not overwrite strategy_name for GeneticStrategy - it uses its own adapter
            if strategy_name != "GeneticStrategy":
                logger_backtest.info(
                    f"Visual strategy config detected. Overriding strategy_name from '{strategy_name}' to 'VisualBuilderStrategy'."
                )
                strategy_name = "VisualBuilderStrategy"

        self.config = _config_override if _config_override is not None else config
        self.strategy_name = strategy_name
        self.symbol = symbol
        self.params = params
        logger.info(f"DepthSightBacktester __init__: self.params = {self.params}")
        self.strategy_json = (
            strategy_json
            if strategy_json is not None
            else self.params.get("strategy_json")
        )
        if self.strategy_json and self.strategy_name == "GeneticStrategy":
            logger_backtest.info(
                f"Strategy JSON loaded for {self.strategy_name} on {self.symbol}."
            )

        self.market_type = market_type
        # Using self.config instead of global config
        self.min_total_foundation_weight_threshold = (
            min_foundation_weight_threshold
            if min_foundation_weight_threshold is not None
            else getattr(self.config, "MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD", 49.0)
        )
        self.foundation_weights = (
            foundation_weights
            if foundation_weights is not None
            else getattr(self.config, "FOUNDATION_WEIGHTS", {})
        )
        self.max_possible_l2_weight = self.foundation_weights.get("orderbook", 0.0)
        if not self.foundation_weights:
            logger.warning(
                "FOUNDATION_WEIGHTS not configured. Short-circuit optimization will be disabled."
            )

        self.historical_data = historical_data if historical_data is not None else {}
        self.initial_balance = initial_balance
        self.min_trades_required = min_trades_required
        self.risk_params = backtest_risk_params
        self.execution_config = execution_config
        self.exchange_info = exchange_info or {}
        self.strategy_defaults = strategy_defaults
        self.ml_training_mode = ml_training_mode
        self.ml_agent_instance = ml_agent_instance
        self.collect_data_mode = collect_data_mode
        self.include_eod_in_log = include_eod_in_log

        self.bt_strategy_symbol_adjustment_enabled: bool = self.risk_params.get(
            "strategySymbolAdjustmentEnabled", False
        )

        self.bt_strategy_symbol_window_size: int = self.risk_params.get(
            "strategySymbolWindowSize", 20
        )
        try:
            self.bt_strategy_symbol_window_size = int(
                self.bt_strategy_symbol_window_size
            )
        except ValueError:
            logger_backtest.warning(
                f"STRATEGY_SYMBOL_ROLLING_WINDOW_SIZE ('{self.bt_strategy_symbol_window_size}') is not a valid integer. Defaulting to 20."
            )
            self.bt_strategy_symbol_window_size = 20
        if self.bt_strategy_symbol_window_size <= 0:
            logger_backtest.warning(
                f"STRATEGY_SYMBOL_ROLLING_WINDOW_SIZE must be positive ({self.bt_strategy_symbol_window_size}). Defaulting to 20."
            )
            self.bt_strategy_symbol_window_size = 20
        self.bt_strategy_symbol_min_trades_assess: int = self.risk_params.get(
            "strategySymbolMinTradesForAssessment", 10
        )
        self.bt_strategy_symbol_pnl_thresh_pct: float = self.risk_params.get(
            "strategySymbolPnlThresholdPct", -0.1
        )
        self.bt_strategy_symbol_wr_thresh_pct: float = self.risk_params.get(
            "strategySymbolWinRateThresholdPct", 40.0
        )
        self.bt_strategy_symbol_max_consec_loss: int = self.risk_params.get(
            "strategySymbolMaxConsecutiveLosses", 3
        )
        # Note: risk_params does not contain a list for multipliers, so we'll keep the global config default for now
        self.bt_strategy_symbol_risk_multipliers: List[float] = getattr(
            self.config, "STRATEGY_SYMBOL_RISK_MULTIPLIERS", [1.0, 0.75, 0.5, 0.25, 0.0]
        )
        self.bt_strategy_symbol_rec_consec_wins: int = self.risk_params.get(
            "strategySymbolRecoveryConsecutiveWins", 2
        )
        self.bt_strategy_symbol_rec_pnl_thresh_pct: float = self.risk_params.get(
            "strategySymbolRecoveryPnlThresholdPct", 1.0
        )
        self.bt_strategy_symbol_cooldown_penalty_sec: int = self.risk_params.get(
            "strategySymbolCooldownAfterPenaltySeconds", 60 * 60 * 1
        )
        self.bt_strategy_symbol_adjustment_enabled_for_backtest: bool = (
            self.risk_params.get("strategySymbolAdjustmentEnabledForBacktest", False)
        )

        self._bt_symbol_strategy_performance: Dict[
            Tuple[str, str], BtSymbolStrategyPerformanceStats
        ] = defaultdict(
            lambda: BtSymbolStrategyPerformanceStats(
                trade_results_buffer=deque(maxlen=self.bt_strategy_symbol_window_size)
            )
        )
        if self.bt_strategy_symbol_adjustment_enabled:
            logger_backtest.info(
                "Backtester: Strategy-Symbol dynamic risk adjustment ENABLED."
            )

        self._enable_ml_confirmation_backtest = (
            enable_ml_confirmation_backtest if not self.ml_training_mode else False
        )
        if self._enable_ml_confirmation_backtest:
            logger_backtest.info("ML Confirmation for backtest ENABLED.")
            try:
                self._ml_confirmation_feature_extractor = FeatureExtractor()
                conf_model_path_str = ml_confirmation_model_path_override or getattr(
                    self.config, "ML_CONFIRMATION_MODEL_PATH", None
                )
                if conf_model_path_str:
                    conf_model_path = Path(conf_model_path_str)
                    self._ml_confirmation_pipeline = ModelPipeline(
                        model_path=conf_model_path
                    )
                    if self._ml_confirmation_pipeline.load_model(conf_model_path):
                        if (
                            self._ml_confirmation_feature_extractor
                            and self._ml_confirmation_pipeline.active_features
                        ):
                            self._ml_confirmation_feature_extractor.set_active_features(
                                self._ml_confirmation_pipeline.active_features
                            )
                    else:
                        self._enable_ml_confirmation_backtest = False
                else:
                    self._enable_ml_confirmation_backtest = False
            except Exception as e_conf_init:
                logger_backtest.error(
                    f"Error initializing ML confirmation components: {e_conf_init}. Confirmation disabled.",
                    exc_info=True,
                )
                self._enable_ml_confirmation_backtest = False

        self.actual_trading_start_dt = actual_trading_start_dt
        self._last_signal_timestamp_per_symbol_strategy = {}
        self.y_true_min_move_pct = y_true_min_move_pct
        self.y_true_max_drawdown_pct = y_true_max_drawdown_pct

        self._backtest_save_trades = False
        self.backtest_trade_log_path = None
        if (
            backtest_log_config
            and isinstance(backtest_log_config, dict)
            and not self.ml_training_mode
        ):
            self._backtest_save_trades = backtest_log_config.get("save_trades", False)
            log_path_template = backtest_log_config.get("log_path_template")
            if self._backtest_save_trades and log_path_template:
                try:
                    ts_str = datetime.now().strftime("%Y%m%d%H%M%S")
                    filename = f"{log_path_template}".format(
                        strategy=self.strategy_name,
                        symbol=self.symbol,
                        timestamp=ts_str,
                    )
                    self.backtest_trade_log_path = Path(filename)
                except KeyError as e:
                    logger_backtest.error(
                        f"Invalid log_path_template '{log_path_template}'. Missing key: {e}"
                    )
                    self._backtest_save_trades = False
                except Exception as e_path:
                    logger_backtest.error(
                        f"Error formatting backtest log path: {e_path}"
                    )
                    self._backtest_save_trades = False
            elif self._backtest_save_trades:
                logger_backtest.warning(
                    "Backtest trade saving enabled, but 'log_path_template' is missing in config. Logging disabled."
                )
                self._backtest_save_trades = False

        self._log_ml_confirmation_data = (
            log_ml_confirmation_data if not self.ml_training_mode else False
        )
        self._ml_confirmation_context_buffer = {}
        self._ml_confirmation_log_path = None
        self._ml_confirmation_header_written = False

        if self._log_ml_confirmation_data and ml_confirmation_log_path:
            self._ml_confirmation_log_path = Path(ml_confirmation_log_path)
            try:
                self._feature_extractor_instance = FeatureExtractor()
            except Exception as e_fe_init:
                logger_backtest.error(
                    f"Failed to initialize FeatureExtractor for ML logging: {e_fe_init}. Logging disabled."
                )
                self._log_ml_confirmation_data = False
            if self._log_ml_confirmation_data:
                self._ensure_ml_confirmation_file_header()
        elif self._log_ml_confirmation_data:
            logger_backtest.warning(
                "ML Confirmation Data logging enabled, but 'ml_confirmation_log_path' is missing. Logging disabled."
            )
            self._log_ml_confirmation_data = False

        if ml_training_config is None:
            ml_training_config = {}

        self._ml_label_lookahead = ml_training_config.get(
            "ML_TRAINING_LABEL_LOOKAHEAD_BARS", 15
        )
        self._ml_simulate_trades = ml_training_config.get(
            "ML_TRAINING_SIMULATE_TRADES", True
        )
        self._ml_simulated_trade_log: List[Dict[str, Any]] = []
        self._ml_simulated_trades_log_path: Optional[Path] = (
            Path(ml_sim_log_path) if ml_sim_log_path else None
        )

        self.candle_tf = "1m"
        try:
            if self.ml_training_mode and self.ml_agent_instance:
                self.candle_tf = self.ml_agent_instance.candle_timeframe
            else:
                strat_defaults_local = self.strategy_defaults.get(strategy_name, {})
                self.candle_tf = params.get(
                    "candle_timeframe",
                    params.get(
                        "entry_timeframe",
                        strat_defaults_local.get(
                            "candle_timeframe",
                            strat_defaults_local.get("entry_timeframe", "1m"),
                        ),
                    ),
                )
            kline_key = f"kline_{self.candle_tf}"
        except Exception as e_tf:
            logger_backtest.error(
                f"Error determining main candle timeframe: {e_tf}. Falling back to '1m'."
            )
            self.candle_tf = "1m"
            kline_key = "kline_1m"

        kline_df_original = self.historical_data.get(kline_key)
        if kline_df_original is None or not isinstance(kline_df_original, pd.DataFrame):
            logger_backtest.error(
                f"Kline data for timeframe '{self.candle_tf}' not found or invalid in historical_data."
            )
            self.klines = pd.DataFrame()
        else:
            self.klines = kline_df_original.copy()
        if not self.klines.empty:
            if (
                not isinstance(self.klines.index, pd.DatetimeIndex)
                or self.klines.index.tz is None
            ):
                try:
                    self.klines.index = pd.to_datetime(self.klines.index, utc=True)
                except Exception as e:
                    logger_backtest.error(
                        f"Failed to convert kline index: {e}. Clearing klines DataFrame."
                    )
                    self.klines = pd.DataFrame()
            if not self.klines.empty:
                if not self.klines.index.is_monotonic_increasing:
                    self.klines.sort_index(inplace=True)
                num_cols = ["open", "high", "low", "close", "volume"]
                for col in num_cols:
                    if col in self.klines.columns:
                        if not pd.api.types.is_numeric_dtype(self.klines[col]):
                            self.klines.loc[:, col] = pd.to_numeric(
                                self.klines[col], errors="coerce"
                            )
                self.klines.dropna(subset=num_cols, inplace=True)

        rolling_period_for_max_min = 20
        high_col, low_col = "high", "low"
        if not self.klines.empty and all(
            c in self.klines.columns for c in [high_col, low_col]
        ):
            self.klines[f"rolling_high_{rolling_period_for_max_min}"] = (
                self.klines[high_col]
                .rolling(
                    window=rolling_period_for_max_min,
                    min_periods=rolling_period_for_max_min,
                )
                .max()
            )
            self.klines[f"rolling_low_{rolling_period_for_max_min}"] = (
                self.klines[low_col]
                .rolling(
                    window=rolling_period_for_max_min,
                    min_periods=rolling_period_for_max_min,
                )
                .min()
            )
            self.klines["candle_range"] = self.klines[high_col] - self.klines[low_col]
            self.klines["candle_range"] = self.klines["candle_range"].apply(
                lambda x: max(0.0, x)
            )
            self.klines[f"rolling_max_range_{rolling_period_for_max_min}"] = (
                self.klines["candle_range"]
                .rolling(
                    window=rolling_period_for_max_min,
                    min_periods=rolling_period_for_max_min,
                )
                .max()
            )
            cols_to_fill = [
                f"rolling_high_{rolling_period_for_max_min}",
                f"rolling_low_{rolling_period_for_max_min}",
                f"rolling_max_range_{rolling_period_for_max_min}",
            ]
            for col in cols_to_fill:
                if col in self.klines.columns:
                    self.klines[col] = self.klines[col].bfill().ffill().fillna(0.0)

        self.required_indicators: Dict[str, Dict] = {}
        self.atr_period = 14
        if not self.klines.empty:
            self.required_indicators = self._get_required_indicators(
                strategy_name, params, self.strategy_defaults
            )
            self.atr_period = self._get_atr_period(strategy_name, params)
            atr_col_name = f"ATR_{self.atr_period}"
            if PANDAS_TA_AVAILABLE:
                try:
                    atr_series = ta.atr(
                        high=self.klines["high"],
                        low=self.klines["low"],
                        close=self.klines["close"],
                        length=self.atr_period,
                        mamode="rma",
                    )
                    if atr_series is not None:
                        atr_series = atr_series.bfill().ffill().fillna(0.0)
                        atr_series[atr_series <= 1e-9] = 1e-9
                        self.klines[atr_col_name] = atr_series

                    macd = ta.macd(
                        close=self.klines["close"], fast=12, slow=26, signal=9
                    )
                    if macd is not None and not macd.empty:
                        self.klines["MACD_12_26_9"] = macd["MACD_12_26_9"]
                        self.klines["MACD_signal_12_26_9"] = macd["MACDs_12_26_9"]
                        self.klines["MACD_hist_12_26_9"] = macd["MACDh_12_26_9"]

                    bbands = ta.bbands(close=self.klines["close"], length=20, std=2)
                    if bbands is not None and not bbands.empty:
                        # Dynamically search for required columns without relying on the exact name
                        upper_col = next(
                            (col for col in bbands.columns if col.startswith("BBU_")),
                            None,
                        )
                        middle_col = next(
                            (col for col in bbands.columns if col.startswith("BBM_")),
                            None,
                        )
                        lower_col = next(
                            (col for col in bbands.columns if col.startswith("BBL_")),
                            None,
                        )

                        if upper_col and middle_col and lower_col:
                            self.klines["BB_upper_20_2"] = bbands[upper_col]
                            self.klines["BB_middle_20_2"] = bbands[middle_col]
                            self.klines["BB_lower_20_2"] = bbands[lower_col]

                            bbm = self.klines["BB_middle_20_2"]
                            self.klines["BBW_20_2"] = np.where(
                                bbm > 1e-9,
                                (
                                    self.klines["BB_upper_20_2"]
                                    - self.klines["BB_lower_20_2"]
                                )
                                / bbm,
                                0.0,
                            )
                        else:
                            logger_backtest.error(
                                f"Failed to find Bollinger Bands columns in pandas_ta output. Available columns: {list(bbands.columns)}"
                            )

                    stoch = ta.stoch(
                        high=self.klines["high"],
                        low=self.klines["low"],
                        close=self.klines["close"],
                        k=14,
                        d=3,
                        smooth_k=3,
                    )
                    if stoch is not None and not stoch.empty:
                        self.klines["STOCH_k_14_3_3"] = stoch["STOCHk_14_3_3"]
                        self.klines["STOCH_d_14_3_3"] = stoch["STOCHd_14_3_3"]

                    adx = ta.adx(
                        high=self.klines["high"],
                        low=self.klines["low"],
                        close=self.klines["close"],
                        length=14,
                    )
                    if adx is not None and not adx.empty:
                        self.klines["ADX_14"] = adx["ADX_14"]
                except Exception as e_atr:
                    logger_backtest.error(
                        f"Error pre-calculating {atr_col_name}: {e_atr}", exc_info=True
                    )
                    self.klines[atr_col_name] = 1e-9
            else:
                self.klines[atr_col_name] = 1e-9

            if PANDAS_TA_AVAILABLE and self.required_indicators:
                indicators_by_df: Dict[str, Dict[str, Dict]] = defaultdict(dict)
                for name, cfg_ind_loop in self.required_indicators.items():
                    df_key = cfg_ind_loop.get("dataframe_key")
                    if df_key:
                        indicators_by_df[df_key][name] = cfg_ind_loop
                for df_key, indicators_to_calc in indicators_by_df.items():
                    target_df_orig = self.historical_data.get(df_key)
                    if target_df_orig is None or target_df_orig.empty:
                        for name in indicators_to_calc:
                            self.klines[name] = 0.0
                        continue
                    df_for_calc = target_df_orig.copy()
                    ohlcv_cols = ["open", "high", "low", "close", "volume"]
                    for col in ohlcv_cols:
                        if col in df_for_calc.columns:
                            if not pd.api.types.is_numeric_dtype(df_for_calc[col]):
                                df_for_calc[col] = pd.to_numeric(
                                    df_for_calc[col], errors="coerce"
                                )
                    df_for_calc.dropna(subset=ohlcv_cols, inplace=True)
                    if df_for_calc.empty:
                        for name in indicators_to_calc:
                            self.klines[name] = 0.0
                        continue
                    for name, indicator_cfg in indicators_to_calc.items():
                        try:
                            indicator_series = None
                            period = indicator_cfg.get("period")
                            if not period:
                                self.klines[name] = 0.0
                                continue
                            if name.startswith("EMA_"):
                                if period:
                                    indicator_series = df_for_calc.ta.ema(length=period)
                            elif name.startswith("SMA_"):
                                if period:
                                    indicator_series = df_for_calc.ta.sma(length=period)
                            elif name.startswith("RSI_"):
                                if period:
                                    indicator_series = df_for_calc.ta.rsi(length=period)
                            elif name.startswith("NATR_"):
                                if period:
                                    percent_range = (
                                        (df_for_calc["high"] - df_for_calc["low"])
                                        / df_for_calc["close"].replace(0, 1)
                                        * 100
                                    )
                                    indicator_series = percent_range.rolling(
                                        window=period
                                    ).mean()
                            elif name.startswith("ADX_"):
                                if period:
                                    adx_df = df_for_calc.ta.adx(length=period)
                                    if adx_df is not None and not adx_df.empty:
                                        indicator_series = adx_df.iloc[:, 0]
                            elif name.startswith("STOCHk_"):
                                parts = name.split("_")
                                if len(parts) >= 4:
                                    k, d, s = (
                                        int(parts[1]),
                                        int(parts[2]),
                                        int(parts[3]),
                                    )
                                    stoch_df = df_for_calc.ta.stoch(
                                        k=k, d=d, smooth_k=s
                                    )
                                    if stoch_df is not None:
                                        indicator_series = stoch_df.iloc[:, 0]
                            elif name.startswith("STOCHd_"):
                                parts = name.split("_")
                                if len(parts) >= 4:
                                    k, d, s = (
                                        int(parts[1]),
                                        int(parts[2]),
                                        int(parts[3]),
                                    )
                                    stoch_df = df_for_calc.ta.stoch(
                                        k=k, d=d, smooth_k=s
                                    )
                                    if stoch_df is not None:
                                        indicator_series = stoch_df.iloc[:, 1]
                            elif (
                                name.startswith("BBL_")
                                or name.startswith("BBU_")
                                or name.startswith("BBB_")
                            ):
                                parts = name.split("_")
                                if len(parts) >= 3:
                                    p, std = int(parts[1]), float(parts[2])
                                    bb_df = df_for_calc.ta.bbands(length=p, std=std)
                                    if bb_df is not None:
                                        if name.startswith("BBL_"):
                                            indicator_series = bb_df.iloc[:, 0]
                                        elif name.startswith("BBU_"):
                                            indicator_series = bb_df.iloc[:, 2]
                                        elif name.startswith("BBB_"):
                                            indicator_series = bb_df.iloc[:, 3]
                            elif name.startswith("MACD"):
                                parts = name.split("_")
                                if len(parts) >= 4:
                                    f, s, sig = (
                                        int(parts[1]),
                                        int(parts[2]),
                                        int(parts[3]),
                                    )
                                    macd_df = df_for_calc.ta.macd(
                                        fast=f, slow=s, signal=sig
                                    )
                                    if macd_df is not None:
                                        if "MACDs" in name:
                                            indicator_series = macd_df.iloc[:, 2]
                                        elif "MACDh" in name or "MACD_hist" in name:
                                            indicator_series = macd_df.iloc[:, 1]
                                        else:
                                            indicator_series = macd_df.iloc[:, 0]
                            if indicator_series is not None:
                                indicator_series = (
                                    indicator_series.bfill().ffill().fillna(0.0)
                                )
                                self.klines[name] = indicator_series.reindex(
                                    self.klines.index, method="ffill"
                                ).fillna(0.0)
                            else:
                                self.klines[name] = 0.0
                        except Exception as e_ind:
                            logger_backtest.error(
                                f"Error pre-calculating {name} on {df_key}: {e_ind}",
                                exc_info=True,
                            )
                            self.klines[name] = 0.0
            elif self.required_indicators:
                for name in self.required_indicators:
                    self.klines[name] = 0.0

        self.current_balance = initial_balance
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.pending_orders: Dict[str, Dict[str, Any]] = {}
        self.trade_log: List[Dict[str, Any]] = []
        self.equity_curve = []
        initial_equity_ts = None
        if not self.klines.empty:
            if self.actual_trading_start_dt:
                try:
                    start_dt_utc_eq = (
                        self.actual_trading_start_dt.astimezone(timezone.utc)
                        if self.actual_trading_start_dt.tzinfo
                        else self.actual_trading_start_dt.replace(tzinfo=timezone.utc)
                    )
                    start_mask = self.klines.index >= start_dt_utc_eq
                    if start_mask.any():
                        initial_equity_ts = self.klines.index[start_mask][
                            0
                        ].to_pydatetime()
                    else:
                        initial_equity_ts = self.klines.index[-1].to_pydatetime()
                except Exception:
                    initial_equity_ts = self.klines.index[0].to_pydatetime()
            else:
                initial_equity_ts = self.klines.index[0].to_pydatetime()
            if initial_equity_ts:
                self.equity_curve = [(initial_equity_ts, self.initial_balance)]

        self.stats: Dict[str, Any] = {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "total_commission": 0.0,
            "max_drawdown": 0.0,
            "peak_equity": initial_balance,
            "consecutive_losses": 0,
            "max_consecutive_losses": 0,
            "daily_pnl": defaultdict(float),
            "start_of_day_balance": initial_balance,
            "current_day_start_ts": 0.0,
            "last_known_day_str": "",
            "number_of_entries": 0,
        }
        self.is_trading_allowed = True
        self._is_liquidated = False  # Liquidation is an irreversible state

        self.strategy_instance: Optional[BaseStrategy] = None
        if not self.ml_training_mode:
            self.strategy_instance = self._initialize_strategy()
        elif self.ml_agent_instance is None and not self.collect_data_mode:
            logger_backtest.critical(
                "ML Training mode enabled, but no ml_agent_instance provided!"
            )

        self.agg_trades: Optional[pd.DataFrame] = self.historical_data.get("aggTrade")
        if self.agg_trades is not None:
            if (
                not isinstance(self.agg_trades.index, pd.DatetimeIndex)
                or self.agg_trades.index.tz is None
            ):
                try:
                    self.agg_trades.index = pd.to_datetime(
                        self.agg_trades.index, utc=True
                    )
                except Exception as e:
                    logger_backtest.error(
                        f"Failed to convert agg_trades index: {e}. Ignoring aggTrades."
                    )
                    self.agg_trades = None
            if (
                self.agg_trades is not None
                and not self.agg_trades.index.is_monotonic_increasing
            ):
                self.agg_trades.sort_index(inplace=True)

        self.open_interest: Optional[pd.DataFrame] = self.historical_data.get(
            "open_interest"
        )
        if self.open_interest is not None:
            if (
                not isinstance(self.open_interest.index, pd.DatetimeIndex)
                or self.open_interest.index.tz is None
            ):
                try:
                    self.open_interest.index = pd.to_datetime(
                        self.open_interest.index, utc=True
                    )
                except Exception as e:
                    logger_backtest.error(
                        f"Failed to convert open_interest index: {e}. Ignoring Open Interest."
                    )
                    self.open_interest = None
            if (
                self.open_interest is not None
                and not self.open_interest.index.is_monotonic_increasing
            ):
                self.open_interest.sort_index(inplace=True)

        self._bt_last_position_close_time_per_symbol: Dict[str, float] = {}
        self._bt_symbol_cooldown_duration: float = getattr(
            self.config, "SYMBOL_COOLDOWN_SECONDS", 300.0
        )

        if self.klines is not None and not self.klines.empty:
            # 1. Main columns
            kline_cols_needed_init = [
                "open",
                "high",
                "low",
                "close",
                "volume",
                "positive",
                "negative",
                "important",
            ]

            # 2. Indicators requested by the strategy
            indicator_cols_init = list(self.required_indicators.keys())
            atr_col_name_init = f"ATR_{self.atr_period}"

            # 3. Custom indicators
            custom_indicator_cols = [
                "natr",
                "relative_volume",
                "is_volume_spike",
                "volume_percentile_threshold",
            ]

            # 4. Tape features
            tape_feature_cols = [
                col for col in self.klines.columns if col.startswith("tape_")
            ]

            # 5. Adding all standard indicators that are always calculated
            standard_indicator_cols = [
                "MACD_12_26_9",
                "MACD_signal_12_26_9",
                "MACD_hist_12_26_9",
                "BB_upper_20_2",
                "BB_middle_20_2",
                "BB_lower_20_2",
                "BBW_20_2",
                "STOCH_k_14_3_3",
                "STOCH_d_14_3_3",
                "ADX_14",
            ]

            # 6. Collect ALL desired columns into one large set
            all_desired_cols = set(
                kline_cols_needed_init
                + indicator_cols_init
                + [atr_col_name_init]
                + custom_indicator_cols
                + tape_feature_cols
                + standard_indicator_cols
            )

            self.oracle: Optional[Oracle] = None
            self.oracle_regime: Optional[int] = None
            self.oracle_confidence: Optional[float] = None

            # Smart search for Oracle parameters
            params_source = (
                self.params.get("config", self.params) if self.params else {}
            )

            if (
                "oracle_regime" in params_source
                and params_source["oracle_regime"] is not None
            ):
                self.oracle_regime = params_source["oracle_regime"]
                self.oracle_confidence = params_source.get("oracle_confidence", 0.0)
                logger_backtest.info(
                    f"Oracle parameters found: Regime={self.oracle_regime}, Confidence={self.oracle_confidence}. Initializing..."
                )
                try:
                    model_path_str = getattr(
                        self.config, "ORACLE_MODEL_PATH", "oracle_model.joblib"
                    )
                    model_path = Path(model_path_str)

                    if not model_path.exists():
                        logger_backtest.critical(
                            f"Oracle model file '{model_path}' not found. Oracle filter will be DEACTIVATED."
                        )
                        self.oracle = None
                        self.oracle_regime = None
                    else:
                        self.oracle = Oracle(model_path=model_path)
                        logger_backtest.info(
                            f"Oracle initialized successfully from '{model_path}'."
                        )

                except Exception as e:
                    logger_backtest.critical(
                        f"Error initializing Oracle: {e}. Oracle filter will be DEACTIVATED.",
                        exc_info=True,
                    )
                    self.oracle = None
                    self.oracle_regime = None
            else:
                logger_backtest.info(
                    "Oracle parameters not found in strategy config. Oracle filter is INACTIVE."
                )

            # Improved column check
            if self.oracle:
                missing_oracle_cols = [
                    col
                    for col in ["positive", "negative", "important"]
                    if col not in self.klines.columns
                ]
                if missing_oracle_cols:
                    logger_backtest.warning(
                        f"Oracle is active, but these sentiment columns are missing in klines: {', '.join(missing_oracle_cols)}. "
                        f"Oracle will function with neutral sentiment (sensor_news = 0)."
                    )
            # 7. Select only those desired columns that ACTUALLY exist in self.klines
            final_cols_to_use = [
                col for col in self.klines.columns if col in all_desired_cols
            ]

            # 8. Create an array and index map based on this final, correct list
            if final_cols_to_use:
                try:
                    self.kline_data_array = self.klines[final_cols_to_use].to_numpy(
                        dtype=np.float64
                    )
                    self.kline_index_map = {
                        col: idx for idx, col in enumerate(final_cols_to_use)
                    }
                    logger.info(
                        f"Successfully created kline_data_array with columns: {final_cols_to_use}"
                    )
                except Exception as e_numpy_init:
                    logger.error(
                        f"Error creating kline_data_array: {e_numpy_init}",
                        exc_info=True,
                    )
                    self.kline_data_array = None
                    self.kline_index_map = {}
            else:
                logger.error("No suitable columns found to create kline_data_array.")
                self.kline_data_array = None
                self.kline_index_map = {}
        else:
            self.kline_data_array = None
            self.kline_index_map = {}

        if self.kline_data_array is None and not self.klines.empty:
            if all(
                c in self.klines.columns
                for c in ["open", "high", "low", "close", "volume"]
            ):
                _cols_to_cache_fallback = [
                    c
                    for c in ["open", "high", "low", "close", "volume"]
                    if c in self.klines.columns
                ]
                _atr_col_fb = f"ATR_{self.atr_period}"
                if _atr_col_fb in self.klines.columns:
                    _cols_to_cache_fallback.append(_atr_col_fb)
                _cols_to_cache_fallback.extend(
                    [
                        ind_col
                        for ind_col in self.required_indicators
                        if ind_col in self.klines.columns
                    ]
                )
                _final_cols_fb = list(dict.fromkeys(_cols_to_cache_fallback))
                if _final_cols_fb:
                    try:
                        self.kline_data_array = self.klines[_final_cols_fb].to_numpy(
                            dtype=np.float64
                        )
                        self.kline_index_map = {
                            col: idx for idx, col in enumerate(_final_cols_fb)
                        }
                    except Exception as e_fb_init:
                        logger_backtest.error(
                            f"Fallback kline_data_array init failed: {e_fb_init}"
                        )

        if self.kline_index_map:
            logger.critical(
                f"--- DIAGNOSTICS: Final columns in kline_data_array: {list(self.kline_index_map.keys())}"
            )
        else:
            logger.critical(
                "--- DIAGNOSTICS: kline_data_array or kline_index_map is EMPTY!"
            )

        self.progress_callback = progress_callback
        self.progress_meta: Dict[str, Any] = {"events": [], "kpis": {}}
        self.last_progress_update_time = 0.0

        self.l2_reader: Optional[L2HistoricalDataReader] = l2_reader
        if self.l2_reader is None and l2_storage_path:
            logger.info(
                f"No L2Reader provided, but l2_storage_path '{l2_storage_path}' is set. Initializing L2HistoricalDataReader."
            )
            self.l2_reader = L2HistoricalDataReader(storage_path=l2_storage_path)

        self.l2_market_impact_enabled: bool = self.l2_reader is not None

        # START: RiskManager Integration
        class MockExecutor:
            def __init__(self, backtester_instance):
                self._backtester = backtester_instance

            async def get_account_balance(self):
                # Return the current balance from the backtester instance
                return {"USDT": {"free": self._backtester.current_balance, "locked": 0}}

        # Create a mock executor instance
        mock_executor = MockExecutor(self)

        # Create a RiskManager instance
        self.rm = RiskManager(
            executor=mock_executor,
            paper_executor=mock_executor,
            user_id=None,  # Not needed for backtesting
            db_session=None,  # Not needed for backtesting
            user_settings={"risk_management": self.risk_params},
        )
        #  END: RiskManager Integration

        self.l2_data_cache: Optional[Dict[str, Any]] = None
        if self.l2_market_impact_enabled:
            logger.info(
                "L2 Market Impact is enabled, initializing L2 data cache for real-time updates."
            )
            self.l2_data_cache = {
                "best_bid": 0.0,
                "best_ask": 0.0,
                "last_update_time": 0,
                "depth_data": None,
            }

        if self.l2_market_impact_enabled:
            l2_source = (
                "provided instance"
                if l2_reader and self.l2_reader is l2_reader
                else f"path '{l2_storage_path}'"
            )
            logger.info(
                f"DepthSightBacktester: L2 Market Impact simulation is ACTIVE. L2Reader source: {l2_source}"
            )
        else:
            logger.info(
                "DepthSightBacktester: L2 Market Impact simulation is INACTIVE (no L2Reader or path)."
            )

        self.run_id = run_id
        self.db_session = db_session

        self._latest_closed_trade_for_report: Optional[Dict[str, Any]] = None
        self._latest_equity_point_for_report: Optional[Tuple[datetime, float]] = None

        self._i_current_candle: int = 0
        self._timestamp_dt_current_candle: Optional[datetime] = None

        if self.run_id and not self.db_session:
            raise ValueError("db_session must be provided if run_id is specified.")

        self.structured_report = {
            "event_counters": {
                "signals_generated_total": 0,
                "foundation_trigger_counts": {},
                "rejections": {
                    "by_global_risk_limit": 0,
                    "by_cooldown": 0,
                    "by_filter": {},
                    "by_weight_threshold": 0,
                    "by_position_calculation": 0,
                    "by_slippage_beyond_sl": 0,
                    "by_risk_manager": 0,
                    "by_risk_manager_reasons": {},
                },
                "trades_opened": 0,
                "errors": {},
            },
            "anomalies": [],
        }
        if self.foundation_weights:
            for foundation_id in self.foundation_weights.keys():
                self.structured_report["event_counters"]["foundation_trigger_counts"][
                    foundation_id
                ] = 0

    @staticmethod
    def _extract_strategy_config(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(params, dict):
            return {}
        nested_config = params.get("config")
        if isinstance(nested_config, dict):
            return nested_config
        return params

    @classmethod
    def _is_visual_strategy_config(cls, params: Optional[Dict[str, Any]]) -> bool:
        strategy_config = cls._extract_strategy_config(params)
        visual_keys = {
            "entryConditions",
            "filters",
            "initialization",
            "positionManagement",
            "conditions",
        }
        return any(key in strategy_config for key in visual_keys)

    def _initialize_strategy(self) -> Optional[BaseStrategy]:
        params_from_backtester = self.params.copy() if self.params is not None else {}

        strategy_name_to_use = (
            self.strategy_name
        )  # Starting with the name passed to the backtester

        # Check that this is indeed a strategy from the editor,
        # and not just a classic strategy, whose parameters also reside in 'config'.
        # Key difference - presence of 'entryConditions' or 'filters'.
        config_dict = self._extract_strategy_config(params_from_backtester)
        if self._is_visual_strategy_config(params_from_backtester):
            # If editor-specific keys are found, force use of VisualBuilderStrategy
            # BUT: do not overwrite for GeneticStrategy - it uses its own adapter
            if self.strategy_name not in ("VisualBuilderStrategy", "GeneticStrategy"):
                logger_backtest.info(
                    f"Visual strategy JSON detected. Overriding strategy_name from '{self.strategy_name}' to 'VisualBuilderStrategy'."
                )
                strategy_name_to_use = "VisualBuilderStrategy"

        # This code block remains, but now it will work with the correct strategy_name_to_use
        params_for_instance = params_from_backtester
        params_for_instance["enabled"] = True
        params_for_instance["min_total_foundation_weight_threshold"] = (
            self.min_total_foundation_weight_threshold
        )
        params_for_instance["foundation_weights"] = self.foundation_weights
        if (
            self._is_visual_strategy_config(params_for_instance)
            and "config" not in params_for_instance
        ):
            params_for_instance["config"] = config_dict.copy()

        logger.info(
            f"Final params for instance creation: {json.dumps(params_for_instance, indent=2)}"
        )

        # GeneticStrategy now uses its own adapter registered in STRATEGIES
        instance = create_strategy_instance(
            strategy_name_to_use, params=params_for_instance
        )

        if instance:
            logger.info(
                f"After strategy creation: instance.enabled = {instance.enabled}, instance.foundation_weights = {instance.foundation_weights}"
            )
        else:
            logger_backtest.error(
                f"Could not get instance for strategy: {strategy_name_to_use} on {self.symbol}"
            )

        return instance

    def _count_foundation_triggers_from_trace(self, trace_node: Dict, counts: Dict):
        """
        Recursively traverses the trace tree and increments counters for all
        weighted bases (ID starts with 'w_') where result: True.
        """
        if not isinstance(trace_node, dict):
            return

        node_id = trace_node.get("id")
        node_result = trace_node.get("result")

        # Main logic: if the node is a weighted base and it triggered
        if node_id and node_id.startswith("w_") and node_result is True:
            counts.setdefault(node_id, 0)
            counts[node_id] += 1

        # Recursively calling for child nodes
        for child in trace_node.get("children", []):
            self._count_foundation_triggers_from_trace(child, counts)

    def _calculate_y_true_trade_quality(
        self, position: Dict[str, Any], exit_timestamp_dt: datetime
    ) -> int:
        try:
            entry_price = position.get("entry_price")
            entry_time_dt = position.get("entry_time")
            direction = position.get("direction")
            exit_reason = position.get("exit_reason")
            if entry_price is None or entry_time_dt is None or direction is None:
                return 0
            exit_timestamp_buffered = exit_timestamp_dt + timedelta(seconds=1)
            kline_slice_df = self.klines[
                (self.klines.index > entry_time_dt)
                & (self.klines.index <= exit_timestamp_buffered)
            ]
            if kline_slice_df.empty:
                return 1 if position.get("pnl", 0) > 0 else 0
            move_in_favor_pct = 0.0
            drawdown_pct = 0.0
            entry_p_float = float(entry_price)
            if direction == SignalDirection.LONG:
                high_after_entry = kline_slice_df["high"].max()
                low_after_entry = kline_slice_df["low"].min()
                if pd.notna(high_after_entry):
                    move_in_favor_pct = (
                        (high_after_entry - entry_p_float) / entry_p_float * 100.0
                    )
                if pd.notna(low_after_entry):
                    drawdown_pct = (
                        (entry_p_float - low_after_entry) / entry_p_float * 100.0
                    )
            elif direction == SignalDirection.SHORT:
                low_after_entry = kline_slice_df["low"].min()
                high_after_entry = kline_slice_df["high"].max()
                if pd.notna(low_after_entry):
                    move_in_favor_pct = (
                        (entry_p_float - low_after_entry) / entry_p_float * 100.0
                    )
                if pd.notna(high_after_entry):
                    drawdown_pct = (
                        (high_after_entry - entry_p_float) / entry_p_float * 100.0
                    )
            if move_in_favor_pct >= self.y_true_min_move_pct:
                return 1
            if drawdown_pct >= self.y_true_max_drawdown_pct:
                return 0
            if exit_reason == "TAKE_PROFIT":
                return 1
            if (
                exit_reason == "STOP_LOSS"
                and move_in_favor_pct < self.y_true_min_move_pct * 0.3
            ):
                return 0
            return 1
        except Exception:
            return 1 if position.get("pnl", 0) > 0 else 0

    def _ensure_ml_confirmation_file_header(self):
        if not self._ml_confirmation_log_path:
            return
        try:
            self._ml_confirmation_log_path.parent.mkdir(parents=True, exist_ok=True)
            file_exists = self._ml_confirmation_log_path.exists()
            if not file_exists or os.path.getsize(self._ml_confirmation_log_path) == 0:
                with open(
                    self._ml_confirmation_log_path, "w", newline="", encoding="utf-8"
                ) as csvfile:
                    writer = csv.DictWriter(
                        csvfile, fieldnames=FIELDNAMES_ML_CONFIRMATION
                    )
                    writer.writeheader()
                self._ml_confirmation_header_written = True
            else:
                self._ml_confirmation_header_written = True
        except Exception as e:
            logger_backtest.error(
                f"Error ensuring ML confirmation file header for {self._ml_confirmation_log_path}: {e}"
            )
            self._log_ml_confirmation_data = False

    async def _close_position_by_market(
        self, position: BacktestPositionState, reason: str
    ):
        """
        Immediately closes the position at the current market price (candle closing price).
        """
        logger_backtest.info(
            f"[{self.symbol}] Market position closure initiated. Reason: {reason}"
        )

        # Using the last known closing price
        exit_price_ideal = self.last_processed_kline_close

        # Apply standard closing logic, including slippage and commission simulation
        await self._close_position(
            position_data=position.__dict__,  # Passing all position data
            exit_price=exit_price_ideal,
            reason=reason,
            timestamp=self._timestamp_dt_current_candle,
        )

        # Important: signal the main loop that the position is closed
        position.remaining_quantity = 0

    @staticmethod
    def _has_active_stop_loss(stop_price: Optional[float]) -> bool:
        return stop_price is not None and float(stop_price) > 0

    @classmethod
    def _is_price_beyond_stop_loss(
        cls,
        direction: SignalDirection,
        execution_price: Optional[float],
        stop_price: Optional[float],
    ) -> bool:
        if execution_price is None or not cls._has_active_stop_loss(stop_price):
            return False
        if direction == SignalDirection.LONG:
            return execution_price <= stop_price
        if direction == SignalDirection.SHORT:
            return execution_price >= stop_price
        return False

    @staticmethod
    def _format_optional_price(price: Optional[float], precision: int = 4) -> str:
        if price is None:
            return "NONE"
        return f"{float(price):.{precision}f}"

    def _modify_position(
        self,
        position: BacktestPositionState,
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None,
    ):
        """Helper method for modifying SL/TP of an open position."""
        if new_sl is not None:
            position.current_sl_price = new_sl
            self.report_progress_event(
                "SL_MODIFIED",
                f"SL for {position.symbol} changed to {new_sl:.4f}",
                {"symbol": position.symbol, "new_sl": new_sl},
            )
        if new_tp is not None:
            position.initial_take_profit = new_tp  # In our model, there is only one TP
            self.report_progress_event(
                "TP_MODIFIED",
                f"TP for {position.symbol} changed to {new_tp:.4f}",
                {"symbol": position.symbol, "new_tp": new_tp},
            )

    def _get_atr_period(self, strategy_name: str, params: Dict[str, Any]) -> int:
        atr_period_default = 14
        if self.ml_training_mode and self.ml_agent_instance:
            return getattr(self.ml_agent_instance, "atr_period", atr_period_default)
        else:
            strat_defaults = self.strategy_defaults.get(strategy_name, {})
            period = params.get(
                "atr_period",
                params.get(
                    "breakout_atr_period",
                    strat_defaults.get("atr_period", atr_period_default),
                ),
            )
            try:
                return int(period)
            except (ValueError, TypeError):
                return atr_period_default

    def _get_required_indicators(
        self,
        strategy_name: str,
        params: Dict[str, Any],
        strategy_defaults_all: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict]:
        indicators = {}
        # 1. ALWAYS calculate the base set for FeatureExtractor and general needs.
        indicators.setdefault(
            "SMA_10", {"period": 10, "source_tf_param": "candle_timeframe"}
        )
        indicators.setdefault(
            "SMA_50", {"period": 50, "source_tf_param": "candle_timeframe"}
        )
        indicators.setdefault(
            "RSI_14", {"period": 14, "source_tf_param": "candle_timeframe"}
        )

        # 2. If it's VisualBuilderStrategy, ADDITIONALLY parse JSON,
        # to find all other required indicators.
        if strategy_name == "VisualBuilderStrategy" or self._is_visual_strategy_config(
            params
        ):
            logger_backtest.info(
                "Visual strategy config: Parsing JSON for additional required indicators."
            )
            strategy_config = self._extract_strategy_config(params)
            if strategy_config:
                # Recursively traverse the entire JSON looking for used indicators
                self._recursively_find_indicators_in_json(strategy_config, indicators)

        logger_backtest.info(
            f"Final list of required indicators after parsing: {list(indicators.keys())}"
        )

        # 3. Determine on which DataFrame to calculate each indicator (this block is unchanged).
        entry_tf = params.get("entry_timeframe", params.get("candle_timeframe", "1m"))
        trend_tf = params.get("trend_timeframe", "5m")

        for name, cfg in indicators.items():
            source_tf_param = cfg.get("source_tf_param")
            target_tf = entry_tf
            if source_tf_param == "trend_timeframe":
                target_tf = trend_tf

            df_key = f"kline_{target_tf}"
            cfg["dataframe_key"] = df_key

        return indicators

    def _recursively_find_indicators_in_json(
        self, node: Any, indicators: Dict[str, Dict]
    ):
        """
        Recursively traverses the strategy JSON tree and collects all necessary indicators.
        """
        if isinstance(node, dict):
            # 1. Check if the node is a known "consumer" of indicators
            node_type = node.get("type")
            params = node.get("params", {})

            if node_type == "trend_direction":
                fast = int(params.get("sma_fast_period", 0))
                slow = int(params.get("sma_slow_period", 0))
                rsi = int(params.get("rsi_period", 0))
                if fast > 0:
                    indicators[f"SMA_{fast}"] = {
                        "period": fast,
                        "source_tf_param": "candle_timeframe",
                    }
                if slow > 0:
                    indicators[f"SMA_{slow}"] = {
                        "period": slow,
                        "source_tf_param": "candle_timeframe",
                    }
                if rsi > 0:
                    indicators[f"RSI_{rsi}"] = {
                        "period": rsi,
                        "source_tf_param": "candle_timeframe",
                    }

            elif node_type == "rsi_condition":
                rsi = int(params.get("period", 14))
                if rsi > 0:
                    indicators[f"RSI_{rsi}"] = {
                        "period": rsi,
                        "source_tf_param": "candle_timeframe",
                    }

            elif node_type == "natr_filter":
                period = int(params.get("period", 14))
                indicators[f"NATR_{period}"] = {
                    "period": period,
                    "source_tf_param": "candle_timeframe",
                }

            elif node_type == "adx_filter" or (
                node_type == "trend_filter" and params.get("indicator") == "ADX"
            ):
                period = int(params.get("period", 14))
                indicators[f"ADX_{period}"] = {
                    "period": period,
                    "source_tf_param": "candle_timeframe",
                }

            elif node_type in ["bollinger_bands_condition", "bb_condition"]:
                period = int(params.get("period", 20))
                std = float(params.get("std_dev", 2.0))
                indicators[f"BBL_{period}_{std}"] = {
                    "period": period,
                    "std": std,
                    "source_tf_param": "candle_timeframe",
                }
                indicators[f"BBU_{period}_{std}"] = {
                    "period": period,
                    "std": std,
                    "source_tf_param": "candle_timeframe",
                }
                indicators[f"BBB_{period}_{std}"] = {
                    "period": period,
                    "std": std,
                    "source_tf_param": "candle_timeframe",
                }

            elif node_type in ["stoch_condition", "stochastic_condition"]:
                k = int(params.get("k_period", 14))
                d = int(params.get("d_period", 3))
                smooth = int(params.get("smooth_k", 3))
                indicators[f"STOCHk_{k}_{d}_{smooth}"] = {
                    "period": k,
                    "d": d,
                    "smooth": smooth,
                    "source_tf_param": "candle_timeframe",
                }
                indicators[f"STOCHd_{k}_{d}_{smooth}"] = {
                    "period": k,
                    "d": d,
                    "smooth": smooth,
                    "source_tf_param": "candle_timeframe",
                }

            elif node_type == "macd_condition":
                fast = int(params.get("fast_period", 12))
                slow = int(params.get("slow_period", 26))
                signal = int(params.get("signal_period", 9))
                indicators[f"MACD_{fast}_{slow}_{signal}"] = {
                    "period": fast,
                    "fast": fast,
                    "slow": slow,
                    "signal": signal,
                    "source_tf_param": "candle_timeframe",
                }
                indicators[f"MACDs_{fast}_{slow}_{signal}"] = {
                    "period": fast,
                    "fast": fast,
                    "slow": slow,
                    "signal": signal,
                    "source_tf_param": "candle_timeframe",
                }
                indicators[f"MACDh_{fast}_{slow}_{signal}"] = {
                    "period": fast,
                    "fast": fast,
                    "slow": slow,
                    "signal": signal,
                    "source_tf_param": "candle_timeframe",
                }

            elif node_type == "ma_cross_condition":
                fast = int(params.get("fast_period", 9))
                slow = int(params.get("slow_period", 21))
                indicators[f"SMA_{fast}"] = {
                    "period": fast,
                    "source_tf_param": "candle_timeframe",
                }
                indicators[f"SMA_{slow}"] = {
                    "period": slow,
                    "source_tf_param": "candle_timeframe",
                }

            elif node_type in [
                "rel_vol_filter",
                "volume_confirmation",
                "market_activity",
            ]:
                lookback = int(params.get("lookback_period", 20))
                indicators[f"VOL_LOOKBACK_{lookback}"] = {
                    "period": lookback,
                    "source_tf_param": "candle_timeframe",
                }

            elif node_type in [
                "level_touch_analyzer",
                "volatility_squeeze",
                "price_action_analyzer",
            ]:
                lookback = int(
                    params.get("lookback_candles", params.get("lookback_period", 20))
                )
                indicators[f"VBS_LOOKBACK_{lookback}"] = {
                    "period": lookback,
                    "source_tf_param": "candle_timeframe",
                }

            # 2. Check if the node is a data source of type "indicator"
            if node.get("source") == "indicator" and "key" in node:
                indicator_key = node["key"]  # for example, 'SMA_50'
                try:
                    parts = indicator_key.split("_")
                    if len(parts) > 1 and parts[-1].isdigit():
                        period = int(parts[-1])
                        # By default, we calculate on the main TF, the logic above will clarify this
                        indicators[indicator_key] = {
                            "period": period,
                            "source_tf_param": "candle_timeframe",
                        }
                except (ValueError, IndexError):
                    logger.warning(
                        f"Could not parse period from indicator key: {indicator_key}"
                    )

            # 3. Recursively traversing all child elements
            for key, value in node.items():
                self._recursively_find_indicators_in_json(value, indicators)

        elif isinstance(node, list):
            # 4. If it is a list, iterate through its elements
            for item in node:
                self._recursively_find_indicators_in_json(item, indicators)

    def _get_current_atr(self, kline_dict_for_step: Dict[str, Any]) -> float:
        atr_col_name = f"ATR_{self.atr_period}"
        val = kline_dict_for_step.get(atr_col_name)
        if val is None or pd.isna(val) or val <= 1e-9:
            return 1e-9
        return float(val)

    def _check_and_reset_daily_stats(self, current_dt_utc: datetime):
        current_day_str = current_dt_utc.strftime("%Y-%m-%d")
        if self.stats["last_known_day_str"] != current_day_str:
            self.stats["start_of_day_balance"] = self.current_balance
            self.stats["consecutive_losses"] = 0
            self.stats["last_known_day_str"] = current_day_str
            current_day_start_dt = datetime(
                current_dt_utc.year,
                current_dt_utc.month,
                current_dt_utc.day,
                tzinfo=timezone.utc,
            )
            self.stats["current_day_start_ts"] = current_day_start_dt.timestamp()
            # DO NOT reset is_trading_allowed if the account is liquidated
            if not self.is_trading_allowed and not self._is_liquidated:
                self.is_trading_allowed = True

    def _check_liquidation(self, timestamp_dt: Optional[datetime] = None) -> bool:
        """Checks for liquidation: if balance <= 0, trading stops forever."""
        if self._is_liquidated:
            return True
        if self.current_balance <= 0:
            self._is_liquidated = True
            self.is_trading_allowed = False
            self.current_balance = 0.0
            self.stats["max_drawdown"] = 1.0  # 100% drawdown
            if timestamp_dt is not None:
                self.equity_curve.append((timestamp_dt, 0.0))
            logger_backtest.warning(
                "LIQUIDATION: Account balance reached zero. "
                "All further trading is disabled for this backtest."
            )
            return True
        return False

    def _check_risk_limits_after_trade(
        self, trade_pnl: float, current_dt_utc: datetime
    ):
        """
        Checks global risk limits after closing a trade and updates statistics.
        """
        current_day_str = current_dt_utc.strftime("%Y-%m-%d")
        self.stats["daily_pnl"][current_day_str] += trade_pnl

        if trade_pnl <= 0:
            self.stats["consecutive_losses"] += 1
        else:
            self.stats["consecutive_losses"] = 0

        self.stats["max_consecutive_losses"] = max(
            self.stats["max_consecutive_losses"], self.stats["consecutive_losses"]
        )

        if not self.is_trading_allowed or self._is_liquidated:
            return

        # Improved and safe parameter retrieval
        daily_max_loss_pct_val = self.risk_params.get("dailyMaxLossPercent")
        daily_max_loss_pct = (
            float(daily_max_loss_pct_val) / 100.0
            if daily_max_loss_pct_val is not None
            else 0.05
        )

        max_consecutive_losses_val = self.risk_params.get("maxConsecutiveLosses")
        max_consecutive_losses_global = (
            int(max_consecutive_losses_val)
            if max_consecutive_losses_val is not None
            else 5
        )

        max_drawdown_pct_val = self.risk_params.get("maxDrawdown")
        max_drawdown_pct = (
            float(max_drawdown_pct_val) / 100.0
            if max_drawdown_pct_val is not None
            else 0.20
        )

        daily_loss_reached = False
        drawdown_reached = False
        daily_pnl_usd = self.stats["daily_pnl"].get(current_day_str, 0.0)
        start_balance = self.stats.get("start_of_day_balance", self.initial_balance)
        daily_loss_limit_usd = 0.0

        if start_balance > 1e-9:
            daily_loss_limit_usd = -(start_balance * daily_max_loss_pct)
            # Comparing negative numbers: the loss must be "less than or equal to" the limit
            if daily_pnl_usd <= daily_loss_limit_usd:
                daily_loss_reached = True

        if self.stats["peak_equity"] > 1e-9:
            drawdown = (self.stats["peak_equity"] - self.current_balance) / self.stats[
                "peak_equity"
            ]
            if drawdown >= max_drawdown_pct:
                drawdown_reached = True

        consecutive_losses_current = self.stats["consecutive_losses"]
        consecutive_loss_reached_global = (
            consecutive_losses_current >= max_consecutive_losses_global
        )

        if daily_loss_reached or consecutive_loss_reached_global or drawdown_reached:
            reason_log = []
            if daily_loss_reached:
                reason_log.append(
                    f"DailyLoss: {daily_pnl_usd:.2f} USD <= {daily_loss_limit_usd:.2f} USD"
                )
            if consecutive_loss_reached_global:
                reason_log.append(
                    f"ConsecLoss: {consecutive_losses_current} >= {max_consecutive_losses_global}"
                )
            if drawdown_reached:
                reason_log.append(
                    f"Drawdown: {drawdown * 100:.2f}% >= {max_drawdown_pct * 100:.2f}%"
                )

            logger_backtest.critical(
                f"GLOBAL TRADING DISABLED due to risk limits ({', '.join(reason_log)})"
            )
            self.is_trading_allowed = False

    def _generate_client_order_id(self):
        return f"bt-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"

    def _process_pending_orders(self, k_open, k_high, k_low, current_dt_utc):
        orders_to_process = list(self.pending_orders.values())
        for order in orders_to_process:
            if order["order_id"] not in self.pending_orders:
                continue

            limit_price = order["price"]
            entry_price_filled = None

            # 1. Check if a limit order is executed on this candle
            if order["side"] == SignalDirection.LONG and k_low <= limit_price:
                # For long, the execution price is the limit price or the open price if it is LOWER
                entry_price_filled = min(k_open, limit_price)
            elif order["side"] == SignalDirection.SHORT and k_high >= limit_price:
                # For short, the execution price is the limit price or the open price if it is HIGHER
                entry_price_filled = max(k_open, limit_price)

            if entry_price_filled is not None:
                # LIMIT ORDER IS EXECUTED WITHOUT SLIPPAGE

                adj_quantity = order["quantity"]
                # Execution price is the one we determined. No slippage.
                entry_price_final = entry_price_filled
                sl_price = order["stop_loss"]
                direction = order["side"]
                signal_details = order.get("signal_details", {})
                no_stop_loss_mode = bool(
                    order.get("no_stop_loss")
                    or (
                        isinstance(signal_details, dict)
                        and signal_details.get("no_stop_loss") is True
                    )
                    or sl_price is None
                )

                if self._is_price_beyond_stop_loss(
                    direction, entry_price_final, sl_price
                ):
                    del self.pending_orders[order["order_id"]]
                    continue

                # 2. Calculate only the commission, without slippage simulation
                commission_entry = abs(
                    entry_price_final
                    * adj_quantity
                    * self.execution_config["commission_pct"]
                )

                # 3. Creating a position with the exact entry price
                self.positions[order["symbol"]] = BacktestPositionState(
                    symbol=order["symbol"],
                    direction=direction,
                    entry_price=entry_price_final,
                    initial_quantity=adj_quantity,
                    remaining_quantity=adj_quantity,
                    entry_time=current_dt_utc,
                    strategy=order["strategy"],
                    initial_stop_loss=sl_price,
                    initial_take_profit=order["take_profit"],
                    current_sl_price=sl_price,
                    no_stop_loss=no_stop_loss_mode,
                    is_stop_at_be=False,
                    move_sl_to_be_enabled=order.get("move_sl_to_be_enabled", False),
                    partial_targets=[
                        (pt.price, pt.fraction, False)
                        for pt in order.get("partial_targets", []) or []
                    ],
                    entry_atr=order.get("entry_atr"),
                    signal_details=signal_details,
                    client_order_id=order["order_id"],
                    initial_risk_usd_planned=order.get("initial_risk_usd_planned"),
                    entry_slippage_usd=0.0,
                    entry_commission_paid=commission_entry,
                    entry_fill_type="LIMIT_FILL",
                    executions=[
                        {
                            "timestamp": current_dt_utc,
                            "price": entry_price_final,
                            "quantity": adj_quantity,
                            "type": "ENTRY",
                        }
                    ],
                )

                self.current_balance -= commission_entry
                self.equity_curve.append((current_dt_utc, self.current_balance))
                self.stats["peak_equity"] = max(
                    self.stats["peak_equity"], self.current_balance
                )

                del self.pending_orders[order["order_id"]]

    # Modified _close_position (from SimpleBacktester, with DB integration from DepthSightBacktester)
    async def _close_position(
        self,
        position_data: dict,
        exit_price: float,
        reason: str,
        timestamp: datetime,
        avg_weighted_exit_price_override: Optional[float] = None,
        num_partial_tp_hits_override: Optional[int] = None,
        total_commission_override: Optional[float] = None,
        # New L2 parameters for exit
        l2_ideal_exit_price: Optional[float] = None,
        l2_exit_slippage_usd: Optional[float] = None,
        l2_filled_qty_at_exit: Optional[float] = None,
    ) -> None:
        client_order_id = position_data.get("client_order_id")
        entry_price = position_data.get("entry_price")
        initial_quantity = position_data.get("initial_quantity")
        direction = position_data.get("direction")
        entry_time = position_data.get("entry_time")
        pnl = position_data.get("pnl")
        commission = (
            total_commission_override
            if total_commission_override is not None
            else position_data.get("commission")
        )

        if not self.run_id or not self.db_session:
            return
        if str(reason).upper() == "END_OF_DATA":
            return

        from api import models

        try:
            decision_trace_raw = position_data.get("signal_details", {}).get(
                "decision_trace"
            )
            decision_trace_for_db = None
            if decision_trace_raw:
                # This trick converts NaN/inf to null, which complies with the JSON standard
                decision_trace_for_db = json.loads(
                    json.dumps(decision_trace_raw, default=str, allow_nan=True)
                )

            l2_ideal_entry_val = position_data.get(
                "ideal_entry_price_l2",
                position_data.get("signal_details", {}).get("ideal_entry_price_l2"),
            )
            l2_entry_slippage_val = position_data.get(
                "entry_slippage_usd",
                position_data.get("signal_details", {}).get("entry_slippage_usd"),
            )

            # 1. Create a parent trade record WITHOUT executions
            db_trade = models.BacktestTrade(
                backtest_run_id=self.run_id,
                client_order_id=client_order_id or str(uuid.uuid4()),
                direction=direction.name if direction else "UNKNOWN",
                timestamp_entry=entry_time,
                timestamp_exit=timestamp,
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=initial_quantity,
                pnl=pnl,
                commission=commission,
                exit_reason=reason,
                decision_trace_json=decision_trace_for_db,
                l2_ideal_entry_price=l2_ideal_entry_val,
                l2_entry_slippage_usd=l2_entry_slippage_val,
                l2_entry_filled_quantity=initial_quantity,
                l2_ideal_exit_price=l2_ideal_exit_price,
                l2_exit_slippage_usd=l2_exit_slippage_usd,
                l2_filled_qty_at_exit=l2_filled_qty_at_exit,
            )
            self.db_session.add(db_trade)
            await self.db_session.flush()  # Getting ID for db_trade

            # 2. Getting the list of executions from the position state
            # This list already contains ALL necessary executions (entry, partial exits, and final exit),
            # since they were added in run_async
            executions_to_save = position_data.get("executions", [])

            # 3. In a loop, create and add all child execution records
            for exec_data in executions_to_save:
                db_execution = models.BacktestTradeExecution(
                    trade_id=db_trade.id,
                    timestamp=exec_data["timestamp"],
                    price=exec_data["price"],
                    quantity=exec_data["quantity"],
                    type=exec_data["type"],
                )
                self.db_session.add(db_execution)

            # 4. Commit all changes (both trade and executions) in a single transaction
            await self.db_session.commit()
            await self.db_session.refresh(db_trade)
            logger_backtest.info(
                f"Successfully committed trade {db_trade.client_order_id} with {len(executions_to_save)} executions."
            )

        except Exception as e:
            logger_backtest.error(
                f"Failed to commit BacktestTrade and Executions to DB. Error: {e}",
                exc_info=True,
            )
            await self.db_session.rollback()

    def _save_backtest_trades_to_csv(self):
        if not self._backtest_save_trades or not self.backtest_trade_log_path:
            return
        if not self.trade_log:
            return
        fieldnames = [
            "timestamp",
            "entry_time",
            "symbol",
            "strategy",
            "direction",
            "entry_price",
            "exit_price",
            "avg_weighted_exit_price",
            "num_partial_tp_hits",
            "quantity",
            "pnl",
            "exit_reason",
            "commission",
            "sl_level",
            "tp_level",
            "client_order_id",
            "partial_fills_count",
            "moved_to_be",
            "ml_confirmed",
            "ml_confirm_proba_1",
            "ml_confirm_proba_0",
        ]
        log_prefix = "[SaveBacktestLog]"
        try:
            self.backtest_trade_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(
                self.backtest_trade_log_path, "w", newline="", encoding="utf-8"
            ) as csvfile:
                writer = csv.DictWriter(
                    csvfile, fieldnames=fieldnames, extrasaction="ignore"
                )
                writer.writeheader()
                for entry in self.trade_log:
                    row = entry.copy()
                    if isinstance(row.get("timestamp"), datetime):
                        row["timestamp"] = row["timestamp"].isoformat()
                    if isinstance(row.get("entry_time"), datetime):
                        row["entry_time"] = row["entry_time"].isoformat()
                    for key in [
                        "entry_price",
                        "exit_price",
                        "quantity",
                        "pnl",
                        "commission",
                        "sl_level",
                        "tp_level",
                    ]:
                        if key in row and isinstance(row[key], (float, int, Decimal)):
                            try:
                                row[key] = f"{float(row[key]):.8f}"
                            except (TypeError, ValueError):
                                pass
                    writer.writerow(row)
        except IOError as e:
            logger_backtest.error(
                f"{log_prefix} Error writing backtest trades log to {self.backtest_trade_log_path}: {e}"
            )
        except Exception as e:
            logger_backtest.error(
                f"{log_prefix} Unexpected error saving backtest trades log: {e}",
                exc_info=True,
            )

    def _adjust_quantity(
        self, quantity: float, symbol: str, entry_price: Optional[float]
    ) -> float:
        lot_params = self.exchange_info.get("lot_params")
        min_notional_filter = self.exchange_info.get("min_notional")
        adj_qty = quantity
        if adj_qty <= 1e-12:
            return 0.0
        if lot_params and lot_params.get("stepSize", 0) > 0:
            step = Decimal(str(lot_params["stepSize"]))
            qty_dec = Decimal(str(quantity))
            adj_qty = float(
                (qty_dec / step).quantize(Decimal("0"), rounding=ROUND_DOWN) * step
            )
        if adj_qty <= 1e-12:
            return 0.0
        min_qty_filter = lot_params.get("minQty", 0) if lot_params else 0
        if adj_qty < min_qty_filter:
            return 0.0
        if (
            min_notional_filter is not None
            and min_notional_filter > 0
            and entry_price is not None
            and entry_price > 0
        ):
            if (adj_qty * entry_price) < min_notional_filter:
                return 0.0
        max_qty_filter = (
            lot_params.get("maxQty", float("inf")) if lot_params else float("inf")
        )
        if adj_qty > max_qty_filter:
            adj_qty = max_qty_filter
        if adj_qty <= 1e-12:
            return 0.0
        return adj_qty

    def _resolve_position_management_value(
        self,
        raw_value: Any,
        position: BacktestPositionState,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
    ) -> Any:
        if not self.strategy_instance or not hasattr(
            self.strategy_instance, "_resolve_value"
        ):
            return raw_value

        signal_details = getattr(position, "signal_details", {}) or {}
        context = {
            "pair_info": pair_info,
            "market_data": market_data,
            "position": position,
            "trace": signal_details.get("decision_trace"),
        }
        try:
            return self.strategy_instance._resolve_value(raw_value, context)
        except Exception as e:
            logger_backtest.warning(
                f"[{self.symbol}] Failed to resolve management value {raw_value}: {e}"
            )
            return None

    def _calculate_target_price_from_config(
        self,
        target_type: str,
        target_value: Any,
        comparison_price: float,
        stop_loss_price: float,
        direction: SignalDirection,
        tick_size: float,
    ) -> Optional[float]:
        if target_value is None or comparison_price <= 0 or tick_size <= 0:
            return None

        target_type_normalized = str(target_type or "rr_multiplier").lower()

        try:
            if target_type_normalized == "fixed_price":
                target_price_raw = float(target_value)
            elif target_type_normalized == "percent_from_price":
                multiplier = (
                    1 + (float(target_value) / 100.0)
                    if direction == SignalDirection.LONG
                    else 1 - (float(target_value) / 100.0)
                )
                target_price_raw = comparison_price * multiplier
            elif target_type_normalized == "rr_multiplier":
                risk_distance_abs = abs(comparison_price - stop_loss_price)
                if risk_distance_abs <= 1e-12:
                    return None
                target_price_raw = (
                    comparison_price + (risk_distance_abs * float(target_value))
                    if direction == SignalDirection.LONG
                    else comparison_price - (risk_distance_abs * float(target_value))
                )
            else:
                return None
        except (TypeError, ValueError):
            return None

        rounding = ROUND_UP if direction == SignalDirection.LONG else ROUND_DOWN
        return round_price_by_tick(target_price_raw, tick_size, rounding)

    @staticmethod
    def _strategy_uses_dca_or_grid_management(node: Any) -> bool:
        if isinstance(node, dict):
            if str(node.get("type", "")).lower() in {
                "dca_management",
                "grid_management",
            }:
                return True
            return any(
                DepthSightBacktester._strategy_uses_dca_or_grid_management(value)
                for value in node.values()
            )
        if isinstance(node, list):
            return any(
                DepthSightBacktester._strategy_uses_dca_or_grid_management(item)
                for item in node
            )
        return False

    def _current_strategy_uses_dca_or_grid_management(self) -> bool:
        strategy_config = None
        if self.strategy_instance:
            strategy_config = getattr(
                self.strategy_instance, "_instance_params", {}
            ).get("config")
        if not isinstance(strategy_config, dict):
            strategy_config = (
                self.params.get("config") if isinstance(self.params, dict) else None
            )
        if not isinstance(strategy_config, dict):
            return False

        management_config = strategy_config.get(
            "positionManagement", strategy_config.get("management", [])
        )
        return self._strategy_uses_dca_or_grid_management(management_config)

    def _refresh_position_targets_after_scale_in(
        self,
        position: BacktestPositionState,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
    ) -> None:
        if not self.strategy_instance:
            return

        if getattr(position, "partial_fills", None):
            logger_backtest.info(
                f"[{position.symbol}] Skipping TP refresh after scale-in because partial exits already occurred."
            )
            return

        strategy_config = getattr(self.strategy_instance, "_instance_params", {}).get(
            "config"
        )
        if not isinstance(strategy_config, dict):
            return

        action_config = strategy_config.get("initialization") or strategy_config.get(
            "action"
        )
        if not isinstance(action_config, dict):
            return

        action_params = action_config.get("params", {})
        if not isinstance(action_params, dict):
            return

        comparison_price = float(getattr(position, "entry_price", 0.0) or 0.0)
        current_sl_price = getattr(position, "current_sl_price", None)
        stop_loss_price = (
            float(current_sl_price) if current_sl_price is not None else 0.0
        )
        tick_size = float(
            pair_info.get("tick_size")
            or self.exchange_info.get("tick_size", self.config.DEFAULT_TICK_SIZE)
            or 0.0
        )
        if comparison_price <= 0 or tick_size <= 0:
            return

        partial_targets: List[Tuple[float, float, bool]] = []
        partial_exits_raw = action_params.get("partial_exits")
        if isinstance(partial_exits_raw, list):
            for exit_item in partial_exits_raw:
                if not isinstance(exit_item, dict):
                    continue
                resolved_tp_value = self._resolve_position_management_value(
                    exit_item.get("tp_value"),
                    position,
                    pair_info,
                    market_data,
                )
                target_price = self._calculate_target_price_from_config(
                    target_type=str(exit_item.get("tp_type", "rr_multiplier")),
                    target_value=resolved_tp_value,
                    comparison_price=comparison_price,
                    stop_loss_price=stop_loss_price,
                    direction=position.direction,
                    tick_size=tick_size,
                )
                if target_price is None:
                    continue
                try:
                    size_fraction = float(exit_item.get("size_pct", 0.0)) / 100.0
                except (TypeError, ValueError):
                    continue
                if size_fraction <= 0:
                    continue
                partial_targets.append((float(target_price), size_fraction, False))

        if partial_targets:
            partial_targets.sort(
                key=lambda item: item[0],
                reverse=(position.direction == SignalDirection.SHORT),
            )

        resolved_final_tp_value = self._resolve_position_management_value(
            action_params.get("tp_value"),
            position,
            pair_info,
            market_data,
        )
        final_take_profit = self._calculate_target_price_from_config(
            target_type=str(action_params.get("tp_type", "rr_multiplier")),
            target_value=resolved_final_tp_value,
            comparison_price=comparison_price,
            stop_loss_price=stop_loss_price,
            direction=position.direction,
            tick_size=tick_size,
        )

        if partial_targets:
            total_fraction = sum(target[1] for target in partial_targets)
            if total_fraction >= (1.0 - 1e-9):
                final_take_profit = None

        if partial_targets or final_take_profit is not None:
            position.partial_targets = partial_targets
            position.initial_take_profit = final_take_profit
            logger_backtest.info(
                f"[{position.symbol}] Repriced exits after scale-in. "
                f"Entry={position.entry_price:.8f}, SL={self._format_optional_price(position.current_sl_price, 8)}, "
                f"TP={position.initial_take_profit}, Partials={len(position.partial_targets)}"
            )

    def _apply_position_addition_fill(
        self,
        position: BacktestPositionState,
        fill_price: float,
        filled_quantity: float,
        commission_paid: float,
        timestamp_dt: datetime,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        *,
        is_dca: bool = False,
    ) -> None:
        if filled_quantity <= 0:
            return

        previous_quantity = float(position.remaining_quantity)
        new_total_quantity = previous_quantity + float(filled_quantity)
        if new_total_quantity <= 0:
            return

        new_avg_price = (
            (float(position.entry_price) * previous_quantity)
            + (float(fill_price) * float(filled_quantity))
        ) / new_total_quantity

        position.executions.append(
            {
                "timestamp": timestamp_dt,
                "price": float(fill_price),
                "quantity": float(filled_quantity),
                "type": "ENTRY",
            }
        )
        position.entry_price = new_avg_price
        position.remaining_quantity = new_total_quantity
        position.initial_quantity = new_total_quantity
        position.number_of_entries += 1
        position.entry_commission_paid += float(commission_paid)

        if is_dca:
            position.dca_active_sos += 1

        self.stats["number_of_entries"] += 1
        self.stats["total_commission"] += float(commission_paid)
        self.current_balance -= float(commission_paid)
        self.equity_curve.append((timestamp_dt, self.current_balance))
        self.stats["peak_equity"] = max(self.stats["peak_equity"], self.current_balance)

        self._refresh_position_targets_after_scale_in(position, pair_info, market_data)

    def _resolve_grid_bound_price(
        self,
        raw_bound: Any,
        range_type: str,
        reference_price: float,
        atr_value: float,
        position: BacktestPositionState,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
    ) -> Optional[float]:
        resolved_bound = self._resolve_position_management_value(
            raw_bound, position, pair_info, market_data
        )
        if resolved_bound is None:
            return None

        try:
            bound_value = float(resolved_bound)
        except (TypeError, ValueError):
            return None

        range_type_normalized = str(range_type or "fixed_prices").lower()
        if range_type_normalized == "percentage":
            return reference_price * (1 + bound_value / 100.0)
        if range_type_normalized == "atr":
            if atr_value <= 0:
                return None
            return reference_price + (atr_value * bound_value)
        return bound_value

    def _initialize_grid_orders_for_position(
        self,
        position: BacktestPositionState,
        grid_params: Dict[str, Any],
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
    ) -> None:
        current_price = float(
            pair_info.get("last_price") or position.entry_price or 0.0
        )
        tick_size = float(
            pair_info.get("tick_size")
            or self.exchange_info.get("tick_size", self.config.DEFAULT_TICK_SIZE)
            or 0.0
        )
        atr_value = float(pair_info.get("atr") or position.entry_atr or 0.0)
        if current_price <= 0 or tick_size <= 0:
            position.grid_init_triggered = None
            return

        levels_raw = grid_params.get("grid_levels", grid_params.get("levels", 10))
        try:
            levels = max(int(levels_raw), 1)
        except (TypeError, ValueError):
            levels = 1

        range_type = str(grid_params.get("range_type", "fixed_prices"))
        lower_bound = self._resolve_grid_bound_price(
            grid_params.get("lower_bound"),
            range_type,
            current_price,
            atr_value,
            position,
            pair_info,
            market_data,
        )
        upper_bound = self._resolve_grid_bound_price(
            grid_params.get("upper_bound"),
            range_type,
            current_price,
            atr_value,
            position,
            pair_info,
            market_data,
        )

        if lower_bound is None or upper_bound is None:
            logger_backtest.warning(
                f"[{position.symbol}] Grid initialization skipped: could not resolve bounds from {grid_params}."
            )
            position.grid_order_ids = ["grid_init_failed"]
            position.grid_init_triggered = None
            return

        if lower_bound > upper_bound:
            lower_bound, upper_bound = upper_bound, lower_bound

        if levels == 1:
            raw_prices = [(lower_bound + upper_bound) / 2.0]
        else:
            step = (upper_bound - lower_bound) / (levels - 1)
            raw_prices = [
                lower_bound + (step * level_idx) for level_idx in range(levels)
            ]

        price_rounding = (
            ROUND_DOWN if position.direction == SignalDirection.LONG else ROUND_UP
        )
        candidate_prices: List[float] = []
        for raw_price in raw_prices:
            rounded_price = round_price_by_tick(raw_price, tick_size, price_rounding)
            if rounded_price is None:
                continue
            if position.direction == SignalDirection.LONG and rounded_price < (
                current_price - tick_size * 0.5
            ):
                candidate_prices.append(float(rounded_price))
            elif position.direction == SignalDirection.SHORT and rounded_price > (
                current_price + tick_size * 0.5
            ):
                candidate_prices.append(float(rounded_price))

        deduped_candidate_prices: List[float] = []
        seen_prices = set()
        for price in candidate_prices:
            if price in seen_prices:
                continue
            deduped_candidate_prices.append(price)
            seen_prices.add(price)

        qty_per_level_raw = (float(position.initial_quantity) * 2.0) / max(levels, 1)
        created_candle_index = int(pair_info.get("current_candle_index", -1))
        pending_orders: List[Dict[str, Any]] = []
        grid_order_ids: List[str] = []

        for order_idx, price in enumerate(deduped_candidate_prices, start=1):
            adjusted_qty = self._adjust_quantity(
                qty_per_level_raw, position.symbol, price
            )
            if adjusted_qty <= 0:
                continue
            order_id = f"{position.client_order_id or 'bt-grid'}-grid-{order_idx}"
            pending_orders.append(
                {
                    "order_id": order_id,
                    "price": float(price),
                    "quantity": float(adjusted_qty),
                    "side": position.direction,
                    "created_candle_index": created_candle_index,
                }
            )
            grid_order_ids.append(order_id)

        position.grid_pending_orders = pending_orders
        position.grid_order_ids = grid_order_ids or ["grid_initialized"]
        position.grid_init_triggered = None

        logger_backtest.info(
            f"[{position.symbol}] Initialized grid with {len(position.grid_pending_orders)} pending orders "
            f"between {lower_bound:.8f} and {upper_bound:.8f}."
        )

    def _process_grid_orders_for_candle(
        self,
        position: BacktestPositionState,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
    ) -> None:
        pending_grid_orders = list(getattr(position, "grid_pending_orders", []) or [])
        if not pending_grid_orders:
            return

        current_candle_index = int(pair_info.get("current_candle_index", -1))
        k_open = float(pair_info.get("open", pair_info.get("last_price", 0.0)) or 0.0)
        k_high = float(pair_info.get("high", pair_info.get("last_price", 0.0)) or 0.0)
        k_low = float(pair_info.get("low", pair_info.get("last_price", 0.0)) or 0.0)
        k_close = float(pair_info.get("close", pair_info.get("last_price", 0.0)) or 0.0)
        timestamp_dt = pair_info.get("timestamp_dt")

        remaining_orders: List[Dict[str, Any]] = []
        fill_candidates: List[Dict[str, Any]] = []

        for order in pending_grid_orders:
            if current_candle_index <= int(order.get("created_candle_index", -1)):
                remaining_orders.append(order)
                continue

            fill_price = None
            if order.get("side") == SignalDirection.LONG and k_low <= order["price"]:
                fill_price = min(k_open, order["price"])
            elif (
                order.get("side") == SignalDirection.SHORT and k_high >= order["price"]
            ):
                fill_price = max(k_open, order["price"])

            if fill_price is None:
                remaining_orders.append(order)
                continue

            fill_candidates.append({**order, "fill_price": float(fill_price)})

        fill_candidates.sort(
            key=lambda order: order["price"],
            reverse=(position.direction == SignalDirection.LONG),
        )

        for order in fill_candidates:
            sim_result = simulate_market_order_execution(
                order_quantity=float(order["quantity"]),
                direction=position.direction,
                market_data_for_sim=market_data,
                ideal_entry_price=float(order["fill_price"]),
                commission_pct=self.execution_config["commission_pct"],
                kline_close_for_fallback=k_close,
                simple_slippage_pct=self.execution_config.get("slippage_pct"),
            )

            if sim_result.filled_quantity <= 0 or sim_result.avg_fill_price is None:
                logger_backtest.warning(
                    f"[{position.symbol}] Grid order {order['order_id']} failed to fill in simulation. Keeping it pending."
                )
                remaining_orders.append(order)
                continue

            is_slippage_past_sl = self._is_price_beyond_stop_loss(
                position.direction,
                sim_result.avg_fill_price,
                position.current_sl_price,
            )
            if is_slippage_past_sl:
                logger_backtest.warning(
                    f"[{position.symbol}] Grid order {order['order_id']} skipped: "
                    f"fill {sim_result.avg_fill_price:.8f} is beyond SL "
                    f"{self._format_optional_price(position.current_sl_price, 8)}."
                )
                continue

            self._apply_position_addition_fill(
                position=position,
                fill_price=float(sim_result.avg_fill_price),
                filled_quantity=float(sim_result.filled_quantity),
                commission_paid=float(sim_result.actual_commission_paid),
                timestamp_dt=timestamp_dt,
                pair_info=pair_info,
                market_data=market_data,
                is_dca=False,
            )

        position.grid_pending_orders = remaining_orders

    def _write_ml_confirmation_row(self, data_row: Dict[str, Any]):
        if not self._ml_confirmation_log_path:
            return
        try:
            if not self._ml_confirmation_header_written:
                self._ensure_ml_confirmation_file_header()
                if not self._ml_confirmation_header_written:
                    return
            row_cleaned = {}
            for k, v in data_row.items():
                if v is None:
                    row_cleaned[k] = "" if k == "signal_entry_price" else ""
                elif isinstance(v, float):
                    row_cleaned[k] = f"{v:.8f}"
                else:
                    row_cleaned[k] = v
            with open(
                self._ml_confirmation_log_path, "a", newline="", encoding="utf-8"
            ) as csvfile:
                writer = csv.DictWriter(
                    csvfile,
                    fieldnames=FIELDNAMES_ML_CONFIRMATION,
                    extrasaction="ignore",
                )
                writer.writerow(row_cleaned)
        except IOError as e:
            logger_backtest.error(
                f"Error writing ML confirmation row to {self._ml_confirmation_log_path}: {e}"
            )
        except Exception as e:
            logger_backtest.error(
                f"Unexpected error writing ML confirmation row: {e}", exc_info=True
            )

    def _get_ml_target_label(
        self,
        index: int,
        hypothetical_sl: float,
        hypothetical_tp: float,
        direction: SignalDirection,
    ) -> int:
        if self.kline_data_array is None or not self.kline_index_map:
            return 0
        if index + 1 >= len(self.klines):
            return 0
        lookahead_end_idx = min(index + self._ml_label_lookahead, len(self.klines) - 1)
        if index + 1 > lookahead_end_idx:
            return 0
        high_col_idx = self.kline_index_map.get("high")
        low_col_idx = self.kline_index_map.get("low")
        if high_col_idx is None or low_col_idx is None:
            return 0
        if np.isnan(hypothetical_sl) or np.isnan(hypothetical_tp):
            return 0
        try:
            klines_high_np = self.kline_data_array[:, high_col_idx].astype(np.float64)
            klines_low_np = self.kline_data_array[:, low_col_idx].astype(np.float64)
        except Exception:
            return 0
        return _get_ml_target_label_numba(
            klines_high_np,
            klines_low_np,
            index,
            lookahead_end_idx,
            float(hypothetical_sl),
            float(hypothetical_tp),
            direction == SignalDirection.LONG,
        )

    def _update_and_adjust_strategy_symbol_performance(
        self,
        strategy_name: str,
        symbol: str,
        pnl_usd: float,
        initial_risk_usd_planned: float,
        current_kline_timestamp_float: float,
    ):
        if not self.bt_strategy_symbol_adjustment_enabled:
            return
        perf_key = (symbol, strategy_name)
        stats = self._bt_symbol_strategy_performance[perf_key]
        stats.trade_results_buffer.append((pnl_usd, initial_risk_usd_planned))
        stats.current_pnl_sum_usd = sum(p for p, r in stats.trade_results_buffer)
        stats.sum_initial_risk_usd_in_window = sum(
            r for p, r in stats.trade_results_buffer
        )
        stats.current_wins_in_window = sum(
            1 for p, r in stats.trade_results_buffer if p > 0
        )
        stats.current_trades_in_window = len(stats.trade_results_buffer)
        stats.current_consecutive_losses = 0
        stats.current_consecutive_wins_for_recovery = 0
        _counting_losses = True
        _counting_wins = True
        for p, _ in reversed(stats.trade_results_buffer):
            if _counting_losses:
                if p <= 0:
                    stats.current_consecutive_losses += 1
                else:
                    _counting_losses = False
            if _counting_wins:
                if p > 0:
                    stats.current_consecutive_wins_for_recovery += 1
                else:
                    _counting_wins = False
            if not _counting_losses and not _counting_wins:
                break
        stats.total_trades_for_assessment += 1

        if (
            stats.total_trades_for_assessment
            < self.bt_strategy_symbol_min_trades_assess
        ):
            return
        max_multiplier_idx = len(self.bt_strategy_symbol_risk_multipliers) - 1
        reduction_triggered = False

        if stats.current_risk_multiplier_index < max_multiplier_idx:
            reason_for_reduction = []
            if stats.current_trades_in_window >= self.bt_strategy_symbol_window_size:
                pnl_pct = (
                    (
                        stats.current_pnl_sum_usd
                        / stats.sum_initial_risk_usd_in_window
                        * 100.0
                    )
                    if stats.sum_initial_risk_usd_in_window > 1e-9
                    else 0.0
                )
                wr_pct = (
                    (
                        stats.current_wins_in_window
                        / stats.current_trades_in_window
                        * 100.0
                    )
                    if stats.current_trades_in_window > 0
                    else 0.0
                )
                if pnl_pct < self.bt_strategy_symbol_pnl_thresh_pct:
                    reason_for_reduction.append(
                        f"PnL {pnl_pct:.2f}% < {self.bt_strategy_symbol_pnl_thresh_pct:.2f}%"
                    )
                if wr_pct < self.bt_strategy_symbol_wr_thresh_pct:
                    reason_for_reduction.append(
                        f"WR {wr_pct:.2f}% < {self.bt_strategy_symbol_wr_thresh_pct:.2f}%"
                    )
            if (
                stats.current_consecutive_losses
                >= self.bt_strategy_symbol_max_consec_loss
            ):
                reason_for_reduction.append(
                    f"ConsecLoss {stats.current_consecutive_losses} >= {self.bt_strategy_symbol_max_consec_loss}"
                )
            if reason_for_reduction:
                reduction_triggered = True
                stats.current_risk_multiplier_index = min(
                    stats.current_risk_multiplier_index + 1, max_multiplier_idx
                )
                stats.last_penalty_timestamp = current_kline_timestamp_float
                stats.current_consecutive_wins_for_recovery = 0

        if not reduction_triggered and stats.current_risk_multiplier_index > 0:
            cooldown_passed = (
                current_kline_timestamp_float - stats.last_penalty_timestamp
            ) >= self.bt_strategy_symbol_cooldown_penalty_sec
            if cooldown_passed:
                reason_for_recovery = []
                if (
                    stats.current_consecutive_wins_for_recovery
                    >= self.bt_strategy_symbol_rec_consec_wins
                ):
                    reason_for_recovery.append(
                        f"RecConsecWins {stats.current_consecutive_wins_for_recovery} >= {self.bt_strategy_symbol_rec_consec_wins}"
                    )
                if (
                    stats.current_trades_in_window
                    >= self.bt_strategy_symbol_window_size
                ):
                    pnl_pct_rec = (
                        (
                            stats.current_pnl_sum_usd
                            / stats.sum_initial_risk_usd_in_window
                            * 100.0
                        )
                        if stats.sum_initial_risk_usd_in_window > 1e-9
                        else 0.0
                    )
                    if pnl_pct_rec > self.bt_strategy_symbol_rec_pnl_thresh_pct:
                        reason_for_recovery.append(
                            f"RecPnL {pnl_pct_rec:.2f}% > {self.bt_strategy_symbol_rec_pnl_thresh_pct:.2f}%"
                        )
                if reason_for_recovery:
                    stats.current_risk_multiplier_index = max(
                        0, stats.current_risk_multiplier_index - 1
                    )
                    stats.current_consecutive_wins_for_recovery = 0

    def _save_simulated_trades_to_csv(self):
        if not self._ml_simulated_trade_log:
            return
        if not self._ml_simulated_trades_log_path:
            return
        fieldnames = [
            "timestamp",
            "symbol",
            "direction",
            "entry_price",
            "exit_price",
            "quantity",
            "pnl",
            "commission",
            "exit_reason",
            "sl_level",
            "tp_level",
            "entry_time",
            "prediction",
            "prediction_proba",
        ]
        try:
            self._ml_simulated_trades_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(
                self._ml_simulated_trades_log_path, "w", newline="", encoding="utf-8"
            ) as csvfile:
                writer = csv.DictWriter(
                    csvfile, fieldnames=fieldnames, extrasaction="ignore"
                )
                writer.writeheader()
                for entry in self._ml_simulated_trade_log:
                    row = entry.copy()
                    if isinstance(row.get("timestamp"), datetime):
                        row["timestamp"] = row["timestamp"].isoformat()
                    if isinstance(row.get("entry_time"), datetime):
                        row["entry_time"] = row["entry_time"].isoformat()
                    writer.writerow(row)
        except Exception as e:
            logger_backtest.error(
                f"Error saving simulated trades log: {e}", exc_info=True
            )

    def _calculate_final_kpis_for_mode(self) -> Dict[str, Any]:
        if self.ml_training_mode and self._ml_simulate_trades:
            return self._calculate_kpis(self._ml_simulated_trade_log)
        elif not self.ml_training_mode:
            return self._calculate_kpis(self.trade_log)
        else:
            steps = 0
            final_metrics = {}
            if self.ml_agent_instance and hasattr(
                self.ml_agent_instance, "model_pipeline"
            ):
                steps = getattr(
                    self.ml_agent_instance.model_pipeline, "steps_processed", 0
                )
                final_metrics = self.ml_agent_instance.model_pipeline.get_metrics()
            return {
                "trades": 0,
                "ml_steps_processed": steps,
                "ml_final_metrics": final_metrics,
            }

    def _calculate_kpis(self, trade_log_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        kpis = {
            "trades": 0,
            "total_pnl": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "total_commission": 0.0,
            "wins": 0,
            "losses": 0,
            "avg_trade_pnl": 0.0,
            "sharpe_ratio": 0.0,
            "max_consecutive_losses": 0,
            "total_entry_slippage_usd": 0.0,
            "total_exit_slippage_usd": 0.0,
            "total_slippage_usd": 0.0,
            "avg_slippage_per_trade_usd": 0.0,
            "avg_total_slippage_pct": 0.0,
            "trades_all": 0,
            "excluded_end_of_data_trades": 0,
            "tick_size": self.exchange_info.get(
                "tick_size", self.config.DEFAULT_TICK_SIZE
            ),
        }
        trades_all = len(trade_log_list)
        filtered_trade_log = [
            trade
            for trade in trade_log_list
            if str(trade.get("exit_reason", "")).upper() != "END_OF_DATA"
        ]
        trades = len(filtered_trade_log)
        kpis["trades"] = trades
        kpis["trades_all"] = trades_all
        kpis["excluded_end_of_data_trades"] = trades_all - trades

        if not self.ml_training_mode and trades < self.min_trades_required:
            penalty_kpis = kpis.copy()
            penalty_kpis.update(
                {
                    "total_pnl": -999999.0,
                    "profit_factor": 0.0,
                    "max_drawdown": 100.0,
                    "win_rate": 0.0,
                    "sharpe_ratio": -10.0,
                }
            )
            return penalty_kpis
        elif trades == 0:
            start_ts = self.actual_trading_start_dt or datetime.now(timezone.utc)
            kpis["equity_curve"] = [(start_ts.isoformat(), float(self.initial_balance))]
            return kpis

        df_log = pd.DataFrame(filtered_trade_log)
        if df_log.empty or "pnl" not in df_log.columns:
            return kpis

        df_log["pnl"] = pd.to_numeric(df_log["pnl"], errors="coerce")
        df_log.dropna(subset=["pnl"], inplace=True)
        if df_log.empty:
            return kpis

        for ts_col in ("timestamp", "exit_time", "timestamp_exit"):
            if ts_col in df_log.columns:
                df_log["kpi_exit_time"] = pd.to_datetime(
                    df_log[ts_col], errors="coerce"
                )
                break
        else:
            df_log["kpi_exit_time"] = pd.NaT

        for ts_col in ("entry_time", "timestamp_entry"):
            if ts_col in df_log.columns:
                df_log["kpi_entry_time"] = pd.to_datetime(
                    df_log[ts_col], errors="coerce"
                )
                break
        else:
            df_log["kpi_entry_time"] = pd.NaT

        df_log.sort_values("kpi_exit_time", inplace=True, na_position="last")

        total_pnl = df_log["pnl"].sum()
        wins_df = df_log[df_log["pnl"] > 0]
        losses_df = df_log[df_log["pnl"] <= 0]

        num_wins = len(wins_df)
        num_losses = len(losses_df)
        gross_profit = wins_df["pnl"].sum()
        gross_loss = abs(losses_df["pnl"].sum())

        profit_factor = (
            gross_profit / gross_loss
            if gross_loss > 1e-9
            else (99999.0 if gross_profit > 1e-9 else 0.0)
        )
        if math.isinf(profit_factor):
            profit_factor = 99999.0

        win_rate = num_wins / trades * 100 if trades > 0 else 0.0
        max_consecutive_losses = 0
        current_consecutive_losses = 0
        for pnl_value in df_log["pnl"].tolist():
            if pnl_value <= 0:
                current_consecutive_losses += 1
                max_consecutive_losses = max(
                    max_consecutive_losses, current_consecutive_losses
                )
            else:
                current_consecutive_losses = 0

        total_commission = (
            float(
                pd.to_numeric(df_log["commission"], errors="coerce").fillna(0.0).sum()
            )
            if "commission" in df_log.columns
            else 0.0
        )

        # Robust handling of missing L2 columns
        l2_cols_with_default_zero = ["l2_entry_slippage_usd", "l2_exit_slippage_usd"]
        for col in l2_cols_with_default_zero:
            if col not in df_log.columns:
                df_log[col] = 0.0
            else:
                df_log[col] = pd.to_numeric(df_log[col], errors="coerce").fillna(0.0)

        l2_cols_with_default_nan = [
            "l2_ideal_entry_price",
            "l2_entry_filled_quantity",
            "l2_ideal_exit_price",
            "l2_filled_qty_at_exit",
        ]
        for col in l2_cols_with_default_nan:
            if col not in df_log.columns:
                df_log[col] = np.nan
            else:
                df_log[col] = pd.to_numeric(df_log[col], errors="coerce")

        total_entry_slippage_usd = df_log["l2_entry_slippage_usd"].sum()
        total_exit_slippage_usd = df_log["l2_exit_slippage_usd"].sum()
        total_slippage_usd = total_entry_slippage_usd + total_exit_slippage_usd

        slippage_trades_count = df_log[
            (df_log["l2_entry_slippage_usd"] != 0)
            | (df_log["l2_exit_slippage_usd"] != 0)
        ].shape[0]

        avg_slippage_per_active_trade_usd = (
            total_slippage_usd / slippage_trades_count
            if slippage_trades_count > 0
            else 0.0
        )

        total_ideal_value_entry = (
            df_log["l2_ideal_entry_price"] * df_log["l2_entry_filled_quantity"]
        ).sum(skipna=True)
        total_ideal_value_exit = (
            df_log["l2_ideal_exit_price"] * df_log["l2_filled_qty_at_exit"]
        ).sum(skipna=True)
        total_ideal_value = total_ideal_value_entry + total_ideal_value_exit

        avg_total_slippage_pct = (
            (total_slippage_usd / total_ideal_value) * 100
            if total_ideal_value > 1e-9
            else 0.0
        )

        if df_log["kpi_entry_time"].notna().any():
            curve_start_ts = df_log["kpi_entry_time"].dropna().iloc[0]
        elif self.actual_trading_start_dt is not None:
            curve_start_ts = pd.Timestamp(self.actual_trading_start_dt)
        else:
            curve_start_ts = pd.Timestamp(datetime.now(timezone.utc))

        running_balance = float(self.initial_balance)
        equity_curve_for_kpis = [(curve_start_ts, running_balance)]
        for _, row in df_log.iterrows():
            running_balance += float(row["pnl"])
            exit_ts = (
                row["kpi_exit_time"]
                if pd.notna(row["kpi_exit_time"])
                else curve_start_ts
            )
            equity_curve_for_kpis.append((exit_ts, running_balance))

        max_drawdown = 0.0
        peak_balance = equity_curve_for_kpis[0][1]
        for _, balance in equity_curve_for_kpis:
            peak_balance = max(peak_balance, balance)
            if peak_balance > 1e-9:
                max_drawdown = max(
                    max_drawdown, (peak_balance - balance) / peak_balance * 100.0
                )

        sharpe_ratio = 0.0
        if len(equity_curve_for_kpis) > 1:
            try:
                equity_df = pd.DataFrame(
                    equity_curve_for_kpis, columns=["timestamp", "balance"]
                ).set_index("timestamp")
                if not equity_df.index.is_monotonic_increasing:
                    equity_df = equity_df.sort_index()
                if equity_df.index.normalize().nunique() > 1:
                    daily_returns = (
                        equity_df["balance"].resample("D").last().pct_change().dropna()
                    )
                    if not daily_returns.empty and daily_returns.std() > 1e-9:
                        annualized_return = daily_returns.mean() * 252
                        annualized_volatility = daily_returns.std() * np.sqrt(252)
                        if annualized_volatility > 1e-9:
                            sharpe_ratio = max(
                                -10.0,
                                min(10.0, annualized_return / annualized_volatility),
                            )
            except Exception as e_sharpe:
                logger_backtest.warning(f"Could not calculate Sharpe Ratio: {e_sharpe}")
                sharpe_ratio = 0.0

        kpis.update(
            {
                "total_pnl": float(total_pnl),
                "profit_factor": float(profit_factor),
                "win_rate": float(win_rate),
                "wins": int(num_wins),
                "losses": int(num_losses),
                "avg_trade_pnl": float(total_pnl / trades if trades > 0 else 0.0),
                "sharpe_ratio": float(sharpe_ratio),
                "total_commission": float(total_commission),
                "max_consecutive_losses": int(max_consecutive_losses),
                "max_drawdown": float(max_drawdown),
                "total_entry_slippage_usd": float(total_entry_slippage_usd),
                "total_exit_slippage_usd": float(total_exit_slippage_usd),
                "total_slippage_usd": float(total_slippage_usd),
                "avg_slippage_per_active_trade_usd": float(
                    avg_slippage_per_active_trade_usd
                ),
                "avg_total_slippage_pct": float(avg_total_slippage_pct),
            }
        )

        kpis["equity_curve"] = [
            (ts.isoformat(), float(balance)) for ts, balance in equity_curve_for_kpis
        ]

        if not self.ml_training_mode:
            for key, value in kpis.items():
                if not isinstance(value, (int, float)):
                    continue

                if pd.isna(value) or not math.isfinite(value):
                    if key == "total_pnl":
                        kpis[key] = -999999.0
                    elif key == "profit_factor":
                        kpis[key] = 0.0
                    elif key == "max_drawdown":
                        kpis[key] = 100.0
                    elif key == "sharpe_ratio":
                        kpis[key] = -10.0
                    else:
                        kpis[key] = 0
        return kpis

    # Asynchronous start (formerly `SimpleBacktester.run`, now with L2)
    # bot_module/depthsight_backtester.py
    def report_progress_event(
        self, event_type: str, message: str, data: Optional[Dict] = None
    ):
        """
        Collects and sends progress data via callback.
        Extended to include data on new trades and equity points.
        """
        if not self.progress_callback:
            return

        # Base event for the log
        event = {
            "timestamp": self._timestamp_dt_current_candle.isoformat(),
            "type": event_type.upper(),
            "message": message,
            "data": data or {},
        }
        self.progress_meta["events"].append(event)
        if len(self.progress_meta["events"]) > 150:
            self.progress_meta["events"].pop(0)

        # Aggregated KPIs
        progress_percent = (
            (self._i_current_candle - self.final_loop_start_index + 1)
            / (len(self.klines) - self.final_loop_start_index)
        ) * 100
        self.progress_meta["kpis"] = {
            "progress": round(max(0.0, min(100.0, progress_percent)), 2),
            "current_date": self._timestamp_dt_current_candle.strftime(
                "%Y-%m-%d %H:%M"
            ),
            "balance": round(self.current_balance, 2),
            "pnl": round(self.stats["total_pnl"], 2),
            "trades": self.stats["trades"],
            "wins": self.stats["wins"],
            "losses": self.stats["losses"],
            "win_rate": round(
                (self.stats["wins"] / self.stats["trades"] * 100)
                if self.stats["trades"] > 0
                else 0,
                1,
            ),
            "max_drawdown": round(self.stats["max_drawdown"] * 100, 2),
        }

        # Checking if there is a new trade to send
        if self._latest_closed_trade_for_report:
            self.progress_meta["new_trade"] = self._latest_closed_trade_for_report
            self._latest_closed_trade_for_report = None  # Clearing after adding

        # Checking if there is a new equity point to send
        if self._latest_equity_point_for_report:
            ts, val = self._latest_equity_point_for_report
            # Serialize for JSON
            self.progress_meta["equity_point"] = (ts.isoformat(), val)
            self._latest_equity_point_for_report = None  # Clearing after adding

        # Create a copy of metadata for safe asynchronous sending
        meta_to_send = self.progress_meta.copy()

        asyncio.create_task(self.progress_callback(meta=meta_to_send))
        self.last_progress_update_time = time.time()

        # Clear metadata of one-time events in the original dictionary
        if "new_trade" in self.progress_meta:
            del self.progress_meta["new_trade"]
        if "equity_point" in self.progress_meta:
            del self.progress_meta["equity_point"]

    async def _load_1s_klines_for_window(
        self, symbol: str, start_dt: datetime, end_dt: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Asynchronously loads partitioned 1-second data for the specified time window.
        """
        try:
            # Replicating path logic from download_pipeline.py
            base_path = (
                Path("data_storage")
                / "binance"
                / "futures"
                / symbol.upper()
                / "klines_1s"
            )

            months_to_load = set()
            # Ensure timezone awareness for comparison
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)

            # Iterate through months in the range
            current_month_start = date(start_dt.year, start_dt.month, 1)
            while current_month_start <= end_dt.date():
                months_to_load.add(current_month_start)
                current_month_start = (
                    current_month_start + timedelta(days=32)
                ).replace(day=1)

            df_list = []
            loop = asyncio.get_running_loop()

            # Creating a list of tasks for parallel file reading
            tasks = []
            for month_key in sorted(list(months_to_load)):
                partition_path = (
                    base_path
                    / f"year={month_key.year}"
                    / f"month={month_key.month}"
                    / "data.parquet"
                )
                if partition_path.exists():
                    # functools.partial is needed to pass arguments to a function executed in another thread
                    read_task = loop.run_in_executor(
                        None, functools.partial(pd.read_parquet, partition_path)
                    )
                    tasks.append(read_task)

            # Waiting for all read tasks to complete
            loaded_dfs = await asyncio.gather(*tasks)
            df_list = [df for df in loaded_dfs if df is not None]

            if not df_list:
                logger.warning(
                    f"1s data not found for {symbol} in range {start_dt}-{end_dt}"
                )
                return None

            # concat and sorting can also be long, we move them out too
            def _concat_and_sort(dfs):
                return pd.concat(dfs).sort_index()

            combined_df = await loop.run_in_executor(None, _concat_and_sort, df_list)

            return combined_df[
                (combined_df.index >= start_dt) & (combined_df.index < end_dt)
            ]
        except Exception as e:
            logger.error(
                f"[Backtester:{symbol}] Error during asynchronous loading of 1s data: {e}",
                exc_info=True,
            )
            return None

    def _get_failed_filter_from_trace(self, trace: Dict[str, Any]) -> Optional[str]:
        if not isinstance(trace, dict):
            return None

        nodes_to_visit = [trace]
        while nodes_to_visit:
            current_node = nodes_to_visit.pop(0)

            if current_node.get("result") is False:
                # If it's a leaf node, we found our culprit
                if not current_node.get("children"):
                    return current_node.get("id")

                # Otherwise, add children to the queue
                if "children" in current_node:
                    nodes_to_visit.extend(current_node.get("children", []))
        return None

    async def run_async(self) -> Optional[Dict[str, Any]]:
        """
        Main asynchronous backtesting loop.
        Processes candles, generates signals, manages positions, and tracks progress.
        """
        if self.klines is None or self.klines.empty:
            logger_backtest.error(
                "Kline data missing or empty. Cannot run DepthSight backtest."
            )
            return self._calculate_final_kpis_for_mode()

        if (
            not isinstance(self.klines.index, pd.DatetimeIndex)
            or self.klines.index.tz is None
        ):
            logger_backtest.error(
                "Kline index invalid or missing timezone. Cannot run DepthSight backtest."
            )
            return self._calculate_final_kpis_for_mode()

        if (
            self.kline_data_array is None
            or self.kline_index_map is None
            or not self.kline_index_map
        ):
            logger_backtest.error(
                "kline_data_array or kline_index_map not initialized properly. Cannot run."
            )
            return self._calculate_final_kpis_for_mode()

        atr_col_name = f"ATR_{self.atr_period}"
        if (
            atr_col_name not in self.klines.columns
            or atr_col_name not in self.kline_index_map
        ):
            logger_backtest.error(
                f"ATR column '{atr_col_name}' not found. Cannot run DepthSight backtest."
            )
            return self._calculate_final_kpis_for_mode()

        is_ml_mode = self.ml_training_mode
        is_ml_data_collection_mode = self.ml_training_mode and self.collect_data_mode

        if not is_ml_mode and self.strategy_instance is None:
            logger_backtest.error("Strategy instance not initialized. Cannot run.")
            return self._calculate_final_kpis_for_mode()

        if (
            is_ml_mode
            and not is_ml_data_collection_mode
            and self.ml_agent_instance is None
        ):
            logger_backtest.error(
                "ML agent instance not provided for ML training/simulation. Cannot run."
            )
            return self._calculate_final_kpis_for_mode()

        if self._log_ml_confirmation_data and self._feature_extractor_instance is None:
            self._log_ml_confirmation_data = False

        if self._enable_ml_confirmation_backtest and (
            self._ml_confirmation_feature_extractor is None
            or self._ml_confirmation_pipeline is None
        ):
            self._enable_ml_confirmation_backtest = False

        backtest_position: Optional[BacktestPositionState] = None
        pending_limit_order: Optional[Dict[str, Any]] = None
        collected_training_data_for_main_ml: List[Dict[str, Any]] = []

        max_indicator_period = 0
        if self.required_indicators:
            try:
                periods = [
                    cfg.get("period", 0)
                    for cfg in self.required_indicators.values()
                    if isinstance(cfg, dict)
                    and isinstance(cfg.get("period"), (int, float))
                ]
                if periods:
                    max_indicator_period = max(periods)
            except Exception as e_max_ind:
                logger_backtest.error(
                    f"Error determining max_indicator_period: {e_max_ind}",
                    exc_info=True,
                )
                max_indicator_period = 100

        indicator_warmup_bars = max(self.atr_period + 1, max_indicator_period + 1, 10)
        trading_start_index_from_dt = 0

        if self.actual_trading_start_dt:
            try:
                start_dt_utc = (
                    self.actual_trading_start_dt.astimezone(timezone.utc)
                    if self.actual_trading_start_dt.tzinfo
                    else self.actual_trading_start_dt.replace(tzinfo=timezone.utc)
                )
                candle_duration_td = timedelta(minutes=1)
                if len(self.klines.index) > 1:
                    time_diff = self.klines.index[1] - self.klines.index[0]
                    candle_duration_td = timedelta(seconds=time_diff.total_seconds())

                for idx, ts_open in enumerate(self.klines.index):
                    ts_close_approx = ts_open + candle_duration_td
                    if ts_close_approx >= start_dt_utc:
                        trading_start_index_from_dt = idx
                        break
                else:
                    logger_backtest.error(
                        f"Actual start date {start_dt_utc} is after all data. No trading period."
                    )
                    return self._calculate_final_kpis_for_mode()
                logger_backtest.info(
                    f"Trading will start from index: {trading_start_index_from_dt} (Timestamp: {self.klines.index[trading_start_index_from_dt]})"
                )
            except Exception as e_search:
                logger_backtest.error(
                    f"Error finding trading start index based on actual_trading_start_dt: {e_search}. Starting after warmup.",
                    exc_info=True,
                )
                trading_start_index_from_dt = 0

        loop_start_index = indicator_warmup_bars
        if is_ml_mode and not is_ml_data_collection_mode:
            max_feature_period = 100
            if self.ml_agent_instance and hasattr(
                self.ml_agent_instance, "feature_extractor"
            ):
                fe = self.ml_agent_instance.feature_extractor
                all_fe_periods = []
                kline_cfgs = getattr(fe, "kline_feature_configs", {})
                agg_cfgs = getattr(fe, "aggtrade_feature_configs", {})
                if not isinstance(kline_cfgs, dict):
                    kline_cfgs = {}
                if not isinstance(agg_cfgs, dict):
                    agg_cfgs = {}
                for cfg_dict in [kline_cfgs, agg_cfgs]:
                    for cfg_val in cfg_dict.values():
                        if (
                            isinstance(cfg_val, dict)
                            and "period" in cfg_val
                            and cfg_val["period"] is not None
                        ):
                            try:
                                all_fe_periods.append(int(cfg_val["period"]))
                            except Exception:
                                pass
                        if (
                            isinstance(cfg_val, dict)
                            and "window_size" in cfg_val
                            and cfg_val["window_size"] is not None
                        ):
                            try:
                                all_fe_periods.append(int(cfg_val["window_size"]))
                            except Exception:
                                pass
                if all_fe_periods:
                    max_feature_period = max(all_fe_periods, default=100)

            required_ml_lookahead = self._ml_label_lookahead + 1
            loop_start_index = max(
                loop_start_index, max_feature_period, required_ml_lookahead
            )

        self.final_loop_start_index = max(loop_start_index, trading_start_index_from_dt)

        if self.final_loop_start_index >= len(self.klines):
            logger_backtest.error(
                f"Loop start index ({self.final_loop_start_index}) is out of bounds (klines: {len(self.klines)})."
            )
            return self._calculate_final_kpis_for_mode()

        logger_backtest.info(
            f"[DepthSightBacktester.run_async] Effective klines length: {len(self.klines)}, final_loop_start_index: {self.final_loop_start_index}"
        )

        mode_str_log = (
            "ML_TRAINING_SIM"
            if (
                is_ml_mode
                and not is_ml_data_collection_mode
                and self._ml_simulate_trades
            )
            else (
                "ML_DATA_COLLECTION"
                if is_ml_data_collection_mode
                else (
                    "OPTIMIZATION_WITH_ML_CONFIRM"
                    if (not is_ml_mode and self._enable_ml_confirmation_backtest)
                    else (
                        "OPTIMIZATION_WITH_ML_LOG"
                        if (not is_ml_mode and self._log_ml_confirmation_data)
                        else "DEPTHSIGHT_BACKTEST"
                    )
                )
            )
        )
        logger_backtest.info(
            f"Running DepthSight backtest for {self.strategy_name} on {self.symbol} ({self.candle_tf}). Mode: {mode_str_log}."
        )
        logger_backtest.info(
            f"Total klines: {len(self.klines)}. Loop Start Index: {self.final_loop_start_index}"
        )

        execution_start_time = time.time()

        if self.final_loop_start_index < len(self.klines):
            first_loop_timestamp_dt = self.klines.index[
                self.final_loop_start_index
            ].to_pydatetime()
            self._check_and_reset_daily_stats(first_loop_timestamp_dt)

        self.last_processed_kline_close = 0.0
        kline_index_list_pd = self.klines.index

        prev_pair_info_enriched: Optional[Dict[str, Any]] = None

        for i in range(self.final_loop_start_index, len(self.klines)):
            if self._is_liquidated:
                break
            try:
                self._i_current_candle = i
                self._timestamp_dt_current_candle = kline_index_list_pd[
                    i
                ].to_pydatetime()
                current_kline_row_numpy = self.kline_data_array[i]
                timestamp_dt = self._timestamp_dt_current_candle
                current_event_ts_float = timestamp_dt.timestamp()

                def get_val(name, default=np.nan):
                    return (
                        current_kline_row_numpy[self.kline_index_map[name]]
                        if name in self.kline_index_map
                        else default
                    )

                k_open = get_val("open")
                k_high = get_val("high")
                k_low = get_val("low")
                k_close = get_val("close")
                k_volume = get_val("volume")

                if (
                    np.isnan(k_open)
                    or np.isnan(k_high)
                    or np.isnan(k_low)
                    or np.isnan(k_close)
                    or np.isnan(k_volume)
                ):
                    prev_pair_info_enriched = None
                    continue

                self.last_processed_kline_close = k_close
                self._check_and_reset_daily_stats(timestamp_dt)

                if self.stats["peak_equity"] > 1e-9:
                    drawdown = (
                        self.stats["peak_equity"] - self.current_balance
                    ) / self.stats["peak_equity"]
                    self.stats["max_drawdown"] = max(
                        self.stats["max_drawdown"], drawdown
                    )
                self.stats["peak_equity"] = max(
                    self.stats["peak_equity"], self.current_balance
                )

                current_time = time.time()
                if self.progress_callback and (
                    current_time - self.last_progress_update_time > 1
                ):
                    self.report_progress_event("PROGRESS", "Backtest is running...")

                current_kline_data_dict = {
                    col: current_kline_row_numpy[idx]
                    for col, idx in self.kline_index_map.items()
                }
                current_atr = self._get_current_atr(current_kline_data_dict)
                if current_atr <= 1e-9:
                    prev_pair_info_enriched = None
                    continue

                pair_info_enriched = {
                    "symbol": self.symbol,
                    "atr": current_atr,
                    "last_price": k_close,
                    "tick_size": self.exchange_info.get(
                        "tick_size", self.config.DEFAULT_TICK_SIZE
                    ),
                    "lot_params": self.exchange_info.get("lot_params"),
                    "min_notional": self.exchange_info.get("min_notional"),
                    **current_kline_data_dict,
                    "current_candle_index": i,
                    "time_since_last_signal_sec": (
                        current_event_ts_float
                        - self._last_signal_timestamp_per_symbol_strategy.get(
                            (self.symbol, self.strategy_name), 0.0
                        )
                    )
                    if self._last_signal_timestamp_per_symbol_strategy.get(
                        (self.symbol, self.strategy_name)
                    )
                    else float("inf"),
                    "candle_timeframe": self.candle_tf,
                    "timestamp_dt": timestamp_dt,
                    "is_volume_spike": get_val("is_volume_spike", False),
                    "relative_volume": get_val("relative_volume", 1.0),
                }

                # Slice dataframes to prevent lookahead bias in backtesting and fix scalar indicators
                market_data_full = {}
                for key, df_item in self.historical_data.items():
                    if df_item is not None:
                        if isinstance(df_item, pd.DataFrame) and not df_item.empty:
                            try:
                                idx_at_ts_arr = df_item.index.get_indexer(
                                    [timestamp_dt], method="ffill"
                                )
                                if idx_at_ts_arr[0] != -1:
                                    market_data_full[key] = df_item.iloc[
                                        : idx_at_ts_arr[0] + 1
                                    ]
                                else:
                                    market_data_full[key] = df_item.iloc[:0]
                            except Exception:
                                market_data_full[key] = df_item
                        else:
                            market_data_full[key] = df_item

                if self.agg_trades is not None and not self.agg_trades.empty:
                    try:
                        idx_agg_arr = self.agg_trades.index.get_indexer(
                            [timestamp_dt], method="ffill"
                        )
                        if idx_agg_arr[0] != -1:
                            market_data_full["aggTrade"] = self.agg_trades.iloc[
                                : idx_agg_arr[0] + 1
                            ]
                        else:
                            market_data_full["aggTrade"] = self.agg_trades.iloc[:0]
                    except Exception:
                        market_data_full["aggTrade"] = self.agg_trades

                if self.open_interest is not None and not self.open_interest.empty:
                    try:
                        idx_oi_arr = self.open_interest.index.get_indexer(
                            [timestamp_dt], method="ffill"
                        )
                        if idx_oi_arr[0] != -1:
                            market_data_full["open_interest"] = self.open_interest.iloc[
                                : idx_oi_arr[0] + 1
                            ]
                        else:
                            market_data_full["open_interest"] = self.open_interest.iloc[
                                :0
                            ]
                    except Exception:
                        market_data_full["open_interest"] = self.open_interest

                # 1. Processing L2 and Aggregated (bookDepth) data
                short_circuit_triggered = False
                if (
                    self.strategy_instance
                    and hasattr(self.strategy_instance, "check_fast_foundations")
                    and self.foundation_weights
                ):
                    (
                        fast_foundations_results,
                        _,
                    ) = await self.strategy_instance.check_fast_foundations(
                        pair_info_enriched.copy(), market_data_full.copy()
                    )
                    fast_weight = 0.0
                    for foundation_key, is_met in fast_foundations_results.items():
                        if is_met and foundation_key != "orderbook":
                            fast_weight += self.foundation_weights.get(
                                foundation_key, 0.0
                            )
                    if (
                        fast_weight + self.max_possible_l2_weight
                    ) < self.min_total_foundation_weight_threshold:
                        short_circuit_triggered = True
                        logger.debug(
                            f"[{self.symbol}] Short-circuit triggered. Fast weight ({fast_weight}) + max L2 weight ({self.max_possible_l2_weight}) < Threshold ({self.min_total_foundation_weight_threshold})"
                        )

                l2_snapshot = None
                if short_circuit_triggered:
                    market_data_full["depth_trading"] = None
                elif self.l2_market_impact_enabled and self.l2_reader:
                    l2_snapshot = await self.l2_reader.get_book_snapshot_at(
                        self.symbol, int(timestamp_dt.timestamp() * 1000)
                    )
                    market_data_full["depth_trading"] = l2_snapshot or {}
                else:
                    market_data_full["depth_trading"] = {}

                # Parsing bookDepth into 'depth_analysis' for simulation and strategy
                market_data_full["depth_analysis"] = {}
                if "bookDepth" in self.historical_data and isinstance(
                    self.historical_data["bookDepth"], pd.DataFrame
                ):
                    bookdepth_df = self.historical_data["bookDepth"]
                    if not bookdepth_df.empty and isinstance(
                        bookdepth_df.index, pd.DatetimeIndex
                    ):
                        candle_start_time = kline_index_list_pd[i]
                        candle_end_time = (
                            kline_index_list_pd[i + 1]
                            if i + 1 < len(kline_index_list_pd)
                            else timestamp_dt + timedelta(minutes=1)
                        )

                        snapshot_in_candle = bookdepth_df[
                            (bookdepth_df.index >= candle_start_time)
                            & (bookdepth_df.index < candle_end_time)
                        ]

                        if not snapshot_in_candle.empty:
                            last_ts_in_candle = snapshot_in_candle.index.max()
                            snapshot_series = snapshot_in_candle.loc[last_ts_in_candle]

                            bids = []
                            asks = []

                            try:
                                # If loc returned a DataFrame (multiple rows with the same timestamp), take the last one
                                if isinstance(snapshot_series, pd.DataFrame):
                                    snapshot_series = snapshot_series.iloc[-1]

                                # Iterating through levels from 1 to 5
                                # IMPORTANT: use level_idx to avoid overwriting the 'i' variable of the main loop!
                                for level_idx in range(1, 6):
                                    # Processing BIDS (side 'm' - minus)
                                    bid_price_col = f"depth_m{level_idx}"
                                    bid_notional_col = f"notional_m{level_idx}"

                                    if (
                                        bid_price_col in snapshot_series.index
                                        and bid_notional_col in snapshot_series.index
                                    ):
                                        price = snapshot_series[bid_price_col]
                                        notional = snapshot_series[bid_notional_col]
                                        if (
                                            pd.notna(price)
                                            and pd.notna(notional)
                                            and price > 0
                                            and notional > 0
                                        ):
                                            bids.append(
                                                {
                                                    "price": float(price),
                                                    "notional": float(notional),
                                                    "quantity": float(notional)
                                                    / float(price),
                                                }
                                            )

                                    # Processing ASKS (side 'p' - plus)
                                    ask_price_col = f"depth_p{level_idx}"
                                    ask_notional_col = f"notional_p{level_idx}"

                                    if (
                                        ask_price_col in snapshot_series.index
                                        and ask_notional_col in snapshot_series.index
                                    ):
                                        price = snapshot_series[ask_price_col]
                                        notional = snapshot_series[ask_notional_col]
                                        if (
                                            pd.notna(price)
                                            and pd.notna(notional)
                                            and price > 0
                                            and notional > 0
                                        ):
                                            asks.append(
                                                {
                                                    "price": float(price),
                                                    "notional": float(notional),
                                                    "quantity": float(notional)
                                                    / float(price),
                                                }
                                            )

                            except Exception as e_parse:
                                logger.error(
                                    f"[BookDepth Parser] Error parsing order book data of the new format: {e_parse}",
                                    exc_info=True,
                                )

                            bids.sort(key=lambda x: x["price"], reverse=True)
                            asks.sort(key=lambda x: x["price"])

                            market_data_full["depth_analysis"] = {
                                "bids": bids,
                                "asks": asks,
                            }

                # 2. LIMIT ORDER PROCESSING (if there is no open position)
                if backtest_position is None and pending_limit_order:
                    limit_price_ord = pending_limit_order["price"]
                    limit_side_ord = pending_limit_order["side"]
                    limit_sl_ord = pending_limit_order["stop_loss"]
                    filled_price_limit_ord = None

                    if (
                        limit_side_ord == SignalDirection.LONG
                        and k_low <= limit_price_ord
                    ):
                        filled_price_limit_ord = min(k_open, limit_price_ord)
                    elif (
                        limit_side_ord == SignalDirection.SHORT
                        and k_high >= limit_price_ord
                    ):
                        filled_price_limit_ord = max(k_open, limit_price_ord)

                    if filled_price_limit_ord is not None:
                        sim_result_limit_entry: OrderExecutionResult = (
                            simulate_market_order_execution(
                                order_quantity=pending_limit_order["quantity"],
                                direction=limit_side_ord,
                                market_data_for_sim=market_data_full,
                                ideal_entry_price=filled_price_limit_ord,
                                commission_pct=self.execution_config["commission_pct"],
                                kline_close_for_fallback=k_close,
                                simple_slippage_pct=self.execution_config.get(
                                    "slippage_pct"
                                ),
                            )
                        )

                        actual_entry_price = sim_result_limit_entry.avg_fill_price
                        actual_filled_quantity = sim_result_limit_entry.filled_quantity

                        if (
                            actual_filled_quantity > 0
                            and actual_entry_price is not None
                        ):
                            is_slippage_past_sl = self._is_price_beyond_stop_loss(
                                limit_side_ord,
                                actual_entry_price,
                                limit_sl_ord,
                            )

                            if is_slippage_past_sl:
                                logger.warning(
                                    f"[{self.symbol}] Limit Order rejected: Entry price ({actual_entry_price:.4f}) "
                                    f"after slippage is beyond stop-loss "
                                    f"({self._format_optional_price(limit_sl_ord)})."
                                )
                                self.structured_report["event_counters"]["rejections"][
                                    "by_slippage_beyond_sl"
                                ] += 1
                            else:
                                signal_details_limit_ord = pending_limit_order[
                                    "signal_details"
                                ]
                                signal_details_limit_ord["commission_entry"] = (
                                    sim_result_limit_entry.actual_commission_paid
                                )

                                backtest_position = BacktestPositionState(
                                    symbol=self.symbol,
                                    direction=limit_side_ord,
                                    entry_price=actual_entry_price,
                                    initial_quantity=actual_filled_quantity,
                                    remaining_quantity=actual_filled_quantity,
                                    entry_time=timestamp_dt,
                                    strategy=pending_limit_order["strategy"],
                                    initial_stop_loss=limit_sl_ord,
                                    initial_take_profit=pending_limit_order[
                                        "take_profit"
                                    ],
                                    current_sl_price=limit_sl_ord,
                                    no_stop_loss=bool(
                                        pending_limit_order.get("no_stop_loss")
                                        or (
                                            isinstance(signal_details_limit_ord, dict)
                                            and signal_details_limit_ord.get(
                                                "no_stop_loss"
                                            )
                                            is True
                                        )
                                        or limit_sl_ord is None
                                    ),
                                    move_sl_to_be_enabled=signal_details_limit_ord.get(
                                        "move_sl_to_be", False
                                    ),
                                    partial_targets=[
                                        (pt.price, pt.fraction, False)
                                        for pt in pending_limit_order.get(
                                            "partial_targets", []
                                        )
                                        or []
                                    ],
                                    entry_atr=pending_limit_order.get("entry_atr"),
                                    signal_details=signal_details_limit_ord,
                                    client_order_id=pending_limit_order.get(
                                        "client_order_id"
                                    ),
                                    initial_risk_usd_planned=pending_limit_order.get(
                                        "initial_risk_usd_planned"
                                    ),
                                    ideal_entry_price_l2=sim_result_limit_entry.ideal_entry_price,
                                    entry_slippage_usd=sim_result_limit_entry.slippage_usd,
                                    entry_commission_paid=sim_result_limit_entry.actual_commission_paid,
                                    entry_fill_type=sim_result_limit_entry.fill_type.value,
                                    executions=[
                                        {
                                            "timestamp": timestamp_dt,
                                            "price": actual_entry_price,
                                            "quantity": actual_filled_quantity,
                                            "type": "ENTRY",
                                        }
                                    ],
                                )
                                self.structured_report["event_counters"][
                                    "trades_opened"
                                ] += 1
                                self.current_balance -= (
                                    sim_result_limit_entry.actual_commission_paid
                                )
                                self.equity_curve.append(
                                    (timestamp_dt, self.current_balance)
                                )
                                self.stats["peak_equity"] = max(
                                    self.stats["peak_equity"], self.current_balance
                                )
                                self.report_progress_event(
                                    "POSITION_OPEN",
                                    f"Opened {backtest_position.direction.name} position for {self.symbol} (limit order). Entry: {backtest_position.entry_price:.4f}",
                                    {
                                        "symbol": backtest_position.symbol,
                                        "direction": backtest_position.direction.name,
                                        "entry_price": backtest_position.entry_price,
                                        "qty": backtest_position.initial_quantity,
                                    },
                                )
                                self._bt_last_position_close_time_per_symbol[
                                    self.symbol
                                ] = 0

                        pending_limit_order = None

                # 3. OPEN POSITION MANAGEMENT
                if backtest_position:
                    self._process_grid_orders_for_candle(
                        position=backtest_position,
                        pair_info=pair_info_enriched,
                        market_data=market_data_full,
                    )

                    import copy

                    position_state_before_management = copy.deepcopy(backtest_position)

                    exit_reason: Optional[str] = None
                    ideal_exit_price: Optional[float] = None
                    exit_is_limit_order = False

                    pos_before_update = position_state_before_management

                    # Mid-candle liquidation check (worst-case unrealized PnL)
                    worst_price_for_liq = (
                        k_low
                        if backtest_position.direction == SignalDirection.LONG
                        else k_high
                    )
                    unrealized_pnl_liq = (
                        (worst_price_for_liq - backtest_position.entry_price)
                        * backtest_position.remaining_quantity
                        if backtest_position.direction == SignalDirection.LONG
                        else (backtest_position.entry_price - worst_price_for_liq)
                        * backtest_position.remaining_quantity
                    )

                    if self.current_balance + unrealized_pnl_liq <= 0:
                        exit_reason = "LIQUIDATION"
                        ideal_exit_price = worst_price_for_liq
                    elif self._has_active_stop_loss(
                        pos_before_update.current_sl_price
                    ) and self._is_price_beyond_stop_loss(
                        pos_before_update.direction,
                        k_low
                        if pos_before_update.direction == SignalDirection.LONG
                        else k_high,
                        pos_before_update.current_sl_price,
                    ):
                        exit_reason = (
                            "SL_AT_BE"
                            if pos_before_update.is_stop_at_be
                            else "STOP_LOSS"
                        )
                        ideal_exit_price = pos_before_update.current_sl_price
                    elif pos_before_update.initial_take_profit and (
                        (
                            pos_before_update.direction == SignalDirection.LONG
                            and k_high >= pos_before_update.initial_take_profit
                        )
                        or (
                            pos_before_update.direction == SignalDirection.SHORT
                            and k_low <= pos_before_update.initial_take_profit
                        )
                    ):
                        exit_reason = "TAKE_PROFIT"
                        ideal_exit_price = pos_before_update.initial_take_profit
                        exit_is_limit_order = True

                    if exit_reason and ideal_exit_price is not None:
                        pos_to_close = position_state_before_management
                        timestamp_exit = timestamp_dt
                        final_exit_price: float
                        commission_exit: float
                        slippage_usd: float
                        qty_closed: float

                        if exit_is_limit_order:
                            final_exit_price = ideal_exit_price
                            qty_closed = pos_to_close.remaining_quantity
                            commission_exit = abs(
                                final_exit_price
                                * qty_closed
                                * self.execution_config["commission_pct"]
                            )
                            slippage_usd = 0.0
                        else:
                            sim_result_exit = simulate_market_order_execution(
                                order_quantity=float(pos_to_close.remaining_quantity),
                                direction=SignalDirection.SHORT
                                if pos_to_close.direction == SignalDirection.LONG
                                else SignalDirection.LONG,
                                market_data_for_sim=market_data_full,
                                ideal_entry_price=float(
                                    ideal_exit_price
                                ),  # Using stop/take price as ideal
                                commission_pct=self.execution_config["commission_pct"],
                                kline_close_for_fallback=float(
                                    ideal_exit_price
                                ),  # Fallback to the SL/TP price itself
                                simple_slippage_pct=self.execution_config.get(
                                    "slippage_pct"
                                ),
                            )
                            final_exit_price = (
                                sim_result_exit.avg_fill_price or ideal_exit_price
                            )
                            qty_closed = sim_result_exit.filled_quantity
                            commission_exit = sim_result_exit.actual_commission_paid
                            slippage_usd = sim_result_exit.slippage_usd

                        total_pnl_gross = 0.0
                        if qty_closed > 0:
                            pnl = (
                                (final_exit_price - pos_to_close.entry_price)
                                * qty_closed
                                if pos_to_close.direction == SignalDirection.LONG
                                else (pos_to_close.entry_price - final_exit_price)
                                * qty_closed
                            )
                            total_pnl_gross = float(pnl)

                        total_commission = (
                            pos_to_close.entry_commission_paid + commission_exit
                        )
                        
                        funding_rate = float(getattr(config, "BACKTEST_FUNDING_RATE_8H", 0.0001))
                        temp_final_executions = [
                            exec_item
                            for exec_item in pos_to_close.executions
                            if exec_item.get("type") == "ENTRY"
                        ]
                        temp_final_executions.append(
                            {
                                "timestamp": timestamp_exit,
                                "price": final_exit_price,
                                "quantity": qty_closed,
                                "type": "EXIT",
                            }
                        )
                        funding_pnl = calculate_position_funding_pnl(
                            executions=temp_final_executions,
                            is_short=(pos_to_close.direction == SignalDirection.SHORT),
                            funding_rate=funding_rate
                        )
                        
                        net_pnl = total_pnl_gross - total_commission + funding_pnl
                        pnl_for_balance_update = total_pnl_gross - commission_exit + funding_pnl

                        self.current_balance += pnl_for_balance_update

                        # Liquidation check after balance update
                        if self._check_liquidation(timestamp_dt=timestamp_exit):
                            # Liquidation recorded, but we will log the trade before stopping
                            pass
                        else:
                            self.equity_curve.append(
                                (timestamp_exit, float(self.current_balance))
                            )

                        self.stats["trades"] += 1
                        if net_pnl > 0:
                            self.stats["wins"] += 1
                        else:
                            self.stats["losses"] += 1
                        self.stats["total_pnl"] += net_pnl
                        self.stats["total_commission"] += total_commission
                        self._check_risk_limits_after_trade(net_pnl, timestamp_exit)
                        self._bt_last_position_close_time_per_symbol[self.symbol] = (
                            current_event_ts_float
                        )

                        final_executions = temp_final_executions

                        trade_log_entry = {
                            "timestamp": timestamp_exit,
                            "entry_time": pos_to_close.entry_time,
                            "symbol": pos_to_close.symbol,
                            "strategy": pos_to_close.strategy,
                            "direction": pos_to_close.direction.name,
                            "entry_price": float(pos_to_close.entry_price),
                            "exit_price": float(final_exit_price),
                            "avg_weighted_exit_price": float(final_exit_price),
                            "num_partial_tp_hits": getattr(
                                pos_to_close, "num_partial_tp_hits", 0
                            ),
                            "quantity": float(pos_to_close.initial_quantity),
                            "pnl": float(net_pnl),
                            "funding_pnl": float(funding_pnl),
                            "exit_reason": exit_reason,
                            "commission": float(total_commission),
                            "sl_level": float(pos_to_close.initial_stop_loss)
                            if pos_to_close.initial_stop_loss is not None
                            else None,
                            "tp_level": float(pos_to_close.initial_take_profit or 0),
                            "client_order_id": pos_to_close.client_order_id,
                            "l2_entry_slippage_usd": pos_to_close.entry_slippage_usd,
                            "l2_exit_slippage_usd": slippage_usd,
                            "entry_fill_type": getattr(
                                pos_to_close, "entry_fill_type", None
                            ),
                            "moved_to_be": getattr(
                                pos_to_close, "is_stop_at_be", False
                            ),
                        }
                        self.trade_log.append(trade_log_entry)
                        self._latest_closed_trade_for_report = trade_log_entry
                        self._latest_equity_point_for_report = (
                            timestamp_exit,
                            self.current_balance,
                        )

                        await self._close_position(
                            position_data={
                                **pos_to_close.__dict__,
                                "pnl": net_pnl,
                                "executions": final_executions,
                            },
                            exit_price=final_exit_price,
                            reason=exit_reason,
                            timestamp=timestamp_exit,
                            total_commission_override=total_commission,
                            l2_exit_slippage_usd=slippage_usd,
                            l2_filled_qty_at_exit=qty_closed,
                        )
                        if self.strategy_instance:
                            self.strategy_instance.notify_closure(i)
                        backtest_position = None

                    if backtest_position:
                        (
                            updated_position,
                            management_exit_details,
                        ) = await self.strategy_instance.manage_position(
                            backtest_position,
                            pair_info_enriched,
                            market_data_full,
                            prev_pair_info_enriched,
                        )
                        backtest_position = updated_position

                        if management_exit_details:
                            pos_to_close_mgmt = backtest_position
                            timestamp_exit_mgmt = timestamp_dt
                            exit_price_ideal_mgmt = management_exit_details.get(
                                "exit_price", k_close
                            )
                            reason_mgmt = management_exit_details.get(
                                "reason", "MANAGEMENT_EXIT"
                            )

                            sim_result_mgmt = simulate_market_order_execution(
                                order_quantity=float(
                                    pos_to_close_mgmt.remaining_quantity
                                ),
                                direction=SignalDirection.SHORT
                                if pos_to_close_mgmt.direction == SignalDirection.LONG
                                else SignalDirection.LONG,
                                market_data_for_sim=market_data_full,
                                ideal_entry_price=exit_price_ideal_mgmt,
                                commission_pct=self.execution_config["commission_pct"],
                                kline_close_for_fallback=k_close,
                                simple_slippage_pct=self.execution_config.get(
                                    "slippage_pct"
                                ),
                            )

                            final_exit_price_mgmt = (
                                sim_result_mgmt.avg_fill_price or exit_price_ideal_mgmt
                            )
                            qty_closed_mgmt = sim_result_mgmt.filled_quantity
                            commission_exit_mgmt = (
                                sim_result_mgmt.actual_commission_paid
                            )
                            slippage_usd_mgmt = sim_result_mgmt.slippage_usd

                            total_pnl_gross_mgmt = 0.0
                            if qty_closed_mgmt > 0:
                                pnl_mgmt = (
                                    (
                                        final_exit_price_mgmt
                                        - pos_to_close_mgmt.entry_price
                                    )
                                    * qty_closed_mgmt
                                    if pos_to_close_mgmt.direction
                                    == SignalDirection.LONG
                                    else (
                                        pos_to_close_mgmt.entry_price
                                        - final_exit_price_mgmt
                                    )
                                    * qty_closed_mgmt
                                )
                                total_pnl_gross_mgmt = float(pnl_mgmt)

                            total_commission_mgmt = (
                                pos_to_close_mgmt.entry_commission_paid
                                + commission_exit_mgmt
                            )
                            
                            funding_rate = float(getattr(config, "BACKTEST_FUNDING_RATE_8H", 0.0001))
                            temp_final_executions_mgmt = [
                                exec_item
                                for exec_item in pos_to_close_mgmt.executions
                                if exec_item.get("type") == "ENTRY"
                            ]
                            temp_final_executions_mgmt.append(
                                {
                                    "timestamp": timestamp_exit_mgmt,
                                    "price": final_exit_price_mgmt,
                                    "quantity": qty_closed_mgmt,
                                    "type": "EXIT",
                                }
                            )
                            funding_pnl_mgmt = calculate_position_funding_pnl(
                                executions=temp_final_executions_mgmt,
                                is_short=(pos_to_close_mgmt.direction == SignalDirection.SHORT),
                                funding_rate=funding_rate
                            )
                            
                            net_pnl_mgmt = total_pnl_gross_mgmt - total_commission_mgmt + funding_pnl_mgmt
                            pnl_for_balance_update_mgmt = (
                                total_pnl_gross_mgmt - commission_exit_mgmt + funding_pnl_mgmt
                            )

                            self.current_balance += pnl_for_balance_update_mgmt
                            self.equity_curve.append(
                                (timestamp_exit_mgmt, float(self.current_balance))
                            ) if not self._check_liquidation(
                                timestamp_dt=timestamp_exit_mgmt
                            ) else None
                            self.stats["trades"] += 1
                            if net_pnl_mgmt > 0:
                                self.stats["wins"] += 1
                            else:
                                self.stats["losses"] += 1
                            self.stats["total_pnl"] += net_pnl_mgmt
                            self.stats["total_commission"] += total_commission_mgmt
                            self._check_risk_limits_after_trade(
                                net_pnl_mgmt, timestamp_exit_mgmt
                            )
                            self._bt_last_position_close_time_per_symbol[
                                self.symbol
                            ] = current_event_ts_float

                            final_executions_mgmt = temp_final_executions_mgmt

                            trade_log_entry_mgmt = {
                                "timestamp": timestamp_exit_mgmt,
                                "entry_time": pos_to_close_mgmt.entry_time,
                                "symbol": pos_to_close_mgmt.symbol,
                                "strategy": pos_to_close_mgmt.strategy,
                                "direction": pos_to_close_mgmt.direction.name,
                                "entry_price": float(pos_to_close_mgmt.entry_price),
                                "exit_price": float(final_exit_price_mgmt),
                                "avg_weighted_exit_price": float(final_exit_price_mgmt),
                                "num_partial_tp_hits": getattr(
                                    pos_to_close_mgmt, "num_partial_tp_hits", 0
                                ),
                                "quantity": float(pos_to_close_mgmt.initial_quantity),
                                "pnl": float(net_pnl_mgmt),
                                "funding_pnl": float(funding_pnl_mgmt),
                                "exit_reason": reason_mgmt,
                                "commission": float(total_commission_mgmt),
                                "sl_level": float(pos_to_close_mgmt.initial_stop_loss)
                                if pos_to_close_mgmt.initial_stop_loss is not None
                                else None,
                                "tp_level": float(
                                    pos_to_close_mgmt.initial_take_profit or 0
                                ),
                                "client_order_id": pos_to_close_mgmt.client_order_id,
                                "l2_entry_slippage_usd": pos_to_close_mgmt.entry_slippage_usd,
                                "l2_exit_slippage_usd": slippage_usd_mgmt,
                                "entry_fill_type": getattr(
                                    pos_to_close_mgmt, "entry_fill_type", None
                                ),
                                "moved_to_be": getattr(
                                    pos_to_close_mgmt, "is_stop_at_be", False
                                ),
                            }
                            self.trade_log.append(trade_log_entry_mgmt)
                            self._latest_closed_trade_for_report = trade_log_entry_mgmt
                            self._latest_equity_point_for_report = (
                                timestamp_exit_mgmt,
                                self.current_balance,
                            )

                            await self._close_position(
                                position_data={
                                    **pos_to_close_mgmt.__dict__,
                                    "pnl": net_pnl_mgmt,
                                    "executions": final_executions_mgmt,
                                },
                                exit_price=final_exit_price_mgmt,
                                reason=reason_mgmt,
                                timestamp=timestamp_exit_mgmt,
                                total_commission_override=total_commission_mgmt,
                                l2_exit_slippage_usd=slippage_usd_mgmt,
                                l2_filled_qty_at_exit=qty_closed_mgmt,
                            )
                            backtest_position = None

                    if (
                        backtest_position
                        and hasattr(backtest_position, "scale_in_triggered")
                        and backtest_position.scale_in_triggered
                    ):
                        log_prefix_scale_in_bt = f"[{self.symbol}|SCALE_IN_BACKTESTER]"
                        logger.info(
                            f"{log_prefix_scale_in_bt} Flag 'scale_in_triggered' detected. Starting the addition process."
                        )
                        scale_in_params = backtest_position.scale_in_triggered
                        backtest_position.scale_in_triggered = None
                        add_size_pct = scale_in_params.get("add_size_pct", 100)
                        initial_risk = backtest_position.initial_risk_usd_planned
                        if initial_risk:
                            additional_quantity_adjusted = (
                                await self.rm.calculate_scaled_in_quantity(
                                    backtest_position,
                                    float(add_size_pct),
                                    float(k_close),
                                    self.exchange_info.get("lot_params"),
                                    self.exchange_info.get("min_notional"),
                                )
                            )
                            if (
                                additional_quantity_adjusted
                                and additional_quantity_adjusted > 0
                            ):
                                sim_result = simulate_market_order_execution(
                                    order_quantity=float(additional_quantity_adjusted),
                                    direction=backtest_position.direction,
                                    market_data_for_sim=market_data_full,
                                    ideal_entry_price=k_close,
                                    commission_pct=self.execution_config[
                                        "commission_pct"
                                    ],
                                    kline_close_for_fallback=k_close,
                                    simple_slippage_pct=self.execution_config.get(
                                        "slippage_pct"
                                    ),
                                )

                                if (
                                    sim_result.filled_quantity > 0
                                    and sim_result.avg_fill_price is not None
                                ):
                                    self._apply_position_addition_fill(
                                        position=backtest_position,
                                        fill_price=float(sim_result.avg_fill_price),
                                        filled_quantity=float(
                                            sim_result.filled_quantity
                                        ),
                                        commission_paid=float(
                                            sim_result.actual_commission_paid
                                        ),
                                        timestamp_dt=timestamp_dt,
                                        pair_info=pair_info_enriched,
                                        market_data=market_data_full,
                                        is_dca=bool(scale_in_params.get("is_dca")),
                                    )
                                    logger.info(
                                        f"[{self.symbol}] Position scaled in. "
                                        f"New avg price: {backtest_position.entry_price:.4f}, "
                                        f"new total qty: {backtest_position.remaining_quantity:.4f}, "
                                        f"entries: {backtest_position.number_of_entries}, "
                                        f"dca_sos: {backtest_position.dca_active_sos}"
                                    )

                # 4. SEARCH FOR NEW SIGNAL (only if there is no open position and no pending limit)
                if backtest_position and getattr(
                    backtest_position, "grid_init_triggered", None
                ):
                    self._initialize_grid_orders_for_position(
                        position=backtest_position,
                        grid_params=backtest_position.grid_init_triggered,
                        pair_info=pair_info_enriched,
                        market_data=market_data_full,
                    )

                if (
                    backtest_position is None
                    and pending_limit_order is None
                    and self.is_trading_allowed
                    and not self._is_liquidated
                ):
                    last_close_time_this_symbol = (
                        self._bt_last_position_close_time_per_symbol.get(
                            self.symbol, 0.0
                        )
                    )

                    if not (
                        current_event_ts_float - last_close_time_this_symbol
                        < self._bt_symbol_cooldown_duration
                    ):
                        # Oracle Filter Integration
                        if self.oracle and self.oracle_regime is not None:
                            try:
                                kline_history_slice = self.klines.iloc[: i + 1]
                                (
                                    current_regime,
                                    current_confidence,
                                ) = await self.oracle.get_current_regime(
                                    kline_history_slice
                                )

                                is_allowed = (
                                    current_regime == self.oracle_regime
                                    and current_confidence >= self.oracle_confidence
                                )

                                if not is_allowed:
                                    # Log only if there is something interesting (not every skip)
                                    # Can be done less frequently, for example, once every 100 candles, if there are too many logs
                                    if i % 10 == 0:
                                        logger_backtest.info(
                                            f"Oracle filter: REJECTED candle {i}. "
                                            f"Current(Regime={current_regime}, Conf={current_confidence:.1f}%) | "
                                            f"Required(Regime={self.oracle_regime}, Conf={self.oracle_confidence:.1f}%)"
                                        )
                                    prev_pair_info_enriched = pair_info_enriched.copy()
                                    continue  # Skip signal check for this candle
                                else:
                                    logger_backtest.warning(
                                        f"Oracle filter: PASSED candle {i}. "
                                        f"Current(Regime={current_regime}, Conf={current_confidence:.1f}%) matches "
                                        f"Required(Regime={self.oracle_regime}, Conf={self.oracle_confidence:.1f}%)"
                                    )

                            except Exception as e_oracle_filter:
                                logger_backtest.error(
                                    f"Error applying Oracle filter at candle {i}: {e_oracle_filter}",
                                    exc_info=True,
                                )
                                # Continue without Oracle filter if there's an error

                        market_data_for_strategy = market_data_full.copy()
                        if "bookDepth" in self.historical_data:
                            market_data_for_strategy["bookDepth"] = (
                                self.historical_data["bookDepth"]
                            )

                        signal: Optional[StrategySignal] = None
                        trace: Optional[Dict] = None
                        if self.strategy_instance:
                            is_visual_strategy = (
                                self.strategy_instance
                                and self.strategy_instance.NAME
                                == "VisualBuilderStrategy"
                            )
                            two_phase_candidate = (
                                is_visual_strategy
                                and getattr(
                                    self.strategy_instance,
                                    "max_possible_expensive_weight",
                                    0.0,
                                )
                                > 0
                            )
                            if two_phase_candidate:
                                (
                                    _,
                                    cheap_weight,
                                    _,
                                ) = await self.strategy_instance.check_signal(
                                    pair_info_enriched,
                                    market_data_full.copy(),
                                    prev_pair_info_enriched,
                                )
                                max_expensive_weight = getattr(
                                    self.strategy_instance,
                                    "max_possible_expensive_weight",
                                    0.0,
                                )
                                min_threshold = self.strategy_instance.min_total_foundation_weight_threshold
                                if (
                                    cheap_weight + max_expensive_weight
                                ) >= min_threshold:
                                    logger_backtest.info(
                                        f"[{self.symbol}] Minute scan passed (cheap_weight={cheap_weight:.1f}, max_expensive={max_expensive_weight:.1f}). Switching to 1s analysis for next candle..."
                                    )
                                    candle_open_time = kline_index_list_pd[i]
                                    next_candle_open_time = (
                                        kline_index_list_pd[i + 1]
                                        if i + 1 < len(kline_index_list_pd)
                                        else candle_open_time + timedelta(minutes=1)
                                    )
                                    candle_duration = (
                                        next_candle_open_time - candle_open_time
                                    )
                                    next_candle_close_time = (
                                        next_candle_open_time + candle_duration
                                    )
                                    klines_1s_for_minute = (
                                        await self._load_1s_klines_for_window(
                                            self.symbol,
                                            next_candle_open_time,
                                            next_candle_close_time,
                                        )
                                    )
                                    if (
                                        klines_1s_for_minute is not None
                                        and not klines_1s_for_minute.empty
                                    ):
                                        logger_backtest.info(
                                            f"[{self.symbol}] Entering 1s analysis loop with {len(klines_1s_for_minute)} bars..."
                                        )
                                        intra_candle_pair_info = (
                                            pair_info_enriched.copy()
                                        )
                                        for (
                                            ts_1s,
                                            kline_1s_row,
                                        ) in klines_1s_for_minute.iterrows():
                                            intra_candle_pair_info.update(
                                                kline_1s_row.to_dict()
                                            )
                                            intra_candle_pair_info["last_price"] = (
                                                kline_1s_row["close"]
                                            )
                                            intra_candle_pair_info["timestamp_dt"] = (
                                                ts_1s.to_pydatetime()
                                            )
                                            (
                                                intra_candle_signal,
                                                _,
                                                intra_candle_trace,
                                            ) = await self.strategy_instance.check_signal(
                                                intra_candle_pair_info,
                                                market_data_full.copy(),
                                                prev_pair_info_enriched,
                                                analysis_level="second_bar_trigger",
                                            )
                                            if intra_candle_signal:
                                                logger_backtest.info(
                                                    f"[{self.symbol}] Intra-candle signal triggered on 1s bar at {kline_1s_row['close']:.4f} ({ts_1s})."
                                                )
                                                signal = intra_candle_signal
                                                trace = intra_candle_trace
                                                break
                                    else:
                                        logger_backtest.warning(
                                            f"[{self.symbol}] Minute scan passed, but no 1s klines found for {next_candle_open_time} - {next_candle_close_time}."
                                        )
                                else:
                                    logger_backtest.info(
                                        f"[{self.symbol}] Short-circuit triggered. Cheap weight ({cheap_weight:.1f}) + max expensive ({max_expensive_weight:.1f}) < Threshold ({min_threshold:.1f})"
                                    )
                            else:
                                (
                                    signal,
                                    _,
                                    trace,
                                ) = await self.strategy_instance.check_signal(
                                    pair_info_enriched,
                                    market_data_for_strategy,
                                    prev_pair_info_enriched,
                                )

                        if trace:
                            self._count_foundation_triggers_from_trace(
                                trace,
                                self.structured_report["event_counters"][
                                    "foundation_trigger_counts"
                                ],
                            )

                        if signal:
                            self.structured_report["event_counters"][
                                "signals_generated_total"
                            ] += 1
                            current_strategy_name_for_signal = (
                                signal.strategy_name if signal else self.strategy_name
                            )
                            self._last_signal_timestamp_per_symbol_strategy[
                                (self.symbol, current_strategy_name_for_signal)
                            ] = current_event_ts_float

                            ml_confirmed_this_signal = True

                            if ml_confirmed_this_signal:
                                self.rm.stats.current_balance = self.current_balance

                                if self._current_strategy_uses_dca_or_grid_management():
                                    if not isinstance(signal.details, dict):
                                        signal.details = {}
                                    signal.details["uses_dca_or_grid_management"] = True
                                    signal.details["skip_min_rr_for_dca_grid"] = True

                                (
                                    approved_sig,
                                    quantity_sig,
                                    initial_risk_usd_planned_trade,
                                    rejection_reason,
                                ) = await self.rm.assess_signal(
                                    signal,
                                    lot_params=self.exchange_info.get("lot_params"),
                                    min_notional_usd=self.exchange_info.get(
                                        "min_notional"
                                    ),
                                    mode="paper",
                                )

                                if (
                                    not approved_sig
                                    or not quantity_sig
                                    or quantity_sig <= 0
                                ):
                                    self.structured_report["event_counters"][
                                        "rejections"
                                    ]["by_risk_manager"] += 1
                                    rejection_key = (
                                        rejection_reason
                                        if rejection_reason
                                        else "UNKNOWN"
                                    )
                                    self.structured_report["event_counters"][
                                        "rejections"
                                    ]["by_risk_manager_reasons"].setdefault(
                                        rejection_key, 0
                                    )
                                    self.structured_report["event_counters"][
                                        "rejections"
                                    ]["by_risk_manager_reasons"][rejection_key] += 1
                                    logger.warning(
                                        f"[{self.symbol}] Signal REJECTED by Risk Manager. Reason: {rejection_reason}"
                                    )
                                    continue

                                if approved_sig and quantity_sig and quantity_sig > 0:
                                    client_order_id_for_trade = (
                                        self._generate_client_order_id()
                                    )
                                    signal_details_final = {
                                        **signal.details,
                                        "client_order_id": client_order_id_for_trade,
                                        "initial_risk_usd_planned": initial_risk_usd_planned_trade,
                                    }

                                    # Support for limit orders for visual strategies
                                    if signal.mode != OrderMode.MARKET:
                                        pending_limit_order = {
                                            "price": signal.entry_price,
                                            "side": signal.direction,
                                            "stop_loss": signal.stop_loss,
                                            "take_profit": signal.take_profit,
                                            "quantity": quantity_sig,
                                            "signal_details": signal_details_final,
                                            "strategy": current_strategy_name_for_signal,
                                            "partial_targets": signal.partial_targets,
                                            "entry_atr": pair_info_enriched.get("atr"),
                                            "client_order_id": client_order_id_for_trade,
                                            "initial_risk_usd_planned": initial_risk_usd_planned_trade,
                                            "no_stop_loss": signal.no_stop_loss,
                                        }
                                        logger.info(
                                            f"[{self.symbol}] Limit signal stored: {signal.mode.name} at {signal.entry_price:.4f}"
                                        )
                                        prev_pair_info_enriched = (
                                            pair_info_enriched.copy()
                                        )
                                        continue

                                    sim_result_entry: OrderExecutionResult = simulate_market_order_execution(
                                        order_quantity=quantity_sig,
                                        direction=signal.direction,
                                        market_data_for_sim=market_data_full,
                                        ideal_entry_price=k_close,
                                        commission_pct=self.execution_config[
                                            "commission_pct"
                                        ],
                                        kline_close_for_fallback=k_close,
                                        simple_slippage_pct=self.execution_config.get(
                                            "slippage_pct", 0.0002
                                        ),
                                    )

                                    actual_entry_price = sim_result_entry.avg_fill_price
                                    actual_filled_quantity = (
                                        sim_result_entry.filled_quantity
                                    )

                                    if (
                                        sim_result_entry.slippage_usd
                                        > initial_risk_usd_planned_trade * 0.25
                                    ):
                                        self.structured_report["anomalies"].append(
                                            {
                                                "type": "EXECUTION_WARNING",
                                                "timestamp": timestamp_dt.isoformat(),
                                                "message": f"High slippage detected: {sim_result_entry.slippage_usd:.2f} USD",
                                            }
                                        )

                                    if (
                                        actual_filled_quantity <= 0
                                        or actual_entry_price is None
                                    ):
                                        logger.warning(
                                            f"[{self.symbol}] Signal rejected: Market order simulation failed to fill. Reason: {sim_result_entry.message}"
                                        )
                                        continue

                                    is_slippage_past_sl = (
                                        self._is_price_beyond_stop_loss(
                                            signal.direction,
                                            actual_entry_price,
                                            signal.stop_loss,
                                        )
                                    )

                                    if is_slippage_past_sl:
                                        logger.warning(
                                            f"[{self.symbol}] Signal rejected: Entry price ({actual_entry_price:.4f}) "
                                            f"after slippage is beyond stop-loss "
                                            f"({self._format_optional_price(signal.stop_loss)}). "
                                            f"Fill type: {sim_result_entry.fill_type.value}"
                                        )
                                        self.structured_report["event_counters"][
                                            "rejections"
                                        ]["by_slippage_beyond_sl"] += 1
                                        continue

                                    if self._log_ml_confirmation_data:
                                        self._ml_confirmation_context_buffer[
                                            client_order_id_for_trade
                                        ] = {
                                            "timestamp": timestamp_dt.isoformat(),
                                            "strategy": current_strategy_name_for_signal,
                                            "symbol": signal.symbol,
                                            "direction": signal.direction.name,
                                            "mode": signal.mode.name,
                                            "signal_trigger_price": signal.trigger_price,
                                            "signal_entry_price": signal.entry_price,
                                            "signal_sl": signal.stop_loss,
                                            "signal_tp": signal.take_profit,
                                            **signal_details_final,
                                        }

                                    signal_details_final["commission_entry"] = (
                                        sim_result_entry.actual_commission_paid
                                    )
                                    max_entries = 1

                                    initial_execution = {
                                        "timestamp": timestamp_dt,
                                        "price": sim_result_entry.avg_fill_price,
                                        "quantity": sim_result_entry.filled_quantity,
                                        "type": "ENTRY",
                                    }

                                    backtest_position = BacktestPositionState(
                                        symbol=signal.symbol,
                                        direction=signal.direction,
                                        entry_price=sim_result_entry.avg_fill_price,
                                        initial_quantity=actual_filled_quantity,
                                        remaining_quantity=actual_filled_quantity,
                                        entry_time=timestamp_dt,
                                        strategy=current_strategy_name_for_signal,
                                        initial_stop_loss=signal.stop_loss,
                                        initial_take_profit=signal.take_profit,
                                        current_sl_price=signal.stop_loss,
                                        no_stop_loss=signal.no_stop_loss,
                                        move_sl_to_be_enabled=signal.move_sl_to_be_on_first_tp,
                                        partial_targets=[
                                            (pt.price, pt.fraction, False)
                                            for pt in signal.partial_targets or []
                                        ],
                                        entry_atr=pair_info_enriched.get("atr"),
                                        signal_details=signal_details_final,
                                        client_order_id=client_order_id_for_trade,
                                        initial_risk_usd_planned=initial_risk_usd_planned_trade,
                                        ideal_entry_price_l2=sim_result_entry.ideal_entry_price,
                                        entry_slippage_usd=sim_result_entry.slippage_usd,
                                        entry_commission_paid=sim_result_entry.actual_commission_paid,
                                        entry_fill_type=sim_result_entry.fill_type.value,
                                        entry_sim_message=sim_result_entry.message,
                                        max_entries=max_entries,
                                        number_of_entries=1,
                                        executions=[initial_execution],
                                    )
                                    self.structured_report["event_counters"][
                                        "trades_opened"
                                    ] += 1

                                    logger.info(
                                        f"[PM_DEBUG] Position CREATED: CID={backtest_position.client_order_id}, FillType: {backtest_position.entry_fill_type}, Slippage: ${backtest_position.entry_slippage_usd:.4f}"
                                    )

                                    self.stats["number_of_entries"] += 1
                                    self.current_balance -= (
                                        sim_result_entry.actual_commission_paid
                                    )
                                    self.equity_curve.append(
                                        (timestamp_dt, self.current_balance)
                                    )
                                    self.stats["peak_equity"] = max(
                                        self.stats["peak_equity"], self.current_balance
                                    )
                                    self._bt_last_position_close_time_per_symbol[
                                        self.symbol
                                    ] = 0
                                    self.report_progress_event(
                                        "POSITION_OPEN",
                                        f"Opened {backtest_position.direction.name} on {backtest_position.symbol} via {backtest_position.entry_fill_type}. Price: {backtest_position.entry_price:.4f}",
                                        {
                                            "symbol": backtest_position.symbol,
                                            "direction": backtest_position.direction.name,
                                            "entry_price": backtest_position.entry_price,
                                            "fill_type": backtest_position.entry_fill_type,
                                            "slippage_usd": backtest_position.entry_slippage_usd,
                                        },
                                    )

                        elif trace and trace.get("rejection_reason"):
                            rejection_reason = trace.get("rejection_reason")
                            if rejection_reason == "weight_threshold":
                                self.structured_report["event_counters"]["rejections"][
                                    "by_weight_threshold"
                                ] += 1
                            elif rejection_reason == "filter":
                                failed_filter_id = self._get_failed_filter_from_trace(
                                    trace
                                )
                                if failed_filter_id:
                                    self.structured_report["event_counters"][
                                        "rejections"
                                    ]["by_filter"].setdefault(failed_filter_id, 0)
                                    self.structured_report["event_counters"][
                                        "rejections"
                                    ]["by_filter"][failed_filter_id] += 1

                prev_pair_info_enriched = pair_info_enriched.copy()
            except Exception as e:
                logger.error(
                    f"[{self.symbol}] Unhandled exception in backtest loop at index {i} (Timestamp: {self._timestamp_dt_current_candle}). Skipping candle. Error: {e}",
                    exc_info=True,
                )
                self.structured_report["anomalies"].append(
                    {
                        "type": "LOOP_EXCEPTION",
                        "timestamp": self._timestamp_dt_current_candle.isoformat()
                        if self._timestamp_dt_current_candle
                        else None,
                        "message": f"Unhandled exception in backtest loop: {e}",
                    }
                )
                prev_pair_info_enriched = None
                continue

        if backtest_position and "i" in locals() and i == len(self.klines) - 1:
            pos_end = backtest_position
            last_k_close_idx = min(i, len(self.kline_data_array) - 1)

            if last_k_close_idx >= 0 and "close" in self.kline_index_map:
                k_close_end = self.kline_data_array[last_k_close_idx][
                    self.kline_index_map["close"]
                ]
                last_ts_dt = kline_index_list_pd[last_k_close_idx].to_pydatetime()

                # PROBLEM #1 (for exit at the end of data)
                exit_direction_eod = (
                    SignalDirection.SHORT
                    if pos_end.direction == SignalDirection.LONG
                    else SignalDirection.LONG
                )
                sim_result_eod = simulate_market_order_execution(
                    order_quantity=pos_end.remaining_quantity,
                    direction=exit_direction_eod,
                    market_data_for_sim=None,  # DISABLING L2 FOR CONSISTENCY
                    ideal_entry_price=k_close_end,
                    commission_pct=self.execution_config["commission_pct"],
                    kline_close_for_fallback=k_close_end,
                    simple_slippage_pct=self.execution_config.get("slippage_pct"),
                )

                exit_price_eod = sim_result_eod.avg_fill_price or k_close_end
                qty_closed_final_eod = sim_result_eod.filled_quantity

                pnl_from_partials = sum(fill["pnl"] for fill in pos_end.partial_fills)
                comm_from_partials = sum(
                    fill["commission"] for fill in pos_end.partial_fills
                )

                pnl_final_eod_event = (
                    (exit_price_eod - pos_end.entry_price) * qty_closed_final_eod
                    if pos_end.direction == SignalDirection.LONG
                    else (pos_end.entry_price - exit_price_eod) * qty_closed_final_eod
                )

                total_pnl_gross_eod = pnl_from_partials + pnl_final_eod_event
                total_comm_exit_eod = (
                    comm_from_partials + sim_result_eod.actual_commission_paid
                )
                total_commission_eod = (
                    pos_end.entry_commission_paid + total_comm_exit_eod
                )
                
                funding_rate = float(getattr(config, "BACKTEST_FUNDING_RATE_8H", 0.0001))
                temp_final_executions_eod = [
                    exec_item
                    for exec_item in pos_end.executions
                    if exec_item.get("type") == "ENTRY"
                ]
                temp_final_executions_eod.append(
                    {
                        "timestamp": last_ts_dt,
                        "price": exit_price_eod,
                        "quantity": qty_closed_final_eod,
                        "type": "EXIT",
                    }
                )
                funding_pnl_eod = calculate_position_funding_pnl(
                    executions=temp_final_executions_eod,
                    is_short=(pos_end.direction == SignalDirection.SHORT),
                    funding_rate=funding_rate
                )
                
                net_pnl_for_log_eod = total_pnl_gross_eod - total_commission_eod + funding_pnl_eod
                pnl_for_balance_stats_eod = total_pnl_gross_eod - total_comm_exit_eod + funding_pnl_eod

                self.current_balance += pnl_for_balance_stats_eod
                self.equity_curve.append((last_ts_dt, self.current_balance))
                self.stats["trades"] += 1
                if net_pnl_for_log_eod > 0:
                    self.stats["wins"] += 1
                else:
                    self.stats["losses"] += 1
                self.stats["total_pnl"] += net_pnl_for_log_eod
                self.stats["total_commission"] += total_commission_eod
                self._check_risk_limits_after_trade(net_pnl_for_log_eod, last_ts_dt)

                logger.critical(
                    f"[{timestamp_dt}] CLOSING POSITION AFTER LOOP! Reason: END_OF_DATA"
                )

                pos_end.executions.append(
                    {
                        "timestamp": last_ts_dt,
                        "price": exit_price_eod,
                        "quantity": qty_closed_final_eod,
                        "type": "EXIT",
                        "slippage_usd": sim_result_eod.slippage_usd,
                        "fill_type": sim_result_eod.fill_type.value,
                    }
                )

                if self.include_eod_in_log:
                    trade_log_entry_eod = {
                        "timestamp": last_ts_dt,
                        "entry_time": pos_end.entry_time,
                        "symbol": pos_end.symbol,
                        "strategy": pos_end.strategy,
                        "direction": pos_end.direction.name,
                        "entry_price": float(pos_end.entry_price),
                        "exit_price": float(exit_price_eod),
                        "avg_weighted_exit_price": float(exit_price_eod),
                        "num_partial_tp_hits": getattr(
                            pos_end, "num_partial_tp_hits", 0
                        ),
                        "quantity": float(pos_end.initial_quantity),
                        "pnl": float(net_pnl_for_log_eod),
                        "funding_pnl": float(funding_pnl_eod),
                        "exit_reason": "END_OF_DATA",
                        "commission": float(total_commission_eod),
                        "sl_level": float(pos_end.initial_stop_loss)
                        if pos_end.initial_stop_loss is not None
                        else None,
                        "tp_level": float(pos_end.initial_take_profit or 0),
                        "client_order_id": pos_end.client_order_id,
                        "l2_entry_slippage_usd": pos_end.entry_slippage_usd,
                        "l2_exit_slippage_usd": sim_result_eod.slippage_usd,
                        "entry_fill_type": getattr(pos_end, "entry_fill_type", None),
                        "moved_to_be": getattr(pos_end, "is_stop_at_be", False),
                    }
                    self.trade_log.append(trade_log_entry_eod)

                await self._close_position(
                    position_data={
                        **pos_end.__dict__,
                        "pnl": net_pnl_for_log_eod,
                        "executions": pos_end.executions,
                    },
                    exit_price=exit_price_eod,
                    reason="END_OF_DATA",
                    timestamp=last_ts_dt,
                    total_commission_override=total_commission_eod,
                    l2_ideal_exit_price=sim_result_eod.ideal_entry_price,
                    l2_exit_slippage_usd=sim_result_eod.slippage_usd,
                    l2_filled_qty_at_exit=qty_closed_final_eod,
                )
                if False:
                    self.report_progress_event(
                        "POSITION_CLOSE_END_DATA",
                        f"Position {pos_end.direction.name} for {pos_end.symbol} closed (end of data). PnL: {net_pnl_for_log_eod:.2f}.",
                        {
                            "symbol": pos_end.symbol,
                            "direction": pos_end.direction.name,
                            "pnl": net_pnl_for_log_eod,
                            "reason": "END_OF_DATA",
                        },
                    )
                logger_backtest.info(
                    f"[{last_ts_dt}] END_OF_DATA close hidden from user-facing trade outputs for "
                    f"{pos_end.symbol}. PnL={net_pnl_for_log_eod:.2f}"
                )

        logger_backtest.info(
            f"DepthSight Backtest loop finished. Last index processed: {i if 'i' in locals() else 'N/A'}"
        )
        execution_end_time = time.time()
        logger_backtest.info(
            f"DepthSight Backtest loop finished in {execution_end_time - execution_start_time:.2f} seconds."
        )

        if is_ml_mode and not is_ml_data_collection_mode and self._ml_simulate_trades:
            self._save_simulated_trades_to_csv()
        elif not is_ml_mode and self._backtest_save_trades:
            self._save_backtest_trades_to_csv()
        if self._log_ml_confirmation_data and self._ml_confirmation_context_buffer:
            self._ml_confirmation_context_buffer.clear()

        final_kpis_result = self._calculate_final_kpis_for_mode()
        if is_ml_data_collection_mode:
            if final_kpis_result is None:
                final_kpis_result = {}
            final_kpis_result["training_data"] = collected_training_data_for_main_ml

        if final_kpis_result:
            final_kpis_result["analytics_report"] = self.structured_report

        self.report_progress_event("COMPLETE", "Backtest completed.", final_kpis_result)

        return final_kpis_result

    # Synchronous launch (from DepthSightBacktester)
    def run(self) -> Optional[Dict[str, Any]]:
        """
        Synchronous wrapper for running an asynchronous backtest.
        This method MUST NOT contain `await` or loop logic.
        """
        logger.info("Starting synchronous run of Hybrid DepthSightBacktester...")
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # Run the ASYNCHRONOUS version and return its result
            return loop.run_until_complete(self.run_async())

        except Exception as e:
            logger.error(
                f"Error running Hybrid backtest event loop: {e}", exc_info=True
            )
            return None


# Usage example (from DepthSightBacktester)
if __name__ == "__main__":

    async def run_depthsight_test():
        logger.info("--- Running DepthSight Backtester Standalone Test ---")
        test_symbol = "BTCUSDT"  # Use proper symbol format
        test_kline_data = {
            "open_time": pd.to_datetime(
                pd.date_range(
                    start="2023-10-10 12:00", periods=100, freq="1min", tz="UTC"
                )
            ),
            "open": np.linspace(27000, 27500, 100),
            "high": np.linspace(27050, 27550, 100),
            "low": np.linspace(26950, 27450, 100),
            "close": np.linspace(27020, 27520, 100),
            "volume": np.random.randint(10, 100, 100),
        }
        df_klines = pd.DataFrame(test_kline_data).set_index("open_time")
        # Add required columns for ATR and rolling calculations if not present
        df_klines["candle_range"] = df_klines["high"] - df_klines["low"]
        df_klines["rolling_high_20"] = (
            df_klines["high"].rolling(window=20, min_periods=1).max()
        )
        df_klines["rolling_low_20"] = (
            df_klines["low"].rolling(window=20, min_periods=1).min()
        )
        df_klines["rolling_max_range_20"] = (
            df_klines["candle_range"].rolling(window=20, min_periods=1).max()
        )

        historical_data_mock = {"kline_1m": df_klines}

        # Mock strategy instance for testing (if needed, otherwise get_strategy_instance will fail)
        class MockStrategy(BaseStrategy):
            NAME = "MockStrategy"

            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.candle_timeframe = "1m"
                self.required_data_types = ["kline_1m"]  # Mock requires kline data
                self.foundation_weights = {"market_activity": 100.0}  # Needs weights
                self.min_total_foundation_weight_threshold = (
                    1.0  # Very low threshold for easy signal
                )

            def check_signal_sync(
                self, pair_info: Dict[str, Any], market_data: Dict[str, Any]
            ) -> Optional[StrategySignal]:
                if (
                    pair_info["last_price"] > 27050
                    and len(market_data.get("kline_1m", [])) > 50
                ):
                    # Mock a simple signal
                    return StrategySignal(
                        strategy_name=self.NAME,
                        symbol=pair_info["symbol"],
                        direction=SignalDirection.LONG,
                        trigger_price=pair_info["last_price"],
                        entry_price=pair_info["last_price"],
                        stop_loss=pair_info["last_price"] * 0.99,
                        take_profit=pair_info["last_price"] * 1.015,
                        mode=OrderMode.MARKET,
                        details={"some_mock_detail": True},
                    )
                return None

            def check_fast_foundations(
                self, pair_info: Dict[str, Any], market_data: Dict[str, Any]
            ) -> Dict[str, Any]:
                # Mock fast foundations check
                return {"market_activity": True, "level": False}

        # Mock get_strategy_instance to return our MockStrategy
        original_get_strategy_instance = STRATEGIES.get("MockStrategy")
        STRATEGIES["MockStrategy"] = MockStrategy  # Temporarily register

        try:
            params = {
                "candle_timeframe": "1m",
                "stop_loss_atr_multiplier": 1.5,
                "take_profit_atr_multiplier": 2.0,
                "risk_pct_per_trade": 0.005,  # Example risk
            }
            risk_params_mock = {
                "risk_pct_per_trade": 0.01,
                "daily_max_loss_pct": 0.05,
                "max_consecutive_losses": 5,
                "max_stop_distance_pct": 0.05,
            }
            execution_config_mock = {"commission_pct": 0.001, "slippage_pct": 0.0005}
            exchange_info_mock = {
                "tick_size": 0.01,
                "lot_params": {"minQty": 0.001, "maxQty": 1000, "stepSize": 0.001},
                "min_notional": 10.0,  # Min order value $10
            }

            # --- Test with L2 enabled ---
            logger.info("--- Running DepthSight Test (L2 ENABLED) ---")
            backtester_l2_enabled = DepthSightBacktester(
                strategy_name="MockStrategy",  # Use the mock strategy
                symbol=test_symbol,
                params=params,
                historical_data=historical_data_mock,
                initial_balance=10000.0,
                min_trades_required=1,
                risk_params=risk_params_mock,
                execution_config=execution_config_mock,
                strategy_defaults=config.STRATEGY_DEFAULTS,
                ml_training_config={},
                ml_sim_log_path=None,
                backtest_log_config={
                    "save_trades": True,
                    "log_path_template": "logs/backtest_trades/{strategy}_{symbol}_{timestamp}_l2.csv",
                },
                actual_trading_start_dt=None,
                exchange_info=exchange_info_mock,
                ml_training_mode=False,
                ml_agent_instance=None,
                collect_data_mode=False,
                log_ml_confirmation_data=False,
                ml_confirmation_log_path=None,
                l2_storage_path="./test_l2_data",  # Provide a dummy path for testing
                progress_callback=lambda meta: logger.info(
                    f"Progress L2: {meta['kpis']['progress']:.1f}% PnL: {meta['kpis']['pnl']:.2f}"
                ),
            )
            # Create a dummy L2 directory for the test
            Path("./test_l2_data/binance/BTCUSDT/2023/10/10").mkdir(
                parents=True, exist_ok=True
            )
            # Create a dummy L2 file (can be empty or contain minimal data)
            with open(
                "./test_l2_data/binance/BTCUSDT/2023/10/10/12-00-00.bin.zst", "wb"
            ) as f:
                # write a minimal zstd compressed empty msgpack array
                dctx = zstandard.ZstdCompressor()
                with dctx.stream_writer(f) as writer:
                    writer.write(msgpack.pack([]))

            results_l2 = await backtester_l2_enabled.run_async()
            if results_l2:
                logger.info("--- DepthSight Test Results (L2 ENABLED) ---")
                for key, value in results_l2.items():
                    logger.info(f"{key}: {value}")
            else:
                logger.error(
                    "DepthSight backtest (L2 ENABLED) did not return any results."
                )

            # Test with L2 disabled (by not providing path)
            logger.info("--- Running DepthSight Test (L2 DISABLED) ---")
            backtester_l2_disabled = DepthSightBacktester(
                strategy_name="MockStrategy",
                symbol=test_symbol,
                params=params,
                historical_data=historical_data_mock,
                initial_balance=10000.0,
                min_trades_required=1,
                risk_params=risk_params_mock,
                execution_config=execution_config_mock,
                strategy_defaults=config.STRATEGY_DEFAULTS,
                ml_training_config={},
                ml_sim_log_path=None,
                backtest_log_config={
                    "save_trades": True,
                    "log_path_template": "logs/backtest_trades/{strategy}_{symbol}_{timestamp}_nol2.csv",
                },
                actual_trading_start_dt=None,
                exchange_info=exchange_info_mock,
                ml_training_mode=False,
                ml_agent_instance=None,
                collect_data_mode=False,
                log_ml_confirmation_data=False,
                ml_confirmation_log_path=None,
                l2_storage_path=None,  # Explicitly disable L2
                progress_callback=lambda meta: logger.info(
                    f"Progress NoL2: {meta['kpis']['progress']:.1f}% PnL: {meta['kpis']['pnl']:.2f}"
                ),
            )
            results_nol2 = await backtester_l2_disabled.run_async()
            if results_nol2:
                logger.info("--- DepthSight Test Results (L2 DISABLED) ---")
                for key, value in results_nol2.items():
                    logger.info(f"{key}: {value}")
            else:
                logger.error(
                    "DepthSight backtest (L2 DISABLED) did not return any results."
                )

        except Exception as e:
            logger.error(f"An error occurred during the test run: {e}", exc_info=True)
        finally:
            # Clean up temporary mock strategy
            if (
                "MockStrategy" in STRATEGIES
                and STRATEGIES["MockStrategy"] is MockStrategy
            ):
                if original_get_strategy_instance is None:
                    del STRATEGIES["MockStrategy"]
                else:
                    STRATEGIES["MockStrategy"] = original_get_strategy_instance

            # Clean up dummy L2 data
            import shutil

            if Path("./test_l2_data").exists():
                shutil.rmtree("./test_l2_data")

    asyncio.run(run_depthsight_test())
