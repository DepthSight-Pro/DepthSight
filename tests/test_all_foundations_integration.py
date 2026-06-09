# File: tests/test_all_foundations_integration.py

import pytest
import pandas as pd
from bot_module.strategy import (
    get_strategy_instance,
    STRATEGIES,
    VolumeBreakoutStrategy,
    FakeBreakoutStrategy,
    ConsolidationImpulseStrategy,
)
from bot_module import config

# --- REGISTRATION FOR TESTS ---
test_strategies_map = {
    "VolumeBreakout": VolumeBreakoutStrategy,
    "FakeBreakout": FakeBreakoutStrategy,
    "ConsolidationImpulse": ConsolidationImpulseStrategy,
}
for name, cls in test_strategies_map.items():
    if name not in STRATEGIES:
        STRATEGIES[name] = cls


# The mock_comprehensive_data fixture remains unchanged, but we'll make a small improvement for aggTrade
@pytest.fixture
def mock_comprehensive_data():
    """Creates a complete dataset to verify all foundations."""
    pair_info = {
        "symbol": "TESTUSDT",
        "last_price": 100.1,
        "atr": 1.0,
        "natr": 2.0,
        "relative_volume": 6.0,
        "tick_size": 0.01,
        "current_candle_index": 59,
        "SMA_10": 100,  # Trend: SMA_10 > SMA_50
        "SMA_50": 99,
        "RSI_14": 60,  # Trend: RSI > 55 (was 55)
    }
    depth_strong = {
        "bids": [["99.0", "1011.0"]],
        "asks": [["102.0", "500.0"]],
    }  # For the 40000 USD threshold, this will work
    now = pd.Timestamp.now(tz="UTC")
    timestamps = pd.to_datetime(
        [now - pd.Timedelta(minutes=i) for i in range(60, 0, -1)]
    )

    # Data for VolumeBreakout, FakeBreakout, and ConsolidationImpulse
    # VolumeBreakout: last_closed_candle['close'] (100.1) > prev_closed_candle['high'] (99.8)
    # FakeBreakout: Need to configure parameters or data
    # ConsolidationImpulse: Need to configure parameters or data
    kline_1m_data = {
        "open": [100.0] * 58 + [100.0, 100.0],  # 58th: open=100, 59th: open=100
        "high": [100.2] * 58
        + [99.8, 100.6],  # 58th: high=99.8 (for VB), 59th: high=100.6
        "low": [99.0] * 60,  # Everywhere low=99.0
        "close": [99.5] * 58
        + [99.5, 100.1],  # 58th: close=99.5, 59th: close=100.1 (trigger for VB)
        "volume": [100] * 58 + [100, 300],  # 59th: volume=300 (for VolumeConfirmation)
    }
    df_1m = pd.DataFrame(kline_1m_data, index=timestamps)

    df_1d_timestamps = pd.to_datetime(
        [now - pd.Timedelta(days=2), now - pd.Timedelta(days=1)]
    )
    df_1d_data = {"high": [105.0, 101.0], "low": [100.0, 95.0]}
    df_1d = pd.DataFrame(df_1d_data, index=df_1d_timestamps)

    market_data = {
        "kline_1m": df_1m.copy(),
        "kline_1h": df_1m.copy()
        .resample("h")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        ),  # was '1H'
        "kline_4h": df_1m.copy()
        .resample("4h")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        ),  # was '4H'
        "kline_1d": df_1d,
        "depth_trading": depth_strong,
        "depth_analysis": None,
        "aggTrade": pd.DataFrame(
            {"price": [100.1], "quantity": [10], "timestamp": [now]}
        ).set_index("timestamp"),  # Fixed
    }
    return pair_info, market_data


