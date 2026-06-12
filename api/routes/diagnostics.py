import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

import os
import json
import aiohttp
import pandas as pd
import pandas_ta as ta
import api.depthsight_api as depthsight_api
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from pathlib import Path
from sqlalchemy import text

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..redis_client import get_redis_client
from ..session_manager import HttpSessDep
from bot_module.strategy import (
    find_trend_zones,
    find_consolidation_zones,
    find_squeeze_zones,
    find_level_touch_visuals,
    find_price_action_visuals,
    find_significant_levels,
    find_local_levels,
    _check_foundation_classic_pattern,
    _check_foundation_volume_confirmation,
    _generate_round_levels,
)


class ModuleProxy:
    def __init__(self, getattr_fn):
        self._getattr_fn = getattr_fn

    def __getattr__(self, name):
        return getattr(self._getattr_fn(), name)


data_loader = ModuleProxy(lambda: depthsight_api.data_loader)

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
LOCAL_DATA_STORAGE_PATH = PROJECT_ROOT / "data_storage"


def _load_app_version() -> str:
    try:
        version_file = PROJECT_ROOT / "VERSION"
        if version_file.exists():
            with open(version_file, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return "1.0.1"


APP_VERSION = os.getenv("APP_VERSION", _load_app_version())

logger = logging.getLogger(__name__)

diagnostics_router = APIRouter(
    prefix="/api/v1",
    tags=["Diagnostics"],
)


@diagnostics_router.get(
    "/status", response_model=schemas.ApiResponseData, summary="Get system status"
)
async def get_system_status_endpoint(
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Checks and returns real state of key system components.
    """
    components = []

    # 1. Database connection check
    try:
        await db.execute(text("SELECT 1"))
        components.append({"name": "database_connection", "status": "ok"})
    except Exception as e:
        logger.error(f"System status check: Database connection failed: {e}")
        components.append({"name": "database_connection", "status": "error"})

    # 2. Redis connection check (also Celery broker)
    try:
        await redis_client.ping()
        components.append({"name": "task_queue_connection", "status": "ok"})
    except Exception as e:
        logger.error(f"System status check: Redis/Task Queue connection failed: {e}")
        components.append({"name": "task_queue_connection", "status": "error"})

    # 3. WebSocket connection status (this data should be published by the bot itself)
    # Keep stubs for now, but they are now separated from real checks.
    # In the future, the bot will be able to write its status to Redis, and API will read it.
    components.append({"name": "binance_spot_ws", "status": "connected"})
    components.append({"name": "binance_futures_ws", "status": "connected"})

    dynamic_system_state = {
        "status": "ok"
        if all(c["status"] in ["ok", "connected"] for c in components)
        else "error",
        "version": APP_VERSION,  # Dynamic version
        "timestamp_utc": datetime.now(timezone.utc),
        "components": components,
    }

    return {"data": schemas.SystemStatus(**dynamic_system_state)}


@diagnostics_router.get("/proxy/binance/klines")
async def proxy_binance_klines(
    symbol: str,
    interval: str,
    startTime: Optional[int] = None,
    endTime: Optional[int] = None,
    limit: int = 500,
    http_session: aiohttp.ClientSession = HttpSessDep,
):
    """
    Proxy to fetch klines data from Binance API.
    Tries futures API first, falls back to spot on error.
    """
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    if startTime:
        params["startTime"] = startTime
    if endTime:
        params["endTime"] = endTime

    # Try futures API first (most trades are on futures)
    binance_futures_url = "https://fapi.binance.com/fapi/v1/klines"
    binance_spot_url = "https://api.binance.com/api/v3/klines"

    try:
        async with http_session.get(binance_futures_url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return data
            else:
                # Futures API failed, try spot
                logger.debug(f"Futures API failed for {symbol}, trying spot API...")
    except aiohttp.ClientError as exc:
        logger.debug(
            f"Futures API connection error for {symbol}: {exc}, trying spot API..."
        )

    # Fallback to spot API
    try:
        async with http_session.get(binance_spot_url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return data
            else:
                error_text = await response.text()
                raise HTTPException(
                    status_code=response.status,
                    detail=f"Binance API error for {symbol}: {error_text}",
                )
    except aiohttp.ClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect to Binance API: {exc}",
        )


@diagnostics_router.get("/proxy/binance/exchange-info")
async def proxy_binance_exchange_info(
    symbol: Optional[str] = None,
    http_session: aiohttp.ClientSession = HttpSessDep,
):
    """
    Proxy to fetch exchange info from Binance API.
    Tries futures API first, falls back to spot on error.
    """
    params = {}
    if symbol:
        params["symbol"] = symbol.upper()

    # Try futures API first
    binance_futures_url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    binance_spot_url = "https://api.binance.com/api/v3/exchangeInfo"

    try:
        async with http_session.get(binance_futures_url, params=params) as response:
            if response.status == 200:
                return await response.json()
    except Exception:
        pass

    try:
        async with http_session.get(binance_spot_url, params=params) as response:
            if response.status == 200:
                return await response.json()
            else:
                error_text = await response.text()
                raise HTTPException(
                    status_code=response.status,
                    detail=f"Binance API error: {error_text}",
                )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect to Binance API: {exc}",
        )


@diagnostics_router.get("/proxy/bybit/exchange-info")
async def proxy_bybit_exchange_info(
    symbol: Optional[str] = None,
    category: str = "linear",
    http_session: aiohttp.ClientSession = HttpSessDep,
):
    """
    Proxy to fetch instruments info from Bybit V5 API.
    """
    params = {"category": category}
    if symbol:
        params["symbol"] = symbol.upper()

    url = "https://api.bybit.com/v5/market/instruments-info"
    try:
        async with http_session.get(url, params=params) as response:
            if response.status == 200:
                return await response.json()
            else:
                error_text = await response.text()
                raise HTTPException(
                    status_code=response.status,
                    detail=f"Bybit API error: {error_text}",
                )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect to Bybit API: {exc}",
        )


@diagnostics_router.get("/proxy/bybit/klines")
async def proxy_bybit_klines(
    symbol: str,
    interval: str,
    category: str = "linear",
    start: Optional[int] = None,
    end: Optional[int] = None,
    limit: int = 1000,
    http_session: aiohttp.ClientSession = HttpSessDep,
):
    """
    Proxy to fetch klines data from Bybit V5 API.
    """
    params = {
        "category": category,
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": limit,
    }
    if start:
        params["start"] = start
    if end:
        params["end"] = end

    url = "https://api.bybit.com/v5/market/kline"
    try:
        async with http_session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return data
            else:
                error_text = await response.text()
                raise HTTPException(
                    status_code=response.status,
                    detail=f"Bybit API error for {symbol}: {error_text}",
                )
    except aiohttp.ClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect to Bybit API: {exc}",
        )


@diagnostics_router.get(
    "/diagnostics/preview-foundation",
    response_model=schemas.ApiResponseData[schemas.FoundationPreviewResponse],
    summary="Preview foundation visualizations on a chart",
)
async def preview_foundation(
    symbol: str,
    end_date: str,
    timeframe: str,
    foundations: str = Query(
        ..., description="Comma-separated list of foundation types"
    ),
    params: str = Query(
        "{}", description="JSON string with parameters for all foundations"
    ),
    start_date: Optional[str] = Query(
        None, description="Optional start date (ISO format)"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Generates chart data and visualizations for selected foundations
    over the specified period or a default 24-hour period.
    """
    try:
        # Set time interval
        end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        if start_date:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        else:
            # Increase window to 3 days for more context
            start_dt = end_dt - timedelta(days=3)

        logger.info(
            f"Foundation preview for user '{current_user.username}': Period={start_dt.isoformat()} to {end_dt.isoformat()}"
        )

        foundation_params = json.loads(params)
        foundation_list = [f.strip() for f in foundations.split(",") if f.strip()]
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid date, params, or foundations format: {e}"
        )

    # --- STEP 1: Load data with margin ---
    required_timeframes = {timeframe, "1h", "4h", "1d"}

    # Collect additional timeframes that may be required for individual blocks
    for f_type in foundation_list:
        f_p = foundation_params.get(f_type, {})
        if isinstance(f_p, dict) and f_p.get("timeframe"):
            tf_val = str(f_p.get("timeframe"))
            if tf_val and tf_val != "auto":
                required_timeframes.add(tf_val)
    margin = timedelta(days=90)  # Margin for indicator calculation
    market_data_full_history = {}

    for tf in required_timeframes:
        try:
            df = await data_loader.download_klines(
                symbol=symbol,
                timeframe=tf,
                start_dt=start_dt - margin,
                end_dt=end_dt,
                market_type="futures_usdtm",
            )
            if df is not None and not df.empty:
                market_data_full_history[f"kline_{tf}"] = df
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to load kline data for {tf}: {e}"
            )

    main_tf_key = f"kline_{timeframe}"
    if main_tf_key not in market_data_full_history:
        raise HTTPException(
            status_code=404,
            detail=f"Main timeframe data '{timeframe}' not found for symbol '{symbol}'.",
        )

    main_df_full_history = market_data_full_history[main_tf_key]

    # --- STEP 2: Pre-calculate indicators on full DataFrame ---
    # This guarantees no NaN at start of visible section
    main_df_with_indicators = main_df_full_history.copy()

    # Calculate SMA and RSI for trend zones
    trend_params = foundation_params.get("trend_direction", {})
    sma_fast = trend_params.get("sma_fast_period", 10)
    sma_slow = trend_params.get("sma_slow_period", 50)
    rsi_p = trend_params.get("rsi_period", 14)

    if sma_fast > 0:
        main_df_with_indicators[f"SMA_{sma_fast}"] = (
            main_df_with_indicators["close"].rolling(window=sma_fast).mean()
        )
    if sma_slow > 0:
        main_df_with_indicators[f"SMA_{sma_slow}"] = (
            main_df_with_indicators["close"].rolling(window=sma_slow).mean()
        )
    if rsi_p > 0:
        delta = main_df_with_indicators["close"].diff()
        gain = (delta.where(delta > 0, 0)).ewm(com=rsi_p - 1, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(com=rsi_p - 1, adjust=False).mean()
        rs = gain / loss
        main_df_with_indicators[f"RSI_{rsi_p}"] = 100 - (100 / (1 + rs))

    # --- STEP 3: Slice display range ---
    main_df_display = main_df_with_indicators[
        (main_df_with_indicators.index >= start_dt)
        & (main_df_with_indicators.index <= end_dt)
    ].copy()

    if main_df_display.empty:
        raise HTTPException(
            status_code=404,
            detail="No kline data available for the selected 24-hour period.",
        )

    # --- STEP 4: Calculate visualizations (zones, levels, sub-charts) ---
    visualizations = {"levels": [], "markers": [], "zones": [], "subcharts": {}}

    # Calculate zones
    if "trend_direction" in foundation_list:
        trend_params = foundation_params.get("trend_direction", {}).copy()
        if not trend_params.get("timeframe"):
            trend_params["timeframe"] = timeframe
        visualizations["zones"].extend(
            find_trend_zones(
                market_data_full_history, trend_params, main_df_with_indicators
            )
        )

    if "price_consolidation" in foundation_list:
        cons_params = foundation_params.get("price_consolidation", {}).copy()
        # If timeframe is not specified or 'auto' - use chart timeframe
        if not cons_params.get("timeframe") or cons_params.get("timeframe") == "auto":
            cons_params["timeframe"] = timeframe
        visualizations["zones"].extend(
            find_consolidation_zones(
                market_data_full_history, cons_params, main_df_with_indicators
            )
        )

    if "volatility_squeeze" in foundation_list:
        v_params = foundation_params.get("volatility_squeeze", {}).copy()
        if not v_params.get("timeframe") or v_params.get("timeframe") == "auto":
            v_params["timeframe"] = timeframe
        visualizations["zones"].extend(
            find_squeeze_zones(
                market_data_full_history, v_params, main_df_with_indicators
            )
        )

    if "level_touch_analyzer" in foundation_list:
        lt_params = foundation_params.get("level_touch_analyzer", {}).copy()
        res = find_level_touch_visuals(
            market_data_full_history, lt_params, main_df_with_indicators
        )
        visualizations["levels"].extend(res.get("levels", []))
        visualizations["markers"].extend(res.get("markers", []))

    if "price_action_analyzer" in foundation_list:
        pa_params = foundation_params.get("price_action_analyzer", {}).copy()
        visualizations["markers"].extend(
            find_price_action_visuals(
                market_data_full_history, pa_params, main_df_with_indicators
            )
        )

    # Filter zones: keep only those intersecting with visible range
    display_start_ts = int(start_dt.timestamp())
    display_end_ts = int(end_dt.timestamp())
    visualizations["zones"] = [
        z
        for z in visualizations["zones"]
        if not (z["end_time"] < display_start_ts or z["start_time"] > display_end_ts)
    ]

    # Calculate levels (relative to the last visible candle)
    last_timestamp_on_chart = main_df_display.index[-1].to_pydatetime()

    if "significant_level" in foundation_list:
        levels_dict = find_significant_levels(
            market_data_full_history, None, last_timestamp_on_chart
        )
        for level_type, prices in levels_dict.items():
            for price in prices:
                visualizations["levels"].append(
                    {
                        "time": int(start_dt.timestamp()),
                        "price": price,
                        "type": "significant_level",
                        "label": f"SIG_{level_type.upper()}",
                    }
                )

    if "local_level" in foundation_list:
        levels_dict = find_local_levels(
            market_data_full_history,
            foundation_params.get("local_level", {}),
            last_timestamp_on_chart,
        )
        for level_type, prices in levels_dict.items():
            for price in prices:
                visualizations["levels"].append(
                    {
                        "time": int(start_dt.timestamp()),
                        "price": price,
                        "type": "local_level",
                        "label": f"LOCAL_{level_type.upper()}",
                    }
                )

    # --- STEP 5: Iterate over candles ONLY for markers ---

    for timestamp, candle in main_df_display.iterrows():
        # Find index in full DataFrame for correct calculation of rolling windows/patterns
        idx_in_full = main_df_with_indicators.index.get_loc(timestamp)

        # Form pair_info for each candle
        pair_info = {
            **candle.to_dict(),
            "symbol": symbol,
            "candle_timeframe": timeframe,
            "current_candle_index": idx_in_full,
            "timestamp_dt": timestamp,
            "tick_size": 0.01,
        }

        # Check requested markers
        if "classic_pattern" in foundation_list:
            res_pattern = _check_foundation_classic_pattern(
                pair_info,
                main_df_with_indicators,
                foundation_params.get("classic_pattern", {}),
            )
            if res_pattern and isinstance(res_pattern, tuple) and res_pattern[0]:
                result, details = res_pattern
                visualizations["markers"].append(
                    {
                        "time": int(timestamp.timestamp()),
                        "type": "classic_pattern",
                        "text": str(details.get("pattern_checked", "P"))[0].upper(),
                        "position": "aboveBar",
                        "shape": "arrowDown",
                        "color": "#e91e63",
                    }
                )

        if "volume_confirmation" in foundation_list:
            result = _check_foundation_volume_confirmation(
                pair_info,
                market_data_full_history,
                main_df_with_indicators,
                idx_in_full,
            )
            if result:
                visualizations["markers"].append(
                    {
                        "time": int(timestamp.timestamp()),
                        "type": "volume_confirmation",
                        "text": "V",
                        "position": "belowBar",
                        "shape": "circle",
                        "color": "#ff9800",
                    }
                )

        if "tape_acceleration" in foundation_list or "tape_analysis" in foundation_list:
            # FIX: Key mismatch workaround (frontend sends tape_acceleration, strategy might expect tape_analysis)
            params_ta = foundation_params.get(
                "tape_acceleration", {}
            ) or foundation_params.get("tape_analysis", {})

            # 1. Call data provider block (Tape Analysis)
            # Note: real operations require order book/tape access, this is an emulation based on candle volume
            # as full tape history may be unavailable or too large.
            # In the future, a real aggregated tape history should be connected.

            # Emulation: if candle volume > 2x average, consider it an "acceleration"
            current_vol = pair_info.get("volume", 0)
            avg_vol_series = main_df_with_indicators["volume"].rolling(20).mean()
            avg_vol = avg_vol_series.loc[timestamp]

            if current_vol > avg_vol * params_ta.get("multiplier", 2.0):
                visualizations["markers"].append(
                    {
                        "time": int(timestamp.timestamp()),
                        "type": "tape_acceleration",
                        "text": "T",
                        "position": "belowBar",
                        "shape": "arrowUp",
                        "color": "#2196F3",
                    }
                )

    # --- ADDED: Round Levels ---
    if "round_level" in foundation_list:
        # For display, take the price range on the chart
        stats_min_price = main_df_display["low"].min()
        stats_max_price = main_df_display["high"].max()

        # Generate levels relative to the last price, but filter by window range
        # Use standard generation from strategy
        # step_definitions=[] means use default logic (orders of magnitude)
        # Generate levels relative to the last price
        last_price_on_chart = main_df_display["close"].iloc[-1]
        generated_rounds = _generate_round_levels(
            last_price=last_price_on_chart,
            tick_size=0.01,
            step_definitions_config=[],
            max_check_per_step_type=2,
            max_orders_scan_override=2,
        )

        for price in generated_rounds:
            # Show only those that fall within the visible range +/- small offset
            if stats_min_price * 0.95 <= price <= stats_max_price * 1.05:
                # FIX: Explicit int/float casting
                visualizations["levels"].append(
                    {
                        "time": int(start_dt.timestamp()),
                        "price": float(price),
                        "type": "round_level",
                        "label": f"{price}",
                    }
                )

    # --- ADDED: Indicators and filters visualization ---
    # We process both filters and indicators, converting them into visual form

    # 1. Volatility Filter (ATR / BBW)
    if "volatility_filter" in foundation_list:
        v_params = foundation_params.get("volatility_filter", {})
        indicator = v_params.get("indicator", "ATR")

        if indicator == "ATR":
            main_df_with_indicators["visual_atr"] = ta.atr(
                main_df_with_indicators["high"],
                main_df_with_indicators["low"],
                main_df_with_indicators["close"],
                length=14,
            )
            data_points = []
            for t, v in main_df_with_indicators["visual_atr"].dropna().items():
                if start_dt <= t <= end_dt:
                    data_points.append({"time": int(t.timestamp()), "value": float(v)})
            visualizations["subcharts"]["ATR"] = data_points
            # Add threshold as level on sub-chart (frontend logic must support this)
            # Or pass as a separate series
        elif indicator == "BBW":
            bb = ta.bbands(main_df_with_indicators["close"], length=20, std=2)
            if bb is not None and not bb.empty:
                # Dynamic column lookup to avoid KeyError
                bbl_col = next((c for c in bb.columns if c.startswith("BBL")), None)
                bbu_col = next((c for c in bb.columns if c.startswith("BBU")), None)
                bbm_col = next((c for c in bb.columns if c.startswith("BBM")), None)

                if bbl_col and bbu_col and bbm_col:
                    main_df_with_indicators["visual_bbw"] = (
                        bb[bbu_col] - bb[bbl_col]
                    ) / bb[bbm_col]
                    data_points = []
                    for t, v in main_df_with_indicators["visual_bbw"].dropna().items():
                        if start_dt <= t <= end_dt:
                            data_points.append(
                                {"time": int(t.timestamp()), "value": float(v)}
                            )
                    visualizations["subcharts"]["BBW"] = data_points

    # 2. Trend Filter (ADX)
    if "trend_filter" in foundation_list:
        adx_df = ta.adx(
            main_df_with_indicators["high"],
            main_df_with_indicators["low"],
            main_df_with_indicators["close"],
            length=14,
        )
        if adx_df is not None and not adx_df.empty:
            # ADX column usually ADX_14, but let's be safe
            adx_col = next((c for c in adx_df.columns if c.startswith("ADX")), None)
            if adx_col:
                data_points = []
                for t, v in adx_df[adx_col].dropna().items():
                    if start_dt <= t <= end_dt:
                        data_points.append(
                            {"time": int(t.timestamp()), "value": float(v)}
                        )
                visualizations["subcharts"]["ADX"] = data_points

    # 3. NATR Filter
    if "natr_filter" in foundation_list:
        # NATR = (ATR / Close) * 100
        atr = ta.atr(
            main_df_with_indicators["high"],
            main_df_with_indicators["low"],
            main_df_with_indicators["close"],
            length=14,
        )
        if atr is not None:
            main_df_with_indicators["visual_natr"] = (
                atr / main_df_with_indicators["close"]
            ) * 100
            data_points = []
            for t, v in main_df_with_indicators["visual_natr"].dropna().items():
                if start_dt <= t <= end_dt:
                    data_points.append({"time": int(t.timestamp()), "value": float(v)})
            visualizations["subcharts"]["NATR"] = data_points

    # 4. Relative Volume Filter
    if "rel_vol_filter" in foundation_list:
        main_df_with_indicators["visual_rel_vol"] = (
            main_df_with_indicators["volume"]
            / main_df_with_indicators["volume"].rolling(20).mean()
        )
        data_points = []
        for t, v in main_df_with_indicators["visual_rel_vol"].dropna().items():
            if start_dt <= t <= end_dt:
                data_points.append({"time": int(t.timestamp()), "value": float(v)})
        visualizations["subcharts"]["RelVol"] = data_points

    # 5. Bollinger Bands (Overlay)
    if "bollinger_bands_condition" in foundation_list:
        # Even if it is a filter, visualize the bands themselves
        bb = ta.bbands(main_df_with_indicators["close"], length=20, std=2)
        if bb is not None and not bb.empty:
            # For overlay on main chart, we can use subcharts with overlay flag
            # or add lines to the main chart. Frontend FoundationChart currently supports subcharts only.
            # Add Bollinger Bands to subcharts, but teach frontend to draw them over price if name is 'Bollinger Bands'

            # Dynamic lookup
            cols_map = {
                "BBL": next((c for c in bb.columns if c.startswith("BBL")), None),
                "BBM": next((c for c in bb.columns if c.startswith("BBM")), None),
                "BBU": next((c for c in bb.columns if c.startswith("BBU")), None),
            }

            for key, col in cols_map.items():
                if col:
                    data_points = []
                    for t, v in bb[col].dropna().items():
                        if start_dt <= t <= end_dt:
                            data_points.append(
                                {"time": int(t.timestamp()), "value": float(v)}
                            )

                    label = (
                        "BB_Lower"
                        if key == "BBL"
                        else ("BB_Upper" if key == "BBU" else "BB_Middle")
                    )
                    visualizations["subcharts"][label] = data_points

    # 6. MA Crossover Condition (Overlays)
    if "ma_cross_condition" in foundation_list or "ma_crossover" in foundation_list:
        ma_params = foundation_params.get(
            "ma_cross_condition", {}
        ) or foundation_params.get("ma_crossover", {})
        fast_period = int(ma_params.get("fast_period", 9))
        slow_period = int(ma_params.get("slow_period", 21))
        ma_type = ma_params.get("ma_type", "EMA")

        # Calculate Fast MA
        fast_ma = (
            ta.ema(main_df_with_indicators["close"], length=fast_period)
            if ma_type == "EMA"
            else ta.sma(main_df_with_indicators["close"], length=fast_period)
        )
        # Calculate Slow MA
        slow_ma = (
            ta.ema(main_df_with_indicators["close"], length=slow_period)
            if ma_type == "EMA"
            else ta.sma(main_df_with_indicators["close"], length=slow_period)
        )

        if fast_ma is not None:
            data_points = []
            for t, v in fast_ma.dropna().items():
                if start_dt <= t <= end_dt:
                    data_points.append({"time": int(t.timestamp()), "value": float(v)})
            visualizations["subcharts"][f"MA_Fast_{fast_period}"] = data_points

        if slow_ma is not None:
            data_points = []
            for t, v in slow_ma.dropna().items():
                if start_dt <= t <= end_dt:
                    data_points.append({"time": int(t.timestamp()), "value": float(v)})
            visualizations["subcharts"][f"MA_Slow_{slow_period}"] = data_points

    # 7. MACD Condition (Subchart)
    if "macd_condition" in foundation_list:
        macd_params = foundation_params.get("macd_condition", {})
        fast_period = int(macd_params.get("fast", 12))
        slow_period = int(macd_params.get("slow", 26))
        signal_period = int(macd_params.get("signal", 9))

        macd = ta.macd(
            main_df_with_indicators["close"],
            fast=fast_period,
            slow=slow_period,
            signal=signal_period,
        )
        if macd is not None and not macd.empty:
            # Dynamic lookup for MACD, Signal, Hist
            macd_col = next((c for c in macd.columns if c.startswith("MACD_")), None)
            signal_col = next((c for c in macd.columns if c.startswith("MACDs_")), None)
            hist_col = next((c for c in macd.columns if c.startswith("MACDh_")), None)

            if macd_col:
                visualizations["subcharts"]["MACD_Line"] = [
                    {"time": int(t.timestamp()), "value": float(v)}
                    for t, v in macd[macd_col].dropna().items()
                    if start_dt <= t <= end_dt
                ]
            if signal_col:
                visualizations["subcharts"]["MACD_Signal"] = [
                    {"time": int(t.timestamp()), "value": float(v)}
                    for t, v in macd[signal_col].dropna().items()
                    if start_dt <= t <= end_dt
                ]
            if hist_col:
                visualizations["subcharts"]["MACD_Hist"] = [
                    {"time": int(t.timestamp()), "value": float(v)}
                    for t, v in macd[hist_col].dropna().items()
                    if start_dt <= t <= end_dt
                ]

    # 8. Stochastic Condition (Subchart)
    if "stochastic_condition" in foundation_list:
        stoch_params = foundation_params.get("stochastic_condition", {})
        k_period = int(stoch_params.get("k_period", 14))
        d_period = int(stoch_params.get("d_period", 3))
        slowing = int(stoch_params.get("slowing", 3))

        # pandas_ta.stoch returns %K and %D
        stoch = ta.stoch(
            main_df_with_indicators["high"],
            main_df_with_indicators["low"],
            main_df_with_indicators["close"],
            k=k_period,
            d=d_period,
            smooth_k=slowing,
        )

        if stoch is not None and not stoch.empty:
            # Dynamic lookup for %K and %D columns
            k_col = next((c for c in stoch.columns if c.startswith("STOCHk_")), None)
            d_col = next((c for c in stoch.columns if c.startswith("STOCHd_")), None)

            if k_col:
                visualizations["subcharts"]["Stoch_K"] = [
                    {"time": int(t.timestamp()), "value": float(v)}
                    for t, v in stoch[k_col].dropna().items()
                    if start_dt <= t <= end_dt
                ]
            if d_col:
                visualizations["subcharts"]["Stoch_D"] = [
                    {"time": int(t.timestamp()), "value": float(v)}
                    for t, v in stoch[d_col].dropna().items()
                    if start_dt <= t <= end_dt
                ]

    # 9. RSI Condition (Subchart)
    if "rsi_condition" in foundation_list:
        rsi_params = foundation_params.get("rsi_condition", {})
        period = int(rsi_params.get("period", 14))

        rsi = ta.rsi(main_df_with_indicators["close"], length=period)
        if rsi is not None:
            visualizations["subcharts"]["RSI"] = [
                {"time": int(t.timestamp()), "value": float(v)}
                for t, v in rsi.dropna().items()
                if start_dt <= t <= end_dt
            ]

    # --- ADDED: Open Interest ---
    if "open_interest" in foundation_list:
        try:
            # Try to load OI
            # OI is typically available on 5m, 1h, 4h, etc. Use same timeframe or convert
            oi_df = await data_loader.download_open_interest(
                symbol=symbol,
                timeframe=timeframe
                if timeframe in ["5m", "15m", "30m", "1h", "4h"]
                else "1h",
                start_dt=start_dt - margin,
                end_dt=end_dt,
                market_type="futures_usdtm",
            )

            if oi_df is not None and not oi_df.empty:
                # Filter by date
                oi_display = oi_df[(oi_df.index >= start_dt) & (oi_df.index <= end_dt)]

                oi_data = []
                for ts, row in oi_display.iterrows():
                    # FIX: Explicit int/float casting (ts.timestamp() might be float, int() is safer for API)
                    oi_data.append(
                        {
                            "time": int(ts.timestamp()),
                            "value": float(row["open_interest"]),
                        }
                    )

                visualizations["subcharts"]["open_interest"] = oi_data

        except Exception as e:
            logger.warning(f"Failed to load Open Interest for {symbol}: {e}")

    # --- ADDED: Correlation ---
    if "correlation" in foundation_list:
        try:
            # Determine benchmark (BTCUSDT by default, if symbol itself is not BTC)
            benchmark_symbol = "BTCUSDT"
            if symbol.upper() == "BTCUSDT":
                benchmark_symbol = "ETHUSDT"

            # Load benchmark data
            bench_df = await data_loader.download_klines(
                symbol=benchmark_symbol,
                timeframe=timeframe,
                start_dt=start_dt - margin,
                end_dt=end_dt,
            )

            if bench_df is not None and not bench_df.empty:
                # Synchronize indices
                # Use close prices for correlation
                # Align data (inner join by time index)
                combined_df = pd.DataFrame(
                    {
                        "target": main_df_full_history["close"],
                        "benchmark": bench_df["close"],
                    }
                ).dropna()

                corr_params = foundation_params.get("correlation", {})
                lookback = int(corr_params.get("lookback", 50))

                # Calculate rolling correlation
                rolling_corr = (
                    combined_df["target"]
                    .rolling(window=lookback)
                    .corr(combined_df["benchmark"])
                )

                # Slice the required piece
                corr_display = rolling_corr[
                    (rolling_corr.index >= start_dt) & (rolling_corr.index <= end_dt)
                ]

                corr_data = []
                for ts, val in corr_display.items():
                    if not pd.isna(val):
                        # Explicit int/float casting
                        corr_data.append(
                            {"time": int(ts.timestamp()), "value": float(val)}
                        )

                visualizations["subcharts"]["correlation"] = corr_data

        except Exception as e:
            logger.warning(f"Failed to calculate Correlation for {symbol}: {e}")

    # --- STEP 6: Form final response ---
    klines_for_chart = [
        {
            "time": int(ts.timestamp()),
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
        }
        for ts, row in main_df_display.iterrows()
    ]

    response_data = schemas.FoundationPreviewResponse(
        klines=klines_for_chart, visualizations=visualizations
    )

    # Grant 'clairvoyant' achievement
    from ..depthsight_api import grant_achievement

    await grant_achievement(db, current_user.id, "clairvoyant")

    return {"data": response_data}


@diagnostics_router.get(
    "/diagnostics/available-symbols",
    response_model=schemas.ApiResponseData[List[str]],
    summary="Find symbols for which downloaded data exists",
)
async def find_available_symbols(
    q: Optional[str] = Query(None, description="Partial symbol name to search"),
    current_user: models.User = Depends(get_current_user),
):
    """
    Scans the data directory and returns a list of symbols
    for which history folders exist.
    """
    # Now base_path will be absolute and correct, e.g.: /data_storage/binance/futures
    base_path = LOCAL_DATA_STORAGE_PATH / "binance" / "futures"

    if not base_path.is_dir():
        logger.warning(f"Data directory '{base_path}' was not found.")
        return {"data": []}

    found_symbols = []
    try:
        for item in os.scandir(base_path):
            if item.is_dir():
                symbol_name = item.name.upper()
                if q:
                    if symbol_name.startswith(q.upper()):
                        found_symbols.append(symbol_name)
                else:
                    found_symbols.append(symbol_name)

        found_symbols.sort()

        limit = 50 if q else 10
        return {"data": found_symbols[:limit]}

    except Exception as e:
        logger.error(f"Error scanning directory '{base_path}': {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Server error when searching for available symbols."
        )


@diagnostics_router.get(
    "/logs/history",
    response_model=schemas.ApiResponseData[List[Dict[str, Any]]],
    summary="Get user's recent log history",
)
async def get_log_history(
    current_user: models.User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Fetches the last 100 log entries for the current user from Redis.
    """
    try:
        history_key = f"log_history:{current_user.id}"
        log_entries_json = await redis_client.lrange(history_key, 0, 99)

        log_entries = [json.loads(entry) for entry in log_entries_json]

        return {"data": log_entries}
    except Exception as e:
        logger.error(
            f"Failed to retrieve log history for user {current_user.id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Could not retrieve log history.")
