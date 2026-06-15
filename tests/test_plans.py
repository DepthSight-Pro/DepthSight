# tests/test_plans.py

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import uuid

from api import models


@pytest.mark.asyncio
class TestUserPlans:
    """
    A group of tests to verify permissions, quotas, and limits
    for different user plans (free, standard, pro).
    """

    # --- General data for tests (remain unchanged) ---
    backtest_payload = {
        "strategy_name": "TestStrategy",
        "symbol": "BTCUSDT",
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-01-15T00:00:00Z",
        "params": {},
    }
    portfolio_payload = {
        "name": "Test Portfolio",
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-01-15T00:00:00Z",
        "initial_balance": 10000,
        "contracts": [
            {
                "strategy_name": "s1",
                "symbol": "BTCUSDT",
                "market_type": "futures",
                "params": {},
            }
        ],
    }
    optimization_payload = {
        "strategy_name": "TestStrategy",
        "symbol": "BTCUSDT",
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-01-15T00:00:00Z",
    }
    genetic_payload = {"config_json": {"population_size": 50}}
    dataset_payload = {
        "name": "Test Dataset",
        "symbols": ["BTCUSDT"],
        "start_date": "2024-01-01",
        "end_date": "2024-01-15",
        "feature_data_types": ["kline_1m"],
        "target_variable": "close",
    }
    training_payload = {"dataset_id": "existing_dataset_id", "model_type": "XGBoost"}
    start_strategy_payload = {"config_id": "existing_config_id"}

    @pytest.fixture(autouse=True)
    def setup_common_crud_mocks(self, mocker):
        # This mock is useful and does not conflict, keeping it
        mock_config = models.StrategyConfig(
            id="existing_config_id",
            name="Mocked Strategy",
            config_data={"param": 1},
            symbol_selection_mode="DYNAMIC",
            symbols=None,
            use_ml_confirmation=False,
            user_id=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mocker.patch(
            "api.crud.get_strategy_config",
            new_callable=AsyncMock,
            return_value=mock_config,
        )

        async def mock_create_gr(db, user_id, config_json, **kwargs):
            from api import models

            run = models.GeneticRun(
                id=str(uuid.uuid4()),
                user_id=user_id,
                status="PENDING",
                created_at=datetime.now(timezone.utc),
                config_json=config_json,
            )
            db.add(run)
            return run

        mocker.patch("api.crud.create_genetic_run", side_effect=mock_create_gr)

        async def mock_create_tr(db, user_id, run_create, celery_task_id):
            from api import models

            run = models.TrainingRun(
                id=str(uuid.uuid4()),
                user_id=user_id,
                dataset_id=run_create.dataset_id,
                celery_task_id=celery_task_id,
                status="QUEUED",
                parameters_json={},
                created_at=datetime.now(timezone.utc),
            )
            db.add(run)
            return run

        mocker.patch("api.crud.create_training_run", side_effect=mock_create_tr)

        mocker.patch(
            "api.crud.get_dataset_run",
            new_callable=AsyncMock,
            return_value=models.DatasetRun(status="COMPLETED"),
        )

    @pytest.mark.parametrize(
        "user_fixture, endpoint, payload, expected_status",
        [
            ("free_user", "/api/v1/backtests", backtest_payload, 202),
            ("free_user", "/api/v1/portfolio-backtests", portfolio_payload, 403),
            ("free_user", "/api/v1/strategies", start_strategy_payload, 403),
            ("free_user", "/api/v1/discovery/runs", genetic_payload, 403),
            ("standard_user", "/api/v1/backtests", backtest_payload, 202),
            ("standard_user", "/api/v1/portfolio-backtests", portfolio_payload, 202),
            ("standard_user", "/api/v1/strategies", start_strategy_payload, 202),
            ("standard_user", "/api/v1/discovery/runs", genetic_payload, 403),
            ("standard_user", "/api/v1/model-lab/datasets", dataset_payload, 403),
            ("pro_user", "/api/v1/optimizations", optimization_payload, 202),
            ("pro_user", "/api/v1/discovery/runs", genetic_payload, 202),
            ("pro_user", "/api/v1/model-lab/train", training_payload, 202),
            (
                "free_user",
                "/api/v1/backtests",
                {**backtest_payload, "params": {"backtest_engine": "kline"}},
                403,
            ),
        ],
    )
    async def test_permission_enforcement(
        self,
        user_fixture,
        endpoint,
        payload,
        expected_status,
        free_user_client,
        standard_user_client,
        pro_user_client,
        mock_celery_tasks,
    ):
        clients = {
            "free_user": free_user_client,
            "standard_user": standard_user_client,
            "pro_user": pro_user_client,
        }
        client = clients[user_fixture]

        # mocker.patch('sqlalchemy.ext.asyncio.AsyncSession.refresh', new_callable=AsyncMock) # This patch might not be needed

        response = await client.post(endpoint, json=payload)
        assert response.status_code == expected_status, (
            f"For {user_fixture} on {endpoint}, expected {expected_status}, but got {response.status_code}. Response: {response.text}"
        )

    async def test_quota_enforcement_for_free_user(
        self, free_user_client, mock_redis_client, free_user, mock_celery_tasks
    ):
        """
        Verifies that the quota of 20 backtests per day for a free user works correctly.
        """
        client = free_user_client
        redis_concurrent_key = f"concurrent_tasks:user:{free_user.id}"

        for i in range(20):
            response = await client.post(
                "/api/v1/backtests", json=self.backtest_payload
            )
            assert response.status_code == 202, f"Request #{i + 1} should have passed"
            await mock_redis_client.decr(redis_concurrent_key)

        response = await client.post("/api/v1/backtests", json=self.backtest_payload)
        assert response.status_code == 429
        assert "exceeded the usage limit" in response.json()["error"]

    @pytest.mark.parametrize(
        "user_fixture, duration_days, expected_status",
        [
            ("free_user", 89, 202),
            ("free_user", 91, 403),
            ("standard_user", 360, 202),
            ("standard_user", 370, 403),
            ("pro_user", 1000, 202),
        ],
    )
    async def test_backtest_duration_limit(
        self,
        user_fixture,
        duration_days,
        expected_status,
        free_user_client,
        standard_user_client,
        pro_user_client,
        mock_celery_tasks,
    ):
        """Verifies the limit on the maximum backtest duration."""
        clients = {
            "free_user": free_user_client,
            "standard_user": standard_user_client,
            "pro_user": pro_user_client,
        }
        client = clients[user_fixture]

        start_date = datetime(2023, 1, 1)
        end_date = start_date + timedelta(days=duration_days)
        payload = {
            **self.backtest_payload,
            "start_date": start_date.isoformat() + "Z",
            "end_date": end_date.isoformat() + "Z",
        }
        response = await client.post("/api/v1/backtests", json=payload)
        assert response.status_code == expected_status
        if expected_status == 403:
            assert "exceeds your plan's limit" in response.json()["error"]

    @pytest.mark.parametrize(
        "user_fixture, task_limit",
        [
            ("free_user", 1),
            ("standard_user", 2),
            ("pro_user", 5),
        ],
    )
    async def test_concurrent_task_limit(
        self,
        user_fixture,
        task_limit,
        free_user_client,
        standard_user_client,
        pro_user_client,
        free_user,
        standard_user,
        pro_user,
        mock_celery_tasks,
    ):
        """Verifies that the user cannot start more tasks than allowed by their plan."""
        clients = {
            "free_user": free_user_client,
            "standard_user": standard_user_client,
            "pro_user": pro_user_client,
        }
        users = {
            "free_user": free_user,
            "standard_user": standard_user,
            "pro_user": pro_user,
        }
        client = clients[user_fixture]
        user = users[user_fixture]

        for i in range(task_limit):
            response = await client.post(
                "/api/v1/backtests", json=self.backtest_payload
            )
            assert response.status_code == 202, (
                f"Concurrent task #{i + 1} for plan '{user.plan}' should have been accepted"
            )

        response = await client.post("/api/v1/backtests", json=self.backtest_payload)
        assert response.status_code == 429
        assert "maximum number of concurrent tasks" in response.json()["error"]

    @pytest.mark.parametrize(
        "user_fixture, expected_priority",
        [
            ("free_user", 9),
            ("standard_user", 5),
            ("pro_user", 1),
        ],
    )
    async def test_celery_task_priority(
        self,
        user_fixture,
        expected_priority,
        free_user_client,
        standard_user_client,
        pro_user_client,
        mock_celery_tasks,
    ):
        """Verifies that Celery tasks are assigned the correct priority."""
        from api.depthsight_api import run_backtest_task

        clients = {
            "free_user": free_user_client,
            "standard_user": standard_user_client,
            "pro_user": pro_user_client,
        }
        client = clients[user_fixture]

        # Resetting the mock state before the call
        run_backtest_task.apply_async.reset_mock()

        await client.post("/api/v1/backtests", json=self.backtest_payload)

        run_backtest_task.apply_async.assert_called_once()
        _, kwargs = run_backtest_task.apply_async.call_args
        assert kwargs.get("priority") == expected_priority

    async def test_free_user_bybit_trading(
        self,
        free_user,
        free_user_client,
        db_session,
        mock_redis_client,
        mock_celery_tasks,
    ):
        """Verifies that a free plan user can trade only on Bybit and not other exchanges."""
        from api import models

        # 1. Add a Bybit API key for the free user
        bybit_key = models.ApiKey(
            user_id=free_user.id,
            name="Bybit Test Key",
            exchange="bybit",
            encrypted_api_key="enc-key",
            encrypted_api_secret="enc-secret",
            key_prefix="bybit...1234",
            status="valid",
            is_active=True,
        )
        db_session.add(bybit_key)
        await db_session.commit()
        await db_session.refresh(bybit_key)

        # 2. Try starting strategy with the Bybit key (should return 202)
        payload = {
            "config_id": "existing_config_id",
            "api_key_id": bybit_key.id,
            "mode": "live",
        }
        response = await free_user_client.post("/api/v1/strategies", json=payload)
        assert response.status_code == 202, (
            f"Failed starting strategy with Bybit key: {response.text}"
        )

        # 3. Add a Binance API key for the free user
        binance_key = models.ApiKey(
            user_id=free_user.id,
            name="Binance Test Key",
            exchange="binance",
            encrypted_api_key="enc-key",
            encrypted_api_secret="enc-secret",
            key_prefix="binance...1234",
            status="valid",
            is_active=True,
        )
        db_session.add(binance_key)
        await db_session.commit()
        await db_session.refresh(binance_key)

        # 4. Try starting strategy with the Binance key (should return 403)
        payload["api_key_id"] = binance_key.id
        response = await free_user_client.post("/api/v1/strategies", json=payload)
        assert response.status_code == 403
        assert "only allowed using Bybit API keys" in response.json()["error"]
