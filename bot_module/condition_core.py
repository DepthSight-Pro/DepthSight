# bot_module/condition_core.py
"""
A unified module for evaluating strategy conditions.
Used by both FastVectorBacktester (vectorized) and VisualBuilderStrategy (scalar).

Principles:
1. All evaluate_*_vectorized functions return pd.Series of boolean values
2. normalize_condition_type() ensures backward compatibility with genetic types
3. Functions accept the minimum necessary context (df, signals, params)
"""

import logging
from typing import Dict, Any, Tuple, Optional
import pandas as pd

logger = logging.getLogger("bot_module.condition_core")

# =============================================================================
# TYPE ALIASES - mapping of genetic names to canonical ones
# =============================================================================

CONDITION_TYPE_ALIASES: Dict[str, str] = {
    # Genetic names -> Canonical
    "stoch_condition": "stochastic_condition",
    "bb_condition": "bollinger_bands_condition",
    # Canonical remain as is
    "stochastic_condition": "stochastic_condition",
    "bollinger_bands_condition": "bollinger_bands_condition",
    "macd_condition": "macd_condition",
    "ma_cross_condition": "ma_cross_condition",
    "rsi_condition": "rsi_condition",
    "trend_direction": "trend_direction",
    "time_filter": "time_filter",
    "natr_filter": "natr_filter",
    "adx_filter": "adx_filter",
    "trend_filter": "trend_filter",
    "value_comparison": "value_comparison",
    "price_condition": "value_comparison",
    "tape_condition": "tape_condition",
    "volatility_filter": "volatility_filter",
    "trading_session": "trading_session",
    "volume_confirmation": "volume_confirmation",
    "rel_vol_filter": "rel_vol_filter",
    "market_activity": "market_activity",
    "price_consolidation": "price_consolidation",
    "btc_state_filter": "btc_state_filter",
    "open_interest": "open_interest",
    "correlation": "correlation",
}


def normalize_condition_type(condition_type: str) -> str:
    """
    Normalizes the condition type to a canonical form.
    Ensures backward compatibility with genetic strategies.
    """
    return CONDITION_TYPE_ALIASES.get(condition_type, condition_type)


# =============================================================================
# PURE EVALUATION LOGIC - evaluation logic functions for scalar values
# Used in strategy.py to eliminate code duplication
# =============================================================================


def evaluate_stochastic_logic(
    k0: float,
    d0: float,
    k1: Optional[float],
    d1: Optional[float],
    operator: str,
    threshold: float,
    line: str = "k",
) -> bool:
    """
    Pure logic for Stochastic evaluation based on pre-calculated values.

    Args:
        k0: Current %K value
        d0: Current %D value
        k1: Previous %K value (for cross)
        d1: Previous %D value (for cross)
        operator: 'gt', 'lt', 'cross_above', 'cross_below'
        threshold: Threshold value
        line: 'k' or 'd' - which line to check
    """
    check_val = k0 if line == "k" else d0

    if operator == "gt":
        return check_val > threshold
    elif operator == "lt":
        return check_val < threshold
    elif operator == "cross_above" and k1 is not None and d1 is not None:
        return (k0 > d0) and (k1 <= d1)
    elif operator == "cross_below" and k1 is not None and d1 is not None:
        return (k0 < d0) and (k1 >= d1)

    return False


def evaluate_bollinger_logic(
    close: float,
    lower: Optional[float],
    upper: Optional[float],
    width: Optional[float],
    check_type: str,
    width_threshold: float = 0.01,
) -> bool:
    """
    Pure logic for Bollinger Bands evaluation.

    Args:
        close: Current closing price
        lower: Lower BB band
        upper: Upper BB band
        width: BB width (bandwidth)
        check_type: 'price_below_lower', 'price_above_upper', 'width_gt', 'width_lt'
        width_threshold: Width threshold
    """
    if check_type == "price_below_lower" and lower is not None:
        return close < lower
    elif check_type == "price_above_upper" and upper is not None:
        return close > upper
    elif check_type == "width_gt" and width is not None:
        return width > (width_threshold * 100)
    elif check_type == "width_lt" and width is not None:
        return width < (width_threshold * 100)

    return False


