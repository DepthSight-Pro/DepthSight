# tests/test_api_full_coverage.py

import pytest
import uuid
import json
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timezone

from api import schemas, crud, models
from bot_module.config import (
    REDIS_STATE_KEY_PORTFOLIO,
    REDIS_STATE_KEY_POSITIONS,
    REDIS_STATE_KEY_STRATEGIES,
)

# Marker for all tests in this file
pytestmark = pytest.mark.asyncio

# --- Classes with tests ---


class TestAuthentication:
    """Group of tests to verify authentication and authorization."""

    async def test_unprotected_endpoint_is_accessible(self, test_client: AsyncClient):
        response = await test_client.get("/api/v1/status")
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "ok"

    @pytest.mark.parametrize(
        "url, method",
        [
            ("/api/v1/config", "GET"),
            ("/api/v1/strategies", "GET"),
            ("/api/v1/backtests", "POST"),
        ],
    )
    async def test_protected_endpoints_return_401_without_token(
        self, test_client: AsyncClient, url: str, method: str
    ):
        if method.upper() == "GET":
            response = await test_client.get(url)
        else:
            response = await test_client.post(url, json={})

        assert response.status_code == 401

    async def test_login_with_invalid_credentials_returns_401(
        self, test_client: AsyncClient
    ):
        response = await test_client.post(
            "/api/v1/token", data={"username": "testuser", "password": "wrongpassword"}
        )
        assert response.status_code == 401
        error_response = response.json()
        assert "error" in error_response
        assert "Incorrect username or password" in error_response["error"]


class TestGeneralConfigEndpoints:
    """Tests for the main configuration endpoints (/config)."""

    async def test_get_config_returns_user_config(
        self, authenticated_client: AsyncClient, pro_user: models.User
    ):
        """Test for retrieving the full user configuration."""
        response = await authenticated_client.get("/api/v1/config")
        assert response.status_code == 200
        config_data = response.json()["data"]
        # Use pro_user, which corresponds to authenticated_client
        assert config_data["userId"] == pro_user.id

    async def test_update_config_succeeds(self, authenticated_client: AsyncClient):
        """Test for successful partial configuration update."""
        update_payload = {
            "risk_management": {
                "daily_max_loss_percent": 5.0,
                "risk_per_trade_percent": 1.0,
                "min_rr_ratio": 2.0,
                "maxDrawdown": 15.5,
                "maxConcurrentTrades": 8,
                "stopLossEnabled": False,
                "defaultStopLossPercent": 2.0,
            },
            "exchange_settings": {
                "binance_futures": {"enabled": True, "api_key_name": "default_futures"}
            },
        }
        response = await authenticated_client.put("/api/v1/config", json=update_payload)
        assert response.status_code == 200, f"API returned error: {response.text}"
        data = response.json()["data"]
        assert data["riskManagement"]["maxDrawdown"] == 15.5
        assert data["riskManagement"]["maxConcurrentTrades"] == 8

    async def test_add_and_delete_symbol_succeeds(
        self, authenticated_client: AsyncClient
    ):
        symbol_to_add = "ADAUSDT"

        add_response = await authenticated_client.post(
            "/api/v1/config/datasources/symbols", json={"symbol": symbol_to_add}
        )
        assert add_response.status_code == 200
        assert symbol_to_add in add_response.json()["data"]["symbols"]

        delete_response = await authenticated_client.delete(
            f"/api/v1/config/datasources/symbols/{symbol_to_add}"
        )
        assert delete_response.status_code == 200
        assert symbol_to_add not in delete_response.json()["data"]["symbols"]

    @pytest.mark.parametrize(
        "invalid_payload",
        [
            {"risk_management": {"maxConcurrentTrades": "not-a-number"}},
            {"notifications": {"emailEnabled": "not-a-boolean"}},
        ],
    )
    async def test_update_config_with_invalid_types_returns_422(
        self, authenticated_client: AsyncClient, invalid_payload
    ):
        full_payload = {
            "risk_management": {
                "daily_max_loss_percent": 1,
                "risk_per_trade_percent": 1,
                "min_rr_ratio": 1,
                "maxDrawdown": 1,
                "maxConcurrentTrades": 1,
                "stopLossEnabled": True,
                **(invalid_payload.get("risk_management", {})),
            },
            "exchange_settings": {
                "binance_futures": {"enabled": True, "api_key_name": "d"}
            },
            "notifications": {
                "emailEnabled": False,
                "telegramEnabled": False,
                **(invalid_payload.get("notifications", {})),
            },
        }
        response = await authenticated_client.put("/api/v1/config", json=full_payload)
        assert response.status_code == 422


