import pytest
import pandas as pd
from unittest.mock import patch
from bot_module.depthsight_backtester import DepthSightBacktester
from tests.test_visual_strategy_extended import create_test_kline_df

# Ensure that the strategy is registered
from bot_module.strategy import STRATEGIES
from bot_module.genetic_adapter import GeneticCompatibleStrategy

if GeneticCompatibleStrategy.NAME not in STRATEGIES:
    STRATEGIES[GeneticCompatibleStrategy.NAME] = GeneticCompatibleStrategy


@pytest.mark.asyncio
async def test_genetic_adapter_rr_breakeven_with_data_loss():
    """
    The test checks the scenario:
    1. Genetic strategy opens a position.
    2. "Memory loss" occurs (initial_stop_loss becomes None).
    3. Price reaches the R:R target.
    4. BE should trigger thanks to the fallback mechanism in BaseStrategy.
    """
    with patch("bot_module.depthsight_backtester.ta", autospec=True) as mock_ta:
        # 1. Data preparation
        klines = create_test_kline_df(150, 100)
        mock_ta.atr.return_value = pd.Series([1.0] * 150, index=klines.index)

        # 2. Config
        test_json_config = {
            "name": "Genetic Strategy",
            # Use the correct key for the reasons filter
            "min_total_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "type": "price_vs_level",
                        "params": {
                            "price_source": {"source": "candle", "key": "close"},
                            "operator": "gt",
                            "level_source": {"source": "value", "value": 99},
                        },
                    }
                ],
            },
            "initialization": {
                "id": "act1",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "fixed_price",
                    "sl_value": 98.0,  # SL = 98.0 (Risk = 2.0)
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
                        "target_value": 1.0,  # RR = 1. High must be >= 102.0
                        "offset_pips": 2,
                    },
                }
            ],
        }

        # 3. Market scenario
        signal_fire_idx = 60
        # Entry at 100.0
        klines.loc[klines.index[signal_fire_idx], ["open", "high", "low", "close"]] = [
            100.0,
            100.5,
            99.5,
            100.0,
        ]

        # Next candle: High = 103.0. Profit 3.0. Risk 2.0. RR = 1.5 > 1.0.
        # Break-even should trigger.
        klines.loc[
            klines.index[signal_fire_idx + 1], ["open", "high", "low", "close"]
        ] = [100.0, 103.0, 99.8, 102.0]

        # Candle hitting BE (or stop, if BE did not trigger)
        klines.loc[
            klines.index[signal_fire_idx + 2], ["open", "high", "low", "close"]
        ] = [102.0, 102.5, 99.5, 99.8]

        symbol = "GENETIC_TEST"

        # 4. Backtester initialization
        backtester = DepthSightBacktester(
            strategy_name="GeneticStrategy",
            symbol=symbol,
            strategy_json=test_json_config,
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
            include_eod_in_log=True,
        )

        assert backtester.strategy_instance is not None, "Strategy was not initialized!"

        # --- Forcefully set the config so the strategy works in visual mode ---
        # This ensures that is_visual_strategy becomes True inside check_signal_sync
        if "config" not in backtester.strategy_instance._instance_params:
            backtester.strategy_instance._instance_params["config"] = test_json_config

        # Just in case, update the threshold as well
        backtester.strategy_instance.min_total_foundation_weight_threshold = 0.0

        # 5. HOOK FOR DATA LOSS SIMULATION
        original_check_signal = backtester.strategy_instance.check_signal_sync
        signal_fired = False

        def sabotaging_hook(pair_info, market_data, prev_pair_info, *args, **kwargs):
            nonlocal signal_fired

            # Get position by symbol
            current_position = backtester.positions.get(symbol)

            # If the position is already open
            if current_position and current_position.remaining_quantity > 0:
                # === BUG SIMULATION: removing initial_stop_loss ===
                if hasattr(current_position, "initial_stop_loss"):
                    current_position.initial_stop_loss = None
                # =================================================

            # Entry logic
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

        backtester.strategy_instance.check_signal_sync = sabotaging_hook

        # 6. Run
        await backtester.run_async()

    # 7. Checks
    # Output the trade log for debugging if the assertion fails
    print(f"\nTrade Log: {backtester.trade_log}")

    assert len(backtester.trade_log) == 1, (
        f"Trade not executed. Log: {backtester.trade_log}"
    )
    trade = backtester.trade_log[0]

    print(f"Exit Reason: {trade['exit_reason']}")
    print(f"Exit Price: {trade['exit_price']}")

    # Checking Fallback operation (if initial_stop_loss is lost, BE should trigger)
    assert trade["exit_reason"] == "SL_AT_BE", (
        f"Expected SL_AT_BE, received {trade['exit_reason']}"
    )

    # Price check (Entry 100.0 + 2 pips (0.02) = 100.02)
    assert trade["exit_price"] == pytest.approx(100.02, abs=0.01)


if __name__ == "__main__":
    import asyncio

    asyncio.run(test_genetic_adapter_rr_breakeven_with_data_loss())
