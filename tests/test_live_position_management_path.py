# File: tests/test_live_position_management_path.py
"""
Tests to verify that the position management code path in live mode (via the controller)
correctly passes all necessary data to manage_position.

These tests emulate a real scenario:
1. pair_info is formed from a DataFrame (as in the controller)
2. manage_position is called with this data
3. It is verified that positionManagement blocks are executed
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from bot_module.strategy import VisualBuilderStrategy
from bot_module.datatypes import BasePosition, SignalDirection


def create_mock_kline_df_with_datetime_index(num_rows=100, base_price=100.0):
    """
    Creates a DataFrame with candles where the index is a DatetimeIndex (as in reality).
    """
    now = datetime.now(timezone.utc)
    timestamps = pd.date_range(end=now, periods=num_rows, freq="1T", tz="UTC")

    df = pd.DataFrame(
        {
            "open": np.linspace(base_price, base_price + 5, num_rows),
            "high": np.linspace(base_price + 2, base_price + 8, num_rows),
            "low": np.linspace(base_price - 2, base_price + 3, num_rows),
            "close": np.linspace(base_price + 1, base_price + 6, num_rows),
            "volume": np.random.rand(num_rows) * 1000,
        },
        index=timestamps,
    )

    return df


@pytest.mark.asyncio
async def test_pair_info_enrichment_includes_timestamp_dt():
    """
    Test: when enriching pair_info from a DataFrame, timestamp_dt should be
    extracted from the index, even if it is NOT a DataFrame column.

    This is exactly the bug that was in production!
    """
    klines = create_mock_kline_df_with_datetime_index(100, 100.0)

    # Emulate what the controller does
    pair_info = {
        "symbol": "TESTUSDT",
        "last_price": 105.0,
        "atr": 1.0,
    }

    last_candle = klines.iloc[-1]
    pair_info.update(last_candle.to_dict())

    # IMPORTANT: to_dict() does NOT include the index!
    # Therefore timestamp_dt must be added separately

    # Check that after to_dict() timestamp_dt is missing
    assert "timestamp_dt" not in pair_info, (
        "to_dict() should not include the index. "
        "If this test fails, the data structure has changed."
    )

    # Now add timestamp_dt as the fixed controller does
    candle_timestamp = klines.index[-1]
    if hasattr(candle_timestamp, "to_pydatetime"):
        pair_info["timestamp_dt"] = candle_timestamp.to_pydatetime()
    else:
        pair_info["timestamp_dt"] = candle_timestamp

    # Check that timestamp_dt is now present
    assert "timestamp_dt" in pair_info
    assert pair_info["timestamp_dt"] is not None


@pytest.mark.asyncio
async def test_manage_position_receives_required_data():
    """
    Test: manage_position should receive all necessary data
    (high, low, timestamp_dt, tick_size) and NOT exit prematurely.
    """
    klines = create_mock_kline_df_with_datetime_index(100, 100.0)

    # Set specific values for the last candle
    klines.iloc[-1, klines.columns.get_loc("high")] = 105.0
    klines.iloc[-1, klines.columns.get_loc("low")] = 99.0

    # Emulate pair_info as in the controller AFTER the fix
    pair_info = {
        "symbol": "TESTUSDT",
        "last_price": 102.0,
        "atr": 1.0,
        "tick_size": 0.01,
    }

    last_candle = klines.iloc[-1]
    pair_info.update(last_candle.to_dict())

    # Add timestamp_dt from the index (as in the fixed controller)
    pair_info["timestamp_dt"] = klines.index[-1].to_pydatetime()

    # Create a strategy with positionManagement
    test_config = {
        "positionManagement": [
            {
                "id": "mng1",
                "type": "move_to_breakeven",
                "params": {
                    "target_type": "rr_multiplier",
                    "target_value": 1.0,  # 1R
                    "offset_pips": 2,
                },
            }
        ]
    }

    strategy = VisualBuilderStrategy(params={"config": test_config})

    # Create a test position
    # Entry: 100.0, SL: 98.0 (risk = 2.0), current high = 105.0 (profit = 5.0, RR = 2.5)
    position = BasePosition(
        symbol="TESTUSDT",
        direction=SignalDirection.LONG,
        entry_price=100.0,
        initial_quantity=1.0,
        remaining_quantity=1.0,
        entry_time=1000000.0,
        strategy="VisualBuilderStrategy",
        initial_stop_loss=98.0,
        current_sl_price=98.0,
        initial_take_profit=110.0,
        is_stop_at_be=False,
        client_order_id="test123",
    )

    # Add attributes expected by manage_position
    position.partial_targets = []
    position.partial_fills = []
    position.executions = []

    market_data = {"kline_1m": klines}

    # Call manage_position
    updated_position, exit_details = await strategy.manage_position(
        position, pair_info, market_data, None
    )

    # Check that the function did NOT exit prematurely (exit_details = None if the position is not closed)
    # and that is_stop_at_be became True (1R condition met at high=105)
    assert updated_position.is_stop_at_be, (
        f"Expected is_stop_at_be=True (RR={5.0 / 2.0}=2.5 >= 1.0), "
        f"but got is_stop_at_be={updated_position.is_stop_at_be}"
    )

    # Check that SL moved to BE
    expected_be_price = 100.0 + (2 * 0.01)  # entry + offset_pips * tick_size
    assert updated_position.current_sl_price == pytest.approx(
        expected_be_price, abs=0.01
    ), (
        f"Expected SL at BE around {expected_be_price}, "
        f"got {updated_position.current_sl_price}"
    )


@pytest.mark.asyncio
async def test_manage_position_exits_early_without_timestamp_dt():
    """
    Test: if timestamp_dt is missing, manage_position should
    exit prematurely WITHOUT changing the position (this was before the fix).

    This test documents the issue that was in production.
    """
    klines = create_mock_kline_df_with_datetime_index(100, 100.0)

    # pair_info WITHOUT timestamp_dt (as it was BEFORE the fix)
    pair_info = {
        "symbol": "TESTUSDT",
        "last_price": 102.0,
        "atr": 1.0,
        "tick_size": 0.01,
        "high": 105.0,
        "low": 99.0,
        # timestamp_dt intentionally missing!
    }

    test_config = {
        "positionManagement": [
            {
                "id": "mng1",
                "type": "move_to_breakeven",
                "params": {
                    "target_type": "rr_multiplier",
                    "target_value": 1.0,
                    "offset_pips": 2,
                },
            }
        ]
    }

    strategy = VisualBuilderStrategy(params={"config": test_config})

    position = BasePosition(
        symbol="TESTUSDT",
        direction=SignalDirection.LONG,
        entry_price=100.0,
        initial_quantity=1.0,
        remaining_quantity=1.0,
        entry_time=1000000.0,
        strategy="VisualBuilderStrategy",
        initial_stop_loss=98.0,
        current_sl_price=98.0,
        initial_take_profit=110.0,
        is_stop_at_be=False,
        client_order_id="test123",
    )
    position.partial_targets = []
    position.partial_fills = []
    position.executions = []

    market_data = {"kline_1m": klines}

    updated_position, exit_details = await strategy.manage_position(
        position, pair_info, market_data, None
    )

    # WITHOUT timestamp_dt the function exits early and does NOT change the position
    assert not updated_position.is_stop_at_be, (
        "Without timestamp_dt manage_position should exit early, "
        "and is_stop_at_be should remain False"
    )

    assert updated_position.current_sl_price == 98.0, (
        "Without timestamp_dt, SL should not have changed"
    )
