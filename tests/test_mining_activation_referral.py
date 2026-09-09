import pytest
from sqlalchemy import select
from api import models, schemas
from api.routes.config import activate_local_mining, format_mining_status_response
from api.hub_router import register_hub_node


def test_mining_activate_payload_case_compatibility():
    """Verify MiningActivatePayload parses both camelCase and snake_case."""
    p1 = schemas.MiningActivatePayload.model_validate({"referrerCode": "DSN-REF-1234"})
    assert p1.referrer_code == "DSN-REF-1234"

    p2 = schemas.MiningActivatePayload.model_validate({"referrer_code": "DSN-REF-5678"})
    assert p2.referrer_code == "DSN-REF-5678"

    p3 = schemas.MiningActivatePayload(referrer_code="DSN-REF-9999")
    assert p3.referrer_code == "DSN-REF-9999"


@pytest.mark.asyncio
async def test_activate_mining_links_user_and_node_referrer(db_session, monkeypatch):
    """
    When a user registered without a referral code enters a referrer code upon
    mining activation, both HubNode.referrer_node_uuid and User.referred_by_user_id
    must be linked.
    """
    monkeypatch.setenv("IS_CENTRAL_HUB", "true")

    # 1. Create referrer user and referrer node
    inviter = models.User(
        username="inviter_user",
        email="inviter@test.com",
        hashed_password="pw",
        referral_code="REF-INVITER-1",
        is_active=True,
    )
    db_session.add(inviter)
    await db_session.commit()
    await db_session.refresh(inviter)

    inviter_node = models.HubNode(
        node_uuid="inviter-node-uuid-1111",
        name="InviterNode",
        secret_hash="secret1",
        node_referral_code=inviter.referral_code,
        total_mined=0.0,
    )
    db_session.add(inviter_node)
    await db_session.commit()

    # 2. Create invitee user (registered without referral link)
    invitee = models.User(
        username="invitee_user",
        email="invitee@test.com",
        hashed_password="pw",
        referral_code="REF-INVI-2",
        referred_by_user_id=None,
        is_active=True,
    )
    db_session.add(invitee)
    await db_session.commit()
    await db_session.refresh(invitee)

    wallet_uuid = "invitee-wallet-node-uuid-2222"
    invitee_config = models.AppConfig(
        user_id=invitee.id,
        risk_management={},
        notifications={},
        data_sources={},
        exchange_settings={
            "mining_node_uuid": wallet_uuid,
            "mining_node_secret": "encrypted_dummy",
            "wallet_configured": True,
        },
    )
    db_session.add(invitee_config)
    await db_session.commit()

    node_cfg = models.NodeMiningConfig(
        id=1, is_global_mining_enabled=True, user_reward_share_percent=75.0
    )
    db_session.add(node_cfg)
    await db_session.commit()

    # Monkeypatch node secret decryption and redis to avoid socket timeouts
    from unittest.mock import AsyncMock
    from api import security

    monkeypatch.setattr(security, "decrypt_node_secret", lambda s: "decrypted_secret")
    monkeypatch.setattr(
        "api.redis_client.get_redis_client", AsyncMock(return_value=AsyncMock())
    )

    # 3. Activate mining with camelCase referrerCode
    payload = schemas.MiningActivatePayload.model_validate(
        {"referrerCode": inviter.referral_code}
    )
    res = await activate_local_mining(
        payload=payload,
        db=db_session,
        current_user=invitee,
    )

    assert res["data"].is_mining_enabled is True

    # 4. Check HubNode has referrer_node_uuid set to inviter's node
    node_res = await db_session.execute(
        select(models.HubNode).where(models.HubNode.node_uuid == wallet_uuid)
    )
    invitee_node = node_res.scalars().first()
    assert invitee_node is not None
    assert invitee_node.referrer_node_uuid == inviter_node.node_uuid

    # 5. Check User has referred_by_user_id set to inviter.id
    user_res = await db_session.execute(
        select(models.User).where(models.User.id == invitee.id)
    )
    updated_invitee = user_res.scalars().first()
    assert updated_invitee.referred_by_user_id == inviter.id


