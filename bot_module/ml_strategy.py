# bot_module/ml_strategy.py
import logging
import threading
import time
from typing import Optional, Dict, Any, Set, Tuple, Deque, List
from pathlib import Path
from decimal import ROUND_DOWN, ROUND_UP
from collections import deque  # Import deque

from bot_module.strategy import (
    BaseStrategy,
    StrategySignal,
    SignalDirection,
    OrderMode,
    PartialTarget,
)
from bot_module.feature_extractor import FeatureExtractor
from bot_module.model_pipeline import ModelPipeline, DEFAULT_PIPELINE

try:
    from bot_module import config
    from .utils import round_price_by_tick
    from bot_module.config import (
        ONLINE_MODEL_SAVE_PATH,
        ML_OFFLINE_TRAINED_MODEL_PATH,
        RETRAIN_ENABLED,
        RETRAIN_PNL_THRESHOLD_PCT,
        RETRAIN_WINDOW_SIZE,
    )

except ImportError:

    class MockMLConfig:
        ONLINE_MODEL_SAVE_PATH = Path("data/online_model.joblib")
        ML_OFFLINE_TRAINED_MODEL_PATH = Path("data/offline_trained_model.pkl")
        ML_SIMULATED_TRADES_LOG_FILE = Path("logs/ml_simulated_trades.csv")
        ML_TRAINING_REPORT_FILE = Path("logs/ml_training_report.json")
        ML_TRAINING_LABEL_LOOKAHEAD_BARS = 15
        ML_TRAINING_SIMULATE_TRADES = True
        RETRAIN_ENABLED = True
        RETRAIN_PNL_THRESHOLD_PCT = -10.0
        RETRAIN_WINDOW_SIZE = 50
        ONLINE_AGENT_PARAMS = {
            "enabled": True,
            "candle_timeframe": "1m",
            "required_confirmation": False,
            "atr_period": 14,
            "stop_loss_atr_multiplier": 1.5,
            "take_profit_atr_multiplier": 2.0,
            "min_probability_threshold": 0.70,
            "save_model_interval_seconds": 3600,
            "use_offline_model": False,  # Add for initialization
            "model_save_path": str(ONLINE_MODEL_SAVE_PATH),  # Path for saving
            "offline_model_save_path": str(
                ML_OFFLINE_TRAINED_MODEL_PATH
            ),  # Path to offline model
            "retrain_enabled": RETRAIN_ENABLED,
            "retrain_pnl_threshold_pct": RETRAIN_PNL_THRESHOLD_PCT,
            "retrain_window_size": RETRAIN_WINDOW_SIZE,
        }
        STRATEGY_DEFAULTS = {"OnlineAgentStrategy": ONLINE_AGENT_PARAMS}
        ALL_POSSIBLE_FEATURES = ["f1", "f2", "f3", "f4", "f5"]  # Stub
        ADAPTATION_ENABLED = True
        ADAPTATION_CHECK_INTERVAL = 50
        MIN_HISTORY_FOR_CORR = 100
        FEATURE_HISTORY_MAX_SIZE = 2000
        NUM_FEATURES_TO_REMOVE = 1
        NUM_FEATURES_TO_ADD = 1
        MIN_CORRELATION_THRESHOLD = -0.01

        def get_strategy_param(self, strategy_name, param_name, default=None):
            val = self.ONLINE_AGENT_PARAMS.get(param_name, default)
            # Add return of RETRAIN parameters from the stub
            if param_name == "retrain_enabled":
                return self.RETRAIN_ENABLED
            if param_name == "retrain_pnl_threshold_pct":
                return self.RETRAIN_PNL_THRESHOLD_PCT
            if param_name == "retrain_window_size":
                return self.RETRAIN_WINDOW_SIZE
            return val

    config = MockMLConfig()
    # Loading RETRAIN parameters from config
    ONLINE_MODEL_SAVE_PATH = config.ONLINE_MODEL_SAVE_PATH
    ML_OFFLINE_TRAINED_MODEL_PATH = config.ML_OFFLINE_TRAINED_MODEL_PATH
    RETRAIN_ENABLED = config.RETRAIN_ENABLED
    RETRAIN_PNL_THRESHOLD_PCT = config.RETRAIN_PNL_THRESHOLD_PCT
    RETRAIN_WINDOW_SIZE = config.RETRAIN_WINDOW_SIZE


logger = logging.getLogger("bot_module.ml_strategy")
if not logger.hasHandlers():
    logger.addHandler(logging.NullHandler())


