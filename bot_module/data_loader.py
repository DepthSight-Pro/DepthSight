# bot_module/data_loader.py
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

import backoff
import pandas as pd
import requests
from requests.adapters import HTTPAdapter, Retry

from . import config
from .utils import (
    add_relative_volume,
    calculate_scalper_natr,
    add_volume_percentile_rank,
)

import asyncio
import functools

logger = logging.getLogger("bot_module.data_loader")

# Configuring HTTP session for fault tolerance
retry_strategy = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[
        418,
        429,
        500,
        502,
        503,
        504,
    ],  # Standard server error codes + rate limit
)
adapter = HTTPAdapter(max_retries=retry_strategy)
http_session = requests.Session()
http_session.mount("https://", adapter)
http_session.mount("http://", adapter)

# Constants for DataFrame columns
KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume",
    "ignore",
]
AGGTRADE_COLUMNS = [
    "agg_trade_id",
    "price",
    "quantity",
    "first_trade_id",
    "last_trade_id",
    "timestamp",
    "is_buyer_maker",
]


# ==============================================================================
# Helper functions
# ==============================================================================


def get_local_path(
    symbol: str, data_type: str, market_type: str, timeframe: Optional[str] = None
) -> Path:
    """Determines the path to the local Parquet file for a given data type."""
    market_folder = "futures" if "futures" in market_type else "spot"

    filename = ""
    if data_type == "klines":
        if not timeframe:
            raise ValueError("Timeframe must be provided for klines data type.")
        filename = f"kline_{timeframe}.parquet"
    elif data_type == "aggTrades":
        filename = "aggTrade.parquet"  # The filename for partitions will be different, this is for the old format
    elif data_type == "open_interest":
        filename = "open_interest.parquet"
    elif data_type == "aggregated_depth":
        filename = "aggregated_depth.parquet"
    else:
        raise ValueError(f"Unknown data type {data_type}")

    return (
        Path(config.LOCAL_DATA_STORAGE_PATH)
        / "binance"
        / market_folder
        / symbol.upper()
        / filename
    )


@backoff.on_exception(
    backoff.expo,
    requests.exceptions.RequestException,
    max_tries=5,
    max_time=60,
    logger=logger,
)
def _make_api_request(
    endpoint: str, params: Optional[Dict[str, Any]] = None, market_type: str = "spot"
) -> List[Any]:
    """Performs a request to the Binance API with consideration of the environment (mainnet/testnet)."""
    if config.ACTIVE_TRADING_ENVIRONMENT == "testnet":
        base_url = (
            config.BINANCE_SPOT_TESTNET_API_URL_FOR_LOADER
            if market_type == "spot"
            else config.BINANCE_FUTURES_TESTNET_API_URL_FOR_LOADER
        )
    else:  # mainnet
        base_url = (
            config.BINANCE_SPOT_DATA_API_URL_FOR_LOADER
            if market_type == "spot"
            else config.BINANCE_FUTURES_USDTM_DATA_API_URL_FOR_LOADER
        )

    url = f"{base_url}/{endpoint}"

    logger.debug(f"DataLoader: Making API request to: {url} with params: {params}")
    response = http_session.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


# ==============================================================================
# Private functions for direct data downloading via API (blocking)
# ==============================================================================


def _download_klines_from_api(
    symbol: str, timeframe: str, start_dt: datetime, end_dt: datetime, market_type: str
) -> Optional[pd.DataFrame]:
    """Downloads klines directly from Binance API."""
    logger.info(
        f"API CALL: Loading klines for {symbol} ({timeframe}) with {start_dt} for {end_dt}"
    )
    all_klines = []
    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)

    current_start_ts = start_ts
    while current_start_ts < end_ts:
        params = {
            "symbol": symbol.upper(),
            "interval": timeframe,
            "startTime": current_start_ts,
            "limit": 1000,
            "endTime": end_ts,
        }
        klines_data = _make_api_request("klines", params, market_type=market_type)
        if not klines_data:
            break
        all_klines.extend(klines_data)
        current_start_ts = klines_data[-1][0] + 1

    if not all_klines:
        return pd.DataFrame()

    df = pd.DataFrame(all_klines, columns=KLINE_COLUMNS)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time")
    numeric_cols = ["open", "high", "low", "close", "volume", "number_of_trades"]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    df = df[~df.index.duplicated(keep="first")]
    return df[["open", "high", "low", "close", "volume", "number_of_trades"]]


