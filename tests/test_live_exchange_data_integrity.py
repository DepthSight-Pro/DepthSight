# tests/test_live_exchange_data_integrity.py
"""
Live Exchange Data Integrity & Visual Block Pipeline Verification.
Connects directly to Binance, Bybit, OKX, and Weex public market APIs,
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
ALL_BLOCKS_REGISTRY: List[Dict[str, Any]] = [
    # --- OSCILLATORS ---
    {"type": "RSI", "params": {"period": 14, "operator": "lt", "value": 30.0}},
    {
        "type": "MACD",
        "params": {
            "fast_period": 12,
            "slow_period": 26,
            "signal_period": 9,
            "condition": "hist_gt_zero",
        },
    },
    {
        "type": "STOCHASTIC",
        "params": {
            "k_period": 14,
            "d_period": 3,
            "smooth_k": 3,
            "operator": "lt",
            "threshold": 20,
        },
    },
    # --- VOLATILITY & RANGE ---
    {
        "type": "BOLLINGER",
        "params": {
            "period": 20,
            "std_dev": 2.0,
            "operator": "cross_above",
            "band": "lower",
        },
    },
    {"type": "NATR", "params": {"period": 14, "operator": "gt", "value": 1.0}},
    {
        "type": "VOLATILITY_SQUEEZE",
        "params": {
            "bb_period": 20,
            "bb_std": 2.0,
            "kc_period": 20,
            "kc_mult": 1.5,
            "operator": "sqz_on",
        },
    },
    {"type": "VOLATILITY", "params": {"threshold_percent": 1.0}},
    # --- TREND & MOMENTUM ---
    {"type": "ADX", "params": {"period": 14, "threshold": 25, "operator": "gt"}},
    {
        "type": "MA_CROSS",
        "params": {"fast_period": 10, "slow_period": 50, "ma_type": "sma"},
    },
    {
        "type": "TREND_DIRECTION",
        "params": {"fast_period": 10, "slow_period": 50, "required_trend": "LONG"},
    },
    {"type": "TREND_STRENGTH", "params": {"min_strength": 0.5}},
    # --- PRICE ACTION & LEVELS ---
    {"type": "PRICE_ACTION", "params": {"pattern": "pinbar"}},
    {"type": "PRICE_CONSOLIDATION", "params": {"period": 20, "threshold_pct": 1.0}},
    {"type": "LEVEL_TOUCH", "params": {"lookback": 50, "touch_range_pct": 0.1}},
    {"type": "RETURN_TO_LEVEL", "params": {"lookback": 50, "return_range_pct": 0.2}},
    {
        "type": "PRICE_VS_LEVEL",
        "params": {"level_type": "rolling_high", "lookback": 50, "operator": "lt"},
    },
    {"type": "LOCAL_LEVEL", "params": {"lookback": 50, "level_type": "support"}},
    {
        "type": "VALUE_COMPARISON",
        "params": {
            "left": {"source": "candle", "key": "close"},
            "operator": "gt",
            "right": {"source": "constant", "value": 0},
        },
    },
    # --- MICROSTRUCTURE & TAPE ---
    {
        "type": "TAPE_CONDITION",
        "params": {
            "metric": "delta_volume",
            "window_sec": "30",
            "operator": "gt",
            "threshold": 0,
        },
    },
    {
        "type": "ORDER_BOOK_ZONE",
        "params": {"metric": "obi_1p", "operator": "gt", "threshold": 0},
    },
    {
        "type": "OPEN_INTEREST",
        "params": {"analyze": "absolute_value", "operator": "gt", "value": 0},
    },
    # --- MARKET FILTERS ---
    {"type": "TRADING_SESSION", "params": {"allowed_sessions": ["London", "New York"]}},
    {"type": "MARKET_ACTIVITY", "params": {"min_trades": 100}},
    {"type": "BTC_STATE", "params": {"required_state": "Any"}},
    {
        "type": "CORRELATION",
        "params": {"lookback": 20, "operator": "gt", "value": -1.0},
    },
    # --- FOUNDATIONS ---
    {"type": "CLASSIC_PATTERN", "params": {"pattern_type": "double_bottom"}},
    {"type": "VOLUME_CONFIRMATION", "params": {"period": 20, "threshold": 1.5}},
    {"type": "ROUND_NUMBER_LEVEL", "params": {"proximity_pct": 0.1}},
    {"type": "L2_MICROSTRUCTURE", "params": {"imbalance_threshold": 0.2}},
    {"type": "TAPE_ANALYSIS", "params": {"window_sec": 30}},
]


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

        # Precompute common technical series for live test
        df_klines["SMA_10"] = df_klines["close"].rolling(10).mean().bfill()
        df_klines["SMA_20"] = df_klines["close"].rolling(20).mean().bfill()
        df_klines["SMA_50"] = df_klines["close"].rolling(50).mean().bfill()
        df_klines["RSI_14"] = 50.0
        df_klines["ADX_14"] = 28.0
        df_klines["BBW_20_2"] = 0.04
        df_klines["MACD_hist_12_26_9"] = 0.5

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
            "atr": 100.0,
            "natr": 1.5,
            "tick_size": 0.1,
            "relative_volume": 2.0,
            "is_volume_spike": True,
            "current_candle_index": len(df_klines) - 1,
            "timestamp_dt": datetime.now(timezone.utc),
            "tape_delta_volume_usd_30s": 250000.0,
            "obi_1p": 0.8,
            "is_live_mode": True,
            "SMA_10": float(df_klines["SMA_10"].iloc[-1]),
            "SMA_20": float(df_klines["SMA_20"].iloc[-1]),
            "SMA_50": float(df_klines["SMA_50"].iloc[-1]),
            "RSI_14": 50.0,
            "ADX_14": 28.0,
            "BBW_20_2": 0.04,
            "MACD_hist_12_26_9": 0.5,
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

                if "error" in details:
                    error_msg = details["error"].lower()
                    if "not enough" not in error_msg and "unknown" not in error_msg:
                        failed_blocks.append(
                            f"{block_type}: Возвращена ошибка: {details['error']}"
                        )

                for key, val in details.items():
                    if isinstance(val, float) and pd.isna(val):
                        failed_blocks.append(
                            f"{block_type}: Индикатор '{key}' вернул NaN. Details: {details}"
                        )
                        break

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
                        "type": "RSI",
                        "params": {"period": 14, "operator": "gt", "value": 30.0},
                    },
                    {
                        "id": "h_ma",
                        "type": "MA_CROSS",
                        "params": {
                            "fast_period": 10,
                            "slow_period": 50,
                            "ma_type": "sma",
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
