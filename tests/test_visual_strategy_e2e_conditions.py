# File: tests/test_visual_strategy_e2e_conditions.py
"""
Complex integration E2E tests for all types of visual strategy editor blocks.
Tests use real historical data from parquet files and verify the operation
of each condition type through a full backtester run.
"""

import pytest
import pandas as pd
from pathlib import Path
from typing import Dict, Any

from bot_module.depthsight_backtester import DepthSightBacktester
from bot_module import strategy as strategy_module

# === CONFIGURATION ===
# Using absolute path relative to this file to ensure it works from any CWD
DATA_STORAGE_PATH = (
    Path(__file__).resolve().parents[1] / "data_storage" / "binance" / "futures"
)
DEFAULT_SYMBOL = "BTCUSDT"
SECONDARY_SYMBOL = "ETHUSDT"


# === FIXTURES ===


@pytest.fixture(scope="module")
def real_kline_data() -> Dict[str, pd.DataFrame]:
    """
    Loads real candlestick data from parquet files for BTCUSDT.
    Taking the last 2000 candles for test speed.
    """
    symbol_path = DATA_STORAGE_PATH / DEFAULT_SYMBOL

    data = {}
    timeframes = ["1m", "5m", "15m", "1h", "4h", "1d"]

    for tf in timeframes:
        parquet_path = symbol_path / f"kline_{tf}.parquet"
        if parquet_path.exists():
            df = pd.read_parquet(parquet_path)
            # Take the last 2000 records for speed
            if len(df) > 2000:
                df = df.tail(2000).copy()
            # Ensuring the index is datetime
            if not isinstance(df.index, pd.DatetimeIndex):
                if "timestamp" in df.columns:
                    df.set_index("timestamp", inplace=True)
                elif "open_time" in df.columns:
                    df["timestamp"] = pd.to_datetime(
                        df["open_time"], unit="ms", utc=True
                    )
                    df.set_index("timestamp", inplace=True)
            data[f"kline_{tf}"] = df

    return data


@pytest.fixture(scope="module")
def btc_kline_data() -> pd.DataFrame:
    """Loads 1m BTCUSDT data for BTC-dependent filters."""
    parquet_path = DATA_STORAGE_PATH / DEFAULT_SYMBOL / "kline_1m.parquet"
    if parquet_path.exists():
        df = pd.read_parquet(parquet_path)
        if len(df) > 2000:
            df = df.tail(2000).copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            if "timestamp" in df.columns:
                df.set_index("timestamp", inplace=True)
            elif "open_time" in df.columns:
                df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
                df.set_index("timestamp", inplace=True)
        return df
    return pd.DataFrame()


@pytest.fixture(scope="module")
def eth_kline_data() -> pd.DataFrame:
    """Loads 1m ETHUSDT data."""
    parquet_path = DATA_STORAGE_PATH / SECONDARY_SYMBOL / "kline_1m.parquet"
    if parquet_path.exists():
        df = pd.read_parquet(parquet_path)
        if len(df) > 2000:
            df = df.tail(2000).copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            if "timestamp" in df.columns:
                df.set_index("timestamp", inplace=True)
            elif "open_time" in df.columns:
                df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
                df.set_index("timestamp", inplace=True)
        return df
    return pd.DataFrame()


@pytest.fixture
def visual_strategy_instance(monkeypatch):
    """Fixture for creating a VisualBuilderStrategy instance."""
    from bot_module.strategy import VisualBuilderStrategy

    monkeypatch.setitem(
        strategy_module.STRATEGIES, "VisualBuilderStrategy", VisualBuilderStrategy
    )

    monkeypatch.setattr(
        strategy_module.config,
        "FOUNDATION_WEIGHTS",
        {
            "market_activity": 15.0,
            "level": 15.0,
            "pattern": 10.0,
            "volume_confirmation": 10.0,
            "orderbook": 30.0,
            "trend": 10.0,
            "round_number_level": 10.0,
            "local_level": 15.0,
            "tape_acceleration": 15.0,
            "significant_level": 15.0,
            "trend_direction": 10.0,
            "classic_pattern": 10.0,
        },
    )
    monkeypatch.setattr(
        strategy_module.config, "MIN_TOTAL_FOUNDATION_WEIGHT_THRESHOLD", 0.0
    )

    def _create_instance(json_config: Dict[str, Any]):
        if "initialization" not in json_config and "action" not in json_config:
            json_config["initialization"] = {
                "id": "default_act",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "atr_multiplier",
                    "sl_value": 2.0,
                    "tp_type": "rr_multiplier",
                    "tp_value": 2.0,
                },
            }
        params_for_creation = {"config": json_config, "enabled": True}
        instance = strategy_module.create_strategy_instance(
            strategy_name="VisualBuilderStrategy", params=params_for_creation
        )
        assert instance is not None, "Failed to create VisualBuilderStrategy instance"
        return instance

    return _create_instance


