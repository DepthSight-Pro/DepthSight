import logging
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Query,
    UploadFile,
    File,
    Form,
)
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

import json
from datetime import datetime, timezone
from typing import Optional

from .. import crud, models, schemas, security
from ..auth import get_current_user
from ..database import get_db
from ..federation import get_federation_hub_url
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


async def sync_node_weex_uid_to_hub(db: AsyncSession, user_id: int, weex_uid: str):
    """
    Finds the active mining node for this user, and sends a registration request
    to the Central Hub to update its weex_uid. Only runs if mining is enabled and
    we are not on the Central Hub itself.
    """
    import os
    import aiohttp
    from sqlalchemy import select
    from .. import models, crud

    # 1. Check if we are on Central Hub (if so, we do not need to register remotely, we are the authority)
    is_central = os.getenv("IS_CENTRAL_HUB", "false").lower() == "true"
    if is_central:
        return

    # 2. Check if mining is enabled for this user to preserve privacy
    config = await crud.get_config_model(db, user_id)
    if not config or not config.is_mining_enabled:
        return

    # 3. Retrieve user object
    user_stmt = select(models.User).where(models.User.id == user_id)
    user_res = await db.execute(user_stmt)
    user = user_res.scalars().first()
    if not user:
        return

    settings = dict(config.exchange_settings or {})
    weex_settings = settings.get("weex") or {}
    mining_node_uuid = weex_settings.get("mining_node_uuid")
    mining_node_secret = security.decrypt_node_secret(
        weex_settings.get("mining_node_secret")
    )

    if not mining_node_uuid or not mining_node_secret:
        # Fallback to physical identity
        from pathlib import Path
        import json

        identity_path = Path("/app/data/node_identity.json")
        if not identity_path.parent.exists():
            identity_path = Path("node_identity.json")
        if identity_path.exists():
            try:
                with open(identity_path, "r") as f:
                    data = json.load(f)
                    mining_node_uuid = data.get("node_uuid")
                    mining_node_secret = data.get("node_secret")
            except Exception:
                pass

    if not mining_node_uuid or not mining_node_secret:
        return

    hub_url = get_federation_hub_url()

    is_server_admin = user.role == "admin"
    reg_payload = {
        "node_uuid": mining_node_uuid,
        "name": f"DepthSightNode-{mining_node_uuid[:8]}",
        "node_secret": mining_node_secret,
        "version": "1.0.0",
        "referrer_code": None,
        "weex_uid": weex_uid,
        "is_mining_server": is_server_admin,
    }

    # Update local HubNode directly in database if present
    try:
        from sqlalchemy import update

        await db.execute(
            update(models.HubNode)
            .where(
                (models.HubNode.node_referral_code == user.referral_code)
                | (models.HubNode.node_uuid == mining_node_uuid)
            )
            .values(weex_uid=weex_uid)
        )
        await db.commit()
    except Exception as dbe:
        logger.debug(f"Direct HubNode weex_uid update skipped: {dbe}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{hub_url}/nodes/register", json=reg_payload, timeout=5.0
            ) as resp:
                if resp.status in (200, 201):
                    logger.info(
                        f"Successfully synced resolved Weex UID {weex_uid} to Hub for node {mining_node_uuid}"
                    )
                else:
                    err_txt = await resp.text()
                    logger.warning(
                        f"Failed to sync Weex UID to Hub. Status: {resp.status}, Response: {err_txt}"
                    )
    except Exception as e:
        logger.error(f"Error syncing Weex UID to Hub: {e}")


async def auto_resolve_weex_uid(db: AsyncSession, user_id: int) -> Optional[str]:
    """
    Attempts to automatically fetch the Weex UID using the user's saved Weex API credentials,
    and save it in exchange_settings.
    """
    from sqlalchemy import select, update
    from .. import models, security
    import httpx
    import hmac
    import hashlib
    import time
    import base64
    import json

    # 1. Fetch user's Weex API keys
    stmt = select(models.ApiKey).where(
        models.ApiKey.user_id == user_id,
        models.ApiKey.exchange.in_(["weex", "weex_futures", "weex_spot"]),
    )
    res = await db.execute(stmt)
    api_keys = res.scalars().all()

    if not api_keys:
        return None

    for key_obj in api_keys:
        try:
            api_key = security.decrypt_data(key_obj.encrypted_api_key)
            decrypted_secret = security.decrypt_data(key_obj.encrypted_api_secret)
            api_secret = decrypted_secret
            passphrase = ""
            try:
                parsed = json.loads(decrypted_secret)
                if isinstance(parsed, dict) and "secret" in parsed:
                    api_secret = parsed["secret"]
                    passphrase = parsed.get("password", "")
            except (json.JSONDecodeError, TypeError):
                pass

            if not api_key or not api_secret:
                continue

            # Perform standalone Weex V3 API request without using hub_private client
            timestamp = str(int(time.time() * 1000))
            method = "GET"
            path = "/api/v3/account"
            message = f"{timestamp}{method}{path}"

            signature = hmac.new(
                api_secret.encode("utf-8"),
                message.encode("utf-8"),
                hashlib.sha256,
            ).digest()
            sign = base64.b64encode(signature).decode("utf-8")

            headers = {
                "ACCESS-KEY": api_key,
                "ACCESS-SIGN": sign,
                "ACCESS-TIMESTAMP": timestamp,
                "ACCESS-PASSPHRASE": passphrase,
                "Content-Type": "application/json",
            }

            url = f"https://api-spot.weex.com{path}"

            async with httpx.AsyncClient(timeout=10.0) as http_client:
                resp = await http_client.get(url, headers=headers)
                if resp.status_code == 200:
                    res_json = resp.json()
                    # Weex wraps responses in a "data" object
                    res_data = (
                        res_json.get("data") if isinstance(res_json, dict) else {}
                    )
                    if not res_data:
                        res_data = res_json
                    uid = res_data.get("uid")
                    if uid is not None:
                        uid_str = str(uid)
                        cfg_stmt = select(models.AppConfig).where(
                            models.AppConfig.user_id == user_id
                        )
                        cfg_res = await db.execute(cfg_stmt)
                        cfg = cfg_res.scalars().first()
                        if cfg:
                            settings = dict(cfg.exchange_settings or {})
                            weex_settings = settings.get("weex") or {}
                            weex_settings["weex_uid"] = uid_str
                            weex_settings["uid"] = uid_str
                            settings["weex"] = weex_settings

                            await db.execute(
                                update(models.AppConfig)
                                .where(models.AppConfig.user_id == user_id)
                                .values(exchange_settings=settings)
                            )
                            await db.commit()
                            logger.info(
                                f"[AUTO_WEEX_UID] Automatically resolved and saved Weex UID {uid_str} for user ID {user_id}"
                            )
                        # Sync Weex UID to Central Hub (if mining is active and user is opt-in)
                        await sync_node_weex_uid_to_hub(db, user_id, uid_str)
                        return uid_str
        except Exception as e:
            logger.error(
                f"[AUTO_WEEX_UID] Error resolving Weex UID for user {user_id}: {e}",
                exc_info=True,
            )

    return None


async def sync_node_okx_uid_to_hub(db: AsyncSession, user_id: int, okx_uid: str):
    """
    Finds the active mining node for this user, and sends a registration request
    to the Central Hub to update its okx_uid. Only runs if mining is enabled and
    we are not on the Central Hub itself.
    """
    import os
    import aiohttp
    from sqlalchemy import select
    from .. import models, crud

    # 1. Check if we are on Central Hub
    is_central = os.getenv("IS_CENTRAL_HUB", "false").lower() == "true"
    if is_central:
        return

    # 2. Check if mining is enabled for this user to preserve privacy
    config = await crud.get_config_model(db, user_id)
    if not config or not config.is_mining_enabled:
        return

    # 3. Retrieve user object
    user_stmt = select(models.User).where(models.User.id == user_id)
    user_res = await db.execute(user_stmt)
    user = user_res.scalars().first()
    if not user:
        return

    settings = dict(config.exchange_settings or {})
    okx_settings = settings.get("okx") or {}
    mining_node_uuid = okx_settings.get("mining_node_uuid") or (
        settings.get("weex") or {}
    ).get("mining_node_uuid")
    mining_node_secret = security.decrypt_node_secret(
        okx_settings.get("mining_node_secret")
        or (settings.get("weex") or {}).get("mining_node_secret")
    )

    if not mining_node_uuid or not mining_node_secret:
        # Fallback to physical identity
        from pathlib import Path
        import json

        identity_path = Path("/app/data/node_identity.json")
        if not identity_path.parent.exists():
            identity_path = Path("node_identity.json")
        if identity_path.exists():
            try:
                with open(identity_path, "r") as f:
                    data = json.load(f)
                    mining_node_uuid = data.get("node_uuid")
                    mining_node_secret = data.get("node_secret")
            except Exception:
                pass

    if not mining_node_uuid or not mining_node_secret:
        return

    hub_url = get_federation_hub_url()
    is_server_admin = user.role == "admin"
    reg_payload = {
        "node_uuid": mining_node_uuid,
        "name": f"DepthSightNode-{mining_node_uuid[:8]}",
        "node_secret": mining_node_secret,
        "version": "1.0.0",
        "referrer_code": None,
        "okx_uid": okx_uid,
        "is_mining_server": is_server_admin,
    }

    # Update local HubNode directly in database if present
    try:
        from sqlalchemy import update

        await db.execute(
            update(models.HubNode)
            .where(
                (models.HubNode.node_referral_code == user.referral_code)
                | (models.HubNode.node_uuid == mining_node_uuid)
            )
            .values(okx_uid=okx_uid)
        )
        await db.commit()
    except Exception as dbe:
        logger.debug(f"Direct HubNode okx_uid update skipped: {dbe}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{hub_url}/nodes/register", json=reg_payload, timeout=5.0
            ) as resp:
                if resp.status in (200, 201):
                    logger.info(
                        f"Successfully synced resolved OKX UID {okx_uid} to Hub for node {mining_node_uuid}"
                    )
                else:
                    err_txt = await resp.text()
                    logger.warning(
                        f"Failed to sync OKX UID to Hub. Status: {resp.status}, Response: {err_txt}"
                    )
    except Exception as e:
        logger.error(f"Error syncing OKX UID to Hub: {e}")


