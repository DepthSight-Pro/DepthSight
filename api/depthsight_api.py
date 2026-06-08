# api/depthsight_api.py

import os
import uuid
from datetime import datetime, timezone, timedelta
import secrets
from typing import Any, Dict, Optional, List
import json
import logging
import traceback
from pathlib import Path
import asyncio
import aiohttp
import numpy as np
from celery.result import AsyncResult  # noqa: F401
from .gamification import grant_achievement  # noqa: F401

from tasks import (  # noqa: F401
    generate_dataset_task,
    train_model_task,
    run_backtest_task,
    run_portfolio_backtest_task,
    run_optimization_task,
    run_genetic_search_task,
)
from .live_runtime import (
    build_deactivate_api_key_command,
    build_initialize_user_controller_command,
    count_new_strategy_instances,
    get_active_api_key_ids,
    get_max_live_strategies,
    load_user_running_strategies,
    plan_allows_live_trading,
)

try:
    import uvicorn

    UVICORN_INSTALLED_API_DEPTHSIGHT = True
except ModuleNotFoundError:
    UVICORN_INSTALLED_API_DEPTHSIGHT = False
    uvicorn = (
        None  # Placeholder to prevent NameError if uvicorn.run is called conditionally
    )

try:
    from fastapi import (
        FastAPI,
        HTTPException,
        status,
        Depends,
        APIRouter,
        Query,
        Request,
    )
    from contextlib import asynccontextmanager
    from .session_manager import session_manager
    from fastapi.responses import JSONResponse, Response
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.security import OAuth2PasswordRequestForm

    FASTAPI_INSTALLED_API = True
except ModuleNotFoundError:
    # Define mock classes for FastAPI components
    class MockFastAPIComponent:
        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, *args, **kwargs):
            if args and callable(args[0]):  # Decorator usage
                return args[0]
            return self  # Instance usage

        def include_router(self, *args, **kwargs):
            pass

        def add_middleware(self, *args, **kwargs):
            pass

        def exception_handler(self, *args, **kwargs):
            return lambda func: func  # Decorator

    FastAPI = MockFastAPIComponent
    HTTPException = type(
        "HTTPException", (Exception,), {"status_code": 0, "detail": ""}
    )
    status = (
        MockFastAPIComponent()
    )  # Mock status codes if accessed like status.HTTP_404_NOT_FOUND
    Depends = MockFastAPIComponent
    APIRouter = MockFastAPIComponent
    Query = MockFastAPIComponent
    JSONResponse = MockFastAPIComponent
    CORSMiddleware = MockFastAPIComponent
    OAuth2PasswordRequestForm = MockFastAPIComponent
from pydantic import BaseModel
import redis.asyncio as redis

# --- Rate Limiting ---
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession
from . import crud, schemas, models

from bot_module.exchanges import (
    create_exchange_executor as _create_exchange_executor,
    is_binance_exchange,
)
from bot_module.exchanges.binance import BinanceExchangeExecutor as BinanceExecutor

from . import ai_assistant
from .gamification import check_and_grant_retroactive_achievements
from .database import get_db
from .redis_client import get_redis_client
from .auth import get_current_user
from . import security
from .audit_logger import audit_logger, get_client_ip, get_user_agent
from .dependencies import (
    is_strategy_pro_only,
    is_strategy_kline_only,
)

from .plans import plans_config
from .routes.affiliate import affiliate_router
from .routes.ai import create_ai_routers
from .routes.model_lab import create_model_lab_router
from .routes.notifications import notifications_router
from .routes.public import public_router
from .routes.registry import include_application_routers
from .routes.support import admin_support_router, support_router
from .routes.users import users_extra_router
from bot_module import data_loader
from .hft_router import router as hft_router
from .routes.auth import auth_router
from .routes.payments import payments_router
from .routes.webhooks import webhooks_router
from .routes.admin import admin_router
from .routes.discovery import discovery_router
from .routes.account import (  # noqa: F401
    account_router,
    get_account_status,
    get_paper_wallet,
    reset_paper_wallet,
)
from .routes.portfolio import (  # noqa: F401
    portfolio_router,
    get_portfolio_status,
    get_portfolio_equity,
    emergency_stop,
    list_positions,
    close_position,
    update_position_sl_tp,
    get_trades_history,
    list_portfolio_backtests,
    run_portfolio_backtest_endpoint,
)
from .routes.config import (  # noqa: F401
    config_router,
    get_config_endpoint,
    update_config_endpoint,
    add_symbol,
    delete_symbol,
    get_blacklist,
    add_to_blacklist,
    remove_from_blacklist,
    update_auto_blacklist_rules,
    get_block_restrictions,
)
from .routes.diagnostics import (  # noqa: F401
    diagnostics_router,
    get_system_status_endpoint,
    proxy_binance_klines,
    preview_foundation,
    find_available_symbols,
    get_log_history,
)
from .routes.tasks import (  # noqa: F401
    tasks_router,
    get_all_tasks,
    get_task_status_endpoint,
    run_optimization,
    get_optimization_status,
)
from .routes.gamification import (  # noqa: F401
    gamification_router,
    get_leaderboard,
    delete_leaderboard_entry,
    get_achievements,
    get_user_achievements,
    general_exception_handler_custom,
)
from .routes.api_keys import (  # noqa: F401
    api_keys_router,
    add_api_key,
    delete_api_key,
    update_api_key_status_active,
    get_multi_account_balances,
    test_api_key,
)
from .routes.backtests import (  # noqa: F401
    backtests_router,
    get_backtest_klines,
    run_backtest,
    list_backtests,
    get_backtest_details,
    delete_backtest,
    create_shareable_backtest_link,
)
from .routes.strategies import (  # noqa: F401
    strategies_router,
    list_strategies,
    list_saved_strategy_configurations,
    generate_strategy_from_text_endpoint,
    save_strategy_configuration,
    get_saved_strategy_configuration,
    update_saved_strategy_configuration,
    delete_saved_strategy_configuration,
    start_strategy_instance,
    stop_strategy_instance,
    get_strategy_lineages,
    get_strategy_lineage,
    breed_strategies,
)

_BINANCE_ADAPTER_CLASS = BinanceExecutor


def create_exchange_executor(
    exchange: str,
    api_key: str,
    api_secret: str,
    session,
    market_type: Optional[str] = None,
):
    """Create an exchange executor while keeping legacy BinanceExecutor mocks working."""
    if is_binance_exchange(exchange) and BinanceExecutor is not _BINANCE_ADAPTER_CLASS:
        return BinanceExecutor(
            api_key=api_key,
            api_secret=api_secret,
            session=session,
            market_type=market_type or "futures_usdtm",
        )
    return _create_exchange_executor(
        exchange=exchange,
        api_key=api_key,
        api_secret=api_secret,
        session=session,
        market_type=market_type,
    )


MARKET_TYPE_ALL = "all"
MARKET_TYPE_FUTURES = "futures_usdtm"
MARKET_TYPE_SPOT = "spot"
SUPPORTED_BALANCE_MARKETS = (MARKET_TYPE_FUTURES, MARKET_TYPE_SPOT)


def normalize_market_type_filter(raw_market_type: Optional[str]) -> str:
    raw = str(raw_market_type or MARKET_TYPE_ALL).strip().lower()
    if raw in {"", MARKET_TYPE_ALL}:
        return MARKET_TYPE_ALL
    if raw in {"futures", "future", "futures_usdtm", "usdtm", "linear", "swap"}:
        return MARKET_TYPE_FUTURES
    if raw == MARKET_TYPE_SPOT:
        return MARKET_TYPE_SPOT
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="market_type must be one of: all, futures, futures_usdtm, spot",
    )


