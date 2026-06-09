# FILE: tests/test_realtime_updates.py

import pytest
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock
import pandas as pd
from datetime import datetime, timezone

from bot_module.trainer import Trainer
from tasks import _async_backtest_logic
from api import schemas


@pytest.mark.asyncio
async def test_backtest_task_publishes_realtime_progress(mocker, test_user):
    task_id = "test-realtime-task-123"
    test_user.level = (
        1  # Set a numeric value to avoid comparison errors in gamification.py
    )
    user_id = test_user.id

    mock_redis_pub_client = AsyncMock()
    mocker.patch("tasks.aredis.Redis", return_value=mock_redis_pub_client)

    mock_db_run = MagicMock()
    mock_db_run.id = "mock-run-id-123"
    mock_db_run.strategy_id = "mock-strategy-id"
    mock_db_run.start_date = datetime.now(timezone.utc)
    mock_db_run.end_date = datetime.now(timezone.utc)

    mocker.patch("tasks.crud.create_task", new_callable=AsyncMock)
    mocker.patch("tasks.crud.update_task_status", new_callable=AsyncMock)
    mocker.patch(
        "tasks.crud.create_backtest_run",
        new_callable=AsyncMock,
        return_value=mock_db_run,
    )
    mocker.patch("tasks.crud.update_backtest_run_results", new_callable=AsyncMock)
    mocker.patch(
        "tasks.crud.update_backtest_run_status", new_callable=AsyncMock
    )  # Important for error handling
    mocker.patch(
        "tasks.crud.admin_get_user_details", new_callable=AsyncMock, return_value=None
    )  # For push notifications
    mocker.patch(
        "tasks.crud.get_backtest_run_with_trades",
        new_callable=AsyncMock,
        return_value=None,
    )  # For gene analysis

    # Mock get_config to avoid session issues and provide risk settings
    mock_user_config = MagicMock()
    mock_user_config.risk_management = schemas.RiskManagementSettings(
        maxDrawdown=10.0,
        maxConsecutiveLosses=10,
        maxConcurrentTrades=5,
        stopLossEnabled=True,
        defaultStopLossPercent=2.0,
        riskPerTradePercent=1.0,
    )
    mock_user_config.backtest_risk_management = None
    mocker.patch(
        "tasks.crud.get_config", new_callable=AsyncMock, return_value=mock_user_config
    )

    mocker.patch("tasks.process_backtest_analytics_task.delay")

    # Configure the DB session mock with the correct execute() behavior
    mock_scalars_result = MagicMock()
    mock_scalars_result.all.return_value = []  # Empty list for backtest_runs
    mock_scalars_result.first.return_value = None

    mock_execute_result = MagicMock()
    mock_execute_result.scalars.return_value = mock_scalars_result

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_execute_result
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.refresh = AsyncMock()

    mocker.patch(
        "tasks.get_isolated_worker_session",
        return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_session)),
    )

    # 1. Mock Trainer so it doesn't try to actually load data
    mock_trainer_instance = MagicMock(spec=Trainer)
    # 2. Return mock data so that the empty data check passes successfully
    mock_trainer_instance._load_historical_data.return_value = {
        "kline_1m": pd.DataFrame({"close": [1, 2, 3]}),
        "kline_1h": pd.DataFrame({"close": [1, 2, 3]}),
        "kline_4h": pd.DataFrame({"close": [1, 2, 3]}),
        "kline_1d": pd.DataFrame({"close": [1, 2, 3]}),
    }
    # 3. Mock the method that determines which data is needed
    mock_trainer_instance.get_data_requirements_for_strategy.return_value = {
        "kline_1m",
        "kline_1h",
        "kline_4h",
        "kline_1d",
    }
    # 4. Add attributes that are used when creating DepthSightBacktester
    mock_trainer_instance.backtest_execution_config = {
        "commission_pct": 0.001,
        "slippage_pct": 0.0,
    }
    mock_trainer_instance.strategy_defaults = {}
    mocker.patch("tasks.Trainer", return_value=mock_trainer_instance)

    # 5. Mock the entire DepthSightBacktester class to avoid errors in __init__
    # Use side_effect to capture progress_callback from constructor arguments
    captured_callback = {}

    def mock_backtester_constructor(*args, **kwargs):
        # Save progress_callback from constructor arguments
        captured_callback["callback"] = kwargs.get("progress_callback")

        async def mock_run_async():
            callback = captured_callback.get("callback")
            if callback:
                # First call - will trigger immediately (last_update_time = 0)
                await callback(
                    meta={
                        "kpis": {"progress": 50},
                        "events": [{"type": "trade", "id": 1, "pnl": 100}],
                    }
                )
                # Wait 2.5 seconds to pass throttling (update_interval = 2.0)
                await asyncio.sleep(2.5)
                # Second call - will trigger after waiting
                await callback(
                    meta={
                        "kpis": {"progress": 100},
                        "equity_point": ["2023-01-01T00:00:00Z", 10100],
                    }
                )
            return {"kpis": {"total_pnl": 100}, "trade_log": [], "equity_curve": []}

        mock_instance = MagicMock()
        mock_instance.run_async = mock_run_async
        mock_instance.strategy_instance = None
        return mock_instance

    mocker.patch("tasks.DepthSightBacktester", side_effect=mock_backtester_constructor)

    mock_celery_task = MagicMock()
    mock_celery_task.request.id = task_id
    mock_celery_task.update_state = MagicMock()

    backtest_params = {
        # 4. Use an existing strategy
        "strategy_name": "VisualBuilderStrategy",
        "symbol": "BTC/USDT",
        "start_date": "2023-01-01T00:00:00Z",
        "end_date": "2023-01-02T00:00:00Z",
        "params": {"backtest_engine": "precision"},
    }

    await _async_backtest_logic(mock_celery_task, task_id, backtest_params, user_id)

    await asyncio.sleep(0.1)

    assert mock_redis_pub_client.publish.call_count > 0, (
        "Expected at least 1 call for publishing to Redis"
    )

    # Checks - message structure: {'kpis': {...}, 'equity_point': ..., 'events': [...]}
    expected_channel = f"backtest-progress:{task_id}"
    call_args_list = [
        call.args for call in mock_redis_pub_client.publish.call_args_list
    ]

    kpis_found = False
    for args in call_args_list:
        assert args[0] == expected_channel
        message = json.loads(args[1])
        # Check that kpis is present and contains progress
        if "kpis" in message and message["kpis"] and "progress" in message["kpis"]:
            kpis_found = True

    assert kpis_found, "No messages with kpis.progress found"
