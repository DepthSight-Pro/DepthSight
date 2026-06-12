# bot_module/strategy.py
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set, Type, Tuple, Literal, Callable
from enum import Enum
import time
from datetime import datetime, timedelta
import asyncio
from collections import defaultdict
from decimal import Decimal, ROUND_DOWN, ROUND_UP, ROUND_HALF_UP
import pandas as pd
import numpy as np
import sys
import json
import math
import copy

from .strategy_risk import resolve_strategy_risk_override

try:
    from numba import njit

    _NUMBA_AVAILABLE = True
except ImportError:
    njit = None
    _NUMBA_AVAILABLE = False

# Enums and Dataclasses


def format_float_detail(value: Any) -> str:
    if isinstance(value, (int, float)):
        if math.isnan(value) or math.isinf(value):
            return str(value)  # Convert nan/inf to "nan", "inf", "-inf"
        return f"{value:.8f}"
    return "N/A"


def format_optional_price(value: Any) -> str:
    if value is None:
        return "NONE"
    return format_float_detail(value)


def position_uses_no_stop_loss(position: Any) -> bool:
    signal_details = getattr(position, "signal_details", {}) or {}
    details_flag = (
        isinstance(signal_details, dict) and signal_details.get("no_stop_loss") is True
    )
    return bool(getattr(position, "no_stop_loss", False) or details_flag)


def position_has_active_stop(position: Any) -> bool:
    sl_price = getattr(position, "current_sl_price", None)
    return sl_price is not None and sl_price > 0


# Imports
try:
    from bot_module import config
    from .utils import round_price_by_tick
    from .datatypes import (
        BasePosition,
        PartialTarget,
        StrategySignal,
        DensityInfo,
        OrderbookAnalysisResult,
        SignalDirection,
        OrderMode,
    )

    from bot_module.config import DEFAULT_TICK_SIZE
    from bot_module.config import (
        DYNAMIC_SELECTION_REL_VOL_THRESHOLD,
        DYNAMIC_SELECTION_NATR_THRESHOLD,
        DENSITY_NEAR_PROXIMITY_TICKS,
        ORDERBOOK_FOUNDATION_MIN_DENSITY_USD,
        ORDERBOOK_FOUNDATION_LEVELS_TO_CHECK,
        ORDERBOOK_FOUNDATION_MIN_DENSITY_ATR_FACTOR,
        ORDERBOOK_FOUNDATION_USE_ATR_THRESHOLD,
        ORDERBOOK_APPROACH_CANDLES,
        ORDERBOOK_APPROACH_MIN_MOVE_ATR,
    )
except ImportError:  # pragma: no cover
    print(
        "WARN: Cannot import bot_module.config in strategy.py. Using mock config.",
        file=sys.stderr,
    )

    # FALLBACKS FOR ISOLATED TESTING
    if "SignalDirection" not in globals():

        class SignalDirection(Enum):
            LONG = "LONG"
            SHORT = "SHORT"

    if "OrderMode" not in globals():

        class OrderMode(Enum):
            MARKET = "MARKET"
            LIMIT = "LIMIT"
            LIMIT_RETEST = "LIMIT_RETEST"
            LIMIT_BREAK = "LIMIT_BREAK"

    if "OrderbookAnalysisResult" not in globals():

        @dataclass
        class OrderbookAnalysisResult:
            nearest_support: Optional[float] = None
            nearest_resistance: Optional[float] = None
            is_price_near_support: bool = False
            is_price_near_resistance: bool = False
            is_price_approaching_support: bool = False
            is_price_approaching_resistance: bool = False

    if "StrategySignal" not in globals():

        @dataclass
        class StrategySignal:
            symbol: str
            direction: SignalDirection
            trigger_price: float
            stop_loss: Optional[float] = None
            take_profit: Optional[float] = None
            mode: OrderMode = OrderMode.MARKET
            entry_price: Optional[float] = None
            details: Dict[str, Any] = field(default_factory=dict)
            partial_targets: Optional[List] = None
            risk_pct: Optional[float] = None
            risk_usd: Optional[float] = None

    if "BasePosition" not in globals():

        class BasePosition:
            pass

    if "PartialTarget" not in globals():
        PartialTarget = Tuple[float, float, bool]

    class MockConfig:
        LOG_FORMAT = "%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s"
        STRATEGY_DEFAULTS = {}
        DEFAULT_TICK_SIZE = 0.00000001

        @staticmethod
        def get_strategy_param(strategy_name, param_name, default=None):
            return default

        DYNAMIC_SELECTION_REL_VOL_THRESHOLD = 2.0
        DYNAMIC_SELECTION_NATR_THRESHOLD = 1.0
        MIN_DENSITY_USD_THRESHOLD = 500000
        DEPTH_LEVELS_TO_CHECK_FOUNDATION = 5
        DENSITY_PROXIMITY_PCT_FOUNDATION = 0.005
        DENSITY_NEAR_PROXIMITY_TICKS = 3
        ROUND_LEVEL_FOUNDATION_ENABLED = True
        ROUND_LEVEL_PROXIMITY_PCT = 0.002
        ROUND_LEVEL_ATR_MULTIPLIER = 0.1
        ROUND_LEVEL_USE_ATR_PROXIMITY = False
        ROUND_LEVEL_MIN_TICK_PROXIMITY = 5
        ROUND_LEVEL_MAX_LEVELS_TO_CHECK_PER_STEP_TYPE = 2
        ROUND_LEVEL_STEP_DEFINITIONS = []
        MIN_PARTIAL_TP_DISTANCE_PCT = 0.004
        ADAPT_SL_TO_ORDERBOOK_ENABLED = True
        ADAPT_TP_TO_ORDERBOOK_ENABLED = True
        ORDERBOOK_ADAPT_MAX_OFFSET_ATR = 0.5
        ORDERBOOK_ADAPT_MIN_DENSITY_DISTANCE_ATR = 0.3
        ORDERBOOK_ADAPT_SL_TICKS_BEHIND_DENSITY = 5
        ORDERBOOK_ADAPT_TP_TICKS_BEFORE_DENSITY = 5
        ORDERBOOK_FOUNDATION_MIN_DENSITY_USD = 100000
        ORDERBOOK_FOUNDATION_LEVELS_TO_CHECK = 5
        ORDERBOOK_FOUNDATION_MIN_DENSITY_ATR_FACTOR = 10.0
        ORDERBOOK_FOUNDATION_USE_ATR_THRESHOLD = False
        ORDERBOOK_APPROACH_CANDLES = 3
        ORDERBOOK_APPROACH_MIN_MOVE_ATR = 0.25
        ALLOW_SHORT_POSITIONS = False
        FOUNDATION_WEIGHTS = {}
        MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD = 50.0
        OB_CONFLICT_PROXIMITY_TICKS = 2
        USE_COMPANION_ORDERBOOK_ANALYSIS = True

    @dataclass
    class DensityInfo:
        price: float
        size_usd: float
        distance_from_current_price_abs: float
        side: str
        distance_from_current_price_atr: Optional[float] = None

        def get_strategy_param(self, strategy_name, param_name, default=None):
            # Try to get from self.STRATEGY_DEFAULTS first
            val_from_dict = self.STRATEGY_DEFAULTS.get(strategy_name, {}).get(
                param_name
            )
            if val_from_dict is not None:
                return val_from_dict

            # Fallback to hardcoded defaults ONLY if not in STRATEGY_DEFAULTS for this specific strategy
            if strategy_name == "FirstPullbacksInTrend":
                if param_name == "sma_fast_period":
                    return 10
                if param_name == "sma_slow_period":
                    return 50
                if param_name == "rsi_period":
                    return 14
                if param_name == "rsi_lower_bound":
                    return 30
                if param_name == "rsi_upper_bound":
                    return 70

            if strategy_name in ["ReverseVolumeBreakout", "ReverseFakeBreakout"]:
                if param_name == "reverse_sl_to_tp_ratio":
                    return 2.0

            return default  # Final fallback to the provided default argument

    config = MockConfig()

    def round_price_by_tick(price, tick_size, rounding_mode):
        return price  # Dummy func

    DEFAULT_TICK_SIZE = config.DEFAULT_TICK_SIZE
    DYNAMIC_SELECTION_REL_VOL_THRESHOLD = config.DYNAMIC_SELECTION_REL_VOL_THRESHOLD
    DYNAMIC_SELECTION_NATR_THRESHOLD = config.DYNAMIC_SELECTION_NATR_THRESHOLD
    DENSITY_NEAR_PROXIMITY_TICKS = config.DENSITY_NEAR_PROXIMITY_TICKS
    ORDERBOOK_FOUNDATION_MIN_DENSITY_USD = config.ORDERBOOK_FOUNDATION_MIN_DENSITY_USD
    ORDERBOOK_FOUNDATION_LEVELS_TO_CHECK = config.ORDERBOOK_FOUNDATION_LEVELS_TO_CHECK
    ORDERBOOK_FOUNDATION_MIN_DENSITY_ATR_FACTOR = (
        config.ORDERBOOK_FOUNDATION_MIN_DENSITY_ATR_FACTOR
    )
    ORDERBOOK_FOUNDATION_USE_ATR_THRESHOLD = (
        config.ORDERBOOK_FOUNDATION_USE_ATR_THRESHOLD
    )
    ORDERBOOK_APPROACH_CANDLES = config.ORDERBOOK_APPROACH_CANDLES
    ORDERBOOK_APPROACH_MIN_MOVE_ATR = config.ORDERBOOK_APPROACH_MIN_MOVE_ATR


logger = logging.getLogger("bot_module.strategy")
if not logger.hasHandlers():  # pragma: no cover
    if not logging.getLogger("bot_module").hasHandlers():
        logger.addHandler(logging.NullHandler())


@dataclass(frozen=True)
class CompiledConditionNode:
    node_id: str
    node_type: Optional[str]
    params: Dict[str, Any]
    analysis_level: str
    children: Tuple["CompiledConditionNode", ...] = ()
    checker: Optional[Callable[..., Tuple[bool, Dict[str, Any]]]] = None
    evaluator: Optional[Callable[..., Tuple[bool, Dict[str, Any]]]] = None


def _should_use_numba_orderbook() -> bool:
    return _NUMBA_AVAILABLE and bool(getattr(config, "ENABLE_NUMBA_ORDERBOOK", True))


def _depth_levels_to_numpy(
    levels: Any, max_levels: int
) -> Tuple[np.ndarray, np.ndarray]:
    if not isinstance(levels, list) or not levels or max_levels <= 0:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)

    limit = min(len(levels), max_levels)
    prices = np.empty(limit, dtype=np.float64)
    qtys = np.empty(limit, dtype=np.float64)
    n = 0
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
        prices[n] = price
        qtys[n] = qty
        n += 1
    return prices[:n], qtys[:n]


def _first_density_idx_py(
    prices: np.ndarray,
    qtys: np.ndarray,
    min_notional: float,
    current_price: float,
    want_support: bool,
) -> int:
    for i in range(prices.shape[0]):
        price = prices[i]
        notional = price * qtys[i]
        if notional < min_notional:
            continue
        if want_support:
            if price >= current_price:
                continue
        elif price <= current_price:
            continue
        return i
    return -1


def _first_large_order_idx_py(
    prices: np.ndarray, qtys: np.ndarray, min_notional: float
) -> int:
    for i in range(prices.shape[0]):
        if prices[i] * qtys[i] >= min_notional:
            return i
    return -1


if _NUMBA_AVAILABLE:

    @njit(cache=True)
    def _first_density_idx_numba(
        prices: np.ndarray,
        qtys: np.ndarray,
        min_notional: float,
        current_price: float,
        want_support_flag: int,
    ) -> int:
        for i in range(prices.shape[0]):
            price = prices[i]
            notional = price * qtys[i]
            if notional < min_notional:
                continue
            if want_support_flag == 1:
                if price >= current_price:
                    continue
            elif price <= current_price:
                continue
            return i
        return -1

    @njit(cache=True)
    def _first_large_order_idx_numba(
        prices: np.ndarray, qtys: np.ndarray, min_notional: float
    ) -> int:
        for i in range(prices.shape[0]):
            if prices[i] * qtys[i] >= min_notional:
                return i
        return -1


def _build_first_density(
    levels: Any,
    *,
    max_levels: int,
    min_notional: float,
    current_price: float,
    want_support: bool,
) -> Optional[DensityInfo]:
    prices, qtys = _depth_levels_to_numpy(levels, max_levels=max_levels)
    if prices.size == 0:
        return None

    if _should_use_numba_orderbook():
        idx = _first_density_idx_numba(
            prices,
            qtys,
            float(min_notional),
            float(current_price),
            1 if want_support else 0,
        )
    else:
        idx = _first_density_idx_py(
            prices, qtys, float(min_notional), float(current_price), want_support
        )

    if idx < 0:
        return None

    price = float(prices[idx])
    notional = float(price * qtys[idx])
    return DensityInfo(
        price=price,
        size_usd=notional,
        distance_from_current_price_abs=abs(current_price - price),
        side="bid" if want_support else "ask",
    )


def _find_first_large_order(
    levels: Any, *, min_notional: float, max_levels: int
) -> Tuple[bool, Optional[float], Optional[float], int]:
    prices, qtys = _depth_levels_to_numpy(levels, max_levels=max_levels)
    if prices.size == 0:
        return False, None, None, 0

    if _should_use_numba_orderbook():
        idx = _first_large_order_idx_numba(prices, qtys, float(min_notional))
    else:
        idx = _first_large_order_idx_py(prices, qtys, float(min_notional))

    if idx < 0:
        return False, None, None, int(prices.size)

    price = float(prices[idx])
    notional = float(price * qtys[idx])
    return True, price, notional, int(prices.size)


# Adding a new base type
FOUNDATION_RETURN_TO_LEVEL = "return_to_level"
FOUNDATION_TAPE_ACCELERATION = "tape_acceleration"
FOUNDATION_MARKET_ACTIVITY = "market_activity"
FOUNDATION_LEVEL = "level"
FOUNDATION_PATTERN = "pattern"
FOUNDATION_VOLUME_CONFIRMATION = "volume_confirmation"
FOUNDATION_ORDERBOOK = "orderbook"
FOUNDATION_TREND = "trend"
FOUNDATION_ROUND_NUMBER = "round_number_level"


# AI_CONTEXT_START: _check_foundation_orderbook
def _check_foundation_orderbook(
    pair_info: Dict[str, Any],
    market_data: Dict[str, Any],
    min_density_usd: float,
    levels_to_check: int,
    use_analysis: bool,
    conflict_ticks: int,
    near_ticks: int,
    side: str = "any",
) -> OrderbookAnalysisResult:
    """Analyzes order books and returns the result."""
    depth_trading = market_data.get("depth_trading")
    depth_analysis = market_data.get("depth_analysis")

    result = OrderbookAnalysisResult()
    last_price = pair_info.get("last_price")
    tick_size = pair_info.get("tick_size")
    if not last_price or not tick_size:
        return result

    s_trading, r_trading = None, None
    s_analysis, r_analysis = None, None

    if isinstance(depth_trading, dict):
        if side in ["any", "support"]:
            s_trading = _build_first_density(
                depth_trading.get("bids"),
                max_levels=levels_to_check,
                min_notional=min_density_usd,
                current_price=last_price,
                want_support=True,
            )
        if side in ["any", "resistance"]:
            r_trading = _build_first_density(
                depth_trading.get("asks"),
                max_levels=levels_to_check,
                min_notional=min_density_usd,
                current_price=last_price,
                want_support=False,
            )

    if use_analysis and isinstance(depth_analysis, dict):
        if side in ["any", "support"]:
            s_analysis = _build_first_density(
                depth_analysis.get("bids"),
                max_levels=levels_to_check,
                min_notional=min_density_usd,
                current_price=last_price,
                want_support=True,
            )
        if side in ["any", "resistance"]:
            r_analysis = _build_first_density(
                depth_analysis.get("asks"),
                max_levels=levels_to_check,
                min_notional=min_density_usd,
                current_price=last_price,
                want_support=False,
            )

    final_support = s_trading
    final_resistance = r_trading

    if (
        final_support
        and r_analysis
        and abs(final_support.price - r_analysis.price) <= conflict_ticks * tick_size
    ):
        final_support = None

    if (
        final_resistance
        and s_analysis
        and abs(final_resistance.price - s_analysis.price) <= conflict_ticks * tick_size
    ):
        final_resistance = None

    if not final_support:
        final_support = s_analysis

    if not final_resistance:
        final_resistance = r_analysis

    result.nearest_support = final_support
    result.nearest_resistance = final_resistance
    if (
        final_support
        and abs(last_price - final_support.price) <= near_ticks * tick_size
    ):
        result.is_price_near_support = True

    if (
        final_resistance
        and abs(last_price - final_resistance.price) <= near_ticks * tick_size
    ):
        result.is_price_near_resistance = True

    return result


# AI_CONTEXT_END


def _generate_round_levels(
    last_price: float,
    tick_size: float,
    step_definitions_config: List[Dict[str, Any]],
    max_check_per_step_type: int,
    order_multipliers_override: Optional[List[float]] = None,
    max_orders_scan_override: Optional[int] = None,
) -> List[float]:
    candidate_levels = set()
    if last_price <= 0 or tick_size <= 0:
        return []
    if step_definitions_config:
        applicable_steps = []
        for config_item in sorted(
            step_definitions_config, key=lambda x: x.get("min_price", 0), reverse=True
        ):
            if last_price >= config_item.get("min_price", 0):
                applicable_steps = config_item.get("steps", [])
                break
        if not applicable_steps and step_definitions_config:
            applicable_steps = step_definitions_config[-1].get("steps", [])
        for step_val in applicable_steps:
            if step_val <= 0:
                continue
            try:
                actual_step_dec = Decimal(str(step_val))
                tick_size_dec = Decimal(str(tick_size))
                actual_step_dec = (actual_step_dec / tick_size_dec).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                ) * tick_size_dec
                actual_step_dec = max(actual_step_dec, tick_size_dec)
                actual_step = float(actual_step_dec)
                if actual_step <= 1e-9:
                    continue
                last_price_dec = Decimal(str(last_price))
                level_ref_dec = (last_price_dec / Decimal(str(actual_step))).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                ) * Decimal(str(actual_step))
                for k in range(-max_check_per_step_type, max_check_per_step_type + 1):
                    level_dec = level_ref_dec + Decimal(str(k)) * Decimal(
                        str(actual_step)
                    )
                    final_level = round_price_by_tick(
                        float(level_dec), tick_size, rounding_mode=ROUND_HALF_UP
                    )
                    if final_level is not None and final_level > 0:
                        candidate_levels.add(final_level)
            except Exception as e_step_gen:
                logger.warning(
                    f"[_generate_round_levels step-based] Error for step {step_val}: {e_step_gen}"
                )
                continue
    order_multipliers = (
        order_multipliers_override
        if order_multipliers_override is not None
        else [
            0.1,
            0.125,
            0.15,
            0.2,
            0.25,
            0.3,
            0.4,
            0.5,
            0.6,
            0.7,
            0.75,
            0.8,
            0.9,
            1.0,
            1.25,
            1.5,
            1.75,
            2.0,
            2.5,
            3.0,
            4.0,
            5.0,
            6.0,
            7.0,
            7.5,
            8.0,
            9.0,
            10.0,
        ]
    )
    max_orders_scan = (
        max_orders_scan_override if max_orders_scan_override is not None else 1
    )
    try:
        order_of_magnitude_price = (
            10 ** math.floor(math.log10(last_price)) if last_price >= 1e-9 else 1e-8
        )
        for i in range(-max_orders_scan, max_orders_scan + 1):
            current_order_base = order_of_magnitude_price * (10**i)
            if current_order_base <= 1e-9:
                continue
            for multiplier in order_multipliers:
                raw_level = current_order_base * multiplier
                if current_order_base >= 1:
                    precision_digits = 2
                elif current_order_base >= 0.01:
                    precision_digits = max(4, -int(math.floor(math.log10(tick_size))))
                else:
                    precision_digits = max(8, -int(math.floor(math.log10(tick_size))))
                try:
                    raw_level_dec = Decimal(str(raw_level))
                    quantizer = Decimal("1e-" + str(precision_digits))
                    rounded_intermediate_level_dec = raw_level_dec.quantize(
                        quantizer, rounding=ROUND_HALF_UP
                    )
                    rounded_intermediate_level = float(rounded_intermediate_level_dec)
                    final_level = round_price_by_tick(
                        rounded_intermediate_level,
                        tick_size,
                        rounding_mode=ROUND_HALF_UP,
                    )
                    if final_level is not None and final_level > 0:
                        candidate_levels.add(final_level)
                except Exception:
                    continue  # pragma: no cover
    except Exception as e_order_calc:
        logger.error(
            f"[_generate_round_levels order-based] Error calculating order of magnitude for price {last_price}: {e_order_calc}"
        )
    return sorted(list(candidate_levels))


# AI_CONTEXT_START: _check_foundation_round_number_level
def _check_foundation_round_number_level(
    pair_info: Dict[str, Any],
    market_data: Dict[str, Any],
    enabled: bool,
    proximity_pct: float,
    atr_multiplier: float,
    use_atr: bool,
    min_tick_prox: int,
    max_check_per_step: int,
    step_definitions: List[Dict[str, Any]],
    order_multipliers_cfg: Optional[List[float]],
    max_orders_scan_cfg: Optional[int],
) -> bool:
    """
    Checks if the current price is near a "round" numerical level.
    Round levels are generated based on powers of 10 and standard steps.

    Parameters in 'params' (when called from JSON):
    - proximity_pips (int): Proximity to the level in pips (ticks). Example: 5.
    """
    if not enabled:
        return False
    symbol = pair_info.get("symbol", "Unknown")
    log_prefix = f"[{symbol}:F_RoundNum]"
    last_price = pair_info.get("last_price")
    tick_size = pair_info.get("tick_size")
    atr = pair_info.get("atr")
    if last_price is None or last_price <= 0 or tick_size is None or tick_size <= 0:
        logger.warning(f"{log_prefix} Invalid last_price or tick_size.")
        return False

    candidate_round_levels = _generate_round_levels(
        last_price,
        tick_size,
        step_definitions,
        max_check_per_step,
        order_multipliers_cfg,
        max_orders_scan_cfg,
    )
    if not candidate_round_levels:
        return False
    for round_level in candidate_round_levels:
        min_abs_tolerance_by_tick = min_tick_prox * tick_size
        if use_atr and atr is not None and atr > 0:
            tolerance_abs = atr * atr_multiplier
        else:
            tolerance_abs = round_level * proximity_pct
        final_tolerance = max(tolerance_abs, min_abs_tolerance_by_tick)
        if abs(last_price - round_level) <= final_tolerance:
            logger.info(
                f"{log_prefix} Price {last_price:.8f} IS NEAR round level {round_level:.8f} (Tolerance: {final_tolerance:.8f})"
            )
            return True
    return False


# AI_CONTEXT_END


# AI_CONTEXT_START: find_significant_levels
def find_significant_levels(
    market_data: Dict[str, Any],
    lookback_config: Optional[Dict[str, int]] = None,
    current_timestamp_dt: Optional[datetime] = None,
) -> Dict[str, List[float]]:
    """
    Finds significant levels (high/low) based on the provided configuration.
    FIXED VERSION: Correctly handles data slices for local and significant levels.
    """
    # We want to collect both named levels (daily_high, etc.) and a general list of all levels
    # from all available timeframes for the widest possible check.
    resolved_named = resolve_significant_levels(market_data, current_timestamp_dt)

    levels = {
        level_type: [level] if level is not None and level > 0 else []
        for level_type, level in resolved_named.items()
    }

    # Initialize base lists if they don't exist yet
    if "high" not in levels:
        levels["high"] = []
    if "low" not in levels:
        levels["low"] = []

    # Determine if the call was for local_level (with config) or for significant_level (without config)
    is_local_level_call = lookback_config is not None
    config_to_use = lookback_config

    # For significant_level, use the default config
    if not is_local_level_call:
        config_to_use = {
            "kline_1d": 2,  # Including yesterday
            "kline_4h": 7 * 6,
            "kline_1h": 24,
        }

    def get_idx_for_ts(df, ts):
        if ts is None or not isinstance(df.index, pd.DatetimeIndex):
            return len(df) - 1
        try:
            if not df.index.is_monotonic_increasing:
                return len(df) - 1
            ts = pd.Timestamp(ts)
            if df.index.tz is None and ts.tz is not None:
                ts = ts.tz_convert(None)
            elif df.index.tz is not None:
                ts = (
                    ts.tz_localize(df.index.tz)
                    if ts.tz is None
                    else ts.tz_convert(df.index.tz)
                )
            idx = df.index.get_indexer([ts], method="ffill")[0]
            return int(idx) if idx != -1 else len(df) - 1
        except Exception:
            return len(df) - 1

    kline_data_sources = {
        key: df
        for key, df in market_data.items()
        if key.startswith("kline_") and isinstance(df, pd.DataFrame) and not df.empty
    }

    if config_to_use:
        for tf_key, num_candles in config_to_use.items():
            df = kline_data_sources.get(tf_key)
            if df is not None and not df.empty:
                current_idx_tf = get_idx_for_ts(df, current_timestamp_dt)

                # DIFFERENT LOGIC FOR TWO SCENARIOS
                if is_local_level_call:
                    # For local_level, look at candles STRICTLY BEFORE the current one.
                    lookback_end_idx = current_idx_tf
                else:
                    # For significant_level, we want to include the last closed candle (e.g., yesterday's).
                    # current_idx_tf is its index. To make iloc include it, +1 is needed.
                    lookback_end_idx = current_idx_tf + 1

                lookback_start_idx = max(0, lookback_end_idx - num_candles)

                if lookback_end_idx > lookback_start_idx:
                    try:
                        # iloc does not include the right boundary, so our logic is now correct
                        recent_candles = df.iloc[lookback_start_idx:lookback_end_idx]
                        if not recent_candles.empty:
                            # We consider the window extremum as the level, not every candle shadow within the range.
                            if "high" in recent_candles.columns:
                                highs = recent_candles["high"].dropna().astype(float)
                                if not highs.empty:
                                    levels["high"].append(float(highs.max()))
                            if "low" in recent_candles.columns:
                                lows = recent_candles["low"].dropna().astype(float)
                                if not lows.empty:
                                    levels["low"].append(float(lows.min()))
                    except (IndexError, KeyError, ValueError, TypeError) as e:
                        logger.warning(
                            f"[FindLevels] Error getting levels for {tf_key} from {lookback_start_idx} to {lookback_end_idx}: {e}"
                        )

    levels["high"] = sorted(
        list(set(lvl for lvl in levels["high"] if lvl > 0)), reverse=True
    )
    levels["low"] = sorted(list(set(lvl for lvl in levels["low"] if lvl > 0)))
    return levels


# AI_CONTEXT_END


# AI_CONTEXT_START: _get_idx_for_timestamp
def _get_idx_for_timestamp(df: pd.DataFrame, ts: Optional[datetime]) -> int:
    if ts is None or not isinstance(df.index, pd.DatetimeIndex):
        return len(df) - 1
    try:
        if not df.index.is_monotonic_increasing:
            return len(df) - 1
        ts = pd.Timestamp(ts)
        if df.index.tz is None and ts.tz is not None:
            ts = ts.tz_convert(None)
        elif df.index.tz is not None:
            ts = (
                ts.tz_localize(df.index.tz)
                if ts.tz is None
                else ts.tz_convert(df.index.tz)
            )
        idx = df.index.get_indexer([ts], method="ffill")[0]
        return int(idx) if idx != -1 else len(df) - 1
    except Exception:
        return len(df) - 1


# AI_CONTEXT_END


def _get_recent_closed_candles(
    df: Optional[pd.DataFrame],
    num_candles: int,
    current_timestamp_dt: Optional[datetime] = None,
    include_current: bool = False,
) -> pd.DataFrame:
    if df is None or df.empty or num_candles <= 0:
        return pd.DataFrame()

    current_idx = _get_idx_for_timestamp(df, current_timestamp_dt)

    # Logic for selecting the end index
    # If include_current=True (e.g., for significant levels), we include the current candle.
    # If False (standard for filters), we look only at STRICTLY closed candles before the current one.
    lookback_end_idx = current_idx + (1 if include_current else 0)
    lookback_start_idx = max(0, lookback_end_idx - num_candles)

    if lookback_end_idx <= lookback_start_idx:
        return pd.DataFrame(columns=df.columns)

    try:
        return df.iloc[lookback_start_idx:lookback_end_idx]
    except (IndexError, KeyError, ValueError, TypeError) as e:
        logger.warning(
            f"[FindLevels] Error getting candles for window {lookback_start_idx}:{lookback_end_idx}: {e}"
        )
        return pd.DataFrame(columns=df.columns)


def resolve_significant_levels(
    market_data: Dict[str, Any],
    current_timestamp_dt: Optional[datetime] = None,
) -> Dict[str, Optional[float]]:
    """
    Returns a snapshot of significant levels corresponding to the UI parameter `level_type`.

    Source priority:
    - daily_*: 1D -> 4H (6 candles) -> 1H (24 candles)
    - weekly_*: 1D (7 candles) -> 4H (42 candles) -> 1H (168 candles)
    """
    kline_data_sources = {
        key: df
        for key, df in market_data.items()
        if key.startswith("kline_") and isinstance(df, pd.DataFrame) and not df.empty
    }

    level_windows: Dict[str, List[Tuple[str, int, str]]] = {
        "daily_high": [
            ("kline_1d", 1, "high"),
            ("kline_4h", 6, "high"),
            ("kline_1h", 24, "high"),
        ],
        "daily_low": [
            ("kline_1d", 1, "low"),
            ("kline_4h", 6, "low"),
            ("kline_1h", 24, "low"),
        ],
        "weekly_high": [
            ("kline_1d", 7, "high"),
            ("kline_4h", 42, "high"),
            ("kline_1h", 168, "high"),
        ],
        "weekly_low": [
            ("kline_1d", 7, "low"),
            ("kline_4h", 42, "low"),
            ("kline_1h", 168, "low"),
        ],
    }

    resolved_levels: Dict[str, Optional[float]] = {key: None for key in level_windows}

    for level_type, candidates in level_windows.items():
        for tf_key, num_candles, column in candidates:
            recent_candles = _get_recent_closed_candles(
                kline_data_sources.get(tf_key),
                num_candles,
                current_timestamp_dt,
                # include_current=False (Default for named levels like "Yesterday's high")
            )
            if recent_candles.empty or column not in recent_candles.columns:
                continue

            source_series = recent_candles[column].dropna().astype(float)
            if source_series.empty:
                continue

            resolved_levels[level_type] = (
                float(source_series.max())
                if column == "high"
                else float(source_series.min())
            )
            break

    return resolved_levels


def find_local_levels(
    market_data: Dict[str, Any],
    params: Dict[str, Any],
    current_timestamp_dt: Optional[datetime] = None,
) -> Dict[str, List[float]]:
    """
    Finds local levels (high/low) based on parameters from the request.
    """
    lookback_period = params.get("lookback_period", 20)
    timeframe = params.get("timeframe", "1m")
    kline_key = f"kline_{timeframe}"

    lookback_config = {kline_key: lookback_period}

    # We can simply call find_significant_levels with the required configuration
    # as the logic for finding the maximum/minimum for the period is identical.
    # Pass is_default_call=False so that daily levels are not added.
    levels = find_significant_levels(market_data, lookback_config, current_timestamp_dt)
    return _filter_local_levels_by_type(levels, params.get("level_type", "all"))


def _normalize_local_level_type(level_type: Any) -> str:
    normalized = str(level_type or "all").strip().lower()
    aliases = {
        "any": "all",
        "both": "all",
        "max": "high",
        "maximum": "high",
        "highs": "high",
        "hi": "high",
        "min": "low",
        "minimum": "low",
        "lows": "low",
        "lo": "low",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in {"all", "high", "low"} else "all"


def _filter_local_levels_by_type(
    levels: Dict[str, List[float]], level_type: Any
) -> Dict[str, List[float]]:
    selected_type = _normalize_local_level_type(level_type)
    if selected_type == "high":
        return {"high": levels.get("high", []), "low": []}
    if selected_type == "low":
        return {"high": [], "low": levels.get("low", [])}
    return {"high": levels.get("high", []), "low": levels.get("low", [])}


def find_consolidation_zones(
    market_data: Dict[str, Any], params: Dict[str, Any], main_df: pd.DataFrame
) -> List[Dict[str, Any]]:
    """
    Finds consolidation zones ("shelves") on the chart.
    FINAL VERSION: Resistant to SettingWithCopyWarning.
    """
    lookback_period = int(params.get("lookback_period", 10))
    max_range_atr = float(params.get("max_range_atr", 0.8))

    # 1. Select DataFrame based on the requested timeframe
    target_tf = params.get("timeframe")
    if target_tf and f"kline_{target_tf}" in market_data:
        df = market_data[f"kline_{target_tf}"].copy()
    else:
        df = main_df.copy()

    # Step 1: Ensure ATR is present in the DataFrame. If not - calculate it.
    # Use a longer period (100) for stability on lower TFs
    if "atr" not in df.columns or df["atr"].isnull().all():
        tr = pd.DataFrame(index=df.index)
        tr["h-l"] = df["high"] - df["low"]
        tr["h-pc"] = abs(df["high"] - df["close"].shift())
        tr["l-pc"] = abs(df["low"] - df["close"].shift())
        tr["tr"] = tr[["h-l", "h-pc", "l-pc"]].max(axis=1)
        df["atr"] = tr["tr"].ewm(span=100, adjust=False).mean()
        df["atr"] = df["atr"].bfill()

    # Step 2: Create a consolidation "map"
    # Using the maximum and minimum of candle BODIES to ignore false breakouts (wicks)
    body_max = df[["open", "close"]].max(axis=1)
    body_min = df[["open", "close"]].min(axis=1)

    rolling_high = body_max.rolling(window=lookback_period).max()
    rolling_low = body_min.rolling(window=lookback_period).min()
    price_range = rolling_high - rolling_low

    atr_threshold = df["atr"] * max_range_atr

    is_consolidating = price_range <= atr_threshold

    # Step 3: Find consolidation blocks considering price boundaries
    zones = []

    for i in range(len(is_consolidating)):
        if not is_consolidating.iloc[i]:
            continue

        current_ts = is_consolidating.index[i]
        top_p = float(rolling_high.iloc[i])
        bottom_p = float(rolling_low.iloc[i])

        # Determining the start of the consolidation window (lookback_period back)
        window_start_idx = max(0, i - lookback_period + 1)
        window_start_ts = is_consolidating.index[window_start_idx]

        # Trying to merge with the previous zone.
        # MAIN RULE: The total height of the entire merged zone cannot exceed the ATR threshold,
        # And zones must follow each other TIGHTLY (without gaps in time).
        is_merged = False
        if zones:
            last_zone = zones[-1]

            # Checking time gap (for 1m candles, a gap > 65 sec is already a new zone)
            # We take 65 seconds to account for micro-delays but cut off gaps of 1+ minute.
            time_gap = int(current_ts.timestamp()) - last_zone["end_time"]

            if time_gap <= 65:
                # Calculate what the zone height will become if we add the current candle to it
                combined_top = max(last_zone["top_price"], top_p)
                combined_bottom = min(last_zone["bottom_price"], bottom_p)
                combined_range = combined_top - combined_bottom

                # If the total height is still within the allowed ATR — merging
                if combined_range <= atr_threshold.iloc[i]:
                    last_zone["end_time"] = int(current_ts.timestamp())
                    last_zone["top_price"] = combined_top
                    last_zone["bottom_price"] = combined_bottom
                    is_merged = True

        if not is_merged:
            # If it didn't fit into the old zone or it doesn't exist — create a new separate shelf
            zones.append(
                {
                    "start_time": int(window_start_ts.timestamp()),
                    "end_time": int(current_ts.timestamp()),
                    "top_price": top_p,
                    "bottom_price": bottom_p,
                    "type": "price_consolidation",
                    "label": "CONSOLIDATION",
                }
            )

    # Final cleanup: keep only those zones that are actually shelves (length > lookback)
    return [
        z for z in zones if (z["end_time"] - z["start_time"]) >= (lookback_period * 40)
    ]


def find_trend_zones(
    market_data: Dict[str, Any], params: Dict[str, Any], main_df: pd.DataFrame
) -> List[Dict[str, Any]]:
    """
    Finds and returns trend zones (LONG/SHORT) on the chart using pre-calculated indicators.
    Returns a list of dictionaries ready for the Pydantic schema VisualizationZone.
    """
    zones = []
    sma_fast_period = int(params.get("sma_fast_period", 10))
    sma_slow_period = int(params.get("sma_slow_period", 50))
    rsi_period = int(params.get("rsi_period", 14))
    rsi_lower_bound = float(params.get("rsi_lower_bound", 40))
    rsi_upper_bound = float(params.get("rsi_upper_bound", 60))

    # 0. Select DataFrame based on the requested timeframe
    target_tf = params.get("timeframe")
    df = (
        market_data.get(f"kline_{target_tf}", main_df).copy()
        if target_tf
        else main_df.copy()
    )

    # 1. Checking that all necessary indicator columns exist in the DataFrame.
    sma_fast_col = f"SMA_{sma_fast_period}"
    sma_slow_col = f"SMA_{sma_slow_period}"
    rsi_col = f"RSI_{rsi_period}"

    required_cols = [sma_fast_col, sma_slow_col, rsi_col]

    # If indicators are not yet calculated on the target TF, calculate them
    if not all(col in df.columns for col in required_cols):
        if sma_fast_period > 0:
            df[sma_fast_col] = df["close"].rolling(window=sma_fast_period).mean()
        if sma_slow_period > 0:
            df[sma_slow_col] = df["close"].rolling(window=sma_slow_period).mean()
        if rsi_period > 0:
            delta = df["close"].diff()
            gain = (
                (delta.where(delta > 0, 0)).ewm(com=rsi_period - 1, adjust=False).mean()
            )
            loss = (
                (-delta.where(delta < 0, 0))
                .ewm(com=rsi_period - 1, adjust=False)
                .mean()
            )
            rs = gain / loss
            df[rsi_col] = 100 - (100 / (1 + rs))

    # 2. Determine the trend state for each candle using np.select
    conditions = [
        ((df[sma_fast_col] > df[sma_slow_col]) & (df[rsi_col] > rsi_upper_bound)),
        ((df[sma_fast_col] < df[sma_slow_col]) & (df[rsi_col] < rsi_lower_bound)),
    ]
    choices = ["trend_long", "trend_short"]
    df["trend_state"] = np.select(conditions, choices, default="flat")

    # 3. Find continuous groups with the same trend state
    df["trend_group"] = (df["trend_state"] != df["trend_state"].shift()).cumsum()

    # 4. Grouping and creating zones
    for group_num, group_df in df.groupby("trend_group"):
        state = group_df["trend_state"].iloc[0]

        # We are only interested in zones with a trend, not 'flat'
        if state in ["trend_long", "trend_short"] and len(group_df) > 1:
            start_time = int(group_df.index.min().timestamp())

            # Zone end is the END TIME of the last candle in the group
            last_candle_start_time = group_df.index.max()
            # Trying to determine the candle duration
            candle_duration = pd.Timedelta(minutes=1)  # Fallback
            if len(df.index) > 1:
                candle_duration = df.index[1] - df.index[0]

            end_time = int((last_candle_start_time + candle_duration).timestamp())

            # 5. Form a dictionary in the correct format
            zones.append(
                {
                    "start_time": start_time,
                    "end_time": end_time,
                    "type": "trend_direction",  # General type for all trend zones
                    "label": f"Trend {state.split('_')[1].capitalize()}",  # "Trend Long" or "Trend Short"
                }
            )

    return zones


def find_squeeze_zones(
    market_data: Dict[str, Any], params: Dict[str, Any], main_df: pd.DataFrame
) -> List[Dict[str, Any]]:
    """
    Finds volatility "squeeze" periods on the chart.
    """
    zones = []
    lookback = int(params.get("lookback_period", params.get("lookback_candles", 20)))
    squeeze_ratio = float(params.get("squeeze_ratio", 0.6))
    half = max(2, lookback // 2)

    target_tf = params.get("timeframe")
    df = (
        market_data.get(f"kline_{target_tf}", main_df).copy()
        if target_tf
        else main_df.copy()
    )

    if len(df) < lookback:
        return []

    # Vectorized squeeze check
    rolling_max = df["high"].rolling(half).max()
    rolling_min = df["low"].rolling(half).min()
    rolling_mean = df["close"].rolling(half).mean()

    # Avoiding division by zero
    rolling_mean_safe = rolling_mean.replace(0, np.nan)
    range_pct = (rolling_max - rolling_min) / rolling_mean_safe * 100.0

    # past_range_pct - range of the PREVIOUS half of the window
    past_range = range_pct.shift(half)
    # current_range_pct - range of the CURRENT half of the window
    current_range = range_pct

    is_squeezing = (past_range > 0) & (current_range <= past_range * squeeze_ratio)

    df["is_squeezing"] = is_squeezing.fillna(False)
    # Grouping consecutive candles with compression
    df["squeeze_group"] = (df["is_squeezing"] != df["is_squeezing"].shift()).cumsum()

    for _, group_df in df.groupby("squeeze_group"):
        if group_df["is_squeezing"].iloc[0]:
            start_time = int(group_df.index.min().timestamp())

            last_candle_start_time = group_df.index.max()
            candle_duration = pd.Timedelta(minutes=1)
            if len(df.index) > 1:
                candle_duration = df.index[1] - df.index[0]

            end_time = int((last_candle_start_time + candle_duration).timestamp())

            zones.append(
                {
                    "start_time": start_time,
                    "end_time": end_time,
                    "type": "volatility_squeeze",
                    "label": "Volatility Squeeze",
                    "color": "rgba(255, 255, 0, 0.3)",  # Yellow for compression
                }
            )

    return zones


def find_level_touch_visuals(
    market_data: Dict[str, Any], params: Dict[str, Any], main_df: pd.DataFrame
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Finds touches of a specific level on the chart considering all trading block parameters.
    """
    levels = []
    markers = []

    level_price = float(params.get("level_source", params.get("level_price", 0)))
    if level_price <= 0:
        return {"levels": [], "markers": []}

    lookback = int(params.get("lookback_candles", 100))
    tolerance_pct = float(params.get("touch_tolerance_pct", 0.1))
    tolerance = level_price * (tolerance_pct / 100.0)
    invalidate_on_pierce = bool(params.get("invalidate_on_pierce", True))

    target_tf = params.get("timeframe")
    df = (
        market_data.get(f"kline_{target_tf}", main_df).copy()
        if target_tf
        else main_df.copy()
    )

    recent_df = df.tail(lookback)
    if recent_df.empty:
        return {"levels": [], "markers": []}

    # Drawing the level itself
    levels.append(
        {
            "time": int(recent_df.index[0].timestamp()),
            "price": level_price,
            "type": "level_touch_analyzer",
            "label": f"LVL {level_price}",
        }
    )

    # Determining the level side (support or resistance) for breakout (pierce) logic
    close_series = recent_df["close"]
    level_side = (
        "resistance" if float(close_series.median()) <= level_price else "support"
    )

    touch_indices = []
    pierce_indices = []

    # Finding touches and breakouts
    for i in range(len(recent_df)):
        row = recent_df.iloc[i]
        ts = recent_df.index[i]
        high = float(row["high"])
        low = float(row["low"])

        is_touch = high >= level_price - tolerance and low <= level_price + tolerance
        is_pierce = False

        if level_side == "resistance" and high > level_price + tolerance:
            is_pierce = True
        elif level_side == "support" and low < level_price - tolerance:
            is_pierce = True

        if is_touch:
            touch_indices.append(i)
            markers.append(
                {
                    "time": int(ts.timestamp()),
                    "type": "level_touch_analyzer",
                    "position": "inBar",
                    "color": "#FFD700",
                    "shape": "circle",
                    "text": "T",
                }
            )

        if is_pierce:
            pierce_indices.append(i)
            markers.append(
                {
                    "time": int(ts.timestamp()),
                    "type": "level_touch_analyzer",
                    "position": "inBar",
                    "color": "#ef5350",
                    "shape": "circle",
                    "text": "P",  # Pierce
                }
            )
            if invalidate_on_pierce:
                # If invalidation is enabled, we could mark everything after the breakout as invalid,
                # but for the visualizer, it's better to show all attempts.
                pass

    return {"levels": levels, "markers": markers}


def find_price_action_visuals(
    market_data: Dict[str, Any], params: Dict[str, Any], main_df: pd.DataFrame
) -> List[Dict[str, Any]]:
    """
    Finds and marks the Price Action structure (HH, HL, LH, LL) considering the parameters.
    Returns markers and a single clean structure line.
    """
    markers = []

    lookback = int(params.get("lookback_candles", 500))
    # Increasing the default sensitivity to 5 to remove noise
    order = int(params.get("order", 5))

    target_tf = params.get("timeframe")
    df = (
        market_data.get(f"kline_{target_tf}", main_df).copy()
        if target_tf
        else main_df.copy()
    )

    data = df.tail(lookback).copy()
    if len(data) < order * 2 + 1:
        return []

    highs_all = data["high"].to_numpy()
    lows_all = data["low"].to_numpy()

    # Searching for highs (H) and lows (L)
    found_points = []  # List of (index, price, label, type)

    for i in range(order, len(data) - order):
        h_val = highs_all[i]
        l_val = lows_all[i]

        is_h = np.all(h_val > highs_all[i - order : i]) and np.all(
            h_val > highs_all[i + 1 : i + order + 1]
        )
        is_l = np.all(l_val < lows_all[i - order : i]) and np.all(
            l_val < lows_all[i + 1 : i + order + 1]
        )

        if is_h:
            found_points.append(
                {
                    "idx": i,
                    "price": h_val,
                    "type": "H",
                    "time": int(data.index[i].timestamp()),
                }
            )
        if is_l:
            found_points.append(
                {
                    "idx": i,
                    "price": l_val,
                    "type": "L",
                    "time": int(data.index[i].timestamp()),
                }
            )

    # Sorting by time
    found_points.sort(key=lambda x: x["idx"])

    last_h = None
    last_l = None

    for pt in found_points:
        label = pt["type"]
        val = pt["price"]

        if pt["type"] == "H":
            if last_h is not None:
                label = "HH" if val > last_h else "LH"
            last_h = val
            markers.append(
                {
                    "time": pt["time"],
                    "type": "price_action_analyzer",
                    "position": "aboveBar",
                    "color": "#2196F3"
                    if label == "HH"
                    else ("#ef5350" if label == "LH" else "#888888"),
                    "shape": "arrowDown",
                    "text": label,
                }
            )
        else:
            if last_l is not None:
                label = "LL" if val < last_l else "HL"
            last_l = val
            markers.append(
                {
                    "time": pt["time"],
                    "type": "price_action_analyzer",
                    "position": "belowBar",
                    "color": "#4CAF50"
                    if label == "HL"
                    else ("#ef5350" if label == "LL" else "#888888"),
                    "shape": "arrowUp",
                    "text": label,
                }
            )

    return markers


def _check_foundation_pattern(
    pair_info: Dict[str, Any], market_data: Dict[str, Any], strategy_context: str
) -> bool:
    return False


# AI_CONTEXT_START: _check_foundation_volume_confirmation
def _check_foundation_volume_confirmation(
    pair_info: Dict[str, Any],
    market_data: Dict[str, Any],
    candles_df: Optional[pd.DataFrame],
    last_closed_candle_idx: Optional[int],
    lookback_period: int = 20,
    multiplier: float = 1.8,
) -> bool:
    """
    Checks for abnormal volume activity.
    The condition is considered met if there is a volume spike on candles
    OR a spike in trade intensity in the tape (aggTrade).
    """
    symbol = pair_info.get("symbol", "Unknown")
    log_prefix = f"[{symbol}:F_VolumeConfirmation]"

    if (
        last_closed_candle_idx is None
        or not isinstance(candles_df, pd.DataFrame)
        or candles_df.empty
    ):
        logger.warning(
            f"{log_prefix} Invalid index ({last_closed_candle_idx}) or candles DataFrame for volume check."
        )
        return False

    volume_confirmed_kline = False
    kline_vol_lookback = lookback_period
    kline_vol_multiplier = multiplier

    if (
        last_closed_candle_idx is not None
        and last_closed_candle_idx >= kline_vol_lookback
    ):
        try:
            if not (0 <= last_closed_candle_idx < len(candles_df)):
                logger.warning(
                    f"{log_prefix} Kline idx {last_closed_candle_idx} out of bounds (len={len(candles_df)})."
                )
            else:
                current_volume = float(
                    candles_df["volume"].iloc[last_closed_candle_idx]
                )
                lookback_end_idx_for_avg = last_closed_candle_idx
                lookback_start_idx_for_avg = (
                    lookback_end_idx_for_avg - kline_vol_lookback
                )

                if lookback_start_idx_for_avg < 0:
                    logger.debug(
                        f"{log_prefix} Kline: Not enough history for rolling average volume at index {last_closed_candle_idx}."
                    )
                else:
                    avg_volume_hist = float(
                        candles_df["volume"]
                        .iloc[lookback_start_idx_for_avg:lookback_end_idx_for_avg]
                        .mean()
                    )
                    if (
                        avg_volume_hist > 1e-9
                        and current_volume >= avg_volume_hist * kline_vol_multiplier
                    ):
                        volume_confirmed_kline = True
                        logger.debug(
                            f"{log_prefix} Kline volume confirmed at index {last_closed_candle_idx} (Vol: {current_volume:.2f} vs Avg: {avg_volume_hist:.2f})"
                        )
        except (IndexError, KeyError, ValueError, TypeError) as e:
            logger.warning(
                f"{log_prefix} Error checking kline volume at index {last_closed_candle_idx}: {e}"
            )
            volume_confirmed_kline = False

    volume_confirmed_agg = False
    agg_trades_df = market_data.get("aggTrade")
    if isinstance(agg_trades_df, pd.DataFrame) and not agg_trades_df.empty:
        try:
            if not (0 <= last_closed_candle_idx < len(candles_df)):
                logger.warning(
                    f"{log_prefix} AggTrade: Invalid kline index {last_closed_candle_idx} for timestamp boundaries."
                )
            else:
                last_closed_candle_start_time = candles_df.index[last_closed_candle_idx]
                candle_duration = timedelta(minutes=1)
                if last_closed_candle_idx > 0:
                    try:
                        candle_duration = timedelta(
                            seconds=(
                                candles_df.index[last_closed_candle_idx]
                                - candles_df.index[last_closed_candle_idx - 1]
                            ).total_seconds()
                        )
                    except Exception:
                        pass  # pragma: no cover
                elif len(candles_df.index) > 1:
                    try:
                        candle_duration = timedelta(
                            seconds=(
                                candles_df.index[1] - candles_df.index[0]
                            ).total_seconds()
                        )
                    except Exception:
                        pass  # pragma: no cover

                last_closed_candle_end_time = (
                    last_closed_candle_start_time + candle_duration
                )
                agg_window_sec = 5
                window_end_time = last_closed_candle_end_time
                window_start_time = window_end_time - pd.Timedelta(
                    seconds=agg_window_sec
                )

                if (
                    not isinstance(agg_trades_df.index, pd.DatetimeIndex)
                    or agg_trades_df.index.tz is None
                ):
                    logger.warning(
                        f"{log_prefix} AggTrade index is not timezone-aware DatetimeIndex."
                    )
                else:
                    trades_in_window_df = agg_trades_df[
                        (agg_trades_df.index >= window_start_time)
                        & (agg_trades_df.index < window_end_time)
                    ]
                    if not trades_in_window_df.empty:
                        num_trades = len(trades_in_window_df)
                        trade_rate = (
                            num_trades / agg_window_sec if agg_window_sec > 0 else 0
                        )
                        if trade_rate >= 5:
                            volume_confirmed_agg = True
                            logger.debug(
                                f"{log_prefix} AggTrade volume confirmed for candle ending {last_closed_candle_end_time}."
                            )
        except Exception as e:
            logger.warning(
                f"{log_prefix} Error checking aggTrade volume for index {last_closed_candle_idx}: {e}",
                exc_info=True,
            )
            volume_confirmed_agg = False

    final_confirmation = volume_confirmed_kline or volume_confirmed_agg
    if not final_confirmation:
        logger.debug(
            f"{log_prefix} Volume NOT confirmed for index {last_closed_candle_idx} (Kline: {volume_confirmed_kline}, Agg: {volume_confirmed_agg})."
        )
    return final_confirmation


# AI_CONTEXT_END


# AI_CONTEXT_START: _determine_trend_direction
def _determine_trend_direction_from_values(
    sma_fast_val: Optional[float],
    sma_slow_val: Optional[float],
    rsi_val: Optional[float],
    rsi_trend_zone_lower: float,
    rsi_trend_zone_upper: float,
    symbol: str = "Unknown",
) -> str:
    """
    Determines trend direction from pre-calculated indicator values.
    This is the core logic function.
    """
    log_prefix = f"[{symbol}:F_Trend_Values]"

    if sma_fast_val is None or sma_slow_val is None or rsi_val is None:
        logging.info(
            f"{log_prefix} Trend is FLAT because one or more indicator values are None."
        )
        return "FLAT"

    try:
        sma_fast_f = float(sma_fast_val)
        sma_slow_f = float(sma_slow_val)
        rsi_f = float(rsi_val)

        if pd.isna(sma_fast_f) or pd.isna(sma_slow_f) or pd.isna(rsi_f):
            logging.info(
                f"{log_prefix} Trend is FLAT because one or more values are NaN. Fast: {sma_fast_f}, Slow: {sma_slow_f}, RSI: {rsi_f}"
            )
            return "FLAT"

    except (ValueError, TypeError):
        logging.info(
            f"{log_prefix} Trend is FLAT because values could not be converted to float."
        )
        return "FLAT"

    # rsi_lower_bound for LONG, rsi_upper_bound for SHORT
    is_long_trend = sma_fast_f > sma_slow_f and rsi_f > rsi_trend_zone_lower
    is_short_trend = sma_fast_f < sma_slow_f and rsi_f < rsi_trend_zone_upper

    final_trend = "FLAT"
    # The condition has become stricter: for a LONG trend, there should be no signs of a SHORT trend
    if is_long_trend and not is_short_trend:
        final_trend = "LONG"
    # And vice versa
    elif is_short_trend and not is_long_trend:
        final_trend = "SHORT"

    logging.info(
        f"{log_prefix} Decision -> is_long: {is_long_trend}, is_short: {is_short_trend} ==> FINAL: {final_trend}"
    )

    return final_trend


def _determine_trend_direction(
    pair_info: Dict[str, Any],
    sma_fast_period: int,
    sma_slow_period: int,
    rsi_period: int,
    rsi_trend_zone_lower: float,
    rsi_trend_zone_upper: float,
) -> Optional[str]:
    """
    Wrapper function that retrieves indicator values from pair_info
    and uses the core logic to determine trend.
    """
    symbol = pair_info.get("symbol", "Unknown")
    log_prefix = f"[{symbol}:F_Trend_Wrapper]"

    sma_fast_key = f"SMA_{sma_fast_period}"
    sma_slow_key = f"SMA_{sma_slow_period}"
    rsi_key = f"RSI_{rsi_period}"

    sma_fast = pair_info.get(sma_fast_key)
    sma_slow = pair_info.get(sma_slow_key)
    rsi = pair_info.get(rsi_key)

    logging.info(
        f"{log_prefix} Time: {pair_info.get('timestamp_dt')}, "
        f"Keys: {sma_fast_key}, {sma_slow_key}, {rsi_key}, "
        f"Values: SMA_fast={sma_fast}, SMA_slow={sma_slow}, RSI={rsi}"
    )

    return _determine_trend_direction_from_values(
        sma_fast_val=sma_fast,
        sma_slow_val=sma_slow,
        rsi_val=rsi,
        rsi_trend_zone_lower=rsi_trend_zone_lower,
        rsi_trend_zone_upper=rsi_trend_zone_upper,
        symbol=symbol,
    )


# AI_CONTEXT_END

# Functions for defining classic patterns


def _is_bullish_engulfing(candles_df: pd.DataFrame, index: int) -> bool:
    """
    Checks the "Bullish Engulfing" pattern according to strict rules.
    1. Previous candle is bearish and is not a doji.
    2. Current candle is bullish.
    3. The body of the current candle completely engulfs the body of the previous one.
    """
    if index < 1:
        return False
    try:
        prev = candles_df.iloc[index - 1]
        curr = candles_df.iloc[index]

        # Rule 1: Previous candle is bearish (red)
        is_prev_bearish = prev["close"] < prev["open"]

        # Rule 2: Current candle is bullish (green)
        is_curr_bullish = curr["close"] > curr["open"]

        # Rule 3 (Additional): The previous candle must not be a doji
        prev_body_size = abs(prev["open"] - prev["close"])
        prev_range = prev["high"] - prev["low"]
        # If the range is zero or the body is <10% of the range, it's a doji
        is_prev_doji = prev_range < 1e-9 or (prev_body_size / prev_range < 0.1)

        # Rule 4: The body of the current candle engulfs the body of the previous one
        is_body_engulfing = (
            curr["open"] < prev["close"] and curr["close"] > prev["open"]
        )

        # Collecting all conditions together
        return (
            is_prev_bearish
            and is_curr_bullish
            and not is_prev_doji
            and is_body_engulfing
        )

    except (IndexError, KeyError):
        return False
    return False


def _is_bearish_engulfing(candles_df: pd.DataFrame, index: int) -> bool:
    """
    Checks the "Bearish Engulfing" pattern according to strict rules.
    1. Previous candle is bullish and is not a doji.
    2. Current candle is bearish.
    3. The body of the current candle completely engulfs the body of the previous one.
    """
    if index < 1:
        return False
    try:
        prev = candles_df.iloc[index - 1]
        curr = candles_df.iloc[index]

        # Rule 1: Previous candle is bullish (green)
        is_prev_bullish = prev["close"] > prev["open"]

        # Rule 2: Current candle is bearish (red)
        is_curr_bearish = curr["close"] < curr["open"]

        # Rule 3 (Additional): The previous candle must not be a doji
        prev_body_size = abs(prev["open"] - prev["close"])
        prev_range = prev["high"] - prev["low"]
        is_prev_doji = prev_range < 1e-9 or (prev_body_size / prev_range < 0.1)

        # Rule 4: The body of the current candle engulfs the body of the previous one
        is_body_engulfing = (
            curr["open"] > prev["close"] and curr["close"] < prev["open"]
        )

        # Collecting all conditions together
        return (
            is_prev_bullish
            and is_curr_bearish
            and not is_prev_doji
            and is_body_engulfing
        )

    except (IndexError, KeyError):
        return False
    return False


def _is_pin_bar(candles_df: pd.DataFrame, index: int) -> Optional[str]:
    """
    FINAL VERSION: Checks the pin bar according to the strictest rules.
    1. The long shadow ("tail") must be > 50% of the entire candle range.
    2. The body must be small (< 1/3 of the range).
    3. The short shadow ("nose") must be smaller than the body.
    """
    try:
        candle = candles_df.iloc[index]
        body_size = abs(candle["open"] - candle["close"])
        candle_range = candle["high"] - candle["low"]

        if candle_range < 1e-9:
            return None

        upper_wick = candle["high"] - max(candle["open"], candle["close"])
        lower_wick = min(candle["open"], candle["close"]) - candle["low"]

        # Rule 2: The body must be small
        if body_size / candle_range > 0.33:
            return None

        # Checking for a bullish pin bar (Hammer)
        is_bullish_pin = (
            # Rule 1 (NEW): Lower tail is the main part of the candle
            lower_wick / candle_range > 0.5
            and
            # Rule 3: Upper "nose" is very short
            upper_wick < body_size
        )
        if is_bullish_pin:
            return "BULLISH"

        # Check for a bearish pin bar (Shooting Star)
        is_bearish_pin = (
            # Rule 1 (NEW): Upper tail is the main part of the candle
            upper_wick / candle_range > 0.5
            and
            # Rule 3: Lower "nose" is very short
            lower_wick < body_size
        )
        if is_bearish_pin:
            return "BEARISH"

    except (IndexError, KeyError):
        return None
    return None


def _is_doji(candles_df: pd.DataFrame, index: int) -> bool:
    """Checks the "Doji" pattern."""
    try:
        candle = candles_df.iloc[index]
        body_size = abs(candle["open"] - candle["close"])
        candle_range = candle["high"] - candle["low"]
        if candle_range < 1e-9:
            return True  # If the range is zero, it's a doji
        # The body must be very small (e.g., < 10% of the range)
        if body_size / candle_range < 0.1:
            return True
    except (IndexError, KeyError):
        return False
    return False


def _is_inside_bar(candles_df: pd.DataFrame, index: int) -> bool:
    """Checks the "Inside Bar" pattern."""
    if index < 1:
        return False
    try:
        prev = candles_df.iloc[index - 1]
        curr = candles_df.iloc[index]
        # High and Low of the current candle must be within the range of the previous one
        if curr["high"] < prev["high"] and curr["low"] > prev["low"]:
            return True
    except (IndexError, KeyError):
        return False
    return False


# Dispatcher dictionary for calling the required function
CLASSIC_PATTERN_CHECKS = {
    "bullish_engulfing": _is_bullish_engulfing,
    "bearish_engulfing": _is_bearish_engulfing,
    "pin_bar": _is_pin_bar,
    "doji": _is_doji,
    "inside_bar": _is_inside_bar,
}


# AI_CONTEXT_START: _check_foundation_classic_pattern
def _check_foundation_classic_pattern(
    pair_info: Dict[str, Any], candles_df: pd.DataFrame, params: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """
    Checks for the presence of a classic candlestick pattern on the last closed candle.

    Parameters in 'params':
    - pattern_name (str): Pattern name.
        Available values:
        - "bullish_engulfing": Bullish engulfing.
        - "bearish_engulfing": Bearish engulfing.
        - "pin_bar": Pin bar (hammer or shooting star).
        - "doji": Doji candle.
        - "inside_bar": Inside bar.
    - side (str, optional): For pin bar, allows specifying the direction.
        - "BULLISH": Search only for bullish pin bar (hammer).
        - "BEARISH": Search only for bearish pin bar (shooting star).
        - "ANY" (default): Any pin bar.
    - timeframe (str, optional): Timeframe for analysis. Example: '5m', '1h'. Default '1m'.
    """
    pattern_name = params.get("pattern_name")
    side = params.get("side", "any").upper()

    if not pattern_name or pattern_name not in CLASSIC_PATTERN_CHECKS:
        return False, {"error": f"Unknown or missing pattern_name: {pattern_name}"}

    # Remove timeframe and kline_key retrieval, as the DataFrame has already been passed
    current_index = pair_info.get("current_candle_index")

    if (
        not isinstance(candles_df, pd.DataFrame)
        or candles_df.empty
        or current_index is None
    ):
        return False, {"error": "Candlestick data not available for pattern checking"}

    check_index = current_index
    if check_index < 0:
        return False, {"info": "Not enough history for pattern check"}

    details = {
        "pattern_checked": pattern_name,
        "check_index": check_index,
        "side_checked": side,
    }

    # The logic for the pin bar remains the same, but now works with the correct data
    if pattern_name == "pin_bar":
        pin_bar_type = _is_pin_bar(candles_df, check_index)
        details["pin_bar_type_detected"] = pin_bar_type
        if pin_bar_type is None:
            return False, details
        if side == "ANY":
            return True, details
        if side == pin_bar_type:
            return True, details
        return False, details

    checker_func = CLASSIC_PATTERN_CHECKS[pattern_name]
    result = checker_func(candles_df, check_index)

    return result, details


# AI_CONTEXT_END


def _adapt_sl_to_orderbook(
    original_sl: float,
    entry_or_trigger_price: float,
    direction: SignalDirection,
    ob_info_density: Optional[DensityInfo],
    atr: float,
    tick_size: float,
    log_prefix: str,
) -> Optional[float]:
    if (
        not getattr(config, "ADAPT_SL_TO_ORDERBOOK_ENABLED", False)
        or ob_info_density is None
        or ob_info_density.price is None
        or atr <= 0
        or tick_size <= 0
    ):
        return None
    max_offset_atr = getattr(config, "ORDERBOOK_ADAPT_MAX_OFFSET_ATR", 0.5)
    min_density_dist_atr = getattr(
        config, "ORDERBOOK_ADAPT_MIN_DENSITY_DISTANCE_ATR", 0.3
    )
    sl_ticks_behind = getattr(config, "ORDERBOOK_ADAPT_SL_TICKS_BEHIND_DENSITY", 5)
    adapted_sl = None
    density_price = ob_info_density.price
    original_sl_distance = abs(entry_or_trigger_price - original_sl)
    density_distance_from_entry = abs(entry_or_trigger_price - density_price)
    if direction == SignalDirection.LONG:
        if ob_info_density.side == "bid" and density_price < entry_or_trigger_price:
            if density_distance_from_entry < min_density_dist_atr * atr:
                logger.debug(
                    f"{log_prefix} SL Adapt: Density at {density_price:.4f} too close to entry for SL (DistATR: {density_distance_from_entry / atr:.2f} < Min: {min_density_dist_atr})."
                )
                return None
            candidate_sl_raw = density_price - (sl_ticks_behind * tick_size)
            candidate_sl = round_price_by_tick(candidate_sl_raw, tick_size, ROUND_DOWN)
            if candidate_sl is not None and candidate_sl < entry_or_trigger_price:
                new_sl_distance = abs(entry_or_trigger_price - candidate_sl)
                if new_sl_distance <= original_sl_distance + (max_offset_atr * atr):
                    if candidate_sl >= original_sl:
                        adapted_sl = candidate_sl
                        logger.info(
                            f"{log_prefix} SL (L) adapted from {original_sl:.4f} to {adapted_sl:.4f} based on BID density at {density_price:.4f}"
                        )
                else:
                    logger.debug(
                        f"{log_prefix} SL (L) Adapt REJECTED: Candidate SL {candidate_sl:.4f} (dist {new_sl_distance:.4f}) exceeds max offset from original {original_sl:.4f} (orig_dist {original_sl_distance:.4f}, MaxOffsetATR: {max_offset_atr * atr:.4f})."
                    )
    elif direction == SignalDirection.SHORT:
        if ob_info_density.side == "ask" and density_price > entry_or_trigger_price:
            if density_distance_from_entry < min_density_dist_atr * atr:
                logger.debug(
                    f"{log_prefix} SL Adapt: Density at {density_price:.4f} too close to entry for SL (DistATR: {density_distance_from_entry / atr:.2f} < Min: {min_density_dist_atr})."
                )
                return None
            candidate_sl_raw = density_price + (sl_ticks_behind * tick_size)
            candidate_sl = round_price_by_tick(candidate_sl_raw, tick_size, ROUND_UP)
            if candidate_sl is not None and candidate_sl > entry_or_trigger_price:
                new_sl_distance = abs(entry_or_trigger_price - candidate_sl)
                if new_sl_distance <= original_sl_distance + (max_offset_atr * atr):
                    if candidate_sl <= original_sl:
                        adapted_sl = candidate_sl
                        logger.info(
                            f"{log_prefix} SL (S) adapted from {original_sl:.4f} to {adapted_sl:.4f} based on ASK density at {density_price:.4f}"
                        )
                else:
                    logger.debug(
                        f"{log_prefix} SL (S) Adapt REJECTED: Candidate SL {candidate_sl:.4f} (dist {new_sl_distance:.4f}) exceeds max offset from original {original_sl:.4f} (orig_dist {original_sl_distance:.4f}, MaxOffsetATR: {max_offset_atr * atr:.4f})."
                    )
    return adapted_sl


def _adapt_tp_to_orderbook(
    original_tp: Optional[float],
    entry_or_trigger_price: float,
    direction: SignalDirection,
    ob_info_density: Optional[DensityInfo],
    atr: float,
    tick_size: float,
    log_prefix: str,
    is_partial_tp: bool = False,
) -> Optional[float]:
    if (
        not getattr(config, "ADAPT_TP_TO_ORDERBOOK_ENABLED", False)
        or original_tp is None
        or original_tp <= 0
        or ob_info_density is None
        or ob_info_density.price is None
        or atr <= 0
        or tick_size <= 0
    ):
        return None
    max_offset_atr = getattr(config, "ORDERBOOK_ADAPT_MAX_OFFSET_ATR", 0.5)
    min_density_dist_atr = getattr(
        config, "ORDERBOOK_ADAPT_MIN_DENSITY_DISTANCE_ATR", 0.3
    )
    tp_ticks_before = getattr(config, "ORDERBOOK_ADAPT_TP_TICKS_BEFORE_DENSITY", 5)
    adapted_tp = None
    density_price = ob_info_density.price
    density_distance_from_entry = abs(entry_or_trigger_price - density_price)
    original_tp_distance_from_entry = abs(entry_or_trigger_price - original_tp)
    if direction == SignalDirection.LONG:
        if (
            ob_info_density.side == "ask"
            and density_price > entry_or_trigger_price
            and density_price < original_tp
        ):
            if density_distance_from_entry < min_density_dist_atr * atr:
                logger.debug(
                    f"{log_prefix} TP Adapt: Density at {density_price:.4f} too close to entry for TP (DistATR: {density_distance_from_entry / atr:.2f} < Min: {min_density_dist_atr})."
                )
                return None
            candidate_tp_raw = density_price - (tp_ticks_before * tick_size)
            candidate_tp = round_price_by_tick(candidate_tp_raw, tick_size, ROUND_DOWN)
            if candidate_tp is not None and candidate_tp > entry_or_trigger_price:
                new_tp_distance = abs(entry_or_trigger_price - candidate_tp)
                if new_tp_distance >= original_tp_distance_from_entry - (
                    max_offset_atr * atr
                ):
                    adapted_tp = candidate_tp
                    tp_type_log = "Partial TP" if is_partial_tp else "Final TP"
                    logger.info(
                        f"{log_prefix} {tp_type_log} (L) adapted from {original_tp:.4f} to {adapted_tp:.4f} based on ASK density at {density_price:.4f}"
                    )
                else:
                    logger.debug(
                        f"{log_prefix} TP (L) Adapt REJECTED: Candidate TP {candidate_tp:.4f} (dist {new_tp_distance:.4f}) too far from original {original_tp:.4f} (orig_dist {original_tp_distance_from_entry:.4f}, MaxOffsetATR: {max_offset_atr * atr:.4f})."
                    )
    elif direction == SignalDirection.SHORT:
        if (
            ob_info_density.side == "bid"
            and density_price < entry_or_trigger_price
            and density_price > original_tp
        ):
            if density_distance_from_entry < min_density_dist_atr * atr:
                logger.debug(
                    f"{log_prefix} TP Adapt: Density at {density_price:.4f} too close to entry for TP (DistATR: {density_distance_from_entry / atr:.2f} < Min: {min_density_dist_atr})."
                )
                return None
            candidate_tp_raw = density_price + (tp_ticks_before * tick_size)
            candidate_tp = round_price_by_tick(candidate_tp_raw, tick_size, ROUND_UP)
            if candidate_tp is not None and candidate_tp < entry_or_trigger_price:
                new_tp_distance = abs(entry_or_trigger_price - candidate_tp)
                if new_tp_distance >= original_tp_distance_from_entry - (
                    max_offset_atr * atr
                ):
                    adapted_tp = candidate_tp
                    tp_type_log = "Partial TP" if is_partial_tp else "Final TP"
                    logger.info(
                        f"{log_prefix} {tp_type_log} (S) adapted from {original_tp:.4f} to {adapted_tp:.4f} based on BID density at {density_price:.4f}"
                    )
                else:
                    logger.debug(
                        f"{log_prefix} TP (S) Adapt REJECTED: Candidate TP {candidate_tp:.4f} (dist {new_tp_distance:.4f}) too far from original {original_tp:.4f} (orig_dist {original_tp_distance_from_entry:.4f}, MaxOffsetATR: {max_offset_atr * atr:.4f})."
                    )
    return adapted_tp


class BaseStrategy:
    NAME = "BaseStrategy"
    description = "Base class for all strategies."
    enabled: bool = False
    candle_timeframe: Optional[str] = None
    entry_timeframe: Optional[str] = None
    trend_timeframe: Optional[str] = None
    atr_period: Optional[int] = None

    def __init__(
        self, params: Optional[Dict[str, Any]] = None, contract_id: Optional[str] = None
    ):
        self._instance_params: Dict[str, Any] = params or {}
        self.contract_id: Optional[str] = contract_id
        self.enabled: bool = self._get_param("enabled", True)
        self.breakeven_on_regime_change: bool = self._get_param(
            "breakeven_on_regime_change", False
        )
        self.foundation_weights = (
            self._get_param(
                "foundation_weights", getattr(config, "FOUNDATION_WEIGHTS", {})
            )
            or {}
        )
        self.min_total_foundation_weight_threshold = self._get_param(
            "min_total_foundation_weight_threshold",
            getattr(config, "MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD", 50.0),
        )
        self._last_closed_candle_index: int = -1  # Prevents re-entry on the same candle
        self.active_tv_signals: Dict[str, float] = {}  # signal_id -> expiry_timestamp
        self.max_possible_expensive_weight: float = 0.0
        self._required_data_types_cache: Optional[Set[str]] = None
        self._required_indicators_cache: Optional[Set[str]] = None
        self._compiled_fast_config_id: Optional[int] = None
        self._compiled_fast_filters_root: Optional[CompiledConditionNode] = None
        self._compiled_fast_entry_root: Optional[CompiledConditionNode] = None
        self._rtl_state: Dict[str, Dict[str, Any]] = {}

        # CONDITION DISPATCHER
        self.condition_checkers = {
            "trading_session": self._check_filter_trading_session,
            "volatility_filter": self._check_filter_volatility,
            "trend_filter": self._check_filter_trend_strength,
            "btc_state_filter": self._check_filter_btc_state,
            "open_interest": self._check_condition_open_interest,
            "correlation": self._check_condition_correlation,
            "natr_filter": self._check_filter_natr,
            "rel_vol_filter": self._check_filter_rel_vol,
            "market_activity": self._check_foundation_market_activity_wrapper,
            "local_level": self._check_condition_local_level,
            "tape_analysis": self._check_condition_tape_analysis,
            "return_to_level": self._check_condition_return_to_level,
            "classic_pattern": self._check_foundation_classic_pattern_wrapper,
            "trend_direction": self._check_condition_trend_direction,
            "significant_level": self._check_foundation_level_wrapper,
            "volume_confirmation": self._check_foundation_volume_confirmation_wrapper,
            "round_level": self._check_foundation_round_number_level_wrapper,
            "price_consolidation": self._check_condition_price_consolidation,
            "rsi_condition": self._check_condition_rsi,
            "ma_cross_condition": self._check_condition_ma_cross,
            "macd_condition": self._check_condition_macd,
            "value_comparison": self._check_condition_value_comparison,
            "price_vs_level": self._check_condition_price_vs_level,
            "position_state": self._check_condition_position_state,
            "orderbook_condition": self._check_foundation_orderbook_wrapper,
            "order_book_zone": self._check_condition_order_book_zone,
            "l2_microstructure": self._check_condition_l2_microstructure,
            "l2_microstructure_check": self._check_condition_l2_microstructure,
            "orderbook_imbalance": self._check_condition_l2_microstructure,
            "price_condition": self._check_condition_value_comparison,
            "tape_condition": self._check_condition_tape,  # For genetic strategies
            # ALIASES FOR BACKWARD COMPATIBILITY WITH GENETIC STRATEGIES
            "stoch_condition": self._check_condition_stochastic,  # Alias: stoch_condition -> stochastic
            "stochastic_condition": self._check_condition_stochastic,  # Canonical type
            "bb_condition": self._check_condition_bollinger,  # Alias: bb_condition -> bollinger
            "bollinger_bands_condition": self._check_condition_bollinger,  # Canonical type
            "adx_filter": self._check_filter_adx,  # ADX filter
            "time_filter": self._check_filter_trading_session,  # Alias: time_filter -> trading_session (Unified)
            "level_touch_analyzer": self._check_condition_level_touch,
            "volatility_squeeze": self._check_condition_volatility_squeeze,
            "price_action_analyzer": self._check_condition_price_action,
        }

    def notify_closure(self, candle_index: int):
        """
        Notifies the strategy about closing a position on a specific candle.
        Used by the backtester during forced closure (SL/TP).
        """
        self._last_closed_candle_index = candle_index
        logger.info(
            f"[{self.NAME}] Strategy notified of position closure at candle {candle_index}"
        )

    def register_tv_signal(self, signal_id: str, ttl_seconds: int):
        """
        Registers a signal from TradingView with a given TTL.
        Used in hybrid mode, where TV signals act as foundations.
        """
        expiry = time.time() + ttl_seconds
        self.active_tv_signals[signal_id] = expiry
        logger.info(
            f"[{self.NAME}] Registered TV signal '{signal_id}' with TTL {ttl_seconds}s (expires at {datetime.fromtimestamp(expiry).strftime('%H:%M:%S')})"
        )

    def _check_condition_order_book_zone(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        [DATA PROVIDER] Analyzes a zone in the aggregated order book and provides volume metrics.
        """
        aggregated_depth = market_data.get("depth_analysis")
        details = {"params": params, "source": "depth_analysis"}

        if not aggregated_depth or not isinstance(aggregated_depth, dict):
            details["error"] = (
                "Aggregated depth data (depth_analysis) is missing or invalid."
            )
            return True, details

        side = params.get("side", "bids").lower()
        range_type = params.get("range_type", "Percentage")
        range_value = float(
            self._resolve_value(params.get("range_value", 1.0), context)
        )
        last_price = pair_info.get("last_price")
        atr = pair_info.get("atr")

        if not last_price or last_price <= 0:
            details["error"] = "last_price not available or invalid in pair_info"
            return True, details

        calculated_percentage_range = 0.0
        if range_type == "Percentage":
            calculated_percentage_range = range_value
        elif range_type == "ATR Multiplier":
            if not atr or atr <= 0:
                details["error"] = "ATR not available for ATR Multiplier range type"
                return True, details
            calculated_percentage_range = (atr * range_value / last_price) * 100
        elif range_type == "Ticks":
            tick_size = pair_info.get("tick_size")
            if not tick_size or tick_size <= 0:
                details["error"] = "tick_size not available for Ticks range type"
                return True, details
            calculated_percentage_range = (tick_size * range_value / last_price) * 100

        target_buckets = aggregated_depth.get(side, [])

        # Replacing summation logic with selecting a single level
        total_volume_usd = 0.0
        level_count = 0
        largest_level_usd = 0.0
        selected_bucket_percentage = None

        if target_buckets:
            # Define known percentage levels corresponding to columns notional_m1, notional_m2, etc.
            bucket_percentages = [1.0, 2.0, 3.0, 4.0, 5.0]

            # Find the index of the first (smallest) level that is greater than or equal to the required range.
            target_bucket_index = -1
            for i, p in enumerate(bucket_percentages):
                if p >= calculated_percentage_range:
                    target_bucket_index = i
                    break

            # If a suitable level is found and it exists in our data
            if target_bucket_index != -1 and target_bucket_index < len(target_buckets):
                selected_bucket = target_buckets[target_bucket_index]

                # Take a single value. DO NOT SUM.
                notional_value = selected_bucket.get("notional", 0.0)
                total_volume_usd = notional_value
                largest_level_usd = notional_value
                level_count = 1  # This is one aggregated level.
                selected_bucket_percentage = bucket_percentages[target_bucket_index]

        details.update(
            {
                "total_volume_usd": total_volume_usd,
                "level_count": level_count,
                "largest_level_usd": largest_level_usd,
                "calculated_percentage_range": calculated_percentage_range,
                "selected_bucket_percentage": selected_bucket_percentage,  # Adding for debugging
            }
        )

        logger.debug(
            f"[VBS|order_book_zone|{pair_info.get('symbol', '?')}] "
            f" Candle: {pair_info.get('current_candle_index')} |"
            f" Side: {side} |"
            f" Total Volume USD: {total_volume_usd:,.2f} |"
            f" Details: {details}"
        )

        return True, details

    @staticmethod
    def _normalize_btc_state_value(raw_state: Any) -> str:
        if not isinstance(raw_state, str):
            return "Any"

        normalized = raw_state.strip()
        if not normalized:
            return "Any"

        canonical_map = {
            "consolidation": "Consolidation",
            "trending_up": "Trending Up",
            "trending_down": "Trending Down",
            "any": "Any",
        }
        normalized_key = normalized.lower().replace("-", "_").replace(" ", "_")
        return canonical_map.get(normalized_key, normalized)

    @staticmethod
    def _normalize_trailing_stop_type(raw_type: Any) -> str:
        if not isinstance(raw_type, str):
            return "ATR"

        normalized_key = raw_type.strip().lower()
        if normalized_key in {"percent", "percentage"}:
            return "Percentage"
        if normalized_key == "ma":
            return "MA"
        if normalized_key == "atr":
            return "ATR"
        return raw_type

    def _check_condition_l2_microstructure(
        self,
        pair_info: Dict,
        market_data: Dict,
        params: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Performs a detailed analysis of the full L2 order book.
        Skipped in backtest if full L2 is unavailable.
        """
        full_l2_depth = market_data.get("depth_trading")
        details = {"params": params, "source": "depth_trading"}

        # TOR 3.1: On backtest, this block should always return True and log a warning.
        # We determine the backtest mode by the absence of 'depth_trading'.
        if (
            not full_l2_depth
            or not isinstance(full_l2_depth, dict)
            or not full_l2_depth.get("bids")
        ):
            logger.debug(
                f"[{self.NAME}] L2 microstructure check skipped (likely backtest mode or no data)."
            )
            details["info"] = "L2 microstructure check skipped (backtest mode)."
            return True, details

        side = params.get("side", "bids").lower()
        if side not in ("bids", "asks"):
            side = "bids"
        single_order_size_usd = float(params.get("single_order_size_usd", 250000.0))
        levels_to_scan = int(params.get("levels_to_scan", 200))
        target_levels = full_l2_depth.get(side, [])

        found_large_order, found_price, found_notional, scanned_levels = (
            _find_first_large_order(
                target_levels,
                min_notional=single_order_size_usd,
                max_levels=levels_to_scan,
            )
        )
        details["scanned_levels"] = scanned_levels
        details["numba_enabled"] = _should_use_numba_orderbook()
        if found_large_order:
            details["found_large_order_at"] = found_price
            details["size_usd"] = found_notional

        return found_large_order, details

    def _get_param(self, param_name: str, default: Any = None) -> Any:
        if param_name in self._instance_params:
            value = self._instance_params[param_name]
            if param_name == "breakeven_on_regime_change":
                logger.info(
                    f"[_get_param] Found '{param_name}' in _instance_params: {value}"
                )
            return value
        # Also check in nested 'config' dict
        if "config" in self._instance_params and isinstance(
            self._instance_params["config"], dict
        ):
            if param_name in self._instance_params["config"]:
                value = self._instance_params["config"][param_name]
                if param_name == "breakeven_on_regime_change":
                    logger.info(
                        f"[_get_param] Found '{param_name}' in _instance_params['config']: {value}"
                    )
                return value
        value_attr = getattr(self, param_name, None)
        if value_attr is not None and not callable(value_attr):
            return value_attr
        if param_name == "breakeven_on_regime_change":
            logger.info(
                f"[_get_param] '{param_name}' not found, returning default: {default}"
            )
        return config.get_strategy_param(self.NAME, param_name, default)

    def _resolve_value(self, param_value: Any, context: Dict[str, Any]) -> Any:
        """
        Resolves a parameter that might be a static value or a dynamic link.
        FIXED VERSION: Guarantees return of a numeric value or None.
        """
        if not isinstance(param_value, dict) or "source" not in param_value:
            return param_value

        source = param_value.get("source")
        key = param_value.get("key")
        pair_info = context.get("pair_info", {})
        market_data = context.get("market_data", {})

        # Processing different sources
        if source in {"value", "constant"}:
            return param_value.get("value")

        if source == "candle":
            shift = int(param_value.get("shift", 0))
            # For shift 0, first try to quickly get from pair_info
            if shift == 0 and key in pair_info:
                try:
                    return float(pair_info[key])
                except (ValueError, TypeError):
                    pass  # If it didn't work, try via the DataFrame below

            # For any shift (or if not found in pair_info), use the DataFrame
            timeframe = param_value.get(
                "timeframe", pair_info.get("candle_timeframe", "1m")
            )
            kline_key = f"kline_{timeframe}"
            candles_df = market_data.get(kline_key)
            current_index = pair_info.get("current_candle_index")

            # In Live mode, current_candle_index may be missing.
            # In this case, we assume that we are on the last available candle.
            if (
                current_index is None
                and candles_df is not None
                and not candles_df.empty
            ):
                current_index = len(candles_df) - 1

            if (
                candles_df is not None
                and not candles_df.empty
                and current_index is not None
            ):
                target_index = current_index - shift
                if 0 <= target_index < len(candles_df):
                    try:
                        value = candles_df.iloc[target_index][key]
                        return float(value)
                    except (KeyError, ValueError, TypeError, IndexError):
                        pass  # If an error occurs, return None at the end

            logger.warning(
                f"[_resolve_value] Failed to resolve CANDLE value. Key: {key}, Shift: {shift}. Data available: {candles_df is not None}, Index: {current_index}"
            )
            return None

        elif source == "indicator":
            if key:
                # First try uppercase (pandas_ta standard)
                val = pair_info.get(key.upper())
                # If not found, try the lower one (as DataConsumer saves it)
                if val is None:
                    val = pair_info.get(key.lower())

                if val is not None:
                    return val

                logger.warning(
                    f"[_resolve_value] Failed to resolve INDICATOR. Key: {key} (checked upper/lower). Available keys in pair_info: {list(pair_info.keys())[:10]}..."
                )
                return None
            return None

        elif source == "block_result":
            block_id = param_value.get("block_id")
            trace = context.get("trace")
            if block_id and trace:
                block_trace = self.find_block_in_trace(trace, block_id)
                if block_trace:
                    val = block_trace.get("details", {}).get(key)
                    if val is not None:
                        return val
                    logger.warning(
                        f"[_resolve_value] BLOCK_RESULT found for {block_id} but key '{key}' missing in details. Details keys: {list(block_trace.get('details', {}).keys())}"
                    )
                else:
                    logger.warning(
                        f"[_resolve_value] BLOCK_RESULT trace not found for block_id: {block_id}"
                    )
            return None

        elif source == "position_state":
            position = context.get("position")
            if not position or not key:
                return None

            # Processing computed properties
            if key == "unrealized_pnl_pct":
                current_price = pair_info.get("last_price")
                if current_price and hasattr(position, "get_unrealized_pnl_pct"):
                    return position.get_unrealized_pnl_pct(current_price)
                return 0.0
            if key == "partial_exits_count":
                return len(getattr(position, "partial_fills", []))
            if key == "unrealized_pnl_rr":
                # Calculate risk based on Price difference first (More accurate for partial fills)
                entry_price_for_risk = getattr(position, "entry_price", None)
                if not entry_price_for_risk or entry_price_for_risk <= 0:
                    entry_price_for_risk = getattr(position, "trigger_price", None)

                initial_sl = getattr(position, "initial_stop_loss", None)
                risk_per_unit = 0.0

                if (
                    entry_price_for_risk
                    and initial_sl
                    and entry_price_for_risk > 0
                    and initial_sl > 0
                ):
                    risk_per_unit = abs(entry_price_for_risk - initial_sl)

                # Fallback to planned risk if price diff is zero (e.g. bad SL) or data missing
                if risk_per_unit <= 1e-9:
                    initial_risk = getattr(position, "initial_risk_usd_planned", None)
                    initial_quantity = getattr(position, "initial_quantity", None)
                    if initial_risk and initial_quantity and initial_quantity > 0:
                        risk_per_unit = initial_risk / initial_quantity

                if risk_per_unit <= 1e-9:
                    return 0.0

                current_price = pair_info.get("last_price")
                direction = getattr(position, "direction", None)
                # Ensure we use the same entry price for PnL as for Risk if possible, or actual entry
                calc_entry_price = (
                    getattr(position, "entry_price", None) or entry_price_for_risk
                )

                if not all([current_price, calc_entry_price, direction]):
                    return 0.0

                pnl_per_unit = (
                    (current_price - calc_entry_price)
                    if direction == SignalDirection.LONG
                    else (calc_entry_price - current_price)
                )
                return pnl_per_unit / risk_per_unit

            # Returning direct attributes
            return getattr(position, key, None)

        # If no source matched, return None instead of the original dictionary
        return None

    def _validate_pair_info(
        self, pair_info: Dict[str, Any], required_keys: List[str]
    ) -> bool:
        for key in required_keys:
            val = pair_info.get(key)
            if val is None:
                logger.warning(
                    f"[{self.NAME}:{pair_info.get('symbol', '?')}] Missing required key '{key}'."
                )
                return False
            if (
                key in ["atr", "last_price", "tick_size"]
                and isinstance(val, (int, float))
                and val <= 1e-9
            ):
                logger.warning(
                    f"[{self.NAME}:{pair_info.get('symbol', '?')}] Invalid value for '{key}' ({val})."
                )
                return False
            if key == "natr" and isinstance(val, (int, float)) and val < 0:
                logger.warning(
                    f"[{self.NAME}:{pair_info.get('symbol', '?')}] Invalid 'natr' ({val})."
                )
                return False
            if key == "relative_volume" and isinstance(val, (int, float)) and val < 0:
                logger.warning(
                    f"[{self.NAME}:{pair_info.get('symbol', '?')}] Invalid 'relative_volume' ({val})."
                )
                return False
        return True

    def _validate_market_data(
        self,
        market_data: Dict[str, Any],
        required_kline_keys: List[str],
        require_agg: bool = False,
        require_depth: bool = False,
    ) -> bool:
        for key in required_kline_keys:
            df = market_data.get(key)
            if not isinstance(df, pd.DataFrame) or df.empty:
                logger.warning(f"[{self.NAME}] Missing/empty DataFrame for '{key}'.")
                return False
        if require_agg and not isinstance(market_data.get("aggTrade"), pd.DataFrame):
            logger.warning(f"[{self.NAME}] Missing 'aggTrade'.")
            return False
        if require_depth:
            depth = market_data.get("depth")
            if (
                not isinstance(depth, dict)
                or not depth.get("bids")
                or not depth.get("asks")
            ):
                logger.warning(f"[{self.NAME}] Missing/invalid 'depth'.")
                return False
        return True

    def _create_signal(
        self,
        symbol: str,
        direction: SignalDirection,
        trigger_price: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        mode: OrderMode = OrderMode.MARKET,
        entry_price: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
        partial_targets: Optional[List[PartialTarget]] = None,
        move_sl_to_be_on_first_tp: bool = False,
        risk_pct: Optional[float] = None,
        risk_usd: Optional[float] = None,
    ) -> Optional[StrategySignal]:
        log_prefix = f"[{self.NAME}:{symbol}]"
        allow_short = getattr(config, "ALLOW_SHORT_POSITIONS", False)
        if direction == SignalDirection.SHORT and not allow_short:
            logger.info(
                f"{log_prefix} SHORT signal generation disabled by global config (ALLOW_SHORT_POSITIONS=False). Signal ignored."
            )
            return None
        try:
            sl_float = float(stop_loss) if stop_loss is not None else None
            tp_float = float(take_profit) if take_profit is not None else None
            entry_float = float(entry_price) if entry_price is not None else None
            trigger_float = float(trigger_price)
            if sl_float is not None and sl_float <= 0:
                sl_float = None
            if tp_float is not None and tp_float <= 0:
                raise ValueError(f"Invalid take_profit: {tp_float}")
            comparison_price = (
                entry_float if mode != OrderMode.MARKET else trigger_float
            )
            if comparison_price is None or comparison_price <= 0:
                raise ValueError(f"Invalid comparison price: {comparison_price}")
            # SL validation only if it is set (stop_loss=None = no-stop mode)
            if sl_float is not None:
                if direction == SignalDirection.LONG:
                    if sl_float >= comparison_price:
                        raise ValueError(
                            f"SL ({sl_float:.8f}) must be below comparison price ({comparison_price:.8f}) for LONG."
                        )
                elif direction == SignalDirection.SHORT:
                    if sl_float <= comparison_price:
                        raise ValueError(
                            f"SL ({sl_float:.8f}) must be above comparison price ({comparison_price:.8f}) for SHORT."
                        )
            if direction == SignalDirection.LONG:
                if tp_float is not None and tp_float <= comparison_price:
                    raise ValueError(
                        f"TP ({tp_float:.8f}) must be above comparison price ({comparison_price:.8f}) for LONG."
                    )
            elif direction == SignalDirection.SHORT:
                if tp_float is not None and tp_float >= comparison_price:
                    raise ValueError(
                        f"TP ({tp_float:.8f}) must be below comparison price ({comparison_price:.8f}) for SHORT."
                    )
            if partial_targets:
                total_fraction = 0.0
                last_target_price_val = None
                for i, target in enumerate(partial_targets):
                    if direction == SignalDirection.LONG:
                        if target.price <= comparison_price:
                            raise ValueError(
                                f"Partial target {i + 1} price ({target.price}) must be above comparison price ({comparison_price}) for LONG."
                            )
                        if (
                            last_target_price_val is not None
                            and target.price <= last_target_price_val
                        ):
                            raise ValueError(
                                f"Partial target {i + 1} price ({target.price}) must be > prev target ({last_target_price_val}) for LONG."
                            )
                    elif direction == SignalDirection.SHORT:
                        if target.price >= comparison_price:
                            raise ValueError(
                                f"Partial target {i + 1} price ({target.price}) must be below comparison price ({comparison_price}) for SHORT."
                            )
                        if (
                            last_target_price_val is not None
                            and target.price >= last_target_price_val
                        ):
                            raise ValueError(
                                f"Partial target {i + 1} price ({target.price}) must be < prev target ({last_target_price_val}) for SHORT."
                            )
                    last_target_price_val = target.price
                    total_fraction += target.fraction
                if total_fraction > 1.000001:
                    raise ValueError(
                        f"Sum of partial target fractions ({total_fraction}) cannot exceed 1.0."
                    )
                is_100_percent_partials = abs(total_fraction - 1.0) < 1e-9
                if is_100_percent_partials and tp_float is not None:
                    logger.warning(
                        f"{log_prefix} Partials cover 100%, but final TP ({tp_float}) also set. Final TP ignored if partials hit."
                    )
                if not is_100_percent_partials and tp_float is None:
                    raise ValueError(
                        "Final take_profit must be set if partial targets do not sum to 1.0."
                    )
            # Adding cleanup and new logging
            final_details = details or {}
            final_details.setdefault("no_stop_loss", sl_float is None)
            if self._uses_dca_or_grid_management():
                final_details["uses_dca_or_grid_management"] = True
                final_details["skip_min_rr_for_dca_grid"] = True

            # Clean details from NaN/inf before creating a signal
            details_json_str = "null"
            try:
                # Convert Enum to string and NaN/inf to null
                def custom_serializer(obj):
                    if isinstance(obj, (SignalDirection, OrderMode)):
                        return obj.name
                    # For float/int, check for NaN/inf
                    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
                        return None  # Convert to null
                    return str(obj)  # Fallback

                # Creating a "clean" JSON string
                details_json_str = json.dumps(final_details, default=custom_serializer)
                # Loading back into dict to ensure there are no NaNs in the signal object
                final_details = json.loads(details_json_str)

            except Exception as e_json:
                details_json_str = (
                    f'{{"error": "Failed to serialize details: {str(e_json)}"}}'
                )
            signal = StrategySignal(
                strategy_name=self.NAME,
                symbol=symbol,
                direction=direction,
                trigger_price=trigger_float,
                stop_loss=sl_float,
                take_profit=tp_float,
                mode=mode,
                entry_price=entry_float,
                details=final_details,
                partial_targets=partial_targets,
                move_sl_to_be_on_first_tp=move_sl_to_be_on_first_tp,
                risk_pct=risk_pct,
                risk_usd=risk_usd,
                no_stop_loss=(sl_float is None),
            )

            effective_tp_for_log = take_profit
            if effective_tp_for_log is None and partial_targets:
                effective_tp_for_log = partial_targets[-1].price

            risk_dist_log = (
                abs(comparison_price - sl_float) if sl_float is not None else 0.0
            )
            reward_dist_log = abs((effective_tp_for_log or 0) - comparison_price)
            rr_ratio_log = (
                reward_dist_log / risk_dist_log
                if risk_dist_log > 1e-9 and reward_dist_log > 0
                else 0
            )

            sl_str_log = (
                format_float_detail(sl_float) if sl_float is not None else "NONE"
            )
            tp_str_log = (
                format_float_detail(take_profit) if take_profit is not None else "N/A"
            )

            log_details = (
                f"---> SIGNAL CREATED: {direction.name} {mode.name} | "
                f"Entry/Trig: {comparison_price:.4f}, SL: {sl_str_log}, TP: {tp_str_log} | "
                f"RiskDist: {risk_dist_log:.8f}, RR: {rr_ratio_log:.2f} | "
                f"MoveBE: {move_sl_to_be_on_first_tp}"
            )

            details_json_str = "null"
            if details:
                try:
                    # Convert Enum to string for safe serialization
                    def enum_serializer(obj):
                        if isinstance(obj, (SignalDirection, OrderMode)):
                            return obj.name
                        return str(obj)  # Fallback for other non-serializable objects

                    details_json_str = json.dumps(details, default=enum_serializer)
                except Exception as e_json:
                    details_json_str = (
                        f'{{"error": "Failed to serialize details: {str(e_json)}"}}'
                    )

            # Forming the final message with a unique DETAILS_PAYLOAD key
            # Add information about partial takes to the main message
            final_log_message = f"{log_details} Partials: {len(partial_targets) if partial_targets else 0} DETAILS_PAYLOAD={details_json_str}"

            # Logging a new, enriched message
            if risk_dist_log < comparison_price * 0.0005:
                logger.warning(f"{log_prefix} [ANOMALY_RISK] {final_log_message}")
            else:
                logger.info(final_log_message)

            return signal
        except ValueError as ve:
            logger.error(f"{log_prefix} Invalid Signal Parameters: {ve}")
            return None
        except Exception as e_create:
            logger.error(
                f"{log_prefix} Unexpected error during signal creation: {e_create}",
                exc_info=True,
            )
            return None

    @property
    def required_data_types(self) -> Set[str]:
        """
        Returns a set of data types required for the strategy to work.
        OPTIMIZED VERSION: Analyzes the JSON configuration and subscribes ONLY
        to the data that is actually needed (spots, timeframes, tape, etc.)
        """
        if self._required_data_types_cache is not None:
            return set(self._required_data_types_cache)

        requirements = set()

        # 1. Main strategy timeframe - ALWAYS needed
        visual_config = self._instance_params.get("config", {})
        if not isinstance(visual_config, dict):
            visual_config = {}

        entry_trigger_tf = visual_config.get("entryTrigger", {}).get("timeframe")
        trading_tf = visual_config.get("tradingTimeframe")

        candle_tf = (
            entry_trigger_tf
            or trading_tf
            or self._get_param(
                "candle_timeframe", self._get_param("entry_timeframe", "1m")
            )
        )
        if candle_tf:
            requirements.add(f"kline_{candle_tf}")

        # 2. Check for the presence of JSON configuration (VisualBuilder / GeneticStrategy)
        visual_config = self._instance_params.get("config", {})
        if visual_config and isinstance(visual_config, dict):
            # Dynamic configuration analysis
            self._extract_required_data_from_config(visual_config, requirements)
        else:
            # Classic strategies - using old logic based on the name
            if self.NAME in [
                "FakeBreakout",
                "AggTradeReversal",
                "OnlineAgentStrategy",
                "VolumeBreakout",
                "ConsolidationImpulse",
                "ReverseVolumeBreakout",
                "ReverseFakeBreakout",
            ]:
                requirements.add("aggTrade")

            if self.NAME == "FirstPullbacksInTrend":
                fpi_trend_tf = self._get_param("trend_timeframe")
                if fpi_trend_tf:
                    requirements.add(f"kline_{fpi_trend_tf}")
                requirements.add("aggTrade")

        # 3. For trend strategies, add trend_timeframe
        default_trend_tf = self._get_param("trend_timeframe")
        if default_trend_tf:
            requirements.add(f"kline_{default_trend_tf}")

        # 4. Guarantee at least one kline if nothing was added
        if not any(k.startswith("kline_") for k in requirements):
            requirements.add("kline_1m")

        self._required_data_types_cache = set(requirements)
        return set(requirements)

    def _extract_required_data_from_config(self, node: Any, required: Set[str]):
        """
        Recursively analyzes the JSON configuration of VisualBuilder/GeneticStrategy and determines
        which data types are required for the blocks to function.
        """
        if not isinstance(node, dict):
            if isinstance(node, list):
                for item in node:
                    self._extract_required_data_from_config(item, required)
            return

        block_type = node.get("type")
        params = node.get("params", {})

        # Mapping blocks to required data
        BLOCK_DATA_REQUIREMENTS = {
            # Order book blocks
            "order_book_zone": {"depth"},
            "l2_microstructure": {"depth"},
            "l2_microstructure_check": {"depth"},
            "orderbook_imbalance": {"depth"},
            # Tape of trades
            "tape_analysis": {"aggTrade"},
            "volume_spike": {"aggTrade"},
            # Levels (require higher TFs to determine significant levels)
            "significant_level": {"kline_1h", "kline_4h", "kline_1d"},
            # Blocks requiring BTC data
            "btc_state_filter": {"kline_1m_BTCUSDT"},
            "correlation": {"kline_1m_BTCUSDT"},
            "open_interest": {"open_interest"},
            # Blocks without additional requirements (work on the current TF)
            "local_level": set(),
            "round_number_level": set(),
            "trend_direction": set(),
            "classic_pattern": set(),
            "consolidation_zone": set(),
            # Genetic blocks (GeneticCompatibleStrategy)
            "time_filter": set(),
            "trend_filter": set(),
            "natr_filter": set(),
            "adx_filter": set(),
            "ma_cross_condition": set(),
            "bb_condition": set(),
            "stoch_condition": set(),
            "macd_condition": set(),
            # Containers for higher timeframes
            "senior_tf_confluence": set(),  # Timeframe is extracted from params['timeframe']
        }

        if block_type in BLOCK_DATA_REQUIREMENTS:
            required.update(BLOCK_DATA_REQUIREMENTS[block_type])

        # Extracting timeframe from parameters or from the node itself (for entryTrigger/indicators)
        tf = params.get("timeframe") or node.get("timeframe")
        if tf and isinstance(tf, str):
            required.add(f"kline_{tf}")

        # Recursively traverse all nested structures
        for value in node.values():
            if isinstance(value, (dict, list)):
                self._extract_required_data_from_config(value, required)

    @property
    def requires_spot_orderbook(self) -> bool:
        """
        Returns True if the strategy requires a spot order book for analysis.
        Used for conditional inclusion of companion orderbook subscription.
        """
        visual_config = self._instance_params.get("config", {})
        if not visual_config or not isinstance(visual_config, dict):
            return False

        # Blocks requiring companion (spot) order book
        SPOT_OB_BLOCKS = {
            "order_book_zone",
            "l2_microstructure",
            "l2_microstructure_check",
        }

        return self._has_block_type(visual_config, SPOT_OB_BLOCKS)

    def _has_block_type(self, node: Any, block_types: Set[str]) -> bool:
        """Checks for the presence of blocks of the specified types in the configuration."""
        if isinstance(node, dict):
            if node.get("type") in block_types:
                return True
            for value in node.values():
                if self._has_block_type(value, block_types):
                    return True
        elif isinstance(node, list):
            for item in node:
                if self._has_block_type(item, block_types):
                    return True
        return False

    def _recursively_find_required_metrics(self, node: Any, required: Set[str]):
        """Recursively traverses JSON and searches for used metrics/indicators."""
        if isinstance(node, dict):
            # 1. Look for dynamic values referencing indicators
            if node.get("source") == "indicator" and isinstance(node.get("key"), str):
                required.add(node["key"])

            # 2. Look for blocks that implicitly use indicators
            node_type = node.get("type")
            params = node.get("params", {})
            if node_type == "trend_direction":
                if isinstance(params.get("sma_fast_period"), int):
                    required.add(f"SMA_{params['sma_fast_period']}")
                if isinstance(params.get("sma_slow_period"), int):
                    required.add(f"SMA_{params['sma_slow_period']}")
                if isinstance(params.get("rsi_period"), int):
                    required.add(f"RSI_{params['rsi_period']}")

            elif node_type == "tape_analysis":
                window = params.get("time_window_sec", 5)
                metric_suffixes = [
                    "buy_volume_usd",
                    "sell_volume_usd",
                    "total_volume_usd",
                    "buy_count",
                    "sell_count",
                    "total_count",
                    "delta_volume_usd",
                    "delta_count",
                    "buy_sell_ratio_volume",
                    "buy_sell_ratio_count",
                    "avg_trade_size_usd",
                ]
                for suffix in metric_suffixes:
                    required.add(f"tape_{suffix}_{window}s")

                avg_lookback = 60  # Must match DataConsumer
                accel_suffixes = ["volume", "count"]
                for suffix in accel_suffixes:
                    required.add(f"tape_accel_mult_{suffix}_{window}s_{avg_lookback}s")

            # 3. Recursively traverse all child nodes
            for key, value in node.items():
                self._recursively_find_required_metrics(value, required)

        elif isinstance(node, list):
            for item in node:
                self._recursively_find_required_metrics(item, required)

    @property
    def required_indicators(self) -> Set[str]:
        """Collect required indicators/metrics for precomputation."""
        if self._required_indicators_cache is not None:
            return set(self._required_indicators_cache)

        strategy_config = self._instance_params.get("config", {})
        if strategy_config and isinstance(strategy_config, dict):
            required = set()
            self._recursively_find_required_metrics(strategy_config, required)
            self._required_indicators_cache = set(required)
            return set(required)

        if self.NAME != "VisualBuilderStrategy":
            required = {"SMA_10", "SMA_50", "RSI_14", "ATR_14"}
        else:
            required = set()
        self._required_indicators_cache = set(required)
        return set(required)

    def check_on_screener_update(
        self, position: BasePosition, screener_data: Dict[str, Any]
    ) -> Tuple[str, Optional[float]]:
        """
        Checks for mode change.
        Returns a tuple: (ACTION_TYPE, PRICE).
        ACTION_TYPE: 'NONE', 'MOVE_SL', 'CLOSE_POSITION'.
        """
        if not self.breakeven_on_regime_change:
            return "NONE", None

        # Checking for the presence of mode information
        entry_regime = position.signal_details.get("oracle_regime")
        current_regime = screener_data.get("oracle_regime")

        # Get the current price from the screener to estimate PnL
        current_price = screener_data.get("close") or screener_data.get("last_price")

        if entry_regime is None or current_regime is None or current_price is None:
            return "NONE", None

        # If the mode has changed (e.g., from 1 to 0)
        if current_regime != entry_regime:
            logger.info(
                f"[{position.symbol}] Oracle regime changed {entry_regime} -> {current_regime}. Evaluating exit strategy."
            )

            # 1. Checking if we are in profit or loss
            is_winning = False
            if position.direction == SignalDirection.LONG:
                is_winning = current_price > position.entry_price
            elif position.direction == SignalDirection.SHORT:
                is_winning = current_price < position.entry_price

            # ADDED: Detailed logging for debugging
            logger.warning(
                f"[{position.symbol}|REGIME_CHANGE_DEBUG] "
                f"Direction={position.direction.name}, Entry={position.entry_price}, "
                f"CurrentPrice={current_price}, is_winning={is_winning}, "
                f"is_stop_at_be={getattr(position, 'is_stop_at_be', False)}"
            )

            # 2. Decision-making logic
            if is_winning:
                # If we are in profit -> Trying to set break-even
                if getattr(position, "is_stop_at_be", False):
                    logger.info(
                        f"[{position.symbol}] Already at BE, no action needed on regime change."
                    )
                    return "NONE", None  # Already at BE, doing nothing

                be_price = position.entry_price
                # Check: are we not worsening the current stop
                should_move = position.current_sl_price is None
                if (
                    not should_move
                    and position.direction == SignalDirection.LONG
                    and position.current_sl_price < be_price
                ):
                    should_move = True
                elif (
                    not should_move
                    and position.direction == SignalDirection.SHORT
                    and position.current_sl_price > be_price
                ):
                    should_move = True

                if should_move:
                    logger.info(
                        f"[{position.symbol}] Moving SL to BE ({be_price}) on regime change (winning trade)."
                    )
                    return "MOVE_SL", be_price
                else:
                    logger.info(
                        f"[{position.symbol}] SL already at or better than BE. No action."
                    )
                    return "NONE", None
            else:
                # If we are in the red (or near zero) when changing mode -> EVACUATION
                logger.info(
                    f"[{position.symbol}] Regime ended while losing (Entry: {position.entry_price}, Curr: {current_price}). Signal CLOSE."
                )
                return "CLOSE_POSITION", None

        return "NONE", None

    async def check_signal(
        self,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        prev_pair_info: Optional[Dict[str, Any]] = None,
        analysis_level: Literal[
            "minute_bar_filter", "second_bar_trigger"
        ] = "second_bar_trigger",
    ) -> Tuple[Optional[StrategySignal], float, Optional[Dict]]:
        if not self.enabled:
            return None, 0.0, None
        start_ts = time.perf_counter()
        try:
            return self.check_signal_sync(
                pair_info, market_data, prev_pair_info, analysis_level=analysis_level
            )
        except Exception as e:
            logger.error(
                f"[{self.NAME}] Error in check_signal_sync from async wrapper: {e}",
                exc_info=True,
            )
            return None, 0.0, None
        finally:
            elapsed_ms = (time.perf_counter() - start_ts) * 1000.0
            slow_threshold_ms = float(
                getattr(config, "STRATEGY_CHECK_SLOW_LOG_MS", 25.0)
            )
            if elapsed_ms >= slow_threshold_ms:
                logger.warning(
                    f"[{self.NAME}:{pair_info.get('symbol', 'Unknown')}] "
                    f"Slow strategy check: {elapsed_ms:.2f}ms (threshold={slow_threshold_ms:.2f}ms)"
                )

    def check_signal_sync(
        self,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        prev_pair_info: Optional[Dict[str, Any]] = None,
        analysis_level: Literal[
            "minute_bar_filter", "second_bar_trigger"
        ] = "second_bar_trigger",
    ) -> Tuple[Optional[StrategySignal], float, Optional[Dict]]:
        # Checking inheritance, not the name
        visual_config = self._instance_params.get("config")
        is_visual_strategy = visual_config is not None and isinstance(
            visual_config, dict
        )
        logger.debug(
            "check_signal_sync symbol=%s is_visual=%s enabled=%s",
            pair_info.get("symbol"),
            is_visual_strategy,
            self.enabled,
        )

        if is_visual_strategy:
            if isinstance(self._instance_params, dict):
                # Ensure that config is available
                config_val = self._instance_params.get("config", {})
                if isinstance(config_val, dict):
                    # Ensure candle_timeframe is present in pair_info to resolve dynamic values (operands)
                    if "candle_timeframe" not in pair_info:
                        pair_info["candle_timeframe"] = (
                            config_val.get("tradingTimeframe")
                            or config_val.get("entryTrigger", {}).get("timeframe")
                            or "1m"
                        )

        if not self.enabled:
            return None, 0.0, None

        symbol = pair_info.get("symbol", "Unknown")
        log_prefix = f"[{self.NAME}:{symbol}]"

        # CANDLE SKIP CHECK (for all strategy types)
        current_idx = pair_info.get("current_candle_index")
        if current_idx is not None and current_idx == self._last_closed_candle_index:
            logger.info(
                f"{log_prefix} Skipping signal check: position already closed on candle {current_idx}"
            )
            return None, 0.0, None

        # The logic below uses this flag
        if is_visual_strategy:
            visual_config = self._instance_params.get("config")
            if visual_config and isinstance(visual_config, dict):
                log_prefix = f"[{self.NAME} (Visual):{symbol}]"
                logger.debug(
                    f"{log_prefix} Detected visual builder config. Executing interpreter."
                )
                try:
                    # Check if we have already closed on this candle
                    # (The logic below has already been moved up, but we'll keep logging for Visual mode if needed)
                    if visual_config.get("signal_source") == "tradingview_webhook":
                        return (
                            None,
                            0.0,
                            {"rejection_reason": "external_signal_required"},
                        )

                    signal, weight, trace = self._execute_visual_strategy(
                        visual_config,
                        pair_info,
                        market_data,
                        prev_pair_info,
                        analysis_level=analysis_level,
                    )
                    return signal, weight, trace
                except Exception as e_visual:
                    logger.error(
                        f"{log_prefix} Error executing visual strategy: {e_visual}",
                        exc_info=True,
                    )
                    return None, 0.0, None
            else:
                if not visual_config:
                    logger.warning(
                        f"{log_prefix} No nested 'config' key found in strategy params."
                    )
                return None, 0.0, None

        else:
            trace_root = {
                "id": "root",
                "type": "AND",
                "result": False,
                "children": [],
                "details": {},
            }
            total_weight_achieved = 0.0
            try:
                foundations, foundation_trace_nodes = self.check_foundations(
                    pair_info, market_data
                )
                trace_root["children"].extend(foundation_trace_nodes)

                if foundations is None:
                    logger.error(f"{log_prefix} check_foundations returned None!")
                    return None, 0.0, trace_root

                met_foundations_details_for_log = {}

                if not self.foundation_weights:
                    logger.warning(
                        f"{log_prefix} self.foundation_weights are not configured. Skipping weighted check."
                    )
                else:
                    logger.debug(
                        f"Checking foundation weights. Weights: {self.foundation_weights}, Threshold: {self.min_total_foundation_weight_threshold}"
                    )
                    for found_key, weight_value in self.foundation_weights.items():
                        is_met = False
                        foundation_value = foundations.get(found_key)
                        if found_key == FOUNDATION_ORDERBOOK:
                            is_met = isinstance(
                                foundation_value, OrderbookAnalysisResult
                            ) and bool(
                                foundation_value.nearest_support
                                or foundation_value.nearest_resistance
                            )
                        elif isinstance(foundation_value, bool):
                            is_met = foundation_value

                        if is_met:
                            total_weight_achieved += weight_value
                            met_foundations_details_for_log[found_key] = (
                                f"+{weight_value}"
                            )
                        else:
                            met_foundations_details_for_log[found_key] = "(-)"

                    current_threshold = self.min_total_foundation_weight_threshold
                    if total_weight_achieved < current_threshold:
                        logger.info(
                            f"{log_prefix} Rejected: Insufficient foundation weight ({total_weight_achieved:.1f} < {current_threshold:.1f})."
                        )
                        return None, total_weight_achieved, trace_root
                    else:
                        logger.info(
                            f"{log_prefix} PASSED foundation weight check ({total_weight_achieved:.1f} >= {current_threshold:.1f})."
                        )

                foundations["foundation_total_weight"] = total_weight_achieved
                foundations["foundation_met_details_log"] = (
                    met_foundations_details_for_log
                )

                signal = self._check_specific_signal_logic(
                    pair_info, market_data, foundations
                )

                if signal:
                    if signal.details is None:
                        signal.details = {}
                    signal.details["decision_trace"] = trace_root
                    return signal, total_weight_achieved, trace_root

            except Exception as e_sync:
                logger.error(
                    f"{log_prefix} Error in classic check_signal_sync: {e_sync}",
                    exc_info=True,
                )

            return None, total_weight_achieved, trace_root

    async def manage_position(
        self,
        position: BasePosition,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        prev_pair_info: Optional[Dict[str, Any]],
    ) -> Tuple[BasePosition, Optional[Dict[str, Any]]]:
        """
        Public method for managing an open position.
        FINAL FIXED VERSION: More reliable and consistent exit check logic.
        """
        log_prefix = f"[PM_DEBUG|{position.symbol}|{position.client_order_id[:8] if position.client_order_id else 'None'}]"
        current_sl_price = (
            position.current_sl_price if position_has_active_stop(position) else None
        )
        logger.debug(
            f"{log_prefix} manage_position ENTRY at {pair_info.get('timestamp_dt')}. High: {pair_info.get('high')}, Low: {pair_info.get('low')}"
        )
        logger.debug(
            f"{log_prefix} Position State BEFORE: RemQty={position.remaining_quantity:.4f}, SL={format_optional_price(current_sl_price)}, TP={position.initial_take_profit}, Partials={getattr(position, 'partial_targets', 'N/A')}"
        )

        logger.debug(
            f"[DIAGNOSTIC-STEP-1] ENTERING MANAGE_POSITION | "
            f"Candle: {pair_info.get('current_candle_index')} | "
            f"Partial Fills: {len(getattr(position, 'partial_fills', []))} | "
            f"Is BE: {getattr(position, 'is_stop_at_be', 'N/A')}"
        )

        k_high = pair_info.get("high")
        k_low = pair_info.get("low")
        timestamp_dt = pair_info.get("timestamp_dt")

        if k_high is None or k_low is None or timestamp_dt is None:
            return position, None

        # Recalculating targets after averaging (if TP/SL are reset by the controller)
        if position.initial_take_profit is None:
            position = self._recalculate_targets_if_needed(
                position, pair_info, market_data
            )

        # In live mode, SL and TP orders are placed on the exchange and executed there.
        # manage_position MUST NOT return exit_details for SL/TP in live,
        # otherwise the controller will close the position at MARKET (at the current price),
        # and not by order price!
        #
        # is_live_mode is passed from the controller via pair_info
        is_live_mode = pair_info.get("is_live_mode", False)

        # 1. Checking stop-loss (ONLY for backtest)
        if not is_live_mode:
            if current_sl_price is not None and (
                (
                    position.direction == SignalDirection.LONG
                    and k_low <= current_sl_price
                )
                or (
                    position.direction == SignalDirection.SHORT
                    and k_high >= current_sl_price
                )
            ):
                reason = "STOP_LOSS" if not position.is_stop_at_be else "SL_AT_BE"
                exit_details = {
                    "reason": reason,
                    "exit_price": current_sl_price,
                    "timestamp": timestamp_dt,
                }
                logger.debug(
                    f"{log_prefix} Position CLOSED by SL/BE. Reason: {reason}, Exit Price: {current_sl_price:.4f}"
                )

                # Remembering the closing candle
                current_idx = pair_info.get("current_candle_index")
                if current_idx is not None:
                    self._last_closed_candle_index = current_idx

                return position, exit_details

        # 2. Then checking partial take-profits (ONLY for backtest)
        if not is_live_mode and hasattr(position, "partial_targets"):
            unhit_targets = [
                t for t in getattr(position, "partial_targets", []) if not t[2]
            ]
            if unhit_targets and position.remaining_quantity > 0:
                sorted_targets = sorted(
                    unhit_targets,
                    key=lambda x: x[0],
                    reverse=(position.direction == SignalDirection.SHORT),
                )

                targets_hit_this_candle = []

                for pt_price, pt_fraction, _ in sorted_targets:
                    if position.remaining_quantity <= 1e-9:
                        break
                    hit_price = None
                    if (
                        position.direction == SignalDirection.LONG
                        and k_high >= pt_price
                    ):
                        hit_price = pt_price
                    elif (
                        position.direction == SignalDirection.SHORT
                        and k_low <= pt_price
                    ):
                        hit_price = pt_price

                    if hit_price:
                        logger.info(
                            f"{log_prefix} Partial TP HIT at price {hit_price:.4f} (Target: {pt_price:.4f}). Closing {pt_fraction * 100:.2f}% of initial quantity."
                        )
                        qty_to_close = position.initial_quantity * pt_fraction
                        actual_qty_closed = min(
                            qty_to_close, position.remaining_quantity
                        )

                        exit_execution = {
                            "timestamp": timestamp_dt,
                            "price": hit_price,
                            "quantity": actual_qty_closed,
                            "type": "EXIT",
                        }
                        position.executions.append(exit_execution)

                        position.partial_fills.append(
                            {
                                "price": hit_price,
                                "qty": actual_qty_closed,
                                "pnl": 0,
                                "commission": 0,
                            }
                        )
                        position.remaining_quantity -= actual_qty_closed

                        if hasattr(position, "num_partial_tp_hits"):
                            position.num_partial_tp_hits += 1

                        targets_hit_this_candle.append(pt_price)

                        if (
                            position.move_sl_to_be_enabled
                            and not position.is_stop_at_be
                        ):
                            logger.info(
                                f"{log_prefix} Move to Breakeven TRIGGERED after partial TP hit (from initialization block)."
                            )
                            be_offset_ticks = getattr(config, "BE_SL_OFFSET_TICKS", 1)
                            offset = be_offset_ticks * pair_info.get("tick_size", 0)
                            be_price_raw = (
                                position.entry_price + offset
                                if position.direction == SignalDirection.LONG
                                else position.entry_price - offset
                            )
                            be_rounding = (
                                ROUND_UP
                                if position.direction == SignalDirection.LONG
                                else ROUND_DOWN
                            )
                            be_price = round_price_by_tick(
                                be_price_raw, pair_info.get("tick_size"), be_rounding
                            )
                            if be_price:
                                position = self._modify_position(
                                    position, new_sl=be_price
                                )
                                position.is_stop_at_be = True

                if targets_hit_this_candle:
                    new_partial_targets = []
                    for p, f, h in position.partial_targets:
                        if p in targets_hit_this_candle:
                            new_partial_targets.append((p, f, True))
                        else:
                            new_partial_targets.append((p, f, h))
                    if hasattr(position, "partial_targets"):
                        position.partial_targets = new_partial_targets

        logger.debug(
            f"[DIAGNOSTIC-STEP-2] AFTER PARTIAL TP CHECK | "
            f"Candle: {pair_info.get('current_candle_index')} | "
            f"Partial Fills: {len(getattr(position, 'partial_fills', []))} | "
            f"Is BE: {getattr(position, 'is_stop_at_be', 'N/A')}"
        )

        # 3. ONLY NOW, when the position state is up-to-date, we execute custom blocks from JSON.
        # positionManagement blocks must be processed for ANY strategy if they are present in the configuration
        if position.remaining_quantity > 0:
            visual_config_orig = self._instance_params.get("config")

            # DIAGNOSTIC LOG: Why is positionManagement not being called?
            config_keys = (
                list(visual_config_orig.keys())
                if visual_config_orig and isinstance(visual_config_orig, dict)
                else "N/A (config is None or not dict)"
            )
            has_pm = (
                "positionManagement" in visual_config_orig
                if visual_config_orig and isinstance(visual_config_orig, dict)
                else False
            )
            logger.debug(
                f"[PM_CONFIG_DEBUG|{position.symbol}] Strategy: {self.NAME}, "
                f"ConfigKeys: {config_keys}, HasPM: {has_pm}"
            )

            if (
                visual_config_orig
                and isinstance(visual_config_orig, dict)
                and "positionManagement" in visual_config_orig
            ):
                logger.debug(
                    f"[DIAGNOSTIC-STEP-3] BEFORE CALLING JSON LOGIC | Strategy: {self.NAME}, Blocks: {len(visual_config_orig.get('positionManagement', []))}"
                )

                position, exit_details = await self._execute_position_management(
                    visual_config_orig, position, pair_info, market_data, prev_pair_info
                )
                if exit_details:
                    # Remembering the closing candle
                    current_idx = pair_info.get("current_candle_index")
                    if current_idx is not None:
                        self._last_closed_candle_index = current_idx
                    return position, exit_details

        # 4. Checking the main/final take-profit (ONLY for backtest)
        if not is_live_mode:
            if position.remaining_quantity > 1e-9 and position.initial_take_profit:
                if (
                    position.direction == SignalDirection.LONG
                    and k_high >= position.initial_take_profit
                ) or (
                    position.direction == SignalDirection.SHORT
                    and k_low <= position.initial_take_profit
                ):
                    exit_details = {
                        "reason": "TAKE_PROFIT",
                        "exit_price": position.initial_take_profit,
                        "timestamp": timestamp_dt,
                    }
                    logger.debug(
                        f"{log_prefix} Position CLOSED by TP. Reason: TAKE_PROFIT, Exit Price: {position.initial_take_profit:.4f}"
                    )

                    # Remembering the closing candle
                    current_idx = pair_info.get("current_candle_index")
                    if current_idx is not None:
                        self._last_closed_candle_index = current_idx

                    return position, exit_details

            # 5. Check if the position closed due to the LAST partial take (ONLY for backtest).
            if position.remaining_quantity <= 1e-9 and len(position.partial_fills) > 0:
                last_fill = position.partial_fills[-1]
                exit_details = {
                    "reason": "FINAL_TAKE_PROFIT",
                    "exit_price": last_fill["price"],
                    "timestamp": timestamp_dt,
                }

                # Remembering the closing candle
                current_idx = pair_info.get("current_candle_index")
                if current_idx is not None:
                    self._last_closed_candle_index = current_idx

                return position, exit_details

        logger.debug(
            f"{log_prefix} Position State AFTER: RemQty={position.remaining_quantity:.4f}, SL={format_optional_price(position.current_sl_price if position_has_active_stop(position) else None)}, TP={position.initial_take_profit}"
        )
        return position, None

    async def _execute_pm_action(
        self,
        action: Dict[str, Any],
        position: BasePosition,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
    ) -> Tuple[BasePosition, Optional[Dict[str, Any]]]:
        """
        Performs a specific action from the 'then_actions' block in 'conditional_management'.
        """
        action_type = action.get("type")
        params = action.get("params", {})
        context = {
            "pair_info": pair_info,
            "market_data": market_data,
            "position": position,
        }
        exit_details = None

        log_prefix = f"[{self.NAME} (Visual):{position.symbol}:PM_Action]"

        if action_type == "modify_stop_loss":
            new_sl_price_cfg = params.get("new_sl_price")
            if new_sl_price_cfg:
                new_sl_price = self._resolve_value(new_sl_price_cfg, context)
                if new_sl_price is not None:
                    logger.info(
                        f"{log_prefix} Executing modify_stop_loss. New SL: {new_sl_price}"
                    )
                    position = self._modify_position(
                        position, new_sl=float(new_sl_price)
                    )
                else:
                    logger.warning(
                        f"{log_prefix} Could not resolve new_sl_price for modify_stop_loss."
                    )

        elif action_type == "modify_take_profit":
            new_tp_price_cfg = params.get("new_tp_price")
            if new_tp_price_cfg:
                new_tp_price = self._resolve_value(new_tp_price_cfg, context)
                if new_tp_price is not None:
                    logger.info(
                        f"{log_prefix} Executing modify_take_profit. New TP: {new_tp_price}"
                    )
                    position = self._modify_position(
                        position, new_tp=float(new_tp_price)
                    )
                else:
                    logger.warning(
                        f"{log_prefix} Could not resolve new_tp_price for modify_take_profit."
                    )

        elif action_type == "close_position":
            logger.info(f"{log_prefix} Executing close_position.")
            exit_price = (
                pair_info.get("last_price")
                or pair_info.get("close")
                or getattr(position, "current_price", None)
                or position.entry_price
            )
            exit_details = {
                "reason": "PM_ACTION_CLOSE",  # New reason for clarity
                "exit_price": exit_price,
                "timestamp": pair_info["timestamp_dt"],
            }

        elif action_type == "trailing_stop":
            logger.debug(f"{log_prefix} Executing trailing_stop action.")
            position = self._handle_trailing_stop(action, position, pair_info)

        elif action_type == "move_to_breakeven":
            logger.debug(f"{log_prefix} Executing move_to_breakeven action.")
            position = self._handle_move_to_breakeven(action, position, pair_info)

        else:
            logger.warning(f"{log_prefix} Unsupported PM action type: {action_type}")

        return position, exit_details

    def _modify_position(
        self,
        position: BasePosition,
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None,
    ) -> BasePosition:
        """
        Helper method for changing SL/TP of an open position.
        Works directly with the position state object.
        """
        if new_sl is not None:
            logger.info(
                f"[{position.symbol}] Strategy signals SL modification to {new_sl:.4f}"
            )
            position.current_sl_price = new_sl
        if new_tp is not None:
            logger.info(
                f"[{position.symbol}] Strategy signals TP modification to {new_tp:.4f}"
            )
            # In our model, there is one main TP, partials are separate
            position.initial_take_profit = new_tp
        return position

    def _handle_trailing_stop(
        self, block: Dict[str, Any], position: BasePosition, pair_info: Dict[str, Any]
    ) -> BasePosition:
        """
        Processes trailing stop logic.
        Supports two modes:
        - 'local' (default): the bot locally recalculates SL and moves it on the exchange
        - 'exchange': trailing is managed by the exchange via TRAILING_STOP_MARKET, local logic is skipped
        """
        params = block.get("params", {})

        # Checking trailing mode
        trail_mode = params.get("mode", "local")
        if trail_mode == "exchange":
            # In 'exchange' mode, trailing is managed by the exchange, we do not process it locally
            return position

        ts_type = self._normalize_trailing_stop_type(params.get("type", "ATR"))
        k_high = pair_info.get("high")
        k_low = pair_info.get("low")
        if not k_high or not k_low:
            return position

        potential_new_sl = None
        try:
            if position.direction == SignalDirection.LONG:
                if ts_type == "ATR":
                    value = float(params.get("value", 2.5))
                    atr = pair_info.get("atr")
                    if not atr:
                        return position
                    potential_new_sl = k_high - (atr * value)
                elif ts_type == "Percentage":
                    value = float(params.get("value", 1.5))
                    if value <= 0:
                        return position
                    potential_new_sl = k_high * (1 - value / 100.0)
                elif ts_type == "MA":
                    period = int(params.get("period", 20))
                    ma_key = f"SMA_{period}"
                    if ma_key not in pair_info:
                        return position
                    potential_new_sl = pair_info[ma_key]

                if potential_new_sl and (
                    position.current_sl_price is None
                    or potential_new_sl > position.current_sl_price
                ):
                    position = self._modify_position(position, new_sl=potential_new_sl)

            elif position.direction == SignalDirection.SHORT:
                if ts_type == "ATR":
                    value = float(params.get("value", 2.5))
                    atr = pair_info.get("atr")
                    if not atr:
                        return position
                    potential_new_sl = k_low + (atr * value)
                elif ts_type == "Percentage":
                    value = float(params.get("value", 1.5))
                    if value <= 0:
                        return position
                    potential_new_sl = k_low * (1 + value / 100.0)
                elif ts_type == "MA":
                    period = int(params.get("period", 20))
                    ma_key = f"SMA_{period}"
                    if ma_key not in pair_info:
                        return position
                    potential_new_sl = pair_info[ma_key]

                if potential_new_sl and (
                    position.current_sl_price is None
                    or potential_new_sl < position.current_sl_price
                ):
                    position = self._modify_position(position, new_sl=potential_new_sl)

        except (ValueError, TypeError) as e:
            logger.error(
                f"[{position.symbol}] Error in trailing stop params: {params}. Error: {e}"
            )

        return position

    def _handle_move_to_breakeven(
        self, block: Dict[str, Any], position: BasePosition, pair_info: Dict[str, Any]
    ) -> BasePosition:
        """
        Processes the break-even logic.
        FIXED VERSION: Added fallback for initial_stop_loss and improved diagnostics.
        """
        log_prefix = f"[{position.symbol}|BE_DEBUG]"

        params = block.get("params", {})
        target_type = params.get("target_type", "atr_multiplier")
        target_value = float(params.get("target_value", 1.0))
        offset_pips = int(params.get("offset_pips", 2))

        # DIAGNOSTICS
        initial_sl_raw = getattr(position, "initial_stop_loss", None)
        entry_price = position.entry_price

        # Skipping if already at BE
        if getattr(position, "is_stop_at_be", False):
            # logger.debug(f"{log_prefix} Skipping: position is already at break-even.")
            return position

        tick_size = pair_info.get("tick_size")
        price_for_check = (
            pair_info.get("high")
            if position.direction == SignalDirection.LONG
            else pair_info.get("low")
        )

        if not all([price_for_check, entry_price, tick_size]):
            logger.warning(
                f"{log_prefix} Insufficient market data. Price={price_for_check}, Entry={entry_price}, TickSize={tick_size}. Skipping BE check."
            )
            return position

        # Calculation of current profit per unit of volume (maximum per candle, as we take High/Low)
        pnl_per_unit = (
            price_for_check - entry_price
            if position.direction == SignalDirection.LONG
            else entry_price - price_for_check
        )

        # EXTENDED DIAGNOSTICS: Always log the state when entering the function
        logger.debug(
            f"{log_prefix} BE_CHECK_ENTRY | target_type={target_type}, target_value={target_value}, "
            f"entry={entry_price}, price_for_check={price_for_check}, pnl_per_unit={pnl_per_unit:.6f}, "
            f"initial_sl={initial_sl_raw}, current_sl={position.current_sl_price}, "
            f"candle_time={pair_info.get('timestamp_dt')}"
        )

        # If we are not in profit yet, there is no point in checking further
        if pnl_per_unit <= 0:
            return position

        activation_threshold_met = False

        # R:R LOGIC
        if target_type in ["unrealized_pnl_rr", "rr_multiplier"]:
            # Fallback for initial_stop_loss
            # If the initial stop is not saved, but we are not yet in BE, consider the current stop as the initial risk.
            calc_initial_sl = initial_sl_raw
            if calc_initial_sl is None and not getattr(
                position, "is_stop_at_be", False
            ):
                calc_initial_sl = position.current_sl_price
                logger.debug(
                    f"{log_prefix} initial_stop_loss is None. Using current_sl_price ({calc_initial_sl}) as proxy for risk calculation."
                )

            if calc_initial_sl is None or entry_price is None:
                logger.warning(
                    f"{log_prefix} Unable to calculate R:R. No initial_sl and entry_price."
                )
                return position

            # Risk distance (1R)
            risk_distance = abs(entry_price - calc_initial_sl)

            if risk_distance < 1e-9:
                logger.warning(
                    f"{log_prefix} Risk distance is zero/near-zero ({risk_distance:.8f}). Cannot calc R:R."
                )
                return position

            current_rr = pnl_per_unit / risk_distance

            # Log only if we are approaching the target (e.g., > 50% of the target) to avoid spamming
            if current_rr > target_value * 0.5:
                logger.debug(
                    f"{log_prefix} R:R Check. PnL: {pnl_per_unit:.4f}, RiskDist: {risk_distance:.4f}, CurrRR: {current_rr:.2f} / Target: {target_value:.2f}"
                )

            if current_rr >= target_value:
                activation_threshold_met = True

        elif target_type == "atr_multiplier":
            atr = position.entry_atr
            if not atr:
                return position
            activation_threshold = atr * target_value
            if pnl_per_unit >= activation_threshold:
                activation_threshold_met = True

        elif target_type == "percent_from_price":
            activation_threshold = entry_price * (target_value / 100.0)
            if pnl_per_unit >= activation_threshold:
                activation_threshold_met = True

        else:
            logger.warning(f"{log_prefix} Unknown target_type: {target_type}")
            return position

        # CARRYOVER EXECUTION
        if activation_threshold_met:
            offset_value = offset_pips * tick_size

            # Calculating the BE price: Entry +/- offset
            raw_new_sl_price = (
                entry_price + offset_value
                if position.direction == SignalDirection.LONG
                else entry_price - offset_value
            )

            # Round in the SAFE direction (to accurately cover commissions if the offset implies it)
            # For Long: round up (above entry), For Short: round down (below entry)
            rounding_direction = (
                ROUND_UP if position.direction == SignalDirection.LONG else ROUND_DOWN
            )
            new_sl_price = round_price_by_tick(
                raw_new_sl_price, tick_size, rounding_direction
            )

            if new_sl_price is None:
                return position

            # Checking if the new stop is actually better than the current one
            is_new_sl_better = (
                position.current_sl_price is None
                or (
                    position.direction == SignalDirection.LONG
                    and new_sl_price > position.current_sl_price
                )
                or (
                    position.direction == SignalDirection.SHORT
                    and new_sl_price < position.current_sl_price
                )
            )

            # Formulate a clear reason for the notification
            trigger_reason_map = {
                "unrealized_pnl_rr": f"R:R reached {target_value}:1",
                "rr_multiplier": f"R:R reached {target_value}:1",
                "atr_multiplier": f"ATR x{target_value}",
                "percent_from_price": f"{target_value}% of price",
            }
            be_reason = trigger_reason_map.get(target_type, target_type)

            if is_new_sl_better:
                # DETAILED LOG FOR DIAGNOSTICS
                logger.info(
                    f"{log_prefix} BE_TRIGGERED! | reason={be_reason} | "
                    f"target_type={target_type}, target_value={target_value}, "
                    f"entry={entry_price}, price_for_check={price_for_check}, "
                    f"pnl_per_unit={pnl_per_unit:.6f}, "
                    f"risk_distance={risk_distance if 'risk_distance' in locals() else 'N/A'}, "
                    f"current_rr={current_rr if 'current_rr' in locals() else 'N/A'}, "
                    f"old_sl={position.current_sl_price}, new_sl={new_sl_price}, "
                    f"candle_time={pair_info.get('timestamp_dt')}"
                )

                position = self._modify_position(position, new_sl=new_sl_price)
                position.is_stop_at_be = True
                # Save the reason for transmission to Telegram
                position.be_trigger_reason = be_reason
                # Saving diagnostic data for Telegram
                position.be_diagnostic_data = {
                    "initial_sl": initial_sl_raw,
                    "current_rr": current_rr if "current_rr" in locals() else None,
                    "pnl_per_unit": pnl_per_unit,
                    "price_for_check": price_for_check,
                    "candle_time": pair_info.get("timestamp_dt"),
                }
            else:
                # If the condition is met, but the current stop is already better (e.g., trailing moved it further),
                # just mark the flag that BE is passed.
                if not getattr(position, "is_stop_at_be", False):
                    logger.info(
                        f"{log_prefix} Threshold met, but current SL {position.current_sl_price} is already better than BE {new_sl_price}. Marking as BE."
                    )
                    position.is_stop_at_be = True
                    position.be_trigger_reason = f"{be_reason} (SL is already better)"
                    position.be_diagnostic_data = {
                        "initial_sl": initial_sl_raw,
                        "current_rr": current_rr if "current_rr" in locals() else None,
                        "pnl_per_unit": pnl_per_unit,
                        "price_for_check": price_for_check,
                        "candle_time": pair_info.get("timestamp_dt"),
                    }

        return position

    def _get_pm_conditions_root(
        self, block: Dict[str, Any], fallback_type: str = "AND"
    ) -> Dict[str, Any]:
        """
        Returns the canonical condition tree for PM blocks.
        Supports both the newer params.conditions shape and the older/editor
        children-based shape to preserve backward compatibility.
        """
        params_conditions = block.get("params", {}).get("conditions")
        if isinstance(params_conditions, dict) and params_conditions:
            return params_conditions

        children = block.get("children")
        if isinstance(children, list) and children:
            return {
                "id": f"{block.get('id', 'pm_block')}_conditions_root",
                "type": fallback_type,
                "children": children,
            }

        return {}

    @staticmethod
    def _config_uses_dca_or_grid_management(node: Any) -> bool:
        if isinstance(node, dict):
            if str(node.get("type", "")).lower() in {
                "dca_management",
                "grid_management",
            }:
                return True
            return any(
                BaseStrategy._config_uses_dca_or_grid_management(value)
                for value in node.values()
            )
        if isinstance(node, list):
            return any(
                BaseStrategy._config_uses_dca_or_grid_management(item) for item in node
            )
        return False

    def _uses_dca_or_grid_management(self) -> bool:
        visual_config = self._instance_params.get("config")
        if isinstance(visual_config, dict):
            management_config = visual_config.get(
                "positionManagement", visual_config.get("management", [])
            )
            return self._config_uses_dca_or_grid_management(management_config)
        return False

    def _recalculate_targets_if_needed(
        self,
        position: BasePosition,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
    ) -> BasePosition:
        """
        Recalculates TP/SL based on the initialization block from the config.
        Called when the controller has reset targets (e.g., after Scale-In).
        """
        visual_config = self._instance_params.get("config")
        if not visual_config or not isinstance(visual_config, dict):
            return position

        init_block = visual_config.get("initialization")
        if not init_block or init_block.get("type") != "open_position":
            return position

        params = init_block.get("params", {})
        log_prefix = f"[PM_RECALC|{position.symbol}]"

        try:
            tick_size = pair_info.get("tick_size")
            atr = pair_info.get("atr")
            entry_price = (
                position.entry_price
            )  # This is already the average price after Scale-In

            if not tick_size or tick_size <= 0:
                logger.warning(
                    f"{log_prefix} Cannot recalculate: tick_size missing or invalid."
                )
                return position

            # 1. Stop Loss recalculation (if required)
            sl_type = params.get("sl_type", "atr_multiplier")
            sl_value = self._resolve_value(
                params.get("sl_value", 1.5),
                {
                    "pair_info": pair_info,
                    "market_data": market_data,
                    "position": position,
                },
            )

            if sl_value is not None:
                is_averaging_down = getattr(position, "_is_averaging_down", False)
                preserve_sl = (
                    getattr(position, "current_sl_price", None) is not None
                    and is_averaging_down
                )
                if preserve_sl:
                    logger.info(
                        f"{log_prefix} Preserving original SL price: {position.current_sl_price:.8f} during DCA/Scale-In recalculation."
                    )
                else:
                    sl_price_raw = 0.0
                    no_sl_mode = False
                    if sl_type == "fixed_price":
                        sl_price_raw = float(sl_value)
                    elif sl_type == "atr_multiplier":
                        if float(sl_value) == 0:
                            no_sl_mode = True
                        elif atr and atr > 0:
                            sl_price_raw = (
                                entry_price - (atr * float(sl_value))
                                if position.direction == SignalDirection.LONG
                                else entry_price + (atr * float(sl_value))
                            )
                        else:
                            no_sl_mode = True
                    elif sl_type == "percent_from_price":
                        if float(sl_value) == 0:
                            no_sl_mode = True
                        else:
                            sl_price_raw = (
                                entry_price * (1 - float(sl_value) / 100.0)
                                if position.direction == SignalDirection.LONG
                                else entry_price * (1 + float(sl_value) / 100.0)
                            )

                    if not no_sl_mode:
                        sl_rounding = (
                            ROUND_DOWN
                            if position.direction == SignalDirection.LONG
                            else ROUND_UP
                        )
                        position.current_sl_price = round_price_by_tick(
                            sl_price_raw, tick_size, sl_rounding
                        )
                        logger.info(
                            f"{log_prefix} Recalculated SL: {position.current_sl_price:.8f}"
                        )

            # 2. Take Profit recalculation
            tp_type = params.get("tp_type", "rr_multiplier")
            tp_value = self._resolve_value(
                params.get("tp_value", 2.0),
                {
                    "pair_info": pair_info,
                    "market_data": market_data,
                    "position": position,
                },
            )

            if tp_value is not None:
                tp_price_raw = 0.0
                risk_distance_abs = (
                    abs(entry_price - position.current_sl_price)
                    if position.current_sl_price
                    else 0
                )

                if tp_type == "fixed_price":
                    tp_price_raw = float(tp_value)
                elif tp_type == "rr_multiplier":
                    tp_price_raw = (
                        entry_price + (risk_distance_abs * float(tp_value))
                        if position.direction == SignalDirection.LONG
                        else entry_price - (risk_distance_abs * float(tp_value))
                    )
                elif tp_type == "atr_multiplier":
                    if atr and atr > 0:
                        tp_price_raw = (
                            entry_price + (atr * float(tp_value))
                            if position.direction == SignalDirection.LONG
                            else entry_price - (atr * float(tp_value))
                        )
                elif tp_type == "percent_from_price":
                    tp_price_raw = (
                        entry_price * (1 + float(tp_value) / 100.0)
                        if position.direction == SignalDirection.LONG
                        else entry_price * (1 - float(tp_value) / 100.0)
                    )

                tp_rounding = (
                    ROUND_UP
                    if position.direction == SignalDirection.LONG
                    else ROUND_DOWN
                )
                position.initial_take_profit = round_price_by_tick(
                    tp_price_raw, tick_size, tp_rounding
                )
                logger.info(
                    f"{log_prefix} Recalculated TP: {position.initial_take_profit:.8f} (Entry: {entry_price:.8f}, Value: {tp_value})"
                )

            # 3. Recalculation of partial exits
            partial_exits_raw = params.get("partial_exits")
            if isinstance(partial_exits_raw, list) and len(partial_exits_raw) > 0:
                position.partial_targets = self._calculate_partial_targets_from_config(
                    entry_price=entry_price,
                    direction=position.direction,
                    partial_exits_raw=partial_exits_raw,
                    tick_size=tick_size,
                    stop_loss_price=position.current_sl_price,
                    atr_at_signal_time=atr,
                )
                # For compatibility with LivePosition, we also update partial_tp_orders in the controller later,
                # but here we are simply updating the data model.
                logger.info(
                    f"{log_prefix} Recalculated {len(position.partial_targets)} partial targets."
                )

        except Exception as e:
            logger.error(
                f"{log_prefix} Error in recalculating targets: {e}", exc_info=True
            )

        return position

    async def _execute_position_management(
        self,
        strategy_config: Dict[str, Any],
        position: BasePosition,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        prev_pair_info: Optional[Dict[str, Any]],
    ) -> Tuple[BasePosition, Optional[Dict[str, Any]]]:
        """
        Sequentially executes blocks from 'positionManagement'.
        Returns (updated_position, exit_details_or_None).
        """
        management_blocks = strategy_config.get("positionManagement", [])

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "PM CHECK | Candle: %s | Pos Entries: %s | Config State: %s",
                pair_info.get("current_candle_index", "N/A"),
                position.number_of_entries,
                json.dumps(management_blocks, default=str),
            )
        exit_details = None

        # Reset execution flags before each iteration
        for block in management_blocks:
            if "executed_this_candle" in block:
                del block["executed_this_candle"]

        for block in management_blocks:
            if position.remaining_quantity <= 0:
                break

            # Skip if already executed (for scale_in)
            if block.get("executed_this_candle"):
                continue

            block_type = block.get("type")

            if block_type == "trailing_stop":
                position = self._handle_trailing_stop(block, position, pair_info)

            elif block_type == "move_to_breakeven":
                position = self._handle_move_to_breakeven(block, position, pair_info)

            elif block_type == "conditional_exit":
                conditions = self._get_pm_conditions_root(block)
                if not conditions:
                    continue

                exit_condition_met, _ = self._evaluate_condition_tree(
                    conditions,
                    pair_info,
                    market_data,
                    prev_pair_info,
                    position=position,
                )

                if exit_condition_met:
                    logger.info(
                        f"[{position.symbol}] Conditional exit met. Signaling position closure."
                    )
                    exit_details = {
                        "reason": "CONDITIONAL_EXIT",
                        "exit_price": pair_info["last_price"],
                        "timestamp": pair_info["timestamp_dt"],
                    }
                    break  # Exiting the loop as the position is closing

            elif block_type == "conditional_management":
                if_conditions = block.get("if_conditions")
                if not if_conditions:
                    continue

                condition_met, _ = self._evaluate_condition_tree(
                    if_conditions,
                    pair_info,
                    market_data,
                    prev_pair_info,
                    position=position,
                )

                if condition_met:
                    logger.info(
                        f"[{position.symbol}] Conditional management condition met for block ID: {block.get('id')}"
                    )
                    then_actions = block.get("then_actions", [])
                    for action in then_actions:
                        position, action_exit_details = await self._execute_pm_action(
                            action, position, pair_info, market_data
                        )
                        if action_exit_details:
                            exit_details = action_exit_details
                            break
                    if exit_details:
                        break

            elif block_type == "scale_in":
                params = block.get("params", {})
                max_entries_from_json = params.get("max_entries", 1)
                current_entries = getattr(position, "number_of_entries", 1)
                if current_entries < max_entries_from_json:
                    scale_in_conditions_root = self._get_pm_conditions_root(block)
                    if scale_in_conditions_root:
                        condition_met, _ = self._evaluate_condition_tree(
                            scale_in_conditions_root,
                            pair_info,
                            market_data,
                            prev_pair_info,
                            position=position,
                        )
                        if condition_met:
                            logger.info(f"[{position.symbol}] Scale-in conditions met.")
                            add_size_pct = block.get("params", {}).get(
                                "add_size_pct_of_initial_risk", 100
                            )
                            position.scale_in_triggered = {"add_size_pct": add_size_pct}
                            block["executed_this_candle"] = True
                            break

            elif block_type == "dca_management":
                position = await self._handle_dca_management(
                    block, position, pair_info, market_data, prev_pair_info
                )

            elif block_type == "grid_management":
                position = await self._handle_grid_management(
                    block, position, pair_info, market_data
                )

        return position, exit_details

    def _calculate_weight_from_trace(
        self, trace: Dict[str, Any]
    ) -> Tuple[float, Dict[str, str]]:
        """
        Recursively traverses the entire trace tree and sums weights for all nodes
        that executed successfully (result: True) and whose ID is in the foundation_weights config.
        """
        total_weight = 0.0
        met_foundations_log = {}

        # Use a queue to traverse the tree without deep recursion
        nodes_to_visit = [trace]

        # PROTECTION AGAINST NONE
        weights = self.foundation_weights or {}

        while nodes_to_visit:
            current_node = nodes_to_visit.pop(0)

            node_id = current_node.get("id")
            node_result = current_node.get("result", False)

            # MAIN LOGIC: Checking if this node's ID is in the weights AND if it passed the check
            # USE THE SAFE VARIABLE weights INSTEAD OF self.foundation_weights
            legacy_weight_key = (
                f"w_{node_id}"
                if node_id and not str(node_id).startswith("w_")
                else None
            )
            weight_key = None
            if node_id in weights:
                weight_key = node_id
            elif legacy_weight_key and legacy_weight_key in weights:
                weight_key = legacy_weight_key

            if weight_key is not None and node_result:
                weight = weights[weight_key]
                total_weight += weight
                met_foundations_log[node_id] = f"+{weight}"

            # Add child nodes to the queue for checking
            if "children" in current_node:
                children = current_node.get("children")
                if children is not None:
                    nodes_to_visit.extend(children)
                else:
                    logger.warning(
                        f"[_calculate_weight_from_trace] Node {node_id} has 'children' key but value is None. Skipping children."
                    )

        return total_weight, met_foundations_log

    def _get_failure_reasons(self, trace: Dict[str, Any]) -> List[str]:
        """
        Recursively extracts failure reasons from the condition trace tree.
        Returns a list of strings describing failed indicators and their values.
        """
        if not trace or trace.get("result", True):
            return []

        children = trace.get("children", [])
        if not children:
            # Leaf node (specific indicator/filter)
            details = trace.get("details", {})
            node_type = trace.get("type", "Unknown")
            info = []
            for k, v in details.items():
                if k in ["params", "info", "rejection_reason", "message"]:
                    continue
                if isinstance(v, float):
                    info.append(f"{k}={v:.4f}")
                else:
                    info.append(f"{k}={v}")
            return [f"{node_type}({', '.join(info)})" if info else node_type]

        # Recursive traversal of children for AND/OR nodes
        reasons = []
        for child in children:
            reasons.extend(self._get_failure_reasons(child))

        # Return unique reasons to avoid duplication if the same filter is in different branches
        return list(dict.fromkeys(reasons))

    def build_external_signal(
        self,
        strategy_json: Dict[str, Any],
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        action: str,
        webhook_payload: Optional[Dict[str, Any]] = None,
        prev_pair_info: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[StrategySignal], Dict[str, Any]]:
        symbol = pair_info.get("symbol", "Unknown")
        log_prefix = f"[{self.NAME} (Webhook):{symbol}]"

        filters_root = strategy_json.get("filters")
        trace_filters = None
        if filters_root:
            filters_passed, trace_filters = self._evaluate_condition_tree(
                filters_root,
                pair_info,
                market_data,
                prev_pair_info,
                analysis_level="second_bar_trigger",
            )
            if not filters_passed:
                if trace_filters is None:
                    trace_filters = {}
                trace_filters["rejection_reason"] = "filter"
                logger.info(f"{log_prefix} Rejected by filters.")
                return None, trace_filters

        trace: Dict[str, Any] = {
            "id": "external_webhook",
            "type": "EXTERNAL_WEBHOOK",
            "result": True,
            "details": {"action": action},
            "children": [],
        }
        if trace_filters:
            trace["filters_trace"] = trace_filters

        required_regime = strategy_json.get("oracle_regime")
        current_regime = pair_info.get("oracle_regime")
        if required_regime is not None and current_regime != required_regime:
            trace["rejection_reason"] = "oracle_regime"
            trace["oracle_regime"] = current_regime
            logger.info(
                f"{log_prefix} Rejected by oracle_regime filter. Required={required_regime}, got={current_regime}"
            )
            return None, trace

        required_confidence = strategy_json.get("oracle_confidence")
        current_confidence = pair_info.get("oracle_confidence")
        current_confidence_value = (
            float(current_confidence)
            if isinstance(current_confidence, (int, float))
            else 0.0
        )
        required_confidence_value = None
        if required_confidence is not None:
            required_confidence_value = float(required_confidence)
            if required_confidence_value > 1:
                required_confidence_value = required_confidence_value / 100.0
        if (
            required_confidence_value is not None
            and current_confidence_value < required_confidence_value
        ):
            trace["rejection_reason"] = "oracle_confidence"
            trace["oracle_confidence"] = current_confidence_value
            logger.info(
                f"{log_prefix} Rejected by oracle_confidence filter. "
                f"Required={required_confidence_value}, got={current_confidence_value}"
            )
            return None, trace

        action_config = copy.deepcopy(
            strategy_json.get("initialization") or strategy_json.get("action")
        )
        if not action_config:
            logger.error(
                f"{log_prefix} No 'initialization' or 'action' block found to create signal."
            )
            return None, trace

        action_params = action_config.setdefault("params", {})
        configured_direction = str(action_params.get("direction", "LONG")).upper()
        external_direction = "LONG" if str(action).lower() == "buy" else "SHORT"
        if configured_direction == "BOTH":
            action_params["direction"] = external_direction
        elif configured_direction != external_direction:
            trace["rejection_reason"] = "direction_mismatch"
            trace["configured_direction"] = configured_direction
            logger.info(
                f"{log_prefix} Rejected by direction mismatch. "
                f"Configured={configured_direction}, webhook={external_direction}"
            )
            return None, trace

        context = {
            "pair_info": pair_info,
            "market_data": market_data,
            "trace": trace,
            "external_direction": external_direction,
        }
        signal = self._create_signal_from_action(action_config, context)
        if signal and isinstance(signal.details, dict):
            signal.details["signal_source"] = "tradingview_webhook"
            signal.details["strategy_config_id"] = pair_info.get("strategy_config_id")
            signal.details["webhook"] = webhook_payload or {}

        return signal, trace

    def _compile_condition_tree(self, node: Any) -> Optional[CompiledConditionNode]:
        if not isinstance(node, dict):
            return None
        node_type = node.get("type")
        raw_params = node.get("params")
        params = raw_params if isinstance(raw_params, dict) else {}
        checker = self.condition_checkers.get(node_type)
        evaluator = None
        if checker:

            def evaluator(
                *, pair_info, market_data, context, _checker=checker, _params=params
            ):
                return _checker(
                    pair_info=pair_info,
                    market_data=market_data,
                    params=_params,
                    context=context,
                )

        children_raw = node.get("children") or []
        children: List[CompiledConditionNode] = []
        if isinstance(children_raw, list):
            for child in children_raw:
                compiled_child = self._compile_condition_tree(child)
                if compiled_child is not None:
                    children.append(compiled_child)
        return CompiledConditionNode(
            node_id=node.get("id", "unknown"),
            node_type=node_type,
            params=params,
            analysis_level=node.get("analysis_level", "minute_bar_filter"),
            children=tuple(children),
            checker=checker,
            evaluator=evaluator,
        )

    def _ensure_compiled_fast_roots(self, strategy_json: Dict[str, Any]) -> None:
        config_id = id(strategy_json)
        if self._compiled_fast_config_id == config_id:
            return
        self._compiled_fast_config_id = config_id
        self._compiled_fast_filters_root = self._compile_condition_tree(
            strategy_json.get("filters")
        )
        self._compiled_fast_entry_root = self._compile_condition_tree(
            strategy_json.get("entryConditions")
        )

    def _should_use_live_fast_rejection_path(
        self,
        pair_info: Dict[str, Any],
        analysis_level: Literal["minute_bar_filter", "second_bar_trigger"],
    ) -> bool:
        if analysis_level != "second_bar_trigger":
            return False
        if (
            pair_info.get("is_backtest_mode")
            or pair_info.get("is_live_mode") is not True
        ):
            return False
        if bool(getattr(config, "TRACE_REJECTIONS_ENABLED", False)):
            return False
        return bool(getattr(config, "LIVE_FAST_SIGNAL_CHECK", True))

    def _execute_visual_strategy_fast_rejection(
        self,
        strategy_json: Dict[str, Any],
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        prev_pair_info: Optional[Dict[str, Any]],
        analysis_level: Literal[
            "minute_bar_filter", "second_bar_trigger"
        ] = "second_bar_trigger",
    ) -> Tuple[bool, float, Dict[str, Any]]:
        symbol = pair_info.get("symbol", "Unknown")
        log_prefix = f"[{self.NAME} (VisualFast):{symbol}]"
        self._ensure_compiled_fast_roots(strategy_json)

        filters_root = self._compiled_fast_filters_root
        if filters_root:
            filters_passed, trace_filters = self._evaluate_compiled_condition_tree_fast(
                filters_root,
                pair_info,
                market_data,
                prev_pair_info,
                analysis_level=analysis_level,
            )
            if not filters_passed:
                trace_filters["rejection_reason"] = "filter"
                logger.debug("%s Fast rejection by filters.", log_prefix)
                return False, 0.0, trace_filters

        entry_conditions_root = self._compiled_fast_entry_root
        if not entry_conditions_root:
            return False, 0.0, {"rejection_reason": "no_entry_conditions"}

        entry_conditions_passed, trace = self._evaluate_compiled_condition_tree_fast(
            entry_conditions_root,
            pair_info,
            market_data,
            prev_pair_info,
            analysis_level=analysis_level,
        )
        if not entry_conditions_passed:
            trace["rejection_reason"] = "entry_conditions"
            logger.debug("%s Fast rejection by entry conditions.", log_prefix)
            return False, 0.0, trace

        total_weight, _ = self._calculate_weight_from_trace(trace)
        current_threshold = self.min_total_foundation_weight_threshold
        effective_threshold = min(current_threshold, self.max_possible_expensive_weight)
        if total_weight < effective_threshold:
            trace["rejection_reason"] = "weight_threshold"
            logger.debug(
                "%s Fast rejection by weight %.4f < %.4f.",
                log_prefix,
                total_weight,
                effective_threshold,
            )
            return False, total_weight, trace

        return True, total_weight, trace

    def _execute_visual_strategy(
        self,
        strategy_json: Dict[str, Any],
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        prev_pair_info: Optional[Dict[str, Any]],
        analysis_level: Literal[
            "minute_bar_filter", "second_bar_trigger"
        ] = "second_bar_trigger",
    ) -> Tuple[Optional[StrategySignal], float, Dict]:
        symbol = pair_info.get("symbol", "Unknown")
        log_prefix = f"[{self.NAME} (Visual):{symbol}]"

        if self._should_use_live_fast_rejection_path(pair_info, analysis_level):
            rtl_state_snapshot = copy.deepcopy(self._rtl_state)
            active_tv_signals_snapshot = dict(self.active_tv_signals)
            signal_possible, fast_weight, fast_trace = (
                self._execute_visual_strategy_fast_rejection(
                    strategy_json,
                    pair_info,
                    market_data,
                    prev_pair_info,
                    analysis_level=analysis_level,
                )
            )
            if not signal_possible:
                return None, fast_weight, fast_trace
            self._rtl_state = rtl_state_snapshot
            self.active_tv_signals = active_tv_signals_snapshot

        # 1. Filter check
        filters_root = strategy_json.get("filters")
        trace_filters = None
        if filters_root:
            logger.debug(
                "%s --- Checking Filters (Level: %s) ---", log_prefix, analysis_level
            )
            filters_passed, trace_filters = self._evaluate_condition_tree(
                filters_root,
                pair_info,
                market_data,
                prev_pair_info,
                analysis_level=analysis_level,
            )
            if not filters_passed:
                reasons = self._get_failure_reasons(trace_filters)
                logger.info(
                    f"{log_prefix} >>> Filters result: FAILED. Reasons: {', '.join(reasons)}"
                )
                trace_filters["rejection_reason"] = "filter"
                return None, 0.0, trace_filters
            logger.debug("%s >>> Filters result: PASSED.", log_prefix)

        # 2. Checking entry conditions
        entry_conditions_root = strategy_json.get("entryConditions")
        if not entry_conditions_root:
            logger.info(f"{log_prefix} No entry conditions defined, no signal.")
            return None, 0.0, {}

        logger.debug(
            "%s --- Checking Entry Conditions (Level: %s) ---",
            log_prefix,
            analysis_level,
        )
        entry_conditions_passed, trace = self._evaluate_condition_tree(
            entry_conditions_root,
            pair_info,
            market_data,
            prev_pair_info,
            analysis_level=analysis_level,
        )
        if not entry_conditions_passed:
            reasons = self._get_failure_reasons(trace)
            logger.debug(
                "%s >>> Entry conditions result: FAILED. Reasons: %s",
                log_prefix,
                ", ".join(reasons),
            )
            # Do not return yet, we still want to calculate foundation weight

        # NEW: Attach filter trace to the main trace for analytics
        if trace_filters:
            trace["filters_trace"] = trace_filters

        total_weight, met_foundations_log = self._calculate_weight_from_trace(trace)
        logger.debug(
            "%s Total weight: %.4f, Threshold: %.4f",
            log_prefix,
            total_weight,
            self.min_total_foundation_weight_threshold,
        )

        if analysis_level == "minute_bar_filter":
            return None, total_weight, trace

        current_threshold = self.min_total_foundation_weight_threshold
        effective_threshold = min(current_threshold, self.max_possible_expensive_weight)
        if total_weight < effective_threshold:
            logger.info(
                f"{log_prefix} Rejected: Insufficient foundation weight ({total_weight:.1f} < {effective_threshold:.1f})."
            )
            trace["rejection_reason"] = "weight_threshold"
            return None, total_weight, trace

        if not entry_conditions_passed:
            logger.info(
                f"{log_prefix} >>> Entry conditions result: FAILED. Signal rejected."
            )
            return None, total_weight, trace

        logger.info(
            f"{log_prefix} >>> Foundation Weight Check: PASSED ({total_weight:.1f} >= {current_threshold:.1f}). Proceeding to signal creation."
        )
        action_config = strategy_json.get("initialization") or strategy_json.get(
            "action"
        )
        if not action_config:
            logger.error(
                f"{log_prefix} No 'initialization' or 'action' block found to create signal."
            )
            return None, total_weight, trace

        context = {"pair_info": pair_info, "market_data": market_data, "trace": trace}
        logger.debug("%s Creating signal from action block...", log_prefix)
        signal = self._create_signal_from_action(action_config, context)
        logger.debug("%s Signal created: %s", log_prefix, signal is not None)
        logger.debug(
            f"[{pair_info.get('symbol', '?')}] Calculated total_weight for level '{analysis_level}': {total_weight}"
        )
        return signal, total_weight, trace

    def _create_signal_from_action(
        self, action_config: Dict[str, Any], context: Dict[str, Any]
    ) -> Optional[StrategySignal]:
        pair_info = context.get("pair_info")
        if not pair_info:
            logger.error(
                "[VisualBuilder:Action] Critical error: 'pair_info' not found in context."
            )
            return None

        symbol = pair_info.get("symbol", "Unknown")
        log_prefix = f"[{self.NAME} (Visual):{symbol}:Action]"
        action_params = action_config.get("params", {})

        try:
            tick_size = pair_info.get("tick_size")
            last_price = pair_info.get("last_price")
            atr = pair_info.get("atr")

            if not tick_size or tick_size <= 0 or not last_price or last_price <= 0:
                logger.error(
                    f"{log_prefix} Missing or invalid market data for action: TickSize={tick_size}, Price={last_price}"
                )
                return None

            direction = SignalDirection[action_params.get("direction", "LONG").upper()]
            order_type_str = action_params.get("order_type", "MARKET").upper()
            mode = OrderMode[order_type_str]

            entry_price = None
            comparison_price = last_price

            if mode in [OrderMode.LIMIT_RETEST, OrderMode.LIMIT_BREAK]:
                entry_price_resolved = self._resolve_value(
                    action_params.get("entry_price"), context
                )
                if entry_price_resolved is None:
                    logger.error(
                        f"{log_prefix} Could not resolve entry_price for LIMIT order."
                    )
                    return None
                entry_price = float(entry_price_resolved)
                comparison_price = entry_price

            sl_type = action_params.get("sl_type", "atr_multiplier")
            sl_value = self._resolve_value(action_params.get("sl_value", 1.5), context)
            if sl_value is None:
                logger.error(f"{log_prefix} Could not resolve SL value.")
                return None

            sl_price_raw = 0.0
            # sl_value == 0 means "no stop"
            no_sl_mode = False
            if sl_type == "fixed_price":
                sl_price_raw = float(sl_value)
            elif sl_type == "atr_multiplier":
                if float(sl_value) == 0:
                    no_sl_mode = True
                elif not atr or atr <= 0:
                    logger.error(
                        f"{log_prefix} ATR is required for sl_type='atr_multiplier' but ATR={atr}"
                    )
                    return None
                else:
                    sl_price_raw = (
                        comparison_price - (atr * float(sl_value))
                        if direction == SignalDirection.LONG
                        else comparison_price + (atr * float(sl_value))
                    )
            elif sl_type == "percent_from_price":
                if float(sl_value) == 0:
                    no_sl_mode = True
                else:
                    sl_price_raw = (
                        comparison_price * (1 - float(sl_value) / 100.0)
                        if direction == SignalDirection.LONG
                        else comparison_price * (1 + float(sl_value) / 100.0)
                    )

            stop_loss_price = None
            if no_sl_mode:
                logger.info(
                    f"{log_prefix} SL value is 0 -> NO STOP LOSS mode activated."
                )
            else:
                sl_rounding = (
                    ROUND_DOWN if direction == SignalDirection.LONG else ROUND_UP
                )
                stop_loss_price = round_price_by_tick(
                    sl_price_raw, tick_size, sl_rounding
                )
                if stop_loss_price is None:
                    return None

            tp_type = action_params.get("tp_type", "rr_multiplier")
            tp_value = self._resolve_value(action_params.get("tp_value", 2.0), context)
            if tp_value is None:
                logger.error(f"{log_prefix} Could not resolve TP value.")
                return None

            tp_price_raw = 0.0
            risk_distance_abs = (
                abs(comparison_price - stop_loss_price)
                if stop_loss_price is not None
                else 0
            )
            if tp_type == "fixed_price":
                tp_price_raw = float(tp_value)
            elif tp_type == "rr_multiplier":
                tp_price_raw = (
                    comparison_price + (risk_distance_abs * float(tp_value))
                    if direction == SignalDirection.LONG
                    else comparison_price - (risk_distance_abs * float(tp_value))
                )
            elif tp_type == "atr_multiplier":
                if not atr or atr <= 0:
                    logger.error(
                        f"{log_prefix} ATR is required for tp_type='atr_multiplier' but ATR={atr}"
                    )
                    return None
                tp_price_raw = (
                    comparison_price + (atr * float(tp_value))
                    if direction == SignalDirection.LONG
                    else comparison_price - (atr * float(tp_value))
                )
            elif tp_type == "percent_from_price":
                tp_price_raw = (
                    comparison_price * (1 + float(tp_value) / 100.0)
                    if direction == SignalDirection.LONG
                    else comparison_price * (1 - float(tp_value) / 100.0)
                )

            tp_rounding = ROUND_UP if direction == SignalDirection.LONG else ROUND_DOWN
            take_profit_price = round_price_by_tick(
                tp_price_raw, tick_size, tp_rounding
            )
            if take_profit_price is None:
                return None

            partial_targets_list = None
            partial_exits_raw = action_params.get("partial_exits")
            if isinstance(partial_exits_raw, list):
                partial_targets_list = self._calculate_partial_targets_from_config(
                    entry_price=comparison_price,
                    direction=direction,
                    partial_exits_raw=partial_exits_raw,
                    tick_size=tick_size,
                    stop_loss_price=stop_loss_price,
                    atr_at_signal_time=atr,
                )

            logger.info(
                f"{log_prefix} Preparing to create signal. "
                f"Direction: {direction.name}, Mode: {mode.name}, Entry: {entry_price if entry_price else 'MARKET'}, "
                f"ComparisonPrice: {comparison_price:.8f}, SL_Raw: {sl_price_raw:.8f}, SL_Final: {stop_loss_price if stop_loss_price else 'NONE (no SL)'}, "
                f"TP_Raw: {tp_price_raw:.8f}, TP_Final: {take_profit_price:.8f}"
            )

            final_details = {"decision_trace": context.get("trace")}

            # Add oracle_regime for the breakeven_on_regime_change function to work
            # First, try to get the current mode from market data (pair_info)
            oracle_regime = pair_info.get("oracle_regime")

            # If not in the data, take from parameters (as a fallback)
            if oracle_regime is None:
                oracle_regime = self._get_param("oracle_regime")

            if oracle_regime is not None:
                final_details["oracle_regime"] = oracle_regime

            # PARITY FIX: Store signal ATR and other context in details
            final_details["signal_atr"] = atr
            final_details["signal_last_price"] = last_price

            move_sl_to_be_on_first_tp = action_params.get(
                "move_sl_to_be", action_params.get("move_sl_to_be_on_first_tp", False)
            )

            risk_pct = None
            risk_usd = None
            risk_val_cfg = action_params.get(
                "risk_value", action_params.get("riskValue")
            )
            risk_type_cfg = action_params.get(
                "risk_type", action_params.get("riskType", "percent_balance")
            )

            if risk_val_cfg is not None:
                risk_override = resolve_strategy_risk_override(
                    risk_type_cfg, float(risk_val_cfg)
                )
                risk_pct = risk_override.risk_pct
                risk_usd = risk_override.risk_usd

            # If not in JSON, try the global parameter
            if risk_pct is None and risk_usd is None:
                risk_pct = self._get_param("risk_pct_per_trade")

            return self._create_signal(
                symbol=symbol,
                direction=direction,
                trigger_price=last_price,
                stop_loss=stop_loss_price,
                take_profit=take_profit_price,
                mode=mode,
                entry_price=entry_price,
                details=final_details,
                partial_targets=partial_targets_list if partial_targets_list else None,
                move_sl_to_be_on_first_tp=move_sl_to_be_on_first_tp,
                risk_pct=risk_pct,
                risk_usd=risk_usd,
            )

        except (ValueError, TypeError, KeyError) as e:
            logger.error(
                f"{log_prefix} Error processing action block: {e}", exc_info=True
            )
            return None

    def _evaluate_all_leaves(
        self,
        node: Dict[str, Any],
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        prev_pair_info: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, Tuple[str, bool]], Dict[str, Any]]:
        """Recursively traverses the tree, returns leaf results, and builds a complete, calculated trace."""

        node_type = node.get("type")
        node_id = node.get("id", "unknown")
        children = node.get("children", [])

        leaf_results = {}
        trace = {
            "id": node_id,
            "type": node_type,
            "result": False,
            "details": {},
            "children": [],
        }

        if node_type in ["AND", "OR"]:
            child_results_bool = []
            if children:
                for child_node in children:
                    child_leaf_results, child_trace = self._evaluate_all_leaves(
                        child_node, pair_info, market_data, prev_pair_info
                    )
                    leaf_results.update(child_leaf_results)
                    trace["children"].append(child_trace)
                    child_results_bool.append(child_trace.get("result", False))

                # Calculate and save the result for the current node (AND/OR)
                trace["result"] = (
                    all(child_results_bool)
                    if node_type == "AND"
                    else any(child_results_bool)
                )
            else:  # Handling an empty AND/OR block
                trace["result"] = True if node_type == "AND" else False
                trace["details"] = {"info": "Empty logic gate evaluated."}
        else:  # This is a terminal node ("leaf")
            result, single_trace = self._evaluate_condition_tree(
                node, pair_info, market_data, prev_pair_info
            )
            leaf_results[node_id] = (node_type, result)
            trace = (
                single_trace  # trace for a leaf is the result of its own calculation
            )

        return leaf_results, trace

    def _evaluate_compiled_condition_tree_fast(
        self,
        node: CompiledConditionNode,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        prev_pair_info: Optional[Dict[str, Any]],
        position: Optional[BasePosition] = None,
        _depth: int = 0,
        analysis_level: Literal[
            "minute_bar_filter", "second_bar_trigger"
        ] = "second_bar_trigger",
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        node_type = node.node_type
        trace = {"id": node.node_id, "type": node_type, "result": False, "details": {}}

        if context is None:
            context = {
                "pair_info": pair_info,
                "market_data": market_data,
                "trace": trace,
                "prev_pair_info": prev_pair_info,
                "position": position,
            }

        if node_type in ["AND", "OR"]:
            trace["children"] = []
            if not node.children:
                result = node_type == "AND"
                trace["result"] = result
                trace["details"]["info"] = "Empty logic gate evaluated."
                return result, trace

            child_context = context.copy()
            child_context["trace"] = trace

            if node_type == "AND":
                for child_node in node.children:
                    child_result, child_trace = (
                        self._evaluate_compiled_condition_tree_fast(
                            child_node,
                            pair_info,
                            market_data,
                            prev_pair_info,
                            position=position,
                            _depth=_depth + 1,
                            analysis_level=analysis_level,
                            context=child_context,
                        )
                    )
                    trace["children"].append(child_trace)
                    if not child_result:
                        trace["result"] = False
                        trace["details"]["short_circuit"] = "AND_FALSE"
                        return False, trace
                trace["result"] = True
                return True, trace

            for child_node in node.children:
                child_result, child_trace = self._evaluate_compiled_condition_tree_fast(
                    child_node,
                    pair_info,
                    market_data,
                    prev_pair_info,
                    position=position,
                    _depth=_depth + 1,
                    analysis_level=analysis_level,
                    context=child_context,
                )
                trace["children"].append(child_trace)
                if child_result:
                    trace["result"] = True
                    trace["details"]["short_circuit"] = "OR_TRUE"
                    return True, trace
            trace["result"] = False
            return False, trace

        if node_type == "senior_tf_confluence":
            trace["children"] = []
            htf_timeframe = node.params.get("timeframe", "1h")
            if not node.children:
                trace["result"] = True
                trace["details"] = {
                    "info": "Empty senior_tf_confluence container evaluated.",
                    "timeframe": htf_timeframe,
                }
                return True, trace

            htf_pair_info = self._create_htf_pair_info(
                pair_info, market_data, htf_timeframe
            )
            if htf_pair_info is None:
                htf_pair_info = pair_info
                trace["details"]["warning"] = (
                    f"HTF data for '{htf_timeframe}' not available, using current timeframe"
                )
            else:
                trace["details"]["htf_timeframe"] = htf_timeframe
                trace["details"]["htf_last_price"] = htf_pair_info.get("last_price")
                trace["details"]["htf_atr"] = htf_pair_info.get("atr")

            child_context = context.copy()
            child_context["trace"] = trace
            child_context["pair_info"] = htf_pair_info
            for child_node in node.children:
                child_result, child_trace = self._evaluate_compiled_condition_tree_fast(
                    child_node,
                    htf_pair_info,
                    market_data,
                    prev_pair_info,
                    position=position,
                    _depth=_depth + 1,
                    analysis_level=analysis_level,
                    context=child_context,
                )
                trace["children"].append(child_trace)
                if not child_result:
                    trace["result"] = False
                    trace["details"]["short_circuit"] = "SENIOR_TF_FALSE"
                    return False, trace
            trace["result"] = True
            return True, trace

        if node_type == "tradingview_signal":
            signal_id = node.params.get("signal_id")
            if pair_info.get("is_backtest_mode", False):
                trace["details"] = {
                    "info": "TradingView signal block ignored in backtest mode.",
                    "signal_id": signal_id,
                }
                return False, trace
            if not signal_id:
                trace["details"] = {"error": "Missing 'signal_id' in block parameters."}
                return False, trace

            now = time.time()
            self.active_tv_signals = {
                sid: exp for sid, exp in self.active_tv_signals.items() if exp > now
            }
            expiry = self.active_tv_signals.get(signal_id)
            if expiry:
                trace["result"] = True
                trace["details"] = {
                    "info": "Active TradingView signal found.",
                    "expires_at": datetime.fromtimestamp(expiry).strftime("%H:%M:%S"),
                }
                return True, trace
            trace["details"] = {
                "info": "No active TradingView signal found for this ID."
            }
            return False, trace

        if (
            analysis_level == "minute_bar_filter"
            and node.analysis_level == "second_bar_trigger"
        ):
            trace["result"] = True
            trace["details"] = {"info": "Skipped expensive node during cheap scan."}
            return True, trace

        if node.evaluator:
            try:
                result, details = node.evaluator(
                    pair_info=pair_info, market_data=market_data, context=context
                )
                trace["result"] = result
                if isinstance(details, dict):
                    trace["details"].update(details)
            except Exception as e:
                trace["result"] = False
                trace["details"]["error"] = (
                    f"Exception during evaluation of '{node_type}': {str(e)}"
                )
        else:
            trace["result"] = False
            trace["details"]["error"] = f"Unknown node_type: '{node_type}'"

        return trace["result"], trace

    def _evaluate_condition_tree_fast(
        self,
        node: Dict[str, Any],
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        prev_pair_info: Optional[Dict[str, Any]],
        position: Optional[BasePosition] = None,
        _depth: int = 0,
        analysis_level: Literal[
            "minute_bar_filter", "second_bar_trigger"
        ] = "second_bar_trigger",
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        node_type = node.get("type")
        node_id = node.get("id", "unknown")
        children = node.get("children") or []
        trace = {"id": node_id, "type": node_type, "result": False, "details": {}}

        if context is None:
            context = {
                "pair_info": pair_info,
                "market_data": market_data,
                "trace": trace,
                "prev_pair_info": prev_pair_info,
                "position": position,
            }

        if node_type in ["AND", "OR"]:
            trace["children"] = []
            if not children:
                result = node_type == "AND"
                trace["result"] = result
                trace["details"]["info"] = "Empty logic gate evaluated."
                return result, trace

            child_context = context.copy()
            child_context["trace"] = trace

            if node_type == "AND":
                for child_node in children:
                    child_result, child_trace = self._evaluate_condition_tree_fast(
                        child_node,
                        pair_info,
                        market_data,
                        prev_pair_info,
                        position=position,
                        _depth=_depth + 1,
                        analysis_level=analysis_level,
                        context=child_context,
                    )
                    trace["children"].append(child_trace)
                    if not child_result:
                        trace["result"] = False
                        trace["details"]["short_circuit"] = "AND_FALSE"
                        return False, trace
                trace["result"] = True
                return True, trace

            for child_node in children:
                child_result, child_trace = self._evaluate_condition_tree_fast(
                    child_node,
                    pair_info,
                    market_data,
                    prev_pair_info,
                    position=position,
                    _depth=_depth + 1,
                    analysis_level=analysis_level,
                    context=child_context,
                )
                trace["children"].append(child_trace)
                if child_result:
                    trace["result"] = True
                    trace["details"]["short_circuit"] = "OR_TRUE"
                    return True, trace
            trace["result"] = False
            return False, trace

        if node_type == "senior_tf_confluence":
            trace["children"] = []
            params = node.get("params", {})
            htf_timeframe = params.get("timeframe", "1h")
            if not children:
                trace["result"] = True
                trace["details"] = {
                    "info": "Empty senior_tf_confluence container evaluated.",
                    "timeframe": htf_timeframe,
                }
                return True, trace

            htf_pair_info = self._create_htf_pair_info(
                pair_info, market_data, htf_timeframe
            )
            if htf_pair_info is None:
                htf_pair_info = pair_info
                trace["details"]["warning"] = (
                    f"HTF data for '{htf_timeframe}' not available, using current timeframe"
                )
            else:
                trace["details"]["htf_timeframe"] = htf_timeframe
                trace["details"]["htf_last_price"] = htf_pair_info.get("last_price")
                trace["details"]["htf_atr"] = htf_pair_info.get("atr")

            child_context = context.copy()
            child_context["trace"] = trace
            child_context["pair_info"] = htf_pair_info
            for child_node in children:
                child_result, child_trace = self._evaluate_condition_tree_fast(
                    child_node,
                    htf_pair_info,
                    market_data,
                    prev_pair_info,
                    position=position,
                    _depth=_depth + 1,
                    analysis_level=analysis_level,
                    context=child_context,
                )
                trace["children"].append(child_trace)
                if not child_result:
                    trace["result"] = False
                    trace["details"]["short_circuit"] = "SENIOR_TF_FALSE"
                    return False, trace
            trace["result"] = True
            return True, trace

        if node_type == "tradingview_signal":
            params = node.get("params", {})
            signal_id = params.get("signal_id")
            if pair_info.get("is_backtest_mode", False):
                trace["details"] = {
                    "info": "TradingView signal block ignored in backtest mode.",
                    "signal_id": signal_id,
                }
                return False, trace
            if not signal_id:
                trace["details"] = {"error": "Missing 'signal_id' in block parameters."}
                return False, trace

            now = time.time()
            self.active_tv_signals = {
                sid: exp for sid, exp in self.active_tv_signals.items() if exp > now
            }
            expiry = self.active_tv_signals.get(signal_id)
            if expiry:
                trace["result"] = True
                trace["details"] = {
                    "info": "Active TradingView signal found.",
                    "expires_at": datetime.fromtimestamp(expiry).strftime("%H:%M:%S"),
                }
                return True, trace
            trace["details"] = {
                "info": "No active TradingView signal found for this ID."
            }
            return False, trace

        node_analysis_level = node.get("analysis_level", "minute_bar_filter")
        if (
            analysis_level == "minute_bar_filter"
            and node_analysis_level == "second_bar_trigger"
        ):
            trace["result"] = True
            trace["details"] = {"info": "Skipped expensive node during cheap scan."}
            return True, trace

        checker_method = self.condition_checkers.get(node_type)
        if checker_method:
            try:
                params = node.get("params", {})
                result, details = checker_method(
                    pair_info=pair_info,
                    market_data=market_data,
                    params=params,
                    context=context,
                )
                trace["result"] = result
                if isinstance(details, dict):
                    trace["details"].update(details)
            except Exception as e:
                trace["result"] = False
                trace["details"]["error"] = (
                    f"Exception during evaluation of '{node_type}': {str(e)}"
                )
        else:
            trace["result"] = False
            trace["details"]["error"] = f"Unknown node_type: '{node_type}'"

        return trace["result"], trace

    def _evaluate_condition_tree(
        self,
        node: Dict[str, Any],
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        prev_pair_info: Optional[Dict[str, Any]],
        position: Optional[BasePosition] = None,
        _is_foundation_node: bool = False,
        _depth: int = 0,
        analysis_level: Literal[
            "minute_bar_filter", "second_bar_trigger"
        ] = "second_bar_trigger",
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        [DISPATCHER] Recursively calculates the result of the condition tree.
        FIXED VERSION: Does not change the node type to avoid breaking visualization and analysis.
        """
        indent = "  " * _depth
        node_type = node.get("type")
        node_id = node.get("id", "unknown")
        children = node.get("children")
        if children is None:
            children = []
        logger.debug(
            f"{indent}--> Evaluating Node ID: '{node_id}', Type: '{node_type}'"
        )

        # Node type in trace is now always original
        trace = {"id": node_id, "type": node_type, "result": False, "details": {}}
        params_for_trace = node.get("params")
        if isinstance(params_for_trace, dict):
            trace["params"] = copy.deepcopy(params_for_trace)
        trace_time = pair_info.get("timestamp_dt") or pair_info.get("timestamp")
        if trace_time is not None:
            trace["details"]["time"] = (
                trace_time.isoformat()
                if hasattr(trace_time, "isoformat")
                else trace_time
            )

        if context is None:
            context = {
                "pair_info": pair_info,
                "market_data": market_data,
                "trace": trace,
                "prev_pair_info": prev_pair_info,
                "position": position,
            }

        if node_type in ["AND", "OR"]:
            trace["children"] = []
            if not children:
                is_true = node_type == "AND"
                trace["result"] = is_true
                trace["details"]["info"] = "Empty logic gate evaluated."
                logger.debug(
                    f"{indent}<-- Result for '{node_id}' ({node_type}): {trace['result']}"
                )
                return (is_true, trace)

            child_context = context.copy()
            child_context["trace"] = trace

            child_results_bool = []
            for child_node in children:
                child_result, child_trace = self._evaluate_condition_tree(
                    child_node,
                    pair_info,
                    market_data,
                    prev_pair_info,
                    position=position,
                    _depth=_depth + 1,
                    analysis_level=analysis_level,
                    context=child_context,
                )
                child_results_bool.append(child_result)
                trace["children"].append(child_trace)

            trace["result"] = (
                all(child_results_bool)
                if node_type == "AND"
                else any(child_results_bool)
            )
            logger.debug(
                f"{indent}<-- Result for '{node_id}' ({node_type}): {trace['result']}"
            )
            return (trace["result"], trace)

        # SENIOR_TF_CONFLUENCE: Logical container for checking conditions on a higher timeframe
        elif node_type == "senior_tf_confluence":
            trace["children"] = []
            params = node.get("params", {})
            htf_timeframe = params.get("timeframe", "1h")

            logger.info(
                f"{indent}---> senior_tf_confluence: Switching context to timeframe '{htf_timeframe}'"
            )

            if not children:
                trace["result"] = True  # Empty container = True (like AND)
                trace["details"] = {
                    "info": "Empty senior_tf_confluence container evaluated.",
                    "timeframe": htf_timeframe,
                }
                logger.debug(
                    f"{indent}<-- Result for '{node_id}' (senior_tf_confluence): {trace['result']}"
                )
                return (True, trace)

            # Create a modified pair_info for the higher timeframe
            htf_pair_info = self._create_htf_pair_info(
                pair_info, market_data, htf_timeframe
            )

            if htf_pair_info is None:
                # If HTF data could not be retrieved, use the current pair_info
                logger.warning(
                    f"{indent}[senior_tf_confluence] Could not create HTF pair_info for '{htf_timeframe}'. Using current pair_info."
                )
                htf_pair_info = pair_info
                trace["details"]["warning"] = (
                    f"HTF data for '{htf_timeframe}' not available, using current timeframe"
                )
            else:
                trace["details"]["htf_timeframe"] = htf_timeframe
                trace["details"]["htf_last_price"] = htf_pair_info.get("last_price")
                trace["details"]["htf_atr"] = htf_pair_info.get("atr")

            child_context = context.copy()
            child_context["trace"] = trace
            child_context["pair_info"] = (
                htf_pair_info  # Updating pair_info in the context
            )

            child_results_bool = []
            for child_node in children:
                child_result, child_trace = self._evaluate_condition_tree(
                    child_node,
                    htf_pair_info,
                    market_data,
                    prev_pair_info,
                    position=position,
                    _depth=_depth + 1,
                    analysis_level=analysis_level,
                    context=child_context,
                )
                child_results_bool.append(child_result)
                trace["children"].append(child_trace)

            # AND logic: all conditions must be True
            trace["result"] = all(child_results_bool)
            logger.debug(
                f"{indent}<-- Result for '{node_id}' (senior_tf_confluence on {htf_timeframe}): {trace['result']}"
            )
            return (trace["result"], trace)

        elif node_type == "tradingview_signal":
            params = node.get("params", {})
            signal_id = params.get("signal_id")

            # In backtest mode, TV signals are always False
            if pair_info.get("is_backtest_mode", False):
                trace["result"] = False
                trace["details"] = {
                    "info": "TradingView signal block ignored in backtest mode.",
                    "signal_id": signal_id,
                }
                return (False, trace)

            if not signal_id:
                trace["result"] = False
                trace["details"] = {"error": "Missing 'signal_id' in block parameters."}
                return (False, trace)

            # Clearing expired signals
            now = time.time()
            self.active_tv_signals = {
                sid: exp for sid, exp in self.active_tv_signals.items() if exp > now
            }

            expiry = self.active_tv_signals.get(signal_id)
            if expiry:
                result = True
                details = {
                    "info": "Active TradingView signal found.",
                    "expires_at": datetime.fromtimestamp(expiry).strftime("%H:%M:%S"),
                }
            else:
                result = False
                details = {"info": "No active TradingView signal found for this ID."}

            trace["result"] = result
            trace["details"].update(details)
            return (result, trace)

        else:  # This is a leaf node (specific condition)
            node_analysis_level = node.get("analysis_level", "minute_bar_filter")
            if (
                analysis_level == "minute_bar_filter"
                and node_analysis_level == "second_bar_trigger"
            ):
                trace["result"] = True
                trace["details"] = {"info": "Skipped expensive node during cheap scan."}
                logger.debug(
                    f"{indent}<-- Result for '{node_id}' ({node_type}): SKIPPED (True)"
                )
                return (True, trace)

            checker_method = self.condition_checkers.get(node_type)
            if checker_method:
                try:
                    params = node.get("params", {})
                    result, details = checker_method(
                        pair_info=pair_info,
                        market_data=market_data,
                        params=params,
                        context=context,
                    )
                    trace["result"] = result
                    trace["details"].update(details)
                except Exception as e:
                    trace["result"] = False
                    trace["details"]["error"] = (
                        f"Exception during evaluation of '{node_type}': {str(e)}"
                    )
            else:
                trace["result"] = False
                trace["details"]["error"] = f"Unknown node_type: '{node_type}'"

            return (trace["result"], trace)

    # Add this helper method to the BaseStrategy class (anywhere)
    @staticmethod
    def find_block_in_trace(
        trace: Dict[str, Any], block_id: str
    ) -> Optional[Dict[str, Any]]:
        """Helper to find a specific block's result within a trace tree."""
        if not trace:
            return None
        if trace.get("id") == block_id:
            return trace
        for child in trace.get("children") or []:
            found = BaseStrategy.find_block_in_trace(child, block_id)
            if found:
                return found
        return None

    def _create_htf_pair_info(
        self, pair_info: Dict[str, Any], market_data: Dict[str, Any], htf_timeframe: str
    ) -> Optional[Dict[str, Any]]:
        """
        Creates a modified pair_info with higher timeframe data.

        Extracts the last closed HTF candle and recalculates main indicators.

        Args:
            pair_info: Current pair_info
            market_data: Dictionary with market data (contains kline_1m, kline_5m, kline_1h, etc.)
            htf_timeframe: Target timeframe (e.g., '1h', '4h', '1d')

        Returns:
            Modified pair_info with HTF data or None if data is unavailable
        """
        import pandas_ta as ta

        htf_kline_key = f"kline_{htf_timeframe}"
        htf_df = market_data.get(htf_kline_key)

        if htf_df is None or not isinstance(htf_df, pd.DataFrame) or htf_df.empty:
            logger.warning(
                f"[_create_htf_pair_info] No HTF data available for key '{htf_kline_key}'"
            )
            return None

        # Copying current pair_info as a base
        htf_pair_info = pair_info.copy()

        try:
            # Take the last CLOSED candle (shift 1, as the current one is not yet closed)
            if len(htf_df) < 2:
                logger.warning(
                    f"[_create_htf_pair_info] Not enough HTF candles (need at least 2, got {len(htf_df)})"
                )
                return None

            # Use the second-to-last candle, as the last one might be unclosed
            last_closed_candle = htf_df.iloc[-2]

            # Updating OHLCV data
            htf_pair_info["htf_timeframe"] = htf_timeframe
            htf_pair_info["htf_open"] = float(last_closed_candle.get("open", 0))
            htf_pair_info["htf_high"] = float(last_closed_candle.get("high", 0))
            htf_pair_info["htf_low"] = float(last_closed_candle.get("low", 0))
            htf_pair_info["htf_close"] = float(last_closed_candle.get("close", 0))
            htf_pair_info["htf_volume"] = float(last_closed_candle.get("volume", 0))

            # Also save to standard fields for compatibility with condition checkers
            htf_pair_info["last_price"] = htf_pair_info["htf_close"]

            # Calculating indicators on HTF data
            if len(htf_df) >= 14:
                # ATR (14 periods)
                atr_series = ta.atr(
                    high=htf_df["high"],
                    low=htf_df["low"],
                    close=htf_df["close"],
                    length=14,
                )
                if atr_series is not None and len(atr_series) > 1:
                    htf_atr = atr_series.iloc[-2]  # Using value for a closed candle
                    if not pd.isna(htf_atr):
                        htf_pair_info["atr"] = float(htf_atr)
                        htf_pair_info["ATR_14"] = float(htf_atr)

                # RSI (14 periods)
                rsi_series = ta.rsi(close=htf_df["close"], length=14)
                if rsi_series is not None and len(rsi_series) > 1:
                    htf_rsi = rsi_series.iloc[-2]
                    if not pd.isna(htf_rsi):
                        htf_pair_info["rsi_14"] = float(htf_rsi)
                        htf_pair_info["RSI_14"] = float(htf_rsi)

                # ADX (14 periods)
                adx_result = ta.adx(
                    high=htf_df["high"],
                    low=htf_df["low"],
                    close=htf_df["close"],
                    length=14,
                )
                if (
                    adx_result is not None
                    and "ADX_14" in adx_result.columns
                    and len(adx_result) > 1
                ):
                    htf_adx = adx_result["ADX_14"].iloc[-2]
                    if not pd.isna(htf_adx):
                        htf_pair_info["adx_14"] = float(htf_adx)
                        htf_pair_info["ADX_14"] = float(htf_adx)

            if len(htf_df) >= 50:
                # SMA (20 and 50 periods)
                sma_20 = ta.sma(close=htf_df["close"], length=20)
                if sma_20 is not None and len(sma_20) > 1:
                    val = sma_20.iloc[-2]
                    if not pd.isna(val):
                        htf_pair_info["SMA_20"] = float(val)

                sma_50 = ta.sma(close=htf_df["close"], length=50)
                if sma_50 is not None and len(sma_50) > 1:
                    val = sma_50.iloc[-2]
                    if not pd.isna(val):
                        htf_pair_info["SMA_50"] = float(val)

                # EMA (9 and 21 periods)
                ema_9 = ta.ema(close=htf_df["close"], length=9)
                if ema_9 is not None and len(ema_9) > 1:
                    val = ema_9.iloc[-2]
                    if not pd.isna(val):
                        htf_pair_info["EMA_9"] = float(val)

                ema_21 = ta.ema(close=htf_df["close"], length=21)
                if ema_21 is not None and len(ema_21) > 1:
                    val = ema_21.iloc[-2]
                    if not pd.isna(val):
                        htf_pair_info["EMA_21"] = float(val)

            logger.debug(
                f"[_create_htf_pair_info] Created HTF pair_info for '{htf_timeframe}': "
                f"close={htf_pair_info.get('htf_close')}, atr={htf_pair_info.get('atr')}"
            )

            return htf_pair_info

        except Exception as e:
            logger.error(
                f"[_create_htf_pair_info] Error creating HTF pair_info: {e}",
                exc_info=True,
            )
            return None

    # COMPATIBILITY WRAPPERS
    # These wrappers allow using old functions in the new dispatcher

    def _check_foundation_market_activity_wrapper(
        self, pair_info, market_data, params, context
    ) -> Tuple[bool, Dict]:
        result = self._check_foundation_market_activity(
            pair_info, market_data=market_data, params_override=params
        )
        details = {
            "rel_vol_actual": pair_info.get("relative_volume"),
            "natr_actual": pair_info.get("natr"),
        }
        return result, details

    def _check_condition_tape_analysis(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        [DATA PROVIDER] Calculates and provides various tape analysis metrics for a given time window.
        This block always returns True and passes its calculated values in the details dictionary.

        Params from UI:
        - time_window_sec (int): The lookback window in seconds. Example: 5.
        """
        time_window_sec = params.get("time_window_sec", 5)

        # Define all possible metrics that can be calculated for a given window
        metric_suffixes = [
            "buy_volume_usd",
            "sell_volume_usd",
            "total_volume_usd",
            "buy_count",
            "sell_count",
            "total_count",
            "delta_volume_usd",
            "delta_count",
            "buy_sell_ratio_volume",
            "buy_sell_ratio_count",
            "avg_trade_size_usd",
        ]

        details = {"time_window_sec": time_window_sec}
        all_metrics_found = True

        for suffix in metric_suffixes:
            col_name = f"tape_{suffix}_{time_window_sec}s"
            value = pair_info.get(col_name)
            if value is not None:
                details[suffix] = value
            else:
                details[suffix] = None
                all_metrics_found = False

        # Also include acceleration multipliers if available
        # These compare the short window (e.g., 5s) to a longer one (e.g., 60s)
        avg_lookback_sec = 60
        accel_suffixes = ["volume", "count"]
        for suffix in accel_suffixes:
            col_name = (
                f"tape_accel_mult_{suffix}_{time_window_sec}s_{avg_lookback_sec}s"
            )
            value = pair_info.get(col_name)
            if value is not None:
                details[f"acceleration_multiplier_{suffix}"] = value
            else:
                details[f"acceleration_multiplier_{suffix}"] = None

        if not all_metrics_found:
            logger.warning(
                f"[{pair_info.get('symbol', 'Unknown')}:F_TapeAnalysis] Not all metrics were found in pair_info for window {time_window_sec}s."
            )
            details["warning"] = "Some metrics were not pre-calculated."

        # As a data provider, this block always returns True.
        # The actual logic is performed in other blocks that consume this data.
        return True, details

    def _check_condition_tape(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        [CONDITION] Checks conditions based on trade tape data.
        Unlike tape_analysis (data provider), this block returns True/False.

        Params from UI/Genetic:
        - metric (str): Metric type.
            Available: 'delta_volume', 'delta_count', 'ratio_volume', 'ratio_count',
                       'accel_volume', 'accel_count', 'total_volume', 'total_count'
        - window_sec (int): Window in seconds (5, 10, 30). Default: 5.
        - operator (str): Comparison operator ('gt', 'lt', 'gte', 'lte'). Default: 'gt'.
        - threshold (float): Threshold value. Default: 1.0.
        - avg_lookback_sec (int): For accel metrics — averaging window (60, 120). Default: 60.
        """
        metric = params.get("metric", "delta_volume")
        window_sec = int(params.get("window_sec", 5))
        operator = params.get("operator", "gt")
        threshold = float(params.get("threshold", 1.0))
        avg_lookback_sec = int(params.get("avg_lookback_sec", 60))

        # Building the column name depending on the metric
        col_name = None
        if metric == "delta_volume":
            col_name = f"tape_delta_volume_usd_{window_sec}s"
        elif metric == "delta_count":
            col_name = f"tape_delta_count_{window_sec}s"
        elif metric == "ratio_volume":
            col_name = f"tape_buy_sell_ratio_volume_{window_sec}s"
        elif metric == "ratio_count":
            col_name = f"tape_buy_sell_ratio_count_{window_sec}s"
        elif metric == "accel_volume":
            col_name = f"tape_accel_mult_volume_{window_sec}s_{avg_lookback_sec}s"
        elif metric == "accel_count":
            col_name = f"tape_accel_mult_count_{window_sec}s_{avg_lookback_sec}s"
        elif metric == "total_volume":
            col_name = f"tape_total_volume_usd_{window_sec}s"
        elif metric == "total_count":
            col_name = f"tape_total_count_{window_sec}s"

        if col_name is None:
            return False, {"error": f"Unknown metric: {metric}"}

        # Getting the value from pair_info
        value = pair_info.get(col_name)

        details = {
            "metric": metric,
            "col_name": col_name,
            "window_sec": window_sec,
            "threshold": threshold,
            "operator": operator,
            "value": value,
        }

        if value is None:
            # Tape is not loaded — skipping the condition (True for compatibility)
            details["warning"] = f"Tape column '{col_name}' not found in pair_info"
            logger.warning(
                f"[{pair_info.get('symbol', 'Unknown')}:tape_condition] {details['warning']}"
            )
            return True, details

        # Apply operator
        result = False
        if operator == "gt":
            result = value > threshold
        elif operator == "lt":
            result = value < threshold
        elif operator == "gte":
            result = value >= threshold
        elif operator == "lte":
            result = value <= threshold

        details["result"] = result
        return bool(result), details

    def _check_foundation_classic_pattern_wrapper(
        self, pair_info, market_data, params, context
    ) -> Tuple[bool, Dict]:
        timeframe = params.get("timeframe", pair_info.get("candle_timeframe", "1m"))
        kline_key = f"kline_{timeframe}"
        candles_df = market_data.get(kline_key)
        return _check_foundation_classic_pattern(pair_info, candles_df, params)

    def _check_foundation_level_wrapper(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        [UPDATED] Checks proximity to significant levels using parameters from the UI.
        Ensures backward compatibility with old strategies.
        """
        symbol = pair_info.get("symbol", "Unknown")
        log_prefix = f"[{self.NAME}:{symbol}:F_Level]"
        last_price = pair_info.get("last_price")
        atr = pair_info.get("atr")
        current_ts = pair_info.get("timestamp_dt")
        level_type = str(params.get("level_type", "daily_high")).strip().lower()

        if last_price is None or atr is None or atr <= 0:
            return False, {"error": "Missing last_price or atr"}

        # Use parameters from `params` if they exist, otherwise — default values (old behavior)
        proximity_type = params.get("proximity_type", "atr_multiplier")
        proximity_value = float(
            self._resolve_value(params.get("proximity_value", 0.25), context)
        )

        available_market_data_for_levels = {
            k: df
            for k, df in market_data.items()
            if k.startswith("kline_") and isinstance(df, pd.DataFrame) and not df.empty
        }
        if not available_market_data_for_levels:
            return False, {"error": "No kline data available"}

        significant_levels = find_significant_levels(
            available_market_data_for_levels, current_timestamp_dt=current_ts
        )
        selected_levels = significant_levels.get(level_type, [])

        if not selected_levels:
            return False, {
                "info": f"No significant levels found for '{level_type}'",
                "level_type": level_type,
            }

        details = {"level_type": level_type, "levels_found": selected_levels}

        for level in selected_levels:
            # Calculate the tolerance depending on the type
            if proximity_type == "percentage":
                proximity_threshold = level * (proximity_value / 100.0)
            else:  # By default (and for 'atr_multiplier'), use ATR
                proximity_threshold = atr * proximity_value

            if abs(last_price - level) <= proximity_threshold:
                logger.debug(
                    f"{log_prefix} Near significant level {level:.4f} (proximity: {proximity_threshold:.4f})"
                )
                details["level_hit"] = level
                details["detected_level"] = level
                details["proximity_used"] = proximity_threshold
                return True, details

        return False, details

    def _check_foundation_volume_confirmation_wrapper(
        self, pair_info, market_data, params, context
    ) -> Tuple[bool, Dict]:
        candles_df = market_data.get(f"kline_{pair_info.get('candle_timeframe', '1m')}")
        current_index = pair_info.get("current_candle_index")
        if current_index is None and candles_df is not None and not candles_df.empty:
            current_index = len(candles_df) - 1

        lookback = int(self._resolve_value(params.get("lookback_period", 20), context))
        multiplier = float(
            self._resolve_value(
                params.get("multiplier", params.get("kline_vol_multiplier", 1.8)),
                context,
            )
        )

        result = _check_foundation_volume_confirmation(
            pair_info,
            market_data,
            candles_df,
            current_index,
            lookback_period=lookback,
            multiplier=multiplier,
        )
        details = {"lookback_period": lookback, "multiplier": multiplier}
        if (
            candles_df is not None
            and current_index is not None
            and 0 <= current_index < len(candles_df)
        ):
            try:
                current_volume = float(candles_df["volume"].iloc[current_index])
                start_idx = max(0, current_index - lookback)
                avg_volume = float(
                    candles_df["volume"].iloc[start_idx:current_index].mean()
                )
                details.update(
                    {
                        "volume": current_volume,
                        "volume_ma": avg_volume,
                        "threshold": avg_volume * multiplier
                        if avg_volume == avg_volume
                        else None,
                    }
                )
            except Exception:
                pass
        return result, details

    def _check_foundation_round_number_level_wrapper(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        [UPDATED] Wrapper for checking round levels using parameters from the UI.
        """
        proximity_type = params.get("proximity_type", "pips")  # 'pips' or 'percentage'
        raw_proximity_value = params.get(
            "proximity_value", params.get("proximity_pips", 5)
        )
        proximity_value = float(self._resolve_value(raw_proximity_value, context))

        # Default values
        proximity_pct_val = 0.002
        min_tick_prox_val = 5

        if proximity_type == "percentage":
            # Convert UI percentages (e.g., 0.2) to multiplier (0.002)
            proximity_pct_val = proximity_value / 100.0
            # When the main tolerance is in %, we set the minimum tolerance in ticks so it doesn't interfere
            min_tick_prox_val = 1
        elif proximity_type == "pips":
            min_tick_prox_val = int(proximity_value)
            # When the main tolerance is in ticks, zero out the percentage one so it doesn't interfere
            proximity_pct_val = 0.0

        result = _check_foundation_round_number_level(
            pair_info,
            market_data,
            enabled=True,
            proximity_pct=proximity_pct_val,
            atr_multiplier=0.1,  # Not used because use_atr=False
            use_atr=False,
            min_tick_prox=min_tick_prox_val,
            max_check_per_step=2,
            step_definitions=[],
            order_multipliers_cfg=None,
            max_orders_scan_cfg=None,
        )
        details = {"params_used": {"type": proximity_type, "value": proximity_value}}
        last_price = pair_info.get("last_price")
        tick_size = pair_info.get("tick_size")
        if result and last_price and tick_size:
            try:
                candidates = _generate_round_levels(
                    float(last_price),
                    float(tick_size),
                    [],
                    2,
                    None,
                    None,
                )
                if candidates:
                    details["detected_level"] = min(
                        candidates, key=lambda level: abs(float(last_price) - level)
                    )
            except Exception:
                pass
        return result, details

    # AI_CONTEXT_START: _check_filter_trading_session
    def _check_filter_trading_session(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Filters trades by trading session or UTC hours.
        Supports two modes: 'session' (presets) and 'hours' (custom hours).
        """
        from .condition_core import evaluate_time_filter_logic

        filter_mode = params.get("filter_mode", "session")
        current_hour = pair_info.get("timestamp_dt", {})

        if hasattr(current_hour, "hour"):
            current_hour = current_hour.hour
        else:
            # Fallback
            current_hour = 12

        details = {"current_hour_utc": current_hour, "filter_mode": filter_mode}

        if filter_mode == "hours":
            # Custom hours mode
            start_hour = int(params.get("start_hour_utc", 0))
            end_hour = int(params.get("end_hour_utc", 23))
            mode = params.get("mode", "include")

            result = evaluate_time_filter_logic(
                current_hour, start_hour, end_hour, mode
            )
            details["start_hour"] = start_hour
            details["end_hour"] = end_hour
            details["mode"] = mode
        else:
            # Session preset mode
            session_map = {
                "london": (7, 16),
                "new_york": (12, 21),
                "asia": (0, 9),
                "sydney": (21, 6),
            }
            session = params.get("session", "london")
            start_hour, end_hour = session_map.get(session, (0, 24))

            result = evaluate_time_filter_logic(
                current_hour, start_hour, end_hour, "include"
            )
            details["session"] = session
            details["session_hours"] = (start_hour, end_hour)

        return bool(result), details

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_filter_volatility
    def _check_filter_volatility(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Filters by volatility level using ATR or BBW indicators.

        Parameters in 'params':
        - indicator (str): Indicator for measuring volatility.
            - 'ATR' (default): Average True Range.
            - 'BBW': Bollinger Bands Width.
        - operator (str): Comparison operator.
            - 'gt' (default): greater than.
            - 'lt': less than.
        - value (float): Threshold value for comparison. Can be dynamic.
        """
        indicator = params.get("indicator", "ATR")
        operator = params.get("operator", "gt")
        value = self._resolve_value(params.get("value", 0), context)
        if indicator == "ATR":
            actual_value = float(pair_info.get("atr", 0))
        elif indicator == "BBW":
            period = params.get("period", 20)
            std = params.get("std_dev", 2.0)
            actual_value = float(pair_info.get(f"bbb_{period}_{float(std)}", 0))
        else:
            actual_value = 0.0
        result = False
        if operator == "gt":
            result = actual_value > value
        elif operator == "lt":
            result = actual_value < value

        details = {
            "indicator": indicator,
            "actual": actual_value,
            "expected": f"{operator} {value}",
        }
        return result, details

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_filter_trend_strength
    def _check_filter_trend_strength(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Filters by trend strength. Supports ADX and SMA indicators.
        Uses evaluate_adx_scalar from condition_core.py for ADX.
        """
        from .condition_core import evaluate_adx_scalar

        indicator_type = params.get("indicator", "ADX")
        threshold = self._resolve_value(
            params.get("threshold", 25.0 if indicator_type == "ADX" else 50), context
        )

        candle_tf = pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")

        # ADX Mode
        if indicator_type == "ADX":
            # First, check the ready-made value in pair_info
            period = 14
            adx_key = f"ADX_{period}"
            adx_value = pair_info.get(adx_key)

            if adx_value is not None:
                try:
                    adx_val = float(adx_value)
                    result = adx_val > threshold
                    return result, {
                        "indicator": "ADX",
                        "adx_actual": adx_val,
                        "threshold": threshold,
                        "period": period,
                    }
                except (ValueError, TypeError):
                    pass  # Fall through to dynamic calculation

            # Calculating dynamically
            adx_params = {"period": period, "threshold": threshold, "operator": "gt"}
            return evaluate_adx_scalar(df, adx_params)

        # SMA Mode
        else:
            period = int(threshold)  # In SMA mode threshold = period
            details = {"indicator": "SMA", "threshold": threshold}

            if df is None or df.empty:
                return False, {**details, "error": "No kline data for SMA calculation"}

            required_len = period + 5
            if len(df) < required_len:
                return False, {
                    **details,
                    "error": f"Not enough history for SMA (req {required_len}, got {len(df)})",
                }

            try:
                slice_df = df.tail(required_len).copy()
                sma_series = slice_df.ta.sma(close="close", length=period)

                if sma_series is None or sma_series.empty:
                    return False, {**details, "error": "SMA calculation failed"}

                sma = sma_series.iloc[-1]
                close = df["close"].iloc[-1]

                if pd.isna(sma):
                    return False, {
                        **details,
                        "error": "SMA calculation resulted in NaN",
                    }

                result = close > sma
                details[f"SMA_{period}"] = float(sma)
                details["close"] = float(close)
                return result, details
            except Exception as e:
                return False, {**details, "error": f"SMA calculation error: {str(e)}"}

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_condition_ma_cross
    def _check_condition_ma_cross(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Checks the crossover of two moving averages (MA).
        Uses evaluate_ma_cross_scalar from condition_core.py for dynamic calculation.
        """
        from .condition_core import evaluate_ma_cross_scalar

        fast_period = int(params.get("fast_period", params.get("fast", 9)))
        slow_period = int(params.get("slow_period", params.get("slow", 21)))
        direction = params.get("direction", params.get("operator", "Above"))
        shift = int(params.get("shift", 0))

        key_fast = f"EMA_{fast_period}"
        key_slow = f"EMA_{slow_period}"

        # Trying to get ready-made values from pair_info
        curr_fast = self._get_previous_indicator_value(
            pair_info, market_data, key_fast, shift
        )
        curr_slow = self._get_previous_indicator_value(
            pair_info, market_data, key_slow, shift
        )
        prev_fast = self._get_previous_indicator_value(
            pair_info, market_data, key_fast, shift + 1
        )
        prev_slow = self._get_previous_indicator_value(
            pair_info, market_data, key_slow, shift + 1
        )

        # If ready values exist, use them
        if all(v is not None for v in [curr_fast, curr_slow, prev_fast, prev_slow]):
            result = False

            if direction in ("Above", "cross_above", "crosses_above"):
                if prev_fast <= prev_slow and curr_fast > curr_slow:
                    result = True
            elif direction in ("Below", "cross_below", "crosses_below"):
                if prev_fast >= prev_slow and curr_fast < curr_slow:
                    result = True

            return result, {
                "fast": curr_fast,
                "slow": curr_slow,
                "fast_period": fast_period,
                "slow_period": slow_period,
                "direction": direction,
            }

        # Calculate dynamically from kline data
        candle_tf = pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")
        return evaluate_ma_cross_scalar(df, params)

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_filter_btc_state
    def _check_filter_btc_state(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Filters trades depending on the current state of the BTCUSDT market (uptrend, downtrend, or consolidation).

        Parameters in 'params':
        - required_state (str): Required BTC state.
            - 'Trending Up': Uptrend.
            - 'Trending Down': Downtrend.
            - 'Consolidation': Consolidation (flat).
            - 'Any': Any state (filter disabled).
        - consolidation_threshold (float): Threshold for determining consolidation in percent.
            Default: 0.1 (which corresponds to ±0.1% from SMA_20).
            Example: 0.5 means consolidation is a range of ±0.5% from SMA_20.
        """
        symbol = pair_info.get("symbol", "Unknown")
        log_prefix = f"[{self.NAME}:{symbol}:F_BTC_State]"

        required_state = self._normalize_btc_state_value(
            params.get("required_state", "Any")
        )
        # Consolidation threshold in percent (default 0.1%)
        consolidation_threshold_pct = float(params.get("consolidation_threshold", 1.0))
        # Convert to multiplier (0.1% -> 0.001)
        threshold_multiplier = consolidation_threshold_pct / 100.0

        details = {
            "required_state": required_state,
            "consolidation_threshold_pct": consolidation_threshold_pct,
        }
        result = False

        if required_state == "Any":
            logger.debug(
                f"{log_prefix} Required state is 'Any', filter passes automatically."
            )
            result = True
        else:
            btc_kline_df = market_data.get("kline_1m_BTCUSDT")
            if btc_kline_df is not None and not btc_kline_df.empty:
                # Getting SMA_20: first try pre-calculated, otherwise calculate on the fly
                sma_20_series = btc_kline_df.get("SMA_20")
                if sma_20_series is not None and not sma_20_series.empty:
                    sma_20 = sma_20_series.iloc[-1]
                else:
                    sma_20 = btc_kline_df["close"].rolling(window=20).mean().iloc[-1]

                current_price = btc_kline_df["close"].iloc[-1]

                if pd.notna(sma_20) and pd.notna(current_price):
                    # Determining the state based on the threshold
                    upper_bound = sma_20 * (1 + threshold_multiplier)
                    lower_bound = sma_20 * (1 - threshold_multiplier)

                    state = "Consolidation"
                    if current_price > upper_bound:
                        state = "Trending Up"
                    elif current_price < lower_bound:
                        state = "Trending Down"

                    result = state == required_state
                    details["btc_state"] = state
                    details["btc_price"] = current_price
                    details["btc_sma_20"] = sma_20
                    details["upper_bound"] = upper_bound
                    details["lower_bound"] = lower_bound

                    logger.info(
                        f"{log_prefix} BTC Price: {current_price:.2f}, SMA_20: {sma_20:.2f}, "
                        f"Bounds: [{lower_bound:.2f}, {upper_bound:.2f}] (±{consolidation_threshold_pct}%), "
                        f"State: {state}, Required: {required_state} -> {'PASSED' if result else 'FAILED'}"
                    )
                else:
                    details["error"] = (
                        "Could not determine SMA_20 or current_price for BTC"
                    )
                    logger.warning(
                        f"{log_prefix} {details['error']}. SMA_20={sma_20}, Price={current_price}"
                    )
            else:
                details["error"] = "BTC kline data not available"
                logger.warning(
                    f"{log_prefix} {details['error']}. Ensure 'kline_1m_BTCUSDT' is in market_data."
                )

        return result, details

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_condition_open_interest
    def _check_condition_open_interest(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Checks a condition related to Open Interest.

        Parameters in 'params':
        - analyze (str): Analysis type.
            - 'change_pct' (default): Percentage change over a period.
            - 'absolute_value': Absolute value.
        - lookback (int): Analysis period in candles. Example: 5.
        - operator (str): Comparison operator ('gt' or 'lt').
        - value (float): Threshold value for comparison.
        """
        analyze_type = params.get("analyze", "change_pct")
        lookback = int(self._resolve_value(params.get("lookback", 5), context))
        operator = params.get("operator", "gt")
        value = float(self._resolve_value(params.get("value", 1.0), context))
        details = {}
        result = False

        oi_df = market_data.get("open_interest")
        if oi_df is not None and not oi_df.empty and len(oi_df) >= lookback:
            oi_series = oi_df["open_interest"].iloc[-lookback:]
            actual_value = 0.0
            if analyze_type == "change_pct":
                initial_oi = oi_series.iloc[0]
                latest_oi = oi_series.iloc[-1]
                if initial_oi > 0:
                    actual_value = ((latest_oi - initial_oi) / initial_oi) * 100
            elif analyze_type == "absolute_value":
                actual_value = oi_series.iloc[-1]

            if operator == "gt":
                result = actual_value > value
            elif operator == "lt":
                result = actual_value < value
            details = {"oi_actual": actual_value, "condition": f"{operator} {value}"}
        else:
            details = {
                "error": "Open interest data not available or not enough data for lookback"
            }

        return result, details

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_condition_correlation
    def _check_condition_correlation(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Checks the correlation of the instrument's price with BTCUSDT.

        Parameters in 'params':
        - lookback (int): Period for calculating correlation in candles. Example: 50.
        - operator (str): Comparison operator ('gt' or 'lt').
        - value (float): Correlation threshold value (from -1.0 to 1.0). Example: 0.7.
        """
        lookback = int(self._resolve_value(params.get("lookback", 50), context))
        operator = params.get("operator", "lt")
        value = float(self._resolve_value(params.get("value", 0.7), context))
        details = {}
        result = False

        symbol_kline_df = market_data.get(
            f"kline_{pair_info.get('candle_timeframe', '1m')}"
        )
        btc_kline_df = market_data.get("kline_1m_BTCUSDT")

        if (
            symbol_kline_df is not None
            and not symbol_kline_df.empty
            and len(symbol_kline_df) >= lookback
            and btc_kline_df is not None
            and not btc_kline_df.empty
            and len(btc_kline_df) >= lookback
        ):
            symbol_closes = symbol_kline_df["close"].iloc[-lookback:]
            btc_closes = btc_kline_df["close"].iloc[-lookback:]
            aligned_symbol, aligned_btc = symbol_closes.align(btc_closes, join="inner")

            if not aligned_symbol.empty:
                correlation = aligned_symbol.corr(aligned_btc)
                if pd.notna(correlation):
                    if operator == "gt":
                        result = correlation > value
                    elif operator == "lt":
                        result = correlation < value
                    details = {
                        "correlation_actual": correlation,
                        "condition": f"{operator} {value}",
                    }
                    logger.info(
                        f"[{pair_info.get('symbol', 'Unknown')}:F_Correlation] Check: {correlation:.4f} {operator} {value} -> {'PASSED' if result else 'FAILED'}"
                    )
                else:
                    details = {"error": "Could not calculate correlation (NaN result)"}
            else:
                details = {"error": "Could not align time series for correlation"}
        else:
            details = {"error": "Not enough kline data for correlation calculation"}

        return result, details

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_condition_local_level
    def _check_condition_local_level(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Finds a local level. Can operate in two modes:
        1. CONDITION mode (default): Returns True only if the price is near the level.
        2. DATA PROVIDER mode (is_data_provider=True): Always returns True and the price of the nearest level.
        """
        # 1. Get parameters, including the new "mode switch"
        is_data_provider = params.get("is_data_provider", False)
        level_type = _normalize_local_level_type(params.get("level_type", "all"))
        proximity_type = params.get("proximity_type", "atr_multiplier")
        proximity_value = float(
            self._resolve_value(params.get("proximity_value", 0.25), context)
        )

        details = {"level_type": level_type}
        result = False

        # 2. Level search logic remains the same
        levels = find_local_levels(market_data, params, pair_info.get("timestamp_dt"))
        all_levels = levels["high"] + levels["low"]
        last_price = pair_info.get("last_price")

        if not last_price or not all_levels:
            details = {
                "info": "Price or levels not available",
                "detected_level": None,
                "level_type": level_type,
            }
            # In data provider mode, if there are no levels, it's not an error, just no data
            return True if is_data_provider else False, details

        # 3. Find the level closest to the current price among all those found
        closest_level = min(all_levels, key=lambda level: abs(last_price - level))

        # 4. NEW LOGIC: Select behavior depending on the mode
        if is_data_provider:
            # DATA PROVIDER MODE
            # Simply return the found level and always consider the condition met
            result = True
            details = {
                "detected_level": closest_level,
                "mode": "data_provider",
                "level_type": level_type,
            }
        else:
            # CONDITION MODE (old behavior)
            # Checking if the price is close enough to the nearest level
            atr = pair_info.get("atr")
            if atr:
                tolerance_abs = (
                    atr * proximity_value
                    if proximity_type == "atr_multiplier"
                    else closest_level * (proximity_value / 100.0)
                )
                if abs(last_price - closest_level) <= tolerance_abs:
                    result = True
                    details = {
                        "detected_level": closest_level,
                        "proximity_type": proximity_type,
                        "tolerance": tolerance_abs,
                        "mode": "condition_checker",
                        "level_type": level_type,
                    }

            if not result:
                details = {
                    "info": "Price not near any local level",
                    "detected_level": None,
                    "mode": "condition_checker",
                    "level_type": level_type,
                }

        return result, details

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_condition_return_to_level
    def _check_condition_return_to_level(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        [IMPROVED] Checks that the price has returned (made a retest) to a level found by another block.
        Used for building "breakout-retest" scenarios.

        Parameters in 'params':
        - level_block_id (str): ID of the level source block ('local_level', 'significant_level').
        - retest_type (str): Retest type.
            - 'touch': price touches the level (with a 10% ATR tolerance).
            - 'breakout_retest': price moved away from the level and returned back.
        - approach_direction (str): Direction from which the price came.
            - 'any' (default): from any side.
            - 'from_above': price came from above (was above the level).
            - 'from_below': price came from below (was below the level).
        - confirmation_time_sec (float): Time in seconds the price must remain
          near the level before the block triggers. 0 = instant trigger.
        - cooldown_sec (float): Minimum pause between two consecutive
          triggers at the same level. Default: 60.
        """
        level_source = params.get("level_source")
        level_block_id = params.get("level_block_id")
        retest_type = (
            str(params.get("retest_type", "touch"))
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )
        approach_direction = (
            str(params.get("approach_direction", "any")).strip().lower()
        )
        confirmation_time_sec = float(
            self._resolve_value(params.get("confirmation_time_sec", 0), context) or 0
        )
        cooldown_sec = float(params.get("cooldown_sec", 60))

        symbol = pair_info.get("symbol", "Unknown")
        current_ts = pair_info.get("timestamp_dt")
        details: Dict[str, Any] = {
            "retest_type": retest_type,
            "approach_direction": approach_direction,
            "confirmation_time_sec": confirmation_time_sec,
        }

        if level_source is None:
            if not level_block_id:
                details["error"] = "level_source or level_block_id is not specified"
                return False, details
            level_source = {
                "source": "block_result",
                "block_id": level_block_id,
                "key": "detected_level",
            }

        # 1. Get the level price from the source block
        level_price = self._resolve_value(level_source, context)

        if level_price is None:
            details["error"] = "Could not resolve level price"
            return False, details

        last_price = pair_info.get("last_price")
        atr = pair_info.get("atr")
        if not last_price or not atr or atr <= 0:
            details["error"] = "last_price or atr not available"
            return False, details

        # 2. Tolerance zones
        def _calc_threshold(
            p_type, p_val, default_val, current_atr, current_level_price
        ):
            val = p_val if p_val is not None else default_val
            if p_type == "percentage":
                return (val / 100.0) * current_level_price
            return val * current_atr

        proximity = _calc_threshold(
            params.get("proximity_type", "atr_multiplier"),
            params.get("proximity_value", params.get("proximity_multiplier")),
            0.1,
            atr,
            level_price,
        )
        departure_threshold = _calc_threshold(
            params.get("departure_type", "atr_multiplier"),
            params.get("departure_value", params.get("departure_multiplier")),
            1.5,
            atr,
            level_price,
        )

        price_is_near_level = abs(last_price - level_price) <= proximity
        price_is_above_level = last_price > level_price

        details["level_price"] = level_price
        details["last_price"] = last_price
        details["proximity"] = proximity
        details["price_is_near_level"] = price_is_near_level

        # 3. Key for persistent state
        state_key = f"{symbol}:{level_block_id or json.dumps(level_source, sort_keys=True, default=str)}"
        state = self._rtl_state.get(state_key, {})

        # 4. Logic by retest type
        if retest_type == "touch":
            # === TOUCH mode: Simple level touch ===
            if not price_is_near_level:
                # Price is far — resetting the confirmation timer
                state.pop("confirmed_at", None)
                self._rtl_state[state_key] = state
                details["info"] = "Price is away from level"
                return False, details

            # Check the approach direction (if specified)
            if approach_direction == "from_above" and not price_is_above_level:
                details["info"] = (
                    "Direction filter: expected from_above, but price is below level"
                )
                return False, details
            if approach_direction == "from_below" and price_is_above_level:
                details["info"] = (
                    "Direction filter: expected from_below, but price is above level"
                )
                return False, details

            # Checking confirmation_time_sec
            result = self._rtl_check_confirmation(
                state, current_ts, confirmation_time_sec, cooldown_sec, details
            )
            self._rtl_state[state_key] = state
            return result, details

        elif retest_type == "breakout_retest":
            # BREAKOUT_RETEST mode: Departure + return
            departed = state.get(
                "departed"
            )  # bool: price has already moved away from the level
            departed_above = state.get(
                "departed_above"
            )  # bool: was above the level when leaving

            if not departed:
                # Phase 1: Waiting for price to move away from the level
                if abs(last_price - level_price) > departure_threshold:
                    # Price is far enough — fixing the departure
                    state["departed"] = True
                    state["departed_above"] = price_is_above_level
                    state["departed_at"] = current_ts
                    state.pop("confirmed_at", None)
                    self._rtl_state[state_key] = state
                    details["info"] = (
                        f"Departure detected: price {last_price:.4f} moved away from level {level_price:.4f} ({'above' if price_is_above_level else 'below'})"
                    )
                else:
                    details["info"] = (
                        f"Waiting for departure: distance {abs(last_price - level_price):.4f} < threshold {departure_threshold:.4f}"
                    )

                return False, details
            else:
                # Phase 2: Waiting for price return to the level
                if not price_is_near_level:
                    # Price is still far away — just waiting
                    state.pop("confirmed_at", None)
                    self._rtl_state[state_key] = state
                    details["info"] = (
                        f"Departed (was {'above' if departed_above else 'below'}), waiting for return to level"
                    )
                    return False, details

                # Price returned to the level — checking direction
                if approach_direction == "from_above" and departed_above is not True:
                    details["info"] = (
                        "Direction filter: expected from_above, but departure was from below"
                    )
                    return False, details
                if approach_direction == "from_below" and departed_above is not False:
                    details["info"] = (
                        "Direction filter: expected from_below, but departure was from above"
                    )
                    return False, details

                details["departed_above"] = departed_above
                details["departed_at"] = str(state.get("departed_at", ""))

                # Checking confirmation_time_sec
                result = self._rtl_check_confirmation(
                    state, current_ts, confirmation_time_sec, cooldown_sec, details
                )

                if result:
                    # Signal triggered — resetting the "departure" state for the next cycle
                    state["departed"] = False
                    state.pop("departed_above", None)
                    state.pop("departed_at", None)

                self._rtl_state[state_key] = state
                return result, details

        else:
            details["warning"] = f"Unsupported retest_type '{retest_type}'"
            return False, details

    def _rtl_check_confirmation(
        self,
        state: Dict,
        current_ts,
        confirmation_time_sec: float,
        cooldown_sec: float,
        details: Dict,
    ) -> bool:
        """
        Helper method: checks the confirmation timer and cooldown for return_to_level.
        Returns True if the condition is confirmed.
        """
        # Check cooldown (do not trigger too often)
        fired_at = state.get("fired_at")
        if fired_at is not None and current_ts is not None and cooldown_sec > 0:
            try:
                elapsed_since_fire = (current_ts - fired_at).total_seconds()
                if elapsed_since_fire < cooldown_sec:
                    details["info"] = (
                        f"Cooldown active: {cooldown_sec - elapsed_since_fire:.1f}s remaining"
                    )
                    return False
            except (TypeError, AttributeError):
                pass  # If timestamp_dt is not a datetime — skip

        # Checking confirmation_time_sec
        if confirmation_time_sec <= 0:
            # Instant execution
            state["fired_at"] = current_ts
            state.pop("confirmed_at", None)
            details["info"] = "Confirmed instantly (confirmation_time_sec=0)"
            return True

        confirmed_at = state.get("confirmed_at")
        if confirmed_at is None:
            # Starting the confirmation timer
            state["confirmed_at"] = current_ts
            details["info"] = f"Confirmation started, waiting {confirmation_time_sec}s"
            return False

        # The timer is already ticking — checking if enough time has passed
        try:
            elapsed = (current_ts - confirmed_at).total_seconds()
        except (TypeError, AttributeError):
            elapsed = 0

        if elapsed >= confirmation_time_sec:
            # Confirmed!
            state["fired_at"] = current_ts
            state.pop("confirmed_at", None)
            details["info"] = (
                f"Confirmed after {elapsed:.1f}s (required {confirmation_time_sec}s)"
            )
            return True
        else:
            details["info"] = (
                f"Confirmation in progress: {elapsed:.1f}s / {confirmation_time_sec}s"
            )
            return False

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_condition_trend_direction
    def _check_condition_trend_direction(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        # 1. Getting new parameters
        required_trend = params.get("required_trend", "ANY_TREND").upper()
        timeframe = params.get("timeframe", pair_info.get("candle_timeframe", "1m"))
        sma_fast_p = int(params.get("fast_period", 10))
        sma_slow_p = int(params.get("slow_period", 50))
        rsi_p = int(params.get("rsi_period", 14))
        rsi_low = float(params.get("rsi_lower_bound", 40))
        rsi_high = float(params.get("rsi_upper_bound", 60))

        details = {"required": required_trend, "timeframe": timeframe}

        # 2. Getting the required DataFrame and index
        candles_df = market_data.get(f"kline_{timeframe}")
        if candles_df is None or candles_df.empty:
            details["error"] = f"Kline data for {timeframe} not found."
            return False, details

        current_ts = pair_info.get("timestamp_dt")
        try:
            idx = candles_df.index.get_indexer([current_ts], method="ffill")[0]
            if idx == -1:
                raise IndexError("No valid candle index found")
        except Exception:
            details["error"] = (
                f"Could not find candle index for {current_ts} on {timeframe}."
            )
            return False, details

        # 3. Attempting to get values from pair_info (for tests and optimization)
        sma_fast_val = pair_info.get(f"SMA_{sma_fast_p}")
        sma_slow_val = pair_info.get(f"SMA_{sma_slow_p}")
        rsi_val = pair_info.get(f"RSI_{rsi_p}")

        # If something is missing — calculate on the fly
        if sma_fast_val is None or sma_slow_val is None or rsi_val is None:
            if idx < sma_slow_p or idx < rsi_p:
                details["info"] = "Not enough history on this timeframe."
                return False, details

            if sma_fast_val is None:
                sma_fast_val = (
                    candles_df["close"]
                    .iloc[: idx + 1]
                    .rolling(window=sma_fast_p)
                    .mean()
                    .iloc[-1]
                )
            if sma_slow_val is None:
                sma_slow_val = (
                    candles_df["close"]
                    .iloc[: idx + 1]
                    .rolling(window=sma_slow_p)
                    .mean()
                    .iloc[-1]
                )

            if rsi_val is None:
                # RSI calculation
                delta = candles_df["close"].diff()
                gain = (delta.where(delta > 0, 0)).iloc[: idx + 1]
                loss = (-delta.where(delta < 0, 0)).iloc[: idx + 1]
                avg_gain = gain.rolling(window=rsi_p).mean().iloc[-1]
                avg_loss = loss.rolling(window=rsi_p).mean().iloc[-1]
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    rsi_val = 100 - (100 / (1 + rs))
                else:
                    rsi_val = 100 if avg_gain > 0 else 50

        details["sma_fast"] = sma_fast_val
        details["sma_slow"] = sma_slow_val
        details["rsi"] = rsi_val

        # 4. Define trend
        detected_trend = _determine_trend_direction_from_values(
            sma_fast_val,
            sma_slow_val,
            rsi_val,
            rsi_low,
            rsi_high,
            symbol=pair_info.get("symbol", "Unknown"),
        )
        details["detected_trend"] = detected_trend

        # 5. Comparing with the required
        result = False
        if required_trend == "ANY_TREND":
            result = detected_trend in ["LONG", "SHORT"]
        elif required_trend == "FLAT":
            result = detected_trend == "FLAT"
        else:
            result = detected_trend == required_trend

        return result, details

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_condition_level_touch
    def _check_condition_level_touch(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Checks if the price touches a certain level.

        Parameters:
        - level_source (DynamicParam): Level source (e.g., significant_level block)
        - touch_tolerance_atr (float): Touch tolerance in ATR units. Default 0.15.
        - lookback_candles (int): Check depth (how many last candles). Default 1.
        """
        raw_level = params.get("level_source")
        if raw_level is None:
            raw_level = params.get("level_price")
        level = self._resolve_value(raw_level, context)
        if level is None:
            return False, {
                "error": "Level not resolved",
                "touches_count": 0,
                "is_valid": False,
            }

        try:
            level = float(level)
        except (TypeError, ValueError):
            return False, {
                "error": f"Invalid level value: {level}",
                "touches_count": 0,
                "is_valid": False,
            }

        lookback = max(
            1, int(self._resolve_value(params.get("lookback_candles", 50), context))
        )
        tolerance_pct_param = params.get("touch_tolerance_pct")
        tolerance = None
        if tolerance_pct_param is not None:
            tolerance_pct = float(self._resolve_value(tolerance_pct_param, context))
            tolerance = abs(level) * (tolerance_pct / 100.0)
        else:
            proximity_type = params.get("proximity_type")
            proximity_value = params.get("proximity_value")
            if proximity_type == "percentage" and proximity_value is not None:
                tolerance = abs(level) * (
                    float(self._resolve_value(proximity_value, context)) / 100.0
                )
            elif (
                params.get("touch_tolerance_atr") is not None
                or proximity_type == "atr_multiplier"
            ):
                atr = pair_info.get("atr")
                atr_multiplier = params.get(
                    "touch_tolerance_atr",
                    proximity_value if proximity_value is not None else 0.15,
                )
                if atr is None:
                    return False, {
                        "error": "ATR not available for ATR-based tolerance",
                        "level": level,
                        "touches_count": 0,
                        "is_valid": False,
                    }
                tolerance = float(atr) * float(
                    self._resolve_value(atr_multiplier, context)
                )

        if tolerance is None:
            tolerance = abs(level) * 0.001

        min_touches = max(
            1, int(self._resolve_value(params.get("min_touches", 1), context))
        )
        invalidate_on_pierce = bool(params.get("invalidate_on_pierce", False))
        candle_tf = params.get("timeframe") or pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")

        if df is None or len(df) < lookback:
            return False, {
                "error": "Not enough candles",
                "level": level,
                "touches_count": 0,
                "is_valid": False,
            }

        current_ts = pair_info.get("timestamp_dt")
        base_tf = str(pair_info.get("candle_timeframe", "1m"))
        include_current = str(candle_tf) == base_tf
        recent_df = _get_recent_closed_candles(
            df,
            lookback,
            current_timestamp_dt=current_ts,
            include_current=include_current,
        )
        if len(recent_df) < lookback:
            return False, {
                "error": "Not enough candles",
                "level": level,
                "touches_count": 0,
                "is_valid": False,
            }
        if not {"high", "low"}.issubset(recent_df.columns):
            return False, {
                "error": "Kline data must contain high and low columns",
                "level": level,
                "touches_count": 0,
                "is_valid": False,
            }

        close_series = (
            recent_df["close"]
            if "close" in recent_df.columns
            else (recent_df["high"] + recent_df["low"]) / 2
        )
        configured_side = str(params.get("level_side", "auto")).lower()
        if configured_side in {"resistance", "upper"}:
            level_side = "resistance"
        elif configured_side in {"support", "lower"}:
            level_side = "support"
        else:
            level_side = (
                "resistance" if float(close_series.median()) <= level else "support"
            )

        touch_indices = []
        pierce_indices = []
        touch_times = []
        pierce_times = []
        for idx, (_, row) in enumerate(recent_df.iterrows()):
            high = float(row["high"])
            low = float(row["low"])
            ts = recent_df.index[idx]
            ts_seconds = int(ts.timestamp()) if hasattr(ts, "timestamp") else None
            if high >= level - tolerance and low <= level + tolerance:
                touch_indices.append(idx)
                if ts_seconds is not None:
                    touch_times.append(ts_seconds)
            if level_side == "resistance" and high > level + tolerance:
                pierce_indices.append(idx)
                if ts_seconds is not None:
                    pierce_times.append(ts_seconds)
            elif level_side == "support" and low < level - tolerance:
                pierce_indices.append(idx)
                if ts_seconds is not None:
                    pierce_times.append(ts_seconds)

        touches_count = len(touch_indices)
        is_valid = not (invalidate_on_pierce and bool(pierce_indices))
        result = is_valid and touches_count >= min_touches
        return result, {
            "level": level,
            "touches_count": touches_count,
            "is_valid": is_valid,
            "touch_tolerance_pct": (tolerance / abs(level) * 100.0) if level else None,
            "tolerance": tolerance,
            "level_side": level_side,
            "pierce_detected": bool(pierce_indices),
            "touch_indices": touch_indices,
            "pierce_indices": pierce_indices,
            "touch_times": touch_times,
            "pierce_times": pierce_times,
            "min_touches": min_touches,
        }

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_condition_volatility_squeeze
    def _check_condition_volatility_squeeze(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Determines volatility "squeeze" (Squeeze).
        A squeeze occurs when the current Bollinger Band Width (BBW) is
        at a historical minimum over a certain period.
        """
        lookback_param = params.get(
            "lookback_candles", params.get("lookback_period", 20)
        )
        lookback = max(4, int(self._resolve_value(lookback_param, context)))
        squeeze_ratio = float(
            self._resolve_value(params.get("squeeze_ratio", 0.6), context)
        )

        candle_tf = params.get("timeframe") or pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")

        if df is None or len(df) < lookback:
            return False, {
                "error": "Not enough data for squeeze analysis",
                "is_squeezing": False,
            }

        recent = df.tail(lookback).copy()
        if "close" not in recent.columns:
            return False, {
                "error": "Kline data must contain close column",
                "is_squeezing": False,
            }
        if "high" not in recent.columns:
            recent["high"] = recent["close"]
        if "low" not in recent.columns:
            recent["low"] = recent["close"]

        half = len(recent) // 2
        past = recent.iloc[:half]
        current = recent.iloc[half:]

        def _range_pct(window: pd.DataFrame) -> float:
            midpoint = float(window["close"].mean())
            if midpoint == 0:
                return 0.0
            channel_width = float(window["high"].max()) - float(window["low"].min())
            return abs(channel_width / midpoint) * 100.0

        past_range_pct = _range_pct(past)
        current_range_pct = _range_pct(current)
        is_squeezing = (
            past_range_pct > 0 and current_range_pct <= past_range_pct * squeeze_ratio
        )

        return bool(is_squeezing), {
            "is_squeezing": bool(is_squeezing),
            "current_range_pct": current_range_pct,
            "past_range_pct": past_range_pct,
            "squeeze_ratio": squeeze_ratio,
        }

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_condition_price_action
    def _check_condition_price_action(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Analyzes the Price Action structure (HH/HL or LH/LL).
        """
        lookback = max(
            3, int(self._resolve_value(params.get("lookback_candles", 30), context))
        )
        order = max(1, int(self._resolve_value(params.get("order", 3), context)))
        min_points = max(
            2, int(self._resolve_value(params.get("min_points", 2), context))
        )
        structure_type = params.get("structure_type")
        required_structure = params.get("required_structure")
        structure_type = structure_type or "higher_lows"

        candle_tf = params.get("timeframe") or pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")

        if df is None or len(df) < lookback:
            return False, {"error": "Not enough data"}

        data = df.tail(lookback).copy()
        if "high" not in data.columns or "low" not in data.columns:
            return False, {"error": "Kline data must contain high and low columns"}

        highs_all = data["high"].astype(float).to_numpy()
        lows_all = data["low"].astype(float).to_numpy()

        def _local_extrema(values: np.ndarray, find_min: bool) -> List[float]:
            found: List[float] = []
            if len(values) < (order * 2 + 1):
                return found
            for i in range(order, len(values) - 1):
                left = values[i - order : i]
                right = values[i + 1 : i + order + 1]
                if find_min:
                    if np.all(values[i] < left) and np.all(values[i] < right):
                        found.append(float(values[i]))
                else:
                    if np.all(values[i] > left) and np.all(values[i] > right):
                        found.append(float(values[i]))
            return found

        def _local_extrema_points(
            values: np.ndarray, find_min: bool
        ) -> List[Dict[str, Any]]:
            found: List[Dict[str, Any]] = []
            if len(values) < (order * 2 + 1):
                return found
            for i in range(order, len(values) - 1):
                left = values[i - order : i]
                right = values[i + 1 : i + order + 1]
                if find_min:
                    is_extreme = np.all(values[i] < left) and np.all(values[i] < right)
                else:
                    is_extreme = np.all(values[i] > left) and np.all(values[i] > right)
                if is_extreme:
                    ts = data.index[i]
                    found.append(
                        {
                            "idx": i,
                            "price": float(values[i]),
                            "time": int(ts.timestamp())
                            if hasattr(ts, "timestamp")
                            else None,
                        }
                    )
            return found

        high_points_all = _local_extrema_points(highs_all, find_min=False)
        low_points_all = _local_extrema_points(lows_all, find_min=True)
        highs = [point["price"] for point in high_points_all]
        lows = [point["price"] for point in low_points_all]

        markers: List[Dict[str, Any]] = []
        found_points = [{**point, "point_type": "H"} for point in high_points_all] + [
            {**point, "point_type": "L"} for point in low_points_all
        ]
        found_points.sort(key=lambda point: point["idx"])

        last_h = None
        last_l = None
        for point in found_points:
            label = point["point_type"]
            value = point["price"]
            if point["point_type"] == "H":
                if last_h is not None:
                    label = "HH" if value > last_h else "LH"
                last_h = value
                markers.append(
                    {
                        "time": point["time"],
                        "type": "price_action_analyzer",
                        "position": "aboveBar",
                        "color": "#2196F3"
                        if label == "HH"
                        else ("#ef5350" if label == "LH" else "#888888"),
                        "shape": "arrowDown",
                        "text": label,
                    }
                )
            else:
                if last_l is not None:
                    label = "LL" if value < last_l else "HL"
                last_l = value
                markers.append(
                    {
                        "time": point["time"],
                        "type": "price_action_analyzer",
                        "position": "belowBar",
                        "color": "#4CAF50"
                        if label == "HL"
                        else ("#ef5350" if label == "LL" else "#888888"),
                        "shape": "arrowUp",
                        "text": label,
                    }
                )

        details = {
            "structure_type": structure_type,
            "min_points": min_points,
            "highs": highs,
            "lows": lows,
            "highs_count": len(highs),
            "lows_count": len(lows),
            "markers": [marker for marker in markers if marker.get("time") is not None],
        }
        if len(highs) >= 2:
            details.update({"last_high": highs[-1], "prev_high": highs[-2]})
        if len(lows) >= 2:
            details.update({"last_low": lows[-1], "prev_low": lows[-2]})

        def _strictly_increasing(values: List[float]) -> bool:
            return all(values[i] > values[i - 1] for i in range(1, len(values)))

        def _strictly_decreasing(values: List[float]) -> bool:
            return all(values[i] < values[i - 1] for i in range(1, len(values)))

        if required_structure == "HH_HL" and params.get("structure_type") is None:
            high_points = highs[-min_points:]
            low_points = lows[-min_points:]
            result = (
                len(high_points) >= min_points
                and len(low_points) >= min_points
                and _strictly_increasing(high_points)
                and _strictly_increasing(low_points)
            )
            details["points_used"] = {"highs": high_points, "lows": low_points}
        elif required_structure == "LH_LL" and params.get("structure_type") is None:
            high_points = highs[-min_points:]
            low_points = lows[-min_points:]
            result = (
                len(high_points) >= min_points
                and len(low_points) >= min_points
                and _strictly_decreasing(high_points)
                and _strictly_decreasing(low_points)
            )
            details["points_used"] = {"highs": high_points, "lows": low_points}
        elif structure_type == "higher_lows":
            points = lows[-min_points:]
            result = len(points) >= min_points and _strictly_increasing(points)
            details["points_used"] = points
        elif structure_type == "lower_highs":
            points = highs[-min_points:]
            result = len(points) >= min_points and _strictly_decreasing(points)
            details["points_used"] = points
        else:
            result = False
            details["error"] = f"Unknown structure_type: {structure_type}"

        details["is_valid"] = bool(result)
        return bool(result), details

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_condition_price_consolidation
    def _check_condition_price_consolidation(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Checks if the price is in consolidation ("shelf").
        Consolidation is defined as a narrow price range over N candles.

        Parameters in 'params':
        - lookback_period (int): Number of candles for analysis. Example: 10.
        - max_range_atr (float): Max consolidation range in ATR units. Example: 0.8.
        - timeframe (str): Timeframe for analysis (1m, 5m, 1h...). Default 'auto' (strategy timeframe).
        """
        lookback_period = int(
            self._resolve_value(params.get("lookback_period", 10), context)
        )
        max_range_atr = float(
            self._resolve_value(params.get("max_range_atr", 0.8), context)
        )
        requested_tf = params.get("timeframe", "auto")

        # If auto - take the timeframe of the current strategy candle
        if requested_tf == "auto":
            requested_tf = pair_info.get("candle_timeframe", "1m")

        details = {
            "lookback_period": lookback_period,
            "max_range_atr": max_range_atr,
            "timeframe": requested_tf,
        }
        result = False

        # 1. Getting the required DataFrame
        candles_df = market_data.get(f"kline_{requested_tf}")
        if candles_df is None or candles_df.empty:
            details["error"] = f"Kline data for {requested_tf} not found."
            return False, details

        # 2. Synchronize the index (find the candle index on the requested TF that corresponds to the current strategy time)
        current_ts = pair_info.get("timestamp_dt")
        try:
            # Use ffill to find the last closed candle on the higher TF
            idx = candles_df.index.get_indexer([current_ts], method="ffill")[0]
            if idx == -1:
                raise IndexError("No valid candle index found")
        except Exception:
            details["error"] = (
                f"Could not find candle index for {current_ts} on {requested_tf}."
            )
            return False, details

        # 3. Getting ATR for this timeframe
        atr = None
        # If TF matches the main one - take it from pair_info (it's already there and up to date)
        if requested_tf == pair_info.get("candle_timeframe"):
            atr = pair_info.get("atr")

        # If it doesn't match or is not in pair_info - take it from DataFrame columns
        if atr is None:
            if "atr" in candles_df.columns:
                atr = candles_df["atr"].iloc[idx]
            else:
                # If the column is missing, try to find it by the standard indicator name
                atr_col = next(
                    (c for c in candles_df.columns if c.startswith("ATR_")), None
                )
                if atr_col:
                    atr = candles_df[atr_col].iloc[idx]

        if atr is None or atr <= 0:
            details.update(
                {
                    "error": f"ATR is not available for {requested_tf}",
                    "columns": list(candles_df.columns),
                }
            )
            return False, details

        # 4. Checking data sufficiency for lookback
        if idx < lookback_period:
            details["error"] = (
                f"Not enough history on {requested_tf} (idx={idx}, need {lookback_period})"
            )
            return False, details

        # 5. Range calculation by bodies (including current candle idx) - Ignore shadows to match "shelves"
        consolidation_slice = candles_df.iloc[idx - lookback_period + 1 : idx + 1]
        body_max = consolidation_slice[["open", "close"]].max(axis=1).max()
        body_min = consolidation_slice[["open", "close"]].min(axis=1).min()
        price_range = body_max - body_min
        atr_threshold = atr * max_range_atr

        result = price_range <= atr_threshold
        zone_start_time = (
            consolidation_slice.index[0] if len(consolidation_slice.index) > 0 else None
        )
        zone_end_time = (
            consolidation_slice.index[-1]
            if len(consolidation_slice.index) > 0
            else current_ts
        )
        detected_level = (float(body_max) + float(body_min)) / 2.0

        details.update(
            {
                "price_range": float(price_range),
                "atr_threshold": float(atr_threshold),
                "atr": float(atr),
                "idx": int(idx),
                "rolling_high": float(body_max),
                "rolling_low": float(body_min),
                "detected_level": detected_level,
                "zone_start_time": zone_start_time.isoformat()
                if hasattr(zone_start_time, "isoformat")
                else zone_start_time,
                "zone_end_time": zone_end_time.isoformat()
                if hasattr(zone_end_time, "isoformat")
                else zone_end_time,
            }
        )

        return result, details

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_condition_rsi
    def _check_condition_rsi(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Checks the condition for the RSI indicator.
        Uses evaluate_rsi_scalar from condition_core.py for dynamic calculation.
        """
        from .condition_core import evaluate_rsi_scalar, evaluate_rsi_logic

        period = int(params.get("period", 14))
        operator = params.get("operator", "gt")
        value = float(self._resolve_value(params.get("value", 50), context))

        rsi_key = f"RSI_{period}"

        # Trying to get a ready value from pair_info (safe to 0.0)
        rsi_value = pair_info.get(rsi_key)
        if rsi_value is None:
            rsi_value = pair_info.get(rsi_key.lower())
        if rsi_value is None:
            rsi_value = pair_info.get("RSI_14")

        # If a ready value exists, use it
        if rsi_value is not None:
            try:
                rsi_val = float(rsi_value)

                # For cross operators, the previous value is needed
                if operator in ("cross_above", "cross_below"):
                    prev_rsi = self._get_previous_indicator_value(
                        pair_info, market_data, rsi_key, 1
                    )
                    if prev_rsi is not None:
                        if operator == "cross_above":
                            result = (prev_rsi <= value) and (rsi_val > value)
                        else:  # cross_below
                            result = (prev_rsi >= value) and (rsi_val < value)
                    else:
                        result = False
                else:
                    result = evaluate_rsi_logic(rsi_val, operator, value)

                return bool(result), {
                    "rsi": rsi_val,
                    "period": period,
                    "operator": operator,
                    "threshold": value,
                }
            except (ValueError, TypeError):
                pass  # Fall through to dynamic calculation

        # Calculate dynamically from kline data
        candle_tf = pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")
        return evaluate_rsi_scalar(df, params)

    def _get_previous_indicator_value(
        self, pair_info: Dict, market_data: Dict, indicator_key: str, shift: int
    ) -> Optional[float]:
        """Helper method to get the indicator value with a given offset."""
        candle_tf = pair_info.get("candle_timeframe", "1m")
        candles_df = market_data.get(f"kline_{candle_tf}")
        current_index = pair_info.get("current_candle_index")

        if (
            candles_df is None
            or indicator_key not in candles_df.columns
            or current_index is None
        ):
            return None

        target_index = current_index - shift
        if 0 <= target_index < len(candles_df):
            val = candles_df.iloc[target_index][indicator_key]
            if pd.notna(val):
                return float(val)
        return None

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_condition_macd
    def _check_condition_macd(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Checks the condition for MACD.
        Uses evaluate_macd_scalar from condition_core.py for dynamic calculation.
        """
        from .condition_core import evaluate_macd_scalar, evaluate_macd_logic

        # Support for custom periods from params
        fast = int(params.get("fast_period", params.get("fast", 12)))
        slow = int(params.get("slow_period", params.get("slow", 26)))
        signal_p = int(params.get("signal_period", params.get("signal", 9)))
        condition = params.get(
            "condition", params.get("condition_type", "hist_gt_zero")
        )

        # Keys for ready-made values in pair_info
        hist_key = f"MACD_hist_{fast}_{slow}_{signal_p}"
        hist_key_alt = f"MACDh_{fast}_{slow}_{signal_p}"
        macd_key = f"MACD_{fast}_{slow}_{signal_p}"
        signal_key = f"MACDs_{fast}_{slow}_{signal_p}"

        # Safe value retrieval (considering 0.0 as a valid value)
        def get_best_val(keys_list):
            for k in keys_list:
                val = pair_info.get(k)
                if val is not None:
                    return val
            return None

        hist_value = get_best_val(
            [hist_key, hist_key_alt, "MACD_hist_12_26_9", "MACDh_12_26_9"]
        )
        macd_value = get_best_val([macd_key, "MACD_12_26_9"])
        signal_value = get_best_val([signal_key, "MACDs_12_26_9"])

        # Determine if the received data is sufficient for the current condition
        is_hist_condition = "hist" in condition
        is_cross_condition = "cross" in condition

        can_evaluate = False
        if is_hist_condition:
            can_evaluate = hist_value is not None
        elif is_cross_condition:
            can_evaluate = macd_value is not None and signal_value is not None
        else:  # value_above/below (usually by MACD line)
            can_evaluate = macd_value is not None

        if can_evaluate:
            try:
                hist_f = float(hist_value) if hist_value is not None else 0.0
                macd_f = float(macd_value) if macd_value is not None else 0.0
                signal_f = float(signal_value) if signal_value is not None else 0.0

                macd_prev = self._get_previous_indicator_value(
                    pair_info, market_data, macd_key, 1
                )
                signal_prev = self._get_previous_indicator_value(
                    pair_info, market_data, signal_key, 1
                )

                value_to_check = hist_f if is_hist_condition else macd_f
                result = evaluate_macd_logic(
                    value_to_check, signal_f, macd_prev, signal_prev, condition
                )

                return bool(result), {
                    "macd": macd_f,
                    "signal": signal_f,
                    "histogram": hist_f,
                    "condition": condition,
                    "fast_period": fast,
                    "slow_period": slow,
                    "signal_period": signal_p,
                }
            except (ValueError, TypeError):
                pass  # Fall through to dynamic calculation

        # Calculate dynamically from kline data
        candle_tf = pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")
        return evaluate_macd_scalar(df, params)

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_condition_stochastic (Genetic Alias: stoch_condition)
    def _check_condition_stochastic(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Checks the condition for the Stochastic indicator.
        Uses evaluate_stochastic_scalar from condition_core.py for dynamic calculation.
        """
        from .condition_core import (
            evaluate_stochastic_scalar,
            evaluate_stochastic_logic,
        )

        k_per = int(params.get("k_period", 14))
        d_per = int(params.get("d_period", 3))
        smooth = int(params.get("smooth_k", 3))
        operator = params.get("operator", "gt")
        value = float(params.get("value", 80))
        line = params.get("line", "k")

        k_key = f"STOCHk_{k_per}_{d_per}_{smooth}"
        d_key = f"STOCHd_{k_per}_{d_per}_{smooth}"

        k_val = pair_info.get(k_key)
        d_val = pair_info.get(d_key)

        # If values are present in pair_info, use them
        if k_val is not None:
            try:
                k0 = float(k_val)
                d0 = float(d_val) if d_val is not None else 0.0
                k1 = self._get_previous_indicator_value(
                    pair_info, market_data, k_key, 1
                )
                d1 = (
                    self._get_previous_indicator_value(pair_info, market_data, d_key, 1)
                    if d_val is not None
                    else None
                )

                result = evaluate_stochastic_logic(
                    k0, d0, k1, d1, operator, value, line
                )
                return bool(result), {
                    "k": k0,
                    "d": d0,
                    "k_period": k_per,
                    "d_period": d_per,
                    "slowing": smooth,
                    "operator": operator,
                    "threshold": value,
                }
            except (ValueError, TypeError):
                pass  # Fall through to dynamic calculation

        # Calculate dynamically from kline data
        candle_tf = pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")
        return evaluate_stochastic_scalar(df, params)

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_condition_bollinger (Genetic Alias: bb_condition)
    def _check_condition_bollinger(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Checks the condition for Bollinger Bands.
        Uses evaluate_bollinger_scalar from condition_core.py for dynamic calculation.
        """
        from .condition_core import evaluate_bollinger_scalar, evaluate_bollinger_logic

        period = int(params.get("period", 20))
        std_dev = float(params.get("std_dev", 2.0))
        check_type = params.get("check_type", "price_below_lower")
        width_value = float(params.get("width_value", 0.01))

        # Searching for keys in pair_info
        lower_key = f"BBL_{period}_{std_dev}"
        upper_key = f"BBU_{period}_{std_dev}"
        width_key = f"BBB_{period}_{std_dev}"

        lower = pair_info.get(lower_key)
        upper = pair_info.get(upper_key)
        width = pair_info.get(width_key)
        close = pair_info.get("close")

        # If there are ready values in pair_info, use them
        if close is not None and (lower is not None or upper is not None):
            try:
                close_f = float(close)
                lower_f = float(lower) if lower is not None else None
                upper_f = float(upper) if upper is not None else None
                width_f = float(width) if width is not None else None

                result = evaluate_bollinger_logic(
                    close_f, lower_f, upper_f, width_f, check_type, width_value
                )
                return bool(result), {
                    "lower": lower_f,
                    "upper": upper_f,
                    "width": width_f,
                    "close": close_f,
                    "period": period,
                    "std_dev": std_dev,
                    "check": check_type,
                }
            except (ValueError, TypeError):
                pass  # Fall through to dynamic calculation

        # Calculate dynamically from kline data
        candle_tf = pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")
        return evaluate_bollinger_scalar(df, params)

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_filter_adx
    def _check_filter_adx(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """ADX filter. Uses evaluate_adx_scalar from condition_core.py."""
        from .condition_core import evaluate_adx_scalar, evaluate_adx_logic

        period = int(params.get("period", 14))
        threshold = float(params.get("threshold", 25))
        operator = params.get("operator", "gt")

        adx_key = f"ADX_{period}"
        adx_val = pair_info.get(adx_key)

        # If there is a ready value in pair_info, use it
        if adx_val is not None:
            try:
                adx = float(adx_val)
                result = evaluate_adx_logic(adx, threshold, operator)
                return bool(result), {
                    "adx": adx,
                    "period": period,
                    "threshold": threshold,
                    "operator": operator,
                }
            except (ValueError, TypeError):
                pass  # Fall through to dynamic calculation

        # Calculate dynamically from kline data
        candle_tf = pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")
        return evaluate_adx_scalar(df, params)

    # AI_CONTEXT_END

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_filter_natr
    def _check_filter_natr(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """NATR filter. Uses evaluate_natr_scalar from condition_core.py."""
        from .condition_core import evaluate_natr_scalar

        # First check if there is a ready value in pair_info
        period = int(params.get("period", 14))
        natr_key = f"NATR_{period}"
        natr_val = pair_info.get(natr_key)

        if natr_val is not None:
            # Using the ready value
            from .condition_core import evaluate_natr_logic

            threshold = float(
                params.get(
                    "value", params.get("threshold", params.get("natr_threshold", 1.0))
                )
            )
            operator = params.get("operator", "gt")
            try:
                natr = float(natr_val)
                result = evaluate_natr_logic(natr, threshold, operator)
                return bool(result), {
                    "natr": natr,
                    "threshold": threshold,
                    "operator": operator,
                    "period": period,
                }
            except (ValueError, TypeError):
                pass  # Fall through to dynamic calculation

        # Calculate dynamically from kline data
        candle_tf = pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")
        return evaluate_natr_scalar(df, params)

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_filter_rel_vol (Relative Volume Filter)
    def _check_filter_rel_vol(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Relative volume filter.

        Parameters:
        - rel_vol_threshold (float): Threshold. Default: 1.5.
        - lookback_period (int): Period for calculating average volume. Default: 20.
        """
        threshold = float(
            self._resolve_value(
                params.get("rel_vol_threshold", params.get("multiplier", 1.5)), context
            )
        )
        lookback = int(self._resolve_value(params.get("lookback_period", 20), context))

        # If a custom period is specified, calculate on the spot
        if lookback != 20:
            candle_tf = pair_info.get("candle_timeframe", "1m")
            df = market_data.get(f"kline_{candle_tf}")
            current_idx = pair_info.get("current_candle_index")

            if df is not None and current_idx is not None and current_idx >= lookback:
                try:
                    curr_vol = float(df["volume"].iloc[current_idx])
                    avg_vol = float(
                        df["volume"].iloc[current_idx - lookback : current_idx].mean()
                    )
                    if avg_vol > 1e-9:
                        rel_vol = curr_vol / avg_vol
                    else:
                        rel_vol = 1.0
                except Exception as e:
                    logger.warning(f"Error calculating dynamic rel_vol: {e}")
                    rel_vol = pair_info.get("relative_volume", 1.0)
            else:
                rel_vol = pair_info.get("relative_volume", 1.0)
        else:
            rel_vol = pair_info.get("relative_volume", 1.0)

        details = {
            "relative_volume": rel_vol,
            "threshold": threshold,
            "lookback_period": lookback,
        }

        if rel_vol is None:
            return False, {**details, "error": "No relative_volume in pair_info"}

        try:
            result = float(rel_vol) > threshold
        except (ValueError, TypeError):
            return False, {**details, "error": "Invalid relative_volume value"}

        return bool(result), details

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_condition_price_comparison
    def _check_condition_value_comparison(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Compares two dynamic or static values with enhanced logging.
        """
        left_operand_cfg = params.get("leftOperand", {})
        right_operand_cfg = params.get("rightOperand", {})
        operator = params.get("operator", "gt")
        details = {}
        result = False

        # 1. Attempting to resolve both operands
        left_value = self._resolve_value(left_operand_cfg, context)
        right_value = self._resolve_value(right_operand_cfg, context)

        details["left_operand_config"] = left_operand_cfg
        details["right_operand_config"] = right_operand_cfg
        details["left_value_resolved"] = left_value
        details["right_value_resolved"] = right_value
        details["operator"] = operator

        # 2. Check that both values were successfully obtained
        if left_value is not None and right_value is not None:
            try:
                # 3. Try to convert them to numbers for comparison
                left_float, right_float = float(left_value), float(right_value)

                # Support for both symbolic and text operators
                op_map = {
                    "gt": left_float > right_float,
                    ">": left_float > right_float,
                    "gte": left_float >= right_float,
                    ">=": left_float >= right_float,
                    "lt": left_float < right_float,
                    "<": left_float < right_float,
                    "lte": left_float <= right_float,
                    "<=": left_float <= right_float,
                    "eq": abs(left_float - right_float) < 1e-9,
                    "==": abs(left_float - right_float) < 1e-9,
                }

                if operator in op_map:
                    result = op_map[operator]
                    # 4. KEY LOG: Show exactly what was compared and what the result was
                    logger.info(
                        f"[VBS|value_comparison] "
                        f"Check: {left_float:.4f} {operator} {right_float:.4f} -> {'PASSED' if result else 'FAILED'}"
                    )
                else:
                    details["error"] = f"Unknown operator: {operator}"
                    logger.warning(
                        f"[VBS|value_comparison] FAILED due to unknown operator: {operator}"
                    )

            except (ValueError, TypeError) as e:
                details["error"] = (
                    f"Could not convert values to float for comparison: Left='{left_value}', Right='{right_value}'. Error: {e}"
                )
                logger.warning(
                    f"[VBS|value_comparison] FAILED due to conversion error: {details['error']}"
                )
        else:
            details["error"] = "One or both operands could not be resolved."
            logger.warning(
                f"[VBS|value_comparison] FAILED because an operand was None. Left: {left_value}, Right: {right_value}"
            )

        return result, details

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_condition_price_vs_level
    def _check_condition_price_vs_level(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Compares the price (or indicator) with a level found in another block.

        Parameters in 'params':
        - price_source (dict): Price source for comparison (dynamic value).
        - operator (str): Comparison operator ('gt' or 'lt').
        - level_source (dict): Level source (dynamic value, usually refers to 'block_result').
        """
        price_source = params.get("price_source")
        operator = params.get("operator", "gt")
        level_source = params.get("level_source")
        details = {}
        result = False

        left_value = self._resolve_value(price_source, context)
        right_value = self._resolve_value(level_source, context)

        details["left_value_resolved"] = left_value
        details["right_value_resolved"] = right_value

        if left_value is not None and right_value is not None:
            try:
                left_float, right_float = float(left_value), float(right_value)
                if operator == "gt":
                    result = left_float > right_float
                elif operator == "lt":
                    result = left_float < right_float
                else:
                    details["error"] = f"Unknown operator: {operator}"
            except (ValueError, TypeError) as e:
                details["error"] = f"Could not convert resolved values to float: {e}"
        else:
            details["error"] = "One or both dynamic values could not be resolved."

        return result, details

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_condition_position_state
    def _check_condition_position_state(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        [FOR POSITION MANAGEMENT ONLY] Checks the state of the current open position.

        Parameters in 'params':
        - key (str): Position attribute to check.
            - 'unrealized_pnl_pct': Unrealized PnL as a percentage of entry.
            - 'unrealized_pnl_rr': Unrealized PnL in risk units (R:R).
            - 'partial_exits_count': Number of triggered partial takes.
        - operator (str): Comparison operator ('>', '>=', '<', '<=', '==').
        - value (float): Threshold value for comparison.
        """
        key = params.get("key")
        operator = params.get("operator", ">=")
        value = self._resolve_value(params.get("value"), context)
        details = {}
        result = False

        position = context.get("position")
        if not position:
            details["error"] = (
                "Position state check called outside of position management context."
            )
            return False, details

        position_value_cfg = {"source": "position_state", "key": key}
        position_value = self._resolve_value(position_value_cfg, context)

        details["position_value_resolved"] = position_value

        if position_value is not None and value is not None:
            try:
                pos_float, val_float = float(position_value), float(value)
                op_map = {
                    ">": pos_float > val_float,
                    ">=": pos_float >= val_float,
                    "<": pos_float < val_float,
                    "<=": pos_float <= val_float,
                    "==": abs(pos_float - val_float) < 1e-9,
                }
                if operator in op_map:
                    result = op_map[operator]
                else:
                    details["error"] = f"Unknown operator: {operator}"
            except (ValueError, TypeError) as e:
                details["error"] = f"Could not convert values to float: {e}"
        else:
            details["error"] = (
                "Position state value or comparison value could not be resolved."
            )

        return result, details

    # AI_CONTEXT_END

    def _check_specific_signal_logic(
        self,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        foundations: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        logger.warning(f"_check_specific_signal_logic not implemented for {self.NAME}")
        return None  # pragma: no cover

    def check_foundations(
        self, pair_info: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        foundations_status: Dict[str, Any] = {}
        trace_nodes: List[Dict[str, Any]] = []
        symbol = pair_info.get("symbol", "UNKNOWN")
        log_prefix = f"[{self.NAME}:{symbol}:Foundations]"

        try:
            # 1. Market activity
            is_active, market_activity_details = (
                self._check_foundation_market_activity_wrapper(
                    pair_info, market_data, {}, {}
                )
            )
            foundations_status[FOUNDATION_MARKET_ACTIVITY] = is_active
            trace_nodes.append(
                {
                    "id": FOUNDATION_MARKET_ACTIVITY,
                    "type": "foundation",
                    "result": is_active,
                    "details": market_activity_details,
                }
            )

            # 2. Trend
            base_strategy_name = "FirstPullbacksInTrend"
            trend_direction = _determine_trend_direction(
                pair_info,
                sma_fast_period=self._get_param_from_original_strategy(
                    base_strategy_name, "sma_fast_period", 10
                ),
                sma_slow_period=self._get_param_from_original_strategy(
                    base_strategy_name, "sma_slow_period", 50
                ),
                rsi_period=self._get_param_from_original_strategy(
                    base_strategy_name, "rsi_period", 14
                ),
                rsi_trend_zone_lower=self._get_param_from_original_strategy(
                    base_strategy_name, "rsi_lower_bound", 30
                ),
                rsi_trend_zone_upper=self._get_param_from_original_strategy(
                    base_strategy_name, "rsi_upper_bound", 70
                ),
            )
            foundations_status[FOUNDATION_TREND] = trend_direction not in ["FLAT", None]
            foundations_status["trend_detected"] = (
                trend_direction if trend_direction else "None"
            )
            trace_nodes.append(
                {
                    "id": FOUNDATION_TREND,
                    "type": "foundation",
                    "result": foundations_status[FOUNDATION_TREND],
                    "details": {"direction": trend_direction},
                }
            )

            # 3. Levels
            is_near_level, level_details = self._check_foundation_level_wrapper(
                pair_info, market_data, {}, {}
            )
            foundations_status[FOUNDATION_LEVEL] = is_near_level
            trace_nodes.append(
                {
                    "id": FOUNDATION_LEVEL,
                    "type": "significant_level",
                    "result": foundations_status[FOUNDATION_LEVEL],
                    "details": level_details,
                }
            )

            # 4. Volume
            volume_params = {
                "lookback_period": self._get_param("kline_vol_lookback", 20),
                "multiplier": self._get_param("kline_vol_multiplier", 1.8),
            }
            volume_confirmed, volume_details = (
                self._check_foundation_volume_confirmation_wrapper(
                    pair_info, market_data, volume_params, {}
                )
            )
            foundations_status[FOUNDATION_VOLUME_CONFIRMATION] = volume_confirmed
            trace_nodes.append(
                {
                    "id": FOUNDATION_VOLUME_CONFIRMATION,
                    "type": "volume_confirmation",
                    "result": foundations_status[FOUNDATION_VOLUME_CONFIRMATION],
                    "details": {**volume_params, **volume_details},
                }
            )

            # 5. Round levels
            is_near_round, round_details = (
                self._check_foundation_round_number_level_wrapper(
                    pair_info, market_data, {}, {}
                )
            )
            foundations_status[FOUNDATION_ROUND_NUMBER] = is_near_round
            trace_nodes.append(
                {
                    "id": FOUNDATION_ROUND_NUMBER,
                    "type": "round_level",
                    "result": foundations_status[FOUNDATION_ROUND_NUMBER],
                    "details": round_details,
                }
            )

            # 6. Order book
            orderbook_analysis_result = _check_foundation_orderbook(
                pair_info,
                market_data,
                min_density_usd=self._get_param(
                    "ORDERBOOK_FOUNDATION_MIN_DENSITY_USD", 100000
                ),
                levels_to_check=self._get_param(
                    "ORDERBOOK_FOUNDATION_LEVELS_TO_CHECK", 5
                ),
                use_analysis=self._get_param("USE_COMPANION_ORDERBOOK_ANALYSIS", True),
                conflict_ticks=self._get_param("OB_CONFLICT_PROXIMITY_TICKS", 2),
                near_ticks=self._get_param("DENSITY_NEAR_PROXIMITY_TICKS", 3),
            )
            foundations_status[FOUNDATION_ORDERBOOK] = orderbook_analysis_result
            trace_nodes.append(
                {
                    "id": FOUNDATION_ORDERBOOK,
                    "type": "orderbook_condition",
                    "result": bool(
                        orderbook_analysis_result.nearest_support
                        or orderbook_analysis_result.nearest_resistance
                    ),
                    "details": {
                        "conflict": orderbook_analysis_result.conflict,
                        "support_found_at": orderbook_analysis_result.nearest_support.price
                        if orderbook_analysis_result.nearest_support
                        else None,
                        "support_size_usd": orderbook_analysis_result.nearest_support.size_usd
                        if orderbook_analysis_result.nearest_support
                        else None,
                        "resistance_found_at": orderbook_analysis_result.nearest_resistance.price
                        if orderbook_analysis_result.nearest_resistance
                        else None,
                        "resistance_size_usd": orderbook_analysis_result.nearest_resistance.size_usd
                        if orderbook_analysis_result.nearest_resistance
                        else None,
                        "is_price_near_support": orderbook_analysis_result.is_price_near_support,
                        "is_price_near_resistance": orderbook_analysis_result.is_price_near_resistance,
                    },
                }
            )

        except Exception as e:
            logger.error(
                f"{log_prefix} Error during base foundation checks: {e}", exc_info=True
            )

        return foundations_status, trace_nodes

    # AI_CONTEXT_START: _check_foundation_market_activity
    def _check_foundation_market_activity(
        self,
        pair_info: Dict[str, Any],
        market_data: Optional[Dict[str, Any]] = None,
        params_override: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Checks if the market is active enough for trading.
        The condition passes if volatility (NATR) is above the threshold OR volume (relative_volume/volume_spike) is above the threshold.

        Parameters in 'params' (when called from JSON):
        - mode (str): Volume check mode.
            - 'percentile' (default): uses the pre-calculated 'is_volume_spike' flag.
            - 'relative': compares 'relative_volume' with a threshold.
        - natr_threshold (float): Minimum NATR value. Example: 1.0.
        - rel_vol_threshold (float): Minimum relative_volume value (only for 'relative' mode). Example: 1.5.
        """
        symbol = pair_info.get("symbol", "Unknown")
        log_prefix = f"[{self.NAME}:{symbol}:F_MarketActivity]"
        params = params_override or {}

        # Defining the filter operation mode
        # By default, the new, more reliable 'percentile' mode is used
        mode = params.get("mode", "percentile").lower()

        # General logic for all modes
        natr_actual = pair_info.get("natr")
        natr_threshold = float(params.get("natr_threshold", 1.0))

        if natr_actual is None:
            logger.warning(f"{log_prefix} Missing 'natr' in pair_info.")
            return False

        natr_check_passed = float(natr_actual) >= natr_threshold

        # Volume check logic depending on the mode
        volume_check_passed = False
        details = {"natr_actual": natr_actual, "natr_threshold": natr_threshold}

        if mode == "percentile":
            # NEW MODE (RECOMMENDED): Comparison with a percentile threshold
            is_spike = pair_info.get("is_volume_spike")  # This is a ready boolean value
            if is_spike is None:
                logger.warning(
                    f"{log_prefix} Missing 'is_volume_spike' in pair_info for percentile mode."
                )
                volume_check_passed = False
            else:
                volume_check_passed = bool(is_spike)

            details["mode"] = "percentile"
            details["volume_spike_detected"] = volume_check_passed

        elif mode == "relative":
            # OLD MODE: Comparison with relative volume
            rel_vol_actual = pair_info.get("relative_volume")
            rel_vol_threshold = float(params.get("rel_vol_threshold", 1.5))
            lookback = int(params.get("lookback_period", 20))

            # If a custom period is specified, calculate on the spot
            if lookback != 20:
                candle_tf = pair_info.get("candle_timeframe", "1m")
                df = market_data.get(f"kline_{candle_tf}") if market_data else None
                current_idx = pair_info.get("current_candle_index")

                if df is not None and current_idx is not None:
                    if "volume" in df.columns:
                        volumes = df["volume"].iloc[
                            max(0, current_idx - lookback) : current_idx
                        ]
                        if not volumes.empty:
                            avg_vol = volumes.mean()
                            current_vol = df["volume"].iloc[current_idx]
                            rel_vol = current_vol / avg_vol if avg_vol > 0 else 0
                            rel_vol_actual = rel_vol

            if rel_vol_actual is None:
                logger.warning(
                    f"{log_prefix} 'relative_volume' is missing in pair_info for relative mode."
                )
                volume_check_passed = False
            else:
                volume_check_passed = float(rel_vol_actual) >= rel_vol_threshold

            details["mode"] = "relative"
            details["rel_vol_actual"] = rel_vol_actual
            details["rel_vol_threshold"] = rel_vol_threshold
            details["lookback_period"] = lookback

        else:
            logger.error(f"{log_prefix} Unknown mode for market_activity: '{mode}'")
            return False

        # The filter passes if the volatility (NATR) OR volume check is passed
        is_active = natr_check_passed or volume_check_passed

        logger.info(
            f"--- ACTIVITY FILTER [{symbol}] --- "
            f"NATR Check: [Value: {natr_actual:.4f}, Threshold: {natr_threshold}, Passed: {natr_check_passed}]. "
            f"Volume Check (Mode: {mode}): [Passed: {volume_check_passed}]. "
            f"Final Result (NATR or VOL): {is_active}"
        )

        if not is_active:
            logger.debug(
                f"{log_prefix} Market INACTIVE. NATR_OK: {natr_check_passed}, VOL_OK: {volume_check_passed}. Details: {details}"
            )

        return is_active

    # AI_CONTEXT_END

    # AI_CONTEXT_START: _check_foundation_level
    def _check_foundation_level(
        self, pair_info: Dict[str, Any], market_data: Dict[str, Any]
    ) -> bool:
        """
        Checks if the price is near significant global levels (previous day, H4, H1).
        Proximity is defined as 25% of ATR.
        This block does not take parameters.
        """
        symbol = pair_info.get("symbol", "Unknown")
        log_prefix = f"[{self.NAME}:{symbol}:F_Level]"
        last_price = pair_info.get("last_price")
        atr = pair_info.get("atr")
        current_ts = pair_info.get("timestamp_dt")  # FIX: Getting the current timestamp

        if last_price is None or atr is None or atr <= 0:
            return False

        # Explicitly collect all available DataFrames for level analysis.
        # This ensures that even if there is only one kline_1d in market_data, it will be used.
        available_market_data_for_levels = {
            key: df
            for key, df in market_data.items()
            if key.startswith("kline_")
            and isinstance(df, pd.DataFrame)
            and not df.empty
        }

        if not available_market_data_for_levels:
            return False

        # Calling find_significant_levels without lookback_config so it uses its default.
        # Passing explicitly collected data.
        significant_levels = find_significant_levels(
            available_market_data_for_levels, current_timestamp_dt=current_ts
        )

        if not any(significant_levels.values()):
            return False

        proximity_threshold = atr * 0.25
        for level_type, levels in significant_levels.items():
            for level in levels:
                if abs(last_price - level) <= proximity_threshold:
                    logger.debug(f"{log_prefix} Near {level_type} level {level:.4f}")
                    return True

        return False

    # AI_CONTEXT_END

    # AI_CONTEXT_START: orderbook_condition
    def _check_foundation_orderbook_wrapper(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        """
        Checks the order book for the presence of large densities (support or resistance).
        Acts as a wrapper for calling the main order book analysis logic.

        Parameters in 'params':
        - min_density_usd (float): Minimum density size in USD. Example: 100000.
        - levels_to_check (int): How many levels in the order book to check. Example: 5.
        - side (str): 'support', 'resistance' or 'any'. Check only support, resistance, or any density.
        - conflict_ticks (int): Tolerance in ticks for determining conflicting densities. Example: 2.
        - near_ticks (int): Tolerance in ticks for determining price proximity to density. Example: 5.
        """
        # 1. "Unpacks" specific parameters from params, setting default values and using _resolve_value
        min_density = float(
            self._resolve_value(params.get("min_density_usd", 100000), context)
        )
        levels = int(self._resolve_value(params.get("levels_to_check", 5), context))
        side = params.get("side", "any")
        conflict = int(self._resolve_value(params.get("conflict_ticks", 2), context))
        near = int(self._resolve_value(params.get("near_ticks", 5), context))

        # 2. Calls the ORIGINAL function with correct, unpacked arguments
        analysis_result = _check_foundation_orderbook(
            pair_info=pair_info,
            market_data=market_data,
            min_density_usd=min_density,
            levels_to_check=levels,
            use_analysis=True,  # Assume that we always use companion orderbook
            conflict_ticks=conflict,
            near_ticks=near,
            side=side,
        )

        # 3. Formats the complex result into a standard tuple (bool, dict) for the dispatcher
        is_met = (
            (side == "support" and analysis_result.nearest_support)
            or (side == "resistance" and analysis_result.nearest_resistance)
            or (
                side == "any"
                and (
                    analysis_result.nearest_support
                    or analysis_result.nearest_resistance
                )
            )
        )

        details = {
            "support_found_at": analysis_result.nearest_support.price
            if analysis_result.nearest_support
            else None,
            "resistance_found_at": analysis_result.nearest_resistance.price
            if analysis_result.nearest_resistance
            else None,
        }

        return is_met, details

    # AI_CONTEXT_END

    def _calculate_partial_targets_from_config(
        self,
        entry_price: float,
        direction: SignalDirection,
        partial_exits_raw: List[Dict[str, Any]],
        tick_size: Optional[float],
        stop_loss_price: Optional[float] = None,
        atr_at_signal_time: Optional[float] = None,
    ) -> Optional[List[PartialTarget]]:
        if tick_size is None or tick_size <= 0:
            logger.error(
                f"[{self.NAME}] Invalid tick_size ({tick_size}) for partial target calculation."
            )
            return None

        rounding_mode = ROUND_UP if direction == SignalDirection.LONG else ROUND_DOWN
        partial_targets: List[PartialTarget] = []
        log_prefix = f"[{self.NAME}:{entry_price:.4f}:PartialExits]"

        for idx, exit_item in enumerate(partial_exits_raw):
            try:
                tp_type = exit_item.get("tp_type", "rr_multiplier")
                tp_value = float(exit_item["tp_value"])
                fraction = float(exit_item["size_pct"]) / 100.0
            except (ValueError, TypeError, KeyError) as exc:
                logger.error(
                    f"{log_prefix} Invalid format in partial_exits item #{idx + 1}: {exc}"
                )
                return None

            if fraction <= 0:
                logger.warning(
                    f"{log_prefix} Partial exit #{idx + 1} has non-positive size_pct={exit_item.get('size_pct')}. Skipping."
                )
                continue

            target_price_raw: Optional[float] = None

            if tp_type == "rr_multiplier":
                if stop_loss_price is None:
                    logger.warning(
                        f"{log_prefix} Partial exit #{idx + 1} uses rr_multiplier but stop_loss is disabled. Skipping."
                    )
                    continue
                risk_distance = abs(entry_price - stop_loss_price)
                if risk_distance <= 1e-12:
                    logger.warning(
                        f"{log_prefix} Partial exit #{idx + 1} has zero SL distance. Skipping."
                    )
                    continue
                target_price_raw = (
                    entry_price + (risk_distance * tp_value)
                    if direction == SignalDirection.LONG
                    else entry_price - (risk_distance * tp_value)
                )
            elif tp_type == "percent_from_price":
                target_price_raw = (
                    entry_price * (1 + tp_value / 100.0)
                    if direction == SignalDirection.LONG
                    else entry_price * (1 - tp_value / 100.0)
                )
            elif tp_type == "fixed_price":
                target_price_raw = tp_value
            elif tp_type == "atr_multiplier":
                if atr_at_signal_time is None or atr_at_signal_time <= 0:
                    logger.warning(
                        f"{log_prefix} Partial exit #{idx + 1} uses atr_multiplier but ATR is unavailable. Skipping."
                    )
                    continue
                target_price_raw = (
                    entry_price + (atr_at_signal_time * tp_value)
                    if direction == SignalDirection.LONG
                    else entry_price - (atr_at_signal_time * tp_value)
                )
            else:
                logger.warning(
                    f"{log_prefix} Unsupported partial exit tp_type='{tp_type}' in item #{idx + 1}. Skipping."
                )
                continue

            rounded_target_price = round_price_by_tick(
                target_price_raw, tick_size, rounding_mode
            )
            if rounded_target_price is None or rounded_target_price <= 0:
                logger.warning(
                    f"{log_prefix} Rounded partial target price is invalid for item #{idx + 1}: {rounded_target_price}. Skipping."
                )
                continue

            if (
                direction == SignalDirection.LONG
                and rounded_target_price <= entry_price
            ):
                logger.warning(
                    f"{log_prefix} Partial exit #{idx + 1} target {rounded_target_price:.8f} is not above entry {entry_price:.8f}. Skipping."
                )
                continue
            if (
                direction == SignalDirection.SHORT
                and rounded_target_price >= entry_price
            ):
                logger.warning(
                    f"{log_prefix} Partial exit #{idx + 1} target {rounded_target_price:.8f} is not below entry {entry_price:.8f}. Skipping."
                )
                continue

            partial_targets.append(
                PartialTarget(price=rounded_target_price, fraction=fraction)
            )

        if not partial_targets:
            return None

        partial_targets.sort(
            key=lambda target: target.price,
            reverse=(direction == SignalDirection.SHORT),
        )
        return partial_targets

    def _calculate_partial_targets_from_rr(
        self,
        entry_price: float,
        stop_loss_price: float,
        direction: SignalDirection,
        rr_targets_config: Optional[List[Tuple[float, float]]] = None,
        tick_size: Optional[float] = None,
        atr_at_signal_time: Optional[float] = None,
    ) -> Optional[List[PartialTarget]]:
        if tick_size is None or tick_size <= 0:
            logger.error(
                f"[{self.NAME}] Invalid tick_size ({tick_size}) for partial target calculation."
            )
            return None

        targets: List[PartialTarget] = []
        risk_distance = (
            abs(entry_price - stop_loss_price) if stop_loss_price is not None else 0.0
        )
        log_prefix_local = f"[{self.NAME}:{entry_price:.4f}]"

        min_risk_pct_for_rr_calc = self._get_param(
            "min_risk_pct_for_rr_targets_override",
            getattr(config, "STRATEGY_MIN_RISK_PCT_FOR_RR_TARGETS", 0.001),
        )
        min_risk_atr_mult_for_rr_calc = self._get_param(
            "min_risk_atr_mult_for_rr_targets_override",
            getattr(config, "STRATEGY_MIN_RISK_ATR_MULT_FOR_RR_TARGETS", 0.2),
        )
        risk_is_too_small_for_rr = False
        if risk_distance < entry_price * min_risk_pct_for_rr_calc:
            risk_is_too_small_for_rr = True
        elif (
            atr_at_signal_time
            and atr_at_signal_time > 0
            and risk_distance < atr_at_signal_time * min_risk_atr_mult_for_rr_calc
        ):
            risk_is_too_small_for_rr = True

        current_tp_config_raw = None
        is_percent_based = False
        if risk_is_too_small_for_rr:
            current_tp_config_raw = self._get_param("small_risk_percent_tp_config")
            is_percent_based = True
            logger.info(
                f"{log_prefix_local} Risk distance {risk_distance:.8f} is very small. Using %-based partial TP config."
            )
        elif rr_targets_config:
            current_tp_config_raw = rr_targets_config
            is_percent_based = False
            logger.debug(f"{log_prefix_local} Using R/R-based partial TP config.")
        else:
            logger.debug(
                f"{log_prefix_local} No partial TP config applicable. No partial targets will be set."
            )
            return None

        parsed_tp_config: List[Tuple[float, float]] = []
        if isinstance(current_tp_config_raw, list) and all(
            isinstance(t, (tuple, list)) and len(t) == 2 for t in current_tp_config_raw
        ):
            try:
                parsed_tp_config = sorted(
                    [(float(p_or_r), float(f)) for p_or_r, f in current_tp_config_raw],
                    key=lambda x: x[0],
                )
            except (ValueError, TypeError):
                logger.warning(
                    f"{log_prefix_local} Invalid format for TP config. Config: {current_tp_config_raw}"
                )

        if not parsed_tp_config:
            log_type_str = "percent-based" if is_percent_based else "R/R-based"
            logger.warning(
                f"{log_prefix_local} No valid {log_type_str} TP config items found after parsing. Raw config: {current_tp_config_raw}"
            )
            return None

        min_tp_distance_pct = getattr(config, "MIN_PARTIAL_TP_DISTANCE_PCT", 0.004)
        cumulative_fraction = 0.0
        num_targets_in_config = len(parsed_tp_config)

        for i, (target_level_or_percent, configured_fraction) in enumerate(
            parsed_tp_config
        ):
            is_last_target_in_config = i == num_targets_in_config - 1
            fraction_to_close_this_target = configured_fraction

            if cumulative_fraction + configured_fraction >= 1.0 - 1e-9:
                fraction_to_close_this_target = max(0, 1.0 - cumulative_fraction)
                logger.info(
                    f"{log_prefix_local} Target #{i + 1} (Level/Pct: {target_level_or_percent:.4f}) will close remaining position. Original frac: {configured_fraction:.2f}, Adjusted frac: {fraction_to_close_this_target:.2f}"
                )
            elif is_last_target_in_config and configured_fraction < 1e-9:
                fraction_to_close_this_target = max(0, 1.0 - cumulative_fraction)
                logger.info(
                    f"{log_prefix_local} Last Target #{i + 1} (Level/Pct: {target_level_or_percent:.4f}) has zero fraction, will close remaining. Adjusted frac: {fraction_to_close_this_target:.2f}"
                )

            if fraction_to_close_this_target <= 1e-9:
                logger.debug(
                    f"{log_prefix_local} Target #{i + 1} (Level/Pct: {target_level_or_percent:.4f}) has zero/negative fraction to close ({fraction_to_close_this_target:.2f}). Skipping."
                )
                if cumulative_fraction >= 1.0 - 1e-9:
                    break
                continue

            if target_level_or_percent <= 0:
                logger.warning(
                    f"{log_prefix_local} Invalid target level/percent ({target_level_or_percent}). Skipping target."
                )
                continue

            target_price_raw = 0.0
            if is_percent_based:
                target_price_raw = (
                    entry_price * (1 + target_level_or_percent)
                    if direction == SignalDirection.LONG
                    else entry_price * (1 - target_level_or_percent)
                )
            else:
                if risk_distance <= 1e-9:
                    logger.warning(
                        f"{log_prefix_local} Risk distance zero for R/R target {target_level_or_percent}. Skipping."
                    )
                    continue
                target_price_raw_rr = (
                    entry_price + risk_distance * target_level_or_percent
                    if direction == SignalDirection.LONG
                    else entry_price - risk_distance * target_level_or_percent
                )
                min_profit_abs = entry_price * min_tp_distance_pct
                target_price_raw_min_pct = (
                    entry_price + min_profit_abs
                    if direction == SignalDirection.LONG
                    else entry_price - min_profit_abs
                )
                target_price_raw = (
                    max(target_price_raw_rr, target_price_raw_min_pct)
                    if direction == SignalDirection.LONG
                    else min(target_price_raw_rr, target_price_raw_min_pct)
                )

            rounding_mode = (
                ROUND_UP if direction == SignalDirection.LONG else ROUND_DOWN
            )
            target_price_rounded = round_price_by_tick(
                target_price_raw, tick_size, rounding_mode
            )

            if target_price_rounded is None:
                continue
            if (
                direction == SignalDirection.LONG
                and target_price_rounded <= entry_price + (tick_size / 2)
            ) or (
                direction == SignalDirection.SHORT
                and target_price_rounded >= entry_price - (tick_size / 2)
            ):
                continue

            if targets:
                last_added_tp = targets[-1].price
                min_diff = tick_size / 2
                if (
                    direction == SignalDirection.LONG
                    and target_price_rounded <= last_added_tp + min_diff
                ) or (
                    direction == SignalDirection.SHORT
                    and target_price_rounded >= last_added_tp - min_diff
                ):
                    continue

            try:
                targets.append(
                    PartialTarget(
                        price=target_price_rounded,
                        fraction=fraction_to_close_this_target,
                    )
                )
                cumulative_fraction += fraction_to_close_this_target
                log_type_str = "%-based" if is_percent_based else "R/R-based"
                logger.debug(
                    f"{log_prefix_local} Added {log_type_str} Partial TP: Level/Pct={target_level_or_percent:.4f}, Price={target_price_rounded:.8f}, Fraction={fraction_to_close_this_target:.2f}, CumulativeFrac={cumulative_fraction:.2f}"
                )
            except ValueError as e:
                logger.error(f"{log_prefix_local} Error creating PartialTarget: {e}")
                continue

            if cumulative_fraction >= 1.0 - 1e-9:
                logger.info(
                    f"{log_prefix_local} Cumulative fraction {cumulative_fraction:.2f} reached >= 1.0. Stopping target generation."
                )
                break

        if targets:
            logger.debug(
                f"{log_prefix_local} Successfully calculated {len(targets)} partial targets. Total fraction: {cumulative_fraction:.2f}"
            )
        else:
            logger.warning(
                f"{log_prefix_local} Failed to calculate any valid partial targets."
            )
        return targets if targets else None

    def _get_param_from_original_strategy(
        self, original_strategy_name: str, param_name: str, default: Any = None
    ) -> Any:
        return config.get_strategy_param(original_strategy_name, param_name, default)

    def get_tradable_params(self) -> List[str]:
        """Returns a list of parameter names that can be configured."""
        # Child classes can override this to show only the necessary parameters
        # By default, return several common ones
        return [
            "candle_timeframe",
            "stop_loss_atr_multiplier",
            "take_profit_atr_multiplier",
        ]

    def _get_expensive_weight(self, node: Dict[str, Any]) -> float:
        """
        Recursively calculates the sum of weights for all 'expensive' (second_bar_trigger) nodes.
        UPDATED: Correctly handles logic gates for max possible weight calculation.
        """
        total_weight = 0.0
        node_type = node.get("type")

        if node_type == "AND":
            # For AND, all children must be met, so we sum their expensive weights.
            for child in node.get("children", []):
                total_weight += self._get_expensive_weight(child)
        elif node_type == "OR":
            # For OR, only one child needs to be met. We find the child path with the maximum possible expensive weight.
            max_child_weight = 0.0
            for child in node.get("children", []):
                max_child_weight = max(
                    max_child_weight, self._get_expensive_weight(child)
                )
            total_weight = max_child_weight
        else:
            # This is a leaf node (a condition)
            analysis_level = node.get("analysis_level", "minute_bar_filter")
            if analysis_level == "second_bar_trigger":
                # Get the weight for this condition type
                weight = self.foundation_weights.get(node_type, 0.0)
                total_weight += weight

        return total_weight

    async def _handle_dca_management(
        self,
        block: dict,
        position,
        pair_info: dict,
        market_data: dict,
        prev_pair_info: dict,
    ) -> "BasePosition":
        """Processes the averaging logic (DCA) for a position."""
        params = block.get("params", {})
        max_sos = params.get("max_safety_orders", 0)

        if position.dca_active_sos >= max_sos:
            return position

        symbol = position.symbol
        log_prefix = f"[{self.NAME}:{symbol}:DCA]"

        step_type = str(params.get("step_type", "percentage")).lower()

        # Proactive placement of the limit grid
        # If the step type allows (percentage or ATR), we place the entire grid immediately after entry
        # ONLY in LIVE mode. In backtest, we use reactive logic for simulation simplicity.
        is_live_mode = pair_info.get("is_live_mode", False)
        if is_live_mode and step_type in ["percentage", "atr"]:
            if (
                not getattr(position, "dca_order_ids", [])
                and not getattr(position, "dca_grid_init_triggered", None)
                and not getattr(position, "dca_grid_init_in_progress", False)
            ):
                logger.info(
                    f"{log_prefix} Initializing proactive DCA Limit Order Grid..."
                )
                position.dca_grid_init_triggered = params
            return position

        # Old reactive logic for custom_condition
        current_price = pair_info.get("last_price")
        entry_price = position.entry_price
        if not current_price or not entry_price:
            return position

        trigger_so = False
        if step_type in ["percentage", "atr"]:
            try:
                step_multiplier = float(params.get("step_multiplier", 1.0))
            except (TypeError, ValueError):
                logger.warning(
                    f"{log_prefix} Invalid step_multiplier for DCA: {params.get('step_multiplier')!r}"
                )
                return position
            active_step_multiplier = step_multiplier**position.dca_active_sos

        if step_type == "percentage":
            step_value_raw = params.get("step_value", 1.0)
            step_value = self._resolve_value(
                step_value_raw, {"pair_info": pair_info, "market_data": market_data}
            )
            try:
                target_step_value = float(step_value) * active_step_multiplier
            except (TypeError, ValueError):
                logger.warning(
                    f"{log_prefix} Invalid percentage step_value for DCA: {step_value_raw!r}"
                )
                return position

            deviation_pct = abs(current_price - entry_price) / entry_price * 100.0
            if deviation_pct >= target_step_value:
                if (
                    position.direction.name == "LONG" and current_price < entry_price
                ) or (
                    position.direction.name == "SHORT" and current_price > entry_price
                ):
                    trigger_so = True

        elif step_type == "atr":
            step_value_raw = params.get("step_value", 1.0)
            step_value = self._resolve_value(
                step_value_raw, {"pair_info": pair_info, "market_data": market_data}
            )
            try:
                target_step_value = float(step_value) * active_step_multiplier
            except (TypeError, ValueError):
                logger.warning(
                    f"{log_prefix} Invalid ATR step_value for DCA: {step_value_raw!r}"
                )
                return position

            atr = pair_info.get("atr")
            if atr and atr > 0:
                deviation_abs = abs(current_price - entry_price)
                if deviation_abs >= atr * target_step_value:
                    if (
                        position.direction.name == "LONG"
                        and current_price < entry_price
                    ) or (
                        position.direction.name == "SHORT"
                        and current_price > entry_price
                    ):
                        trigger_so = True

        elif step_type == "custom_condition":
            condition_root = None
            step_value_condition = params.get("step_value")
            if isinstance(step_value_condition, dict) and step_value_condition.get(
                "type"
            ):
                condition_root = step_value_condition
            else:
                condition_root = self._get_pm_conditions_root(block)

            if condition_root:
                condition_met, _ = self._evaluate_condition_tree(
                    condition_root,
                    pair_info,
                    market_data,
                    prev_pair_info,
                    position=position,
                )
                if condition_met:
                    trigger_so = True

        if trigger_so:
            logger.info(
                f"{log_prefix} DCA Safety Order #{position.dca_active_sos + 1} triggered!"
            )
            vol_mult = float(params.get("volume_multiplier", 1.0))
            add_size_pct = 100.0 * (vol_mult ** (position.dca_active_sos + 1))
            position.scale_in_triggered = {
                "add_size_pct": add_size_pct,
                "is_dca": True,
                "dca_so_index": position.dca_active_sos + 1,
            }
            block["executed_this_candle"] = True

        return position

    async def _handle_grid_management(
        self, block: dict, position, pair_info: dict, market_data: dict
    ) -> "BasePosition":
        """Processes grid trading logic (GRID)."""
        if not getattr(position, "grid_order_ids", []):
            logger.info(
                f"[{self.NAME}:{position.symbol}:GRID] Initializing Grid ladder..."
            )
            position.grid_init_triggered = block.get("params", {})
        return position


class VisualBuilderStrategy(BaseStrategy):
    """
    Empty marker class for strategies created in the visual editor.
    All execution logic is inherited from BaseStrategy, which can now
    interpret JSON configurations.
    """

    NAME = "VisualBuilderStrategy"
    description = "Universal strategy managed via JSON from the visual editor."

    def __init__(
        self, params: Optional[Dict[str, Any]] = None, contract_id: Optional[str] = None
    ):
        super().__init__(params=params, contract_id=contract_id)
        self.max_possible_expensive_weight = 0.0

        visual_config = self._instance_params.get("config")
        if visual_config and isinstance(visual_config, dict):
            # Using _get_expensive_weight from BaseStrategy, as it is already implemented
            entry_conditions_root = visual_config.get("entryConditions")
            if entry_conditions_root:
                self.max_possible_expensive_weight = self._get_expensive_weight(
                    entry_conditions_root
                )

                self._extract_tv_signal_weights(entry_conditions_root)

        logger.info(
            f"[{self.NAME}] Calculated max_possible_expensive_weight: {self.max_possible_expensive_weight}"
        )

    def _extract_tv_signal_weights(self, node: Any):
        """
        Recursively scans the condition tree for 'tradingview_signal' nodes
        and registers their weights in self.foundation_weights.
        """
        if not isinstance(node, dict):
            return

        node_type = node.get("type")
        if node_type == "tradingview_signal":
            params = node.get("params", {})
            signal_id = params.get("signal_id")
            weight = params.get("weight", 0.0)
            if signal_id and weight > 0:
                # Add/Update the weight in foundation_weights
                self.foundation_weights[signal_id] = float(weight)
                logger.info(
                    f"[{self.NAME}] Extracted TV signal weight: {signal_id} -> {weight}"
                )

        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                self._extract_tv_signal_weights(child)

    def _get_all_required_indicators_from_json(self, node: Any) -> Set[str]:
        """
        Recursively traverses JSON and collects indicators.
        """
        if not isinstance(node, dict):
            return set()

        required = set()

        # 1. Checking direct links to indicators
        if node.get("source") == "indicator" and "key" in node:
            required.add(node["key"])

        # 2. Checking SL/TP parameters (ATR Multiplier)
        # Checking both in the node itself and in the params sub-dictionary (structure may differ)
        params = node.get("params", {})

        # Check inside 'params' (standard for blocks)
        if (
            params.get("sl_type") == "atr_multiplier"
            or params.get("tp_type") == "atr_multiplier"
        ):
            p = params.get("atr_period", 14)
            required.add(f"ATR_{p}")

        # Checking in the node root (sometimes initialization is written flatly)
        if (
            node.get("sl_type") == "atr_multiplier"
            or node.get("tp_type") == "atr_multiplier"
        ):
            p = node.get("atr_period", 14)
            required.add(f"ATR_{p}")

        # 3. Processing specific block types
        node_type = node.get("type")

        if node_type == "rsi_condition":
            period = params.get("period", 14)
            required.add(f"RSI_{period}")
        elif node_type == "volatility_filter":
            ind = params.get("indicator", "ATR")
            if ind == "ATR":
                period = params.get("period", 14)
                required.add(f"ATR_{period}")
            elif ind == "BBW":
                period = params.get("period", 20)
                std = params.get("std_dev", 2.0)
                required.add(f"BBL_{period}_{std}")
                required.add(f"BBU_{period}_{std}")
                required.add(f"BBB_{period}_{std}")
        elif node_type == "dca_management" and params.get("step_type") == "atr":
            required.add("ATR_14")
        elif node_type == "adx_filter":
            period = params.get("period", 14)
            required.add(f"ADX_{period}")
        elif node_type == "natr_filter":
            period = params.get("period", 14)
            required.add(f"NATR_{period}")
        elif node_type == "stoch_condition" or node_type == "stochastic_condition":
            k = params.get("k_period", 14)
            d = params.get("d_period", 3)
            smooth = params.get("smooth_k", 3)
            required.add(f"STOCHk_{k}_{d}_{smooth}")
            required.add(f"STOCHd_{k}_{d}_{smooth}")
        elif node_type == "bollinger_bands_condition" or node_type == "bb_condition":
            period = params.get("period", 20)
            std = params.get("std_dev", 2.0)
            required.add(f"BBL_{period}_{std}")
            required.add(f"BBU_{period}_{std}")
            required.add(f"BBB_{period}_{std}")
        elif node_type == "trend_filter" and params.get("indicator") == "ADX":
            # Explicitly add ADX if it is used in the filter
            required.add("ADX_14")
        elif node_type == "trend_direction":
            f_p = params.get("sma_fast_period") or params.get("fast_period")
            s_p = params.get("sma_slow_period") or params.get("slow_period")
            r_p = params.get("rsi_period", 14)
            if f_p:
                required.add(f"SMA_{f_p}")
            if s_p:
                required.add(f"SMA_{s_p}")
            if r_p:
                required.add(f"RSI_{r_p}")
        elif node_type == "macd_condition":
            fast = params.get("fast_period") or params.get("fast", 12)
            slow = params.get("slow_period") or params.get("slow", 26)
            signal_param = params.get("signal_period") or params.get("signal", 9)
            required.add(f"MACD_{fast}_{slow}_{signal_param}")
            required.add(f"MACDs_{fast}_{slow}_{signal_param}")
            required.add(f"MACDh_{fast}_{slow}_{signal_param}")
            required.add(f"MACD_hist_{fast}_{slow}_{signal_param}")
        elif node_type == "ma_cross_condition":
            fast = params.get("fast_period", 9)
            slow = params.get("slow_period", 21)
            required.add(f"SMA_{fast}")
            required.add(f"SMA_{slow}")
        elif node_type == "tape_analysis":
            window = params.get("time_window_sec", 5)
            metric_suffixes = [
                "buy_volume_usd",
                "sell_volume_usd",
                "total_volume_usd",
                "buy_count",
                "sell_count",
                "total_count",
                "delta_volume_usd",
                "delta_count",
                "buy_sell_ratio_volume",
                "buy_sell_ratio_count",
                "avg_trade_size_usd",
            ]
            for suffix in metric_suffixes:
                required.add(f"tape_{suffix}_{window}s")
            avg_lookback = 60
            accel_suffixes = ["volume", "count"]
            for suffix in accel_suffixes:
                required.add(f"tape_accel_mult_{suffix}_{window}s_{avg_lookback}s")
        elif node_type in ["rel_vol_filter", "volume_confirmation", "market_activity"]:
            # Adding a dummy indicator with the required period for correct warmup
            lookback = params.get("lookback_period", 20)
            required.add(f"VOL_LOOKBACK_{lookback}")

        # 4. Recursive traversal of children
        for key, value in node.items():
            if isinstance(value, dict):
                required.update(self._get_all_required_indicators_from_json(value))
            elif isinstance(value, list):
                for item in value:
                    required.update(self._get_all_required_indicators_from_json(item))

        return required

    @property
    def required_indicators(self) -> Set[str]:
        """
        Dynamically determines the necessary indicators by analyzing the JSON configuration.
        """
        if self._required_indicators_cache is not None:
            return set(self._required_indicators_cache)

        visual_config = self._instance_params.get("config")
        if visual_config and isinstance(visual_config, dict):
            required = self._get_all_required_indicators_from_json(visual_config)
        else:
            required = set()
        self._required_indicators_cache = set(required)
        return set(required)


class VolumeBreakoutStrategy(BaseStrategy):
    NAME = "VolumeBreakout"
    description = "Trades on the breakout of the previous candle when confirmed by abnormal volume."

    @property
    def required_data_types(self) -> Set[str]:
        tf = self._get_param("candle_timeframe", "1m")
        base_reqs = super().required_data_types
        strategy_reqs = {f"kline_{tf}", "aggTrade"}
        return base_reqs.union(strategy_reqs)

    def _check_pattern_volume_breakout(
        self,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        current_candle_idx: Optional[int],
    ) -> Tuple[Optional[str], Optional[float]]:
        symbol = pair_info.get("symbol")
        log_prefix = f"[{self.NAME}:{symbol}:PatternCheck]"
        try:
            candle_tf = self._get_param("candle_timeframe", "1m")
        except Exception as e:
            logger.error(f"{log_prefix} Error getting params: {e}")
            return None, None  # pragma: no cover
        kline_key = f"kline_{candle_tf}"
        candles_df = market_data.get(kline_key)
        if (
            current_candle_idx is None
            or not isinstance(candles_df, pd.DataFrame)
            or candles_df.empty
            or current_candle_idx < 1
            or current_candle_idx >= len(candles_df)
        ):
            return None, None
        try:
            last_closed_candle = candles_df.iloc[current_candle_idx]
            prev_closed_candle = candles_df.iloc[current_candle_idx - 1]
            trigger_price = float(last_closed_candle["close"])
            prev_high = float(prev_closed_candle["high"])
            prev_low = float(prev_closed_candle["low"])
            if trigger_price > prev_high:
                return "VolBreakUp", trigger_price
            elif trigger_price < prev_low:
                return "VolBreakDown", trigger_price
        except (IndexError, KeyError, ValueError, TypeError) as e:
            logger.error(
                f"{log_prefix} Error checking breakout at index {current_candle_idx}: {e}",
                exc_info=True,
            )
            return None, None  # pragma: no cover
        return None, None

    def check_foundations(
        self, pair_info: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        # 1. Getting common foundations from the parent
        foundations_status, trace_nodes = super().check_foundations(
            pair_info, market_data
        )

        # 2. Checking our specific pattern
        candle_tf_strat = self._get_param("candle_timeframe", "1m")
        kline_key_strat = f"kline_{candle_tf_strat}"
        candles_df_strat = market_data.get(kline_key_strat)

        current_candle_idx = None
        if isinstance(candles_df_strat, pd.DataFrame) and not candles_df_strat.empty:
            backtest_idx = pair_info.get("current_candle_index")
            current_candle_idx = (
                backtest_idx if backtest_idx is not None else len(candles_df_strat) - 1
            )

        # Check the pattern ONCE and save ALL results
        pattern_name, trigger_price = self._check_pattern_volume_breakout(
            pair_info, market_data, current_candle_idx
        )

        # 3. Updating the status of reasons and trace
        foundations_status[FOUNDATION_PATTERN] = pattern_name is not None
        foundations_status["pattern_detected"] = (
            pattern_name if pattern_name else "None"
        )

        # Save additional data for the next step
        if pattern_name:
            foundations_status["pattern_trigger_price"] = trigger_price

        trace_nodes.append(
            {
                "id": FOUNDATION_PATTERN,
                "type": "foundation",
                "result": (pattern_name is not None),
                "details": f"Pattern: {pattern_name}",
            }
        )

        # If there is a breakout pattern, we consider that we are at the level
        if foundations_status[FOUNDATION_PATTERN]:
            foundations_status[FOUNDATION_LEVEL] = True

        return foundations_status, trace_nodes

    def _check_specific_signal_logic(
        self,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        foundations: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        symbol = pair_info.get("symbol")
        log_prefix = f"[{self.NAME}:{symbol}:SpecificLogic]"
        pattern_name = foundations.get("pattern_detected")
        # Getting trigger_price directly from foundations instead of calling the check again
        trigger_price_from_pattern = foundations.get("pattern_trigger_price")

        if (
            not pattern_name
            or pattern_name == "None"
            or trigger_price_from_pattern is None
        ):
            # This check will now catch cases where the pattern was not found in step 1
            return None

        direction = (
            SignalDirection.LONG
            if "Up" in pattern_name
            else (SignalDirection.SHORT if "Down" in pattern_name else None)
        )
        if direction is None:
            return None

        ob_analysis = foundations.get(FOUNDATION_ORDERBOOK)
        if isinstance(ob_analysis, OrderbookAnalysisResult):
            if (
                direction == SignalDirection.LONG
                and ob_analysis.is_price_near_resistance
            ):
                logger.info(
                    f"{log_prefix} LONG signal REJECTED by OB: Price near resistance."
                )
                return None
            if direction == SignalDirection.SHORT and ob_analysis.is_price_near_support:
                logger.info(
                    f"{log_prefix} SHORT signal REJECTED by OB: Price near support."
                )
                return None

        try:
            trigger_price = trigger_price_from_pattern
            candle_tf_strat = self._get_param("candle_timeframe", "1m")
            kline_key_strat = f"kline_{candle_tf_strat}"
            candles_df_strat = market_data.get(kline_key_strat)
            current_candle_idx_strat: Optional[int] = None
            backtest_idx = pair_info.get("current_candle_index")
            if (
                isinstance(candles_df_strat, pd.DataFrame)
                and not candles_df_strat.empty
            ):
                current_candle_idx_strat = (
                    backtest_idx
                    if backtest_idx is not None
                    else len(candles_df_strat) - 1
                )
            if current_candle_idx_strat is None:
                logger.warning(f"{log_prefix} Invalid index for specific logic.")
                return None
            _, trigger_price_from_pattern = self._check_pattern_volume_breakout(
                pair_info, market_data, current_candle_idx_strat
            )
            if trigger_price_from_pattern is None:
                logger.debug(f"{log_prefix} Pattern check did not yield trigger price.")
                return None
            retest_atr_percent = self._get_param("retest_atr_percent", 0.2)
            stop_loss_mult = self._get_param("stop_loss_atr_multiplier", 1.5)
            atr = pair_info.get("atr")
            tick_size = pair_info.get("tick_size")

            if atr is None or tick_size is None or atr <= 0 or tick_size <= 0:
                raise ValueError("Missing/invalid ATR or TickSize.")
            base_sl_price = (
                round_price_by_tick(
                    trigger_price - atr * stop_loss_mult, tick_size, ROUND_DOWN
                )
                if direction == SignalDirection.LONG
                else round_price_by_tick(
                    trigger_price + atr * stop_loss_mult, tick_size, ROUND_UP
                )
            )
            if (
                base_sl_price is None
                or base_sl_price <= 0
                or (
                    direction == SignalDirection.LONG and base_sl_price >= trigger_price
                )
                or (
                    direction == SignalDirection.SHORT
                    and base_sl_price <= trigger_price
                )
            ):
                raise ValueError("Invalid base SL")
            entry_price: Optional[float] = None
            mode = OrderMode.MARKET
            comparison_price = trigger_price
            if retest_atr_percent > 0:
                pe_raw = (
                    trigger_price - atr * retest_atr_percent
                    if direction == SignalDirection.LONG
                    else trigger_price + atr * retest_atr_percent
                )
                pe = round_price_by_tick(
                    pe_raw,
                    tick_size,
                    ROUND_DOWN if direction == SignalDirection.LONG else ROUND_UP,
                )
                if pe is not None and (
                    (
                        direction == SignalDirection.LONG
                        and pe > base_sl_price
                        and pe < trigger_price
                    )
                    or (
                        direction == SignalDirection.SHORT
                        and pe < base_sl_price
                        and pe > trigger_price
                    )
                ):
                    entry_price = pe
                    mode = OrderMode.LIMIT_RETEST
                    comparison_price = entry_price
            ob_density_for_sl = (
                ob_analysis.nearest_support
                if direction == SignalDirection.LONG
                and isinstance(ob_analysis, OrderbookAnalysisResult)
                else (
                    ob_analysis.nearest_resistance
                    if direction == SignalDirection.SHORT
                    and isinstance(ob_analysis, OrderbookAnalysisResult)
                    else None
                )
            )
            adapted_sl = _adapt_sl_to_orderbook(
                base_sl_price,
                comparison_price,
                direction,
                ob_density_for_sl,
                atr,
                tick_size,
                log_prefix,
            )
            final_sl_price = adapted_sl if adapted_sl is not None else base_sl_price
            rr_conf_raw = self._get_param("partial_exit_rr_config", [])
            move_sl_be = self._get_param("move_sl_to_be_on_first_tp", True)
            final_tp_rr_param = self._get_param("final_tp_rr")
            tp_atr_mult = self._get_param("take_profit_atr_multiplier", 2.0)
            partials: Optional[List[PartialTarget]] = None
            final_tp: Optional[float] = None
            rr_conf_parsed = None
            if isinstance(rr_conf_raw, list) and all(
                isinstance(t, (list, tuple)) and len(t) == 2 for t in rr_conf_raw
            ):
                try:
                    rr_conf_parsed = [(float(r), float(f)) for r, f in rr_conf_raw]
                except Exception:
                    logger.warning(
                        f"{log_prefix} Invalid partial_exit_rr_config format."
                    )  # pragma: no cover
            if rr_conf_parsed:
                partials = self._calculate_partial_targets_from_rr(
                    comparison_price,
                    final_sl_price,
                    direction,
                    rr_conf_parsed,
                    tick_size,
                    atr_at_signal_time=atr,
                )
                if partials and isinstance(ob_analysis, OrderbookAnalysisResult):
                    adapted_partials = []
                    for pt_idx, pt in enumerate(partials):
                        ob_density_for_pt = (
                            ob_analysis.nearest_resistance
                            if direction == SignalDirection.LONG
                            else ob_analysis.nearest_support
                        )
                        adapted_pt_price = _adapt_tp_to_orderbook(
                            pt.price,
                            comparison_price,
                            direction,
                            ob_density_for_pt,
                            atr,
                            tick_size,
                            f"{log_prefix}[PT#{pt_idx + 1}]",
                            is_partial_tp=True,
                        )
                        adapted_partials.append(
                            PartialTarget(
                                price=(
                                    adapted_pt_price if adapted_pt_price else pt.price
                                ),
                                fraction=pt.fraction,
                            )
                        )
                    partials = adapted_partials

                    # NEW: Ensure adapted partial targets maintain strict order
                    if partials:
                        final_ordered_partials = []
                        last_price_for_order_check = None
                        for i, pt in enumerate(adapted_partials):
                            current_price = pt.price
                            if last_price_for_order_check is not None:
                                if direction == SignalDirection.LONG:
                                    # Ensure current price is strictly greater than last price
                                    if current_price <= last_price_for_order_check + (
                                        tick_size / 2
                                    ):  # Allow for minor rounding differences
                                        current_price = round_price_by_tick(
                                            last_price_for_order_check + tick_size,
                                            tick_size,
                                            ROUND_UP,
                                        )
                                        logger.warning(
                                            f"{log_prefix}[PT#{i + 1}] Adjusted adapted TP from {pt.price:.4f} to {current_price:.4f} to maintain strict LONG order."
                                        )
                                elif direction == SignalDirection.SHORT:
                                    # Ensure current price is strictly less than last price
                                    if current_price >= last_price_for_order_check - (
                                        tick_size / 2
                                    ):  # Allow for minor rounding differences
                                        current_price = round_price_by_tick(
                                            last_price_for_order_check - tick_size,
                                            tick_size,
                                            ROUND_DOWN,
                                        )
                                        logger.warning(
                                            f"{log_prefix}[PT#{i + 1}] Adjusted adapted TP from {pt.price:.4f} to {current_price:.4f} to maintain strict SHORT order."
                                        )

                            if (
                                current_price is None
                                or (
                                    direction == SignalDirection.LONG
                                    and current_price <= comparison_price
                                )
                                or (
                                    direction == SignalDirection.SHORT
                                    and current_price >= comparison_price
                                )
                            ):
                                logger.warning(
                                    f"{log_prefix}[PT#{i + 1}] Adapted TP {current_price:.4f} is invalid after re-ordering. Skipping this partial target."
                                )
                                continue  # Skip this partial target if it becomes invalid after adjustment

                            final_ordered_partials.append(
                                PartialTarget(price=current_price, fraction=pt.fraction)
                            )
                            last_price_for_order_check = current_price
                        partials = final_ordered_partials
            cumulative_partial_fraction = (
                sum(t.fraction for t in partials) if partials else 0.0
            )
            if cumulative_partial_fraction < (1.0 - 1e-9):
                final_tp_calc_raw = None
                risk_dist = abs(comparison_price - final_sl_price)
                if risk_dist <= 1e-9:
                    logger.warning(
                        f"{log_prefix} Zero risk for final TP calc."
                    )  # pragma: no cover
                elif final_tp_rr_param is not None and final_tp_rr_param > 0:
                    final_tp_calc_raw = (
                        comparison_price + risk_dist * final_tp_rr_param
                        if direction == SignalDirection.LONG
                        else comparison_price - risk_dist * final_tp_rr_param
                    )
                elif tp_atr_mult > 0:
                    final_tp_calc_raw = (
                        comparison_price + atr * tp_atr_mult
                        if direction == SignalDirection.LONG
                        else comparison_price - atr * tp_atr_mult
                    )
                if final_tp_calc_raw is not None:
                    min_tp_dist_pct = getattr(
                        config, "MIN_PARTIAL_TP_DISTANCE_PCT", 0.004
                    )
                    min_profit_abs_f = comparison_price * min_tp_dist_pct
                    tp_raw_min_pct_f = (
                        comparison_price + min_profit_abs_f
                        if direction == SignalDirection.LONG
                        else comparison_price - min_profit_abs_f
                    )
                    final_tp_adj_by_min = (
                        max(final_tp_calc_raw, tp_raw_min_pct_f)
                        if direction == SignalDirection.LONG
                        else min(final_tp_calc_raw, tp_raw_min_pct_f)
                    )
                    ob_density_for_final_tp = (
                        ob_analysis.nearest_resistance
                        if direction == SignalDirection.LONG
                        and isinstance(ob_analysis, OrderbookAnalysisResult)
                        else (
                            ob_analysis.nearest_support
                            if direction == SignalDirection.SHORT
                            and isinstance(ob_analysis, OrderbookAnalysisResult)
                            else None
                        )
                    )
                    adapted_final_tp = _adapt_tp_to_orderbook(
                        final_tp_adj_by_min,
                        comparison_price,
                        direction,
                        ob_density_for_final_tp,
                        atr,
                        tick_size,
                        log_prefix,
                        is_partial_tp=False,
                    )
                    final_tp_to_round = (
                        adapted_final_tp
                        if adapted_final_tp is not None
                        else final_tp_adj_by_min
                    )
                    rounding_f = (
                        ROUND_UP if direction == SignalDirection.LONG else ROUND_DOWN
                    )
                    final_tp = round_price_by_tick(
                        final_tp_to_round, tick_size, rounding_f
                    )
                if final_tp is None:
                    logger.error(
                        f"{log_prefix} Partials do not cover 100% ({cumulative_partial_fraction:.2f}) but could not determine a final TP. Signal cannot be created."
                    )
                    return None

                if (
                    direction == SignalDirection.LONG and final_tp <= comparison_price
                ) or (
                    direction == SignalDirection.SHORT and final_tp >= comparison_price
                ):
                    logger.error(
                        f"{log_prefix} Invalid final TP calculated ({final_tp:.8f}) relative to comparison price ({comparison_price:.8f}) for {direction.name} signal. Signal rejected."
                    )
                    return None

            else:  # Partials cover 100%
                final_tp = None  # Final TP is not needed

            # If there are no partial exits at all, and the final TP was not calculated
            if not partials and final_tp is None:
                logger.error(
                    f"{log_prefix} Signal REJECTED: No valid exit conditions (no partials and no final TP) could be determined."
                )
                return None

            risk_pct = self._get_param("risk_pct_per_trade")
            details = {
                "pattern": pattern_name,
                "trend": foundations.get("trend_detected", "N"),
                "atr": f"{atr:.8f}",
                "trig_raw": f"{trigger_price:.8f}",
                "entry_calc": f"{entry_price:.8f}" if entry_price else "MKT",
                "sl_calc": f"{final_sl_price:.8f}",
                "tp_final_calc": f"{final_tp:.8f}" if final_tp else "N",
                "partials_n": len(partials or []),
                "founds": {
                    k: (v if isinstance(v, bool) else str(v))
                    for k, v in foundations.items()
                    if not k.startswith("foundation_")
                },  # Removing our service keys
                "foundation_total_weight": foundations.get(
                    "foundation_total_weight"
                ),  # Add weight
                "foundation_met_details_log": foundations.get(
                    "foundation_met_details_log"
                ),  # Add log
            }
            return self._create_signal(
                symbol,
                direction,
                trigger_price,
                final_sl_price,
                final_tp,
                mode,
                entry_price,
                details,
                partials,
                move_sl_be,
                risk_pct=risk_pct,
            )
        except ValueError as ve:
            logger.error(f"{log_prefix} ValueError: {ve}")
            return None  # pragma: no cover
        except Exception as e:
            logger.error(f"{log_prefix} Unexpected error: {e}", exc_info=True)
            return None  # pragma: no cover


class FakeBreakoutStrategy(BaseStrategy):
    NAME = "FakeBreakout"
    description = "Searches for false breakouts of local levels followed by the price returning to the range."

    @property
    def required_data_types(self) -> Set[str]:
        tf = self._get_param("candle_timeframe", "1m")
        base_reqs = super().required_data_types
        strategy_reqs = {f"kline_{tf}", "aggTrade"}
        return base_reqs.union(strategy_reqs)

    def _check_pattern_fake_breakout(
        self,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        current_candle_idx: Optional[int],
    ) -> Tuple[Optional[str], Optional[float], Optional[float], Optional[float]]:
        symbol = pair_info.get("symbol")
        log_prefix = f"[{self.NAME}:{symbol}:PatternCheck]"
        try:
            candle_tf = self._get_param("candle_timeframe", "1m")
            lookback_candles = self._get_param("lookback_candles", 5)
            reversal_confirmation_bars = self._get_param(
                "reversal_confirmation_bars", 1
            )
        except Exception as e:
            logger.error(f"{log_prefix} Error getting params: {e}")
            return None, None, None, None  # pragma: no cover
        kline_key = f"kline_{candle_tf}"
        candles_df = market_data.get(kline_key)
        if (
            current_candle_idx is None
            or not isinstance(candles_df, pd.DataFrame)
            or candles_df.empty
        ):
            return None, None, None, None
        required_hist_len = lookback_candles + 1 + reversal_confirmation_bars
        if current_candle_idx < required_hist_len:
            return None, None, None, None
        try:
            confirmation_end_idx = (
                current_candle_idx + 1
            )  # The slice will be up to this index (exclusive)
            breakout_candle_idx = current_candle_idx - reversal_confirmation_bars
            lookback_end_idx = breakout_candle_idx
            lookback_start_idx = lookback_end_idx - lookback_candles
            if lookback_start_idx < 0 or breakout_candle_idx < 0:
                return None, None, None, None
            lookback_candles_data = candles_df.iloc[lookback_start_idx:lookback_end_idx]
            level_high = float(lookback_candles_data["high"].max())
            level_low = float(lookback_candles_data["low"].min())
            breakout_candle = candles_df.iloc[breakout_candle_idx]
            break_high = float(breakout_candle["high"])
            break_low = float(breakout_candle["low"])
            break_close = float(breakout_candle["close"])
            trigger_price_candidate = (
                break_close  # By default, if there are no confirmation_bars
            )
            reversal_candles_slice = None
            if reversal_confirmation_bars > 0:
                reversal_start_idx = breakout_candle_idx + 1
                reversal_end_idx = confirmation_end_idx
                if reversal_start_idx >= reversal_end_idx or reversal_end_idx > len(
                    candles_df
                ):
                    return None, None, None, None  # pragma: no cover
                reversal_candles_slice = candles_df.iloc[
                    reversal_start_idx:reversal_end_idx
                ]
                if (
                    reversal_candles_slice.empty
                    or reversal_candles_slice["close"].isnull().any()
                ):
                    return None, None, None, None  # pragma: no cover
                trigger_price_candidate = float(
                    reversal_candles_slice.iloc[-1]["close"]
                )
            if break_high > level_high:
                returned_below_level = (
                    (reversal_candles_slice["close"] < level_high).all()
                    if reversal_confirmation_bars > 0
                    and reversal_candles_slice is not None
                    else break_close < level_high
                )
                if returned_below_level:
                    return (
                        "FakeBreakUp",
                        level_high,
                        trigger_price_candidate,
                        break_high,
                    )
            elif break_low < level_low:
                returned_above_level = (
                    (reversal_candles_slice["close"] > level_low).all()
                    if reversal_confirmation_bars > 0
                    and reversal_candles_slice is not None
                    else break_close > level_low
                )
                if returned_above_level:
                    return (
                        "FakeBreakDown",
                        level_low,
                        trigger_price_candidate,
                        break_low,
                    )
        except (IndexError, KeyError, TypeError, ValueError) as e:
            logger.error(f"{log_prefix} Error checking pattern: {e}", exc_info=True)
            return None, None, None, None  # pragma: no cover
        return None, None, None, None

    def check_foundations(
        self, pair_info: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        # 1. Getting general bases
        foundations_status, trace_nodes = super().check_foundations(
            pair_info, market_data
        )

        # 2. Checking own pattern
        candle_tf_strat = self._get_param("candle_timeframe", "1m")
        kline_key_strat = f"kline_{candle_tf_strat}"
        candles_df_strat = market_data.get(kline_key_strat)

        current_candle_idx = None
        if isinstance(candles_df_strat, pd.DataFrame) and not candles_df_strat.empty:
            backtest_idx = pair_info.get("current_candle_index")
            current_candle_idx = (
                backtest_idx if backtest_idx is not None else len(candles_df_strat) - 1
            )

        # Check the pattern ONCE and save ALL results
        pattern_name, level_broken, trigger_price, extremum_price = (
            self._check_pattern_fake_breakout(
                pair_info, market_data, current_candle_idx
            )
        )

        # 3. Update status
        foundations_status[FOUNDATION_PATTERN] = pattern_name is not None
        foundations_status["pattern_detected"] = (
            pattern_name if pattern_name else "None"
        )

        # Save additional data for the next step
        if pattern_name:
            foundations_status["pattern_level_broken"] = level_broken
            foundations_status["pattern_trigger_price"] = trigger_price
            foundations_status["pattern_extremum_price"] = extremum_price

        trace_nodes.append(
            {
                "id": FOUNDATION_PATTERN,
                "type": "foundation",
                "result": (pattern_name is not None),
                "details": f"Pattern: {pattern_name}",
            }
        )

        if foundations_status[FOUNDATION_PATTERN]:
            foundations_status[FOUNDATION_LEVEL] = True

        return foundations_status, trace_nodes

    def _check_specific_signal_logic(
        self,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        foundations: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        symbol = pair_info.get("symbol")
        log_prefix = f"[{self.NAME}:{symbol}:SpecificLogic]"
        pattern_name = foundations.get("pattern_detected")
        # Getting data directly from foundations
        level_broken = foundations.get("pattern_level_broken")
        trigger_price_pattern = foundations.get("pattern_trigger_price")
        extremum_price = foundations.get("pattern_extremum_price")

        if (
            not pattern_name
            or pattern_name == "None"
            or level_broken is None
            or trigger_price_pattern is None
            or extremum_price is None
        ):
            return None

        direction = (
            SignalDirection.SHORT
            if "Up" in pattern_name
            else (SignalDirection.LONG if "Down" in pattern_name else None)
        )
        if direction is None:
            return None
        candle_tf_strat = self._get_param("candle_timeframe", "1m")
        kline_key_strat = f"kline_{candle_tf_strat}"
        candles_df_strat = market_data.get(kline_key_strat)
        current_candle_idx_strat: Optional[int] = None
        backtest_idx = pair_info.get("current_candle_index")
        if isinstance(candles_df_strat, pd.DataFrame) and not candles_df_strat.empty:
            current_candle_idx_strat = (
                backtest_idx if backtest_idx is not None else len(candles_df_strat) - 1
            )
        if current_candle_idx_strat is None:
            logger.warning(f"{log_prefix} Invalid index for specific logic.")
            return None
        _, level_broken, trigger_price_pattern, extremum_price = (
            self._check_pattern_fake_breakout(
                pair_info, market_data, current_candle_idx_strat
            )
        )
        if (
            level_broken is None
            or trigger_price_pattern is None
            or extremum_price is None
        ):
            logger.debug(f"{log_prefix} Pattern check incomplete vals.")
            return None
        direction = (
            SignalDirection.SHORT
            if "Up" in pattern_name
            else (SignalDirection.LONG if "Down" in pattern_name else None)
        )
        if direction is None:
            return None  # pragma: no cover
        if not foundations.get(FOUNDATION_VOLUME_CONFIRMATION, False):
            logger.debug(f"{log_prefix} Rejected: Vol not confirmed.")
            return None
        ob_analysis = foundations.get(FOUNDATION_ORDERBOOK)
        if isinstance(ob_analysis, OrderbookAnalysisResult):
            if (
                direction == SignalDirection.LONG
                and ob_analysis.is_price_near_resistance
            ):
                logger.info(
                    f"{log_prefix} LONG signal REJECTED by OB: Price near resistance."
                )
                return None
            if direction == SignalDirection.SHORT and ob_analysis.is_price_near_support:
                logger.info(
                    f"{log_prefix} SHORT signal REJECTED by OB: Price near support."
                )
                return None
        try:
            stop_loss_mult = self._get_param("stop_loss_atr_multiplier", 1.2)
            atr = pair_info.get("atr")
            tick_size = pair_info.get("tick_size")
            if atr is None or tick_size is None or atr <= 0 or tick_size <= 0:
                raise ValueError("Missing/invalid ATR or TickSize.")
            base_sl_price = (
                round_price_by_tick(
                    extremum_price + atr * stop_loss_mult, tick_size, ROUND_UP
                )
                if direction == SignalDirection.SHORT
                else round_price_by_tick(
                    extremum_price - atr * stop_loss_mult, tick_size, ROUND_DOWN
                )
            )
            if (
                base_sl_price is None
                or base_sl_price <= 0
                or (
                    direction == SignalDirection.SHORT
                    and base_sl_price <= trigger_price_pattern
                )
                or (
                    direction == SignalDirection.LONG
                    and base_sl_price >= trigger_price_pattern
                )
            ):
                raise ValueError("Invalid base SL")
            mode = OrderMode.MARKET
            entry_price = None
            comparison_price = trigger_price_pattern
            ob_density_for_sl = (
                ob_analysis.nearest_support
                if direction == SignalDirection.LONG
                and isinstance(ob_analysis, OrderbookAnalysisResult)
                else (
                    ob_analysis.nearest_resistance
                    if direction == SignalDirection.SHORT
                    and isinstance(ob_analysis, OrderbookAnalysisResult)
                    else None
                )
            )
            adapted_sl = _adapt_sl_to_orderbook(
                base_sl_price,
                comparison_price,
                direction,
                ob_density_for_sl,
                atr,
                tick_size,
                log_prefix,
            )
            final_sl_price = adapted_sl if adapted_sl is not None else base_sl_price
            rr_conf_raw = self._get_param("partial_exit_rr_config", [])
            move_sl_be = self._get_param("move_sl_to_be_on_first_tp", True)
            final_tp_rr_param = self._get_param("final_tp_rr")
            tp_atr_mult = self._get_param("take_profit_atr_multiplier", 1.5)
            partials: Optional[List[PartialTarget]] = None
            final_tp: Optional[float] = None
            rr_conf_parsed = None
            if isinstance(rr_conf_raw, list) and all(
                isinstance(t, (list, tuple)) and len(t) == 2 for t in rr_conf_raw
            ):
                try:
                    rr_conf_parsed = [(float(r), float(f)) for r, f in rr_conf_raw]
                except Exception:
                    logger.warning(
                        f"{log_prefix} Invalid partial_exit_rr_config format."
                    )  # pragma: no cover
            if rr_conf_parsed:
                partials = self._calculate_partial_targets_from_rr(
                    comparison_price,
                    final_sl_price,
                    direction,
                    rr_conf_parsed,
                    tick_size,
                    atr_at_signal_time=atr,
                )
                if partials and isinstance(ob_analysis, OrderbookAnalysisResult):
                    adapted_partials = []
                    for pt_idx, pt in enumerate(partials):
                        relevant_ob_for_pt = (
                            ob_analysis.nearest_resistance
                            if direction == SignalDirection.LONG
                            else ob_analysis.nearest_support
                        )
                        adapted_pt_price = _adapt_tp_to_orderbook(
                            pt.price,
                            comparison_price,
                            direction,
                            relevant_ob_for_pt,
                            atr,
                            tick_size,
                            f"{log_prefix}[PT#{pt_idx + 1}]",
                            is_partial_tp=True,
                        )
                        adapted_partials.append(
                            PartialTarget(
                                price=(
                                    adapted_pt_price if adapted_pt_price else pt.price
                                ),
                                fraction=pt.fraction,
                            )
                        )
                    partials = adapted_partials

                    if partials:
                        final_ordered_partials = []
                        last_price_for_order_check = None
                        for i_pt_reorder, pt_reorder in enumerate(partials):
                            current_price = pt_reorder.price

                            if current_price is None:
                                logger.warning(
                                    f"{log_prefix}[PT#{i_pt_reorder + 1}] Original adapted price is None. Skipping this partial target."
                                )
                                continue
                            if last_price_for_order_check is not None:
                                price_str = (
                                    f"{current_price:.8f}"
                                    if current_price is not None
                                    else "None"
                                )
                                if direction == SignalDirection.LONG:
                                    if current_price <= last_price_for_order_check + (
                                        tick_size / 2
                                    ):
                                        current_price = round_price_by_tick(
                                            last_price_for_order_check + tick_size,
                                            tick_size,
                                            ROUND_UP,
                                        )
                                        logger.warning(
                                            f"{log_prefix}[PT#{i_pt_reorder + 1}] Adjusted adapted TP from {pt_reorder.price:.8f} to {price_str} to maintain strict LONG order."
                                        )
                                elif direction == SignalDirection.SHORT:
                                    if current_price >= last_price_for_order_check - (
                                        tick_size / 2
                                    ):
                                        current_price = round_price_by_tick(
                                            last_price_for_order_check - tick_size,
                                            tick_size,
                                            ROUND_DOWN,
                                        )
                                        logger.warning(
                                            f"{log_prefix}[PT#{i_pt_reorder + 1}] Adjusted adapted TP from {pt_reorder.price:.8f} to {price_str} to maintain strict SHORT order."
                                        )
                            if (
                                current_price is None
                                or (
                                    direction == SignalDirection.LONG
                                    and current_price
                                    <= comparison_price + (tick_size / 2)
                                )
                                or (
                                    direction == SignalDirection.SHORT
                                    and current_price
                                    >= comparison_price - (tick_size / 2)
                                )
                            ):
                                price_str_invalid = (
                                    f"{current_price:.8f}"
                                    if current_price is not None
                                    else "None"
                                )
                                logger.warning(
                                    f"{log_prefix}[PT#{i_pt_reorder + 1}] Adapted TP {price_str_invalid} is invalid relative to entry {comparison_price:.8f} after re-ordering/adjustment. Skipping this partial target."
                                )
                                continue
                            try:
                                final_ordered_partials.append(
                                    PartialTarget(
                                        price=current_price,
                                        fraction=pt_reorder.fraction,
                                    )
                                )
                                last_price_for_order_check = current_price
                            except ValueError as e_pt_create:
                                logger.error(
                                    f"{log_prefix}[PT#{i_pt_reorder + 1}] Error creating PartialTarget after reorder (Price: {current_price}): {e_pt_create}"
                                )
                                continue

                        partials = (
                            final_ordered_partials if final_ordered_partials else None
                        )
            cumulative_partial_fraction = (
                sum(t.fraction for t in partials) if partials else 0.0
            )
            if cumulative_partial_fraction < (1.0 - 1e-9):
                final_tp_calc_raw = None
                risk_dist = abs(comparison_price - final_sl_price)
                if risk_dist <= 1e-9:
                    logger.warning(
                        f"{log_prefix} Zero risk for final TP calc."
                    )  # pragma: no cover
                elif final_tp_rr_param is not None and final_tp_rr_param > 0:
                    final_tp_calc_raw = (
                        comparison_price + risk_dist * final_tp_rr_param
                        if direction == SignalDirection.LONG
                        else comparison_price - risk_dist * final_tp_rr_param
                    )
                elif tp_atr_mult > 0:
                    final_tp_calc_raw = (
                        comparison_price + atr * tp_atr_mult
                        if direction == SignalDirection.LONG
                        else comparison_price - atr * tp_atr_mult
                    )
                if final_tp_calc_raw is not None:
                    min_tp_dist_pct = getattr(
                        config, "MIN_PARTIAL_TP_DISTANCE_PCT", 0.004
                    )
                    min_profit_abs_f = comparison_price * min_tp_dist_pct
                    tp_raw_min_pct_f = (
                        comparison_price + min_profit_abs_f
                        if direction == SignalDirection.LONG
                        else comparison_price - min_profit_abs_f
                    )
                    final_tp_adj_by_min = (
                        max(final_tp_calc_raw, tp_raw_min_pct_f)
                        if direction == SignalDirection.LONG
                        else min(final_tp_calc_raw, tp_raw_min_pct_f)
                    )
                    relevant_ob_for_final_tp = (
                        ob_analysis.nearest_resistance
                        if direction == SignalDirection.LONG
                        and isinstance(ob_analysis, OrderbookAnalysisResult)
                        else (
                            ob_analysis.nearest_support
                            if direction == SignalDirection.SHORT
                            and isinstance(ob_analysis, OrderbookAnalysisResult)
                            else None
                        )
                    )

                    adapted_final_tp = _adapt_tp_to_orderbook(
                        final_tp_adj_by_min,
                        comparison_price,
                        direction,
                        relevant_ob_for_final_tp,
                        atr,
                        tick_size,
                        log_prefix,
                        is_partial_tp=False,
                    )

                    final_tp_to_round = (
                        adapted_final_tp
                        if adapted_final_tp is not None
                        else final_tp_adj_by_min
                    )
                    rounding_f = (
                        ROUND_UP if direction == SignalDirection.LONG else ROUND_DOWN
                    )
                    final_tp = round_price_by_tick(
                        final_tp_to_round, tick_size, rounding_f
                    )
                if final_tp is None:
                    logger.error(
                        f"{log_prefix} Partials do not cover 100% ({cumulative_partial_fraction:.2f}) but could not determine a final TP. Signal cannot be created."
                    )
                    return None
            else:  # Partials cover 100%
                final_tp = None  # Final TP is not needed
                logger.debug(
                    f"{log_prefix} Partials cover 100% ({cumulative_partial_fraction:.2f}). Final TP set to None."
                )
            risk_pct = self._get_param("risk_pct_per_trade")
            atr_for_details = pair_info.get("atr")
            details = {
                "pattern": pattern_name,
                "trend": foundations.get("trend_detected", "N"),
                "lvl_broken": format_float_detail(level_broken),
                "break_extr": format_float_detail(extremum_price),
                "atr": format_float_detail(atr_for_details),
                "trig_raw": format_float_detail(trigger_price_pattern),
                "sl_calc": format_float_detail(final_sl_price),
                "tp_final_calc": format_float_detail(final_tp),
                "partials_n": len(partials or []),
                "founds": {
                    k: (v if isinstance(v, bool) else str(v))
                    for k, v in foundations.items()
                    if not k.startswith("foundation_")
                },
                "foundation_total_weight": foundations.get("foundation_total_weight"),
                "foundation_met_details_log": foundations.get(
                    "foundation_met_details_log"
                ),
            }
            return self._create_signal(
                symbol,
                direction,
                trigger_price_pattern,
                final_sl_price,
                final_tp,
                mode,
                entry_price,
                details,
                partials,
                move_sl_be,
                risk_pct=risk_pct,
            )
        except ValueError as ve:
            logger.error(f"{log_prefix} ValueError: {ve}")
            return None  # pragma: no cover
        except Exception as e:
            logger.error(f"{log_prefix} Unexpected error: {e}", exc_info=True)
            return None  # pragma: no cover


class DensityBounceStrategy(BaseStrategy):
    NAME = "DensityBounce"
    description = "Searches for bounces from significant density levels in the order book using market depth data."
    touch_tracker: Dict[str, Dict[float, Tuple[int, float]]] = defaultdict(dict)
    touch_reset_interval: int = 300

    @property
    def required_data_types(self) -> Set[str]:
        base_reqs = super().required_data_types
        strategy_reqs = {"depth"}
        return base_reqs.union(strategy_reqs)

    def _check_pattern_density_bounce(
        self, pair_info: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Tuple[Optional[str], Optional[float], Dict[str, Any]]:
        symbol = pair_info.get("symbol")
        log_prefix = f"[{self.NAME}:{symbol}:PatternCheck]"
        if not self._validate_pair_info(
            pair_info, ["symbol", "tick_size", "last_price"]
        ):
            return None, None, {}  # pragma: no cover

        # Use depth_trading, with a fallback to depth for safety during transition
        depth_to_use = market_data.get("depth_trading")
        if depth_to_use is None:
            depth_to_use = market_data.get("depth")
            if depth_to_use is not None:
                logger.warning(
                    f"{log_prefix} Using 'depth' as fallback, 'depth_trading' not found."
                )

        if (
            not isinstance(depth_to_use, dict)
            or not depth_to_use.get("bids")
            or not depth_to_use.get("asks")
        ):
            logger.warning(
                f"{log_prefix} Invalid or missing depth data ('depth_trading' or 'depth')."
            )
            return None, None, {}

        try:
            min_density_size_usd = self._get_param("min_density_size_usd", 100000)
            depth_levels_to_check = self._get_param("depth_levels_to_check", 10)
        except Exception as e:
            logger.error(f"{log_prefix} Error getting params: {e}")
            return None, None, {}  # pragma: no cover

        current_price = pair_info["last_price"]
        tick_size = pair_info["tick_size"]
        if tick_size is None or tick_size <= 0:
            logger.error(f"{log_prefix} Invalid or missing tick_size: {tick_size}")
            return None, None, {}  # pragma: no cover

        for side, levels_data_key in [("BID", "bids"), ("ASK", "asks")]:
            levels = depth_to_use.get(levels_data_key, [])
            for i in range(min(len(levels), depth_levels_to_check)):
                try:
                    price_str, size_str = levels[i]
                    price_f, size_f = float(price_str), float(size_str)
                    if price_f * size_f >= min_density_size_usd:
                        touch_allowance_ticks = getattr(
                            config, "DENSITY_NEAR_PROXIMITY_TICKS", 3
                        )
                        lower_bound = price_f - (
                            touch_allowance_ticks * tick_size if side == "ASK" else 0
                        )
                        upper_bound = price_f + (
                            touch_allowance_ticks * tick_size if side == "BID" else 0
                        )
                        if lower_bound <= current_price <= upper_bound:
                            pattern_details = {
                                "density_price": price_f,
                                "density_size_usd": price_f * size_f,
                                "density_side": side,
                            }
                            logger.debug(
                                f"{log_prefix} Touching significant {side} density at {price_f:.4f}"
                            )
                            return (
                                f"DensityBounce{'Long' if side == 'BID' else 'Short'}",
                                price_f,
                                pattern_details,
                            )
                except (IndexError, ValueError, TypeError) as e:
                    logger.warning(
                        f"{log_prefix} Error processing {side} level {i}: {e}"
                    )  # pragma: no cover
        return None, None, {}

    def check_foundations(
        self, pair_info: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        symbol = pair_info.get("symbol", self.NAME)
        log_prefix = f"[{symbol}:{self.NAME}:Foundations]"
        foundations_status, trace_nodes = super().check_foundations(
            pair_info, market_data
        )
        try:
            pattern_name, density_price_val, pattern_details = (
                self._check_pattern_density_bounce(pair_info, market_data)
            )
            foundations_status[FOUNDATION_PATTERN] = pattern_name is not None
            foundations_status["pattern_detected"] = (
                pattern_name if pattern_name else "None"
            )
            if pattern_name:
                foundations_status.update(pattern_details)
            if (
                foundations_status[FOUNDATION_PATTERN]
                and not foundations_status[FOUNDATION_LEVEL]
            ):
                foundations_status[FOUNDATION_LEVEL] = True
            ob_analysis_from_super: OrderbookAnalysisResult = foundations_status.get(
                FOUNDATION_ORDERBOOK, OrderbookAnalysisResult()
            )
            density_side_pattern = pattern_details.get("density_side")
            update_general_ob = False
            last_px_for_dist = pair_info.get("last_price", 0.0)  # Use 0.0 as fallback
            if density_side_pattern == "BID":
                if ob_analysis_from_super.nearest_support is None or (
                    density_price_val is not None
                    and abs(density_price_val - last_px_for_dist)
                    < ob_analysis_from_super.nearest_support.distance_from_current_price_abs
                ):
                    update_general_ob = True
            elif density_side_pattern == "ASK":
                if ob_analysis_from_super.nearest_resistance is None or (
                    density_price_val is not None
                    and abs(density_price_val - last_px_for_dist)
                    < ob_analysis_from_super.nearest_resistance.distance_from_current_price_abs
                ):
                    update_general_ob = True
            if update_general_ob and density_price_val is not None:
                current_atr_val = pair_info.get("atr")
                dist_abs = abs(last_px_for_dist - density_price_val)
                dist_atr = (
                    (dist_abs / current_atr_val)
                    if current_atr_val and current_atr_val > 0
                    else None
                )
                density_info_for_general = DensityInfo(
                    price=density_price_val,
                    size_usd=pattern_details.get("density_size_usd", 0),
                    distance_from_current_price_abs=dist_abs,
                    distance_from_current_price_atr=dist_atr,
                    side=density_side_pattern.lower(),
                )
                current_tick_size = pair_info.get("tick_size", DEFAULT_TICK_SIZE)
                if density_side_pattern == "BID":
                    ob_analysis_from_super.nearest_support = density_info_for_general
                    if (
                        dist_abs
                        <= getattr(config, "DENSITY_NEAR_PROXIMITY_TICKS", 3)
                        * current_tick_size
                    ):
                        ob_analysis_from_super.is_price_near_support = True
                elif density_side_pattern == "ASK":
                    ob_analysis_from_super.nearest_resistance = density_info_for_general
                    if (
                        dist_abs
                        <= getattr(config, "DENSITY_NEAR_PROXIMITY_TICKS", 3)
                        * current_tick_size
                    ):
                        ob_analysis_from_super.is_price_near_resistance = True
                foundations_status[FOUNDATION_ORDERBOOK] = (
                    ob_analysis_from_super  # Update the main foundations status
                )
                logger.debug(
                    f"{log_prefix} Updated general FOUNDATION_ORDERBOOK based on DensityBounce pattern."
                )
        except Exception as e:
            logger.error(
                f"{log_prefix} Error in specific foundation checks: {e}", exc_info=True
            )  # pragma: no cover
        return foundations_status, trace_nodes

    def _check_specific_signal_logic(
        self,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        foundations: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        symbol = pair_info.get("symbol")
        log_prefix = f"[{self.NAME}:{symbol}:SpecificLogic]"
        pattern_name = foundations.get("pattern_detected")
        density_price_pattern = foundations.get("density_price")
        pattern_name = foundations.get("pattern_detected")
        if not pattern_name or pattern_name == "None" or density_price_pattern is None:
            return None
        direction = (
            SignalDirection.LONG if "Long" in pattern_name else SignalDirection.SHORT
        )
        ob_analysis = foundations.get(FOUNDATION_ORDERBOOK)
        tick_size_local = pair_info.get("tick_size")
        if tick_size_local is None or tick_size_local <= 0:
            logger.error(
                f"{log_prefix} Invalid tick_size ({tick_size_local}) for DensityBounce OB check."
            )
            return None  # pragma: no cover
        if isinstance(ob_analysis, OrderbookAnalysisResult):
            if (
                direction == SignalDirection.LONG
                and ob_analysis.is_price_near_resistance
                and ob_analysis.nearest_resistance
                and abs(ob_analysis.nearest_resistance.price - density_price_pattern)
                > tick_size_local * 2
            ):
                logger.info(
                    f"{log_prefix} LONG signal REJECTED: general OB shows near resistance at {ob_analysis.nearest_resistance.price:.4f}, conflicting with bounce from {density_price_pattern:.4f}"
                )
                return None
            if (
                direction == SignalDirection.SHORT
                and ob_analysis.is_price_near_support
                and ob_analysis.nearest_support
                and abs(ob_analysis.nearest_support.price - density_price_pattern)
                > tick_size_local * 2
            ):
                logger.info(
                    f"{log_prefix} SHORT signal REJECTED: general OB shows near support at {ob_analysis.nearest_support.price:.4f}, conflicting with bounce from {density_price_pattern:.4f}"
                )
                return None
        max_touch_param = self._get_param("max_touch_count", 3)
        now = time.time()
        self.touch_tracker[symbol] = {
            p: (c, ts)
            for p, (c, ts) in self.touch_tracker[symbol].items()
            if now - ts < self.touch_reset_interval
        }
        current_touches, _ = self.touch_tracker[symbol].get(
            density_price_pattern, (0, 0)
        )
        if current_touches >= max_touch_param:
            logger.debug(
                f"{log_prefix} Density at {density_price_pattern:.4f} touched {current_touches} times. Skip."
            )
            return None
        self.touch_tracker[symbol][density_price_pattern] = (current_touches + 1, now)
        try:
            sl_ticks_mult = self._get_param("sl_ticks_multiplier", 5)
            atr_val = pair_info.get("atr")
            atr_val = pair_info.get("atr")
            rr_conf_raw = self._get_param("partial_exit_rr_config", [])
            move_sl_be = self._get_param("move_sl_to_be_on_first_tp", True)
            final_tp_rr = self._get_param("final_tp_rr")
            tp_ticks_mult = self._get_param("tp_ticks_multiplier", 10)
            if tp_ticks_mult <= 0:
                raise ValueError(
                    f"Invalid tp_ticks_multiplier: {tp_ticks_mult}"
                )  # pragma: no cover
        except Exception as e:
            logger.error(f"{log_prefix} Error getting params/data: {e}")
            return None  # pragma: no cover
        entry_p_raw = (
            density_price_pattern + tick_size_local
            if direction == SignalDirection.LONG
            else density_price_pattern - tick_size_local
        )
        entry_p = round_price_by_tick(
            entry_p_raw,
            tick_size_local,
            ROUND_DOWN if direction == SignalDirection.LONG else ROUND_UP,
        )
        if entry_p is None:
            logger.error(f"{log_prefix} Failed to calc entry price.")
            return None  # pragma: no cover
        mode = OrderMode.LIMIT_RETEST
        trigger_p = density_price_pattern
        comparison_p = entry_p
        sl_p_raw = (
            density_price_pattern - sl_ticks_mult * tick_size_local
            if direction == SignalDirection.LONG
            else density_price_pattern + sl_ticks_mult * tick_size_local
        )
        sl_p = round_price_by_tick(
            sl_p_raw,
            tick_size_local,
            ROUND_DOWN if direction == SignalDirection.LONG else ROUND_UP,
        )
        final_sl_price = sl_p
        if (
            final_sl_price is None
            or final_sl_price <= 0
            or (direction == SignalDirection.LONG and final_sl_price >= entry_p)
            or (direction == SignalDirection.SHORT and final_sl_price <= entry_p)
        ):
            logger.error(
                f"{log_prefix} Invalid SL ({final_sl_price}) vs entry ({entry_p})."
            )
            return None  # pragma: no cover
        partials: Optional[List[PartialTarget]] = None
        final_tp: Optional[float] = None
        rr_conf_parsed = None
        if isinstance(rr_conf_raw, list) and all(
            isinstance(t, (list, tuple)) and len(t) == 2 for t in rr_conf_raw
        ):
            try:
                rr_conf_parsed = [(float(r), float(f)) for r, f in rr_conf_raw]
            except Exception:
                logger.warning(
                    f"{log_prefix} Invalid partial_exit_rr_config format."
                )  # pragma: no cover
        if rr_conf_parsed:
            partials = self._calculate_partial_targets_from_rr(
                comparison_p,
                final_sl_price,
                direction,
                rr_conf_parsed,
                tick_size_local,
                atr_at_signal_time=atr_val,
            )
            if partials and isinstance(ob_analysis, OrderbookAnalysisResult):
                adapted_partials = []
                for pt_idx, pt in enumerate(partials):
                    relevant_ob_for_pt = (
                        ob_analysis.nearest_resistance
                        if direction == SignalDirection.LONG
                        else ob_analysis.nearest_support
                    )
                    current_atr_for_adapt = atr_val if atr_val and atr_val > 0 else 0.0
                    adapted_pt_price = _adapt_tp_to_orderbook(
                        pt.price,
                        comparison_p,
                        direction,
                        relevant_ob_for_pt,
                        current_atr_for_adapt,
                        tick_size_local,
                        f"{log_prefix}[PT#{pt_idx + 1}]",
                        is_partial_tp=True,
                    )
                    adapted_partials.append(
                        PartialTarget(
                            price=(adapted_pt_price if adapted_pt_price else pt.price),
                            fraction=pt.fraction,
                        )
                    )
                partials = adapted_partials
        cumulative_partial_fraction = (
            sum(t.fraction for t in partials) if partials else 0.0
        )
        if cumulative_partial_fraction < (1.0 - 1e-9):
            final_tp_calc_raw = None
            risk_dist = abs(comparison_p - final_sl_price)
            if final_tp_rr is not None and final_tp_rr > 0:
                if risk_dist > 1e-9:
                    final_tp_calc_raw = (
                        comparison_p + risk_dist * final_tp_rr
                        if direction == SignalDirection.LONG
                        else comparison_p - risk_dist * final_tp_rr
                    )
            else:
                final_tp_calc_raw = (
                    density_price_pattern + tp_ticks_mult * tick_size_local
                    if direction == SignalDirection.LONG
                    else density_price_pattern - tp_ticks_mult * tick_size_local
                )
            if final_tp_calc_raw is not None:
                min_tp_dist_pct = getattr(config, "MIN_PARTIAL_TP_DISTANCE_PCT", 0.004)
                min_profit_abs_f = comparison_p * min_tp_dist_pct
                tp_raw_min_pct_f = (
                    comparison_p + min_profit_abs_f
                    if direction == SignalDirection.LONG
                    else comparison_p - min_profit_abs_f
                )
                final_tp_adj_by_min = (
                    max(final_tp_calc_raw, tp_raw_min_pct_f)
                    if direction == SignalDirection.LONG
                    else min(final_tp_calc_raw, tp_raw_min_pct_f)
                )
                relevant_ob_for_final_tp = (
                    ob_analysis.nearest_resistance
                    if direction == SignalDirection.LONG
                    and isinstance(ob_analysis, OrderbookAnalysisResult)
                    else (
                        ob_analysis.nearest_support
                        if direction == SignalDirection.SHORT
                        and isinstance(ob_analysis, OrderbookAnalysisResult)
                        else None
                    )
                )
                current_atr_for_adapt = atr_val if atr_val and atr_val > 0 else 0.0
                adapted_final_tp = _adapt_tp_to_orderbook(
                    final_tp_adj_by_min,
                    comparison_p,
                    direction,
                    relevant_ob_for_final_tp,
                    current_atr_for_adapt,
                    tick_size_local,
                    log_prefix,
                    is_partial_tp=False,
                )
                final_tp_to_round = (
                    adapted_final_tp
                    if adapted_final_tp is not None
                    else final_tp_adj_by_min
                )
                rounding_f = (
                    ROUND_UP if direction == SignalDirection.LONG else ROUND_DOWN
                )
                final_tp = round_price_by_tick(
                    final_tp_to_round, tick_size_local, rounding_f
                )
            if final_tp is None:
                logger.error(
                    f"{log_prefix} Partials do not cover 100% ({cumulative_partial_fraction:.2f}) but could not determine a final TP. Signal cannot be created."
                )
                return None
        else:  # Partials cover 100%
            final_tp = None  # Final TP is not needed
            logger.debug(
                f"{log_prefix} Partials cover 100% ({cumulative_partial_fraction:.2f}). Final TP set to None."
            )
        risk_pct = self._get_param("risk_pct_per_trade")
        density_details = {
            k: v for k, v in foundations.items() if k.startswith("density_")
        }
        details = {
            **density_details,
            "pattern": pattern_name,
            "trend": foundations.get("trend_detected", "N"),
            "atr": f"{atr_val:.8f}" if atr_val else "N/A",
            "trig_raw": f"{trigger_p:.8f}",
            "entry_calc": f"{entry_p:.8f}",
            "sl_calc": f"{final_sl_price:.8f}",
            "tp_final_calc": f"{final_tp:.8f}" if final_tp else "N",
            "partials_n": len(partials or []),
            "founds": {
                k: (v if isinstance(v, bool) else str(v))
                for k, v in foundations.items()
            },
        }
        return self._create_signal(
            symbol,
            direction,
            trigger_p,
            final_sl_price,
            final_tp,
            mode,
            entry_p,
            details,
            partials,
            move_sl_be,
            risk_pct=risk_pct,
        )


class ConsolidationImpulseStrategy(BaseStrategy):
    NAME = "ConsolidationImpulse"
    description = (
        "Searches for impulse candles after consolidation, using ATR for filtering."
    )

    @property
    def required_data_types(self) -> Set[str]:
        tf = self._get_param("candle_timeframe", "1m")
        base_reqs = super().required_data_types
        strategy_reqs = {f"kline_{tf}", "aggTrade"}
        return base_reqs.union(strategy_reqs)

    def _check_pattern_consolidation_impulse(
        self,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        current_candle_idx: Optional[int],
    ) -> Tuple[
        Optional[str],
        Optional[float],
        Optional[float],
        Optional[float],
        Optional[float],
    ]:
        symbol = pair_info.get("symbol")
        log_prefix = f"[{self.NAME}:{symbol}:PatternCheck]"
        try:
            candle_tf = self._get_param("candle_timeframe", "1m")
            range_bars = self._get_param("range_bars", 15)
            max_range_atr_mult = self._get_param("max_range_atr_multiplier", 0.8)
            min_body_atr_mult = self._get_param("impulse_candle_min_body_atr", 0.5)
            entry_delay_bars = self._get_param("entry_delay_bars", 0)
            impulse_vol_mult = self._get_param("impulse_volume_multiplier", 2.0)
            atr = pair_info.get("atr")
        except Exception as e:
            logger.error(f"{log_prefix} Error getting params/ATR: {e}")
            return None, None, None, None, None  # pragma: no cover
        if atr is None or atr <= 0:
            logger.warning(f"{log_prefix} Missing/invalid ATR: {atr}")
            return None, None, None, None, None
        kline_key = f"kline_{candle_tf}"
        candles_df = market_data.get(kline_key)
        if (
            current_candle_idx is None
            or not isinstance(candles_df, pd.DataFrame)
            or candles_df.empty
        ):
            return None, None, None, None, None
        required_hist_len = range_bars + 1 + entry_delay_bars
        if current_candle_idx < required_hist_len:
            return None, None, None, None, None
        try:
            trigger_candle_idx = current_candle_idx
            impulse_candle_idx = trigger_candle_idx - entry_delay_bars

            # Correct slice: range_end_idx must be equal to impulse_candle_idx,
            # so that it does NOT include the impulse candle in the range calculation.
            range_end_idx = impulse_candle_idx
            range_start_idx = range_end_idx - range_bars

            if range_start_idx < 0 or impulse_candle_idx < 0 or trigger_candle_idx < 0:
                return None, None, None, None, None  # pragma: no cover
            range_candles = candles_df.iloc[range_start_idx:range_end_idx]
            consolidation_high = float(range_candles["high"].max())
            consolidation_low = float(range_candles["low"].min())
            avg_range_volume = float(range_candles["volume"].mean())
            consolidation_range = consolidation_high - consolidation_low
            if consolidation_range > atr * max_range_atr_mult:
                return None, None, None, None, None
            impulse_candle = candles_df.iloc[impulse_candle_idx]
            imp_open = float(impulse_candle["open"])
            imp_close = float(impulse_candle["close"])
            imp_volume = float(impulse_candle["volume"])
            imp_high = float(impulse_candle["high"])
            imp_low = float(impulse_candle["low"])
            if imp_volume < (
                avg_range_volume * impulse_vol_mult if avg_range_volume > 1e-9 else 0.0
            ):
                return None, None, None, None, None
            if abs(imp_close - imp_open) < atr * min_body_atr_mult:
                return None, None, None, None, None
            trigger_price = float(candles_df.iloc[trigger_candle_idx]["close"])
            if imp_close > consolidation_high and imp_high > consolidation_high:
                return (
                    "ConsImpulseUp",
                    consolidation_high,
                    consolidation_low,
                    trigger_price,
                    atr,
                )
            elif imp_close < consolidation_low and imp_low < consolidation_low:
                return (
                    "ConsImpulseDown",
                    consolidation_high,
                    consolidation_low,
                    trigger_price,
                    atr,
                )
        except (IndexError, KeyError, TypeError, ValueError) as e:
            logger.error(f"{log_prefix} Error checking pattern: {e}", exc_info=True)
            return None, None, None, None, None  # pragma: no cover
        return None, None, None, None, None

    def check_foundations(
        self, pair_info: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        # 1. Getting general bases
        foundations_status, trace_nodes = super().check_foundations(
            pair_info, market_data
        )

        # 2. Checking own pattern
        candle_tf_strat = self._get_param("candle_timeframe", "1m")
        kline_key_strat = f"kline_{candle_tf_strat}"
        candles_df_strat = market_data.get(kline_key_strat)

        current_candle_idx = None
        if isinstance(candles_df_strat, pd.DataFrame) and not candles_df_strat.empty:
            backtest_idx = pair_info.get("current_candle_index")
            current_candle_idx = (
                backtest_idx if backtest_idx is not None else len(candles_df_strat) - 1
            )

        pattern_name, cons_high, cons_low, trig_p, atr_check = (
            self._check_pattern_consolidation_impulse(
                pair_info, market_data, current_candle_idx
            )
        )

        # 3. Update status
        foundations_status[FOUNDATION_PATTERN] = pattern_name is not None
        foundations_status["pattern_detected"] = (
            pattern_name if pattern_name else "None"
        )
        if pattern_name:
            foundations_status["pattern_cons_high"] = cons_high
            foundations_status["pattern_cons_low"] = cons_low
            foundations_status["pattern_trigger_price"] = trig_p
            foundations_status["pattern_atr_at_check"] = atr_check

        trace_nodes.append(
            {
                "id": FOUNDATION_PATTERN,
                "type": "foundation",
                "result": (pattern_name is not None),
                "details": f"Pattern: {pattern_name}",
            }
        )

        if foundations_status[FOUNDATION_PATTERN]:
            foundations_status[FOUNDATION_LEVEL] = True

        return foundations_status, trace_nodes

    def _check_specific_signal_logic(
        self,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        foundations: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        symbol = pair_info.get("symbol")
        log_prefix = f"[{self.NAME}:{symbol}:SpecificLogic]"
        pattern_name = foundations.get("pattern_detected")
        cons_high = foundations.get("pattern_cons_high")
        cons_low = foundations.get("pattern_cons_low")
        trig_p_pattern = foundations.get("pattern_trigger_price")
        atr_at_check = foundations.get("pattern_atr_at_check")

        if (
            not pattern_name
            or pattern_name == "None"
            or cons_high is None
            or cons_low is None
            or trig_p_pattern is None
            or atr_at_check is None
            or atr_at_check <= 0
        ):
            return None

        direction = (
            SignalDirection.LONG
            if "Up" in pattern_name
            else (SignalDirection.SHORT if "Down" in pattern_name else None)
        )
        if direction is None:
            return None

        candle_tf_strat = self._get_param("candle_timeframe", "1m")
        kline_key_strat = f"kline_{candle_tf_strat}"
        candles_df_strat = market_data.get(kline_key_strat)
        current_candle_idx_strat: Optional[int] = None
        backtest_idx = pair_info.get("current_candle_index")
        if isinstance(candles_df_strat, pd.DataFrame) and not candles_df_strat.empty:
            current_candle_idx_strat = (
                backtest_idx if backtest_idx is not None else len(candles_df_strat) - 1
            )

        logger.debug(
            f"{log_prefix} current_candle_idx_strat: {current_candle_idx_strat}"
        )  # DEBUG

        if current_candle_idx_strat is None:
            logger.warning(f"{log_prefix} Invalid index for specific logic.")
            return None

        _, cons_high, cons_low, trig_p_pattern, atr_at_check = (
            self._check_pattern_consolidation_impulse(
                pair_info, market_data, current_candle_idx_strat
            )
        )

        logger.debug(
            f"{log_prefix} Pattern check results: cons_high={cons_high}, cons_low={cons_low}, trig_p_pattern={trig_p_pattern}, atr_at_check={atr_at_check}"
        )  # DEBUG

        if (
            cons_high is None
            or cons_low is None
            or trig_p_pattern is None
            or atr_at_check is None
            or atr_at_check <= 0
        ):
            logger.debug(f"{log_prefix} Pattern check incomplete vals. Returning None.")
            return None

        direction = (
            SignalDirection.LONG
            if "Up" in pattern_name
            else (SignalDirection.SHORT if "Down" in pattern_name else None)
        )
        logger.debug(f"{log_prefix} Determined direction: {direction}")  # DEBUG
        if direction is None:
            return None

        if not foundations.get(FOUNDATION_VOLUME_CONFIRMATION, False):
            logger.debug(f"{log_prefix} Rejected: Vol not confirmed.")
            return None

        ob_analysis = foundations.get(FOUNDATION_ORDERBOOK)
        if isinstance(ob_analysis, OrderbookAnalysisResult):
            if (
                direction == SignalDirection.LONG
                and ob_analysis.is_price_near_resistance
            ):
                logger.info(
                    f"{log_prefix} LONG signal REJECTED by OB: Price near resistance."
                )
                return None
            if direction == SignalDirection.SHORT and ob_analysis.is_price_near_support:
                logger.info(
                    f"{log_prefix} SHORT signal REJECTED by OB: Price near support."
                )
                return None

        try:
            atr = pair_info.get("atr")
            if atr is None or atr <= 0:
                raise ValueError(
                    "Missing or invalid ATR in pair_info for partials calculation"
                )

            tick_size = pair_info.get("tick_size")
            if tick_size is None or tick_size <= 0:
                raise ValueError("Missing/invalid TickSize.")
            sl_buffer_atr_mult = self._get_param("stop_loss_atr_multiplier", 0.1)

            logger.debug(
                f"{log_prefix} Params for SL: cons_low={cons_low}, cons_high={cons_high}, atr_at_check={atr_at_check}, sl_buffer_atr_mult={sl_buffer_atr_mult}, tick_size={tick_size}"
            )  # DEBUG

            base_sl_price = (
                round_price_by_tick(
                    cons_low - atr_at_check * sl_buffer_atr_mult, tick_size, ROUND_DOWN
                )
                if direction == SignalDirection.LONG
                else round_price_by_tick(
                    cons_high + atr_at_check * sl_buffer_atr_mult, tick_size, ROUND_UP
                )
            )

            logger.debug(
                f"{log_prefix} Calculated base_sl_price: {base_sl_price}"
            )  # DEBUG

            if (
                base_sl_price is None
                or base_sl_price <= 0
                or (
                    direction == SignalDirection.LONG
                    and base_sl_price >= trig_p_pattern
                )
                or (
                    direction == SignalDirection.SHORT
                    and base_sl_price <= trig_p_pattern
                )
            ):
                logger.error(
                    f"{log_prefix} Invalid base SL: base_sl_price={base_sl_price}, trig_p_pattern={trig_p_pattern}, direction={direction}"
                )  # DEBUG
                raise ValueError("Invalid base SL")

            mode = OrderMode.MARKET
            entry_p = None
            comparison_p = trig_p_pattern
            ob_density_for_sl = (
                ob_analysis.nearest_support
                if direction == SignalDirection.LONG
                and isinstance(ob_analysis, OrderbookAnalysisResult)
                else (
                    ob_analysis.nearest_resistance
                    if direction == SignalDirection.SHORT
                    and isinstance(ob_analysis, OrderbookAnalysisResult)
                    else None
                )
            )
            adapted_sl = _adapt_sl_to_orderbook(
                base_sl_price,
                comparison_p,
                direction,
                ob_density_for_sl,
                atr_at_check,
                tick_size,
                log_prefix,
            )
            final_sl_price = adapted_sl if adapted_sl is not None else base_sl_price

            logger.debug(f"{log_prefix} Final SL price: {final_sl_price}")  # DEBUG
            rr_conf_raw = self._get_param("partial_exit_rr_config", [])
            move_sl_be = self._get_param("move_sl_to_be_on_first_tp", True)
            final_tp_rr_param = self._get_param("final_tp_rr")
            tp_atr_mult = self._get_param("take_profit_atr_multiplier", 2.3)
            partials: Optional[List[PartialTarget]] = None
            final_tp: Optional[float] = None
            rr_conf_parsed = None
            if isinstance(rr_conf_raw, list) and all(
                isinstance(t, (list, tuple)) and len(t) == 2 for t in rr_conf_raw
            ):
                try:
                    rr_conf_parsed = [(float(r), float(f)) for r, f in rr_conf_raw]
                except Exception:
                    logger.warning(
                        f"{log_prefix} Invalid partial_exit_rr_config format."
                    )  # pragma: no cover
            if rr_conf_parsed:
                partials = self._calculate_partial_targets_from_rr(
                    comparison_p,
                    final_sl_price,
                    direction,
                    rr_conf_parsed,
                    tick_size,
                    atr_at_signal_time=atr,
                )
                if partials and isinstance(ob_analysis, OrderbookAnalysisResult):
                    adapted_partials = []
                    for pt_idx, pt in enumerate(partials):
                        relevant_ob_for_pt = (
                            ob_analysis.nearest_resistance
                            if direction == SignalDirection.LONG
                            else ob_analysis.nearest_support
                        )
                        adapted_pt_price = _adapt_tp_to_orderbook(
                            pt.price,
                            comparison_p,
                            direction,
                            relevant_ob_for_pt,
                            atr_at_check,
                            tick_size,
                            f"{log_prefix}[PT#{pt_idx + 1}]",
                            is_partial_tp=True,
                        )
                        adapted_partials.append(
                            PartialTarget(
                                price=(
                                    adapted_pt_price if adapted_pt_price else pt.price
                                ),
                                fraction=pt.fraction,
                            )
                        )
                    partials = adapted_partials
            cumulative_partial_fraction = (
                sum(t.fraction for t in partials) if partials else 0.0
            )
            if cumulative_partial_fraction < (1.0 - 1e-9):
                final_tp_calc_raw = None
                risk_dist = abs(comparison_p - final_sl_price)
                if risk_dist <= 1e-9:
                    logger.warning(
                        f"{log_prefix} Zero risk for final TP calc."
                    )  # pragma: no cover
                elif final_tp_rr_param is not None and final_tp_rr_param > 0:
                    final_tp_calc_raw = (
                        comparison_p + risk_dist * final_tp_rr_param
                        if direction == SignalDirection.LONG
                        else comparison_p - risk_dist * final_tp_rr_param
                    )
                elif tp_atr_mult > 0:
                    final_tp_calc_raw = (
                        comparison_p + atr_at_check * tp_atr_mult
                        if direction == SignalDirection.LONG
                        else comparison_p - atr_at_check * tp_atr_mult
                    )
                if final_tp_calc_raw is not None:
                    min_tp_dist_pct = getattr(
                        config, "MIN_PARTIAL_TP_DISTANCE_PCT", 0.004
                    )
                    min_profit_abs_f = comparison_p * min_tp_dist_pct
                    tp_raw_min_pct_f = (
                        comparison_p + min_profit_abs_f
                        if direction == SignalDirection.LONG
                        else comparison_p - min_profit_abs_f
                    )
                    final_tp_adj_by_min = (
                        max(final_tp_calc_raw, tp_raw_min_pct_f)
                        if direction == SignalDirection.LONG
                        else min(final_tp_calc_raw, tp_raw_min_pct_f)
                    )
                    relevant_ob_for_final_tp = (
                        ob_analysis.nearest_resistance
                        if direction == SignalDirection.LONG
                        and isinstance(ob_analysis, OrderbookAnalysisResult)
                        else (
                            ob_analysis.nearest_support
                            if direction == SignalDirection.SHORT
                            and isinstance(ob_analysis, OrderbookAnalysisResult)
                            else None
                        )
                    )
                    adapted_final_tp = _adapt_tp_to_orderbook(
                        final_tp_adj_by_min,
                        comparison_p,
                        direction,
                        relevant_ob_for_final_tp,
                        atr_at_check,
                        tick_size,
                        log_prefix,
                        is_partial_tp=False,
                    )
                    final_tp_to_round = (
                        adapted_final_tp
                        if adapted_final_tp is not None
                        else final_tp_adj_by_min
                    )
                    rounding_f = (
                        ROUND_UP if direction == SignalDirection.LONG else ROUND_DOWN
                    )
                    final_tp = round_price_by_tick(
                        final_tp_to_round, tick_size, rounding_f
                    )
                if final_tp is None:
                    logger.error(
                        f"{log_prefix} Partials do not cover 100% ({cumulative_partial_fraction:.2f}) but could not determine a final TP. Signal cannot be created."
                    )
                    return None
            else:  # Partials cover 100%
                final_tp = None  # Final TP is not needed
                logger.debug(
                    f"{log_prefix} Partials cover 100% ({cumulative_partial_fraction:.2f}). Final TP set to None."
                )
            risk_pct = self._get_param("risk_pct_per_trade")
            details = {
                "pattern": pattern_name,
                "trend": foundations.get("trend_detected", "N"),
                "range_h": f"{cons_high:.8f}",
                "range_l": f"{cons_low:.8f}",
                "atr_chk": f"{atr_at_check:.8f}",
                "trig_raw": f"{trig_p_pattern:.8f}",
                "sl_calc": f"{final_sl_price:.8f}",
                "tp_final_calc": f"{final_tp:.8f}" if final_tp else "N",
                "partials_n": len(partials or []),
                "founds": {
                    k: (v if isinstance(v, bool) else str(v))
                    for k, v in foundations.items()
                    if not k.startswith("foundation_")
                },
                "foundation_total_weight": foundations.get("foundation_total_weight"),
                "foundation_met_details_log": foundations.get(
                    "foundation_met_details_log"
                ),
            }
            logger.debug(
                f"{log_prefix} About to create signal with: dir={direction}, trig={trig_p_pattern}, sl={final_sl_price}, tp={final_tp}, mode={mode}, entry={entry_p}"
            )  # DEBUG
            return self._create_signal(
                symbol,
                direction,
                trig_p_pattern,
                final_sl_price,
                final_tp,
                mode,
                entry_p,
                details,
                partials,
                move_sl_be,
                risk_pct=risk_pct,
            )
        except ValueError as ve:
            logger.error(f"{log_prefix} ValueError: {ve}")
            return None  # pragma: no cover
        except Exception as e:
            logger.error(f"{log_prefix} Unexpected error: {e}", exc_info=True)
            return None  # pragma: no cover


class AggTradeReversalStrategy(BaseStrategy):
    NAME = "AggTradeReversal"
    description = "Searches for reversals based on aggregated trades (aggTrades) using the spike/fade pattern."

    @property
    def required_data_types(self) -> Set[str]:
        tf = self._get_param("candle_timeframe", "1m")
        base_reqs = super().required_data_types
        strategy_reqs = {f"kline_{tf}", "aggTrade"}
        return base_reqs.union(strategy_reqs)

    def _check_pattern_agg_trade_reversal(
        self,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        current_candle_idx: Optional[int],
    ) -> Tuple[
        Optional[str],
        Optional[float],
        Optional[float],
        Optional[float],
        Optional[float],
    ]:
        symbol = pair_info.get("symbol")
        log_prefix = f"[{self.NAME}:{symbol}:PatternCheck]"
        try:
            spike_trades_count = self._get_param("spike_trades_count", 10)
            fade_trades_count = self._get_param("fade_trades_count", 30)
            spike_dev_atr_mult = self._get_param("spike_price_deviation_atr", 0.5)
            volume_inc_mult = self._get_param("volume_increase_multiplier", 2.0)
            atr = pair_info.get("atr")
        except Exception as e:
            logger.error(f"{log_prefix} Error getting params/ATR: {e}")
            return None, None, None, None, None  # pragma: no cover
        if atr is None or atr <= 0:
            logger.warning(f"{log_prefix} Missing/invalid ATR: {atr}")
            return None, None, None, None, None
        agg_trades_df = market_data.get("aggTrade")
        required_trades = spike_trades_count + fade_trades_count
        if (
            not isinstance(agg_trades_df, pd.DataFrame)
            or agg_trades_df.empty
            or len(agg_trades_df) < required_trades
        ):
            return None, None, None, None, None
        try:
            trades_df_slice = agg_trades_df.iloc[-required_trades:]
            spike_trades_data = trades_df_slice.iloc[-spike_trades_count:]
            fade_trades_data = trades_df_slice.iloc[:-spike_trades_count]
            avg_fade_price = float(fade_trades_data["price"].mean())
            avg_fade_volume_per_trade = float(fade_trades_data["quantity"].mean())
            avg_spike_price = float(spike_trades_data["price"].mean())
            total_spike_volume = float(spike_trades_data["quantity"].sum())
            trigger_price = float(spike_trades_data["price"].iloc[-1])
            spike_extremum_price = (
                float(spike_trades_data["price"].max())
                if avg_spike_price > avg_fade_price
                else float(spike_trades_data["price"].min())
            )
            if abs(avg_spike_price - avg_fade_price) < atr * spike_dev_atr_mult:
                return None, None, None, None, None
            expected_fade_vol = avg_fade_volume_per_trade * spike_trades_count
            if (
                expected_fade_vol <= 1e-9
                or total_spike_volume < expected_fade_vol * volume_inc_mult
            ):
                return None, None, None, None, None
            if avg_spike_price > avg_fade_price:
                return (
                    "AggReversalUpSpike",
                    spike_extremum_price,
                    trigger_price,
                    avg_fade_price,
                    atr,
                )
            elif avg_spike_price < avg_fade_price:
                return (
                    "AggReversalDownSpike",
                    spike_extremum_price,
                    trigger_price,
                    avg_fade_price,
                    atr,
                )
        except (IndexError, KeyError, ValueError, TypeError) as e:
            logger.error(f"{log_prefix} Error processing aggTrades: {e}", exc_info=True)
            return None, None, None, None, None  # pragma: no cover
        return None, None, None, None, None

    def check_foundations(
        self, pair_info: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        symbol = pair_info.get("symbol", self.NAME)
        log_prefix = f"[{symbol}:{self.NAME}:Foundations]"
        foundations_status, trace_nodes = super().check_foundations(
            pair_info, market_data
        )
        try:
            candle_tf_strat = self._get_param("candle_timeframe", "1m")
            kline_key_strat = f"kline_{candle_tf_strat}"
            candles_df_strat = market_data.get(kline_key_strat)

            current_candle_idx_for_pattern = None
            if (
                isinstance(candles_df_strat, pd.DataFrame)
                and not candles_df_strat.empty
            ):
                backtest_idx = pair_info.get("current_candle_index")
                current_candle_idx_for_pattern = (
                    backtest_idx
                    if backtest_idx is not None
                    else len(candles_df_strat) - 1
                )

            pattern_name, spike_extr, trig_p, avg_fade_p, atr_check = (
                self._check_pattern_agg_trade_reversal(
                    pair_info, market_data, current_candle_idx_for_pattern
                )
            )

            foundations_status[FOUNDATION_PATTERN] = pattern_name is not None
            foundations_status["pattern_detected"] = (
                pattern_name if pattern_name else "None"
            )
            if pattern_name:
                foundations_status["pattern_spike_extremum"] = spike_extr
                foundations_status["pattern_trigger_price"] = trig_p
                foundations_status["pattern_avg_fade_price"] = avg_fade_p
                foundations_status["pattern_atr_at_check"] = atr_check

            trace_nodes.append(
                {
                    "id": FOUNDATION_PATTERN,
                    "type": "foundation",
                    "result": foundations_status[FOUNDATION_PATTERN],
                    "details": f"Pattern: {pattern_name}",
                }
            )

            if foundations_status[FOUNDATION_PATTERN] and not foundations_status.get(
                FOUNDATION_VOLUME_CONFIRMATION
            ):
                foundations_status[FOUNDATION_VOLUME_CONFIRMATION] = True
        except Exception as e:
            logger.error(
                f"{log_prefix} Error in specific foundation checks: {e}", exc_info=True
            )
        return foundations_status, trace_nodes

    def _check_specific_signal_logic(
        self,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        foundations: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        symbol = pair_info.get("symbol")
        log_prefix = f"[{self.NAME}:{symbol}:SpecificLogic]"
        pattern_name = foundations.get("pattern_detected")
        spike_extr = foundations.get("pattern_spike_extremum")
        trig_p_pattern = foundations.get("pattern_trigger_price")
        avg_fade_p = foundations.get("pattern_avg_fade_price")
        atr_at_check = foundations.get("pattern_atr_at_check")

        if (
            not pattern_name
            or pattern_name == "None"
            or spike_extr is None
            or trig_p_pattern is None
            or avg_fade_p is None
            or atr_at_check is None
            or atr_at_check <= 0
        ):
            return None

        direction = (
            SignalDirection.SHORT
            if "UpSpike" in pattern_name
            else (SignalDirection.LONG if "DownSpike" in pattern_name else None)
        )
        if direction is None:
            return None
        candle_tf_strat = self._get_param("candle_timeframe", "1m")
        kline_key_strat = f"kline_{candle_tf_strat}"
        candles_df_strat = market_data.get(kline_key_strat)
        current_candle_idx_strat: Optional[int] = None
        backtest_idx = pair_info.get("current_candle_index")
        if isinstance(candles_df_strat, pd.DataFrame) and not candles_df_strat.empty:
            current_candle_idx_strat = (
                backtest_idx if backtest_idx is not None else len(candles_df_strat) - 1
            )
        if current_candle_idx_strat is None:
            logger.warning(f"{log_prefix} Invalid index for specific logic.")
            return None
        _, spike_extr, trig_p_pattern, avg_fade_p, atr_at_check = (
            self._check_pattern_agg_trade_reversal(
                pair_info, market_data, current_candle_idx_strat
            )
        )
        if (
            spike_extr is None
            or trig_p_pattern is None
            or avg_fade_p is None
            or atr_at_check is None
            or atr_at_check <= 0
        ):
            logger.debug(f"{log_prefix} Pattern check incomplete vals.")
            return None
        direction = (
            SignalDirection.SHORT
            if "UpSpike" in pattern_name
            else (SignalDirection.LONG if "DownSpike" in pattern_name else None)
        )
        if direction is None:
            return None  # pragma: no cover
        ob_analysis = foundations.get(FOUNDATION_ORDERBOOK)
        if isinstance(ob_analysis, OrderbookAnalysisResult):
            if (
                direction == SignalDirection.LONG
                and ob_analysis.is_price_near_resistance
            ):
                logger.info(
                    f"{log_prefix} LONG signal REJECTED by OB: Price near resistance."
                )
                return None
            if direction == SignalDirection.SHORT and ob_analysis.is_price_near_support:
                logger.info(
                    f"{log_prefix} SHORT signal REJECTED by OB: Price near support."
                )
                return None
        try:
            entry_mode_str = self._get_param("entry_mode", "MARKET")
            mode = OrderMode[entry_mode_str.upper()]
            limit_offset_atr = self._get_param("limit_entry_offset_atr", 0.1)
            sl_mult = self._get_param("stop_loss_atr_multiplier", 1.0)
            atr = pair_info.get("atr")
            if atr is None or atr <= 0:
                raise ValueError(
                    "Missing or invalid ATR in pair_info for partials calculation"
                )
            tick_size = pair_info.get("tick_size")
            if tick_size is None or tick_size <= 0:
                raise ValueError("Missing/invalid TickSize.")  # pragma: no cover
            base_sl_price = (
                round_price_by_tick(
                    spike_extr + atr_at_check * sl_mult, tick_size, ROUND_UP
                )
                if direction == SignalDirection.SHORT
                else round_price_by_tick(
                    spike_extr - atr_at_check * sl_mult, tick_size, ROUND_DOWN
                )
            )
            if (
                base_sl_price is None
                or base_sl_price <= 0
                or (
                    direction == SignalDirection.SHORT
                    and base_sl_price <= trig_p_pattern
                )
                or (
                    direction == SignalDirection.LONG
                    and base_sl_price >= trig_p_pattern
                )
            ):
                raise ValueError("Invalid base SL")  # pragma: no cover
            entry_p: Optional[float] = None
            comparison_p = trig_p_pattern
            if mode == OrderMode.LIMIT_RETEST:
                pe_raw = (
                    trig_p_pattern + atr_at_check * limit_offset_atr
                    if direction == SignalDirection.SHORT
                    else trig_p_pattern - atr_at_check * limit_offset_atr
                )
                pe = round_price_by_tick(
                    pe_raw,
                    tick_size,
                    ROUND_UP if direction == SignalDirection.SHORT else ROUND_DOWN,
                )
                if pe is not None and (
                    (
                        direction == SignalDirection.SHORT
                        and pe < base_sl_price
                        and pe > trig_p_pattern
                    )
                    or (
                        direction == SignalDirection.LONG
                        and pe > base_sl_price
                        and pe < trig_p_pattern
                    )
                ):
                    entry_p = pe
                    comparison_p = entry_p
                else:
                    logger.debug(
                        f"{log_prefix} Limit entry ({pe}) invalid. Using MARKET."
                    )
                    mode = OrderMode.MARKET  # pragma: no cover
            ob_density_for_sl = (
                ob_analysis.nearest_support
                if direction == SignalDirection.LONG
                and isinstance(ob_analysis, OrderbookAnalysisResult)
                else (
                    ob_analysis.nearest_resistance
                    if direction == SignalDirection.SHORT
                    and isinstance(ob_analysis, OrderbookAnalysisResult)
                    else None
                )
            )
            adapted_sl = _adapt_sl_to_orderbook(
                base_sl_price,
                comparison_p,
                direction,
                ob_density_for_sl,
                atr_at_check,
                tick_size,
                log_prefix,
            )
            final_sl_price = adapted_sl if adapted_sl is not None else base_sl_price
            rr_conf_raw = self._get_param("partial_exit_rr_config", [])
            move_sl_be = self._get_param("move_sl_to_be_on_first_tp", True)
            final_tp_rr_param = self._get_param("final_tp_rr")
            tp_atr_mult = self._get_param("take_profit_atr_multiplier", 1.2)
            partials: Optional[List[PartialTarget]] = None
            final_tp: Optional[float] = None
            rr_conf_parsed = None
            if isinstance(rr_conf_raw, list) and all(
                isinstance(t, (list, tuple)) and len(t) == 2 for t in rr_conf_raw
            ):
                try:
                    rr_conf_parsed = [(float(r), float(f)) for r, f in rr_conf_raw]
                except Exception:
                    logger.warning(
                        f"{log_prefix} Invalid partial_exit_rr_config format."
                    )  # pragma: no cover
            if rr_conf_parsed:
                partials = self._calculate_partial_targets_from_rr(
                    comparison_p,
                    final_sl_price,
                    direction,
                    rr_conf_parsed,
                    tick_size,
                    atr_at_signal_time=atr,
                )
                if partials and isinstance(ob_analysis, OrderbookAnalysisResult):
                    adapted_partials = []
                    for pt_idx, pt in enumerate(partials):
                        relevant_ob_for_pt = (
                            ob_analysis.nearest_resistance
                            if direction == SignalDirection.LONG
                            else ob_analysis.nearest_support
                        )
                        adapted_pt_price = _adapt_tp_to_orderbook(
                            pt.price,
                            comparison_p,
                            direction,
                            relevant_ob_for_pt,
                            atr_at_check,
                            tick_size,
                            f"{log_prefix}[PT#{pt_idx + 1}]",
                            is_partial_tp=True,
                        )
                        adapted_partials.append(
                            PartialTarget(
                                price=(
                                    adapted_pt_price if adapted_pt_price else pt.price
                                ),
                                fraction=pt.fraction,
                            )
                        )
                    partials = adapted_partials
            cumulative_partial_fraction = (
                sum(t.fraction for t in partials) if partials else 0.0
            )
            if cumulative_partial_fraction < (1.0 - 1e-9):
                final_tp_calc_raw = None
                risk_dist = abs(comparison_p - final_sl_price)
                if risk_dist <= 1e-9:
                    logger.warning(
                        f"{log_prefix} Zero risk for final TP calc."
                    )  # pragma: no cover
                elif final_tp_rr_param is not None and final_tp_rr_param > 0:
                    final_tp_calc_raw = (
                        comparison_p + risk_dist * final_tp_rr_param
                        if direction == SignalDirection.LONG
                        else comparison_p - risk_dist * final_tp_rr_param
                    )
                elif tp_atr_mult > 0:
                    final_tp_calc_raw = (
                        comparison_p + atr * tp_atr_mult
                        if direction == SignalDirection.LONG
                        else comparison_p - atr * tp_atr_mult
                    )
                if final_tp_calc_raw is not None:
                    min_tp_dist_pct = getattr(
                        config, "MIN_PARTIAL_TP_DISTANCE_PCT", 0.004
                    )
                    min_profit_abs_f = comparison_p * min_tp_dist_pct
                    tp_raw_min_pct_f = (
                        comparison_p + min_profit_abs_f
                        if direction == SignalDirection.LONG
                        else comparison_p - min_profit_abs_f
                    )
                    final_tp_adj_by_min = (
                        max(final_tp_calc_raw, tp_raw_min_pct_f)
                        if direction == SignalDirection.LONG
                        else min(final_tp_calc_raw, tp_raw_min_pct_f)
                    )
                    relevant_ob_for_final_tp = (
                        ob_analysis.nearest_resistance
                        if direction == SignalDirection.LONG
                        and isinstance(ob_analysis, OrderbookAnalysisResult)
                        else (
                            ob_analysis.nearest_support
                            if direction == SignalDirection.SHORT
                            and isinstance(ob_analysis, OrderbookAnalysisResult)
                            else None
                        )
                    )
                    adapted_final_tp = _adapt_tp_to_orderbook(
                        final_tp_adj_by_min,
                        comparison_p,
                        direction,
                        relevant_ob_for_final_tp,
                        atr,
                        tick_size,
                        log_prefix,
                        is_partial_tp=False,
                    )
                    final_tp_to_round = (
                        adapted_final_tp
                        if adapted_final_tp is not None
                        else final_tp_adj_by_min
                    )
                    rounding_f = (
                        ROUND_UP if direction == SignalDirection.LONG else ROUND_DOWN
                    )
                    final_tp = round_price_by_tick(
                        final_tp_to_round, tick_size, rounding_f
                    )
                if final_tp is None:
                    logger.error(
                        f"{log_prefix} Partials do not cover 100% ({cumulative_partial_fraction:.2f}) but could not determine a final TP. Signal cannot be created."
                    )
                    return None
            else:  # Partials cover 100%
                final_tp = None  # Final TP is not needed
                logger.debug(
                    f"{log_prefix} Partials cover 100% ({cumulative_partial_fraction:.2f}). Final TP set to None."
                )
            risk_pct = self._get_param("risk_pct_per_trade")
            details = {
                "pattern": pattern_name,
                "trend": foundations.get("trend_detected", "N"),
                "spike_extr": f"{spike_extr:.8f}",
                "avg_fade_p": f"{avg_fade_p:.8f}",
                "atr_chk": f"{atr_at_check:.8f}",
                "trig_raw": f"{trig_p_pattern:.8f}",
                "entry_calc": f"{entry_p:.8f}" if entry_p else "MKT",
                "sl_calc": f"{final_sl_price:.8f}",
                "tp_final_calc": f"{final_tp:.8f}" if final_tp else "N",
                "partials_n": len(partials or []),
                "founds": {
                    k: (v if isinstance(v, bool) else str(v))
                    for k, v in foundations.items()
                },
            }
            return self._create_signal(
                symbol,
                direction,
                trig_p_pattern,
                final_sl_price,
                final_tp,
                mode,
                entry_p,
                details,
                partials,
                move_sl_be,
                risk_pct=risk_pct,
            )
        except ValueError as ve:
            logger.error(f"{log_prefix} ValueError: {ve}")
            return None  # pragma: no cover
        except Exception as e:
            logger.error(f"{log_prefix} Unexpected error: {e}", exc_info=True)
            return None  # pragma: no cover


class FirstPullbacksInTrendStrategy(BaseStrategy):
    NAME = "FirstPullbacksInTrend"
    description = "Searches for the first pullbacks in a trend, using SMA or Bars to check the pullback."

    @property
    def required_data_types(self) -> Set[str]:
        tf_entry = self._get_param("entry_timeframe", "1m")
        tf_trend = self._get_param("trend_timeframe", "5m")
        base_reqs = super().required_data_types
        strategy_reqs = {f"kline_{tf_entry}", f"kline_{tf_trend}", "aggTrade"}
        return base_reqs.union(strategy_reqs)

    def _check_pattern_pullback(
        self,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        trend: str,
        current_candle_idx_entry_tf: Optional[int],
    ) -> Tuple[Optional[str], Optional[float], Optional[pd.DataFrame]]:
        symbol = pair_info.get("symbol")
        log_prefix = f"[{self.NAME}:{symbol}:PatternCheck]"
        try:
            entry_timeframe = self._get_param("entry_timeframe", "1m")
            pullback_mode = self._get_param("pullback_check_mode", "SMA").upper()
            pb_sma_allowance = self._get_param("pullback_sma_touch_allowance", 0.02)
            pb_bars_count = self._get_param("pullback_bars_count", 3)
            sma_fast_period = self._get_param("sma_fast_period", 10)
        except Exception as e:
            logger.error(f"{log_prefix} Error getting params: {e}")
            return None, None, None  # pragma: no cover
        kline_entry_key = f"kline_{entry_timeframe}"
        entry_candles_df = market_data.get(kline_entry_key)
        sma_fast_trend_tf_key = f"SMA_{sma_fast_period}"
        sma_fast_val = pair_info.get(sma_fast_trend_tf_key)
        if (
            current_candle_idx_entry_tf is None
            or not isinstance(entry_candles_df, pd.DataFrame)
            or entry_candles_df.empty
            or current_candle_idx_entry_tf < 0
        ):
            return None, None, None  # pragma: no cover
        required_hist_len = (
            pb_bars_count if pullback_mode == "BARS" else 0
        )  # Index 0 already means 1 candle
        if current_candle_idx_entry_tf < required_hist_len:
            return None, None, None
        try:
            last_closed_entry_candle = entry_candles_df.iloc[
                current_candle_idx_entry_tf
            ]
            low_entry = float(last_closed_entry_candle["low"])
            high_entry = float(last_closed_entry_candle["high"])
            sl_base_price = None
            pullback_candles_slice = None
            pattern_name = None
            if pullback_mode == "SMA":
                if sma_fast_val is None:
                    logger.warning(
                        f"{log_prefix} SMA_fast ({sma_fast_trend_tf_key}) not found in pair_info for SMA pullback mode."
                    )
                    return None, None, None  # pragma: no cover
                sma_fast_target = float(sma_fast_val)
                pullback_level_upper = sma_fast_target * (1 + pb_sma_allowance)
                pullback_level_lower = sma_fast_target * (1 - pb_sma_allowance)
                if trend == "LONG" and low_entry <= pullback_level_upper:
                    sl_base_price = low_entry
                    pattern_name = "PullbackSmaLong"
                elif trend == "SHORT" and high_entry >= pullback_level_lower:
                    sl_base_price = high_entry
                    pattern_name = "PullbackSmaShort"
            elif pullback_mode == "BARS":
                pullback_end_idx = current_candle_idx_entry_tf + 1
                pullback_start_idx = pullback_end_idx - pb_bars_count
                if pullback_start_idx < 0:
                    return None, None, None  # pragma: no cover
                pullback_candles_slice = entry_candles_df.iloc[
                    pullback_start_idx:pullback_end_idx
                ]
                if pullback_candles_slice.empty:
                    return None, None, None  # pragma: no cover
                first_close = float(pullback_candles_slice["close"].iloc[0])
                last_close = float(pullback_candles_slice["close"].iloc[-1])
                if trend == "LONG" and last_close < first_close:
                    sl_base_price = float(pullback_candles_slice["low"].min())
                    pattern_name = "PullbackBarsLong"
                elif trend == "SHORT" and last_close > first_close:
                    sl_base_price = float(pullback_candles_slice["high"].max())
                    pattern_name = "PullbackBarsShort"
            return pattern_name, sl_base_price, pullback_candles_slice
        except (IndexError, KeyError, ValueError, TypeError) as e:
            logger.error(f"{log_prefix} Error checking pullback: {e}", exc_info=True)
            return None, None, None  # pragma: no cover

    def check_foundations(
        self, pair_info: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        symbol = pair_info.get("symbol", self.NAME)
        log_prefix = f"[{symbol}:{self.NAME}:Foundations]"
        foundations_status, trace_nodes = super().check_foundations(
            pair_info, market_data
        )
        try:
            trend_direction = foundations_status.get("trend_detected")
            if trend_direction and trend_direction != "FLAT":
                entry_tf = self._get_param("entry_timeframe", "1m")
                kline_entry_key = f"kline_{entry_tf}"
                entry_candles_df = market_data.get(kline_entry_key)

                current_candle_idx_entry_tf: Optional[int] = None
                if (
                    isinstance(entry_candles_df, pd.DataFrame)
                    and not entry_candles_df.empty
                ):
                    backtest_idx = pair_info.get("current_candle_index")
                    current_candle_idx_entry_tf = (
                        backtest_idx
                        if backtest_idx is not None
                        else len(entry_candles_df) - 1
                    )

                pattern_name, sl_base_price, _ = self._check_pattern_pullback(
                    pair_info, market_data, trend_direction, current_candle_idx_entry_tf
                )

                foundations_status[FOUNDATION_PATTERN] = pattern_name is not None
                foundations_status["pattern_detected"] = (
                    pattern_name if pattern_name else "None"
                )
                if pattern_name:
                    foundations_status["pattern_sl_base_price"] = sl_base_price

                trace_nodes.append(
                    {
                        "id": FOUNDATION_PATTERN,
                        "type": "foundation",
                        "result": foundations_status[FOUNDATION_PATTERN],
                        "details": f"Pattern: {pattern_name}",
                    }
                )

            else:
                foundations_status[FOUNDATION_PATTERN] = False
                foundations_status["pattern_detected"] = "None"
                trace_nodes.append(
                    {
                        "id": FOUNDATION_PATTERN,
                        "type": "foundation",
                        "result": False,
                        "details": "No Trend",
                    }
                )

        except Exception as e:
            logger.error(
                f"{log_prefix} Error in specific foundation checks: {e}", exc_info=True
            )
            foundations_status[FOUNDATION_PATTERN] = False
            foundations_status["pattern_detected"] = "None"
            trace_nodes.append(
                {
                    "id": FOUNDATION_PATTERN,
                    "type": "foundation",
                    "result": False,
                    "details": f"Error: {e}",
                }
            )

        return foundations_status, trace_nodes

    def _check_specific_signal_logic(
        self,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        foundations: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        symbol = pair_info.get("symbol")
        log_prefix = f"[{self.NAME}:{symbol}:SpecificLogic]"
        trend_dir_str = foundations.get("trend_detected")
        pattern_name = foundations.get("pattern_detected")
        sl_base_p_pattern = foundations.get("pattern_sl_base_price")

        if (
            not trend_dir_str
            or trend_dir_str == "FLAT"
            or not pattern_name
            or pattern_name == "None"
            or sl_base_p_pattern is None
        ):
            return None

        direction = (
            SignalDirection.LONG if trend_dir_str == "LONG" else SignalDirection.SHORT
        )
        entry_tf = self._get_param("entry_timeframe", "1m")
        kline_entry_key = f"kline_{entry_tf}"
        entry_candles_df = market_data.get(kline_entry_key)
        current_candle_idx_entry_tf: Optional[int] = None
        backtest_idx = pair_info.get("current_candle_index")
        if isinstance(entry_candles_df, pd.DataFrame) and not entry_candles_df.empty:
            current_candle_idx_entry_tf = (
                backtest_idx if backtest_idx is not None else len(entry_candles_df) - 1
            )
        if current_candle_idx_entry_tf is None:
            logger.warning(f"{log_prefix} Invalid index for specific logic.")
            return None  # pragma: no cover
        _, sl_base_p_pattern, _ = self._check_pattern_pullback(
            pair_info, market_data, trend_dir_str, current_candle_idx_entry_tf
        )
        if sl_base_p_pattern is None:
            logger.debug(f"{log_prefix} Pullback pattern no SL base.")
            return None
        direction = (
            SignalDirection.LONG if trend_dir_str == "LONG" else SignalDirection.SHORT
        )
        if not foundations.get(FOUNDATION_VOLUME_CONFIRMATION, False):
            logger.debug(f"{log_prefix} Rejected: Vol not confirmed.")
            return None
        ob_analysis = foundations.get(FOUNDATION_ORDERBOOK)
        if isinstance(ob_analysis, OrderbookAnalysisResult):
            if (
                direction == SignalDirection.LONG
                and ob_analysis.is_price_near_resistance
            ):
                logger.info(
                    f"{log_prefix} LONG signal REJECTED by OB: Price near resistance."
                )
                return None
            if direction == SignalDirection.SHORT and ob_analysis.is_price_near_support:
                logger.info(
                    f"{log_prefix} SHORT signal REJECTED by OB: Price near support."
                )
                return None
        try:
            rsi_p = self._get_param("rsi_period", 14)
            rsi_low = self._get_param("rsi_lower_bound", 30)
            rsi_high = self._get_param("rsi_upper_bound", 70)
            confirmation_req = self._get_param("confirmation_bar_required", False)
            sl_mult = self._get_param("stop_loss_atr_multiplier", 1.1)
            atr = pair_info.get("atr")
            tick_size = pair_info.get("tick_size")
            rsi_trend_key = f"RSI_{rsi_p}"
            rsi_trend_val = pair_info.get(rsi_trend_key)
            if (
                atr is None
                or tick_size is None
                or rsi_trend_val is None
                or atr <= 0
                or tick_size <= 0
            ):
                raise ValueError(
                    "Missing/invalid ATR,TickSize,RSI_trend"
                )  # pragma: no cover
            rsi_trend_val = float(rsi_trend_val)
            if (direction == SignalDirection.LONG and rsi_trend_val <= rsi_low) or (
                direction == SignalDirection.SHORT and rsi_trend_val >= rsi_high
            ):
                logger.debug(f"{log_prefix} {direction.name} Rejected: Trend RSI.")
                return None
            trigger_candle = entry_candles_df.iloc[current_candle_idx_entry_tf]
            trigger_p = float(trigger_candle["close"])
            if confirmation_req:
                conf_open = float(trigger_candle["open"])
                conf_close = trigger_p
                if (direction == SignalDirection.LONG and conf_close <= conf_open) or (
                    direction == SignalDirection.SHORT and conf_close >= conf_open
                ):
                    logger.debug(
                        f"{log_prefix} {direction.name} Rejected: Conf bar invalid."
                    )
                    return None  # pragma: no cover
            base_sl_price = (
                round_price_by_tick(
                    sl_base_p_pattern - atr * sl_mult, tick_size, ROUND_DOWN
                )
                if direction == SignalDirection.LONG
                else round_price_by_tick(
                    sl_base_p_pattern + atr * sl_mult, tick_size, ROUND_UP
                )
            )
            if (
                base_sl_price is None
                or base_sl_price <= 0
                or (direction == SignalDirection.LONG and base_sl_price >= trigger_p)
                or (direction == SignalDirection.SHORT and base_sl_price <= trigger_p)
            ):
                raise ValueError("Invalid base SL")  # pragma: no cover
            mode = OrderMode.MARKET
            entry_p = None
            comparison_p = trigger_p
            ob_density_for_sl = (
                ob_analysis.nearest_support
                if direction == SignalDirection.LONG
                and isinstance(ob_analysis, OrderbookAnalysisResult)
                else (
                    ob_analysis.nearest_resistance
                    if direction == SignalDirection.SHORT
                    and isinstance(ob_analysis, OrderbookAnalysisResult)
                    else None
                )
            )
            adapted_sl = _adapt_sl_to_orderbook(
                base_sl_price,
                comparison_p,
                direction,
                ob_density_for_sl,
                atr,
                tick_size,
                log_prefix,
            )
            final_sl_price = adapted_sl if adapted_sl is not None else base_sl_price
            rr_conf_raw = self._get_param("partial_exit_rr_config", [])
            move_sl_be = self._get_param("move_sl_to_be_on_first_tp", True)
            final_tp_rr_param = self._get_param("final_tp_rr")
            tp_atr_mult = self._get_param("take_profit_atr_multiplier", 1.5)
            partials: Optional[List[PartialTarget]] = None
            final_tp: Optional[float] = None
            rr_conf_parsed = None
            if isinstance(rr_conf_raw, list) and all(
                isinstance(t, (list, tuple)) and len(t) == 2 for t in rr_conf_raw
            ):
                try:
                    rr_conf_parsed = [(float(r), float(f)) for r, f in rr_conf_raw]
                except Exception:
                    logger.warning(
                        f"{log_prefix} Invalid partial_exit_rr_config format."
                    )  # pragma: no cover
            if rr_conf_parsed:
                partials = self._calculate_partial_targets_from_rr(
                    comparison_p,
                    final_sl_price,
                    direction,
                    rr_conf_parsed,
                    tick_size,
                    atr_at_signal_time=atr,
                )
                if partials and isinstance(ob_analysis, OrderbookAnalysisResult):
                    adapted_partials = []
                    for pt_idx, pt in enumerate(partials):
                        relevant_ob_for_pt = (
                            ob_analysis.nearest_resistance
                            if direction == SignalDirection.LONG
                            else ob_analysis.nearest_support
                        )
                        adapted_pt_price = _adapt_tp_to_orderbook(
                            pt.price,
                            comparison_p,
                            direction,
                            relevant_ob_for_pt,
                            atr,
                            tick_size,
                            f"{log_prefix}[PT#{pt_idx + 1}]",
                            is_partial_tp=True,
                        )
                        adapted_partials.append(
                            PartialTarget(
                                price=(
                                    adapted_pt_price if adapted_pt_price else pt.price
                                ),
                                fraction=pt.fraction,
                            )
                        )
                    partials = adapted_partials
            cumulative_partial_fraction = (
                sum(t.fraction for t in partials) if partials else 0.0
            )
            if cumulative_partial_fraction < (1.0 - 1e-9):
                final_tp_calc_raw = None
                risk_dist = abs(comparison_p - final_sl_price)
                if risk_dist <= 1e-9:
                    logger.warning(
                        f"{log_prefix} Zero risk for final TP calc."
                    )  # pragma: no cover
                elif final_tp_rr_param is not None and final_tp_rr_param > 0:
                    final_tp_calc_raw = (
                        comparison_p + risk_dist * final_tp_rr_param
                        if direction == SignalDirection.LONG
                        else comparison_p - risk_dist * final_tp_rr_param
                    )
                elif tp_atr_mult > 0:
                    final_tp_calc_raw = (
                        comparison_p + atr * tp_atr_mult
                        if direction == SignalDirection.LONG
                        else comparison_p - atr * tp_atr_mult
                    )
                if final_tp_calc_raw is not None:
                    min_tp_dist_pct = getattr(
                        config, "MIN_PARTIAL_TP_DISTANCE_PCT", 0.004
                    )
                    min_profit_abs_f = comparison_p * min_tp_dist_pct
                    tp_raw_min_pct_f = (
                        comparison_p + min_profit_abs_f
                        if direction == SignalDirection.LONG
                        else comparison_p - min_profit_abs_f
                    )
                    final_tp_adj_by_min = (
                        max(final_tp_calc_raw, tp_raw_min_pct_f)
                        if direction == SignalDirection.LONG
                        else min(final_tp_calc_raw, tp_raw_min_pct_f)
                    )
                    relevant_ob_for_final_tp = (
                        ob_analysis.nearest_resistance
                        if direction == SignalDirection.LONG
                        and isinstance(ob_analysis, OrderbookAnalysisResult)
                        else (
                            ob_analysis.nearest_support
                            if direction == SignalDirection.SHORT
                            and isinstance(ob_analysis, OrderbookAnalysisResult)
                            else None
                        )
                    )
                    adapted_final_tp = _adapt_tp_to_orderbook(
                        final_tp_adj_by_min,
                        comparison_p,
                        direction,
                        relevant_ob_for_final_tp,
                        atr,
                        tick_size,
                        log_prefix,
                        is_partial_tp=False,
                    )
                    final_tp_to_round = (
                        adapted_final_tp
                        if adapted_final_tp is not None
                        else final_tp_adj_by_min
                    )
                    rounding_f = (
                        ROUND_UP if direction == SignalDirection.LONG else ROUND_DOWN
                    )
                    final_tp = round_price_by_tick(
                        final_tp_to_round, tick_size, rounding_f
                    )
                if final_tp is None:
                    logger.error(
                        f"{log_prefix} Partials do not cover 100% ({cumulative_partial_fraction:.2f}) but could not determine a final TP. Signal cannot be created."
                    )
                    return None
            else:  # Partials cover 100%
                final_tp = None  # Final TP is not needed
                logger.debug(
                    f"{log_prefix} Partials cover 100% ({cumulative_partial_fraction:.2f}). Final TP set to None."
                )
            risk_pct = self._get_param("risk_pct_per_trade")
            details = {
                "pattern": pattern_name,
                "trend": trend_dir_str,
                "rsi_trend": f"{rsi_trend_val:.2f}",
                "sl_base_patt": f"{sl_base_p_pattern:.8f}",
                "atr_entry": f"{atr:.8f}",
                "trig_raw": f"{trigger_p:.8f}",
                "conf_used": confirmation_req,
                "sl_calc": f"{final_sl_price:.8f}",
                "tp_final_calc": f"{final_tp:.8f}" if final_tp else "N",
                "partials_n": len(partials or []),
                "founds": {
                    k: (v if isinstance(v, bool) else str(v))
                    for k, v in foundations.items()
                },
            }
            return self._create_signal(
                symbol,
                direction,
                trigger_p,
                final_sl_price,
                final_tp,
                mode,
                entry_p,
                details,
                partials,
                move_sl_be,
                risk_pct=risk_pct,
            )
        except ValueError as ve:
            logger.error(f"{log_prefix} ValueError: {ve}")
            return None  # pragma: no cover
        except Exception as e:
            logger.error(f"{log_prefix} Unexpected error: {e}", exc_info=True)
            return None  # pragma: no cover


class ReverseVolumeBreakoutStrategy(BaseStrategy):
    NAME = "ReverseVolumeBreakout"
    description = "Reverses VolumeBreakoutStrategy signals based on volume confirmation and price action."

    @property
    def required_data_types(self) -> Set[str]:
        orig_strat = get_strategy_instance("VolumeBreakout")
        return (
            orig_strat.required_data_types
            if orig_strat
            else super().required_data_types
        )  # pragma: no cover

    def check_foundations(
        self, pair_info: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        orig_strat = get_strategy_instance("VolumeBreakout")
        return (
            orig_strat.check_foundations(pair_info, market_data)
            if orig_strat
            else super().check_foundations(pair_info, market_data)
        )  # pragma: no cover

    def _check_specific_signal_logic(
        self,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        foundations: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        symbol = pair_info.get("symbol")
        log_prefix = f"[{self.NAME}:{symbol}:SpecificLogic]"
        original_pattern_name = foundations.get("pattern_detected")
        if not original_pattern_name or original_pattern_name == "None":
            return None
        if not foundations.get(FOUNDATION_VOLUME_CONFIRMATION, False):
            return None  # pragma: no cover
        original_direction = (
            SignalDirection.LONG
            if "Up" in original_pattern_name
            else (SignalDirection.SHORT if "Down" in original_pattern_name else None)
        )
        if original_direction is None:
            return None  # pragma: no cover
        reversed_direction = (
            SignalDirection.SHORT
            if original_direction == SignalDirection.LONG
            else SignalDirection.LONG
        )
        original_strat = get_strategy_instance("VolumeBreakout")
        if not original_strat:
            logger.error(
                f"{log_prefix} Could not get original VolumeBreakoutStrategy instance."
            )
            return None  # pragma: no cover
        orig_signal_for_risk_calc = original_strat._check_specific_signal_logic(
            pair_info, market_data, foundations
        )
        if not orig_signal_for_risk_calc:
            return None
        new_sl_price = orig_signal_for_risk_calc.take_profit
        if new_sl_price is None:
            logger.warning(
                f"{log_prefix} Original TP (new SL) is None. Cannot reverse."
            )
            return None
        new_trigger_price = orig_signal_for_risk_calc.stop_loss
        reverse_sl_tp_ratio = self._get_param("reverse_sl_to_tp_ratio", 2.0)
        risk_distance_new = abs(new_trigger_price - new_sl_price)
        if risk_distance_new <= 1e-9:
            return None  # pragma: no cover
        new_tp_price = (
            new_trigger_price + risk_distance_new * reverse_sl_tp_ratio
            if reversed_direction == SignalDirection.LONG
            else new_trigger_price - risk_distance_new * reverse_sl_tp_ratio
        )
        tick_size = pair_info.get("tick_size")
        if tick_size is None:
            return None  # pragma: no cover
        new_tp_price_rounded = round_price_by_tick(
            new_tp_price,
            tick_size,
            ROUND_UP if reversed_direction == SignalDirection.LONG else ROUND_DOWN,
        )
        if new_tp_price_rounded is None:
            return None  # pragma: no cover
        risk_pct = self._get_param("risk_pct_per_trade")
        details = {
            "original_pattern": original_pattern_name,
            "original_direction": original_direction.name,
            "reversed_from_strategy": "VolumeBreakout",
            "trend": foundations.get("trend_detected", "N"),
            "founds": {
                k: (v if isinstance(v, bool) else str(v))
                for k, v in foundations.items()
            },
        }
        return self._create_signal(
            symbol,
            reversed_direction,
            new_trigger_price,
            new_sl_price,
            new_tp_price_rounded,
            mode=OrderMode.MARKET,
            details=details,
            risk_pct=risk_pct,
        )


class ReverseFakeBreakoutStrategy(BaseStrategy):
    NAME = "ReverseFakeBreakout"
    description = "Reverses FakeBreakoutStrategy signals based on volume confirmation and price action."

    @property
    def required_data_types(self) -> Set[str]:
        orig_strat = get_strategy_instance("FakeBreakout")
        return (
            orig_strat.required_data_types
            if orig_strat
            else super().required_data_types
        )  # pragma: no cover

    def check_foundations(
        self, pair_info: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        orig_strat = get_strategy_instance("FakeBreakout")
        return (
            orig_strat.check_foundations(pair_info, market_data)
            if orig_strat
            else super().check_foundations(pair_info, market_data)
        )  # pragma: no cover

    def _check_specific_signal_logic(
        self,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        foundations: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        symbol = pair_info.get("symbol")
        log_prefix = f"[{self.NAME}:{symbol}:SpecificLogic]"
        original_pattern_name = foundations.get("pattern_detected")
        if not original_pattern_name or original_pattern_name == "None":
            return None
        if not foundations.get(FOUNDATION_VOLUME_CONFIRMATION, False):
            return None  # pragma: no cover
        original_direction = (
            SignalDirection.SHORT
            if "Up" in original_pattern_name
            else (SignalDirection.LONG if "Down" in original_pattern_name else None)
        )
        if original_direction is None:
            return None  # pragma: no cover
        reversed_direction = (
            SignalDirection.SHORT
            if original_direction == SignalDirection.LONG
            else SignalDirection.LONG
        )
        original_strat = get_strategy_instance("FakeBreakout")
        if not original_strat:
            logger.error(
                f"{log_prefix} Could not get original FakeBreakoutStrategy instance."
            )
            return None  # pragma: no cover
        orig_signal_for_risk_calc = original_strat._check_specific_signal_logic(
            pair_info, market_data, foundations
        )
        if not orig_signal_for_risk_calc:
            return None
        new_sl_price = orig_signal_for_risk_calc.take_profit
        if new_sl_price is None:
            logger.warning(
                f"{log_prefix} Original TP (new SL) is None. Cannot reverse."
            )
            return None
        new_trigger_price = orig_signal_for_risk_calc.stop_loss
        reverse_sl_tp_ratio = self._get_param("reverse_sl_to_tp_ratio", 2.0)
        risk_distance_new = abs(new_trigger_price - new_sl_price)
        if risk_distance_new <= 1e-9:
            return None  # pragma: no cover
        new_tp_price = (
            new_trigger_price + risk_distance_new * reverse_sl_tp_ratio
            if reversed_direction == SignalDirection.LONG
            else new_trigger_price - risk_distance_new * reverse_sl_tp_ratio
        )
        tick_size = pair_info.get("tick_size")
        if tick_size is None:
            return None  # pragma: no cover
        new_tp_price_rounded = round_price_by_tick(
            new_tp_price,
            tick_size,
            ROUND_UP if reversed_direction == SignalDirection.LONG else ROUND_DOWN,
        )
        if new_tp_price_rounded is None:
            return None  # pragma: no cover
        risk_pct = self._get_param("risk_pct_per_trade")
        details = {
            "original_pattern": original_pattern_name,
            "original_direction": original_direction.name,
            "reversed_from_strategy": "FakeBreakout",
            "trend": foundations.get("trend_detected", "N"),
            "founds": {
                k: (v if isinstance(v, bool) else str(v))
                for k, v in foundations.items()
            },
        }
        return self._create_signal(
            symbol,
            reversed_direction,
            new_trigger_price,
            new_sl_price,
            new_tp_price_rounded,
            mode=OrderMode.MARKET,
            details=details,
            risk_pct=risk_pct,
        )


try:
    from bot_module.ml_strategy import OnlineAgentStrategy

    ML_STRATEGY_CLASS = OnlineAgentStrategy
except ImportError:
    logger.warning("OnlineAgentStrategy could not be imported.")
    ML_STRATEGY_CLASS = None  # pragma: no cover

ALLOWED_DEFAULT_STRATEGIES = ["VisualBuilderStrategy", "CompassStrategy"]

STRATEGIES: Dict[str, Type[BaseStrategy]] = {
    cls.NAME: cls
    for cls in BaseStrategy.__subclasses__()
    if hasattr(cls, "NAME")
    and cls is not ML_STRATEGY_CLASS
    and cls.NAME in ALLOWED_DEFAULT_STRATEGIES
}

if (
    ML_STRATEGY_CLASS
    and hasattr(ML_STRATEGY_CLASS, "NAME")
    and ML_STRATEGY_CLASS.NAME in ALLOWED_DEFAULT_STRATEGIES
):
    if ML_STRATEGY_CLASS.NAME in STRATEGIES:
        logger.warning(
            f"Strategy name '{ML_STRATEGY_CLASS.NAME}' from ml_strategy.py might conflict."
        )  # pragma: no cover
    STRATEGIES[ML_STRATEGY_CLASS.NAME] = ML_STRATEGY_CLASS
    logger.debug(f"Explicitly added '{ML_STRATEGY_CLASS.NAME}' to STRATEGIES registry.")
else:
    logger.debug(
        "ML_STRATEGY_CLASS not available, has no NAME, or not in allowed list."
    )  # pragma: no cover

# Genetic Strategy Adapter Registration
try:
    from bot_module.genetic_adapter import GeneticCompatibleStrategy

    if GeneticCompatibleStrategy.NAME in STRATEGIES:
        logger.warning(
            f"Overwriting strategy {GeneticCompatibleStrategy.NAME} with adapter version."
        )
    STRATEGIES[GeneticCompatibleStrategy.NAME] = GeneticCompatibleStrategy
    logger.info(
        f"Registered GeneticCompatibleStrategy as '{GeneticCompatibleStrategy.NAME}'"
    )
except ImportError as e:
    logger.warning(f"Could not import GeneticCompatibleStrategy: {e}")

_strategy_instances: Dict[str, BaseStrategy] = {}


def get_strategy_instance(strategy_name: str) -> Optional[BaseStrategy]:
    instance = _strategy_instances.get(strategy_name)
    if instance:
        return instance
    strategy_class = STRATEGIES.get(strategy_name)
    if strategy_class:
        logger.debug(f"Instantiating shared strategy '{strategy_name}'...")
        try:
            instance = strategy_class()
            _strategy_instances[strategy_name] = instance
            logger.info(f"Shared instance created for '{strategy_name}'.")
            return instance
        except Exception as e:
            logger.error(
                f"Error instantiating shared strategy '{strategy_name}': {e}",
                exc_info=True,
            )
    else:
        logger.warning(
            f"Strategy class '{strategy_name}' not found in STRATEGIES registry for shared instance. Available: {list(STRATEGIES.keys())}"
        )
    return None


def create_strategy_instance(
    strategy_name: str,
    params: Optional[Dict[str, Any]] = None,
    contract_id: Optional[str] = None,
) -> Optional[BaseStrategy]:
    strategy_class = STRATEGIES.get(strategy_name)
    if strategy_class:
        logger.debug(
            f"Creating new instance for strategy '{strategy_name}', contract_id: {contract_id}, params: {params}"
        )
        try:
            instance = strategy_class(params=params, contract_id=contract_id)
            logger.info(
                f"New instance created for '{strategy_name}' (contract_id: {contract_id}). Enabled: {instance.enabled}"
            )
            return instance
        except Exception as e:
            logger.error(
                f"Error creating new instance for strategy '{strategy_name}' (contract_id: {contract_id}): {e}",
                exc_info=True,
            )
            return None
    else:
        logger.warning(
            f"Strategy class '{strategy_name}' not found in STRATEGIES registry for new instance."
        )
        return None


async def main_test_strategy():  # pragma: no cover
    logger.info("Running strategy standalone test block...")
    strat_names_to_test = list(STRATEGIES.keys())
    for strat_name in strat_names_to_test:
        instance = get_strategy_instance(strat_name)
        if instance:
            print(f"\n--- Instance: {strat_name} ---")
            print(
                f"Enabled by default from config: {instance._get_param('enabled', False)}"
            )
            print(
                f"Candle TF from config: {instance._get_param('candle_timeframe', 'N/A')}"
            )
            print(f"Required data: {instance.required_data_types}")
            mock_pair_info = {
                "symbol": "TESTUSDT",
                "current_candle_index": 50,
                "atr": 0.01,
                "tick_size": 0.00001,
                "last_price": 100.0,
                "SMA_10": 99.0,
                "SMA_50": 98.0,
                "RSI_14": 55.0,
                "relative_volume": 3.0,
                "natr": 1.5,
            }
            closes = list(np.linspace(100.5, 100.0, 5)) + list(
                np.random.rand(55) * 10 + 95
            )
            mock_kline_data = {
                "open_time": [
                    pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=i)
                    for i in range(60, 0, -1)
                ],
                "open": np.random.rand(60) * 10 + 95,
                "high": np.random.rand(60) * 5 + 100,
                "low": np.random.rand(60) * 5 + 90,
                "close": closes,
                "volume": np.random.rand(60) * 1000,
            }
            mock_df_1m = pd.DataFrame(mock_kline_data).set_index("open_time")
            mock_depth_data = {
                "lastUpdateId": 123456,
                "bids": [
                    [
                        f"{99.98 - i * 0.01:.2f}",
                        f"{10 + i * 2 + (500000 / 99.9 if i == 2 else 0):.1f}",
                    ]
                    for i in range(10)
                ],
                "asks": [
                    [f"{100.02 + i * 0.01:.2f}", f"{10 + i * 2:.1f}"] for i in range(10)
                ],
            }
            mock_market_data = {
                "kline_1m": mock_df_1m,
                "depth": mock_depth_data,
                "kline_1d": mock_df_1m.resample("1D").agg(
                    {
                        "open": "first",
                        "high": "max",
                        "low": "min",
                        "close": "last",
                        "volume": "sum",
                    }
                ),
                "kline_1h": mock_df_1m.resample("1h").agg(
                    {
                        "open": "first",
                        "high": "max",
                        "low": "min",
                        "close": "last",
                        "volume": "sum",
                    }
                ),
                "kline_4h": mock_df_1m.resample("4h").agg(
                    {
                        "open": "first",
                        "high": "max",
                        "low": "min",
                        "close": "last",
                        "volume": "sum",
                    }
                ),
            }
            foundations = instance.check_foundations(mock_pair_info, mock_market_data)
            print("Foundation check (mocked data):")
            for f_key, f_val in foundations.items():
                if isinstance(f_val, OrderbookAnalysisResult):
                    print(
                        f"  {f_key}: Support={f_val.nearest_support}, Resistance={f_val.nearest_resistance}, NearSup={f_val.is_price_near_support}, NearRes={f_val.is_price_near_resistance}, ApprSup={f_val.is_price_approaching_support}, ApprRes={f_val.is_price_approaching_resistance}"
                    )
                else:
                    print(f"  {f_key}: {f_val}")
            if strat_name in ["ReverseVolumeBreakout", "ReverseFakeBreakout"]:
                print(
                    f"Reverse SL to TP Ratio: {instance._get_param('reverse_sl_to_tp_ratio', 'N/A')}"
                )
        else:
            print(f"Could not get instance for {strat_name}")


if __name__ == "__main__":  # pragma: no cover
    if not logging.getLogger("bot_module").hasHandlers():
        log_formatter = logging.Formatter(
            config.LOG_FORMAT
            if hasattr(config, "LOG_FORMAT")
            else "%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s"
        )
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(log_formatter)
        stream_handler.setLevel(logging.DEBUG)
        logging.getLogger("bot_module").addHandler(stream_handler)
        logging.getLogger("bot_module").setLevel(logging.DEBUG)
    logger.info("Running strategy.py standalone test...")
    asyncio.run(main_test_strategy())
