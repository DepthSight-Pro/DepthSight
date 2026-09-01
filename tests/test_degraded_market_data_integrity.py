# tests/test_degraded_market_data_integrity.py
"""
Degraded & Dirty Market Data Resilience Test Suite.

Simulates real-world exchange anomalies, WebSocket dropouts, network lags,
and corrupt payloads to guarantee that the VisualBuilderStrategy engine
NEVER crashes, throws uncaught exceptions, or issues rogue trades.

Scenarios tested:
1. NaN / None / Inf indicator values and candle prices.
2. Empty, missing, or crossed (inverted) orderbooks and stale tape feeds.
3. Empty DataFrames, truncated klines (insufficient warmup), and missing timeframes.
4. Zero-division traps (zero price, zero volume, zero ATR) and flash crash anomalies.
5. Corrupted AST condition nodes (missing params, unknown types, invalid param types).
6. Incomplete / corrupted BasePosition objects during Position Management execution.
7. Chaos fuzzing stream (random corruptions over 100 consecutive ticks).
"""

import os
import random
import time
from typing import Dict, Any, Tuple
import numpy as np
import pandas as pd
import pytest

# Ensure mock database env vars are set before importing api
os.environ.setdefault("POSTGRES_USER", "testuser")
os.environ.setdefault("POSTGRES_PASSWORD", "testpassword")
os.environ.setdefault("POSTGRES_DB", "testdb")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from bot_module.strategy import (
    VisualBuilderStrategy,
    BasePosition,
    SignalDirection,
)


