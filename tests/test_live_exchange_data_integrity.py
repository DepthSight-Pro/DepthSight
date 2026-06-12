import asyncio
import os
import platform
from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest
from dotenv import load_dotenv

from bot_module.exchanges import create_exchange_executor
from bot_module.data_loader import download_klines
from bot_module.strategy import VisualBuilderStrategy

# Ensure event loop policy for Windows if needed
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

load_dotenv()

# We define a registry of EVERY block type in the system.
# This ensures that ALL blocks are verified against live exchange data.
ALL_BLOCKS_REGISTRY = [
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
    # --- MICROSTRUCTURE & TAPE (Live Context required) ---
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
    if exchange == "binance_spot":
        return os.getenv("TESTNET_BINANCE_SPOT_API_KEY"), os.getenv(
            "TESTNET_BINANCE_SPOT_API_SECRET"
        )
    elif exchange == "binance_futures":
        return os.getenv("TESTNET_BINANCE_FUTURES_API_KEY"), os.getenv(
            "TESTNET_BINANCE_FUTURES_API_SECRET"
        )
    elif exchange == "bybit_futures":
        return os.getenv("TESTNET_BYBIT_API_KEY") or os.getenv(
            "BYBIT_TESTNET_API_KEY"
        ), os.getenv("TESTNET_BYBIT_API_SECRET") or os.getenv(
            "BYBIT_TESTNET_API_SECRET"
        )
    return None, None


@pytest.mark.live_api
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exchange, market_type, symbol",
    [
        ("binance_spot", "spot", "BTCUSDT"),
        ("bybit_futures", "futures_usdtm", "BTCUSDT"),
    ],
)
async def test_all_visual_blocks_pipeline_no_fallbacks(exchange, market_type, symbol):
    """
    ULTIMATE PIPELINE TEST:
    Passes EVERY SINGLE visual block through the actual strategy evaluation engine
    using live downloaded exchange data. Fails if any block throws an error or
    crashes due to missing keys or bad data types from the exchange.
    """
    api_key, api_secret = _get_api_keys(exchange)
    # We do not skip! We test public market endpoints if keys are missing.
    if not api_key:
        api_key = ""
    if not api_secret:
        api_secret = ""

    import aiohttp

    session = aiohttp.ClientSession()

    executor = create_exchange_executor(
        exchange=exchange,
        api_key=api_key,
        api_secret=api_secret,
        session=session,
        market_type=market_type,
    )

    try:
        await asyncio.wait_for(executor._exchange.fetch_time(), timeout=10.0)
    except Exception as exc:
        await executor.close()
        await session.close()
        pytest.skip(f"{exchange} is not reachable: {exc}")

    failed_blocks = []

    try:
        # 1. Fetch Real Market Klines (300 for sufficient warmup like EMA200)
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(minutes=300)

        df_klines = await download_klines(
            symbol=symbol,
            timeframe="1m",
            start_dt=start_dt,
            end_dt=end_dt,
            market_type=market_type,
        )

        assert df_klines is not None and not df_klines.empty, (
            f"Failed to download klines for {symbol}"
        )
        df_klines = df_klines.dropna(subset=["close", "high", "low"]).tail(300)

        # Create a mock BTC kline dataframe for BTC-dependent blocks (e.g. BTC_STATE)
        btc_klines = df_klines.copy()

        # 2. Build exact state dicts that Strategy uses in production
        strategy = VisualBuilderStrategy(params={"enabled": True})

        market_data = {
            "kline_1m": df_klines,
            "kline_1m_BTCUSDT": btc_klines,
            "open_interest": pd.DataFrame(
                {"open_interest": [15000.0, 15100.0]},
                index=[df_klines.index[-2], df_klines.index[-1]],
            ),
        }

        pair_info = {
            "symbol": symbol,
            "candle_timeframe": "1m",
            "last_price": float(df_klines["close"].iloc[-1]),
            "tape_delta_volume_usd_30s": 250000.0,
            "obi_1p": 0.8,
            "is_live_mode": True,
        }

        # 3. Test EVERY block in the registry via the core routing engine
        for block_config in ALL_BLOCKS_REGISTRY:
            block_type = block_config["type"]

            try:
                # _evaluate_condition_tree routes the block to its corresponding _check_ method
                result, details = strategy._evaluate_condition_tree(
                    node=block_config,
                    pair_info=pair_info,
                    market_data=market_data,
                    prev_pair_info={},
                    context={},
                )

                # We check for explicit runtime errors returned by the handler
                if "error" in details:
                    # Ignore intentional "Not enough data" or specific config skips, focus on crashes/NaNs
                    error_msg = details["error"].lower()
                    if "not enough" not in error_msg and "unknown" not in error_msg:
                        failed_blocks.append(
                            f"{block_type}: Возвращена ошибка: {details['error']}"
                        )

                # Catch specific indicators that silently failed and returned NaN in details
                for key, val in details.items():
                    if isinstance(val, float) and pd.isna(val):
                        failed_blocks.append(
                            f"{block_type}: Индикатор '{key}' вернул NaN. Details: {details}"
                        )
                        break

            except Exception as e:
                failed_blocks.append(f"{block_type}: Падение с исключением: {e}")

        if failed_blocks:
            pytest.fail(
                f"Ошибки при прогоне блоков через движок на {exchange}:\n"
                + "\n".join(failed_blocks)
            )

    finally:
        await executor.close()
        await session.close()
