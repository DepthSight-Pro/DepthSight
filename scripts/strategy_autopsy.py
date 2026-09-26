#!/usr/bin/env python3
"""Strategy autopsy: why does a VisualBuilder strategy produce no trades?

Replays recent closed candles through the REAL evaluation path
(VisualBuilderStrategy.check_signal_sync) and splits every rejection into:
  - CONFIG : static config problems (weight key mismatch vs node ids incl.
             the w_ legacy rule, threshold key, ignored params) or dynamic
             weight rejections (accrued < threshold),
  - DATA   : checker errors (missing candles/indicators), not market decisions,
  - MARKET : clean False evaluations (conditions genuinely too strict).

Also reports per-block pass/error rates so the strictest block is obvious.

Usage:
    python scripts/strategy_autopsy.py --config path/to/strategy.json \\
        --symbol ZECUSDT --market futures_usdtm --days 7 [--max-candles 3000]
        [--json-out report.json] [--strict] [--pnl] [--fee-bps 5] [--notional 1000]

Exit code: 0 normally; 2 with --strict when verdict is CONFIG or DATA.

Fidelity notes (read before quoting numbers):
- Replay calls the REAL VisualBuilderStrategy.check_signal_sync per closed
  candle with prod-equivalent inputs (sliced kline history, consumer-style
  indicators). Boolean outcomes match live.
- The live controller additionally gates on risk/overlap/balance, routes
  events, and executes orders — none of that is emulated. Signal count is an
  UPPER bound on positions, not a trade count.
- Replay evaluates the full condition tree (no AND short-circuit) so that
  per-block stats cover every block; live uses a boolean-equivalent fast
  path that stops at the first failure. Pass/fail COUNTS per block therefore
  differ from live logs, pass/fail DECISIONS do not.
- --pnl is a lightweight exit simulator (SL/TP/partials/BE/fees from the
  config, pessimistic same-candle SL-first rule, one position at a time),
  not the full backtester. Use it for expectancy/direction, not for
  cent-level PnL claims.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(override=True)

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("autopsy")

IGNORED_PARAMS_BY_BLOCK = {
    # param -> (ignored?, note). Curated from checker implementations.
    ("rel_vol_filter", "mode"): (
        True,
        "checker reads only rel_vol_threshold/multiplier/lookback_period",
    ),
}


def load_config(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise ValueError("strategy config must be a JSON object")
    return cfg


def iter_condition_nodes(node: Any) -> List[Dict[str, Any]]:
    """Collects all dict nodes with a 'type' (conditions, filters, gates)."""
    found = []
    stack = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if cur.get("type"):
                found.append(cur)
            stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
        elif isinstance(cur, list):
            stack.extend(cur)
    return found


def collect_timeframes(config: Dict[str, Any], default_tf: str) -> Set[str]:
    tfs = {default_tf}
    for node in iter_condition_nodes(config):
        params = node.get("params", {}) if isinstance(node.get("params"), dict) else {}
        tf = params.get("timeframe") or node.get("timeframe")
        if isinstance(tf, str) and tf not in ("auto",):
            tfs.add(tf)
    return tfs


def runtime_weight_match(node_id: str, weight_key: str) -> bool:
    """Replicates _calculate_weight_from_trace matching exactly.

    A passing node accrues its key iff node_id == key, or the node id does
    NOT start with 'w_' and key == f"w_{node_id}". The reverse direction
    (key 'breakout_setup' vs node 'w_breakout_setup') does NOT match.
    """
    if node_id == weight_key:
        return True
    if node_id and not str(node_id).startswith("w_"):
        return f"w_{node_id}" == weight_key
    return False


def lint_weights(config: Dict[str, Any]) -> Tuple[List[str], bool]:
    """Static weight-key audit. Returns (issues, gap).

    gap=True means at least one configured weight can never accrue at
    runtime (without healer) — live signals would carry less weight.
    """
    issues: List[str] = []
    weights = config.get("foundation_weights") or {}
    if not isinstance(weights, dict) or not weights:
        return (
            ["foundation_weights is empty: no signal can pass a weight threshold > 0"],
            True,
        )
    node_ids = sorted(
        {
            str(n.get("id"))
            for n in iter_condition_nodes(config.get("entryConditions"))
            if isinstance(n, dict) and n.get("id")
        }
    )
    gap = False
    for w_key in weights:
        w_key_s = str(w_key)
        if not any(runtime_weight_match(nid, w_key_s) for nid in node_ids):
            gap = True
            issues.append(
                f"weight key '{w_key_s}' never accrues at runtime "
                f"(node ids: {node_ids}): live weight misses "
                f"+{weights[w_key]} unless healed/renamed"
            )
    return issues, gap


KNOWN_COMPARISON_OPS = {
    "gt",
    ">",
    "gte",
    ">=",
    "lt",
    "<",
    "lte",
    "<=",
    "eq",
    "==",
    "cross_above",
    "cross_below",
}


def _operand_refs(node: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """Yields (role, operand_dict) for comparison-like blocks."""
    params = node.get("params", {}) if isinstance(node.get("params"), dict) else {}
    roles = []
    if node.get("type") in ("value_comparison", "price_condition"):
        roles = [
            ("left", params.get("leftOperand") or params.get("left") or {}),
            ("right", params.get("rightOperand") or params.get("right") or {}),
        ]
    elif node.get("type") == "price_vs_level":
        roles = [
            ("price", params.get("price_source") or {}),
            ("level", params.get("level_source") or {}),
        ]
    return [(role, op) for role, op in roles if isinstance(op, dict)]


def lint_operands(config: Dict[str, Any]) -> List[str]:
    """Static audit of dynamic operands (sources, TF/shift, operators)."""
    issues: List[str] = []
    main_tf = (
        (config.get("entryTrigger") or {}).get("timeframe")
        or config.get("tradingTimeframe")
        or "1m"
    )
    for node in iter_condition_nodes(config):
        params = node.get("params", {}) if isinstance(node.get("params"), dict) else {}
        op = params.get("operator")
        if node.get("type") in (
            "value_comparison",
            "price_condition",
            "price_vs_level",
        ):
            if op is not None and op not in KNOWN_COMPARISON_OPS:
                issues.append(
                    f"block {node.get('id')}: unknown operator '{op}' "
                    f"(always False at runtime)"
                )
        for role, operand in _operand_refs(node):
            src = operand.get("source")
            if src == "indicator":
                tf = operand.get("timeframe")
                shift = operand.get("shift", 0)
                if tf is not None and tf != main_tf:
                    issues.append(
                        f"block {node.get('id')}: {role} indicator "
                        f"'{operand.get('key')}' on {tf} (not {main_tf}): "
                        f"resolved by recompute on that TF"
                    )
                if shift not in (None, 0, "0"):
                    issues.append(
                        f"block {node.get('id')}: {role} indicator shift={shift} "
                        f"is honored (previous-bar semantics)"
                    )
            elif src == "block_result":
                if operand.get("shift", 0) not in (None, 0, "0"):
                    issues.append(
                        f"block {node.get('id')}: shifted block_result "
                        f"(shift={operand.get('shift')}) is unsupported live: "
                        f"always False + error"
                    )
                if op in ("cross_above", "cross_below"):
                    issues.append(
                        f"block {node.get('id')}: cross over block_result is "
                        f"unsupported live (no block history): always False + "
                        f"error — split into prev-lt + curr-gt comparisons"
                    )
    return issues


def lint_config(config: Dict[str, Any]) -> Tuple[List[str], bool]:
    issues: List[str] = lint_exit_plan(config)
    weight_gap = False
    if "min_total_foundation_weight_threshold" not in config:
        if "min_foundation_weight_threshold" in config:
            issues.append(
                "threshold key is 'min_foundation_weight_threshold' (typo form): "
                "live controller corrects it, other paths may read default 50.0"
            )
        else:
            issues.append(
                "no weight threshold key: default 50.0 applies unless overridden"
            )
    for node in iter_condition_nodes(config):
        params = node.get("params", {}) if isinstance(node.get("params"), dict) else {}
        for pname in params:
            note = IGNORED_PARAMS_BY_BLOCK.get((node.get("type"), pname))
            if note and note[0]:
                issues.append(
                    f"block {node.get('id') or node.get('type')}: "
                    f"param '{pname}' is ignored ({note[1]})"
                )
    issues.extend(lint_operands(config))
    _w_issues, weight_gap = lint_weights(config)
    issues.extend(_w_issues)
    # Session window vs now (informational; evaluation still replays history).
    for node in iter_condition_nodes(config):
        if node.get("type") in ("trading_session", "time_filter"):
            params = node.get("params", {}) or {}
            if params.get("filter_mode") == "hours":
                issues.append(
                    f"session filter {node.get('id')}: hours mode "
                    f"{params.get('start_hour_utc')}-{params.get('end_hour_utc')} UTC "
                    f"(signals exist only inside the window)"
                )
    return issues, weight_gap


def prepare_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Adds the standard live-pipeline indicator columns (same utils)."""
    from bot_module.utils import (
        add_relative_volume,
        add_volume_percentile_rank,
        calculate_scalper_natr,
    )

    out = df.copy()
    close = out["close"].astype(float)
    for p in (10, 20, 50):
        out[f"SMA_{p}"] = close.rolling(p).mean()
    out["RSI_14"] = _wilder_rsi(close, 14)
    try:
        import pandas_ta as ta

        adx = ta.adx(high=out["high"], low=out["low"], close=close, length=14)
        if adx is not None and "ADX_14" in adx.columns:
            out["ADX_14"] = adx["ADX_14"]
        atr = ta.atr(high=out["high"], low=out["low"], close=close, length=14)
        if atr is not None:
            out["ATR_14"] = atr
    except Exception as e:
        log.warning("pandas_ta unavailable for ADX/ATR, continuing without: %s", e)
    out = calculate_scalper_natr(out, period=30)
    out = add_relative_volume(out, period=20)
    out = add_volume_percentile_rank(out, period=1000, percentile=90)
    return out


