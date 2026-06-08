# bot_module/train_offline_model.py

import logging
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import joblib
import json
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import argparse
import time
import sys

# Attempting to import River and bot_module components
try:
    import river

    print(
        f"Successfully imported river in train_offline_model.py, version: {river.__version__}"
    )
except ImportError as e_river_check:
    logging.critical(
        f"CRITICAL CHECK: Failed to import river at the very beginning: {e_river_check}"
    )
    sys.exit(100)

try:
    from river import (
        compose,
        linear_model,
        metrics,
        optim,
        preprocessing,
        tree,
        drift,
    )
    from river.forest import ARFClassifier
    from river import naive_bayes, neighbors
    # from river import svm # Postponing for now
    # Calibration is not available in River 0.22.0 in river.proba
    # from river.proba import LogisticCalibration

    RIVER_AVAILABLE = True
except ImportError as e_river_components:
    logging.critical(
        f"CRITICAL: Failed to import a specific River component. Error: {e_river_components}"
    )
    sys.exit(2)

try:
    from bot_module import config
    from bot_module.logger_setup import setup_bot_logging
    from bot_module.model_pipeline import __version__ as PIPELINE_VERSION

    DATA_FILE_PATH_DEFAULT = Path(
        getattr(
            config,
            "BACKTEST_ML_CONFIRMATION_DATA_PATH",
            "logs/ml_confirmation_training_data_new_format.csv",
        )
    )
    OFFLINE_MODEL_SAVE_PATH_DEFAULT = Path(
        getattr(
            config, "ML_OFFLINE_TRAINED_MODEL_PATH", "data/offline_trained_model.joblib"
        )
    )
    TRAINING_REPORT_FILE_DEFAULT = Path(
        getattr(config, "ML_TRAINING_REPORT_FILE", "logs/ml_training_report.json")
    )
except ImportError as e_bot_module:
    logging.critical(
        f"Failed to import bot_module components: {e_bot_module}. Ensure the script is run within the correct environment."
    )
    sys.exit(3)
# End of imports

TARGET_COLUMN = "y_true"
RAW_FEATURES_JSON_COLUMN = "raw_features_json"
# DATA_FILE_PATH will be defined from args in __main__

# setup_bot_logging() # Called once at script startup if __name__ == "__main__"
logger = logging.getLogger("bot_module.train_offline")

OFFLINE_TRAINING_METRICS: Dict[str, metrics.base.Metric] = {
    "accuracy": metrics.Accuracy(),
    "f1_binary": metrics.F1(),
    "log_loss": metrics.LogLoss(),
    "roc_auc": metrics.ROCAUC(),
    "confusion_matrix": metrics.ConfusionMatrix(),
}


