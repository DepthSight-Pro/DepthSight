import logging
import os
import requests

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..redis_client import get_redis_client
from ..plans import plans_config

logger = logging.getLogger(__name__)

# --- Payments Router ---
payments_router = APIRouter(
    prefix="/api/v1/payments",
    tags=["Payments"],
    dependencies=[Depends(get_current_user)],
)


@payments_router.get("/plans")
async def get_plans(db: AsyncSession = Depends(get_db)):
    """
    Get a list of all available plans from the config file.
    """
    try:
        from ..depthsight_api import _get_lifetime_slots_for_plan

        all_plans = plans_config.get_all_plans()
        billing_mode = plans_config.get_billing_mode()
        # Convert to required format
        response_plans = []
        for key, config in all_plans.items():
            effective_price = plans_config.get_effective_plan_price(key)
            plan_billing = plans_config.get_plan_billing(key, billing_mode)
            is_lifetime_offer = billing_mode == "lifetime" and plan_billing.get(
                "enabled", False
            )
            slots = (
                await _get_lifetime_slots_for_plan(db, key, config)
                if is_lifetime_offer
                else None
            )
            response_plans.append(
                {
                    "key": key,
                    "name": config.get("name", "Unnamed Plan"),
                    "price_usd": effective_price,
                    "active": config.get("active", False),
                    "billing_mode": billing_mode,
                    "period_label": "lifetime" if is_lifetime_offer else "month",
                    "slots": slots,
                    "description": config.get("description", ""),
                    "features": config.get("features", []),
                }
            )
        return response_plans
    except Exception as e:
        logger.error(f"Failed to load plans from config: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Could not load plans configuration."
        )


