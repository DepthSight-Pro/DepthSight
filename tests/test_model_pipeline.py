# tests/test_model_pipeline.py
import pytest
from unittest.mock import MagicMock, patch
import logging
import math
import random

# Import the class under test and River dependencies
try:
    from river import compose, metrics, base
    from bot_module.model_pipeline import (
        ModelPipeline,
        DEFAULT_METRICS,
        ALL_POSSIBLE_FEATURES,
    )
except ImportError:
    pytest.skip(
        "Cannot import river or bot_module components for ModelPipeline tests.",
        allow_module_level=True,
    )

# --- Fixtures ---


@pytest.fixture
def sample_features():
    """Example of input features."""
    # Use features that may be in ALL_POSSIBLE_FEATURES or will be set as active
    return {"ema_20_rel": 0.5, "atr_14_rel": -1.2, "rsi_14": 10.0}


@pytest.fixture
def mock_pipeline_instance():
    """Creates a mock of a River pipeline instance."""
    mock_pipe = MagicMock(spec=compose.Pipeline)
    mock_pipe.predict_one.return_value = 1
    mock_pipe.predict_proba_one.return_value = {0: 0.3, 1: 0.7}
    mock_pipe.learn_one = MagicMock()

    # Mock for list(self.pipeline.steps.values())[-1]
    mock_last_step = MagicMock()
    mock_last_step.predict_proba_one = MagicMock(
        return_value={0: 0.3, 1: 0.7}
    )  # This is for predict_proba_one

    # So that list(self.pipeline.steps.values()) works
    # Assume that pipeline.steps is a dictionary
    mock_pipe.steps = {"scaler": MagicMock(), "model": mock_last_step}

    mock_pipe.clone.return_value = mock_pipe  # Simple return of self for cloning
    return mock_pipe


@pytest.fixture
def mock_metrics_dict():
    """Creates a mock of a River metrics dictionary."""
    metrics_dict = {}
    for name, metric_class_type in DEFAULT_METRICS.items():
        # Create a mock corresponding to the metric type (if it's a class, not an instance)
        # DEFAULT_METRICS stores instances, so spec=metric_class_type.get() if it is a Metric object
        # But since DEFAULT_METRICS contains instances, then spec=type(metric_class_type)
        mock_metric = MagicMock(
            spec=type(metric_class_type)
        )  # Use type() for instances
        mock_metric.get.return_value = random.random()
        mock_metric.update = MagicMock()
        mock_metric.clone.return_value = mock_metric
        metrics_dict[name] = mock_metric
    return metrics_dict


# --- Tests ---


@pytest.fixture
def pipeline_for_adaptation(monkeypatch):
    """Creates a ModelPipeline with configured parameters for the adaptation test."""
    monkeypatch.setattr("bot_module.model_pipeline.ADAPTATION_ENABLED", True)
    monkeypatch.setattr("bot_module.model_pipeline.ADAPTATION_CHECK_INTERVAL", 3)
    monkeypatch.setattr("bot_module.model_pipeline.MIN_HISTORY_FOR_CORR", 5)
    monkeypatch.setattr("bot_module.model_pipeline.FEATURE_HISTORY_MAX_SIZE", 10)
    monkeypatch.setattr("bot_module.model_pipeline.NUM_FEATURES_TO_REMOVE", 1)
    monkeypatch.setattr("bot_module.model_pipeline.NUM_FEATURES_TO_ADD", 1)
    # monkeypatch.setattr('bot_module.model_pipeline.MIN_CORRELATION_THRESHOLD', 0.01) # Removed, will pass to __init__

    # Ensure logger for model_pipeline and its parent are at DEBUG level for this specific test fixture
    # This is to try and override what setup_bot_logging might be doing at INFO level.
    logging.getLogger("bot_module").setLevel(logging.DEBUG)
    logging.getLogger("bot_module.model_pipeline").setLevel(logging.DEBUG)

    # Define the full set of features so there is something to add from
    all_features = {
        "feat_good",
        "feat_bad",
        "feat_ok1",
        "feat_ok2",
        "feat_ok3",
        "feat_neutral",
        "feat_new_available",
    }
    monkeypatch.setattr(
        "bot_module.model_pipeline.ALL_POSSIBLE_FEATURES", list(all_features)
    )

    # Starting with a subset of features
    initial_active = {
        "feat_good",
        "feat_bad",
        "feat_ok1",
        "feat_ok2",
        "feat_ok3",
        "feat_neutral",
    }

    # Pass the threshold directly to the constructor
    pipeline = ModelPipeline(
        initial_features=initial_active, min_correlation_threshold=0.15
    )  # Changed from 0.01
    return pipeline