def load_training_data(
    file_path: Path,
    target_col: str,
    raw_json_col: str,
    strategy_column_name: str = "strategy",
    strategy_to_train: Optional[str] = None,
    create_interactions: bool = False,
    interaction_set_to_use: Optional[str] = None,
) -> Optional[Tuple[pd.DataFrame, pd.Series, List[str]]]:
    log_prefix = "[LoadData]"
    if not file_path.exists():
        logger.error(f"{log_prefix} Training data file not found: {file_path}")
        return None
    try:
        logger.info(f"{log_prefix} Loading training data from: {file_path}")
        df = pd.read_csv(file_path, header=0, low_memory=False)
        logger.info(f"{log_prefix} Initial rows loaded: {len(df)}")

        if df.empty:
            logger.error(f"{log_prefix} Training data file is empty: {file_path}")
            return None
        if target_col not in df.columns:
            logger.error(
                f"{log_prefix} Target column '{target_col}' not found in CSV. Cannot train."
            )
            return None

        # Filtering by strategy
        if strategy_to_train:
            if strategy_column_name not in df.columns:
                logger.error(
                    f"{log_prefix} Strategy column '{strategy_column_name}' not found in data. Cannot filter by strategy '{strategy_to_train}'."
                )
                return None

            unique_strategies = df[strategy_column_name].unique()
            logger.info(
                f"{log_prefix} Available strategies in data: {unique_strategies}"
            )
            if strategy_to_train not in unique_strategies:
                logger.error(
                    f"{log_prefix} Specified strategy_to_train '{strategy_to_train}' not found in available strategies: {unique_strategies}. No data will be loaded."
                )
                return None

            original_len = len(df)
            df = df[df[strategy_column_name] == strategy_to_train].copy()
            logger.info(
                f"{log_prefix} Applied strategy filter: '{strategy_to_train}'. Rows reduced from {original_len} to {len(df)}."
            )
            if df.empty:
                logger.error(
                    f"{log_prefix} No data left after applying strategy filter '{strategy_to_train}'."
                )
                return None
        else:
            logger.info(
                f"{log_prefix} No specific strategy filter applied. Using all data."
            )

        # Feature extraction
        direct_feature_cols = [
            col
            for col in df.columns
            if col.startswith("feature_") or col.startswith("foundation_")
        ]
        X_direct = df[direct_feature_cols].copy()
        X_json_features = pd.DataFrame()

        if raw_json_col in df.columns and not df[raw_json_col].isnull().all():

            def safe_json_loads(json_str):
                if (
                    pd.isna(json_str)
                    or not isinstance(json_str, str)
                    or not json_str.strip()
                ):
                    return {}
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError as e_json:
                    logger.warning(
                        f"{log_prefix} Failed to parse JSON: '{str(json_str)[:100]}...' Error: {e_json}"
                    )
                    return {}

            parsed_json = df[raw_json_col].apply(safe_json_loads)
            if not parsed_json.empty:
                temp_json_df = pd.json_normalize(parsed_json)
                if not temp_json_df.empty:
                    X_json_features = temp_json_df

        # Reset indices BEFORE concatenation to ensure alignment
        X_direct = X_direct.reset_index(drop=True)
        if not X_json_features.empty:
            X_json_features = X_json_features.reset_index(drop=True)
            X = pd.concat([X_direct, X_json_features], axis=1)
        else:
            X = X_direct

        X = X.loc[:, ~X.columns.duplicated(keep="first")]
        logger.info(
            f"{log_prefix} Columns in X after initial feature extraction and duplicate removal: {list(X.columns)}"
        )

        created_interaction_feature_names = []
        if create_interactions and interaction_set_to_use:
            logger.info(
                f"{log_prefix} Attempting to create interaction features for set: {interaction_set_to_use}..."
            )
            interaction_definitions = {}
            if interaction_set_to_use == "vzaim1":
                interaction_definitions = {
                    "dist_min_x_vol_spike": (
                        "distance_to_local_min_20",
                        "volatility_spike_20",
                    ),
                    "dist_min_x_trade_rate": (
                        "distance_to_local_min_20",
                        "trade_rate_30s",
                    ),
                }
            elif interaction_set_to_use == "vzaim2":
                interaction_definitions = {
                    "dist_max_x_vol_spike": (
                        "distance_to_local_max_20",
                        "volatility_spike_20",
                    ),
                    "dist_max_x_trade_rate": (
                        "distance_to_local_max_20",
                        "trade_rate_30s",
                    ),
                }
            elif interaction_set_to_use == "vzaim3":
                interaction_definitions = {
                    "trade_rate_x_vol_spike": ("trade_rate_30s", "volatility_spike_20"),
                    "dist_min_x_vol_spike": (
                        "distance_to_local_min_20",
                        "volatility_spike_20",
                    ),
                }
            else:
                logger.warning(
                    f"{log_prefix} Unknown interaction_set_to_use: {interaction_set_to_use} for interactions. No specific interactions created by set name."
                )

            if interaction_definitions:
                all_base_features_for_interactions_exist = True
                required_base_features = set()
                for _, (f1, f2) in interaction_definitions.items():
                    required_base_features.add(f1)
                    required_base_features.add(f2)

                for base_f in list(required_base_features):
                    if base_f not in X.columns:
                        logger.error(
                            f"{log_prefix} CRITICAL: Base feature '{base_f}' for interactions is missing in X.columns. Cannot create specified interactions."
                        )
                        all_base_features_for_interactions_exist = False
                        break

                if all_base_features_for_interactions_exist:
                    for new_feat_name, (f1, f2) in interaction_definitions.items():
                        X[new_feat_name] = X[f1] * X[f2]
                        created_interaction_feature_names.append(new_feat_name)
                        logger.debug(
                            f"{log_prefix} Created interaction: {new_feat_name} = {f1} * {f2}"
                        )
                    logger.info(
                        f"{log_prefix} Successfully created interaction features: {created_interaction_feature_names}"
                    )
                else:
                    logger.error(
                        f"{log_prefix} Skipping creation of interaction features due to missing base features."
                    )
        elif create_interactions and not interaction_set_to_use:
            logger.warning(
                f"{log_prefix} 'create_interactions' is True, but 'interaction_set_to_use' is not specified for interactions. No specific interactions created by set name."
            )

        features_to_select_for_model = [
            "atr_14_rel",
            "distance_to_local_min_20",
            "volatility_spike_20",
            "distance_to_local_max_20",
            "trade_rate_30s",
        ]
        if create_interactions and created_interaction_feature_names:
            for feat_name in created_interaction_feature_names:
                if feat_name not in features_to_select_for_model:
                    features_to_select_for_model.append(feat_name)
            logger.info(
                f"{log_prefix} Features for model will include original Top-5 and created interactions."
            )

        logger.info(
            f"{log_prefix} Features declared for use in model: {features_to_select_for_model}"
        )

        final_features_in_X_present_in_df = [
            f for f in features_to_select_for_model if f in X.columns
        ]

        if not final_features_in_X_present_in_df:
            logger.error(
                f"{log_prefix} CRITICAL: No features left after selection based on '{features_to_select_for_model}'. Check feature names."
            )
            return None
        elif len(final_features_in_X_present_in_df) < len(features_to_select_for_model):
            missing_declared_features = set(features_to_select_for_model) - set(
                final_features_in_X_present_in_df
            )
            logger.warning(
                f"{log_prefix} Not all declared features for model were found in X. Missing: {list(missing_declared_features)}. Using: {final_features_in_X_present_in_df}"
            )
            X_selected_cols = X[final_features_in_X_present_in_df].copy()
        else:
            logger.info(
                f"{log_prefix} Final selection of {len(final_features_in_X_present_in_df)} features for training: {final_features_in_X_present_in_df}"
            )
            X_selected_cols = X[final_features_in_X_present_in_df].copy()

        all_feature_names_final = list(X_selected_cols.columns)
        if not all_feature_names_final:
            logger.error(
                f"{log_prefix} No feature columns found after processing. Cannot train."
            )
            return None

        logger.info(
            f"{log_prefix} Total {len(all_feature_names_final)} features identified for training (final count)."
        )

        y_series = df[target_col].copy().fillna(0).astype(int)  # y from the filtered df

        X_processed = (
            X_selected_cols.apply(pd.to_numeric, errors="coerce")
            .fillna(0.0)
            .replace([np.inf, -np.inf], [1e18, -1e18])
        )

        # Resetting indices for X and y for consistency BEFORE RETURNING
        X_final = X_processed.reset_index(drop=True)
        y_final = y_series.reset_index(drop=True)

        logger.info(
            f"{log_prefix} Target distribution for strategy '{strategy_to_train if strategy_to_train else 'all'}': {y_final.value_counts(normalize=True).to_dict() if not y_final.empty else 'empty'}"
        )
        logger.info(
            f"{log_prefix} Data loaded. Features: {X_final.shape}, Target: {y_final.shape} for strategy: '{strategy_to_train if strategy_to_train else 'all'}'"
        )
        return X_final, y_final, all_feature_names_final
    except Exception as e:
        logger.error(f"{log_prefix} Error loading data: {e}", exc_info=True)
        return None


