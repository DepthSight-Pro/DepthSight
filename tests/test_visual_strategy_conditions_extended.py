# ruff: noqa: F811
import pytest
import pandas as pd
from tests.test_visual_strategy_foundations_and_filters import (
    get_default_pair_info,
    get_default_market_data,
    visual_strategy_instance,  # noqa: F401 — pytest fixture, import IS usage
)

# --- Tests for uncovered blocks ---


def test_price_consolidation_block(visual_strategy_instance):
    """Test: Verifies the 'price_consolidation' block."""
    test_json_config = {
        "entryConditions": {
            "id": "root",
            "type": "AND",
            "children": [
                {
                    "type": "price_consolidation",
                    "params": {"lookback_period": 10, "max_range_atr": 0.8},
                }
            ],
        }
    }
    strat = visual_strategy_instance(test_json_config)
    market_data = get_default_market_data()

    klines_pass = market_data["kline_1m"].copy()
    last_idx = len(klines_pass) - 1

    for i in range(last_idx - 9, last_idx + 1):
        klines_pass.iloc[i, klines_pass.columns.get_loc("open")] = 100.0
        klines_pass.iloc[i, klines_pass.columns.get_loc("high")] = 100.3
        klines_pass.iloc[i, klines_pass.columns.get_loc("low")] = 99.7
        klines_pass.iloc[i, klines_pass.columns.get_loc("close")] = 100.1

    market_data_pass = market_data.copy()
    market_data_pass["kline_1m"] = klines_pass

    # Synchronize pair_info with the last modified candle by index and time
    pair_info_pass = get_default_pair_info(
        last_price=100.1,
        atr_val=1.0,
        current_idx=last_idx,
        dt=klines_pass.index[last_idx].to_pydatetime(),
    )

    signal_pass, _, _ = strat.check_signal_sync(pair_info_pass, market_data_pass, None)
    assert signal_pass is not None, "Signal should be present with a narrow range"

    # Failure test (wide range)
    klines_fail = klines_pass.copy()
    klines_fail.iloc[last_idx, klines_fail.columns.get_loc("close")] = (
        102.0  # Expanding the range above the 0.8 ATR threshold
    )
    market_data_fail = market_data.copy()
    market_data_fail["kline_1m"] = klines_fail

    pair_info_fail = get_default_pair_info(
        last_price=102.0,
        atr_val=1.0,
        current_idx=last_idx,
        dt=klines_fail.index[last_idx].to_pydatetime(),
    )

    signal_fail, _, _ = strat.check_signal_sync(pair_info_fail, market_data_fail, None)
    assert signal_fail is None, "Signal should not be present with a wide range"


@pytest.mark.parametrize(
    "test_id, p_cond, updates, should_pass",
    [
        (
            "close > open",
            {
                "leftOperand": {"source": "candle", "key": "close"},
                "operator": ">",
                "rightOperand": {"source": "candle", "key": "open"},
            },
            {
                "open": 99.0,
                "close": 100.0,
                "relative_volume": 3.0,
                "natr": 2.0,
                "is_volume_spike": True,
            },
            True,
        ),
        (
            "SMA10 < SMA50",
            {
                "leftOperand": {"source": "indicator", "key": "SMA_10"},
                "operator": "<",
                "rightOperand": {"source": "indicator", "key": "SMA_50"},
            },
            {
                "SMA_10": 98.0,
                "SMA_50": 100.0,
                "relative_volume": 3.0,
                "natr": 2.0,
                "is_volume_spike": True,
            },
            True,
        ),
        (
            "high(prev) > close(curr)",
            {
                "leftOperand": {"source": "candle", "key": "high", "shift": 1},
                "operator": ">",
                "rightOperand": {"source": "candle", "key": "close"},
            },
            {
                "close": 101.0,
                "relative_volume": 3.0,
                "natr": 2.0,
                "is_volume_spike": True,
            },
            True,
        ),
    ],
)
def test_price_condition_block(
    visual_strategy_instance, test_id, p_cond, updates, should_pass
):
    """Test: Verifies the flexible 'value_comparison' block."""
    # Add a foundation block to ensure minimum weight
    strat = visual_strategy_instance(
        {
            "entryConditions": {
                "type": "AND",
                "children": [
                    {
                        "type": "market_activity",
                        "params": {
                            "rel_vol_threshold": 1.5,
                            "natr_threshold": 1.5,
                            "mode": "relative",
                        },
                    },
                    {"type": "value_comparison", "params": p_cond},
                ],
            }
        }
    )

    market_data = get_default_market_data()
    pair_info = get_default_pair_info()

    # For tests with indicators, update their values in pair_info
    if test_id == "SMA10 < SMA50":
        # Update indicators so that SMA_10 < SMA_50
        pair_info["SMA_10"] = updates.get("SMA_10", 98.0)
        pair_info["SMA_50"] = updates.get("SMA_50", 100.0)

    # Applying the remaining updates
    pair_info.update(updates)

    # For the test with a shift, we need to change the data in market_data
    if test_id == "high(prev) > close(curr)":
        target_idx = pair_info["current_candle_index"] - 1
        market_data["kline_1m"].iloc[
            target_idx, market_data["kline_1m"].columns.get_loc("high")
        ] = 102.0

    # Update DataFrame at the current index
    current_idx = pair_info["current_candle_index"]
    if "close" in updates:
        market_data["kline_1m"].iloc[
            current_idx, market_data["kline_1m"].columns.get_loc("close")
        ] = updates["close"]
    if "open" in updates:
        market_data["kline_1m"].iloc[
            current_idx, market_data["kline_1m"].columns.get_loc("open")
        ] = updates["open"]

    signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)

    if should_pass:
        assert signal is not None, (
            f"FAIL [{test_id}]: Signal should have been generated"
        )
    else:
        assert signal is None, (
            f"FAIL [{test_id}]: Signal should not have been generated"
        )


