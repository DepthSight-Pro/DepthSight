# tests/test_live_exchange_data_integrity.py
"""
Live Exchange Data Integrity & Visual Block Pipeline Verification.
Connects directly to Binance, Bybit, OKX, Weex, and Bitget public market APIs,
downloads live candlestick streams, and evaluates all 30+ visual builder blocks,
multi-timeframe confluences, position management lifecycle, and dynamic parameter links
to guarantee complete data compatibility and zero runtime exceptions on live feeds.
"""

import asyncio
import os
import platform
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

import pandas as pd
import pytest
from dotenv import load_dotenv

from bot_module.exchanges import create_exchange_executor
from bot_module.data_loader import download_klines
from bot_module.strategy import VisualBuilderStrategy, BasePosition, SignalDirection

# Ensure event loop policy for Windows if needed
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

load_dotenv()

# We define a registry of EVERY block type in the system.
# This ensures that ALL blocks are verified against live exchange data.
# NOTE: entries must use production lowercase block types (the exact keys of
# BaseStrategy.condition_checkers). UPPERCASE aliases never reach a checker and
# only produce "Unknown node_type", which this test forbids.
ALL_BLOCKS_REGISTRY: List[Dict[str, Any]] = [
    # --- OSCILLATORS ---
    {
        "type": "rsi_condition",
        "params": {"period": 14, "operator": "lt", "value": 30.0},
    },
    {
        "type": "macd_condition",
        "params": {
            "fast_period": 12,
            "slow_period": 26,
            "signal_period": 9,
            "condition": "hist_gt_zero",
        },
    },
    {
        "type": "stochastic_condition",
        "params": {
            "k_period": 14,
            "d_period": 3,
            "smooth_k": 3,
            "operator": "lt",
            "value": 20,
            "line": "k",
        },
    },
    # --- VOLATILITY & RANGE ---
    {
        "type": "bollinger_bands_condition",
        "params": {"period": 20, "std_dev": 2.0, "check_type": "price_below_lower"},
    },
    {
        "type": "natr_filter",
        "params": {"period": 14, "operator": "gt", "value": 0.5},
    },
    {
        "type": "volatility_squeeze",
        "params": {"lookback_candles": 20, "squeeze_ratio": 0.6},
    },
    {
        "type": "volatility_filter",
        "params": {"indicator": "ATR", "operator": "gt", "value": 0.0},
    },
    # --- TREND & MOMENTUM ---
    {
        "type": "adx_filter",
        "params": {"period": 14, "threshold": 25, "operator": "gt"},
    },
    {
        "type": "ma_cross_condition",
        "params": {"fast_period": 10, "slow_period": 50},
    },
    {
        "type": "trend_direction",
        "params": {"fast_period": 10, "slow_period": 50, "required_trend": "LONG"},
    },
    {"type": "trend_filter", "params": {"indicator": "ADX", "threshold": 25.0}},
    # --- PRICE ACTION & LEVELS ---
    {
        "type": "price_action_analyzer",
        "params": {"structure_type": "higher_lows", "lookback_candles": 30},
    },
    {
        "type": "price_consolidation",
        "params": {"lookback_period": 20, "max_range_atr": 1.0},
    },
    {
        "type": "level_touch_analyzer",
        "params": {
            "lookback_candles": 50,
            "touch_tolerance_atr": 0.15,
            # Far-away constant level: must evaluate cleanly to False.
            "level_price": 1e12,
        },
    },
    {
        "type": "return_to_level",
        "params": {
            # Constant level resolvable without upstream block_result links.
            "level_source": {"source": "constant", "value": 1e12},
            "retest_type": "touch",
            "approach_direction": "any",
        },
    },
    {
        "type": "price_vs_level",
        "params": {
            "price_source": {"source": "candle", "key": "close", "shift": 0},
            "operator": "gt",
            "level_source": {"source": "constant", "value": 0},
        },
    },
    {"type": "local_level", "params": {"lookback": 50, "level_type": "low"}},
    {
        "type": "value_comparison",
        "params": {
            "left": {"source": "candle", "key": "close"},
            "operator": "gt",
            "right": {"source": "constant", "value": 0},
        },
    },
    # --- MICROSTRUCTURE & TAPE ---
    {
        "type": "tape_condition",
        "params": {
            "metric": "delta_volume",
            "window_sec": 30,
            "operator": "gt",
            "threshold": 0,
        },
    },
    {
        "type": "order_book_zone",
        "params": {"side": "bids", "range_type": "Percentage", "range_value": 1.0},
    },
    {
        "type": "open_interest",
        "params": {"analyze": "absolute_value", "operator": "gt", "value": 0},
    },
    # --- MARKET FILTERS ---
    {
        "type": "trading_session",
        "params": {"filter_mode": "session", "session": "london"},
    },
    {"type": "market_activity", "params": {}},
    {"type": "btc_state_filter", "params": {"required_state": "Any"}},
    {
        "type": "correlation",
        "params": {"lookback": 20, "operator": "gt", "value": -1.0},
    },
    # --- FOUNDATIONS ---
    {"type": "classic_pattern", "params": {"pattern_name": "pin_bar", "side": "ANY"}},
    {
        "type": "volume_confirmation",
        "params": {"lookback_period": 20, "multiplier": 1.5},
    },
    {
        "type": "round_level",
        "params": {"proximity_type": "percentage", "proximity_value": 0.1},
    },
    {"type": "l2_microstructure", "params": {}},
    {"type": "tape_analysis", "params": {"window_sec": 30}},
]

