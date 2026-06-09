# tests/e2e/test_genetic_workflow.py
import pytest
import asyncio
from httpx import AsyncClient
from unittest.mock import patch, MagicMock, AsyncMock

from api import schemas
from bot_module.genetic_strategy_finder import GeneticStrategyFinder


@pytest.fixture
def mock_genetic_run():
    """Mock for successful execution of GeneticStrategyFinder."""
    # Returning a list of dictionaries, as the new run() method does
    results = []
    for i in range(3):
        results.append(
            {
                "rank": i + 1,
                "fitness_score": 2.5 - i * 0.2,
                "strategy_json": {
                    "name": f"FoundStrategy_{i + 1}",
                    "symbol": "BTCUSDT",
                    "marketType": "FUTURES",
                    "trigger": {"type": "on_candle_close", "timeframe": "1h"},
                    "conditions": {"id": "root", "type": "AND", "children": []},
                    "action": {
                        "params": {"direction": "LONG", "risk_value": 1.0 + i * 0.1}
                    },
                },
                "kpis_json": {"trades_in_eval": 20},
            }
        )

    mock_gsf_instance = MagicMock(spec=GeneticStrategyFinder)
    mock_gsf_instance.run.return_value = results
    return mock_gsf_instance


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_full_genetic_search_workflow(
    authenticated_client: AsyncClient,
    mock_genetic_run,  # Fixture for mocking the genetic algorithm itself
):
    """
    Checks the full cycle of genetic search: start, execution, obtaining results.
    """
    client = authenticated_client

    # 1. GIVEN: GeneticStrategyFinder itself is mocked to avoid waiting for the real GA execution.
    #    We are testing the integration specifically, not the algorithm itself.
    #    ALSO mock download_klines, as tasks.py calls it with the interval argument,
    #    which is not supported by the real function, and we do not want to make real requests.
    import pandas as pd

    # Creating a valid DataFrame for download_klines
    dates = pd.date_range(start="2023-05-01", periods=100, freq="1h")
    mock_df = pd.DataFrame(
        {
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": 102.0,
            "volume": 1000.0,
            "number_of_trades": 100,
        },
        index=dates,
    )
    mock_df.index.name = "open_time"

    with (
        patch("tasks.GeneticStrategyFinder", return_value=mock_genetic_run),
        patch("tasks.download_klines", new_callable=AsyncMock) as mock_dl,
    ):
        mock_dl.return_value = mock_df  # download_klines should return a DataFrame

        # 2. WHEN: User starts a new genetic search
        genetic_payload = {
            "config_json": {
                "name": "E2E Genetic Search for BTC",
                "target_symbols": ["BTCUSDT"],
                "data_start_date": "2023-05-01T00:00:00Z",
                "data_end_date": "2023-06-01T00:00:00Z",
                "fitness_metric": "profit_factor",
                "population_size": 10,  # Small values for test speed
                "generations": 5,
            }
        }

        # 2. WHEN: Running search via API
        # Patching tasks so they don't actually run in eager mode
        with patch("tasks.run_backtest_task.delay") as mock_bt_task:
            mock_bt_task.return_value = MagicMock(id="mock-bt-id")

            print("\n[E2E Genetic Test] Submitting genetic search task...")
            response = await client.post("/api/v1/discovery/runs", json=genetic_payload)

            # 3. THEN: Checking that the task was successfully accepted
            assert response.status_code == 202, (
                f"Expected 202, got {response.status_code}. Body: {response.text}"
            )
            run_response = schemas.GeneticRunResponse.model_validate(response.json())
            run_id = str(run_response.id)
            assert run_id
            print(f"[E2E Genetic Test] Genetic run created with ID: {run_id}")

            # 4. WHEN: Waiting for task completion (since Celery is eager, it is already completed)
            #    and requesting detailed results.
            await asyncio.sleep(0.1)  # A short pause to guarantee writing to the DB

            print(f"[E2E Genetic Test] Fetching details for run {run_id}...")
            details_response = await client.get(f"/api/v1/discovery/runs/{run_id}")
            assert details_response.status_code == 200
            run_details = schemas.GeneticRunResponse.model_validate(
                details_response.json()
            )

            # 5. THEN: Checking status and results
            assert run_details.status == "COMPLETED", (
                f"Run status is {run_details.status}, expected COMPLETED. Error: {run_details.error_message}"
            )

            # 6. WHEN: Requesting the "Hall of Fame" (found strategies)
            print(f"[E2E Genetic Test] Fetching found strategies for run {run_id}...")
            results_response = await client.get(
                f"/api/v1/discovery/runs/{run_id}/results"
            )
            assert results_response.status_code == 200
            found_strategies_data = results_response.json()
            found_strategies = [
                schemas.FoundStrategyResponse.model_validate(s)
                for s in found_strategies_data
            ]

            # 7. THEN: Checking that the strategies were saved
            # ATTENTION: If the mock returned 3, then there should be 3 in the DB.
            assert len(found_strategies) == 3, (
                f"Expected 3 strategies, got {len(found_strategies)}"
            )
            best_strategy = found_strategies[0]
            assert best_strategy.rank == 1
            assert best_strategy.fitness_score == pytest.approx(2.5)

            # Checking that KPIs were saved
            assert best_strategy.kpis_json is not None
            assert best_strategy.kpis_json.get("trades_in_eval") == 20

            # Checking the strategy JSON itself
            assert best_strategy.strategy_json["name"] == "FoundStrategy_1"

        print(
            "[E2E Genetic Test] Successfully fetched and validated genetic search results."
        )