class OnlineAgentStrategy(BaseStrategy):
    NAME = "OnlineAgentStrategy"
    _save_lock = threading.Lock()  # Keep for saving

    def __init__(self):
        super().__init__()
        # Getting parameters from config
        self.enabled = config.get_strategy_param(self.NAME, "enabled", False)
        self.candle_timeframe = config.get_strategy_param(
            self.NAME, "candle_timeframe", "1m"
        )
        self.required_confirmation = config.get_strategy_param(
            self.NAME, "required_confirmation", False
        )
        self.atr_period = config.get_strategy_param(self.NAME, "atr_period", 14)
        self.stop_loss_atr_multiplier = config.get_strategy_param(
            self.NAME, "stop_loss_atr_multiplier", 1.5
        )
        self.take_profit_atr_multiplier = config.get_strategy_param(
            self.NAME, "take_profit_atr_multiplier", 2.0
        )
        self.min_probability_threshold = config.get_strategy_param(
            self.NAME, "min_probability_threshold", 0.60
        )
        self.save_model_interval_sec = config.get_strategy_param(
            self.NAME, "save_model_interval_seconds", 3600
        )
        use_offline = config.get_strategy_param(self.NAME, "use_offline_model", False)

        # Loading the threshold for signal quality
        # Use get_strategy_param so it can be overridden in optimized_params.json
        self.min_signal_quality_score_threshold = config.get_strategy_param(
            self.NAME,
            "min_signal_quality_score_threshold",
            0.5,  # Default value (e.g., 3 out of 6 with weight 1 = 0.5)
        )

        # Get paths to models
        online_path_str = config.get_strategy_param(self.NAME, "model_save_path", None)
        offline_path_str = config.get_strategy_param(
            self.NAME, "offline_model_save_path", None
        )
        self.online_model_path = (
            Path(online_path_str) if online_path_str else ONLINE_MODEL_SAVE_PATH
        )
        self.offline_model_path = (
            Path(offline_path_str)
            if offline_path_str
            else ML_OFFLINE_TRAINED_MODEL_PATH
        )

        # Get retraining parameters
        self.retrain_enabled = config.get_strategy_param(
            self.NAME, "retrain_enabled", config.RETRAIN_ENABLED
        )
        self.retrain_pnl_threshold_pct = config.get_strategy_param(
            self.NAME, "retrain_pnl_threshold_pct", config.RETRAIN_PNL_THRESHOLD_PCT
        )
        self.retrain_window_size = config.get_strategy_param(
            self.NAME, "retrain_window_size", config.RETRAIN_WINDOW_SIZE
        )
        if self.retrain_window_size <= 0:
            self.retrain_window_size = 1

        initial_model_path = (
            self.offline_model_path
            if use_offline
            and self.offline_model_path
            and self.offline_model_path.exists()
            else self.online_model_path
        )
        logger.info(
            f"[{self.NAME}] Initial model path set to: {initial_model_path} (Using offline: {initial_model_path == self.offline_model_path})"
        )

        self.feature_extractor = FeatureExtractor()
        self.model_pipeline = ModelPipeline(
            pipeline=DEFAULT_PIPELINE.clone(), model_path=initial_model_path
        )
        self.model_pipeline.load_model(initial_model_path)
        self.feature_extractor.set_active_features(self.model_pipeline.active_features)

        self._last_model_save_time = time.time()
        self.rolling_pnl_buffer: Deque[float] = deque(maxlen=self.retrain_window_size)
        self.current_rolling_pnl_sum: float = 0.0

        # Use global config for signal quality threshold, if it exists,
        # otherwise default from STRATEGY_DEFAULTS['OnlineAgentStrategy']
        self.min_signal_quality_score_threshold = config.get_strategy_param(
            self.NAME,
            "min_signal_quality_score_threshold",
            getattr(
                config, "min_signal_quality_score_threshold", 0.5
            ),  # Global config as fallback
        )

        logger.info(f"[{self.NAME}] Initialized. Timeframe={self.candle_timeframe}")
        logger.info(
            f"[{self.NAME}] Min Probability Threshold: {self.min_probability_threshold:.2f}"
        )
        # Log new threshold
        logger.info(
            f"[{self.NAME}] Min Signal Quality Score Threshold: {self.min_signal_quality_score_threshold:.3f}"
        )
        logger.info(f"[{self.NAME}] Retraining Enabled: {self.retrain_enabled}")
        if self.retrain_enabled:
            logger.info(
                f"[{self.NAME}] Retraining PnL Threshold: {self.retrain_pnl_threshold_pct:.2f}% over {self.retrain_window_size} trades"
            )

    def load_pipeline_model(self, path: Optional[Path] = None) -> bool:
        """Loads the ModelPipeline state and updates the active extractor features."""
        load_path = path if path else self.online_model_path
        if not load_path:
            logger.error(
                f"[{self.NAME}] Cannot load model: No valid path provided or configured."
            )
            return False

        logger.info(
            f"[{self.NAME}] Attempting to load model pipeline from: {load_path}"
        )
        # Create a new instance and load into it
        self.model_pipeline = ModelPipeline(model_path=load_path)
        loaded_ok = self.model_pipeline.load_model(load_path)

        if loaded_ok:
            logger.info(
                f"[{self.NAME}] Model pipeline loaded successfully from {load_path}. Steps: {self.model_pipeline.steps_processed}"
            )
        else:
            logger.warning(
                f"[{self.NAME}] Failed to load model from {load_path}. Pipeline might be in default state."
            )

        # Update active features in FeatureExtractor in any case
        self.feature_extractor.set_active_features(self.model_pipeline.active_features)
        # Reset performance counters on load
        self._reset_performance_trackers()
        return loaded_ok

    def save_pipeline_model(self, path: Optional[Path] = None):
        """Saves the CURRENT (online) model."""
        save_path = path if path else self.online_model_path
        if not save_path:
            logger.warning(
                f"[{self.NAME}] Cannot save model: Online model path not configured."
            )
            return
        logger.info(f"[{self.NAME}] Saving model pipeline to: {save_path}")
        self.model_pipeline.save_model(
            save_path
        )  # ModelPipeline logs success/error itself
        self._last_model_save_time = time.time()

    def reset_pipeline(self):
        """Resets the pipeline to the default state and activates all features."""
        logger.warning(f"[{self.NAME}] Resetting model pipeline to default state.")
        # Call the reset method in ModelPipeline
        self.model_pipeline.reset_pipeline()
        # Synchronize extractor features
        self.feature_extractor.set_active_features(self.model_pipeline.active_features)
        # Resetting performance counters
        self._reset_performance_trackers()

    @property
    def required_data_types(self) -> Set[str]:
        tf = getattr(self, "candle_timeframe", None) or getattr(
            self, "entry_timeframe", None
        )
        req = set()
        if tf:
            req.add(f"kline_{tf}")
        if self.feature_extractor:
            if self.feature_extractor.aggtrade_feature_configs:
                req.add("aggTrade")
        if not req:
            req.add("kline_1m")
        return req

    async def check_signal(
        self, pair_info: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Optional[StrategySignal]:
        """
        Asynchronous signal check by the ML agent.
        The model predicts the probability of success for a LONG trade (label 1).
        A LONG signal is generated when P(1) > threshold.
        A SHORT signal is generated when P(0) > threshold (i.e., P(1) < 1 - threshold).
        """
        if not self.enabled:
            return None
        symbol = pair_info.get("symbol", "Unknown")
        log_prefix = f"[{self.NAME}:{symbol}]"

        features_norm, features_raw = self._extract_and_normalize(
            market_data, pair_info
        )
        if not features_norm or not features_raw:
            return None

        pred = self.model_pipeline.predict_one(features_norm)
        proba = self.model_pipeline.predict_proba_one(features_norm)
        if proba is None:
            logger.warning(
                f"{log_prefix} predict_proba_one returned None. Cannot generate signal."
            )
            return None

        prob_1 = proba.get(1, 0.0)
        prob_0 = proba.get(0, 0.0)
        direction: Optional[SignalDirection] = None
        confidence: float = 0.0

        # USE self.min_probability_threshold FROM THE INSTANCE
        if (
            prob_1 >= self.min_probability_threshold
        ):  # min_probability_threshold is already set in __init__
            direction = SignalDirection.LONG
            confidence = prob_1
        elif prob_0 >= self.min_probability_threshold:
            direction = SignalDirection.SHORT
            confidence = prob_0

        if direction is None:
            return None

        quality_score = features_norm.get("signal_quality_score", 0.0)
        if (
            quality_score < self.min_signal_quality_score_threshold
        ):  # Use threshold from instance
            logger.debug(
                f"{log_prefix} Signal {direction.name} REJECTED by quality score: {quality_score:.3f} < {self.min_signal_quality_score_threshold:.3f}"
            )
            return None

        logger.info(
            f"{log_prefix} Signal {direction.name} PASSED quality score: {quality_score:.3f}"
        )

        kline_key = f"kline_{self.candle_timeframe}"
        if kline_key not in market_data or market_data[kline_key].empty:
            logger.warning(f"{log_prefix} Missing kline data for {kline_key}.")
            return None
        try:
            trigger_price = float(market_data[kline_key]["close"].iloc[-1])
        except Exception as e:
            logger.error(f"{log_prefix} Could not get trigger price: {e}")
            return None

        atr = pair_info.get("atr")
        tick_size = pair_info.get("tick_size", config.DEFAULT_TICK_SIZE)
        sl, tp_final_atr = self._calculate_risk(
            trigger_price, atr, direction, tick_size
        )  # tp_final_atr is the base TP by ATR
        if sl <= 0 or tp_final_atr <= 0:
            logger.error(
                f"{log_prefix} Invalid SL/TP_ATR calculated: SL={sl}, TP_ATR={tp_final_atr}."
            )
            return None

        # Calculation of partial TPs and final TP for the ML agent
        rr_config_raw = self._get_param("partial_exit_rr_config", [])
        move_sl_be = self._get_param("move_sl_to_be_on_first_tp", True)
        final_tp_rr_param = self._get_param("final_tp_rr")  # Can be None

        partial_targets_list: Optional[List[PartialTarget]] = None
        final_take_profit_value: Optional[float] = (
            tp_final_atr  # Use TP by ATR by default
        )

        rr_config_ml = None
        if isinstance(rr_config_raw, list) and all(
            isinstance(t, (tuple, list)) and len(t) == 2 for t in rr_config_raw
        ):
            try:
                rr_config_ml = [(float(r), float(f)) for r, f in rr_config_raw]
            except (ValueError, TypeError):
                logger.warning(
                    f"{log_prefix} Invalid format for ML agent partial_exit_rr_config."
                )

        if rr_config_ml:
            partial_targets_list = self._calculate_partial_targets_from_rr(
                entry_price=trigger_price,  # For MARKET order entry == trigger
                stop_loss_price=sl,
                direction=direction,
                rr_targets_config=rr_config_ml,
                tick_size=tick_size,
            )

        cumulative_partial_fraction = (
            sum(t.fraction for t in partial_targets_list)
            if partial_targets_list
            else 0.0
        )

        if cumulative_partial_fraction < (1.0 - 1e-9):  # If partials do not close 100%
            if final_tp_rr_param is not None and final_tp_rr_param > 0:
                risk_distance = abs(trigger_price - sl)
                if risk_distance > 1e-9:
                    final_tp_raw_rr = (
                        trigger_price + risk_distance * final_tp_rr_param
                        if direction == SignalDirection.LONG
                        else trigger_price - risk_distance * final_tp_rr_param
                    )

                    # Adjustment by MIN_PARTIAL_TP_DISTANCE_PCT
                    min_tp_distance_pct_cfg = getattr(
                        config, "MIN_PARTIAL_TP_DISTANCE_PCT", 0.002
                    )
                    min_profit_abs_final = trigger_price * min_tp_distance_pct_cfg
                    target_price_raw_min_pct_final = (
                        trigger_price + min_profit_abs_final
                        if direction == SignalDirection.LONG
                        else trigger_price - min_profit_abs_final
                    )
                    final_tp_raw_adjusted_rr = (
                        max(final_tp_raw_rr, target_price_raw_min_pct_final)
                        if direction == SignalDirection.LONG
                        else min(final_tp_raw_rr, target_price_raw_min_pct_final)
                    )

                    rounding_final_rr = (
                        ROUND_UP if direction == SignalDirection.LONG else ROUND_DOWN
                    )
                    final_tp_from_rr = round_price_by_tick(
                        final_tp_raw_adjusted_rr, tick_size, rounding_final_rr
                    )

                    # Check that TP by R/R is no worse than by ATR (or not None)
                    if final_tp_from_rr is not None and (
                        (
                            direction == SignalDirection.LONG
                            and final_tp_from_rr > trigger_price
                        )
                        or (
                            direction == SignalDirection.SHORT
                            and final_tp_from_rr < trigger_price
                        )
                    ):
                        final_take_profit_value = final_tp_from_rr
                        logger.debug(
                            f"{log_prefix} Using final TP based on R/R: {final_take_profit_value:.8f}"
                        )
                    else:
                        logger.debug(
                            f"{log_prefix} Final TP from R/R invalid or worse than entry. Using ATR-based TP: {tp_final_atr:.8f}"
                        )
                        final_take_profit_value = tp_final_atr  # Fallback to ATR TP
                else:  # Zero risk, use ATR TP
                    final_take_profit_value = tp_final_atr
            # If final_tp_rr_param is not set, final_take_profit_value is already equal to tp_final_atr
        else:  # Partial closes cover 100%
            final_take_profit_value = None  # Final TP is not needed
            logger.debug(f"{log_prefix} Partials cover 100%. Final TP is None.")

        # Collect details for the signal
        details = {
            "model_features_raw": features_raw,
            "model_features_norm": features_norm,
            "prediction": int(pred)
            if pred is not None
            else None,  # Class predicted by the model
            "prediction_proba": proba,  # Probabilities for all classes
            "signal_quality_score": quality_score,
            "atr": f"{atr:.8f}" if atr else "N/A",
            "trigger_price_raw": f"{trigger_price:.8f}",
        }

        # Create signal
        signal = StrategySignal(
            strategy_name=self.NAME,
            symbol=symbol,
            direction=direction,
            stop_loss=sl,
            take_profit=final_take_profit_value,
            mode=OrderMode.MARKET,
            trigger_price=trigger_price,
            confidence=confidence,
            details=details,
            partial_targets=partial_targets_list,
            move_sl_to_be_on_first_tp=move_sl_be,
        )

        # Processing the training buffer and saving the model (if needed)
        # self.model_pipeline.process_training_buffer() # Not needed in real-time, done in learn_from_trade
        self._save_model_periodically()

        return signal

    # Adapted check_signal_sync
    def check_signal_sync(
        self, pair_info: Dict[str, Any], market_data: Dict[str, Any]
    ) -> Optional[StrategySignal]:
        # Similar changes as in async check_signal
        if not self.enabled:
            return None
        symbol = pair_info.get("symbol", "Unknown")

        features_norm, features_raw = self._extract_and_normalize(
            market_data, pair_info
        )
        if not features_norm or not features_raw:
            return None

        pred = self.model_pipeline.predict_one(features_norm)
        proba = self.model_pipeline.predict_proba_one(features_norm)
        if proba is None:
            return None

        prob_1 = proba.get(1, 0.0)
        prob_0 = proba.get(0, 0.0)
        direction: Optional[SignalDirection] = None
        confidence: float = 0.0

        if prob_1 >= self.min_probability_threshold:
            direction = SignalDirection.LONG
            confidence = prob_1
        elif prob_0 >= self.min_probability_threshold:
            direction = SignalDirection.SHORT
            confidence = prob_0

        if direction is None:
            return None

        quality_score = features_norm.get("signal_quality_score", 0.0)
        if quality_score < self.min_signal_quality_score_threshold:
            return None

        kline_key = f"kline_{self.candle_timeframe}"
        if kline_key not in market_data or market_data[kline_key].empty:
            return None
        try:
            trigger_price = float(market_data[kline_key]["close"].iloc[-1])
        except Exception:
            return None

        atr = pair_info.get("atr")
        tick_size = pair_info.get("tick_size", config.DEFAULT_TICK_SIZE)
        sl, tp_final_atr = self._calculate_risk(
            trigger_price, atr, direction, tick_size
        )
        if sl <= 0 or tp_final_atr <= 0:
            return None

        rr_config_raw = self._get_param("partial_exit_rr_config", [])
        move_sl_be = self._get_param("move_sl_to_be_on_first_tp", True)
        final_tp_rr_param = self._get_param("final_tp_rr")
        partial_targets_list: Optional[List[PartialTarget]] = None
        final_take_profit_value: Optional[float] = tp_final_atr

        rr_config_ml = None
        if isinstance(rr_config_raw, list) and all(
            isinstance(t, (tuple, list)) and len(t) == 2 for t in rr_config_raw
        ):
            try:
                rr_config_ml = [(float(r), float(f)) for r, f in rr_config_raw]
            except (ValueError, TypeError):
                pass

        if rr_config_ml:
            partial_targets_list = self._calculate_partial_targets_from_rr(
                trigger_price, sl, direction, rr_config_ml, tick_size
            )

        cumulative_partial_fraction = (
            sum(t.fraction for t in partial_targets_list)
            if partial_targets_list
            else 0.0
        )
        if cumulative_partial_fraction < (1.0 - 1e-9):
            if final_tp_rr_param is not None and final_tp_rr_param > 0:
                risk_distance = abs(trigger_price - sl)
                if risk_distance > 1e-9:
                    final_tp_raw_rr = (
                        trigger_price + risk_distance * final_tp_rr_param
                        if direction == SignalDirection.LONG
                        else trigger_price - risk_distance * final_tp_rr_param
                    )
                    min_tp_distance_pct_cfg = getattr(
                        config, "MIN_PARTIAL_TP_DISTANCE_PCT", 0.002
                    )
                    min_profit_abs_final = trigger_price * min_tp_distance_pct_cfg
                    target_price_raw_min_pct_final = (
                        trigger_price + min_profit_abs_final
                        if direction == SignalDirection.LONG
                        else trigger_price - min_profit_abs_final
                    )
                    final_tp_raw_adjusted_rr = (
                        max(final_tp_raw_rr, target_price_raw_min_pct_final)
                        if direction == SignalDirection.LONG
                        else min(final_tp_raw_rr, target_price_raw_min_pct_final)
                    )
                    rounding_final_rr = (
                        ROUND_UP if direction == SignalDirection.LONG else ROUND_DOWN
                    )
                    final_tp_from_rr = round_price_by_tick(
                        final_tp_raw_adjusted_rr, tick_size, rounding_final_rr
                    )
                    if final_tp_from_rr is not None and (
                        (
                            direction == SignalDirection.LONG
                            and final_tp_from_rr > trigger_price
                        )
                        or (
                            direction == SignalDirection.SHORT
                            and final_tp_from_rr < trigger_price
                        )
                    ):
                        final_take_profit_value = final_tp_from_rr
        else:
            final_take_profit_value = None

        details = {
            "model_features_raw": features_raw,
            "model_features_norm": features_norm,
            "prediction": int(pred) if pred is not None else None,
            "prediction_proba": proba,
            "signal_quality_score": quality_score,
            "atr": f"{atr:.8f}" if atr else "N/A",
            "trigger_price_raw": f"{trigger_price:.8f}",
        }

        return StrategySignal(
            strategy_name=self.NAME,
            symbol=symbol,
            direction=direction,
            stop_loss=sl,
            take_profit=final_take_profit_value,
            mode=OrderMode.MARKET,
            trigger_price=trigger_price,
            confidence=confidence,
            details=details,
            partial_targets=partial_targets_list,
            move_sl_to_be_on_first_tp=move_sl_be,
        )

    def learn_from_trade(
        self, client_order_id: str, pnl: float, trade_open_details: Dict[str, Any]
    ):
        """
        Processes the trade result, buffers it for training,
        updates performance statistics, and checks if a model reset is necessary.
        """
        log_prefix = f"[{self.NAME}:Learn]"
        if not isinstance(trade_open_details, dict):
            logger.error(
                f"{log_prefix} Invalid trade_open_details format (ClientOrderID: {client_order_id})."
            )
            return

        # Extract RAW features
        raw_features = trade_open_details.get("model_features_raw")
        if raw_features is None or not isinstance(raw_features, dict):
            logger.error(
                f"{log_prefix} Cannot learn: 'model_features_raw' missing or invalid (ClientOrderID: {client_order_id})."
            )
            return
        # End of extraction

        y_true = 1 if pnl > 0 else 0
        y_pred = trade_open_details.get("prediction")
        proba = trade_open_details.get("prediction_proba")
        sample_weight = abs(pnl) if pnl != 0 else 0.1  # Small weight for break-even

        # Form an example for the buffer
        training_example = {
            "raw_features": raw_features,  # Pass RAW features
            "y_true": y_true,
            "y_pred": y_pred,
            "proba": proba,
            "weight": sample_weight,
            "pnl": pnl,  # Actual PnL
        }

        # Buffering the example
        self.model_pipeline.buffer_training_example(training_example)

        # Performance update and check
        self._update_performance_stats(pnl)
        if self.retrain_enabled:
            self._check_performance_and_reset()

    def _save_model_periodically(self) -> None:
        """Saves the CURRENT (online) model periodically."""
        now = time.time()
        if now - self._last_model_save_time < self.save_model_interval_sec:
            return
        with self._save_lock:
            # Re-check time under lock
            if now - self._last_model_save_time >= self.save_model_interval_sec:
                # Always save to online_model_path
                self.save_pipeline_model(self.online_model_path)
                # Last save time is updated inside save_pipeline_model

    def _extract_and_normalize(
        self, market_data: Dict[str, Any], pair_info: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, float]], Optional[Dict[str, Any]]]:
        kkey = f"kline_{self.candle_timeframe}"
        df_kline = market_data.get(kkey)
        list_agg = market_data.get("aggTrade")
        if df_kline is None or df_kline.empty:
            logger.debug(f"[{self.NAME}] No data for {kkey}")
            return None, None
        try:
            current_candle_series = df_kline.iloc[-1]
            current_candle_data = current_candle_series.to_dict()
            for key, val in pair_info.items():
                if (
                    key.startswith(("EMA_", "SMA_", "RSI_", "ATR_"))
                    and key not in current_candle_data
                ):
                    current_candle_data[key] = val
            current_candle_data["natr"] = pair_info.get("natr", 0.0)
            current_index = len(df_kline) - 1
            current_timestamp_ms = int(df_kline.index[-1].value / 1_000_000)
            if len(df_kline.index) > 1:
                current_timestamp_ms += int(
                    (df_kline.index[-1] - df_kline.index[-2]).total_seconds() * 1000
                )
            else:
                current_timestamp_ms += 60000
        except Exception as e:
            logger.error(f"[{self.NAME}] Error preparing current candle data: {e}")
            return None, None
        raw_features = self.feature_extractor.extract_features_optimized(
            current_candle_data=current_candle_data,
            agg_trades_list=list_agg,
            full_kline_history=df_kline,
            current_index=current_index,
            current_timestamp_ms=current_timestamp_ms,
        )
        if not raw_features:
            return None, None
        normalized_features = self.feature_extractor.normalize_features(raw_features)
        return normalized_features, raw_features

    def _ensure_proba(
        self, pred: Any, proba: Optional[Dict[Any, float]]
    ) -> Dict[int, float]:
        if proba is None and pred is not None:
            lbl = int(pred)
            return {1: float(lbl == 1), 0: float(lbl == 0)}
        return proba or {0: 0.0, 1: 0.0}

    def _decide_direction(
        self, proba: Dict[int, float]
    ) -> Tuple[Optional[SignalDirection], float]:
        p1, p0 = proba.get(1, 0.0), proba.get(0, 0.0)
        if p1 >= self.min_probability_threshold:
            return SignalDirection.LONG, p1
        if p0 >= self.min_probability_threshold:
            return SignalDirection.SHORT, p0
        return None, 0.0

    def _calculate_risk(
        self,
        price: float,
        atr: Optional[float],
        direction: SignalDirection,
        tick_size: Optional[float],
    ) -> Tuple[float, float]:
        if atr is None or atr <= 0:
            logger.warning(
                f"[{self.NAME}] Invalid ATR ({atr}) for risk calculation. Using default small values."
            )
            sl = price * 0.999 if direction == SignalDirection.LONG else price * 1.001
            tp = price * 1.001 if direction == SignalDirection.LONG else price * 0.999
            return sl, tp
        if direction == SignalDirection.LONG:
            sl = self._round_price(
                price - atr * self.stop_loss_atr_multiplier, tick_size, ROUND_DOWN
            )
            tp = self._round_price(
                price + atr * self.take_profit_atr_multiplier, tick_size, ROUND_UP
            )
        else:
            sl = self._round_price(
                price + atr * self.stop_loss_atr_multiplier, tick_size, ROUND_UP
            )
            tp = self._round_price(
                price - atr * self.take_profit_atr_multiplier, tick_size, ROUND_DOWN
            )
        return sl, tp

    # METHODS for performance management
    def _reset_performance_trackers(self):
        """Resets counters for performance tracking."""
        self.trades_since_last_check = 0
        self.rolling_pnl_buffer.clear()
        self.current_rolling_pnl_pct = 0.0
        self.balance_at_window_start = (
            0.0  # Will be set at the first trade of the window
        )
        logger.debug(f"[{self.NAME}] Performance trackers reset.")

    def _update_performance_stats(self, pnl: float):
        """Updates PnL statistics for the window."""
        if not self.retrain_enabled or self.retrain_window_size <= 0:
            return

        # If the buffer is empty, remember the "initial balance" of the window (approximately)
        if not self.rolling_pnl_buffer:
            # Use the current balance from RiskManager (if available)
            # Or simply assume some base balance
            # This is not ideal, but it provides an estimate for the % calculation
            # TODO: Get real balance from RiskManager? Difficult due to asynchrony.
            # For now, we use PnL as an absolute measure or a simple divisor.
            self.balance_at_window_start = 10000.0  # Stub
            logger.debug(
                f"[{self.NAME}] Performance window started. Approx start balance: {self.balance_at_window_start:.2f}"
            )

        self.rolling_pnl_buffer.append(pnl)
        self.trades_since_last_check += 1

        # Recalculate % PnL for the window
        total_pnl_in_window = sum(self.rolling_pnl_buffer)
        if self.balance_at_window_start > 1e-9:
            self.current_rolling_pnl_pct = (
                total_pnl_in_window / self.balance_at_window_start
            ) * 100.0
        else:
            self.current_rolling_pnl_pct = (
                -999.0 if total_pnl_in_window < 0 else 0.0
            )  # If no balance

        # logger.debug(f"[{self.NAME}] Performance Updated: Trades={self.trades_since_last_check}/{self.retrain_window_size}, Window PnL Sum={total_pnl_in_window:.2f}, Window PnL Pct={self.current_rolling_pnl_pct:.2f}%")

    def _reset_performance_trackers(self):
        """Resets counters for performance tracking."""
        self.rolling_pnl_buffer.clear()
        self.current_rolling_pnl_sum = 0.0
        logger.debug(f"[{self.NAME}] Performance trackers reset.")

    def _update_performance_stats(self, pnl: float):
        """Updates PnL statistics for the window."""
        if not self.retrain_enabled or self.retrain_window_size <= 0:
            return

        # If the buffer is already full, remove the old value from the sum
        if len(self.rolling_pnl_buffer) == self.retrain_window_size:
            oldest_pnl = self.rolling_pnl_buffer[0]  # Get before adding a new one
            self.current_rolling_pnl_sum -= oldest_pnl

        # Add new PnL
        self.rolling_pnl_buffer.append(pnl)
        self.current_rolling_pnl_sum += pnl

        # logger.debug(f"[{self.NAME}] Performance Updated: Window Size={len(self.rolling_pnl_buffer)}/{self.retrain_window_size}, Window PnL Sum={self.current_rolling_pnl_sum:.2f}")

    def _check_performance_and_reset(self):
        """Checks performance and triggers reset/retraining if necessary."""
        log_prefix = f"[{self.NAME}:PerfCheck]"
        # Check only if the window is full
        if len(self.rolling_pnl_buffer) < self.retrain_window_size:
            return

        logger.info(
            f"{log_prefix} Checking performance window ({self.retrain_window_size} trades). PnL Sum: {self.current_rolling_pnl_sum:.2f}"
        )

        # Simplified check: currently using absolute PnL < 0 as a trigger
        # TODO: Implement a more reliable % PnL calculation if needed
        performance_below_threshold = False
        if self.retrain_pnl_threshold_pct < 0:  # If threshold is a negative %
            # Check that the sum of PnL in the window is negative
            # (More complex logic with % requires knowledge of the window's initial balance)
            if self.current_rolling_pnl_sum < 0:
                # Here you can add a more complex calculation of % drawdown if balance is available
                # For now, we just consider a negative PnL sum as poor performance
                performance_below_threshold = True
                logger.warning(
                    f"{log_prefix} Performance window PnL is negative ({self.current_rolling_pnl_sum:.2f}). Treating as below threshold."
                )
        # If the threshold is 0 or positive, this logic will not work (which is logical)

        if performance_below_threshold:
            logger.critical(
                f"{log_prefix} Poor performance detected! PnL Sum {self.current_rolling_pnl_sum:.2f} over last {self.retrain_window_size} trades triggers reset/reload."
            )
            self._handle_poor_performance()
        # else:
        # logger.info(f"{log_prefix} Performance is acceptable.")

    def _handle_poor_performance(self):
        """Handles a poor performance situation: attempts to load an offline model or resets."""
        log_prefix = f"[{self.NAME}:HandlePoorPerf]"
        logger.warning(f"{log_prefix} Handling poor performance...")

        offline_model_available = (
            self.offline_model_path and self.offline_model_path.exists()
        )
        # Check which path is currently being used in the pipeline
        currently_using_offline = (
            self.model_pipeline.model_path == self.offline_model_path
        )

        if offline_model_available and not currently_using_offline:
            logger.warning(
                f"{log_prefix} Attempting to switch to offline trained model: {self.offline_model_path}"
            )
            if self.load_pipeline_model(self.offline_model_path):
                logger.critical(
                    f"{log_prefix} Successfully switched to offline model due to poor performance."
                )
                # Performance reset has already occurred in load_pipeline_model
                # Optional: run feature adaptation immediately
                if self.model_pipeline.adaptation_enabled:
                    logger.info(
                        f"{log_prefix} Triggering feature adaptation after loading offline model."
                    )
                    self.model_pipeline._adapt_features()
                return  # Exit after successful model change
            else:
                logger.error(
                    f"{log_prefix} Failed to load offline model. Proceeding with pipeline reset."
                )
        elif currently_using_offline:
            logger.warning(
                f"{log_prefix} Already using the offline model, but performance is still poor. Resetting pipeline."
            )
        else:  # Offline model is unavailable
            logger.warning(
                f"{log_prefix} Offline model not available ({self.offline_model_path}). Resetting pipeline."
            )

        # Reset pipeline to default state
        self.reset_pipeline()
        # Performance reset has already occurred in reset_pipeline
        logger.critical(
            f"{log_prefix} Pipeline reset to default state due to poor performance."
        )
        # Optional: run feature adaptation immediately
        if self.model_pipeline.adaptation_enabled:
            logger.info(
                f"{log_prefix} Triggering feature adaptation after pipeline reset."
            )
            self.model_pipeline._adapt_features()
