# tests/test_fast_vector_backtester.py
import pytest
import pandas as pd
import numpy as np
import bot_module.fast_vector_backtester as fvb_module
from bot_module.fast_vector_backtester import FastVectorBacktester
from bot_module.trainer import Trainer

pd_ta = pytest.importorskip("pandas_ta")


def test_fast_vector_extracts_visual_config_from_config_data_wrapper():
    params = {
        "strategy_name": "CustomStrategyName",
        "config_data": {
            "entryConditions": {"type": "AND", "children": []},
            "initialization": {
                "type": "open_position",
                "params": {"direction": "LONG"},
            },
        },
    }

    strategy_json = FastVectorBacktester._extract_strategy_json(params)

    assert "entryConditions" in strategy_json
    assert "initialization" in strategy_json


def test_trainer_collects_visual_requirements_independent_of_strategy_name():
    trainer = Trainer.__new__(Trainer)
    trainer.strategy_defaults = {}
    params = {
        "config": {
            "entryConditions": {
                "type": "tape_analysis",
                "params": {"timeframe": "5m"},
            }
        }
    }

    requirements = trainer.get_data_requirements_for_strategy(
        "CustomStrategyName",
        params,
        symbol="TESTUSDT",
        market_type="futures_usdtm",
    )

    assert "aggTrade" in requirements
    assert "kline_5m" in requirements


@pytest.fixture
def fvb_klines_df() -> pd.DataFrame:
    """A longer and more varied DataFrame for testing."""
    data = {
        "open": [100.0, 102.0, 101.0, 103.0, 105.0, 104.0, 106.0, 107.0, 105.0, 103.0]
        * 10,
        "high": [101.0, 103.0, 102.0, 104.0, 106.0, 105.0, 107.0, 108.0, 106.0, 104.0]
        * 10,
        "low": [99.0, 101.0, 100.0, 102.0, 104.0, 103.0, 105.0, 106.0, 104.0, 102.0]
        * 10,
        "close": [101.0, 101.0, 102.0, 104.0, 104.0, 105.0, 106.0, 105.0, 104.0, 103.0]
        * 10,
        "volume": [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0, 180.0, 190.0]
        * 10,
    }
    index = pd.to_datetime(pd.date_range(start="2023-01-01", periods=100, freq="1min"))
    df = pd.DataFrame(data, index=index)
    return df


@pytest.fixture
def new_format_strategy_json() -> dict:
    """Strategy in the NEW format: LONG when RSI(14) > 60."""
    return {
        "id": "test-strat-1",
        "name": "Test RSI Strategy",
        "symbol": "TESTUSDT",
        "marketType": "FUTURES",
        "min_foundation_weight_threshold": 0,
        "filters": {"id": "f_root", "type": "AND", "children": []},
        "entryTrigger": {"type": "on_candle_close", "timeframe": "1m"},
        "entryConditions": {
            "id": "e_root",
            "type": "AND",
            "children": [
                {
                    "id": "rsi_cond_1",
                    "type": "rsi_condition",
                    "params": {"period": 14, "operator": "gt", "value": 60},
                }
            ],
        },
        "initialization": {
            "id": "init1",
            "type": "open_position",
            "params": {
                "sl_type": "percent",
                "sl_value": 1.5,
                "tp_type": "percent",
                "tp_value": 3.0,
            },
        },
        "positionManagement": [],
    }


def test_fvb_initialization(fvb_klines_df, new_format_strategy_json):
    """Test of FVB initialization with the new format."""
    fvb = FastVectorBacktester(fvb_klines_df, new_format_strategy_json)
    assert not fvb.main_df.empty
    # In the new backtester, strategy_json is normalized (expanded from config_data if present)
    assert fvb.strategy_json["id"] == "test-strat-1"


def test_fvb_prepare_data(fvb_klines_df, new_format_strategy_json):
    """Test of data preparation and indicator calculation from the new format."""
    fvb = FastVectorBacktester(fvb_klines_df, new_format_strategy_json)
    fvb._prepare_data()
    # Indicators are now placed in signals
    assert "RSI_14" in fvb.signals.columns
    assert not fvb.signals["RSI_14"].isnull().all()


def test_fvb_run_produces_trades(fvb_klines_df, new_format_strategy_json):
    """Test of the full run cycle with the new format."""
    # Create a clean, monotonic trend to ensure RSI triggers.
    num_rows = len(fvb_klines_df)
    fvb_klines_df["close"] = np.linspace(100, 150, num_rows)

    # Expand high and low so that trades can close by SL/TP.
    fvb_klines_df["high"] = fvb_klines_df["close"] * 1.1
    fvb_klines_df["low"] = fvb_klines_df["close"] * 0.9

    fvb = FastVectorBacktester(fvb_klines_df, new_format_strategy_json)
    results = fvb.run()

    assert isinstance(results, dict)
    assert "total_trades" in results
    assert results["total_trades"] > 0
    assert len(fvb.trade_log) > 0


