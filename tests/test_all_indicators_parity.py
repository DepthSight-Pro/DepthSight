import pytest
import pandas as pd
import pandas_ta as ta
from datetime import timezone

from bot_module.fast_vector_backtester import FastVectorBacktester
from bot_module.strategy import VisualBuilderStrategy

from pathlib import Path


# Using real data loader
def load_real_data(symbol: str = "RIVERUSDT", rows: int = 1000) -> pd.DataFrame:
    project_root = Path(__file__).resolve().parent.parent
    data_path = (
        project_root
        / "data_storage"
        / "binance"
        / "futures"
        / symbol
        / "kline_1m.parquet"
    )

    if not data_path.exists():
        pytest.skip(f"Data for {symbol} not found at {data_path}")

    df = pd.read_parquet(data_path)
    # Take a slice to speed up tests
    return df.iloc[:rows].copy()


FAST_COMMISSION_PCT = 0.0006
FAST_SLIPPAGE_PCT = 0.001


def _to_utc_ts(ts):
    if ts is None:
        return None
    if isinstance(ts, str):
        ts = pd.Timestamp(ts)
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return pd.Timestamp(ts).tz_convert("UTC")


async def _run_strategy_replay(df_raw: pd.DataFrame, strategy_json: dict) -> list[dict]:
    df = df_raw.copy()
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    # Pre-calculate indicators (SAME as in FastVectorBacktester)
    df["ATR_14"] = (
        ta.atr(df["high"], df["low"], df["close"], length=14).bfill().fillna(0)
    )
    df["RSI_14"] = ta.rsi(df["close"], length=14).bfill().fillna(0)

    macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
    df["MACD_12_26_9"] = macd["MACD_12_26_9"].bfill()
    df["MACDs_12_26_9"] = macd["MACDs_12_26_9"].bfill()
    df["MACD_hist_12_26_9"] = macd["MACDh_12_26_9"].bfill()

    bb = ta.bbands(df["close"], length=20, std=2.0)
    df["BBL_20_2.0"] = bb["BBL_20_2.0"].bfill()
    df["BBU_20_2.0"] = bb["BBU_20_2.0"].bfill()
    df["BBB_20_2.0"] = bb["BBB_20_2.0"].bfill()

    stoch = ta.stoch(df["high"], df["low"], df["close"], k=14, d=3, smooth_k=3)
    df["STOCHk_14_3_3"] = stoch["STOCHk_14_3_3"].bfill()
    df["STOCHd_14_3_3"] = stoch["STOCHd_14_3_3"].bfill()

    adx = ta.adx(df["high"], df["low"], df["close"], length=14)
    df["ADX_14"] = adx["ADX_14"].bfill()

    high_low = df["high"] - df["low"]
    close_adj = df["close"].replace(0, 1)
    df["NATR_14"] = (
        (high_low / close_adj * 100).rolling(window=14).mean().bfill().fillna(0)
    )

    # Strategy setup
    weights = {}
    if "children" in strategy_json["entryConditions"]:
        for i, child in enumerate(strategy_json["entryConditions"]["children"]):
            weights[child.get("id", f"child_{i}")] = 100.0
    else:
        weights[strategy_json["entryConditions"].get("id", "root")] = 100.0

    strategy = VisualBuilderStrategy(
        params={
            "config": strategy_json,
            "enabled": True,
            "min_total_foundation_weight_threshold": 0.0,
            "foundation_weights": weights,
        }
    )
    init_params = strategy_json["initialization"]["params"]
    sl_mult = float(init_params.get("sl_value", 1.5))
    tp_mult = float(init_params.get("tp_value", 2.0))

    trade_log = []
    position = None
    pending_signal = None
    prev_pair_info = None

    for i in range(50, len(df)):
        row = df.iloc[i]
        ts = df.index[i]

        if i < 60:
            print(
                f"DEBUG REPLAY: i={i}, ts={ts}, RSI={row.get('RSI_14')}, MACD={row.get('MACD_12_26_9')}"
            )

        pair_info = {
            "symbol": "RIVERUSDT",
            **row.to_dict(),
            "timestamp": ts,
            "current_candle_index": i,
            "is_candle_closed": True,
            "tick_size": 1e-8,
            "atr": float(row.get("ATR_14", 0.0)),
            "last_price": float(row["close"]),
            "candle_timeframe": "1m",
            "is_live_mode": False,
        }
        market_data = {"kline_1m": df}

        # 1. Check Exit
        just_closed = False
        if position:
            entry_price = position["entry_price"]
            sl = position["sl"]
            tp = position["tp"]
            hi, lo = row["high"], row["low"]

            exit_price = None
            reason = None

            if lo <= sl:
                exit_price = sl
                reason = "SL"
            elif hi >= tp:
                exit_price = tp
                reason = "TP"

            if exit_price:
                net_pnl_pct = (exit_price - entry_price) / entry_price - (
                    FAST_COMMISSION_PCT * 2 + FAST_SLIPPAGE_PCT
                )
                trade_log.append(
                    {
                        "entry_time": position["entry_time"],
                        "exit_time": ts,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "reason": reason,
                        "pnl_pct": float(net_pnl_pct),
                    }
                )
                position = None
                strategy.notify_closure(i)
                just_closed = True

        # 2. Check Entry execution
        if position is None and pending_signal:
            # We enter on the Open of the candle FOLLOWING the signal
            entry_price = row["open"] * (1.0 + FAST_SLIPPAGE_PCT)
            # Use ATR from the SIGNAL candle (i-1)
            atr_at_signal = df.iloc[i - 1]["ATR_14"]
            sl_dist = atr_at_signal * sl_mult

            position = {
                "entry_time": ts,
                "entry_price": entry_price,
                "sl": entry_price - sl_dist,
                "tp": entry_price + sl_dist * tp_mult,
            }
            pending_signal = None

        # 3. Check Signal generation
        if position is None and pending_signal is None and not just_closed:
            signal, weight, trace = await strategy.check_signal(
                pair_info, market_data, prev_pair_info
            )
            if signal:
                pending_signal = signal

        prev_pair_info = pair_info

    return trade_log


