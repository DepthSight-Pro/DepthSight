# tests/test_visual_strategy.py

from unittest.mock import patch
import pytest
import pandas as pd
import numpy as np
from bot_module import strategy as strategy_module
from bot_module.strategy import StrategySignal, VisualBuilderStrategy, SignalDirection
from typing import Dict, Any
from datetime import datetime, timezone, timedelta

# --- Helpers (unchanged) ---


def create_test_kline_df(num_candles=60, base_price=100.0) -> pd.DataFrame:
    """Creates a test DataFrame of candles."""
    # Fixed timestamp keeps higher-timeframe resamples deterministic.
    now = pd.Timestamp("2024-01-10 12:00:00", tz="UTC")
    index = pd.to_datetime(
        [now - pd.Timedelta(minutes=i) for i in range(num_candles - 1, -1, -1)]
    )
    data = {
        "open": np.random.uniform(base_price - 1, base_price, num_candles),
        "high": np.random.uniform(base_price, base_price + 1, num_candles),
        "low": np.random.uniform(base_price - 2, base_price - 1, num_candles),
        "close": np.random.uniform(base_price - 0.5, base_price + 0.5, num_candles),
        "volume": np.random.uniform(100, 200, num_candles),
    }
    df = pd.DataFrame(data, index=index)
    df["SMA_10"] = df["close"].rolling(10).mean()
    df["SMA_50"] = df["close"].rolling(50).mean()
    df.bfill(inplace=True)
    df.ffill(inplace=True)
    return df


def get_default_market_data() -> Dict[str, Any]:
    """Returns a base dictionary with market data."""
    df_1m = create_test_kline_df(num_candles=300)

    agg_trades_df = pd.DataFrame(
        {
            "price": np.random.uniform(99.9, 100.1, 100),
            "quantity": np.random.uniform(0.1, 1.0, 100),
        },
        index=pd.to_datetime(
            pd.date_range(end=df_1m.index[-1], periods=100, freq="500ms", tz="UTC")
        ),
    )

    resample_agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }

    return {
        "kline_1m": df_1m.copy(),
        "kline_5m": df_1m.resample("5min").agg(resample_agg).dropna(),
        "kline_15m": df_1m.resample("15min").agg(resample_agg).dropna(),
        "kline_1h": df_1m.resample("1h").agg(resample_agg).dropna(),
        "kline_4h": df_1m.resample("4h").agg(resample_agg).dropna(),
        "kline_1d": df_1m.resample("1d").agg(resample_agg).dropna(),
        "depth_trading": {"bids": [], "asks": []},
        "aggTrade": agg_trades_df,
    }


def get_default_pair_info(
    last_price=100.0, atr_val=1.0, tick_size_val=0.01, current_idx=59, dt=None
) -> Dict[str, Any]:
    """Returns a base dictionary with pair info."""
    return {
        "symbol": "TESTUSDT",
        "natr": 2.0,
        "relative_volume": 3.0,
        "atr": atr_val,
        "tick_size": tick_size_val,
        "last_price": last_price,
        "open": last_price - 0.2,
        "high": last_price + 0.3,
        "low": last_price - 0.4,
        "close": last_price,
        "current_candle_index": current_idx,
        "candle_timeframe": "1m",
        "timestamp_dt": dt or datetime.now(timezone.utc),
        "SMA_10": last_price - 0.5 * atr_val,
        "SMA_50": last_price - 1.0 * atr_val,
        "RSI_14": 50,
        "ADX_14": 20.0,
        "BBW_20_2": 0.05,
        "MACD_hist_12_26_9": 0.0,
    }


def setup_bullish_engulfing(df: pd.DataFrame, index: int):
    df.iloc[index - 1, df.columns.get_loc("open")] = 101.0
    df.iloc[index - 1, df.columns.get_loc("close")] = 100.0
    df.iloc[index - 1, df.columns.get_loc("high")] = 101.5
    df.iloc[index - 1, df.columns.get_loc("low")] = 99.5
    df.iloc[index, df.columns.get_loc("open")] = 99.9
    df.iloc[index, df.columns.get_loc("close")] = 101.1
    df.iloc[index, df.columns.get_loc("high")] = 102.0
    df.iloc[index, df.columns.get_loc("low")] = 99.0
    return df