def test_feature_correlation_calculation(pipeline_for_adaptation):
    """Correlation calculation test."""
    pipeline = pipeline_for_adaptation
    # Create history with explicit correlations
    pipeline.feature_pnl_history.extend(
        [
            ({"feat_good": 1, "feat_bad": 1, "feat_neutral": 1}, 10),
            ({"feat_good": 2, "feat_bad": -1, "feat_neutral": -1}, 20),
            ({"feat_good": 3, "feat_bad": 1, "feat_neutral": 1}, 30),
            ({"feat_good": 4, "feat_bad": -1, "feat_neutral": -1}, 40),
            ({"feat_good": 5, "feat_bad": 1, "feat_neutral": -1}, 50),
        ]
    )

    corrs = pipeline._calculate_feature_correlations()

    assert "feat_good" in corrs and corrs["feat_good"] > 0.99
    assert "feat_bad" in corrs and math.isclose(corrs["feat_bad"], 0.0, abs_tol=1e-9)
    assert "feat_neutral" in corrs and corrs["feat_neutral"] < 0


def test_feature_adaptation_removes_and_adds(pipeline_for_adaptation):
    """Test: _adapt_features removes the worst feature and adds a new one."""
    pipeline = pipeline_for_adaptation
    # Filling history
    pipeline.feature_pnl_history.extend(
        [
            (
                {
                    "feat_good": 10,
                    "feat_bad": 5,
                    "feat_ok1": 8,
                    "feat_ok2": 7,
                    "feat_ok3": 6,
                    "feat_neutral": 1,
                },
                10,
            ),
            (
                {
                    "feat_good": 20,
                    "feat_bad": 4,
                    "feat_ok1": 9,
                    "feat_ok2": 8,
                    "feat_ok3": 7,
                    "feat_neutral": -1,
                },
                20,
            ),
            (
                {
                    "feat_good": 30,
                    "feat_bad": 3,
                    "feat_ok1": 7,
                    "feat_ok2": 6,
                    "feat_ok3": 8,
                    "feat_neutral": 1,
                },
                30,
            ),
            (
                {
                    "feat_good": 40,
                    "feat_bad": 2,
                    "feat_ok1": 8,
                    "feat_ok2": 9,
                    "feat_ok3": 6,
                    "feat_neutral": -2,
                },
                40,
            ),
            (
                {
                    "feat_good": 50,
                    "feat_bad": 1,
                    "feat_ok1": 6,
                    "feat_ok2": 7,
                    "feat_ok3": 9,
                    "feat_neutral": 0,
                },
                50,
            ),
        ]
    )

    initial_features = pipeline.active_features.copy()
    assert "feat_neutral" in initial_features
    assert (
        "feat_new_available" not in initial_features
    )  # Check the new feature isn't there initially

    pipeline._adapt_features()

    final_features = pipeline.active_features
    # feat_ok2 should have the worst absolute correlation (0.0)
    # and its original correlation (0.0) should be less than the new threshold (0.01), so it's removed.
    assert "feat_ok2" not in final_features, "feat_ok2 was not removed"
    assert "feat_neutral" in final_features, "feat_neutral should NOT have been removed"
    assert "feat_good" in final_features  # Best should remain
    assert "feat_bad" in final_features
    assert "feat_ok1" in final_features
    # feat_ok2 is removed
    assert "feat_ok3" in final_features

    # Initial features had 6. One removed, one added. Count should remain 6.
    assert len(final_features) == len(initial_features), (
        f"Number of features should be {len(initial_features)} after remove/add"
    )

    # Check that 'feat_new_available' was added, and it's the only one added
    expected_removed_feature = "feat_ok2"
    added_features_set = final_features - (
        initial_features - {expected_removed_feature}
    )
    assert len(added_features_set) == 1, "Exactly one new feature should be added"
    assert "feat_new_available" in added_features_set


