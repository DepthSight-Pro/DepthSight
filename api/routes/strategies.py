import logging
import json
from typing import List, Optional
import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas, ai_assistant
from ..auth import get_current_user
from ..database import get_db
from ..redis_client import get_redis_client
from ..dependencies import require_permission, is_strategy_kline_only
from ..gamification import grant_achievement

try:
    from bot_module import config as bot_config
except ImportError:

    class MockConfig:
        REDIS_STATE_KEY_STRATEGIES = "depthsight:state:strategies"
        REDIS_COMMAND_CHANNEL = "depthsight:commands"

    bot_config = MockConfig()
REDIS_COMMAND_CHANNEL = getattr(
    bot_config, "REDIS_COMMAND_CHANNEL", "depthsight:commands"
)

logger = logging.getLogger(__name__)

strategies_router = APIRouter(
    prefix="/api/v1/strategies",
    tags=["Strategies"],
    dependencies=[Depends(get_current_user)],
)


@strategies_router.get(
    "", response_model=schemas.ApiResponseData[List[schemas.StrategyInfo]]
)
async def list_strategies(
    redis_client: redis.Redis = Depends(get_redis_client),
    current_user: models.User = Depends(get_current_user),
    mode: str = Query("live", enum=["live", "paper"]),
    api_key_id: Optional[int] = Query(
        None, description="Filter by specific API key (subaccount)"
    ),
):
    """
    Fetches the list of running strategy instances for the current user from Redis,
    filtered by the selected trading mode ('live' or 'paper') and optionally by api_key_id.
    """
    logger.info(
        f"User '{current_user.username}' listing running '{mode}' strategies from Redis. api_key_id filter: {api_key_id}"
    )
    # Use user-specific key to isolate data between users
    # New structure: strategies:user_id:api_key_id
    base_strategies_key = f"{bot_config.REDIS_STATE_KEY_STRATEGIES}:{current_user.id}"

    strategies_data = []

    try:
        if api_key_id is not None:
            # Fetch for specific account
            specific_key = f"{base_strategies_key}:{api_key_id}"
            strategies_json = await redis_client.get(specific_key)
            if strategies_json:
                strategies_data.extend(json.loads(strategies_json))
        else:
            # Aggregation: Scan for all keys associated with this user
            pattern = f"{base_strategies_key}:*"
            keys = await redis_client.keys(pattern)
            if keys:
                values = await redis_client.mget(keys)
                for v in values:
                    if v:
                        strategies_data.extend(json.loads(v))

        if not strategies_data:
            return {"data": []}

        # Filter strategies for the requested mode (user_id already filtered by key)
        user_mode_strategies = [
            s
            for s in strategies_data
            if s.get("mode") == mode and str(s.get("user_id")) == str(current_user.id)
        ]

        # --- MULTI-ACCOUNT: Filter by api_key_id if specified ---
        if api_key_id is not None:
            user_mode_strategies = [
                s for s in user_mode_strategies if s.get("api_key_id") == api_key_id
            ]

        validated_strategies = [schemas.StrategyInfo(**s) for s in user_mode_strategies]
        return {"data": validated_strategies}
    except Exception as e:
        logger.error(
            f"Error processing strategies state from Redis: {e}", exc_info=True
        )
        return {"data": []}


