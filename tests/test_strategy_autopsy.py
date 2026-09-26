# tests/test_strategy_autopsy.py
"""Unit tests for scripts/strategy_autopsy.py lint + verdict + pnl logic.

No network: pure functions on synthetic configs/stats/candles.
"""

from collections import Counter

import pandas as pd
import pytest

from scripts.strategy_autopsy import (
    _unsupported_exits,
    decide_verdict,
    lint_exit_plan,
    lint_weights,
    runtime_weight_match,
    simulate_pnl,
)


def _entry_config(weights, child_id="w_breakout_setup"):
    return {
        "foundation_weights": weights,
        "entryConditions": {
            "id": "root",
            "type": "AND",
            "children": [{"id": child_id, "type": "value_comparison", "params": {}}],
        },
    }


def test_runtime_weight_match_mirrors_checker():
    assert runtime_weight_match("w_breakout_setup", "w_breakout_setup")
    assert runtime_weight_match("trend", "trend")
    assert runtime_weight_match("trend", "w_trend")
    # Reverse direction does NOT match (the live ZECUSDT bug).
    assert not runtime_weight_match("w_breakout_setup", "breakout_setup")
    assert not runtime_weight_match("other", "breakout_setup")


def test_lint_weights_flags_unaccruable_key():
    issues, gap = lint_weights(_entry_config({"breakout_setup": 100}))
    assert gap is True
    assert any("breakout_setup" in i for i in issues)


def test_lint_weights_ok_on_exact_key():
    issues, gap = lint_weights(_entry_config({"w_breakout_setup": 100}))
    assert gap is False
    assert issues == []


def test_lint_weights_ok_on_legacy_prefix():
    # Node 'trend' + key 'w_trend' matches at runtime.
    issues, gap = lint_weights(_entry_config({"w_trend": 10}, child_id="trend"))
    assert gap is False
    assert issues == []


def _stats(signals=0, max_weight=0.0, reasons=None, evaluated=100):
    return {
        "evaluated": evaluated,
        "signals": signals,
        "weights": [max_weight],
        "leaf_stats": Counter(),
        "leaf_errors": Counter(),
        "rejection_reasons": Counter(reasons or {}),
    }


def test_decide_config_on_static_gap_without_dynamic_rejects():
    # Entry never passed (filters), but weight could never accrue either.
    verdict, detail = decide_verdict(
        _stats(signals=0, max_weight=0.0, reasons={"filter": 90}),
        ["weight key 'breakout_setup' never accrues"],
        True,
        40.0,
    )
    assert verdict == "CONFIG"
    assert any("0.0 < threshold 40" in d for d in detail)


def test_decide_market_ok_when_firing():
    verdict, _ = decide_verdict(_stats(signals=5, max_weight=100.0), [], False, 40.0)
    assert verdict == "MARKET-OK"


def test_decide_market_selectivity():
    stats = _stats(signals=0, max_weight=0.0, reasons={"entry_conditions": 10})
    stats["leaf_stats"][("price_action_analyzer:x", "fail")] = 10
    # No weight gap and threshold trivially reachable -> MARKET, not CONFIG.
    verdict, detail = decide_verdict(stats, [], False, 0.0)
    assert verdict == "MARKET"
    assert any("price_action_analyzer:x" in d for d in detail)


# ---------------------------------------------------------------------------
# PnL simulator tests (synthetic 1m candles, tick_size=1.0 for readability)


def _df(rows):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="1min", tz="UTC")
    return pd.DataFrame(
        rows, columns=["open", "high", "low", "close", "volume"], index=idx
    )


def _base_config(**overrides):
    init_params = {
        "direction": "LONG",
        "sl_type": "atr_multiplier",
        "sl_value": 4,
        "tp_type": "rr_multiplier",
        "tp_value": 6,
        "partial_exits": [
            {"tp_type": "rr_multiplier", "tp_value": 2.5, "size_pct": 25},
            {"tp_type": "rr_multiplier", "tp_value": 4, "size_pct": 25},
            {"tp_type": "rr_multiplier", "tp_value": 6, "size_pct": 50},
        ],
    }
    init_params.update(overrides.get("init_params", {}))
    cfg = {
        "initialization": {
            "id": "init",
            "type": "open_position",
            "params": init_params,
        },
        "positionManagement": overrides.get(
            "positionManagement",
            [
                {
                    "id": "be",
                    "type": "move_to_breakeven",
                    "params": {
                        "target_type": "rr_multiplier",
                        "target_value": 2,
                        "offset_pips": 2,
                    },
                }
            ],
        ),
    }
    return cfg


