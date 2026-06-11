import logging
import json
import asyncio
import aiohttp
import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..redis_client import get_redis_client
from ..audit_logger import audit_logger, get_client_ip
from ..gamification import grant_achievement
from .. import security
from bot_module.exchanges import exchange_settings_key
from ..live_runtime import (
    build_activate_api_key_command,
    build_deactivate_api_key_command,
)
from ..session_manager import get_aiohttp_session

try:
    from bot_module import config as bot_config
except ImportError:

    class MockConfig:
        REDIS_COMMAND_CHANNEL = "depthsight:commands"

    bot_config = MockConfig()
REDIS_COMMAND_CHANNEL = getattr(
    bot_config, "REDIS_COMMAND_CHANNEL", "depthsight:commands"
)

logger = logging.getLogger(__name__)

api_keys_router = APIRouter(
    prefix="/api/v1/config/api-keys",
    tags=["API Keys"],
    dependencies=[Depends(get_current_user)],
)


@api_keys_router.post(
    "",
    response_model=schemas.ApiResponseData[schemas.ApiKey],
    status_code=status.HTTP_201_CREATED,
)
async def add_api_key(
    request: Request,
    api_key_data: schemas.ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) adding new API key: {api_key_data.name}"
    )

    # Check if this is the first API key
    is_first_key = not current_user.api_keys

    # Create the API key with duplicate check
    try:
        db_api_key = await crud.create_api_key_for_user(
            db=db, user_id=current_user.id, key_data=api_key_data
        )
        await db.commit()
        await db.refresh(db_api_key)
    except ValueError as e:
        logger.warning(
            f"User '{current_user.username}' (ID: {current_user.id}) tried to add duplicate API key: {str(e)}"
        )
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) successfully added API key '{db_api_key.name}' (ID: {db_api_key.id})."
    )

    # Grant 'first_api_key' achievement
    if is_first_key:
        await grant_achievement(db, current_user.id, "first_api_key")

    # Referral bonus activation logic - only for first UNIQUE key
    if is_first_key and current_user.referred_by_user_id:
        logger.info(
            f"Activating referral bonuses for user {current_user.id} and referrer {current_user.referred_by_user_id}."
        )
        await crud.activate_bonuses_for_user(db, user_id=current_user.id)
        await crud.activate_bonuses_for_user(
            db, user_id=current_user.referred_by_user_id
        )
        await db.commit()

    # Now, check if we should set it as the active key
    try:
        config = await crud.get_config(db, user_id=current_user.id)
        if config:
            # Get current settings or create a new dict if they don't exist
            current_exchange_settings = config.exchange_settings or {}

            settings_key = exchange_settings_key(db_api_key.exchange)
            exchange_settings = current_exchange_settings.get(settings_key, {})

            # Check if an active key is already set or if the name is empty
            if not exchange_settings.get("api_key_name"):
                logger.info(
                    f"No active key set for {settings_key} for user {current_user.id}. Setting '{db_api_key.name}' as active."
                )

                # Update the settings
                exchange_settings["api_key_name"] = db_api_key.name
                exchange_settings["enabled"] = True  # Also enable the exchange
                current_exchange_settings[settings_key] = exchange_settings

                # Update the entire section in the DB
                await crud.update_config_section(
                    db, current_user.id, "exchange_settings", current_exchange_settings
                )
                await db.commit()
                logger.info(
                    f"Successfully set '{db_api_key.name}' as the active key for user {current_user.id}."
                )

    except Exception as e:
        logger.error(
            f"Failed to set new API key as active for user {current_user.id}. The key was saved but not activated. Error: {e}",
            exc_info=True,
        )

    try:
        command = build_activate_api_key_command(current_user.id, db_api_key.id)
        await redis_client.publish(REDIS_COMMAND_CHANNEL, json.dumps(command))
        logger.info(
            "Published ACTIVATE_API_KEY command for user %s, key %s",
            current_user.id,
            db_api_key.id,
        )
    except Exception as e:
        logger.error(
            "Failed to publish ACTIVATE_API_KEY command for user %s, key %s: %s",
            current_user.id,
            db_api_key.id,
            e,
            exc_info=True,
        )
        # Don't fail the request: the controller will be initialized on next bot restart.

    # We need to return a schema-compliant object. The db_api_key is a model instance.
    # --- Audit Log ---
    audit_logger.api_key_created(
        user_id=current_user.id,
        username=current_user.username,
        key_id=db_api_key.id,
        exchange=db_api_key.exchange,
        ip_address=get_client_ip(request),
    )
    return {"data": schemas.ApiKey.model_validate(db_api_key)}