async def auto_resolve_okx_uid(db: AsyncSession, user_id: int) -> Optional[str]:
    """
    Attempts to automatically fetch the OKX UID using the user's saved OKX API credentials,
    and save it in exchange_settings.
    """
    from sqlalchemy import select, update
    from .. import models, security
    import httpx
    import hmac
    import hashlib
    from datetime import datetime, timezone
    import base64
    import json

    # 1. Fetch user's OKX API keys
    stmt = select(models.ApiKey).where(
        models.ApiKey.user_id == user_id,
        models.ApiKey.exchange.in_(
            ["okx", "okx_futures", "okx_spot", "okx_usdtm", "okx_linear"]
        ),
    )
    res = await db.execute(stmt)
    api_keys = res.scalars().all()

    if not api_keys:
        return None

    for key_obj in api_keys:
        try:
            api_key = security.decrypt_data(key_obj.encrypted_api_key)
            decrypted_secret = security.decrypt_data(key_obj.encrypted_api_secret)
            api_secret = decrypted_secret
            passphrase = ""
            try:
                parsed = json.loads(decrypted_secret)
                if isinstance(parsed, dict) and "secret" in parsed:
                    api_secret = parsed["secret"]
                    passphrase = parsed.get("password", "")
            except (json.JSONDecodeError, TypeError):
                pass

            if not api_key or not api_secret:
                continue

            timestamp = (
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            )
            method = "GET"
            path = "/api/v5/account/config"
            message = f"{timestamp}{method}{path}"

            signature = hmac.new(
                api_secret.encode("utf-8"),
                message.encode("utf-8"),
                hashlib.sha256,
            ).digest()
            sign = base64.b64encode(signature).decode("utf-8")

            headers = {
                "OK-ACCESS-KEY": api_key,
                "OK-ACCESS-SIGN": sign,
                "OK-ACCESS-TIMESTAMP": timestamp,
                "OK-ACCESS-PASSPHRASE": passphrase,
                "Content-Type": "application/json",
            }

            url = f"https://www.okx.com{path}"

            async with httpx.AsyncClient(timeout=10.0) as http_client:
                resp = await http_client.get(url, headers=headers)
                if resp.status_code == 200:
                    res_json = resp.json()
                    res_data = res_json.get("data")
                    if isinstance(res_data, list) and res_data:
                        uid = res_data[0].get("uid")
                        if uid is not None:
                            uid_str = str(uid)
                            cfg_stmt = select(models.AppConfig).where(
                                models.AppConfig.user_id == user_id
                            )
                            cfg_res = await db.execute(cfg_stmt)
                            cfg = cfg_res.scalars().first()
                            if cfg:
                                settings = dict(cfg.exchange_settings or {})
                                okx_settings = settings.get("okx") or {}
                                okx_settings["okx_uid"] = uid_str
                                okx_settings["uid"] = uid_str
                                settings["okx"] = okx_settings

                                await db.execute(
                                    update(models.AppConfig)
                                    .where(models.AppConfig.user_id == user_id)
                                    .values(exchange_settings=settings)
                                )
                                await db.commit()
                                logger.info(
                                    f"[AUTO_OKX_UID] Automatically resolved and saved OKX UID {uid_str} for user ID {user_id}"
                                )
                            await sync_node_okx_uid_to_hub(db, user_id, uid_str)
                            return uid_str
        except Exception as e:
            logger.error(
                f"[AUTO_OKX_UID] Error resolving OKX UID for user {user_id}: {e}",
                exc_info=True,
            )

    return None


async def sync_node_bybit_uid_to_hub(db: AsyncSession, user_id: int, bybit_uid: str):
    """
    Finds the active mining node for this user, and sends a registration request
    to the Central Hub to update its bybit_uid. Only runs if mining is enabled and
    we are not on the Central Hub itself.
    """
    import os
    import aiohttp
    from sqlalchemy import select
    from .. import models, crud

    is_central = os.getenv("IS_CENTRAL_HUB", "false").lower() == "true"
    if is_central:
        return

    config = await crud.get_config_model(db, user_id)
    if not config or not config.is_mining_enabled:
        return

    user_stmt = select(models.User).where(models.User.id == user_id)
    user_res = await db.execute(user_stmt)
    user = user_res.scalars().first()
    if not user:
        return

    settings = dict(config.exchange_settings or {})
    bybit_settings = settings.get("bybit") or {}
    mining_node_uuid = (
        bybit_settings.get("mining_node_uuid")
        or (settings.get("weex") or {}).get("mining_node_uuid")
        or (settings.get("okx") or {}).get("mining_node_uuid")
    )
    mining_node_secret = security.decrypt_node_secret(
        bybit_settings.get("mining_node_secret")
        or (settings.get("weex") or {}).get("mining_node_secret")
        or (settings.get("okx") or {}).get("mining_node_secret")
    )

    if not mining_node_uuid or not mining_node_secret:
        from pathlib import Path
        import json

        identity_path = Path("/app/data/node_identity.json")
        if not identity_path.parent.exists():
            identity_path = Path("node_identity.json")
        if identity_path.exists():
            try:
                with open(identity_path, "r") as f:
                    data = json.load(f)
                    mining_node_uuid = data.get("node_uuid")
                    mining_node_secret = data.get("node_secret")
            except Exception:
                pass

    if not mining_node_uuid or not mining_node_secret:
        return

    hub_url = get_federation_hub_url()
    is_server_admin = user.role == "admin"
    reg_payload = {
        "node_uuid": mining_node_uuid,
        "name": f"DepthSightNode-{mining_node_uuid[:8]}",
        "node_secret": mining_node_secret,
        "version": "1.0.0",
        "referrer_code": None,
        "bybit_uid": bybit_uid,
        "is_mining_server": is_server_admin,
    }

    # Update local HubNode directly in database if present
    try:
        from sqlalchemy import update

        await db.execute(
            update(models.HubNode)
            .where(
                (models.HubNode.node_referral_code == user.referral_code)
                | (models.HubNode.node_uuid == mining_node_uuid)
            )
            .values(bybit_uid=bybit_uid)
        )
        await db.commit()
    except Exception as dbe:
        logger.debug(f"Direct HubNode bybit_uid update skipped: {dbe}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{hub_url}/nodes/register", json=reg_payload, timeout=5.0
            ) as resp:
                if resp.status in (200, 201):
                    logger.info(
                        f"Successfully synced resolved Bybit UID {bybit_uid} to Hub for node {mining_node_uuid}"
                    )
                else:
                    err_txt = await resp.text()
                    logger.warning(
                        f"Failed to sync Bybit UID to Hub. Status: {resp.status}, Response: {err_txt}"
                    )
    except Exception as e:
        logger.error(f"Error syncing Bybit UID to Hub: {e}")


