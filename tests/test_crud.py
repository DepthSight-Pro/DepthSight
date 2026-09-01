# tests/test_crud.py

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from api import crud, schemas, security


@pytest.mark.asyncio
async def test_create_api_key_packs_secret_with_api_password(db_session, test_user):
    api_key_value = f"bitget-key-{uuid.uuid4().hex}"
    key_data = schemas.ApiKeyCreate(
        name="Bitget Key",
        exchange="bitget",
        api_key=api_key_value,
        api_secret="bitget-secret",
        api_password="bitget-passphrase",
    )

    created_key = await crud.create_api_key_for_user(
        db=db_session,
        user_id=test_user.id,
        key_data=key_data,
    )

    decrypted_key = security.decrypt_data(created_key.encrypted_api_key)
    decrypted_secret = security.decrypt_data(created_key.encrypted_api_secret)
    packed_secret = json.loads(decrypted_secret)

    assert decrypted_key == api_key_value
    assert packed_secret == {
        "secret": "bitget-secret",
        "password": "bitget-passphrase",
    }
    assert created_key.key_prefix == f"{api_key_value[:4]}...{api_key_value[-4:]}"


@pytest.mark.asyncio
async def test_create_api_key_keeps_plain_secret_without_api_password(
    db_session, test_user
):
    api_key_value = f"binance-key-{uuid.uuid4().hex}"
    key_data = schemas.ApiKeyCreate(
        name="Binance Key",
        exchange="binance",
        api_key=api_key_value,
        api_secret="binance-secret",
    )

    created_key = await crud.create_api_key_for_user(
        db=db_session,
        user_id=test_user.id,
        key_data=key_data,
    )

    assert security.decrypt_data(created_key.encrypted_api_key) == api_key_value
    assert security.decrypt_data(created_key.encrypted_api_secret) == "binance-secret"


@pytest.mark.asyncio
async def test_create_and_get_user(db_session):
    user_data = schemas.UserCreate(
        username="testcrud", email="testcrud@example.com", password="password123"
    )
    await crud.create_user(db=db_session, user=user_data)
    await db_session.commit()

    retrieved_user = await crud.get_user_by_username(db=db_session, username="testcrud")
    assert retrieved_user is not None

    config = await crud.get_config(db=db_session, user_id=retrieved_user.id)
    assert config is not None

    # Accessing a Pydantic model field via a dot
    # `risk_management` in the `AppConfig` response schema is a RiskManagementSettings object
    assert config.risk_management.maxDrawdown == 10.0


@pytest.mark.asyncio
async def test_create_user_applies_registration_trial_from_config(
    db_session, monkeypatch
):
    monkeypatch.setattr(
        crud.plans_config,
        "get_registration_trial_config",
        lambda: {"enabled": True, "plan": "standard", "days": 7},
    )
    monkeypatch.setattr(
        crud.plans_config,
        "get_all_plans",
        lambda: {"free": {}, "standard": {}},
    )

    now = datetime.now(timezone.utc)
    user_data = schemas.UserCreate(
        username="trialuser", email="trialuser@example.com", password="password123"
    )
    created_user = await crud.create_user(db=db_session, user=user_data)
    await db_session.commit()

    assert created_user.plan == "standard"
    assert created_user.plan_expires_at is not None
    expires_at = created_user.plan_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    assert (
        now + timedelta(days=7)
        <= expires_at
        <= datetime.now(timezone.utc) + timedelta(days=7)
    )


@pytest.mark.asyncio
async def test_create_user_keeps_free_plan_when_registration_trial_disabled(
    db_session, monkeypatch
):
    monkeypatch.setattr(
        crud.plans_config,
        "get_registration_trial_config",
        lambda: {"enabled": False, "plan": "standard", "days": 7},
    )

    user_data = schemas.UserCreate(
        username="notrialuser", email="notrialuser@example.com", password="password123"
    )
    created_user = await crud.create_user(db=db_session, user=user_data)
    await db_session.commit()

    assert created_user.plan == "free"
    assert created_user.plan_expires_at is None


@pytest.mark.asyncio
async def test_create_user_keeps_free_plan_when_registration_trial_days_is_zero(
    db_session, monkeypatch
):
    monkeypatch.setattr(
        crud.plans_config,
        "get_registration_trial_config",
        lambda: {"enabled": True, "plan": "standard", "days": 0},
    )

    user_data = schemas.UserCreate(
        username="zerotrialuser",
        email="zerotrialuser@example.com",
        password="password123",
    )
    created_user = await crud.create_user(db=db_session, user=user_data)
    await db_session.commit()

    assert created_user.plan == "free"
    assert created_user.plan_expires_at is None


@pytest.mark.asyncio
async def test_create_user_keeps_free_plan_when_registration_trial_plan_is_unknown(
    db_session, monkeypatch
):
    monkeypatch.setattr(
        crud.plans_config,
        "get_registration_trial_config",
        lambda: {"enabled": True, "plan": "unknown", "days": 7},
    )
    monkeypatch.setattr(
        crud.plans_config,
        "get_all_plans",
        lambda: {"free": {}, "standard": {}},
    )

    user_data = schemas.UserCreate(
        username="unknowntrialuser",
        email="unknowntrialuser@example.com",
        password="password123",
    )
    created_user = await crud.create_user(db=db_session, user=user_data)
    await db_session.commit()

    assert created_user.plan == "free"
    assert created_user.plan_expires_at is None


