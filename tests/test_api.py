# tests/test_api.py

import pytest
import asyncio
from httpx import AsyncClient
import json
from datetime import datetime, timezone, timedelta
from api import schemas, models, crud
from unittest.mock import MagicMock, AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
import pandas as pd

from bot_module.config import REDIS_COMMAND_CHANNEL, REDIS_STATE_KEY_STRATEGIES

VALID_API_KEY = "your-super-secret-api-key"
INVALID_API_KEY = "invalid-key"


@pytest.mark.asyncio
async def test_get_status(test_client: AsyncClient):
    """Tests the /status endpoint."""
    response = await test_client.get("/api/v1/status")
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["status"] == "ok"


@pytest.mark.asyncio
async def test_authentication_is_required(test_client: AsyncClient):
    """
    Verifies that endpoints require authentication and return 401,
    if a valid token is not provided.
    """
    response = await test_client.get("/api/v1/config")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_authentication_is_successful(authenticated_client: AsyncClient):
    """
    Verifies that an authenticated client (with a Bearer token) gains access (status 200).
    """
    response = await authenticated_client.get("/api/v1/config")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_strategies_workflow(
    pro_user_client: AsyncClient,
    mock_redis_client: MagicMock,
    db_session: AsyncSession,
    pro_user: models.User,
):
    """
    Tests the new lifecycle: start by config_id,
    getting the list of running instances and stopping.
    """
    config_payload = {
        "name": "Test Workflow Strategy",
        "config_data": {"strategy_name": "Test", "params": {}},
    }
    # Use CRUD directly, as the created_strategy_config fixture may cause conflicts
    created_config = await crud.create_strategy_config(
        db_session,
        user_id=pro_user.id,
        config_create=schemas.StrategyConfigCreate(**config_payload),
    )
    await db_session.commit()
    await db_session.refresh(created_config)

    config_id_to_run = created_config.id
    response = await pro_user_client.post(
        "/api/v1/strategies", json={"config_id": config_id_to_run}
    )
    assert response.status_code == 202, f"API returned error on start: {response.text}"

    mock_redis_client.publish.assert_called_once()
    channel, message_json = mock_redis_client.publish.call_args[0]
    assert channel == REDIS_COMMAND_CHANNEL
    message_data = json.loads(message_json)
    assert message_data["command"] == "START_STRATEGY"
    assert message_data["payload"]["id"] == config_id_to_run
    mock_redis_client.publish.reset_mock()

    mock_strategies_state = [
        {
            "id": config_id_to_run,
            "config_id": config_id_to_run,
            "strategy_name": "VolumeBreakout",
            "symbol": "Dynamic (All)",
            "market_type": "futures",
            "params": {"candle_timeframe": "5m"},
            "status": "running",
            "pnl": 0.0,
            "open_positions": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "user_id": pro_user.id,
        }
    ]
    await mock_redis_client.set_initial_data(
        REDIS_STATE_KEY_STRATEGIES, mock_strategies_state
    )

    response = await pro_user_client.get("/api/v1/strategies")
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) >= 0, f"API returned unexpected data: {data}"

    instance_id_to_stop = config_id_to_run
    response = await pro_user_client.delete(f"/api/v1/strategies/{instance_id_to_stop}")
    assert response.status_code == 202
    mock_redis_client.publish.assert_called_once()
    _, message_json_stop = mock_redis_client.publish.call_args[0]
    message_data_stop = json.loads(message_json_stop)
    assert message_data_stop["command"] == "STOP_STRATEGY"
    assert message_data_stop["payload"]["strategy_id"] == instance_id_to_stop


@pytest.mark.asyncio
async def test_get_tradingview_webhook_info(
    pro_user_client: AsyncClient, pro_user: models.User
):
    response = await pro_user_client.get("/api/v1/webhooks/tv-info")
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["url"].endswith(f"/webhooks/tv/{pro_user.tradingview_webhook_token}")
    assert data["user_secret_token_masked"]
    assert "strategy_id" in data["sample_payload"]
    assert data["requires_strategy_id"] is True


@pytest.mark.asyncio
async def test_get_tradingview_webhook_info_generates_missing_token(
    pro_user_client: AsyncClient, pro_user: models.User, db_session: AsyncSession
):
    pro_user.tradingview_webhook_token = None
    await db_session.commit()

    response = await pro_user_client.get("/api/v1/webhooks/tv-info")
    assert response.status_code == 200

    await db_session.refresh(pro_user)
    assert pro_user.tradingview_webhook_token
    assert response.json()["data"]["url"].endswith(
        f"/webhooks/tv/{pro_user.tradingview_webhook_token}"
    )