def _download_agg_trades_from_api(
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    market_type: str,
    limit_per_req: int = 1000,
    max_total_trades: int = 500000,
) -> Optional[pd.DataFrame]:
    """Downloads aggTrades directly with API Binance, using pagination for fromId."""
    logger.info(
        f"API CALL: Loading aggTrades for {symbol} with {start_dt} for {end_dt}"
    )
    all_trades = []
    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)
    from_id = None

    while True:
        params = {"symbol": symbol.upper(), "limit": limit_per_req}
        if from_id is not None:
            params["fromId"] = from_id
        else:
            params["startTime"] = start_ts
            params["endTime"] = end_ts

        trades_data = _make_api_request("aggTrades", params, market_type=market_type)
        if not trades_data:
            break

        last_trade_in_batch = trades_data[-1]
        from_id = last_trade_in_batch["a"] + 1
        all_trades.extend(trades_data)

        if last_trade_in_batch["T"] >= end_ts or len(all_trades) >= max_total_trades:
            break

    if not all_trades:
        return pd.DataFrame()

    df = pd.DataFrame(all_trades)
    df.rename(
        columns={
            "a": "agg_trade_id",
            "p": "price",
            "q": "quantity",
            "T": "timestamp",
            "m": "is_buyer_maker",
        },
        inplace=True,
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    df = df[(df.index >= start_dt) & (df.index <= end_dt)]
    df[["price", "quantity"]] = df[["price", "quantity"]].apply(
        pd.to_numeric, errors="coerce"
    )
    df["is_buyer_maker"] = df["is_buyer_maker"].astype(bool)
    df = df.drop_duplicates(subset=["agg_trade_id"], keep="last")
    return df[["price", "quantity", "is_buyer_maker", "agg_trade_id"]]


def _download_open_interest_from_api(
    symbol: str, timeframe: str, start_dt: datetime, end_dt: datetime, market_type: str
) -> Optional[pd.DataFrame]:
    """Downloads open interest history directly with API Binance."""
    if "futures" not in market_type:
        logger.warning(
            f"Open Interest is available only for futures. Skipping for {market_type}."
        )
        return None

    logger.info(
        f"API CALL: Loading Open Interest for {symbol} ({timeframe}) with {start_dt} for {end_dt}"
    )
    all_oi_data = []
    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)

    current_start_ts = start_ts
    while current_start_ts < end_ts:
        params = {
            "symbol": symbol.upper(),
            "period": timeframe,
            "startTime": current_start_ts,
            "limit": 500,
            "endTime": end_ts,
        }
        try:
            oi_data = _make_api_request(
                "openInterestHist", params, market_type=market_type
            )
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                # Symbol does not support Open Interest History API (new coins, specific contracts)
                logger.warning(
                    f"Open Interest History is unavailable for {symbol} (404). Perhaps the symbol is new or does not support this function."
                )
                return pd.DataFrame()
            raise  # Reraising other HTTP errors

        if not oi_data:
            break
        all_oi_data.extend(oi_data)
        current_start_ts = oi_data[-1]["timestamp"] + 1

    if not all_oi_data:
        return pd.DataFrame()

    df = pd.DataFrame(all_oi_data)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    df["open_interest"] = pd.to_numeric(df["sumOpenInterest"], errors="coerce")
    df = df[~df.index.duplicated(keep="first")]
    return df[["open_interest"]]


# ==============================================================================
# "Smart" public functions (main module interface)
# ==============================================================================


