# train_sklearn_batch.py

import logging
import pandas as pd
import numpy as np
import json
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import argparse
import time
import sys
from datetime import datetime

# Scikit-learn imports
from sklearn.model_selection import (
    train_test_split,
    StratifiedKFold,
    GridSearchCV,
    RandomizedSearchCV,
)
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    precision_score,
    recall_score,
    roc_auc_score,
    log_loss,
    confusion_matrix,
    make_scorer,
)
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier

# GBM library imports
import lightgbm as lgb
import xgboost as xgb

# Attempt to import bot_module components for configuration and logging
try:
    from bot_module import config
    from bot_module.logger_setup import setup_bot_logging

    DEFAULT_DATA_FILE_FROM_CONFIG = Path(
        getattr(
            config,
            "BACKTEST_ML_CONFIRMATION_DATA_PATH",
            "logs/ml_confirmation_training_data.csv",
        )
    )
except ImportError:
    print(
        "Warning: bot_module.config or bot_module.logger_setup not found. Using default paths and basic logging."
    )
    setup_bot_logging = None
    DEFAULT_DATA_FILE_FROM_CONFIG = Path("logs/ml_confirmation_training_data.csv")

TARGET_COLUMN = "y_true"
RAW_FEATURES_JSON_COLUMN = "raw_features_json"
# Columns that are definitely not features for the model
NON_FEATURE_COLUMNS_IN_CSV = [
    "timestamp_signal",
    "timestamp_close",
    "client_order_id",
    "symbol",
    "direction",
    "mode",
    "signal_trigger_price",
    "signal_entry_price",
    "signal_sl",
    "signal_tp",
    "actual_entry_price",
    "actual_exit_price",
    "avg_weighted_exit_price",
    "num_partial_tp_hits",
    "quantity",
    "pnl",
    "exit_reason",
    "commission",
    "pattern_detected",
    "trend_detected",
    TARGET_COLUMN,
    RAW_FEATURES_JSON_COLUMN,
    "strategy",
]

# Logger initialization
if setup_bot_logging is None:

    def setup_basic_logging():
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(sys.stdout)],
        )

    setup_basic_logging()

logger = logging.getLogger("train_sklearn_batch")