@pytest.mark.asyncio
async def test_register_node_allows_initial_referrer_for_wallet_node(
    db_session, monkeypatch
):
    """
    A wallet node that currently has NO referrer (referrer_node_uuid is None)
    must be permitted to bind its initial referrer via /nodes/register.
    """
    # 1. Create referrer node
    ref_node = models.HubNode(
        node_uuid="ref-node-uuid-root",
        name="RefNodeRoot",
        secret_hash="hash1",
        node_referral_code="DSN-REF-ROOT",
    )
    db_session.add(ref_node)
    await db_session.commit()

    # 2. Pre-create wallet node without referrer (e.g. created when wallet was linked)
    wallet_uuid = "wallet-node-no-ref-1234"
    wallet_addr = "0x1111111111111111111111111111111111111111"
    import hashlib

    existing_node = models.HubNode(
        node_uuid=wallet_uuid,
        name="WalletNode",
        secret_hash=hashlib.sha256(b"secret_abc").hexdigest(),
        wallet_address=wallet_addr,
        referrer_node_uuid=None,  # Not yet linked
    )
    db_session.add(existing_node)
    await db_session.commit()

    # 3. Simulate registration payload from local node during mining activation
    # (no owner_signature provided)
    class DummyRequest:
        client = None
        headers = {}

    reg_payload = schemas.HubNodeRegister(
        node_uuid=wallet_uuid,
        name="WalletNode",
        node_secret="secret_abc",
        referrer_code="DSN-REF-ROOT",
    )

    reg_res = await register_hub_node(
        node_in=reg_payload,
        request=DummyRequest(),
        db=db_session,
    )
    assert reg_res["status"] == "success"

    # 4. Verify node now has the referrer bound
    await db_session.refresh(existing_node)
    assert existing_node.referrer_node_uuid == ref_node.node_uuid

    # 5. Verify re-binding to a different referrer is blocked
    other_ref_node = models.HubNode(
        node_uuid="other-ref-node-uuid",
        name="OtherRef",
        secret_hash="hash3",
        node_referral_code="DSN-REF-OTHER",
    )
    db_session.add(other_ref_node)
    await db_session.commit()

    rebind_payload = schemas.HubNodeRegister(
        node_uuid=wallet_uuid,
        name="WalletNode",
        node_secret="secret_abc",
        referrer_code="DSN-REF-OTHER",
    )

    # Rebinding must fail or not overwrite the original referrer
    try:
        await register_hub_node(
            node_in=rebind_payload,
            request=DummyRequest(),
            db=db_session,
        )
    except Exception:
        pass

    await db_session.refresh(existing_node)
    # Must remain bound to original referrer!
    assert existing_node.referrer_node_uuid == ref_node.node_uuid


@pytest.mark.asyncio
async def test_format_mining_status_resolves_referrer_code_fallback(
    db_session, monkeypatch
):
    """
    format_mining_status_response should populate referrer_referral_code even
    if referred_by_user_id is None, provided referrer_node_uuid exists in Hub.
    """
    monkeypatch.setenv("IS_CENTRAL_HUB", "true")

    ref_node = models.HubNode(
        node_uuid="fallback-ref-uuid-5555",
        name="FallbackRef",
        secret_hash="dummy",
        node_referral_code="DSN-REF-FOUND",
    )
    db_session.add(ref_node)

    user = models.User(
        username="fallback_user",
        email="fb@test.com",
        hashed_password="pw",
        referral_code="REF-FB-USER",
        referred_by_user_id=None,
    )
    db_session.add(user)
    await db_session.commit()

    resp = await format_mining_status_response(
        db=db_session,
        current_user=user,
        is_enabled=True,
        node_uuid="my-node-uuid",
        node_name="MyNode",
        hub_data={"referrerNodeUuid": ref_node.node_uuid},
        registered=True,
    )

    data = resp["data"]
    assert data.referrer_referral_code == "DSN-REF-FOUND"
    assert data.referrer_node_uuid == ref_node.node_uuid
