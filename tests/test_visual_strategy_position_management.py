# File: tests/test_visual_strategy_position_management.py

import pytest
import pandas as pd
from bot_module.depthsight_backtester import DepthSightBacktester
from tests.test_visual_strategy_extended import create_test_kline_df
from unittest.mock import patch


@pytest.mark.asyncio
async def test_pm_trailing_stop_atr(mocker):
    """Test: E2E for Trailing Stop by ATR."""
    with patch("bot_module.depthsight_backtester.ta", autospec=True) as mock_ta:
        klines = create_test_kline_df(150, 100)
        mock_ta.atr.return_value = pd.Series([2.0] * 150, index=klines.index)

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
                    "sl_value": 95.0,
                    "tp_type": "fixed_price",
                    "tp_value": 110.0,
                },
            },
            "positionManagement": [
                {
                    "id": "mng1",
                    "type": "trailing_stop",
                    "params": {"type": "ATR", "value": 2.0},
                }
            ],
        }

        signal_fire_idx = 60
        klines.loc[klines.index[signal_fire_idx], ["close"]] = [100.0]
        klines.loc[klines.index[signal_fire_idx + 1], ["high", "low"]] = [105.0, 98.0]
        klines.loc[klines.index[signal_fire_idx + 2], ["high", "low"]] = [108.0, 103.5]
        klines.loc[klines.index[signal_fire_idx + 3], ["high", "low"]] = [105.0, 103.0]

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

    assert len(backtester.trade_log) == 1, "There should be one trade"
    trade = backtester.trade_log[0]
    assert trade["exit_reason"] == "STOP_LOSS"
    assert trade["exit_price"] == pytest.approx(104.0)


@pytest.mark.asyncio
async def test_pm_conditional_exit(mocker):
    """Test: E2E for conditional exit (Conditional Exit)."""
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
                    "sl_value": 95.0,
                    "tp_type": "fixed_price",
                    "tp_value": 110.0,
                },
            },
            "positionManagement": [
                {
                    "id": "mng1",
                    "type": "conditional_exit",
                    "params": {
                        "conditions": {
                            "type": "OR",
                            "children": [
                                {
                                    "type": "rsi_condition",
                                    "params": {"operator": "lt", "value": 40},
                                }
                            ],
                        }
                    },
                }
            ],
        }

        signal_fire_idx = 60
        klines.loc[klines.index[signal_fire_idx], ["close"]] = [100.0]

        klines.loc[klines.index[signal_fire_idx + 1], ["close", "low"]] = [102.0, 96.0]
        klines.loc[klines.index[signal_fire_idx + 2], ["close", "low"]] = [103.0, 96.0]

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

        original_manage_position = backtester.strategy_instance.manage_position

        async def mocked_manage_position(
            position, pair_info, market_data, prev_pair_info
        ):
            idx = pair_info["current_candle_index"]
            if idx == signal_fire_idx + 1:
                pair_info["RSI_14"] = 50
            if idx == signal_fire_idx + 2:
                pair_info["RSI_14"] = 35
            return await original_manage_position(
                position, pair_info, market_data, prev_pair_info
            )

        backtester.strategy_instance.manage_position = mocked_manage_position

        await backtester.run_async()

    assert len(backtester.trade_log) == 1, "There should be one trade"
    trade = backtester.trade_log[0]
    assert trade["exit_reason"] == "CONDITIONAL_EXIT"
    assert trade["exit_price"] == pytest.approx(103.0)


@pytest.mark.asyncio
async def test_pm_partial_take_profit(mocker):
    """Test: E2E for partial position closing."""
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
                    "tp_value": 106.0,
                    "partial_exits": [
                        {"tp_type": "rr_multiplier", "tp_value": 1.0, "size_pct": 50},
                        {"tp_type": "rr_multiplier", "tp_value": 2.0, "size_pct": 30},
                    ],
                },
            },
        }

        signal_fire_idx = 60
        klines.loc[klines.index[signal_fire_idx], ["close", "high"]] = [100.0, 100.5]

        klines.loc[klines.index[signal_fire_idx + 1], ["high", "low"]] = [102.5, 99.0]
        klines.loc[klines.index[signal_fire_idx + 2], ["high", "low"]] = [104.5, 99.0]
        klines.loc[klines.index[signal_fire_idx + 3], ["high", "low"]] = [106.5, 99.0]

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
            risk_params={},
            backtest_risk_params={
                "riskPerTradePercent": 1.0,
                "dailyMaxLossPercent": 1.0,
            },
            initial_balance=10000,
            min_trades_required=0,
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

    assert len(backtester.trade_log) == 1, "There should be one trade"
    trade = backtester.trade_log[0]

    expected_pnl = 60.0

    assert trade["exit_reason"] == "TAKE_PROFIT"
    assert trade["pnl"] == pytest.approx(expected_pnl, abs=1e-6)


