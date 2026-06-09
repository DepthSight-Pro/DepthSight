# tests/test_strategies.py
import pytest
import time
import random
import math
import pandas as pd
from typing import Dict, Any, List, Tuple
from decimal import ROUND_DOWN
from datetime import datetime, timezone

# --- Imports ---
import bot_module.strategy as strategy_module

try:
    from bot_module.strategy import (
        BaseStrategy,
        StrategySignal,
        SignalDirection,
        STRATEGIES,
        get_strategy_instance,
        VolumeBreakoutStrategy,
        DensityBounceStrategy,
        FakeBreakoutStrategy,
        ConsolidationImpulseStrategy,
        AggTradeReversalStrategy,
        FirstPullbacksInTrendStrategy,
        VisualBuilderStrategy,
        FOUNDATION_MARKET_ACTIVITY,
        FOUNDATION_LEVEL,
        FOUNDATION_PATTERN,
        FOUNDATION_VOLUME_CONFIRMATION,
        FOUNDATION_ORDERBOOK,
        FOUNDATION_TREND,
        FOUNDATION_ROUND_NUMBER,
    )
    import bot_module.config as global_config
    from bot_module.utils import round_price_by_tick
except ImportError as e:
    pytest.skip(
        f"Cannot import bot_module components for strategy tests. Error: {e}",
        allow_module_level=True,
    )

# --- REGISTRATION FOR TESTS ---
test_strategies_map = {
    "VolumeBreakout": VolumeBreakoutStrategy,
    "FakeBreakout": FakeBreakoutStrategy,
    "DensityBounce": DensityBounceStrategy,
    "ConsolidationImpulse": ConsolidationImpulseStrategy,
    "AggTradeReversal": AggTradeReversalStrategy,
    "FirstPullbacksInTrend": FirstPullbacksInTrendStrategy,
    "VisualBuilderStrategy": VisualBuilderStrategy,
}
for name, cls in test_strategies_map.items():
    if name not in STRATEGIES:
        STRATEGIES[name] = cls


# --- set_strategy_defaults fixture ---
@pytest.fixture
def set_strategy_defaults(monkeypatch):
    def _setup_strategy(strategy_instance: BaseStrategy):
        strategy_name = getattr(strategy_instance, "NAME", None)
        if not strategy_name:
            return
        setattr(strategy_instance, "enabled", True)
        # Ensure that weights are configured so that specific logic tests pass,
        # unless the test checks the weights themselves.
        default_weights = {
            FOUNDATION_MARKET_ACTIVITY: 20.0,
            FOUNDATION_LEVEL: 20.0,
            FOUNDATION_PATTERN: 20.0,
            FOUNDATION_VOLUME_CONFIRMATION: 20.0,
            FOUNDATION_ORDERBOOK: 10.0,
            FOUNDATION_TREND: 10.0,
            FOUNDATION_ROUND_NUMBER: 0.0,  # Default is 0, so it doesn't affect if not being tested
            "significant_level": 15.0,  # Adding for VisualBuilder
        }
        monkeypatch.setattr(global_config, "FOUNDATION_WEIGHTS", default_weights)
        monkeypatch.setattr(
            global_config, "MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD", 0.0
        )  # Skip the default weight threshold

    return _setup_strategy


@pytest.fixture
def visual_strategy_instance(monkeypatch):
    from bot_module.strategy import VisualBuilderStrategy

    monkeypatch.setitem(
        strategy_module.STRATEGIES, "VisualBuilderStrategy", VisualBuilderStrategy
    )

    def _create_instance(json_config: Dict[str, Any]):
        if "initialization" not in json_config and "action" not in json_config:
            json_config["initialization"] = {
                "id": "default_act",
                "type": "open_position",
                "params": {"direction": "LONG"},
            }

        instance = strategy_module.create_strategy_instance(
            strategy_name="VisualBuilderStrategy",
            params={"config": json_config, "enabled": True},
        )
        assert instance is not None
        return instance

    return _create_instance


# --- Helpers ---
def make_candle(
    ts: int, o: float, h: float, low: float, c: float, v: float
) -> List[Any]:
    return [int(ts), float(o), float(h), float(low), float(c), float(v)]


def make_trade(
    ts: int, price: float, qty: float, is_buyer_maker: bool
) -> Dict[str, Any]:
    return {
        "T": int(ts),
        "p": str(price),
        "q": str(qty),
        "m": is_buyer_maker,
        "a": random.randint(1, 1_000_000_000),
        "f": 0,
        "l": 0,
    }


def make_depth_data(
    bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]
) -> Dict[str, Any]:
    return {
        "bids": [[f"{float(p):.8f}", f"{float(s):.8f}"] for p, s in bids],
        "asks": [[f"{float(p):.8f}", f"{float(s):.8f}"] for p, s in asks],
        "lastUpdateId": int(time.time() * 1000),
    }


