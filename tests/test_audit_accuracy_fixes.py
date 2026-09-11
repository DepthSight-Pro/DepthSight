import pandas as pd
from datetime import datetime, timezone
from bot_module.fast_vector_backtester import FastVectorBacktester
from tasks import _normalize_vector_results


def test_candle_source_lookahead_bias_fixed():
    """
    Audit Finding #1:
    At 10:01, the engine should only know the close of the closed 1h candle (09:00-10:00).
    It must NOT leak the close of the unclosed 10:00-11:00 candle.
    """
    idx_1m = pd.date_range("2024-01-01 10:00", "2024-01-01 10:59", freq="1min")
    df_1m = pd.DataFrame(
        {
            "open": [100.0] * len(idx_1m),
            "high": [101.0] * len(idx_1m),
            "low": [99.0] * len(idx_1m),
            "close": [100.0] * len(idx_1m),
            "volume": [1000.0] * len(idx_1m),
        },
        index=idx_1m,
    )

    idx_1h = pd.to_datetime(["2024-01-01 09:00", "2024-01-01 10:00"])
    df_1h = pd.DataFrame(
        {
            "open": [95.0, 100.0],
            "high": [105.0, 115.0],
            "low": [95.0, 99.0],
            "close": [100.0, 110.0],  # 09:00 close is 100, 10:00 close is 110
            "volume": [5000.0, 5000.0],
        },
        index=idx_1h,
    )

    bt = FastVectorBacktester(
        klines_input={"1m": df_1m, "1h": df_1h},
        strategy_json={
            "entryConditions": {"type": "AND", "children": []},
            "initialization": {},
        },
    )

    candle_operand = {
        "source": "candle",
        "key": "close",
        "timeframe": "1h",
    }
    resolved = bt._resolve_value_series(candle_operand)

    # At 10:01 (and throughout 10:00-10:59), the latest closed 1h candle is 09:00 (close=100.0).
    # The 10:00-11:00 candle (close=110.0) is not closed yet and must NOT be visible!
    ts_1001 = pd.Timestamp("2024-01-01 10:01")
    assert resolved.loc[ts_1001] == 100.0, (
        f"Expected 100.0, got {resolved.loc[ts_1001]} (future leak!)"
    )

    # Changing the future close of 10:00 candle from 110 to 90 must not change the value at 10:01
    df_1h_future_change = df_1h.copy()
    df_1h_future_change.loc[pd.Timestamp("2024-01-01 10:00"), "close"] = 90.0
    bt2 = FastVectorBacktester(
        klines_input={"1m": df_1m, "1h": df_1h_future_change},
        strategy_json={
            "entryConditions": {"type": "AND", "children": []},
            "initialization": {},
        },
    )
    resolved2 = bt2._resolve_value_series(candle_operand)
    assert resolved2.loc[ts_1001] == 100.0


def test_sl_executed_before_liquidation_on_extreme_candle():
    """
    Audit Finding #3:
    Balance 1000, 100 contracts at 100, SL at 95.
    Candle with Open=100, Low=80, High=100, Close=85.
    SL at 95 must trigger before liquidation at 80.
    """
    # 30 bars so indicator warmups pass cleanly
    times = pd.date_range("2024-01-01 00:00", periods=30, freq="1min")
    opens = [100.0] * 30
    highs = [100.0] * 30
    lows = [100.0] * 30
    closes = [100.0] * 30
    # Bar 2 drops to 80 (would liquidate 10x position if no SL)
    lows[2] = 80.0
    closes[2] = 85.0

    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100.0] * 30,
        },
        index=times,
    )

    strategy = {
        "id": "test-strat-1",
        "min_foundation_weight_threshold": 0,
        "riskManagement": {"maxStopDistancePercent": 25.0},
        "entryConditions": {
            "id": "e1",
            "type": "AND",
            "children": [],
        },
        "initialization": {
            "type": "open_position",
            "params": {
                "direction": "LONG",
                "sl_type": "fixed_price",
                "sl_value": 96.0,
                "tp_type": "percent",
                "tp_value": 50.0,
            },
        },
    }

    bt = FastVectorBacktester(
        klines_input=df,
        strategy_json=strategy,
        initial_balance=1000.0,
        risk_params={"maxStopDistancePercent": 25.0},
    )
    bt.run()
    trades = bt.trade_log
    assert len(trades) >= 1
    first_trade = trades[0]
    assert first_trade["exit_reason"] == "STOP_LOSS", (
        f"Expected STOP_LOSS, got {first_trade['exit_reason']}"
    )
    assert first_trade["exit_price"] < 97.0 and first_trade["exit_price"] > 95.0


