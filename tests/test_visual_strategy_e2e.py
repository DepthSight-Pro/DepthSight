# File: tests/test_visual_strategy_e2e.py
# ruff: noqa: F811

import pytest
from bot_module.depthsight_backtester import DepthSightBacktester
from tests.test_visual_strategy_foundations_and_filters import (
    create_test_kline_df,
    visual_strategy_instance,  # noqa: F401 — pytest fixture, import IS usage
)


@pytest.mark.asyncio
async def test_e2e_breakout_retest_and_breakeven(visual_strategy_instance):
    """
    End-to-end test of the full scenario...
    """
    test_json_config = {
        "min_foundation_weight_threshold": 0,
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
                },
                {
                    "type": "price_vs_level",
                    "params": {
                        "price_source": {"source": "candle", "key": "close"},
                        "operator": "gt",
                        "level_source": {
                            "source": "block_result",
                            "block_id": "level1",
                            "key": "detected_level",
                        },
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
                "sl_value": 2.0,
                "tp_type": "rr_multiplier",
                "tp_value": 5.0,
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

    klines = create_test_kline_df(150, 100)
    for i in range(55, 60):
        klines.loc[klines.index[i], ["open", "high", "low", "close"]] = [
            104.5,
            105.0,
            104.0,
            104.7,
        ]
    klines.loc[klines.index[60], ["open", "high", "low", "close"]] = [
        105.1,
        106.0,
        105.0,
        105.5,
    ]
    klines.loc[klines.index[61], ["open", "high", "low", "close"]] = [
        105.5,
        105.6,
        104.9,
        105.2,
    ]
    klines.loc[klines.index[62], ["open", "high", "low", "close"]] = [
        105.2,
        108.5,
        105.1,
        107.8,
    ]
    klines.loc[klines.index[63], ["open", "high", "low", "close"]] = [
        107.8,
        107.9,
        105.0,
        105.1,
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
            pair_info["atr"] = 2.0
            return await original_check_signal(
                pair_info, market_data, prev_pair_info, analysis_level
            )
        return None, 0.0, None

    backtester.strategy_instance.check_signal = single_signal_on_60
    await backtester.run_async()

    assert len(backtester.trade_log) == 1, (
        f"Expected 1 trade, but got: {backtester.trade_log}"
    )
    trade = backtester.trade_log[0]

    assert trade["entry_price"] == pytest.approx(105.0), (
        "Entry price must be at the retest level"
    )
    assert trade["exit_reason"] == "SL_AT_BE", "Exit reason must be 'SL_AT_BE'"
    assert trade["exit_price"] == pytest.approx(105.02), (
        "Exit price must be at the break-even stop level with an offset"
    )
    assert trade["pnl"] > 0, "PnL should be slightly positive due to the stop offset"
