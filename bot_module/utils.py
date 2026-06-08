# bot_module/utils.py
import logging
import pandas as pd
import numpy as np
from typing import Optional
from decimal import Decimal, ROUND_DOWN, InvalidOperation, Context

logger = logging.getLogger("bot_module.utils")
if not logging.getLogger("bot_module").hasHandlers():
    logging.basicConfig(level=logging.WARNING)
    logger.warning(
        "Root logger 'bot_module' has no handlers. Basic config applied to utils logger."
    )


def round_dynamic(value: float, tick_size: float) -> float:
    """
    Rounds the value DOWN to the nearest multiple of tick_size.
    Example: round_dynamic(55.6, 0.5) -> 55.5
             round_dynamic(123.45, 0.1) -> 123.4
    """
    if not isinstance(tick_size, (int, float)) or tick_size <= 0:
        if tick_size != 0:
            logger.warning(
                f"Invalid or non-positive tick_size: {tick_size}. Returning original value: {value}"
            )
        return value
    try:
        value_dec = Decimal(str(value))
        tick_dec = Decimal(str(tick_size))

        # Use division, floor rounding, and multiplication
        # Set sufficient precision for intermediate calculations
        ctx = Context(
            prec=max(value_dec.adjusted(), tick_dec.adjusted())
            + abs(tick_dec.as_tuple().exponent)
            + 5
        )
        if tick_dec == 0:
            return float(value_dec)  # Protection against division by zero

        # Round the division result DOWN to an integer
        multiple = ctx.divide(value_dec, tick_dec).to_integral_value(
            rounding=ROUND_DOWN
        )
        rounded_value = multiple * tick_dec

        return float(rounded_value)
    except (InvalidOperation, TypeError) as e:
        logger.error(
            f"Error rounding value '{value}' (type: {type(value)}) with tick_size {tick_size}: {e}"
        )
        return value
    except Exception as e:
        logger.error(
            f"Unexpected error rounding {value} with tick_size {tick_size}: {e}"
        )
        return value


def round_qty_by_step(
    quantity: float, step_size: float, rounding_mode: str = ROUND_DOWN
) -> float:
    """
    Rounds a quantity according to the step size using Decimal.
    Args:
        quantity: The quantity to round.
        step_size: The step size for the quantity.
        rounding_mode: ROUND_DOWN, ROUND_UP, etc. from Decimal.
    Returns:
        Rounded quantity.
    """
    if not isinstance(step_size, (int, float)) or step_size <= 0:
        if step_size != 0:  # Allow step_size = 0 for no rounding
            logger.warning(
                f"Invalid or non-positive step_size: {step_size}. Returning original quantity: {quantity}"
            )
        return quantity
    if not isinstance(quantity, (int, float)):
        logger.warning(
            f"Input quantity is not numeric ({type(quantity)}). Returning original quantity."
        )
        return quantity

    try:
        quantity_dec = Decimal(str(quantity))
        step_dec = Decimal(str(step_size))

        if step_dec == Decimal(
            0
        ):  # Avoid division by zero if step_size is effectively zero
            return float(quantity_dec)

        # Quantize the quantity based on the step size
        # This effectively means: floor(quantity / step_size) * step_size for ROUND_DOWN
        quantized_multiple = (quantity_dec / step_dec).to_integral_value(
            rounding=rounding_mode
        )
        rounded_qty_dec = quantized_multiple * step_dec

        return float(rounded_qty_dec)
    except (InvalidOperation, TypeError) as e:
        logger.error(
            f"Error rounding quantity {quantity} with step_size {step_size}: {e}"
        )
        return quantity
    except Exception as e_other:
        logger.error(
            f"Unexpected error rounding quantity {quantity} with step_size {step_size}: {e_other}",
            exc_info=True,
        )
        return quantity


# PRICE ROUNDING FUNCTION
def round_price_by_tick(
    price: Optional[float], tick_size: Optional[float], rounding_mode: str = ROUND_DOWN
) -> Optional[float]:
    """
    Rounds the price according to the tick size using Decimal.
    Args:
        price: Price to round.
        tick_size: Price step (tick size).
        rounding_mode: Rounding mode (ROUND_DOWN, ROUND_UP, etc.).
    Returns:
        Rounded price or None on error/invalid inputs.
    """
    # Input data validation
    if price is None:
        logger.warning("Input price is None for rounding. Returning None.")
        return None
    if tick_size is None:
        # logger_utils.debug(f"Tick size is None for price {price}. Returning original price.") # Can do debug
        return price  # Return as is if tick is not specified
    if not isinstance(tick_size, (int, float)) or tick_size <= 0:
        logger.warning(
            f"Invalid or non-positive tick_size: {tick_size} for price {price}. Returning original price."
        )
        return price
    # Allow integers as well as floats for price
    if not isinstance(price, (int, float)):
        logger.warning(
            f"Input price is not numeric ({type(price)}). Returning original price."
        )
        return price

    try:
        price_dec = Decimal(str(price))
        tick_dec = Decimal(str(tick_size))

        # Use quantize to round to the tick step
        # Divide by step, round to integer, multiply by step
        quantized_multiple = (price_dec / tick_dec).to_integral_value(
            rounding=rounding_mode
        )
        rounded_dec = quantized_multiple * tick_dec

        return float(rounded_dec)
    except (InvalidOperation, TypeError) as e:
        logger.error(f"Error rounding price {price} with tick_size {tick_size}: {e}")
        return price  # Return the original in case of a rounding error
    except Exception as e_other:
        logger.error(
            f"Unexpected error rounding price {price} with tick_size {tick_size}: {e_other}",
            exc_info=True,
        )
        return price


