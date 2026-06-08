import argparse
import io
import logging
import zipfile
import pandas as pd
import requests
from pathlib import Path
from datetime import datetime
import time

# === CONFIGURATION ===
# If running from 'scripts/' directory, point to the parent's data_storage
LOCAL_DATA_STORAGE_PATH = Path(__file__).resolve().parent.parent / "data_storage"
MARKET_TYPE = "futures"  # or "spot", if needed
BASE_URL = "https://data.binance.vision/data/futures/um/monthly/klines"
COLUMNS = [
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

# Logger setup
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_target_path(symbol: str) -> Path:
    """Returns the path to the kline_1m.parquet file."""
    base_path = Path(LOCAL_DATA_STORAGE_PATH) / "binance" / MARKET_TYPE / symbol.upper()
    base_path.mkdir(parents=True, exist_ok=True)
    return base_path / "kline_1m.parquet"


def download_monthly_kline(session, symbol, year, month):
    """Downloads and processes the archive for one month."""
    date_str = f"{year}-{month:02d}"
    file_name = f"{symbol.upper()}-1m-{date_str}"
    url = f"{BASE_URL}/{symbol.upper()}/1m/{file_name}.zip"

    logger.info(f"Downloading: {url}")

    try:
        response = session.get(url, stream=True)
        if response.status_code == 404:
            logger.warning(
                f"Data not found (404) for {date_str}. The coin might not have existed yet."
            )
            return None
        response.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            csv_name = z.namelist()[0]
            with z.open(csv_name) as f:
                # Read with column names
                df = pd.read_csv(f, names=COLUMNS)

        # 1. Try to convert open_time to numbers.
        # If there was a header (text), it will become NaN.
        df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")

        # 2. Remove rows where open_time became NaN (that was the header)
        df.dropna(subset=["open_time"], inplace=True)

        # Data processing
        df = df[["open_time", "open", "high", "low", "close", "volume"]]

        # Now the conversion will succeed
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df.set_index("open_time", inplace=True)

        # Cast other columns' types
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        return df

    except Exception as e:
        logger.error(f"Error downloading {url}: {e}")
        return None


def save_to_parquet(symbol, new_df):
    """Saves data, merging with existing data"""
    target_path = get_target_path(symbol)

    if target_path.exists():
        logger.info(f"Merging with existing file: {target_path}")
        try:
            existing_df = pd.read_parquet(target_path)
            # Merge
            combined_df = pd.concat([existing_df, new_df])
            # Remove duplicates by index (time), keeping latest data
            combined_df = combined_df[~combined_df.index.duplicated(keep="last")]
            combined_df.sort_index(inplace=True)
        except Exception as e:
            logger.error(f"Error reading old file, overwriting: {e}")
            combined_df = new_df
    else:
        logger.info(f"Creating a new file: {target_path}")
        combined_df = new_df

    # Save
    try:
        combined_df.to_parquet(target_path, engine="pyarrow", compression="snappy")
        logger.info(f"Successfully saved {len(combined_df)} rows for {symbol}")
    except Exception as e:
        logger.error(f"Error saving: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Fast history downloader (Monthly Klines)"
    )
    parser.add_argument(
        "--symbols",
        required=True,
        type=str,
        help="List of coins separated by commas (BTCUSDT,ETHUSDT)",
    )
    parser.add_argument(
        "--start-date",
        required=True,
        type=str,
        help="YYYY-MM-01 (Always the first day of the month)",
    )
    parser.add_argument("--end-date", required=True, type=str, help="YYYY-MM-01")

    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d")

    session = requests.Session()

    for symbol in symbols:
        print(f"\n{'=' * 30}\nProcessing {symbol}\n{'=' * 30}")

        current_date = start_date
        symbol_dfs = []

        while current_date <= end_date:
            df = download_monthly_kline(
                session, symbol, current_date.year, current_date.month
            )
            if df is not None and not df.empty:
                symbol_dfs.append(df)

            # Move to the next month
            if current_date.month == 12:
                current_date = current_date.replace(year=current_date.year + 1, month=1)
            else:
                current_date = current_date.replace(month=current_date.month + 1)

            time.sleep(0.1)  # Politeness to API

        if symbol_dfs:
            logger.info(f"Assembling full DataFrame for {symbol}...")
            full_df = pd.concat(symbol_dfs)
            full_df.sort_index(inplace=True)
            save_to_parquet(symbol, full_df)
        else:
            logger.warning(f"Data for {symbol} was not loaded.")


if __name__ == "__main__":
    main()