def evaluate_comparison_logic(
    left: float,
    right: float,
    left_prev: Optional[float],
    right_prev: Optional[float],
    operator: str,
) -> bool:
    """
    Pure logic for value comparison.

    Args:
        left: Left operand (current)
        right: Right operand (current)
        left_prev: Left operand (previous) for cross
        right_prev: Right operand (previous) for cross
        operator: 'gt', 'lt', 'gte', 'lte', 'cross_above', 'cross_below'
    """
    if operator == "gt":
        return left > right
    elif operator == "lt":
        return left < right
    elif operator == "gte":
        return left >= right
    elif operator == "lte":
        return left <= right
    elif operator == "cross_above" and left_prev is not None and right_prev is not None:
        return (left > right) and (left_prev <= right_prev)
    elif operator == "cross_below" and left_prev is not None and right_prev is not None:
        return (left < right) and (left_prev >= right_prev)

    return False


def evaluate_rsi_logic(rsi_value: float, operator: str, threshold: float) -> bool:
    """
    Pure logic for RSI evaluation.
    """
    if operator == "gt":
        return rsi_value > threshold
    elif operator == "lt":
        return rsi_value < threshold
    elif operator == "gte":
        return rsi_value >= threshold
    elif operator == "lte":
        return rsi_value <= threshold
    return False


def evaluate_macd_logic(
    macd: float,
    signal: Optional[float],
    macd_prev: Optional[float],
    signal_prev: Optional[float],
    condition_type: str,
) -> bool:
    """
    Pure logic for MACD evaluation.

    condition_type: 'crossover', 'macd_cross_above_signal', 'macd_cross_below_signal',
                   'hist_gt_zero', 'hist_lt_zero', 'value_above', 'value_below'
    """
    if condition_type in ("crossover", "macd_cross_above_signal"):
        if signal is not None and macd_prev is not None and signal_prev is not None:
            return (macd > signal) and (macd_prev <= signal_prev)
    elif condition_type == "macd_cross_below_signal":
        if signal is not None and macd_prev is not None and signal_prev is not None:
            return (macd < signal) and (macd_prev >= signal_prev)
    elif condition_type in ("hist_gt_zero", "value_above"):
        return macd > 0
    elif condition_type in ("hist_lt_zero", "value_below"):
        return macd < 0
    return False


def evaluate_adx_logic(
    adx_value: float, threshold: float, operator: str = "gt"
) -> bool:
    """
    Pure logic for ADX evaluation.
    """
    if operator == "gt":
        return adx_value > threshold
    return adx_value < threshold


def evaluate_ma_cross_logic(
    fast_ma: float,
    slow_ma: float,
    fast_ma_prev: Optional[float],
    slow_ma_prev: Optional[float],
    operator: str = "crosses_above",
) -> bool:
    """
    Pure logic for MA crossover.

    operator: 'crosses_above', 'crosses_below', 'above', 'below'
    """
    if (
        operator == "crosses_above"
        and fast_ma_prev is not None
        and slow_ma_prev is not None
    ):
        return (fast_ma > slow_ma) and (fast_ma_prev <= slow_ma_prev)
    elif (
        operator == "crosses_below"
        and fast_ma_prev is not None
        and slow_ma_prev is not None
    ):
        return (fast_ma < slow_ma) and (fast_ma_prev >= slow_ma_prev)
    elif operator == "above":
        return fast_ma > slow_ma
    elif operator == "below":
        return fast_ma < slow_ma
    return False


def evaluate_trend_direction_logic(
    sma_fast: Optional[float],
    sma_slow: Optional[float],
    rsi: Optional[float],
    rsi_lower_bound: float,
    rsi_upper_bound: float,
    required_trend: str,
) -> bool:
    """
    Pure logic for determining trend direction.

    required_trend: 'long', 'short', 'any_trend', 'flat'
    """
    if sma_fast is None or sma_slow is None:
        return False

    rsi_val = rsi if rsi is not None else 50  # neutral

    is_long = (sma_fast > sma_slow) and (rsi_val > rsi_lower_bound)
    is_short = (sma_fast < sma_slow) and (rsi_val < rsi_upper_bound)

    req = str(required_trend).lower()
    if "long" in req:
        return is_long
    elif "short" in req:
        return is_short
    elif "any" in req:
        return is_long or is_short
    elif "flat" in req:
        return not (is_long or is_short)

    return is_long  # default


def evaluate_time_filter_logic(
    current_hour: int, start_hour: int, end_hour: int, mode: str = "include"
) -> bool:
    """
    Pure logic for the time filter.
    """
    if start_hour < end_hour:
        in_range = start_hour <= current_hour < end_hour
    else:
        in_range = (current_hour >= start_hour) or (current_hour < end_hour)

    return in_range if mode == "include" else not in_range


def evaluate_natr_logic(
    natr_value: float, threshold: float, operator: str = "gt"
) -> bool:
    """
    Pure logic for the NATR filter.
    """
    if operator == "gt":
        return natr_value > threshold
    return natr_value < threshold