async def auto_resolve_bybit_uid(db: AsyncSession, user_id: int) -> Optional[str]:
    """
    Attempts to automatically fetch the Bybit UID using the user's saved Bybit API credentials (GET /v5/user/query-api),
    and save it in exchange_settings and sync to Hub.
    """
    from sqlalchemy import select, update
    from .. import models, security
    import httpx
    import hmac
    import hashlib
    import time
    import json

    stmt = select(models.ApiKey).where(
        models.ApiKey.user_id == user_id,
        models.ApiKey.exchange.in_(
            [
                "bybit",
                "bybit_futures",
                "bybit_spot",
                "bybit_linear",
                "bybit_usdtm",
                "bybit_unified",
            ]
        ),
    )
    res = await db.execute(stmt)
    api_keys = res.scalars().all()

    if not api_keys:
        return None

    for key_obj in api_keys:
        try:
            api_key = security.decrypt_data(key_obj.encrypted_api_key)
            decrypted_secret = security.decrypt_data(key_obj.encrypted_api_secret)
            api_secret = decrypted_secret
            try:
                parsed = json.loads(decrypted_secret)
                if isinstance(parsed, dict) and "secret" in parsed:
                    api_secret = parsed["secret"]
            except (json.JSONDecodeError, TypeError):
                pass

            if not api_key or not api_secret:
                continue

            timestamp = str(int(time.time() * 1000))
            recv_window = "5000"
            raw_signature = f"{timestamp}{api_key}{recv_window}"
            signature = hmac.new(
                api_secret.encode("utf-8"),
                raw_signature.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

            headers = {
                "X-BAPI-API-KEY": api_key,
                "X-BAPI-TIMESTAMP": timestamp,
                "X-BAPI-SIGN": signature,
                "X-BAPI-RECV-WINDOW": recv_window,
                "Content-Type": "application/json",
            }

            url = "https://api.bybit.com/v5/user/query-api"

            async with httpx.AsyncClient(timeout=10.0) as http_client:
                resp = await http_client.get(url, headers=headers)
                if resp.status_code == 200:
                    res_json = resp.json()
                    if res_json.get("retCode") == 0:
                        result = res_json.get("result") or {}
                        uid = result.get("userID") or result.get("id")
                        if uid is not None:
                            uid_str = str(uid)
                            cfg_stmt = select(models.AppConfig).where(
                                models.AppConfig.user_id == user_id
                            )
                            cfg_res = await db.execute(cfg_stmt)
                            cfg = cfg_res.scalars().first()
                            if cfg:
                                settings = dict(cfg.exchange_settings or {})
                                bybit_settings = settings.get("bybit") or {}
                                bybit_settings["bybit_uid"] = uid_str
                                bybit_settings["uid"] = uid_str
                                settings["bybit"] = bybit_settings

                                await db.execute(
                                    update(models.AppConfig)
                                    .where(models.AppConfig.user_id == user_id)
                                    .values(exchange_settings=settings)
                                )
                                await db.commit()
                                logger.info(
                                    f"[AUTO_BYBIT_UID] Automatically resolved and saved Bybit UID {uid_str} for user ID {user_id}"
                                )
                            await sync_node_bybit_uid_to_hub(db, user_id, uid_str)
                            return uid_str
        except Exception as e:
            logger.error(
                f"[AUTO_BYBIT_UID] Error resolving Bybit UID for user {user_id}: {e}",
                exc_info=True,
            )

    return None


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
    if new_config.notifications:
        # Consent integrity: while Trade Mining is active (and a wallet is
        # bound) telemetry sharing is mandatory — the controller refuses to
        # dispatch trades without it. Reject the silent opt-out instead of
        # letting mining appear on while no rewards can accrue.
        if new_config.notifications.shareTelemetry is False:
            db_config = await crud.get_config_model(db, current_user.id)
            cfg_settings = dict(db_config.exchange_settings or {}) if db_config else {}
            weex_cfg = cfg_settings.get("weex") or {}
            mining_on = bool(db_config and db_config.is_mining_enabled)
            wallet_ok = bool(weex_cfg.get("wallet_configured"))
            if mining_on and wallet_ok:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Telemetry sharing is required while Trade Mining is "
                        "active. Deactivate Trade Mining first to disable it."
                    ),
                )
        await crud.update_config_section(
            db,
            current_user.id,
            "notifications",
            new_config.notifications.model_dump(by_alias=True),
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
    if new_config.risk_management:
        await crud.update_config_section(
            db,
            current_user.id,
            "risk_management",
            new_config.risk_management.model_dump(by_alias=True),
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

    if new_config.is_mining_enabled is not None:
        db_config = await crud.get_config_model(db, current_user.id)
        if db_config:
            db_config.is_mining_enabled = new_config.is_mining_enabled
            updated_any_section = True
            if new_config.is_mining_enabled:
                await auto_resolve_weex_uid(db, current_user.id)

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


async def _ensure_node_secret(
    db: AsyncSession,
    user_id: int,
    settings: Optional[dict],
    node_uuid: str,
    hub_node: models.HubNode,
) -> None:
    """
    Ensures a HubNode has a strong, non-deterministic secret bound.

    Uses the user's wallet-derived ``mining_node_secret`` when present; otherwise generates
    a cryptographically random secret and persists it in ``AppConfig.exchange_settings`` so
    the local bot can sign telemetry with the same value.
    """
    import hashlib
    import secrets

    weex_settings = dict(((settings or {}).get("weex") or {}))
    node_secret = security.decrypt_node_secret(weex_settings.get("mining_node_secret"))
    if not node_secret:
        node_secret = secrets.token_hex(32)
        weex_settings["mining_node_secret"] = security.encrypt_node_secret(node_secret)
        if not weex_settings.get("mining_node_uuid"):
            weex_settings["mining_node_uuid"] = node_uuid
        updated_settings = dict(settings or {})
        updated_settings["weex"] = weex_settings
        from sqlalchemy import update

        await db.execute(
            update(models.AppConfig)
            .where(models.AppConfig.user_id == user_id)
            .values(exchange_settings=updated_settings)
        )
        await db.commit()

    secret_hash = hashlib.sha256(node_secret.encode()).hexdigest()
    if hub_node.secret_hash != secret_hash:
        hub_node.secret_hash = secret_hash
        await db.commit()


async def format_mining_status_response(
    db: AsyncSession,
    current_user: models.User,
    is_enabled: bool,
    node_uuid: Optional[str],
    node_name: Optional[str],
    hub_data: Optional[dict],
    registered: bool,
):
    from sqlalchemy import select, func

    node_cfg_res = await db.execute(
        select(models.NodeMiningConfig).where(models.NodeMiningConfig.id == 1)
    )
    node_config = node_cfg_res.scalar_one_or_none()
    if not node_config:
        node_config = models.NodeMiningConfig(
            id=1, is_global_mining_enabled=False, user_reward_share_percent=75.0
        )
        db.add(node_config)
        await db.commit()
        await db.refresh(node_config)

    is_mining_active = is_enabled and node_config.is_global_mining_enabled

    # Safe default: 0.0 (legacy) meant 100% operator fee. Treat non-positive
    # values as the 75% user share so user rewards are never silently zeroed.
    if node_config and node_config.user_reward_share_percent > 0.0:
        share_pct = node_config.user_reward_share_percent / 100.0
    else:
        share_pct = 0.75

    import os

    is_central = os.getenv("IS_CENTRAL_HUB", "false").lower() == "true"

    from datetime import timezone
    import datetime as dt

    today = dt.datetime.now(timezone.utc).date()
    today_start = dt.datetime.combine(today, dt.time.min, tzinfo=timezone.utc)

    if is_central:
        # On the central hub the wallet-derived mining_node_uuid is the user's
        # mining identity, so volume/rebate must be read from it to match where
        # telemetry is now attributed.
        wallet_node_uuid = None
        config_model = await crud.get_config_model(db, current_user.id)
        if config_model:
            c_settings = dict(config_model.exchange_settings or {})
            wallet_node_uuid = (
                (c_settings.get("bybit") or {}).get("mining_node_uuid")
                or (c_settings.get("okx") or {}).get("mining_node_uuid")
                or (c_settings.get("weex") or {}).get("mining_node_uuid")
                or (c_settings.get("binance") or {}).get("mining_node_uuid")
                or c_settings.get("mining_node_uuid")
            )
        target_node = wallet_node_uuid
    else:
        target_node = node_uuid

    # A user with a wallet is the owner of their own mining node, so their share is
    # the full node reward (times the operator share), independent of user_ratio.
    has_subnode = False
    config_model = await crud.get_config_model(db, current_user.id)
    if config_model:
        c_settings = dict(config_model.exchange_settings or {})
        if (
            (c_settings.get("bybit") or {}).get("mining_node_uuid")
            or (c_settings.get("okx") or {}).get("mining_node_uuid")
            or (c_settings.get("weex") or {}).get("mining_node_uuid")
            or (c_settings.get("binance") or {}).get("mining_node_uuid")
            or c_settings.get("mining_node_uuid")
        ):
            has_subnode = True

    # 1. All-time volume for the user
    stmt_vol = select(func.sum(models.HubTelemetryReport.trade_volume_usdt)).where(
        models.HubTelemetryReport.node_uuid == target_node,
    )
    if is_central:
        stmt_vol = stmt_vol.where(
            models.HubTelemetryReport.is_mining_eligible.is_(True)
        )
    res_vol = await db.execute(stmt_vol)
    user_vol = float(res_vol.scalar() or 0.0)

    # 1b. Today's volume for the user (since midnight UTC)
    stmt_daily_vol = select(
        func.sum(models.HubTelemetryReport.trade_volume_usdt)
    ).where(
        models.HubTelemetryReport.node_uuid == target_node,
        models.HubTelemetryReport.created_at >= today_start,
    )
    if is_central:
        stmt_daily_vol = stmt_daily_vol.where(
            models.HubTelemetryReport.is_mining_eligible.is_(True)
        )
    res_daily_vol = await db.execute(stmt_daily_vol)
    user_daily_vol = float(res_daily_vol.scalar() or 0.0)

    # 2. Today's rebates for the user (since midnight UTC)
    stmt_rebate = select(
        func.sum(models.HubTelemetryReport.estimated_rebate_usdt)
    ).where(
        models.HubTelemetryReport.node_uuid == target_node,
        models.HubTelemetryReport.created_at >= today_start,
    )
    if is_central:
        stmt_rebate = stmt_rebate.where(
            models.HubTelemetryReport.is_mining_eligible.is_(True)
        )
    res_rebate = await db.execute(stmt_rebate)
    user_rebate = float(res_rebate.scalar() or 0.0)

    # 3. Today's volume for all nodes on this server (since midnight UTC)
    stmt_total_daily_vol = select(
        func.sum(models.HubTelemetryReport.trade_volume_usdt)
    ).where(
        models.HubTelemetryReport.created_at >= today_start,
    )
    if is_central:
        stmt_total_daily_vol = stmt_total_daily_vol.where(
            models.HubTelemetryReport.is_mining_eligible.is_(True)
        )
    res_total_daily_vol = await db.execute(stmt_total_daily_vol)
    total_daily_node_vol = float(res_total_daily_vol.scalar() or 0.0)

    # 3b. All-time volume for all nodes on this server
    stmt_total_vol = select(func.sum(models.HubTelemetryReport.trade_volume_usdt))
    if is_central:
        stmt_total_vol = stmt_total_vol.where(
            models.HubTelemetryReport.is_mining_eligible.is_(True)
        )
    res_total_vol = await db.execute(stmt_total_vol)
    total_node_vol = float(res_total_vol.scalar() or 0.0)

    # On a local node the telemetry lives on the hub, so the local DB is empty.
    # Mirror the hub's own numbers instead of showing zero volume/share.
    if not is_central and hub_data:
        if hub_data.get("yourTotalVolume") is not None:
            user_vol = float(hub_data.get("yourTotalVolume") or 0.0)
        if hub_data.get("serverTotalVolume") is not None:
            total_node_vol = float(hub_data.get("serverTotalVolume") or 0.0)
        if hub_data.get("yourEpochRebates") is not None:
            user_rebate = float(hub_data.get("yourEpochRebates") or 0.0)
        if hub_data.get("yourDailyVolume") is not None:
            user_daily_vol = float(hub_data.get("yourDailyVolume") or 0.0)
        if hub_data.get("serverDailyVolume") is not None:
            total_daily_node_vol = float(hub_data.get("serverDailyVolume") or 0.0)

    # Daily volume percentage: user's trade volume today / total trade volume today
    user_ratio = (
        (user_daily_vol / total_daily_node_vol)
        if total_daily_node_vol > 0.0
        else 0.0
    )
    if not is_central and hub_data and hub_data.get("yourVolumeShare") is not None:
        user_ratio = float(hub_data.get("yourVolumeShare") or 0.0)

    if current_user.role == "admin" and total_daily_node_vol == 0.0:
        user_ratio = 1.0 if user_daily_vol > 0.0 else 0.0

    total_node_mined = hub_data.get("yourTotalMined", 0.0) if hub_data else 0.0
    config_data = hub_data.get("config") if hub_data else None
    node_referral_code = hub_data.get("nodeReferralCode") if hub_data else None
    if node_referral_code and current_user.referral_code != node_referral_code:
        current_user.referral_code = node_referral_code
        db.add(current_user)
        await db.commit()
    referrer_node_uuid = hub_data.get("referrerNodeUuid") if hub_data else None
    has_welcome_bonus = hub_data.get("hasWelcomeBonus", False) if hub_data else False

    referrer_referral_code = None
    if current_user.referred_by_user_id:
        ref_user_stmt = select(models.User.referral_code).where(
            models.User.id == current_user.referred_by_user_id
        )
        ref_user_res = await db.execute(ref_user_stmt)
        referrer_referral_code = ref_user_res.scalar()

    if current_user.role == "admin":
        if is_central:
            stmt = select(
                models.HubTelemetryReport.node_uuid,
                func.sum(models.HubTelemetryReport.trade_volume_usdt).label(
                    "total_volume"
                ),
                func.sum(models.HubTelemetryReport.estimated_rebate_usdt).label(
                    "total_rebate"
                ),
            ).group_by(models.HubTelemetryReport.node_uuid)

            node_stats_res = await db.execute(stmt)
            user_metrics = []
            for row in node_stats_res.all():
                node_uuid = row.node_uuid
                display_name = node_uuid
                user_id = node_uuid

                hn_stmt = select(models.HubNode.name).where(
                    models.HubNode.node_uuid == node_uuid
                )
                hn_res = await db.execute(hn_stmt)
                hname = hn_res.scalar()
                if hname:
                    display_name = hname

                user_metrics.append(
                    {
                        "username": display_name,
                        "userId": user_id,
                        "tradeVolume": float(row.total_volume or 0.0),
                        "estimatedRebate": float(row.total_rebate or 0.0),
                    }
                )
        else:
            all_users_stats_res = await db.execute(
                select(models.LocalUserMiningStats, models.User.username).join(
                    models.User, models.User.id == models.LocalUserMiningStats.user_id
                )
            )
            user_metrics = []
            for r_stats, username in all_users_stats_res.all():
                user_metrics.append(
                    {
                        "username": username,
                        "userId": r_stats.user_id,
                        "tradeVolume": r_stats.total_trade_volume_usdt,
                        "estimatedRebate": r_stats.estimated_rebate_usdt,
                    }
                )

        if hub_data is None:
            hub_data = {}
        hub_data["userMetrics"] = user_metrics

        user_share_mined = total_node_mined * share_pct

        total_operator_fee = (
            hub_data.get("totalOperatorFeeCollected", 0.0) if hub_data else 0.0
        )
        if is_central:
            # Just show the node's actual base_reward from the ledger as its collected fees
            ledger_stmt = select(func.sum(models.MiningLedger.base_reward)).where(
                models.MiningLedger.node_uuid == target_node
            )
            ledger_res = await db.execute(ledger_stmt)
            total_operator_fee = float(ledger_res.scalar() or 0.0)
        else:
            total_operator_fee = total_node_mined * (1.0 - share_pct)

        hub_data["operatorFeeBalance"] = total_operator_fee
        hub_data["totalOperatorFeeCollected"] = total_operator_fee

        if is_central:
            total_all_mined_res = await db.execute(
                select(func.sum(models.HubNode.total_mined))
            )
            server_total_mined = float(total_all_mined_res.scalar() or 0.0)
        else:
            server_total_mined = total_node_mined
        hub_data["serverTotalMined"] = server_total_mined
        hub_data["totalNodeMined"] = total_node_mined

        if is_central:
            vol_res = await db.execute(
                select(func.sum(models.HubTelemetryReport.trade_volume_usdt))
            )
            server_total_vol = float(vol_res.scalar() or 0.0)
        else:
            server_total_vol = total_node_vol
        hub_data["serverTotalVolume"] = server_total_vol
        hub_data["serverDailyVolume"] = total_daily_node_vol
        hub_data["yourDailyVolume"] = user_daily_vol
        hub_data["yourVolumeShare"] = user_ratio
        hub_data["userRatio"] = user_ratio

        # For central hub wallet nodes, the user IS the node, so they get exactly what the ledger says for total mined.
        # The live estimate (your_epoch_reward) is already NET (node commission deducted
        # + referral bonus added, see estimate_live_epoch_reward), so it is shown as-is.
        # We do NOT multiply by user_ratio, because for a wallet node, user == node (ratio is always 100%).
        if is_central:
            user_share_mined = total_node_mined
            your_epoch_reward_val = float(
                hub_data.get("your_epoch_reward")
                or hub_data.get("yourEpochReward")
                or 0.0
            )
        else:
            if has_subnode:
                user_share_mined = total_node_mined
                your_epoch_reward_val = float(
                    hub_data.get("your_epoch_reward")
                    or hub_data.get("yourEpochReward")
                    or 0.0
                )
            else:
                user_share_mined = total_node_mined * share_pct * user_ratio
                # The estimate is already net of the node commission, so only the
                # user's share of the server node's volume is applied here.
                your_epoch_reward_val = (
                    float(
                        hub_data.get("your_epoch_reward")
                        or hub_data.get("yourEpochReward")
                        or 0.0
                    )
                    * user_ratio
                )

        hub_data["your_epoch_reward"] = your_epoch_reward_val
        hub_data["yourEpochReward"] = your_epoch_reward_val
        hub_data["epoch_total_rebates"] = user_rebate
        hub_data["epochTotalRebates"] = user_rebate

        return {
            "data": schemas.LocalMiningStatusResponse(
                is_mining_enabled=is_mining_active,
                node_uuid=node_uuid,
                node_name=node_name,
                registered_on_hub=registered,
                node_referral_code=current_user.referral_code,
                referrer_node_uuid=referrer_node_uuid,
                referrer_referral_code=referrer_referral_code,
                has_welcome_bonus=has_welcome_bonus,
                total_mined=user_share_mined,
                config=config_data,
                stats=hub_data,
                is_global_mining_enabled=node_config.is_global_mining_enabled,
                user_reward_share_percent=node_config.user_reward_share_percent,
                user_trade_volume=user_vol,
                user_estimated_rebate=user_rebate * share_pct,
            )
        }
    else:
        if is_central:
            user_share_mined = total_node_mined
        elif has_subnode:
            user_share_mined = total_node_mined
        else:
            user_share_mined = total_node_mined * user_ratio * share_pct

        user_stats = {}
        if hub_data:
            user_stats = hub_data.copy()
            epoch_reward = (
                hub_data.get("your_epoch_reward")
                or hub_data.get("yourEpochReward")
                or 0.0
            )
            if is_central:
                user_stats["your_epoch_reward"] = float(epoch_reward)
            elif has_subnode:
                user_stats["your_epoch_reward"] = float(epoch_reward)
            else:
                # The estimate is already net of the node commission, so only the
                # user's share of the server node's volume is applied here.
                user_stats["your_epoch_reward"] = float(epoch_reward) * user_ratio
            user_stats["yourEpochReward"] = user_stats["your_epoch_reward"]

            user_stats["epoch_total_rebates"] = user_rebate
            user_stats["epochTotalRebates"] = user_rebate

        user_stats["userRatio"] = user_ratio
        user_stats["yourVolumeShare"] = user_ratio
        user_stats["yourDailyVolume"] = user_daily_vol
        user_stats["serverDailyVolume"] = total_daily_node_vol
        user_stats["totalNodeMined"] = total_node_mined

        return {
            "data": schemas.LocalMiningStatusResponse(
                is_mining_enabled=is_mining_active,
                node_uuid=node_uuid,
                node_name=node_name,
                registered_on_hub=registered,
                node_referral_code=current_user.referral_code,
                referrer_node_uuid=referrer_node_uuid,
                referrer_referral_code=referrer_referral_code,
                has_welcome_bonus=has_welcome_bonus,
                total_mined=user_share_mined,
                config=config_data,
                stats=user_stats,
                is_global_mining_enabled=node_config.is_global_mining_enabled,
                user_reward_share_percent=node_config.user_reward_share_percent,
                user_trade_volume=user_vol,
                user_estimated_rebate=user_rebate * share_pct,
            )
        }


@config_router.get(
    "/mining/status",
    response_model=schemas.ApiResponseData[schemas.LocalMiningStatusResponse],
    summary="Get local node mining status",
)
async def get_local_mining_status(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    from pathlib import Path
    import os
    import json
    import aiohttp
    from sqlalchemy import select

    # 1. Fetch user's AppConfig to see if mining is enabled
    config = await crud.get_config_model(db, current_user.id)
    settings = dict(config.exchange_settings or {}) if config else {}
    wallet_node_uuid = (
        (settings.get("bybit") or {}).get("mining_node_uuid")
        or (settings.get("okx") or {}).get("mining_node_uuid")
        or (settings.get("weex") or {}).get("mining_node_uuid")
        or (settings.get("binance") or {}).get("mining_node_uuid")
        or settings.get("mining_node_uuid")
    )
    if not wallet_node_uuid and current_user.referral_code:
        hn_res = await db.execute(
            select(models.HubNode.node_uuid)
            .where(models.HubNode.node_referral_code == current_user.referral_code)
            .limit(1)
        )
        wallet_node_uuid = hn_res.scalar()

    wallet_configured = bool(
        (settings.get("bybit") or {}).get("wallet_configured")
        or (settings.get("okx") or {}).get("wallet_configured")
        or (settings.get("weex") or {}).get("wallet_configured")
        or (settings.get("binance") or {}).get("wallet_configured")
        or settings.get("wallet_configured")
        or (settings.get("bybit") or {}).get("wallet_address")
        or (settings.get("okx") or {}).get("wallet_address")
        or (settings.get("weex") or {}).get("wallet_address")
        or (settings.get("binance") or {}).get("wallet_address")
        or settings.get("wallet_address")
        or wallet_node_uuid
    )
    is_enabled = bool(
        (config.is_mining_enabled if config else False) and wallet_configured
    )

    # NOTE: shareTelemetry is force-enabled once at mining ACTIVATION (the
    # controller refuses to send telemetry without it). We deliberately do NOT
    # silently re-enable it here anymore: a user's explicit opt-out must stick.

    # Get node-wide config
    node_cfg_res = await db.execute(
        select(models.NodeMiningConfig).where(models.NodeMiningConfig.id == 1)
    )
    node_config = node_cfg_res.scalar_one_or_none()
    if not node_config:
        node_config = models.NodeMiningConfig(
            id=1, is_global_mining_enabled=False, user_reward_share_percent=75.0
        )
        db.add(node_config)
        await db.commit()
        await db.refresh(node_config)

    is_mining_active = is_enabled and node_config.is_global_mining_enabled

    is_central = os.getenv("IS_CENTRAL_HUB", "false").lower() == "true"
    if is_central:
        wallet_node_uuid = (
            (settings.get("bybit") or {}).get("mining_node_uuid")
            or (settings.get("okx") or {}).get("mining_node_uuid")
            or (settings.get("weex") or {}).get("mining_node_uuid")
            or (settings.get("binance") or {}).get("mining_node_uuid")
            or settings.get("mining_node_uuid")
        )
        if not wallet_node_uuid:
            return await format_mining_status_response(
                db=db,
                current_user=current_user,
                is_enabled=False,
                node_uuid=None,
                node_name=None,
                hub_data=None,
                registered=False,
            )

        # The wallet node IS the user's mining node. Look it up strictly by its uuid.
        node_uuid = wallet_node_uuid
        node_name = f"DepthSightNode-{wallet_node_uuid[:8]}"
        stmt = select(models.HubNode).where(
            models.HubNode.node_uuid == wallet_node_uuid
        )
        res = await db.execute(stmt)
        db_node = res.scalars().first()

        if db_node is None:
            referrer_node_uuid = await _resolve_safe_referrer_node_uuid(
                db, current_user, wallet_node_uuid
            )

            db_node = models.HubNode(
                node_uuid=wallet_node_uuid,
                name=node_name,
                secret_hash="",
                node_referral_code=current_user.referral_code,
                referrer_node_uuid=referrer_node_uuid,
                total_mined=0.0,
                has_welcome_bonus=False,
            )
            db.add(db_node)
            await db.commit()
            await db.refresh(db_node)
        elif not db_node.node_referral_code:
            db_node.node_referral_code = current_user.referral_code
            await db.commit()

        # Bind a strong, non-deterministic secret to the node so it can
        # authenticate telemetry.
        await _ensure_node_secret(db, current_user.id, settings, node_uuid, db_node)

        if not db_node.weex_uid:
            resolved_uid = await auto_resolve_weex_uid(db, current_user.id)
            if resolved_uid:
                db_node.weex_uid = resolved_uid

        if not db_node.bybit_uid:
            resolved_bybit = await auto_resolve_bybit_uid(db, current_user.id)
            if resolved_bybit:
                db_node.bybit_uid = resolved_bybit

        if not db_node.okx_uid:
            resolved_okx = await auto_resolve_okx_uid(db, current_user.id)
            if resolved_okx:
                db_node.okx_uid = resolved_okx

        await db.commit()

        from ..hub_router import (
            _get_active_mining_config,
            estimate_live_epoch_reward,
        )

        cfg = await _get_active_mining_config(db)

        from datetime import timezone
        import datetime as dt
        from sqlalchemy.sql import func

        today = dt.datetime.now(timezone.utc).date()

        days_since_launch = 0
        if cfg.launch_date:
            days_since_launch = max((today - cfg.launch_date).days, 0)
        halvings = days_since_launch // cfg.halving_interval_days
        daily_emission = cfg.daily_emission_base / (2**halvings)

        today_start = dt.datetime.combine(today, dt.time.min, tzinfo=timezone.utc)
        stmt_rebates = select(
            func.sum(models.HubTelemetryReport.estimated_rebate_usdt)
        ).where(
            models.HubTelemetryReport.created_at >= today_start,
            models.HubTelemetryReport.is_mining_eligible.is_(True),
        )
        res_rebates = await db.execute(stmt_rebates)
        epoch_total_rebates = float(res_rebates.scalar() or 0.0)

        stmt_nodes = select(
            func.count(func.distinct(models.HubTelemetryReport.node_uuid))
        ).where(
            models.HubTelemetryReport.created_at >= today_start,
            models.HubTelemetryReport.is_mining_eligible.is_(True),
        )
        res_nodes = await db.execute(stmt_nodes)
        participating_nodes = int(res_nodes.scalar() or 0)

        db_node_res = await db.execute(
            select(models.HubNode).where(models.HubNode.node_uuid == node_uuid)
        )
        db_node_obj = db_node_res.scalars().first()

        stmt_total_mined = select(func.sum(models.MiningLedger.total_reward)).where(
            models.MiningLedger.node_uuid == node_uuid
        )
        res_total_mined = await db.execute(stmt_total_mined)
        ledger_mined = float(res_total_mined.scalar() or 0.0)
        node_db_mined = float(db_node_obj.total_mined or 0.0) if db_node_obj else 0.0

        your_total_mined = max(ledger_mined, node_db_mined)

        # 5. Live estimate of expected daily reward for today (matches the daily
        #    MiningLedger calc: net of node commission + referral bonus).
        today_reports_stmt = select(models.HubTelemetryReport).where(
            models.HubTelemetryReport.created_at >= today_start,
            models.HubTelemetryReport.is_mining_eligible.is_(True),
        )
        today_reports_res = await db.execute(today_reports_stmt)
        today_reports = today_reports_res.scalars().all()

        your_epoch_reward = await estimate_live_epoch_reward(
            db, cfg, daily_emission, node_uuid, today_reports
        )

        hub_data = {
            "isMiningEnabled": cfg.is_mining_enabled,
            "eligibleExchanges": cfg.eligible_exchanges,
            "rebateRates": cfg.rebate_rates or {},
            "currentEpochDate": today.isoformat(),
            "dailyEmission": daily_emission,
            "yourTotalMined": your_total_mined,
            "yourEpochReward": your_epoch_reward,
            "epochTotalRebates": epoch_total_rebates,
            "participatingNodes": participating_nodes,
            "nodeReferralCode": db_node.node_referral_code,
            "referrerNodeUuid": db_node.referrer_node_uuid,
            "hasWelcomeBonus": db_node.has_welcome_bonus,
        }

        return await format_mining_status_response(
            db=db,
            current_user=current_user,
            is_enabled=is_enabled,
            node_uuid=node_uuid,
            node_name=node_name,
            hub_data=hub_data,
            registered=True,
        )

    # 2. Check if user has a configured Web3 wallet first, else fallback to node_identity.json
    node_uuid = None
    node_secret = None
    node_name = None

    if config:
        settings = dict(config.exchange_settings or {})
        node_uuid = (
            (settings.get("bybit") or {}).get("mining_node_uuid")
            or (settings.get("okx") or {}).get("mining_node_uuid")
            or (settings.get("weex") or {}).get("mining_node_uuid")
            or (settings.get("binance") or {}).get("mining_node_uuid")
            or settings.get("mining_node_uuid")
        )
        if node_uuid:
            raw_sec = (
                (settings.get("bybit") or {}).get("mining_node_secret")
                or (settings.get("okx") or {}).get("mining_node_secret")
                or (settings.get("weex") or {}).get("mining_node_secret")
                or (settings.get("binance") or {}).get("mining_node_secret")
                or settings.get("mining_node_secret")
            )
            node_secret = security.decrypt_node_secret(raw_sec)
            ref_suf = node_uuid[:6].lower()
            node_name = f"DepthSightNode-{ref_suf}"

    if not node_uuid:
        identity_path = Path("/app/data/node_identity.json")
        if not identity_path.parent.exists():
            identity_path = Path("node_identity.json")

        if identity_path.exists():
            try:
                with open(identity_path, "r") as f:
                    data = json.load(f)
                    node_uuid = data.get("node_uuid")
                    node_secret = data.get("node_secret")
                    node_name = data.get("node_name")
            except Exception:
                pass

    request_node_uuid = node_uuid

    # 3. If mining is not enabled or identity doesn't exist, return disabled status
    if not is_mining_active or not node_uuid or not node_secret:
        return await format_mining_status_response(
            db=db,
            current_user=current_user,
            is_enabled=is_mining_active,
            node_uuid=request_node_uuid,
            node_name=node_name,
            hub_data=None,
            registered=False,
        )

    # 4. Query central hub for actual mining statistics
    hub_url = get_federation_hub_url()
    hub_url = hub_url.rstrip("/")

    headers = {
        "X-Node-UUID": request_node_uuid,
        "X-Node-Secret": node_secret,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{hub_url}/mining/status", headers=headers, timeout=5.0
            ) as resp:
                if resp.status == 200:
                    hub_data = await resp.json()
                    return await format_mining_status_response(
                        db=db,
                        current_user=current_user,
                        is_enabled=True,
                        node_uuid=request_node_uuid,
                        node_name=node_name,
                        hub_data=hub_data,
                        registered=True,
                    )
                else:
                    logger.warning(
                        f"Hub returned status {resp.status} for mining status check."
                    )
    except Exception as e:
        logger.error(f"Error checking mining status on Hub: {e}")

    # Fallback if Hub is unreachable but node has registered
    return await format_mining_status_response(
        db=db,
        current_user=current_user,
        is_enabled=True,
        node_uuid=request_node_uuid,
        node_name=node_name,
        hub_data=None,
        registered=True,
    )


async def _resolve_proxy_node_identity(
    db: AsyncSession, current_user: models.User
) -> tuple:
    """
    Resolves the node identity used to proxy mining queries to the Central Hub.

    Prefers the wallet-derived ``mining_node_uuid``/``mining_node_secret``, which follows
    the user across servers, falling back to ``node_identity.json`` for physical nodes
    without a configured wallet.
    """
    from pathlib import Path
    import json

    config = await crud.get_config_model(db, current_user.id)
    if config:
        settings = dict(config.exchange_settings or {})
        for ex_key in ("bybit", "okx", "weex", "binance", None):
            d = settings.get(ex_key) if ex_key else settings
            if isinstance(d, dict) and d.get("mining_node_uuid"):
                node_uuid = d.get("mining_node_uuid")
                raw_sec = d.get("mining_node_secret")
                if raw_sec:
                    node_secret = security.decrypt_node_secret(raw_sec)
                    if node_uuid and node_secret:
                        return node_uuid, node_secret

    for identity_path in (
        Path("/app/data/node_identity.json"),
        Path("data/node_identity.json"),
        Path("node_identity.json"),
    ):
        if identity_path.exists():
            try:
                with open(identity_path, "r") as f:
                    data = json.load(f)
                    node_uuid = data.get("node_uuid")
                    node_secret = data.get("node_secret")
                    if node_uuid and node_secret:
                        return node_uuid, node_secret
            except Exception:
                continue
    return None, None


@config_router.get(
    "/mining/referrals",
    summary="Get mining referrals list for node user",
)
async def get_local_mining_referrals(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    import os
    import aiohttp

    is_central = os.getenv("IS_CENTRAL_HUB", "false").lower() == "true"
    if is_central:
        from ..hub_router import get_mining_referrals_impl

        return await get_mining_referrals_impl(db=db, current_user_obj=current_user)

    hub_url = get_federation_hub_url()

    node_uuid, node_secret = await _resolve_proxy_node_identity(db, current_user)
    if not node_uuid or not node_secret:
        return {
            "total_invited": 0,
            "active_referrals": 0,
            "total_referral_rewards_depth": 0.0,
            "total_referral_volume_usdt": 0.0,
            "referrals": [],
        }

    headers = {"X-Node-UUID": node_uuid, "X-Node-Secret": node_secret}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{hub_url}/mining/referrals", headers=headers, timeout=5.0
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        logger.error(f"Error fetching referrals from Hub: {e}")

    return {
        "total_invited": 0,
        "active_referrals": 0,
        "total_referral_rewards_depth": 0.0,
        "total_referral_volume_usdt": 0.0,
        "referrals": [],
    }


@config_router.get(
    "/mining/trades",
    summary="Get paginated telemetry trades list with filters",
)
async def get_local_mining_trades(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    exchange: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    scope: Optional[str] = Query("all"),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    import os
    import aiohttp
    from sqlalchemy import select, func, or_
    import math

    is_central = os.getenv("IS_CENTRAL_HUB", "false").lower() == "true"

    # For non-central nodes, proxy to the Central Hub
    if not is_central:
        hub_url = get_federation_hub_url()

        node_uuid, node_secret = await _resolve_proxy_node_identity(db, current_user)

        if node_uuid and node_secret:
            headers = {"X-Node-UUID": node_uuid, "X-Node-Secret": node_secret}
            params = {"page": page, "limit": limit}
            if status and status.upper() != "ALL":
                params["status_filter"] = status
            if exchange and exchange.lower() != "all":
                params["exchange"] = exchange
            if search:
                params["search"] = search
            if scope and scope.lower() != "all":
                params["scope"] = scope.lower()

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{hub_url}/mining/node-trades",
                        headers=headers,
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status == 200:
                            return await resp.json()
            except Exception as e:
                logger.error(f"Error fetching trades from Hub: {e}")

        # Fallback: return empty response
        return {
            "total": 0,
            "page": page,
            "limit": limit,
            "totalPages": 0,
            "items": [],
        }

    # --- Central Hub: query local database directly ---
    my_node_uuids = []
    user_node_stmt = select(models.HubNode.node_uuid).where(
        models.HubNode.node_referral_code == current_user.referral_code
    )
    user_node_res = await db.execute(user_node_stmt)
    for nuuid in user_node_res.scalars().all():
        if nuuid not in my_node_uuids:
            my_node_uuids.append(nuuid)

    cfg = await crud.get_config_model(db, current_user.id)
    if cfg and cfg.exchange_settings:
        c_settings = dict(cfg.exchange_settings)
        w_uuid = (
            (c_settings.get("bybit") or {}).get("mining_node_uuid")
            or (c_settings.get("okx") or {}).get("mining_node_uuid")
            or (c_settings.get("weex") or {}).get("mining_node_uuid")
            or (c_settings.get("binance") or {}).get("mining_node_uuid")
            or c_settings.get("mining_node_uuid")
        )
        if w_uuid and w_uuid not in my_node_uuids:
            my_node_uuids.append(w_uuid)

    referral_node_uuids = []
    ref_users_stmt = select(models.User).where(
        models.User.referred_by_user_id == current_user.id
    )
    ref_users_res = await db.execute(ref_users_stmt)
    ref_users = ref_users_res.scalars().all()
    for ru in ref_users:
        r_node_stmt = select(models.HubNode.node_uuid).where(
            models.HubNode.node_referral_code == ru.referral_code
        )
        r_node_res = await db.execute(r_node_stmt)
        for rnuuid in r_node_res.scalars().all():
            if rnuuid not in referral_node_uuids and rnuuid not in my_node_uuids:
                referral_node_uuids.append(rnuuid)

    remote_nodes_stmt = select(models.HubNode.node_uuid).where(
        models.HubNode.referrer_node_uuid.in_(my_node_uuids)
    )
    remote_nodes_res = await db.execute(remote_nodes_stmt)
    for rnuuid in remote_nodes_res.scalars().all():
        if rnuuid not in referral_node_uuids and rnuuid not in my_node_uuids:
            referral_node_uuids.append(rnuuid)

    stmt = select(models.HubTelemetryReport)
    filters = []

    if user_id:
        target_node_uuids = []
        ref_user_stmt = select(models.User).where(models.User.id == user_id)
        ref_user_res = await db.execute(ref_user_stmt)
        target_user = ref_user_res.scalars().first()
        if target_user:
            t_node_stmt = select(models.HubNode.node_uuid).where(
                models.HubNode.node_referral_code == target_user.referral_code
            )
            t_node_res = await db.execute(t_node_stmt)
            for nuuid in t_node_res.scalars().all():
                if nuuid not in target_node_uuids:
                    target_node_uuids.append(nuuid)
        filters.append(
            models.HubTelemetryReport.node_uuid.in_(target_node_uuids or ["none"])
        )
    elif scope and scope.lower() == "my":
        filters.append(
            models.HubTelemetryReport.node_uuid.in_(my_node_uuids or ["none"])
        )
    elif scope and scope.lower() == "referrals":
        filters.append(
            models.HubTelemetryReport.node_uuid.in_(referral_node_uuids or ["none"])
        )
    else:
        all_uuids = list(set(my_node_uuids + referral_node_uuids))
        filters.append(models.HubTelemetryReport.node_uuid.in_(all_uuids or ["none"]))

    if status and status.upper() != "ALL":
        filters.append(models.HubTelemetryReport.verification_status == status.upper())

    if exchange and exchange.lower() != "all":
        filters.append(
            func.lower(models.HubTelemetryReport.exchange_id) == exchange.lower()
        )

    if search:
        search_str = search.strip()
        search_pattern = f"%{search_str}%"

        # Find matching users to include their node_uuids in search filter
        matching_user_stmt = select(models.User.id, models.User.referral_code).where(
            or_(
                models.User.username.ilike(search_pattern),
                models.User.email.ilike(search_pattern),
            )
        )
        m_users_res = await db.execute(matching_user_stmt)
        matching_users = m_users_res.all()

        matching_node_uuids = []
        for m_uid, m_ref_code in matching_users:
            if m_ref_code:
                mn_stmt = select(models.HubNode.node_uuid).where(
                    models.HubNode.node_referral_code == m_ref_code
                )
                mn_res = await db.execute(mn_stmt)
                for m_nuuid in mn_res.scalars().all():
                    matching_node_uuids.append(m_nuuid)

        search_or_conditions = [
            models.HubTelemetryReport.symbol.ilike(search_pattern),
            models.HubTelemetryReport.broker_trade_id.ilike(search_pattern),
            models.HubTelemetryReport.node_uuid.ilike(search_pattern),
        ]
        if matching_node_uuids:
            search_or_conditions.append(
                models.HubTelemetryReport.node_uuid.in_(matching_node_uuids)
            )

        filters.append(or_(*search_or_conditions))

    if filters:
        stmt = stmt.where(*filters)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_res = await db.execute(count_stmt)
    total_count = count_res.scalar() or 0

    offset = (page - 1) * limit
    stmt = (
        stmt.order_by(models.HubTelemetryReport.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    res = await db.execute(stmt)
    reports = res.scalars().all()

    node_uuids = {r.node_uuid for r in reports if r.node_uuid}
    user_map = {}
    if node_uuids:
        # Step 1: Resolve HubNode.node_referral_code -> User.referral_code
        n_stmt = (
            select(
                models.HubNode.node_uuid,
                models.User.id,
                models.User.username,
                models.User.email,
            )
            .join(
                models.User,
                models.User.referral_code == models.HubNode.node_referral_code,
            )
            .where(models.HubNode.node_uuid.in_(node_uuids))
        )
        n_res = await db.execute(n_stmt)
        for nuuid, uid, uname, uemail in n_res.all():
            display_name = uname or (uemail.split("@")[0] if uemail else f"User-{uid}")
            user_map[nuuid] = (uid, display_name)

        # Step 2: For unresolved node_uuids, fall back to the HubNode name.
        unresolved = [nu for nu in node_uuids if nu not in user_map]
        if unresolved:
            hn_stmt = select(models.HubNode).where(
                models.HubNode.node_uuid.in_(unresolved)
            )
            hn_res = await db.execute(hn_stmt)
            for hn in hn_res.scalars().all():
                if hn.name:
                    user_map[hn.node_uuid] = (None, hn.name)

    items = []
    for r in reports:
        u_info = user_map.get(r.node_uuid)
        is_own = bool(
            (r.node_uuid in my_node_uuids) or (u_info and u_info[0] == current_user.id)
        )
        items.append(
            schemas.MiningTradeItem(
                id=r.id,
                user_id=u_info[0] if u_info else None,
                username=u_info[1] if u_info else (r.node_uuid or ""),
                node_uuid=r.node_uuid or "",
                is_own_trade=is_own,
                symbol=r.symbol,
                direction=r.direction,
                exchange_id=r.exchange_id,
                market_type=r.market_type,
                trade_volume_usdt=r.trade_volume_usdt or 0.0,
                verification_status=r.verification_status or "PENDING",
                verification_error=r.verification_error,
                verified_volume_usdt=r.verified_volume_usdt,
                is_mining_eligible=bool(r.is_mining_eligible),
                score=r.score,
                reward_tokens=r.reward_tokens or 0.0,
                created_at=r.created_at.isoformat() if r.created_at else "",
            )
        )

    total_pages = math.ceil(total_count / limit) if limit > 0 else 1

    return schemas.MiningTradesResponse(
        total=total_count,
        page=page,
        limit=limit,
        total_pages=total_pages,
        items=items,
    )


@config_router.post(
    "/node/wallet/nonce",
    response_model=schemas.ApiResponseData[schemas.WalletNonceResponse],
    summary="Generate a signable SIWE nonce for EVM wallet authentication",
)
async def generate_evm_wallet_nonce(
    payload: schemas.WalletNoncePayload,
    current_user: models.User = Depends(get_current_user),
):
    from ..wallet_auth import build_ownership_message

    if (
        not payload.address
        or not payload.address.startswith("0x")
        or len(payload.address) != 42
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid EVM wallet address format. Must start with 0x and be 42 chars long.",
        )

    # The signable message is a self-verifying ownership authorization: it embeds
    # the wallet address, purpose and an absolute expiry. The signature over it can
    # be verified by the local node AND by the hub (forwarded during registration)
    # without shared nonce state, and survives multiple uvicorn workers.
    message = build_ownership_message(payload.address)
    return {"data": {"nonce": message, "message": message}}


async def _resolve_safe_referrer_node_uuid(
    db: AsyncSession, current_user: models.User, node_uuid: str
) -> Optional[str]:
    """
    Resolves the platform referrer's mining node uuid for the given user's node.

    Refuses links that would close a referral cycle (A -> B -> ... -> A): such
    rings let one entity farm the referral bonus on its own volume and dilute
    honest nodes' share of the fixed daily emission. Mirrors the cycle guard
    already enforced by the hub's _bind_referrer_once.
    """
    if not current_user.referred_by_user_id:
        return None
    from sqlalchemy import select as _select

    ref_user_stmt = _select(models.User).where(
        models.User.id == current_user.referred_by_user_id
    )
    ref_user_res = await db.execute(ref_user_stmt)
    ref_user_obj = ref_user_res.scalars().first()
    if not ref_user_obj:
        return None
    ref_node_stmt = _select(models.HubNode.node_uuid).where(
        models.HubNode.node_referral_code == ref_user_obj.referral_code
    )
    candidate = (await db.execute(ref_node_stmt)).scalar()
    if not candidate or candidate == node_uuid:
        return None
    if await crud.referrer_link_creates_cycle(db, node_uuid, candidate):
        logger.warning(
            "[MINING] Rejected cyclic referral link %s -> %s", candidate, node_uuid
        )
        return None
    return candidate


async def _transfer_node_data(db: AsyncSession, src_uuid: str, dst_uuid: str) -> None:
    """Migrates telemetry, ledger, total_mined, and referral links from src_uuid to dst_uuid."""
    from sqlalchemy import select, update, delete

    if not src_uuid or not dst_uuid or src_uuid == dst_uuid:
        return

    src_res = await db.execute(
        select(models.HubNode).where(models.HubNode.node_uuid == src_uuid)
    )
    src = src_res.scalars().first()
    dst_res = await db.execute(
        select(models.HubNode).where(models.HubNode.node_uuid == dst_uuid)
    )
    dst = dst_res.scalars().first()

    if not dst:
        dst = models.HubNode(
            node_uuid=dst_uuid,
            name=f"DepthSightNode-{dst_uuid[:6]}",
            secret_hash=src.secret_hash if src else "",
            total_mined=0.0,
            has_welcome_bonus=False,
        )
        db.add(dst)
        await db.flush()

    # Move Telemetry Reports
    dup_stmt = select(models.HubTelemetryReport.broker_trade_id).where(
        models.HubTelemetryReport.node_uuid == src_uuid,
        models.HubTelemetryReport.broker_trade_id.is_not(None),
    )
    dup_ids = set((await db.execute(dup_stmt)).scalars().all())
    if dup_ids:
        await db.execute(
            delete(models.HubTelemetryReport).where(
                models.HubTelemetryReport.node_uuid == dst_uuid,
                models.HubTelemetryReport.broker_trade_id.in_(dup_ids),
            )
        )

    await db.execute(
        update(models.HubTelemetryReport)
        .where(models.HubTelemetryReport.node_uuid == src_uuid)
        .values(node_uuid=dst_uuid)
    )
    # Keep per-server commission history consistent as well: reports mined
    # THROUGH the old node must keep attributing their operator fee to the
    # destination identity, otherwise the fee trail dangles on the old uuid.
    await db.execute(
        update(models.HubTelemetryReport)
        .where(models.HubTelemetryReport.source_node_uuid == src_uuid)
        .values(source_node_uuid=dst_uuid)
    )

    # Move Mining Ledger entries
    src_ledgers = (
        (
            await db.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == src_uuid
                )
            )
        )
        .scalars()
        .all()
    )

    for led in src_ledgers:
        existing = (
            await db.execute(
                select(models.MiningLedger).where(
                    models.MiningLedger.node_uuid == dst_uuid,
                    models.MiningLedger.epoch_date == led.epoch_date,
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.base_reward += led.base_reward or 0.0
            existing.referral_bonus += led.referral_bonus or 0.0
            existing.welcome_bonus += led.welcome_bonus or 0.0
            existing.total_reward += led.total_reward or 0.0
            existing.total_rebate_usdt += led.total_rebate_usdt or 0.0
            existing.verified_trades_count += led.verified_trades_count or 0
            # Keep the strongest boost of the two entries instead of silently
            # dropping the incoming multiplier.
            existing.boost_multiplier = max(
                existing.boost_multiplier or 1.0, led.boost_multiplier or 1.0
            )
            await db.delete(led)
        else:
            led.node_uuid = dst_uuid

    if src:
        if not dst.weex_uid and src.weex_uid:
            dst.weex_uid = src.weex_uid
        if not dst.has_welcome_bonus and src.has_welcome_bonus:
            dst.has_welcome_bonus = True
        dst.total_mined = (dst.total_mined or 0.0) + (src.total_mined or 0.0)
        if not dst.node_referral_code and src.node_referral_code:
            ref_code = src.node_referral_code
            src.node_referral_code = None
            await db.flush()
            dst.node_referral_code = ref_code
        src.total_mined = 0.0

    await db.execute(
        update(models.HubNode)
        .where(models.HubNode.referrer_node_uuid == src_uuid)
        .values(referrer_node_uuid=dst_uuid)
    )


@config_router.post(
    "/node/wallet/verify",
    response_model=schemas.ApiResponseData[schemas.WalletVerifyResponse],
    summary="Verify EVM wallet signature and bind wallet identity to node",
)
async def verify_evm_wallet_signature(
    payload: schemas.WalletVerifyPayload,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    from sqlalchemy import select, update
    import uuid
    import secrets
    import os
    import time as _time
    from ..crud import claim_ownership_message
    from ..wallet_auth import (
        verify_ownership_signature,
        verify_wallet_signature,
        ownership_message_hash,
        OWNERSHIP_PURPOSE_BIND,
        OWNERSHIP_AUTH_TTL_SECONDS,
    )

    clean_addr = payload.address.strip().lower()
    # When running as the central hub there is no upstream to forward to, so the
    # signed message is consumed HERE. On regular nodes the hub consumes it
    # during the forwarded /nodes/register call (single authoritative claim per
    # message; avoids double-consume where local and hub share one database).
    is_central_hub = os.getenv("IS_CENTRAL_HUB", "false").lower() == "true"

    if payload.message:
        # Self-verifying ownership message: no shared nonce state, safe across workers
        # and the SAME signature proves ownership to the hub during registration.
        if not verify_ownership_signature(
            clean_addr,
            payload.signature,
            payload.message,
            purpose=OWNERSHIP_PURPOSE_BIND,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid EVM signature or expired message. Please re-connect wallet and try again.",
            )
        # Single-use replay protection (hub mode only, see above).
        if is_central_hub and not await claim_ownership_message(
            db,
            ownership_message_hash(payload.message),
            int(_time.time()) + OWNERSHIP_AUTH_TTL_SECONDS,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="This authorization signature has already been used. Please re-connect wallet and try again.",
            )
        owner_message = payload.message
        owner_signature = payload.signature
    else:
        # Legacy nonce-based flow (kept for older frontends).
        if not verify_wallet_signature(clean_addr, payload.signature, payload.nonce):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid EVM signature or expired nonce. Please re-connect wallet and try again.",
            )
        # The legacy nonce cache is in-process, so with multiple uvicorn
        # workers a consumed nonce could still be replayed on another worker.
        # Route it through the same single-use registry as ownership messages.
        import hashlib as _hashlib

        if not await claim_ownership_message(
            db,
            _hashlib.sha256(payload.nonce.encode("utf-8")).hexdigest(),
            int(_time.time()) + OWNERSHIP_AUTH_TTL_SECONDS,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="This authorization has already been used. Please re-connect wallet and try again.",
            )
        owner_message = None
        owner_signature = None

    # Derive deterministic UUIDv5 for the EVM wallet address
    node_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"evm:{clean_addr}"))

    config = await crud.get_config_model(db, current_user.id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User configuration not found.",
        )

    settings = dict(config.exchange_settings or {})
    weex_settings = dict(settings.get("weex") or {})

    # Capture existing node uuids to transfer legacy data onto the new EVM node
    previous_mining_uuid = weex_settings.get("mining_node_uuid")
    virtual_user_uuid = f"virtual-{current_user.id}"

    # Perform data migration from old node_uuids to new EVM node_uuid
    if previous_mining_uuid and previous_mining_uuid != node_uuid:
        await _transfer_node_data(db, previous_mining_uuid, node_uuid)
    if virtual_user_uuid != node_uuid:
        await _transfer_node_data(db, virtual_user_uuid, node_uuid)

    # Check if this EVM address is already bound to another HubNode/user
    existing_wallet_stmt = select(models.HubNode).where(
        models.HubNode.wallet_address == clean_addr
    )
    existing_res = await db.execute(existing_wallet_stmt)
    existing_node = existing_res.scalars().first()

    if existing_node and existing_node.node_uuid != node_uuid:
        # SEMANTICS (documented, intentional): the EVM wallet IS the owner.
        # When a second platform account binds the same wallet it joins the
        # SAME mining node — its referral code is synced to the node's code
        # further below. We log the event for auditability; no data is split.
        other_user_stmt = select(models.User).where(
            models.User.referral_code == existing_node.node_referral_code,
            models.User.id != current_user.id,
        )
        other_user = (await db.execute(other_user_stmt)).scalars().first()
        if other_user:
            logger.warning(
                "[MINING] Wallet %s re-bound by account '%s' while already "
                "owned via node %s (account '%s'). Referral code synced.",
                clean_addr,
                current_user.username,
                existing_node.node_uuid,
                other_user.username,
            )

    node_secret = security.decrypt_node_secret(
        weex_settings.get("mining_node_secret")
    ) or secrets.token_hex(32)

    weex_settings["mining_node_uuid"] = node_uuid
    weex_settings["mining_node_secret"] = security.encrypt_node_secret(node_secret)
    weex_settings["wallet_address"] = clean_addr
    weex_settings["wallet_configured"] = True
    # PURGE any legacy mnemonic
    weex_settings.pop("mnemonic", None)
    settings["weex"] = weex_settings
    settings["mining_node_uuid"] = node_uuid
    settings["mining_node_secret"] = security.encrypt_node_secret(node_secret)
    settings["wallet_address"] = clean_addr
    settings["wallet_configured"] = True

    ref_suffix = clean_addr[-6:].upper()
    # SECURITY: the referral code is shared publicly, so it must never embed
    # bits of the node secret. Use random public noise instead (same scheme the
    # hub uses); the code is stored on the node and stays stable afterwards.
    for _attempt in range(3):
        node_ref_code = f"DSN-REF-{ref_suffix}-{secrets.token_hex(3)[:4].upper()}"
        _code_taken = (
            await db.execute(
                select(models.HubNode.node_uuid).where(
                    models.HubNode.node_referral_code == node_ref_code
                )
            )
        ).scalar_one_or_none()
        if _code_taken is None:
            break
    node_name = f"DepthSightNode-{clean_addr[:6]}...{clean_addr[-4:]}"

    # Search existing HubNode by wallet_address or node_uuid or referral code
    stmt_hn = select(models.HubNode).where(
        (models.HubNode.wallet_address == clean_addr)
        | (models.HubNode.node_uuid == node_uuid)
        | (models.HubNode.node_referral_code == current_user.referral_code)
    )
    res_hn = await db.execute(stmt_hn)
    db_node = res_hn.scalars().first()

    if not db_node:
        referrer_node_uuid = await _resolve_safe_referrer_node_uuid(
            db, current_user, node_uuid
        )

        db_node = models.HubNode(
            node_uuid=node_uuid,
            name=node_name,
            secret_hash="",
            node_referral_code=node_ref_code,
            referrer_node_uuid=referrer_node_uuid,
            total_mined=0.0,
            has_welcome_bonus=False,
            wallet_address=clean_addr,
        )
        db.add(db_node)
        # Brand-new node: its referral code becomes the user's mining referral code.
        current_user.referral_code = node_ref_code
    else:
        db_node.wallet_address = clean_addr

        async def _safe_adopt_code(target_code: str) -> None:
            """Adopts the node's referral code unless ANOTHER platform account
            already holds it (users.referral_code is UNIQUE). A second account
            binding the same wallet keeps its own code — mining still follows
            the shared wallet node; only the code identity stays separate."""
            holder = (
                await db.execute(
                    select(models.User.id).where(
                        models.User.referral_code == target_code,
                        models.User.id != current_user.id,
                    )
                )
            ).scalar_one_or_none()
            if holder is not None:
                logger.warning(
                    "[MINING] Referral code %s is held by account id=%s; "
                    "account '%s' keeps its own code after wallet bind.",
                    target_code,
                    holder,
                    current_user.username,
                )
                return
            current_user.referral_code = target_code

        if not db_node.node_referral_code:
            db_node.node_referral_code = node_ref_code
            await _safe_adopt_code(node_ref_code)
        elif current_user.referral_code != db_node.node_referral_code:
            # Keep the user's referral code in sync with the node's existing code
            # instead of fabricating a new one on a re-bind / cross-server transfer.
            await _safe_adopt_code(db_node.node_referral_code)
    db.add(current_user)

    await _ensure_node_secret(db, current_user.id, settings, node_uuid, db_node)

    await db.execute(
        update(models.AppConfig)
        .where(models.AppConfig.user_id == current_user.id)
        .values(exchange_settings=settings, is_mining_enabled=True)
    )
    await db.commit()

    # On a local node, register the wallet-bound mining node with the hub using the
    # ownership signature just verified. This creates the node (preventing
    # pre-registration hijack), rotates the telemetry secret and, for the server
    # admin, flags it as a mining server and binds the referrer вЂ” all wallet-owned.
    hub_ref_code = None
    hub_reg_error = None
    if os.getenv("IS_CENTRAL_HUB", "false").lower() != "true" and owner_signature:
        try:
            from pathlib import Path
            import aiohttp

            is_server_admin = current_user.role == "admin"
            share_pct = None
            try:
                from ..depthsight_api import _get_local_share_percent

                share_pct = await _get_local_share_percent()
            except Exception:
                share_pct = None
            hub_url = get_federation_hub_url()
            hub_payload = {
                "node_uuid": node_uuid,
                "name": f"DepthSightNode-{node_uuid[:8]}",
                "node_secret": node_secret,
                "version": "1.0.0",
                "referrer_code": payload.referrer_code,
                "is_mining_server": is_server_admin,
                "user_reward_share_percent": share_pct,
                "wallet_address": clean_addr,
                "owner_signature": owner_signature,
                "owner_message": owner_message,
                # Optional Bybit/OKX account binding used by the broker verifier
                "bybit_uid": ((settings.get("bybit") or {}).get("uid")) or None,
                "okx_uid": ((settings.get("okx") or {}).get("uid")) or None,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{hub_url}/nodes/register",
                    json=hub_payload,
                    timeout=10.0,
                ) as resp:
                    if resp.status in (200, 201):
                        try:
                            resp_body = await resp.json()
                        except Exception:
                            resp_body = None
                        if isinstance(resp_body, dict):
                            hub_ref_code = resp_body.get("node_referral_code")
                        logger.info(
                            f"Wallet node {node_uuid} registered on hub after wallet bind."
                        )
                        if is_server_admin:
                            srv_identity_path = Path("/app/data/server_identity.json")
                            if not srv_identity_path.parent.exists():
                                srv_identity_path = Path("server_identity.json")
                            try:
                                with open(srv_identity_path, "w") as f:
                                    json.dump(
                                        {
                                            "node_uuid": node_uuid,
                                            "node_secret": node_secret,
                                        },
                                        f,
                                    )
                            except Exception as e:
                                logger.error(
                                    f"Failed to write server identity file: {e}"
                                )
                    else:
                        err_text = await resp.text()
                        logger.error(
                            f"Hub rejected wallet node registration. Status: {resp.status}, Body: {err_text}"
                        )
                        hub_reg_error = (
                            f"Hub registration failed ({resp.status}): {err_text}"
                        )
        except Exception as e:
            logger.error(f"Failed to register wallet node on hub: {e}", exc_info=True)
            hub_reg_error = f"Hub connection error: {e}"

    # The hub is the authority for a wallet-bound node: its referral code follows
    # the wallet across servers. On a transfer the hub returns the code of the
    # existing node; use it instead of any locally-generated one so the local UI
    # shows the original code (and mining history keeps resolving to this node).
    if hub_ref_code:
        changed = False
        if db_node.node_referral_code != hub_ref_code:
            db_node.node_referral_code = hub_ref_code
            changed = True
        if current_user.referral_code != hub_ref_code:
            current_user.referral_code = hub_ref_code
            changed = True
        if changed:
            db.add(db_node)
            db.add(current_user)
            try:
                from sqlalchemy.exc import IntegrityError

                await db.commit()
            except IntegrityError:
                logger.warning(
                    f"Could not adopt hub referral code {hub_ref_code} for user "
                    f"{current_user.id}: unique constraint violated. Keeping existing code."
                )
                await db.rollback()

    response_data = {
        "walletAddress": clean_addr,
        "nodeUuid": node_uuid,
        "status": "ok",
    }
    if hub_reg_error:
        response_data["hubRegistrationError"] = hub_reg_error
    return {"data": response_data}


@config_router.get(
    "/node/wallet/status",
    response_model=schemas.ApiResponseData[schemas.WalletStatusResponse],
    summary="Get EVM wallet configuration status for user",
)
async def get_evm_wallet_status(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    config = await crud.get_config_model(db, current_user.id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User configuration not found.",
        )
    settings = dict(config.exchange_settings or {})
    wallet_address = (
        (settings.get("bybit") or {}).get("wallet_address")
        or (settings.get("okx") or {}).get("wallet_address")
        or (settings.get("weex") or {}).get("wallet_address")
        or (settings.get("binance") or {}).get("wallet_address")
        or settings.get("wallet_address")
    )
    node_uuid = (
        (settings.get("bybit") or {}).get("mining_node_uuid")
        or (settings.get("okx") or {}).get("mining_node_uuid")
        or (settings.get("weex") or {}).get("mining_node_uuid")
        or (settings.get("binance") or {}).get("mining_node_uuid")
        or settings.get("mining_node_uuid")
    )
    wallet_configured = (
        (settings.get("bybit") or {}).get("wallet_configured", False)
        or (settings.get("okx") or {}).get("wallet_configured", False)
        or (settings.get("weex") or {}).get("wallet_configured", False)
        or (settings.get("binance") or {}).get("wallet_configured", False)
        or settings.get("wallet_configured", False)
    )

    return {
        "data": {
            "walletAddress": wallet_address,
            "nodeUuid": node_uuid,
            "walletConfigured": wallet_configured,
        }
    }


@config_router.post(
    "/node/wallet/disconnect",
    summary="Disconnect EVM wallet from node",
)
async def disconnect_evm_wallet(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    from sqlalchemy import update

    config = await crud.get_config_model(db, current_user.id)
    if config and config.exchange_settings:
        settings = dict(config.exchange_settings)
        weex_settings = dict(settings.get("weex") or {})
        weex_settings.pop("wallet_address", None)
        weex_settings["wallet_configured"] = False
        settings["weex"] = weex_settings

        await db.execute(
            update(models.AppConfig)
            .where(models.AppConfig.user_id == current_user.id)
            .values(exchange_settings=settings)
        )
        await db.commit()

    return {"data": {"success": True}}


@config_router.post(
    "/mining/activate",
    response_model=schemas.ApiResponseData[schemas.LocalMiningStatusResponse],
    summary="Activate local node mining and link referral code",
)
async def activate_local_mining(
    payload: schemas.MiningActivatePayload,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    from pathlib import Path
    import os
    import json
    import aiohttp
    from sqlalchemy import select
    import uuid
    import secrets

    config = await crud.get_config_model(db, current_user.id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User configuration not found.",
        )

    # Check if wallet is configured (required for ALL users on central or local nodes)
    settings = dict(config.exchange_settings or {})
    mining_node_uuid = (
        (settings.get("bybit") or {}).get("mining_node_uuid")
        or (settings.get("okx") or {}).get("mining_node_uuid")
        or (settings.get("weex") or {}).get("mining_node_uuid")
        or (settings.get("binance") or {}).get("mining_node_uuid")
        or settings.get("mining_node_uuid")
    )
    raw_sec = (
        (settings.get("bybit") or {}).get("mining_node_secret")
        or (settings.get("okx") or {}).get("mining_node_secret")
        or (settings.get("weex") or {}).get("mining_node_secret")
        or (settings.get("binance") or {}).get("mining_node_secret")
        or settings.get("mining_node_secret")
    )
    mining_node_secret = security.decrypt_node_secret(raw_sec)
    wallet_configured = (
        (settings.get("bybit") or {}).get("wallet_configured", False)
        or (settings.get("okx") or {}).get("wallet_configured", False)
        or (settings.get("weex") or {}).get("wallet_configured", False)
        or (settings.get("binance") or {}).get("wallet_configured", False)
        or settings.get("wallet_configured", False)
    )

    if not mining_node_uuid or not wallet_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="WALLET_REQUIRED",
        )

    is_central = os.getenv("IS_CENTRAL_HUB", "false").lower() == "true"
    if is_central and current_user.role != "admin":
        from sqlalchemy import update

        config.is_mining_enabled = True

        # We must explicitly flush so that the boolean is_mining_enabled is saved.
        await db.commit()

        # Now update notifications via direct query to avoid SQLAlchemy JSON tracking bugs
        notifications = dict(config.notifications or {})
        notifications["shareTelemetry"] = True
        await db.execute(
            update(models.AppConfig)
            .where(models.AppConfig.user_id == current_user.id)
            .values(notifications=notifications)
        )
        await db.commit()

        # The wallet-derived node is the user's mining node.
        node_uuid = mining_node_uuid
        node_name = f"DepthSightNode-{node_uuid[:8]}"

        stmt = select(models.HubNode).where(models.HubNode.node_uuid == node_uuid)
        res = await db.execute(stmt)
        db_node = res.scalars().first()

        if not db_node:
            referrer_node_uuid = await _resolve_safe_referrer_node_uuid(
                db, current_user, node_uuid
            )

            db_node = models.HubNode(
                node_uuid=node_uuid,
                name=node_name,
                secret_hash="",
                node_referral_code=current_user.referral_code,
                referrer_node_uuid=referrer_node_uuid,
                total_mined=0.0,
                has_welcome_bonus=False,
            )
            db.add(db_node)
            await db.commit()
            await db.refresh(db_node)

        # Bind a strong, non-deterministic secret to the wallet node so it can
        # authenticate telemetry.
        await _ensure_node_secret(db, current_user.id, settings, node_uuid, db_node)

        if payload.referrer_code:
            from ..hub_router import _bind_referrer_once

            await _bind_referrer_once(db, db_node, payload.referrer_code)
            await db.commit()

        # Auto-resolve and save Weex, OKX, and Bybit UIDs
        resolved_uid = await auto_resolve_weex_uid(db, current_user.id)
        if resolved_uid:
            db_node.weex_uid = resolved_uid
        resolved_okx = await auto_resolve_okx_uid(db, current_user.id)
        if resolved_okx:
            db_node.okx_uid = resolved_okx
        resolved_bybit = await auto_resolve_bybit_uid(db, current_user.id)
        if resolved_bybit:
            db_node.bybit_uid = resolved_bybit
        if resolved_uid or resolved_okx or resolved_bybit:
            await db.commit()

        return await get_local_mining_status(db=db, current_user=current_user)

    # 1. Update local AppConfig to enable mining
    config.is_mining_enabled = True
    if not config.notifications:
        config.notifications = {}
    # Force dict copy to trigger SQLAlchemy JSON mutation tracking
    notifications = dict(config.notifications)
    notifications["shareTelemetry"] = True
    config.notifications = notifications

    # 2. Check if identity exists (physical node)
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
        except Exception:
            pass

    # 3. If physical identity doesn't exist, create fallback physical ID
    if not node_uuid or not node_secret:
        node_uuid = str(uuid.uuid4())
        node_secret = secrets.token_hex(32)
        node_name = f"DepthSightNode-{node_uuid[:8]}"

    if not mining_node_secret:
        mining_node_secret = node_secret

    await db.commit()

    # 4. Register or Update node on Central Hub
    hub_url = get_federation_hub_url()
    hub_url = hub_url.rstrip("/")

    local_weex_uid = await auto_resolve_weex_uid(db, current_user.id)
    local_okx_uid = await auto_resolve_okx_uid(db, current_user.id)
    local_bybit_uid = await auto_resolve_bybit_uid(db, current_user.id)

    # Use the user's seed-derived mining_node_uuid & mining_node_secret for registration and attribution
    # A local-node admin activates mining for the whole server: their wallet node is the
    # server's mining node, so it is flagged as a mining server (receives commissions).
    is_server_admin = (not is_central) and current_user.role == "admin"
    reg_payload = {
        "node_uuid": mining_node_uuid,
        "name": f"DepthSightNode-{mining_node_uuid[:8]}",
        "node_secret": mining_node_secret,
        "version": "1.0.0",
        "referrer_code": payload.referrer_code,
        "weex_uid": local_weex_uid,
        "okx_uid": local_okx_uid,
        "bybit_uid": local_bybit_uid,
        "is_mining_server": is_server_admin,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{hub_url}/nodes/register", json=reg_payload, timeout=5.0
            ) as resp:
                if resp.status in (200, 201):
                    logger.info(
                        "Node successfully registered/updated on Hub during activation."
                    )
                    # Persist the server's mining identity so bot telemetry can stamp
                    # source_node_uuid (bots don't know the admin account).
                    if is_server_admin and mining_node_uuid:
                        srv_identity_path = Path("/app/data/server_identity.json")
                        if not srv_identity_path.parent.exists():
                            srv_identity_path = Path("server_identity.json")
                        try:
                            with open(srv_identity_path, "w") as f:
                                json.dump(
                                    {
                                        "node_uuid": mining_node_uuid,
                                        "node_secret": mining_node_secret,
                                    },
                                    f,
                                )
                        except Exception as e:
                            logger.error(f"Failed to write server identity file: {e}")
                    # Write/update the physical identity file ONLY when no wallet is
                    # configured. With a wallet, the wallet-derived mining identity is
                    # preferred everywhere and a random physical id would only break
                    # telemetry auth/attribution.
                    if not mining_node_uuid:
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
                        f"Failed to register node on Hub. Status: {resp.status}, Body: {err_text}"
                    )
    except Exception as e:
        logger.error(f"Connection error to Hub during mining activation: {e}")

    # 5. Fetch updated stats from Hub to return
    headers = {
        "X-Node-UUID": mining_node_uuid,
        "X-Node-Secret": mining_node_secret,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{hub_url}/mining/status", headers=headers, timeout=5.0
            ) as resp:
                if resp.status == 200:
                    hub_data = await resp.json()
                    return await format_mining_status_response(
                        db=db,
                        current_user=current_user,
                        is_enabled=True,
                        node_uuid=mining_node_uuid,
                        node_name=node_name,
                        hub_data=hub_data,
                        registered=True,
                    )
    except Exception as e:
        logger.error(f"Failed to retrieve mining stats from Hub: {e}")

    return await format_mining_status_response(
        db=db,
        current_user=current_user,
        is_enabled=True,
        node_uuid=mining_node_uuid,
        node_name=node_name,
        hub_data=None,
        registered=True,
    )


@config_router.get(
    "/mining/node-config",
    response_model=schemas.ApiResponseData[schemas.NodeMiningConfigUpdate],
    summary="Get node-wide mining configuration (Admin only)",
)
async def get_node_mining_config_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    from sqlalchemy import select

    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required.",
        )
    result = await db.execute(
        select(models.NodeMiningConfig).where(models.NodeMiningConfig.id == 1)
    )
    config = result.scalar_one_or_none()
    if not config:
        config = models.NodeMiningConfig(
            id=1, is_global_mining_enabled=False, user_reward_share_percent=75.0
        )
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return {"data": config}


@config_router.put(
    "/mining/node-config",
    response_model=schemas.ApiResponseData[schemas.NodeMiningConfigUpdate],
    summary="Update node-wide mining configuration (Admin only)",
)
async def update_node_mining_config_endpoint(
    payload: schemas.NodeMiningConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    from sqlalchemy import select

    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required.",
        )
    result = await db.execute(
        select(models.NodeMiningConfig).where(models.NodeMiningConfig.id == 1)
    )
    config = result.scalar_one_or_none()
    if not config:
        config = models.NodeMiningConfig(id=1)
        db.add(config)

    config.is_global_mining_enabled = payload.is_global_mining_enabled
    config.user_reward_share_percent = payload.user_reward_share_percent
    await db.commit()
    await db.refresh(config)
    return {"data": config}


@config_router.post(
    "/mining/deactivate",
    response_model=schemas.ApiResponseData[dict],
    summary="Deactivate local node mining and disable telemetry",
)
async def deactivate_local_mining(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    from sqlalchemy import update
    from sqlalchemy.orm.attributes import flag_modified

    config = await crud.get_config_model(db, current_user.id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User configuration not found.",
        )

    config.is_mining_enabled = False

    notifications = dict(config.notifications or {})
    notifications["shareTelemetry"] = False
    config.notifications = notifications
    flag_modified(config, "notifications")

    await db.execute(
        update(models.AppConfig)
        .where(models.AppConfig.user_id == current_user.id)
        .values(is_mining_enabled=False, notifications=notifications)
    )
    await db.commit()
    await db.refresh(config)

    return {"data": {"success": True, "message": "Mining and telemetry deactivated"}}


@config_router.post(
    "/mining/admin/import-bybit-xlsx",
    summary="Upload Bybit Broker XLSX Export and apply verified reports (Central Hub Admin only)",
)
async def import_bybit_xlsx_endpoint(
    file: UploadFile = File(...),
    dry_run: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    import os

    is_central = os.getenv("IS_CENTRAL_HUB", "false").lower() == "true"
    if not is_central:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation is only available on the Central Hub.",
        )
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required.",
        )
    if not file.filename or not file.filename.endswith((".xlsx", ".csv")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Please upload an .xlsx file from Bybit Broker Dashboard.",
        )
    try:
        contents = await file.read()
        from scripts.import_bybit_xlsx import (
            parse_bybit_xlsx,
            apply_bybit_records_session,
        )

        records = parse_bybit_xlsx(contents)
        if not records:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No readable transaction records found in the uploaded file.",
            )
        stats = await apply_bybit_records_session(db, records, dry_run=dry_run)
        return {
            "data": {
                "success": True,
                "stats": stats,
                "message": f"Successfully processed {len(records)} records across dates: {', '.join(stats.get('dates_processed', []))}",
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[BYBIT_XLSX_IMPORT] Error processing file: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process Bybit XLSX file: {str(e)}",
        )