async def download_klines(
    symbol: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
    market_type: str = "futures_usdtm",
) -> Optional[pd.DataFrame]:
    """
    (ASYNCHRONOUS) Hybrid klines loader.
    All blocking operations (file reading, HTTP requests) are executed in separate threads.
    """
    try:
        if isinstance(start_dt, str):
            start_dt = datetime.fromisoformat(start_dt.replace("Z", "+00:00"))
        if isinstance(end_dt, str):
            end_dt = datetime.fromisoformat(end_dt.replace("Z", "+00:00"))

        loop = asyncio.get_running_loop()
        start_dt_utc = (
            start_dt.astimezone(timezone.utc)
            if start_dt.tzinfo
            else start_dt.replace(tzinfo=timezone.utc)
        )
        end_dt_utc = (
            end_dt.astimezone(timezone.utc)
            if end_dt.tzinfo
            else end_dt.replace(tzinfo=timezone.utc)
        )

        local_path = get_local_path(symbol, "klines", market_type, timeframe)
        df_local = None

        if local_path.exists():
            logger.info(f"Local klines file found: {local_path}. Reading...")
            df_local = await loop.run_in_executor(None, pd.read_parquet, local_path)
            df_local = df_local[
                (df_local.index >= start_dt_utc) & (df_local.index <= end_dt_utc)
            ]

        if df_local is not None and not df_local.empty:
            last_local_ts = df_local.index[-1]
            timeframe_delta = pd.to_timedelta(timeframe)
            is_complete = last_local_ts >= end_dt_utc - timeframe_delta
            has_indicators = (
                "natr" in df_local.columns and "is_volume_spike" in df_local.columns
            )

            if is_complete and has_indicators:
                logger.info(
                    "Local data is complete and contains indicators. Returning from cache."
                )
                return df_local

        api_start_dt = start_dt_utc
        if df_local is not None and not df_local.empty:
            api_start_dt = df_local.index[-1] + pd.to_timedelta(timeframe)

        df_api = await loop.run_in_executor(
            None,
            _download_klines_from_api,
            symbol,
            timeframe,
            api_start_dt,
            end_dt_utc,
            market_type,
        )

        if df_api is None and (df_local is None or df_local.empty):
            return None

        df_final = pd.concat([df_local, df_api]) if df_local is not None else df_api
        if df_final.empty:
            return df_final

        df_final = df_final[~df_final.index.duplicated(keep="last")].sort_index()

        def _process_indicators(df: pd.DataFrame) -> pd.DataFrame:
            df_processed = df.copy()
            df_processed = add_relative_volume(df_processed, period=200)
            df_processed = calculate_scalper_natr(df_processed, period=30)
            df_processed = add_volume_percentile_rank(
                df_processed, period=1000, percentile=90
            )
            return df_processed

        df_processed = await loop.run_in_executor(None, _process_indicators, df_final)

        logger.info(f"Loaded/merged and processed {len(df_final)} candles.")
        return df_processed

    except Exception as e:
        logger.error(
            f"Critical error in async download_klines for {symbol}: {e}", exc_info=True
        )
        return None


def get_aggtrade_base_path(symbol: str, market_type: str) -> Path:
    """Returns the root path to aggTrades partitions."""
    dummy_path = get_local_path(symbol, "aggTrades", market_type)
    return dummy_path.parent / "aggTrade"


async def download_agg_trades(
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    market_type: str = "futures_usdtm",
) -> Optional[pd.DataFrame]:
    """(ASYNCHRONOUS) Hybrid aggTrades loader with support for partitioned data."""
    if isinstance(start_dt, str):
        start_dt = datetime.fromisoformat(start_dt.replace("Z", "+00:00"))
    if isinstance(end_dt, str):
        end_dt = datetime.fromisoformat(end_dt.replace("Z", "+00:00"))

    loop = asyncio.get_running_loop()
    start_dt_utc = (
        start_dt.astimezone(timezone.utc)
        if start_dt.tzinfo
        else start_dt.replace(tzinfo=timezone.utc)
    )
    end_dt_utc = (
        end_dt.astimezone(timezone.utc)
        if end_dt.tzinfo
        else end_dt.replace(tzinfo=timezone.utc)
    )

    base_partition_path = get_aggtrade_base_path(symbol, market_type)
    df_local = None

    if base_partition_path.exists():
        logger.info(
            f"Found directory with aggTrades partitions: {base_partition_path}. Reading in a separate thread..."
        )
        try:
            read_func = functools.partial(
                pd.read_parquet,
                base_partition_path,
                engine="pyarrow",
                filters=[
                    ("timestamp", ">=", start_dt_utc),
                    ("timestamp", "<=", end_dt_utc),
                ],
            )
            df_local = await loop.run_in_executor(None, read_func)
            logger.info(f"Loaded from partitions {len(df_local)} aggTrades records.")
        except Exception as e:
            logger.warning(f"Error reading partitioned data: {e}.")
            df_local = pd.DataFrame()

    api_start_dt = start_dt_utc
    if df_local is not None and not df_local.empty:
        last_local_ts = df_local.index[-1]
        if last_local_ts >= end_dt_utc - pd.Timedelta(minutes=5):
            return df_local
        api_start_dt = last_local_ts + pd.Timedelta(milliseconds=1)
        logger.info(f"Local aggTrades are incomplete. Downloading from {api_start_dt}")
    else:
        logger.info("Local aggTrades data not found/empty. Full download via API.")

    df_api = await loop.run_in_executor(
        None,
        _download_agg_trades_from_api,
        symbol,
        api_start_dt,
        end_dt_utc,
        market_type,
    )

    if df_api is None:
        return df_local

    df_final = pd.concat([df_local, df_api]) if df_local is not None else df_api
    df_final.drop_duplicates(subset=["agg_trade_id"], keep="last", inplace=True)
    df_final.sort_index(inplace=True)

    return df_final


