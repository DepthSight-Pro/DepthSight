# File: tests/test_move_to_breakeven_rr.py
"""
Tests to verify move_to_breakeven logic with rr_multiplier.
"""

import pytest
import pandas as pd
from unittest.mock import patch
from bot_module.depthsight_backtester import DepthSightBacktester
from tests.test_visual_strategy_extended import create_test_kline_df


@pytest.mark.asyncio
async def test_move_to_breakeven_rr_multiplier_triggers():
    """
    Test: move_to_breakeven with target_type='rr_multiplier' should trigger
    when the price passes the specified R-multiplier.

    Scenario:
    - Entry: 100.0, SL: 98.0 (risk_distance = 2.0, this is 1R)
    - For 1.5 RR, profit = 1.5 * 2 = 3.0 is needed, i.e., high >= 103.0
    - Expected: stop is moved to BE (100.0 + offset)
    """
    with patch("bot_module.depthsight_backtester.ta", autospec=True) as mock_ta:
        klines = create_test_kline_df(150, 100)  # 150 candles
        mock_ta.atr.return_value = pd.Series([1.0] * 150, index=klines.index)

        test_json_config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {"type": "market_activity", "params": {}},
                    {
                        "type": "price_vs_level",
                        "params": {
                            "price_source": {"source": "candle", "key": "close"},
                            "operator": "gt",
                            "level_source": {"source": "value", "value": 99},
                        },
                    },
                ],
            },
            "initialization": {
                "id": "act1",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "fixed_price",
                    "sl_value": 98.0,  # risk = 2.0
                    "tp_type": "fixed_price",
                    "tp_value": 110.0,
                },
            },
            "positionManagement": [
                {
                    "id": "mng1",
                    "type": "move_to_breakeven",
                    "params": {
                        "target_type": "rr_multiplier",
                        "target_value": 1.5,  # Need 1.5R profit
                        "offset_pips": 2,
                    },
                }
            ],
        }

        signal_fire_idx = 60  # using index 60
        # Entry candle
        klines.loc[klines.index[signal_fire_idx], ["open", "high", "low", "close"]] = [
            100.0,
            100.5,
            99.5,
            100.0,
        ]

        # Candle after entry: high = 103.5 (profit = 3.5 > 1.5R = 3.0) -> BE should trigger
        klines.loc[
            klines.index[signal_fire_idx + 1], ["open", "high", "low", "close"]
        ] = [100.0, 103.5, 99.8, 102.0]

        # Candle after BE: price pulls back and hits stop at BE (100.02)
        klines.loc[
            klines.index[signal_fire_idx + 2], ["open", "high", "low", "close"]
        ] = [102.0, 102.5, 99.5, 99.8]

        backtester = DepthSightBacktester(
            strategy_name="VisualBuilderStrategy",
            symbol="TESTUSDT",
            params={"config": test_json_config},
            historical_data={"kline_1m": klines},
            exchange_info={
                "tick_size": 0.01,
                "lot_params": {"stepSize": 0.001},
                "min_notional": 10.0,
            },
            initial_balance=10000,
            min_trades_required=0,
            risk_params={},
            backtest_risk_params={
                "riskPerTradePercent": 1.0,
                "dailyMaxLossPercent": 1.0,
            },
            execution_config={"commission_pct": 0.0, "slippage_pct": 0.0},
            strategy_defaults={"risk_pct_per_trade": 0.01},
            ml_training_config={},
            ml_sim_log_path=None,
            min_foundation_weight_threshold=0.0,
        )

        original_check_signal = backtester.strategy_instance.check_signal_sync
        signal_fired = False

        def single_signal_trigger(
            pair_info, market_data, prev_pair_info, *args, **kwargs
        ):
            nonlocal signal_fired
            if (
                pair_info["current_candle_index"] == signal_fire_idx
                and not signal_fired
            ):
                signal_fired = True
                pair_info["natr"] = 2.0
                return original_check_signal(
                    pair_info, market_data, prev_pair_info, *args, **kwargs
                )
            return None, 0.0, None

        backtester.strategy_instance.check_signal_sync = single_signal_trigger

        await backtester.run_async()

    # Checks
    assert len(backtester.trade_log) == 1, (
        f"There should be one trade, but received: {len(backtester.trade_log)}"
    )
    trade = backtester.trade_log[0]

    # Main check: stop should have moved to BE and triggered
    assert trade["exit_reason"] == "SL_AT_BE", (
        f"Expected exit by SL_AT_BE, but got: {trade['exit_reason']}"
    )

    # Check that the exit price is approximately equal to entry + offset (100.0 + 0.02 = 100.02)
    assert trade["exit_price"] == pytest.approx(100.02, abs=0.01), (
        f"Expected exit_price ~100.02, received: {trade['exit_price']}"
    )

    # PnL should be around zero (small plus due to offset)
    assert trade["pnl"] >= 0, f"PnL on BE exit should be >= 0, got: {trade['pnl']}"


