# tests/test_genetic_adapter.py

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from bot_module.genetic_adapter import GeneticCompatibleStrategy
from bot_module.strategy import get_strategy_instance, STRATEGIES

# --- Fixtures ---


@pytest.fixture
def genetic_strategy():
    STRATEGIES[GeneticCompatibleStrategy.NAME] = GeneticCompatibleStrategy
    return GeneticCompatibleStrategy()


@pytest.fixture
def sample_market_data():
    """
    Generates 100 candles (enough for MACD/EMA 50+).
    Linear price growth.
    """
    dates = pd.date_range(start="2024-01-01", periods=100, freq="1min")

    # Linear growth from 100 to 200
    close = np.linspace(100, 200, 100)
    high = close + 2
    low = close - 2
    open_ = close - 1

    df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": [1000] * 100,
        },
        index=dates,
    )

    return {"kline_1m": df}


@pytest.fixture
def pair_info():
    return {
        "symbol": "BTCUSDT",
        "candle_timeframe": "1m",
        "timestamp_dt": datetime.now(timezone.utc),
    }


# --- System tests ---


def test_registry_loading():
    """Checks that the strategy is correctly registered."""
    STRATEGIES["GeneticStrategy"] = GeneticCompatibleStrategy
    instance = get_strategy_instance("GeneticStrategy")

    assert isinstance(instance, GeneticCompatibleStrategy)
    assert (
        instance.condition_checkers["natr_filter"]
        == instance._check_filter_natr_dynamic
    )


# --- Indicator logic tests ---


def test_natr_calculation_logic(genetic_strategy, pair_info):
    """Checks 'Scalping NATR'."""
    # 8 flat candles, 2 volatility candles
    data = []
    for _ in range(8):
        data.append([100.0, 100.0, 100.0, 100.0])
    # Penultimate: Range 20 (10%)
    data.append([210.0, 190.0, 200.0, 100])
    # Last: Range 4 (4%)
    data.append([102.0, 98.0, 100.0, 100])

    df = pd.DataFrame(data, columns=["high", "low", "close", "volume"])
    market_data = {"kline_1m": df}

    # Average (10+4)/2 = 7.0. Checking > 6.0
    res_pass, details = genetic_strategy._check_filter_natr_dynamic(
        pair_info, market_data, {"period": 2, "operator": "gt", "value": 6.0}, {}
    )
    assert res_pass is True
    assert details["natr_val"] == 7.0


def test_trend_filter_price_sma(genetic_strategy, sample_market_data, pair_info):
    """Checks Price > SMA."""
    # Price grows linearly, so Close > SMA
    params = {"threshold": 20}  # Period 20
    res, details = genetic_strategy._check_filter_trend_price_sma(
        pair_info, sample_market_data, params, {}
    )

    assert res is True
    assert details["close"] > details["SMA_20"]


def test_trend_direction_priority(genetic_strategy, sample_market_data, pair_info):
    """Checks direction priority from genetics."""
    # Market is growing -> Indicators LONG

    params = {
        "sma_fast_period": 5,
        "sma_slow_period": 20,
        "rsi_period": 14,
        "rsi_lower_bound": 30,
        "rsi_upper_bound": 70,
        "direction": "short",  # Genetics wants SHORT
        "required_trend": "LONG",  # Editor sets LONG
    }

    res, details = genetic_strategy._check_condition_trend_direction_genetic(
        pair_info, sample_market_data, params, {}
    )

    # Expect False, as the market does not match 'direction': 'short'
    assert res is False
    assert details["target"] == "SHORT"