@payments_router.post("/create")
async def create_payment(
    request: schemas.CreatePaymentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """
    Creates a payment invoice via Bitcart.
    """
    from ..depthsight_api import _get_lifetime_slots_for_plan

    plan_name = request.plan_name
    plan_config = plans_config.get_plan(plan_name)

    if not plan_config or not plan_config.get("active", False):
        raise HTTPException(status_code=400, detail="Plan not found or is not active.")

    billing_mode = plans_config.get_billing_mode()
    price_usd = plans_config.get_effective_plan_price(plan_name)
    if billing_mode == "lifetime":
        lifetime_slots = await _get_lifetime_slots_for_plan(db, plan_name, plan_config)
        if lifetime_slots and lifetime_slots["available"] <= 0:
            raise HTTPException(
                status_code=409, detail="No lifetime seats available for this plan."
            )

    # 1. Create a payment record in our DB
    payment = await crud.create_payment(
        db, user_id=current_user.id, plan_name=plan_name, amount_usd=price_usd
    )
    await db.commit()
    await db.refresh(payment)

    # 2. Request to Bitcart
    try:
        bitcart_api_url = os.getenv(
            "BITCART_API_URL"
        )  # e.g. https://app.depthsight.pro/bitcart-api
        bitcart_api_key = os.getenv("BITCART_API_KEY")
        bitcart_store_id = os.getenv("BITCART_STORE_ID")
        frontend_url = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")

        if not bitcart_api_url or not bitcart_api_key or not bitcart_store_id:
            logger.error(
                "Bitcart configuration (URL, API_KEY, or STORE_ID) is missing."
            )
            raise ValueError("Payment provider is not configured.")

        headers = {
            "Authorization": f"Bearer {bitcart_api_key}",
            "Content-Type": "application/json",
        }

        # Use the actual external API URL for webhooks so Bitcart can reach us
        api_base_url = os.getenv("API_BASE_URL", "https://app.depthsight.pro/api/v1")

        payload = {
            "price": float(price_usd),
            "store_id": bitcart_store_id,
            "order_id": str(payment.id),
            "notification_url": f"{api_base_url}/webhooks/bitcart",
            "redirect_url": f"{frontend_url}/account?payment=success",
            "buyer_email": current_user.email,
        }

        logger.info(
            f"Creating Bitcart invoice for payment {payment.id} with payload: {payload}"
        )

        # Bitcart endpoint to create an invoice
        response = requests.post(
            f"{bitcart_api_url.rstrip('/')}/invoices",
            headers=headers,
            json=payload,
            timeout=60,  # Increased timeout for address generation
        )

        if response.status_code >= 400:
            logger.error(
                f"Bitcart API Error. Status: {response.status_code}. Response: {response.text}"
            )

        response.raise_for_status()

        data = response.json()
        bitcart_invoice_id = data.get("id")

        if not bitcart_invoice_id:
            logger.error(f"Could not find 'id' in Bitcart response: {data}")
            raise HTTPException(
                status_code=500,
                detail="Failed to parse response from payment provider.",
            )

        await crud.update_payment_with_bitcart_id(
            db, payment_id=payment.id, bitcart_id=str(bitcart_invoice_id)
        )
        await db.commit()

        # Extract payment details from the Bitcart invoice response
        payments = data.get("payments", [])
        payment_address = None
        payment_url = None  # bitcoin: URI for QR code
        amount_crypto = None
        currency_crypto = None

        if payments:
            first_payment = payments[0]
            payment_address = first_payment.get("payment_address")
            payment_url = first_payment.get("payment_url")
            amount_crypto = first_payment.get("amount")
            currency_crypto = first_payment.get("currency", "BTC")

        return {
            "invoice_id": bitcart_invoice_id,
            "invoice_url": f"{bitcart_api_url.rstrip('/')}/invoices/{bitcart_invoice_id}",
            "payment_address": payment_address,
            "payment_url": payment_url,
            "amount": amount_crypto,
            "currency": currency_crypto,
            "price_usd": float(price_usd),
            "expiration_seconds": data.get("expiration_seconds", 900),
            "status": data.get("status", "pending"),
            "payments": data.get("payments", []),
        }

    except requests.RequestException as e:
        logger.error(f"Bitcart API request failed: {e}")
        await crud.update_payment_status(db, payment_id=payment.id, status="FAILED")
        await db.commit()
        raise HTTPException(
            status_code=502, detail="Failed to communicate with payment provider."
        )

    except Exception as e:
        logger.error(f"Error creating payment via Bitcart: {e}", exc_info=True)
        await crud.update_payment_status(db, payment_id=payment.id, status="FAILED")
        await db.commit()
        raise HTTPException(status_code=500, detail="An internal error occurred.")


@payments_router.get("/check/{invoice_id}")
async def check_payment_status(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Manually checks payment status with Bitcart and activates subscription if paid.
    Used for frontend polling to avoid relying on webhooks.
    """
    try:
        from ..depthsight_api import (
            _get_payment_plan_expires_at,
            _sync_live_runtime_for_plan_change,
        )

        bitcart_api_url = os.getenv("BITCART_API_URL", "http://bitcart_api:8000")
        bitcart_api_key = os.getenv("BITCART_API_KEY")

        headers = {}
        if bitcart_api_key:
            headers["Authorization"] = f"Bearer {bitcart_api_key}"

        # Get invoice details from Bitcart
        response = requests.get(
            f"{bitcart_api_url.rstrip('/')}/invoices/{invoice_id}",
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        bitcart_status = data.get("status")
        normalized_status = str(bitcart_status or "").strip().lower()
        logger.info(f"Checking status for invoice {invoice_id}: {bitcart_status}")

        # If paid, trigger the same logic as webhook would
        if normalized_status in {
            "complete",
            "completed",
            "confirmed",
            "finished",
            "paid",
        }:
            # Find the payment in our DB
            payment = await crud.get_payment_by_bitcart_id(db, bitcart_id=invoice_id)
            if not payment:
                logger.warning(
                    f"Bitcart polling for unknown invoice_id '{invoice_id}'."
                )
                raise HTTPException(status_code=404, detail="Payment not found.")
            if payment.user_id != current_user.id:
                logger.warning(
                    "User %s attempted to poll invoice %s owned by user %s.",
                    current_user.id,
                    invoice_id,
                    payment.user_id,
                )
                raise HTTPException(
                    status_code=403, detail="Payment does not belong to current user."
                )

            if payment.status not in {"FINISHED", "COMPLETED"}:
                # Update status and activate subscription
                await crud.update_payment_status(
                    db, payment_id=payment.id, status="FINISHED"
                )

                # Activate plan
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
                await crud.create_commission_for_payment(db, payment)
                await db.commit()

                try:
                    await _sync_live_runtime_for_plan_change(
                        redis_client=redis_client,
                        db=db,
                        user_id=user.id,
                        previous_plan=previous_plan,
                        new_plan=payment.plan_name,
                    )
                except Exception as exc:
                    logger.error(
                        "Failed to sync live runtime after payment polling for user_id=%s: %s",
                        user.id,
                        exc,
                        exc_info=True,
                    )

                return {"status": "completed", "message": "Subscription activated!"}

            return {"status": "completed", "message": "Already processed."}

        if normalized_status in {
            "expired",
            "invalid",
            "failed",
            "cancelled",
            "canceled",
        }:
            payment = await crud.get_payment_by_bitcart_id(db, bitcart_id=invoice_id)
            if (
                payment
                and payment.status == "PENDING"
                and payment.user_id == current_user.id
            ):
                terminal_status = (
                    "EXPIRED" if normalized_status == "expired" else "FAILED"
                )
                await crud.update_payment_status(
                    db, payment_id=payment.id, status=terminal_status
                )
                await db.commit()

        return {
            "status": normalized_status or "unknown",
            "message": f"Payment is {bitcart_status}",
        }

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error checking payment status: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