def _wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    # Flat market (no losses): RSI 100 if any gains else 50, like the checker.
    flat = avg_loss.fillna(0) <= 0
    rsi = rsi.mask(flat & (avg_gain.fillna(0) > 0), 100.0)
    rsi = rsi.mask(flat & (avg_gain.fillna(0) <= 0), 50.0)
    return rsi


def estimate_tick_size(price: float) -> float:
    if price <= 0 or not np.isfinite(price):
        return 0.01
    mag = int(np.floor(np.log10(price)))
    return 10.0 ** (mag - 5)


def walk_trace(
    trace: Dict[str, Any],
    leaf_stats: Counter,
    leaf_errors: Counter,
) -> None:
    """Aggregates per-leaf pass/error counters from an evaluation trace."""
    stack = [trace]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        children = node.get("children")
        if children:
            stack.extend(children)
            continue
        key = f"{node.get('type')}:{node.get('id')}"
        if node.get("result"):
            leaf_stats[(key, "pass")] += 1
        else:
            details = node.get("details", {}) or {}
            if details.get("error"):
                leaf_stats[(key, "error")] += 1
                leaf_errors[key] += 1
            else:
                leaf_stats[(key, "fail")] += 1


async def download_all(
    symbol: str, market_type: str, tfs: Set[str], days: int
) -> Dict[str, pd.DataFrame]:
    from bot_module.data_loader import download_klines

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)
    out = {}
    btc_symbol = "BTCUSDT"
    for tf in sorted(tfs):
        df = await download_klines(
            symbol=symbol,
            timeframe=tf,
            start_dt=start_dt,
            end_dt=end_dt,
            market_type=market_type,
        )
        if df is None or df.empty:
            raise RuntimeError(f"no klines downloaded for {symbol} {tf}")
        out[f"kline_{tf}"] = df.sort_index()
    # Cross-market feed for btc_state_filter / correlation blocks.
    if any(k in out for k in ("kline_1m",)) and symbol.upper() != btc_symbol:
        try:
            btc = await download_klines(
                symbol=btc_symbol,
                timeframe="1m",
                start_dt=start_dt,
                end_dt=end_dt,
                market_type=market_type,
            )
            if btc is not None and not btc.empty:
                out["kline_1m_BTCUSDT"] = btc.sort_index()
        except Exception as e:
            log.warning(
                "BTC feed download failed, cross-market blocks may error: %s", e
            )
    return out