def _ev(idx, entry=100.0, atr=2.0):
    return {
        "index": idx,
        "timestamp": None,
        "direction": "LONG",
        "entry": entry,
        "atr": atr,
        "tick_size": 1.0,
    }


def test_pnl_tp_with_partials():
    # Steady rise to 150: partials at 120/132/148 fully close the trade.
    closes = [100 + i for i in range(55)]
    rows = [[c - 0.5, c + 0.5, c - 0.5, c, 10.0] for c in closes]
    df = _df(rows)
    trades, summary = simulate_pnl(
        [_ev(0)], df, _base_config(), fee_bps=0.0, notional=1000.0
    )
    assert summary["trades"] == 1
    assert summary["wins"] == 1
    # (0.25*20 + 0.25*32 + 0.5*48) / 8 = 4.625R
    assert summary["total_r"] == pytest.approx(4.625)
    assert trades[0]["exit_reason"] == "partial"
    assert trades[0]["r"] == pytest.approx(4.625)


def test_pnl_stop_loss():
    rows = [[100, 101, 99, 100, 10.0]] + [
        [95 - i, 96 - i, 94 - i, 95 - i, 10.0] for i in range(10)
    ]
    df = _df(rows)
    trades, summary = simulate_pnl(
        [_ev(0)], df, _base_config(), fee_bps=0.0, notional=1000.0
    )
    assert summary["trades"] == 1
    assert summary["losses"] == 1
    assert trades[0]["exit_reason"] == "stop"
    assert trades[0]["r"] == pytest.approx(-1.0)


def test_pnl_same_candle_sl_first():
    # Candle touches both TP (120) and SL (92): pessimistic SL fill.
    rows = [[100, 100, 100, 100, 10.0], [90, 130, 90, 125, 10.0]] + [
        [125, 126, 124, 125, 10.0]
    ] * 5
    df = _df(rows)
    trades, summary = simulate_pnl(
        [_ev(0)], df, _base_config(), fee_bps=0.0, notional=1000.0
    )
    assert trades[0]["exit_reason"] == "stop"
    assert trades[0]["r"] == pytest.approx(-1.0)


def test_pnl_breakeven():
    # Rises past 2R (116) activating BE at 102, then falls through.
    rows = [[100, 100, 100, 100, 10.0]]
    rows += [[100 + i, 101 + i, 99 + i, 100 + i, 10.0] for i in range(1, 18)]
    rows += [[110 - i, 111 - i, 109 - i, 110 - i, 10.0] for i in range(12)]
    df = _df(rows)
    trades, summary = simulate_pnl(
        [_ev(0)], df, _base_config(), fee_bps=0.0, notional=1000.0
    )
    assert trades[0]["exit_reason"] == "breakeven"
    # Exit at 102 with risk 8 -> +0.25R
    assert trades[0]["r"] == pytest.approx(0.25)


def test_pnl_overlap_skipped():
    rows = [[100 + i, 101 + i, 99 + i, 100 + i, 10.0] for i in range(60)]
    df = _df(rows)
    trades, summary = simulate_pnl(
        [_ev(0), _ev(2)], df, _base_config(), fee_bps=0.0, notional=1000.0
    )
    assert summary["trades"] == 1
    assert summary["skipped_overlap"] == 1


def test_pnl_fees():
    closes = [100 + i for i in range(55)]
    rows = [[c - 0.5, c + 0.5, c - 0.5, c, 10.0] for c in closes]
    df = _df(rows)
    _, summary = simulate_pnl(
        [_ev(0)], df, _base_config(), fee_bps=50.0, notional=1000.0
    )
    # Entry 5.0 + fills 1.5/1.65/3.7 = 11.85; gross 370 -> net 358.15
    assert summary["total_fees_usdt"] == pytest.approx(11.85)
    assert summary["total_usdt"] == pytest.approx(358.15)
    assert summary["total_r"] == pytest.approx(358.15 / 80.0)


def test_unsupported_exits_reported():
    cfg = _base_config(init_params={"sl_type": "percent_from_price", "sl_value": 1.0})
    assert _unsupported_exits(cfg) is not None
    assert _unsupported_exits(_base_config()) is None


def test_lint_exit_plan_flags_dead_final_tp():
    issues = lint_exit_plan(_base_config())
    assert any("final TP" in i for i in issues)