def market_types_for_filter(raw_market_type: Optional[str]) -> List[str]:
    normalized = normalize_market_type_filter(raw_market_type)
    if normalized == MARKET_TYPE_ALL:
        return list(SUPPORTED_BALANCE_MARKETS)
    return [normalized]


def _balance_float(balance_row: Dict[str, Any], key: str) -> float:
    try:
        return float(balance_row.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _asset_balances_from_exchange_response(
    balances: Optional[Dict[str, Dict[str, Any]]],
) -> List[schemas.AssetBalance]:
    assets: List[schemas.AssetBalance] = []
    for asset, row in (balances or {}).items():
        if not isinstance(row, dict):
            continue
        free = _balance_float(row, "free")
        locked = _balance_float(row, "locked")
        total = free + locked
        if total <= 1e-9:
            continue
        assets.append(
            schemas.AssetBalance(
                asset=str(asset),
                free=free,
                locked=locked,
                total=total,
            )
        )
    return sorted(assets, key=lambda item: (item.asset != "USDT", item.asset))


async def fetch_api_key_market_balance(
    *,
    key_obj: models.ApiKey,
    http_session: aiohttp.ClientSession,
    market_type: str,
) -> schemas.AccountBalance:
    api_key = security.decrypt_data(key_obj.encrypted_api_key)
    api_secret = security.decrypt_data(key_obj.encrypted_api_secret)

    if not api_key or not api_secret:
        raise ValueError("Failed to decrypt credentials")

    executor = create_exchange_executor(
        exchange=key_obj.exchange,
        api_key=api_key,
        api_secret=api_secret,
        session=http_session,
        market_type=market_type,
    )
    try:
        balances = await executor.get_account_balance()
    finally:
        close_method = getattr(executor, "close", None)
        if callable(close_method):
            try:
                await close_method()
            except Exception as exc:
                logger.debug(
                    "Failed to close balance executor for key %s: %s",
                    key_obj.id,
                    exc,
                    exc_info=True,
                )

    assets = _asset_balances_from_exchange_response(balances)
    usdt = (balances or {}).get("USDT", {}) if isinstance(balances, dict) else {}
    free_usdt = _balance_float(usdt, "free")
    locked_usdt = _balance_float(usdt, "locked")
    wallet_balance = free_usdt + locked_usdt
    unrealized_pnl = _balance_float(usdt, "unrealized_pnl")
    total_equity = wallet_balance + unrealized_pnl

    return schemas.AccountBalance(
        api_key_id=key_obj.id,
        api_key_name=key_obj.name,
        exchange=key_obj.exchange,
        market_type=market_type,
        balance=wallet_balance,
        available_balance=free_usdt,
        unrealized_pnl=unrealized_pnl,
        margin_used=locked_usdt if market_type == MARKET_TYPE_FUTURES else 0.0,
        total_equity=total_equity,
        assets=assets,
    )


def build_market_balance_breakdown(
    accounts: List[schemas.AccountBalance],
) -> List[schemas.MarketBalanceSummary]:
    breakdown: List[schemas.MarketBalanceSummary] = []
    for market_type in SUPPORTED_BALANCE_MARKETS:
        market_accounts = [
            account for account in accounts if account.market_type == market_type
        ]
        if not market_accounts:
            continue
        breakdown.append(
            schemas.MarketBalanceSummary(
                market_type=market_type,
                total_balance=sum(account.balance for account in market_accounts),
                total_available=sum(
                    account.available_balance for account in market_accounts
                ),
                total_unrealized_pnl=sum(
                    account.unrealized_pnl for account in market_accounts
                ),
                total_margin_used=sum(
                    account.margin_used for account in market_accounts
                ),
                total_equity=sum(account.total_equity for account in market_accounts),
                accounts_count=len(market_accounts),
            )
        )
    return breakdown


logger = logging.getLogger(__name__)


try:
    from bot_module import config as bot_config
except ImportError:
    # Stub if run standalone
    class MockConfig:
        REDIS_HOST, REDIS_PORT, REDIS_DB = "localhost", 6379, 0
        REDIS_COMMAND_CHANNEL = "depthsight:commands"
        REDIS_STATE_KEY_PORTFOLIO = "depthsight:state:portfolio"
        REDIS_STATE_KEY_STRATEGIES = "depthsight:state:strategies"
        REDIS_STATE_KEY_POSITIONS = "depthsight:state:positions"
        # Genetic algorithm config fallbacks
        GENETIC_MAX_CONCURRENT_RUNS = 3
        GENETIC_CORES_PER_RUN = 4

    bot_config = MockConfig()

# Redis client for API
REDIS_HOST = getattr(bot_config, "REDIS_HOST", "localhost")
REDIS_PORT = getattr(bot_config, "REDIS_PORT", 6379)
REDIS_DB = getattr(bot_config, "REDIS_DB", 0)
REDIS_USERNAME = getattr(bot_config, "REDIS_USERNAME", None)
REDIS_PASSWORD = getattr(bot_config, "REDIS_PASSWORD", None)
REDIS_COMMAND_CHANNEL = getattr(
    bot_config, "REDIS_COMMAND_CHANNEL", "depthsight:commands"
)
REDIS_STATE_KEY_PORTFOLIO = getattr(
    bot_config, "REDIS_STATE_KEY_PORTFOLIO", "depthsight:state:portfolio"
)
REDIS_STATE_KEY_STRATEGIES = getattr(
    bot_config, "REDIS_STATE_KEY_STRATEGIES", "depthsight:state:strategies"
)
REDIS_STATE_KEY_POSITIONS = getattr(
    bot_config, "REDIS_STATE_KEY_POSITIONS", "depthsight:state:positions"
)
HFT_CMD_CHANNEL = "hft:commands"
TV_WEBHOOK_DEDUPE_TTL_SECONDS = 30
TV_WEBHOOK_STATUS_TTL_SECONDS = 60 * 60 * 24 * 7


# --- SMART PATH DETERMINATION ---
# 1. Get the absolute path to the current file (depthsight_api.py)
# 2. Go up one level (to the project root where the 'api' and 'data_storage' folders are)
# 3. Add the data folder name
PROJECT_ROOT = Path(os.path.dirname(os.path.abspath(__file__))).parent
LOCAL_DATA_STORAGE_PATH = PROJECT_ROOT / "data_storage"


def _is_lifetime_payment(payment: models.Payment) -> bool:
    lifetime_billing = plans_config.get_plan_billing(payment.plan_name, "lifetime")
    if not lifetime_billing.get("enabled", False):
        return False

    lifetime_price = float(lifetime_billing.get("price_usd", -1))
    return abs(float(payment.amount_usd) - lifetime_price) < 0.0001


def _get_payment_plan_expires_at(payment: models.Payment) -> Optional[datetime]:
    if _is_lifetime_payment(payment):
        return None

    monthly_billing = plans_config.get_plan_billing(payment.plan_name, "monthly")
    period_days = int(monthly_billing.get("period_days", 30))
    return datetime.now(timezone.utc) + timedelta(days=period_days)


async def _get_lifetime_slots_for_plan(
    db: AsyncSession,
    plan_name: str,
    plan_config: dict,
) -> Optional[dict]:
    lifetime_billing = plan_config.get("billing", {}).get("lifetime", {})
    if not lifetime_billing.get("enabled", False):
        return None

    slot_limit = lifetime_billing.get("slot_limit")
    if slot_limit is None:
        return None

    price_usd = float(
        lifetime_billing.get("price_usd", plan_config.get("price_usd", 0))
    )
    counts = await crud.get_lifetime_payment_slot_counts(
        db=db,
        plan_name=plan_name,
        amount_usd=price_usd,
        reservation_ttl_seconds=plans_config.get_lifetime_reservation_ttl_seconds(),
    )
    limit = int(slot_limit)
    used = counts["used"]
    reserved = counts["reserved"]
    available = max(0, limit - used - reserved)

    return {
        "limit": limit,
        "used": used,
        "reserved": reserved,
        "available": available,
    }


async def _sync_live_runtime_for_plan_change(
    *,
    redis_client: redis.Redis,
    db: AsyncSession,
    user_id: int,
    previous_plan: Optional[str],
    new_plan: Optional[str],
) -> None:
    previous_live = plan_allows_live_trading(previous_plan)
    new_live = plan_allows_live_trading(new_plan)

    if previous_live == new_live:
        return

    if new_live:
        command = build_initialize_user_controller_command(user_id)
        await redis_client.publish(REDIS_COMMAND_CHANNEL, json.dumps(command))
        logger.info(
            "Published INITIALIZE_USER_CONTROLLER after plan change for user_id=%s (%s -> %s).",
            user_id,
            previous_plan,
            new_plan,
        )
        return

    active_keys = await crud.get_active_api_keys_for_user(db, user_id=user_id)
    for api_key_id in get_active_api_key_ids(active_keys):
        command = build_deactivate_api_key_command(user_id, api_key_id)
        await redis_client.publish(REDIS_COMMAND_CHANNEL, json.dumps(command))

    logger.info(
        "Published %s DEACTIVATE_API_KEY commands after plan change for user_id=%s (%s -> %s).",
        len(get_active_api_key_ids(active_keys)),
        user_id,
        previous_plan,
        new_plan,
    )


async def _enforce_live_strategy_limit(
    *,
    user: models.User,
    request: schemas.StrategyStartRequest,
    db: AsyncSession,
    redis_client: redis.Redis,
) -> None:
    if request.mode != "live":
        return

    live_limit = get_max_live_strategies(user.plan)
    if live_limit is None or live_limit < 0:
        return

    running_live_strategies = await load_user_running_strategies(
        redis_client,
        REDIS_STATE_KEY_STRATEGIES,
        user.id,
        mode="live",
    )
    current_count = len(running_live_strategies)

    if request.api_key_id is not None:
        target_api_key_ids = [int(request.api_key_id)]
    else:
        active_keys = await crud.get_active_api_keys_for_user(db, user_id=user.id)
        target_api_key_ids = get_active_api_key_ids(active_keys)

    projected_new_instances = count_new_strategy_instances(
        config_id=request.config_id,
        target_api_key_ids=target_api_key_ids,
        running_strategies=running_live_strategies,
    )

    if current_count + projected_new_instances <= live_limit:
        return

    detail = (
        f"You have reached the limit of concurrently running live strategies for your plan "
        f"({live_limit}). Currently running: {current_count}. "
        "The limit is applied per user across all API keys. "
    )
    if request.api_key_id is None and len(target_api_key_ids) > 1:
        detail += f"This launch would target {len(target_api_key_ids)} active API keys because api_key_id was not specified."
    elif projected_new_instances > 0:
        detail += f"This launch would add {projected_new_instances} new live strategy instance(s)."
    else:
        detail += "No new live instances would be created by this request."

    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
    )


