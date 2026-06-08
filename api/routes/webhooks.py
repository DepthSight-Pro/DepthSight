import logging
import os
import json
import hmac
import hashlib
from typing import Dict, Any

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from ..database import get_db
from ..redis_client import get_redis_client

logger = logging.getLogger(__name__)

# --- Webhooks Router (No Auth) ---
webhooks_router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@webhooks_router.post("/bitcart")
async def bitcart_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Handles Instant Payment Notifications (IPN) from Bitcart.
    """
    from ..depthsight_api import (
        _get_payment_plan_expires_at,
        _sync_live_runtime_for_plan_change,
    )

    webhook_secret = os.getenv("BITCART_WEBHOOK_SECRET")
    if not webhook_secret:
        logger.error("BITCART_WEBHOOK_SECRET is not set. Cannot verify webhook.")
        raise HTTPException(status_code=500, detail="Webhook secret not configured.")

    # 1. Signature verification
    try:
        signature = request.headers.get("X-Bitcart-Signature")
        if not signature:
            logger.warning("Bitcart Webhook received without signature.")
            raise HTTPException(status_code=401, detail="Missing signature.")

        body = await request.body()
        h = hmac.new(webhook_secret.encode(), body, hashlib.sha256)
        expected_signature = h.hexdigest()

        if not hmac.compare_digest(expected_signature, signature):
            logger.warning("Bitcart Webhook received with invalid signature.")
            raise HTTPException(status_code=401, detail="Invalid signature.")

        data = json.loads(body)
        logger.info(f"Received valid webhook from Bitcart: {data}")

    except Exception as e:
        logger.error(f"Error during Bitcart webhook verification: {e}", exc_info=True)
        raise HTTPException(
            status_code=400, detail="Invalid request format or signature."
        )

    # 2. Data processing
    try:
        event = data.get("event")
        invoice_data = data.get("data", {})
        payment_id = invoice_data.get("order_id")

        # In Bitcart, the "finished" status corresponds to the "invoice_completed" event
        # There is also "invoice_confirmed" (after blockchain confirmations)
        if event not in ["invoice_completed", "invoice_confirmed"]:
            logger.info(f"Ignoring Bitcart event: {event}")
            return {"status": "ignored"}

        if not payment_id:
            raise HTTPException(
                status_code=400, detail="Missing order_id in Bitcart webhook payload."
            )

        # Find payment in our DB
        payment = await crud.get_payment_by_id(db, payment_id=payment_id)
        if not payment:
            logger.error(
                f"Bitcart Webhook for unknown payment_id '{payment_id}' received."
            )
            raise HTTPException(status_code=404, detail="Payment not found.")

        # Update status in our DB
        await crud.update_payment_status(db, payment_id=payment.id, status="FINISHED")

        # If the payment is successful, update the user subscription
        user = await db.get(models.User, payment.user_id)
        if not user:
            logger.error(
                f"User with id {payment.user_id} not found for successful payment {payment.id}"
            )
            raise HTTPException(status_code=404, detail="User not found.")

        previous_plan = user.plan
        await crud.update_user_plan(
            db,
            user_id=user.id,
            plan_name=payment.plan_name,
            expires_at=_get_payment_plan_expires_at(payment),
        )
        logger.info(f"User {user.id} plan updated to '{payment.plan_name}' via Bitcart")

        # --- AFFILIATE PROGRAM: Create commission for payment ---
        await crud.create_commission_for_payment(db, payment)

        await db.commit()

        try:
            await _sync_live_runtime_for_plan_change(
                redis_client=redis_client,
                db=db,
                user_id=user.id,
                previous_plan=previous_plan,
                new_plan=user.plan,
            )
        except Exception as exc:
            logger.error(
                "Failed to sync live runtime after successful payment for user_id=%s: %s",
                user.id,
                exc,
                exc_info=True,
            )
        return {"status": "ok"}

    except HTTPException as e:
        await db.rollback()
        raise e
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to process Bitcart webhook: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error processing webhook."
        )


@webhooks_router.post(
    "/tv/{user_secret_token}", response_model=schemas.ApiResponseData[Dict[str, Any]]
)
async def tradingview_webhook(
    user_secret_token: str,
    payload: schemas.TradingViewWebhookPayload,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    from ..depthsight_api import _queue_tradingview_signal_command

    user = await crud.get_user_by_tradingview_webhook_token(db, user_secret_token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook token."
        )

    result = await _queue_tradingview_signal_command(
        user=user,
        strategy_id=payload.strategy_id,
        action=payload.action,
        symbol=payload.symbol,
        api_key_id=payload.api_key_id,
        event_id=payload.event_id,
        sent_at=payload.sent_at,
        price=payload.price,
        timeframe=payload.timeframe,
        bar_time=payload.bar_time,
        metadata=payload.metadata,
        redis_client=redis_client,
        db=db,
        source="tradingview_webhook",
    )
    return {"data": result}


@webhooks_router.post(
    "/tv/{user_secret_token}/{strategy_id}",
    response_model=schemas.ApiResponseData[Dict[str, Any]],
)
async def tradingview_strategy_scoped_webhook(
    user_secret_token: str,
    strategy_id: str,
    payload: schemas.TradingViewStrategyScopedWebhookPayload,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    from ..depthsight_api import _queue_tradingview_signal_command

    user = await crud.get_user_by_tradingview_webhook_token(db, user_secret_token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook token."
        )

    if payload.strategy_id and payload.strategy_id != strategy_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="strategy_id in payload does not match the strategy-specific webhook URL.",
        )

    result = await _queue_tradingview_signal_command(
        user=user,
        strategy_id=strategy_id,
        action=payload.action,
        symbol=payload.symbol,
        api_key_id=payload.api_key_id,
        event_id=payload.event_id,
        sent_at=payload.sent_at,
        price=payload.price,
        timeframe=payload.timeframe,
        bar_time=payload.bar_time,
        metadata=payload.metadata,
        redis_client=redis_client,
        db=db,
        source="tradingview_webhook",
    )
    return {"data": result}