def test_sl_gap_through_fills_at_open():
    """
    Audit Finding #3:
    LONG position entered at 100, SL at 96.
    Next candle opens with gap at 90 (High=92, Low=89, Close=90).
    Exit price must execute at Open=90 (with slippage), NOT at 96.
    """
    times = pd.date_range("2024-01-01 00:00", periods=30, freq="1min")
    opens = [100.0] * 30
    highs = [100.0] * 30
    lows = [100.0] * 30
    closes = [100.0] * 30
    # Bar 2 opens at 90 with gap below stop-loss of 96
    opens[2] = 90.0
    highs[2] = 92.0
    lows[2] = 89.0
    closes[2] = 90.0

    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [100.0] * 30,
        },
        index=times,
    )

    strategy = {
        "id": "test-strat-2",
        "min_foundation_weight_threshold": 0,
        "riskManagement": {"maxStopDistancePercent": 25.0},
        "entryConditions": {
            "id": "e1",
            "type": "AND",
            "children": [],
        },
        "initialization": {
            "type": "open_position",
            "params": {
                "direction": "LONG",
                "sl_type": "fixed_price",
                "sl_value": 96.0,
                "tp_type": "percent",
                "tp_value": 50.0,
            },
        },
    }

    bt = FastVectorBacktester(
        klines_input=df,
        strategy_json=strategy,
        initial_balance=1000.0,
        risk_params={"maxStopDistancePercent": 25.0},
    )
    bt.run()
    trades = bt.trade_log
    assert len(trades) >= 1
    first_trade = trades[0]
    assert first_trade["exit_reason"] == "STOP_LOSS"
    # Gap fill at 90 (with slippage ~90 * (1 - 0.0005) = 89.955), definitely NOT 96
    assert first_trade["exit_price"] <= 90.5, (
        f"Expected gap fill around 90, got {first_trade['exit_price']}"
    )


def test_end_of_data_and_final_equity():
    """
    Audit Finding #3 & #5:
    END_OF_DATA is excluded from trades count, but final_equity and total_return_all
    reflect the true equity curve including the open position at the end.
    """
    normalized_trades = [
        {
            "timestamp_entry": datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
            "timestamp_exit": datetime(2024, 1, 1, 2, tzinfo=timezone.utc),
            "pnl": 100.0,
            "commission": 5.0,
            "exit_reason": "TAKE_PROFIT",
        },
        {
            "timestamp_entry": datetime(2024, 1, 1, 3, tzinfo=timezone.utc),
            "timestamp_exit": datetime(2024, 1, 1, 4, tzinfo=timezone.utc),
            "pnl": -50.0,
            "commission": 2.0,
            "exit_reason": "END_OF_DATA",
        },
    ]

    normalized = _normalize_vector_results(
        raw_results={"final_equity": 10050.0, "total_return_all": 0.5},
        normalized_trades=normalized_trades,
        total_commission=7.0,
        initial_balance=10000.0,
    )

    assert normalized["trades"] == 1
    assert normalized["trades_all"] == 2
    assert normalized["excluded_end_of_data_trades"] == 1
    assert normalized["total_pnl"] == 100.0
    assert normalized["final_equity"] == 10050.0
    assert normalized["total_return_all"] == 0.5


