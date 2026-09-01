import os
import json
import time
import hmac
import hashlib
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api import crud, models
from api.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


def get_node_identity() -> Tuple[Optional[str], Optional[str]]:
    """Reads auth_node_uuid and node_secret from identity files or environment."""
    auth_node_uuid = os.getenv("HUB_NODE_UUID")
    node_secret = os.getenv("HUB_NODE_SECRET")
    if auth_node_uuid and node_secret:
        return auth_node_uuid, node_secret

    for p_str in [
        "/app/data/node_identity.json",
        "node_identity.json",
        "/app/node_identity.json",
        "identity.json",
    ]:
        p = Path(p_str)
        if p.exists():
            try:
                with open(p, "r") as f:
                    data = json.load(f)
                    auth_node_uuid = data.get("node_uuid")
                    node_secret = data.get("node_secret")
                    if auth_node_uuid and node_secret:
                        return auth_node_uuid, node_secret
            except Exception as e:
                logger.error(
                    f"[telemetry_sync] Failed to read node identity file {p_str}: {e}"
                )

    return None, None


def get_hub_report_url() -> str:
    """Determines the full telemetry report endpoint URL on the central hub."""
    from api.federation import get_federation_hub_url

    url = get_federation_hub_url()
    if url.endswith("/api/v1/hub"):
        return f"{url}/telemetry/report"
    elif "/api/v1" in url:
        return f"{url}/hub/telemetry/report"
    else:
        return f"{url}/api/v1/hub/telemetry/report"


async def _identity_from_db(
    session: AsyncSession,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Fallback node identity resolved from the local DB: the wallet-derived
    mining identity of any configured user. Keeps offline delivery working
    after a wallet re-key, when env/file identities hold an outdated secret.
    """
    from sqlalchemy.future import select
    from api.security import decrypt_node_secret

    res = await session.execute(select(models.AppConfig).limit(200))
    for cfg in res.scalars().all():
        settings = (
            cfg.exchange_settings if isinstance(cfg.exchange_settings, dict) else {}
        )
        uuid_val = (
            (settings.get("bybit") or {}).get("mining_node_uuid")
            or (settings.get("okx") or {}).get("mining_node_uuid")
            or (settings.get("weex") or {}).get("mining_node_uuid")
            or (settings.get("binance") or {}).get("mining_node_uuid")
            or settings.get("mining_node_uuid")
        )
        raw_secret = (
            (settings.get("bybit") or {}).get("mining_node_secret")
            or (settings.get("okx") or {}).get("mining_node_secret")
            or (settings.get("weex") or {}).get("mining_node_secret")
            or (settings.get("binance") or {}).get("mining_node_secret")
            or settings.get("mining_node_secret")
        )
        secret_val = decrypt_node_secret(raw_secret)
        if uuid_val and secret_val:
            return str(uuid_val), str(secret_val)
    return None, None


def format_report_payload(report: models.HubTelemetryReport) -> Dict[str, Any]:
    """Converts a HubTelemetryReport database object to JSON payload dictionary."""
    return {
        "symbol": report.symbol,
        "direction": report.direction,
        "entryPrice": report.entry_price,
        "exitPrice": report.exit_price,
        "pnlPercent": report.pnl_percent,
        "tradeDurationSec": report.trade_duration_sec,
        "exitReason": report.exit_reason,
        "tradeMode": report.trade_mode,
        "strategyBlocks": report.strategy_blocks or [],
        "marketContext": report.market_context or {},
        "exchangeId": report.exchange_id,
        "marketType": report.market_type,
        "brokerTradeId": report.broker_trade_id,
        "entryBrokerTradeIds": report.entry_broker_trade_ids or [],
        "closeBrokerTradeIds": report.close_broker_trade_ids or [],
        "tradeVolumeUsdt": report.trade_volume_usdt,
        "attribution_node_uuid": report.node_uuid,
        "source_node_uuid": report.source_node_uuid,
    }


async def resync_pending_telemetry_reports(
    db: Optional[AsyncSession] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Scans local PostgreSQL DB for pending 'LOCAL_ONLY' telemetry reports
    and attempts to post them to the central hub. Marks successful reports as 'SENT'.
    Skips execution if IS_CENTRAL_HUB=true.
    """
    if os.getenv("IS_CENTRAL_HUB", "false").lower() == "true":
        return {"synced": 0, "total": 0, "reason": "is_central_hub"}

    auth_node_uuid, node_secret = get_node_identity()
    if (not auth_node_uuid or not node_secret) and db is not None:
        # env/file identity missing or stale -> wallet identity from the DB.
        auth_node_uuid, node_secret = await _identity_from_db(db)
    if (not auth_node_uuid or not node_secret) and db is None:
        async with AsyncSessionLocal() as ident_session:
            auth_node_uuid, node_secret = await _identity_from_db(ident_session)
    if not auth_node_uuid or not node_secret:
        logger.warning("[telemetry_sync] Node identity not found. Resync skipped.")
        return {"synced": 0, "total": 0, "reason": "no_node_identity"}

    report_url = get_hub_report_url()

    async def _process(session: AsyncSession) -> Dict[str, Any]:
        pending_reports = await crud.get_pending_local_telemetry_reports(
            session, limit=limit
        )
        if not pending_reports:
            return {"synced": 0, "total": 0, "reason": "queue_empty"}

        synced_count = 0
        async with httpx.AsyncClient(timeout=10.0) as client:
            for report in pending_reports:
                payload = format_report_payload(report)
                body_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
                signature = hmac.new(
                    node_secret.encode("utf-8"), body_bytes, hashlib.sha256
                ).hexdigest()

                headers = {
                    "X-Node-UUID": auth_node_uuid,
                    "X-Node-Secret": node_secret,
                    "X-Node-Signature": signature,
                    "X-Timestamp": str(int(time.time() * 1000)),
                    "Content-Type": "application/json",
                }

                try:
                    res = await client.post(
                        report_url, content=body_bytes, headers=headers
                    )
                    if res.status_code in (200, 201) or res.status_code == 409:
                        await crud.update_hub_telemetry_status(
                            session, report.id, status="SENT"
                        )
                        synced_count += 1
                        logger.info(
                            f"[telemetry_sync] Resynced telemetry report {report.id} -> SENT"
                        )
                    else:
                        logger.warning(
                            f"[telemetry_sync] Failed to resync report {report.id}. Status: {res.status_code}, Body: {res.text}"
                        )
                except Exception as exc:
                    logger.error(
                        f"[telemetry_sync] Error dispatching report {report.id}: {exc}"
                    )
                    break  # Stop batch processing if connection failed

        return {"synced": synced_count, "total": len(pending_reports)}

    if db is not None:
        return await _process(db)
    else:
        async with AsyncSessionLocal() as session:
            return await _process(session)
