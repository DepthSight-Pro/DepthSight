# File: tests/test_visual_strategy_integration.py
# ruff: noqa: F811

import pytest
import pandas as pd
import numpy as np
from bot_module.strategy import StrategySignal
from tests.test_visual_strategy_foundations_and_filters import (
    get_default_market_data,
    visual_strategy_instance,  # noqa: F401 — pytest fixture, import IS usage
)


@pytest.fixture
def get_default_pair_info():
    """
    LOCAL fixture-factory for this file.
    """

    def _generate(last_price=100.0, atr_val=1.0, symbol="MOCKUSDT", **kwargs):
        base_info = {
            "symbol": symbol,
            "atr": atr_val,
            "natr": 1.5,
            "last_price": last_price,
            "tick_size": 0.01,
            "current_candle_index": 50,
            "timestamp_dt": pd.Timestamp.now(tz="UTC"),
            "candle_timeframe": "1m",
            "relative_volume": 2.0,
            "is_volume_spike": True,
            "SMA_10": last_price * 0.99,
            "SMA_50": last_price * 0.98,
            "RSI_14": 55.0,
            "ADX_14": 25.0,
            "MACD_hist_12_26_9": 0.1,
            "BBW_20_2": 0.05,
        }
        base_info.update(kwargs)
        return base_info

    return _generate


def test_integration_and_or_logic(visual_strategy_instance, get_default_pair_info):
    """
    Checks the correct operation of nested logical operators AND/OR.
    Strategy: (Market Activity) AND (Trend LONG OR RSI > 75)
    """
    test_json_config = {
        "entryConditions": {
            "id": "root",
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
                {
                    "id": "nested_or",
                    "type": "OR",
                    "children": [
                        {"type": "trend_direction", "params": {}},
                        {
                            "type": "rsi_condition",
                            "params": {"operator": "gt", "value": 75},
                        },
                    ],
                },
            ],
        }
    }
    strat = visual_strategy_instance(test_json_config)
    market_data = get_default_market_data()

    # Scenario 1: Activity + Trend = Signal
    pair_info_1 = get_default_pair_info(
        relative_volume=2.0, natr=2.0, SMA_10=101, SMA_50=100, RSI_14=60
    )
    signal_1, _, _ = strat.check_signal_sync(pair_info_1, market_data, None)
    assert signal_1 is not None, "Scenario 1 (Activity + Trend) should produce a signal"

    # Scenario 2: Activity + RSI = Signal
    pair_info_2 = get_default_pair_info(
        relative_volume=2.0, natr=2.0, SMA_10=100, SMA_50=101, RSI_14=80
    )
    signal_2, _, _ = strat.check_signal_sync(pair_info_2, market_data, None)
    assert signal_2 is not None, "Scenario 2 (Activity + RSI) should produce a signal"

    # Scenario 3: Activity, but neither Trend nor RSI = No signal
    pair_info_3 = get_default_pair_info(
        relative_volume=2.0, natr=2.0, SMA_10=100.0, SMA_50=100.0, RSI_14=50.0
    )
    signal_3, _, _ = strat.check_signal_sync(pair_info_3, market_data, None)
    assert signal_3 is None, "Scenario 3 should not produce a signal"

    # Scenario 4: No Activity (neither by vol nor by natr) = No signal
    pair_info_4 = get_default_pair_info(
        relative_volume=1.0,
        natr=1.0,
        is_volume_spike=False,
        SMA_10=101,
        SMA_50=100,
        RSI_14=80,
    )
    signal_4, _, _ = strat.check_signal_sync(pair_info_4, market_data, None)
    assert signal_4 is None, "Scenario 4 (No Activity) should not produce a signal"


def test_data_flow_between_blocks(visual_strategy_instance, get_default_pair_info):
    """
    Checks that data from one block (local_level) is correctly
    passed to another block (initialization) to create a signal.
    """
    test_json_config = {
        "entryConditions": {
            "id": "root",
            "type": "AND",
            "children": [
                {
                    "id": "level1",
                    "type": "local_level",
                    "params": {
                        "lookback_period": 5,
                        "proximity_type": "atr_multiplier",
                        "proximity_value": 0.5,
                        "timeframe": "1m",
                    },
                }
            ],
        },
        "initialization": {
            "id": "act1",
            "type": "open_position",
            "params": {
                "direction": "LONG",
                "order_type": "LIMIT_RETEST",
                "entry_price": {
                    "source": "block_result",
                    "block_id": "level1",
                    "key": "detected_level",
                },
            },
        },
    }
    strat = visual_strategy_instance(test_json_config)

    market_data = get_default_market_data()
    market_data["kline_1m"].iloc[
        -3, market_data["kline_1m"].columns.get_loc("high")
    ] = 105.0

    pair_info = get_default_pair_info(last_price=105.1, atr_val=0.5)

    signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)

    assert signal is not None, "Signal should have been generated"
    assert signal.entry_price == pytest.approx(105.0), (
        "Entry price in the signal must be equal to the found level"
    )


def test_integration_btc_dependent_filters(
    visual_strategy_instance, get_default_pair_info
):
    """
    Checks that the 'btc_state_filter' and 'correlation' filters work
    when the necessary data for BTCUSDT is provided.
    """
    test_json_config = {
        "filters": {
            "id": "root",
            "type": "AND",
            "children": [
                {
                    "id": "btc_state",
                    "type": "btc_state_filter",
                    "params": {"required_state": "Trending Up"},
                },
                {
                    "id": "correlation",
                    "type": "correlation",
                    "params": {"operator": "gt", "value": 0.9},
                },
            ],
        },
        "entryConditions": {"id": "entry_root", "type": "AND", "children": []},
    }
    strat = visual_strategy_instance(test_json_config)

    pair_info = get_default_pair_info(symbol="ETHUSDT")
    market_data = get_default_market_data()

    num_candles = len(market_data["kline_1m"])

    btc_closes = np.array([20000 + i * 10 for i in range(num_candles)], dtype=float)
    # Adding momentum at the end to exit consolidation (±1% from SMA)
    btc_closes[-30:] += np.linspace(0, 5000, 30)

    eth_closes = np.array([2000 + i * 1.01 for i in range(num_candles)], dtype=float)
    # Synchronous impulse to maintain correlation > 0.9
    eth_closes[-30:] += np.linspace(0, 500, 30)

    market_data["kline_1m"]["close"] = eth_closes
    btc_df = pd.DataFrame({"close": btc_closes}, index=market_data["kline_1m"].index)
    btc_df["SMA_20"] = btc_df["close"].rolling(window=20).mean().bfill()
    market_data["kline_1m_BTCUSDT"] = btc_df

    signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)

    assert isinstance(signal, StrategySignal), (
        "Signal MUST be generated because both filters, "
        "depending on BTC, should have executed successfully."
    )
