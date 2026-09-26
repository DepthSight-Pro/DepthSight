# tests/test_live_backtest_parity.py
"""Live scalar <-> vector backtester parity harness.

The same operands must evaluate to the same booleans through:
  - live path:  BaseStrategy._check_condition_value_comparison
                 (with _resolve_value / TF-aware indicator resolver), and
  - backtest path: FastVectorBacktester._compare_value_series over
                 _resolve_value_series.

Deterministic seeded candles, no network. Any future divergence between the
two engines fails here instead of silently in production.
"""

import numpy as np
import pandas as pd
import pytest

import bot_module.fast_vector_backtester as fvb_module  # noqa: F401
from bot_module.fast_vector_backtester import FastVectorBacktester
from bot_module.strategy import VisualBuilderStrategy

pd_ta = pytest.importorskip("pandas_ta")


def _make_klines(n=400, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-05 00:00", periods=n, freq="1min", tz="UTC")
    drift = 0.02 * np.sin(np.arange(n) / 25.0)
    noise = rng.normal(0, 0.15, n)
    close = 100.0 + np.cumsum(drift + noise)
    df = pd.DataFrame(
        {
            "open": close - 0.05,
            "high": close + 0.12,
            "low": close - 0.12,
            "close": close,
            "volume": 100.0 + rng.normal(0, 5, n),
        },
        index=idx,
    )
    df.index.name = "open_time"
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    df5 = df.resample("5min").agg(agg).dropna()
    return df, df5


def _with_indicators(df):
    out = df.copy()
    out["SMA_10"] = out["close"].rolling(10).mean()
    out["EMA_20"] = out["close"].ewm(span=20, adjust=False).mean()
    out["RSI_14"] = pd_ta.rsi(close=out["close"], length=14)
    return out


@pytest.fixture(scope="module")
def klines():
    df1, df5 = _make_klines()
    return _with_indicators(df1), df5


@pytest.fixture(scope="module")
def strategy():
    inst = VisualBuilderStrategy.__new__(VisualBuilderStrategy)
    inst._tf_indicator_cache = {}
    return inst


@pytest.fixture(scope="module")
def vector(klines):
    df1, df5 = klines
    fvb = FastVectorBacktester.__new__(FastVectorBacktester)
    fvb.main_df = df1
    fvb.signals = pd.DataFrame(index=df1.index)
    fvb.broadcasted_cache = {}
    fvb.base_timeframe = "1m"
    fvb.data_context = {"1m": df1, "5m": df5}
    # Mirror a backtester-computed provider series (level = close 5 bars ago).
    fvb._dynamic_block_results = {
        "lvl": {"detected_level": df1["close"].shift(5).astype(float)}
    }
    # Mirror backtester prep for 5m indicator columns (closed-shifted broadcast).
    c5 = df5["close"]
    ema10_5m = c5.ewm(span=10, adjust=False).mean()
    fvb.broadcasted_cache["EMA_10|5m"] = ema10_5m.shift(1).reindex(
        df1.index, method="ffill"
    )
    sma20_5m = c5.rolling(20).mean()
    fvb.broadcasted_cache["SMA_20|5m"] = sma20_5m.shift(1).reindex(
        df1.index, method="ffill"
    )
    return fvb


def _scalar(strategy, df1, df5, i, left, right, operator, extra_pair=None):
    ts = df1.index[i]
    df5_slice = df5[df5.index <= ts]
    market_data = {"kline_1m": df1.iloc[: i + 1], "kline_5m": df5_slice}
    pair_info = {
        "symbol": "TESTUSDT",
        "candle_timeframe": "1m",
        "timestamp_dt": ts.to_pydatetime(),
        "current_candle_index": i,
        "close": float(df1["close"].iloc[i]),
        "tick_size": 0.01,
    }
    if extra_pair:
        pair_info.update(extra_pair)
    provider_trace = {
        "id": "lvl",
        "type": "local_level",
        "result": True,
        "details": {"detected_level": float(df1["close"].iloc[max(i - 5, 0)])},
    }
    context = {
        "pair_info": pair_info,
        "market_data": market_data,
        "trace": {
            "id": "root",
            "type": "AND",
            "result": True,
            "children": [provider_trace],
        },
        "prev_pair_info": None,
    }
    result, details = strategy._check_condition_value_comparison(
        pair_info=pair_info,
        market_data=market_data,
        params={"leftOperand": left, "rightOperand": right, "operator": operator},
        context=context,
    )
    return bool(result), details


def _vector(vector, left, right, operator, i):
    left_series = vector._resolve_value_series(left)
    right_series = vector._resolve_value_series(right)
    out = vector._compare_value_series(left_series, right_series, operator)
    return bool(out.iloc[i])


CANDLE = lambda key, **kw: {"source": "candle", "key": key, **kw}  # noqa: E731
IND = lambda key, **kw: {"source": "indicator", "key": key, **kw}  # noqa: E731
CONST = lambda v: {"source": "constant", "value": v}  # noqa: E731
BLOCK = lambda bid, key="detected_level", **kw: {  # noqa: E731
    "source": "block_result",
    "block_id": bid,
    "key": key,
    **kw,
}

# index 150 == exact 5m close (150 % 5 == 0): the HTF alignment edge.
PROBE_POINTS = [100, 101, 149, 150, 151, 200, 299]

OPERAND_CASES = [
    # (left, right) — operators are crossed separately below.
    (CANDLE("close"), CANDLE("close", shift=1)),
    (CANDLE("close"), CONST(100.0)),
    (CANDLE("high", shift=1), CANDLE("low")),
    (IND("SMA_10"), IND("SMA_10", shift=1)),
    (IND("EMA_20"), CANDLE("close")),
    (IND("RSI_14"), CONST(50.0)),
    (CANDLE("close", timeframe="5m"), CANDLE("close", timeframe="5m", shift=1)),
    (IND("EMA_10", timeframe="5m"), IND("SMA_20", timeframe="5m")),
    (CANDLE("close"), BLOCK("lvl")),
    (BLOCK("lvl"), CONST(0.0)),
]

OPERATORS = ["gt", "lt", "gte", "lte", "eq", "cross_above", "cross_below"]


@pytest.mark.parametrize("case_id", list(range(len(OPERAND_CASES))))
@pytest.mark.parametrize("operator", OPERATORS)
@pytest.mark.parametrize("i", PROBE_POINTS)
def test_scalar_matches_vector(strategy, vector, klines, case_id, operator, i):
    df1, df5 = klines
    left, right = OPERAND_CASES[case_id]
    # block_result has no previous bar in live: cross over it is an explicit
    # error on the scalar side; vector would silently use shifted series, so
    # that combination is covered by the dedicated contract test instead.
    uses_block = any(
        isinstance(op, dict) and op.get("source") == "block_result"
        for op in (left, right)
    )
    if uses_block and operator in ("cross_above", "cross_below"):
        result, details = _scalar(strategy, df1, df5, i, left, right, operator)
        assert result is False
        assert "error" in details
        return
    expected = _vector(vector, left, right, operator, i)
    result, details = _scalar(strategy, df1, df5, i, left, right, operator)
    assert result == expected, (
        f"divergence at i={i} op={operator} left={left} right={right}: "
        f"scalar={result} vector={expected} details={details}"
    )


def test_block_result_shift_is_explicit_error(strategy, klines):
    df1, df5 = klines
    result, details = _scalar(
        strategy, df1, df5, 200, BLOCK("lvl", shift=1), CONST(1.0), "gt"
    )
    # Shifted block_result: live has no block history. Must fail closed with
    # a clear message (vector silently shifts its broadcast cache instead —
    # documented divergence, see module docstring of the resolver).
    assert result is False
    assert "error" in details or details.get("left_value_resolved") is None


def test_unknown_indicator_fails_closed(strategy, klines):
    df1, df5 = klines
    result, details = _scalar(strategy, df1, df5, 200, IND("NOPE_99"), CONST(1.0), "gt")
    assert result is False
    assert "error" in details


def test_unknown_operator_still_errors(strategy, klines):
    df1, df5 = klines
    result, details = _scalar(
        strategy, df1, df5, 200, CANDLE("close"), CONST(1.0), "sideways"
    )
    assert result is False
    assert "error" in details
