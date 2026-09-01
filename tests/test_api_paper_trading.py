# tests/test_api_paper_trading.py

import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock
from api import crud, models
from datetime import datetime, timezone

pytestmark = pytest.mark.asyncio


async def test_start_strategy_paper_mode(
    authenticated_client, test_user, db_session, mock_redis_client
):
    """
    Test starting a strategy in paper mode.
    It should trigger the Celery task.
    """
    config_id = "some_config_id"

    with patch(
        "api.crud.get_strategy_config", new_callable=AsyncMock
    ) as mock_get_config:
        mock_config = MagicMock(spec=models.StrategyConfig)
        mock_config.id = config_id
        mock_config.config_data = {}
        mock_config.user_id = test_user.id
        mock_config.name = "Test Strat"
        mock_config.description = "Desc"
        mock_config.symbol_selection_mode = "manual"
        mock_config.symbols = ["BTCUSDT"]
        mock_config.use_ml_confirmation = False
        mock_config.foundation_weights = {}
        mock_get_config.return_value = mock_config

        # Fetch the API key that was automatically added by the fixture
        active_keys = await crud.get_active_api_keys_for_user(db_session, test_user.id)
        assert len(active_keys) > 0, "test_user should have at least one active API key"

        response = await authenticated_client.post(
            "/api/v1/strategies", json={"config_id": config_id, "mode": "paper"}
        )

    assert response.status_code == 202
    data = response.json()["data"]
    assert data["mode"] == "paper"
    # Unified controller uses Redis for paper mode start now
    assert mock_redis_client.publish.call_count == 2
    publish_calls = mock_redis_client.publish.call_args_list
    start_strategy_call = None
    for call_args in publish_calls:
        channel, message_str = call_args[0]
        message_data = json.loads(message_str)
        if message_data.get("command") == "START_STRATEGY":
            start_strategy_call = message_data
            break
    assert start_strategy_call is not None


# Remove mocker from arguments
async def test_start_strategy_live_mode(
    authenticated_client, pro_user, db_session, mock_redis_client
):
    """
    Test starting a strategy in live mode.
    It should publish a command to Redis.
    """
    test_user = pro_user  # Use the user that authenticated_client is logged in as
    config_id = "some_config_id"

    with patch(
        "api.crud.get_strategy_config", new_callable=AsyncMock
    ) as mock_get_config:
        mock_config = MagicMock(spec=models.StrategyConfig)
        mock_config.id = config_id
        mock_config.config_data = {}
        mock_config.user_id = test_user.id
        mock_config.name = "Test Strat"
        mock_config.description = "Desc"
        mock_config.symbol_selection_mode = "manual"
        mock_config.symbols = ["BTCUSDT"]
        mock_config.use_ml_confirmation = False
        mock_config.foundation_weights = {}
        mock_get_config.return_value = mock_config

        # Fetch the API key that was automatically added by the fixture
        active_keys = await crud.get_active_api_keys_for_user(db_session, test_user.id)
        assert len(active_keys) > 0, "test_user should have at least one active API key"
        api_key_id = active_keys[0].id

        response = await authenticated_client.post(
            "/api/v1/strategies",
            json={"config_id": config_id, "mode": "live", "api_key_id": api_key_id},
        )

    assert response.status_code == 202
    data = response.json()["data"]
    assert data["mode"] == "live"

    assert mock_redis_client.publish.call_count == 2
    publish_calls = mock_redis_client.publish.call_args_list
    start_strategy_call = None
    for call_args in publish_calls:
        channel, message_str = call_args[0]
        message_data = json.loads(message_str)
        if message_data.get("command") == "START_STRATEGY":
            start_strategy_call = message_data
            break
    assert start_strategy_call is not None


# Correct path for patch
async def test_get_trades_paper_mode(authenticated_client, pro_user, db_session):
    """
    Test fetching only paper trades.
    """
    test_user = pro_user  # Use the user that authenticated_client is logged in as
    # Create mock trades in the database
    await crud.create_trade(
        db_session,
        user_id=test_user.id,
        trade_data={
            "trade_uuid": "live-trade-1",
            "timestamp_close": datetime.now(timezone.utc),
            "symbol": "BTCUSDT",
            "direction": "BUY",
            "entry_price": 1,
            "exit_price": 1,
            "pnl": 0,
            "commission": 0,
            "exit_reason": "",
            "quantity": 1,
        },
        trade_mode="LIVE",
    )
    await crud.create_trade(
        db_session,
        user_id=test_user.id,
        trade_data={
            "trade_uuid": "paper-trade-1",
            "timestamp_close": datetime.now(timezone.utc),
            "symbol": "BTCUSDT",
            "direction": "BUY",
            "entry_price": 1,
            "exit_price": 1,
            "pnl": 0,
            "commission": 0,
            "exit_reason": "",
            "quantity": 1,
        },
        trade_mode="PAPER",
    )
    await db_session.commit()

    response = await authenticated_client.get("/api/v1/trades?mode=paper")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["trades"][0]["trade_mode"] == "PAPER"


@patch("api.crud.init_or_reset_paper_wallet", new_callable=AsyncMock)
async def test_reset_paper_wallet(mock_reset, authenticated_client, test_user):
    """
    Test the endpoint for resetting the paper wallet.
    """
    mock_reset.return_value = [models.PaperWallet(asset="USDT", balance=10000.0)]

    response = await authenticated_client.post("/api/v1/account/paper/reset")

    assert response.status_code == 200
    data = response.json()["data"]

    mock_reset.assert_called_once()
    assert len(data) == 1
    assert data[0]["asset"] == "USDT"
    assert data[0]["balance"] == 10000.0
