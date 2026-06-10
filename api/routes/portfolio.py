import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

import json
import asyncio
import aiohttp
import api.depthsight_api as depthsight_api
from typing import List, Tuple, Optional, Literal
from datetime import datetime, timezone, timedelta, date
from sqlalchemy import select, func

from .. import models, schemas, security
from ..auth import get_current_user
from ..database import get_db
from ..redis_client import get_redis_client
from ..session_manager import HttpSessDep
from ..plans import plans_config

from ..dependencies import (
    require_permission,
    check_concurrent_task_limit,
    increment_concurrent_task_counter,
)
from tasks import run_portfolio_backtest_task


class ModuleProxy:
    def __init__(self, getattr_fn):
        self._getattr_fn = getattr_fn

    def __getattr__(self, name):
        return getattr(self._getattr_fn(), name)


crud = ModuleProxy(lambda: depthsight_api.crud)


MARKET_TYPE_ALL = "all"
MARKET_TYPE_FUTURES = "futures_usdtm"

try:
    from bot_module import config as bot_config
except ImportError:

    class MockConfig:
        REDIS_COMMAND_CHANNEL = "depthsight:commands"
        REDIS_STATE_KEY_PORTFOLIO = "depthsight:state:portfolio"
        REDIS_STATE_KEY_POSITIONS = "depthsight:state:positions"

    bot_config = MockConfig()

REDIS_COMMAND_CHANNEL = getattr(
    bot_config, "REDIS_COMMAND_CHANNEL", "depthsight:commands"
)
REDIS_STATE_KEY_PORTFOLIO = getattr(
    bot_config, "REDIS_STATE_KEY_PORTFOLIO", "depthsight:state:portfolio"
)
REDIS_STATE_KEY_POSITIONS = getattr(
    bot_config, "REDIS_STATE_KEY_POSITIONS", "depthsight:state:positions"
)

if not hasattr(bot_config, "REDIS_STATE_KEY_PORTFOLIO"):
    bot_config.REDIS_STATE_KEY_PORTFOLIO = REDIS_STATE_KEY_PORTFOLIO
if not hasattr(bot_config, "REDIS_STATE_KEY_POSITIONS"):
    bot_config.REDIS_STATE_KEY_POSITIONS = REDIS_STATE_KEY_POSITIONS

logger = logging.getLogger(__name__)

portfolio_router = APIRouter(
    prefix="/api/v1",
    tags=["Portfolio"],
    dependencies=[Depends(get_current_user)],
)