@pytest.mark.asyncio
async def test_add_and_delete_symbol(db_session):
    user_data = schemas.UserCreate(
        username="testsymbols", email="testsymbols@example.com", password="password"
    )
    user = await crud.create_user(db=db_session, user=user_data)

    # Save the transaction to the DB
    await db_session.commit()

    data_sources_after_add = await crud.add_symbol_to_config(
        db=db_session, user_id=user.id, symbol="SOLUSDT"
    )
    assert "SOLUSDT" in data_sources_after_add["symbols"]

    data_sources_after_delete = await crud.delete_symbol_from_config(
        db=db_session, user_id=user.id, symbol="SOLUSDT"
    )
    assert "SOLUSDT" not in data_sources_after_delete["symbols"]


@pytest.mark.asyncio
async def test_create_and_get_dataset_run(db_session, test_user):
    """Tests the creation and retrieval of a DatasetRun."""
    dataset_create_schema = schemas.DatasetRunCreate(
        name="CRUD Test Dataset",
        symbols=["ETHUSDT"],
        start_date="2023-01-01T00:00:00Z",
        end_date="2023-02-01T00:00:00Z",
        feature_data_types=["kline_1m"],
        target_variable="Test Target",
    )

    db_run = await crud.create_dataset_run(
        db=db_session,
        user_id=test_user.id,
        run_create=dataset_create_schema,
        celery_task_id="crud-test-task-1",
    )
    await db_session.commit()

    assert db_run.name == "CRUD Test Dataset"
    assert db_run.user_id == test_user.id

    retrieved_run = await crud.get_dataset_run(
        db=db_session, user_id=test_user.id, run_id=db_run.id
    )
    assert retrieved_run is not None
    assert retrieved_run.id == db_run.id


@pytest.mark.asyncio
async def test_create_training_run_on_completed_dataset(db_session, test_user):
    """Tests the creation of a TrainingRun on a ready dataset."""
    # First, create a "ready" dataset
    dataset_create_schema = schemas.DatasetRunCreate(
        name="Completed Dataset",
        symbols=["LTCUSDT"],
        start_date="2023-01-01T00:00:00Z",
        end_date="2023-02-01T00:00:00Z",
        feature_data_types=["kline_1m"],
        target_variable="Test",
    )
    db_dataset = await crud.create_dataset_run(
        db_session, test_user.id, dataset_create_schema, "ds-task-crud"
    )
    db_dataset.status = "COMPLETED"  # Simulate completion
    await db_session.commit()

    training_create_schema = schemas.TrainingRunCreate(
        dataset_id=db_dataset.id, model_type="Test Model"
    )

    db_training_run = await crud.create_training_run(
        db_session, test_user.id, training_create_schema, "train-task-crud"
    )
    await db_session.commit()

    assert db_training_run.dataset_id == db_dataset.id

    retrieved_training_run = await crud.get_training_run(
        db_session, test_user.id, db_training_run.id
    )
    assert retrieved_training_run is not None
    assert (
        retrieved_training_run.dataset.name == "Completed Dataset"
    )  # Check that selectinload worked


@pytest.mark.asyncio
async def test_create_training_run_on_pending_dataset_fails(db_session, test_user):
    """Tests that a TrainingRun cannot be created on a non-ready dataset."""
    dataset_create_schema = schemas.DatasetRunCreate(
        name="Pending Dataset",
        symbols=["XRPUSDT"],
        start_date="2023-01-01T00:00:00Z",
        end_date="2023-02-01T00:00:00Z",
        feature_data_types=["kline_1m"],
        target_variable="Test",
    )
    db_dataset = await crud.create_dataset_run(
        db_session, test_user.id, dataset_create_schema, "ds-task-crud-pending"
    )
    # Default status is PENDING/QUEUED, do not change it
    await db_session.commit()

    training_create_schema = schemas.TrainingRunCreate(
        dataset_id=db_dataset.id, model_type="Test Model"
    )

    with pytest.raises(ValueError, match="not completed"):
        await crud.create_training_run(
            db_session, test_user.id, training_create_schema, "train-task-crud-fail"
        )