def test_model_pipeline_init_defaults():
    """Test initialization with default parameters."""
    pipeline = ModelPipeline()
    assert isinstance(pipeline.pipeline, compose.Pipeline)
    assert isinstance(pipeline.metric_trackers.get("accuracy"), metrics.Accuracy)
    assert pipeline.model_path is None
    assert pipeline.steps_processed == 0
    assert pipeline.active_features == set(
        ALL_POSSIBLE_FEATURES
    )  # Checking active_features initialization


def test_model_pipeline_init_custom_no_load(mock_pipeline_instance, mock_metrics_dict):
    """Test initialization with custom parameters WITHOUT loading the model."""
    # Pass initial_features so they are used instead of ALL_POSSIBLE_FEATURES
    initial_feats = {"ema_20_rel", "custom_feat"}
    pipeline = ModelPipeline(
        pipeline=mock_pipeline_instance,
        metric_trackers=mock_metrics_dict,
        model_path=None,  # Do not specify the path to avoid a loading attempt
        initial_features=initial_feats,
    )
    assert (
        pipeline.pipeline is mock_pipeline_instance
    )  # mock_pipeline_instance.clone() returned itself

    # Check element-wise that the metric mocks are the same
    assert len(pipeline.metric_trackers) == len(mock_metrics_dict)
    for key in mock_metrics_dict:
        assert key in pipeline.metric_trackers
        assert (
            pipeline.metric_trackers[key] is mock_metrics_dict[key]
        )  # clone() returned the same mock

    assert pipeline.active_features == initial_feats


def test_model_pipeline_init_custom_with_nonexistent_load(
    mock_pipeline_instance, mock_metrics_dict, tmp_path
):
    """Test initialization with custom parameters and a NON-existent load path."""
    model_path = tmp_path / "custom_model.pkl"
    initial_feats = {"ema_20_rel", "another_feat"}

    # We expect that if the file is not found, defaults are used
    pipeline = ModelPipeline(
        pipeline=mock_pipeline_instance,  # This pipeline will be replaced by the default one upon failed loading
        metric_trackers=mock_metrics_dict,  # Similarly for metrics
        model_path=model_path,
        initial_features=initial_feats,  # This will be used if the model fails to load OR if there are no active_features in the loaded model
    )
    # Since load_model did not find the file, it initializes pipeline and metrics with defaults
    assert (
        pipeline.pipeline is not mock_pipeline_instance
    )  # Must be a clone of DEFAULT_PIPELINE
    assert isinstance(pipeline.pipeline, compose.Pipeline)

    # Check that metrics have reset to defaults (are not the passed mocks)
    assert len(pipeline.metric_trackers) == len(DEFAULT_METRICS)
    for key in DEFAULT_METRICS:
        assert key in pipeline.metric_trackers
        assert isinstance(pipeline.metric_trackers[key], type(DEFAULT_METRICS[key]))
        if key in mock_metrics_dict:  # If the key was in mocks
            assert (
                pipeline.metric_trackers[key] is not mock_metrics_dict[key]
            )  # Ensure it's not the same mock

    assert pipeline.model_path == model_path
    assert pipeline.steps_processed == 0
    # active_features will be ALL_POSSIBLE_FEATURES, as load_model() overwrites initial_features upon unsuccessful loading
    assert pipeline.active_features == set(ALL_POSSIBLE_FEATURES)