def test_return_to_level_block(visual_strategy_instance):
    """Test: Verifies the integration of 'local_level' and 'return_to_level'."""
    test_json_config = {
        "entryConditions": {
            "id": "root",
            "type": "AND",
            "children": [
                {
                    "id": "level_finder",
                    "type": "local_level",
                    "params": {
                        "lookback_period": 5,
                        "proximity_type": "atr_multiplier",
                        "proximity_value": 10.0,
                        "timeframe": "1m",
                    },
                },
                {
                    "id": "level_returner",
                    "type": "return_to_level",
                    "params": {
                        "level_block_id": "level_finder",
                        "retest_type": "touch",
                    },
                },
            ],
        }
    }
    strat = visual_strategy_instance(test_json_config)
    market_data = get_default_market_data()
    # Setting high at index -3
    market_data["kline_1m"].iloc[
        -3, market_data["kline_1m"].columns.get_loc("high")
    ] = 105.0

    pair_info = get_default_pair_info(last_price=105.01, atr_val=0.5)
    # Update the index to match the end of the data (-1)
    pair_info["current_candle_index"] = len(market_data["kline_1m"]) - 1

    signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
    assert signal is not None, (
        "Signal should be present when the price returns to the found level"
    )


def test_return_to_level_breakout_retest_block(visual_strategy_instance):
    """Test: breakout_retest via prev_pair_info should work as return to level."""
    test_json_config = {
        "entryConditions": {
            "id": "root",
            "type": "AND",
            "children": [
                {
                    "id": "level_finder",
                    "type": "local_level",
                    "params": {
                        "lookback_period": 5,
                        "proximity_type": "atr_multiplier",
                        "proximity_value": 10.0,
                        "timeframe": "1m",
                    },
                },
                {
                    "id": "level_returner",
                    "type": "return_to_level",
                    "params": {
                        "level_block_id": "level_finder",
                        "retest_type": "breakout_retest",
                    },
                },
            ],
        }
    }
    strat = visual_strategy_instance(test_json_config)
    market_data = get_default_market_data()
    market_data["kline_1m"].iloc[
        -3, market_data["kline_1m"].columns.get_loc("high")
    ] = 105.0

    # 1. First, simulate the price moving away from the level (breakout)
    prev_pair_info = get_default_pair_info(last_price=108.0, atr_val=0.5)
    prev_pair_info["current_candle_index"] = len(market_data["kline_1m"]) - 2
    strat.check_signal_sync(prev_pair_info, market_data, None)

    # 2. Then check the return to the level (retest)
    pair_info = get_default_pair_info(last_price=105.01, atr_val=0.5)
    pair_info["current_candle_index"] = len(market_data["kline_1m"]) - 1

    signal, _, _ = strat.check_signal_sync(pair_info, market_data, prev_pair_info)
    assert signal is not None, (
        "Signal should be present when the price has returned to the level after moving away"
    )


def test_local_level_ignores_middle_wicks_inside_lookback(visual_strategy_instance):
    test_json_config = {
        "entryConditions": {
            "id": "root",
            "type": "AND",
            "children": [
                {
                    "id": "level_finder",
                    "type": "local_level",
                    "params": {
                        "lookback_period": 5,
                        "proximity_type": "percentage",
                        "proximity_value": 0.5,
                        "timeframe": "1m",
                    },
                }
            ],
        }
    }
    strat = visual_strategy_instance(test_json_config)
    idx = pd.date_range("2024-01-01 00:00", periods=8, freq="1min")
    df = pd.DataFrame(
        {
            "open": [100.0] * 8,
            "high": [100.2, 100.2, 110.0, 100.2, 100.2, 100.2, 100.2, 100.2],
            "low": [99.8, 99.8, 99.8, 90.0, 99.8, 99.8, 99.8, 99.8],
            "close": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.1],
            "volume": [100.0] * 8,
        },
        index=idx,
    )
    pair_info = get_default_pair_info(
        last_price=100.1,
        atr_val=1.0,
        current_idx=len(df) - 1,
        dt=idx[-1].to_pydatetime(),
    )

    signal, _, _ = strat.check_signal_sync(pair_info, {"kline_1m": df}, None)

    assert signal is None


