# bot_module/feature_extractor.py

import pandas as pd
import numpy as np
from typing import Dict, Optional, Any, List, Tuple, Set
import logging
from collections import deque
import math
import time

# Ensure that river is imported
try:
    from river import preprocessing, stats, utils
except ImportError:
    # Placeholder if river is not set (although it is required for operation)
    logging.critical(
        "Python library 'river' not found. FeatureExtractor depends on it. Please install: pip install river"
    )

    # Create type stubs so the code doesn't crash on import
    class _MockRiverObject:
        pass

    class preprocessing:
        RobustScaler = _MockRiverObject

    class stats:
        Mean = _MockRiverObject
        Var = _MockRiverObject
        Max = _MockRiverObject
        Min = _MockRiverObject

    class utils:
        Rolling = _MockRiverObject


try:
    from bot_module import config
    from bot_module.config import (
        DEFAULT_KLINE_FEATURES,
        DEFAULT_AGGTRADE_FEATURES,
        NEW_KLINE_FEATURES,
        NEW_AGGTRADE_FEATURES,
        ALL_POSSIBLE_FEATURES,
    )
except ImportError:

    class MockFEConfig:
        ALL_POSSIBLE_FEATURES = [
            "ema_20_rel",
            "atr_14_rel",
            "rsi_14",
            "vol_zscore_20",
            "price_change_1m",
            "candle_body_pct",
            "candle_wick_pct",
            "volume_spike_ratio_20",
            "delta_volume_pct_1",
            "price_std_5",
            "is_high_volatility",
            "agg_trade_spike_10s",
            "agg_trade_delta_10s",
            "avg_trade_size_norm_100",
            "rel_volume_spike_20",
            "volatility_spike_20",
            "momentum_3",
            "fake_breakout_score",
            "range_compression_20",
            "distance_to_local_max_20",
            "distance_to_local_min_20",
            "body_pct",
            "wick_pct",
            "signal_quality_score",
            "buyer_ratio_50",
            "volume_imbalance_50",
            "avg_trade_size_norm_50",
            "trade_rate_30s",
            "liquidity_shift_score_50",
        ]
        DEFAULT_KLINE_FEATURES = {}
        DEFAULT_AGGTRADE_FEATURES = {}
        NEW_KLINE_FEATURES = {}
        NEW_AGGTRADE_FEATURES = {}
        SIGNAL_QUALITY_THRESHOLDS = {}
        SIGNAL_QUALITY_WEIGHTS = {}
        SIGNAL_QUALITY_MAX_SCORE = 1.0

        def get_strategy_param(self, *args, **kwargs):
            return None  # Stub for get_strategy_param

    config = MockFEConfig()
    DEFAULT_KLINE_FEATURES = {}
    DEFAULT_AGGTRADE_FEATURES = {}
    NEW_KLINE_FEATURES = {}
    NEW_AGGTRADE_FEATURES = {}
    ALL_POSSIBLE_FEATURES = config.ALL_POSSIBLE_FEATURES

PANDAS_TA_AVAILABLE = False
try:
    import pandas_ta as ta  # noqa: F401

    PANDAS_TA_AVAILABLE = True
except ImportError:
    pass

logger = logging.getLogger("bot_module.feature_extractor")
if not logger.hasHandlers():
    logger.addHandler(logging.NullHandler())


