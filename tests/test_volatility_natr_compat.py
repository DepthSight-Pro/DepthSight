import pandas as pd
import numpy as np
from bot_module.fast_vector_backtester import FastVectorBacktester
from bot_module.strategy import VisualBuilderStrategy


def create_synthetic_data(n=100, price=10.0, range_val=0.20):
    dates = pd.date_range("2026-01-01", periods=n, freq="1min", tz="UTC")
    close = np.linspace(price, price + 1.0, n)
    high = close + range_val * 0.75
    low = close - range_val * 0.25
    open_p = close
    volume = np.ones(n) * 1000

    df = pd.DataFrame(
        {
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )
    return df


def test_fast_vector_pure_atr_evaluation():
    # Asset with ATR ~ 0.20
    df = create_synthetic_data(100, price=10.0, range_val=0.20)
    hist = {"kline_1m": df}

    bt = FastVectorBacktester(
        historical_data=hist,
        strategy_json={"entryConditions": {"type": "AND", "children": []}},
        symbol="TESTUSDT",
    )
    bt._prepare_data()

    # Even if an ATR block has a stray natr_threshold (from old prompt),
    # it MUST be evaluated as ATR!
    atr_params_with_stray = {
        "id": "f_atr_test",
        "indicator": "ATR",
        "operator": "gt",
        "value": 1.5,
        "natr_threshold": 0.8,
    }
    result = bt._evaluate_volatility_filter(atr_params_with_stray)
    # ATR is ~0.20, which is NOT > 1.5 => False!
    assert bool(result.iloc[-1]) is False, "Dollar ATR ~0.20 is not > 1.5"

    # Now with high ATR asset (e.g. ETH with range 5.0)
    df_high_atr = create_synthetic_data(100, price=2000.0, range_val=5.0)
    bt_high = FastVectorBacktester(
        historical_data={"kline_1m": df_high_atr},
        strategy_json={"entryConditions": {"type": "AND", "children": []}},
        symbol="ETHUSDT",
    )
    bt_high._prepare_data()
    result_high = bt_high._evaluate_volatility_filter(atr_params_with_stray)
    # ATR is ~5.0, which IS > 1.5 => True!
    assert bool(result_high.iloc[-1]) is True, "Dollar ATR ~5.0 is > 1.5"


def test_fast_vector_natr_filter():
    # Asset with price=10.0, range=0.20 => NATR is ~ (0.20 / 10) * 100 ~ 2.0%
    df = create_synthetic_data(100, price=10.0, range_val=0.20)
    hist = {"kline_1m": df}

    bt = FastVectorBacktester(
        historical_data=hist,
        strategy_json={"entryConditions": {"type": "AND", "children": []}},
        symbol="TESTUSDT",
    )
    bt._prepare_data()

    natr_params = {
        "id": "f_natr",
        "natr_threshold": 0.8,
    }
    result = bt._evaluate_natr_filter(natr_params)
    assert bool(result.iloc[-1]) is True, "NATR 2.0% is > 0.8%"


def test_strategy_volatility_vs_natr():
    strat = VisualBuilderStrategy()
    pair_info = {
        "atr": 2.5,
        "last_price": 2000.0,
        "candle_timeframe": "1m",
    }
    market_data = {
        "kline_1m": create_synthetic_data(100, price=2000.0, range_val=2.5),
    }

    # ATR filter: ATR is 2.5, value is 1.5, operator is gt => Should pass!
    atr_params = {
        "indicator": "ATR",
        "operator": "gt",
        "value": 1.5,
        "natr_threshold": 0.8,  # Stray param should be ignored for ATR!
    }
    passed_atr, details_atr = strat._check_filter_volatility(
        pair_info=pair_info,
        market_data=market_data,
        params=atr_params,
        context={},
    )
    assert passed_atr is True
    assert details_atr.get("indicator") == "ATR"
    assert details_atr.get("actual") == 2.5

    # Legacy NATR indicator in volatility_filter
    legacy_natr_params = {
        "indicator": "NATR",
        "value": 0.05,
    }
    passed_natr, details_natr = strat._check_filter_volatility(
        pair_info=pair_info,
        market_data=market_data,
        params=legacy_natr_params,
        context={},
    )
    assert passed_natr is True
    assert "natr" in details_natr