@strategies_router.get(
    "/config",
    response_model=schemas.ApiResponseData[List[schemas.StrategyConfig]],
)
async def list_saved_strategy_configurations(
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns list of ALL saved strategy configurations for the user from DB.
    """
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) listing saved strategy configs from DB."
    )
    try:
        configs = await crud.get_strategy_configs_by_user(db, user_id=current_user.id)
        # Explicitly validate each ORM model against the Pydantic schema
        validated_configs = [schemas.StrategyConfig.model_validate(c) for c in configs]
        return {"data": validated_configs}
    except Exception as e:
        logger.error(
            f"User '{current_user.username}' (ID: {current_user.id}) - DB Error listing configs: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Database error while fetching strategy configurations.",
        )


@strategies_router.post(
    "/generate-from-text",
    response_model=schemas.ApiResponseData[schemas.StrategyV2ConfigData],
    status_code=status.HTTP_200_OK,
    summary="Generate strategy JSON from text description",
    dependencies=[Depends(require_permission("use_ai_assistant"))],
)
async def generate_strategy_from_text_endpoint(
    request: schemas.GenerateStrategyRequest,
    current_user: models.User = Depends(get_current_user),
):
    """
    Accepts text strategy description, processes it using Gemini
    and returns complete strategy JSON structure.
    """
    from ..depthsight_api import (
        _enforce_strategy_plan_restrictions,
        _user_has_pro_tier_access,
    )

    logger.info(f"User '{current_user.username}' generating strategy from text prompt.")
    try:
        generated_json = await ai_assistant.generate_strategy_json_from_prompt(
            request, current_user
        )
        _enforce_strategy_plan_restrictions(generated_json, current_user)
        if is_strategy_kline_only(generated_json) and not _user_has_pro_tier_access(
            current_user
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Generated strategy requires Precision-compatible blocks that are unavailable on your current plan.",
            )
        return {"data": generated_json}
    except ConnectionError as e:
        logger.error(
            f"AI Assistant connection error for user '{current_user.username}': {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        )
    except ValueError as e:
        logger.warning(
            f"AI Assistant validation/parsing error for user '{current_user.username}': {e}"
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(
            f"Unexpected error in AI Assistant endpoint for user '{current_user.username}': {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while generating the strategy.",
        )


@strategies_router.post(
    "/config",
    response_model=schemas.ApiResponseData[schemas.StrategyConfig],
    status_code=status.HTTP_201_CREATED,
)
async def save_strategy_configuration(
    strategy_create: schemas.StrategyConfigCreate,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Saves new strategy configuration to DB.
    """
    from ..depthsight_api import (
        _coerce_strategy_config_dict,
        _enforce_strategy_plan_restrictions,
    )

    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) saving new strategy config: {strategy_create.name}"
    )
    config_data = _coerce_strategy_config_dict(strategy_create.config_data, "new")
    _enforce_strategy_plan_restrictions(config_data, current_user)
    db_config = await crud.create_strategy_config(
        db=db, user_id=current_user.id, config_create=strategy_create
    )

    # Grant 'first_save' achievement
    user_configs = await crud.get_strategy_configs_by_user(db, user_id=current_user.id)
    if len(user_configs) == 1:
        await grant_achievement(db, current_user.id, "first_save")

    await db.commit()
    await db.refresh(db_config)
    logger.info(
        f"User '{current_user.username}' saved config '{db_config.name}' with ID {db_config.id}"
    )
    return {"data": db_config}


@strategies_router.get(
    "/config/{config_id}",
    response_model=schemas.ApiResponseData[schemas.StrategyConfig],
)
async def get_saved_strategy_configuration(
    config_id: str,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns details of ONE saved configuration from DB.
    """
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) requesting config details from DB for ID: {config_id}"
    )
    db_config = await crud.get_strategy_config(
        db, user_id=current_user.id, config_id=config_id
    )
    if not db_config:
        logger.warning(
            f"User '{current_user.username}' (ID: {current_user.id}) - Config not found in DB: {config_id}"
        )
        raise HTTPException(
            status_code=404, detail="Strategy configuration not found in database"
        )
    return {"data": db_config}


@strategies_router.put(
    "/config/{config_id}",
    response_model=schemas.ApiResponseData[schemas.StrategyConfig],
)
async def update_saved_strategy_configuration(
    config_id: str,
    strategy_update: schemas.StrategyConfigUpdate,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Updates existing strategy configuration in DB.
    """
    from ..depthsight_api import (
        _coerce_strategy_config_dict,
        _enforce_strategy_plan_restrictions,
        count_blocks,
    )

    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) updating config: {config_id}"
    )
    if strategy_update.config_data is not None:
        config_data = _coerce_strategy_config_dict(
            strategy_update.config_data, config_id
        )
        _enforce_strategy_plan_restrictions(config_data, current_user)
    updated_config = await crud.update_strategy_config(
        db, user_id=current_user.id, config_id=config_id, config_update=strategy_update
    )
    if not updated_config:
        raise HTTPException(status_code=404, detail="Strategy configuration not found")

    # Grant achievement for creating a strategy with 5+ blocks
    if strategy_update.config_data and count_blocks(strategy_update.config_data) >= 5:
        await grant_achievement(db, current_user.id, "strategy_5_blocks")

    await db.commit()
    await db.refresh(updated_config)
    return {"data": updated_config}