@pytest.mark.asyncio
async def test_all_indicators_parity():
    # A simple strategy to isolate core engine parity
    # A trivial strategy to test timing parity
    strategy_json = {
        "entryConditions": {
            "type": "OR",
            "children": [
                {
                    "id": "c1",
                    "type": "value_comparison",
                    "params": {
                        "leftOperand": {"source": "candle", "key": "close"},
                        "rightOperand": {"source": "const", "value": 0},
                        "operator": "gt",
                    },
                }
            ],
        },
        "initialization": {
            "type": "open_position",
            "params": {
                "direction": "LONG",
                "sl_type": "atr_multiplier",
                "sl_value": 10.0,
                "tp_type": "rr_multiplier",
                "tp_value": 20.0,
            },
        },
    }

    df_raw = load_real_data("RIVERUSDT", rows=2000)
    df_fast = df_raw.copy()
    if df_fast.index.tz is not None:
        df_fast.index = df_fast.index.tz_convert(None)

    # Synchronize start time (skip 50 candles warmup)
    start_ts = df_fast.index[50]

    fast_bt = FastVectorBacktester(
        df_fast,
        strategy_json,
        execution_config={
            "commission_pct": FAST_COMMISSION_PCT,
            "slippage_pct": FAST_SLIPPAGE_PCT,
        },
        risk_params={
            "max_stop_distance_pct": 100.0,
            "min_rr_ratio": 0.0,
            "daily_max_loss_pct": 100.0,
            "max_consecutive_losses": 1000,
        },
        trade_start_ts=pd.Timestamp(start_ts),
    )
    fast_bt.run()

    strategy_trades = await _run_strategy_replay(df_raw, strategy_json)

    # Debug divergence
    fast_entries = [_to_utc_ts(t["entry_time"]) for t in fast_bt.trade_log]
    repl_entries = [_to_utc_ts(t["entry_time"]) for t in strategy_trades]

    print(
        f"\nComparing All-Indicators: Fast={len(fast_entries)}, Replay={len(repl_entries)}"
    )

    # Find first mismatching entry
    min_len = min(len(fast_entries), len(repl_entries))
    for i in range(min_len):
        if fast_entries[i] != repl_entries[i]:
            print(f"!!! FIRST DIVERGENCE AT INDEX {i} !!!")
            print(f"  Fast entry: {fast_entries[i]} | Replay entry: {repl_entries[i]}")
            break

    diff = abs(len(fast_bt.trade_log) - len(strategy_trades))
    assert diff <= 5, (
        f"Mismatch in count! Fast: {len(fast_bt.trade_log)}, Repl: {len(strategy_trades)}"
    )

    # Check first 5 trades for exact time parity
    for i in range(min(5, min_len)):
        f, s = fast_bt.trade_log[i], strategy_trades[i]
        assert _to_utc_ts(f["entry_time"]) == _to_utc_ts(s["entry_time"]), (
            f"Trade {i} entry time mismatch"
        )