def load_training_data(
    file_path: Path,
    target_col: str,
    raw_json_col: str,
    strategy_column_name: str = "strategy",
    strategy_to_train: Optional[str] = None,
    create_interactions: bool = False,
    interaction_set_to_use: Optional[str] = None,
    use_all_numeric_features: bool = False,
) -> Optional[Tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series, List[str]]]:
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

        # Sort chronologically by timestamp_signal to prevent look-ahead bias
        if "timestamp_signal" in df.columns:
            df["timestamp_signal_dt"] = pd.to_datetime(df["timestamp_signal"], errors="coerce")
            df = df.sort_values(by="timestamp_signal_dt").drop(columns=["timestamp_signal_dt"]).reset_index(drop=True)
            logger.info(f"{log_prefix} Sorted training data chronologically by timestamp_signal.")

        if target_col not in df.columns:
            logger.error(
                f"{log_prefix} Target column '{target_col}' not found in CSV. Cannot train."
            )
            return None

        if strategy_to_train:
            if strategy_column_name not in df.columns:
                logger.error(
                    f"{log_prefix} Strategy column '{strategy_column_name}' not found. Cannot filter."
                )
                return None
            original_len = len(df)
            df = df[df[strategy_column_name] == strategy_to_train].copy()
            logger.info(
                f"{log_prefix} Applied strategy filter: '{strategy_to_train}'. Rows reduced from {original_len} to {len(df)}."
            )
            if df.empty:
                logger.error(
                    f"{log_prefix} No data left after strategy filter '{strategy_to_train}'."
                )
                return None

        X_json_features_df = pd.DataFrame()
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
                except json.JSONDecodeError:
                    return {}

            parsed_json = df[raw_json_col].apply(safe_json_loads)
            if not parsed_json.empty:
                temp_json_df = pd.json_normalize(parsed_json)
                if not temp_json_df.empty:
                    X_json_features_df = temp_json_df

        potential_direct_features = [
            col
            for col in df.columns
            if col not in NON_FEATURE_COLUMNS_IN_CSV
            and col != target_col
            and col != raw_json_col
        ]
        X_direct_features_df = df[potential_direct_features].copy()

        X_combined = X_direct_features_df.reset_index(drop=True)
        if not X_json_features_df.empty:
            X_json_features_df = X_json_features_df.reset_index(drop=True)
            X_combined = pd.concat([X_combined, X_json_features_df], axis=1)

        X_combined = X_combined.loc[:, ~X_combined.columns.duplicated(keep="first")]
        logger.info(
            f"{log_prefix} Combined features from CSV and JSON (before type conversion/selection): {list(X_combined.columns)}"
        )

        for col in X_combined.columns:
            X_combined[col] = pd.to_numeric(X_combined[col], errors="coerce")
        X_combined = X_combined.fillna(0.0).replace([np.inf, -np.inf], [1e18, -1e18])

        all_feature_names_selected = []

        if use_all_numeric_features:
            logger.info(f"{log_prefix} Using all identified numeric features.")
            X_selected = X_combined.select_dtypes(include=np.number).copy()
            all_feature_names_selected = list(X_selected.columns)
            logger.info(
                f"{log_prefix} Identified {len(all_feature_names_selected)} numeric features: {all_feature_names_selected[:10]}..."
            )
        else:
            features_to_select_for_model_base = [
                "atr_14_rel",
                "distance_to_local_min_20",
                "volatility_spike_20",
                "distance_to_local_max_20",
                "trade_rate_30s",
            ]
            missing_base_for_top5 = [
                f
                for f in features_to_select_for_model_base
                if f not in X_combined.columns
            ]
            if missing_base_for_top5:
                logger.error(
                    f"{log_prefix} CRITICAL: Base features for Top-5 are missing from data: {missing_base_for_top5}. Cannot proceed with Top-5 selection."
                )
                return None

            X_selected = X_combined[features_to_select_for_model_base].copy()
            all_feature_names_selected = list(features_to_select_for_model_base)

        created_interaction_feature_names = []
        if create_interactions and interaction_set_to_use:
            logger.info(
                f"{log_prefix} Attempting to create interaction features for set: {interaction_set_to_use} on current feature base..."
            )
            interaction_definitions = {}
            if interaction_set_to_use == "vzaim3":
                interaction_definitions = {
                    "trade_rate_x_vol_spike": ("trade_rate_30s", "volatility_spike_20"),
                    "dist_min_x_vol_spike": (
                        "distance_to_local_min_20",
                        "volatility_spike_20",
                    ),
                }
            else:
                logger.warning(
                    f"{log_prefix} Interaction set '{interaction_set_to_use}' not recognized or no interactions defined for it."
                )

            if interaction_definitions:
                source_for_interactions = X_combined
                temp_interaction_df = pd.DataFrame(index=source_for_interactions.index)

                for new_feat_name, (f1, f2) in interaction_definitions.items():
                    if (
                        f1 not in source_for_interactions.columns
                        or f2 not in source_for_interactions.columns
                    ):
                        logger.error(
                            f"{log_prefix} Base feature for interaction missing from combined data: {f1} or {f2}. Cannot create {new_feat_name}."
                        )
                        continue
                    temp_interaction_df[new_feat_name] = (
                        source_for_interactions[f1] * source_for_interactions[f2]
                    )
                    created_interaction_feature_names.append(new_feat_name)

                if created_interaction_feature_names:
                    logger.info(
                        f"{log_prefix} Successfully created interaction features: {created_interaction_feature_names}"
                    )
                    for feat_name in created_interaction_feature_names:
                        if feat_name in temp_interaction_df.columns:
                            X_selected[feat_name] = temp_interaction_df[feat_name]
                            if feat_name not in all_feature_names_selected:
                                all_feature_names_selected.append(feat_name)
                else:
                    logger.warning(
                        f"{log_prefix} No interaction features were created."
                    )

        if not use_all_numeric_features:
            final_check_features = [
                f for f in all_feature_names_selected if f in X_combined.columns
            ]
            if len(final_check_features) != len(all_feature_names_selected):
                logger.warning(
                    f"Some selected features for Top-5 (+interactions) were not found in combined data. Using {final_check_features}"
                )
            all_feature_names_selected = final_check_features
            X_final_features = X_combined[all_feature_names_selected].copy()
        else:
            X_final_features = X_selected.copy()

        if X_final_features.empty or not all_feature_names_selected:
            logger.error(
                f"{log_prefix} CRITICAL: No features left after selection/processing. Cannot train."
            )
            return None

        logger.info(
            f"{log_prefix} Final {len(all_feature_names_selected)} features for training: {all_feature_names_selected[:10]}{'...' if len(all_feature_names_selected) > 10 else ''}"
        )

        y_series = df[target_col].copy().fillna(0).astype(int)

        X_output = X_final_features.reset_index(drop=True)
        y_output = y_series.reset_index(drop=True)

        t0_series = df["timestamp_signal"].copy() if "timestamp_signal" in df.columns else pd.Series([pd.Timestamp.now()] * len(df))
        t1_series = df["timestamp_close"].copy() if "timestamp_close" in df.columns else t0_series.copy()

        t0_series = t0_series.fillna(pd.Timestamp.now())
        t1_series = t1_series.fillna(t0_series)

        logger.info(
            f"{log_prefix} Target distribution: {y_output.value_counts(normalize=True).to_dict() if not y_output.empty else 'empty'}"
        )
        logger.info(
            f"{log_prefix} Data loaded. Features: {X_output.shape}, Target: {y_output.shape}"
        )
        return X_output, y_output, t0_series.reset_index(drop=True), t1_series.reset_index(drop=True), all_feature_names_selected
    except Exception as e:
        logger.error(f"{log_prefix} Error loading data: {e}", exc_info=True)
        return None