@strategies_router.delete("/config/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_strategy_configuration(
    config_id: str,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Deletes saved strategy configuration from DB.
    IMPORTANT: Forbids deletion if a strategy with this config is active.
    """
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) attempting to delete config: {config_id}"
    )

    # 1. Check if strategy is running
    try:
        # Use user-specific key to isolate data between users
        user_strategies_key = (
            f"{bot_config.REDIS_STATE_KEY_STRATEGIES}:{current_user.id}"
        )
        strategies_json = await redis_client.get(user_strategies_key)
        if strategies_json:
            running_strategies = json.loads(strategies_json)
            for strategy in running_strategies:
                # IMPORTANT: Running strategy ID in Redis is the config_id
                if strategy.get("id") == config_id:
                    logger.warning(
                        f"User '{current_user.username}' cannot delete config {config_id} because it is currently running."
                    )
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Cannot delete a strategy configuration that is currently running. Please stop the strategy first.",
                    )
    except Exception as e:
        logger.error(
            f"Error checking running strategies in Redis for user {current_user.id}: {e}",
            exc_info=True,
        )
        # Do not block deletion if Redis is unavailable, but log the error
        pass

    # 2. Deletion from DB
    deleted_config = await crud.delete_strategy_config(
        db, user_id=current_user.id, config_id=config_id
    )
    if not deleted_config:
        raise HTTPException(status_code=404, detail="Strategy configuration not found")

    await db.commit()
    logger.info(
        f"User '{current_user.username}' successfully deleted config {config_id}."
    )
    return None


@strategies_router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=schemas.ApiResponseData,
)
async def start_strategy_instance(
    request: schemas.StrategyStartRequest,
    redis_client: redis.Redis = Depends(get_redis_client),
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Starts an instance of a saved strategy configuration by sending a command to the bot.
    This endpoint now handles both 'live' and 'paper' modes uniformly.
    """
    from ..depthsight_api import (
        _enforce_live_strategy_limit,
        _check_intracandle_trigger_permission,
        _coerce_strategy_config_dict,
        _enforce_strategy_plan_restrictions,
    )
    from ..plans import plans_config

    config_id = request.config_id
    mode = request.mode
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) requested to run strategy config ID: {config_id} in mode: {mode}"
    )

    # 1. Find the configuration in the DB
    config_to_run = await crud.get_strategy_config(
        db, user_id=current_user.id, config_id=config_id
    )
    if not config_to_run:
        raise HTTPException(
            status_code=404,
            detail="Strategy configuration not found or you don't have permission.",
        )

    if request.api_key_id is not None:
        api_key = await crud.get_api_key_by_id(db, current_user.id, request.api_key_id)
        if not api_key:
            raise HTTPException(
                status_code=404,
                detail="API key not found or you don't have permission.",
            )
    else:
        if mode == "live":
            raise HTTPException(
                status_code=400, detail="API key must be specified for live trading."
            )
        active_keys = await crud.get_active_api_keys_for_user(db, current_user.id)
        if not active_keys:
            raise HTTPException(
                status_code=400,
                detail="You need at least one active API key to run paper trading.",
            )
        request.api_key_id = active_keys[0].id
        api_key = active_keys[0]

    # --- Live/Paper Trading Permission Checks ---
    user_plan = plans_config.get_plan(current_user.plan)
    limits = user_plan.get("limits", {})
    if "allow_real_trading" not in user_plan.get("permissions", []):
        allow_free_bybit = limits.get("allow_free_bybit_trading", False)
        if allow_free_bybit:
            # Check if the API key being used is Bybit
            if not api_key or api_key.exchange.lower() != "bybit":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Trading on your plan is only allowed using Bybit API keys.",
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your current plan ({current_user.plan}) does not allow trading.",
            )

    await _enforce_live_strategy_limit(
        user=current_user,
        request=request,
        db=db,
        redis_client=redis_client,
    )

    # 2. Determine launch overrides
    symbol_selection_mode = (
        request.symbol_selection_mode
        if request.symbol_selection_mode
        else config_to_run.symbol_selection_mode
    )
    symbols = request.symbols if request.symbols is not None else config_to_run.symbols

    # 3. Perform permission checks (symbol list restrictions only apply to backtests)
    pass

    _check_intracandle_trigger_permission(current_user, config_to_run.config_data)

    # 4. Prepare the command payload, now unified for both 'live' and 'paper' modes.

    config_data_dict = _coerce_strategy_config_dict(
        config_to_run.config_data, config_id
    )

    # --- Apply Dynamic Overrides from Request ---
    if request.params:
        logger.info(
            f"Applying override params for strategy run {config_id} (User: {current_user.id}): {request.params}"
        )
        # We perform a shallow update. For deep merges, a more complex utility would be needed,
        # but typically params overrides specific top-level keys like 'natr_settings'.
        config_data_dict.update(request.params)

    _enforce_strategy_plan_restrictions(config_data_dict, current_user)

    # The controller expects a payload with all necessary details.
    # The 'id' field from the payload is used as the unique instance ID.
    payload = {
        "user_id": current_user.id,
        "id": config_id,  # Use 'id' for the instance identifier
        "config_id": config_id,  # Also include config_id for clarity
        "mode": mode,
        "symbol_selection_mode": symbol_selection_mode,
        "symbols": symbols,
        "config_data": config_data_dict,
        # Pass the rest of the config attributes
        "name": config_to_run.name,
        "description": config_to_run.description,
        "use_ml_confirmation": config_to_run.use_ml_confirmation,
        "foundation_weights": config_to_run.foundation_weights,
        "api_key_id": request.api_key_id,  # Multi-account support
    }

    command = {"command": "START_STRATEGY", "payload": payload}

    # 5. Publish the command to Redis
    try:
        await redis_client.publish(
            bot_config.REDIS_COMMAND_CHANNEL, json.dumps(command)
        )
        logger.info(
            f"START_STRATEGY command published for config_id {config_id} in mode {mode}."
        )
    except Exception as e:
        logger.error(
            f"Failed to publish START_STRATEGY for config {config_id}. Error: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=503, detail="Failed to send start strategy command to the bot."
        )

    return {
        "data": {
            "message": f"START_STRATEGY command sent for config {config_id}.",
            "mode": mode,
        }
    }