def build_pair_info(
    symbol: str,
    main_tf: str,
    df_1m: pd.DataFrame,
    idx_1m: int,
    tick_size: float,
) -> Dict[str, Any]:
    row = df_1m.iloc[idx_1m]
    ts = df_1m.index[idx_1m]
    last_close = float(row["close"])
    pair_info: Dict[str, Any] = {
        "symbol": symbol.upper(),
        "candle_timeframe": main_tf,
        "timestamp_dt": ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
        "current_candle_index": int(idx_1m),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": last_close,
        "last_price": last_close,
        "volume": float(row["volume"]),
        "tick_size": tick_size,
        "is_live_mode": False,
        "is_backtest_mode": True,
    }
    for key in (
        "SMA_10",
        "SMA_20",
        "SMA_50",
        "RSI_14",
        "ADX_14",
        "ATR_14",
        "atr",
        "natr",
        "relative_volume",
        "is_volume_spike",
    ):
        if key in df_1m.columns:
            val = df_1m[key].iloc[idx_1m]
            if pd.notna(val):
                pair_info[key] = bool(val) if key == "is_volume_spike" else float(val)
    if "ATR_14" in pair_info and "atr" not in pair_info:
        pair_info["atr"] = pair_info["ATR_14"]
    return pair_info


def run_replay(
    config: Dict[str, Any],
    symbol: str,
    klines: Dict[str, pd.DataFrame],
    main_tf: str,
    max_candles: Optional[int],
) -> Dict[str, Any]:
    from bot_module.strategy import VisualBuilderStrategy

    df_1m = klines["kline_1m"]
    # Adaptive warmup: the slowest indicator is usually an HTF SMA
    # (e.g. slow 50 on 15m needs 50*15 = 750 1m-candles). Undersized warmup
    # shows up as honest DATA errors on early candles.
    tf_minutes = {
        "1m": 1,
        "3m": 3,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "2h": 120,
        "4h": 240,
        "1d": 1440,
    }
    warmup = 300
    for node in iter_condition_nodes(
        config.get("entryConditions")
    ) + iter_condition_nodes(config.get("filters")):
        if not isinstance(node, dict):
            continue
        params = node.get("params", {}) if isinstance(node.get("params"), dict) else {}
        slow = params.get("slow_period", params.get("sma_slow_period", 0)) or 0
        rsi_p = params.get("rsi_period", 0) or 0
        lookback = params.get("lookback_period", params.get("lookback_candles", 0)) or 0
        tf = params.get("timeframe", "1m")
        mult = tf_minutes.get(tf, 1)
        try:
            need = max(int(slow), int(rsi_p), int(lookback)) * mult
        except (TypeError, ValueError):
            need = 0
        warmup = max(warmup, need + 5)
    warmup = min(warmup, max(len(df_1m) - 10, 0))
    log.info("warmup: skipping first %d candles", warmup)
    indices = list(range(warmup, len(df_1m)))
    if max_candles:
        indices = indices[-max_candles:]

    # Per-TF indicator prep (mirrors the live consumer columns).
    prepared = {k: prepare_indicators(v) for k, v in klines.items()}
    df_1m_p = prepared["kline_1m"]

    tick_size = estimate_tick_size(float(df_1m_p["close"].iloc[-1]))
    log.info(
        "tick_size estimated as %s (close=%s); only affects action creation",
        tick_size,
        float(df_1m_p["close"].iloc[-1]),
    )

    params = dict(config)
    params["config"] = config
    params.setdefault("enabled", True)
    strategy = VisualBuilderStrategy(params=params)

    leaf_stats: Counter = Counter()
    leaf_errors: Counter = Counter()
    rejection_reasons: Counter = Counter()
    weights: List[float] = []
    signals = 0
    evaluated = 0
    signal_events: List[Dict[str, Any]] = []
    init_cfg = config.get("initialization") or config.get("action") or {}
    init_direction = str(
        (init_cfg.get("params") or {}).get("direction", "LONG")
    ).upper()
    t0 = time.time()

    # Map each 1m position to the HTF slice end (tolerant ffill, like live).
    htf_pos: Dict[str, Any] = {}
    for key, df in prepared.items():
        if key == "kline_1m":
            continue
        try:
            htf_pos[key] = df.index.get_indexer(df_1m_p.index, method="ffill")
        except Exception:
            htf_pos[key] = np.full(len(df_1m_p), -1)

    for n, i in enumerate(indices):
        if n and n % 1000 == 0:
            log.info("replayed %d/%d candles...", n, len(indices))
        market_data = {"kline_1m": df_1m_p.iloc[: i + 1]}
        for key, df in prepared.items():
            if key == "kline_1m":
                continue
            j = int(htf_pos[key][i]) if i < len(htf_pos[key]) else -1
            if j >= 0:
                market_data[key] = df.iloc[: j + 1]
        pair_info = build_pair_info(symbol, main_tf, df_1m_p, i, tick_size)
        try:
            signal, weight, trace = strategy.check_signal_sync(
                pair_info, market_data, None
            )
        except Exception as e:
            leaf_stats[("ENGINE:exception", "error")] += 1
            log.warning("check_signal_sync raised at %s: %s", i, e)
            continue
        evaluated += 1
        weights.append(float(weight or 0.0))
        if signal is not None:
            signals += 1
            signal_events.append(
                {
                    "index": int(i),
                    "timestamp": pair_info.get("timestamp_dt"),
                    "direction": init_direction,
                    "entry": float(pair_info.get("close")),
                    "atr": pair_info.get("atr"),
                    "tick_size": tick_size,
                }
            )
        if isinstance(trace, dict):
            rr = trace.get("rejection_reason")
            if rr:
                rejection_reasons[rr] += 1
            walk_trace(trace, leaf_stats, leaf_errors)

    dt = time.time() - t0
    log.info("replay done: %d candles in %.1fs", evaluated, dt)
    return {
        "evaluated": evaluated,
        "signals": signals,
        "weights": weights,
        "leaf_stats": leaf_stats,
        "leaf_errors": leaf_errors,
        "rejection_reasons": rejection_reasons,
        "signal_events": signal_events,
        "init_direction": init_direction,
    }