def evaluate_tape_logic(metric_value: float, threshold: float, operator: str) -> bool:
    """
    Pure logic for the tape condition.
    """
    if operator == "gt":
        return metric_value > threshold
    elif operator == "lt":
        return metric_value < threshold
    elif operator == "gte":
        return metric_value >= threshold
    elif operator == "lte":
        return metric_value <= threshold
    return False


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _get_series_from_context(
    col_name: str, main_df: pd.DataFrame, signals_df: pd.DataFrame
) -> Optional[pd.Series]:
    """Gets a series from main_df or signals_df."""
    if col_name in main_df.columns:
        return main_df[col_name]
    if col_name in signals_df.columns:
        return signals_df[col_name]
    return None


# =============================================================================
# VECTORIZED EVALUATORS - return pd.Series of boolean values
# =============================================================================


def evaluate_time_filter_vectorized(
    index: pd.DatetimeIndex, start_hour: int, end_hour: int, mode: str = "include"
) -> pd.Series:
    """
    Time of day filter.

    Args:
        index: DatetimeIndex of the data
        start_hour: Start hour (UTC)
        end_hour: End hour (UTC)
        mode: 'include' or 'exclude'

    Returns:
        pd.Series of boolean values
    """
    if start_hour == 0 and end_hour == 0:
        return pd.Series(True, index=index)

    hours = index.hour
    if start_hour < end_hour:
        in_range = (hours >= start_hour) & (hours < end_hour)
    else:
        in_range = (hours >= start_hour) | (hours < end_hour)

    return in_range if mode == "include" else ~in_range


def evaluate_trend_filter_vectorized(
    main_df: pd.DataFrame, signals_df: pd.DataFrame, indicator: str, threshold: float
) -> pd.Series:
    """
    Trend filter (ADX or SMA).
    """
    if indicator == "ADX":
        col = "ADX_14"
        series = _get_series_from_context(col, main_df, signals_df)
        if series is None:
            return pd.Series(False, index=main_df.index)
        return series > threshold
    else:
        col = f"SMA_{int(threshold)}"
        series = _get_series_from_context(col, main_df, signals_df)
        if series is None:
            return pd.Series(False, index=main_df.index)
        return main_df["close"] > series


def evaluate_volatility_filter_vectorized(
    main_df: pd.DataFrame, value: float, operator: str = "gt"
) -> pd.Series:
    """
    Volatility filter: (High-Low)/Close.
    """
    vol = (main_df["high"] - main_df["low"]) / main_df["close"]
    if operator == "lt":
        return vol < value
    return vol > value


def evaluate_natr_filter_vectorized(
    main_df: pd.DataFrame,
    signals_df: pd.DataFrame,
    period: int,
    value: float,
    operator: str = "gt",
) -> pd.Series:
    """
    NATR filter.
    """
    col = f"NATR_{period}"
    series = _get_series_from_context(col, main_df, signals_df)
    if series is None:
        return pd.Series(False, index=main_df.index)

    if operator == "gt":
        return series > value
    return series < value


def evaluate_adx_filter_vectorized(
    main_df: pd.DataFrame,
    signals_df: pd.DataFrame,
    period: int,
    threshold: float,
    operator: str = "gt",
) -> pd.Series:
    """
    ADX filter.
    """
    col = f"ADX_{period}"
    series = _get_series_from_context(col, main_df, signals_df)
    if series is None:
        return pd.Series(False, index=main_df.index)

    if operator == "gt":
        return series > threshold
    return series < threshold


def evaluate_ma_cross_vectorized(
    main_df: pd.DataFrame,
    signals_df: pd.DataFrame,
    fast_period: int,
    slow_period: int,
    direction: str = "crosses_above",
) -> pd.Series:
    """
    MA Crossover (EMA fast crosses above EMA slow).
    """
    f_col = f"EMA_{fast_period}"
    s_col = f"EMA_{slow_period}"

    ema_fast = _get_series_from_context(f_col, main_df, signals_df)
    ema_slow = _get_series_from_context(s_col, main_df, signals_df)

    if ema_fast is None or ema_slow is None:
        return pd.Series(False, index=main_df.index)

    normalized_direction = str(direction or "crosses_above").lower()
    if normalized_direction in {"below", "cross_below", "crosses_below"}:
        return (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))

    return (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))