@portfolio_router.get(
    "/portfolio/equity",
    response_model=schemas.ApiResponseData[List[Tuple[int, float]]],
    summary="Get portfolio equity curve for a given period",
)
async def get_portfolio_equity(
    period: Literal["1d", "7d", "mtd"] = Query(
        "1d", description="Period for the equity curve"
    ),
    mode: Literal["live", "paper"] = Query(
        "paper", description="Trading mode for the equity data"
    ),
    current_user: models.User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Fetches the portfolio equity data points (timestamp_ms, balance) for the specified period and mode.
    Data is retrieved from a Redis Sorted Set.
    """
    now = datetime.now(timezone.utc)
    start_time = None

    if period == "1d":
        start_time = now - timedelta(days=1)
    elif period == "7d":
        start_time = now - timedelta(days=7)
    elif period == "mtd":
        start_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    start_timestamp_ms = int(start_time.timestamp() * 1000)
    end_timestamp_ms = int(now.timestamp() * 1000)

    redis_key = f"equity_history:{mode}:{current_user.id}"

    try:
        equity_data = await redis_client.zrangebyscore(
            redis_key, min=start_timestamp_ms, max=end_timestamp_ms, withscores=True
        )

        result = [(int(score), float(value)) for value, score in equity_data]

        # Replace 'count=1' with 'num=1'
        prev_point_data = await redis_client.zrevrangebyscore(
            redis_key,
            max=start_timestamp_ms - 1,
            min="-inf",
            withscores=True,
            start=0,
            num=1,
        )
        if prev_point_data:
            prev_value, prev_score = prev_point_data[0]
            result.insert(0, (int(prev_score), float(prev_value)))

        return {"data": result}
    except Exception as e:
        logger.error(
            f"Failed to retrieve equity curve for user {current_user.id} (mode: {mode}): {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Could not retrieve equity history."
        )


@portfolio_router.get(
    "/portfolio",
    response_model=schemas.ApiResponseData[schemas.PortfolioStatus],
    summary="Get portfolio state",
)
async def get_portfolio_status(
    redis_client: redis.Redis = Depends(get_redis_client),
    current_user: models.User = Depends(get_current_user),
    http_session: aiohttp.ClientSession = HttpSessDep,
    db: AsyncSession = Depends(get_db),
    mode: str = Query("live", enum=["live", "paper"]),
    api_key_id: Optional[int] = Query(
        None, description="Optional API key ID for multi-account support"
    ),
    market_type: str = Query(
        MARKET_TYPE_ALL,
        description="Market scope: all, futures, futures_usdtm, or spot",
    ),
):
    """
    Fetches the portfolio status for the current user.

    Priority Order:
    1.  Directly from Binance API: Uses the user's configured API key from the database.
    2.  Redis Cache Fallback: If the Binance API call fails or no key is configured, it falls back to Redis.
    """
    from ..depthsight_api import (
        normalize_market_type_filter,
        market_types_for_filter,
        fetch_api_key_market_balance,
        build_market_balance_breakdown,
    )

    normalized_market_type = normalize_market_type_filter(market_type)
    requested_market_types = market_types_for_filter(normalized_market_type)
    logger.info(
        "User '%s' (ID: %s) requested portfolio status. Mode: %s, KeyID: %s, Market: %s",
        current_user.username,
        current_user.id,
        mode,
        api_key_id,
        normalized_market_type,
    )

    if mode == "paper":
        logger.info(
            f"User '{current_user.username}' requesting paper portfolio status."
        )
        wallet_assets = await crud.get_paper_wallet(db, user_id=current_user.id)
        if not wallet_assets:
            wallet_assets = await crud.init_or_reset_paper_wallet(
                db, user_id=current_user.id
            )
            await db.commit()

        total_balance = 0.0
        for asset in wallet_assets:
            if asset.asset == "USDT":
                total_balance += asset.balance

        # Calculate today's PnL from completed trades
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_pnl_result = await db.execute(
            select(func.sum(models.Trade.pnl - models.Trade.commission)).where(
                models.Trade.user_id == current_user.id,
                models.Trade.trade_mode == "PAPER",
                models.Trade.timestamp_close >= today_start,
            )
        )
        today_pnl = today_pnl_result.scalar() or 0.0

        paper_portfolio_status = schemas.PortfolioStatus(
            balance=total_balance,
            today_pnl=today_pnl,  # Real PnL for today
            is_trading_allowed=True,
            consecutive_losses=0,  # Not tracked yet
            timestamp_utc=datetime.now(timezone.utc),
        )
        return {"data": paper_portfolio_status}

    # --- 1. PRIORITY: Request to Binance via user's key ---
    try:
        if api_key_id:
            # --- Single Account Mode ---
            active_key = await crud.get_api_key_by_id(
                db, user_id=current_user.id, key_id=api_key_id
            )

            # Security check: ensure key belongs to user
            if active_key and active_key.user_id != current_user.id:
                raise ValueError("API Key does not belong to user")

            # Ensure key is active and valid
            if active_key and (
                not active_key.is_active or active_key.status != "valid"
            ):
                raise ValueError("Selected API Key is not active or valid")

            if not active_key:
                raise ValueError("Selected API Key not found.")

            api_key = security.decrypt_data(active_key.encrypted_api_key)
            api_secret = security.decrypt_data(active_key.encrypted_api_secret)
            if not api_key or not api_secret:
                raise ValueError("Failed to decrypt API keys.")
            balance_results = await asyncio.gather(
                *[
                    fetch_api_key_market_balance(
                        key_obj=active_key,
                        http_session=http_session,
                        market_type=market,
                    )
                    for market in requested_market_types
                ],
                return_exceptions=True,
            )
            account_balances = [
                result
                for result in balance_results
                if isinstance(result, schemas.AccountBalance)
            ]
            if not account_balances:
                first_error = next(
                    (
                        result
                        for result in balance_results
                        if isinstance(result, Exception)
                    ),
                    None,
                )
                raise ValueError(f"Failed to fetch account balance: {first_error}")
            total_equity = sum(account.total_equity for account in account_balances)

        else:
            # --- All Accounts Mode (Aggregation) ---
            active_keys = await crud.get_active_api_keys_for_user(
                db, user_id=current_user.id
            )

            if not active_keys:
                raise ValueError("User has no active API keys configured.")

            async def fetch_account_data(key_model, market: str):
                try:
                    return await fetch_api_key_market_balance(
                        key_obj=key_model,
                        http_session=http_session,
                        market_type=market,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to fetch %s balance for key %s: %s",
                        market,
                        key_model.id,
                        e,
                    )
                    return None

            # Parallel fetch
            tasks = [
                fetch_account_data(k, market)
                for k in active_keys
                for market in requested_market_types
            ]
            results = await asyncio.gather(*tasks)
            account_balances = [
                result
                for result in results
                if isinstance(result, schemas.AccountBalance)
            ]
            total_equity = sum(account.total_equity for account in account_balances)

        # Calculate today's PnL from completed trades (LIVE mode)
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        pnl_query = select(func.sum(models.Trade.pnl - models.Trade.commission)).where(
            models.Trade.user_id == current_user.id,
            models.Trade.trade_mode == "LIVE",
            models.Trade.timestamp_close >= today_start,
        )

        # If a specific API key is selected, filter PnL by it
        if api_key_id:
            pnl_query = pnl_query.where(models.Trade.api_key_id == api_key_id)

        today_pnl_result = await db.execute(pnl_query)
        today_pnl_live = today_pnl_result.scalar() or 0.0

        # Construct a PortfolioStatus object from the live data.
        market_breakdown = build_market_balance_breakdown(account_balances)
        live_portfolio_status = schemas.PortfolioStatus(
            balance=total_equity,  # Use Equity for dashboard "Balance"
            today_pnl=today_pnl_live,
            is_trading_allowed=True,
            consecutive_losses=0,
            timestamp_utc=datetime.now(timezone.utc),
            market_type=normalized_market_type,
            total_available=sum(
                account.available_balance for account in account_balances
            ),
            total_unrealized_pnl=sum(
                account.unrealized_pnl for account in account_balances
            ),
            total_margin_used=sum(account.margin_used for account in account_balances),
            market_breakdown=market_breakdown,
        )
        logger.info(
            f"Successfully fetched live portfolio status from Binance for user '{current_user.username}'."
        )
        return {"data": live_portfolio_status}

    except Exception as e:
        logger.warning(
            f"Could not fetch live portfolio status for user '{current_user.username}': {e}. Falling back to Redis cache.",
            exc_info=True,
        )

    # --- 2. FALLBACK: Read from Redis ---
    try:
        # New structure: prefix:user_id:api_key_id
        base_portfolio_key = f"{bot_config.REDIS_STATE_KEY_PORTFOLIO}:{current_user.id}"

        aggregated_status = {
            "total_wallet_balance": 0.0,
            "total_unrealized_pnl": 0.0,
            "total_equity": 0.0,
            "today_pnl": 0.0,
        }

        found_data = False

        if api_key_id is not None:
            # Specific Key
            specific_key = f"{base_portfolio_key}:{api_key_id}"
            port_json = await redis_client.get(specific_key)
            if port_json:
                data = json.loads(port_json)
                aggregated_status = data
                found_data = True
        else:
            # Aggregate All
            pattern = f"{base_portfolio_key}:*"
            keys = await redis_client.keys(pattern)
            if keys:
                values = await redis_client.mget(keys)
                for v in values:
                    if v:
                        data = json.loads(v)
                        aggregated_status["total_wallet_balance"] += float(
                            data.get("total_wallet_balance", 0)
                        )
                        aggregated_status["total_unrealized_pnl"] += float(
                            data.get("total_unrealized_pnl", 0)
                        )
                        aggregated_status["total_equity"] += float(
                            data.get("total_equity", 0)
                        )
                        aggregated_status["today_pnl"] += float(
                            data.get("today_pnl", 0)
                        )
                        found_data = True
        if not found_data:
            raise ValueError(
                f"Portfolio keys associated with '{base_portfolio_key}' not found in Redis."
            )

        # Map to Schema
        # IMPORTANT: Frontend uses balance field as "Total Equity" to show total balance.
        # Therefore, we map total_equity to balance here if available.
        portfolio_data = schemas.PortfolioStatus(
            balance=aggregated_status.get(
                "total_equity", aggregated_status.get("total_wallet_balance", 0.0)
            ),
            today_pnl=aggregated_status.get("today_pnl", 0.0),
            is_trading_allowed=aggregated_status.get("is_trading_allowed", True),
            consecutive_losses=aggregated_status.get("consecutive_losses", 0),
            timestamp_utc=datetime.now(timezone.utc),
        )
        logger.info(
            f"Returning cached portfolio status for user '{current_user.username}'."
        )
        return {"data": portfolio_data}

    except Exception as e:
        logger.warning(
            f"Could not retrieve or parse portfolio status from Redis for user '{current_user.username}': {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio state not found in cache. Bot might not be running or publishing its state for your account yet.",
        )


@portfolio_router.delete(
    "/portfolio/positions",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=schemas.ApiResponseData,
    summary="Emergency Stop! Close all positions.",
)
async def emergency_stop(
    redis_client: redis.Redis = Depends(get_redis_client),
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ..depthsight_api import grant_achievement

    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) initiated EMERGENCY STOP."
    )
    # --- Cast user_id to string for consistency ---
    command = {
        "type": "EMERGENCY_STOP",
        "payload": {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "user_id": str(current_user.id),  # Add user_id to payload as a string
        },
    }
    try:
        await redis_client.publish(REDIS_COMMAND_CHANNEL, json.dumps(command))
        logger.info(
            f"EMERGENCY_STOP command sent to the bot by user '{current_user.username}' (ID: {current_user.id})."
        )
        # Grant 'pulling_the_plug' achievement
        await grant_achievement(db, current_user.id, "pulling_the_plug")
    except redis.exceptions.ConnectionError as e:
        logger.error(
            f"Could not send EMERGENCY_STOP command to Redis for user '{current_user.username}' (ID: {current_user.id}): {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not send command to Redis: {e}",
        )
    return {"data": {"message": "EMERGENCY_STOP command has been sent to the bot."}}


@portfolio_router.post(
    "/portfolio-backtests",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=schemas.ApiResponse,
    dependencies=[
        Depends(require_permission("run_portfolio_backtest")),
        Depends(check_concurrent_task_limit("run_portfolio_backtest")),
    ],
)
async def run_portfolio_backtest_endpoint(
    request: schemas.PortfolioBacktestRunRequest,
    current_user: models.User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    from ..depthsight_api import (
        _check_symbol_permissions,
        _check_intracandle_trigger_permission,
    )

    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) submitting portfolio backtest: {request.name or 'Unnamed Portfolio Backtest'}"
    )

    symbols_to_check = [c.symbol for c in request.contracts]
    await _check_symbol_permissions(current_user, symbols_to_check)

    for contract in request.contracts:
        if contract.params and "config_data" in contract.params:
            _check_intracandle_trigger_permission(
                current_user, contract.params["config_data"]
            )

    user_plan = plans_config.get_plan(current_user.plan)
    limits = user_plan.get("limits", {})

    priority = limits.get("celery_task_priority", 9)

    try:
        celery_task = run_portfolio_backtest_task.apply_async(
            args=[request.model_dump(exclude_none=True), current_user.id],
            priority=priority,
        )
        await increment_concurrent_task_counter(current_user.id, redis_client)
        logger.info(
            f"Portfolio backtest task {celery_task.id} queued for user '{current_user.username}' (ID: {current_user.id}), name: {request.name or 'Unnamed'}, priority: {priority}"
        )
        return {"data": {"task_id": celery_task.id, "status": "pending"}}
    except Exception as e:
        logger.error(
            f"User '{current_user.username}' (ID: {current_user.id}) - Failed to queue portfolio backtest task for {request.name or 'Unnamed'}. Error: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to queue portfolio backtest task: {str(e)}",
        )


@portfolio_router.get(
    "/positions",
    response_model=schemas.ApiResponseData[List[schemas.PositionResponseItem]],
    summary="List all active trading positions",
)
async def list_positions(
    redis_client: redis.Redis = Depends(get_redis_client),
    current_user: models.User = Depends(get_current_user),
    mode: str = Query("live", enum=["live", "paper"]),
    api_key_id: Optional[int] = Query(
        None, description="Filter by specific API key (subaccount)"
    ),
    market_type: str = Query(
        MARKET_TYPE_ALL,
        description="Market scope: all, futures, futures_usdtm, or spot",
    ),
):
    """
    Fetches the list of active trading positions for the current user from Redis cache,
    filtered by the selected trading mode ('live' or 'paper').
    """
    from ..depthsight_api import normalize_market_type_filter

    normalized_market_type = normalize_market_type_filter(market_type)
    logger.info(
        "User '%s' is fetching '%s' positions from Redis. api_key_id=%s market_type=%s",
        current_user.username,
        mode,
        api_key_id,
        normalized_market_type,
    )

    try:
        # Use user-specific key to isolate data between users
        # New key structure: prefix:user_id:api_key_id
        base_positions_key = f"{bot_config.REDIS_STATE_KEY_POSITIONS}:{current_user.id}"

        all_positions = []

        if api_key_id is not None:
            # Fetch for specific account
            specific_key = f"{base_positions_key}:{api_key_id}"
            positions_json = await redis_client.get(specific_key)
            if positions_json:
                all_positions.extend(json.loads(positions_json))
        else:
            # Aggregation: Scan for all keys associated with this user
            # Pattern: positions:user_id:*
            pattern = f"{base_positions_key}:*"
            # Use SCAN or KEYS (KEYS is acceptable here as user key count is low)
            keys = await redis_client.keys(pattern)
            if keys:
                values = await redis_client.mget(keys)
                for v in values:
                    if v:
                        all_positions.extend(json.loads(v))

        if not all_positions:
            logger.info(
                f"Redis positions for '{current_user.username}' empty. Returning no positions."
            )
            return {"data": []}

        # Filter positions for the requested mode (user_id already filtered by key)
        user_mode_positions = [
            p
            for p in all_positions
            if p.get("mode") == mode and str(p.get("user_id")) == str(current_user.id)
        ]

        # --- MULTI-ACCOUNT: Filter by api_key_id if specified ---
        if api_key_id is not None:
            user_mode_positions = [
                p for p in user_mode_positions if p.get("api_key_id") == api_key_id
            ]

        if normalized_market_type != MARKET_TYPE_ALL:
            user_mode_positions = [
                p
                for p in user_mode_positions
                if normalize_market_type_filter(
                    p.get("market_type") or p.get("marketType") or MARKET_TYPE_FUTURES
                )
                == normalized_market_type
            ]

        validated_positions = [
            schemas.PositionResponseItem(**p) for p in user_mode_positions
        ]
        logger.info(
            f"Returning {len(validated_positions)} '{mode}' positions for user '{current_user.username}'."
        )
        return {"data": validated_positions}
    except Exception as e:
        logger.error(
            f"Error fetching or processing positions from Redis for user {current_user.id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Could not retrieve positions from cache."
        )


@portfolio_router.delete(
    "/positions/{symbol}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Close a specific position by market order",
)
async def close_position(
    symbol: str,
    api_key_id: Optional[int] = Query(None, description="Close position for a specific API key (subaccount)"),
    current_user: models.User = Depends(get_current_user),
    http_session: aiohttp.ClientSession = HttpSessDep,
    db: AsyncSession = Depends(get_db),
):
    """
    Closes an active futures position by placing a reduce-only market order
    directly via Binance API. Uses the user's specific API key.
    """
    from ..depthsight_api import create_exchange_executor, grant_achievement

    logger.info(
        f"User '{current_user.username}' requested to close position for {symbol} (api_key_id={api_key_id})."
    )

    try:
        # Get user-specific API key
        if api_key_id is not None:
            active_key = await crud.get_api_key_by_id(
                db, user_id=current_user.id, key_id=api_key_id
            )
        else:
            active_key = await crud.get_active_api_key_for_user(db, user_id=current_user.id)
        if not active_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no active API key configured to perform this action.",
            )

        # Decrypt keys
        api_key = security.decrypt_data(active_key.encrypted_api_key)
        api_secret = security.decrypt_data(active_key.encrypted_api_secret)
        if not api_key or not api_secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to decrypt API keys.",
            )

        # --- Pass common session to Executor ---
        executor = create_exchange_executor(
            exchange=active_key.exchange,
            api_key=api_key,
            api_secret=api_secret,
            session=http_session,
        )

        positions = await executor.get_open_positions()
        position_to_close = next(
            (p for p in positions if p.get("symbol") == symbol.upper()), None
        )

        if not position_to_close:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No open position found for symbol {symbol}.",
            )

        position_amt = float(position_to_close.get("positionAmt", 0))
        if abs(position_amt) == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Position for {symbol} has zero size.",
            )

        close_side = "SELL" if position_amt > 0 else "BUY"
        quantity_to_close = abs(position_amt)

        logger.info(
            f"Placing market {close_side} order for {quantity_to_close} {symbol} to close position for user '{current_user.username}'."
        )

        close_order_resp = await executor.place_order(
            symbol=symbol.upper(),
            side=close_side,
            order_type="MARKET",
            quantity=quantity_to_close,
            reduceOnly=True,
        )

        if close_order_resp.get("error"):
            logger.error(
                f"Failed to place close order for {symbol} for user '{current_user.username}': {close_order_resp.get('msg')}"
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Binance API error: {close_order_resp.get('msg')}",
            )

        # Cancel all open orders (limit entry, stop-loss, take-profit etc.)
        try:
            logger.info(f"Cancelling all open orders for {symbol} after closing position.")
            cancel_standard_resp = await executor.cancel_all_open_orders(symbol=symbol.upper())
            logger.info(f"Cancel standard orders response: {cancel_standard_resp}")
        except Exception as e:
            logger.error(f"Error cancelling standard orders for {symbol}: {e}", exc_info=True)

        try:
            logger.info(f"Checking for remaining/algo orders to cancel for {symbol}.")
            open_algo_orders = await executor.get_open_algo_orders(symbol=symbol.upper())
            if open_algo_orders:
                logger.info(f"Found {len(open_algo_orders)} open algo/conditional orders. Cancelling them...")
                for order in open_algo_orders:
                    order_id = order.get("orderId") or order.get("id")
                    if order_id:
                        cancel_algo_resp = await executor.cancel_order(
                            symbol=symbol.upper(),
                            orderId=order_id,
                            is_algo_order=True
                        )
                        logger.info(f"Cancelled algo order {order_id}: {cancel_algo_resp}")
        except Exception as e:
            logger.error(f"Error cancelling algo orders for {symbol}: {e}", exc_info=True)

        # Grant 'the_intervention' achievement
        await grant_achievement(db, current_user.id, "the_intervention")

        return {
            "message": f"Close order for {symbol} sent successfully.",
            "details": close_order_resp,
        }

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(
            f"Failed to process close_position for {symbol} for user '{current_user.username}': {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while trying to close the position.",
        )


@portfolio_router.patch(
    "/positions/{position_id}",
    response_model=schemas.ApiResponseData[schemas.PositionData],
    summary="Modify Stop Loss / Take Profit for an open position",
)
async def update_position_sl_tp(
    position_id: str,
    request_body: schemas.UpdatePositionRequest,
    current_user: models.User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
    db: AsyncSession = Depends(get_db),
):
    logger.info(
        f"User '{current_user.username}' (ID: {current_user.id}) attempting to update SL/TP for position {position_id} with data {request_body.model_dump(exclude_unset=True)}"
    )

    if request_body.stop_loss is None and request_body.take_profit is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either stop_loss or take_profit must be provided.",
        )

    # Use user-specific key to isolate data between users
    base_positions_key = f"{REDIS_STATE_KEY_POSITIONS}:{current_user.id}"
    pattern = f"{base_positions_key}:*"
    
    try:
        keys = await redis_client.keys(pattern)
        all_positions_data = []
        if keys:
            values = await redis_client.mget(keys)
            for v in values:
                if v:
                    all_positions_data.extend(json.loads(v))
    except Exception as e:
        logger.error(
            f"User '{current_user.username}' (ID: {current_user.id}) - SL/TP Update: Failed to fetch/parse positions from Redis: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error reading positions data.",
        )

    if not all_positions_data:
        logger.warning(
            f"User '{current_user.username}' (ID: {current_user.id}) - SL/TP Update: Positions list not found in Redis keys for position {position_id}."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Positions data not available.",
        )

    target_position_data = None
    # --- Replace unused variable '_' with 'pos' for clarity ---
    for pos in all_positions_data:
        if pos.get("id") == position_id:
            target_position_data = pos
            break

    if not target_position_data:
        logger.warning(
            f"User '{current_user.username}' (ID: {current_user.id}) - SL/TP Update: Position {position_id} not found in Redis."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Position {position_id} not found.",
        )

    if "user_id" not in target_position_data:
        logger.error(
            f"CRITICAL: 'user_id' missing in position data from Redis for position {position_id}. Cannot authorize SL/TP update for user '{current_user.username}' (ID: {current_user.id})."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Cannot verify position ownership due to missing user ID in position data.",
        )

    if str(target_position_data.get("user_id")) != str(current_user.id):
        logger.warning(
            f"User '{current_user.username}' (ID: {current_user.id}) FORBIDDEN to update SL/TP for position {position_id} owned by user {target_position_data.get('user_id')}."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to modify this position.",
        )

    command_payload = {
        "position_id": position_id,
        "user_id": str(current_user.id),
    }
    if request_body.stop_loss is not None:
        command_payload["new_stop_loss"] = request_body.stop_loss
    if request_body.take_profit is not None:
        command_payload["new_take_profit"] = request_body.take_profit

    command = {"command": "UPDATE_SL_TP", "payload": command_payload}

    try:
        await redis_client.publish(REDIS_COMMAND_CHANNEL, json.dumps(command))
        logger.info(
            f"User '{current_user.username}' (ID: {current_user.id}) - SL/TP Update: UPDATE_SL_TP command sent for position {position_id}. Payload: {command_payload}"
        )
    except redis.exceptions.ConnectionError as e:
        logger.error(
            f"User '{current_user.username}' (ID: {current_user.id}) - SL/TP Update: Failed to publish UPDATE_SL_TP command to Redis for position {position_id}. Error: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to send update command.",
        )

    updated_position_for_response = target_position_data.copy()
    if request_body.stop_loss is not None:
        updated_position_for_response["stop_loss"] = request_body.stop_loss
    if request_body.take_profit is not None:
        updated_position_for_response["take_profit"] = request_body.take_profit

    try:
        if "user_id" in updated_position_for_response and not isinstance(
            updated_position_for_response["user_id"], (int, str, type(None))
        ):
            pass
        validated_response_pos = schemas.PositionData(**updated_position_for_response)
    except Exception as e:
        logger.error(
            f"User '{current_user.username}' (ID: {current_user.id}) - SL/TP Update: Failed to validate position data for response for position {position_id}. Error: {e}. Data: {updated_position_for_response}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error preparing response data after SL/TP update.",
        )

    return {"data": validated_response_pos}


@portfolio_router.get("/trades", summary="Get trade history with pagination")
async def get_trades_history(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    run_id: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=10000),
    symbol: Optional[str] = Query(None),
    strategy: Optional[str] = Query(
        None, alias="strategy_config_id"
    ),  # Use alias for clarity
    mode: str = Query("live", enum=["live", "paper"]),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    api_key_id: Optional[int] = Query(
        None, description="Filter by specific API key (subaccount)"
    ),
):
    if run_id:
        logger.info(
            f"User '{current_user.username}' requested backtest trade history for run {run_id}."
        )
        backtest_run = await crud.get_backtest_run_by_any_id(
            db, user_id=current_user.id, identity=run_id
        )
        if not backtest_run:
            raise HTTPException(status_code=404, detail="Backtest run not found")

        trades, total_count = await crud.get_trades_with_count_by_run_id(
            db, user_id=current_user.id, run_id=run_id, skip=skip, limit=limit
        )
        for trade in trades:
            trade.symbol = backtest_run.symbol
            trade.strategy_name = backtest_run.strategy_name

        return {"data": {"total": total_count, "trades": trades}}

    else:
        logger.info(
            f"User '{current_user.username}' requested trade history with filters: mode={mode}, symbol={symbol}, strategy={strategy}, date_from={date_from}, date_to={date_to}, api_key_id={api_key_id}"
        )
        start_date_obj: Optional[date] = None
        end_date_obj: Optional[date] = None

        try:
            if date_from:
                # Handle full ISO datetime string (e.g. 2024-01-01T00:00:00.000Z) by taking only the date part
                if "T" in date_from:
                    date_from = date_from.split("T")[0]
                start_date_obj = date.fromisoformat(date_from)
            if date_to:
                if "T" in date_to:
                    date_to = date_to.split("T")[0]
                # Include the entire day until the end
                end_date_obj = date.fromisoformat(date_to)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid date format. Please use YYYY-MM-DD. Error: {e}",
            )

        trades, total_count = await crud.get_trades_with_count(
            db,
            user_id=current_user.id,
            skip=skip,
            limit=limit,
            symbol=symbol,
            strategy_config_id=strategy,
            trade_mode=mode.upper(),  # CRUD expects UPPERCASE
            start_date=start_date_obj,
            end_date=end_date_obj,
            api_key_id=api_key_id,
        )
        # crud.get_trades_with_count returns SQLAlchemy models, they need validation
        validated_trades = [schemas.Trade.model_validate(t) for t in trades]
        return {"data": {"total": total_count, "trades": validated_trades}}


@portfolio_router.get(
    "/portfolio-backtests",
    response_model=schemas.ApiResponseData[List[schemas.PortfolioBacktestRunListItem]],
)
async def list_portfolio_backtests(
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieves list of all portfolio backtest runs for current user.
    """
    logger.info(f"User {current_user.id} listing portfolio backtest runs.")

    # We only need tasks list, ignore total count.
    all_tasks, _ = await crud.get_tasks_by_user(
        db, user_id=current_user.id, limit=1000
    )  # Load up to 1000 tasks for filtering

    portfolio_tasks = [
        task for task in all_tasks if task.task_type == "portfolio_backtest"
    ]

    response_items = []
    for task in portfolio_tasks:
        pnl = None
        sharpe = None
        if (
            task.status == "COMPLETED"
            and task.results
            and isinstance(task.results, dict)
        ):
            kpis = task.results.get("portfolio_kpis")
            if kpis and isinstance(kpis, dict):
                pnl = kpis.get("net_pnl_total")
                sharpe = kpis.get("sharpe_ratio_simplified")

        item = schemas.PortfolioBacktestRunListItem(
            id=task.task_id,
            name=task.parameters.get("name", "Unnamed Portfolio Run"),
            status=task.status.upper(),
            created_at=task.submitted_at,
            completed_at=task.completed_at,
            pnl=pnl,
            sharpe_ratio=sharpe,
        )
        response_items.append(item)

    return {"data": response_items}
