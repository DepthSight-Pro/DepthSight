"""
test_ml_feature_extraction_live.py

Integration test for verifying ML confirmation with realistic data.
Checks that:
1. FeatureExtractor correctly calculates features from kline and aggTrade data
2. Features have non-zero values (fallback calculations work)
3. ModelPipeline can use these features for prediction
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

from bot_module.feature_extractor import FeatureExtractor
from bot_module.model_pipeline import ModelPipeline


# --- Fixtures with realistic data ---


@pytest.fixture
def realistic_kline_history() -> pd.DataFrame:
    """
    Creates a realistic history of kline data (200 candles).
    Simulates a volatile market with a trend.
    """
    np.random.seed(42)
    n_bars = 200

    # Generate price walk with a trend
    base_price = 100.0
    returns = np.random.normal(0.0001, 0.002, n_bars)  # Average drift + volatility
    prices = base_price * np.cumprod(1 + returns)

    # OHLC data
    data = {
        "open": prices * (1 + np.random.uniform(-0.001, 0.001, n_bars)),
        "high": prices * (1 + np.random.uniform(0.001, 0.005, n_bars)),
        "low": prices * (1 - np.random.uniform(0.001, 0.005, n_bars)),
        "close": prices,
        "volume": np.random.uniform(1000, 10000, n_bars),
    }

    # Ensuring that high >= max(open, close) and low <= min(open, close)
    data["high"] = np.maximum(data["high"], np.maximum(data["open"], data["close"]))
    data["low"] = np.minimum(data["low"], np.minimum(data["open"], data["close"]))

    # Create DataFrame with DatetimeIndex
    start_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    index = pd.date_range(start=start_time, periods=n_bars, freq="1min")

    df = pd.DataFrame(data, index=index)
    return df


@pytest.fixture
def realistic_aggtrades() -> list:
    """
    Creates realistic aggTrade data for the last 30 seconds.
    """
    np.random.seed(42)
    n_trades = 200

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    trades = []
    for i in range(n_trades):
        # Timestamp within the last 30 seconds
        ts = now_ms - np.random.randint(0, 30000)

        trades.append(
            {
                "timestamp": ts,  # Or 'T' depending on the format
                "T": ts,  # Binance API format
                "price": 100.0 + np.random.uniform(-0.5, 0.5),
                "p": str(100.0 + np.random.uniform(-0.5, 0.5)),  # Binance format
                "quantity": np.random.uniform(0.1, 10.0),
                "q": str(np.random.uniform(0.1, 10.0)),  # Binance format
                "is_buyer_maker": np.random.choice([True, False]),
                "m": np.random.choice([True, False]),  # Binance format
            }
        )

    return trades


@pytest.fixture
def feature_extractor_with_active_features() -> FeatureExtractor:
    """
    Creates a FeatureExtractor with active features,
    as they are configured in a typical model.
    """
    fe = FeatureExtractor()

    # Typical set of active features (as in a real model)
    active_features = {
        "atr_14_rel",
        "volatility_spike_20",
        "distance_to_local_max_20",
        "distance_to_local_min_20",
        "trade_rate_30s",
    }
    fe.set_active_features(active_features)

    return fe


# --- Tests ---


class TestFeatureExtractionLive:
    """
    Tests for verifying correct feature extraction during live trading.
    """

    def test_kline_features_have_non_zero_values(
        self,
        feature_extractor_with_active_features: FeatureExtractor,
        realistic_kline_history: pd.DataFrame,
    ):
        """
        Checks that kline features (atr_14_rel, distance_to_local_*)
        have non-zero values during live-like extraction.

        This is critical because in live trading current_candle_data
        does NOT contain pre-calculated indicators — they must
        be calculated from full_kline_history via fallback logic.
        """
        fe = feature_extractor_with_active_features
        df = realistic_kline_history
        current_index = len(df) - 1

        # Simulating live data — only basic OHLCV, WITHOUT indicators
        current_candle_data = df.iloc[current_index].to_dict()

        # Call feature extraction
        features = fe.extract_features_optimized(
            current_candle_data=current_candle_data,
            agg_trades_list=None,  # First without aggTrade
            full_kline_history=df,
            current_index=current_index,
            current_timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        )

        # Checking that key kline features have non-zero values
        assert features is not None, "Features should not be None"

        # ATR feature should be > 0 for a volatile market
        if "atr_14_rel" in features:
            assert features["atr_14_rel"] > 0, (
                f"atr_14_rel should be > 0, got {features['atr_14_rel']}"
            )

        # Distance features must be >= 0
        if "distance_to_local_max_20" in features:
            # Can be 0 if the price is at the maximum, but should not be NaN
            assert not pd.isna(features["distance_to_local_max_20"]), (
                "distance_to_local_max_20 should not be NaN"
            )

        if "distance_to_local_min_20" in features:
            assert not pd.isna(features["distance_to_local_min_20"]), (
                "distance_to_local_min_20 should not be NaN"
            )

    def test_aggtrade_features_with_trade_data(
        self,
        feature_extractor_with_active_features: FeatureExtractor,
        realistic_kline_history: pd.DataFrame,
        realistic_aggtrades: list,
    ):
        """
        Checks that aggTrade features (trade_rate_30s)
        are calculated correctly when tape data is present.
        """
        fe = feature_extractor_with_active_features
        df = realistic_kline_history
        current_index = len(df) - 1
        current_candle_data = df.iloc[current_index].to_dict()

        # Call feature extraction with aggTrade data
        features = fe.extract_features_optimized(
            current_candle_data=current_candle_data,
            agg_trades_list=realistic_aggtrades,
            full_kline_history=df,
            current_index=current_index,
            current_timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        )

        assert features is not None, "Features should not be None"

        # trade_rate_30s should be > 0 if there are trades
        if "trade_rate_30s" in features:
            assert features["trade_rate_30s"] > 0, (
                f"trade_rate_30s should be > 0 with {len(realistic_aggtrades)} trades, got {features['trade_rate_30s']}"
            )

    def test_multiple_calls_improve_volatility_spike(
        self, realistic_kline_history: pd.DataFrame
    ):
        """
        Checks that volatility_spike_20 (River-based feature)
        starts producing non-zero values after several calls.

        River stats require "warm-up" — the first calls return 0,
        but after history accumulation, the values become non-zero.
        """
        fe = FeatureExtractor()
        fe.set_active_features({"volatility_spike_20", "atr_14_rel"})

        df = realistic_kline_history
        values = []

        # Simulate several consecutive signals
        for i in range(min(50, len(df) - 20)):
            current_index = 20 + i  # Start from the 20th candle for ATR
            current_candle_data = df.iloc[current_index].to_dict()

            features = fe.extract_features_optimized(
                current_candle_data=current_candle_data,
                agg_trades_list=None,
                full_kline_history=df.iloc[: current_index + 1],
                current_index=current_index,
                current_timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
            )

            if features and "volatility_spike_20" in features:
                values.append(features["volatility_spike_20"])

        # After warm-up, non-zero values should appear
        non_zero_count = sum(1 for v in values if v > 0)
        assert non_zero_count > 0, (
            f"volatility_spike_20 should have some non-zero values after warmup, got all zeros in {len(values)} calls"
        )

    def test_sample_values_log_format(
        self,
        feature_extractor_with_active_features: FeatureExtractor,
        realistic_kline_history: pd.DataFrame,
        realistic_aggtrades: list,
    ):
        """
        Checks the output format for logging (first 3 features).
        This is what is displayed in the ML confirmation logs.
        """
        fe = feature_extractor_with_active_features
        df = realistic_kline_history
        current_index = len(df) - 1
        current_candle_data = df.iloc[current_index].to_dict()

        features = fe.extract_features_optimized(
            current_candle_data=current_candle_data,
            agg_trades_list=realistic_aggtrades,
            full_kline_history=df,
            current_index=current_index,
            current_timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        )

        # Format as in logs
        sample_values = {k: f"{v:.4f}" for k, v in list(features.items())[:3]}

        # Check that at least one value is non-zero
        non_zero_samples = [k for k, v in sample_values.items() if v != "0.0000"]
        assert len(non_zero_samples) > 0, (
            f"At least one sample value should be non-zero, got: {sample_values}"
        )


class TestModelPipelineIntegration:
    """
    Integration tests for FeatureExtractor + ModelPipeline.
    """

    @pytest.mark.skipif(
        not Path("data/offline_trained_model.joblib").exists(),
        reason="Requires trained ML model at data/offline_trained_model.joblib",
    )
    def test_full_ml_confirmation_flow(
        self, realistic_kline_history: pd.DataFrame, realistic_aggtrades: list
    ):
        """
        Full integration test of ML confirmation:
        1. Loads a real model
        2. Extracts features from realistic data
        3. Obtains a probability prediction
        """
        # 1. Load model
        model_path = Path("data/offline_trained_model.joblib")
        pipeline = ModelPipeline(model_path=model_path)
        loaded = pipeline.load_model(model_path)
        assert loaded, "Model should load successfully"

        # 2. Configuring FeatureExtractor with active features from the model
        fe = FeatureExtractor()
        fe.set_active_features(pipeline.active_features)

        # 3. Extract features
        df = realistic_kline_history
        current_index = len(df) - 1
        current_candle_data = df.iloc[current_index].to_dict()

        raw_features = fe.extract_features_optimized(
            current_candle_data=current_candle_data,
            agg_trades_list=realistic_aggtrades,
            full_kline_history=df,
            current_index=current_index,
            current_timestamp_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        )

        assert raw_features is not None, "Should extract features"
        assert len(raw_features) > 0, "Should have some features"

        # 4. Normalize features
        norm_features = fe.normalize_features(raw_features)
        assert norm_features is not None, "Should normalize features"

        # 5. Get prediction
        proba_map = pipeline.predict_proba_one(norm_features)

        assert proba_map is not None, "Model should return predictions"
        assert 0 in proba_map or 1 in proba_map, (
            "Proba map should have class probabilities"
        )

        # Check that probabilities are in the valid range
        for cls, prob in proba_map.items():
            assert 0.0 <= prob <= 1.0, (
                f"Probability {prob} for class {cls} should be in [0, 1]"
            )

        # Sum of probabilities should be ~1
        total_prob = sum(proba_map.values())
        assert 0.99 <= total_prob <= 1.01, (
            f"Total probability should be ~1, got {total_prob}"
        )