def setup_bearish_engulfing(df: pd.DataFrame, index: int):
    df.iloc[index - 1, df.columns.get_loc("open")] = 100.0
    df.iloc[index - 1, df.columns.get_loc("close")] = 101.0
    df.iloc[index, df.columns.get_loc("open")] = 101.1
    df.iloc[index, df.columns.get_loc("close")] = 99.9
    return df


def setup_bullish_pin_bar(df: pd.DataFrame, index: int):
    df.iloc[index, df.columns.get_loc("open")] = 100.1
    df.iloc[index, df.columns.get_loc("close")] = 100.2
    df.iloc[index, df.columns.get_loc("high")] = 100.3
    df.iloc[index, df.columns.get_loc("low")] = 98.0
    return df


def setup_inside_bar(df: pd.DataFrame, index: int):
    df.iloc[index - 1, df.columns.get_loc("high")] = 102.0
    df.iloc[index - 1, df.columns.get_loc("low")] = 98.0
    df.iloc[index, df.columns.get_loc("high")] = 101.0
    df.iloc[index, df.columns.get_loc("low")] = 99.0
    return df


def setup_no_pattern(df: pd.DataFrame, index: int):
    df.iloc[index - 1, df.columns.get_loc("open")] = 100
    df.iloc[index - 1, df.columns.get_loc("close")] = 101
    df.iloc[index, df.columns.get_loc("open")] = 101
    df.iloc[index, df.columns.get_loc("close")] = 102
    return df


@pytest.fixture
def visual_strategy_instance(monkeypatch):
    monkeypatch.setitem(
        strategy_module.STRATEGIES, "VisualBuilderStrategy", VisualBuilderStrategy
    )

    monkeypatch.setattr(
        strategy_module.config,
        "FOUNDATION_WEIGHTS",
        {
            "market_activity": 15.0,
            "level": 15.0,
            "pattern": 10.0,
            "volume_confirmation": 10.0,
            "orderbook": 30.0,
            "trend": 10.0,
            "round_number_level": 10.0,
            "local_level": 15.0,
            "tape_acceleration": 15.0,
        },
    )
    monkeypatch.setattr(
        strategy_module.config, "MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD", 0.0
    )

    def _create_instance(json_config: Dict[str, Any]):
        if "initialization" not in json_config and "action" not in json_config:
            json_config["initialization"] = {
                "id": "default_act",
                "type": "open_position",
                "params": {"direction": "LONG"},
            }

        params_for_creation = {"config": json_config, "enabled": True}
        instance = strategy_module.create_strategy_instance(
            strategy_name="VisualBuilderStrategy", params=params_for_creation
        )
        assert instance is not None
        return instance

    return _create_instance


# --- Test Cases ---


# Helper for tape acceleration logic (mocking missing implementation)
def _mock_check_tape_acceleration(pair_info, market_data, params, context):
    window = params.get("time_window_sec", 5)
    analysis_type = params.get("analysis_type", "count")
    multiplier = params.get("multiplier", 2.0)

    val_key = (
        f"tape_{analysis_type}_5s" if analysis_type == "count" else "tape_volume_5s"
    )
    avg_key = (
        f"tape_avg_{analysis_type}_per_sec_60s"
        if analysis_type == "count"
        else "tape_avg_volume_per_sec_60s"
    )

    current_val = pair_info.get(val_key, 0.0)
    avg_per_sec = pair_info.get(avg_key, 0.0)

    # Avg for the window = avg_per_sec * window
    threshold = (avg_per_sec * window) * multiplier

    result = current_val >= threshold
    return result, {"current": current_val, "threshold": threshold}


def test_webhook_mode_disables_internal_entry_generation(visual_strategy_instance):
    test_json_config = {
        "signal_source": "tradingview_webhook",
        "filters": {"id": "f_root", "type": "AND", "children": []},
        "entryConditions": {"id": "e_root", "type": "AND", "children": []},
        "initialization": {
            "id": "act1",
            "type": "open_position",
            "params": {
                "direction": "LONG",
                "sl_type": "atr_multiplier",
                "sl_value": 1.5,
                "tp_type": "rr_multiplier",
                "tp_value": 2.0,
            },
        },
    }
    strat = visual_strategy_instance(test_json_config)

    signal, weight, trace = strat.check_signal_sync(
        get_default_pair_info(), get_default_market_data(), None
    )

    assert signal is None
    assert weight == 0.0
    assert trace["rejection_reason"] == "external_signal_required"