def lint_exit_plan(config: Dict[str, Any]) -> List[str]:
    """Static audit of initialization/positionManagement exit config."""
    issues: List[str] = []
    init_cfg = config.get("initialization") or config.get("action") or {}
    ip = init_cfg.get("params", {}) if isinstance(init_cfg, dict) else {}
    if not isinstance(ip, dict):
        return ["initialization params are not a dict: exits cannot be simulated"]
    if ip.get("sl_type", "atr_multiplier") != "atr_multiplier":
        issues.append(
            f"sl_type '{ip.get('sl_type')}' is not simulated "
            f"(only atr_multiplier supported)"
        )
    if ip.get("tp_type", "rr_multiplier") != "rr_multiplier":
        issues.append(
            f"tp_type '{ip.get('tp_type')}' is not simulated "
            f"(only rr_multiplier supported)"
        )
    partials = ip.get("partial_exits") or []
    total_pct = 0.0
    for pt in partials:
        if not isinstance(pt, dict):
            continue
        if pt.get("tp_type", "rr_multiplier") != "rr_multiplier":
            issues.append(
                f"partial tp_type '{pt.get('tp_type')}' is not simulated "
                f"(only rr_multiplier supported)"
            )
        try:
            total_pct += float(pt.get("size_pct", 0))
        except (TypeError, ValueError):
            issues.append(f"partial with non-numeric size_pct: {pt}")
    if partials and total_pct >= 100.0 and ip.get("tp_value") is not None:
        issues.append(
            f"partials cover {total_pct:.0f}%: final TP (rr {ip.get('tp_value')}) "
            f"is unreachable and will be ignored"
        )
    for block in config.get("positionManagement") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "move_to_breakeven":
            bp = block.get("params", {}) or {}
            if bp.get("target_type", "rr_multiplier") != "rr_multiplier":
                issues.append(
                    f"breakeven target_type '{bp.get('target_type')}' is not "
                    f"simulated (only rr_multiplier supported)"
                )
    return issues