def calculate_scale_pos_weight(y_train: pd.Series) -> float:
    counts = y_train.value_counts()
    scale = (
        counts.get(0, 1) / counts.get(1, 1)
        if 1 in counts and counts.get(1, 1) > 0
        else 1.0
    )
    logger.info(
        f"Calculated scale_pos_weight: {scale:.4f} (neg/pos based on training data)"
    )
    return scale


def train_evaluate_sklearn_model(
    model_name: str,
    model_instance,
    param_grid: Dict,
    X_train_scaled: pd.DataFrame,
    y_train: pd.Series,
    X_test_scaled: pd.DataFrame,
    y_test: pd.Series,
    feature_names: List[str],
    cv_folds: int = 5,
    random_state: int = 42,
    scale_pos_weight_val: Optional[float] = None,
    use_randomized_search: bool = False,
    random_search_iterations: int = 10,
    t0_train: Optional[pd.Series] = None,
    t1_train: Optional[pd.Series] = None,
):
    logger.info(f"--- Training {model_name} with {len(feature_names)} features ---")
    start_time = time.time()

    current_model_params = {}
    if model_name == "LGBMClassifier":
        current_model_params = {
            "random_state": random_state,
            "n_jobs": -1,
            "objective": "binary",
        }
        if scale_pos_weight_val is not None:
            current_model_params["scale_pos_weight"] = scale_pos_weight_val
        else:
            current_model_params["class_weight"] = "balanced"
    elif model_name == "XGBClassifier":
        current_model_params = {
            "random_state": random_state,
            "use_label_encoder": False,
            "eval_metric": "logloss",
        }
        if scale_pos_weight_val is not None:
            current_model_params["scale_pos_weight"] = scale_pos_weight_val
    elif "class_weight" in model_instance().get_params():
        if "class_weight" not in param_grid:
            current_model_params["class_weight"] = "balanced"
    if (
        "random_state" in model_instance().get_params()
        and "random_state" not in param_grid
    ):
        current_model_params["random_state"] = random_state
    if model_name == "SVC" and "probability" not in param_grid:
        current_model_params["probability"] = True

    estimator = model_instance(
        **{
            k: v
            for k, v in current_model_params.items()
            if k in model_instance().get_params()
        }
    )

    scorers = {
        "precision_c1": make_scorer(precision_score, pos_label=1, zero_division=0),
        "roc_auc": "roc_auc",
        "recall_c1": make_scorer(recall_score, pos_label=1, zero_division=0),
    }

    # Setup Purged & Embargo CV if timestamps are available
    if t0_train is not None and t1_train is not None:
        cv_splitter = PurgedEmbargoCV(t0_train, t1_train, n_splits=cv_folds)
        logger.info(f"Using PurgedEmbargoCV for time-series cross-validation.")
    else:
        cv_splitter = StratifiedKFold(
            n_splits=cv_folds, shuffle=True, random_state=random_state
        )
        logger.info(f"Using default StratifiedKFold for cross-validation.")

    if use_randomized_search:
        logger.info(
            f"Performing RandomizedSearchCV for {model_name}. Iterations: {random_search_iterations}. Optimizing for Precision (Class 1). CV Folds: {cv_folds}."
        )
        search_cv = RandomizedSearchCV(
            estimator=estimator,
            param_distributions=param_grid,
            n_iter=random_search_iterations,
            scoring=scorers,
            refit="precision_c1",
            cv=cv_splitter,
            verbose=1,
            n_jobs=-1,
            random_state=random_state,
        )
    else:
        logger.info(
            f"Performing GridSearchCV for {model_name}. Optimizing for Precision (Class 1). CV Folds: {cv_folds}."
        )
        search_cv = GridSearchCV(
            estimator=estimator,
            param_grid=param_grid,
            scoring=scorers,
            refit="precision_c1",
            cv=cv_splitter,
            verbose=1,
            n_jobs=-1,
        )

    search_cv.fit(X_train_scaled, y_train)

    best_model = search_cv.best_estimator_
    logger.info(f"Best parameters for {model_name}: {search_cv.best_params_}")

    best_cv_precision_c1 = search_cv.cv_results_["mean_test_precision_c1"][
        search_cv.best_index_
    ]
    best_cv_roc_auc = search_cv.cv_results_["mean_test_roc_auc"][search_cv.best_index_]
    logger.info(
        f"Best CV Precision (Class 1) for {model_name}: {best_cv_precision_c1:.4f}"
    )
    logger.info(f"Corresponding CV ROC AUC for {model_name}: {best_cv_roc_auc:.4f}")

    y_pred_test_proba = best_model.predict_proba(X_test_scaled)[:, 1]
    y_pred_test_labels = best_model.predict(X_test_scaled)

    precision_c1_test = precision_score(
        y_test, y_pred_test_labels, pos_label=1, zero_division=0
    )
    recall_c1_test = recall_score(
        y_test, y_pred_test_labels, pos_label=1, zero_division=0
    )
    roc_auc_test = roc_auc_score(y_test, y_pred_test_proba)
    logloss_test = log_loss(y_test, y_pred_test_proba)
    cm_test = confusion_matrix(y_test, y_pred_test_labels)

    tn, fp, fn, tp = 0, 0, 0, 0
    if cm_test.size == 4:
        tn, fp, fn, tp = cm_test.ravel()
    elif cm_test.size == 1:
        if y_test.iloc[0] == 0:
            tn = cm_test[0, 0]
        else:
            tp = cm_test[0, 0]

    training_time = time.time() - start_time
    logger.info(
        f"{model_name} training and evaluation completed in {training_time:.2f}s."
    )
    logger.info(f"Metrics for {model_name} on Test Set:")
    logger.info(f"  Precision (Class 1): {precision_c1_test:.4f}")
    logger.info(f"  Recall (Class 1):    {recall_c1_test:.4f}")
    logger.info(f"  ROC AUC:             {roc_auc_test:.4f}")
    logger.info(f"  LogLoss:             {logloss_test:.4f}")
    logger.info(f"  Confusion Matrix (Test):\n{cm_test}")
    logger.info(f"  TP: {tp}, FP: {fp}, FN: {fn}, TN: {tn}")

    if hasattr(best_model, "feature_importances_"):
        try:
            importances = best_model.feature_importances_
            feature_importance_df = pd.DataFrame(
                {"feature": feature_names, "importance": importances}
            )
            feature_importance_df = feature_importance_df.sort_values(
                by="importance", ascending=False
            )
            logger.info(f"Top 10 feature importances for {model_name}:")
            logger.info("\n" + feature_importance_df.head(10).to_string(index=False))
        except Exception as e_fi:
            logger.warning(
                f"Could not retrieve/display feature importances for {model_name}: {e_fi}"
            )

    results = {
        "model_name": model_name,
        "feature_set_name": f"{len(feature_names)} features"
        if len(feature_names) > 10
        else ", ".join(feature_names),
        "num_features": len(feature_names),
        "best_params": search_cv.best_params_,
        "cv_precision_c1": best_cv_precision_c1,
        "cv_roc_auc": best_cv_roc_auc,
        "test_precision_c1": precision_c1_test,
        "test_recall_c1": recall_c1_test,
        "test_roc_auc": roc_auc_test,
        "test_logloss": logloss_test,
        "test_tp": tp,
        "test_fp": fp,
        "test_fn": fn,
        "test_tn": tn,
        "training_time_seconds": training_time,
    }
    return results


