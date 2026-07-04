import pandas as pd
import numpy as np
import pytest
import pandas_ta as ta
from pathlib import Path

# pandas_ta<=0.3.14b0 expects numpy.NaN; numpy>=2 removed this alias.
if not hasattr(np, "NaN"):
    np.NaN = np.nan

from bot_module.datatypes import BasePosition
from bot_module.fast_vector_backtester import FastVectorBacktester
from bot_module.strategy import SignalDirection, VisualBuilderStrategy
from bot_module import config

FAST_SLIPPAGE_PCT = 0.0
FAST_COMMISSION_PCT = 0.0


def load_real_data(symbol="RIVERUSDT", rows=1000) -> pd.DataFrame:
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

    try:
        df = pd.read_parquet(data_path)
        if df.empty or not all(c in df.columns for c in ["open", "high", "low", "close"]):
            pytest.skip(f"Data for {symbol} is empty or missing required OHLC columns")
        # Take a slice to speed up tests
        return df.iloc[:rows].copy()
    except Exception as e:
        pytest.skip(f"Failed to load/read parquet data for {symbol}: {e}")


def _to_utc_ts(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _compute_fast_style_sl_tp(
    entry_price: float, direction: SignalDirection, init_params: dict, atr: float
) -> tuple[float, float]:
    sl_type = init_params.get("sl_type", "percent_from_price")
    sl_value = float(init_params.get("sl_value", 1.0))
    tp_value = float(init_params.get("tp_value", 2.0))

    if sl_type == "atr_multiplier":
        sl_distance = atr * sl_value
    else:
        sl_distance = entry_price * (sl_value / 100.0)

    if direction == SignalDirection.SHORT:
        sl_price = entry_price + sl_distance
        tp_price = entry_price - abs(entry_price - sl_price) * tp_value
    else:
        sl_price = entry_price - sl_distance
        tp_price = entry_price + abs(entry_price - sl_price) * tp_value

    return sl_price, tp_price


async def _run_strategy_replay(
    df_live: pd.DataFrame, strategy_json: dict
) -> list[dict]:
    # We must ensure indicators required by the strategy are in pair_info.
    # FastVectorBacktester calculates them internally, so we simulate that for VBS.
    df = df_live.copy()

    # Ensure indicators are present and filled (they should be pre-calculated in the main test)
    if "ATR_14" not in df.columns:
        df["ATR_14"] = (
            ta.atr(high=df["high"], low=df["low"], close=df["close"], length=14)
            .ffill()
            .bfill()
            .fillna(0)
        )
    if "NATR_14" not in df.columns:
        high_low = df["high"] - df["low"]
        close_adj = df["close"].replace(0, 1)
        df["NATR_14"] = (
            ((high_low / close_adj) * 100)
            .rolling(window=14)
            .mean()
            .ffill()
            .bfill()
            .fillna(0)
        )

    strategy = VisualBuilderStrategy(
        params={
            "config": strategy_json,
            "enabled": True,
            "min_total_foundation_weight_threshold": 0.0,
            "foundation_weights": {"w_filter": 50.0, "w_signal": 50.0},
        }
    )
    market_data = {"kline_1m": df}
    init_params = strategy_json["initialization"]["params"]

    trade_log: list[dict] = []
    prev_pair_info = None
    pending_signal = None
    position = None

    for i, (ts, row) in enumerate(df.iloc[:-1].iterrows()):
        atr_val = row["ATR_14"] if not pd.isna(row["ATR_14"]) else row["close"] * 0.01

        pair_info = {
            **row.to_dict(),
            "symbol": "RIVERUSDT",
            "last_price": float(row["close"]),
            "atr": float(atr_val),
            "tick_size": 1e-8,
            "candle_timeframe": "1m",
            "timestamp_dt": ts.to_pydatetime(),
            "current_candle_index": i,
            "is_live_mode": False,
        }

        if pending_signal is not None:
            entry_raw = float(row["open"])
            if pending_signal.direction == SignalDirection.SHORT:
                entry_price = entry_raw * (1.0 - FAST_SLIPPAGE_PCT)
            else:
                entry_price = entry_raw * (1.0 + FAST_SLIPPAGE_PCT)

            # --- Use ATR from the SIGNAL candle (i-1) ---
            # FastVectorBacktester now uses np_atr[real_entry_idx - 1] to match live trading.
            atr = df["ATR_14"].iloc[i - 1]

            sl_price, tp_price = _compute_fast_style_sl_tp(
                entry_price=entry_price,
                direction=pending_signal.direction,
                init_params=init_params,
                atr=atr,
            )

            position = BasePosition(
                symbol=pending_signal.symbol,
                direction=pending_signal.direction,
                entry_price=entry_price,
                initial_quantity=1.0,
                remaining_quantity=1.0,
                entry_time=ts.to_pydatetime(),
                strategy=pending_signal.strategy_name,
                initial_stop_loss=sl_price,
                current_sl_price=sl_price,
                initial_take_profit=tp_price,
                move_sl_to_be_enabled=pending_signal.move_sl_to_be_on_first_tp,
                signal_details=pending_signal.details or {},
            )
            position.partial_targets = pending_signal.partial_targets or []
            position.partial_fills = []
            position.executions = []
            pending_signal = None

        closed_this_candle = False
        if position is not None:
            position, exit_details = await strategy.manage_position(
                position, pair_info, market_data, prev_pair_info
            )
            if exit_details:
                exit_raw = float(exit_details.get("exit_price", row["close"]))
                if position.direction == SignalDirection.SHORT:
                    exit_price = exit_raw * (1.0 + FAST_SLIPPAGE_PCT)
                    gross_pnl_pct = (
                        position.entry_price - exit_price
                    ) / position.entry_price
                else:
                    exit_price = exit_raw * (1.0 - FAST_SLIPPAGE_PCT)
                    gross_pnl_pct = (
                        exit_price - position.entry_price
                    ) / position.entry_price

                net_pnl_pct = gross_pnl_pct - (FAST_COMMISSION_PCT * 2.0)
                trade_log.append(
                    {
                        "entry_time": position.entry_time,
                        "exit_time": ts.to_pydatetime(),
                        "direction": position.direction.name,
                        "exit_reason": str(exit_details.get("reason", "UNKNOWN")),
                        "pnl_pct": float(net_pnl_pct),
                    }
                )
                position = None
                closed_this_candle = True

        if position is None and pending_signal is None and not closed_this_candle:
            signal, _, _ = await strategy.check_signal(
                pair_info,
                market_data,
                prev_pair_info,
                analysis_level="second_bar_trigger",
            )
            if signal is not None:
                pending_signal = signal

        prev_pair_info = pair_info

    return trade_log


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
async def test_real_data_parity(direction):
    # Strategy that triggers on a trend and NATR threshold
    operator = "gt" if direction == "LONG" else "lt"
    strategy_json = {
        "filters": {
            "id": "w_filter",
            "type": "natr_filter",
            "params": {
                "period": 14,
                "operator": "gt",
                "value": 0.1,
            },  # Low value to ensure triggers
        },
        "entryConditions": {
            "id": "w_signal",
            "type": "value_comparison",
            "params": {
                "leftOperand": {"source": "candle", "key": "close"},
                "rightOperand": {"source": "candle", "key": "open"},
                "operator": operator,
            },
        },
        "initialization": {
            "id": "init",
            "type": "open_position",
            "params": {
                "direction": direction,
                "sl_type": "atr_multiplier",
                "sl_value": 1.5,
                "tp_type": "rr_multiplier",
                "tp_value": 2.0,
            },
        },
    }

    df_raw = load_real_data("RIVERUSDT", rows=1000)
    df_raw["ATR_14"] = (
        ta.atr(high=df_raw["high"], low=df_raw["low"], close=df_raw["close"], length=14)
        .ffill()
        .bfill()
        .fillna(0)
    )
    high_low = df_raw["high"] - df_raw["low"]
    close_adj = df_raw["close"].replace(0, 1)
    df_raw["NATR_14"] = (high_low / close_adj).rolling(window=14).mean() * 100
    df_raw["NATR_14"] = df_raw["NATR_14"].ffill().bfill().fillna(0)

    df_fast = df_raw.copy()
    if df_fast.index.tz is not None:
        df_fast.index = df_fast.index.tz_convert(None)

    risk_params = {
        "risk_pct_per_trade": 1.0,
        "max_stop_distance_pct": 100.0,
        "min_rr_ratio": 0.0,
    }
    execution_config = {
        "commission_pct": 0.0,
        "slippage_pct": 0.0,
    }
    fast_bt = FastVectorBacktester(
        df_fast,
        strategy_json,
        risk_params=risk_params,
        execution_config=execution_config,
        initial_balance=1000000.0,
    )
    orig_funding = getattr(config, "BACKTEST_FUNDING_RATE_8H", 0.0001)
    config.BACKTEST_FUNDING_RATE_8H = 0.0
    try:
        fast_bt.run()
    finally:
        config.BACKTEST_FUNDING_RATE_8H = orig_funding

    strategy_trades = await _run_strategy_replay(df_raw, strategy_json)

    print(
        f"\nComparing {direction} trades: Fast={len(fast_bt.trade_log)}, Replay={len(strategy_trades)}"
    )

    # Assert there are trades to compare
    assert len(fast_bt.trade_log) > 0, (
        f"No trades generated by FastVectorBacktester for {direction}"
    )
    assert len(strategy_trades) > 0, "No trades generated by Strategy Replay"

    # One trade difference at the end is acceptable due to data truncation
    assert abs(len(fast_bt.trade_log) - len(strategy_trades)) <= 1

    compare_count = min(len(fast_bt.trade_log), len(strategy_trades))
    for i in range(compare_count):
        fast_t = fast_bt.trade_log[i]
        strat_t = strategy_trades[i]

        assert fast_t["direction"] == strat_t["direction"], (
            f"Trade {i} direction mismatch"
        )
        assert fast_t["exit_reason"] == strat_t["exit_reason"], (
            f"Trade {i} exit reason mismatch"
        )
        assert _to_utc_ts(fast_t["entry_time"]) == _to_utc_ts(strat_t["entry_time"]), (
            f"Trade {i} entry time mismatch"
        )
        assert _to_utc_ts(fast_t["exit_time"]) == _to_utc_ts(strat_t["exit_time"]), (
            f"Trade {i} exit time mismatch"
        )
        assert float(fast_t["pnl_pct"]) == pytest.approx(
            strat_t["pnl_pct"], abs=1e-10
        ), f"Trade {i} PnL mismatch"