async def download_open_interest(
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    market_type: str = "futures_usdtm",
    timeframe: str = "5m",
) -> Optional[pd.DataFrame]:
    """(ASYNCHRONOUS) Hybrid open interest history loader."""
    try:
        if isinstance(start_dt, str):
            start_dt = datetime.fromisoformat(start_dt.replace("Z", "+00:00"))
        if isinstance(end_dt, str):
            end_dt = datetime.fromisoformat(end_dt.replace("Z", "+00:00"))

        loop = asyncio.get_running_loop()
        start_dt_utc = (
            start_dt.astimezone(timezone.utc)
            if start_dt.tzinfo
            else start_dt.replace(tzinfo=timezone.utc)
        )
        end_dt_utc = (
            end_dt.astimezone(timezone.utc)
            if end_dt.tzinfo
            else end_dt.replace(tzinfo=timezone.utc)
        )

        local_path = get_local_path(symbol, "open_interest", market_type)
        df_local = None

        if local_path.exists():
            logger.info(f"Found local open_interest file: {local_path}. Reading...")
            df_local = await loop.run_in_executor(None, pd.read_parquet, local_path)
            df_local = df_local[
                (df_local.index >= start_dt_utc) & (df_local.index <= end_dt_utc)
            ]

        api_start_dt = start_dt_utc
        if df_local is not None and not df_local.empty:
            last_local_ts = df_local.index[-1]
            if last_local_ts >= end_dt_utc - pd.Timedelta(minutes=10):
                return df_local
            api_start_dt = last_local_ts + pd.Timedelta(milliseconds=1)
            logger.info(
                f"Local open_interest data is incomplete. Downloading more with {api_start_dt}"
            )
        else:
            logger.info(
                "Local open_interest file not found/empty. Full download via API."
            )

        df_api = await loop.run_in_executor(
            None,
            _download_open_interest_from_api,
            symbol,
            timeframe,
            api_start_dt,
            end_dt_utc,
            market_type,
        )

        if df_api is None and (df_local is None or df_local.empty):
            return None

        df_final = pd.concat([df_local, df_api]) if df_local is not None else df_api
        if df_final.empty:
            return df_final

        df_final = df_final[~df_final.index.duplicated(keep="last")].sort_index()
        logger.info(f"Loaded/merged {len(df_final)} open interest records.")
        return df_final

    except Exception as e:
        logger.error(
            f"Critical error in async download_open_interest for {symbol}: {e}",
            exc_info=True,
        )
        return None


async def download_aggregated_depth(
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    market_type: str = "futures_usdtm",
) -> Optional[pd.DataFrame]:
    """
    (ASYNCHRONOUS) Loader for aggregated order book data.
    IMPORTANT: This function works ONLY with local data. It does not attempt to download them with API.
    Data must be pre-prepared and saved in Parquet format.
    """
    try:
        loop = asyncio.get_running_loop()
        start_dt_utc = (
            start_dt.astimezone(timezone.utc)
            if start_dt.tzinfo
            else start_dt.replace(tzinfo=timezone.utc)
        )
        end_dt_utc = (
            end_dt.astimezone(timezone.utc)
            if end_dt.tzinfo
            else end_dt.replace(tzinfo=timezone.utc)
        )

        local_path = get_local_path(symbol, "aggregated_depth", market_type)

        if local_path.exists():
            logger.info(f"Found local aggregated_depth file: {local_path}. Reading...")

            read_func = functools.partial(pd.read_parquet, local_path)
            df_local = await loop.run_in_executor(None, read_func)

            # Filter for date if the file contains more data than needed
            if not df_local.empty:
                df_local = df_local[
                    (df_local.index >= start_dt_utc) & (df_local.index <= end_dt_utc)
                ]

            if not df_local.empty:
                logger.info(
                    f"Loaded {len(df_local)} aggregated depth records from local file."
                )
                return df_local
            else:
                logger.warning(
                    f"Local file aggregated_depth {local_path} is empty for the requested range."
                )
                return pd.DataFrame()
        else:
            logger.warning(
                f"Local file for aggregated_depth not found for path: {local_path}. Returning an empty DataFrame."
            )
            return pd.DataFrame()

    except Exception as e:
        logger.error(
            f"Critical error in download_aggregated_depth for {symbol}: {e}",
            exc_info=True,
        )
        return None