def test_fvb_no_trades_scenario(fvb_klines_df):
    """Test where the new format conditions are never met."""
    strategy_json = {
        "entryConditions": {
            "id": "e_root",
            "type": "AND",
            "children": [
                {
                    "id": "rsi_cond_1",
                    "type": "rsi_condition",
                    "params": {"period": 14, "operator": "gt", "value": 9999},
                }  # Unfeasible
            ],
        },
        "initialization": {
            "params": {
                "sl_type": "percent",
                "sl_value": 1.0,
                "tp_type": "percent",
                "tp_value": 2.0,
            }
        },
    }
    fvb = FastVectorBacktester(fvb_klines_df, strategy_json)
    results = fvb.run()

    assert results["total_trades"] == 0
    # In default KPIs, profit_factor may be missing, checking what is available
    assert results["total_pnl_pct"] == 0.0


def _make_condition_bt(data_context: dict, **kwargs) -> FastVectorBacktester:
    strategy_json = {
        "entryConditions": {"id": "root", "type": "AND", "children": []},
        "initialization": {
            "params": {
                "sl_type": "percent",
                "sl_value": 1.0,
                "tp_type": "percent",
                "tp_value": 2.0,
            }
        },
    }
    return FastVectorBacktester(data_context, strategy_json, **kwargs)


def _make_weight_test_df(periods: int = 200, start: float = 100.0) -> pd.DataFrame:
    index = pd.date_range("2023-01-01", periods=periods, freq="1min")
    close = np.linspace(start, start + 5.0, periods)
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
            "volume": np.linspace(100, 300, periods),
        },
        index=index,
    )


def test_vector_significant_level_respects_level_type():
    idx_1m = pd.date_range(start="2023-01-03 10:00", periods=3, freq="1min")
    df_1m = pd.DataFrame(
        {
            "open": [104.8, 104.9, 105.0],
            "high": [105.0, 105.1, 105.2],
            "low": [104.7, 104.8, 104.9],
            "close": [104.9, 105.0, 105.1],
            "volume": [100.0, 100.0, 100.0],
        },
        index=idx_1m,
    )
    idx_1d = pd.to_datetime(["2023-01-01", "2023-01-02", "2023-01-03"])
    df_1d = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [103.0, 105.0, 106.0],
            "low": [99.0, 95.0, 98.0],
            "close": [101.0, 102.0, 103.0],
            "volume": [10.0, 10.0, 10.0],
        },
        index=idx_1d,
    )

    bt = _make_condition_bt({"1m": df_1m, "1d": df_1d})

    daily_high = bt._evaluate_significant_level(
        {
            "level_type": "daily_high",
            "proximity_type": "percentage",
            "proximity_value": 0.2,
        }
    )
    daily_low = bt._evaluate_significant_level(
        {
            "level_type": "daily_low",
            "proximity_type": "percentage",
            "proximity_value": 0.2,
        }
    )

    assert bool(daily_high.iloc[-1]) is True
    assert bool(daily_low.iloc[-1]) is False


def test_vector_local_level_detects_recent_level_and_provider_mode():
    idx = pd.date_range(start="2023-01-01 00:00", periods=5, freq="1min")
    df_1m = pd.DataFrame(
        {
            "open": [100.0, 101.0, 101.3, 101.5, 101.9],
            "high": [100.5, 102.0, 101.6, 101.8, 102.0],
            "low": [99.7, 100.7, 101.0, 101.2, 101.7],
            "close": [100.2, 101.2, 101.4, 101.6, 101.95],
            "volume": [100.0, 100.0, 100.0, 100.0, 100.0],
        },
        index=idx,
    )

    bt = _make_condition_bt({"1m": df_1m})

    result = bt._evaluate_local_level(
        {
            "timeframe": "1m",
            "lookback_period": 3,
            "proximity_type": "percentage",
            "proximity_value": 0.1,
        }
    )
    provider = bt._evaluate_local_level({"is_data_provider": True})

    assert bool(result.iloc[-1]) is True
    assert provider.all()


