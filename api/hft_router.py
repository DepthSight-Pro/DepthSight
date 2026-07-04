from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from .database import get_db
from .crud import get_config as get_user_app_config
import json
import logging
import os
from .auth import get_current_user
from .redis_client import get_redis_client
from .models import User
from bot_module.exchanges.common import is_binance_exchange
import redis.asyncio as redis
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/hft", tags=["HFT Control"], dependencies=[Depends(get_current_user)]
)

# Redis Channels matching Rust implementation
# Rust: hft:commands, hft:symbols, hft:oracle
CMD_CHANNEL = "hft:commands"


def get_user_config_key(user_id: int) -> str:
    return f"hft:config:{user_id}"


class PartialTakeProfitConfig(BaseModel):
    """Partial take profit configuration to match Rust PartialTakeProfitConfig struct."""

    use_limit_orders: bool = True
    ptp1_enabled: bool = True
    ptp1_rr: float = 2.0
    ptp1_percent: float = 20.0

    ptp2_enabled: bool = True
    ptp2_rr: float = 4.0
    ptp2_percent: float = 20.0

    ptp3_enabled: bool = False
    ptp3_rr: float = 8.0
    ptp3_percent: float = 20.0

    ptp4_enabled: bool = False
    ptp4_rr: float = 16.0
    ptp4_percent: float = 20.0


class HftConfig(BaseModel):
    # Matches Rust HftConfig struct
    entry_threshold: float = 0.4
    max_position_size_usd: float = 100.0

    # Stop Loss Settings
    sl_type: str = "ATR"  # PERCENT, ATR

    sl_val: float = 0.02
    stop_loss_cooldown_seconds: int = 0

    # Take Profit Settings
    tp_type: str = "RR"  # PERCENT, ATR, RR
    tp_val: float = 0.4

    # Partial Take Profit Settings
    partial_tp: PartialTakeProfitConfig = PartialTakeProfitConfig()

    # Breakeven Settings
    be_enabled: bool = False
    be_type: str = "PERCENT"  # PERCENT, RR
    be_threshold: float = 0.01

    trailing_stop_enabled: bool = False
    risk_per_trade_pct: float = 1.0
    max_leverage: float = 20.0
    max_hold_minutes: int = 0
    use_screener: bool = True
    use_oracle: bool = True

    # Limits (new fields matching Rust)
    max_analyzed_symbols: int = 20
    max_concurrent_trades: int = 5
    use_risk_size: bool = True
    use_maker_mode: bool = False

    # Stop Loss / Take Profit additional
    min_sl_percent: float = 0.0005
    be_offset_pct: float = 0.1
    sl_trigger_type: str = "LAST"  # LAST, MARK

    # Liquidity & Filters
    min_volume_24h: float = 50_000_000.0
    entry_slippage_limit: float = 0.0005
    liquidity_safety_factor: float = 10.0
    max_spread_pct: float = 0.001  # 0.1%

    # Dynamic Exit
    auto_exit_on_low_confidence: bool = False
    exit_confidence_threshold: float = 0.48

    trade_on_close_only: bool = True
    ignore_auto_blacklist_rules: bool = False

    # Mock Screener
    mock_screener_enabled: bool = False
    mock_screener_symbols: List[str] = []

    class Config:
        extra = "allow"