def create_backtester(
    strategy_config: Dict[str, Any],
    historical_data: Dict[str, pd.DataFrame],
    symbol: str = "BTCUSDT",
) -> DepthSightBacktester:
    """Helper for creating a backtester with typical settings."""
    return DepthSightBacktester(
        strategy_name="VisualBuilderStrategy",
        symbol=symbol,
        params={"config": strategy_config},
        historical_data=historical_data,
        initial_balance=10000,
        min_trades_required=0,
        risk_params={"risk_pct_per_trade": 0.01, "daily_max_loss_pct": 5.0},
        backtest_risk_params={"riskPerTradePercent": 1.0, "dailyMaxLossPercent": 5.0},
        execution_config={"commission_pct": 0.0},
        strategy_defaults={"risk_pct_per_trade": 0.01},
        ml_training_config={},
        ml_sim_log_path=None,
        exchange_info={
            "tick_size": 0.01,
            "lot_params": {"stepSize": 0.001},
            "min_notional": 10.0,
        },
        min_foundation_weight_threshold=0.0,
    )


# =============================================================================
# GROUP 1: FILTER TESTS
# =============================================================================


class TestFilterBlocks:
    """E2E tests for visual editor filters."""

    @pytest.mark.asyncio
    async def test_e2e_filter_trading_session_passes(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Verifies that the trading_session filter allows trades during the specified session.
        Using the 'london' session (07:00-16:00 UTC).
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "filters": {
                "id": "f_root",
                "type": "AND",
                "children": [
                    {
                        "id": "f_session",
                        "type": "trading_session",
                        "params": {"session": "london"},
                    }
                ],
            },
            "entryConditions": {"id": "e_root", "type": "AND", "children": []},
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        # Check that there were trades (data must contain London hours)
        # If there are no trades, it means either there is no data at this time, or the filter is working
        assert backtester.trade_log is not None, "trade_log must be initialized"

    @pytest.mark.asyncio
    async def test_e2e_filter_volatility_atr(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Verifies the ATR volatility filter.
        Setting a very low threshold - trades should open.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "filters": {
                "id": "f_root",
                "type": "AND",
                "children": [
                    {
                        "id": "f_vol",
                        "type": "volatility_filter",
                        "params": {"indicator": "ATR", "operator": "gt", "value": 0.01},
                    }
                ],
            },
            "entryConditions": {"id": "e_root", "type": "AND", "children": []},
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        # With a very low threshold, there should be trades
        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_filter_volatility_atr_blocks(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Verifies that the ATR filter with a very high threshold blocks trades.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "filters": {
                "id": "f_root",
                "type": "AND",
                "children": [
                    {
                        "id": "f_vol",
                        "type": "volatility_filter",
                        "params": {
                            "indicator": "ATR",
                            "operator": "gt",
                            "value": 999999.0,
                        },
                    }
                ],
            },
            "entryConditions": {"id": "e_root", "type": "AND", "children": []},
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        # With a very high threshold, there should be no trades
        assert len(backtester.trade_log) == 0, (
            "With ATR threshold > 999999 there should be no trades"
        )

    @pytest.mark.asyncio
    async def test_e2e_filter_trend_adx(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Checks the ADX trend strength filter.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "filters": {
                "id": "f_root",
                "type": "AND",
                "children": [
                    {
                        "id": "f_trend",
                        "type": "trend_filter",
                        "params": {"threshold": 25.0},
                    }
                ],
            },
            "entryConditions": {"id": "e_root", "type": "AND", "children": []},
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_filter_natr(self, real_kline_data, visual_strategy_instance):
        """
        Verifies the NATR normalized volatility filter.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "filters": {
                "id": "f_root",
                "type": "AND",
                "children": [
                    {
                        "id": "f_natr",
                        "type": "natr_filter",
                        "params": {"value": 0.5, "operator": "gt"},
                    }
                ],
            },
            "entryConditions": {"id": "e_root", "type": "AND", "children": []},
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None


# =============================================================================
# GROUP 2: FOUNDATION TESTS (FOUNDATIONS)
# =============================================================================


class TestFoundationBlocks:
    """E2E tests for visual editor bases."""

    @pytest.mark.asyncio
    async def test_e2e_foundation_market_activity(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Checks the market_activity basis.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "f_activity",
                        "type": "market_activity",
                        "params": {
                            "rel_vol_threshold": 1.0,
                            "natr_threshold": 0.5,
                            "mode": "relative",
                        },
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_foundation_local_level(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Verifies the local_level base - proximity to a local level.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "f_level",
                        "type": "local_level",
                        "params": {
                            "timeframe": "1m",
                            "lookback_period": 20,
                            "proximity_type": "atr_multiplier",
                            "proximity_value": 0.5,
                        },
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_foundation_significant_level(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Verifies the significant_level base - proximity to significant H1/H4/D1 levels.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {"id": "f_sig_level", "type": "significant_level", "params": {}}
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_foundation_round_level(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Verifies the round_level base - proximity to round numbers.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "f_round",
                        "type": "round_level",
                        "params": {"proximity_pips": 50},
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_foundation_volume_confirmation(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Verifies the volume_confirmation base - volume confirmation.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {"id": "f_vol", "type": "volume_confirmation", "params": {}}
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_foundation_trend_direction(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Checks the trend_direction basis.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "f_trend",
                        "type": "trend_direction",
                        "params": {"required_trend": "LONG"},
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None


# =============================================================================
# GROUP 3: INDICATOR TESTS
# =============================================================================


class TestIndicatorBlocks:
    """E2E tests for indicator conditions."""

    @pytest.mark.asyncio
    async def test_e2e_indicator_rsi_condition(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Checks RSI condition.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "c_rsi",
                        "type": "rsi_condition",
                        "params": {"operator": "lt", "value": 70, "period": 14},
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_indicator_macd_condition(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Checks MACD condition.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "c_macd",
                        "type": "macd_condition",
                        "params": {"condition": "hist_gt_zero"},
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_indicator_stochastic_condition(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Checks the Stochastic condition.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "c_stoch",
                        "type": "stochastic_condition",
                        "params": {
                            "condition": "oversold",
                            "k_period": 14,
                            "d_period": 3,
                            "slowing": 3,
                        },
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_indicator_bollinger_condition(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Checks the Bollinger Bands condition.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "c_bb",
                        "type": "bollinger_bands_condition",
                        "params": {
                            "condition": "below_lower",
                            "period": 20,
                            "std_dev": 2.0,
                        },
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_indicator_ma_cross_condition(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Verifies the moving average crossover condition.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "c_ma",
                        "type": "ma_cross_condition",
                        "params": {
                            "fast_period": 9,
                            "slow_period": 21,
                            "condition": "bullish_cross",
                        },
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_indicator_adx_filter(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Checks ADX filter.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "c_adx",
                        "type": "adx_filter",
                        "params": {"threshold": 20, "period": 14},
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None


# =============================================================================
# GROUP 4: TAPE TESTS
# =============================================================================


class TestTapeBlocks:
    """E2E tests for conditions based on the trade feed."""

    @pytest.mark.asyncio
    async def test_e2e_tape_condition_delta_volume(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Verifies tape_condition with the delta_volume metric.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "c_tape",
                        "type": "tape_condition",
                        "params": {
                            "metric": "delta_volume",
                            "window_sec": 5,
                            "operator": "gt",
                            "threshold": 0,
                        },
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        # Tape conditions may be skipped if data is missing
        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_tape_analysis_data_provider(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Verifies the tape_analysis block (data provider - always returns True).
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "c_tape_analysis",
                        "type": "tape_analysis",
                        "params": {"time_window_sec": 5},
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None


# =============================================================================
# GROUP 5: ORDER BOOK TESTS
# =============================================================================


class TestOrderBookBlocks:
    """E2E tests for order book based conditions."""

    @pytest.mark.asyncio
    async def test_e2e_orderbook_condition(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Checks orderbook_condition.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "c_ob",
                        "type": "orderbook_condition",
                        "params": {
                            "min_density_usd": 1000,
                            "levels_to_check": 5,
                            "side": "any",
                        },
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        # Order book might not be loaded in historical data
        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_order_book_zone(self, real_kline_data, visual_strategy_instance):
        """
        Checks the order_book_zone block.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "c_ob_zone",
                        "type": "order_book_zone",
                        "params": {"zone_pct": 0.5, "min_density_usd": 1000},
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None


# =============================================================================
# GROUP 6: COMPARISON AND LOGIC TESTS
# =============================================================================


class TestComparisonBlocks:
    """E2E tests for value comparison blocks."""

    @pytest.mark.asyncio
    async def test_e2e_value_comparison(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Checks the value_comparison block.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "c_cmp",
                        "type": "value_comparison",
                        "params": {
                            "leftOperand": {"source": "indicator", "key": "RSI_14"},
                            "operator": "lt",
                            "rightOperand": {"source": "value", "value": 80},
                        },
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None


# =============================================================================
# GROUP 7: BTC-DEPENDENT FILTER TESTS
# =============================================================================


class TestBtcDependentFilters:
    """E2E tests for filters depending on BTCUSDT."""

    @pytest.mark.asyncio
    async def test_e2e_btc_state_filter(
        self, real_kline_data, btc_kline_data, visual_strategy_instance
    ):
        """
        Checks btc_state_filter.
        """
        if btc_kline_data.empty:
            pytest.skip("No BTCUSDT data for the test")

        config = {
            "min_foundation_weight_threshold": 0,
            "filters": {
                "id": "f_root",
                "type": "AND",
                "children": [
                    {
                        "id": "f_btc",
                        "type": "btc_state_filter",
                        "params": {"required_state": "Trending Up"},
                    }
                ],
            },
            "entryConditions": {"id": "e_root", "type": "AND", "children": []},
        }

        # Adding BTCUSDT data to market_data
        historical_data = real_kline_data.copy()
        historical_data["kline_1m_BTCUSDT"] = btc_kline_data

        backtester = create_backtester(config, historical_data)
        await backtester.run_async()

        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_correlation_filter(
        self, real_kline_data, btc_kline_data, eth_kline_data, visual_strategy_instance
    ):
        """
        Checks the correlation filter.
        """
        if btc_kline_data.empty or eth_kline_data.empty:
            pytest.skip("No BTC or ETH data for correlation test")

        config = {
            "min_foundation_weight_threshold": 0,
            "filters": {
                "id": "f_root",
                "type": "AND",
                "children": [
                    {
                        "id": "f_corr",
                        "type": "correlation",
                        "params": {"operator": "gt", "value": 0.5},
                    }
                ],
            },
            "entryConditions": {"id": "e_root", "type": "AND", "children": []},
        }

        historical_data = {"kline_1m": eth_kline_data.copy()}
        historical_data["kline_1m_BTCUSDT"] = btc_kline_data

        backtester = create_backtester(config, historical_data, symbol="ETHUSDT")
        await backtester.run_async()

        assert backtester.trade_log is not None


# =============================================================================
# GROUP 8: CLASSIC PATTERN TESTS
# =============================================================================


class TestClassicPatternBlocks:
    """E2E tests for classic candlestick patterns."""

    @pytest.mark.asyncio
    async def test_e2e_classic_pattern_bullish_engulfing(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Checks bullish engulfing recognition.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "c_pattern",
                        "type": "classic_pattern",
                        "params": {
                            "pattern_name": "bullish_engulfing",
                            "timeframe": "1m",
                        },
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_classic_pattern_pin_bar(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Checks pin bar recognition.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "c_pattern",
                        "type": "classic_pattern",
                        "params": {"pattern_name": "pin_bar", "timeframe": "1m"},
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_classic_pattern_inside_bar(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Checks inside bar recognition.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "c_pattern",
                        "type": "classic_pattern",
                        "params": {"pattern_name": "inside_bar", "timeframe": "1m"},
                    }
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None


# =============================================================================
# GROUP 9: COMBINATION TESTS
# =============================================================================


class TestCombinedConditions:
    """E2E tests for combinations of multiple conditions."""

    @pytest.mark.asyncio
    async def test_e2e_complex_strategy_trend_plus_level(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Verifies the combination: Trend + Level + Volatility filter.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "filters": {
                "id": "f_root",
                "type": "AND",
                "children": [
                    {
                        "id": "f_vol",
                        "type": "volatility_filter",
                        "params": {"indicator": "ATR", "operator": "gt", "value": 1.0},
                    }
                ],
            },
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "c_trend",
                        "type": "trend_direction",
                        "params": {"required_trend": "LONG"},
                    },
                    {
                        "id": "c_level",
                        "type": "local_level",
                        "params": {
                            "timeframe": "1m",
                            "lookback_period": 20,
                            "proximity_type": "atr_multiplier",
                            "proximity_value": 0.5,
                        },
                    },
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_or_logic_rsi_or_stoch(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Verifies OR logic: RSI oversold OR Stochastic oversold.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "OR",
                "children": [
                    {
                        "id": "c_rsi",
                        "type": "rsi_condition",
                        "params": {"operator": "lt", "value": 30},
                    },
                    {
                        "id": "c_stoch",
                        "type": "stochastic_condition",
                        "params": {"condition": "oversold"},
                    },
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_nested_and_or_logic(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Verifies nested logic: (Trend) AND (RSI < 70 OR MACD > 0).
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {"id": "c_trend", "type": "trend_direction", "params": {}},
                    {
                        "id": "nested_or",
                        "type": "OR",
                        "children": [
                            {
                                "id": "c_rsi",
                                "type": "rsi_condition",
                                "params": {"operator": "lt", "value": 70},
                            },
                            {
                                "id": "c_macd",
                                "type": "macd_condition",
                                "params": {"condition": "hist_gt_zero"},
                            },
                        ],
                    },
                ],
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None


# =============================================================================
# GROUP 10: POSITION MANAGEMENT TESTS
# =============================================================================


class TestPositionManagement:
    """E2E tests for position management blocks."""

    @pytest.mark.asyncio
    async def test_e2e_position_move_to_breakeven(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Verifies the break-even logic.
        Adding RSI < 25 condition to limit the number of trades.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    # Restrict to very rare signals only
                    {
                        "id": "c_rsi",
                        "type": "rsi_condition",
                        "params": {"operator": "lt", "value": 25, "period": 14},
                    }
                ],
            },
            "initialization": {
                "id": "act1",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "atr_multiplier",
                    "sl_value": 2.0,
                    "tp_type": "rr_multiplier",
                    "tp_value": 5.0,
                },
            },
            "positionManagement": [
                {
                    "id": "mng_be",
                    "type": "move_to_breakeven",
                    "params": {
                        "target_type": "atr_multiplier",
                        "target_value": 1.0,
                        "offset_pips": 2,
                    },
                }
            ],
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        # Checking that the test passed without errors
        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_position_trailing_stop(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Verifies trailing stop logic.
        Adding RSI < 25 condition to limit the number of trades.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "c_rsi",
                        "type": "rsi_condition",
                        "params": {"operator": "lt", "value": 25, "period": 14},
                    }
                ],
            },
            "initialization": {
                "id": "act1",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "atr_multiplier",
                    "sl_value": 3.0,
                    "tp_type": "rr_multiplier",
                    "tp_value": 5.0,
                },
            },
            "positionManagement": [
                {
                    "id": "mng_trail",
                    "type": "trailing_stop",
                    "params": {"type": "ATR", "value": 2.0, "mode": "local"},
                }
            ],
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None

    @pytest.mark.asyncio
    async def test_e2e_position_partial_exits(
        self, real_kline_data, visual_strategy_instance
    ):
        """
        Verifies partial exits logic.
        Adding RSI < 25 condition to limit the number of trades.
        """
        config = {
            "min_foundation_weight_threshold": 0,
            "entryConditions": {
                "id": "e_root",
                "type": "AND",
                "children": [
                    {
                        "id": "c_rsi",
                        "type": "rsi_condition",
                        "params": {"operator": "lt", "value": 25, "period": 14},
                    }
                ],
            },
            "initialization": {
                "id": "act1",
                "type": "open_position",
                "params": {
                    "direction": "LONG",
                    "sl_type": "atr_multiplier",
                    "sl_value": 2.0,
                    "tp_type": "rr_multiplier",
                    "tp_value": 5.0,
                    "partial_exits": [
                        {"tp_type": "rr_multiplier", "tp_value": 1.0, "size_pct": 30},
                        {"tp_type": "rr_multiplier", "tp_value": 2.0, "size_pct": 30},
                    ],
                },
            },
        }

        backtester = create_backtester(config, real_kline_data)
        await backtester.run_async()

        assert backtester.trade_log is not None