@api_keys_router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    request: Request,
    key_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) attempting to delete API key ID: {key_id}"
    )
    deleted_key = await crud.delete_api_key(
        db=db, user_id=current_user.id, key_id=key_id
    )
    if not deleted_key:
        logger.warning(
            f"User '{current_user.username}' (ID: {current_user.id}) - Failed to delete API key {key_id}. Not found or not authorized."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        )
    await db.commit()
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) successfully deleted API key ID: {key_id}."
    )
    try:
        command = build_deactivate_api_key_command(current_user.id, key_id)
        await redis_client.publish(REDIS_COMMAND_CHANNEL, json.dumps(command))
        logger.info(
            "Published DEACTIVATE_API_KEY command for user %s, key %s after API key deletion.",
            current_user.id,
            key_id,
        )
    except Exception as e:
        logger.error(
            "Failed to publish DEACTIVATE_API_KEY command for user %s, key %s: %s",
            current_user.id,
            key_id,
            e,
            exc_info=True,
        )
        # Don't fail the request: DB deletion succeeded and stale controllers will disappear on bot restart.
    # --- Audit Log ---
    audit_logger.api_key_deleted(
        user_id=current_user.id,
        username=current_user.username,
        key_id=key_id,
        ip_address=get_client_ip(request),
    )
    return None