@pytest.mark.parametrize(
    "test_id, hour_utc, params, expected",
    [
        # --- Include mode (trade ONLY at the specified time) ---
        (
            "include_all_day_pass",
            14,
            {"start_hour_utc": 0, "end_hour_utc": 23, "mode": "include"},
            True,
        ),
        (
            "include_morning_pass",
            8,
            {"start_hour_utc": 6, "end_hour_utc": 12, "mode": "include"},
            True,
        ),
        (
            "include_morning_fail",
            14,
            {"start_hour_utc": 6, "end_hour_utc": 12, "mode": "include"},
            False,
        ),
        (
            "include_start_boundary_pass",
            9,
            {"start_hour_utc": 9, "end_hour_utc": 17, "mode": "include"},
            True,
        ),
        (
            "include_end_boundary_fail",
            17,
            {"start_hour_utc": 9, "end_hour_utc": 17, "mode": "include"},
            False,
        ),  # < end, not <=
        # --- Exclude mode (trade OUTSIDE the specified time) ---
        (
            "exclude_night_pass",
            14,
            {"start_hour_utc": 0, "end_hour_utc": 6, "mode": "exclude"},
            True,
        ),  # 14:00 outside 0-6
        (
            "exclude_night_fail",
            3,
            {"start_hour_utc": 0, "end_hour_utc": 6, "mode": "exclude"},
            False,
        ),  # 3:00 inside 0-6
        # --- Midnight crossing (start > end) ---
        (
            "midnight_cross_pass_night",
            23,
            {"start_hour_utc": 22, "end_hour_utc": 6, "mode": "include"},
            True,
        ),  # 23:00 within 22:00-6:00
        (
            "midnight_cross_pass_early",
            3,
            {"start_hour_utc": 22, "end_hour_utc": 6, "mode": "include"},
            True,
        ),  # 3:00 in 22:00-6:00
        (
            "midnight_cross_fail_day",
            12,
            {"start_hour_utc": 22, "end_hour_utc": 6, "mode": "include"},
            False,
        ),  # 12:00 outside 22:00-6:00
        # --- American session as a time_filter ---
        (
            "us_session_via_time_pass",
            15,
            {"start_hour_utc": 12, "end_hour_utc": 21, "mode": "include"},
            True,
        ),
        (
            "us_session_via_time_fail",
            10,
            {"start_hour_utc": 12, "end_hour_utc": 21, "mode": "include"},
            False,
        ),
    ],
)
def test_time_filter(genetic_strategy, pair_info, test_id, hour_utc, params, expected):
    """Checks flexible time_filter with various parameters."""
    pair_info["timestamp_dt"] = datetime(
        2023, 10, 10, hour_utc, 30, tzinfo=timezone.utc
    )
    res, details = genetic_strategy._check_filter_time_genetic(
        pair_info, {}, params, {}
    )
    assert res == expected, (
        f"FAIL [{test_id}]: Expected {expected}, got {res}. Details: {details}"
    )


def test_ma_cross_condition(genetic_strategy, pair_info):
    """Checks for a crossover (Golden Cross) at the last step."""
    # EMA_2 vs EMA_5.
    # Step 1: Flat at 100. EMA_2=100, EMA_5=100.
    # Step 2: Sharp jump to 150.
    # EMA_2 will react faster and become > EMA_5.

    data = [100.0] * 20 + [150.0]
    df = pd.DataFrame({"close": data, "volume": [1] * 21})
    market_data = {"kline_1m": df}

    params = {"fast_period": 2, "slow_period": 5}
    res, details = genetic_strategy._check_condition_ma_cross(
        pair_info, market_data, params, {}
    )

    assert res is True
    assert details["fast"] > details["slow"]  # Fast is higher now
    # Check that at the previous step they were equal or Fast was lower (due to flat 100)
    # EMA(100) = 100. So the condition F_prev <= S_prev will be met (100 <= 100).


def test_bb_condition(genetic_strategy, sample_market_data, pair_info):
    """Checks Bollinger Bands."""
    # Price is inside the channel or above Upper (due to growth)
    params = {
        "period": 20,
        "std_dev": 2.0,
        "check_type": "width_gt",
        "width_value": 0.0,
    }

    res, details = genetic_strategy._check_condition_bb(
        pair_info, sample_market_data, params, {}
    )

    assert res is True  # Channel width is definitely greater than 0
    assert isinstance(details["width"], float)


def test_macd_extended(genetic_strategy, sample_market_data, pair_info):
    """Checks MACD with sufficient data (100 candles)."""
    # Uptrend -> MACD > 0
    params = {
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9,
        "condition_type": "value_above",
        "value": -9999.0,
    }

    res, details = genetic_strategy._check_condition_macd_extended(
        pair_info, sample_market_data, params, {}
    )

    assert res is True
    assert "macd" in details
    assert not np.isnan(details["macd"])


def test_adx_filter(genetic_strategy, sample_market_data, pair_info):
    """Checks ADX."""
    # We have an ideal linear trend, ADX should be high (close to 100)
    params = {"period": 14, "threshold": 10, "operator": "gt"}

    res, details = genetic_strategy._check_filter_adx_genetic(
        pair_info, sample_market_data, params, {}
    )

    assert res is True
    assert details["adx"] > 10


def test_stoch_condition(genetic_strategy, pair_info):
    """Checks Stochastic."""
    # Data: 50 candles at 100, then growth to 110.
    # Close = High -> Stochastic K should be 100 (or close to it)
    data = [100.0] * 50 + [110.0] * 5
    df = pd.DataFrame(
        {
            "high": data,  # High = Close
            "low": [x - 5 for x in data],
            "close": data,
            "volume": [1] * len(data),
        }
    )
    market_data = {"kline_1m": df}

    # Checking K > 80
    params = {
        "k_period": 5,
        "d_period": 3,
        "smooth_k": 3,
        "operator": "gt",
        "value": 80,
        "line": "k",
    }

    res, details = genetic_strategy._check_condition_stoch(
        pair_info, market_data, params, {}
    )

    assert res is True
    assert details["k"] > 80
