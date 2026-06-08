import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
import logging
from bot_module import utils

logger = logging.getLogger("bot_module.compass_adapter")


class CompassFeatureAdapter:
    """
    Adapter for calculating features specific to the Compass Strategy (XGBoost)
    and Oracle Regime Filter. Replicates logic from 'build_compass_dataset.py'.
    """

    def __init__(self):
        pass

    def calculate_oracle_features(
        self, df_kline: pd.DataFrame
    ) -> Optional[pd.DataFrame]:
        """
        Calculates sensors for the Oracle (Amnesia Filter).
        Expects a DataFrame with 'close', 'high', 'low' and DatetimeIndex.
        Returns a DataFrame with ['sensor_memory', 'sensor_news', 'sensor_complexity'].
        """
        if df_kline.empty:
            return None

        df_calc = df_kline.copy()

        # 1. Sensor Memory
        # log returns
        df_calc["log_returns"] = np.log(df_calc["close"] / df_calc["close"].shift(1))
        # rolling std 60 and 1440
        df_calc["volatility_short"] = (
            df_calc["log_returns"].rolling(window=60, min_periods=1).std()
        )
        df_calc["volatility_long"] = (
            df_calc["log_returns"].rolling(window=1440, min_periods=1).std()
        )
        df_calc["sensor_memory"] = df_calc["volatility_short"] / (
            df_calc["volatility_long"] + 1e-9
        )

        # 2. Sensor News (Stub)
        df_calc["sensor_news"] = 0.0

        # 3. Sensor Complexity
        high_low = df_calc["high"] - df_calc["low"]
        high_close = np.abs(df_calc["high"] - df_calc["close"].shift())
        low_close = np.abs(df_calc["low"] - df_calc["close"].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        # ATR 14 ewm alpha=1/14
        atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
        df_calc["sensor_complexity"] = atr / (df_calc["close"] + 1e-9)

        # Fill NaNs
        features = df_calc[["sensor_memory", "sensor_news", "sensor_complexity"]].copy()
        features = features.bfill().ffill().fillna(0.0)

        # Replace infs
        features.replace([np.inf, -np.inf], 0, inplace=True)

        return features.tail(1)  # Return only the latest row

    def calculate_compass_features(
        self,
        df_kline: pd.DataFrame,
        depth_aggregated: Dict[str, Any],
        recent_agg_trades: List[Dict[str, Any]],
    ) -> Optional[Dict[str, float]]:
        """
        Calculates 'Physics of Market' features (Tape + Orderbook).

        Args:
            df_kline: DataFrame with klines (for price range and context).
            depth_aggregated: Result from DataConsumer._aggregate_depth (buckets -5..5).
            recent_agg_trades: List of aggTrades for the last 30 seconds.

        Returns:
            Dictionary with feature values.
        """
        if df_kline.empty:
            return None

        current_candle = df_kline.iloc[-1]
        close_price = float(current_candle["close"])

        # 1. Process Tape (30s)
        tape_buy_vol_usd = 0.0
        tape_sell_vol_usd = 0.0

        # Filter trades for last 30s is handled by caller or we assume input is already filtered?
        # The Implementation Plan said "Adatper ... Aggregating aggTrades for last 30s".
        # We assume recent_agg_trades contains only relevant trades (e.g. last 30s) passed by Strategy.

        for trade in recent_agg_trades:
            # Trade format: {'p': price, 'q': qty, 'm': is_buyer_maker, ...}
            try:
                price = float(trade["p"])
                qty = float(trade["q"])
                is_buyer_maker = trade[
                    "m"
                ]  # True = Sell (Taker Sell), False = Buy (Taker Buy)
                notional = price * qty

                if is_buyer_maker:
                    tape_sell_vol_usd += notional
                else:
                    tape_buy_vol_usd += notional
            except (KeyError, ValueError):
                continue

        tape_delta_usd = tape_buy_vol_usd - tape_sell_vol_usd

        # 2. Process Orderbook (Depth)
        # DataConsumer._aggregate_depth returns {'bids': [{'percentage': -1, 'notional': ...}, ...], 'asks': ...}
        # But wait, looking at _aggregate_depth in snippet:
        # return {'bids': sorted(aggregated_bids...), 'asks': sorted(aggregated_asks...)}
        # Each record: {'percentage': p, 'depth': notional, 'notional': notional, 'avg_price': ...}

        # Convert to dictionary for easy access
        bids_buckets = {
            item["percentage"]: item["notional"]
            for item in depth_aggregated.get("bids", [])
        }
        asks_buckets = {
            item["percentage"]: item["notional"]
            for item in depth_aggregated.get("asks", [])
        }

        # bids_1p = bucket -1. asks_1p = bucket 1.
        bids_1p = bids_buckets.get(-1, 0.0)
        asks_1p = asks_buckets.get(1, 0.0)

        # bids_5p = sum(-1 to -5), asks_5p = sum(1 to 5)
        bids_5p = sum(bids_buckets.get(p, 0.0) for p in [-1, -2, -3, -4, -5])
        asks_5p = sum(asks_buckets.get(p, 0.0) for p in [1, 2, 3, 4, 5])

        # Avoid division by zero
        bids_1p = max(bids_1p, 1.0)
        asks_1p = max(asks_1p, 1.0)
        bids_5p = max(bids_5p, 1.0)
        asks_5p = max(asks_5p, 1.0)

        # 3. Calculate Features
        features = {}

        # Pressure
        features["pressure_buy"] = tape_buy_vol_usd / asks_1p
        features["pressure_sell"] = tape_sell_vol_usd / bids_1p

        # Absorption
        # price_range = (high - low) / close
        high = float(current_candle["high"])
        low = float(current_candle["low"])
        price_range = (high - low) / close_price if close_price > 1e-9 else 0.001

        absorption_raw = (tape_buy_vol_usd + tape_sell_vol_usd) / (price_range + 1e-6)
        features["absorption"] = np.log1p(absorption_raw)

        # Path Resistance
        features["path_resistance"] = bids_5p / (asks_5p + 1e-9)

        # OBI 1P
        features["obi_1p"] = (bids_1p - asks_1p) / (bids_1p + asks_1p)

        # Delta Wall Divergence
        features["delta_wall_divergence"] = np.sign(tape_delta_usd) * features["obi_1p"]

        # Scalper NATR
        # Need to ensure 'natr' is in df_kline. We can use utils to calculate if missing.
        # But ideally the strategy ensures it's updated.
        features["scalper_natr"] = float(current_candle.get("natr", 0.0))

        # Relative Volume
        # Need 'relative_volume' in df_kline.
        features["relative_volume"] = float(current_candle.get("relative_volume", 1.0))

        return features

    def calculate_scalper_natr_for_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Helper to append NATR to dataframe using utils."""
        return utils.calculate_scalper_natr(df)

    def calculate_relative_volume_for_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Helper to append RelVol to dataframe using utils."""
        return utils.add_relative_volume(df)