# Parameterize the test by strategy names
# Parameterize the test by strategy names
@pytest.mark.parametrize(
    "strategy_name, pattern_parameters_for_mock",
    [
        ("VolumeBreakout", {}),
        ("FakeBreakout", {"lookback_candles": 3, "reversal_confirmation_bars": 0}),
        (
            "ConsolidationImpulse",
            {
                "max_range_atr_multiplier": 1.5,
                "entry_delay_bars": 0,
                "impulse_candle_min_body_atr": 0.05,
            },
        ),
    ],
)
def test_strategy_all_foundations_and_summation(
    mock_comprehensive_data, monkeypatch, strategy_name, pattern_parameters_for_mock
):
    pair_info, market_data = mock_comprehensive_data

    if strategy_name == "FakeBreakout":
        pass

    original_highs = None
    if strategy_name == "ConsolidationImpulse":
        original_highs = market_data["kline_1m"]["high"].copy()
        market_data["kline_1m"].loc[market_data["kline_1m"].index[44:58], "high"] = 99.7

    strategy = get_strategy_instance(strategy_name)
    assert strategy is not None
    strategy.enabled = True

    original_get_param = strategy._get_param

    def mocked_get_param(param_name, default=None):
        if param_name in pattern_parameters_for_mock:
            return pattern_parameters_for_mock[param_name]
        return original_get_param(param_name, default)

    monkeypatch.setattr(strategy, "_get_param", mocked_get_param)

    print(
        f"\n--- Strategy testing: {strategy_name} (Scenario 1: Sufficient weight) ---"
    )

    monkeypatch.setattr(config, "ORDERBOOK_FOUNDATION_MIN_DENSITY_USD", 40000.0)
    monkeypatch.setattr(config, "ORDERBOOK_FOUNDATION_LEVELS_TO_CHECK", 5)
    monkeypatch.setattr(config, "USE_COMPANION_ORDERBOOK_ANALYSIS", False)
    monkeypatch.setattr(config, "ROUND_LEVEL_FOUNDATION_ENABLED", True)
    monkeypatch.setattr(config, "ROUND_LEVEL_USE_ATR_PROXIMITY", False)
    monkeypatch.setattr(config, "ROUND_LEVEL_PROXIMITY_PCT", 0.002)
    monkeypatch.setattr(config, "ROUND_LEVEL_MIN_TICK_PROXIMITY", 2)
    monkeypatch.setattr(config, "ROUND_LEVEL_STEP_DEFINITIONS", [])

    first_pullbacks_defaults = {
        "sma_fast_period": 10,
        "sma_slow_period": 50,
        "rsi_period": 14,
        "rsi_lower_bound": 30,
        "rsi_upper_bound": 70,
        "rsi_long_zone_min": 45,
        "rsi_short_zone_max": 55,
    }
    monkeypatch.setitem(
        config.STRATEGY_DEFAULTS,
        "FirstPullbacksInTrend",
        config.STRATEGY_DEFAULTS.get("FirstPullbacksInTrend", {})
        | first_pullbacks_defaults,
    )

    foundation_weights_all_active = {
        "market_activity": 15.0,
        "level": 15.0,
        "pattern": 10.0,
        "volume_confirmation": 10.0,
        "orderbook": 30.0,
        "trend": 10.0,
        "round_number_level": 10.0,
    }
    monkeypatch.setattr(strategy, "foundation_weights", foundation_weights_all_active)
    monkeypatch.setattr(strategy, "min_total_foundation_weight_threshold", 50.0)

    # Correct tuple unpacking ---
    signal_obj, actual_weight, trace = strategy.check_signal_sync(
        pair_info, market_data
    )

    print(
        f"Result for {strategy_name} (sufficient weight):",
        (signal_obj, actual_weight, trace),
    )
    details = getattr(signal_obj, "details", {})
    foundation_log = details.get("foundation_met_details_log", "No basis log")
    print(f"Signal details for {strategy_name}:", details)
    print(f"Basis log for {strategy_name}: {foundation_log}")

    pattern_detected_in_details = details.get(
        "pattern",
        details.get("founds", {}).get("pattern_detected", "Pattern not specified"),
    )

    # The 'round_number_level' foundation is not met (weight 10), so the expected weight is 100 - 10 = 90
    expected_weight_scenario1 = 90.0

    assert actual_weight == expected_weight_scenario1, (
        f"[{strategy_name}] Expected weight {expected_weight_scenario1}, received {actual_weight}. Basis log: {foundation_log}. Pattern from details: {pattern_detected_in_details}"
    )

    assert signal_obj is not None, (
        f"[{strategy_name}] Signal should not be None when weight {actual_weight} (expected {expected_weight_scenario1}) is sufficient."
    )

    print(
        f"\n--- Strategy testing: {strategy_name} (Scenario 2: Insufficient weight) ---"
    )

    foundation_weights_some_disabled = {
        "market_activity": 15.0,
        "level": 15.0,
        "pattern": 10.0,
        "volume_confirmation": 10.0,
        "orderbook": 30.0,
        "trend": 0.0,
        "round_number_level": 0.0,
    }
    monkeypatch.setattr(
        strategy, "foundation_weights", foundation_weights_some_disabled
    )
    monkeypatch.setattr(strategy, "min_total_foundation_weight_threshold", 95.0)

    # Correct tuple unpacking ---
    signal_rejected, weight_rejected, _ = strategy.check_signal_sync(
        pair_info, market_data
    )

    print(f"Result for {strategy_name} (insufficient weight):", signal_rejected)
    if signal_rejected:
        details_rejected = getattr(signal_rejected, "details", {})
        foundation_log_rejected = details_rejected.get(
            "foundation_met_details_log", "No basis log"
        )
        print(f"Error signal details for {strategy_name}:", details_rejected)
        print(
            f"Foundations log of erroneous signal for {strategy_name}: {foundation_log_rejected}"
        )

    assert signal_rejected is None, (
        f"[{strategy_name}] Signal should be None when weight is insufficient."
    )

    if original_highs is not None:
        market_data["kline_1m"].loc[market_data["kline_1m"].index[44:58], "high"] = (
            original_highs.iloc[44:58]
        )
