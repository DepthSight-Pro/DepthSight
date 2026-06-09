# FILE: tests/test_paper_executor.py

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from bot_module.paper_executor import PaperTradingExecutor
from bot_module.data_consumer import DataConsumer
from api import models

# All tests in this file will be asynchronous
pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_db_session():
    """Fixture for an asynchronous DB session."""
    session = AsyncMock()
    # Mock commit and rollback to avoid AttributeError errors
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def mock_data_consumer():
    """Fixture for DataConsumer. Allows controlling the simulated price."""
    consumer = MagicMock(spec=DataConsumer)
    # get_latest_price will be an AsyncMock so that we can change its return_value in tests
    consumer.get_latest_price = AsyncMock(return_value=50000.0)

    # Mock for opening the initial position
    consumer.get_latest_depth = AsyncMock(
        return_value={
            "aggregated_depth": {
                "bids": [{"avg_price": 49999.0, "notional": 100000.0}],
                "asks": [{"avg_price": 50001.0, "notional": 100000.0}],
            },
            "full_l2_depth": {
                "bids": [["49999.5", "1.0"]],
                "asks": [["50000.5", "1.0"]],
            },
        }
    )
    return consumer


@pytest.fixture
def paper_executor(mock_db_session, mock_data_consumer):
    """Fixture for creating a PaperTradingExecutor instance with mocks."""
    return PaperTradingExecutor(
        user_id=1, db_session=mock_db_session, data_consumer=mock_data_consumer
    )


# --- Old tests for checking basic functionality ---


async def test_executor_initialization(
    paper_executor, mock_db_session, mock_data_consumer
):
    assert paper_executor.user_id == 1
    assert paper_executor.db == mock_db_session
    assert paper_executor.data_consumer == mock_data_consumer


@patch("api.crud.get_paper_wallet", new_callable=AsyncMock)
async def test_get_account_balance_existing(mock_get_wallet, paper_executor):
    mock_get_wallet.return_value = [models.PaperWallet(asset="USDT", balance=10000.0)]
    balance = await paper_executor.get_account_balance()
    assert balance is not None
    assert balance["USDT"]["free"] == "10000.0"


# --- NEW TEST: Full trade lifecycle ---


@patch("tasks.process_live_trade_analytics_task.delay", new_callable=MagicMock)
@patch("api.crud.create_trade", new_callable=AsyncMock)
@patch("api.crud.update_paper_wallet_balance", new_callable=AsyncMock)
async def test_full_trade_lifecycle_tp_hit(
    mock_update_balance,
    mock_create_trade,
    mock_celery_task,
    paper_executor,
    mock_data_consumer,
):
    """
    Tests the full cycle: opening -> setting SL/TP -> TP trigger -> closing.
    """
    # --- 1. ARRANGE: Setting parameters and initial state ---
    symbol = "BTCUSDT"
    entry_quantity = 0.1
    entry_price = 50001.0
    tp_price = 51000.0
    sl_price = 49000.0

    mock_data_consumer.get_latest_price.return_value = entry_price
    mock_create_trade.return_value = models.Trade(id=1)

    # --- 2. ACT: Opening a LONG position ---
    entry_response = await paper_executor.place_order(
        symbol=symbol, side="BUY", order_type="MARKET", quantity=entry_quantity
    )

    # --- ASSERT: Checking position opening ---
    assert entry_response and not entry_response.get("error")
    assert entry_response["status"] == "FILLED"
    assert paper_executor._positions[symbol]["quantity"] == entry_quantity
    assert paper_executor._positions[symbol]["avg_entry_price"] == pytest.approx(
        entry_price
    )
    mock_update_balance.assert_called_once()
    assert mock_update_balance.call_args[0][3] < 0
    mock_create_trade.assert_called_once()

    # --- 3. ACT: Placing Take-Profit and Stop-Loss ---
    tp_response = await paper_executor.place_order(
        symbol=symbol,
        side="SELL",
        order_type="LIMIT",
        quantity=entry_quantity,
        price=tp_price,
    )
    sl_response = await paper_executor.place_order(
        symbol=symbol,
        side="SELL",
        order_type="STOP_MARKET",
        quantity=entry_quantity,
        stopPrice=sl_price,
    )
    assert tp_response["status"] == "NEW"
    assert sl_response["status"] == "NEW"
    assert len(paper_executor._open_orders) == 2

    # --- 4. ACT: Simulate price growth and call order check ---
    print("\nSimulating price growth for TP trigger...")
    mock_data_consumer.get_latest_price.return_value = tp_price + 1.0

    # Updating the order book mock to match the new price ---
    # When closing LONG (SELL MARKET), the simulator will look at 'bids'.
    # We must substitute our TP price there to simulate execution at it.
    mock_data_consumer.get_latest_depth.return_value = {
        "aggregated_depth": {
            "bids": [{"avg_price": tp_price, "notional": 100000.0}],
            "asks": [{"avg_price": tp_price + 2.0, "notional": 100000.0}],
        },
        "full_l2_depth": {
            "bids": [[str(tp_price), "1.0"]],
            "asks": [[str(tp_price + 2.0), "1.0"]],
        },
    }

    await paper_executor.check_open_orders()
    await asyncio.sleep(0.01)

    # --- 5. ASSERT: Checking the TP trigger result ---
    assert not paper_executor._positions, "Position was not removed after TP trigger"
    assert len(paper_executor._open_orders) == 1, (
        "Executed TP order was not removed from _open_orders"
    )

    remaining_order = list(paper_executor._open_orders.values())[0]
    assert remaining_order["type"] == "STOP_MARKET"

    assert mock_update_balance.call_count == 2
    assert mock_create_trade.call_count == 2

    last_trade_call_kwargs = mock_create_trade.call_args.kwargs
    assert "trade_data" in last_trade_call_kwargs
    pnl = last_trade_call_kwargs["trade_data"]["pnl"]

    # Expected PnL calculation changed because the TP execution price is now equal to tp_price, not entry_price
    expected_pnl = (tp_price - entry_price) * entry_quantity
    assert pnl == pytest.approx(expected_pnl, rel=0.01)

    print("TP trigger check passed successfully.")