def evaluate_bollinger_vectorized(
    main_df: pd.DataFrame,
    signals_df: pd.DataFrame,
    period: int,
    std_dev: float,
    check_type: str,
    width_value: float = 0.01,
) -> pd.Series:
    """
    Bollinger Bands condition.

    check_type: 'price_below_lower', 'price_above_upper', 'width_gt', 'width_lt'
    """
    all_cols = list(main_df.columns) + list(signals_df.columns)
    lower_col = next((c for c in all_cols if c.startswith(f"BBL_{period}")), None)
    upper_col = next((c for c in all_cols if c.startswith(f"BBU_{period}")), None)
    width_col = next((c for c in all_cols if c.startswith(f"BBB_{period}")), None)

    if not lower_col:
        return pd.Series(False, index=main_df.index)

    lower = _get_series_from_context(lower_col, main_df, signals_df)
    upper = (
        _get_series_from_context(upper_col, main_df, signals_df) if upper_col else None
    )
    width = (
        _get_series_from_context(width_col, main_df, signals_df) if width_col else None
    )

    if check_type == "price_below_lower":
        return main_df["close"] < lower
    elif check_type == "price_above_upper" and upper is not None:
        return main_df["close"] > upper
    elif check_type == "width_gt" and width is not None:
        return width > (width_value * 100)
    elif check_type == "width_lt" and width is not None:
        return width < (width_value * 100)

    return pd.Series(False, index=main_df.index)


def evaluate_stochastic_vectorized(
    main_df: pd.DataFrame,
    signals_df: pd.DataFrame,
    k_period: int,
    d_period: int,
    smooth_k: int,
    operator: str,
    value: float,
    line: str = "k",
) -> pd.Series:
    """
    Stochastic condition.

    operator: 'gt', 'lt', 'cross_above', 'cross_below'
    line: 'k' or 'd'
    """
    k_col = f"STOCHk_{k_period}_{d_period}_{smooth_k}"
    d_col = f"STOCHd_{k_period}_{d_period}_{smooth_k}"

    stoch_k = _get_series_from_context(k_col, main_df, signals_df)
    stoch_d = _get_series_from_context(d_col, main_df, signals_df)

    if stoch_k is None:
        return pd.Series(False, index=main_df.index)

    check_series = stoch_k if line == "k" else stoch_d

    if operator == "gt":
        return check_series > value
    elif operator == "lt":
        return check_series < value
    elif operator == "cross_above" and stoch_d is not None:
        return (stoch_k > stoch_d) & (stoch_k.shift(1) <= stoch_d.shift(1))
    elif operator == "cross_below" and stoch_d is not None:
        return (stoch_k < stoch_d) & (stoch_k.shift(1) >= stoch_d.shift(1))

    return pd.Series(False, index=main_df.index)


def evaluate_rsi_vectorized(
    main_df: pd.DataFrame,
    signals_df: pd.DataFrame,
    period: int,
    operator: str,
    value: float,
) -> pd.Series:
    """
    RSI condition.
    """
    col = f"RSI_{period}"
    rsi = _get_series_from_context(col, main_df, signals_df)

    if rsi is None:
        return pd.Series(False, index=main_df.index)

    if operator == "gt":
        return rsi > value
    return rsi < value


def evaluate_macd_vectorized(
    main_df: pd.DataFrame,
    signals_df: pd.DataFrame,
    fast_period: int,
    slow_period: int,
    signal_period: int,
    condition_type: str,
) -> pd.Series:
    """
    MACD condition.

    condition_type: 'crossover', 'macd_cross_above_signal', 'macd_cross_below_signal',
                   'hist_gt_zero', 'hist_lt_zero', 'value_above', 'value_below'
    """
    # Ensure fast < slow
    fast, slow = min(fast_period, slow_period), max(fast_period, slow_period)

    macd_col = f"MACD_{fast}_{slow}_{signal_period}"
    signal_col = f"MACDs_{fast}_{slow}_{signal_period}"
    # Try both common naming conventions for histogram
    hist_col = f"MACD_hist_{fast}_{slow}_{signal_period}"
    hist_col_alt = f"MACDh_{fast}_{slow}_{signal_period}"

    macd = _get_series_from_context(macd_col, main_df, signals_df)
    signal = _get_series_from_context(signal_col, main_df, signals_df)
    hist = _get_series_from_context(hist_col, main_df, signals_df)
    if hist is None:
        hist = _get_series_from_context(hist_col_alt, main_df, signals_df)

    if macd is None:
        return pd.Series(False, index=main_df.index)

    if condition_type in ("crossover", "macd_cross_above_signal"):
        if signal is not None:
            return (macd > signal) & (macd.shift(1) <= signal.shift(1))
    elif condition_type == "macd_cross_below_signal":
        if signal is not None:
            return (macd < signal) & (macd.shift(1) >= signal.shift(1))
    elif condition_type == "hist_gt_zero":
        val = hist if hist is not None else (macd - signal)
        return val > 0
    elif condition_type == "hist_lt_zero":
        val = hist if hist is not None else (macd - signal)
        return val < 0
    elif condition_type == "value_above":
        return macd > 0
    elif condition_type == "value_below":
        return macd < 0

    return pd.Series(False, index=main_df.index)