@pytest.mark.asyncio
async def test_move_to_breakeven_rr_not_triggers_if_below_target():
    """
    Test: move_to_breakeven should NOT trigger if the price has not reached the target R:R.

    Scenario:
    - Entry: 100.0, SL: 98.0 (risk_distance = 2.0)
    - For 1.5 RR, profit >= 3.0 is needed (high >= 103.0)
    - High reaches only 102.5 (profit = 2.5, RR = 1.25 < 1.5)
    - Expected: stop remains at 98.0, position closes by SL
    """
    with patch("bot_module.depthsight_backtester.ta", autospec=True) as mock_ta:
        klines = create_test_kline_df(150, 100)
        mock_ta.atr.return_value = pd.Series([1.0] * 150, index=klines.index)

        test_json_config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {"type": "market_activity", "params": {}},
                    {
                        "type": "price_vs_level",
                        "params": {
                            "price_source": {"source": "candle", "key": "close"},
                            "operator": "gt",
                            "level_source": {"source": "value", "value": 99},
                        },
                    },
                ],
            },
            "initialization": {
                "id": "act1",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "fixed_price",
                    "sl_value": 98.0,
                    "tp_type": "fixed_price",
                    "tp_value": 110.0,
                },
            },
            "positionManagement": [
                {
                    "id": "mng1",
                    "type": "move_to_breakeven",
                    "params": {
                        "target_type": "rr_multiplier",
                        "target_value": 1.5,  # Need 1.5R = 3.0 profit
                        "offset_pips": 2,
                    },
                }
            ],
        }

        signal_fire_idx = 60
        klines.loc[klines.index[signal_fire_idx], ["open", "high", "low", "close"]] = [
            100.0,
            100.5,
            99.5,
            100.0,
        ]

        # High = 102.5 (profit = 2.5, RR = 1.25) - NOT enough for 1.5 RR
        klines.loc[
            klines.index[signal_fire_idx + 1], ["open", "high", "low", "close"]
        ] = [100.0, 102.5, 99.8, 101.0]

        # Price falls and hits the original SL (98.0)
        klines.loc[
            klines.index[signal_fire_idx + 2], ["open", "high", "low", "close"]
        ] = [101.0, 101.5, 97.5, 97.8]

        backtester = DepthSightBacktester(
            strategy_name="VisualBuilderStrategy",
            symbol="TESTUSDT",
            params={"config": test_json_config},
            historical_data={"kline_1m": klines},
            exchange_info={
                "tick_size": 0.01,
                "lot_params": {"stepSize": 0.001},
                "min_notional": 10.0,
            },
            initial_balance=10000,
            min_trades_required=0,
            risk_params={},
            backtest_risk_params={
                "riskPerTradePercent": 1.0,
                "dailyMaxLossPercent": 1.0,
            },
            execution_config={"commission_pct": 0.0, "slippage_pct": 0.0},
            strategy_defaults={"risk_pct_per_trade": 0.01},
            ml_training_config={},
            ml_sim_log_path=None,
            min_foundation_weight_threshold=0.0,
        )

        original_check_signal = backtester.strategy_instance.check_signal_sync
        signal_fired = False

        def single_signal_trigger(
            pair_info, market_data, prev_pair_info, *args, **kwargs
        ):
            nonlocal signal_fired
            if (
                pair_info["current_candle_index"] == signal_fire_idx
                and not signal_fired
            ):
                signal_fired = True
                pair_info["natr"] = 2.0
                return original_check_signal(
                    pair_info, market_data, prev_pair_info, *args, **kwargs
                )
            return None, 0.0, None

        backtester.strategy_instance.check_signal_sync = single_signal_trigger

        await backtester.run_async()

    assert len(backtester.trade_log) == 1
    trade = backtester.trade_log[0]

    # Should be a regular STOP_LOSS, not SL_AT_BE
    assert trade["exit_reason"] == "STOP_LOSS", (
        f"Expected STOP_LOSS (RR not reached), got: {trade['exit_reason']}"
    )
    assert trade["exit_price"] == pytest.approx(98.0, abs=0.01), (
        "Expected exit_price = 98.0 (original SL)"
    )


