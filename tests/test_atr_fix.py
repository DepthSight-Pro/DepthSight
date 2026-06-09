# tests/test_atr_fix.py
import pytest
import pandas as pd
import numpy as np
from unittest.mock import AsyncMock

# Importing classes from your modules
from bot_module.genetic_adapter import GeneticCompatibleStrategy
from bot_module.data_consumer import DataConsumer

# --- Fixtures & Data Generation ---


@pytest.fixture
def sample_strategy_config():
    """Strategy config that previously caused an error."""
    return {
        "id": "test_strat",
        "name": "ATR Test Strategy",
        "config": {
            "entryConditions": {
                "type": "stoch_condition",
                "params": {"k_period": 14, "operator": "gt", "value": 0},
            },
            "initialization": {
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "atr_multiplier",
                    "sl_value": 2.0,
                    "tp_type": "rr_multiplier",
                    "tp_value": 2.0,
                },
            },
        },
    }


def create_mock_candles(length=50):
    """Generates OHLCV data."""
    dates = pd.date_range(end=pd.Timestamp.now(), periods=length, freq="5min")
    data = {
        "open": np.linspace(100, 110, length),
        "high": np.linspace(101, 111, length),
        "low": np.linspace(99, 109, length),
        "close": np.linspace(100.5, 110.5, length),
        "volume": np.random.rand(length) * 1000,
        "open_time": dates,
    }
    df = pd.DataFrame(data)
    df.set_index("open_time", inplace=True)
    return df


# --- TESTS ---


@pytest.mark.asyncio
async def test_strategy_requests_atr_automatically(sample_strategy_config):
    """
    Checks that the Strategy adds ATR_14 to the list of required indicators.
    """
    strategy = GeneticCompatibleStrategy(sample_strategy_config)
    req_indicators = strategy.required_indicators

    print(f"\n[TEST 1] Required indicators found: {req_indicators}")

    assert "ATR_14" in req_indicators, (
        "ERROR: Strategy did NOT add ATR_14 to the list of required indicators!"
    )


@pytest.mark.asyncio
async def test_data_consumer_saves_atr_key(sample_strategy_config):
    """
    Checks that DataConsumer saves a copy of ATR under the 'atr' key.
    """
    symbol = "TESTUSDT"
    timeframe = "5m"

    executor_mock = AsyncMock()
    consumer = DataConsumer(executor=executor_mock)
    consumer._required_metrics[symbol] = {"ATR_14"}

    df = create_mock_candles(50)
    consumer.get_kline_history = AsyncMock(return_value=df)
    consumer._active_pairs[symbol] = {"symbol": symbol, "last_price": 100.0}

    await consumer._recalculate_kline_indicators(symbol, timeframe)

    pair_data = consumer._active_pairs[symbol]
    print(f"\n[TEST 2] Keys in pair_data after recalc: {list(pair_data.keys())}")

    # 1. Checking raw calculation (could be atr_ or atrr_)
    has_atr_raw = any(k.startswith(("atr_", "atrr_")) for k in pair_data.keys())
    assert has_atr_raw, (
        "ERROR: DataConsumer did not calculate ATR (no atr_ or atrr_ keys)!"
    )

    # 2. Checking for the presence of the universal 'atr' key (Our fix)
    assert "atr" in pair_data, (
        "ERROR: Key 'atr' is missing! DataConsumer did not copy the value."
    )

    assert pair_data["atr"] is not None and pair_data["atr"] > 0


@pytest.mark.asyncio
async def test_integration_signal_generation(sample_strategy_config):
    """
    Integration test:
    Checks that check_signal does not crash when attempting to calculate stop-loss.
    """
    strategy = GeneticCompatibleStrategy(sample_strategy_config)

    # Manually create pair_info, simulating what the Fixed DataConsumer should output
    pair_info = {
        "symbol": "TESTUSDT",
        "timestamp_dt": pd.Timestamp.now(),
        "current_candle_index": 100,
        "candle_timeframe": "5m",
        "last_price": 100.0,
        "tick_size": 0.01,
        "atr": 1.5,
        "ATR_14": 1.5,
        "STOCHk_14_3_3": 10,
        "STOCHd_14_3_3": 5,
    }

    market_data = {"kline_5m": create_mock_candles(100)}

    # Attempting to get a signal
    try:
        signal, weight, trace = await strategy.check_signal(pair_info, market_data)

        print(f"\n[TEST 3] Signal Result: {signal}")
        if signal:
            print(f"  SL: {signal.stop_loss}")
            print(f"  TP: {signal.take_profit}")

        # If we are here and no error occurred - the test is half passed
        # Now let's check if the stop was calculated
        if signal:
            expected_sl_dist = 1.5 * 2.0  # atr * sl_value
            actual_sl_dist = abs(100.0 - signal.stop_loss)
            # Taking tick rounding into account
            assert abs(actual_sl_dist - expected_sl_dist) < 0.02, (
                "Stop-loss calculated incorrectly!"
            )

    except Exception as e:
        pytest.fail(f"ERROR during signal generation: {e}")


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main(["-v", __file__]))