def evaluate_trend_direction_vectorized(
    main_df: pd.DataFrame,
    signals_df: pd.DataFrame,
    sma_fast_period: int,
    sma_slow_period: int,
    rsi_period: int,
    rsi_lower_bound: float,
    rsi_upper_bound: float,
    required_trend: str,
) -> pd.Series:
    """
    Trend direction (SMA Cross + RSI).

    required_trend: 'long', 'short', 'any_trend', 'flat'
    """
    f_col = f"SMA_{sma_fast_period}"
    s_col = f"SMA_{sma_slow_period}"
    r_col = f"RSI_{rsi_period}"

    sma_fast = _get_series_from_context(f_col, main_df, signals_df)
    sma_slow = _get_series_from_context(s_col, main_df, signals_df)
    rsi = _get_series_from_context(r_col, main_df, signals_df)

    if sma_fast is None:
        return pd.Series(False, index=main_df.index)

    is_long = (sma_fast > sma_slow) & (rsi > rsi_lower_bound)
    is_short = (sma_fast < sma_slow) & (rsi < rsi_upper_bound)

    req = str(required_trend).lower()
    if "long" in req:
        return is_long
    elif "short" in req:
        return is_short
    elif "any" in req:
        return is_long | is_short
    elif "flat" in req:
        return ~(is_long | is_short)

    return is_long  # default


def evaluate_tape_condition_vectorized(
    main_df: pd.DataFrame,
    metric: str,
    window_sec: int,
    operator: str,
    threshold: float,
    avg_lookback_sec: int = 60,
) -> pd.Series:
    """
    Condition on the tape (time and sales).

    metric: 'delta_volume', 'delta_count', 'ratio_volume', 'ratio_count',
            'accel_volume', 'accel_count', 'total_volume', 'total_count'
    """
    col = None
    if metric == "delta_volume":
        col = f"tape_delta_volume_usd_{window_sec}s"
    elif metric == "delta_count":
        col = f"tape_delta_count_{window_sec}s"
    elif metric == "ratio_volume":
        col = f"tape_buy_sell_ratio_volume_{window_sec}s"
    elif metric == "ratio_count":
        col = f"tape_buy_sell_ratio_count_{window_sec}s"
    elif metric == "accel_volume":
        col = f"tape_accel_mult_volume_{window_sec}s_{avg_lookback_sec}s"
    elif metric == "accel_count":
        col = f"tape_accel_mult_count_{window_sec}s_{avg_lookback_sec}s"
    elif metric == "total_volume":
        col = f"tape_total_volume_usd_{window_sec}s"
    elif metric == "total_count":
        col = f"tape_total_count_{window_sec}s"
    else:
        return pd.Series(False, index=main_df.index)

    # Column search (may have _x, _y suffixes)
    actual_col = None
    for c in [col, f"{col}_x", f"{col}_y"]:
        if c in main_df.columns:
            actual_col = c
            break

    if actual_col is None:
        # If the column is missing, return True (neutral result)
        return pd.Series(True, index=main_df.index)

    val_series = main_df[actual_col]

    if operator == "gt":
        return val_series > threshold
    elif operator == "lt":
        return val_series < threshold
    elif operator == "gte":
        return val_series >= threshold
    elif operator == "lte":
        return val_series <= threshold

    return pd.Series(False, index=main_df.index)


def evaluate_value_comparison_vectorized(
    main_df: pd.DataFrame,
    signals_df: pd.DataFrame,
    left_operand: Dict[str, Any],
    right_operand: Dict[str, Any],
    operator: str,
) -> pd.Series:
    """
    Value comparison (dynamic).

    operand: {source: 'candle'|'indicator'|'constant'|'value', key: str}
    operator: 'gt', 'lt', 'gte', 'lte', 'cross_above', 'cross_below'
    """

    def get_series(operand: Dict[str, Any]) -> pd.Series:
        src = operand.get("source")
        key = operand.get("key")
        value = operand.get("value", key)

        if src == "candle":
            return (
                main_df[key]
                if key in main_df.columns
                else pd.Series(0, index=main_df.index)
            )
        if src == "indicator":
            series = _get_series_from_context(key, main_df, signals_df)
            return series if series is not None else pd.Series(0, index=main_df.index)
        if src in {"constant", "value"}:
            try:
                return pd.Series(float(value), index=main_df.index)
            except (TypeError, ValueError):
                return pd.Series(0, index=main_df.index)

        return pd.Series(0, index=main_df.index)

    left = get_series(left_operand)
    right = get_series(right_operand)

    if operator == "gt":
        return left > right
    elif operator == "lt":
        return left < right
    elif operator == "gte":
        return left >= right
    elif operator == "lte":
        return left <= right
    elif operator == "cross_above":
        return (left > right) & (left.shift(1) <= right.shift(1))
    elif operator == "cross_below":
        return (left < right) & (left.shift(1) >= right.shift(1))

    return pd.Series(False, index=main_df.index)


