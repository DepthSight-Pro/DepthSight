# download_pipeline.py (Final version with hybrid loading and bookDepth partitioning)
import argparse
import io
import logging
import time
import zipfile
from calendar import monthrange
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional
import gc
import shutil
import os
import sys

# Add project root to sys.path to resolve bot_module imports when running directly as a script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd
import numpy as np
import requests
import psutil

# It is assumed that you have this module
from bot_module.utils import (
    add_relative_volume,
    calculate_scalper_natr,
    add_volume_percentile_rank,
)

"""
Example command


python download_pipeline.py --symbols BTCUSDT --data-types "klines,aggTrades,open_interest,bookDepth" --timeframes "1m,5m,15m,1h,4h,1d" --start-date 2025-06-01 --end-date 2025-09-16 --delete-aggtrades

"""

# ==============================================================================
# Basic setup
# ==============================================================================
logger = logging.getLogger()
if not logger.handlers:
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# ==============================================================================
# Constants
# ==============================================================================
# If running from 'scripts/' directory, point to the parent's data_storage
LOCAL_DATA_STORAGE_PATH = str(Path(__file__).resolve().parent.parent / "data_storage")
BULK_DATA_DOWNLOAD_URL = "https://data.binance.vision"
MARKET_TYPE = "futures"
TEMPLATES = {
    "klines": {
        "daily": "data/futures/um/daily/klines/{symbol}/{timeframe}/{symbol}-{timeframe}-{date_str}.zip",
        "monthly": "data/futures/um/monthly/klines/{symbol}/{timeframe}/{symbol}-{timeframe}-{date_str}.zip",
    },
    "aggTrades": {
        "daily": "data/futures/um/daily/aggTrades/{symbol}/{symbol}-aggTrades-{date_str}.zip",
        "monthly": "data/futures/um/monthly/aggTrades/{symbol}/{symbol}-aggTrades-{date_str}.zip",
    },
    "open_interest": {
        "daily": "data/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{date_str}.zip",
    },
    "bookDepth": {
        "daily": "data/futures/um/daily/bookDepth/{symbol}/{symbol}-bookDepth-{date_str}.zip",
    },
}
ENRICHMENT_MARKER_COLUMN = "tape_total_count_5s"
WINDOWS_SEC = [5, 10, 30]
AVG_LOOKBACKS_SEC = [60, 120]


# ==============================================================================
# Helper functions (with modifications)
# ==============================================================================
def print_memory_usage(context: str = ""):
    process = psutil.Process()
    mem_info = process.memory_info()
    print(f"[{context}] Memory Usage: {mem_info.rss / 1024**2:.2f} MB")


def get_partitioned_folder_name(data_type: str) -> str:
    mapping = {
        "aggTrades": "aggTrade",
        "klines_1s": "klines_1s",
        "bookDepth": "bookDepth",
    }
    if data_type not in mapping:
        raise ValueError(f"Data type {data_type} does not support partitioning.")
    return mapping[data_type]


def get_target_path(
    symbol: str,
    data_type: str,
    timeframe: str = None,
    partition_date: date = None,
    base_path: Optional[Path] = None,
) -> Path:
    if base_path is None:
        actual_base = (
            Path(LOCAL_DATA_STORAGE_PATH) / "binance" / MARKET_TYPE / symbol.upper()
        )
    else:
        # If base_path is provided (e.g. data_storage/actual/binance/futures),
        # we append the symbol to it.
        actual_base = base_path / symbol.upper()

    if data_type == "klines":
        if not timeframe:
            raise ValueError("Timeframe is required for klines.")
        actual_base.mkdir(parents=True, exist_ok=True)
        return actual_base / f"kline_{timeframe}.parquet"
    elif data_type in ["aggTrades", "klines_1s", "bookDepth"]:
        if not partition_date:
            raise ValueError(
                f"Date (partition_date) is required for partitioning {data_type}."
            )
        folder_name = get_partitioned_folder_name(data_type)
        partition_path = (
            actual_base
            / folder_name
            / f"year={partition_date.year}"
            / f"month={partition_date.month}"
        )
        partition_path.mkdir(parents=True, exist_ok=True)
        return partition_path / "data.parquet"
    elif data_type == "open_interest":
        actual_base.mkdir(parents=True, exist_ok=True)
        return actual_base / "open_interest.parquet"
    else:
        raise ValueError(f"Unknown data type: {data_type}")


def save_data(df: pd.DataFrame, target_path: Path):
    if df.empty:
        logging.warning(f"Received empty DataFrame. Saving to {target_path} canceled.")
        return
    if target_path.exists():
        print(f"Detected existing file: {target_path}. Merging...")
        try:
            existing_df = pd.read_parquet(target_path)
            df = pd.concat([existing_df, df])
            df.sort_index(inplace=True)
            df = df[~df.index.duplicated(keep="last")]
        except Exception as e:
            logging.error(
                f"Failed to read {target_path}: {e}. File will be overwritten."
            )
            df.sort_index(inplace=True)
            df = df[~df.index.duplicated(keep="last")]

    df = df[~df.index.duplicated(keep="last")].sort_index()  # Final check
    temp_path = target_path.with_name(f"{target_path.name}.tmp")
    try:
        df.to_parquet(temp_path, engine="pyarrow", compression="snappy")
        os.replace(temp_path, target_path)
        print(f"Successfully saved/updated {len(df)} rows in file {target_path}")
    except Exception as e:
        logging.error(f"Error saving to Parquet file {target_path}: {e}")
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