@api_keys_router.patch(
    "/{key_id}/status",
    response_model=schemas.ApiResponseData[schemas.ApiKey],
)
async def update_api_key_status_active(
    request: Request,
    key_id: int,
    status_update: schemas.ApiKeyStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Activates or deactivates an API key.
    Sends commands to the bot to start/stop controllers.
    """
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) updating status for API key {key_id} to active={status_update.is_active}"
    )

    # 1. Update in DB
    updated_key = await crud.set_api_key_active_status(
        db, user_id=current_user.id, key_id=key_id, is_active=status_update.is_active
    )
    if not updated_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        )

    await db.commit()
    await db.refresh(updated_key)

    # 2. Notify Bot via Redis
    command_type = (
        "ACTIVATE_API_KEY" if status_update.is_active else "DEACTIVATE_API_KEY"
    )
    command = {
        "command": command_type,
        "payload": {"user_id": current_user.id, "api_key_id": key_id},
    }

    try:
        await redis_client.publish(REDIS_COMMAND_CHANNEL, json.dumps(command))
        logger.info(
            f"Published {command_type} for user {current_user.id}, key {key_id}"
        )
    except Exception as e:
        logger.error(f"Failed to publish {command_type} to Redis: {e}", exc_info=True)
        # We don't fail the request because DB is updated and bot will sync on restart
        # (or user can try again)

    # --- Audit Log ---
    audit_logger.api_key_status_changed(
        user_id=current_user.id,
        username=current_user.username,
        key_id=key_id,
        is_active=status_update.is_active,
        ip_address=get_client_ip(request),
    )
    return {"data": schemas.ApiKey.model_validate(updated_key)}


@api_keys_router.get(
    "/balances",
    response_model=schemas.ApiResponseData[schemas.MultiAccountOverview],
)
async def get_multi_account_balances(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    http_session: aiohttp.ClientSession = Depends(get_aiohttp_session),
    market_type: str = Query(
        "all",
        description="Market scope: all, futures, futures_usdtm, or spot",
    ),
):
    """
    Fetches and aggregates account balances for all active API keys of the current user.
    """
    from ..depthsight_api import (
        normalize_market_type_filter,
        market_types_for_filter,
        fetch_api_key_market_balance,
        build_market_balance_breakdown,
        get_deduplicated_balances_for_totals,
    )

    normalized_market_type = normalize_market_type_filter(market_type)
    requested_market_types = market_types_for_filter(normalized_market_type)
    logger.info(
        "User '%s' (ID: %s) fetching multi-account balances. Market: %s",
        current_user.username,
        current_user.id,
        normalized_market_type,
    )

    # 1. Get all active API keys
    active_keys = await crud.get_active_api_keys_for_user(db, user_id=current_user.id)

    async def fetch_balance_or_empty(
        key_obj: models.ApiKey, market: str
    ) -> schemas.AccountBalance:
        try:
            return await fetch_api_key_market_balance(
                key_obj=key_obj,
                http_session=http_session,
                market_type=market,
            )
        except Exception as e:
            logger.error(
                "Error fetching %s balance for key %s (ID: %s): %s",
                market,
                key_obj.name,
                key_obj.id,
                e,
            )
            return schemas.AccountBalance(
                api_key_id=key_obj.id,
                api_key_name=key_obj.name,
                exchange=key_obj.exchange,
                market_type=market,
                balance=0.0,
                available_balance=0.0,
                unrealized_pnl=0.0,
                margin_used=0.0,
                total_equity=0.0,
                assets=[],
            )

    tasks = [
        fetch_balance_or_empty(key_obj, market)
        for key_obj in active_keys
        for market in requested_market_types
    ]
    accounts_balances = await asyncio.gather(*tasks) if tasks else []
    market_breakdown = build_market_balance_breakdown(list(accounts_balances))
    dedup_balances = get_deduplicated_balances_for_totals(list(accounts_balances))

    return {
        "data": schemas.MultiAccountOverview(
            market_type=normalized_market_type,
            total_balance=sum(account.balance for account in dedup_balances),
            total_available=sum(
                account.available_balance for account in dedup_balances
            ),
            total_unrealized_pnl=sum(
                account.unrealized_pnl for account in dedup_balances
            ),
            total_margin_used=sum(account.margin_used for account in dedup_balances),
            total_equity=sum(account.total_equity for account in dedup_balances),
            market_breakdown=market_breakdown,
            accounts=accounts_balances,
        )
    }


@api_keys_router.post(
    "/{key_id}/test",
    response_model=schemas.ApiResponseData[schemas.ApiKey],
)
async def test_api_key(
    request: Request,
    key_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    http_session: aiohttp.ClientSession = Depends(
        get_aiohttp_session
    ),  # Re-use session
):
    """
    Tests the validity of an API key by trying to fetch account balance from the exchange.
    Updates the key's status to 'valid' or 'invalid'.
    """
    from ..depthsight_api import create_exchange_executor

    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) testing API key ID: {key_id}"
    )

    # 1. Get the key from DB
    db_key = await crud.get_api_key_by_id(db, user_id=current_user.id, key_id=key_id)
    if not db_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        )

    # 2. Decrypt credentials
    try:
        api_key = security.decrypt_data(db_key.encrypted_api_key)
        api_secret = security.decrypt_data(db_key.encrypted_api_secret)
        if not api_key or not api_secret:
            raise ValueError("Failed to decrypt API credentials.")
    except Exception as e:
        logger.error(
            f"Decryption failed for key {key_id} for user {current_user.id}: {e}"
        )
        audit_logger.api_key_decrypt_failed(
            user_id=current_user.id,
            username=current_user.username,
            key_id=key_id,
            ip_address=get_client_ip(request),
        )
        await crud.update_api_key_status(
            db,
            key_id=key_id,
            user_id=current_user.id,
            status="invalid",
            status_message="Decryption failed",
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process API key.",
        )

    # 3. Test credentials against the exchange
    new_status = "invalid"
    status_message = ""
    executor = None
    try:
        logger.info(
            f"Testing key '{db_key.name}' for user {current_user.id} against {db_key.exchange}..."
        )
        # We use a shared session for performance
        executor = create_exchange_executor(
            exchange=db_key.exchange,
            api_key=api_key,
            api_secret=api_secret,
            session=http_session,
        )

        # A lightweight call to check credentials. Empty balances are still a
        # valid exchange response; a zero-funded key must not be marked invalid.
        balance_data = await executor.get_account_balance()
        credentials_accepted = (
            isinstance(balance_data, dict) and "error" not in balance_data
        )

        if not credentials_accepted and getattr(executor, "exchange_id", "") == "bingx":
            # BingX VST/live keys may fail or return an empty balance through
            # CCXT's balance route while futures private endpoints still accept
            # the credentials. This mirrors the BingX e2e path more closely.
            try:
                if getattr(executor, "supports_positions", False):
                    await executor._exchange.fetch_positions(params={"type": "swap"})
                else:
                    await executor._exchange.fetch_open_orders(
                        None, params={"type": "spot"}
                    )
                credentials_accepted = True
            except Exception as bingx_validation_error:
                logger.warning(
                    "BingX fallback credential check failed for key %s: %s",
                    key_id,
                    bingx_validation_error,
                    exc_info=True,
                )

        # The actual check for validity depends on the response structure
        if credentials_accepted:
            # More specific check if possible, e.g. based on error codes for invalid keys
            new_status = "valid"
            status_message = "Connection successful."
            logger.info(f"API key ID {key_id} for user {current_user.id} is valid.")
        else:
            error_msg = (
                balance_data.get("msg", "Unknown error from exchange.")
                if isinstance(balance_data, dict)
                else "Invalid response format."
            )
            status_message = f"Test failed: {error_msg}"
            logger.warning(
                f"API key ID {key_id} for user {current_user.id} is invalid. Reason: {status_message}"
            )

    except Exception as e:
        status_message = f"Test failed with exception: {str(e)}"
        logger.error(
            f"Exception while testing API key {key_id} for user {current_user.id}: {e}",
            exc_info=True,
        )
        new_status = "invalid"
    finally:
        close_method = getattr(executor, "close", None)
        if callable(close_method):
            try:
                await close_method()
            except Exception as close_error:
                logger.debug(
                    "Failed to close API key test executor for key %s: %s",
                    key_id,
                    close_error,
                    exc_info=True,
                )

    # 4. Update status in DB
    updated_key = await crud.update_api_key_status(
        db,
        key_id=key_id,
        user_id=current_user.id,
        status=new_status,
        status_message=status_message,
    )
    await db.commit()
    await db.refresh(updated_key)

    # --- Audit Log ---
    audit_logger.api_key_tested(
        user_id=current_user.id,
        username=current_user.username,
        key_id=key_id,
        test_result=new_status,
        ip_address=get_client_ip(request),
    )

    return {"data": schemas.ApiKey.model_validate(updated_key)}