def test_predict_one(sample_features, mock_pipeline_instance):
    """predict_one test."""
    # Set active_features so that sample_features pass filtering
    active_f = set(sample_features.keys())
    pipeline = ModelPipeline(pipeline=mock_pipeline_instance, initial_features=active_f)

    prediction = pipeline.predict_one(sample_features)
    mock_pipeline_instance.predict_one.assert_called_once_with(sample_features)
    assert prediction == 1


def test_predict_proba_one(sample_features, mock_pipeline_instance):
    active_f = set(sample_features.keys())
    pipeline = ModelPipeline(pipeline=mock_pipeline_instance, initial_features=active_f)

    proba = pipeline.predict_proba_one(sample_features)
    # predict_proba_one is called on the pipeline itself
    mock_pipeline_instance.predict_proba_one.assert_called_once_with(sample_features)
    assert proba == {0: 0.3, 1: 0.7}


def test_predict_proba_one_no_method(sample_features):
    """Test predict_proba_one if the model does not have such a method."""
    mock_simple_model = MagicMock(
        spec=base.Estimator
    )  # Model without predict_proba_one
    mock_simple_model.predict_one = MagicMock(return_value=1)  # But with predict_one

    mock_simple_pipeline_obj = MagicMock(spec=compose.Pipeline)
    mock_simple_pipeline_obj.steps = {"model": mock_simple_model}  # Last step
    mock_simple_pipeline_obj.clone.return_value = mock_simple_pipeline_obj
    mock_simple_pipeline_obj.predict_one.return_value = 1  # For internal call
    # Important: the pipeline itself will NOT have predict_proba_one if its last step does not have it
    # Therefore hasattr(self.pipeline, 'predict_proba_one') will be False
    # Modify the mock_pipeline fixture so it doesn't have predict_proba_one
    del mock_simple_pipeline_obj.predict_proba_one

    active_f = set(sample_features.keys())
    pipeline = ModelPipeline(
        pipeline=mock_simple_pipeline_obj, initial_features=active_f
    )
    proba = pipeline.predict_proba_one(sample_features)
    assert proba is None


def test_learn_one(sample_features, mock_pipeline_instance, mock_metrics_dict):
    """learn_one test."""
    active_f = set(sample_features.keys())
    pipeline = ModelPipeline(
        pipeline=mock_pipeline_instance,
        metric_trackers=mock_metrics_dict,
        initial_features=active_f,
    )
    y_true = 1
    initial_steps = pipeline.steps_processed

    # Mock predict_one and predict_proba_one of ModelPipeline itself so they don't call the pipeline mock unnecessarily
    # Otherwise mock_pipeline_instance.predict_one will be called inside learn_one if y_pred/proba are not passed
    with (
        patch.object(pipeline, "predict_one", return_value=y_true),
        patch.object(pipeline, "predict_proba_one", return_value={0: 0.1, 1: 0.9}),
    ):
        pipeline.learn_one(
            sample_features, y_true
        )  # y_pred and proba will be None, internal predict* will be called

        # Checking model training call
        mock_pipeline_instance.learn_one.assert_called_once_with(
            sample_features, y_true, sample_weight=None
        )
        # Checking metrics update call
        for name, metric_mock in mock_metrics_dict.items():
            metric_mock.update.assert_called_once()
        # Checking step counter increment
        assert pipeline.steps_processed == initial_steps + 1


def test_get_metrics(mock_metrics_dict):
    """get_metrics test."""
    pipeline = ModelPipeline(
        metric_trackers=mock_metrics_dict
    )  # active_features will be ALL_POSSIBLE_FEATURES
    pipeline.steps_processed = 123
    metrics_result = pipeline.get_metrics()

    # +1 for steps_processed, +1 for active_features_count
    assert len(metrics_result) == len(mock_metrics_dict) + 2
    assert metrics_result["steps_processed"] == 123
    assert metrics_result["active_features_count"] == len(ALL_POSSIBLE_FEATURES)
    for name, metric_mock in mock_metrics_dict.items():
        metric_mock.get.assert_called_once()
        assert name in metrics_result
        assert isinstance(metrics_result[name], float)