def download_and_process(
    session: requests.Session,
    symbol: str,
    data_type: str,
    timeframe: str,
    archive_date: date,
    period: str,
    base_path: Optional[Path] = None,
):
    date_str = (
        archive_date.strftime("%Y-%m")
        if period == "monthly"
        else archive_date.strftime("%Y-%m-%d")
    )
    try:
        period_to_use = (
            "daily" if data_type in ["open_interest", "bookDepth"] else period
        )
        path_template = TEMPLATES[data_type][period_to_use]
    except KeyError:
        logging.error(f"Template not found for {data_type}/{period}")
        return

    url_path = path_template.format(
        symbol=symbol.upper(), timeframe=timeframe, date_str=date_str
    )
    full_url = f"{BULK_DATA_DOWNLOAD_URL}/{url_path}"
    print(f"Downloading ({period_to_use.upper()}): {full_url}")

    try:
        response = session.get(full_url, timeout=300, stream=True)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            csv_filename = z.namelist()[0]
            with z.open(csv_filename) as f:
                # bookDepth can be large, but usually not enough to require chunksize
                df_iterator = pd.read_csv(
                    f, chunksize=500000 if data_type != "bookDepth" else None
                )

                for chunk_df in (
                    [df_iterator]
                    if isinstance(df_iterator, pd.DataFrame)
                    else df_iterator
                ):
                    print(f"Processing chunk of {len(chunk_df)} rows...")

                    if data_type == "klines":
                        chunk_df["open_time"] = pd.to_datetime(
                            chunk_df["open_time"], unit="ms", utc=True
                        )
                        chunk_df.set_index("open_time", inplace=True)
                    elif data_type == "aggTrades":
                        chunk_df.rename(
                            columns={
                                "p": "price",
                                "q": "quantity",
                                "m": "is_buyer_maker",
                                "t": "transact_time",
                            },
                            inplace=True,
                            errors="ignore",
                        )
                        chunk_df["transact_time"] = pd.to_datetime(
                            chunk_df["transact_time"], unit="ms", utc=True
                        )
                        chunk_df.set_index("transact_time", inplace=True)
                    elif data_type == "open_interest":
                        # Check that there are enough columns in the DataFrame
                        if chunk_df.shape[1] >= 4:
                            processed_df = pd.DataFrame(
                                {
                                    "create_time": chunk_df.iloc[:, 0],
                                    "open_interest": chunk_df.iloc[:, 2],
                                    "sum_open_interest_value": chunk_df.iloc[:, 3],
                                }
                            )

                            # Remove unit='ms'. Now pandas will determine by itself
                            # whether the value is a number (timestamp) or a string ('YYYY-MM-DD HH:MM:SS').
                            # errors='coerce' will turn any unrecognized formats into NaT (Not a Time),
                            # which we can then remove.
                            processed_df["create_time"] = pd.to_datetime(
                                processed_df["create_time"], errors="coerce", utc=True
                            )

                            # Remove rows where date was not recognized
                            processed_df.dropna(subset=["create_time"], inplace=True)

                            # If empty DataFrame after removal, skip
                            if processed_df.empty:
                                logging.warning(
                                    "Skipped open_interest chunk: no valid timestamps found."
                                )
                                continue

                            processed_df.set_index("create_time", inplace=True)

                            chunk_df = processed_df
                        else:
                            logging.warning(
                                f"Skipped open_interest chunk: expected at least 4 columns, but got {chunk_df.shape[1]}."
                            )
                            continue
                    elif data_type == "bookDepth":
                        if chunk_df.empty:
                            continue
                        chunk_df["timestamp"] = pd.to_datetime(
                            chunk_df["timestamp"], utc=True
                        )
                        pivoted_df = chunk_df.pivot_table(
                            index="timestamp",
                            columns="percentage",
                            values=["depth", "notional"],
                        )
                        pivoted_df.columns = [
                            f"{val}_{'p' if p > 0 else 'm'}{abs(p)}"
                            for val, p in pivoted_df.columns
                        ]
                        chunk_df = pivoted_df

                    chunk_df.index.name = "timestamp"

                    if data_type in ["klines", "open_interest"]:
                        target_path = get_target_path(
                            symbol, data_type, timeframe, base_path=base_path
                        )
                        save_data(chunk_df, target_path)
                    elif data_type in ["aggTrades", "bookDepth"]:
                        for group_month, group_df in chunk_df.groupby(
                            pd.Grouper(freq="MS")
                        ):
                            if not group_df.empty:
                                target_path = get_target_path(
                                    symbol,
                                    data_type,
                                    partition_date=group_month.date(),
                                    base_path=base_path,
                                )
                                save_data(group_df, target_path)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logging.warning(
                f"Data not found (404) for {symbol} for {date_str}. Skipping."
            )
        else:
            logging.error(f"HTTP error downloading {full_url}: {e}")
    except Exception as e:
        logging.error(
            f"Failed to process data for {symbol} for {date_str}: {e}", exc_info=True
        )
    time.sleep(0.5)


def get_existing_dates(
    symbol: str, data_type: str, base_path: Optional[Path] = None
) -> set[date]:
    folder_name = "aggTrade" if data_type == "aggTrades" else "klines_1s"
    if base_path is None:
        target_base = (
            Path(LOCAL_DATA_STORAGE_PATH)
            / "binance"
            / MARKET_TYPE
            / symbol.upper()
            / folder_name
        )
    else:
        target_base = base_path / symbol.upper() / folder_name

    if not target_base.exists():
        return set()
    existing_dates = set()
    for parquet_file in target_base.glob("**/data.parquet"):
        try:
            year = int(parquet_file.parent.parent.name.split("=")[1])
            month = int(parquet_file.parent.name.split("=")[1])
            existing_dates.add(
                date(year, month, 1)
            )  # Returns the beginning of the month
        except (IndexError, ValueError) as e:
            logging.warning(f"Failed to extract date from path {parquet_file}: {e}")
    print(
        f"Found {len(existing_dates)} existing months for {data_type} of symbol {symbol}."
    )
    return existing_dates


def get_existing_partitioned_dates(
    symbol: str, data_type: str, base_path: Optional[Path] = None
) -> set[date]:
    """Scans all partitions and returns a set of all unique dates."""
    folder_name = get_partitioned_folder_name(data_type)
    if base_path is None:
        target_base = (
            Path(LOCAL_DATA_STORAGE_PATH)
            / "binance"
            / MARKET_TYPE
            / symbol.upper()
            / folder_name
        )
    else:
        target_base = base_path / symbol.upper() / folder_name

    if not target_base.exists():
        return set()

    all_dates = set()
    partition_files = list(target_base.glob("**/data.parquet"))
    if not partition_files:
        return set()

    print(
        f"Checking existing dates in {len(partition_files)} partition files for {data_type}..."
    )
    for i, parquet_file in enumerate(partition_files):
        try:
            df = pd.read_parquet(parquet_file, columns=[])  # Read index only
            all_dates.update(set(df.index.date))
            print(f"\rProcessed {i + 1}/{len(partition_files)} files...", end="")
        except Exception as e:
            logging.warning(f"\nFailed to read index from {parquet_file}: {e}")
    print(
        f"\nFound {len(all_dates)} unique existing dates for {data_type} of symbol {symbol}."
    )
    return all_dates


