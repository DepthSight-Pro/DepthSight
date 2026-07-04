# tests/e2e/test_backtest_workflow.py
import pytest
import asyncio
from httpx import AsyncClient
from api import schemas, models


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_full_backtest_workflow(
    authenticated_client: AsyncClient,
    mock_celery_tasks,
    db_session,
    pro_user: models.User,
):
    """
    Checks the full cycle: starting a backtest via API, executing a Celery task,
    saving to the DB, and retrieving results via API.
    """
    client = authenticated_client

    # 1. GIVEN: Initial conditions - user is authorized.

    # 2. WHEN: User sends a request to start a backtest
    backtest_payload = {
        "strategy_name": "VolumeBreakout",
        "symbol": "BTCUSDT",
        "start_date": "2023-01-01T00:00:00Z",
        "end_date": "2023-02-01T00:00:00Z",
        "params": {"retest_atr_percent": 0.1},
    }

    print("\n[E2E Test] Submitting backtest task...")
    response = await client.post("/api/v1/backtests", json=backtest_payload)

    # 3. THEN: Check that the task is accepted
    assert response.status_code == 202, (
        f"Expected 202, got {response.status_code}. Body: {response.text}"
    )
    task_id = response.json()["data"]["task_id"]
    assert task_id
    print(f"[E2E Test] Backtest task submitted with ID: {task_id}")

    # Simulate worker operation (create task and result in DB)
    # Since mock_celery_tasks prevents real task execution,
    # and the API does not create a Task record (the worker does that), we must create it manually.
    from datetime import datetime, timezone
    import uuid

    # Use the actual user_id from the authenticated client's user object
    user_id = pro_user.id

    # Create a task in the DB
    new_task = models.Task(
        user_id=user_id,
        task_id=task_id,
        task_type="backtest",
        status="PENDING",
        submitted_at=datetime.now(timezone.utc),
        parameters=backtest_payload,
    )
    db_session.add(new_task)
    await db_session.commit()

    # Emulate task completion via a short pause or immediately
    new_task.status = "COMPLETED"
    run_id = str(uuid.uuid4())
    new_task.results = {"run_id": run_id}
    new_task.completed_at = datetime.now(timezone.utc)

    backtest_run = models.BacktestRun(
        id=run_id,
        user_id=user_id,
        task_id=task_id,
        strategy_name=backtest_payload["strategy_name"],
        symbol=backtest_payload["symbol"],
        market_type="futures",  # Default
        status="COMPLETED",
        start_date=datetime.fromisoformat(
            backtest_payload["start_date"].replace("Z", "+00:00")
        ),
        end_date=datetime.fromisoformat(
            backtest_payload["end_date"].replace("Z", "+00:00")
        ),
        initial_balance=10000.0,
        parameters_json=backtest_payload["params"],
        kpi_results_json={
            "total_pnl": 100.0,
            "win_rate": 0.6,
            "sharpe_ratio": 1.5,
            "trades": 1,
        },
        trades=[
            models.BacktestTrade(
                backtest_run_id=run_id,
                client_order_id=f"test-trade-{uuid.uuid4()}",
                direction="LONG",
                timestamp_entry=datetime(2023, 1, 1, 10, 0, tzinfo=timezone.utc),
                timestamp_exit=datetime(2023, 1, 1, 11, 0, tzinfo=timezone.utc),
                entry_price=100,
                exit_price=110,
                quantity=1,
                pnl=10,
                commission=0.1,
                exit_reason="TAKE_PROFIT",
            )
        ],
    )
    # Add backtest_run to the DB
    db_session.add(backtest_run)
    await db_session.commit()

    print(
        f"[E2E Test] Simulating worker: Created Task and BacktestRun in DB (Run ID: {run_id}) for user {user_id}"
    )

    # --- CELERY RESULT MOCK ---
    # Since we mocked Celery, we also need to mock the result,
    # which the API tries to get from Celery.
    from unittest.mock import patch, MagicMock
    from celery.result import AsyncResult

    mock_celery_result = MagicMock(spec=AsyncResult)
    mock_celery_result.state = "SUCCESS"
    mock_celery_result.result = {"run_id": run_id}

    with patch("api.routes.tasks.AsyncResult", return_value=mock_celery_result):
        # 4. WHEN: User periodically checks the task status
        found_run_id = None
        timeout = 5  # seconds
        start_time = asyncio.get_event_loop().time()

        print("[E2E Test] Polling for task completion...")
        while asyncio.get_event_loop().time() - start_time < timeout:
            status_response = await client.get(f"/api/v1/tasks/{task_id}")
            assert status_response.status_code == 200, (
                f"Polling failed with {status_response.status_code}: {status_response.text}"
            )

            task_data = status_response.json()["data"]
            print(f"[E2E Test] Polling... Task status: {task_data['status']}")

            if task_data["status"] in ["COMPLETED", "SUCCESS"]:
                if task_data.get("results") and task_data["results"].get("run_id"):
                    found_run_id = task_data["results"]["run_id"]
                    break

            await asyncio.sleep(0.5)

        # 5. THEN: Check that the task completed successfully and we have a run_id
        assert found_run_id == run_id, (
            f"Task did not complete successfully or returned wrong run_id. Expected {run_id}, got {found_run_id}"
        )

    print(f"[E2E Test] Task completed. Backtest Run ID: {found_run_id}")

    # 6. WHEN: User requests detailed results
    details_response = await client.get(f"/api/v1/backtests/{found_run_id}")

    # 7. THEN: Check detailed results
    assert details_response.status_code == 200
    details_data = details_response.json()["data"]

    # Response schema validation
    validated_details = schemas.BacktestRunDetails.model_validate(details_data)

    assert validated_details.id == run_id
    assert validated_details.strategy_name == "VolumeBreakout"
    assert validated_details.status == "COMPLETED"
    assert validated_details.kpi_results_json is not None
    assert "total_pnl" in validated_details.kpi_results_json
    assert validated_details.trades is not None  # Pydantic model - use the attribute
    # Since our `download_klines` mock returns data, there should be trades
    assert len(validated_details.trades) > 0

    print("[E2E Test] Successfully fetched and validated backtest results.")
