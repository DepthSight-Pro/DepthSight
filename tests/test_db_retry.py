"""Transient DB-connection retry (night-run follow-up).

The 640-user night showed ~670 entry/balance failures with
"connection was closed in the middle of operation": PgBouncer recycling a
server connection mid-query under 28:1 multiplex. pool_pre_ping cannot
cover mid-operation kills, so the paper persist/read paths retry once on
transient connection errors - strictly pre-commit, with the in-memory
position restored.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot_module.db_retry import get_retry_attempts, is_transient_connection_error
from bot_module.paper_executor import PaperTradingExecutor
from bot_module.data_consumer import DataConsumer
from api import models


def _transient():
    return Exception("connection was closed in the middle of operation")


# --- matcher ---


def test_matcher_transient_messages():
    assert is_transient_connection_error(_transient())
    assert is_transient_connection_error(
        Exception("server closed the connection unexpectedly")
    )
    assert is_transient_connection_error(Exception("remaining connection slots"))
    assert is_transient_connection_error(Exception("SSL SYSCALL error: EOF detected"))


def test_matcher_transient_class_even_with_empty_message():
    exc = type("ConnectionDoesNotExistError", (Exception,), {})()
    assert str(exc) == ""
    assert is_transient_connection_error(exc)


def test_matcher_non_transient():
    assert not is_transient_connection_error(ValueError("bad quantity"))
    assert not is_transient_connection_error(Exception("UNIQUE violation"))
    assert not is_transient_connection_error(Exception(""))
    assert not is_transient_connection_error(None)


def test_retry_attempts_default_and_env(monkeypatch):
    monkeypatch.delenv("DB_TRANSIENT_RETRY_ATTEMPTS", raising=False)
    assert get_retry_attempts() == 2
    monkeypatch.setenv("DB_TRANSIENT_RETRY_ATTEMPTS", "4")
    assert get_retry_attempts() == 4
    monkeypatch.setenv("DB_TRANSIENT_RETRY_ATTEMPTS", "garbage")
    assert get_retry_attempts() == 2
    monkeypatch.setenv("DB_TRANSIENT_RETRY_ATTEMPTS", "0")
    assert get_retry_attempts() == 1


# --- persist retry ---


def _executor():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    consumer = MagicMock(spec=DataConsumer)
    consumer.get_latest_price = AsyncMock(return_value=50000.0)
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
    return PaperTradingExecutor(user_id=1, db_session=session, data_consumer=consumer)


@pytest.mark.asyncio
@patch("tasks.process_live_trade_analytics_task.delay", new_callable=MagicMock)
@patch("api.crud.create_trade", new_callable=AsyncMock)
@patch("api.crud.update_paper_wallet_balance", new_callable=AsyncMock)
async def test_place_order_retries_transient_wallet_failure(
    mock_update, mock_create, mock_celery
):
    """First wallet SELECT dies mid-operation -> rollback, retry, success
    with exactly one wallet effect and one trade row."""
    mock_update.side_effect = [_transient(), None]
    mock_create.return_value = models.Trade(id=1)
    ex = _executor()

    resp = await ex.place_order(
        symbol="BTCUSDT", side="BUY", order_type="MARKET", quantity=0.1
    )

    assert resp and not resp.get("error")
    assert resp["status"] == "FILLED"
    assert mock_update.call_count == 2
    mock_create.assert_called_once()
    assert ex._positions["BTCUSDT"]["quantity"] == pytest.approx(0.1)


@pytest.mark.asyncio
@patch("tasks.process_live_trade_analytics_task.delay", new_callable=MagicMock)
@patch("api.crud.create_trade", new_callable=AsyncMock)
@patch("api.crud.update_paper_wallet_balance", new_callable=AsyncMock)
async def test_place_order_no_retry_on_logic_error(
    mock_update, mock_create, mock_celery
):
    """A non-transient failure must keep the old single-attempt behaviour."""
    mock_update.side_effect = ValueError("bad quantity")
    ex = _executor()

    resp = await ex.place_order(
        symbol="BTCUSDT", side="BUY", order_type="MARKET", quantity=0.1
    )

    assert resp.get("error") is True
    assert resp["code"] == -1002
    assert mock_update.call_count == 1
    mock_create.assert_not_called()
    assert "BTCUSDT" not in ex._positions


@pytest.mark.asyncio
@patch("tasks.process_live_trade_analytics_task.delay", new_callable=MagicMock)
@patch("api.crud.create_trade", new_callable=AsyncMock)
@patch("api.crud.update_paper_wallet_balance", new_callable=AsyncMock)
async def test_place_order_no_retry_after_commit(
    mock_update, mock_create, mock_celery, monkeypatch
):
    """A transient failure AFTER commit (refresh) must not re-enter the
    loop: the wallet/trade writes are already durable."""
    mock_create.return_value = models.Trade(id=1)
    ex = _executor()
    ex.db.refresh = AsyncMock(side_effect=_transient())

    resp = await ex.place_order(
        symbol="BTCUSDT", side="BUY", order_type="MARKET", quantity=0.1
    )

    assert resp.get("error") is True
    assert mock_update.call_count == 1
    mock_create.assert_called_once()


# --- read-path retry ---


@pytest.mark.asyncio
@patch("api.crud.get_paper_wallet", new_callable=AsyncMock)
async def test_get_account_balance_retries_transient_read(mock_get):
    # Calls: _ensure attempt 1 (dies) -> _ensure attempt 2 (wallet found) ->
    # balance read.
    mock_get.side_effect = [
        _transient(),
        [models.PaperWallet(asset="USDT", balance=10000.0)],
        [models.PaperWallet(asset="USDT", balance=10000.0)],
    ]
    ex = _executor()

    balance = await ex.get_account_balance()

    assert balance is not None
    assert balance["USDT"]["free"] == "10000.0"
    assert mock_get.call_count == 3