class TestStrategyConfigEndpoints:
    """Full set of tests for CRUD operations with strategy configurations."""

    async def test_create_and_delete_config_workflow(
        self, authenticated_client: AsyncClient
    ):
        payload = {"name": f"Workflow Test {uuid.uuid4()}", "config_data": {"p": 1}}
        create_response = await authenticated_client.post(
            "/api/v1/strategies/config", json=payload
        )
        assert create_response.status_code == 201
        config_id = create_response.json()["data"]["id"]

        get_response = await authenticated_client.get(
            f"/api/v1/strategies/config/{config_id}"
        )
        assert get_response.status_code == 200
        assert get_response.json()["data"]["name"] == payload["name"]

        delete_response = await authenticated_client.delete(
            f"/api/v1/strategies/config/{config_id}"
        )
        assert delete_response.status_code == 204

        get_after_delete_response = await authenticated_client.get(
            f"/api/v1/strategies/config/{config_id}"
        )
        assert get_after_delete_response.status_code == 404

    async def test_create_config_with_valid_data_returns_201(
        self, authenticated_client: AsyncClient
    ):
        payload = {
            "name": f"My New Strategy {uuid.uuid4()}",
            "config_data": {"param": "value"},
        }
        response = await authenticated_client.post(
            "/api/v1/strategies/config", json=payload
        )
        assert response.status_code == 201
        assert response.json()["data"]["name"] == payload["name"]

    async def test_get_all_configs_returns_list(
        self, authenticated_client: AsyncClient, created_strategy_config: dict
    ):
        response = await authenticated_client.get("/api/v1/strategies/config")
        assert response.status_code == 200
        data = response.json()["data"]
        assert isinstance(data, list)
        assert any(c["id"] == created_strategy_config["id"] for c in data)

    async def test_get_config_by_id_succeeds(
        self, authenticated_client: AsyncClient, created_strategy_config: dict
    ):
        config_id = created_strategy_config["id"]
        response = await authenticated_client.get(
            f"/api/v1/strategies/config/{config_id}"
        )
        assert response.status_code == 200
        assert response.json()["data"]["id"] == config_id

    async def test_update_config_succeeds(
        self, authenticated_client: AsyncClient, created_strategy_config: dict
    ):
        config_id = created_strategy_config["id"]
        update_payload = {"name": "Updated Name"}
        response = await authenticated_client.put(
            f"/api/v1/strategies/config/{config_id}", json=update_payload
        )
        assert response.status_code == 200
        assert response.json()["data"]["name"] == update_payload["name"]

    async def test_delete_config_succeeds_and_returns_404_on_next_get(
        self, authenticated_client: AsyncClient, current_user: models.User
    ):
        payload = {"name": f"To Be Deleted {uuid.uuid4()}", "config_data": {}}
        create_response = await authenticated_client.post(
            "/api/v1/strategies/config", json=payload
        )
        config_id = create_response.json()["data"]["id"]

        delete_response = await authenticated_client.delete(
            f"/api/v1/strategies/config/{config_id}"
        )
        assert delete_response.status_code == 204

        get_response = await authenticated_client.get(
            f"/api/v1/strategies/config/{config_id}"
        )
        assert get_response.status_code == 404

    async def test_delete_config_succeeds(
        self, authenticated_client: AsyncClient, created_strategy_config: dict
    ):
        config_id = created_strategy_config["id"]
        delete_response = await authenticated_client.delete(
            f"/api/v1/strategies/config/{config_id}"
        )
        assert delete_response.status_code == 204
        get_response = await authenticated_client.get(
            f"/api/v1/strategies/config/{config_id}"
        )
        assert get_response.status_code == 404

    @pytest.mark.skip(reason="Endpoint /strategies/templates was removed from API")
    async def test_get_templates_returns_list(self, authenticated_client: AsyncClient):
        response = await authenticated_client.get("/api/v1/strategies/templates")
        assert response.status_code == 200
        data = response.json()["data"]
        assert isinstance(data, list)
        assert len(data) > 0
        assert "name" in data[0]
        assert "default_params" in data[0]

    @pytest.mark.parametrize(
        "invalid_payload, expected_error_part",
        [
            ({"config_data": {}}, "Field required"),
            ({"name": "Test"}, "Field required"),
            ({"name": 123, "config_data": {}}, "Input should be a valid string"),
            (
                {"name": "Test", "config_data": "not a dict"},
                "Input should be a valid dictionary",
            ),
        ],
    )
    async def test_create_config_with_invalid_data_returns_422(
        self,
        authenticated_client: AsyncClient,
        invalid_payload: dict,
        expected_error_part: str,
    ):
        response = await authenticated_client.post(
            "/api/v1/strategies/config", json=invalid_payload
        )
        assert response.status_code == 422
        error_details = response.json()
        assert "detail" in error_details
        assert any(expected_error_part in e["msg"] for e in error_details["detail"])