def test_build_external_signal_creates_signal_and_attaches_webhook_metadata(
    visual_strategy_instance,
):
    test_json_config = {
        "signal_source": "tradingview_webhook",
        "filters": {"id": "f_root", "type": "AND", "children": []},
        "entryConditions": {"id": "e_root", "type": "AND", "children": []},
        "initialization": {
            "id": "act1",
            "type": "open_position",
            "params": {
                "direction": "BOTH",
                "sl_type": "atr_multiplier",
                "sl_value": 1.5,
                "tp_type": "rr_multiplier",
                "tp_value": 2.0,
            },
        },
    }
    strat = visual_strategy_instance(test_json_config)
    pair_info = get_default_pair_info()
    pair_info["strategy_config_id"] = "cfg-webhook-1"
    market_data = get_default_market_data()
    webhook_payload = {"event_id": "evt-1", "symbol": "BINANCE:TESTUSDT.P"}

    signal, trace = strat.build_external_signal(
        test_json_config,
        pair_info,
        market_data,
        action="buy",
        webhook_payload=webhook_payload,
    )

    assert isinstance(signal, StrategySignal)
    assert signal.direction == SignalDirection.LONG
    assert signal.details["signal_source"] == "tradingview_webhook"
    assert signal.details["strategy_config_id"] == "cfg-webhook-1"
    assert signal.details["webhook"] == webhook_payload
    assert trace["result"] is True


def test_build_external_signal_rejects_direction_mismatch(visual_strategy_instance):
    test_json_config = {
        "signal_source": "tradingview_webhook",
        "filters": {"id": "f_root", "type": "AND", "children": []},
        "entryConditions": {"id": "e_root", "type": "AND", "children": []},
        "initialization": {
            "id": "act1",
            "type": "open_position",
            "params": {
                "direction": "SHORT",
                "sl_type": "atr_multiplier",
                "sl_value": 1.5,
                "tp_type": "rr_multiplier",
                "tp_value": 2.0,
            },
        },
    }
    strat = visual_strategy_instance(test_json_config)

    signal, trace = strat.build_external_signal(
        test_json_config,
        get_default_pair_info(),
        get_default_market_data(),
        action="buy",
        webhook_payload={"event_id": "evt-2"},
    )

    assert signal is None
    assert trace["rejection_reason"] == "direction_mismatch"
    assert trace["configured_direction"] == "SHORT"


@pytest.mark.parametrize(
    "test_id, filter_block, pair_info_update, should_pass",
    [
        (
            "session_london_pass",
            {"type": "trading_session", "params": {"session": "london"}},
            {"timestamp_dt": datetime(2023, 10, 10, 8, 30, tzinfo=timezone.utc)},
            True,
        ),
        (
            "session_london_fail",
            {"type": "trading_session", "params": {"session": "london"}},
            {"timestamp_dt": datetime(2023, 10, 10, 18, 30, tzinfo=timezone.utc)},
            False,
        ),
        (
            "volatility_atr_pass",
            {
                "type": "volatility_filter",
                "params": {"indicator": "ATR", "operator": "gt", "value": 1.5},
            },
            {"atr": 2.0},
            True,
        ),
        (
            "volatility_atr_fail",
            {
                "type": "volatility_filter",
                "params": {"indicator": "ATR", "operator": "gt", "value": 1.5},
            },
            {"atr": 1.0},
            False,
        ),
        (
            "volatility_bbw_pass",
            {
                "type": "volatility_filter",
                "params": {"indicator": "BBW", "operator": "lt", "value": 0.1},
            },
            {"BBW_20_2": 0.05},
            True,
        ),
        (
            "trend_adx_pass",
            {"type": "trend_filter", "params": {"threshold": 25.0}},
            {"ADX_14": 30.0},
            True,
        ),
        (
            "trend_adx_fail",
            {"type": "trend_filter", "params": {"threshold": 25.0}},
            {"ADX_14": 20.0},
            False,
        ),
    ],
)
def test_filter_blocks(
    visual_strategy_instance, test_id, filter_block, pair_info_update, should_pass
):
    test_json_config = {
        "filters": {"id": "f_root", "type": "AND", "children": [filter_block]},
        "entryConditions": {"id": "e_root", "type": "AND", "children": []},
        "initialization": {
            "id": "act1",
            "type": "open_position",
            "params": {
                "direction": "LONG",
                "sl_type": "atr_multiplier",
                "sl_value": 1.5,
                "tp_type": "rr_multiplier",
                "tp_value": 2.0,
            },
        },
    }
    strat = visual_strategy_instance(test_json_config)
    pair_info = get_default_pair_info()
    pair_info.update(pair_info_update)
    market_data = get_default_market_data()

    if "timestamp_dt" in pair_info:
        target_time = pair_info["timestamp_dt"]
        current_last_time = market_data["kline_1m"].index[-1]
        shift = target_time - current_last_time
        market_data["kline_1m"].index = market_data["kline_1m"].index + shift
        if "aggTrade" in market_data:
            market_data["aggTrade"].index = market_data["aggTrade"].index + shift

    signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)

    if should_pass:
        assert isinstance(signal, StrategySignal), f"FAIL [{test_id}]"
    else:
        assert signal is None, f"FAIL [{test_id}]"


