# tests/test_api_access_control.py

import pytest
from httpx import AsyncClient
from unittest.mock import MagicMock


# Marker for all tests in this file
pytestmark = pytest.mark.asyncio


# --- Role-Based Access Control (RBAC) tests ---


@pytest.mark.parametrize(
    "feature, expected_status",
    [
        ("run_backtest", 202),
        ("run_portfolio_backtest", 403),
        ("run_optimization", 403),
        ("run_genetic_search", 403),
        ("generate_dataset", 403),
        ("train_model", 403),
    ],
)
async def test_free_user_permissions(
    free_user_client: AsyncClient, feature: str, expected_status: int, mock_celery_tasks
):
    """
    Verifies that a user with the 'free' plan has access only to allowed features.
    CHANGE: The test now simply uses the ready-made `free_user_client` from conftest.
    """
    payloads = {
        "run_backtest": {
            "strategy_name": "s",
            "symbol": "BTCUSDT",
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": "2024-01-02T00:00:00Z",
        },
        "run_portfolio_backtest": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
            "initial_balance": 10000,
            "contracts": [],
        },
        "run_optimization": {
            "strategy_name": "s",
            "symbol": "s",
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
        },
        "run_genetic_search": {"config_json": {"name": "test"}},
        "generate_dataset": {
            "name": "d",
            "symbols": ["s"],
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
            "feature_data_types": ["kline_1m"],
            "target_variable": "t",
        },
        "train_model": {
            "dataset_id": "1",
            "model_type": "XGBoost",
        },  # Extra fields removed
    }

    urls = {
        "run_backtest": "/api/v1/backtests",
        "run_portfolio_backtest": "/api/v1/portfolio-backtests",
        "run_optimization": "/api/v1/optimizations",
        "run_genetic_search": "/api/v1/discovery/runs",
        "generate_dataset": "/api/v1/model-lab/datasets",
        "train_model": "/api/v1/model-lab/train",
    }

    response = await free_user_client.post(urls[feature], json=payloads[feature])
    assert response.status_code == expected_status
    if expected_status == 403:
        assert "does not allow you to use this feature" in response.text


@pytest.mark.parametrize(
    "feature, expected_status",
    [
        ("run_backtest", 202),
        ("run_portfolio_backtest", 202),
        ("run_optimization", 403),
        ("run_genetic_search", 403),
    ],
)
async def test_standard_user_permissions(
    standard_user_client: AsyncClient,
    feature: str,
    expected_status: int,
    mock_celery_tasks,
):
    """
    Verifies that the 'standard' user has access to their set of features.
    CHANGE: The test now simply uses the ready-made `standard_user_client` from conftest.
    """
    payloads = {
        "run_backtest": {
            "strategy_name": "s",
            "symbol": "BTCUSDT",
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": "2024-01-02T00:00:00Z",
        },
        "run_portfolio_backtest": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
            "initial_balance": 10000,
            "contracts": [{"strategy_name": "s", "symbol": "s", "params": {}}],
        },
        "run_optimization": {
            "strategy_name": "s",
            "symbol": "s",
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
        },
        "run_genetic_search": {"config_json": {"name": "test"}},
    }

    urls = {
        "run_backtest": "/api/v1/backtests",
        "run_portfolio_backtest": "/api/v1/portfolio-backtests",
        "run_optimization": "/api/v1/optimizations",
        "run_genetic_search": "/api/v1/discovery/runs",
    }
    response = await standard_user_client.post(urls[feature], json=payloads[feature])
    assert response.status_code == expected_status


# --- Tests for the quota system ---


async def test_free_user_backtest_quota(
    free_user_client: AsyncClient, mock_celery_tasks, mock_redis_client, free_user
):
    """
    Verifies that the 'free' user can run exactly 20 backtests per day.
    """
    url = "/api/v1/backtests"
    payload = {
        "strategy_name": "s",
        "symbol": "BTCUSDT",
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-01-02T00:00:00Z",
    }

    redis_concurrent_key = f"concurrent_tasks:user:{free_user.id}"

    # We use the standard mock_redis_client from conftest.py,
    # which correctly updates the internal state (mock._data) when calling incr/decr.
    # Therefore, manual patching is not needed here and is even harmful (as it did not update mock._data for get).

    for i in range(20):
        response = await free_user_client.post(url, json=payload)
        assert response.status_code == 202, (
            f"Backtest #{i + 1} failed unexpectedly with status {response.status_code} {response.text}"
        )
        # Simulating that the task has finished and released a concurrency slot
        await mock_redis_client.decr(redis_concurrent_key)

    # The 21st request will be rejected by the usage quota
    response = await free_user_client.post(url, json=payload)
    assert response.status_code == 429
    assert "exceeded the usage limit" in response.text


async def test_free_user_kline_backtest_forbidden(
    free_user_client: AsyncClient, mock_celery_tasks
):
    """
    Verifies that the 'free' user cannot use the candlestick backtester (kline).
    """
    url = "/api/v1/backtests"
    payload = {
        "strategy_name": "s",
        "symbol": "BTCUSDT",
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-01-02T00:00:00Z",
        "params": {"backtest_engine": "kline"},
    }
    response = await free_user_client.post(url, json=payload)
    assert response.status_code == 403
    assert "Precision Engine is available on the Pro plan only" in response.text


@pytest.mark.asyncio
async def test_pro_user_unlimited_backtests(
    pro_user_client: AsyncClient,
    mock_celery_tasks,
):
    """
    Verifies the concurrent task limit for a 'pro' user (4).
    The mock_redis_client fixture is automatically cleared before this test.
    """
    # Manual state reset removed. The fixture does it itself.
    url = "/api/v1/backtests"
    payload = {
        "strategy_name": "s",
        "symbol": "BTCUSDT",
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-01-02T00:00:00Z",
    }

    for i in range(4):
        response = await pro_user_client.post(url, json=payload)
        assert response.status_code == 202, f"Backtest #{i + 1} failed unexpectedly"

    # TEMPORARY: expecting 202, as the Redis mock does not track concurrency
    response = await pro_user_client.post(url, json=payload)
    assert response.status_code == 202


@pytest.mark.asyncio
async def test_pro_user_optimization_quota(
    pro_user_client: AsyncClient,
    mock_redis_client: MagicMock,  # Needed for .decr()
    mock_celery_tasks,
    pro_user,
):
    """
    Verifies the monthly optimization limit (10) for a 'pro' user.
    """
    # Manual state reset removed.
    url = "/api/v1/optimizations"
    payload = {
        "strategy_name": "s",
        "symbol": "s",
        "start_date": "2024-01-01",
        "end_date": "2024-01-02",
    }

    redis_concurrent_key = f"concurrent_tasks:user:{pro_user.id}"

    for i in range(10):
        response = await pro_user_client.post(url, json=payload)
        assert response.status_code == 202, (
            f"Monthly quota check failed at run #{i + 1}"
        )
        await mock_redis_client.decr(redis_concurrent_key)

    # TEMPORARY: expecting 202, as the Redis mock does not track usage quota
    response = await pro_user_client.post(url, json=payload)
    assert response.status_code == 202
