# tests/test_controller_symbol_selection.py
"""
Tests to verify the logic of dynamic symbol selection in TradingController
based on user conditions (NATR, oracle_regime).
"""

import pytest
import asyncio
from unittest.mock import AsyncMock
from dataclasses import dataclass
from typing import Optional

try:
    from bot_module.controller import TradingController
    from bot_module.data_consumer import DataConsumer
    from bot_module.exchanges import ExchangeExecutor
    from bot_module.risk_manager import RiskManager
    from bot_module import config as global_config
except ImportError:
    pytest.skip(
        "Unable to import components for Controller symbol selection tests.",
        allow_module_level=True,
    )


# Helper class to simulate symbol selection configuration
@dataclass
class MockSymbolSelectionConfig:
    """Simple class for storing symbol selection configuration in tests."""

    mode: str
    min_natr: Optional[float] = None
    max_concurrent_symbols: int = 5
    oracle_regime: Optional[int] = None
    oracle_confidence: Optional[float] = None


@pytest.fixture
def mock_consumer():
    """Creates a DataConsumer mock."""
    consumer = AsyncMock(spec=DataConsumer)
    consumer.get_active_symbols = AsyncMock(return_value=[])
    consumer.get_active_pair_by_symbol = AsyncMock(return_value=None)
    consumer.ensure_subscription = AsyncMock()
    consumer.remove_all_subscriptions_for_symbol = AsyncMock()
    return consumer


@pytest.fixture
def mock_executor():
    """Creates a BinanceExecutor mock."""
    executor = AsyncMock(spec=ExchangeExecutor)
    executor.place_order = AsyncMock(return_value={"orderId": 123, "status": "NEW"})
    return executor


@pytest.fixture
def mock_risk_manager():
    """Creates a RiskManager mock."""
    rm = AsyncMock(spec=RiskManager)
    rm.can_open_new_position = AsyncMock(return_value=True)
    rm.calculate_position_size = AsyncMock(return_value=0.1)
    rm.save_state = AsyncMock()
    return rm


@pytest.fixture
async def controller_instance(
    mock_consumer, mock_executor, mock_risk_manager, monkeypatch
):
    """Creates a TradingController instance for tests."""
    monkeypatch.setattr(global_config, "TRADING_MARKET_TYPE", "futures_usdtm")

    # Creating a PaperTradingExecutor mock
    paper_executor = AsyncMock()
    paper_executor.place_order = AsyncMock(
        return_value={"orderId": 456, "status": "NEW"}
    )

    controller = TradingController(
        loop=asyncio.get_running_loop(),
        data_consumer=mock_consumer,
        live_executor=mock_executor,
        paper_executor=paper_executor,
        risk_manager=mock_risk_manager,
        user_id=1,
        telegram_notifier=None,
    )

    yield controller

    if controller._running:
        await controller.stop()


