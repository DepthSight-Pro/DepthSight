# FILE: tests/test_backtester_two_phase.py
"""
Tests to verify the two-phase backtester logic:
1. Minute scan (minute_bar_filter) - cheap conditions
2. Second analysis (second_bar_trigger) - expensive conditions
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import AsyncMock

from bot_module.depthsight_backtester import DepthSightBacktester
from bot_module.strategy import VisualBuilderStrategy
from bot_module import strategy as strategy_module


@pytest.fixture
def two_phase_tester_instance(mocker):
    """
    Fixture for creating a configured DepthSightBacktester instance.
    """
    mocker.patch.dict(
        strategy_module.STRATEGIES,
        {"VisualBuilderStrategy": VisualBuilderStrategy},
        clear=True,
    )
    mocker.patch.object(strategy_module, "_strategy_instances", {})
    mocker.patch("bot_module.depthsight_backtester.PANDAS_TA_AVAILABLE", True)
    mock_ta = mocker.patch("bot_module.depthsight_backtester.ta")

    # Creating minute data
    kline_df_1m = pd.DataFrame(
        {
            "open": np.full(100, 100.0),
            "high": np.full(100, 101.0),
            "low": np.full(100, 99.0),
            "close": np.full(100, 100.5),
            "volume": np.full(100, 1000),
            "natr": np.full(100, 1.5),
            "relative_volume": np.full(100, 2.0),
            "is_volume_spike": np.full(100, True),
        },
        index=pd.to_datetime(
            pd.date_range(start="2023-01-01 10:00", periods=100, freq="1min", tz="UTC")
        ),
    )

    # Mocking indicators
    mock_ta.atr.return_value = pd.Series(
        np.full(len(kline_df_1m), 1.0), index=kline_df_1m.index
    )
    mock_ta.sma.side_effect = lambda close, length, **kwargs: pd.Series(
        close, index=close.index
    )
    mock_ta.rsi.return_value = pd.Series(
        np.full(len(kline_df_1m), 50), index=kline_df_1m.index
    )

    def _create_bt(strategy_json_config: dict, historical_data: dict):
        bt = DepthSightBacktester(
            strategy_name="VisualBuilderStrategy",
            symbol="TESTUSDT",
            params={"config": strategy_json_config},
            historical_data=historical_data,
            initial_balance=10000.0,
            min_trades_required=0,
            risk_params={"risk_pct_per_trade": 0.01, "max_stop_distance_pct": 0.05},
            backtest_risk_params={},
            execution_config={"commission_pct": 0.001, "slippage_pct": 0.0},
            strategy_defaults={},
            ml_training_config={},
            ml_sim_log_path=None,
            exchange_info={
                "tick_size": 0.01,
                "lot_params": {"stepSize": "0.001"},
                "min_notional": 10.0,
            },
            l2_storage_path=None,
            foundation_weights=strategy_json_config.get("foundation_weights", {}),
            min_foundation_weight_threshold=strategy_json_config.get(
                "min_foundation_weight_threshold", 50.0
            ),
        )
        return bt

    return _create_bt, kline_df_1m


@pytest.mark.asyncio
async def test_two_phase_short_circuit(two_phase_tester_instance, mocker):
    """
    Test: Verifies that short-circuit triggers when
    (weight of cheap conditions + max weight of expensive ones) < threshold.

    Scenario:
    - market_activity (minute_bar_filter) with a high threshold -> FAIL
    - rsi_condition (second_bar_trigger) has weight 50
    - Total: 0 (cheap) + 50 (expensive max) = 50 < threshold 80
    - Second data MUST NOT be loaded
    """
    create_bt, kline_df_1m = two_phase_tester_instance

    mock_logger = mocker.patch("bot_module.depthsight_backtester.logger_backtest")

    strategy_config = {
        "foundation_weights": {"market_activity": 20.0, "rsi_condition": 50.0},
        "min_foundation_weight_threshold": 80.0,
        "entryConditions": {
            "id": "root",
            "type": "AND",
            "children": [
                {
                    "id": "cheap1",
                    "type": "market_activity",
                    "analysis_level": "minute_bar_filter",
                    "params": {"rel_vol_threshold": 5.0, "natr_threshold": 5.0},
                },
                {
                    "id": "expensive1",
                    "type": "rsi_condition",
                    "analysis_level": "second_bar_trigger",
                    "params": {"operator": "gt", "value": 50},
                },
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

    bt = create_bt(strategy_config, {"kline_1m": kline_df_1m})

    mock_load_1s = mocker.patch.object(
        bt, "_load_1s_klines_for_window", new_callable=AsyncMock
    )
    mock_load_1s.return_value = None

    await bt.run_async()

    # Checking that short-circuit triggered (1s data was not loaded)
    short_circuit_log_found = any(
        "Short-circuit triggered" in str(call)
        for call in mock_logger.info.call_args_list
    )
    assert short_circuit_log_found, "Short-circuit should have triggered"
    mock_load_1s.assert_not_called()


@pytest.mark.asyncio
async def test_two_phase_minute_scan_passes_and_loads_1s_data(
    two_phase_tester_instance, mocker
):
    """
    Test: Verifies that second data is loaded upon a successful minute scan.

    Scenario:
    - market_activity (minute_bar_filter) passes with a low threshold
    - rsi_condition (second_bar_trigger) - "expensive" condition
    - Minute scan should pass
    - Second data MUST be requested
    """
    create_bt, kline_df_1m = two_phase_tester_instance
    mock_logger = mocker.patch("bot_module.depthsight_backtester.logger_backtest")

    strategy_config = {
        "foundation_weights": {"market_activity": 50.0, "rsi_condition": 50.0},
        "min_foundation_weight_threshold": 50.0,
        "entryConditions": {
            "id": "root",
            "type": "AND",
            "children": [
                {
                    "id": "market_activity",
                    "type": "market_activity",
                    "analysis_level": "minute_bar_filter",
                    "params": {"rel_vol_threshold": 1.5, "natr_threshold": 1.0},
                },
                {
                    "id": "rsi_condition",
                    "type": "rsi_condition",
                    "analysis_level": "second_bar_trigger",
                    "params": {"operator": "gte", "value": 60},
                },
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

    bt = create_bt(strategy_config, {"kline_1m": kline_df_1m})

    # Mocking second data loading - returning None (data not found)
    mock_load_1s = mocker.patch.object(
        bt, "_load_1s_klines_for_window", new_callable=AsyncMock
    )
    mock_load_1s.return_value = None

    await bt.run_async()

    # Checking logs - minute scan should pass
    all_log_messages = [str(call) for call in mock_logger.info.call_args_list]
    minute_scan_log_found = any("Minute scan passed" in msg for msg in all_log_messages)

    assert minute_scan_log_found, (
        "There should be a message about a successful minute scan"
    )

    # Checking that there was an attempt to load second data
    assert mock_load_1s.called, (
        "Method _load_1s_klines_for_window should have been called"
    )
