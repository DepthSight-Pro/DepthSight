import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

import json
from datetime import datetime, timezone
from typing import Optional

from .. import crud, models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..redis_client import get_redis_client
from ..plans import plans_config

try:
    from bot_module import config as bot_config
except ImportError:

    class MockConfig:
        REDIS_COMMAND_CHANNEL = "depthsight:commands"

    bot_config = MockConfig()

REDIS_COMMAND_CHANNEL = getattr(
    bot_config, "REDIS_COMMAND_CHANNEL", "depthsight:commands"
)
HFT_CMD_CHANNEL = "hft:commands"

logger = logging.getLogger(__name__)

config_router = APIRouter(
    prefix="/api/v1",
    tags=["Configuration"],
    dependencies=[Depends(get_current_user)],
)


@config_router.get(
    "/config",
    response_model=schemas.ApiResponseData[schemas.AppConfig],
    summary="Get current configuration",
)
async def get_config_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) fetching application configuration."
    )
    config = await crud.get_config(db, user_id=current_user.id)
    if not config:
        logger.warning(
            f"AppConfig for user '{current_user.username}' (ID: {current_user.id}) not found."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Configuration for user {current_user.username} not found.",
        )
    return {"data": config}


@config_router.put(
    "/config",
    response_model=schemas.ApiResponseData[schemas.AppConfig],
    summary="Update configuration",
)
async def update_config_endpoint(
    new_config: schemas.AppConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) updating application configuration."
    )

    updated_any_section = False
    if new_config.risk_management:
        await crud.update_config_section(
            db,
            current_user.id,
            "risk_management",
            new_config.risk_management.model_dump(by_alias=True),
        )
        updated_any_section = True
    if new_config.exchange_settings:
        await crud.update_config_section(
            db,
            current_user.id,
            "exchange_settings",
            new_config.exchange_settings.model_dump(by_alias=True),
        )
        updated_any_section = True
    if new_config.notifications:
        await crud.update_config_section(
            db,
            current_user.id,
            "notifications",
            new_config.notifications.model_dump(by_alias=True),
        )
        updated_any_section = True
    if new_config.data_sources:
        await crud.update_config_section(
            db, current_user.id, "data_sources", new_config.data_sources
        )
        updated_any_section = True
    if new_config.backtest_risk_management:
        await crud.update_config_section(
            db,
            current_user.id,
            "backtest_risk_management",
            new_config.backtest_risk_management.model_dump(by_alias=True),
        )
        updated_any_section = True

    if not updated_any_section:
        logger.info(
            f"User '{current_user.username}' (ID: {current_user.id}) - No specific configuration sections provided for update."
        )
        pass

    await db.commit()

    updated_db_config = await crud.get_config(db, user_id=current_user.id)
    if not updated_db_config:
        logger.error(
            f"User '{current_user.username}' (ID: {current_user.id}) - Failed to retrieve configuration after update."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve configuration after update.",
        )

    # --- Publish RELOAD_CONFIG command to apply settings instantly in the bot ---
    if updated_any_section:
        try:
            reload_command = {
                "command": "RELOAD_CONFIG",
                "payload": {"user_id": current_user.id},
            }
            await redis_client.publish(
                REDIS_COMMAND_CHANNEL, json.dumps(reload_command)
            )
            logger.info(
                f"User '{current_user.username}' (ID: {current_user.id}) - RELOAD_CONFIG command published to bot."
            )
        except Exception as e:
            # Do not block response on publish error - settings will apply on next reload cycle anyway
            logger.warning(
                f"Failed to publish RELOAD_CONFIG command for user {current_user.id}: {e}"
            )

    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) - Application configuration updated successfully."
    )
    return {"data": updated_db_config}