def train_model(
    pipeline: compose.Pipeline,
    metrics_dict: Dict[str, metrics.base.Metric],
    X_train_df: pd.DataFrame,
    y_train_series: pd.Series,
    sample_weight_multiplier_class1: float = 1.0,
) -> Tuple[compose.Pipeline, Dict[str, metrics.base.Metric], int]:
    log_prefix = "[TrainModel]"
    # Checking for empty data before starting
    if X_train_df.empty or y_train_series.empty:
        logger.error(f"{log_prefix} Training data (X or y) is empty. Cannot train.")
        # Returning the original pipeline and metrics, 0 steps
        return pipeline, metrics_dict, 0

    model_in_pipeline = pipeline.steps.get("model", pipeline)
    logger.info(
        f"{log_prefix} Starting training with {len(X_train_df)} examples for model: {type(model_in_pipeline).__name__}"
    )
    steps_processed = 0
    log_interval = (
        max(1, len(X_train_df) // 10) if len(X_train_df) > 0 else 1
    )  # Do not divide by 0
    detailed_log_interval = (
        max(1, len(X_train_df) // 5)
        if len(X_train_df) > 1000
        else max(1, len(X_train_df) // 10)
    )  # More common for small DS

    start_time = time.time()
    predicted_class_1_count = 0

    y_value_counts = y_train_series.value_counts()
    base_weight_for_class_1 = 1.0
    if 0 in y_value_counts and 1 in y_value_counts and y_value_counts.get(1, 0) > 0:
        base_weight_for_class_1 = float(y_value_counts.get(0, 1)) / y_value_counts.get(
            1, 1
        )  # get(0,1) - default 1 if class 0 is missing
    final_weight_for_class_1 = base_weight_for_class_1 * sample_weight_multiplier_class1
    logger.info(
        f"{log_prefix} Base sample weight for class 1 (inverse freq): {base_weight_for_class_1:.2f}"
    )
    if sample_weight_multiplier_class1 != 1.0:
        logger.info(
            f"{log_prefix} Applied multiplier for class 1: {sample_weight_multiplier_class1:.2f}"
        )
    logger.info(
        f"{log_prefix} Final sample weights for learn_one: class 0: 1.0, class 1: {final_weight_for_class_1:.2f}"
    )
    class_weights_map = {0: 1.0, 1: final_weight_for_class_1}

    # Use iloc, as X_train_df and y_train_series now have reset and consistent indices
    for i in range(len(X_train_df)):
        try:
            features_dict = X_train_df.iloc[i].to_dict()
            target_value = y_train_series.iloc[i]  # Use iloc

            y_pred_proba, y_pred = None, None
            if any(pd.isna(v) for v in features_dict.values()):
                features_dict = {
                    k: (0.0 if pd.isna(v) else v) for k, v in features_dict.items()
                }

            if hasattr(pipeline, "predict_proba_one"):
                y_pred_proba = pipeline.predict_proba_one(features_dict)

            y_pred = pipeline.predict_one(features_dict)

            if y_pred == 1 or y_pred is True:
                predicted_class_1_count += 1
            current_sample_weight = class_weights_map.get(target_value, 1.0)

            if (i + 1) % detailed_log_interval == 0 or i == len(
                X_train_df
            ) - 1:  # Log for the last iteration as well
                logger.debug(
                    f"{log_prefix} Step {i + 1}: y_true={target_value}, y_pred={y_pred}, y_pred_proba={y_pred_proba}, learn_sw={current_sample_weight:.2f}"
                )

            for name, metric_obj in metrics_dict.items():
                try:
                    if isinstance(metric_obj, (metrics.LogLoss, metrics.ROCAUC)):
                        if y_pred_proba is not None:
                            metric_obj.update(y_true=target_value, y_pred=y_pred_proba)
                    elif isinstance(metric_obj, metrics.ConfusionMatrix):
                        if y_pred is not None:
                            metric_obj.update(y_true=target_value, y_pred=y_pred)
                    elif y_pred is not None:
                        metric_obj.update(y_true=target_value, y_pred=y_pred)
                except Exception as e_metric:
                    logger.warning(
                        f"{log_prefix} Metric '{name}' update error @ step {i + 1}: {e_metric}. True={target_value}, Pred={y_pred}, Proba={y_pred_proba}"
                    )

            pipeline.learn_one(
                features_dict, target_value, sample_weight=current_sample_weight
            )
            steps_processed += 1

            if (i + 1) % log_interval == 0 or i == len(X_train_df) - 1:
                elapsed = time.time() - start_time
                metrics_str_val_list = []
                for name, metric_val_obj in metrics_dict.items():
                    if name != "confusion_matrix":
                        metric_value = metric_val_obj.get()
                        if metric_value is not None:
                            metrics_str_val_list.append(f"{name}={metric_value:.4f}")
                        else:
                            metrics_str_val_list.append(f"{name}=N/A")
                metrics_str_val = ", ".join(metrics_str_val_list)
                logger.info(
                    f"{log_prefix} Step {i + 1}/{len(X_train_df)} ({elapsed:.1f}s) | Pred '1's: {predicted_class_1_count} | Metrics: {metrics_str_val}"
                )
        except Exception as e_learn:
            # In case of an error, we try to get the index from X_train_df if it is not a standard RangeIndex
            current_idx_for_log = (
                X_train_df.index[i]
                if not isinstance(X_train_df.index, pd.RangeIndex)
                else i
            )
            logger.error(
                f"{log_prefix} Error during training @ original_df_idx_approx={current_idx_for_log} (loop_step={i + 1}): {e_learn}. Features: {X_train_df.iloc[i].to_dict() if isinstance(X_train_df.iloc[i], pd.Series) else X_train_df.iloc[i]}",
                exc_info=True,
            )

    end_time = time.time()
    logger.info(
        f"{log_prefix} Training finished. Steps: {steps_processed}, Duration: {end_time - start_time:.2f}s. Pred '1's: {predicted_class_1_count}/{len(X_train_df) if len(X_train_df) > 0 else 'N/A'}."
    )

    model_component_for_weights = pipeline.steps.get("model", pipeline)
    if hasattr(model_component_for_weights, "weights") and isinstance(
        model_component_for_weights.weights, dict
    ):
        weights_ddict = model_component_for_weights.weights
        valid_feature_weights = {
            f: w for f, w in weights_ddict.items() if f in X_train_df.columns
        }  # Using current X_train_df columns

        intercept_val = None
        # Checking the standard key and the alternative one
        intercept_key_standard = getattr(
            model_component_for_weights, "intercept_key", "_intercept"
        )
        if intercept_key_standard in weights_ddict:
            intercept_val = weights_ddict[intercept_key_standard]

        logger.info(
            f"--- Feature Weights (from {type(model_component_for_weights).__name__}) ---"
        )
        if intercept_val is not None:
            logger.info(f"Intercept: {intercept_val:.4f}")

        if valid_feature_weights:
            # Sort by absolute weight value for more informativeness or simply by value
            feature_weights_series = pd.Series(valid_feature_weights).sort_values(
                ascending=False
            )
            num_weights_to_show = min(
                15, len(feature_weights_series)
            )  # Showing more weights if there are few of them
            logger.info(
                f"Top {num_weights_to_show} Positive Weights (or all if less than {num_weights_to_show}):\n{feature_weights_series.head(num_weights_to_show)}"
            )
            logger.info(
                f"Top {num_weights_to_show} Negative Weights (or all if less than {num_weights_to_show}):\n{feature_weights_series.tail(num_weights_to_show).sort_values(ascending=True)}"
            )
        else:
            logger.warning(
                f"{log_prefix} Could not extract comparable feature weights from model or no valid feature weights found for current feature set."
            )
            if weights_ddict:
                logger.debug(
                    f"All weights from model (may include old/intercept): {weights_ddict}"
                )

    elif isinstance(
        model_component_for_weights,
        (
            ARFClassifier,
            tree.HoeffdingTreeClassifier,
            naive_bayes.GaussianNB,
            neighbors.KNNClassifier,
            tree.HoeffdingAdaptiveTreeClassifier,
        ),
    ):
        logger.info(
            f"--- Feature importance for {type(model_component_for_weights).__name__} is not directly extracted as weights. ---"
        )
    return pipeline, metrics_dict, steps_processed


def save_trained_model(
    pipeline: compose.Pipeline,
    metrics_dict_obj: Dict[str, metrics.base.Metric],
    steps: int,
    active_features: List[str],
    model_path: Path,
    report_path: Path,
    training_data_path_for_report: Path,
):  # Argument added
    log_prefix = "[SaveModel]"
    metrics_to_save_for_joblib, metrics_to_save_for_report = {}, {}
    for name, metric_obj_item in metrics_dict_obj.items():
        if isinstance(metric_obj_item, metrics.ConfusionMatrix):
            cm_data_dict = metric_obj_item.data
            report_cm_intuitive = {
                "true_positives": int(
                    cm_data_dict.get((True, True), 0) + cm_data_dict.get((1, 1), 0)
                ),  # Consider True/1
                "false_negatives": int(
                    cm_data_dict.get((True, False), 0) + cm_data_dict.get((1, 0), 0)
                ),
                "false_positives": int(
                    cm_data_dict.get((False, True), 0) + cm_data_dict.get((0, 1), 0)
                ),
                "true_negatives": int(
                    cm_data_dict.get((False, False), 0) + cm_data_dict.get((0, 0), 0)
                ),
            }
            metrics_to_save_for_report[name] = metrics_to_save_for_joblib[name] = (
                report_cm_intuitive
            )
        else:
            metric_value = metric_obj_item.get()
            metrics_to_save_for_report[name] = metrics_to_save_for_joblib[name] = (
                metric_value if metric_value is not None else "N/A"
            )
    try:
        model_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": PIPELINE_VERSION,
            "pipeline": pipeline,
            "metrics": metrics_to_save_for_joblib,
            "steps": steps,
            "active_features": set(active_features),
        }
        joblib.dump(payload, model_path)
        logger.info(f"{log_prefix} Trained model saved to: {model_path}")
    except Exception as e_save:
        logger.error(f"{log_prefix} Error saving model: {e_save}", exc_info=True)
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_data = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "training_data_file": str(
                training_data_path_for_report
            ),  # Using the provided path
            "model_save_path": str(model_path),
            "pipeline_version": PIPELINE_VERSION,
            "total_steps": steps,
            "active_features_count": len(active_features),
            "active_features_list": sorted(list(active_features)),
            "final_metrics": metrics_to_save_for_report,
            "pipeline_structure": str(pipeline),
            "ml_confirmation_y_true_min_move_pct": getattr(
                config, "ML_CONFIRMATION_Y_TRUE_MIN_MOVE_FAVOR_PCT", None
            ),
            "ml_confirmation_y_true_max_drawdown_pct": getattr(
                config, "ML_CONFIRMATION_Y_TRUE_MAX_DRAWDOWN_PCT", None
            ),
        }

        def custom_serializer(obj):
            if isinstance(obj, Path):
                return str(obj)
            if isinstance(obj, np.integer):
                return int(obj)  # For np.int64, np.int32
            if isinstance(obj, np.floating):
                return float(obj)  # For np.float64, np.float32
            if isinstance(obj, np.ndarray):
                return obj.tolist()  # For numpy arrays
            if isinstance(obj, set):
                return list(obj)
            try:
                return str(obj)
            except Exception:
                return f"Unserializable_object_type_{type(obj).__name__}"

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, default=custom_serializer)
        logger.info(f"{log_prefix} Training report saved to: {report_path}")
    except Exception as e_report:
        logger.error(f"{log_prefix} Error saving report: {e_report}", exc_info=True)