async def _check_symbol_permissions(user: models.User, symbols: List[str]):
    """Checks if requested symbols are allowed for the user under their plan."""
    if not symbols:
        return

    user_plan_config = plans_config.get_plan(user.plan)
    allowed_symbols = user_plan_config.get("allowed_symbols")

    # If there is no 'allowed_symbols' key in the plan, there are no limits
    if allowed_symbols is None:
        return

    # Check that all requested symbols are in the allowed list
    for symbol in symbols:
        if symbol.upper() not in allowed_symbols:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your '{user.plan}' plan does not allow backtesting for the symbol '{symbol}'. "
                f"Available symbols: {', '.join(allowed_symbols)}",
            )


async def _validate_backtest_for_leaderboard(backtest_run: models.BacktestRun):
    """
    Checks if the backtest meets the requirements for leaderboard publication.
    Raises HTTPException on failure.
    """
    MIN_TRADES = 30  # Minimum number of trades
    kpis = backtest_run.kpi_results_json

    # --- Check 1: Minimum number of trades ---
    trades_count = kpis.get("trades", 0)
    if trades_count < MIN_TRADES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"A minimum of {MIN_TRADES} trades is required to publish in the leaderboard (you have {trades_count}).",
        )

    # --- Check 2: "Anti-HODL" filter (comparison with Buy & Hold) ---
    try:
        # Load daily asset data for the same period
        daily_klines = await data_loader.download_klines(
            symbol=backtest_run.symbol,
            timeframe="1d",
            start_dt=backtest_run.start_date,
            end_dt=backtest_run.end_date,
            market_type=backtest_run.market_type,
        )

        if daily_klines is None or daily_klines.empty:
            raise ValueError(
                "Failed to load historical data for Buy & Hold comparison."
            )

        # Calculate Sharpe Ratio for Buy & Hold
        daily_klines["daily_return"] = daily_klines["close"].pct_change()

        # Skip the first NaN value
        valid_returns = daily_klines["daily_return"].dropna()

        if valid_returns.std() > 0:
            mean_return = valid_returns.mean()
            std_dev = valid_returns.std()
            # Annualization (assuming 365 trading days per year for crypto)
            buy_and_hold_sharpe = (mean_return / std_dev) * np.sqrt(365)
        else:
            buy_and_hold_sharpe = 0.0

        strategy_sharpe = kpis.get("sharpe_ratio", 0.0)

        if strategy_sharpe <= buy_and_hold_sharpe:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Strategy did not pass validation: its efficiency (Sharpe {strategy_sharpe:.2f}) "
                f"does not exceed simple asset holding (Sharpe {buy_and_hold_sharpe:.2f}).",
            )

    except Exception as e:
        logger.error(
            f"Error validating backtest {backtest_run.id} for leaderboard: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error during strategy validation: {e}",
        )


def _check_intracandle_trigger_permission(
    user: models.User, config_data: Dict[str, Any]
):
    """
    Checks if the user is allowed to use intra-candle triggers.
    """
    user_plan_config = plans_config.get_plan(user.plan)
    limits = user_plan_config.get("limits", {})
    allow_intracandle = limits.get("allow_intracandle_triggers", False)

    if allow_intracandle:
        return  # User has permission, exit

    # Check which trigger is used in the configuration
    if isinstance(config_data, dict):
        entry_trigger = config_data.get("entryTrigger", {})
        trigger_type = entry_trigger.get("type")

        # If a forbidden trigger type is used, raise an error
        if trigger_type in ["on_tick", "on_condition_met"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your '{user.plan}' plan does not allow intra-candle entry triggers ('{trigger_type}'). "
                f"Please upgrade your plan to use this feature.",
            )


