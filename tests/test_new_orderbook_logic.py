# FILE: tests/test_new_orderbook_logic.py

import pytest
import pandas as pd
from unittest.mock import AsyncMock
import numpy as np

from bot_module.depthsight_backtester import (
    DepthSightBacktester,
    L2HistoricalDataReader,
)


@pytest.fixture
def backtester_shared_data():
    """Common data for backtester tests."""
    # Increased to 60 candles, as the backtester requires at least 51 for indicator warmup
    num_candles = 60

    # Replacing utc=True with tz='UTC' for compatibility with newer Pandas versions ---
    date_index = pd.date_range(
        start="2023-01-01 12:01", periods=num_candles, freq="1min", tz="UTC"
    )

    klines_df = pd.DataFrame(
        {
            "open": np.linspace(100, 159, num_candles),
            "high": np.linspace(102, 161, num_candles),
            "low": np.linspace(98, 157, num_candles),
            "close": np.linspace(101, 160, num_candles),
            "volume": [1000] * num_candles,
        },
        index=date_index,
    )

    klines_df["ATR_14"] = [1.5] * num_candles

    # Adding other standard indicators with dummy values
    klines_df["MACD_12_26_9"] = 0.0
    klines_df["MACD_signal_12_26_9"] = 0.0
    klines_df["MACD_hist_12_26_9"] = 0.0
    klines_df["BB_upper_20_2"] = 110.0
    klines_df["BB_middle_20_2"] = 105.0
    klines_df["BB_lower_20_2"] = 100.0
    klines_df["BBW_20_2"] = 0.1
    klines_df["STOCH_k_14_3_3"] = 50.0
    klines_df["STOCH_d_14_3_3"] = 50.0
    klines_df["ADX_14"] = 25.0

    # To create an empty DatetimeIndex, use utc=True instead of tz='UTC' ---
    agg_trades_df = pd.DataFrame(
        columns=["price", "quantity"], index=pd.to_datetime([], utc=True)
    )

    # Signal candle must be after the warmup index (51), using index 55
    signal_timestamp = klines_df.index[55]
    l2_snapshot = {
        "ts": signal_timestamp.timestamp() * 1000,
        "asks": [["155.1", "100"]],  # Updated for the new price
        "bids": [["154.9", "200"]],
    }

    signal_price = klines_df["close"].iloc[55]

    # Updating strategy JSON to the current format ---
    strategy_json = {
        "id": "test_strat_single_signal",
        "entryConditions": {
            "id": "e_root",
            "type": "AND",
            "children": [
                {
                    "id": "e1",
                    "type": "price_condition",
                    "params": {
                        "leftOperand": {"source": "candle", "key": "close"},
                        "operator": "==",
                        "rightOperand": {
                            "source": "value",
                            "value": float(signal_price),
                        },
                    },
                }
            ],
        },
        "initialization": {
            "id": "init1",
            "type": "open_position",
            "params": {
                "direction": "LONG",
                "sl_type": "percent_from_price",
                "sl_value": 1.0,
                "tp_type": "percent_from_price",
                "tp_value": 2.0,
            },
        },
    }

    return {
        "klines": klines_df,
        "agg_trades": agg_trades_df,
        "l2_snapshot": l2_snapshot,
        "strategy_json": strategy_json,
        "signal_price": signal_price,
    }


@pytest.mark.asyncio
async def test_backtester_full_mode(backtester_shared_data):
    """Backtester test in mode with L2 data ('full' mode)."""
    mock_l2_reader = AsyncMock(spec=L2HistoricalDataReader)
    mock_l2_reader.get_book_snapshot_at.return_value = backtester_shared_data[
        "l2_snapshot"
    ]

    historical_data = {
        "kline_1m": backtester_shared_data["klines"],
        "aggTrade": backtester_shared_data["agg_trades"],
    }

    bt = DepthSightBacktester(
        strategy_name="VisualBuilderStrategy",
        symbol="TESTUSDT",
        params={"config": backtester_shared_data["strategy_json"]},
        historical_data=historical_data,
        initial_balance=10000.0,
        min_trades_required=1,
        min_foundation_weight_threshold=0,
        foundation_weights={
            "market_activity": 15.0,
            "level": 15.0,
            "pattern": 10.0,
            "volume_confirmation": 10.0,
            "orderbook": 30.0,
            "trend": 10.0,
            "round_number_level": 10.0,
        },
        strategy_defaults={},
        risk_params={"riskPerTradePercent": 1.0},
        backtest_risk_params={"riskPerTradePercent": 1.0},
        execution_config={"commission_pct": 0.00075},
        ml_training_config={},
        ml_sim_log_path=None,
        l2_reader=mock_l2_reader,
    )

    results = await bt.run_async()
    assert results is not None
    assert results["trades"] == 1, (
        f"Should be one trade, but received {results['trades']}"
    )

    trade = bt.trade_log[0]
    # Check that the trade opened at a price close to the signal price (accounting for slippage)
    signal_price = backtester_shared_data["signal_price"]
    assert trade["entry_price"] == pytest.approx(
        signal_price, rel=0.01
    )  # allowing 1% deviation


@pytest.mark.asyncio
async def test_backtester_none_mode(backtester_shared_data):
    """Backtester test in mode without L2 data ('none' mode)."""
    historical_data = {
        "kline_1m": backtester_shared_data["klines"],
        "aggTrade": backtester_shared_data["agg_trades"],
    }

    bt = DepthSightBacktester(
        strategy_name="VisualBuilderStrategy",
        symbol="TESTUSDT",
        params={"config": backtester_shared_data["strategy_json"]},
        historical_data=historical_data,
        initial_balance=10000.0,
        min_trades_required=1,
        min_foundation_weight_threshold=0,
        foundation_weights={
            "market_activity": 15.0,
            "level": 15.0,
            "pattern": 10.0,
            "volume_confirmation": 10.0,
            "orderbook": 30.0,
            "trend": 10.0,
            "round_number_level": 10.0,
        },
        strategy_defaults={},
        risk_params={"riskPerTradePercent": 1.0},
        backtest_risk_params={"riskPerTradePercent": 1.0},
        execution_config={"slippage_pct": 0.001, "commission_pct": 0.00075},
        ml_training_config={},
        ml_sim_log_path=None,
        l2_reader=None,
    )

    results = await bt.run_async()
    assert results is not None
    assert results["trades"] == 1, (
        f"Should be one trade, but received {results['trades']}"
    )

    signal_price = backtester_shared_data["signal_price"]
    trade = bt.trade_log[0]
    # Check that the trade opened at a price close to the signal price (accounting for slippage)
    assert trade["entry_price"] == pytest.approx(
        signal_price, rel=0.01
    )  # allowing 1% deviation
