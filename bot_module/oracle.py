import pandas as pd
import numpy as np
import joblib
from pathlib import Path
from typing import Tuple, Optional
import warnings

# Ignore warnings from sklearn for clean output
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)


class Oracle:
    def __init__(self, model_path: Path):
        """
        Initializes the Oracle, loading the trained GMM model.
        """
        if not model_path.exists():
            raise FileNotFoundError(f"Oracle Model not found at path: {model_path}")
        self.model = joblib.load(model_path)
        self._cached_regime: Optional[Tuple[int, float]] = None
        self._last_kline_timestamp: Optional[int] = None
        print(f"[Oracle] Oracle Model successfully loaded from {model_path}")

    def engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Creates "sensors" for the Oracle. This is the heart of our mechanism.
        Logic is copied from train_oracle.py.
        """
        df = df.copy()

        if not isinstance(df.index, pd.DatetimeIndex):
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df.set_index("timestamp")
            df = df.sort_index()

        # Sensor #1: "Memory" (The Forgetting Speed)
        short_window_vol = 60
        long_window_vol = 1440

        log_returns = np.log(df["close"] / df["close"].shift(1))
        df["volatility_short"] = log_returns.rolling(window=short_window_vol).std()
        df["volatility_long"] = log_returns.rolling(window=long_window_vol).std()

        df["sensor_memory"] = df["volatility_short"] / (df["volatility_long"] + 1e-9)

        # Sensor #2: "News Background" (The News Asymmetry)
        news_window = 720

        # Check for the presence of sentiment columns
        required_sentiment_cols = ["positive", "negative", "important"]
        if all(col in df.columns for col in required_sentiment_cols):
            df["sentiment_score"] = (df["positive"] - df["negative"]) * (
                df["important"] + 1
            )
            df["sensor_news"] = df["sentiment_score"].rolling(window=news_window).mean()
        else:
            # If there are no columns, create an "empty" sensor with a neutral value of 0
            df["sensor_news"] = 0.0

        # Sensor #3: "Complexity" (The Complexity Drift)
        atr_window = 14

        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())

        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1 / atr_window, adjust=False).mean()

        df["sensor_complexity"] = atr / (df["close"] + 1e-9)

        # Final data preparation
        features_df = df[["sensor_memory", "sensor_news", "sensor_complexity"]].copy()

        features_df = features_df.ffill().bfill()

        features_df.replace([np.inf, -np.inf], np.nan, inplace=True)
        features_df.fillna(0, inplace=True)

        return features_df

    async def get_current_regime(
        self, kline_history: pd.DataFrame
    ) -> Tuple[int, float]:
        """
        Determines the current market regime and Oracle confidence.
        Caches the result, recalculating only when a new closed candle appears.
        """
        if kline_history.empty:
            return -1, 0.0  # Returning "undefined" regime and 0 confidence

        current_kline_timestamp = (
            kline_history.index[-1]
            if isinstance(kline_history.index, pd.DatetimeIndex)
            else kline_history["timestamp"].iloc[-1]
        )

        if (
            self._cached_regime
            and self._last_kline_timestamp == current_kline_timestamp
        ):
            return self._cached_regime

        # To correctly calculate features, we need history,
        # therefore we pass the entire kline_history to engineer_features
        features_df = self.engineer_features(kline_history)

        # Take only the last row with features for prediction
        latest_features = features_df.iloc[[-1]][
            ["sensor_memory", "sensor_news", "sensor_complexity"]
        ]

        if latest_features.isnull().values.any():
            print(
                "[Oracle] NaN detected in the latest features. Returning undefined regime."
            )
            self._cached_regime = (-1, 0.0)
            self._last_kline_timestamp = current_kline_timestamp
            return self._cached_regime

        # Get probabilities for each regime
        probabilities = self.model.predict_proba(latest_features)[0]

        # Find the regime with the maximum probability
        max_probability_index = np.argmax(probabilities)
        max_confidence = probabilities[max_probability_index] * 100  # In percent

        self._cached_regime = (int(max_probability_index), float(max_confidence))
        self._last_kline_timestamp = current_kline_timestamp

        return self._cached_regime
