import pytest
from datetime import datetime, timezone, timedelta
from api import crud, models


@pytest.mark.asyncio
async def test_affiliate_commission_lifecycle(db_session):
    # 1. Create an affiliate user
    affiliate_schema = crud.schemas.UserCreate(
        username="test_affiliate", email="affiliate@example.com", password="password123"
    )
    affiliate = await crud.create_user(db_session, affiliate_schema)
    affiliate.role = "affiliate"
    affiliate.affiliate_commission_rate = 0.20
    db_session.add(affiliate)
    await db_session.commit()

    # 2. Create a referred user
    referred_schema = crud.schemas.UserCreate(
        username="test_referred", email="referred@example.com", password="password123"
    )
    referred_user = await crud.create_user(db_session, referred_schema)
    referred_user.referred_by_user_id = affiliate.id
    db_session.add(referred_user)
    await db_session.commit()

    # 3. Create a Payment for the referred user
    payment = models.Payment(
        user_id=referred_user.id, plan_name="pro", amount_usd=100.0, status="FINISHED"
    )
    db_session.add(payment)
    await db_session.commit()
    await db_session.refresh(payment)

    now = datetime.now(timezone.utc)

    # 4. Create Commissions manually to simulate different states

    # Commission 1: Should become available (date in the past)
    comm_past = models.Commission(
        affiliate_user_id=affiliate.id,
        referred_user_id=referred_user.id,
        source_payment_id=payment.id,
        commission_amount_usd=20.0,
        status="pending",
        becomes_available_at=now - timedelta(days=1),
    )

    # Commission 2: Should stay pending (date in the future)
    comm_future = models.Commission(
        affiliate_user_id=affiliate.id,
        referred_user_id=referred_user.id,
        source_payment_id=payment.id,
        commission_amount_usd=20.0,
        status="pending",
        becomes_available_at=now + timedelta(days=1),
    )

    db_session.add_all([comm_past, comm_future])
    await db_session.commit()

    # 5. Run the update task logic
    updated_count = await crud.update_commission_statuses(db_session)
    await db_session.commit()

    assert updated_count == 1, "Only one commission should have been updated"

    # Refresh commissions
    await db_session.refresh(comm_past)
    await db_session.refresh(comm_future)

    assert comm_past.status == "available", "Past commission should be available"
    assert comm_future.status == "pending", "Future commission should remain pending"

    # 6. Test Request Payout logic
    await crud.create_payout_request(db_session, user_id=affiliate.id)

    # We no longer return a Payout model, we just update statuses
    # Let's verify the 'available' commission was marked as 'paid'

    await db_session.refresh(comm_past)
    await db_session.refresh(comm_future)

    assert comm_past.status == "paid", (
        "Available commission should have transitioned to paid"
    )
    assert comm_future.status == "pending", (
        "Pending commission should still be pending after payout request"
    )