def create_test_kline_df(
    candles_list: List[List[Any]], timeframe_str: str = "1m"
) -> pd.DataFrame:
    if not candles_list:
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"]
        ).set_index(pd.to_datetime([]))
    df = pd.DataFrame(
        candles_list, columns=["open_time", "open", "high", "low", "close", "volume"]
    )
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time")
    numeric_cols = ["open", "high", "low", "close", "volume"]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    df.dropna(subset=numeric_cols, inplace=True)
    if df.empty and candles_list:
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"]
        ).set_index(pd.to_datetime([]))
    return df


def create_test_trades_df(trades_list: List[Dict[str, Any]]) -> pd.DataFrame:
    if not trades_list:
        return pd.DataFrame(columns=["price", "quantity", "is_buyer_maker"]).set_index(
            pd.to_datetime([])
        )
    df = pd.DataFrame(trades_list)
    df.rename(
        columns={
            "a": "agg_trade_id",
            "p": "price",
            "q": "quantity",
            "f": "first_trade_id",
            "l": "last_trade_id",
            "T": "timestamp",
            "m": "is_buyer_maker",
        },
        inplace=True,
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    numeric_cols = ["price", "quantity"]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    df.dropna(subset=numeric_cols, inplace=True)
    if df.empty and trades_list:
        return pd.DataFrame(columns=["price", "quantity", "is_buyer_maker"]).set_index(
            pd.to_datetime([])
        )
    if not df.empty:
        df = df[["price", "quantity", "is_buyer_maker"]]
    df = df.sort_index()
    return df


def get_default_pair_info(
    candle_tf_str: str = "1m",
    last_price=100.0,
    atr_val=1.0,
    tick_size_val=0.01,
    current_idx=59,
) -> Dict[str, Any]:
    return {
        "symbol": "TESTUSDT",
        "natr": 2.0,
        "relative_volume": 3.0,
        "is_volume_spike": True,
        "atr": atr_val,
        "tick_size": tick_size_val,
        "last_price": last_price,
        "current_candle_index": current_idx,
        "candle_timeframe": candle_tf_str,
        "SMA_10": last_price - 0.5 * atr_val,
        "SMA_50": last_price - 1.0 * atr_val,
        "RSI_14": 60,
        "timestamp_dt": datetime.now(timezone.utc),
    }


def get_default_market_data(
    pair_info: Dict[str, Any], num_candles=60
) -> Dict[str, Any]:
    now_ms = int(time.time() * 1000)
    entry_tf_str = pair_info.get("candle_timeframe", "1m")
    last_price_md = pair_info.get("last_price", 100.0)
    atr_val_md = pair_info.get("atr", 1.0)
    candles_list = [
        make_candle(
            now_ms - (num_candles - 1 - i) * 60000,
            last_price_md - 1 + i * 0.02,
            last_price_md + atr_val_md + i * 0.02,
            last_price_md - atr_val_md + i * 0.02,
            last_price_md + i * 0.02,
            100 + i * 20,
        )
        for i in range(num_candles)
    ]
    df_entry = create_test_kline_df(candles_list, entry_tf_str)

    df_1h = (
        df_entry.resample("1h")
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
        if not df_entry.empty
        else pd.DataFrame()
    )
    if df_1h.empty and not df_entry.empty:
        df_1h = df_entry.iloc[[-1]].copy()
        df_1h.index = [df_1h.index[0].replace(minute=0, second=0, microsecond=0)]

    df_4h = (
        df_entry.resample("4h")
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
        if not df_entry.empty
        else pd.DataFrame()
    )
    if df_4h.empty and not df_entry.empty:
        df_4h = df_entry.iloc[[-1]].copy()
        df_4h.index = [
            df_4h.index[0].replace(
                hour=df_4h.index[0].hour // 4 * 4, minute=0, second=0, microsecond=0
            )
        ]

    df_1d = (
        df_entry.resample("1D")
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
        if not df_entry.empty
        else pd.DataFrame()
    )
    if df_1d.empty and not df_entry.empty:
        df_1d = df_entry.iloc[[-1]].copy()
        df_1d.index = [df_1d.index[0].normalize()]

    kline_data = {
        f"kline_{entry_tf_str}": df_entry,
        "kline_1h": df_1h
        if not df_1h.empty
        else df_entry.copy()
        if not df_entry.empty
        else pd.DataFrame(),
        "kline_4h": df_4h
        if not df_4h.empty
        else df_entry.copy()
        if not df_entry.empty
        else pd.DataFrame(),
        "kline_1d": df_1d
        if not df_1d.empty
        else df_entry.copy()
        if not df_entry.empty
        else pd.DataFrame(),
    }
    trend_tf = pair_info.get("trend_timeframe")
    if trend_tf and f"kline_{trend_tf}" not in kline_data and not df_entry.empty:
        resample_rule = trend_tf
        if trend_tf.endswith("m") and trend_tf[:-1].isdigit():
            resample_rule = f"{trend_tf[:-1]}min"
        elif trend_tf.isdigit() and not any(c.isalpha() for c in trend_tf):
            resample_rule = f"{trend_tf}min"
        try:
            df_trend = (
                df_entry.resample(resample_rule)
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
            if df_trend.empty:
                df_trend = df_entry.copy()
        except ValueError:
            df_trend = df_entry.copy()
        kline_data[f"kline_{trend_tf}"] = df_trend

    default_depth = make_depth_data(
        bids=[
            (
                last_price_md - 5 * atr_val_md,
                100000 / (last_price_md - 5 * atr_val_md + 1e-9),
            )
        ],
        asks=[
            (
                last_price_md + 5 * atr_val_md,
                100000 / (last_price_md + 5 * atr_val_md + 1e-9),
            )
        ],
    )

    return {
        **kline_data,
        "depth": default_depth,
        "aggTrade": create_test_trades_df(
            [
                make_trade(
                    int(df_entry.index[-1].timestamp() * 1000 - (60 - k) * 100),
                    last_price_md,
                    1,
                    False,
                )
                for k in range(60)
            ]
        )
        if not df_entry.empty
        else create_test_trades_df([]),
    }


# --- VolumeBreakoutStrategy Tests ---
def test_volume_breakout_no_signal_low_activity(set_strategy_defaults, monkeypatch):
    strat = get_strategy_instance("VolumeBreakout")
    assert strat is not None
    set_strategy_defaults(strat)
    monkeypatch.setattr(global_config, "MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD", 100.0)
    monkeypatch.setattr(
        global_config, "FOUNDATION_WEIGHTS", {FOUNDATION_MARKET_ACTIVITY: 10.0}
    )

    pair_info = get_default_pair_info(strat._get_param("candle_timeframe", "1m"))
    pair_info["relative_volume"] = 0.5
    pair_info["natr"] = 0.5
    market_data = get_default_market_data(pair_info)

    sig, _, _ = strat.check_signal_sync(pair_info, market_data, None)
    assert sig is None, (
        "Signal generated despite low market activity (and high foundation threshold)"
    )


def test_volume_breakout_signal_long(set_strategy_defaults, monkeypatch):
    strat = get_strategy_instance("VolumeBreakout")
    assert strat is not None
    set_strategy_defaults(strat)

    setattr(strat, "retest_atr_percent", 0.0)
    setattr(strat, "stop_loss_atr_multiplier", 1.5)
    setattr(strat, "take_profit_atr_multiplier", 2.0)

    idx_signal_candle = 23
    pair_info = get_default_pair_info(
        strat._get_param("candle_timeframe", "1m"),
        last_price=100.0,
        atr_val=0.5,
        tick_size_val=0.01,
        current_idx=idx_signal_candle,
    )
    market_data = get_default_market_data(pair_info, num_candles=idx_signal_candle + 2)

    candles_df = market_data[f"kline_{pair_info['candle_timeframe']}"].copy()
    idx_prev_candle = idx_signal_candle - 1

    candles_df.iloc[idx_prev_candle, candles_df.columns.get_loc("high")] = 99.0
    candles_df.iloc[idx_signal_candle, candles_df.columns.get_loc("close")] = 100.0

    market_data[f"kline_{pair_info['candle_timeframe']}"] = candles_df
    pair_info["last_price"] = 100.0

    foundations_status, _ = strat.check_foundations(pair_info, market_data)

    assert foundations_status["pattern_detected"] == "VolBreakUp", (
        f"Pattern VolBreakUp not detected, got {foundations_status['pattern_detected']}"
    )
    foundations_status[FOUNDATION_VOLUME_CONFIRMATION] = True
    foundations_status[FOUNDATION_PATTERN] = True

    sig = strat._check_specific_signal_logic(pair_info, market_data, foundations_status)

    assert isinstance(sig, StrategySignal), (
        f"Signal not generated. Foundations used in test: {foundations_status}"
    )
    assert sig.direction == SignalDirection.LONG


# --- DensityBounceStrategy Tests ---
def test_density_bounce_no_signal_max_touches_exceeded(
    set_strategy_defaults, monkeypatch
):
    strat = get_strategy_instance("DensityBounce")
    assert strat is not None
    set_strategy_defaults(strat)
    monkeypatch.setattr(global_config, "MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD", 0.0)
    monkeypatch.setattr(global_config, "DENSITY_NEAR_PROXIMITY_TICKS", 3)

    setattr(strat, "max_touch_count", 1)
    setattr(strat, "min_density_size_usd", 50000)
    setattr(strat, "sl_ticks_multiplier", 5)
    setattr(strat, "tp_ticks_multiplier", 10)

    pair_info = get_default_pair_info(last_price=50.1, tick_size_val=0.1, atr_val=0.2)
    market_data = get_default_market_data(pair_info)

    density_price = 50.0
    density_size_coin = (
        strat._get_param("min_density_size_usd", 50000) / density_price
    ) + 1
    market_data["depth"] = make_depth_data(
        bids=[(density_price, density_size_coin)], asks=[(51.0, 10)]
    )

    sig1, _, _ = strat.check_signal_sync(pair_info, market_data, None)
    assert isinstance(sig1, StrategySignal), (
        "Signal expected on first touch for DensityBounce"
    )

    sig2, _, _ = strat.check_signal_sync(pair_info, market_data, None)
    assert sig2 is None, (
        "Signal generated on second touch when max_touch_count=1 for DensityBounce"
    )


def test_density_bounce_signal_long(set_strategy_defaults, monkeypatch):
    strat = get_strategy_instance("DensityBounce")
    assert strat is not None
    set_strategy_defaults(strat)
    monkeypatch.setattr(global_config, "MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD", 0.0)
    monkeypatch.setattr(global_config, "DENSITY_NEAR_PROXIMITY_TICKS", 3)

    setattr(strat, "max_touch_count", 2)
    setattr(strat, "min_density_size_usd", 50000)
    setattr(strat, "sl_ticks_multiplier", 5)
    setattr(strat, "tp_ticks_multiplier", 10)

    pair_info = get_default_pair_info(last_price=50.1, tick_size_val=0.1, atr_val=0.2)
    market_data = get_default_market_data(pair_info)

    density_price = 50.0
    density_size_coin = (
        strat._get_param("min_density_size_usd", 50000) / density_price
    ) + 1
    market_data["depth"] = make_depth_data(
        bids=[(density_price, density_size_coin)], asks=[(51.0, 10)]
    )

    sig, _, _ = strat.check_signal_sync(pair_info, market_data, None)
    assert isinstance(sig, StrategySignal), (
        f"Signal not generated for DensityBounce LONG. Foundations: {strat.check_foundations(pair_info, market_data)}"
    )


# --- FakeBreakoutStrategy Tests ---
def test_fake_breakout_no_signal_weak_volume_confirmation(
    set_strategy_defaults, monkeypatch
):
    strat = get_strategy_instance("FakeBreakout")
    assert strat is not None
    set_strategy_defaults(strat)
    monkeypatch.setattr(global_config, "MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD", 5.0)
    monkeypatch.setattr(
        global_config,
        "FOUNDATION_WEIGHTS",
        {
            FOUNDATION_MARKET_ACTIVITY: 0.0,
            FOUNDATION_LEVEL: 0.0,
            FOUNDATION_PATTERN: 0.0,
            FOUNDATION_VOLUME_CONFIRMATION: 10.0,
            FOUNDATION_ORDERBOOK: 0.0,
            FOUNDATION_TREND: 0.0,
            FOUNDATION_ROUND_NUMBER: 0.0,
        },
    )

    setattr(strat, "lookback_candles", 5)
    setattr(strat, "reversal_confirmation_bars", 1)

    idx_confirmation_candle = 13
    num_candles_total = idx_confirmation_candle + 2

    pair_info = get_default_pair_info(
        atr_val=1.0, tick_size_val=0.01, current_idx=idx_confirmation_candle
    )
    market_data = get_default_market_data(pair_info, num_candles=num_candles_total)

    candles_df = market_data[f"kline_{pair_info['candle_timeframe']}"].copy()
    level_high = 100.0
    idx_breakout_candle = idx_confirmation_candle - strat._get_param(
        "reversal_confirmation_bars"
    )

    for k_idx in range(
        idx_breakout_candle - strat._get_param("lookback_candles"), idx_breakout_candle
    ):
        candles_df.iloc[k_idx, candles_df.columns.get_loc("high")] = level_high - 0.1

    candles_df.iloc[idx_breakout_candle, candles_df.columns.get_loc("high")] = (
        level_high + 1.0
    )
    candles_df.iloc[idx_breakout_candle, candles_df.columns.get_loc("close")] = (
        level_high - 0.5
    )

    candles_df.iloc[idx_confirmation_candle, candles_df.columns.get_loc("close")] = (
        level_high - 0.7
    )
    candles_df.iloc[idx_confirmation_candle, candles_df.columns.get_loc("volume")] = 10

    market_data[f"kline_{pair_info['candle_timeframe']}"] = candles_df
    market_data["aggTrade"] = create_test_trades_df([])

    sig, _, _ = strat.check_signal_sync(pair_info, market_data, None)
    assert sig is None, "Signal generated with weak volume confirmation"


def test_fake_breakout_signal_short_on_false_breakup(
    set_strategy_defaults, monkeypatch
):
    monkeypatch.setattr(global_config, "ALLOW_SHORT_POSITIONS", True)
    strat = get_strategy_instance("FakeBreakout")
    assert strat is not None
    set_strategy_defaults(strat)

    setattr(strat, "lookback_candles", 5)
    setattr(strat, "reversal_confirmation_bars", 1)
    setattr(strat, "stop_loss_atr_multiplier", 1.2)
    setattr(strat, "take_profit_atr_multiplier", 1.5)

    idx_confirmation_candle = 13
    num_candles_total = idx_confirmation_candle + 2

    pair_info = get_default_pair_info(
        atr_val=2.0, tick_size_val=0.01, current_idx=idx_confirmation_candle
    )
    market_data = get_default_market_data(pair_info, num_candles=num_candles_total)

    candles_df = market_data[f"kline_{pair_info['candle_timeframe']}"].copy()
    level_high = 100.0
    extremum_price_spike = level_high + 1.0
    idx_breakout_candle = idx_confirmation_candle - strat._get_param(
        "reversal_confirmation_bars"
    )

    for k_idx in range(
        idx_breakout_candle - strat._get_param("lookback_candles"), idx_breakout_candle
    ):
        candles_df.iloc[k_idx, candles_df.columns.get_loc("high")] = level_high - 0.1

    candles_df.iloc[idx_breakout_candle, candles_df.columns.get_loc("high")] = (
        extremum_price_spike
    )
    candles_df.iloc[idx_breakout_candle, candles_df.columns.get_loc("close")] = (
        level_high - 0.5
    )

    trigger_price_val = level_high - 0.7
    candles_df.iloc[idx_confirmation_candle, candles_df.columns.get_loc("close")] = (
        trigger_price_val
    )
    avg_vol_lookback = (
        candles_df["volume"]
        .iloc[max(0, idx_confirmation_candle - 20) : idx_confirmation_candle]
        .mean()
    )
    candles_df.iloc[idx_confirmation_candle, candles_df.columns.get_loc("volume")] = (
        avg_vol_lookback * 2.0
    )

    market_data[f"kline_{pair_info['candle_timeframe']}"] = candles_df
    pair_info["last_price"] = trigger_price_val

    confirmation_candle_ts_ms = int(
        candles_df.index[idx_confirmation_candle].timestamp() * 1000
    )
    market_data["aggTrade"] = create_test_trades_df(
        [
            make_trade(confirmation_candle_ts_ms + 10 * k, trigger_price_val, 10, False)
            for k in range(60)
        ]
    )

    foundations_status, _ = strat.check_foundations(pair_info, market_data)

    assert foundations_status["pattern_detected"] == "FakeBreakUp", (
        "Pattern not detected as expected for FakeBreakout"
    )
    foundations_status[FOUNDATION_VOLUME_CONFIRMATION] = True
    foundations_status[FOUNDATION_PATTERN] = True

    sig = strat._check_specific_signal_logic(pair_info, market_data, foundations_status)

    assert isinstance(sig, StrategySignal), (
        f"Signal not generated. Foundations used in test: {foundations_status}"
    )


# --- ConsolidationImpulseStrategy Tests ---
def test_consolidation_impulse_no_signal_wide_range(set_strategy_defaults, monkeypatch):
    strat = get_strategy_instance("ConsolidationImpulse")
    assert strat is not None
    set_strategy_defaults(strat)
    monkeypatch.setattr(global_config, "MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD", 0.0)

    setattr(strat, "range_bars", 10)
    setattr(strat, "max_range_atr_multiplier", 0.5)
    setattr(strat, "entry_delay_bars", 0)

    idx_impulse_candle = 13
    idx_signal_candle = idx_impulse_candle + strat._get_param("entry_delay_bars")
    num_candles_total = idx_signal_candle + 2

    pair_info = get_default_pair_info(atr_val=1.0, current_idx=idx_signal_candle)
    market_data = get_default_market_data(pair_info, num_candles=num_candles_total)

    candles_df = market_data[f"kline_{pair_info['candle_timeframe']}"].copy()
    idx_range_start = idx_impulse_candle - strat._get_param("range_bars")

    for k_idx in range(idx_range_start, idx_impulse_candle):
        candles_df.iloc[k_idx, candles_df.columns.get_loc("high")] = 100.4
        candles_df.iloc[k_idx, candles_df.columns.get_loc("low")] = 99.6
    market_data[f"kline_{pair_info['candle_timeframe']}"] = candles_df

    sig, _, _ = strat.check_signal_sync(pair_info, market_data, None)
    assert sig is None


def test_consolidation_impulse_signal_long(set_strategy_defaults, monkeypatch):
    strat = get_strategy_instance("ConsolidationImpulse")
    assert strat is not None
    set_strategy_defaults(strat)

    setattr(strat, "range_bars", 12)
    setattr(strat, "max_range_atr_multiplier", 1.0)
    setattr(strat, "impulse_volume_multiplier", 1.5)
    setattr(strat, "impulse_candle_min_body_atr", 0.3)
    setattr(strat, "entry_delay_bars", 0)
    setattr(strat, "stop_loss_atr_multiplier", 0.1)

    idx_impulse_candle = 23
    idx_signal_candle = idx_impulse_candle + strat._get_param("entry_delay_bars")
    num_candles_total = idx_signal_candle + 2

    pair_info = get_default_pair_info(
        atr_val=0.5, tick_size_val=0.01, current_idx=idx_signal_candle
    )
    market_data = get_default_market_data(pair_info, num_candles=num_candles_total)

    candles_df = market_data[f"kline_{pair_info['candle_timeframe']}"].copy()
    idx_range_start = idx_impulse_candle - strat._get_param("range_bars")

    consolidation_high = 100.1
    consolidation_low = 99.9
    avg_range_volume_calc = (
        candles_df["volume"].iloc[idx_range_start:idx_impulse_candle].mean()
    )
    if pd.isna(avg_range_volume_calc) or avg_range_volume_calc < 1e-9:
        avg_range_volume_calc = 50.0

    for k_idx in range(idx_range_start, idx_impulse_candle):
        candles_df.iloc[k_idx, candles_df.columns.get_loc("high")] = consolidation_high
        candles_df.iloc[k_idx, candles_df.columns.get_loc("low")] = consolidation_low
        candles_df.iloc[k_idx, candles_df.columns.get_loc("open")] = 100.0
        candles_df.iloc[k_idx, candles_df.columns.get_loc("close")] = 100.0
        candles_df.iloc[k_idx, candles_df.columns.get_loc("volume")] = (
            avg_range_volume_calc
        )

    candles_df.iloc[idx_impulse_candle, candles_df.columns.get_loc("open")] = (
        consolidation_high - 0.05
    )
    candles_df.iloc[idx_impulse_candle, candles_df.columns.get_loc("close")] = (
        consolidation_high + 0.2
    )
    candles_df.iloc[idx_impulse_candle, candles_df.columns.get_loc("high")] = (
        consolidation_high + 0.25
    )
    candles_df.iloc[idx_impulse_candle, candles_df.columns.get_loc("low")] = (
        consolidation_high - 0.06
    )
    candles_df.iloc[idx_impulse_candle, candles_df.columns.get_loc("volume")] = (
        avg_range_volume_calc * (strat._get_param("impulse_volume_multiplier") + 0.1)
    )

    trigger_price_val = candles_df.iloc[idx_signal_candle]["close"]
    market_data[f"kline_{pair_info['candle_timeframe']}"] = candles_df
    pair_info["last_price"] = trigger_price_val

    signal_candle_ts_ms = int(candles_df.index[idx_signal_candle].timestamp() * 1000)
    market_data["aggTrade"] = create_test_trades_df(
        [
            make_trade(signal_candle_ts_ms + 10 * k, trigger_price_val, 10, False)
            for k in range(60)
        ]
    )

    foundations_status, _ = strat.check_foundations(pair_info, market_data)

    assert foundations_status["pattern_detected"] == "ConsImpulseUp", (
        f"Pattern not ConsImpulseUp, got {foundations_status['pattern_detected']}"
    )
    foundations_status[FOUNDATION_VOLUME_CONFIRMATION] = True
    foundations_status[FOUNDATION_PATTERN] = True

    sig = strat._check_specific_signal_logic(pair_info, market_data, foundations_status)

    assert isinstance(sig, StrategySignal), (
        f"Signal not generated. Foundations used in test: {foundations_status}"
    )


# --- AggTradeReversalStrategy Tests ---
def test_agg_trade_reversal_no_signal_without_spike(set_strategy_defaults, monkeypatch):
    strat = get_strategy_instance("AggTradeReversal")
    assert strat is not None
    set_strategy_defaults(strat)
    monkeypatch.setattr(global_config, "MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD", 0.0)

    setattr(strat, "spike_trades_count", 10)
    setattr(strat, "fade_trades_count", 30)
    setattr(strat, "spike_price_deviation_atr", 0.5)

    num_candles = 60
    pair_info = get_default_pair_info(atr_val=1.0, current_idx=num_candles - 1)
    market_data = get_default_market_data(pair_info, num_candles=num_candles)

    now_ms = int(time.time() * 1000)
    required_trades = strat._get_param("spike_trades_count") + strat._get_param(
        "fade_trades_count"
    )
    trades_list = [
        make_trade(now_ms - (required_trades - 1 - i) * 100, 100.0, 5, False)
        for i in range(required_trades)
    ]
    market_data["aggTrade"] = create_test_trades_df(trades_list)

    sig, _, _ = strat.check_signal_sync(pair_info, market_data, None)
    assert sig is None


def test_agg_trade_reversal_signal_short_on_up_spike(
    set_strategy_defaults, monkeypatch
):
    monkeypatch.setattr(global_config, "ALLOW_SHORT_POSITIONS", True)
    strat = get_strategy_instance("AggTradeReversal")
    assert strat is not None
    set_strategy_defaults(strat)

    setattr(strat, "entry_mode", "MARKET")
    setattr(strat, "spike_trades_count", 10)
    setattr(strat, "fade_trades_count", 30)
    setattr(strat, "spike_price_deviation_atr", 0.3)
    setattr(strat, "volume_increase_multiplier", 1.5)
    setattr(strat, "stop_loss_atr_multiplier", 1.0)
    setattr(strat, "take_profit_atr_multiplier", 1.2)

    num_candles = 60
    pair_info = get_default_pair_info(
        atr_val=1.0, tick_size_val=0.01, current_idx=num_candles - 1
    )
    market_data = get_default_market_data(pair_info, num_candles=num_candles)

    now_ms = int(time.time() * 1000)
    spike_trades_n = strat._get_param("spike_trades_count")
    fade_trades_n = strat._get_param("fade_trades_count")

    avg_fade_price = 100.0
    avg_fade_vol_per_trade = 10.0
    trades_list = []
    for i in range(fade_trades_n):
        trades_list.append(
            make_trade(
                now_ms - (spike_trades_n + fade_trades_n - 1 - i) * 100,
                avg_fade_price + random.uniform(-0.05, 0.05),
                avg_fade_vol_per_trade,
                False,
            )
        )

    spike_extremum = avg_fade_price + pair_info["atr"] * (
        strat._get_param("spike_price_deviation_atr") + 0.1
    )
    spike_vol_per_trade = avg_fade_vol_per_trade * (
        strat._get_param("volume_increase_multiplier") + 0.1
    )
    last_spike_price = 0
    for i in range(spike_trades_n):
        current_price = spike_extremum - (spike_trades_n - 1 - i) * 0.01
        if i == spike_trades_n - 1:
            last_spike_price = current_price
        trades_list.append(
            make_trade(
                now_ms - (spike_trades_n - 1 - i) * 100,
                current_price,
                spike_vol_per_trade,
                False,
            )
        )

    market_data["aggTrade"] = create_test_trades_df(trades_list)
    pair_info["last_price"] = last_spike_price

    candles_df_entry = market_data[f"kline_{pair_info['candle_timeframe']}"].copy()
    candles_df_entry.iloc[
        pair_info["current_candle_index"], candles_df_entry.columns.get_loc("volume")
    ] *= 2
    market_data[f"kline_{pair_info['candle_timeframe']}"] = candles_df_entry

    foundations_status, _ = strat.check_foundations(pair_info, market_data)

    assert foundations_status["pattern_detected"] == "AggReversalUpSpike", (
        f"Pattern not AggReversalUpSpike, got {foundations_status['pattern_detected']}"
    )
    foundations_status[FOUNDATION_PATTERN] = True
    foundations_status[FOUNDATION_VOLUME_CONFIRMATION] = True

    sig = strat._check_specific_signal_logic(pair_info, market_data, foundations_status)

    assert isinstance(sig, StrategySignal), (
        f"Signal not generated. Foundations used in test: {foundations_status}"
    )


# --- FirstPullbacksInTrendStrategy Tests ---
def test_first_pullback_no_signal_flat_trend(set_strategy_defaults, monkeypatch):
    strat = get_strategy_instance("FirstPullbacksInTrend")
    assert strat is not None
    set_strategy_defaults(strat)
    monkeypatch.setattr(global_config, "MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD", 0.0)

    trend_tf_name = strat._get_param("trend_timeframe", "5m")
    entry_tf = strat._get_param("entry_timeframe", "1m")

    sma_fast_p = strat._get_param("sma_fast_period", 10)
    sma_slow_p = strat._get_param("sma_slow_period", 50)
    rsi_p = strat._get_param("rsi_period", 14)

    num_candles_entry = max(sma_slow_p, rsi_p) + 5
    pair_info = get_default_pair_info(
        candle_tf_str=entry_tf, current_idx=num_candles_entry - 1
    )
    pair_info["trend_timeframe"] = trend_tf_name
    pair_info[f"SMA_{sma_fast_p}"] = 100.0
    pair_info[f"SMA_{sma_slow_p}"] = 100.0  # FLAT trend
    pair_info[f"RSI_{rsi_p}"] = 50.0

    market_data = get_default_market_data(pair_info, num_candles=num_candles_entry)

    sig, _, _ = strat.check_signal_sync(pair_info, market_data, None)
    assert sig is None


def test_first_pullback_signal_long_sma_pullback(set_strategy_defaults, monkeypatch):
    strat = get_strategy_instance("FirstPullbacksInTrend")
    assert strat is not None
    set_strategy_defaults(strat)

    trend_tf_name = strat._get_param("trend_timeframe", "5m")
    entry_tf = strat._get_param("entry_timeframe", "1m")
    sma_fast_p_trend = strat._get_param("sma_fast_period", 10)
    sma_slow_p_trend = strat._get_param("sma_slow_period", 50)
    rsi_p_trend = strat._get_param("rsi_period", 14)

    setattr(strat, "rsi_lower_bound", 30)
    setattr(strat, "rsi_upper_bound", 70)
    setattr(strat, "pullback_check_mode", "SMA")
    setattr(strat, "pullback_sma_touch_allowance", 0.02)
    setattr(strat, "confirmation_bar_required", True)
    setattr(strat, "stop_loss_atr_multiplier", 1.1)
    setattr(strat, "take_profit_atr_multiplier", 1.5)

    idx_signal_candle = 29
    num_candles_total = idx_signal_candle + 1

    pair_info = get_default_pair_info(
        candle_tf_str=entry_tf,
        atr_val=0.5,
        tick_size_val=0.01,
        current_idx=idx_signal_candle,
    )
    pair_info["trend_timeframe"] = trend_tf_name

    sma_fast_trend_val_for_pullback = 101.0
    pair_info[f"SMA_{sma_fast_p_trend}"] = sma_fast_trend_val_for_pullback
    pair_info[f"SMA_{sma_slow_p_trend}"] = 100.0
    pair_info[f"RSI_{rsi_p_trend}"] = 55.0

    market_data = get_default_market_data(pair_info, num_candles=num_candles_total)

    entry_candles_df = market_data[f"kline_{entry_tf}"].copy()

    entry_candles_df.iloc[
        idx_signal_candle, entry_candles_df.columns.get_loc("low")
    ] = sma_fast_trend_val_for_pullback

    open_price_conf = entry_candles_df.iloc[idx_signal_candle]["low"] + 0.01
    close_price_conf = open_price_conf + 0.02
    entry_candles_df.iloc[
        idx_signal_candle, entry_candles_df.columns.get_loc("open")
    ] = open_price_conf
    entry_candles_df.iloc[
        idx_signal_candle, entry_candles_df.columns.get_loc("close")
    ] = close_price_conf

    avg_vol_lookback = (
        entry_candles_df["volume"]
        .iloc[max(0, idx_signal_candle - 20) : idx_signal_candle]
        .mean()
    )
    entry_candles_df.iloc[
        idx_signal_candle, entry_candles_df.columns.get_loc("volume")
    ] = avg_vol_lookback * 2.0

    sl_base_price_expected = entry_candles_df.iloc[idx_signal_candle]["low"]
    trigger_price_expected = entry_candles_df.iloc[idx_signal_candle]["close"]
    pair_info["last_price"] = trigger_price_expected

    market_data[f"kline_{entry_tf}"] = entry_candles_df
    last_closed_ts_ms = int(
        entry_candles_df.index[idx_signal_candle].timestamp() * 1000
    )
    market_data["aggTrade"] = create_test_trades_df(
        [
            make_trade(last_closed_ts_ms + 10 * k, trigger_price_expected, 10, False)
            for k in range(60)
        ]
    )

    foundations_status, _ = strat.check_foundations(pair_info, market_data)

    assert foundations_status["trend_detected"] == "LONG", (
        f"Trend not LONG, got {foundations_status['trend_detected']}"
    )
    assert foundations_status["pattern_detected"] == "PullbackSmaLong", (
        f"Pattern not PullbackSmaLong, got {foundations_status['pattern_detected']}"
    )
    foundations_status[FOUNDATION_VOLUME_CONFIRMATION] = True
    foundations_status[FOUNDATION_PATTERN] = True

    sig = strat._check_specific_signal_logic(pair_info, market_data, foundations_status)

    assert isinstance(sig, StrategySignal), (
        f"Signal not generated. Foundations used in test: {foundations_status}"
    )
    assert sig.direction == SignalDirection.LONG
    assert sig.trigger_price == trigger_price_expected

    expected_sl_raw = sl_base_price_expected - pair_info["atr"] * strat._get_param(
        "stop_loss_atr_multiplier"
    )
    expected_sl = round_price_by_tick(
        expected_sl_raw, pair_info["tick_size"], ROUND_DOWN
    )
    assert math.isclose(sig.stop_loss, expected_sl, abs_tol=1e-9)


def test_visual_strategy_simple_and_condition_not_met(visual_strategy_instance):
    """
    Test: Verifies that a signal is NOT generated if ONE of the conditions in the 'AND' block is not met.
    """
    test_json_config = {
        "entryConditions": {
            "id": "root",
            "type": "AND",
            "children": [
                {
                    "id": "c1",
                    "type": "market_activity",
                    "params": {"rel_vol_threshold": 2.5, "natr_threshold": 1.5},
                },
                {"id": "c2", "type": "trend_direction", "params": {}},
            ],
        }
    }
    strat = visual_strategy_instance(test_json_config)

    pair_info = get_default_pair_info()
    pair_info["relative_volume"] = 1.0
    pair_info["natr"] = 1.0
    pair_info["is_volume_spike"] = False
    pair_info["SMA_10"] = 100
    pair_info["SMA_50"] = 99

    market_data = get_default_market_data(pair_info)

    signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)

    assert signal is None, (
        "Signal MUST NOT be generated because one of the AND conditions is not met"
    )


@pytest.mark.asyncio
async def test_visual_strategy_or_condition_met(visual_strategy_instance, monkeypatch):
    """
    Test: Verifies that a signal is generated if AT LEAST ONE of the conditions in the 'OR' block is met.
    """
    test_json_config = {
        "entryConditions": {
            "id": "root",
            "type": "OR",
            "children": [
                {
                    "id": "c1",
                    "type": "market_activity",
                    "params": {
                        "rel_vol_threshold": 2.5,
                        "natr_threshold": 1.5,
                        "mode": "relative",
                    },
                },
                {"id": "c2", "type": "significant_level", "params": {}},
            ],
        }
    }
    strat = visual_strategy_instance(test_json_config)

    monkeypatch.setattr(strat, "min_total_foundation_weight_threshold", 0.0)

    pair_info = get_default_pair_info(last_price=104.9, atr_val=1.0)
    pair_info["relative_volume"] = 1.0
    pair_info["natr"] = 1.0
    pair_info["is_volume_spike"] = False

    market_data = get_default_market_data(pair_info)

    now = market_data["kline_1m"].index[-1]
    pair_info["timestamp_dt"] = now

    df_1d = pd.DataFrame(
        {
            "high": [103.0, 105.0, 106.0],
            "low": [100.0, 95.0, 99.0],
            "open": [101.0, 102.0, 103.0],
            "close": [102.0, 103.0, 104.0],
            "volume": [10.0, 10.0, 10.0],
        },
        index=pd.to_datetime(
            [
                now.normalize() - pd.Timedelta(days=2),
                now.normalize() - pd.Timedelta(days=1),
                now.normalize(),
            ],
            utc=True,
        ),
    )
    market_data["kline_1d"] = df_1d

    signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)

    assert isinstance(signal, StrategySignal), (
        "Signal MUST be generated because one of the OR conditions (significant_level) is met"
    )