def test_vector_local_level_uses_window_extremes_not_nearest_candle_wick():
    idx = pd.date_range(start="2023-01-01 00:00", periods=8, freq="1min")
    df_1m = pd.DataFrame(
        {
            "open": [100.0] * 8,
            "high": [100.2, 100.2, 110.0, 100.2, 100.2, 100.2, 100.2, 100.2],
            "low": [99.8, 99.8, 99.8, 90.0, 99.8, 99.8, 99.8, 99.8],
            "close": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.1],
            "volume": [100.0] * 8,
        },
        index=idx,
    )

    bt = _make_condition_bt({"1m": df_1m})
    params = {
        "timeframe": "1m",
        "lookback_period": 5,
        "proximity_type": "percentage",
        "proximity_value": 0.5,
    }

    detected = bt._resolve_local_level_series(params)
    result = bt._evaluate_local_level(params)

    assert detected.iloc[-1] == pytest.approx(110.0)
    assert bool(result.iloc[-1]) is False


def test_vector_level_touch_uses_only_closed_higher_timeframe_candles():
    idx_1m = pd.date_range(start="2023-01-01 00:00", periods=6, freq="1min")
    df_1m = pd.DataFrame(
        {
            "open": [100.0] * 6,
            "high": [101.0] * 6,
            "low": [99.0] * 6,
            "close": [100.0] * 6,
            "volume": [100.0] * 6,
        },
        index=idx_1m,
    )
    df_1h = pd.DataFrame(
        {
            "open": [100.0],
            "high": [200.1],
            "low": [199.9],
            "close": [200.0],
            "volume": [100.0],
        },
        index=pd.to_datetime(["2023-01-01 00:00"]),
    )

    bt = _make_condition_bt({"1m": df_1m, "1h": df_1h})
    result, details = bt._evaluate_level_touch_analyzer(
        {
            "level_price": 200.0,
            "lookback_candles": 1,
            "touch_tolerance_pct": 0.1,
            "timeframe": "1h",
        }
    )

    assert not result.any()
    assert details["touches_count"].fillna(0).sum() == 0


def test_vector_round_level_supports_proximity_pips_alias():
    idx = pd.date_range(start="2023-01-01 00:00", periods=3, freq="1min")
    df_1m = pd.DataFrame(
        {
            "open": [99.80, 99.90, 100.03],
            "high": [99.85, 99.95, 100.05],
            "low": [99.75, 99.85, 100.01],
            "close": [99.80, 99.90, 100.04],
            "volume": [100.0, 100.0, 100.0],
        },
        index=idx,
    )

    bt = _make_condition_bt({"1m": df_1m}, exchange_info={"tick_size": 0.01})
    result = bt._evaluate_round_level({"proximity_pips": 5})

    assert bool(result.iloc[-1]) is True
    assert bool(result.iloc[-2]) is False


def test_vector_round_level_generates_levels_per_price_order(monkeypatch):
    idx = pd.date_range(start="2023-01-01 00:00", periods=8, freq="1min")
    close = np.array([99.80, 99.90, 100.04, 100.50, 995.0, 1000.04, 1000.50, 1001.0])
    df_1m = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.02,
            "low": close - 0.02,
            "close": close,
            "volume": [100.0] * len(close),
        },
        index=idx,
    )
    params = {"proximity_pips": 5}
    tick_size = 0.01
    expected = []
    for price in close:
        levels = fvb_module._generate_round_levels(
            float(price), tick_size, [], 2, None, None
        )
        expected.append(
            any(abs(float(price) - level) <= 5 * tick_size for level in levels)
        )

    calls = []
    original_generate = fvb_module._generate_round_levels

    def counting_generate(*args, **kwargs):
        calls.append(args[0])
        return original_generate(*args, **kwargs)

    monkeypatch.setattr(fvb_module, "_generate_round_levels", counting_generate)

    bt = _make_condition_bt({"1m": df_1m}, exchange_info={"tick_size": tick_size})
    result = bt._evaluate_round_level(params)

    assert result.tolist() == expected
    assert len(calls) == 3


def test_vector_classic_pattern_detects_bullish_engulfing():
    idx = pd.date_range(start="2023-01-01 00:00", periods=3, freq="1min")
    df_1m = pd.DataFrame(
        {
            "open": [100.4, 101.0, 99.8],
            "high": [100.7, 101.3, 102.1],
            "low": [100.1, 99.6, 99.4],
            "close": [100.5, 100.0, 101.8],
            "volume": [100.0, 100.0, 100.0],
        },
        index=idx,
    )

    bt = _make_condition_bt({"1m": df_1m})
    result = bt._evaluate_classic_pattern(
        {"pattern_name": "bullish_engulfing", "timeframe": "1m"}
    )

    assert bool(result.iloc[-1]) is True


