import logging
import numpy as np
import xgboost as xgb
import joblib
from pathlib import Path
from typing import Dict, Any, Optional, List, Set, Tuple, Literal

from bot_module.strategy import (
    BaseStrategy,
    StrategySignal,
    SignalDirection,
    OrderMode,
    PartialTarget,
)
from bot_module import config
from bot_module import utils
from bot_module.compass_adapter import CompassFeatureAdapter

logger = logging.getLogger("bot_module.compass_strategy")


class CompassStrategy(BaseStrategy):
    NAME = "CompassStrategy"

    # Default logic parameters (can be overridden by UI config)
    DEFAULT_PARAMS = {
        "enabled": False,
        "min_entry_probability": 0.65,
        "use_oracle": True,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_atr_multiplier": 7.5,
        "trailing_stop_enabled": False,
        "trailing_stop_activation_atr": 2.0,
        "trailing_stop_distance_atr": 1.0,
        "partial_exits": [],  # List of {"fraction": 0.5, "rr_multiplier": 1.5}
        "move_sl_to_be_after_first_tp": True,
    }

    def __init__(self):
        super().__init__()

        # Paths
        # Try to get paths from config, else use defaults relative to project root
        self.compass_model_path = getattr(
            config, "COMPASS_MODEL_PATH", Path("data/compass_model.json")
        )
        self.oracle_model_path = getattr(
            config, "ORACLE_MODEL_PATH", Path("data/oracle_model.joblib")
        )

        self.compass_model: Optional[xgb.Booster] = None
        self.oracle_model: Any = None
        self.feature_names: List[str] = []

        self.adapter = CompassFeatureAdapter()

        self._load_models()

    def _load_models(self):
        """Loads XGBoost and Oracle models."""
        # Load Compass Model
        try:
            if not Path(self.compass_model_path).exists():
                logger.error(
                    f"[{self.NAME}] Compass model not found at {self.compass_model_path}"
                )
            else:
                self.compass_model = xgb.Booster()
                self.compass_model.load_model(str(self.compass_model_path))
                self.feature_names = self.compass_model.feature_names
                if not self.feature_names:
                    # Fallback if feature names not saved, assume fixed order from training script
                    logger.warning(
                        f"[{self.NAME}] Model has no feature names. Using default order."
                    )
                    self.feature_names = [
                        "pressure_buy",
                        "pressure_sell",
                        "absorption",
                        "path_resistance",
                        "obi_1p",
                        "delta_wall_divergence",
                        "scalper_natr",
                        "relative_volume",
                    ]
                logger.info(
                    f"[{self.NAME}] Loaded Compass model. Features: {self.feature_names}"
                )
        except Exception as e:
            logger.error(
                f"[{self.NAME}] Failed to load Compass model: {e}", exc_info=True
            )

        # Load Oracle Model
        try:
            if not Path(self.oracle_model_path).exists():
                logger.error(
                    f"[{self.NAME}] Oracle model not found at {self.oracle_model_path}"
                )
            else:
                self.oracle_model = joblib.load(str(self.oracle_model_path))
                logger.info(f"[{self.NAME}] Loaded Oracle model.")
        except Exception as e:
            logger.error(
                f"[{self.NAME}] Failed to load Oracle model: {e}", exc_info=True
            )

    @property
    def required_data_types(self) -> Set[str]:
        """Validates that we have Klines, Orderbook, and Tape data."""
        return {"kline_1m", "depth", "aggTrade"}

    async def check_signal(
        self,
        pair_info: Dict[str, Any],
        market_data: Dict[str, Any],
        prev_pair_info: Optional[Dict[str, Any]] = None,
        analysis_level: Literal[
            "minute_bar_filter", "second_bar_trigger"
        ] = "second_bar_trigger",
    ) -> Tuple[Optional[StrategySignal], float, Optional[Dict]]:
        """
        Main logic loop: Feature calc -> Oracle Check -> Compass Predict -> Signal.
        Returns: (signal, confidence_weight, trace_dict)
        """
        # 1. Config & State Check
        if not self._get_param("enabled", False):
            return None, 0.0, None

        symbol = pair_info.get("symbol", "Unknown")

        # 2. Prepare Data
        df_kline = market_data.get("kline_1m")
        if (
            df_kline is None or df_kline.empty or len(df_kline) < 60
        ):  # Need 60 for Oracle volatility
            return None, 0.0, None

        # Add helper columns (NATR, RelVol) if missing
        # We do this on a copy or modify in place? Modify in place is efficient but risky if shared.
        # DataConsumer caches are shared. Best to calc on a slice/copy for indicators.
        # But utils functions modify inplace.
        # Check if already present to avoid recalculation.
        if "natr" not in df_kline.columns:
            df_kline = self.adapter.calculate_scalper_natr_for_df(df_kline)
        if "relative_volume" not in df_kline.columns:
            df_kline = self.adapter.calculate_relative_volume_for_df(df_kline)

        # 3. Oracle Check
        if self._get_param("use_oracle", True) and self.oracle_model:
            oracle_feats = self.adapter.calculate_oracle_features(df_kline)
            if oracle_feats is not None:
                # Predict Regime. 1 = Amnesia (Trade). 0 = Paranoia (No Trade).
                # The model is likely a sklearn Classifier or similar.
                try:
                    regime = self.oracle_model.predict(oracle_feats)[0]
                    if regime != 1:  # Assuming 1 is AMNESIA/SAFE
                        # logger.debug(f"[{self.NAME}:{symbol}] Oracle rejected. Regime: {regime}")
                        return (
                            None,
                            0.0,
                            {"oracle_regime": regime, "reason": "paranoia"},
                        )
                except Exception as e:
                    logger.error(
                        f"[{self.NAME}:{symbol}] Oracle prediction failed: {e}"
                    )
                    return None, 0.0, None
            else:
                logger.warning(
                    f"[{self.NAME}:{symbol}] Could not calculate Oracle features."
                )
                return None, 0.0, None

        # 4. Compass Feature Extraction
        # Get Depth & Tape
        # Controller provides 'depth_analysis' (aggregated by _aggregate_depth) and 'depth_trading' (raw).
        # We need the aggregated one for obi_1p and pressure features.
        depth_data = market_data.get(
            "depth_analysis", {}
        )  # Aggregated depth from controller
        # 'aggTrade' list is needed for tape analysis.
        recent_trades = market_data.get("aggTrade", [])

        compass_features = self.adapter.calculate_compass_features(
            df_kline, depth_data, recent_trades
        )
        if not compass_features:
            return None, 0.0, None

        # 5. Prediction
        if not self.compass_model:
            return None, 0.0, None

        # Prepare DMatrix
        try:
            # Ensure correct order
            feature_vector = [compass_features.get(f, 0.0) for f in self.feature_names]
            dtest = xgb.DMatrix([feature_vector], feature_names=self.feature_names)

            # Predict
            # Predict
            output = self.compass_model.predict(dtest)

            # Initialize loop vars
            direction = None
            confidence = 0.0

            # Handle Multiclass Output (e.g. [Prob_Short, Prob_Skip, Prob_Long])
            if isinstance(output, np.ndarray) and output.ndim == 2:
                # Standard sklearn/xgb multiclass output shape (n_samples, n_classes) -> (1, 3)
                if output.shape[1] == 3:
                    # Assumption: classes are sorted [-1, 0, 1] or similar
                    p_short = float(output[0][0])
                    p_long = float(output[0][2])

                    thresh = self._get_param("min_entry_probability")

                    if p_long > thresh:
                        direction = SignalDirection.LONG
                        confidence = p_long
                    elif p_short > thresh:
                        direction = SignalDirection.SHORT
                        confidence = p_short

                    # For trace/logging
                    prob = p_long  # Default to long prob for simple logging if needed
                else:
                    logger.warning(
                        f"[{self.NAME}] Unexpected model output shape: {output.shape}. Expected (1, 3)."
                    )
                    return None, 0.0, {"raw_output": output.tolist()}

            # Handle Binary Output (scalar or 1D array)
            else:
                # Could be scalar or 1D array [0.8]
                if isinstance(output, np.ndarray):
                    prob = float(output[0])
                else:
                    prob = float(output)

                if prob > self._get_param("min_entry_probability"):
                    direction = SignalDirection.LONG
                    confidence = prob

            if not direction:
                return (
                    None,
                    0.0,
                    {
                        "features": compass_features,
                        "prob": prob,
                        "threshold": self._get_param("min_entry_probability"),
                    },
                )

            # 6. Risk Calculation
            atr = float(
                compass_features.get("scalper_natr", 0.0)
            )  # Note: this is NATR (%), not ATR (Price)
            # Re-read: `scalper_natr` is in %. ATR is in Price.
            # Need ATR absolute for Price calculation.
            # `df_kline` has 'natr'. We need 'ATR_14' or calculate relative from NATR?
            # NATR = ATR / Close * 100 => ATR = NATR * Close / 100.
            current_close = float(df_kline["close"].iloc[-1])
            atr_abs = (atr * current_close) / 100.0 if atr > 0 else 0.0

            # Get Multipliers
            sl_mult = self._get_param("stop_loss_atr_multiplier")
            tp_mult = self._get_param("take_profit_atr_multiplier")

            stop_loss_price = (
                current_close - (atr_abs * sl_mult)
                if direction == SignalDirection.LONG
                else current_close + (atr_abs * sl_mult)
            )
            take_profit_price = (
                current_close + (atr_abs * tp_mult)
                if direction == SignalDirection.LONG
                else current_close - (atr_abs * tp_mult)
            )

            # Rounding
            tick_size = pair_info.get("tick_size", config.DEFAULT_TICK_SIZE)
            stop_loss_price = utils.round_price_by_tick(stop_loss_price, tick_size)
            take_profit_price = utils.round_price_by_tick(take_profit_price, tick_size)

            # Partial Exits
            partials = []
            partial_cfg = self._get_param(
                "partial_exits"
            )  # Expecting [{"fraction": 0.5, "rr_multiplier": 1.0}]
            if partial_cfg:
                base_risk = abs(current_close - stop_loss_price)
                for p in partial_cfg:
                    frac = p.get("fraction", 0.0)
                    rr = p.get("rr_multiplier", 0.0)
                    if frac > 0 and rr > 0:
                        dist = base_risk * rr
                        target_price = (
                            current_close + dist
                            if direction == SignalDirection.LONG
                            else current_close - dist
                        )
                        partials.append(
                            PartialTarget(
                                fraction=frac,
                                price=utils.round_price_by_tick(
                                    target_price, tick_size
                                ),
                            )
                        )

            # Create Signal
            signal = StrategySignal(
                strategy_name=self.NAME,
                symbol=symbol,
                direction=direction,
                stop_loss=stop_loss_price,
                take_profit=take_profit_price,
                mode=OrderMode.MARKET,
                trigger_price=current_close,
                confidence=confidence,
                details={"features": compass_features, "prob": float(confidence)},
                partial_targets=partials,
                move_sl_to_be_on_first_tp=self._get_param(
                    "move_sl_to_be_after_first_tp"
                ),
            )

            # MODIFICATION: Always return oracle_regime (if available) and features in trace
            # We need to retrieve the regime from the earlier calculation or cache
            # Since we didn't store it in a local var accessible here easily if we didn't return early,
            # we might need to refactor slightly or just pass what we have.
            # Ideally, `check_signal` logic flow should be cleaner.
            # For now, we assume 'features' are critical. 'oracle_regime' was checked earlier.
            # Let's try to pass the regime if we can.
            # Actually, let's just ensure 'features' are there. Controller can use features.
            # For Oracle, the Controller handles it via separate channel if needed,
            # OR we pass it here.

            trace_data = {
                "features": compass_features,
                "direction": direction.value,
                "prob": float(confidence),
            }
            # Try to fetch cached oracle regime from adapter/model if possible, or just skip if complex.
            # But wait, looking at flow:
            # Logic: 3. Oracle Check -> if fails, returns (regime, reason).
            # If succeeds, we are here. So regime must be 1 (AMNESIA/SAFE) or oracle disabled.
            if self._get_param("use_oracle", True) and self.oracle_model:
                trace_data["oracle_regime"] = (
                    1  # Implied because we didn't return earlier
                )

            return signal, confidence, trace_data

        except Exception as e:
            logger.error(
                f"[{self.NAME}:{symbol}] Error in prediction/signal logic: {e}",
                exc_info=True,
            )
            return None, 0.0, None

    def _get_param(self, key: str, default: Any = None) -> Any:
        """Helper to get param from config or defaults."""
        # 1. Check if configured in global config.STRATEGY_DEFAULTS specifically for this instance
        # Typically BaseStrategy handles this if we implement config loading there.
        # Here we assume 'self.config' might be populated or we use a direct config lookup.
        # For now, simplest is to use internal defaults + generic config check.
        val = config.get_strategy_param(
            self.NAME, key, self.DEFAULT_PARAMS.get(key, default)
        )
        return val
