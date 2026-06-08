# ruff: noqa: E402
# bot_module/genetic_strategy_finder.py

import logging
import random
import copy
import json
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple, Optional
from uuid import uuid4
import os
import multiprocessing
from tqdm import tqdm

from deap import base, creator, tools

from .fast_vector_backtester import FastVectorBacktester


class TqdmLoggingHandler(logging.Handler):
    def __init__(self, level=logging.NOTSET):
        super().__init__(level)

    def emit(self, record):
        try:
            msg = self.format(record)
            # tqdm.write prints the message ABOVE the progress bar
            tqdm.write(msg)
            self.flush()
        except Exception:
            self.handleError(record)


def get_fitness_value(individual):
    """Helper function for DEAP Statistics to avoid pickle issues."""
    # DEAP may pass an empty tuple if fitness has not been calculated yet
    if not individual.fitness.values:
        return 0.0
    return individual.fitness.values[0]


logger = logging.getLogger("bot_module.genetic_finder")
if not logging.getLogger("bot_module").hasHandlers():
    logging.basicConfig(level=logging.INFO)
    logger.warning("Root logger 'bot_module' has no handlers. Basic config applied.")

# <<< CHANGE: New "Gene Pool" reflecting editor components >>>
GENE_POOL = {
    "filters": {
        "trend_filter": {
            "threshold": (10, 100),
            "timeframe": ["1h"],  # Trend filters are better on higher TFs
        },
        "volatility_filter": {
            "operator": ["gt"],
            "value": (0.005, 0.03),
            "timeframe": ["1m", "5m", "15m"],
        },
        "natr_filter": {
            "period": [30],
            "operator": ["gt"],
            "value": (0.2, 5.0),
            "timeframe": ["1m", "5m", "15m"],
        },
        # WEAKENING ADX: Allowing entry at the start of a trend, not at the peak
        "adx_filter": {
            "period": (7, 14),
            "threshold": (15, 25),  # Enter at the very beginning of the trend
            "operator": ["gt"],
            "timeframe": ["15m", "1h"],  # ADX is better on higher TFs
        },
        "time_filter": {
            "start_hour_utc": (0, 23),
            "end_hour_utc": (0, 23),
            "mode": ["include", "exclude"],  # Trade INSIDE or OUTSIDE the range
            # time_filter has no timeframe, it is always 1m
        },
        "rel_vol_filter": {
            "rel_vol_threshold": (1.0, 3.0),
            "lookback_period": (10, 50),
            "timeframe": ["1m", "5m", "15m"],
        },
        "market_activity": {
            "mode": ["percentile", "relative"],
            "natr_threshold": (0.5, 3.0),
            "rel_vol_threshold": (1.0, 3.0),
            "timeframe": ["1m", "5m", "15m"],
        },
        "trading_session": {
            "filter_mode": ["session", "hours"],
            "session": ["london", "new_york", "asia", "sydney"],
            "start_hour_utc": (0, 23),
            "end_hour_utc": (0, 23),
            "mode": ["include", "exclude"],
        },
        "btc_state_filter": {
            "required_state": ["Trending Up", "Trending Down", "Consolidation"],
            "consolidation_threshold": (0.5, 2.5),
        },
        "correlation": {
            "lookback": (20, 100),
            "operator": ["lt", "gt"],
            "value": (-0.9, 0.9),
        },
    },
    "conditions": {
        "rsi_condition": {
            "period": (5, 14),
            "operator": ["gt", "lt"],
            "value": (25, 75),
            "timeframe": ["1m", "5m", "15m", "1h"],  # RSI can be used on any TF
        },
        "ma_cross_condition": {
            "fast_period": (3, 20),
            "slow_period": (21, 50),
            "timeframe": ["1m", "5m", "15m"],  # Crosses are better on lower TFs
        },
        "macd_condition": {
            "fast_period": (6, 26),
            "slow_period": (12, 52),
            "signal_period": (5, 18),
            "condition_type": ["crossover", "value_above", "value_below"],
            "value": (0.0, 0.01),
            "timeframe": ["5m", "15m", "1h"],
        },
        "bb_condition": {
            "period": (14, 20),
            "std_dev": (2.0, 2.5),
            "check_type": ["price_above_upper", "price_below_lower", "width_gt"],
            "width_value": (0.002, 0.02),
            "timeframe": ["1m", "5m", "15m"],
        },
        "stoch_condition": {
            "k_period": (5, 21),
            "d_period": (3, 9),
            "smooth_k": (3, 9),
            "value": (20, 80),
            "operator": ["cross_above", "cross_below", "gt", "lt"],
            "line": ["k", "d"],  # Which line to check
            "timeframe": ["1m", "5m", "15m"],
        },
        "value_comparison": {
            "leftOperand": [
                {"source": "candle", "key": "close"},
                {"source": "indicator", "key": "EMA_20"},
            ],
            "rightOperand": [{"source": "indicator", "key": "EMA_50"}],
            "operator": ["gt", "lt", "cross_above", "cross_below"],
            "timeframe": ["1m", "5m", "15m", "1h"],
        },
        "classic_pattern": {
            "pattern_name": [
                "bullish_engulfing",
                "bearish_engulfing",
                "pin_bar",
                "doji",
            ],
            "timeframe": ["1m", "5m", "15m"],
        },
        "local_level": {
            "lookback_period": (10, 100),
            "proximity_value": (0.1, 1.0),
            "timeframe": ["5m", "15m", "1h"],
        },
        "price_consolidation": {
            "lookback_period": (10, 100),
            "max_range_atr": (0.5, 2.0),
            "timeframe": ["5m", "15m", "1h"],
        },
        "volume_confirmation": {
            "lookback_period": (10, 50),
            "multiplier": (1.5, 3.0),
            "timeframe": ["1m", "5m"],
        },
        "trend_direction": {
            "sma_fast_period": (10, 50),
            "sma_slow_period": (51, 200),
            "rsi_period": (7, 28),
            "rsi_lower_bound": (20, 45),
            "rsi_upper_bound": (55, 80),
            "direction": ["long", "short"],
            "timeframe": ["1h"],  # Trend direction on higher TFs
        },
        "open_interest": {
            "lookback": (3, 20),
            "analyze": ["change_pct", "absolute_value"],
            "operator": ["gt", "lt"],
            "value": (0.1, 5.0),
        },
        "tape_condition": {
            "metric": [
                "delta_volume",
                "delta_count",
                "ratio_volume",
                "ratio_count",
                "accel_volume",
                "accel_count",
                "total_volume",
                "total_count",
            ],
            "window_sec": [5, 10, 30],
            "operator": ["gt", "lt"],
            "threshold": (0.1, 10.0),
            "avg_lookback_sec": [60, 120],
        },
        "volatility_squeeze": {
            "lookback_candles": (10, 50),
            "squeeze_ratio": (0.3, 0.8),
            "timeframe": ["1m", "5m", "15m", "1h"],
        },
        "round_level": {
            "proximity_type": ["pips", "percentage"],
            "proximity_value": (1.0, 10.0),
        },
        "significant_level": {
            "level_type": ["daily_high", "daily_low", "weekly_high", "weekly_low"],
            "proximity_type": ["atr_multiplier", "percentage"],
            "proximity_value": (0.1, 1.0),
        },
        "price_action_analyzer": {
            "lookback_candles": (10, 60),
            "order": (2, 5),
            "min_points": (2, 4),
            "structure_type": ["higher_lows", "lower_highs"],
            "required_structure": ["HH_HL", "LH_LL"],
            "timeframe": ["5m", "15m", "1h"],
        },
    },
    "logic": {
        "AND": {"max_children": 3},
        "OR": {"max_children": 3},
    },
    "initialization": {
        "direction": ["LONG"],
        # Stop Loss (ATR-based)
        "sl_type": ["atr_multiplier"],
        "sl_value_atr": (1.5, 5.0),  # 1.5 - 5.0 ATR
        # Take Profit (Risk-Reward based)
        "tp_type": ["rr_multiplier"],
        "tp_value_rr": (2.0, 8.0),
        # Breakeven configuration
        "breakeven_enabled": [True, False],
        "breakeven_trigger_rr": (0.5, 2.0),  # Move SL to BE when price reaches X * Risk
        "breakeven_buffer_atr": (0.02, 0.15),  # Buffer above entry price in ATR
        "move_sl_to_be_on_first_tp": [True, False],  # Legacy compatibility
        # TIME STOP: Close trade after X candles
        "max_hold_candles": (100, 600),  # Range: 100-600 candles
        # Partial Take Profits
        "max_partial_exits": (1, 3),
        "partial_tp_value_rr": (1.0, 6.0),  # First TP at 1-6 RR
        "partial_size_pct": (20, 60),  # Take 20-60% of position
    },
}
# Collect lists of available types for convenience
AVAILABLE_FILTERS = list(GENE_POOL["filters"].keys())
AVAILABLE_CONDITIONS = list(GENE_POOL["conditions"].keys())
AVAILABLE_LOGIC = list(GENE_POOL["logic"].keys())

# Create Fitness and Individual types ONCE when loading the module.
creator.create("FitnessMax", base.Fitness, weights=(1.0,))
creator.create("Individual", dict, fitness=creator.FitnessMax)