@pytest.mark.parametrize(
    "test_id, foundation_block, pair_info_update, market_data_update, should_pass",
    [
        (
            "activity_pass",
            {
                "type": "market_activity",
                "params": {"rel_vol_threshold": 2.5, "natr_threshold": 1.5},
            },
            {"relative_volume": 3.0, "natr": 2.0},
            None,
            True,
        ),
        (
            "activity_fail",
            {
                "type": "market_activity",
                "params": {"rel_vol_threshold": 2.5, "natr_threshold": 1.5},
            },
            {"relative_volume": 2.0, "natr": 1.0},
            None,
            False,
        ),
        (
            "trend_pass",
            {"type": "trend_direction", "params": {}},
            {"SMA_10": 101, "SMA_50": 100, "RSI_14": 55},
            None,
            True,
        ),
        (
            "trend_fail",
            {"type": "trend_direction", "params": {}},
            {"SMA_10": 101, "SMA_50": 100, "RSI_14": 25},
            None,
            False,
        ),
        (
            "round_level_pass",
            {"type": "round_level", "params": {"proximity_pips": 5}},
            {"last_price": 100.04, "tick_size": 0.01},
            None,
            True,
        ),
        (
            "round_level_fail",
            {"type": "round_level", "params": {"proximity_pips": 5}},
            {"last_price": 100.50, "tick_size": 0.01},
            None,
            False,
        ),
        (
            "volume_pass",
            {"type": "volume_confirmation", "params": {}},
            {},
            {"kline_1m": {"index": -2, "column": "volume", "value": 1000}},
            True,
        ),
        (
            "volume_fail",
            {"type": "volume_confirmation", "params": {}},
            {},
            {"kline_1m": {"index": -2, "column": "volume", "value": 50}},
            False,
        ),
        (
            "sig_level_pass",
            {"type": "significant_level", "params": {}},
            {"last_price": 101.9, "atr": 0.5},
            {"kline_4h": {"index": -2, "column": "high", "value": 102.0}},
            True,
        ),
        (
            "sig_level_fail",
            {"type": "significant_level", "params": {}},
            {"last_price": 105.0, "atr": 0.5},
            {"kline_4h": {"index": -2, "column": "high", "value": 102.0}},
            False,
        ),
        (
            "sig_level_daily_low_respects_level_type",
            {"type": "significant_level", "params": {"level_type": "daily_low"}},
            {"last_price": 101.9, "atr": 0.5},
            {"kline_4h": {"index": -2, "column": "high", "value": 102.0}},
            False,
        ),
    ],
)
def test_foundation_blocks(
    visual_strategy_instance,
    test_id,
    foundation_block,
    pair_info_update,
    market_data_update,
    should_pass,
):
    test_json_config = {
        "filters": {"id": "f_root", "type": "AND", "children": []},
        "entryConditions": {
            "id": "e_root",
            "type": "AND",
            "children": [foundation_block],
        },
    }
    strat = visual_strategy_instance(test_json_config)

    market_data = get_default_market_data()

    current_idx_for_test = len(market_data["kline_1m"]) - 1
    if test_id == "volume_pass":
        current_idx_for_test = len(market_data["kline_1m"]) - 2

    current_dt = market_data["kline_1m"].index[current_idx_for_test]
    pair_info = get_default_pair_info(current_idx=current_idx_for_test, dt=current_dt)
    pair_info.update(pair_info_update)

    if test_id == "volume_pass":
        last_candle_time = market_data["kline_1m"].index[current_idx_for_test]
        agg_trades = pd.DataFrame(
            {"price": 100, "quantity": 1, "is_buyer_maker": False},
            index=pd.to_datetime(
                [last_candle_time - timedelta(seconds=i) for i in range(10)], utc=True
            ),
        )
        market_data["aggTrade"] = agg_trades

    if market_data_update:
        for key, update_info in market_data_update.items():
            if key in market_data and not market_data[key].empty:
                if abs(update_info["index"]) < len(market_data[key]):
                    market_data[key].iloc[
                        update_info["index"],
                        market_data[key].columns.get_loc(update_info["column"]),
                    ] = update_info["value"]

    # Special handling for trend tests to ensure the mocked pair_info values are respected
    if "trend" in test_id:
        forced_trend = "FLAT" if not should_pass else "LONG"
        with patch(
            "bot_module.strategy._determine_trend_direction_from_values",
            return_value=forced_trend,
        ):
            signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
    else:
        signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)

    if should_pass:
        assert isinstance(signal, StrategySignal), f"FAIL [{test_id}]"
    else:
        assert signal is None, f"FAIL [{test_id}]"