def calculate_atr(df: pd.DataFrame, period: int = 14) -> Optional[pd.Series]:
    """
    Calculates ATR using pandas_ta and returns a Series,
    aligned with the index of the original DataFrame.
    """
    required_cols = ["high", "low", "close"]
    if df is None or df.empty:
        logger.debug(
            f"Cannot calculate ATR({period}): Input DataFrame is None or empty."
        )
        return None
    if not all(col in df.columns for col in required_cols):
        logger.warning(
            f"Cannot calculate ATR({period}): Missing required columns {required_cols}."
        )
        return None
    if len(df) < period:
        logger.debug(
            f"Cannot calculate ATR({period}): Insufficient data rows ({len(df)} < {period})."
        )
        return None

    try:
        import pandas_ta  # noqa: F401
    except ImportError:
        logger.error(
            "Library 'pandas_ta' not found. Cannot calculate ATR. Install it: pip install pandas_ta"
        )
        return None

    try:
        df_copy = df.copy()
        for col in required_cols:
            # Attempt to convert to numeric type, replace errors with NaN
            df_copy[col] = pd.to_numeric(df_copy[col], errors="coerce")

        nan_counts_before = df_copy[required_cols].isnull().sum()
        if nan_counts_before.sum() > 0:
            logger.warning(
                f"NaN values found before ATR({period}) calculation: High={nan_counts_before['high']}, Low={nan_counts_before['low']}, Close={nan_counts_before['close']}. Dropping rows with NaNs in HLC."
            )
            # Remove rows with NaN only in the required columns
            df_copy.dropna(subset=required_cols, inplace=True)

        if df_copy.empty or len(df_copy) < period:
            logger.warning(
                f"Not enough valid data points for ATR({period}) after NaN removal ({len(df_copy)} < {period})."
            )
            return None

        # Calculate ATR
        atr_series_calculated = df_copy.ta.atr(length=period, mamode="rma")

        if atr_series_calculated is None or atr_series_calculated.empty:
            logger.error(
                f"pandas_ta.atr calculation failed or returned empty Series for ATR({period})."
            )
            return None

        # Create Series with the original index for the result
        result_series = pd.Series(np.nan, index=df.index, name=f"ATR_{period}")
        # Update with values from ATR calculation (index alignment)
        result_series.update(atr_series_calculated)

        # Fill NaN at the beginning and possible NaN at the end
        initial_nans = result_series.isnull().sum()
        if initial_nans > 0:
            result_series = result_series.bfill()  # Forward fill
            result_series = result_series.ffill()  # Backward fill
            result_series = result_series.fillna(
                0.0
            )  # Fill remaining (if the entire column was NaN) with 0

        # Check for zero or negative ATR values
        invalid_atr_count = (result_series <= 1e-9).sum()
        if invalid_atr_count > 0:
            logger.warning(
                f"Found {invalid_atr_count} zero or negative ATR values after calculation and fillna for period {period}. Check data quality."
            )

        return result_series

    except Exception as e:
        logger.error(f"Error calculating ATR({period}): {e}", exc_info=True)
        return None