def test_save_and_load_model(tmp_path, sample_features):
    """Test for saving and loading a model."""
    model_save_path = tmp_path / "full_model.joblib"

    # 1. Create, "train" and save
    pipeline_to_save = ModelPipeline(initial_features=set(sample_features.keys()))
    # Ensure that sample_features correspond to active_features
    assert pipeline_to_save.active_features == set(sample_features.keys())

    pipeline_to_save.learn_one(sample_features, 1)
    pipeline_to_save.learn_one({k: v * 0.5 for k, v in sample_features.items()}, 0)

    steps_before_save = pipeline_to_save.steps_processed
    active_features_before_save = (
        pipeline_to_save.active_features.copy()
    )  # Copying for comparison
    assert steps_before_save == 2

    pipeline_to_save.save_model(model_save_path)
    assert model_save_path.exists()

    # 2. Create a NEW instance and load
    pipeline_loaded = ModelPipeline(
        model_path=model_save_path
    )  # Loading will occur in __init__

    assert pipeline_loaded.steps_processed == steps_before_save
    assert (
        pipeline_loaded.active_features == active_features_before_save
    )  # Checking active_features

    # Check for the presence of metrics and their type (without checking values, as they depend on data)
    assert list(pipeline_loaded.metric_trackers.keys()) == list(DEFAULT_METRICS.keys())
    assert isinstance(pipeline_loaded.metric_trackers["accuracy"], metrics.Accuracy)

    # Check that the pipeline is loaded (compare string representation or component types)
    assert str(pipeline_loaded.pipeline) == str(pipeline_to_save.pipeline)

    # Try to make a prediction with the loaded model
    prediction = pipeline_loaded.predict_one(sample_features)
    assert prediction in [
        0,
        1,
        None,
    ]  # Depends on the trained model, None if filtering did not pass


def test_load_model_file_not_found(tmp_path):
    """Test for loading a non-existent file."""
    model_path = tmp_path / "non_existent.joblib"
    pipeline = ModelPipeline(model_path=model_path)
    # load_model is called in __init__
    assert pipeline.pipeline is not None
    assert isinstance(pipeline.pipeline, compose.Pipeline)  # Should be default
    assert pipeline.steps_processed == 0
    assert pipeline.active_features == set(
        ALL_POSSIBLE_FEATURES
    )  # Default active features


@patch("joblib.load")
def test_load_model_invalid_data_format(mock_joblib_load, tmp_path):
    """Test loading a file with an incorrect format (not a dictionary)."""
    model_path = tmp_path / "invalid_format.joblib"
    model_path.touch()
    mock_joblib_load.return_value = "this is not a dict"  # Invalid format

    pipeline = ModelPipeline(model_path=model_path)

    assert isinstance(pipeline.pipeline, compose.Pipeline)  # Default
    assert pipeline.steps_processed == 0
    assert pipeline.active_features == set(ALL_POSSIBLE_FEATURES)
    mock_joblib_load.assert_called_once_with(model_path)


@patch("joblib.load")
def test_load_model_missing_keys(mock_joblib_load, tmp_path):
    """Test loading a file with missing keys in the dictionary."""
    model_path = tmp_path / "missing_keys.joblib"
    model_path.touch()
    mock_joblib_load.return_value = {"version": "1.5"}  # Missing 'pipeline', 'metrics'

    pipeline = ModelPipeline(model_path=model_path)

    assert isinstance(pipeline.pipeline, compose.Pipeline)  # Default
    assert pipeline.steps_processed == 0
    assert pipeline.active_features == set(ALL_POSSIBLE_FEATURES)
    mock_joblib_load.assert_called_once_with(model_path)