@pytest.mark.asyncio
async def test_move_to_breakeven_rr_short_position():
    """
    Test: move_to_breakeven with rr_multiplier for SHORT position.

    Scenario:
    - Entry: 100.0, SL: 102.0 (risk_distance = 2.0)
    - For 1.5 RR, profit >= 3.0 is needed, i.e., low <= 97.0
    - Expected: stop is moved to BE (100.0 - offset = 99.98)
    """
    with patch("bot_module.depthsight_backtester.ta", autospec=True) as mock_ta:
        klines = create_test_kline_df(150, 100)
        mock_ta.atr.return_value = pd.Series([1.0] * 150, index=klines.index)

        test_json_config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {"type": "market_activity", "params": {}},
                    {
                        "type": "price_vs_level",
                        "params": {
                            "price_source": {"source": "candle", "key": "close"},
                            "operator": "lt",  # SHORT condition
                            "level_source": {"source": "value", "value": 101},
                        },
                    },
                ],
            },
            "initialization": {
                "id": "act1",
                "type": "open_position",
                "params": {
                    "direction": "SHORT",
                    "sl_type": "fixed_price",
                    "sl_value": 102.0,  # SL above entry
                    "tp_type": "fixed_price",
                    "tp_value": 90.0,
                },
            },
            "positionManagement": [
                {
                    "id": "mng1",
                    "type": "move_to_breakeven",
                    "params": {
                        "target_type": "rr_multiplier",
                        "target_value": 1.5,
                        "offset_pips": 2,
                    },
                }
            ],
        }

        signal_fire_idx = 60
        klines.loc[klines.index[signal_fire_idx], ["open", "high", "low", "close"]] = [
            100.0,
            100.5,
            99.5,
            100.0,
        ]

        # Low = 96.5 (profit = 3.5 > 1.5R = 3.0) -> BE should trigger
        klines.loc[
            klines.index[signal_fire_idx + 1], ["open", "high", "low", "close"]
        ] = [100.0, 100.2, 96.5, 97.0]

        # Price rises and hits BE (99.98)
        klines.loc[
            klines.index[signal_fire_idx + 2], ["open", "high", "low", "close"]
        ] = [97.0, 100.5, 96.8, 100.2]

        backtester = DepthSightBacktester(
            strategy_name="VisualBuilderStrategy",
            symbol="TESTUSDT",
            params={"config": test_json_config},
            historical_data={"kline_1m": klines},
            exchange_info={
                "tick_size": 0.01,
                "lot_params": {"stepSize": 0.001},
                "min_notional": 10.0,
            },
            initial_balance=10000,
            min_trades_required=0,
            risk_params={},
            backtest_risk_params={
                "riskPerTradePercent": 1.0,
                "dailyMaxLossPercent": 1.0,
            },
            execution_config={"commission_pct": 0.0, "slippage_pct": 0.0},
            strategy_defaults={"risk_pct_per_trade": 0.01},
            ml_training_config={},
            ml_sim_log_path=None,
            min_foundation_weight_threshold=0.0,
        )

        original_check_signal = backtester.strategy_instance.check_signal_sync
        signal_fired = False

        def single_signal_trigger(
            pair_info, market_data, prev_pair_info, *args, **kwargs
        ):
            nonlocal signal_fired
            if (
                pair_info["current_candle_index"] == signal_fire_idx
                and not signal_fired
            ):
                signal_fired = True
                pair_info["natr"] = 2.0
                return original_check_signal(
                    pair_info, market_data, prev_pair_info, *args, **kwargs
                )
            return None, 0.0, None

        backtester.strategy_instance.check_signal_sync = single_signal_trigger

        await backtester.run_async()

    assert len(backtester.trade_log) == 1
    trade = backtester.trade_log[0]

    # Main check: SL_AT_BE should also trigger for SHORT
    assert trade["exit_reason"] == "SL_AT_BE", (
        f"Expected SL_AT_BE for SHORT, received: {trade['exit_reason']}"
    )

    # For SHORT: BE = entry - offset = 100.0 - 0.02 = 99.98
    assert trade["exit_price"] == pytest.approx(99.98, abs=0.01), (
        f"Expected exit_price ~99.98, received: {trade['exit_price']}"
    )