def add_relative_volume(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """
    Calculates and adds the 'relative_volume' column to the Klines DataFrame.

    Args:
        df: DataFrame with Klines (must contain 'volume' column and DatetimeIndex).
        period: Period for calculating the moving average volume.

    Returns:
        DataFrame with the added 'relative_volume' column.
        Returns the original DataFrame unchanged if calculation is not possible.
    """
    if df is None or df.empty or "volume" not in df.columns:
        logger.warning(
            "Cannot add relative volume: DataFrame is empty or missing 'volume' column."
        )
        return df
    if not isinstance(df.index, pd.DatetimeIndex):
        logger.warning(
            "Cannot add relative volume: DataFrame index is not DatetimeIndex."
        )
        return df
    if len(df) < period:
        logger.warning(
            f"Cannot add relative volume: Not enough data ({len(df)}) for period {period}. Returning original df with default value."
        )
        if "relative_volume" not in df.columns:
            df["relative_volume"] = 1.0
        return df

    try:
        # Ensure volume is numeric
        if not pd.api.types.is_numeric_dtype(df["volume"]):
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
            df.dropna(
                subset=["volume"], inplace=True
            )  # Remove rows where volume was not converted

        if df.empty or len(df) < period:
            logger.warning(
                f"Not enough valid volume data for relative volume calculation (period {period}). Returning original df."
            )
            if "relative_volume" not in df.columns:
                df["relative_volume"] = 1.0
            return df

        # Sort just in case (although data is usually already sorted)
        if not df.index.is_monotonic_increasing:
            df = df.sort_index()

        # Calculate moving average
        # Use min_periods=period to avoid incomplete calculations at the beginning
        df["avg_volume"] = (
            df["volume"].rolling(window=period, min_periods=period).mean().shift(1)
        )

        # Calculate relative volume, handling division by zero and NaN
        df["relative_volume"] = np.where(
            df["avg_volume"].notna() & (df["avg_volume"] > 1e-9),
            df["volume"] / df["avg_volume"],
            1.0,
        )

        # Fill NaN at the beginning (due to min_periods) with the default value
        df["relative_volume"] = df["relative_volume"].fillna(1.0)

        # Delete temporary column
        if "avg_volume" in df.columns:
            del df["avg_volume"]

        logger.debug(f"Successfully added 'relative_volume' column (period={period}).")
        return df

    except Exception as e:
        logger.error(
            f"Error calculating relative volume (period={period}): {e}", exc_info=True
        )
        # In case of an error, return the DataFrame without this column (or with a default one)
        if "relative_volume" not in df.columns:
            df["relative_volume"] = 1.0
        if "avg_volume" in df.columns:
            del df["avg_volume"]  # Remove temporary column
        return df


def calculate_scalper_natr(df: pd.DataFrame, period: int = 30) -> pd.DataFrame:
    """
    Calculates "scalper" NATR as the average percentage range of a candle over N periods.
    This logic reacts quickly to changes in volatility, unlike the classic ATR.

    Args:
        df: DataFrame with Klines (must contain 'high', 'low', 'close').
        period: Period for calculating the moving average.

    Returns:
        DataFrame with the added 'natr' column.
    """
    if (
        df is None
        or df.empty
        or not all(c in df.columns for c in ["high", "low", "close"])
    ):
        logger.warning("Unable to calculate NATR: required HLC columns are missing.")
        if "natr" not in df.columns:
            df["natr"] = 0.0
        return df

    try:
        # 1. Calculate the range of each candle as a percentage of the closing price
        # Use np.where for safe division to avoid errors with zero price
        df["__percent_range"] = np.where(
            df["close"] > 1e-9, ((df["high"] - df["low"]) / df["close"]) * 100, 0.0
        )

        # 2. Calculate the simple moving average of these percentage ranges
        df["natr"] = df["__percent_range"].rolling(window=period, min_periods=1).mean()

        # 3. Fill possible gaps at the beginning of the data
        df["natr"] = df["natr"].bfill().ffill().fillna(0.0)

        # 4. Remove the temporary auxiliary column
        del df["__percent_range"]

        logger.debug(
            f"Successfully calculated 'natr' column using scalper methodology (period={period})."
        )

    except Exception as e:
        logger.error(f"Error calculating scalper NATR: {e}", exc_info=True)
        if "natr" not in df.columns:
            df["natr"] = 0.0  # In case of an error, add a column with zeros
        if "__percent_range" in df.columns:
            del df["__percent_range"]

    return df


def add_volume_percentile_rank(
    df: pd.DataFrame, period: int = 1000, percentile: int = 90
) -> pd.DataFrame:
    """
    Calculates and adds two columns:
    1. 'volume_percentile_threshold': Volume threshold value for a given percentile.
    2. 'is_volume_spike': Boolean value, True if the current candle volume is above the threshold.

    Args:
        df: DataFrame with Klines (must contain 'volume').
        period: Period for calculating the rolling percentile.
        percentile: Percentile for determining the threshold (from 0 to 100).

    Returns:
        DataFrame with added columns.
    """
    if df is None or df.empty or "volume" not in df.columns:
        logger.warning(
            "Unable to calculate volume percentile: DataFrame is empty or 'volume' column is missing."
        )
        df["volume_percentile_threshold"] = 0.0
        df["is_volume_spike"] = False
        return df

    if len(df) < period:
        logger.warning(
            f"Insufficient data ({len(df)}) for percentile calculation with period {period}. A smaller period is used."
        )

    try:
        # 1. Calculate the rolling percentile. This will be our dynamic threshold.
        # min_periods=100 (or less) so that there are some values at the beginning
        df["volume_percentile_threshold"] = (
            df["volume"]
            .rolling(window=period, min_periods=min(100, period))
            .quantile(percentile / 100.0)
        )

        # 2. Compare the current candle volume with the threshold calculated on the PREVIOUS candle.
        # This prevents "look-ahead bias" and makes the signal more honest.
        df["is_volume_spike"] = df["volume"] > df["volume_percentile_threshold"].shift(
            1
        )

        # 3. Fill gaps at the beginning
        df["volume_percentile_threshold"] = (
            df["volume_percentile_threshold"].bfill().ffill().fillna(0.0)
        )
        df["is_volume_spike"] = df["is_volume_spike"].fillna(False).astype(bool)

        logger.debug(
            f"Successfully added columns for volume analysis by percentile (period={period}, percentile={percentile})."
        )

    except Exception as e:
        logger.error(f"Error calculating volume percentile: {e}", exc_info=True)
        df["volume_percentile_threshold"] = 0.0
        df["is_volume_spike"] = False

    return df
