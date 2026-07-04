# tests/test_oracle_integration.py
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import pandas as pd
from datetime import datetime, timezone
import numpy as np

from bot_module.depthsight_backtester import DepthSightBacktester
from bot_module.strategy import (
    StrategySignal,
    SignalDirection,
    OrderMode,
)
from bot_module.oracle import Oracle

# --- Fixtures and mocks adapted from test_controller.py and test_depthsight_backtester.py ---


@pytest.fixture
def mock_oracle():
    """Mock for Oracle that can be configured in tests."""
    oracle = AsyncMock(spec=Oracle)
    # By default returns "trend" with high confidence
    oracle.get_current_regime.return_value = (0, 95.0)
    return oracle


@pytest.fixture
def mock_consumer_for_oracle():
    """Adapted DataConsumer mock."""
    consumer = AsyncMock()
    consumer.get_active_symbols.return_value = {"ORCLTEST"}
    consumer.get_active_pair_by_symbol.return_value = {
        "symbol": "ORCLTEST",
        "atr": 1.0,
        "last_price": 100.0,
        "tick_size": 0.01,
        "lot_params": {"stepSize": "0.001"},
        "min_notional": 10.0,
    }

    # Generate DataFrame for candle history
    kline_index = pd.to_datetime(
        pd.date_range(end=datetime.now(timezone.utc), periods=1500, freq="1min"),
        utc=True,
    )
    kline_df = pd.DataFrame(
        {
            "open": np.linspace(100, 110, 1500),
            "high": np.linspace(101, 111, 1500),
            "low": np.linspace(99, 109, 1500),
            "close": np.linspace(100.5, 110.5, 1500),
            "volume": np.random.randint(100, 1000, 1500),
            "positive": np.random.randint(0, 5, 1500),
            "negative": np.random.randint(0, 5, 1500),
            "important": np.random.randint(0, 2, 1500),
        },
        index=kline_index,
    )
    consumer.get_kline_history.return_value = kline_df
    consumer.event_queue = asyncio.Queue()
    return consumer


@pytest.fixture
def mock_executor_for_oracle():
    """Adapted Executor mock."""
    executor = AsyncMock()
    executor.market_type = "futures_usdtm"
    executor.get_account_balance.return_value = {"USDT": {"free": "10000.0"}}
    executor.place_order = AsyncMock(
        return_value={"status": "FILLED", "orderId": 1, "error": False}
    )
    return executor


@pytest.fixture
def mock_risk_manager_for_oracle():
    """Adapted RiskManager mock."""
    rm = AsyncMock()
    rm.assess_signal.return_value = (
        True,
        0.1,
        100.0,
        None,
    )  # (approved, quantity, risk_usd, reason)
    rm.is_symbol_trading_allowed.return_value = True
    return rm


# --- Tests for DepthSightBacktester ---


def create_backtester_for_oracle_test(
    strategy_params, historical_data, mock_oracle_instance
):
    """Helper for creating a backtester instance."""
    from pathlib import Path
    real_exists = Path.exists
    def mock_exists(self_path):
        if "oracle_model.joblib" in str(self_path):
            return True
        return real_exists(self_path)

    with (
        patch("bot_module.depthsight_backtester.Oracle", return_value=mock_oracle_instance),
        patch("pathlib.Path.exists", side_effect=mock_exists),
    ):
        bt = DepthSightBacktester(
            strategy_name="TestStrategy",
            symbol="ORCLTEST",
            params=strategy_params,
            historical_data=historical_data,
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
        )
    return bt


class SimpleSignalStrategy(StrategySignal):
    NAME = "TestStrategy"

    def check_signal(self, pair_info, market_data):
        # Generate a signal on every candle for test simplicity
        return StrategySignal(
            strategy_name=self.NAME,
            symbol=pair_info["symbol"],
            direction=SignalDirection.LONG,
            stop_loss=pair_info["last_price"] * 0.99,
            take_profit=pair_info["last_price"] * 1.02,
            trigger_price=pair_info["last_price"],
            mode=OrderMode.MARKET,
        )


