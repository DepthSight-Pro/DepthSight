# File: tests/test_controller_position_management_integration.py
"""
Integration test: checks the full position management path
via the controller, including pair_info formation from DataFrame.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone


def create_mock_kline_df(num_rows=100, base_price=100.0):
    """Creates DataFrame with candles with DatetimeIndex."""
    now = datetime.now(timezone.utc)
    timestamps = pd.date_range(end=now, periods=num_rows, freq="1T", tz="UTC")

    return pd.DataFrame(
        {
            "open": np.linspace(base_price, base_price + 5, num_rows),
            "high": np.linspace(
                base_price + 2, base_price + 10, num_rows
            ),  # High high for BE trigger
            "low": np.linspace(base_price - 2, base_price + 3, num_rows),
            "close": np.linspace(base_price + 1, base_price + 6, num_rows),
            "volume": np.random.rand(num_rows) * 1000,
        },
        index=timestamps,
    )


@pytest.mark.asyncio
async def test_controller_enriches_pair_info_with_timestamp_dt():
    """
    Test: controller should add timestamp_dt to pair_info
    when preparing data for manage_position.

    This test emulates code from controller.py lines 2086-2107.
    """
    klines = create_mock_kline_df(100, 100.0)

    # Emulate pair_info from consumer.get_active_pair_by_symbol()
    pair_info = {
        "symbol": "TESTUSDT",
        "last_price": 105.0,
        "atr": 1.0,
    }

    # Emulating market_data
    market_data = {"kline_1m": klines}

    # === This is code from controller.py (_process_event) AFTER the fix ===
    candle_timeframe = "1m"
    kline_key = f"kline_{candle_timeframe}"
    candles_df = market_data.get(kline_key)

    if candles_df is not None and not candles_df.empty:
        last_candle = candles_df.iloc[-1]
        pair_info.update(last_candle.to_dict())

        if "timestamp_dt" not in pair_info:
            candle_timestamp = candles_df.index[-1]
            if hasattr(candle_timestamp, "to_pydatetime"):
                pair_info["timestamp_dt"] = candle_timestamp.to_pydatetime()
            else:
                pair_info["timestamp_dt"] = candle_timestamp

    # CHECKS
    assert "timestamp_dt" in pair_info, (
        "timestamp_dt should be added from DataFrame index"
    )
    assert pair_info["timestamp_dt"] is not None, "timestamp_dt should not be None"
    assert "high" in pair_info, "high should be from the last candle"
    assert "low" in pair_info, "low should be from the last candle"

    print("✓ pair_info enriched correctly:")
    print(f"  timestamp_dt = {pair_info['timestamp_dt']}")
    print(f"  high = {pair_info['high']}")
    print(f"  low = {pair_info['low']}")


@pytest.mark.asyncio
async def test_full_position_management_flow_with_be_trigger():
    """
    Full integration test: from pair_info formation to breakeven trigger.

    Scenario:
    - Entry: 100.0, SL: 98.0 (risk = 2.0, this is 1R)
    - Candle high: 105.0 (profit = 5.0, RR = 2.5)
    - move_to_breakeven with target_value=1.0 (1R required)
    - Expected: stop is moved to BE (100.0 + offset)
    """
    from bot_module.strategy import VisualBuilderStrategy
    from bot_module.datatypes import BasePosition, SignalDirection

    klines = create_mock_kline_df(100, 100.0)

    # Set high of the last candle = 105 (this gives 2.5R)
    klines.iloc[-1, klines.columns.get_loc("high")] = 105.0
    klines.iloc[-1, klines.columns.get_loc("low")] = 99.5

    # Step 1: Form pair_info as in the controller
    pair_info = {
        "symbol": "TESTUSDT",
        "last_price": 104.0,
        "atr": 1.0,
        "tick_size": 0.01,
    }

    candles_df = klines
    last_candle = candles_df.iloc[-1]
    pair_info.update(last_candle.to_dict())

    if "timestamp_dt" not in pair_info:
        candle_timestamp = candles_df.index[-1]
        pair_info["timestamp_dt"] = (
            candle_timestamp.to_pydatetime()
            if hasattr(candle_timestamp, "to_pydatetime")
            else candle_timestamp
        )

    # Step 2: Create strategy with positionManagement (as in config)
    test_config = {
        "name": "Test Strategy",
        "positionManagement": [
            {
                "id": "be_rule",
                "type": "move_to_breakeven",
                "params": {
                    "target_type": "rr_multiplier",
                    "target_value": 1.0,  # Need 1R for trigger
                    "offset_pips": 2,  # +0.02 from entry
                },
            }
        ],
    }

    strategy = VisualBuilderStrategy(params={"config": test_config})

    # Step 3: Create position
    position = BasePosition(
        symbol="TESTUSDT",
        direction=SignalDirection.LONG,
        entry_price=100.0,
        initial_quantity=1.0,
        remaining_quantity=1.0,
        entry_time=1000000.0,
        strategy="VisualBuilderStrategy",
        initial_stop_loss=98.0,  # Risk = 2.0
        current_sl_price=98.0,
        initial_take_profit=110.0,
        is_stop_at_be=False,
        client_order_id="test-order-123",
    )
    position.partial_targets = []
    position.partial_fills = []
    position.executions = []

    market_data = {"kline_1m": klines}

    # Step 4: Call manage_position
    print("\nBefore manage_position:")
    print(f"  current_sl_price = {position.current_sl_price}")
    print(f"  is_stop_at_be = {position.is_stop_at_be}")
    print(f"  pair_info['high'] = {pair_info['high']}")
    print(f"  pair_info['timestamp_dt'] = {pair_info['timestamp_dt']}")

    updated_position, exit_details = await strategy.manage_position(
        position, pair_info, market_data, None
    )

    print("\nAfter manage_position:")
    print(f"  current_sl_price = {updated_position.current_sl_price}")
    print(f"  is_stop_at_be = {updated_position.is_stop_at_be}")

    # CHECKS
    assert updated_position.is_stop_at_be, (
        f"Expected is_stop_at_be=True. High={pair_info['high']}, Entry=100, "
        f"Risk=2.0, Profit=5.0, RR=2.5 >= target=1.0"
    )

    expected_be = 100.0 + (2 * 0.01)  # entry + offset_pips * tick_size = 100.02
    assert updated_position.current_sl_price == pytest.approx(expected_be, abs=0.01), (
        f"Expected SL = {expected_be}, got {updated_position.current_sl_price}"
    )

    print("\n✓ Breakeven triggered correctly!")
    print(f"  SL moved from 98.0 to {updated_position.current_sl_price}")