@config_router.post(
    "/config/datasources/symbols", response_model=schemas.ApiResponseData
)
async def add_symbol(
    payload: schemas.SymbolPayload,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) attempting to add symbol: {payload.symbol}"
    )
    updated_sources = await crud.add_symbol_to_config(
        db, user_id=current_user.id, symbol=payload.symbol
    )
    if updated_sources is None:
        logger.error(
            f"User '{current_user.username}' (ID: {current_user.id}) - Failed to add symbol {payload.symbol}. User configuration (AppConfig) not found."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User configuration not found. Cannot add symbol.",
        )

    await db.commit()
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) successfully added symbol: {payload.symbol}. Current symbols: {updated_sources.get('symbols')}"
    )
    return {"data": updated_sources}


@config_router.delete(
    "/config/datasources/symbols/{symbol}", response_model=schemas.ApiResponseData
)
async def delete_symbol(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) attempting to delete symbol: {symbol}"
    )
    updated_sources = await crud.delete_symbol_from_config(
        db, user_id=current_user.id, symbol=symbol
    )
    if updated_sources is None:
        logger.error(
            f"User '{current_user.username}' (ID: {current_user.id}) - Failed to delete symbol {symbol}. User configuration (AppConfig) not found or symbol already not present."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User configuration not found or symbol not in list.",
        )

    await db.commit()
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) successfully deleted symbol: {symbol}. Current symbols: {updated_sources.get('symbols')}"
    )
    return {"data": updated_sources}


@config_router.get(
    "/config/blacklist",
    response_model=schemas.ApiResponseData[schemas.BlacklistSettings],
)
async def get_blacklist(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Returns current coin blacklist of the user.
    Automatically clears expired entries before returning.
    """
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) requesting blacklist."
    )

    config = await crud.get_config(db, user_id=current_user.id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User configuration not found.",
        )

    # Get blacklist from risk_management
    risk_management = config.risk_management or {}
    # Convert Pydantic model to dictionary if needed
    if hasattr(risk_management, "model_dump"):
        risk_management = risk_management.model_dump(mode="json")
    elif not isinstance(risk_management, dict):
        risk_management = {}

    blacklist_data = risk_management.get("blacklist") or {"coins": []}

    # Clear expired entries
    now = datetime.now(timezone.utc)
    active_coins = []
    for coin in blacklist_data.get("coins", []):
        until_str = coin.get("until")
        if until_str:
            try:
                until_dt = datetime.fromisoformat(until_str.replace("Z", "+00:00"))
                if until_dt > now:
                    active_coins.append(coin)
            except (ValueError, TypeError):
                # If date parsing fails, consider it permanent
                active_coins.append(coin)
        else:
            # until is None = permanent
            active_coins.append(coin)

    # If there were changes, save the cleared list
    if len(active_coins) != len(blacklist_data.get("coins", [])):
        blacklist_data["coins"] = active_coins
        risk_management["blacklist"] = blacklist_data
        await crud.update_config_section(
            db, current_user.id, "risk_management", risk_management
        )
        await db.commit()

    # Get autoRules
    auto_rules_data = blacklist_data.get("autoRules", [])
    auto_rules = (
        [schemas.AutoBlacklistRule(**rule) for rule in auto_rules_data]
        if auto_rules_data
        else []
    )

    return {
        "data": schemas.BlacklistSettings(
            coins=[schemas.BlacklistedCoin(**coin) for coin in active_coins],
            auto_rules=auto_rules,
        )
    }


@config_router.post(
    "/config/blacklist",
    response_model=schemas.ApiResponseData[schemas.BlacklistSettings],
)
async def add_to_blacklist(
    payload: schemas.AddToBlacklistPayload,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Adds a coin to the user's blacklist.
    """
    symbol = payload.symbol.upper().strip()
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) adding {symbol} to blacklist with duration: {payload.duration}"
    )

    config = await crud.get_config(db, user_id=current_user.id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User configuration not found.",
        )

    # Determine block time
    until: Optional[datetime] = None
    if payload.duration == "end_of_day":
        # End of current day UTC
        now = datetime.now(timezone.utc)
        until = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif payload.duration == "custom" and payload.custom_until:
        until = payload.custom_until
    # permanent -> until remains None

    # Get current blacklist
    risk_management = config.risk_management or {}
    # Convert Pydantic model to dictionary if needed
    if hasattr(risk_management, "model_dump"):
        risk_management = risk_management.model_dump(mode="json")
    elif isinstance(risk_management, str):
        import json

        risk_management = json.loads(risk_management)
    elif not isinstance(risk_management, dict):
        risk_management = {}

    blacklist_data = risk_management.get("blacklist", {"coins": []})
    if not isinstance(blacklist_data, dict):
        blacklist_data = {"coins": []}

    coins = blacklist_data.get("coins", [])
    if not isinstance(coins, list):
        coins = []

    # Check if such coin already exists
    for coin in coins:
        if coin.get("symbol", "").upper() == symbol:
            # Update existing entry
            coin["until"] = until.isoformat() if until else None
            coin["reason"] = payload.reason
            coin["addedAt"] = datetime.now(timezone.utc).isoformat()
            logger.info(f"Updated existing blacklist entry for {symbol}")
            break
    else:
        # Add new entry
        new_coin = {
            "symbol": symbol,
            "until": until.isoformat() if until else None,
            "reason": payload.reason,
            "addedAt": datetime.now(timezone.utc).isoformat(),
        }
        coins.append(new_coin)
        logger.info(f"Added new blacklist entry for {symbol}")

    # Save updated blacklist
    blacklist_data["coins"] = coins
    risk_management["blacklist"] = blacklist_data
    await crud.update_config_section(
        db, current_user.id, "risk_management", risk_management
    )
    await db.commit()

    try:
        redis = await get_redis_client()

        # 1. Update simple blacklist set (hft:blacklist:{user_id}) for fast lookup
        # Only active, existing coins
        active_symbols = [c.get("symbol", "").upper() for c in coins if c.get("symbol")]
        await redis.set(f"hft:blacklist:{current_user.id}", json.dumps(active_symbols))

        # 2. Publish full UpdateBlacklist command to HFT engine
        # Need to construct the full settings object
        auto_rules = blacklist_data.get("autoRules", [])
        settings = {"coins": coins, "autoRules": auto_rules}

        cmd = {
            "action": "UpdateBlacklist",
            "user_id": current_user.id,
            "settings": settings,
        }
        await redis.publish(HFT_CMD_CHANNEL, json.dumps(cmd))
        logger.info(f"Published UpdateBlacklist command for user {current_user.id}")

    except Exception as e:
        logger.error(f"Failed to sync blacklist to Redis: {e}")

    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) successfully added {symbol} to blacklist."
    )

    return {
        "data": schemas.BlacklistSettings(
            coins=[schemas.BlacklistedCoin(**coin) for coin in coins]
        )
    }


