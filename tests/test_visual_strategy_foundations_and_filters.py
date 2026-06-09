# File: tests/test_visual_strategy_foundations_and_filters.py

import pytest
import pandas as pd
import numpy as np
from bot_module import strategy as strategy_module
from bot_module.strategy import StrategySignal
from typing import Dict, Any
from datetime import datetime, timezone

# --- Helpers ---


def create_test_kline_df(num_candles=60, base_price=100.0) -> pd.DataFrame:
    """Creates a test candlestick DataFrame."""
    now = pd.Timestamp.now(tz="UTC")
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
    df_1m = create_test_kline_df(num_candles=5000)

    agg_trades_df = pd.DataFrame(
        {
            "price": np.random.uniform(99.9, 100.1, 100),
            "quantity": np.random.uniform(0.1, 1.0, 100),
            "is_buyer_maker": np.random.choice([True, False], 100),
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
        "kline_5m": df_1m.resample("5T").agg(resample_agg).dropna(),
        "kline_15m": df_1m.resample("15T").agg(resample_agg).dropna(),
        "kline_1h": df_1m.resample("1H").agg(resample_agg).dropna(),
        "kline_4h": df_1m.resample("4H").agg(resample_agg).dropna(),
        "kline_1d": df_1m.resample("1D").agg(resample_agg).dropna(),
        "depth_trading": {"bids": [], "asks": []},
        "aggTrade": agg_trades_df,
    }


def get_default_pair_info(
    last_price=100.0, atr_val=1.0, tick_size_val=0.01, current_idx=59, dt=None
) -> Dict[str, Any]:
    """Returns a base dictionary with pair information."""
    return {
        "symbol": "TESTUSDT",
        "natr": 2.0,
        "relative_volume": 3.0,
        "is_volume_spike": True,
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
    """Modifies DataFrame to create a bullish engulfing at index."""
    df.iloc[index - 1, df.columns.get_loc("open")] = 101.0
    df.iloc[index - 1, df.columns.get_loc("close")] = 100.0  # Red candle
    df.iloc[index - 1, df.columns.get_loc("high")] = 101.5
    df.iloc[index - 1, df.columns.get_loc("low")] = 99.5

    df.iloc[index, df.columns.get_loc("open")] = 99.9
    df.iloc[index, df.columns.get_loc("close")] = 101.1  # Green candle engulfs body
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
    from bot_module.strategy import VisualBuilderStrategy

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
            # Add all possible types to avoid KeyError
            "significant_level": 15.0,
            "trend_direction": 10.0,
            "classic_pattern": 10.0,
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
        assert instance is not None, "Failed to create VisualBuilderStrategy instance"
        return instance

    return _create_instance


# --- Tests ---


@pytest.mark.parametrize(
    "test_id, filter_block, pair_info_update, should_pass",
    [
        # --- London Session Tests (07:00-16:00 UTC) ---
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
        # --- New York Session Tests (12:00-21:00 UTC) ---
        (
            "session_new_york_pass_midday",
            {"type": "trading_session", "params": {"session": "new_york"}},
            {"timestamp_dt": datetime(2023, 10, 10, 15, 0, tzinfo=timezone.utc)},
            True,
        ),
        (
            "session_new_york_pass_start",
            {"type": "trading_session", "params": {"session": "new_york"}},
            {"timestamp_dt": datetime(2023, 10, 10, 12, 0, tzinfo=timezone.utc)},
            True,
        ),
        (
            "session_new_york_fail_before",
            {"type": "trading_session", "params": {"session": "new_york"}},
            {"timestamp_dt": datetime(2023, 10, 10, 11, 59, tzinfo=timezone.utc)},
            False,
        ),
        (
            "session_new_york_fail_after",
            {"type": "trading_session", "params": {"session": "new_york"}},
            {"timestamp_dt": datetime(2023, 10, 10, 21, 30, tzinfo=timezone.utc)},
            False,
        ),
        # --- Asia Session Tests (00:00-09:00 UTC) ---
        (
            "session_asia_pass_early",
            {"type": "trading_session", "params": {"session": "asia"}},
            {"timestamp_dt": datetime(2023, 10, 10, 2, 30, tzinfo=timezone.utc)},
            True,
        ),
        (
            "session_asia_pass_start",
            {"type": "trading_session", "params": {"session": "asia"}},
            {"timestamp_dt": datetime(2023, 10, 10, 0, 0, tzinfo=timezone.utc)},
            True,
        ),
        (
            "session_asia_fail_after",
            {"type": "trading_session", "params": {"session": "asia"}},
            {"timestamp_dt": datetime(2023, 10, 10, 10, 0, tzinfo=timezone.utc)},
            False,
        ),
        # --- Sydney Session Tests (21:00-06:00 UTC, crosses midnight) ---
        (
            "session_sydney_pass_night",
            {"type": "trading_session", "params": {"session": "sydney"}},
            {"timestamp_dt": datetime(2023, 10, 10, 23, 0, tzinfo=timezone.utc)},
            True,
        ),
        (
            "session_sydney_pass_early_morning",
            {"type": "trading_session", "params": {"session": "sydney"}},
            {"timestamp_dt": datetime(2023, 10, 10, 3, 0, tzinfo=timezone.utc)},
            True,
        ),
        (
            "session_sydney_fail_daytime",
            {"type": "trading_session", "params": {"session": "sydney"}},
            {"timestamp_dt": datetime(2023, 10, 10, 12, 0, tzinfo=timezone.utc)},
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
    signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
    if should_pass:
        assert isinstance(signal, StrategySignal), (
            f"FAIL [{test_id}]: Signal should have passed the filter."
        )
    else:
        assert signal is None, (
            f"FAIL [{test_id}]: Signal should not have passed the filter."
        )


@pytest.mark.parametrize(
    "test_id, timestamp, should_pass",
    [
        # --- During American session (12:00-21:00 UTC) ---
        (
            "us_or_asia_pass_in_new_york",
            datetime(2023, 10, 10, 15, 0, tzinfo=timezone.utc),
            True,
        ),
        # --- During Asian session (00:00-09:00 UTC) ---
        (
            "us_or_asia_pass_in_asia",
            datetime(2023, 10, 10, 3, 0, tzinfo=timezone.utc),
            True,
        ),
        # --- Between sessions (09:00-12:00 UTC - gap between Asia and America) ---
        (
            "us_or_asia_fail_gap",
            datetime(2023, 10, 10, 10, 30, tzinfo=timezone.utc),
            False,
        ),
        # --- During London session, but NOT in US and NOT in Asia (09:30 UTC - after Asia, before America) ---
        (
            "us_or_asia_fail_between_sessions",
            datetime(2023, 10, 10, 9, 30, tzinfo=timezone.utc),
            False,
        ),
    ],
)
def test_combined_sessions_or_filter(
    visual_strategy_instance, test_id, timestamp, should_pass
):
    """
    Tests user scenario: trade only during American OR Asian session.
    Configuration: filters.type = OR with two children - new_york and asia.
    """
    test_json_config = {
        "filters": {
            "id": "f_root",
            "type": "OR",
            "children": [
                {
                    "id": "f_us",
                    "type": "trading_session",
                    "params": {"session": "new_york"},
                },
                {
                    "id": "f_asia",
                    "type": "trading_session",
                    "params": {"session": "asia"},
                },
            ],
        },
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
    pair_info = get_default_pair_info(dt=timestamp)
    market_data = get_default_market_data()
    signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
    if should_pass:
        assert isinstance(signal, StrategySignal), (
            f"FAIL [{test_id}]: Signal should have passed the OR filter (US or Asia)."
        )
    else:
        assert signal is None, (
            f"FAIL [{test_id}]: Signal should not have passed - time is outside both sessions."
        )


@pytest.mark.parametrize(
    "test_id, foundation_block, pair_info_update, market_data_update, should_pass",
    [
        (
            "activity_pass",
            {
                "type": "market_activity",
                "params": {
                    "rel_vol_threshold": 2.5,
                    "natr_threshold": 1.5,
                    "mode": "relative",
                },
            },
            {"relative_volume": 3.0, "natr": 2.0},
            None,
            True,
        ),
        (
            "activity_fail",
            {
                "type": "market_activity",
                "params": {
                    "rel_vol_threshold": 2.5,
                    "natr_threshold": 1.5,
                    "mode": "relative",
                },
            },
            {"relative_volume": 2.0, "natr": 1.0, "is_volume_spike": False},
            None,
            False,
        ),
        (
            "trend_pass",
            {"type": "trend_direction", "params": {"required_trend": "LONG"}},
            {"SMA_10": 101, "SMA_50": 100, "RSI_14": 55},
            None,
            True,
        ),
        (
            "trend_fail",
            {"type": "trend_direction", "params": {"required_trend": "LONG"}},
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
            {"kline_1m": {"index": 59, "column": "volume", "value": 10000}},
            True,
        ),
        (
            "volume_fail",
            {"type": "volume_confirmation", "params": {}},
            {},
            {"kline_1m": {"index": 59, "column": "volume", "value": 0.1}},
            False,
        ),
        (
            "sig_level_pass",
            {"type": "significant_level", "params": {}},
            {"last_price": 101.9, "atr": 0.5},
            {"kline_1d": {"index": -2, "column": "high", "value": 102.0}},
            True,
        ),
        (
            "sig_level_fail",
            {"type": "significant_level", "params": {}},
            {"last_price": 105.0, "atr": 0.5},
            {"kline_1d": {"index": -2, "column": "high", "value": 102.0}},
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

    current_idx_for_test = (
        len(market_data["kline_1m"]) - 25
    )  # Take the index with a margin

    current_dt = market_data["kline_1m"].index[current_idx_for_test]
    pair_info = get_default_pair_info(current_idx=current_idx_for_test, dt=current_dt)

    pair_info.update(pair_info_update)

    if market_data_update and "kline_1m" in market_data_update:
        update_info = market_data_update["kline_1m"]
        update_idx = current_idx_for_test
        avg_vol = (
            market_data["kline_1m"]["volume"].iloc[update_idx - 20 : update_idx].mean()
        )
        market_data["kline_1m"].iloc[
            update_idx, market_data["kline_1m"].columns.get_loc("volume")
        ] = update_info["value"] * avg_vol

    if test_id == "volume_fail":
        market_data["aggTrade"] = pd.DataFrame()

    if market_data_update and "kline_1d" in market_data_update:
        df_1d = market_data["kline_1d"].copy()
        if len(df_1d) > 2:
            update_info = market_data_update["kline_1d"]
            df_1d.iloc[
                update_info["index"], df_1d.columns.get_loc(update_info["column"])
            ] = update_info["value"]
            market_data["kline_1d"] = df_1d
        else:
            pytest.skip("Not enough 1d data for sig_level test.")

    signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)

    if should_pass:
        assert isinstance(signal, StrategySignal), (
            f"FAIL [{test_id}]: Signal should have been generated."
        )
    else:
        assert signal is None, (
            f"FAIL [{test_id}]: Signal should not have been generated."
        )


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

    signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)

    if should_pass:
        assert isinstance(signal, StrategySignal), (
            f"FAIL [{test_id}]: Signal should have been generated."
        )
    else:
        assert signal is None, (
            f"FAIL [{test_id}]: Signal should not have been generated."
        )


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

    signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)

    assert isinstance(signal, StrategySignal), (
        "Signal was not generated, although all conditions should have passed."
    )
    expected_sl = 96.00
    expected_tp = 112.00
    assert signal.direction == strategy_module.SignalDirection.LONG
    assert signal.stop_loss == pytest.approx(expected_sl)
    assert signal.take_profit == pytest.approx(expected_tp)


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
                        "params": {
                            "rel_vol_threshold": 1.5,
                            "natr_threshold": 1.5,
                            "mode": "relative",
                        },
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
                        "params": {
                            "rel_vol_threshold": 2.5,
                            "natr_threshold": 1.5,
                            "mode": "relative",
                        },
                    },
                    {"type": "trend_direction", "params": {}},
                ],
            },
            {
                "relative_volume": 2.0,
                "natr": 1.0,
                "is_volume_spike": False,
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
                        "params": {
                            "rel_vol_threshold": 2.5,
                            "natr_threshold": 1.5,
                            "mode": "relative",
                        },
                    },
                    {"type": "trend_direction", "params": {}},
                ],
            },
            {
                "relative_volume": 2.0,
                "natr": 1.0,
                "is_volume_spike": False,
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
        assert isinstance(signal, StrategySignal), (
            f"FAIL [{test_id}]: Signal should have been generated."
        )
    else:
        assert signal is None, (
            f"FAIL [{test_id}]: Signal should not have been generated."
        )


def test_missing_data_handling(visual_strategy_instance):
    test_json_config = {
        "filters": {"id": "f_root", "type": "AND", "children": []},
        "entryConditions": {
            "id": "e_root",
            "type": "AND",
            "children": [
                {
                    "type": "market_activity",
                    "params": {
                        "rel_vol_threshold": 1.5,
                        "natr_threshold": 1.5,
                        "mode": "relative",
                    },
                }
            ],
        },
    }
    strat = visual_strategy_instance(test_json_config)

    pair_info = get_default_pair_info()
    del pair_info["relative_volume"]
    pair_info["natr"] = 1.0
    pair_info["is_volume_spike"] = False

    market_data = get_default_market_data()

    signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)

    assert signal is None, (
        "Strategy should return None when data is missing, instead of crashing with an error."
    )


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

        market_data = get_default_market_data()
        current_idx = len(market_data["kline_1m"]) - 50
        pair_info = get_default_pair_info(
            last_price=109.9, atr_val=0.5, current_idx=current_idx
        )

        df_15m = market_data["kline_15m"].copy()
        current_ts = market_data["kline_1m"].index[pair_info["current_candle_index"]]
        idx_15m = df_15m.index.get_indexer([current_ts], method="ffill")[0]
        if idx_15m > 10:
            df_15m.iloc[idx_15m - 10, df_15m.columns.get_loc("high")] = 110.0
        else:
            pytest.skip("Not enough 15m data to set level")

        market_data["kline_15m"] = df_15m

        signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
        assert isinstance(signal, StrategySignal), (
            "Signal should have triggered due to proximity to local high (ATR)"
        )

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

        market_data = get_default_market_data()
        current_idx = len(market_data["kline_1m"]) - 100
        pair_info = get_default_pair_info(last_price=95.15, current_idx=current_idx)

        df_1h = market_data["kline_1h"].copy()
        current_ts = market_data["kline_1m"].index[pair_info["current_candle_index"]]
        idx_1h = df_1h.index.get_indexer([current_ts], method="ffill")[0]
        if idx_1h > 5:
            df_1h.iloc[idx_1h - 5, df_1h.columns.get_loc("low")] = 95.0
        else:
            pytest.skip("Not enough 1h data to set level")
        market_data["kline_1h"] = df_1h

        signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
        assert isinstance(signal, StrategySignal), (
            "Signal should have triggered due to proximity to local low (%)"
        )

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

        market_data = get_default_market_data()
        current_idx = len(market_data["kline_1m"]) - 50
        pair_info = get_default_pair_info(
            last_price=108.0, atr_val=0.5, current_idx=current_idx
        )
        df_15m = market_data["kline_15m"].copy()
        current_ts = market_data["kline_1m"].index[pair_info["current_candle_index"]]
        idx_15m = df_15m.index.get_indexer([current_ts], method="ffill")[0]
        if idx_15m > 10:
            df_15m.iloc[idx_15m - 10, df_15m.columns.get_loc("high")] = 110.0
        else:
            pytest.skip("Not enough 15m data to set level")

        market_data["kline_15m"] = df_15m

        signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
        assert signal is None, (
            "Signal should not have triggered, price is far from level"
        )

    def test_tape_acceleration_pass_count(self, visual_strategy_instance):
        # Simulate "acceleration" by comparing current value with averaged * multiplier
        foundation_block = {
            "type": "value_comparison",
            "params": {
                "leftOperand": {"source": "indicator", "key": "tape_count_5s"},
                "operator": "gte",
                "rightOperand": {
                    "source": "value",
                    "value": 10.0,
                },  # Just checking the value for the test
            },
        }
        strat = visual_strategy_instance(
            {"entryConditions": {"type": "AND", "children": [foundation_block]}}
        )

        market_data = get_default_market_data()
        now_dt = market_data["kline_1m"].index[-1]
        pair_info = get_default_pair_info(dt=now_dt)

        pair_info["tape_count_5s"] = 10.0

        signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
        assert isinstance(signal, StrategySignal), (
            "Signal should have triggered (value_comparison)"
        )

    def test_tape_acceleration_pass_volume(self, visual_strategy_instance):
        foundation_block = {
            "type": "value_comparison",
            "params": {
                "leftOperand": {"source": "indicator", "key": "tape_volume_5s"},
                "operator": "gte",
                "rightOperand": {"source": "value", "value": 900.0},
            },
        }
        strat = visual_strategy_instance(
            {"entryConditions": {"type": "AND", "children": [foundation_block]}}
        )

        market_data = get_default_market_data()
        now_dt = market_data["kline_1m"].index[-1]
        pair_info = get_default_pair_info(dt=now_dt)

        pair_info["tape_volume_5s"] = 900.0

        signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
        assert isinstance(signal, StrategySignal), "Signal should have triggered"

    def test_tape_acceleration_fail_normal_activity(self, visual_strategy_instance):
        foundation_block = {
            "type": "value_comparison",
            "params": {
                "leftOperand": {"source": "indicator", "key": "tape_count_5s"},
                "operator": "gte",
                "rightOperand": {"source": "value", "value": 10.0},
            },
        }
        strat = visual_strategy_instance(
            {"entryConditions": {"type": "AND", "children": [foundation_block]}}
        )

        market_data = get_default_market_data()
        now_dt = market_data["kline_1m"].index[-1]
        pair_info = get_default_pair_info(dt=now_dt)

        pair_info["tape_count_5s"] = 5.0  # 5 < 10

        signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)
        assert signal is None, "Signal should not have triggered"

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
            assert isinstance(signal, StrategySignal), (
                f"FAIL [{test_id}]: Signal should have triggered for pattern '{pattern_to_test}'"
            )
        else:
            assert signal is None, (
                f"FAIL [{test_id}]: Signal should NOT have triggered for pattern '{pattern_to_test}'"
            )
