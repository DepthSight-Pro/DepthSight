import pytest
import asyncio
import time
from unittest.mock import MagicMock, AsyncMock, patch
from bot_module.controller import TradingController
from bot_module.strategy import SignalDirection, StrategySignal, OrderMode


@pytest.mark.asyncio
async def test_symbol_lock_independence():
    """
    Verifies that locking one symbol does not block processing for another symbol.
    """
    controller = TradingController(
        loop=asyncio.get_running_loop(),
        data_consumer=MagicMock(),
        live_executor=AsyncMock(),
        paper_executor=AsyncMock(),
        risk_manager=MagicMock(),
        user_id=1,
    )

    symbol_a = "BTCUSDT"
    symbol_b = "ETHUSDT"
    market_type = "futures_usdtm"

    lock_a = controller._get_lock_for_position(symbol_a, market_type)
    lock_b = controller._get_lock_for_position(symbol_b, market_type)

    assert lock_a is not lock_b, "Locks for different symbols must be different objects"

    # Simulate a long-running operation on symbol A
    async def heavy_operation_a():
        async with lock_a:
            await asyncio.sleep(0.5)
            return "A_done"

    # Simulate a fast operation on symbol B
    async def fast_operation_b():
        # Small delay to ensure A starts first
        await asyncio.sleep(0.1)
        start_time = time.time()
        async with lock_b:
            end_time = time.time()
            return end_time - start_time

    # Run both concurrently
    results = await asyncio.gather(heavy_operation_a(), fast_operation_b())

    # Verify that operation B did not wait for 0.5s for operation A to finish
    wait_time_b = results[1]
    assert wait_time_b < 0.2, (
        f"Symbol B was blocked by Symbol A! Wait time: {wait_time_b:.4f}s"
    )
    print(f"Lock independence verified. B wait time: {wait_time_b:.4f}s")


@pytest.mark.asyncio
async def test_concurrency_limit_integrity_with_fine_grained_locks():
    """
    Verifies that the hybrid locking logic correctly enforces max_concurrent_trades
    even when signals arrive simultaneously.
    """
    mock_rm = MagicMock()
    mock_rm.max_concurrent_trades = 1
    mock_rm.is_symbol_trading_allowed = AsyncMock(return_value=True)
    mock_rm.assess_signal = AsyncMock(return_value=(True, 1.0, 100.0, None))

    mock_executor = AsyncMock()

    # Simulate slightly slow order placement to increase race condition window
    async def slow_place_order(*args, **kwargs):
        await asyncio.sleep(0.2)
        return {"orderId": 123, "status": "NEW", "error": False}

    mock_executor.place_order.side_effect = slow_place_order

    controller = TradingController(
        loop=asyncio.get_running_loop(),
        data_consumer=MagicMock(),
        live_executor=mock_executor,
        paper_executor=AsyncMock(),
        risk_manager=mock_rm,
        user_id=1,
    )

    # Mocking strategy lookup to return a dummy instance
    mock_strategy = MagicMock()
    controller.running_strategy_instances = {
        "cfg_1": (mock_strategy, {"config_data": {}}),
        "cfg_2": (mock_strategy, {"config_data": {}}),
    }

    # Prepare two signals for different symbols
    signal_1 = StrategySignal(
        strategy_name="Test",
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        stop_loss=40000,
        take_profit=50000,
        mode=OrderMode.MARKET,
        trigger_price=45000,
        details={"strategy_config_id": "cfg_1"},
    )
    signal_2 = StrategySignal(
        strategy_name="Test",
        symbol="ETHUSDT",
        direction=SignalDirection.LONG,
        stop_loss=2000,
        take_profit=3000,
        mode=OrderMode.MARKET,
        trigger_price=2500,
        details={"strategy_config_id": "cfg_2"},
    )

    pair_info = {"symbol": "ANY", "last_price": 100}

    # Fire both signals concurrently
    # Both should hit the _positions_dict_lock check.
    # One should pass and create a RESERVING placeholder, the other should be rejected.
    await asyncio.gather(
        controller._process_signal(signal_1, pair_info),
        controller._process_signal(signal_2, pair_info),
    )

    # Verify that only ONE position was created
    async with controller._positions_dict_lock:
        active_count = len(controller._active_positions)
        assert active_count == 1, (
            f"Concurrency limit breached! Created {active_count} positions, expected 1."
        )

    print("Concurrency limit integrity verified with hybrid locking.")


@pytest.mark.asyncio
async def test_reconcile_does_not_block_dictionary_structure():
    """
    Verifies that _reconcile_positions_with_exchange uses snapshotting
    and doesn't hold the dict lock while performing logic.
    """
    mock_executor = AsyncMock()
    # Mock many positions on exchange
    mock_executor.get_open_positions.return_value = [
        {"symbol": f"SYM{i}", "positionAmt": "1.0", "entryPrice": "100.0"}
        for i in range(10)
    ]
    mock_executor.market_type = "futures_usdtm"

    controller = TradingController(
        loop=asyncio.get_running_loop(),
        data_consumer=MagicMock(),
        live_executor=mock_executor,
        paper_executor=AsyncMock(),
        risk_manager=MagicMock(),
        user_id=1,
    )

    # We'll patch _get_lock_for_position to simulate a delay during the "apply" phase
    # of reconciliation (Step 4 in the plan).
    original_get_lock = controller._get_lock_for_position

    async def delayed_lock(*args, **kwargs):
        lock = original_get_lock(*args, **kwargs)
        # When reconcile tries to use this lock, it will yield, but it should NOT be holding the dict lock!
        return lock

    with patch.object(controller, "_get_lock_for_position", side_effect=delayed_lock):
        # Start reconcile in background
        reconcile_task = asyncio.create_task(
            controller._reconcile_positions_with_exchange()
        )

        # Give it a tiny bit of time to reach the diff/apply phase
        await asyncio.sleep(0.05)

        # Test: Can we still access the dictionary (e.g., set a new position) while reconcile is running?
        # If reconcile held _positions_dict_lock, this would wait.
        start_wait = time.time()
        async with controller._positions_dict_lock:
            can_access_dict = True
        end_wait = time.time()

        assert can_access_dict
        assert (end_wait - start_wait) < 0.1, (
            "Dictionary lock was held too long by reconciliation!"
        )

        await reconcile_task

    print("Reconciliation snapshotting verified.")