@config_router.delete(
    "/config/blacklist/{symbol}",
    response_model=schemas.ApiResponseData[schemas.BlacklistSettings],
)
async def remove_from_blacklist(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Removes a coin from the user's blacklist.
    """
    symbol = symbol.upper().strip()
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) removing {symbol} from blacklist."
    )

    config = await crud.get_config(db, user_id=current_user.id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User configuration not found.",
        )

    # Get current blacklist
    risk_management = config.risk_management or {}
    # Convert Pydantic model to dictionary if needed
    if hasattr(risk_management, "model_dump"):
        risk_management = risk_management.model_dump(mode="json")
    elif isinstance(risk_management, str):
        import json

        risk_management = json.loads(risk_management)
    elif not isinstance(risk_management, dict):
        risk_management = {}

    blacklist_data = risk_management.get("blacklist", {"coins": []})
    if not isinstance(blacklist_data, dict):
        blacklist_data = {"coins": []}

    coins = blacklist_data.get("coins", [])
    if not isinstance(coins, list):
        coins = []

    # Filter coin
    original_count = len(coins)
    coins = [coin for coin in coins if coin.get("symbol", "").upper() != symbol]

    if len(coins) == original_count:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Symbol {symbol} not found in blacklist.",
        )

    # Save updated blacklist
    blacklist_data["coins"] = coins
    risk_management["blacklist"] = blacklist_data
    await crud.update_config_section(
        db, current_user.id, "risk_management", risk_management
    )
    await db.commit()

    try:
        redis = await get_redis_client()

        active_symbols = [c.get("symbol", "").upper() for c in coins if c.get("symbol")]
        await redis.set(f"hft:blacklist:{current_user.id}", json.dumps(active_symbols))

        auto_rules = blacklist_data.get("autoRules", [])
        settings = {"coins": coins, "autoRules": auto_rules}

        cmd = {
            "action": "UpdateBlacklist",
            "user_id": current_user.id,
            "settings": settings,
        }
        await redis.publish(HFT_CMD_CHANNEL, json.dumps(cmd))
        logger.info(f"Published UpdateBlacklist command for user {current_user.id}")

    except Exception as e:
        logger.error(f"Failed to sync blacklist to Redis: {e}")

    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) successfully removed {symbol} from blacklist."
    )

    return {
        "data": schemas.BlacklistSettings(
            coins=[schemas.BlacklistedCoin(**coin) for coin in coins]
        )
    }


@config_router.put(
    "/config/blacklist/rules",
    response_model=schemas.ApiResponseData[schemas.BlacklistSettings],
)
async def update_auto_blacklist_rules(
    payload: schemas.UpdateAutoBlacklistRulesPayload,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Updates automatic block rules for the user.
    """
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) updating auto-blacklist rules. Count: {len(payload.autoRules)}"
    )

    config = await crud.get_config(db, user_id=current_user.id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User configuration not found.",
        )

    # Get current risk_management
    risk_management = config.risk_management or {}
    if hasattr(risk_management, "model_dump"):
        risk_management = risk_management.model_dump(mode="json")
    elif isinstance(risk_management, str):
        import json

        risk_management = json.loads(risk_management)
    elif not isinstance(risk_management, dict):
        risk_management = {}

    blacklist_data = risk_management.get("blacklist", {"coins": []})
    if not isinstance(blacklist_data, dict):
        blacklist_data = {"coins": []}

    # Update auto_rules, serializing rules to dictionaries with camelCase keys
    blacklist_data["autoRules"] = [
        rule.model_dump(mode="json", by_alias=True) for rule in payload.autoRules
    ]

    # Save updated blacklist
    risk_management["blacklist"] = blacklist_data
    await crud.update_config_section(
        db, current_user.id, "risk_management", risk_management
    )
    await db.commit()

    try:
        redis = await get_redis_client()

        coins = blacklist_data.get("coins", [])
        active_symbols = [c.get("symbol", "").upper() for c in coins if c.get("symbol")]
        await redis.set(f"hft:blacklist:{current_user.id}", json.dumps(active_symbols))

        # Payload autoRules are already Pydantic models in the input, but we serialized them for DB
        # Use the raw JSON list we just created
        settings = {"coins": coins, "autoRules": blacklist_data["autoRules"]}

        cmd = {
            "action": "UpdateBlacklist",
            "user_id": current_user.id,
            "settings": settings,
        }
        await redis.publish(HFT_CMD_CHANNEL, json.dumps(cmd))
        logger.info(f"Published UpdateBlacklist command for user {current_user.id}")

    except Exception as e:
        logger.error(f"Failed to sync blacklist to Redis: {e}")

    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) successfully updated auto-blacklist rules."
    )

    return {
        "data": schemas.BlacklistSettings(
            coins=[
                schemas.BlacklistedCoin(**coin)
                for coin in blacklist_data.get("coins", [])
            ],
            auto_rules=payload.autoRules,
        )
    }


@config_router.get(
    "/config/block-restrictions",
    response_model=schemas.ApiResponseData[schemas.BlockRestrictionsConfig],
)
async def get_block_restrictions(current_user: models.User = Depends(get_current_user)):
    restrictions = plans_config.get_block_restrictions()
    return {"data": restrictions}
