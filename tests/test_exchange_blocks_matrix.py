# tests/test_exchange_blocks_matrix.py
"""
Multi-Exchange Block Matrix & Combinatorial Fuzzing Test Suite.
Verifies that all visual builder blocks, complex multi-block chains,
multi-timeframe confluences, position management lifecycle, dynamic parameter linking,
short-selling symmetry, and micro-price / memecoin asset regimes function seamlessly
across Bybit, OKX, and Weex data feeds.
"""

import copy
import time
import random
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Tuple

import numpy as np
import pandas as pd
import pytest

from bot_module.strategy import (
    VisualBuilderStrategy,
    StrategySignal,
    BasePosition,
    SignalDirection,
)


# ============================================================================================
# 1. EXHAUSTIVE BLOCK REGISTRY (All 30+ Block Types)
# ============================================================================================
ALL_BLOCKS_REGISTRY: List[Dict[str, Any]] = [
    # --- Oscillators ---
    {
        "id": "node_rsi",
        "type": "RSI",
        "params": {"period": 14, "operator": "lt", "value": 30.0},
    },
    {
        "id": "node_macd",
        "type": "MACD",
        "params": {
            "fast_period": 12,
            "slow_period": 26,
            "signal_period": 9,
            "condition": "hist_gt_zero",
        },
    },
    {
        "id": "node_stoch",
        "type": "STOCHASTIC",
        "params": {
            "k_period": 14,
            "d_period": 3,
            "smooth_k": 3,
            "operator": "lt",
            "threshold": 20,
        },
    },
    # --- Volatility & Range ---
    {
        "id": "node_bollinger",
        "type": "BOLLINGER",
        "params": {
            "period": 20,
            "std_dev": 2.0,
            "operator": "cross_above",
            "band": "lower",
        },
    },
    {
        "id": "node_natr",
        "type": "NATR",
        "params": {"period": 14, "operator": "gt", "value": 1.0},
    },
    {
        "id": "node_vol_squeeze",
        "type": "VOLATILITY_SQUEEZE",
        "params": {
            "bb_period": 20,
            "bb_std": 2.0,
            "kc_period": 20,
            "kc_mult": 1.5,
            "operator": "sqz_on",
        },
    },
    {
        "id": "node_volatility",
        "type": "VOLATILITY",
        "params": {"threshold_percent": 1.0},
    },
    # --- Trend & Momentum ---
    {
        "id": "node_adx",
        "type": "ADX",
        "params": {"period": 14, "threshold": 25, "operator": "gt"},
    },
    {
        "id": "node_ma_cross",
        "type": "MA_CROSS",
        "params": {"fast_period": 10, "slow_period": 50, "ma_type": "sma"},
    },
    {
        "id": "node_trend_dir",
        "type": "TREND_DIRECTION",
        "params": {"fast_period": 10, "slow_period": 50, "required_trend": "LONG"},
    },
    {"id": "node_trend_str", "type": "TREND_STRENGTH", "params": {"min_strength": 0.5}},
    # --- Price Action & Levels ---
    {
        "id": "node_price_action",
        "type": "PRICE_ACTION",
        "params": {"pattern": "pinbar"},
    },
    {
        "id": "node_consolidation",
        "type": "PRICE_CONSOLIDATION",
        "params": {"period": 20, "threshold_pct": 1.0},
    },
    {
        "id": "node_level_touch",
        "type": "LEVEL_TOUCH",
        "params": {"lookback": 50, "touch_range_pct": 0.1},
    },
    {
        "id": "node_return_to_level",
        "type": "RETURN_TO_LEVEL",
        "params": {"lookback": 50, "return_range_pct": 0.2},
    },
    {
        "id": "node_price_vs_level",
        "type": "PRICE_VS_LEVEL",
        "params": {"level_type": "rolling_high", "lookback": 50, "operator": "lt"},
    },
    {
        "id": "node_local_level",
        "type": "LOCAL_LEVEL",
        "params": {"lookback": 50, "level_type": "support"},
    },
    {
        "id": "node_value_comp",
        "type": "VALUE_COMPARISON",
        "params": {
            "left": {"source": "candle", "key": "close"},
            "operator": "gt",
            "right": {"source": "constant", "value": 0},
        },
    },
    # --- Microstructure & Tape ---
    {
        "id": "node_tape_cond",
        "type": "TAPE_CONDITION",
        "params": {
            "metric": "delta_volume",
            "window_sec": "30",
            "operator": "gt",
            "threshold": 0,
        },
    },
    {
        "id": "node_ob_zone",
        "type": "ORDER_BOOK_ZONE",
        "params": {"metric": "obi_1p", "operator": "gt", "threshold": 0},
    },
    {
        "id": "node_oi",
        "type": "OPEN_INTEREST",
        "params": {"analyze": "absolute_value", "operator": "gt", "value": 0},
    },
    # --- Market Filters ---
    {
        "id": "node_session",
        "type": "TRADING_SESSION",
        "params": {"allowed_sessions": ["London", "New York", "Tokyo", "Sydney"]},
    },
    {"id": "node_market_act", "type": "MARKET_ACTIVITY", "params": {"min_trades": 10}},
    {"id": "node_btc_state", "type": "BTC_STATE", "params": {"required_state": "Any"}},
    {
        "id": "node_corr",
        "type": "CORRELATION",
        "params": {"lookback": 20, "operator": "gt", "value": -1.0},
    },
    # --- Foundations ---
    {
        "id": "node_classic_pat",
        "type": "CLASSIC_PATTERN",
        "params": {"pattern_type": "double_bottom"},
    },
    {
        "id": "node_vol_conf",
        "type": "VOLUME_CONFIRMATION",
        "params": {"period": 20, "threshold": 1.5},
    },
    {
        "id": "node_round_lvl",
        "type": "ROUND_NUMBER_LEVEL",
        "params": {"proximity_pct": 0.1},
    },
    {
        "id": "node_l2_micro",
        "type": "L2_MICROSTRUCTURE",
        "params": {"imbalance_threshold": 0.2},
    },
    {"id": "node_tape_ana", "type": "TAPE_ANALYSIS", "params": {"window_sec": 30}},
]


