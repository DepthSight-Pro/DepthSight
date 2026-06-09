# tests/test_multi_account.py
"""
Tests for multi-account (sub-account) functionality.
Cover CRUD operations, API endpoints, and API key activation/deactivation logic.
"""

import pytest
import json
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import MagicMock, AsyncMock

from api import crud, schemas, models
from bot_module.config import REDIS_COMMAND_CHANNEL


async def _clear_api_keys_for_user(db_session: AsyncSession, user_id: int) -> None:
    await db_session.execute(
        delete(models.ApiKey).where(models.ApiKey.user_id == user_id)
    )
    await db_session.commit()


# ============================================================================
# CRUD TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_set_api_key_active_status(
    db_session: AsyncSession, test_user: models.User
):
    """Tests API key activation and deactivation via CRUD."""
    # Create API key
    api_key_data = schemas.ApiKeyCreate(
        name="Test Key for Status",
        api_key="test_key_123",
        api_secret="test_secret_456",
        exchange="binance_futures",
    )
    created_key = await crud.create_api_key_for_user(
        db=db_session, user_id=test_user.id, key_data=api_key_data
    )
    await db_session.commit()
    await db_session.refresh(created_key)

    # By default, the key is active
    assert created_key.is_active is True

    # Deactivate the key
    updated_key = await crud.set_api_key_active_status(
        db=db_session, key_id=created_key.id, user_id=test_user.id, is_active=False
    )
    await db_session.commit()

    assert updated_key is not None
    assert updated_key.is_active is False

    # Activate the key back
    reactivated_key = await crud.set_api_key_active_status(
        db=db_session, key_id=created_key.id, user_id=test_user.id, is_active=True
    )
    await db_session.commit()

    assert reactivated_key is not None
    assert reactivated_key.is_active is True


@pytest.mark.asyncio
async def test_get_active_api_keys_for_user(
    db_session: AsyncSession, test_user: models.User
):
    """Tests getting only active API keys."""
    await _clear_api_keys_for_user(db_session, test_user.id)

    # Create two keys
    key1_data = schemas.ApiKeyCreate(
        name="Active Key",
        api_key="key1",
        api_secret="secret1",
        exchange="binance_futures",
    )
    key2_data = schemas.ApiKeyCreate(
        name="Inactive Key",
        api_key="key2",
        api_secret="secret2",
        exchange="binance_futures",
    )

    await crud.create_api_key_for_user(
        db=db_session, user_id=test_user.id, key_data=key1_data
    )
    key2 = await crud.create_api_key_for_user(
        db=db_session, user_id=test_user.id, key_data=key2_data
    )
    await db_session.commit()

    # Deactivate the second key
    await crud.set_api_key_active_status(
        db=db_session, key_id=key2.id, user_id=test_user.id, is_active=False
    )
    await db_session.commit()

    # Get only active keys
    active_keys = await crud.get_active_api_keys_for_user(
        db=db_session, user_id=test_user.id
    )

    assert len(active_keys) == 1
    assert active_keys[0].name == "Active Key"
    assert active_keys[0].is_active is True


@pytest.mark.asyncio
async def test_set_api_key_active_status_wrong_user(
    db_session: AsyncSession, test_user: models.User
):
    """Tests that the status of another user's key cannot be changed."""
    # Create a key for test_user
    api_key_data = schemas.ApiKeyCreate(
        name="Test Key", api_key="key123", api_secret="secret123", exchange="binance"
    )
    created_key = await crud.create_api_key_for_user(
        db=db_session, user_id=test_user.id, key_data=api_key_data
    )
    await db_session.commit()

    # Attempting to change status on behalf of another user (non-existent ID)
    result = await crud.set_api_key_active_status(
        db=db_session,
        key_id=created_key.id,
        user_id=99999,  # Non-existent user
        is_active=False,
    )

    # Should return None, as the key does not belong to this user
    assert result is None


# ============================================================================
# API ENDPOINT TESTS - uses pro_user_client for consistency
# ============================================================================