@pytest.mark.asyncio
async def test_backtester_oracle_allows_trade():
    """
    Test: Backtester with oracle. Oracle allows the trade.
    """
    # 1. Prepare data and mocks
    mock_oracle_bt = MagicMock(spec=Oracle)
    # On the candle with minute == 50, the oracle will provide the required mode
    mock_oracle_bt.get_current_regime.side_effect = lambda df: (
        (0, 95.0) if df.index[-1].minute == 50 else (1, 95.0)
    )

    kline_df = pd.DataFrame(
        {
            "open": np.linspace(100, 110, 150),
            "high": np.linspace(101, 111, 150),
            "low": np.linspace(99, 109, 150),
            "close": np.linspace(100.5, 110.5, 150),
            "volume": 100,
            "positive": 1,
            "negative": 1,
            "important": 0,
        },
        index=pd.to_datetime(
            pd.date_range(start="2023-01-01 10:00", periods=150, freq="1min", tz="UTC")
        ),
    )

    # 2. Create backtester
    strategy_params = {"oracle_regime": 0, "oracle_confidence": 80.0}
    bt = create_backtester_for_oracle_test(
        strategy_params, {"kline_1m": kline_df}, mock_oracle_bt
    )

    # Mock the strategy itself so it just generates a signal
    mock_strategy_instance = AsyncMock()
    # Use named arguments to create StrategySignal
    mock_strategy_instance.check_signal.return_value = (
        StrategySignal(
            strategy_name="Test",
            symbol="ORCLTEST",
            direction=SignalDirection.LONG,
            trigger_price=100.0,
            stop_loss=99.0,
            take_profit=102.0,
            mode=OrderMode.MARKET,
            risk_pct=0.01,
        ),
        100,
        {},
    )
    mock_strategy_instance.check_fast_foundations.return_value = ({}, None)
    bt.strategy_instance = mock_strategy_instance

    # 3. Run backtest
    results = await bt.run_async()

    # 4. Verify
    # Expect the trade to open because at some point the oracle will return (0, 95.0)
    assert results["trades"] > 0, (
        "Trade should have opened when the oracle gave permission"
    )
    assert len(bt.trade_log) == 1
    # Check that the trade opened exactly on the candle where the oracle triggered
    entry_time = bt.trade_log[0]["entry_time"]
    assert entry_time.minute == 50


@pytest.mark.asyncio
async def test_backtester_oracle_rejects_all_trades():
    """
    Test: Backtester with oracle. Oracle never allows the trade.
    """
    # 1. Prepare data and mocks
    mock_oracle_bt = MagicMock(spec=Oracle)
    # Oracle always returns "Flat" mode (1)
    mock_oracle_bt.get_current_regime.return_value = (1, 95.0)

    kline_df = pd.DataFrame(
        {
            "open": np.linspace(100, 110, 150),
            "high": np.linspace(101, 111, 150),
            "low": np.linspace(99, 109, 150),
            "close": np.linspace(100.5, 110.5, 150),
            "volume": 100,
            "positive": 1,
            "negative": 1,
            "important": 0,
        },
        index=pd.to_datetime(
            pd.date_range(start="2023-01-01 10:00", periods=150, freq="1min", tz="UTC")
        ),
    )

    # 2. Create a backtester with a strategy requiring "Trend" mode (0)
    strategy_params = {"oracle_regime": 0, "oracle_confidence": 80.0}
    bt = create_backtester_for_oracle_test(
        strategy_params, {"kline_1m": kline_df}, mock_oracle_bt
    )

    mock_strategy_instance = AsyncMock()
    # Use named arguments to create StrategySignal
    mock_strategy_instance.check_signal.return_value = (
        StrategySignal(
            strategy_name="Test",
            symbol="ORCLTEST",
            direction=SignalDirection.LONG,
            trigger_price=100.0,
            stop_loss=99.0,
            take_profit=102.0,
            mode=OrderMode.MARKET,
            risk_pct=0.01,
        ),
        100,
        {},
    )
    mock_strategy_instance.check_fast_foundations.return_value = ({}, None)
    bt.strategy_instance = mock_strategy_instance

    # 3. Run backtest
    results = await bt.run_async()

    # 4. Verify
    assert results["trades"] == 0, (
        "There should be no trades as the oracle always prohibited them"
    )
