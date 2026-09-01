import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from api import crud, models


@pytest.mark.asyncio
async def test_referral_bonus_lifecycle(db_session):
    # 1. Create referrer
    referrer_schema = crud.schemas.UserCreate(
        username="bonus_referrer",
        email="referrer_bonus@example.com",
        password="password123",
    )
    referrer = await crud.create_user(db_session, referrer_schema)

    # 2. Create referred user
    referred_schema = crud.schemas.UserCreate(
        username="bonus_referred",
        email="referred_bonus@example.com",
        password="password123",
    )
    referred = await crud.create_user(db_session, referred_schema)
    referred.referred_by_user_id = referrer.id
    db_session.add(referred)
    await db_session.commit()

    # 3. Create pending bonuses
    await crud.create_pending_bonuses_for_referral(
        db_session, referrer_id=referrer.id, referred_id=referred.id
    )
    await db_session.commit()

    # Verify pending bonuses in DB
    referrer_bonuses = (
        (
            await db_session.execute(
                select(models.Bonus).filter_by(user_id=referrer.id, status="pending")
            )
        )
        .scalars()
        .all()
    )
    assert len(referrer_bonuses) == 1
    assert referrer_bonuses[0].quantity == 50
    assert referrer_bonuses[0].source_user_id == referred.id

    referred_bonuses = (
        (
            await db_session.execute(
                select(models.Bonus).filter_by(user_id=referred.id, status="pending")
            )
        )
        .scalars()
        .all()
    )
    assert len(referred_bonuses) == 1
    assert referred_bonuses[0].quantity == 25

    # 4. Activate bonuses when referred user activates
    await crud.activate_referral_bonuses(db_session, referred_user_id=referred.id)
    await db_session.commit()

    await db_session.refresh(referrer_bonuses[0])
    await db_session.refresh(referred_bonuses[0])
    assert referrer_bonuses[0].status == "active"
    assert referred_bonuses[0].status == "active"

    # 5. Consume bonus
    consumed = await crud.get_and_consume_bonus(
        db_session, user_id=referred.id, feature_name="run_backtest"
    )
    assert consumed is True
    await db_session.refresh(referred_bonuses[0])
    assert referred_bonuses[0].quantity == 24


@pytest.mark.asyncio
async def test_affiliate_commission_and_payout_lifecycle(db_session):
    # 1. Create an affiliate user
    affiliate_schema = crud.schemas.UserCreate(
        username="test_affiliate", email="affiliate@example.com", password="password123"
    )
    affiliate = await crud.create_user(db_session, affiliate_schema)
    affiliate.role = "affiliate"
    affiliate.affiliate_commission_rate = 0.50
    affiliate.payout_address = "TX1234567890TRC20Address"
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

    # 3. Create a Payment for the referred user ($100)
    payment = models.Payment(
        user_id=referred_user.id, plan_name="pro", amount_usd=100.0, status="FINISHED"
    )
    db_session.add(payment)
    await db_session.commit()

    now = datetime.now(timezone.utc)

    # 4. Create Commission with past hold date -> should become available
    comm = models.Commission(
        affiliate_user_id=affiliate.id,
        referred_user_id=referred_user.id,
        source_payment_id=payment.id,
        commission_amount_usd=50.0,
        status="pending",
        becomes_available_at=now - timedelta(days=1),
    )
    db_session.add(comm)
    await db_session.commit()

    # 5. Run the update task logic
    updated_count = await crud.update_commission_statuses(db_session)
    await db_session.commit()
    assert updated_count == 1

    await db_session.refresh(comm)
    assert comm.status == "available"

    # 6. Request Payout
    payout = await crud.create_payout_request(db_session, user_id=affiliate.id)
    assert payout is not None
    assert payout.amount == 50.0
    assert payout.status == "pending"
    assert payout.payout_address == "TX1234567890TRC20Address"

    await db_session.refresh(comm)
    assert comm.status == "processing"
    assert comm.payout_id == payout.id

    # 7. Check user payouts history
    user_payouts, total_p = await crud.get_payouts_for_user(
        db_session, user_id=affiliate.id
    )
    assert total_p == 1
    assert user_payouts[0].id == payout.id

    # 8. Admin processes payout (marks as paid with TXID)
    processed = await crud.admin_process_payout(
        db_session,
        payout_id=payout.id,
        status="paid",
        transaction_id="0xabcdef1234567890txhash",
    )
    assert processed.status == "paid"
    assert processed.transaction_id == "0xabcdef1234567890txhash"
    assert processed.processed_at is not None

    await db_session.refresh(comm)
    assert comm.status == "paid"


