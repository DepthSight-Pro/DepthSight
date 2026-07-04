# tests/test_telegram_be_e2e_real.py
"""
E2E test with REAL notification sending to Telegram.
Goes through the entire path: strategy -> controller -> telegram_notifier -> Telegram API
"""

import pytest
import asyncio
from bot_module.telegram_notifier import TelegramNotifier
from bot_module.strategy import BaseStrategy
from bot_module.controller import LivePosition
from bot_module.datatypes import SignalDirection
from bot_module import config


@pytest.mark.asyncio
async def test_real_telegram_be_notification():
    """
    E2E test: Checking REAL sending of a BE notification to Telegram.

    This test:
    1. Creates a real TelegramNotifier with credentials from .env
    2. Emulates a position moving to BE
    3. Calls sl_moved_to_be directly
    4. Sends a REAL message to Telegram
    """
    # Checking that credentials are configured
    if (not config.TELEGRAM_BOT_TOKEN 
        or "YOUR_TELEGRAM_BOT_TOKEN" in config.TELEGRAM_BOT_TOKEN 
        or not config.TELEGRAM_CHAT_ID 
        or "YOUR_TELEGRAM_CHAT_ID" in str(config.TELEGRAM_CHAT_ID)):
        pytest.skip("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID are not configured in .env")

    print("\n=== TELEGRAM E2E TEST ===")
    print(
        f"Bot Token: {config.TELEGRAM_BOT_TOKEN[:10]}...{config.TELEGRAM_BOT_TOKEN[-5:]}"
    )
    print(f"Chat ID: {config.TELEGRAM_CHAT_ID}")

    # Create a real notifier
    notifier = TelegramNotifier(
        bot_token=config.TELEGRAM_BOT_TOKEN, chat_id=config.TELEGRAM_CHAT_ID
    )

    # Starting notifier (it will start the worker for sending)
    await notifier.start()

    try:
        # Calling sl_moved_to_be directly
        await notifier.sl_moved_to_be(
            symbol="TESTUSDT",
            new_sl_price=50010.0,
            entry_price=50000.0,
            entry_client_order_id="test-e2e-entry-123",
            tick_size=0.01,
            chat_id=config.TELEGRAM_CHAT_ID,
            reason="[E2E TEST] R:R 1.5 reached",
            diagnostic_data={
                "initial_sl": 49000.0,
                "current_rr": 1.5,
                "pnl_per_unit": 500.0,
                "candle_time": "2026-01-01 21:30:00",
            },
        )

        # Give time for sending
        print("Waiting for message sending...")
        await asyncio.sleep(3)

        print("✅ Message should have been sent to Telegram!")
        print("Check the chat!")

    finally:
        await notifier.stop()


@pytest.mark.asyncio
async def test_full_chain_strategy_to_telegram():
    """
    Full E2E: strategy._handle_move_to_breakeven -> controller -> telegram
    """
    if (not config.TELEGRAM_BOT_TOKEN 
        or "YOUR_TELEGRAM_BOT_TOKEN" in config.TELEGRAM_BOT_TOKEN 
        or not config.TELEGRAM_CHAT_ID 
        or "YOUR_TELEGRAM_CHAT_ID" in str(config.TELEGRAM_CHAT_ID)):
        pytest.skip("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID are not configured in .env")

    print("\n=== FULL CHAIN E2E TEST ===")

    # 1. Creating a strategy with move_to_breakeven configuration
    strategy_config = {
        "config": {
            "positionManagement": [
                {
                    "type": "move_to_breakeven",
                    "params": {
                        "target_type": "rr_multiplier",
                        "target_value": 1.0,  # At R:R = 1, move to BE
                        "offset_pips": 2,
                    },
                }
            ]
        }
    }

    strategy = BaseStrategy(params=strategy_config)

    # 2. Creating a position that is ALREADY in profit (so the BE condition triggers)
    position = LivePosition(
        symbol="BTCUSDT",
        direction=SignalDirection.LONG,
        entry_price=50000.0,
        initial_quantity=1.0,
        remaining_quantity=1.0,
        entry_time=1000,
        strategy="TestStrategy",
        initial_stop_loss=49000.0,  # Risk = 1000
        current_sl_price=49000.0,
        initial_take_profit=55000.0,
        entry_client_order_id="e2e-test-entry",
        status="OPEN",
        is_stop_at_be=False,
    )

    # 3. pair_info with a price that gives R:R > 1
    pair_info = {
        "symbol": "BTCUSDT",
        "high": 51500.0,  # +1500 from entry = R:R 1.5
        "low": 50500.0,
        "close": 51000.0,
        "tick_size": 0.01,
        "timestamp_dt": "2026-01-01 21:30:00",
        "current_candle_index": 100,
        "is_live_mode": True,
    }

    market_data = {}

    # 4. Call manage_position
    print("Calling manage_position...")
    print(
        f"Before: is_stop_at_be={position.is_stop_at_be}, SL={position.current_sl_price}"
    )

    updated_position, exit_details = await strategy.manage_position(
        position, pair_info, market_data, None
    )

    print(
        f"After: is_stop_at_be={updated_position.is_stop_at_be}, SL={updated_position.current_sl_price}"
    )
    print(f"be_trigger_reason={getattr(updated_position, 'be_trigger_reason', 'N/A')}")

    # 5. Checking that the flag is set
    assert updated_position.is_stop_at_be, (
        f"is_stop_at_be should be True, but got {updated_position.is_stop_at_be}"
    )

    # 6. If the flag is set - send a real notification
    if updated_position.is_stop_at_be:
        print("\n✅ Flag is_stop_at_be=True is set!")
        print("Sending real notification...")

        notifier = TelegramNotifier(
            bot_token=config.TELEGRAM_BOT_TOKEN, chat_id=config.TELEGRAM_CHAT_ID
        )
        await notifier.start()

        try:
            await notifier.sl_moved_to_be(
                symbol=updated_position.symbol,
                new_sl_price=updated_position.current_sl_price,
                entry_price=position.entry_price,
                entry_client_order_id=position.entry_client_order_id,
                tick_size=pair_info["tick_size"],
                chat_id=config.TELEGRAM_CHAT_ID,
                reason=getattr(updated_position, "be_trigger_reason", "Test"),
                diagnostic_data=getattr(updated_position, "be_diagnostic_data", {}),
            )

            await asyncio.sleep(3)
            print("✅ Notification sent! Check Telegram!")

        finally:
            await notifier.stop()
    else:
        pytest.fail("is_stop_at_be is NOT set! Problem in the strategy!")


if __name__ == "__main__":
    # To run directly: python -m tests.test_telegram_be_e2e_real
    asyncio.run(test_real_telegram_be_notification())
