# bot_module/genetic_adapter.py

import logging
from typing import Dict, Tuple, Any
import pandas as pd

from .strategy import VisualBuilderStrategy

logger = logging.getLogger("bot_module.genetic_adapter")


class GeneticCompatibleStrategy(VisualBuilderStrategy):
    """
    Special adapter strategy for executing configurations,
    created by the genetic algorithm.
    """

    NAME = "GeneticStrategy"
    description = (
        "Adapter for genetic strategies with exact implementation of vector logic."
    )

    def __init__(self, params: Dict[str, Any] = None, contract_id: str = None):
        super().__init__(params, contract_id)

        self.condition_checkers = self.condition_checkers.copy()

        self.condition_checkers.update(
            {
                "time_filter": self._check_filter_time_genetic,
                "trend_filter": self._check_filter_trend_price_sma,
                "natr_filter": self._check_filter_natr_dynamic,
                "adx_filter": self._check_filter_adx_genetic,
                "ma_cross_condition": self._check_condition_ma_cross,
                "bb_condition": self._check_condition_bb,
                "stoch_condition": self._check_condition_stoch,
                "macd_condition": self._check_condition_macd_extended,
                "trend_direction": self._check_condition_trend_direction_genetic,  # Added
            }
        )

    def _check_filter_time_genetic(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        start = int(params.get("start_hour_utc", 0))
        end = int(params.get("end_hour_utc", 23))
        mode = params.get("mode", "include")

        current_dt = pair_info.get("timestamp_dt")
        if not current_dt:
            return True, {"warning": "No timestamp"}

        hour = current_dt.hour
        if start < end:
            in_range = start <= hour < end
        else:
            in_range = (hour >= start) or (hour < end)

        result = in_range if mode == "include" else not in_range
        return bool(result), {
            "current_hour": hour,
            "range": f"{start}-{end}",
            "mode": mode,
        }

    def _check_filter_trend_price_sma(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        # --- Check for indicator type (ADX or SMA) ---
        indicator_type = params.get("indicator", "SMA")

        # If it is ADX, redirect logic to ADX filter
        if indicator_type == "ADX":
            # ADX usually requires a period, but it might not be in trend_filter.
            # By default, use 14, and take the threshold from parameters.
            adx_params = {
                "period": 14,
                "threshold": params.get("threshold", 25),
                "operator": "gt",
            }
            # Call the existing ADX check method
            return self._check_filter_adx_genetic(
                pair_info, market_data, adx_params, context
            )

        # --- Standard SMA logic (if indicator != ADX) ---
        period = int(params.get("threshold", 50))
        candle_tf = pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")

        if df is None or df.empty:
            return False, {"error": "No data"}

        # Take the tail for acceleration
        slice_df = df.tail(period + 5).copy()
        sma_series = slice_df.ta.sma(close="close", length=period)

        if sma_series is None or sma_series.empty:
            return False, {"error": "SMA calc failed"}

        sma = sma_series.iloc[-1]
        close = df["close"].iloc[-1]

        result = close > sma
        return bool(result), {"close": float(close), f"SMA_{period}": float(sma)}

    def _check_filter_natr_dynamic(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        period = int(params.get("period", 14))
        operator = params.get("operator", "gt")
        threshold = float(params.get("value", 1.0))

        candle_tf = pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")

        if df is None or df.empty:
            return False, {"error": "No data"}

        required_len = period + 5
        if len(df) < required_len:
            return False, {
                "error": f"Not enough history for NATR (req {required_len}, got {len(df)})"
            }

        slice_df = df.tail(required_len).copy()

        # Scalper formula (like in vector)
        percent_range = (
            (slice_df["high"] - slice_df["low"]) / slice_df["close"].replace(0, 1) * 100
        )
        natr_series = percent_range.rolling(window=period).mean()
        natr_val = natr_series.iloc[-1]

        if pd.isna(natr_val):
            return False, {"error": "NATR resulted in NaN"}

        result = False
        if operator == "gt":
            result = natr_val > threshold
        elif operator == "lt":
            result = natr_val < threshold

        return bool(result), {
            "natr_val": float(natr_val),
            "threshold": threshold,
            "op": operator,
            "period": period,
        }

    def _check_filter_adx_genetic(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        period = int(params.get("period", 14))
        threshold = float(params.get("threshold", 25))
        operator = params.get("operator", "gt")

        # --- First look for a ready value in pair_info ---
        # DataConsumer (and our validator) pass it as 'ADX_14'
        adx_key = f"ADX_{period}"
        adx_val = None

        if adx_key in pair_info:
            adx_val = float(pair_info[adx_key])
        elif adx_key.lower() in pair_info:
            adx_val = float(pair_info[adx_key.lower()])

        # If not in pair_info, look in the DataFrame, but without recalculation (if column exists)
        if adx_val is None:
            candle_tf = pair_info.get("candle_timeframe", "1m")
            df = market_data.get(f"kline_{candle_tf}")
            if df is not None and not df.empty:
                if adx_key in df.columns:
                    adx_val = float(df[adx_key].iloc[-1])
                else:
                    # If the column does not exist, we have to calculate it.
                    # IMPORTANT: Take more history for ADX accuracy (was *2, now *10)
                    required_len = period * 10
                    slice_df = df.tail(required_len).copy()
                    try:
                        adx_df = slice_df.ta.adx(length=period)
                        if adx_df is not None and adx_key in adx_df.columns:
                            adx_val = float(adx_df[adx_key].iloc[-1])
                    except Exception:
                        pass

        if adx_val is None:
            return False, {"error": "ADX calc failed"}

        result = adx_val > threshold if operator == "gt" else adx_val < threshold

        return bool(result), {
            "adx": float(adx_val),
            "threshold": threshold,
            "period": period,
        }

    def _check_condition_ma_cross(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        fast_p = int(params.get("fast_period", 9))
        slow_p = int(params.get("slow_period", 21))

        candle_tf = pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")

        if df is None:
            return False, {"error": "No data"}

        slice_df = df.tail(max(fast_p, slow_p) + 5).copy()
        ema_fast = slice_df.ta.ema(length=fast_p)
        ema_slow = slice_df.ta.ema(length=slow_p)

        f0, f1 = ema_fast.iloc[-1], ema_fast.iloc[-2]
        s0, s1 = ema_slow.iloc[-1], ema_slow.iloc[-2]

        result = (f0 > s0) and (f1 <= s1)
        return bool(result), {
            "fast": float(f0),
            "slow": float(s0),
            "fast_period": fast_p,
            "slow_period": slow_p,
        }

    def _check_condition_bb(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        period = int(params.get("period", 20))
        std_dev = float(params.get("std_dev", 2.0))
        check_type = params.get("check_type", "price_below_lower")
        width_val = float(params.get("width_value", 0.01))

        candle_tf = pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")
        if df is None:
            return False, {"error": "No data"}

        slice_df = df.tail(period + 5).copy()
        bb = slice_df.ta.bbands(length=period, std=std_dev)

        if bb is None:
            return False, {"error": "BB calc failed"}

        cols = bb.columns
        lower_col = next((c for c in cols if c.startswith("BBL")), None)
        upper_col = next((c for c in cols if c.startswith("BBU")), None)
        width_col = next((c for c in cols if c.startswith("BBB")), None)

        close = slice_df["close"].iloc[-1]
        lower = bb[lower_col].iloc[-1]
        upper = bb[upper_col].iloc[-1]
        width = bb[width_col].iloc[-1]

        result = False
        if check_type == "price_below_lower":
            result = close < lower
        elif check_type == "price_above_upper":
            result = close > upper
        elif check_type == "width_gt":
            result = width > (width_val * 100)
        elif check_type == "width_lt":
            result = width < (width_val * 100)

        return bool(result), {
            "close": float(close),
            "lower": float(lower),
            "upper": float(upper),
            "width": float(width),
            "check": check_type,
            "period": period,
            "std_dev": std_dev,
        }

    def _check_condition_stoch(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        k_per = int(params.get("k_period", 14))
        d_per = int(params.get("d_period", 3))
        smooth = int(params.get("smooth_k", 3))
        operator = params.get("operator", "gt")
        val = float(params.get("value", 80))
        line = params.get("line", "k")

        candle_tf = pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")
        if df is None:
            return False, {"error": "No data"}

        slice_df = df.tail(k_per + 20).copy()
        stoch = slice_df.ta.stoch(k=k_per, d=d_per, smooth_k=smooth)
        if stoch is None:
            return False, {"error": "Stoch calc failed"}

        cols = stoch.columns
        k_col = next((c for c in cols if c.startswith("STOCHk")), None)
        d_col = next((c for c in cols if c.startswith("STOCHd")), None)

        k0, k1 = stoch[k_col].iloc[-1], stoch[k_col].iloc[-2]
        d0, d1 = stoch[d_col].iloc[-1], stoch[d_col].iloc[-2]

        check_val = k0 if line == "k" else d0

        result = False
        if operator == "gt":
            result = check_val > val
        elif operator == "lt":
            result = check_val < val
        elif operator == "cross_above":
            result = (k0 > d0) and (k1 <= d1)
        elif operator == "cross_below":
            result = (k0 < d0) and (k1 >= d1)

        # Include params for visualization to use exact same parameters
        return bool(result), {
            "k": float(k0),
            "d": float(d0),
            "k_period": k_per,
            "d_period": d_per,
            "slowing": smooth,
        }

    def _check_condition_macd_extended(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        fast = int(params.get("fast_period", 12))
        slow = int(params.get("slow_period", 26))
        signal = int(params.get("signal_period", 9))
        cond_type = params.get("condition_type", "crossover")
        value = float(params.get("value", 0.0))

        candle_tf = pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")
        if df is None:
            return False, {"error": "No data"}

        slice_df = df.tail(slow + signal + 10).copy()
        macd_df = slice_df.ta.macd(fast=fast, slow=slow, signal=signal)

        if macd_df is None:
            return False, {"error": "MACD calc failed"}

        macd_col = f"MACD_{fast}_{slow}_{signal}"
        signal_col = f"MACDs_{fast}_{slow}_{signal}"

        m0 = macd_df[macd_col].iloc[-1]
        s0 = macd_df[signal_col].iloc[-1]
        m1 = macd_df[macd_col].iloc[-2]
        s1 = macd_df[signal_col].iloc[-2]

        result = False
        if cond_type == "crossover":
            result = (m0 > s0) and (m1 <= s1)
        elif cond_type == "value_above":
            result = m0 > value
        elif cond_type == "value_below":
            result = m0 < value

        return bool(result), {
            "macd": float(m0),
            "signal": float(s0),
            "fast_period": fast,
            "slow_period": slow,
            "signal_period": signal,
        }

    def _check_condition_trend_direction_genetic(
        self, pair_info: Dict, market_data: Dict, params: Dict, context: Dict
    ) -> Tuple[bool, Dict]:
        fast_p = int(params.get("sma_fast_period") or params.get("fast_period") or 10)
        slow_p = int(params.get("sma_slow_period") or params.get("slow_period") or 50)
        rsi_p = int(params.get("rsi_period", 14))

        rsi_lower = float(params.get("rsi_lower_bound", 40))
        rsi_upper = float(params.get("rsi_upper_bound", 60))

        raw_direction = params.get("direction")
        required_trend = params.get("required_trend", "LONG").upper()

        target_direction = "LONG"
        if raw_direction:
            target_direction = raw_direction.upper()
        elif required_trend:
            target_direction = required_trend

        candle_tf = pair_info.get("candle_timeframe", "1m")
        df = market_data.get(f"kline_{candle_tf}")

        if df is None or df.empty:
            return False, {"error": "No data"}

        required_len = slow_p + 10
        if len(df) < required_len:
            return False, {"error": f"Not enough data for SMA {slow_p}"}

        slice_df = df.tail(required_len).copy()

        try:
            sma_fast_series = slice_df.ta.sma(length=fast_p)
            sma_slow_series = slice_df.ta.sma(length=slow_p)
            rsi_series = slice_df.ta.rsi(length=rsi_p)

            if sma_fast_series is None or sma_slow_series is None or rsi_series is None:
                return False, {"error": "Indicator calc failed"}

            f_val = sma_fast_series.iloc[-1]
            s_val = sma_slow_series.iloc[-1]
            r_val = rsi_series.iloc[-1]

        except Exception as e:
            return False, {"error": f"Calc error: {e}"}

        is_long_signal = (f_val > s_val) and (r_val > rsi_lower)
        is_short_signal = (f_val < s_val) and (r_val < rsi_upper)

        result = False
        if target_direction == "LONG":
            result = is_long_signal
        elif target_direction == "SHORT":
            result = is_short_signal
        elif target_direction == "ANY_TREND":
            result = is_long_signal or is_short_signal
        elif target_direction == "FLAT":
            result = not (is_long_signal or is_short_signal)

        return bool(result), {
            "sma_fast": float(f_val),
            "sma_slow": float(s_val),
            "rsi": float(r_val),
            "target": target_direction,
            "is_long": bool(is_long_signal),
            "is_short": bool(is_short_signal),
        }