def _coerce_strategy_config_dict(config_data: Any, config_id: str) -> Dict[str, Any]:
    if isinstance(config_data, BaseModel):
        return config_data.model_dump(exclude_none=True)

    if hasattr(config_data, "model_dump") and callable(config_data.model_dump):
        return config_data.model_dump(exclude_none=True)

    if isinstance(config_data, str):
        try:
            return json.loads(config_data)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse config_data string for config {config_id}")
            raise HTTPException(
                status_code=500, detail="Corrupted strategy configuration data in DB."
            )

    if isinstance(config_data, dict):
        return dict(config_data)

    try:
        return json.loads(json.dumps(config_data, default=str))
    except (TypeError, json.JSONDecodeError) as exc:
        logger.error(
            f"Could not convert config_data of type {type(config_data)} to dict for config {config_id}: {exc}"
        )
        raise HTTPException(
            status_code=500, detail="Invalid format for strategy configuration data."
        )


def _plan_supports_backtest_engine(plan_name: str, engine: str) -> bool:
    quota_key = f"run_{engine}_backtest_per_day"
    quota_limit = plans_config.get_plan(plan_name).get("quotas", {}).get(quota_key, 0)
    return quota_limit != 0


def _user_has_pro_tier_access(user: models.User) -> bool:
    return _plan_supports_backtest_engine(user.plan, "kline")


def _enforce_strategy_plan_restrictions(
    strategy_payload: Dict[str, Any], user: models.User
) -> None:
    if is_strategy_pro_only(strategy_payload) and not _user_has_pro_tier_access(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This strategy contains Pro-only blocks. Upgrade to Pro to use it.",
        )


def _enforce_backtest_engine_access(user: models.User, engine: str) -> None:
    if engine == "kline" and not _plan_supports_backtest_engine(user.plan, engine):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Precision Engine is available on the Pro plan only.",
        )


def _normalize_tradingview_symbol(symbol: str) -> str:
    cleaned = (symbol or "").strip().upper()
    if ":" in cleaned:
        cleaned = cleaned.split(":", 1)[1]
    if "." in cleaned:
        cleaned = cleaned.split(".", 1)[0]
    return "".join(ch for ch in cleaned if ch.isalnum())


def _mask_secret_token(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def _build_tradingview_symbol_hint(
    symbol: str, market_type: Optional[str] = None
) -> str:
    normalized_symbol = _normalize_tradingview_symbol(symbol) or "BTCUSDT"
    if str(market_type or "").upper() == "FUTURES":
        return f"BINANCE:{normalized_symbol}.P"
    return f"BINANCE:{normalized_symbol}"


def _get_public_base_url(request: Request) -> str:
    public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip()
    if public_base_url:
        return public_base_url.rstrip("/")
    return str(request.base_url).rstrip("/")


def _build_tradingview_webhook_url(
    request: Request, user_secret_token: str, strategy_id: Optional[str] = None
) -> str:
    suffix = f"/{strategy_id}" if strategy_id else ""
    return _get_public_base_url(request) + f"/webhooks/tv/{user_secret_token}{suffix}"


def _build_tradingview_sample_payload(
    strategy_id: Optional[str] = "<strategy_id>",
    symbol: str = "BINANCE:BTCUSDT.P",
    api_key_id: Optional[int] = 123,
    include_strategy_id: bool = True,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": "buy",
        "symbol": symbol,
        "event_id": "{{strategy.order.id}}",
        "sent_at": "{{timenow}}",
        "price": "{{close}}",
        "timeframe": "{{interval}}",
        "bar_time": "{{time}}",
        "metadata": {"exchange": "{{exchange}}", "ticker": "{{ticker}}"},
    }
    if include_strategy_id:
        payload["strategy_id"] = strategy_id or "<strategy_id>"
    if api_key_id is not None:
        payload["api_key_id"] = api_key_id
    return payload


def _build_tv_webhook_dedupe_key(
    user_id: int,
    strategy_id: str,
    action: str,
    symbol: str,
    api_key_id: Optional[int],
    event_id: Optional[str],
    sent_at: Optional[datetime],
) -> str:
    event_id_part = event_id or ""
    sent_at_part = sent_at.isoformat() if sent_at else ""
    normalized_symbol = _normalize_tradingview_symbol(symbol)
    return f"tv:webhook:dedupe:{user_id}:{strategy_id}:{action}:{normalized_symbol}:{api_key_id}:{event_id_part}:{sent_at_part}"


def _build_tv_webhook_status_key(user_id: int, config_id: str) -> str:
    return f"tv:webhook:last:{user_id}:{config_id}"


async def _store_tv_webhook_status(
    redis_client: redis.Redis,
    user_id: int,
    config_id: str,
    status_value: str,
    message: Optional[str] = None,
    *,
    source: str = "tradingview_webhook",
    action: Optional[str] = None,
    symbol: Optional[str] = None,
    event_id: Optional[str] = None,
    api_key_id: Optional[int] = None,
    trace: Optional[Dict[str, Any]] = None,
) -> None:
    if not redis_client or not config_id:
        return

    payload: Dict[str, Any] = {
        "config_id": config_id,
        "status": status_value,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "message": message,
        "source": source,
        "action": action,
        "symbol": symbol,
        "event_id": event_id,
        "api_key_id": api_key_id,
    }
    if trace:
        payload["trace"] = json.loads(json.dumps(trace, default=str))

    try:
        await redis_client.set(
            _build_tv_webhook_status_key(user_id, config_id),
            json.dumps(payload, default=str),
            ex=TV_WEBHOOK_STATUS_TTL_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            f"Failed to store TradingView webhook status for {config_id}: {exc}"
        )


async def _queue_tradingview_signal_command(
    *,
    user: models.User,
    strategy_id: str,
    action: str,
    symbol: str,
    api_key_id: Optional[int],
    event_id: Optional[str],
    sent_at: Optional[datetime],
    price: Optional[float],
    timeframe: Optional[str],
    bar_time: Optional[str],
    metadata: Optional[Dict[str, Any]],
    redis_client: redis.Redis,
    db: AsyncSession,
    source: str = "tradingview_webhook",
) -> Dict[str, Any]:
    strategy_config = await crud.get_strategy_config(
        db, user_id=user.id, config_id=strategy_id
    )
    if not strategy_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy configuration not found.",
        )

    config_data = _coerce_strategy_config_dict(
        strategy_config.config_data, strategy_config.id
    )
    configured_symbol = _normalize_tradingview_symbol(config_data.get("symbol", ""))
    incoming_symbol = _normalize_tradingview_symbol(symbol)
    effective_symbol = incoming_symbol or configured_symbol

    if config_data.get("signal_source") != "tradingview_webhook":
        await _store_tv_webhook_status(
            redis_client,
            user.id,
            strategy_config.id,
            "rejected_by_api",
            "Strategy is not configured for TradingView webhook signals.",
            source=source,
            action=action,
            symbol=effective_symbol,
            event_id=event_id,
            api_key_id=api_key_id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Strategy is not configured for TradingView webhook signals.",
        )

    if configured_symbol and incoming_symbol and configured_symbol != incoming_symbol:
        mismatch_message = f"Webhook symbol mismatch. Expected '{configured_symbol}', got '{incoming_symbol}'."
        await _store_tv_webhook_status(
            redis_client,
            user.id,
            strategy_config.id,
            "rejected_by_api",
            mismatch_message,
            source=source,
            action=action,
            symbol=effective_symbol,
            event_id=event_id,
            api_key_id=api_key_id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=mismatch_message
        )

    if api_key_id is not None:
        api_key = await crud.get_api_key_by_id(db, user.id, api_key_id)
        if not api_key:
            await _store_tv_webhook_status(
                redis_client,
                user.id,
                strategy_config.id,
                "rejected_by_api",
                "api_key_id is invalid for this user.",
                source=source,
                action=action,
                symbol=effective_symbol,
                event_id=event_id,
                api_key_id=api_key_id,
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="api_key_id is invalid for this user.",
            )

    dedupe_key = _build_tv_webhook_dedupe_key(
        user.id, strategy_config.id, action, symbol, api_key_id, event_id, sent_at
    )
    is_new_event = await redis_client.set(
        dedupe_key, "1", ex=TV_WEBHOOK_DEDUPE_TTL_SECONDS, nx=True
    )
    if not is_new_event:
        await _store_tv_webhook_status(
            redis_client,
            user.id,
            strategy_config.id,
            "duplicate",
            "Duplicate webhook event ignored.",
            source=source,
            action=action,
            symbol=effective_symbol,
            event_id=event_id,
            api_key_id=api_key_id,
        )
        return {
            "status": "duplicate",
            "strategy_id": strategy_config.id,
            "event_id": event_id,
        }

    command = {
        "command": "TV_WEBHOOK_SIGNAL",
        "payload": {
            "user_id": user.id,
            "config_id": strategy_config.id,
            "api_key_id": api_key_id,
            "action": action,
            "symbol": symbol,
            "normalized_symbol": effective_symbol,
            "event_id": event_id,
            "sent_at": sent_at.isoformat() if sent_at else None,
            "price": price,
            "timeframe": timeframe,
            "bar_time": bar_time,
            "metadata": metadata or {},
            "source": source,
        },
    }

    await redis_client.publish(REDIS_COMMAND_CHANNEL, json.dumps(command))
    await _store_tv_webhook_status(
        redis_client,
        user.id,
        strategy_config.id,
        "accepted_by_api",
        "Webhook accepted and published to the bot controller.",
        source=source,
        action=action,
        symbol=effective_symbol,
        event_id=event_id,
        api_key_id=api_key_id,
    )
    return {
        "status": "accepted",
        "strategy_id": strategy_config.id,
        "event_id": event_id,
    }


