# bot_module/trainer.py
import asyncio
import logging
import logging.handlers
import pandas as pd
import json
import os
from datetime import datetime, timedelta, timezone, date
from itertools import product
import time
import math
from pathlib import Path
from collections import defaultdict
from decimal import Decimal
from typing import Dict, Any, Optional, List, Tuple, Set, Callable
import optuna
from optuna.exceptions import TrialPruned
import threading
import sys
import argparse
import multiprocessing  # Added multiprocessing
import operator
import random

try:
    from bot_module import config
    from bot_module.strategy import STRATEGIES, SignalDirection, get_strategy_instance
    from bot_module.ml_strategy import OnlineAgentStrategy
    from bot_module.trade_logger import TradeLogger
    from bot_module.depthsight_backtester import DepthSightBacktester
    from bot_module.data_loader import (
        download_klines,
        download_agg_trades,
        download_open_interest,
        _make_api_request,
    )
    from .utils import (
        add_relative_volume,
        add_volume_percentile_rank,
        calculate_scalper_natr,
    )
except ImportError as e:
    import traceback

    print(
        f"[trainer.py ERROR] Failed to import CRITICAL bot_module components: {e}",
        file=sys.stderr,
    )
    traceback.print_exc()
    STRATEGIES = {}
    SignalDirection = None
    TradeLogger = None
    DepthSightBacktester = None
    OnlineAgentStrategy = None
    download_klines = None
    download_agg_trades = None
    _make_api_request = None
    get_strategy_instance = None
    download_open_interest = None
    add_relative_volume = None
    add_volume_percentile_rank = None
    calculate_scalper_natr = None

    class MockConfig:
        LOG_FILE_TRADES = "logs/trades_and_events.csv"
        OPTIMIZED_PARAMS_FILE = "data/optimized_params.json"
        TRAINER_DATA_LOOKBACK_DAYS = 90
        TRAINER_MIN_TRADES_OPTIMIZE = 20
        TRAINER_OPTIMIZATION_METHOD = "bayesian"
        TRAINER_OPTUNA_CONFIG = {}
        TRAINER_OPTUNA_SEARCH_SPACE = {}
        STRATEGY_DEFAULTS = {}
        TRAINER_TARGET_SYMBOLS = []
        TRAINER_PARAM_GRID = {}
        OPTIMIZATION_DATA_OVERLAP_DAYS = 0
        BACKTEST_INITIAL_BALANCE = 10000.0
        BACKTEST_COMMISSION_PCT = 0.00075
        BACKTEST_SLIPPAGE_PCT = 0.0002
        DEFAULT_RISK_PER_TRADE_PERCENT = 0.5
        DEFAULT_DAILY_MAX_LOSS_PERCENT = 5.0
        DEFAULT_MAX_CONSECUTIVE_LOSSES = 10
        BACKTEST_SAVE_TRADES = False
        BACKTEST_TRADES_LOG_PATH_TEMPLATE = None
        ML_OFFLINE_TRAINED_MODEL_PATH = "data/offline_trained_model.pkl"
        ML_TRAINING_REPORT_FILE = "logs/ml_training_report.json"
        ML_TRAINING_CHUNK_WEEKS = 2
        ML_TRAINING_OVERLAP_DAYS = 7
        ML_TRAINING_LABEL_LOOKAHEAD_BARS = 15
        ML_TRAINING_SIMULATE_TRADES = True
        ML_SIMULATED_TRADES_LOG_FILE = None
        USE_LOCAL_HISTORICAL_DATA = False
        LOCAL_HISTORICAL_DATA_PATH = "data/historical_csv"
        BACKTEST_LOG_FOR_ML_CONFIRMATION_MODEL = False
        BACKTEST_ML_CONFIRMATION_DATA_PATH = None
        ML_CONFIRMATION_Y_TRUE_MIN_MOVE_FAVOR_PCT = 0.15
        ML_CONFIRMATION_Y_TRUE_MAX_DRAWDOWN_PCT = 0.10
        ML_CONFIRMATION_ENABLED = False
        ML_CONFIRMATION_MODEL_PATH = None

    config = MockConfig()

# Separate import for BayesianOptimizer - optional, does not block critical functions
try:
    from bot_module.optimizer import BayesianOptimizer
except ImportError as e_opt:
    print(
        f"[trainer.py WARN] BayesianOptimizer not available (optimization features disabled): {e_opt}",
        file=sys.stderr,
    )
    BayesianOptimizer = None

logger = logging.getLogger("bot_module.trainer")
if not logging.getLogger("bot_module").hasHandlers():
    logging.basicConfig(level=logging.INFO, format=getattr(config, "LOG_FORMAT", None))
    logger.warning("Root logger 'bot_module' has no handlers. Basic config applied.")

# ADD CONSTANT FROM CONFIG
optuna_base_config_tr = getattr(config, "TRAINER_OPTUNA_CONFIG", {})
DEFAULT_DIRECTION_TR = optuna_base_config_tr.get(
    "direction", "maximize"
)  # Using the _TR suffix for trainer
DEFAULT_METRIC_TR = optuna_base_config_tr.get("metric_name", "profit_factor")