class TestPortfolioAndPositions:
    """Tests for portfolio and open positions endpoints."""

    async def test_get_portfolio_status_succeeds(
        self,
        authenticated_client: AsyncClient,
        override_redis_client: MagicMock,
        pro_user: models.User,
        db_session: AsyncSession,
    ):
        """Tests retrieving the portfolio status from Redis."""
        # We need to remove the API key to force the fallback to Redis
        await db_session.execute(
            delete(models.ApiKey).where(models.ApiKey.user_id == pro_user.id)
        )
        await db_session.commit()

        mock_portfolio_state = {
            "user_id": pro_user.id,
            "total_wallet_balance": 9800.0,
            "total_equity": 9876.54,
            "today_pnl": -50.1,
            "is_trading_allowed": True,
            "consecutive_losses": 1,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        # API expects a portfolio object, not a list. Appending the :1 suffix to match the :* pattern
        await override_redis_client.set_initial_data(
            f"{REDIS_STATE_KEY_PORTFOLIO}:{pro_user.id}:1", mock_portfolio_state
        )
        response = await authenticated_client.get("/api/v1/portfolio")
        assert response.status_code == 200
        # API maps 'total_equity' to 'balance'
        assert (
            response.json()["data"]["balance"] == mock_portfolio_state["total_equity"]
        )

    async def test_get_portfolio_status_when_not_set_returns_404(
        self,
        authenticated_client: AsyncClient,
        override_redis_client: MagicMock,
        pro_user: models.User,
        db_session: AsyncSession,
    ):
        # We need to remove the API key to force the fallback to Redis, which then should return 404 if no data is there
        await db_session.execute(
            delete(models.ApiKey).where(models.ApiKey.user_id == pro_user.id)
        )
        await db_session.commit()

        await override_redis_client.delete(
            f"{REDIS_STATE_KEY_PORTFOLIO}:{pro_user.id}:1"
        )
        response = await authenticated_client.get("/api/v1/portfolio")
        assert response.status_code == 404

    async def test_get_positions_filters_by_user(
        self,
        authenticated_client: AsyncClient,
        override_redis_client: MagicMock,
        pro_user: models.User,
    ):
        # Use pro_user, which corresponds to authenticated_client
        mock_positions = [
            {
                "id": "pos1",
                "user_id": pro_user.id,
                "symbol": "BTCUSDT",
                "strategy": "s1",
                "direction": "LONG",
                "size": 0.1,
                "entry_price": 70000,
                "mark_price": 71000,
                "pnl": 100,
                "pnl_percent": 1,
                "entry_time": "...",
                "mode": "live",
            },
            {
                "id": "pos2",
                "user_id": 999,
                "symbol": "ETHUSDT",
                "strategy": "s2",
                "direction": "SHORT",
                "size": 1,
                "entry_price": 3500,
                "mark_price": 3400,
                "pnl": 100,
                "pnl_percent": 2.8,
                "entry_time": "...",
                "mode": "live",
            },
        ]
        await override_redis_client.set_initial_data(
            f"{REDIS_STATE_KEY_POSITIONS}:{pro_user.id}:1", mock_positions
        )
        response = await authenticated_client.get("/api/v1/positions")
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["id"] == "pos1"

    async def test_emergency_stop_publishes_command(
        self,
        authenticated_client: AsyncClient,
        override_redis_client: MagicMock,
        pro_user: models.User,
    ):
        response = await authenticated_client.delete("/api/v1/portfolio/positions")
        assert response.status_code == 202
        override_redis_client.publish.assert_called_once()
        channel, message_str = override_redis_client.publish.call_args[0]
        message_data = json.loads(message_str)
        # API usually sends 'command', checking both to be safe
        assert (
            message_data.get("command") == "EMERGENCY_STOP"
            or message_data.get("type") == "EMERGENCY_STOP"
        )
        # Compare user_id as strings, since a string comes from JSON
        assert str(message_data["payload"]["user_id"]) == str(pro_user.id)


class TestLiveStrategyEndpoints:
    """Tests for strategy lifecycle management (via Redis)."""

    # Changed the test signature to use the correct fixtures.
    async def test_start_strategy_publishes_command_to_redis(
        self,
        pro_user_client: AsyncClient,
        db_session: AsyncSession,
        override_redis_client: MagicMock,
        pro_user: models.User,
    ):
        # Create the config on behalf of the same user
        config = await crud.create_strategy_config(
            db_session,
            user_id=pro_user.id,
            config_create=schemas.StrategyConfigCreate(name="test", config_data={}),
        )
        await db_session.commit()

        response = await pro_user_client.post(
            "/api/v1/strategies", json={"config_id": config.id}
        )
        assert response.status_code == 202
        override_redis_client.publish.assert_called_once()
        channel, message_str = override_redis_client.publish.call_args[0]
        message_data = json.loads(message_str)
        assert message_data.get("command") == "START_STRATEGY"
        assert message_data["payload"]["id"] == config.id
        assert str(message_data["payload"]["user_id"]) == str(pro_user.id)

    # Replaced 'authenticated_client' with 'pro_user_client'
    async def test_list_running_strategies_reads_from_redis(
        self,
        pro_user_client: AsyncClient,
        override_redis_client: MagicMock,
        pro_user: models.User,
    ):
        mock_strategies_state = [
            {
                "id": "s1",
                "user_id": pro_user.id,
                "strategy_name": "s_a",
                "symbol": "A",
                "market_type": "f",
                "params": {},
                "status": "r",
                "pnl": 0,
                "open_positions": 0,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "mode": "live",
            },
            {
                "id": "s2",
                "user_id": 999,
                "strategy_name": "s_b",
                "symbol": "B",
                "market_type": "f",
                "params": {},
                "status": "r",
                "pnl": 0,
                "open_positions": 0,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "mode": "live",
            },
        ]
        await override_redis_client.set_initial_data(
            f"{REDIS_STATE_KEY_STRATEGIES}:{pro_user.id}:1", mock_strategies_state
        )
        response = await pro_user_client.get("/api/v1/strategies")
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["id"] == "s1"

    async def test_stop_strategy_publishes_command_to_redis(
        self,
        pro_user_client: AsyncClient,
        override_redis_client: MagicMock,
        pro_user: models.User,
    ):
        instance_id_to_stop = "running_strat_123"
        response = await pro_user_client.delete(
            f"/api/v1/strategies/{instance_id_to_stop}"
        )
        assert response.status_code == 202  # Expecting 202 Accepted
        override_redis_client.publish.assert_called_once()
        channel, message_str = override_redis_client.publish.call_args[0]
        message_data = json.loads(message_str)
        assert message_data.get("command") == "STOP_STRATEGY"
        assert message_data["payload"]["strategy_id"] == instance_id_to_stop
        assert str(message_data["payload"]["user_id"]) == str(pro_user.id)


class TestBacktestEndpoints:
    """Tests for backtest management endpoints."""

    async def test_run_backtest_with_valid_data_returns_202(
        self, authenticated_client: AsyncClient, mocker
    ):
        mocker.patch(
            "api.celery_app.celery_app.send_task",
            return_value=MagicMock(id="mock-task-id"),
        )
        mocker.patch(
            "api.dependencies.require_permission",
            return_value=lambda feature: lambda user, redis_client: user,
        )
        payload = {
            "strategy_name": "TS",
            "symbol": "BTC/USDT",
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": "2024-01-02T00:00:00Z",
        }
        response = await authenticated_client.post("/api/v1/backtests", json=payload)
        assert response.status_code == 202
        assert "task_id" in response.json()["data"]

    @pytest.mark.parametrize(
        "invalid_payload",
        [
            {
                "strategy_name": "TestStrategy",
                "symbol": "BTC/USDT",
                "start_date": "2024-01-02",
                "end_date": "2024-01-01",
            },
            {
                "symbol": "BTC/USDT",
                "start_date": "2024-01-01",
                "end_date": "2024-01-02",
            },
        ],
    )
    async def test_run_backtest_with_invalid_data_returns_422(
        self, authenticated_client: AsyncClient, invalid_payload: dict, mocker
    ):
        mocker.patch(
            "api.dependencies.require_permission",
            return_value=lambda feature: lambda user, redis_client: user,
        )
        response = await authenticated_client.post(
            "/api/v1/backtests", json=invalid_payload
        )
        assert response.status_code == 422

    # Removed the `celery_no_eager` fixture because it is not defined and not needed when mocking.
    async def test_backtest_full_workflow(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
        mocker,
        pro_user: models.User,
    ):
        # Use pro_user instead of current_user
        mock_logic = mocker.patch("tasks._async_backtest_logic", new_callable=AsyncMock)
        mock_logic.return_value = {
            "kpi_results": {"total_pnl": 100},
            "equity_curve": [],
        }

        # Mock Celery so it doesn't actually execute the task, but just returns an ID
        mock_celery_task = MagicMock(id=f"mock-task-{uuid.uuid4()}")
        mocker.patch(
            "api.celery_app.celery_app.send_task",
            return_value=mock_celery_task,
        )

        payload = {
            "strategy_name": "FakeBreakout",
            "symbol": "ETH/USDT",
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": "2024-01-02T00:00:00Z",
        }
        run_response = await authenticated_client.post(
            "/api/v1/backtests", json=payload
        )
        assert run_response.status_code == 202
        task_id = run_response.json()["data"]["task_id"]

        # Simulate that the task has completed and created DB records for the correct user
        task_in_db = models.Task(
            user_id=pro_user.id,
            task_id=task_id,
            task_type="backtest",
            parameters=payload,
        )
        db_session.add(task_in_db)

        backtest_run_in_db = models.BacktestRun(
            id=str(uuid.uuid4()),
            user_id=pro_user.id,
            task_id=task_id,
            strategy_name=payload["strategy_name"],
            symbol=payload["symbol"],
            start_date=datetime.now(timezone.utc),
            end_date=datetime.now(timezone.utc),
            initial_balance=10000,
            parameters_json=payload,
            status="COMPLETED",
            kpi_results_json={"total_pnl": 100},  # Adding KPI for verification
        )
        db_session.add(backtest_run_in_db)
        await db_session.commit()
        await db_session.refresh(backtest_run_in_db)
        run_id_from_db = backtest_run_in_db.id

        list_response = await authenticated_client.get("/api/v1/backtests")
        assert list_response.status_code == 200
        backtests_list = list_response.json()["data"]
        our_run = next((b for b in backtests_list if b["task_id"] == task_id), None)

        assert our_run is not None, (
            "Backtest run not found in the list after execution."
        )
        assert our_run["status"] == "COMPLETED"
        assert our_run["pnl"] == 100

        delete_response = await authenticated_client.delete(
            f"/api/v1/backtests/{task_id}"
        )
        assert delete_response.status_code == 204

        get_after_delete_response = await authenticated_client.get(
            f"/api/v1/backtests/{run_id_from_db}"
        )
        assert get_after_delete_response.status_code == 404