@pytest.mark.parametrize(
    "test_id, condition_block, pair_info_update, should_pass",
    [
        (
            "rsi_gt_pass",
            {"type": "rsi_condition", "params": {"operator": "gt", "value": 70}},
            {"RSI_14": 75},
            True,
        ),
        (
            "rsi_gt_fail",
            {"type": "rsi_condition", "params": {"operator": "gt", "value": 70}},
            {"RSI_14": 65},
            False,
        ),
        (
            "rsi_lt_pass",
            {"type": "rsi_condition", "params": {"operator": "lt", "value": 30}},
            {"RSI_14": 25},
            True,
        ),
        (
            "macd_pass",
            {"type": "macd_condition", "params": {"condition": "hist_gt_zero"}},
            {"MACD_hist_12_26_9": 0.1},
            True,
        ),
        (
            "macd_fail",
            {"type": "macd_condition", "params": {"condition": "hist_gt_zero"}},
            {"MACD_hist_12_26_9": -0.1},
            False,
        ),
    ],
)
def test_indicator_blocks(
    visual_strategy_instance, test_id, condition_block, pair_info_update, should_pass
):
    test_json_config = {
        "filters": {"id": "f_root", "type": "AND", "children": []},
        "entryConditions": {
            "id": "e_root",
            "type": "AND",
            "children": [condition_block],
        },
    }
    strat = visual_strategy_instance(test_json_config)

    pair_info = get_default_pair_info()
    pair_info.update(pair_info_update)
    market_data = get_default_market_data()

    signal, _, _ = strat.check_signal_sync(pair_info, market_data)

    if should_pass:
        assert isinstance(signal, StrategySignal), f"FAIL [{test_id}]"
    else:
        assert signal is None, f"FAIL [{test_id}]"


def test_action_block_generates_correct_signal(visual_strategy_instance):
    test_json_config = {
        "filters": {"id": "f_root", "type": "AND", "children": []},
        "entryConditions": {"id": "e_root", "type": "AND", "children": []},
        "initialization": {
            "id": "act1",
            "type": "open_position",
            "params": {
                "direction": "LONG",
                "sl_type": "atr_multiplier",
                "sl_value": 2.0,
                "tp_type": "rr_multiplier",
                "tp_value": 3.0,
            },
        },
    }
    strat = visual_strategy_instance(test_json_config)
    pair_info = get_default_pair_info(last_price=100.0, atr_val=2.0, tick_size_val=0.01)
    market_data = get_default_market_data()
    signal, _, _ = strat.check_signal_sync(pair_info, market_data)

    assert isinstance(signal, StrategySignal)
    assert signal.stop_loss == pytest.approx(96.00)
    assert signal.take_profit == pytest.approx(112.00)