@pytest.mark.asyncio
async def test_affiliate_payout_rejection(db_session):
    # 1. Create affiliate
    affiliate_schema = crud.schemas.UserCreate(
        username="test_affiliate_rej",
        email="affiliate_rej@example.com",
        password="password123",
    )
    affiliate = await crud.create_user(db_session, affiliate_schema)
    affiliate.payout_address = "TX_Rejection_Address"
    db_session.add(affiliate)
    await db_session.commit()

    # 2. Create referred user and payment
    ref_schema = crud.schemas.UserCreate(
        username="ref_user_rej", email="ref_rej@example.com", password="password123"
    )
    ref_user = await crud.create_user(db_session, ref_schema)
    payment = models.Payment(
        user_id=ref_user.id, plan_name="pro", amount_usd=150.0, status="FINISHED"
    )
    db_session.add(payment)
    await db_session.commit()

    # 3. Create available commission
    comm = models.Commission(
        affiliate_user_id=affiliate.id,
        referred_user_id=ref_user.id,
        source_payment_id=payment.id,
        commission_amount_usd=60.0,
        status="available",
        becomes_available_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(comm)
    await db_session.commit()

    # 4. Request Payout
    payout = await crud.create_payout_request(db_session, user_id=affiliate.id)
    await db_session.refresh(comm)
    assert comm.status == "processing"

    # 5. Admin rejects payout
    rejected_payout = await crud.admin_process_payout(
        db_session, payout_id=payout.id, status="rejected"
    )
    assert rejected_payout.status == "rejected"

    # 6. Verify commission is reverted to available
    await db_session.refresh(comm)
    assert comm.status == "available"
    assert comm.payout_id is None


@pytest.mark.asyncio
async def test_payout_validation_checks(db_session):
    # User without payout address cannot request payout
    user_schema = crud.schemas.UserCreate(
        username="no_addr_user", email="no_addr@example.com", password="password123"
    )
    user = await crud.create_user(db_session, user_schema)
    assert user.payout_address is None

    with pytest.raises(
        ValueError, match="Please provide your USDT TRC-20 payout address"
    ):
        await crud.create_payout_request(db_session, user_id=user.id)

    # Set address, but no available commissions
    user.payout_address = "TX_Some_Address"
    db_session.add(user)
    await db_session.commit()

    with pytest.raises(ValueError, match="No available commissions for payout"):
        await crud.create_payout_request(db_session, user_id=user.id)


@pytest.mark.asyncio
async def test_default_user_commission_earning(db_session):
    referrer_schema = crud.schemas.UserCreate(
        username="normal_referrer",
        email="normal_ref@example.com",
        password="password123",
    )
    referrer = await crud.create_user(db_session, referrer_schema)
    assert referrer.role == "user"
    assert referrer.affiliate_commission_rate is None

    referred_schema = crud.schemas.UserCreate(
        username="referred_by_normal",
        email="referred_normal@example.com",
        password="password123",
    )
    referred_user = await crud.create_user(db_session, referred_schema)
    referred_user.referred_by_user_id = referrer.id
    db_session.add(referred_user)
    await db_session.commit()

    payment = models.Payment(
        user_id=referred_user.id, plan_name="pro", amount_usd=100.0, status="FINISHED"
    )
    db_session.add(payment)
    await db_session.commit()
    await db_session.refresh(payment)

    await crud.create_commission_for_payment(db_session, payment)
    await db_session.commit()

    comm_query = select(models.Commission).filter_by(affiliate_user_id=referrer.id)
    res = await db_session.execute(comm_query)
    commissions = res.scalars().all()

    assert len(commissions) == 1
    commission = commissions[0]
    assert commission.commission_amount_usd == 40.0
    assert commission.status == "pending"


@pytest.mark.asyncio
async def test_affiliate_and_admin_api_endpoints(
    pro_user, free_user, db_session, authenticated_client_factory
):
    pro_user.role = "admin"
    await db_session.commit()

    admin_client = await authenticated_client_factory(pro_user)
    user_client = await authenticated_client_factory(free_user)

    # 1. User updates payout address
    addr_res = await user_client.post(
        "/api/v1/affiliate/payout-details",
        json={"usdtTrc20Address": "TRC20_Test_Address_987"},
    )
    assert addr_res.status_code == 200

    # 2. Check dashboard stats includes the payout address
    dash_res = await user_client.get("/api/v1/affiliate/dashboard")
    assert dash_res.status_code == 200
    dash_data = dash_res.json()
    assert dash_data.get("payoutAddress") == "TRC20_Test_Address_987"

    # 3. Create a mock available commission for free_user
    payment = models.Payment(
        user_id=pro_user.id, plan_name="pro", amount_usd=200.0, status="FINISHED"
    )
    db_session.add(payment)
    await db_session.commit()

    comm = models.Commission(
        affiliate_user_id=free_user.id,
        referred_user_id=pro_user.id,
        source_payment_id=payment.id,
        commission_amount_usd=80.0,
        status="available",
        becomes_available_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(comm)
    await db_session.commit()

    # 4. User requests payout via API
    req_res = await user_client.post("/api/v1/affiliate/request-payout")
    assert req_res.status_code == 200

    # 5. User checks payouts list
    payouts_res = await user_client.get("/api/v1/affiliate/payouts")
    assert payouts_res.status_code == 200
    payouts_json = payouts_res.json()
    assert payouts_json["total"] == 1
    payout_id = payouts_json["payouts"][0]["id"]
    assert payouts_json["payouts"][0]["status"] == "pending"

    # 6. Admin lists payouts
    admin_payouts_res = await admin_client.get("/api/v1/admin/payouts")
    assert admin_payouts_res.status_code == 200
    admin_payouts_json = admin_payouts_res.json()
    assert admin_payouts_json["total"] >= 1

    # Non-admin cannot access admin payouts
    forbidden_res = await user_client.get("/api/v1/admin/payouts")
    assert forbidden_res.status_code == 403

    # 7. Admin processes payout (marks as paid)
    proc_res = await admin_client.post(
        f"/api/v1/admin/payouts/{payout_id}/process",
        json={"status": "paid", "transactionId": "TXHASH_123456"},
    )
    assert proc_res.status_code == 200
    proc_json = proc_res.json()
    assert proc_json["status"] == "paid"
    assert proc_json["transactionId"] == "TXHASH_123456"

    # Verify commission is marked paid in DB
    await db_session.refresh(comm)
    assert comm.status == "paid"