def run_river_training_from_config(config: Dict[str, Any]):
    """
    Performs a full offline training cycle for a River model based on a configuration dictionary.
    This function encapsulates all the logic previously located in the if __name__ == "__main__" block.

    Args:
        config (Dict[str, Any]): A dictionary with parameters similar to those
                                 obtained from argparse. Includes file paths,
                                 model type, hyperparameters, etc.

    Returns:
        Tuple[Path, Path]: A tuple containing paths to the saved model and the report.
    """
    # Step 1: Configuring logging based on the configuration
    # It is assumed that setup_bot_logging() has already been called once at script/worker startup.
    logger = logging.getLogger("bot_module.train_offline")
    log_level_str = config.get("log_level", "INFO").upper()
    logging.getLogger().setLevel(log_level_str)
    logger.setLevel(log_level_str)
    for handler in logging.getLogger("bot_module").handlers:
        handler.setLevel(log_level_str)
    logger.info(f"Global and bot_module log level set to {log_level_str} from config.")

    # Step 2: Defining paths for data and for saving results
    data_file_path = Path(config.get("data_file"))

    strategy_filter = config.get("strategy")
    if strategy_filter:
        strategy_suffix = f"_{strategy_filter.replace(' ', '_').replace('/', '_')}"
        model_out_str = config.get("model_out")
        report_out_str = config.get("report_out")

        model_output_path = (
            Path(model_out_str).parent
            / f"{Path(model_out_str).stem}{strategy_suffix}{Path(model_out_str).suffix}"
        )
        report_output_path = (
            Path(report_out_str).parent
            / f"{Path(report_out_str).stem}{strategy_suffix}{Path(report_out_str).suffix}"
        )
    else:
        model_output_path = Path(config.get("model_out"))
        report_output_path = Path(config.get("report_out"))

    logger.info(
        f"Data Source: {data_file_path}, Model Output: {model_output_path}, Report Output: {report_output_path}"
    )
    if strategy_filter:
        logger.info(f"TRAINING FOR STRATEGY: {strategy_filter}")

    create_interactions_flag = config.get("create_interactions", False)
    interaction_set = config.get("interaction_set")
    if create_interactions_flag:
        logger.info(
            f"Interaction features creation ENABLED. Set to use: {interaction_set}"
        )
    else:
        logger.info("Interaction features creation DISABLED.")

    logger.info("--- Starting Offline ML Confirmation Model Training ---")

    # Step 3: Initializing the model based on the configuration
    model_instance = None
    model_type = config.get("model_type")

    if model_type == "logistic":
        lr_val = config.get("lr", 0.005)
        l2_val = config.get("l2", 0.001)
        model_instance = linear_model.LogisticRegression(
            optimizer=optim.Adam(lr=lr_val), l2=l2_val
        )
        logger.info(f"Using model: LogisticRegression with lr={lr_val}, l2={l2_val}")

    elif model_type == "hoeffding":
        grace_period_val = config.get("ht_grace_period", 200)
        delta_val = config.get("ht_delta", 1e-7)
        model_instance = tree.HoeffdingTreeClassifier(
            grace_period=grace_period_val, delta=delta_val, seed=42
        )
        logger.info(
            f"Using model: HoeffdingTreeClassifier with grace_period={grace_period_val}, delta={delta_val}"
        )

    elif model_type == "arf":
        drift_detector_instance = None
        warning_detector_instance = None
        if config.get("use_drift_detectors", False):
            drift_delta = config.get("adwin_drift_delta", 0.002)
            warning_delta = config.get("adwin_warning_delta", 0.01)
            drift_detector_instance = drift.ADWIN(delta=drift_delta)
            warning_detector_instance = drift.ADWIN(delta=warning_delta)
            logger.info(
                f"Using ADWIN drift detector (delta={drift_delta}) and warning detector (delta={warning_delta})"
            )
        else:
            logger.info("Drift detectors for ARF are NOT enabled.")

        model_instance = ARFClassifier(
            n_models=config.get("arf_n_models", 10),
            grace_period=config.get("arf_grace_period", 50),
            delta=config.get("ht_delta", 1e-7),
            max_depth=config.get("arf_max_depth", 10),
            drift_detector=drift_detector_instance,
            warning_detector=warning_detector_instance,
            seed=42,
        )
        logger.info(
            f"Using model: ARFClassifier with n_models={config.get('arf_n_models', 10)}, tree_grace_period={config.get('arf_grace_period', 50)}, tree_delta={config.get('ht_delta', 1e-7)}, tree_max_depth={config.get('arf_max_depth', 10)}"
        )

    elif model_type == "gaussian_nb":
        model_instance = naive_bayes.GaussianNB()
        logger.info("Using model: GaussianNB")

    elif model_type == "knn":
        n_neighbors_val = config.get("knn_n_neighbors", 5)
        model_instance = neighbors.KNNClassifier(n_neighbors=n_neighbors_val)
        logger.info(f"Using model: KNNClassifier with n_neighbors={n_neighbors_val}")

    elif model_type == "pa":
        c_val = config.get("pa_c", 1.0)
        mode_val = config.get("pa_mode", 1)
        model_instance = linear_model.PAClassifier(C=c_val, mode=mode_val)
        logger.info(
            f"Using model: PAClassifier with C={c_val}, mode={mode_val} (0:PA, 1:PA-I, 2:PA-II)"
        )

    elif model_type == "hat":
        drift_detector_instance_hat = None
        warning_detector_instance_hat = None
        if config.get("use_drift_detectors", False):
            drift_delta_hat = config.get("adwin_drift_delta", 0.002)
            warning_delta_hat = config.get("adwin_warning_delta", 0.01)
            drift_detector_instance_hat = drift.ADWIN(delta=drift_delta_hat)
            warning_detector_instance_hat = drift.ADWIN(delta=warning_delta_hat)
            logger.info(
                f"Using ADWIN for HAT: drift_delta={drift_delta_hat}, warning_delta={warning_delta_hat}"
            )
        else:
            logger.info("Drift detectors for HAT are NOT enabled.")

        model_instance = tree.HoeffdingAdaptiveTreeClassifier(
            grace_period=config.get("ht_grace_period", 200),
            delta=config.get("ht_delta", 1e-7),
            drift_detector=drift_detector_instance_hat,
            warning_detector=warning_detector_instance_hat,
            seed=42,
        )
        logger.info(
            f"Using model: HoeffdingAdaptiveTreeClassifier with grace_period={config.get('ht_grace_period', 200)}, delta={config.get('ht_delta', 1e-7)}"
        )

    else:
        logger.error(f"Unknown model type in config: {model_type}")
        raise ValueError(f"Unknown model type: {model_type}")

    if model_instance is None:
        logger.critical(
            f"Model instance was not created for type {model_type}. Exiting."
        )
        raise RuntimeError(f"Model instance was not created for type {model_type}")

    # Step 4: Creating the pipeline
    current_pipeline = compose.Pipeline(
        ("scaler", preprocessing.StandardScaler()), ("model", model_instance)
    )

    logger.info(
        f"Sample weight multiplier for class 1: {config.get('sw_multiplier_c1', 1.0)}"
    )

    # Step 5: Data loading
    data_load_result = load_training_data(
        data_file_path,
        TARGET_COLUMN,
        RAW_FEATURES_JSON_COLUMN,
        strategy_column_name="strategy",
        strategy_to_train=strategy_filter,
        create_interactions=create_interactions_flag,
        interaction_set_to_use=interaction_set,
    )

    if data_load_result is None:
        logger.critical("Failed to load training data. Exiting.")
        # Instead of sys.exit(1), we raise an exception
        raise FileNotFoundError("Failed to load training data.")

    X_train, y_train, actual_feature_names = data_load_result
    if X_train.empty or y_train.empty or not actual_feature_names:
        logger.critical("Training data empty or no features after processing. Exiting.")
        raise ValueError("Training data is empty or has no features after processing.")

    logger.info(
        f"Training with {len(actual_feature_names)} features: {', '.join(actual_feature_names[: min(3, len(actual_feature_names))])}{'...' if len(actual_feature_names) > 3 else ''}"
    )

    # Step 6: Model training
    pipeline_cloned = current_pipeline.clone()
    metrics_dict_cloned = {k: v.clone() for k, v in OFFLINE_TRAINING_METRICS.items()}

    trained_pipeline, final_metrics_dict_objects, total_steps = train_model(
        pipeline_cloned,
        metrics_dict_cloned,
        X_train,
        y_train,
        sample_weight_multiplier_class1=config.get("sw_multiplier_c1", 1.0),
    )

    # Step 7: Saving the model and report
    save_trained_model(
        trained_pipeline,
        final_metrics_dict_objects,
        total_steps,
        actual_feature_names,
        model_output_path,
        report_output_path,
        data_file_path,
    )

    # Step 8: Logging final metrics
    logger.info("--- Final Training Metrics ---")
    final_metrics_calculated = {}
    for name, metric_obj_item in final_metrics_dict_objects.items():
        if isinstance(metric_obj_item, metrics.ConfusionMatrix):
            logger.info(f"  {name}:\n{metric_obj_item}")
            cm_data = metric_obj_item.data
            tp = cm_data.get((True, True), 0) + cm_data.get((1, 1), 0)
            fp = cm_data.get((False, True), 0) + cm_data.get((0, 1), 0)
            fn = cm_data.get((True, False), 0) + cm_data.get((1, 0), 0)
            tn = cm_data.get((False, False), 0) + cm_data.get((0, 0), 0)

            precision_manual = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall_manual = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            logger.info(
                f"    Manually calculated from CM: TP={tp}, FP={fp}, FN={fn}, TN={tn}"
            )
            logger.info(
                f"    Manually calculated from CM: Precision={precision_manual:.4f}, Recall={recall_manual:.4f}"
            )
            final_metrics_calculated[f"{name}_precision_manual"] = precision_manual
            final_metrics_calculated[f"{name}_recall_manual"] = recall_manual
        else:
            metric_value = metric_obj_item.get()
            logger.info(
                f"  {name}: {metric_value:.4f}"
                if metric_value is not None
                else f"  {name}: N/A"
            )
            final_metrics_calculated[name] = (
                metric_value if metric_value is not None else "N/A"
            )

    logger.info(f"Total Steps Processed: {total_steps}")
    logger.info("--- Offline Training Finished ---")

    return model_output_path, report_output_path