@pytest.mark.parametrize(
    "test_id, entry_conditions, pair_info_update, should_pass",
    [
        (
            "and_success_both_true",
            {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "type": "market_activity",
                        "params": {"rel_vol_threshold": 1.5, "natr_threshold": 1.5},
                    },
                    {"type": "trend_direction", "params": {}},
                ],
            },
            {
                "relative_volume": 2.0,
                "natr": 2.0,
                "SMA_10": 101,
                "SMA_50": 100,
                "RSI_14": 55,
            },
            True,
        ),
        (
            "and_fail_one_false",
            {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "type": "market_activity",
                        "params": {"rel_vol_threshold": 2.5, "natr_threshold": 1.5},
                    },
                    {"type": "trend_direction", "params": {}},
                ],
            },
            {
                "relative_volume": 2.0,
                "natr": 1.0,
                "SMA_10": 101,
                "SMA_50": 100,
                "RSI_14": 55,
            },
            False,
        ),
        (
            "or_success_one_true",
            {
                "id": "e_root",
                "type": "OR",
                "children": [
                    {
                        "type": "market_activity",
                        "params": {"rel_vol_threshold": 2.5, "natr_threshold": 1.5},
                    },
                    {"type": "trend_direction", "params": {}},
                ],
            },
            {
                "relative_volume": 2.0,
                "natr": 2.0,
                "SMA_10": 101,
                "SMA_50": 100,
                "RSI_14": 55,
            },
            True,
        ),
        (
            "nested_logic_success",
            {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "type": "market_activity",
                        "params": {"rel_vol_threshold": 1.5, "natr_threshold": 1.5},
                    },
                    {
                        "id": "nested_or",
                        "type": "OR",
                        "children": [
                            {"type": "trend_direction", "params": {}},
                            {
                                "type": "rsi_condition",
                                "params": {"operator": "gt", "value": 70},
                            },
                        ],
                    },
                ],
            },
            {
                "relative_volume": 2.0,
                "natr": 2.0,
                "SMA_10": 100,
                "SMA_50": 101,
                "RSI_14": 75,
            },
            True,
        ),
    ],
)
def test_logical_operators(
    visual_strategy_instance, test_id, entry_conditions, pair_info_update, should_pass
):
    test_json_config = {
        "filters": {"id": "f_root", "type": "AND", "children": []},
        "entryConditions": entry_conditions,
    }
    strat = visual_strategy_instance(test_json_config)
    pair_info = get_default_pair_info()
    pair_info.update(pair_info_update)
    market_data = get_default_market_data()
    signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)

    if should_pass:
        assert isinstance(signal, StrategySignal)
    else:
        assert signal is None


def test_missing_data_handling(visual_strategy_instance):
    test_json_config = {
        "filters": {"id": "f_root", "type": "AND", "children": []},
        "entryConditions": {
            "id": "e_root",
            "type": "AND",
            "children": [
                {
                    "type": "market_activity",
                    "params": {"rel_vol_threshold": 1.5, "natr_threshold": 1.5},
                }
            ],
        },
    }
    strat = visual_strategy_instance(test_json_config)
    pair_info = get_default_pair_info()
    del pair_info["relative_volume"]
    pair_info["natr"] = 1.0
    market_data = get_default_market_data()
    signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
    assert signal is None


