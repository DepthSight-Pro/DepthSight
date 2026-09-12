import pandas as pd
import numpy as np
from bot_module.fast_vector_backtester import FastVectorBacktester
from bot_module.strategy import VisualBuilderStrategy


def create_synthetic_data(n=100):
    dates = pd.date_range("2026-01-01", periods=n, freq="1min", tz="UTC")
    close = np.linspace(10.0, 11.0, n)
    high = close + 0.15  # Range ~ 0.15, NATR ~ (0.15 / 10) * 100 ~ 1.5%
    low = close - 0.05
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


def test_fast_vector_volatility_filter_natr_routing():
    df = create_synthetic_data(100)
    hist = {"kline_1m": df}

    # Case 1: Contaminated block (volatility_filter + indicator ATR + value 1.5 + natr_threshold 0.8)
    # The range is 0.20 on price 10.0 => ATR in dollars is ~0.20, while NATR is ~2.0%
    # If it checked dollar ATR > 1.5, it would be False.
    # Because it routes to NATR with threshold 0.8%, it should be True!
    contaminated_params = {
        "id": "f_natr",
        "indicator": "ATR",
        "operator": "gt",
        "value": 1.5,
        "natr_threshold": 0.8,
    }

    bt = FastVectorBacktester(
        historical_data=hist,
        strategy_json={"entryConditions": {"type": "AND", "children": []}},
        symbol="TESTUSDT",
    )
    bt._prepare_data()

    result_contaminated = bt._evaluate_volatility_filter(contaminated_params)
    assert bool(result_contaminated.iloc[-1]) is True, (
        "Should evaluate as NATR > 0.8% and return True"
    )

    # Case 2: Pure dollar ATR filter (without natr_threshold or natr id)
    pure_atr_params = {
        "id": "f_atr",
        "indicator": "ATR",
        "operator": "gt",
        "value": 1.5,
    }
    result_pure_atr = bt._evaluate_volatility_filter(pure_atr_params)
    assert bool(result_pure_atr.iloc[-1]) is False, (
        "Pure dollar ATR > 1.5 on $10 asset should be False"
    )


def test_strategy_volatility_filter_natr_fallback():
    strat = VisualBuilderStrategy()
    pair_info = {
        "atr": 0.05,
        "last_price": 10.0,
        "candle_timeframe": "1m",
    }
    market_data = {
        "kline_1m": create_synthetic_data(100),
    }

    # Volatility filter with natr_threshold
    params = {
        "id": "f_natr",
        "indicator": "ATR",
        "operator": "gt",
        "value": 1.5,
        "natr_threshold": 0.8,
    }

    passed, details = strat._check_filter_volatility(
        pair_info=pair_info,
        market_data=market_data,
        params=params,
        context={},
    )
    assert passed is True, "Should route to NATR filter and pass"