def get_existing_dates_from_parquet(target_path: Path) -> set[date]:
    if not target_path.exists():
        return set()
    try:
        df = pd.read_parquet(target_path, columns=[])
        existing_dates = set(df.index.date)
        print(f"Found {len(existing_dates)} unique dates in file {target_path.name}.")
        return existing_dates
    except Exception as e:
        logging.warning(
            f"Failed to read index from {target_path}: {e}. File will be treated as empty."
        )
        return set()


# --- Other functions (load_aggtrades_for_range, etc.) unchanged ---
def load_aggtrades_for_range(
    symbol: str, start_date: date, end_date: date, base_path: Optional[Path] = None
) -> pd.DataFrame:
    print(f"Loading aggTrades for {symbol} in range {start_date} -> {end_date}")
    all_trades = []
    months_to_load = set()
    current_month_start = date(start_date.year, start_date.month, 1)
    while current_month_start <= end_date:
        months_to_load.add(current_month_start)
        if current_month_start.month == 12:
            current_month_start = current_month_start.replace(
                year=current_month_start.year + 1, month=1
            )
        else:
            current_month_start = current_month_start.replace(
                month=current_month_start.month + 1
            )
    for month_key in sorted(list(months_to_load)):
        partition_path = get_target_path(
            symbol, "aggTrades", partition_date=month_key, base_path=base_path
        )
        if partition_path.exists():
            try:
                month_df = pd.read_parquet(partition_path)
                filtered_df = month_df[
                    (month_df.index.date >= start_date)
                    & (month_df.index.date <= end_date)
                ]
                if not filtered_df.empty:
                    all_trades.append(filtered_df)
                del month_df, filtered_df
                gc.collect()
            except Exception as e:
                logging.warning(f"Failed to read partition {partition_path}: {e}")
    if not all_trades:
        return pd.DataFrame()

    combined_df = pd.concat(all_trades).sort_index()
    if combined_df.index.has_duplicates:
        duplicates_count = combined_df.index.duplicated().sum()
        print(
            f"Detected and removed {duplicates_count} duplicates when loading aggTrades for the period."
        )
        combined_df = combined_df[~combined_df.index.duplicated(keep="last")]
    return combined_df


def calculate_tape_features(
    target_index: pd.DatetimeIndex, agg_trades_df: pd.DataFrame
) -> pd.DataFrame:
    print(f"Starting tape features calculation for {len(target_index)} candles...")
    if agg_trades_df.empty:
        logging.warning(
            "Empty trades DataFrame passed, tape features calculation skipped."
        )
        return pd.DataFrame(index=target_index)

    # --- DATA VERIFICATION AND PREPARATION BLOCK ---
    if "price" not in agg_trades_df.columns or "quantity" not in agg_trades_df.columns:
        logging.error(
            "CRITICAL ERROR: 'price' or 'quantity' columns are missing in aggTrades. Tape features calculation is impossible."
        )
        return pd.DataFrame(index=target_index)
    if "volume_usd" not in agg_trades_df.columns:
        agg_trades_df["volume_usd"] = agg_trades_df["price"] * agg_trades_df["quantity"]
    if "is_buyer_maker" not in agg_trades_df.columns:
        logging.error(
            "CRITICAL ERROR: 'is_buyer_maker' column is missing in aggTrades. Tape features calculation is impossible."
        )
        return pd.DataFrame(index=target_index)

    if not agg_trades_df.index.is_monotonic_increasing:
        agg_trades_df.sort_index(inplace=True)
    if agg_trades_df.index.has_duplicates:
        agg_trades_df = agg_trades_df[~agg_trades_df.index.duplicated(keep="last")]

    agg_trades_df["buy_volume_usd"] = np.where(
        agg_trades_df["is_buyer_maker"], 0, agg_trades_df["volume_usd"]
    )
    agg_trades_df["sell_volume_usd"] = np.where(
        agg_trades_df["is_buyer_maker"], agg_trades_df["volume_usd"], 0
    )
    agg_trades_df["buy_trade_count"] = np.where(agg_trades_df["is_buyer_maker"], 0, 1)
    agg_trades_df["sell_trade_count"] = np.where(agg_trades_df["is_buyer_maker"], 1, 0)

    list_of_feature_dfs = []
    epsilon = 1e-9

    # WINDOWS_SEC and AVG_LOOKBACKS_SEC are now global constants

    # --- Calculation of features by windows (rolling activity) ---
    for w_sec in WINDOWS_SEC:
        rolling_activity = agg_trades_df.rolling(f"{w_sec}s").agg(
            {
                "buy_volume_usd": "sum",
                "sell_volume_usd": "sum",
                "buy_trade_count": "sum",
                "sell_trade_count": "sum",
            }
        )
        rolling_activity.rename(
            columns={
                "buy_volume_usd": f"tape_buy_volume_usd_{w_sec}s",
                "sell_volume_usd": f"tape_sell_volume_usd_{w_sec}s",
                "buy_trade_count": f"tape_buy_trade_count_{w_sec}s",
                "sell_trade_count": f"tape_sell_trade_count_{w_sec}s",
            },
            inplace=True,
        )

        rolling_activity[f"tape_total_volume_usd_{w_sec}s"] = (
            rolling_activity[f"tape_buy_volume_usd_{w_sec}s"]
            + rolling_activity[f"tape_sell_volume_usd_{w_sec}s"]
        )
        rolling_activity[f"tape_delta_volume_usd_{w_sec}s"] = (
            rolling_activity[f"tape_buy_volume_usd_{w_sec}s"]
            - rolling_activity[f"tape_sell_volume_usd_{w_sec}s"]
        )
        rolling_activity[f"tape_total_count_{w_sec}s"] = (
            rolling_activity[f"tape_buy_trade_count_{w_sec}s"]
            + rolling_activity[f"tape_sell_trade_count_{w_sec}s"]
        )
        rolling_activity[f"tape_delta_count_{w_sec}s"] = (
            rolling_activity[f"tape_buy_trade_count_{w_sec}s"]
            - rolling_activity[f"tape_sell_trade_count_{w_sec}s"]
        )
        rolling_activity[f"tape_buy_sell_ratio_volume_{w_sec}s"] = rolling_activity[
            f"tape_buy_volume_usd_{w_sec}s"
        ] / (rolling_activity[f"tape_sell_volume_usd_{w_sec}s"] + epsilon)
        rolling_activity[f"tape_buy_sell_ratio_count_{w_sec}s"] = rolling_activity[
            f"tape_buy_trade_count_{w_sec}s"
        ] / (rolling_activity[f"tape_sell_trade_count_{w_sec}s"] + epsilon)

        list_of_feature_dfs.append(rolling_activity)

    # --- Calculation of averages for acceleration ---
    for avg_sec in AVG_LOOKBACKS_SEC:
        rolling_avg = agg_trades_df.rolling(f"{avg_sec}s").agg(
            {"volume_usd": "sum", "buy_trade_count": "sum", "sell_trade_count": "sum"}
        )
        avg_per_sec_raw = rolling_avg / avg_sec

        # Instead of .rename(inplace=True) we create a new DataFrame with required names
        avg_per_sec_final = pd.DataFrame(
            {
                f"tape_avg_volume_per_sec_{avg_sec}s": avg_per_sec_raw["volume_usd"],
                f"tape_avg_count_per_sec_{avg_sec}s": avg_per_sec_raw["buy_trade_count"]
                + avg_per_sec_raw["sell_trade_count"],
            },
            index=avg_per_sec_raw.index,
        )

        list_of_feature_dfs.append(avg_per_sec_final)

    # --- Merging all features and calculating acceleration ---
    all_tape_features_df = pd.concat(list_of_feature_dfs, axis=1)

    for w_sec in WINDOWS_SEC:
        for avg_sec in AVG_LOOKBACKS_SEC:
            current_vol_col = f"tape_total_volume_usd_{w_sec}s"
            avg_vol_per_sec_col = f"tape_avg_volume_per_sec_{avg_sec}s"
            if (
                current_vol_col in all_tape_features_df
                and avg_vol_per_sec_col in all_tape_features_df
            ):
                avg_vol_for_window = all_tape_features_df[avg_vol_per_sec_col] * w_sec
                all_tape_features_df[f"tape_accel_mult_volume_{w_sec}s_{avg_sec}s"] = (
                    all_tape_features_df[current_vol_col]
                    / (avg_vol_for_window + epsilon)
                )

            current_count_col = f"tape_total_count_{w_sec}s"
            avg_count_per_sec_col = f"tape_avg_count_per_sec_{avg_sec}s"
            if (
                current_count_col in all_tape_features_df
                and avg_count_per_sec_col in all_tape_features_df
            ):
                avg_count_for_window = (
                    all_tape_features_df[avg_count_per_sec_col] * w_sec
                )
                all_tape_features_df[f"tape_accel_mult_count_{w_sec}s_{avg_sec}s"] = (
                    all_tape_features_df[current_count_col]
                    / (avg_count_for_window + epsilon)
                )

    return all_tape_features_df.reindex(target_index, method="ffill")