def test_higher_timeframe_local_level_synchronization():
    """
    Verifies that local_level series from higher timeframes (e.g. 5m)
    are synchronized with candle.close on 1m resolution without look-ahead
    bias and without double-shift misalignment.
    """
    n_candles_5m = 30
    dates_5m = pd.date_range("2024-01-01 00:00:00", periods=n_candles_5m, freq="5min", tz="UTC")
    df_5m = pd.DataFrame(
        {
            "open": [100.0] * n_candles_5m,
            "high": [105.0] * n_candles_5m,
            "low": [98.0] * n_candles_5m,
            "close": [100.0] * n_candles_5m,
            "volume": [1000.0] * n_candles_5m,
        },
        index=dates_5m,
    )
    # Candle 25 breaks below the previous 20 candles' low (low was 98.0, candle 25 closes at 95.0)
    df_5m.iloc[25, df_5m.columns.get_loc("close")] = 95.0
    df_5m.iloc[25, df_5m.columns.get_loc("low")] = 94.0
    # Candle 26-28 drop further to hit TP (entry ~100, 5% TP is 95 or lower)
    df_5m.iloc[26:29, df_5m.columns.get_loc("low")] = 90.0
    df_5m.iloc[26:29, df_5m.columns.get_loc("close")] = 91.0

    n_candles_1m = n_candles_5m * 5
    dates_1m = pd.date_range("2024-01-01 00:00:00", periods=n_candles_1m, freq="1min", tz="UTC")
    df_1m = pd.DataFrame(
        {
            "open": [100.0] * n_candles_1m,
            "high": [105.0] * n_candles_1m,
            "low": [98.0] * n_candles_1m,
            "close": [100.0] * n_candles_1m,
            "volume": [200.0] * n_candles_1m,
        },
        index=dates_1m,
    )
    # Mirror price action on 1m
    df_1m.iloc[125:130, df_1m.columns.get_loc("close")] = 95.0
    df_1m.iloc[125:130, df_1m.columns.get_loc("low")] = 94.0
    df_1m.iloc[130:145, df_1m.columns.get_loc("low")] = 90.0
    df_1m.iloc[130:145, df_1m.columns.get_loc("close")] = 91.0

    strategy = {
        "strategy_name": "VisualBuilderStrategy",
        "symbol": "BTCUSDT",
        "marketType": "FUTURES",
        "entryTrigger": {"type": "on_candle_close", "timeframe": "5m"},
        "entryConditions": {
            "id": "root",
            "type": "OR",
            "children": [
                {
                    "id": "signal",
                    "type": "AND",
                    "children": [
                        {
                            "id": "channel",
                            "type": "local_level",
                            "params": {
                                "timeframe": "5m",
                                "lookback_period": 20,
                                "is_data_provider": True,
                                "level_type": "low",
                            },
                        },
                        {
                            "id": "break",
                            "type": "value_comparison",
                            "params": {
                                "operator": "lt",
                                "leftOperand": {"source": "candle", "key": "close", "timeframe": "5m", "shift": 0},
                                "rightOperand": {
                                    "source": "block_result",
                                    "block_id": "channel",
                                    "key": "detected_level",
                                },
                            },
                        },
                    ],
                }
            ],
        },
        "initialization": {
            "id": "init",
            "type": "open_position",
            "params": {
                "direction": "SHORT",
                "risk_type": "percent_balance",
                "risk_value": 1,
                "sl_type": "percent",
                "sl_value": 5.0,
                "tp_type": "percent",
                "tp_value": 5.0,
            },
        },
    }

    bt = FastVectorBacktester(
        historical_data={"kline_1m": df_1m, "kline_5m": df_5m},
        strategy_json=strategy,
        params=strategy,
        initial_balance=1000.0,
        risk_params={"maxStopDistancePercent": 25.0},
    )
    bt.run()
    assert len(bt.trade_log) >= 1, "Expected breakout trade to be registered"