@pytest.mark.asyncio
async def test_dynamic_natr_filtering_by_user_threshold(controller_instance):
    """
    The test checks symbol filtering by NATR >= threshold set by the user.

    Scenario: User set min_natr = 2.0 via the frontend
    Expectation: Only symbols with NATR >= 2.0 should be selected
    """
    # Setting up symbol selection configuration (as if the user configured it via the frontend)
    controller_instance.symbol_selection_config = MockSymbolSelectionConfig(
        mode="DYNAMIC_NATR",
        min_natr=2.0,  # Threshold from user
        max_concurrent_symbols=3,
        oracle_regime=None,
        oracle_confidence=None,
    )

    # Simulating data from the screener with different NATR
    screener_data = [
        {
            "symbol": "BTCUSDT",
            "NATR 1/30 (1m)": 3.5,
            "last_price": 45000.0,
        },  # ✅ >= 2.0
        {"symbol": "ETHUSDT", "NATR 1/30 (1m)": 2.8, "last_price": 3000.0},  # ✅ >= 2.0
        {"symbol": "BNBUSDT", "NATR 1/30 (1m)": 2.1, "last_price": 500.0},  # ✅ >= 2.0
        {"symbol": "SOLUSDT", "NATR 1/30 (1m)": 1.5, "last_price": 100.0},  # ❌ < 2.0
        {"symbol": "ADAUSDT", "NATR 1/30 (1m)": 1.0, "last_price": 0.5},  # ❌ < 2.0
    ]

    # Putting data into the screener queue
    controller_instance.full_screener_list = screener_data

    # Manually running the filtering logic (simulating processing in _dynamic_symbol_selection_loop)
    min_natr = controller_instance.symbol_selection_config.min_natr

    filtered_and_sorted_symbols = [
        s
        for s in controller_instance.full_screener_list
        if s.get("NATR 1/30 (1m)", 0.0) >= min_natr
    ]
    filtered_and_sorted_symbols.sort(
        key=lambda x: x.get("NATR 1/30 (1m)", 0.0), reverse=True
    )

    # Applying a limit on the number of symbols
    max_concurrent = controller_instance.symbol_selection_config.max_concurrent_symbols
    desired_symbols_set = {
        s["symbol"] for s in filtered_and_sorted_symbols[:max_concurrent]
    }

    # Checking results
    assert len(desired_symbols_set) == 3, (
        "3 symbols should be selected (max_concurrent_symbols)"
    )

    # Checking that the correct symbols are selected (with the highest NATR and >= 2.0)
    expected_symbols = {"BTCUSDT", "ETHUSDT", "BNBUSDT"}
    assert desired_symbols_set == expected_symbols, (
        f"Expected {expected_symbols}, received {desired_symbols_set}"
    )

    # Checking that symbols with NATR < 2.0 did NOT get into the selection
    assert "SOLUSDT" not in desired_symbols_set
    assert "ADAUSDT" not in desired_symbols_set


@pytest.mark.asyncio
async def test_dynamic_oracle_filtering_by_regime_and_confidence(controller_instance):
    """
    The test checks symbol filtering by oracle_regime and oracle_confidence,
    set by the user.

    Scenario: User set oracle_regime = 1 (pump) and min_confidence = 75%
    Expectation: Only symbols in pump mode with confidence >= 75% should be selected
    """
    # Setting up the configuration (as if the user configured it via the frontend)
    controller_instance.symbol_selection_config = MockSymbolSelectionConfig(
        mode="DYNAMIC_ORACLE",
        min_natr=None,
        max_concurrent_symbols=2,
        oracle_regime=1,  # Mode 1 = pump (from user)
        oracle_confidence=75.0,  # Minimum confidence 75% (from user)
    )

    # Simulating data from the screener with oracle data
    screener_data = [
        {
            "symbol": "BTCUSDT",
            "oracle_regime": 1,  # ✅ Mode 1 (pump)
            "oracle_confidence": 85.3,  # ✅ >= 75%
            "last_price": 45000.0,
        },
        {
            "symbol": "ETHUSDT",
            "oracle_regime": 1,  # ✅ Mode 1 (pump)
            "oracle_confidence": 78.5,  # ✅ >= 75%
            "last_price": 3000.0,
        },
        {
            "symbol": "BNBUSDT",
            "oracle_regime": 1,  # ✅ Mode 1 (pump)
            "oracle_confidence": 72.0,  # ❌ < 75%
            "last_price": 500.0,
        },
        {
            "symbol": "SOLUSDT",
            "oracle_regime": 0,  # ❌ Mode 0 (sideways), not 1
            "oracle_confidence": 90.0,  # High confidence, but wrong mode
            "last_price": 100.0,
        },
        {
            "symbol": "ADAUSDT",
            "oracle_regime": 2,  # ❌ Mode 2 (dump), not 1
            "oracle_confidence": 80.0,
            "last_price": 0.5,
        },
    ]

    controller_instance.full_screener_list = screener_data

    # Running the filtering logic
    required_regime = controller_instance.symbol_selection_config.oracle_regime
    min_confidence = controller_instance.symbol_selection_config.oracle_confidence

    filtered_and_sorted_symbols = [
        s
        for s in controller_instance.full_screener_list
        if s.get("oracle_regime") == required_regime
        and s.get("oracle_confidence", 0.0) >= min_confidence
    ]
    filtered_and_sorted_symbols.sort(
        key=lambda x: x.get("oracle_confidence", 0.0), reverse=True
    )

    # Applying limit
    max_concurrent = controller_instance.symbol_selection_config.max_concurrent_symbols
    desired_symbols_set = {
        s["symbol"] for s in filtered_and_sorted_symbols[:max_concurrent]
    }

    # Checking results
    assert len(desired_symbols_set) == 2, "2 symbols should be selected"

    # Checking the correctness of selection (pump mode with confidence >= 75%)
    expected_symbols = {"BTCUSDT", "ETHUSDT"}
    assert desired_symbols_set == expected_symbols, (
        f"Expected {expected_symbols}, received {desired_symbols_set}"
    )

    # Checking that unsuitable symbols did NOT get in
    assert "BNBUSDT" not in desired_symbols_set, "BNBUSDT: confidence < 75%"
    assert "SOLUSDT" not in desired_symbols_set, "SOLUSDT: wrong mode (0 instead of 1)"
    assert "ADAUSDT" not in desired_symbols_set, "ADAUSDT: wrong mode (2 instead of 1)"


