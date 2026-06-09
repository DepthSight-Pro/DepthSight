# tests/test_oracle_component.py
import pytest
import pandas as pd
import numpy as np
import joblib
from pathlib import Path
from sklearn.mixture import GaussianMixture

# Import the class for testing
from bot_module.oracle import Oracle


@pytest.fixture(scope="module")
def mock_dataset_path(tmp_path_factory) -> Path:
    """
    Creates a temporary 'golden_dataset.parquet' file with valid data
    for a single test run.
    """
    # Create a temporary directory for this test module
    tmp_dir = tmp_path_factory.mktemp("oracle_data")
    file_path = tmp_dir / "golden_dataset.parquet"

    # Generate 1500 rows of data, as in your script
    num_rows = 1500
    timestamps = pd.to_datetime(
        pd.date_range(end="2023-01-01", periods=num_rows, freq="1min", tz="UTC")
    )

    df = pd.DataFrame(
        {
            "timestamp": timestamps.astype(np.int64) // 10**6,  # in milliseconds
            "open": np.linspace(100, 110, num_rows),
            "high": np.linspace(101, 111, num_rows),
            "low": np.linspace(99, 109, num_rows),
            "close": np.linspace(100.5, 110.5, num_rows),
            "volume": np.random.randint(100, 1000, num_rows),
            "positive": np.random.randint(0, 5, num_rows),
            "negative": np.random.randint(0, 5, num_rows),
            "important": np.random.randint(0, 2, num_rows),
        }
    )
    df.set_index(pd.to_datetime(df["timestamp"], unit="ms", utc=True), inplace=True)
    df.to_parquet(file_path)
    print(f"Temporary dataset created for test: {file_path}")
    return file_path


@pytest.fixture(scope="module")
def mock_model_path(tmp_path_factory) -> Path:
    """
    Creates and saves a temporary but working 'oracle_model.joblib' model.
    """
    tmp_dir = tmp_path_factory.mktemp("oracle_model")
    model_path = tmp_dir / "oracle_model.joblib"

    # Create a simple GMM model and "train" it on random data
    dummy_features = np.random.rand(100, 3)
    dummy_model = GaussianMixture(n_components=3, random_state=42)
    dummy_model.fit(dummy_features)

    joblib.dump(dummy_model, model_path)
    print(f"Temporary model created for test: {model_path}")
    return model_path


@pytest.mark.asyncio
async def test_oracle_initialization_and_prediction(mock_model_path, mock_dataset_path):
    """
    Test: Verifies that the real Oracle class can be initialized,
    process a real DataFrame, and produce a correct result.
    """
    # --- 1. Arrange (Preparation) ---

    # Initialize Oracle with the path to our temporary but valid model
    try:
        oracle = Oracle(model_path=mock_model_path)
    except Exception as e:
        pytest.fail(f"Oracle class initialization failed with error: {e}")

    # Load our temporary dataset
    kline_history = pd.read_parquet(mock_dataset_path)
    assert not kline_history.empty, "Failed to load test dataset"

    # --- 2. Act (Action) ---
    try:
        regime, confidence = await oracle.get_current_regime(kline_history)
    except Exception as e:
        pytest.fail(f"Call to get_current_regime failed with error: {e}")

    # --- 3. Assert (Check) ---
    print(f"Result obtained: Mode={regime}, Confidence={confidence:.2f}%")

    assert isinstance(regime, int), "Regime must be an integer (int)"
    assert isinstance(confidence, float), (
        "Confidence must be a floating-point number (float)"
    )
    assert regime >= 0, "Regime ID cannot be negative in a successful scenario"
    assert 0.0 <= confidence <= 100.0, "Confidence must be in the range from 0 to 100"

    # Check caching: a repeated call with the same data should return the same result
    cached_regime, cached_confidence = await oracle.get_current_regime(kline_history)
    assert cached_regime == regime
    assert cached_confidence == confidence
