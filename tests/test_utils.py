# tests/test_utils.py
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock, PropertyMock
from decimal import ROUND_DOWN, ROUND_UP
import math
import logging
import sys

try:
    from bot_module.utils import (
        round_dynamic,
        calculate_atr,
        round_price_by_tick,
        add_relative_volume,
    )

    PANDAS_TA_AVAILABLE = True
except ImportError:
    pytest.skip("Cannot import bot_module.utils or pandas_ta.", allow_module_level=True)
    PANDAS_TA_AVAILABLE = False

# --- Tests for round_dynamic ---


@pytest.mark.parametrize(
    "value, tick_size, expected",
    [
        (123.4567, 0.01, 123.45),
        (123.4567, 0.1, 123.4),
        (123.4567, 1.0, 123.0),
        (123.9, 1.0, 123.0),
        (0.00012345, 0.00001, 0.00012),
        (100.0, 0.01, 100.0),
        (100.0, 0.0, 100.0),
        (100.0, -0.1, 100.0),
        (55.5, 0.5, 55.5),
        (55.6, 0.5, 55.5),  # Rounding down - should work now
        (55.99, 0.5, 55.5),  # Another test for rounding down
        (56.0, 0.5, 56.0),
        (56.1, 0.5, 56.0),
    ],
)
def test_round_dynamic(value, tick_size, expected):
    result = round_dynamic(value, tick_size)
    assert math.isclose(result, expected), (
        f"Failed for {value}, tick={tick_size}. Got {result}, expected {expected}"
    )


# --- NEW TESTS for round_price_by_tick ---
@pytest.mark.parametrize(
    "price, tick_size, rounding_mode, expected",
    [
        (123.456, 0.01, ROUND_DOWN, 123.45),
        (123.456, 0.01, ROUND_UP, 123.46),
        (55.8, 0.5, ROUND_DOWN, 55.5),
        (55.8, 0.5, ROUND_UP, 56.0),
        (99.9, 1.0, ROUND_DOWN, 99.0),
        (99.9, 1.0, ROUND_UP, 100.0),
        (None, 0.01, ROUND_DOWN, None),  # price is None
        (123.45, None, ROUND_DOWN, 123.45),  # tick_size is None
        (123.45, 0, ROUND_DOWN, 123.45),  # tick_size is zero
        (123.45, -0.01, ROUND_DOWN, 123.45),  # tick_size is negative
    ],
)
def test_round_price_by_tick(price, tick_size, rounding_mode, expected):
    """Tests round_price_by_tick with different rounding modes and edge cases."""
    result = round_price_by_tick(price, tick_size, rounding_mode)
    if expected is None:
        assert result is None
    else:
        assert math.isclose(result, expected), (
            f"Failed for {price}, tick={tick_size}, mode={rounding_mode}. Got {result}, expected {expected}"
        )


# --- NEW TESTS for add_relative_volume ---
@pytest.fixture
def kline_for_rel_vol():
    data = {"volume": [10, 20, 30, 40, 50, 60]}
    index = pd.to_datetime(
        pd.date_range(start="2023-01-01", periods=6, freq="1min", tz="UTC")
    )
    return pd.DataFrame(data, index=index)


def test_add_relative_volume_success(kline_for_rel_vol):
    """Test for successful relative volume calculation."""
    df = kline_for_rel_vol.copy()
    period = 4
    # Previous 4 volumes: [20, 30, 40, 50]. Average = 35.
    # Last volume = 60.
    # Expected relative volume = 60 / 35
    expected_rel_vol = 60.0 / 35.0

    result_df = add_relative_volume(df, period=period)
    assert "relative_volume" in result_df.columns
    # Check the last value
    assert math.isclose(result_df["relative_volume"].iloc[-1], expected_rel_vol)
    # Check that the first values (where there is no full period) are equal to 1.0
    assert (result_df["relative_volume"].iloc[: period - 1] == 1.0).all()


def test_round_dynamic_invalid_input():
    """Tests round_dynamic with incorrect input data."""
    assert round_dynamic("abc", 0.01) == "abc"
    assert round_dynamic(123.45, "xyz") == 123.45
    assert round_dynamic(None, 0.01) is None
    assert round_dynamic(123.45, None) == 123.45


def test_add_relative_volume_insufficient_data(kline_for_rel_vol):
    """Test when data is less than the period."""
    df = kline_for_rel_vol.iloc[:3].copy()  # 3 rows
    result_df = add_relative_volume(df, period=5)
    # The column should be added with a default value of 1.0
    assert "relative_volume" in result_df.columns
    assert (result_df["relative_volume"] == 1.0).all()


def test_add_relative_volume_missing_volume_col(kline_for_rel_vol):
    """Test for missing 'volume' column."""
    df = kline_for_rel_vol.drop(columns=["volume"])
    result_df = add_relative_volume(df, period=4)
    # DataFrame should be returned unchanged
    assert "relative_volume" not in result_df.columns
    assert result_df.equals(df)


# --- Tests for calculate_atr ---