@pytest.mark.asyncio
async def test_pm_conditional_management_modify_sl(mocker):
    """E2E test for 'conditional_management'."""
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
                    "id": "mng_cond",
                    "type": "conditional_management",
                    "if_conditions": {
                        "id": "if_pnl_pos",
                        "type": "AND",
                        "children": [
                            {
                                "id": "pnl_check",
                                "type": "price_vs_level",
                                "params": {
                                    "price_source": {
                                        "source": "position_state",
                                        "key": "unrealized_pnl_pct",
                                    },
                                    "operator": "gt",
                                    "level_source": {"source": "value", "value": 0.5},
                                },
                            }
                        ],
                    },
                    "then_actions": [
                        {
                            "id": "then_mod_sl",
                            "type": "modify_stop_loss",
                            "params": {
                                "new_sl_price": {
                                    "source": "position_state",
                                    "key": "entry_price",
                                }
                            },
                        }
                    ],
                }
            ],
        }

        signal_fire_idx = 60
        klines.loc[klines.index[signal_fire_idx], ["close"]] = [100.0]
        klines.loc[klines.index[signal_fire_idx + 1], ["high", "low", "close"]] = [
            101.5,
            100.5,
            101.0,
        ]
        klines.loc[klines.index[signal_fire_idx + 2], ["high", "low", "close"]] = [
            101.0,
            99.5,
            99.8,
        ]

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
            execution_config={"commission_pct": 0.001, "slippage_pct": 0.0},
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

    assert len(backtester.trade_log) == 1, "There should be exactly one trade"
    trade = backtester.trade_log[0]
    assert trade["exit_reason"] == "STOP_LOSS"
    assert trade["exit_price"] == pytest.approx(100.0)
    assert trade["pnl"] < 0


@pytest.mark.asyncio
async def test_pm_scale_in(mocker):
    """E2E test for 'scale_in'."""
    with patch("bot_module.depthsight_backtester.ta", autospec=True) as mock_ta:
        klines = create_test_kline_df(150, 100)
        mock_ta.atr.return_value = pd.Series([2.0] * 150, index=klines.index)

        test_json_config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {"type": "market_activity", "params": {}},
                    {
                        "type": "rsi_condition",
                        "params": {"operator": "lt", "value": 35},
                    },
                ],
            },
            "initialization": {
                "id": "act1",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "atr_multiplier",
                    "sl_value": 2.0,
                    "tp_type": "rr_multiplier",
                    "tp_value": 10.0,
                },
            },
            "positionManagement": [
                {
                    "id": "mng_scale_in",
                    "type": "scale_in",
                    "params": {
                        "add_size_pct_of_initial_risk": 100,
                        "max_entries": 2,
                        "conditions": {
                            "id": "scale_in_root",
                            "type": "AND",
                            "children": [
                                {
                                    "id": "scale_in_rsi",
                                    "type": "rsi_condition",
                                    "params": {"operator": "gt", "value": 65},
                                }
                            ],
                        },
                    },
                }
            ],
        }

        signal_fire_idx = 60
        klines.loc[klines.index[signal_fire_idx], ["close"]] = [100.0]
        klines.loc[klines.index[signal_fire_idx + 1], ["close"]] = [102.0]
        klines.loc[klines.index[signal_fire_idx + 2], ["close"]] = [104.0]
        klines.loc[klines.index[signal_fire_idx + 3], ["low"]] = [90.0]

        for i in range(signal_fire_idx + 1, signal_fire_idx + 3):
            klines.loc[klines.index[i], "low"] = 97.0

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
                "dailyMaxLossPercent": 10.0,
            },
            execution_config={"commission_pct": 0.001, "slippage_pct": 0.0},
            strategy_defaults={"risk_pct_per_trade": 0.01},
            ml_training_config={},
            ml_sim_log_path=None,
            min_foundation_weight_threshold=0.0,
        )

        original_check_signal = backtester.strategy_instance.check_signal_sync
        original_manage_position = backtester.strategy_instance.manage_position
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
                pair_info["RSI_14"] = 30
                pair_info["natr"] = 2.0
                return original_check_signal(
                    pair_info, market_data, prev_pair_info, *args, **kwargs
                )
            return None, 0.0, None

        async def mocked_manage_position(
            position, pair_info, market_data, prev_pair_info
        ):
            idx = pair_info["current_candle_index"]
            if idx == signal_fire_idx + 1:
                pair_info["RSI_14"] = 55
            if idx == signal_fire_idx + 2:
                pair_info["RSI_14"] = 70
            return await original_manage_position(
                position, pair_info, market_data, prev_pair_info
            )

        backtester.strategy_instance.check_signal_sync = single_signal_trigger
        backtester.strategy_instance.manage_position = mocked_manage_position

        await backtester.run_async()

    assert len(backtester.trade_log) == 1, "There should be 1 trade after scale-in"
    trade = backtester.trade_log[0]
    assert trade["entry_price"] >= 100.0
    assert backtester.stats.get("number_of_entries") == 2, (
        "Number of entries should be 2"
    )


