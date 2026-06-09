# tests/test_real_oracle_integration.py

import pytest
import pandas as pd
import numpy as np
import joblib
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from sklearn.mixture import GaussianMixture

# Import classes
from bot_module.depthsight_backtester import DepthSightBacktester
from bot_module.strategy import StrategySignal, SignalDirection, OrderMode


# --- Fixtures (remain unchanged) ---
@pytest.fixture(scope="module")
def mock_model_file_path(tmp_path_factory) -> Path:
    tmp_dir = tmp_path_factory.mktemp("real_oracle_model")
    model_path = tmp_dir / "oracle_model.joblib"
    dummy_model = GaussianMixture(n_components=3, random_state=42)
    dummy_model.fit(np.random.rand(100, 3))
    joblib.dump(dummy_model, model_path)
    print(f"Real temporary model file created: {model_path}")
    return model_path


@pytest.fixture
def mock_config_with_oracle_path(mock_model_file_path):
    config = MagicMock()
    config.ORACLE_MODEL_PATH = str(mock_model_file_path)
    config.LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    config.DEFAULT_TICK_SIZE = 0.01
    config.MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD = 50.0
    config.FOUNDATION_WEIGHTS = {"market_activity": 100.0}
    config.STRATEGY_SYMBOL_RISK_MULTIPLIERS = [1.0, 0.75, 0.5, 0.25, 0.0]
    config.SYMBOL_COOLDOWN_SECONDS = 300.0
    return config


@pytest.fixture
def kline_data_for_oracle_test():
    """
    Generates a more realistic test DataFrame where SL will not trigger immediately.
    """
    num_periods = 200
    # Create a baseline price
    base_price = np.linspace(100, 110, num_periods)

    # Create OHLC with small deviations from the baseline
    df = pd.DataFrame(
        {
            "open": base_price - 0.1,
            "high": base_price + 0.2,
            "low": base_price - 0.2,
            "close": base_price,
            "volume": 100,
            "positive": 1,
            "negative": 1,
            "important": 0,
        },
        index=pd.to_datetime(
            pd.date_range(
                start="2023-01-01 12:00", periods=num_periods, freq="min", tz="UTC"
            )
        ),
    )

    return df


# --- "Bulletproof" test (fixed version) ---


@pytest.mark.asyncio
async def test_backtester_loads_and_uses_real_oracle_for_filtering(
    mock_config_with_oracle_path, kline_data_for_oracle_test
):
    # Arrange (Preparation)
    mock_gmm_model = MagicMock(spec=GaussianMixture)

    def predict_proba_side_effect(features):
        # `features` is a DataFrame with a single row having a DatetimeIndex.
        # We can just check the time!
        current_timestamp = features.index[0]

        flat_proba = np.array([[0.1, 0.8, 0.1]])  # Mode 1 (Flat, forbidden)
        trend_proba = np.array([[0.8, 0.1, 0.1]])  # Mode 0 (Trend, allowed)

        # Allow a trade only on a candle where the minute is 45
        if current_timestamp.minute == 45:
            print(
                f"TEST_DEBUG: Oracle returns TREND regime (0) for timestamp {current_timestamp}"
            )
            return trend_proba
        else:
            return flat_proba

    mock_gmm_model.predict_proba.side_effect = predict_proba_side_effect

    # Create a mock instance that the backtester will return
    mock_strategy_instance = AsyncMock()

    # Creating a dynamic signal ---
    def dynamic_signal_side_effect(pair_info, market_data, prev_pair_info):
        """This function will be called instead of check_signal and generate a signal with targets relative to the current price."""
        current_price = pair_info["last_price"]
        signal = StrategySignal(
            strategy_name="Test",
            symbol="ORCLTEST",
            direction=SignalDirection.LONG,
            trigger_price=current_price,
            stop_loss=current_price * 0.99,
            take_profit=current_price * 1.03,
            mode=OrderMode.MARKET,
            risk_pct=0.01,
        )
        return (signal, 100, {})

    # Use .side_effect instead of .return_value
    mock_strategy_instance.check_signal.side_effect = dynamic_signal_side_effect
    mock_strategy_instance.check_fast_foundations.return_value = ({}, None)

    with (
        patch("joblib.load", return_value=mock_gmm_model) as mock_joblib_load,
        patch(
            "bot_module.depthsight_backtester.DepthSightBacktester._initialize_strategy",
            return_value=mock_strategy_instance,
        ) as mock_init_strategy,
    ):
        strategy_params = {"oracle_regime": 0, "oracle_confidence": 70.0}
        bt = DepthSightBacktester(
            strategy_name="TestStrategy",  # Name is not important since initialization is mocked
            symbol="ORCLTEST",
            params=strategy_params,
            historical_data={"kline_1m": kline_data_for_oracle_test},
            initial_balance=10000.0,
            min_trades_required=0,
            risk_params={"risk_pct_per_trade": 0.01},
            backtest_risk_params={"risk_pct_per_trade": 0.01},
            execution_config={"commission_pct": 0.0, "slippage_pct": 0.0},
            strategy_defaults={},
            ml_training_config={},
            ml_sim_log_path=None,
            exchange_info={
                "tick_size": 0.01,
                "lot_params": {"stepSize": "0.001"},
                "min_notional": 10.0,
            },
            _config_override=mock_config_with_oracle_path,
        )

        # Checking the call with a Path object
        expected_path = Path(mock_config_with_oracle_path.ORACLE_MODEL_PATH)
        mock_joblib_load.assert_called_once_with(expected_path)

        # Ensure that the strategy initialization was "intercepted"
        mock_init_strategy.assert_called_once()
        assert bt.strategy_instance is mock_strategy_instance

        results = await bt.run_async()

    # Assert (Check)
    assert results is not None, "Backtest did not return results"
    assert results["trades"] == 1, "Exactly one trade should have opened"

    trade_entry_time = bt.trade_log[0]["entry_time"]
    print(f"Trade was opened at: {trade_entry_time}")

    # Checking the correct entry time
    assert trade_entry_time.hour == 13 and trade_entry_time.minute == 45, (
        "The trade did not open on the same candle where the Oracle gave permission"
    )