@pytest.mark.asyncio
async def test_update_api_key_status_endpoint(
    pro_user_client: AsyncClient, mock_redis_client: MagicMock
):
    """Tests the PATCH endpoint for changing the API key status."""
    # Create an API key via API
    create_response = await pro_user_client.post(
        "/api/v1/config/api-keys",
        json={
            "name": "Endpoint Test Key",
            "api_key": "ep_key_status",
            "api_secret": "ep_secret_status",
            "exchange": "binance_futures",
        },
    )
    assert create_response.status_code == 201, (
        f"Failed to create key: {create_response.text}"
    )
    key_id = create_response.json()["data"]["id"]

    # Deactivate the key via API
    mock_redis_client.publish.reset_mock()
    response = await pro_user_client.patch(
        f"/api/v1/config/api-keys/{key_id}/status", json={"is_active": False}
    )

    assert response.status_code == 200, f"Patch failed: {response.text}"
    data = response.json()["data"]
    assert data["isActive"] is False

    # Checking that the command was sent to Redis
    mock_redis_client.publish.assert_called()
    channel, message_json = mock_redis_client.publish.call_args[0]
    assert channel == REDIS_COMMAND_CHANNEL
    message = json.loads(message_json)
    assert message["command"] == "DEACTIVATE_API_KEY"
    assert message["payload"]["api_key_id"] == key_id


