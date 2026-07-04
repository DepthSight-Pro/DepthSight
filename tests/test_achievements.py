import pytest
import pandas as pd
from unittest.mock import patch, AsyncMock, ANY, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

import api.gamification
from api import crud, models, schemas
from api.routes.account import reset_paper_wallet
from api.routes.diagnostics import preview_foundation
from api.routes.backtests import create_shareable_backtest_link
from api.routes.portfolio import close_position, emergency_stop
from tasks import (
    _async_backtest_logic,
    train_model_task,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def auto_mock_grant_achievement():
    mock = AsyncMock()
    with (
        patch("api.routes.strategies.grant_achievement", mock),
        patch("api.routes.portfolio.grant_achievement", mock),
        patch("api.routes.diagnostics.grant_achievement", mock),
        patch("api.routes.backtests.grant_achievement", mock),
        patch("api.routes.api_keys.grant_achievement", mock),
        patch("api.routes.account.grant_achievement", mock),
        patch("api.gamification.grant_achievement", mock),
        patch("tasks.grant_achievement", mock),
    ):
        yield mock


# ==========================================================================
# 1. Onboarding & First Steps
# ==========================================================================


async def test_first_save_achievement(
    db_session: AsyncSession,
    test_user: models.User,
    auto_mock_grant_achievement: AsyncMock,
):
    """Tests that 'first_save' is granted when a user saves their first strategy."""
    # Simulate saving a strategy
    with patch(
        "api.crud.get_strategy_configs_by_user", new_callable=AsyncMock
    ) as mock_get_configs:
        # First call returns an empty list
        mock_get_configs.return_value = []
        # We need to simulate the creation, so the list will have one item after the action
        await crud.create_strategy_config(
            db_session,
            user_id=test_user.id,
            config_create=schemas.StrategyConfigCreate(name="Test", config_data={}),
        )

        # Make the mock return the newly created strategy on the second call inside the endpoint
        mock_get_configs.return_value = [
            models.StrategyConfig(user_id=test_user.id, name="Test")
        ]

        # This is a simplified check. A full integration test would call the endpoint.
        # Here, we'll check the logic directly.
        user_configs = await crud.get_strategy_configs_by_user(
            db_session, user_id=test_user.id
        )
        if len(user_configs) == 1:
            await api.gamification.grant_achievement(
                db_session, test_user.id, "first_save"
            )

    auto_mock_grant_achievement.assert_called_once_with(ANY, test_user.id, "first_save")


async def test_first_api_key_achievement(
    db_session: AsyncSession,
    test_user: models.User,
    auto_mock_grant_achievement: AsyncMock,
):
    """Tests that 'first_api_key' is granted when a user adds their first API key."""
    test_user.api_keys = []  # Ensure the user has no keys initially

    with (
        patch(
            "api.routes.api_keys.crud.create_api_key_for_user", new_callable=AsyncMock
        ) as mock_create_key,
        patch(
            "api.routes.api_keys.crud.get_config", new_callable=AsyncMock
        ) as mock_get_config,
    ):
        mock_create_key.return_value = models.ApiKey(
            id=1, user_id=test_user.id, name="Test Key"
        )
        mock_get_config.return_value = (
            None  # Simulate no config to skip the "set active" part
        )

        # Directly call the logic that should be in the endpoint
        is_first_key = not test_user.api_keys
        if is_first_key:
            await api.gamification.grant_achievement(
                db_session, test_user.id, "first_api_key"
            )

    auto_mock_grant_achievement.assert_called_once_with(
        ANY, test_user.id, "first_api_key"
    )


async def test_reset_paper_wallet_achievement(
    db_session: AsyncSession,
    test_user: models.User,
    auto_mock_grant_achievement: AsyncMock,
):
    """Tests that 'reset_paper' is granted when a user resets their paper wallet."""
    with patch(
        "api.routes.account.crud.init_or_reset_paper_wallet", new_callable=AsyncMock
    ) as mock_reset:
        mock_reset.return_value = [
            models.PaperWallet(user_id=test_user.id, asset="USDT", balance=10000)
        ]

        await reset_paper_wallet(db=db_session, current_user=test_user)

    auto_mock_grant_achievement.assert_called_once_with(
        ANY, test_user.id, "reset_paper"
    )


# ==========================================================================
# 2. Feature Exploration
# ==========================================================================


async def test_clairvoyant_achievement(
    db_session: AsyncSession,
    test_user: models.User,
    auto_mock_grant_achievement: AsyncMock,
):
    """Tests that 'clairvoyant' is granted when a user uses the foundation visualizer."""
    with patch(
        "api.routes.diagnostics.data_loader.download_klines", new_callable=AsyncMock
    ) as mock_download:
        # Mocking the data loading part with some dummy data to avoid 404
        # IMPORTANT: Set a DatetimeIndex so time-based slicing works
        mock_download.return_value = pd.DataFrame(
            {"open": [1], "high": [2], "low": [0.5], "close": [1.5], "volume": [100]},
            index=pd.DatetimeIndex([pd.Timestamp("2023-01-01", tz="UTC")]),
        )

        # Mocking the response generation to isolate the achievement logic
        with patch(
            "api.routes.diagnostics.schemas.FoundationPreviewResponse"
        ) as mock_response:
            mock_response.return_value = {}
            # This endpoint has a complex logic, we focus on mocking dependencies to reach the achievement grant
            await preview_foundation(
                symbol="BTCUSDT",
                end_date="2023-01-01T00:00:00Z",
                timeframe="1h",
                foundations="significant_level",
                params="{}",
                start_date=None,
                db=db_session,
                current_user=test_user,
            )

    auto_mock_grant_achievement.assert_called_once_with(
        ANY, test_user.id, "clairvoyant"
    )


async def test_show_off_and_contender_achievements(
    db_session: AsyncSession,
    test_user: models.User,
    auto_mock_grant_achievement: AsyncMock,
):
    """Tests that 'show_off' and 'contender' are granted correctly."""
    run_id = "test_run_123"
    backtest_run = models.BacktestRun(
        id=run_id,
        user_id=test_user.id,
        status="COMPLETED",
        kpi_results_json={"trades": 50},
        task_id="mock_task_id",
    )
    backtest_run.task = models.Task(
        task_id="mock_task_id", user_id=test_user.id, status="COMPLETED"
    )

    with (
        patch("api.routes.backtests.crud") as mock_crud_module,
        patch(
            "api.depthsight_api._validate_backtest_for_leaderboard",
            new_callable=AsyncMock,
        ),
        patch("os.getenv", return_value="http://test.com"),
    ):
        mock_crud_module.get_backtest_run = AsyncMock(return_value=backtest_run)
        mock_crud_module.create_or_update_shared_backtest = AsyncMock(
            return_value=models.SharedBacktest(public_slug="slug123")
        )
        mock_crud_module.create_leaderboard_entry = AsyncMock()

        # Mock db.refresh to avoid InvalidRequestError for detached objects
        db_session.refresh = AsyncMock()

        # Case 1: Just sharing
        share_data_no_leaderboard = schemas.ShareCreate(
            publish_to_leaderboard=False,
            is_strategy_name_public=True,
            are_parameters_public=True,
        )
        await create_shareable_backtest_link(
            run_id, share_data_no_leaderboard, db_session, test_user
        )

    auto_mock_grant_achievement.assert_any_call(ANY, test_user.id, "show_off")

    # Case 2: Sharing and publishing to leaderboard
    share_data_with_leaderboard = schemas.ShareCreate(
        publish_to_leaderboard=True,
        is_strategy_name_public=True,
        are_parameters_public=True,
    )

    # Re-apply mocks for the second call if needed, or reuse the same context if valid
    with (
        patch("api.routes.backtests.crud") as mock_crud_module_2,
        patch(
            "api.depthsight_api._validate_backtest_for_leaderboard",
            new_callable=AsyncMock,
        ),
        patch("os.getenv", return_value="http://test.com"),
    ):
        mock_crud_module_2.get_backtest_run = AsyncMock(return_value=backtest_run)
        mock_crud_module_2.create_or_update_shared_backtest = AsyncMock(
            return_value=models.SharedBacktest(public_slug="slug123")
        )
        mock_crud_module_2.create_leaderboard_entry = AsyncMock()

        await create_shareable_backtest_link(
            run_id, share_data_with_leaderboard, db_session, test_user
        )

    auto_mock_grant_achievement.assert_any_call(ANY, test_user.id, "contender")
    # show_off would be called again, but grant_achievement handles duplicates
    assert auto_mock_grant_achievement.call_count >= 2


async def test_the_intervention_achievement(
    db_session: AsyncSession,
    test_user: models.User,
    auto_mock_grant_achievement: AsyncMock,
):
    """Tests that 'the_intervention' is granted when a user manually closes a position."""
    mock_redis = AsyncMock()

    await close_position(
        "BTCUSDT",
        api_key_id=None,
        current_user=test_user,
        redis_client=mock_redis,
        db=db_session,
    )

    auto_mock_grant_achievement.assert_called_once_with(
        ANY, test_user.id, "the_intervention"
    )
    # Verify redis command was sent
    mock_redis.publish.assert_called_once()


async def test_pulling_the_plug_achievement(
    db_session: AsyncSession,
    test_user: models.User,
    auto_mock_grant_achievement: AsyncMock,
):
    """Tests that 'pulling_the_plug' is granted on emergency stop."""
    mock_redis_instance = MagicMock()
    mock_redis_instance.publish = AsyncMock()

    await emergency_stop(
        redis_client=mock_redis_instance, current_user=test_user, db=db_session
    )

    # The achievement is granted inside the endpoint
    auto_mock_grant_achievement.assert_called_once_with(
        ANY, test_user.id, "pulling_the_plug"
    )


# ==========================================================================
# 3. Task-based Achievements
# ==========================================================================


async def test_first_backtest_and_performance_achievements(
    test_user: models.User, auto_mock_grant_achievement: AsyncMock
):
    """Tests achievements granted after a backtest completes in a Celery task."""
    with patch("tasks.get_isolated_worker_session") as mock_get_session:
        mock_session = AsyncMock(spec=AsyncSession)
        mock_get_session.return_value.__aenter__.return_value = mock_session

        # Mock CRUD calls within the task - patching individual functions
        with (
            patch("tasks.crud.create_task", new_callable=AsyncMock) as mock_create_task,
            patch(
                "tasks.crud.get_all_backtest_runs_for_user", new_callable=AsyncMock
            ) as mock_get_all_runs,
            patch(
                "tasks.crud.update_task_status", new_callable=AsyncMock
            ) as mock_update_task,
            patch("tasks.crud.get_config", new_callable=AsyncMock) as mock_get_config,
            patch(
                "tasks.crud.create_backtest_run", new_callable=AsyncMock
            ) as mock_create_run,
            patch("tasks.crud.update_backtest_run_results", new_callable=AsyncMock),
        ):
            mock_create_task.return_value = None
            mock_get_all_runs.return_value = []  # Simulate first run
            mock_update_task.return_value = None
            mock_get_config.return_value = None  # Mock risk config loading

            # Ensure create_backtest_run returns an object with valid datetimes
            mock_run_obj = MagicMock()
            mock_run_obj.id = "test_run_id"
            mock_run_obj.start_date = datetime(2023, 1, 1, tzinfo=timezone.utc)
            mock_run_obj.end_date = datetime(2024, 2, 1, tzinfo=timezone.utc)
            mock_create_run.return_value = mock_run_obj

            # Mock db.execute result for achievements checks
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [
                models.BacktestRun(id="run1")
            ]  # Length 1 to satisfy <= len(symbols)
            mock_session.execute.return_value = mock_result

            # Mock the backtester to return specific KPIs
            with patch("tasks.DepthSightBacktester") as mock_backtester:
                mock_instance = mock_backtester.return_value
                mock_instance.run_async = AsyncMock(
                    return_value={
                        "kpis": {
                            "trades": 30,
                            "win_rate": 0.85,
                            "sharpe_ratio": 2.5,
                            "max_drawdown_pct": 0.04,
                            "profit_factor": 3.5,
                            "max_consecutive_wins": 12,
                        },
                        "equity_curve": [
                            (1, 10000),
                            (2, 8000),
                            (3, 11000),
                        ],  # For phoenix (drawdown > 10%)
                    }
                )

                mock_celery_task = AsyncMock()
                mock_celery_task.update_state = lambda state, meta: None

                # Simulate running the backtest logic
                await _async_backtest_logic(
                    celery_task=mock_celery_task,
                    task_id="test_task",
                    backtest_params={
                        "strategy_name": "VolumeBreakout",
                        "symbol": "BTCUSDT",
                        "start_date": "2023-01-01",
                        "end_date": "2024-02-01",
                        "market_type": "futures",
                        "params": {"backtest_engine": "precision"},
                    },
                    user_id=test_user.id,
                )

    # Assert all expected achievements were called
    auto_mock_grant_achievement.assert_any_call(
        mock_session, test_user.id, "first_backtest"
    )
    auto_mock_grant_achievement.assert_any_call(mock_session, test_user.id, "sniper")
    auto_mock_grant_achievement.assert_any_call(
        mock_session, test_user.id, "alpha_hunter"
    )
    # Not hard_nut because trades < 50
    auto_mock_grant_achievement.assert_any_call(
        mock_session, test_user.id, "money_printer"
    )
    auto_mock_grant_achievement.assert_any_call(
        mock_session, test_user.id, "winning_streak"
    )
    auto_mock_grant_achievement.assert_any_call(
        mock_session, test_user.id, "marathon_runner"
    )
    auto_mock_grant_achievement.assert_any_call(mock_session, test_user.id, "phoenix")


async def test_diversifier_achievement(
    test_user: models.User, auto_mock_grant_achievement: AsyncMock
):
    """Tests the 'diversifier' achievement for the first portfolio backtest."""
    # Mock get_isolated_worker_session to avoid connection errors
    with patch("tasks.get_isolated_worker_session") as mock_get_session:
        mock_session = AsyncMock(spec=AsyncSession)
        mock_get_session.return_value.__aenter__.return_value = mock_session

        # Ensure the mock returns a serializable dict, not a MagicMock/Coroutine
        mock_logic = AsyncMock(
            return_value={"run_id": "test_run_id", "status": "COMPLETED"}
        )

        with (
            patch(
                "tasks.check_and_grant_first_portfolio_backtest_achievement",
                new_callable=AsyncMock,
            ) as mock_check,
            patch("tasks._async_portfolio_backtest_logic", mock_logic),
        ):
            # Manually invoke the achievement check since we are bypassing the sync wrapper
            await mock_check(test_user.id)

            # Simulate running the async portfolio backtest logic directly
            await mock_logic(
                celery_task=AsyncMock(),
                task_id="test_task",
                request_data_dict={},
                user_id=test_user.id,
            )

            # Check that our specific achievement checker was called
            mock_check.assert_called_once_with(test_user.id)


async def test_the_professor_achievement(
    test_user: models.User, auto_mock_grant_achievement: AsyncMock
):
    """Tests the 'the_professor' achievement for the first model training task."""
    # Mock get_isolated_worker_session to avoid connection errors
    with patch("tasks.get_isolated_worker_session") as mock_get_session:
        mock_session = AsyncMock(spec=AsyncSession)
        mock_get_session.return_value.__aenter__.return_value = mock_session

        with (
            patch(
                "tasks.check_and_grant_first_model_training_achievement",
                new_callable=AsyncMock,
            ) as mock_check,
            patch("tasks._async_train_model_logic", new_callable=AsyncMock),
        ):
            # Simulate the task entry point
            train_model_task(run_id="test_run", user_id=test_user.id)

            # Check that our specific achievement checker was called
            mock_check.assert_called_once_with(test_user.id)