@pytest.mark.asyncio
async def test_pm_scale_in_works_across_multiple_trades(mocker):
    with patch("bot_module.depthsight_backtester.ta", autospec=True) as mock_ta:
        klines = create_test_kline_df(150, 100)
        mock_ta.atr.return_value = pd.Series([2.0] * 150, index=klines.index)

        test_json_config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {"type": "market_activity", "params": {}},
                    {
                        "type": "rsi_condition",
                        "params": {"operator": "lt", "value": 35},
                    },
                ],
            },
            "initialization": {
                "id": "act1",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "atr_multiplier",
                    "sl_value": 2.0,
                    "tp_type": "rr_multiplier",
                    "tp_value": 10.0,
                },
            },
            "positionManagement": [
                {
                    "id": "mng_scale_in",
                    "type": "scale_in",
                    "params": {
                        "add_size_pct_of_initial_risk": 100,
                        "max_entries": 2,
                        "conditions": {
                            "id": "scale_in_root",
                            "type": "AND",
                            "children": [
                                {
                                    "id": "scale_in_rsi",
                                    "type": "rsi_condition",
                                    "params": {"operator": "gt", "value": 65},
                                }
                            ],
                        },
                    },
                }
            ],
        }

        klines.loc[klines.index[60], ["close", "low"]] = [100.0, 99.0]
        klines.loc[klines.index[62], ["close", "low"]] = [104.0, 103.0]
        for i in range(61, 65):
            klines.loc[klines.index[i], "low"] = 97.0
        klines.loc[klines.index[65], "low"] = [95.0]

        klines.loc[klines.index[70], ["close", "low"]] = [110.0, 109.0]
        klines.loc[klines.index[72], ["close", "low"]] = [115.0, 114.0]
        for i in range(71, 75):
            klines.loc[klines.index[i], "low"] = 107.0
        klines.loc[klines.index[75], "low"] = [105.0]

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
                "dailyMaxLossPercent": 10.0,
            },
            execution_config={"commission_pct": 0.001, "slippage_pct": 0.0},
            strategy_defaults={"risk_pct_per_trade": 0.01},
            ml_training_config={},
            ml_sim_log_path=None,
            min_foundation_weight_threshold=0.0,
        )

        original_check_signal = backtester.strategy_instance.check_signal_sync
        original_manage_position = backtester.strategy_instance.manage_position

        def mocked_check_signal(
            pair_info, market_data, prev_pair_info, *args, **kwargs
        ):
            idx = pair_info["current_candle_index"]
            if idx == 60 or idx == 70:
                pair_info["RSI_14"] = 30
                pair_info["natr"] = 2.0
                return original_check_signal(
                    pair_info, market_data, prev_pair_info, *args, **kwargs
                )
            return None, 0.0, None

        async def mocked_manage_position(
            position, pair_info, market_data, prev_pair_info
        ):
            idx = pair_info["current_candle_index"]
            if idx == 62 or idx == 72:
                pair_info["RSI_14"] = 70
            else:
                pair_info["RSI_14"] = 50
            return await original_manage_position(
                position, pair_info, market_data, prev_pair_info
            )

        backtester.strategy_instance.check_signal_sync = mocked_check_signal
        backtester.strategy_instance.manage_position = mocked_manage_position

        await backtester.run_async()

    assert len(backtester.trade_log) == 2, "There should be exactly 2 trades in the log"
    assert backtester.stats.get("number_of_entries") == 4, (
        "Total number of entries (2 main + 2 scale-in) should be 4"
    )


@pytest.mark.asyncio
async def test_pm_breakeven_and_partial_tp_on_same_candle(mocker):
    """
    Test: Partial TP and move to BE should trigger on the same candle if conditions are met.
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
                    "partial_exits": [
                        {"tp_type": "rr_multiplier", "tp_value": 1.0, "size_pct": 50}
                    ],
                },
            },
            "positionManagement": [
                {
                    "id": "mng1",
                    "type": "move_to_breakeven",
                    "params": {
                        "target_type": "atr_multiplier",
                        "target_value": 1.5,
                        "offset_pips": 2,
                    },
                }
            ],
        }

        signal_fire_idx = 60
        klines.loc[klines.index[signal_fire_idx], ["close"]] = [100.0]
        klines.loc[klines.index[signal_fire_idx + 1], ["high", "low"]] = [102.1, 100.5]
        klines.loc[klines.index[signal_fire_idx + 2], ["high", "low"]] = [101.5, 100.01]

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

        original_manage_position = backtester.strategy_instance.manage_position

        async def mocked_manage_position(
            position, pair_info, market_data, prev_pair_info
        ):
            pair_info["atr"] = 1.0
            return await original_manage_position(
                position, pair_info, market_data, prev_pair_info
            )

        backtester.strategy_instance.manage_position = mocked_manage_position

        await backtester.run_async()

    assert len(backtester.trade_log) == 1, "There should be one trade"
    trade = backtester.trade_log[0]

    assert trade["num_partial_tp_hits"] == 1, "One partial take should have triggered"
    assert trade["moved_to_be"] is True, "Stop MUST have moved to BE"
    assert trade["exit_reason"] == "SL_AT_BE", "Exit reason - stop at BE"
    assert trade["pnl"] > 0, "Final PnL should be positive"