@pytest.mark.asyncio
async def test_update_api_key_status_activates_key(
    pro_user_client: AsyncClient, mock_redis_client: MagicMock
):
    """Tests key activation via API."""
    # Create a key via API
    create_response = await pro_user_client.post(
        "/api/v1/config/api-keys",
        json={
            "name": "To Activate Key",
            "api_key": "activate_key",
            "api_secret": "activate_secret",
            "exchange": "binance_futures",
        },
    )
    assert create_response.status_code == 201
    key_id = create_response.json()["data"]["id"]

    # First, deactivate
    await pro_user_client.patch(
        f"/api/v1/config/api-keys/{key_id}/status", json={"is_active": False}
    )

    # Then activate via API
    mock_redis_client.publish.reset_mock()
    response = await pro_user_client.patch(
        f"/api/v1/config/api-keys/{key_id}/status", json={"is_active": True}
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["isActive"] is True

    # Check the Redis command
    mock_redis_client.publish.assert_called()
    channel, message_json = mock_redis_client.publish.call_args[0]
    message = json.loads(message_json)
    assert message["command"] == "ACTIVATE_API_KEY"


@pytest.mark.asyncio
async def test_update_api_key_status_not_found(pro_user_client: AsyncClient):
    """Tests for a 404 error when trying to change the status of a non-existent key."""
    response = await pro_user_client.patch(
        "/api/v1/config/api-keys/99999/status", json={"is_active": False}
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_multi_account_balances_endpoint(
    pro_user_client: AsyncClient, mocker
):
    """Tests the GET endpoint for getting balances of all active accounts."""
    # Mocking BinanceExecutor to return balance
    mock_executor_class = mocker.patch("api.depthsight_api.create_exchange_executor")
    mock_executor_instance = MagicMock()
    mock_executor_class.return_value = mock_executor_instance
    mock_executor_instance.get_account_balance = AsyncMock(
        return_value={
            "USDT": {"free": "800.00", "locked": "200.50", "unrealized_pnl": "50.25"}
        }
    )

    # Creating an active API key via API
    create_response = await pro_user_client.post(
        "/api/v1/config/api-keys",
        json={
            "name": "Balance Test Key",
            "api_key": "balance_key_test",
            "api_secret": "balance_secret_test",
            "exchange": "binance_futures",
        },
    )
    assert create_response.status_code == 201, f"Create failed: {create_response.text}"

    response = await pro_user_client.get("/api/v1/config/api-keys/balances")

    assert response.status_code == 200
    data = response.json()["data"]

    # API returns snake_case
    assert "total_balance" in data or "totalBalance" in data
    assert "accounts" in data
    assert len(data["accounts"]) >= 1


@pytest.mark.asyncio
async def test_get_multi_account_balances_no_active_keys(
    pro_user_client: AsyncClient,
    db_session: AsyncSession,
    pro_user: models.User,
):
    """Tests the balances endpoint when there are no active keys."""
    await _clear_api_keys_for_user(db_session, pro_user.id)

    # Create a key and deactivate it
    create_response = await pro_user_client.post(
        "/api/v1/config/api-keys",
        json={
            "name": "Inactive Key",
            "api_key": "inactive_key_test",
            "api_secret": "inactive_secret",
            "exchange": "binance_futures",
        },
    )
    assert create_response.status_code == 201
    key_id = create_response.json()["data"]["id"]

    # Deactivate the key
    await pro_user_client.patch(
        f"/api/v1/config/api-keys/{key_id}/status", json={"is_active": False}
    )

    response = await pro_user_client.get("/api/v1/config/api-keys/balances")

    assert response.status_code == 200
    data = response.json()["data"]

    # API can return snake_case or camelCase
    total_balance = data.get("total_balance", data.get("totalBalance", 0))
    assert total_balance == 0
    assert len(data["accounts"]) == 0


@pytest.mark.asyncio
async def test_api_key_is_active_field_in_config(
    pro_user_client: AsyncClient,
):
    """Tests that the isActive field is present in the configuration response."""
    # Create a key via API
    create_response = await pro_user_client.post(
        "/api/v1/config/api-keys",
        json={
            "name": "Config Test Key",
            "api_key": "config_key_test",
            "api_secret": "config_secret",
            "exchange": "binance_futures",
        },
    )
    assert create_response.status_code == 201

    response = await pro_user_client.get("/api/v1/config")

    assert response.status_code == 200
    data = response.json()["data"]

    assert "apiKeys" in data
    assert len(data["apiKeys"]) >= 1

    api_key = data["apiKeys"][0]
    assert "isActive" in api_key
    assert api_key["isActive"] is True


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_full_multi_account_workflow(
    pro_user_client: AsyncClient,
    mock_redis_client: MagicMock,
    db_session: AsyncSession,
    pro_user: models.User,
    mocker,
):
    """
    Integration test of the full multi-account workflow:
    1. Creating two API keys
    2. Getting balances
    3. Deactivating one key
    4. Checking that balances are only for the active key
    5. Reactivation
    """
    # Mock BinanceExecutor
    mock_executor_class = mocker.patch("api.depthsight_api.create_exchange_executor")
    mock_executor_instance = MagicMock()
    mock_executor_class.return_value = mock_executor_instance
    mock_executor_instance.get_account_balance = AsyncMock(
        return_value={
            "USDT": {"free": "400.00", "locked": "100.00", "unrealized_pnl": "10.00"}
        }
    )

    # 1. Create two keys via API
    await _clear_api_keys_for_user(db_session, pro_user.id)

    key1_response = await pro_user_client.post(
        "/api/v1/config/api-keys",
        json={
            "name": "Account 1 Multi",
            "api_key": "key_account_1_multi",
            "api_secret": "secret_1_multi",
            "exchange": "binance_futures",
        },
    )
    assert key1_response.status_code == 201, (
        f"Key1 creation failed: {key1_response.text}"
    )
    key1_id = key1_response.json()["data"]["id"]

    key2_response = await pro_user_client.post(
        "/api/v1/config/api-keys",
        json={
            "name": "Account 2 Multi",
            "api_key": "key_account_2_multi",
            "api_secret": "secret_2_multi",
            "exchange": "binance_futures",
        },
    )
    assert key2_response.status_code == 201, (
        f"Key2 creation failed: {key2_response.text}"
    )

    # 2. Getting balances - both accounts should be present (filtering by market to avoid duplicates with spot)
    balances_response = await pro_user_client.get(
        "/api/v1/config/api-keys/balances?market_type=futures_usdtm"
    )
    assert balances_response.status_code == 200
    balances = balances_response.json()["data"]
    assert len(balances["accounts"]) == 2

    # 3. Deactivate the first key
    mock_redis_client.publish.reset_mock()
    deactivate_response = await pro_user_client.patch(
        f"/api/v1/config/api-keys/{key1_id}/status", json={"is_active": False}
    )
    assert deactivate_response.status_code == 200

    # Check the Redis command
    mock_redis_client.publish.assert_called_once()
    _, message_json = mock_redis_client.publish.call_args[0]
    message = json.loads(message_json)
    assert message["command"] == "DEACTIVATE_API_KEY"

    # 4. Balances only for the active one
    balances_after = await pro_user_client.get(
        "/api/v1/config/api-keys/balances?market_type=futures_usdtm"
    )
    balances_data = balances_after.json()["data"]
    assert len(balances_data["accounts"]) == 1

    # 5. Reactivate
    mock_redis_client.publish.reset_mock()
    reactivate_response = await pro_user_client.patch(
        f"/api/v1/config/api-keys/{key1_id}/status", json={"is_active": True}
    )
    assert reactivate_response.status_code == 200

    _, message_json = mock_redis_client.publish.call_args[0]
    message = json.loads(message_json)
    assert message["command"] == "ACTIVATE_API_KEY"

    # Final check - two accounts again
    final_balances = await pro_user_client.get(
        "/api/v1/config/api-keys/balances?market_type=futures_usdtm"
    )
    assert len(final_balances.json()["data"]["accounts"]) == 2