@router.post("/start", status_code=status.HTTP_200_OK)
async def start_hft_engine(
    symbol: Optional[str] = None,
    api_key_id: Optional[int] = None,
    redis_client: redis.Redis = Depends(get_redis_client),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Starts the HFT Engine. If symbol is provided, starts a specific bot. Otherwise, starts global screener."""
    try:
        # 1. Fetch user's API keys
        app_config = await get_user_app_config(db, user.id)
        api_key = os.getenv("HFT_INTERNAL_API_KEY", "internal")
        api_secret = os.getenv("HFT_INTERNAL_API_SECRET", "internal")

        if app_config and app_config.api_keys:
            futures_key = None

            # If explicit ID is provided, try to find it first
            if api_key_id:
                futures_key = next(
                    (
                        k
                        for k in app_config.api_keys
                        if k.id == api_key_id
                        and k.is_active
                        and is_binance_exchange(k.exchange)
                    ),
                    None,
                )
                if not futures_key:
                    logger.warning(
                        f"Requested api_key_id={api_key_id} not found, inactive or not Binance for user {user.id}. Falling back to default."
                    )

            # Default fallback logic (first active Binance key)
            if not futures_key:
                futures_key = next(
                    (
                        k
                        for k in app_config.api_keys
                        if is_binance_exchange(k.exchange) and k.is_active
                    ),
                    None,
                )

            if futures_key:
                from .models import ApiKey as ApiKeyModel
                from sqlalchemy import select

                res = await db.execute(
                    select(ApiKeyModel).where(ApiKeyModel.id == futures_key.id)
                )
                db_key = res.scalar_one_or_none()
                if db_key:
                    # Send encrypted keys to Rust bot - decryption happens there
                    api_key = db_key.encrypted_api_key
                    api_secret = db_key.encrypted_api_secret
                else:
                    logger.warning(
                        f"DB key not found for futures_key.id={futures_key.id}"
                    )
            else:
                logger.warning(
                    f"No active Binance-compatible key found for user {user.id}"
                )
        else:
            logger.warning(f"No app_config or api_keys for user {user.id}")

        # 2. Fetch current HFT config
        config_key = get_user_config_key(user.id)
        config_json = await redis_client.get(config_key)
        if config_json:
            config_dict = json.loads(config_json)
        else:
            config_dict = HftConfig().model_dump()

        if symbol:
            # Single Bot Mode
            payload = {
                "action": "StartBot",
                "bot_id": f"bot_{user.id}_{symbol}",
                "user_id": user.id,
                "symbol": symbol,
                "api_key": api_key,
                "api_secret": api_secret,
                "config": config_dict,
            }
        else:
            # Global Screener Mode
            payload = {
                "action": "StartScreener",
                "user_id": user.id,
                "api_key": api_key,
                "api_secret": api_secret,
                "config": config_dict,
            }

        await redis_client.publish(CMD_CHANNEL, json.dumps(payload))
        msg = f"Start command for {'screener' if not symbol else symbol} published"
        logger.info(f"User {user.username} published start command: {msg}")
        return {"status": "command_sent", "message": msg}
    except Exception as e:
        logger.error(f"Failed to publish Start command: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop", status_code=status.HTTP_200_OK)
async def stop_hft_engine(
    symbol: Optional[str] = None,
    redis_client: redis.Redis = Depends(get_redis_client),
    user: User = Depends(get_current_user),
):
    """Stops the HFT Engine. If symbol is provided, stops specific bot. Otherwise, stops all bots for user."""
    try:
        if symbol:
            payload = {"action": "StopBot", "bot_id": f"bot_{user.id}_{symbol}"}
        else:
            payload = {"action": "EmergencyStop", "user_id": user.id}
        await redis_client.publish(CMD_CHANNEL, json.dumps(payload))
        logger.info(
            f"User {user.username} published Stop command for {'all bots' if not symbol else symbol}"
        )
        return {"status": "command_sent", "message": "Stop command published"}
    except Exception as e:
        logger.error(f"Failed to publish Stop command: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/emergency", status_code=status.HTTP_200_OK)
async def emergency_stop(
    redis_client: redis.Redis = Depends(get_redis_client),
    user: User = Depends(get_current_user),
):
    """Triggers Emergency Stop (Flatten all positions and stop)."""
    try:
        # Construct Rust HftCommand::EmergencyStop payload
        payload = {"action": "EmergencyStop", "user_id": user.id}
        await redis_client.publish(CMD_CHANNEL, json.dumps(payload))
        logger.info(f"User {user.username} published EmergencyStop command")
        return {"status": "command_sent", "message": "Emergency stop command published"}
    except Exception as e:
        logger.error(f"Failed to publish EmergencyStop command: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config", status_code=status.HTTP_200_OK)
async def update_config(
    config: HftConfig,
    symbol: str = "BTCUSDT",
    redis_client: redis.Redis = Depends(get_redis_client),
    user: User = Depends(get_current_user),
):
    """Updates HFT strategy configuration."""
    try:
        # Save to Redis persistence
        config_key = get_user_config_key(user.id)
        await redis_client.set(config_key, config.model_dump_json())

        # Publish UpdateScreenerConfig command (Global Update)
        # This updates the screener template AND broadcasts to all active bots for this user
        payload = {
            "action": "UpdateScreenerConfig",
            "user_id": user.id,
            "config": config.model_dump(),
        }
        await redis_client.publish(CMD_CHANNEL, json.dumps(payload))

        logger.info(f"User {user.username} updated HFT Config")
        return {"status": "success", "config": config}
    except Exception as e:
        logger.error(f"Failed to update HFT config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config", response_model=HftConfig)
async def get_config(
    redis_client: redis.Redis = Depends(get_redis_client),
    user: User = Depends(get_current_user),
):
    """Fetches current HFT configuration."""
    try:
        config_key = get_user_config_key(user.id)
        config_json = await redis_client.get(config_key)
        if not config_json:
            return HftConfig()
        return json.loads(config_json)
    except Exception as e:
        logger.error(f"Failed to get HFT config: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch config")