def _scan_strategy_params(
    strategy_json: Dict[str, Any], search_width_pct: float = 50.0
) -> Dict[str, Tuple[str, List[Any]]]:
    """
    Recursively scans the visual strategy JSON tree for numeric parameters.
    Returns a search space dictionary compatible with Optuna:
    { "path.to.param": ("int"/"float", [low, high]) }
    """
    search_space = {}

    def scan_params_recursive(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                current_path = path + [k]
                if k == "params" and isinstance(v, dict):
                    for pk, pv in v.items():
                        if isinstance(pv, (int, float)) and not isinstance(pv, bool):
                            param_path = ".".join(map(str, current_path + [pk]))
                            width = abs(pv) * (search_width_pct / 100.0)
                            if width == 0:
                                low, high = -5.0, 5.0
                            else:
                                low, high = pv - width, pv + width

                            if isinstance(pv, int) and pk not in (
                                "sl_value",
                                "tp_value",
                                "stop_loss",
                                "take_profit",
                            ):
                                low_i = int(round(low))
                                high_i = int(round(high))
                                if low_i >= high_i:
                                    low_i = max(1, pv - 1)
                                    high_i = pv + 1
                                search_space[param_path] = ("int", [low_i, high_i])
                            else:
                                search_space[param_path] = (
                                    "float",
                                    [float(low), float(high)],
                                )
                else:
                    scan_params_recursive(v, current_path)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                scan_params_recursive(item, path + [i])

    scan_params_recursive(strategy_json, [])
    return search_space


def _inject_params_to_strategy(
    strategy_template: Dict[str, Any], suggested_params: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Takes a visual strategy template JSON tree and injects suggested flat param values
    back into their respective dotted paths.
    """
    import copy

    strat = copy.deepcopy(strategy_template)
    for path_str, val in suggested_params.items():
        parts = []
        for p in path_str.split("."):
            if p.isdigit():
                parts.append(int(p))
            else:
                parts.append(p)
        try:
            curr = strat
            for part in parts[:-1]:
                if isinstance(curr, dict):
                    curr = curr[part]
                elif isinstance(curr, list):
                    curr = curr[int(part)]

            last_part = parts[-1]
            if isinstance(curr, dict):
                orig_val = curr[last_part]
                if isinstance(orig_val, int) and not isinstance(orig_val, bool):
                    curr[last_part] = int(round(val))
                else:
                    curr[last_part] = float(val)
        except Exception as e:
            logger.error(
                f"Failed to inject parameter at path {path_str} with value {val}: {e}"
            )
    return strat


def _is_heavy_strategy(strategy_config: Dict[str, Any]) -> bool:
    """
    Recursively checks the block types in the strategy configuration.
    If the strategy contains L2 microstructure or DCA blocks, returns True.
    """

    def check_node(node):
        if isinstance(node, list):
            return any(check_node(item) for item in node)
        if not isinstance(node, dict):
            return False

        block_type = str(node.get("type", "") or "").strip().lower()
        heavy_types = {
            "l2_microstructure",
            "l2_microstructure_check",
            "order_book_zone",
            "orderbook_imbalance",
            "tape_acceleration",
            "tape_analysis",
            "tape_condition",
            "dca_grid",
            "dca_management",
            "dca_orders",
            "bookdepth",
            "aggtrade",
        }
        if block_type in heavy_types:
            return True

        for k, v in node.items():
            if k in (
                "children",
                "entryConditions",
                "filters",
                "initialization",
                "positionManagement",
                "conditions",
            ):
                if check_node(v):
                    return True
        return False

    return check_node(strategy_config)


def _setup_process_logging(pid: int, symbol: str):
    """Configures logging for the child process."""
    try:
        # Get the module's root logger (or a specific logger can be configured)
        process_logger = logging.getLogger(
            "bot_module"
        )  # Configuring the module's root logger
        process_logger.setLevel(logging.DEBUG)  # Set DEBUG for the process

        # Remove existing handlers if they were inherited
        # This prevents duplication if the pool somehow passes handlers
        for handler in process_logger.handlers[:]:
            process_logger.removeHandler(handler)
            if hasattr(handler, "close"):
                try:
                    handler.close()
                except Exception:
                    pass  # Ignoring closure errors

        # Add a handler for console output (from the process)
        # The format can be made simpler for process debugging
        log_format = f"%(asctime)s - %(levelname)s - [Process:{pid}:{symbol}:%(name)s:%(lineno)d] - %(message)s"
        formatter = logging.Formatter(log_format)
        stream_handler = logging.StreamHandler(sys.stdout)  # Or sys.stderr
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(
            logging.DEBUG
        )  # Output all DEBUG messages from the process
        process_logger.addHandler(stream_handler)

        # Optional: Logging to a separate file for the process
        log_file_path = Path(f"logs/trainer_process_{pid}_{symbol}.log")
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file_path, mode="a", encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        process_logger.addHandler(file_handler)

        # Reducing noise from libraries inside the process
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("numba").setLevel(logging.WARNING)
        logging.getLogger("optuna").setLevel(logging.WARNING)

        process_logger.debug("Logging configured for process.")

    except Exception as e:
        # Use print, as the logger might not have been configured
        print(
            f"[Process:{pid}:{symbol} ERROR] Failed to configure logging: {e}",
            file=sys.stderr,
        )


# Data loader function for processes
def _load_data_for_process(
    symbol: str,
    backtest_start_dt: datetime,  # Actual start of the backtest period
    backtest_end_dt: datetime,  # End of backtest period
    overlap_days: int,  # Number of buffer days for Klines
    required_data_types: Set[str],
    use_local_data: bool,
    local_data_path: Path,
) -> Dict[str, Optional[pd.DataFrame]]:
    """Loads data: Klines with overlap, AggTrades without overlap."""
    # Dates for LOADING Klines (with overlap)
    kline_load_start_dt = backtest_start_dt - timedelta(days=overlap_days)
    kline_load_end_dt = backtest_end_dt
    kline_load_start_dt_utc = (
        kline_load_start_dt.astimezone(timezone.utc)
        if kline_load_start_dt.tzinfo
        else kline_load_start_dt.replace(tzinfo=timezone.utc)
    )
    kline_load_end_dt_utc = (
        kline_load_end_dt.astimezone(timezone.utc)
        if kline_load_end_dt.tzinfo
        else kline_load_end_dt.replace(tzinfo=timezone.utc)
    )

    # Dates for LOADING AggTrades (WITHOUT overlap)
    non_overlap_load_start_dt = backtest_start_dt
    non_overlap_load_end_dt = backtest_end_dt
    non_overlap_load_start_dt_utc = (
        non_overlap_load_start_dt.astimezone(timezone.utc)
        if non_overlap_load_start_dt.tzinfo
        else non_overlap_load_start_dt.replace(tzinfo=timezone.utc)
    )
    non_overlap_load_end_dt_utc = (
        non_overlap_load_end_dt.astimezone(timezone.utc)
        if non_overlap_load_end_dt.tzinfo
        else non_overlap_load_end_dt.replace(tzinfo=timezone.utc)
    )

    actual_backtest_start_dt_utc = (
        backtest_start_dt.astimezone(timezone.utc)
        if backtest_start_dt.tzinfo
        else backtest_start_dt.replace(tzinfo=timezone.utc)
    )
    actual_backtest_end_dt_utc = (
        backtest_end_dt.astimezone(timezone.utc)
        if backtest_end_dt.tzinfo
        else backtest_end_dt.replace(tzinfo=timezone.utc)
    )

    historical_data: Dict[str, Optional[pd.DataFrame]] = {}
    pid = os.getpid()
    log_prefix = f"[LoadDataProcess:{pid}:{symbol}]"
    source = "LOCAL Parquet" if use_local_data else "API"
    logger.debug(
        f"{log_prefix} Required types: {required_data_types}, Source: {source}"
    )
    logger.debug(
        f"{log_prefix} Kline load period (incl. overlap {overlap_days}d): [{kline_load_start_dt_utc.date()} to {kline_load_end_dt_utc.date()}) for backtest period [{actual_backtest_start_dt_utc.date()} to {actual_backtest_end_dt_utc.date()})"
    )
    if "aggTrade" in required_data_types or "bookDepth" in required_data_types:
        logger.debug(
            f"{log_prefix} Non-kline data load period (no overlap): [{non_overlap_load_start_dt_utc.date()} to {non_overlap_load_end_dt_utc.date()})"
        )

    for data_key in required_data_types:
        df_loaded = None

        # Defining dates for loading
        current_load_start_utc = kline_load_start_dt_utc
        current_load_end_utc = kline_load_end_dt_utc

        if data_key in ["aggTrades", "bookDepth", "open_interest"]:
            current_load_start_utc = non_overlap_load_start_dt_utc
            current_load_end_utc = non_overlap_load_end_dt_utc

        if use_local_data:
            df_loaded = _load_local_data_for_process(
                symbol,
                data_key,
                current_load_start_utc,
                current_load_end_utc,
                local_data_path,
            )
        else:
            # Loading via API
            if data_key.startswith("kline_"):
                tf = data_key.split("_")[1]
                if download_klines is None:
                    logger.error(f"{log_prefix} download_klines unavailable.")
                    continue
                try:
                    df_loaded = download_klines(
                        symbol, tf, current_load_start_utc, current_load_end_utc
                    )
                except Exception as e:
                    logger.error(
                        f"{log_prefix} API download failed for {data_key}: {e}"
                    )
            elif data_key == "aggTrade":
                if download_agg_trades is None:
                    logger.error(f"{log_prefix} download_agg_trades unavailable.")
                    continue
                try:
                    df_loaded = download_agg_trades(
                        symbol, current_load_start_utc, current_load_end_utc
                    )
                except Exception as e:
                    logger.error(
                        f"{log_prefix} API download failed for {data_key}: {e}"
                    )
            elif data_key == "open_interest":
                try:
                    from bot_module.data_loader import download_open_interest

                    df_loaded = download_open_interest(
                        symbol, current_load_start_utc, current_load_end_utc
                    )
                except ImportError:
                    logger.error(
                        f"{log_prefix} Function 'download_open_interest' not found in data_loader."
                    )
                except Exception as e:
                    logger.error(
                        f"{log_prefix} API download failed for {data_key}: {e}"
                    )
            elif data_key == "bookDepth":
                logger.error(
                    f"{log_prefix} API download for 'bookDepth' is not implemented. It must be provided as local data."
                )
                df_loaded = None
            else:
                logger.warning(
                    f"{log_prefix} Unknown data key for API download: {data_key}"
                )

        historical_data[data_key] = (
            df_loaded if df_loaded is not None else pd.DataFrame()
        )

    if not any(
        df is not None and not df.empty
        for k, df in historical_data.items()
        if k.startswith("kline_")
    ):
        logger.error(
            f"{log_prefix} Failed to load any required kline data from {source} for loading period."
        )
        return {}

    # Filter Klines so they start EXACTLY from backtest_start_dt (after overlap)
    # The rest of the data is already loaded from backtest_start_dt
    final_filtered_data = {}
    for key, df in historical_data.items():
        if df is not None and not df.empty:
            if key.startswith("kline_"):
                df_filtered = df[df.index >= actual_backtest_start_dt_utc].copy()
                if not df_filtered.empty:
                    final_filtered_data[key] = df_filtered
                else:
                    final_filtered_data[key] = pd.DataFrame()
            else:
                final_filtered_data[key] = df.copy()
        else:
            final_filtered_data[key] = pd.DataFrame()
    return final_filtered_data


def _optuna_objective_global(trial: optuna.Trial, **kwargs) -> float:
    """Global objective function for Optuna (called from processes)."""
    try:
        params_from_optuna = kwargs["params"]
        strategy_name = kwargs["strategy_name"]
        historical_data = kwargs["historical_data"]
        initial_balance = kwargs["initial_balance"]
        base_config = kwargs["base_config"]
        symbol = kwargs["symbol"]
        exchange_info_all_symbols = kwargs["exchange_info_all_symbols"]
        min_trades_required = kwargs["min_trades_required"]
        backtester_execution_config = kwargs["backtester_execution_config"]
        strategy_defaults_all = kwargs["strategy_defaults_all"]
        optuna_study_config = kwargs["optuna_study_config"]
        actual_start_dt_for_backtest = kwargs["actual_start_dt_for_backtest"]
        log_ml_confirmation_data_flag = kwargs.get(
            "log_ml_confirmation_data_flag", False
        )
        ml_confirmation_data_log_path = kwargs.get(
            "ml_confirmation_data_log_path", None
        )
        y_true_min_move_pct_val = kwargs.get("y_true_min_move_pct_val", 0.15)
        y_true_max_drawdown_pct_val = kwargs.get("y_true_max_drawdown_pct_val", 0.10)
        enable_ml_confirmation_during_backtest = kwargs.get(
            "enable_ml_confirmation_during_backtest", False
        )
        ml_confirmation_model_path_override_val = kwargs.get(
            "ml_confirmation_model_path_override_val", None
        )

    except KeyError as e:
        pid_err = os.getpid()
        symbol_err = kwargs.get("symbol", "UNKNOWN_SYM_IN_KWARGS")
        strat_err = kwargs.get("strategy_name", "UNKNOWN_STRAT_IN_KWARGS")
        trial_num_err = trial.number if trial else -1
        logger_err_prefix = f"[OptunaObjectiveGlobal:{pid_err}:{strat_err}:{symbol_err}:Trial {trial_num_err}]"
        logger.critical(
            f"{logger_err_prefix} CRITICAL ERROR: Missing key '{e}' in kwargs for Optuna objective. Cannot proceed."
        )
        direction_err = kwargs.get("optuna_study_config", {}).get(
            "direction", DEFAULT_DIRECTION_TR
        )
        return -float("inf") if direction_err == "maximize" else float("inf")

    pid = os.getpid()
    log_prefix = (
        f"[OptunaObjectiveGlobal:{pid}:{strategy_name}:{symbol}:Trial {trial.number}]"
    )

    visual_strategy_template = optuna_study_config.get("visual_strategy")
    if visual_strategy_template:
        full_params_for_strategy = _inject_params_to_strategy(
            visual_strategy_template, params_from_optuna
        )
    else:
        full_params_for_strategy = base_config.copy()
        full_params_for_strategy.update(params_from_optuna)

    cfg_default_risk_pct = (
        getattr(config, "DEFAULT_RISK_PER_TRADE_PERCENT", 0.5) / 100.0
    )
    cfg_daily_loss_pct = getattr(config, "DEFAULT_DAILY_MAX_LOSS_PERCENT", 5.0) / 100.0
    cfg_max_consecutive_losses = getattr(config, "DEFAULT_MAX_CONSECUTIVE_LOSSES", 10)
    risk_per_trade_from_params = full_params_for_strategy.get(
        "risk_pct_per_trade", cfg_default_risk_pct
    )
    risk_params_for_backtester = {
        "risk_pct_per_trade": risk_per_trade_from_params,
        "daily_max_loss_pct": cfg_daily_loss_pct,
        "max_consecutive_losses": cfg_max_consecutive_losses,
    }

    cfg_backtest_save_trades = getattr(config, "BACKTEST_SAVE_TRADES", False)
    cfg_backtest_log_template = getattr(
        config, "BACKTEST_TRADES_LOG_PATH_TEMPLATE", None
    )
    backtest_log_cfg_for_run = {
        "save_trades": cfg_backtest_save_trades,
        "log_path_template": cfg_backtest_log_template,
    }

    candle_tf_final = full_params_for_strategy.get(
        "candle_timeframe",
        full_params_for_strategy.get(
            "entry_timeframe",
            base_config.get(
                "candle_timeframe", base_config.get("entry_timeframe", "1m")
            ),
        ),
    )
    kline_key_for_run = f"kline_{candle_tf_final}"
    if (
        kline_key_for_run not in historical_data
        or historical_data[kline_key_for_run] is None
        or historical_data[kline_key_for_run].empty
    ):
        logger.warning(
            f"{log_prefix} Missing or empty kline data for main timeframe '{candle_tf_final}'. Pruning trial."
        )
        raise TrialPruned(f"Missing data for main kline timeframe {candle_tf_final}")

    final_kpis = None
    try:
        historical_data_copy = {
            k: v.copy() if v is not None else None for k, v in historical_data.items()
        }
        symbol_specific_exchange_info = exchange_info_all_symbols.get(symbol, {})

        # Check visual compatibility and select backtester
        strategy_config = full_params_for_strategy
        if Trainer._is_config_based_strategy_params(full_params_for_strategy):
            strategy_config = Trainer._normalize_strategy_config_for_requirements(
                full_params_for_strategy
            )

        use_fast_backtester = Trainer._is_config_based_strategy_params(
            full_params_for_strategy
        ) and not _is_heavy_strategy(strategy_config)

        if use_fast_backtester:
            from bot_module.fast_vector_backtester import FastVectorBacktester

            logger.info(
                f"{log_prefix} Standard visual blocks. Routing trial to FastVectorBacktester (Turbo)"
            )
            backtester = FastVectorBacktester(
                strategy_name=strategy_name,
                symbol=symbol,
                params=full_params_for_strategy,
                historical_data=historical_data_copy,
                initial_balance=initial_balance,
                min_trades_required=min_trades_required,
                actual_trading_start_dt=actual_start_dt_for_backtest,
                risk_params=risk_params_for_backtester,
                execution_config=backtester_execution_config,
                exchange_info=symbol_specific_exchange_info,
                strategy_defaults=strategy_defaults_all,
            )
        else:
            logger.info(
                f"{log_prefix} Routing trial to DepthSightBacktester (Precision)"
            )
            backtester = DepthSightBacktester(
                strategy_name=strategy_name,
                symbol=symbol,
                params=full_params_for_strategy,
                historical_data=historical_data_copy,
                initial_balance=initial_balance,
                min_trades_required=min_trades_required,
                actual_trading_start_dt=actual_start_dt_for_backtest,
                risk_params=risk_params_for_backtester,
                execution_config=backtester_execution_config,
                exchange_info=symbol_specific_exchange_info,
                strategy_defaults=strategy_defaults_all,
                ml_training_mode=False,
                ml_agent_instance=None,
                ml_training_config={},
                ml_sim_log_path=None,
                backtest_log_config=backtest_log_cfg_for_run,
                log_ml_confirmation_data=log_ml_confirmation_data_flag,
                ml_confirmation_log_path=ml_confirmation_data_log_path,
                y_true_min_move_pct=y_true_min_move_pct_val,
                y_true_max_drawdown_pct=y_true_max_drawdown_pct_val,
                enable_ml_confirmation_backtest=enable_ml_confirmation_during_backtest,
                ml_confirmation_model_path_override=ml_confirmation_model_path_override_val,
            )
        final_kpis = backtester.run()
        if final_kpis is None:
            logger.warning(f"{log_prefix} Backtest run returned None. Pruning trial.")
            raise TrialPruned("Backtest run returned None or failed internally")
    except TrialPruned as e_pruned_inner:
        logger.info(
            f"{log_prefix} Trial pruned from within DepthSightBacktester: {e_pruned_inner}"
        )
        raise
    except Exception as e_backtest_run:
        logger.error(
            f"{log_prefix} Unhandled error during DepthSightBacktester.run(): {e_backtest_run}",
            exc_info=True,
        )
        direction_run_err = optuna_study_config.get("direction", DEFAULT_DIRECTION_TR)
        return -float("inf") if direction_run_err == "maximize" else float("inf")

    num_trades = final_kpis.get("trades", 0)
    if num_trades < min_trades_required:
        logger.info(
            f"{log_prefix} Pruning trial: Insufficient trades ({num_trades} < {min_trades_required})."
        )
        raise TrialPruned(
            f"Insufficient trades: {num_trades} (required: {min_trades_required})"
        )

    metric_name_to_optimize = optuna_study_config.get("metric_name", DEFAULT_METRIC_TR)
    metric_value_from_kpis = final_kpis.get(metric_name_to_optimize)

    if metric_value_from_kpis is None:
        logger.error(
            f"{log_prefix} Metric '{metric_name_to_optimize}' not found in KPIs: {list(final_kpis.keys())}. Pruning trial."
        )
        raise TrialPruned(
            f"Metric '{metric_name_to_optimize}' not found in backtest KPIs."
        )

    if isinstance(metric_value_from_kpis, float):
        if abs(metric_value_from_kpis) == float("inf"):
            large_finite_val = 1e12
            metric_value_from_kpis = (
                large_finite_val if metric_value_from_kpis > 0 else -large_finite_val
            )
            logger.warning(
                f"{log_prefix} Infinite metric value for '{metric_name_to_optimize}' replaced with {metric_value_from_kpis}"
            )
        elif math.isnan(metric_value_from_kpis):
            logger.error(
                f"{log_prefix} Metric '{metric_name_to_optimize}' is NaN. Pruning trial."
            )
            raise TrialPruned(f"Metric '{metric_name_to_optimize}' is NaN.")
    elif not isinstance(metric_value_from_kpis, (int, float)):
        logger.error(
            f"{log_prefix} Metric '{metric_name_to_optimize}' is not a valid number: {metric_value_from_kpis} (type: {type(metric_value_from_kpis)}). Pruning trial."
        )
        raise TrialPruned(f"Metric '{metric_name_to_optimize}' is not numeric.")

    pnl_for_log = final_kpis.get("total_pnl", 0.0)
    logger.info(
        f"{log_prefix} Trial OK. Metric ({metric_name_to_optimize}): {metric_value_from_kpis:.4f}, Trades: {num_trades}, PnL: {pnl_for_log:.2f}"
    )

    trial.set_user_attr("total_pnl", final_kpis.get("total_pnl"))
    trial.set_user_attr("trades", num_trades)
    trial.set_user_attr("win_rate", final_kpis.get("win_rate"))
    trial.set_user_attr("max_drawdown", final_kpis.get("max_drawdown"))
    trial.set_user_attr("sharpe_ratio", final_kpis.get("sharpe_ratio"))
    trial.set_user_attr("profit_factor", final_kpis.get("profit_factor"))

    return float(metric_value_from_kpis)


# Updated wrapper function for ML backtest
def _run_ml_backtest_for_symbol_process(
    args_tuple: Tuple[str, Dict[str, Any]],  # Accept ONE argument - a tuple
) -> Tuple[str, List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Runs in a separate process for ML backtest/data collection."""
    # ARGUMENT UNPACKING
    try:
        symbol_to_train, fixed_args = args_tuple
        strategy_name = fixed_args["strategy_name"]
        start_dt = fixed_args["start_dt"]
        end_dt = fixed_args["end_dt"]
        exchange_info_all = fixed_args["exchange_info_all"]
        initial_balance = fixed_args["initial_balance"]
        backtest_exec_config = fixed_args["backtest_exec_config"]  # Expecting this key
        strategy_defaults_all = fixed_args["strategy_defaults_all"]
        ml_training_cfg = fixed_args["ml_training_cfg"]
        ml_sim_log_path = fixed_args["ml_sim_log_path"]
        # Risk parameters are passed as a single dictionary
        risk_params = fixed_args["risk_params"]
        agent_req_types = fixed_args["agent_req_types"]  # Added
        use_local_data = fixed_args["use_local_data"]  # Added
        local_data_path = fixed_args["local_data_path"]  # Added
        # overlap_days for ML backtest, if needed at this level (usually 0 or small)
        ml_overlap_days = fixed_args.get("ml_data_load_overlap_days", 0)

    except (TypeError, KeyError, IndexError) as e:
        pid = os.getpid()
        logger.error(
            f"[Process:{pid}] Error unpacking arguments for ML backtest: {e}. Args received: {args_tuple}"
        )
        fallback_symbol = (
            args_tuple[0]
            if isinstance(args_tuple, tuple) and len(args_tuple) > 0
            else "UNKNOWN_SYMBOL"
        )
        return fallback_symbol, [], None

    pid = os.getpid()
    _setup_process_logging(pid, symbol_to_train)
    logger.info(f"[Process:{pid}] Running ML Backtest for: {symbol_to_train}")
    collected_data: List[Dict[str, Any]] = []
    simulated_kpis: Optional[Dict[str, Any]] = None

    # 1. Define required data (agent_req_types already passed)
    logger.info(
        f"[Process:{pid}:{symbol_to_train}] Loading data (Types: {agent_req_types}, Overlap: {ml_overlap_days} days)..."
    )
    try:
        symbol_historical_data = _load_data_for_process(
            symbol_to_train,
            start_dt,
            end_dt,
            ml_overlap_days,  # Passing overlap_days
            agent_req_types,
            use_local_data,
            local_data_path,
        )
        if not symbol_historical_data or not any(
            df is not None and not df.empty
            for k, df in symbol_historical_data.items()
            if k.startswith("kline_")
        ):
            logger.error(
                f"[Process:{pid}:{symbol_to_train}] Failed to load sufficient historical data for ML backtest. Skipping."
            )
            return symbol_to_train, [], None
    except Exception as e_load:
        logger.error(
            f"[Process:{pid}:{symbol_to_train}] Exception during data loading for ML backtest: {e_load}. Skipping."
        )
        return symbol_to_train, [], None

    # 3. RUN BACKTESTER (as before, but passing risk_params)
    logger.info(
        f"[Process:{pid}:{symbol_to_train}] Starting DepthSightBacktester for ML..."
    )
    symbol_exchange_info = exchange_info_all.get(symbol_to_train, {})
    # Create a local agent instance for this process
    if get_strategy_instance is None:
        logger.error(
            f"[Process:{pid}:{symbol_to_train}] get_strategy_instance is None (import failed?). Skipping."
        )
        return symbol_to_train, [], None
    local_ml_agent = get_strategy_instance(strategy_name)
    if not local_ml_agent:
        logger.error(
            f"[Process:{pid}:{symbol_to_train}] Could not create ML agent instance. Skipping."
        )
        return symbol_to_train, [], None

    # Inheriting parameters from strategy_defaults_all
    agent_defaults = strategy_defaults_all.get(strategy_name, {})
    for key, value in agent_defaults.items():
        if hasattr(local_ml_agent, key):
            setattr(local_ml_agent, key, value)
    local_ml_agent.reset_pipeline()  # Reset model state for each process/symbol

    try:
        backtester = DepthSightBacktester(
            strategy_name=strategy_name,
            symbol=symbol_to_train,
            params={},  # Parameters for the ML agent are hardcoded into it
            historical_data=symbol_historical_data,
            initial_balance=initial_balance,
            min_trades_required=0,  # For ML data collection, the min. number of trades is not important
            risk_params=risk_params,  # Passing risk_params dictionary
            execution_config=backtest_exec_config,
            exchange_info=symbol_exchange_info,
            ml_training_mode=True,
            ml_agent_instance=local_ml_agent,  # Passing local instance
            strategy_defaults=strategy_defaults_all,
            ml_training_config=ml_training_cfg,
            ml_sim_log_path=ml_sim_log_path,
            collect_data_mode=True,  # Indicating that this is data collection mode
        )
        backtest_results = backtester.run()
        if backtest_results:
            collected_data = backtest_results.get("training_data", [])
            # Simulation KPIs, if any
            if (
                ml_training_cfg.get("ML_TRAINING_SIMULATE_TRADES", False)
                and backtester._ml_simulated_trade_log
            ):
                # Using Trainer._calculate_kpis_from_sim_log to calculate KPIs
                # This method should be static or belong to a Trainer instance,
                # but here we call it as static for simplicity if it doesn't use self.
                # Ideally, it should be moved or made static.
                # For now, create a temporary Trainer instance for the call.
                temp_trainer_for_kpi_calc = Trainer()  # Temporary instance
                simulated_kpis = temp_trainer_for_kpi_calc._calculate_kpis_from_sim_log(
                    backtester._ml_simulated_trade_log
                )

            logger.info(
                f"[Process:{pid}:{symbol_to_train}] ML Backtest finished. Collected {len(collected_data)} examples."
            )
        else:
            logger.error(f"[Process:{pid}:{symbol_to_train}] ML Backtest run failed.")
    except Exception as e_backtest:
        logger.error(
            f"[Process:{pid}:{symbol_to_train}] Error during ML Backtest: {e_backtest}",
            exc_info=True,
        )

    return symbol_to_train, collected_data, simulated_kpis


# Updated wrapper function for OPTIMIZATION (unpacking + loader call)
def _run_optimization_for_symbol_process(
    args_tuple: Tuple[str, Dict[str, Any]],
) -> Tuple[str, Dict[str, Tuple[Optional[Dict[str, Any]], Optional[float]]]]:
    """Runs in a separate process for optimization."""
    try:
        symbol_to_optimize, fixed_args = args_tuple
        strategies_to_optimize = fixed_args["strategies_to_optimize"]
        optuna_search_space_all = fixed_args["optuna_search_space_all"]
        strategy_defaults_all = fixed_args["strategy_defaults_all"]
        start_dt = fixed_args["start_dt"]
        end_dt = fixed_args["end_dt"]
        exchange_info_all = fixed_args["exchange_info_all"]
        optuna_config = fixed_args["optuna_config"]
        initial_balance = fixed_args["initial_balance"]
        backtester_execution_config = fixed_args["backtester_execution_config"]
        min_trades_opt = fixed_args[
            "min_trades_required"
        ]  # Key was min_trades_required
        overlap_days = fixed_args["overlap_days"]
        use_local_data = fixed_args["use_local_data"]
        local_data_path = fixed_args["local_data_path"]
        log_ml_confirm_data_cfg = fixed_args[
            "log_ml_confirmation_data_flag"
        ]  # Key was log_ml_confirmation_data_flag
        ml_confirm_path_cfg = fixed_args[
            "ml_confirmation_data_log_path"
        ]  # Key was ml_confirmation_data_log_path
        y_true_min_move_pct_cfg = fixed_args[
            "y_true_min_move_pct_val"
        ]  # Key was y_true_min_move_pct_val
        y_true_max_drawdown_pct_cfg = fixed_args[
            "y_true_max_drawdown_pct_val"
        ]  # Key was y_true_max_drawdown_pct_val
        enable_ml_confirmation_during_backtest_cfg = fixed_args[
            "enable_ml_confirmation_during_backtest"
        ]
        ml_confirmation_model_path_override_val_cfg = fixed_args[
            "ml_confirmation_model_path_override_val"
        ]

    except (TypeError, KeyError, IndexError) as e:
        pid = os.getpid()
        fallback_symbol = (
            args_tuple[0]
            if isinstance(args_tuple, tuple) and len(args_tuple) > 0
            else "UNKNOWN_SYMBOL"
        )
        print(
            f"[Process:{pid}:{fallback_symbol}] Error unpacking optimization args: {e}",
            file=sys.stderr,
        )
        return fallback_symbol, {}

    pid = os.getpid()
    _setup_process_logging(pid, symbol_to_optimize)
    log_prefix = f"[Process:{pid}:{symbol_to_optimize}:Optimize]"
    logger.info(
        f"{log_prefix} Starting optimization (Overlap: {overlap_days} days, Use Local: {use_local_data})..."
    )
    symbol_results: Dict[str, Tuple[Optional[Dict[str, Any]], Optional[float]]] = {}

    # 1. DEFINING REQUIRED DATA (as it was)
    all_required_data_types: Set[str] = set()
    for strategy_name in strategies_to_optimize:
        s_defaults = strategy_defaults_all.get(strategy_name, {})
        tf = s_defaults.get("candle_timeframe", s_defaults.get("entry_timeframe", "1m"))
        all_required_data_types.add(f"kline_{tf}")
        # Adding required data for specific strategies (if any)
        # For example, 'aggTrade' might be needed for FakeBreakout, AggTradeReversal, VolumeBreakout
        # This should be defined in the strategies themselves or in their defaults
        temp_strat_instance = (
            get_strategy_instance(strategy_name)
            if get_strategy_instance is not None
            else None
        )
        if temp_strat_instance and hasattr(temp_strat_instance, "required_data_types"):
            all_required_data_types.update(temp_strat_instance.required_data_types)
        else:  # Fallback if the strategy has no explicit required_data_types
            if strategy_name in [
                "FakeBreakoutStrategy",
                "AggTradeReversalStrategy",
                "VolumeBreakoutStrategy",
            ]:  # Example
                all_required_data_types.add("aggTrade")

        search_space = optuna_search_space_all.get(strategy_name, {})
        for param, spec in search_space.items():
            if (
                param in ["candle_timeframe", "entry_timeframe", "trend_timeframe"]
                and isinstance(spec, (list, tuple))
                and len(spec) > 1
                and spec[0] == "categorical"
            ):
                if (
                    isinstance(spec[1], list)
                    and len(spec[1]) > 0
                    and isinstance(spec[1][0], list)
                ):
                    all_required_data_types.update(
                        f"kline_{tf_opt}" for tf_opt in spec[1][0]
                    )
    # Adding standard timeframes that might be needed for general indicators or context
    all_required_data_types.update({"kline_1d", "kline_1h", "kline_4h"})

    # 2. DATA LOADING (passing overlap_days)
    logger.info(f"{log_prefix} Loading data (Types: {all_required_data_types})...")
    try:
        symbol_historical_data = _load_data_for_process(
            symbol_to_optimize,
            backtest_start_dt=start_dt,
            backtest_end_dt=end_dt,
            overlap_days=overlap_days,
            required_data_types=all_required_data_types,
            use_local_data=use_local_data,
            local_data_path=local_data_path,
        )
        if not symbol_historical_data or not any(
            df is not None and not df.empty
            for k, df in symbol_historical_data.items()
            if k.startswith("kline_")
        ):
            logger.error(
                f"{log_prefix} Failed to load sufficient historical data (incl. overlap). Skipping."
            )
            return symbol_to_optimize, {}
    except Exception as e_load:
        logger.error(
            f"{log_prefix} Exception during data loading: {e_load}. Skipping optimization."
        )
        return symbol_to_optimize, {}

    # 3. LOOP THROUGH STRATEGIES
    for strategy_name in strategies_to_optimize:
        logger.info(f"{log_prefix} --- Starting Optuna for {strategy_name} ---")
        strategy_search_space = optuna_search_space_all.get(strategy_name)
        base_config_params = strategy_defaults_all.get(strategy_name, {}).copy()
        if not strategy_search_space:
            logger.warning(
                f"{log_prefix} No search space found for {strategy_name}. Skipping."
            )
            continue

        best_params: Optional[Dict[str, Any]] = None
        best_value: Optional[float] = None
        try:
            optimizer = BayesianOptimizer(
                objective_func=_optuna_objective_global,
                search_space=strategy_search_space,
                config_override=optuna_config,
                # Passing all necessary data via kwargs for _optuna_objective_global
                params={},  # This 'params' will be overwritten by Optuna in _objective_wrapper
                strategy_name=strategy_name,
                historical_data=symbol_historical_data,
                initial_balance=initial_balance,
                base_config=base_config_params,  # Passing 'base_config'
                symbol=symbol_to_optimize,
                exchange_info_all_symbols=exchange_info_all,  # Passing 'exchange_info_all_symbols'
                min_trades_required=min_trades_opt,
                backtester_execution_config=backtester_execution_config,  # Pass 'backtester_execution_config'
                strategy_defaults_all=strategy_defaults_all,
                optuna_study_config=optuna_config,  # Passing optuna_config as optuna_study_config
                actual_start_dt_for_backtest=start_dt,  # Actual backtest start for this run
                log_ml_confirmation_data_flag=log_ml_confirm_data_cfg,
                ml_confirmation_data_log_path=ml_confirm_path_cfg,
                y_true_min_move_pct_val=y_true_min_move_pct_cfg,
                y_true_max_drawdown_pct_val=y_true_max_drawdown_pct_cfg,
                enable_ml_confirmation_during_backtest=enable_ml_confirmation_during_backtest_cfg,
                ml_confirmation_model_path_override_val=ml_confirmation_model_path_override_val_cfg,
            )
            best_params = optimizer.optimize()
            best_value = optimizer.best_value
        except Exception as e_opt:
            logger.error(
                f"{log_prefix} Error during optimization for {strategy_name}: {e_opt}",
                exc_info=True,
            )

        symbol_results[strategy_name] = (best_params, best_value)
        logger.info(f"{log_prefix} --- Finished Optuna for {strategy_name} ---")

    logger.info(f"{log_prefix} Finished optimizing symbol: {symbol_to_optimize}")
    return symbol_to_optimize, symbol_results


MARKET_TYPE = "futures"  # Constant required for get_target_path


def get_partitioned_folder_name(data_type: str) -> str:
    """Returns the folder name for partitioned data."""
    mapping = {
        "aggTrades": "aggTrade",
        "klines_1s": "klines_1s",
        "bookDepth": "bookDepth",
    }
    if data_type not in mapping:
        raise ValueError(f"Data type {data_type} does not support partitioning.")
    return mapping[data_type]


def get_target_path(
    symbol: str,
    data_type: str,
    timeframe: str = None,
    partition_date: Optional[date] = None,
) -> Path:
    """Defines the path for saving/loading data."""
    # Note: This function is a simplified version from download_pipeline for loader needs
    base_path = (
        Path(getattr(config, "LOCAL_HISTORICAL_DATA_PATH", "data/historical_csv"))
        / "binance"
        / MARKET_TYPE
        / symbol.upper()
    )

    if data_type.startswith("kline_") and timeframe:
        return base_path / f"kline_{timeframe}.parquet"
    elif data_type == "open_interest":
        return base_path / "open_interest.parquet"
    elif data_type in ["aggTrades", "klines_1s", "bookDepth"]:
        if not partition_date:
            raise ValueError(
                f"Date (partition_date) is required for partitioning {data_type}."
            )
        folder_name = get_partitioned_folder_name(data_type)
        partition_path = (
            base_path
            / folder_name
            / f"year={partition_date.year}"
            / f"month={partition_date.month}"
        )
        return partition_path / "data.parquet"
    else:
        # Fallback for other keys, for example, 'klines' without a timeframe
        tf_from_key = data_type.split("_")[-1] if "_" in data_type else "1m"
        return base_path / f"kline_{tf_from_key}.parquet"


# NEW CSV reading function for processes
def _load_local_data_for_process(
    symbol: str,
    data_type_key: str,
    start_dt_utc: datetime,
    end_dt_utc: datetime,
    local_data_path: Path,
) -> Optional[pd.DataFrame]:
    """
    Loads data from local storage (Parquet).
    Supports both single files (klines) and partitioned ones (aggTrades, bookDepth).
    """
    pid = os.getpid()
    log_prefix = f"[LocalLoad:{pid}:{symbol}:{data_type_key}]"

    # 1. Logic for single Parquet files
    if data_type_key.startswith("kline_") or data_type_key == "open_interest":
        timeframe = (
            data_type_key.split("_")[1] if data_type_key.startswith("kline_") else None
        )
        target_path = get_target_path(symbol, data_type_key, timeframe)
        if not target_path.exists():
            logger.warning(f"{log_prefix} Parquet file not found: {target_path}")
            return None

        try:
            df = pd.read_parquet(target_path)
            # Filtering by date after loading
            df_filtered = df[
                (df.index >= start_dt_utc) & (df.index < end_dt_utc)
            ].copy()
            logger.info(
                f"{log_prefix} Loaded {len(df_filtered)} rows from single file {target_path.name}"
            )
            return df_filtered if not df_filtered.empty else None
        except Exception as e:
            logger.error(
                f"{log_prefix} Error reading single Parquet file {target_path}: {e}",
                exc_info=True,
            )
            return None

    # 2. Logic for partitioned data (aggTrades, bookDepth)
    elif data_type_key in ["aggTrades", "bookDepth", "klines_1s"]:
        try:
            folder_name = get_partitioned_folder_name(data_type_key)
        except ValueError as e:
            logger.error(f"{log_prefix} {e}")
            return None

        base_path = (
            local_data_path / "binance" / MARKET_TYPE / symbol.upper() / folder_name
        )
        if not base_path.exists():
            logger.warning(
                f"{log_prefix} Partitioned data base path does not exist: {base_path}"
            )
            return None

        # Defining the months that need to be loaded
        months_to_load = set()
        current_month_start = date(start_dt_utc.year, start_dt_utc.month, 1)
        while current_month_start <= end_dt_utc.date():
            months_to_load.add(current_month_start)
            if current_month_start.month == 12:
                current_month_start = current_month_start.replace(
                    year=current_month_start.year + 1, month=1
                )
            else:
                current_month_start = current_month_start.replace(
                    month=current_month_start.month + 1
                )

        all_chunks = []
        for month_key in sorted(list(months_to_load)):
            partition_path = (
                base_path
                / f"year={month_key.year}"
                / f"month={month_key.month}"
                / "data.parquet"
            )
            if partition_path.exists():
                try:
                    df_month = pd.read_parquet(partition_path)
                    all_chunks.append(df_month)
                except Exception as e:
                    logger.warning(
                        f"{log_prefix} Could not read partition file {partition_path}: {e}"
                    )

        if not all_chunks:
            logger.warning(
                f"{log_prefix} No valid partition files found for the date range."
            )
            return None

        try:
            final_df = pd.concat(all_chunks).sort_index()
            # Filter the final DataFrame by the exact range
            df_filtered = final_df[
                (final_df.index >= start_dt_utc) & (final_df.index < end_dt_utc)
            ].copy()
            logger.info(
                f"{log_prefix} Loaded {len(df_filtered)} rows from {len(all_chunks)} partition files."
            )
            return df_filtered if not df_filtered.empty else None
        except Exception as e_concat:
            logger.error(
                f"{log_prefix} Error concatenating partitioned data: {e_concat}",
                exc_info=True,
            )
            return None

    else:
        logger.error(
            f"{log_prefix} Unknown data type for local loading: {data_type_key}"
        )
        return None


def calculate_kpis_from_sim_log_standalone(
    sim_trade_log: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Calculates KPIs based on the log of simulated trades."""
    kpis: Dict[str, Any] = {
        "trades": 0,
        "total_pnl": 0.0,
        "profit_factor": 0.0,
        "max_drawdown": 0.0,
        "win_rate": 0.0,
        "total_commission": 0.0,
        "wins": 0,
        "losses": 0,
        "avg_trade_pnl": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "sharpe_ratio": 0.0,
        "max_consecutive_losses": 0,
        "ml_steps_processed": 0,
    }
    if not sim_trade_log:
        logger.info("No simulated trades to calculate KPIs for (standalone func).")
        return kpis

    trades = len(sim_trade_log)
    kpis["trades"] = trades
    if trades == 0:
        return kpis

    df_log = pd.DataFrame(sim_trade_log)
    if df_log.empty:
        return kpis

    if "pnl" not in df_log.columns or "commission" not in df_log.columns:
        logger.error(
            "Missing 'pnl' or 'commission' column in simulated trade log for KPI calculation."
        )
        return kpis

    df_log["pnl"] = pd.to_numeric(df_log["pnl"], errors="coerce").fillna(0)
    df_log["commission"] = pd.to_numeric(df_log["commission"], errors="coerce").fillna(
        0
    )

    kpis["total_pnl"] = df_log["pnl"].sum()
    kpis["total_commission"] = df_log["commission"].sum()

    wins_df = df_log[df_log["pnl"] > 0]
    losses_df = df_log[df_log["pnl"] < 0]

    kpis["wins"] = len(wins_df)
    kpis["losses"] = len(losses_df)

    sum_profit = wins_df["pnl"].sum()
    sum_loss = abs(losses_df["pnl"].sum())

    if sum_loss > 1e-9:
        kpis["profit_factor"] = sum_profit / sum_loss
    elif sum_profit > 0:
        kpis["profit_factor"] = 99999.0
    else:
        kpis["profit_factor"] = 0.0
    if math.isinf(kpis["profit_factor"]):
        kpis["profit_factor"] = 99999.0

    if kpis["trades"] > 0:
        kpis["win_rate"] = (kpis["wins"] / kpis["trades"]) * 100.0
        kpis["avg_trade_pnl"] = kpis["total_pnl"] / kpis["trades"]
        kpis["avg_win"] = sum_profit / kpis["wins"] if kpis["wins"] > 0 else 0.0
        kpis["avg_loss"] = sum_loss / kpis["losses"] if kpis["losses"] > 0 else 0.0

    if not df_log["pnl"].empty:
        equity_curve = df_log["pnl"].cumsum()
        rolling_max = equity_curve.cummax()
        drawdown_abs = equity_curve - rolling_max
        kpis["max_drawdown"] = drawdown_abs.min() if not drawdown_abs.empty else 0.0

    max_consecutive_losses_val = 0
    current_consecutive_losses = 0
    for pnl_val in df_log["pnl"]:
        if pnl_val < 0:
            current_consecutive_losses += 1
        else:
            if current_consecutive_losses > 0:
                max_consecutive_losses_val = max(
                    max_consecutive_losses_val, current_consecutive_losses
                )
            current_consecutive_losses = 0
    kpis["max_consecutive_losses"] = max(
        max_consecutive_losses_val, current_consecutive_losses
    )

    if kpis["trades"] > 1:
        pnl_std = df_log["pnl"].std()
        if pnl_std is not None and pnl_std > 1e-9 and not pd.isna(pnl_std):
            kpis["sharpe_ratio"] = (kpis["avg_trade_pnl"] / pnl_std) * (
                kpis["trades"] ** 0.5
            )
        elif kpis["avg_trade_pnl"] > 0:
            kpis["sharpe_ratio"] = float("inf")
        else:
            kpis["sharpe_ratio"] = 0.0
    else:
        kpis["sharpe_ratio"] = 0.0
    if math.isinf(kpis["sharpe_ratio"]):
        kpis["sharpe_ratio"] = 99999.0

    if "ml_steps_processed" in df_log.columns:
        kpis["ml_steps_processed"] = int(
            df_log["ml_steps_processed"].sum()
        )  # Ensure it's int

    return kpis


optuna_base_config_tr_global_scope = getattr(config, "TRAINER_OPTUNA_CONFIG", {})
DEFAULT_METRIC_TR_GLOBAL_SCOPE = optuna_base_config_tr_global_scope.get(
    "metric_name", "profit_factor"
)


class Trainer:
    def __init__(self):
        default_log_file = "logs/trades_and_events.csv"
        config_log_file = getattr(config, "LOG_FILE_TRADES", None)
        self.log_file = Path(
            config_log_file if config_log_file is not None else default_log_file
        )
        default_opt_file = "data/optimized_params.json"
        config_opt_file = getattr(config, "OPTIMIZED_PARAMS_FILE", None)
        self.optimized_params_file = Path(
            config_opt_file if config_opt_file is not None else default_opt_file
        )
        default_lookback = 90
        config_lookback = getattr(config, "TRAINER_DATA_LOOKBACK_DAYS", None)
        self.lookback_days = (
            config_lookback if config_lookback is not None else default_lookback
        )
        self.optimization_method = getattr(
            config, "TRAINER_OPTIMIZATION_METHOD", "bayesian"
        ).lower()
        self.min_trades_for_optimization = getattr(
            config, "TRAINER_MIN_TRADES_OPTIMIZE", 20
        )
        self.param_grid = getattr(config, "TRAINER_PARAM_GRID", {})
        self.optuna_config = getattr(config, "TRAINER_OPTUNA_CONFIG", {})
        self.optuna_search_space = getattr(config, "TRAINER_OPTUNA_SEARCH_SPACE", {})
        self.strategy_defaults = getattr(config, "STRATEGY_DEFAULTS", {})
        self.backtest_initial_balance = getattr(
            config, "BACKTEST_INITIAL_BALANCE", 10000.0
        )
        self.backtest_execution_config = {
            "commission_pct": getattr(config, "BACKTEST_COMMISSION_PCT", 0.0004),
            "slippage_pct": getattr(config, "BACKTEST_SLIPPAGE_PCT", 0.0002),
        }
        self.exchange_info_cache = {}
        self._exchange_info_lock = threading.Lock()
        self._last_exchange_info_update = 0
        self.data_cache: Dict[
            str, Tuple[float, pd.DataFrame]
        ] = {}  # For _load_historical_data (API mode)
        self.data_cache_ttl = getattr(
            config, "DATA_LOADER_CACHE_TTL_SECONDS", 3600 * 6
        )  # For _load_historical_data (API mode)

        self.optimized_params = self._load_optimized_params()
        try:
            self.mp_context = multiprocessing.get_context("spawn")
        except Exception:  # pragma: no cover
            logger.warning(
                "Failed to get 'spawn' multiprocessing context, falling back to default."
            )
            self.mp_context = multiprocessing.get_context(None)  # type: ignore

        self.ml_trained_model_path = Path(
            getattr(
                config,
                "ML_OFFLINE_TRAINED_MODEL_PATH",
                "data/offline_trained_model.pkl",
            )
        )
        self.ml_training_report_file = Path(
            getattr(config, "ML_TRAINING_REPORT_FILE", "logs/ml_training_report.json")
        )
        self.use_local_data = getattr(config, "USE_LOCAL_HISTORICAL_DATA", False)
        self.local_data_path = Path(
            getattr(config, "LOCAL_HISTORICAL_DATA_PATH", "data_storage")
        )
        logger.info(
            f"Trainer initialized. Opt Method: {self.optimization_method.upper()}. Log file: {self.log_file}, Opt file: {self.optimized_params_file}, Lookback: {self.lookback_days} days, Min trades: {self.min_trades_for_optimization}"
        )
        logger.info(f"ML Model Path (Offline Trained): {self.ml_trained_model_path}")
        logger.info(f"ML Training Report File: {self.ml_training_report_file}")
        logger.info(
            f"Using local historical data: {self.use_local_data}, Path: {self.local_data_path}"
        )

    def _get_exchange_info(self, force_update: bool = False) -> Dict[str, Any]:
        """
        Retrieves or updates exchange information (symbols, filters, precision).
        Caches the result.
        """
        now = time.time()
        cache_duration = 3600  # 1 hour
        log_prefix = "[ExchangeInfo]"

        with self._exchange_info_lock:
            if (
                not force_update
                and self.exchange_info_cache
                and (now - self._last_exchange_info_update < cache_duration)
            ):
                return self.exchange_info_cache

            logger.info(f"{log_prefix} Fetching/Updating exchange information...")
            all_info = {}
            try:
                if _make_api_request is None:
                    raise RuntimeError(
                        "_make_api_request function is not available (Import Error?)"
                    )

                raw_info = _make_api_request("exchangeInfo")

                if raw_info and isinstance(raw_info.get("symbols"), list):
                    for symbol_data in raw_info["symbols"]:
                        symbol = symbol_data.get("symbol")
                        if not symbol:
                            logger.warning(
                                f"{log_prefix} Skipping symbol data with missing 'symbol' key."
                            )
                            continue

                        filters = symbol_data.get("filters", [])
                        if not isinstance(filters, list):
                            logger.warning(
                                f"{log_prefix} Invalid 'filters' type for {symbol}: {type(filters)}. Treating as empty."
                            )
                            filters = []

                        try:
                            lot_params_filter = next(
                                (
                                    f
                                    for f in filters
                                    if f.get("filterType") == "LOT_SIZE"
                                ),
                                None,
                            )
                            price_filter = next(
                                (
                                    f
                                    for f in filters
                                    if f.get("filterType") == "PRICE_FILTER"
                                ),
                                None,
                            )
                            notional_filter = next(
                                (
                                    f
                                    for f in filters
                                    if f.get("filterType") == "NOTIONAL"
                                ),
                                None,
                            )
                            if not notional_filter:
                                notional_filter = next(
                                    (
                                        f
                                        for f in filters
                                        if f.get("filterType") == "MIN_NOTIONAL"
                                    ),
                                    None,
                                )

                            tick_size = (
                                float(price_filter["tickSize"])
                                if price_filter and "tickSize" in price_filter
                                else None
                            )
                            lot_params = None
                            if lot_params_filter and all(
                                k in lot_params_filter
                                for k in ["minQty", "maxQty", "stepSize"]
                            ):
                                lot_params = {
                                    "minQty": float(lot_params_filter["minQty"]),
                                    "maxQty": float(lot_params_filter["maxQty"]),
                                    "stepSize": float(lot_params_filter["stepSize"]),
                                }
                            min_notional = None
                            if notional_filter:
                                min_notional_key = (
                                    "minNotional"
                                    if "minNotional" in notional_filter
                                    else (
                                        "notional"
                                        if "notional" in notional_filter
                                        else None
                                    )
                                )
                                if (
                                    min_notional_key
                                    and min_notional_key in notional_filter
                                ):
                                    min_notional = float(
                                        notional_filter[min_notional_key]
                                    )

                            all_info[symbol] = {
                                "tick_size": tick_size,
                                "lot_params": lot_params,
                                "min_notional": min_notional,
                                "status": symbol_data.get("status"),
                                "baseAsset": symbol_data.get("baseAsset"),
                                "quoteAsset": symbol_data.get("quoteAsset"),
                            }
                        except (KeyError, ValueError, TypeError) as e_filter:
                            logger.warning(
                                f"{log_prefix} Could not parse filters for {symbol}: {e_filter}. Saving basic info."
                            )
                            all_info[symbol] = {"status": symbol_data.get("status")}

                    self.exchange_info_cache = all_info
                    self._last_exchange_info_update = now
                    logger.info(
                        f"{log_prefix} Exchange information updated. Processed {len(all_info)} symbols."
                    )
                else:
                    logger.error(
                        f"{log_prefix} Failed to fetch valid exchange info. Response: {str(raw_info)[:500]}"
                    )

            except RuntimeError as e_runtime:
                logger.critical(
                    f"{log_prefix} Runtime error during exchange info fetch: {e_runtime}"
                )
            except Exception as e:
                logger.error(
                    f"{log_prefix} Error fetching exchange information: {e}",
                    exc_info=True,
                )

            return self.exchange_info_cache

    async def _load_historical_data(
        self,
        symbol: str,
        start_dt: datetime,
        end_dt: datetime,
        required_data_types: Set[str],
        market_type: str = "futures_usdtm",
        **kwargs,
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """
        (FIXED) Loads all necessary historical data in parallel,
        including bookDepth from local storage.
        """
        log_prefix = f"[Trainer._load_historical_data|{symbol}]"
        logger.info(
            f"{log_prefix} Loading historical data. Required types: {required_data_types}."
        )

        tasks = {}
        # Use the current event loop to run a synchronous function in a separate thread
        loop = asyncio.get_running_loop()

        for data_type in required_data_types:
            if data_type.startswith("kline_"):
                parts = data_type.split("_", 2)
                timeframe = parts[1]
                symbol_for_task = parts[2] if len(parts) == 3 else symbol
                tasks[data_type] = download_klines(
                    symbol_for_task, timeframe, start_dt, end_dt, market_type
                )
            elif data_type == "aggTrade":
                tasks[data_type] = download_agg_trades(
                    symbol, start_dt, end_dt, market_type
                )
            elif data_type == "open_interest":
                tasks[data_type] = download_open_interest(symbol, start_dt, end_dt)
            elif data_type == "bookDepth":
                logger.info(
                    f"{log_prefix} 'bookDepth' data is always loaded from local storage."
                )
                # Run the synchronous loading function in a thread pool executor
                tasks[data_type] = loop.run_in_executor(
                    None,  # Use the default executor
                    _load_local_data_for_process,
                    symbol,
                    data_type,
                    start_dt.replace(tzinfo=timezone.utc),  # Ensure time is in UTC
                    end_dt.replace(tzinfo=timezone.utc),
                    self.local_data_path,
                )

        loaded_data_results = await asyncio.gather(
            *tasks.values(), return_exceptions=True
        )

        historical_data: Dict[str, Optional[pd.DataFrame]] = {}
        data_keys = list(tasks.keys())
        for i, result in enumerate(loaded_data_results):
            key = data_keys[i]
            if isinstance(result, Exception):
                logger.error(f"{log_prefix} Failed to load data '{key}': {result}")
                historical_data[key] = None
            else:
                if key == "bookDepth" and (result is None or result.empty):
                    logger.warning(
                        f"{log_prefix} 'bookDepth' data not found in local storage or is empty."
                    )
                historical_data[key] = result

        # Step 2: Check if enrichment is needed for the main DataFrame (usually kline_1m)
        main_kline_key = next(
            (
                k
                for k in historical_data
                if k.startswith("kline_") and "BTCUSDT" not in k
            ),
            None,
        )
        if not main_kline_key or historical_data.get(main_kline_key) is None:
            logger.error(
                f"{log_prefix} Failed to load main Klines for symbol {symbol}. Backtest is impossible."
            )
            return {}

        main_kline_df = historical_data[main_kline_key]

        required_enrichment_cols = {"relative_volume", "natr", "is_volume_spike"}
        missing_cols = required_enrichment_cols - set(main_kline_df.columns)

        if not missing_cols:
            logger.info(
                f"{log_prefix} Main DataFrame ({main_kline_key}) is already enriched. Skipping recalculation."
            )
        else:
            logger.info(
                f"{log_prefix} In DataFrame ({main_kline_key}) columns are missing: {missing_cols}. Enrichment in progress..."
            )

            if "relative_volume" in missing_cols or "is_volume_spike" in missing_cols:
                agg_trades_df = historical_data.get("aggTrade")
                if agg_trades_df is not None and not agg_trades_df.empty:
                    main_kline_df = add_relative_volume(main_kline_df, agg_trades_df)
                    main_kline_df = add_volume_percentile_rank(main_kline_df)
                else:
                    logger.warning(
                        f"{log_prefix} Failed to enrich volume because aggTrade is not loaded. Default values will be used."
                    )
                    if "relative_volume" not in main_kline_df.columns:
                        main_kline_df["relative_volume"] = 1.0
                    if "is_volume_spike" not in main_kline_df.columns:
                        main_kline_df["is_volume_spike"] = False

            if "natr" in missing_cols:
                main_kline_df = calculate_scalper_natr(main_kline_df)

            historical_data[main_kline_key] = main_kline_df

        logger.info(f"{log_prefix} Data loading and enrichment completed.")
        return historical_data

    @staticmethod
    def _decode_strategy_config_payload(payload: Any) -> Any:
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except Exception:
                return payload
        return payload

    @classmethod
    def _normalize_strategy_config_for_requirements(
        cls, params: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if not isinstance(params, dict):
            return {}

        result: Any = params
        for key in ("config_data", "strategy", "strategy_json", "config"):
            if isinstance(result, dict) and key in result:
                inner = cls._decode_strategy_config_payload(result.get(key))
                if isinstance(inner, dict):
                    result = inner

        return result if isinstance(result, dict) else {}

    @classmethod
    def _is_config_based_strategy_params(cls, params: Optional[Dict[str, Any]]) -> bool:
        strategy_config = cls._normalize_strategy_config_for_requirements(params)
        visual_keys = {
            "entryConditions",
            "filters",
            "initialization",
            "positionManagement",
            "conditions",
        }
        return any(key in strategy_config for key in visual_keys)

    @classmethod
    def _collect_data_requirements_from_strategy_config(
        cls, node: Any, required: Set[str]
    ) -> None:
        if isinstance(node, list):
            for item in node:
                cls._collect_data_requirements_from_strategy_config(item, required)
            return
        if not isinstance(node, dict):
            return

        block_type = str(node.get("type", "") or "").strip().lower()
        params = node.get("params", {})
        if not isinstance(params, dict):
            params = {}

        block_data_requirements = {
            "order_book_zone": {"bookDepth"},
            "l2_microstructure": {"bookDepth"},
            "l2_microstructure_check": {"bookDepth"},
            "orderbook_imbalance": {"bookDepth"},
            "tape_acceleration": {"aggTrade"},
            "tape_analysis": {"aggTrade"},
            "tape_condition": {"aggTrade"},
            "volume_spike": {"aggTrade"},
            "significant_level": {"kline_1h", "kline_4h", "kline_1d"},
            "btc_state_filter": {"kline_1m_BTCUSDT"},
            "correlation": {"kline_1m_BTCUSDT"},
            "open_interest": {"open_interest"},
        }
        required.update(block_data_requirements.get(block_type, set()))

        for tf in (
            node.get("timeframe"),
            params.get("timeframe"),
            node.get("tradingTimeframe"),
            params.get("tradingTimeframe"),
            node.get("candle_timeframe"),
            params.get("candle_timeframe"),
            node.get("entry_timeframe"),
            params.get("entry_timeframe"),
            node.get("trend_timeframe"),
            params.get("trend_timeframe"),
        ):
            if isinstance(tf, str) and tf and tf != "auto":
                required.add(f"kline_{tf}")

        entry_trigger = node.get("entryTrigger")
        if isinstance(entry_trigger, dict):
            tf = entry_trigger.get("timeframe")
            if isinstance(tf, str) and tf:
                required.add(f"kline_{tf}")

        for value in node.values():
            if isinstance(value, (dict, list)):
                cls._collect_data_requirements_from_strategy_config(value, required)

    def get_data_requirements_for_strategy(
        self, strategy_name: str, params: Dict[str, Any], symbol: str, market_type: str
    ) -> Set[str]:
        """
        Defines the necessary data types for the strategy, including analysis
        of the JSON configuration for VisualBuilderStrategy.

        Args:
            strategy_name (str): Strategy name.
            params (Dict[str, Any]): Strategy parameters.
            symbol (str): Symbol for which the check is performed.
            market_type (str): Market type ('futures', 'spot').
        """
        # Local import to ensure function availability (workaround for module loading order issues in Celery)
        try:
            from bot_module.strategy import (
                get_strategy_instance as _get_strategy_instance,
            )
        except ImportError:
            logger.warning(
                "[get_data_requirements_for_strategy] Failed to import get_strategy_instance locally. Using global reference."
            )
            _get_strategy_instance = (
                get_strategy_instance  # Fallback to global variable
            )

        required_data_types: Set[str] = set()

        # 1. Get base requirements from the strategy instance
        if _get_strategy_instance is None:
            logger.warning(
                f"[get_data_requirements_for_strategy] get_strategy_instance is None (import failed?). Skipping strategy instance check for '{strategy_name}'."
            )
            temp_strat_instance = None
        else:
            temp_strat_instance = _get_strategy_instance(strategy_name)
        if temp_strat_instance and hasattr(temp_strat_instance, "required_data_types"):
            required_data_types.update(temp_strat_instance.required_data_types)

        # 2. If it is a strategy based on a JSON config, analyze its config
        # Supported: VisualBuilderStrategy, GeneticStrategy, GeneticCompatibleStrategy
        config_based_strategies = {
            "VisualBuilderStrategy",
            "GeneticStrategy",
            "GeneticCompatibleStrategy",
        }
        if params and (
            strategy_name in config_based_strategies
            or self._is_config_based_strategy_params(params)
        ):
            strategy_config = self._normalize_strategy_config_for_requirements(params)
            self._collect_data_requirements_from_strategy_config(
                strategy_config, required_data_types
            )

        # 3. Adding timeframes specified in the parameters
        s_defaults = self.strategy_defaults.get(strategy_name, {})
        base_config_params = s_defaults.copy()
        if params:
            base_config_params.update(params)

        tf = base_config_params.get(
            "candle_timeframe", base_config_params.get("entry_timeframe", "1m")
        )
        required_data_types.add(f"kline_{tf}")

        trend_tf = base_config_params.get("trend_timeframe")
        if trend_tf:
            required_data_types.add(f"kline_{trend_tf}")

        # 4. Add standard timeframes for general context
        required_data_types.update({"kline_1d", "kline_1h", "kline_4h"})

        logger.info(
            f"LOG #1 [Trainer]: For strategy '{strategy_name}' ({symbol}) the following data types are defined for loading: {required_data_types}"
        )

        return required_data_types

    def _load_trade_logs(self) -> Optional[pd.DataFrame]:
        log_path = Path(self.log_file)
        if not log_path.exists():
            logger.warning(f"Log file not found: {self.log_file}")
            return None
        try:
            df = pd.read_csv(self.log_file, sep=",", low_memory=False)
            if df.empty:
                logger.info("Trade log file is empty.")
                return None

            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
            df.dropna(
                subset=["timestamp"], inplace=True
            )  # Removing rows with invalid timestamp
            cutoff_date_utc = datetime.now(timezone.utc) - timedelta(
                days=self.lookback_days
            )
            df = df[
                df["timestamp"] >= cutoff_date_utc
            ].copy()  # Filtering by lookback_days
            if df.empty:
                logger.info(
                    f"No trade records found within the last {self.lookback_days} days."
                )
                return None

            # Filter only position closing events
            df_closed = df[df["event_type"] == "POSITION_CLOSED"].copy()
            if df_closed.empty:
                logger.info(
                    "No 'POSITION_CLOSED' events found in the specified period."
                )
                return None

            # Converting numerical columns
            numeric_cols_target = [
                "entry_price",
                "exit_price",
                "quantity",
                "pnl",
                "initial_stop_loss",
                "initial_take_profit",
                "entry_atr",
                "trigger_price",
                "commission",
            ]
            cols_to_convert = [
                col for col in numeric_cols_target if col in df_closed.columns
            ]
            for col in cols_to_convert:
                if not pd.api.types.is_numeric_dtype(
                    df_closed[col]
                ):  # Checking if conversion is needed
                    df_closed[col] = pd.to_numeric(df_closed[col], errors="coerce")

            # Convert direction to Enum
            if "direction" in df_closed.columns:
                df_closed["direction_enum"] = df_closed["direction"].apply(
                    lambda x: (
                        SignalDirection.LONG
                        if x == "LONG"
                        else (SignalDirection.SHORT if x == "SHORT" else None)
                    )
                )
            else:
                logger.error("Column 'direction' not found in log file.")
                return None  # Cannot continue without direction

            # Check for the presence of main columns for KPI and simulation
            required_for_kpi_and_sim_base = [
                "strategy",
                "pnl",
                "direction_enum",
                "entry_price",
                "quantity",
                "symbol",
            ]
            cols_exist_in_df = [
                col for col in required_for_kpi_and_sim_base if col in df_closed.columns
            ]

            initial_rows = len(df_closed)
            df_closed.dropna(
                subset=cols_exist_in_df, inplace=True
            )  # Remove rows with NaN in key columns
            dropped_rows_base = initial_rows - len(df_closed)
            if dropped_rows_base > 0:
                logger.warning(
                    f"Dropped {dropped_rows_base} rows due to NaN in base required columns: {cols_exist_in_df}"
                )

            if df_closed.empty:
                logger.warning(
                    "No valid records remain after base NaN checks for KPI/Simulation."
                )
                return None

            # Data check for SL/TP simulation (without deleting rows, just logging)
            has_atr = "entry_atr" in df_closed.columns and df_closed[
                "entry_atr"
            ].notna() & (df_closed["entry_atr"] > 1e-9)
            has_initial_sl = (
                "initial_stop_loss" in df_closed.columns
                and df_closed["initial_stop_loss"].notna()
            )
            has_initial_tp = (
                "initial_take_profit" in df_closed.columns
                and df_closed["initial_take_profit"].notna()
            )
            can_simulate_sl_tp = has_atr | (has_initial_sl & has_initial_tp)
            num_cannot_simulate = len(df_closed[~can_simulate_sl_tp])
            if num_cannot_simulate > 0:
                logger.warning(
                    f"Found {num_cannot_simulate} trades where SL/TP simulation might be inaccurate due to missing 'entry_atr' or 'initial_sl/tp'. These trades will use actual PnL for simulation if SL/TP params are provided."
                )

            logger.info(
                f"Loaded {len(df_closed)} trade records potentially usable for KPI/Simulation."
            )
            return df_closed

        except KeyError as e:
            logger.error(
                f"KeyError processing log file {self.log_file}: Column '{e}' not found.",
                exc_info=True,
            )
            return None
        except Exception as e:
            logger.error(
                f"Error loading or processing log file {self.log_file}: {e}",
                exc_info=True,
            )
            return None

    def _simulate_trade_outcome(
        self, trade_data: pd.Series, params: Dict[str, Any]
    ) -> Optional[float]:
        """
        Recalculates trade PnL taking into account NEW SL/TP parameters from `params`.
        Uses data from the `trade_data` log.
        Returns simulated PnL or None if simulation is not possible.
        """
        log_prefix = f"[Simulate:{trade_data.get('strategy', 'Unk')}:{trade_data.get('symbol', 'Unk')}:{trade_data.name}]"
        try:
            entry_price = trade_data["entry_price"]
            exit_price = trade_data["exit_price"]
            quantity = trade_data["quantity"]
            direction = trade_data["direction_enum"]
            actual_pnl = trade_data["pnl"]
            if (
                pd.isna(entry_price)
                or pd.isna(exit_price)
                or pd.isna(quantity)
                or direction is None
            ):
                return actual_pnl

            new_sl_mult = params.get("stop_loss_atr_multiplier")
            new_tp_mult = params.get("take_profit_atr_multiplier")
            if (
                new_sl_mult is None or new_tp_mult is None
            ):  # If the required keys are not in params, simulation is impossible
                # logger.debug(f"{log_prefix} No SL/TP multipliers in params. Returning actual PnL.")
                return actual_pnl

            entry_atr = trade_data.get("entry_atr")
            trigger_price = trade_data.get("trigger_price")
            initial_sl = trade_data.get("initial_stop_loss")
            initial_tp = trade_data.get("initial_take_profit")
            strategy_name = trade_data.get("strategy")

            entry_price_d = Decimal(str(entry_price))
            exit_price_d = Decimal(str(exit_price))
            quantity_d = Decimal(str(quantity))
            sl_new_d, tp_new_d = None, None
            calculation_base_price_d = (
                Decimal(str(trigger_price))
                if not pd.isna(trigger_price)
                else entry_price_d
            )

            if not pd.isna(entry_atr) and entry_atr > 1e-9:
                entry_atr_d = Decimal(str(entry_atr))
                new_sl_mult_d = Decimal(str(new_sl_mult))
                new_tp_mult_d = Decimal(str(new_tp_mult))
                stop_distance = entry_atr_d * new_sl_mult_d
                profit_distance = entry_atr_d * new_tp_mult_d
                if direction == SignalDirection.LONG:
                    sl_new_d = calculation_base_price_d - stop_distance
                    tp_new_d = calculation_base_price_d + profit_distance
                else:
                    sl_new_d = calculation_base_price_d + stop_distance
                    tp_new_d = calculation_base_price_d - profit_distance
            elif (
                not pd.isna(initial_sl) and not pd.isna(initial_tp) and strategy_name
            ):  # Attempting to restore from initial_sl/tp
                initial_sl_d = Decimal(str(initial_sl))
                initial_tp_d = Decimal(str(initial_tp))
                # Default multipliers are needed for this strategy to understand the initial distances
                strategy_defaults_all = getattr(config, "STRATEGY_DEFAULTS", {})
                s_defaults = strategy_defaults_all.get(strategy_name, {})
                default_sl_mult = s_defaults.get("stop_loss_atr_multiplier", None)
                default_tp_mult = s_defaults.get("take_profit_atr_multiplier", None)

                if (
                    default_sl_mult is not None
                    and default_tp_mult is not None
                    and default_sl_mult > 0
                    and default_tp_mult > 0
                ):
                    # Assume that initial_sl/tp were set based on some entry_atr,
                    # which we are now trying to "restore" or scale the distance.
                    # This is less accurate than having an explicit entry_atr.
                    # Calculate initial distances from the entry/trigger price
                    stop_dist_orig_d = abs(calculation_base_price_d - initial_sl_d)
                    profit_dist_orig_d = abs(initial_tp_d - calculation_base_price_d)

                    # Scale distances based on new multipliers relative to default ones
                    # (if entry_atr was X, then stop_dist_orig = X * default_sl_mult)
                    # new_stop_dist = X * new_sl_mult = stop_dist_orig * (new_sl_mult / default_sl_mult)
                    new_stop_dist_d = stop_dist_orig_d * (
                        Decimal(str(new_sl_mult)) / Decimal(str(default_sl_mult))
                    )
                    new_profit_dist_d = profit_dist_orig_d * (
                        Decimal(str(new_tp_mult)) / Decimal(str(default_tp_mult))
                    )

                    if direction == SignalDirection.LONG:
                        sl_new_d = calculation_base_price_d - new_stop_dist_d
                        tp_new_d = calculation_base_price_d + new_profit_dist_d
                    else:
                        sl_new_d = calculation_base_price_d + new_stop_dist_d
                        tp_new_d = calculation_base_price_d - new_profit_dist_d
                else:  # Cannot restore, returning actual_pnl
                    # logger.debug(f"{log_prefix} Cannot simulate based on initial SL/TP due to missing defaults. Returning actual PnL.")
                    return actual_pnl
            else:  # Insufficient data for simulation
                # logger.debug(f"{log_prefix} Insufficient data for SL/TP simulation. Returning actual PnL.")
                return actual_pnl

            if sl_new_d is None or tp_new_d is None:
                return actual_pnl  # Failed to calculate
            # Check validity of new SL/TP
            if direction == SignalDirection.LONG and (
                sl_new_d >= calculation_base_price_d
                or tp_new_d <= calculation_base_price_d
            ):
                return actual_pnl
            if direction == SignalDirection.SHORT and (
                sl_new_d <= calculation_base_price_d
                or tp_new_d >= calculation_base_price_d
            ):
                return actual_pnl

            simulated_exit_price_d = exit_price_d  # Default is the actual exit price
            if direction == SignalDirection.LONG:
                if exit_price_d <= sl_new_d:
                    simulated_exit_price_d = sl_new_d  # Closing by new SL
                elif exit_price_d >= tp_new_d:
                    simulated_exit_price_d = tp_new_d  # Closing by new TP
                simulated_pnl = float(
                    (simulated_exit_price_d - entry_price_d) * quantity_d
                )
            elif direction == SignalDirection.SHORT:
                if exit_price_d >= sl_new_d:
                    simulated_exit_price_d = sl_new_d  # Closing by new SL
                elif exit_price_d <= tp_new_d:
                    simulated_exit_price_d = tp_new_d  # Closing by new TP
                simulated_pnl = float(
                    (entry_price_d - simulated_exit_price_d) * quantity_d
                )
            else:  # In case direction_enum is None (although we filtered it)
                return actual_pnl

            # logger.debug(f"{log_prefix} Actual PnL: {actual_pnl:.4f}, Simulated PnL: {simulated_pnl:.4f} (New SL: {sl_new_d}, New TP: {tp_new_d})")
            return simulated_pnl

        except Exception as e:
            logger.error(
                f"{log_prefix} Error simulating trade outcome: {e}", exc_info=True
            )
            return trade_data.get("pnl")

    def _calculate_kpis_simulated(
        self, strategy_trades: pd.DataFrame, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Calculates KPIs for a strategy based on SIMULATED results."""
        kpis: Dict[str, Any] = {
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
        }
        if strategy_trades.empty:
            return kpis

        simulated_pnl_series = strategy_trades.apply(
            lambda row: self._simulate_trade_outcome(row, params), axis=1
        ).fillna(0)

        kpis["trades"] = len(simulated_pnl_series)
        if kpis["trades"] == 0:
            return kpis

        kpis["total_pnl"] = simulated_pnl_series.sum()

        # Commission remains actual from the log, as the simulation only changes PnL from SL/TP
        if "commission" in strategy_trades.columns:
            kpis["total_commission"] = (
                pd.to_numeric(strategy_trades["commission"], errors="coerce")
                .fillna(0)
                .sum()
            )

        wins_series = simulated_pnl_series[simulated_pnl_series > 0]
        losses_series = simulated_pnl_series[simulated_pnl_series < 0]
        kpis["wins"] = len(wins_series)
        kpis["losses"] = len(losses_series)

        sum_profit = wins_series.sum()
        sum_loss = abs(losses_series.sum())

        if sum_loss > 1e-9:
            kpis["profit_factor"] = sum_profit / sum_loss
        elif sum_profit > 0:
            kpis["profit_factor"] = 99999.0  # float('inf')
        else:
            kpis["profit_factor"] = 0.0
        if math.isinf(kpis["profit_factor"]):
            kpis["profit_factor"] = 99999.0

        if kpis["trades"] > 0:
            kpis["win_rate"] = (kpis["wins"] / kpis["trades"]) * 100.0
            kpis["avg_trade_pnl"] = kpis["total_pnl"] / kpis["trades"]
            kpis["avg_win"] = sum_profit / kpis["wins"] if kpis["wins"] > 0 else 0.0
            kpis["avg_loss"] = sum_loss / kpis["losses"] if kpis["losses"] > 0 else 0.0

        if not simulated_pnl_series.empty:
            equity_curve = simulated_pnl_series.cumsum()
            rolling_max = equity_curve.cummax()
            drawdown = equity_curve - rolling_max
            kpis["max_drawdown"] = drawdown.min() if not drawdown.empty else 0.0

        consecutive_losses_val = 0
        current_consecutive_losses = 0
        for pnl_val in simulated_pnl_series:
            if pnl_val < 0:
                current_consecutive_losses += 1
            else:
                if current_consecutive_losses > 0:
                    consecutive_losses_val = max(
                        consecutive_losses_val, current_consecutive_losses
                    )
                current_consecutive_losses = 0
        kpis["max_consecutive_losses"] = max(
            consecutive_losses_val, current_consecutive_losses
        )

        # Sharpe Ratio (simplified, without risk-free)
        if kpis["trades"] > 1:
            pnl_std = simulated_pnl_series.std()
            if pnl_std is not None and pnl_std > 1e-9 and not pd.isna(pnl_std):
                # Use kpis['avg_trade_pnl'] as the average PnL
                # Can be "annualized" by the square root of the number of trades, assuming independence
                kpis["sharpe_ratio"] = (kpis["avg_trade_pnl"] / pnl_std) * (
                    kpis["trades"] ** 0.5
                )
            elif kpis["avg_trade_pnl"] > 0:
                kpis["sharpe_ratio"] = float("inf")  # All PnL are identical and > 0
            else:
                kpis["sharpe_ratio"] = 0.0
        else:
            kpis["sharpe_ratio"] = 0.0
        if math.isinf(kpis["sharpe_ratio"]):
            kpis["sharpe_ratio"] = 99999.0  # Replacing inf

        return kpis

    def _log_performance_report(
        self,
        kpis_by_strategy: Dict[str, Dict[str, Any]],
        title="--- Performance Report ---",
    ):
        """Logs a performance report by strategies."""
        report = [title]
        if not kpis_by_strategy:
            report.append("  No data to report.")
        else:
            # Sort by total_pnl for output
            sorted_strategies = sorted(
                kpis_by_strategy.items(),
                key=lambda item: item[1].get("total_pnl", -float("inf")),
                reverse=True,
            )
            for strategy_name, metrics in sorted_strategies:
                if not metrics or metrics.get("trades", 0) == 0:
                    # report.append(f"\nStrategy: {strategy_name} - No trades or data.")
                    continue  # Skip strategies without trades

                report.append(
                    f"\nStrategy: {strategy_name} ({metrics.get('trades', 0)} trades)"
                )
                report.append(f"  Total PnL:     {metrics.get('total_pnl', 0):,.2f}")
                report.append(f"  Win Rate:      {metrics.get('win_rate', 0):.2f}%")
                pf = metrics.get("profit_factor", 0)
                pf_str = (
                    f"{pf:.2f}"
                    if pf != float("inf") and pf != 99999.0
                    else ("Inf" if pf == 99999.0 else "0.00")
                )
                report.append(f"  Profit Factor: {pf_str}")
                report.append(
                    f"  Avg Win / Loss: {metrics.get('avg_win', 0):.2f} / {metrics.get('avg_loss', 0):.2f}"
                )
                report.append(
                    f"  Max Drawdown:  {metrics.get('max_drawdown', 0):.2f}"
                )  # Usually a negative value
                report.append(
                    f"  Max Consec Losses: {metrics.get('max_consecutive_losses', 0)}"
                )
                report.append(f"  Sharpe Ratio:  {metrics.get('sharpe_ratio', 0):.2f}")
                report.append(
                    f"  Total Comm:    {metrics.get('total_commission', 0):.2f}"
                )

        logger.info("\n".join(report))

    def run_grid_search(self, df_trades: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """Performs Grid Search with SIMULATION of results."""
        best_params_found: Dict[str, Dict[str, Any]] = {}
        if df_trades is None or df_trades.empty:
            logger.warning("No trade data provided for Grid Search. Skipping.")
            return best_params_found

        all_strategy_names_in_log = df_trades["strategy"].unique()

        for strategy_name in all_strategy_names_in_log:
            if strategy_name == "Unknown" or pd.isna(strategy_name):
                continue

            grid_config_for_strategy = self.param_grid.get(strategy_name)
            if not grid_config_for_strategy:
                logger.debug(
                    f"No grid config for {strategy_name}. Skipping grid search for this strategy."
                )
                continue

            optimizable_params_in_grid = {
                k: v
                for k, v in grid_config_for_strategy.items()
                if isinstance(v, list) and len(v) > 0
            }
            if not optimizable_params_in_grid:
                logger.debug(
                    f"No optimizable params in grid for {strategy_name}. Skipping."
                )
                continue

            keys, values_for_product = zip(*optimizable_params_in_grid.items())

            metric_to_optimize = self.optuna_config.get(
                "metric_name", DEFAULT_METRIC_TR
            )
            direction_to_optimize = self.optuna_config.get(
                "direction", DEFAULT_DIRECTION_TR
            )

            best_score_for_strategy = (
                -float("inf") if direction_to_optimize == "maximize" else float("inf")
            )
            compare_op_grid = (
                operator.gt if direction_to_optimize == "maximize" else operator.lt
            )

            best_comb_params_for_strategy = None
            best_kpis_for_best_params_for_strategy = None

            current_strategy_trades_df = df_trades[
                df_trades["strategy"] == strategy_name
            ].copy()
            if current_strategy_trades_df.empty:
                logger.debug(
                    f"No trades found for {strategy_name} in log. Skipping grid search."
                )
                continue

            logger.info(
                f"Running Grid Search for {strategy_name} ({len(current_strategy_trades_df)} trades)..."
            )
            param_combinations = list(product(*values_for_product))
            logger.info(
                f"Total parameter combinations to test for {strategy_name}: {len(param_combinations)}"
            )

            default_params_for_strategy = self.strategy_defaults.get(
                strategy_name, {}
            ).copy()

            for combo_idx, combo_values in enumerate(param_combinations):
                current_optimizing_params_combo = dict(zip(keys, combo_values))
                full_params_for_sim = default_params_for_strategy.copy()
                full_params_for_sim.update(current_optimizing_params_combo)

                simulated_kpis = self._calculate_kpis_simulated(
                    current_strategy_trades_df, full_params_for_sim
                )
                num_sim_trades = simulated_kpis.get("trades", 0)

                if num_sim_trades < self.min_trades_for_optimization:
                    # logger.debug(f"  Params ({strategy_name}) #{combo_idx+1}: {current_optimizing_params_combo} -> SKIPPED (Trades: {num_sim_trades} < {self.min_trades_for_optimization})")
                    continue

                current_score = simulated_kpis.get(
                    metric_to_optimize,
                    0 if direction_to_optimize == "maximize" else float("inf"),
                )
                if (
                    math.isinf(current_score)
                    and current_score > 0
                    and direction_to_optimize == "maximize"
                ):
                    current_score = 99999.0
                elif (
                    math.isinf(current_score)
                    and current_score < 0
                    and direction_to_optimize == "minimize"
                ):
                    current_score = -99999.0
                elif math.isnan(current_score):
                    current_score = (
                        -float("inf")
                        if direction_to_optimize == "maximize"
                        else float("inf")
                    )

                # logger.debug(f"  Params ({strategy_name}) #{combo_idx+1}: {current_optimizing_params_combo} -> {metric_to_optimize}: {current_score:.2f}, PnL: {simulated_kpis.get('total_pnl', 0):.2f}, Trades: {num_sim_trades}")

                update_best = False
                if best_kpis_for_best_params_for_strategy is None:  # First valid KPIs
                    update_best = True
                    # logger.debug(f"    First valid combo. Setting initial best score for {metric_to_optimize}.")
                elif compare_op_grid(current_score, best_score_for_strategy):
                    update_best = True
                    # logger.debug(f"    New best score ({metric_to_optimize}): {current_score:.2f} {'>' if compare_op_grid == operator.gt else '<'} {best_score_for_strategy:.2f}")
                elif math.isclose(
                    current_score, best_score_for_strategy
                ):  # If the metric is the same, compare by PnL
                    current_pnl = simulated_kpis.get("total_pnl", -float("inf"))
                    best_pnl_so_far = best_kpis_for_best_params_for_strategy.get(
                        "total_pnl", -float("inf")
                    )
                    # For PnL, it's always maximization (or loss minimization if PnL is negative)
                    if current_pnl > best_pnl_so_far:
                        update_best = True
                        # logger.debug(f"    Same {metric_to_optimize} score ({current_score:.2f}), but better PnL: {current_pnl:.2f} > {best_pnl_so_far:.2f}")

                if update_best:
                    best_score_for_strategy = current_score
                    best_comb_params_for_strategy = current_optimizing_params_combo
                    best_kpis_for_best_params_for_strategy = simulated_kpis

            if best_comb_params_for_strategy:
                best_params_found[strategy_name] = best_comb_params_for_strategy
                logger.info(
                    f"--> Best params for {strategy_name} (Grid Search): {best_comb_params_for_strategy}"
                )
                self._log_performance_report(
                    {
                        f"{strategy_name} (Optimized Grid)": best_kpis_for_best_params_for_strategy
                    },
                    title=f"--- Best Simulated Performance for {strategy_name} (Grid Search) ---",
                )
            else:
                logger.warning(
                    f"No suitable parameters found for {strategy_name} via Grid Search that meet min_trades criteria."
                )
        return best_params_found

    def _save_optimized_params(self, params_to_save: Dict[str, Any]):
        """Saves optimized parameters to JSON, merging with existing ones."""
        current_optimized_in_file = (
            self._load_optimized_params()
        )  # Loading what is already in the file

        # Update existing parameters with new ones if they exist for the same strategies,
        # or add new strategies.
        updated_params_for_file = current_optimized_in_file.copy()
        updated_params_for_file.update(params_to_save)

        try:
            self.optimized_params_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.optimized_params_file, "w") as f:
                save_data = {
                    "timestamp": time.time(),
                    "optimized_params": updated_params_for_file,
                }
                json.dump(save_data, f, indent=2)
            logger.info(f"Optimized parameters saved to {self.optimized_params_file}")
        except IOError as e:
            logger.error(
                f"Error saving optimized params file {self.optimized_params_file}: {e}"
            )
        except Exception as e:
            logger.error(
                f"Unexpected error saving optimized params: {e}", exc_info=True
            )

    def _load_optimized_params(self) -> Dict[str, Any]:
        """Loads current optimized parameters from a file."""
        if self.optimized_params_file.exists():
            try:
                with open(self.optimized_params_file, "r") as f:
                    data = json.load(f)
                return data.get("optimized_params", {})
            except (json.JSONDecodeError, IOError) as e:
                logger.error(
                    f"Error loading optimized params file {self.optimized_params_file}: {e}"
                )
        return {}

    def run_training_cycle(self, mode: str = "optimize"):
        """Starts the analysis and optimization/training cycle depending on the mode."""
        logger.info(f"--- Starting Training Cycle (Mode: {mode.upper()}) ---")

        if mode == "optimize":
            logger.info("Running in OPTIMIZE mode...")
            trade_df = self._load_trade_logs()
            if trade_df is not None and not trade_df.empty:
                actual_kpis_by_strategy = self._calculate_kpis(trade_df)
                self._log_performance_report(
                    actual_kpis_by_strategy,
                    title="--- Actual Performance Report (Last {} Days) ---".format(
                        self.lookback_days
                    ),
                )
            else:
                logger.warning("No sufficient trade data found for actual KPI report.")

            new_optimized_params = {}
            if self.optimization_method == "bayesian":
                logger.info(
                    "Starting parameters optimization (Bayesian Optimization)..."
                )
                new_optimized_params = self.run_bayesian_optimization()
            elif self.optimization_method == "grid":
                logger.info("Starting parameters optimization (Grid Search on logs)...")
                if trade_df is not None and not trade_df.empty:
                    new_optimized_params = self.run_grid_search(trade_df)
                else:
                    logger.error(
                        "Cannot run Grid Search without trade logs for simulation."
                    )
            else:
                logger.warning(
                    f"Unknown optimization method '{self.optimization_method}'. Skipping optimization."
                )

            if new_optimized_params:  # If optimization yielded any results
                current_params_in_file = self._load_optimized_params()
                params_to_save_final = (
                    current_params_in_file.copy()
                )  # Starting with current ones from file

                config_changed_overall = False
                changed_strategies_list = []

                for strategy_name, best_params_from_opt in new_optimized_params.items():
                    if best_params_from_opt != current_params_in_file.get(
                        strategy_name, {}
                    ):
                        logger.info(
                            f"Parameters for '{strategy_name}' changed by optimization: {best_params_from_opt}"
                        )
                        params_to_save_final[strategy_name] = (
                            best_params_from_opt  # Updating or adding
                        )
                        config_changed_overall = True
                        changed_strategies_list.append(strategy_name)
                    else:
                        logger.info(
                            f"Parameters for '{strategy_name}' remain unchanged after optimization."
                        )

                if config_changed_overall:
                    logger.info(
                        f"Saving updated parameters to file for: {changed_strategies_list}"
                    )
                    self._save_optimized_params(
                        params_to_save_final
                    )  # Save the MERGED result
                    self.optimized_params = (
                        params_to_save_final.copy()
                    )  # Updating in-memory cache
                else:
                    logger.info(
                        "No changes detected in optimized parameters after comparison with current file content."
                    )
            else:
                logger.info("Optimization step did not yield new parameters.")

        elif mode == "train_ml":
            logger.info("Running in TRAIN_ML mode...")
            self.run_ml_agent_training()
        else:
            logger.error(
                f"Invalid trainer mode specified: '{mode}'. Use 'optimize' or 'train_ml'."
            )

        logger.info(f"--- Training Cycle Finished (Mode: {mode.upper()}) ---")

    def execute_single_backtest(
        self,
        strategy_name: str,
        symbol: str,
        start_dt: datetime,
        end_dt: datetime,
        params: Dict[str, Any],
        market_type: str = "futures_usdtm",
    ) -> Optional[Dict[str, Any]]:
        """
        Executes a single backtest run for a given strategy, symbol, and parameters.
        This is a simplified version of the logic in _optuna_objective_global.
        """
        log_prefix = f"[ExecuteSingleBacktest:{strategy_name}:{symbol}]"
        logger.info(
            f"{log_prefix} Starting single backtest run for period [{start_dt.date()} to {end_dt.date()}]"
        )

        # 1. Load Exchange Info
        exchange_info_all_symbols = self._get_exchange_info()
        if not exchange_info_all_symbols:
            logger.error(f"{log_prefix} Failed to load exchange info. Cannot proceed.")
            return None
        symbol_specific_exchange_info = exchange_info_all_symbols.get(symbol, {})
        if not symbol_specific_exchange_info:
            logger.error(
                f"{log_prefix} Exchange info not found for symbol {symbol}. Cannot proceed."
            )
            return None

        # 2. Determine required data types and load data
        s_defaults = self.strategy_defaults.get(strategy_name, {})
        base_config_params = s_defaults.copy()  # Base parameters from strategy defaults
        base_config_params.update(params)  # Override with provided params

        required_data_types: Set[str] = set()
        temp_strat_instance = (
            get_strategy_instance(strategy_name)
            if get_strategy_instance is not None
            else None
        )
        if temp_strat_instance and hasattr(temp_strat_instance, "required_data_types"):
            required_data_types.update(temp_strat_instance.required_data_types)
        else:  # Fallback if strategy doesn't define it explicitly
            tf = base_config_params.get(
                "candle_timeframe", base_config_params.get("entry_timeframe", "1m")
            )
            required_data_types.add(f"kline_{tf}")
            if strategy_name in [
                "FakeBreakoutStrategy",
                "AggTradeReversalStrategy",
                "VolumeBreakoutStrategy",
                "ConsolidationImpulseStrategy",
            ]:
                required_data_types.add("aggTrade")
        required_data_types.update(
            {"kline_1d", "kline_1h", "kline_4h"}
        )  # Common context TFs

        historical_data = self._load_historical_data(
            symbol, start_dt, end_dt, required_data_types, market_type=market_type
        )

        main_tf_key = f"kline_{base_config_params.get('candle_timeframe', base_config_params.get('entry_timeframe', '1m'))}"
        if not historical_data or not historical_data.get(main_tf_key):
            logger.error(
                f"{log_prefix} Failed to load kline data for main timeframe {main_tf_key}. Cannot run backtest."
            )
            return None

        # 3. Prepare backtester arguments
        cfg_default_risk_pct = (
            getattr(config, "DEFAULT_RISK_PER_TRADE_PERCENT", 0.5) / 100.0
        )
        cfg_daily_loss_pct = (
            getattr(config, "DEFAULT_DAILY_MAX_LOSS_PERCENT", 5.0) / 100.0
        )
        cfg_max_consecutive_losses = getattr(
            config, "DEFAULT_MAX_CONSECUTIVE_LOSSES", 10
        )
        risk_per_trade_from_params = base_config_params.get(
            "risk_pct_per_trade", cfg_default_risk_pct
        )

        risk_params_for_backtester = {
            "risk_pct_per_trade": risk_per_trade_from_params,
            "daily_max_loss_pct": cfg_daily_loss_pct,
            "max_consecutive_losses": cfg_max_consecutive_losses,
        }
        backtest_log_cfg_for_run = {
            "save_trades": getattr(config, "BACKTEST_SAVE_TRADES", False),
            "log_path_template": getattr(
                config, "BACKTEST_TRADES_LOG_PATH_TEMPLATE", None
            ),
        }

        # 4. Run the backtest
        final_kpis: Optional[Dict[str, Any]] = None
        try:
            backtester = DepthSightBacktester(
                strategy_name=strategy_name,
                symbol=symbol,
                params=base_config_params,  # Combined defaults and provided params
                historical_data=historical_data,
                initial_balance=self.backtest_initial_balance,
                min_trades_required=0,  # Not strictly needed for a single run unless desired
                actual_trading_start_dt=start_dt,  # Actual start for this backtest
                risk_params=risk_params_for_backtester,
                execution_config=self.backtest_execution_config,
                exchange_info=symbol_specific_exchange_info,
                strategy_defaults=self.strategy_defaults,
                # ML related params can be set to False/None for non-ML strategies
                ml_training_mode=False,
                ml_agent_instance=None,
                ml_training_config={},
                ml_sim_log_path=None,
                backtest_log_config=backtest_log_cfg_for_run,
                log_ml_confirmation_data=getattr(
                    config, "BACKTEST_LOG_FOR_ML_CONFIRMATION_MODEL", False
                ),
                ml_confirmation_log_path=getattr(
                    config, "BACKTEST_ML_CONFIRMATION_DATA_PATH", None
                ),
                y_true_min_move_pct=getattr(
                    config, "ML_CONFIRMATION_Y_TRUE_MIN_MOVE_FAVOR_PCT", 0.15
                ),
                y_true_max_drawdown_pct=getattr(
                    config, "ML_CONFIRMATION_Y_TRUE_MAX_DRAWDOWN_PCT", 0.10
                ),
                enable_ml_confirmation_backtest=getattr(
                    config, "ML_CONFIRMATION_ENABLED", False
                ),
                ml_confirmation_model_path_override=getattr(
                    config, "ML_CONFIRMATION_MODEL_PATH", None
                ),
            )
            final_kpis = backtester.run()
            if final_kpis is None:
                logger.warning(f"{log_prefix} Backtest run returned None.")
        except Exception as e_backtest_run:
            logger.error(
                f"{log_prefix} Unhandled error during DepthSightBacktester.run(): {e_backtest_run}",
                exc_info=True,
            )
            return None

        if final_kpis:
            logger.info(
                f"{log_prefix} Backtest completed. Trades: {final_kpis.get('trades', 0)}, PnL: {final_kpis.get('total_pnl', 0.0):.2f}"
            )
        return final_kpis

    async def run_single_optimization(
        self,
        strategy_name: str,
        symbol: str,
        start_dt: datetime,
        end_dt: datetime,
        optuna_config: Dict[str, Any],
        progress_callback: Optional[Callable] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Executes a single optimization run for a given strategy and symbol.
        """
        if BayesianOptimizer is None:
            logger.error(
                "BayesianOptimizer class not available. Cannot run single optimization."
            )
            return None

        log_prefix = f"[SingleOpt:{strategy_name}:{symbol}]"
        logger.info(
            f"{log_prefix} Starting single optimization run for period [{start_dt.date()} to {end_dt.date()}]"
        )

        exchange_info_all_symbols = self._get_exchange_info()
        if not exchange_info_all_symbols:
            logger.error(f"{log_prefix} Failed to load exchange info. Cannot proceed.")
            return None

        visual_strategy = optuna_config.get("visual_strategy")
        if visual_strategy:
            base_config_params = visual_strategy.copy()
            required_data_types = self.get_data_requirements_for_strategy(
                strategy_name,
                base_config_params,
                symbol,
                getattr(self, "market_type", "futures"),
            )
            search_width_pct = optuna_config.get("search_width_pct", 50.0)
            strategy_search_space = _scan_strategy_params(
                visual_strategy, search_width_pct=search_width_pct
            )
            logger.info(
                f"{log_prefix} Dynamic search space generated with {len(strategy_search_space)} parameters for visual strategy."
            )
        else:
            s_defaults = self.strategy_defaults.get(strategy_name, {})
            base_config_params = s_defaults.copy()
            required_data_types = self.get_data_requirements_for_strategy(
                strategy_name,
                base_config_params,
                symbol,
                getattr(self, "market_type", "futures"),
            )
            strategy_search_space = self.optuna_search_space.get(strategy_name)

        historical_data = await self._load_historical_data(
            symbol, start_dt, end_dt, required_data_types
        )

        main_tf_key = f"kline_{base_config_params.get('candle_timeframe', base_config_params.get('entry_timeframe', '1m'))}"

        main_df = historical_data.get(main_tf_key)
        if not historical_data or main_df is None or main_df.empty:
            logger.error(
                f"{log_prefix} Failed to load kline data for main timeframe {main_tf_key}. Cannot run optimization."
            )
            return None

        if not strategy_search_space:
            logger.warning(
                f"{log_prefix} No search space found for {strategy_name}. Skipping optimization."
            )
            return None

        final_optuna_config = self.optuna_config.copy()
        final_optuna_config.update(optuna_config)

        best_params: Optional[Dict[str, Any]] = None
        try:
            optimizer = BayesianOptimizer(
                objective_func=_optuna_objective_global,
                search_space=strategy_search_space,
                config_override=final_optuna_config,
                params={},
                strategy_name=strategy_name,
                historical_data=historical_data,
                initial_balance=self.backtest_initial_balance,
                base_config=base_config_params,
                symbol=symbol,
                exchange_info_all_symbols=exchange_info_all_symbols,
                min_trades_required=self.min_trades_for_optimization,
                backtester_execution_config=self.backtest_execution_config,
                strategy_defaults_all=self.strategy_defaults,
                optuna_study_config=final_optuna_config,
                actual_start_dt_for_backtest=start_dt,
                log_ml_confirmation_data_flag=getattr(
                    config, "BACKTEST_LOG_FOR_ML_CONFIRMATION_MODEL", False
                ),
                ml_confirmation_data_log_path=getattr(
                    config, "BACKTEST_ML_CONFIRMATION_DATA_PATH", None
                ),
                y_true_min_move_pct_val=getattr(
                    config, "ML_CONFIRMATION_Y_TRUE_MIN_MOVE_FAVOR_PCT", 0.15
                ),
                y_true_max_drawdown_pct_val=getattr(
                    config, "ML_CONFIRMATION_Y_TRUE_MAX_DRAWDOWN_PCT", 0.10
                ),
                enable_ml_confirmation_during_backtest=getattr(
                    config, "ML_CONFIRMATION_ENABLED", False
                ),
                ml_confirmation_model_path_override_val=getattr(
                    config, "ML_CONFIRMATION_MODEL_PATH", None
                ),
            )
            best_params = optimizer.optimize(progress_callback_celery=progress_callback)
            best_value = optimizer.best_value

            if best_params:
                logger.info(
                    f"{log_prefix} Optimization completed. Best params: {best_params}, Best value: {best_value:.4f}"
                )
                self._save_optimized_params({strategy_name: best_params})
                return {
                    "best_params": best_params,
                    "best_value": best_value,
                    "study_dataframe": optimizer.get_study_dataframe().to_dict(
                        orient="records"
                    ),
                }
            else:
                logger.warning(
                    f"{log_prefix} Optimization did not find any best parameters."
                )
                return None
        except Exception as e_opt:
            logger.error(
                f"{log_prefix} Unhandled error during single optimization: {e_opt}",
                exc_info=True,
            )
            return None

    def _calculate_kpis(self, trades_df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """
        Calculates KPIs based on backtest results from a DataFrame of trades grouped by strategies.
        Returns Dict[strategy_name, Dict[kpi_name, value]].
        """
        if trades_df is None or trades_df.empty:
            logger.warning("Cannot calculate KPIs: trades_df is None or empty.")
            return {}

        all_kpis: Dict[str, Dict[str, Any]] = {}

        for strategy_name, group_df in trades_df.groupby("strategy"):
            kpis: Dict[str, Any] = {
                "trades": 0,
                "total_pnl": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
                "total_commission": 0.0,
                "wins": 0,
                "losses": 0,
                "avg_trade_pnl": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "sharpe_ratio": 0.0,
                "max_consecutive_losses": 0,
            }
            if group_df.empty:
                all_kpis[strategy_name] = kpis
                continue

            # Ensure that 'pnl' exists and is numeric
            if "pnl" not in group_df.columns:
                logger.error(
                    f"Missing 'pnl' column for strategy {strategy_name}. Skipping KPI calculation for this strategy."
                )
                all_kpis[strategy_name] = kpis
                continue

            pnl_series = pd.to_numeric(group_df["pnl"], errors="coerce").fillna(0)

            kpis["trades"] = len(group_df)
            kpis["total_pnl"] = pnl_series.sum()

            if "commission" in group_df.columns:
                kpis["total_commission"] = (
                    pd.to_numeric(group_df["commission"], errors="coerce")
                    .fillna(0)
                    .sum()
                )

            wins_series = pnl_series[pnl_series > 0]
            losses_series = pnl_series[pnl_series < 0]

            kpis["wins"] = len(wins_series)
            kpis["losses"] = len(losses_series)

            sum_profit = wins_series.sum()
            sum_loss = abs(losses_series.sum())

            if sum_loss > 1e-9:
                kpis["profit_factor"] = sum_profit / sum_loss
            elif sum_profit > 0:
                kpis["profit_factor"] = 99999.0  # float('inf')
            else:
                kpis["profit_factor"] = 0.0
            if math.isinf(kpis["profit_factor"]):
                kpis["profit_factor"] = 99999.0

            if kpis["trades"] > 0:
                kpis["win_rate"] = (kpis["wins"] / kpis["trades"]) * 100.0
                kpis["avg_trade_pnl"] = kpis["total_pnl"] / kpis["trades"]
                kpis["avg_win"] = sum_profit / kpis["wins"] if kpis["wins"] > 0 else 0.0
                kpis["avg_loss"] = (
                    sum_loss / kpis["losses"] if kpis["losses"] > 0 else 0.0
                )

            if not pnl_series.empty:
                equity_curve = pnl_series.cumsum()
                rolling_max = equity_curve.cummax()
                drawdown_abs = equity_curve - rolling_max
                kpis["max_drawdown"] = (
                    drawdown_abs.min() if not drawdown_abs.empty else 0.0
                )

            max_consecutive_losses_val = 0
            current_consecutive_losses = 0
            for pnl_val in pnl_series:
                if pnl_val < 0:
                    current_consecutive_losses += 1
                else:
                    if current_consecutive_losses > 0:
                        max_consecutive_losses_val = max(
                            max_consecutive_losses_val, current_consecutive_losses
                        )
                    current_consecutive_losses = 0
            kpis["max_consecutive_losses"] = max(
                max_consecutive_losses_val, current_consecutive_losses
            )

            if kpis["trades"] > 1:
                pnl_std = pnl_series.std()
                if pnl_std is not None and pnl_std > 1e-9 and not pd.isna(pnl_std):
                    kpis["sharpe_ratio"] = (kpis["avg_trade_pnl"] / pnl_std) * (
                        kpis["trades"] ** 0.5
                    )
                elif kpis["avg_trade_pnl"] > 0:
                    kpis["sharpe_ratio"] = float("inf")
                else:
                    kpis["sharpe_ratio"] = 0.0
            else:
                kpis["sharpe_ratio"] = 0.0
            if math.isinf(kpis["sharpe_ratio"]):
                kpis["sharpe_ratio"] = 99999.0

            all_kpis[strategy_name] = kpis

        return all_kpis

    def run_bayesian_optimization(self) -> Dict[str, Dict[str, Any]]:
        if BayesianOptimizer is None:
            logger.error("BayesianOptimizer class not available.")
            return {}
        best_params_aggregated: Dict[str, Dict[str, Any]] = {}

        metric_to_optimize = self.optuna_config.get("metric_name", DEFAULT_METRIC_TR)
        direction_to_optimize = self.optuna_config.get(
            "direction", DEFAULT_DIRECTION_TR
        )

        best_values_overall: Dict[str, float] = defaultdict(
            lambda: (
                -float("inf") if direction_to_optimize == "maximize" else float("inf")
            )
        )
        compare_op = operator.gt if direction_to_optimize == "maximize" else operator.lt

        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=self.lookback_days)
        overlap_days = getattr(config, "OPTIMIZATION_DATA_OVERLAP_DAYS", 0)
        logger.info(
            f"Optimization Backtest Period: [{start_dt.date()}, {end_dt.date()}), Data Load Overlap for Klines: {overlap_days} days"
        )
        full_exchange_info = self._get_exchange_info()
        if not full_exchange_info:
            logger.error("Failed to load Exchange Info for Bayesian Opt.")
            return {}
        target_symbols = getattr(config, "TRAINER_TARGET_SYMBOLS", [])
        if not target_symbols:
            logger.error("TRAINER_TARGET_SYMBOLS is empty for Bayesian Opt.")
            return {}

        strategies_to_optimize = [
            s_name
            for s_name in self.optuna_search_space.keys()
            if self.strategy_defaults.get(s_name, {}).get("enabled", False)
            and (
                OnlineAgentStrategy is None or s_name != OnlineAgentStrategy.NAME
            )  # Excluding ML strategy
        ]
        if not strategies_to_optimize:
            logger.warning(
                "No enabled non-ML strategies found for Bayesian optimization."
            )
            return {}

        logger.info(
            f"--- Starting PARALLEL Bayesian Optimization for {len(strategies_to_optimize)} strategies on {len(target_symbols)} symbols ---"
        )
        num_workers_config = self.optuna_config.get("n_jobs", 1)
        num_workers = (
            multiprocessing.cpu_count()
            if num_workers_config == -1
            else max(1, num_workers_config)
        )
        logger.info(
            f"Using {num_workers} worker processes for Optuna parallel execution."
        )

        fixed_args_opt = {
            "strategies_to_optimize": strategies_to_optimize,
            "optuna_search_space_all": self.optuna_search_space,
            "strategy_defaults_all": self.strategy_defaults,
            "start_dt": start_dt,
            "end_dt": end_dt,
            "overlap_days": overlap_days,
            "exchange_info_all": full_exchange_info,  # Pass as exchange_info_all
            "optuna_config": self.optuna_config.copy(),  # Copy of Optuna config for each process
            "initial_balance": self.backtest_initial_balance,
            "backtester_execution_config": self.backtest_execution_config,  # Pass as backtester_execution_config
            "min_trades_required": self.min_trades_for_optimization,
            "use_local_data": self.use_local_data,
            "local_data_path": self.local_data_path,
            "log_ml_confirmation_data_flag": getattr(
                config, "BACKTEST_LOG_FOR_ML_CONFIRMATION_MODEL", False
            ),
            "ml_confirmation_data_log_path": getattr(
                config, "BACKTEST_ML_CONFIRMATION_DATA_PATH", None
            ),
            "y_true_min_move_pct_val": getattr(
                config, "ML_CONFIRMATION_Y_TRUE_MIN_MOVE_FAVOR_PCT", 0.15
            ),
            "y_true_max_drawdown_pct_val": getattr(
                config, "ML_CONFIRMATION_Y_TRUE_MAX_DRAWDOWN_PCT", 0.10
            ),
            "enable_ml_confirmation_during_backtest": getattr(
                config, "ML_CONFIRMATION_ENABLED", False
            ),
            "ml_confirmation_model_path_override_val": getattr(
                config, "ML_CONFIRMATION_MODEL_PATH", None
            ),
        }
        map_args = [(symbol, fixed_args_opt) for symbol in target_symbols]

        results_by_symbol: Dict[
            str, Dict[str, Tuple[Optional[Dict[str, Any]], Optional[float]]]
        ] = {}
        if (
            num_workers > 1 and len(map_args) > 0
        ):  # Use the pool only if there is work and workers
            try:
                with self.mp_context.Pool(processes=num_workers) as pool:
                    for symbol, symbol_results in pool.imap_unordered(
                        _run_optimization_for_symbol_process, map_args
                    ):
                        logger.info(
                            f"Received optimization results for symbol: {symbol}"
                        )
                        if symbol_results:
                            results_by_symbol[symbol] = symbol_results
            except KeyboardInterrupt:
                logger.warning("Parallel optimization interrupted by user!")
            except Exception as e_pool:
                logger.critical(
                    f"Pool execution error during Bayesian optimization: {e_pool}",
                    exc_info=True,
                )
        elif len(map_args) > 0:  # Sequential execution if n_jobs=1
            logger.info("Running Bayesian optimization sequentially (n_jobs=1).")
            for arg_tuple in map_args:
                symbol, symbol_results = _run_optimization_for_symbol_process(arg_tuple)
                logger.info(f"Received optimization results for symbol: {symbol}")
                if symbol_results:
                    results_by_symbol[symbol] = symbol_results

        logger.info("--- Aggregating Bayesian Optimization Results ---")
        for symbol, symbol_results_dict in results_by_symbol.items():
            # logger.debug(f"Aggregating for {symbol}: {symbol_results_dict}")
            for strategy_name, (best_params, best_value) in symbol_results_dict.items():
                if best_params and best_value is not None:
                    if compare_op(best_value, best_values_overall[strategy_name]):
                        best_values_overall[strategy_name] = best_value
                        best_params_aggregated[strategy_name] = best_params
                        logger.info(
                            f"  New best for {strategy_name} (from {symbol}): Value({metric_to_optimize})={best_value:.4f}, Params={best_params}"
                        )
                else:
                    logger.warning(
                        f"  No valid best_params/best_value for {strategy_name} on {symbol}."
                    )

        if not best_params_aggregated:
            logger.warning(
                "Aggregation finished, but no best parameters found across all symbols for any strategy."
            )
        else:
            logger.info(
                f"Final aggregated best parameters (Bayesian Opt): {best_params_aggregated}"
            )
        logger.info("--- Parallel Bayesian Optimization Finished ---")
        return best_params_aggregated

    def run_ml_agent_training(self):
        """Starts the offline training cycle for OnlineAgentStrategy in parallel by symbols."""
        if OnlineAgentStrategy is None or get_strategy_instance is None:
            logger.error(
                "OnlineAgentStrategy or get_strategy_instance not available. Skipping ML training."
            )
            return

        strategy_name = OnlineAgentStrategy.NAME
        strategy_config = self.strategy_defaults.get(strategy_name, {})
        is_enabled = strategy_config.get("enabled", False)

        if not is_enabled:
            logger.info(
                f"{strategy_name} is disabled in STRATEGY_DEFAULTS. Skipping ML training."
            )
            return

        logger.info(
            f"--- Starting PARALLEL Chunked Offline ML Agent Training Cycle for {strategy_name} ---"
        )
        end_dt_global = datetime.now(timezone.utc)
        start_dt_global = end_dt_global - timedelta(days=self.lookback_days)

        chunk_weeks = getattr(config, "ML_TRAINING_CHUNK_WEEKS", 2)
        overlap_days_ml = getattr(
            config, "ML_TRAINING_OVERLAP_DAYS", 7
        )  # Separate overlap for ML
        chunk_duration = timedelta(weeks=chunk_weeks)
        overlap_duration_ml = timedelta(days=overlap_days_ml)

        logger.info(
            f"Global period: {start_dt_global.date()} to {end_dt_global.date()}, Chunk: {chunk_weeks}w, KLine Overlap: {overlap_days_ml}d"
        )

        target_symbols = getattr(config, "TRAINER_TARGET_SYMBOLS", [])
        if not target_symbols:
            logger.error("TRAINER_TARGET_SYMBOLS is empty. Skipping ML training.")
            return
        logger.info(f"Target symbols for ML training: {target_symbols}")

        # "Global" agent instance for loading/saving the main model
        # and to get agent_req_types
        global_ml_agent = get_strategy_instance(strategy_name)
        if not global_ml_agent:
            logger.error(
                f"Could not create global instance of {strategy_name}. Skipping ML training."
            )
            return

        # Load the main model if it exists
        # The path to the model for saving/loading is taken from trainer_instance
        if self.ml_trained_model_path.exists():
            logger.info(
                f"Loading existing global ML model from: {self.ml_trained_model_path}"
            )
            global_ml_agent.load_pipeline_model(self.ml_trained_model_path)
        else:
            logger.info(
                f"No existing global ML model found at {self.ml_trained_model_path}. Starting with a fresh model."
            )
            global_ml_agent.reset_pipeline()

        try:
            agent_req_types = global_ml_agent.required_data_types
        except Exception as e:  # Fallback if required_data_types is not defined
            s_defaults = self.strategy_defaults.get(strategy_name, {})
            tf = s_defaults.get("candle_timeframe", "1m")
            agent_req_types = {
                f"kline_{tf}",
                "aggTrade",
                "kline_1d",
                "kline_1h",
                "kline_4h",
            }
            logger.warning(
                f"Could not get required_data_types from {strategy_name} instance, using fallback: {agent_req_types}. Error: {e}"
            )

        full_exchange_info = self._get_exchange_info()
        if not full_exchange_info:
            logger.error("Failed to load Exchange Info for ML Training. Skipping.")
            return

        ml_training_cfg_params = {
            "ML_TRAINING_LABEL_LOOKAHEAD_BARS": getattr(
                config, "ML_TRAINING_LABEL_LOOKAHEAD_BARS", 15
            ),
            "ML_TRAINING_SIMULATE_TRADES": getattr(
                config, "ML_TRAINING_SIMULATE_TRADES", True
            ),
        }
        ml_sim_log_file_path = getattr(config, "ML_SIMULATED_TRADES_LOG_FILE", None)
        ml_sim_log_path_str = (
            str(ml_sim_log_file_path) if ml_sim_log_file_path else None
        )

        risk_params_for_ml = {
            "risk_pct_per_trade": getattr(config, "DEFAULT_RISK_PER_TRADE_PERCENT", 0.5)
            / 100.0,
            "daily_max_loss_pct": getattr(config, "DEFAULT_DAILY_MAX_LOSS_PERCENT", 5.0)
            / 100.0,
            "max_consecutive_losses": getattr(
                config, "DEFAULT_MAX_CONSECUTIVE_LOSSES", 10
            ),
        }

        num_workers_config = self.optuna_config.get(
            "n_jobs", 1
        )  # Use n_jobs from Optuna for ML as well
        num_workers = (
            multiprocessing.cpu_count()
            if num_workers_config == -1
            else max(1, num_workers_config)
        )
        logger.info(f"Using {num_workers} worker processes for ML data collection...")

        fixed_args_ml_dict = {
            "strategy_name": strategy_name,
            "start_dt_global": start_dt_global,
            "end_dt_global": end_dt_global,
            "chunk_duration": chunk_duration,
            "overlap_duration": overlap_duration_ml,  # Passing overlap_duration_ml
            "exchange_info_all": full_exchange_info,
            "initial_balance": self.backtest_initial_balance,
            "backtest_exec_config": self.backtest_execution_config,  # Passing backtest_exec_config
            "strategy_defaults_all": self.strategy_defaults,
            "ml_training_cfg": ml_training_cfg_params,
            "ml_sim_log_path": ml_sim_log_path_str,
            "agent_req_types": agent_req_types,
            "risk_params": risk_params_for_ml,
            "use_local_data": self.use_local_data,
            "local_data_path": self.local_data_path,
        }
        map_args = [(symbol, fixed_args_ml_dict.copy()) for symbol in target_symbols]

        all_training_data_collected: List[Dict[str, Any]] = []
        all_simulated_kpis_by_symbol: Dict[str, Dict[str, Any]] = {}

        if num_workers > 1 and len(map_args) > 0:
            try:
                with self.mp_context.Pool(processes=num_workers) as pool:
                    for (
                        symbol,
                        collected_data_chunk,
                        sim_kpis_chunk,
                    ) in pool.imap_unordered(
                        _run_ml_backtest_for_symbol_process_chunked, map_args
                    ):
                        logger.info(
                            f"Received results for ML data collection on symbol: {symbol}. Examples: {len(collected_data_chunk)}"
                        )
                        if collected_data_chunk:
                            all_training_data_collected.extend(collected_data_chunk)
                        if sim_kpis_chunk:
                            all_simulated_kpis_by_symbol[symbol] = sim_kpis_chunk
            except KeyboardInterrupt:
                logger.warning("Parallel ML data collection interrupted by user!")
            except Exception as e_pool:
                logger.critical(
                    f"Pool execution error during ML data collection: {e_pool}",
                    exc_info=True,
                )
        elif len(map_args) > 0:  # Sequential execution
            logger.info("Running ML data collection sequentially (n_jobs=1).")
            for arg_tuple_ml in map_args:
                symbol, collected_data_chunk, sim_kpis_chunk = (
                    _run_ml_backtest_for_symbol_process_chunked(arg_tuple_ml)
                )
                logger.info(
                    f"Received results for ML data collection on symbol: {symbol}. Examples: {len(collected_data_chunk)}"
                )
                if collected_data_chunk:
                    all_training_data_collected.extend(collected_data_chunk)
                if sim_kpis_chunk:
                    all_simulated_kpis_by_symbol[symbol] = sim_kpis_chunk

        logger.info(
            f"--- Starting FINAL Sequential Training on Collected Data ({len(all_training_data_collected)} examples) ---"
        )
        if global_ml_agent and all_training_data_collected:
            random.shuffle(all_training_data_collected)
            train_start_time = time.time()
            # Using the "global" agent instance for training on all data
            for i, example in enumerate(all_training_data_collected):
                try:
                    # Ensure that model_pipeline exists
                    if (
                        hasattr(global_ml_agent, "model_pipeline")
                        and global_ml_agent.model_pipeline is not None
                    ):
                        global_ml_agent.model_pipeline.learn_one(
                            features=example["raw_features"], y_true=example["y_true"]
                        )
                    else:
                        logger.error(
                            f"global_ml_agent.model_pipeline is None at example {i}. Skipping learn_one."
                        )
                        break  # Aborting training if the pipeline is missing
                except Exception as e_learn:
                    logger.error(
                        f"Error during final learn_one at example {i}: {e_learn}",
                        exc_info=True,
                    )

                if (i + 1) % 10000 == 0:
                    logger.info(
                        f"Processed {i + 1}/{len(all_training_data_collected)} examples for final training..."
                    )
                if (i + 1) % 50000 == 0:
                    logger.info(f"Saving intermediate ML model (step {i + 1})...")
                    global_ml_agent.save_pipeline_model(
                        self.ml_trained_model_path
                    )  # Saving to the main file

            train_duration = time.time() - train_start_time
            logger.info(
                f"Final sequential training finished in {train_duration:.2f} seconds."
            )
            logger.info(
                f"Saving final trained ML model pipeline to {self.ml_trained_model_path}..."
            )
            global_ml_agent.save_pipeline_model(
                self.ml_trained_model_path
            )  # Saving to the main file

        elif not all_training_data_collected:
            logger.warning(
                "No training data collected. Final ML model training skipped."
            )
        else:  # global_ml_agent is None (unlikely after the checks above, but for completeness)
            logger.error(
                "Global ML Agent instance not available for final training. Skipping."
            )

        if all_simulated_kpis_by_symbol:
            try:
                self.ml_training_report_file.parent.mkdir(parents=True, exist_ok=True)
                report_content = {
                    "timestamp": time.time(),
                    "training_info": {
                        "start_dt_global": start_dt_global.isoformat(),
                        "end_dt_global": end_dt_global.isoformat(),
                        "chunk_weeks": chunk_weeks,
                        "overlap_days_ml": overlap_days_ml,
                        "num_symbols_processed": len(all_simulated_kpis_by_symbol),
                        "total_examples_collected": len(all_training_data_collected),
                    },
                    "training_results": all_simulated_kpis_by_symbol,
                }
                with open(self.ml_training_report_file, "w") as f:
                    json.dump(report_content, f, indent=2)
                logger.info(
                    f"ML Training simulated performance report saved to {self.ml_training_report_file}"
                )

                aggregated_sim_kpis_ml = self._aggregate_simulated_kpis(
                    all_simulated_kpis_by_symbol
                )
                self._log_performance_report(
                    {"Aggregated ML Sim": aggregated_sim_kpis_ml},
                    title="--- Aggregated Simulated ML Performance (Chunked Training) ---",
                )
            except Exception as e_report:
                logger.error(
                    f"Failed to save/process ML training report: {e_report}",
                    exc_info=True,
                )
        else:
            logger.info("No simulated KPIs to report for ML training.")
        logger.info("--- Parallel Chunked Offline ML Agent Training Cycle Finished ---")

    def _aggregate_simulated_kpis(
        self, kpis_by_symbol: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Aggregates simulation KPIs across different symbols."""
        agg_kpis = defaultdict(float)  # Initializing float for summation
        total_trades_overall = 0
        total_wins_overall = 0
        total_losses_overall = 0

        # For max_drawdown and max_consecutive_losses, we take the worst (maximum) value
        # Max drawdown is the minimum value (the largest drawdown), so we look for min.
        # Max consecutive losses - maximum value.
        worst_max_drawdown = 0.0  # Drawdown - negative number or 0
        highest_max_consecutive_losses = 0
        total_ml_steps = 0

        for symbol, kpis_for_symbol in kpis_by_symbol.items():
            trades_on_symbol = kpis_for_symbol.get("trades", 0)
            if trades_on_symbol > 0:
                total_trades_overall += trades_on_symbol
                agg_kpis["total_pnl"] += kpis_for_symbol.get("total_pnl", 0.0)
                agg_kpis["total_commission"] += kpis_for_symbol.get(
                    "total_commission", 0.0
                )
                total_wins_overall += kpis_for_symbol.get("wins", 0)
                total_losses_overall += kpis_for_symbol.get("losses", 0)

                worst_max_drawdown = min(
                    worst_max_drawdown, kpis_for_symbol.get("max_drawdown", 0.0)
                )
                highest_max_consecutive_losses = max(
                    highest_max_consecutive_losses,
                    kpis_for_symbol.get("max_consecutive_losses", 0),
                )
                total_ml_steps += kpis_for_symbol.get("ml_steps_processed", 0)

        agg_kpis["trades"] = total_trades_overall
        agg_kpis["wins"] = total_wins_overall
        agg_kpis["losses"] = total_losses_overall
        agg_kpis["max_drawdown"] = worst_max_drawdown
        agg_kpis["max_consecutive_losses"] = highest_max_consecutive_losses
        agg_kpis["ml_steps_processed"] = total_ml_steps

        if total_trades_overall > 0:
            agg_kpis["win_rate"] = (total_wins_overall / total_trades_overall) * 100.0
            agg_kpis["avg_trade_pnl"] = agg_kpis["total_pnl"] / total_trades_overall
            agg_kpis["avg_win"] = (
                (agg_kpis["total_pnl"] + abs(agg_kpis["total_commission"]))
                / total_wins_overall
                if total_wins_overall > 0
                else 0.0
            )  # Approximately
            agg_kpis["avg_loss"] = (
                (abs(agg_kpis["total_pnl"]) + abs(agg_kpis["total_commission"]))
                / total_losses_overall
                if total_losses_overall > 0
                else 0.0
            )  # Approximately
        else:
            agg_kpis["win_rate"] = 0.0
            agg_kpis["avg_trade_pnl"] = 0.0
            agg_kpis["avg_win"] = 0.0
            agg_kpis["avg_loss"] = 0.0

        sum_profit_overall = sum(
            s_kpis.get("total_pnl", 0.0)
            for s_kpis in kpis_by_symbol.values()
            if s_kpis.get("total_pnl", 0.0) > 0
        )
        sum_loss_overall = abs(
            sum(
                s_kpis.get("total_pnl", 0.0)
                for s_kpis in kpis_by_symbol.values()
                if s_kpis.get("total_pnl", 0.0) < 0
            )
        )

        if sum_loss_overall > 1e-9:
            agg_kpis["profit_factor"] = sum_profit_overall / sum_loss_overall
        elif sum_profit_overall > 0:
            agg_kpis["profit_factor"] = 99999.0
        else:
            agg_kpis["profit_factor"] = 0.0
        if math.isinf(agg_kpis["profit_factor"]):
            agg_kpis["profit_factor"] = 99999.0

        # Sharpe Ratio for aggregated data is harder to calculate accurately without individual trade PnL.
        # You can leave it as 0 or make a rough estimate if there is data on the PnL of all trades.
        agg_kpis["sharpe_ratio"] = 0.0  # Simplified

        return dict(agg_kpis)


def _run_ml_backtest_for_symbol_process_chunked(
    args_tuple: Tuple[str, Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Starts backtest/data collection for ONE symbol BY CHUNKS.
    """
    try:
        symbol_to_train, fixed_args = args_tuple
        strategy_name = fixed_args["strategy_name"]
        start_dt_global = fixed_args["start_dt_global"]
        end_dt_global = fixed_args["end_dt_global"]
        chunk_duration = fixed_args["chunk_duration"]
        overlap_duration = fixed_args["overlap_duration"]
        exchange_info_all = fixed_args["exchange_info_all"]
        initial_balance = fixed_args["initial_balance"]
        backtest_exec_config = fixed_args["backtest_exec_config"]
        strategy_defaults_all = fixed_args["strategy_defaults_all"]
        ml_training_cfg = fixed_args["ml_training_cfg"]

        agent_req_types = fixed_args["agent_req_types"]  # This is Set[str]
        risk_params = fixed_args["risk_params"]
        use_local_data = fixed_args["use_local_data"]
        local_data_path = fixed_args["local_data_path"]
        requires_agg = "aggTrade" in agent_req_types  # boolean
    except (TypeError, KeyError, IndexError) as e:
        pid = os.getpid()
        fallback_symbol = (
            args_tuple[0]
            if isinstance(args_tuple, tuple) and len(args_tuple) > 0
            else "UNKNOWN_SYMBOL_ML_CHUNK"
        )
        print(
            f"[Process:{pid}:{fallback_symbol}] Error unpacking ML chunked args: {e}",
            file=sys.stderr,
        )
        return fallback_symbol, [], None

    pid = os.getpid()
    _setup_process_logging(pid, symbol_to_train)
    log_prefix = f"[Process:{pid}:{symbol_to_train}:MLChunk]"
    logger.info(
        f"{log_prefix} Starting chunked ML backtest (Use Local: {use_local_data})..."
    )

    all_collected_data_for_symbol: List[Dict[str, Any]] = []
    all_simulated_trades_for_symbol: List[Dict[str, Any]] = []

    if get_strategy_instance is None:
        logger.error(
            f"{log_prefix} get_strategy_instance is None (import failed?). Skipping."
        )
        return symbol_to_train, [], None
    local_ml_agent = get_strategy_instance(strategy_name)
    if not local_ml_agent:
        logger.error(f"{log_prefix} Failed to get agent instance for {strategy_name}.")
        return symbol_to_train, [], None

    agent_s_defaults = strategy_defaults_all.get(strategy_name, {})
    for key, value in agent_s_defaults.items():
        if hasattr(local_ml_agent, key):
            setattr(local_ml_agent, key, value)
    local_ml_agent.reset_pipeline()
    logger.info(
        f"{log_prefix} Initialized local ML agent instance for {strategy_name}."
    )

    main_tf_key = (
        f"kline_{local_ml_agent.candle_timeframe}"
        if hasattr(local_ml_agent, "candle_timeframe")
        else "kline_1m"
    )

    actual_start_dt = start_dt_global
    try:
        first_chunk_start_for_discovery = start_dt_global
        first_chunk_end_for_discovery = min(
            start_dt_global + chunk_duration, end_dt_global
        )
        logger.info(
            f"{log_prefix} Loading first chunk data ({first_chunk_start_for_discovery.date()} to {first_chunk_end_for_discovery.date()}) to find actual start date..."
        )

        initial_data = _load_data_for_process(
            symbol_to_train,
            first_chunk_start_for_discovery,
            first_chunk_end_for_discovery,
            0,
            agent_req_types,  # Passing all agent_req_types
            use_local_data,
            local_data_path,
        )
        kline_df_init = initial_data.get(main_tf_key)
        agg_df_init = initial_data.get("aggTrade") if requires_agg else None
        kline_start = (
            kline_df_init.index.min()
            if kline_df_init is not None and not kline_df_init.empty
            else pd.NaT
        )
        if pd.isna(kline_start):
            logger.error(
                f"{log_prefix} No kline data found for {main_tf_key} in initial chunk. Cannot determine actual start date."
            )
            return symbol_to_train, [], None
        actual_start_dt = kline_start
        if requires_agg:
            agg_start = (
                agg_df_init.index.min()
                if agg_df_init is not None and not agg_df_init.empty
                else pd.NaT
            )
            if pd.isna(agg_start):
                logger.error(
                    f"{log_prefix} Required aggTrade data not found in initial chunk. Cannot determine actual start date."
                )
                return symbol_to_train, [], None
            actual_start_dt = max(kline_start, agg_start)
        logger.info(
            f"{log_prefix} Determined actual start date: {actual_start_dt.date()}"
        )
        del initial_data, kline_df_init, agg_df_init
    except Exception as e_init_load:
        logger.error(
            f"{log_prefix} Exception during initial data load for actual_start_dt: {e_init_load}",
            exc_info=True,
        )
        return symbol_to_train, [], None

    if actual_start_dt >= end_dt_global:
        logger.info(
            f"{log_prefix} Actual start date ({actual_start_dt.date()}) is after or at global end date ({end_dt_global.date()}). No data to process."
        )
        return symbol_to_train, [], None

    chunk_start_dt = actual_start_dt
    chunk_number = 0
    symbol_exchange_info = exchange_info_all.get(symbol_to_train, {})

    while chunk_start_dt < end_dt_global:
        chunk_number += 1
        chunk_end_dt = min(chunk_start_dt + chunk_duration, end_dt_global)
        logger.info(
            f"{log_prefix} Processing Chunk {chunk_number}: TrainPeriod=[{chunk_start_dt.date()} to {chunk_end_dt.date()}], KLineOverlap={overlap_duration.days}d"
        )

        chunk_historical_data: Dict[str, Optional[pd.DataFrame]] = {}
        kline_req_types_in_agent = {
            k for k in agent_req_types if k.startswith("kline_")
        }

        if kline_req_types_in_agent:
            try:
                kline_data_loaded = _load_data_for_process(
                    symbol_to_train,
                    chunk_start_dt,
                    chunk_end_dt,
                    overlap_duration.days,
                    kline_req_types_in_agent,
                    use_local_data,
                    local_data_path,
                )
                chunk_historical_data.update(kline_data_loaded)
            except Exception as e_load_kline:
                logger.error(
                    f"{log_prefix} Error loading kline data for chunk {chunk_number}: {e_load_kline}. Skipping chunk."
                )
                chunk_start_dt = chunk_end_dt
                continue

        if requires_agg:
            try:
                agg_data_loaded = _load_data_for_process(
                    symbol_to_train,
                    chunk_start_dt,
                    chunk_end_dt,
                    0,
                    {"aggTrade"},
                    use_local_data,
                    local_data_path,
                )
                chunk_historical_data.update(agg_data_loaded)
            except Exception as e_load_agg:
                logger.error(
                    f"{log_prefix} Error loading aggTrade data for chunk {chunk_number}: {e_load_agg}. Skipping chunk."
                )
                chunk_start_dt = chunk_end_dt
                continue

        if (
            main_tf_key not in chunk_historical_data
            or chunk_historical_data[main_tf_key] is None
            or chunk_historical_data[main_tf_key].empty
        ):
            logger.warning(
                f"{log_prefix} Skipping chunk {chunk_number}: Missing essential kline data ({main_tf_key}) after load."
            )
            chunk_start_dt = chunk_end_dt
            continue
        if requires_agg and (
            "aggTrade" not in chunk_historical_data
            or chunk_historical_data["aggTrade"] is None
            or chunk_historical_data["aggTrade"].empty
        ):
            logger.warning(
                f"{log_prefix} Skipping chunk {chunk_number}: Missing required AggTrades after load."
            )
            chunk_start_dt = chunk_end_dt
            continue

        logger.info(
            f"{log_prefix} Running DepthSightBacktester for chunk {chunk_number}..."
        )
        try:
            backtester = DepthSightBacktester(
                strategy_name=strategy_name,
                symbol=symbol_to_train,
                params={},
                historical_data=chunk_historical_data,
                initial_balance=initial_balance,
                min_trades_required=0,
                risk_params=risk_params,
                execution_config=backtest_exec_config,
                exchange_info=symbol_exchange_info,
                ml_training_mode=True,
                ml_agent_instance=local_ml_agent,
                strategy_defaults=strategy_defaults_all,
                ml_training_config=ml_training_cfg,
                ml_sim_log_path=None,
                collect_data_mode=True,
                actual_trading_start_dt=chunk_start_dt,
            )
            backtest_results = backtester.run()

            if backtest_results:
                chunk_data = backtest_results.get("training_data", [])
                if chunk_data:
                    all_collected_data_for_symbol.extend(chunk_data)

                if (
                    ml_training_cfg.get("ML_TRAINING_SIMULATE_TRADES", False)
                    and backtester._ml_simulated_trade_log
                ):
                    all_simulated_trades_for_symbol.extend(
                        backtester._ml_simulated_trade_log
                    )

                logger.info(
                    f"{log_prefix} Chunk {chunk_number} OK. Steps this chunk (approx): {backtest_results.get('ml_steps_processed', 0)}. Total Collected: {len(all_collected_data_for_symbol)}"
                )
            else:
                logger.error(
                    f"{log_prefix} ML Backtest run failed for chunk {chunk_number}."
                )

        except Exception as e_backtest:
            logger.error(
                f"{log_prefix} Error during ML Backtest chunk {chunk_number}: {e_backtest}",
                exc_info=True,
            )

        chunk_start_dt = chunk_end_dt
    simulated_kpis_for_symbol: Optional[Dict[str, Any]] = None
    if (
        ml_training_cfg.get("ML_TRAINING_SIMULATE_TRADES", False)
        and all_simulated_trades_for_symbol
    ):
        try:
            # Calling a top-level function, not a static class method
            simulated_kpis_for_symbol = calculate_kpis_from_sim_log_standalone(
                all_simulated_trades_for_symbol
            )
            if (
                simulated_kpis_for_symbol
                and hasattr(local_ml_agent, "model_pipeline")
                and local_ml_agent.model_pipeline
            ):
                simulated_kpis_for_symbol["ml_steps_processed"] = getattr(
                    local_ml_agent.model_pipeline, "steps_processed", 0
                )
        except Exception as e_kpi:
            logger.error(
                f"{log_prefix} Error calculating simulated KPIs: {e_kpi}", exc_info=True
            )

    logger.info(
        f"{log_prefix} Finished chunked ML backtest for {symbol_to_train}. Total collected: {len(all_collected_data_for_symbol)} examples."
    )
    return symbol_to_train, all_collected_data_for_symbol, simulated_kpis_for_symbol


# --- Function for external launch ---
def run_trainer():
    """Main function to run the trainer with mode selection via CLI."""
    parser = argparse.ArgumentParser(description="Bot Module Trainer")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["optimize", "train_ml"],
        default="optimize",  # Default is optimization
        help="Set the trainer mode: 'optimize' for hyperparameter optimization or 'train_ml' for offline ML model training.",
    )
    args = parser.parse_args()

    try:
        trainer = Trainer()
        trainer.run_training_cycle(mode=args.mode)
    except Exception as e:
        logger.critical(
            f"Critical error during training run (Mode: {args.mode}): {e}",
            exc_info=True,
        )


if __name__ == "__main__":
    print("Running Trainer manually...")
    if not logging.getLogger("bot_module").hasHandlers():
        log_formatter = logging.Formatter(
            getattr(
                config,
                "LOG_FORMAT",
                "%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s",
            )
        )
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(log_formatter)
        stream_handler.setLevel(logging.INFO)
        try:
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)
            log_file_main = getattr(
                config, "LOG_FILE_BOT", "logs/bot_module_trainer.log"
            )  # Use a different file for the main trainer log
            file_handler = logging.FileHandler(
                log_file_main, mode="a", encoding="utf-8"
            )
            file_handler.setFormatter(log_formatter)
            file_handler.setLevel(logging.DEBUG)

            # Configure the root logger or the bot_module logger
            base_logger_to_configure = logging.getLogger(
                "bot_module"
            )  # Configuring module logger
            base_logger_to_configure.setLevel(logging.DEBUG)
            if (
                not base_logger_to_configure.hasHandlers()
            ):  # Add handlers only if they don't exist
                base_logger_to_configure.addHandler(stream_handler)
                base_logger_to_configure.addHandler(file_handler)
            logger.info("Standalone trainer logger configured.")
        except Exception as e_log_setup:
            print(f"Error setting up file logging for trainer: {e_log_setup}")
            logging.basicConfig(
                level=logging.INFO, format=getattr(config, "LOG_FORMAT", None)
            )

    run_trainer()
    print("Trainer finished.")