def test_vector_move_to_breakeven_block_exits_at_be():
    idx = pd.date_range(start="2023-01-01 00:00", periods=5, freq="1min")
    df_1m = pd.DataFrame(
        {
            "open": [99.8, 100.0, 100.0, 102.0, 100.1],
            "high": [100.0, 100.5, 103.5, 102.5, 100.2],
            "low": [99.6, 99.5, 99.8, 100.0, 99.9],
            "close": [99.9, 100.0, 102.0, 100.1, 100.0],
            "volume": [100.0, 100.0, 100.0, 100.0, 100.0],
        },
        index=idx,
    )
    strategy_json = {
        "entryConditions": {"id": "root", "type": "AND", "children": []},
        "initialization": {
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
                "type": "move_to_breakeven",
                "params": {
                    "target_type": "rr_multiplier",
                    "target_value": 1.5,
                    "offset_pips": 2,
                },
            }
        ],
    }

    bt = FastVectorBacktester(
        {"1m": df_1m},
        strategy_json,
        exchange_info={"tick_size": 0.01},
        execution_config={"commission_pct": 0.0, "slippage_pct": 0.0},
    )
    bt._prepare_data()
    bt.signals["enter_long"] = False
    bt.signals.loc[idx[0], "enter_long"] = True

    bt._simulate_trades_vectorized_v2()

    assert len(bt.trade_log) == 1
    trade = bt.trade_log[0]
    assert trade["exit_reason"] == "SL_AT_BE"
    assert trade["exit_price"] == pytest.approx(100.02, abs=1e-9)


def test_vector_foundation_weights_accept_legacy_prefixed_ids():
    df = _make_weight_test_df()
    strategy = {
        "foundation_weights": {"w_foundation_price_up": 10.0},
        "min_foundation_weight_threshold": 10.0,
        "entryConditions": {
            "id": "root",
            "type": "OR",
            "children": [
                {
                    "id": "foundation_price_up",
                    "type": "value_comparison",
                    "params": {
                        "leftOperand": {"source": "candle", "key": "close"},
                        "rightOperand": {"source": "value", "value": 101.0},
                        "operator": "gt",
                    },
                },
                {
                    "id": "foundation_never",
                    "type": "value_comparison",
                    "params": {
                        "leftOperand": {"source": "candle", "key": "close"},
                        "rightOperand": {"source": "value", "value": 9999.0},
                        "operator": "gt",
                    },
                },
            ],
        },
        "initialization": {
            "type": "open_position",
            "params": {
                "direction": "LONG",
                "sl_type": "percent",
                "sl_value": 1.0,
                "tp_type": "percent",
                "tp_value": 2.0,
            },
        },
    }

    bt = FastVectorBacktester(df, strategy)
    bt._prepare_data()
    bt._generate_signals()

    assert bt.signals["foundation_total_weight"].max() == pytest.approx(10.0)
    assert int(bt.signals["enter_long"].sum()) > 0
    counts = bt.structured_report["event_counters"]["foundation_trigger_counts"]
    assert counts.get("w_foundation_price_up", 0) > 0 or counts.get("foundation_price_up", 0) > 0


def test_vector_foundation_weight_threshold_rejects_insufficient_weight():
    df = _make_weight_test_df()
    strategy = {
        "foundation_weights": {"foundation_price_up": 10.0, "foundation_never": 10.0},
        "min_foundation_weight_threshold": 15.0,
        "entryConditions": {
            "id": "root",
            "type": "AND",
            "children": [
                {
                    "id": "foundation_price_up",
                    "type": "value_comparison",
                    "params": {
                        "leftOperand": {"source": "candle", "key": "close"},
                        "rightOperand": {"source": "value", "value": 101.0},
                        "operator": "gt",
                    },
                },
                {
                    "id": "foundation_never",
                    "type": "value_comparison",
                    "params": {
                        "leftOperand": {"source": "candle", "key": "close"},
                        "rightOperand": {"source": "value", "value": 9999.0},
                        "operator": "gt",
                    },
                },
            ],
        },
        "initialization": {
            "type": "open_position",
            "params": {
                "direction": "LONG",
                "sl_type": "percent",
                "sl_value": 1.0,
                "tp_type": "percent",
                "tp_value": 2.0,
            },
        },
    }

    bt = FastVectorBacktester(df, strategy)
    bt._prepare_data()
    bt._generate_signals()

    assert bt.signals["foundation_total_weight"].max() == pytest.approx(10.0)
    assert int(bt.signals["enter_long"].sum()) == 0
    assert (
        bt.structured_report["event_counters"]["rejections"]["by_weight_threshold"] > 0
    )