# Global variable to hold the client, to be initialized on startup
# We will use this as a fallback, but the main one will be in app.state
_redis_client_instance: Optional[redis.Redis] = None


# This function remains unchanged
async def create_redis_client_instance() -> redis.Redis:
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        username=REDIS_USERNAME,
        password=REDIS_PASSWORD,
        decode_responses=True,
    )


async def perform_node_hub_sync():
    import socket
    import time
    from pathlib import Path

    hub_url = os.getenv("FEDERATION_HUB_URL", "https://app.depthsight.pro/api/v1/hub")
    hub_url = hub_url.rstrip("/")

    identity_path = Path("/app/data/node_identity.json")
    if not identity_path.parent.exists():
        identity_path = Path("node_identity.json")

    node_uuid = None
    node_secret = None
    node_name = None

    if identity_path.exists():
        try:
            with open(identity_path, "r") as f:
                data = json.load(f)
                node_uuid = data.get("node_uuid")
                node_secret = data.get("node_secret")
                node_name = data.get("node_name")
        except Exception as e:
            logger.error(f"Failed to read node identity file: {e}")

    app_version = APP_VERSION

    if not node_uuid or not node_secret:
        node_uuid = str(uuid.uuid4())
        node_secret = secrets.token_hex(32)
        node_name = f"DepthSightNode-{socket.gethostname()}-{node_uuid[:6]}"

        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "node_uuid": node_uuid,
                    "name": node_name,
                    "node_secret": node_secret,
                    "version": app_version,
                }
                async with session.post(
                    f"{hub_url}/nodes/register", json=payload, timeout=10.0
                ) as resp:
                    if resp.status == 201:
                        logger.info(
                            f"Node registered successfully with UUID: {node_uuid}"
                        )
                        with open(identity_path, "w") as f:
                            json.dump(
                                {
                                    "node_uuid": node_uuid,
                                    "node_secret": node_secret,
                                    "node_name": node_name,
                                },
                                f,
                            )
                    else:
                        err_text = await resp.text()
                        logger.error(
                            f"Failed to register node on Hub. Status: {resp.status}, Response: {err_text}"
                        )
                        return
        except Exception as e:
            logger.error(f"Connection error during node registration to Hub: {e}")
            return

    try:
        headers = {"X-Node-UUID": node_uuid, "X-Node-Secret": node_secret}
        async with aiohttp.ClientSession() as session:
            t0 = time.time()
            async with session.post(
                f"{hub_url}/nodes/ping",
                json={"latency_ms": 0.0, "version": app_version},
                headers=headers,
                timeout=10.0,
            ) as resp:
                latency = round((time.time() - t0) * 1000.0, 1)
                if resp.status == 200:
                    await session.post(
                        f"{hub_url}/nodes/ping",
                        json={"latency_ms": latency, "version": app_version},
                        headers=headers,
                        timeout=5.0,
                    )
                    logger.debug(f"Heartbeat ping successful. Latency: {latency}ms")
                else:
                    err_text = await resp.text()
                    logger.error(
                        f"Heartbeat ping failed. Status: {resp.status}, Response: {err_text}"
                    )
    except Exception as e:
        logger.error(f"Connection error during node heartbeat ping to Hub: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os as lifespan_os

    print(
        f"INFO: Application lifespan startup in worker PID: {lifespan_os.getpid()}..."
    )
    logger.info("Initializing AI Assistant...")
    ai_assistant.build_and_cache_prompts()
    await session_manager.start_session()
    print("INFO: Aiohttp session started.")

    if os.getenv("IS_CENTRAL_HUB", "false").lower() == "true":
        try:
            from .database import engine
            from .models import Base
            from sqlalchemy import text

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                # Auto-heal table if image column is missing
                try:
                    await conn.execute(
                        text(
                            "ALTER TABLE support_ticket_messages ADD COLUMN IF NOT EXISTS image TEXT;"
                        )
                    )
                except Exception as alter_err:
                    logger.warning(
                        f"Could not auto-add 'image' column to support_ticket_messages: {alter_err}"
                    )
                # Auto-heal news table if likes_count column is missing
                try:
                    await conn.execute(
                        text(
                            "ALTER TABLE hub_news ADD COLUMN IF NOT EXISTS likes_count INTEGER DEFAULT 0;"
                        )
                    )
                except Exception as alter_err:
                    logger.warning(
                        f"Could not auto-add 'likes_count' column to hub_news: {alter_err}"
                    )
                # Auto-heal news table if is_pinned column is missing
                try:
                    await conn.execute(
                        text(
                            "ALTER TABLE hub_news ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN DEFAULT FALSE;"
                        )
                    )
                except Exception as alter_err:
                    logger.warning(
                        f"Could not auto-add 'is_pinned' column to hub_news: {alter_err}"
                    )
                # Auto-heal nodes table if version column is missing
                try:
                    await conn.execute(
                        text(
                            "ALTER TABLE hub_nodes ADD COLUMN IF NOT EXISTS version VARCHAR(50) DEFAULT '1.0.0';"
                        )
                    )
                except Exception as alter_err:
                    logger.warning(
                        f"Could not auto-add 'version' column to hub_nodes: {alter_err}"
                    )
                # Auto-heal topics table if is_verified column is missing
                try:
                    await conn.execute(
                        text(
                            "ALTER TABLE hub_topics ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;"
                        )
                    )
                except Exception as alter_err:
                    logger.warning(
                        f"Could not auto-add 'is_verified' column to hub_topics: {alter_err}"
                    )
                # Auto-heal topics table if tags column is missing
                try:
                    await conn.execute(
                        text(
                            "ALTER TABLE hub_topics ADD COLUMN IF NOT EXISTS tags JSON;"
                        )
                    )
                except Exception as alter_err:
                    logger.warning(
                        f"Could not auto-add 'tags' column to hub_topics: {alter_err}"
                    )
            logger.info("Central Hub database tables verified/created successfully.")
        except Exception as db_err:
            logger.error(
                f"Error during Hub database tables auto-creation: {db_err}",
                exc_info=True,
            )
    else:

        async def run_sync_loop_wrapper():
            await asyncio.sleep(10.0)
            redis_lock_key = "depthsight:node_hub_sync_lock"

            while True:
                has_lock = False
                try:
                    redis_client = await create_redis_client_instance()
                    pid_val = str(lifespan_os.getpid())
                    acquired = await redis_client.set(
                        redis_lock_key, pid_val, ex=70, nx=True
                    )

                    if acquired:
                        has_lock = True
                    else:
                        current_val = await redis_client.get(redis_lock_key)
                        if current_val == pid_val:
                            await redis_client.expire(redis_lock_key, 70)
                            has_lock = True
                        else:
                            has_lock = False

                    await redis_client.close()
                except Exception as redis_err:
                    logger.warning(
                        f"Redis lock check failed, running sync anyway: {redis_err}"
                    )
                    has_lock = True

                if has_lock:
                    try:
                        await perform_node_hub_sync()
                    except Exception as sync_err:
                        logger.error(f"Error in perform_node_hub_sync: {sync_err}")

                await asyncio.sleep(60.0)

        asyncio.create_task(run_sync_loop_wrapper())

    # Pre-load Oracle model for this worker to ensure deterministic behavior
    try:
        from .simulation_router import get_oracle

        oracle = get_oracle()
        if oracle:
            logger.info(
                f"Oracle model pre-loaded successfully in worker PID: {lifespan_os.getpid()}"
            )
        else:
            logger.warning(
                f"Oracle model not available in worker PID: {lifespan_os.getpid()}"
            )
    except Exception as e:
        logger.error(
            f"Failed to pre-load Oracle model in worker PID {lifespan_os.getpid()}: {e}"
        )

    yield
    print(
        f"INFO: Application lifespan shutdown in worker PID: {lifespan_os.getpid()}..."
    )
    await session_manager.close_session()
    print("INFO: Aiohttp session closed.")


# --- Application Version ---
def _load_app_version() -> str:
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        version_file = os.path.join(base_dir, "VERSION")
        if os.path.exists(version_file):
            with open(version_file, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return "1.0.1"


APP_VERSION = os.getenv("APP_VERSION", _load_app_version())


# --- FastAPI Application and Routers ---
app = FastAPI(
    title="DepthSight Trading Bot API", version=APP_VERSION, lifespan=lifespan
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; frame-ancestors 'none';"
    )
    return response


# --- Rate Limiter Setup ---
# Use memory storage in tests, Redis in production for synchronization between workers
_redis_auth_str = ""
if REDIS_PASSWORD:
    _redis_auth_str = (
        f"{REDIS_USERNAME}:{REDIS_PASSWORD}@"
        if REDIS_USERNAME
        else f":{REDIS_PASSWORD}@"
    )
RATE_LIMIT_REDIS_URL = os.getenv(
    "RATE_LIMIT_REDIS_URL", f"redis://{_redis_auth_str}{REDIS_HOST}:{REDIS_PORT}/1"
)
TESTING = os.getenv("TESTING", "false").lower() == "true"
IS_CENTRAL_HUB = os.getenv("IS_CENTRAL_HUB", "false").lower() == "true"
RATELIMIT_ENABLED = (
    os.getenv("RATELIMIT_ENABLED", "true").lower() != "false"
)  # DISABLED FOR LOAD TEST

# Limits for different endpoints. Overridden in tests.
LIMITS_CONFIG = {
    "backtest": "100/hour",
    "genetic": "10/hour",
    "login": "5/minute",
    "default": "600/minute",
    "hub_feedback": "5/hour",
    "hub_topics": "10/hour",
    "hub_like": "60/minute",
    "hub_comments": "30/minute",
    "hub_messages": "30/minute",
}


def get_limit_value(limit_name: str) -> str:
    """Returns limit by name or stub for tests."""
    is_testing = os.getenv("TESTING", "false").lower() == "true"
    if is_testing:
        # For quota testing, low limits can be selectively enabled via env or mock
        test_limit = os.getenv(f"TEST_LIMIT_{limit_name.upper()}")
        return test_limit if test_limit else "10000/hour"

    return LIMITS_CONFIG.get(limit_name, LIMITS_CONFIG["default"])


if TESTING:
    limiter = Limiter(
        key_func=get_remote_address,
        storage_uri="memory://",
        default_limits=["10000/hour"],
        enabled=RATELIMIT_ENABLED,
    )
else:
    limiter = Limiter(
        key_func=get_remote_address,
        storage_uri=RATE_LIMIT_REDIS_URL,
        default_limits=[get_limit_value("default")],
        enabled=RATELIMIT_ENABLED,
    )
app.state.limiter = limiter

app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- Simulation of system state ---
SYSTEM_STATE = {
    "status": "ok",
    "version": APP_VERSION,
    "timestamp_utc": datetime.now(timezone.utc),
    "components": [
        {"name": "binance_spot_ws", "status": "connected"},
        {"name": "binance_futures_ws", "status": "connected"},
        {"name": "database_connection", "status": "ok"},
        {"name": "task_queue_connection", "status": "ok"},
    ],
}
ACTIVE_STRATEGIES: Dict[str, Dict[str, Any]] = {}
TASKS: Dict[str, Dict[str, Any]] = {}
CLIENT_CONFIG = {
    "risk_management": {
        "daily_max_loss_percent": 5.0,
        "risk_per_trade_percent": 0.5,  # Sniper Strategy Safe Default
        "min_rr_ratio": 2.0,
        "maxDrawdown": 10.0,
        "maxConcurrentTrades": 2,  # Increased for Sniper Strategy
        "stopLossEnabled": True,
    },
    "exchange_settings": {"binance": {"enabled": True, "api_key_name": "default"}},
    "notifications": {
        "emailEnabled": False,
        "telegramEnabled": False,
        "telegramChatId": "",
    },
    "dataSources": {
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "statuses": [
            {
                "name": "Binance Spot WS",
                "connected": True,
                "lastSync": datetime.now(timezone.utc).isoformat(),
            },
            {
                "name": "Binance Futures WS",
                "connected": True,
                "lastSync": datetime.now(timezone.utc).isoformat(),
            },
        ],
    },
}


origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix="/api/v1", tags=["v1"])

api_router.include_router(hft_router)


redis_api_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    username=REDIS_USERNAME,
    password=REDIS_PASSWORD,
    decode_responses=True,
)