@strategies_router.delete(
    "/{instance_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=schemas.ApiResponseData,
)
async def stop_strategy_instance(
    instance_id: str,
    redis_client: redis.Redis = Depends(get_redis_client),
    current_user: models.User = Depends(get_current_user),
):
    """
    Stops running strategy instance by sending command to the bot.
    """
    from ..plans import plans_config

    # Enforce stop strategy permission
    user_plan = plans_config.get_plan(current_user.plan)
    if "allow_real_trading" not in user_plan.get("permissions", []):
        limits = user_plan.get("limits", {})
        if not limits.get("allow_free_bybit_trading", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your current plan ({current_user.plan}) does not allow stopping strategies.",
            )

    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) requested to stop strategy instance ID: {instance_id}."
    )

    command = {
        "command": "STOP_STRATEGY",
        "payload": {"strategy_id": instance_id, "user_id": current_user.id},
    }
    try:
        await redis_client.publish(REDIS_COMMAND_CHANNEL, json.dumps(command))
        logger.info(f"STOP_STRATEGY command published for instance {instance_id}.")
    except Exception as e:
        logger.error(
            f"Failed to publish STOP_STRATEGY for instance {instance_id}. Error: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=503, detail="Failed to send stop strategy command to the bot."
        )

    return {
        "data": {"message": f"STOP_STRATEGY command sent for strategy {instance_id}."}
    }


# ==============================================================================
# EVOLUTION TREE ENDPOINTS
# ==============================================================================