def is_enrichment_needed(df: pd.DataFrame, marker_column: str) -> bool:
    """Checks if enrichment is needed for this DataFrame."""
    if marker_column not in df.columns:
        print(
            f"   Check: Marker column '{marker_column}' is missing. Enrichment is required."
        )
        return True

    total_rows = len(df)
    if total_rows == 0:
        return False  # Nothing to enrich

    null_count = df[marker_column].isnull().sum()
    if null_count == 0:
        print("   Check: All data is already enriched (no null values). Skipping.")
        return False

    # Allow up to 1% of empty values (warm-up of indicators at the beginning)
    null_percentage = (null_count / total_rows) * 100
    if null_percentage < 1.0:
        print(
            f"   Check: Found small amount ({null_percentage:.2f}%) of empty values. Considering enrichment complete. Skipping."
        )
        return False

    print(
        f"   Check: Found too many ({null_percentage:.2f}%) empty values in the marker column. Enrichment is required."
    )
    return True


def run_enrichment_for_1m(
    symbol: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    base_path: Optional[Path] = None,
):
    print(f"--- 1M KLINES ENRICHMENT for {symbol} ---")
    kline_path = get_target_path(symbol, "klines", "1m", base_path=base_path)
    if not kline_path.exists():
        logging.error(
            f"File kline_1m.parquet not found for {symbol}. Enrichment is impossible."
        )
        return

    print(f"Loading candles from {kline_path}...")
    # Load only the marker column for a quick check
    try:
        klines_df_check = pd.read_parquet(
            kline_path, columns=[ENRICHMENT_MARKER_COLUMN]
        )
    except Exception:
        # If it failed (e.g. column is missing), read everything, check will decide
        klines_df_check = pd.read_parquet(kline_path)

    # === START OF NEW CHECK BLOCK ===
    if not is_enrichment_needed(klines_df_check, ENRICHMENT_MARKER_COLUMN):
        print(f"--- Enrichment for {symbol} is not required. Skipping. ---")
        return
    del klines_df_check  # Free memory
    # === END OF NEW CHECK BLOCK ===

    print("Full re-enrichment is required. Loading full candle file...")
    klines_df = pd.read_parquet(kline_path)
    print_memory_usage("After loading klines_df")

    # --- Incremental enrichment ---
    # We no longer delete all tape_cols in bulk.
    # Instead, we will check data availability for each day.

    # Generate a full list of columns that we must have
    tape_cols = []

    # 1. Rolling activity columns
    for w in WINDOWS_SEC:
        tape_cols.extend(
            [
                f"tape_buy_volume_usd_{w}s",
                f"tape_sell_volume_usd_{w}s",
                f"tape_buy_trade_count_{w}s",
                f"tape_sell_trade_count_{w}s",
                f"tape_total_volume_usd_{w}s",
                f"tape_delta_volume_usd_{w}s",
                f"tape_total_count_{w}s",
                f"tape_delta_count_{w}s",
                f"tape_buy_sell_ratio_volume_{w}s",
                f"tape_buy_sell_ratio_count_{w}s",
            ]
        )

    # 2. Average per sec columns
    for avg in AVG_LOOKBACKS_SEC:
        tape_cols.extend(
            [f"tape_avg_volume_per_sec_{avg}s", f"tape_avg_count_per_sec_{avg}s"]
        )

    # 3. Acceleration columns
    for w in WINDOWS_SEC:
        for avg in AVG_LOOKBACKS_SEC:
            tape_cols.extend(
                [
                    f"tape_accel_mult_volume_{w}s_{avg}s",
                    f"tape_accel_mult_count_{w}s_{avg}s",
                ]
            )

    # Initialize columns if they don't exist to allow checks/assignments
    # (but do not overwrite existing data if present!)
    for col in tape_cols:
        if col not in klines_df.columns:
            klines_df[col] = np.nan
            # Memory optimization for new columns
            if "count" in col:
                klines_df[col] = klines_df[col].astype(
                    "float32"
                )  # count can be int, but NaN requires float
            else:
                klines_df[col] = klines_df[col].astype("float32")

    # Remove only EXPLICIT duplicates/junk (with suffixes _x, _y),
    # which could remain from past unsuccessful merges
    cols_to_drop = [
        c for c in klines_df.columns if c.endswith("_x") or c.endswith("_y")
    ]
    if cols_to_drop:
        print(f"Removing {len(cols_to_drop)} junk columns (suffixes _x/_y).")
        klines_df.drop(columns=cols_to_drop, inplace=True)
        gc.collect()

    # Calculating basic indicators (they don't require much memory)
    print("Calculating basic indicators (natr, relative_volume, volume_percentile)...")
    klines_df = add_relative_volume(klines_df, period=200)
    klines_df = calculate_scalper_natr(klines_df, period=30)
    if "natr" in klines_df.columns:
        klines_df.rename(columns={"natr": "scalper_natr"}, inplace=True)
    klines_df = add_volume_percentile_rank(klines_df, period=1000, percentile=90)
    if "volume_percentile_threshold" in klines_df.columns:
        klines_df["volume_percentile_rank"] = klines_df["volume_percentile_threshold"]
    print("Basic indicators calculation complete.")

    min_date, max_date = klines_df.index.min().date(), klines_df.index.max().date()
    print(
        f"Starting incremental calculation of tape features for range: {min_date} -> {max_date}"
    )
    if start_date or end_date:
        print(f"Date filter applied: {start_date} -> {end_date}")

    # Group days by month to load monthly parquet file exactly once
    months_groups = {}
    date_range = pd.date_range(start=min_date, end=max_date, freq="D")
    for current_day in date_range:
        if start_date and current_day.date() < start_date:
            continue
        if end_date and current_day.date() > end_date:
            continue

        day_mask = klines_df.index.date == current_day.date()
        if not day_mask.any():
            continue

        day_slice = klines_df.loc[day_mask, ENRICHMENT_MARKER_COLUMN]
        if day_slice.notna().all():
            print(f"Day {current_day.strftime('%Y-%m-%d')} already enriched. Skipping.")
            continue

        month_key = (current_day.year, current_day.month)
        if month_key not in months_groups:
            months_groups[month_key] = []
        months_groups[month_key].append(current_day)

    days_processed = 0
    total_days_to_enrich = sum(len(days) for days in months_groups.values())
    current_day_index = 0

    for (year, month), days in sorted(months_groups.items()):
        print(
            f"\n--- Loading aggTrades for month: {year}-{month:02d} (found {len(days)} days to enrich) ---"
        )

        month_start = date(year, month, 1)
        partition_path = get_target_path(
            symbol, "aggTrades", partition_date=month_start, base_path=base_path
        )

        if not partition_path.exists():
            logging.warning(
                f"No aggTrades partition file found: {partition_path}. Skipping this month."
            )
            current_day_index += len(days)
            continue

        try:
            print(f"Reading {partition_path}...")
            month_trades_df = pd.read_parquet(partition_path)
            if not month_trades_df.index.is_monotonic_increasing:
                month_trades_df.sort_index(inplace=True)
            if month_trades_df.index.has_duplicates:
                month_trades_df = month_trades_df[
                    ~month_trades_df.index.duplicated(keep="last")
                ]
        except Exception as e:
            logging.error(f"Failed to read partition {partition_path}: {e}")
            current_day_index += len(days)
            continue

        for current_day in days:
            current_day_index += 1
            day_str = current_day.strftime("%Y-%m-%d")
            print(
                f"\n>>>> Enriching day {day_str} ({current_day_index}/{total_days_to_enrich}) <<<<"
            )

            day_mask = klines_df.index.date == current_day.date()

            # Slice the loaded month trades for the day (+ 5 mins buffer at start)
            day_start = pd.to_datetime(
                current_day.date() - timedelta(minutes=5)
            ).tz_localize("UTC")
            day_end = pd.to_datetime(
                current_day.date() + timedelta(days=1)
            ).tz_localize("UTC")

            agg_trades_day = month_trades_df.loc[day_start:day_end]

            if agg_trades_day.empty:
                logging.warning(
                    f"No aggTrades data in partition for {day_str}. Tape features will not be calculated."
                )
                continue

            print(f"Calculating tape features for {day_mask.sum()} rows...")
            new_features_df = calculate_tape_features(
                klines_df.index[day_mask], agg_trades_day
            )

            if not new_features_df.empty:
                new_features_df = new_features_df.astype("float32")
                common_cols = new_features_df.columns.intersection(klines_df.columns)
                if len(common_cols) > 0:
                    klines_df.loc[new_features_df.index, common_cols] = new_features_df[
                        common_cols
                    ]
                    days_processed += 1
                else:
                    logging.warning(f"No common columns to update on day {day_str}!")

            del agg_trades_day, new_features_df
            gc.collect()

        del month_trades_df
        gc.collect()

        # Save intermediate progress to disk after completing each month
        if days_processed > 0:
            print(
                f"\nSaving intermediate enriched file kline_1m.parquet after month {year}-{month:02d}..."
            )
            try:
                if klines_df.columns.duplicated().any():
                    klines_df = klines_df.loc[
                        :, ~klines_df.columns.duplicated(keep="first")
                    ]
                klines_df.to_parquet(kline_path, engine="pyarrow", compression="snappy")
                print("Intermediate save complete.")
            except Exception as e:
                logging.error(f"Failed to save intermediate progress: {e}")

    if days_processed > 0:
        print(f"\nSuccessfully enriched {days_processed} days.")
    else:
        print("\nNo new days for enrichment found (all skipped).")

    print("\nSaving final enriched file kline_1m.parquet...")

    # Column deduplication before saving (in case of artifacts from previous failures)
    if klines_df.columns.duplicated().any():
        dup_cols = klines_df.columns[klines_df.columns.duplicated()].tolist()
        print(f"WARNING: Duplicate columns detected: {dup_cols}. Removing duplicates.")
        klines_df = klines_df.loc[:, ~klines_df.columns.duplicated(keep="first")]

    klines_df.to_parquet(kline_path, engine="pyarrow", compression="snappy")
    print("Saving complete.")