class FeatureExtractor:
    def __init__(
        self,
        kline_feature_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        aggtrade_feature_configs: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        # Merge old and new configs
        self.kline_feature_configs = {
            **DEFAULT_KLINE_FEATURES,
            **NEW_KLINE_FEATURES,
            **(kline_feature_configs or {}),
        }
        self.aggtrade_feature_configs = {
            **DEFAULT_AGGTRADE_FEATURES,
            **NEW_AGGTRADE_FEATURES,
            **(aggtrade_feature_configs or {}),
        }
        self.all_feature_configs = {
            **self.kline_feature_configs,
            **self.aggtrade_feature_configs,
        }

        # Load parameters for Signal Quality Score
        self.quality_thresholds = config.get_strategy_param(
            "OnlineAgentStrategy", "signal_quality_thresholds", {}
        )
        self.quality_weights = config.get_strategy_param(
            "OnlineAgentStrategy", "signal_quality_weights", {}
        )
        self.max_quality_score = config.get_strategy_param(
            "OnlineAgentStrategy", "signal_quality_max_score", 1.0
        )
        if (
            not self.quality_thresholds
            or not self.quality_weights
            or self.max_quality_score <= 0
        ):
            logger.warning(
                "Signal Quality Score thresholds/weights not fully configured in config. Score might be zero."
            )
            self.quality_thresholds = {}
            self.quality_weights = {}
            self.max_quality_score = 1.0

        # Initialization of states and scaler
        self._kline_stats: Dict[str, Any] = {}
        self._aggtrade_stats: Dict[str, Any] = {}
        self.max_agg_trade_history_sec = 15
        for cfg in self.aggtrade_feature_configs.values():
            self.max_agg_trade_history_sec = max(
                self.max_agg_trade_history_sec, cfg.get("window_sec", 0)
            )
        self.max_agg_trade_history_sec += 5
        self._trade_history: deque[Tuple[int, float, float, bool]] = deque()
        self._aggtrade_stats_dirty = True
        self.active_feature_names: Set[str] = set(ALL_POSSIBLE_FEATURES)
        self._initialize_kline_stats()
        self._initialize_aggtrade_stats()
        # Checking for the presence of RobustScaler
        if hasattr(preprocessing, "RobustScaler"):
            self.scaler = preprocessing.RobustScaler()
        else:
            logger.error(
                "river.preprocessing.RobustScaler not available. Normalization will fail."
            )
            self.scaler = None  # Set to None if not present

        logger.info("FeatureExtractor initialized (with Signal Quality Score).")
        logger.debug(f"Quality Score Thresholds: {self.quality_thresholds}")
        logger.debug(f"Quality Score Weights: {self.quality_weights}")

    def set_active_features(self, active_features: Set[str]):
        """Sets the set of active features and reinitializes stats."""
        all_configured_features = set(ALL_POSSIBLE_FEATURES)
        valid_features = active_features.intersection(all_configured_features)
        invalid_features = active_features - valid_features
        if invalid_features:
            logger.warning(
                f"Ignoring unknown features requested for activation: {invalid_features}"
            )
        if (
            self.active_feature_names != valid_features
        ):  # Reinitialize only if the set has changed
            self.active_feature_names = valid_features
            logger.info(
                f"Active features set by ModelPipeline. Count: {len(self.active_feature_names)}. Active: {self.active_feature_names}"
            )
            # Reinitialize stats for active features
            self._initialize_kline_stats()
            self._initialize_aggtrade_stats()
        # else: logger.debug("Active features unchanged, skipping stats reinitialization.")

    def _initialize_kline_stats(self):
        """Initializes Rolling objects for active kline features."""
        self._kline_stats = {}
        if not hasattr(utils, "Rolling"):
            logger.error("river.utils.Rolling not available.")
            return

        for name in self.active_feature_names:
            if name not in self.kline_feature_configs:
                continue
            config_params = self.kline_feature_configs[name]
            period = config_params.get("period")
            if period is None or period <= 0:
                continue

            try:
                if name.startswith("vol_zscore_"):
                    self._kline_stats[name] = {
                        "mean": utils.Rolling(stats.Mean(), window_size=period),
                        "variance": utils.Rolling(
                            stats.Var(ddof=0), window_size=period
                        ),
                        "type": "vol_zscore",
                    }
                elif name.startswith(("volume_spike_ratio_", "rel_volume_spike_")):
                    # Do NOT initialize for 'rel_volume_spike_20', as it is taken from pre-calculation
                    if name != "rel_volume_spike_20":
                        self._kline_stats[name] = {
                            "mean_volume": utils.Rolling(
                                stats.Mean(), window_size=period
                            ),
                            "type": "rel_volume_spike",
                        }
                elif name.startswith("price_std_"):
                    self._kline_stats[name] = {
                        "variance_price": utils.Rolling(
                            stats.Var(ddof=0), window_size=period
                        ),
                        "type": "price_std",
                    }
                elif name.startswith("volatility_spike_"):
                    atr_period = config_params.get("atr_period", 14)
                    self._kline_stats[name] = {
                        f"mean_atr_{atr_period}": utils.Rolling(
                            stats.Mean(), window_size=period
                        ),
                        "type": "volatility_spike",
                    }

            except Exception as e_outer:  # Catch errors for other types of stats
                logger.error(
                    f"Error initializing kline stats for '{name}' (Outer loop): {e_outer}"
                )
                self._kline_stats[name] = None  # Mark as uninitialized

        # Remove keys that failed to initialize
        keys_to_remove = [k for k, v in self._kline_stats.items() if v is None]
        for key in keys_to_remove:
            del self._kline_stats[key]

        logger.debug(
            f"Initialized kline stats for active features: {list(self._kline_stats.keys())}"
        )

    def _initialize_aggtrade_stats(self):
        """Initializes Rolling objects for active aggtrade features."""
        self._aggtrade_stats = {}
        if not hasattr(utils, "Rolling"):  # Checking for the presence of Rolling
            logger.error(
                "river.utils.Rolling not available. Cannot initialize aggtrade stats."
            )
            return

        for name in self.active_feature_names:
            if name not in self.aggtrade_feature_configs:
                continue
            config_params = self.aggtrade_feature_configs.get(name, {})

            try:  # Wrap stats creation in try-except
                if name.startswith("avg_trade_size_norm_"):
                    window_records = config_params.get("window_size", 50)
                    norm_window_mult = config_params.get("norm_window_multiplier", 2)
                    norm_window_records = window_records * norm_window_mult
                    if window_records <= 0 or norm_window_records <= 0:
                        continue
                    self._aggtrade_stats[name] = {
                        "avg_size": utils.Rolling(
                            stats.Mean(), window_size=window_records
                        ),
                        "mean_of_avg": utils.Rolling(
                            stats.Mean(), window_size=norm_window_records
                        ),
                        "variance_of_avg": utils.Rolling(
                            stats.Var(ddof=0), window_size=norm_window_records
                        ),
                        "type": "avg_trade_size_norm",
                    }
                elif name.startswith("liquidity_shift_score_"):
                    window_records = config_params.get("window_size", 50)
                    long_window_mult = config_params.get("long_window_multiplier", 3)
                    long_window_records = window_records * long_window_mult
                    if window_records <= 0 or long_window_records <= 0:
                        continue
                    self._aggtrade_stats[name] = {
                        "short_avg_size": utils.Rolling(
                            stats.Mean(), window_size=window_records
                        ),
                        "long_avg_size_mean": utils.Rolling(
                            stats.Mean(), window_size=long_window_records
                        ),
                        "long_avg_size_variance": utils.Rolling(
                            stats.Var(ddof=0), window_size=long_window_records
                        ),
                        "type": "liquidity_shift_score",
                    }
            except Exception as e:
                logger.error(f"Error initializing aggtrade stats for '{name}': {e}")

        logger.debug(
            f"Initialized aggtrade stats for active features: {list(self._aggtrade_stats.keys())}"
        )

    def _calculate_signal_quality_score(
        self, calculated_features: Dict[str, float]
    ) -> float:
        """Calculates the weighted signal quality score."""
        score = 0.0
        log_prefix = "[FE_QualityScore]"
        if not self.quality_thresholds or not self.quality_weights:
            return 0.0

        try:
            for key, threshold in self.quality_thresholds.items():
                weight = self.quality_weights.get(key)
                feature_value = calculated_features.get(key)
                if weight is None or feature_value is None:
                    continue  # Skip if no weight or value

                condition_met = False
                if key == "momentum_3_abs":  # Special handling for absolute value
                    condition_met = abs(feature_value) > threshold
                elif key in [
                    "wick_pct",
                    "range_compression_20",
                ]:  # Features where LESS - is better
                    condition_met = feature_value < threshold
                else:  # Others - MORE - is better
                    condition_met = feature_value > threshold

                if condition_met:
                    score += weight
                    # logger.debug(f"{log_prefix} +{weight:.2f} for {key} (Value: {feature_value:.3f}, Thr: {threshold})")

            # Score normalization (0-1)
            normalized_score = (
                max(0.0, min(1.0, score / self.max_quality_score))
                if self.max_quality_score > 0
                else 0.0
            )
            # logger.debug(f"{log_prefix} Calculated Score: {score:.2f}, Normalized: {normalized_score:.3f}")
            return normalized_score
        except Exception as e:
            logger.error(
                f"{log_prefix} Error calculating quality score: {e}. Features: {calculated_features}",
                exc_info=True,
            )
            return 0.0

    def _calculate_kline_features(
        self,
        current_candle_data: Dict[str, Any],
        full_kline_history: pd.DataFrame,
        current_index: int,
    ) -> Dict[str, float]:
        """
        Calculates all ACTIVE kline features for the current candle.
        Uses pre-calculated rolling values from current_candle_data.
        If pre-calculated values are missing — calculates them from full_kline_history.
        """
        features: Dict[str, float] = {
            name: 0.0
            for name in self.active_feature_names
            if name in self.kline_feature_configs
        }
        log_prefix = "[FE_KlineCalc]"

        # FALLBACK: Calculate ATR/NATR from history if not provided
        if "atr" not in current_candle_data or pd.isna(current_candle_data.get("atr")):
            if full_kline_history is not None and len(full_kline_history) >= 14:
                try:
                    tr = pd.concat(
                        [
                            full_kline_history["high"] - full_kline_history["low"],
                            abs(
                                full_kline_history["high"]
                                - full_kline_history["close"].shift(1)
                            ),
                            abs(
                                full_kline_history["low"]
                                - full_kline_history["close"].shift(1)
                            ),
                        ],
                        axis=1,
                    ).max(axis=1)
                    atr_series = tr.rolling(14).mean()
                    atr_value = (
                        float(atr_series.iloc[current_index])
                        if pd.notna(atr_series.iloc[current_index])
                        else 0.0
                    )
                    current_candle_data["atr"] = atr_value
                    # Also add ATR_14 for compatibility with atr_14_rel config
                    current_candle_data["ATR_14"] = atr_value
                except Exception as e_atr:
                    logger.debug(
                        f"{log_prefix} Failed to calculate ATR fallback: {e_atr}"
                    )
                    current_candle_data["atr"] = 0.0
                    current_candle_data["ATR_14"] = 0.0
            else:
                current_candle_data["atr"] = 0.0
                current_candle_data["ATR_14"] = 0.0
        elif "ATR_14" not in current_candle_data:
            # If atr exists but ATR_14 does not — copy
            current_candle_data["ATR_14"] = current_candle_data.get("atr", 0.0)

        if "natr" not in current_candle_data or pd.isna(
            current_candle_data.get("natr")
        ):
            atr_val = current_candle_data.get("atr", 0.0)
            close_val = current_candle_data.get("close", 0.0)
            if close_val and close_val > 1e-9:
                current_candle_data["natr"] = (atr_val / close_val) * 100.0
            else:
                current_candle_data["natr"] = 0.0

        # FALLBACK: Calculate rolling_high/low from history if not provided
        rolling_period = 20
        if f"rolling_high_{rolling_period}" not in current_candle_data:
            if (
                full_kline_history is not None
                and len(full_kline_history) >= rolling_period
            ):
                try:
                    rolling_high = (
                        full_kline_history["high"].rolling(rolling_period).max()
                    )
                    current_candle_data[f"rolling_high_{rolling_period}"] = (
                        float(rolling_high.iloc[current_index])
                        if pd.notna(rolling_high.iloc[current_index])
                        else 0.0
                    )
                except Exception:
                    current_candle_data[f"rolling_high_{rolling_period}"] = 0.0
            else:
                current_candle_data[f"rolling_high_{rolling_period}"] = 0.0

        if f"rolling_low_{rolling_period}" not in current_candle_data:
            if (
                full_kline_history is not None
                and len(full_kline_history) >= rolling_period
            ):
                try:
                    rolling_low = (
                        full_kline_history["low"].rolling(rolling_period).min()
                    )
                    current_candle_data[f"rolling_low_{rolling_period}"] = (
                        float(rolling_low.iloc[current_index])
                        if pd.notna(rolling_low.iloc[current_index])
                        else 0.0
                    )
                except Exception:
                    current_candle_data[f"rolling_low_{rolling_period}"] = 0.0
            else:
                current_candle_data[f"rolling_low_{rolling_period}"] = 0.0

        required_keys = ["open", "high", "low", "close", "volume", "natr", "atr"]
        if any(
            key not in current_candle_data or pd.isna(current_candle_data[key])
            for key in required_keys
        ):
            logger.warning(f"{log_prefix} Missing or NaN base OHLCV/NATR/ATR data.")
            if "signal_quality_score" in features:
                features["signal_quality_score"] = self._calculate_signal_quality_score(
                    features
                )
            return features

        try:
            c_open = float(current_candle_data["open"])
            c_high = float(current_candle_data["high"])
            c_low = float(current_candle_data["low"])
            c_close = float(current_candle_data["close"])
            c_volume = float(current_candle_data["volume"])
            c_natr = float(current_candle_data["natr"])
            c_atr = float(current_candle_data["atr"])
            # Use pre-calculated candle_range
            c_range = float(
                current_candle_data.get("candle_range", max(0.0, c_high - c_low))
            )
        except (TypeError, ValueError) as e:
            logger.error(
                f"{log_prefix} Error converting base OHLCV/NATR/ATR/Range to float: {e}"
            )
            if "signal_quality_score" in features:
                features["signal_quality_score"] = self._calculate_signal_quality_score(
                    features
                )
            return features

        # Define the period for pre-calculated features
        rolling_period_for_max_min = (
            20  # Must match the period in SimpleBacktester.__init__
        )

        for name in features.keys():
            if name == "signal_quality_score":
                continue
            config_params = self.kline_feature_configs.get(name, {})
            feature_value = 0.0

            try:
                # Feature calculation logic
                indicator_key = config_params.get("indicator")
                if indicator_key:  # Calculation of features based on indicators (SMA_rel, ATR_rel, RSI)
                    indicator_value = current_candle_data.get(indicator_key)
                    if indicator_value is not None and not pd.isna(indicator_value):
                        indicator_value = float(indicator_value)
                        if name.startswith(("ema_", "sma_")) and name.endswith("_rel"):
                            if indicator_value > 1e-9:
                                feature_value = (
                                    c_close / indicator_value - 1.0
                                ) * 100.0
                        elif name.startswith("atr_") and name.endswith("_rel"):
                            if c_close > 1e-9:
                                feature_value = (indicator_value / c_close) * 100.0
                        elif name.startswith("rsi_"):
                            feature_value = indicator_value / 100.0
                elif name.startswith("vol_zscore_"):  # Uses River stats
                    stats_entry = self._kline_stats.get(name)
                    if stats_entry:
                        mean_roller = stats_entry.get("mean")
                        var_roller = stats_entry.get("variance")
                        if mean_roller and var_roller:
                            mean_roller.update(c_volume)
                            var_roller.update(c_volume)
                            mean_vol = mean_roller.get()
                            variance_vol = var_roller.get()
                            if (
                                mean_vol is not None
                                and variance_vol is not None
                                and variance_vol >= 0
                            ):
                                std_vol = math.sqrt(variance_vol)
                                if std_vol > 1e-9:
                                    feature_value = (c_volume - mean_vol) / std_vol
                                elif abs(c_volume - mean_vol) < 1e-9:
                                    feature_value = 0.0
                                else:
                                    feature_value = np.sign(c_volume - mean_vol) * 10.0
                elif name.startswith("price_change_"):  # Uses history
                    period = config_params.get("period", 1)
                    if current_index >= period:
                        prev_close_price = full_kline_history["close"].iloc[
                            current_index - period
                        ]
                        if pd.notna(prev_close_price) and prev_close_price > 1e-9:
                            feature_value = (c_close / prev_close_price - 1.0) * 100.0
                elif name.startswith(
                    ("volume_spike_ratio_", "rel_volume_spike_")
                ):  # Uses River or pre-calculated
                    # Use pre-calculated 'relative_volume' for rel_volume_spike_20
                    if name == "rel_volume_spike_20":
                        rel_vol_val = current_candle_data.get("relative_volume")
                        if rel_vol_val is not None and pd.notna(rel_vol_val):
                            feature_value = float(rel_vol_val)
                        else:
                            feature_value = 1.0  # Default value if no data
                    else:  # Use River stat for other volume_spike_ratio_
                        stats_entry = self._kline_stats.get(name)
                        if stats_entry:
                            mean_vol_roller = stats_entry.get("mean_volume")
                            if mean_vol_roller:
                                mean_vol_roller.update(c_volume)
                                mean_vol = mean_vol_roller.get()
                                if mean_vol is not None:
                                    feature_value = (
                                        c_volume / mean_vol
                                        if mean_vol > 1e-9
                                        else (100.0 if c_volume > 1e-9 else 1.0)
                                    )
                elif name.startswith("delta_volume_pct_"):  # Uses history
                    period = config_params.get("period", 1)
                    if current_index >= period:
                        prev_volume = float(
                            full_kline_history["volume"].iloc[current_index - period]
                        )
                        if pd.notna(prev_volume):
                            feature_value = (
                                (c_volume / prev_volume - 1.0) * 100.0
                                if prev_volume > 1e-9
                                else (10000.0 if c_volume > 1e-9 else 0.0)
                            )
                elif name.startswith("price_std_"):  # Uses River stats
                    stats_entry = self._kline_stats.get(name)
                    if stats_entry:
                        variance_roller = stats_entry.get("variance_price")
                        if variance_roller:
                            variance_roller.update(c_close)
                            variance = variance_roller.get()
                            if variance is not None and variance >= 0:
                                feature_value = math.sqrt(variance)
                elif name == "is_high_volatility":  # Uses other features
                    natr_threshold = config_params.get("natr_threshold", 1.5)
                    std_threshold_pct = config_params.get("std_threshold_pct", 0.5)
                    std_feature_name = config_params.get(
                        "std_feature_name", "price_std_5"
                    )
                    price_std_abs = features.get(std_feature_name, 0.0)
                    std_threshold_abs = (
                        c_close * (std_threshold_pct / 100.0) if c_close > 1e-9 else 0.0
                    )
                    feature_value = (
                        1.0
                        if c_natr > natr_threshold and price_std_abs > std_threshold_abs
                        else 0.0
                    )
                elif name.startswith("volatility_spike_"):  # Uses River stats
                    stats_entry = self._kline_stats.get(name)
                    if stats_entry and c_atr > 1e-9:
                        atr_period = config_params.get("atr_period", 14)
                        mean_atr_roller_key = f"mean_atr_{atr_period}"
                        mean_atr_roller = stats_entry.get(mean_atr_roller_key)
                        if mean_atr_roller:
                            mean_atr_roller.update(c_atr)
                            mean_atr = mean_atr_roller.get()
                            if mean_atr is not None:
                                feature_value = (
                                    c_atr / mean_atr if mean_atr > 1e-9 else 1.0
                                )
                elif name.startswith("momentum_"):  # Uses history
                    period = config_params.get("period", 3)
                    if current_index >= period:
                        prev_close_price = full_kline_history["close"].iloc[
                            current_index - period
                        ]
                        if pd.notna(prev_close_price) and prev_close_price > 1e-9:
                            feature_value = (c_close / prev_close_price - 1.0) * 100.0
                elif name == "fake_breakout_score":  # Uses other features
                    vol_spike_key = (
                        f"rel_volume_spike_{config_params.get('period', 20)}"
                    )
                    wick_pct_key = "wick_pct"
                    vol_spike_val = (
                        features.get(vol_spike_key, 0.0)
                        if vol_spike_key in features
                        else 0.0
                    )
                    wick_pct_val = (
                        features.get(wick_pct_key, 0.0)
                        if wick_pct_key in features
                        else 0.0
                    )
                    feature_value = (vol_spike_val / 5.0) * (wick_pct_val / 100.0)

                # Use pre-calculated values
                elif name.startswith("range_compression_"):
                    rolling_max_range_key = (
                        f"rolling_max_range_{rolling_period_for_max_min}"
                    )
                    # c_range is already calculated at the beginning
                    rolling_max_range_val = current_candle_data.get(
                        rolling_max_range_key
                    )
                    if (
                        rolling_max_range_val is not None
                        and rolling_max_range_val > 1e-9
                    ):
                        feature_value = c_range / rolling_max_range_val
                    elif rolling_max_range_val is not None:  # If max_range = 0
                        feature_value = (
                            1.0 if c_range <= 1e-9 else 0.0
                        )  # 1.0 if both are 0, otherwise 0.0
                elif name.startswith("distance_to_local_max_"):
                    rolling_max_key = f"rolling_high_{rolling_period_for_max_min}"
                    rolling_max_val = current_candle_data.get(rolling_max_key)
                    if rolling_max_val is not None and rolling_max_val > 1e-9:
                        feature_value = (
                            (rolling_max_val - c_close) / rolling_max_val * 100.0
                        )
                elif name.startswith("distance_to_local_min_"):
                    rolling_min_key = f"rolling_low_{rolling_period_for_max_min}"
                    rolling_min_val = current_candle_data.get(rolling_min_key)
                    if rolling_min_val is not None and rolling_min_val > 1e-9:
                        feature_value = (
                            (c_close - rolling_min_val) / rolling_min_val * 100.0
                        )

                elif name == "body_pct":
                    feature_value = (
                        (abs(c_close - c_open) / c_range) * 100.0
                        if c_range > 1e-9
                        else 50.0
                    )
                elif name == "wick_pct":
                    feature_value = (
                        ((c_range - abs(c_close - c_open)) / c_range) * 100.0
                        if c_range > 1e-9
                        else 0.0
                    )
                elif name == "time_since_last_signal_sec":
                    value = current_candle_data.get("time_since_last_signal_sec")
                    if value is None:
                        feature_value = 86400.0
                    elif np.isinf(value):
                        feature_value = 86400.0
                    else:
                        feature_value = min(float(value), 86400.0)

                # Checking for NaN/inf and recording
                features[name] = (
                    feature_value
                    if pd.notna(feature_value) and np.isfinite(feature_value)
                    else 0.0
                )

            except KeyError as ke:
                logger.warning(
                    f"{log_prefix} KeyError calculating kline feature '{name}': Missing key {ke}. Setting to 0."
                )
                features[name] = 0.0
            except Exception as e:
                logger.error(
                    f"{log_prefix} Error calculating kline feature '{name}': {e}",
                    exc_info=True,
                )
                features[name] = 0.0

        # Calculation of the quality score after all other features
        if "signal_quality_score" in features:
            quality_score_value = self._calculate_signal_quality_score(features)
            features["signal_quality_score"] = quality_score_value

        return features

    def _add_aggtrade_to_history(self, trade: Dict[str, Any]):
        """Adds a trade to history for calculating aggtrade features."""
        try:
            timestamp_ms = int(trade.get("T", 0))
            price = float(trade.get("p", 0.0))
            qty = float(trade.get("q", 0.0))
            is_buyer_maker = bool(trade.get("m", True))
            # Skipping invalid trades
            if timestamp_ms == 0 or price <= 0 or qty <= 0:
                return
            self._trade_history.append((timestamp_ms, price, qty, is_buyer_maker))
            self._aggtrade_stats_dirty = (
                True  # Flag that rolling stats need to be recalculated
            )
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Error processing aggtrade: {e}. Trade: {trade}")
        except Exception as e:
            logger.error(f"Unexpected error adding aggtrade: {e}", exc_info=True)

    def _process_trade_history(self, current_timestamp_ms: int):
        """Updates rolling statistics for aggtrade features."""
        if not self._aggtrade_stats_dirty:
            return  # Do not recalculate if history has not changed
        log_prefix = "[FE_ProcHist]"
        # Clearing old trades
        cutoff_ts = current_timestamp_ms - (self.max_agg_trade_history_sec * 1000)
        self._trade_history = deque(
            trade for trade in self._trade_history if trade[0] >= cutoff_ts
        )

        # Recalculating rolling stats
        for name in self.active_feature_names:
            if name not in self._aggtrade_stats:
                continue  # Only for features with rolling stats
            config_params = self.aggtrade_feature_configs.get(name, {})
            stats_dict = self._aggtrade_stats.get(name)
            if not stats_dict:
                continue

            try:
                stats_type = stats_dict.get("type")
                # Recreate Rolling objects and fill them with current history
                if stats_type == "avg_trade_size_norm":
                    window_records = config_params.get("window_size", 50)
                    norm_window_mult = config_params.get("norm_window_multiplier", 2)
                    norm_window_records = window_records * norm_window_mult
                    if window_records <= 0 or norm_window_records <= 0:
                        continue
                    avg_roller = utils.Rolling(stats.Mean(), window_size=window_records)
                    mean_roller = utils.Rolling(
                        stats.Mean(), window_size=norm_window_records
                    )
                    var_roller = utils.Rolling(
                        stats.Var(ddof=0), window_size=norm_window_records
                    )
                    # Refilling
                    for _, _, qty, _ in self._trade_history:
                        avg_roller.update(qty)
                        cur_avg = avg_roller.get()
                        if cur_avg is not None:
                            mean_roller.update(cur_avg)
                            var_roller.update(cur_avg)
                    stats_dict["avg_size"] = avg_roller
                    stats_dict["mean_of_avg"] = mean_roller
                    stats_dict["variance_of_avg"] = var_roller
                elif stats_type == "liquidity_shift_score":
                    window_records = config_params.get("window_size", 50)
                    long_window_mult = config_params.get("long_window_multiplier", 3)
                    long_window_records = window_records * long_window_mult
                    if window_records <= 0 or long_window_records <= 0:
                        continue
                    short_avg_roller = utils.Rolling(
                        stats.Mean(), window_size=window_records
                    )
                    long_mean_roller = utils.Rolling(
                        stats.Mean(), window_size=long_window_records
                    )
                    long_var_roller = utils.Rolling(
                        stats.Var(ddof=0), window_size=long_window_records
                    )
                    # Refilling
                    for _, _, qty, _ in self._trade_history:
                        short_avg_roller.update(qty)
                        cur_short_avg = short_avg_roller.get()
                        if cur_short_avg is not None:
                            long_mean_roller.update(cur_short_avg)
                            long_var_roller.update(cur_short_avg)
                    stats_dict["short_avg_size"] = short_avg_roller
                    stats_dict["long_avg_size_mean"] = long_mean_roller
                    stats_dict["long_avg_size_variance"] = long_var_roller
            except Exception as e_update:
                logger.error(
                    f"{log_prefix} Error updating rolling aggtrade stats for '{name}': {e_update}"
                )

        self._aggtrade_stats_dirty = False  # Resetting the flag

    def _calculate_aggtrade_features(
        self, df_agg: pd.DataFrame, current_timestamp_ms: int
    ) -> Dict[str, str]:
        #                                                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^
        """Calculates features based on recent aggregated trades."""
        features: Dict[str, float] = {
            name: 0.0
            for name in self.active_feature_names
            if name in self.aggtrade_feature_configs
        }
        if not self._trade_history:
            return features
        now_ms = current_timestamp_ms
        log_prefix = "[FE_AggCalc]"

        # Calculation of all active AGGTRADE features
        for name in features.keys():
            config_params = self.aggtrade_feature_configs.get(name, {})
            feature_value = 0.0
            try:
                # Rolling Delta calculation
                if name.startswith("agg_delta_"):
                    window_sec = config_params.get("window_sec", 10)
                    if window_sec <= 0:
                        continue
                    window_start_ms = now_ms - window_sec * 1000
                    buy_vol = 0.0
                    sell_vol = 0.0
                    # Iterate over self._trade_history (already cleared of old ones)
                    for ts, _, qty, is_buyer_maker in self._trade_history:
                        if ts >= window_start_ms:
                            if not is_buyer_maker:
                                buy_vol += qty  # Taker Buy
                            else:
                                sell_vol += qty  # Taker Sell
                    feature_value = buy_vol - sell_vol

                # Calculation of other aggtrade features
                elif name.startswith(
                    ("agg_trade_spike_")
                ):  # Removed agg_trade_delta_ from here
                    window_sec = config_params.get("window_sec", 10)
                    window_start_ms = now_ms - window_sec * 1000
                    # Define trades_in_window HERE
                    trades_in_window = [
                        (ts, p, q, m)
                        for ts, p, q, m in self._trade_history
                        if ts >= window_start_ms
                    ]
                    if name.startswith("agg_trade_spike_"):
                        feature_value = float(len(trades_in_window))

                # New features
                elif name.startswith("buyer_ratio_"):
                    window_size = config_params.get("window_size", 50)
                    # Define trades_in_window HERE
                    trades_in_window = list(self._trade_history)[-window_size:]
                    if trades_in_window:
                        total_trades = len(trades_in_window)
                        buyer_trades = sum(
                            1 for _, _, _, m in trades_in_window if not m
                        )
                        feature_value = (
                            buyer_trades / total_trades if total_trades > 0 else 0.0
                        )

                elif name.startswith("volume_imbalance_"):
                    window_size = config_params.get("window_size", 50)
                    # Define trades_in_window HERE
                    trades_in_window = list(self._trade_history)[-window_size:]
                    if trades_in_window:
                        buy_vol = sum(q for _, _, q, m in trades_in_window if not m)
                        sell_vol = sum(q for _, _, q, m in trades_in_window if m)
                        total_vol = buy_vol + sell_vol
                        feature_value = (
                            (buy_vol - sell_vol) / total_vol
                            if total_vol > 1e-9
                            else 0.0
                        )

                elif name.startswith("avg_trade_size_norm_"):
                    # Get stats HERE
                    stats_dict = self._aggtrade_stats.get(name)
                    if stats_dict:  # Checking for the presence of stats
                        avg_roller = stats_dict.get("avg_size")
                        mean_roller = stats_dict.get("mean_of_avg")
                        var_roller = stats_dict.get("variance_of_avg")
                        if avg_roller and mean_roller and var_roller:
                            cur_avg = avg_roller.get()
                            mean_avg = mean_roller.get()
                            var_avg = var_roller.get()
                            # Check that all values are received
                            if (
                                cur_avg is not None
                                and mean_avg is not None
                                and var_avg is not None
                            ):
                                std_avg = (
                                    math.sqrt(var_avg) if var_avg > 1e-12 else 1e-9
                                )  # Use a small number instead of None
                                if std_avg > 1e-12:
                                    feature_value = max(
                                        -10.0, min(10.0, (cur_avg - mean_avg) / std_avg)
                                    )
                                elif abs(cur_avg - mean_avg) > 1e-9:
                                    feature_value = (
                                        10.0 if cur_avg > mean_avg else -10.0
                                    )
                                else:
                                    feature_value = 0.0

                elif name.startswith("trade_rate_"):
                    window_sec = config_params.get("window_sec", 30)
                    window_start_ms = now_ms - window_sec * 1000
                    # Define trades_in_window HERE
                    trades_in_window = [
                        (ts, p, q, m)
                        for ts, p, q, m in self._trade_history
                        if ts >= window_start_ms
                    ]
                    if trades_in_window:
                        feature_value = (
                            len(trades_in_window) / window_sec
                            if window_sec > 0
                            else 0.0
                        )

                elif name.startswith("liquidity_shift_score_"):
                    # Get stats HERE
                    stats_dict = self._aggtrade_stats.get(name)
                    if stats_dict:  # Checking for the presence of stats
                        short_roller = stats_dict.get("short_avg_size")
                        long_mean_roller = stats_dict.get("long_avg_size_mean")
                        long_var_roller = stats_dict.get("long_avg_size_variance")
                        if short_roller and long_mean_roller and long_var_roller:
                            cur_short_avg = short_roller.get()
                            long_mean_avg = long_mean_roller.get()
                            long_var_avg = long_var_roller.get()
                            # Check that all values are received
                            if (
                                cur_short_avg is not None
                                and long_mean_avg is not None
                                and long_var_avg is not None
                            ):
                                long_std_avg = (
                                    math.sqrt(long_var_avg)
                                    if long_var_avg > 1e-12
                                    else 1e-9
                                )  # Use a small number instead of None
                                if long_std_avg > 1e-12:
                                    feature_value = max(
                                        -10.0,
                                        min(
                                            10.0,
                                            (cur_short_avg - long_mean_avg)
                                            / long_std_avg,
                                        ),
                                    )
                                elif abs(cur_short_avg - long_mean_avg) > 1e-9:
                                    feature_value = (
                                        10.0 if cur_short_avg > long_mean_avg else -10.0
                                    )
                                else:
                                    feature_value = 0.0

                # Write the value if it is valid
                features[name] = (
                    feature_value
                    if pd.notna(feature_value) and np.isfinite(feature_value)
                    else 0.0
                )
            except Exception as e:
                logger.error(
                    f"{log_prefix} Error calculating aggtrade feature '{name}': {e}",
                    exc_info=True,
                )
                features[name] = 0.0

        return features

    def extract_features_optimized(
        self,
        current_candle_data: Dict[str, Any],
        agg_trades_list: Optional[List[Dict[str, Any]]],
        full_kline_history: pd.DataFrame,
        current_index: int,
        current_timestamp_ms: int,
    ) -> Dict[str, Any]:
        """
        Optimized feature extraction method.
        Accepts pre-calculated data and history.
        """
        log_prefix = "[FE_ExtractOpt]"
        final_features: Dict[str, Any] = {}
        kline_features: Dict[str, Any] = {}
        aggtrade_features_calculated: Dict[str, str] = {}  # Initializing by default

        # 1. Calculation of KLINE features
        try:
            kline_features = self._calculate_kline_features(
                current_candle_data, full_kline_history, current_index
            )
            if not kline_features:
                logger.warning(
                    f"{log_prefix} @ i={current_index}] Kline features calculation returned empty dict."
                )
            final_features = kline_features.copy()  # Initialize the final dictionary
        except Exception as e_kline:
            logger.error(
                f"{log_prefix} @ i={current_index}] Error calculating kline features: {e_kline}",
                exc_info=True,
            )
            final_features = {}
            kline_features = {}

        # 2. Updating AggTrades history (if data exists)
        if agg_trades_list:
            for trade in agg_trades_list:
                self._add_aggtrade_to_history(trade)
        # 2.1 Update rolling stats for aggtrade
        self._process_trade_history(current_timestamp_ms)

        # 3. Calculation of AGGTRADE features
        aggtrade_features_calculated = {
            key: 0.0
            for key in self.aggtrade_feature_configs
            if key in self.active_feature_names
        }
        try:
            calculated_agg_features_dict = self._calculate_aggtrade_features(
                None, current_timestamp_ms
            )  # Passing None for df_agg
            if calculated_agg_features_dict:
                aggtrade_features_calculated.update(calculated_agg_features_dict)
            # logger.debug(f"{log_prefix} AggTrade features calculated: {aggtrade_features_calculated}")
        except Exception as e_agg_calc:
            logger.error(
                f"{log_prefix} @ i={current_index}] Error calculating aggtrade features: {e_agg_calc}",
                exc_info=True,
            )

        # 4. Merging results (kline + aggtrade)
        try:
            if aggtrade_features_calculated:
                final_features.update(aggtrade_features_calculated)
            # logger.debug(f"{log_prefix} @ i={current_index}] Final merged features count: {len(final_features)}")
        except Exception as e_merge:
            logger.error(
                f"{log_prefix} @ i={current_index}] Error merging kline and aggtrade features: {e_merge}",
                exc_info=True,
            )

        # 5. Final check and return
        if not final_features:
            logger.warning(
                f"{log_prefix} @ i={current_index}] Returning empty feature dictionary."
            )
        final_float_features = {}
        for key, value in final_features.items():
            try:
                final_float_features[key] = float(value)
            except (ValueError, TypeError):
                logger.warning(
                    f"{log_prefix} @ i={current_index}] Could not convert feature '{key}' value '{value}' to float. Using 0.0."
                )
                final_float_features[key] = 0.0
        return final_float_features

    def extract_features(
        self,
        kline_history: pd.DataFrame,
        recent_agg_trades: Optional[List[Dict[str, Any]]] = None,
        current_timestamp_ms: Optional[int] = None,
    ) -> Dict[str, float]:
        """Deprecated method, calls extract_features_optimized."""
        log_prefix = "[FE_ExtractLegacy]"
        logger.warning(f"{log_prefix} Using legacy method. Switch to optimized.")
        if kline_history is None or kline_history.empty:
            return {key: 0.0 for key in self.active_feature_names}
        current_index = len(kline_history) - 1
        current_candle_series = kline_history.iloc[current_index]
        current_candle_data = current_candle_series.to_dict()
        return self.extract_features_optimized(
            current_candle_data=current_candle_data,  # No ATR/NATR, will be calculated internally
            agg_trades_list=recent_agg_trades,
            full_kline_history=kline_history,
            current_index=current_index,
            current_timestamp_ms=current_timestamp_ms
            or int(time.time() * 1000),  # Adding fallback
        )

    def normalize_features(self, features: Dict[str, float]) -> Dict[str, float]:
        """Normalizes active features using RobustScaler."""
        if self.scaler is None:
            logger.error("Scaler is not initialized. Cannot normalize features.")
            return {k: features.get(k, 0.0) for k in self.active_feature_names}
        if not features:
            return {k: 0.0 for k in self.active_feature_names}
        active_features_to_normalize = {
            k: features.get(k, 0.0) for k in self.active_feature_names
        }
        if not active_features_to_normalize:
            return {k: 0.0 for k in self.active_feature_names}
        try:
            self.scaler.learn_one(active_features_to_normalize)
            normalized_active_features = self.scaler.transform_one(
                active_features_to_normalize
            )
            result = {
                k: 0.0 for k in self.active_feature_names
            }  # Initializing with zeros
            for k, v in normalized_active_features.items():
                if k in result:  # Updating only active ones
                    result[k] = v if pd.notna(v) and np.isfinite(v) else 0.0
            return result
        except Exception as e:
            logger.error(
                f"Error normalizing features: {e}. Features: {active_features_to_normalize}",
                exc_info=True,
            )
            return {
                k: 0.0 for k in self.active_feature_names
            }  # Return zeros for all active features on error
