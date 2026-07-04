# File: tests/test_visual_strategy_extended.py

import pytest
import pandas as pd
import numpy as np
from bot_module import strategy as strategy_module
from bot_module.strategy import OrderMode
from bot_module.depthsight_backtester import DepthSightBacktester
from typing import Dict, Any
from datetime import datetime, timezone

# --- Helpers ---


def create_test_kline_df(num_candles=60, base_price=100.0) -> pd.DataFrame:
    """Creates a test candle DataFrame."""
    now = pd.Timestamp.now(tz="UTC")
    index = pd.to_datetime(
        [now - pd.Timedelta(minutes=i) for i in range(num_candles - 1, -1, -1)]
    )

    closes = base_price + np.cumsum(np.random.normal(0, 0.5, num_candles))
    highs = closes + np.abs(np.random.normal(2, 1, num_candles))
    lows = closes - np.abs(np.random.normal(2, 1, num_candles))
    opens = (highs + lows) / 2 + np.random.normal(0, 0.5, num_candles)

    data = {
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": np.random.uniform(100, 200, num_candles),
    }
    df = pd.DataFrame(data, index=index)
    df["SMA_10"] = df["close"].rolling(10).mean()
    df["SMA_50"] = df["close"].rolling(50).mean()

    df["RSI_14"] = 50.0
    df["ADX_14"] = 20.0
    df["BBW_20_2"] = 0.05
    df["MACD_hist_12_26_9"] = 0.0

    df.bfill(inplace=True)
    df.ffill(inplace=True)
    return df


def get_default_market_data() -> Dict[str, Any]:
    """Returns a base dictionary with market data."""
    df = create_test_kline_df()
    agg_trades_df = pd.DataFrame(
        {
            "price": np.random.uniform(99.9, 100.1, 100),
            "quantity": np.random.uniform(0.1, 1.0, 100),
        },
        index=pd.to_datetime(
            pd.date_range(end=df.index[-1], periods=100, freq="500ms", tz="UTC")
        ),
    )
    return {
        "kline_1m": df.copy(),
        "kline_5m": df.copy(),
        "kline_15m": df.copy(),
        "kline_1h": df.copy(),
        "kline_4h": df.copy(),
        "kline_1d": df.copy(),
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


# --- Fixture ---


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
        },
    )
    monkeypatch.setattr(
        strategy_module.config, "MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD", 0.0
    )

    def _create_instance(json_config: Dict[str, Any]):
        params_for_creation = {
            "config": json_config,
            "enabled": True,
            "risk_pct_per_trade": 0.01,
        }
        instance = strategy_module.create_strategy_instance(
            strategy_name="VisualBuilderStrategy", params=params_for_creation
        )
        assert instance is not None, (
            "Failed to create an instance of VisualBuilderStrategy"
        )
        return instance

    return _create_instance


# --- Tests ---


@pytest.mark.asyncio
async def test_move_to_breakeven_percentage(visual_strategy_instance):
    test_json_config = {
        "min_foundation_weight_threshold": 0,
        "entryConditions": {
            "id": "e_root",
            "type": "AND",
            "children": [
                {
                    "type": "price_vs_level",
                    "params": {
                        "price_source": {"source": "candle", "key": "close"},
                        "operator": "gt",
                        "level_source": {"source": "value", "value": 99.9},
                    },
                },
                {
                    "type": "price_vs_level",
                    "params": {
                        "price_source": {"source": "candle", "key": "close"},
                        "operator": "lt",
                        "level_source": {"source": "value", "value": 100.1},
                    },
                },
            ],
        },
        "initialization": {
            "id": "act1",
            "type": "open_position",
            "params": {
                "direction": "LONG",
                "sl_type": "atr_multiplier",
                "sl_value": 1.0,
                "tp_type": "rr_multiplier",
                "tp_value": 5.0,
            },
        },
        "positionManagement": [
            {
                "id": "mng1",
                "type": "move_to_breakeven",
                "params": {
                    "target_type": "percent_from_price",
                    "target_value": 2.0,
                    "offset_pips": 5,
                },
            }
        ],
    }
    klines = create_test_kline_df(150, 100)
    klines.loc[klines.index[60], ["open", "high", "low", "close"]] = [
        99.95,
        100.05,
        99.9,
        100.0,
    ]
    klines.loc[klines.index[61], ["open", "high", "low", "close"]] = [
        100.0,
        102.5,
        99.9,
        102.1,
    ]
    klines.loc[klines.index[62], ["open", "high", "low", "close"]] = [
        102.1,
        102.1,
        99.0,
        99.5,
    ]

    backtester = DepthSightBacktester(
        strategy_name="VisualBuilderStrategy",
        symbol="TESTUSDT",
        params={"config": test_json_config},
        historical_data={"kline_1m": klines},
        initial_balance=10000,
        min_trades_required=0,
        risk_params={"risk_pct_per_trade": 0.01, "daily_max_loss_pct": 1.0},
        backtest_risk_params={"riskPerTradePercent": 1.0, "dailyMaxLossPercent": 5.0},
        execution_config={"commission_pct": 0.0},
        strategy_defaults={"risk_pct_per_trade": 0.01},
        ml_training_config={},
        ml_sim_log_path=None,
        exchange_info={
            "tick_size": 0.01,
            "lot_params": {"stepSize": 0.001},
            "min_notional": 10.0,
        },
        min_foundation_weight_threshold=0.0,
    )

    original_check_signal = backtester.strategy_instance.check_signal
    fired = False

    async def single_signal_on_60(
        pair_info, market_data, prev_pair_info, analysis_level="second_bar_trigger"
    ):
        nonlocal fired
        if pair_info["current_candle_index"] == 60 and not fired:
            fired = True
            return await original_check_signal(
                pair_info, market_data, prev_pair_info, analysis_level
            )
        return None, 0.0, None

    backtester.strategy_instance.check_signal = single_signal_on_60
    await backtester.run_async()

    assert len(backtester.trade_log) == 1, (
        f"There should have been one trade, but trade_log: {backtester.trade_log}"
    )
    trade = backtester.trade_log[0]
    assert trade["exit_reason"] == "SL_AT_BE"