def run_generation_for_1s(
    symbol: str, start_date: date, end_date: date, base_path: Optional[Path] = None
):
    print(f"--- GENERATION AND ENRICHMENT OF 1S KLINES for {symbol} ---")
    existing_months = get_existing_dates(symbol, "klines_1s", base_path=base_path)
    current_month_start = date(start_date.year, start_date.month, 1)
    while current_month_start <= end_date:
        month_key = current_month_start
        if month_key in existing_months:
            print(
                f"Second-by-second data for {month_key.strftime('%Y-%m')} already exists. Skipping."
            )
            current_month_start = (current_month_start + timedelta(days=32)).replace(
                day=1
            )
            continue
        print(f"\n--- Processing month: {month_key.strftime('%Y-%m')} ---")
        _, days_in_month = monthrange(month_key.year, month_key.month)
        month_end = month_key.replace(day=days_in_month)

        # Need to fix load_aggtrades_for_range if we want full base_path support there too
        month_trades_df = load_aggtrades_for_range(
            symbol, month_key - timedelta(days=1), month_end, base_path=base_path
        )
        if month_trades_df.empty:
            logging.warning(
                f"No aggTrades data for month {month_key.strftime('%Y-%m')}. Skipping generation."
            )
            current_month_start = (current_month_start + timedelta(days=32)).replace(
                day=1
            )
            continue
        print_memory_usage(f"After loading aggTrades for {month_key.strftime('%Y-%m')}")
        print("Generating 1s OHLCV...")
        resampler = month_trades_df["price"].resample("1s")
        klines_1s_df = resampler.ohlc()
        klines_1s_df["volume"] = month_trades_df["quantity"].resample("1s").sum()
        klines_1s_df.dropna(subset=["open", "high", "low", "close"], inplace=True)
        print(f"Generated {len(klines_1s_df)} second-by-second candles.")
        if klines_1s_df.empty:
            current_month_start = (current_month_start + timedelta(days=32)).replace(
                day=1
            )
            continue
        print("Enriching 1s candles with tape features...")
        enriched_1s_df = calculate_tape_features(klines_1s_df.index, month_trades_df)
        klines_1s_df.update(enriched_1s_df)
        final_month_df = klines_1s_df[klines_1s_df.index.month == month_key.month]
        target_path = get_target_path(
            symbol, "klines_1s", partition_date=month_key, base_path=base_path
        )
        print(f"Saving enriched 1s klines to {target_path}...")
        final_month_df.to_parquet(target_path, engine="pyarrow", compression="snappy")
        del month_trades_df, klines_1s_df, enriched_1s_df, final_month_df
        gc.collect()
        print_memory_usage(f"After memory cleanup for {month_key.strftime('%Y-%m')}")
        current_month_start = (current_month_start + timedelta(days=32)).replace(day=1)