class PurgedEmbargoCV:
    """
    Purged and Embargo Cross-Validation for Time Series (Lopez de Prado).
    """
    def __init__(self, t0: pd.Series, t1: pd.Series, n_splits: int = 5, embargo_pct: float = 0.01):
        self.t0 = pd.to_datetime(t0).reset_index(drop=True)
        self.t1 = pd.to_datetime(t1).reset_index(drop=True)
        self.n_splits = n_splits
        self.embargo_pct = embargo_pct

    def split(self, X, y=None, groups=None):
        n_samples = len(X)
        indices = np.arange(n_samples)
        
        test_size = n_samples // (self.n_splits + 1)
        
        total_duration = self.t0.max() - self.t0.min()
        embargo_duration = total_duration * self.embargo_pct
        
        for i in range(self.n_splits):
            test_start = (i + 1) * test_size
            test_end = (i + 2) * test_size if i < self.n_splits - 1 else n_samples
            
            test_indices = indices[test_start:test_end]
            
            test_t0_min = self.t0.iloc[test_start]
            test_t1_max = self.t1.iloc[test_indices].max()
            
            embargo_boundary = test_t1_max + embargo_duration
            
            train_indices = []
            for idx in indices:
                if idx >= test_start and idx < test_end:
                    continue
                    
                t0_val = self.t0.iloc[idx]
                t1_val = self.t1.iloc[idx]
                
                is_overlap = (t0_val <= test_t1_max) and (t1_val >= test_t0_min)
                is_embargoed = (t0_val > test_t1_max) and (t0_val <= embargo_boundary)
                
                if not is_overlap and not is_embargoed:
                    train_indices.append(idx)
                    
            yield np.array(train_indices), np.array(test_indices)

    def get_n_splits(self, X=None, y=None, groups=None):
        return self.n_splits