@pytest.mark.asyncio
async def test_update_or_create_symbol_strategy_performance(db_session, test_user):
    """
    Checks the logic of creation and subsequent update
    of a strategy performance record.
    """
    # 1. Creation (INSERT)
    initial_data = {
        "symbol": "BTCUSDT",
        "strategy_name": "TestStrat",
        "trade_results_buffer_json": "[]",
        "current_risk_multiplier_index": 2,
        "last_penalty_timestamp": 0.0,
        "total_trades_for_assessment": 5,
        "total_pnl_usd": 150.5,
    }

    # First record
    await crud.update_or_create_symbol_strategy_performance(
        db=db_session, user_id=test_user.id, performance_data=initial_data
    )
    await db_session.commit()

    # Check that the record appeared in the DB
    all_records = await crud.get_all_symbol_strategy_performance(
        db=db_session, user_id=test_user.id
    )
    assert len(all_records) == 1
    record = all_records[0]
    assert record.symbol == "BTCUSDT"
    assert record.strategy_name == "TestStrat"
    assert record.total_trades_for_assessment == 5
    assert record.total_pnl_usd == 150.5

    # 2. Update (UPDATE)
    updated_data = {
        "symbol": "BTCUSDT",
        "strategy_name": "TestStrat",
        "trade_results_buffer_json": "[[10, 100]]",
        "current_risk_multiplier_index": 1,
        "last_penalty_timestamp": 12345.67,
        "total_trades_for_assessment": 6,
        "total_pnl_usd": 140.0,
    }

    await crud.update_or_create_symbol_strategy_performance(
        db=db_session, user_id=test_user.id, performance_data=updated_data
    )
    await db_session.commit()

    # Check that the record was updated, not a new one added
    all_records_after_update = await crud.get_all_symbol_strategy_performance(
        db=db_session, user_id=test_user.id
    )
    assert len(all_records_after_update) == 1
    updated_record = all_records_after_update[0]
    assert updated_record.total_trades_for_assessment == 6
    assert updated_record.current_risk_multiplier_index == 1
    assert updated_record.total_pnl_usd == 140.0


@pytest.mark.asyncio
async def test_init_or_reset_paper_wallet(db_session, test_user):
    """Tests creating and resetting a paper wallet."""
    # 1. Initial creation
    wallet = await crud.init_or_reset_paper_wallet(db_session, user_id=test_user.id)
    await db_session.commit()

    assert len(wallet) == 1
    assert wallet[0].asset == "USDT"
    assert wallet[0].balance == 10000.0  # Default value from config

    # 2. Update balance and then reset
    wallet[0].balance = 5000.0
    await db_session.commit()

    reset_wallet = await crud.init_or_reset_paper_wallet(
        db_session, user_id=test_user.id, initial_balance=15000.0
    )
    await db_session.commit()

    assert len(reset_wallet) == 1
    assert reset_wallet[0].balance == 15000.0  # Custom initial balance


@pytest.mark.asyncio
async def test_get_paper_wallet(db_session, test_user):
    """Tests retrieving a user's paper wallet."""
    await crud.init_or_reset_paper_wallet(db_session, user_id=test_user.id)
    await crud.update_paper_wallet_balance(
        db_session, user_id=test_user.id, asset="BTC", amount_change=0.5
    )
    await db_session.commit()

    wallet = await crud.get_paper_wallet(db_session, user_id=test_user.id)
    assert len(wallet) == 2

    usdt_asset = next((a for a in wallet if a.asset == "USDT"), None)
    btc_asset = next((a for a in wallet if a.asset == "BTC"), None)

    assert usdt_asset is not None
    assert btc_asset is not None
    assert usdt_asset.balance == 10000.0
    assert btc_asset.balance == 0.5


@pytest.mark.asyncio
async def test_update_paper_wallet_balance(db_session, test_user):
    """Tests updating a specific asset in the paper wallet."""
    await crud.init_or_reset_paper_wallet(db_session, user_id=test_user.id)
    await db_session.commit()

    # Add BTC
    await crud.update_paper_wallet_balance(
        db_session, user_id=test_user.id, asset="BTC", amount_change=1.0
    )
    await db_session.commit()

    btc_asset = await crud.get_paper_wallet_asset(
        db_session, user_id=test_user.id, asset="BTC"
    )
    assert btc_asset is not None
    assert btc_asset.balance == 1.0

    # Subtract from USDT
    await crud.update_paper_wallet_balance(
        db_session, user_id=test_user.id, asset="USDT", amount_change=-500
    )
    await db_session.commit()

    usdt_asset = await crud.get_paper_wallet_asset(
        db_session, user_id=test_user.id, asset="USDT"
    )
    assert usdt_asset is not None
    assert usdt_asset.balance == 9500.0


@pytest.mark.asyncio
async def test_create_oauth_user_creates_app_config(db_session):
    oauth_user = await crud.create_oauth_user(
        db=db_session, email="oauthuser@example.com", username="oauthuser"
    )
    await db_session.commit()

    config = await crud.get_config(db=db_session, user_id=oauth_user.id)
    assert config is not None
    assert config.user_id == oauth_user.id
    assert config.risk_management.maxDrawdown == 10.0


@pytest.mark.asyncio
async def test_get_config_lazy_initialization_when_missing(db_session, test_user):
    # Simulate a user missing an AppConfig row
    from api import models
    from sqlalchemy import delete

    await db_session.execute(
        delete(models.AppConfig).where(models.AppConfig.user_id == test_user.id)
    )
    await db_session.commit()

    # Requesting config should lazy-create default AppConfig
    config = await crud.get_config(db=db_session, user_id=test_user.id)
    assert config is not None
    assert config.user_id == test_user.id
    assert config.risk_management.maxDrawdown == 10.0