def delete_aggtrades_for_range(
    symbol: str, start_date: date, end_date: date, base_path: Optional[Path] = None
):
    """
    Deletes aggTrades partitions for the specified date range,
    PREVIOUSLY CHECKING that the kline_1m data was successfully enriched.
    """
    print(
        f"--- VERIFICATION BEFORE DELETING AGGTRADES for {symbol} in range {start_date} -> {end_date} ---"
    )

    # --- Start of verification block ---
    kline_path = get_target_path(symbol, "klines", "1m", base_path=base_path)
    if not kline_path.exists():
        logging.error(
            f"File kline_1m.parquet not found for {symbol}. Cannot verify enrichment. DELETION CANCELED."
        )
        return

    try:
        print(f"Loading data for verification from {kline_path}...")
        # Load only the index and marker column to save memory
        klines_df = pd.read_parquet(kline_path, columns=[ENRICHMENT_MARKER_COLUMN])

        if ENRICHMENT_MARKER_COLUMN not in klines_df.columns:
            logging.error(
                f"Marker column '{ENRICHMENT_MARKER_COLUMN}' not found in {kline_path}. Enrichment was not performed. DELETION CANCELED."
            )
            return

        # Filter DataFrame by required date range
        klines_in_range = klines_df[
            (klines_df.index.date >= start_date) & (klines_df.index.date <= end_date)
        ]

        if klines_in_range.empty:
            logging.warning(
                f"No candles found in kline_1m.parquet in range {start_date} -> {end_date}. Verification is impossible. Deletion canceled."
            )
            return

        # Check if there are unfilled (null) values in the marker column
        if klines_in_range[ENRICHMENT_MARKER_COLUMN].isnull().any():
            null_count = klines_in_range[ENRICHMENT_MARKER_COLUMN].isnull().sum()
            total_count = len(klines_in_range)
            logging.error(
                f"Detected {null_count} out of {total_count} unenriched rows in kline_1m in the specified date range. DELETION CANCELED."
            )
            return

        print(
            "VERIFICATION SUCCESSFUL: All 1-minute candles in the date range are enriched."
        )

    except Exception as e:
        logging.error(
            f"Error during enrichment check: {e}. DELETION CANCELED.", exc_info=True
        )
        return
    # --- End of verification block ---

    print(
        f"--- STARTING DELETION OF AGGTRADES for {symbol} in range {start_date} -> {end_date} ---"
    )
    current_month_start = date(start_date.year, start_date.month, 1)
    while current_month_start <= end_date:
        year, month = current_month_start.year, current_month_start.month

        if base_path is None:
            base_dir = (
                Path(LOCAL_DATA_STORAGE_PATH)
                / "binance"
                / MARKET_TYPE
                / symbol.upper()
                / "aggTrade"
            )
        else:
            base_dir = base_path / symbol.upper() / "aggTrade"

        month_dir = base_dir / f"year={year}" / f"month={month}"
        year_dir = base_dir / f"year={year}"

        if month_dir.exists():
            try:
                shutil.rmtree(month_dir)
                print(f"Successfully deleted folder: {month_dir}")
                # Check if the year folder has become empty, and delete it if so
                if year_dir.exists() and not os.listdir(year_dir):
                    os.rmdir(year_dir)
                    print(f"Deleted empty year folder: {year_dir}")
            except Exception as e:
                logging.error(f"Failed to delete folder {month_dir}: {e}")

        # Move to the next month
        if current_month_start.month == 12:
            current_month_start = current_month_start.replace(
                year=current_month_start.year + 1, month=1
            )
        else:
            current_month_start = current_month_start.replace(
                month=current_month_start.month + 1
            )

    print("--- DELETION OF AGGTRADES COMPLETE ---")