@strategies_router.get(
    "/lineages",
    response_model=schemas.ApiResponseData[List[schemas.RootStrategy]],
)
async def get_strategy_lineages(
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all root strategies (lineage origins) for the current user.
    These are strategies without parent_strategy_id.
    """
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) listing strategy lineages."
    )

    root_strategies = await crud.get_root_strategies(db, user_id=current_user.id)

    # Convert to response format
    response_data = []
    for strategy in root_strategies:
        response_data.append(
            schemas.RootStrategy(
                id=strategy.id,
                name=strategy.name,
                generation=strategy.generation,
                created_at=strategy.created_at,
                descendants_count=len(strategy.children) if strategy.children else 0,
            )
        )

    return {"data": response_data}


@strategies_router.get(
    "/lineage/{strategy_id}",
    response_model=schemas.ApiResponseData[schemas.StrategyLineageResponse],
)
async def get_strategy_lineage(
    strategy_id: str,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the complete evolution tree (ancestors + descendants) for a specific strategy.
    Returns nodes and edges for visualization with react-flow or similar libraries.
    """
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) requesting lineage for strategy {strategy_id}."
    )

    lineage_data = await crud.get_strategy_lineage(
        db, user_id=current_user.id, strategy_id=strategy_id
    )

    if not lineage_data:
        raise HTTPException(
            status_code=404, detail="Strategy not found or you don't have permission."
        )

    return {"data": lineage_data}


@strategies_router.post(
    "/breed",
    response_model=schemas.ApiResponseData[schemas.StrategyBreedResponse],
)
async def breed_strategies(
    breed_request: schemas.StrategyBreedRequest,
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Breed (combine) two strategies to create a hybrid offspring.

    Breeding modes:
    - entry_a_exit_b: Entry logic from A, exit management from B
    - entry_b_exit_a: Entry logic from B, exit management from A
    - filters_a_entry_b: Filters from A, entry/exit from B
    - filters_b_entry_a: Filters from B, entry/exit from A
    - balanced_merge: Merge all components from both parents
    - best_of_both: Intelligently select best components from each

    Returns a new strategy configuration ready to be saved or backtested.
    """
    from ..strategy_breeder import StrategyBreeder

    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) breeding strategies {breed_request.parent_a_id} × {breed_request.parent_b_id} (mode: {breed_request.mode})"
    )

    # Get parent strategies
    parent_a = await crud.get_strategy_config(
        db, user_id=current_user.id, config_id=breed_request.parent_a_id
    )
    parent_b = await crud.get_strategy_config(
        db, user_id=current_user.id, config_id=breed_request.parent_b_id
    )

    if not parent_a:
        raise HTTPException(
            status_code=404,
            detail=f"Parent strategy A (ID: {breed_request.parent_a_id}) not found",
        )
    if not parent_b:
        raise HTTPException(
            status_code=404,
            detail=f"Parent strategy B (ID: {breed_request.parent_b_id}) not found",
        )

    # Breed the strategies
    try:
        hybrid_config = StrategyBreeder.breed_strategies(
            parent_a_config=parent_a.config_data
            if isinstance(parent_a.config_data, dict)
            else json.loads(parent_a.config_data),
            parent_b_config=parent_b.config_data
            if isinstance(parent_b.config_data, dict)
            else json.loads(parent_b.config_data),
            mode=breed_request.mode,
            mutation_rate=breed_request.mutation_rate,
        )

        # Validate the hybrid config
        validated_config = schemas.StrategyV2ConfigData(**hybrid_config)

        response = schemas.StrategyBreedResponse(
            hybrid_config=validated_config,
            parent_a_name=parent_a.name,
            parent_b_name=parent_b.name,
            mode=breed_request.mode,
            suggested_name=hybrid_config.get(
                "name", f"Hybrid: {parent_a.name} × {parent_b.name}"
            ),
        )

        logger.info(
            f"Successfully bred strategies for user {current_user.id}. Hybrid: {response.suggested_name}"
        )
        return {"data": response}

    except Exception as e:
        logger.error(
            f"Failed to breed strategies for user {current_user.id}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to breed strategies: {str(e)}"
        )