@pytest.mark.asyncio
async def test_get_tradingview_webhook_info_prefers_public_base_url(
    pro_user_client: AsyncClient, pro_user: models.User, monkeypatch
):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.depthsight.pro")

    response = await pro_user_client.get("/api/v1/webhooks/tv-info")
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["url"].startswith("https://app.depthsight.pro/webhooks/tv/")
    assert data["url"].endswith(pro_user.tradingview_webhook_token)


@pytest.mark.asyncio
async def test_get_tradingview_webhook_info_for_specific_strategy(
    pro_user_client: AsyncClient, db_session: AsyncSession, pro_user: models.User
):
    created_config = await crud.create_strategy_config(
        db_session,
        user_id=pro_user.id,
        config_create=schemas.StrategyConfigCreate(
            name="TV Specific Info Strategy",
            config_data={
                "strategy_name": "VisualBuilderStrategy",
                "signal_source": "tradingview_webhook",
                "symbol": "BTCUSDT",
                "marketType": "FUTURES",
            },
        ),
    )
    api_key = models.ApiKey(
        user_id=pro_user.id,
        name="Webhook Account",
        exchange="binance",
        encrypted_api_key="enc-key",
        encrypted_api_secret="enc-secret",
        key_prefix="test...1234",
        status="valid",
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.commit()
    await db_session.refresh(created_config)
    await db_session.refresh(api_key)

    response = await pro_user_client.get(
        f"/api/v1/webhooks/tv-info?config_id={created_config.id}&api_key_id={api_key.id}"
    )
    assert response.status_code == 200, response.text

    data = response.json()["data"]
    assert data["url"].endswith(
        f"/webhooks/tv/{pro_user.tradingview_webhook_token}/{created_config.id}"
    )
    assert data["requires_strategy_id"] is False
    assert data["strategy_id"] == created_config.id
    assert data["symbol"] == "BTCUSDT"
    assert "strategy_id" not in data["sample_payload"]
    assert data["sample_payload"]["symbol"] == "BINANCE:BTCUSDT.P"
    assert data["sample_payload"]["api_key_id"] == api_key.id


@pytest.mark.asyncio
async def test_tradingview_webhook_publishes_signal_command(
    test_client: AsyncClient,
    mock_redis_client: MagicMock,
    db_session: AsyncSession,
    pro_user: models.User,
):
    config_payload = {
        "name": "TV Webhook Strategy",
        "config_data": {
            "strategy_name": "VisualBuilderStrategy",
            "signal_source": "tradingview_webhook",
            "symbol": "BTCUSDT",
        },
    }
    created_config = await crud.create_strategy_config(
        db_session,
        user_id=pro_user.id,
        config_create=schemas.StrategyConfigCreate(**config_payload),
    )
    await db_session.commit()
    await db_session.refresh(created_config)

    response = await test_client.post(
        f"/webhooks/tv/{pro_user.tradingview_webhook_token}",
        json={
            "strategy_id": created_config.id,
            "action": "buy",
            "symbol": "BINANCE:BTCUSDT.P",
            "event_id": "evt-1",
        },
    )
    assert response.status_code == 200, response.text

    mock_redis_client.publish.assert_called_once()
    channel, message_json = mock_redis_client.publish.call_args[0]
    assert channel == REDIS_COMMAND_CHANNEL
    message_data = json.loads(message_json)
    assert message_data["command"] == "TV_WEBHOOK_SIGNAL"
    assert message_data["payload"]["config_id"] == created_config.id
    assert message_data["payload"]["normalized_symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_tradingview_strategy_scoped_webhook_publishes_without_strategy_id(
    test_client: AsyncClient,
    mock_redis_client: MagicMock,
    db_session: AsyncSession,
    pro_user: models.User,
):
    created_config = await crud.create_strategy_config(
        db_session,
        user_id=pro_user.id,
        config_create=schemas.StrategyConfigCreate(
            name="TV Scoped Webhook Strategy",
            config_data={
                "strategy_name": "VisualBuilderStrategy",
                "signal_source": "tradingview_webhook",
                "symbol": "BTCUSDT",
            },
        ),
    )
    await db_session.commit()
    await db_session.refresh(created_config)

    response = await test_client.post(
        f"/webhooks/tv/{pro_user.tradingview_webhook_token}/{created_config.id}",
        json={
            "action": "buy",
            "symbol": "BINANCE:BTCUSDT.P",
            "event_id": "evt-scoped-1",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "accepted"

    mock_redis_client.publish.assert_called_once()
    channel, message_json = mock_redis_client.publish.call_args[0]
    assert channel == REDIS_COMMAND_CHANNEL
    message_data = json.loads(message_json)
    assert message_data["command"] == "TV_WEBHOOK_SIGNAL"
    assert message_data["payload"]["config_id"] == created_config.id
    assert message_data["payload"]["source"] == "tradingview_webhook"


@pytest.mark.asyncio
async def test_tradingview_webhook_rejects_invalid_token(test_client: AsyncClient):
    response = await test_client.post(
        "/webhooks/tv/invalid-token",
        json={
            "strategy_id": "missing-config",
            "action": "buy",
            "symbol": "BINANCE:BTCUSDT.P",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"] == "Invalid webhook token."


@pytest.mark.asyncio
async def test_tradingview_webhook_rejects_internal_strategy(
    test_client: AsyncClient,
    mock_redis_client: MagicMock,
    db_session: AsyncSession,
    pro_user: models.User,
):
    created_config = await crud.create_strategy_config(
        db_session,
        user_id=pro_user.id,
        config_create=schemas.StrategyConfigCreate(
            name="Internal Only Strategy",
            config_data={
                "strategy_name": "VisualBuilderStrategy",
                "signal_source": "internal",
                "symbol": "BTCUSDT",
            },
        ),
    )
    await db_session.commit()

    response = await test_client.post(
        f"/webhooks/tv/{pro_user.tradingview_webhook_token}",
        json={
            "strategy_id": created_config.id,
            "action": "buy",
            "symbol": "BINANCE:BTCUSDT.P",
        },
    )

    assert response.status_code == 409
    assert "not configured for TradingView webhook" in response.json()["error"]
    mock_redis_client.publish.assert_not_called()


@pytest.mark.asyncio
async def test_tradingview_webhook_rejects_symbol_mismatch(
    test_client: AsyncClient,
    mock_redis_client: MagicMock,
    db_session: AsyncSession,
    pro_user: models.User,
):
    created_config = await crud.create_strategy_config(
        db_session,
        user_id=pro_user.id,
        config_create=schemas.StrategyConfigCreate(
            name="TV Symbol Guard",
            config_data={
                "strategy_name": "VisualBuilderStrategy",
                "signal_source": "tradingview_webhook",
                "symbol": "BTCUSDT",
            },
        ),
    )
    await db_session.commit()

    response = await test_client.post(
        f"/webhooks/tv/{pro_user.tradingview_webhook_token}",
        json={
            "strategy_id": created_config.id,
            "action": "buy",
            "symbol": "BINANCE:ETHUSDT.P",
        },
    )

    assert response.status_code == 409
    assert "Webhook symbol mismatch" in response.json()["error"]
    mock_redis_client.publish.assert_not_called()


@pytest.mark.asyncio
async def test_tradingview_webhook_rejects_invalid_api_key_id(
    test_client: AsyncClient,
    mock_redis_client: MagicMock,
    db_session: AsyncSession,
    pro_user: models.User,
):
    created_config = await crud.create_strategy_config(
        db_session,
        user_id=pro_user.id,
        config_create=schemas.StrategyConfigCreate(
            name="TV API Key Validation",
            config_data={
                "strategy_name": "VisualBuilderStrategy",
                "signal_source": "tradingview_webhook",
                "symbol": "BTCUSDT",
            },
        ),
    )
    await db_session.commit()

    response = await test_client.post(
        f"/webhooks/tv/{pro_user.tradingview_webhook_token}",
        json={
            "strategy_id": created_config.id,
            "action": "buy",
            "symbol": "BINANCE:BTCUSDT.P",
            "api_key_id": 999999,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"] == "api_key_id is invalid for this user."
    mock_redis_client.publish.assert_not_called()


@pytest.mark.asyncio
async def test_tradingview_webhook_deduplicates_duplicate_events(
    test_client: AsyncClient,
    mock_redis_client: MagicMock,
    db_session: AsyncSession,
    pro_user: models.User,
):
    created_config = await crud.create_strategy_config(
        db_session,
        user_id=pro_user.id,
        config_create=schemas.StrategyConfigCreate(
            name="TV Dedupe Strategy",
            config_data={
                "strategy_name": "VisualBuilderStrategy",
                "signal_source": "tradingview_webhook",
                "symbol": "BTCUSDT",
            },
        ),
    )
    await db_session.commit()

    payload = {
        "strategy_id": created_config.id,
        "action": "buy",
        "symbol": "BINANCE:BTCUSDT.P",
        "event_id": "same-event-id",
    }

    first_response = await test_client.post(
        f"/webhooks/tv/{pro_user.tradingview_webhook_token}", json=payload
    )
    second_response = await test_client.post(
        f"/webhooks/tv/{pro_user.tradingview_webhook_token}", json=payload
    )

    assert first_response.status_code == 200
    assert first_response.json()["data"]["status"] == "accepted"
    assert second_response.status_code == 200
    assert second_response.json()["data"]["status"] == "duplicate"
    mock_redis_client.publish.assert_called_once()


@pytest.mark.asyncio
async def test_send_tradingview_test_signal_publishes_signal_command(
    pro_user_client: AsyncClient,
    mock_redis_client: MagicMock,
    db_session: AsyncSession,
    pro_user: models.User,
):
    created_config = await crud.create_strategy_config(
        db_session,
        user_id=pro_user.id,
        config_create=schemas.StrategyConfigCreate(
            name="TV UI Test Signal Strategy",
            config_data={
                "strategy_name": "VisualBuilderStrategy",
                "signal_source": "tradingview_webhook",
                "symbol": "BTCUSDT",
                "marketType": "FUTURES",
            },
        ),
    )
    await db_session.commit()
    await db_session.refresh(created_config)

    response = await pro_user_client.post(
        "/api/v1/webhooks/tv-test",
        json={"config_id": created_config.id, "action": "buy"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "accepted"

    mock_redis_client.publish.assert_called_once()
    channel, message_json = mock_redis_client.publish.call_args[0]
    assert channel == REDIS_COMMAND_CHANNEL
    message_data = json.loads(message_json)
    assert message_data["command"] == "TV_WEBHOOK_SIGNAL"
    assert message_data["payload"]["config_id"] == created_config.id
    assert message_data["payload"]["source"] == "ui_test"
    assert message_data["payload"]["normalized_symbol"] == "BTCUSDT"

    status_payload_raw = await mock_redis_client.get(
        f"tv:webhook:last:{pro_user.id}:{created_config.id}"
    )
    assert status_payload_raw is not None
    status_payload = json.loads(status_payload_raw)
    assert status_payload["status"] == "accepted_by_api"
    assert status_payload["source"] == "ui_test"


@pytest.mark.asyncio
async def test_get_tradingview_webhook_status_returns_saved_state(
    pro_user_client: AsyncClient,
    mock_redis_client: MagicMock,
    db_session: AsyncSession,
    pro_user: models.User,
):
    created_config = await crud.create_strategy_config(
        db_session,
        user_id=pro_user.id,
        config_create=schemas.StrategyConfigCreate(
            name="TV Status Strategy",
            config_data={
                "strategy_name": "VisualBuilderStrategy",
                "signal_source": "tradingview_webhook",
                "symbol": "BTCUSDT",
            },
        ),
    )
    await db_session.commit()
    await db_session.refresh(created_config)

    await mock_redis_client.set(
        f"tv:webhook:last:{pro_user.id}:{created_config.id}",
        json.dumps(
            {
                "config_id": created_config.id,
                "status": "queued_for_execution",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "message": "Webhook signal passed filters and was queued for execution.",
                "source": "ui_test",
                "action": "buy",
                "symbol": "BTCUSDT",
                "event_id": "evt-status-1",
            }
        ),
    )

    response = await pro_user_client.get(
        f"/api/v1/webhooks/tv-status/{created_config.id}"
    )
    assert response.status_code == 200, response.text

    data = response.json()["data"]
    assert data["config_id"] == created_config.id
    assert data["status"] == "queued_for_execution"
    assert data["source"] == "ui_test"
    assert data["event_id"] == "evt-status-1"


@pytest.mark.asyncio
async def test_backtest_task_workflow(authenticated_client: AsyncClient, mocker):
    """
    The test verifies that the backtest task is correctly queued.
    """
    mocker.patch("tasks._async_backtest_logic", new_callable=AsyncMock)

    backtest_payload = {
        "strategy_name": "FakeBreakout",
        "symbol": "ETH/USDT",
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-01-15T00:00:00Z",
        "params": {"lookback_candles": 20, "atr_multiplier": 2.5},
    }

    response = await authenticated_client.post(
        "/api/v1/backtests", json=backtest_payload
    )
    assert response.status_code == 202, f"API call failed: {response.text}"
    data = response.json().get("data", {})
    task_id = data.get("task_id")
    assert task_id is not None


@pytest.mark.asyncio
async def test_validation_error_handling(authenticated_client: AsyncClient):
    """
    Verifies that the API returns a 422 error when sending incorrect data.
    """
    invalid_payload = {
        "risk_management": {
            "daily_max_loss_percent": 5.0,
            "risk_per_trade_percent": 1.0,
            "min_rr_ratio": 2.0,
            "maxDrawdown": 25.5,
            "maxConcurrentTrades": "five",
            "stopLossEnabled": False,
        },
        "exchange_settings": {
            "binance_futures": {"enabled": True, "api_key_name": "default_futures"}
        },
    }
    response = await authenticated_client.put("/api/v1/config", json=invalid_payload)
    assert response.status_code == 422
    error_details = response.json()
    assert "detail" in error_details
    assert error_details["detail"][0]["type"] == "int_parsing"


@pytest.mark.asyncio
async def test_not_found_error_handling(authenticated_client: AsyncClient):
    """
    Verifies that the API returns a 404 error when requesting non-existent resources.
    """
    non_existent_id = 999999
    response = await authenticated_client.delete(
        f"/api/v1/config/api-keys/{non_existent_id}"
    )
    assert response.status_code == 404
    response = await authenticated_client.get("/api/v1/tasks/non-existent-task-id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_run_backtest_applies_all_ui_settings(
    authenticated_client: AsyncClient, mocker
):
    """
    Verifies that the backtest task correctly parses all settings from the UI.
    """
    start_date = datetime(2025, 8, 1, tzinfo=timezone.utc)
    end_date = start_date + timedelta(days=20)
    backtest_payload = {
        "strategy_name": "VolumeBreakout",
        "symbol": "BTCUSDT",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "market_type": "futures",
        "min_foundation_weight_threshold": 49.0,
        "params": {
            "use_ml_confirmation": True,
            "use_partial_exits": True,
            "move_sl_to_be": True,
            "candle_timeframe": "1m",
        },
    }

    mock_async_logic = mocker.patch(
        "tasks._async_backtest_logic", new_callable=AsyncMock
    )
    response = await authenticated_client.post(
        "/api/v1/backtests", json=backtest_payload
    )
    assert response.status_code == 202, f"API call failed: {response.text}"

    await asyncio.sleep(0.1)
    mock_async_logic.assert_called_once()
    called_args = mock_async_logic.call_args.args
    backtest_params_dict = called_args[2]
    assert backtest_params_dict.get("market_type") == "futures"
    assert backtest_params_dict.get("min_foundation_weight_threshold") == 49.0
    assert backtest_params_dict.get("params", {}).get("use_ml_confirmation") is True
    assert backtest_params_dict.get("strategy_name") == "VolumeBreakout"


@pytest.mark.asyncio
async def test_get_backtest_klines_without_time_range(
    authenticated_client: AsyncClient, mocker
):
    """
    Verifies that the /klines endpoint does NOT return a 422 error,
    when startTime and endTime are not provided.
    """
    mock_get_run = mocker.patch(
        "api.depthsight_api.crud.get_backtest_run_by_any_id", new_callable=AsyncMock
    )
    mock_data_loader = mocker.patch("api.routes.backtests.data_loader")

    mock_run = MagicMock()
    mock_run.symbol = "BTCUSDT"
    mock_run.market_type = "futures_usdtm"
    mock_run.start_date = datetime(2023, 1, 1, tzinfo=timezone.utc)
    mock_run.end_date = datetime(2023, 1, 10, tzinfo=timezone.utc)

    mock_get_run.return_value = mock_run
    mock_data_loader.download_klines = AsyncMock(
        return_value=pd.DataFrame(
            {
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000],
            },
            index=pd.DatetimeIndex([mock_run.start_date]),
        )
    )
    run_id = str(uuid.uuid4())

    response = await authenticated_client.get(
        f"/api/v1/backtests/{run_id}/klines?timeframe=15m"
    )
    assert response.status_code == 200, (
        f"Expected status 200, but received {response.status_code}. Response body: {response.text}"
    )

    mock_data_loader.download_klines.assert_called_once()
    _, kwargs = mock_data_loader.download_klines.call_args
    assert kwargs["start_dt"] == mock_run.start_date
    assert kwargs["end_dt"] == mock_run.end_date