if __name__ == "__main__":
    # Logging configuration should be one of the first things
    setup_bot_logging()  # If this function also configures the root logger, then great

    # Command line argument parsing block
    # This block remains here so that the script can be run directly.
    parser = argparse.ArgumentParser(
        description="Offline Trainer for ML Signal Confirmation Model"
    )
    parser.add_argument(
        "--data-file",
        type=str,
        default=str(DATA_FILE_PATH_DEFAULT),
        help="Path to training data CSV.",
    )
    parser.add_argument(
        "--model-out",
        type=str,
        default=str(OFFLINE_MODEL_SAVE_PATH_DEFAULT),
        help="Path to save trained model.",
    )
    parser.add_argument(
        "--report-out",
        type=str,
        default=str(TRAINING_REPORT_FILE_DEFAULT),
        help="Path to save training report.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level.",
    )
    parser.add_argument(
        "--sw-multiplier-c1",
        type=float,
        default=1.0,
        help="Multiplier for sample_weight of class 1.",
    )

    parser.add_argument(
        "--model-type",
        type=str,
        default="logistic",
        choices=["logistic", "hoeffding", "arf", "gaussian_nb", "knn", "pa", "hat"],
        help="Type of model to train.",
    )

    parser.add_argument(
        "--strategy",
        type=str,
        default=None,
        help="Specify a strategy to filter data for training (e.g., VolumeBreakout, FakeBreakout). If None, all data is used.",
    )
    parser.add_argument(
        "--create-interactions",
        action="store_true",
        default=False,
        help="Enable creation of interaction features.",
    )
    parser.add_argument(
        "--interaction-set",
        type=str,
        default=None,
        choices=[None, "vzaim1", "vzaim2", "vzaim3"],
        help="Which set of interaction features to use (e.g., vzaim1, vzaim2, vzaim3). Requires --create-interactions.",
    )

    parser.add_argument(
        "--use-drift-detectors",
        action="store_true",
        default=False,
        help="Enable ADWIN drift and warning detectors for ARF/HAT.",
    )
    parser.add_argument(
        "--adwin-drift-delta",
        type=float,
        default=0.002,
        help="Delta for ADWIN drift detector.",
    )
    parser.add_argument(
        "--adwin-warning-delta",
        type=float,
        default=0.01,
        help="Delta for ADWIN warning detector.",
    )

    # LogisticRegression
    parser.add_argument(
        "--lr",
        type=float,
        default=0.005,
        help="Learning rate for LogisticRegression and calibrator.",
    )
    parser.add_argument(
        "--l2",
        type=float,
        default=0.001,
        help="L2 regularization for LogisticRegression.",
    )
    # HoeffdingTree & HoeffdingAdaptiveTree
    parser.add_argument(
        "--ht-grace-period",
        type=int,
        default=200,
        help="Grace period for HoeffdingTree based models.",
    )
    parser.add_argument(
        "--ht-delta",
        type=float,
        default=1e-7,
        help="Delta for HoeffdingTree based models.",
    )
    # ARFClassifier
    parser.add_argument(
        "--arf-n-models", type=int, default=10, help="Number of trees in ARFClassifier."
    )
    parser.add_argument(
        "--arf-grace-period",
        type=int,
        default=50,
        help="Grace period for trees in ARF.",
    )
    parser.add_argument(
        "--arf-max-depth", type=int, default=10, help="Max depth for trees in ARF."
    )
    # KNNClassifier
    parser.add_argument(
        "--knn-n-neighbors",
        type=int,
        default=5,
        help="Number of neighbors for KNNClassifier.",
    )
    # PassiveAggressiveClassifier
    parser.add_argument(
        "--pa-c",
        type=float,
        default=1.0,
        help="Maximum step size (C) for PAClassifier.",
    )
    parser.add_argument(
        "--pa-mode",
        type=int,
        default=1,
        choices=[0, 1, 2],
        help="Mode for PAClassifier (0: 'PA', 1: 'PA1', 2: 'PA2').",
    )

    args = parser.parse_args()

    # Converting args to a dictionary and calling the main function
    try:
        # Converting the Namespace object from argparse into a regular dictionary
        config_from_cli = vars(args)

        # Calling the main logic, passing the configuration to it
        model_path, report_path = run_river_training_from_config(config_from_cli)

        # Outputting final information to the console for the user
        print("\n--- Command-Line Training Summary ---")
        print(f"Model successfully trained and saved to: {model_path}")
        print(f"Training report saved to: {report_path}")
        print("-------------------------------------")

    except (ValueError, FileNotFoundError, RuntimeError) as e:
        # Catching exceptions that our function now throws,
        # and terminating the script with an error.
        logging.critical(
            f"A critical error occurred during training: {e}", exc_info=True
        )
        sys.exit(1)
    except Exception as e:
        logging.critical(f"An unexpected error occurred: {e}", exc_info=True)
        sys.exit(2)
