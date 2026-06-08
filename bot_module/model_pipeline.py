# bot_module/model_pipeline.py

import logging
import joblib
from typing import Dict, Any, Optional, Union, List, Set, Tuple
from pathlib import Path
import math
import pandas as pd
import random
from collections import deque  # Use deque for feature history

from river import compose, linear_model, metrics, optim, preprocessing

# Import config for ALL_POSSIBLE_FEATURES and adaptation parameters
try:
    from bot_module import config

    # Getting adaptation parameters from config
    ADAPTATION_ENABLED = getattr(config, "ADAPTATION_ENABLED", True)
    ADAPTATION_CHECK_INTERVAL = getattr(config, "ADAPTATION_CHECK_INTERVAL", 50)
    MIN_HISTORY_FOR_CORR = getattr(config, "MIN_HISTORY_FOR_CORR", 100)
    FEATURE_HISTORY_MAX_SIZE = getattr(config, "FEATURE_HISTORY_MAX_SIZE", 2000)
    NUM_FEATURES_TO_REMOVE = getattr(config, "NUM_FEATURES_TO_REMOVE", 1)
    NUM_FEATURES_TO_ADD = getattr(config, "NUM_FEATURES_TO_ADD", 1)
    MIN_CORRELATION_THRESHOLD = getattr(config, "MIN_CORRELATION_THRESHOLD", -0.01)
    ALL_POSSIBLE_FEATURES = getattr(config, "ALL_POSSIBLE_FEATURES", [])
except ImportError:
    # Stub if running separately
    class MockMPConfig:
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
        ADAPTATION_ENABLED = True
        ADAPTATION_CHECK_INTERVAL = 50
        MIN_HISTORY_FOR_CORR = 100
        FEATURE_HISTORY_MAX_SIZE = 2000
        NUM_FEATURES_TO_REMOVE = 1
        NUM_FEATURES_TO_ADD = 1
        MIN_CORRELATION_THRESHOLD = -0.01

    config = MockMPConfig()
    ADAPTATION_ENABLED = config.ADAPTATION_ENABLED
    ADAPTATION_CHECK_INTERVAL = config.ADAPTATION_CHECK_INTERVAL
    MIN_HISTORY_FOR_CORR = config.MIN_HISTORY_FOR_CORR
    FEATURE_HISTORY_MAX_SIZE = config.FEATURE_HISTORY_MAX_SIZE
    NUM_FEATURES_TO_REMOVE = config.NUM_FEATURES_TO_REMOVE
    NUM_FEATURES_TO_ADD = config.NUM_FEATURES_TO_ADD
    MIN_CORRELATION_THRESHOLD = config.MIN_CORRELATION_THRESHOLD
    ALL_POSSIBLE_FEATURES = config.ALL_POSSIBLE_FEATURES

logger = logging.getLogger("bot_module.model_pipeline")
if not logger.hasHandlers():
    logger.addHandler(logging.NullHandler())

__version__ = "1.5"  # Update version (adaptation added)

DEFAULT_PIPELINE = compose.Pipeline(
    ("scaler", preprocessing.StandardScaler()),
    (
        "model",
        linear_model.LogisticRegression(optimizer=optim.Adam(lr=0.005), l2=0.001),
    ),
)

DEFAULT_METRICS: Dict[str, metrics.base.Metric] = {
    "accuracy": metrics.Accuracy(),
    "f1": metrics.F1(),
    "log_loss": metrics.LogLoss(),
    "roc_auc": metrics.ROCAUC(),
}