# ==============================================================================
# Main logic
# ==============================================================================

# ==============================================================================
# Reusable logic (exported)
# ==============================================================================


def run_pipeline(
    symbols: list[str],
    data_types: list[str],
    start_date_obj: date,
    end_date_obj: date,
    timeframes: list[str] = ["1m"],
    enrich_only: bool = False,
    delete_aggtrades: bool = False,
    base_path: Optional[Path] = None,
):
    """
    Programmatic entry point for starting load/enrichment pipeline.
    """
    total_symbols = len(symbols)
    total_types = len(data_types)
    total_steps = total_symbols * total_types
    current_step = 0

    def print_progress(msg: str = ""):
        nonlocal current_step
        progress = (current_step / total_steps) * 100
        print(f"[PROGRESS]: {progress:.1f}% | {msg}")

    if not enrich_only:
        session = requests.Session()
        for symbol in symbols:
            print(f"\n{'=' * 20} PROCESSING SYMBOL: {symbol} {'=' * 20}")
            for data_type in data_types:
                current_step += 1
                print_progress(f"Processing {symbol} {data_type}...")
                print(f"\n--- Data type: {data_type} ---")

                # --- Logic for aggTrades (hybrid load) ---
                if data_type == "aggTrades":
                    today = datetime.utcnow().date()

                    # 1. Get ALL existing dates for aggTrades ONCE at the beginning
                    # TODO: get_existing_partitioned_dates also needs base_path support?
                    # For now, let's assume klines are the priority for the simulator.
                    print("Preliminary check of existing dates for aggTrades...")
                    existing_dates_agg = get_existing_partitioned_dates(
                        symbol, "aggTrades", base_path=base_path
                    )

                    # 2. Collect all months in the specified range
                    months_to_process = set()
                    d = start_date_obj
                    while d <= end_date_obj:
                        months_to_process.add(date(d.year, d.month, 1))
                        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)

                    print(
                        f"Planned processing of {len(months_to_process)} months for aggTrades..."
                    )
                    for month_start in sorted(list(months_to_process)):
                        _, days_in_month = monthrange(
                            month_start.year, month_start.month
                        )
                        month_end = month_start.replace(day=days_in_month)

                        # Flag that will determine if we need to check days individually
                        needs_daily_check = True

                        # Try to download monthly archive if month is fully passed
                        if month_end < today - timedelta(days=1):
                            has_any_data_for_month = any(
                                d.year == month_start.year
                                and d.month == month_start.month
                                for d in existing_dates_agg
                            )

                            if not has_any_data_for_month:
                                print(
                                    f"Processing full passed month: {month_start.strftime('%Y-%m')}. Downloading monthly archive."
                                )
                                download_and_process(
                                    session,
                                    symbol,
                                    "aggTrades",
                                    None,
                                    month_start,
                                    "monthly",
                                )
                                needs_daily_check = False
                            else:
                                print(
                                    f"Skipping monthly archive for {month_start.strftime('%Y-%m')} because data for this month already partially exists."
                                )

                        # If current month or we decided to process it by days
                        if needs_daily_check:
                            print(
                                f"Processing month by days: {month_start.strftime('%Y-%m')}. Downloading missing daily archives."
                            )

                            start_loop = max(start_date_obj, month_start)
                            end_loop = min(end_date_obj, month_end, today)

                            d_inner = start_loop
                            while d_inner <= end_loop:
                                if d_inner not in existing_dates_agg:
                                    download_and_process(
                                        session,
                                        symbol,
                                        "aggTrades",
                                        None,
                                        d_inner,
                                        "daily",
                                    )
                                else:
                                    print(
                                        f"Skip: aggTrades data for {symbol} for {d_inner} already exists."
                                    )
                                d_inner += timedelta(days=1)

                # --- Logic for bookDepth (partitioned daily load) ---
                elif data_type == "bookDepth":
                    existing_dates = get_existing_partitioned_dates(
                        symbol, data_type, base_path=base_path
                    )
                    current_date = start_date_obj
                    while current_date <= end_date_obj:
                        if current_date not in existing_dates:
                            download_and_process(
                                session,
                                symbol,
                                data_type,
                                None,
                                current_date,
                                "daily",
                                base_path=base_path,
                            )
                        else:
                            print(
                                f"Skip: data for {symbol} {data_type} for {current_date} already exists."
                            )
                        current_date += timedelta(days=1)

                # --- Logic for other (non-partitioned) data types ---
                else:  # klines, open_interest
                    tf_list = timeframes if data_type == "klines" else [None]
                    for timeframe in tf_list:
                        target_path = get_target_path(
                            symbol, data_type, timeframe, base_path=base_path
                        )
                        existing_dates = get_existing_dates_from_parquet(target_path)

                        current_date = start_date_obj
                        while current_date <= end_date_obj:
                            if current_date not in existing_dates:
                                download_and_process(
                                    session,
                                    symbol,
                                    data_type,
                                    timeframe,
                                    current_date,
                                    "daily",
                                    base_path=base_path,
                                )
                            else:
                                print(
                                    f"Skip: data for {symbol} {data_type} {timeframe or ''} for {current_date} already exists."
                                )
                            current_date += timedelta(days=1)
        print("\n--- DATA LOADING COMPLETE ---")

    # --- Post-processing phase (enrichment and deletion) ---
    needs_postprocessing = (
        "klines" in data_types and "aggTrades" in data_types
    ) or enrich_only
    if needs_postprocessing:
        print(f"\n{'=' * 20} POST-PROCESSING PHASE {'=' * 20}")
        for symbol in symbols:
            print(f"\n--- Post-processing for symbol: {symbol} ---")

            # Enrich 1-minute candles if they were in the request
            if "1m" in timeframes or enrich_only:
                run_enrichment_for_1m(
                    symbol,
                    start_date=start_date_obj,
                    end_date=end_date_obj,
                    base_path=base_path,
                )

            # Generate 1-second candles
            run_generation_for_1s(
                symbol, start_date_obj, end_date_obj, base_path=base_path
            )

            # Delete aggTrades if flag is specified
            if delete_aggtrades:
                delete_aggtrades_for_range(
                    symbol, start_date_obj, end_date_obj, base_path=base_path
                )

    print(f"\n{'=' * 20} PIPELINE COMPLETELY FINISHED {'=' * 20}")


