# tests/test_backtester_with_bookdepth.py

import pytest
import pandas as pd
import numpy as np

from bot_module.depthsight_backtester import DepthSightBacktester
from bot_module import config


@pytest.fixture
def historical_data_with_bookdepth():
    """
    Creates historical data. bookDepth data is configured to
    trigger a signal on candle i=84.
    """
    num_candles = 100
    start_time = pd.to_datetime("2025-09-30 00:00:00", utc=True)
    klines_df = pd.DataFrame(
        {
            "open": np.linspace(100, 150, num_candles),
            "high": np.linspace(101, 151, num_candles),
            "low": np.linspace(99, 149, num_candles),
            "close": np.linspace(101, 151, num_candles),
            "volume": [100] * num_candles,
        },
        index=pd.date_range(start=start_time, periods=num_candles, freq="1min"),
    )
    klines_df["ATR_14"] = 1.0

    # bookDepth data in the new format: depth_m1..m5 (bids), depth_p1..p5 (asks), notional_m1..m5, notional_p1..p5
    # Strategy requests range_type='Percentage', range_value=2.5
    # Logic in _check_condition_order_book_zone:
    #   bucket_percentages = [1.0, 2.0, 3.0, 4.0, 5.0]
    #   target_bucket_index = first index where p >= 2.5 -> index 2 (for 3.0%)
    # Therefore notional_m3 must contain a value > 120,000 USD

    close_price_at_84 = 143.42  # approximate price for candle i=84

    bookdepth_df = pd.DataFrame(
        [
            # Data before the required candle i=83 (condition is not met - notional_m3 < 120k)
            {
                "timestamp": start_time + pd.Timedelta(minutes=83, seconds=18),
                "depth_m1": close_price_at_84 * 0.99,  # -1%
                "depth_m2": close_price_at_84 * 0.98,  # -2%
                "depth_m3": close_price_at_84 * 0.97,  # -3%
                "notional_m1": 5000.0,
                "notional_m2": 8000.0,
                "notional_m3": 10000.0,  # < 120k, condition is NOT met
                "depth_p1": close_price_at_84 * 1.01,
                "depth_p2": close_price_at_84 * 1.02,
                "depth_p3": close_price_at_84 * 1.03,
                "notional_p1": 5000.0,
                "notional_p2": 8000.0,
                "notional_p3": 10000.0,
            },
            # Data for candle i=84 (01:24:00) that will trigger the signal
            {
                "timestamp": start_time + pd.Timedelta(minutes=84, seconds=5),
                "depth_m1": close_price_at_84 * 0.99,  # -1%
                "depth_m2": close_price_at_84 * 0.98,  # -2%
                "depth_m3": close_price_at_84
                * 0.97,  # -3% -> this is the level for 2.5% range
                "notional_m1": 50000.0,
                "notional_m2": 100000.0,
                "notional_m3": 150000.0,  # > 120k, condition IS met
                "depth_p1": close_price_at_84
                * 1.0002,  # - changed to tight spread to match expected execution
                "depth_p2": close_price_at_84 * 1.0004,
                "depth_p3": close_price_at_84 * 1.0006,
                "notional_p1": 50000.0,
                "notional_p2": 100000.0,
                "notional_p3": 150000.0,
            },
        ]
    )
    bookdepth_df["timestamp"] = pd.to_datetime(bookdepth_df["timestamp"], utc=True)
    bookdepth_df.set_index("timestamp", inplace=True)

    return {"kline_1m": klines_df, "bookDepth": bookdepth_df}


@pytest.mark.asyncio
async def test_backtester_with_bookdepth_integration(historical_data_with_bookdepth):
    """
    Integration test: backtester + strategy + bookDepth data.
    Strategy: enter LONG if the total volume on bids within 2.5% > 120,000 USD.
    """
    strategy_json = {
        "entryConditions": {
            "id": "e_root",
            "type": "AND",
            "children": [
                {
                    "id": "data_provider",
                    "type": "order_book_zone",
                    "params": {
                        "side": "bids",
                        "range_type": "Percentage",
                        "range_value": {"source": "value", "value": 2.5},
                    },
                },
                {
                    "id": "comparison",
                    "type": "value_comparison",
                    "params": {
                        "leftOperand": {
                            "source": "block_result",
                            "block_id": "data_provider",
                            "key": "total_volume_usd",
                        },
                        "operator": "gt",
                        "rightOperand": {"source": "value", "value": 120000.0},
                    },
                },
            ],
        },
        "initialization": {
            "id": "init1",
            "type": "open_position",
            "params": {
                "direction": "LONG",
                "sl_type": "percent_from_price",
                "sl_value": 1,
                "tp_type": "percent_from_price",
                "tp_value": 2,
            },
        },
    }

    custom_foundation_weights = config.FOUNDATION_WEIGHTS.copy()
    custom_foundation_weights["order_book_zone"] = config.FOUNDATION_WEIGHTS.get(
        "orderbook", 30.0
    )

    bt = DepthSightBacktester(
        strategy_name="VisualBuilderStrategy",
        symbol="TESTUSDT",
        params={"config": strategy_json},
        historical_data=historical_data_with_bookdepth,
        initial_balance=10000.0,
        min_trades_required=0,
        risk_params={"riskPerTradePercent": 1.0},
        backtest_risk_params={"riskPerTradePercent": 1.0},
        execution_config={"commission_pct": 0.0},
        exchange_info={
            "tick_size": 0.01,
            "lot_params": {"stepSize": "0.001"},
            "min_notional": 10.0,
        },
        strategy_defaults={},
        ml_training_config={},
        ml_sim_log_path=None,
        foundation_weights=custom_foundation_weights,
        min_foundation_weight_threshold=0.0,
    )

    results = await bt.run_async()

    assert results is not None
    assert results["trades"] == 1, (
        f"Exactly one trade should have been opened, but opened {results['trades']}"
    )

    trade = bt.trade_log[0]

    # Signal is generated on data from 01:24:05, which is available on candle i=84 (01:24:00).
    # Entry occurs at the open price of the next candle i=85 (standard backtester behavior).
    # open[85] = close[84] + delta ≈ 143.45
    expected_entry_price = 143.45
    assert trade["entry_price"] == pytest.approx(expected_entry_price, abs=0.1), (
        f"Entry price should be around {expected_entry_price}, but it is {trade['entry_price']}"
    )