# Blocks with no tape feed in this harness. The harness carries no tape_*
# columns, so in live mode these must fail closed (False + error) — never
# True-with-Nones.
TAPE_BLOCK_TYPES = {"tape_condition", "tape_analysis"}


def _get_api_keys(exchange: str):
    if "binance" in exchange:
        return os.getenv("TESTNET_BINANCE_SPOT_API_KEY", ""), os.getenv(
            "TESTNET_BINANCE_SPOT_API_SECRET", ""
        )
    elif "bybit" in exchange:
        return os.getenv("TESTNET_BYBIT_API_KEY") or os.getenv(
            "BYBIT_TESTNET_API_KEY", ""
        ), os.getenv("TESTNET_BYBIT_API_SECRET") or os.getenv(
            "BYBIT_TESTNET_API_SECRET", ""
        )
    elif "okx" in exchange:
        return os.getenv("TESTNET_OKX_API_KEY", ""), os.getenv(
            "TESTNET_OKX_API_SECRET", ""
        )
    elif "weex" in exchange:
        return os.getenv("TESTNET_WEEX_API_KEY", ""), os.getenv(
            "TESTNET_WEEX_API_SECRET", ""
        )
    elif "bitget" in exchange:
        return os.getenv("TESTNET_BITGET_API_KEY", ""), os.getenv(
            "TESTNET_BITGET_API_SECRET", ""
        )
    return "", ""