# --- API Endpoints ---
@api_router.post("/token", response_model=schemas.LoginResponse)
@limiter.limit(get_limit_value("5/hour"))
# Login brute-force attack protection
async def login_for_access_token(
    request: Request,  # Required for slowapi
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    user_db = await crud.get_user_by_username(db, username=form_data.username)
    if not user_db or not security.verify_password(
        form_data.password, user_db.hashed_password
    ):
        # Log failed login attempt
        audit_logger.login_failed(
            username=form_data.username,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            reason="Invalid credentials" if not user_db else "Wrong password",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user_db.is_active:
        audit_logger.login_failed(
            username=form_data.username,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            reason="Account inactive",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user. Please confirm your email.",
        )

    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        data={"sub": user_db.username}, expires_delta=access_token_expires
    )

    refresh_token_expires = timedelta(minutes=security.REFRESH_TOKEN_EXPIRE_MINUTES)
    refresh_token = security.create_refresh_token(
        data={"sub": user_db.username}, expires_delta=refresh_token_expires
    )

    token_data = schemas.Token(
        access_token=access_token, refresh_token=refresh_token, token_type="bearer"
    )

    # 1. Check and grant retroactive achievements
    await check_and_grant_retroactive_achievements(db, user_db.id)

    # 2. Force commit changes in DB to get actual state
    await db.commit()

    # 3. Refresh user_db object from DB to fetch new XP and level
    await db.refresh(user_db)

    # 4. Now create user_data from refreshed object
    user_data = schemas.User.model_validate(user_db)

    # 5. Log successful login
    audit_logger.login_success(
        user_id=user_db.id,
        username=user_db.username,
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
    )

    return schemas.LoginResponse(token=token_data, user=user_data)


@api_router.post("/refresh", response_model=schemas.Token)
@limiter.limit(get_limit_value("10/minute"))
async def refresh_access_token(
    request: Request,
    refresh_request: schemas.RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        payload = security.jwt.decode(
            refresh_request.refresh_token,
            security.SECRET_KEY,
            algorithms=[security.ALGORITHM],
        )
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except security.JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_db = await crud.get_user_by_username(db, username=username)
    if not user_db or not user_db.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=security.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        data={"sub": user_db.username}, expires_delta=access_token_expires
    )

    refresh_token_expires = timedelta(minutes=security.REFRESH_TOKEN_EXPIRE_MINUTES)
    new_refresh_token = security.create_refresh_token(
        data={"sub": user_db.username}, expires_delta=refresh_token_expires
    )

    return schemas.Token(
        access_token=access_token, refresh_token=new_refresh_token, token_type="bearer"
    )


@api_router.post(
    "/register",
    response_model=schemas.ApiResponse,
    status_code=status.HTTP_200_OK,
    summary="Register new user",
)
@limiter.limit(get_limit_value("3/minute"))  # Protection against mass bot registration
async def register_user(
    user: schemas.UserCreate, request: Request, db: AsyncSession = Depends(get_db)
):
    """
    Registers a new user, sends a confirmation email, and waits for activation.
    """
    logger.info(
        f"REGISTRATION REQUEST: username={user.username}, email={user.email}, source={user.source}"
    )
    db_user = await crud.get_user_by_username(db, username=user.username)
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already registered",
        )

    db_user_by_email = await crud.get_user_by_email(db, email=user.email)
    if db_user_by_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Referral logic
    referred_by_user_id = None
    if user.ref_code:
        referrer = await crud.get_user_by_referral_code(db, referral_code=user.ref_code)
        if referrer:
            referred_by_user_id = referrer.id
        else:
            logger.warning(
                f"Referral code '{user.ref_code}' provided but no user found."
            )

    # If email confirmation is disabled, create an active user right away
    if not security.EMAIL_CONFIRMATION_ENABLED:
        new_user = await crud.create_user(
            db=db, user=user, referred_by_user_id=referred_by_user_id, is_active=True
        )
        if referred_by_user_id:
            await crud.create_pending_bonuses_for_referral(
                db, referrer_id=referred_by_user_id, referred_id=new_user.id
            )
        await db.commit()
        return {
            "data": {
                "message": "Registration successful. You can now log in.",
                "requires_confirmation": False,
            }
        }

    new_user = await crud.create_user(
        db=db, user=user, referred_by_user_id=referred_by_user_id
    )

    if referred_by_user_id:
        await crud.create_pending_bonuses_for_referral(
            db, referrer_id=referred_by_user_id, referred_id=new_user.id
        )

    await db.commit()
    await db.refresh(new_user)

    # --- Email Confirmation Logic ---
    token = security.email_confirmation_serializer.dumps(
        new_user.email, salt=security.EMAIL_CONFIRMATION_SALT
    )

    frontend_url = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")
    # Use PWA path if registration came from PWA
    if user.source == "pwa":
        confirm_url = f"{frontend_url}/pwa/confirm-email/{token}"
    else:
        confirm_url = f"{frontend_url}/confirm-email/{token}"

    # Send email
    from .email_utils import send_email

    subject = "Confirm your email for DepthSight"
    html_content = f"""<html>
<body>
<h2>Welcome to DepthSight!</h2>
<p>Please click the link below to confirm your email address:</p>
<p><a href="{confirm_url}">Confirm Email</a></p>
<p>If you did not register for an account, please ignore this email.</p>
</body>
</html>"""
    try:
        send_email(new_user.email, subject, html_content)
    except Exception as e:
        logger.error(
            f"Failed to send confirmation email to {new_user.email}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The email service is currently unavailable. Please try again later.",
        )

    logger.info(f"CONFIRMATION URL FOR {new_user.email}: {confirm_url}")

    return {
        "data": {
            "message": "Registration successful. Please check your email to confirm your account.",
            "requires_confirmation": True,
        }
    }