def _unsupported_exits(config: Dict[str, Any]) -> Optional[str]:
    """Returns a reason if the exit plan cannot be simulated, else None."""
    init_cfg = config.get("initialization") or config.get("action") or {}
    ip = init_cfg.get("params", {}) if isinstance(init_cfg, dict) else {}
    if not isinstance(ip, dict):
        return "initialization params are not a dict"
    if ip.get("sl_type", "atr_multiplier") != "atr_multiplier":
        return f"unsupported sl_type {ip.get('sl_type')}"
    if ip.get("tp_type", "rr_multiplier") != "rr_multiplier":
        return f"unsupported tp_type {ip.get('tp_type')}"
    for pt in ip.get("partial_exits") or []:
        if (
            isinstance(pt, dict)
            and pt.get("tp_type", "rr_multiplier") != "rr_multiplier"
        ):
            return f"unsupported partial tp_type {pt.get('tp_type')}"
    for block in config.get("positionManagement") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "move_to_breakeven":
            bp = block.get("params", {}) or {}
            if bp.get("target_type", "rr_multiplier") != "rr_multiplier":
                return f"unsupported breakeven target_type {bp.get('target_type')}"
    return None


def simulate_pnl(
    signal_events: List[Dict[str, Any]],
    df_1m: pd.DataFrame,
    config: Dict[str, Any],
    fee_bps: float = 5.0,
    notional: float = 1000.0,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Lightweight exit simulator over 1m candles (LONG/SHORT symmetric).

    Mirrors production exit semantics: SL = entry -/+ ATR*sl_value,
    partial/final TPs at R multiples, breakeven move at target R with
    offset_pips*tick_size. Conservative same-candle rule: if a candle
    touches both SL and a profit target, the SL fill is assumed first.
    One position at a time; overlapping signals are counted, not traded.
    Fees apply per side on filled notional.
    """
    init_cfg = config.get("initialization") or config.get("action") or {}
    ip = init_cfg.get("params", {}) if isinstance(init_cfg, dict) else {}
    direction = str(ip.get("direction", "LONG")).upper()
    sign = 1 if direction == "LONG" else -1
    sl_value = float(ip.get("sl_value", 2.0))
    tp_value = float(ip.get("tp_value", 2.0))
    partials_cfg = [
        p
        for p in (ip.get("partial_exits") or [])
        if isinstance(p, dict) and float(p.get("size_pct", 0)) > 0
    ]
    partials_cfg.sort(key=lambda p: float(p.get("tp_value", 0)))

    be_target = None
    be_offset_pips = 0
    for block in config.get("positionManagement") or []:
        if isinstance(block, dict) and block.get("type") == "move_to_breakeven":
            bp = block.get("params", {}) or {}
            be_target = float(bp.get("target_value", 2.0))
            be_offset_pips = int(bp.get("offset_pips", 0))
            break

    fee_rate = fee_bps / 10000.0
    closes = df_1m["close"].to_numpy(dtype=float)
    highs = df_1m["high"].to_numpy(dtype=float)
    lows = df_1m["low"].to_numpy(dtype=float)
    last_idx = len(df_1m) - 1

    trades: List[Dict[str, Any]] = []
    summary = {
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "total_r": 0.0,
        "total_usdt": 0.0,
        "total_fees_usdt": 0.0,
        "skipped_overlap": 0,
        "skipped_no_atr": 0,
        "gross_win_r": 0.0,
        "gross_loss_r": 0.0,
    }
    busy_until = -1

    def ts_of(idx: int) -> str:
        ts = df_1m.index[idx]
        try:
            return ts.isoformat()
        except Exception:
            return str(ts)

    for ev in signal_events:
        i = int(ev["index"])
        if i <= busy_until:
            summary["skipped_overlap"] += 1
            continue
        atr = ev.get("atr")
        if atr is None or not np.isfinite(float(atr)) or float(atr) <= 0:
            summary["skipped_no_atr"] += 1
            continue
        entry = float(ev["entry"])
        tick = float(ev.get("tick_size") or 0.0) or estimate_tick_size(entry)
        risk = float(atr) * sl_value
        if risk <= 0 or entry <= 0:
            summary["skipped_no_atr"] += 1
            continue
        qty = notional / entry
        stop = entry - sign * risk
        levels = [
            (
                entry + sign * risk * float(p.get("tp_value", 0)),
                float(p.get("size_pct", 0)) / 100.0,
            )
            for p in partials_cfg
        ]
        final_tp = entry + sign * risk * tp_value
        remaining = 1.0
        be_active = False
        be_stop = None
        fills: List[Dict[str, Any]] = []
        exit_reason = "timeout"
        exit_idx = last_idx

        def touched(price: float, high: float, low: float, is_stop: bool) -> bool:
            if sign > 0:
                return (low <= price) if is_stop else (high >= price)
            return (high >= price) if is_stop else (low <= price)

        closed = False
        for j in range(i + 1, last_idx + 1):
            h, low = float(highs[j]), float(lows[j])
            cur_stop = be_stop if be_active else stop
            # 1. Stop first (conservative same-candle rule).
            if touched(cur_stop, h, low, True):
                fills.append(
                    {
                        "price": cur_stop,
                        "frac": remaining,
                        "reason": "breakeven" if be_active else "stop",
                    }
                )
                remaining = 0.0
                exit_reason = "breakeven" if be_active else "stop"
                exit_idx = j
                closed = True
                break
            # 2. Breakeven activation on the extreme.
            if (
                not be_active
                and be_target is not None
                and touched(entry + sign * risk * be_target, h, low, False)
            ):
                be_active = True
                be_stop = entry + sign * be_offset_pips * tick
            # 3. Partials in ascending R order.
            for k, (lvl, frac) in enumerate(levels):
                if frac <= 0 or remaining <= 0:
                    continue
                tag = f"partial_{k}"
                if any(f.get("tag") == tag for f in fills):
                    continue
                if touched(lvl, h, low, False):
                    take = min(frac, remaining)
                    fills.append(
                        {
                            "price": lvl,
                            "frac": take,
                            "reason": f"partial_{float(partials_cfg[k].get('tp_value', 0))}R",
                            "tag": tag,
                        }
                    )
                    remaining -= take
                    if remaining <= 1e-9:
                        remaining = 0.0
                        exit_reason = "partial"
                        exit_idx = j
                        closed = True
                        break
            if closed:
                break
            # 4. Final TP only if partials leave remainder.
            if remaining > 0 and sum(f for _, f in levels) < 1.0 - 1e-9:
                if touched(final_tp, h, low, False):
                    fills.append(
                        {"price": final_tp, "frac": remaining, "reason": "take_profit"}
                    )
                    remaining = 0.0
                    exit_reason = "take_profit"
                    exit_idx = j
                    break

        if remaining > 0:
            px = float(closes[exit_idx])
            fills.append({"price": px, "frac": remaining, "reason": exit_reason})
        # Gross move PnL minus entry fee and per-fill exit fees.
        gross = sum(sign * (f["price"] - entry) * qty * f["frac"] for f in fills)
        total_fee = notional * fee_rate + sum(
            qty * f["frac"] * f["price"] * fee_rate for f in fills
        )
        net = gross - total_fee
        r_mult = net / (risk * qty) if risk * qty > 0 else 0.0

        summary["trades"] += 1
        summary["total_r"] += r_mult
        summary["total_usdt"] += net
        summary["total_fees_usdt"] += total_fee
        if net > 0:
            summary["wins"] += 1
            summary["gross_win_r"] += r_mult
        else:
            summary["losses"] += 1
            summary["gross_loss_r"] += -r_mult
        busy_until = exit_idx
        trades.append(
            {
                "entry_time": ts_of(i),
                "exit_time": ts_of(exit_idx),
                "direction": direction,
                "entry": entry,
                "risk": risk,
                "r": round(r_mult, 3),
                "net_usdt": round(net, 2),
                "fees_usdt": round(total_fee, 2),
                "exit_reason": exit_reason,
                "fills": [
                    {
                        "price": round(f["price"], 4),
                        "frac": f["frac"],
                        "reason": f["reason"],
                    }
                    for f in fills
                ],
            }
        )
        if len(trades) >= 5000:
            break

    n = summary["trades"]
    summary["winrate"] = summary["wins"] / n if n else 0.0
    summary["avg_r"] = summary["total_r"] / n if n else 0.0
    summary["profit_factor"] = (
        summary["gross_win_r"] / summary["gross_loss_r"]
        if summary["gross_loss_r"] > 0
        else float("inf")
        if summary["gross_win_r"] > 0
        else 0.0
    )
    # Max drawdown on per-trade R equity.
    peak, dd, eq = 0.0, 0.0, 0.0
    for t in trades:
        eq += t["r"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    summary["max_dd_r"] = dd
    summary["fee_bps"] = fee_bps
    summary["notional"] = notional
    return trades, summary


def decide_verdict(
    stats: Dict[str, Any],
    lint_issues: List[str],
    weight_gap: bool,
    threshold: float,
) -> Tuple[str, List[str]]:
    evaluated = stats["evaluated"]
    signals = stats["signals"]
    reasons = stats["rejection_reasons"]
    weights = stats["weights"]
    leaf_stats = stats["leaf_stats"]

    findings = list(lint_issues)
    max_weight = max(weights) if weights else 0.0

    weight_rejects = reasons.get("weight_threshold", 0)
    if (
        evaluated
        and signals == 0
        and max_weight < threshold
        and (weight_rejects or weight_gap)
    ):
        return "CONFIG", findings + [
            f"max accrued weight {max_weight:.1f} < threshold {threshold} "
            f"({weight_rejects} dynamic weight rejections; "
            f"static weight-key gap: {weight_gap}). Even a perfect setup "
            f"could not pass the weight gate."
        ]
    if signals > 0:
        rate = 100.0 * signals / max(evaluated, 1)
        return "MARKET-OK", findings + [
            f"strategy fires: {signals}/{evaluated} candles ({rate:.2f}%)"
        ]

    total_leaf_errors = sum(v for (k, kind), v in leaf_stats.items() if kind == "error")
    total_leaf = sum(leaf_stats.values())
    if total_leaf and total_leaf_errors / total_leaf > 0.2:
        worst = sorted(
            ((k, v) for (k, kind), v in leaf_stats.items() if kind == "error"),
            key=lambda kv: -kv[1],
        )[:5]
        return "DATA", findings + [
            f"{100.0 * total_leaf_errors / total_leaf:.1f}% leaf evaluations "
            f"are data errors (not market decisions). Worst: "
            + ", ".join(f"{k} x{v}" for k, v in worst)
        ]

    # Pure market selectivity: name the strictest clean-failing leaves.
    fails = sorted(
        ((k, v) for (k, kind), v in leaf_stats.items() if kind == "fail"),
        key=lambda kv: -kv[1],
    )[:5]
    detail = (
        ", ".join(f"{k} failed {v}/{evaluated}" for k, v in fails)
        if fails
        else "no leaf failures recorded"
    )
    return "MARKET", findings + [
        f"0/{evaluated} signals, data healthy. Strictest blocks: {detail}. "
        f"Top rejection reasons: {dict(reasons.most_common(5))}"
    ]


def print_report(
    stats: Dict[str, Any],
    lint_issues: List[str],
    verdict: str,
    verdict_detail: List[str],
    threshold: float,
    pnl_summary: Optional[Dict[str, Any]] = None,
    trades: Optional[List[Dict[str, Any]]] = None,
) -> None:
    print("=" * 72)
    print(f"VERDICT: {verdict}")
    for line in verdict_detail:
        print(f"  - {line}")
    print("-" * 72)
    print(
        f"candles={stats['evaluated']} signals={stats['signals']} "
        f"threshold={threshold} max_weight={max(stats['weights']) if stats['weights'] else 0:.1f}"
    )
    print(f"rejections: {dict(stats['rejection_reasons'].most_common())}")
    if lint_issues:
        print("config lints:")
        for issue in lint_issues:
            print(f"  ! {issue}")
    if pnl_summary is not None:
        print("-" * 72)
        print(
            f"PnL: trades={pnl_summary['trades']} "
            f"winrate={100.0 * pnl_summary['winrate']:.1f}% "
            f"total={pnl_summary['total_r']:+.2f}R / "
            f"{pnl_summary['total_usdt']:+.2f} USDT "
            f"(fees {pnl_summary['total_fees_usdt']:.2f}, "
            f"notional {pnl_summary['notional']:.0f}, "
            f"fee {pnl_summary['fee_bps']}bps/side)"
        )
        print(
            f"  avg={pnl_summary['avg_r']:+.2f}R "
            f"PF={pnl_summary['profit_factor']:.2f} "
            f"maxDD={pnl_summary['max_dd_r']:.2f}R "
            f"overlap_skipped={pnl_summary['skipped_overlap']} "
            f"no_atr_skipped={pnl_summary['skipped_no_atr']}"
        )
        for t in (trades or [])[:15]:
            print(
                f"  {t['entry_time'][:16]} {t['direction']:5s} "
                f"in={t['entry']:.2f} out={t['exit_reason']:10s} "
                f"{t['r']:+.2f}R {t['net_usdt']:+.2f}$"
            )
        if trades and len(trades) > 15:
            print(f"  ... and {len(trades) - 15} more (see --json-out)")
    print("per-block (pass / fail / error):")
    leaves = sorted({k for (k, _) in stats["leaf_stats"]})
    for k in leaves:
        p = stats["leaf_stats"].get((k, "pass"), 0)
        f = stats["leaf_stats"].get((k, "fail"), 0)
        e = stats["leaf_stats"].get((k, "error"), 0)
        flag = "  <-- DATA ERRORS" if e and e > (p + f) else ""
        print(f"  {k}: pass={p} fail={f} error={e}{flag}")
    print("=" * 72)


def main() -> int:
    ap = argparse.ArgumentParser(description="VisualBuilder strategy autopsy")
    ap.add_argument("--config", required=True, help="path to strategy JSON")
    ap.add_argument("--symbol", required=True, help="e.g. ZECUSDT")
    ap.add_argument("--market", default="futures_usdtm")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument(
        "--max-candles", type=int, default=0, help="0 = all candles in window"
    )
    ap.add_argument("--json-out", default="")
    ap.add_argument(
        "--strict", action="store_true", help="exit 2 on CONFIG or DATA verdict"
    )
    ap.add_argument(
        "--pnl",
        action="store_true",
        help="simulate exits (SL/TP/partials/BE/fees) for every signal",
    )
    ap.add_argument(
        "--fee-bps", type=float, default=5.0, help="taker fee per side in bps"
    )
    ap.add_argument(
        "--notional", type=float, default=1000.0, help="position notional in USDT"
    )
    args = ap.parse_args()

    config = load_config(args.config)
    lint_issues, weight_gap = lint_config(config)
    print("config lints:")
    for issue in lint_issues:
        print(f"  ! {issue}")
    if not lint_issues:
        print("  (none)")

    threshold = float(
        config.get(
            "min_total_foundation_weight_threshold",
            config.get("min_foundation_weight_threshold", 50.0),
        )
    )
    main_tf = (
        (config.get("entryTrigger") or {}).get("timeframe")
        or config.get("tradingTimeframe")
        or "1m"
    )
    tfs = collect_timeframes(config, main_tf)
    log.info("downloading %s %s for %dd...", args.symbol, sorted(tfs), args.days)
    klines = asyncio.run(download_all(args.symbol, args.market, tfs, args.days))

    stats = run_replay(
        config,
        args.symbol,
        klines,
        main_tf,
        args.max_candles or None,
    )
    verdict, detail = decide_verdict(stats, lint_issues, weight_gap, threshold)

    trades: List[Dict[str, Any]] = []
    pnl_summary: Optional[Dict[str, Any]] = None
    if args.pnl:
        unsupported = _unsupported_exits(config)
        if unsupported:
            print(f"PnL simulation skipped: {unsupported}")
        elif not stats["signal_events"]:
            print("PnL simulation skipped: no signals to simulate")
        else:
            trades, pnl_summary = simulate_pnl(
                stats["signal_events"],
                klines["kline_1m"],
                config,
                fee_bps=args.fee_bps,
                notional=args.notional,
            )
    print_report(stats, lint_issues, verdict, detail, threshold, pnl_summary, trades)

    if args.json_out:
        serializable = {
            "verdict": verdict,
            "detail": detail,
            "lint_issues": lint_issues,
            "evaluated": stats["evaluated"],
            "signals": stats["signals"],
            "threshold": threshold,
            "rejection_reasons": dict(stats["rejection_reasons"]),
            "leaf_stats": {
                f"{k}::{kind}": v for (k, kind), v in stats["leaf_stats"].items()
            },
            "pnl": pnl_summary,
            "trades": trades,
        }
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, default=str)
        print(f"report written to {args.json_out}")

    if args.strict and verdict in ("CONFIG", "DATA"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