@pytest.mark.asyncio
async def test_limit_retest_order(visual_strategy_instance):
    test_json_config = {
        "min_foundation_weight_threshold": 0,
        "entryConditions": {
            "id": "e_root",
            "type": "AND",
            "children": [
                {
                    "type": "price_vs_level",
                    "params": {
                        "price_source": {"source": "candle", "key": "close"},
                        "operator": "gt",
                        "level_source": {"source": "value", "value": 105.9},
                    },
                },
                {
                    "id": "level1",
                    "type": "local_level",
                    "params": {
                        "timeframe": "1m",
                        "lookback_period": 5,
                        "proximity_type": "atr_multiplier",
                        "proximity_value": 0.5,
                    },
                },
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
                "sl_type": "atr_multiplier",
                "sl_value": 1.0,
                "tp_type": "rr_multiplier",
                "tp_value": 4.0,
            },
        },
    }

    klines = create_test_kline_df(150, 100)
    for i in range(50, 62):
        klines.loc[klines.index[i], ["open", "high", "low", "close"]] = [90, 91, 89, 90]
    for i in range(55, 60):
        klines.loc[klines.index[i], ["open", "high", "low", "close"]] = [
            104.5,
            105.0,
            104.0,
            104.7,
        ]
    klines.loc[klines.index[60], ["open", "high", "low", "close"]] = [
        106.0,
        107.0,
        105.8,
        106.0,
    ]
    klines.loc[klines.index[61], ["open", "high", "low", "close"]] = [
        106.0,
        106.5,
        104.9,
        105.5,
    ]
    klines.loc[klines.index[62], ["open", "high", "low", "close"]] = [
        105.5,
        105.5,
        99.0,
        100.0,
    ]

    backtester = DepthSightBacktester(
        strategy_name="VisualBuilderStrategy",
        symbol="TESTUSDT",
        params={"config": test_json_config},
        historical_data={"kline_1m": klines},
        initial_balance=10000,
        min_trades_required=0,
        risk_params={"risk_pct_per_trade": 0.01, "daily_max_loss_pct": 1.0},
        backtest_risk_params={"riskPerTradePercent": 1.0, "dailyMaxLossPercent": 5.0},
        execution_config={"commission_pct": 0.0},
        strategy_defaults={"risk_pct_per_trade": 0.01},
        ml_training_config={},
        ml_sim_log_path=None,
        exchange_info={
            "tick_size": 0.01,
            "lot_params": {"stepSize": 0.001},
            "min_notional": 10.0,
        },
        min_foundation_weight_threshold=0.0,
    )

    original_check_signal = backtester.strategy_instance.check_signal
    fired = False

    async def single_signal_on_60(
        pair_info, market_data, prev_pair_info, analysis_level="second_bar_trigger"
    ):
        nonlocal fired
        if pair_info["current_candle_index"] == 60 and not fired:
            fired = True
            pair_info["atr"] = 3.5
            return await original_check_signal(
                pair_info, market_data, prev_pair_info, analysis_level
            )
        return None, 0.0, None

    backtester.strategy_instance.check_signal = single_signal_on_60
    await backtester.run_async()

    assert len(backtester.trade_log) == 1
    trade = backtester.trade_log[0]
    assert trade["entry_price"] == pytest.approx(105.0)


