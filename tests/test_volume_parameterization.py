# tests/test_volume_parameterization.py
import pytest
import pandas as pd
from datetime import datetime, timezone
from bot_module import strategy as strategy_module
from bot_module.strategy import VisualBuilderStrategy, BaseStrategy
from bot_module.depthsight_backtester import DepthSightBacktester


def create_mock_klines(num_candles=200, volume_val=100.0):
    now = pd.Timestamp.now(tz="UTC")
    index = pd.to_datetime(
        [now - pd.Timedelta(minutes=i) for i in range(num_candles - 1, -1, -1)]
    )
    df = pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": volume_val,
            "relative_volume": 1.0,
            "is_volume_spike": False,
        },
        index=index,
    )
    return df


@pytest.fixture
def market_data():
    df = create_mock_klines()
    return {"kline_1m": df}


@pytest.fixture
def pair_info():
    return {
        "symbol": "TESTUSDT",
        "candle_timeframe": "1m",
        "current_candle_index": 150,
        "last_price": 100.0,
        "atr": 1.0,
        "timestamp_dt": datetime.now(timezone.utc),
        "tick_size": 0.01,
        "relative_volume": 1.0,
        "is_volume_spike": False,
    }


class TestVolumeParameterization:
    def test_rel_vol_filter_custom_lookback(self, market_data, pair_info):
        """Checks that rel_vol_filter uses a custom calculation period."""
        # Setting up data:
        # The last candle (150) has a volume of 500
        # Previous 5 candles have a volume of 100 (average 100, rel_vol=5)
        # Previous 50 candles have a volume of 1000 (average 1000, rel_vol=0.5)
        df = market_data["kline_1m"].copy()
        df.iloc[150, df.columns.get_loc("volume")] = 500.0
        df.iloc[145:150, df.columns.get_loc("volume")] = 100.0
        df.iloc[100:145, df.columns.get_loc("volume")] = 1000.0
        market_data["kline_1m"] = df

        # 1. Test with lookback=5 (should pass, because 500/100 = 5 > 2)
        params_pass = {"lookback_period": 5, "rel_vol_threshold": 2.0}
        strat = VisualBuilderStrategy({"config": {}})
        passed, details = strat._check_filter_rel_vol(
            pair_info, market_data, params_pass, {}
        )
        assert passed is True
        assert details["relative_volume"] == 5.0

        # 2. Test with lookback=50 (should fail because the average will be high)
        params_fail = {"lookback_period": 50, "rel_vol_threshold": 2.0}
        passed, details = strat._check_filter_rel_vol(
            pair_info, market_data, params_fail, {}
        )
        assert passed is False
        assert details["relative_volume"] < 1.0

    def test_volume_confirmation_custom_params(self, market_data, pair_info):
        """Checks the volume_confirmation block with a custom multiplier and period."""
        df = market_data["kline_1m"].copy()
        df.iloc[150, df.columns.get_loc("volume")] = 300.0
        df.iloc[140:150, df.columns.get_loc("volume")] = 100.0
        market_data["kline_1m"] = df

        strat = VisualBuilderStrategy({"config": {}})

        # With multiplier 2.5 (300 > 100 * 2.5) -> True
        params_pass = {"lookback_period": 10, "multiplier": 2.5}
        passed, details = strat._check_foundation_volume_confirmation_wrapper(
            pair_info, market_data, params_pass, {}
        )
        assert passed is True
        assert details["multiplier"] == 2.5

        # With multiplier 3.5 (300 < 100 * 3.5) -> False
        params_fail = {"lookback_period": 10, "multiplier": 3.5}
        passed, details = strat._check_foundation_volume_confirmation_wrapper(
            pair_info, market_data, params_fail, {}
        )
        assert passed is False

    def test_backtester_warmup_adjustment(self):
        """Checks that the backtester sees the custom lookback and takes it into account during warmup."""
        strategy_json = {
            "strategy_name": "VisualBuilderStrategy",
            "entryConditions": {
                "type": "AND",
                "children": [
                    {"type": "volume_confirmation", "params": {"lookback_period": 123}}
                ],
            },
        }

        # To avoid creating the entire complex Backtester object with all arguments,
        # let's directly check the indicator collection method by creating a minimal mock

        bt = object.__new__(DepthSightBacktester)
        bt.base_timeframe = "1m"

        # Checking which indicators it found
        indicators = {}
        bt._recursively_find_indicators_in_json(strategy_json, indicators)

        assert "VOL_LOOKBACK_123" in indicators
        assert indicators["VOL_LOOKBACK_123"]["period"] == 123

    def test_base_strategy_foundation_params(self, market_data, pair_info):
        """Checks that BaseStrategy.check_foundations uses parameters from settings."""
        df = market_data["kline_1m"].copy()
        df.iloc[150, df.columns.get_loc("volume")] = 500.0
        df.iloc[140:150, df.columns.get_loc("volume")] = 100.0  # Avg=100
        market_data["kline_1m"] = df

        # Creating a strategy with custom parameters in _instance_params
        # Default multiplier is 1.8, let's set it to 6.0 (500 < 100 * 6.0)
        custom_params = {
            "kline_vol_lookback": 10,
            "kline_vol_multiplier": 6.0,
            "enabled": True,
        }

        class TestStrategy(BaseStrategy):
            NAME = "TestVol"

            def _check_specific_signal_logic(self, p, m, f):
                return None

        strat = TestStrategy(custom_params)
        foundations, trace = strat.check_foundations(pair_info, market_data)

        # volume_confirmation should be False, because 500 < 100 * 6.0
        assert foundations[strategy_module.FOUNDATION_VOLUME_CONFIRMATION] is False

        # Now changing to multiplier 4.0 (500 > 100 * 4.0)
        strat._instance_params["kline_vol_multiplier"] = 4.0
        foundations, trace = strat.check_foundations(pair_info, market_data)
        assert foundations[strategy_module.FOUNDATION_VOLUME_CONFIRMATION] is True

    def test_visual_strategy_warmup_indicators(self):
        """Checks that VisualBuilderStrategy.required_indicators includes volume periods."""
        strategy_json = {
            "filters": {"type": "rel_vol_filter", "params": {"lookback_period": 88}},
            "entryConditions": {
                "type": "volume_confirmation",
                "params": {"lookback_period": 99},
            },
        }
        strat = VisualBuilderStrategy({"config": strategy_json})
        required = strat.required_indicators

        assert "VOL_LOOKBACK_88" in required
        assert "VOL_LOOKBACK_99" in required
        # Live DataConsumer computes 'relative_volume' only for RELATIVE_VOLUME;
        # without it the filter falls back to the 1.0 default and rejects everything.
        assert "RELATIVE_VOLUME" in required

    def test_visual_strategy_market_activity_requires_volume_spike(self):
        """market_activity default percentile mode reads pair_info['is_volume_spike']."""
        strategy_json = {"filters": {"type": "market_activity", "params": {}}}
        strat = VisualBuilderStrategy({"config": strategy_json})
        required = strat.required_indicators

        assert "RELATIVE_VOLUME" in required
        assert "IS_VOLUME_SPIKE" in required