class ModelPipeline:
    def __init__(
        self,
        pipeline: Optional[compose.Pipeline] = None,
        metric_trackers: Optional[Dict[str, metrics.base.Metric]] = None,
        model_path: Optional[Path] = None,
        initial_features: Optional[
            Set[str]
        ] = None,  # Leave the possibility to set initial features
        min_correlation_threshold: Optional[float] = None,  # New parameter
    ):
        self.pipeline = (
            pipeline.clone() if pipeline is not None else DEFAULT_PIPELINE.clone()
        )
        self.metric_trackers = {
            k: v.clone() for k, v in (metric_trackers or DEFAULT_METRICS).items()
        }
        # Use the passed threshold or the global default
        self.min_correlation_threshold = (
            min_correlation_threshold
            if min_correlation_threshold is not None
            else MIN_CORRELATION_THRESHOLD
        )
        self.model_path = model_path
        self.steps_processed = 0
        self.training_buffer: List[Dict[str, Any]] = []

        # ATTRIBUTES for adaptation
        # active_features is initialized during loading or by default
        self.active_features: Set[str] = (
            initial_features
            if initial_features is not None
            else set(ALL_POSSIBLE_FEATURES)
        )
        # Use deque for feature/pnl history
        self.feature_pnl_history: deque[Tuple[Dict[str, float], float]] = deque(
            maxlen=FEATURE_HISTORY_MAX_SIZE
        )
        self.trades_processed_since_adapt_check = 0

        # Loading will restore everything, including active_features
        if self.model_path:
            self.load_model(self.model_path)
        else:
            # If the model doesn't load, use initial_features or all possible
            self.active_features = (
                initial_features
                if initial_features is not None
                else set(ALL_POSSIBLE_FEATURES)
            )

        logger.info(
            f"ModelPipeline v{__version__} initialized. Pipeline={self.pipeline}"
        )
        logger.info(f"Adaptation enabled: {ADAPTATION_ENABLED}")
        logger.info(
            f"Initially active features ({len(self.active_features)}): {self.active_features}"
        )

    def _filter_features(self, features: Dict[str, float]) -> Dict[str, float]:
        """Selects only active features from the dictionary."""
        # Check self.active_features
        if not self.active_features:  # If None or an empty set, use all
            logger.warning("Active features set is empty! Using all provided features.")
            return features
        return {k: v for k, v in features.items() if k in self.active_features}

    def predict_one(self, features: Dict[str, float]) -> Optional[Any]:
        if not features:
            return None
        filtered_features = self._filter_features(features)  # Filter
        if not filtered_features:
            logger.warning("No active features left after filtering for predict_one.")
            return None
        try:
            return self.pipeline.predict_one(filtered_features)
        except Exception:
            logger.error("Error in predict_one", exc_info=True)
            return None

    def predict_proba_one(
        self, features: Dict[str, float]
    ) -> Optional[Dict[Any, float]]:
        if not features:
            return None
        filtered_features = self._filter_features(features)  # Filter
        if not filtered_features:
            logger.warning(
                "No active features left after filtering for predict_proba_one."
            )
            return None
        try:
            last_step = list(self.pipeline.steps.values())[-1]
            if hasattr(last_step, "predict_proba_one"):
                return self.pipeline.predict_proba_one(filtered_features)
            return None
        except Exception:
            logger.error("Error in predict_proba_one", exc_info=True)
            return None

    def learn_one(
        self,
        features: Dict[str, float],
        y_true: Any,
        y_pred: Optional[Any] = None,
        proba: Optional[Dict[Any, float]] = None,
        weight: Optional[float] = None,
    ) -> None:
        """Trains the model on a single example (with active features) and updates metrics."""
        if not features:
            return
        filtered_features = self._filter_features(features)  # Filter
        if not filtered_features:
            logger.warning("No active features left after filtering for learn_one.")
            return
        try:
            if proba is None:
                proba = self.predict_proba_one(filtered_features)  # Use filtered
            if y_pred is None:
                y_pred = self.predict_one(filtered_features)  # Use filtered

            for name, metric in self.metric_trackers.items():
                try:
                    if (
                        isinstance(metric, (metrics.LogLoss, metrics.ROCAUC))
                        and proba is not None
                    ):
                        metric.update(y_true=y_true, y_pred=proba)
                    elif y_pred is not None:
                        metric.update(y_true=y_true, y_pred=y_pred)
                except Exception as e_metric:
                    logger.warning(f"Metric '{name}' update failed: {e_metric}")

            self.pipeline.learn_one(
                filtered_features, y_true, sample_weight=weight
            )  # Use filtered
            self.steps_processed += 1

        except Exception as e_learn:
            logger.error(f"Error in learn_one: {e_learn}", exc_info=True)

    def buffer_training_example(self, example: Dict[str, Any]) -> None:
        if (
            not isinstance(example, dict)
            or "features" not in example
            or "y_true" not in example
        ):
            logger.warning("Invalid training example structure")
            return
        # Add pnl
        example["pnl"] = example.get(
            "pnl", example.get("weight", 0.0)
        )  # pnl or fallback to weight
        self.training_buffer.append(example)

    def process_training_buffer(self) -> None:
        if not self.training_buffer:
            return
        log_prefix = "[MP_ProcessBuffer]"
        logger.debug(
            f"{log_prefix} Processing {len(self.training_buffer)} buffered examples..."
        )
        processed_count = 0
        # Use a copy of the buffer for iteration to avoid issues when modifying
        buffer_copy = self.training_buffer[:]
        self.training_buffer.clear()  # Clear the original buffer

        for ex in buffer_copy:
            try:
                features = ex.get("features")
                pnl = ex.get("pnl", 0.0)  # Get pnl
                weight = ex.get("weight")  # Get weight (can be None)

                if not isinstance(features, dict):
                    logger.warning(
                        f"{log_prefix} Skipping example with invalid features."
                    )
                    continue

                # Save the FULL set of features and pnl for analysis
                # Use deque's append, it will handle maxlen itself
                if isinstance(pnl, (int, float)):
                    self.feature_pnl_history.append((features.copy(), float(pnl)))

                # Perform training on an example
                self.learn_one(
                    features=features,  # learn_one will filter by active_features itself
                    y_true=ex["y_true"],
                    y_pred=ex.get("y_pred"),
                    proba=ex.get("proba"),
                    weight=weight,
                )
                processed_count += 1

                # Check if feature adaptation is necessary
                self.trades_processed_since_adapt_check += 1
                if (
                    ADAPTATION_ENABLED
                    and self.trades_processed_since_adapt_check
                    >= ADAPTATION_CHECK_INTERVAL
                ):
                    self._adapt_features()  # Call adaptation

            except Exception as e_buffer:
                logger.error(
                    f"{log_prefix} Failed to process buffered example: {e_buffer}. Example keys: {list(ex.keys())}",
                    exc_info=True,
                )

        logger.debug(
            f"{log_prefix} Finished processing {processed_count} buffered examples."
        )

    # NEW METHODS for feature analysis and adaptation
    def _calculate_feature_correlations(self) -> Dict[str, float]:
        """Calculates Pearson correlation between each feature and PnL."""
        correlations = {}
        history_size = len(self.feature_pnl_history)
        log_prefix = "[MP_CorrCalc]"

        if history_size < MIN_HISTORY_FOR_CORR:
            logger.debug(
                f"{log_prefix} Not enough history ({history_size} < {MIN_HISTORY_FOR_CORR}) for correlation calculation."
            )
            return correlations

        try:
            # Use deque to create DataFrame
            features_list = [item[0] for item in self.feature_pnl_history]
            pnl_list = [item[1] for item in self.feature_pnl_history]
            df = pd.DataFrame(features_list)
            df["pnl"] = pnl_list
            logger.debug(
                f"{log_prefix} Created DataFrame with shape {df.shape} for correlation."
            )

            # Calculate correlation for each column (feature) with 'pnl'
            for feature_name in df.columns:
                if feature_name == "pnl":
                    continue
                # Check that the column is not constant and contains numbers
                if df[feature_name].nunique() > 1 and pd.api.types.is_numeric_dtype(
                    df[feature_name]
                ):
                    try:
                        # Remove NaN before calculating correlation
                        corr_series = df[[feature_name, "pnl"]].dropna()
                        if (
                            len(corr_series) < MIN_HISTORY_FOR_CORR / 2
                        ):  # Require at least half of the data
                            logger.warning(
                                f"{log_prefix} Insufficient non-NaN data for '{feature_name}' correlation ({len(corr_series)} rows)."
                            )
                            correlations[feature_name] = 0.0
                            continue

                        # Check standard deviation before calculation
                        if (
                            corr_series[feature_name].std() < 1e-9
                            or corr_series["pnl"].std() < 1e-9
                        ):
                            logger.debug(
                                f"{log_prefix} Skipping correlation for '{feature_name}': Zero standard deviation."
                            )
                            correlations[feature_name] = 0.0
                            continue

                        corr = corr_series[feature_name].corr(
                            corr_series["pnl"], method="pearson"
                        )
                        correlations[feature_name] = corr if pd.notna(corr) else 0.0
                    except Exception as e_corr_calc:
                        logger.warning(
                            f"{log_prefix} Could not calculate correlation for feature '{feature_name}': {e_corr_calc}"
                        )
                        correlations[feature_name] = 0.0
                else:
                    # If the feature is constant or non-numeric, correlation is 0
                    logger.debug(
                        f"{log_prefix} Skipping correlation for '{feature_name}': Constant or non-numeric."
                    )
                    correlations[feature_name] = 0.0
            logger.info(
                f"{log_prefix} Calculated correlations for {len(correlations)} features based on {history_size} trades."
            )
            # logger.debug(f"Correlations: { {k: f'{v:.3f}' for k, v in sorted(correlations.items(), key=lambda item: abs(item[1]), reverse=True)} }") # Log top correlations

        except Exception as e:
            logger.error(
                f"{log_prefix} Error calculating feature correlations: {e}",
                exc_info=True,
            )
        return correlations

    def _adapt_features(self):
        """Removes the least useful features and adds new ones based on correlation with PnL."""
        log_prefix = "[MP_AdaptFeatures]"
        logger.info(
            f"{log_prefix} Starting feature adaptation check (History size: {len(self.feature_pnl_history)})..."
        )
        self.trades_processed_since_adapt_check = 0  # Reset the counter

        correlations = self._calculate_feature_correlations()
        if not correlations:
            logger.warning(
                f"{log_prefix} Cannot perform adaptation: Feature correlations unavailable or insufficient history."
            )
            return

        current_active_features = self.active_features.copy()

        # 1. Define features to remove
        features_to_remove = set()
        # Sort ACTIVE features by ABSOLUTE correlation (from smallest to largest)
        active_correlations = {
            name: abs(corr)
            for name, corr in correlations.items()
            if name in current_active_features
        }
        sorted_active_features = sorted(
            active_correlations.items(), key=lambda item: item[1]
        )

        # Remove N worst (with the lowest absolute correlation)
        num_to_potentially_remove = min(
            NUM_FEATURES_TO_REMOVE, len(sorted_active_features)
        )
        for i in range(num_to_potentially_remove):
            feature_name, abs_corr = sorted_active_features[i]
            # Additionally check the self.min_correlation_threshold threshold (based on the original, not absolute correlation)
            original_corr = correlations.get(feature_name, 0.0)

            if original_corr < self.min_correlation_threshold:
                features_to_remove.add(feature_name)
                logger.info(
                    f"{log_prefix} Marking feature '{feature_name}' for removal (Low Abs Corr: {abs_corr:.4f} AND Orig Corr: {original_corr:.4f} < {self.min_correlation_threshold})"
                )
            else:
                logger.debug(
                    f"{log_prefix} Feature '{feature_name}' has low abs corr ({abs_corr:.4f}), but orig corr ({original_corr:.4f}) >= threshold ({self.min_correlation_threshold}). Not removing."
                )

        # Ensure that we don't remove too many features (leave at least 5, for example)
        min_features_to_keep = 5
        if len(current_active_features - features_to_remove) < min_features_to_keep:
            num_can_remove = len(current_active_features) - min_features_to_keep
            if num_can_remove <= 0:
                features_to_remove.clear()  # Do not delete anything
            else:
                # Shorten the list of items to be removed, leaving the worst ones
                features_to_remove = set(
                    dict(sorted_active_features[:num_can_remove]).keys()
                )
            logger.warning(
                f"{log_prefix} Reduced features to remove to {len(features_to_remove)} to keep at least {min_features_to_keep} active features."
            )

        if features_to_remove:
            current_active_features -= features_to_remove
        else:
            logger.info(f"{log_prefix} No features marked for removal.")

        # 2. Define features to add
        features_to_add = set()
        # Candidates = All possible - Current active (which already REFLECT REMOVAL at this step)
        potential_candidates_pool = set(ALL_POSSIBLE_FEATURES) - current_active_features

        # From these candidates, exclude those that were JUST removed at this same adaptation step,
        # so as not to add them back immediately.
        eligible_for_immediate_addition = list(
            potential_candidates_pool - features_to_remove
        )

        if eligible_for_immediate_addition:
            num_to_add_planned = min(
                NUM_FEATURES_TO_ADD, len(eligible_for_immediate_addition)
            )
            if num_to_add_planned > 0:
                try:
                    features_to_add = set(
                        random.sample(
                            eligible_for_immediate_addition, num_to_add_planned
                        )
                    )
                    logger.info(
                        f"{log_prefix} Marking {len(features_to_add)} new features for addition: {features_to_add} (from {len(eligible_for_immediate_addition)} eligible)"
                    )
                except ValueError:
                    # This can happen if eligible_for_immediate_addition is empty and num_to_add_planned was > 0 (e.g. 1)
                    # or if num_to_add_planned is larger than the list (should be caught by min).
                    # Safely sample what's possible.
                    actual_num_to_sample = min(
                        num_to_add_planned, len(eligible_for_immediate_addition)
                    )  # Recalculate to be safe
                    if actual_num_to_sample > 0:
                        features_to_add = set(
                            random.sample(
                                eligible_for_immediate_addition, actual_num_to_sample
                            )
                        )
                        logger.warning(
                            f"{log_prefix} Sampled {len(features_to_add)} features after adjusting for ValueError (planned: {num_to_add_planned})."
                        )
                    else:
                        logger.info(
                            f"{log_prefix} No features to add after ValueError adjustment, eligible list might be empty."
                        )
                except Exception as e_sample:
                    logger.error(
                        f"{log_prefix} Error sampling new features: {e_sample}"
                    )
        else:
            logger.info(
                f"{log_prefix} No potential new features available to add (after excluding recently removed)."
            )

        # 3. Update the set of active features if there were changes (removal OR addition)
        # current_active_features ALREADY reflects removals. Now applying additions.
        if features_to_add:  # If there is something to add
            current_active_features.update(features_to_add)

        # Check if the set of active features has changed AFTER REMOVALS AND ADDITIONS
        # compared to the original self.active_features AT THE BEGINNING OF THIS _adapt_features METHOD
        if (
            self.active_features != current_active_features
        ):  # self.active_features here is the state BEFORE adaptation in this call
            logger.warning(
                f"{log_prefix} Feature set adapted! Removed: {features_to_remove}, Added: {features_to_add}. New active count: {len(current_active_features)}"
            )
            self.active_features = current_active_features
            # Clear history so that correlations are calculated based on the new set
            logger.info(
                f"{log_prefix} Clearing feature/PnL history due to feature set adaptation."
            )
            self.feature_pnl_history.clear()
        else:
            logger.info(f"{log_prefix} No changes made during feature adaptation.")

    def get_metrics(self) -> Dict[str, Union[float, int, None]]:
        res: Dict[str, Union[float, int, None]] = {}
        for name, metric in self.metric_trackers.items():
            try:
                metric_value = metric.get()
                if isinstance(metric_value, float) and (
                    math.isnan(metric_value) or math.isinf(metric_value)
                ):
                    res[name] = None
                else:
                    res[name] = metric_value
            except Exception:
                res[name] = None
        res["steps_processed"] = self.steps_processed
        res["active_features_count"] = (
            len(self.active_features)
            if self.active_features
            else len(ALL_POSSIBLE_FEATURES)
        )
        return res

    def save_model(self, path: Optional[Path] = None) -> None:
        save_path = path or self.model_path
        if not save_path:
            logger.warning("No path specified to save model.")
            return
        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            # Save active_features
            payload = {
                "version": __version__,
                "pipeline": self.pipeline,
                "metrics": self.metric_trackers,
                "steps": self.steps_processed,
                "active_features": self.active_features,  # Save the set
                "min_correlation_threshold": self.min_correlation_threshold,  # Save the threshold
            }
            joblib.dump(payload, save_path)
            logger.info(
                f"Model pipeline state saved to {save_path} (Steps: {self.steps_processed}, Active Features: {len(self.active_features)})"
            )
        except Exception as e_save:
            logger.error(f"Error saving model to {save_path}: {e_save}", exc_info=True)

    def load_model(self, path: Optional[Path] = None) -> bool:
        load_path = path or self.model_path
        if not load_path or not load_path.exists():
            logger.warning(
                f"Model file not found: {load_path}. Initializing with default pipeline and activating all features."
            )
            self.pipeline = DEFAULT_PIPELINE.clone()
            self.metric_trackers = {k: v.clone() for k, v in DEFAULT_METRICS.items()}
            self.steps_processed = 0
            # Initialize active_features with all possible ones
            self.active_features = set(ALL_POSSIBLE_FEATURES)
            return False
        try:
            data = joblib.load(load_path)
            if not isinstance(data, dict):
                logger.error(f"Invalid model file format in {load_path}.")
                return False

            loaded_version = data.get("version")
            if loaded_version != __version__:
                logger.warning(
                    f"Loading model with different version (File: {loaded_version}, Current: {__version__})."
                )

            self.pipeline = data["pipeline"]
            self.metric_trackers = data["metrics"]
            self.steps_processed = data.get("steps", 0)
            # Load active_features
            loaded_active_features = data.get("active_features")
            self.min_correlation_threshold = data.get(
                "min_correlation_threshold", MIN_CORRELATION_THRESHOLD
            )  # Load the threshold

            if isinstance(loaded_active_features, set):
                # Check that the loaded features exist in the current configuration
                unknown_features = loaded_active_features - set(ALL_POSSIBLE_FEATURES)
                if unknown_features:
                    logger.warning(
                        f"Loaded model contains unknown features: {unknown_features}. They will be ignored."
                    )
                # Use only known features
                self.active_features = loaded_active_features.intersection(
                    set(ALL_POSSIBLE_FEATURES)
                )
                if (
                    not self.active_features
                ):  # If nothing remains after the intersection
                    logger.error(
                        "No known features found in the loaded 'active_features' set! Activating all possible features."
                    )
                    self.active_features = set(ALL_POSSIBLE_FEATURES)
            else:
                logger.warning(
                    f"'active_features' not found or invalid in {load_path}. Activating all possible features."
                )
                self.active_features = set(ALL_POSSIBLE_FEATURES)

            logger.info(
                f"Model pipeline state loaded from {load_path}. Steps: {self.steps_processed}, Active Features: {len(self.active_features)}"
            )
            # Reset history and adaptation counters on load
            self.feature_pnl_history.clear()
            self.trades_processed_since_adapt_check = 0
            return True
        except KeyError as e_key:
            logger.error(
                f"Error loading model from {load_path}: Missing key '{e_key}'."
            )
            return False
        except Exception as e_load:
            logger.error(
                f"Error loading model from {load_path}: {e_load}", exc_info=True
            )
            return False

    def reset_pipeline(self):
        """Resets the pipeline to the default state and activates all features."""
        logger.warning(
            "Resetting model pipeline to default state and activating all features."
        )
        self.pipeline = DEFAULT_PIPELINE.clone()
        self.metric_trackers = {k: v.clone() for k, v in DEFAULT_METRICS.items()}
        self.steps_processed = 0
        self.active_features = set(ALL_POSSIBLE_FEATURES)
        self.training_buffer.clear()
        self.feature_pnl_history.clear()
        self.trades_processed_since_adapt_check = 0
        logger.info("Model pipeline reset complete.")