def test_level_touch_uses_current_timestamp_not_dataset_tail(visual_strategy_instance):
    test_json_config = {
        "entryConditions": {
            "id": "root",
            "type": "AND",
            "children": [
                {
                    "id": "touch",
                    "type": "level_touch_analyzer",
                    "params": {
                        "level_price": 200.0,
                        "lookback_candles": 3,
                        "touch_tolerance_pct": 0.1,
                        "min_touches": 1,
                        "timeframe": "1m",
                    },
                }
            ],
        }
    }
    strat = visual_strategy_instance(test_json_config)
    idx = pd.date_range("2024-01-01 00:00", periods=8, freq="1min")
    df = pd.DataFrame(
        {
            "open": [100.0] * 8,
            "high": [101.0, 101.0, 101.0, 101.0, 101.0, 200.1, 200.1, 200.1],
            "low": [99.0, 99.0, 99.0, 99.0, 99.0, 199.9, 199.9, 199.9],
            "close": [100.0] * 8,
            "volume": [100.0] * 8,
        },
        index=idx,
    )
    current_dt = idx[3].tz_localize("UTC").to_pydatetime()
    pair_info = get_default_pair_info(
        last_price=100.0, atr_val=1.0, current_idx=3, dt=current_dt
    )

    signal, _, _ = strat.check_signal_sync(pair_info, {"kline_1m": df}, None)

    assert signal is None


def test_edge_cases_empty_children_and_bad_ref(visual_strategy_instance):
    market_data = get_default_market_data()
    pair_info = get_default_pair_info()

    strat_and = visual_strategy_instance(
        {"entryConditions": {"type": "AND", "children": []}}
    )
    signal_and, _, _ = strat_and.check_signal_sync(pair_info, market_data, None)
    assert signal_and is not None, "Empty AND should generate a signal"

    strat_or = visual_strategy_instance(
        {"entryConditions": {"type": "OR", "children": []}}
    )
    signal_or, _, _ = strat_or.check_signal_sync(pair_info, market_data, None)
    assert signal_or is None, "Empty OR should not generate a signal"

    bad_ref_config = {
        "entryConditions": {
            "id": "root",
            "type": "AND",
            "children": [
                {
                    "type": "price_vs_level",
                    "params": {
                        "level_source": {
                            "source": "block_result",
                            "block_id": "non_existent_id",
                            "key": "detected_level",
                        }
                    },
                }
            ],
        }
    }
    strat_bad_ref = visual_strategy_instance(bad_ref_config)
    signal_bad, _, _ = strat_bad_ref.check_signal_sync(pair_info, market_data, None)
    assert signal_bad is None, (
        "Signal should not be generated when referencing a non-existent block"
    )


@pytest.mark.parametrize(
    "test_id, params, expected_total_volume, expected_level_count",
    [
        (
            "bids_1_percent",
            {
                "side": "bids",
                "range_type": "Percentage",
                "range_value": {"source": "value", "value": 1.5},
            },
            100000.0,
            1,
        ),
        (
            "bids_3_percent",
            {
                "side": "bids",
                "range_type": "Percentage",
                "range_value": {"source": "value", "value": 3.0},
            },
            450000.0,
            3,
        ),
        (
            "asks_2_percent",
            {
                "side": "asks",
                "range_type": "Percentage",
                "range_value": {"source": "value", "value": 2.5},
            },
            350000.0,
            2,
        ),
        (
            "asks_atr_range",
            {
                "side": "asks",
                "range_type": "ATR Multiplier",
                "range_value": {"source": "value", "value": 3.5},
            },
            590000.0,
            3,
        ),
    ],
)
def test_order_book_zone_data_provider(
    visual_strategy_instance,
    test_id,
    params,
    expected_total_volume,
    expected_level_count,
):
    """
    Unit test for the new data provider block `order_book_zone`.
    """
    strat = visual_strategy_instance(
        {"entryConditions": {"type": "AND", "children": []}}
    )

    mock_depth_analysis = {
        "bids": [
            {"percentage": -1, "notional": 100000.0},
            {"percentage": -2, "notional": 150000.0},
            {"percentage": -3, "notional": 200000.0},
        ],
        "asks": [
            {"percentage": 1, "notional": 120000.0},
            {"percentage": 2, "notional": 230000.0},
            {"percentage": 3, "notional": 240000.0},
        ],
    }

    pair_info = get_default_pair_info(last_price=50000.0, atr_val=500.0)
    market_data = {"depth_analysis": mock_depth_analysis}
    context = {"pair_info": pair_info, "market_data": market_data}

    # Correct argument order (pair_info, market_data, params, context)
    is_true, details = strat._check_condition_order_book_zone(
        pair_info, market_data, params, context
    )

    assert is_true is True, "Data provider block should always return True"
    assert "error" not in details, (
        f"There should be no errors in 'details': {details.get('error')}"
    )
    assert "total_volume_usd" in details