def test_limit_break_signal_mode_and_entry_price(visual_strategy_instance):
    test_json_config = {
        "min_total_foundation_weight_threshold": 0.0,
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
                "order_type": "LIMIT_BREAK",
                "entry_price": {
                    "source": "block_result",
                    "block_id": "level1",
                    "key": "detected_level",
                },
                "sl_type": "atr_multiplier",
                "sl_value": 1.0,
                "tp_type": "rr_multiplier",
                "tp_value": 3.0,
            },
        },
    }

    strat = visual_strategy_instance(test_json_config)
    market_data = get_default_market_data()
    # Reset lookback window to 100.0 to prevent random walk from going above 105.0 or causing failures
    for i in range(1, 11):
        market_data["kline_1m"].iloc[-i, market_data["kline_1m"].columns.get_loc("open")] = 100.0
        market_data["kline_1m"].iloc[-i, market_data["kline_1m"].columns.get_loc("high")] = 100.1
        market_data["kline_1m"].iloc[-i, market_data["kline_1m"].columns.get_loc("low")] = 99.9
        market_data["kline_1m"].iloc[-i, market_data["kline_1m"].columns.get_loc("close")] = 100.0

    market_data["kline_1m"].iloc[-3, market_data["kline_1m"].columns.get_loc("high")] = 105.0
    pair_info = get_default_pair_info(last_price=105.1, atr_val=0.5)
    pair_info["timestamp_dt"] = market_data["kline_1m"].index[-1]

    signal, _, _ = strat.check_signal_sync(pair_info, market_data, None)

    assert signal is not None
    assert signal.mode == OrderMode.LIMIT_BREAK
    assert signal.entry_price == pytest.approx(105.0)


@pytest.mark.asyncio
async def test_dynamic_sl_tp(visual_strategy_instance):
    test_json_config = {
        "min_foundation_weight_threshold": 0,
        "entryConditions": {
            "id": "e_root",
            "type": "AND",
            "children": [
                {
                    "type": "price_vs_level",
                    "params": {
                        "price_source": {"source": "candle", "key": "close"},
                        "operator": "gt",
                        "level_source": {"source": "value", "value": 99.9},
                    },
                },
                {
                    "type": "price_vs_level",
                    "params": {
                        "price_source": {"source": "candle", "key": "close"},
                        "operator": "lt",
                        "level_source": {"source": "value", "value": 100.1},
                    },
                },
            ],
        },
        "initialization": {
            "id": "act1",
            "type": "open_position",
            "params": {
                "direction": "LONG",
                "order_type": "MARKET",
                "sl_type": "fixed_price",
                "sl_value": {"source": "candle", "key": "low", "shift": 1},
                "tp_type": "fixed_price",
                "tp_value": {"source": "candle", "key": "high", "shift": 1},
            },
        },
    }
    klines = create_test_kline_df(150, 100)
    klines.loc[klines.index[59], ["open", "high", "low", "close"]] = [
        99.0,
        115.0,
        95.0,
        100.0,
    ]
    klines.loc[klines.index[60], ["open", "high", "low", "close"]] = [
        100.0,
        101.0,
        99.0,
        100.0,
    ]
    klines.loc[klines.index[61], ["open", "high", "low", "close"]] = [
        100.0,
        101.0,
        94.0,
        95.0,
    ]

    backtester = DepthSightBacktester(
        strategy_name="VisualBuilderStrategy",
        symbol="TESTUSDT",
        params={"config": test_json_config},
        historical_data={"kline_1m": klines},
        initial_balance=10000,
        min_trades_required=0,
        risk_params={"risk_pct_per_trade": 0.01, "daily_max_loss_pct": 1.0},
        backtest_risk_params={"riskPerTradePercent": 1.0, "dailyMaxLossPercent": 5.0},
        execution_config={"commission_pct": 0.0},
        strategy_defaults={"risk_pct_per_trade": 0.01},
        ml_training_config={},
        ml_sim_log_path=None,
        exchange_info={
            "tick_size": 0.01,
            "lot_params": {"stepSize": 0.001},
            "min_notional": 10.0,
        },
        min_foundation_weight_threshold=0.0,
    )

    original_check_signal = backtester.strategy_instance.check_signal
    fired = False

    async def single_signal_on_60(
        pair_info, market_data, prev_pair_info, analysis_level="second_bar_trigger"
    ):
        nonlocal fired
        if pair_info["current_candle_index"] == 60 and not fired:
            fired = True
            return await original_check_signal(
                pair_info, market_data, prev_pair_info, analysis_level
            )
        return None, 0.0, None

    backtester.strategy_instance.check_signal = single_signal_on_60
    await backtester.run_async()

    assert len(backtester.trade_log) == 1
    trade = backtester.trade_log[0]
    assert trade["sl_level"] == pytest.approx(95.0)
    assert trade["tp_level"] == pytest.approx(115.0)