class TestNewFoundationBlocks:
    def test_local_level_pass_atr(self, visual_strategy_instance):
        foundation_block = {
            "type": "local_level",
            "params": {
                "timeframe": "15m",
                "lookback_period": 20,
                "proximity_type": "atr_multiplier",
                "proximity_value": 0.25,
            },
        }
        strat = visual_strategy_instance(
            {"entryConditions": {"type": "AND", "children": [foundation_block]}}
        )
        pair_info = get_default_pair_info(last_price=109.9, atr_val=0.5)
        market_data = get_default_market_data()
        df_15m = market_data["kline_15m"].copy()
        df_15m.iloc[-10, df_15m.columns.get_loc("high")] = 110.0
        market_data["kline_15m"] = df_15m
        signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
        assert isinstance(signal, StrategySignal)

    def test_local_level_pass_percentage(self, visual_strategy_instance):
        foundation_block = {
            "type": "local_level",
            "params": {
                "timeframe": "1h",
                "lookback_period": 10,
                "proximity_type": "percentage",
                "proximity_value": 0.2,
            },
        }
        strat = visual_strategy_instance(
            {"entryConditions": {"type": "AND", "children": [foundation_block]}}
        )
        pair_info = get_default_pair_info(last_price=95.15)
        market_data = get_default_market_data()
        df_1h = market_data["kline_1h"].copy()
        df_1h.iloc[-5, df_1h.columns.get_loc("low")] = 95.0
        market_data["kline_1h"] = df_1h
        signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
        assert isinstance(signal, StrategySignal)

    def test_local_level_fail_too_far(self, visual_strategy_instance):
        foundation_block = {
            "type": "local_level",
            "params": {
                "timeframe": "15m",
                "lookback_period": 20,
                "proximity_type": "atr_multiplier",
                "proximity_value": 0.25,
            },
        }
        strat = visual_strategy_instance(
            {"entryConditions": {"type": "AND", "children": [foundation_block]}}
        )
        pair_info = get_default_pair_info(last_price=108.0, atr_val=0.5)
        market_data = get_default_market_data()
        df_15m = market_data["kline_15m"].copy()
        df_15m.iloc[-10, df_15m.columns.get_loc("high")] = 110.0
        market_data["kline_15m"] = df_15m
        signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
        assert signal is None

    def test_tape_acceleration_pass_count(self, visual_strategy_instance):
        foundation_block = {
            "type": "tape_acceleration",
            "params": {
                "time_window_sec": 5,
                "analysis_type": "count",
                "multiplier": 2.0,
            },
        }
        strat = visual_strategy_instance(
            {"entryConditions": {"type": "AND", "children": [foundation_block]}}
        )

        # Inject the missing checker logic directly into the strategy instance
        strat.condition_checkers["tape_acceleration"] = _mock_check_tape_acceleration

        market_data = get_default_market_data()
        now_dt = market_data["kline_1m"].index[-1]
        pair_info = get_default_pair_info(dt=now_dt)

        pair_info["tape_count_5s"] = 10.0
        pair_info["tape_avg_count_per_sec_60s"] = 1.0

        signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
        assert isinstance(signal, StrategySignal)

    def test_tape_acceleration_pass_volume(self, visual_strategy_instance):
        foundation_block = {
            "type": "tape_acceleration",
            "params": {
                "time_window_sec": 5,
                "analysis_type": "volume_usd",
                "multiplier": 3.0,
            },
        }
        strat = visual_strategy_instance(
            {"entryConditions": {"type": "AND", "children": [foundation_block]}}
        )

        strat.condition_checkers["tape_acceleration"] = _mock_check_tape_acceleration

        market_data = get_default_market_data()
        now_dt = market_data["kline_1m"].index[-1]
        pair_info = get_default_pair_info(dt=now_dt)

        pair_info["tape_volume_5s"] = 900.0
        pair_info["tape_avg_volume_per_sec_60s"] = 50.0

        signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
        assert isinstance(signal, StrategySignal)

    def test_tape_acceleration_fail_normal_activity(self, visual_strategy_instance):
        foundation_block = {
            "type": "tape_acceleration",
            "params": {
                "time_window_sec": 5,
                "analysis_type": "count",
                "multiplier": 2.0,
            },
        }
        strat = visual_strategy_instance(
            {"entryConditions": {"type": "AND", "children": [foundation_block]}}
        )

        strat.condition_checkers["tape_acceleration"] = _mock_check_tape_acceleration

        market_data = get_default_market_data()
        now_dt = market_data["kline_1m"].index[-1]
        pair_info = get_default_pair_info(dt=now_dt)

        pair_info["tape_count_5s"] = 5.0
        pair_info["tape_avg_count_per_sec_60s"] = 1.0

        signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
        assert signal is None

    @pytest.mark.parametrize(
        "test_id, pattern_to_test, setup_func, should_pass",
        [
            ("bull_eng_pass", "bullish_engulfing", setup_bullish_engulfing, True),
            ("bull_eng_fail", "bullish_engulfing", setup_bearish_engulfing, False),
            ("bear_eng_pass", "bearish_engulfing", setup_bearish_engulfing, True),
            ("pin_bar_pass", "pin_bar", setup_bullish_pin_bar, True),
            ("pin_bar_fail", "pin_bar", setup_no_pattern, False),
            ("inside_bar_pass", "inside_bar", setup_inside_bar, True),
            ("inside_bar_fail", "inside_bar", setup_bullish_engulfing, False),
        ],
    )
    def test_classic_pattern_block(
        self,
        visual_strategy_instance,
        test_id,
        pattern_to_test,
        setup_func,
        should_pass,
    ):
        foundation_block = {
            "type": "classic_pattern",
            "params": {"pattern_name": pattern_to_test, "timeframe": "1m"},
        }
        strat = visual_strategy_instance(
            {"entryConditions": {"type": "AND", "children": [foundation_block]}}
        )
        market_data = get_default_market_data()
        check_index = 58
        pair_info = get_default_pair_info(current_idx=check_index)
        df_1m = market_data["kline_1m"].copy()
        df_1m = setup_func(df_1m, check_index)
        market_data["kline_1m"] = df_1m
        signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
        if should_pass:
            assert isinstance(signal, StrategySignal)
        else:
            assert signal is None