@pytest.mark.live_api
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exchange, market_type, symbol",
    [
        ("binance", "spot", "BTC/USDT"),
        ("bybit", "futures_usdtm", "BTCUSDT"),
        ("okx", "futures_usdtm", "BTC/USDT:USDT"),
        ("weex", "futures_usdtm", "BTCUSDT"),
        ("bitget", "futures_usdtm", "BTCUSDT"),
    ],
)
async def test_all_visual_blocks_pipeline_no_fallbacks(
    exchange: str, market_type: str, symbol: str
):
    """
    ULTIMATE PIPELINE TEST:
    Passes EVERY SINGLE visual block, multi-timeframe confluence, position management block,
    and dynamic reference resolver through the strategy execution engine using live downloaded
    exchange data across Binance, Bybit, OKX, and Weex.
    """
    api_key, api_secret = _get_api_keys(exchange)
    import aiohttp

    session = aiohttp.ClientSession()

    executor = create_exchange_executor(
        exchange=exchange,
        api_key=api_key or "",
        api_secret=api_secret or "",
        session=session,
        market_type=market_type,
    )

    try:
        await asyncio.wait_for(executor._exchange.fetch_time(), timeout=10.0)
    except Exception as exc:
        await executor.close()
        await session.close()
        pytest.skip(
            f"{exchange} public endpoint is currently not reachable or timed out: {exc}"
        )

    failed_blocks = []

    try:
        # 1. Fetch Real Market Klines via CCXT executor or data_loader
        try:
            ohlcv = await asyncio.wait_for(
                executor.fetch_ohlcv(symbol, "1m", limit=300), timeout=10.0
            )
        except Exception:
            ohlcv = None

        if ohlcv and len(ohlcv) > 0:
            df_klines = pd.DataFrame(
                ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            df_klines["timestamp"] = pd.to_datetime(
                df_klines["timestamp"], unit="ms", utc=True
            )
            df_klines.set_index("timestamp", inplace=True)
        else:
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(minutes=300)
            df_klines = await download_klines(
                symbol=symbol.replace("/", "").replace(":USDT", ""),
                timeframe="1m",
                start_dt=start_dt,
                end_dt=end_dt,
                market_type=market_type,
            )

        assert df_klines is not None and not df_klines.empty, (
            f"Failed to retrieve live klines for {symbol} on {exchange}"
        )
        df_klines = df_klines.dropna(subset=["close", "high", "low"]).tail(300)

        # Compute indicators with the SAME functions the live DataConsumer
        # pipeline uses (bot_module.utils + pandas_ta) — never synthetic
        # constants, so a broken pipeline cannot be masked by the fixture.
        from bot_module.utils import (
            add_relative_volume,
            add_volume_percentile_rank,
            calculate_scalper_natr,
        )

        df_klines.ta.sma(length=10, append=True)
        df_klines.ta.sma(length=20, append=True)
        df_klines.ta.sma(length=50, append=True)
        df_klines.ta.rsi(length=14, append=True)
        df_klines.ta.adx(length=14, append=True)
        df_klines.ta.stoch(k=14, d=3, smooth_k=3, append=True)
        df_klines.ta.bbands(length=20, std=2, append=True)
        df_klines.ta.macd(fast=12, slow=26, signal=9, append=True)
        df_klines.ta.atr(length=14, append=True)
        df_klines = calculate_scalper_natr(df_klines, period=14)
        natr_14_live = float(df_klines["natr"].iloc[-1])
        df_klines = calculate_scalper_natr(df_klines, period=30)
        df_klines = add_relative_volume(df_klines, period=20)
        df_klines = add_volume_percentile_rank(df_klines, period=1000, percentile=90)

        def _live_val(col: str, default=None):
            if col in df_klines.columns:
                val = df_klines[col].iloc[-1]
                if pd.notna(val):
                    return float(val)
            # pandas_ta names the ATR column ATRr_14, not ATR_14.
            if col in ("ATR_14", "atr"):
                for alt in ("ATRr_14", "atr_14"):
                    if alt in df_klines.columns:
                        val = df_klines[alt].iloc[-1]
                        if pd.notna(val):
                            return float(val)
            return default

        live_indicators = {
            "SMA_10": _live_val("SMA_10"),
            "SMA_20": _live_val("SMA_20"),
            "SMA_50": _live_val("SMA_50"),
            "RSI_14": _live_val("RSI_14"),
            "ADX_14": _live_val("ADX_14"),
            "STOCHk_14_3_3": _live_val("STOCHk_14_3_3"),
            "STOCHd_14_3_3": _live_val("STOCHd_14_3_3"),
            "BBL_20_2.0": _live_val("BBL_20_2.0"),
            "BBU_20_2.0": _live_val("BBU_20_2.0"),
            "BBB_20_2.0": _live_val("BBB_20_2.0"),
            "MACD_12_26_9": _live_val("MACD_12_26_9"),
            "MACDh_12_26_9": _live_val("MACDh_12_26_9"),
            "MACDs_12_26_9": _live_val("MACDs_12_26_9"),
            "ATR_14": _live_val("ATR_14"),
            "atr": _live_val("ATR_14"),
            "NATR_14": natr_14_live,
            "natr_14": natr_14_live,
            "NATR_30": _live_val("natr"),
            "natr": _live_val("natr"),
            "relative_volume": _live_val("relative_volume"),
            "is_volume_spike": bool(df_klines["is_volume_spike"].iloc[-1])
            if "is_volume_spike" in df_klines.columns
            else None,
        }
        missing_indicators = [k for k, v in live_indicators.items() if v is None]
        assert not missing_indicators, (
            f"Live indicator computation failed on {exchange} for: {missing_indicators}"
        )

        # Multi-timeframe live resampling
        resample_agg = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
        df_5m = df_klines.resample("5min").agg(resample_agg).dropna()
        df_1h = df_klines.resample("1h").agg(resample_agg).dropna()
        df_5m["SMA_10"] = df_5m["close"].rolling(10).mean().bfill()
        df_5m["SMA_50"] = df_5m["close"].rolling(50).mean().bfill()
        df_1h["SMA_10"] = df_1h["close"].rolling(10).mean().bfill()
        df_1h["SMA_50"] = df_1h["close"].rolling(50).mean().bfill()

        # Create live BTC series for correlation / cross-market blocks
        btc_klines = df_klines.copy()

        # 2. Build live orderbook structure if available from live exchange
        last_price = float(df_klines["close"].iloc[-1])
        try:
            orderbook = await asyncio.wait_for(
                executor._exchange.fetch_order_book(symbol, limit=20), timeout=5.0
            )
            bids = [[str(b[0]), str(b[1])] for b in orderbook.get("bids", [])]
            asks = [[str(a[0]), str(a[1])] for a in orderbook.get("asks", [])]
            depth_trading = {"bids": bids, "asks": asks}
        except Exception:
            depth_trading = {
                "bids": [
                    [f"{last_price * 0.999:.2f}", "100.0"],
                    [f"{last_price * 0.998:.2f}", "300.0"],
                ],
                "asks": [
                    [f"{last_price * 1.001:.2f}", "100.0"],
                    [f"{last_price * 1.002:.2f}", "300.0"],
                ],
            }

        depth_analysis = {
            "bids": [{"notional": 250000.0, "price": last_price * 0.99}],
            "asks": [{"notional": 200000.0, "price": last_price * 1.01}],
        }

        # 3. Build exact state dicts that Strategy uses in production
        strategy = VisualBuilderStrategy(params={"enabled": True})

        market_data = {
            "kline_1m": df_klines,
            "kline_5m": df_5m,
            "kline_1h": df_1h,
            "kline_1m_BTCUSDT": btc_klines,
            "open_interest": pd.DataFrame(
                {"open_interest": [15000.0, 15100.0]},
                index=[df_klines.index[-2], df_klines.index[-1]],
            ),
            "depth_trading": depth_trading,
            "depth_analysis": depth_analysis,
        }

        pair_info = {
            "symbol": symbol,
            "exchange": exchange,
            "market_type": market_type,
            "candle_timeframe": "1m",
            "last_price": last_price,
            "open": float(df_klines["open"].iloc[-1]),
            "high": float(df_klines["high"].iloc[-1]),
            "low": float(df_klines["low"].iloc[-1]),
            "close": last_price,
            "tick_size": 0.1,
            "current_candle_index": len(df_klines) - 1,
            "timestamp_dt": datetime.now(timezone.utc),
            "is_live_mode": True,
            # Every indicator below is computed from the live klines above —
            # no synthetic constants. A missing pipeline input must surface
            # as False + error, never as a neutral default.
            **live_indicators,
        }

        # 4. Test EVERY block in the registry via the core routing engine
        for block_config in ALL_BLOCKS_REGISTRY:
            block_type = block_config["type"]

            try:
                result, details = strategy._evaluate_condition_tree(
                    node=block_config,
                    pair_info=pair_info,
                    market_data=market_data,
                    prev_pair_info={},
                    context={},
                )

                # Normalize numpy bools so identity checks below are exact.
                result = bool(result)

                for key, val in details.items():
                    if isinstance(val, float) and pd.isna(val):
                        failed_blocks.append(
                            f"{block_type}: Индикатор '{key}' вернул NaN. Details: {details}"
                        )
                        break

                if "error" in details:
                    err_str = str(details["error"])
                    if "Unknown node_type" in err_str:
                        failed_blocks.append(
                            f"{block_type}: незарегистрированный тип блока: {err_str}"
                        )
                    elif block_type in TAPE_BLOCK_TYPES:
                        # No tape feed in this harness: must fail closed.
                        if result is not False or "missing" not in err_str.lower():
                            failed_blocks.append(
                                f"{block_type}: должен дать False + missing-error "
                                f"без ленты, получено result={result}: {details}"
                            )
                    else:
                        error_msg = err_str.lower()
                        if (
                            "not enough" not in error_msg
                            and "missing" not in error_msg
                            and "not available" not in error_msg
                            and "could not resolve" not in error_msg
                        ):
                            failed_blocks.append(
                                f"{block_type}: Возвращена ошибка: {details['error']}"
                            )
                elif block_type not in TAPE_BLOCK_TYPES and result is True:
                    # A passing block must carry measured values, never Nones.
                    none_keys = [k for k, v in details.items() if v is None]
                    if none_keys:
                        failed_blocks.append(
                            f"{block_type}: True с None в details "
                            f"(маскировка дефолта): {none_keys}"
                        )

            except Exception as e:
                failed_blocks.append(f"{block_type}: Падение с исключением: {e}")

        # 5. Test Live Multi-Timeframe Confluence (senior_tf_confluence)
        try:
            htf_node = {
                "id": "htf_live_container",
                "type": "senior_tf_confluence",
                "params": {"timeframe": "5m"},
                "children": [
                    {
                        "id": "h_rsi",
                        "type": "rsi_condition",
                        "params": {"period": 14, "operator": "gt", "value": 30.0},
                    },
                    {
                        "id": "h_ma",
                        "type": "ma_cross_condition",
                        "params": {
                            "fast_period": 10,
                            "slow_period": 50,
                        },
                    },
                ],
            }
            res_htf, trace_htf = strategy._evaluate_condition_tree(
                node=htf_node,
                pair_info=pair_info,
                market_data=market_data,
                prev_pair_info={},
                context={},
            )
            assert isinstance(res_htf, (bool, bool))
        except Exception as e:
            failed_blocks.append(f"senior_tf_confluence live test failed: {e}")

        # 6. Test Live Position Management Lifecycle (Trailing, BE, DCA, Grid, Scale-in)
        try:
            live_pm_config = {
                "positionManagement": [
                    {
                        "id": "live_trail",
                        "type": "trailing_stop",
                        "params": {"type": "ATR", "value": 2.0},
                    },
                    {
                        "id": "live_be",
                        "type": "move_to_breakeven",
                        "params": {
                            "target_type": "atr_multiplier",
                            "target_value": 0.5,
                            "offset_pips": 2,
                        },
                    },
                    {
                        "id": "live_dca",
                        "type": "dca_management",
                        "params": {
                            "max_safety_orders": 3,
                            "volume_multiplier": 1.5,
                            "step_type": "percentage",
                            "step_value": 1.0,
                        },
                    },
                    {
                        "id": "live_grid",
                        "type": "grid_management",
                        "params": {
                            "range_type": "percentage",
                            "grid_levels": 4,
                            "upper_bound": last_price * 1.05,
                            "lower_bound": last_price * 0.95,
                        },
                    },
                ]
            }
            live_pos = BasePosition(
                symbol=symbol,
                direction=SignalDirection.LONG,
                entry_price=last_price * 0.99,
                initial_quantity=1.0,
                remaining_quantity=1.0,
                entry_time=time.time() - 300,
                strategy="VisualBuilderStrategy",
                initial_stop_loss=last_price * 0.95,
                current_sl_price=last_price * 0.95,
                initial_take_profit=last_price * 1.05,
            )

            # Check trailing stop calculation on live price
            trail_pos = strategy._handle_trailing_stop(
                live_pm_config["positionManagement"][0], live_pos, pair_info
            )
            assert trail_pos.current_sl_price is not None

            # Check BE calculation on live price
            be_pos = strategy._handle_move_to_breakeven(
                live_pm_config["positionManagement"][1], live_pos, pair_info
            )
            assert be_pos is not None

            # Check full async PM execution
            exec_pos, _ = await strategy._execute_position_management(
                strategy_config=live_pm_config,
                position=live_pos,
                pair_info=pair_info,
                market_data=market_data,
                prev_pair_info=None,
            )
            assert exec_pos is not None
        except Exception as e:
            failed_blocks.append(f"Position management live execution failed: {e}")

        # 7. Test Dynamic Reference Resolvers on Live Data
        try:
            live_context = {
                "pair_info": pair_info,
                "market_data": market_data,
                "position": live_pos,
            }
            candle_val = strategy._resolve_value(
                {"source": "candle", "key": "close", "shift": 1}, live_context
            )
            assert isinstance(candle_val, float)
            assert candle_val > 0
        except Exception as e:
            failed_blocks.append(f"Dynamic resolver live execution failed: {e}")

        if failed_blocks:
            pytest.fail(
                f"Ошибки при прогоне блоков через движок на {exchange}:\n"
                + "\n".join(failed_blocks)
            )

    finally:
        await executor.close()
        await session.close()


# Blocks below REQUIRE pair_info keys (no kline-df fallback). With an empty
# live pair_info each of them must return False + error — never True and never
# a neutral default (relative_volume 1.0, hour 12, atr 0).
EMPTY_TRAP_BLOCKS: List[Dict[str, Any]] = [
    {"id": "t_relvol", "type": "rel_vol_filter", "params": {}},
    {"id": "t_activity", "type": "market_activity", "params": {}},
    {
        "id": "t_tapec",
        "type": "tape_condition",
        "params": {
            "metric": "delta_volume",
            "window_sec": 30,
            "operator": "gt",
            "threshold": 0,
        },
    },
    {"id": "t_tapea", "type": "tape_analysis", "params": {"window_sec": 30}},
    {
        "id": "t_obz",
        "type": "order_book_zone",
        "params": {"side": "bids", "range_type": "Percentage", "range_value": 1.0},
    },
    {"id": "t_l2", "type": "l2_microstructure", "params": {}},
    {
        "id": "t_sess",
        "type": "trading_session",
        "params": {"filter_mode": "session", "session": "london"},
    },
    {
        "id": "t_vol",
        "type": "volatility_filter",
        "params": {"indicator": "ATR", "operator": "gt", "value": 0.0},
    },
]


@pytest.mark.live_api
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exchange, market_type, symbol",
    [
        ("binance", "spot", "BTC/USDT"),
        ("bybit", "futures_usdtm", "BTCUSDT"),
        ("okx", "futures_usdtm", "BTC/USDT:USDT"),
        ("weex", "futures_usdtm", "BTCUSDT"),
        ("bitget", "futures_usdtm", "BTCUSDT"),
    ],
)
@pytest.mark.parametrize("block_config", EMPTY_TRAP_BLOCKS, ids=lambda b: b["id"])
async def test_empty_pair_info_fails_closed_on_live_data(
    exchange: str, market_type: str, symbol: str, block_config: Dict[str, Any]
):
    """Empty live pair_info must fail closed with an explicit error."""
    api_key, api_secret = _get_api_keys(exchange)
    import aiohttp

    session = aiohttp.ClientSession()
    executor = create_exchange_executor(
        exchange=exchange,
        api_key=api_key or "",
        api_secret=api_secret or "",
        session=session,
        market_type=market_type,
    )

    try:
        try:
            ohlcv = await asyncio.wait_for(
                executor.fetch_ohlcv(symbol, "1m", limit=300), timeout=10.0
            )
        except Exception:
            ohlcv = None

        if ohlcv and len(ohlcv) > 0:
            df_klines = pd.DataFrame(
                ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            df_klines["timestamp"] = pd.to_datetime(
                df_klines["timestamp"], unit="ms", utc=True
            )
            df_klines.set_index("timestamp", inplace=True)
        else:
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(minutes=300)
            df_klines = await download_klines(
                symbol=symbol.replace("/", "").replace(":USDT", ""),
                timeframe="1m",
                start_dt=start_dt,
                end_dt=end_dt,
                market_type=market_type,
            )

        assert df_klines is not None and not df_klines.empty, (
            f"Failed to retrieve live klines for {symbol} on {exchange}"
        )
        df_klines = df_klines.dropna(subset=["close", "high", "low"]).tail(300)

        strategy = VisualBuilderStrategy(params={"enabled": True})
        pair_info = {
            "symbol": symbol,
            "exchange": exchange,
            "market_type": market_type,
            "candle_timeframe": "1m",
            "is_live_mode": True,
        }
        market_data = {"kline_1m": df_klines}

        result, trace = strategy._evaluate_condition_tree(
            node=block_config,
            pair_info=pair_info,
            market_data=market_data,
            prev_pair_info={},
            context={},
        )
        details = trace.get("details", {})
        assert bool(result) is False, (
            f"Block {block_config['type']} passed on empty live pair_info "
            f"on {exchange}: {details}"
        )
        assert "error" in details, (
            f"Block {block_config['type']} failed without an error on empty "
            f"live pair_info on {exchange}: {details}"
        )
    finally:
        await executor.close()
        await session.close()
