# tests/test_feature_extractor.py
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import sys
import logging
import time  # Adding for sample_agg_trades
from unittest.mock import patch


# Setting up logger for tests
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


try:
    from bot_module.feature_extractor import FeatureExtractor

    # ALL_POSSIBLE_FEATURES will be available via the fe instance or imported if needed globally
    from bot_module.config import (
        ALL_POSSIBLE_FEATURES as CONFIG_ALL_POSSIBLE_FEATURES,
    )  # Use for explicit indication
except ImportError:
    sys.path.insert(0, "..")  # Let's try to go up one level
    try:
        from bot_module.feature_extractor import FeatureExtractor
        from bot_module.config import (
            ALL_POSSIBLE_FEATURES as CONFIG_ALL_POSSIBLE_FEATURES,
        )
    except ImportError:
        pytest.skip(
            "Cannot import FeatureExtractor or ALL_POSSIBLE_FEATURES from bot_module.",
            allow_module_level=True,
        )


# --- Fixtures ---
@pytest.fixture
def sample_kline_data():
    """Creates a DataFrame with test Klines (more data) and pre-calculated fields."""
    num_candles = 50
    np.random.seed(42)  # For reproducibility
    data = {
        "open": np.linspace(100, 110, num_candles)
        + np.random.normal(0, 0.5, num_candles),
        "high": np.linspace(101, 112, num_candles)
        + np.random.normal(0, 0.5, num_candles),
        "low": np.linspace(99, 108, num_candles)
        + np.random.normal(0, 0.5, num_candles),
        "close": np.linspace(101, 111, num_candles)
        + np.random.normal(0, 0.5, num_candles),
        "volume": np.random.poisson(20, num_candles) + 10.0,
    }
    data["high"] = np.maximum(data["high"], np.maximum(data["open"], data["close"]))
    data["low"] = np.minimum(data["low"], np.minimum(data["open"], data["close"]))
    start_time = datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    index = pd.to_datetime(
        [start_time + timedelta(minutes=i) for i in range(num_candles)]
    )
    df = pd.DataFrame(data, index=index)
    df["number_of_trades"] = np.random.randint(5, 20, num_candles)

    # Adding pre-calculated fields
    df["atr"] = (
        (df["high"] - df["low"]).rolling(window=14, min_periods=1).mean()
    )  # Approximate ATR
    df.loc[df["close"] <= 1e-9, "close"] = (
        1.0  # Protection against division by zero for NATR
    )
    df["natr"] = (df["atr"] / df["close"]) * 100
    df["ema_20"] = df["close"].ewm(span=20, adjust=False).mean()
    # RSI requires pandas_ta or a custom implementation, currently just a mock
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)  # +1e-9 to avoid division by zero
    df["rsi_14"] = 100 - (100 / (1 + rs))
    df["rsi_14"] = df["rsi_14"].fillna(50.0)  # Fill NaN values (e.g., at the beginning)

    df["candle_range"] = df["high"] - df["low"]
    df["rolling_max_range_20"] = (
        df["candle_range"].rolling(window=20, min_periods=1).max()
    )
    df["rolling_high_20"] = df["high"].rolling(window=20, min_periods=1).max()
    df["rolling_low_20"] = df["low"].rolling(window=20, min_periods=1).min()
    mean_vol_20 = df["volume"].rolling(window=20, min_periods=1).mean()
    df["relative_volume"] = df["volume"] / (
        mean_vol_20 + 1e-9
    )  # +1e-9 to avoid division by zero

    df["time_since_last_signal_sec"] = np.random.randint(60, 86400, num_candles).astype(
        float
    )

    numeric_cols = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "number_of_trades",
        "atr",
        "natr",
        "ema_20",
        "rsi_14",
        "candle_range",
        "rolling_max_range_20",
        "rolling_high_20",
        "rolling_low_20",
        "relative_volume",
        "time_since_last_signal_sec",
    ]
    for col in numeric_cols:
        if (
            col not in df.columns
        ):  # if some column was not created (e.g., rsi_14 due to pandas_ta)
            df[col] = 0.0
    df[numeric_cols] = (
        df[numeric_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    )  # Fill possible NaNs with zeros

    # Ensure there are no NaNs after all operations
    df.fillna(0.0, inplace=True)
    return df


@pytest.fixture
def sample_agg_trades():
    """Creates a list with test AggTrades with GUARANTEED activity at the end."""
    trades = []
    num_trades_total = 400
    base_time_ms = int(time.time() * 1000)
    start_time_ms = base_time_ms - 60 * 1000
    current_ts_ms = start_time_ms
    np.random.seed(43)
    last_price = 105.0
    buy_pressure = 0.6

    num_regular_trades = num_trades_total - 20
    for i in range(num_regular_trades):
        time_delta_ms = np.random.randint(50, 250)
        current_ts_ms += time_delta_ms
        price_change = np.random.normal(0, 0.1)
        current_price = max(100.0, last_price + price_change)
        quantity = np.random.exponential(scale=0.4) + 0.01
        current_buy_pressure = max(0.1, min(0.9, buy_pressure))
        is_buy_trade = np.random.rand() < current_buy_pressure
        is_buyer_maker = not is_buy_trade
        trades.append(
            {
                "T": current_ts_ms,
                "p": f"{current_price:.2f}",
                "q": f"{quantity:.6f}",
                "m": is_buyer_maker,
                "a": i + 1000,
                "f": i,
                "l": i,
            }
        )
        last_price = current_price
        if i % 75 == 0:
            buy_pressure = np.random.uniform(0.3, 0.7)

    target_end_time_ms = base_time_ms - 2 * 1000
    target_start_time_ms = target_end_time_ms - 8 * 1000
    current_ts_ms = max(current_ts_ms + 50, target_start_time_ms)
    # print(f"\nDEBUG [Fixture]: Generating last 20 trades between {target_start_time_ms} and {target_end_time_ms}. Starting at {current_ts_ms}")

    final_trades_generated = 0
    force_buy = True
    while current_ts_ms < target_end_time_ms and final_trades_generated < 20:
        time_delta_ms = np.random.randint(50, 150)
        current_ts_ms += time_delta_ms
        if current_ts_ms >= target_end_time_ms:
            break

        price_change = np.random.normal(0, 0.05)
        current_price = max(100.0, last_price + price_change)
        quantity = np.random.exponential(scale=0.8) + 0.05
        is_buy_trade = force_buy if final_trades_generated % 4 != 0 else not force_buy
        is_buyer_maker = not is_buy_trade
        trades.append(
            {
                "T": current_ts_ms,
                "p": f"{current_price:.2f}",
                "q": f"{quantity:.6f}",
                "m": is_buyer_maker,
                "a": num_regular_trades + final_trades_generated + 1000,
                "f": num_regular_trades + final_trades_generated,
                "l": num_regular_trades + final_trades_generated,
            }
        )
        last_price = current_price
        final_trades_generated += 1
    # print(f"DEBUG [Fixture]: Generated {final_trades_generated} trades in the final window.")
    return trades


# --- Tests ---


def test_feature_extractor_initialization():
    """Tests FeatureExtractor stats initialization."""
    fe = FeatureExtractor()
    assert fe is not None

    # Checking KLINE stats (only those using River Rolling objects)
    # Names must match those in ALL_POSSIBLE_FEATURES and for which stats are created
    expected_kline_stats = {
        "vol_zscore_20": "vol_zscore",
        "volume_spike_ratio_20": "rel_volume_spike",  # 'rel_volume_spike_20' is excluded from stats initialization
        "price_std_5": "price_std",
        "volatility_spike_20": "volatility_spike",
    }
    for name, type_val in expected_kline_stats.items():
        if (
            name in fe.active_feature_names
            and name in fe.kline_feature_configs
            and name in fe._kline_stats
        ):  # Additional check for activity and config
            assert name in fe._kline_stats, (
                f"Kline stat '{name}' not found in _kline_stats"
            )
            assert fe._kline_stats[name]["type"] == type_val, (
                f"Kline stat '{name}' has wrong type"
            )
        elif (
            name == "volume_spike_ratio_20"
            and "rel_volume_spike_20" in fe.active_feature_names
        ):
            # 'rel_volume_spike_20' does not create a stat, 'volume_spike_ratio_20' might
            pass  # Expected if 'rel_volume_spike_20' is active and 'volume_spike_ratio_20' is not, or vice versa
        # else:
        # print(f"Warning: Kline stat '{name}' for test_feature_extractor_initialization is not active, configured or initialized.")

    # Checking AGGTRADE stats (only those using River Rolling objects)
    expected_aggtrade_stats = {
        "avg_trade_size_norm_50": "avg_trade_size_norm",
        "avg_trade_size_norm_100": "avg_trade_size_norm",
        "liquidity_shift_score_50": "liquidity_shift_score",
    }
    for name, type_val in expected_aggtrade_stats.items():
        if (
            name in fe.active_feature_names
            and name in fe.aggtrade_feature_configs
            and name in fe._aggtrade_stats
        ):  # Additional check
            assert name in fe._aggtrade_stats, (
                f"Aggtrade stat '{name}' not found in _aggtrade_stats"
            )
            assert fe._aggtrade_stats[name]["type"] == type_val, (
                f"Aggtrade stat '{name}' has wrong type"
            )
        # else:
        # print(f"Warning: Aggtrade stat '{name}' for test_feature_extractor_initialization is not active, configured or initialized.")


def test_extract_kline_features_only(sample_kline_data):
    """Tests extraction of only kline-features."""
    fe = FeatureExtractor()

    # Define kline-features based on FeatureExtractor configurations
    # These are features for which there is an entry in fe.kline_feature_configs
    defined_kline_feature_names = {
        name
        for name in CONFIG_ALL_POSSIBLE_FEATURES
        if name in fe.kline_feature_configs
    }
    fe.set_active_features(defined_kline_feature_names)

    # Use the last full dataset for calculation
    current_candle_data = sample_kline_data.iloc[-1].to_dict()
    current_index = len(sample_kline_data) - 1
    current_timestamp_ms = int(sample_kline_data.index[-1].value / 1_000_000)

    features = fe.extract_features_optimized(
        current_candle_data=current_candle_data,
        agg_trades_list=None,
        full_kline_history=sample_kline_data,
        current_index=current_index,
        current_timestamp_ms=current_timestamp_ms,
    )

    assert isinstance(features, dict)
    print(f"\nKline Features Only ({len(features)}): {features}")
    assert set(features.keys()) == defined_kline_feature_names, (
        f"Returned keys {set(features.keys())} do not match active kline features {defined_kline_feature_names}"
    )

    for key in defined_kline_feature_names:
        assert key in features, f"Expected kline key '{key}' not found"
        value = features[key]
        assert isinstance(value, (int, float)), (
            f"Feature '{key}' not numeric: {value} ({type(value)})"
        )
        assert not np.isnan(value), f"Feature '{key}' is NaN"
        assert np.isfinite(value), f"Feature '{key}' is not finite: {value}"

        # Specific checks (can be extended)
        if key == "rsi_14":
            assert -0.001 <= value <= 1.001, (
                f"RSI {value} out of [0, 1]"
            )  # Tolerance for float
        if key == "body_pct":
            assert -0.001 <= value <= 100.001, f"Body % {value} out of [0, 100]"
        if key == "wick_pct":
            assert -0.001 <= value <= 100.001, f"Wick % {value} out of [0, 100]"

    # Ensure that kline-features have some values (not all zeros, except possibly SQS)
    non_sqs_kline_features = {
        k: v for k, v in features.items() if k != "signal_quality_score"
    }
    if len(non_sqs_kline_features) > 0:  # If there are kline features besides SQS
        assert any(abs(v) > 1e-9 for v in non_sqs_kline_features.values()), (
            "All non-SQS kline features are zero, check data or calculation. Features: "
            + str(non_sqs_kline_features)
        )


def test_extract_with_aggtrades(sample_kline_data, sample_agg_trades):
    """Tests extraction with klines and aggtrades."""
    fe = (
        FeatureExtractor()
    )  # By default, all features from ALL_POSSIBLE_FEATURES are active

    current_candle_data = sample_kline_data.iloc[-1].to_dict()
    current_index = len(sample_kline_data) - 1
    current_timestamp_ms = int(sample_kline_data.index[-1].value / 1_000_000)
    if (
        sample_agg_trades
    ):  # If there are trades, take the time of the last trade + a bit
        current_timestamp_ms = max(
            current_timestamp_ms, sample_agg_trades[-1]["T"] + 1000
        )

    features = fe.extract_features_optimized(
        current_candle_data=current_candle_data,
        agg_trades_list=sample_agg_trades,
        full_kline_history=sample_kline_data,
        current_index=current_index,
        current_timestamp_ms=current_timestamp_ms,
    )

    assert isinstance(features, dict)
    print(f"\nKline & AggTrade Features ({len(features)}): {features}")
    assert set(features.keys()) == fe.active_feature_names, (
        f"Returned keys {set(features.keys())} do not match active features {fe.active_feature_names}"
    )

    for key, value in features.items():
        assert isinstance(value, (int, float)), (
            f"Feature '{key}' not numeric: {value} ({type(value)})"
        )
        assert not np.isnan(value), f"Feature '{key}' is NaN"
        assert np.isfinite(value), f"Feature '{key}' is not finite: {value}"

    # Check that some aggtrade features are non-zero if there were trades
    defined_aggtrade_feature_names = {
        name
        for name in CONFIG_ALL_POSSIBLE_FEATURES
        if name in fe.aggtrade_feature_configs
    }
    if sample_agg_trades and defined_aggtrade_feature_names:
        non_zero_agg_features = {
            k: v
            for k, v in features.items()
            if k in defined_aggtrade_feature_names and abs(v) > 1e-9
        }
        assert len(non_zero_agg_features) > 0, (
            f"Expected some non-zero aggtrade features. Got: {non_zero_agg_features}. All agg features: {{k:features[k] for k in defined_aggtrade_feature_names}}"
        )


def test_normalize_features(sample_kline_data):
    """Tests feature normalization."""
    fe = FeatureExtractor()  # All features are active by default
    features_list = []
    normalized_list = []

    # Scaler warmup on several points
    warmup_period = min(10, len(sample_kline_data) - 1)
    if warmup_period <= 1:
        pytest.skip("Not enough data for scaler warmup")

    for i in range(1, len(sample_kline_data)):
        hist_slice = sample_kline_data.iloc[: i + 1]
        current_candle_data = hist_slice.iloc[-1].to_dict()
        current_idx = len(hist_slice) - 1
        current_ts_ms = int(hist_slice.index[-1].value / 1_000_000)

        raw_features = fe.extract_features_optimized(
            current_candle_data, None, hist_slice, current_idx, current_ts_ms
        )

        if raw_features and fe.scaler is not None:
            features_list.append(raw_features)
            # learn_one and transform_one modify the scaler state, use them directly
            fe.scaler.learn_one(raw_features)
            normalized_features = fe.scaler.transform_one(raw_features)

            if not normalized_features and raw_features:
                pytest.fail(f"Normalization returned empty dict at step {i}")
            if i >= warmup_period:  # Collecting after warmup
                normalized_list.append(normalized_features)
        elif fe.scaler is None:
            pytest.fail("Scaler is None, cannot test normalization.")

    assert len(normalized_list) > 0, "No normalization results after warmup"
    last_raw = features_list[-1]
    last_normalized = normalized_list[-1]

    print(f"\nLast Raw Features ({len(last_raw)}): {last_raw}")
    print(f"Last Normalized Features ({len(last_normalized)}): {last_normalized}")

    assert isinstance(last_normalized, dict)
    assert set(last_normalized.keys()) == fe.active_feature_names, (
        f"Normalized keys {set(last_normalized.keys())} do not match active features {fe.active_feature_names}"
    )

    for key, value in last_normalized.items():
        assert isinstance(value, float), (
            f"Normalized feature '{key}' not float: {value}"
        )
        assert not np.isnan(value), f"Normalized feature '{key}' is NaN"
        assert np.isfinite(value), f"Normalized feature '{key}' not finite: {value}"

    # Ensure that values have changed (if raw are not all zeros)
    if any(abs(val) > 1e-9 for val in last_raw.values()):
        changed_count = sum(
            abs(last_raw[k] - last_normalized[k]) > 1e-9
            for k in fe.active_feature_names
            if k in last_raw and k in last_normalized
        )
        assert changed_count > 0, (
            "Normalization didn't change values for non-zero raw features."
        )
    else:
        print(
            "Warning: Last raw features were all zero, normalization effect might be limited."
        )


def test_empty_input_data(sample_kline_data):  # sample_kline_data for kline_ok
    """Tests behavior with empty or incorrect input data."""
    fe = FeatureExtractor()

    # Calculation of expected SQS for zero features
    _dummy_zero_features = {key: 0.0 for key in fe.active_feature_names}
    expected_sqs_for_zeros = fe._calculate_signal_quality_score(_dummy_zero_features)
    print(f"DEBUG: Expected SQS for zero features: {expected_sqs_for_zeros}")

    expected_features_for_bad_kline = {key: 0.0 for key in fe.active_feature_names}
    expected_features_for_bad_kline["signal_quality_score"] = expected_sqs_for_zeros

    # 1. Empty Kline DataFrame
    # extract_features_optimized expects current_candle_data, full_kline_history, current_index
    # The old extract_features returned zeros. The new one should also handle this.
    # If kline_history is empty, current_candle_data will be a problem.
    # _calculate_kline_features will return zeros (and SQS) if current_candle_data is invalid.

    # Calling extract_features_optimized with intentionally bad data
    bad_kline_history = pd.DataFrame()
    bad_current_candle_data = {
        "open": np.nan,
        "high": np.nan,
        "low": np.nan,
        "close": np.nan,
        "volume": np.nan,
        "atr": np.nan,
        "natr": np.nan,
    }

    current_ts_ms = int(time.time() * 1000)
    features_empty_kline = fe.extract_features_optimized(
        current_candle_data=bad_current_candle_data,
        agg_trades_list=None,
        full_kline_history=bad_kline_history,
        current_index=0,  # or -1
        current_timestamp_ms=current_ts_ms,
    )
    assert features_empty_kline == expected_features_for_bad_kline, (
        f"Features for empty kline data mismatch. Got: {features_empty_kline}, Expected: {expected_features_for_bad_kline}"
    )

    # 2. Kline with NaN in the current candle
    nan_kline_df = pd.DataFrame(
        {
            "open": [100, 101, np.nan],
            "high": [102, 103, np.nan],
            "low": [99, 100, np.nan],
            "close": [101, 102, np.nan],
            "volume": [10, 12, np.nan],
            "number_of_trades": [5, 6, np.nan],
            "atr": [0.1, 0.1, np.nan],
            "natr": [0.1, 0.1, np.nan],  # Mandatory fields
            # Add the remaining fields expected by sample_kline_data, with NaN for the last row
            "ema_20": [101, 101.5, np.nan],
            "rsi_14": [50, 55, np.nan],
            "candle_range": [3, 3, np.nan],
            "rolling_max_range_20": [3, 3, np.nan],
            "rolling_high_20": [102, 103, np.nan],
            "rolling_low_20": [99, 100, np.nan],
            "relative_volume": [1, 1, np.nan],
            "time_since_last_signal_sec": [100, 120, np.nan],
        },
        index=pd.to_datetime(
            ["2023-01-01 00:00", "2023-01-01 00:01", "2023-01-01 00:02"], utc=True
        ),
    )

    nan_current_candle_data = nan_kline_df.iloc[-1].to_dict()
    features_nan_kline = fe.extract_features_optimized(
        current_candle_data=nan_current_candle_data,
        agg_trades_list=None,
        full_kline_history=nan_kline_df,
        current_index=len(nan_kline_df) - 1,
        current_timestamp_ms=current_ts_ms,
    )
    assert features_nan_kline == expected_features_for_bad_kline, (
        f"Features for NaN kline data mismatch. Got: {features_nan_kline}, Expected: {expected_features_for_bad_kline}"
    )

    # 3. Correct Kline, no AggTrades
    kline_ok_df = sample_kline_data  # Using full fixture
    ok_current_candle_data = kline_ok_df.iloc[-1].to_dict()
    ok_current_index = len(kline_ok_df) - 1
    ok_current_ts_ms = int(kline_ok_df.index[-1].value / 1_000_000)

    features_no_trades = fe.extract_features_optimized(
        current_candle_data=ok_current_candle_data,
        agg_trades_list=None,
        full_kline_history=kline_ok_df,
        current_index=ok_current_index,
        current_timestamp_ms=ok_current_ts_ms,
    )
    print(
        f"\nFeatures with None agg trades ({len(features_no_trades)}): {features_no_trades}"
    )

    kline_feature_names_in_fe = {
        name for name in fe.active_feature_names if name in fe.kline_feature_configs
    }
    aggtrade_feature_names_in_fe = {
        name for name in fe.active_feature_names if name in fe.aggtrade_feature_configs
    }

    if kline_feature_names_in_fe:
        # Exclude SQS from this check, as it may be 0 or not depending on other (zero) features
        non_sqs_kline_values = [
            v
            for k, v in features_no_trades.items()
            if k in kline_feature_names_in_fe and k != "signal_quality_score"
        ]
        if non_sqs_kline_values:  # if there are kline features besides SQS
            assert any(abs(v) > 1e-9 for v in non_sqs_kline_values), (
                f"Expected some non-SQS kline features to be non-zero. Got: {non_sqs_kline_values}"
            )

    for key in aggtrade_feature_names_in_fe:
        assert key in features_no_trades, f"Aggtrade feature {key} missing"
        assert features_no_trades[key] == 0.0, (
            f"AggTrade feature '{key}' ({features_no_trades[key]}) != 0.0 for no trades"
        )

    # 4. Correct Kline, empty AggTrades list
    features_empty_trades_list = fe.extract_features_optimized(
        current_candle_data=ok_current_candle_data,
        agg_trades_list=[],
        full_kline_history=kline_ok_df,
        current_index=ok_current_index,
        current_timestamp_ms=ok_current_ts_ms,
    )
    print(
        f"\nFeatures with empty list agg trades ({len(features_empty_trades_list)}): {features_empty_trades_list}"
    )
    if kline_feature_names_in_fe:
        non_sqs_kline_values_empty_agg = [
            v
            for k, v in features_empty_trades_list.items()
            if k in kline_feature_names_in_fe and k != "signal_quality_score"
        ]
        if non_sqs_kline_values_empty_agg:
            assert any(abs(v) > 1e-9 for v in non_sqs_kline_values_empty_agg), (
                f"Expected some non-SQS kline features to be non-zero with empty agg_list. Got: {non_sqs_kline_values_empty_agg}"
            )

    for key in aggtrade_feature_names_in_fe:
        assert key in features_empty_trades_list, f"Aggtrade feature {key} missing"
        assert features_empty_trades_list[key] == 0.0, (
            f"AggTrade feature '{key}' ({features_empty_trades_list[key]}) != 0.0 for empty agg_list"
        )


@patch("time.time")
def test_agg_trade_time_window_features(
    mock_time_fixture, sample_agg_trades, sample_kline_data
):
    """Tests feature calculation over a time window with improved data."""
    fe = FeatureExtractor()
    if not sample_agg_trades:
        pytest.skip("No sample trades generated")

    last_trade_ts = max(t["T"] for t in sample_agg_trades)
    mock_current_time_sec = (last_trade_ts / 1000) + 1.0  # 1 second later
    mock_time_fixture.return_value = mock_current_time_sec
    current_calc_timestamp_ms = int(mock_current_time_sec * 1000)

    # Use data from sample_kline_data for dummy_kline
    # Ensure that dummy_kline time precedes current_calc_timestamp_ms
    kline_ts_for_test = pd.to_datetime(
        current_calc_timestamp_ms - 60000, unit="ms", utc=True
    )

    # full_kline_history must be a DataFrame with a DateTimeIndex
    dummy_kline_history = sample_kline_data.copy()
    # Set the index of the last row in kline_ts_for_test so that current_candle_data is up to date
    # This is a bit artificial, but the goal is to provide valid kline data for _calculate_kline_features
    dummy_kline_history.index = pd.to_datetime(
        np.linspace(
            (kline_ts_for_test - timedelta(minutes=len(dummy_kline_history) - 1)).value,
            kline_ts_for_test.value,
            len(dummy_kline_history),
        ),
        unit="ns",
        utc=True,
    )
    dummy_kline_current_dict = dummy_kline_history.iloc[-1].to_dict()

    print(
        f"\nDEBUG [test_agg_trade]: Last Trade TS: {last_trade_ts} ({datetime.fromtimestamp(last_trade_ts / 1000, timezone.utc)})"
    )
    print(
        f"DEBUG [test_agg_trade]: Using Calculation Timestamp: {current_calc_timestamp_ms} ({datetime.fromtimestamp(current_calc_timestamp_ms / 1000, timezone.utc)})"
    )
    print(
        f"DEBUG [test_agg_trade]: Dummy kline last entry timestamp: {dummy_kline_history.index[-1]}"
    )

    print(
        f"DEBUG [test_agg_trade]: Calling extract_features_optimized with {len(sample_agg_trades)} trades..."
    )
    features = fe.extract_features_optimized(
        current_candle_data=dummy_kline_current_dict,
        agg_trades_list=sample_agg_trades,
        full_kline_history=dummy_kline_history,
        current_index=len(dummy_kline_history) - 1,
        current_timestamp_ms=current_calc_timestamp_ms,
    )

    print(f"AggTrade Features after processing trades: {features}")

    defined_aggtrade_feature_names = {
        name
        for name in CONFIG_ALL_POSSIBLE_FEATURES
        if name in fe.aggtrade_feature_configs
    }

    for key in defined_aggtrade_feature_names:
        if key in fe.active_feature_names:  # Check only active features
            assert key in features, f"AggTrade key '{key}' missing"
            assert isinstance(features[key], float), (
                f"AggTrade feature '{key}' is not float: {features[key]} ({type(features[key])})"
            )
            assert not np.isnan(features[key]), f"AggTrade feature '{key}' is NaN"
            assert np.isfinite(features[key]), (
                f"AggTrade feature '{key}' is not finite: {features[key]}"
            )

    assert features["agg_trade_spike_10s"] >= 0.0  # Basic check

    non_zero_features = {
        k: v
        for k, v in features.items()
        if k in defined_aggtrade_feature_names
        and k in fe.active_feature_names
        and abs(v) > 1e-9
    }
    print(f"Non-zero AggTrade features: {non_zero_features}")
    assert len(non_zero_features) > 0, (
        "All active AggTrade features are zero. Check calculation logic or data. Non-zero: "
        + str(non_zero_features)
    )