from pathlib import Path

# Constants for data loading
KLINE_FILENAME = "kline_1m.parquet"
KLINE_COLUMN_NAMES = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume",
    "ignore",
]

# Multi-Timeframe Support
AVAILABLE_TFS = ["1m", "5m", "15m", "1h", "4h"]


def build_dynamic_gene_pool(ui_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Builds GENE_POOL dynamically from UI configuration (Genetic Command Center).

    Args:
        ui_config: Configuration from the UI containing:
            - indicators: Dict of indicator configs {id: {active, minPeriod, maxPeriod, timeframes}}
            - filters: Dict of filter configs
            - risk: Risk/execution settings {sl_range, tp_range, trailing, breakeven, partials}
            - fitness: Fitness settings {weights, killSwitches}
            - evolution: Evolution params {populationSize, generations}

    Returns:
        GENE_POOL dict formatted for GeneticStrategyFinder
    """
    logger.info("Building dynamic GENE_POOL from UI configuration")

    # Start with empty structure
    dynamic_pool = {
        "filters": {},
        "conditions": {},
        "logic": {"AND": {"max_children": 3}, "OR": {"max_children": 3}},
        "initialization": {},
    }

    # INDICATORS -> CONDITIONS
    indicators = ui_config.get("indicators", {})

    # Mapping from UI indicator names to GENE_POOL condition types
    indicator_mapping = {
        "rsi": "rsi_condition",
        "macd": "macd_condition",
        "bb": "bb_condition",
        "adx": "adx_filter",  # ADX is typically a filter
        "ema": "ma_cross_condition",
        "stoch": "stoch_condition",
    }

    for ind_id, ind_config in indicators.items():
        if not ind_config.get("active", False):
            continue

        condition_type = indicator_mapping.get(ind_id.lower())
        if not condition_type:
            logger.warning(f"Unknown indicator type: {ind_id}, skipping")
            continue

        # Build condition config from UI settings
        min_period = ind_config.get("minPeriod", 5)
        max_period = ind_config.get("maxPeriod", 50)
        timeframes = ind_config.get("timeframes", ["1m", "5m", "15m"])

        # Condition-specific params
        if condition_type == "rsi_condition":
            dynamic_pool["conditions"]["rsi_condition"] = {
                "period": (min_period, max_period),
                "operator": ["gt", "lt"],
                "value": (25, 75),
                "timeframe": timeframes,
            }
        elif condition_type == "macd_condition":
            dynamic_pool["conditions"]["macd_condition"] = {
                "fast_period": (6, 26),
                "slow_period": (12, 52),
                "signal_period": (5, 18),
                "condition_type": ["crossover", "value_above", "value_below"],
                "value": (0.0, 0.01),
                "timeframe": timeframes,
            }
        elif condition_type == "bb_condition":
            dynamic_pool["conditions"]["bb_condition"] = {
                "period": (min_period, max_period),
                "std_dev": (2.0, 2.5),
                "check_type": ["price_above_upper", "price_below_lower", "width_gt"],
                "width_value": (0.002, 0.02),
                "timeframe": timeframes,
            }
        elif condition_type == "stoch_condition":
            dynamic_pool["conditions"]["stoch_condition"] = {
                "k_period": (5, 21),
                "d_period": (3, 9),
                "smooth_k": (3, 9),
                "value": (20, 80),
                "operator": ["cross_above", "cross_below", "gt", "lt"],
                "line": ["k", "d"],
                "timeframe": timeframes,
            }
        elif condition_type == "ma_cross_condition":
            dynamic_pool["conditions"]["ma_cross_condition"] = {
                "fast_period": (3, 20),
                "slow_period": (21, 50),
                "timeframe": timeframes,
            }

    # === FILTERS ===
    filters_config = ui_config.get("filters", {})

    if filters_config.get("adx_filter", {}).get("active", False):
        adx_cfg = filters_config["adx_filter"]
        dynamic_pool["filters"]["adx_filter"] = {
            "period": (adx_cfg.get("minPeriod", 7), adx_cfg.get("maxPeriod", 14)),
            "threshold": (15, 25),
            "operator": ["gt"],
            "timeframe": adx_cfg.get("timeframes", ["15m", "1h"]),
        }

    if filters_config.get("trend_filter", {}).get("active", True):
        dynamic_pool["filters"]["trend_filter"] = {
            "threshold": (10, 100),
            "timeframe": ["1h"],
        }

    if filters_config.get("volatility_filter", {}).get("active", False):
        dynamic_pool["filters"]["volatility_filter"] = {
            "operator": ["gt"],
            "value": (0.005, 0.03),
            "timeframe": ["1m", "5m", "15m"],
        }

    # === RISK / EXECUTION -> INITIALIZATION ===
    # Support both direct risk object and nested breakeven_config/partial_tps from API
    risk = ui_config.get("risk", {})

    sl_range = ui_config.get("sl_range") or risk.get("slRange", [1.5, 5.0])
    tp_range = ui_config.get("tp_range") or risk.get("tpRange", [2.0, 8.0])

    # Breakeven ranges - support both nested and flat formats
    breakeven_cfg = ui_config.get("breakeven_config", {})
    be_trigger_range = breakeven_cfg.get("trigger_rr_range") or risk.get(
        "breakevenTriggerRRRange", [0.5, 1.5]
    )
    be_buffer_range = breakeven_cfg.get("buffer_atr_range") or risk.get(
        "breakevenBufferATRRange", [0.02, 0.1]
    )
    be_enabled = breakeven_cfg.get("enabled", risk.get("breakevenEnabled", True))

    # Time Stop range
    time_stop_range = ui_config.get("time_stop_candles_range") or risk.get(
        "timeStopCandlesRange", [144, 576]
    )

    # Build partial TPs config - support both formats
    partial_tps = ui_config.get("partial_tps") or risk.get("partialTPs", [])
    if partial_tps:
        # Take min/max from all partial TP ranges
        all_sizes = []
        all_rrs = []
        for p in partial_tps:
            # Support both snake_case (API) and camelCase (legacy)
            size_range = p.get("size_pct_range") or p.get("sizePctRange", [30, 50])
            rr_range = p.get("target_rr_range") or p.get("targetRRRange", [1.5, 3.0])
            all_sizes.extend(size_range)
            all_rrs.extend(rr_range)
        partial_size_range = (min(all_sizes), max(all_sizes))
        partial_rr_range = (min(all_rrs), max(all_rrs))
    else:
        partial_size_range = (20, 60)
        partial_rr_range = (1.0, 6.0)

    dynamic_pool["initialization"] = {
        "direction": ["LONG"],  # Can be extended to support shorts
        # Stop Loss
        "sl_type": ["atr_multiplier"],
        "sl_value_atr": (sl_range[0], sl_range[1]),
        # Take Profit
        "tp_type": ["rr_multiplier"],
        "tp_value_rr": (tp_range[0], tp_range[1]),
        # Breakeven
        "breakeven_enabled": [be_enabled],
        "breakeven_trigger_rr": (be_trigger_range[0], be_trigger_range[1]),
        "breakeven_buffer_atr": (be_buffer_range[0], be_buffer_range[1]),
        # Time Stop
        "max_hold_candles": (time_stop_range[0], time_stop_range[1]),
        # Partial Exits
        "max_partial_exits": (1, len(partial_tps) + 1) if partial_tps else (1, 3),
        "partial_tp_value_rr": partial_rr_range,
        "partial_size_pct": partial_size_range,
    }

    # === If no conditions were added, use defaults ===
    if not dynamic_pool["conditions"]:
        logger.warning("No active indicators, using default RSI condition")
        dynamic_pool["conditions"]["rsi_condition"] = {
            "period": (5, 14),
            "operator": ["gt", "lt"],
            "value": (25, 75),
            "timeframe": ["1m", "5m", "15m", "1h"],
        }

    if not dynamic_pool["filters"]:
        dynamic_pool["filters"]["trend_filter"] = {
            "threshold": (10, 100),
            "timeframe": ["1h"],
        }

    logger.info(
        f"Dynamic GENE_POOL built: {len(dynamic_pool['conditions'])} conditions, "
        f"{len(dynamic_pool['filters'])} filters"
    )

    return dynamic_pool


def resample_to_timeframes(
    df_1m: pd.DataFrame, timeframes: List[str] = None
) -> Dict[str, pd.DataFrame]:
    """
    Resamples 1m DataFrame into different timeframes.

    Args:
        df_1m: DataFrame with 1-minute data
        timeframes: List of timeframes to create (default is AVAILABLE_TFS)

    Returns:
        Dictionary {timeframe: DataFrame}
    """
    if timeframes is None:
        timeframes = AVAILABLE_TFS

    result = {"1m": df_1m}  # Always include the base 1m

    # Resampling rules for pandas
    tf_rules = {"5m": "5T", "15m": "15T", "1h": "1H", "4h": "4H"}

    for tf in timeframes:
        if tf == "1m":
            continue  # Already exists

        if tf not in tf_rules:
            logger.warning(f"Unknown timeframe: {tf}, skipping")
            continue

        rule = tf_rules[tf]

        # Data aggregation
        agg_dict = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }

        # Add aggregation for additional columns if they exist
        for col in df_1m.columns:
            if col not in agg_dict and col not in [
                "open_time",
                "close_time",
                "timestamp",
            ]:
                # For indicators and other metrics, use the last value
                if col.startswith(
                    (
                        "RSI_",
                        "EMA_",
                        "SMA_",
                        "ADX_",
                        "MACD_",
                        "ATR_",
                        "NATR_",
                        "BB",
                        "STOCH",
                    )
                ):
                    agg_dict[col] = "last"
                # Sum for tape metrics
                elif col.startswith("tape_"):
                    if "volume" in col or "count" in col:
                        agg_dict[col] = "sum"
                    else:
                        agg_dict[col] = "mean"
                # For oracle, we also take the last one
                elif "oracle" in col:
                    agg_dict[col] = "last"

        try:
            df_resampled = df_1m.resample(rule).agg(agg_dict)
            df_resampled.dropna(subset=["open", "high", "low", "close"], inplace=True)
            result[tf] = df_resampled
        except Exception as e:
            logger.error(f"Failed to resample to {tf}: {e}")

    return result


def load_asset_data(path: Path, include_tape: bool = True) -> pd.DataFrame:
    """
    Loads and normalizes asset data from a parquet file with memory optimization.

    Args:
        path: Path to the parquet file
        include_tape: If False, all tape_* columns will be excluded to save memory
    """
    logger.debug(f"Loading data from: {path}...")
    if not path.exists():
        logger.error(f"File not found: {path}")
        return pd.DataFrame()

    df = pd.read_parquet(path)
    if df.empty:
        logger.warning("Loaded DataFrame is empty.")
        return df

    # Normalize column names to lowercase
    df.columns = [str(col).lower() for col in df.columns]

    # Check for required columns and attempt to rename if necessary
    required_cols = {"open", "high", "low", "close", "volume"}
    if not required_cols.issubset(df.columns):
        logger.info(
            "Standard columns not found. Attempting rename from numeric format..."
        )
        num_cols = len(df.columns)
        if num_cols >= 6:
            df.columns = KLINE_COLUMN_NAMES[:num_cols]
            logger.info(f"Columns renamed to: {df.columns.tolist()}")
        else:
            logger.error(
                f"Insufficient columns for renaming ({num_cols}). Cannot proceed."
            )
            return pd.DataFrame()

    # Set datetime index
    if "open_time" in df.columns:
        df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df = df.set_index("timestamp")
    elif isinstance(df.index, pd.DatetimeIndex):
        df.index.name = "timestamp"
        logger.info("Datetime index already exists.")
    else:
        logger.error(f"Could not find a datetime index in file {path}.")
        return pd.DataFrame()

    # IMPORTANT: First remove duplicate columns with suffixes _x, _y, _z
    # This could be the result of multiple merge operations
    all_cols = df.columns.tolist()

    # Group columns by base name (without suffixes)
    col_groups = {}
    for col in all_cols:
        if col.endswith("_x"):
            base = col[:-2]
        elif col.endswith("_y"):
            base = col[:-2]
        elif col.endswith("_z"):
            base = col[:-2]
        else:
            base = col

        if base not in col_groups:
            col_groups[base] = []
        col_groups[base].append(col)

    # Select ONE column from each group (priority: no suffix > _x > _y > _z)
    dedup_cols = []
    for base, variants in col_groups.items():
        if base in variants:
            dedup_cols.append(base)
        elif f"{base}_x" in variants:
            dedup_cols.append(f"{base}_x")
        elif f"{base}_y" in variants:
            dedup_cols.append(f"{base}_y")
        elif f"{base}_z" in variants:
            dedup_cols.append(f"{base}_z")
        else:
            dedup_cols.append(variants[0])

    # Apply deduplication to DataFrame
    df = df[dedup_cols]
    logger.debug(
        f"After deduplication: {len(df.columns)} columns (was {len(all_cols)})"
    )

    # Processing tape columns
    kept_tape_cols = []

    if include_tape:
        # 1. Define the EXACT list of required tape columns
        # Build a whitelist of names based on GENE_POOL
        needed_tape_cols = set()
        for window in [5, 10, 30]:
            needed_tape_cols.add(f"tape_delta_volume_usd_{window}s")
            needed_tape_cols.add(f"tape_delta_count_{window}s")
            needed_tape_cols.add(f"tape_buy_sell_ratio_volume_{window}s")
            needed_tape_cols.add(f"tape_buy_sell_ratio_count_{window}s")
            needed_tape_cols.add(f"tape_total_volume_usd_{window}s")
            needed_tape_cols.add(f"tape_total_count_{window}s")

            # For accel metrics - add averaging windows
            for avg in [60, 120]:
                needed_tape_cols.add(f"tape_accel_mult_volume_{window}s_{avg}s")
                needed_tape_cols.add(f"tape_accel_mult_count_{window}s_{avg}s")

        # Now filter tape columns by whitelist
        all_tape_cols = [c for c in df.columns if c.startswith("tape_")]

        # DEBUG: show the first 5 tape-columns to understand the structure
        if all_tape_cols and len(all_tape_cols) > 0:
            logger.debug(f"Sample tape columns after dedup: {all_tape_cols[:5]}")

        for col in all_tape_cols:
            # Correct removal of suffixes
            if col.endswith("_x"):
                clean_col = col[:-2]
            elif col.endswith("_y"):
                clean_col = col[:-2]
            else:
                clean_col = col

            if clean_col in needed_tape_cols:
                kept_tape_cols.append(col)
    else:
        # If include_tape=False, just ignore all tape columns
        logger.info("Tape columns excluded to save memory (include_tape=False)")

    # 2. Form the final list of columns
    base_cols = ["open", "high", "low", "close", "volume"]
    oracle_cols = [c for c in df.columns if "oracle" in c]

    final_cols = base_cols + kept_tape_cols + oracle_cols

    # Keeping only existing ones
    final_cols = [c for c in final_cols if c in df.columns]
    df = df[final_cols]

    # 3. IMPORTANT: Downcast to float32 (50% memory savings)
    for col in df.columns:
        if df[col].dtype == "float64":
            df[col] = df[col].astype("float32")

    # Ensure base columns are numeric (though they should be after cast)
    for col in base_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df.dropna(subset=base_cols, inplace=True)

    if df.empty:
        logger.error("DataFrame is empty after normalization. Check source file.")
    else:
        tape_status = (
            f"{len(kept_tape_cols)} tape columns"
            if include_tape
            else "0 tape columns (excluded)"
        )
        logger.info(
            f"Loaded {len(df.columns)} columns (Base: {len(base_cols)}, Tape: {tape_status}, Oracle: {len(oracle_cols)}) and downcasted to float32"
        )

    return df


def load_and_prepare_assets(
    asset_paths: List[Path], max_rows: int = 0, include_tape: bool = True
) -> Dict[str, Dict[str, pd.DataFrame]]:
    """
    Loads and prepares data for multiple assets, calculating indicators if missing.

    Args:
        asset_paths: List of paths to asset directories
        max_rows: Maximum rows per asset. 0 = unlimited. 430000 ≈ 10 months for 1m.
        include_tape: If False, tape_* columns will be excluded to save memory (recommended for MTF)

    Returns:
        Dict[asset_name, Dict[timeframe, DataFrame]]
        Example: {'BTCUSDT': {'1m': df_1m, '5m': df_5m, '1h': df_1h, ...}}
    """
    prepared_data = {}
    for asset_path in asset_paths:
        asset_name = asset_path.name
        kline_file = asset_path / KLINE_FILENAME

        logger.info(f"Processing asset: {asset_name} from {kline_file}")
        df = load_asset_data(kline_file, include_tape=include_tape)

        if df.empty:
            logger.warning(f"Skipping asset {asset_name} due to empty data.")
            continue

        # Data limitation (if specified)
        if max_rows > 0 and len(df) > max_rows:
            logger.info(
                f"Trimming {asset_name} from {len(df)} to {max_rows} rows (~{max_rows // 43200} months)"
            )
            df = df.tail(max_rows).copy()

        # Check if indicators are already present (e.g., from a previous run or pre-processed data)
        # A simple check for common indicator prefixes
        has_indicators = any(
            col.startswith(("RSI_", "EMA_", "SMA_", "MACD_", "NATR_", "ATR_"))
            for col in df.columns
        )

        if not has_indicators:
            logger.info(
                f"Indicators not found for {asset_name}. Calculating them using FastVectorBacktester._prepare_data."
            )
            # Create a dummy strategy JSON for indicator calculation
            dummy_strategy = {
                "initialization": {"params": {"sl_value": 1.5, "tp_value": 3.0}},
                "entryConditions": {"type": "AND", "children": []},
                "filters": {"type": "AND", "children": []},
            }
            # Temporarily instantiate FastVectorBacktester to use its _prepare_data method
            temp_backtester = FastVectorBacktester(df, dummy_strategy)
            temp_backtester._prepare_data()

            # Combine main data with calculated indicators (ATR, etc.)
            if not temp_backtester.signals.empty:
                df = pd.concat([df, temp_backtester.signals], axis=1)

            logger.info(
                f"Indicators calculated for {asset_name}. New total columns: {len(df.columns)}"
            )
        else:
            logger.info(
                f"Indicators already present for {asset_name}. Skipping calculation."
            )

        # Creating multi-timeframe data
        logger.info(f"Creating multi-timeframe data for {asset_name}")
        mtf_data = resample_to_timeframes(df, AVAILABLE_TFS)
        prepared_data[asset_name] = mtf_data

        logger.info(
            f"Multi-timeframe data created for {asset_name}: {list(mtf_data.keys())}"
        )

    return prepared_data


def split_data_into_windows(
    assets: Dict[str, Dict[str, pd.DataFrame]], n_windows: int
) -> List[Dict[str, Dict[str, pd.DataFrame]]]:
    """
    Splits data into N equal windows for Walk-Forward optimization.

    Args:
        assets: Dictionary {asset_name: {timeframe: DataFrame}}
        n_windows: Number of windows

    Returns:
        List of N dictionaries, each containing a data slice for the corresponding window
    """
    windows = [{} for _ in range(n_windows)]

    for asset_name, mtf_data in assets.items():
        # Use 1m as the base timeframe for splitting
        df_1m = mtf_data.get("1m")
        if df_1m is None or df_1m.empty:
            continue

        # Splitting by index (time)
        n_rows = len(df_1m)
        window_size = n_rows // n_windows

        for i in range(n_windows):
            start_idx = i * window_size
            end_idx = (i + 1) * window_size if i < n_windows - 1 else n_rows

            # Get time range from 1m data
            start_time = df_1m.index[start_idx]
            end_time = df_1m.index[end_idx - 1]

            # For each timeframe, cut out the corresponding period
            mtf_window = {}
            for tf, df_tf in mtf_data.items():
                # Filter by time
                mask = (df_tf.index >= start_time) & (df_tf.index <= end_time)
                mtf_window[tf] = df_tf[mask].copy()

            windows[i][asset_name] = mtf_window

    return windows


class GeneticStrategyFinder:
    def __init__(
        self,
        training_data: Dict[str, pd.DataFrame],
        run_config: Dict[str, Any],
        run_id: Optional[str] = None,
        ui_config: Optional[Dict[str, Any]] = None,  # Config from Command Center UI
        seed_population: Optional[
            List[Dict[str, Any]]
        ] = None,  # NEW: Seed strategies for continuation
        keep_structure: bool = False,  # NEW: If True, only mutate params, keep block structure
    ):
        self.training_data = training_data
        self.config = run_config
        self.run_id = run_id
        self.seed_population = seed_population or []
        self.keep_structure = keep_structure

        # Build dynamic GENE_POOL from UI config if provided
        if ui_config:
            self.gene_pool = build_dynamic_gene_pool(ui_config)
            logger.info("Using dynamic GENE_POOL from UI config")
        else:
            self.gene_pool = GENE_POOL  # Fallback to static default
            logger.info("Using static default GENE_POOL")

        # Cache derived lists for this instance
        self.available_filters = list(self.gene_pool["filters"].keys())
        self.available_conditions = list(self.gene_pool["conditions"].keys())
        self.available_logic = list(self.gene_pool["logic"].keys())

        # Fitness config from UI (for kill switches)
        self.fitness_config = ui_config.get("fitness", {}) if ui_config else {}

        self.population_size = self.config.get("population_size", 50)
        self.generations = self.config.get("generations", 20)
        self.cx_prob = self.config.get("crossover_probability", 0.7)
        self.mut_prob = self.config.get("mutation_probability", 0.3)

        self.fitness_cache: Dict[str, Tuple] = {}

        self.toolbox = base.Toolbox()
        self._register_deap_functions()

        self.hall_of_fame = tools.HallOfFame(10)
        self.stats = tools.Statistics(key=get_fitness_value)
        self.stats.register("avg", np.mean)
        self.stats.register("std", np.std)
        self.stats.register("min", np.min)
        self.stats.register("max", np.max)

        if self.seed_population:
            logger.info(
                f"GeneticStrategyFinder initialized with {len(self.seed_population)} seed strategies (keep_structure={keep_structure})"
            )
        else:
            logger.info(
                "GeneticStrategyFinder initialized with new logic and MULTIPROCESSING."
            )

    def _register_deap_functions(self):
        """Registers functions for DEAP toolbox."""
        self.toolbox.register("individual", self._create_individual)
        self.toolbox.register(
            "population", tools.initRepeat, list, self.toolbox.individual
        )
        self.toolbox.register("evaluate", self._evaluate_fitness)

        self.toolbox.register("mate", self._crossover_individuals)
        self.toolbox.register("mutate", self._mutate_individual)
        self.toolbox.register("select", tools.selTournament, tournsize=2)

    def _evaluate_fitness(self, individual: Dict[str, Any]) -> Tuple[float]:
        # 1. Validation
        if not individual or not isinstance(individual, dict):
            return (-9999.0,)

        results_per_asset = []
        for asset_name, mtf_data in self.training_data.items():
            try:
                # use_oracle=False to search for a pure strategy
                backtester = FastVectorBacktester(
                    mtf_data, individual, use_oracle=False
                )
                kpis = backtester.run()
                results_per_asset.append(kpis)
            except Exception:
                results_per_asset.append(self._get_default_kpis())

        if not results_per_asset:
            return (-9999.0,)

        # 2. Data collection
        total_trades = sum(r.get("total_trades", 0) for r in results_per_asset)
        # If PnL = NaN, count as -100%
        avg_pnl = np.nanmean(
            [r.get("total_pnl_pct", -100.0) for r in results_per_asset]
        )
        avg_max_dd = np.nanmean([r.get("max_dd", 100.0) for r in results_per_asset])

        # =========================================================
        # ⛔ HARD FILTERS (KILL SWITCHES)
        # =========================================================

        # 1. SPAM KILLER: If there are more than 1000 trades in 5 months — it's garbage.
        # Your 12000 trades will immediately get -9999 and die.
        if total_trades > 1000:
            return (-9999.0,)

        # 2. MINIMUM TRADES: To exclude "one trade for the whole bankroll"
        if total_trades < 30:
            return (-5000.0,)

        # 3. LOSS-MAKING: If you lose money — your fitness is NEGATIVE.
        # No bonuses. Lost 5% -> Fitness -5. Lost 100% -> Fitness -100.
        if avg_pnl <= 0:
            return (avg_pnl,)

        # 4. DRAWDOWN: We want a safe strategy.
        # If drawdown is above 25% — we don't take it, even if there is profit.
        if avg_max_dd > 25.0:
            return (-avg_max_dd * 10.0,)  # Penalty

        # =========================================================
        # 🏆 QUALITY FORMULA (Calmar Ratio Style)
        # =========================================================
        # ONLY strategies that reach here are those that:
        # - In profit (PnL > 0)
        # - No spamming (30 < Trades < 1000)
        # - Safe (DD < 25%)

        # We divide Profit by Drawdown.
        # PnL 100% / DD 10% = 10 points.
        # PnL 100% / DD 50% = 2 points (won't reach here because of the filter above, but the point is clear).

        risk_free_dd = max(1.0, avg_max_dd)  # To avoid division by zero
        score = (avg_pnl / risk_free_dd) * 10.0

        # Small bonus for an adequate number of trades (to avoid sitting in one trade for a year)
        # Bonus works only if the strategy is already profitable!
        if total_trades > 100:
            score *= 1.1  # +10% to points

        return (score,)

    # ===========================================================================
    # SEED POPULATION METHODS
    # ===========================================================================

    def _init_seeded_population(self) -> List[Any]:
        """
        Initialize population using seed strategies.
        Takes top N seeds and fills rest with mutations.
        """
        seed_count = min(len(self.seed_population), self.population_size // 2)
        population = []

        tqdm.write(
            f"🌱 SEEDED EVOLUTION: Using {seed_count} seed strategies as starting population"
        )

        # Convert seed strategies to DEAP individuals
        for i, strategy in enumerate(self.seed_population[:seed_count]):
            try:
                ind = self._strategy_to_individual(strategy)
                population.append(ind)
                tqdm.write(
                    f"   Seed {i + 1}: Loaded strategy with {len(ind.get('filters', {}).get('children', []))} filters"
                )
            except Exception as e:
                tqdm.write(f"   ⚠️ Failed to convert seed {i + 1}: {e}")

        if not population:
            tqdm.write("   ⚠️ No valid seeds, falling back to random population")
            return self.toolbox.population(n=self.population_size)

        # Fill remaining slots with mutations of seeds
        while len(population) < self.population_size:
            # Pick a random seed as source
            source = random.choice(population[:seed_count])
            mutant = copy.deepcopy(source)

            # Apply mutation
            if self.keep_structure:
                self._mutate_params_only(mutant)
            else:
                self._mutate_individual(mutant)

            # Wrap in creator.Individual if needed
            if not hasattr(mutant, "fitness"):
                mutant = creator.Individual(mutant)
            else:
                del mutant.fitness.values

            population.append(mutant)

        tqdm.write(
            f"   ✓ Population initialized: {seed_count} seeds + {len(population) - seed_count} mutations"
        )
        return population

    def _strategy_to_individual(self, strategy_dict: Dict[str, Any]) -> Any:
        """
        Convert a strategy JSON dict back into a DEAP Individual.
        Handles various formats (raw, nested, from found_strategy, etc.)
        """
        # Normalize strategy format (extract from wrappers if needed)
        normalized = FastVectorBacktester.normalize_strategy(strategy_dict)

        # Extract the core strategy components
        individual_data = {
            "filters": normalized.get("filters", {}),
            "entryConditions": normalized.get("entryConditions", {}),
            "initialization": normalized.get("initialization", {}),
        }

        # Create DEAP Individual
        ind = creator.Individual(individual_data)
        return ind

    def _mutate_params_only(self, individual: Dict[str, Any]) -> None:
        """
        Mutate only numeric parameters, preserving the block structure.
        This allows optimization of periods, thresholds etc. without changing
        the logical structure of the strategy.
        """

        def mutate_node(node: Dict[str, Any]) -> None:
            if not isinstance(node, dict):
                return

            # Mutate params if present
            if "params" in node and isinstance(node["params"], dict):
                for key, val in list(node["params"].items()):
                    if isinstance(val, (int, float)) and key != "timeframe":
                        # Mutation: ±20% with some probability
                        if random.random() < 0.3:  # 30% chance per param
                            if isinstance(val, int):
                                # Integer: ±2 or ±20%
                                delta = max(1, int(val * 0.2))
                                node["params"][key] = max(
                                    1, val + random.randint(-delta, delta)
                                )
                            else:
                                # Float: ±20%
                                node["params"][key] = val * random.uniform(0.8, 1.2)

            # Recurse into children
            if "children" in node and isinstance(node["children"], list):
                for child in node["children"]:
                    mutate_node(child)

        # Mutate filters and entry conditions
        for key in ["filters", "entryConditions"]:
            if key in individual and isinstance(individual[key], dict):
                mutate_node(individual[key])

        # Optionally mutate initialization params
        if "initialization" in individual and "params" in individual["initialization"]:
            params = individual["initialization"]["params"]
            if isinstance(params, dict):
                for key in ["sl_value", "tp_value"]:
                    if key in params and isinstance(params[key], (int, float)):
                        if random.random() < 0.3:
                            params[key] = params[key] * random.uniform(0.8, 1.2)

    def run(
        self,
        map_function,
        progress_callback: Optional[callable] = None,
        checkpoint_file: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        # 🔇 SILENT MODE
        logging.getLogger("bot_module").setLevel(logging.WARNING)
        logging.getLogger().setLevel(logging.WARNING)

        # POPULATION INITIALIZATION (with seed support)
        if self.seed_population and len(self.seed_population) > 0:
            population = self._init_seeded_population()
        else:
            population = self.toolbox.population(n=self.population_size)

        start_gen = 0

        # Variables for a pretty log
        display_pnl = 0.0

        # LOADING CHECKPOINT
        if checkpoint_file and os.path.exists(checkpoint_file):
            try:
                is_json = False
                try:
                    with open(checkpoint_file, "r") as cp_file:
                        header = cp_file.read(100)
                        if header.strip().startswith("{"):
                            is_json = True
                except Exception:
                    pass

                if is_json:
                    with open(checkpoint_file, "r") as cp_file:
                        state = json.load(cp_file)

                    if state.get("serialization_format") != "json":
                        logger.warning(
                            "SECURITY WARNING: Checkpoint serialization_format is not 'json'. "
                            "Skipping loading of unverified checkpoint to prevent pickle vulnerability."
                        )
                    else:
                        population_dicts = state.get("population", [])
                        restored_pop = []
                        for ind_dict in population_dicts:
                            fit_vals = ind_dict.pop("fitness_values", None)
                            ind = creator.Individual(ind_dict)
                            if fit_vals:
                                ind.fitness.values = tuple(fit_vals)
                            restored_pop.append(ind)
                        population = restored_pop
                        start_gen = state.get("generation", 0) + 1

                        self.hall_of_fame.clear()
                        hof_inds = []
                        for ind_dict in state.get("hall_of_fame", []):
                            fit_vals = ind_dict.pop("fitness_values", None)
                            ind = creator.Individual(ind_dict)
                            if fit_vals:
                                ind.fitness.values = tuple(fit_vals)
                            hof_inds.append(ind)
                        if hof_inds:
                            self.hall_of_fame.update(hof_inds)

                        self.fitness_cache = {}

                        # Reset fitness cache values for population (as in original logic)
                        for ind in population:
                            if hasattr(ind, "fitness"):
                                del ind.fitness.values
                        self.hall_of_fame.clear()

                        tqdm.write(
                            f"♻️  RESUMED from Gen {start_gen}. Fitness cache CLEARED for re-evaluation."
                        )
                else:
                    logger.warning(
                        "SECURITY WARNING: Checkpoint file is in legacy format (pickle). "
                        "Skipping loading of unverified checkpoint to prevent pickle vulnerability."
                    )
            except Exception as e:
                logger.error(f"Failed to load checkpoint safely: {e}")

        tqdm.write(
            f"🧬 STARTING EVOLUTION: {self.generations} gens, {self.population_size} pop"
        )
        tqdm.write("-" * 60)

        for gen in range(start_gen, self.generations):
            # 1. Selection
            offspring = self.toolbox.select(population, len(population))
            offspring = [self.toolbox.clone(ind) for ind in offspring]

            # 2. Crossover
            for child1, child2 in zip(offspring[::2], offspring[1::2]):
                if random.random() < self.cx_prob:
                    self.toolbox.mate(child1, child2)
                    del child1.fitness.values
                    del child2.fitness.values

            # 3. Mutation
            for mutant in offspring:
                if random.random() < self.mut_prob:
                    self.toolbox.mutate(mutant)
                    del mutant.fitness.values

            # 4. Evaluation (Evaluate EVERYONE, as we have reset the cache)
            invalid_ind = [ind for ind in offspring if not ind.fitness.valid]

            if invalid_ind:
                desc_str = f"Gen {gen + 1} (Best: {display_pnl:.1f}%)"

                fitnesses = list(
                    tqdm(
                        map_function(self.toolbox.evaluate, invalid_ind),
                        total=len(invalid_ind),
                        desc=desc_str,
                        unit="ind",
                        colour="green",
                        mininterval=0.5,
                        leave=False,
                    )
                )
                for ind, fit in zip(invalid_ind, fitnesses):
                    safe_fit = fit if (fit and not np.isnan(fit[0])) else (-99999.0,)
                    ind.fitness.values = safe_fit
                    ind.__dict__["fitness_values"] = safe_fit

            # 5. Update HoF
            if self.hall_of_fame is not None:
                self.hall_of_fame.update(offspring)

            # HONEST STATISTICS OUTPUT (AGGREGATE)
            if self.hall_of_fame:
                best_ind = self.hall_of_fame[0]
                best_fit = best_ind.fitness.values[0]

                try:
                    # Calculate the average across ALL assets so the log doesn't lie
                    total_pnl = 0.0
                    total_trades = 0
                    total_dd = 0.0
                    count = 0

                    # Take the first 3 assets for speed (or all if there are few)
                    check_assets = list(self.training_data.values())[:5]

                    for mtf_data in check_assets:
                        bt = FastVectorBacktester(mtf_data, best_ind, use_oracle=False)
                        kpis = bt.run()
                        total_pnl += kpis.get("total_pnl_pct", 0)
                        total_trades += kpis.get("total_trades", 0)
                        total_dd += kpis.get("max_dd", 0)
                        count += 1

                    avg_pnl = total_pnl / count if count > 0 else 0
                    avg_dd = total_dd / count if count > 0 else 0
                    sum_trades = total_trades  # Sum of deals

                    display_pnl = avg_pnl

                    log_msg = (
                        f"Gen {gen + 1:03d} | "
                        f"Fit: {best_fit:>6.1f} | "
                        f"Trd: {sum_trades:>4} | "
                        f"AvgPnL: {avg_pnl:>6.2f}% | "
                        f"AvgDD: {avg_dd:>4.1f}%"
                    )
                    tqdm.write(log_msg)

                    # Call progress callback if provided
                    if progress_callback:
                        try:
                            progress_callback(
                                {
                                    "current_generation": gen + 1,
                                    "total_generations": self.generations,
                                    "best_fitness_so_far": best_fit,
                                    "average_fitness_this_gen": avg_pnl,
                                    "best_pnl": avg_pnl,
                                    "best_trades": sum_trades,
                                    "best_dd": avg_dd,
                                    "hof": [
                                        dict(ind) for ind in self.hall_of_fame[:5]
                                    ],  # Passing top-5
                                }
                            )
                        except Exception as cb_err:
                            logger.warning(f"Progress callback error: {cb_err}")

                except Exception:
                    tqdm.write(f"Gen {gen + 1} | Fit: {best_fit:.2f} (Calc Error)")

            # 6. Elitism
            ELITE_COUNT = 3
            if self.hall_of_fame:
                elites = [
                    self.toolbox.clone(ind) for ind in self.hall_of_fame[:ELITE_COUNT]
                ]
                offspring.sort(
                    key=lambda x: x.fitness.values[0] if x.fitness.valid else -99999.0
                )
                for i in range(len(elites)):
                    if i < len(offspring):
                        offspring[i] = elites[i]

            population[:] = offspring

            # Save Checkpoint
            if checkpoint_file:
                try:
                    population_dicts = []
                    for ind in population:
                        d = dict(ind)
                        if hasattr(ind, "fitness") and ind.fitness.valid:
                            d["fitness_values"] = list(ind.fitness.values)
                        population_dicts.append(d)

                    hof_dicts = []
                    if self.hall_of_fame:
                        for ind in self.hall_of_fame:
                            d = dict(ind)
                            if hasattr(ind, "fitness") and ind.fitness.valid:
                                d["fitness_values"] = list(ind.fitness.values)
                            hof_dicts.append(d)

                    state = {
                        "population": population_dicts,
                        "generation": gen,
                        "hall_of_fame": hof_dicts,
                        "serialization_format": "json",
                    }
                    with open(checkpoint_file, "w") as cp_file:
                        json.dump(state, cp_file, indent=2)

                    if self.hall_of_fame:
                        output_dir = Path("found_strategies_mtf")
                        output_dir.mkdir(exist_ok=True)
                        for i, ind in enumerate(self.hall_of_fame[:3], 1):
                            fname = f"gen{gen + 1:03d}_rank{i}_fitness{ind.fitness.values[0]:.2f}.json"
                            if not (output_dir / fname).exists():
                                with open(output_dir / fname, "w") as f:
                                    json.dump(dict(ind), f, indent=2)
                except Exception:
                    pass

        # FINALIZATION: FORMING RESULTS
        final_results = []
        if self.hall_of_fame:
            for rank, ind in enumerate(self.hall_of_fame, 1):
                try:
                    # Aggregating KPIs across all assets
                    total_pnl = 0.0
                    total_trades = 0
                    total_pf = 0.0
                    total_max_dd = 0.0
                    total_sharpe = 0.0
                    total_win_rate = 0.0
                    count = 0

                    for mtf_data in self.training_data.values():
                        bt = FastVectorBacktester(mtf_data, ind, use_oracle=False)
                        kpis = bt.run()
                        total_pnl += kpis.get("total_pnl_pct", 0)
                        total_trades += kpis.get("total_trades", 0)
                        total_pf += kpis.get("profit_factor", 0)
                        total_max_dd += kpis.get("max_dd", 0)
                        total_sharpe += kpis.get("sharpe_ratio", 0)
                        total_win_rate += kpis.get("win_rate", 0)
                        count += 1

                    # Calculate averages across all assets
                    avg_pnl = total_pnl / count if count > 0 else 0
                    avg_pf = total_pf / count if count > 0 else 0
                    avg_max_dd = total_max_dd / count if count > 0 else 0
                    avg_sharpe = total_sharpe / count if count > 0 else 0
                    avg_win_rate = total_win_rate / count if count > 0 else 0

                    final_results.append(
                        {
                            "rank": rank,
                            "fitness_score": ind.fitness.values[0]
                            if ind.fitness.valid
                            else 0.0,
                            "strategy_json": dict(ind),
                            "kpis_json": {
                                "total_pnl_pct": avg_pnl,
                                "total_trades": total_trades,
                                "profit_factor": avg_pf,
                                "max_drawdown_pct": avg_max_dd,
                                "sharpe_ratio": avg_sharpe,
                                "win_rate": avg_win_rate,
                            },
                        }
                    )
                except Exception as e:
                    logger.warning(f"Error finalizing result for rank {rank}: {e}")

        tqdm.write(f"\\n✅ EVOLUTION COMPLETE. Found {len(final_results)} strategies.")
        return final_results

    def _get_default_kpis(self) -> Dict[str, float]:
        """Returns KPI for the case when there are no trades or an error occurred."""
        return {
            "total_trades": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "sharpe_ratio": -10.0,
            "total_pnl_pct": 0.0,
        }

    def _create_individual(self) -> creator.Individual:
        """Creates a random strategy with a GUARANTEED correct structure."""
        strategy = {
            "id": str(uuid4()),
            "name": "Genetic Strategy",
            "strategy_name": "GeneticStrategy",
            "symbol": "GENETIC",
            "marketType": "FUTURES",
            "filters": self._generate_logic_node(
                self.available_filters, max_depth=2, current_depth=0
            ),
            "entryTrigger": {
                "type": "on_candle_close",
                "params": {},
                "timeframe": "1m",
            },
            "entryConditions": self._generate_logic_node(
                self.available_conditions, max_depth=3, current_depth=0
            ),
            "initialization": self._generate_random_initialization(),
            "positionManagement": [],
        }
        return creator.Individual(strategy)

    def _generate_logic_node(
        self, allowed_nodes: List[str], max_depth: int, current_depth: int
    ) -> Dict:
        """Generates ONLY a logical node (ConditionNode)."""
        root_op = random.choice(["AND", "OR"])  # Logic only

        # Generating children
        num_children = random.randint(
            2, self.gene_pool["logic"][root_op]["max_children"]
        )  # Minimum 2 children for logic
        children = []

        for _ in range(num_children):
            children.append(
                self._generate_subtree(allowed_nodes, max_depth, current_depth + 1)
            )

        return {"id": str(uuid4()), "type": root_op, "children": children}

    def _generate_subtree(
        self, allowed_nodes: List[str], max_depth: int, current_depth: int
    ) -> Dict:
        """Generates either a node or a leaf."""
        # Chance to create a nested logical block
        if current_depth < max_depth and random.random() < 0.3:
            return self._generate_logic_node(allowed_nodes, max_depth, current_depth)
        else:
            # Otherwise create a list
            node_type = random.choice(
                [n for n in allowed_nodes if n not in self.available_logic]
            )
            return self._generate_random_leaf_node(node_type)

    def _generate_random_tree(
        self,
        allowed_nodes: List[str],
        max_depth: int,
        current_depth: int = 1,
        is_filter: bool = False,
    ) -> Dict:
        """Generates a random condition tree (for filters or entryConditions)."""
        # If this is a filter, the root node cannot be a logical operator
        if is_filter:
            node_type = random.choice(
                [n for n in allowed_nodes if n not in self.available_logic]
            )
            return self._generate_random_leaf_node(node_type)

        root_op = random.choice(self.available_logic)
        num_children = random.randint(
            1, self.gene_pool["logic"][root_op]["max_children"]
        )
        children = []
        for _ in range(num_children):
            # Chance of creating a nested logical block decreases with depth
            is_logic_node = (current_depth < max_depth) and (
                random.random() < 0.3 / current_depth
            )

            if is_logic_node:
                children.append(
                    self._generate_random_tree(
                        allowed_nodes, max_depth, current_depth + 1
                    )
                )
            else:
                node_type = random.choice(
                    [n for n in allowed_nodes if n not in self.available_logic]
                )
                children.append(self._generate_random_leaf_node(node_type))

        return {"id": str(uuid4()), "type": root_op, "children": children}

    def _generate_random_leaf_node(self, node_type: str) -> Dict:
        """Generates ConditionLeaf (WITHOUT children)."""
        params = {}
        pool = self.gene_pool["filters"].get(node_type) or self.gene_pool[
            "conditions"
        ].get(node_type)

        if pool:
            if node_type == "value_comparison":
                # Special logic for value_comparison
                params["leftOperand"] = random.choice(pool["leftOperand"])
                params["rightOperand"] = random.choice(pool["rightOperand"])
                params["operator"] = random.choice(pool["operator"])
            else:
                for param, value_range in pool.items():
                    # Skip timeframe, we will process it separately
                    if param == "timeframe":
                        continue

                    if isinstance(value_range, list):
                        params[param] = random.choice(value_range)
                    elif isinstance(value_range, tuple):
                        if isinstance(value_range[0], int):
                            params[param] = random.randint(*value_range)
                        else:
                            params[param] = round(random.uniform(*value_range), 4)

            # Select timeframe if it is in the pool
            if "timeframe" in pool:
                params["timeframe"] = random.choice(pool["timeframe"])

            # THIS BLOCK NEEDS TO BE ADDED
            # Ensure that fast_period < slow_period for MACD
            if node_type == "macd_condition":
                fast = params.get("fast_period")
                slow = params.get("slow_period")
                if fast is not None and slow is not None and fast >= slow:
                    params["fast_period"], params["slow_period"] = (
                        slow,
                        fast,
                    )  # Just swap them

        return {"id": str(uuid4()), "type": node_type, "params": params}

    def _generate_random_initialization(self) -> Dict:
        """Generates the initialization block with extended logic."""
        params_pool = self.gene_pool["initialization"]

        # Selection of type and value for Stop Loss
        sl_type = random.choice(params_pool["sl_type"])
        if sl_type == "percent_from_price":
            sl_value = round(random.uniform(*params_pool["sl_value_percent"]), 2)
        else:  # atr_multiplier
            sl_value = round(random.uniform(*params_pool["sl_value_atr"]), 2)

        # Selection of type and value for Take Profit
        tp_type = random.choice(params_pool["tp_type"])
        if tp_type == "percent_from_price":
            tp_value = round(random.uniform(*params_pool["tp_value_percent"]), 2)
        else:  # rr_multiplier
            tp_value = round(random.uniform(*params_pool["tp_value_rr"]), 2)

        # Generation of partial exits (with 40% probability)
        partial_exits = []
        if random.random() < 0.4:
            # max_partial_exits is now a tuple range (min, max)
            max_exits_range = params_pool["max_partial_exits"]
            if isinstance(max_exits_range, tuple):
                num_exits = random.randint(max_exits_range[0], max_exits_range[1])
            else:
                num_exits = random.randint(1, max_exits_range)
            remaining_size_pct = 100
            for _ in range(num_exits):
                # Minimum size for partial take
                min_size_pct = params_pool["partial_size_pct"][0]

                # Check if there is enough size left to create another exit
                if remaining_size_pct < min_size_pct + 5:  # +5 to have a margin
                    break  # If too few remain, stop generating takes

                # Upper bound cannot be less than lower bound
                max_allowed_size = min(
                    params_pool["partial_size_pct"][1], remaining_size_pct - 5
                )
                if max_allowed_size < min_size_pct:
                    break  # If even the maximum possible size is less than the minimum allowed

                # Generate output size
                size_pct = random.randint(min_size_pct, max_allowed_size)

                partial_exits.append(
                    {
                        "tp_type": "rr_multiplier",
                        "tp_value": round(
                            random.uniform(*params_pool["partial_tp_value_rr"]), 2
                        ),
                        "size_pct": size_pct,
                    }
                )
                remaining_size_pct -= size_pct

        # Sort partial exits by R:R so they are in the correct order
        partial_exits.sort(key=lambda x: x["tp_value"])

        max_hold_range = GENE_POOL["initialization"].get("max_hold_candles", (0, 0))
        if isinstance(max_hold_range, tuple) and max_hold_range != (0, 0):
            max_hold = random.randint(*max_hold_range)
        else:
            max_hold = 0

        return {
            "id": str(uuid4()),
            "type": "open_position",
            "params": {
                "direction": random.choice(params_pool["direction"]),
                "sl_type": sl_type,
                "sl_value": sl_value,
                "tp_type": tp_type,
                "tp_value": tp_value,
                "move_sl_to_be_on_first_tp": random.choice(
                    params_pool.get("move_sl_to_be_on_first_tp", [True, False])
                ),
                "partial_exits": partial_exits,
                "max_hold_candles": max_hold,
            },
        }

    def _get_all_nodes(self, tree: Dict) -> List[Tuple[Dict, Optional[Dict]]]:
        """Recursively collects all tree nodes and their parents."""
        nodes = []

        def traverse(node, parent=None):
            nodes.append((node, parent))
            if "children" in node and node["children"]:
                for child in node["children"]:
                    traverse(child, node)

        traverse(tree)
        return nodes

    def _crossover_individuals(self, ind1: Dict, ind2: Dict) -> Tuple[Dict, Dict]:
        """
        Crosses two individuals by exchanging sub-trees in filters or entryConditions sections.
        Can also cross parameters in initialization.
        """
        child1, child2 = self.toolbox.clone(ind1), self.toolbox.clone(ind2)

        # 1. Crossover of initialization parameters
        init_params1 = child1.get("initialization", {}).get("params", {})
        init_params2 = child2.get("initialization", {}).get("params", {})

        # Take keys from the individual itself, not from GENE_POOL
        # Find common keys present in both parents
        common_params = list(set(init_params1.keys()) & set(init_params2.keys()))

        for param in common_params:
            if random.random() < 0.5:  # 50% chance to exchange a parameter
                init_params1[param], init_params2[param] = (
                    init_params2[param],
                    init_params1[param],
                )

        # 2. Crossover of sub-trees in filters or entryConditions
        for section_key in ["filters", "entryConditions"]:
            if random.random() < 0.7:  # 70% crossover chance for this section
                nodes1 = self._get_all_nodes_with_parents(child1.get(section_key, {}))
                nodes2 = self._get_all_nodes_with_parents(child2.get(section_key, {}))

                # Exclude the root node for exchange to avoid breaking the structure
                valid_nodes1 = [n for n in nodes1 if n[1] is not None]
                valid_nodes2 = [n for n in nodes2 if n[1] is not None]

                if valid_nodes1 and valid_nodes2:
                    node1, parent1, parent_key1 = random.choice(valid_nodes1)
                    node2, parent2, parent_key2 = random.choice(valid_nodes2)

                    # Node exchange
                    if (
                        parent1
                        and parent2
                        and parent_key1 == "children"
                        and parent_key2 == "children"
                    ):
                        idx1 = parent1["children"].index(node1)
                        idx2 = parent2["children"].index(node2)
                        parent1["children"][idx1], parent2["children"][idx2] = (
                            node2,
                            node1,
                        )
                        logger.debug(f"Crossed over nodes in {section_key}")
                    elif (
                        parent1
                        and parent2
                        and parent_key1 == section_key
                        and parent_key2 == section_key
                    ):
                        # If the root nodes of the section are not logical blocks, but single filters/conditions
                        child1[section_key], child2[section_key] = (
                            child2[section_key],
                            child1[section_key],
                        )
                        logger.debug(f"Crossed over root nodes in {section_key}")

        return child1, child2

    def _mutate_individual(self, individual: Dict, ind_pb: float = 0.1) -> Tuple[Dict]:
        """
        Applies a random mutation to an individual.
        ind_pb: Mutation probability for each element (parameter, node).
        """
        # Parameter mutation in initialization
        init_params = individual.get("initialization", {}).get("params", {})

        # First, mutate simple parameters that are directly in GENE_POOL
        for param, value_range in GENE_POOL["initialization"].items():
            if param in init_params and random.random() < ind_pb:
                # If it's a list (e.g., direction), we select random.choice
                if isinstance(value_range, list):
                    init_params[param] = random.choice(value_range)
                # If it's a tuple (numbers), then uniform/randint (simplified here for bool/int)
                elif isinstance(value_range, tuple) and isinstance(
                    value_range[0], (int, float)
                ):
                    init_params[param] = round(random.uniform(*value_range), 2)

        # Separate logic for SL and TP mutation (since their keys differ from GENE_POOL)
        if random.random() < ind_pb:
            sl_type = init_params.get("sl_type")
            if sl_type == "percent_from_price":
                # Was: GENE_POOL...["sl_value_percent"]
                # Make sure you take exactly a range (tuple), not a list
                init_params["sl_value"] = round(
                    random.uniform(*GENE_POOL["initialization"]["sl_value_percent"]), 2
                )
            elif sl_type == "atr_multiplier":
                init_params["sl_value"] = round(
                    random.uniform(*GENE_POOL["initialization"]["sl_value_atr"]), 2
                )

        # Same for TP, make sure you use the correct keys from the updated GENE_POOL
        if random.random() < ind_pb:
            # We only left rr_multiplier in GENE_POOL, so it can be simplified:
            init_params["tp_value"] = round(
                random.uniform(*GENE_POOL["initialization"]["tp_value_rr"]), 2
            )

        # Mutation in filters and entryConditions
        for section_key in ["filters", "entryConditions"]:
            if section_key not in individual:
                continue

            nodes_with_parents = self._get_all_nodes_with_parents(
                individual[section_key]
            )
            if not nodes_with_parents:
                continue

            for node, parent, parent_key in nodes_with_parents:
                if random.random() < ind_pb:  # Mutation probability for each node
                    node_type = node.get("type")

                    # 1. Mutation of parameters inside the node
                    pool = GENE_POOL["filters"].get(node_type) or GENE_POOL[
                        "conditions"
                    ].get(node_type)
                    if pool and node.get("params"):
                        # Select a random parameter (including timeframe if it exists)
                        available_params = [k for k in pool.keys() if k != "timeframe"]

                        # Mutate timeframe with 30% probability (if it exists)
                        if (
                            "timeframe" in pool
                            and "timeframe" in node["params"]
                            and random.random() < 0.3
                        ):
                            new_tf = random.choice(pool["timeframe"])
                            node["params"]["timeframe"] = new_tf
                            logger.debug(
                                f"Mutated timeframe to {new_tf} in node {node_type}"
                            )
                        # Otherwise, mutate a regular parameter
                        elif available_params:
                            param_to_mutate = random.choice(available_params)
                            value_range = pool[param_to_mutate]
                            if isinstance(value_range, list):
                                new_value = random.choice(value_range)
                            elif isinstance(value_range[0], int):
                                new_value = random.randint(*value_range)
                            else:
                                new_value = round(random.uniform(*value_range), 4)
                            node["params"][param_to_mutate] = new_value
                            logger.debug(
                                f"Mutated parameter {param_to_mutate} in node {node_type}"
                            )

                    # 2. Structural mutation: node replacement (only for non-logical nodes)
                    elif (
                        node_type not in AVAILABLE_LOGIC
                        and parent
                        and random.random() < 0.2
                    ):  # 20% chance of structural mutation
                        idx = parent["children"].index(node)
                        allowed_nodes = (
                            AVAILABLE_FILTERS
                            if section_key == "filters"
                            else AVAILABLE_CONDITIONS
                        )
                        new_node_type = random.choice(allowed_nodes)
                        parent["children"][idx] = self._generate_random_leaf_node(
                            new_node_type
                        )
                        logger.debug(
                            f"Structurally mutated node from {node_type} to {new_node_type}"
                        )

                    # 3. Logical mutation: adding/removing a child node in AND/OR
                    elif (
                        node_type in AVAILABLE_LOGIC and random.random() < 0.15
                    ):  # 15% chance of logical mutation
                        if (
                            random.random() < 0.5 and node["children"]
                        ):  # 50% chance to delete
                            node["children"].pop(
                                random.randrange(len(node["children"]))
                            )
                            logger.debug(f"Removed child from logical node {node_type}")
                        elif (
                            len(node["children"])
                            < GENE_POOL["logic"][node_type]["max_children"]
                        ):  # 50% chance to add
                            allowed_nodes = (
                                AVAILABLE_FILTERS
                                if section_key == "filters"
                                else AVAILABLE_CONDITIONS
                            )
                            new_child_type = random.choice(
                                allowed_nodes + AVAILABLE_LOGIC
                            )
                            if new_child_type in AVAILABLE_LOGIC:
                                node["children"].append(
                                    self._generate_random_tree(
                                        allowed_nodes, max_depth=2
                                    )
                                )
                            else:
                                node["children"].append(
                                    self._generate_random_leaf_node(new_child_type)
                                )
                            logger.debug(f"Added child to logical node {node_type}")

                    # 4. OPERATOR mutation (AND <-> OR)
                    # This allows the strategy to instantly change its mind:
                    # "I need both this AND that" -> "I need either this OR that"
                    elif node_type in ["AND", "OR"]:
                        # Changing type to the opposite
                        node["type"] = "OR" if node_type == "AND" else "AND"
                        logger.debug(
                            f"Flipped logic operator from {node_type} to {node['type']}"
                        )

        init_params = individual.get("initialization", {}).get("params", {})

        # Add mutation for max_hold_candles
        if random.random() < ind_pb:
            val_range = GENE_POOL["initialization"].get("max_hold_candles")
            if val_range and isinstance(val_range, tuple):
                init_params["max_hold_candles"] = random.randint(*val_range)

        return (individual,)

    def _get_all_nodes_with_parents(
        self, tree: Dict, parent=None, parent_key=None
    ) -> List[Tuple[Dict, Optional[Dict], Optional[str]]]:
        """Recursively collects all tree nodes, their parents, and the key by which the parent refers to the node."""
        nodes = []
        if not isinstance(tree, dict):  # If it's a leaf, not a tree
            return nodes

        nodes.append((tree, parent, parent_key))
        if "children" in tree and tree["children"]:
            for child in tree["children"]:
                nodes.extend(self._get_all_nodes_with_parents(child, tree, "children"))
        return nodes


if __name__ == "__main__":
    import argparse
    import os
    from pathlib import Path

    import logging

    log_handler = TqdmLoggingHandler()
    log_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(message)s")
    )  # Removed unnecessary parts from the format

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    # Remove old handlers if they existed
    while root_logger.handlers:
        root_logger.removeHandler(root_logger.handlers[0])
    root_logger.addHandler(log_handler)

    parser = argparse.ArgumentParser(
        description="Genetic Strategy Finder for DepthSight"
    )
    parser.add_argument(
        "--data_path",
        type=str,
        required=True,
        help="Path to the root folder containing asset data (e.g., F:\\TRAIN_ASSETS).",
    )
    parser.add_argument(
        "--test_assets",
        type=str,
        nargs="*",
        default=[],
        help="List of asset folder names to be used for testing (e.g., ADAUSDT ZECUSDT).",
    )
    parser.add_argument(
        "--population_size",
        type=int,
        default=50,
        help="Size of the genetic algorithm population.",
    )
    parser.add_argument(
        "--generations",
        type=int,
        default=20,
        help="Number of generations for the genetic algorithm.",
    )
    parser.add_argument(
        "--crossover_probability",
        type=float,
        default=0.7,
        help="Crossover probability.",
    )
    parser.add_argument(
        "--mutation_probability", type=float, default=0.3, help="Mutation probability."
    )
    parser.add_argument(
        "--min_trades_for_prescreening",
        type=int,
        default=10,
        help="Minimum number of trades for a strategy to avoid heavy penalty.",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="found_strategies",
        help="Directory to save the found strategies.",
    )
    parser.add_argument(
        "--checkpoint_file",
        type=str,
        default="ga_checkpoint.pkl",
        help="File to save and load the algorithm's state.",
    )
    parser.add_argument(
        "--max_cores",
        type=int,
        default=None,
        help="Maximum number of CPU cores to use. Default: all available.",
    )

    args = parser.parse_args()

    data_path_obj = Path(args.data_path)
    if not data_path_obj.exists():
        logger.error(f"Data path not found: {args.data_path}")
        exit(1)

    all_asset_folders = [d.name for d in data_path_obj.iterdir() if d.is_dir()]

    train_asset_names = [
        name for name in all_asset_folders if name not in args.test_assets
    ]
    test_asset_names = [name for name in all_asset_folders if name in args.test_assets]

    if not train_asset_names:
        logger.error(
            "No training assets found. Please check --data_path and --test_assets arguments."
        )
        exit(1)

    train_asset_paths = [data_path_obj / name for name in train_asset_names]
    test_asset_paths = [data_path_obj / name for name in test_asset_names]

    logger.info(f"Found {len(all_asset_folders)} total assets.")
    logger.info(
        f"Training assets ({len(train_asset_names)}): {', '.join(train_asset_names)}"
    )
    logger.info(f"Test assets ({len(test_asset_names)}): {', '.join(test_asset_names)}")

    training_data_dfs = load_and_prepare_assets(train_asset_paths)
    if not training_data_dfs:
        logger.error("No training data loaded. Exiting.")
        exit(1)

    # Launch configuration
    run_config = {
        "population_size": args.population_size,
        "generations": args.generations,
        "crossover_probability": args.crossover_probability,
        "mutation_probability": args.mutation_probability,
        "min_trades_for_prescreening": args.min_trades_for_prescreening,
    }

    # Initialization and launch of genetic search
    finder = GeneticStrategyFinder(
        training_data=training_data_dfs, run_config=run_config
    )

    def progress_callback(data):
        logger.info(
            f"Gen {data['current_generation']}/{data['total_generations']} - "
            f"Best Fitness: {data['best_fitness_so_far']:.4f}, "
            f"Avg Fitness: {data['average_fitness_this_gen']:.4f}"
        )

    # Pass map_function as the first argument
    pool = multiprocessing.Pool(processes=args.max_cores)

    try:
        # Pass pool.map as the first positional argument
        found_strategies = finder.run(
            pool.imap,
            progress_callback=progress_callback,
            checkpoint_file=args.checkpoint_file,
        )
    finally:
        pool.close()
        pool.join()

    # === PHASE 2: FAST VERIFICATION ON TEST ASSETS ===
    if test_asset_paths and found_strategies:
        logger.info("\n--- Starting Phase 2: Fast Verification on Test Assets ---")
        test_data_dfs = load_and_prepare_assets(test_asset_paths)

        verification_results = []
        for i, strategy_data in enumerate(found_strategies):
            strategy_json = strategy_data["strategy_json"]
            strategy_fitness_train = strategy_data["fitness_score"]

            kpis_on_test_assets = []
            for asset_name, df_asset in test_data_dfs.items():
                try:
                    backtester = FastVectorBacktester(df_asset, strategy_json)
                    kpis = backtester.run()
                    kpis_on_test_assets.append(kpis)
                except Exception as e:
                    logger.error(
                        f"FastVectorBacktester failed for strategy {i + 1} on test asset {asset_name}: {e}"
                    )

            # Aggregate results by test assets
            if kpis_on_test_assets:
                avg_pnl_test = np.mean(
                    [k.get("total_pnl_pct", 0.0) for k in kpis_on_test_assets]
                )
                avg_pf_test = np.mean(
                    [
                        k.get("profit_factor", 0.0)
                        for k in kpis_on_test_assets
                        if k.get("profit_factor", 0.0) > 0
                    ]
                )
            else:
                avg_pnl_test = 0.0
                avg_pf_test = 0.0

            verification_results.append(
                {
                    "Rank": i + 1,
                    "Fitness (Train)": strategy_fitness_train,
                    "Avg PNL (Test, %)": avg_pnl_test,
                    "Avg PF (Test)": avg_pf_test,
                }
            )

        logger.info("\n--- Fast Verification Summary ---")
        summary_df = pd.DataFrame(verification_results)
        print(summary_df.to_markdown(index=False))
        print("-" * 75)

    # Saving results
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    logger.info(f"Saving top {len(found_strategies)} strategies to {output_dir}")

    for i, strategy_data in enumerate(found_strategies):
        # Use pathlib to create file paths
        file_basename = f"strategy_{i + 1}_fitness_{strategy_data['fitness_score']:.2f}"
        strategy_json_path = output_dir / f"{file_basename}.json"
        kpis_json_path = output_dir / f"{file_basename}_kpis.json"

        with open(strategy_json_path, "w") as f:
            json.dump(strategy_data["strategy_json"], f, indent=4)
        with open(kpis_json_path, "w") as f:
            json.dump(strategy_data["kpis_json"], f, indent=4)

        logger.info(
            f"Saved strategy {i + 1} with fitness {strategy_data['fitness_score']:.2f}"
        )

    logger.info("Genetic search completed and results saved.")