def get_parquet_range(target_path: Path) -> tuple[Optional[date], Optional[date]]:
    """Quickly gets first and last dates from file without loading all data."""
    if not target_path.exists():
        return None, None
    try:
        # The fastest way for pandas parquet:
        df_first = pd.read_parquet(target_path, engine="pyarrow").head(1)
        df_last = pd.read_parquet(target_path, engine="pyarrow").tail(1)
        if df_first.empty or df_last.empty:
            return None, None
        return df_first.index[0].date(), df_last.index[0].date()
    except Exception as e:
        logging.warning(f"Error during quick read of {target_path}: {e}")
        return None, None


def ensure_data_for_period(
    symbols: list[str],
    start_date_str: str,
    end_date_str: str,
    base_path: Optional[Path] = None,
):
    """
    Checks data presence for period and loads missing.
    Uses quick bounds check (min/max).
    """
    try:
        if not start_date_str or not end_date_str:
            logging.info("Period not specified, automatic loading skipped.")
            return

        start_dt = pd.to_datetime(start_date_str).date()
        end_dt = pd.to_datetime(end_date_str).date()

        symbols_to_process = []

        for symbol in symbols:
            kline_path = get_target_path(symbol, "klines", "1m", base_path=base_path)

            min_date, max_date = get_parquet_range(kline_path)

            # If file doesn't exist or doesn't cover full range
            is_missing = False
            if min_date is None or max_date is None:
                is_missing = True
                logging.info(f"Download trigger: {symbol} file not found or empty.")
            elif start_dt < min_date:
                is_missing = True
                logging.info(
                    f"Download trigger: {symbol} start date missing. Req: {start_dt}, Found Min: {min_date}"
                )
            elif end_dt > max_date:
                is_missing = True
                logging.info(
                    f"Download trigger: {symbol} end date missing. Req: {end_dt}, Found Max: {max_date}"
                )

            if is_missing:
                symbols_to_process.append(symbol)
            else:
                logging.info(
                    f"Download check PASSED: {symbol} has {min_date} to {max_date}"
                )

        if symbols_to_process:
            logging.info(
                f"--- STARTING AUTO DOWNLOAD FOR: {symbols_to_process} ({start_dt} -> {end_dt}) ---"
            )

            run_pipeline(
                symbols=symbols_to_process,
                data_types=["klines"],
                timeframes=["1m"],
                start_date_obj=start_dt,
                end_date_obj=end_dt,
                delete_aggtrades=False,
                base_path=base_path,
            )
            logging.info("--- AUTO DOWNLOAD FINISHED ---")
        else:
            logging.info("--- All data present, skipping download. ---")

    except Exception as e:
        logging.error(f"Error in ensure_data_for_period: {e}", exc_info=True)


# ==============================================================================
# CLI Entry point
# ==============================================================================


def main():
    print("--- SCRIPT STARTED ---")
    parser = argparse.ArgumentParser(
        description="ETL pipeline for downloading and enriching Binance historical data.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--symbols",
        required=True,
        type=str,
        help="List of symbols separated by commas (e.g., BTCUSDT,ETHUSDT)",
    )
    parser.add_argument(
        "--data-types",
        type=str,
        default="klines,aggTrades",
        help="Data types to load separated by commas (klines,aggTrades,open_interest,bookDepth)",
    )
    parser.add_argument(
        "--timeframes",
        type=str,
        default="1m",
        help="Timeframes for klines (e.g., 1m,5m,1h)",
    )
    parser.add_argument(
        "--start-date", type=str, help="Start date in YYYY-MM-DD format"
    )
    parser.add_argument("--end-date", type=str, help="End date in YYYY-MM-DD format")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Flag for quick loading of data for yesterday only.",
    )
    parser.add_argument(
        "--enrich-only",
        action="store_true",
        help="Skip loading and run only enrichment/generation process for existing data.",
    )
    parser.add_argument(
        "--delete-aggtrades",
        action="store_true",
        help="Delete aggTrades partitions after enrichment use (with preliminary check).",
    )

    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    data_types = [dt.strip() for dt in args.data_types.split(",")]
    timeframes = [tf.strip() for tf in args.timeframes.split(",")]

    start_date_obj = None
    end_date_obj = None

    if args.update:
        start_date_obj = end_date_obj = datetime.utcnow().date() - timedelta(days=1)
        print(
            f"--- UPDATE MODE: Downloading data for {start_date_obj.strftime('%Y-%m-%d')} ---"
        )
    elif args.start_date and args.end_date:
        start_date_obj = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        end_date_obj = datetime.strptime(args.end_date, "%Y-%m-%d").date()
        print(
            f"--- RANGE DOWNLOAD MODE: {start_date_obj.strftime('%Y-%m-%d')} -> {end_date_obj.strftime('%Y-%m-%d')} ---"
        )
    else:
        parser.error("Must specify --start-date and --end-date, or --update flag.")

    run_pipeline(
        symbols=symbols,
        data_types=data_types,
        start_date_obj=start_date_obj,
        end_date_obj=end_date_obj,
        timeframes=timeframes,
        enrich_only=args.enrich_only,
        delete_aggtrades=args.delete_aggtrades,
    )


if __name__ == "__main__":
    main()