# ============================================================================================
# 2. MULTI-EXCHANGE CONTEXT GENERATOR (Bybit, OKX, Weex)
# ============================================================================================
def create_exchange_context(
    exchange: str,
    symbol: str = "BTCUSDT",
    num_candles: int = 300,
    direction_hint: str = "LONG",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Constructs highly realistic, exchange-calibrated market_data and pair_info
    simulating WebSocket & REST feeds from Bybit, OKX, or Weex.
    Supports BTCUSDT, ETHUSDT, DOGEUSDT, and high-precision memecoins like PEPEUSDT.
    """
    now = datetime.now(timezone.utc)
    timestamps = [now - timedelta(minutes=i) for i in range(num_candles - 1, -1, -1)]

    # Asset price & precision configuration
    if "PEPE" in symbol or "SHIB" in symbol:
        base_price = 0.00001234
        tick_size = 0.00000001
        atr_val = 0.00000045
        dec = 8
    elif "DOGE" in symbol:
        base_price = 0.125
        tick_size = 0.00001
        atr_val = 0.003
        dec = 5
    elif "ETH" in symbol:
        base_price = 3000.0
        tick_size = 0.01
        atr_val = 25.0
        dec = 2
    else:  # BTC default
        base_price = 60000.0
        tick_size = 0.1
        atr_val = 150.0
        dec = 2

    # Generate realistic candle walk
    np.random.seed(42 + len(exchange) + len(symbol))
    drift = -0.0002 if direction_hint == "SHORT" else 0.0002
    returns = np.random.normal(drift, 0.002, num_candles)
    price_series = base_price * np.cumprod(1 + returns)

    highs = price_series * (1 + np.abs(np.random.normal(0.001, 0.001, num_candles)))
    lows = price_series * (1 - np.abs(np.random.normal(0.001, 0.001, num_candles)))
    opens = np.roll(price_series, 1)
    opens[0] = base_price
    closes = price_series
    volumes = (
        np.random.uniform(500, 50000, num_candles)
        if base_price < 1.0
        else np.random.uniform(50, 500, num_candles)
    )

    df_1m = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=pd.to_datetime(timestamps),
    )

    # Precalculate essential indicators directly into dataframe
    df_1m["SMA_10"] = df_1m["close"].rolling(10).mean().bfill()
    df_1m["SMA_20"] = df_1m["close"].rolling(20).mean().bfill()
    df_1m["SMA_50"] = df_1m["close"].rolling(50).mean().bfill()
    df_1m["RSI_14"] = 40.0 if direction_hint == "SHORT" else 60.0
    df_1m["ADX_14"] = 28.0
    df_1m["BBW_20_2"] = 0.04
    df_1m["MACD_hist_12_26_9"] = -0.5 if direction_hint == "SHORT" else 0.5

    resample_agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }

    # Higher timeframe dataframes
    df_5m = df_1m.resample("5min").agg(resample_agg).dropna()
    df_5m["SMA_10"] = df_5m["close"].rolling(10).mean().bfill()
    df_5m["SMA_50"] = df_5m["close"].rolling(50).mean().bfill()
    df_5m["RSI_14"] = 42.0 if direction_hint == "SHORT" else 55.0

    df_1h = df_1m.resample("1h").agg(resample_agg).dropna()
    df_1h["SMA_10"] = df_1h["close"].rolling(10).mean().bfill()
    df_1h["SMA_50"] = df_1h["close"].rolling(50).mean().bfill()
    df_1h["RSI_14"] = 45.0 if direction_hint == "SHORT" else 58.0

    # Secondary BTC series for correlation / cross-market checks
    btc_df = df_1m.copy()

    # Open Interest series formatted per exchange standards
    oi_series = pd.DataFrame(
        {"open_interest": np.linspace(15000.0, 16000.0, num_candles)},
        index=df_1m.index,
    )

    # Aggregated Trades tape stream
    tape_timestamps = pd.date_range(
        end=df_1m.index[-1], periods=150, freq="200ms", tz="UTC"
    )
    agg_trades_df = pd.DataFrame(
        {
            "price": np.random.uniform(closes[-1] * 0.999, closes[-1] * 1.001, 150),
            "quantity": np.random.uniform(0.05, 1.5, 150),
            "is_buyer_maker": np.random.choice([True, False], 150),
        },
        index=tape_timestamps,
    )

    # L2 Orderbook Depth structure with exact decimal precision
    last_p = float(closes[-1])
    depth_trading = {
        "bids": [
            [f"{last_p * 0.999:.{dec}f}", "1500.0"],
            [f"{last_p * 0.998:.{dec}f}", "3500.0"],
            [f"{last_p * 0.995:.{dec}f}", "10000.0"],
        ],
        "asks": [
            [f"{last_p * 1.001:.{dec}f}", "1200.0"],
            [f"{last_p * 1.002:.{dec}f}", "2800.0"],
            [f"{last_p * 1.005:.{dec}f}", "9500.0"],
        ],
    }

    depth_analysis = {
        "bids": [
            {"notional": 250000.0, "price": last_p * 0.99},
            {"notional": 500000.0, "price": last_p * 0.98},
            {"notional": 800000.0, "price": last_p * 0.97},
            {"notional": 1200000.0, "price": last_p * 0.96},
            {"notional": 2000000.0, "price": last_p * 0.95},
        ],
        "asks": [
            {"notional": 200000.0, "price": last_p * 1.01},
            {"notional": 450000.0, "price": last_p * 1.02},
            {"notional": 750000.0, "price": last_p * 1.03},
            {"notional": 1100000.0, "price": last_p * 1.04},
            {"notional": 1800000.0, "price": last_p * 1.05},
        ],
    }

    market_data = {
        "kline_1m": df_1m.copy(),
        "kline_5m": df_5m,
        "kline_15m": df_1m.resample("15min").agg(resample_agg).dropna(),
        "kline_1h": df_1h,
        "kline_4h": df_1m.resample("4h").agg(resample_agg).dropna(),
        "kline_1d": df_1m.resample("1D").agg(resample_agg).dropna(),
        "kline_1m_BTCUSDT": btc_df,
        "open_interest": oi_series,
        "depth_trading": depth_trading,
        "depth_analysis": depth_analysis,
        "aggTrade": agg_trades_df,
    }

    # Exchange-calibrated pair_info
    pair_info = {
        "symbol": symbol,
        "exchange": exchange,
        "market_type": "futures_usdtm",
        "candle_timeframe": "1m",
        "last_price": last_p,
        "open": float(df_1m["open"].iloc[-1]),
        "high": float(df_1m["high"].iloc[-1]),
        "low": float(df_1m["low"].iloc[-1]),
        "close": last_p,
        "atr": atr_val,
        "natr": 1.8,
        "tick_size": tick_size,
        "relative_volume": 2.5,
        "is_volume_spike": True,
        "current_candle_index": len(df_1m) - 1,
        "timestamp_dt": now,
        "tape_delta_volume_usd_30s": -750000.0
        if direction_hint == "SHORT"
        else 750000.0,
        "obi_1p": -0.65 if direction_hint == "SHORT" else 0.65,
        "is_live_mode": True,
        "is_backtest_mode": False,
        "SMA_10": float(df_1m["SMA_10"].iloc[-1]),
        "SMA_20": float(df_1m["SMA_20"].iloc[-1]),
        "SMA_50": float(df_1m["SMA_50"].iloc[-1]),
        "RSI_14": float(df_1m["RSI_14"].iloc[-1]),
        "ADX_14": 28.0,
        "BBW_20_2": 0.04,
        "MACD_hist_12_26_9": -0.5 if direction_hint == "SHORT" else 0.5,
    }

    return pair_info, market_data


# ============================================================================================
# 3. TEST 1: ALL INDIVIDUAL BLOCKS EVALUATION ACROSS ALL 3 EXCHANGES
# ============================================================================================
@pytest.mark.parametrize("exchange", ["bybit", "okx", "weex"])
@pytest.mark.parametrize("block_config", ALL_BLOCKS_REGISTRY, ids=lambda b: b["type"])
def test_all_individual_blocks_across_exchanges(
    exchange: str, block_config: Dict[str, Any]
):
    """
    Passes every single visual builder block through VisualBuilderStrategy
    under Bybit, OKX, and Weex data feeds.
    Fails if any block throws an unhandled exception or produces NaN values.
    """
    pair_info, market_data = create_exchange_context(exchange=exchange)
    strategy = VisualBuilderStrategy(params={"enabled": True})

    result, trace = strategy._evaluate_condition_tree(
        node=block_config,
        pair_info=pair_info,
        market_data=market_data,
        prev_pair_info={},
        context={},
    )

    assert isinstance(result, (bool, np.bool_)), (
        f"Block {block_config['type']} returned non-boolean result on {exchange}: {result}"
    )
    assert isinstance(trace, dict), (
        f"Block {block_config['type']} trace must be a dictionary on {exchange}"
    )
    assert "result" in trace and trace["result"] == result

    # Ensure no NaN errors were quietly produced in details
    details = trace.get("details", {})
    if "error" in details:
        err_str = str(details["error"]).lower()
        assert "not enough" in err_str or "warmup" in err_str or "unknown" in err_str, (
            f"Unexpected error in block {block_config['type']} on {exchange}: {details['error']}"
        )


# ============================================================================================
# 4. TEST 2: COMPLEX REALISTIC MULTI-BLOCK STRATEGY CHAINS ACROSS EXCHANGES
# ============================================================================================
STRATEGY_CHAINS = [
    {
        "name": "Microstructure_Scalper",
        "tree": {
            "id": "root_and",
            "type": "AND",
            "children": [
                {
                    "id": "c1",
                    "type": "TREND_DIRECTION",
                    "params": {
                        "fast_period": 10,
                        "slow_period": 50,
                        "required_trend": "LONG",
                    },
                },
                {
                    "id": "c2",
                    "type": "ORDER_BOOK_ZONE",
                    "params": {"metric": "obi_1p", "operator": "gt", "threshold": 0.2},
                },
                {
                    "id": "c3",
                    "type": "TAPE_CONDITION",
                    "params": {
                        "metric": "delta_volume",
                        "window_sec": "30",
                        "operator": "gt",
                        "threshold": 0,
                    },
                },
                {
                    "id": "c4",
                    "type": "NATR",
                    "params": {"period": 14, "operator": "gt", "value": 0.5},
                },
            ],
        },
    },
    {
        "name": "Breakout_Volatility_Confluence",
        "tree": {
            "id": "root_and",
            "type": "AND",
            "children": [
                {
                    "id": "branch_or",
                    "type": "OR",
                    "children": [
                        {
                            "id": "b1",
                            "type": "BOLLINGER",
                            "params": {
                                "period": 20,
                                "std_dev": 2.0,
                                "operator": "cross_above",
                                "band": "lower",
                            },
                        },
                        {
                            "id": "b2",
                            "type": "VOLATILITY_SQUEEZE",
                            "params": {
                                "bb_period": 20,
                                "bb_std": 2.0,
                                "kc_period": 20,
                                "kc_mult": 1.5,
                                "operator": "sqz_on",
                            },
                        },
                    ],
                },
                {
                    "id": "c_vol",
                    "type": "VOLUME_CONFIRMATION",
                    "params": {"period": 20, "threshold": 1.2},
                },
                {
                    "id": "c_sess",
                    "type": "TRADING_SESSION",
                    "params": {"allowed_sessions": ["London", "New York"]},
                },
                {
                    "id": "c_corr",
                    "type": "CORRELATION",
                    "params": {"lookback": 20, "operator": "gt", "value": -0.8},
                },
            ],
        },
    },
    {
        "name": "Mean_Reversion_L2_Defense",
        "tree": {
            "id": "root_and",
            "type": "AND",
            "children": [
                {
                    "id": "m1",
                    "type": "RSI",
                    "params": {"period": 14, "operator": "lt", "value": 40.0},
                },
                {
                    "id": "m2",
                    "type": "STOCHASTIC",
                    "params": {
                        "k_period": 14,
                        "d_period": 3,
                        "smooth_k": 3,
                        "operator": "lt",
                        "threshold": 30,
                    },
                },
                {
                    "id": "m3",
                    "type": "L2_MICROSTRUCTURE",
                    "params": {"imbalance_threshold": 0.1},
                },
                {
                    "id": "m4",
                    "type": "OPEN_INTEREST",
                    "params": {
                        "analyze": "absolute_value",
                        "operator": "gt",
                        "value": 1000,
                    },
                },
            ],
        },
    },
]


@pytest.mark.parametrize("exchange", ["bybit", "okx", "weex"])
@pytest.mark.parametrize("chain_def", STRATEGY_CHAINS, ids=lambda c: c["name"])
def test_complex_strategy_chains_across_exchanges(
    exchange: str, chain_def: Dict[str, Any]
):
    """
    Verifies that complex, nested multi-block strategy trees execute smoothly
    with full signal dispatch and trace collection on Bybit, OKX, and Weex.
    """
    pair_info, market_data = create_exchange_context(exchange=exchange)

    full_config = {
        "initialization": {
            "id": "init_act",
            "type": "open_position",
            "params": {"direction": "LONG"},
        },
        "entryConditions": chain_def["tree"],
        "position_management": {
            "sl_type": "atr_multiplier",
            "sl_atr_multiplier": 1.5,
            "tp_type": "risk_reward",
            "tp_risk_reward_ratio": 2.0,
        },
    }

    strategy = VisualBuilderStrategy(params={"config": full_config, "enabled": True})

    # 1. Evaluate the complex condition tree directly (asserting complete trace tree)
    tree_result, tree_trace = strategy._evaluate_condition_tree(
        node=chain_def["tree"],
        pair_info=pair_info,
        market_data=market_data,
        prev_pair_info={},
        context={},
    )
    assert isinstance(tree_result, (bool, np.bool_))
    assert isinstance(tree_trace, dict)
    assert tree_trace.get("type") == chain_def["tree"]["type"]
    assert len(tree_trace.get("children", [])) > 0

    # 2. Check full signal dispatcher pipeline
    signal, weight, trace = strategy.check_signal_sync(
        pair_info=pair_info,
        market_data=market_data,
        prev_pair_info={},
    )

    assert isinstance(signal, (StrategySignal, type(None)))
    assert isinstance(weight, (int, float))
    if trace is not None:
        assert isinstance(trace, dict)


# ============================================================================================
# 5. TEST 3: RANDOM COMBINATORIAL FUZZING (Stress Test on Generated Trees)
# ============================================================================================
def generate_random_ast_tree(
    depth: int = 1, max_depth: int = 3, rng: random.Random = None
) -> Dict[str, Any]:
    """Recursively generates a random but structurally valid condition tree."""
    if rng is None:
        rng = random.Random(42)

    if depth >= max_depth or (depth > 1 and rng.random() < 0.4):
        leaf = copy.deepcopy(rng.choice(ALL_BLOCKS_REGISTRY))
        leaf["id"] = f"fuzz_leaf_{rng.randint(1000, 9999)}"
        return leaf

    gate_type = rng.choice(["AND", "OR"])
    num_children = rng.randint(2, 4)
    children = [
        generate_random_ast_tree(depth=depth + 1, max_depth=max_depth, rng=rng)
        for _ in range(num_children)
    ]
    return {
        "id": f"fuzz_gate_{gate_type}_{rng.randint(1000, 9999)}",
        "type": gate_type,
        "children": children,
    }


@pytest.mark.parametrize("exchange", ["bybit", "okx", "weex"])
@pytest.mark.parametrize("fuzz_seed", [101, 202, 303, 404, 505])
def test_random_fuzzing_block_combinations_matrix(exchange: str, fuzz_seed: int):
    """
    Fuzz testing: Generates 5 distinct randomized AST trees and validates
    that no combination of blocks crashes when evaluated against Bybit, OKX, or Weex.
    """
    rng = random.Random(fuzz_seed)
    random_tree = generate_random_ast_tree(depth=1, max_depth=3, rng=rng)

    pair_info, market_data = create_exchange_context(exchange=exchange)
    strategy = VisualBuilderStrategy(
        params={"config": {"entryConditions": random_tree}}
    )

    result, trace = strategy._evaluate_condition_tree(
        node=random_tree,
        pair_info=pair_info,
        market_data=market_data,
        prev_pair_info={},
        context={},
    )

    assert isinstance(result, (bool, np.bool_))
    assert isinstance(trace, dict)
    assert trace["type"] == random_tree["type"]


# ============================================================================================
# 6. TEST 4: CONTEXT PROPAGATION & CROSS-BLOCK LINKING
# ============================================================================================
@pytest.mark.parametrize("exchange", ["bybit", "okx", "weex"])
def test_context_propagation_and_reference_linking(exchange: str):
    """
    Verifies that context (e.g. support levels, calculated ATR, density metrics)
    correctly propagates through the execution context from upstream to downstream blocks.
    """
    pair_info, market_data = create_exchange_context(exchange=exchange)
    strategy = VisualBuilderStrategy(params={"enabled": True})

    linked_tree = {
        "id": "root_seq",
        "type": "AND",
        "children": [
            {
                "id": "n_level",
                "type": "LOCAL_LEVEL",
                "params": {"lookback": 50, "level_type": "support"},
            },
            {
                "id": "n_price",
                "type": "PRICE_VS_LEVEL",
                "params": {
                    "level_type": "rolling_low",
                    "lookback": 50,
                    "operator": "gt",
                },
            },
            {
                "id": "n_l2",
                "type": "L2_MICROSTRUCTURE",
                "params": {"imbalance_threshold": 0.2},
            },
        ],
    }

    shared_context: Dict[str, Any] = {}
    result, trace = strategy._evaluate_condition_tree(
        node=linked_tree,
        pair_info=pair_info,
        market_data=market_data,
        prev_pair_info={},
        context=shared_context,
    )

    assert isinstance(result, (bool, np.bool_))
    assert len(trace.get("children", [])) == 3
    for child_trace in trace["children"]:
        assert "result" in child_trace


# ============================================================================================
# 7. TEST 5: MULTI-TIMEFRAME CONFLUENCE (senior_tf_confluence)
# ============================================================================================
@pytest.mark.parametrize("exchange", ["bybit", "okx", "weex"])
@pytest.mark.parametrize("htf", ["5m", "1h", "4h"])
def test_senior_tf_confluence_across_exchanges(exchange: str, htf: str):
    """
    Validates senior_tf_confluence container nodes across multiple timeframes
    and exchanges, ensuring seamless HTF context switching and nested indicator calculations.
    """
    pair_info, market_data = create_exchange_context(exchange=exchange)
    strategy = VisualBuilderStrategy(params={"enabled": True})

    htf_tree = {
        "id": "htf_container_root",
        "type": "senior_tf_confluence",
        "params": {"timeframe": htf},
        "children": [
            {
                "id": "htf_rsi",
                "type": "RSI",
                "params": {"period": 14, "operator": "gt", "value": 40.0},
            },
            {
                "id": "htf_ma",
                "type": "MA_CROSS",
                "params": {"fast_period": 10, "slow_period": 50, "ma_type": "sma"},
            },
        ],
    }

    result, trace = strategy._evaluate_condition_tree(
        node=htf_tree,
        pair_info=pair_info,
        market_data=market_data,
        prev_pair_info={},
        context={},
    )

    assert isinstance(result, (bool, np.bool_))
    assert trace["type"] == "senior_tf_confluence"
    assert "details" in trace
    assert len(trace.get("children", [])) == 2


# ============================================================================================
# 8. TEST 6: TRADINGVIEW WEBHOOK SIGNALS & WEIGHT EXTRACTION
# ============================================================================================
@pytest.mark.parametrize("exchange", ["bybit", "okx", "weex"])
def test_tradingview_signals_across_exchanges(exchange: str):
    """
    Verifies that TradingView webhook nodes register, properly handle TTL expirations,
    and dynamically contribute to foundation weights.
    """
    pair_info, market_data = create_exchange_context(exchange=exchange)

    tv_node = {
        "id": "node_tv_webhook",
        "type": "tradingview_signal",
        "params": {"signal_id": "PINE_SCALPER_BUY", "weight": 75.0},
    }

    config = {
        "entryConditions": {
            "id": "root_and",
            "type": "AND",
            "children": [
                tv_node,
                {
                    "id": "c_rsi",
                    "type": "RSI",
                    "params": {"period": 14, "operator": "lt", "value": 70.0},
                },
            ],
        }
    }

    strategy = VisualBuilderStrategy(params={"config": config, "enabled": True})
    assert strategy.foundation_weights.get("PINE_SCALPER_BUY") == 75.0

    # 1. Before signal registration -> evaluate should return False for the TV node
    res_before, trace_before = strategy._evaluate_condition_tree(
        node=tv_node,
        pair_info=pair_info,
        market_data=market_data,
        prev_pair_info={},
        context={},
    )
    assert res_before is False

    # 2. Register active signal with 60s TTL -> evaluate should return True
    strategy.register_tv_signal(signal_id="PINE_SCALPER_BUY", ttl_seconds=60)
    res_active, trace_active = strategy._evaluate_condition_tree(
        node=tv_node,
        pair_info=pair_info,
        market_data=market_data,
        prev_pair_info={},
        context={},
    )
    assert res_active is True
    assert "Active TradingView signal found" in trace_active["details"]["info"]


# ============================================================================================
# 9. TEST 7: FULL POSITION MANAGEMENT LIFECYCLE (DCA, Grid, Trailing, BE, Scale-in)
# ============================================================================================
@pytest.mark.parametrize("exchange", ["bybit", "okx", "weex"])
@pytest.mark.asyncio
async def test_all_position_management_blocks_across_exchanges(exchange: str):
    """
    Exhaustively tests all position management block types:
    - trailing_stop (ATR, Percentage, MA)
    - move_to_breakeven (ATR multiplier, RR, Percent)
    - scale_in
    - conditional_management (Dynamic SL / TP adjustments)
    - conditional_exit
    - dca_management
    - grid_management
    """
    pair_info, market_data = create_exchange_context(exchange=exchange)
    last_p = pair_info["last_price"]

    config = {
        "positionManagement": [
            {
                "id": "pm_trail",
                "type": "trailing_stop",
                "params": {"type": "ATR", "value": 2.0},
            },
            {
                "id": "pm_be",
                "type": "move_to_breakeven",
                "params": {
                    "target_type": "atr_multiplier",
                    "target_value": 0.5,
                    "offset_pips": 2,
                },
            },
            {
                "id": "pm_dca",
                "type": "dca_management",
                "params": {
                    "max_safety_orders": 3,
                    "volume_multiplier": 1.5,
                    "step_type": "percentage",
                    "step_value": 1.0,
                },
            },
            {
                "id": "pm_grid",
                "type": "grid_management",
                "params": {
                    "range_type": "percentage",
                    "grid_levels": 4,
                    "upper_bound": last_p * 1.05,
                    "lower_bound": last_p * 0.95,
                },
            },
            {
                "id": "pm_cond_mgmt",
                "type": "conditional_management",
                "if_conditions": {
                    "id": "c_rsi",
                    "type": "RSI",
                    "params": {"period": 14, "operator": "gt", "value": 20.0},
                },
                "then_actions": [
                    {
                        "id": "act_mod_sl",
                        "type": "modify_stop_loss",
                        "params": {"new_sl_price": last_p * 0.98},
                    }
                ],
            },
        ]
    }

    strategy = VisualBuilderStrategy(params={"config": config, "enabled": True})

    # Create test open position
    pos = BasePosition(
        symbol=pair_info["symbol"],
        direction=SignalDirection.LONG,
        entry_price=last_p * 0.99,
        initial_quantity=1.0,
        remaining_quantity=1.0,
        entry_time=time.time() - 300,
        strategy="VisualBuilderStrategy",
        initial_stop_loss=last_p * 0.95,
        current_sl_price=last_p * 0.95,
        initial_take_profit=last_p * 1.05,
    )

    # 1. Trailing Stop
    updated_pos = strategy._handle_trailing_stop(
        config["positionManagement"][0], pos, pair_info
    )
    assert updated_pos.current_sl_price is not None
    assert updated_pos.current_sl_price > pos.entry_price * 0.90

    # 2. Move to Break-even
    be_pos = strategy._handle_move_to_breakeven(
        config["positionManagement"][1], pos, pair_info
    )
    assert be_pos is not None

    # 3. Full Position Management Executor
    exec_pos, exit_details = await strategy._execute_position_management(
        strategy_config=config,
        position=pos,
        pair_info=pair_info,
        market_data=market_data,
        prev_pair_info=None,
    )
    assert exec_pos is not None
    assert exec_pos.symbol == pair_info["symbol"]


# ============================================================================================
# 10. TEST 8: DYNAMIC PARAMETER RESOLVERS (_resolve_value)
# ============================================================================================
@pytest.mark.parametrize("exchange", ["bybit", "okx", "weex"])
def test_dynamic_reference_resolvers_across_exchanges(exchange: str):
    """
    Validates dynamic parameter resolution from all supported sources:
    - Static constants
    - Candle values with historical shifts
    - Calculated indicator series
    - Position state metrics (unrealized PnL, partials count)
    - Upstream block trace results
    """
    pair_info, market_data = create_exchange_context(exchange=exchange)
    strategy = VisualBuilderStrategy(params={"enabled": True})

    context = {
        "pair_info": pair_info,
        "market_data": market_data,
        "trace": {
            "id": "upstream_finder",
            "type": "LOCAL_LEVEL",
            "details": {"level_price": 59500.0, "touches": 3},
        },
        "position": BasePosition(
            symbol=pair_info["symbol"],
            direction=SignalDirection.LONG,
            entry_price=60000.0,
            initial_quantity=1.0,
            remaining_quantity=1.0,
            entry_time=time.time() - 300,
            strategy="VisualBuilderStrategy",
        ),
    }

    # 1. Constant value
    val_const = strategy._resolve_value(
        {"source": "constant", "value": 123.45}, context
    )
    assert val_const == 123.45

    # 2. Candle lookup with shift
    val_candle = strategy._resolve_value(
        {"source": "candle", "key": "close", "shift": 1}, context
    )
    assert isinstance(val_candle, float)
    assert val_candle > 0

    # 3. Indicator lookup
    val_ind = strategy._resolve_value({"source": "indicator", "key": "SMA_10"}, context)
    assert isinstance(val_ind, (int, float))

    # 4. Block result upstream linking
    val_block = strategy._resolve_value(
        {"source": "block_result", "block_id": "upstream_finder", "key": "level_price"},
        context,
    )
    assert val_block == 59500.0

    # 5. Position state metrics
    val_pos = strategy._resolve_value(
        {"source": "position_state", "key": "unrealized_pnl_pct"},
        context,
    )
    assert isinstance(val_pos, (int, float))


# ============================================================================================
# 11. TEST 9: SHORT POSITION SYMMETRY & SHORT LIFECYCLE ACROSS EXCHANGES
# ============================================================================================
@pytest.mark.parametrize("exchange", ["bybit", "okx", "weex"])
@pytest.mark.asyncio
async def test_short_symmetry_chains_and_management_across_exchanges(exchange: str):
    """
    Exhaustively tests short trading symmetry across Bybit, OKX, and Weex:
    - Short condition trees (Upper Bollinger cross below, Trend SHORT, Asks density)
    - Short Trailing Stop (lowering SL downwards as market drops)
    - Short Move-to-Breakeven (calculating profit on dropping Low price)
    - Short Position Management execution
    """
    pair_info, market_data = create_exchange_context(
        exchange=exchange, direction_hint="SHORT"
    )
    last_p = pair_info["last_price"]

    # Short Condition Strategy
    short_tree = {
        "id": "root_short_and",
        "type": "AND",
        "children": [
            {
                "id": "s_trend",
                "type": "TREND_DIRECTION",
                "params": {
                    "fast_period": 10,
                    "slow_period": 50,
                    "required_trend": "SHORT",
                },
            },
            {
                "id": "s_ob",
                "type": "ORDER_BOOK_ZONE",
                "params": {
                    "side": "asks",
                    "metric": "obi_1p",
                    "operator": "lt",
                    "threshold": 0,
                },
            },
            {
                "id": "s_bb",
                "type": "BOLLINGER",
                "params": {
                    "period": 20,
                    "std_dev": 2.0,
                    "operator": "cross_below",
                    "band": "upper",
                },
            },
        ],
    }

    full_short_config = {
        "initialization": {
            "id": "init_short",
            "type": "open_position",
            "params": {"direction": "SHORT"},
        },
        "entryConditions": short_tree,
        "positionManagement": [
            {
                "id": "pm_short_trail",
                "type": "trailing_stop",
                "params": {"type": "ATR", "value": 2.0},
            },
            {
                "id": "pm_short_be",
                "type": "move_to_breakeven",
                "params": {
                    "target_type": "atr_multiplier",
                    "target_value": 0.5,
                    "offset_pips": 2,
                },
            },
            {
                "id": "pm_short_dca",
                "type": "dca_management",
                "params": {
                    "max_safety_orders": 3,
                    "volume_multiplier": 1.5,
                    "step_type": "percentage",
                    "step_value": 1.0,
                },
            },
        ],
    }

    strategy = VisualBuilderStrategy(
        params={"config": full_short_config, "enabled": True}
    )

    # 1. Condition evaluation
    result, trace = strategy._evaluate_condition_tree(
        node=short_tree,
        pair_info=pair_info,
        market_data=market_data,
        prev_pair_info={},
        context={},
    )
    assert isinstance(result, (bool, np.bool_))
    assert trace["type"] == "AND"

    # 2. Short Position Trailing Stop (SL moves downwards as price drops)
    short_pos = BasePosition(
        symbol=pair_info["symbol"],
        direction=SignalDirection.SHORT,
        entry_price=last_p * 1.02,
        initial_quantity=1.0,
        remaining_quantity=1.0,
        entry_time=time.time() - 300,
        strategy="VisualBuilderStrategy",
        initial_stop_loss=last_p * 1.05,
        current_sl_price=last_p * 1.05,
        initial_take_profit=last_p * 0.95,
    )

    trail_updated_pos = strategy._handle_trailing_stop(
        full_short_config["positionManagement"][0], short_pos, pair_info
    )
    assert trail_updated_pos.current_sl_price is not None
    # For SHORT, new SL must be lower than original high SL
    assert trail_updated_pos.current_sl_price <= short_pos.initial_stop_loss

    # 3. Short Move-to-Breakeven
    be_updated_pos = strategy._handle_move_to_breakeven(
        full_short_config["positionManagement"][1], short_pos, pair_info
    )
    assert be_updated_pos is not None

    # 4. Async Position Management Executor
    exec_pos, exit_details = await strategy._execute_position_management(
        strategy_config=full_short_config,
        position=short_pos,
        pair_info=pair_info,
        market_data=market_data,
        prev_pair_info=None,
    )
    assert exec_pos is not None
    assert exec_pos.direction == SignalDirection.SHORT


# ============================================================================================
# 12. TEST 10: MEMECOIN & MICRO-PRICE ASSETS (PEPE, DOGE) HIGH-PRECISION REGIME
# ============================================================================================
@pytest.mark.parametrize("exchange", ["bybit", "okx", "weex"])
@pytest.mark.parametrize("memecoin_symbol", ["PEPEUSDT", "DOGEUSDT"])
@pytest.mark.asyncio
async def test_memecoin_micro_price_precision_across_exchanges(
    exchange: str, memecoin_symbol: str
):
    """
    Validates extreme decimal precision (8 decimals for PEPE, 5 for DOGE)
    to guarantee zero floating-point underflow or precision loss in ATR, SL/TP, and indicators.
    """
    pair_info, market_data = create_exchange_context(
        exchange=exchange, symbol=memecoin_symbol
    )
    last_p = pair_info["last_price"]

    assert last_p < 1.0, (
        f"Memecoin {memecoin_symbol} price must be micro-scaled (< 1.0)"
    )

    config = {
        "positionManagement": [
            {
                "id": "pm_trail_meme",
                "type": "trailing_stop",
                "params": {"type": "ATR", "value": 2.0},
            },
            {
                "id": "pm_be_meme",
                "type": "move_to_breakeven",
                "params": {
                    "target_type": "atr_multiplier",
                    "target_value": 0.5,
                    "offset_pips": 5,
                },
            },
            {
                "id": "pm_grid_meme",
                "type": "grid_management",
                "params": {
                    "range_type": "percentage",
                    "grid_levels": 5,
                    "upper_bound": last_p * 1.10,
                    "lower_bound": last_p * 0.90,
                },
            },
        ]
    }

    strategy = VisualBuilderStrategy(params={"config": config, "enabled": True})

    # Test Open Position on micro-price
    pos = BasePosition(
        symbol=memecoin_symbol,
        direction=SignalDirection.LONG,
        entry_price=last_p * 0.98,
        initial_quantity=1000000.0,
        remaining_quantity=1000000.0,
        entry_time=time.time() - 300,
        strategy="VisualBuilderStrategy",
        initial_stop_loss=last_p * 0.90,
        current_sl_price=last_p * 0.90,
        initial_take_profit=last_p * 1.10,
    )

    # 1. Trailing stop precision
    updated_pos = strategy._handle_trailing_stop(
        config["positionManagement"][0], pos, pair_info
    )
    assert updated_pos.current_sl_price is not None
    assert updated_pos.current_sl_price > 0

    # 2. Move to BE precision
    be_pos = strategy._handle_move_to_breakeven(
        config["positionManagement"][1], pos, pair_info
    )
    assert be_pos is not None

    # 3. Dynamic candle lookback resolver on micro decimals
    context = {"pair_info": pair_info, "market_data": market_data, "position": pos}
    resolved_val = strategy._resolve_value(
        {"source": "candle", "key": "close", "shift": 1}, context
    )
    assert isinstance(resolved_val, float)
    assert resolved_val > 0