@pytest.fixture
def sample_kline_df():
    """DataFrame for ATR test."""
    data = {
        "open": [
            100,
            101,
            102,
            100,
            103,
            104,
            105,
            106,
            107,
            108,
            109,
            110,
            111,
            110,
            112,
        ],
        "high": [
            102,
            103,
            103,
            102,
            104,
            105,
            106,
            108,
            108,
            109,
            110,
            111,
            112,
            112,
            113,
        ],
        "low": [
            99,
            100,
            101,
            99,
            102,
            103,
            104,
            105,
            106,
            107,
            108,
            109,
            110,
            109,
            111,
        ],
        "close": [
            101,
            102,
            100,
            101,
            104,
            105,
            106,
            107,
            108,
            109,
            110,
            111,
            110,
            111,
            112,
        ],
        "volume": [10] * 15,
    }
    index = pd.to_datetime(
        pd.date_range(start="2023-01-01", periods=15, freq="1min", tz="UTC")
    )
    return pd.DataFrame(data, index=index)


@patch("pandas.DataFrame.ta", new_callable=PropertyMock)  # Patch the .ta property
def test_calculate_atr_success(mock_ta_accessor, sample_kline_df):
    """Test for successful ATR calculation with a mock of the .ta accessor."""
    period = 5
    expected_length = len(sample_kline_df)
    mock_values = [np.nan] * (period - 1) + [
        1.5,
        1.6,
        1.7,
        1.8,
        1.9,
        2.0,
        2.1,
        2.2,
        2.3,
        2.4,
        2.5,
    ]
    if len(mock_values) < expected_length:
        mock_values.extend([mock_values[-1]] * (expected_length - len(mock_values)))
    elif len(mock_values) > expected_length:
        mock_values = mock_values[:expected_length]

    mock_atr_series = pd.Series(mock_values, index=sample_kline_df.index)

    # Create a mock object that the .ta accessor will return
    mock_ta_object = MagicMock()
    # Configure the atr method on this mock object
    mock_ta_object.atr.return_value = mock_atr_series
    # Set that the .ta accessor will return our mock object
    mock_ta_accessor.return_value = mock_ta_object

    result = calculate_atr(sample_kline_df, period=period)

    assert isinstance(result, pd.Series)
    assert len(result) == expected_length
    assert not result.isnull().any(), f"NaNs found in result: {result[result.isnull()]}"
    assert math.isclose(result.iloc[-1], mock_values[-1])
    first_valid_mock_value = next(v for v in mock_values if not np.isnan(v))
    assert math.isclose(result.iloc[0], first_valid_mock_value)
    # Check the call to the atr mock method
    mock_ta_object.atr.assert_called_once_with(length=period, mamode="rma")
    # Check that the .ta accessor was accessed
    mock_ta_accessor.assert_called()


def test_calculate_atr_insufficient_data():
    """Test with insufficient data."""
    index = pd.date_range(start="2023-01-01", periods=3, freq="1min", tz="UTC")
    df_short = pd.DataFrame(
        {"high": [1, 2, 3], "low": [0, 1, 2], "close": [1, 2, 2]}, index=index
    )
    result = calculate_atr(df_short, period=5)
    assert result is None


def test_calculate_atr_missing_columns():
    """Test when required columns are missing."""
    index = pd.date_range(start="2023-01-01", periods=3, freq="1min", tz="UTC")
    df_missing = pd.DataFrame(
        {"high": [1, 2, 3], "low": [0, 1, 2]}, index=index
    )  # No 'close'
    result = calculate_atr(df_missing, period=1)
    assert result is None


@pytest.mark.skipif(not PANDAS_TA_AVAILABLE, reason="pandas_ta not installed")
def test_calculate_atr_with_nans(sample_kline_df):
    """Test for NaN handling in source data (uses real pandas_ta)."""
    df_with_nans = sample_kline_df.copy()
    df_with_nans.loc[df_with_nans.index[2], "high"] = np.nan
    df_with_nans.loc[df_with_nans.index[5], "close"] = np.nan

    result = calculate_atr(df_with_nans, period=5)

    assert isinstance(result, pd.Series)
    assert len(result) == len(df_with_nans)
    assert not result.isnull().any()
    assert result.iloc[-1] > 0


def test_calculate_atr_pandas_ta_not_imported(sample_kline_df):
    """Test if pandas_ta import failed."""
    # Modify sys.modules to simulate the absence of pandas_ta
    # Save the original if it exists
    original_pandas_ta = sys.modules.get("pandas_ta")
    sys.modules["pandas_ta"] = None  # Set to None

    try:
        # Catch the error log using patch
        with patch.object(
            logging.getLogger("bot_module.utils"), "error"
        ) as mock_log_error:
            result = calculate_atr(sample_kline_df, period=5)
            assert result is None
            mock_log_error.assert_called_once_with(
                "Library 'pandas_ta' not found. Cannot calculate ATR. Install it: pip install pandas_ta"
            )
    finally:
        # Restore sys.modules
        if original_pandas_ta:
            sys.modules["pandas_ta"] = original_pandas_ta
        else:
            # If it wasn't there, remove our None
            if "pandas_ta" in sys.modules:
                del sys.modules["pandas_ta"]