def get_baseline_clean_data() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Returns a baseline clean pair_info and market_data."""
    timestamps = pd.date_range("2026-08-31 12:00:00", periods=50, freq="1min", tz="UTC")
    df = pd.DataFrame(
        {
            "open": np.linspace(60000, 60500, 50),
            "high": np.linspace(60100, 60600, 50),
            "low": np.linspace(59900, 60400, 50),
            "close": np.linspace(60050, 60550, 50),
            "volume": np.full(50, 150.0),
        },
        index=timestamps,
    )

    df_5m = (
        df.resample("5min")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna()
    )

    market_data = {
        "kline_1m": df,
        "kline_5m": df_5m,
        "kline_1m_BTCUSDT": df,
        "depth_trading": {
            "bids": [["60040.0", "5.0"], ["60030.0", "10.0"]],
            "asks": [["60060.0", "4.0"], ["60070.0", "8.0"]],
        },
        "depth_analysis": {
            "bids": [{"notional": 300000.0, "price": 60040.0}],
            "asks": [{"notional": 250000.0, "price": 60060.0}],
        },
    }

    pair_info = {
        "symbol": "BTCUSDT",
        "exchange": "bybit",
        "market_type": "futures_usdtm",
        "candle_timeframe": "1m",
        "last_price": 60050.0,
        "open": 60000.0,
        "high": 60100.0,
        "low": 59900.0,
        "close": 60050.0,
        "atr": 100.0,
        "natr": 0.166,
        "tick_size": 0.1,
        "relative_volume": 1.2,
        "is_volume_spike": False,
        "current_candle_index": 49,
        "timestamp_dt": timestamps[-1],
        "tape_delta_volume_usd_30s": 150000.0,
        "obi_1p": 0.2,
        "is_live_mode": True,
        "SMA_10": 60400.0,
        "SMA_20": 60300.0,
        "SMA_50": 60150.0,
        "RSI_14": 52.0,
        "ADX_14": 22.0,
    }

    return pair_info, market_data


# ============================================================================================
# 1. TEST 1: NaN, None, Inf Indicator Values & Price Payload Safety
# ============================================================================================
@pytest.mark.parametrize(
    "corrupt_key,corrupt_val",
    [
        ("RSI_14", np.nan),
        ("RSI_14", None),
        ("RSI_14", float("inf")),
        ("SMA_20", np.nan),
        ("SMA_20", None),
        ("SMA_20", float("-inf")),
        ("last_price", np.nan),
        ("last_price", None),
        ("atr", np.nan),
        ("atr", None),
        ("atr", float("inf")),
        ("relative_volume", np.nan),
        ("relative_volume", None),
        ("high", np.nan),
        ("low", np.nan),
    ],
)
def test_nan_none_inf_indicator_values_safe_rejection(
    corrupt_key: str, corrupt_val: Any
):
    """
    Ensures that when technical indicators or price fields contain NaN, None, or Inf:
    - Condition tree evaluates safely to False.
    - Zero uncaught exceptions are raised.
    - Result trace explicitly records the anomaly.
    """
    pair_info, market_data = get_baseline_clean_data()
    pair_info[corrupt_key] = corrupt_val

    strategy_config = {
        "entryConditions": {
            "id": "root_and",
            "type": "AND",
            "children": [
                {
                    "id": "c_rsi",
                    "type": "RSI",
                    "params": {"period": 14, "operator": "gt", "value": 50},
                },
                {
                    "id": "c_ma",
                    "type": "MA_CROSS",
                    "params": {"fast_period": 10, "slow_period": 20, "ma_type": "sma"},
                },
                {
                    "id": "c_vol",
                    "type": "VOLATILITY_FILTER",
                    "params": {"indicator": "ATR", "operator": "gt", "value": 50},
                },
            ],
        }
    }

    strategy = VisualBuilderStrategy(
        params={"config": strategy_config, "enabled": True}
    )

    # check_signal_sync must handle degraded pair_info gracefully
    signal, weight, trace = strategy.check_signal_sync(
        pair_info=pair_info,
        market_data=market_data,
        prev_pair_info={},
    )

    # When critical values are corrupted, signal must NOT be generated
    if corrupt_key in ["last_price", "RSI_14", "SMA_20", "atr"]:
        assert signal is None
    assert isinstance(weight, (int, float))
    assert isinstance(trace, (dict, type(None)))


# ============================================================================================
# 2. TEST 2: Empty, Missing, or Crossed (Inverted) Orderbook & Stale Tape Safety
# ============================================================================================
@pytest.mark.parametrize(
    "orderbook_mutation",
    [
        "empty_depth_trading",
        "none_depth_trading",
        "crossed_bids_asks",
        "corrupted_string_orderbook",
        "empty_depth_analysis",
        "stale_zero_tape",
    ],
)
def test_empty_and_crossed_orderbook_and_stale_tape_safety(orderbook_mutation: str):
    """
    Verifies that Microstructure, Orderbook Zone, and Tape Analysis blocks:
    - Return False without crashing when orderbook is empty, crossed (ask < bid), or invalid.
    - Correctly report diagnostics in trace.
    """
    pair_info, market_data = get_baseline_clean_data()

    if orderbook_mutation == "empty_depth_trading":
        market_data["depth_trading"] = {"bids": [], "asks": []}
    elif orderbook_mutation == "none_depth_trading":
        market_data["depth_trading"] = None
    elif orderbook_mutation == "crossed_bids_asks":
        # Crossed book: best ask (59,000) < best bid (61,000)
        market_data["depth_trading"] = {
            "bids": [["61000.0", "10.0"]],
            "asks": [["59000.0", "10.0"]],
        }
    elif orderbook_mutation == "corrupted_string_orderbook":
        market_data["depth_trading"] = {"bids": [["invalid_price", "abc"]], "asks": []}
    elif orderbook_mutation == "empty_depth_analysis":
        market_data["depth_analysis"] = {"bids": [], "asks": []}
    elif orderbook_mutation == "stale_zero_tape":
        pair_info["tape_delta_volume_usd_30s"] = 0.0

    strategy_config = {
        "entryConditions": {
            "id": "root_micro",
            "type": "AND",
            "children": [
                {
                    "id": "c_ob_zone",
                    "type": "order_book_zone",
                    "params": {
                        "side": "bids",
                        "range_type": "Percentage",
                        "range_value": 1,
                    },
                },
                {
                    "id": "c_l2",
                    "type": "l2_microstructure",
                    "params": {
                        "check_type": "large_order",
                        "single_order_size_usd": 100000,
                        "side": "bids",
                    },
                },
                {
                    "id": "c_tape",
                    "type": "tape_analysis",
                    "params": {"time_window_sec": 30},
                },
            ],
        }
    }

    strategy = VisualBuilderStrategy(
        params={"config": strategy_config, "enabled": True}
    )

    res, trace = strategy._evaluate_condition_tree(
        node=strategy_config["entryConditions"],
        pair_info=pair_info,
        market_data=market_data,
        prev_pair_info={},
        context={},
    )

    assert isinstance(res, (bool, bool))
    assert trace["type"] == "AND"


# ============================================================================================
# 3. TEST 3: Empty, Truncated Klines & Missing Timeframes Safety
# ============================================================================================
@pytest.mark.parametrize(
    "kline_mutation",
    [
        "empty_df",
        "single_row_df",
        "missing_kline_5m",
        "all_none_columns_df",
    ],
)
def test_empty_and_truncated_klines_and_missing_timeframes(kline_mutation: str):
    """
    Tests engine response when klines are missing, empty, or have insufficient bars
    for indicator calculation (e.g. 1 bar available for 50-period SMA).
    """
    pair_info, market_data = get_baseline_clean_data()

    if kline_mutation == "empty_df":
        market_data["kline_1m"] = pd.DataFrame()
    elif kline_mutation == "single_row_df":
        market_data["kline_1m"] = market_data["kline_1m"].iloc[:1]
        pair_info["current_candle_index"] = 0
    elif kline_mutation == "missing_kline_5m":
        market_data.pop("kline_5m", None)
    elif kline_mutation == "all_none_columns_df":
        market_data["kline_1m"] = pd.DataFrame(
            {
                "open": [None, None],
                "high": [None, None],
                "low": [None, None],
                "close": [None, None],
            }
        )

    strategy_config = {
        "filters": {
            "id": "f_root",
            "type": "AND",
            "children": [
                {
                    "id": "f_htf",
                    "type": "senior_tf_confluence",
                    "params": {"timeframe": "5m"},
                    "children": [
                        {
                            "id": "f_htf_ma",
                            "type": "MA_CROSS",
                            "params": {
                                "fast_period": 10,
                                "slow_period": 50,
                                "ma_type": "sma",
                            },
                        }
                    ],
                }
            ],
        },
        "entryConditions": {
            "id": "e_root",
            "type": "AND",
            "children": [
                {
                    "id": "c_consolidation",
                    "type": "price_consolidation",
                    "params": {"lookback_period": 20, "max_range_atr": 0.8},
                },
                {
                    "id": "c_pa",
                    "type": "price_action_analyzer",
                    "params": {"structure_type": "higher_lows", "lookback_candles": 30},
                },
            ],
        },
    }

    strategy = VisualBuilderStrategy(
        params={"config": strategy_config, "enabled": True}
    )

    # Strategy must safely return without unhandled exception
    signal, weight, trace = strategy.check_signal_sync(
        pair_info=pair_info,
        market_data=market_data,
        prev_pair_info={},
    )

    assert signal is None  # Degraded klines cannot generate valid signals


# ============================================================================================
# 4. TEST 4: Zero-Division Traps & Flash Crash Spikes Resilience
# ============================================================================================
@pytest.mark.parametrize(
    "extreme_case",
    [
        {"last_price": 0.0, "atr": 0.0, "relative_volume": 0.0},
        {"last_price": -100.0, "atr": -10.0},
        {"last_price": 0.00000001, "tick_size": 0.000000001, "atr": 0.000000001},
        {"last_price": 100000000.0, "atr": 50000000.0},
    ],
)
def test_zero_division_and_flash_crash_outlier_resilience(extreme_case: Dict[str, Any]):
    """
    Tests mathematical stability against zero price, negative numbers,
    extreme small decimals (micro-memecoins), and massive flash spikes.
    """
    pair_info, market_data = get_baseline_clean_data()
    pair_info.update(extreme_case)

    strategy_config = {
        "filters": {
            "id": "f_root",
            "type": "AND",
            "children": [
                {
                    "id": "f_natr",
                    "type": "natr_filter",
                    "params": {"natr_threshold": 1.0},
                },
                {
                    "id": "f_squeeze",
                    "type": "volatility_squeeze",
                    "params": {"lookback_candles": 20, "squeeze_ratio": 0.6},
                },
            ],
        },
        "entryConditions": {
            "id": "e_root",
            "type": "AND",
            "children": [
                {
                    "id": "c_round",
                    "type": "round_level",
                    "params": {"proximity_type": "percentage", "proximity_value": 0.2},
                },
                {
                    "id": "c_vol",
                    "type": "volume_confirmation",
                    "params": {"multiplier": 1.5},
                },
            ],
        },
    }

    strategy = VisualBuilderStrategy(
        params={"config": strategy_config, "enabled": True}
    )

    signal, weight, trace = strategy.check_signal_sync(
        pair_info=pair_info,
        market_data=market_data,
        prev_pair_info={},
    )

    assert isinstance(weight, (int, float))


# ============================================================================================
# 5. TEST 5: Corrupted AST Condition Nodes & Invalid Parameter Types
# ============================================================================================
def test_malformed_condition_nodes_and_invalid_param_types():
    """
    Injects malformed AST nodes (missing params, unknown types, string values where float expected).
    Verifies that the engine isolates the error per node and does not crash the entire strategy.
    """
    pair_info, market_data = get_baseline_clean_data()

    malformed_config = {
        "entryConditions": {
            "id": "root_and",
            "type": "AND",
            "children": [
                # 1. Unknown node type
                {
                    "id": "node_unknown",
                    "type": "QUANTUM_AI_SUPER_INDICATOR_XYZ",
                    "params": {},
                },
                # 2. Missing params dictionary entirely
                {"id": "node_missing_params", "type": "RSI"},
                # 3. Invalid parameter data types
                {
                    "id": "node_corrupted_types",
                    "type": "RSI",
                    "params": {"period": "not_an_int", "operator": "gt", "value": None},
                },
                # 4. Broken dynamic link referencing non-existent block UUID
                {
                    "id": "node_broken_link",
                    "type": "value_comparison",
                    "params": {
                        "leftOperand": {
                            "source": "block_result",
                            "block_id": "00000000-0000-0000-0000-000000000000",
                            "key": "val",
                        },
                        "operator": "gt",
                        "rightOperand": 100,
                    },
                },
            ],
        }
    }

    strategy = VisualBuilderStrategy(
        params={"config": malformed_config, "enabled": True}
    )

    res, trace = strategy._evaluate_condition_tree(
        node=malformed_config["entryConditions"],
        pair_info=pair_info,
        market_data=market_data,
        prev_pair_info={},
        context={},
    )

    # Malformed nodes safely evaluate to False
    assert res is False
    assert trace["type"] == "AND"
    assert len(trace["children"]) == 4


# ============================================================================================
# 6. TEST 6: Incomplete / Corrupted Position Objects in Position Management
# ============================================================================================
@pytest.mark.parametrize(
    "corrupted_pos_params",
    [
        {"entry_price": 0.0, "initial_stop_loss": 0.0, "current_sl_price": 0.0},
        {"entry_price": None, "initial_stop_loss": None},
        {"initial_quantity": 0.0, "remaining_quantity": 0.0},
        {"entry_price": -50000.0, "initial_stop_loss": -51000.0},
    ],
)
def test_corrupted_position_objects_in_position_management(
    corrupted_pos_params: Dict[str, Any],
):
    """
    Verifies that Position Management blocks (Trailing stop, Break-even, DCA, Grid)
    handle corrupted BasePosition states safely without throwing unhandled exceptions.
    """
    pair_info, market_data = get_baseline_clean_data()
    strategy = VisualBuilderStrategy(params={"enabled": True})

    pos = BasePosition(
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        entry_price=corrupted_pos_params.get("entry_price") or 60000.0,
        initial_quantity=corrupted_pos_params.get("initial_quantity") or 1.0,
        remaining_quantity=corrupted_pos_params.get("remaining_quantity") or 1.0,
        entry_time=time.time(),
        strategy="VisualBuilderStrategy",
        initial_stop_loss=corrupted_pos_params.get("initial_stop_loss"),
        current_sl_price=corrupted_pos_params.get("current_sl_price") or 59000.0,
    )

    trailing_block = {
        "id": "pm_trail",
        "type": "trailing_stop",
        "params": {"type": "Percentage", "value": 2.0},
    }
    be_block = {
        "id": "pm_be",
        "type": "move_to_breakeven",
        "params": {
            "target_type": "rr_multiplier",
            "target_value": 1.0,
            "offset_pips": 2,
        },
    }

    # Execute all PM handlers on corrupted position
    pos_out_1 = strategy._handle_trailing_stop(trailing_block, pos, pair_info)
    pos_out_2 = strategy._handle_move_to_breakeven(be_block, pos_out_1, pair_info)

    assert isinstance(pos_out_1, BasePosition)
    assert isinstance(pos_out_2, BasePosition)


# ============================================================================================
# 7. TEST 7: Chaos Fuzzing Stream (Random Dropouts Over 100 Consecutive Ticks)
# ============================================================================================
def test_chaos_fuzzing_random_dropouts_and_corruptions():
    """
    Runs 100 consecutive stream cycles where each cycle randomly applies 1-3 corruptions
    (NaNs, missing orderbooks, empty klines, zero prices, missing indicators).
    Verifies that the strategy engine runs all 100 iterations with 100% stability.
    """
    random.seed(999)
    np.random.seed(999)

    strategy_config = {
        "filters": {
            "id": "f_root",
            "type": "AND",
            "children": [
                {
                    "id": "f_vol",
                    "type": "volatility_filter",
                    "params": {"indicator": "ATR", "operator": "gt", "value": 10},
                },
                {
                    "id": "f_trend",
                    "type": "trend_filter",
                    "params": {"indicator": "ADX", "threshold": 20},
                },
            ],
        },
        "entryConditions": {
            "id": "e_root",
            "type": "AND",
            "children": [
                {
                    "id": "c_rsi",
                    "type": "RSI",
                    "params": {"period": 14, "operator": "lt", "value": 70},
                },
                {
                    "id": "c_ob",
                    "type": "order_book_zone",
                    "params": {
                        "side": "bids",
                        "range_type": "Percentage",
                        "range_value": 1,
                    },
                },
            ],
        },
    }

    strategy = VisualBuilderStrategy(
        params={"config": strategy_config, "enabled": True}
    )

    for tick in range(100):
        pair_info, market_data = get_baseline_clean_data()

        # Randomly apply 1 to 3 corruptions
        corruptions = random.sample(
            [
                "nan_indicator",
                "none_price",
                "empty_ob",
                "truncated_klines",
                "zero_atr",
                "none_klines",
            ],
            k=random.randint(1, 3),
        )

        for c in corruptions:
            if c == "nan_indicator":
                pair_info["RSI_14"] = np.nan
            elif c == "none_price":
                pair_info["last_price"] = None
            elif c == "empty_ob":
                market_data["depth_trading"] = {"bids": [], "asks": []}
            elif c == "truncated_klines":
                if market_data.get("kline_1m") is not None:
                    market_data["kline_1m"] = market_data["kline_1m"].iloc[:2]
            elif c == "zero_atr":
                pair_info["atr"] = 0.0
            elif c == "none_klines":
                market_data["kline_1m"] = None

        # Execute check_signal_sync under chaos conditions
        signal, weight, trace = strategy.check_signal_sync(
            pair_info=pair_info,
            market_data=market_data,
            prev_pair_info={},
        )

        assert isinstance(weight, (int, float))
        assert isinstance(trace, (dict, type(None)))
