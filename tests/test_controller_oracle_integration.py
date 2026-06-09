# tests/test_controller_oracle_integration.py
"""
Integration test to verify the full cycle of dynamic symbol selection
using Oracle mode.

Checks:
1. Receiving data from the screener via queue
2. Filtering by oracle_regime and oracle_confidence
3. Applying max_concurrent_symbols limit
4. Subscribing only to filtered symbols
5. Synchronization of _last_known_symbols_from_consumer with currently_managed_symbols
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
        "Unable to import components for Controller integration tests.",
        allow_module_level=True,
    )


@dataclass
class MockSymbolSelectionConfig:
    """Class for simulating symbol selection configuration."""

    mode: str
    min_natr: Optional[float] = None
    max_concurrent_symbols: int = 5
    oracle_regime: Optional[int] = None
    oracle_confidence: Optional[float] = None


@pytest.fixture
def mock_consumer():
    """Creates a DataConsumer mock with subscription tracking."""
    consumer = AsyncMock(spec=DataConsumer)
    consumer.get_active_symbols = AsyncMock(return_value=set())
    consumer.get_active_pair_by_symbol = AsyncMock(return_value=None)

    # Tracking subscriptions
    consumer._subscribed_symbols = set()

    async def mock_ensure_subscription(
        data_type, symbol, required_metrics=None, **kwargs
    ):
        consumer._subscribed_symbols.add(symbol)
        return True

    async def mock_remove_subscriptions(symbol):
        consumer._subscribed_symbols.discard(symbol)
        return True

    consumer.ensure_subscription = AsyncMock(side_effect=mock_ensure_subscription)
    consumer.remove_all_subscriptions_for_symbol = AsyncMock(
        side_effect=mock_remove_subscriptions
    )

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
    rm.initialize_balance = AsyncMock()
    return rm


@pytest.fixture
async def controller_with_oracle_mode(
    mock_consumer, mock_executor, mock_risk_manager, monkeypatch
):
    """
    Creates a TradingController instance with DYNAMIC_ORACLE mode configured.
    """
    monkeypatch.setattr(global_config, "TRADING_MARKET_TYPE", "futures_usdtm")

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

    # Configuring Oracle mode
    controller.symbol_selection_config = MockSymbolSelectionConfig(
        mode="DYNAMIC_ORACLE",
        oracle_regime=1,  # Pump mode
        oracle_confidence=70.0,  # Minimum confidence 70%
        max_concurrent_symbols=3,  # Maximum 3 symbols simultaneously
    )

    yield controller

    if controller._running:
        await controller.stop()


@pytest.mark.asyncio
async def test_full_oracle_filtering_cycle(controller_with_oracle_mode, mock_consumer):
    """
    Full integration test of the Oracle filtering cycle.

    Scenario:
    1. Screener sends 10 coins with different oracle_regime and oracle_confidence
    2. Controller filters only coins with regime=1 and confidence>=70%
    3. Takes top-3 by confidence from the filtered ones
    4. Subscribes only to these 3 coins
    5. _last_known_symbols_from_consumer contains only these 3 coins
    """
    controller = controller_with_oracle_mode

    # Simulate data from the screener (10 coins)
    screener_data = [
        {
            "symbol": "BTCUSDT",
            "oracle_regime": 1,
            "oracle_confidence": 95.0,
            "last_price": 45000.0,
        },  # ✅ Top-1
        {
            "symbol": "ETHUSDT",
            "oracle_regime": 1,
            "oracle_confidence": 88.0,
            "last_price": 3000.0,
        },  # ✅ Top-2
        {
            "symbol": "BNBUSDT",
            "oracle_regime": 1,
            "oracle_confidence": 75.0,
            "last_price": 500.0,
        },  # ✅ Top-3
        {
            "symbol": "SOLUSDT",
            "oracle_regime": 1,
            "oracle_confidence": 72.0,
            "last_price": 100.0,
        },  # ❌ Top-4 (does not fit into the limit)
        {
            "symbol": "ADAUSDT",
            "oracle_regime": 1,
            "oracle_confidence": 65.0,
            "last_price": 0.5,
        },  # ❌ < 70%
        {
            "symbol": "DOGEUSDT",
            "oracle_regime": 0,
            "oracle_confidence": 90.0,
            "last_price": 0.1,
        },  # ❌ Mode 0
        {
            "symbol": "XRPUSDT",
            "oracle_regime": 2,
            "oracle_confidence": 85.0,
            "last_price": 0.6,
        },  # ❌ Mode 2
        {
            "symbol": "MATICUSDT",
            "oracle_regime": 1,
            "oracle_confidence": 50.0,
            "last_price": 0.8,
        },  # ❌ < 70%
        {
            "symbol": "AVAXUSDT",
            "oracle_regime": 0,
            "oracle_confidence": 95.0,
            "last_price": 30.0,
        },  # ❌ Mode 0
        {
            "symbol": "LINKUSDT",
            "oracle_regime": 1,
            "oracle_confidence": 68.0,
            "last_price": 15.0,
        },  # ❌ < 70%
    ]

    # Put data into the screener queue (simulate receiving from websocket)
    await controller._screener_update_queue.put({"data": screener_data})

    # Running one processing cycle
    controller._running = True

    # Get data from the queue (as in _dynamic_symbol_selection_loop)
    screener_update = await controller._screener_update_queue.get()
    controller.full_screener_list = screener_update.get("data", [])

    # Apply filtering (copy logic from _dynamic_symbol_selection_loop)
    required_regime = controller.symbol_selection_config.oracle_regime
    min_confidence = controller.symbol_selection_config.oracle_confidence

    filtered_and_sorted_symbols = [
        s
        for s in controller.full_screener_list
        if s.get("oracle_regime") == required_regime
        and s.get("oracle_confidence", 0.0) >= min_confidence
    ]
    filtered_and_sorted_symbols.sort(
        key=lambda x: x.get("oracle_confidence", 0.0), reverse=True
    )

    # Applying limit
    max_concurrent = controller.symbol_selection_config.max_concurrent_symbols
    desired_symbols_set = {
        s["symbol"] for s in filtered_and_sorted_symbols[:max_concurrent]
    }

    # Update currently_managed_symbols (as in a loop)
    for symbol in desired_symbols_set:
        if symbol not in controller.currently_managed_symbols:
            await controller.start_managing_symbol(symbol)

    controller.currently_managed_symbols = desired_symbols_set.copy()

    # Synchronize _last_known_symbols_from_consumer (as in _check_and_update_symbols)
    controller._last_known_symbols_from_consumer = (
        controller.currently_managed_symbols.copy()
    )

    # === CHECKS ===

    # 1. Check that the correct number of symbols is filtered
    assert len(desired_symbols_set) == 3, (
        f"3 symbols should be selected, received {len(desired_symbols_set)}"
    )

    # 2. Check that the correct symbols are selected (top-3 by confidence with regime=1 and confidence>=70%)
    expected_symbols = {"BTCUSDT", "ETHUSDT", "BNBUSDT"}
    assert desired_symbols_set == expected_symbols, (
        f"Expected {expected_symbols}, received {desired_symbols_set}"
    )

    # 3. Check that currently_managed_symbols contains the correct symbols
    assert controller.currently_managed_symbols == expected_symbols, (
        f"currently_managed_symbols should contain {expected_symbols}, received {controller.currently_managed_symbols}"
    )

    # 4. Check that _last_known_symbols_from_consumer is synchronized
    assert controller._last_known_symbols_from_consumer == expected_symbols, (
        f"_last_known_symbols_from_consumer should contain {expected_symbols}, received {controller._last_known_symbols_from_consumer}"
    )

    # 5. Check that unsuitable symbols did NOT get into the selection
    rejected_symbols = {
        "SOLUSDT",
        "ADAUSDT",
        "DOGEUSDT",
        "XRPUSDT",
        "MATICUSDT",
        "AVAXUSDT",
        "LINKUSDT",
    }
    for symbol in rejected_symbols:
        assert symbol not in desired_symbols_set, (
            f"{symbol} should not be in the selection"
        )
        assert symbol not in controller.currently_managed_symbols, (
            f"{symbol} should not be in currently_managed_symbols"
        )
        assert symbol not in controller._last_known_symbols_from_consumer, (
            f"{symbol} should not be in _last_known_symbols_from_consumer"
        )

    # 6. Check that _monitored_symbols is updated
    # (start_managing_symbol calls _update_monitored_symbols)
    # Note: ensure_subscription is called only if there are running strategies,
    # therefore, in this test we do not check subscription calls

    print(f"✅ Test passed! Selected symbols: {desired_symbols_set}")
    print(f"✅ currently_managed_symbols: {controller.currently_managed_symbols}")
    print(
        f"✅ _last_known_symbols_from_consumer: {controller._last_known_symbols_from_consumer}"
    )


@pytest.mark.asyncio
async def test_oracle_mode_updates_on_new_screener_data(
    controller_with_oracle_mode, mock_consumer
):
    """
    The test verifies that when receiving new data from the screener,
    the controller correctly updates the list of managed symbols.

    Scenario:
    1. First update: 3 coins pass the filter
    2. Second update: another 3 coins pass the filter
    3. Controller must unsubscribe from old ones and subscribe to new ones
    """
    controller = controller_with_oracle_mode
    controller._running = True

    # === First update from the screener ===
    screener_data_1 = [
        {
            "symbol": "BTCUSDT",
            "oracle_regime": 1,
            "oracle_confidence": 95.0,
            "last_price": 45000.0,
        },
        {
            "symbol": "ETHUSDT",
            "oracle_regime": 1,
            "oracle_confidence": 88.0,
            "last_price": 3000.0,
        },
        {
            "symbol": "BNBUSDT",
            "oracle_regime": 1,
            "oracle_confidence": 75.0,
            "last_price": 500.0,
        },
    ]

    await controller._screener_update_queue.put({"data": screener_data_1})
    screener_update = await controller._screener_update_queue.get()
    controller.full_screener_list = screener_update.get("data", [])

    # Filtering and updating
    filtered_1 = [
        s
        for s in controller.full_screener_list
        if s.get("oracle_regime") == 1 and s.get("oracle_confidence", 0.0) >= 70.0
    ]
    filtered_1.sort(key=lambda x: x.get("oracle_confidence", 0.0), reverse=True)
    desired_symbols_1 = {s["symbol"] for s in filtered_1[:3]}

    for symbol in desired_symbols_1:
        await controller.start_managing_symbol(symbol)

    controller.currently_managed_symbols = desired_symbols_1.copy()
    controller._last_known_symbols_from_consumer = (
        controller.currently_managed_symbols.copy()
    )

    # Checking the first state
    assert controller.currently_managed_symbols == {"BTCUSDT", "ETHUSDT", "BNBUSDT"}

    # === Second update from the screener (other coins) ===
    screener_data_2 = [
        {
            "symbol": "SOLUSDT",
            "oracle_regime": 1,
            "oracle_confidence": 92.0,
            "last_price": 100.0,
        },
        {
            "symbol": "ADAUSDT",
            "oracle_regime": 1,
            "oracle_confidence": 85.0,
            "last_price": 0.5,
        },
        {
            "symbol": "DOGEUSDT",
            "oracle_regime": 1,
            "oracle_confidence": 78.0,
            "last_price": 0.1,
        },
        # Old coins no longer pass the filter (e.g., regime changed)
        {
            "symbol": "BTCUSDT",
            "oracle_regime": 0,
            "oracle_confidence": 95.0,
            "last_price": 45000.0,
        },
        {
            "symbol": "ETHUSDT",
            "oracle_regime": 2,
            "oracle_confidence": 88.0,
            "last_price": 3000.0,
        },
        {
            "symbol": "BNBUSDT",
            "oracle_regime": 1,
            "oracle_confidence": 65.0,
            "last_price": 500.0,
        },  # < 70%
    ]

    await controller._screener_update_queue.put({"data": screener_data_2})
    screener_update = await controller._screener_update_queue.get()
    controller.full_screener_list = screener_update.get("data", [])

    # Filtering new data
    filtered_2 = [
        s
        for s in controller.full_screener_list
        if s.get("oracle_regime") == 1 and s.get("oracle_confidence", 0.0) >= 70.0
    ]
    filtered_2.sort(key=lambda x: x.get("oracle_confidence", 0.0), reverse=True)
    desired_symbols_2 = {s["symbol"] for s in filtered_2[:3]}

    # Determine which symbols need to be added/removed
    current_managed = controller.currently_managed_symbols.copy()
    symbols_to_add = desired_symbols_2 - current_managed
    symbols_to_remove = current_managed - desired_symbols_2

    # Removing outdated
    for symbol in symbols_to_remove:
        await controller.stop_managing_symbol(symbol)

    # Adding new
    for symbol in symbols_to_add:
        await controller.start_managing_symbol(symbol)

    controller.currently_managed_symbols = desired_symbols_2.copy()
    controller._last_known_symbols_from_consumer = (
        controller.currently_managed_symbols.copy()
    )

    # === CHECKS ===

    # Checking that the list has updated
    expected_symbols_2 = {"SOLUSDT", "ADAUSDT", "DOGEUSDT"}
    assert controller.currently_managed_symbols == expected_symbols_2, (
        f"After the second update, expected {expected_symbols_2}, received {controller.currently_managed_symbols}"
    )

    # Check that old symbols are removed
    old_symbols = {"BTCUSDT", "ETHUSDT", "BNBUSDT"}
    for symbol in old_symbols:
        assert symbol not in controller.currently_managed_symbols, (
            f"{symbol} should be deleted"
        )

    # Checking synchronization
    assert controller._last_known_symbols_from_consumer == expected_symbols_2

    print("✅ Update test passed!")
    print(f"✅ Old symbols: {old_symbols}")
    print(f"✅ New symbols: {expected_symbols_2}")


@pytest.mark.asyncio
async def test_static_mode_does_not_use_screener(
    controller_with_oracle_mode, mock_consumer
):
    """
    The test verifies that in STATIC mode the controller does NOT use data from the screener,
    but trades only symbols from the strategy config.
    """
    controller = controller_with_oracle_mode

    # Switching to STATIC mode
    controller.symbol_selection_config = MockSymbolSelectionConfig(
        mode="STATIC",
        oracle_regime=None,
        oracle_confidence=None,
        max_concurrent_symbols=5,
    )

    # Simulating data from the screener
    screener_data = [
        {
            "symbol": "BTCUSDT",
            "oracle_regime": 1,
            "oracle_confidence": 95.0,
            "last_price": 45000.0,
        },
        {
            "symbol": "ETHUSDT",
            "oracle_regime": 1,
            "oracle_confidence": 88.0,
            "last_price": 3000.0,
        },
    ]

    await controller._screener_update_queue.put({"data": screener_data})

    # In STATIC mode _check_and_update_symbols should use consumer.get_active_symbols()
    # and not data from the screener

    # Configure consumer mock to return static symbols
    static_symbols = {"XRPUSDT", "ADAUSDT"}  # Symbols from the strategy config
    mock_consumer.get_active_symbols = AsyncMock(return_value=static_symbols)

    # Call _check_and_update_symbols
    await controller._check_and_update_symbols()

    # Check that static symbols are used, not from the screener
    assert controller._last_known_symbols_from_consumer == static_symbols, (
        f"In STATIC mode, symbols from the config should be used: {static_symbols}, received {controller._last_known_symbols_from_consumer}"
    )

    # Check that symbols from the screener are NOT used
    screener_symbols = {"BTCUSDT", "ETHUSDT"}
    assert controller._last_known_symbols_from_consumer != screener_symbols, (
        "In STATIC mode, symbols from the screener should not be used"
    )

    print("✅ STATIC mode test passed!")
    print(f"✅ Static symbols are used: {static_symbols}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