def run_sklearn_training_from_config(config: Dict[str, Any]):
    """
    Performs a full batch training cycle for a Scikit-learn model based on a configuration dictionary.
    This function encapsulates all the logic previously found in the if __name__ == "__main__" block.

    Args:
        config (Dict[str, Any]): Dictionary with parameters similar to those
                                 obtained from argparse.

    Returns:
        Path: Path to the file with the final report.
    """
    # Step 1: Logging setup
    log_level_str = config.get("log_level", "INFO").upper()
    if setup_bot_logging:
        setup_bot_logging()
        logging.getLogger().setLevel(log_level_str)
        logger.setLevel(log_level_str)
    else:
        logging.getLogger().setLevel(log_level_str)
        logger.setLevel(log_level_str)

    logger.info("--- Starting Scikit-learn Batch Model Training from Config ---")
    logger.info(f"Script config: {config}")

    # Step 2: Defining paths and parameters from the config dictionary
    data_file_path = Path(config.get("data_file"))
    report_out_path = Path(
        config.get("report_out", "sklearn_batch_training_results_all_features.csv")
    )
    strategy_filter = config.get("strategy_filter")
    use_randomized_search_flag = config.get("use_randomized_search", False)

    # Step 3: Defining feature sets for testing
    # In this refactoring, we will simplify to a single set specified in config
    feature_set_params = {
        "use_all_numeric_features": config.get("use_all_numeric_features", False),
        "create_interactions": config.get("create_interactions", False),
        "interaction_set": config.get("interaction_set", None),
    }

    # Step 4: Defining models and their parameter grids
    lgbm_param_dist = {
        "n_estimators": [100, 200, 300, 400, 500],
        "learning_rate": [0.01, 0.02, 0.05, 0.1],
        "max_depth": [3, 5, 7, 10, -1],
        "num_leaves": [15, 31, 50, 70, 100],
        "reg_alpha": [0, 0.01, 0.1, 0.5, 1],
        "reg_lambda": [0, 0.01, 0.1, 0.5, 1],
        "colsample_bytree": [0.6, 0.7, 0.8, 0.9, 1.0],
        "subsample": [0.6, 0.7, 0.8, 0.9, 1.0],
        "min_child_samples": [10, 20, 30, 50],
    }
    xgb_param_dist = {
        "n_estimators": [100, 200, 300, 400, 500],
        "learning_rate": [0.01, 0.02, 0.05, 0.1],
        "max_depth": [3, 5, 7, 9],
        "gamma": [0, 0.1, 0.5, 1],
        "reg_lambda": [0.1, 0.5, 1, 5],
        "reg_alpha": [0, 0.01, 0.1, 0.5],
        "colsample_bytree": [0.6, 0.7, 0.8, 0.9, 1.0],
        "subsample": [0.6, 0.7, 0.8, 0.9, 1.0],
        "min_child_weight": [1, 3, 5],
    }
    default_lgbm_grid = {
        "n_estimators": [100, 200],
        "learning_rate": [0.05, 0.1],
        "max_depth": [3, 5, 7],
        "num_leaves": [15, 31],
    }
    default_xgb_grid = {
        "n_estimators": [100, 200],
        "learning_rate": [0.05, 0.1],
        "max_depth": [3, 5, 7],
    }

    models_to_test = {
        "LGBMClassifier": {
            "model_class": lgb.LGBMClassifier,
            "param_grid": lgbm_param_dist
            if use_randomized_search_flag
            else default_lgbm_grid,
        },
        "XGBClassifier": {
            "model_class": xgb.XGBClassifier,
            "param_grid": xgb_param_dist
            if use_randomized_search_flag
            else default_xgb_grid,
        },
        "GradientBoostingClassifier": {
            "model_class": GradientBoostingClassifier,
            "param_grid": {
                "n_estimators": [100, 200, 300],
                "learning_rate": [0.05, 0.1],
                "max_depth": [3, 5],
                "subsample": [0.7, 1.0],
            },
        },
        "RandomForestClassifier": {
            "model_class": RandomForestClassifier,
            "param_grid": {
                "n_estimators": [100, 200, 300],
                "max_depth": [5, 10, 15, None],
                "min_samples_split": [2, 5, 10],
                "min_samples_leaf": [1, 3, 5],
                "class_weight": ["balanced", "balanced_subsample"],
            },
        },
        "SVC": {
            "model_class": SVC,
            "param_grid": {
                "C": [0.1, 1, 10],
                "gamma": ["scale", "auto", 0.01, 0.1],
                "kernel": ["rbf"],
                "class_weight": ["balanced"],
            },
        },
    }

    all_results = []

    # Step 5: Data loading
    fs_name_from_config = config.get("feature_set_name", "CustomSet")
    logger.info(f"--- Testing Feature Set Configuration: {fs_name_from_config} ---")

    load_result = load_training_data(
        file_path=data_file_path,
        target_col=TARGET_COLUMN,
        raw_json_col=RAW_FEATURES_JSON_COLUMN,
        strategy_to_train=strategy_filter,
        create_interactions=feature_set_params["create_interactions"],
        interaction_set_to_use=feature_set_params["interaction_set"],
        use_all_numeric_features=feature_set_params["use_all_numeric_features"],
    )

    if load_result is None:
        logger.error(
            f"Failed to load data for feature set config {fs_name_from_config}. Exiting."
        )
        raise FileNotFoundError("Failed to load training data.")

    X, y, t0, t1, actual_features_used = load_result
    if X.empty or y.empty or not actual_features_used:
        logger.error(
            f"Data is empty or no features after loading for set {fs_name_from_config}. Exiting."
        )
        raise ValueError("Data is empty or has no features after loading.")

    logger.info(
        f"Feature set for '{fs_name_from_config}' loaded with {X.shape[1]} features."
    )

    # Step 6: Data splitting and scaling
    test_size_val = config.get("test_size", 0.20)
    random_state_val = config.get("random_state", 42)

    # Sequential split for time series to prevent look-ahead bias
    split_idx = int(len(X) * (1.0 - test_size_val))
    X_train = X.iloc[:split_idx]
    X_test = X.iloc[split_idx:]
    y_train = y.iloc[:split_idx]
    y_test = y.iloc[split_idx:]

    t0_train = t0.iloc[:split_idx]
    t1_train = t1.iloc[:split_idx]

    logger.info(f"Train data: {X_train.shape}, Test data: {X_test.shape} (Sequential time series split)")

    scaler = StandardScaler()
    X_train_scaled_np = scaler.fit_transform(X_train)
    X_test_scaled_np = scaler.transform(X_test)
    X_train_scaled_df = pd.DataFrame(X_train_scaled_np, columns=X_train.columns)
    X_test_scaled_df = pd.DataFrame(X_test_scaled_np, columns=X_test.columns)

    spw = calculate_scale_pos_weight(y_train)

    # Step 7: Model training and evaluation loop
    for model_name, model_config in models_to_test.items():
        try:
            current_param_grid = model_config["param_grid"]
            current_use_randomized_search = use_randomized_search_flag

            if (
                model_name not in ["LGBMClassifier", "XGBClassifier"]
                and use_randomized_search_flag
            ):
                logger.info(
                    f"Using GridSearchCV for {model_name} as specific distributions are not set."
                )
                current_use_randomized_search = False

            model_results = train_evaluate_sklearn_model(
                model_name=model_name,
                model_instance=model_config["model_class"],
                param_grid=current_param_grid,
                X_train_scaled=X_train_scaled_df,
                y_train=y_train,
                X_test_scaled=X_test_scaled_df,
                y_test=y_test,
                feature_names=actual_features_used,
                cv_folds=config.get("cv_folds", 5),
                random_state=random_state_val,
                scale_pos_weight_val=spw,
                use_randomized_search=current_use_randomized_search,
                random_search_iterations=config.get("random_search_iters", 20),
                t0_train=t0_train,
                t1_train=t1_train,
            )
            model_results["feature_set_name_key"] = fs_name_from_config
            all_results.append(model_results)
        except Exception as e_model_train:
            logger.error(
                f"Error training model {model_name} for feature set config {fs_name_from_config}: {e_model_train}",
                exc_info=True,
            )

    # Step 8: Outputting and saving results
    logger.info("\n--- Overall Batch Training Summary ---")
    results_df = pd.DataFrame(all_results)

    if not results_df.empty:
        display_cols = [
            "model_name",
            "feature_set_name_key",
            "num_features",
            "test_precision_c1",
            "test_roc_auc",
            "test_recall_c1",
            "test_logloss",
            "test_tp",
            "test_fp",
            "test_fn",
            "cv_precision_c1",
            "cv_roc_auc",
            "best_params",
            "training_time_seconds",
        ]
        display_cols = [col for col in display_cols if col in results_df.columns]
        results_df_display = results_df[display_cols].copy()

        float_cols = [
            "test_precision_c1",
            "test_roc_auc",
            "test_recall_c1",
            "test_logloss",
            "cv_precision_c1",
            "cv_roc_auc",
            "training_time_seconds",
        ]
        for col in float_cols:
            if col in results_df_display.columns:
                results_df_display[col] = results_df_display[col].map(
                    lambda x: f"{x:.4f}" if pd.notnull(x) else "N/A"
                )

        if (
            "test_precision_c1" in results_df_display.columns
            and "test_roc_auc" in results_df_display.columns
        ):
            results_df_numeric_sort = results_df.copy()
            results_df_numeric_sort["test_precision_c1"] = pd.to_numeric(
                results_df_numeric_sort["test_precision_c1"], errors="coerce"
            )
            results_df_numeric_sort["test_roc_auc"] = pd.to_numeric(
                results_df_numeric_sort["test_roc_auc"], errors="coerce"
            )
            results_df_display = results_df_display.loc[
                results_df_numeric_sort.sort_values(
                    by=["test_precision_c1", "test_roc_auc"], ascending=[False, False]
                ).index
            ]

        logger.info("Results Table (Test Set Metrics):")
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 2000)
        pd.set_option("display.max_colwidth", 200)
        logger.info("\n" + results_df_display.to_string(index=False))

        try:
            report_out_path.parent.mkdir(parents=True, exist_ok=True)
            results_df.to_csv(report_out_path, index=False)
            logger.info(f"\nFull results saved to {report_out_path}")
        except Exception as e_csv:
            logger.error(f"Failed to save results to CSV: {e_csv}")
    else:
        logger.info("No results to display. All model training runs may have failed.")

    logger.info("--- Scikit-learn Batch Model Training Finished ---")
    return report_out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scikit-learn Batch Trainer for ML Confirmation Model"
    )
    parser.add_argument(
        "--data-file",
        type=str,
        default=str(DEFAULT_DATA_FILE_FROM_CONFIG),
        help="Path to training data CSV.",
    )
    parser.add_argument(
        "--report-out",
        type=str,
        default=f"sklearn_batch_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        help="Path to save the final results CSV report.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level.",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=0.20,
        help="Proportion of dataset for test split.",
    )
    parser.add_argument(
        "--cv-folds", type=int, default=5, help="Number of folds for cross-validation."
    )
    parser.add_argument(
        "--random-state", type=int, default=42, help="Random state for reproducibility."
    )
    parser.add_argument(
        "--strategy-filter",
        type=str,
        default=None,
        help="Optional: Filter data for a specific strategy (e.g., VolumeBreakout).",
    )
    parser.add_argument(
        "--use-randomized-search",
        action="store_true",
        default=False,
        help="Use RandomizedSearchCV instead of GridSearchCV for hyperparameter tuning.",
    )
    parser.add_argument(
        "--random-search-iters",
        type=int,
        default=20,
        help="Number of iterations for RandomizedSearchCV.",
    )
    # Adding arguments for feature management
    parser.add_argument(
        "--feature-set-name",
        type=str,
        default="Default_Top5",
        help="A descriptive name for the feature set being tested.",
    )
    parser.add_argument(
        "--use-all-numeric-features",
        action="store_true",
        default=False,
        help="Use all numeric features found in the data instead of the predefined Top-5.",
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
        choices=[None, "vzaim3"],
        help="Which set of interaction features to use. Requires --create-interactions.",
    )

    args = parser.parse_args()

    try:
        # Converting args to a dictionary
        config_from_cli = vars(args)

        # Calling the main function with the configuration
        final_report_path = run_sklearn_training_from_config(config_from_cli)

        print("\n--- Command-Line Training Summary ---")
        print("Scikit-learn training complete.")
        print(f"Training report saved to: {final_report_path}")
        print("-------------------------------------")

    except (ValueError, FileNotFoundError) as e:
        logging.critical(
            f"A critical error occurred during training: {e}", exc_info=True
        )
        sys.exit(1)
    except Exception as e:
        logging.critical(f"An unexpected error occurred: {e}", exc_info=True)
        sys.exit(2)