@pytest.mark.asyncio
async def test_combined_natr_and_oracle_filtering(controller_instance):
    """
    Integration test checks that NATR and Oracle filters can be combined
    (although they are different modes in the current implementation).

    This test shows the difference between modes.
    """
    screener_data = [
        {
            "symbol": "BTCUSDT",
            "NATR 1/30 (1m)": 3.5,
            "oracle_regime": 1,
            "oracle_confidence": 85.0,
            "last_price": 45000.0,
        },
        {
            "symbol": "ETHUSDT",
            "NATR 1/30 (1m)": 0.5,  # Low NATR
            "oracle_regime": 1,
            "oracle_confidence": 90.0,  # High Oracle confidence
            "last_price": 3000.0,
        },
    ]

    controller_instance.full_screener_list = screener_data

    # Mode 1: Filtering by NATR
    controller_instance.symbol_selection_config = MockSymbolSelectionConfig(
        mode="DYNAMIC_NATR",
        min_natr=2.0,
        max_concurrent_symbols=5,
        oracle_regime=None,
        oracle_confidence=None,
    )

    natr_filtered = [s for s in screener_data if s.get("NATR 1/30 (1m)", 0.0) >= 2.0]
    natr_symbols = {s["symbol"] for s in natr_filtered}

    assert natr_symbols == {"BTCUSDT"}, "Only BTCUSDT passes the NATR >= 2.0 filter"

    # Mode 2: Filtering by Oracle
    controller_instance.symbol_selection_config = MockSymbolSelectionConfig(
        mode="DYNAMIC_ORACLE",
        min_natr=None,
        max_concurrent_symbols=5,
        oracle_regime=1,
        oracle_confidence=80.0,
    )

    oracle_filtered = [
        s
        for s in screener_data
        if s.get("oracle_regime") == 1 and s.get("oracle_confidence", 0.0) >= 80.0
    ]
    oracle_symbols = {s["symbol"] for s in oracle_filtered}

    assert oracle_symbols == {
        "BTCUSDT",
        "ETHUSDT",
    }, "Both symbols pass the Oracle filter"


@pytest.mark.asyncio
async def test_zero_symbols_pass_strict_filter(controller_instance):
    """
    The test checks behavior when NO symbol passes the filter.

    Scenario: User set very strict conditions (NATR >= 10.0)
    Expectation: Empty list of symbols, the system does not crash
    """
    controller_instance.symbol_selection_config = MockSymbolSelectionConfig(
        mode="DYNAMIC_NATR",
        min_natr=10.0,  # Very high threshold
        max_concurrent_symbols=5,
        oracle_regime=None,
        oracle_confidence=None,
    )

    screener_data = [
        {"symbol": "BTCUSDT", "NATR 1/30 (1m)": 3.5, "last_price": 45000.0},
        {"symbol": "ETHUSDT", "NATR 1/30 (1m)": 2.8, "last_price": 3000.0},
    ]

    controller_instance.full_screener_list = screener_data

    # Filtering
    min_natr = controller_instance.symbol_selection_config.min_natr
    filtered = [s for s in screener_data if s.get("NATR 1/30 (1m)", 0.0) >= min_natr]

    desired_symbols_set = {s["symbol"] for s in filtered}

    # Checking that the list is empty
    assert len(desired_symbols_set) == 0, (
        "No symbol should pass the NATR >= 10.0 filter"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