@api_router.get("/users/me", response_model=schemas.User, summary="Get current user")
async def read_users_me(current_user: models.User = Depends(get_current_user)):
    """
    Returns current authorized user data.
    Used for validating token on application load.
    """
    logger.info(
        f"DEBUG: Returning user {current_user.username} with referral code: {current_user.referral_code}"
    )
    return current_user


@api_router.delete("/users/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_current_user(
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete the current user's account and all associated data.
    """
    success = await crud.delete_user(db, user_id=current_user.id)
    if not success:
        # This should not happen if the user is authenticated
        raise HTTPException(status_code=404, detail="User not found")

    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def count_blocks(config_data: dict) -> int:
    """Counts the number of blocks in a strategy configuration."""
    count = 0

    def count_recursive(node):
        nonlocal count
        if not isinstance(node, dict):
            return

        # Each block is a dictionary with a 'type' key
        if "type" in node:
            count += 1

        # Recursively check children in logical operators or other nested structures
        if "children" in node and isinstance(node.get("children"), list):
            for child in node["children"]:
                count_recursive(child)

    # Count blocks in filters
    if "filters" in config_data and isinstance(config_data.get("filters"), list):
        for block in config_data["filters"]:
            count_recursive(block)

    # Count blocks in entry conditions
    if "entryConditions" in config_data and isinstance(
        config_data.get("entryConditions"), dict
    ):
        count_recursive(config_data["entryConditions"])

    # Count blocks in position management
    if "positionManagement" in config_data and isinstance(
        config_data.get("positionManagement"), list
    ):
        for block in config_data["positionManagement"]:
            count_recursive(block)

    return count


@api_router.get(
    "/webhooks/tv-info",
    response_model=schemas.ApiResponseData[schemas.TradingViewWebhookInfo],
)
async def get_tradingview_webhook_info(
    request: Request,
    config_id: Optional[str] = Query(None),
    api_key_id: Optional[int] = Query(None),
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_user = await crud.ensure_user_tradingview_webhook_token(db, current_user)
    await db.commit()
    await db.refresh(current_user)

    if config_id:
        strategy_config = await crud.get_strategy_config(
            db, user_id=current_user.id, config_id=config_id
        )
        if not strategy_config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy configuration not found.",
            )

        config_data = _coerce_strategy_config_dict(
            strategy_config.config_data, strategy_config.id
        )
        strategy_symbol = str(config_data.get("symbol") or "").upper() or None
        symbol_hint = _build_tradingview_symbol_hint(
            strategy_symbol or "BTCUSDT", config_data.get("marketType")
        )

        if api_key_id is not None:
            api_key = await crud.get_api_key_by_id(db, current_user.id, api_key_id)
            if not api_key:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="api_key_id is invalid for this user.",
                )

        return {
            "data": {
                "url": _build_tradingview_webhook_url(
                    request, current_user.tradingview_webhook_token, strategy_config.id
                ),
                "user_secret_token_masked": _mask_secret_token(
                    current_user.tradingview_webhook_token
                ),
                "sample_payload": _build_tradingview_sample_payload(
                    strategy_id=strategy_config.id,
                    symbol=symbol_hint,
                    api_key_id=api_key_id,
                    include_strategy_id=False,
                ),
                "requires_strategy_id": False,
                "strategy_id": strategy_config.id,
                "symbol": strategy_symbol,
            }
        }

    return {
        "data": {
            "url": _build_tradingview_webhook_url(
                request, current_user.tradingview_webhook_token
            ),
            "user_secret_token_masked": _mask_secret_token(
                current_user.tradingview_webhook_token
            ),
            "sample_payload": _build_tradingview_sample_payload(api_key_id=None),
            "requires_strategy_id": True,
        }
    }


@api_router.get(
    "/webhooks/tv-status/{config_id}",
    response_model=schemas.ApiResponseData[schemas.TradingViewWebhookStatus],
)
async def get_tradingview_webhook_status(
    config_id: str,
    redis_client: redis.Redis = Depends(get_redis_client),
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    strategy_config = await crud.get_strategy_config(
        db, user_id=current_user.id, config_id=config_id
    )
    if not strategy_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy configuration not found.",
        )

    raw_status = await redis_client.get(
        _build_tv_webhook_status_key(current_user.id, config_id)
    )
    if raw_status:
        try:
            return {"data": json.loads(raw_status)}
        except json.JSONDecodeError:
            logger.warning(
                f"Invalid TradingView webhook status payload in Redis for config {config_id}"
            )

    return {
        "data": {
            "config_id": config_id,
            "status": "idle",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "message": "No webhook events received yet.",
            "source": "tradingview_webhook",
        }
    }


@api_router.post(
    "/webhooks/tv-test", response_model=schemas.ApiResponseData[Dict[str, Any]]
)
async def send_tradingview_test_signal(
    request: schemas.TradingViewWebhookTestRequest,
    redis_client: redis.Redis = Depends(get_redis_client),
    current_user: models.User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    strategy_config = await crud.get_strategy_config(
        db, user_id=current_user.id, config_id=request.config_id
    )
    if not strategy_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy configuration not found.",
        )

    config_data = _coerce_strategy_config_dict(
        strategy_config.config_data, strategy_config.id
    )
    strategy_symbol = str(config_data.get("symbol") or "").upper()
    if not strategy_symbol:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Strategy symbol is not configured.",
        )

    symbol_hint = _build_tradingview_symbol_hint(
        strategy_symbol, config_data.get("marketType")
    )
    event_id = f"ui-test-{request.action}-{uuid.uuid4().hex[:12]}"

    result = await _queue_tradingview_signal_command(
        user=current_user,
        strategy_id=request.config_id,
        action=request.action,
        symbol=symbol_hint,
        api_key_id=request.api_key_id,
        event_id=event_id,
        sent_at=datetime.now(timezone.utc),
        price=None,
        timeframe="ui_test",
        bar_time=None,
        metadata={"source": "strategy_editor", "test_signal": True},
        redis_client=redis_client,
        db=db,
        source="ui_test",
    )
    return {"data": result}


@api_router.get(
    "/genes/my", response_model=schemas.ApiResponseData[schemas.UserGenesResponse]
)
async def get_my_genes(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Get all genes discovered by the current user."""
    genes_data = await crud.get_user_genes(db, current_user.id, limit, offset)
    total = await crud.count_user_genes(db, current_user.id)

    genes_list = []
    for user_gene, gene in genes_data:
        genes_list.append(
            schemas.UserGene(
                id=user_gene.id,
                user_id=user_gene.user_id,
                gene_id=user_gene.gene_id,
                unlocked_at=user_gene.unlocked_at,
                source_strategy_id=user_gene.source_strategy_id,
                source_type=user_gene.source_type,
                gene=schemas.Gene(
                    id=gene.id,
                    name=gene.name,
                    description=gene.description,
                    components=gene.components,
                    rarity=gene.rarity,
                    discovered_at=gene.discovered_at,
                    first_discovered_by=gene.first_discovered_by,
                ),
            )
        )

    return schemas.ApiResponseData(
        data=schemas.UserGenesResponse(total=total, genes=genes_list)
    )


@api_router.get(
    "/genes/stats", response_model=schemas.ApiResponseData[schemas.GeneStatsResponse]
)
async def get_gene_stats(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Get statistics about user's gene collection."""
    total_user_genes = await crud.count_user_genes(db, current_user.id)
    total_system_genes = await crud.get_total_genes_in_system(db)
    rarity_breakdown = await crud.get_user_genes_by_rarity(db, current_user.id)
    recent_data = await crud.get_recent_user_genes(db, current_user.id, limit=5)

    recent_genes = []
    for user_gene, gene in recent_data:
        recent_genes.append(
            schemas.UserGene(
                id=user_gene.id,
                user_id=user_gene.user_id,
                gene_id=user_gene.gene_id,
                unlocked_at=user_gene.unlocked_at,
                source_strategy_id=user_gene.source_strategy_id,
                source_type=user_gene.source_type,
                gene=schemas.Gene(
                    id=gene.id,
                    name=gene.name,
                    description=gene.description,
                    components=gene.components,
                    rarity=gene.rarity,
                    discovered_at=gene.discovered_at,
                    first_discovered_by=gene.first_discovered_by,
                ),
            )
        )

    return schemas.ApiResponseData(
        data=schemas.GeneStatsResponse(
            total_genes_discovered=total_user_genes,
            total_genes_in_system=total_system_genes,
            rarity_breakdown=rarity_breakdown,
            recent_discoveries=recent_genes,
        )
    )


# --- Discovery Router (Genetic Algorithms) ---
ai_meta_router, ai_core_router = create_ai_routers(
    _enforce_strategy_plan_restrictions,
    _user_has_pro_tier_access,
    is_strategy_kline_only,
)


@app.exception_handler(HTTPException)
async def http_exception_handler_custom(request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code, content={"error": exc.detail, "detail": None}
    )


@app.exception_handler(Exception)
async def validation_exception_handler(request, exc):
    print("--- UNHANDLED EXCEPTION ---")
    traceback.print_exc()
    print("--- END UNHANDLED EXCEPTION ---")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Internal Server Error", "detail": str(exc)},
    )


model_lab_router = create_model_lab_router(generate_dataset_task, train_model_task)

include_application_routers(
    app,
    (
        public_router,
        api_router,
        auth_router,
        payments_router,
        webhooks_router,
        admin_router,
        affiliate_router,
        model_lab_router,
        users_extra_router,
        notifications_router,
        support_router,
        admin_support_router,
        discovery_router,
        ai_meta_router,
        ai_core_router,
        api_keys_router,
        backtests_router,
        strategies_router,
        account_router,
        portfolio_router,
        config_router,
        diagnostics_router,
        tasks_router,
        gamification_router,
    ),
    is_central_hub=IS_CENTRAL_HUB,
    logger=logger,
)


if __name__ == "__main__":
    if UVICORN_INSTALLED_API_DEPTHSIGHT and uvicorn:
        uvicorn.run(app, host="127.0.0.1", port=8000)
    else:
        print(
            "Uvicorn not installed in api/depthsight_api.py. Cannot run FastAPI app directly."
        )