# =============================================================================
# SCALAR WRAPPERS - for use in strategy.py (extract the last value)
# =============================================================================


def evaluate_stochastic_scalar(
    df: pd.DataFrame, params: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """
    Scalar version for VisualBuilderStrategy.
    Calculates Stochastic on the provided DataFrame and returns the result of the last bar.
    """
    k_per = int(params.get("k_period", 14))
    d_per = int(params.get("d_period", 3))
    smooth = int(params.get("smooth_k", 3))
    operator = params.get("operator", "gt")
    value = float(params.get("value", 80))
    line = params.get("line", "k")

    if df is None or df.empty or len(df) < k_per + 5:
        return False, {"error": "Not enough data"}

    try:
        slice_df = df.tail(k_per + 20).copy()
        stoch = slice_df.ta.stoch(k=k_per, d=d_per, smooth_k=smooth)

        if stoch is None or stoch.empty:
            return False, {"error": "Stochastic calculation failed"}

        cols = stoch.columns
        k_col = next((c for c in cols if c.startswith("STOCHk")), None)
        d_col = next((c for c in cols if c.startswith("STOCHd")), None)

        if k_col is None:
            return False, {"error": "STOCHk column not found"}

        k0, k1 = float(stoch[k_col].iloc[-1]), float(stoch[k_col].iloc[-2])
        d0, d1 = (
            float(stoch[d_col].iloc[-1]),
            float(stoch[d_col].iloc[-2]) if d_col else (0, 0),
        )

        check_val = k0 if line == "k" else d0

        result = False
        if operator == "gt":
            result = check_val > value
        elif operator == "lt":
            result = check_val < value
        elif operator == "cross_above":
            result = (k0 > d0) and (k1 <= d1)
        elif operator == "cross_below":
            result = (k0 < d0) and (k1 >= d1)

        return bool(result), {
            "k": k0,
            "d": d0,
            "k_period": k_per,
            "d_period": d_per,
            "slowing": smooth,
        }

    except Exception as e:
        return False, {"error": str(e)}


def evaluate_bollinger_scalar(
    df: pd.DataFrame, params: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """
    Scalar version for VisualBuilderStrategy.
    """
    period = int(params.get("period", 20))
    std_dev = float(params.get("std_dev", 2.0))
    check_type = params.get("check_type", "price_below_lower")
    width_value = float(params.get("width_value", 0.01))

    if df is None or df.empty or len(df) < period + 5:
        return False, {"error": "Not enough data"}

    try:
        slice_df = df.tail(period + 5).copy()
        bb = slice_df.ta.bbands(length=period, std=std_dev)

        if bb is None or bb.empty:
            return False, {"error": "BB calculation failed"}

        cols = bb.columns
        lower_col = next((c for c in cols if c.startswith("BBL")), None)
        upper_col = next((c for c in cols if c.startswith("BBU")), None)
        width_col = next((c for c in cols if c.startswith("BBB")), None)

        close = float(slice_df["close"].iloc[-1])
        lower = float(bb[lower_col].iloc[-1])
        upper = float(bb[upper_col].iloc[-1]) if upper_col else 0
        width = float(bb[width_col].iloc[-1]) if width_col else 0

        result = False
        if check_type == "price_below_lower":
            result = close < lower
        elif check_type == "price_above_upper":
            result = close > upper
        elif check_type == "width_gt":
            result = width > (width_value * 100)
        elif check_type == "width_lt":
            result = width < (width_value * 100)

        return bool(result), {
            "close": close,
            "lower": lower,
            "upper": upper,
            "width": width,
            "check": check_type,
            "period": period,
            "std_dev": std_dev,
        }

    except Exception as e:
        return False, {"error": str(e)}


def evaluate_ma_cross_scalar(
    df: pd.DataFrame, params: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """
    Scalar version for VisualBuilderStrategy.
    """
    fast_p = int(params.get("fast_period", 9))
    slow_p = int(params.get("slow_period", 21))

    if df is None or df.empty:
        return False, {"error": "No data"}

    try:
        slice_df = df.tail(max(fast_p, slow_p) + 5).copy()
        ema_fast = slice_df.ta.ema(length=fast_p)
        ema_slow = slice_df.ta.ema(length=slow_p)

        if ema_fast is None or ema_slow is None:
            return False, {"error": "EMA calculation failed"}

        f0, f1 = float(ema_fast.iloc[-1]), float(ema_fast.iloc[-2])
        s0, s1 = float(ema_slow.iloc[-1]), float(ema_slow.iloc[-2])

        result = (f0 > s0) and (f1 <= s1)

        return bool(result), {
            "fast": f0,
            "slow": s0,
            "fast_period": fast_p,
            "slow_period": slow_p,
        }

    except Exception as e:
        return False, {"error": str(e)}


def evaluate_natr_scalar(
    df: pd.DataFrame, params: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """
    Scalar version of the NATR filter. Calculates NATR dynamically from the DataFrame.
    Formula: (high - low) / close * 100, then rolling mean.
    """
    period = int(params.get("period", 14))
    threshold = float(
        params.get("value", params.get("threshold", params.get("natr_threshold", 1.0)))
    )
    operator = params.get("operator", "gt")

    if df is None or df.empty:
        return False, {"error": "No data"}

    required_len = period
    if len(df) < required_len:
        return False, {
            "error": f"Not enough history for NATR (req {required_len}, got {len(df)})"
        }

    try:
        slice_df = df.tail(required_len).copy()
        # Scalper formula (as in genetic_adapter)
        percent_range = (
            (slice_df["high"] - slice_df["low"]) / slice_df["close"].replace(0, 1) * 100
        )
        natr_series = percent_range.rolling(window=period).mean()
        natr_val = float(natr_series.iloc[-1])

        if pd.isna(natr_val):
            return False, {"error": "NATR calculation resulted in NaN"}

        result = evaluate_natr_logic(natr_val, threshold, operator)

        return bool(result), {
            "natr": natr_val,
            "threshold": threshold,
            "operator": operator,
            "period": period,
        }

    except Exception as e:
        return False, {"error": str(e)}


def evaluate_adx_scalar(
    df: pd.DataFrame, params: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """
    Scalar version of the ADX filter. Calculates ADX dynamically from the DataFrame.
    """
    period = int(params.get("period", 14))
    threshold = float(params.get("threshold", 25))
    operator = params.get("operator", "gt")

    if df is None or df.empty:
        return False, {"error": "No data"}

    required_len = period * 3
    if len(df) < required_len:
        return False, {
            "error": f"Not enough history for ADX (req {required_len}, got {len(df)})"
        }

    try:
        slice_df = df.tail(required_len).copy()
        adx_df = slice_df.ta.adx(length=period)

        if adx_df is None or adx_df.empty:
            return False, {"error": "ADX calculation failed"}

        adx_col = next((c for c in adx_df.columns if c.startswith("ADX_")), None)
        if adx_col is None:
            return False, {"error": "ADX column not found"}

        adx_val = float(adx_df[adx_col].iloc[-1])

        if pd.isna(adx_val):
            return False, {"error": "ADX calculation resulted in NaN"}

        result = evaluate_adx_logic(adx_val, threshold, operator)

        return bool(result), {
            "adx": adx_val,
            "threshold": threshold,
            "operator": operator,
            "period": period,
        }

    except Exception as e:
        return False, {"error": str(e)}


def evaluate_macd_scalar(
    df: pd.DataFrame, params: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """
    Scalar version of the MACD condition. Calculates MACD dynamically from the DataFrame.
    """
    fast = int(params.get("fast_period", 12))
    slow = int(params.get("slow_period", 26))
    signal = int(params.get("signal_period", 9))
    condition = params.get("condition", params.get("condition_type", "hist_gt_zero"))

    if df is None or df.empty:
        return False, {"error": "No data"}

    required_len = slow + signal + 10
    if len(df) < required_len:
        return False, {
            "error": f"Not enough history for MACD (req {required_len}, got {len(df)})"
        }

    try:
        slice_df = df.tail(required_len).copy()
        macd_df = slice_df.ta.macd(fast=fast, slow=slow, signal=signal)

        if macd_df is None or macd_df.empty:
            return False, {"error": "MACD calculation failed"}

        macd_col = f"MACD_{fast}_{slow}_{signal}"
        signal_col = f"MACDs_{fast}_{slow}_{signal}"
        hist_col = f"MACDh_{fast}_{slow}_{signal}"

        m0 = float(macd_df[macd_col].iloc[-1])
        s0 = float(macd_df[signal_col].iloc[-1])
        m1 = float(macd_df[macd_col].iloc[-2])
        s1 = float(macd_df[signal_col].iloc[-2])
        hist = (
            float(macd_df[hist_col].iloc[-1])
            if hist_col in macd_df.columns
            else m0 - s0
        )

        # For histogram conditions, pass hist, otherwise macd line
        value_to_check = hist if "hist" in condition else m0
        result = evaluate_macd_logic(value_to_check, s0, m1, s1, condition)

        return bool(result), {
            "macd": m0,
            "signal": s0,
            "histogram": hist,
            "condition": condition,
            "fast_period": fast,
            "slow_period": slow,
            "signal_period": signal,
        }

    except Exception as e:
        return False, {"error": str(e)}


def evaluate_trend_direction_scalar(
    df: pd.DataFrame, params: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """
    Scalar version of Trend Direction. Calculates SMA and RSI dynamically.
    """
    fast_p = int(params.get("sma_fast_period", params.get("fast_period", 10)))
    slow_p = int(params.get("sma_slow_period", params.get("slow_period", 50)))
    rsi_p = int(params.get("rsi_period", 14))

    rsi_lower = float(params.get("rsi_lower_bound", 40))
    rsi_upper = float(params.get("rsi_upper_bound", 60))

    raw_direction = params.get("direction")
    required_trend = params.get("required_trend", "LONG")

    target_direction = "LONG"
    if raw_direction:
        target_direction = str(raw_direction).upper()
    elif required_trend:
        target_direction = str(required_trend).upper()

    if df is None or df.empty:
        return False, {"error": "No data"}

    required_len = slow_p + 10
    if len(df) < required_len:
        return False, {"error": f"Not enough data for SMA {slow_p}"}

    try:
        slice_df = df.tail(required_len).copy()

        sma_fast = slice_df.ta.sma(length=fast_p)
        sma_slow = slice_df.ta.sma(length=slow_p)
        rsi = slice_df.ta.rsi(length=rsi_p)

        if sma_fast is None or sma_slow is None or rsi is None:
            return False, {"error": "Indicator calculation failed"}

        f_val = float(sma_fast.iloc[-1])
        s_val = float(sma_slow.iloc[-1])
        r_val = float(rsi.iloc[-1])

        is_long_signal = (f_val > s_val) and (r_val > rsi_lower)
        is_short_signal = (f_val < s_val) and (r_val < rsi_upper)

        result = evaluate_trend_direction_logic(
            f_val, s_val, r_val, rsi_lower, rsi_upper, target_direction
        )

        return bool(result), {
            "sma_fast": f_val,
            "sma_slow": s_val,
            "rsi": r_val,
            "target": target_direction,
            "is_long": bool(is_long_signal),
            "is_short": bool(is_short_signal),
        }

    except Exception as e:
        return False, {"error": str(e)}


def evaluate_rsi_scalar(
    df: pd.DataFrame, params: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any]]:
    """
    Scalar version of the RSI condition. Calculates RSI dynamically from the DataFrame.
    """
    period = int(params.get("period", 14))
    operator = params.get("operator", "gt")
    value = float(params.get("value", 50))

    if df is None or df.empty:
        return False, {"error": "No data"}

    required_len = period
    if len(df) < required_len:
        return False, {
            "error": f"Not enough history for RSI (req {required_len}, got {len(df)})"
        }

    try:
        slice_df = df.tail(required_len).copy()
        rsi_series = slice_df.ta.rsi(length=period)

        if rsi_series is None or rsi_series.empty:
            return False, {"error": "RSI calculation failed"}

        rsi_val = float(rsi_series.iloc[-1])
        rsi_prev = float(rsi_series.iloc[-2]) if len(rsi_series) > 1 else None

        if pd.isna(rsi_val):
            return False, {"error": "RSI calculation resulted in NaN"}

        result = evaluate_rsi_logic(rsi_val, operator, value)

        # For cross operators
        if operator in ("cross_above", "cross_below") and rsi_prev is not None:
            if operator == "cross_above":
                result = (rsi_prev <= value) and (rsi_val > value)
            else:  # cross_below
                result = (rsi_prev >= value) and (rsi_val < value)

        return bool(result), {
            "rsi": rsi_val,
            "period": period,
            "operator": operator,
            "threshold": value,
        }

    except Exception as e:
        return False, {"error": str(e)}
